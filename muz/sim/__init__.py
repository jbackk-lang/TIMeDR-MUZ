"""Pakiety budzetow: syntetyczne gospodarstwa domowe oparte na danych GUS, do uczenia mini-AI.

- gus_bgd:   liczby z GUS "Budzety gospodarstw domowych w 2024 r." (kwintyle dochodu, struktura wydatkow),
- generator: gospodarstwa w 5 kwintylach dochodu, strumienie platnosci, zdarzenia (podwyzki, koniec promocji,
             indeksacja, podwojny rachunek), umowy,
- teacher:   jawny nauczyciel (reguly z prereg/muz_decision_v0.2.json) - etykiety akcji.
Model uczony na pakietach odtwarza nauczyciela. Nie jest dowodem trafnosci decyzji na prawdziwych danych.
"""
