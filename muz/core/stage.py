"""Protokoly modulow (dokument MUZ, sekcja "Interfejsy")."""
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from .messages import Envelope


@runtime_checkable
class Stage(Protocol):
    schema_in: str            # np. "muz.stream/1"
    schema_out: str           # np. "muz.signal_frame/1"
    config_sha256: str        # hash zamrozonych progow lub wag

    def run(self, msgs: list[Envelope]) -> list[Envelope]: ...


@runtime_checkable
class Executor(Protocol):
    level: Literal["L0", "L1", "L2", "L3"]
    allowed_hosts: frozenset[str]

    def dry_run(self, plan: dict) -> dict: ...

    def execute(self, plan: dict, approval: dict) -> dict: ...
