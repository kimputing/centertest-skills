#!/usr/bin/env python3
"""
Configuration management for centertest-healthcheck.

Resolution order (first wins):
    1. CLI arguments
    2. Environment variables (EIR_* → eir.*)
    3. Config file (~/.centertest/centertest-healthcheck.json)
    4. Defaults

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/centertest-healthcheck/scripts/eir_config.py
"""

import json
import os
import sys

CONFIG_DIR = os.path.expanduser("~/.centertest")
CONFIG_FILE = os.path.join(CONFIG_DIR, "centertest-healthcheck.json")

# Default rulesets matching Eir's rulesets.conf + new beyond-Eir sets
DEFAULT_RULESETS = {
    "Statistics":        ["0001", "1001"],
    "PackageStatistics": ["0002"],
    "FixSet":            ["1002", "1003", "1004", "2001", "2002"],
    "XPath":             ["3001"],
    "Methods":           ["4001", "4002"],
    "Full":              ["0001", "0002", "1001", "1002", "1003", "1004",
                          "2001", "2002", "3001", "4001", "4002"],
    "CenterTest":        ["9001", "9003", "9005", "9007", "9008", "3001"],
    "Quality":           ["5001", "5002", "15001", "15002", "15004", "15006", "15016", "7001"],
    "Security":          ["7001"],
    "CenterTestFull":    ["0001", "0002", "1001", "1002", "1003", "1004",
                          "2001", "2002", "3001", "4001", "4002",
                          "5001", "5002", "7001",
                          "9001", "9003", "9005", "9007", "9008",
                          "15001", "15002", "15004", "15005", "15006", "15016"],
}

# Default threshold values for configurable rules
DEFAULT_THRESHOLDS = {
    "4001": 2,   # variable substitution: min occurrences
    "4002": 2,   # duplicate row selection: min occurrences
    "5001": 10,  # cyclomatic complexity threshold
    "5002": 50,  # method length threshold (lines)
}


def load_config():
    """Load config from ~/.centertest/eir-analyzer.json."""
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config):
    """Save config to ~/.centertest/eir-analyzer.json."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Config saved to {CONFIG_FILE}")


def set_path(path):
    """Set or override the project path."""
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        print(f"Error: directory not found: {path}", file=sys.stderr)
        sys.exit(1)
    config = load_config()
    old = config.get("repository_dir", "(not set)")
    config["repository_dir"] = path
    save_config(config)
    print(f"  Old: {old}")
    print(f"  New: {path}")


def show_path():
    """Show the current configured path."""
    env_val = os.environ.get("EIR_REPOSITORY_DIR")
    config = load_config()
    saved = config.get("repository_dir")
    if env_val:
        print(f"Active path (from EIR_REPOSITORY_DIR env var): {env_val}")
        if saved:
            print(f"Saved path (overridden by env var): {saved}")
    elif saved:
        print(f"Active path: {saved}")
    else:
        print("No path configured. Use --set-path or set EIR_REPOSITORY_DIR env var.")


def _env_to_prop(env_key):
    """Convert EIR_RULE_4001_THRESHOLD → eir.rule.4001.threshold."""
    return env_key.lower().replace("_", ".")


def _load_env_props():
    """Load properties from EIR_* environment variables."""
    props = {}
    for key, val in os.environ.items():
        if key.startswith("EIR_"):
            props[_env_to_prop(key)] = val
    return props


class EirConfig:
    """Resolved configuration for a single eir-analyzer run."""

    def __init__(self, cli_args=None):
        # Layer 4: defaults
        self.repository_dir = os.getcwd()
        self.source_root = "src/main/java"
        self.ruleset = "Full"
        self.rules = None  # specific rule IDs override ruleset
        self.exclude_packages = [".*datadriven.*"]  # generated code, skip by default
        self.exclude_files = []
        self.commit_from = None
        self.commit_to = None
        self.commit_list = None
        self.commit_monthly = False
        self.pr_target = None
        self.pr_source = None
        self.output_formats = ["html", "excel", "terminal"]
        self.files = None  # specific files to analyze
        self.max_commits = 24
        self.compat_comment_lines = True  # bug-compatible with Eir
        self.thresholds = dict(DEFAULT_THRESHOLDS)

        # Layer 3: config file
        config = load_config()
        if config.get("repository_dir"):
            self.repository_dir = config["repository_dir"]
        if config.get("default_ruleset"):
            self.ruleset = config["default_ruleset"]
        if config.get("source_root"):
            self.source_root = config["source_root"]
        if config.get("exclude_packages"):
            self.exclude_packages = config["exclude_packages"]
        if config.get("exclude_files"):
            self.exclude_files = config["exclude_files"]
        if config.get("thresholds"):
            self.thresholds.update(config["thresholds"])
        custom_rulesets = config.get("custom_rulesets", {})

        # Layer 2: environment variables
        env_props = _load_env_props()
        if "eir.repository.dir" in env_props:
            self.repository_dir = env_props["eir.repository.dir"]
        if "eir.report.ruleset" in env_props:
            self.ruleset = env_props["eir.report.ruleset"]
        if "eir.source.root" in env_props:
            self.source_root = env_props["eir.source.root"]
        if "eir.exclude.package" in env_props:
            self.exclude_packages = [p.strip() for p in env_props["eir.exclude.package"].split(",") if p.strip()]
        if "eir.exclude.file" in env_props:
            self.exclude_files = [p.strip() for p in env_props["eir.exclude.file"].split(",") if p.strip()]
        if "eir.commit.from" in env_props:
            self.commit_from = env_props["eir.commit.from"]
        if "eir.commit.to" in env_props:
            self.commit_to = env_props["eir.commit.to"]
        if "eir.commit.list" in env_props:
            self.commit_list = [s.strip() for s in env_props["eir.commit.list"].split(",") if s.strip()]
        if "eir.commit.monthly" in env_props:
            self.commit_monthly = env_props["eir.commit.monthly"].lower() == "true"
        if "eir.branch.target" in env_props:
            self.pr_target = env_props["eir.branch.target"]
        if "eir.branch.new" in env_props:
            self.pr_source = env_props["eir.branch.new"]
        if "eir.compat.comment.lines" in env_props:
            self.compat_comment_lines = env_props["eir.compat.comment.lines"].lower() == "true"
        # Load rule-specific thresholds from env
        for key, val in env_props.items():
            if key.startswith("eir.rule.") and key.endswith(".threshold"):
                rule_id = key.split(".")[2]
                try:
                    self.thresholds[rule_id] = int(val)
                except ValueError:
                    pass

        # Layer 1: CLI arguments (highest priority)
        if cli_args:
            if cli_args.path:
                self.repository_dir = os.path.expanduser(cli_args.path)
            if cli_args.ruleset:
                self.ruleset = cli_args.ruleset
            if cli_args.rules:
                self.rules = [r.strip() for r in cli_args.rules.split(",") if r.strip()]
            if cli_args.exclude_package:
                self.exclude_packages = [p.strip() for p in cli_args.exclude_package.split(",") if p.strip()]
            if cli_args.exclude_file:
                self.exclude_files = [p.strip() for p in cli_args.exclude_file.split(",") if p.strip()]
            if cli_args.commit_from:
                self.commit_from = cli_args.commit_from
            if cli_args.commit_to:
                self.commit_to = cli_args.commit_to
            if cli_args.commits:
                self.commit_list = [s.strip() for s in cli_args.commits.split(",") if s.strip()]
            if cli_args.monthly:
                self.commit_monthly = True
            if hasattr(cli_args, 'pr') and cli_args.pr:
                self.pr_target = cli_args.pr[0]
                self.pr_source = cli_args.pr[1]
            if cli_args.output:
                self.output_formats = [f.strip() for f in cli_args.output.split(",") if f.strip()]
            if cli_args.files:
                self.files = [f.strip() for f in cli_args.files.split(",") if f.strip()]
            if hasattr(cli_args, 'source_root') and cli_args.source_root:
                self.source_root = cli_args.source_root
            if hasattr(cli_args, 'max_commits') and cli_args.max_commits:
                self.max_commits = cli_args.max_commits

        # Merge custom rulesets from config file
        self.rulesets = dict(DEFAULT_RULESETS)
        self.rulesets.update(custom_rulesets)

    def get_active_rule_ids(self):
        """Return the list of rule IDs to execute."""
        if self.rules:
            return self.rules
        return self.rulesets.get(self.ruleset, [])

    def get_threshold(self, rule_id, default=None):
        """Get the threshold for a specific rule."""
        if default is None:
            default = DEFAULT_THRESHOLDS.get(rule_id, 0)
        return int(self.thresholds.get(rule_id, default))

    def has_git_options(self):
        """Check if any git-based analysis mode is requested."""
        return bool(
            self.commit_from or self.commit_to or self.commit_list
            or self.commit_monthly or self.pr_target or self.pr_source
        )

    def get_commit_selection_mode(self):
        """
        Return the commit selection mode.

        Priority matching Eir: PR > commits > monthly > date range > local.
        """
        if self.pr_target and self.pr_source:
            return "pr"
        if self.commit_list:
            return "commits"
        if self.commit_monthly:
            return "monthly"
        if self.commit_from or self.commit_to:
            return "date_range"
        return "local"
