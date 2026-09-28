"""Wyciagi PDF -- tylko syntetyczne PDF-y generowane w tescie (reportlab)."""
from datetime import date

import pytest

pytest.importorskip("pdfplumber")
pytest.importorskip("reportlab")

import synth  # noqa: E402
from muz.adapter.pdf_import import PdfPasswordNeeded, PdfScanned, load_pdf  # noqa: E402
from muz.export_docs import _font  # noqa: E402

SALT = b"s" * 32


def _canvas(path, **kw):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    reg, _ = _font()
    if reg is None:
        pytest.skip("brak czcionki TTF")
    pdfmetrics.registerFont(TTFont("F", reg))
    c = canvas.Canvas(str(path), pagesize=A4, **kw)
    return c, A4


def _tx():
    return sorted(synth.transactions(n_months=6), key=lambda t: t[0])


def _zl(x, sign=True):
    s = f"{abs(x):,.2f}".replace(",", " ").replace(".", ",")
    return ("-" if x < 0 and sign else "") + s


def text_pdf(path, signed=True, **kw):
    """Uklad tekstowy: data operacji, data ksiegowania, opis (czasem w 2 liniach), kwota, saldo; naglowki i sumy."""
    c, (W, H) = _canvas(path, **kw)
    y = H - 50
    c.setFont("F", 9)
    for line in ["Bank Przykładowy S.A.", "Wyciąg nr 6/2024 za okres 01.01.2024 - 30.06.2024",
                 "Saldo początkowe: 20 000,00 PLN", "Data op.  Data ks.  Opis  Kwota  Saldo"]:
        c.drawString(40, y, line); y -= 14
    bal = 20000.0
    for i, (d, amt, cp, title) in enumerate(_tx()):
        bal += amt
        ds = d.strftime("%d.%m.%Y")
        c.drawString(40, y, ds); c.drawString(100, y, ds); c.drawString(160, y, cp.split(" PL")[0][:30])
        c.drawRightString(470, y, _zl(amt, signed)); c.drawRightString(550, y, _zl(bal))
        y -= 12
        if i % 3 == 0:
            c.drawString(160, y, f"Tytuł: {title} nr ref. ABC{i}"); y -= 12
        if y < 80:
            c.drawString(40, 40, "Strona 1"); c.showPage(); c.setFont("F", 9); y = H - 50
    c.drawString(40, y - 10, f"Saldo końcowe: {_zl(bal)} PLN")
    c.save()
    return path


def table_pdf(path):
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
    reg, _ = _font()
    if reg is None:
        pytest.skip("brak czcionki TTF")
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    pdfmetrics.registerFont(TTFont("F", reg))
    data = [["Data", "Kontrahent", "Tytuł", "Kwota", "Saldo"]]
    bal = 5000.0
    for d, amt, cp, title in _tx():
        bal += amt
        data.append([d.strftime("%d.%m.%Y"), cp.split(" PL")[0][:30], title, _zl(amt), _zl(bal)])
    t = Table(data)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "F", 8), ("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(str(path)).build([t])
    return path


def _check(recs):
    tx = _tx()
    assert len(recs) == len(tx)
    assert sorted(r.amount_gr for r in recs) == sorted(round(a * 100) for _, a, _, _ in tx)
    assert min(r.date for r in recs) == tx[0][0]


def test_pdf_tekstowy_z_saldem(tmp_path):
    recs = load_pdf(text_pdf(tmp_path / "wyciag.pdf"), SALT)
    _check(recs)
    assert all(r.balance_gr is not None for r in recs)
    assert any("Abonament" in r.description for r in recs)          # ciag dalszy opisu doklejony


def test_pdf_bez_znakow_kwot_znak_z_salda(tmp_path):
    _check(load_pdf(text_pdf(tmp_path / "bez_znaku.pdf", signed=False), SALT))


def test_pdf_tabela(tmp_path):
    recs = load_pdf(table_pdf(tmp_path / "tabela.pdf"), SALT)
    _check(recs)
    assert any(r.counterparty == "ORANGE POLSKA" for r in recs)


def test_pdf_z_haslem(tmp_path):
    p = text_pdf(tmp_path / "haslo.pdf", encrypt="12345678901")
    with pytest.raises(PdfPasswordNeeded):
        load_pdf(p, SALT)
    _check(load_pdf(p, SALT, password="12345678901"))


def test_pdf_skan(tmp_path):
    c, (W, H) = _canvas(tmp_path / "skan.pdf")
    c.rect(50, 50, 400, 600, fill=1)
    c.save()
    with pytest.raises(PdfScanned):
        load_pdf(tmp_path / "skan.pdf", SALT)


def test_pdf_w_oknie_zarzadcy_i_haslo_raz(tmp_path):
    from muz import zarzadca
    from muz.ustawienia import Ustawienia
    wy, dane, out = tmp_path / "wyciagi", tmp_path / "dane", tmp_path / "wyniki"
    wy.mkdir(); dane.mkdir()
    (dane / "cpi.csv").write_text("miesiac;cpi_rr\n" + "\n".join(f"{y}-{m:02d};4,0" for y in (2023, 2024) for m in range(1, 13)),
                                  encoding="utf-8")
    text_pdf(wy / "czerwiec.pdf")
    text_pdf(wy / "zabezpieczony.pdf", encrypt="12345678901")
    ust = Ustawienia(tmp_path / "u.json")
    kw = dict(wyciagi=wy, dane=dane, wyniki=out, formats_path=tmp_path / "f.json", salt_path=tmp_path / "salt")
    w = zarzadca.run(date(2024, 7, 2), ust, **kw)
    assert [p["plik"] for p in w.pliki] == ["czerwiec.pdf"] and [f.name for f in w.hasla] == ["zabezpieczony.pdf"]
    csv_out = zarzadca.unlock_pdf(wy / "zabezpieczony.pdf", "12345678901", ust, wyciagi=wy, salt_path=tmp_path / "salt")
    assert csv_out.name == "zabezpieczony (z PDF).csv"
    w2 = zarzadca.run(date(2024, 7, 2), ust, **kw)
    assert not w2.hasla and {p["plik"] for p in w2.pliki} == {"czerwiec.pdf", "zabezpieczony (z PDF).csv"}
    assert "12345678901" not in (tmp_path / "u.json").read_text(encoding="utf-8")


def realistic_pdf(path, months):
    """Opisy jak w prawdziwych PDF: rodzaj operacji na poczatku, numery kart i sklepow, forma prawna, miasto."""
    c, (W, H) = _canvas(path)
    y = H - 50
    c.setFont("F", 8)
    bal = 3000.0
    rows = []
    for m in range(1, months + 1):
        rows += [(date(2026, m, 1), 5200.0, "PRZELEW PRZYCHODZĄCY PRACODAWCA SP. Z O.O. Tytuł: Wynagrodzenie"),
                 (date(2026, m, 5), -89.0, "PRZELEW WYCHODZĄCY Orange Polska S.A. Tytuł: Abonament FV/" + str(m)),
                 (date(2026, m, 7), -45.0, "ZLECENIE STAŁE NETFLIX.COM"),
                 (date(2026, m, 9), -63.2 - m, f"PŁATNOŚĆ KARTĄ 4567 XXXX XXXX 1234 BIEDRONKA {1000 + m} WARSZAWA"),
                 (date(2026, m, 20), -230.0 - m, "POLECENIE ZAPŁATY PGE Obrót S.A. faktura " + str(m))]
    for d, amt, desc in rows:
        bal += amt
        c.drawString(30, y, d.strftime("%d.%m.%Y")); c.drawString(85, y, desc[:70])
        c.drawRightString(500, y, _zl(amt)); c.drawRightString(570, y, _zl(bal)); y -= 12
    c.save()
    return path


def _run(tmp_path, months):
    from muz import zarzadca
    from muz.ustawienia import Ustawienia
    wy, dane = tmp_path / "wyciagi", tmp_path / "dane"
    wy.mkdir(); dane.mkdir()
    (dane / "cpi.csv").write_text("miesiac;cpi_rr\n2026-01;3,0\n", encoding="utf-8")
    realistic_pdf(wy / "wyciag.pdf", months)
    return zarzadca.run(date(2026, months, 25), Ustawienia(tmp_path / "u.json"), wyciagi=wy, dane=dane,
                        wyniki=tmp_path / "wyniki", formats_path=tmp_path / "f.json", salt_path=tmp_path / "salt")


def test_jeden_miesiac_pdf_mowi_dlaczego_i_pokazuje_prawdopodobne(tmp_path):
    w = _run(tmp_path, 1)
    assert "3 miesiącach" in w.oplaty_info and w.miesiace == 1
    cats = {o["kontrahent"]: (o["kategoria"], o.get("kandydat")) for o in w.oplaty}
    assert cats["ORANGE POLSKA"] == ("telekom", True)
    assert cats["NETFLIX COM"] == ("subskrypcja", True) and cats["PGE OBROT"] == ("energia", True)


def test_cztery_miesiace_pdf_oplaty_stale(tmp_path):
    w = _run(tmp_path, 4)
    stale = {o["kontrahent"]: o["kategoria"] for o in w.oplaty if not o.get("kandydat")}
    assert stale.get("ORANGE POLSKA") == "telekom" and stale.get("PGE OBROT") == "energia"
    assert stale.get("NETFLIX COM") == "subskrypcja" and "BIEDRONKA WARSZAWA" in stale
    assert w.oplaty_info == ""


def test_uklad_naglowek_i_szczegoly(tmp_path):
    """Uklad jak w wielu bankach: linia operacji (data, identyfikator, rodzaj, kwota, saldo) + linie szczegolow
    (data waluty, Lokalizacja:, rachunek i nazwa odbiorcy), stopka strony i komunikat banku z procentem."""
    c, (W, H) = _canvas(tmp_path / "wyc.pdf")
    y = H - 40
    lines = [
        "Saldo poprzednie -1 000,00",
        "Data operacji Identyfikator operacji TYP OPERACJI Kwota operacji Saldo",
        "02.03.2026 6522MX93920255427 ZAKUP PRZY UŻYCIU KARTY -49,86 -1 049,86",
        "01.03.2026 Karta:425125******1111 Lokalizacja: F.H.U. WEPO WIELICZKA PL Nr ref:",
        "74810316020181496233783",
        "Kwota oryg.: 49,86 PLN",
        "03.03.2026 6624FE97770065092 PRZELEW WYCHODZĄCY -236,83 -1 286,69",
        "03.03.2026 518145811225 JAN TESTOWY UL. PROSTA 1, 00-001 MIASTO 03 1140",
        "1238 2444 8009 7699 5033 T-MOBILE POLSKA S.A. UL.MARYNARSKA 12, 02-674",
        "WARSZAWA Ref. wł. zlec.: 176897518896",
        "Saldo do przeniesienia -1 286,69",
        "Niniejszy dokument jest wydrukiem z systemu informatycznego banku.",
        "01.03.2026 r. Rada Polityki Pieniężnej obniżyła stopę do 4,00%.",
        "05.03.2026 6625KI38900175432 PRZELEW PRZYCH. SYSTEMAT. WPŁYW 1 874,70 588,01",
        "05.03.2026 Świadczenie ZUS 180000C260506TRI/6/018410859",
        "88102056040000010281401010 ZUS ul. Pędzichów 27 31-080 Kraków",
        "06.03.2026 6614MX98530027287 PŁATNOŚĆ WEB - KOD MOBILNY -40,00 548,01",
        "06.03.2026 Tel.:48700000000 Godz.16:57:51 Lokalizacja: https://www.lotto.pl/ Nr ref:",
        "07.03.2026 6629UG92130000048 KREDYT - SPŁATA RATY -172,85 375,16",
        "07.03.2026 KAPITAŁ: 0,00 ODSETKI: 172,85 05102028920000579602796290",
    ]
    c.setFont("F", 8)
    for l in lines:
        c.drawString(30, y, l); y -= 11
    c.save()
    recs = load_pdf(tmp_path / "wyc.pdf", SALT)
    got = [(r.date, r.amount_gr, r.counterparty) for r in recs]
    assert got == [(date(2026, 3, 2), -4986, "WEPO WIELICZKA"), (date(2026, 3, 3), -23683, "TMOBILE POLSKA"),
                   (date(2026, 3, 5), 187470, "ZUS"), (date(2026, 3, 6), -4000, "LOTTO"),
                   (date(2026, 3, 7), -17285, "KREDYT SPLATA RATY")]


def test_podsumowanie_stanu(tmp_path):
    from muz.adapter.pdf_import import read_summary
    c, (W, H) = _canvas(tmp_path / "stan.pdf")
    c.setFont("F", 9)
    y = H - 40
    for l in ["PODSUMOWANIE ŚRODKÓW", "Datawydruku 2026-09-28g.16:15", "Potwierdzeniestanurachunków",
              "Rachunek Saldorachunku Środkidostępne Limitkredytowy",
              "11222233334444555566667777 -5293,90PLN 206,10PLN 5500,00PLN", "KONTOOSOBISTE",
              "Potwierdzeniestanukredytów", "Rachunek Przyznanakwota Pozostałakwotakapitałudospłaty",
              "22333344445555666677778888 16157,34PLN 14571,72PLN", "POŻYCZKAGOTÓWKOWA"]:
        c.drawString(30, y, l); y -= 12
    c.save()
    st = read_summary(tmp_path / "stan.pdf")
    assert st["saldo_gr"] == -529390 and st["dostepne_gr"] == 20610 and st["limit_gr"] == 550000
    assert st["kredyty"] == [{"nazwa": "Pożyczka Gotówkowa", "przyznana_gr": 1615734, "pozostalo_gr": 1457172}]
    assert st["data"] == date(2026, 9, 28)
