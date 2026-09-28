# RESULT MUZ-SIM v0.1: wyprowadzanie budżetu na prostą w trudnej symulacji

Pre-rejestracja: `PREREG_MUZ_SIM_v0_1.md` (commit c1d6680). Jedno uruchomienie:
`python core/muz_sim_run.py 400 20260929 S0,S1,S2`. JSON: `RESULT_MUZ_SIM_v0_1.json`.

## S1 — scenariusz trudny (400 gospodarstw, te same dla wszystkich zarządców)

| Zarządca | na prostej | dług / dochód | saldo / dochód | dni na debecie | konsumpcja / potrzeba | wybuchy |
|---|---|---|---|---|---|---|
| Brak | 1% | 0,49 | −3,0 | 822 | 1,05 | 0 |
| Bank (typowa aplikacja) | **0,3%** | 0,49 | −7,6 | 864 | 1,19 | 4,5 |
| Koperty (styl YNAB, najsilniejszy standard) | 55,5% | 0,13 | 1,1 | 349 | 0,91 | 0,35 |
| **MUZ** | **60,8%** | 0,10 | 1,4 | 336 | 0,90 | 0,53 |
| MUZ_kal (kalendarz) | 57,0% | 0,16 | 1,6 | 358 | 0,89 | 0,46 |
| MUZ_1cpi (jeden CPI) | 56,5% | 0,12 | 1,1 | 349 | 0,91 | 0,36 |
| MUZ_bezD (bez reżimu zdarzeń) | 60,0% | 0,11 | 1,4 | 335 | 0,90 | 0,48 |
| Asceta (zna przyszłość — granica) | 78,7% | 0,07 | 3,7 | 260 | 0,81 | 0 |

| Hipoteza | Δ (pkt proc.) | 95% CI | Werdykt | Przewidywanie |
|---|---|---|---|---|
| H1: MUZ > Koperty | +5,2 | [+2,8; +7,7] | **SUPPORTED** | MIXED/SUPPORTED ✓ |
| H1b: MUZ > Bank | +60,5 | [+55,5; +65,5] | **SUPPORTED** | ✓ |
| H2 zegar: MUZ > MUZ_kal | +3,7 | [+1,0; +6,5] | **SUPPORTED** | MIXED (lepiej niż przewidziane) |
| H3 odniesienie: MUZ > MUZ_1cpi | +4,3 | [+2,2; +6,5] | **SUPPORTED** | ✓ |
| H4 reżim zdarzeń: MUZ > MUZ_bezD | +0,7 | [−1,0; +2,5] | **MIXED** | NOT (lepiej niż przewidziane) |
| H5 nie głodzi: konsumpcja MUZ − Koperty | −1,4 | [−1,5; −1,3] | **SUPPORTED** (granica −3) | ✓ |

Według typu wypłaty (MUZ / Koperty / Bank): 10. dnia 59 / 50 / 1%; przesuwana 63 / 58 / 0%; co 14 dni
66 / 64 / 0%; freelance 54 / 49 / 0%. Przewaga MUZ we wszystkich czterech typach.

## S0 — kontrola i S2 — przewidziana porażka

- **S0** (stała wypłata, bez inflacji i zdarzeń): MUZ ≡ Koperty 78,2% (z konstrukcji — odniesienie i reżim
  zdarzeń nie mają czego robić), Bank 9,2%, Asceta 97,8%. H6 zgodna. Nieprzewidziane: MUZ_kal 66,0% — decyzja
  1. dnia miesiąca przy wypłacie 10. dnia kosztuje 12 pkt [+9; +16] nawet w najprostszym świecie.
- **S2** (deficyt strukturalny): MUZ 3,7%, Koperty 2,5%, Asceta 6,2%, Bank 0%. **H7 potwierdzona** — MUZ nie
  tworzy pieniędzy; różnice istotne, ale bez znaczenia praktycznego (łagodniejszy upadek: mniej odsetek i debetu).

## Interpretacja

1. **Standardowa aplikacja bankowa w trudnych warunkach nie wyprowadza nikogo** (0,3%, gorzej niż brak
   zarządcy — cięcia po miesiącu bez wpływu wywołują wybuchy). To potwierdza tezę zadania.
2. **Większość pracy robi kopertowa strategia, nie TIMDR**: przydział przy wpływie, rezerwa zobowiązań do
   następnego wpływu, tryb wychodzenia z długu tuż nad progiem zmęczenia — Bank 0% → Koperty 55%.
   Najsilniejszy standard (styl YNAB) już to ma.
3. **Zasady TIMDR dokładają +5 pkt ponad najlepszy standard** (55,5 → 60,8), głównie przez odniesienie
   (CPI każdej kategorii: +4,3) i zegar (+3,7). Reżim zdarzeń ≈ 0 — fundusz na wybuchy trzyma gotówkę,
   gdy dług kosztuje 20%.
4. Do granicy wykonalności (Asceta 79%) brakuje 18 pkt — to cena nieznajomości przyszłości i prawdziwej potrzeby.
5. MUZ ma więcej wybuchów niż Koperty (0,53 vs 0,35): dokładniejsza potrzeba częściej trzyma przydział przy
   progu 0,80. Do poprawy w v0.2 (margines zależny od historii wybuchów).

## Ograniczenia (ważne)

Symulację i zagrożenia zaprojektowałem sam; MUZ był strojony na ziarnie rozwojowym w dwóch punktach
(ujawnione w PREREG), Koperty nie. Kalibracja wykonalności na Ascecie. Model zmęczenia i próg 0,75 są
założeniem wspólnym dla Koperty i MUZ. Wynik mówi: **jeśli** gospodarstwo żyje w takich warunkach, zasady
TIMDR dają mierzalną, niewielką przewagę nad najlepszym standardem i ogromną nad typowym programem
bankowym. Nie mówi, jak często prawdziwe gospodarstwa w nich żyją.
