"""Okno zarzadcy budzetu (tkinter z biblioteki standardowej). Uzytkownik nie programuje i nie wypelnia rubryk:

- przy otwarciu okno samo wczytuje wyciagi z folderu `wyciagi/`, odswieza inflacje i pokazuje, co robic,
- "Dodaj wyciągi…" (albo przeciagniecie pliku na run.bat) -- kopiuje pliki i od razu liczy,
- "Wklej…" -- tekst skopiowany ze strony banku, z aplikacji albo z Excela; MUZ sam znajduje daty i kwoty,
- jedyne pole do wpisania: saldo teraz (opcjonalne, gdy wyciag jest starszy),
- sprawy: karta PDF, pismo do wydruku, "Załatwione" / "Nie udało się" -- MUZ pamieta i nastepnym razem proponuje dalej.
Blad nie zamyka okna: komunikat w oknie, pelny slad w wyniki/blad.txt.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import traceback
from datetime import date
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import wklej, zarzadca
from .decisions import render_cycle, zl
from .ustawienia import Ustawienia

REPO = zarzadca.REPO
ACTION_LABEL = {"negocjowac": "zadzwoń / negocjuj", "anulowac": "wypowiedz", "zmienic": "zmień ofertę"}


def open_path(path) -> None:
    path = Path(path)
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # domyslny program: Excel dla .csv, przegladarka PDF, Eksplorator dla folderu
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


class App(tk.Tk):
    def __init__(self, add: list[str] | None = None):
        super().__init__()
        self.title("MUZ — zarządca budżetu")
        self.geometry("1000x700")
        self.ust = Ustawienia(REPO / "ustawienia.json")
        self.w: zarzadca.Wynik | None = None
        self._build()
        if add:
            zarzadca.add_files(add)
        self.after(100, self.refresh)

    # ---------------------------------------------------------------- budowa okna
    def _build(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="➕ Dodaj wyciągi…", command=self.add_statements).pack(side="left")
        ttk.Button(top, text="Wklej…", command=self.paste).pack(side="left", padx=4)
        ttk.Button(top, text="⟳ Odśwież", command=self.refresh).pack(side="left")
        ttk.Label(top, text="   Saldo teraz:").pack(side="left")
        self.saldo = tk.StringVar(value="" if self.ust.saldo(date.today()) is None else f"{self.ust.saldo(date.today()):.2f}".replace(".", ","))
        e = ttk.Entry(top, textvariable=self.saldo, width=12)
        e.pack(side="left")
        e.bind("<Return>", lambda _e: self.set_saldo())
        ttk.Label(top, text="zł").pack(side="left")
        ttk.Button(top, text="OK", width=4, command=self.set_saldo).pack(side="left", padx=2)
        ttk.Label(top, text="(tylko gdy wyciąg jest starszy niż kilka dni)", foreground="#777").pack(side="left", padx=4)

        self.status = ttk.Label(self, text="", padding=(8, 0))
        self.status.pack(fill="x")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=6)
        # --- zakladka 1: co teraz
        t1 = ttk.Frame(nb, padding=6)
        nb.add(t1, text="Co teraz")
        self.plan_txt = tk.Text(t1, height=12, wrap="word", font=("Segoe UI", 11), relief="flat", background="#f7f7f5")
        self.plan_txt.pack(fill="x")
        ttk.Label(t1, text="Sprawy do załatwienia (od największej kwoty):", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 2))
        cols = ("sprawa", "co", "rocznie", "termin")
        self.tree = ttk.Treeview(t1, columns=cols, show="headings", height=7, selectmode="browse")
        for c, label, width in (("sprawa", "Sprawa", 520), ("co", "Co zrobić", 140), ("rocznie", "Zysk rocznie", 110), ("termin", "Termin", 100)):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=width, anchor="w" if c in ("sprawa", "co") else "e")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.open_card())
        bar = ttk.Frame(t1)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Karta: co powiedzieć (PDF)", command=self.open_card).pack(side="left")
        ttk.Button(bar, text="✉ Pismo do wydruku", command=self.letter).pack(side="left", padx=4)
        ttk.Button(bar, text="✓ Załatwione", command=lambda: self.mark(True)).pack(side="left", padx=(16, 4))
        ttk.Button(bar, text="✗ Nie udało się", command=lambda: self.mark(False)).pack(side="left")
        # --- zakladka 2: oplaty stale
        t2 = ttk.Frame(nb, padding=6)
        nb.add(t2, text="Opłaty stałe")
        ttk.Label(t2, text="MUZ rozpoznał te opłaty sam. Jeśli kategoria jest zła — zaznacz wiersz i wybierz właściwą.",
                  foreground="#555").pack(anchor="w")
        self.tree2 = ttk.Treeview(t2, columns=("k", "kat", "kw", "st"), show="headings", height=12, selectmode="browse")
        for c, label, width in (("k", "Komu płacisz", 420), ("kat", "Kategoria", 140), ("kw", "Ostatnio", 110), ("st", "", 140)):
            self.tree2.heading(c, text=label)
            self.tree2.column(c, width=width, anchor="e" if c == "kw" else "w")
        self.tree2.pack(fill="both", expand=True)
        bar2 = ttk.Frame(t2)
        bar2.pack(fill="x", pady=4)
        self.cat = tk.StringVar()
        ttk.Combobox(bar2, textvariable=self.cat, values=zarzadca.CATEGORIES, state="readonly", width=16).pack(side="left")
        ttk.Button(bar2, text="Ustaw kategorię", command=self.set_category).pack(side="left", padx=4)
        ttk.Button(bar2, text="✓ Zgadza się", command=self.confirm_category).pack(side="left")
        # --- zakladka 3: szczegoly
        t3 = ttk.Frame(nb, padding=6)
        nb.add(t3, text="Szczegóły")
        self.details = tk.Text(t3, wrap="word", font=("Consolas", 10))
        self.details.pack(fill="both", expand=True)

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="x")
        self.excel_btn = ttk.Button(bottom, text="Excel ▾", command=self.excel_menu, state="disabled")
        self.excel_btn.pack(side="left")
        self.pdf_btn = ttk.Button(bottom, text="Przydział do wypłaty (PDF)", command=self.open_plan_pdf, state="disabled")
        self.pdf_btn.pack(side="left", padx=4)
        ttk.Button(bottom, text="Folder wyciągów", command=lambda: open_path(self._ensure(zarzadca.WYCIAGI))).pack(side="left", padx=(16, 4))
        ttk.Button(bottom, text="Folder wyników", command=lambda: open_path(self._ensure(zarzadca.WYNIKI))).pack(side="left")
        ttk.Button(bottom, text="Moje dane do pism…", command=self.person).pack(side="right")

    @staticmethod
    def _ensure(p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ---------------------------------------------------------------- przebieg
    def refresh(self):
        self.status.config(text="Liczę… (wyciągi, inflacja z GUS, opłaty, sprawy)")
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            w = zarzadca.run(date.today(), self.ust)
            self.after(0, self._show, w, None)
        except Exception as exc:  # noqa: BLE001
            zarzadca.WYNIKI.mkdir(exist_ok=True)
            (zarzadca.WYNIKI / "blad.txt").write_text(traceback.format_exc(), encoding="utf-8")
            self.after(0, self._show, None, exc)

    def _show(self, w, exc):
        self.plan_txt.delete("1.0", "end")
        self.tree.delete(*self.tree.get_children())
        self.tree2.delete(*self.tree2.get_children())
        if exc is not None:
            self.status.config(text=f"Błąd: {exc} — szczegóły w wyniki\\blad.txt")
            return
        self.w = w
        if w.plan is None:
            self.plan_txt.insert("end", "Dodaj wyciąg z banku (przycisk „➕ Dodaj wyciągi…”: plik CSV lub MT940 pobrany "
                                        "z bankowości internetowej) albo skopiuj historię ze strony banku i użyj „Wklej…”.\n\n"
                                 + "\n".join(w.problemy))
            self.status.config(text="Czekam na dane.")
            return
        plain = render_cycle(w.plan).replace("**", "").replace("## ", "").replace("_", "")
        self.plan_txt.insert("end", plain)
        for s in w.sprawy:
            self.tree.insert("", "end", iid=s.id, values=(s.tytul, ACTION_LABEL.get(s.akcja, s.akcja), zl(s.rocznie_gr),
                                                          s.termin.strftime("%d.%m.%Y")))
        for o in w.oplaty:
            st = "potwierdzona" if o["potwierdzona"] else ("rozpoznana" if o["rozpoznana"] else "ustawiona")
            self.tree2.insert("", "end", iid=o["kontrahent"], values=(o["kontrahent"], o["kategoria"], zl(o["kwota_gr"]), st))
        files = ", ".join(f"{p['plik']} ({p['format']})" for p in w.pliki)
        self.details.delete("1.0", "end")
        self.details.insert("end", f"Wczytane: {files}\nDane do: {w.dane_do}\n\n" +
                            ("Uwagi:\n- " + "\n- ".join(w.problemy) + "\n\n" if w.problemy else "") + w.raport)
        self.excel_btn.config(state="normal")
        self.pdf_btn.config(state="normal" if w.pdf_przydzial else "disabled")
        n = len(w.sprawy)
        self.status.config(text=f"Gotowe: {len(w.pliki)} plik(ów), dane do {w.dane_do:%d.%m.%Y}; "
                                f"spraw do załatwienia: {n}" + (f"; uwagi: {len(w.problemy)} (zakładka Szczegóły)" if w.problemy else ""))

    # ---------------------------------------------------------------- dane
    def add_statements(self):
        fs = filedialog.askopenfilenames(parent=self, title="Wyciągi z banku (można zaznaczyć kilka)",
                                         filetypes=[("Wyciągi", "*.csv *.txt *.sta *.mt940 *.940"), ("Wszystkie", "*.*")])
        if fs:
            zarzadca.add_files(fs)
            self.refresh()

    def paste(self):
        win = tk.Toplevel(self)
        win.title("Wklej historię")
        win.geometry("760x520")
        ttk.Label(win, text="Skopiuj historię ze strony banku, z aplikacji, z SMS-a albo z Excela i wklej tutaj (Ctrl+V):",
                  padding=6).pack(anchor="w")
        txt = tk.Text(win, height=12, wrap="none")
        txt.pack(fill="both", expand=True, padx=6)
        prev = ttk.Treeview(win, columns=("d", "k", "o"), show="headings", height=8)
        for c, label, width in (("d", "Data", 100), ("k", "Kwota", 100), ("o", "Opis", 500)):
            prev.heading(c, text=label)
            prev.column(c, width=width, anchor="e" if c == "k" else "w")
        prev.pack(fill="both", expand=True, padx=6, pady=4)
        info = ttk.Label(win, text="", padding=6)
        info.pack(anchor="w")
        state = {"rows": []}

        def recognize(_e=None):
            rows, skipped = wklej.parse(txt.get("1.0", "end"), date.today())
            state["rows"] = rows
            prev.delete(*prev.get_children())
            for r in rows:
                prev.insert("", "end", values=(r.date.strftime("%d.%m.%Y"), zl(r.amount_gr), r.text))
            info.config(text=f"Rozpoznano {len(rows)} transakcji" + (f"; pominięto {skipped} bez daty" if skipped else "")
                             + ". Sprawdź i kliknij „Zapisz”.")

        def save():
            if not state["rows"]:
                recognize()
            n = wklej.append(state["rows"], zarzadca.DANE / "wklejone.csv")
            win.destroy()
            messagebox.showinfo("Zapisano", f"Dopisano {n} nowych transakcji (powtórzone pominięte).", parent=self)
            self.refresh()

        txt.bind("<<Paste>>", lambda _e: self.after(50, recognize))
        b = ttk.Frame(win, padding=6)
        b.pack(fill="x")
        ttk.Button(b, text="Rozpoznaj", command=recognize).pack(side="left")
        ttk.Button(b, text="Zapisz", command=save).pack(side="left", padx=4)
        ttk.Button(b, text="Anuluj", command=win.destroy).pack(side="right")

    def set_saldo(self):
        raw = self.saldo.get().strip().replace(" ", "").replace(",", ".")
        try:
            self.ust.set_saldo(float(raw) if raw else None, date.today())
        except ValueError:
            messagebox.showwarning("Saldo", "Wpisz kwotę, np. 3250,40", parent=self)
            return
        self.refresh()

    def person(self):
        o = self.ust.d.setdefault("osoba", {})
        for key, label in (("imie_nazwisko", "Imię i nazwisko"), ("adres", "Adres (ulica, kod, miasto)"),
                           ("miejscowosc", "Miejscowość (do daty pisma)")):
            v = simpledialog.askstring("Dane do pism", label, initialvalue=o.get(key, ""), parent=self)
            if v is None:
                return
            o[key] = v.strip()
        self.ust.save()

    # ---------------------------------------------------------------- sprawy
    def _selected(self):
        sel = self.tree.selection()
        if not sel or self.w is None:
            messagebox.showinfo("Sprawy", "Zaznacz sprawę na liście.", parent=self)
            return None
        return next(s for s in self.w.sprawy if s.id == sel[0])

    def open_card(self):
        s = self._selected()
        if s is None:
            return
        if s.pdf:
            open_path(s.pdf)
        else:
            messagebox.showinfo(s.tytul, (self.w.pdf_note or "") + "\n\nKarta jest w zakładce Szczegóły.", parent=self)

    def letter(self):
        s = self._selected()
        if s is None:
            return
        if not self.ust.d.get("osoba", {}).get("imie_nazwisko"):
            if messagebox.askyesno("Dane do pism", "Wpisać raz imię, nazwisko i adres? (Bez nich w piśmie zostaną puste "
                                                   "miejsca do wypełnienia długopisem.)", parent=self):
                self.person()
        try:
            open_path(zarzadca.letter_pdf(s, self.ust, date.today(), zarzadca.WYNIKI / "pisma"))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Pismo", str(exc), parent=self)

    def mark(self, ok: bool):
        s = self._selected()
        if s is None:
            return
        price = None
        if ok and s.akcja in ("negocjowac", "zmienic"):
            v = simpledialog.askstring("Załatwione", f"{s.kontrahent}: nowa cena miesięcznie (zł)? Możesz zostawić puste.",
                                       parent=self)
            try:
                price = float(v.replace(",", ".")) if v and v.strip() else None
            except ValueError:
                price = None
        self.ust.done(s.id, s.kontrahent, s.akcja, "udalo_sie" if ok else "nie_udalo_sie", price, date.today())
        if not ok and s.akcja == "negocjowac":
            messagebox.showinfo("Zapamiętane", "Następnym razem MUZ zaproponuje zmianę oferty albo wypowiedzenie.", parent=self)
        self.refresh()

    # ---------------------------------------------------------------- oplaty stale
    def _sel2(self):
        sel = self.tree2.selection()
        if not sel:
            messagebox.showinfo("Opłaty stałe", "Zaznacz opłatę na liście.", parent=self)
            return None
        return sel[0]

    def set_category(self):
        k = self._sel2()
        if k is None or not self.cat.get():
            return
        self.ust.d["kategorie"][k] = self.cat.get()
        self.ust.d["potwierdzone"][k] = True
        self.ust.save()
        self.refresh()

    def confirm_category(self):
        k = self._sel2()
        if k is None:
            return
        self.ust.d["potwierdzone"][k] = True
        self.ust.save()
        self.refresh()

    # ---------------------------------------------------------------- pliki
    def excel_menu(self):
        if self.w is None:
            return
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Lista spraw i przydziału", command=lambda: open_path(self.w.excel["decyzje"]))
        m.add_command(label="Wszystkie transakcje", command=lambda: open_path(self.w.excel["transakcje"]))
        m.tk_popup(self.excel_btn.winfo_rootx(), self.excel_btn.winfo_rooty() - 50)

    def open_plan_pdf(self):
        if self.w and self.w.pdf_przydzial:
            open_path(self.w.pdf_przydzial)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    App(add=[a for a in args if Path(a).is_file()]).mainloop()


if __name__ == "__main__":
    main()
