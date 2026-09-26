"""Pelny przeplyw: pobranie -> sygnaly -> faza -> propozycja -> weryfikacja -> bramka -> wykonanie -> pokwitowanie."""
import json
from datetime import date

import pytest

from muz import audit, pipeline
from muz.__main__ import main
from muz.core import messages as msg
from muz.executor import LetterExecutor, approve, signing
import synth


@pytest.fixture()
def files(tmp_path):
    (tmp_path / "map.json").write_text(json.dumps(synth.MAPPING, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "umowy.json").write_text(json.dumps(synth.CONTRACTS, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "profil.json").write_text(json.dumps(synth.PROFILE, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_etap0_report_and_audit(files):
    csv = synth.write_bank_csv(files / "w.csv", synth.transactions(30))
    s = pipeline.run([csv], files / "map.json", files / "out", salt_path=files / "salt")
    rep = (files / "out" / "raport_etap0.md").read_text(encoding="utf-8")
    assert "tylko odczyt" in rep and "ORANGE POLSKA" in rep and "Rezonans M" in rep
    assert s["n_monthly_streams"] == 4 and audit.verify(files / "out" / "audit.jsonl")[0]


def test_full_flow_to_receipt(files):
    pytest.importorskip("reportlab")
    csv = synth.write_bank_csv(files / "w21.csv", synth.transactions(21))
    counts = pipeline.propose([csv], files / "map.json", files / "out", today=date(2025, 9, 15),
                              profile_path=files / "profil.json", contracts_path=files / "umowy.json", salt_path=files / "salt")
    assert counts["plany"] == 1
    plan = json.loads((files / "out" / "kolejka" / "plany.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert plan["executor"] == "letter" and plan["level"] == "L1" and plan["action"] == "negocjowac"
    assert "89,00 zł do 119,00 zł" in plan["content"]["text"]

    # lancuch komunikatow: kazdy rodzic istnieje, hashe tresci sie zgadzaja
    envs = [json.loads(l) for l in (files / "out" / "komunikaty.jsonl").read_text(encoding="utf-8").splitlines()]
    ids = {e["id"] for e in envs}
    for e in envs:
        msg.verify(msg.Envelope(**{**e, "parents": tuple(e["parents"])}))
        assert all(p in ids for p in e["parents"])
    chain = [e["schema"] for e in envs if e["payload"].get("stream_id", e["payload"].get("subject")) == plan["stream_id"]
             or e["schema"] in ("muz.meta_state/1", "muz.verified_claim/1", "muz.action_plan/1")]
    for schema in ("muz.stream/1", "muz.signal_frame/1", "muz.phase_state/1", "muz.action_proposal/1",
                   "muz.verified_claim/1", "muz.action_plan/1"):
        assert schema in chain

    # bramka + wykonanie + pokwitowanie
    sk = b"\x07" * 32
    appr = approve(plan, decision="approve", secret_key=sk)
    ex = LetterExecutor(signing.public_key(sk), files / "out" / "nadawcze")
    if ex.font_path is None:
        pytest.skip("brak czcionki TTF")
    receipt = ex.execute(plan, appr)
    msg.validate_payload("muz.execution_receipt/1", receipt)
    audit.append(files / "out" / "audit.jsonl", "pokwitowanie", receipt)
    assert audit.verify(files / "out" / "audit.jsonl")[0]


def test_cli_verify(files, capsys):
    audit.append(files / "a.jsonl", "e", {})
    assert main(["verify", "--log", str(files / "a.jsonl")]) == 0
    assert "poprawny" in capsys.readouterr().out


def test_plain_text_report_aligns_tables():
    from muz.report import plain_text
    t = plain_text("# Tytuł\n\n| A | Bbb |\n| --- | --- |\n| 1 | 2 |\n\n**x** `y`")
    lines = t.splitlines()
    assert lines[0] == "TYTUŁ" and "|" not in t and "**" not in t
    assert lines[3].startswith("A  Bbb") and lines[5].startswith("1  2")
