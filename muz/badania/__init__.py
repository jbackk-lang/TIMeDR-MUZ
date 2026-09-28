"""Badania MUZ: sprawdzenie zasad TIMDR w zarzadzaniu budzetem (pre-rejestrowane, jednorazowe uruchomienia).

- petla:     symulacja zamknietej petli (36 miesiecy, dzien po dniu): czy zarzadca wyprowadza zadluzone
             gospodarstwo "na prosta". Kopia 1:1 pliku zamrozonego w GIA-TIMDR (core/muz_sim.py, commit c1d6680,
             sha256 25ff4ec2...). Nie zmieniac -- zmiana = nowa wersja badania z nowa pre-rejestracja.
- petla_run: uruchomienie scenariuszy S0 (kontrola), S1 (trudny), S2 (deficyt strukturalny) i hipotezy H1-H7.

Zarzadca "MUZ" w badaniu to model badawczy polityki (zegar wplywu, odniesienie CPI per kategoria, rezim zdarzen),
jeszcze nie przeniesiony do muz/mini_ai ani prereg/muz_decision_*.json.
"""
