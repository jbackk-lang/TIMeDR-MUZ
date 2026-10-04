"""Pamiec zarzadcy (ustawienia.json obok run.bat). Uzytkownik nigdy jej nie edytuje: zapisuje ja okno.

Trzyma tylko to, czego nie da sie wyczytac z wyciagow: aktualne saldo (jesli wpisane), dane do pism,
poprawki kategorii, potwierdzenia umow, wyniki zalatwionych spraw (liczba negocjacji, nowa cena),
dlugi dopisane recznie. Wszystko inne MUZ rozpoznaje sam przy kazdym uruchomieniu.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from .core.atomic import atomic_write_text


class Ustawienia:
    def __init__(self, path):
        self.path = Path(path)
        self.d = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        for k, v in {"kategorie": {}, "potwierdzone": {}, "negocjacje": {}, "zrobione": {}, "dlugi": [],
                     "osoba": {}}.items():
            self.d.setdefault(k, v)

    def save(self):
        atomic_write_text(self.path, json.dumps(self.d, indent=2, ensure_ascii=False))

    # --- saldo --------------------------------------------------------------------------------
    def set_saldo(self, zl: float | None, today: date):
        if zl is None:
            self.d.pop("saldo", None)
        else:
            self.d["saldo"] = {"zl": float(zl), "data": today.isoformat()}
        self.save()

    def saldo(self, today: date, max_age_days: int = 3) -> float | None:
        s = self.d.get("saldo")
        if not s or (today - date.fromisoformat(s["data"])).days > max_age_days:
            return None
        return s["zl"]

    # --- zalatwione sprawy --------------------------------------------------------------------
    def done(self, action_id: str, counterparty: str, action: str, wynik: str, nowa_cena_zl: float | None, today: date):
        self.d["zrobione"][action_id] = {"data": today.isoformat(), "wynik": wynik, "nowa_cena_zl": nowa_cena_zl,
                                         "kontrahent": counterparty, "akcja": action}
        if action == "negocjowac" and wynik == "nie_udalo_sie":
            self.d["negocjacje"][counterparty] = self.d["negocjacje"].get(counterparty, 0) + 1
        self.save()

    def is_done(self, action_id: str) -> bool:
        return action_id in self.d["zrobione"]

    def profile(self, today: date) -> dict:
        """Profil w ksztalcie oczekiwanym przez decisions.cycle_plan i pisma."""
        p = dict(self.d.get("osoba", {}))
        s = self.saldo(today)
        if s is not None:
            p["saldo_zl"] = s
        p["dlugi"] = self.d.get("dlugi", [])
        if self.d.get("oszczednosci_zl") is not None:
            p["oszczednosci_zl"] = self.d["oszczednosci_zl"]
        return p
