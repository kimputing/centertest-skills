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

    def test_the_review_names_jurisdictions_a_line_stops_running_in(self):
        import shutil
        from eir_review import render_markdown
        base = os.path.join(self.tmp.name, "base")
        shutil.copytree(self.root, base)
        make_xlsx(os.path.join(base, "testdata", "ca", "CA_SubmissionDC.xlsx"), {"DataCombination": [
            ["Code", "#Address", "Disabled"], ["Phoenix", "phx", ""], ["Reno", "reno", ""]]})  # NV ran; TX did not
        delta = eir_states.state_delta(base, self.root, self.cssids)
        self.assertEqual(delta, [{"line": "CA", "lost": ["NV"], "gained": ["TX"]}])
        self.assertEqual(eir_states.state_delta(self.root, self.root, self.cssids), [])
        meta = {"base_name": "main", "head_name": "b", "base_short": "1", "head_short": "2", "base_files": 1,
                "head_files": 1, "ruleset": "x", "rerun": [], "data": [], "suites": [], "states": delta}
        md = render_markdown([], meta)
        self.assertIn("**No scenario of the line runs there any more** (1): CA: NV", md)
        self.assertIn("Newly run in (1): CA: TX", md)

    def test_breadth_tiles_head_the_dashboard(self):
        lines = eir_states.state_coverage(self.root, self.cssids)
        reach = [{"suite": "(full run)", "scenarios": 3, "test": 4, "coverage": 2, "jurisdiction": 3},
                 {"suite": "Smoke", "scenarios": 1, "test": 1, "coverage": 1, "jurisdiction": 1},
                 {"suite": "All", "scenarios": 3, "test": 3, "coverage": 2, "jurisdiction": 3}]
        products = [{"line": "GLLine", "coverages": 10, "named": [{}, {}], "options_chosen": 1, "options_total": 4}]
        html = eir_report._breadth_tiles_html({"scenarios": 9}, products, lines, reach)
        for value, label in (("4", "Flows that run"), ("9", "Scenario runs per full run"),
                             ("2/10", "Product coverages selected"), ("1/4", "Limit/deductible options set"),
                             ("3", "Jurisdictions"), ("75%", "Flows in the widest suite (All)")):
            self.assertIn(f'<div class="stat-value stat-blue">{value}</div><div class="stat-label">{label}</div>', html)
        self.assertEqual(eir_report._breadth_tiles_html(None, None, None, None), "")

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
