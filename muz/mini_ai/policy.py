"""Propozycja akcji: polityka budzetowa (reguly) albo MLP, z bramka fazy i wstrzymaniem ponizej 0,6.

Od decyzji v0.3 plany tworzy polityka budzetowa (sekcja "budget_policy" w prereg/muz_decision_v0.3.json):
te same jawne reguly, ktore mini-AI odtwarza w trybie cienia. rule_policy (v0.1) zostaje tylko do porownan.
"""
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


def _month_minus_12(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - 1:04d}-{m:02d}"


def amount_12m_ago(frames) -> int | None:
    """Kwota z tego samego miesiaca rok wczesniej (po nazwie miesiaca, nie po indeksie - luki w historii nie przesuwaja)."""
    target = _month_minus_12(frames[-1].month)
    return next((f.amount_gr for f in reversed(frames) if f.month == target), None)


def budget_action(*, amount_gr: int, amount_12m_ago_gr: int | None, cpi_yoy: float | None, contract: dict | None,
                  income_month_gr: float, cfg: dict) -> str:
    """Polityka budzetowa (prereg: sekcja "teacher"/"budget_policy"). Uzywa tylko kwoty teraz i rok temu, CPI r/r,
    potwierdzonej umowy i dochodu. Faza jest sprawdzana osobno (bramka fazy w propose)."""
    t = cfg["teacher"]
    c = contract or {}
    cat = c.get("category", "inne")
    if cat in t["not_negotiable"] or not amount_12m_ago_gr or amount_12m_ago_gr <= 0 or cpi_yoy is None:
        return "zostawic"
    yoy = amount_gr / amount_12m_ago_gr - 1.0
    extra_annual = max(0, amount_gr - amount_12m_ago_gr) * 12
    over_cpi = yoy > cpi_yoy + t["cpi_margin"]
    material = income_month_gr > 0 and extra_annual >= t["materiality_annual_share_of_monthly_income"] * income_month_gr
    if not (over_cpi and material):
        return "zostawic"
    nego = c.get("negotiations", 0) or 0
    if nego == 0 or cat == "kredyt":
        return "negocjowac"
    if cat in t["cancellable"]:
        return "anulowac"
    if cat in t["switchable"]:
        return "zmienic"
    return "negocjowac"


def budget_policy(frames, phase: str, contract: dict | None, cpi_yoy: float | None, income_month_gr: float,
                  cfg: dict) -> str:
    if phase == "stabilna":
        return "zostawic"
    return budget_action(amount_gr=frames[-1].amount_gr, amount_12m_ago_gr=amount_12m_ago(frames), cpi_yoy=cpi_yoy,
                         contract=contract, income_month_gr=income_month_gr, cfg=cfg)


def propose(*, stream_id: str, x: np.ndarray, frame, phase: str, contract: dict | None, cfg: dict,
            policy_sha256: str, model=None, weights_sha256: str | None = None, background=None,
            frames=None, cpi_yoy: float | None = None, income_month_gr: float = 0.0) -> dict | None:
    """Zwraca payload muz.action_proposal/1 albo None dla fazy stabilnej (tylko monitoring).
    Bez modelu: polityka budzetowa - wymaga frames (historia strumienia), cpi_yoy i income_month_gr."""
    if phase == "stabilna":
        return None
    allowed = set(cfg["allowed_by_phase"][phase])
    if model is None:
        if frames is None:
            raise ValueError("polityka budzetowa wymaga historii strumienia (frames)")
        action = budget_policy(frames, phase, contract, cpi_yoy, income_month_gr, cfg)
        probs = {a: float(a == action) for a in ACTIONS}
        source, sha, top = "budget_rules", policy_sha256, []
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
        note = "niepewne" if confidence < cfg["abstain_below"] else f"faza {phase} nie pozwala: {action}"
        action = "zostawic"
    return {"stream_id": stream_id, "probabilities": probs, "action": action, "confidence": confidence,
            "top_features": top, "weights_sha256": sha, "abstained": abstained, "source": source,
            "phase": phase, "note": note}
