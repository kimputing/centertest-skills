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
    eir_analyzer.py --review main [feature/branch]
    eir_analyzer.py --trend [MONTHS]
    eir_analyzer.py --portfolio <project> [<project> ...]

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/centertest-healthcheck/scripts/eir_analyzer.py
"""

from __future__ import annotations

import argparse
import os
import re
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
    print(f"ERROR: openpyxl is not installed for {sys.executable}.\n"
          f"  Install it for this Python: \"{sys.executable}\" -m pip install openpyxl\n"
          "  If pip refuses (Homebrew and other externally managed Pythons), create the CenterTest\n"
          "  environment once; the skills use it automatically:\n"
          "    python3 -m venv ~/.centertest/venv && ~/.centertest/venv/bin/python -m pip install openpyxl javalang",
          file=sys.stderr)
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
from eir_suppressions import load_suppressions, apply_suppressions, show_suppressions


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
    p.add_argument("--output", help="Output formats: html,excel,markdown,json,terminal (default: html,excel,terminal)")
    p.add_argument("--max-commits", type=int, help="Max commits to analyze (default: 24)")

    # Git options
    p.add_argument("--commit-from", help="Analyze commits from date (YYYY-MM-DD)")
    p.add_argument("--commit-to", help="Analyze commits to date (YYYY-MM-DD)")
    p.add_argument("--commits", help="Specific commit SHAs, comma-separated")
    p.add_argument("--monthly", action="store_true", help="Sample one commit per month")
    p.add_argument("--pr", nargs=2, metavar=("TARGET", "SOURCE"),
                   help="PR diff mode: analyze diff between branches")
    p.add_argument("--fix", metavar="RULE", choices=["15018"],
                   help="Rewrite findings of RULE (15018: discarded .equals() -> assertion); prints a diff, "
                        "writes only with --write")
    p.add_argument("--write", action="store_true", help="With --fix: apply the changes")
    p.add_argument("--cssids", metavar="DIR",
                   help="Generated project's src/main/resources (or its cssids/) for the screens and product coverage panels; "
                        "default: <project>-generated next to the project, then the cssid-finder config")
    p.add_argument("--trend", nargs="?", const=6, type=int, metavar="MONTHS",
                   help="Health trend: score, trust blockers and test cases for the last mainline "
                        "commit of each of the last MONTHS months (default 6), as an HTML page")
    p.add_argument("--portfolio", nargs="+", metavar="PROJECT",
                   help="Compare several CenterTest projects on one page (score, trust blockers, "
                        "scenarios, wizards, broken data); reads them only; page in ~/.centertest/reports/")
    p.add_argument("--statement", action="store_true",
                   help="A one-page coverage statement for the client: flows, scenarios, coverages and options "
                        "selected, jurisdictions, suites and known gaps (healthcheck/Coverage_Statement_*.html)")
    p.add_argument("--cover", nargs="?", const="", metavar="SUITE",
                   help="The fewest scenarios that still run every test method, select every product coverage and run "
                        "every line in every jurisdiction the full regression does: a suite and its command. With a "
                        "suite name: what that suite misses, and the fewest scenarios to add")
    p.add_argument("--deep", action="store_true",
                   help="With --cover: also keep every limit and deductible option the full run sets")
    p.add_argument("--of", metavar="SUITE",
                   help="With --cover: measure against this suite instead of every scenario that runs")
    p.add_argument("--scenario", nargs=2, metavar=("TEST", "CODE"),
                   help="Everything one scenario enters: its DataCombination row (TEST = test class or DC workbook, "
                        "CODE = row code) and every row it references, as a tree, with the tests and suites that run it")
    p.add_argument("--uses", metavar="PATTERN", action="append",
                   help="Which scenarios exercise a coverage, product, state ... : test data rows whose cell "
                        "matches PATTERN (whole cell, case-insensitive regex), followed through references; "
                        "prints the tests and a suite that runs exactly them; repeat it for rows that use every value")
    p.add_argument("--touches", metavar="PAGE",
                   help="Which tests touch a screen: regex over the generated page classes the project uses "
                        "(e.g. PolicyChangeWizard), or Page.getWidget for one widget; prints the tests and a "
                        "suite that runs them")
    p.add_argument("--weekly", nargs="+", metavar="PROJECT",
                   help="What landed in each suite in the last --days days (default 7): verdict, new trust "
                        "blockers, coverages lost, data rows, tests to rerun; reads the projects only; page in "
                        "~/.centertest/reports/")
    p.add_argument("--days", type=int, default=7, help="With --weekly: how many days back (default 7)")
    p.add_argument("--json", action="store_true",
                   help="Print the result of any mode as one JSON document on stdout (progress goes to stderr)")
    p.add_argument("--review", nargs="+", metavar="REV",
                   help="Branch review: BASE [HEAD] (HEAD defaults to HEAD). Lists only the findings "
                        "the branch introduced or fixed since its merge-base, writes a PR comment and "
                        "exits 1 when it introduces a trust blocker")

    # Config management
    p.add_argument("--set-path", metavar="DIR", help="Save project path to config")
    p.add_argument("--show-path", action="store_true", help="Show configured project path")

    # Suppressions
    p.add_argument("--show-suppressions", action="store_true", help="Show current suppressions")

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

    if args.show_suppressions:
        config = EirConfig(args)
        output_dir = os.path.join(config.repository_dir, "healthcheck")
        show_suppressions(output_dir)
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

    if args.portfolio:
        from eir_portfolio import run_portfolio
        if not args.ruleset and not args.rules:
            config.ruleset = "CenterTestFull"  # a portfolio compares complete verdicts
        print(f"\n  CenterTest portfolio: {len(args.portfolio)} project(s), rules {config.ruleset}")
        sys.exit(run_portfolio(config, args.portfolio))

    if args.weekly:
        from eir_weekly import run_weekly
        if not args.ruleset and not args.rules:
            config.ruleset = "CenterTestFull"
        print(f"\n  CenterTest weekly: {len(args.weekly)} project(s), last {args.days} days")
        sys.exit(run_weekly(config, args.weekly, args.days, args.cssids))

    if args.statement:
        from eir_screens import find_cssids_dir
        from eir_statement import write as write_statement
        path = write_statement(config.repository_dir, config.source_root,
                               find_cssids_dir(config.repository_dir, args.cssids))
        print(f"  Coverage statement: {path}")
        sys.exit(0)

    if args.cover is not None:
        from eir_cover import cover_report, print_cover
        from eir_impact import suite_command
        from eir_json import emit
        from eir_screens import find_cssids_dir
        report = cover_report(config.repository_dir, config.source_root,
                              find_cssids_dir(config.repository_dir, args.cssids), args.cover or None, args.of,
                              args.deep)
        name = f"Cover-{re.sub(r'[^A-Za-z0-9]+', '', args.cover)[:40]}" if args.cover else "Cover-Breadth"
        command = suite_command(config.repository_dir, name)
        emit(dict(report, suite_name=name, command=command))
        print_cover(report, name, command)
        sys.exit(2 if report.get("error") else 0)

    if args.scenario:
        from eir_json import emit
        from eir_uses import print_scenario, scenario_report
        from eir_screens import find_cssids_dir
        report = scenario_report(config.repository_dir, config.source_root, *args.scenario,
                                 cssids_dir=find_cssids_dir(config.repository_dir, args.cssids))
        emit(report)
        print_scenario(report)
        sys.exit(0 if report["found"] else 1)

    if args.uses:
        from eir_impact import suite_command
        from eir_uses import print_uses, suite_name, uses_report
        name = suite_name(" ".join(args.uses))
        from eir_json import emit
        report = uses_report(config.repository_dir, config.source_root, args.uses)
        emit(dict(report, suite=name, command=suite_command(config.repository_dir, name)))
        print_uses(report, name, suite_command(config.repository_dir, name))
        sys.exit(0)

    if args.touches:
        from eir_impact import suite_command
        from eir_uses import print_touches, touches_report
        name = "Touches-" + (re.sub(r"[^A-Za-z0-9]+", "", args.touches) or "Page")[:40]
        from eir_screens import find_cssids_dir
        report = touches_report(config.repository_dir, config.source_root, args.touches,
                                find_cssids_dir(config.repository_dir, args.cssids))
        from eir_json import emit
        emit(dict(report, suite=name, command=suite_command(config.repository_dir, name)))
        print_touches(report, name,
                      suite_command(config.repository_dir, name))
        sys.exit(0)

    if args.trend:
        from eir_trend import run_trend
        print(f"\n  CenterTest health trend: last {args.trend} months  ({config.repository_dir})")
        suppressions = load_suppressions(os.path.join(config.repository_dir, "healthcheck"))
        sys.exit(run_trend(config, args.trend, suppressions, cssids=args.cssids))

    if args.review:
        if len(args.review) > 2:
            parser.error("--review takes BASE and optionally HEAD")
        from eir_review import run_review
        base_rev = args.review[0]
        head_rev = args.review[1] if len(args.review) > 1 else "HEAD"
        print(f"\n  CenterTest branch review: {head_rev} vs {base_rev}  ({config.repository_dir})")
        suppressions = load_suppressions(os.path.join(config.repository_dir, "healthcheck"))
        sys.exit(run_review(config, base_rev, head_rev, suppressions, cssids=args.cssids))

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
    print(f"\n[2/4] Running {len(active_ids)} analysis rule(s)...")
    results = run_rules(commits, config)
    if not config.has_git_options():
        from eir_locate import annotate_locations
        annotate_locations(results, commits, config.repository_dir)
    if args.fix:
        from eir_fix import run_fix
        sys.exit(run_fix(config.repository_dir, results, args.write))

    # Step 3: Apply suppressions
    output_dir = os.path.join(config.repository_dir, "healthcheck")
    suppressions = load_suppressions(output_dir)
    suppressed_count = 0
    if suppressions:
        results, suppressed_count = apply_suppressions(results, suppressions)
        print(f"\n[3/4] Applied {len(suppressions)} suppression(s) — {suppressed_count} finding(s) suppressed")
    else:
        print(f"\n[3/4] No suppressions configured")

    # Step 4: Generate reports
    print(f"\n[4/4] Generating reports...")
    output_dir = os.path.join(config.repository_dir, "healthcheck")
    generated = []
    elapsed = time.time() - start_time
    project_name = os.path.basename(config.repository_dir)

    screens = data = products = states = suite_reach = since = None
    if not config.has_git_options():
        from eir_data import data_overview
        data = data_overview(config.repository_dir, config.source_root, results)
        from eir_screens import find_cssids_dir, screen_coverage
        cssids = find_cssids_dir(config.repository_dir, args.cssids)
        screens = screen_coverage(config.repository_dir, config.source_root, cssids) if cssids else []
        from eir_products import product_coverage
        products = product_coverage(config.repository_dir, cssids, config.source_root)
        from eir_states import state_coverage
        states = state_coverage(config.repository_dir, cssids)
        from eir_cover import suite_breadth
        suite_reach = suite_breadth(config.repository_dir, config.source_root, cssids)
        from eir_since import since_last, snapshot
        from eir_since import flows_running
        since = since_last(output_dir, snapshot(results, total_files, data, products, states,
                                                flows_running(config.repository_dir, config.source_root)))

    # Excel first (appendix — referenced by HTML)
    excel_filename = ""
    if "excel" in config.output_formats:
        filepath = generate_excel(results, output_dir, total_files=total_files, data=data, products=products,
                                  states=states, suite_reach=suite_reach)
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
            suppressed_count=suppressed_count,
            screens=screens,
            data=data,
            products=products,
            states=states,
            suite_reach=suite_reach,
            since=since,
        )
        if filepath:
            generated.append(filepath)
            print(f"  HTML:     {filepath}")

    from eir_json import emit, health_json, write
    doc = health_json(results, project_name, total_files, data, screens, products, since, states, suite_reach)
    emit(doc)
    if "json" in config.output_formats:
        filepath = write(doc, output_dir, "HealthCheck")
        generated.append(filepath)
        print(f"  JSON:     {filepath}")

    if "markdown" in config.output_formats:
        filepath = generate_markdown(results, output_dir)
        if filepath:
            generated.append(filepath)
            print(f"  Markdown: {filepath}")

    if "terminal" in config.output_formats:
        print_terminal_summary(results, suppressed_count)
        if data:
            from eir_data import print_data
            print_data(data)
        if screens:
            from eir_screens import print_screens
            print_screens(screens)
        if products:
            from eir_products import print_products
            print_products(products)
        if states:
            from eir_states import print_states
            print_states(states)
        if suite_reach:
            from eir_cover import print_suite_breadth
            print_suite_breadth(suite_reach)
        if since:
            from eir_since import print_since
            print_since(since)

    print(f"\n  Completed in {elapsed:.1f}s")
    if generated:
        print(f"  Reports saved to: {output_dir}/")
    print()


def _main_json():
    """--json: progress to stderr, the mode's result as one JSON document on stdout (for the MCP server, CI)."""
    import json
    import eir_json
    real = sys.stdout
    sys.stdout = sys.stderr
    code = 0
    try:
        main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        sys.stdout = real
    print(json.dumps(eir_json.LAST[0] if eir_json.LAST else {"error": "no result", "exit_code": code},
                     ensure_ascii=False))
    sys.exit(code)


if __name__ == "__main__":
    if "--json" in sys.argv[1:]:
        _main_json()
    else:
        main()
