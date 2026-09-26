"""timdr_formalism/meta_validator.py

Uniwersalny walidator formalizmu Lambda-tau-rho-J (TIMDR-META-DYNAMICS),
NIEZALEZNY od konkretnej domeny/implementacji MetaState -- dziala na
surowych szeregach liczbowych (Lambda/tau/rho/J per krok + magnitude/fazy
per krok M), nie importuje ZADNEJ klasy z TIMDR-META-DYNAMICS ani zadnego
konkretnego adaptera (Grid-Monitor/Earthquake-Core/Quantum-Lattice/
Synoptyk-v3/Industrial-Predict/...) -- kazdy z nich buduje trywialny
`MetaSeriesData` (kilka linii) ze swojego wlasnego wyniku i przekazuje
tutaj. Powod tej decyzji: repozytoria w tym ekosystemie sa od 2026-09-10
swiadomie NIEZALEZNE od siebie (zwendorowany kod, nie sibling-import) --
ten modul zyje w TIMDR-Math-Formalism (repo "protokolu testowania
formalizmu") i jest wendorowany do kazdego klienta jako KOPIA, dokladnie
jak timdr_formalism/pipeline.py juz jest.

PIEC OBSZAROW WALIDACJI (numeracja zgodna ze specyfikacja, z ktorej ten
modul powstal):

  1. Sanity surowej serii -- NIE walidacja REGUL AKTUALIZACJI modelu
     (to jest z definicji domenowo-specyficzne: "czy defect_operator()
     na siatce Kuramoto jest policzony poprawnie" wymaga zupelnie innej
     wiedzy niz "czy flow()/twist() w sygnale sejsmicznym sa poprawne").
     Ten modul sprawdza tylko KSZTALT/SKONCZONOSC danych (`validate_shape_and_ranges`)
     i udostepnia pluggable hook `domain_check_fn` (patrz `validate_meta_series`)
     dla wywolujacego, ktory MA te domenowa wiedze.
  2. Spojnosc agregatu Lambda-tau-rho-J -- zakresy, NaN/Inf, dlugosci
     (`validate_shape_and_ranges`).
  3. Izolacja kanalow -- koreluje kazda pare kanalow (Spearman, bo kanaly
     czesto NIE sa rozkladem normalnym) i ostrzega, gdy dwa kanaly sa
     PODEJRZANIE ZDUBLOWANE -- dokladnie ten blad, ktory juz wystapil
     DWUKROTNIE w tym ekosystemie pod inna postacia: Synoptyk-v3 V1
     (surowe rho/J dominujace sume nad Lambda/tau) i odrzucone
     Omega=D+|R| w TIMDR-Quantum-Lattice (`validate_channel_isolation`).
  4. Diagnostyka progow fazowych -- rozklad magnitude vs classify_phase()
     0.1/1.0 -- NIE zmienia progow, tylko RAPORTUJE czy sa w ogole w
     zasiegu tej domeny i SUGERUJE percentylowa alternatywe do RECZNEJ
     decyzji, nigdy automatycznie nie stosowana (`diagnose_phase_thresholds`).
  5. Walidacja statystyczna -- opakowanie `mann_whitney_test()` z
     `pipeline.py` (ten sam kod, nie duplikat) + NIEZALEZNY test
     Kolmogorova-Smirnowa jako druga metoda (`compare_regimes`), test
     stabilnosci klasyfikacji faz -- "flapping" krok-po-kroku jako
     sygnal szumu okienkowania, dokladnie wzorzec juz zdiagnozowany w
     TIMDR-Grid-Monitor PROBA 1 (`phase_stability_diagnostic`), i
     spojnosc kierunku/skali efektu miedzy niezaleznymi
     przebiegami/ziarnami (`cross_run_consistency`).

UCZCIWE OGRANICZENIA:
  - Ten modul NIE ocenia, czy dana MATEMATYKA/FORMULA Lambda-tau-rho-J
    jest sama w sobie sensowna dla danej domeny -- to decyzja projektowa
    czlowieka, pre-rejestrowana PRZED uruchomieniem (patrz skill
    timdr-signal-framework). Ocenia tylko, czy WYNIK tej matematyki jest
    wewnetrznie spojny, statystycznie odrozniania tam gdzie powinien byc,
    i nie ma ukrytych patologii (zdublowane kanaly, prog poza skala).
  - Sugestie progow (obszar 4) sa DIAGNOSTYCZNE, nie prognostyczne --
    uzycie ich jako nowych progow produkcyjnych bez niezaleznej
    weryfikacji na INNYCH danych/ziarnach jest post-hoc dopasowaniem
    (numerologia), dokladnie temu, czemu ten projekt sie przeciwstawia.
  - Testy w obszarze 5 dzialaja BEZ scipy (czysto-numpy fallback), tym
    samym wzorcem bezpieczenstwa importu co `pipeline.py::mann_whitney_test`
    (Windows Device Guard moze blokowac DLL-e scipy -- patrz naglowek
    `pipeline.py` i `TIMDR-Earthquake-Core/HISTORIA_I_TESTY.md` dla
    realnego przypadku). Fallback Spearmana nie liczy p-wartosci (tylko
    wspolczynnik) -- jesli potrzebna formalna istotnosc korelacji, uzyj
    scipy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from .pipeline import mann_whitney_test

try:
    from scipy.stats import spearmanr as _scipy_spearmanr
    from scipy.stats import ks_2samp as _scipy_ks_2samp
    _HAS_SCIPY = True
except ImportError:  # pragma: no cover - patrz naglowek modulu
    _scipy_spearmanr = None
    _scipy_ks_2samp = None
    _HAS_SCIPY = False

CHANNEL_NAMES = ("Lambda", "tau", "rho", "J")
VALID_PHASE_LABELS = {"stabilna", "przejsciowa", "krytyczna"}


# ---------------------------------------------------------------------
# Kontener wejsciowy -- domenowo-niezalezny
# ---------------------------------------------------------------------

@dataclass
class MetaSeriesData:
    """Domenowo-niezalezny kontener na jeden wynik meta_adapter-podobny.
    Kazdy adapter w ekosystemie buduje to z wlasnej listy MetaState +
    M_series + phases w kilku liniach, np.:

        MetaSeriesData(
            Lambda=[s.Lambda for s in result.states],
            tau=[s.tau for s in result.states],
            rho=[s.rho for s in result.states],
            J=[s.J for s in result.states],
            magnitude=[op.magnitude(m) for m in result.M_series],
            phases=result.phases,
        )

    `Lambda/tau/rho/J` maja dlugosc n (jeden stan na krok/okno),
    `magnitude/phases` maja dlugosc n-1 (jeden na krok M-serii)."""
    Lambda: Sequence[float]
    tau: Sequence[float]
    rho: Sequence[float]
    J: Sequence[float]
    magnitude: Sequence[float]
    phases: Sequence[str]
    trigger_triggered: Optional[bool] = None
    trigger_location: Optional[int] = None


# ---------------------------------------------------------------------
# Raport
# ---------------------------------------------------------------------

@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning" | "info"
    area: str      # "shape" | "isolation" | "thresholds" | "statistics" | "domain"
    code: str
    message: str


@dataclass
class MetaValidationReport:
    issues: List[ValidationIssue] = field(default_factory=list)
    channel_stats: Dict[str, dict] = field(default_factory=dict)
    channel_correlations: Dict[str, Optional[float]] = field(default_factory=dict)
    magnitude_stats: Dict[str, float] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Brak problemow o wadze 'error'. UWAGA: 'warning'/'info' moga
        nadal byc wazne (np. progi nigdy nieosiagniete) -- `passed=True`
        NIE znaczy "wszystko idealnie", tylko "nic wewnetrznie zepsute"."""
        return not any(i.severity == "error" for i in self.issues)

    def add(self, severity: str, area: str, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(severity, area, code, message))

    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def format_report(self) -> str:
        lines = [f"MetaValidationReport: {'PASSED' if self.passed else 'FAILED'} ({len(self.issues)} uwag)"]
        for i in self.issues:
            lines.append(f"  [{i.severity.upper()}] ({i.area}/{i.code}) {i.message}")
        return "\n".join(lines)


# ---------------------------------------------------------------------
# Obszary 1 (czesc niedomenowa) + 2: ksztalt i zakresy
# ---------------------------------------------------------------------

def validate_shape_and_ranges(
    data: MetaSeriesData,
    expect_unit_interval: Sequence[str] = ("Lambda", "rho", "J"),
) -> MetaValidationReport:
    """Sanity ksztaltu + spojnosc zakresow agregatu Lambda-tau-rho-J.

    `expect_unit_interval`: ktore kanaly z definicji powinny byc w [0,1]
    -- domyslnie Lambda/rho/J, bo TAK sa zdefiniowane we WSZYSTKICH
    dotychczasowych adapterach tego ekosystemu (fraction/high-freq-fraction).
    `tau` jest ilorazem wzgledem progu robust, wiec formalnie MOZE
    przekroczyc 1 -- to NIE jest blad, dlatego nie jest tu domyslnie."""
    report = MetaValidationReport()
    n = len(data.Lambda)

    for name in CHANNEL_NAMES:
        vals = np.asarray(getattr(data, name), dtype=float)
        if len(vals) != n:
            report.add(
                "error", "shape", "length_mismatch",
                f"Kanal {name} ma dlugosc {len(vals)}, oczekiwano {n} (jak Lambda)",
            )
            continue
        if not np.all(np.isfinite(vals)):
            n_bad = int(np.sum(~np.isfinite(vals)))
            report.add("error", "shape", "non_finite", f"Kanal {name} ma {n_bad} wartosci NaN/Inf")
        if name in expect_unit_interval:
            n_out = int(np.sum((vals < -1e-9) | (vals > 1 + 1e-9)))
            if n_out > 0:
                report.add(
                    "warning", "shape", "out_of_unit_interval",
                    f"Kanal {name} ma {n_out}/{len(vals)} wartosci poza [0,1] "
                    f"(oczekiwane dla tego kanalu we wszystkich dotychczasowych adapterach "
                    f"-- sprawdz definicje formuly dla tej domeny)",
                )
        finite = vals[np.isfinite(vals)]
        if finite.size:
            report.channel_stats[name] = dict(
                min=float(finite.min()), max=float(finite.max()),
                mean=float(finite.mean()), std=float(finite.std()),
                p50=float(np.percentile(finite, 50)), p95=float(np.percentile(finite, 95)),
            )

    expected_m_len = max(n - 1, 0)
    if len(data.magnitude) != expected_m_len:
        report.add(
            "error", "shape", "magnitude_length_mismatch",
            f"magnitude ma dlugosc {len(data.magnitude)}, oczekiwano {expected_m_len} (n-1 stanow)",
        )
    if len(data.phases) != len(data.magnitude):
        report.add(
            "error", "shape", "phases_length_mismatch",
            f"phases ma dlugosc {len(data.phases)}, oczekiwano {len(data.magnitude)} (jak magnitude)",
        )

    bad_labels = set(data.phases) - VALID_PHASE_LABELS
    if bad_labels:
        report.add("error", "shape", "invalid_phase_labels", f"Nieznane etykiety fazy: {sorted(bad_labels)}")

    mags = np.asarray(data.magnitude, dtype=float)
    if mags.size and np.all(np.isfinite(mags)):
        report.magnitude_stats.update(dict(
            min=float(mags.min()), max=float(mags.max()), mean=float(mags.mean()),
            p50=float(np.percentile(mags, 50)), p95=float(np.percentile(mags, 95)),
            p99=float(np.percentile(mags, 99)),
        ))
    elif mags.size:
        report.add("error", "shape", "magnitude_non_finite", "magnitude zawiera NaN/Inf")

    return report


# ---------------------------------------------------------------------
# Obszar 3: izolacja kanalow (m.in. izolacja J od Lambda/tau/rho)
# ---------------------------------------------------------------------

def _spearman_numpy(a: np.ndarray, b: np.ndarray) -> float:
    """Fallback bez scipy: Spearman = Pearson na rangach. Srednie rangi
    dla remisow (jak scipy.stats.rankdata(method='average'))."""
    def rank(x: np.ndarray) -> np.ndarray:
        order = np.argsort(x, kind="mergesort")
        ranks = np.empty_like(order, dtype=float)
        sorted_x = x[order]
        i = 0
        n = len(x)
        while i < n:
            j = i
            while j + 1 < n and sorted_x[j + 1] == sorted_x[i]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            ranks[order[i:j + 1]] = avg_rank
            i = j + 1
        return ranks

    ra, rb = rank(a), rank(b)
    if np.std(ra) < 1e-12 or np.std(rb) < 1e-12:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def validate_channel_isolation(
    data: MetaSeriesData,
    correlation_warn_threshold: float = 0.8,
) -> MetaValidationReport:
    """Obszar 3: wykrywa PODEJRZANE zdublowanie miedzy kanalami --
    dokladnie ten blad, ktory juz dwukrotnie wystapil w tym ekosystemie
    pod inna postacia (Synoptyk-v3 V1: rho/J SUROWE dominujace sume;
    TIMDR-Quantum-Lattice: odrzucone Omega=D+|R| mieszajace defekt z
    rezonansem w JEDNA wielkosc). Szczegolnie wazne dla J (rezonans) --
    ten kanal z definicji MA byc niezalezny od pozostalych trzech (patrz
    zastrzezenia w kazdym adapterze uzywajacym rezonansu), wiec wysoka
    korelacja J z ktorymkolwiek innym kanalem jest najbardziej
    podejrzanym sygnalem z tej czworki par."""
    report = MetaValidationReport()
    series = {name: np.asarray(getattr(data, name), dtype=float) for name in CHANNEL_NAMES}
    pairs = [(a, b) for i, a in enumerate(CHANNEL_NAMES) for b in CHANNEL_NAMES[i + 1:]]

    for a, b in pairs:
        va, vb = series[a], series[b]
        finite_mask = np.isfinite(va) & np.isfinite(vb)
        va_f, vb_f = va[finite_mask], vb[finite_mask]
        key = f"{a}-{b}"
        if va_f.size < 3 or np.std(va_f) < 1e-12 or np.std(vb_f) < 1e-12:
            report.channel_correlations[key] = None
            continue

        if _HAS_SCIPY:
            rho, p = _scipy_spearmanr(va_f, vb_f)
            rho = float(rho)
        else:
            rho = _spearman_numpy(va_f, vb_f)
            p = None

        report.channel_correlations[key] = rho
        if abs(rho) >= correlation_warn_threshold:
            j_note = " (UWAGA: dotyczy kanalu J -- rezonans MA byc niezalezny)" if "J" in (a, b) else ""
            p_str = f", p={p:.3g}" if p is not None else " (p niedostepne bez scipy)"
            report.add(
                "warning", "isolation", "high_channel_correlation",
                f"Kanaly {a} i {b} sa silnie skorelowane (Spearman rho={rho:.3f}{p_str}){j_note} "
                f"-- sprawdz, czy nie sa faktycznie tym samym sygnalem liczonym dwa razy "
                f"(dokladnie blad juz odkryty w tym ekosystemie: Synoptyk-v3 V1 / "
                f"TIMDR-Quantum-Lattice Omega=D+|R|).",
            )

    return report


# ---------------------------------------------------------------------
# Obszar 4: diagnostyka progow fazowych
# ---------------------------------------------------------------------

def diagnose_phase_thresholds(
    data: MetaSeriesData,
    thresholds: "tuple[float, float]" = (0.1, 1.0),
) -> MetaValidationReport:
    """Obszar 4: RAPORTUJE, czy domyslne progi classify_phase() (0.1/1.0)
    sa w ogole w zasiegu skali danych tej domeny -- NIE zmienia progow.
    Sugeruje (informacyjnie, NIGDY automatycznie) alternatywne,
    percentylowe progi -- decyzja o ich uzyciu nalezy WYLACZNIE do
    czlowieka, po niezaleznej weryfikacji na INNYCH danych/ziarnach niz
    te, z ktorych zostaly policzone (w przeciwnym razie to post-hoc
    data snooping, dokladnie numerologia)."""
    report = MetaValidationReport()
    mags = np.asarray(data.magnitude, dtype=float)
    mags = mags[np.isfinite(mags)]
    if mags.size == 0:
        report.add("error", "thresholds", "no_data", "Brak skonczonych wartosci magnitude do analizy progow")
        return report

    thr_transitional, thr_critical = thresholds
    frac_ge_transitional = float(np.mean(mags >= thr_transitional))
    frac_ge_critical = float(np.mean(mags >= thr_critical))
    report.magnitude_stats["fraction_ge_transitional_threshold"] = frac_ge_transitional
    report.magnitude_stats["fraction_ge_critical_threshold"] = frac_ge_critical
    report.magnitude_stats["max_magnitude"] = float(mags.max())

    if frac_ge_transitional == 0.0:
        report.add(
            "warning", "thresholds", "thresholds_never_reached",
            f"Magnitude NIGDY nie osiaga progu 'przejsciowa'={thr_transitional} "
            f"(max zaobserwowane={mags.max():.4g}) -- domyslne progi 0.1/1.0 sa "
            f"prawdopodobnie skalibrowane dla innej skali danych niz ta domena. "
            f"NIE zmieniaj progu automatycznie -- patrz sugestia ponizej do "
            f"RECZNEJ, niezaleznej weryfikacji.",
        )
    elif frac_ge_critical > 0.5:
        report.add(
            "warning", "thresholds", "mostly_critical",
            f"{frac_ge_critical:.0%} krokow przekracza prog 'krytyczna' -- jesli to "
            f"nie jest oczekiwane (np. caly przebieg powinien byc w wiekszosci "
            f"spokojny), sprawdz czy progi sa wlasciwej skali dla tej domeny.",
        )

    suggested_transitional = float(np.percentile(mags, 90))
    suggested_critical = float(np.percentile(mags, 99))
    report.magnitude_stats["suggested_transitional_p90"] = suggested_transitional
    report.magnitude_stats["suggested_critical_p99"] = suggested_critical
    report.add(
        "info", "thresholds", "suggested_percentile_thresholds",
        f"Sugestia DIAGNOSTYCZNA (nie do automatycznego zastosowania): percentyl 90 "
        f"tej serii={suggested_transitional:.4g}, percentyl 99={suggested_critical:.4g}. "
        f"Uzycie tych liczb jako nowych progow produkcyjnych wymaga niezaleznej "
        f"weryfikacji na INNYCH przebiegach/ziarnach niz te, z ktorych zostaly "
        f"policzone -- w przeciwnym razie to post-hoc dopasowanie (numerologia).",
    )
    return report


# ---------------------------------------------------------------------
# Obszar 5: walidacja statystyczna
# ---------------------------------------------------------------------

def _ks_2samp_numpy(a: np.ndarray, b: np.ndarray) -> "tuple[float, float]":
    """Fallback bez scipy: statystyka D (max |roznica CDF|) + asymptotyczna
    p-wartosc (rozklad Kolmogorova, ta sama formula co scipy przy
    method='asymp', two-sided) -- Q(lambda)=2*sum_{k=1..K}(-1)^(k-1)*exp(-2k^2*lambda^2)."""
    a_sorted = np.sort(a)
    b_sorted = np.sort(b)
    all_vals = np.concatenate([a_sorted, b_sorted])
    cdf_a = np.searchsorted(a_sorted, all_vals, side="right") / a_sorted.size
    cdf_b = np.searchsorted(b_sorted, all_vals, side="right") / b_sorted.size
    d_stat = float(np.max(np.abs(cdf_a - cdf_b)))

    n, m = a_sorted.size, b_sorted.size
    ne = n * m / (n + m)
    lam = (np.sqrt(ne) + 0.12 + 0.11 / np.sqrt(ne)) * d_stat  # poprawka Stephensa, jak scipy
    if lam < 0.2:
        p = 1.0
    else:
        total = 0.0
        for k in range(1, 101):
            term = ((-1) ** (k - 1)) * np.exp(-2.0 * (k ** 2) * (lam ** 2))
            total += term
            if abs(term) < 1e-10:
                break
        p = float(np.clip(2.0 * total, 0.0, 1.0))
    return d_stat, p


def compare_regimes(
    values_a: Sequence[float],
    values_b: Sequence[float],
    alternative: str = "two-sided",
) -> dict:
    """Obszar 5 (czesc 1): porownuje dwie grupy WARTOSCI (np. magnitude
    w dwoch polowach przebiegu, albo w dwoch niezaleznych scenariuszach)
    DWIEMA NIEZALEZNYMI metodami nieparametrycznymi:

    - Mann-Whitney U (reuzywa `mann_whitney_test()` z pipeline.py -- ten
      sam kod co reszta protokolu formalizmu w tym repo, NIE duplikat).
      Wykrywa przesuniecie MEDIANY.
    - Kolmogorov-Smirnov. Wykrywa roznice CALEGO ROZKLADU (np. wariancji/
      ksztaltu), ktorych Mann-Whitney moze nie zlapac.

    Zwraca oba wyniki -- NIE redukuje do jednej liczby, bo pytaja o rozne
    rzeczy."""
    mw = mann_whitney_test(values_a, values_b, alternative=alternative)
    out: dict = {"mann_whitney": mw}

    va = np.asarray(values_a, dtype=float)
    vb = np.asarray(values_b, dtype=float)
    if _HAS_SCIPY:
        ks_result = _scipy_ks_2samp(va, vb, alternative=alternative)
        out["ks_statistic"] = float(ks_result.statistic)
        out["ks_pvalue"] = float(ks_result.pvalue)
    else:
        d_stat, p = _ks_2samp_numpy(va, vb)
        out["ks_statistic"] = d_stat
        out["ks_pvalue"] = p
    return out


def phase_stability_diagnostic(phases: Sequence[str]) -> MetaValidationReport:
    """Obszar 5 (czesc 2): wykrywa PODEJRZANE, wysokoczestotliwosciowe
    "trzepotanie" miedzy fazami krok po kroku -- sygnatura tego samego
    problemu, ktory PROBA 1 w TIMDR-Grid-Monitor/meta_adapter.py juz raz
    zdiagnozowala (zbyt krotkie okno -> szum probkowania dominuje nad
    realnym sygnalem, klasyfikacja skacze losowo miedzy fazami zamiast
    zmieniac sie w odpowiedzi na realne zdarzenia)."""
    report = MetaValidationReport()
    if len(phases) < 2:
        return report
    n_transitions = sum(1 for i in range(1, len(phases)) if phases[i] != phases[i - 1])
    flip_rate = n_transitions / (len(phases) - 1)
    report.magnitude_stats["phase_flip_rate"] = flip_rate
    if flip_rate > 0.5:
        report.add(
            "warning", "statistics", "high_phase_flip_rate",
            f"Faza zmienia sie w {flip_rate:.0%} kolejnych krokow -- podejrzanie "
            f"czeste jak na realny sygnal (nie szum okienkowania). Patrz "
            f"TIMDR-Grid-Monitor PROBA 1 dla dokladnie tego wzorca bledu "
            f"(zbyt krotkie okno -> szum probkowania dominuje).",
        )
    return report


def cross_run_consistency(magnitude_series_list: Sequence[Sequence[float]]) -> MetaValidationReport:
    """Obszar 5 (czesc 3): sprawdza, czy skala efektu jest SPOJNA miedzy
    niezaleznymi przebiegami (np. roznymi ziarnami) -- dokladnie
    dyscyplina mocy testu juz ustalona w TIMDR-Grid-Monitor (jedno
    ziarno to za malo, agreguj po wielu). Liczy wspolczynnik zmiennosci
    (CV) sredniej magnitude miedzy przebiegami -- wysoki CV oznacza, ze
    wynik jest niestabilny (moze byc artefaktem pojedynczego ziarna),
    nie realna wlasciwoscia systemu."""
    report = MetaValidationReport()
    means = [float(np.mean(m)) for m in magnitude_series_list if len(m) > 0]
    if len(means) < 2:
        report.add(
            "info", "statistics", "insufficient_runs",
            "Potrzeba >=2 niezaleznych przebiegow do oceny spojnosci miedzy nimi",
        )
        return report

    mean_of_means = float(np.mean(means))
    std_of_means = float(np.std(means))
    cv = std_of_means / mean_of_means if mean_of_means > 1e-12 else float("inf")
    report.magnitude_stats["cross_run_mean"] = mean_of_means
    report.magnitude_stats["cross_run_cv"] = cv
    if cv > 1.0:
        report.add(
            "warning", "statistics", "high_cross_run_variability",
            f"Wspolczynnik zmiennosci sredniej magnitude miedzy {len(means)} "
            f"przebiegami = {cv:.2f} (>1.0) -- wynik moze byc niestabilny/"
            f"zdominowany przez pojedyncze ziarno, nie ogolna wlasciwoscia "
            f"systemu. Rozwaz wiecej ziaren przed uogolnianiem wniosku.",
        )
    return report


# ---------------------------------------------------------------------
# Pojedyncze wejscie -- laczy obszary 1/2/3/4 + czesc 5 (jeden przebieg)
# ---------------------------------------------------------------------

def validate_meta_series(
    data: MetaSeriesData,
    channel_correlation_warn_threshold: float = 0.8,
    phase_thresholds: "tuple[float, float]" = (0.1, 1.0),
    domain_check_fn: Optional[Callable[[MetaSeriesData], MetaValidationReport]] = None,
) -> MetaValidationReport:
    """Uruchamia obszary 1 (niedomenowa czesc)/2/3/4 plus
    `phase_stability_diagnostic` z obszaru 5, i laczy wyniki w jeden
    raport dla JEDNEGO przebiegu. `compare_regimes()`/`cross_run_consistency()`
    z obszaru 5 wymagaja DODATKOWYCH danych (dwie grupy wartosci / wiele
    przebiegow) i sa wywolywane OSOBNO przez wywolujacego -- ta funkcja
    dostaje tylko JEDEN wynik naraz, wiec nie moze ich policzyc sama.

    `domain_check_fn`: opcjonalny hook do domenowo-specyficznej walidacji
    REGUL AKTUALIZACJI (obszar 1, czesc domenowa) -- ten modul CELOWO
    nie implementuje tego sam (wymaga znajomosci konkretnego modelu
    fizycznego/matematycznego kazdej domeny), ale zapewnia miejsce,
    gdzie wywolujacy moze wpiac wlasna funkcje `(MetaSeriesData) ->
    MetaValidationReport`, ktorej wyniki zostana dolaczone do calosci."""
    report = validate_shape_and_ranges(data)

    isolation_report = validate_channel_isolation(data, channel_correlation_warn_threshold)
    report.issues.extend(isolation_report.issues)
    report.channel_correlations.update(isolation_report.channel_correlations)

    threshold_report = diagnose_phase_thresholds(data, phase_thresholds)
    report.issues.extend(threshold_report.issues)
    report.magnitude_stats.update(threshold_report.magnitude_stats)

    stability_report = phase_stability_diagnostic(data.phases)
    report.issues.extend(stability_report.issues)
    report.magnitude_stats.update(stability_report.magnitude_stats)

    if domain_check_fn is not None:
        domain_report = domain_check_fn(data)
        report.issues.extend(domain_report.issues)
        report.channel_stats.update(domain_report.channel_stats)

    return report
