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
