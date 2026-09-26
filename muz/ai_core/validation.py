"""Testy walidacyjne bramek P1/P2 zgodne z protokolem TIMDR.

- controls_for_defect(): kontrola pozytywna (wstrzyknieta podwyzka musi dac defekt) i negatywna
  (dwie niezalezne probki bez zmian nie moga sie roznic) przez run_controls z TIMDR-Math-Formalism,
- p1_signals_vs_baseline(): czy sygnaly M/S wskazuja strumienie oznaczone przez uzytkownika jako warte
  dzialania lepiej niz regula "r/r > CPI + 5 pp" (Mann-Whitney + rozmiar efektu, Bonferroni),
- select_model(): regula wyboru modelu (log-loss na zbiorze odrzuconym, margines z prereg).
Wynik to TestEvidence dla TIMDRProtocol.run_test - werdykt wydaje protokol, nie ten modul.
"""
from __future__ import annotations

import numpy as np

from .._vendor.ai_core.timdr_ai_core import ControlResult as CoreControlResult
from .._vendor.ai_core.timdr_ai_core import TestEvidence
from .._vendor.math_formalism.pipeline import bonferroni_correct, mann_whitney_test, run_controls
from .._vendor.topologic import defect

SIGNAL_NAMES = ("anomaly", "defect", "twist", "any_flag")


def _defect_rate(series: np.ndarray, rel: float = 0.10) -> float:
    hits = [defect(series[i - 1], series[i], method="relative", rel_threshold=rel)
            for i in range(1, len(series)) if series[i - 1] != 0]
    return float(np.mean(hits)) if hits else 0.0


def _flat_bill(n: int, seed) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 89.0 * (1.0 + rng.normal(0, 0.01, n))


def _bill_with_rise(n: int, seed) -> np.ndarray:
    x = _flat_bill(n, seed)
    x[n // 2:] *= 1.34  # abonament 89 -> ok. 119 zl
    return x


def controls_for_defect(n_windows: int = 30, window_size: int = 24, seed: int = 0, rel: float = 0.10):
    """Zwraca (wynik Math-Formalism, ControlResult dla TIMDRProtocol)."""
    mf = run_controls(metric_fn=lambda s: _defect_rate(s, rel), positive_injector=_bill_with_rise,
                      negative_generator_a=_flat_bill, negative_generator_b=_flat_bill,
                      n_windows=n_windows, window_size=window_size, seed=seed)
    core = CoreControlResult(positive_ok=mf.positive.pvalue < 0.05, negative_ok=mf.negative.pvalue >= 0.05,
                             details={"reason": mf.reason})
    return mf, core


def p1_signals_vs_baseline(frames_with_labels: list[tuple], margin: float = 0.1) -> TestEvidence:
    """frames_with_labels: lista (SignalFrame, etykieta 0/1) z okresu POTWIERDZENIA (druga polowa historii).

    Dla kazdego sygnalu M/S liczymy Mann-Whitney wyniku (0/1) w grupie "warte dzialania" vs reszta.
    p najlepszego sygnalu jest korygowane Bonferronim za liczbe sprawdzonych sygnalow.
    Efekt = r(najlepszy sygnal) - r(baseline CPI). Werdykt wydaje TIMDRProtocol: SUPPORTED wymaga
    p (po korekcie) < alpha ORAZ efektu >= margines (ProtocolCriteria.min_abs_effect_size = margin).
    Hipoteza jest kierunkowa: przy efekcie <= 0 p ustawiane na 1,0.
    """
    frames = [f for f, _ in frames_with_labels if f.baseline_hit is not None]
    labels = np.array([y for f, y in frames_with_labels if f.baseline_hit is not None], dtype=int)
    if labels.sum() == 0 or labels.sum() == len(labels):
        raise ValueError("P1 wymaga obu klas etykiet (warte dzialania i nie) w okresie potwierdzenia")

    def r_and_p(scores):
        s = np.asarray(scores, dtype=float)
        res = mann_whitney_test(s[labels == 1], s[labels == 0], backend="numpy")
        return res.effect_size_r, res.pvalue

    r_base, p_base = r_and_p([float(bool(f.baseline_hit)) for f in frames])
    per_signal = {name: r_and_p([float(getattr(f, name)) for f in frames]) for name in SIGNAL_NAMES}
    best = max(per_signal, key=lambda k: per_signal[k][0])
    r_best, p_best = per_signal[best]
    p_corr = bonferroni_correct(p_best, len(SIGNAL_NAMES))
    effect = r_best - r_base
    direction = "TIMDR lepsze od baseline" if effect > 0 else "kierunek przeciwny albo brak roznicy"
    if effect <= 0:
        # hipoteza jest kierunkowa; TIMDRProtocol porownuje |efekt|, wiec kierunek przeciwny nie moze przejsc
        p_corr = 1.0
    return TestEvidence(p_value=p_corr, effect_size=effect,
                        method="Mann-Whitney U (numpy) + Bonferroni; efekt = r(TIMDR) - r(baseline CPI+5pp)",
                        details={"direction": direction, "best_signal": best, "r_best": r_best, "p_best_raw": p_best, "r_baseline": r_base,
                                 "p_baseline": p_base, "margin": margin,
                                 "per_signal": {k: {"r": v[0], "p": v[1]} for k, v in per_signal.items()}})


def select_model(logloss_candidate: float, logloss_reference: float, margin: float) -> bool:
    """Bardziej zlozony model zastepuje prostszy tylko przy poprawie log-loss o co najmniej margines."""
    return (logloss_reference - logloss_candidate) >= margin
