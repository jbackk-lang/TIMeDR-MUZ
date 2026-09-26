"""Raport etapu 0 w Markdown. Tylko opis stanu: zadnych rekomendacji wykonania ani porad inwestycyjnych."""
from __future__ import annotations

from .meta import is_finite
from .phases import NAMES


def _zl(gr: int) -> str:
    return f"{gr / 100:,.2f} zł".replace(",", " ").replace(".", ",")


def _pct(x) -> str:
    return "–" if x is None else f"{x * 100:+.1f}%".replace(".", ",")


def _num(x) -> str:
    return f"{x:.3f}".replace(".", ",") if is_finite(x) else "–"


def render(*, streams, frames, s_phases, bmeta, b_phases, calib, res, hard, cpi_given, hashes, n_raw, n_records) -> str:
    monthly = [s for s in streams if s.cadence == "monthly"]
    irregular = [s for s in streams if s.cadence != "monthly"]
    L = []
    L.append("# TIMeDR-MUZ — raport etapu 0 (tylko odczyt)\n")
    L.append("Nic nie zostało wysłane ani zmienione. Raport opisuje stan wydatków i nie jest poradą finansową.\n")
    L.append(f"Rekordy: {n_raw} wczytane, {n_records} po usunięciu duplikatów. Strumienie: {len(monthly)} miesięcznych, "
             f"{len(irregular)} nieregularnych.\n")

    L.append("## Strumienie miesięczne — stan w ostatnim miesiącu\n")
    L.append("| Kontrahent | Miesiąc | Kwota | Zmiana m/m | r/r | Flagi | Faza |")
    L.append("| --- | --- | --- | --- | --- | --- | --- |")
    rows = []
    for s in monthly:
        f = frames[s.stream_id][-1]
        ph = s_phases[s.stream_id][-1]
        flags = ", ".join(n for n, v in (("anomalia", f.anomaly), ("defekt", f.defect), ("skręt", f.twist),
                                           ("ponad CPI", bool(f.baseline_hit))) if v) or "–"
        rows.append((-ph, s.counterparty, f"| {s.counterparty} | {f.month} | {_zl(f.amount_gr)} | {_pct(f.defect_rel)} | "
                                         f"{_pct(f.yoy)} | {flags} | {NAMES[ph]} |"))
    for _, _, r in sorted(rows):
        L.append(r)
    L.append("")

    events = [(m, v) for m, v in res.items() if v["resonance_m"]]
    L.append("## Rezonans M (co najmniej 3 strumienie ze zdarzeniem w tym samym miesiącu)\n")
    if events:
        for m, v in events[-12:]:
            L.append(f"- {m}: {v['n_events']} z {v['n_streams']} strumieni")
    else:
        L.append("- brak")
    L.append("")

    L.append("## Budżet — agregat Λ–τ–ρ–J i faza (ostatnie 12 miesięcy)\n")
    L.append(f"Kalibracja faz budżetu: **{calib.status}** ({calib.reason}). Progi ρ: przejściowa > {_num(calib.rho_transitional)}, "
             f"krytyczna > {_num(calib.rho_critical)}.\n")
    if not cpi_given:
        L.append("Brak pliku CPI: kanał J i reguła „ponad CPI” są niepoliczone (–), a nie zerowe.\n")
    L.append("| Miesiąc | Strumienie | Λ | τ | ρ | J | Faza |")
    L.append("| --- | --- | --- | --- | --- | --- | --- |")
    for b, ph in list(zip(bmeta, b_phases))[-12:]:
        s = b.state
        L.append(f"| {b.month} | {b.n_streams} | {_num(s.Lambda)} | {_num(s.tau)} | {_num(s.rho)} | {_num(s.J)} | {NAMES[ph]} |")
    L.append("")
    if hard:
        L.append(f"Twarda reguła (prognozowane saldo < 0 w 30 dni) zadziałała w miesiącach: {', '.join(sorted(hard))}.\n")

    if irregular:
        L.append("## Strumienie nieregularne (bez sygnałów w etapie 0)\n")
        for s in irregular:
            L.append(f"- {s.counterparty}: {s.n_payments} płatności w {len(s.months)} miesiącach")
        L.append("")

    L.append("## Ślad audytowy\n")
    for k, v in hashes.items():
        L.append(f"- {k}: `{v}`")
    L.append("")
    L.append("Sygnały TIMDR są tu diagnostyką obok prostej reguły „r/r ponad CPI + 5 pp”. "
             "Zgodnie z planem nie wpływają na decyzje, dopóki nie przejdą pre-rejestrowanego testu P1.\n")
    return "\n".join(L)
