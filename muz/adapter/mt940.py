"""Minimalny parser MT940 (SWIFT) dla wyciagow polskich bankow.

Obslugiwane pola: :60F: (waluta), :61: (linia operacji), :86: (opis z podpolami ~NN albo <NN:
20-25 tytul, 32-33 nazwa kontrahenta, 38 rachunek kontrahenta). Warianty bankow roznia sie;
nieznany uklad :86: trafia w calosci do opisu.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

from .csv_import import IBAN_RE, LSFRecord, _iban_hash, _read_text, counterparty_from_description, normalize_counterparty

LINE61 = re.compile(r"^(\d{2})(\d{2})(\d{2})(\d{4})?(RC|RD|C|D)[A-Z]?(\d+,\d{0,2})")
SUBFIELD = re.compile(r"[~<](\d{2})")


def _split_tags(text: str) -> list[tuple[str, str]]:
    tags, cur_tag, cur = [], None, []
    for line in text.splitlines():
        m = re.match(r"^:(\d{2}[A-Z]?):(.*)$", line)
        if m:
            if cur_tag:
                tags.append((cur_tag, "\n".join(cur)))
            cur_tag, cur = m.group(1), [m.group(2)]
        elif cur_tag:
            cur.append(line)
    if cur_tag:
        tags.append((cur_tag, "\n".join(cur)))
    return tags


def _parse86(text: str) -> tuple[str, str, str]:
    flat = text.replace("\n", "")
    parts = SUBFIELD.split(flat)
    if len(parts) < 3:
        return "", flat.strip(), ""
    fields: dict[str, str] = {}
    for code, val in zip(parts[1::2], parts[2::2]):
        fields[code] = fields.get(code, "") + val
    title = "".join(fields.get(str(c), "") for c in range(20, 26)).strip()
    name = (fields.get("32", "") + " " + fields.get("33", "")).strip()
    return name, title, fields.get("38", "").strip()


def load_mt940(path, salt: bytes, aliases: dict | None = None) -> list[LSFRecord]:
    path = Path(path)
    tags = _split_tags(_read_text(path))
    currency = "PLN"
    out: list[LSFRecord] = []
    pending = None
    for tag, val in tags + [("END", "")]:
        if pending and tag != "86":
            out.append(pending(None))
            pending = None
        if tag == "60F":
            currency = val[7:10] or currency
        elif tag == "61":
            m = LINE61.match(val)
            if not m:
                raise ValueError(f"niepoprawna linia :61: {val!r}")
            yy, mm, dd, _, mark, amount = m.groups()
            d = date(2000 + int(yy), int(mm), int(dd))
            gr = int(round(float(amount.replace(",", ".")) * 100))
            sign = -1 if mark in ("D", "RC") else 1
            raw61 = val

            def pending(v86, d=d, gr=gr, sign=sign, raw61=raw61, cur=currency):
                name, title, acct = _parse86(v86 or "")
                raw = raw61 + "|" + (v86 or "")
                cp = normalize_counterparty(name, aliases) or counterparty_from_description(title, aliases)
                return LSFRecord(date=d, amount_gr=sign * gr, currency=cur, counterparty=cp,
                                 description=IBAN_RE.sub("[RACHUNEK]", title),
                                 iban_hash=_iban_hash(acct + " " + title, salt), balance_gr=None,
                                 source=path.name, raw_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest())
        elif tag == "86" and pending:
            out.append(pending(val))
            pending = None
    return out
