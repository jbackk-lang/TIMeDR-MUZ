"""Wyrazne decyzje: przydzial do wyplaty i karty dzialania -- dane syntetyczne."""
import json
from datetime import date

import synth
from muz import decisions, pipeline


def _files(tmp_path):
    bank = synth.write_bank_csv(tmp_path / "bank.csv", synth.transactions())
    cpi = tmp_path / "cpi.csv"
    months = [f"{y}-{m:02d}" for y in (2023, 2024, 2025, 2026) for m in range(1, 13)]
    cpi.write_text("miesiac;cpi_rr\n" + "\n".join(f"{m};4,0" for m in months), encoding="utf-8")
    contracts = tmp_path / "umowy.json"
    contracts.write_text(json.dumps(synth.CONTRACTS), encoding="utf-8")
    return bank, cpi, contracts


def test_decyzje_przydzial_i_karta_negocjacji(tmp_path):
    bank, cpi, contracts = _files(tmp_path)
    # synth: wyplata 1. dnia miesiaca, ostatni miesiac 2026-06
    r = pipeline.decide([bank], None, tmp_path / "out", today=date(2026, 6, 25), cpi_path=cpi,
                        contracts_path=contracts, salt_path=tmp_path / "salt", formats_path=tmp_path / "f.json")
    plan = r["plan"]
    assert plan.next_payday in (date(2026, 7, 1), date(2026, 7, 2))
    names = [n for _, n, _ in plan.due]
    assert any("WSPOLNOTA" in n for n in names) is False  # czynsz 10. dnia -- po wyplacie
    assert plan.balance_gr is not None
    # bilans przydzialu: rezerwa + zycie + odlozenia + nadplata + reszta = saldo (gdy nie brakuje)
    if plan.shortfall_gr == 0:
        assert plan.reserve_gr + plan.allowance_gr + plan.to_fund_gr + plan.to_buffer_gr + plan.to_debt_gr + plan.left_gr \
               == plan.balance_gr
    md = (tmp_path / "out" / "decyzje.md").read_text(encoding="utf-8")
    assert "Do następnej wypłaty" in md
    orange = [k for k in r["cards"] if k["counterparty"] == "ORANGE POLSKA"]
    assert orange and orange[0]["action"] == "negocjowac"
    k = orange[0]
    assert k["before_gr"] == 8900 and k["now_gr"] == 11900 and k["max_ok_gr"] == round(8900 * 1.04)
    assert k["yearly_gr"] == (11900 - round(8900 * 1.04)) * 12
    assert "Co powiedzieć" in md and "Nie zgadzaj się na" in md and "89,00 zł" in md
    assert (tmp_path / "out" / "decyzje.json").exists()


def test_tryb_wychodzenia_z_dlugu_nadplaca_najdrozszy(tmp_path):
    bank, cpi, contracts = _files(tmp_path)
    ctx = pipeline.prepare([bank], None, cpi, contracts, tmp_path / "salt", formats_path=tmp_path / "f.json")
    prof = {"saldo_zl": 9000, "dlugi": [{"nazwa": "karta", "kwota_zl": 4000, "oprocentowanie_proc": 20},
                                        {"nazwa": "pozyczka", "kwota_zl": 10000, "oprocentowanie_proc": 9}]}
    plan = decisions.cycle_plan(ctx["records"], ctx["streams"], today=date(2026, 6, 2), profile=prof)
    assert plan.mode == "wychodzenie z długu"
    need = plan.need_day_gr * plan.days
    assert plan.allowance_gr == int(0.80 * need)
    assert plan.to_debt_gr == 0 or plan.debt_target.startswith("karta")
    assert plan.reserve_gr + plan.allowance_gr + plan.to_fund_gr + plan.to_buffer_gr + plan.to_debt_gr + plan.left_gr == 900000


def test_brak_salda_nie_zgaduje(tmp_path):
    bank, cpi, contracts = _files(tmp_path)
    ctx = pipeline.prepare([bank], None, cpi, contracts, tmp_path / "salt", formats_path=tmp_path / "f.json")
    recs = [r.__class__(**{**r.__dict__, "balance_gr": None}) for r in ctx["records"]]
    plan = decisions.cycle_plan(recs, ctx["streams"], today=date(2026, 6, 25))
    assert plan.balance_gr is None and plan.allowance_gr == 0
    assert "na koncie" in decisions.render_cycle(plan)


def test_krotka_historia_nie_zawiesza():
    # jeden-dwa miesiace wyciagu (np. jeden PDF): wczesniej petla nextpayday krecila sie w nieskonczonosc
    assert decisions.next_payday([date(2026, 5, 1)], date(2026, 6, 14))[0] == date(2026, 6, 30)
    nxt, step = decisions.next_payday([date(2026, 5, 1), date(2026, 6, 1)], date(2026, 6, 14))
    assert step == 31 and nxt == date(2026, 7, 2)
    assert decisions.next_payday([], date(2026, 6, 14))[0] == date(2026, 7, 14)
