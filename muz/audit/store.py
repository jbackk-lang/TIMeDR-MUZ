"""Szyfrowany magazyn lokalny: AES-256-GCM (biblioteka `cryptography`, ten sam prymityw co Helix-Lock).

Klucz 32 bajty; docelowo w magazynie kluczy systemu. Bez `cryptography` magazyn odmawia pracy
(fail closed) zamiast zapisywac dane jawnym tekstem.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from ..core.atomic import atomic_write_bytes

try:  # pragma: no cover - zalezne od srodowiska
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    AVAILABLE = True
except Exception:  # noqa: BLE001
    AESGCM = None
    AVAILABLE = False

MAGIC = b"MUZ1"


class EncryptionUnavailable(RuntimeError):
    pass


def new_key(path) -> bytes:
    key = secrets.token_bytes(32)
    atomic_write_bytes(path, key, private=True)
    return key


class SecureStore:
    def __init__(self, key: bytes):
        if not AVAILABLE:
            raise EncryptionUnavailable("brak AES-256-GCM (biblioteka cryptography) - magazyn nie zapisze danych jawnie")
        if len(key) != 32:
            raise ValueError("AES-256 wymaga klucza 32 bajtow")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes, associated: bytes = b"") -> bytes:
        nonce = secrets.token_bytes(12)
        return MAGIC + nonce + self._aead.encrypt(nonce, plaintext, associated)

    def decrypt(self, blob: bytes, associated: bytes = b"") -> bytes:
        if blob[:4] != MAGIC:
            raise ValueError("to nie jest plik magazynu MUZ")
        return self._aead.decrypt(blob[4:16], blob[16:], associated)

    def write_json(self, path, obj) -> None:
        atomic_write_bytes(path, self.encrypt(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                                              Path(path).name.encode()), private=True)

    def read_json(self, path):
        return json.loads(self.decrypt(Path(path).read_bytes(), Path(path).name.encode()).decode("utf-8"))
