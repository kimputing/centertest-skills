import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from refcheck_fixture import POLICY_CHANGE_HEADERS, build_project


class ClassifyHeadersTest(unittest.TestCase):
    @unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
    def test_overrides_and_joins_are_not_reference_columns(self):
        import ddt_refcheck
        refs, rels, hops = ddt_refcheck.classify_headers(POLICY_CHANGE_HEADERS)
        self.assertEqual(refs, ["#Company"])
        self.assertEqual(rels, ["@Submission"])
        self.assertEqual(hops, [("@Submission.#Coverage", "Submission", "coverage")])


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class ValidateProjectTest(unittest.TestCase):
    def setUp(self):
        import ddt_refcheck
        self.engine = ddt_refcheck
        self.tmp = tempfile.TemporaryDirectory()
        build_project(self.tmp.name)
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        ddt_refcheck.reset_caches()

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_reports_only_real_breaks(self):
        findings = self.engine.validate_project()
        self.assertEqual(list(findings), ["testdata/wc/WC_PolicyChangeDC.xlsx"])
        got = sorted((row, col, code) for row, col, code, _s, _m in findings["testdata/wc/WC_PolicyChangeDC.xlsx"])
        self.assertEqual(got, [(3, "@Submission.#Coverage", "Terrorism"),
                               (4, "#Company", "Nope"),
                               (4, "@Submission", "Missing")])

    def test_hop_code_is_checked_in_the_related_dc_scope(self):
        errors = self.engine.validate_dc("testdata/wc/WC_PolicyChangeDC.xlsx")
        hop = [e for e in errors if e[1] == "@Submission.#Coverage"]
        self.assertEqual(len(hop), 1)
        self.assertEqual(hop[0][4], "code not found")
        self.assertFalse(any("unknown identifier" in e[4] for e in errors))


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class EmptyColumnTest(unittest.TestCase):
    def test_an_empty_column_naming_no_sheet_is_not_a_crash(self):
        import ddt_refcheck
        from refcheck_fixture import make_xlsx
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "testdata"))
            make_xlsx(os.path.join(tmp, "testdata", "OldDC.xlsx"),
                      {"DataCombination": [["Code", "#UWCompany"], ["Default", ""]]})
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                ddt_refcheck.reset_caches()
                self.assertEqual(ddt_refcheck.validate_dc("testdata/OldDC.xlsx"), [])
            finally:
                os.chdir(cwd)



@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class UsedCodesTest(unittest.TestCase):
    """A code is in use through a DC column, a relationship hop, another sheet's # column or a
    DDTHelper call in Java. Missing any of them makes the cleanup report delete live data."""

    def setUp(self):
        import ddt_refcheck
        from refcheck_fixture import build_project, make_xlsx
        self.engine = ddt_refcheck
        self.tmp = tempfile.TemporaryDirectory()
        build_project(self.tmp.name)
        make_xlsx(os.path.join(self.tmp.name, "testdata", "SharedData.xlsx"), {
            "Company": [["Code", "Name"], ["Acme", "Acme Inc"], ["Zed", "Zed Ltd"], ["Javaco", "J"]],
            "Address": [["Code", "City"], ["CA-LA", "Los Angeles"], ["NY-NYC", "New York"]],
            "Location": [["Code", "#Address"], ["HQ", "NY-NYC"]],
        })
        java = os.path.join(self.tmp.name, "src", "main", "java", "com", "acme")
        os.makedirs(os.path.join(java, "generated", "datadriven"))
        with open(os.path.join(java, "generated", "datadriven", "DDTHelper.java"), "w") as fh:
            fh.write('public static x.SharedData.Company getSharedDataCompany(String code) {return new x.SharedData('
                     'new TestDataProvider().provideDataRecordAsExcelInput("testdata/SharedData.xlsx", "company", code)).getCompany();}\n')
        with open(os.path.join(java, "SomeStep.java"), "w") as fh:
            fh.write('class SomeStep { void run() { DDTHelper.getSharedDataCompany("Javaco"); } }\n')
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        ddt_refcheck.reset_caches()

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_every_way_of_using_a_code_counts(self):
        used = self.engine.used_codes()
        self.assertIn("DC column", used["company"]["Acme"])
        self.assertEqual(used["coverage"]["Liability"], {"relationship hop"})
        self.assertEqual(used["address"]["NY-NYC"], {"reference sheet"})
        self.assertEqual(used["company"]["Javaco"], {"Java"})
        self.assertNotIn("Zed", used["company"])
        self.assertNotIn("<blank>", used["company"])  # a sentinel, not a code
        self.assertNotIn("company.name", used)  # an override holds a value


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class InstanceCopyTest(unittest.TestCase):
    """"Acme(2)" is the second copy of record Acme on the row (join scenarios), not a missing code."""

    def test_instance_copies_resolve_to_their_record(self):
        import ddt_refcheck
        from refcheck_fixture import build_project, make_xlsx
        with tempfile.TemporaryDirectory() as tmp:
            build_project(tmp)
            make_xlsx(os.path.join(tmp, "testdata", "wc", "WC_PolicyChangeDC.xlsx"), {
                "DataCombination": [["Code", "#Company"], ["Twice", "Acme, Acme(2)"], ["Bad", "Nope(2)"]]})
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                ddt_refcheck.reset_caches()
                errors = ddt_refcheck.validate_dc("testdata/wc/WC_PolicyChangeDC.xlsx")
                self.assertEqual([(e[0], e[2]) for e in errors], [(3, "Nope(2)")])
                self.assertIn("Acme", ddt_refcheck.used_codes()["company"])
                self.assertEqual(ddt_refcheck.base_code("Coupe(12)"), "Coupe")
                self.assertEqual(ddt_refcheck.base_code("Plan (A)"), "Plan (A)")
            finally:
                os.chdir(cwd)

if __name__ == "__main__":
    unittest.main()
