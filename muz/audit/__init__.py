"""Dziennik audytu: JSONL tylko do dopisywania, kazdy wpis zawiera hash poprzedniego.

export_anchor() zwraca hash ostatniego wpisu do wyniesienia poza urzadzenie (wydruk, e-mail do siebie),
zeby wykryc przepisanie calego dziennika. export_anchor_n() dodaje liczbe wpisow ("N:hash").
verify_anchor() sprawdza dziennik wzgledem takiej kotwicy: wykrywa obciecie ogona i przepisanie lancucha,
czego samo verify() nie umie (lancuch bez zewnetrznego punktu odniesienia mozna przeliczyc od nowa).
"""
from __future__ import annotations

import json
import os
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
        fh.flush()
        os.fsync(fh.fileno())
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


def export_anchor_n(log_path) -> str:
    """Kotwica "N:hash" - N to liczba wpisow; pozwala wykryc obciecie ogona."""
    h = export_anchor(log_path)
    n = sum(1 for l in Path(log_path).read_text(encoding="utf-8").splitlines() if l.strip()) if Path(log_path).exists() else 0
    return f"{n}:{h}"


def verify_anchor(log_path, anchor: str) -> tuple[bool, str]:
    """Sprawdza lancuch ORAZ zgodnosc z wczesniej wyniesiona kotwica ("hash" albo "N:hash").

    Dziennik moze byc dluzszy niz w chwili eksportu kotwicy (nowe wpisy), ale wpis z kotwicy musi w nim
    stac na tym samym miejscu z tym samym hashem. Obciecie ogona albo przepisanie lancucha -> False.
    """
    ok, msg = verify(log_path)
    if not ok:
        return False, msg
    anchor = anchor.strip()
    n_expected = None
    if ":" in anchor:
        n_txt, anchor = anchor.split(":", 1)
        try:
            n_expected = int(n_txt)
        except ValueError:
            return False, "kotwica: niepoprawna liczba wpisow"
    hashes = [json.loads(l)["entry_hash"] for l in Path(log_path).read_text(encoding="utf-8").splitlines()
              if l.strip()] if Path(log_path).exists() else []
    if anchor == GENESIS and n_expected in (None, 0):
        return True, "kotwica pusta (genesis)"
    if anchor not in hashes:
        return False, "kotwica nie wystepuje w dzienniku (obciety ogon albo przepisany lancuch)"
    pos = hashes.index(anchor) + 1
    if n_expected is not None and pos != n_expected:
        return False, f"kotwica: wpis na pozycji {pos}, a oczekiwano {n_expected}"
    return True, f"dziennik zgodny z kotwica (pozycja {pos} z {len(hashes)})"
