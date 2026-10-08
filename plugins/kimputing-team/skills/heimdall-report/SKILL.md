---
name: heimdall-report
description: Generate a CenterTest usage-analytics report for any Heimdall customer from the production RDS. Use when the user asks for a usage report, usage analytics, or activity summary for a license client (e.g. "Heimdall report for Copperpoint", "usage for <customer>", "which customers use us", "list clients"). Routes queries through AWS SSM to the EC2 box because the RDS port is not directly reachable.
---

# Heimdall Usage Report

Produces a usage-analytics report for any customer tracked in the Heimdall license
database (`HEIMDALL.usage_analytics` + key/value `usage_data`). These are CenterTest
execution telemetry records (engine, browser, OS, mode, version, environments,
scenario counts, thread parallelism, Guidewire footprint).

## Why a script (don't hand-roll psql)

Queries run **on the SSM-managed Heimdall EC2 box** (default `i-07fc04cfca5348076`,
eu-west-1) against the RDS `license-pg17`, so no local psql or database credentials are
needed. The script handles that routing (via `aws ssm send-command` over 443), installs
psql on the box, and escapes the client name. Prefer it over ad-hoc SSM calls.

Script: `scripts/heimdall-report.sh` in the user's checkout of `kimputing/centertest-heimdall`
(usually `~/projects/kimputing/centertest-heimdall`; if it isn't there, ask where it is, or
offer `gh repo clone kimputing/centertest-heimdall`). Below, `$HR` means that script's path.
Requires the `aws` CLI authenticated with `ssm:SendCommand` on the instance. The DB password
comes from `HEIMDALL_DB_PASSWORD` or the repo's `application.properties`. Other defaults
can be overridden with `HEIMDALL_INSTANCE_ID`, `HEIMDALL_REGION`, `HEIMDALL_DB_HOST`.

## Workflow

1. **If the user didn't name a customer, or the name is uncertain**, list them first and
   match (names are case-sensitive, e.g. `Copperpoint`, not `copperpoint`):
   ```bash
   "$HR" --list
   ```
   Watch for related clients (e.g. a `*_POC` proof-of-concept client) and mention them.

2. **Generate the data report** to a temp file:
   ```bash
   "$HR" "<Client>" /tmp/<Client>_report.md
   ```
   Optional date window: `--from 2026-01-01 --to 2026-06-30`.

3. **Read the file**, then **write a narrative report** on top of the raw tables — don't
   just dump the tables. Include:
   - **Executive summary**: total runs, date span, active-day cadence, whether it's a
     daily-driver vs trial, headline stack (engine/browser/OS/test manager).
   - **Volume & cadence**: monthly trend, day-of-week pattern, busiest days.
   - **Execution profile**: mode, execution mode, engine/browser/OS, headless, version
     adoption (flag if stuck on an old version).
   - **Environments & reporting**: environment coverage, test manager, savetodatabase,
     performancetest.
   - **Scale**: scenario totals (basic vs data-driven vs multiplied), thread parallelism
     distribution.
   - **Guidewire footprint**: centers, product lines, package — confirms full GW usage.
   - **Observations & recommendations**: adoption health, upsell/enablement gaps
     (e.g. perf testing unused), version-migration nudges.
   Compute shares/percentages from the counts; the script gives raw counts only.

4. Save the final narrative report where the user wants it (default: the heimdall repo
   root as `<Client>_Usage_Report.md`).

## Notes

- `--check` runs a connectivity smoke test.
- The script leaves `psql` installed on the prod EC2 box (intended; reused each run).
- The report contains customer usage data. Keep it internal; don't paste it into tickets or chats
  outside Kimputing.
- If `centertest-heimdall/Copperpoint_Usage_Report.md` exists in the checkout, match its depth and
  structure.
