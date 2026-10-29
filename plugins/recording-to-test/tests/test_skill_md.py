import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), "skills", "recording-to-test", "SKILL.md")


class SkillTextTest(unittest.TestCase):
    def test_no_dollar_digit(self):
        """Claude Code replaces $0, $1… in a skill with its arguments when it loads, so "Comprehensive $1,000"
        reaches the model as "Comprehensive <recording path>,000"."""
        with open(SKILL, encoding="utf-8") as f:
            found = [f"{n}: {line.strip()}" for n, line in enumerate(f, 1) if re.search(r"\$\d", line)]
        self.assertEqual(found, [], "write amounts without a $ before the digit")


if __name__ == "__main__":
    unittest.main()
