"""Wykonawca pism: PDF z wersjonowanego szablonu + szkic e-maila (.eml). L1 (prosba) albo L2 (wypowiedzenie).

Bez sieci: pismo trafia do folderu nadawczego; uzytkownik wysyla je ze swojej skrzynki albo drukuje
jako list polecony. PDF przez reportlab z czcionka TTF zawierajaca polskie znaki.
"""
from __future__ import annotations

import string
from email.message import EmailMessage
from pathlib import Path

from ..core.common import sha256_file
from .base import LOCAL, BaseExecutor

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
TEMPLATE_BY_ACTION = {"negocjowac": ("prosba_o_obnizke_v0.1.txt", "L1"), "anulowac": ("wypowiedzenie_v0.1.txt", "L2"),
                      "zmienic": ("wniosek_o_zmiane_planu_v0.1.txt", "L2")}
FONT_CANDIDATES = ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                   "/Library/Fonts/Arial Unicode.ttf")


def render_letter(action: str, fields: dict) -> tuple[str, str, str]:
    """Zwraca (tresc, nazwa szablonu, hash szablonu). Brakujace pole = blad, nie puste miejsce."""
    name, _ = TEMPLATE_BY_ACTION[action]
    path = TEMPLATES_DIR / name
    tpl = path.read_text(encoding="utf-8")
    needed = {f for _, f, _, _ in string.Formatter().parse(tpl) if f}
    missing = sorted(needed - set(fields))
    if missing:
        raise KeyError(f"brak pol szablonu {name}: {missing}")
    return tpl.format(**fields), name, sha256_file(path)


def level_for(action: str) -> str:
    return TEMPLATE_BY_ACTION[action][1]


class LetterExecutor(BaseExecutor):
    name = "letter"
    level = "L2"
    levels = ("L1", "L2")
    allowed_hosts = frozenset({LOCAL})

    def __init__(self, trusted_public_key: bytes, outbox, font_path: str | None = None):
        super().__init__(trusted_public_key)
        self.outbox = Path(outbox)
        self.font_path = font_path or next((f for f in FONT_CANDIDATES if Path(f).exists()), None)

    def _do(self, plan: dict) -> dict:
        self.outbox.mkdir(parents=True, exist_ok=True)
        text = plan["content"]["text"]
        stem = f"{plan['plan_id'][:12]}_{plan['action']}"
        pdf = self.outbox / f"{stem}.pdf"
        self._write_pdf(pdf, text)
        eml = self.outbox / f"{stem}.eml"
        msg = EmailMessage()
        msg["To"] = plan["content"].get("to_email", "")
        msg["Subject"] = plan["content"].get("subject", "Pismo")
        msg.set_content(text)
        msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf", filename=pdf.name)
        eml.write_bytes(bytes(msg))
        return {"pdf": pdf.name, "pdf_sha256": sha256_file(pdf), "eml": eml.name, "eml_sha256": sha256_file(eml),
                "template": plan["content"]["template"], "template_sha256": plan["content"]["template_sha256"],
                "note": "pismo czeka w folderze nadawczym: wyslij ze swojej skrzynki albo wydrukuj"}

    def _write_pdf(self, path: Path, text: str) -> None:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
        if not self.font_path:
            raise RuntimeError("brak czcionki TTF z polskimi znakami (ustaw font_path)")
        pdfmetrics.registerFont(TTFont("MUZ", self.font_path))
        c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
        width, height = A4
        y = height - 60
        c.setFont("MUZ", 11)
        for para in text.split("\n"):
            line = ""
            for word in para.split(" "):
                trial = (line + " " + word).strip()
                if c.stringWidth(trial, "MUZ", 11) > width - 120:
                    c.drawString(60, y, line)
                    y -= 15
                    line = word
                else:
                    line = trial
            c.drawString(60, y, line)
            y -= 15
        c.save()
