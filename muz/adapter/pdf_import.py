"""Wyciagi PDF z banku -- lokalnie (pdfplumber), bez wysylania pliku gdziekolwiek.

Dwie drogi, bez pytania uzytkownika o uklad:
1. tabela (PDF z liniami tabeli): wiersze tabeli -> samodopasowanie kolumn jak dla CSV (data, kwota, saldo...),
2. tekst: kazda linia z data zaczyna transakcje; linie bez daty i kwoty to ciag dalszy opisu (dlugie tytuly
   przelewow lamia sie na kilka linii). Gdy w linii sa dwie kwoty (kwota i saldo po operacji), MUZ sprawdza,
   ktora jest saldem: saldo zmienia sie dokladnie o kwote. Saldo ustala tez znak kwoty, gdy bank go nie drukuje.
Linie podsumowan ("saldo poczatkowe", "suma obciazen", "razem") sa pomijane.

Nie da sie odczytac: skanu (PDF bez warstwy tekstu -- trzeba by OCR). PDF z haslem: okno pyta o haslo raz
i zapisuje odczytane transakcje jako CSV MUZ obok, haslo nie jest nigdzie zapisywane.
"""
from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

from .csv_import import IBAN_RE, LSFRecord, _iban_hash, _strip_accents, load_csv, normalize_counterparty, parse_amount_gr

SKIP = re.compile(r"saldo (poczatkowe|koncowe|otwarcia|zamkniecia|na dzien|dostepne|ksiegowe)|suma (obciazen|uznan|wplywow|"
                  r"wydatkow)|razem|obroty|strona \d+|limit|oprocentowanie", re.I)


class PdfError(ValueError):
    pass


class PdfPasswordNeeded(PdfError):
    pass


class PdfScanned(PdfError):
    pass


def _open(path, password):
    try:
        import pdfplumber
    except ImportError as exc:
        raise PdfError("do czytania PDF potrzebna jest biblioteka pdfplumber (run.bat instaluje ja sam)") from exc
    try:
        return pdfplumber.open(str(path), password=password or "")
    except Exception as exc:  # noqa: BLE001 - pdfminer zglasza rozne wyjatki dla hasla
        name = (exc.__class__.__name__ + " " + repr(exc) + " " + repr(getattr(exc, "args", ""))).lower()
        if "password" in name or "encrypt" in name or "pdfpassword" in name:
            raise PdfPasswordNeeded(f"{Path(path).name}: PDF zabezpieczony hasłem") from None
        raise PdfError(f"{Path(path).name}: nie da się otworzyć PDF ({exc.__class__.__name__})") from None


def _tables(pdf) -> list[list[str]]:
    rows = []
    for page in pdf.pages:
        for t in page.extract_tables() or []:
            for r in t:
                cells = [re.sub(r"\s+", " ", (c or "")).strip() for c in r]
                if sum(1 for c in cells if c) >= 3:
                    rows.append(cells)
    return rows


def _records_from_table(rows, path: Path, salt: bytes) -> list[LSFRecord]:
    from .autodetect import sniff
    n = max(len(r) for r in rows)
    lines = ["\t".join((r + [""] * (n - len(r)))) for r in rows]
    from ..wklej import _find_date
    from datetime import date
    if _find_date(lines[0], date.today())[0] is not None:     # tabela bez naglowka
        lines = ["\t".join(f"Kolumna {i + 1}" for i in range(n))] + lines
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / (path.stem + ".csv")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        det = sniff(p)
        if not det.ok:
            return []
        recs = load_csv(p, det.mapping, salt)
    return [LSFRecord(**{**r.__dict__, "source": path.name}) for r in recs]


def _records_from_text(text: str, path: Path, salt: bytes) -> list[LSFRecord]:
    from datetime import date
    from ..wklej import INCOME, RE_AMOUNT, _find_date
    today = date.today()
    tx = []                                  # [data, [kwoty ze znakiem?], opis]
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = _strip_accents(line).lower()
        d, rest = _find_date(line, today, allow_dm=False)
        if d is not None:
            rest2 = rest
            d2, rest2 = _find_date(rest2, today, allow_dm=False)   # druga data (ksiegowania) -- pomijana
            rest = rest2 if d2 is not None else rest
        amounts = []
        for m in RE_AMOUNT.finditer(rest):
            s = m.group(1).replace("−", "-").replace("–", "-").replace(" ", "").replace(" ", "")
            try:
                amounts.append((parse_amount_gr(s), s[0] in "+-"))
            except ValueError:
                pass
        desc = re.sub(r"\s+", " ", RE_AMOUNT.sub(" ", rest)).strip(" -–:|")
        if d is not None and amounts and not SKIP.search(low):
            tx.append([d, amounts, desc])
        elif d is None and not amounts and tx and not SKIP.search(low):
            tx[-1][2] = (tx[-1][2] + " " + line).strip()           # ciag dalszy opisu
    if not tx:
        return []
    # ktora kwota jest saldem: saldo[i] - saldo[i-1] = +-kwota[i]
    two = [t for t in tx if len(t[1]) >= 2]
    use_balance = False
    if len(two) >= max(3, len(tx) // 2):
        ok = n = 0
        for a, b in zip(two, two[1:]):
            n += 1
            ok += abs(abs(b[1][-1][0] - a[1][-1][0]) - abs(b[1][0][0])) <= 1
        use_balance = n > 0 and ok / n >= 0.6
    out = []
    prev_bal = None
    for i, (d, amounts, desc) in enumerate(tx):
        amt, signed = amounts[0]
        bal = amounts[-1][0] if use_balance and len(amounts) >= 2 else None
        if use_balance and bal is not None and prev_bal is not None and not signed:
            amt = bal - prev_bal if abs(abs(bal - prev_bal) - abs(amt)) <= 1 else amt
        elif not signed:
            amt = abs(amt) if INCOME.search(_strip_accents(desc)) else -abs(amt)
        prev_bal = bal if bal is not None else prev_bal
        cp = normalize_counterparty(" ".join(desc.split()[:3]))
        raw = f"{path.name}|{i}|{d}|{amt}|{desc}"
        out.append(LSFRecord(date=d, amount_gr=amt, currency="PLN", counterparty=cp,
                             description=IBAN_RE.sub("[RACHUNEK]", desc), iban_hash=_iban_hash(desc, salt),
                             balance_gr=bal, source=path.name, raw_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest()))
    return out


def load_pdf(path, salt: bytes, password: str | None = None) -> list[LSFRecord]:
    path = Path(path)
    with _open(path, password) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if len(text.strip()) < 40:
            raise PdfScanned(f"{path.name}: to skan (obraz bez tekstu) — pobierz w banku wyciąg PDF z historii "
                             f"albo plik CSV; skanów MUZ jeszcze nie czyta")
        rows = _tables(pdf)
    recs = []
    if len(rows) >= 3:
        try:
            recs = _records_from_table(rows, path, salt)
        except ValueError:
            recs = []
    if len(recs) < 3:
        recs = _records_from_text(text, path, salt)
    if not recs:
        raise PdfError(f"{path.name}: nie znalazłem transakcji (linii z datą i kwotą)")
    return recs
