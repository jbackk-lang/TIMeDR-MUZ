"""Agregat META-DYNAMICS dla budzetu (instancja finansowa MetaState z TIMDR-META-DYNAMICS).

Mapowanie (dokument TIMeDR-MUZ, modul 3):
  Lambda - dyspersja: 1.4826*MAD wzglednych zmian kwot miedzy strumieniami w miesiacu
  tau    - tempo: zmiana odsetka strumieni z defektem miesiac do miesiaca
  rho    - gestosc: odsetek strumieni z dowolna flaga M/S
  J      - sprzezenie z tlem (progi v0.2): korelacja Spearmana r/r indeksu kosztow z CPI r/r (12 miesiecy),
           zakres [-1, 1]; v0.1 uzywala nachylenia regresji (bez ograniczen - walidator META to zglosil).
           Nachylenie zostaje jako liczba opisowa j_slope, poza agregatem.
Wartosci niepoliczalne (za malo danych, brak CPI) to NaN, nie zero.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .._vendor.meta_state import MetaState
from ..adapter import Stream
from ..signals import SignalFrame

NAN = float("nan")


@dataclass(frozen=True)
class BudgetMeta:
    month: str
    n_streams: int
    state: MetaState
    M: MetaState | None   # roznica wzgledem poprzedniego miesiaca
    j_slope: float = float("nan")  # opisowo: o ile pkt proc. r/r rosna koszty na 1 pkt inflacji


def _rank(x: np.ndarray) -> np.ndarray:
    """Rangi srednie przy remisach (jak w Spearmanie)."""
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    ranks[order] = np.arange(1, len(x) + 1)
    for v in np.unique(x):
        m = x == v
        if m.sum() > 1:
            ranks[m] = ranks[m].mean()
    return ranks


def spearman(a, b) -> float:
    ra, rb = _rank(np.asarray(a, dtype=float)), _rank(np.asarray(b, dtype=float))
    if np.std(ra) == 0 or np.std(rb) == 0:
        return NAN
    return float(np.corrcoef(ra, rb)[0, 1])


def budget_meta(streams: list[Stream], frames: dict[str, list[SignalFrame]], cpi: dict[str, float] | None,
                min_streams: int = 3, j_definition: str = "spearman") -> list[BudgetMeta]:
    monthly = [s for s in streams if s.cadence == "monthly"]
    months = sorted({m for s in monthly for m in s.months})
    fidx = {sid: {f.month: f for f in fs} for sid, fs in frames.items()}
    amount = {s.stream_id: dict(zip(s.months, s.amounts_gr)) for s in monthly}
    index = []  # suma kosztow strumieni miesiecznych
    out: list[BudgetMeta] = []
    prev_def_frac = None
    prev_state = None
    for i, m in enumerate(months):
        active = [s for s in monthly if m in fidx[s.stream_id]]
        index.append(sum(amount[s.stream_id].get(m, 0) for s in monthly))
        if len(active) < min_streams:
            prev_def_frac, prev_state = None, None
            continue
        fr = [fidx[s.stream_id][m] for s in active]
        rels = np.array([f.defect_rel for f in fr if f.defect_rel is not None], dtype=float)
        lam = 1.4826 * float(np.median(np.abs(rels - np.median(rels)))) if len(rels) >= min_streams else NAN
        rho = sum(f.any_flag for f in fr) / len(fr)
        def_frac = sum(f.defect for f in fr) / len(fr)
        tau = def_frac - prev_def_frac if prev_def_frac is not None else NAN
        J, slope = NAN, NAN
        if cpi is not None and i >= 23:
            yy, cc = [], []
            for j in range(i - 11, i + 1):
                if index[j - 12] > 0 and months[j] in cpi:
                    yy.append(index[j] / index[j - 12] - 1.0)
                    cc.append(cpi[months[j]])
            if len(yy) >= 6 and np.std(cc) > 0:
                slope = float(np.polyfit(cc, yy, 1)[0])
                if j_definition == "spearman":
                    J = spearman(yy, cc)
                elif j_definition == "slope":
                    J = slope
                else:
                    raise ValueError(f"nieznana definicja J: {j_definition}")
        state = MetaState(Lambda=lam, tau=tau, rho=rho, J=J)
        M = prev_state.delta(state) if prev_state is not None else None
        out.append(BudgetMeta(m, len(active), state, M, slope))
        prev_def_frac, prev_state = def_frac, state
    return out


def is_finite(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def meta_payload(b: BudgetMeta, validator_report_sha256: str | None) -> dict:
    """Payload muz.meta_state/1 (NaN zapisywane jako null)."""
    def v(x):
        return x if is_finite(x) else None
    s, M = b.state, b.M
    return {"scope": "budget", "period": b.month, "Lambda": v(s.Lambda), "tau": v(s.tau), "rho": v(s.rho), "J": v(s.J),
            "M": None if M is None else {"Lambda": v(M.Lambda), "tau": v(M.tau), "rho": v(M.rho), "J": v(M.J)},
            "validator_report_sha256": validator_report_sha256}


def validate_budget_meta(bmeta: list, phase_names: list[str]):
    """Raport meta_validator (TIMDR-Math-Formalism) dla serii budzetu: izolacja kanalow, zakresy, fazy.

    NaN (np. J bez CPI) zamieniane na 0 tylko na potrzeby walidatora; raport to zaznacza.
    """
    import numpy as np
    from .._vendor.math_formalism.meta_validator import MetaSeriesData, validate_meta_series
    def col(k):
        return [float(getattr(b.state, k)) if is_finite(getattr(b.state, k)) else 0.0 for b in bmeta]
    mags = [0.0 if b.M is None else float(np.sqrt(sum((getattr(b.M, k) if is_finite(getattr(b.M, k)) else 0.0) ** 2
                                                       for k in ("Lambda", "tau", "rho", "J")))) for b in bmeta[1:]]
    data = MetaSeriesData(Lambda=col("Lambda"), tau=col("tau"), rho=col("rho"), J=col("J"),
                          magnitude=mags, phases=list(phase_names[1:len(bmeta)]))
    return validate_meta_series(data)
