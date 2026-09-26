"""Dziennik audytu: JSONL tylko do dopisywania, kazdy wpis zawiera hash poprzedniego.

export_anchor() zwraca hash ostatniego wpisu do wyniesienia poza urzadzenie (wydruk, e-mail do siebie),
zeby wykryc przepisanie calego dziennika.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..core.common import canonical_json, sha256_text

GENESIS = "0" * 64


def _entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "entry_hash"}
    return sha256_text(canonical_json(body))


def append(log_path, event: str, data: dict) -> dict:
    log_path = Path(log_path)
    prev = GENESIS
    if log_path.exists():
        lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lines:
            prev = json.loads(lines[-1])["entry_hash"]
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event,
             "prev_hash": prev, "data": data}
    entry["entry_hash"] = _entry_hash(entry)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(canonical_json(entry) + "\n")
    return entry


def verify(log_path) -> tuple[bool, str]:
    log_path = Path(log_path)
    if not log_path.exists():
        return True, "brak dziennika"
    prev = GENESIS
    for n, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("prev_hash") != prev:
            return False, f"wpis {n}: prev_hash nie pasuje (usuniety albo wstawiony wpis)"
        if _entry_hash(e) != e.get("entry_hash"):
            return False, f"wpis {n}: tresc zmieniona po zapisie"
        prev = e["entry_hash"]
    return True, f"lancuch poprawny, ostatni hash {prev}"


def export_anchor(log_path) -> str:
    ok, msg = verify(log_path)
    if not ok:
        raise RuntimeError("dziennik uszkodzony: " + msg)
    lines = [l for l in Path(log_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(lines[-1])["entry_hash"] if lines else GENESIS
