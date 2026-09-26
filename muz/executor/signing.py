"""Podpis Ed25519 zatwierdzen: `cryptography`, a gdy jest niedostepna - implementacja RFC 8032.

Klucz prywatny bramki: docelowo magazyn kluczy systemu (DPAPI w Windows, Keychain, Android Keystore).
Prototyp trzyma go w pliku z uprawnieniami tylko dla wlasciciela (0600) poza repozytorium.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from . import ed25519_ref

try:  # pragma: no cover - zalezne od srodowiska
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature
    BACKEND = "cryptography"
except Exception:  # noqa: BLE001 - np. DLL zablokowana przez Device Guard
    BACKEND = "rfc8032-python"


def generate_key(path) -> bytes:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    path.write_bytes(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return public_key(secret)


def load_secret(path) -> bytes:
    return Path(path).read_bytes()


def public_key(secret: bytes) -> bytes:
    if BACKEND == "cryptography":
        return Ed25519PrivateKey.from_private_bytes(secret).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return ed25519_ref.public_key(secret)


def sign(secret: bytes, msg: bytes) -> bytes:
    if BACKEND == "cryptography":
        return Ed25519PrivateKey.from_private_bytes(secret).sign(msg)
    return ed25519_ref.sign(secret, msg)


def verify(public: bytes, msg: bytes, signature: bytes) -> bool:
    if BACKEND == "cryptography":
        try:
            Ed25519PublicKey.from_public_bytes(public).verify(signature, msg)
            return True
        except (InvalidSignature, ValueError):
            return False
    return ed25519_ref.verify(public, msg, signature)
