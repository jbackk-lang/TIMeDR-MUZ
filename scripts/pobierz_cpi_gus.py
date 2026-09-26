"""Pobiera miesieczne CPI z GUS i zapisuje dane/cpi.csv w formacie MUZ (miesiac;cpi_rr).

Uruchom w folderze TIMeDR-MUZ:  python scripts/pobierz_cpi_gus.py
Surowy plik GUS zostaje obok (dane/gus_cpi_surowe.csv) z hashem w dane/cpi_zrodlo.json - do audytu.
"""
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from muz.adapter.gus import GUS_CPI_CSV_URL, parse_gus_monthly_csv, write_cpi_csv  # noqa: E402

out = ROOT / "dane"
out.mkdir(exist_ok=True)
print("Pobieram:", GUS_CPI_CSV_URL)
req = urllib.request.Request(GUS_CPI_CSV_URL, headers={"User-Agent": "TIMeDR-MUZ/0"})
raw = urllib.request.urlopen(req, timeout=60).read()
(out / "gus_cpi_surowe.csv").write_bytes(raw)
cpi = parse_gus_monthly_csv(raw)
write_cpi_csv(cpi, out / "cpi.csv")
meta = {"url": GUS_CPI_CSV_URL, "pobrano": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256_surowego": hashlib.sha256(raw).hexdigest(), "miesiecy": len(cpi),
        "od": min(cpi), "do": max(cpi)}
(out / "cpi_zrodlo.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Zapisano dane/cpi.csv: {len(cpi)} miesiecy ({meta['od']} - {meta['do']})")
for m in sorted(cpi)[-6:]:
    print(f"  {m}: {cpi[m] * 100:.1f}%")
