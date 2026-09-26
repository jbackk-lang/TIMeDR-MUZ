"""Modul 7: TIMeDR-MUZ - warstwa wykonawcza (bramka, wykonawcy L0-L3).

Wykonawcy: ICSExecutor (L0 terminy), LetterExecutor (L1/L2 pisma PDF), FormExecutor (L2 formularze,
Playwright), QRTransferExecutor (L3 dane przelewu, SCA w banku). Kazdy wykonuje tylko plan
z poprawnym podpisem Ed25519 zatwierdzenia i tylko na swoich allowed_hosts.
"""
from .base import LOCAL, BaseExecutor
from .forms import FormExecutor, load_recipe
from .gate import GateError, approve, make_plan, plan_sha256, verify_approval
from .ics import ICSExecutor
from .letters import LetterExecutor, level_for, render_letter
from .qr import QRTransferExecutor, zbp_payload

__all__ = ["LOCAL", "BaseExecutor", "FormExecutor", "load_recipe", "GateError", "approve", "make_plan",
           "plan_sha256", "verify_approval", "ICSExecutor", "LetterExecutor", "level_for", "render_letter",
           "QRTransferExecutor", "zbp_payload"]
