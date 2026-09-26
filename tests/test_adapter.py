"""Modul 1: adapter GSF -> LSF -> dane PL."""
import json
from datetime import date

import pytest

from muz import adapter
from muz.adapter import gus, nbp
from muz.core.netguard import HostNotAllowed
import synth

SALT = b"s" * 32


def _csv(tmp_path, n=30):
    return synth.write_bank_csv(tmp_path / "w.csv", synth.transactions(n))


def test_csv_cp1250_preamble_decimal_comma(tmp_path):
    recs = adapter.load_csv(_csv(tmp_path), synth.MAPPING, SALT)
    first = [r for r in recs if r.counterparty == "ORANGE POLSKA"][0]
    assert first.amount_gr == -8900 and first.currency == "PLN" and first.date == date(2024, 1, 5)
    assert first.balance_gr is not None
    assert any(r.counterparty == "WSPOLNOTA MIESZKANIOWA LAKOWA 5" for r in recs)  # polskie znaki z CP1250


def test_iban_hashed_and_removed(tmp_path):
    recs = adapter.load_csv(_csv(tmp_path), synth.MAPPING, SALT)
    orange = [r for r in recs if r.counterparty == "ORANGE POLSKA"]
    assert orange[0].iban_hash and len(orange[0].iban_hash) == 16
    assert all("1090101400000712" not in (r.counterparty + r.description) for r in orange)


def test_counterparty_normalization_merges_variants():
    assert adapter.normalize_counterparty("ORANGE POLSKA S.A.") == adapter.normalize_counterparty("Orange Polska SA")
    assert adapter.normalize_counterparty("Pracodawca Sp. z o.o.") == "PRACODAWCA"


def test_amount_parsing():
    assert adapter.parse_amount_gr("-1 234,56") == -123456
    assert adapter.parse_amount_gr("1.234,56") == 123456
    assert adapter.parse_amount_gr("-89,00PLN") == -8900


def test_dedup_overlapping_exports_but_keeps_same_day_duplicates(tmp_path):
    a = synth.write_bank_csv(tmp_path / "a.csv", synth.transactions(6))
    b = synth.write_bank_csv(tmp_path / "b.csv", synth.transactions(6))
    recs = adapter.load_csv(a, synth.MAPPING, SALT) + adapter.load_csv(b, synth.MAPPING, SALT)
    assert len(adapter.deduplicate(recs)) == len(recs) // 2
    tx = synth.transactions(2) + [synth.transactions(2)[1]]  # ta sama platnosc dwa razy w jednym pliku
    c = synth.write_bank_csv(tmp_path / "c.csv", tx)
    rc = adapter.load_csv(c, synth.MAPPING, SALT)
    assert len(adapter.deduplicate(rc)) == len(rc)


def test_streams_monthly_vs_irregular(tmp_path):
    streams = adapter.build_streams(adapter.load_csv(_csv(tmp_path), synth.MAPPING, SALT))
    cad = {s.counterparty: s.cadence for s in streams}
    assert cad["ORANGE POLSKA"] == "monthly" and cad["PZU"] == "irregular"
    assert "PRACODAWCA" not in cad  # wplywy nie sa strumieniami kosztow
    orange = [s for s in streams if s.counterparty == "ORANGE POLSKA"][0]
    assert orange.amounts_gr[19] == 8900 and orange.amounts_gr[20] == 11900
    assert all(orange.month_records[m] for m in orange.months)


def test_mt940(tmp_path):
    p = tmp_path / "w.sta"
    p.write_text(synth.MT940_SAMPLE, encoding="utf-8")
    recs = adapter.load_mt940(p, SALT)
    assert [r.amount_gr for r in recs] == [-8900, 800000]
    assert recs[0].counterparty == "ORANGE POLSKA" and recs[0].iban_hash
    assert recs[0].description.startswith("Abonament")
    assert recs[1].counterparty == "PRACODAWCA"


def test_contracts_only_confirmed(tmp_path):
    p = tmp_path / "umowy.json"
    p.write_text(json.dumps(synth.CONTRACTS), encoding="utf-8")
    c = adapter.load_contracts(p)
    assert "ORANGE POLSKA" in c and "NETFLIX COM" not in c


def test_nbp_conversion_with_weekend_fallback():
    calls = []

    def fake_fetch(url, allowed):
        calls.append(url)
        assert "api.nbp.pl" in allowed
        if "2024-06-08" in url:  # sobota - brak tabeli
            raise IOError("404")
        return json.dumps({"rates": [{"mid": 4.3}]}).encode()

    rate, day = nbp.mid_rate("EUR", date(2024, 6, 8), fake_fetch)
    assert rate == 4.3 and day == date(2024, 6, 7)
    rec = adapter.LSFRecord(date(2024, 6, 7), -1000, "EUR", "X", "", "", None, "f", "h")
    out = nbp.convert_to_pln([rec], fake_fetch)[0]
    assert out.currency == "PLN" and out.amount_gr == -4300


def test_gus_bdl_requires_allowed_host_and_api_path():
    with pytest.raises(ValueError):
        gus.fetch_bdl("https://evil.example/api/x", fetcher=lambda u, a: b"")
    seen = {}
    gus.fetch_bdl("/api/v1/data", fetcher=lambda u, a: seen.setdefault("u", (u, a)) and b"")
    assert seen["u"][0].startswith("https://bdl.stat.gov.pl/api/") and seen["u"][1] == frozenset({"bdl.stat.gov.pl"})


def test_detect_header_and_guess_mapping(tmp_path):
    p = _csv(tmp_path, 3)
    idx, cols = adapter.csv_import.detect_header(p)
    assert idx == 3 and cols[0] == "Data operacji"
    m = adapter.csv_import.guess_mapping(cols)
    assert m == {"date": "Data operacji", "amount": "Kwota", "counterparty": "Nadawca / Odbiorca",
                 "description": "Tytuł", "currency": "Waluta", "balance": "Saldo po operacji"}
    recs = adapter.load_csv(p, m, SALT)
    assert len(recs) > 0


def test_parse_gus_monthly_csv_yoy_only():
    raw = ("Nazwa zmiennej;Jednostka terytorialna;Sposób prezentacji;Rok;Miesiąc;Wartość;Flaga\n"
           "Ogółem;Polska;Analogiczny miesiąc poprzedniego roku = 100;2025;1;104,9;\n"
           "Ogółem;Polska;Poprzedni miesiąc = 100;2025;1;101,0;\n"
           "Ogółem;Polska;Analogiczny miesiąc poprzedniego roku = 100;2025;2;104,9;\n").encode("cp1250")
    cpi = gus.parse_gus_monthly_csv(raw)
    assert cpi == {"2025-01": pytest.approx(0.049), "2025-02": pytest.approx(0.049)}


def test_parse_gus_unknown_layout_raises():
    with pytest.raises(ValueError):
        gus.parse_gus_monthly_csv("a;b;c\n1;2;3\n".encode())
