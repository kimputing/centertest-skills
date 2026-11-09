import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "find_getter.py")
FIXTURES = os.path.join(os.path.dirname(os.path.dirname(HERE)), "recording-to-test", "tests", "fixtures", "cssids")


class FindGetterJsonTest(unittest.TestCase):
    def run_json(self, app, css_id):
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "HOME": home, "CENTERTEST_CSSIDS_DIR": FIXTURES}
            return subprocess.run([sys.executable, SCRIPT, app, css_id, "--json"], capture_output=True, text=True, env=env)

    def test_a_known_widget(self):
        run = self.run_json("pc", "OrganizationSearchPopup-OrganizationSearchPopupScreen-"
                                  "OrganizationSearchDV-GlobalContactNameInputSet-Name")
        self.assertEqual(run.returncode, 0, run.stderr)
        doc = json.loads(run.stdout)
        self.assertEqual(doc["resolution"], "exact")
        self.assertEqual(doc["getters"], ["new OrganizationSearchPopup(getContext()).getGlobalContactName().getName()"])

    def test_an_unknown_widget_and_app(self):
        run = self.run_json("pc", "No-Such-Widget")
        self.assertEqual((run.returncode, json.loads(run.stdout)["resolution"]), (1, "none"))
        self.assertIn("unknown app", json.loads(self.run_json("xx", "A-B").stdout)["error"])


if __name__ == "__main__":
    unittest.main()
