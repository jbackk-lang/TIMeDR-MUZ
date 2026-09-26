"""Przelewy (L3): MUZ przygotowuje tylko dane przelewu jako kod QR w standardzie 2D Zwiazku Bankow Polskich.

Format (rekomendacja ZBP 2D, 2013): NIP|PL|NRB|KWOTA|ODBIORCA|TYTUL|||
- NIP 10 cyfr (opcjonalny dla osob prywatnych), kraj "PL", rachunek 26 cyfr,
- kwota w groszach, 6 cyfr (maks. 9999,99 zl), odbiorca maks. 20 znakow, tytul maks. 32,
- calosc maks. 160 znakow, UTF-8, korekcja bledow L.
Przelew wykonuje uzytkownik w aplikacji banku, z silnym uwierzytelnieniem (SCA). MUZ niczego nie wysyla.
Obraz QR wymaga pakietu `segno` (czysty Python); bez niego zapisywany jest sam tekst danych.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..core.common import sha256_file, sha256_text
from .base import LOCAL, BaseExecutor


class QRDataError(ValueError):
    pass


def nrb_valid(nrb: str) -> bool:
    digits = re.sub(r"\s", "", nrb)
    if not re.fullmatch(r"\d{26}", digits):
        return False
    rearranged = digits[2:] + "2521" + digits[:2]  # "PL" -> 25 21
    return int(rearranged) % 97 == 1


def zbp_payload(*, nrb: str, amount_gr: int, name: str, title: str, nip: str = "") -> str:
    nrb = re.sub(r"\s", "", nrb)
    if not nrb_valid(nrb):
        raise QRDataError("niepoprawny numer rachunku (26 cyfr, suma kontrolna)")
    if not (0 < amount_gr <= 999_999):
        raise QRDataError("kwota poza zakresem standardu (1 gr - 9999,99 zl)")
    if nip and not re.fullmatch(r"\d{10}", nip):
        raise QRDataError("NIP musi miec 10 cyfr")
    for fld in (name, title):
        if "|" in fld:
            raise QRDataError("znak | jest separatorem i nie moze wystapic w polach")
    payload = f"{nip}|PL|{nrb}|{amount_gr:06d}|{name[:20]}|{title[:32]}|||"
    if len(payload) > 160:
        raise QRDataError("dane przekraczaja 160 znakow")
    return payload


class QRTransferExecutor(BaseExecutor):
    name = "qr"
    level = "L3"
    levels = ("L3",)
    allowed_hosts = frozenset({LOCAL})

    def __init__(self, trusted_public_key: bytes, outdir):
        super().__init__(trusted_public_key)
        self.outdir = Path(outdir)

    def _do(self, plan: dict) -> dict:
        c = plan["content"]
        payload = zbp_payload(nrb=c["nrb"], amount_gr=c["amount_gr"], name=c["name"], title=c["title"], nip=c.get("nip", ""))
        self.outdir.mkdir(parents=True, exist_ok=True)
        stem = f"{plan['plan_id'][:12]}_przelew"
        txt = self.outdir / f"{stem}.txt"
        txt.write_text(payload, encoding="utf-8")
        ev = {"payload_sha256": sha256_text(payload), "txt": txt.name,
              "note": "zeskanuj kod w aplikacji banku i zatwierdz przelew tam (SCA)"}
        try:
            import segno
            svg = self.outdir / f"{stem}.svg"
            segno.make(payload, error="l", micro=False).save(str(svg), scale=4)
            ev |= {"svg": svg.name, "svg_sha256": sha256_file(svg)}
        except ImportError:
            ev["svg"] = None
        return ev
