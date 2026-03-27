#!/usr/bin/env python3
"""
centertest-healthcheck — Automated health check for CenterTest Java projects.

Parses Java source files, applies configurable analysis rules, and generates
Excel/Markdown reports with actionable findings.

Usage:
    eir_analyzer.py [options]
    eir_analyzer.py --list-rules
    eir_analyzer.py --list-rulesets
    eir_analyzer.py --set-path "/path/to/project"
    eir_analyzer.py --show-path

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/centertest-healthcheck/scripts/eir_analyzer.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Ensure scripts/ is on the path for imports
sys.path.insert(0, os.path.dirname(__file__))

# ---------------------------------------------------------------------------
# Dependency guards (matching existing skill pattern)
# ---------------------------------------------------------------------------

try:
    from openpyxl import Workbook  # noqa: F401
except ImportError:
    print("ERROR: openpyxl is required. Install with: pip install openpyxl", file=sys.stderr)
    sys.exit(1)

try:
    import javalang  # noqa: F401
except ImportError:
    print("WARNING: javalang not installed. Using regex fallback parser (reduced accuracy).",
          file=sys.stderr)
    print("  Install with: pip install javalang", file=sys.stderr)

# ---------------------------------------------------------------------------
# Internal imports (after path setup)
# ---------------------------------------------------------------------------

from eir_config import EirConfig, set_path, show_path
from eir_models import LOCAL_COMMIT, CommitsDict
from eir_parser import parse_directory
from eir_rules import discover_rules, run_rules, list_rules, list_rulesets, get_registry
from eir_report import generate_excel, generate_markdown, generate_html, print_terminal_summary
from eir_git import parse_commits_from_git


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="centertest-healthcheck",
        description="Automated health check for CenterTest Java projects.",
    )
    # Analysis options
    p.add_argument("--path", help="Project root directory (default: configured or cwd)")
    p.add_argument("--ruleset", help="Rule set to run (default: Full)")
    p.add_argument("--rules", help="Specific rule IDs, comma-separated (overrides --ruleset)")
    p.add_argument("--exclude-package", help="Package patterns to exclude, comma-separated")
    p.add_argument("--exclude-file", help="File patterns to exclude, comma-separated")
    p.add_argument("--source-root", help="Source root relative to project (default: src/main/java)")
    p.add_argument("--files", help="Analyze specific files only, comma-separated paths")
    p.add_argument("--output", help="Output formats: excel,markdown,terminal (default: excel,terminal)")
    p.add_argument("--max-commits", type=int, help="Max commits to analyze (default: 24)")

    # Git options
    p.add_argument("--commit-from", help="Analyze commits from date (YYYY-MM-DD)")
    p.add_argument("--commit-to", help="Analyze commits to date (YYYY-MM-DD)")
    p.add_argument("--commits", help="Specific commit SHAs, comma-separated")
    p.add_argument("--monthly", action="store_true", help="Sample one commit per month")
    p.add_argument("--pr", nargs=2, metavar=("TARGET", "SOURCE"),
                   help="PR diff mode: analyze diff between branches")

    # Config management
    p.add_argument("--set-path", metavar="DIR", help="Save project path to config")
    p.add_argument("--show-path", action="store_true", help="Show configured project path")

    # Info
    p.add_argument("--list-rules", action="store_true", help="List all available rules")
    p.add_argument("--list-rulesets", action="store_true", help="List all rule sets")

    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()

    # Discover rules first (needed for --list-rules/--list-rulesets)
    discover_rules()

    # Handle info/config commands
    if args.set_path:
        set_path(args.set_path)
        return

    if args.show_path:
        show_path()
        return

    if args.list_rules:
        rules = list_rules()
        if not rules:
            print("No rules found.")
            return
        print(f"\nAvailable rules ({len(rules)}):\n")
        print(f"  {'ID':<8} {'Category':<15} Description")
        print(f"  {'—'*6:<8} {'—'*13:<15} {'—'*40}")
        for r in rules:
            print(f"  {r.id:<8} {r.category:<15} {r.description}")
        print()
        return

    if args.list_rulesets:
        config = EirConfig()
        rulesets = config.rulesets
        registry = get_registry()
        print(f"\nAvailable rule sets ({len(rulesets)}):\n")
        for name, ids in sorted(rulesets.items()):
            available = sum(1 for i in ids if i in registry)
            print(f"  {name:<20} {len(ids)} rules ({available} implemented): {', '.join(ids)}")
        print()
        return

    # Build config from all layers
    config = EirConfig(args)

    # Banner
    print()
    print("=" * 60)
    print("  CenterTest Health Check")
    print("=" * 60)
    print(f"  Project:  {config.repository_dir}")
    print(f"  Source:   {config.source_root}")
    print(f"  Ruleset:  {config.ruleset}")
    active_ids = config.get_active_rule_ids()
    print(f"  Rules:    {len(active_ids)} active")
    print(f"  Mode:     {config.get_commit_selection_mode()}")
    print("=" * 60)
    print()

    start_time = time.time()

    # Step 1: Parse source files
    print("[1/3] Parsing Java source files...")

    commits: CommitsDict
    if config.has_git_options():
        commits = parse_commits_from_git(config)
    else:
        # Local mode — parse working directory
        specific_files = None
        if config.files:
            specific_files = config.files
        files = parse_directory(
            config.repository_dir,
            config.source_root,
            config.exclude_packages,
            config.exclude_files,
            config.compat_comment_lines,
            specific_files,
        )
        commits = {LOCAL_COMMIT: files}

    # Stats
    total_files = sum(len(f) for f in commits.values())
    total_unparsed = sum(1 for files in commits.values() for f in files if f.cannot_compile)
    print(f"  Parsed {total_files} file(s) across {len(commits)} commit(s)")
    if total_unparsed > 0:
        print(f"  WARNING: {total_unparsed} file(s) could not be parsed "
              f"(Java 14+ syntax or errors). Results may be incomplete.")

    if total_files == 0:
        print("\n  No Java files found. Check --path and --source-root settings.")
        return

    # Step 2: Run rules
    print(f"\n[2/3] Running {len(active_ids)} analysis rule(s)...")
    results = run_rules(commits, config)

    # Step 3: Generate reports
    print(f"\n[3/3] Generating reports...")
    output_dir = os.path.join(config.repository_dir, "healthcheck")
    generated = []
    elapsed = time.time() - start_time
    project_name = os.path.basename(config.repository_dir)

    # Excel first (appendix — referenced by HTML)
    excel_filename = ""
    if "excel" in config.output_formats:
        filepath = generate_excel(results, output_dir)
        if filepath:
            excel_filename = os.path.basename(filepath)
            generated.append(filepath)
            print(f"  Excel:    {filepath}")

    # HTML (primary report)
    if "html" in config.output_formats:
        filepath = generate_html(
            results, output_dir,
            project_name=project_name,
            total_files=total_files,
            elapsed=elapsed,
            excel_filename=excel_filename,
        )
        if filepath:
            generated.append(filepath)
            print(f"  HTML:     {filepath}")

    if "markdown" in config.output_formats:
        filepath = generate_markdown(results, output_dir)
        if filepath:
            generated.append(filepath)
            print(f"  Markdown: {filepath}")

    if "terminal" in config.output_formats:
        print_terminal_summary(results)

    print(f"\n  Completed in {elapsed:.1f}s")
    if generated:
        print(f"  Reports saved to: {output_dir}/")
    print()


if __name__ == "__main__":
    main()
