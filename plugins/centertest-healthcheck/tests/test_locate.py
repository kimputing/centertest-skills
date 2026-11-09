import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from eir_locate import _lookup, find_line

SOURCE = """package com.acme;

public class DelinquencyEvent {
    public void run() {
        validate();
    }

    @Override
    protected boolean validate(String a) {
        a.equals("x");
        return true;
    }

    static class Row {
        void check() {
        }
    }
}
""".splitlines()


class FindLineTest(unittest.TestCase):
    def test_snippet_line_wins(self):
        self.assertEqual(find_line(SOURCE, "DelinquencyEvent", "validate", 'a.equals("x");'), 10)

    def test_method_declaration_not_a_call(self):
        self.assertEqual(find_line(SOURCE, "DelinquencyEvent", "validate", None), 9)

    def test_inner_class_method(self):
        self.assertEqual(find_line(SOURCE, "DelinquencyEvent.Row", "check", None), 15)

    def test_class_declaration_when_no_method(self):
        self.assertEqual(find_line(SOURCE, "com.acme.DelinquencyEvent", None, None), 3)


class LookupTest(unittest.TestCase):
    def test_fully_qualified_and_inner_names(self):
        index = {"DelinquencyEvent": "/p/A.java", "DelinquencyEvent.Row": "/p/A.java", "Other": "/p/B.java"}
        self.assertEqual(_lookup(index, "com.acme.DelinquencyEvent"), "/p/A.java")
        self.assertEqual(_lookup(index, "DelinquencyEvent.Row"), "/p/A.java")
        self.assertIsNone(_lookup(index, "Missing"))


if __name__ == "__main__":
    unittest.main()
