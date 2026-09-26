"""CPI (inflacja r/r, miesiecznie) z GUS.

Dwie drogi:
- plik pobrany recznie ze strony GUS -> load_cpi() z csv_import (kolumny miesiac;cpi_rr),
- zapytanie do BDL (bdl.stat.gov.pl) - adres zapytania i identyfikator zmiennej ustawia uzytkownik
  w konfiguracji; prototyp NIE zgaduje identyfikatora zmiennej.
"""
from __future__ import annotations

from ..core.netguard import fetch

ALLOWED_HOSTS = frozenset({"bdl.stat.gov.pl"})


def fetch_bdl(path_and_query: str, fetcher=fetch) -> bytes:
    """Surowa odpowiedz BDL; interpretacje zapisuje uzytkownik jako plik CPI i zamraza hash."""
    if not path_and_query.startswith("/api/"):
        raise ValueError("oczekiwano sciezki zaczynajacej sie od /api/ (np. z dokumentacji BDL)")
    return fetcher("https://bdl.stat.gov.pl" + path_and_query, ALLOWED_HOSTS)


GUS_CPI_CSV_URL = ("https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultstronaopisowa/4741/1/1/"
                   "miesiecznewskaznikicentowarowiuslugkonsumpcyjnychod1982roku_8.csv")
GUS_HOSTS = frozenset({"stat.gov.pl"})
YOY_BASE = "analogiczny miesiąc poprzedniego roku"


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1250", "iso-8859-2"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("nie rozpoznano kodowania pliku GUS")


def parse_gus_monthly_csv(raw: bytes) -> dict[str, float]:
    """Plik GUS "Miesieczne wskazniki cen towarow i uslug konsumpcyjnych od 1982 r." -> {RRRR-MM: inflacja r/r}.

    Kolumny rozpoznawane po nazwach (Rok, Miesiac, Wartosc, Sposob prezentacji). Brane sa tylko wiersze
    "analogiczny miesiac poprzedniego roku = 100"; wartosc 104,9 -> 0,049. Nierozpoznany uklad = blad
    z lista naglowkow, zamiast zgadywania.
    """
    import csv
    import io
    text = _decode(raw)
    lines = text.splitlines()
    delim = ";" if lines and lines[0].count(";") >= lines[0].count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    header = [h.strip().lower() for h in rows[0]]

    def col(*names):
        for i, h in enumerate(header):
            if any(n in h for n in names):
                return i
        raise ValueError(f"brak kolumny {names} w naglowku GUS: {rows[0]}")

    i_year, i_month, i_val = col("rok"), col("miesiąc", "miesiac"), col("wartość", "wartosc")
    i_pres = col("sposób prezentacji", "sposob prezentacji", "prezentac")
    out: dict[str, float] = {}
    for r in rows[1:]:
        if len(r) <= max(i_year, i_month, i_val, i_pres):
            continue
        if YOY_BASE not in r[i_pres].lower():
            continue
        val = r[i_val].strip().replace(",", ".")
        if not val:
            continue
        month = int(r[i_month])
        if not 1 <= month <= 12:
            continue
        out[f"{int(r[i_year]):04d}-{month:02d}"] = round(float(val) / 100.0 - 1.0, 6)
    if not out:
        raise ValueError("nie znaleziono wierszy 'analogiczny miesiac poprzedniego roku = 100'")
    return out


def write_cpi_csv(cpi: dict[str, float], path) -> None:
    """Zapis w formacie MUZ: miesiac;cpi_rr (procent, przecinek dziesietny)."""
    from pathlib import Path
    lines = ["miesiac;cpi_rr"] + [f"{m};{v * 100:.1f}".replace(".", ",") for m, v in sorted(cpi.items())]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
