import numpy as np


def twist(prev2, prev, curr, threshold=0.0):
    """
    Operator skretu: wykrywa ODWROCENIE KIERUNKU trendu miedzy dwoma
    kolejnymi krokami sygnalu - zgodnie z definicja "skretu sygnalowego"
    uzywana w reszcie ekosystemu TIMDR (zmiana znaku lokalnego nachylenia
    miedzy dwoma kolejnymi oknami/krokami).

    POPRAWKA BLEDU (v0.2): oryginalna wersja przyjmowala tylko 2 punkty
    (prev, curr) i liczyla (curr-prev)*(prev-threshold)<0. Odwrocenia
    kierunku NIE DA SIE wykryc z 2 punktow - do tego potrzeba trzeciego,
    wczesniejszego punktu (prev2), zeby w ogole miec POPRZEDNI kierunek
    zmiany do porownania. Stara wersja faktycznie liczyla "czy sygnal
    zblizza sie do `threshold`", co jest INNA wielkoscia niz "zmiana
    kierunku sygnalu" z jej wlasnego docstringa.

    Parametry:
      prev2, prev, curr - trzy kolejne wartosci sygnalu (w tej kolejnosci
                           czasowej: prev2 najstarsza, curr najnowsza)
      threshold          - minimalna WIELKOSC zmiany nachylenia (nie
                            polozenie wzgledem zera), zeby odwrocenie
                            zostalo uznane za istotne, a nie szum

    Zwraca True, jesli znak (curr-prev) jest przeciwny do znaku
    (prev-prev2) ORAZ wielkosc zmiany nachylenia przekracza `threshold`.
    """
    delta_prev = prev - prev2
    delta_curr = curr - prev

    if delta_prev == 0 or delta_curr == 0:
        # brak ruchu w ktoryms z krokow - nie da sie mowic o "odwroceniu
        # kierunku" (kierunek niezdefiniowany), traktujemy jako brak skretu
        return False

    reversed_direction = np.sign(delta_curr) != np.sign(delta_prev)
    magnitude = abs(delta_curr - delta_prev)
    return bool(reversed_direction and magnitude > threshold)
