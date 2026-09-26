import numpy as np


def resonance(*signals):
    """
    Operator rezonansu KIERUNKOWEGO: True, jesli KAZDY z podanych sygnalow jest sam w
    sobie monotoniczny (wszystkie kroki w jedna strone, pomijajac kroki
    zerowe/plateau) ORAZ wszystkie sygnaly zgadzaja sie co do kierunku
    (wszystkie rosna albo wszystkie maleja).

    ZNACZENIE (v0.3): to jest rezonans "kierunkowy" (zgodnosc kierunku,
    bliski R(t) = mean(sign(S')) z GIA-TIMDR), a NIE rezonans M z Axioms_S
    (koincydencja >= 3 anomalii w tym samym czasie). Rezonans M jest osobnym
    operatorem: `resonance_m()`. Nazwa `resonance` zostaje bez zmian, zeby nie
    lamac istniejacego kodu.

    POPRAWKA BLEDU (v0.2): oryginalna wersja przyjmowala JEDNA plaska
    liste wartosci (`resonance(values)`). Dzialalo to poprawnie dla
    pojedynczego sygnalu (sprawdzenie jego wlasnej monotonicznosci - patrz
    examples/j_operator_basic/resonance_demo.py, ten przypadek zostaje bez
    zmian), ALE J.__call__/logikal.py wywolywaly ja z
    `resonance([prev_a, curr_a, prev_b, curr_b])` - spleszczona lista
    wartosci z DWOCH ROZNYCH sygnalow. `np.diff` na takiej liscie liczy
    m.in. `prev_b - curr_a`, roznice miedzy OSTATNIA wartoscia sygnalu A a
    PIERWSZA wartoscia sygnalu B - wielkosc bez sensu fizycznego, ktora
    mimo to wplywala na wynik. Zweryfikowane na przykladzie z README: dla
    A: 1.0->1.3 (rosnie) i B: 0.9->1.0 (rosnie), stara funkcja zwracala
    resonance=False, mimo ze oba sygnaly wyraznie rosna w tym samym
    kierunku - wlasnie przez ten sztuczny miedzysygnalowy czlon.

    Teraz kazdy sygnal podaje sie OSOBNO jako wlasny argument (albo
    rozpakowana liste): `resonance(sygnal_a, sygnal_b, ...)`. Wywolanie
    z JEDNYM sygnalem odtwarza dokladnie oryginalne zachowanie
    (monotonicznosc calej serii).

    Parametry:
      *signals - jeden lub wiecej sygnalow, kazdy jako sekwencja liczb
                 dlugosci >= 2

    Zwraca:
      False, jesli ktorykolwiek sygnal jest calkowicie plaski (brak
      zdefiniowanego kierunku) albo sygnaly nie zgadzaja sie co do
      kierunku; w przeciwnym razie True.
    """
    if len(signals) < 1:
        raise ValueError("resonance() wymaga co najmniej jednego sygnalu")

    first_sign = None
    for signal in signals:
        arr = np.asarray(signal, dtype=float)
        if len(arr) < 2:
            raise ValueError("kazdy sygnal potrzebuje co najmniej 2 punktow")

        diffs = np.diff(arr)
        diffs = diffs[diffs != 0]  # kroki zerowe (plateau) nie niosa kierunku
        if len(diffs) == 0:
            return False  # sygnal calkowicie plaski - brak kierunku

        signs = np.sign(diffs)
        if not np.all(signs == signs[0]):
            return False  # ten sygnal sam w sobie nie jest monotoniczny

        if first_sign is None:
            first_sign = signs[0]
        elif signs[0] != first_sign:
            return False  # sygnaly nie zgadzaja sie co do kierunku

    return True
