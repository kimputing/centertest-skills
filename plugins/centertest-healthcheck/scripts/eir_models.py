#!/usr/bin/env python3
"""
Data models for the eir-analyzer skill.

Replicates Eir's com.eir.entries package with Python dataclasses.
Custom __eq__/__hash__ match Java semantics exactly for rule correctness.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Core parsed-code models
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Field:
    """Java field declaration. Equality: name + type only."""
    name: str
    type: str
    modifiers: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)

    def __eq__(self, other):
        return isinstance(other, Field) and (self.name, self.type) == (other.name, other.type)

    def __hash__(self):
        return hash((self.name, self.type))


@dataclass(eq=False)
class Method:
    """Java method declaration. Equality: name + body only (for rule 2001)."""
    name: str
    modifiers: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    body: str = ""

    def __eq__(self, other):
        return isinstance(other, Method) and (self.name, self.body) == (other.name, other.body)

    def __hash__(self):
        return hash((self.name, self.body))


@dataclass(eq=False)
class ClassEntry:
    """
    Java class declaration.

    Equality excludes class_name and key — compares structural content only.
    This is critical for rule 2002 (inner class duplicate detection).
    """
    class_name: str
    key: str  # packageName.ClassName (or packageName.Parent.Inner for inner classes)
    methods: list[Method] = field(default_factory=list)
    fields: list[Field] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)  # simple names, not FQN
    interfaces: list[str] = field(default_factory=list)  # simple names, not FQN
    annotations: list[str] = field(default_factory=list)  # simple annotation names
    method_count: int = 0

    def __eq__(self, other):
        if not isinstance(other, ClassEntry):
            return False
        return (
            self.methods == other.methods
            and self.fields == other.fields
            and self.extensions == other.extensions
            and self.interfaces == other.interfaces
            and self.annotations == other.annotations
        )

    def __hash__(self):
        return hash((
            tuple(self.methods),
            tuple(self.fields),
            tuple(self.extensions),
            tuple(self.interfaces),
            tuple(self.annotations),
        ))


@dataclass
class SourceCodeFile:
    """
    Parsed Java source file — mirrors Eir's SourceCodeFile.

    key = absolute file path (unique ID).
    package_name = derived from directory path, NOT from package statement.
    """
    key: str = ""
    file_name: str = ""
    parent_directory: str = ""
    package_name: str = ""
    main_class: Optional[ClassEntry] = None
    inner_classes: list[ClassEntry] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    lines: int = 0
    lines_of_code: int = 0
    blank_lines: int = 0
    comment_lines: int = 0
    cannot_compile: bool = False

    def is_test_class(self) -> bool:
        """Check if this file contains a CenterTest or ScenarioContainer class."""
        if self.main_class is None:
            return False
        annots = self.main_class.annotations
        return "CenterTest" in annots or "ScenarioContainer" in annots


# ---------------------------------------------------------------------------
# Commit key
# ---------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class CommitInfo:
    """
    Key for commits dict — sorted by commit_time (matches Java TreeMap<RevCommit>).

    For local mode (no git), use LOCAL_COMMIT sentinel.
    """
    commit_time: int  # epoch seconds
    sha: str  # 40-char hex
    short_sha: str  # sha[:7]
    message: str = ""  # first line of commit message

    @property
    def date_str(self) -> str:
        """Return commit date as YYYY-MM-DD."""
        if self.commit_time == 0:
            return "local"
        from datetime import datetime
        return datetime.fromtimestamp(self.commit_time).strftime("%Y-%m-%d")

    @property
    def label(self) -> str:
        """Return a human-readable label: 'abc1234 (2025-06-15)'."""
        if self.commit_time == 0:
            return "local"
        return f"{self.short_sha} ({self.date_str})"


LOCAL_COMMIT = CommitInfo(
    commit_time=0,
    sha="local",
    short_sha="local",
    message="working directory",
)

# Type alias
CommitsDict = dict[CommitInfo, list[SourceCodeFile]]


# ---------------------------------------------------------------------------
# Suppression model
# ---------------------------------------------------------------------------

@dataclass
class Suppression:
    """A suppressed finding — stored in healthcheck/suppressions.json."""
    rule_id: str
    class_name: str = "*"      # matches row[0], "*" = any
    method: str = "*"          # matches row[1], "*" = any
    match: str = ""            # substring match against any column
    reason: str = ""           # why this was suppressed
    added: str = ""            # date added (YYYY-MM-DD)


# ---------------------------------------------------------------------------
# Rule result models
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """A single non-tabular finding from a rule."""
    location: str
    message: str
    severity: str = "info"  # info, warning, error


@dataclass
class Section:
    """
    Hierarchical report section.

    Rules that produce grouped/nested output (1002, 1003, 2001, 2002, 3001, 4001, 4002)
    use sections instead of flat rows.
    """
    title: str
    items: list[str] = field(default_factory=list)
    subsections: list[Section] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)  # optional table within section
    rows: list[list] = field(default_factory=list)


@dataclass
class RuleResult:
    """
    Output of a single rule execution.

    Two output modes:
    - Flat tabular: headers + rows (rules 0001, 0002, 1001)
    - Hierarchical: sections (rules 1002, 1003, 2001, 2002, 3001, 4001, 4002)
    """
    rule_id: str
    description: str
    category: str = "General"
    error: Optional[str] = None
    # Flat tabular output
    headers: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    # Hierarchical output
    sections: list[Section] = field(default_factory=list)
    summary: str = ""
