import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
import schema  # noqa: E402


def top_entry():
    with open(os.path.join(PLUGIN, "CHANGELOG.md"), encoding="utf-8") as f:
        text = f.read()
    sections = text.split("\n## ")
    return sections[1] if len(sections) > 1 else ""


class ChangelogTest(unittest.TestCase):
    def test_top_entry_names_current_schema_versions(self):
        entry = top_entry()
        self.assertIn(f"plan schemaVersion {schema.PLAN_SCHEMA_VERSION}", entry)
        self.assertIn(f"project schemaVersion {schema.PROJECT_SCHEMA_VERSION}", entry)


if __name__ == "__main__":
    unittest.main()
