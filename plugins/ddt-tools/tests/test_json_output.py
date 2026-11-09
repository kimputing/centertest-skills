import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, HERE)

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class JsonOutputTest(unittest.TestCase):
    def run_tool(self, root, script):
        env = {**os.environ, "CENTERTEST_PROJECT_DIR": root, "HOME": root}
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, script), "--json"],
                              capture_output=True, text=True, env=env)

    def test_validate_refs_json(self):
        from refcheck_fixture import build_project
        with tempfile.TemporaryDirectory() as root:
            build_project(root)
            run = self.run_tool(root, "xlsx-validate-refs.py")
            self.assertFalse(os.path.isdir(os.path.join(root, "pr-review")))  # no report tee in JSON mode
        self.assertEqual(run.returncode, 1)
        doc = json.loads(run.stdout)
        self.assertEqual((doc["tool"], doc["broken"]), ("xlsx-validate-refs", 3))  # the fixture's three
        self.assertEqual({f["code"] for f in doc["findings"]}, {"Terrorism", "Missing", "Nope"})

    def test_cleanup_json(self):
        from refcheck_fixture import build_project
        with tempfile.TemporaryDirectory() as root:
            build_project(root)
            run = self.run_tool(root, "xlsx-cleanup-unused.py")
        self.assertEqual(run.returncode, 0, run.stderr[-300:])
        doc = json.loads(run.stdout)
        self.assertEqual(doc["tool"], "xlsx-cleanup-unused")
        self.assertIn("DC column", doc["ways"])


if __name__ == "__main__":
    unittest.main()
