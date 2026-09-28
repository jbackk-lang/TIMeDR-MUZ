"""MUZ-SIM v0.1: czy zarzadca budzetu MUZ wyprowadza gospodarstwo na prosta w trudnej symulacji,
w ktorej standardowe programy budzetowe zawodza. Zamknieta petla, dzien po dniu, 36 miesiecy.

Gospodarstwo (egzogeniczne, wspolne dla wszystkich zarzadcow -- wspolne liczby losowe):
  dochod: wyplata 10. dnia / pod koniec miesiaca z przesunieciem na poniedzialek / co 14 dni / freelance;
          podwyzki z opoznieniem (0,7 x inflacja); przerwa w pracy 61 dni (30% gospodarstw w S1)
  zobowiazania: czynsz (5. dnia), zaliczka na energie (20. dnia, stala w roku) + rozliczenie w marcu,
          ubezpieczenie roczne, losowe awarie (Poisson), karta kredytowa 20%/rok, rata min. 3% (25. dnia),
          debet 25%/rok
  inflacja per kategoria (mieszkanie 8%, energia 30%, jedzenie 15%, inne 4% rocznie)
  wydatki swobodne: zarzadca daje przydzial A na okres; gospodarstwo wydaje go z przodu okresu, z poslizgiem;
          zmeczenie: przydzial < 0,85 potrzeby narasta, powyzej progu -- wybuch (1,2 x potrzeby przez okres)
Zarzadcy: Brak, Bank (kalendarz, nominalnie, ostatni miesiac), Koperty (styl YNAB: przydzial przy wplywie,
  cele indeksowane jednym CPI, fundusz = srednia 12 mies.), MUZ (zegar wyplaty + rezerwa zobowiazan do nastepnej
  wyplaty wg ich kalendarza, odniesienie: CPI kazdej kategorii, rezim zdarzen: fundusz na wybuchy), ablacje MUZ.
PREREG_MUZ_SIM_v0_1."""
import sys, json, datetime as dt
import numpy as np

T0 = dt.date(2023, 1, 1); NM = 36
DATES = [T0 + dt.timedelta(days=i) for i in range((dt.date(2026, 1, 1) - T0).days)]
T = len(DATES)
MON = np.array([(d.year - 2023) * 12 + d.month - 1 for d in DATES]); DOM = np.array([d.day for d in DATES])
WD = np.array([d.weekday() for d in DATES]); MSTART = np.array([i for i in range(T) if DOM[i] == 1])
DIM = np.array([(dt.date(2023 + (m + 1) // 12, (m + 1) % 12 + 1, 1) - dt.timedelta(days=1)).day for m in range(NM)])
CATS = ["mieszk", "energia", "jedzenie", "inne"]; WNAT = np.array([0.30, 0.10, 0.30, 0.30])
ONB = 60  # dni obserwacji przed pierwsza decyzja

SCEN = {
    "S0": dict(pi=[0, 0, 0, 0], raises=False, gap=0.0, shocks=0.0, ins=False, pay={"d10": 1.0}, settle=False),
    "S1": dict(pi=[0.08, 0.30, 0.15, 0.04], raises=True, gap=0.3, shocks=1.2, ins=True,
               pay={"d10": 0.25, "slide": 0.30, "biweek": 0.25, "free": 0.20}, settle=True),
    "S2": dict(pi=[0.08, 0.30, 0.15, 0.04], raises=True, gap=0.3, shocks=1.2, ins=True,
               pay={"d10": 0.25, "slide": 0.30, "biweek": 0.25, "free": 0.20}, settle=True, structural=True),
}


def cpi(sc):
    P = np.array([[(1 + p) ** (m / 12) for p in sc["pi"]] for m in range(NM)])
    return P, P @ WNAT


def workday_back(i):
    while WD[i] >= 5:
        i -= 1
    return i


def workday_fwd(i):
    while i < T - 1 and WD[i] >= 5:
        i += 1
    return i


def gen(rng, sc):
    P, P1 = cpi(sc); I0 = 6000 * np.exp(0.35 * rng.standard_normal())
    pf = np.exp(0.05 * rng.standard_normal(4))
    types = list(sc["pay"]); ptype = types[rng.choice(len(types), p=list(sc["pay"].values()))]
    # dochod miesieczny z podwyzkami (wiek 1 i 2, losowy miesiac)
    R = np.ones(NM)
    if sc["raises"]:
        for y in (0, 1, 2):  # coroczna podwyzka w losowym miesiacu = inflacja z ostatnich 12 miesiecy
            m = 12 * y + rng.integers(0, 12); prev = P1[m] / P1[m - 12] if m >= 12 else P1[12] / P1[0]
            r = 1 + sc.get("idx", 1.0) * (prev - 1) + 0.02 * rng.standard_normal()
            R[m:] *= r
    Im = I0 * R; cred = np.zeros(T)
    if ptype == "d10":
        for m in range(NM):
            cred[workday_back(MSTART[m] + 9)] += Im[m]
    elif ptype == "slide":
        for m in range(NM):
            cred[workday_fwd(min(MSTART[m] + min(30, DIM[m]) - 1, T - 1))] += Im[m]
    elif ptype == "biweek":
        for i in range(rng.integers(0, 14), T, 14):
            cred[i] += Im[MON[i]] * 12 / 26
    else:  # freelance: polowa stala 10. dnia + zlecenia
        for m in range(NM):
            cred[workday_back(MSTART[m] + 9)] += 0.5 * Im[m]
            for _ in range(rng.poisson(3)):
                cred[MSTART[m] + rng.integers(0, DIM[m])] += rng.exponential(0.5 * Im[m] / 3)
    if rng.random() < sc["gap"]:
        g = rng.integers(180, 900); cred[g:g + 61] = 0
    struct = sc.get("structural", False)
    rs = rng.uniform(0.25, 0.35) if not struct else rng.uniform(0.55, 0.60)
    es = rng.uniform(0.06, 0.10) if not struct else rng.uniform(0.12, 0.15)
    D0 = I0 * (rng.uniform(0.3, 1.5) if not struct else 3.0)
    rent = np.zeros(T); en = np.zeros(T); irr = np.zeros(T)
    for m in range(NM):
        rent[MSTART[m] + 4] = rs * I0 * P[m, 0] * pf[0]
        adv_m = 12 * (m // 12) if sc["settle"] else m
        en[MSTART[m] + 19] = es * I0 * P[adv_m, 1] * pf[1]
    if sc["settle"]:
        for y in (1, 2):  # rozliczenie roku y-1 w marcu roku y
            true = sum(es * I0 * P[m, 1] * pf[1] for m in range(12 * (y - 1), 12 * y))
            irr[MSTART[12 * y + 2] + 14] += true - 12 * es * I0 * P[12 * (y - 1), 1] * pf[1]
    if sc["ins"]:
        mi = rng.integers(0, 12)
        for y in range(3):
            irr[MSTART[12 * y + mi] + 14] += 0.04 * I0 * P[12 * y + mi, 3]
    for i in np.where(rng.random(T) < sc["shocks"] / 365)[0]:
        irr[i] += I0 * 0.35 * np.exp(0.6 * rng.standard_normal() - 0.18) * P[MON[i], 3]
    irr_avg = (0.04 / 12 if sc["ins"] else 0) + sc["shocks"] * 0.35 / 12
    Wtot = I0 * (sc.get("deficit", 1.03) - rs - es - irr_avg - 0.03 * D0 / I0)
    Wtot = max(Wtot, 0.25 * I0)
    fs = rng.uniform(0.4, 0.6); W = np.array([0, 0, fs, 1 - fs]) * Wtot  # realnie, ceny z m=0
    return dict(I0=I0, P=P, P1=P1, pf=pf, ptype=ptype, cred=cred, rent=rent, en=en, irr=irr, D0=D0, W=W,
                bal0=I0 * rng.uniform(0, 0.3), noise=rng.gamma(3, 1 / 3, T), slip=0.05 + 0.08 * rng.standard_normal(NM))


def desire_rate(h, m):
    """prawdziwa potrzeba nominalna na dzien w miesiacu m"""
    return float((h["W"] * h["P"][m] * h["pf"]).sum() * 12 / 365)


# --------------------------- zarzadcy ---------------------------
class Base:
    name = "Brak"

    def __init__(self, h, sc):
        self.h, self.sc = h, sc; self.last = None

    def decide(self, d, st):
        return None  # (A, L, prepay) albo None


class Bank(Base):
    """Typowa aplikacja bankowa: 1. dnia miesiaca limit = wplywy - oplaty z poprzedniego miesiaca - 5%; nominalnie."""
    name = "Bank"

    def decide(self, d, st):
        if d < ONB or DOM[d] != 1:
            return None
        a = MSTART[MON[d] - 1]; inc = self.h["cred"][a:d].sum(); fix = st["out_fix"][a:d].sum()
        A = max(0.0, inc - fix - 0.05 * inc); pre = max(0.0, st["bal"] - 2 * inc) if inc > 0 else 0.0
        return A, int(DIM[MON[d]]), pre


class Planner(Base):
    """Wspolny planista kopertowy; flagi: clock pay|cal, ref cat|one|nom, event learn|avg|none."""

    def __init__(self, h, sc, clock, ref, event, name):
        super().__init__(h, sc); self.clock, self.ref, self.event, self.name = clock, ref, event, name
        self.trig = []; self.West = None; self.fund = 0.0; self.saved = 0.0

    def index(self, k):
        """indeks cen wg odniesienia w miesiacu k (wzgledem m=0)"""
        P, P1 = self.h["P"], self.h["P1"]
        if self.ref == "cat":
            return P[k] / P[0]
        if self.ref == "one":
            return np.full(4, P1[k] / P1[0])
        return np.ones(4)

    def cpi_ratio(self, m):
        return self.index(max(m - 1, 0))  # CPI publikowany z miesiecznym opoznieniem

    def is_trigger(self, d, st):
        c = self.h["cred"][d]
        if c <= 0:
            return False
        past = self.h["cred"][max(0, d - 90):d]
        if len(past) == 0:
            return True
        return c >= 0.5 * past.max() if past.max() > 0 else True

    def decide(self, d, st):
        h = self.h; m = MON[d]
        if self.clock == "pay":
            trig = self.is_trigger(d, st)
            if trig:
                self.trig.append(d)
            if d < ONB:
                return None
            since = d - self.last if self.last is not None else 99
            if not ((trig and since >= 8) or since >= 35):
                return None
            iv = np.diff(self.trig[-7:]); iv = iv[iv >= 8]
            L = int(np.clip(np.median(iv) if len(iv) else 30, 10, 35))
        else:
            if d < ONB or DOM[d] != 1:
                return None
            L = int(DIM[m])
        if self.West is None:  # potrzeba z okresu obserwacji, realnie wg odniesienia
            sp = st["disc_cat"][:ONB]; defl = np.array([self.index(MON[i]) for i in range(ONB)])
            self.West = (sp / defl).mean(0)  # dzienna, w cenach bazowych odniesienia
        need = float((self.West * self.cpi_ratio(m)).sum()) * L
        # rezerwa zobowiazan do nastepnej decyzji (+3 dni) wg ich kalendarza (nauczony z historii)
        H = 3 if self.clock == "pay" else 0
        res = 0.0
        for dd in range(d, min(d + L + H, T)):
            dm = DOM[dd]
            if dm == 5:
                res += st["last_rent"] * 1.01
            if dm == 20:
                res += st["last_en"]
            if dm == 25:
                res += max(0.03 * st["debt"], 100) if st["debt"] > 0 else 0
        # fundusz na zdarzenia nieregularne
        irr_hist = st["out_irr"][:d]; days = max(d, 1)
        if self.event == "none":
            fund_target = 0.0
        elif self.event == "avg":
            fund_target = irr_hist.sum() / days * 90
        else:  # rezim zdarzen: wydatki nieregularne przychodza wybuchami -- cel = 80. percentyl sum 90-dniowych
            cs = np.concatenate([[0.0], np.cumsum(irr_hist)])
            win = cs[90:] - cs[:-90] if d > 90 else np.array([irr_hist.sum() / days * 90])
            fund_target = max(float(np.percentile(win, 80)), irr_hist.sum() / days * 90)
        # rozliczenie energii: zaliczka stala w roku, ceny rosna -> luka narasta (tylko przy odniesieniu do cen)
        if self.ref != "nom" and st["last_en"] > 0:
            y0 = 12 * (m // 12); ix = lambda k: self.index(k)[1]
            gap = sum(st["last_en"] * (ix(k) / ix(y0) - 1) for k in range(y0, m))
            if m % 12 < 3 and y0 >= 12:  # rozliczenie poprzedniego roku jeszcze przed nami (marzec)
                gap += sum(st["last_en"] / (ix(y0) / ix(y0 - 12)) * (ix(k) / ix(y0 - 12) - 1) for k in range(y0 - 12, y0))
            fund_target += max(gap, 0.0)
        ess = st["last_rent"] + st["last_en"] + max(0.03 * st["debt"], 100) * (st["debt"] > 0)
        buf = ess
        inc = self.inc_est(d) * L / 30.4
        # koperty trwale: oszczednosci i fundusz istnieja tylko, jesli sa pieniadze po rezerwie
        self.saved = min(self.saved, max(st["bal"] - res, 0.0))
        self.fund = min(fund_target, max(st["bal"] - res - self.saved, 0.0))
        free = st["bal"] - res - self.saved - self.fund
        buf = max(buf - self.fund, 0.0)  # fundusz zdarzen i bufor to ta sama kieszen (nie dublowac rezerwy)
        save = 0.10 * inc if (st["debt"] > 0 or self.saved < buf) else 0.0
        # tryb wychodzenia z dlugu: przydzial 0,80 potrzeby (tuz nad progiem zmeczenia 0,75), reszta na oszczednosci/dlug
        target = 0.80 * need if (st["debt"] > 0 or self.saved < buf) else need
        A = float(np.clip(free - save, 0.75 * need, target))
        self.saved += max(0.0, min(save, free - A))
        pre = 0.0
        if st["debt"] > 0 and self.saved > buf:
            pre = self.saved - buf; self.saved = buf
        self.last = d
        return A, L, pre

    def monthly_income(self, d):
        c = self.h["cred"]; ms = [MSTART[k] for k in range(MON[d]) if MSTART[k] < d]
        return np.array([c[ms[i]:ms[i + 1]].sum() for i in range(len(ms) - 1)][-12:])

    def inc_est(self, d):
        mi = self.monthly_income(d)
        return float(np.median(mi[-6:])) if len(mi) else float(self.h["cred"][:d].sum() / max(d, 1) * 30.4)


class Asceta(Planner):
    """Odniesienie z gory (nie do pobicia w praktyce): zna prawdziwa potrzebe i przyszle zdarzenia nieregularne
    na 90 dni; przydzial = 0,76 potrzeby (tuz nad progiem zmeczenia). Mierzy wykonalnosc scenariusza."""
    def __init__(self, h, sc):
        super().__init__(h, sc, "pay", "cat", "learn", "Asceta")

    def decide(self, d, st):
        r = super().decide(d, st)
        if r is None:
            return None
        A, L, pre = r; need = desire_rate(self.h, MON[d]) * L
        fut = self.h["irr"][d:d + 90].sum(); free = st["bal"] - fut
        A2 = 0.76 * need
        buf = st["last_rent"] + st["last_en"]
        pre2 = max(0.0, min(st["debt"], free - A2 - buf - 1.5 * buf))
        self.saved = 0.0
        return A2, L, pre2


def make(kind, h, sc):
    if kind == "Asceta":
        return Asceta(h, sc)
    if kind == "Brak":
        return Base(h, sc)
    if kind == "Bank":
        return Bank(h, sc)
    spec = {"Koperty": ("pay", "one", "avg"), "MUZ": ("pay", "cat", "learn"), "MUZ_kal": ("cal", "cat", "learn"),
            "MUZ_1cpi": ("pay", "one", "learn"), "MUZ_bezD": ("pay", "cat", "none")}[kind]
    return Planner(h, sc, *spec, kind)


CTRL = ["Brak", "Asceta", "Bank", "Koperty", "MUZ", "MUZ_kal", "MUZ_1cpi", "MUZ_bezD"]


def run(h, sc, kind):
    c = make(kind, h, sc); bal = h["bal0"]; debt = h["D0"]; F = 0.0
    st = {"disc_cat": np.zeros((T, 4)), "out_fix": np.zeros(T), "out_irr": np.zeros(T), "last_rent": 0.0, "last_en": 0.0}
    rate = None; ps = 0; Lp = 30; blow = False; od = np.zeros(T, bool); interest = 0.0; bounce = 0; blows = 0
    cons = 0.0; want = 0.0; shares = h["W"] * h["pf"]
    for d in range(T):
        m = MON[d]; bal += h["cred"][d]; st["bal"] = bal; st["debt"] = debt  # wplyw rano, decyzja po nim
        dec = c.decide(d, st)
        if dec is not None:
            A, L, pre = dec; W = desire_rate(h, m)
            rho = A / (W * L) if W > 0 else 1.0; F = 0.7 * F + max(0.0, 0.85 - rho)
            blow = F > 0.5
            if blow:
                F = 0.0; blows += 1
            rate = A / L; ps = d; Lp = L
            pre = min(pre, debt, max(bal, 0)); bal -= pre; debt -= pre
        fix = h["rent"][d] + h["en"][d]
        if h["rent"][d]:
            st["last_rent"] = h["rent"][d]
        if h["en"][d]:
            st["last_en"] = h["en"][d]
        if DOM[d] == 25 and debt > 0:
            mp = min(debt, max(0.03 * debt, 100)); fix += mp; debt -= mp
        st["out_fix"][d] = fix; st["out_irr"][d] = h["irr"][d]; bal -= fix + h["irr"][d]
        di = debt * 0.20 / 365; debt += di; interest += di
        W = desire_rate(h, m)
        if rate is None or blow:
            spend = (1.2 if blow else 1.0) * W
        else:
            k = d - ps
            spend = rate * (1.8 if k < 3 else (Lp - 5.4) / max(Lp - 3, 1))
        spend *= h["noise"][d] * (1 + h["slip"][m])
        pr = h["P"][m] * h["pf"]; split = shares * pr / (shares * pr).sum()
        st["disc_cat"][d] = spend * split; bal -= spend
        cons += (spend * split / pr).sum(); want += (W * split / pr).sum() * 1.0
        if bal < 0:
            oi = -bal * 0.25 / 365; bal -= oi; interest += oi; od[d] = True
            if bal < -1.5 * h["I0"]:
                bounce += 1
    ess_end = h["rent"][MSTART[-1] + 4] + h["en"][MSTART[-1] + 19]
    ok = bool(debt <= 1 and bal >= ess_end and not od[-180:].any())
    return dict(ok=ok, debt=debt / h["I0"], bal=bal / h["I0"], od_days=int(od.sum()), bounce=bounce,
                interest=interest / h["I0"], cons=cons / want, blows=blows)


def simulate(scen, n, seed, ctrls=CTRL):
    sc = SCEN[scen]; out = {k: [] for k in ctrls}; meta = []
    for i in range(n):
        h = gen(np.random.default_rng([seed, i, list(SCEN).index(scen)]), sc); meta.append(h["ptype"])
        for k in ctrls:
            out[k].append(run(h, sc, k))
    return out, meta


def summarize(out, meta, n_boot=2000, seed=11):
    S = {k: {q: float(np.mean([r[q] for r in v])) for q in v[0]} for k, v in out.items()}
    ok = {k: np.array([r["ok"] for r in v], float) for k, v in out.items()}
    rng = np.random.default_rng(seed); n = len(meta); B = [rng.integers(0, n, n) for _ in range(n_boot)]

    def diff(a, b, q="ok"):
        x = np.array([r[q] for r in out[a]], float) - np.array([r[q] for r in out[b]], float)
        v = [x[ii].mean() for ii in B]
        return {"d": float(x.mean()), "CI95": [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]}
    per_type = {t: {k: float(ok[k][[i for i, m in enumerate(meta) if m == t]].mean()) for k in out}
                for t in sorted(set(meta))}
    return S, diff, per_type


if __name__ == "__main__":
    scen, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    out, meta = simulate(scen, n, seed)
    S, diff, pt = summarize(out, meta)
    res = {"scen": scen, "n": n, "seed": seed, "mean": S, "per_type_ok": pt,
           "diff": {f"{a}-{b}": diff(a, b) for a, b in [("MUZ", "Koperty"), ("MUZ", "Bank"), ("MUZ", "MUZ_kal"),
                                                         ("MUZ", "MUZ_1cpi"), ("MUZ", "MUZ_bezD"), ("Koperty", "Bank")]},
           "cons_diff": {"MUZ-Koperty": diff("MUZ", "Koperty", "cons")}}
    print(json.dumps(res, indent=1, ensure_ascii=False))
