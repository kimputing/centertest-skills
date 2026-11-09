import os
import re
import unittest

SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "skills", "ddt-tools", "SKILL.md")


class SkillPythonSelectionTest(unittest.TestCase):
    """The skill must pick an interpreter that can import its packages, not just any python3:
    Homebrew's python3 can be a fresh version with no packages and pip refuses to install into it."""

    def setUp(self):
        with open(SKILL, encoding="utf-8") as fh:
            self.text = fh.read()

    def test_every_python_choice_checks_the_packages(self):
        choices = re.findall(r"^PYTHON=.*$", self.text, flags=re.M)
        self.assertTrue(choices)
        for line in choices:
            self.assertIn('-c "import openpyxl"', line)
            self.assertIn(".centertest/venv/bin/python", line)
            self.assertNotIn("command -v", line)  # breaks on Windows Git Bash

    def test_the_skill_explains_the_one_time_environment(self):
        self.assertIn("## Python with the packages", self.text)
        self.assertIn('-m venv "$HOME/.centertest/venv"', self.text)


if __name__ == "__main__":
    unittest.main()
