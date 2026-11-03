import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)
import ct  # noqa: E402
import parse_recording as pr  # noqa: E402
import scan_project as sp  # noqa: E402
import schema  # noqa: E402
from test_scan_project import fake_project  # noqa: E402

RECORDINGS = os.path.join(HERE, "fixtures", "recordings")
CSSIDS = os.path.join(HERE, "fixtures", "cssids")


def load(name):
    return pr.load_session(os.path.join(RECORDINGS, name))


class SchemaVersionTest(unittest.TestCase):
    def test_versions_are_2(self):
        self.assertEqual((schema.PLAN_SCHEMA_VERSION, schema.PROJECT_SCHEMA_VERSION), (2, 2))

    def test_plan_carries_schema_version(self):
        plan = pr.build_plan(load("synthetic"), CSSIDS)
        self.assertEqual(plan["schemaVersion"], schema.PLAN_SCHEMA_VERSION)

    def test_project_carries_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "acme-project")
            fake_project(root)
            result = sp.scan(root, gradle_home=os.path.join(tmp, "g"), m2_home=os.path.join(tmp, "m"),
                             cache_root=os.path.join(tmp, "c"))
        self.assertEqual(result["schemaVersion"], schema.PROJECT_SCHEMA_VERSION)

    def test_plan_keys_are_declared(self):
        for name in sorted(os.listdir(RECORDINGS)):
            path = os.path.join(RECORDINGS, name)
            if not os.path.isdir(path):
                continue
            plan = pr.build_plan(load(name), CSSIDS, pr.file_reader(path), None)
            self.assertLessEqual(set(plan), schema.PLAN_FIELDS, name)

    def test_plan_fields_include_conditional_and_future_keys(self):
        for key in ("startValues", "policyShape", "outcomeMismatch", "facadeSequence", "existingTests",
                    "dcColumns", "dataRowCandidates", "restartCandidates", "seedPointCandidates",
                    "narration", "parts", "chain", "schemaVersion"):
            self.assertIn(key, schema.PLAN_FIELDS)


def quiet_main(argv):
    """(exit code, stdout, stderr) of ct.main, so the suite prints only unittest's own lines."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ct.main(argv)
    return code, out.getvalue(), err.getvalue()


class DispatcherTest(unittest.TestCase):
    def test_commands_are_module_function_strings(self):
        self.assertEqual(set(ct.COMMANDS), {"scan", "parse", "xlsx", "narrate", "profile", "tools", "gap-report"})
        self.assertEqual(ct.COMMANDS["scan"], "scan_project:main")
        self.assertEqual(ct.COMMANDS["profile"], "client_profile:main")
        for value in ct.COMMANDS.values():
            self.assertRegex(value, r"^\w+:\w+$")

    def test_help_lists_all_commands(self):
        text = ct.build_parser().format_help()
        for command in ct.COMMANDS:
            self.assertIn(command, text)

    def test_unknown_command_exits_2(self):
        code, _, err = quiet_main(["nope"])
        self.assertEqual((code, err.startswith("Error: unknown command: nope")), (2, True))

    def test_no_command_exits_2(self):
        code, out, _ = quiet_main([])
        self.assertEqual((code, out.startswith("usage: ct.py")), (2, True))

    def test_missing_module_exits_2(self):
        saved = dict(ct.COMMANDS)
        ct.COMMANDS["ghost"] = "no_such_module_here:main"
        try:
            code, _, err = quiet_main(["ghost"])
            self.assertEqual((code, "command ghost is not available" in err), (2, True))
        finally:
            ct.COMMANDS.clear()
            ct.COMMANDS.update(saved)

    def test_parse_matches_parse_recording(self):
        recording = os.path.join(RECORDINGS, "real-180418")
        with tempfile.TemporaryDirectory() as tmp:
            direct, via = os.path.join(tmp, "a.json"), os.path.join(tmp, "b.json")
            args = [recording, "--cssids", CSSIDS, "--out"]
            subprocess.run([sys.executable, os.path.join(SCRIPTS, "parse_recording.py"), *args, direct], check=True)
            subprocess.run([sys.executable, os.path.join(SCRIPTS, "ct.py"), "parse", *args, via], check=True)
            with open(direct) as a, open(via) as b:
                self.assertEqual(json.load(a), json.load(b))

    def test_script_help_lists_commands(self):
        out = subprocess.run([sys.executable, os.path.join(SCRIPTS, "ct.py"), "-h"],
                             capture_output=True, text=True, check=True).stdout
        for command in ct.COMMANDS:
            self.assertIn(command, out)


class QuietTest(unittest.TestCase):
    def test_dispatcher_tests_print_nothing_on_stdout(self):
        run = subprocess.run([sys.executable, "-m", "unittest", "test_ct.DispatcherTest"], cwd=HERE,
                             capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stdout, "Error:" in run.stderr), (0, "", False))


if __name__ == "__main__":
    unittest.main()
