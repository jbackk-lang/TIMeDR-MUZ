"""Test spojnosci polityki planow (decyzja v0.3) na pakietach budzetow: pelny przeplyw do bramki.
Uzycie (w katalogu repozytorium): python scripts/spojnosc_polityki.py [liczba_pakietow]
"""
import json, sys, time
from collections import Counter
from datetime import timedelta
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
__import__("os").chdir(ROOT)
import synth
from muz import pipeline, adapter, phases
from muz.mini_ai.policy import budget_policy, rule_policy, amount_12m_ago
th, th_sha = pipeline.load_frozen(pipeline.THRESHOLDS)
dec, dec_sha = pipeline.load_frozen(pipeline.DECISION)
cpi = adapter.load_cpi("dane/cpi.csv")
from muz.sim.generator import generate_package
N = int(sys.argv[1]) if len(sys.argv) > 1 else 60
stats = Counter(); viol = []; v01 = Counter(); examples = []
t0 = time.time()
for k in range(N):
    pkg = generate_package(900_000 + k, cpi=cpi)
    ctx = pipeline.prepare_records(pkg.records, cpi, pkg.contracts, th=th, th_sha=th_sha)
    today = max(r.date for r in ctx["records"]) + timedelta(days=1)
    for s in ctx["monthly"]:
        fs = ctx["frames"][s.stream_id]
        r = pipeline.run_stream(s, fs, ctx=ctx, dec=dec, dec_sha=dec_sha, profile=synth.PROFILE, today=today)
        ph = phases.stream_phase_state(fs, th)["phase"]
        cat = (s.contract or {}).get("category", "inne")
        stats["strumienie"] += 1
        if ph == "stabilna":
            stats["stabilne"] += 1; continue
        pol = budget_policy(fs, ph, s.contract, cpi.get(fs[-1].month), ctx["income_month_gr"], dec)
        gated = pol if pol in dec["allowed_by_phase"][ph] else "zostawic"
        if gated != pol: stats[f"bramka fazy zatrzymala: {pol} w fazie {ph}"] += 1
        old = rule_policy(fs[-1], ph, s.contract)
        v01["zgodne" if old == gated else "niezgodne"] += 1
        if old != "zostawic" and gated == "zostawic": v01["v0.1 dzialalaby, polityka budzetowa: zostawic"] += 1
        if old == "zostawic" and gated != "zostawic": v01["v0.1 pominelaby dzialanie"] += 1
        prop = r["proposal"]; plan = r["plan"]
        stats[f"propozycja:{prop['action']}"] += 1
        if prop["action"] != gated: viol.append(("propozycja != polityka", pkg.package_id, cat, prop["action"], gated))
        if plan is not None:
            stats[f"plan:{plan['action']}:{plan['level']}"] += 1
            if plan["action"] != gated: viol.append(("plan != polityka", pkg.package_id, cat, plan["action"], gated))
            if cat in dec["teacher"]["not_negotiable"]: viol.append(("plan dla kategorii nienegocjowalnej", pkg.package_id, cat))
            txt = plan["content"].get("text", "")
            base = amount_12m_ago(fs)
            if plan["action"] == "negocjowac" and f"{base / 100:.2f}".replace(".", ",") not in txt:
                viol.append(("pismo nie podaje kwoty sprzed roku", pkg.package_id, cat))
            if len(examples) < 2 and plan["action"] == "negocjowac": examples.append(txt)
        elif prop["action"] != "zostawic":
            stats[f"bez planu ({r['reason'][:60]})"] += 1
print(json.dumps({"pakiety": N, "sek": round(time.time() - t0), "wyniki": stats, "v0.1_vs_budzet": v01,
                  "naruszenia": len(viol), "przyklady_naruszen": viol[:10]}, ensure_ascii=False, indent=1, default=str))
if examples: print("\n--- przykladowe pismo ---\n" + examples[0])
