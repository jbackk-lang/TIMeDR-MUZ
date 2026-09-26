"""Moduly 2-4: sygnaly M/S, META-DYNAMICS, fazy."""
import math
from pathlib import Path

import numpy as np
import pytest

from muz import adapter, meta, phases, signals
from muz.pipeline import THRESHOLDS, load_frozen
import synth

TH, TH_SHA = load_frozen(THRESHOLDS)


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("d")
    recs = adapter.load_csv(synth.write_bank_csv(tmp / "w.csv", synth.transactions(30)), synth.MAPPING, b"s" * 32)
    streams = adapter.build_streams(recs)
    monthly = {s.counterparty: s for s in streams if s.cadence == "monthly"}
    frames = {s.stream_id: signals.stream_signals(s, TH) for s in monthly.values()}
    return monthly, frames, streams


def _flags(frames, month):
    return {f.month: f for f in frames}[month]


def test_defect_on_price_rise(data):
    monthly, frames, _ = data
    f = _flags(frames[monthly["ORANGE POLSKA"].stream_id], "2025-09")
    assert f.defect and abs(f.defect_rel - 30 / 89) < 1e-9


def test_anomaly_on_double_bill(data):
    monthly, frames, _ = data
    f = _flags(frames[monthly["PGE OBROT"].stream_id], "2025-04")
    assert f.anomaly and f.anomaly_z > 3


def test_constant_stream_has_no_flags_before_indexation(data):
    monthly, frames, _ = data
    assert not any(f.any_flag for f in frames[monthly["NETFLIX COM"].stream_id] if f.month < "2026-01")


def test_resonance_m_on_january_indexation(data):
    _, frames, _ = data
    res = signals.resonance_by_month(frames, TH["resonance_min_count"])
    assert res["2026-01"]["resonance_m"] and res["2026-01"]["n_events"] >= 3
    assert not res["2025-06"]["resonance_m"]


def test_signals_are_causal(data):
    """Zmiana przyszlych kwot nie zmienia sygnalow wczesniejszych miesiecy."""
    monthly, frames, _ = data
    s = monthly["PGE OBROT"]
    import copy
    s2 = copy.deepcopy(s)
    s2.amounts_gr[25:] = [x * 3 for x in s2.amounts_gr[25:]]
    a, b = signals.stream_signals(s, TH), signals.stream_signals(s2, TH)
    assert a[:25] == b[:25]


def test_budget_meta_ranges(data):
    _, frames, streams = data
    bm = meta.budget_meta(streams, frames, None)
    assert bm and all(0.0 <= b.state.rho <= 1.0 for b in bm)
    assert all(math.isnan(b.state.J) for b in bm)  # brak CPI -> J niepoliczone, nie zero
    assert bm[1].M is not None and bm[1].M.rho == pytest.approx(bm[1].state.rho - bm[0].state.rho)


def test_budget_J_with_cpi(data):
    _, frames, streams = data
    cpi = {synth.month_date(i, 1).strftime("%Y-%m"): 0.03 + 0.001 * i for i in range(30)}
    bm = meta.budget_meta(streams, frames, cpi)
    assert any(meta.is_finite(b.state.J) for b in bm)


def test_hysteresis_enter_now_exit_after_two():
    assert phases.hysteresis([0, 2, 0, 0, 0, 1, 0], 2) == [0, 2, 2, 0, 0, 1, 1]


def test_stream_phase_state_payload(data):
    monthly, frames, _ = data
    fs = frames[monthly["ORANGE POLSKA"].stream_id]
    idx = [f.month for f in fs].index("2025-09")
    ps = phases.stream_phase_state(fs[: idx + 1], TH)
    assert ps["phase"] == "krytyczna" and "defekt >= 2x prog" in ps["rules_fired"]


def _fake_meta(rhos):
    from muz._vendor.meta_state import MetaState
    return [meta.BudgetMeta(f"2024-{i + 1:02d}", 4, MetaState(0.0, 0.0, r, float("nan")), None) for i, r in enumerate(rhos)]


def test_calibration_inconclusive_short_history():
    c = phases.calibrate_budget(_fake_meta([0.5] * 10), TH)
    assert c.status == "INCONCLUSIVE" and c.rho_transitional == TH["phase"]["budget_rho_default_transitional"]


def test_calibration_inconclusive_when_percentile_collapses():
    c = phases.calibrate_budget(_fake_meta([0.0] * 30), TH)
    assert c.status == "INCONCLUSIVE" and "zera" in c.reason


def test_calibration_ok_uses_first_half_only():
    rng = np.random.default_rng(0)
    rhos = list(rng.uniform(0.1, 0.5, 15)) + [1.0] * 15
    c = phases.calibrate_budget(_fake_meta(rhos), TH)
    assert c.status == "OK" and c.rho_critical < 0.6  # druga polowa (1.0) nie wplywa na progi


def test_balance_hard_rule():
    from datetime import date
    R = adapter.LSFRecord
    recs = [R(date(2024, 1, 2), -150000, "PLN", "X", "", "", 1000, "f", "a"),
            R(date(2024, 2, 2), -150000, "PLN", "X", "", "", 500, "f", "b")]
    assert phases.balance_hard_rule(recs) >= {"2024-02"}


def test_twist_on_trend_reversal():
    from muz.adapter import Stream
    amounts = [10000, 11000, 12000, 13000, 12000, 11000]  # wzrost, potem spadek
    s = Stream("t", "T", [f"2024-{i + 1:02d}" for i in range(6)], amounts, "monthly")
    fr = signals.stream_signals(s, TH)
    assert [f.twist for f in fr] == [False, False, False, False, False, True]  # szczyt daje nachylenie 0


def test_J_v02_is_bounded_spearman_and_slope_kept(data):
    _, frames, streams = data
    cpi = {synth.month_date(i, 1).strftime("%Y-%m"): 0.03 + 0.001 * i for i in range(30)}
    bm = meta.budget_meta(streams, frames, cpi, j_definition="spearman")
    js = [b.state.J for b in bm if meta.is_finite(b.state.J)]
    assert js and all(-1.0 <= j <= 1.0 for j in js)
    assert any(meta.is_finite(b.j_slope) for b in bm)
    old = meta.budget_meta(streams, frames, cpi, j_definition="slope")
    assert [b.j_slope for b in old] == [b.j_slope for b in bm]  # nachylenie takie samo w obu wersjach
    with pytest.raises(ValueError):
        meta.budget_meta(streams, frames, cpi, j_definition="tanh")


def test_spearman_known_values():
    assert meta.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert meta.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert meta.spearman([1, 2, 3, 100], [1, 2, 3, 4]) == pytest.approx(1.0)  # odporna na wartosc odstajaca
    assert math.isnan(meta.spearman([1, 1, 1], [1, 2, 3]))


def test_thresholds_v01_still_frozen_and_v02_active():
    from muz import pipeline
    th1, _ = pipeline.load_frozen(pipeline.PREREG / "muz_thresholds_v0.1.json")
    th2, _ = pipeline.load_frozen(pipeline.THRESHOLDS)
    assert "J_definition" not in th1 and th2["J_definition"] == "spearman"
    assert {k: v for k, v in th2.items() if k not in ("version", "note", "J_definition", "J_window_months", "J_min_points")} == \
           {k: v for k, v in th1.items() if k not in ("version", "note")}
