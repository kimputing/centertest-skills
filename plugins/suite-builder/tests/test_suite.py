import filecmp
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))

import suite  # noqa: E402
from xlsx_fixture import make_xlsx  # noqa: E402

SUBMISSION = """package com.acme.tests.pc.submission;
@CenterTest
public final class PA_SubmissionTest {
    @CenterTestCase(testCaseId = "TC-1")
    @DataDriven(datasource = "testdata/PA_SubmissionDC.xlsx")
    public void run(ScenarioContext scenarioContext) { }
}
"""
LOGIN = """package com.acme.tests.misc;
@CenterTest
public class LoginTest {
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) { }
    // @CenterTestCase public void commentedOut(ScenarioContext c) { }
    @CenterTestCase
    public void runAsAdmin(ScenarioContext scenarioContext) { }
}
"""
SUITES = {"CenterTestSuites": [
    {"Name": "Smoke", "List": ["LoginTest run", "PA_SubmissionTest run tx_.*"]},
    {"Name": "Stale", "List": ["PA_SubmissionTest run atv"]},
    {"Name": "All", "Suites": ["Smoke", "Stale"]},
]}


class SuiteTest(unittest.TestCase):
    def setUp(self):
        self.p = tempfile.mkdtemp()
        for rel, text in (("src/main/java/com/acme/tests/pc/submission/PA_SubmissionTest.java", SUBMISSION),
                          ("src/main/java/com/acme/tests/misc/LoginTest.java", LOGIN)):
            os.makedirs(os.path.dirname(os.path.join(self.p, rel)), exist_ok=True)
            with open(os.path.join(self.p, rel), "w") as fh:
                fh.write(text)
        os.makedirs(os.path.join(self.p, "testdata"))
        make_xlsx(os.path.join(self.p, "testdata", "PA_SubmissionDC.xlsx"), {"DataCombination": [
            ["Code", "Description", "Disabled"],
            ["tx_Austin", "Texas, Austin", ""], ["tx_Dallas", "Texas, Dallas", ""],
            ["CA.LA (2)", "California with dots and a space", ""], ["old_row", "switched off", "True"]]})
        self.path = os.path.join(self.p, "src", "main", "resources", "CenterTestSuiteList.json")
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", newline="") as fh:
            fh.write(json.dumps(SUITES, indent=4).replace("\n", "\r\n") + "\r\n")

    def tearDown(self):
        shutil.rmtree(self.p)

    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = suite.main(["--project", self.p, *args])
        return code, out.getvalue()

    def doc(self):
        with open(self.path, newline="") as fh:
            text = fh.read()
        return json.loads(text), text

    def test_scan_reads_methods_codes_and_disabled_rows(self):
        tests = suite.scan(self.p)
        self.assertEqual([t["class"] for t in tests], ["LoginTest", "PA_SubmissionTest"])
        self.assertEqual([m["name"] for m in tests[0]["methods"]], ["run", "runAsAdmin"])
        codes = tests[1]["methods"][0]["codes"]
        self.assertEqual([c["code"] for c in codes if not c["disabled"]], ["tx_Austin", "tx_Dallas", "CA.LA (2)"])

    def test_entries_resolve_as_centertest_reads_them(self):
        tests = suite.scan(self.p)
        doc, _ = self.doc()
        r = suite.resolve_suite(doc, "Smoke", tests)
        self.assertEqual(sorted(r["scenarios"]), [("LoginTest", "run", ""), ("PA_SubmissionTest", "run", "tx_Austin"),
                                                  ("PA_SubmissionTest", "run", "tx_Dallas")])
        everything = suite.resolve_suite(doc, "All", tests)
        self.assertEqual(everything["unmatched"], ["PA_SubmissionTest run atv"])

    def test_add_appends_only_what_is_not_covered_and_keeps_patterns(self):
        code, out = self.run_cli("add", "Smoke", "--code", "tx_|CA", "--write")
        self.assertEqual(code, 0, out)
        doc, text = self.doc()
        smoke = suite.find(doc, "Smoke")["List"]
        self.assertEqual(smoke, ["LoginTest run", "PA_SubmissionTest run tx_.*", "PA_SubmissionTest run CA\\.LA\\s\\(2\\)"])
        self.assertIn("\r\n    ", text)  # the file's CRLF and 4-space indent are kept

    def test_remove_expands_a_partly_removed_pattern_and_drops_whole_ones(self):
        code, out = self.run_cli("remove", "Smoke", "--code", "Dallas", "--write")
        self.assertEqual(code, 0, out)
        doc, _ = self.doc()
        self.assertEqual(suite.find(doc, "Smoke")["List"], ["LoginTest run", "PA_SubmissionTest run tx_Austin"])
        self.run_cli("remove", "Smoke", "--class", "Login", "--write")
        self.assertEqual(suite.find(self.doc()[0], "Smoke")["List"], ["PA_SubmissionTest run tx_Austin"])

    def test_create_compacts_whole_classes_and_methods(self):
        code, out = self.run_cli("create", "Mixed", "--class", "Login|Submission", "--write")
        self.assertEqual(code, 0, out)
        self.assertEqual(suite.find(self.doc()[0], "Mixed")["List"], ["LoginTest", "PA_SubmissionTest"])
        self.run_cli("create", "Two", "--entry", "LoginTest runAsAdmin", "--entry", "PA_SubmissionTest run tx_Austin", "--write")
        self.assertEqual(suite.find(self.doc()[0], "Two")["List"], ["LoginTest runAsAdmin", "PA_SubmissionTest run tx_Austin"])

    def test_all_rows_but_a_few_is_written_as_an_exclusion(self):
        code, out = self.run_cli("create", "MostRows", "--class", "PA_Submission", "--code", "tx_|CA", "--write")
        self.assertEqual(code, 0, out)
        doc = self.doc()[0]
        # 3 enabled rows, 3 chosen -> whole class
        self.assertEqual(suite.find(doc, "MostRows")["List"], ["PA_SubmissionTest"])
        self.run_cli("remove", "MostRows", "--code", "Dallas", "--write")
        entry = suite.find(self.doc()[0], "MostRows")["List"]
        self.assertEqual(entry, ["PA_SubmissionTest run (?!(?:tx_Dallas)$).*"])
        tests = suite.scan(self.p)
        self.assertEqual(sorted(k for _, _, k in suite.resolve_entry(entry[0], suite.scenarios_of(tests))),
                         ["CA.LA (2)", "tx_Austin"])

    def test_picker_page_embeds_the_scan_safely(self):
        out = os.path.join(self.p, "picker.html")
        code, _ = self.run_cli("picker", "--suite", "Smoke", "--out", out)
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8") as fh:
            page = fh.read()
        self.assertNotIn("/*__DATA__*/", page)
        blob = page.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0]
        data = json.loads(blob.replace("<\\/", "</"))
        self.assertEqual(data["preselect"], "Smoke")
        self.assertEqual([t["class"] for t in data["tests"]], ["LoginTest", "PA_SubmissionTest"])

    def test_a_hand_edited_file_with_trailing_commas_is_read_and_kept(self):
        text = '{\n  "CenterTestSuites": [\n    {\n      "Name": "Smoke",\n      "List": [\n        "LoginTest",\n      ]\n    },\n    {"Name": "agr", "Packages": ["com.acme.tests.agr.*"]},\n  ]\n}\n'
        with open(self.path, "w") as fh:
            fh.write(text)
        code, out = self.run_cli("add", "Smoke", "--class", "PA_Submission", "--write")
        self.assertEqual(code, 0, out)
        with open(self.path) as fh:
            new = fh.read()
        self.assertIn('"PA_SubmissionTest"', new)
        self.assertIn("},\n  ]", new)  # the file's own trailing comma is still there
        tests = suite.scan(self.p)
        doc, _ = suite.load_suites(self.path)
        self.assertEqual(suite.resolve_suite(doc, "agr", tests)["unmatched_packages"], ["com.acme.tests.agr.*"])

    def test_dry_run_writes_nothing(self):
        before = self.doc()[1]
        code, out = self.run_cli("delete", "Stale")
        self.assertIn("Not written (dry run; add --write)", out)
        self.assertIn("composite suites that name it: All", out)
        self.assertEqual(self.doc()[1], before)

    def test_rename_follows_composites(self):
        self.run_cli("rename", "Smoke", "Quick", "--write")
        doc, _ = self.doc()
        self.assertEqual(suite.find(doc, "All")["Suites"], ["Quick", "Stale"])

    def test_a_disabled_row_is_selected_only_on_request(self):
        tests = suite.scan(self.p)

        class A:
            cls = method = desc = package = entry = None
            code = "old"
            include_disabled = False
        self.assertEqual(suite.select(tests, A), set())
        A.include_disabled = True
        self.assertEqual(suite.select(tests, A), {("PA_SubmissionTest", "run", "old_row")})


class VendoredReaderTest(unittest.TestCase):
    def test_xlsx_reader_matches_recording_to_test(self):
        mine = os.path.join(PLUGIN, "scripts", "xlsx_read.py")
        source = os.path.join(os.path.dirname(PLUGIN), "recording-to-test", "scripts", "xlsx_read.py")
        self.assertTrue(filecmp.cmp(mine, source, shallow=False),
                        "plugins/suite-builder/scripts/xlsx_read.py must be an unchanged copy of "
                        "plugins/recording-to-test/scripts/xlsx_read.py; copy it again with cp")



IRREGULAR = """{
  "CenterTestSuites": [

    {
      "Name": "A",
      "List": [
        "LoginTest run",
        "PA_SubmissionTest"
     ]
    },


    {
      "Name": "B",
      "List": [
        "LoginTest"
      ]
    }
  ]
}"""


class MinimalEditTest(unittest.TestCase):
    """A team edits this file by hand: a change must show as that change in git, nothing else."""

    def edit(self, change):
        before = json.loads(IRREGULAR)
        after = json.loads(IRREGULAR)
        change(after["CenterTestSuites"])
        out = suite.minimal_edit(IRREGULAR, before, after)
        self.assertIsNotNone(out)
        self.assertEqual(json.loads(out), after)
        return out

    def test_list_change_touches_only_its_lines(self):
        out = self.edit(lambda s: s[0]["List"].pop(0))
        self.assertEqual(IRREGULAR.replace('        "LoginTest run",\n', ""), out.replace('        "PA_SubmissionTest"\n      ]', '        "PA_SubmissionTest"\n     ]'))

    def test_rename_delete_and_create_keep_the_blank_lines(self):
        self.assertEqual(self.edit(lambda s: s[1].update(Name="C")), IRREGULAR.replace('"Name": "B"', '"Name": "C"'))
        deleted = self.edit(lambda s: s.pop(1))
        self.assertIn('[\n\n    {\n      "Name": "A"', deleted)
        created = self.edit(lambda s: s.append({"Name": "New", "List": ["LoginTest"]}))
        self.assertTrue(created.startswith(IRREGULAR[:IRREGULAR.rindex("}\n  ]")]))
        self.assertFalse(created.endswith("\n"))  # no trailing newline before, none after

if __name__ == "__main__":
    unittest.main()
