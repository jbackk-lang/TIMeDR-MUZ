"""Propozycja akcji: polityka regulowa albo MLP, z bramka fazy i wstrzymaniem ponizej 0,6."""
from __future__ import annotations

import numpy as np

from ..core.messages import ACTIONS
from .features import FEATURE_NAMES

ALLOWED_BY_PHASE_DEFAULT = {
    "stabilna": ("zostawic",),
    "przejsciowa": ("negocjowac", "zmienic", "zostawic"),
    "krytyczna": ACTIONS,
}
ALLOWED_BY_PHASE = ALLOWED_BY_PHASE_DEFAULT


def rule_policy(frame, phase: str, contract: dict | None) -> str:
    if phase == "stabilna":
        return "zostawic"
    if phase == "przejsciowa":
        return "negocjowac" if (frame.defect or frame.baseline_hit) else "zostawic"
    nego = (contract or {}).get("negotiations", 0) or 0
    if nego >= 1 and (contract or {}).get("category") == "subskrypcja":
        return "anulowac"
    if nego >= 1:
        return "zmienic"
    return "negocjowac"


def propose(*, stream_id: str, x: np.ndarray, frame, phase: str, contract: dict | None, cfg: dict,
            policy_sha256: str, model=None, weights_sha256: str | None = None, background=None) -> dict | None:
    """Zwraca payload muz.action_proposal/1 albo None dla fazy stabilnej (tylko monitoring)."""
    if phase == "stabilna":
        return None
    allowed = set(cfg["allowed_by_phase"][phase])
    if model is None:
        action = rule_policy(frame, phase, contract)
        probs = {a: float(a == action) for a in ACTIONS}
        source, sha, top = "rules", policy_sha256, []
    else:
        p = model.predict_proba(x)[0]
        probs = {a: float(v) for a, v in zip(ACTIONS, p)}
        action = ACTIONS[int(np.argmax(p))]
        source, sha = "mlp", weights_sha256
        top = []
        if background is not None:
            imp = model.permutation_importance(x, background, ACTIONS.index(action))
            top = [FEATURE_NAMES[j] for j in np.argsort(-imp)[: cfg["top_features"]]]
    confidence = probs[action]
    abstained = confidence < cfg["abstain_below"] or action not in allowed
    note = None
    if abstained:
        action, note = "zostawic", "niepewne"
    return {"stream_id": stream_id, "probabilities": probs, "action": action, "confidence": confidence,
            "top_features": top, "weights_sha256": sha, "abstained": abstained, "source": source,
            "phase": phase, "note": note}
