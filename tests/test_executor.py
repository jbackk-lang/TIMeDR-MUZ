"""Modul 7: bramka (Ed25519, poziomy L0-L3) i wykonawcy (PDF, formularz, QR, ICS)."""
from datetime import datetime, timedelta, timezone

import pytest

from muz.core.netguard import HostNotAllowed
from muz.executor import (FormExecutor, GateError, ICSExecutor, LetterExecutor, QRTransferExecutor, approve,
                          make_plan, render_letter, verify_approval, zbp_payload)
from muz.executor import ed25519_ref, gate, signing
from muz.executor.qr import QRDataError, nrb_valid

SK = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
PK = signing.public_key(SK)
CLAIM = {"claim_id": "muz:s:2025-09", "verdict": "SUPPORTED", "text": "t", "record_ids": ["lsf:a"]}
PROP = {"stream_id": "s", "action": "negocjowac"}


def _plan(executor="letter", level="L1", host="local", content=None, action="negocjowac"):
    return make_plan(claim=CLAIM, proposal=PROP | {"action": action}, executor=executor, target_host=host,
                     content=content or {"text": "Treść pisma ąęłńóśźż", "template": "t", "template_sha256": "x"},
                     level=level)


def test_ed25519_rfc8032_vector_and_cross_check():
    assert ed25519_ref.public_key(SK).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    assert ed25519_ref.sign(SK, b"").hex().startswith("e5564300c360ac729086e2cc806e828a")
    assert ed25519_ref.sign(SK, b"plan") == signing.sign(SK, b"plan")


def test_plan_requires_supported_claim():
    with pytest.raises(GateError):
        make_plan(claim=CLAIM | {"verdict": "INCONCLUSIVE"}, proposal=PROP, executor="letter", target_host="local",
                  content={}, level="L1")


def test_approval_signature_and_tamper():
    plan = _plan()
    appr = approve(plan, decision="approve", secret_key=SK)
    verify_approval(plan, appr, PK)
    tampered = dict(plan, content={"text": "inna treść"})
    with pytest.raises(GateError):
        verify_approval(tampered, appr, PK)
    with pytest.raises(GateError):
        verify_approval(plan, appr, signing.public_key(b"\x01" * 32))
    forged = dict(appr, decision="approve", signature="00" * 64)
    with pytest.raises(GateError):
        verify_approval(plan, forged, PK)


def test_approval_expires_after_15_minutes():
    plan = _plan()
    t0 = datetime(2025, 9, 15, 12, 0, tzinfo=timezone.utc)
    appr = approve(plan, decision="approve", secret_key=SK, now=t0)
    verify_approval(plan, appr, PK, now=t0 + timedelta(minutes=14))
    with pytest.raises(GateError):
        verify_approval(plan, appr, PK, now=t0 + timedelta(minutes=16))


def test_rejected_plan_cannot_run():
    plan = _plan()
    with pytest.raises(GateError):
        verify_approval(plan, approve(plan, decision="reject", secret_key=SK), PK)


def test_l2_requires_pin(tmp_path):
    plan = _plan(level="L2", action="anulowac")
    gate.set_pin(tmp_path / "pin.json", "4821")
    with pytest.raises(GateError):
        approve(plan, decision="approve", secret_key=SK)
    with pytest.raises(GateError):
        approve(plan, decision="approve", secret_key=SK, pin="0000", pin_path=tmp_path / "pin.json")
    approve(plan, decision="approve", secret_key=SK, pin="4821", pin_path=tmp_path / "pin.json")


def test_l0_ics_runs_without_approval(tmp_path):
    plan = _plan(executor="ics", level="L0", content={"date": "2027-05-31", "summary": "Termin wypowiedzenia",
                                                       "description": "Orange, umowa TEL/123/2023"})
    r = ICSExecutor(PK, tmp_path).execute(plan, None)
    text = (tmp_path / r["evidence"]["ics"]).read_text(encoding="utf-8")
    assert "DTSTART;VALUE=DATE:20270531" in text and "BEGIN:VALARM" in text


def test_letter_pdf_and_eml(tmp_path):
    pytest.importorskip("reportlab")
    text, tpl, sha = render_letter("negocjowac", {"miejscowosc": "Warszawa", "data": "2025-09-15", "imie_nazwisko": "Jan",
                                                  "adres": "a", "kontrahent": "Orange", "adres_kontrahenta": "b",
                                                  "numer_umowy": "1", "miesiac_zmiany": "2025-09", "kwota_przed": "89,00",
                                                  "kwota_po": "119,00", "zmiana": "+33,7%"})
    plan = _plan(content={"text": text, "template": tpl, "template_sha256": sha})
    ex = LetterExecutor(PK, tmp_path)
    if ex.font_path is None:
        pytest.skip("brak czcionki TTF")
    with pytest.raises(GateError):
        ex.execute(plan, None)
    r = ex.execute(plan, approve(plan, decision="approve", secret_key=SK))
    pdf = (tmp_path / r["evidence"]["pdf"]).read_bytes()
    assert pdf.startswith(b"%PDF") and r["evidence"]["template_sha256"] == sha
    assert (tmp_path / r["evidence"]["eml"]).exists()


def test_letter_template_missing_field():
    with pytest.raises(KeyError):
        render_letter("anulowac", {"imie_nazwisko": "Jan"})


def test_zbp_qr_payload_matches_standard():
    nrb = "61109010140000071219812874"
    assert nrb_valid(nrb) and not nrb_valid(nrb[:-1] + "5")
    p = zbp_payload(nrb=nrb, amount_gr=1200, name="Odbiorca 1", title="FV 1234/34/2012", nip="1234567890")
    assert p == "1234567890|PL|61109010140000071219812874|001200|Odbiorca 1|FV 1234/34/2012|||"
    assert zbp_payload(nrb=nrb, amount_gr=1, name="X" * 30, title="Y" * 40).split("|")[4] == "X" * 20
    for bad in (dict(amount_gr=0), dict(amount_gr=1_000_000), dict(nip="123")):
        with pytest.raises(QRDataError):
            zbp_payload(**({"nrb": nrb, "amount_gr": 100, "name": "a", "title": "b"} | bad))


def test_qr_executor_l3(tmp_path):
    plan = _plan(executor="qr", level="L3", content={"nrb": "61109010140000071219812874", "amount_gr": 11900,
                                                      "name": "Orange Polska", "title": "Abonament 09/2025"})
    ex = QRTransferExecutor(PK, tmp_path)
    with pytest.raises(GateError):
        ex.execute(plan, None)
    r = ex.execute(plan, approve(plan, decision="approve", secret_key=SK))
    assert (tmp_path / r["evidence"]["txt"]).read_text(encoding="utf-8").startswith("|PL|6110")
    assert "SCA" in r["evidence"]["note"]


class FakePage:
    def __init__(self):
        self.actions = []

    def goto(self, url): self.actions.append(("goto", url))
    def wait_for_selector(self, sel, timeout=0): self.actions.append(("wait", sel))
    def fill(self, sel, val): self.actions.append(("fill", sel, val))
    def click(self, sel): self.actions.append(("click", sel))
    def screenshot(self, path): open(path, "wb").write(b"png")


RECIPE = {"host": "moje.operator.example", "url": "https://moje.operator.example/rezygnacja", "version": "0.1",
          "fields": [{"selector": "#umowa", "value_key": "numer_umowy"}], "submit": "#wyslij", "recipe_sha256": "r"}


def test_form_dry_run_does_not_submit_and_execute_does(tmp_path):
    page = FakePage()
    ex = FormExecutor(PK, RECIPE, tmp_path, page_factory=lambda: page)
    plan = _plan(executor="form", level="L2", host="moje.operator.example", action="anulowac",
                 content={"recipe": "r", "values": {"numer_umowy": "TEL/123"}})
    pv = ex.dry_run(plan)
    assert pv["submitted"] is False and ("click", "#wyslij") not in page.actions
    appr = approve(plan, decision="approve", secret_key=SK, pin="1", pin_path=_pin(tmp_path))
    r = ex.execute(plan, appr)
    assert ("click", "#wyslij") in page.actions and r["evidence"]["screenshot_after"]["sha256"]


def _pin(tmp_path):
    gate.set_pin(tmp_path / "pin.json", "1")
    return tmp_path / "pin.json"


def test_form_host_outside_allowlist(tmp_path):
    ex = FormExecutor(PK, RECIPE, tmp_path, page_factory=FakePage)
    plan = _plan(executor="form", level="L2", host="evil.example", action="anulowac", content={"values": {}})
    with pytest.raises(HostNotAllowed):
        ex.execute(plan, approve(plan, decision="approve", secret_key=SK, pin="1", pin_path=_pin(tmp_path)))
