"""CLI TIMeDR-MUZ.

  python -m muz run      --in wyciag.csv [--in wyciag.sta] --mapping mapowanie.json [--cpi cpi.csv] --out wyniki
  python -m muz propose  --in ... --mapping ... --contracts umowy.json --profile profil.json --out wyniki
  python -m muz keygen   --key ~/.muz/bramka.key
  python -m muz setpin   --pin-file ~/.muz/pin.json
  python -m muz approve  --plans wyniki/kolejka/plany.jsonl --plan-id ID --key ~/.muz/bramka.key [--pin-file ...]
  python -m muz execute  --plans ... --plan-id ID --approval wyniki/kolejka/ID.approval.json --pubkey HEX --out wyniki
  python -m muz verify   --log wyniki/audit.jsonl
  python -m muz train    [--cpi dane/cpi.csv] [--packages 600] [--out modele/mini_ai_syntetyczny_v0.2]
  python -m muz badanie  [--n 400] [--seed 20260929] [--scen S0,S1,S2] [--out wyniki/badanie_petla.json]
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import date
from pathlib import Path

from . import audit, pipeline
from .executor import gate, signing
from .executor.ics import ICSExecutor
from .executor.letters import LetterExecutor
from .executor.qr import QRTransferExecutor


def _find_plan(plans_path, plan_id):
    for line in Path(plans_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            p = json.loads(line)
            if p["plan_id"].startswith(plan_id):
                return p
    raise SystemExit(f"nie ma planu {plan_id}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="muz", description="TIMeDR-MUZ (lokalny, audytowalny)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "propose"):
        r = sub.add_parser(name)
        r.add_argument("--in", dest="inputs", action="append", required=True)
        r.add_argument("--mapping")
        r.add_argument("--cpi")
        r.add_argument("--contracts")
        r.add_argument("--out", required=True)
        r.add_argument("--log")
        if name == "propose":
            r.add_argument("--profile")
    sub.add_parser("keygen").add_argument("--key", required=True)
    sub.add_parser("setpin").add_argument("--pin-file", required=True)
    a_ = sub.add_parser("approve")
    a_.add_argument("--plans", required=True); a_.add_argument("--plan-id", required=True)
    a_.add_argument("--key", required=True); a_.add_argument("--pin-file"); a_.add_argument("--reject", action="store_true")
    e_ = sub.add_parser("execute")
    e_.add_argument("--plans", required=True); e_.add_argument("--plan-id", required=True)
    e_.add_argument("--approval"); e_.add_argument("--pubkey", required=True); e_.add_argument("--out", required=True)
    sub.add_parser("verify").add_argument("--log", required=True)
    t_ = sub.add_parser("train")
    t_.add_argument("--cpi"); t_.add_argument("--packages", type=int)
    t_.add_argument("--out", default=str(pipeline.REPO_DIR / "modele" / "mini_ai_syntetyczny_v0.2"))
    b_ = sub.add_parser("badanie", help="symulacja zamknietej petli budzetu (MUZ-SIM v0.1)")
    b_.add_argument("--n", type=int, default=400); b_.add_argument("--seed", type=int, default=20260929)
    b_.add_argument("--scen", default="S0,S1,S2"); b_.add_argument("--out")
    a = ap.parse_args(argv)

    if a.cmd == "badanie":
        from .badania.petla_run import main as badanie
        res = badanie(a.n, a.seed, a.scen.split(","))
        txt = json.dumps(res, indent=1, ensure_ascii=False)
        if a.out:
            Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(txt, encoding="utf-8")
        for sc in a.scen.split(","):
            print(sc, {k: round(v["ok"], 3) for k, v in res[sc]["mean"].items()})
        return 0

    if a.cmd == "train":
        from . import adapter
        from .core.common import sha256_file
        from .mini_ai.train import train_and_register
        th, th_sha = pipeline.load_frozen(pipeline.THRESHOLDS)
        dec, dec_sha = pipeline.load_frozen(pipeline.DECISION)
        cpi_path = a.cpi or (pipeline.REPO_DIR / "dane" / "cpi.csv")
        cpi = adapter.load_cpi(cpi_path) if Path(cpi_path).exists() else None
        res = train_and_register(out_dir=a.out, th=th, th_sha=th_sha, dec=dec, dec_sha=dec_sha, cpi=cpi,
                                 cpi_sha=sha256_file(cpi_path) if cpi else None, n_packages=a.packages)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if a.cmd == "run":
        s = pipeline.run(a.inputs, a.mapping, a.out, cpi_path=a.cpi, contracts_path=a.contracts, log_path=a.log)
        print(json.dumps({k: s[k] for k in ("n_records", "n_streams", "n_monthly_streams", "budget_calibration")}, ensure_ascii=False))
        print(f"raport: {a.out}/raport_etap0.md")
    elif a.cmd == "propose":
        c = pipeline.propose(a.inputs, a.mapping, a.out, today=date.today(), profile_path=a.profile, cpi_path=a.cpi,
                             contracts_path=a.contracts, log_path=a.log)
        print(json.dumps(c, ensure_ascii=False), f"\nkolejka: {a.out}/kolejka/plany.jsonl")
    elif a.cmd == "keygen":
        print("klucz publiczny bramki:", signing.generate_key(Path(a.key).expanduser()).hex())
    elif a.cmd == "setpin":
        gate.set_pin(Path(a.pin_file).expanduser(), getpass.getpass("nowy PIN: "))
    elif a.cmd == "approve":
        plan = _find_plan(a.plans, a.plan_id)
        print(json.dumps({k: plan[k] for k in ("executor", "target_host", "level", "action", "claim_text")}, ensure_ascii=False, indent=1))
        print("--- tresc ---\n" + json.dumps(plan["content"], ensure_ascii=False, indent=1))
        pin = getpass.getpass("PIN (L2): ") if plan["level"] == "L2" and not a.reject else None
        appr = gate.approve(plan, decision="reject" if a.reject else "approve",
                            secret_key=signing.load_secret(Path(a.key).expanduser()), pin=pin,
                            pin_path=Path(a.pin_file).expanduser() if a.pin_file else None)
        out = Path(a.plans).parent / f"{plan['plan_id'][:12]}.approval.json"
        out.write_text(json.dumps(appr, indent=1), encoding="utf-8")
        audit.append(Path(a.plans).parent.parent / "audit.jsonl", "zatwierdzenie", {"plan_sha256": plan["plan_sha256"], "decision": appr["decision"]})
        print("zapisano", out, "- wazne 15 minut")
    elif a.cmd == "execute":
        plan = _find_plan(a.plans, a.plan_id)
        approval = json.loads(Path(a.approval).read_text(encoding="utf-8")) if a.approval else None
        pk = bytes.fromhex(a.pubkey)
        ex = {"letter": lambda: LetterExecutor(pk, Path(a.out) / "nadawcze"), "ics": lambda: ICSExecutor(pk, Path(a.out) / "terminy"),
              "qr": lambda: QRTransferExecutor(pk, Path(a.out) / "przelewy")}.get(plan["executor"])
        if ex is None:
            raise SystemExit(f"wykonawca {plan['executor']} wymaga konfiguracji (np. przepis formularza)")
        receipt = ex().execute(plan, approval)
        audit.append(Path(a.out) / "audit.jsonl", "pokwitowanie", receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=1))
    else:
        ok, m = audit.verify(a.log)
        print(m)
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
