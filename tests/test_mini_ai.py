"""Modul 5: mini-AI (NumPy MLP), polityka regulowa, bramka fazy, rejestr modeli."""
import numpy as np
import pytest

from muz._vendor.ai_core.timdr_ai_core import ControlResult, Hypothesis, ProtocolCriteria, TestEvidence
from muz.ai_core.registry import ModelRegistry, NotSupported
from muz.core.messages import ACTIONS
from muz.mini_ai import FEATURE_NAMES, MLP, log_loss, propose, rule_policy
from muz.pipeline import DECISION, load_frozen
from muz.signals import SignalFrame

DEC, DEC_SHA = load_frozen(DECISION)


def _toy(n=600, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.random((n, 40))
    y = (X[:, 0] > 0.5).astype(int) + 2 * (X[:, 1] > 0.5).astype(int)  # 4 klasy z dwoch cech
    return X, y


def test_feature_names():
    assert len(FEATURE_NAMES) == 42 and len(set(FEATURE_NAMES)) == 42


def test_mlp_learns_and_roundtrips(tmp_path):
    X, y = _toy(n=2000)
    m = MLP(seed=0).fit(X[:1600], y[:1600], epochs=100)
    acc = (m.predict_proba(X[1600:]).argmax(1) == y[1600:]).mean()
    assert acc > 0.9
    m.fit_temperature(X[1600:], y[1600:])
    sha = m.save(tmp_path / "w.npz")
    m2 = MLP.load(tmp_path / "w.npz", expected_sha256=sha)
    assert np.allclose(m.predict_proba(X[:5]), m2.predict_proba(X[:5]))
    with pytest.raises(RuntimeError):
        MLP.load(tmp_path / "w.npz", expected_sha256="0" * 64)


def test_logistic_baseline_same_code():
    X, y = _toy()
    lr = MLP(sizes=(40, 4)).fit(X, y, epochs=50)
    assert log_loss(lr.predict_proba(X), y) < np.log(4)


def test_permutation_importance_finds_used_features():
    X, y = _toy()
    m = MLP(seed=0).fit(X, y, epochs=150)
    cls = int(m.predict_proba(X[0]).argmax())
    imp = m.permutation_importance(X[0], X[:200], cls)
    assert set(np.argsort(-imp)[:2]) == {0, 1}


def _frame(defect=True, base=None):
    return SignalFrame("s", "2025-09", 11900, False, None, defect, 0.337 if defect else 0.0, False, base, None)


def test_stable_phase_gives_no_proposal():
    assert propose(stream_id="s", x=np.zeros(40), frame=_frame(), phase="stabilna", contract=None, cfg=DEC,
                   policy_sha256=DEC_SHA) is None


def test_rule_policy():
    assert rule_policy(_frame(True), "przejsciowa", None) == "negocjowac"
    assert rule_policy(_frame(False), "przejsciowa", None) == "zostawic"
    assert rule_policy(_frame(True), "krytyczna", {"negotiations": 1, "category": "subskrypcja"}) == "anulowac"
    assert rule_policy(_frame(True), "krytyczna", {"negotiations": 1, "category": "telekom"}) == "zmienic"


class _Fixed:
    def __init__(self, p):
        self.p = np.array([p])

    def predict_proba(self, x):
        return self.p


def test_abstain_below_threshold_and_phase_gate():
    low = propose(stream_id="s", x=np.zeros(40), frame=_frame(), phase="krytyczna", contract=None, cfg=DEC,
                  policy_sha256=DEC_SHA, model=_Fixed([0.4, 0.3, 0.2, 0.1]), weights_sha256="w")
    assert low["abstained"] and low["action"] == "zostawic" and low["note"] == "niepewne"
    gated = propose(stream_id="s", x=np.zeros(40), frame=_frame(), phase="przejsciowa", contract=None, cfg=DEC,
                    policy_sha256=DEC_SHA, model=_Fixed([0.9, 0.05, 0.03, 0.02]), weights_sha256="w")
    assert gated["abstained"] and gated["action"] == "zostawic"  # anulowac niedozwolone w fazie przejsciowej
    ok = propose(stream_id="s", x=np.zeros(40), frame=_frame(), phase="przejsciowa", contract=None, cfg=DEC,
                 policy_sha256=DEC_SHA, model=_Fixed([0.05, 0.8, 0.1, 0.05]), weights_sha256="w")
    assert not ok["abstained"] and ok["action"] == "negocjowac" and set(ok["probabilities"]) == set(ACTIONS)


def test_registry_loads_only_supported_weights(tmp_path):
    X, y = _toy()
    m = MLP(seed=0).fit(X, y, epochs=20)
    m.save(tmp_path / "w.npz")
    reg = ModelRegistry(tmp_path / "rejestr.json")
    with pytest.raises(NotSupported):
        reg.require_supported(tmp_path / "w.npz")
    h = Hypothesis("P2 MLP vs regulowa", "MLP bije polityke regulowa", "log-loss o >= 0.05 lepszy", {"margin": 0.05})
    node = reg.evaluate_and_register(artifact_path=tmp_path / "w.npz", hypothesis=h, controls=None, evidence=None)
    assert node["verdict"] == "INCONCLUSIVE"
    with pytest.raises(NotSupported):
        reg.require_supported(tmp_path / "w.npz")
    node = reg.evaluate_and_register(artifact_path=tmp_path / "w.npz", hypothesis=h, controls=ControlResult(True, True),
                                     evidence=TestEvidence(0.001, 0.2, "log-loss held-out, permutacja"),
                                     criteria=ProtocolCriteria(0.05, 0.05))
    assert node["verdict"] == "SUPPORTED"
    assert reg.require_supported(tmp_path / "w.npz") == node["artifact_sha256"]
