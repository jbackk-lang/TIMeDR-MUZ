"""Modul 6: TIMDR-AI-Core jako warstwa epistemologiczna.

- claims:     twierdzenia o pojedynczej decyzji (Claim Graph: Decision, render, gate_candidate),
- registry:   twierdzenia o modelach i progach (TIMDRProtocol: preregister, run_controls, run_test),
- validation: testy walidacyjne P1/P2 (Mann-Whitney, rozmiar efektu, Bonferroni, kontrolki).
Kod AI-Core jest wendorowany (muz/_vendor/ai_core) z hashem w VENDOR.lock.json.
"""
from .claims import FORBIDDEN_PHRASES, verify_proposal
from .registry import ModelRegistry

__all__ = ["FORBIDDEN_PHRASES", "verify_proposal", "ModelRegistry"]
