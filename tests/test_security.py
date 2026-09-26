"""Bezpieczenstwo: brak sieci w warstwach decyzyjnych, allowed_hosts, AES-256-GCM, dziennik z lancuchem hashy."""
import json
import socket

import pytest

from muz import audit
from muz.audit.store import AVAILABLE, SecureStore
from muz.core.netguard import HostNotAllowed, NetworkForbidden, check_host, no_network


def test_no_network_blocks_sockets():
    with no_network():
        with pytest.raises(NetworkForbidden):
            socket.create_connection(("api.nbp.pl", 443), timeout=1)
        with pytest.raises(NetworkForbidden):
            socket.getaddrinfo("api.nbp.pl", 443)
    assert socket.getaddrinfo is not None  # przywrocone po wyjsciu


def test_check_host():
    allowed = frozenset({"api.nbp.pl"})
    assert check_host("https://api.nbp.pl/api/x", allowed) == "api.nbp.pl"
    for bad in ("http://api.nbp.pl/api/x", "https://api.nbp.pl.evil.example/x", "https://evil.example/"):
        with pytest.raises(HostNotAllowed):
            check_host(bad, allowed)


def test_audit_chain_detects_edit_and_deletion(tmp_path):
    log = tmp_path / "audit.jsonl"
    for i in range(4):
        audit.append(log, "e", {"i": i})
    assert audit.verify(log)[0]
    anchor = audit.export_anchor(log)
    lines = log.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[1]); e["data"]["i"] = 99
    log.write_text("\n".join([lines[0], json.dumps(e)] + lines[2:]) + "\n", encoding="utf-8")
    ok, msg = audit.verify(log)
    assert not ok and "zmieniona" in msg
    log.write_text("\n".join([lines[0]] + lines[2:]) + "\n", encoding="utf-8")
    ok, msg = audit.verify(log)
    assert not ok and "prev_hash" in msg
    assert len(anchor) == 64


@pytest.mark.skipif(not AVAILABLE, reason="brak biblioteki cryptography")
def test_aes_gcm_store_roundtrip_and_tamper(tmp_path):
    st = SecureStore(b"k" * 32)
    st.write_json(tmp_path / "lsf.bin", {"kwota_gr": -8900})
    assert st.read_json(tmp_path / "lsf.bin") == {"kwota_gr": -8900}
    blob = bytearray((tmp_path / "lsf.bin").read_bytes()); blob[-1] ^= 1
    (tmp_path / "lsf.bin").write_bytes(bytes(blob))
    with pytest.raises(Exception):
        st.read_json(tmp_path / "lsf.bin")
    with pytest.raises(ValueError):
        SecureStore(b"k" * 16)
