import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import parse_recording as pr  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
RECORDINGS = os.path.join(FIXTURES, "recordings")
CSSIDS = os.path.join(FIXTURES, "cssids")


def load(name):
    return pr.load_session(os.path.join(RECORDINGS, name))


class LoadSessionTest(unittest.TestCase):
    def test_loads_folder(self):
        self.assertEqual(load("real-180418")["id"], "2026-10-01_180418")

    def test_loads_zip_with_one_top_level_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rec.zip")
            with zipfile.ZipFile(path, "w") as z:
                z.write(os.path.join(RECORDINGS, "real-180418", "session.json"),
                        "2026-10-01_180418_test1/session.json")
            self.assertEqual(pr.load_session(path)["id"], "2026-10-01_180418")

    def test_loads_zip_ignoring_macosx_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rec.zip")
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("__MACOSX/2026-10-01_180418_test1/._session.json", b"\x00\x05binary")
                z.write(os.path.join(RECORDINGS, "real-180418", "session.json"),
                        "2026-10-01_180418_test1/session.json")
            self.assertEqual(pr.load_session(path)["id"], "2026-10-01_180418")

    def test_folder_without_session_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(pr.RecordingError, "no session.json"):
                pr.load_session(tmp)

    def test_not_a_recording(self):
        with self.assertRaisesRegex(pr.RecordingError, "not a recording"):
            pr.load_session(os.path.join(RECORDINGS, "does-not-exist"))


class HelpersTest(unittest.TestCase):
    def test_messages_accept_plain_strings_and_objects(self):
        step = {"messages": ["old style", {"text": "new style", "level": "error"}]}
        self.assertEqual(pr.messages(step), [{"text": "old style", "level": ""},
                                             {"text": "new style", "level": "error"}])

    def test_wait_title_keeps_the_part_before_the_colon(self):
        self.assertEqual(pr.wait_title("Account Summary: Duncan Test"), "Account Summary")
        self.assertEqual(pr.wait_title("Offerings"), "Offerings")
        self.assertEqual(pr.wait_title(None), "")


class LookupTest(unittest.TestCase):
    def test_exact_key(self):
        self.assertEqual(pr.lookup(CSSIDS, "pc", "Login-LoginScreen-LoginDV-username"),
                         ("resolved", ["new LoginPage(getContext()).getUsername()"]))

    def test_iterator_index_is_put_back(self):
        result = pr.resolve(CSSIDS, "pc", {"widgetId": "SubmissionWizard-LOBWizardStepGroup-ClauseIterator-2-Limit"})
        self.assertEqual(result, {"resolution": "resolved",
                                  "getter": "new SubmissionWizardPage(getContext()).getClauseIterator(2).getLimit()"})

    def test_unknown_application(self):
        self.assertEqual(pr.resolve(CSSIDS, None, {"widgetId": "X-Y"}),
                         {"resolution": "unresolved", "reason": "unknown application"})

    def test_no_widget_id(self):
        self.assertEqual(pr.resolve(CSSIDS, "pc", {"type": "dialog"}),
                         {"resolution": "unresolved", "reason": "no widget id"})

    def test_row_filters_and_later_page(self):
        getter = "new P(getContext()).getTable().getFirstRow().select().getSelect()"
        action = {"page": 2, "rowKey": [{"header": "Name", "text": "Acme"}, {"header": "City", "text": "Ulm"}]}
        self.assertEqual(pr.with_row(getter, action),
                         'new P(getContext()).getTable().getFirstRow().forMaximumPages(2)'
                         '.with("Name", "Acme", "TextCell").with("City", "Ulm", "TextCell").select().getSelect()')

    def test_row_without_key_is_unchanged(self):
        getter = "new P(getContext()).getTable().getFirstRow().select().getSelect()"
        self.assertEqual(pr.with_row(getter, {"row": 2}), getter)

    def test_jstr_escapes(self):
        self.assertEqual(pr.jstr('say "hi" \\ now\nnext'), '"say \\"hi\\" \\\\ now\\nnext"')
        self.assertEqual(pr.jstr(None), '""')
        self.assertEqual(pr.jstr("Zürich"), '"Zürich"')


if __name__ == "__main__":
    unittest.main()
