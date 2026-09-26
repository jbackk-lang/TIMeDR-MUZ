"""Interfejsy: koperta, 10 schematow komunikatow, wersjonowanie."""
import pytest

from muz.core import messages as msg

EXAMPLES = {
    "muz.lsf_record/1": {"date": "2025-09-05", "amount_gr": -11900, "currency": "PLN", "counterparty": "ORANGE POLSKA",
                         "iban_hash": "3f1c...", "source": "wyciag.csv", "raw_hash": "ab12..."},
    "muz.stream/1": {"stream_id": "aa797c92d563", "counterparty": "ORANGE POLSKA", "contract": None, "cadence": "monthly",
                     "series": [["2025-08", 8900], ["2025-09", 11900]]},
    "muz.signal_frame/1": {"stream_id": "aa797c92d563", "month": "2025-09", "flags": {"anomaly": False, "defect": True, "twist": False},
                           "strengths": {"defect_rel": 0.337}, "baseline_hit": None, "thresholds_sha256": "8bdc56bc..."},
    "muz.meta_state/1": {"scope": "budget", "period": "2025-09", "Lambda": 0.0, "tau": 0.25, "rho": 0.25, "J": None,
                         "M": None, "validator_report_sha256": None},
    "muz.phase_state/1": {"scope": "stream", "subject": "aa797c92d563", "period": "2025-09", "phase": "krytyczna",
                          "rules_fired": ["defekt >= 2x prog"], "hysteresis_counter": 0, "calibration_status": "PREREGISTERED"},
    "muz.action_proposal/1": {"stream_id": "aa797c92d563", "probabilities": {"anulowac": 0, "negocjowac": 1, "zmienic": 0, "zostawic": 0},
                              "action": "negocjowac", "confidence": 1.0, "top_features": [], "weights_sha256": "d40cbc22...",
                              "abstained": False},
    "muz.verified_claim/1": {"claim_id": "muz:aa797c92d563:2025-09", "verdict": "SUPPORTED", "record_ids": ["lsf:2814ead7"],
                             "requirements_met": True, "text": "...", "graph_sha256": "..."},
    "muz.action_plan/1": {"plan_id": "p1", "claim_id": "muz:aa797c92d563:2025-09", "executor": "letter", "target_host": "local",
                          "content": {"text": "..."}, "level": "L1", "plan_sha256": "..."},
    "muz.approval/1": {"plan_sha256": "...", "decision": "approve", "signature": "...", "public_key": "...",
                       "expires_at": "2025-09-15T12:15:00+00:00"},
    "muz.execution_receipt/1": {"plan_sha256": "...", "status": "done", "evidence": {"pdf_sha256": "..."},
                                "finished_at": "2025-09-15T12:03:10+00:00"},
}


def test_all_ten_schemas_have_examples_and_validate():
    assert set(EXAMPLES) == set(msg.SCHEMAS) and len(EXAMPLES) == 10
    for schema, payload in EXAMPLES.items():
        msg.validate_payload(schema, payload)


def test_envelope_hash_parents_and_producer():
    a = msg.make("muz.stream/1", EXAMPLES["muz.stream/1"], msg)
    b = msg.make("muz.signal_frame/1", EXAMPLES["muz.signal_frame/1"], msg.make, [a.id])
    msg.verify(a); msg.verify(b)
    assert b.parents == (a.id,) and len(a.producer["code_sha256"]) == 64
    tampered = msg.Envelope(**{**a.to_dict(), "parents": (), "payload": {**a.payload, "cadence": "irregular"}})
    with pytest.raises(msg.SchemaError):
        msg.verify(tampered)


def test_unknown_major_version_rejected():
    with pytest.raises(msg.SchemaError):
        msg.validate_payload("muz.stream/2", EXAMPLES["muz.stream/1"])
    with pytest.raises(msg.SchemaError):
        msg.validate_payload("muz.stream/1", {"stream_id": "x"})
