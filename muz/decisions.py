"""Wyrazne decyzje budzetowe: co zrobic, ile i do kiedy -- takze to, co trzeba zrobic samemu (rozmowa o cenie).

Dwie czesci:
1. Przydzial do nastepnej wyplaty -- regula z badania MUZ-SIM v0.1 (docs/BADANIA.md): pieniadze dzieli sie
   w chwili wplywu; najpierw rezerwa na oplaty stale, ktore zejda przed nastepna wyplata (wedlug ich kalendarza),
   potem fundusz na wydatki nieregularne (80. percentyl sum 90-dniowych z historii), potem zycie. Przy dlugu
   albo braku zapasu -- tryb wychodzenia: 80% zwyklych wydatkow (w badaniu ponizej 75% gospodarstwo sie
   "lamie"), nadwyzka: fundusz -> bufor 1 miesiac oplat -> nadplata najdrozszego dlugu.
2. Decyzje o umowach -- ta sama polityka budzetowa i weryfikacja co w etapie 1 (prereg/muz_decision_v0.3.json),
   zamieniona na karte dzialania: cel ceny, gorna granica zgody, plan B, termin, co powiedziec, co zapisac.

MUZ niczego nie wykonuje sam: to lista dla czlowieka. Pisma i formularze ida przez bramke (propose/approve).
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from .adapter.csv_import import LSFRecord, Stream


def zl(gr: float | int | None) -> str:
    if gr is None:
        return "?"
    s = f"{abs(gr) / 100:,.2f}".replace(",", " ").replace(".", ",")
    return ("-" if gr < 0 else "") + s + " zł"


# ---------------------------------------------------------------------------
# 1. Przydzial do nastepnej wyplaty
# ---------------------------------------------------------------------------

def paydays(records: list[LSFRecord]) -> list[date]:
    """Wplywy >= 50% najwiekszego wplywu z poprzednich 90 dni, co najmniej 8 dni po poprzednim."""
    cred = sorted((r for r in records if r.amount_gr > 0 and r.currency == "PLN"), key=lambda r: r.date)
    out: list[date] = []
    for i, r in enumerate(cred):
        past = [c.amount_gr for c in cred[:i] if (r.date - c.date).days <= 90]
        if past and r.amount_gr < 0.5 * max(past):
            continue
        if out and (r.date - out[-1]).days < 8:
            continue
        out.append(r.date)
    return out


def next_payday(pd: list[date], today: date) -> tuple[date, int]:
    iv = [(b - a).days for a, b in zip(pd[-7:], pd[-6:])]
    step = int(statistics.median(iv)) if iv else 30
    nxt = (pd[-1] if pd else today) + timedelta(days=step)
    while nxt <= today:
        nxt += timedelta(days=step)
    return nxt, step


@dataclass
class Obligation:
    name: str
    day: int
    amount_gr: int
    category: str = ""


def obligations(streams: list[Stream], records: list[LSFRecord], categories: dict[str, str]) -> list[Obligation]:
    by_cp: dict[str, list[LSFRecord]] = {}
    for r in records:
        if r.amount_gr < 0:
            by_cp.setdefault(r.counterparty, []).append(r)
    out = []
    for s in streams:
        if s.cadence != "monthly":
            continue
        recs = sorted(by_cp.get(s.counterparty, []), key=lambda r: r.date)[-6:]
        if not recs:
            continue
        last = next((a for a in reversed(s.amounts_gr) if a > 0), 0)
        cat = (s.contract or {}).get("category") or categories.get(s.counterparty, "")
        out.append(Obligation(s.counterparty, int(statistics.median(r.date.day for r in recs)), last, cat))
    return out


def due_dates(ob: Obligation, start: date, end: date) -> list[date]:
    out, y, m = [], start.year, start.month
    while date(y, m, 1) <= end:
        dim = (date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1)).day
        d = date(y, m, min(ob.day, dim))
        if start <= d < end:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _daily(records, start: date, end: date, pick) -> np.ndarray:
    v = np.zeros((end - start).days + 1)
    for r in records:
        if start <= r.date <= end and pick(r):
            v[(r.date - start).days] += -r.amount_gr
    return v


@dataclass
class CyclePlan:
    today: date
    next_payday: date
    days: int
    balance_gr: int | None
    balance_date: date | None
    due: list[tuple[date, str, int]]
    reserve_gr: int
    fund_target_gr: int
    buffer_target_gr: int
    savings_gr: int
    need_day_gr: int
    mode: str                      # "normalny" | "wychodzenie z dlugu" | "brak zapasu"
    allowance_gr: int = 0
    to_fund_gr: int = 0
    to_buffer_gr: int = 0
    to_debt_gr: int = 0
    left_gr: int = 0
    debt_target: str = ""
    shortfall_gr: int = 0
    notes: list[str] = field(default_factory=list)


def cycle_plan(records: list[LSFRecord], streams: list[Stream], *, today: date, profile: dict | None = None,
               categories: dict[str, str] | None = None) -> CyclePlan:
    profile = profile or {}
    cats = categories or {}
    pd = paydays(records)
    nxt, step = next_payday(pd, today)
    days = (nxt - today).days
    obls = obligations(streams, records, cats)
    debts = [d for d in profile.get("dlugi", []) if float(d.get("kwota_zl", 0)) > 0]
    for d in debts:
        if d.get("rata_min_zl") and d.get("dzien_raty"):
            obls.append(Obligation(f"rata: {d['nazwa']}", int(d["dzien_raty"]), int(round(float(d["rata_min_zl"]) * 100)), "dlug"))
    horizon = nxt + timedelta(days=3)
    due = sorted((dd, o.name, o.amount_gr) for o in obls for dd in due_dates(o, today, horizon))
    reserve = sum(a for _, _, a in due)

    # historia: oplaty stale (strumienie miesieczne), nieregularne duze, codzienne
    last = max((r.date for r in records), default=today)
    first = min((r.date for r in records), default=today)
    monthly_cp = {o.name for o in obls}
    inc = [r.amount_gr for r in records if r.amount_gr > 0 and (last - r.date).days <= 365]
    income_month = sum(inc) / max(1, min(12, ((last - first).days + 1) / 30.44))
    big = 0.10 * income_month
    irr = lambda r: r.amount_gr < 0 and r.counterparty not in monthly_cp and -r.amount_gr >= big
    daily_irr = _daily(records, first, last, irr)
    cs = np.concatenate([[0.0], np.cumsum(daily_irr)])
    win = cs[90:] - cs[:-90] if len(daily_irr) > 90 else np.array([daily_irr.sum()])
    fund_target = int(max(np.percentile(win, 80) if len(win) else 0.0, daily_irr.mean() * 90 if len(daily_irr) else 0.0))
    everyday = lambda r: r.amount_gr < 0 and r.counterparty not in monthly_cp and -r.amount_gr < big
    d90 = _daily(records, max(first, last - timedelta(days=89)), last, everyday)
    need_day = int(d90.mean()) if len(d90) else 0
    buffer_target = sum(o.amount_gr for o in obls)

    with_bal = [r for r in records if r.balance_gr is not None]
    bal, bal_date = None, None
    if with_bal:
        rb = max(with_bal, key=lambda r: r.date)
        bal, bal_date = rb.balance_gr, rb.date
    if profile.get("saldo_zl") is not None:
        bal, bal_date = int(round(float(profile["saldo_zl"]) * 100)), today
    savings = int(round(float(profile.get("oszczednosci_zl", 0)) * 100))

    fund_gap = max(0, fund_target - savings)
    buf_gap = max(0, buffer_target - max(0, savings - fund_target))
    mode = "wychodzenie z długu" if debts else ("brak zapasu" if fund_gap + buf_gap > 0 else "normalny")
    plan = CyclePlan(today, nxt, days, bal, bal_date, due, reserve, fund_target, buffer_target, savings, need_day, mode)
    if bal_date and (today - bal_date).days > 3:
        plan.notes.append(f"saldo z wyciągu z {bal_date.isoformat()} ({(today - bal_date).days} dni temu) — "
                          f"wpisz aktualne saldo w profilu (saldo_zl), żeby przydział był dokładny")
    if bal is None:
        plan.notes.append("wyciąg nie podaje salda — wpisz saldo w profilu (saldo_zl); poniżej tylko rezerwa i potrzeby")
        return plan
    need = need_day * days
    target = int(0.80 * need) if mode != "normalny" else need
    free = bal - reserve
    if free >= target:
        plan.allowance_gr = target
    else:
        plan.allowance_gr = max(free, 0)
        plan.shortfall_gr = int(0.75 * need) - free if free < 0.75 * need else 0
    surplus = free - plan.allowance_gr
    if surplus > 0:
        plan.to_fund_gr = min(surplus, fund_gap); surplus -= plan.to_fund_gr
        plan.to_buffer_gr = min(surplus, buf_gap); surplus -= plan.to_buffer_gr
        if debts and surplus > 0:
            top = max(debts, key=lambda d: float(d.get("oprocentowanie_proc", 0)))
            plan.to_debt_gr = min(surplus, int(round(float(top["kwota_zl"]) * 100)))
            plan.debt_target = f"{top['nazwa']} ({top.get('oprocentowanie_proc', '?')}%)"
            surplus -= plan.to_debt_gr
        plan.left_gr = max(0, surplus)
    return plan


def render_cycle(p: CyclePlan) -> str:
    L = [f"## Do następnej wypłaty: ok. {p.next_payday.strftime('%d.%m')} ({p.days} dni)", ""]
    L.append(f"Tryb: **{p.mode}**." + (" Wydatki bieżące 80% zwykłych — w badaniu MUZ-SIM niżej niż 75% gospodarstwa się łamały." if p.mode != "normalny" else ""))
    L.append("")
    if p.balance_gr is not None:
        L.append(f"Saldo: {zl(p.balance_gr)} (stan na {p.balance_date.isoformat()}).")
    L.append("")
    L.append(f"1. **Zarezerwuj {zl(p.reserve_gr)} na opłaty**, które zejdą przed wypłatą:")
    for d, name, a in p.due:
        L.append(f"   - {d.strftime('%d.%m')} {name}: {zl(a)}")
    if not p.due:
        L.append("   - brak opłat stałych w tym okresie")
    if p.balance_gr is None:
        L.append(f"2. Na życie potrzeba zwykle {zl(p.need_day_gr)} dziennie. Resztę policzę po wpisaniu salda.")
    else:
        if p.need_day_gr <= 0:
            L.append("2. **Na życie:** w historii nie ma wydatków codziennych (karta, sklepy) — dopisz gotówkę "
                     "w CSV MUZ (`python -m muz szablon`), inaczej przydział na życie jest nieznany.")
        else:
            L.append(f"2. **Na życie: {zl(p.allowance_gr)}** = {zl(p.allowance_gr / max(p.days, 1))} dziennie, "
                     f"{zl(7 * p.allowance_gr / max(p.days, 1))} na tydzień (zwykle wydajesz {zl(p.need_day_gr)} dziennie).")
        n = 3
        if p.to_fund_gr:
            L.append(f"{n}. **Odłóż {zl(p.to_fund_gr)} na fundusz wydatków nieregularnych** (cel {zl(p.fund_target_gr)}, "
                     f"odłożone {zl(p.savings_gr)})."); n += 1
        if p.to_buffer_gr:
            L.append(f"{n}. **Odłóż {zl(p.to_buffer_gr)} do bufora** (cel: miesiąc opłat, {zl(p.buffer_target_gr)})."); n += 1
        if p.to_debt_gr:
            L.append(f"{n}. **Nadpłać {zl(p.to_debt_gr)}: {p.debt_target}** — najdroższy dług."); n += 1
        if p.left_gr:
            L.append(f"{n}. Zostaje {zl(p.left_gr)} — zapas ponad plan (oszczędności albo cel, który wybierzesz)."); n += 1
        if p.shortfall_gr > 0:
            L.append(f"{n}. **Brakuje {zl(p.shortfall_gr)} do minimum na życie.** Przesuń termin płatności, która może "
                     f"poczekać, albo użyj oszczędności — nie tnij bieżących wydatków poniżej 75%.")
    for note in p.notes:
        L.append(f"\n_Uwaga: {note}._")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# 2. Karty dzialania dla umow
# ---------------------------------------------------------------------------

def contract_card(stream: Stream, frames, proposal: dict, cpi_yoy: float | None, today: date) -> dict:
    from .mini_ai.policy import amount_12m_ago
    from .pipeline import _change_basis
    now = frames[-1].amount_gr
    before = amount_12m_ago(frames) or (frames[-2].amount_gr if len(frames) >= 2 else now)
    month, _, rel = _change_basis(frames)
    cpi = cpi_yoy or 0.0
    ok = int(round(before * (1 + cpi)))
    c = stream.contract or {}
    yearly = max(0, now - ok) * 12
    paid = sum(1 for a in stream.amounts_gr if a > 0)
    deadline, why_deadline = today + timedelta(days=14), "w ciągu 2 tygodni"
    if c.get("end_date"):
        end = date.fromisoformat(c["end_date"])
        n = int(c.get("notice_period_months") or 0)
        last = end - timedelta(days=30 * n)
        if last > today:
            deadline = min(deadline, last)
            why_deadline = (f"{'w ciągu 2 tygodni' if deadline < last else 'ostatni dzień'}; ostatni termin wypowiedzenia "
                            f"{last.isoformat()} (umowa do {end.isoformat()}, wypowiedzenie {n} mies.)")
    if c.get("promo_end"):
        why_deadline += f"; promocja kończy się {c['promo_end']}"
    return {"counterparty": stream.counterparty, "action": proposal["action"], "now_gr": now, "before_gr": before,
            "change_month": month, "rel": rel, "cpi": cpi_yoy, "target_gr": before, "max_ok_gr": ok, "yearly_gr": yearly,
            "save_cancel_gr": now * 12, "since": stream.months[0], "n_paid": paid, "deadline": deadline,
            "why_deadline": why_deadline, "category": c.get("category", ""), "has_contract": bool(c),
            "notice": c.get("notice_period_months")}


def render_card(k: dict) -> str:
    who, a = k["counterparty"], k["action"]
    pct = "" if k["rel"] is None else f"{k['rel'] * 100:+.1f}%".replace(".", ",")
    cpi = "brak danych" if k["cpi"] is None else f"{k['cpi'] * 100:.1f}%".replace(".", ",")
    L = []
    if a == "negocjowac":
        L += [f"### Negocjuj cenę: {who} — cel {zl(k['target_gr'])}, zgoda najwyżej do {zl(k['max_ok_gr'])}", "",
              f"**Dlaczego:** od {k['change_month']} płacisz {zl(k['now_gr'])} zamiast {zl(k['before_gr'])} ({pct}), "
              f"inflacja r/r {cpi}. Ponad inflację nadpłacasz ok. **{zl(k['yearly_gr'])} rocznie**.",
              f"**Termin:** {k['deadline'].isoformat()} — {k['why_deadline']}.",
              f"**Cel:** {zl(k['target_gr'])} (poprzednia cena). **Górna granica:** {zl(k['max_ok_gr'])} "
              f"(poprzednia + inflacja). Powyżej — plan B.",
              "**Plan B:** " + ("zmiana dostawcy albo planu" if k["category"] in ("telekom", "energia", "internet", "tv")
                                 else "wypowiedzenie umowy" if k["category"] == "subskrypcja" else "zmiana dostawcy albo wypowiedzenie")
              + (f" — okres wypowiedzenia: {k['notice']} mies." if k["notice"] else " — sprawdź okres wypowiedzenia w umowie."),
              "", "**Co powiedzieć** (dział utrzymania klienta / retencji):",
              f"1. „Od {k['change_month']} opłata wzrosła z {zl(k['before_gr'])} do {zl(k['now_gr'])}, to {pct}, "
              f"przy inflacji {cpi}. Proszę o przywrócenie poprzedniej ceny.”",
              f"2. „Jestem klientem co najmniej od {k['since']} i płacę terminowo ({k['n_paid']} płatności).”",
              "3. „Mam ofertę innej firmy: ____.” — **przed rozmową wpisz 1–2 konkretne oferty** (nazwa, cena, warunki).",
              "4. Przy odmowie: „Jaki jest termin i koszt wypowiedzenia?” — to zwykle przełącza na ofertę utrzymaniową.",
              "", "**Nie zgadzaj się na:** dłuższe zobowiązanie bez obniżki, dodatkowe usługi w cenie „rabatu”, "
              "obniżkę tylko na 3 miesiące bez zapisu, co potem.",
              "**Zapisz:** data, imię rozmówcy, nowa cena i od kiedy; poproś o potwierdzenie mailem albo w aplikacji.",
              "**Zamiast rozmowy — pismo:** `python -m muz propose …` przygotuje „prośbę o obniżkę” do Twojego zatwierdzenia."]
    elif a == "anulowac":
        L += [f"### Wypowiedz: {who} — oszczędność {zl(k['save_cancel_gr'])} rocznie", "",
              f"**Dlaczego:** {zl(k['before_gr'])} → {zl(k['now_gr'])} ({pct}, inflacja {cpi}), negocjacje już były.",
              f"**Termin:** {k['deadline'].isoformat()} — {k['why_deadline']}.",
              "**Jak:** pismo wypowiedzenia z szablonu (`python -m muz propose`, zatwierdzasz Ty); zachowaj potwierdzenie nadania."]
    elif a == "zmienic":
        L += [f"### Zmień plan lub dostawcę: {who} — szukaj ceny ≤ {zl(k['max_ok_gr'])}", "",
              f"**Dlaczego:** {zl(k['before_gr'])} → {zl(k['now_gr'])} ({pct}, inflacja {cpi}), negocjacje już były. "
              f"Różnica ponad inflację: {zl(k['yearly_gr'])} rocznie.",
              f"**Termin:** {k['deadline'].isoformat()} — {k['why_deadline']}.",
              "**Jak:** porównaj 2–3 oferty o tym samym zakresie; nowa umowa dopiero po sprawdzeniu terminu wypowiedzenia starej."]
    for u in k.get("uwagi", []):
        if "dane sprzed" in u:
            L.append(f"\n_Uwaga: {u} — sprawdź na ostatnim rachunku, czy kwota się nie zmieniła; pismo przez bramkę wymaga świeżego wyciągu._")
        else:
            L.append(f"\n_Uwaga: {u}._")
    if not k["has_contract"]:
        L.append("\n_Brak potwierdzonej umowy w umowy.json — dopisz kategorię, okres wypowiedzenia i koniec umowy, "
                 "wtedy MUZ poda dokładny termin i plan B._")
    return "\n".join(L) + "\n"


def contract_decisions(ctx: dict, *, dec, dec_sha, today: date) -> list[dict]:
    from .pipeline import run_stream
    cards = []
    for s in ctx["monthly"]:
        frames = ctx["frames"][s.stream_id]
        r = run_stream(s, frames, ctx=ctx, dec=dec, dec_sha=dec_sha, profile={}, today=today)
        p, cl = r.get("proposal"), r.get("claim") or {}
        if not p or p["action"] == "zostawic":
            continue
        reasons = [x for x in cl.get("reasons", []) if x]
        # do bramki (pisma) trafia tylko SUPPORTED; na liste dla czlowieka -- takze gdy brakuje jedynie swiezosci
        # danych albo pol umowy (z ostrzezeniem). REJECTED i brak rekordow zrodlowych -- nie.
        soft = cl.get("verdict") == "INCONCLUSIVE" and not any("brak rekordow" in x for x in reasons)
        if cl.get("verdict") != "SUPPORTED" and not soft:
            continue
        k = contract_card(s, frames, p, (ctx["cpi"] or {}).get(frames[-1].month), today)
        k["uwagi"] = [x for x in reasons if "dane sprzed" in x or "brakuje danych umowy" in x] if soft else []
        cards.append(k)
    return sorted(cards, key=lambda k: -(k["save_cancel_gr"] if k["action"] == "anulowac" else k["yearly_gr"]))


def render(plan: CyclePlan, cards: list[dict]) -> str:
    L = [f"# Decyzje budżetowe — {plan.today.isoformat()}", "",
         "MUZ nic nie wykonuje sam. To lista dla Ciebie: kwoty, terminy i to, co trzeba zrobić samemu.", "",
         render_cycle(plan), "## Umowy i opłaty stałe", ""]
    if cards:
        total = sum(k["save_cancel_gr"] if k["action"] == "anulowac" else k["yearly_gr"] for k in cards)
        L.append(f"Do odzyskania rocznie: **{zl(total)}**. Kolejność: od największej kwoty.\n")
        L += [render_card(k) for k in cards]
    else:
        L.append("Brak decyzji: żadna opłata nie rośnie istotnie ponad inflację (albo brak pliku CPI — `dane/cpi.csv`).\n")
    return "\n".join(L)


def to_json(plan: CyclePlan, cards: list[dict]) -> str:
    def conv(o):
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, (np.integer, np.floating)):
            return o.item()
        raise TypeError(type(o))
    from dataclasses import asdict
    return json.dumps({"przydzial": asdict(plan), "umowy": cards}, default=conv, ensure_ascii=False, indent=1)
