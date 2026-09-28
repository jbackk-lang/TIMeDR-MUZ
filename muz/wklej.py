"""Wklejanie zamiast wpisywania: tekst skopiowany ze strony banku, z aplikacji, z SMS-a albo z Excela.

- tabela (kolumny rozdzielone tabulatorem, np. z Excela lub strony banku) -> samodopasowanie kolumn jak dla CSV,
- zwykly tekst -> kazda transakcja to data + kwota + opis, w jednej linii albo w kilku kolejnych
  (tak kopiuje sie historia z wiekszosci stron bankow: opis / kwota / data albo naglowek dnia i lista).
Rozumie: 12.06.2026, 2026-06-12, 12.06 (biezacy rok), "12 czerwca 2026", "dzisiaj", "wczoraj";
kwoty "-45,50", "45,50 zł", "1 234,56 PLN", "+3 000,00". Bez znaku: wydatek, chyba ze opis mowi o wplywie.
Wynik trafia do dane/wklejone.csv (CSV MUZ); te same wiersze wklejone drugi raz nie dubluja sie.
"""
from __future__ import annotations

import csv
import io
import re
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .adapter.csv_import import _strip_accents, parse_amount_gr
from .adapter.muz_csv import HEADER

MONTHS = {"sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6, "lip": 7, "sie": 8, "wrz": 9, "paz": 10,
          "lis": 11, "gru": 12}
RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RE_DMY = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
RE_DM = re.compile(r"(?<![\d,.])(\d{1,2})\.(\d{1,2})(?![\d,]|\.\d)")
RE_WORD = re.compile(r"\b(\d{1,2})\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paz|lis|gru)[a-z]*\.?(?:\s+(\d{4}))?", re.I)
RE_AMOUNT = re.compile(r"(?<![\w.,])([+\-−–]?\s?\d{1,3}(?:[  ]\d{3})+(?:[.,]\d{1,2})?(?!\d)|[+\-−–]?\s?\d+[.,]\d{2}(?!\d)|"
                       r"[+\-−–]?\s?\d+(?=\s*(?:zł|zl|pln)\b))\s*(zł|zl|pln)?", re.I)
INCOME = re.compile(r"wplyw|uznanie|przychodzacy|wynagrodzenie|pensja|zwrot|przelew od|otrzyman|swiadczenie|800 ?plus", re.I)


@dataclass
class Row:
    date: date | None
    amount_gr: int
    text: str


def _find_date(line: str, today: date, allow_dm: bool = True) -> tuple[date | None, str]:
    low = _strip_accents(line).lower()
    if re.search(r"\bdzisiaj\b|\bdzis\b", low):
        return today, re.sub(r"(?i)dzisiaj|dziś|dzis", " ", line)
    if re.search(r"\bwczoraj\b", low):
        return today - timedelta(days=1), re.sub(r"(?i)wczoraj", " ", line)
    rules = [(RE_ISO, "iso"), (RE_DMY, "dmy"), (RE_WORD, "word")] + ([(RE_DM, "dm")] if allow_dm else [])
    for rx, kind in rules:
        for m in rx.finditer(low if kind == "word" else line):
            try:
                if kind == "iso":
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                elif kind == "dmy":
                    d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                elif kind == "word":
                    y = int(m.group(3)) if m.group(3) else today.year
                    d = date(y, MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
                    if not m.group(3) and d > today + timedelta(days=1):
                        d = d.replace(year=y - 1)
                else:
                    d = date(today.year, int(m.group(2)), int(m.group(1)))
                    if d > today + timedelta(days=1):
                        d = d.replace(year=today.year - 1)
            except ValueError:
                continue
            return d, line[:m.start()] + " " + line[m.end():]
    return None, line


def _find_amount(line: str) -> tuple[int | None, str, bool]:
    """Kwota: z oznaczeniem waluty, a gdy brak -- ostatnia liczba z groszami. Zwraca (grosze, reszta, czy_ze_znakiem)."""
    ms = list(RE_AMOUNT.finditer(line))
    if not ms:
        return None, line, False
    cur = [m for m in ms if m.group(2)]
    best = cur[-1] if cur else ms[-1]
    raw = best.group(1).replace("−", "-").replace("–", "-").replace(" ", "").replace("\u00a0", "")
    try:
        gr = parse_amount_gr(raw)
    except ValueError:
        return None, line, False
    return gr, line[:best.start()] + " " + line[best.end():], raw[0] in "+-"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[|;\t]+", " ", text)).strip(" -–:,")


def parse_text(text: str, today: date) -> tuple[list[Row], int]:
    """Zwraca (wiersze, liczba pominietych bez daty)."""
    rows: list[Row] = []
    fallback: list[date | None] = []   # ostatnia data widziana PRZED transakcja (naglowek dnia)
    pending: list[str] = []
    current: date | None = None
    date_after = None      # None = jeszcze nie wiadomo; True = data pod kwota (opis/kwota/data); False = naglowek dnia
    for line in text.splitlines():
        if not line.strip():
            continue
        d, rest = _find_date(line, today, allow_dm=False)   # "12.50" to raczej kwota niz data
        gr, rest2, signed = _find_amount(rest)
        if d is None:
            d, rest2 = _find_date(rest2, today, allow_dm=True)
        if gr is None:
            rest = rest2
            if d is not None:
                current = d
                if date_after is None:
                    date_after = bool(rows)
                if rows and rows[-1].date is None:
                    rows[-1].date = d
                if _clean(rest):
                    pending.append(_clean(rest))
            else:
                pending.append(_clean(line))
            continue
        desc = _clean(" ".join(pending + [rest2]))
        pending = []
        if not signed:
            gr = abs(gr) if INCOME.search(_strip_accents(desc)) else -abs(gr)
        rows.append(Row(d or (None if date_after else current), gr, desc))
        fallback.append(current)
    for r, fb in zip(rows, fallback):   # wklejka mieszana: brak daty pod kwota -> naglowek dnia nad nia
        if r.date is None and fb is not None:
            r.date = fb
    kept = [r for r in rows if r.date is not None]
    return kept, len(rows) - len(kept)


def parse_table(text: str, salt: bytes = b"") -> list[Row] | None:
    """Tabela z tabulatorami: samodopasowanie kolumn (naglowek dodany, gdy go brak). None, gdy to nie tabela."""
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 2 or sum("\t" in l for l in lines) < 0.8 * len(lines):
        return None
    from .adapter import load_csv
    from .adapter.autodetect import sniff
    n = max(len(l.split("\t")) for l in lines)
    body = lines
    if _find_date(lines[0], date.today())[0] is not None:
        body = ["\t".join(f"Kolumna {i + 1}" for i in range(n))] + lines
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "wklejone.csv"
        p.write_text("\n".join(body) + "\n", encoding="utf-8")
        try:
            det = sniff(p)
            if not det.ok:
                return None
            recs = load_csv(p, det.mapping, salt)
        except ValueError:
            return None
    return [Row(r.date, r.amount_gr, _clean(f"{r.counterparty} {r.description}")) for r in recs]


def parse(text: str, today: date) -> tuple[list[Row], int]:
    t = parse_table(text)
    return (t, 0) if t else parse_text(text, today)


def append(rows: list[Row], path, category: str = "") -> int:
    """Dopisuje do CSV MUZ; pomija wiersze juz obecne. Zwraca liczbe dopisanych."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if path.exists():
        for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter=";"):
            existing.add((row.get("data"), row.get("kwota"), row.get("opis")))
    new = 0
    write_header = not path.exists()
    with path.open("a", encoding="utf-8-sig" if write_header else "utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        if write_header:
            w.writerow(HEADER)
        for r in rows:
            kw = f"{r.amount_gr / 100:.2f}".replace(".", ",")
            key = (r.date.isoformat(), kw, r.text)
            if key in existing:
                continue
            existing.add(key)
            w.writerow([r.date.isoformat(), kw, "PLN", "", r.text, category, "", "wklejone", ""])
            new += 1
    return new
