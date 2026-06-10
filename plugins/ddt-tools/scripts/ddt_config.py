#!/usr/bin/env python3
"""Shared configuration for DDT tools — manages project path.

Usage:
    ddt-config.py --set-path "/path/to/centertest-project"
    ddt-config.py --show-path

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/ddt-tools/scripts/ddt-config.py
"""

import getpass
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime

CONFIG_DIR = os.path.expanduser("~/.centertest")
CONFIG_FILE = os.path.join(CONFIG_DIR, "ddt-tools.json")


def load_config():
    """Load config from ~/.centertest/ddt-tools.json."""
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config):
    """Save config to ~/.centertest/ddt-tools.json."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Config saved to {CONFIG_FILE}")


def get_project_dir():
    """Resolve the project path: env var > config file > prompt user."""
    # 1. Environment variable takes priority
    env_val = os.environ.get("CENTERTEST_PROJECT_DIR")
    if env_val:
        return env_val

    # 2. Saved config
    config = load_config()
    if config.get("project_dir"):
        return config["project_dir"]

    # 3. First run — ask user
    print("No CenterTest project path configured yet.")
    print("Enter the path to the CenterTest project root")
    print("(the folder containing the 'testdata/' directory):")
    print()
    path = input("> ").strip()

    if not path:
        print("Error: no path provided")
        sys.exit(1)

    path = os.path.expanduser(path)

    if not os.path.isdir(path):
        print(f"Error: directory not found: {path}")
        sys.exit(1)

    if not os.path.isdir(os.path.join(path, "testdata")):
        print(f"Warning: no 'testdata/' directory found in {path}")
        print("Saving anyway — you can update with --set-path later.")

    config["project_dir"] = path
    save_config(config)
    print()
    return path


def set_path(path):
    """Set or override the project path."""
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        print(f"Error: directory not found: {path}")
        sys.exit(1)

    config = load_config()
    old = config.get("project_dir", "(not set)")
    config["project_dir"] = path
    save_config(config)
    print(f"  Old: {old}")
    print(f"  New: {path}")

    if not os.path.isdir(os.path.join(path, "testdata")):
        print(f"  Warning: no 'testdata/' directory found in {path}")


def show_path():
    """Show the current configured path."""
    env_val = os.environ.get("CENTERTEST_PROJECT_DIR")
    config = load_config()
    saved = config.get("project_dir")

    if env_val:
        print(f"Active path (from CENTERTEST_PROJECT_DIR env var): {env_val}")
        if saved:
            print(f"Saved path (overridden by env var): {saved}")
    elif saved:
        print(f"Active path: {saved}")
    else:
        print("No path configured. Run any DDT tool or use --set-path to configure.")


# ─────────────────────────────────────────────────────────────
# PR-review report saving — each report tool also saves its console
# output to pr-review/<git user>/<timestamp>_<tool>.txt inside the
# CenterTest project (mirrors the DDT_check_* Gradle tasks).
# ─────────────────────────────────────────────────────────────


def _resolve_git_user(root):
    """Resolve the git user.name for the project, falling back to the OS user."""
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            cwd=root, capture_output=True, text=True,
        )
        user = result.stdout.strip()
    except OSError:
        user = ""
    if not user:
        user = getpass.getuser()
    # user.name may contain spaces/special chars — keep the path safe
    return re.sub(r"[^A-Za-z0-9._-]", "_", user)


def save_pr_review_report(tool_name, text, root=None):
    """Write report text to pr-review/<git user>/<timestamp>_<tool>.txt under root.

    Returns the report file path, or None if root is not a CenterTest
    project (no testdata/ directory) — avoids littering arbitrary cwds.
    """
    root = root or os.getcwd()
    if not os.path.isdir(os.path.join(root, "testdata")):
        return None
    out_dir = os.path.join(root, "pr-review", _resolve_git_user(root))
    os.makedirs(out_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(out_dir, f"{timestamp}_{tool_name}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class _Tee:
    """Duplicates writes to a real stream and a shared in-memory buffer."""

    def __init__(self, stream, buffer):
        self.stream = stream
        self.buffer = buffer

    def write(self, data):
        self.stream.write(data)
        self.buffer.write(data)

    def flush(self):
        self.stream.flush()


def run_with_pr_review_report(tool_name, main_func):
    """Run main_func with stdout+stderr teed into a pr-review report file.

    The report is saved even when main_func exits non-zero (the exit
    code is preserved), so failed validations still leave evidence.
    """
    buffer = io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout = _Tee(real_out, buffer)
    sys.stderr = _Tee(real_err, buffer)
    exit_code = 0
    try:
        main_func()
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    finally:
        sys.stdout, sys.stderr = real_out, real_err
        path = save_pr_review_report(tool_name, buffer.getvalue())
        if path:
            print(f"\nReport saved to {path}")
    sys.exit(exit_code)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--show-path":
        show_path()
    elif len(sys.argv) == 3 and sys.argv[1] == "--set-path":
        set_path(sys.argv[2])
    else:
        print("Usage:")
        print("  ddt-config.py --set-path <path>   # set project path")
        print("  ddt-config.py --show-path          # show current path")
        sys.exit(1)
