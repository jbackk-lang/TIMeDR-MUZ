"""Atomowy zapis plikow: plik tymczasowy w tym samym katalogu, fsync, os.replace.

Awaria w trakcie zapisu zostawia albo stary, albo nowy plik w calosci - nigdy ucieta wersje.
`private=True` tworzy plik od razu z uprawnieniami 0600 (bez okna, w ktorym jest czytelny dla innych);
w Windows bit 0600 jest w praktyce ignorowany, wiec tam ochrona opiera sie na ACL katalogu uzytkownika.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_bytes(path, data: bytes, *, private: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")  # mkstemp: 0600
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if not private:
            try:
                os.chmod(tmp, 0o666 & ~_umask())
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def _umask() -> int:
    m = os.umask(0)
    os.umask(m)
    return m
