"""Dymny test badania zamknietej petli: dziala, jest deterministyczne, kontrola S0 zgodna z konstrukcja."""
import hashlib
from pathlib import Path

from muz.badania import petla as M
from muz.badania.petla_run import main

FROZEN_SHA = "25ff4ec256eedee1d0cb0f6362375a01665cf1fdaf42191684cd2ea8f2bdf771"


def test_plik_zgodny_z_zamrozonym():
    b = Path(M.__file__).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(b).hexdigest() == FROZEN_SHA


def test_male_uruchomienie_deterministyczne():
    r1 = main(3, 5, ["S0"]); r2 = main(3, 5, ["S0"])
    assert r1["S0"]["mean"] == r2["S0"]["mean"]
    # S0: bez inflacji i zdarzen MUZ i Koperty podejmuja te same decyzje (z konstrukcji)
    assert r1["S0"]["mean"]["MUZ"] == r1["S0"]["mean"]["Koperty"]
