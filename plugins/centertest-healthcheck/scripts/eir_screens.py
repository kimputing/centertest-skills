"""
Which application screens the suite's own code opens.

The generated project lists every Guidewire screen as cssids/<app>/<Screen>.properties, whose
getter chains start with the screen's page object ("new SubmissionWizardPage(getContext())").
A screen counts as used when non-generated project code refers to that page class. Screens
reached only inside framework-provided steps are not seen, so this is a floor, not a ceiling.

Wizards are reported on their own: they are the business transactions (submission, policy
change, disbursement ...) and the gaps a QA architect plans against.
"""

from __future__ import annotations

import json
import os
import re

APPS = {"pc": "PolicyCenter", "bc": "BillingCenter", "cc": "ClaimCenter", "ab": "ContactManager"}
_FIRST_PAGE = re.compile(r"=\s*new\s+(\w+)\s*\(")
_PAGE_WORD = re.compile(r"\b(\w+Page)\b")


def find_cssids_dir(repo_dir: str, explicit: str | None = None) -> str | None:
    """The generated cssids/ folder: --cssids, <project>-generated next to the project, or the
    cssid-finder config (~/.centertest/cssid-finder.json)."""
    candidates = []
    if explicit:
        candidates += [explicit, os.path.join(explicit, "cssids")]
    repo = os.path.abspath(repo_dir)
    candidates.append(os.path.join(repo + "-generated", "src", "main", "resources", "cssids"))
    try:
        with open(os.path.expanduser("~/.centertest/cssid-finder.json"), encoding="utf-8") as fh:
            configured = json.load(fh).get("cssids_dir")
        if configured:
            candidates += [os.path.join(configured, "cssids"), configured]
    except (OSError, ValueError):
        pass
    for c in candidates:
        if c and os.path.isdir(c) and any(os.path.isdir(os.path.join(c, a)) for a in APPS):
            return c
    return None


def _screens(cssids_dir: str, app: str) -> dict[str, str]:
    """{screen name: page class} for one app."""
    out = {}
    folder = os.path.join(cssids_dir, app)
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".properties") or name.startswith("_"):
            continue
        with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as fh:
            m = _FIRST_PAGE.search(fh.read(8000))
        if m:
            out[name[: -len(".properties")]] = m.group(1)
    return out


def _page_users(repo_dir: str, source_root: str) -> dict[str, set[str]]:
    """{page class: classes in non-generated code that refer to it}."""
    users: dict[str, set[str]] = {}
    for root, _dirs, files in os.walk(os.path.join(repo_dir, source_root)):
        parts = root.replace("\\", "/").split("/")
        if "datadriven" in parts or "generated" in parts:
            continue
        for name in files:
            if name.endswith(".java"):
                with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                    for page in set(_PAGE_WORD.findall(fh.read())):
                        users.setdefault(page, set()).add(name[:-5])
    return users


def screen_coverage(repo_dir: str, source_root: str, cssids_dir: str) -> list[dict]:
    """Per app: {app, name, screens, used, wizards: [(screen, users)], unused_wizards, used_screens}."""
    users = _page_users(repo_dir, source_root)
    out = []
    for app, label in APPS.items():
        if not os.path.isdir(os.path.join(cssids_dir, app)):
            continue
        screens = _screens(cssids_dir, app)
        used = {s: sorted(users[p]) for s, p in screens.items() if p in users}
        wizards = [s for s in screens if s.endswith("Wizard")]
        out.append({
            "app": app, "name": label, "screens": len(screens), "used": len(used),
            "used_screens": used,
            "wizards": [(w, used[w]) for w in wizards if w in used],
            "unused_wizards": [w for w in wizards if w not in used],
        })
    return out


def print_screens(coverage: list[dict]) -> None:
    print("  SCREENS THE SUITE OPENS (own code; framework steps not counted)")
    for c in coverage:
        print(f"  {c['name']:<15} wizards {len(c['wizards']):>3}/{len(c['wizards']) + len(c['unused_wizards']):<3} "
              f"screens {c['used']:>4}/{c['screens']}")
        if c["unused_wizards"]:
            print("      no test opens: " + ", ".join(c["unused_wizards"][:6])
                  + (f" +{len(c['unused_wizards']) - 6}" if len(c["unused_wizards"]) > 6 else ""))
