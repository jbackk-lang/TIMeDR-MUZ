"""Samodopasowanie formatu wyciagu CSV -- lokalnie, bez nikogo z zewnatrz.

Kolumny rozpoznawane sa po ZAWARTOSCI, nie tylko po nazwach:
  data          -- >= 90% wierszy daje sie odczytac jako data (wybierany jeden format dla calej kolumny),
  kwota/saldo   -- kolumny liczbowe; saldo = ta, dla ktorej saldo[i] - saldo[i-1] = kwota[i] (tozsamosc ksiegowa),
  obciazenia/uznania -- dwie nieujemne kolumny, ktore sie wykluczaja (w wierszu wypelniona jedna),
  waluta        -- trzyliterowe kody (PLN, EUR),
  kontrahent/opis -- kolumny tekstowe: opis = najdluzszy tekst, kontrahent = krotszy i czesciej sie powtarza.
Nazwy kolumn sa tylko rozstrzygnieciem remisu.

Profile formatow: po pierwszym imporcie format jest zapamietywany pod odciskiem naglowka (sha256 nazw kolumn
i separatora) i sam nadaje sobie nazwe -- z preambuly banku (np. "Bank Przykladowy"), a gdy jej brak, z pliku.
Kolejny plik z tym samym naglowkiem wczytuje sie bez pytan. Nazwe mozna zmienic: python -m muz formaty --nazwa.
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from ..core.atomic import atomic_write_text

from .csv_import import DATE_FORMATS, GUESS, _read_text, _strip_accents, parse_amount_gr

SAMPLE_ROWS = 300
DELIMS = ";,\t|"
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
ORG_HINT = re.compile(r"\b(bank|banku|s\.?\s?a\.?|spoldzielcz|revolut|millennium|pekao|santander|alior|ing|mbank|pko|"
                      r"credit agricole|citi|nest|velo|bnp)\b", re.I)


@dataclass
class Detection:
    header_row: int
    columns: list[str]
    delimiter: str
    mapping: dict                 # zgodne z load_csv: date, amount | debit+credit, counterparty, description, ...
    confidence: dict              # pole -> 0..1
    reasons: dict                 # pole -> dlaczego ta kolumna
    fingerprint: str
    preamble: list[str] = field(default_factory=list)
    suggested_name: str = ""
    n_rows: int = 0

    @property
    def ok(self) -> bool:
        m = self.mapping
        return "date" in m and ("amount" in m or ("debit" in m and "credit" in m))


def _split(line: str, delim: str) -> list[str]:
    import csv
    return [c.strip().strip('"').strip() for c in next(csv.reader([line], delimiter=delim))]


def _pick_delim(lines: list[str]) -> str:
    """Separator dajacy najwiecej wierszy o tej samej, >= 3, liczbie pol."""
    best, score = ";", -1
    for d in DELIMS:
        counts = [len(_split(l, d)) for l in lines[:80] if l.strip()]
        counts = [c for c in counts if c >= 3]
        if not counts:
            continue
        mode = statistics.mode(counts)
        s = sum(1 for c in counts if c == mode) * mode
        if s > score:
            best, score = d, s
    return best


def _date_fmt(values: list[str]) -> tuple[str | None, float]:
    vals = [v[:10] for v in values if v]
    if not vals:
        return None, 0.0
    best, frac = None, 0.0
    for f in DATE_FORMATS:
        ok = 0
        for v in vals:
            try:
                datetime.strptime(v, f)
                ok += 1
            except ValueError:
                pass
        if ok / len(vals) > frac:
            best, frac = f, ok / len(vals)
    return best, frac


def _nums(values: list[str]) -> tuple[list[int | None], float]:
    out, ok, n = [], 0, 0
    for v in values:
        if not v:
            out.append(None)
            continue
        n += 1
        try:
            if not re.search(r"\d", v) or re.search(r"[A-Za-z]{4,}", v):
                raise ValueError
            out.append(parse_amount_gr(v))
            ok += 1
        except (ValueError, ArithmeticError):
            out.append(None)
    return out, (ok / n if n else 0.0)


def _header_hint(col: str, key: str) -> bool:
    c = _strip_accents(col).lower()
    return any(_strip_accents(p).lower() in c for p in GUESS.get(key, ()))


def _find_header(lines: list[str], delim: str) -> int:
    """Pierwszy wiersz z >= 3 niepustymi polami bez dat, po ktorym w 3 wierszach pojawia sie data."""
    for i, line in enumerate(lines[:80]):
        cols = [c for c in _split(line, delim) if c]
        if len(cols) < 3 or _date_fmt(cols)[1] > 0:
            continue
        for nxt in lines[i + 1:i + 4]:
            if _date_fmt([c for c in _split(nxt, delim) if c])[1] > 0:
                return i
    raise ValueError("nie rozpoznano naglowka: brak wiersza z nazwami kolumn przed wierszami z datami")


def fingerprint(columns: list[str], delim: str) -> str:
    norm = "|".join(_strip_accents(c).lower().strip() for c in columns) + f"#{delim!r}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _name_from(preamble: list[str], path: Path) -> str:
    for line in preamble:
        text = " ".join(t for t in re.split(r"[;,\t|]", line) if t.strip()).strip()
        if text and ORG_HINT.search(_strip_accents(text)):
            m = re.search(r"([A-ZŁŚŻŹĆŃÓĘĄ][\wĄĆĘŁŃÓŚŹŻąćęłńóśźż.\- ]{2,60})", text)
            name = (m.group(1) if m else text)[:60]
            name = re.sub(r"\s+(S\.?\s?A\.?|SA)\s*$", "", name.strip(), flags=re.I).strip(" .-")
            if name:
                return name
    stem = re.sub(r"[\d_\-\.]+", " ", path.stem).strip()
    return stem[:40] or "format"


def sniff(path) -> Detection:
    path = Path(path)
    lines = _read_text(path).splitlines()
    delim = _pick_delim(lines)
    h = _find_header(lines, delim)
    columns = _split(lines[h], delim)
    rows = [_split(l, delim) for l in lines[h + 1:h + 1 + SAMPLE_ROWS] if l.strip()]
    rows = [r + [""] * (len(columns) - len(r)) for r in rows if len(r) >= len(columns) - 1]
    cols = {j: [r[j] if j < len(r) else "" for r in rows] for j in range(len(columns)) if columns[j]}
    mapping, conf, why = {}, {}, {}

    # daty
    dates = {}
    for j, vals in cols.items():
        f, frac = _date_fmt(vals)
        if frac >= 0.9:
            dates[j] = (f, frac)
    if dates:
        pref = [j for j in dates if _header_hint(columns[j], "date") and "ksieg" not in _strip_accents(columns[j]).lower()]
        j = pref[0] if pref else min(dates)
        mapping["date"], mapping["date_format"] = columns[j], dates[j][0]
        conf["date"] = dates[j][1]
        why["date"] = f"{dates[j][1]:.0%} wierszy to daty w formacie {dates[j][0]}" + (" (nazwa kolumny)" if pref else " (pierwsza kolumna dat)")

    # liczby
    numeric = {}
    for j, vals in cols.items():
        if j in dates:
            continue
        v, frac = _nums(vals)
        if frac >= 0.9 and sum(x is not None for x in v) >= 3:
            numeric[j] = v

    def balance_fit(a, b):
        """ile par kolejnych wierszy spelnia b[i] - b[i-1] = a[i] (albo w odwrotnej kolejnosci wierszy)"""
        n = fwd = rev = 0
        for i in range(1, len(a)):
            if None in (a[i], a[i - 1], b[i], b[i - 1]):
                continue
            n += 1
            fwd += abs((b[i] - b[i - 1]) - a[i]) <= 1
            rev += abs((b[i - 1] - b[i]) - a[i - 1]) <= 1
        return (max(fwd, rev) / n) if n else 0.0

    # obciazenia/uznania: dwie nieujemne, wzajemnie wylaczne
    split = None
    nonneg = [j for j, v in numeric.items() if all(x is None or x >= 0 for x in v)]
    for a in nonneg:
        for b in nonneg:
            if a >= b:
                continue
            va, vb = numeric[a], numeric[b]
            both = sum(1 for x, y in zip(va, vb) if x and y)
            either = sum(1 for x, y in zip(va, vb) if x or y)
            if either >= 3 and both / either <= 0.02:
                deb, cre = (a, b)
                if _header_hint(columns[b], "debit") or re.search(r"obciaz|wyplyw|debet|wydat", _strip_accents(columns[b]).lower()):
                    deb, cre = b, a
                split = (deb, cre)
                break
        if split:
            break

    amount_col = None
    if split:
        deb, cre = split
        mapping["debit"], mapping["credit"] = columns[deb], columns[cre]
        signed = [(c or 0) - (d or 0) if (c or d) else None for d, c in zip(numeric[deb], numeric[cre])]
        conf["amount"] = 0.9
        why["amount"] = f"obciazenia w '{columns[deb]}', uznania w '{columns[cre]}' (kolumny sie wykluczaja)"
        others = {j: v for j, v in numeric.items() if j not in split}
        best = max(others, key=lambda j: balance_fit(signed, others[j]), default=None)
        if best is not None and balance_fit(signed, others[best]) >= 0.8:
            mapping["balance"] = columns[best]; conf["balance"] = balance_fit(signed, others[best])
            why["balance"] = f"saldo zmienia sie dokladnie o kwote w {conf['balance']:.0%} wierszy"
    elif numeric:
        pairs = [(balance_fit(numeric[a], numeric[b]), a, b) for a in numeric for b in numeric if a != b]
        fit, a, b = max(pairs) if pairs else (0.0, None, None)
        if fit >= 0.8:
            amount_col = a
            mapping["balance"] = columns[b]; conf["balance"] = fit
            why["balance"] = f"saldo zmienia sie dokladnie o kwote w {fit:.0%} wierszy"
            why["amount"] = "kwota zgodna z roznica salda"
            conf["amount"] = fit
        else:
            signed_cols = [j for j, v in numeric.items() if any(x is not None and x < 0 for x in v)]
            pref = [j for j in (signed_cols or list(numeric)) if _header_hint(columns[j], "amount")]
            amount_col = (pref or signed_cols or sorted(numeric))[0]
            conf["amount"] = 0.7 if signed_cols else 0.4
            why["amount"] = ("kolumna z kwotami dodatnimi i ujemnymi" if signed_cols else "jedyna/pierwsza kolumna liczbowa (bez znaku!)") + \
                            (" + nazwa kolumny" if pref else "")
        mapping["amount"] = columns[amount_col]

    # waluta
    for j, vals in cols.items():
        v = [x for x in vals if x]
        if v and sum(bool(CURRENCY_RE.match(x)) for x in v) / len(v) >= 0.95:
            mapping["currency"] = columns[j]; conf["currency"] = 1.0; why["currency"] = "trzyliterowe kody walut"
            break

    # tekst: opis i kontrahent
    used = {mapping.get(k) for k in ("date", "amount", "debit", "credit", "balance", "currency")}
    texts = []
    for j, vals in cols.items():
        if columns[j] in used or j in dates or j in numeric:
            continue
        v = [x for x in vals if x]
        if len(v) < max(3, len(rows) // 3):
            continue
        avg = sum(len(x) for x in v) / len(v)
        uniq = len(set(v)) / len(v)
        texts.append((j, avg, uniq))
    if texts:
        # stale kolumny ("PRZELEW") nie sa opisem; wsrod pasujacych nazw -- najdluzszy tekst
        varied = [t for t in texts if t[2] > 0.05] or texts
        hint_d = sorted([t for t in varied if _header_hint(columns[t[0]], "description")], key=lambda t: -t[1])
        d = hint_d[0] if hint_d else max(varied, key=lambda t: t[1])
        mapping["description"] = columns[d[0]]; conf["description"] = 0.9 if hint_d else 0.6
        why["description"] = ("nazwa kolumny" if hint_d else "najdluzszy tekst") + f" (srednio {d[1]:.0f} znakow)"
        rest = [t for t in texts if t[0] != d[0] and not re.search(r"rachun|konto|iban|nr ", _strip_accents(columns[t[0]]).lower())]
        hint_c = [t for t in rest if _header_hint(columns[t[0]], "counterparty")]
        if hint_c or rest:
            c = hint_c[0] if hint_c else min(rest, key=lambda t: t[2])
            mapping["counterparty"] = columns[c[0]]; conf["counterparty"] = 0.9 if hint_c else 0.6
            why["counterparty"] = ("nazwa kolumny" if hint_c else "tekst, ktory najczesciej sie powtarza") + f" ({c[2]:.0%} unikalnych)"
        else:
            mapping["counterparty"] = mapping["description"]; conf["counterparty"] = 0.3
            why["counterparty"] = "brak osobnej kolumny -- kontrahent z pierwszych slow opisu"

    preamble = [l for l in lines[:h] if l.strip(" ;,\t")]
    det = Detection(h, columns, delim, mapping, conf, why, fingerprint(columns, delim), preamble,
                    _name_from(preamble, path), len(rows))
    return det


# ---------------------------------------------------------------------------
# Profile formatow (uczone po pierwszym imporcie)
# ---------------------------------------------------------------------------

class ProfileStore:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(self.data, indent=2, ensure_ascii=False))

    def get(self, fp: str) -> dict | None:
        return self.data.get(fp)

    def names(self) -> set[str]:
        return {p["name"] for p in self.data.values()}

    def touch(self, fp: str, source: str) -> None:
        """Znany format: dopisuje plik, nie zmienia mapowania (moglo byc poprawione recznie)."""
        if source not in self.data[fp]["files"]:
            self.data[fp]["files"].append(source)
            self.save()

    def learn(self, det: Detection, source: str, name: str | None = None, mapping: dict | None = None) -> dict:
        """Nowy format albo swiadoma poprawka mapowania (mapping z GUI)."""
        if mapping is not None:
            det.mapping = mapping
        base = name or det.suggested_name or "format"
        final, k = base, 2
        while final in self.names() and self.data.get(det.fingerprint, {}).get("name") != final:
            final, k = f"{base} ({k})", k + 1
        prof = self.data.get(det.fingerprint) or {"name": final, "created": datetime.now().isoformat(timespec="seconds"),
                                                  "columns": det.columns, "delimiter": det.delimiter, "files": []}
        prof["mapping"] = det.mapping
        if source not in prof["files"]:
            prof["files"].append(source)
        self.data[det.fingerprint] = prof
        self.save()
        return prof

    def rename(self, key: str, new: str) -> str:
        fp = key if key in self.data else next((f for f, p in self.data.items() if p["name"] == key), None)
        if fp is None:
            raise KeyError(f"nie ma profilu {key!r}")
        self.data[fp]["name"] = new
        self.save()
        return fp


def resolve(path, store: ProfileStore | None, learn: bool = True) -> tuple[dict, dict]:
    """Mapowanie dla pliku: znany profil -> bez pytan; nowy format -> rozpoznanie po zawartosci i zapis profilu
    z nazwa nadana automatycznie. Zwraca (mapping, info)."""
    path = Path(path)
    det = sniff(path)
    if not det.ok:
        raise ValueError(f"{path.name}: nie rozpoznano kolumny daty albo kwoty. Znalezione: {det.reasons}")
    prof = store.get(det.fingerprint) if store else None
    if prof:
        if learn and store:
            store.touch(det.fingerprint, path.name)
        return prof["mapping"], {"profile": prof["name"], "new": False, "fingerprint": det.fingerprint}
    info = {"profile": det.suggested_name, "new": True, "fingerprint": det.fingerprint,
            "reasons": det.reasons, "confidence": det.confidence}
    if learn and store:
        info["profile"] = store.learn(det, path.name)["name"]
    return det.mapping, info


def detection_dict(det: Detection) -> dict:
    return asdict(det)
