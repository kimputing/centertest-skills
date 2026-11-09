#!/usr/bin/env python3
"""
Report generator for eir-analyzer.

Produces Excel (.xlsx), Markdown (.md), and terminal output.
Follows the ddt-analyzer pattern for Excel generation with openpyxl.

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/eir-analyzer/scripts/eir_report.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from eir_models import RuleResult, Section

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
except ImportError:
    Workbook = None


# ---------------------------------------------------------------------------
# Sheet name safety
# ---------------------------------------------------------------------------

_FORBIDDEN_CHARS = set("[]:\\/*?")


def _safe_sheet_name(rule_id: str, description: str, existing_names: set[str]) -> str:
    """Generate a unique, valid Excel sheet name (max 31 chars)."""
    short_desc = description[:22].strip()
    base = f"R{rule_id}_{short_desc}"
    # Remove forbidden characters
    base = "".join(c for c in base if c not in _FORBIDDEN_CHARS)
    base = base[:31]

    name = base
    counter = 2
    while name in existing_names:
        suffix = f"_{counter}"
        name = base[:31 - len(suffix)] + suffix
        counter += 1
    return name


# ---------------------------------------------------------------------------
# Excel report
# ---------------------------------------------------------------------------

def _verdict_sheet(wb, results: list[RuleResult], total_files: int, data) -> None:
    """The first sheet a reader opens: score, trust blockers with their locations, the fix order,
    and the test-data numbers -- the same functions as the HTML dashboard, so they agree."""
    ws = wb.create_sheet("Verdict", 0)
    bold, big = Font(bold=True), Font(bold=True, size=14)
    red = Font(bold=True, color="C0392B")
    score = health_score(results, total_files)
    blockers, not_checked, dormant = trust_blockers(results, sample_size=10_000)
    ws.append(["CenterTest health check", datetime.now().strftime("%Y-%m-%d %H:%M")])
    ws["A1"].font = big
    label = "At risk" if blockers else ("Healthy" if score >= 80 else "Needs attention" if score >= 60 else "Critical")
    ws.append(["Health score", score, label])
    ws.append([])
    ws.append(["Can these tests be trusted?", "No" if blockers else "No trust blockers found"])
    ws.cell(ws.max_row, 1).font = bold
    for b in blockers:
        ws.append([f"{b['count']} x {b['title']}", b["consequence"], f"rule {b['rule_id']}"])
        ws.cell(ws.max_row, 1).font = red
        for label_, loc in zip(b["samples"], b.get("locations") or [""] * len(b["samples"])):
            ws.append(["", label_.replace(f" ({loc})", "") if loc else label_, loc])
    if dormant:
        ws.append(["Not blockers", f"{dormant} data findings in workbooks no test reads or in disabled rows"])
    if not_checked:
        ws.append(["Not checked", "rules " + ", ".join(not_checked)])
    ws.append([])
    ws.append(["What to fix first", "Findings", "Top rules"])
    ws.cell(ws.max_row, 1).font = bold
    for t in fix_order(results):
        ws.append([t["title"], t["count"], "; ".join(f"{d} ({c})" for _r, d, c in t["rules"][:5])])
    if data:
        ws.append([])
        ws.append(["Test data", "", ""])
        ws.cell(ws.max_row, 1).font = bold
        ws.append(["Scenario runs in a full run", data["scenarios"], "Multiplier repeats included"])
        ws.append(["DC workbooks no test reads", len(data["unread"]), ", ".join(os.path.basename(u) for u in data["unread"])])
        ws.append(["Reference codes nothing uses", data["unused_codes"], f"of {data['codes']}"])
        if data["broken_live"] is not None:
            ws.append(["Broken references in data tests run", data["broken_live"], f"{data['broken_dormant']} more in data no test runs"])
        if data.get("in_no_suite"):
            n = data["in_no_suite"]
            ws.append(["Distinct scenarios no suite runs", n["count"], f"of {n['of']}; classes: " + ", ".join(n["classes"])])
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 90
    ws.column_dimensions["C"].width = 70


def generate_excel(results: list[RuleResult], output_dir: str, total_files: int = 0, data=None,
                   products=None, states=None, suite_reach=None) -> str:
    """Generate an Excel report: a Verdict sheet first, then the summary and one sheet per rule."""
    if Workbook is None:
        print("  Warning: openpyxl not installed, skipping Excel output.", file=sys.stderr)
        return ""

    wb = Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    error_fill = PatternFill(start_color="FF6B6B", end_color="FF6B6B", fill_type="solid")

    # Summary sheet
    ws_summary = wb.active
    ws_summary.title = "Summary"
    summary_headers = ["Rule ID", "Description", "Category", "Items Found", "Status"]
    for col, header in enumerate(summary_headers, 1):
        cell = ws_summary.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill

    existing_names = {"Summary"}

    for i, result in enumerate(results):
        # Summary row
        if result.error:
            items = "ERROR"
            status = result.error[:50]
        elif result.rows:
            items = len(result.rows)
            status = "Issues found" if items > 0 else "OK"
        elif result.sections:
            items = sum(len(s.items) + sum(len(ss.items) for ss in s.subsections) for s in result.sections)
            status = "Issues found" if items > 0 else "OK"
        else:
            items = 0
            status = "OK"

        row_num = i + 2
        ws_summary.cell(row=row_num, column=1, value=result.rule_id)
        ws_summary.cell(row=row_num, column=2, value=result.description)
        ws_summary.cell(row=row_num, column=3, value=result.category)
        ws_summary.cell(row=row_num, column=4, value=items)
        cell = ws_summary.cell(row=row_num, column=5, value=status)
        if result.error:
            cell.fill = error_fill

        # Skip detail sheet if no content (no rows, no sections, no error)
        has_content = result.error or result.rows or result.sections
        if not has_content:
            continue

        # Detail sheet
        sheet_name = _safe_sheet_name(result.rule_id, result.description, existing_names)
        existing_names.add(sheet_name)
        ws = wb.create_sheet(title=sheet_name)

        if result.error:
            ws.cell(row=1, column=1, value=f"Rule {result.rule_id} failed:")
            ws.cell(row=2, column=1, value=result.error)
            continue

        next_row = 1
        if result.headers and result.rows:
            # Flat tabular output
            for col, header in enumerate(result.headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
            for row_idx, row_data in enumerate(result.rows, 2):
                for col, val in enumerate(row_data, 1):
                    ws.cell(row=row_idx, column=col, value=val)
            next_row = len(result.rows) + 3  # blank row after table

        if result.sections:
            # Hierarchical output — append after table (or write standalone)
            _write_sections_to_sheet(ws, result.sections, header_font, header_fill,
                                     start_row=next_row)

        # Auto-width columns
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = min(max_len + 2, 120)

    # Auto-width summary columns
    for col in ws_summary.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws_summary.column_dimensions[col_letter].width = min(max_len + 2, 120)

    if products:
        from eir_products import excel_rows
        ws = wb.create_sheet(title="Product coverage")
        for col, header in enumerate(["Line", "Coverage", "Status", "Terms set", "Terms", "Selected by",
                                      "Term options set"], 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
        for r, values in enumerate(excel_rows(products), 2):
            for col, value in enumerate(values, 1):
                ws.cell(row=r, column=col, value=value)
        for letter, width in zip("ABCDEFG", (22, 60, 20, 10, 60, 80, 80)):
            ws.column_dimensions[letter].width = width
        ws.auto_filter.ref = ws.dimensions

    if suite_reach:
        from eir_cover import suite_breadth_rows
        ws = wb.create_sheet(title="Suites")
        heads = ["Suite", "Scenarios", "Test methods", "Share", "Coverages", "Share", "Line/jurisdictions", "Share"]
        for col, header in enumerate(heads, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
        for r, values in enumerate(suite_breadth_rows(suite_reach), 2):
            for col, value in enumerate(values, 1):
                cell = ws.cell(row=r, column=col, value=value)
                if col in (4, 6, 8):
                    cell.number_format = "0%"
        ws.column_dimensions["A"].width = 40
        ws.auto_filter.ref = ws.dimensions

    if states:
        from eir_states import excel_rows as state_rows
        ws = wb.create_sheet(title="States")
        for col, header in enumerate(["Line", "State", "Scenarios"], 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
        for r, values in enumerate(state_rows(states), 2):
            for col, value in enumerate(values, 1):
                ws.cell(row=r, column=col, value=value)
        ws.auto_filter.ref = ws.dimensions

    # Save
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"HealthCheck_{timestamp}.xlsx"
    filepath = os.path.join(output_dir, filename)
    _verdict_sheet(wb, results, total_files, data)  # first sheet, created last so the summary keeps wb.active
    wb.save(filepath)
    return filepath


def _write_sections_to_sheet(ws, sections: list[Section], header_font, header_fill,
                             start_row: int = 1):
    """Write hierarchical sections to an Excel sheet."""
    row = start_row
    section_font = Font(bold=True, size=12)
    subsection_font = Font(bold=True, size=11)

    for section in sections:
        # Section title
        cell = ws.cell(row=row, column=1, value=section.title)
        cell.font = section_font
        row += 1

        # Section table (if present)
        if section.headers and section.rows:
            for col, header in enumerate(section.headers, 1):
                cell = ws.cell(row=row, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
            row += 1
            for row_data in section.rows:
                for col, val in enumerate(row_data, 1):
                    ws.cell(row=row, column=col, value=val)
                row += 1

        # Section items
        for item in section.items:
            ws.cell(row=row, column=2, value=item)
            row += 1

        # Subsections
        for sub in section.subsections:
            cell = ws.cell(row=row, column=2, value=sub.title)
            cell.font = subsection_font
            row += 1
            for item in sub.items:
                ws.cell(row=row, column=3, value=item)
                row += 1

        row += 1  # blank row between sections


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def generate_markdown(results: list[RuleResult], output_dir: str) -> str:
    """Generate a Markdown report."""
    lines = ["# CenterTest Health Check Report", ""]
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    blockers, not_checked, dormant = trust_blockers(results)
    lines.append("## Can these tests be trusted?")
    lines.append("")
    if blockers:
        for b in blockers:
            lines.append(f"- **{b['count']} × {b['title']}** ({b['rule_id']}): {b['consequence']}")
            for x in b["samples"]:
                lines.append(f"  - `{x}`")
    else:
        lines.append("No trust blockers.")
    if dormant:
        lines.append(f"\nNot blockers: {dormant} data findings in workbooks no test reads or in disabled rows.")
    if not_checked:
        lines.append(f"\nNot checked in this run: {', '.join(not_checked)}.")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Rule | Description | Items | Status |")
    lines.append("|------|-------------|-------|--------|")

    for result in results:
        if result.error:
            items = "ERROR"
            status = result.error[:40]
        elif result.rows:
            items = str(len(result.rows))
            status = "Issues" if result.rows else "OK"
        elif result.sections:
            items = str(sum(len(s.items) + sum(len(ss.items) for ss in s.subsections) for s in result.sections))
            status = "Issues" if int(items) > 0 else "OK"
        else:
            items = "0"
            status = "OK"
        lines.append(f"| {result.rule_id} | {result.description} | {items} | {status} |")

    lines.append("")

    # Detail sections
    for result in results:
        lines.append(f"## Rule {result.rule_id}: {result.description}")
        lines.append("")

        if result.error:
            lines.append(f"**ERROR:** {result.error}")
            lines.append("")
            continue

        if result.headers and result.rows:
            lines.append("| " + " | ".join(str(h) for h in result.headers) + " |")
            lines.append("| " + " | ".join("---" for _ in result.headers) + " |")
            for row in result.rows:
                lines.append("| " + " | ".join(str(v) for v in row) + " |")
            lines.append("")

        if result.sections:
            for section in result.sections:
                lines.append(f"### {section.title}")
                lines.append("")
                if section.headers and section.rows:
                    lines.append("| " + " | ".join(str(h) for h in section.headers) + " |")
                    lines.append("| " + " | ".join("---" for _ in section.headers) + " |")
                    for row in section.rows:
                        lines.append("| " + " | ".join(str(v) for v in row) + " |")
                    lines.append("")
                for item in section.items:
                    lines.append(f"- {item}")
                for sub in section.subsections:
                    lines.append(f"#### {sub.title}")
                    for item in sub.items:
                        lines.append(f"  - {item}")
                lines.append("")
        else:
            lines.append("No issues found.")
            lines.append("")

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"HealthCheck_{timestamp}.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return filepath


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def _count_items(result: RuleResult) -> int:
    """Count total items in a RuleResult."""
    if result.error:
        return 0
    section_count = sum(len(s.items) + sum(len(ss.items) for ss in s.subsections) for s in result.sections)
    # If rule has both rows (summary table) and sections (detail findings),
    # count only the sections — the rows are informational summaries, not issues
    if result.sections and section_count > 0:
        return section_count
    return len(result.rows)


# ---------------------------------------------------------------------------
# Trust blockers
# ---------------------------------------------------------------------------

# Findings that mean a test can pass while the application is broken, or cannot run its data
# at all. Any of them makes the suite untrustworthy however clean the rest is, so they are
# listed first and cap the score below "Healthy". Rules whose findings are style or risk
# (complexity, naming, 15017 heuristics) are deliberately not here.
TRUST_RULES = {
    "15018": ("Checks that can never fail",
              "the result of .equals() is thrown away, so the verification passes whatever the app shows"),
    "15005": ("Failures swallowed",
              "an empty catch block hides the exception, so the step reports success"),
    "9010": ("Tests that check nothing",
             "the test opens screens but nothing it runs asserts, so it passes whenever the screens open"),
    "9003": ("Tests that read data they never load",
             "the test reads the scenario's data row but has no @DataDriven, so the run has no data"),
    "14005": ("Suite entries that run nothing",
              "CenterTest reports the entry as a failed scenario, so the suite does not run what it lists"),
    "14002": ("Datasources that do not exist",
              "the @DataDriven workbook is missing, so the test cannot load its data"),
    "14003": ("Test data codes that do not exist",
              "a row references a code no sheet in its scope has, so that scenario fails on load"),
    "14004": ("Related test data rows that do not exist",
              "an @-relationship points at a DC row or file that is not there"),
}

# A blocker caps the score here: one notch below "Healthy" (80) and "Needs Attention" (60).
TRUST_SCORE_CAP = 59


def is_dormant(headers: list, row: list) -> bool:
    """A data finding no test runs (its workbook is read by no test, or its row is disabled)."""
    if "Runs in" not in headers:
        return False
    i = headers.index("Runs in")
    return i < len(row) and str(row[i]).startswith("not run")


def _finding_label(headers: list, row: list) -> str:
    """One readable line for a finding row, from whichever columns the rule has."""
    cell = {str(h): row[i] for i, h in enumerate(headers) if i < len(row)}
    if "File" in cell:
        where = os.path.basename(str(cell["File"]))
        row_no = cell.get("Row")
        if row_no not in (None, "", "-"):
            where += f" row {row_no}"
        col, code = cell.get("Column", ""), cell.get("Code", "")
        what = f"{col} '{code}'" if code not in (None, "", "-") else str(col or cell.get("Issue", ""))
        runs = cell.get("Runs in")
        return f"{where}: {what}" + (f" (in {runs})" if runs and not str(runs).startswith("not run") else "")
    if "Suite" in cell and "Entry" in cell:
        return f"{cell['Suite']}: '{cell['Entry']}'" + (f" ({cell['Location']})" if cell.get("Location") else "")
    label = ".".join(str(cell[k]) for k in ("Class", "Method") if cell.get(k))
    if cell.get("Location"):
        label += f" ({cell['Location']})"
    detail = cell.get("Line") or cell.get("Datasource Path") or ""
    return f"{label}: {detail}" if detail else label


def trust_blockers(results: list[RuleResult], sample_size: int = 5) -> tuple[list[dict], list[str], int]:
    """(blockers, not_checked, dormant) for the trust rules.

    blockers: [{rule_id, title, consequence, count, samples}] for trust rules with findings;
    not_checked: trust rule ids that were not part of this run (or errored), so the report
    never presents an unchecked suite as trustworthy;
    dormant: data findings no test runs (workbook read by no test, or row disabled), listed
    in their rule but not blockers.
    """
    by_id = {r.rule_id: r for r in results}
    blockers, not_checked, dormant_only = [], [], []
    for rule_id, (title, consequence) in TRUST_RULES.items():
        r = by_id.get(rule_id)
        if r is None or r.error:
            not_checked.append(rule_id)
            continue
        live = [row for row in r.rows if not is_dormant(r.headers, row)]
        count = len(live) if r.rows else _count_items(r)
        dormant = len(r.rows) - len(live)
        if count:
            samples = [_finding_label(r.headers, row) for row in live[:sample_size]]
            li = r.headers.index("Location") if "Location" in r.headers else None
            locations = [str(row[li]) if li is not None and li < len(row) else "" for row in live[:sample_size]]
            blockers.append({"rule_id": rule_id, "title": title, "consequence": consequence,
                             "count": count, "samples": samples, "locations": locations, "dormant": dormant})
        elif dormant:
            dormant_only.append({"rule_id": rule_id, "title": title, "dormant": dormant})
    dormant = sum(b["dormant"] for b in blockers) + sum(d["dormant"] for d in dormant_only)
    return blockers, not_checked, dormant


def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# Severity of each category for the health score. Informational categories are not scored.
#   - Low (ClassNames, Methods): suggestions, nice-to-have
#   - Medium (Inheritance, Selenium, Complexity, CenterTest): should fix
#   - High (Quality, Security): must fix
_SEVERITY = {
    "Statistics": None,
    "ClassNames": "low",
    "Methods":    "low",
    "Inheritance": "medium",
    "Selenium":   "medium",
    "Complexity": "medium",
    "CenterTest": "medium",
    "Quality":    "high",
    "Security":   "high",
}
_WEIGHT = {"low": 1, "medium": 2, "high": 3}

# Rules whose consequence in a test suite differs from their category's: an index or null error
# in a test fails it loudly (with an unhelpful message: assert the precondition first), and an
# unused variable is clutter. A busy-wait that can hang (15017) keeps its category's "high".
_RULE_SEVERITY = {"15001": "medium", "15002": "medium", "15006": "low"}


def severity_of(result: RuleResult):
    """'high' / 'medium' / 'low', or None for informational rules."""
    return _RULE_SEVERITY.get(result.rule_id, _SEVERITY.get(result.category, "medium"))


def health_score(results: list[RuleResult], total_files: int) -> int:
    """The health score (0-100): severity-weighted rule credit, capped at TRUST_SCORE_CAP when a
    trust blocker exists. The dashboard and the trend both use this, so they always agree."""
    earned = possible = 0.0
    for r in results:
        severity = severity_of(r)
        if severity is None or r.error:
            if severity is not None:
                possible += _WEIGHT[severity]
            continue
        weight = _WEIGHT[severity]
        possible += weight
        count = _count_items(r)
        # Partial credit: few findings in a large codebase is still mostly healthy.
        earned += weight if count == 0 else weight * max(0, 1.0 - min(count / max(total_files, 1), 1.0))
    score = round(earned / possible * 100) if possible > 0 else 0
    if trust_blockers(results)[0]:
        score = min(score, TRUST_SCORE_CAP)
    return score


def _ide_link(repo_root: str, location: str, text: str) -> str:
    """text as a link that opens path:line in IntelliJ (idea:// scheme); plain text without a location."""
    if not location or ":" not in location or not repo_root:
        return _html_escape(text)
    rel, _, line = location.rpartition(":")
    if not line.isdigit():
        return _html_escape(text)
    from urllib.parse import quote
    url = f"idea://open?file={quote(os.path.join(repo_root, rel))}&line={line}"
    return f'<a class="ide" href="{_html_escape(url)}" title="Open in IntelliJ">{_html_escape(text)}</a>'


_TIERS = (("trust", "Trust blockers", "tests that can pass while the app is broken, or cannot run"),
          ("high", "Must fix", "quality and security defects"),
          ("medium", "Should fix", "framework compliance, complexity, failures with unhelpful messages"),
          ("low", "Suggestions", "naming, readability, clutter"))


def fix_order(results: list[RuleResult]) -> list[dict]:
    """Findings grouped by what they cost, most urgent first: [{tier, title, why, count, rules}].
    Trust rules count only findings a test runs (dormant data findings are cleanup);
    informational categories are left out."""
    blockers, _nc, _dormant = trust_blockers(results)
    live = {b["rule_id"]: b["count"] for b in blockers}
    tiers = {key: [] for key, _t, _w in _TIERS}
    for r in results:
        if r.error:
            continue
        if r.rule_id in TRUST_RULES:
            if live.get(r.rule_id):
                tiers["trust"].append((r.rule_id, r.description, live[r.rule_id]))
            continue
        severity = severity_of(r)
        count = _count_items(r)
        if severity and count:
            tiers[severity].append((r.rule_id, r.description, count))
    out = []
    for key, title, why in _TIERS:
        rules = sorted(tiers[key], key=lambda x: (-x[2], x[0]))
        out.append({"tier": key, "title": title, "why": why, "count": sum(c for _i, _d, c in rules), "rules": rules})
    return out


def _fix_order_html(results: list[RuleResult]) -> str:
    """'What to fix first': the same findings, ordered by cost rather than by count."""
    tiers = fix_order(results)
    top = max((t["count"] for t in tiers), default=1) or 1
    rows = []
    for t in tiers:
        rules = ", ".join(f'<a href="#rule-{r}" onclick="navigateTo(\'rule-{r}\');return false">{_html_escape(d)}</a> {c}'
                          for r, d, c in t["rules"][:4])
        more = f" and {len(t['rules']) - 4} more rules" if len(t["rules"]) > 4 else ""
        rows.append(
            f'<div class="tier tier-{t["tier"]}"><div class="tier-head"><span class="tier-title">{t["title"]}</span>'
            f'<span class="tier-count">{t["count"]}</span></div>'
            f'<div class="cat-bar-bg"><div class="tier-fill" style="width:{t["count"] / top * 100:.0f}%"></div></div>'
            f'<div class="tier-why">{_html_escape(t["why"])}{": " + rules + more if rules else " — none"}</div></div>')
    return ('  <div class="categories">\n    <h2>What to fix first</h2>\n'
            '    <p class="tier-note">The same findings as below, grouped by what they cost rather than by how many there are.</p>\n'
            + "\n".join(rows) + "\n  </div>\n")


def _trust_panel_html(blockers: list[dict], not_checked: list[str], dormant: int = 0,
                      repo_root: str = "") -> str:
    """The 'Can these tests be trusted?' panel shown under the score."""
    unchecked = ""
    if dormant:
        unchecked += (f'    <div class="trust-dormant">Not blockers: {dormant} data finding{"s" if dormant != 1 else ""} '
                      'in workbooks no test reads or in disabled rows. They are listed under rules 14003/14004 '
                      'as cleanup.</div>\n')
    if not_checked:
        unchecked = (f'    <div class="trust-unchecked">Not checked in this run: rules {", ".join(not_checked)}. '
                     'Run the CenterTestFull ruleset for a complete verdict.</div>\n')
    if not blockers:
        return ('  <div class="trust ok">\n    <h2>Can these tests be trusted?</h2>\n'
                '    <div class="trust-sub">No trust blockers: every check can fail, no failure is swallowed, '
                'and all test data resolves.</div>\n' + unchecked + '  </div>\n')
    total = sum(b["count"] for b in blockers)
    out = ['  <div class="trust">', '    <h2>Can these tests be trusted? Not yet.</h2>',
           f'    <div class="trust-sub">{total} finding{"s" if total != 1 else ""} below mean tests can pass while '
           'the application is broken, or cannot run at all. Fix these before anything else; '
           'until then the score is capped below Healthy.</div>']
    for b in blockers:
        more = b["count"] - len(b["samples"])
        locs = b.get("locations") or [""] * len(b["samples"])
        items = "".join(f"<li>{_ide_link(repo_root, loc, x)}</li>" for x, loc in zip(b["samples"], locs))
        if more > 0:
            items += f"<li>… and {more} more</li>"
        out.append(
            f'    <div class="blocker" onclick="navigateTo(\'rule-{b["rule_id"]}\')">'
            f'<div class="blocker-count">{b["count"]}</div>'
            f'<div><div class="blocker-title">{_html_escape(b["title"])} <span class="badge-cat">{b["rule_id"]}</span></div>'
            f'<div class="blocker-why">{_html_escape(b["consequence"])}</div></div>'
            f'<ul>{items}</ul></div>')
    out.append(unchecked.rstrip("\n")) if unchecked else None
    out.append('  </div>')
    return "\n".join(out) + "\n"


def _screens_panel_html(coverage) -> str:
    """'Screens the suite opens': per application, wizards opened and not, and the screen count."""
    if coverage is None:
        return ""
    if not coverage:
        return ('  <div class="screens"><h2>Screens the suite opens</h2><p class="screens-note">Not measured: '
                'the generated project\'s cssids/ folder was not found. Pass --cssids &lt;generated src/main/resources&gt;.</p></div>\n')
    cards = []
    for c in coverage:
        total_w = len(c["wizards"]) + len(c["unused_wizards"])
        pct = (len(c["wizards"]) / total_w * 100) if total_w else 0
        opened = "".join(f'<span class="chip on" title="{_html_escape(", ".join(users[:8]))}">{_html_escape(w)}</span>'
                         for w, users in c["wizards"])
        shown = 12 if len(c["unused_wizards"]) > 15 else 15  # never fold away just a few
        missing = "".join(f'<span class="chip">{_html_escape(w)}</span>' for w in c["unused_wizards"][:shown])
        if len(c["unused_wizards"]) > shown:
            rest = "".join(f'<span class="chip">{_html_escape(w)}</span>' for w in c["unused_wizards"][12:])
            missing += (f'<details class="more"><summary>+{len(c["unused_wizards"]) - 12} more</summary>'
                        f'<div class="chips">{rest}</div></details>')
        cards.append(
            f'<div class="app-card"><div class="app-name">{_html_escape(c["name"])}</div>'
            f'<div class="app-big">{len(c["wizards"])}<small> of {total_w} wizards</small></div>'
            f'<div class="app-bar"><i style="width:{pct:.0f}%"></i></div>'
            f'<div class="app-sub">{c["used"]} of {c["screens"]} screens</div>'
            + (f'<div class="chips-label">Opened</div><div class="chips">{opened}</div>' if opened else "")
            + (f'<div class="chips-label">No test opens</div><div class="chips">{missing}</div>' if missing else "")
            + "</div>")
    return ('  <div class="screens"><h2>Screens the suite opens</h2>'
            '<p class="screens-note">Wizards are the business transactions. Counted from the page objects your own code '
            'uses; screens opened only inside framework steps are not seen, so these are floors.</p>'
            f'<div class="app-grid">{"".join(cards)}</div></div>\n')


def _products_panel_html(lines) -> str:
    """'Product coverages the test data names': per line of business, from the generated product model."""
    if not lines:
        return ""
    cards = []
    for l in sorted(lines, key=lambda l: (-len(l["named"]) / max(l["coverages"], 1), l["line"])):
        pct = len(l["named"]) / l["coverages"] * 100 if l["coverages"] else 0
        # the shorter list says more: what a thin line covers, or what a well-covered line still misses
        if len(l["named"]) <= len(l["missing"]) or not l["missing"]:
            label = "Selected by a scenario"
            from eir_products import _tests, options_text
            chips = [f'<span class="chip on" title="{_html_escape(c["code"] or "")}: terms set '
                     f'{len(c["terms_set"])}/{c["terms"]}. Selected by: {_html_escape(_tests(c)) or "–"}'
                     f'{". Options: " + _html_escape(options_text(c)) if c.get("options") else ""}">'
                     f'{_html_escape(c["name"])}</span>' for c in l["named"]]
        else:
            label = "No scenario selects"
            chips = [f'<span class="chip">{_html_escape(n)}</span>' for n in l["missing"]]
        named = "".join(chips[:10])
        if len(chips) > 10:
            rest = "".join(chips[10:60]) + (f'<span class="chip">+{len(chips) - 60} in Excel</span>' if len(chips) > 60 else "")
            named += (f'<details class="more"><summary>+{len(chips) - 10} more</summary>'
                      f'<div class="chips">{rest}</div></details>')
        java = "".join(f'<span class="chip">{_html_escape(n)}</span>' for n in l["java"][:12])
        outside = "".join(f'<span class="chip">{_html_escape(n)}</span>' for n in (l.get("outside_suites") or [])[:12])
        unused = "".join(f'<span class="chip">{_html_escape(n)}</span>' for n in l.get("unused", [])[:12])
        if len(l.get("unused", [])) > 12:
            unused += f'<span class="chip">+{len(l["unused"]) - 12} in Excel</span>'
        terms = f'{l["terms_set"]} of {l["terms"]} terms of those coverages set' if l["terms"] else "no terms on those coverages"
        if l.get("option_terms"):
            terms += (f'; {l["option_terms"]} option terms set, {l["options_chosen"]} of their '
                      f'{l["options_total"]} options used')
        off = "".join(f'<span class="chip warn" title="Options: {_html_escape(", ".join(n["options"]))}">'
                      f'{_html_escape(n["coverage"])} / {_html_escape(n["term"])} = {_html_escape(n["value"])}</span>'
                      for n in l.get("not_offered", []))
        cards.append(
            f'<div class="app-card"><div class="app-name">{_html_escape(l["line"])}</div>'
            f'<div class="app-big">{len(l["named"])}<small> of {l["coverages"]} coverages</small></div>'
            f'<div class="app-bar"><i style="width:{pct:.0f}%"></i></div>'
            f'<div class="app-sub">{terms}</div>'
            + (f'<div class="chips-label">{label}</div><div class="chips">{named}</div>' if named else "")
            + (f'<div class="chips-label">Term values that are not an option in the product model</div><div class="chips">{off}</div>' if off else "")
            + (f'<div class="chips-label">Selected only by scenarios no suite runs</div><div class="chips">{outside}</div>' if outside else "")
            + (f'<details class="more"><summary>{len(l.get("unused", []))} in data rows no scenario reaches</summary>'
               f'<div class="chips">{unused}</div></details>' if unused else "")
            + (f'<details class="more"><summary>{len(l["java"])} named only in code: check</summary>'
               f'<div class="chips">{java}</div></details>' if java else "")
            + "</div>")
    return ('  <div class="screens"><h2>Product coverages the scenarios select</h2>'
            '<p class="screens-note">From the generated product model, per line of business: a coverage counts when a '
            'row an enabled scenario reaches (its DataCombination row and what it references) names it, by name or code. '
            'Names are counted once per line, and a name several lines share counts for each. Every coverage is in the '
            'Excel sheet "Product coverage".</p>'
            f'<div class="app-grid">{"".join(cards)}</div></div>\n')


def _suites_panel_html(rows) -> str:
    """'How much of the full run each suite reaches': flows (test methods), product coverages and
    line/jurisdiction pairs as a share of what every scenario together reaches."""
    if not rows or len(rows) < 2:
        return ""
    full = rows[0]
    ranked = sorted(rows[1:], key=lambda r: (-r["test"], -r["coverage"], r["suite"].lower()))
    running = [r for r in ranked if r["scenarios"]]
    idle = [r["suite"] for r in ranked if not r["scenarios"]]

    def cell(r, k):
        if not full[k]:
            return '<td class="num">–</td>'
        share = r[k] * 100 // full[k]  # floored as the terminal does: 216 of 217 is 99%, never 100%
        return (f'<td class="num" title="{r[k]} of {full[k]}"><span class="share"><i style="width:{share}%"></i>'
                f'</span>{share}%</td>')

    body = "".join(f'<tr><td>{_html_escape(r["suite"])}</td><td class="num">{r["scenarios"]}</td>'
                   f'{cell(r, "test")}{cell(r, "coverage")}{cell(r, "jurisdiction")}</tr>' for r in running)
    return ('  <div class="screens"><h2>How much of the full run each suite reaches</h2>'
            f'<p class="screens-note">All {full["scenarios"]} scenarios that run reach {full["test"]} test methods (flows), '
            f'{full["coverage"]} product coverages and {full["jurisdiction"]} line/jurisdiction pairs. Each suite as CenterTest '
            'resolves it, as a share of those. <code>--cover SUITE</code> names what a suite misses and the fewest '
            'scenarios to add.</p>'
            '<div class="table-wrap"><table class="suite-reach"><thead><tr><th>Suite</th><th class="num">Scenarios</th>'
            '<th class="num">Flows</th><th class="num">Coverages</th><th class="num">Jurisdictions</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>'
            + (f'<p class="screens-note">Run nothing ({len(idle)}): {_html_escape(", ".join(idle))}</p>' if idle else "")
            + '</div>\n')


def _states_panel_html(lines) -> str:
    """'States the scenarios run in': per line, the states its scenarios' data names, and the states the
    suite uses on other lines but never on this one."""
    if not lines:
        return ""
    every = set().union(*(l["states"] for l in lines))
    cards = []
    for l in lines:
        chips = "".join(f'<span class="chip on" title="{n} scenario{"s" if n != 1 else ""}">{_html_escape(s)}</span>'
                        for s, n in l["states"].items())
        gap = "".join(f'<span class="chip">{_html_escape(s)}</span>' for s in l["elsewhere"])
        cards.append(
            f'<div class="app-card"><div class="app-name">{_html_escape(l["line"])}</div>'
            f'<div class="app-big">{len(l["states"])}<small> of {len(every)} jurisdictions the suite uses</small></div>'
            f'<div class="app-bar"><i style="width:{len(l["states"]) / len(every) * 100:.0f}%"></i></div>'
            f'<div class="chips">{chips}</div>'
            + (f'<details class="more"><summary>{len(l["elsewhere"])} used on other lines, never here</summary>'
               f'<div class="chips">{gap}</div></details>' if gap else "")
            + "</div>")
    return ('  <div class="screens"><h2>Jurisdictions the scenarios run in</h2>'
            '<p class="screens-note">Per line of business (the DataCombination workbook\'s prefix): the states or provinces a row '
            'an enabled scenario reaches names in a State, Jurisdiction or Governing Law column, by the Jurisdiction '
            'typelist\'s code or name. Addresses count too. Hover one for its scenarios; every line and jurisdiction is '
            'in the Excel sheet "States".</p>'
            f'<div class="app-grid">{"".join(cards)}</div></div>\n')


def _data_panel_html(d) -> str:
    """'Test data': scenarios a full run executes, unread workbooks, unused codes, broken references."""
    if not d:
        return ""
    unread = ", ".join(os.path.basename(u) for u in d["unread"][:6]) + (" …" if len(d["unread"]) > 6 else "")
    tiles = [
        (f'{d["scenarios"]}', "scenario runs in a full run",
         f'{d["data_driven"]} data-driven of {d["test_classes"]} test classes; Multiplier repeats included; '
         f'{d["disabled"]} rows disabled'),
        (f'{len(d["unread"])}<small> of {d["dc_files"]}</small>', "DC workbooks no test reads", unread or "every workbook is read"),
        (f'{d["unused_codes"]}<small> of {d["codes"]}</small>', "reference codes nothing uses",
         "xlsx-cleanup-unused lists them"),
        (f'{d["broken_live"]}' if d["broken_live"] is not None else "–", "broken references in data tests run",
         f'{d["broken_dormant"]} more in data no test runs' if d["broken_live"] is not None
         else "not checked: rules 14003/14004 were not part of this run"),
    ]
    if d.get("in_no_suite"):
        n = d["in_no_suite"]
        classes = ", ".join(n["classes"][:5]) + (" …" if len(n["classes"]) > 5 else "")
        tiles.append((f'{n["count"]}<small> of {n["of"]}</small>', "distinct scenarios no suite runs",
                      f"Classes outside every suite: {classes}" if classes else "every class is in a suite"))
    cells = "".join(f'<div class="data-tile"><div class="data-big">{big}</div><div class="data-label">{_html_escape(label)}</div>'
                    f'<div class="data-sub">{_html_escape(sub)}</div></div>' for big, label, sub in tiles)
    return f'  <div class="data"><h2>Test data</h2><div class="data-grid">{cells}</div></div>\n'


def generate_html(results: list[RuleResult], output_dir: str,
                  project_name: str = "", total_files: int = 0,
                  elapsed: float = 0, excel_filename: str = "",
                  suppressed_count: int = 0, screens=None, data=None, products=None, since=None,
                  states=None, suite_reach=None) -> str:
    """Generate a dashboard-style HTML health check report. screens: eir_screens.screen_coverage()
    output, [] when the generated cssids were not found, None when not measured."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_issues = 0
    rules_passed = 0
    rules_failed = 0
    rules_error = 0
    categories: dict[str, dict] = {}

    for r in results:
        count = _count_items(r)
        total_issues += count
        if r.error:
            rules_error += 1
        elif count > 0:
            rules_failed += 1
        else:
            rules_passed += 1

        cat = r.category
        if cat not in categories:
            categories[cat] = {"passed": 0, "failed": 0, "issues": 0}
        if r.error or count > 0:
            categories[cat]["failed"] += 1
        else:
            categories[cat]["passed"] += 1
        categories[cat]["issues"] += count

    total_rules = len(results)
    score = health_score(results, total_files)
    blockers, trust_not_checked, trust_dormant = trust_blockers(results)

    # Determine score color
    if blockers:
        score_color = "#ef4444"  # red
        score_label = "At risk"
    elif score >= 80:
        score_color = "#22c55e"  # green
        score_label = "Healthy"
    elif score >= 60:
        score_color = "#f59e0b"  # amber
        score_label = "Needs Attention"
    else:
        score_color = "#ef4444"  # red
        score_label = "Critical"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CenterTest Health Check — {_html_escape(project_name)}</title>
<style>
  :root {{
    --bg: #0f172a; --surface: #1e293b; --surface2: #334155;
    --border: #475569; --text: #e2e8f0; --text-muted: #94a3b8;
    --accent: #3b82f6; --green: #22c55e; --amber: #f59e0b; --red: #ef4444;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
  }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}

  /* Header */
  .header {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 24px 0; border-bottom: 1px solid var(--border); margin-bottom: 32px;
  }}
  .header h1 {{ font-size: 24px; font-weight: 700; }}
  .header h1 span {{ color: var(--accent); }}
  .header-meta {{ text-align: right; color: var(--text-muted); font-size: 13px; }}

  /* Score card */
  .score-row {{
    display: grid; grid-template-columns: 200px 1fr; gap: 24px; margin-bottom: 32px;
  }}
  .score-card {{
    background: var(--surface); border-radius: 16px; padding: 32px;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    border: 2px solid {score_color};
  }}
  .score-number {{ font-size: 56px; font-weight: 800; color: {score_color}; line-height: 1; }}
  .score-label {{ font-size: 14px; color: var(--text-muted); margin-top: 4px; }}
  .score-badge {{
    margin-top: 12px; padding: 4px 16px; border-radius: 20px; font-size: 13px;
    font-weight: 600; background: {score_color}22; color: {score_color};
  }}

  /* Stat cards */
  .stats-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px;
  }}
  .stat-card {{
    background: var(--surface); border-radius: 12px; padding: 20px;
    border: 1px solid var(--border);
  }}
  .stat-value {{ font-size: 28px; font-weight: 700; }}
  .stat-label {{ font-size: 12px; color: var(--text-muted); text-transform: uppercase;
    letter-spacing: 0.05em; margin-top: 4px; }}
  .stat-green {{ color: var(--green); }}
  .stat-red {{ color: var(--red); }}
  .stat-amber {{ color: var(--amber); }}
  .stat-blue {{ color: var(--accent); }}

  /* Category bars */
  .trust {{ margin: 28px 0 0; background: var(--surface); border: 1px solid var(--border);
    border-left: 4px solid var(--red); border-radius: 12px; padding: 18px 22px; }}
  .trust.ok {{ border-left-color: var(--green); }}
  .trust h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 4px; }}
  .trust .trust-sub {{ color: var(--text-muted); font-size: 14px; margin-bottom: 12px; }}
  .blocker {{ display: grid; grid-template-columns: 56px 1fr; gap: 4px 14px; padding: 12px 0;
    border-top: 1px solid var(--surface2); cursor: pointer; }}
  .blocker-count {{ font-size: 28px; font-weight: 800; color: var(--red); line-height: 1;
    font-variant-numeric: tabular-nums; }}
  .blocker-title {{ font-weight: 600; }}
  .blocker-why {{ color: var(--text-muted); font-size: 14px; }}
  .blocker ul {{ grid-column: 2; margin: 4px 0 0 18px; font-size: 13px; color: var(--text);
    font-family: ui-monospace, Menlo, monospace; overflow-wrap: anywhere; }}
  a.ide {{ color: inherit; text-decoration: underline; text-decoration-color: var(--border); }}
  a.ide:hover {{ text-decoration-color: var(--accent); }}
  .data {{ margin: 28px 0 0; }}
  .data h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 12px; }}
  .data-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }}
  .data-tile {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 18px; min-width: 0; }}
  .data-big {{ font-size: 30px; font-weight: 800; line-height: 1.1; font-variant-numeric: tabular-nums; }}
  .data-big small {{ font-size: 14px; font-weight: 500; color: var(--text-muted); }}
  .data-label {{ font-weight: 600; font-size: 14px; margin-top: 2px; }}
  .data-sub {{ color: var(--text-muted); font-size: 13px; overflow-wrap: anywhere; }}
  ul.since {{ margin: 6px 0 12px 18px; padding: 0; font-size: 13px; color: var(--text-muted); }}
  ul.since code {{ font-size: 12px; overflow-wrap: anywhere; }}
  .screens {{ margin: 28px 0 0; }}
  .screens h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 4px; }}
  .screens-note {{ color: var(--text-muted); font-size: 14px; margin-bottom: 12px; }}
  .app-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; align-items: start; }}
  .app-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; min-width: 0; }}
  .app-name {{ font-weight: 600; }}
  .app-big {{ font-size: 32px; font-weight: 800; line-height: 1.1; font-variant-numeric: tabular-nums; }}
  .app-big small {{ font-size: 14px; font-weight: 500; color: var(--text-muted); }}
  .app-bar {{ height: 6px; border-radius: 4px; background: var(--surface2); margin: 8px 0 6px; overflow: hidden; }}
  .app-bar i {{ display: block; height: 100%; background: var(--accent); }}
  .app-sub {{ color: var(--text-muted); font-size: 13px; }}
  .chips-label {{ font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; margin: 10px 0 4px; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 4px; }}
  .chip {{ font-size: 12px; padding: 2px 8px; border-radius: 10px; border: 1px solid var(--border); color: var(--text-muted); overflow-wrap: anywhere; }}
  .chip.on {{ color: var(--text); border-color: var(--accent); }}
  .chip.warn {{ color: var(--text); border-color: var(--amber); }}
  .table-wrap {{ overflow-x: auto; }}
  table.suite-reach {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  table.suite-reach th, table.suite-reach td {{ padding: 6px 10px; border-bottom: 1px solid var(--border); text-align: left; }}
  table.suite-reach .num {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }}
  .share {{ display: inline-block; width: 70px; height: 6px; margin-right: 8px; border-radius: 3px;
            background: var(--surface2); vertical-align: middle; overflow: hidden; }}
  .share i {{ display: block; height: 100%; background: var(--accent); }}
  details.more {{ width: 100%; }}
  details.more summary {{ cursor: pointer; font-size: 12px; color: var(--accent); margin: 4px 0; }}
  .trust-dormant {{ color: var(--text-muted); font-size: 13px; margin-top: 10px; }}
  .trust-unchecked {{ color: var(--amber); font-size: 13px; margin-top: 10px; }}
  .categories {{ margin: 32px 0; }}
  .categories h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; }}
  .cat-row {{
    display: flex; align-items: center; gap: 12px; padding: 10px 0;
    border-bottom: 1px solid var(--surface2);
  }}
  .cat-name {{ width: 140px; font-weight: 500; font-size: 14px; }}
  .cat-bar-bg {{
    flex: 1; height: 24px; background: var(--surface2); border-radius: 12px;
    overflow: hidden; position: relative;
  }}
  .cat-bar-fill {{
    height: 100%; border-radius: 12px; transition: width 0.5s;
  }}
  .cat-bar-fill.green {{ background: var(--green); }}
  .cat-bar-fill.red {{ background: var(--red); }}
  .cat-bar-fill.amber {{ background: var(--amber); }}
  .cat-issues {{ width: 80px; text-align: right; font-size: 14px; color: var(--text-muted); }}
  .tier-note {{ color: var(--text-muted); font-size: 14px; margin: -8px 0 12px; }}
  .tier {{ padding: 10px 0; border-bottom: 1px solid var(--surface2); }}
  .tier-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }}
  .tier-title {{ font-weight: 600; }}
  .tier-count {{ font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }}
  .tier .cat-bar-bg {{ margin: 6px 0; height: 8px; flex: none; }}
  .tier-fill {{ height: 100%; border-radius: 4px; }}
  .tier-trust .tier-fill {{ background: var(--red); }} .tier-trust .tier-count {{ color: var(--red); }}
  .tier-high .tier-fill {{ background: var(--amber); }}
  .tier-medium .tier-fill {{ background: var(--accent); }}
  .tier-low .tier-fill {{ background: var(--text-muted); opacity: .6; }}
  .tier-why {{ color: var(--text-muted); font-size: 13px; overflow-wrap: anywhere; }}
  .tier-why a {{ color: var(--text); text-decoration: underline; text-decoration-color: var(--border); }}

  /* Rules table */
  .rules-section {{ margin: 32px 0; }}
  .rules-section h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{
    text-align: left; padding: 12px 16px; font-size: 12px; text-transform: uppercase;
    letter-spacing: 0.05em; color: var(--text-muted); border-bottom: 2px solid var(--border);
    background: var(--surface);
  }}
  td {{ padding: 12px 16px; border-bottom: 1px solid var(--surface2); font-size: 14px; }}
  tr:hover td {{ background: var(--surface); }}
  .badge {{
    display: inline-block; padding: 2px 10px; border-radius: 10px;
    font-size: 12px; font-weight: 600;
  }}
  .badge-ok {{ background: var(--green)22; color: var(--green); }}
  .badge-issues {{ background: var(--red)22; color: var(--red); }}
  .badge-error {{ background: var(--amber)22; color: var(--amber); }}
  .badge-cat {{
    background: var(--accent)18; color: var(--accent); font-size: 11px;
    padding: 2px 8px; border-radius: 8px;
  }}

  /* Detail sections */
  .detail {{ margin: 32px 0; }}
  .detail h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; }}
  .rule-detail {{
    background: var(--surface); border-radius: 12px; border: 1px solid var(--border);
    margin-bottom: 16px; overflow: hidden;
  }}
  .rule-detail-header {{
    padding: 16px 20px; display: flex; justify-content: space-between;
    align-items: center; cursor: pointer; user-select: none;
  }}
  .rule-detail-header:hover {{ background: var(--surface2); }}
  .rule-detail-title {{ font-weight: 600; }}
  .rule-detail-body {{ padding: 0 20px 16px; }}
  .detail-table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  .detail-table th {{
    text-align: left; padding: 8px 12px; font-size: 11px; background: var(--surface2);
    border-bottom: 1px solid var(--border);
  }}
  .detail-table td {{
    padding: 8px 12px; font-size: 13px; border-bottom: 1px solid var(--surface2);
    font-family: 'SF Mono', Monaco, monospace; word-break: break-all; max-width: 600px;
  }}
  .finding-list {{ list-style: none; padding: 0; }}
  .finding-list li {{
    padding: 6px 12px; font-size: 13px; border-left: 3px solid var(--accent);
    margin: 4px 0; background: var(--surface2); border-radius: 0 6px 6px 0;
    font-family: 'SF Mono', Monaco, monospace;
  }}
  .section-title {{
    font-weight: 600; font-size: 14px; margin: 12px 0 6px; color: var(--accent);
  }}
  .subsection-title {{
    font-weight: 500; font-size: 13px; margin: 8px 0 4px; color: var(--text-muted);
    padding-left: 12px;
  }}

  /* Footer */
  .footer {{
    margin-top: 48px; padding: 24px 0; border-top: 1px solid var(--border);
    color: var(--text-muted); font-size: 12px; text-align: center;
  }}
  .footer a {{ color: var(--accent); text-decoration: none; }}

  /* Toggle */
  .toggle-arrow {{ transition: transform 0.2s; font-size: 12px; color: var(--text-muted); }}
  .rule-detail.open .toggle-arrow {{ transform: rotate(90deg); }}
  .rule-detail:not(.open) .rule-detail-body {{ display: none; }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1><span>CenterTest</span> Health Check</h1>
    <div class="header-meta">
      <div>{_html_escape(project_name)}</div>
      <div>{generated_at}</div>
    </div>
  </div>

  <div class="score-row">
    <div class="score-card">
      <div class="score-number">{score}</div>
      <div class="score-label">Health Score</div>
      <div class="score-badge">{score_label}</div>
    </div>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-value stat-blue">{total_rules}</div>
        <div class="stat-label">Rules Checked</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-green">{rules_passed}</div>
        <div class="stat-label">Passed</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-red">{rules_failed}</div>
        <div class="stat-label">Rules Failed</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-amber">{total_issues}</div>
        <div class="stat-label">Total Findings</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:var(--text-muted)">{suppressed_count}</div>
        <div class="stat-label">Suppressed</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-blue">{total_files}</div>
        <div class="stat-label">Files Analyzed</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:var(--text-muted)">{elapsed:.1f}s</div>
        <div class="stat-label">Duration</div>
      </div>
    </div>
  </div>
"""

    repo_root = os.path.dirname(os.path.abspath(output_dir))
    from eir_since import panel_html as _since_panel
    html += _since_panel(since, _html_escape)
    html += _trust_panel_html(blockers, trust_not_checked, trust_dormant, repo_root)
    # what to act on before what the suite exercises: the order the skill reports in
    html += _fix_order_html(results)
    html += _data_panel_html(data)
    html += _screens_panel_html(screens)
    html += _products_panel_html(products)
    html += _states_panel_html(states)
    html += _suites_panel_html(suite_reach)

    # Rules summary table (collapsible)
    html += """  <div class="rules-section">
    <div class="rule-detail open">
      <div class="rule-detail-header" onclick="this.parentElement.classList.toggle('open')">
        <span class="rule-detail-title" style="font-size:18px">Rules Summary</span>
        <span class="toggle-arrow">&#9654;</span>
      </div>
      <div class="rule-detail-body">
    <table>
      <thead><tr><th>Rule</th><th>Category</th><th>Description</th><th>Findings</th><th>Status</th></tr></thead>
      <tbody>
"""
    for r in results:
        count = _count_items(r)
        if r.error:
            badge = '<span class="badge badge-error">ERROR</span>'
        elif count > 0:
            badge = f'<span class="badge badge-issues">{count} issue{"s" if count != 1 else ""}</span>'
        else:
            badge = '<span class="badge badge-ok">Passed</span>'
        cat_id = r.category.lower().replace(" ", "-")
        html += f"""        <tr style="cursor:pointer" onclick="navigateTo('rule-{r.rule_id}', 'cat-{cat_id}')">
          <td><strong>{r.rule_id}</strong></td>
          <td><span class="badge-cat">{_html_escape(r.category)}</span></td>
          <td>{_html_escape(r.description)}</td>
          <td>{count}</td>
          <td>{badge}</td>
        </tr>
"""
    html += "      </tbody>\n    </table>\n      </div>\n    </div>\n  </div>\n"

    # Detail sections (grouped by category, collapsible)
    html += """  <div class="detail">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="margin:0">Detailed Findings</h2>
      <div style="display:flex;gap:8px">
        <button onclick="toggleAll(true)" style="padding:6px 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;font-size:12px">Expand All</button>
        <button onclick="toggleAll(false)" style="padding:6px 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;font-size:12px">Collapse All</button>
      </div>
    </div>
"""

    # Group results by category, preserving order
    from collections import OrderedDict
    cat_results: OrderedDict[str, list] = OrderedDict()
    for r in results:
        cat_results.setdefault(r.category, []).append(r)

    for cat_name, cat_rules in cat_results.items():
        cat_issue_count = sum(_count_items(r) for r in cat_rules)
        cat_has_content = any(_count_items(r) > 0 or r.error for r in cat_rules)
        if not cat_has_content:
            continue

        # Category wrapper (collapsed by default)
        cat_open = ""
        cat_id = cat_name.lower().replace(" ", "-")
        html += f'    <div id="cat-{cat_id}" class="rule-detail{cat_open}">\n'
        html += f'      <div class="rule-detail-header" onclick="this.parentElement.classList.toggle(\'open\')">\n'
        html += f'        <span class="rule-detail-title" style="font-size:16px">{_html_escape(cat_name)}</span>\n'
        cat_rule_count = sum(1 for r in cat_rules if _count_items(r) > 0 or r.error)
        html += f'        <span><span style="margin-right:8px;color:var(--text-muted)">{cat_issue_count} finding{"s" if cat_issue_count != 1 else ""} in {cat_rule_count} rule{"s" if cat_rule_count != 1 else ""}</span><span class="toggle-arrow">&#9654;</span></span>\n'
        html += '      </div>\n'
        html += '      <div class="rule-detail-body">\n'

        # Individual rules within category
        for r in cat_rules:
            count = _count_items(r)
            if count == 0 and not r.error:
                continue

            open_class = ""  # collapsed by default
            html += f'        <div id="rule-{r.rule_id}" class="rule-detail{open_class}" style="margin-left:8px;border-color:var(--surface2)">\n'
            html += f'          <div class="rule-detail-header" onclick="this.parentElement.classList.toggle(\'open\')">\n'
            html += f'            <span class="rule-detail-title">{r.rule_id}: {_html_escape(r.description)}</span>\n'
            count_text = f"{count} finding{'s' if count != 1 else ''}" if not r.error else "ERROR"
            html += f'            <span><span style="margin-right:8px;color:var(--text-muted)">{count_text}</span><span class="toggle-arrow">&#9654;</span></span>\n'
            html += '          </div>\n'
            html += '          <div class="rule-detail-body">\n'

            if r.error:
                html += f'            <p style="color:var(--amber)">Error: {_html_escape(r.error)}</p>\n'

            # Flat table
            if r.headers and r.rows:
                html += '            <table class="detail-table"><thead><tr>'
                for h in r.headers:
                    html += f'<th>{_html_escape(h)}</th>'
                html += '</tr></thead><tbody>\n'
                loc_i = r.headers.index("Location") if "Location" in r.headers else None
                for row in r.rows[:100]:
                    html += '              <tr>'
                    for i, val in enumerate(row):
                        cell = _ide_link(repo_root, str(val), str(val)) if i == loc_i else _html_escape(val)
                        html += f'<td>{cell}</td>'
                    html += '</tr>\n'
                if len(r.rows) > 100:
                    html += f'              <tr><td colspan="{len(r.headers)}" style="color:var(--text-muted);text-align:center">... and {len(r.rows) - 100} more (see Excel)</td></tr>\n'
                html += '            </tbody></table>\n'

            # Sections
            for section in r.sections:
                html += f'            <div class="section-title">{_html_escape(section.title)}</div>\n'
                if section.headers and section.rows:
                    html += '            <table class="detail-table"><thead><tr>'
                    for h in section.headers:
                        html += f'<th>{_html_escape(h)}</th>'
                    html += '</tr></thead><tbody>\n'
                    for row in section.rows:
                        html += '              <tr>'
                        for val in row:
                            html += f'<td>{_html_escape(val)}</td>'
                        html += '</tr>\n'
                    html += '            </tbody></table>\n'
                if section.items:
                    html += '            <ul class="finding-list">\n'
                    for item in section.items[:50]:
                        html += f'              <li>{_html_escape(item)}</li>\n'
                    if len(section.items) > 50:
                        html += f'              <li style="color:var(--text-muted)">... and {len(section.items) - 50} more</li>\n'
                    html += '            </ul>\n'
                for sub in section.subsections:
                    html += f'            <div class="subsection-title">{_html_escape(sub.title)}</div>\n'
                    if sub.items:
                        html += '            <ul class="finding-list">\n'
                        for item in sub.items[:30]:
                            html += f'              <li>{_html_escape(item)}</li>\n'
                        if len(sub.items) > 30:
                            html += f'              <li style="color:var(--text-muted)">... and {len(sub.items) - 30} more</li>\n'
                        html += '            </ul>\n'

            html += '          </div>\n        </div>\n'  # close rule

        html += '      </div>\n    </div>\n'  # close category

    html += '  </div>\n'

    # Footer
    excel_link = f'<a href="{_html_escape(excel_filename)}">{_html_escape(excel_filename)}</a>' if excel_filename else ""
    footer_data = f"&nbsp;&bull;&nbsp; Full data: {excel_link}" if excel_link else ""
    html += f"""
  <div class="footer">
    CenterTest Health Check &mdash; Generated {generated_at}
    {footer_data}
    <br>Powered by <a href="https://github.com/Kimputing/centertest-skills">centertest-skills</a>
  </div>

</div>
"""
    html += """<script>
function toggleAll(expand) {
  document.querySelectorAll('.detail .rule-detail').forEach(function(el) {
    if (expand) el.classList.add('open'); else el.classList.remove('open');
  });
}
function navigateTo(ruleId, catId) {
  var cat = catId ? document.getElementById(catId) : null;
  if (cat && !cat.classList.contains('open')) cat.classList.add('open');
  var el = document.getElementById(ruleId);
  if (el) {
    if (!el.classList.contains('open')) el.classList.add('open');
    var parent = el.parentElement ? el.parentElement.closest('.rule-detail') : null;
    if (parent && !parent.classList.contains('open')) parent.classList.add('open');
    setTimeout(function() { el.scrollIntoView({behavior: 'smooth', block: 'start'}); }, 50);
  }
}
</script>
</body>
</html>
"""

    os.makedirs(output_dir, exist_ok=True)
    filename = f"HealthCheck_{timestamp}.html"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return filepath


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def print_terminal_summary(results: list[RuleResult], suppressed_count: int = 0):
    """Print a concise summary to the terminal."""
    print("\n" + "=" * 60)
    print("  HEALTH CHECK RESULTS")
    print("=" * 60)

    total_issues = 0
    errors = 0

    for result in results:
        if result.error:
            errors += 1
            status = "ERROR"
            count = "-"
        elif result.rows:
            count = len(result.rows)
            total_issues += count
            status = f"{count} issue(s)" if count > 0 else "OK"
        elif result.sections:
            count = sum(len(s.items) + sum(len(ss.items) for ss in s.subsections) for s in result.sections)
            total_issues += count
            status = f"{count} finding(s)" if count > 0 else "OK"
        else:
            count = 0
            status = "OK"

        indicator = "X" if (result.error or (isinstance(count, int) and count > 0)) else "."
        print(f"  [{indicator}] {result.rule_id}: {result.description:<50} {status}")

    print("-" * 60)
    sup_text = f"  |  Suppressed: {suppressed_count}" if suppressed_count > 0 else ""
    print(f"  Total issues: {total_issues}{sup_text}  |  Errors: {errors}  |  Rules: {len(results)}")
    print("=" * 60)
    blockers, not_checked, dormant = trust_blockers(results, sample_size=3)
    if blockers:
        print("  TRUST BLOCKERS: tests can pass while the app is broken, or cannot run")
        for b in blockers:
            print(f"  !! {b['count']:>3} x {b['title']} ({b['rule_id']})")
            for x in b["samples"]:
                print(f"         {x}")
    else:
        print("  No trust blockers.")
    if dormant:
        print(f"  Not blockers: {dormant} data finding(s) no test runs (unused workbook or disabled row)")
    if not_checked:
        print(f"  Not checked in this run: {', '.join(not_checked)}")
    print("=" * 60)
