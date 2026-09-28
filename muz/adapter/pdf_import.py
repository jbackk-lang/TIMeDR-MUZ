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

from .csv_import import (IBAN_RE, LSFRecord, _iban_hash, _strip_accents, counterparty_from_description, load_csv,
                         normalize_counterparty, parse_amount_gr)

SKIP = re.compile(r"saldo (poczatkowe|koncowe|otwarcia|zamkniecia|na dzien|dostepne|ksiegowe|poprzednie)|suma (obciazen|uznan|"
                  r"wplywow|wydatkow)|\brazem\b|^obroty|oprocentowanie|limit kredytu", re.I)


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


FOOTER = re.compile(r"saldo (do|z) przeniesienia|niniejszy dokument|powszechna kasa|strona \d+\s*/\s*\d+|wyciag za okres|"
                    r"nr rachunku|nr iban|^www\.|infolinia|sad rejonowy|kapital zakladowy|data operacji|data waluty|"
                    r"identyfikator operacji|obroty (ma|wn)|saldo poprzednie|saldo koncowe", re.I)
ACCOUNT = re.compile(r"(?:PL\s?)?\d{2}(?:\s?\d{4}){6}")
ADDRESS = re.compile(r"\b(?:UL|UL\.|AL|AL\.|OS|OS\.|PL\.|PLAC|UL\.)\s*|\b\d{2}-\d{3}\b|\bREF\b|DATA DOKUMENTU|,")
BANK_OP = re.compile(r"OPLATA|PROWIZJA|KAPITALIZACJA|KAPIT\.|ODSETK|KREDYT|SPLATA|LIMIT|POZYCZK|RATA")


def counterparty_from_details(kind: str, details: str) -> str:
    """Kontrahent z ukladu 'naglowek operacji + linie szczegolow' (np. PKO BP): Lokalizacja: przy kartach i platnosciach
    WEB, nazwa po numerze rachunku przy przelewach, a dla operacji bankowych (oplata, odsetki, rata) -- sam rodzaj."""
    k = _strip_accents(kind).upper()
    det = _strip_accents(details).upper()
    if re.search(r"WYPLATA W BANKOMACIE|WYPLATA Z BANKOMATU|WYPLATA GOTOWKI", k):
        return "WYPLATA GOTOWKI"
    if re.search(r"WPLATA GOTOWKI|WPLATOMA", k):
        return "WPLATA GOTOWKI"
    m = re.search(r"LOKALIZACJA:?\s*(.+?)(?:\s+NR\s*REF|\s+NR\s*$|$)", det)
    if m:
        loc = m.group(1)
        url = re.search(r"(?:HTTPS?://)?(?:WWW\.)?([A-Z0-9-]+)\.(?:[A-Z]{2,}\.?)+", loc)
        if url and ("HTTP" in loc or "WWW" in loc or loc.strip().startswith(url.group(0))):
            return normalize_counterparty(url.group(1))
        cp = counterparty_from_description(re.sub(r"\s+PL\s*$", "", loc.strip()))
        if cp:
            return cp
    acc = list(ACCOUNT.finditer(det))
    if acc:
        after = det[acc[-1].end():]
        cut = ADDRESS.search(after)
        cp = counterparty_from_description(after[:cut.start()] if cut else after)
        if cp:
            return cp
    if BANK_OP.search(k):
        return normalize_counterparty(k)
    return counterparty_from_description(kind + " " + details) or normalize_counterparty(k)


def _records_from_text(text: str, path: Path, salt: bytes) -> list[LSFRecord]:
    """Transakcja zaczyna sie linia z data i kwota; kolejne linie (data waluty, szczegoly) to jej ciag dalszy
    az do nastepnej transakcji albo stopki strony."""
    from datetime import date
    from ..wklej import INCOME, RE_AMOUNT, _find_date
    today = date.today()
    tx = []                                  # {"d", "amounts", "kind", "details"}
    open_tx = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = _strip_accents(line).lower()
        d, rest = _find_date(line, today, allow_dm=False)
        rest_nd = rest
        if d is not None:
            d2, rest2 = _find_date(rest, today, allow_dm=False)    # druga data (ksiegowania/waluty) -- pomijana
            rest_nd = rest2 if d2 is not None else rest
        amounts = []
        for m in RE_AMOUNT.finditer(rest_nd):
            if rest_nd[m.end():m.end() + 2].strip().startswith("%"):
                continue                                               # stopa procentowa, nie kwota
            s_ = m.group(1).replace("−", "-").replace("–", "-").replace(" ", "").replace("\u00a0", "")
            try:
                amounts.append((parse_amount_gr(s_), s_[0] in "+-"))
            except ValueError:
                pass
        if d is not None and amounts and not SKIP.search(low) and not FOOTER.search(low):
            kind = re.sub(r"\s+", " ", RE_AMOUNT.sub(" ", rest_nd)).strip(" -–:|")
            toks = kind.split()
            if toks and len(toks[0]) >= 8 and re.search(r"\d", toks[0]) and re.search(r"[A-Za-z]", toks[0]):
                kind = " ".join(toks[1:])                            # identyfikator operacji
            tx.append({"d": d, "amounts": amounts, "kind": kind, "details": [], "raw": rest_nd.strip()})
            open_tx = True
            continue
        if FOOTER.search(low) or SKIP.search(low):
            open_tx = False
            continue
        if open_tx and not low.startswith("kwota oryg"):
            tx[-1]["details"].append(rest_nd.strip() if d is not None else line)
    if not tx:
        return []
    if sum(len(t["amounts"]) >= 2 for t in tx) >= 0.8 * len(tx):
        tx = [t for t in tx if len(t["amounts"]) >= 2]                # uklad "kwota + saldo": reszta to komunikaty banku
    # ktora kwota jest saldem: saldo[i] - saldo[i-1] = +-kwota[i]
    two = [t for t in tx if len(t["amounts"]) >= 2]
    use_balance = False
    if len(two) >= max(3, len(tx) // 2):
        ok = n = 0
        for a, b in zip(two, two[1:]):
            n += 1
            ok += abs(abs(b["amounts"][-1][0] - a["amounts"][-1][0]) - abs(b["amounts"][0][0])) <= 1
        use_balance = n > 0 and ok / n >= 0.6
    if use_balance:
        # linia szczegolow z data i kwotami (np. "KAPITAL: 0,00 ODSETKI: 172,85") nie zgadza sie z saldem -- to nie
        # nowa operacja, tylko ciag dalszy poprzedniej
        kept = [tx[0]]
        for t in tx[1:]:
            prev = kept[-1]["amounts"][-1][0]
            if len(t["amounts"]) >= 2 and abs(abs(t["amounts"][-1][0] - prev) - abs(t["amounts"][0][0])) > 1 \
                    and t["d"] == kept[-1]["d"]:
                kept[-1]["details"].append(t["raw"])                  # z kwotami (np. ODSETKI: 172,85)
                kept[-1]["details"] += t["details"]
                continue
            kept.append(t)
        tx = kept
    out = []
    prev_bal = None
    for i, t in enumerate(tx):
        d, amounts = t["d"], t["amounts"]
        details = " ".join(x for x in t["details"] if x)
        desc = re.sub(r"\s+", " ", (t["kind"] + " " + details)).strip()[:300]
        amt, signed = amounts[0]
        bal = amounts[-1][0] if use_balance and len(amounts) >= 2 else None
        if use_balance and bal is not None and prev_bal is not None and not signed:
            amt = bal - prev_bal if abs(abs(bal - prev_bal) - abs(amt)) <= 1 else amt
        elif not signed:
            amt = abs(amt) if INCOME.search(_strip_accents(desc)) else -abs(amt)
        prev_bal = bal if bal is not None else prev_bal
        cp = counterparty_from_details(t["kind"], details) if details else counterparty_from_description(t["kind"])
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


# ---------------------------------------------------------------------------
# Podsumowanie srodkow (np. iPKO "PODSUMOWANIE ŚRODKÓW") i naglowek wyciagu: saldo, limit, kredyty
# ---------------------------------------------------------------------------

_MONEY = r"(?:(?<=\s)|^)(-?\d{1,3}(?:[ \u00a0]?\d{3})*,\d{2})\s*PLN"


def _gr(txt: str) -> int:
    return parse_amount_gr(txt.replace(" ", "").replace("\u00a0", ""))


def read_summary(path, password: str | None = None) -> dict | None:
    """Stan rachunkow i kredytow z dokumentu podsumowania. None, gdy to nie jest podsumowanie."""
    from datetime import date
    with _open(Path(path), password) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    flat = _strip_accents(text).upper().replace(" ", "")
    if "PODSUMOWANIESRODKOW" not in flat and "POTWIERDZENIESTANURACHUNKOW" not in flat:
        return None
    out: dict = {"kredyty": []}
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    out["data"] = date.fromisoformat(m.group(1)) if m else date.today()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        norm = _strip_accents(line).upper().replace(" ", "")
        if "SALDORACHUNKU" in norm and i + 1 < len(lines):
            vals = re.findall(_MONEY, lines[i + 1])
            if len(vals) >= 2:
                out["saldo_gr"], out["dostepne_gr"] = _gr(vals[0]), _gr(vals[1])
                out["limit_gr"] = _gr(vals[2]) if len(vals) >= 3 else 0
        if "POZOSTALAKWOTA" in norm:
            j = i + 1
            while j < len(lines):
                vals = re.findall(_MONEY, lines[j])
                if len(vals) < 2:
                    break
                name = lines[j + 1].strip() if j + 1 < len(lines) and not re.findall(_MONEY, lines[j + 1]) else "kredyt"
                name = re.sub(r"(?<=[a-ząćęłńóśźż])(?=[A-ZĄĆĘŁŃÓŚŹŻ])", " ", name)
                name = re.sub(r"(?i)(?<=[a-ząćęłńóśźż])(gotówkow|hipoteczn|konsolidacyjn|samochodow|ratalny|odnawialn)",
                              r" \1", name)
                out["kredyty"].append({"nazwa": name.title() if name.isupper() else name, "przyznana_gr": _gr(vals[0]),
                                       "pozostalo_gr": _gr(vals[1])})
                j += 2
    return out if "saldo_gr" in out or out["kredyty"] else None


def statement_limit_rate(path, password: str | None = None) -> float | None:
    """Oprocentowanie limitu w rachunku z naglowka wyciagu ("...salda debetowego: 5 500,00 / Stopa %: 15,00")."""
    with _open(Path(path), password) as pdf:
        text = pdf.pages[0].extract_text() or ""
    t = _strip_accents(text).lower()
    m = re.search(r"(?:limit|debet)[^\n]*\n?[^\n]*?stopa %:\s*(\d+,\d+)", t)
    if not m:
        m = re.search(r"debetowego[^\n]*\n[^\n]*stopa %:\s*(\d+,\d+)", t)
    return float(m.group(1).replace(",", ".")) if m else None
