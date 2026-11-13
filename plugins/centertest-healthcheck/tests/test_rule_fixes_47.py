"""Issue #47: parser additions (annotation arguments, lines, other types, regex fallback) and the
fixes to rules 14002, 15005, 15006, 4001, 1003, the JSON section items and rule 0003."""

import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

try:
    import javalang  # noqa: F401
    HAS_JAVALANG = True
except ImportError:
    HAS_JAVALANG = False

TEST = """package com.acme.tests.pa.submission;

@CenterTest
public final class PA_SubmissionTest {
  private enum RestartPoints {ACCOUNT, POLICY}
  private static final String CODE = "Default";

  @CenterTestCase(testCaseId = "TC-1", timeout = 600)
  @DataDriven(datasource = "testdata/missing/PA_SubmissionDC.xlsx")
  public void run(ScenarioContext scenarioContext) {
    var vehicleDDT = load();
    return;
  }

  Object load() {
    var vehicleDDT = find();
    return vehicleDDT == null ? null : vehicleDDT.getName();
  }

  void swallow() {
    try { go(); } catch (IllegalStateException e) {
      // ignore
    }
  }

  void asserts(String a, String b) {
    Assertions.assertThat(a).as("first").isEqualTo(b);
    Assertions.assertThat(a).as("second").isEqualTo(b);
    Assertions.assertThat(a).as("third").isEqualTo(b);
  }
}
"""

FACADE = """package com.acme.reusable;
public interface PC {
  static AddVehicle addVehicle(InvocationContext c) { return new AddVehicle(c); }
  static Renew renew(InvocationContext c) { return new Renew(c); }
}
"""

MODERN = """package com.acme.util;
@CenterTest
public class Modern {
  private static final int SIZE = switch (1) { case 1 -> 2; default -> 3; };  // still unreadable: not in a body
  public String pick(Object o) {
    return switch (o) { case String s -> s; default -> ""; };
  }
  public void other() {
    System.out.println("x");
  }
}
"""


def _tree(files: dict) -> str:
    tmp = tempfile.mkdtemp()
    for rel, text in files.items():
        path = os.path.join(tmp, "src", "main", "java", *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
    return tmp


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class Issue47FixesTest(unittest.TestCase):
    def setUp(self):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        self.tmp = _tree({"com/acme/tests/pa/submission/PA_SubmissionTest.java": TEST,
                          "com/acme/reusable/PC.java": FACADE,
                          "com/acme/util/Modern.java": MODERN})
        self.files = parse_directory(self.tmp, "src/main/java", [], [], True, None)
        self.commits = {LOCAL_COMMIT: self.files}
        self.config = SimpleNamespace(repository_dir=self.tmp, source_root="src/main/java",
                                      get_threshold=lambda rid, default: default)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def file(self, name):
        return next(f for f in self.files if f.file_name == name)

    def test_parser_keeps_annotation_arguments_lines_and_other_types(self):
        f = self.file("PA_SubmissionTest.java")
        run = next(m for m in f.main_class.methods if m.name == "run")
        self.assertEqual(run.annotation_args["CenterTestCase"], {"testCaseId": "TC-1", "timeout": "600"})
        self.assertEqual(run.annotation_args["DataDriven"]["datasource"], "testdata/missing/PA_SubmissionDC.xlsx")
        self.assertEqual(run.parameters, [("ScenarioContext", "scenarioContext")])
        self.assertEqual(f.source.splitlines()[run.line - 1].strip(), "public void run(ScenarioContext scenarioContext) {")
        enum = f.other_types[0]
        self.assertEqual((enum.kind, [c.name for c in enum.fields]), ("enum", ["ACCOUNT", "POLICY"]))
        self.assertEqual(f.inner_classes, [])  # nested enums stay out of 2002's inner-class comparison
        code = next(fl for fl in f.main_class.fields if fl.name == "CODE")
        self.assertEqual(code.initializer, '"Default"')
        facade = self.file("PC.java").other_types[0]
        self.assertEqual((facade.kind, [m.name for m in facade.methods]), ("interface", ["addVehicle", "renew"]))

    def test_unparsable_file_keeps_its_methods_and_is_reported(self):
        f = self.file("Modern.java")
        self.assertTrue(f.cannot_compile)
        self.assertIn("line", f.parse_error)
        self.assertEqual([m.name for m in f.main_class.methods], ["pick", "other"])
        self.assertIn("CenterTest", f.main_class.annotations)
        self.assertIn('System.out.println("x");', f.main_class.methods[1].body)
        import rules.rule_parsing as rp
        rows = rp.unparsed_files(self.commits, self.config).rows
        self.assertEqual([(r[0], r[2]) for r in rows], [("Modern.java", 2)])
        self.assertTrue(rows[0][3].startswith("src/main/java/com/acme/util/Modern.java:"))

    def test_14002_reports_a_datasource_that_does_not_exist(self):
        import rules.rule_ddt as rd
        rows = rd.datasource_file_check(self.commits, self.config).rows
        self.assertEqual(rows, [["PA_SubmissionTest", "run", "testdata/missing/PA_SubmissionDC.xlsx", "File not found"]])
        os.makedirs(os.path.join(self.tmp, "testdata", "missing"))
        open(os.path.join(self.tmp, "testdata", "missing", "PA_SubmissionDC.xlsx"), "w").close()
        self.assertEqual(rd.datasource_file_check(self.commits, self.config).rows, [])

    def test_15005_reports_a_catch_that_holds_only_a_comment(self):
        import rules.rule_quality as rq
        rows = rq.empty_catch_blocks(self.commits, self.config).rows
        self.assertIn(["PA_SubmissionTest", "swallow"], rows)

    def test_15006_does_not_read_return_x_equals_as_a_declaration(self):
        import rules.rule_quality as rq
        rows = rq.unused_variables(self.commits, self.config).rows
        self.assertEqual([(r[1], r[2]) for r in rows if r[0] == "PA_SubmissionTest"], [("run", "vehicleDDT")])

    def test_4001_skips_assertion_chains_and_1003_skips_lob_transaction_names(self):
        import rules.rule_methods as rm
        import rules.rule_classnames as rc
        config = SimpleNamespace(**vars(self.config))
        config.get_threshold = lambda rid, default: 3
        self.assertEqual(rm.variable_substitutions(self.commits, config).sections, [])
        self.assertEqual(rc.package_name_in_class(self.commits, self.config).sections, [])

    def test_json_lists_the_items_of_section_rules(self):
        from eir_json import section_items
        from eir_models import Section
        sections = [Section(title="Commit local", subsections=[Section(title="A.m", items=["3x — a.b()"])])]
        self.assertEqual(section_items(sections), ["Commit local > A.m > 3x — a.b()"])


if __name__ == "__main__":
    unittest.main()
