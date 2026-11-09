import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, os.path.join(PLUGINS, "ddt-tools", "tests"))

import eir_report  # noqa: E402
import eir_states  # noqa: E402

try:
    from refcheck_fixture import make_xlsx  # openpyxl: the reference walk reads it
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

TYPELIST = """package com.x.generated.typelist.pc;
public class TC_Jurisdiction extends com.ankrpt.centertest.guidewire.widget.TypeCode {
public static TC_Jurisdiction AZ() { return new TC_Jurisdiction("AZ", "Arizona", false); }
public static TC_Jurisdiction CA() { return new TC_Jurisdiction("CA", "California", false); }
public static TC_Jurisdiction TX() { return new TC_Jurisdiction("TX", "Texas", false); }
public static TC_Jurisdiction NV() { return new TC_Jurisdiction("NV", "Nevada", false); }
}
"""


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class StateCoverage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = os.path.join(self.tmp.name, "proj")
        gen = os.path.join(self.tmp.name, "gen", "src", "main")
        self.cssids = os.path.join(gen, "resources", "cssids")
        os.makedirs(os.path.join(self.cssids, "pc"))
        typelist = os.path.join(gen, "java", "com", "x", "generated", "typelist", "pc")
        os.makedirs(typelist)
        with open(os.path.join(typelist, "TC_Jurisdiction.java"), "w") as fh:
            fh.write(TYPELIST)
        os.makedirs(os.path.join(root, "testdata", "ca"))
        os.makedirs(os.path.join(root, "testdata", "gl"))
        with open(os.path.join(root, "testdata", "DataDrivenHierarchy.json"), "w") as fh:
            json.dump({"$references": {"testdata/SharedData.xlsx": ["testdata/.*DC\\.xlsx"]}}, fh)
        make_xlsx(os.path.join(root, "testdata", "SharedData.xlsx"), {
            "Address": [["Code", "City", "State"], ["phx", "Phoenix", "AZ"], ["aus", "Austin", "Texas"],
                        ["reno", "Reno", "NV"]]})
        make_xlsx(os.path.join(root, "testdata", "ca", "CA_SubmissionDC.xlsx"), {"DataCombination": [
            ["Code", "#Address", "Disabled"], ["Phoenix", "phx", ""], ["Austin", "aus", ""], ["Austin2", "aus", ""],
            ["Reno", "reno", "true"]]})  # a disabled row does not run: NV is nowhere
        make_xlsx(os.path.join(root, "testdata", "gl", "GL_SubmissionDC.xlsx"), {"DataCombination": [
            ["Code", "Jurisdiction", "Description"], ["Cal", "California", "Texas wording, not a state column"]]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_per_line_with_the_states_other_lines_use(self):
        lines = eir_states.state_coverage(self.root, self.cssids)
        self.assertEqual(lines, [
            {"line": "CA", "states": {"AZ": 1, "TX": 2}, "elsewhere": ["CA"]},  # "Texas" by name, two scenarios
            {"line": "GL", "states": {"CA": 1}, "elsewhere": ["AZ", "TX"]},
        ])

    def test_no_jurisdiction_typelist_no_panel(self):
        self.assertIsNone(eir_states.state_coverage(self.root, os.path.join(self.tmp.name, "nowhere")))
        self.assertIsNone(eir_states.state_coverage(self.root, None))

    def test_terminal_panel_and_excel(self):
        lines = eir_states.state_coverage(self.root, self.cssids)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            eir_states.print_states(lines)
        self.assertIn("JURISDICTIONS THE SCENARIOS RUN IN (3 in all", out.getvalue())
        self.assertIn("CA             2: AZ, TX   not here, on other lines: 1 (CA)", out.getvalue())
        html = eir_report._states_panel_html(lines)
        self.assertIn("2<small> of 3 jurisdictions the suite uses</small>", html)
        self.assertIn('<span class="chip on" title="2 scenarios">TX</span>', html)
        self.assertIn("1 used on other lines, never here", html)
        self.assertEqual(eir_states.excel_rows(lines), [["CA", "AZ", 1], ["CA", "TX", 2], ["CA", "CA", 0],
                                                        ["GL", "CA", 1], ["GL", "AZ", 0], ["GL", "TX", 0]])


if __name__ == "__main__":
    unittest.main()
