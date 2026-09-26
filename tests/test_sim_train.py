"""Pakiety budzetow (muz/sim) i uczenie mini-AI na nich (muz/mini_ai/train.py)."""
import json

import numpy as np
import pytest

from muz import pipeline
from muz.ai_core.registry import ModelRegistry, NotSupported
from muz.mini_ai.features import N_FEATURES
from muz.mini_ai.train import income_month, package_samples, train_and_register
from muz.sim import gus_bgd
from muz.sim.generator import generate_package
from muz.sim.teacher import teacher_action

TH, TH_SHA = pipeline.load_frozen(pipeline.THRESHOLDS)
DEC, DEC_SHA = pipeline.load_frozen(pipeline.DECISION)
CPI = {f"{y}-{m:02d}": 0.04 for y in range(2023, 2027) for m in range(1, 13)}


def test_gus_shares_sum_to_100_and_food_housing_falls_with_income():
    for q in range(1, 6):
        assert abs(sum(gus_bgd.category_shares(q).values()) - 100.0) < 1e-6
    assert gus_bgd.food_housing_share(1) > gus_bgd.food_housing_share(5)


def test_generator_is_deterministic():
    a, b = generate_package(7, cpi=CPI), generate_package(7, cpi=CPI)
    assert [(r.date, r.amount_gr, r.counterparty) for r in a.records] == \
           [(r.date, r.amount_gr, r.counterparty) for r in b.records]
    assert a.contracts == b.contracts


def test_generator_has_indefinite_contracts_outside_rent():
    # regresja: gdy tylko czynsz/kredyt nie mialy daty konca, model uczyl sie skrotu "brak daty konca -> zostawic"
    cs = [c for k in range(40) for c in generate_package(200 + k, cpi=CPI).contracts.values()
          if c["category"] in ("telekom", "energia", "media", "ubezpieczenie", "subskrypcja")]
    none = sum(c["end_date"] is None for c in cs)
    assert 0.25 < none / len(cs) < 0.55


def test_generator_quintiles_differ_in_income():
    inc = {q: np.mean([income_month(generate_package(100 + k, cpi=CPI, quintile=q).records) for k in range(15)])
           for q in (1, 3, 5)}
    assert inc[1] < inc[3] < inc[5]


def test_teacher_materiality_depends_on_income():
    kw = dict(amount_gr=12_000, amount_12m_ago_gr=10_000, cpi_yoy=0.04, cfg=DEC,
              contract={"category": "telekom", "negotiations": 0})
    # +20 zl/mies. = 240 zl/rok: istotne przy 3000 zl dochodu (> 90 zl), nieistotne przy 10000 zl? 3% z 10000 = 300 zl.
    assert teacher_action(income_month_gr=300_000, **kw) == "negocjowac"
    assert teacher_action(income_month_gr=1_000_000, **kw) == "zostawic"


def test_teacher_rules_by_category():
    base = dict(amount_gr=13_000, amount_12m_ago_gr=10_000, cpi_yoy=0.04, income_month_gr=300_000, cfg=DEC)
    assert teacher_action(contract={"category": "czynsz", "negotiations": 2}, **base) == "zostawic"
    assert teacher_action(contract={"category": "subskrypcja", "negotiations": 1}, **base) == "anulowac"
    assert teacher_action(contract={"category": "energia", "negotiations": 1}, **base) == "zmienic"
    assert teacher_action(contract={"category": "kredyt", "negotiations": 2}, **base) == "negocjowac"
    assert teacher_action(contract={"category": "energia", "negotiations": 1}, **(base | {"cpi_yoy": None})) == "zostawic"


def test_package_samples_have_42_features_and_skip_stable():
    s = package_samples(generate_package(3, cpi=CPI), TH, DEC, CPI)
    assert s and all(len(x["x"]) == N_FEATURES == 42 for x in s)
    assert all(x["phase"] != "stabilna" for x in s)


def test_train_registers_synthetic_and_blocks_plans(tmp_path):
    res = train_and_register(out_dir=tmp_path / "m", th=TH, th_sha=TH_SHA, dec=DEC, dec_sha=DEC_SHA, cpi=CPI,
                             cpi_sha=None, n_packages=10, seed=1)
    node, card = res["node"], res["card"]
    assert node["synthetic"] is True and card["tryb"] == "cien"
    assert json.loads((tmp_path / "m" / "karta.json").read_text(encoding="utf-8"))["dane"].startswith("SYNTETYCZNE")
    reg = ModelRegistry(tmp_path / "rejestr.json")
    with pytest.raises(NotSupported) as e:
        reg.require_supported(tmp_path / "m" / "wagi.npz")
    if node["verdict"] == "SUPPORTED":
        assert "SYNTHETIC_ONLY" in str(e.value)
        assert reg.require_supported(tmp_path / "m" / "wagi.npz", allow_synthetic=True) == node["artifact_sha256"]
        assert (tmp_path / "aktywny.json").exists()


def test_shadow_section_in_report(tmp_path):
    import sys
    sys.path.insert(0, str(pipeline.REPO_DIR / "tests"))
    import synth
    models = tmp_path / "modele"
    assert pipeline.shadow_section({}, models) == ""          # brak modelu -> brak sekcji
    res = train_and_register(out_dir=models / "m", th=TH, th_sha=TH_SHA, dec=DEC, dec_sha=DEC_SHA, cpi=CPI,
                             cpi_sha=None, n_packages=10, seed=1)
    (tmp_path / "map.json").write_text(json.dumps(synth.MAPPING, ensure_ascii=False), encoding="utf-8")
    csv = synth.write_bank_csv(tmp_path / "w.csv", synth.transactions(30))
    ctx = pipeline.prepare([csv], tmp_path / "map.json", salt_path=tmp_path / "salt")
    assert ctx["income_month_gr"] > 0
    text = pipeline.shadow_section(ctx, models)
    if res["node"]["verdict"] == "SUPPORTED":
        assert "Cień mini-AI (model syntetyczny" in text and "nie tworzy planów" in text
    else:
        assert text == ""
