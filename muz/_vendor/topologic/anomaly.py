import numpy as np

from .defect import MAD_TO_STD


def anomaly(value, history, k=3.0):
    """
    Operator anomalii (v0.3): wartosc poza norma wyznaczona z historii.
    Zgodnie z definicja "anomalii" z Axioms_S (wartosc poza norma), w
    wariancie odpornosciowym zalecanym w projekcie TIMeDR-MUZ:

        anomalia, gdy |value - median(history)| > k * 1.4826 * MAD(history)

    Mediana i MAD zamiast sredniej i odchylenia standardowego, bo przy
    krotkiej historii (np. 12 miesiecznych probek) jedna duza wartosc
    zawyza odchylenie standardowe i maskuje wlasna anomalie.

    Parametry:
      value   - biezaca wartosc (NIE wliczana do historii)
      history - co najmniej 3 wczesniejsze wartosci sygnalu
      k       - prog w jednostkach odpornego odchylenia (domyslnie 3.0)

    Gdy MAD == 0 (historia w wiekszosci stala), anomalia to kazda wartosc
    rozna od mediany. Zwraca bool.
    """
    if history is None or len(history) < 3:
        raise ValueError("anomaly() wymaga 'history' z co najmniej 3 wczesniejszymi wartosciami")
    hist = np.asarray(history, dtype=float)
    center = float(np.median(hist))
    scale = MAD_TO_STD * float(np.median(np.abs(hist - center)))
    deviation = abs(float(value) - center)
    if scale == 0:
        return bool(deviation > 0)
    return bool(deviation > k * scale)
