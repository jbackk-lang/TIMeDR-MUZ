"""Sprawy zarzadcy poza podwyzkami: dane syntetyczne."""
from datetime import date

from muz import sprawy
from muz.adapter.csv_import import LSFRecord, Stream

T = date(2026, 9, 28)


def rec(d, gr, cp, desc=""):
    return LSFRecord(d, gr, "PLN", cp, desc or cp, "", None, "t", f"{d}{gr}{cp}{desc}")


def stream(cp, cat, amounts):
    return Stream(cp, cp, [f"2026-{m:02d}" for m in range(1, len(amounts) + 1)], amounts, "monthly",
                  contract={"category": cat})


def test_kilka_umow_tego_samego_rodzaju():
    ss = [stream("ORANGE POLSKA", "telekom", [25000] * 5), stream("TMOBILE POLSKA", "telekom", [23600] * 5),
          stream("UPC", "media", [6300] * 5), stream("PGE", "energia", [20000] * 5), stream("TAURON", "energia", [9000] * 5)]
    cards = sprawy.duplicates(ss, T)
    assert len(cards) == 1                      # energia (prad + gaz) nie jest dublem
    k = cards[0]
    assert "3 umowy" in k["title"] and k["yearly_gr"] == (23600 + 6300) * 12


def test_koszt_dlugu_i_karencja():
    rs = []
    for m in range(1, 10):
        rs.append(rec(date(2026, m, 8), -17285, "KREDYT SPLATA RATY",
                      "KREDYT - SPŁATA RATY KAPITAŁ: 0,00 ODSETKI: 172,85 ODSETKI SKAPIT.: 0,00 ODSETKI KARNE: 0,00"))
        rs.append(rec(date(2026, m, 24), -6606, "KAPITALIZACJA ODSETEK OBCIAZENIE", "KAPITALIZACJA ODSETEK-OBCIĄŻENIE"))
        rs.append(rec(date(2026, m, 12), -720, "PIEKARNIA ZLOTY KLOS", "ZAKUP PRZY UŻYCIU KARTY PIEKARNIA"))
    cards = sprawy.debt_cost(rs, T, [{"nazwa": "debet w koncie", "kwota_zl": 5000, "oprocentowanie_proc": 14.5}])
    k = cards[0]
    assert "odsetki w ratach kredytu: 1 555,65 zł" in k["body_md"] and "odsetki od debetu: 594,54 zł" in k["body_md"]
    assert "karne" not in k["body_md"].split("**Co zrobić")[0]           # piekarnia to nie odsetki karne
    assert "karencja" in k["body_md"] and "14,5%" in k["body_md"]


def test_oplata_za_konto_i_odroczone():
    rs = [rec(date(2026, m, 24), -1790, "OPLATA ZA PROWADZENIE", "OPŁATA ZA PROWADZENIE RACHUNKU") for m in range(1, 7)]
    rs += [rec(date(2026, m, 3), -50000, "PAYPO", "PŁATNOŚĆ WEB Lokalizacja: https://paypo.pl") for m in range(4, 9)]
    assert sprawy.account_fee(rs, T)[0]["yearly_gr"] == 21480
    b = sprawy.bnpl(rs, T)[0]
    assert b["action"] == "bnpl" and "Płatności odroczone" in b["title"]
