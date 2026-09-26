"""Parametry z GUS "Budzety gospodarstw domowych w 2024 r." (publikacja 2025).

Zrodla (odczytane 2026-09-26):
- GUS, "Sytuacja gospodarstw domowych w 2024 r. w swietle wynikow badania budzetow gospodarstw domowych":
  https://stat.gov.pl/files/gfx/portalinformacyjny/pl/defaultaktualnosci/5486/3/24/1/sytuacja_gospodarstw_domowych_w_2024_r._w_swietle_wynikow_badania_budzetow_gospodarstw_domowych.pdf
- potwierdzenie liczb ogolnych (3167 zl, 1878 zl) i udzialu zywnosci + mieszkania (50,7% / 36,9%): Interia, 2025.
Liczby sa na osobe, miesiecznie. Udzialy dotycza wydatkow ogolem.
"""

INCOME_PP = 3167            # przecietny dochod rozporzadzalny na osobe [zl/mies.]
EXPENDITURE_PP = 1878       # przecietne wydatki na osobe [zl/mies.]

# kwintyle (1 = najnizsze dochody): dochod rozporzadzalny i wydatki na osobe [zl/mies.]
QUINTILES = {
    1: {"income_pp": 1151, "expenditure_pp": 1302},
    2: {"income_pp": 2225, "expenditure_pp": 1417},
    3: {"income_pp": 2838, "expenditure_pp": 1659},
    4: {"income_pp": 3598, "expenditure_pp": 2021},
    5: {"income_pp": 6071, "expenditure_pp": 3012},
}

# struktura wydatkow ogolem (Polska, 2024) [%]
SHARES = {
    "zywnosc": 25.3, "alkohol_tyton": 2.5, "odziez": 3.8, "mieszkanie_energia": 18.8, "wyposazenie": 5.6,
    "zdrowie": 5.1, "transport": 10.7, "lacznosc": 3.9, "rekreacja_kultura": 6.9, "edukacja": 1.0,
    "restauracje_hotele": 5.3, "inne_towary_uslugi": 6.1,
}

# udzial zywnosci + mieszkania i nosnikow energii: kwintyl 1 i 5 (GUS); kwintyle 2-4 interpolowane liniowo
FOOD_HOUSING_Q1 = 50.7
FOOD_HOUSING_Q5 = 36.9


def food_housing_share(q: int) -> float:
    return FOOD_HOUSING_Q1 + (FOOD_HOUSING_Q5 - FOOD_HOUSING_Q1) * (q - 1) / 4.0


def category_shares(q: int) -> dict[str, float]:
    """Udzialy kategorii [%] dla kwintyla q: zywnosc+mieszkanie wg GUS dla kwintyla, reszta przeskalowana."""
    base_fh = SHARES["zywnosc"] + SHARES["mieszkanie_energia"]
    fh = food_housing_share(q)
    rest_total = sum(v for k, v in SHARES.items() if k not in ("zywnosc", "mieszkanie_energia"))
    scale_fh, scale_rest = fh / base_fh, (100.0 - fh) / rest_total
    return {k: v * (scale_fh if k in ("zywnosc", "mieszkanie_energia") else scale_rest) for k, v in SHARES.items()}
