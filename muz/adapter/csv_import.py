"""Import wyciagow CSV do rekordow LSF oraz budowa strumieni miesiecznych.

Tylko pliki lokalne. Zadnego dostepu do sieci (PSD2 to osobny, pozniejszy tryb).
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y", "%Y.%m.%d")
LEGAL_SUFFIXES = (
    "SPOLKA Z OGRANICZONA ODPOWIEDZIALNOSCIA", "SPOLKA AKCYJNA", "SPOLKA KOMANDYTOWA",
    "SP Z O O", "SP ZOO", "S A", "SA", "SP J", "SP K", "SPZOO",
)
IBAN_RE = re.compile(r"\b(?:PL)?\s?\d{2}(?:\s?\d{4}){6}\b")


@dataclass(frozen=True)
class LSFRecord:
    date: date
    amount_gr: int            # kwota w groszach, ujemna = wydatek
    currency: str
    counterparty: str         # znormalizowany kontrahent
    description: str          # opis bez numerow rachunkow
    iban_hash: str            # hash rachunku kontrahenta (lokalna sol) albo ""
    balance_gr: int | None    # saldo po operacji, jesli bank je podaje
    source: str               # nazwa pliku
    raw_hash: str             # hash surowego wiersza (odtwarzalnosc bit w bit)

    def dedup_key(self):
        return (self.date, self.amount_gr, self.counterparty,
                hashlib.sha256(self.description.encode("utf-8")).hexdigest()[:16])


@dataclass
class Stream:
    stream_id: str
    counterparty: str
    months: list[str]                 # "RRRR-MM", ciagle od pierwszego do ostatniego miesiaca
    amounts_gr: list[int]             # suma wydatkow w miesiacu (dodatnia), 0 gdy brak
    cadence: str                      # "monthly" albo "irregular"
    n_payments: int = 0
    record_hashes: list[str] = field(default_factory=list)
    contract: dict | None = None      # potwierdzone recznie pola umowy (umowy.json), albo None
    month_records: dict = field(default_factory=dict)  # miesiac -> hashe surowych transakcji (dowody)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1250", "iso-8859-2"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"nie udalo sie rozpoznac kodowania pliku {path}")


def _find_header(lines: list[str], date_col: str) -> int:
    for i, line in enumerate(lines):
        if date_col.lower() in line.lower():
            return i
    raise ValueError(f"nie znaleziono wiersza naglowka z kolumna daty {date_col!r}")


def parse_amount_gr(text: str) -> int:
    s = (text or "").replace(" ", "").replace(" ", "")
    s = re.sub(r"[A-Za-z]{3}$", "", s)          # np. "-89,00PLN"
    if s.count(",") == 1 and s.count(".") >= 1:  # 1.234,56
        s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"niepoprawna kwota: {text!r}") from exc
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_date(text: str, fmt: str | None = None) -> date:
    t = (text or "").strip()
    formats = (fmt,) if fmt else DATE_FORMATS
    for f in formats:
        try:
            return datetime.strptime(t[:10], f).date()
        except ValueError:
            continue
    raise ValueError(f"niepoprawna data: {text!r}")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).replace("ł", "l").replace("Ł", "L")


def normalize_counterparty(name: str, aliases: dict[str, str] | None = None) -> str:
    s = _strip_accents(name or "").upper()
    s = IBAN_RE.sub(" ", s)
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    changed = True
    while changed and s:
        changed = False
        for suf in LEGAL_SUFFIXES:
            if s.endswith(" " + suf) or s == suf:
                s = s[: -len(suf)].strip()
                changed = True
    for key, target in (aliases or {}).items():
        if s.startswith(_strip_accents(key).upper()):
            return target
    return s


# Opis transakcji z PDF/wklejki zaczyna sie zwykle od rodzaju operacji, nie od kontrahenta.
_LABEL = re.compile(r"\b(?:NAZWA ODBIORCY|NAZWA NADAWCY|DANE ODBIORCY|DANE NADAWCY|DANE KONTRAHENTA|ODBIORCA|NADAWCA|"
                    r"KONTRAHENT|NAZWA|MIEJSCE TRANSAKCJI|LOKALIZACJA|ADRES)\s*:?\s+")
_STOP = re.compile(r"\b(?:TYTUL|TYTULEM|ADRES|REF|REFERENCJE|NR REF|NUMER|RACHUNEK|KONTO|DATA|KWOTA|ORYGINALNA|KARTA|"
                   r"NR KARTY|LOKALIZACJA|MIEJSCE|ODBIORCA|NADAWCA)\b")
_TYPE = re.compile(r"^(?:PRZELEW(?: (?:WYCHODZACY|PRZYCHODZACY|NA RACHUNEK|NA TELEFON|DO|Z|ZEWNETRZNY|WEWNETRZNY|"
                   r"NATYCHMIASTOWY|EXPRESS ELIXIR|ELIXIR|SEPA|KRAJOWY|SORBNET|WLASNY|PRZYCHODZACY))*|"
                   r"PLATNOSC(?: (?:KARTA|KARTY|BLIK|WEB|MOBILNA|INTERNETOWA|TELEFONEM|APPLE PAY|GOOGLE PAY))*|"
                   r"ZAKUP PRZY UZYCIU KARTY|TRANSAKCJA(?: (?:KARTA|KARTOWA|BLIK|BEZGOTOWKOWA))*|BLIK|OBCIAZENIE|UZNANIE|"
                   r"POLECENIE ZAPLATY|ZLECENIE STALE|WYPLATA(?: (?:Z BANKOMATU|GOTOWKI|BLIK))*|WPLATA(?: GOTOWKI)?|"
                   r"OPERACJA KARTA|STANDING ORDER|CARD PAYMENT|TRANSFER|PAYMENT|DEBIT|CREDIT|TYTUL|TYTULEM)\b[ :]*")


def counterparty_from_description(text: str, aliases: dict[str, str] | None = None) -> str:
    """Kontrahent z opisu: najpierw etykieta (Odbiorca:, Nazwa:), potem opis bez rodzaju operacji, bez numerow kart,
    dat i numerow sklepow (ten sam sklep w roznych miesiacach ma rozne numery). Do 3 slow."""
    s = _strip_accents(text or "").upper()
    s = IBAN_RE.sub(" ", s)
    s = re.sub(r"\d{4}[ *X]{2,}\d{4}|\*{2,}\d*|\bX{4,}\d*", " ", s)            # numery kart
    m = _LABEL.search(s)
    if m:
        s = s[m.end():]
        stop = _STOP.search(s)
        s = s[:stop.start()] if stop else s
    else:
        prev = None
        while prev != s:
            prev = s
            s = _TYPE.sub("", s.strip())
        stop = _STOP.search(s)
        s = s[:stop.start()] if stop and stop.start() > 0 else s
    words = [w for w in re.sub(r"[^A-Z0-9 ]+", " ", s).split() if not re.search(r"\d", w)]
    joined = " ".join(words[:8])
    legal = re.search(r"\b(?:SPOLKA Z OGRANICZONA ODPOWIEDZIALNOSCIA|SPOLKA AKCYJNA|SP Z O O|SP ZOO|SPZOO|S A|SA|SP J|SP K)\b", joined)
    if legal and legal.start() > 0:                            # za forma prawna jest juz adres albo miasto
        joined = joined[:legal.start()]
    return normalize_counterparty(" ".join(joined.split()[:3]), aliases)


def _iban_hash(text: str, salt: bytes) -> str:
    m = IBAN_RE.search(text or "")
    if not m:
        return ""
    digits = re.sub(r"\D", "", m.group(0))
    return hashlib.sha256(salt + digits.encode()).hexdigest()[:16]


def _amount(row: dict, mapping: dict) -> int:
    """Kwota ze znakiem: jedna kolumna "amount" albo para "debit" (obciazenia) / "credit" (uznania)."""
    if mapping.get("amount"):
        return parse_amount_gr(row[mapping["amount"]])
    deb, cre = row.get(mapping["debit"], ""), row.get(mapping["credit"], "")
    return (abs(parse_amount_gr(cre)) if cre else 0) - (abs(parse_amount_gr(deb)) if deb else 0)


def load_csv(path, mapping: dict, salt: bytes) -> list[LSFRecord]:
    """Czyta wyciag CSV wedlug mapowania kolumn.

    mapping: {"date": ..., "amount": ... (albo "debit" + "credit"), "counterparty": ..., "description": ...,
              opcjonalnie "currency", "balance", "date_format", "aliases": {...}}
    """
    path = Path(path)
    text = _read_text(path)
    lines = text.splitlines()
    start = _find_header(lines, mapping["date"])
    body = "\n".join(lines[start:])
    sample = body[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    reader = csv.DictReader(io.StringIO(body), dialect=dialect)
    aliases = mapping.get("aliases", {})
    out = []
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if not row.get(mapping["date"]):
            continue
        raw = "|".join(f"{k}={row[k]}" for k in sorted(row))
        cp_raw = row.get(mapping.get("counterparty", ""), "")
        desc_raw = row.get(mapping.get("description", ""), "")
        cp = normalize_counterparty(cp_raw, aliases) or counterparty_from_description(desc_raw, aliases)
        bal_col = mapping.get("balance")
        out.append(LSFRecord(
            date=parse_date(row[mapping["date"]], mapping.get("date_format")),
            amount_gr=_amount(row, mapping),
            currency=(row.get(mapping.get("currency", ""), "") or "PLN").upper(),
            counterparty=cp,
            description=IBAN_RE.sub("[RACHUNEK]", desc_raw),
            iban_hash=_iban_hash(cp_raw + " " + desc_raw, salt),
            balance_gr=parse_amount_gr(row[bal_col]) if bal_col and row.get(bal_col) else None,
            source=path.name,
            raw_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        ))
    return out


def deduplicate(records: list[LSFRecord]) -> list[LSFRecord]:
    """Usuwa nakladajace sie rekordy (np. ten sam miesiac z dwoch eksportow).

    Liczy krotnosc klucza w kazdym pliku osobno i zostawia maksimum, wiec dwie identyczne
    platnosci tego samego dnia w JEDNYM pliku nie zostana polaczone w jedna.
    """
    from collections import Counter, defaultdict
    per_source: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        per_source[r.source][r.dedup_key()] += 1
    keep_count = Counter()
    for counts in per_source.values():
        for k, n in counts.items():
            keep_count[k] = max(keep_count[k], n)
    seen = Counter()
    out = []
    for r in sorted(records, key=lambda r: (r.date, r.source, r.raw_hash)):
        k = r.dedup_key()
        if seen[k] < keep_count[k]:
            out.append(r)
            seen[k] += 1
    return out


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    ly, lm = map(int, last.split("-"))
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def build_streams(records: list[LSFRecord], min_payment_months: int = 3, monthly_min_coverage: float = 0.75) -> list[Stream]:
    """Grupuje wydatki (kwoty ujemne, PLN) po kontrahencie w miesieczne szeregi."""
    from collections import defaultdict
    by_cp: dict[str, list[LSFRecord]] = defaultdict(list)
    for r in records:
        if r.amount_gr < 0 and r.currency == "PLN" and r.counterparty:
            by_cp[r.counterparty].append(r)
    streams = []
    for cp, recs in sorted(by_cp.items()):
        months = _month_range(min(_month(r.date) for r in recs), max(_month(r.date) for r in recs))
        sums = {m: 0 for m in months}
        for r in recs:
            sums[_month(r.date)] += -r.amount_gr
        amounts = [sums[m] for m in months]
        paid = sum(1 for a in amounts if a > 0)
        if paid < min_payment_months:
            continue
        cadence = "monthly" if paid / len(months) >= monthly_min_coverage else "irregular"
        sid = hashlib.sha256(cp.encode("utf-8")).hexdigest()[:12]
        by_month: dict[str, list[str]] = {}
        for r in recs:
            by_month.setdefault(_month(r.date), []).append(r.raw_hash)
        streams.append(Stream(sid, cp, months, amounts, cadence, len(recs), sorted(r.raw_hash for r in recs),
                              month_records={m: sorted(h) for m, h in by_month.items()}))
    return streams


def monthly_income_gr(records: list[LSFRecord]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        if r.amount_gr > 0 and r.currency == "PLN":
            out[_month(r.date)] = out.get(_month(r.date), 0) + r.amount_gr
    return out


def load_cpi(path) -> dict[str, float]:
    """Opcjonalny lokalny plik CPI: kolumny 'miesiac' (RRRR-MM) i 'cpi_rr' (inflacja r/r w procentach)."""
    text = _read_text(Path(path))
    reader = csv.DictReader(io.StringIO(text), delimiter=";" if ";" in text.splitlines()[0] else ",")
    return {row["miesiac"].strip(): float(row["cpi_rr"].replace(",", ".")) / 100.0 for row in reader}


# ---------------------------------------------------------------------------
# Rozpoznawanie naglowka i propozycja mapowania (dla GUI)
# ---------------------------------------------------------------------------

GUESS = {
    "date": ("data operacji", "data transakcji", "data księgowania", "data ksiegowania", "data"),
    "amount": ("kwota operacji", "kwota transakcji", "kwota"),
    "counterparty": ("nadawca / odbiorca", "nadawca/odbiorca", "odbiorca", "nadawca", "kontrahent", "nazwa"),
    "description": ("tytuł", "tytul", "opis operacji", "opis"),
    "currency": ("waluta",),
    "balance": ("saldo po operacji", "saldo po transakcji", "saldo"),
}


def _split_line(line: str) -> tuple[list[str], str]:
    delim = max(";,\t", key=line.count)
    return [c.strip().strip('"') for c in line.split(delim)], delim


def _looks_like_date(text: str) -> bool:
    try:
        parse_date(text)
        return True
    except ValueError:
        return False


def detect_header(path) -> tuple[int, list[str]]:
    """Zwraca (numer wiersza naglowka, nazwy kolumn): pierwszy wiersz z >= 4 polami bez dat,
    po ktorym nastepuje wiersz z data. Wiersze przed naglowkiem (preambula banku) sa pomijane."""
    lines = _read_text(Path(path)).splitlines()
    for i, line in enumerate(lines[:60]):
        cols, _ = _split_line(line)
        named = [c for c in cols if c]
        if len(named) < 4 or any(_looks_like_date(c) for c in named):
            continue
        for nxt in lines[i + 1: i + 4]:
            fields, _ = _split_line(nxt)
            if any(_looks_like_date(f) for f in fields if f):
                return i, cols
    raise ValueError("nie rozpoznano wiersza naglowka (brak wiersza z nazwami kolumn przed wierszami z datami)")


def guess_mapping(columns: list[str]) -> dict:
    """Propozycja mapowania po nazwach kolumn; uzytkownik zatwierdza ja w GUI."""
    low = {c.lower(): c for c in columns if c}
    out: dict[str, str] = {}
    used: set[str] = set()
    for key, patterns in GUESS.items():
        for pat in patterns:
            hit = next((orig for l, orig in low.items() if pat in l and orig not in used), None)
            if hit:
                out[key] = hit
                used.add(hit)
                break
    return out
