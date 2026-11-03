"""Instruction tests: the skill text may only name files, anchors, commands, flags and plan fields
that exist, and must keep every carried-over rule (rule_markers.MARKERS)."""
import contextlib
import io
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
SKILL_DIR = os.path.join(PLUGIN, "skills", "recording-to-test")
SKILL = os.path.join(SKILL_DIR, "SKILL.md")
PHASES = ("understand", "recording", "reuse", "code", "data", "restart", "verify", "profile")

sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
sys.path.insert(0, HERE)
import ct  # noqa: E402
import schema  # noqa: E402
from rule_markers import MARKERS  # noqa: E402

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
HTML_ANCHOR = re.compile(r'<a\s+(?:id|name)="([^"]+)"')
FILE_REF = re.compile(r"(phases/[\w-]+\.md|SKILL\.md)(?:#([\w-]+))?")
LOCAL_LINK = re.compile(r"\]\(#([\w-]+)\)")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
CT_CALL = re.compile(r'ct\.py"?\s+([\w-]+)(.*)')
FLAG = re.compile(r"(?<![\w-])(--[A-Za-z][\w-]*)")
PLAN_FIELD = re.compile(r"`plan\.([A-Za-z_]\w*)")
# `plan.json` / `plan.md` are file names, not plan fields
PLAN_FILE_SUFFIXES = {"json", "md"}


def skill_files():
    found = []
    for folder, _dirs, files in os.walk(SKILL_DIR):
        found += [os.path.join(folder, name) for name in files if name.endswith(".md")]
    return sorted(found)


def rel(path):
    return os.path.relpath(path, SKILL_DIR).replace(os.sep, "/")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def slug(text):
    """GitHub heading slug: markup and punctuation dropped, lower-case, each space a hyphen."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # a link keeps its text
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def anchors(text):
    """Every anchor a file exposes: heading slugs (duplicates get -1, -2…) and <a id="…">."""
    found, seen, fenced = set(HTML_ANCHOR.findall(text)), {}, False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        match = None if fenced else HEADING.match(line)
        if match:
            base = slug(match.group(1))
            count = seen.get(base, 0)
            seen[base] = count + 1
            found.add(base if count == 0 else f"{base}-{count}")
    return found


def code_segments(text):
    """Shell and inline code: fenced lines (backslash continuations joined) and `…` spans."""
    segments, fenced, pending = [], False, ""
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            pending += line.rstrip()
            if pending.endswith("\\"):
                pending = pending[:-1] + " "
            else:
                segments.append(pending)
                pending = ""
        else:
            segments += INLINE_CODE.findall(line)
    if pending:
        segments.append(pending)
    return segments


def help_text(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            ct.main(argv)
        except SystemExit:
            pass
    return out.getvalue() + err.getvalue()


class SkillTextTest(unittest.TestCase):
    def setUp(self):
        self.files = {rel(path): read(path) for path in skill_files()}
        self.assertIn("SKILL.md", self.files)

    def test_no_dollar_digit(self):
        """Claude Code replaces $0, $1… in a skill with its arguments when it loads, so "Comprehensive $1,000"
        reaches the model as "Comprehensive <recording path>,000"."""
        found = [f"{name}:{n}: {line.strip()}" for name, text in self.files.items()
                 for n, line in enumerate(text.splitlines(), 1) if re.search(r"\$\d", line)]
        self.assertEqual(found, [], "write amounts without a $ before the digit")

    def test_skill_md_under_300_lines(self):
        self.assertLessEqual(len(self.files["SKILL.md"].splitlines()), 300)

    def test_every_phase_file_has_a_gate(self):
        missing = [p for p in PHASES if "gate" not in anchors(self.files.get(f"phases/{p}.md", ""))]
        self.assertEqual(missing, [], "each phases/<phase>.md exists and has a '## Gate' heading")

    def test_references_resolve(self):
        exposed = {name: anchors(text) for name, text in self.files.items()}
        broken = []
        for name, text in self.files.items():
            for target, anchor in FILE_REF.findall(text):
                if target not in exposed:
                    broken.append(f"{name}: {target} does not exist")
                elif anchor and anchor not in exposed[target]:
                    broken.append(f"{name}: {target}#{anchor} has no such heading or anchor")
            for anchor in LOCAL_LINK.findall(text):
                if anchor not in exposed[name]:
                    broken.append(f"{name}: #{anchor} has no such heading or anchor")
        self.assertEqual(broken, [])

    def test_ct_commands_and_flags_exist(self):
        helps, wrong = {}, []
        for name, text in self.files.items():
            for segment in code_segments(text):
                for command, rest in CT_CALL.findall(segment):
                    if command not in ct.COMMANDS:
                        wrong.append(f"{name}: ct.py {command}: no such command")
                        continue
                    rest = re.split(r"\||;|&&", rest)[0]
                    argv = [command]
                    top = helps.setdefault(command, help_text([command, "-h"]))
                    choices = re.search(r"\{([\w,-]+)\}", top)
                    if choices:  # a command with subcommands: flags belong to the subcommand
                        words = rest.split()
                        sub = words[0] if words else ""
                        if sub not in choices.group(1).split(","):
                            wrong.append(f"{name}: ct.py {command} {sub}: no such subcommand")
                            continue
                        argv.append(sub)
                    usage = helps.setdefault(" ".join(argv), help_text(argv + ["-h"]))
                    for flag in FLAG.findall(rest):
                        if not re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", usage):
                            wrong.append(f"{name}: ct.py {' '.join(argv)} has no {flag}")
        self.assertEqual(wrong, [])

    def test_plan_fields_exist(self):
        unknown = [f"{name}: plan.{field}" for name, text in self.files.items()
                   for field in PLAN_FIELD.findall(text)
                   if field not in schema.PLAN_FIELDS and field not in PLAN_FILE_SUFFIXES]
        self.assertEqual(unknown, [])

    def test_rule_markers_present(self):
        missing = [f"{name}: {phrase!r}" for name, phrase in MARKERS
                   if phrase not in self.files.get(name, "")]
        self.assertEqual(missing, [])

    def test_no_script_paths_into_other_plugins(self):
        found = [f"{name}:{n}: {line.strip()}" for name, text in self.files.items()
                 for n, line in enumerate(text.splitlines(), 1)
                 if "plugins/" in line or "marketplaces/" in line]
        self.assertEqual(found, [], "call helpers as skills; plugins are copied to a cache on install")


class SlugTest(unittest.TestCase):
    def test_github_rules(self):
        self.assertEqual(slug('"Just run it"'), "just-run-it")
        self.assertEqual(slug("Plan `schemaVersion`"), "plan-schemaversion")
        self.assertEqual(slug("Phases and gates"), "phases-and-gates")

    def test_duplicate_headings_are_numbered(self):
        self.assertEqual(anchors("## Gate\n## Gate\n```\n## Not\n```\n<a id=\"x\"></a>"),
                         {"gate", "gate-1", "x"})


if __name__ == "__main__":
    unittest.main()
