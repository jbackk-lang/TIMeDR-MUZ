"""Klasyfikacja faz: stabilna (0) / przejsciowa (1) / krytyczna (2). Jawne reguly + histereza.

Wejscie w faze wyzsza natychmiast, wyjscie dopiero po `exit_periods` kolejnych okresach ponizej.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..meta import BudgetMeta, is_finite
from ..signals import SignalFrame

NAMES = {0: "stabilna", 1: "przejsciowa", 2: "krytyczna"}


def hysteresis(raw_levels: list[int], exit_periods: int) -> list[int]:
    out, current, below = [], 0, 0
    for r in raw_levels:
        if r >= current:
            current, below = r, 0
        else:
            below += 1
            if below >= exit_periods:
                current, below = r, 0
        out.append(current)
    return out


def stream_raw_level(f: SignalFrame, rel_threshold: float) -> int:
    if f.defect and f.defect_rel is not None and abs(f.defect_rel) >= 2 * rel_threshold:
        return 2
    if f.any_flag or f.baseline_hit:
        return 1
    return 0


def stream_phases(frames: list[SignalFrame], th: dict) -> list[int]:
    raw = [stream_raw_level(f, th["defect_rel_threshold"]) for f in frames]
    return hysteresis(raw, th["phase"]["hysteresis_exit_periods"])


@dataclass(frozen=True)
class BudgetCalibration:
    status: str               # "OK" albo "INCONCLUSIVE"
    reason: str
    rho_transitional: float
    rho_critical: float
    calib_months: list


def calibrate_budget(meta: list[BudgetMeta], th: dict) -> BudgetCalibration:
    """Percentyle rho z PIERWSZEJ polowy historii (druga polowa to okres potwierdzenia).

    Za malo historii albo percentyl zapadniety do zera -> INCONCLUSIVE i stale domyslne,
    zamiast udawanej kalibracji (lekcja z testu sieci energetycznej v0.1).
    """
    ph = th["phase"]
    d_t, d_c = ph["budget_rho_default_transitional"], ph["budget_rho_default_critical"]
    if len(meta) < ph["budget_min_history_months"]:
        return BudgetCalibration("INCONCLUSIVE", f"za malo historii: {len(meta)} < {ph['budget_min_history_months']} miesiecy", d_t, d_c, [])
    half = meta[: len(meta) // 2]
    rho = np.array([b.state.rho for b in half], dtype=float)
    p_t = float(np.percentile(rho, ph["percentile_transitional"]))
    p_c = float(np.percentile(rho, ph["percentile_critical"]))
    if p_t <= 0 or p_c <= 0:
        return BudgetCalibration("INCONCLUSIVE", "percentyl rho zapadl sie do zera (za malo zdarzen)", d_t, d_c, [b.month for b in half])
    return BudgetCalibration("OK", "percentyle z pierwszej polowy historii", p_t, p_c, [b.month for b in half])


def budget_phases(meta: list[BudgetMeta], calib: BudgetCalibration, th: dict,
                  hard_rule_months: set[str] | None = None) -> list[int]:
    hard_rule_months = hard_rule_months or set()
    raw = []
    for b in meta:
        rho = b.state.rho
        d_rho = abs(b.M.rho) if b.M is not None and is_finite(b.M.rho) else 0.0
        if b.month in hard_rule_months or rho > calib.rho_critical:
            raw.append(2)
        elif rho > calib.rho_transitional or d_rho > calib.rho_transitional:
            raw.append(1)
        else:
            raw.append(0)
    return hysteresis(raw, th["phase"]["hysteresis_exit_periods"])


def balance_hard_rule(records, horizon_days: int = 30) -> set[str]:
    """Twarda regula: prognozowane saldo < 0 w horyzoncie 30 dni.

    Prognoza = ostatnie saldo miesiaca + srednia miesieczna zmiana netto z 3 ostatnich miesiecy.
    Dziala tylko, gdy wyciag zawiera kolumne salda.
    """
    from collections import defaultdict
    last_balance: dict[str, tuple] = {}
    net = defaultdict(int)
    for r in sorted(records, key=lambda r: (r.date, r.raw_hash)):
        m = f"{r.date.year:04d}-{r.date.month:02d}"
        net[m] += r.amount_gr
        if r.balance_gr is not None:
            last_balance[m] = (r.date, r.balance_gr)
    months = sorted(last_balance)
    hits = set()
    for i, m in enumerate(months):
        prev = [net[x] for x in sorted(net) if x <= m][-3:]
        forecast = last_balance[m][1] + (sum(prev) / len(prev)) * (horizon_days / 30.0)
        if forecast < 0:
            hits.add(m)
    return hits


def hysteresis_detail(raw_levels: list[int], exit_periods: int) -> list[tuple[int, int]]:
    """Jak hysteresis(), ale zwraca tez licznik okresow ponizej biezacej fazy (do PhaseState)."""
    out, current, below = [], 0, 0
    for r in raw_levels:
        if r >= current:
            current, below = r, 0
        else:
            below += 1
            if below >= exit_periods:
                current, below = r, 0
        out.append((current, below))
    return out


def stream_rules_fired(f: SignalFrame, rel_threshold: float) -> list[str]:
    rules = []
    if f.defect and f.defect_rel is not None and abs(f.defect_rel) >= 2 * rel_threshold:
        rules.append("defekt >= 2x prog")
    for name, on in (("anomalia", f.anomaly), ("defekt", f.defect), ("skret", f.twist), ("ponad CPI", bool(f.baseline_hit))):
        if on:
            rules.append(name)
    return rules


def stream_phase_state(frames: list[SignalFrame], th: dict) -> dict:
    """Payload muz.phase_state/1 dla ostatniego miesiaca strumienia."""
    raw = [stream_raw_level(f, th["defect_rel_threshold"]) for f in frames]
    level, counter = hysteresis_detail(raw, th["phase"]["hysteresis_exit_periods"])[-1]
    return {"scope": "stream", "subject": frames[-1].stream_id, "period": frames[-1].month, "phase": NAMES[level],
            "rules_fired": stream_rules_fired(frames[-1], th["defect_rel_threshold"]),
            "hysteresis_counter": counter, "calibration_status": "PREREGISTERED"}
