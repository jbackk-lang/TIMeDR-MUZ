# TIMeDR-MUZ

Lokalny, audytowalny agent wykonawczy oparty na TIMDR: sygnał (Finance-Core) → decyzja (mini-AI + AI-Core) → wykonanie (MUZ). Architektura: dokument „TIMeDR-MUZ — architektura lokalnego agenta wykonawczego”. Opis implementacji: [docs/IMPLEMENTACJA.md](docs/IMPLEMENTACJA.md).

Stan: prototyp etapów 0–1. Etap 0 (tylko odczyt) działa na wyciągach z pliku. Etap 1 tworzy plany w kolejce; wykonanie wymaga podpisanego zatwierdzenia. Nic nie przenosi pieniędzy: przelew kończy się SCA w aplikacji banku.

## Jak używać — bez programowania i bez wypełniania rubryk

1. **Dwuklik na `run.bat`.** Za pierwszym razem sam doinstaluje, czego potrzebuje (wymagany jest tylko Python).
2. **Daj mu wyciąg** — jedno z trzech:
   - przeciągnij plik(i) wyciągu z banku (PDF, CSV lub MT940) na `run.bat`,
   - albo w oknie „➕ Dodaj wyciągi…” (można zaznaczyć kilka naraz),
   - albo skopiuj historię ze strony banku, z aplikacji, z SMS-a czy z Excela i wklej przez „Wklej…”.
   MUZ sam rozpoznaje format banku (i zapamiętuje go pod nazwą banku), daty, kwoty, opłaty stałe i ich kategorie, dzień wypłaty i debet. Inflację pobiera sam z GUS.
3. **Czytaj zakładkę „Co teraz”**: ile zarezerwować na opłaty do wypłaty, ile masz na życie dziennie, ile odłożyć, co nadpłacić — i lista spraw do załatwienia z zyskiem rocznie i terminem: podwyżki ponad inflację, kilka umów tego samego rodzaju (np. dwóch operatorów), koszt długu (odsetki, prowizje), opłata za konto, płatności odroczone.
4. **Sprawa = jeden klik**: „Karta: co powiedzieć (PDF)” — gotowa rozmowa z celem ceny i granicą zgody; „Pismo do wydruku” — gotowe pismo; po wszystkim „✓ Załatwione” albo „✗ Nie udało się”. MUZ pamięta wynik i następnym razem proponuje kolejny krok (np. zmianę oferty albo wypowiedzenie).

Wyciągi PDF: MUZ czyta PDF z tekstem (taki, w którym da się zaznaczyć tekst myszką) — i tabele, i zwykłe listy; sam rozpoznaje, która kwota to saldo. PDF z hasłem: okno zapyta o hasło raz i go nie zapisuje. Skanu (zdjęcia kartki) nie przeczyta — wtedy pobierz w banku historię jako PDF albo CSV.

Jedyne pole do wpisania: **„Saldo teraz”** — tylko gdy wyciąg jest starszy niż kilka dni. Imię i adres do pism wpisujesz raz (MUZ zapyta przy pierwszym piśmie). Jeśli MUZ źle rozpoznał kategorię opłaty — zakładka „Opłaty stałe”, zaznacz i wybierz z listy.

Nowe wyciągi wrzucasz do folderu `wyciagi/` (przycisk „Folder wyciągów”) — przy każdym otwarciu okno liczy wszystko od nowa. Wyniki (PDF-y, lista dla Excela) są w `wyniki/`. MUZ niczego nie wysyła i nie przenosi pieniędzy.

## Czy MUZ działa? Wyniki badań

Trzy pre-rejestrowane testy (każdy zamrożony przed uruchomieniem, uruchomiony raz). Pełny opis: [docs/BADANIA.md](docs/BADANIA.md).

**Symulacja zamkniętej pętli (MUZ-SIM v0.1).** 400 zadłużonych gospodarstw, 36 miesięcy dzień po dniu: wypłaty przesuwane na następny miesiąc, co 2 tygodnie i freelance, inflacja osobna dla każdej kategorii (energia 30%, jedzenie 15%), rozliczenia energii, awarie, przerwy w pracy. „Na prostej” = dług spłacony, zapas na miesiąc opłat, zero dni na debecie przez ostatnie pół roku.

| Zarządca | na prostej |
|---|---|
| typowa aplikacja bankowa (limit z poprzedniego miesiąca kalendarzowego) | **0,3%** |
| bez zarządcy | 1% |
| najlepszy standard (koperty przy wpływie, styl YNAB) | 55,5% |
| **MUZ** | **60,8%** (+5,2 pkt, 95% CI +2,8…+7,7) |
| granica: zarządca znający przyszłość | 78,7% |

Z zasad TIMDR pomagają odniesienie (CPI każdej kategorii, +4,3 pkt) i zegar wpływu (+3,7 pkt); fundusz na wybuchy wydatków nic nie daje przy długu 20%. Kontrola bez zakłóceń: MUZ = standard. Deficyt strukturalny: MUZ 3,7% — nie tworzy pieniędzy. Symulację napisał autor badania: wynik pokazuje, że mechanizm działa, nie jak często prawdziwe gospodarstwa żyją w takich warunkach.

**Dane rzeczywiste (PKDD'99, czeski bank, zanonimizowane; prognoza złego kredytu).** P1: odniesienie do dochodu **przegrywa** z klasyką (AUC 0,87 vs 0,94) — wycina poziom kwot, który przy wypłacalności jest celem. P2: odniesienie do raty — remis z klasyką (0,91 vs 0,94), bez przewagi. Wniosek dla MUZ: wypłacalność liczyć w kwotach wobec zobowiązań w ich kalendarzu; odniesienie do cen — do wykrywania zmian nawyków.

Odtworzenie symulacji (ok. 5 min):

```powershell
python -m muz badanie --n 400 --seed 20260929 --scen S0,S1,S2 --out wyniki/badanie_petla.json
```

Kod: [muz/badania/petla.py](muz/badania/petla.py) (kopia 1:1 zamrożonego pliku, sprawdzana testem). Zarządca „MUZ” w badaniu to model badawczy polityki — nie jest jeszcze przeniesiony do `muz/mini_ai` ani `prereg/muz_decision_*.json`.

## Wiersz poleceń (dla programistów)

Dwuklik na `run.bat` wystarcza; poniższe polecenia są dla automatyzacji i testów.

Z konsoli:

```powershell
pip install numpy
python -m muz run --in wyciag.csv --mapping mapowanie.json --out wyniki
python -m muz verify --log wyniki/audit.jsonl
```

Raport: `wyniki/raport_etap0.md`. Dane użytkownika (`*.csv`, `mapowanie.json`, `wyniki/`, `.muz_salt`) są w `.gitignore`.

### Dane: dowolny wyciąg CSV i własny CSV MUZ

Nikt z zewnątrz nie dopasowuje formatu — robi to MUZ lokalnie, po **zawartości** kolumn: daty (≥ 90% wierszy), kwota i saldo (saldo zmienia się dokładnie o kwotę), osobne kolumny obciążeń i uznań (wzajemnie się wykluczają), waluta, kontrahent i opis. Nazwy kolumn tylko rozstrzygają remisy. Po pierwszym imporcie format zapisuje się w `formaty.json` pod odciskiem nagłówka i **sam nadaje sobie nazwę** (z nazwy banku w preambule wyciągu, a gdy jej brak — z nazwy pliku). Następny wyciąg z tego banku wczytuje się bez pytań.

```powershell
python -m muz import --in wyciag_bank1.csv --in wyciag_bank2.csv   # -> wyniki/transakcje_muz.csv (jeden format)
python -m muz formaty                                              # zapamiętane formaty
python -m muz formaty --nazwa "historia" "Konto główne"            # zmiana nazwy
python -m muz szablon --out gotowka.csv                            # pusty CSV MUZ do ręcznych wpisów
```

**CSV MUZ** (`data;kwota;waluta;kontrahent;opis;kategoria;saldo;zrodlo;id`, separator `;`, przecinek dziesiętny, UTF-8 z BOM — otwiera się w polskim Excelu). Kwota ujemna = wydatek. Tu dopisuje się gotówkę i rachunki spoza banku; kategoria jest dowolna. Plik CSV MUZ można podać wszędzie tam, gdzie wyciąg (`--in`), także w oknie `run.bat`. Wyciągi PDF też (`--in wyciag.pdf`, wymaga `pip install pdfplumber`).

### Decyzje: co zrobić, ile i do kiedy

```powershell
python -m muz decyzje --in wyciag.csv --in gotowka.csv --profile profil.json --contracts umowy.json --out wyniki
```

Wynik `wyniki/decyzje.md` (w oknie `run.bat` — na górze raportu):

1. **Do następnej wypłaty** — reguła z badania MUZ-SIM: rezerwa na opłaty, które zejdą przed wypłatą (według ich kalendarza), kwota na życie na dzień i tydzień, ile odłożyć na fundusz wydatków nieregularnych i bufor, ile nadpłacić na najdroższy dług. Przy długu lub braku zapasu — 80% zwykłych wydatków (poniżej 75% gospodarstwa w symulacji się łamały). Saldo, oszczędności i długi — w `profil.json` (wzór: `profil_przyklad.json`).
2. **Karty działania dla umów** — gdy opłata rośnie istotnie ponad inflację: cel ceny (poprzednia), górna granica zgody (poprzednia + inflacja), plan B, termin (z okresu wypowiedzenia), co powiedzieć w dziale utrzymania klienta, na co się nie zgadzać, co zapisać. Negocjację prowadzisz Ty; pismo zamiast rozmowy przygotowuje `propose` (z Twoim zatwierdzeniem).

MUZ niczego nie wykonuje sam i nie przenosi pieniędzy.

## Uczenie mini-AI na pakietach budżetów

```powershell
python -m muz train
```

Generuje 600 syntetycznych budżetów gospodarstw domowych (kwintyle dochodu GUS 2024), uczy mini-AI jawnej polityki budżetowej z `prereg/muz_decision_v0.3.json` i rejestruje model w `modele/` (trwa kilka minut). Model działa tylko w trybie cienia: raport pokazuje, co by zaproponował, a plany tworzy ta sama polityka budżetowa zapisana jako reguły. Szczegóły i wyniki: [docs/IMPLEMENTACJA.md, sekcja 11](docs/IMPLEMENTACJA.md#11-pakiety-budżetów-syntetycznych-i-uczenie-mini-ai).

## Testy

```powershell
pip install pytest cryptography reportlab
python -m pytest
```

Sygnały TIMDR są w tym systemie diagnostyką obok prostej reguły „r/r ponad CPI + 5 pp”. Testy P1/P2 na danych publicznych i symulacja MUZ-SIM są opisane w [docs/BADANIA.md](docs/BADANIA.md); polityka z badania nie zastąpiła jeszcze reguł w `prereg/`.
