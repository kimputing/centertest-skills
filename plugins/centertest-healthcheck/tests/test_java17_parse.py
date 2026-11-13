"""Java 14-17 syntax (switch expressions, yield, records, instanceof patterns, text blocks) no longer
makes a file unparseable: javalang reads a copy with method bodies emptied and records lowered to
classes, while bodies are still sliced from the real source."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

try:
    import javalang  # noqa: F401
    HAS_JAVALANG = True
except ImportError:
    HAS_JAVALANG = False

EXIT = """package com.acme.exits;

public class ValueGeneratorExit {
  private static final String TEMPLATE = \"\"\"
      {"a": 1}
      \"\"\";

  public String generate(String field) {
    return switch (field) {
      case "A" -> {
        String v = "x";
        yield v;
      }
      default -> "";
    };
  }

  public boolean isRow(Object o) {
    if (o instanceof AbstractTestData row) {
      return row.isEnabled();
    }
    var cssid = switch (o.hashCode()) { case 1 -> "a"; default -> "b"; };
    return cssid.isEmpty();
  }
}
"""

RECORD = """package com.acme.reusable;

@CenterTest
public class ReformVerifyAccident {
  public record CoverageCheck(String label, @Nullable String value) implements Check {
    public CoverageCheck {
      Objects.requireNonNull(label);
    }

    public boolean matches(String other) {
      return label.equals(other);
    }
  }

  public static class Helper {
    void help() {}
  }

  public void verify(CoverageCheck check) {
    System.out.println(check.label());
  }
}
"""

TOP_RECORD = """package com.acme.reusable;

public record Pair<A, B>(A first,
                         B second) {
  public A left() {
    return first;
  }
}
"""


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class Java17ParseTest(unittest.TestCase):
    def parse(self, rel, text):
        from eir_parser import parse_file
        repo = "/repo"
        return parse_file(text, os.path.join(repo, "src/main/java", rel), repo)

    def test_switch_expressions_yield_patterns_and_text_blocks_parse(self):
        f = self.parse("com/acme/exits/ValueGeneratorExit.java", EXIT)
        self.assertFalse(f.cannot_compile, f.parse_error)
        self.assertEqual([m.name for m in f.main_class.methods], ["generate", "isRow"])
        gen, is_row = f.main_class.methods
        self.assertEqual(EXIT.splitlines()[gen.line - 1].strip(), "public String generate(String field) {")
        self.assertIn("yield v;", gen.body)  # bodies come from the real source, not the emptied copy
        self.assertIn("instanceof AbstractTestData row", is_row.body)
        template = f.main_class.fields[0]
        self.assertEqual((template.name, template.line), ("TEMPLATE", 4))

    def test_nested_record_with_compact_constructor_and_methods(self):
        f = self.parse("com/acme/reusable/ReformVerifyAccident.java", RECORD)
        self.assertFalse(f.cannot_compile, f.parse_error)
        self.assertEqual(f.main_class.annotations, ["CenterTest"])
        self.assertEqual([m.name for m in f.main_class.methods], ["verify"])
        self.assertEqual([c.class_name for c in f.inner_classes], ["Helper"])  # records stay out of 2002
        rec = f.other_types[0]
        self.assertEqual((rec.class_name, rec.kind, rec.line, rec.interfaces), ("CoverageCheck", "record", 5, ["Check"]))
        self.assertEqual([m.name for m in rec.methods], ["CoverageCheck", "matches"])
        self.assertIn("Objects.requireNonNull(label);", rec.methods[0].body)
        self.assertEqual(rec.methods[1].line, 10)

    def test_top_level_record_is_not_the_main_class(self):
        f = self.parse("com/acme/reusable/Pair.java", TOP_RECORD)
        self.assertFalse(f.cannot_compile, f.parse_error)
        self.assertIsNone(f.main_class)
        rec = f.other_types[0]
        self.assertEqual((rec.kind, rec.key, [m.name for m in rec.methods]), ("record", "com.acme.reusable.Pair", ["left"]))
        self.assertEqual(rec.methods[0].line, 5)

    def test_java8_files_parse_exactly_as_before(self):
        from eir_parser import _lower_for_javalang
        plain = "class A {\n  @Foo({\"a\", \"b\"}) int[] x = {1, 2};\n  void m() { int y = 1; }\n}\n"
        lowered, records = _lower_for_javalang(plain)
        self.assertEqual(lowered.count("\n"), plain.count("\n"))
        self.assertIn('@Foo({"a", "b"}) int[] x = {1, 2};', lowered)  # annotation and array values are kept
        self.assertNotIn("int y", lowered)
        self.assertEqual(records, set())


if __name__ == "__main__":
    unittest.main()
