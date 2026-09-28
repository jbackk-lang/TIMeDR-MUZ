# PREREG MUZ-SIM v0.1: czy MUZ wyprowadza gospodarstwo na prostą tam, gdzie standardowe programy zawodzą

Stan: **zamrożone przed uruchomieniem na ziarnie testowym**. Jedno uruchomienie.
Kod: `core/muz_sim.py`, `core/muz_sim_run.py` (sha256 w commicie). Test: `python core/muz_sim_run.py 400 20260929 S0,S1,S2`.

## Pytanie

Na danych rzeczywistych (P1, P2) wynik zależał od 32 złych kredytów, więc był w dużej mierze kwestią losu. Tu
pytanie jest inne: czy zarządca MUZ, sterując budżetem w zamkniętej pętli, doprowadza zadłużone gospodarstwo
do stanu „na prostej” w warunkach, w których typowe programy budżetowe nie dają rady — i które z zasad TIMDR
(zegar, odniesienie, reżim zdarzeń) to robią.

**Czego ten test nie rozstrzyga:** symulację napisałem sam, łącznie z zagrożeniami, na które MUZ ma odpowiedź.
Test sprawdza, czy mechanizm działa i ile daje każda zasada, gdy te zagrożenia występują — nie, czy prawdziwe
gospodarstwa w nich żyją. Obrona przed samooszukiwaniem: warunek kontrolny S0, przewidziana porażka S2,
ablacje, odniesienie „Asceta” (górna granica wykonalności) i silny standardowy konkurent (Koperty).

## Symulacja (dzień po dniu, 36 miesięcy, 2023–2025; wspólne liczby losowe dla wszystkich zarządców)

- Dochód: wypłata 10. dnia / koniec miesiąca z przesunięciem na poniedziałek (przechodzi na następny miesiąc) /
  co 14 dni / freelance (połowa stała + zlecenia Poissona). Coroczna podwyżka w losowym miesiącu = inflacja
  z 12 miesięcy (pełna indeksacja z opóźnieniem). Przerwa w pracy 61 dni u 30% gospodarstw.
- Zobowiązania: czynsz (5. dnia), zaliczka na energię (20. dnia, stała w roku) + rozliczenie w marcu,
  ubezpieczenie roczne, awarie (Poisson 1,2/rok, ~0,35 dochodu), karta 20%/rok z ratą min. 3% (25. dnia),
  debet 25%/rok. Dług początkowy 0,3–1,5 dochodu miesięcznego; wydatki startowe 1,03 dochodu.
- Inflacja: mieszkanie 8%, energia 30%, jedzenie 15%, inne 4% rocznie; różne koszyki gospodarstw.
- Zachowanie: zarządca daje przydział na okres; gospodarstwo wydaje go z przodu okresu, z poślizgiem.
  Zmęczenie: przydział < 0,85 potrzeby narasta; po przekroczeniu progu wybuch (1,2 × potrzeby przez okres).

Scenariusze: **S0** kontrola (wypłata 10. dnia, bez inflacji, bez zdarzeń, bez przerw); **S1** trudny (wszystko
powyżej, mieszanka typów wypłat 25/30/25/20%); **S2** deficyt strukturalny (czynsz 55–60%, energia 12–15%,
dług 3 dochody) — nie da się wyjść.

## Zarządcy

- **Brak** — gospodarstwo wydaje, ile chce.
- **Bank** — typowa aplikacja bankowa: 1. dnia limit = wpływy − opłaty z poprzedniego miesiąca − 5%, nominalnie.
- **Koperty** — najsilniejszy standard (styl YNAB): przydział przy każdym wpływie, rezerwa zobowiązań do
  następnego wpływu, potrzeby indeksowane **jednym CPI**, fundusz na wydatki nieregularne = średnia z historii,
  bufor 1 miesiąc, tryb wychodzenia z długu (przydział 0,80 potrzeby, próg 0,75), nadwyżka na dług.
- **MUZ** — to samo, plus: odniesienie = **CPI każdej kategorii** (także przewidywanie rozliczenia energii),
  **reżim zdarzeń** (fundusz = 80. percentyl sum 90-dniowych wydatków nieregularnych — wybuchy, nie średnia).
  Zegar: przydział przy wpływie (jak Koperty).
- Ablacje: **MUZ_kal** (decyzje 1. dnia miesiąca), **MUZ_1cpi** (jeden CPI), **MUZ_bezD** (bez funduszu zdarzeń).
- **Asceta** — nie do zbudowania w praktyce: zna prawdziwą potrzebę i zdarzenia na 90 dni naprzód; mierzy,
  czy scenariusz jest wykonalny.

Wspólna wiedza Koperty i MUZ (uczciwość porównania): ten sam model zmęczenia (próg), ten sam tryb 0,80,
ten sam bufor, ta sama reguła spłaty. Różnią się tylko zasadami TIMDR (odniesienie, reżim zdarzeń).

## Miara

**„Na prostej”** na koniec: dług na karcie spłacony, saldo ≥ miesięczne opłaty stałe, zero dni na debecie
w ostatnich 180 dniach. Dodatkowo: dni na debecie, odsetki, konsumpcja realna / potrzeba (czy nie wygrywa
głodzeniem), liczba wybuchów. Różnice parami na tych samych gospodarstwach, bootstrap po gospodarstwach 2000×,
95% CI. Werdykt: dolna granica > 0 → SUPPORTED; różnica > 0 → MIXED; inaczej NOT SUPPORTED.

## Hipotezy (S1 — główny)

- **H1**: odsetek „na prostej” MUZ > Koperty.
- **H1b**: MUZ > Bank.
- **H2 (zegar)**: MUZ > MUZ_kal.
- **H3 (odniesienie)**: MUZ > MUZ_1cpi.
- **H4 (reżim zdarzeń)**: MUZ > MUZ_bezD.
- **H5 (nie głodzi)**: konsumpcja MUZ − Koperty, dolna granica CI > −0,03.
- **H6 (kontrola S0)**: MUZ ≡ Koperty z konstrukcji (bez inflacji i zdarzeń zasady nie mają czego robić);
  MUZ > Bank.
- **H7 (przewidziana porażka S2)**: MUZ „na prostej” ≤ 10%. MUZ nie tworzy pieniędzy.

## Rozwój (ziarno 1, 60 gospodarstw na scenariusz) — ujawnienie iteracji

1. Błąd kolejności: decyzja przed zaksięgowaniem wpływu tego dnia — poprawione (wpływ rano).
2. Oszczędności jako trwała koperta (wcześniej przejadane w następnym okresie) — wspólne dla Koperty i MUZ.
3. **Kalibracja wykonalności na Ascecie** (nie na MUZ): pierwsza wersja S1 była niewykonalna nawet dla Ascety
   (23%). Zmiany: dług 0,3–1,5 zamiast 0,5–2,5; podwyżka także w 1. roku; pełna indeksacja zamiast 0,7.
   Asceta po zmianie 0,88.
4. MUZ: usunięty bufor powiększany o zmienność dochodu liczoną w miesiącach kalendarzowych (sprzeczny z zegarem;
   przy przesuwanej wypłacie podwajał bufor). Tylko MUZ.
5. MUZ: fundusz zdarzeń = 80. percentyl sum 90-dniowych (wcześniej średnia + 75. percentyl pojedynczego zdarzenia,
   co blokowało za dużo gotówki przy długu 20%). Tylko MUZ.
6. Tryb wychodzenia z długu 0,80 — wspólny.
7. Fundusz zdarzeń liczony jako część bufora (bez podwójnej rezerwy) — wspólny.

Punkty 4–5 stroiły tylko MUZ na ziarnie rozwojowym — przewaga MUZ może być częściowo dopasowaniem do generatora.

Wynik rozwojowy po iteracjach (S1, 60 gosp.): Asceta 0,88, Bank 0,00, Koperty 0,53, **MUZ 0,63**, MUZ_kal 0,58,
MUZ_1cpi 0,53, MUZ_bezD 0,65. H1 +0,10 [+0,02; +0,20]; H3 +0,10 [+0,02; +0,20]; H2 +0,05 (MIXED); H4 −0,02
(NOT). S0: MUZ = Koperty 0,85, Bank 0,10. S2: wszyscy ≤ 0,03.

## Przewidywanie

H1b SUPPORTED (bank zawodzi całkowicie). H1 MIXED lub SUPPORTED (+0,05…+0,10). H3 SUPPORTED — główne źródło
przewagi: jeden CPI źle szacuje potrzeby przy różnych koszykach. H2 MIXED. **H4 NOT SUPPORTED** — fundusz
na wybuchy trzyma gotówkę, gdy dług kosztuje 20%. H5 SUPPORTED. H6, H7 zgodnie z konstrukcją.
