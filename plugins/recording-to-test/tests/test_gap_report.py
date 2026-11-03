import contextlib
import datetime
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import ct  # noqa: E402
import gap_report  # noqa: E402

TODAY = datetime.date(2026, 11, 3)


def sample_plan():
    return {"schemaVersion": 2,
            "recording": {"id": "rec-1", "name": "Jane Doe renewal", "toolVersion": "1.4.0",
                          "startUrl": "https://client.example.test/pc"},
            "steps": [{"value": "Jane Doe"}]}


class GapReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "gaps")

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_report_written_with_versions(self):
        path = gap_report.write(sample_plan(), "steps[3].getter", "a getter", "nothing", self.out, TODAY)
        self.assertEqual(os.path.basename(path), "2026-11-03-steps-3-getter.md")
        text = self.read(path)
        for expected in ("rec-1", "1.4.0", "schemaVersion", "steps[3].getter", "a getter", "nothing",
                         "Send this file to Kimputing (recording-to-test engine)"):
            self.assertIn(expected, text)

    def test_same_day_same_field_numbered(self):
        names = [os.path.basename(gap_report.write(sample_plan(), "f", "e", "g", self.out, TODAY))
                 for _ in range(3)]
        self.assertEqual(names, ["2026-11-03-f.md", "2026-11-03-f-2.md", "2026-11-03-f-3.md"])

    def test_no_recorded_values_copied(self):
        text = self.read(gap_report.write(sample_plan(), "f", "e", "g", self.out, TODAY))
        for leaked in ("Jane Doe", "client.example.test"):
            self.assertNotIn(leaked, text)

    def test_combined_plan_lists_each_part(self):
        second = sample_plan()
        second["recording"].update(id="rec-2", toolVersion="1.5.0")
        combined = {"schemaVersion": 2, "parts": [sample_plan(), second], "chain": []}
        text = self.read(gap_report.write(combined, "f", "e", "g", self.out, TODAY))
        for expected in ("rec-1", "1.4.0", "rec-2", "1.5.0"):
            self.assertIn(expected, text)

    def test_cli_writes_report(self):
        plan_path = os.path.join(self.tmp.name, "plan.json")
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(sample_plan(), f)
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = gap_report.main(["--plan", plan_path, "--field", "f", "--expected", "e", "--got", "g",
                                    "--out-dir", self.out])
        self.assertEqual(code, 0)
        files = os.listdir(self.out)
        self.assertEqual(len(files), 1)
        self.assertEqual(captured.getvalue().strip(), os.path.join(self.out, files[0]))

    def test_path_like_field_stays_inside_out_dir(self):
        path = gap_report.write(sample_plan(), "../../x", "e", "g", self.out, TODAY)
        self.assertEqual(os.path.dirname(os.path.abspath(path)), os.path.abspath(self.out))


class AllCommandsTest(unittest.TestCase):
    def test_every_command_imports_and_answers_help(self):
        for command in ct.COMMANDS:
            with self.subTest(command=command):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    try:
                        code = ct.main([command, "-h"])
                    except SystemExit as exit_:
                        code = exit_.code
                self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
