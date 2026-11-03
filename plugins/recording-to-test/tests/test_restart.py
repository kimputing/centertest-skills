import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import restart  # noqa: E402
import parse_recording as pr  # noqa: E402


def step(seq, page, title=None, actions=(), checks=(), app="pc", app_switch=False):
    return {"seq": seq, "pages": [page], "waitTitle": title, "app": app, "appSwitch": app_switch,
            "login": False, "actions": [dict(a) for a in actions], "checks": list(checks)}


def click(label, **extra):
    return dict({"type": "click", "label": label, "widgetId": None}, **extra)


def seg(seqs, method=None, step_path=None):
    entry = {"seqs": seqs, "pages": [], "titles": [], "candidates": []}
    if method:
        entry["candidates"] = [{"facade": "F", "method": method, "score": 1.0, "why": "", "step": step_path}]
    return entry


class RestartCandidatesTest(unittest.TestCase):
    def test_payment_followed_by_checks_is_not_resumable(self):
        plan = {"steps": [step(1, "A", actions=[click("Make Payment")]),
                          step(2, "A", checks=[{"label": "Amount"}])]}
        found = restart.restart_candidates(plan, [], [])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["kind"], "stateChanging")
        self.assertEqual(found[0]["rerunRisk"], "notResumable")
        self.assertEqual(found[0]["proposePolicy"], "DISABLE_ON_FAILURE")
        self.assertIn("payment", found[0]["reason"])
        self.assertIn("2", found[0]["reason"])

    def test_commit_as_last_thing_is_not_a_candidate(self):
        plan = {"steps": [step(1, "A", actions=[click("Issue Policy")])]}
        self.assertEqual(restart.restart_candidates(plan, [], []), [])

    def test_check_after_commit_in_same_step_counts(self):
        plan = {"steps": [step(1, "A", actions=[click("Bind Only")], checks=[{"label": "x"}])]}
        found = restart.restart_candidates(plan, [], [])
        self.assertEqual(found[0]["rerunRisk"], "notResumable")
        self.assertIn("bind", found[0]["reason"])

    def test_wizard_action_issue_counts(self):
        plan = {"steps": [step(1, "A", actions=[click("Go", wizardAction="issue")]),
                          step(2, "A", actions=[click("Next")])]}
        self.assertIn("issue", restart.restart_candidates(plan, [], [])[0]["reason"])

    def test_component_after_commit_marks_state_changing(self):
        plan = {"steps": [step(1, "A", actions=[click("Next")]), step(2, "B")]}
        sequence = [seg([1], "doIt", "src/Step.java"), seg([2])]
        effects = [{"path": "src/Step.java", "class": "Step", "commits": ["bind"], "afterCommit": True}]
        found = restart.restart_candidates(plan, sequence, effects)
        self.assertEqual(found[0]["kind"], "stateChanging")
        self.assertEqual(found[0]["afterSeq"], 1)
        self.assertEqual(found[0]["rerunRisk"], "notResumable")
        self.assertIn("bind", found[0]["reason"])

    def test_component_without_after_commit_is_not_state_changing(self):
        plan = {"steps": [step(1, "A"), step(2, "B")]}
        sequence = [seg([1], "doIt", "src/Step.java"), seg([2])]
        effects = [{"path": "src/Step.java", "class": "Step", "commits": ["bind"], "afterCommit": False}]
        self.assertEqual(restart.restart_candidates(plan, sequence, effects), [])

    def test_setup_after_create_submission(self):
        plan = {"steps": [step(1, "A"), step(2, "B")]}
        sequence = [seg([1], "createSubmission", "s"), seg([2], "other", "t")]
        found = restart.restart_candidates(plan, sequence, [])
        self.assertEqual([(c["kind"], c["afterSeq"], c["rerunRisk"], c["proposePolicy"]) for c in found],
                         [("setup", 1, "safe", None)])

    def test_setup_needs_a_following_segment(self):
        plan = {"steps": [step(1, "A")]}
        self.assertEqual(restart.restart_candidates(plan, [seg([1], "createSubmission", "s")], []), [])

    def test_center_switch_candidate(self):
        plan = {"steps": [step(1, "A"), step(2, "A"), step(3, "B", app="bc", app_switch=True)]}
        found = restart.restart_candidates(plan, [], [])
        self.assertEqual([(c["kind"], c["afterSeq"], c["rerunRisk"]) for c in found], [("centerSwitch", 2, "safe")])

    def test_state_changing_beats_center_switch_at_one_boundary(self):
        plan = {"steps": [step(1, "A", actions=[click("Issue")]), step(2, "A", checks=[{"label": "x"}]),
                          step(3, "B", app="bc", app_switch=True)]}
        found = restart.restart_candidates(plan, [], [])
        self.assertEqual([(c["kind"], c["afterSeq"]) for c in found], [("stateChanging", 1), ("centerSwitch", 2)])

    def test_state_changing_wins_when_boundaries_coincide(self):
        plan = {"steps": [step(1, "A", actions=[click("Issue")], checks=[{"label": "x"}]),
                          step(2, "B", app="bc", app_switch=True)]}
        found = restart.restart_candidates(plan, [], [])
        self.assertEqual([(c["kind"], c["afterSeq"]) for c in found], [("stateChanging", 1)])
        self.assertIn("centerSwitch", found[0]["reason"])

    def test_payment_followed_by_check_on_later_screen_is_not_resumable(self):
        plan = {"steps": [step(1, "Payment", actions=[click("Make Payment")]),
                          step(2, "Summary", checks=[{"label": "Amount"}])]}
        found = restart.restart_candidates(plan, [], [])
        self.assertEqual([(c["kind"], c["afterSeq"], c["rerunRisk"], c["proposePolicy"]) for c in found],
                         [("stateChanging", 1, "notResumable", "DISABLE_ON_FAILURE")])
        self.assertIn("payment at seq 1 is followed by more work", found[0]["reason"])

    def test_no_project_has_no_setup(self):
        plan = {"steps": [step(1, "A"), step(2, "B")]}
        found = restart.restart_candidates(plan, [], None)
        self.assertEqual(found, [])


class SeedPointsTest(unittest.TestCase):
    def test_seed_points_from_titles(self):
        plan = {"steps": [step(1, "A", "New Account"), step(2, "B", "Account Summary"),
                          step(3, "C", "Pre-Quote Issues"), step(4, "D", "Quote"),
                          step(5, "E", "Submission Bound"), step(6, "F", "Claim Summary", app="cc")]}
        self.assertEqual([(s["seq"], s["seed"]) for s in restart.seed_points(plan)],
                         [(2, "NEW_ACCOUNT"), (3, "PRE_QUOTE"), (4, "QUOTED"), (5, "ISSUED_POLICY"), (6, "CLAIM")])

    def test_account_summary_without_create_is_not_new_account(self):
        plan = {"steps": [step(1, "B", "Account Summary")]}
        self.assertEqual(restart.seed_points(plan), [])

    def test_claim_needs_claim_center(self):
        plan = {"steps": [step(1, "F", "Claim Summary", app="pc")]}
        self.assertEqual(restart.seed_points(plan), [])

    def test_every_seed_has_a_reason(self):
        plan = {"steps": [step(1, "D", "Quote")]}
        self.assertTrue(restart.seed_points(plan)[0]["why"])


class PlanKeysTest(unittest.TestCase):
    def test_build_plan_without_project_fills_both_lists(self):
        plan = pr.build_plan({"name": "t", "steps": []}, os.path.join(os.path.dirname(__file__), "fixtures", "cssids"))
        self.assertEqual(plan["restartCandidates"], [])
        self.assertEqual(plan["seedPointCandidates"], [])


if __name__ == "__main__":
    unittest.main()
