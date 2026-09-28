"""Lista decyzji dla Excela i PDF zabiegow z tytulem -- dane syntetyczne."""
import csv
from datetime import date

import pytest

from muz import decisions, export_docs, pipeline
from test_decisions import _files


def test_lista_excel_i_pdf_z_tytulem(tmp_path):
    bank, cpi, contracts = _files(tmp_path)
    prof = tmp_path / "profil.json"
    prof.write_text('{"saldo_zl": 3200, "dlugi": [{"nazwa": "karta", "kwota_zl": 4000, "oprocentowanie_proc": 20}]}',
                    encoding="utf-8")
    r = pipeline.decide([bank], None, tmp_path / "out", today=date(2026, 6, 14), cpi_path=cpi, contracts_path=contracts,
                        profile_path=prof, salt_path=tmp_path / "salt", formats_path=tmp_path / "f.json")
    rows = list(csv.DictReader((tmp_path / "out" / "decyzje.csv").read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))
    orange = [x for x in rows if x["kontrahent"] == "ORANGE POLSKA"]
    assert orange and orange[0]["zabieg"].startswith("Negocjuj cenę: ORANGE POLSKA") and orange[0]["cel_zl"] == "89,00"
    assert any(x["rodzaj"] == "przydział" for x in rows)
    assert (tmp_path / "out" / "transakcje_muz.csv").exists()
    if r["pdf_note"]:
        pytest.skip(r["pdf_note"])
    titles = [t for t, _ in r["pdfs"]]
    assert titles[0] == "Przydział do wypłaty" and any(t.startswith("Negocjuj cenę: ORANGE") for t in titles)
    p = dict(r["pdfs"])[decisions.card_title(r["cards"][0])]
    assert p.name == "2026-06-14_Negocjuj_cene_ORANGE_POLSKA.pdf" and p.read_bytes()[:5] == b"%PDF-"
    assert orange[0]["pdf"] == p.name


def test_slug():
    assert export_docs.slug("Zmień plan lub dostawcę: PGE OBRÓT — szukaj ceny ≤ 10 zł") == "Zmien_plan_lub_dostawce_PGE_OBROT"
