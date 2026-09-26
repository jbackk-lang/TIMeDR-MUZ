"""Twierdzenia o pojedynczej decyzji: ActionProposal -> weryfikacja -> VerifiedClaim.

Regula z dokumentu MUZ (modul 6):
1. kazda liczba w uzasadnieniu ma rekord zrodlowy,
2. brak sprzecznosci miedzy rekordami (np. uzytkownik oznaczyl podwyzke jako uzasadniona),
3. komplet danych: "anulowac" wymaga okresu wypowiedzenia i kanalu rezygnacji,
4. swiezosc: dane starsze niz 7 dni -> INCONCLUSIVE,
5. brak twierdzen zakazanych (gwarancje oszczednosci, porady inwestycyjne, obietnice wyniku).
Werdykty: SUPPORTED / INCONCLUSIVE / REJECTED. Do bramki trafia tylko SUPPORTED.
"""
from __future__ import annotations

from datetime import date

from .._vendor.ai_core.claim_graph_gate import Decision, gate_candidate, render
from ..core.common import canonical_json, sha256_file, sha256_text

FORBIDDEN_PHRASES = (
    "gwarantowana oszczednosc", "gwarantowana oszczędność", "gwarantuje", "na pewno obniz", "na pewno obniż",
    "porada inwestycyjna", "kup ", "sprzedaj", "zainwestuj",
)
MAX_AGE_DAYS = 7
RULES_SHA256 = sha256_file(__file__)

ACTION_TEXT = {"anulowac": "wypowiedzenie umowy", "negocjowac": "prośba o obniżkę", "zmienic": "zmiana planu lub dostawcy",
               "zostawic": "bez działania"}


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%".replace(".", ",")


def verify_proposal(*, proposal: dict, stream, frames: list, cpi: dict | None, data_as_of: date,
                    today: date, paraphrase: str | None = None) -> dict:
    """Zwraca payload muz.verified_claim/1."""
    f = frames[-1]
    cp = stream.counterparty
    record_ids: list[str] = []
    facts: list[str] = []
    reasons: list[str] = []
    verdict = "SUPPORTED"

    # 1. liczby z rekordami zrodlowymi
    if f.defect_rel is not None and len(frames) >= 2:
        prev = frames[-2]
        for m in (prev.month, f.month):
            record_ids += [f"lsf:{h[:16]}" for h in stream.month_records.get(m, [])]
        zl = lambda gr: f"{gr / 100:.2f}".replace(".", ",")
        facts.append(f"{cp}: {zl(prev.amount_gr)} zł ({prev.month}) → {zl(f.amount_gr)} zł ({f.month}), "
                     f"zmiana {_pct(f.defect_rel)}")
    if f.yoy is not None:
        facts.append(f"zmiana rok do roku {_pct(f.yoy)}")
        if cpi is not None and f.month in cpi:
            record_ids.append(f"cpi:{f.month}")
            facts.append(f"CPI r/r {cpi[f.month] * 100:.1f}%".replace(".", ","))
    if stream.contract:
        record_ids.append(f"umowa:{sha256_text(canonical_json(stream.contract))[:16]}")
    if not record_ids:
        verdict, reasons = "INCONCLUSIVE", reasons + ["brak rekordow zrodlowych dla uzasadnienia"]

    # 2. sprzecznosc
    explained = (stream.contract or {}).get("explained_changes", [])
    if f.month in explained:
        verdict = "REJECTED"
        reasons.append(f"uzytkownik oznaczyl zmiane w {f.month} jako uzasadniona (np. lepszy pakiet)")

    # 3. komplet danych
    required: list[str] = []
    if proposal["action"] == "anulowac":
        required = ["notice_period_months", "cancel_channel"]
        missing = [k for k in required if not (stream.contract or {}).get(k)]
        if missing and verdict != "REJECTED":
            verdict = "INCONCLUSIVE"
            reasons.append("brakuje danych umowy: " + ", ".join(missing) + " - dodaj umowe")

    # 4. swiezosc
    age = (today - data_as_of).days
    if age > MAX_AGE_DAYS and verdict == "SUPPORTED":
        verdict = "INCONCLUSIVE"
        reasons.append(f"dane sprzed {age} dni (limit {MAX_AGE_DAYS})")

    # tekst deterministyczny (renderer)
    answer = (f"Propozycja: {ACTION_TEXT[proposal['action']]} ({cp}). Podstawa: " + "; ".join(facts) + "."
              if facts else f"Propozycja: {ACTION_TEXT[proposal['action']]} ({cp}).")
    decision = Decision(node_id=f"muz:{stream.stream_id}:{f.month}", verdict=verdict, answer=answer,
                        record_ids=tuple(record_ids), required=tuple(required), forbidden=FORBIDDEN_PHRASES)
    text = render(decision)

    # 5. zakazane twierdzenia (w tekscie deterministycznym i w ewentualnej parafrazie)
    lowered = text.lower()
    if any(p in lowered for p in FORBIDDEN_PHRASES):
        verdict = "REJECTED"
        reasons.append("tekst zawiera twierdzenie zakazane")
    paraphrase_gate = None
    if paraphrase is not None:
        paraphrase_gate = gate_candidate(decision, paraphrase)
        if paraphrase_gate["accepted"]:
            text = paraphrase

    node = {"claim_id": decision.node_id, "verdict": verdict, "record_ids": record_ids, "required": required,
            "rules_sha256": RULES_SHA256, "proposal_action": proposal["action"]}
    return {"claim_id": decision.node_id, "verdict": verdict, "record_ids": record_ids,
            "requirements_met": verdict != "INCONCLUSIVE", "text": text, "reasons": reasons,
            "graph_sha256": sha256_text(canonical_json(node)), "paraphrase_gate": paraphrase_gate}

