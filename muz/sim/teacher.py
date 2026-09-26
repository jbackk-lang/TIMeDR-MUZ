"""Nauczyciel syntetyczny: jawne reguly etykietujace akcje w pakietach budzetow (prereg/muz_decision_v0.2.json).

Korzysta tylko z tego, co widzi tez model (kwoty, zmiana r/r, CPI, umowa, dochod), wiec etykiety sa
uczalne z cech. Nie korzysta z sygnalow TIMDR - dzieki temu mozna sprawdzic, czy model uczy sie
reguly biznesowej, a nie odbija z powrotem wlasnych wejsc.
"""
from __future__ import annotations


def teacher_action(*, amount_gr: int, amount_12m_ago_gr: int | None, cpi_yoy: float | None, contract: dict | None,
                   income_month_gr: float, cfg: dict) -> str:
    t = cfg["teacher"]
    c = contract or {}
    cat = c.get("category", "inne")
    if cat in t["not_negotiable"] or not amount_12m_ago_gr or amount_12m_ago_gr <= 0 or cpi_yoy is None:
        return "zostawic"
    yoy = amount_gr / amount_12m_ago_gr - 1.0
    extra_annual = max(0, amount_gr - amount_12m_ago_gr) * 12
    over_cpi = yoy > cpi_yoy + t["cpi_margin"]
    material = income_month_gr > 0 and extra_annual >= t["materiality_annual_share_of_monthly_income"] * income_month_gr
    if not (over_cpi and material):
        return "zostawic"
    nego = c.get("negotiations", 0) or 0
    if nego == 0 or cat == "kredyt":
        return "negocjowac"
    if cat in t["cancellable"]:
        return "anulowac"
    if cat in t["switchable"]:
        return "zmienic"
    return "negocjowac"
