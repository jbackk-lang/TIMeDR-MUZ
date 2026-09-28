"""Uruchomienie MUZ-SIM v0.1: S0 (kontrola), S1 (trudny, glowny), S2 (deficyt strukturalny -- przewidziana porazka)."""
import sys, json
import numpy as np
from . import petla as M

HYP = {"H1": ("MUZ", "Koperty"), "H1b": ("MUZ", "Bank"), "H2_zegar": ("MUZ", "MUZ_kal"),
       "H3_odniesienie": ("MUZ", "MUZ_1cpi"), "H4_rezimD": ("MUZ", "MUZ_bezD")}


def verdict(ci, d):
    return "SUPPORTED" if ci[0] > 0 else ("MIXED" if d > 0 else "NOT SUPPORTED")


def main(n, seed, scen_list):
    res = {"n": n, "seed": seed}
    for sc in scen_list:
        out, meta = M.simulate(sc, n, seed); S, diff, pt = M.summarize(out, meta)
        r = {"mean": S, "per_type_ok": pt, "types": {t: meta.count(t) for t in set(meta)}}
        r["hyp"] = {}
        for h, (a, b) in HYP.items():
            x = diff(a, b); r["hyp"][h] = dict(x, porownanie=f"{a} - {b}", verdict=verdict(x["CI95"], x["d"]))
        c = diff("MUZ", "Koperty", "cons")
        r["H5_nie_glodzi"] = dict(c, porownanie="cons MUZ - Koperty", verdict="SUPPORTED" if c["CI95"][0] > -0.03 else "NOT SUPPORTED")
        res[sc] = r
    if "S2" in res:
        res["H7_S2_przewidziana_porazka"] = {"ok_MUZ": res["S2"]["mean"]["MUZ"]["ok"],
                                             "verdict": "POTWIERDZONA" if res["S2"]["mean"]["MUZ"]["ok"] <= 0.10 else "NIE"}
    if "S0" in res:
        res["H6_S0_kontrola"] = {"MUZ-Koperty": res["S0"]["hyp"]["H1"], "MUZ-Bank": res["S0"]["hyp"]["H1b"]}
    return res


if __name__ == "__main__":
    n, seed = int(sys.argv[1]), int(sys.argv[2]); sc = sys.argv[3].split(",")
    print(json.dumps(main(n, seed, sc), indent=1, ensure_ascii=False))
