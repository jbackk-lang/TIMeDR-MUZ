"""Uczenie mini-AI na pakietach budzetow (syntetycznych, opartych na GUS) i rejestracja przez TIMDRProtocol.

Przebieg (parametry z prereg/muz_decision_v0.2.json):
1. N pakietow -> ten sam lancuch co dla prawdziwych danych (strumienie, sygnaly, META, fazy, cechy),
   probki tylko z miesiecy poza faza stabilna (tam mini-AI w ogole dziala), etykiety od nauczyciela,
2. podzial PO GOSPODARSTWACH (bez przecieku miedzy zbiorami),
3. kontrolki procesu uczenia: pozytywna (model odzyskuje prosta, podlozona regule) i negatywna
   (model uczony na przetasowanych etykietach nie bije klasy wiekszosciowej),
4. modele: polityka regulowa, regresja logistyczna, MLP; wybor wg marginesu log-loss,
5. test: trafnosc na zbiorze testowym vs rozklad przy permutacji etykiet; efekt = trafnosc - klasa wiekszosciowa,
6. rejestracja z flaga synthetic=True: model dziala wylacznie w trybie cienia.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from ..core.atomic import atomic_write_text

import numpy as np

from .. import adapter, meta, phases, signals
from .._vendor.ai_core.timdr_ai_core import ControlResult, Hypothesis, ProtocolCriteria, TestEvidence
from ..ai_core.registry import ModelRegistry
from ..ai_core.validation import select_model
from ..core.common import sha256_file, sha256_obj
from ..core.messages import ACTIONS
from ..sim.generator import generate_package
from ..sim.teacher import teacher_action
from .features import FEATURE_NAMES, build_features
from .mlp import MLP, log_loss
from .policy import amount_12m_ago, rule_policy

A_IDX = {a: i for i, a in enumerate(ACTIONS)}


def income_month(records) -> float:
    inc = adapter.monthly_income_gr(records)
    vals = [inc[m] for m in sorted(inc)[-12:]]
    return float(np.mean(vals)) if vals else 0.0


def package_samples(pkg, th: dict, dec: dict, cpi: dict | None) -> list[dict]:
    streams = adapter.build_streams(pkg.records, th["recurring_min_payment_months"], th["monthly_min_coverage"])
    for s in streams:
        s.contract = pkg.contracts.get(s.counterparty)
    monthly = [s for s in streams if s.cadence == "monthly"]
    frames = {s.stream_id: signals.stream_signals(s, th, cpi) for s in monthly}
    bmeta = {b.month: b for b in meta.budget_meta(streams, frames, cpi, th["budget_min_streams"],
                                                   th.get("J_definition", "slope"))}
    income = income_month(pkg.records)
    out = []
    for s in monthly:
        fs = frames[s.stream_id]
        levels = phases.stream_phases(fs, th)
        for i in range(13, len(fs)):
            phase = phases.NAMES[levels[i]]
            if phase == "stabilna":
                continue
            f, b = fs[i], bmeta.get(fs[i].month)
            cpi_m = (cpi or {}).get(f.month)
            x = build_features(fs[: i + 1], phase, s.contract, b.state if b else None, b.M if b else None,
                               cpi_m, income)
            y = teacher_action(amount_gr=f.amount_gr, amount_12m_ago_gr=amount_12m_ago(fs[: i + 1]), cpi_yoy=cpi_m,
                               contract=s.contract, income_month_gr=income, cfg=dec)
            out.append({"x": x, "y": A_IDX[y], "package": pkg.package_id, "quintile": pkg.quintile,
                        "category": (s.contract or {}).get("category", "inne"), "month": f.month,
                        "rule": A_IDX[rule_policy(f, phase, s.contract)], "phase": phase})
    return out


def build_dataset(n_packages: int, seed: int, th: dict, dec: dict, cpi: dict | None, months: int = 32):
    samples = []
    for k in range(n_packages):
        pkg = generate_package(seed * 100_000 + k, months=months, cpi=cpi)
        samples += package_samples(pkg, th, dec, cpi)
    return samples


def _split_by_package(samples, fractions, seed):
    pkgs = sorted({s["package"] for s in samples})
    rng = np.random.default_rng(seed)
    rng.shuffle(pkgs)
    n = len(pkgs)
    a, b = int(fractions[0] * n), int((fractions[0] + fractions[1]) * n)
    groups = {p: 0 for p in pkgs[:a]} | {p: 1 for p in pkgs[a:b]} | {p: 2 for p in pkgs[b:]}
    parts = [[s for s in samples if groups[s["package"]] == g] for g in range(3)]
    return [(np.array([s["x"] for s in part]), np.array([s["y"] for s in part]), part) for part in parts]


def _acc(pred, y):
    return float((np.asarray(pred) == np.asarray(y)).mean()) if len(y) else float("nan")


def _perm_test(pred, y, n_perm, seed):
    rng = np.random.default_rng(seed)
    obs = _acc(pred, y)
    null = np.array([_acc(pred, rng.permutation(y)) for _ in range(n_perm)])
    return obs, float((1 + (null >= obs).sum()) / (n_perm + 1)), float(null.mean())


def train_and_register(*, out_dir, th, th_sha, dec, dec_sha, cpi, cpi_sha, n_packages=None, seed=None) -> dict:
    tr = dec["training"]
    n_packages = n_packages or tr["packages"]
    seed = tr["seed"] if seed is None else seed
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    samples = build_dataset(n_packages, seed, th, dec, cpi, tr["months"])
    (Xtr, ytr, _), (Xva, yva, _), (Xte, yte, te) = _split_by_package(samples, tr["split"], seed)
    mcfg = dec["mlp"]
    k = len(ACTIONS)

    # --- kontrolki procesu uczenia ---
    planted = (Xtr[:, FEATURE_NAMES.index("defekt")] > 0.5).astype(int)
    planted_te = (Xte[:, FEATURE_NAMES.index("defekt")] > 0.5).astype(int)
    pos_model = MLP(tuple(mcfg["sizes"][:-1]) + (2,), seed=seed).fit(Xtr, planted, epochs=30, lr=mcfg["lr"])
    pos_acc = _acc(pos_model.predict_proba(Xte).argmax(1), planted_te)
    shuffled = np.random.default_rng(seed + 1).permutation(ytr)
    neg_model = MLP(tuple(mcfg["sizes"]), seed=seed).fit(Xtr, shuffled, epochs=30, lr=mcfg["lr"])
    majority_te = Counter(yte.tolist()).most_common(1)[0][1] / len(yte)
    neg_acc = _acc(neg_model.predict_proba(Xte).argmax(1), yte)
    controls = ControlResult(positive_ok=pos_acc >= 0.95, negative_ok=neg_acc <= majority_te + 0.02,
                             details={"positive_acc_planted_rule": pos_acc, "negative_acc_shuffled": neg_acc,
                                      "majority_test": majority_te})

    # --- modele ---
    mlp = MLP(tuple(mcfg["sizes"]), seed=seed).fit(Xtr, ytr, epochs=mcfg["epochs"], lr=mcfg["lr"], l2=mcfg["l2"],
                                                   batch=mcfg["batch"], seed=seed)
    mlp.fit_temperature(Xva, yva)
    logit = MLP(tuple(dec["logistic"]["sizes"]), seed=seed).fit(Xtr, ytr, epochs=mcfg["epochs"], lr=mcfg["lr"],
                                                                 l2=mcfg["l2"], batch=mcfg["batch"], seed=seed)
    logit.fit_temperature(Xva, yva)
    ll_mlp, ll_log = log_loss(mlp.predict_proba(Xva), yva), log_loss(logit.predict_proba(Xva), yva)
    chosen = mlp if select_model(ll_mlp, ll_log, dec["model_selection_logloss_margin"]) else logit
    chosen_name = "mlp" if chosen is mlp else "logistyczna"

    pred = chosen.predict_proba(Xte).argmax(1)
    acc, p_perm, null_mean = _perm_test(pred, yte, tr["permutations"], seed)
    rules_acc = _acc([s["rule"] for s in te], yte)
    effect = acc - majority_te
    per_q = {q: _acc(pred[[s["quintile"] == q for s in te]], yte[[s["quintile"] == q for s in te]]) for q in range(1, 6)}
    conf = np.zeros((k, k), dtype=int)
    for t, p_ in zip(yte, pred):
        conf[t, p_] += 1

    weights = out / "wagi.npz"
    chosen.save(weights)
    card = {
        "model": chosen_name, "dane": "SYNTETYCZNE (pakiety budzetow GUS 2024)", "tryb": "cien",
        "pakiety": n_packages, "probki": {"trening": len(ytr), "walidacja": len(yva), "test": len(yte)},
        "rozklad_etykiet_test": {ACTIONS[i]: int((yte == i).sum()) for i in range(k)},
        "kontrolki": controls.details | {"positive_ok": controls.positive_ok, "negative_ok": controls.negative_ok},
        "log_loss_walidacja": {"mlp": ll_mlp, "logistyczna": ll_log},
        "test": {"trafnosc": acc, "klasa_wiekszosciowa": majority_te, "polityka_regulowa": rules_acc,
                 "p_permutacyjne": p_perm, "srednia_przy_permutacji": null_mean,
                 "trafnosc_wg_kwintyla": per_q, "macierz_pomylek": {"wiersze_prawda_kolumny_model": ACTIONS,
                                                                     "wartosci": conf.tolist()}},
        "hashe": {"progi": th_sha, "decyzje": dec_sha, "cpi": cpi_sha, "wagi": sha256_file(weights),
                  "dane_probki": sha256_obj([[float(v) for v in s["x"]] + [s["y"]] for s in samples[:200]])},
        "uwaga": ("Model odtwarza jawnego nauczyciela z prereg/muz_decision_v0.2.json na danych syntetycznych. "
                  "Nie jest dowodem trafnych decyzji na prawdziwych budzetach; do planow wykonania wymaga P2."),
    }
    (out / "karta.json").write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")

    hyp = Hypothesis("mini-AI odtwarza nauczyciela na odlozonych pakietach (inne gospodarstwa)",
                     "MLP/logistyczna uczone na pakietach budzetow, test na rozlacznych gospodarstwach",
                     f"trafnosc - klasa wiekszosciowa >= {tr['min_effect_accuracy_over_majority']}, p permutacyjne < {tr['alpha']}",
                     {"decyzje_sha256": dec_sha, "progi_sha256": th_sha, "pakiety": n_packages, "seed": seed})
    evidence = TestEvidence(p_value=p_perm, effect_size=effect, method="test permutacyjny trafnosci (etykiety)",
                            details={"trafnosc": acc, "klasa_wiekszosciowa": majority_te})
    node = ModelRegistry(out.parent / "rejestr.json").evaluate_and_register(
        artifact_path=weights, hypothesis=hyp, controls=controls, evidence=evidence,
        criteria=ProtocolCriteria(alpha=tr["alpha"], min_abs_effect_size=tr["min_effect_accuracy_over_majority"]),
        synthetic=True, extra={"karta": str((out / "karta.json").name)})
    if node["verdict"] == "SUPPORTED":
        atomic_write_text(out.parent / "aktywny.json", json.dumps({"wagi": str(weights.relative_to(out.parent)),
                                                                   "tryb": "cien"}, indent=2))
    return {"card": card, "node": node}
