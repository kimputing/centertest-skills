import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import eir_report
import eir_screens


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class ScreenCoverageTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.repo = os.path.join(self.root, "client")
        gen = os.path.join(self.root, "client-generated", "src", "main", "resources", "cssids", "pc")
        write(os.path.join(gen, "SubmissionWizard.properties"),
              "SubmissionWizard-Next=new SubmissionWizardPage(getContext()).getNext()\n")
        write(os.path.join(gen, "CancellationWizard.properties"),
              "CancellationWizard-Next=new CancellationWizardPage(getContext()).getNext()\n")
        write(os.path.join(gen, "AccountFile_Summary.properties"),
              "AccountFile_Summary-Name=new AccountFile_SummaryPage(getContext()).getName()\n")
        write(os.path.join(gen, "_misc.properties"), "#x=new MiscPage(getContext())\n")
        src = os.path.join(self.repo, "src", "main", "java", "com", "acme")
        write(os.path.join(src, "steps", "CreateSubmission.java"),
              "class CreateSubmission { void run() { var page = new SubmissionWizardPage(getContext()); } }")
        # Generated code is not the suite's own use.
        write(os.path.join(src, "generated", "datadriven", "X.java"), "class X { CancellationWizardPage p; }")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_sibling_generated_project_is_found(self):
        found = eir_screens.find_cssids_dir(self.repo)
        self.assertTrue(found.endswith(os.path.join("client-generated", "src", "main", "resources", "cssids")))

    def test_wizards_opened_and_not(self):
        cov = eir_screens.screen_coverage(self.repo, "src/main/java", eir_screens.find_cssids_dir(self.repo))
        pc = cov[0]
        self.assertEqual((pc["name"], pc["screens"], pc["used"]), ("PolicyCenter", 3, 1))
        self.assertEqual(pc["wizards"], [("SubmissionWizard", ["CreateSubmission"])])
        self.assertEqual(pc["unused_wizards"], ["CancellationWizard"])
        html = eir_report._screens_panel_html(cov)
        self.assertIn("1<small> of 2 wizards</small>", html)
        self.assertIn("1 of 3 screens", html)

    def test_missing_cssids_says_so(self):
        self.assertIn("Not measured", eir_report._screens_panel_html([]))
        self.assertEqual(eir_report._screens_panel_html(None), "")


if __name__ == "__main__":
    unittest.main()
