"""Zarzadca bez wpisywania: rozpoznanie kategorii, wklejanie tekstu, pelny przebieg z folderu -- dane syntetyczne."""
from datetime import date

import synth
from muz import rozpoznanie, wklej, zarzadca
from muz.ustawienia import Ustawienia

TODAY = date(2026, 6, 14)


def test_kategorie_z_nazwy_i_tytulu():
    assert rozpoznanie.category("ORANGE POLSKA") == "telekom"
    assert rozpoznanie.category("PGE OBROT") == "energia"
    assert rozpoznanie.category("NETFLIX COM") == "subskrypcja"
    assert rozpoznanie.category("DISNEY PLUS") == "subskrypcja"
    assert rozpoznanie.category("WSPOLNOTA MIESZKANIOWA LAKOWA 5") == "czynsz"
    assert rozpoznanie.category("JAN KOWALSKI", ["Rata kredytu 12/60"]) == "kredyt"
    assert rozpoznanie.category("BIEDRONKA") == "inne"


def test_wklej_linie_z_data_i_kwota():
    text = "12.06.2026 Biedronka Warszawa -45,50 zł\n2026-06-13\tOrlen\t-210,00 PLN\n13.06 Wynagrodzenie 5 400,00 zł\n"
    rows, skipped = wklej.parse_text(text, TODAY)
    assert skipped == 0
    assert [(r.date, r.amount_gr) for r in rows] == [(date(2026, 6, 12), -4550), (date(2026, 6, 13), -21000),
                                                     (date(2026, 6, 13), 540000)]
    assert "Biedronka" in rows[0].text


def test_wklej_strona_banku_opis_kwota_data():
    text = "Lidl sp. z o.o.\nPłatność kartą\n-67,89 PLN\n10.06.2026\nApteka Pod Lipami\n-23,10 PLN\n11.06.2026\n"
    rows, _ = wklej.parse_text(text, TODAY)
    assert [(r.date, r.amount_gr) for r in rows] == [(date(2026, 6, 10), -6789), (date(2026, 6, 11), -2310)]
    assert rows[0].text.startswith("Lidl")


def test_wklej_naglowek_dnia_i_lista():
    text = "12 czerwca 2026\nŻabka  -12,99 zł\nParking  -6,00 zł\nwczoraj\nKawa 14,50 zł\n"
    rows, _ = wklej.parse_text(text, TODAY)
    assert [(r.date, r.amount_gr) for r in rows] == [(date(2026, 6, 12), -1299), (date(2026, 6, 12), -600),
                                                     (date(2026, 6, 13), -1450)]


def test_wklej_tabela_z_excela_bez_naglowka(tmp_path):
    text = "2026-06-01\tCzynsz\t-2500,00\n2026-06-03\tPrąd PGE\t-230,40\n2026-06-05\tSklep\t-80,00\n"
    rows, _ = wklej.parse(text, TODAY)
    assert sorted(r.amount_gr for r in rows) == [-250000, -23040, -8000]
    p = tmp_path / "wklejone.csv"
    assert wklej.append(rows, p) == 3
    assert wklej.append(rows, p) == 0          # drugi raz te same -- nic nie dopisuje


def _setup(tmp_path):
    wy, dane, out = tmp_path / "wyciagi", tmp_path / "dane", tmp_path / "wyniki"
    src = synth.write_bank_csv(tmp_path / "pobrane_z_banku.csv", synth.transactions())
    zarzadca.add_files([src], wy)
    dane.mkdir()
    months = [f"{y}-{m:02d}" for y in (2023, 2024, 2025, 2026) for m in range(1, 13)]
    (dane / "cpi.csv").write_text("miesiac;cpi_rr\n" + "\n".join(f"{m};4,0" for m in months), encoding="utf-8")
    return wy, dane, out


def test_przebieg_bez_zadnego_wpisywania(tmp_path):
    wy, dane, out = _setup(tmp_path)
    ust = Ustawienia(tmp_path / "ustawienia.json")
    w = zarzadca.run(TODAY, ust, wyciagi=wy, dane=dane, wyniki=out, formats_path=tmp_path / "f.json",
                     salt_path=tmp_path / "salt", cpi_fetch=lambda *_: (_ for _ in ()).throw(OSError("offline")))
    assert w.plan is not None and w.plan.balance_gr is not None
    cats = {o["kontrahent"]: o["kategoria"] for o in w.oplaty}
    assert cats["ORANGE POLSKA"] == "telekom" and cats["NETFLIX COM"] == "subskrypcja"
    orange = [s for s in w.sprawy if s.kontrahent == "ORANGE POLSKA"]
    assert orange and orange[0].akcja == "negocjowac"
    assert (out / "decyzje.csv").exists() and (out / "transakcje_muz.csv").exists()

    # nie udalo sie -> nastepnym razem zmiana oferty (telekom), bez zadnego wpisywania umowy
    ust.done(orange[0].id, "ORANGE POLSKA", "negocjowac", "nie_udalo_sie", None, TODAY)
    w2 = zarzadca.run(TODAY, ust, wyciagi=wy, dane=dane, wyniki=out, formats_path=tmp_path / "f.json", salt_path=tmp_path / "salt")
    o2 = [s for s in w2.sprawy if s.kontrahent == "ORANGE POLSKA"]
    assert o2 and o2[0].akcja == "zmienic"

    # zalatwione -> znika z listy
    ust.done(o2[0].id, "ORANGE POLSKA", "zmienic", "udalo_sie", 79.0, TODAY)
    w3 = zarzadca.run(TODAY, ust, wyciagi=wy, dane=dane, wyniki=out, formats_path=tmp_path / "f.json", salt_path=tmp_path / "salt")
    assert not [s for s in w3.sprawy if s.kontrahent == "ORANGE POLSKA"]


def test_saldo_wpisane_w_oknie_i_wklejona_gotowka(tmp_path):
    wy, dane, out = _setup(tmp_path)
    ust = Ustawienia(tmp_path / "ustawienia.json")
    ust.set_saldo(1500.0, TODAY)
    rows, _ = wklej.parse_text("13.06.2026 Targ warzywa -40,00 zł\n", TODAY)
    wklej.append(rows, dane / "wklejone.csv")
    w = zarzadca.run(TODAY, ust, wyciagi=wy, dane=dane, wyniki=out, formats_path=tmp_path / "f.json", salt_path=tmp_path / "salt")
    assert w.plan.balance_gr == 150000
    assert any(p["plik"] == "wklejone.csv" for p in w.pliki)


def test_pusty_folder_mowi_co_zrobic(tmp_path):
    w = zarzadca.run(TODAY, Ustawienia(tmp_path / "u.json"), wyciagi=tmp_path / "brak", dane=tmp_path / "d", wyniki=tmp_path / "w")
    assert w.plan is None and "dodaj" in w.problemy[0]


def test_pismo_do_wydruku(tmp_path):
    import pytest
    wy, dane, out = _setup(tmp_path)
    ust = Ustawienia(tmp_path / "ustawienia.json")
    w = zarzadca.run(TODAY, ust, wyciagi=wy, dane=dane, wyniki=out, formats_path=tmp_path / "f.json", salt_path=tmp_path / "salt")
    if w.pdf_note:
        pytest.skip(w.pdf_note)
    s = next(s for s in w.sprawy if s.kontrahent == "ORANGE POLSKA")
    p = zarzadca.letter_pdf(s, ust, TODAY, out / "pisma")
    assert p.exists() and p.read_bytes()[:5] == b"%PDF-" and "Prosba_o_obnizke" in p.name


def test_wklej_mieszany_format():
    text = "Lidl\n-67,89 PLN\n10.06.2026\n12 czerwca 2026\nŻabka  -12,99 zł\n"
    rows, skipped = wklej.parse_text(text, TODAY)
    assert skipped == 0 and [(r.date, r.amount_gr) for r in rows] == [(date(2026, 6, 10), -6789), (date(2026, 6, 12), -1299)]
