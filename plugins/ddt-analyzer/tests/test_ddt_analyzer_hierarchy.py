import importlib.util
import json
import os
import tempfile
import unittest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def load_analyzer():
    spec = importlib.util.spec_from_file_location("ddt_analyzer", os.path.join(PLUGIN, "scripts", "ddt-analyzer.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class HierarchyTest(unittest.TestCase):
    """A DC outside the optional class-inheritance entries is not a hierarchy issue."""

    def run_in(self, hierarchy):
        analyzer = load_analyzer()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "testdata", "wc"))
            with open(os.path.join(tmp, "testdata", "DataDrivenHierarchy.json"), "w") as fh:
                json.dump(hierarchy, fh)
            for name in ("testdata/SharedData.xlsx", "testdata/wc/WC_SubmissionDC.xlsx", "testdata/wc/WC_ParentDC.xlsx"):
                wb = openpyxl.Workbook()
                wb.active.title = "Company" if name.endswith("Data.xlsx") else "DataCombination"
                wb.active.append(["Code"])
                wb.save(os.path.join(tmp, name))
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                return analyzer.analyze_hierarchy()
            finally:
                os.chdir(cwd)

    def test_modern_hierarchy_has_no_uncovered_issues(self):
        rows = self.run_in({"$references": {"testdata/SharedData.xlsx": ["testdata/wc/.*DC\\.xlsx"]}})
        self.assertEqual([r for r in rows if r[1] not in ("OK", "MATCHED", "INFO")], [])
        self.assertFalse(any(r[1] in ("UNCOVERED", "INFO") for r in rows))

    def test_with_class_inheritance_uncovered_dcs_are_info(self):
        rows = self.run_in({"testdata/wc/WC_ParentDC.xlsx": ["testdata/other/.*"]})
        info = [r for r in rows if r[1] == "INFO"]
        self.assertEqual([r[0] for r in info], ["testdata/wc/WC_SubmissionDC.xlsx"])


if __name__ == "__main__":
    unittest.main()
