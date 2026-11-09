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


if __name__ == "__main__":
    unittest.main()
