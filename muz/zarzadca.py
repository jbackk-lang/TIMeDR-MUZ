"""Zarzadca: jeden przebieg bez pytan. To on robi robote, uzytkownik tylko podrzuca pliki albo wkleja tekst.

Przy kazdym uruchomieniu okna:
1. bierze wszystkie wyciagi z folderu `wyciagi/` + wklejone (`dane/wklejone.csv`) + gotowke (`dane/gotowka.csv`),
   kazdy plik osobno -- zly plik nie zatrzymuje reszty (trafia na liste problemow),
2. sam odswieza CPI z GUS, gdy plik jest starszy niz 35 dni (siec tylko do stat.gov.pl; bez sieci -- stary plik),
3. sam rozpoznaje kategorie oplat stalych, debet i dzien wyplaty,
4. liczy przydzial do wyplaty i sprawy do zalatwienia, pomija sprawy juz zalatwione,
5. zapisuje PDF-y, liste dla Excela, CSV MUZ i dziennik audytu w `wyniki/`.
Z pamieci (ustawienia.json, zapisywanej przez okno) bierze tylko to, czego nie ma w wyciagach.
"""
from __future__ import annotations

import shutil
import string
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from . import adapter, audit, decisions, export_docs, pipeline, rozpoznanie
from .ustawienia import Ustawienia

REPO = pipeline.REPO_DIR
WYCIAGI = REPO / "wyciagi"
DANE = REPO / "dane"
WYNIKI = REPO / "wyniki"
EXT = (".csv", ".txt", ".sta", ".mt940", ".940")
CATEGORIES = ["czynsz", "energia", "telekom", "media", "subskrypcja", "ubezpieczenie", "kredyt", "inne"]


@dataclass
class Sprawa:
    id: str
    tytul: str
    akcja: str
    kontrahent: str
    rocznie_gr: int
    termin: date
    pdf: Path | None
    karta: dict


@dataclass
class Wynik:
    plan: decisions.CyclePlan | None = None
    sprawy: list[Sprawa] = field(default_factory=list)
    oplaty: list[dict] = field(default_factory=list)       # oplaty stale: kontrahent, kategoria, kwota, rozpoznana?
    pliki: list[dict] = field(default_factory=list)        # co wczytano i w jakim formacie
    problemy: list[str] = field(default_factory=list)
    pdf_przydzial: Path | None = None
    pdf_note: str | None = None
    excel: dict = field(default_factory=dict)
    raport: str = ""
    dane_do: date | None = None


def statement_files(wyciagi: Path = WYCIAGI, dane: Path = DANE) -> list[Path]:
    files = sorted(p for p in wyciagi.glob("*") if p.is_file() and p.suffix.lower() in EXT) if wyciagi.exists() else []
    files += [p for p in (dane / "wklejone.csv", dane / "gotowka.csv") if p.exists()]
    return files


def add_files(paths, wyciagi: Path = WYCIAGI) -> list[Path]:
    """Kopiuje wybrane/przeciagniete pliki do folderu wyciagow (oryginaly zostaja na miejscu)."""
    wyciagi.mkdir(parents=True, exist_ok=True)
    out = []
    for p in map(Path, paths):
        if not p.is_file():
            continue
        target = wyciagi / p.name
        if target.exists() and target.read_bytes() == p.read_bytes():
            out.append(target)
            continue
        k = 2
        while target.exists():
            target = wyciagi / f"{p.stem} ({k}){p.suffix}"
            k += 1
        shutil.copy2(p, target)
        out.append(target)
    return out


def refresh_cpi(dane: Path = DANE, max_age_days: int = 35, fetch=None) -> tuple[Path | None, str]:
    """Plik CPI: odswiezany automatycznie z GUS; bez sieci zostaje ostatni. Zwraca (sciezka albo None, komunikat)."""
    path = dane / "cpi.csv"
    if path.exists() and (datetime.now().timestamp() - path.stat().st_mtime) < max_age_days * 86400:
        return path, "CPI aktualne"
    try:
        from .adapter.gus import GUS_CPI_CSV_URL, GUS_HOSTS, parse_gus_monthly_csv, write_cpi_csv
        from .core.netguard import fetch as nfetch
        raw = (fetch or nfetch)(GUS_CPI_CSV_URL, GUS_HOSTS)
        cpi = parse_gus_monthly_csv(raw)
        dane.mkdir(parents=True, exist_ok=True)
        write_cpi_csv(cpi, path)
        return path, f"CPI pobrane z GUS (do {max(cpi)})"
    except Exception as exc:  # noqa: BLE001 - brak sieci nie zatrzymuje zarzadcy
        return (path if path.exists() else None), f"nie udało się odświeżyć CPI z GUS ({exc.__class__.__name__})"


def forward_fill(cpi: dict[str, float] | None, months: int = 3) -> dict[str, float] | None:
    """Ostatnie znane CPI dla kolejnych miesiecy, zanim GUS je opublikuje (GUS publikuje z ~2-tyg. opoznieniem)."""
    if not cpi:
        return cpi
    out = dict(cpi)
    last = max(cpi)
    y, m = map(int, last.split("-"))
    for _ in range(months):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        out.setdefault(f"{y:04d}-{m:02d}", cpi[last])
    return out


def action_id(k: dict) -> str:
    return f"{k['action']}|{k['counterparty']}|{k['now_gr']}"


def run(today: date, ust: Ustawienia, *, wyciagi: Path = WYCIAGI, dane: Path = DANE, wyniki: Path = WYNIKI,
        formats_path=None, salt_path=None, cpi_fetch=None) -> Wynik:
    w = Wynik()
    files = statement_files(wyciagi, dane)
    if not files:
        w.problemy.append("brak wyciągów — dodaj plik z banku albo wklej historię z przeglądarki")
        return w
    salt = pipeline.local_salt(Path(salt_path) if salt_path else REPO / ".muz_salt")
    records, categories = [], {}
    for f in files:
        info = []
        try:
            records += pipeline._load_records([f], {}, salt, categories, info, formats_path)
            w.pliki += info
        except Exception as exc:  # noqa: BLE001 - jeden zly plik nie zatrzymuje reszty
            w.problemy.append(f"{f.name}: nie udało się wczytać ({exc})")
    if not records:
        return w
    w.dane_do = max(r.date for r in records)
    cpi_path, cpi_msg = refresh_cpi(dane, fetch=cpi_fetch)
    if cpi_path is None:
        w.problemy.append(cpi_msg + " — bez inflacji MUZ nie oceni podwyżek")
    elif "nie udało" in cpi_msg:
        w.problemy.append(cpi_msg + " — użyto ostatniego pliku")
    cpi = forward_fill(adapter.load_cpi(cpi_path)) if cpi_path else None

    th, th_sha = pipeline.load_frozen(pipeline.THRESHOLDS)
    dec, dec_sha = pipeline.load_frozen(pipeline.DECISION)
    streams0 = adapter.build_streams(adapter.deduplicate(records), th["recurring_min_payment_months"], th["monthly_min_coverage"])
    overrides = {**categories, **ust.d["kategorie"]}
    contracts = rozpoznanie.infer_contracts(streams0, records, overrides, ust.d["potwierdzone"], ust.d["negocjacje"])
    ctx = pipeline.prepare_records(records, cpi, contracts, th=th, th_sha=th_sha, vendor_sha=pipeline.verify_vendor())
    ctx["categories"] = categories

    profile = ust.profile(today)
    od = rozpoznanie.overdraft(ctx["records"])
    if od and not any(d.get("nazwa") == "debet na koncie" for d in profile["dlugi"]):
        profile["dlugi"] = profile["dlugi"] + [{"nazwa": "debet na koncie", "kwota_zl": od / 100, "oprocentowanie_proc": 20}]
    w.plan = decisions.cycle_plan(ctx["records"], ctx["streams"], today=today, profile=profile, categories=categories)
    cards = decisions.contract_decisions(ctx, dec=dec, dec_sha=dec_sha, today=today)

    for s in ctx["monthly"]:
        c = s.contract or {}
        w.oplaty.append({"kontrahent": s.counterparty, "kategoria": c.get("category", "inne"),
                         "kwota_gr": next((a for a in reversed(s.amounts_gr) if a > 0), 0),
                         "rozpoznana": c.get("inferred", True), "potwierdzona": c.get("confirmed_by_user", False)})

    wyniki.mkdir(parents=True, exist_ok=True)
    pdfs, w.pdf_note = export_docs.decisions_pdfs(w.plan, cards, wyniki / "pdf")
    export_docs.decisions_csv(w.plan, cards, wyniki / "decyzje.csv", pdfs)
    from .adapter.muz_csv import write_records
    write_records(ctx["records"], wyniki / "transakcje_muz.csv", {**categories, **{k: v["category"] for k, v in contracts.items()}})
    (wyniki / "decyzje.md").write_text(decisions.render(w.plan, cards), encoding="utf-8")
    w.excel = {"decyzje": wyniki / "decyzje.csv", "transakcje": wyniki / "transakcje_muz.csv"}
    w.pdf_przydzial = pdfs.get(-1)
    for i, k in enumerate(cards):
        aid = action_id(k)
        if ust.is_done(aid):
            continue
        yearly = k["save_cancel_gr"] if k["action"] == "anulowac" else k["yearly_gr"]
        w.sprawy.append(Sprawa(aid, decisions.card_title(k), k["action"], k["counterparty"], yearly, k["deadline"],
                               pdfs.get(i), k))
    w.raport = decisions.render(w.plan, cards)
    audit.append(wyniki / "audit.jsonl", "zarzadca_przebieg",
                 {"pliki": [p.get("plik") for p in w.pliki], "rekordy": len(ctx["records"]), "sprawy": len(w.sprawy),
                  "tryb": w.plan.mode, "cpi": cpi_msg, "decision_sha256": dec_sha, "thresholds_sha256": th_sha})
    return w


def letter_pdf(s: Sprawa, ust: Ustawienia, today: date, out: Path) -> Path:
    """Szkic pisma do wydruku (wysylasz sam). Puste miejsca, ktorych MUZ nie zna, zostaja do wpisania dlugopisem."""
    from .executor.letters import TEMPLATES_DIR, TEMPLATE_BY_ACTION
    k = s.karta
    osoba = ust.d.get("osoba", {})
    blank = "____________________"
    fields = {"miejscowosc": osoba.get("miejscowosc", blank), "data": today.strftime("%d.%m.%Y"),
              "imie_nazwisko": osoba.get("imie_nazwisko", blank), "adres": osoba.get("adres", blank),
              "kontrahent": k["counterparty"], "adres_kontrahenta": blank, "numer_umowy": blank,
              "miesiac_zmiany": k["change_month"],
              "kwota_przed": f"{k['before_gr'] / 100:.2f}".replace(".", ","),
              "kwota_po": f"{k['now_gr'] / 100:.2f}".replace(".", ","),
              "zmiana": "" if k["rel"] is None else f"{k['rel'] * 100:+.1f}%".replace(".", ","),
              "okres_wypowiedzenia": k.get("notice") or "___", "nowy_plan": blank}
    tpl = (TEMPLATES_DIR / TEMPLATE_BY_ACTION[s.akcja][0]).read_text(encoding="utf-8")
    needed = {f for _, f, _, _ in string.Formatter().parse(tpl) if f}
    text = tpl.format(**{n: fields.get(n, blank) for n in needed})
    out.mkdir(parents=True, exist_ok=True)
    title = {"negocjowac": "Prośba o obniżkę", "anulowac": "Wypowiedzenie umowy", "zmienic": "Wniosek o zmianę planu"}[s.akcja]
    path = out / f"{today.isoformat()}_Pismo_{export_docs.slug(title + ' ' + s.kontrahent)}.pdf"
    return export_docs._pdf(path, f"{title}: {s.kontrahent}", text, "Szkic pisma — wydrukuj, podpisz i wyślij sam.")
