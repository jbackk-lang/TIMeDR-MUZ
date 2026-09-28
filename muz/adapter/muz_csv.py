"""Wlasny format CSV MUZ (muz.transakcje/1): jeden uklad dla wszystkich zrodel i dla recznych wpisow.

  data;kwota;waluta;kontrahent;opis;kategoria;saldo;zrodlo;id
  2026-09-01;-89,00;PLN;ORANGE POLSKA;Abonament;telekom;;reczne;

- separator ';', przecinek dziesietny, UTF-8 z BOM -- plik otwiera sie poprawnie w polskim Excelu,
- kwota ujemna = wydatek, dodatnia = wplyw; data RRRR-MM-DD (akceptowane tez DD.MM.RRRR),
- kategoria, saldo, zrodlo, id -- opcjonalne. Wiersz bez id dostaje id z hasha zawartosci.
Reczne wpisy (gotowka, rachunki spoza banku) dopisuje sie w Excelu do pliku z `python -m muz szablon`.
"""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

from .csv_import import (IBAN_RE, LSFRecord, _iban_hash, _read_text, counterparty_from_description, normalize_counterparty,
                         parse_amount_gr, parse_date)

HEADER = ["data", "kwota", "waluta", "kontrahent", "opis", "kategoria", "saldo", "zrodlo", "id"]
SCHEMA = "muz.transakcje/1"


def _zl(gr: int | None) -> str:
    return "" if gr is None else f"{gr / 100:.2f}".replace(".", ",")


def is_muz_csv(path) -> bool:
    try:
        first = _read_text(Path(path)).splitlines()[0]
    except (IndexError, ValueError, OSError):
        return False
    return [c.strip().lower() for c in first.split(";")][:5] == HEADER[:5]


def write_template(path) -> Path:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} juz istnieje -- nie nadpisuje")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(";".join(HEADER) + "\n", encoding="utf-8-sig", newline="")
    return path


def write_records(records: list[LSFRecord], path, categories: dict[str, str] | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cats = categories or {}
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(HEADER)
        for r in sorted(records, key=lambda r: (r.date, r.source, r.raw_hash)):
            w.writerow([r.date.isoformat(), _zl(r.amount_gr), r.currency, r.counterparty, r.description,
                        cats.get(r.counterparty, ""), _zl(r.balance_gr), r.source, r.raw_hash[:16]])
    return path


def load_muz_csv(path, salt: bytes) -> tuple[list[LSFRecord], dict[str, str]]:
    """Zwraca (rekordy, kategorie kontrahentow wpisane w pliku)."""
    path = Path(path)
    text = _read_text(path)
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    out, cats = [], {}
    for n, row in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if not row.get("data") and not row.get("kwota"):
            continue
        try:
            d = parse_date(row["data"])
            amt = parse_amount_gr(row["kwota"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{path.name}, wiersz {n}: {exc}") from None
        cp = normalize_counterparty(row.get("kontrahent", "")) or counterparty_from_description(row.get("opis", ""))
        desc = row.get("opis", "")
        raw = "|".join(f"{k}={row.get(k, '')}" for k in HEADER[:7])
        rid = row.get("id") or hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if row.get("kategoria"):
            cats[cp] = row["kategoria"].lower()
        out.append(LSFRecord(date=d, amount_gr=amt, currency=(row.get("waluta") or "PLN").upper(), counterparty=cp,
                             description=IBAN_RE.sub("[RACHUNEK]", desc), iban_hash=_iban_hash(desc, salt),
                             balance_gr=parse_amount_gr(row["saldo"]) if row.get("saldo") else None,
                             source=row.get("zrodlo") or path.name,
                             raw_hash=hashlib.sha256(("muz|" + rid).encode("utf-8")).hexdigest()))
    return out, cats
