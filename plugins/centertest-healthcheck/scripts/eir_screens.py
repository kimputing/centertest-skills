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


def _has_layout(folder: str) -> bool:
    """Guidewire 10 (cssids/<app>/*.properties) or Guidewire 9 (<app>.cssids files)."""
    return any(os.path.isdir(os.path.join(folder, a)) or os.path.isfile(os.path.join(folder, f"{a}.cssids"))
               for a in APPS)


def find_cssids_dir(repo_dir: str, explicit: str | None = None) -> str | None:
    """The generated cssids: --cssids, <project>-generated next to the project, or the
    cssid-finder config (~/.centertest/cssid-finder.json). Guidewire 10 keeps them in
    src/main/resources/cssids/<app>/, Guidewire 9 in src/main/resources/<app>.cssids."""
    candidates = []
    if explicit:
        candidates += [os.path.join(explicit, "cssids"), explicit]
    repo = os.path.abspath(repo_dir)
    resources = os.path.join(repo + "-generated", "src", "main", "resources")
    candidates += [os.path.join(resources, "cssids"), resources]
    for c in candidates:
        if c and os.path.isdir(c) and _has_layout(c):
            return c
    try:
        with open(os.path.expanduser("~/.centertest/cssid-finder.json"), encoding="utf-8") as fh:
            configured = json.load(fh).get("cssids_dir")
    except (OSError, ValueError):
        configured = None
    # the cssid-finder config names whichever generated project was set up last: use it only when it is
    # this project's (its generated Java holds the package the project imports pages from)
    if configured and _belongs_to(repo, configured):
        for c in (os.path.join(configured, "cssids"), configured):
            if os.path.isdir(c) and _has_layout(c):
                return c
    return None


_PAGE_PACKAGE = re.compile(r"^import\s+([\w.]+?)\.generated\.pages\.", re.M)


def _belongs_to(repo: str, resources: str) -> bool:
    """Whether a generated project's resources go with this project: its src/main/java holds the
    package the project imports generated pages from. False when that cannot be shown."""
    prefixes = set()
    for root, dirs, files in os.walk(os.path.join(repo, "src")):
        dirs[:] = [d for d in dirs if d not in ("build", "generated", "datadriven")]
        for name in files:
            if name.endswith(".java"):
                try:
                    with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                        prefixes.update(_PAGE_PACKAGE.findall(fh.read()))
                except OSError:
                    continue
    base = os.path.abspath(resources)
    if os.path.basename(base) == "cssids":
        base = os.path.dirname(base)
    java = os.path.join(os.path.dirname(base), "java")
    return any(os.path.isdir(os.path.join(java, *p.split("."), "generated")) for p in prefixes)


def _screens(cssids_dir: str, app: str) -> dict[str, str]:
    """{screen name: page class} for one app, from either layout."""
    gw9 = os.path.join(cssids_dir, f"{app}.cssids")
    if not os.path.isdir(os.path.join(cssids_dir, app)) and os.path.isfile(gw9):
        out = {}
        try:
            with open(gw9, encoding="utf-8", errors="replace") as fh:
                entries = json.load(fh)
        except (OSError, ValueError):
            return out
        for e in entries if isinstance(entries, list) else []:
            path, cssid = e.get("hierarchyPath") or "", e.get("cssId") or ""
            m = re.match(r"\s*new\s+(\w+)\s*\(", path)
            if m and cssid and not cssid.startswith("#"):
                out.setdefault(re.split(r"[:\-]", cssid, maxsplit=1)[0], m.group(1))
        return dict(sorted(out.items()))
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


# A page object is used where code builds it or holds one: "new AccountFile(", "AccountFile file =".
# A bare word ("Admin" in a string or comment) is not a use.
_PAGE_USE = re.compile(r"\bnew\s+([A-Z]\w*)\s*\(|\b([A-Z]\w*)(?:<[^<>;]*>)?\s+[a-z]\w*\s*[=;,)]")


def _page_users(repo_dir: str, source_root: str, pages: set[str]) -> dict[str, set[str]]:
    """{page class: classes in non-generated code that refer to it}, for the given page classes
    (Guidewire 10 names end in Page, Guidewire 9 names are the screen's own)."""
    users: dict[str, set[str]] = {}
    for root, _dirs, files in os.walk(os.path.join(repo_dir, source_root)):
        parts = root.replace("\\", "/").split("/")
        if "datadriven" in parts or "generated" in parts:
            continue
        for name in files:
            if name.endswith(".java"):
                with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                    used = {a or b for a, b in _PAGE_USE.findall(fh.read())}
                    for page in used & pages:
                        users.setdefault(page, set()).add(name[:-5])
    return users


def screen_coverage(repo_dir: str, source_root: str, cssids_dir: str) -> list[dict]:
    """Per app: {app, name, screens, used, wizards: [(screen, users)], unused_wizards, used_screens}."""
    by_app = {app: _screens(cssids_dir, app) for app in APPS
              if os.path.isdir(os.path.join(cssids_dir, app)) or os.path.isfile(os.path.join(cssids_dir, f"{app}.cssids"))}
    users = _page_users(repo_dir, source_root, {p for screens in by_app.values() for p in screens.values()})
    out = []
    for app, screens in by_app.items():
        label = APPS[app]
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
