import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN, "evals"))
import run_evals  # noqa: E402
from test_scan_project import fake_project  # noqa: E402

CT = os.path.join(PLUGIN, "scripts", "ct.py")
SYNTHETIC = os.path.join(HERE, "fixtures", "recordings", "synthetic")
CSSIDS = os.path.join(HERE, "fixtures", "cssids", "cssids")


def run_main(argv, env=None):
    """Run main() with stdout/stderr captured; return (exit code, output)."""
    out = io.StringIO()
    saved = {}
    for key, value in (env or {}).items():
        saved[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = run_evals.main(argv)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return code, out.getvalue()


class GetPathTest(unittest.TestCase):
    def test_get_path_with_indexes(self):
        doc = {"plan": {"existingTests": [{"path": "a"}, {"path": "b"}]}, "project": {"x": 1}}
        self.assertEqual(run_evals.get_path(doc, "plan.existingTests[1].path"), "b")
        self.assertEqual(run_evals.get_path(doc, "project.x"), 1)

    def test_get_path_missing_segment_raises_keyerror_naming_it(self):
        with self.assertRaises(KeyError) as ctx:
            run_evals.get_path({"plan": {}}, "plan.nope.deeper")
        self.assertIn("nope", str(ctx.exception))

    def test_get_path_index_out_of_range(self):
        with self.assertRaises(KeyError):
            run_evals.get_path({"plan": {"a": []}}, "plan.a[0]")


class CaseTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cases = os.path.join(self.tmp.name, "cases")
        self.project = os.path.join(self.tmp.name, "proj")
        fake_project(self.project)

    def write_case(self, name="c1", **overrides):
        case = {"name": name, "project": self.project, "recordings": [SYNTHETIC], "cssids": CSSIDS,
                "expect": [{"path": "plan.schemaVersion", "op": "equals", "value": 2}]}
        case.update(overrides)
        folder = os.path.join(self.cases, name)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "case.json"), "w", encoding="utf-8") as f:
            json.dump(case, f)
        return folder


class RunCaseTest(CaseTestBase):
    def test_passing_case(self):
        result = run_evals.run_case(self.write_case(), CT)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["failures"], [])

    def test_failing_expectation_reported(self):
        folder = self.write_case(expect=[{"path": "plan.schemaVersion", "op": "equals", "value": 99},
                                         {"path": "plan.nope", "op": "exists"}])
        result = run_evals.run_case(folder, CT)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(len(result["failures"]), 2)
        self.assertIn("plan.schemaVersion", result["failures"][0])

    def test_ops_contains_and_absent(self):
        folder = self.write_case(expect=[
            {"path": "project.clientPackage.value", "op": "contains", "value": "acme"},
            {"path": "plan.doesNotExist", "op": "absent"}])
        self.assertEqual(run_evals.run_case(folder, CT)["status"], "PASS")

    def test_missing_project_is_skip(self):
        folder = self.write_case(project=os.path.join(self.tmp.name, "gone"))
        result = run_evals.run_case(folder, CT)
        self.assertEqual(result["status"], "SKIP")
        self.assertTrue(result["reason"])

    def test_no_cssids_is_skip(self):
        folder = self.write_case()
        case_path = os.path.join(folder, "case.json")
        with open(case_path, encoding="utf-8") as f:
            case = json.load(f)
        del case["cssids"]
        with open(case_path, "w", encoding="utf-8") as f:
            json.dump(case, f)
        result = run_evals.run_case(folder, CT)
        self.assertEqual(result["status"], "SKIP")
        self.assertIn("cssids", result["reason"])

    def test_env_var_expanded(self):
        folder = self.write_case(project="${EVAL_TEST_PROJECT}")
        os.environ["EVAL_TEST_PROJECT"] = self.project
        self.addCleanup(os.environ.pop, "EVAL_TEST_PROJECT", None)
        self.assertEqual(run_evals.run_case(folder, CT)["status"], "PASS")

    def test_unset_env_var_is_skip(self):
        os.environ.pop("EVAL_TEST_UNSET", None)
        folder = self.write_case(project="${EVAL_TEST_UNSET}")
        self.assertEqual(run_evals.run_case(folder, CT)["status"], "SKIP")

    def test_relative_paths_resolve_against_case_folder(self):
        folder = self.write_case(project="../../proj")
        self.assertEqual(run_evals.run_case(folder, CT)["status"], "PASS")


class MainTest(CaseTestBase):
    def test_no_cases_dir_exits_2(self):
        code, out = run_main([], env={"CT_EVALS_DIR": None})
        self.assertEqual(code, 2)
        self.assertIn("--cases", out)

    def test_main_prints_lines_and_total_exit_0(self):
        self.write_case()
        code, out = run_main(["--cases", self.cases])
        self.assertEqual(code, 0)
        self.assertIn("PASS c1", out)
        self.assertIn("1 passed", out)

    def test_main_exit_1_on_fail(self):
        self.write_case(expect=[{"path": "plan.schemaVersion", "op": "equals", "value": 1}])
        code, out = run_main(["--cases", self.cases])
        self.assertEqual(code, 1)
        self.assertIn("FAIL c1", out)

    def test_main_uses_env_dir_and_skip_is_not_failure(self):
        self.write_case(project=os.path.join(self.tmp.name, "gone"))
        code, out = run_main([], env={"CT_EVALS_DIR": self.cases})
        self.assertEqual(code, 0)
        self.assertIn("SKIP c1", out)


if __name__ == "__main__":
    unittest.main()
