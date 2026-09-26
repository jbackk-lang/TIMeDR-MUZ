# TIMeDR-MUZ — opis implementacyjny (prototyp etapów 0–1)

Ten dokument opisuje działający prototyp zgodny z dokumentem „TIMeDR-MUZ — architektura lokalnego agenta wykonawczego”. Definicje, progi, poziomy L0–L3 i ograniczenia pochodzą z dokumentu. Tam, gdzie dokument nie podaje liczby lub reguły potrzebnej w kodzie, wartość jest zapisana w zamrożonym pliku w `prereg/` i opisana w sekcji „Wartości ustalone w prototypie”.

Stan: 72 testy przechodzą (`python -m pytest`). Prototyp działa w całości lokalnie; sieć ma tylko adapter (odczyt NBP/GUS, lista `allowed_hosts`) i wykonawca formularzy (host z przepisu). Żaden wykonawca nie przenosi pieniędzy.

## 1. Architektura

| Warstwa | Pakiet | Wejście → wyjście | Sieć |
| --- | --- | --- | --- |
| TIMDR-Finance-Core: adapter GSF → LSF → PL | `muz/adapter` | CSV / MT940 / NBP / GUS / umowy → `LSFRecord`, `Stream` | tylko adapter, tylko odczyt: `api.nbp.pl`, `bdl.stat.gov.pl` |
| TIMDR-Finance-Core: sygnały M/S | `muz/signals` | `Stream` → `SignalFrame` | brak (`no_network`) |
| TIMDR-Finance-Core: META-DYNAMICS | `muz/meta` | `SignalFrame` → `MetaState` (+ raport `meta_validator`) | brak |
| TIMDR-Finance-Core: fazy | `muz/phases` | `SignalFrame`, `MetaState` → `PhaseState` | brak |
| mini-AI TIMDR | `muz/mini_ai` | cechy (40) → `ActionProposal` | brak |
| TIMDR-AI-Core | `muz/ai_core` | `ActionProposal` → `VerifiedClaim`; rejestr modeli | brak |
| TIMeDR-MUZ | `muz/executor` | `VerifiedClaim` → `ActionPlan` → `Approval` → `ExecutionReceipt` | tylko wykonawca formularzy, host z przepisu |
| Dziennik i magazyn | `muz/audit` | każdy krok → JSONL z łańcuchem hashy; AES-256-GCM | brak |

Wspólne elementy są w `muz/core`: koperta komunikatów i 10 schematów (`messages.py`), protokoły `Stage` i `Executor` (`stage.py`), straż sieci (`netguard.py`) oraz kontrola plików wendorowanych (`common.py`).

W prototypie warstwy działają w jednym procesie, a brak sieci w warstwach decyzyjnych wymusza `no_network()` (podmiana funkcji gniazd; test `test_no_network_blocks_sockets`). Dokument zakłada docelowo osobne procesy; to jest następny krok, nie część prototypu.

## 2. Struktura repozytorium

```text
TIMeDR-MUZ/
  muz/
    core/         messages.py (koperta, 10 schematów), stage.py (Stage, Executor), netguard.py, common.py
    adapter/      csv_import.py, mt940.py, nbp.py, gus.py, contracts.py
    signals/      anomalia, defekt, rezonans M (topologic v0.3), skręt (regresja na 3 próbkach)
    meta/         MetaState budżetu (Λ, τ, ρ, J, M), walidacja meta_validator
    phases/       reguły faz, histereza, kalibracja percentyli, twarda reguła salda
    mini_ai/      features.py (40 cech), mlp.py (NumPy), policy.py (reguły, bramka fazy, wstrzymanie)
    ai_core/      claims.py (Claim Graph), registry.py (TIMDRProtocol), validation.py (P1/P2)
    executor/     gate.py (plan, L0–L3, Ed25519, PIN), letters.py, forms.py, qr.py, ics.py, signing.py, ed25519_ref.py
    audit/        dziennik JSONL z łańcuchem hashy, store.py (AES-256-GCM)
    _vendor/      topologic, meta_state, math_formalism, ai_core + VENDOR.lock.json
    pipeline.py   run() etap 0, run_stream(), propose() etap 1
    report.py     raport etapu 0
    __main__.py   CLI: run, propose, keygen, setpin, approve, execute, verify
  prereg/         muz_thresholds_v0.1.json, muz_decision_v0.1.json, FROZEN.json
  templates/      szablony pism v0.1 (prośba o obniżkę, wypowiedzenie, wniosek o zmianę planu)
  docs/           IMPLEMENTACJA.md, przyklady_komunikatow.json
  scripts/        przyklady_komunikatow.py
  tests/          72 testy + synth.py (dane syntetyczne)
```

## 3. Prototyp kodu — najważniejsze elementy

**Protokoły modułów** (`muz/core/stage.py`), dokładnie jak w dokumencie:

```python
class Stage(Protocol):
    schema_in: str            # np. "muz.stream/1"
    schema_out: str           # np. "muz.signal_frame/1"
    config_sha256: str        # hash zamrożonych progów lub wag
    def run(self, msgs: list[Envelope]) -> list[Envelope]: ...

class Executor(Protocol):
    level: Literal["L0", "L1", "L2", "L3"]
    allowed_hosts: frozenset[str]
    def dry_run(self, plan: dict) -> dict: ...
    def execute(self, plan: dict, approval: dict) -> dict: ...
```

**Koperta** (`muz/core/messages.py`): `schema`, `id`, `created_at`, `producer` (moduł i hash jego kodu), `parents`, `payload`, `payload_sha256` z kanonicznego JSON. `verify()` odrzuca komunikat o zmienionej treści, a `validate_payload()` odrzuca nieznany numer główny schematu zamiast go zgadywać. Prawdziwe przykłady wszystkich 10 komunikatów (`LSFRecord`, `Stream`, `SignalFrame`, `MetaState`, `PhaseState`, `ActionProposal`, `VerifiedClaim`, `ActionPlan`, `Approval`, `ExecutionReceipt`) z przebiegu na danych syntetycznych są w `docs/przyklady_komunikatow.json`.

**Przebieg jednego strumienia** (`muz/pipeline.py::run_stream`): `Stream` → `SignalFrame` → `MetaState` → `PhaseState` → cechy → `ActionProposal` → `VerifiedClaim` → `ActionPlan`. Wszystko od sygnałów do weryfikacji działa pod `no_network()`, a każdy komunikat wskazuje rodzica. Plan powstaje tylko z twierdzenia SUPPORTED i akcji innej niż „zostawić”.

**mini-MLP** (`muz/mini_ai/mlp.py`): 42 → 32 → 16 → 4 (od decyzji v0.2: 40 cech z dokumentu + udział strumienia w dochodzie + roczny koszt podwyżki względem dochodu), ReLU, softmax, Adam, L2, skalowanie temperatury, ważność permutacyjna, zapis `.npz` z hashem. Regresja logistyczna (baseline z dokumentu) to ta sama klasa z `sizes=(42, 4)`. Warianty CNN 1D i TinyTransformer nie są w prototypie; dokument traktuje je jako badawcze.

**Adapter** (`muz/adapter`): CSV z bankowości (UTF-8/CP1250, separator rozpoznawany, pomijanie wierszy przed nagłówkiem, przecinek dziesiętny, kwoty w groszach), MT940 (`:61:`, `:86:` z podpolami `~20–25`, `~32–33`, `~38`), NBP (tabela A, kurs z dnia transakcji, do 7 dni wstecz), GUS (plik CSV albo zapytanie BDL pod `bdl.stat.gov.pl`; identyfikatora zmiennej prototyp nie zgaduje), umowy (tylko pola potwierdzone przez użytkownika). IBAN jest zapisywany jako hash z lokalną solą.

## 4. Przepływ danych

1. **Pobranie** — `prepare()`: import, deduplikacja (klucz: data, kwota, kontrahent, hash opisu; duplikaty w jednym pliku zostają), strumienie miesięczne, dołączenie umów.
2. **Sygnały** — anomalia (mediana ± 3·MAD, pełne okno 12 próbek), defekt (zmiana względna > 10%), skręt (zmiana znaku nachylenia regresji na 3 próbkach, gdy |nachylenie| > 5% poziomu), rezonans M (≥ 3 strumienie ze zdarzeniem w miesiącu), baseline „r/r > CPI + 5 pp”.
3. **META-DYNAMICS** — Λ, τ, ρ, J i `M` dla budżetu; od progów v0.2 J = korelacja Spearmana zmian kosztów r/r z CPI r/r (12 miesięcy, zakres −1…1), a nachylenie regresji zostaje w raporcie tylko opisowo; brak CPI daje NaN, nie zero; raport `meta_validator` z hashem w `MetaState`.
4. **Faza** — reguły z tabeli dokumentu, histereza (wyjście po 2 okresach), percentyle z pierwszej połowy historii, INCONCLUSIVE przy < 24 miesiącach albo zapadniętym percentylu, twarda reguła salda.
5. **Propozycja** — polityka regułowa (brak etykiet) albo MLP z rejestru; bramka fazy; wstrzymanie poniżej 0,6.
6. **Weryfikacja** — `verify_proposal()`: rekordy źródłowe (hashe surowych transakcji, CPI, umowa), sprzeczność, komplet danych dla „anulować”, świeżość 7 dni, zakazane twierdzenia; renderer deterministyczny; parafraza tylko przez `gate_candidate`.
7. **Bramka** — `make_plan()` (plan_sha256), `approve()` (podpis Ed25519, ważność 15 minut, PIN dla L2), `verify_approval()` po stronie wykonawcy.
8. **Wykonanie** — wykonawca sprawdza podpis, hash planu, poziom i `allowed_hosts`.
9. **Pokwitowanie** — `ExecutionReceipt` z hashami dowodów trafia do dziennika.

CLI: `run` (etap 0, raport), `propose` (kolejka planów), `keygen`, `setpin`, `approve`, `execute`, `verify`, `train` (uczenie mini-AI na pakietach budżetów, sekcja 11).

## 5. Testy

| Plik | Co sprawdza |
| --- | --- |
| `test_protocol.py` | zamrożone pliki (zmiana progu → odmowa), zmieniony plik wendorowany → odmowa, deterministyczny odcisk prerejestracji, `run_controls` (kontrola pozytywna i negatywna), brak kontroli nigdy nie przechodzi, `run_test` (INCONCLUSIVE / SUPPORTED / NOT_SUPPORTED), Bonferroni, regresja P1: sygnał lepszy od baseline → SUPPORTED, sygnał równy baseline → NOT_SUPPORTED, kierunek przeciwny nie przechodzi, reguła wyboru modelu |
| `test_adapter.py` | CP1250, preambuła, przecinek dziesiętny, hash IBAN, normalizacja kontrahentów, deduplikacja, strumienie, MT940, umowy potwierdzone, NBP z weekendem, GUS tylko przez dozwolony host |
| `test_signals_meta_phases.py` | defekt przy podwyżce, anomalia przy podwójnym rachunku, rezonans M przy indeksacji, przyczynowość (przyszłość nie zmienia przeszłości), zakresy META, J z CPI, histereza, kalibracja (krótka historia, zapadnięty percentyl, tylko pierwsza połowa), twarda reguła salda, skręt |
| `test_mini_ai.py` | 42 cechy, MLP uczy się i zapis/odczyt z hashem, regresja logistyczna, ważność permutacyjna, faza stabilna bez propozycji, polityka regułowa, wstrzymanie < 0,6, bramka fazy, rejestr ładuje tylko wagi SUPPORTED |
| `test_ai_core_claims.py` | SUPPORTED z dowodami, stare dane → INCONCLUSIVE, zmiana uzasadniona → REJECTED, „anulować” bez okresu wypowiedzenia → INCONCLUSIVE, bramka parafrazy |
| `test_executor.py` | wektor RFC 8032 i zgodność z `cryptography`, plan tylko z SUPPORTED, podpis i manipulacja treścią, wygaśnięcie po 15 minutach, odrzucenie, PIN dla L2, ICS bez zatwierdzenia, PDF i .eml, standard QR ZBP (także przykład z rekomendacji), QR jako L3, formularz: podgląd bez wysyłki, wysyłka po zatwierdzeniu, host spoza listy |
| `test_security.py` | brak sieci, `check_host`, dziennik wykrywa zmianę i usunięcie wpisu, AES-256-GCM i manipulacja szyfrogramem |
| `test_messages.py` | 10 schematów, koperta, rodzice, manipulacja treścią, nieznana wersja |
| `test_sim_train.py` | udziały GUS sumują się do 100, generator deterministyczny, dochód rośnie z kwintylem, istotność podwyżki zależy od dochodu, reguły nauczyciela wg kategorii, 42 cechy bez fazy stabilnej, rejestracja z flagą `synthetic` i odmowa użycia do planów, sekcja cienia w raporcie |
| `test_pipeline_e2e.py` | raport etapu 0 i dziennik; pełny przepływ do pokwitowania na strumieniu z podwyżką 89 → 119 zł |

Wszystkie testy działają na danych syntetycznych (`tests/synth.py`). Test P1 na danych syntetycznych sprawdza mechanikę testu, a nie tezę, że sygnały TIMDR pomagają w finansach. Tę tezę rozstrzyga dopiero bramka P1 na historii użytkownika.

## 6. Wykonawcy

| Wykonawca | Poziom | Co robi | Zależności |
| --- | --- | --- | --- |
| `ICSExecutor` | L0 | plik `.ics` z terminem i przypomnieniem 7 dni wcześniej, bez zatwierdzenia | brak |
| `LetterExecutor` | L1 (prośba), L2 (wypowiedzenie, wniosek o zmianę) | PDF z wersjonowanego szablonu + szkic `.eml` w folderze nadawczym | `reportlab`, czcionka TTF z polskimi znakami |
| `FormExecutor` | L2 | przepis pól dostawcy, logowanie użytkownika w widocznym oknie, podgląd bez wysyłki, wysyłka po zatwierdzeniu, zrzuty przed i po | `playwright` (opcjonalnie) |
| `QRTransferExecutor` | L3 | dane przelewu w standardzie ZBP 2D; przelew i SCA w aplikacji banku | `segno` dla obrazu (opcjonalnie) |

Format QR: `NIP|PL|NRB|KWOTA|ODBIORCA|TYTUŁ|||`, kwota w groszach na 6 cyfrach (maks. 9999,99 zł), odbiorca do 20 znaków, tytuł do 32, całość do 160 znaków, UTF-8, korekcja błędów L ([rekomendacja ZBP 2D](https://zbp.pl/getmedia/1d7fef90-d193-4a2d-a1c3-ffdf1b0e0649/2013-12-03_-_Rekomendacja_-_Standard_2D)). Numer rachunku jest sprawdzany sumą kontrolną IBAN.

## 7. Bezpieczeństwo

- **Podpis Ed25519** — `executor/signing.py` używa `cryptography`; gdy biblioteka jest niedostępna (np. zablokowana przez Device Guard), działa implementacja RFC 8032 w czystym Pythonie (`ed25519_ref.py`), sprawdzona wektorem z RFC i porównaniem z `cryptography`. Podpisywane jest `{plan_sha256, decision, expires_at}`.
- **allowed_hosts** — każdy wykonawca i adapter deklaruje listę; `check_host()` wymaga `https` i dokładnej nazwy hosta.
- **Brak sieci w warstwach decyzyjnych** — `no_network()` wokół sygnałów, META, faz, mini-AI i weryfikacji.
- **AES-256-GCM** — `audit/store.py` (ten sam prymityw co Helix-Lock); bez `cryptography` magazyn odmawia zapisu jawnym tekstem.
- **Dziennik JSONL z łańcuchem hashy** — `audit.append()`, `audit.verify()`, `export_anchor()` do wyniesienia hasha poza urządzenie.
- **PIN dla L2** — `hashlib.scrypt` z biblioteki standardowej.

Ograniczenie prototypu: klucz bramki i klucz magazynu są plikami z uprawnieniami 0600, a nie wpisami w magazynie kluczy systemu (DPAPI, Keychain, Android Keystore), jak zakłada dokument.

## 8. Integracja z repozytoriami TIMDR

Pliki są wendorowane bez zmian do `muz/_vendor/`, a `VENDOR.lock.json` zapisuje repozytorium, commit i SHA-256 każdego pliku. `verify_vendor()` sprawdza hashe przy każdym przebiegu i przy niezgodności zatrzymuje pracę (`INCONCLUSIVE_VENDOR_CHANGED`).

| Źródło | Commit | Pliki | Użycie w MUZ |
| --- | --- | --- | --- |
| topologic v0.3 | `ac2f4f5` | cały pakiet | `anomaly`, `defect(method="relative")`, `resonance_m` |
| TIMDR-META-DYNAMICS | `c1897b2` | `core_meta/meta_state.py` | `MetaState`, `delta()` jako operator `M` |
| TIMDR-Math-Formalism | `689452c` | `pipeline.py`, `meta_validator.py` | `mann_whitney_test` (backend NumPy), `run_controls`, `bonferroni_correct`, `validate_meta_series` |
| TIMDR-AI-Core | `2f27e00` | `timdr_ai_core.py`, `claim_graph_gate.py` | `TIMDRProtocol`, `Hypothesis`, `ControlResult`, `TestEvidence`, `Decision`, `render`, `gate_candidate` |

Nie przejęto warstwy językowej TIMDR-AI-Core (LoRA/Qwen), bo opiera się na PyTorch. Progi i reguły decyzyjne ładują się tylko wtedy, gdy ich hash zgadza się z `prereg/FROZEN.json` (`INCONCLUSIVE_THRESHOLDS_CHANGED`), a wagi mini-AI tylko przy węźle SUPPORTED w rejestrze (`INCONCLUSIVE_NOT_SUPPORTED`).

## 9. Wartości ustalone w prototypie

Dokument nie podaje tych wartości; są zamrożone w `prereg/` i wymagają pre-rejestracji przed użyciem w bramkach:

- okno anomalii: wymagane pełne 12 próbek (krótsza historia dawała fałszywe alarmy na danych syntetycznych),
- próg skrętu: 5% mediany poziomu strumienia,
- progi ρ domyślne przy INCONCLUSIVE: 0,25 (przejściowa) i 0,5 (krytyczna),
- polityka regułowa (`muz_decision_v0.1.json`) i margines wyboru modelu 0,05 w log-loss,
- 40 cech mini-AI (lista w `muz/mini_ai/features.py`),
- definicja kanału J: v0.1 nachylenie regresji (bez ograniczeń, walidator META zgłosił wartości poza [0,1]); v0.2 korelacja Spearmana w [−1, 1]. Obie wersje progów są zamrożone w `FROZEN.json`, aktywna jest v0.2.

## 10. Bez technologii Meta

Zależności: NumPy (wymagane), `cryptography`, `reportlab`, `segno`, `playwright`, `pytest` (opcjonalne). Nie ma PyTorch, LLaMA, ONNX, FAISS, React, GraphQL, Zstandard ani RocksDB. Magazyn danych to pliki szyfrowane i JSONL, bez RocksDB.

## 11. Pakiety budżetów syntetycznych i uczenie mini-AI

Na etapie 0 nie ma etykiet (decyzji użytkownika), więc mini-AI uczy się na **pakietach budżetów**: syntetycznych gospodarstwach domowych zbudowanych na danych GUS, z jawnym nauczycielem zamrożonym w `prereg/muz_decision_v0.2.json`.

**Generator** (`muz/sim/generator.py`, dane w `muz/sim/gus_bgd.py`). Źródło: GUS, Budżety gospodarstw domowych 2024 — dochód rozporządzalny i wydatki na osobę w kwintylach (Q1 1151/1302 zł … Q5 6071/3012 zł), struktura wydatków COICOP, udział żywności i mieszkania malejący z dochodem (Q1 50,7%, Q5 36,9%). Pakiet = kwintyl, liczba osób (1–4), 32 miesiące rekordów LSF (wynagrodzenie, czynsz, energia, telekom, media, subskrypcje, ubezpieczenie, kredyt, zakupy spożywcze jako szum) i potwierdzone umowy. Zmiany cen powstają przez zdarzenia: indeksacja styczniowa o CPI GUS + szum, podwyżki dostawcy 10–40%, koniec promocji, podwójny rachunek za energię. 40% umów (poza czynszem i kredytem — te zawsze) jest na czas nieokreślony. Pakiet jest deterministyczny dla ziarna.

**Nauczyciel** (`muz/sim/teacher.py`) używa tylko tego, co widzi model: kwota teraz i 12 miesięcy temu, CPI r/r, umowa, dochód. „Zostawić”, jeśli kategoria jest nienegocjowalna (czynsz, inne) albo podwyżka nie jest jednocześnie powyżej CPI + 5 pp i istotna (roczny koszt podwyżki ≥ 3% miesięcznego dochodu). Inaczej: brak wcześniejszych negocjacji albo kredyt → „negocjować”; subskrypcja → „anulować”; telekom, media, energia, ubezpieczenie → „zmienić”. Ta sama podwyżka jest więc istotna w Q1 i nieistotna w Q5.

**Uczenie** (`python -m muz train`, `muz/mini_ai/train.py`). Próbki to miesiące poza fazą stabilną (od 13. miesiąca), 42 cechy. Podział 70/15/15 po gospodarstwach (test na innych gospodarstwach niż trening). Kontrolki: pozytywna (model uczy się podłożonej reguły „defekt” ≥ 0,95) i negatywna (na przetasowanych etykietach nie przekracza klasy większościowej + 0,02). MLP i regresja logistyczna, wybór po log-loss na walidacji z marginesem 0,05, test permutacyjny (200 permutacji). Werdykt wydaje `TIMDRProtocol`; węzeł w `modele/rejestr.json` ma `synthetic: true`.

**Wynik (600 pakietów, ziarno 0):** wybrany MLP (log-loss walidacji 0,020 vs 0,073), trafność na teście 0,993 przy klasie większościowej 0,747 i polityce regułowej 0,424, p = 0,005 (minimum przy 200 permutacjach), trafność 0,987–1,0 w każdym kwintylu, „anulować” 50/51. Werdykt SUPPORTED (syntetyczny). Karta modelu: `modele/mini_ai_syntetyczny_v0.2/karta.json`.

**Skrót wykryty poza rozkładem.** Pierwsza wersja generatora dawała umowy bez daty końca tylko dla czynszu i kredytu. Model miał 99,6% na teście syntetycznym, ale na przykładowym wyciągu (`dane/przyklad_wyciag_30mies.csv`, umowy testowe bez daty końca) zgadzał się z nauczycielem tylko w 18 z 31 próbek: nauczył się „brak daty końca → zostawić”. Po dodaniu umów na czas nieokreślony we wszystkich kategoriach zgodność wynosi 31/31. Test regresyjny: `test_generator_has_indefinite_contracts_outside_rent`.

**Tryb cienia.** Model z flagą `synthetic` ładuje się tylko przez `require_supported(..., allow_synthetic=True)`. Raport etapu 0 ma sekcję „Cień mini-AI”, w której obok polityki regułowej widać, co zaproponowałby model. Plany wykonania nadal tworzy polityka regułowa; bez `allow_synthetic` rejestr zwraca `INCONCLUSIVE_SYNTHETIC_ONLY`.

**Czego to nie dowodzi.** Model odtwarza jawną regułę nauczyciela na danych, które sami wygenerowaliśmy. Nie jest to dowód, że jego decyzje są dobre dla prawdziwego budżetu. Do tworzenia planów potrzebny jest test P2 na decyzjach użytkownika.
