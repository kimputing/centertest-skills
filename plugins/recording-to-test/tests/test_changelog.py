import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
import schema  # noqa: E402


def top_entry(text=None):
    if text is None:
        with open(os.path.join(PLUGIN, "CHANGELOG.md"), encoding="utf-8") as f:
            text = f.read()
    sections = text.split("\n## ")
    return sections[1] if len(sections) > 1 else ""


def problems(entry):
    found = []
    if not re.match(r"\d+\.\d+\.\d+", entry):
        found.append("heading does not start with a version")
    for kind, n in (("plan", schema.PLAN_SCHEMA_VERSION), ("project", schema.PROJECT_SCHEMA_VERSION)):
        if not re.search(rf"{kind} schemaVersion {n}\b", entry):
            found.append(f"missing {kind} schemaVersion {n}")
    return found


class ChangelogTest(unittest.TestCase):
    def test_top_entry_names_current_schema_versions(self):
        self.assertEqual(problems(top_entry()), [])

    def test_guard_rejects_prefix_match_and_missing_version(self):
        self.assertTrue(problems("2.0.0 — x\n- plan schemaVersion 20\n- project schemaVersion 2\n"))
        self.assertTrue(problems("scenario wizard\n- plan schemaVersion 2\n- project schemaVersion 2\n"))
        self.assertEqual(problems("2.0.0 — x\n- plan schemaVersion 2\n- project schemaVersion 2\n"), [])


if __name__ == "__main__":
    unittest.main()
