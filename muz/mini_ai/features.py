"""Wektor cech na strumien (dokument MUZ, modul 5, "Wejscie": ok. 40 cech).

v0.2 (decyzje v0.2): 42 cechy - doszly dwie cechy wagi kosztu wzgledem dochodu gospodarstwa
(udzial kwoty w dochodzie, roczny koszt podwyzki r/r wzgledem dochodu), bez ktorych ta sama podwyzka
wyglada identycznie w budzecie 3 tys. i 15 tys. zl miesiecznie.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np

CATEGORIES = ("telekom", "energia", "ubezpieczenie", "kredyt", "subskrypcja", "media", "czynsz", "inne")
PHASES = ("stabilna", "przejsciowa", "krytyczna")

FEATURE_NAMES = (
    # sygnaly M/S i baseline (7)
    "anomalia", "anomalia_z", "defekt", "defekt_wzgl", "skret", "baseline_cpi", "baseline_brak",
    # zmiana r/r (3)
    "rr", "rr_brak", "rr_minus_cpi",
    # umowa (8)
    "mies_do_konca", "mies_do_konca_brak", "okres_wypowiedzenia", "okres_wypowiedzenia_brak",
    "koniec_promocji", "koniec_promocji_brak", "liczba_negocjacji", "umowa_brak",
    # MetaState i M budzetu (8)
    "Lambda", "tau", "rho", "J", "M_Lambda", "M_tau", "M_rho", "M_J",
    # faza (3)
    "faza_stabilna", "faza_przejsciowa", "faza_krytyczna",
    # kategoria dostawcy (8)
    *(f"kat_{c}" for c in CATEGORIES),
    # strumien (3)
    "log_kwota", "dlugosc_historii", "flagi_3_mies",
    # waga wzgledem dochodu gospodarstwa (2), v0.2
    "udzial_w_dochodzie", "podwyzka_roczna_do_dochodu",
)
N_FEATURES = len(FEATURE_NAMES)
assert N_FEATURES == 42


def _f(x) -> float:
    return 0.0 if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def _clip(x, lo=-1.0, hi=1.0) -> float:
    return float(min(hi, max(lo, _f(x))))


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def build_features(frames: list, phase: str, contract: dict | None, meta_state=None, meta_M=None,
                   cpi_month: float | None = None, income_month_gr: float | None = None) -> np.ndarray:
    """frames: SignalFrame strumienia do biezacego miesiaca wlacznie (bez przyszlosci)."""
    f = frames[-1]
    y, m = map(int, f.month.split("-"))
    now = date(y, m, 1)
    v: list[float] = []
    v += [float(f.anomaly), _clip(abs(_f(f.anomaly_z)) / 10.0, 0, 1), float(f.defect), _clip(f.defect_rel),
          float(f.twist), float(bool(f.baseline_hit)), float(f.baseline_hit is None)]
    v += [_clip(f.yoy), float(f.yoy is None),
          _clip(_f(f.yoy) - _f(cpi_month)) if f.yoy is not None and cpi_month is not None else 0.0]
    c = contract or {}
    end = c.get("end_date")
    mte = _months_between(now, date.fromisoformat(end)) if end else None
    promo = c.get("promo_end")
    v += [_clip((mte if mte is not None else 0) / 24.0, 0, 1), float(mte is None),
          _clip(_f(c.get("notice_period_months")) / 3.0, 0, 1), float(c.get("notice_period_months") is None),
          float(bool(promo) and date.fromisoformat(promo) <= now), float(not promo),
          _clip(_f(c.get("negotiations")) / 5.0, 0, 1), float(contract is None)]
    s, M = meta_state, meta_M
    v += [_clip(getattr(s, k, None)) for k in ("Lambda", "tau", "rho", "J")]
    v += [_clip(getattr(M, k, None)) for k in ("Lambda", "tau", "rho", "J")]
    v += [float(phase == p) for p in PHASES]
    cat = c.get("category", "inne") if contract else "inne"
    v += [float(cat == k) for k in CATEGORIES]
    last3 = frames[-3:]
    v += [_clip(math.log10(f.amount_gr / 100.0 + 1.0) / 5.0, 0, 1), _clip(len(frames) / 36.0, 0, 1),
          sum(x.any_flag for x in last3) / 3.0]
    share, extra = 0.0, 0.0
    if income_month_gr and income_month_gr > 0:
        share = f.amount_gr / income_month_gr
        if len(frames) >= 13:
            extra = max(0.0, f.amount_gr - frames[-13].amount_gr) * 12.0 / income_month_gr
    v += [_clip(share / 0.5, 0, 1), _clip(extra / 0.2, 0, 1)]  # skale: 50% dochodu, 20% dochodu rocznie
    arr = np.asarray(v, dtype=float)
    assert arr.shape == (N_FEATURES,)
    return arr
