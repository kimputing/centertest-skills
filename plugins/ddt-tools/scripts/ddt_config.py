#!/usr/bin/env python3
"""Shared configuration for DDT tools — manages project path.

Usage:
    ddt-config.py --set-path "/path/to/centertest-project"
    ddt-config.py --show-path

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/ddt-tools/scripts/ddt-config.py
"""

import json
import os
import sys

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
