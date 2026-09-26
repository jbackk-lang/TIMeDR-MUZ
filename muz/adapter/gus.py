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
