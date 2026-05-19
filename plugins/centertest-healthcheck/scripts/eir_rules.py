#!/usr/bin/env python3
"""
Rule engine for eir-analyzer.

Decorator-based rule registry with auto-discovery.
Mirrors Eir's Spring @RuleClass/@Rule annotation system.

Usage:
    from eir_rules import rule, run_rules, list_rules

    @rule(id="0001", description="General test statistics", category="Statistics")
    def general_stats(commits, config):
        ...
        return RuleResult(...)

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/eir-analyzer/scripts/eir_rules.py
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass, field
from typing import Callable

from eir_models import CommitsDict, RuleResult


@dataclass
class RuleEntry:
    """Metadata for a registered rule."""
    id: str
    description: str
    category: str
    func: Callable[[CommitsDict, object], RuleResult]
    periodic: bool = False  # True = show per-commit trends; False = snapshot (latest only)


# Global registry — populated by @rule decorator
_RULE_REGISTRY: dict[str, RuleEntry] = {}


def rule(id: str, description: str, category: str = "General", periodic: bool = False):
    """
    Decorator to register an analysis rule.

    Args:
        periodic: If True, this rule produces meaningful per-commit trend data
                  (e.g. statistics, counts). If False, findings are shown only
                  for the latest commit to avoid duplicates in monthly mode.

    Usage:
        @rule(id="0001", description="General test statistics", category="Statistics", periodic=True)
        def general_stats(commits, config):
            return RuleResult(...)
    """
    def decorator(func):
        _RULE_REGISTRY[id] = RuleEntry(
            id=id,
            description=description,
            category=category,
            func=func,
            periodic=periodic,
        )
        return func
    return decorator


def discover_rules():
    """
    Import all rule_*.py modules in the rules/ package to trigger registration.

    Must be called once before run_rules().
    """
    rules_dir = os.path.join(os.path.dirname(__file__), "rules")
    if not os.path.isdir(rules_dir):
        return

    # Ensure the rules directory is importable
    if rules_dir not in sys.path:
        sys.path.insert(0, os.path.dirname(__file__))

    for fname in sorted(os.listdir(rules_dir)):
        if fname.startswith("rule_") and fname.endswith(".py"):
            module_name = f"rules.{fname[:-3]}"
            try:
                importlib.import_module(module_name)
            except Exception as e:
                print(f"  Warning: Could not load rule module {fname}: {e}", file=sys.stderr)


def get_registry() -> dict[str, RuleEntry]:
    """Return the global rule registry."""
    return _RULE_REGISTRY


def list_rules() -> list[RuleEntry]:
    """Return all registered rules sorted by ID."""
    return sorted(_RULE_REGISTRY.values(), key=lambda r: r.id)


def list_rulesets(config) -> dict[str, list[str]]:
    """Return all available rulesets."""
    return config.rulesets


def run_rules(commits: CommitsDict, config) -> list[RuleResult]:
    """
    Execute enabled rules against parsed commits.

    In multi-commit mode (monthly, date range, etc.):
    - Periodic rules receive ALL commits (for trend data)
    - Snapshot rules receive only the LATEST commit (to avoid duplicate findings)

    Returns list of RuleResult objects (one per rule).
    Each rule is wrapped in try/except — failures produce error RuleResults.
    """
    active_ids = config.get_active_rule_ids()
    sorted_rules = sorted(
        [r for r in _RULE_REGISTRY.values() if r.id in active_ids],
        key=lambda r: r.id,
    )

    if not sorted_rules:
        print("  No rules matched the active ruleset.", file=sys.stderr)
        return []

    # Build latest-only commits dict for snapshot rules
    is_multi_commit = len(commits) > 1
    if is_multi_commit:
        latest_key = max(commits.keys())
        latest_commits: CommitsDict = {latest_key: commits[latest_key]}
    else:
        latest_commits = commits

    results = []
    total = len(sorted_rules)

    for i, rule_entry in enumerate(sorted_rules, 1):
        mode_label = ""
        if is_multi_commit:
            mode_label = " [trend]" if rule_entry.periodic else " [latest]"
        print(f"  [{i}/{total}] Running rule {rule_entry.id}: {rule_entry.description}{mode_label}...")

        # Periodic rules get all commits; snapshot rules get latest only
        rule_commits = commits if rule_entry.periodic else latest_commits

        try:
            result = rule_entry.func(rule_commits, config)
            if result is None:
                result = RuleResult(
                    rule_id=rule_entry.id,
                    description=rule_entry.description,
                    category=rule_entry.category,
                )
            results.append(result)
        except Exception as exc:
            print(f"  WARNING: Rule {rule_entry.id} failed: {exc}", file=sys.stderr)
            results.append(RuleResult(
                rule_id=rule_entry.id,
                description=rule_entry.description,
                category=rule_entry.category,
                error=str(exc),
            ))

    return results
