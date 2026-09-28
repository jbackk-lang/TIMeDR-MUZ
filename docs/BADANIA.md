# Badania MUZ

Wszystkie testy według protokołu GIA-TIMDR: pre-rejestracja w commicie przed uruchomieniem, jedno uruchomienie,
ujawnione iteracje rozwojowe, wyniki negatywne zapisane na równi z pozytywnymi. Żadnych danych prywatnych.

## 1. MUZ-SIM v0.1 — symulacja zamkniętej pętli budżetu

Pytanie: czy zarządca MUZ wyprowadza zadłużone gospodarstwo „na prostą” w warunkach, w których typowe programy
budżetowe zawodzą, i które zasady TIMDR to robią.

- Pre-rejestracja: [PREREG_MUZ_SIM_v0_1.md](badania/PREREG_MUZ_SIM_v0_1.md) (GIA-TIMDR c1d6680).
- Wynik: [RESULT_MUZ_SIM_v0.1.md](badania/RESULT_MUZ_SIM_v0.1.md), dane: [RESULT_MUZ_SIM_v0_1.json](badania/RESULT_MUZ_SIM_v0_1.json).
- Kod: [muz/badania/petla.py](../muz/badania/petla.py), [muz/badania/petla_run.py](../muz/badania/petla_run.py);
  `python -m muz badanie`. Test `tests/test_badania_petla.py` pilnuje, że plik jest identyczny z zamrożonym.

| Hipoteza (scenariusz trudny S1) | Δ „na prostej” | 95% CI | Werdykt |
|---|---|---|---|
| H1: MUZ > koperty (najlepszy standard) | +5,2 pkt | +2,8…+7,7 | SUPPORTED |
| H1b: MUZ > aplikacja bankowa | +60,5 pkt | +55,5…+65,5 | SUPPORTED |
| H2 zegar: wpływ > 1. dzień miesiąca | +3,7 pkt | +1,0…+6,5 | SUPPORTED |
| H3 odniesienie: CPI per kategoria > jeden CPI | +4,3 pkt | +2,2…+6,5 | SUPPORTED |
| H4 reżim zdarzeń: fundusz na wybuchy | +0,7 pkt | −1,0…+2,5 | MIXED |
| H5 nie głodzi: konsumpcja vs koperty | −1,4 pkt | granica −3 | SUPPORTED |
| H6 kontrola S0: MUZ = koperty | 0 | — | zgodna |
| H7 deficyt strukturalny S2: MUZ ≤ 10% | 3,7% | — | potwierdzona |

Co z tego wynika: większość pracy robi strategia kopertowa (przydział przy wpływie, rezerwa zobowiązań do
następnego wpływu, cięcie tuż nad progiem zmęczenia) — aplikacja bankowa 0,3% → koperty 55,5%. Zasady TIMDR
dokładają +5 pkt. Do granicy (zarządca znający przyszłość, 78,7%) brakuje 18 pkt.

Ograniczenia: symulacja i zagrożenia są autorskie; MUZ strojony w dwóch punktach na ziarnie rozwojowym
(ujawnione); model zmęczenia (próg 0,75) wspólny dla koperty i MUZ.

## 2. P1 i P2 — dane rzeczywiste PKDD'99 (prognoza złego kredytu)

| Test | Wynik | Werdykt |
|---|---|---|
| [P1](https://github.com/jbackk-lang/GIA-TIMDR/blob/main/docs/geometry/RESULT_MUZ_P1_BERKA_v0.1.md): zegar od wypłaty + odniesienie do dochodu vs klasyka kalendarzowa | AUC 0,87 vs 0,94 | NOT SUPPORTED (H1–H4) |
| [P2](https://github.com/jbackk-lang/GIA-TIMDR/blob/main/docs/geometry/RESULT_MUZ_P2_BERKA_v0.1.md): odniesienie do raty | AUC 0,91 vs 0,94; razem 0,93 | H1 NOT, H2 MIXED, remis z klasyką |

Lekcja: wzorzec odniesienia ma znosić zakłócenie (ceny, skalę), nie wielkość, o którą pyta decyzja. Przy
wypłacalności poziom salda wobec zobowiązań jest celem. Zbiór wyczerpany (część testowa użyta 2×).
Kod: GIA-TIMDR `core/muz_berka_p1.py`, `core/muz_p2.py`.

## 3. Co dalej (v0.2, nowa pre-rejestracja)

Margines nad progiem zmęczenia zależny od historii wybuchów; fundusz na wybuchy dopiero po spłacie drogiego
długu; przeniesienie polityki z badania do `prereg/muz_decision_v0.4.json` i trybu cienia.
