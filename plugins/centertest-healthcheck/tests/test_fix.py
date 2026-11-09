import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from eir_fix import _with_import, fix_line


class FixLineTest(unittest.TestCase):
    def test_a_widget_gets_its_own_assertion(self):
        self.assertEqual(fix_line("    page.getCard().getCurrentEvent().equals(getEventName());\n", False),
                         "    page.getCard().getCurrentEvent().assertEquals(getEventName());\n")

    def test_a_value_is_asserted_with_the_framework_factory(self):
        self.assertEqual(fix_line("  status.getValue().equals(expected);\r\n", False),
                         "  Assertions.assertThat(status.getValue()).isEqualTo(expected);\r\n")
        self.assertEqual(fix_line("  name.equalsIgnoreCase(\"abc\");\n", True),
                         "  com.ankrpt.centertest.assertion.Assertions.assertThat(name).isEqualToIgnoringCase(\"abc\");\n")

    def test_anything_but_a_plain_statement_is_left_alone(self):
        self.assertIsNone(fix_line("    if (a.equals(b)) {\n", False))
        self.assertIsNone(fix_line("    boolean same = a.equals(b);\n", False))


class ImportTest(unittest.TestCase):
    def test_import_added_once_or_qualified_beside_raw_assertj(self):
        lines = ["package a;\n", "\n", "import x.Y;\n", "\n", "class C {}\n"]
        out, qualified = _with_import(lines)
        self.assertFalse(qualified)
        self.assertEqual(out[3], "import com.ankrpt.centertest.assertion.Assertions;\n")
        raw = ["package a;\n", "import org.assertj.core.api.Assertions;\n", "class C {}\n"]
        out, qualified = _with_import(raw)
        self.assertTrue(qualified)
        self.assertEqual(out, raw)


if __name__ == "__main__":
    unittest.main()
