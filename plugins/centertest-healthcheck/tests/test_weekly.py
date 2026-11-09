import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from eir_config import EirConfig  # noqa: E402
import eir_weekly  # noqa: E402
import rules  # noqa: E402,F401  (fills the rule registry, as the CLI does)

TEST = """package com.x.tests;
@CenterTest
public final class {name} {{
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) {{
        {body}
    }}
}}
"""


def git(cwd, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@x")
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


class WeeklyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "suite")
        src = os.path.join(self.repo, "src", "main", "java", "com", "x", "tests")
        os.makedirs(src)
        os.makedirs(os.path.join(self.repo, "testdata"))
        with open(os.path.join(src, "AccountTest.java"), "w") as fh:
            fh.write(TEST.format(name="AccountTest", body='Assertions.assertThat(1).isEqualTo(1);'))
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "old", date="2026-01-01T10:00:00")
        from eir_analyzer import build_parser
        self.config = EirConfig(build_parser().parse_args(["--path", self.repo, "--ruleset", "CenterTestFull"]))

    def tearDown(self):
        self.tmp.cleanup()

    def test_quiet_when_nothing_landed(self):
        week = eir_weekly.week_of(self.repo, self.config, 7)
        self.assertEqual(week["landed"], 0)
        self.assertNotIn("verdict", week)
        self.assertIn("Quiet: nothing landed in 7 days", eir_weekly.render_html([week], 7))

    def test_recent_commits_run_through_the_review(self):
        with open(os.path.join(self.repo, "src", "main", "java", "com", "x", "tests", "Broken.java"), "w") as fh:
            fh.write(TEST.format(name="Broken", body='new Page(getContext()).getName().getValue().equals("b");'))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "new")
        with contextlib.redirect_stdout(io.StringIO()):
            week = eir_weekly.week_of(self.repo, self.config, 7)
        self.assertEqual(week["landed"], 1)
        self.assertTrue(week["blocked"])
        self.assertIn("these commits introduce", week["verdict"])
        self.assertTrue(any("never fail" in t for t, _n in week["blockers"]))
        self.assertIn("1 ×", eir_weekly.render_html([week], 7))


if __name__ == "__main__":
    unittest.main()
