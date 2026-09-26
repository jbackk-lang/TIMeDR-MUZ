"""Generuje docs/przyklady_komunikatow.json: po jednym prawdziwym komunikacie kazdego z 10 schematow,
z przebiegu na danych syntetycznych (tests/synth.py). Uruchom z katalogu repo: python scripts/przyklady_komunikatow.py
"""
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import synth  # noqa: E402
from muz import adapter, pipeline  # noqa: E402
from muz.core import messages as msg  # noqa: E402
from muz.executor import LetterExecutor, approve, signing  # noqa: E402

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    (d / "map.json").write_text(json.dumps(synth.MAPPING, ensure_ascii=False), encoding="utf-8")
    (d / "umowy.json").write_text(json.dumps(synth.CONTRACTS, ensure_ascii=False), encoding="utf-8")
    (d / "profil.json").write_text(json.dumps(synth.PROFILE, ensure_ascii=False), encoding="utf-8")
    csv = synth.write_bank_csv(d / "w.csv", synth.transactions(21))
    pipeline.propose([csv], d / "map.json", d / "out", today=date(2025, 9, 15), profile_path=d / "profil.json",
                     contracts_path=d / "umowy.json", salt_path=d / "salt")
    envs = [json.loads(l) for l in (d / "out" / "komunikaty.jsonl").read_text(encoding="utf-8").splitlines()]
    plan = json.loads((d / "out" / "kolejka" / "plany.jsonl").read_text(encoding="utf-8").splitlines()[0])
    rec = adapter.load_csv(csv, synth.MAPPING, (d / "salt").read_bytes())[1]
    sk = b"\x07" * 32
    appr = approve(plan, decision="approve", secret_key=sk)
    receipt = LetterExecutor(signing.public_key(sk), d / "out" / "nadawcze").execute(plan, appr)
    extra = [msg.make("muz.lsf_record/1", adapter.record_payload(rec), adapter).to_dict(),
             msg.make("muz.approval/1", appr, approve).to_dict(),
             msg.make("muz.execution_receipt/1", receipt, LetterExecutor).to_dict()]
    out, seen = [], set()
    order = list(msg.SCHEMAS)
    plan_stream = plan["stream_id"]
    for e in sorted(extra + envs, key=lambda e: order.index(e["schema"])):
        p = e["payload"]
        sid = p.get("stream_id", p.get("subject"))
        if e["schema"] in seen or (sid is not None and sid != plan_stream and e["schema"] != "muz.lsf_record/1"):
            continue
        seen.add(e["schema"])
        out.append(e)
    (ROOT / "docs" / "przyklady_komunikatow.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str),
                                                               encoding="utf-8")
    print(len(out), "komunikatow:", [e["schema"] for e in out])
