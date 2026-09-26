"""Syntetyczne dane testowe: 30 miesiecy wyciagu w stylu polskiego banku (CP1250, ';', przecinek dziesietny)."""
from __future__ import annotations

from datetime import date

import numpy as np

ORANGE_IBAN = "PL61109010140000071219812874"
HEADER = ["Data operacji", "Kwota", "Waluta", "Nadawca / Odbiorca", "Tytuł", "Saldo po operacji"]
MAPPING = {"date": "Data operacji", "amount": "Kwota", "counterparty": "Nadawca / Odbiorca", "description": "Tytuł",
           "currency": "Waluta", "balance": "Saldo po operacji", "aliases": {"ORANGE": "ORANGE POLSKA"}}


def month_date(i: int, day: int, start=(2024, 1)) -> date:
    y, m = start
    m += i
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return date(y, m, day)


def transactions(n_months: int = 30, seed: int = 0):
    rng = np.random.default_rng(seed)
    tx = []
    for i in range(n_months):
        tx.append((month_date(i, 1), 8000.00, "Pracodawca Sp. z o.o.", "Wynagrodzenie"))
        orange = 89.00 if i < 20 else 119.00
        tx.append((month_date(i, 5), -orange, f"Orange Polska S.A. {ORANGE_IBAN}", f"Abonament {i + 1}"))
        pge = round(210 + rng.normal(0, 4), 2)
        if i == 15:
            pge = 420.00
        if i >= 24:
            pge = round(pge * 1.15, 2)
        tx.append((month_date(i, 7), -pge, "PGE Obrót S.A.", "Energia elektryczna"))
        tx.append((month_date(i, 10), -(2500.00 if i < 24 else 2800.00), "Wspólnota Mieszkaniowa Łąkowa 5", "Czynsz"))
        tx.append((month_date(i, 12), -(45.00 if i < 24 else 52.00), "NETFLIX.COM", "Subskrypcja"))
        if i % 12 == 0:
            tx.append((month_date(i, 20), -1200.00, "PZU SA", "Polisa OC/AC"))
    return tx


def write_bank_csv(path, tx, start_balance: float = 20000.0, encoding: str = "cp1250"):
    lines = ["Wyciąg z rachunku;;;;;", "Numer rachunku: 12 3456 7890 1234 5678 9012 3456;;;;;", ";;;;;",
             ";".join(HEADER)]
    bal = start_balance
    for d, amt, cp, title in sorted(tx, key=lambda t: t[0]):
        bal += amt
        f = lambda x: f"{x:.2f}".replace(".", ",")
        lines.append(";".join([d.strftime("%d.%m.%Y"), f(amt), "PLN", cp, title, f(bal)]))
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode(encoding))
    return path


MT940_SAMPLE = """:20:ST240131
:25:/PL12345678901234567890123456
:28C:1/1
:60F:C240101PLN20000,00
:61:2401050105D89,00NTRFNONREF//X1
:86:020~00TRF~20Abonament styczeń~2112345~32ORANGE POLSKA~33S.A.~38PL61109010140000071219812874
:61:2401010101C8000,00NTRFNONREF//X2
:86:051~00TRF~20Wynagrodzenie~32PRACODAWCA SP Z O O
:62F:C240131PLN27911,00
"""

CONTRACTS = [
    {"counterparty": "ORANGE POLSKA", "legal_name": "Orange Polska S.A.", "category": "telekom", "number": "TEL/123/2023",
     "address": "Al. Jerozolimskie 160, 02-326 Warszawa", "notice_period_months": 1, "end_date": "2027-06-30",
     "promo_end": None, "negotiations": 0, "cancel_channel": {"type": "letter", "email": "obsluga@example.test"},
     "confirmed_by_user": True},
    {"counterparty": "NETFLIX COM", "category": "subskrypcja", "confirmed_by_user": False},
]
PROFILE = {"imie_nazwisko": "Jan Testowy", "adres": "ul. Przykładowa 1, 00-001 Warszawa", "miejscowosc": "Warszawa"}
