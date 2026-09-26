"""Maly MLP w czystym NumPy: 40 -> 32 -> 16 -> 4, ReLU, softmax, Adam, L2, skalowanie temperatury.

Wagi zapisywane do .npz; hash pliku identyfikuje model w rejestrze Claim Graph.
Regresja logistyczna (baseline z dokumentu) to ten sam kod z warstwami [40, 4].
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..core.common import sha256_file


def log_loss(proba: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(proba[np.arange(len(y)), y], 1e-12, 1.0)
    return float(-np.mean(np.log(p)))


class MLP:
    def __init__(self, sizes=(40, 32, 16, 4), seed: int = 0):
        self.sizes = tuple(int(s) for s in sizes)
        rng = np.random.default_rng(seed)
        self.W = [rng.normal(0, np.sqrt(2.0 / a), (a, b)) for a, b in zip(self.sizes[:-1], self.sizes[1:])]
        self.b = [np.zeros(b) for b in self.sizes[1:]]
        self.T = 1.0  # temperatura (kalibracja)

    # --- przebieg w przod ---
    def _forward(self, X):
        acts = [X]
        h = X
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            z = h @ W + b
            h = np.maximum(z, 0.0) if i < len(self.W) - 1 else z
            acts.append(h)
        return acts

    @staticmethod
    def _softmax(z):
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    def predict_proba(self, X) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, dtype=float))
        return self._softmax(self._forward(X)[-1] / self.T)

    # --- trening ---
    def fit(self, X, y, epochs: int = 300, lr: float = 0.01, l2: float = 1e-4, batch: int = 32, seed: int = 0):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=int)
        rng = np.random.default_rng(seed)
        params = self.W + self.b
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        b1, b2, eps, t = 0.9, 0.999, 1e-8, 0
        n_layers = len(self.W)
        for _ in range(epochs):
            order = rng.permutation(len(X))
            for start in range(0, len(X), batch):
                idx = order[start:start + batch]
                acts = self._forward(X[idx])
                p = self._softmax(acts[-1])
                g = p.copy()
                g[np.arange(len(idx)), y[idx]] -= 1.0
                g /= len(idx)
                gW, gb = [None] * n_layers, [None] * n_layers
                for i in range(n_layers - 1, -1, -1):
                    gW[i] = acts[i].T @ g + l2 * self.W[i]
                    gb[i] = g.sum(axis=0)
                    if i > 0:
                        g = (g @ self.W[i].T) * (acts[i] > 0)
                grads = gW + gb
                t += 1
                for k, (prm, gr) in enumerate(zip(params, grads)):
                    m[k] = b1 * m[k] + (1 - b1) * gr
                    v[k] = b2 * v[k] + (1 - b2) * gr * gr
                    prm -= lr * (m[k] / (1 - b1 ** t)) / (np.sqrt(v[k] / (1 - b2 ** t)) + eps)
        return self

    def fit_temperature(self, Xval, yval, grid=np.linspace(0.5, 5.0, 46)):
        best = min(grid, key=lambda T: self._nll_at(Xval, yval, T))
        self.T = float(best)
        return self.T

    def _nll_at(self, X, y, T):
        saved, self.T = self.T, T
        try:
            return log_loss(self.predict_proba(X), np.asarray(y, dtype=int))
        finally:
            self.T = saved

    # --- waznosc cech ---
    def permutation_importance(self, x, background, cls: int, n: int = 64, seed: int = 0) -> np.ndarray:
        """Spadek p(cls | x) po zastapieniu cechy j wartosciami z permutowanego tla (dla jednego przykladu)."""
        rng = np.random.default_rng(seed)
        x = np.asarray(x, dtype=float)
        bg = np.asarray(background, dtype=float)
        base = self.predict_proba(x)[0, cls]
        out = np.zeros(len(x))
        for j in range(len(x)):
            Xp = np.repeat(x[None, :], n, axis=0)
            Xp[:, j] = bg[rng.integers(0, len(bg), n), j]
            out[j] = base - self.predict_proba(Xp)[:, cls].mean()
        return out

    # --- zapis / odczyt ---
    def save(self, path) -> str:
        arrays = {f"W{i}": W for i, W in enumerate(self.W)} | {f"b{i}": b for i, b in enumerate(self.b)}
        np.savez(path, sizes=np.array(self.sizes), T=np.array(self.T), **arrays)
        p = Path(path)
        p = p if p.suffix == ".npz" else p.with_suffix(p.suffix + ".npz")
        return sha256_file(p)

    @classmethod
    def load(cls, path, expected_sha256: str | None = None) -> "MLP":
        if expected_sha256 is not None and sha256_file(path) != expected_sha256:
            raise RuntimeError("INCONCLUSIVE_WEIGHTS_CHANGED: hash wag nie zgadza sie z rejestrem")
        d = np.load(path)
        obj = cls(tuple(int(s) for s in d["sizes"]))
        n = len(obj.sizes) - 1
        obj.W = [d[f"W{i}"] for i in range(n)]
        obj.b = [d[f"b{i}"] for i in range(n)]
        obj.T = float(d["T"])
        return obj
