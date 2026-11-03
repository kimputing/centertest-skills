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
]
