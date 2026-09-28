"""Sprawy zarzadcy poza podwyzkami cen: kilka umow tego samego rodzaju, koszt dlugu, oplata za konto,
zakupy z odroczona platnoscia. Wszystko liczone z wyciagow, bez pytania uzytkownika.

To sa jawne reguly zarzadcy (nie przeszly jeszcze testu pre-rejestrowanego, jak polityka podwyzek v0.3):
kazda karta mowi, z czego wynika kwota, a oszczednosc jest gorna granica ("jesli zrezygnujesz").
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import date, timedelta

from .adapter.csv_import import _strip_accents, parse_amount_gr
from .decisions import zl

GROUPS = {"telekom": "łączność (telefon, internet, TV)", "media": "łączność (telefon, internet, TV)",
          "subskrypcja": "subskrypcje", "ubezpieczenie": "ubezpieczenia"}
INTEREST = re.compile(r"\bODSETK|\bODS\b|KAPITALIZACJA|\bKAPIT\b|\bUJEMN|\bNIEAUT")
PENALTY = re.compile(r"\bODSETEK KARNYCH|\bODSETKI KARNE\b|\bODS\.? KARN")
FEES = re.compile(r"PROWIZJA|OPLATA ZA (?!PROWADZENIE)")
ACCOUNT_FEE = re.compile(r"OPLATA ZA PROWADZENIE|OPLATA ZA KONTO|OPLATA MIESIECZNA ZA")
BNPL = re.compile(r"PAYPO|KLARNA|TWISTO|PLACE POZNIEJ|ODROCZON|PAY LATER")
LOAN_INTEREST = re.compile(r"\bODSETKI:\s*(\d[\d \u00a0]*,\d{2})")
LOAN_PENALTY = re.compile(r"\bODSETKI KARNE:\s*(\d[\d \u00a0]*,\d{2})")


def _norm(r) -> str:
    return _strip_accents(f"{r.counterparty} {r.description}").upper()


def _window(records, today: date, days: int = 365):
    start = today - timedelta(days=days)
    rs = [r for r in records if r.date >= start]
    if not rs:
        return [], 1.0
    months = max(1.0, ((max(r.date for r in rs) - min(r.date for r in rs)).days + 1) / 30.44)
    return rs, months


def _card(kind, key, title, body, yearly_gr, today, days=14):
    return {"id": f"{kind}|{key}", "action": kind, "counterparty": key, "title": title, "body_md": body,
            "yearly_gr": int(yearly_gr), "save_cancel_gr": int(yearly_gr), "deadline": today + timedelta(days=days),
            "now_gr": None, "target_gr": None, "max_ok_gr": None}


def duplicates(monthly_streams, today: date) -> list[dict]:
    """Kilka umow tego samego rodzaju (np. trzech operatorow). Oszczednosc: suma bez najdrozszej umowy."""
    groups = defaultdict(list)
    for s in monthly_streams:
        cat = (s.contract or {}).get("category")
        if cat in GROUPS:
            recent = [a for a in s.amounts_gr[-4:] if a > 0]
            if recent:
                groups[GROUPS[cat]].append((s.counterparty, int(statistics.median(recent[-3:]))))
    out = []
    for name, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda x: -x[1])
        total = sum(a for _, a in items)
        who = ", ".join(n for n, _ in items)
        save = (total - items[0][1]) * 12
        body = "\n".join(
            [f"**Ile:** {zl(total)} miesięcznie, {zl(total * 12)} rocznie:"] + [f"- {n}: {zl(a)}" for n, a in items] +
            ["", "**Sprawdź (5 minut):** czyje to numery i co to za usługi (telefon, internet, telewizja); kiedy kończy się "
                 "każda umowa (umowa albo aplikacja operatora).",
             "", "**Co zrobić:**",
             f"1. Zadzwoń do operatora, u którego masz najwięcej, i poproś o **jedną ofertę na wszystko** — cel: wyraźnie "
             f"mniej niż {zl(total)} miesięcznie.",
             "2. Tego, czego nie używasz, nie przedłużaj — wypowiedz przed końcem umowy; numer można przenieść bez opłat.",
             "3. Po zmianie kliknij „✓ Załatwione” — MUZ sprawdzi na kolejnych wyciągach, czy płatności zniknęły.",
             "", f"_Do odzyskania do {zl(save)} rocznie, jeśli zostanie tylko najdroższa umowa — faktycznie zależy od tego, "
                 f"czego potrzebujesz._"])
        out.append(_card("zduplikowane", name, f"Masz {len(items)} umowy — {name} ({who}): {zl(total)} miesięcznie",
                         body, save, today))
    return out


def debt_cost(records, today: date, debts: list[dict]) -> list[dict]:
    """Odsetki (debet, karne, kredyt) i prowizje z ostatnich 12 miesiecy, w przeliczeniu na rok."""
    rs, months = _window(records, today)
    parts = defaultdict(int)
    interest_only = False
    for r in rs:
        if r.amount_gr >= 0:
            continue
        t = _norm(r)
        m = LOAN_INTEREST.search(t)
        if m and ("KREDYT" in t or "RATA" in t or "RATY" in t):
            interest_only |= bool(re.search(r"\bKAPITAL:\s*0,00", t))
            for rx, name in ((LOAN_INTEREST, "odsetki w ratach kredytu"), (LOAN_PENALTY, "odsetki karne")):
                mm = rx.search(t)
                if mm:
                    try:
                        parts[name] += parse_amount_gr(re.sub(r"\s", "", mm.group(1)))
                    except ValueError:
                        pass
        elif m is None and ("KREDYT" in t and "RATY" in t):
            continue                                   # rata bez rozbicia na kapital i odsetki
        elif PENALTY.search(t):
            parts["odsetki karne"] += -r.amount_gr
        elif INTEREST.search(t):
            parts["odsetki od debetu"] += -r.amount_gr
        elif FEES.search(t) and not ACCOUNT_FEE.search(t):
            parts["prowizje i opłaty bankowe"] += -r.amount_gr
    total = sum(parts.values())
    yearly = total / months * 12
    if yearly < 100 * 100:
        return []
    rate_txt = ""
    top = max((d for d in debts if float(d.get("oprocentowanie_proc") or 0) > 0),
              key=lambda d: float(d["oprocentowanie_proc"]), default=None)
    if top:
        rate_txt = f" Najdroższy: {top['nazwa']} ({str(top['oprocentowanie_proc']).replace('.', ',')}%)."
    body = "\n".join(
        [f"**Ile:** {zl(total)} w ciągu {months:.0f} mies., czyli ok. **{zl(yearly)} rocznie** — to pieniądze, które nie "
         f"spłacają długu.{rate_txt}"] + [f"- {k}: {zl(v)}" for k, v in sorted(parts.items(), key=lambda x: -x[1]) if v > 0] +
        ["", "**Co zrobić:**",
         "1. Każda złotówka ponad przydział (zakładka „Co teraz”) idzie na **najdroższy dług** — MUZ wskazuje go w przydziale.",
         "2. Zapytaj w banku o **rozłożenie debetu na raty** albo tańszy kredyt konsolidacyjny — tylko jeśli RRSO jest "
         "niższe niż oprocentowanie debetu i bez prowizji, która zje zysk.",
         "3. Nie przekraczaj limitu — od przekroczenia bank liczy odsetki karne.",
         "4. Raty, w których płacisz same odsetki (kapitał 0,00), nie zmniejszają długu — zapytaj bank, do kiedy trwa "
         "karencja i ile wyniesie rata potem." if interest_only else ""])
    return [_card("koszt_dlugu", "odsetki", f"Dług kosztuje ok. {zl(yearly)} rocznie odsetek i opłat", body.rstrip(),
                  yearly, today, days=30)]


def account_fee(records, today: date) -> list[dict]:
    rs, months = _window(records, today)
    fees = [r for r in rs if r.amount_gr < 0 and ACCOUNT_FEE.search(_norm(r))]
    if len({(r.date.year, r.date.month) for r in fees}) < 2:
        return []
    monthly = int(statistics.median(-r.amount_gr for r in fees))
    yearly = monthly * 12
    body = "\n".join([f"**Ile:** {zl(monthly)} miesięcznie = **{zl(yearly)} rocznie** za samo prowadzenie konta.", "",
                      "**Co zrobić:**",
                      "1. Zapytaj bank (infolinia albo oddział), **jaki warunek zwalnia z opłaty** (np. wpływ, liczba "
                      "płatności kartą lub BLIK) i czy możesz przejść na wersję konta bez opłat.",
                      "2. Jeśli warunku nie da się spełnić — porównaj konta bez opłat w innych bankach (przeniesienie "
                      "zleceń i wpływu ZUS robi nowy bank).",
                      "Uwaga: przy debecie zamknięcie konta wymaga spłaty limitu — najpierw pytaj o zmianę w tym samym banku."])
    return [_card("oplata_konto", "konto", f"Opłata za konto: {zl(yearly)} rocznie — do zwolnienia albo zmiany", body,
                  yearly, today)]


def bnpl(records, today: date) -> list[dict]:
    rs, months = _window(records, today)
    by_m = defaultdict(int)
    for r in rs:
        if r.amount_gr < 0 and BNPL.search(_norm(r)):
            by_m[f"{r.date.year:04d}-{r.date.month:02d}"] += -r.amount_gr
    if len(by_m) < 2:
        return []
    avg = sum(by_m.values()) / months
    peak_m = max(by_m, key=by_m.get)
    body = "\n".join([f"**Ile:** średnio {zl(avg)} miesięcznie płatności odroczonych (PayPo, Klarna, „płacę później”), "
                      f"najwięcej {zl(by_m[peak_m])} w {peak_m}.", "",
                      "Zakup „na później” nie znika z budżetu — wraca jako płatność w następnym cyklu, często z opłatą "
                      "za rozłożenie lub za opóźnienie. Przy debecie oznacza to pożyczanie na pożyczkę.", "",
                      "**Co zrobić:**",
                      "1. Spłać to, co już jest, zgodnie z terminami (MUZ rezerwuje te płatności w przydziale).",
                      "2. Na czas wychodzenia z debetu **nie otwieraj nowych** płatności odroczonych — w aplikacji PayPo/"
                      "Klarna można wyłączyć lub obniżyć limit.",
                      "3. Kliknij „✓ Załatwione”, gdy limit będzie wyłączony — MUZ sprawdzi na wyciągach, czy nowych nie ma."])
    return [_card("bnpl", "odroczone", f"Płatności odroczone: średnio {zl(avg)} miesięcznie", body, 0, today)]


def extra_cards(ctx: dict, today: date, debts: list[dict]) -> list[dict]:
    recs = ctx["records"]
    return duplicates(ctx["monthly"], today) + debt_cost(recs, today, debts) + account_fee(recs, today) + bnpl(recs, today)
