"""Sygnaly M/S na strumieniach miesiecznych (galaz M/S TIMDR).

Anomalia, defekt i rezonans M z topologic v0.3 (wendorowane); skret wg definicji z dokumentu MUZ
(zmiana znaku nachylenia regresji na 3 probkach, gdy |nachylenie| > prog).

Kazdy sygnal w miesiacu i korzysta wylacznie z probek 0..i (bez przyszlosci).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .._vendor.topologic import anomaly, defect, resonance_m
from ..adapter import Stream


@dataclass(frozen=True)
class SignalFrame:
    stream_id: str
    month: str
    amount_gr: int
    anomaly: bool
    anomaly_z: float | None      # odporny z-score wzgledem historii (informacyjnie)
    defect: bool
    defect_rel: float | None     # wzgledna zmiana miesiac do miesiaca
    twist: bool
    baseline_hit: bool | None    # regula "r/r > CPI + margines"; None gdy brak CPI albo 12 miesiecy
    yoy: float | None

    @property
    def any_flag(self) -> bool:
        return self.anomaly or self.defect or self.twist


def _robust_z(value: float, hist: np.ndarray) -> float | None:
    med = float(np.median(hist))
    scale = 1.4826 * float(np.median(np.abs(hist - med)))
    if scale == 0:
        return None
    return (value - med) / scale


def stream_signals(stream: Stream, th: dict, cpi: dict[str, float] | None = None) -> list[SignalFrame]:
    x = np.asarray(stream.amounts_gr, dtype=float)
    k = th["anomaly_k"]
    win = th["anomaly_window"]
    rel = th["defect_rel_threshold"]
    tw_rel = th["twist_rel_threshold"]
    margin = th["baseline_cpi_margin"]
    # nachylenie regresji liniowej na 3 kolejnych probkach (i-2, i-1, i) = (x[i] - x[i-2]) / 2
    slope = np.array([np.nan, np.nan] + [(x[i] - x[i - 2]) / 2.0 for i in range(2, len(x))])
    frames = []
    for i, month in enumerate(stream.months):
        hist = x[max(0, i - win): i]
        is_anom, z = False, None
        if len(hist) >= win:  # pelne okno (dokument: okno 12 probek); krotsza historia daje falszywe alarmy
            is_anom = anomaly(x[i], hist, k=k)
            z = _robust_z(x[i], hist)
        is_def, drel = False, None
        if i >= 1 and x[i - 1] > 0:
            drel = (x[i] - x[i - 1]) / x[i - 1]
            is_def = defect(x[i - 1], x[i], method="relative", rel_threshold=rel)
        is_tw = False
        if i >= 3:  # skret: zmiana znaku nachylenia trendu, gdy |nachylenie| przekracza prog
            level = float(np.median(x[: i + 1][x[: i + 1] > 0])) if np.any(x[: i + 1] > 0) else 0.0
            prev_nz = [v for v in slope[2:i] if v != 0]  # ostatnie niezerowe nachylenie (szczyt daje 0)
            s_now = slope[i]
            is_tw = bool(prev_nz and s_now != 0 and np.sign(prev_nz[-1]) != np.sign(s_now)
                         and abs(s_now) > tw_rel * level)
        yoy, base = None, None
        if i >= 12 and x[i - 12] > 0:
            yoy = x[i] / x[i - 12] - 1.0
            if cpi is not None and month in cpi:
                base = bool(yoy > cpi[month] + margin)
        frames.append(SignalFrame(stream.stream_id, month, int(x[i]), bool(is_anom), z,
                                  bool(is_def), drel, bool(is_tw), base, yoy))
    return frames


def resonance_by_month(frames_by_stream: dict[str, list[SignalFrame]], min_count: int) -> dict[str, dict]:
    """Rezonans M: w danym miesiacu co najmniej min_count strumieni ma anomalie albo defekt."""
    months = sorted({f.month for fs in frames_by_stream.values() for f in fs})
    out = {}
    for m in months:
        flags = [f.anomaly or f.defect for fs in frames_by_stream.values() for f in fs if f.month == m]
        out[m] = {"n_streams": len(flags), "n_events": int(sum(flags)),
                  "resonance_m": resonance_m(flags, min_count=min_count) if flags else False}
    return out


def signal_frame_payload(f: SignalFrame, thresholds_sha256: str) -> dict:
    """Payload muz.signal_frame/1. Rezonans M jest wlasnoscia miesiaca (wielu strumieni), dolaczany osobno."""
    return {"stream_id": f.stream_id, "month": f.month, "amount_gr": f.amount_gr,
            "flags": {"anomaly": f.anomaly, "defect": f.defect, "twist": f.twist},
            "strengths": {"anomaly_z": f.anomaly_z, "defect_rel": f.defect_rel, "yoy": f.yoy},
            "baseline_hit": f.baseline_hit, "thresholds_sha256": thresholds_sha256}
