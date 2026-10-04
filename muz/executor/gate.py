"""Bramka zatwierdzenia (dokument MUZ, modul 7).

- plan akcji powstaje tylko z twierdzenia SUPPORTED,
- plan_sha256 = hash kanonicznego JSON wszystkich pol planu,
- zatwierdzenie podpisuje kluczem Ed25519 {plan_sha256, decision, expires_at}, waznosc 15 minut,
- poziomy: L0 bez zatwierdzenia (tylko dziennik), L1 klikniecie, L2 klikniecie + lokalny PIN,
  L3 pieniadze: MUZ przygotowuje tylko dane przelewu, autoryzacja (SCA) zawsze w aplikacji banku.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from ..core.atomic import atomic_write_bytes

from ..core.common import canonical_json, sha256_text
from . import signing

LEVELS = ("L0", "L1", "L2", "L3")
APPROVAL_TTL = timedelta(minutes=15)


class GateError(RuntimeError):
    pass


def plan_sha256(plan: dict) -> str:
    body = {k: v for k, v in plan.items() if k != "plan_sha256"}
    return sha256_text(canonical_json(body))


def make_plan(*, claim: dict, proposal: dict, executor: str, target_host: str, content: dict, level: str) -> dict:
    if claim["verdict"] != "SUPPORTED":
        raise GateError(f"plan wymaga twierdzenia SUPPORTED, jest {claim['verdict']}")
    if level not in LEVELS:
        raise GateError(f"nieznany poziom {level}")
    plan = {"plan_id": uuid.uuid4().hex, "claim_id": claim["claim_id"], "executor": executor,
            "target_host": target_host, "content": content, "level": level,
            "action": proposal["action"], "stream_id": proposal["stream_id"],
            "claim_text": claim["text"], "record_ids": claim["record_ids"]}
    plan["plan_sha256"] = plan_sha256(plan)
    return plan


# --- PIN dla L2 (scrypt z biblioteki standardowej) ---
def set_pin(path, pin: str) -> None:
    salt = os.urandom(16)
    h = hashlib.scrypt(pin.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    atomic_write_bytes(path, json.dumps({"salt": salt.hex(), "hash": h.hex()}).encode("utf-8"), private=True)


def check_pin(path, pin: str) -> bool:
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    h = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(rec["salt"]), n=2 ** 14, r=8, p=1)
    return hmac.compare_digest(h.hex(), rec["hash"])


def approve(plan: dict, *, decision: str, secret_key: bytes, pin: str | None = None, pin_path=None,
            now: datetime | None = None) -> dict:
    """decision: "approve" albo "reject" (poprawka = nowy plan i nowe zatwierdzenie)."""
    if decision not in ("approve", "reject"):
        raise GateError("decision musi byc 'approve' albo 'reject'")
    if plan_sha256(plan) != plan["plan_sha256"]:
        raise GateError("plan zmieniony po utworzeniu (plan_sha256 nie pasuje)")
    if decision == "approve" and plan["level"] == "L2":
        if pin is None or pin_path is None or not check_pin(pin_path, pin):
            raise GateError("poziom L2 wymaga poprawnego lokalnego PIN")
    now = now or datetime.now(timezone.utc)
    body = {"plan_sha256": plan["plan_sha256"], "decision": decision,
            "expires_at": (now + APPROVAL_TTL).isoformat(timespec="seconds")}
    sig = signing.sign(secret_key, canonical_json(body).encode("utf-8"))
    return body | {"signature": sig.hex(), "public_key": signing.public_key(secret_key).hex(),
                   "backend": signing.BACKEND}


def verify_approval(plan: dict, approval: dict | None, trusted_public_key: bytes, now: datetime | None = None) -> None:
    """Rzuca GateError, jesli plan nie moze byc wykonany. L0 nie wymaga zatwierdzenia."""
    if plan_sha256(plan) != plan["plan_sha256"]:
        raise GateError("tresc planu nie zgadza sie z plan_sha256 - wykonanie odrzucone")
    if plan["level"] == "L0":
        return
    if approval is None:
        raise GateError(f"poziom {plan['level']} wymaga zatwierdzenia")
    if approval["plan_sha256"] != plan["plan_sha256"]:
        raise GateError("zatwierdzenie dotyczy innego planu")
    if bytes.fromhex(approval["public_key"]) != trusted_public_key:
        raise GateError("zatwierdzenie podpisane nieznanym kluczem")
    body = {k: approval[k] for k in ("plan_sha256", "decision", "expires_at")}
    if not signing.verify(trusted_public_key, canonical_json(body).encode("utf-8"), bytes.fromhex(approval["signature"])):
        raise GateError("niepoprawny podpis zatwierdzenia")
    if approval["decision"] != "approve":
        raise GateError("plan odrzucony przez uzytkownika")
    now = now or datetime.now(timezone.utc)
    if now > datetime.fromisoformat(approval["expires_at"]):
        raise GateError("zatwierdzenie wygaslo (15 minut) - wymagane ponowne zatwierdzenie")
