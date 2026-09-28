"""Rozpoznanie bez wpisywania: kategoria oplaty po nazwie kontrahenta i tytule, raty i debet z wyciagu.

Kategorie jak w polityce budzetowej (prereg/muz_decision_v0.3.json): czynsz, energia, telekom, media,
subskrypcja, ubezpieczenie, kredyt, inne. Rozpoznanie jest propozycja: w oknie mozna ja jednym kliknieciem
poprawic albo potwierdzic. Do pism przez bramke ida tylko umowy potwierdzone.
"""
from __future__ import annotations

import re

from .adapter.csv_import import _strip_accents

KEYWORDS = {
    "kredyt": ["RATA", "KREDYT", "POZYCZK", "SPLATA", "LEASING", "PROVIDENT", "WONGA", "VIVUS", "RATY"],
    "czynsz": ["WSPOLNOTA", "SPOLDZIELNIA", "TBS", "ZARZADCA NIERUCH", "CZYNSZ", "NAJEM", "ZGM", "ZGN", "MZBM"],
    "energia": ["PGE", "TAURON", "ENEA", "ENERGA", "E ON", "EON ", "PGNIG", "INNOGY", "POLENERGIA", "FORTUM",
                "VEOLIA", "MPWIK", "WODOCIAG", "MPEC", "CIEPLO", "GAZ "],
    "telekom": ["ORANGE", "PLAY", "P4 SP", "PLUS", "POLKOMTEL", "T MOBILE", "TMOBILE", "HEYAH", "NJU", "VIRGIN MOBILE"],
    "media": ["UPC", "VECTRA", "NETIA", "INEA", "CYFROWY POLSAT", "POLSAT BOX", "CANAL", "TOYA", "MULTIMEDIA"],
    "subskrypcja": ["NETFLIX", "SPOTIFY", "HBO", "MAX COM", "DISNEY", "YOUTUBE", "APPLE COM", "ITUNES", "GOOGLE",
                    "AMAZON PRIME", "PRIME VIDEO", "TIDAL", "STORYTEL", "EMPIK GO", "LEGIMI", "ICLOUD", "MICROSOFT",
                    "ADOBE", "PLAYER PL", "SKYSHOWTIME", "MULTISPORT", "FITNESS", "SILOWNIA", "CITYFIT", "ZDROFIT"],
    "ubezpieczenie": ["PZU", "WARTA", "ALLIANZ", "HESTIA", "GENERALI", "UNIQA", "AVIVA", "LINK4", "COMPENSA",
                      "NATIONALE", "AXA", "TUW", "UBEZPIECZ", "POLISA"],
}
ORDER = ["kredyt", "czynsz", "subskrypcja", "ubezpieczenie", "energia", "media", "telekom"]


def _norm(text: str) -> str:
    s = _strip_accents(text or "").upper()
    return " " + re.sub(r"[^A-Z0-9]+", " ", s).strip() + " "


def category(counterparty: str, descriptions: list[str] = ()) -> str:
    """Najpierw nazwa kontrahenta, potem tytuly przelewow. Brak trafienia -> 'inne'."""
    for text in [counterparty] + list(descriptions):
        t = _norm(text)
        for cat in ORDER:
            if any(f" {k.strip()} " in t or (len(k.strip()) >= 5 and k.strip() in t) for k in KEYWORDS[cat]):
                return cat
    return "inne"


def infer_contracts(streams, records, overrides: dict[str, str] | None = None, confirmed: dict[str, bool] | None = None,
                    negotiations: dict[str, int] | None = None) -> dict[str, dict]:
    """Umowy z rozpoznania dla strumieni miesiecznych (+ poprawki uzytkownika z okna)."""
    overrides, confirmed, negotiations = overrides or {}, confirmed or {}, negotiations or {}
    desc: dict[str, list[str]] = {}
    for r in records:
        if r.amount_gr < 0:
            desc.setdefault(r.counterparty, []).append(r.description)
    out = {}
    for s in streams:
        if s.cadence != "monthly":
            continue
        cat = overrides.get(s.counterparty) or category(s.counterparty, desc.get(s.counterparty, [])[-6:])
        out[s.counterparty] = {"counterparty": s.counterparty, "category": cat,
                               "negotiations": negotiations.get(s.counterparty, 0),
                               "confirmed_by_user": bool(confirmed.get(s.counterparty)),
                               "inferred": s.counterparty not in overrides}
    return out


def overdraft(records) -> int:
    """Debet na koncu wyciagu (grosze, dodatnie) albo 0."""
    with_bal = [r for r in records if r.balance_gr is not None]
    if not with_bal:
        return 0
    last = max(with_bal, key=lambda r: r.date).balance_gr
    return -last if last < 0 else 0
