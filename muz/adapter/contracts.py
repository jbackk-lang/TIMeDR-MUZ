"""Pola umow potwierdzone recznie przez uzytkownika (umowy.json).

Dokument MUZ: umowy PDF czyta lokalny parser, ale pola wchodza do systemu dopiero po recznym
potwierdzeniu. Prototyp przyjmuje juz potwierdzony JSON:
[{"counterparty": "ORANGE POLSKA", "category": "telekom", "notice_period_months": 1,
  "end_date": "2026-12-31", "promo_end": null, "negotiations": 0,
  "cancel_channel": {"type": "letter", "address": "..."} | {"type": "form", "host": "...", "recipe": "..."},
  "confirmed_by_user": true}]
"""
from __future__ import annotations

import json
from pathlib import Path

from .csv_import import Stream, normalize_counterparty


def load_contracts(path) -> dict[str, dict]:
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for c in items:
        if not c.get("confirmed_by_user"):
            continue  # niepotwierdzone pola nie wchodza do decyzji
        out[normalize_counterparty(c["counterparty"])] = c
    return out


def attach_contracts(streams: list[Stream], contracts: dict[str, dict]) -> None:
    for s in streams:
        s.contract = contracts.get(s.counterparty)
