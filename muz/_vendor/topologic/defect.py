import numpy as np

# Stala skalujaca MAD do odchylenia standardowego dla rozkladu normalnego.
MAD_TO_STD = 1.4826

METHODS = ("std", "mad", "relative")


def defect(prev, curr, sigma=2.0, history=None, method="std", rel_threshold=None):
    """
    Operator defektu: wykrywa skok miedzy `prev` a `curr`, ktory odstaje od
    normalnej zmiennosci sygnalu. Zgodnie z definicja "defektu" z Axioms_S
    (skok miedzy kolejnymi probkami powyzej progu).

    HISTORIA POPRAWEK
    - v0.2: oryginalna wersja liczyla np.std([prev, curr]) z tych samych
      dwoch punktow, ktore porownywala. Dla dwoch liczb std = |a-b|/2, wiec
      warunek upraszczal sie do stalej 1 > sigma/2, niezaleznej od skoku
      (przy sigma=2.0 nigdy True, przy sigma<2.0 zawsze True). Naprawione
      przez jawna `history`.
    - v0.3: dodane dwie metody zalecane w projekcie TIMeDR-MUZ (sekcja
      "Sygnaly M/S dla finansow"). Metoda domyslna "std" zostaje bez zmian,
      zeby nie zmieniac wynikow istniejacego kodu.

    METODY
    - "std" (domyslna, zachowanie v0.2): |curr-prev| > sigma * std(history).
      ZNANE OGRANICZENIE: porownuje KROK z rozrzutem POZIOMOW historii. Dla
      sygnalu z trendem (np. 0,1,2,...,19) std poziomow jest duze (~5,8),
      wiec wyrazny skok (+4 zamiast typowego +1) nie zostaje wykryty.
    - "mad" (zalecana dla nowego kodu): odpornosciowy z-score BIEZACEGO
      KROKU wzgledem krokow z historii:
          d = diff(history), m = median(d), s = 1.4826 * median(|d - m|)
          defekt, gdy |(curr-prev) - m| > sigma * s
      Mediana i MAD nie daja sie zawyzyc pojedynczym wczesniejszym skokiem,
      a porownanie krokow z krokami dziala takze przy trendzie.
      Gdy s == 0 (wszystkie wczesniejsze kroki identyczne), defektem jest
      kazdy krok rozny od typowego (analogicznie do plaskiej historii w "std").
    - "relative" (zalecana dla kwot o stalej wysokosci, np. rachunkow):
      |curr-prev| / |prev| > rel_threshold. Prog ustalany Z GORY (np. 0.10),
      nie dopasowywany do danych. Nie wymaga historii.

    Parametry:
      prev, curr    - dwie kolejne wartosci sygnalu
      sigma         - prog czulosci dla "std" i "mad"
      history       - wczesniejsze wartosci sygnalu (SPRZED prev/curr):
                      "std" wymaga >= 2, "mad" wymaga >= 3 (>= 2 krokow),
                      "relative" ignoruje
      method        - "std" | "mad" | "relative"
      rel_threshold - prog wzglednej zmiany dla "relative" (wymagany)

    Zwraca bool. Zglasza ValueError przy nieznanej metodzie, za krotkiej
    historii albo braku rel_threshold, zamiast cicho zwracac bezsensowny wynik.
    """
    if method not in METHODS:
        raise ValueError(f"nieznana metoda defect(): {method!r}, dozwolone: {METHODS}")

    if method == "relative":
        if rel_threshold is None:
            raise ValueError("method='relative' wymaga jawnego 'rel_threshold' (np. 0.10), ustalonego z gory")
        if prev == 0:
            raise ValueError("method='relative' jest niezdefiniowana dla prev == 0 (dzielenie przez zero)")
        return bool(abs(curr - prev) / abs(prev) > rel_threshold)

    if method == "std":
        if history is None or len(history) < 2:
            raise ValueError(
                "defect() wymaga 'history' (co najmniej 2 wczesniejszych "
                "wartosci sygnalu, SPRZED prev/curr) do policzenia bazowego "
                "odchylenia standardowego - bez tego nie da sie statystycznie "
                "odroznic anomalii od normalnej zmiennosci sygnalu. Przekaz "
                "np. ostatnie N probek PRZED 'prev'."
            )
        baseline_std = float(np.std(np.asarray(history, dtype=float)))
        if baseline_std == 0:
            # historia calkowicie plaska - kazda roznica prev/curr jest anomalia
            return bool(curr != prev)
        return bool(abs(curr - prev) > sigma * baseline_std)

    # method == "mad"
    if history is None or len(history) < 3:
        raise ValueError(
            "method='mad' wymaga 'history' z co najmniej 3 wczesniejszymi "
            "wartosciami (czyli co najmniej 2 krokami), SPRZED prev/curr."
        )
    steps = np.diff(np.asarray(history, dtype=float))
    typical = float(np.median(steps))
    scale = MAD_TO_STD * float(np.median(np.abs(steps - typical)))
    deviation = abs((curr - prev) - typical)
    if scale == 0:
        return bool(deviation > 0)
    return bool(deviation > sigma * scale)
