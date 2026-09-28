"""Samodopasowanie formatu CSV i wlasny CSV MUZ -- tylko dane syntetyczne."""
from datetime import date

import pytest

import synth
from muz.adapter import load_csv
from muz.adapter.autodetect import ProfileStore, resolve, sniff
from muz.adapter.muz_csv import is_muz_csv, load_muz_csv, write_records, write_template

SALT = b"s" * 32


def _tx():
    return synth.transactions(n_months=14)


def _write(path, lines, enc="utf-8"):
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode(enc))
    return path


def fmt_a(tmp_path):
    """Preambula z nazwa banku, ';', DD.MM.RRRR, cp1250, dwie kolumny dat, kolumna rachunku."""
    lines = ["Bank Przykładowy S.A.;;;;;;;", "Historia rachunku za okres;;;;;;;", ";;;;;;;",
             "Data operacji;Data księgowania;Opis operacji;Tytuł;Nadawca/Odbiorca;Numer konta;Kwota;Saldo po operacji"]
    bal = 5000.0
    for d, amt, cp, title in sorted(_tx(), key=lambda t: t[0]):
        bal += amt
        f = lambda x: f"{x:.2f}".replace(".", ",")
        lines.append(";".join([d.strftime("%d.%m.%Y"), d.strftime("%d.%m.%Y"), "PRZELEW", title, cp,
                               "12 3456 7890 1234 5678 9012 3456", f(amt), f(bal)]))
    return _write(tmp_path / "historia_2025.csv", lines, "cp1250")


def fmt_b(tmp_path):
    """Angielskie naglowki, ',', daty ISO, kolejnosc od najnowszych."""
    lines = ["Date,Description,Amount,Currency,Balance"]
    rows, bal = [], 0.0
    for d, amt, cp, title in sorted(_tx(), key=lambda t: t[0]):
        bal += amt
        rows.append(f'{d.isoformat()},"{cp} {title}",{amt:.2f},PLN,{bal:.2f}')
    return _write(tmp_path / "export.csv", lines + rows[::-1])


def fmt_c(tmp_path):
    """Osobne kolumny obciazen i uznan, bez salda."""
    lines = ["Data;Kontrahent;Szczegóły;Obciążenia;Uznania"]
    for d, amt, cp, title in sorted(_tx(), key=lambda t: t[0]):
        v = f"{abs(amt):.2f}".replace(".", ",")
        lines.append(";".join([d.strftime("%Y-%m-%d"), cp, title + " opis dłuższy", v if amt < 0 else "", v if amt > 0 else ""]))
    return _write(tmp_path / "wyciag_c.csv", lines)


def fmt_d(tmp_path):
    """Nazwy kolumn bez znaczenia -- tylko zawartosc."""
    lines = ["Kol1;Kol2;Kol3;Kol4;Kol5"]
    bal = 1000.0
    for d, amt, cp, title in sorted(_tx(), key=lambda t: t[0]):
        bal += amt
        f = lambda x: f"{x:.2f}".replace(".", ",")
        lines.append(";".join([f(bal), cp, d.strftime("%d-%m-%Y"), f(amt), f"{title} — płatność za usługę numer {d.month}"]))
    return _write(tmp_path / "x.csv", lines)


def _check(path, **expect):
    det = sniff(path)
    for k, v in expect.items():
        assert det.mapping.get(k) == v, (k, det.mapping, det.reasons)
    recs = load_csv(path, det.mapping, SALT)
    tx = _tx()
    assert len(recs) == len(tx)
    assert sorted(r.amount_gr for r in recs) == sorted(round(a * 100) for _, a, _, _ in tx)
    return det, recs


def test_format_a_preambula_i_nazwa(tmp_path):
    det, recs = _check(fmt_a(tmp_path), date="Data operacji", amount="Kwota", balance="Saldo po operacji",
                       counterparty="Nadawca/Odbiorca", description="Tytuł")
    assert det.suggested_name == "Bank Przykładowy"
    assert all(r.balance_gr is not None for r in recs)


def test_format_b_angielski_odwrocona_kolejnosc(tmp_path):
    _check(fmt_b(tmp_path), date="Date", amount="Amount", balance="Balance", currency="Currency", description="Description")


def test_format_c_obciazenia_uznania(tmp_path):
    det, recs = _check(fmt_c(tmp_path), debit="Obciążenia", credit="Uznania", counterparty="Kontrahent")
    assert "amount" not in det.mapping
    assert any(r.amount_gr > 0 for r in recs) and any(r.amount_gr < 0 for r in recs)


def test_format_d_tylko_zawartosc(tmp_path):
    _check(fmt_d(tmp_path), date="Kol3", amount="Kol4", balance="Kol1", counterparty="Kol2", description="Kol5")


def test_profil_uczy_sie_po_pierwszym_imporcie(tmp_path):
    store = ProfileStore(tmp_path / "formaty.json")
    p = fmt_a(tmp_path)
    m1, i1 = resolve(p, store)
    assert i1["new"] and i1["profile"] == "Bank Przykładowy"
    p2 = tmp_path / "historia_2026.csv"
    p2.write_bytes(p.read_bytes())
    m2, i2 = resolve(p2, ProfileStore(tmp_path / "formaty.json"))
    assert not i2["new"] and i2["profile"] == "Bank Przykładowy" and m2 == m1
    s = ProfileStore(tmp_path / "formaty.json")
    assert s.data[i2["fingerprint"]]["files"] == ["historia_2025.csv", "historia_2026.csv"]
    s.rename("Bank Przykładowy", "Moje konto")
    assert ProfileStore(tmp_path / "formaty.json").get(i2["fingerprint"])["name"] == "Moje konto"


def test_inny_format_ta_sama_nazwa_dostaje_numer(tmp_path):
    store = ProfileStore(tmp_path / "formaty.json")
    resolve(fmt_a(tmp_path), store)
    other = tmp_path / "inny.csv"
    other.write_text(fmt_a(tmp_path).read_text(encoding="cp1250").replace("Numer konta", "Rachunek"), encoding="cp1250")
    _, info = resolve(other, store)
    assert info["new"] and info["profile"] == "Bank Przykładowy (2)"


def test_csv_muz_eksport_i_powrot(tmp_path):
    recs = load_csv(fmt_a(tmp_path), sniff(fmt_a(tmp_path)).mapping, SALT)
    out = write_records(recs, tmp_path / "t.csv", {"ORANGE POLSKA": "telekom"})
    assert is_muz_csv(out)
    back, cats = load_muz_csv(out, SALT)
    assert [(r.date, r.amount_gr, r.counterparty, r.balance_gr) for r in sorted(recs, key=lambda r: (r.date, r.raw_hash))] == \
           [(r.date, r.amount_gr, r.counterparty, r.balance_gr) for r in back] or \
           sorted((r.date, r.amount_gr, r.counterparty) for r in recs) == sorted((r.date, r.amount_gr, r.counterparty) for r in back)
    assert cats.get("ORANGE POLSKA") == "telekom"


def test_szablon_i_reczne_wpisy(tmp_path):
    p = write_template(tmp_path / "moje.csv")
    with pytest.raises(FileExistsError):
        write_template(p)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("2026-09-03;-45,50;PLN;Targ;warzywa;jedzenie;;;\n")
        fh.write("03.09.2026;-120;;Mechanik;wymiana oleju;auto;;;\n")
    recs, cats = load_muz_csv(p, SALT)
    assert [r.amount_gr for r in recs] == [-4550, -12000]
    assert recs[1].date == date(2026, 9, 3) and recs[1].currency == "PLN"
    assert cats == {"TARG": "jedzenie", "MECHANIK": "auto"}
