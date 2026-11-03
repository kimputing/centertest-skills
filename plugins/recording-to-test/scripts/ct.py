#!/usr/bin/env python3
"""Single entry point for the recording-to-test engine: ct.py <command> [args...]."""
import argparse
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# command -> "module:function"; modules are imported lazily, so a command whose module is not there yet
# fails on its own without breaking the others
COMMANDS = {
    "scan": "scan_project:main",
    "parse": "parse_recording:main",
    "xlsx": "xlsx_read:main",
    "narrate": "narration:main_narrate",
    "profile": "client_profile:main",
    "tools": "narration:main_tools",
    "gap-report": "gap_report:main",
    "scrub": "scrub_recording:main",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ct.py", description="recording-to-test engine",
        epilog="commands:\n" + "\n".join(f"  {name:<11} {target}" for name, target in COMMANDS.items()),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=sorted(COMMANDS), metavar="command",
                        help="one of: " + ", ".join(COMMANDS))
    parser.add_argument("args", nargs=argparse.REMAINDER, help="passed on to the command")
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        build_parser().print_help()
        return 0 if argv else 2
    command, rest = argv[0], argv[1:]
    target = COMMANDS.get(command)
    if target is None:
        print(f"Error: unknown command: {command}\ncommands: {', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    module_name, function_name = target.split(":")
    try:
        function = getattr(importlib.import_module(module_name), function_name)
    except (ImportError, AttributeError) as error:
        print(f"Error: command {command} is not available: {error}", file=sys.stderr)
        return 2
    return function(rest)


if __name__ == "__main__":
    sys.exit(main())
