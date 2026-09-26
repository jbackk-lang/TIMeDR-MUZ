"""Terminy (L0): wypowiedzenia i konca promocji jako lokalny plik .ics. Bez zatwierdzenia, tylko dziennik."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from ..core.common import sha256_file
from .base import LOCAL, BaseExecutor


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_event(uid: str, day: date, summary: str, description: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TIMeDR-MUZ//etap0//PL", "BEGIN:VEVENT",
        f"UID:{uid}@timedr-muz.local", f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
        f"SUMMARY:{_esc(summary)}", f"DESCRIPTION:{_esc(description)}",
        "BEGIN:VALARM", "TRIGGER:-P7D", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(summary)}", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR", ""])


class ICSExecutor(BaseExecutor):
    name = "ics"
    level = "L0"
    levels = ("L0",)
    allowed_hosts = frozenset({LOCAL})

    def __init__(self, trusted_public_key: bytes, outdir):
        super().__init__(trusted_public_key)
        self.outdir = Path(outdir)

    def _do(self, plan: dict) -> dict:
        c = plan["content"]
        self.outdir.mkdir(parents=True, exist_ok=True)
        path = self.outdir / f"{plan['plan_id'][:12]}_termin.ics"
        path.write_bytes(ics_event(plan["plan_id"], date.fromisoformat(c["date"]), c["summary"], c["description"]).encode("utf-8"))
        return {"ics": path.name, "ics_sha256": sha256_file(path)}
