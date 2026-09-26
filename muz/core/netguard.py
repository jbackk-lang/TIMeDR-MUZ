"""Straz sieci: warstwy decyzyjne dzialaja bez sieci, adapter i wykonawcy tylko do allowed_hosts.

Prototyp pilnuje tego w procesie (podmiana funkcji gniazd). Docelowo warstwy sa osobnymi procesami
bez uprawnien sieciowych (dokument MUZ, "Architektura ogolna").
"""
from __future__ import annotations

import contextlib
import socket
import urllib.parse
import urllib.request


class NetworkForbidden(RuntimeError):
    pass


class HostNotAllowed(RuntimeError):
    pass


@contextlib.contextmanager
def no_network():
    def _deny(*_a, **_k):
        raise NetworkForbidden("warstwa decyzyjna nie ma dostepu do sieci")
    saved = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo)
    socket.socket.connect = _deny
    socket.socket.connect_ex = _deny
    socket.create_connection = _deny
    socket.getaddrinfo = _deny
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo = saved


def check_host(url: str, allowed_hosts: frozenset[str]) -> str:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise HostNotAllowed(f"tylko https: {url}")
    if host not in allowed_hosts:
        raise HostNotAllowed(f"host {host!r} spoza listy dozwolonych {sorted(allowed_hosts)}")
    return host


def fetch(url: str, allowed_hosts: frozenset[str], timeout: float = 20.0) -> bytes:
    check_host(url, allowed_hosts)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "TIMeDR-MUZ/0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - host sprawdzony wyzej
        return resp.read()
