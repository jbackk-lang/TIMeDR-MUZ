"""Protokol TIMDR: prerejestracja progow, run_controls, run_test, Bonferroni, baseline vs sygnaly TIMDR."""
import json
import shutil

import numpy as np
import pytest

from muz import pipeline
from muz._vendor.ai_core.timdr_ai_core import (ControlResult, Hypothesis, ProtocolCriteria, TestEvidence,
                                                TIMDRProtocol)
from muz._vendor.math_formalism.pipeline import bonferroni_correct
from muz.ai_core import validation
from muz.core import common
from muz.signals import SignalFrame


# --- prerejestracja i zamrozenie ---

def test_frozen_files_match():
    for name in ("muz_thresholds_v0.1.json", "muz_decision_v0.1.json"):
        pipeline.load_frozen(pipeline.PREREG / name)


def test_changed_thresholds_are_refused(tmp_path, monkeypatch):
    shutil.copytree(pipeline.PREREG, tmp_path / "prereg")
    p = tmp_path / "prereg" / "muz_thresholds_v0.1.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["defect_rel_threshold"] = 0.05  # "dostrojenie po fakcie"
    p.write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.setattr(pipeline, "PREREG", tmp_path / "prereg")
    with pytest.raises(pipeline.FrozenFileChanged):
        pipeline.load_frozen(p)


def test_changed_vendor_file_is_refused(tmp_path, monkeypatch):
    shutil.copytree(common.VENDOR_DIR, tmp_path / "_vendor")
    f = tmp_path / "_vendor" / "topologic" / "defect.py"
    f.write_text(f.read_text(encoding="utf-8") + "\n# zmiana\n", encoding="utf-8")
    monkeypatch.setattr(common, "VENDOR_DIR", tmp_path / "_vendor")
    with pytest.raises(common.VendorMismatch):
        common.verify_vendor()


def test_preregistration_fingerprint_is_deterministic():
    h = Hypothesis("P1", "sygnaly M/S vs baseline CPI", "r(TIMDR) - r(baseline) >= 0.1", {"alpha": 0.05, "margin": 0.1})
    a, b = TIMDRProtocol().preregister(h), TIMDRProtocol().preregister(h)
    assert a.fingerprint == b.fingerprint and len(a.fingerprint) == 64


# --- run_controls ---

def test_run_controls_positive_and_negative_pass():
    mf, core = validation.controls_for_defect(n_windows=30, seed=0)
    assert mf.passed and core.passed


def test_missing_controls_never_pass():
    proto = TIMDRProtocol()
    assert proto.run_controls(None).passed is False


# --- run_test ---

def test_run_test_requires_controls_and_evidence():
    proto = TIMDRProtocol()
    ok = ControlResult(True, True)
    assert proto.run_test(ControlResult(True, False), TestEvidence(0.001, 0.5, "MW")).verdict == "INCONCLUSIVE"
    assert proto.run_test(ok, None).verdict == "INCONCLUSIVE"
    assert proto.run_test(ok, TestEvidence(0.001, 0.5, "MW")).verdict == "SUPPORTED"
    assert proto.run_test(ok, TestEvidence(0.2, 0.5, "MW")).verdict == "NOT_SUPPORTED"


# --- Bonferroni ---

def test_bonferroni():
    assert bonferroni_correct(0.012, 4) == pytest.approx(0.048)
    assert bonferroni_correct(0.3, 4) == 1.0
    with pytest.raises(ValueError):
        bonferroni_correct(0.1, 0)


# --- regresja: baseline vs sygnaly TIMDR (P1) ---

def _frame(i, defect, base, anomaly=False):
    return SignalFrame("s", f"2025-{i % 12 + 1:02d}", 100, anomaly, None, defect, 0.2 if defect else 0.0, False, base, 0.0)


def test_p1_supported_when_signal_beats_baseline():
    rng = np.random.default_rng(0)
    rows = []
    for i in range(200):
        y = int(rng.random() < 0.3)
        defect = bool(y) if rng.random() < 0.9 else not y      # sygnal mocno zwiazany z etykieta
        base = bool(rng.random() < 0.3)                         # baseline niezwiazany
        rows.append((_frame(i, defect, base), y))
    ev = validation.p1_signals_vs_baseline(rows)
    res = TIMDRProtocol(ProtocolCriteria(alpha=0.05, min_abs_effect_size=0.1)).run_test(ControlResult(True, True), ev)
    assert res.verdict == "SUPPORTED" and ev.details["best_signal"] in ("defect", "any_flag")


def test_p1_not_supported_when_signal_equals_baseline():
    rng = np.random.default_rng(1)
    rows = []
    for i in range(200):
        y = int(rng.random() < 0.3)
        flag = bool(y) if rng.random() < 0.9 else not y
        rows.append((_frame(i, flag, flag), y))                 # TIMDR = baseline -> brak przewagi
    ev = validation.p1_signals_vs_baseline(rows)
    assert ev.effect_size == pytest.approx(0.0) and ev.p_value == 1.0
    res = TIMDRProtocol(ProtocolCriteria(alpha=0.05, min_abs_effect_size=0.1)).run_test(ControlResult(True, True), ev)
    assert res.verdict == "NOT_SUPPORTED"


def test_p1_opposite_direction_cannot_pass():
    rng = np.random.default_rng(2)
    rows = []
    for i in range(200):
        y = int(rng.random() < 0.3)
        base = bool(y) if rng.random() < 0.95 else not y        # baseline lepszy
        defect = bool(y) if rng.random() < 0.6 else not y
        rows.append((_frame(i, defect, base), y))
    ev = validation.p1_signals_vs_baseline(rows)
    assert ev.effect_size < 0 and ev.p_value == 1.0


def test_model_selection_margin():
    assert validation.select_model(0.50, 0.60, margin=0.05) is True
    assert validation.select_model(0.58, 0.60, margin=0.05) is False
