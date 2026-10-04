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


def test_audit_anchor_detects_truncation_and_rewrite(tmp_path):
    import json
    from muz.core.common import canonical_json
    log = tmp_path / "audit.jsonl"
    for i in range(5):
        audit.append(log, "e", {"kwota": i})
    anchor = audit.export_anchor_n(log)
    assert audit.verify_anchor(log, anchor)[0]
    assert audit.verify_anchor(log, anchor.split(":", 1)[1])[0]          # kotwica sama jako hash
    audit.append(log, "e", {"kwota": 99})                                # dluzszy dziennik nadal OK
    assert audit.verify_anchor(log, anchor)[0]
    lines = log.read_text(encoding="utf-8").splitlines()
    # 1) obciecie ogona: verify() tego nie widzi, verify_anchor() tak
    log.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")
    assert audit.verify(log)[0]
    assert not audit.verify_anchor(log, anchor)[0]
    # 2) przepisanie calego lancucha ze zmieniona trescia
    log.unlink()
    for i in range(5):
        audit.append(log, "e", {"kwota": i if i != 2 else 1000})
    assert audit.verify(log)[0]
    assert not audit.verify_anchor(log, anchor)[0]


def test_atomic_write_no_leftovers_and_replaces(tmp_path):
    from muz.core.atomic import atomic_write_bytes, atomic_write_text
    p = tmp_path / "x.json"
    atomic_write_text(p, "a")
    atomic_write_text(p, "bb")
    assert p.read_text() == "bb"
    atomic_write_bytes(tmp_path / "k", b"k" * 32, private=True)
    assert sorted(q.name for q in tmp_path.iterdir()) == ["k", "x.json"]   # brak plikow .tmp
