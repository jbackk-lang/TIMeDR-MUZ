import numpy as np


def resonance_m(flags, min_count=3):
    """
    Rezonans M (v0.3): KOINCYDENCJA zdarzen w wielu sygnalach w tym samym
    czasie - zgodnie z definicja "rezonansu M" z Axioms_S: co najmniej
    `min_count` (domyslnie 3) sygnalow ma jednoczesnie anomalie (albo inna
    flage zdarzenia, np. defekt).

    To NIE jest fizyczny oscylator i NIE jest tym samym co `resonance()` z
    tego pakietu. `resonance()` mierzy ZGODNOSC KIERUNKU sygnalow (znaczenie
    "kierunkowe", bliskie R(t) = mean(sign(S')) z GIA-TIMDR). Oba znaczenia
    sa w ekosystemie TIMDR osobne - patrz GLOSSARY / TIMDR_Twists.md.

    Parametry:
      flags     - albo 1D sekwencja bool (jedna flaga na sygnal, jeden
                  moment czasu), albo 2D tablica bool o ksztalcie
                  (liczba_sygnalow, liczba_chwil)
      min_count - minimalna liczba jednoczesnych flag (domyslnie 3)

    Zwraca bool (wejscie 1D) albo tablice bool dlugosci liczba_chwil
    (wejscie 2D).
    """
    if min_count < 1:
        raise ValueError("min_count musi byc >= 1")
    arr = np.asarray(flags, dtype=bool)
    if arr.ndim == 1:
        return bool(arr.sum() >= min_count)
    if arr.ndim == 2:
        return arr.sum(axis=0) >= min_count
    raise ValueError("flags musi byc 1D (sygnaly) albo 2D (sygnaly x czas)")
