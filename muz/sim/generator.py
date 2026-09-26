"""Generator pakietow budzetow: syntetyczne gospodarstwa domowe w 5 kwintylach dochodu (GUS 2024).

Kazdy pakiet = rekordy LSF (wplywy i wydatki), potwierdzone umowy i znany dochod. Kwoty strumieni wynikaja
z wydatkow kwintyla i struktury wydatkow GUS; ceny zmieniaja sie przez zdarzenia:
- indeksacja styczniowa (czynsz, energia) o CPI + szum,
- podwyzka dostawcy (telekom, media, subskrypcje, ubezpieczenie) o 10-40%,
- koniec promocji (telekom, media): cena promocyjna 60-80%, potem cena regularna,
- podwojny rachunek za energie (anomalia),
- zakupy spozywcze (zmienne kwoty, bez umowy) jako szum.
Umowy: 40% umow (poza czynszem i kredytem, ktore zawsze) jest na czas nieokreslony - bez daty konca.
Wynik jest deterministyczny dla danego ziarna.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from ..adapter.csv_import import LSFRecord, normalize_counterparty
from . import gus_bgd

PROVIDERS = {
    "czynsz": ["Spółdzielnia Mieszkaniowa Zacisze", "Wspólnota Mieszkaniowa Lipowa 3", "TBS Metropolia"],
    "energia": ["PGE Obrót S.A.", "Tauron Sprzedaż sp. z o.o.", "Enea S.A.", "Energa Obrót S.A."],
    "telekom": ["Orange Polska S.A.", "Play sp. z o.o.", "Plus Polkomtel S.A.", "T-Mobile Polska S.A."],
    "media": ["UPC Polska", "Vectra S.A.", "Netia S.A.", "Inea sp. z o.o."],
    "subskrypcja": ["Netflix.com", "Spotify AB", "Disney Plus", "HBO Max", "YouTube Premium"],
    "ubezpieczenie": ["PZU SA", "Warta S.A.", "Allianz Polska S.A."],
    "kredyt": ["PKO Bank Polski rata", "mBank rata kredytu", "Santander rata"],
    "inne": ["Biedronka", "Lidl"],
}


@dataclass
class BudgetPackage:
    package_id: str
    quintile: int
    household_size: int
    income_month_gr: int
    records: list[LSFRecord]
    contracts: dict[str, dict]            # znormalizowany kontrahent -> umowa
    events: list[dict] = field(default_factory=list)


def _month(start: tuple[int, int], i: int) -> tuple[int, int]:
    y, m = start
    m += i
    return y + (m - 1) // 12, (m - 1) % 12 + 1


def _rec(pkg_id: str, n: int, d: date, amount_gr: int, cp: str, desc: str) -> LSFRecord:
    raw = f"{pkg_id}|{n}|{d}|{amount_gr}|{cp}|{desc}"
    return LSFRecord(date=d, amount_gr=amount_gr, currency="PLN", counterparty=normalize_counterparty(cp),
                     description=desc, iban_hash="", balance_gr=None, source=f"pakiet_{pkg_id}",
                     raw_hash=hashlib.sha256(raw.encode()).hexdigest())


def generate_package(seed: int, *, months: int = 32, start=(2024, 1), cpi: dict[str, float] | None = None,
                     quintile: int | None = None) -> BudgetPackage:
    rng = np.random.default_rng(seed)
    q = int(quintile or rng.integers(1, 6))
    h = int(rng.choice([1, 2, 3, 4], p=[0.25, 0.3, 0.25, 0.2]))
    qd = gus_bgd.QUINTILES[q]
    income = qd["income_pp"] * h * float(rng.normal(1.0, 0.1))
    spend = qd["expenditure_pp"] * h * float(rng.normal(1.0, 0.1))
    sh = {k: v / 100.0 for k, v in gus_bgd.category_shares(q).items()}
    pkg_id = f"{seed:06d}"

    # strumienie: (kategoria, dostawca, cena bazowa zl, zmiennosc)
    streams = [("czynsz", spend * sh["mieszkanie_energia"] * 0.55, 0.0),
               ("energia", spend * sh["mieszkanie_energia"] * 0.30, 0.05),
               ("telekom", spend * sh["lacznosc"] * 0.6, 0.0)]
    if rng.random() < 0.8:
        streams.append(("media", spend * sh["lacznosc"] * 0.4, 0.0))
    n_sub = int(rng.random() < 0.4 + 0.12 * q) + int(rng.random() < 0.1 * q)
    for _ in range(n_sub):
        streams.append(("subskrypcja", float(rng.choice([29.0, 43.0, 49.0, 60.0])), 0.0))
    if rng.random() < 0.6:
        streams.append(("ubezpieczenie", spend * sh["inne_towary_uslugi"] * 0.25, 0.0))
    if rng.random() < 0.25 + 0.05 * q:
        streams.append(("kredyt", income * float(rng.uniform(0.08, 0.15)), 0.0))

    used: set[str] = set()
    records: list[LSFRecord] = []
    contracts: dict[str, dict] = {}
    events: list[dict] = []
    n = 0
    for cat, base, vol in streams:
        choices = [p for p in PROVIDERS[cat] if p not in used]
        if not choices:
            continue
        provider = str(rng.choice(choices))
        used.add(provider)
        cp_norm = normalize_counterparty(provider)
        day = int(rng.integers(3, 26))
        price = round(base, 2)
        promo_end = None
        if cat in ("telekom", "media") and rng.random() < 0.3:
            promo_end_i = int(rng.integers(12, months))
            promo_price = round(price * float(rng.uniform(0.6, 0.8)), 2)
            y, m = _month(start, promo_end_i)
            promo_end = date(y, m, 1).isoformat()
        hikes = {}
        if cat in ("telekom", "media", "subskrypcja", "ubezpieczenie"):
            for i in range(1, months):
                if rng.random() < 0.15 / 12:
                    hikes[i] = float(rng.uniform(0.10, 0.40))
        for i in range(months):
            y, m = _month(start, i)
            if cat in ("czynsz", "energia") and m == 1 and i > 0 and rng.random() < 0.7:
                infl = (cpi or {}).get(f"{y - 1:04d}-12", 0.03)
                price = round(price * (1.0 + infl + float(rng.normal(0.02, 0.03))), 2)
                events.append({"month": f"{y:04d}-{m:02d}", "counterparty": cp_norm, "event": "indeksacja"})
            if i in hikes:
                price = round(price * (1.0 + hikes[i]), 2)
                events.append({"month": f"{y:04d}-{m:02d}", "counterparty": cp_norm, "event": "podwyzka",
                               "rel": round(hikes[i], 3)})
            amount = price
            if promo_end is not None and date(y, m, 1).isoformat() < promo_end:
                amount = promo_price
            if vol:
                amount = round(amount * float(rng.normal(1.0, vol)), 2)
            if cat == "energia" and rng.random() < 0.05:
                amount = round(amount * 2, 2)
                events.append({"month": f"{y:04d}-{m:02d}", "counterparty": cp_norm, "event": "podwojny_rachunek"})
            n += 1
            records.append(_rec(pkg_id, n, date(y, m, day), -int(round(amount * 100)), provider, cat))
        end_i = int(rng.integers(months, months + 24))
        ey, em = _month(start, end_i)
        # umowa na czas nieokreslony (np. po okresie promocyjnym) - bez daty konca w kazdej kategorii,
        # inaczej brak daty konca bylby skrotem "to czynsz albo kredyt" dla modelu
        indefinite = cat in ("czynsz", "kredyt") or rng.random() < 0.4
        contracts[cp_norm] = {"counterparty": cp_norm, "category": cat,
                              "notice_period_months": int(rng.choice([1, 3])),
                              "end_date": None if indefinite else date(ey, em, 28).isoformat(),
                              "promo_end": promo_end, "negotiations": int(rng.choice([0, 0, 1, 2])),
                              "cancel_channel": {"type": "letter"}, "confirmed_by_user": True}

    # zakupy spozywcze: 3-5 razy w miesiacu w jednej sieci, bez umowy (szum)
    shop = str(rng.choice(PROVIDERS["inne"]))
    food_month = spend * sh["zywnosc"] * 0.5
    for i in range(months):
        y, m = _month(start, i)
        k = int(rng.integers(3, 6))
        for j in range(k):
            n += 1
            amt = food_month / k * float(rng.lognormal(0, 0.3))
            records.append(_rec(pkg_id, n, date(y, m, int(rng.integers(1, 28))), -int(round(amt * 100)), shop, "zakupy"))
    # wplywy
    for i in range(months):
        y, m = _month(start, i)
        n += 1
        records.append(_rec(pkg_id, n, date(y, m, int(rng.integers(1, 11))), int(round(income * 100)),
                            "Pracodawca sp. z o.o.", "wynagrodzenie"))
    return BudgetPackage(pkg_id, q, h, int(round(income * 100)), records, contracts, events)
