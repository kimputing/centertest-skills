import filecmp
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
PLUGINS = os.path.dirname(PLUGIN)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
sys.path.insert(0, os.path.join(PLUGINS, "ddt-tools", "tests"))

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

VENDORED = ("ddt_refcheck.py", "ddt_reference_scope.py")


class VendoredRefcheckTest(unittest.TestCase):
    def test_vendored_copies_match_ddt_tools(self):
        for name in VENDORED:
            mine = os.path.join(PLUGIN, "scripts", name)
            source = os.path.join(PLUGINS, "ddt-tools", "scripts", name)
            self.assertTrue(
                filecmp.cmp(mine, source, shallow=False),
                f"plugins/centertest-healthcheck/scripts/{name} must be an unchanged copy of "
                f"plugins/ddt-tools/scripts/{name}; copy it again with: "
                f"cp plugins/ddt-tools/scripts/{name} plugins/centertest-healthcheck/scripts/")


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class DdtRulesAgreeWithValidatorTest(unittest.TestCase):
    def test_14003_plus_14004_equal_the_validator(self):
        from refcheck_fixture import build_project
        import rules.rule_ddt as rule_ddt
        tmp = tempfile.mkdtemp()
        try:
            build_project(tmp)
            config = SimpleNamespace(repository_dir=tmp, source_root="src/main/java")
            refs = rule_ddt.ddt_reference_integrity({}, config)
            rels = rule_ddt.ddt_relationship_integrity({}, config)
            self.assertEqual(sorted((r[1], r[2], r[3]) for r in refs.rows),
                             [(3, "@Submission.#Coverage", "Terrorism"), (4, "#Company", "Nope")])
            self.assertEqual([(r[1], r[2], r[3]) for r in rels.rows], [(4, "@Submission", "Missing")])
        finally:
            shutil.rmtree(tmp)



@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class RunsInTest(unittest.TestCase):
    """A data finding blocks only when a test runs it: its workbook is read and the row is enabled."""

    def setUp(self):
        from refcheck_fixture import build_project, make_xlsx
        import rules.rule_ddt as rule_ddt
        self.rule_ddt = rule_ddt
        self.make_xlsx = make_xlsx
        self.tmp = tempfile.mkdtemp()
        build_project(self.tmp)
        rule_ddt._USERS_CACHE.clear()
        rule_ddt._REFCHECK_CACHE.clear()
        self.config = SimpleNamespace(repository_dir=self.tmp, source_root="src/main/java")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write_java(self, name, body):
        folder = os.path.join(self.tmp, "src", "main", "java", "com", "acme")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name + ".java"), "w") as fh:
            fh.write(f"package com.acme;\npublic class {name} {{\n{body}\n}}\n")

    def runs_in(self):
        rows = self.rule_ddt.ddt_reference_integrity({}, self.config).rows + \
               self.rule_ddt.ddt_relationship_integrity({}, self.config).rows
        return {(r[1], r[3]): r[5] for r in rows}

    def test_workbook_no_test_reads_is_not_run(self):
        self.assertEqual(set(self.runs_in().values()), {self.rule_ddt.NOT_RUN_UNUSED})

    def test_datadriven_reader_is_named(self):
        self.write_java("PolicyChangeTest",
                        '@DataDriven(datasource = "testdata/wc/WC_PolicyChangeDC.xlsx")\npublic void run() {}')
        self.assertEqual(set(self.runs_in().values()), {"PolicyChangeTest"})

    def test_disabled_row_is_not_run(self):
        self.make_xlsx(os.path.join(self.tmp, "testdata", "wc", "WC_PolicyChangeDC.xlsx"), {
            "DataCombination": [["Code", "Disabled", "#Company"], ["Ok", "", "Acme"],
                                ["Off", "True", "Nope"], ["On", "", "Nope"]]})
        self.write_java("PolicyChangeTest", "Object d = DDTHelper.getWcWC_PolicyChangeDC(scenarioContext);")
        helper = os.path.join(self.tmp, "src", "main", "java", "com", "acme", "generated", "datadriven")
        os.makedirs(helper)
        with open(os.path.join(helper, "DDTHelper.java"), "w") as fh:
            fh.write('public static x.WC_PolicyChangeDC getWcWC_PolicyChangeDC(String code) '
                     '{return new x.WC_PolicyChangeDC(p("testdata/wc/WC_PolicyChangeDC.xlsx", code));}\n')
        self.assertEqual(self.runs_in(), {(3, "Nope"): self.rule_ddt.NOT_RUN_DISABLED, (4, "Nope"): "PolicyChangeTest"})

    def test_related_dc_inherits_the_readers(self):
        self.make_xlsx(os.path.join(self.tmp, "testdata", "wc", "WC_SubmissionDC.xlsx"), {
            "DataCombination": [["Code", "#Company"], ["Default", "Ghost"]]})
        self.write_java("PolicyChangeTest",
                        '@DataDriven(datasource = "testdata/wc/WC_PolicyChangeDC.xlsx")\npublic void run() {}')
        self.assertEqual(self.runs_in()[(2, "Ghost")], "PolicyChangeTest")


if __name__ == "__main__":
    unittest.main()
