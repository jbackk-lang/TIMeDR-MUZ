"""Wykonawca formularzy (L2): lokalna przegladarka Chromium sterowana przez Playwright.

- dla kazdego dostawcy wersjonowany przepis pol (forms/<dostawca>_v*.json),
- uzytkownik loguje sie sam w widocznym oknie; MUZ nie przechowuje hasel,
- dry_run wypelnia pola i robi zrzut "przed" bez wysylania,
- execute wysyla dopiero po zweryfikowanym zatwierdzeniu, zrzuty przed i po trafiaja do pokwitowania.
Playwright jest opcjonalny (moze byc zablokowany przez Device Guard); pisma i QR dzialaja bez niego.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core.common import sha256_file, sha256_text
from ..core.netguard import check_host
from .base import BaseExecutor


def load_recipe(path) -> dict:
    recipe = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("host", "url", "fields", "submit", "version"):
        if key not in recipe:
            raise ValueError(f"przepis formularza bez pola {key!r}")
    return recipe | {"recipe_sha256": sha256_file(path)}


def _playwright_page(headless: bool = False):  # pragma: no cover - wymaga przegladarki
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=headless)
    return browser.new_page()


class FormExecutor(BaseExecutor):
    name = "form"
    level = "L2"
    levels = ("L2",)

    def __init__(self, trusted_public_key: bytes, recipe: dict, evidence_dir, page_factory=None,
                 login_timeout_ms: int = 300_000):
        super().__init__(trusted_public_key)
        self.recipe = recipe
        self.allowed_hosts = frozenset({recipe["host"]})
        self.evidence_dir = Path(evidence_dir)
        self.page_factory = page_factory or _playwright_page
        self.login_timeout_ms = login_timeout_ms

    def _fill(self, page, values: dict) -> list[str]:
        check_host(self.recipe["url"], self.allowed_hosts)
        page.goto(self.recipe["url"])
        first = self.recipe["fields"][0]["selector"]
        page.wait_for_selector(first, timeout=self.login_timeout_ms)  # czas na reczne logowanie
        filled = []
        for fld in self.recipe["fields"]:
            page.fill(fld["selector"], str(values[fld["value_key"]]))
            filled.append(fld["selector"])
        return filled

    def _shot(self, page, name: str) -> dict:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / name
        page.screenshot(path=str(path))
        return {"file": path.name, "sha256": sha256_file(path)}

    def dry_run(self, plan: dict) -> dict:
        page = self.page_factory()
        filled = self._fill(page, plan["content"]["values"])
        return {"plan_sha256": plan["plan_sha256"], "executor": self.name, "filled": filled,
                "screenshot_before": self._shot(page, f"{plan['plan_id'][:12]}_podglad.png"), "submitted": False}

    def _do(self, plan: dict) -> dict:
        page = self.page_factory()
        self._fill(page, plan["content"]["values"])
        before = self._shot(page, f"{plan['plan_id'][:12]}_przed.png")
        page.click(self.recipe["submit"])
        after = self._shot(page, f"{plan['plan_id'][:12]}_po.png")
        return {"recipe_version": self.recipe["version"], "recipe_sha256": self.recipe["recipe_sha256"],
                "url": self.recipe["url"], "screenshot_before": before, "screenshot_after": after,
                "values_sha256": sha256_text(json.dumps(plan["content"]["values"], sort_keys=True, ensure_ascii=False))}
