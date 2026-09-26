"""Kursy srednie NBP (tabela A) - przeliczanie platnosci w walutach na PLN kursem z dnia transakcji.

Siec wylacznie do api.nbp.pl. Gdy w dniu transakcji nie ma tabeli (weekend, swieto), bierzemy
ostatnia wczesniejsza tabele (do 7 dni wstecz).
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ..core.netguard import fetch
from .csv_import import LSFRecord

ALLOWED_HOSTS = frozenset({"api.nbp.pl"})


def mid_rate(code: str, day: date, fetcher=fetch) -> tuple[float, date]:
    last_err = None
    for back in range(0, 8):
        d = day - timedelta(days=back)
        url = f"https://api.nbp.pl/api/exchangerates/rates/a/{code.lower()}/{d.isoformat()}/?format=json"
        try:
            data = json.loads(fetcher(url, ALLOWED_HOSTS))
            return float(data["rates"][0]["mid"]), d
        except Exception as exc:  # 404 = brak tabeli w tym dniu
            last_err = exc
    raise RuntimeError(f"brak kursu NBP {code} dla {day} i 7 dni wstecz: {last_err}")


def convert_to_pln(records: list[LSFRecord], fetcher=fetch) -> list[LSFRecord]:
    out = []
    cache: dict[tuple, float] = {}
    for r in records:
        if r.currency == "PLN":
            out.append(r)
            continue
        key = (r.currency, r.date)
        if key not in cache:
            cache[key] = mid_rate(r.currency, r.date, fetcher)[0]
        pln = int((Decimal(r.amount_gr) * Decimal(str(cache[key]))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        out.append(replace(r, amount_gr=pln, currency="PLN",
                           description=f"{r.description} [{r.amount_gr / 100:.2f} {r.currency} po kursie NBP {cache[key]}]"))
    return out
