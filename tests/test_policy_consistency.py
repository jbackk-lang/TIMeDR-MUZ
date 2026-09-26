"""Spojnosc: plany w bramce wynikaja z polityki budzetowej (decyzja v0.3), a nie z reguly v0.1."""
import json
from datetime import date, timedelta

import synth
from muz import adapter, phases, pipeline
from muz.mini_ai.policy import amount_12m_ago, budget_policy
from muz.sim.generator import generate_package

TH, TH_SHA = pipeline.load_frozen(pipeline.THRESHOLDS)
DEC, DEC_SHA = pipeline.load_frozen(pipeline.DECISION)
CPI = {f"{y}-{m:02d}": 0.03 for y in range(2023, 2027) for m in range(1, 13)}


def test_decision_v03_changes_only_plan_policy():
    v2, _ = pipeline.load_frozen(pipeline.PREREG / "muz_decision_v0.2.json")
    same = lambda d: {k: v for k, v in d.items() if k not in ("version", "note", "rule_policy", "budget_policy")}
    assert same(v2) == same(DEC) and DEC["budget_policy"]["rules_from"] == "teacher"


def test_plans_follow_budget_policy_on_packages():
    n_plans, checked = 0, 0
    for k in range(15):
        pkg = generate_package(900_000 + k, cpi=CPI)
        ctx = pipeline.prepare_records(pkg.records, CPI, pkg.contracts, th=TH, th_sha=TH_SHA)
        today = max(r.date for r in ctx["records"]) + timedelta(days=1)
        for s in ctx["monthly"]:
            fs = ctx["frames"][s.stream_id]
            ph = phases.stream_phase_state(fs, TH)["phase"]
            r = pipeline.run_stream(s, fs, ctx=ctx, dec=DEC, dec_sha=DEC_SHA, profile=synth.PROFILE, today=today)
            if ph == "stabilna":
                assert r["plan"] is None
                continue
            pol = budget_policy(fs, ph, s.contract, CPI.get(fs[-1].month), ctx["income_month_gr"], DEC)
            gated = pol if pol in DEC["allowed_by_phase"][ph] else "zostawic"
            checked += 1
            assert r["proposal"]["action"] == gated
            if r["plan"] is not None:
                n_plans += 1
                assert r["plan"]["action"] == gated != "zostawic"
                assert (s.contract or {}).get("category", "inne") not in DEC["teacher"]["not_negotiable"]
                base = amount_12m_ago(fs)
                assert f"{base / 100:.2f}".replace(".", ",") in r["plan"]["content"]["text"]
            elif r["proposal"]["action"] == "zmienic":
                assert "target_plan" in r["reason"]
    assert checked > 20 and n_plans > 0


def test_example_statement_plans(tmp_path):
    (tmp_path / "map.json").write_text(json.dumps(synth.MAPPING, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "umowy.json").write_text(json.dumps(synth.CONTRACTS, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "cpi.csv").write_text("miesiac;cpi_rr\n" + "".join(f"{m};3,0\n" for m in CPI), encoding="utf-8")
    csv = synth.write_bank_csv(tmp_path / "w.csv", synth.transactions(21))
    pipeline.propose([csv], tmp_path / "map.json", tmp_path / "out", today=date(2025, 9, 15),
                     contracts_path=tmp_path / "umowy.json", cpi_path=tmp_path / "cpi.csv",
                     profile_path=None, salt_path=tmp_path / "salt")
    plans = [json.loads(l) for l in (tmp_path / "out" / "kolejka" / "plany.jsonl").read_text(encoding="utf-8").splitlines()]
    envs = [json.loads(l) for l in (tmp_path / "out" / "komunikaty.jsonl").read_text(encoding="utf-8").splitlines()]
    props = {e["payload"]["stream_id"]: e["payload"] for e in envs if e["schema"] == "muz.action_proposal/1"}
    assert [p["action"] for p in plans] == ["negocjowac"]
    assert all(p["source"] == "budget_rules" for p in props.values())
    # czynsz (nienegocjowalny) i strumienie bez potwierdzonej umowy: zostawic
    assert sum(p["action"] != "zostawic" for p in props.values()) == 1
