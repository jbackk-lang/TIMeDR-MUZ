"""Pliki dla czlowieka: lista decyzji dla Excela (CSV) i PDF dla kazdego zabiegu z tytulem zabiegu.

- decyzje.csv  -- ';', UTF-8 z BOM, przecinek dziesietny: otwiera sie w polskim Excelu,
- pdf/<data>_<zabieg>.pdf -- jedna karta = jeden PDF; tytul zabiegu jest naglowkiem i tytulem dokumentu
  (widac go w przegladarce PDF i we wlasciwosciach pliku); osobny PDF z przydzialem do wyplaty.
PDF wymaga reportlab i czcionki TTF z polskimi znakami (jak pisma); bez nich -- tylko CSV.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

from . import decisions as D

FONTS = (("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
         ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
         ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"))


def _zl(gr) -> str:
    return "" if gr is None else f"{gr / 100:.2f}".replace(".", ",")


def slug(text: str, n: int = 60) -> str:
    t = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).replace("ł", "l").replace("Ł", "L")
    t = re.sub(r"[^A-Za-z0-9]+", "_", t.split(" — ")[0]).strip("_")
    return t[:n] or "zabieg"


def decisions_csv(plan: D.CyclePlan, cards: list[dict], path, pdfs: dict[int, Path] | None = None) -> Path:
    path = Path(path)
    pdfs = pdfs or {}
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["lp", "zabieg", "rodzaj", "kontrahent", "teraz_zl", "cel_zl", "granica_zl", "rocznie_zl", "termin", "pdf"])
        n = 1
        if plan.balance_gr is not None:
            rows = [("Zarezerwuj na opłaty do wypłaty", plan.reserve_gr), ("Na życie do wypłaty", plan.allowance_gr),
                    ("Odłóż na fundusz nieregularny", plan.to_fund_gr), ("Odłóż do bufora", plan.to_buffer_gr),
                    (f"Nadpłać: {plan.debt_target}", plan.to_debt_gr), ("Brakuje do minimum", plan.shortfall_gr)]
        else:
            rows = [("Zarezerwuj na opłaty do wypłaty", plan.reserve_gr)]
        for title, gr in rows:
            if gr:
                w.writerow([n, title, "przydział", "", "", _zl(gr), "", "", plan.next_payday.isoformat(),
                            pdfs.get(-1, Path("")).name]); n += 1
        for i, k in enumerate(cards):
            yearly = k["save_cancel_gr"] if k["action"] == "anulowac" else k["yearly_gr"]
            w.writerow([n, D.card_title(k), k["action"], k["counterparty"], _zl(k.get("now_gr")), _zl(k.get("target_gr")),
                        _zl(k.get("max_ok_gr")), _zl(yearly), k["deadline"].isoformat(), pdfs.get(i, Path("")).name]); n += 1
    return path


def _font():
    for reg, bold in FONTS:
        if Path(reg).exists():
            return reg, bold if Path(bold).exists() else reg
    return None, None


def _pdf(path: Path, title: str, body_md: str, subtitle: str = "") -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    reg, bold = _font()
    if reg is None:
        raise RuntimeError("brak czcionki TTF z polskimi znakami")
    pdfmetrics.registerFont(TTFont("MUZ", reg)); pdfmetrics.registerFont(TTFont("MUZ-B", bold))
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle(title); c.setSubject(subtitle or "TIMeDR-MUZ: decyzja budżetowa"); c.setAuthor("TIMeDR-MUZ")
    W, H = A4
    margin, y = 56, H - 64

    def newline(dy):
        nonlocal y
        y -= dy
        if y < 60:
            c.showPage(); y = H - 64

    def para(text, font="MUZ", size=10.5, indent=0, lead=14.5):
        line = ""
        for word in text.split(" "):
            trial = (line + " " + word).strip()
            if c.stringWidth(trial, font, size) > W - 2 * margin - indent and line:
                c.setFont(font, size); c.drawString(margin + indent, y, line); newline(lead); line = word
            else:
                line = trial
        c.setFont(font, size); c.drawString(margin + indent, y, line); newline(lead)

    para(title, "MUZ-B", 15, lead=20)
    if subtitle:
        para(subtitle, "MUZ", 9, lead=13)
    newline(6)
    for raw in body_md.splitlines():
        t = raw.rstrip()
        if not t.strip():
            newline(6); continue
        t = t.replace("**", "").replace("`", "").replace("_Uwaga", "Uwaga").rstrip("_")
        if t.startswith("#"):
            para(t.lstrip("# "), "MUZ-B", 12, lead=17); continue
        indent = 14 if re.match(r"^\s*(\d+\.|-)\s", t) else 0
        para(t.strip(), "MUZ", 10.5, indent)
    c.save()
    return path


def decisions_pdfs(plan: D.CyclePlan, cards: list[dict], out_dir) -> tuple[dict[int, Path], str | None]:
    """Zwraca ({indeks karty -> PDF, -1 -> PDF przydzialu}, powod braku PDF albo None)."""
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return {}, "brak reportlab (pip install reportlab) -- PDF pominiete"
    if _font()[0] is None:
        return {}, "brak czcionki TTF z polskimi znakami -- PDF pominiete"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    day = plan.today.isoformat()
    res = {}
    sub = f"TIMeDR-MUZ, {day}. MUZ nic nie wykonuje sam — to lista dla Ciebie."
    title = f"Do wypłaty {plan.next_payday.strftime('%d.%m')}: przydział pieniędzy"
    body = D.render_cycle(plan).split("\n", 1)[1]
    res[-1] = _pdf(out / f"{day}_Przydzial_do_wyplaty.pdf", title, body, sub)
    for i, k in enumerate(cards):
        body = D.render_card(k).split("\n", 1)[1]
        res[i] = _pdf(out / f"{day}_{slug(D.card_title(k))}.pdf", D.card_title(k), body, sub)
    return res, None
