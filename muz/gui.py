"""Okno etapu 0 (tkinter z biblioteki standardowej): wybor wyciagu, mapowanie kolumn, raport.

Okno nie znika po bledzie: blad pokazuje sie w oknie, a pelny slad trafia do wyniki/blad.txt.
Uruchom: python -m muz.gui  (albo dwuklik na run.bat bez argumentu).
"""
from __future__ import annotations

import json
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import pipeline
from .adapter.csv_import import detect_header, guess_mapping
from .report import plain_text

REPO = Path(__file__).resolve().parents[1]
FIELDS = [("date", "Data operacji *"), ("amount", "Kwota *"), ("counterparty", "Kontrahent *"),
          ("description", "Tytuł / opis *"), ("currency", "Waluta"), ("balance", "Saldo po operacji")]
REQUIRED = {"date", "amount", "counterparty", "description"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TIMeDR-MUZ — etap 0 (tylko odczyt)")
        self.geometry("900x640")
        self.path: Path | None = None
        self.columns: list[str] = []
        self.vars = {k: tk.StringVar() for k, _ in FIELDS}
        self.combos = {}

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="Wybierz wyciąg (CSV lub MT940)…", command=self.choose).pack(side="left")
        self.file_label = ttk.Label(top, text="nie wybrano pliku")
        self.file_label.pack(side="left", padx=8)

        self.map_frame = ttk.LabelFrame(self, text="Kolumny wyciągu (* wymagane)", padding=8)
        self.map_frame.pack(fill="x", padx=8)
        for r, (key, label) in enumerate(FIELDS):
            ttk.Label(self.map_frame, text=label, width=20).grid(row=r, column=0, sticky="w", pady=2)
            cb = ttk.Combobox(self.map_frame, textvariable=self.vars[key], state="readonly", width=50)
            cb.grid(row=r, column=1, sticky="w", pady=2)
            self.combos[key] = cb

        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        self.run_btn = ttk.Button(bar, text="Uruchom analizę", command=self.run, state="disabled")
        self.run_btn.pack(side="left")
        self.status = ttk.Label(bar, text="")
        self.status.pack(side="left", padx=8)

        self.text = tk.Text(self, wrap="word", font=("Consolas", 10))
        self.text.pack(fill="both", expand=True, padx=8, pady=8)
        self.load_saved_mapping()

    def load_saved_mapping(self):
        p = REPO / "mapowanie.json"
        if p.exists():
            try:
                saved = json.loads(p.read_text(encoding="utf-8"))
                for k in self.vars:
                    self.vars[k].set(saved.get(k, ""))
            except (OSError, ValueError):
                pass

    def choose(self):
        start = REPO / "dane" if (REPO / "dane").is_dir() else REPO
        f = filedialog.askopenfilename(parent=self, title="Wyciąg z banku", initialdir=str(start),
                                       filetypes=[("Wyciągi", "*.csv *.txt *.sta *.mt940 *.940"), ("Wszystkie", "*.*")])
        if not f:
            return
        self.path = Path(f)
        self.file_label.config(text=str(self.path))
        if self.path.suffix.lower() in (".sta", ".mt940", ".940"):
            self.map_frame.pack_forget()
            self.run_btn.config(state="normal")
            self.status.config(text="MT940: mapowanie kolumn niepotrzebne")
            return
        self.map_frame.pack(fill="x", padx=8, after=self.file_label.master)
        try:
            _, self.columns = detect_header(self.path)
        except Exception as exc:  # noqa: BLE001 - pokazujemy uzytkownikowi, okno zostaje
            messagebox.showerror("Nie rozpoznano pliku", str(exc), parent=self)
            return
        guess = guess_mapping(self.columns)
        options = [""] + [c for c in self.columns if c]
        for key, cb in self.combos.items():
            cb["values"] = options
            current = self.vars[key].get()
            if not current or current not in options:  # puste albo z innego banku -> propozycja
                self.vars[key].set(guess.get(key, ""))
        self.run_btn.config(state="normal")
        self.status.config(text="Sprawdź dopasowanie kolumn i kliknij „Uruchom analizę”.")

    def run(self):
        if self.path is None:
            return
        mapping_path = None
        if self.path.suffix.lower() not in (".sta", ".mt940", ".940"):
            mapping = {k: v.get() for k, v in self.vars.items() if v.get()}
            missing = [label for key, label in FIELDS if key in REQUIRED and key not in mapping]
            if missing:
                messagebox.showwarning("Brak kolumn", "Wybierz kolumny: " + ", ".join(missing), parent=self)
                return
            mapping_path = REPO / "mapowanie.json"
            mapping_path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
        self.run_btn.config(state="disabled")
        self.status.config(text="Liczę…")
        threading.Thread(target=self._work, args=(mapping_path,), daemon=True).start()

    def _work(self, mapping_path):
        out = REPO / "wyniki"
        try:
            pipeline.run([self.path], mapping_path, out)
            report = (out / "raport_etap0.md").read_text(encoding="utf-8")
            self.after(0, self._done, report, None)
        except Exception as exc:  # noqa: BLE001
            out.mkdir(exist_ok=True)
            (out / "blad.txt").write_text(traceback.format_exc(), encoding="utf-8")
            self.after(0, self._done, None, exc)

    def _done(self, report, exc):
        self.run_btn.config(state="normal")
        self.text.delete("1.0", "end")
        if exc is not None:
            self.status.config(text="Błąd — szczegóły w wyniki\\blad.txt")
            self.text.insert("end", f"Błąd: {exc}\n\nPełny ślad: {REPO / 'wyniki' / 'blad.txt'}")
            messagebox.showerror("Błąd analizy", str(exc), parent=self)
            return
        self.status.config(text=f"Gotowe. Raport: {REPO / 'wyniki' / 'raport_etap0.md'}")
        self.text.insert("end", plain_text(report))


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
