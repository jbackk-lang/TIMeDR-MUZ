# TIMeDR-MUZ

Lokalny, audytowalny agent wykonawczy oparty na TIMDR: sygnał (Finance-Core) → decyzja (mini-AI + AI-Core) → wykonanie (MUZ). Architektura: dokument „TIMeDR-MUZ — architektura lokalnego agenta wykonawczego”. Opis implementacji: [docs/IMPLEMENTACJA.md](docs/IMPLEMENTACJA.md).

Stan: prototyp etapów 0–1. Etap 0 (tylko odczyt) działa na wyciągach z pliku. Etap 1 tworzy plany w kolejce; wykonanie wymaga podpisanego zatwierdzenia. Nic nie przenosi pieniędzy: przelew kończy się SCA w aplikacji banku.

## Szybki start (etap 0)

Dwuklik na `run.bat` otwiera okno: wybierz wyciąg (CSV albo MT940), sprawdź dopasowanie kolumn i kliknij „Uruchom analizę”. Mapowanie zapisuje się w `mapowanie.json`, a raport pokazuje się w oknie i w `wyniki/raport_etap0.md`. Błąd zostaje w oknie, a pełny ślad w `wyniki/blad.txt`.

Z konsoli:

```powershell
pip install numpy
python -m muz run --in wyciag.csv --mapping mapowanie.json --out wyniki
python -m muz verify --log wyniki/audit.jsonl
```

Raport: `wyniki/raport_etap0.md`. Dane użytkownika (`*.csv`, `mapowanie.json`, `wyniki/`, `.muz_salt`) są w `.gitignore`.

## Uczenie mini-AI na pakietach budżetów

```powershell
python -m muz train
```

Generuje 600 syntetycznych budżetów gospodarstw domowych (kwintyle dochodu GUS 2024), uczy mini-AI jawnej reguły decyzji z `prereg/muz_decision_v0.2.json` i rejestruje model w `modele/` (trwa kilka minut). Model działa tylko w trybie cienia: raport pokazuje, co by zaproponował, ale plany nadal tworzą reguły, dopóki model nie przejdzie testu P2 na Twoich decyzjach. Szczegóły i wyniki: [docs/IMPLEMENTACJA.md, sekcja 11](docs/IMPLEMENTACJA.md#11-pakiety-budżetów-syntetycznych-i-uczenie-mini-ai).

## Testy

```powershell
pip install pytest cryptography reportlab
python -m pytest
```

Sygnały TIMDR są w tym systemie diagnostyką obok prostej reguły „r/r ponad CPI + 5 pp”, dopóki nie przejdą pre-rejestrowanego testu P1 na historii użytkownika.
