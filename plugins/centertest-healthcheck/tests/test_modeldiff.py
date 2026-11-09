import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import eir_modeldiff  # noqa: E402
import test_cover  # noqa: E402  (its fixture project; the module name, so its tests are not collected twice)

V1 = [{"codeIdentifier": "GLLiquor", "name": "Liquor Liability",
       "covTerms": [{"name": "Limit", "covTermChoices": [{"codeIdentifier": "z1", "name": "$1,000"},
                                                          {"codeIdentifier": "z2", "name": "$2,000"}]}]},
      {"codeIdentifier": "GLPollution", "name": "Pollution"}]
# v2: the $1,000 limit is gone, Pollution is renamed (same code), Cyber is new
V2 = [{"codeIdentifier": "GLLiquor", "name": "Liquor Liability",
       "covTerms": [{"name": "Limit", "covTermChoices": [{"codeIdentifier": "z2", "name": "$2,000"}]}]},
      {"codeIdentifier": "GLPollution", "name": "Pollution Liability"},
      {"codeIdentifier": "GLCyber", "name": "Cyber"}]


def git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(test_cover.HAS_OPENPYXL, "openpyxl not installed")
class ModelDiff(unittest.TestCase):
    def setUp(self):
        fx = self.fx = test_cover.CoveringSuite("test_without_a_generated_project_it_still_covers_every_flow")
        fx.setUp()
        self.addCleanup(fx.tearDown)
        test_cover.make_xlsx(os.path.join(fx.root, "testdata", "GLData.xlsx"), {
            "Coverage": [["Code", "Coverage", "CovTerm", "CovtermValue"], ["liq", "Liquor Liability", "Limit", "1,000"],
                         ["pol", "Pollution", "", ""]],
            "Address": [["Code", "State"], ["phx", "AZ"], ["aus", "Texas"]]})
        gen = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(fx.cssids))))  # .../gen
        model = os.path.join(os.path.dirname(fx.cssids), "GLLine_coverage_structure.json")
        git(gen, "init", "-q", "-b", "main")
        self.revs = []
        for version in (V1, V2):
            with open(model, "w") as fh:
                json.dump(version, fh)
            git(gen, "add", "-A")
            git(gen, "commit", "-q", "-m", "model")
            self.revs.append(git(gen, "rev-parse", "HEAD"))

    def test_what_breaks_and_what_nobody_tests(self):
        d = eir_modeldiff.model_diff(self.fx.root, "src", self.fx.cssids, self.revs[0], self.revs[1])
        self.assertEqual(d["coverages"], {"removed": 0, "added": 1, "renamed": 1})
        self.assertEqual(d["options"], {"removed": 1, "added": 0})
        self.assertEqual(d["breaks"], {
            "GLLine: coverage renamed - Pollution -> Pollution Liability": [("GL_SubmissionTest", "run", "B"),
                                                                           ("GL_SubmissionTest", "run", "C")],
            "GLLine: option removed - Liquor Liability / Limit = $1,000": [("GL_SubmissionTest", "run", "A"),
                                                                          ("GL_SubmissionTest", "run", "C")]})
        self.assertEqual(d["scenarios"], 3)
        self.assertEqual(d["untested_added"], ["GLLine: Cyber"])

    def test_the_working_tree_is_the_default_new_and_an_unknown_rev_is_an_error(self):
        d = eir_modeldiff.model_diff(self.fx.root, "src", self.fx.cssids, self.revs[1])
        self.assertEqual((d["new"], d["scenarios"]), ("working tree", 0))  # v2 is what is on disk
        self.assertIn("no product model at nope", eir_modeldiff.model_diff(self.fx.root, "src", self.fx.cssids, "nope")["error"])


if __name__ == "__main__":
    unittest.main()
