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
THRESHOLDS = PREREG / "muz_thresholds_v0.2.json"
DECISION = PREREG / "muz_decision_v0.3.json"


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


FORMATS = REPO_DIR / "formaty.json"


def _load_records(inputs, mapping, salt, categories=None, info=None, formats_path=None):
    """MT940; wlasny CSV MUZ; CSV z mapowaniem z pliku; bez mapowania -- samodopasowanie i profil formatu."""
    from .adapter.autodetect import ProfileStore, resolve
    from .adapter.muz_csv import is_muz_csv, load_muz_csv
    records = []
    store = None
    for p in inputs:
        name = Path(p).name
        if str(p).lower().endswith(".pdf"):
            from .adapter.pdf_import import load_pdf
            records += load_pdf(p, salt)
            info is not None and info.append({"plik": name, "format": "PDF"})
        elif str(p).lower().endswith((".sta", ".mt940", ".940")):
            records += adapter.load_mt940(p, salt, mapping.get("aliases") if mapping else None)
            info is not None and info.append({"plik": name, "format": "MT940"})
        elif is_muz_csv(p):
            recs, cats = load_muz_csv(p, salt)
            records += recs
            if categories is not None:
                categories.update(cats)
            info is not None and info.append({"plik": name, "format": "CSV MUZ"})
        elif mapping:
            records += adapter.load_csv(p, mapping, salt)
            info is not None and info.append({"plik": name, "format": "mapowanie z pliku"})
        else:
            store = store or ProfileStore(formats_path or FORMATS)
            m, i = resolve(p, store)
            records += adapter.load_csv(p, m, salt)
            info is not None and info.append({"plik": name, "format": i["profile"], "nowy": i["new"],
                                              **({"dlaczego": i["reasons"]} if i["new"] else {})})
    return records


def prepare(inputs, mapping_path, cpi_path=None, contracts_path=None, salt_path=None, formats_path=None):
    """Pobranie + strumienie + sygnaly + META + fazy budzetu (wspolne dla etapow 0 i 1)."""
    vendor_sha = verify_vendor()
    th, th_sha = load_frozen(THRESHOLDS)
    mapping = json.loads(Path(mapping_path).read_text(encoding="utf-8")) if mapping_path else {}
    salt = local_salt(Path(salt_path) if salt_path else REPO_DIR / ".muz_salt")
    categories, info = {}, []
    records = _load_records(inputs, mapping, salt, categories, info, formats_path)
    cpi = adapter.load_cpi(cpi_path) if cpi_path else None
    contracts = adapter.load_contracts(contracts_path) if contracts_path else None
    ctx = prepare_records(records, cpi, contracts, th=th, th_sha=th_sha, vendor_sha=vendor_sha)
    ctx.update({"categories": categories, "import_info": info})
    ctx.update({"inputs": {Path(p).name: sha256_file(p) for p in inputs},
                "mapping_sha256": sha256_file(mapping_path) if mapping_path else None,
                "cpi_sha256": sha256_file(cpi_path) if cpi_path else None})
    return ctx


def prepare_records(records, cpi, contracts, *, th, th_sha, vendor_sha=None) -> dict:
    """Strumienie + sygnaly + META + fazy z gotowych rekordow LSF (wspolne dla plikow i pakietow budzetow)."""
    n_raw = len(records)
    records = adapter.deduplicate(records)
    streams = adapter.build_streams(records, th["recurring_min_payment_months"], th["monthly_min_coverage"])
    if contracts:
        adapter.attach_contracts(streams, contracts)
    monthly = [s for s in streams if s.cadence == "monthly"]
    with no_network():
        frames = {s.stream_id: signals.stream_signals(s, th, cpi) for s in monthly}
        res = signals.resonance_by_month(frames, th["resonance_min_count"])
        s_phases = {sid: phases.stream_phases(fs, th) for sid, fs in frames.items()}
        bmeta = meta.budget_meta(streams, frames, cpi, th["budget_min_streams"], th.get("J_definition", "slope"))
        calib = phases.calibrate_budget(bmeta, th)
        hard = phases.balance_hard_rule(records)
        b_phases = phases.budget_phases(bmeta, calib, th, hard)
        report = meta.validate_budget_meta(bmeta, [phases.NAMES[p] for p in b_phases]) if len(bmeta) >= 3 else None
    validator_sha = sha256_obj(report.format_report()) if report is not None else None
    from .mini_ai.train import income_month
    income = income_month(records)
    return {"th": th, "th_sha": th_sha, "vendor_sha": vendor_sha, "records": records, "n_raw": n_raw, "cpi": cpi,
            "streams": streams, "monthly": monthly, "frames": frames, "res": res, "s_phases": s_phases,
            "bmeta": bmeta, "calib": calib, "hard": hard, "b_phases": b_phases, "validator_report": report,
            "income_month_gr": income,
            "validator_sha": validator_sha, "inputs": {}, "mapping_sha256": None, "cpi_sha256": None}


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
    text += shadow_section(ctx, REPO_DIR / "modele")
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

def _change_basis(frames):
    """Podstawa pisma zgodna z polityka budzetowa: kwota rok temu -> teraz; miesiac zmiany = najwiekszy wzrost
    miesiac do miesiaca w tym okresie. Bez kwoty sprzed roku: poprzedni miesiac (jak w v0.1)."""
    from .mini_ai.policy import _month_minus_12, amount_12m_ago
    f = frames[-1]
    base = amount_12m_ago(frames)
    if not base:
        prev = frames[-2] if len(frames) >= 2 else f
        return f.month, prev.amount_gr, f.defect_rel
    window = [x for x in frames if x.month >= _month_minus_12(f.month)]
    jumps = [(b.amount_gr - a.amount_gr, b.month) for a, b in zip(window, window[1:])]
    month = max(jumps)[1] if jumps and max(jumps)[0] > 0 else f.month
    return month, base, f.amount_gr / base - 1.0


def _letter_fields(action, stream, frames, profile, today):
    c = stream.contract or {}
    f = frames[-1]
    month, before_gr, rel = _change_basis(frames)
    return {"miejscowosc": profile.get("miejscowosc", ""), "data": today.isoformat(),
            "imie_nazwisko": profile.get("imie_nazwisko", ""), "adres": profile.get("adres", ""),
            "kontrahent": c.get("legal_name", stream.counterparty), "adres_kontrahenta": c.get("address", ""),
            "numer_umowy": c.get("number", ""), "miesiac_zmiany": month,
            "kwota_przed": f"{before_gr / 100:.2f}".replace(".", ","),
            "kwota_po": f"{f.amount_gr / 100:.2f}".replace(".", ","),
            "zmiana": "" if rel is None else f"{rel * 100:+.1f}%".replace(".", ","),
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
        if "nowy_plan" in str(exc):
            return None, "brak planu: do zmiany planu potrzebny jest docelowy plan - dodaj pole target_plan w umowie"
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
                           b_last.M if b_last else None, cpi_m, ctx.get("income_month_gr"))
        proposal = mini_ai_propose(stream_id=stream.stream_id, x=x, frame=frames[-1], phase=ps["phase"],
                                   contract=stream.contract, cfg=dec, policy_sha256=dec_sha, model=model,
                                   weights_sha256=weights_sha, background=background, frames=frames, cpi_yoy=cpi_m,
                                   income_month_gr=ctx["income_month_gr"])
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


def shadow_section(ctx, models_dir: Path) -> str:
    """Tryb cienia: co zaproponowalby mini-AI uczony na pakietach syntetycznych. Nic z tego nie trafia do planow."""
    active = models_dir / "aktywny.json"
    if not active.exists():
        return ""
    from .ai_core.registry import ModelRegistry, NotSupported
    from .mini_ai.mlp import MLP
    cfg = json.loads(active.read_text(encoding="utf-8"))
    weights = models_dir / cfg["wagi"]
    try:
        sha = ModelRegistry(models_dir / "rejestr.json").require_supported(weights, allow_synthetic=True)
    except NotSupported as exc:
        return f"\n## Cień mini-AI\n\nModel niedostępny: {exc}\n"
    model = MLP.load(weights, expected_sha256=sha)
    dec, dec_sha = load_frozen(DECISION)
    with no_network():
        rows = _shadow_rows(ctx, model, sha, dec, dec_sha)
    head = ("\n## Cień mini-AI (model syntetyczny, tylko podgląd)\n\n"
            "Model uczony na pakietach budżetów syntetycznych (GUS 2024). Pokazuje, co by zaproponował; nie tworzy planów "
            "i nie wpływa na decyzje: plany tworzy polityka budżetowa (reguły), którą model odtwarza. "
            f"Wagi: {weights.name}, sha256 {sha[:12]}….\n\n")
    if not rows:
        return head + "Brak strumieni poza fazą stabilną.\n"
    return head + "| Kontrahent | Faza | Plan (polityka budżetowa) | mini-AI | Pewność |\n| --- | --- | --- | --- | --- |\n" + "\n".join(rows) + "\n"


def _shadow_rows(ctx, model, sha, dec, dec_sha) -> list[str]:
    rows = []
    for s in ctx["monthly"]:
        fs = ctx["frames"][s.stream_id]
        ps = phases.stream_phase_state(fs, ctx["th"])
        if ps["phase"] == "stabilna":
            continue
        b = next((b for b in reversed(ctx["bmeta"]) if b.month <= fs[-1].month), None)
        x = build_features(fs, ps["phase"], s.contract, b.state if b else None, b.M if b else None,
                           (ctx["cpi"] or {}).get(fs[-1].month), ctx["income_month_gr"])
        prop = mini_ai_propose(stream_id=s.stream_id, x=x, frame=fs[-1], phase=ps["phase"], contract=s.contract,
                               cfg=dec, policy_sha256=dec_sha, model=model, weights_sha256=sha)
        rule = mini_ai_propose(stream_id=s.stream_id, x=x, frame=fs[-1], phase=ps["phase"], contract=s.contract,
                               cfg=dec, policy_sha256=dec_sha, frames=fs, cpi_yoy=(ctx["cpi"] or {}).get(fs[-1].month),
                               income_month_gr=ctx["income_month_gr"])
        conf = f"{prop['confidence']:.2f}".replace(".", ",")
        note = " (niepewne)" if prop["abstained"] else ""
        rows.append(f"| {s.counterparty} | {ps['phase']} | {rule['action']} | {prop['action']}{note} | {conf} |")
    return rows


# ---------------------------------------------------------------------------
# Wyrazne decyzje: przydzial do wyplaty + karty dzialania dla umow
# ---------------------------------------------------------------------------

def decide(inputs, mapping_path, out_dir, *, today: date, profile_path=None, cpi_path=None, contracts_path=None,
           salt_path=None, log_path=None, formats_path=None) -> dict:
    from . import decisions
    ctx = prepare(inputs, mapping_path, cpi_path, contracts_path, salt_path, formats_path)
    dec, dec_sha = load_frozen(DECISION)
    profile = json.loads(Path(profile_path).read_text(encoding="utf-8")) if profile_path else {}
    plan = decisions.cycle_plan(ctx["records"], ctx["streams"], today=today, profile=profile,
                                categories=ctx.get("categories"))
    cards = decisions.contract_decisions(ctx, dec=dec, dec_sha=dec_sha, today=today)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "decyzje.md").write_text(decisions.render(plan, cards), encoding="utf-8")
    (out / "decyzje.json").write_text(decisions.to_json(plan, cards), encoding="utf-8")
    from . import export_docs
    from .adapter.muz_csv import write_records
    write_records(ctx["records"], out / "transakcje_muz.csv", ctx.get("categories"))
    pdfs, pdf_note = export_docs.decisions_pdfs(plan, cards, out / "pdf")
    export_docs.decisions_csv(plan, cards, out / "decyzje.csv", pdfs)
    summary = {"decyzje_umowy": len(cards), "tryb": plan.mode, "do_wyplaty_dni": plan.days,
               "import": ctx.get("import_info"), "decision_sha256": dec_sha,
               "pdf": pdf_note or len(pdfs),
               "outputs": {f.name: sha256_file(f) for f in (out / "decyzje.md", out / "decyzje.json", out / "decyzje.csv",
                                                            out / "transakcje_muz.csv", *pdfs.values())}}
    audit.append(Path(log_path) if log_path else out / "audit.jsonl", "decyzje", summary)
    titles = {i: (decisions.card_title(cards[i]) if i >= 0 else "Przydział do wypłaty") for i in pdfs}
    return {"plan": plan, "cards": cards, "summary": summary,
            "pdfs": [(titles[i], pdfs[i]) for i in sorted(pdfs)], "pdf_note": pdf_note,
            "excel": {"decyzje": out / "decyzje.csv", "transakcje": out / "transakcje_muz.csv"}}
