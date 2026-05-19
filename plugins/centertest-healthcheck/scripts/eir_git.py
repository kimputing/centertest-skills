#!/usr/bin/env python3
"""
Git integration for eir-analyzer.

Non-destructive: uses `git show` and `git ls-tree` instead of checking out commits.
Preserves the working tree — no temp directories needed.

Commit selection modes (matching Eir priority):
1. PR mode (target..source)
2. Specific commits (--commits)
3. Monthly sampling (--monthly)
4. Date range (--commit-from/to)
5. Local (default — no git, analyze working directory)

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/eir-analyzer/scripts/eir_git.py
"""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from datetime import datetime

from eir_models import CommitInfo, CommitsDict, SourceCodeFile, LOCAL_COMMIT
from eir_parser import parse_file, get_package_from_path, is_excluded


def _run_git(args: list[str], repo_dir: str) -> subprocess.CompletedProcess:
    """Run a git command with UTF-8 encoding."""
    return subprocess.run(
        ["git"] + args,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=repo_dir,
    )


# ---------------------------------------------------------------------------
# File operations at specific commits
# ---------------------------------------------------------------------------

def get_file_at_commit(sha: str, file_path: str, repo_dir: str) -> str | None:
    """Read a file's content at a specific commit without checkout."""
    result = _run_git(["show", f"{sha}:{file_path}"], repo_dir)
    return result.stdout if result.returncode == 0 else None


def list_java_files_at_commit(sha: str, repo_dir: str, source_root: str = "src/main/java") -> list[str]:
    """List all .java files at a specific commit."""
    result = _run_git(["ls-tree", "-r", "--name-only", sha, "--", source_root], repo_dir)
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.strip().split("\n") if f.endswith(".java") and f]


# ---------------------------------------------------------------------------
# Commit discovery
# ---------------------------------------------------------------------------

def _get_commits_in_range(repo_dir: str, branch: str = "HEAD",
                          date_from: str = None, date_to: str = None) -> list[CommitInfo]:
    """Get commits, optionally filtered by date range."""
    args = ["log", branch, "--format=%H|%ct|%s"]
    if date_from:
        args.extend(["--after", date_from])
    if date_to:
        args.extend(["--before", date_to])
    result = _run_git(args, repo_dir)
    if result.returncode != 0:
        return []

    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line or "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        sha = parts[0]
        try:
            epoch = int(parts[1])
        except ValueError:
            continue
        message = parts[2] if len(parts) > 2 else ""
        commits.append(CommitInfo(
            commit_time=epoch,
            sha=sha,
            short_sha=sha[:7],
            message=message,
        ))

    # Sort by commit time ascending (matching Eir's TreeMap behavior)
    commits.sort()
    return commits


def _get_pr_diff_commits(repo_dir: str, target: str, source: str) -> list[CommitInfo]:
    """Get commits in PR range: target..source."""
    # Try with origin/ prefix first
    result = _run_git(["log", f"origin/{target}..origin/{source}", "--format=%H|%ct|%s"], repo_dir)
    if result.returncode != 0:
        # Try without origin/ prefix
        result = _run_git(["log", f"{target}..{source}", "--format=%H|%ct|%s"], repo_dir)
    if result.returncode != 0:
        return []

    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line or "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 2:
            continue
        sha = parts[0]
        try:
            epoch = int(parts[1])
        except ValueError:
            continue
        message = parts[2] if len(parts) > 2 else ""
        commits.append(CommitInfo(
            commit_time=epoch,
            sha=sha,
            short_sha=sha[:7],
            message=message,
        ))

    commits.sort()
    return commits


# ---------------------------------------------------------------------------
# Commit selection strategies
# ---------------------------------------------------------------------------

def _select_monthly(commits: list[CommitInfo]) -> list[CommitInfo]:
    """Select one commit per month (last commit of each month)."""
    by_month: dict[str, CommitInfo] = {}
    for c in commits:
        dt = datetime.fromtimestamp(c.commit_time)
        key = f"{dt.year}-{dt.month:02d}"
        # Keep the last commit per month (commits are sorted ascending)
        by_month[key] = c
    return sorted(by_month.values())


def _select_by_sha_prefix(commits: list[CommitInfo], sha_prefixes: list[str]) -> list[CommitInfo]:
    """Select commits matching partial SHA prefixes."""
    selected = []
    for c in commits:
        for prefix in sha_prefixes:
            if c.sha.startswith(prefix):
                selected.append(c)
                break
    return selected


# ---------------------------------------------------------------------------
# Parse commits
# ---------------------------------------------------------------------------

def parse_commits_from_git(config) -> CommitsDict:
    """
    Select and parse commits based on configuration.

    Returns CommitsDict: {CommitInfo: [SourceCodeFile]}
    """
    repo_dir = config.repository_dir
    source_root = config.source_root
    mode = config.get_commit_selection_mode()

    date_info = ""
    if config.commit_from and config.commit_to:
        date_info = f" ({config.commit_from} to {config.commit_to})"
    elif config.commit_from:
        date_info = f" (from {config.commit_from})"
    elif config.commit_to:
        date_info = f" (to {config.commit_to})"
    else:
        date_info = " (full history)"
    print(f"  Git mode: {mode}{date_info}")

    # Get candidate commits
    if mode == "pr":
        all_commits = _get_pr_diff_commits(repo_dir, config.pr_target, config.pr_source)
        if all_commits:
            # Take latest commit only (matching Eir)
            selected = [all_commits[-1]]
        else:
            print("  Warning: no commits found in PR range.", file=sys.stderr)
            return {}
    elif mode == "commits":
        all_commits = _get_commits_in_range(repo_dir)
        selected = _select_by_sha_prefix(all_commits, config.commit_list)
    elif mode == "monthly":
        all_commits = _get_commits_in_range(
            repo_dir, date_from=config.commit_from, date_to=config.commit_to
        )
        selected = _select_monthly(all_commits)
    elif mode == "date_range":
        selected = _get_commits_in_range(
            repo_dir, date_from=config.commit_from, date_to=config.commit_to
        )
    else:
        return {}

    # Apply max_commits cap
    if len(selected) > config.max_commits:
        print(f"  Warning: {len(selected)} commits exceed max ({config.max_commits}). "
              f"Truncating to most recent {config.max_commits}.", file=sys.stderr)
        selected = selected[-config.max_commits:]

    print(f"  Selected {len(selected)} commit(s) to analyze")

    # Parse each commit
    result: CommitsDict = {}
    for i, commit in enumerate(selected, 1):
        print(f"  [{i}/{len(selected)}] Parsing commit {commit.short_sha}: {commit.message[:50]}...")

        java_files = list_java_files_at_commit(commit.sha, repo_dir, source_root)
        parsed_files = []

        for file_path in java_files:
            # Apply package/file exclusion filters (same as local mode)
            pkg = get_package_from_path(file_path, repo_dir, source_root)
            if is_excluded(file_path, pkg, config.exclude_packages, config.exclude_files):
                continue

            content = get_file_at_commit(commit.sha, file_path, repo_dir)
            if content is None:
                sf = SourceCodeFile(
                    key=file_path,
                    file_name=file_path.split("/")[-1],
                    parent_directory="/".join(file_path.split("/")[:-1]),
                    cannot_compile=True,
                )
                sf.package_name = get_package_from_path(
                    file_path, repo_dir, source_root
                )
                parsed_files.append(sf)
                continue

            # For git show paths, construct a full path for package derivation
            sf = parse_file(
                content, file_path, repo_dir, source_root,
                config.compat_comment_lines,
            )
            parsed_files.append(sf)

        result[commit] = parsed_files

    # Memory warning
    total_files = sum(len(files) for files in result.values())
    if total_files > 20000:
        print(f"  WARNING: {total_files} file snapshots loaded. "
              f"Consider --max-commits to reduce memory.", file=sys.stderr)

    return result
