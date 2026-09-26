"""Modul 6: twierdzenia o decyzji (Claim Graph)."""
import copy
from datetime import date

import pytest

from muz import adapter, signals
from muz.ai_core.claims import verify_proposal
from muz.pipeline import THRESHOLDS, load_frozen
import synth

TH, _ = load_frozen(THRESHOLDS)
TODAY = date(2025, 9, 15)
AS_OF = date(2025, 9, 12)


@pytest.fixture(scope="module")
def orange(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("c")
    recs = adapter.load_csv(synth.write_bank_csv(tmp / "w.csv", synth.transactions(21)), synth.MAPPING, b"s" * 32)
    s = [x for x in adapter.build_streams(recs) if x.counterparty == "ORANGE POLSKA"][0]
    s.contract = copy.deepcopy(synth.CONTRACTS[0])
    return s, signals.stream_signals(s, TH)


def _prop(action="negocjowac"):
    return {"stream_id": "s", "action": action}


def test_supported_with_evidence(orange):
    s, fr = orange
    c = verify_proposal(proposal=_prop(), stream=s, frames=fr, cpi=None, data_as_of=AS_OF, today=TODAY)
    assert c["verdict"] == "SUPPORTED"
    assert sum(r.startswith("lsf:") for r in c["record_ids"]) == 2 and any(r.startswith("umowa:") for r in c["record_ids"])
    assert "+33,7%" in c["text"] and "Werdykt: SUPPORTED" in c["text"]


def test_stale_data_inconclusive(orange):
    s, fr = orange
    c = verify_proposal(proposal=_prop(), stream=s, frames=fr, cpi=None, data_as_of=date(2025, 9, 1), today=TODAY)
    assert c["verdict"] == "INCONCLUSIVE" and any("dni" in r for r in c["reasons"])


def test_user_explained_change_rejected(orange):
    s, fr = orange
    s2 = copy.deepcopy(s)
    s2.contract["explained_changes"] = ["2025-09"]
    c = verify_proposal(proposal=_prop(), stream=s2, frames=fr, cpi=None, data_as_of=AS_OF, today=TODAY)
    assert c["verdict"] == "REJECTED"


def test_cancel_requires_notice_and_channel(orange):
    s, fr = orange
    s2 = copy.deepcopy(s)
    del s2.contract["notice_period_months"]
    c = verify_proposal(proposal=_prop("anulowac"), stream=s2, frames=fr, cpi=None, data_as_of=AS_OF, today=TODAY)
    assert c["verdict"] == "INCONCLUSIVE" and not c["requirements_met"]


def test_paraphrase_gate(orange):
    s, fr = orange
    base = verify_proposal(proposal=_prop(), stream=s, frames=fr, cpi=None, data_as_of=AS_OF, today=TODAY)
    bad = verify_proposal(proposal=_prop(), stream=s, frames=fr, cpi=None, data_as_of=AS_OF, today=TODAY,
                          paraphrase="Gwarantowana oszczędność! SUPPORTED " + " ".join(base["record_ids"]))
    assert bad["paraphrase_gate"]["accepted"] is False and bad["text"] == base["text"]
    good_text = "Podwyżka o 33,7%, werdykt SUPPORTED, dowody: " + ", ".join(base["record_ids"])
    good = verify_proposal(proposal=_prop(), stream=s, frames=fr, cpi=None, data_as_of=AS_OF, today=TODAY,
                           paraphrase=good_text)
    assert good["paraphrase_gate"]["accepted"] is True and good["text"] == good_text
