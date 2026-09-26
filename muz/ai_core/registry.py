"""Rejestr modeli: wagi mini-AI laduja sie tylko, gdy ich hash wskazuje wezel SUPPORTED.

Werdykt powstaje przez TIMDRProtocol (wendorowany z TIMDR-AI-Core): preregister -> run_controls -> run_test.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .._vendor.ai_core.timdr_ai_core import (ControlResult, Hypothesis, ProtocolCriteria, TestEvidence,
                                              TIMDRProtocol)
from ..core.common import sha256_file


class NotSupported(RuntimeError):
    pass


class ModelRegistry:
    def __init__(self, path):
        self.path = Path(path)

    def _load(self) -> list[dict]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def evaluate_and_register(self, *, artifact_path, hypothesis: Hypothesis, controls: ControlResult | None,
                              evidence: TestEvidence | None, criteria: ProtocolCriteria = ProtocolCriteria(),
                              synthetic: bool = False, extra: dict | None = None) -> dict:
        proto = TIMDRProtocol(criteria)
        prereg = proto.preregister(hypothesis)
        controls = proto.run_controls(controls)
        result = proto.run_test(controls, evidence)
        node = {"artifact": Path(artifact_path).name, "artifact_sha256": sha256_file(artifact_path),
                "hypothesis": hypothesis.name, "prereg_fingerprint": prereg.fingerprint,
                "controls": {"positive_ok": controls.positive_ok, "negative_ok": controls.negative_ok},
                "verdict": result.verdict, "reason": result.reason, "method": result.method,
                "p_value": result.p_value, "effect_size": result.effect_size,
                "synthetic": synthetic, **(extra or {})}
        nodes = self._load() + [node]
        self.path.write_text(json.dumps(nodes, indent=2, ensure_ascii=False), encoding="utf-8")
        return node

    def require_supported(self, artifact_path, allow_synthetic: bool = False) -> str:
        """Model uczony tylko na pakietach syntetycznych jest dopuszczany wylacznie w trybie cienia
        (allow_synthetic=True) - nigdy do tworzenia planow wykonania."""
        sha = sha256_file(artifact_path)
        for node in self._load():
            if node["artifact_sha256"] == sha and node["verdict"] == "SUPPORTED":
                if node.get("synthetic") and not allow_synthetic:
                    raise NotSupported(f"INCONCLUSIVE_SYNTHETIC_ONLY: {Path(artifact_path).name} ma SUPPORTED tylko na "
                                       f"danych syntetycznych - dozwolony wylacznie tryb cienia")
                return sha
        raise NotSupported(f"INCONCLUSIVE_NOT_SUPPORTED: {Path(artifact_path).name} ({sha[:12]}) nie ma werdyktu "
                           f"SUPPORTED w rejestrze - MUZ nie laduje tego modelu")
