import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import flow_match as fm  # noqa: E402
import parse_recording as pr  # noqa: E402


def step(seq, pages, title=None, login=False):
    return {"seq": seq, "pages": pages, "waitTitle": title, "login": login}


def facade(name, method, pages=(), titles=(), context_only=True, path=None):
    return {"facade": name, "method": method, "params": [], "returns": "void", "contextOnly": context_only,
            "step": path or "com.acme.%s" % method, "pages": list(pages), "titles": list(titles)}


CSSIDS = os.path.join(os.path.dirname(__file__), "fixtures", "cssids")


class SegmentsTest(unittest.TestCase):
    def test_consecutive_steps_sharing_a_page_form_one_segment(self):
        plan = {"steps": [step(1, ["A"]), step(2, ["A", "B"]), step(3, ["C"])]}
        self.assertEqual([s["seqs"] for s in fm.segments(plan)], [[1, 2], [3]])

    def test_popup_joins_segment(self):
        plan = {"steps": [step(1, ["A"]), step(2, ["ConfirmPopup"]), step(3, ["B"])]}
        segs = fm.segments(plan)
        self.assertEqual([s["seqs"] for s in segs], [[1, 2], [3]])
        self.assertIn("ConfirmPopup", segs[0]["pages"])

    def test_login_alone(self):
        plan = {"steps": [step(1, ["Login"], login=True), step(2, ["Login"])]}
        self.assertEqual([s["seqs"] for s in fm.segments(plan)], [[1], [2]])

    def test_titles_collected(self):
        plan = {"steps": [step(1, ["A"], "Wizard"), step(2, ["A"], "Wizard")]}
        self.assertEqual(fm.segments(plan)[0]["titles"], ["Wizard"])


class FacadeSequenceTest(unittest.TestCase):
    plan = {"steps": [step(1, ["SubmissionWizard"], "Submission")]}

    def candidates(self, facades):
        return fm.facade_sequence(self.plan, facades)[0]["candidates"]

    def test_candidate_needs_context_only(self):
        facades = [facade("F", "a", ["SubmissionWizardPage"], context_only=False),
                   facade("F", "b", ["SubmissionWizardPage"])]
        self.assertEqual([c["method"] for c in self.candidates(facades)], ["b"])

    def test_candidates_ranked_by_overlap(self):
        facades = [facade("F", "weak", ["OtherPage"], ["Submission"]),
                   facade("F", "strong", ["SubmissionWizardPage"], ["Submission"]),
                   facade("F", "none", ["ZPage"])]
        found = self.candidates(facades)
        self.assertEqual([c["method"] for c in found], ["strong", "weak"])
        self.assertEqual(found[0]["score"], 1.0)
        self.assertEqual(found[0]["step"], "com.acme.strong")
        self.assertEqual(set(found[0]), {"facade", "method", "score", "why", "step"})

    def test_max_three(self):
        facades = [facade("F", "m%d" % i, ["SubmissionWizardPage"]) for i in range(5)]
        self.assertEqual(len(self.candidates(facades)), 3)


class ExistingTestsTest(unittest.TestCase):
    seq = [{"seqs": [1], "candidates": [{"facade": "PC", "method": "login"}]},
           {"seqs": [2, 3], "candidates": [{"facade": "F", "method": "quote"}]}]

    def folders(self):
        return {"a": [{"path": "a/Full.java", "flow": ["PC.login", "F.quote"]},
                      {"path": "a/Half.java", "flow": ["PC.login"]}],
                "b": [{"path": "b/Other.java", "flow": ["F.quote", "PC.login"]}]}

    def test_existing_test_covering_all_segments_scores_1(self):
        found = fm.existing_tests(self.seq, self.folders(), "a")
        self.assertEqual(found[0]["path"], "a/Full.java")
        self.assertEqual(found[0]["score"], 1.0)
        self.assertEqual(found[0]["coveredSeqs"], [1, 2, 3])
        self.assertEqual(found[0]["missingSeqs"], [])
        self.assertEqual(found[0]["folder"], "a")

    def test_partial_and_order(self):
        by_path = {t["path"]: t for t in fm.existing_tests(self.seq, self.folders(), "a")}
        self.assertEqual(by_path["a/Half.java"]["missingSeqs"], [2, 3])
        self.assertEqual(by_path["a/Half.java"]["score"], 0.5)
        self.assertEqual(by_path["b/Other.java"]["coveredSeqs"], [1])  # quote precedes login: order matters

    def test_folder_tests_first(self):
        paths = [t["path"] for t in fm.existing_tests(self.seq, self.folders(), "b")]
        self.assertEqual(paths[0], "b/Other.java")

    def test_max_five_and_empty(self):
        many = {"a": [{"path": "t%d" % i, "flow": ["PC.login"]} for i in range(8)]}
        self.assertEqual(len(fm.existing_tests(self.seq, many, "a")), 5)
        self.assertEqual(fm.existing_tests([], many, None), [])


class AnalyseTest(unittest.TestCase):
    def test_no_project_gives_empty_lists(self):
        session = {"id": "x", "name": "n", "steps": []}
        plan = pr.build_plan(session, CSSIDS, project=None)
        self.assertEqual(plan["facadeSequence"], [])
        self.assertEqual(plan["existingTests"], [])

    def test_project_with_facades_fills_both_lists(self):
        session = {"id": "x", "name": "n", "steps": []}
        project = {"facades": {"value": [facade("F", "m", ["SubmissionWizardPage"])]},
                   "folders": {"value": {"tests": {}}}}
        plan = pr.build_plan(session, CSSIDS, project=project)
        self.assertEqual(plan["facadeSequence"], [])
        self.assertEqual(plan["existingTests"], [])


if __name__ == "__main__":
    unittest.main()
