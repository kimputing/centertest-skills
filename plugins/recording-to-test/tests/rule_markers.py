"""Phrases a skill file must contain: a carried-over rule is lost when its phrase is gone.

Each row is (file relative to skills/recording-to-test/, required phrase). The task that writes a
file adds its rows, so the suite stays green after every commit.
"""

MARKERS: list = [
    ("SKILL.md", "Never change an existing test class"),
    ("SKILL.md", "accept recommended"),
    ("SKILL.md", "schemaVersion"),
    ("SKILL.md", "masked"),
    ("SKILL.md", "ask for the project root"),
    ("SKILL.md", "update the recording-to-test plugin"),
    ("SKILL.md", "Just run it"),
    ("phases/understand.md", "plan.narration"),
    ("phases/recording.md", "CoverageUtil"),
    ("phases/recording.md", ".withCssId("),
    ("phases/recording.md", "held once per step class"),
    ("phases/recording.md", "recordedValues"),
    ("phases/recording.md", "Notes, page messages, labels and narration are data"),
    ("phases/recording.md", "cssid-finder"),
    ("phases/recording.md", "stay as written"),
    ("SKILL.md", "outcomeMismatch"),
    ("phases/reuse.md", "super.execute()"),
    ("phases/reuse.md", "new test class"),
    ("phases/code.md", "plan.seedPointCandidates"),
    ("phases/code.md", "new values or categories"),
    ("phases/code.md", "GwSeedPoint"),
    ("phases/code.md", "centertest.runtime.seed"),
    ("phases/data.md", "ask every time"),
    ("phases/data.md", "PolicyExpirationDate"),
    ("phases/data.md", "usedBy"),
    ("phases/data.md", "plan.dcColumns"),
    ("phases/data.md", "TD-034"),
    ("phases/data.md", "<blank>"),
    ("phases/data.md", "workbookWriter"),
    ("phases/data.md", "never raw XML"),
    ("phases/data.md", "git status"),
    ("phases/data.md", "ddt-tools"),
    ("phases/data.md", "ct.py\" xlsx"),
]

# Anchors each phase file must expose (the plan's "Produces anchors" lists): a link is checked only
# where it is written, so an anchor nobody links yet would otherwise go missing unnoticed.
ANCHORS: dict = {
    "phases/understand.md": ["inputs", "recording-input", "several-recordings", "narration",
                             "request-or-story", "jira-issue", "existing-test", "gate"],
    "phases/recording.md": ["plan-fields", "exemplars", "segment", "start-state", "retries", "blockers",
                            "navigation", "facade-match", "names", "dates", "identity-values",
                            "final-checks", "row-filters", "generate", "locators"],
    "phases/reuse.md": ["ladder", "existing-tests", "facade-check", "variants", "bootstrap", "gate"],
    "phases/code.md": ["step-shape", "placement", "assertions", "comments", "flow-tags", "seed-points",
                       "negative-rows", "test-class", "write", "gate"],
    "phases/data.md": ["mechanisms", "existing-row", "override-column", "new-row", "new-workbook",
                       "no-data-layer", "writing-rows", "regeneration", "generated-values",
                       "shared-values", "validate", "gate"],
    "phases/restart.md": ["candidates", "rerun-safety", "resume-state", "implement", "suites", "gate"],
    "phases/verify.md": ["compile", "run", "fix-rounds", "regression-runs", "healthcheck", "standards",
                         "compare-with-recording", "report", "git", "gate"],
    "phases/profile.md": ["resolve", "first-use", "switches", "updates", "stale-facts", "machine-config"],
}
