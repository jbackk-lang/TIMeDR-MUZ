"""Nauczyciel syntetyczny (od v0.3 to ta sama funkcja, ktora tworzy plany - mini_ai.policy.budget_action): jawne reguly etykietujace akcje w pakietach budzetow (prereg/muz_decision_v0.2.json).

Korzysta tylko z tego, co widzi tez model (kwoty, zmiana r/r, CPI, umowa, dochod), wiec etykiety sa
uczalne z cech. Nie korzysta z sygnalow TIMDR - dzieki temu mozna sprawdzic, czy model uczy sie
reguly biznesowej, a nie odbija z powrotem wlasnych wejsc.
"""
from __future__ import annotations

from ..mini_ai.policy import budget_action as teacher_action  # jedna definicja: nauczyciel = polityka budzetowa planow

__all__ = ["teacher_action"]
