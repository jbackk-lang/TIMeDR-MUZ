"""Modul 5: mini-AI TIMDR - klasyfikator akcji anulowac / negocjowac / zmienic / zostawic.

Domyslnie maly MLP w NumPy (42 -> 32 -> 16 -> 4; rozmiar z prereg/muz_decision_v0.2.json). Warianty CNN 1D i TinyTransformer sa
wariantami badawczymi (trening JAX/Keras) i nie wchodza do prototypu.
"""
from .features import FEATURE_NAMES, build_features
from .mlp import MLP, log_loss
from .policy import ALLOWED_BY_PHASE, budget_action, budget_policy, propose, rule_policy

__all__ = ["FEATURE_NAMES", "build_features", "MLP", "log_loss", "ALLOWED_BY_PHASE", "propose", "rule_policy", "budget_action", "budget_policy"]
