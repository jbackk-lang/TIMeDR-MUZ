"""Wspolne narzedzia: kanoniczny JSON, hashe, kontrola plikow wendorowanych."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent
VENDOR_DIR = PKG_DIR / "_vendor"


def canonical_json(obj) -> str:
    """Deterministyczny JSON (posortowane klucze, bez spacji), jak _canonical_json w TIMDR-AI-Core."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_obj(obj) -> str:
    return sha256_text(canonical_json(obj))


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class VendorMismatch(RuntimeError):
    pass


def verify_vendor() -> str:
    """Sprawdza hashe plikow wendorowanych z VENDOR.lock.json. Zwraca hash samego locka."""
    lock_path = VENDOR_DIR / "VENDOR.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    bad = []
    for rel, expected in lock["files"].items():
        p = VENDOR_DIR / rel
        if not p.exists() or sha256_file(p) != expected:
            bad.append(rel)
    if bad:
        raise VendorMismatch(
            "INCONCLUSIVE_VENDOR_CHANGED: pliki wendorowane nie zgadzaja sie z VENDOR.lock.json: " + ", ".join(bad)
        )
    return sha256_file(lock_path)
