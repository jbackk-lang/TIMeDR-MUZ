"""Koperta i komunikaty miedzy warstwami (dokument MUZ, sekcja "Interfejsy").

Kazdy komunikat: schema, id, created_at, producer (modul + hash kodu), parents, payload, payload_sha256.
payload_sha256 liczony z kanonicznego JSON, tak jak _canonical_json w TIMDR-AI-Core.
"""
from __future__ import annotations

import inspect
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .common import canonical_json, sha256_file, sha256_text

# schemat -> wymagane pola payload (wersja glowna po ukosniku)
SCHEMAS: dict[str, tuple[str, ...]] = {
    "muz.lsf_record/1": ("date", "amount_gr", "currency", "counterparty", "iban_hash", "source", "raw_hash"),
    "muz.stream/1": ("stream_id", "counterparty", "contract", "cadence", "series"),
    "muz.signal_frame/1": ("stream_id", "month", "flags", "strengths", "baseline_hit", "thresholds_sha256"),
    "muz.meta_state/1": ("scope", "period", "Lambda", "tau", "rho", "J", "M", "validator_report_sha256"),
    "muz.phase_state/1": ("scope", "subject", "period", "phase", "rules_fired", "hysteresis_counter", "calibration_status"),
    "muz.action_proposal/1": ("stream_id", "probabilities", "action", "confidence", "top_features", "weights_sha256", "abstained"),
    "muz.verified_claim/1": ("claim_id", "verdict", "record_ids", "requirements_met", "text", "graph_sha256"),
    "muz.action_plan/1": ("plan_id", "claim_id", "executor", "target_host", "content", "level", "plan_sha256"),
    "muz.approval/1": ("plan_sha256", "decision", "signature", "public_key", "expires_at"),
    "muz.execution_receipt/1": ("plan_sha256", "status", "evidence", "finished_at"),
}
KNOWN_MAJOR = {name.split("/")[0]: int(name.split("/")[1]) for name in SCHEMAS}

ACTIONS = ("anulowac", "negocjowac", "zmienic", "zostawic")


class SchemaError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def code_sha256(obj) -> str:
    """Hash pliku zrodlowego modulu/klasy, ktora wyprodukowala komunikat."""
    return sha256_file(inspect.getsourcefile(obj))


@dataclass(frozen=True)
class Envelope:
    schema: str
    payload: dict
    producer: dict
    parents: tuple = ()
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=now_iso)
    payload_sha256: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["parents"] = list(self.parents)
        return d


def make(schema: str, payload: dict, producer_obj, parents=()) -> Envelope:
    validate_payload(schema, payload)
    src = producer_obj if (inspect.ismodule(producer_obj) or inspect.isclass(producer_obj)
                           or inspect.isfunction(producer_obj)) else type(producer_obj)
    name = getattr(src, "__module__", None) if inspect.isfunction(src) else None
    name = f"{name}.{src.__name__}" if name else getattr(src, "__name__", str(src))
    return Envelope(schema=schema, payload=payload, producer={"module": name, "code_sha256": code_sha256(src)},
                    parents=tuple(parents), payload_sha256=sha256_text(canonical_json(payload)))


def validate_payload(schema: str, payload: dict) -> None:
    name, _, major = schema.partition("/")
    if name not in KNOWN_MAJOR:
        raise SchemaError(f"nieznany schemat {schema!r}")
    if not major.isdigit() or int(major) != KNOWN_MAJOR[name]:
        raise SchemaError(f"nieznana wersja glowna {schema!r} - konsument odrzuca zamiast zgadywac")
    missing = [k for k in SCHEMAS[schema] if k not in payload]
    if missing:
        raise SchemaError(f"{schema}: brak pol {missing}")


def verify(env: Envelope) -> None:
    validate_payload(env.schema, env.payload)
    if sha256_text(canonical_json(env.payload)) != env.payload_sha256:
        raise SchemaError(f"{env.schema} {env.id}: payload_sha256 nie zgadza sie z trescia")
