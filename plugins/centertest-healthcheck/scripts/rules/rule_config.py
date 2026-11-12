"""
Rule 25001 (category Config): a role the tests log in as that no environment definition declares.

How CenterTest finds a user (centertest-platform, verified):
  * `ScenarioContext.getInvocationContext(key)` creates `new InvocationContext(key, ...)`, whose
    constructor calls `User.getUser(key)` at once (runner/context/InvocationContext.java).
  * `User.getProperty` (runtime/User.java) looks up, first hit wins:
        centertest.user.<role>.<env>, centertest.user.<role>.*, centertest.user.<role>,
        centertest.user.*.<env>, centertest.user.<env>, centertest.user.*.*, centertest.user
    and otherwise throws UserNotFoundException USER_NOT_FOUND_FOR_ENVIRONMENT ("User %s not found for
    environment %s"). A `<key>.secret` entry points the same key at the secret provider.
  * Properties come from the classpath files centertest.properties, core.properties,
    runtime_environments.properties, customer.centertest.properties and profile.<p>.properties
    (properties/GetProperties.loadProperties), then CENTERTEST_* environment variables, JVM -D options,
    the user's own user.properties, and a runtime_environments.properties under
    centertest.runtime.path.customurl. Docs: overview/environments-users-producers.adoc.

Only the project's own files can be read, so the rule speaks only when the project itself defines users
(at least one role-specific centertest.user.<role>... key under src/main/resources) and points nowhere
else (no centertest.runtime.path.customurl). Any wildcard (centertest.user.*.<env>, centertest.user.*.*,
centertest.user, centertest.user.<env>) covers every role, so nothing is reported then. Property values
are never read into a row: only key names.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule
from rule_helpers import ProjectIndex, balanced_end, file_location, latest_files, location
from rules.rule_testdata import _Java, _is_generated, _literal, _split_args

_PREFIX = "centertest.user"
_CUSTOM_URL = "centertest.runtime.path.customurl"
_ROLE_CALL = re.compile(r"\b(?:getInvocationContext|User\s*\.\s*getUser)\s*\(")
_URL_KEY = re.compile(r"^([\w-]+)\.[\w-]+\.url$")


def _property_keys(path: str) -> list[tuple[str, int]]:
    """[(key, line)] of a .properties file: comments, blank lines and continuation lines skipped,
    the key ends at the first unescaped '=', ':' or whitespace. Values are never kept."""
    out = []
    try:
        with open(path, encoding="latin-1") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return out
    continued = False
    for no, raw in enumerate(lines, start=1):
        s = raw.lstrip()
        was_continued = continued
        continued = (len(raw) - len(raw.rstrip("\\"))) % 2 == 1  # odd trailing backslashes continue the value
        if was_continued or not s or s[0] in "#!":
            continue
        key, i = [], 0
        while i < len(s):
            ch = s[i]
            if ch == "\\" and i + 1 < len(s):
                key.append(s[i + 1])
                i += 2
                continue
            if ch in "=:" or ch.isspace():
                break
            key.append(ch)
            i += 1
        if key:
            out.append(("".join(key), no))
    return out


def _resource_keys(repo_dir: str) -> list[tuple[str, str, int]]:
    """[(key, file, line)] from every .properties file under src/main/resources (the classpath CenterTest reads)."""
    root = os.path.join(repo_dir, "src", "main", "resources")
    keys = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.endswith(".properties"):
                path = os.path.join(dirpath, name)
                keys += [(k, path, no) for k, no in _property_keys(path)]
    return sorted(keys, key=lambda t: (t[1], t[2]))


def _code_roles(commits: CommitsDict):
    """[(role, file, offset, _Java)] for getInvocationContext("role") / User.getUser("role"), the role a
    literal or a final String constant of the class (or a superclass)."""
    files = [f for f in latest_files(commits) if f.main_class is not None and not _is_generated(f)]
    idx = ProjectIndex(latest_files(commits))
    out = []
    for f in sorted(files, key=lambda x: x.key):
        if "getInvocationContext" not in (f.source or "") and "getUser" not in (f.source or ""):
            continue
        j = _Java(f, idx)
        for m in _ROLE_CALL.finditer(j.masked):
            open_i = m.end() - 1
            args = _split_args(j.text, j.masked, open_i + 1, balanced_end(j.masked, open_i) - 1)
            if len(args) != 1:
                continue
            role = _literal(args[0][0])
            if role is None:
                const = j.constant(args[0][0])
                role = const[1] if const else None
            if role and role.strip():
                out.append((role.strip(), f, m.start(), j))
    return out


@rule(id="25001", description="Role not defined in any environment", category="Config")
def undefined_role(commits: CommitsDict, config) -> RuleResult:
    """`getInvocationContext("role")` (or `User.getUser("role")`) for a role no environment defines.

    Heuristic: the role is a string literal or a same-class/superclass final String constant. The
    project's user keys are read from every .properties file under src/main/resources (key names only).
    A role counts as defined by centertest.user.<role>[.<env>][.secret] (case-insensitive), and every role
    by a wildcard: centertest.user, centertest.user.*..., or centertest.user.<x> where <x> is not a role
    the code uses (it may be an environment). Guards: nothing is reported when the project defines no
    role-specific user key (users then come from CI variables or user.properties) or sets
    centertest.runtime.path.customurl (environments live in another folder). One row per class and role.
    """
    result = RuleResult(rule_id="25001", description="Role not defined in any environment", category="Config",
                        headers=["Class", "Method", "Line", "Issue", "Location"])
    repo = getattr(config, "repository_dir", "") or ""
    keys = _resource_keys(repo)
    if any(k == _CUSTOM_URL for k, _p, _n in keys):
        return result
    uses = _code_roles(commits)
    if not uses:
        return result
    used = {r.lower() for r, *_ in uses}
    defined, wildcard, sources = set(), False, {}
    for key, path, no in keys:
        if key != _PREFIX and not key.startswith(_PREFIX + "."):
            continue
        tail = key[len(_PREFIX) + 1:]
        if tail.endswith(".secret"):
            tail = tail[: -len(".secret")]
        parts = tail.split(".") if tail else []
        if parts and parts[0] == "properties":  # centertest.user.properties.override: not a user
            continue
        if not parts or parts[0] == "*" or (len(parts) == 1 and parts[0].lower() not in used):
            wildcard = True
            continue
        defined.add(parts[0].lower())
        sources.setdefault(parts[0].lower(), file_location(path, no, config))
    if wildcard or not defined:
        return result
    listed = ", ".join(sorted(defined)[:6]) + (", ..." if len(defined) > 6 else "")
    seen = set()
    for role, f, offset, j in uses:
        if role.lower() in defined:
            continue
        line = j.line(offset)
        cname, mname = j.where(line)
        if (cname, role) in seen:
            continue
        seen.add((cname, role))
        result.rows.append([cname, mname, j.code_line(line),
                            f'Role "{role}" has no user in the project\'s properties (no centertest.user.{role}.<env> '
                            f"key and no wildcard; defined roles: {listed}), so this login throws "
                            f"USER_NOT_FOUND_FOR_ENVIRONMENT unless CI or a local user.properties supplies it",
                            location(f, line, config)])
    return result
