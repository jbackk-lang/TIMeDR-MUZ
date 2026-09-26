"""Przeplyw danych MUZ (dokument, sekcja "Przeplyw danych"):

pobranie -> strumienie -> sygnaly M/S -> META-DYNAMICS -> faza -> propozycja -> weryfikacja -> bramka
-> wykonanie -> pokwitowanie. Kazdy krok to komunikat w kopercie z hashami rodzicow; warstwy decyzyjne
(sygnaly, META, fazy, mini-AI, AI-Core) dzialaja pod no_network().

run()        - etap 0: raport tylko do odczytu (bez propozycji),
run_stream() - przyklad pelnego przebiegu dla jednego strumienia az do planu w bramce,
propose()    - etap 1: plany dla wszystkich strumieni, zapisywane w kolejce do zatwierdzenia.
"""
from __future__ import annotations

import csv
import json
import secrets
from datetime import date
from pathlib import Path

from . import __version__, adapter, audit, meta, phases, signals
from .ai_core.claims import verify_proposal
from .core import messages as msg
from .core.common import PKG_DIR, sha256_file, sha256_obj, verify_vendor
from .core.netguard import no_network
from .executor import letters as letters_mod
from .executor.gate import GateError, make_plan
from .mini_ai.features import build_features
from .mini_ai.policy import propose as mini_ai_propose

REPO_DIR = PKG_DIR.parent
PREREG = REPO_DIR / "prereg"
THRESHOLDS = PREREG / "muz_thresholds_v0.1.json"
DECISION = PREREG / "muz_decision_v0.1.json"


class FrozenFileChanged(RuntimeError):
    pass


def load_frozen(path) -> tuple[dict, str]:
    """Plik progow/decyzji laduje sie tylko, gdy jego hash zgadza sie z prereg/FROZEN.json."""
    path = Path(path)
    frozen = json.loads((PREREG / "FROZEN.json").read_text(encoding="utf-8"))
    sha = sha256_file(path)
    if frozen.get(path.name) != sha:
        raise FrozenFileChanged(f"INCONCLUSIVE_THRESHOLDS_CHANGED: {path.name} ({sha[:12]}) nie zgadza sie z "
                                f"prereg/FROZEN.json - zmiana wymaga nowej pre-rejestracji")
    return json.loads(path.read_text(encoding="utf-8")), sha


def local_salt(path: Path) -> bytes:
    if path.exists():
        return path.read_bytes()
    salt = secrets.token_bytes(32)
    path.write_bytes(salt)
    return salt


def _load_records(inputs, mapping, salt):
    records = []
    for p in inputs:
        if str(p).lower().endswith((".sta", ".mt940", ".940")):
            records += adapter.load_mt940(p, salt, mapping.get("aliases") if mapping else None)
        else:
            records += adapter.load_csv(p, mapping, salt)
    return records


def prepare(inputs, mapping_path, cpi_path=None, contracts_path=None, salt_path=None):
    """Pobranie + strumienie + sygnaly + META + fazy budzetu (wspolne dla etapow 0 i 1)."""
    vendor_sha = verify_vendor()
    th, th_sha = load_frozen(THRESHOLDS)
    mapping = json.loads(Path(mapping_path).read_text(encoding="utf-8")) if mapping_path else {}
    salt = local_salt(Path(salt_path) if salt_path else REPO_DIR / ".muz_salt")
    records = _load_records(inputs, mapping, salt)
    n_raw = len(records)
    records = adapter.deduplicate(records)
    cpi = adapter.load_cpi(cpi_path) if cpi_path else None
    streams = adapter.build_streams(records, th["recurring_min_payment_months"], th["monthly_min_coverage"])
    if contracts_path:
        adapter.attach_contracts(streams, adapter.load_contracts(contracts_path))
    monthly = [s for s in streams if s.cadence == "monthly"]
    with no_network():
        frames = {s.stream_id: signals.stream_signals(s, th, cpi) for s in monthly}
        res = signals.resonance_by_month(frames, th["resonance_min_count"])
        s_phases = {sid: phases.stream_phases(fs, th) for sid, fs in frames.items()}
        bmeta = meta.budget_meta(streams, frames, cpi, th["budget_min_streams"])
        calib = phases.calibrate_budget(bmeta, th)
        hard = phases.balance_hard_rule(records)
        b_phases = phases.budget_phases(bmeta, calib, th, hard)
        report = meta.validate_budget_meta(bmeta, [phases.NAMES[p] for p in b_phases]) if len(bmeta) >= 3 else None
    validator_sha = sha256_obj(report.format_report()) if report is not None else None
    return {"th": th, "th_sha": th_sha, "vendor_sha": vendor_sha, "records": records, "n_raw": n_raw, "cpi": cpi,
            "streams": streams, "monthly": monthly, "frames": frames, "res": res, "s_phases": s_phases,
            "bmeta": bmeta, "calib": calib, "hard": hard, "b_phases": b_phases, "validator_report": report,
            "validator_sha": validator_sha,
            "inputs": {Path(p).name: sha256_file(p) for p in inputs},
            "mapping_sha256": sha256_file(mapping_path) if mapping_path else None,
            "cpi_sha256": sha256_file(cpi_path) if cpi_path else None}


# ---------------------------------------------------------------------------
# Etap 0: raport tylko do odczytu
# ---------------------------------------------------------------------------

def run(inputs, mapping_path, out_dir, cpi_path=None, contracts_path=None, salt_path=None, log_path=None) -> dict:
    ctx = prepare(inputs, mapping_path, cpi_path, contracts_path, salt_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_csvs(out, ctx)
    from .report import render
    text = render(streams=ctx["streams"], frames=ctx["frames"], s_phases=ctx["s_phases"], bmeta=ctx["bmeta"],
                  b_phases=ctx["b_phases"], calib=ctx["calib"], res=ctx["res"], hard=ctx["hard"],
                  cpi_given=ctx["cpi"] is not None,
                  hashes={"progi": ctx["th_sha"], "vendor_lock": ctx["vendor_sha"], "wersja_muz": __version__,
                          "raport_meta_validator": ctx["validator_sha"] or "brak (za malo miesiecy)"},
                  n_raw=ctx["n_raw"], n_records=len(ctx["records"]))
    if ctx["validator_report"] is not None:
        text += "\n## Raport walidatora META (TIMDR-Math-Formalism)\n\n```text\n" + ctx["validator_report"].format_report() + "\n```\n"
    (out / "raport_etap0.md").write_text(text, encoding="utf-8")
    summary = {"inputs": ctx["inputs"], "mapping_sha256": ctx["mapping_sha256"], "cpi_sha256": ctx["cpi_sha256"],
               "thresholds_sha256": ctx["th_sha"], "vendor_lock_sha256": ctx["vendor_sha"], "muz_version": __version__,
               "n_records_raw": ctx["n_raw"], "n_records": len(ctx["records"]), "n_streams": len(ctx["streams"]),
               "n_monthly_streams": len(ctx["monthly"]), "budget_calibration": ctx["calib"].status,
               "outputs": {f.name: sha256_file(f) for f in sorted(out.glob("*")) if f.suffix in (".md", ".csv")}}
    audit.append(Path(log_path) if log_path else out / "audit.jsonl", "etap0_run", summary)
    return summary


def _write_csvs(out, ctx):
    names = {s.stream_id: s.counterparty for s in ctx["streams"]}
    with (out / "sygnaly.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["kontrahent", "miesiac", "kwota_zl", "anomalia", "defekt", "zmiana_wzgl", "skret",
                    "baseline_cpi", "rr", "faza", "rezonans_M_w_miesiacu"])
        for sid, fs in ctx["frames"].items():
            for f, ph in zip(fs, ctx["s_phases"][sid]):
                w.writerow([names[sid], f.month, f"{f.amount_gr / 100:.2f}", int(f.anomaly), int(f.defect),
                            "" if f.defect_rel is None else f"{f.defect_rel:.4f}", int(f.twist),
                            "" if f.baseline_hit is None else int(f.baseline_hit),
                            "" if f.yoy is None else f"{f.yoy:.4f}", phases.NAMES[ph],
                            int(ctx["res"].get(f.month, {}).get("resonance_m", False))])
    with (out / "budzet_meta.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["miesiac", "strumienie", "Lambda", "tau", "rho", "J", "faza"])
        for b, ph in zip(ctx["bmeta"], ctx["b_phases"]):
            s = b.state
            w.writerow([b.month, b.n_streams] + [("" if not meta.is_finite(v) else f"{v:.4f}")
                                                 for v in (s.Lambda, s.tau, s.rho, s.J)] + [phases.NAMES[ph]])


# ---------------------------------------------------------------------------
# Przebieg jednego strumienia az do planu w bramce
# ---------------------------------------------------------------------------

def _letter_fields(action, stream, frames, profile, today):
    c = stream.contract or {}
    f, prev = frames[-1], frames[-2] if len(frames) >= 2 else frames[-1]
    return {"miejscowosc": profile.get("miejscowosc", ""), "data": today.isoformat(),
            "imie_nazwisko": profile.get("imie_nazwisko", ""), "adres": profile.get("adres", ""),
            "kontrahent": c.get("legal_name", stream.counterparty), "adres_kontrahenta": c.get("address", ""),
            "numer_umowy": c.get("number", ""), "miesiac_zmiany": f.month,
            "kwota_przed": f"{prev.amount_gr / 100:.2f}".replace(".", ","),
            "kwota_po": f"{f.amount_gr / 100:.2f}".replace(".", ","),
            "zmiana": "" if f.defect_rel is None else f"{f.defect_rel * 100:+.1f}%".replace(".", ","),
            "okres_wypowiedzenia": c.get("notice_period_months", ""), **({"nowy_plan": c["target_plan"]} if c.get("target_plan") else {})}


def build_plan(proposal, claim, stream, frames, profile, today) -> tuple[dict | None, str | None]:
    """Plan akcji dla bramki albo (None, powod). Formularz, gdy umowa wskazuje kanal 'form', inaczej pismo."""
    if claim["verdict"] != "SUPPORTED" or proposal["action"] == "zostawic":
        return None, f"brak planu: werdykt {claim['verdict']}, akcja {proposal['action']}"
    channel = (stream.contract or {}).get("cancel_channel") or {}
    try:
        if channel.get("type") == "form" and proposal["action"] in ("anulowac", "zmienic"):
            values = {k: v for k, v in _letter_fields(proposal["action"], stream, frames, profile, today).items()}
            plan = make_plan(claim=claim, proposal=proposal, executor="form", target_host=channel["host"],
                             content={"recipe": channel["recipe"], "values": values}, level="L2")
        else:
            text, tpl, tpl_sha = letters_mod.render_letter(proposal["action"],
                                                          _letter_fields(proposal["action"], stream, frames, profile, today))
            plan = make_plan(claim=claim, proposal=proposal, executor="letter", target_host="local",
                             content={"text": text, "template": tpl, "template_sha256": tpl_sha,
                                      "to_email": channel.get("email", ""), "subject": f"{stream.counterparty}: {proposal['action']}"},
                             level=letters_mod.level_for(proposal["action"]))
    except (KeyError, GateError) as exc:
        return None, f"brak planu: {exc}"
    return plan, None


def run_stream(stream, frames, *, ctx, dec, dec_sha, profile, today: date, model=None, weights_sha=None,
               background=None) -> dict:
    """Pelny przebieg dla jednego strumienia. Zwraca {"envelopes": [...], "plan": dict|None, "reason": str|None}."""
    th, th_sha = ctx["th"], ctx["th_sha"]
    envs = []
    e_stream = msg.make("muz.stream/1", adapter.stream_payload(stream), adapter)
    envs.append(e_stream)
    with no_network():
        e_sf = msg.make("muz.signal_frame/1", signals.signal_frame_payload(frames[-1], th_sha), signals, [e_stream.id])
        envs.append(e_sf)
        b_last = next((b for b in reversed(ctx["bmeta"]) if b.month <= frames[-1].month), None)
        parents_meta = []
        if b_last is not None:
            e_meta = msg.make("muz.meta_state/1", meta.meta_payload(b_last, ctx["validator_sha"]), meta, [e_sf.id])
            envs.append(e_meta)
            parents_meta = [e_meta.id]
        ps = phases.stream_phase_state(frames, th)
        e_phase = msg.make("muz.phase_state/1", ps, phases, [e_sf.id, *parents_meta])
        envs.append(e_phase)
        cpi_m = (ctx["cpi"] or {}).get(frames[-1].month)
        x = build_features(frames, ps["phase"], stream.contract, b_last.state if b_last else None,
                           b_last.M if b_last else None, cpi_m)
        proposal = mini_ai_propose(stream_id=stream.stream_id, x=x, frame=frames[-1], phase=ps["phase"],
                                   contract=stream.contract, cfg=dec, policy_sha256=dec_sha, model=model,
                                   weights_sha256=weights_sha, background=background)
        if proposal is None:
            return {"envelopes": envs, "plan": None, "reason": "faza stabilna: tylko monitoring"}
        e_prop = msg.make("muz.action_proposal/1", proposal, mini_ai_propose, [e_phase.id])
        envs.append(e_prop)
        last_date = max(r.date for r in ctx["records"])
        claim = verify_proposal(proposal=proposal, stream=stream, frames=frames, cpi=ctx["cpi"],
                                data_as_of=last_date, today=today)
        e_claim = msg.make("muz.verified_claim/1", claim, verify_proposal, [e_prop.id])
        envs.append(e_claim)
    plan, reason = build_plan(proposal, claim, stream, frames, profile, today)
    if plan is not None:
        envs.append(msg.make("muz.action_plan/1", plan, make_plan, [e_claim.id]))
    return {"envelopes": envs, "plan": plan, "reason": reason, "proposal": proposal, "claim": claim}


def propose(inputs, mapping_path, out_dir, *, today: date, profile_path=None, cpi_path=None, contracts_path=None,
            salt_path=None, log_path=None, model=None, weights_sha=None, background=None) -> dict:
    """Etap 1: plany dla wszystkich strumieni poza faza stabilna, zapisane w kolejce do zatwierdzenia."""
    ctx = prepare(inputs, mapping_path, cpi_path, contracts_path, salt_path)
    dec, dec_sha = load_frozen(DECISION)
    profile = json.loads(Path(profile_path).read_text(encoding="utf-8")) if profile_path else {}
    out = Path(out_dir)
    (out / "kolejka").mkdir(parents=True, exist_ok=True)
    log = Path(log_path) if log_path else out / "audit.jsonl"
    counts = {"plany": 0, "zostawic": 0, "bez_planu": 0, "stabilne": 0}
    with (out / "kolejka" / "plany.jsonl").open("a", encoding="utf-8") as plans_fh, \
            (out / "komunikaty.jsonl").open("a", encoding="utf-8") as env_fh:
        for s in ctx["monthly"]:
            r = run_stream(s, ctx["frames"][s.stream_id], ctx=ctx, dec=dec, dec_sha=dec_sha, profile=profile,
                           today=today, model=model, weights_sha=weights_sha, background=background)
            for e in r["envelopes"]:
                env_fh.write(json.dumps(e.to_dict(), ensure_ascii=False, default=str) + "\n")
            if r["plan"] is not None:
                plans_fh.write(json.dumps(r["plan"], ensure_ascii=False) + "\n")
                counts["plany"] += 1
                audit.append(log, "plan_utworzony", {"plan_sha256": r["plan"]["plan_sha256"], "level": r["plan"]["level"],
                                                     "executor": r["plan"]["executor"], "claim_id": r["plan"]["claim_id"]})
            elif r["reason"] and r["reason"].startswith("faza stabilna"):
                counts["stabilne"] += 1
            elif r.get("claim", {}).get("verdict") == "SUPPORTED" and r["proposal"]["action"] == "zostawic":
                counts["zostawic"] += 1
            else:
                counts["bez_planu"] += 1
                audit.append(log, "odrzucone", {"stream_id": s.stream_id, "reason": r["reason"],
                                                "claim": (r.get("claim") or {}).get("verdict")})
    return counts
