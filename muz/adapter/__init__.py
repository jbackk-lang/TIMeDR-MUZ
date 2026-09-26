"""Modul 1: adapter finansowy GSF -> LSF -> dane PL.

- csv_import: wyciagi CSV z bankowosci (lokalnie),
- mt940:      wyciagi MT940 (lokalnie),
- nbp:        kursy srednie NBP, tabela A (siec: tylko api.nbp.pl),
- gus:        CPI z pliku pobranego z GUS albo z BDL (siec: tylko bdl.stat.gov.pl),
- contracts:  recznie potwierdzone pola umow (umowy.json).
Adapter jest jedyna warstwa Finance-Core z dostepem do sieci i tylko do odczytu.
"""
from .csv_import import (LSFRecord, Stream, build_streams, deduplicate, load_cpi, load_csv,
                         monthly_income_gr, normalize_counterparty, parse_amount_gr, parse_date)
from .contracts import attach_contracts, load_contracts
from .mt940 import load_mt940

__all__ = ["LSFRecord", "Stream", "build_streams", "deduplicate", "load_cpi", "load_csv", "load_mt940",
           "monthly_income_gr", "normalize_counterparty", "parse_amount_gr", "parse_date",
           "attach_contracts", "load_contracts", "record_payload", "stream_payload"]


def record_payload(r: LSFRecord) -> dict:
    return {"date": r.date.isoformat(), "amount_gr": r.amount_gr, "currency": r.currency,
            "counterparty": r.counterparty, "iban_hash": r.iban_hash, "source": r.source, "raw_hash": r.raw_hash,
            "balance_gr": r.balance_gr}


def stream_payload(s: Stream) -> dict:
    return {"stream_id": s.stream_id, "counterparty": s.counterparty, "contract": s.contract,
            "cadence": s.cadence, "series": [[m, a] for m, a in zip(s.months, s.amounts_gr)]}
