from collections import deque

import numpy as np


class J:
    """
    Operator J: laczy skret (twist), defekt (defect) i rezonans (resonance)
    w jedna decyzje topologiczna, dla strumienia par wartosci (sygnal_a,
    sygnal_b) doplywajacych krok po kroku.

    POPRAWKA BLEDU (v0.2): oryginalna wersja byla BEZSTANOWA -
    `J(prev_a, curr_a, prev_b, curr_b)` dostawala tylko jedna pare
    kolejnych punktow na wywolanie. To fundamentalnie nie wystarcza:
    poprawny `twist()` potrzebuje 3 punktow (zeby wykryc odwrocenie
    kierunku), a poprawny `defect()` potrzebuje historii do policzenia
    bazowej zmiennosci (patrz poprawki w twist.py/defect.py). Z samej
    pary (prev, curr) nie da sie tego zrobic poprawnie - stara wersja
    dawala wyniki matematycznie zdegenerowane (patrz README, sekcja
    "Poprawki v0.2" - przyklad z oryginalnej dokumentacji dawal
    {twist: False, defect: False, resonance: False, J: 0.0} mimo
    wyraznie rosnacych obu sygnalow).

    Nowe API jest STANOWE: `J.step(value_a, value_b)` dostaje JEDNA nowa
    probke na wywolanie i sam trzyma wewnetrzne okno historii
    (`window` ostatnich probek per sygnal), z ktorego liczy wszystko, co
    potrzebne. Surowe funkcje (twist/defect/resonance) sa nadal dostepne
    bezposrednio, jesli ktos chce sam zarzadzac wlasna historia.
    """

    def __init__(self, twist_fn, defect_fn, resonance_fn, window=20, sigma=2.0, twist_threshold=0.0,
                 defect_method="std", rel_threshold=None):
        """
        defect_method (v0.3): "std" (domyslnie, zachowanie v0.2), "mad"
        (zalecane, odporny z-score kroku) albo "relative" (wymaga
        rel_threshold). Patrz topologic.defect.defect.
        """
        self.defect_method = defect_method
        self.rel_threshold = rel_threshold
        self.twist = twist_fn
        self.defect = defect_fn
        self.resonance = resonance_fn
        self.window = window
        self.sigma = sigma
        self.twist_threshold = twist_threshold
        self._hist_a = deque(maxlen=window)
        self._hist_b = deque(maxlen=window)

    def reset(self):
        """Czysci wewnetrzna historie (np. po zresetowaniu monitorowanego zjawiska)."""
        self._hist_a.clear()
        self._hist_b.clear()

    def step(self, value_a, value_b):
        """
        Dodaje nowa probke (value_a, value_b) do wewnetrznego okna i
        zwraca decyzje J policzona na jego podstawie.

        Zawsze zwraca ten sam ksztalt slownika, nawet gdy w oknie jest
        jeszcze za malo danych do policzenia ktoregos z operatorow
        (wtedy ten operator jest po prostu False, a nie wyrzuca wyjatku) -
        celowo, zeby wywolujacy mogl karmic funkcje strumieniem danych od
        pierwszej probki bez specjalnej obslugi "rozgrzewki".
        """
        self._hist_a.append(float(value_a))
        self._hist_b.append(float(value_b))

        result = {"twist": False, "defect": False, "resonance": False, "J": 0.0}
        if len(self._hist_a) < 2:
            return result

        hist_a, hist_b = list(self._hist_a), list(self._hist_b)
        prev_a, curr_a = hist_a[-2], hist_a[-1]
        prev_b, curr_b = hist_b[-2], hist_b[-1]

        twist_a = twist_b = False
        if len(hist_a) >= 3:
            twist_a = self.twist(hist_a[-3], prev_a, curr_a, threshold=self.twist_threshold)
            twist_b = self.twist(hist_b[-3], prev_b, curr_b, threshold=self.twist_threshold)

        defect_a = defect_b = False
        # bazowa historia: "std" >= 2 punkty, "mad" >= 3 punkty, "relative" nie potrzebuje
        min_len = {"std": 4, "mad": 5, "relative": 2}.get(self.defect_method, 4)
        if len(hist_a) >= min_len:
            baseline_a = hist_a[:-2]
            baseline_b = hist_b[:-2]
            kw = dict(sigma=self.sigma, method=self.defect_method, rel_threshold=self.rel_threshold)
            if self.defect_method == "relative":
                defect_a = prev_a != 0 and self.defect(prev_a, curr_a, **kw)
                defect_b = prev_b != 0 and self.defect(prev_b, curr_b, **kw)
            else:
                defect_a = self.defect(prev_a, curr_a, history=baseline_a, **kw)
                defect_b = self.defect(prev_b, curr_b, history=baseline_b, **kw)

        resonance = self.resonance([prev_a, curr_a], [prev_b, curr_b])

        J_point = float(np.mean([
            float(bool(twist_a) or bool(twist_b)),
            float(bool(defect_a) or bool(defect_b)),
            float(resonance),
        ]))

        return {
            "twist": bool(twist_a) or bool(twist_b),
            "defect": bool(defect_a) or bool(defect_b),
            "resonance": bool(resonance),
            "J": J_point,
        }

    def __call__(self, value_a, value_b):
        """Alias na step() - wygodne przy uzyciu jako obiekt wywolywalny w petli."""
        return self.step(value_a, value_b)
