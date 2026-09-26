"""Wspolna logika wykonawcow: weryfikacja zatwierdzenia, lista dozwolonych hostow, pokwitowanie."""
from __future__ import annotations

from datetime import datetime, timezone

from ..core.netguard import HostNotAllowed
from .gate import verify_approval

LOCAL = "local"  # wykonawca bez sieci (pliki na dysku uzytkownika)


class BaseExecutor:
    name = "base"
    level = "L0"                 # najwyzszy poziom obslugiwany przez wykonawce (protokol Executor)
    levels: tuple = ("L0",)      # wszystkie poziomy, jakie wykonawca przyjmuje
    allowed_hosts: frozenset[str] = frozenset({LOCAL})

    def __init__(self, trusted_public_key: bytes):
        self.trusted_public_key = trusted_public_key

    def _check(self, plan: dict, approval: dict | None, now=None) -> None:
        if plan["executor"] != self.name:
            raise ValueError(f"plan dla {plan['executor']}, nie dla {self.name}")
        if plan["target_host"] not in self.allowed_hosts:
            raise HostNotAllowed(f"{self.name}: host {plan['target_host']!r} spoza allowed_hosts")
        if plan["level"] not in self.levels:
            raise ValueError(f"{self.name}: poziom planu {plan['level']} spoza {self.levels}")
        verify_approval(plan, approval, self.trusted_public_key, now)

    def dry_run(self, plan: dict) -> dict:
        return {"plan_sha256": plan["plan_sha256"], "executor": self.name, "preview": plan["content"]}

    def execute(self, plan: dict, approval: dict | None, now=None) -> dict:
        self._check(plan, approval, now)
        evidence = self._do(plan)
        return {"plan_sha256": plan["plan_sha256"], "status": "done", "evidence": evidence,
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def _do(self, plan: dict) -> dict:  # pragma: no cover - nadpisywane
        raise NotImplementedError
