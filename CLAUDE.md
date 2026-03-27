# CLAUDE.md

## What This Is

Collection of Claude Code skills for CenterTest test automation development. Each skill is a self-contained folder under `skills/` with a SKILL.md (definition), scripts/ (implementation), and README.md (docs).

## Skill Pattern

Every skill follows this structure:
```
skills/<name>/
├── SKILL.md          # YAML frontmatter (name, description with trigger phrases) + usage instructions
├── README.md         # Public docs, GitHub links, prerequisites
├── CLAUDE.md         # Development context for Claude Code
└── scripts/
    ├── main_script.py
    └── helper.py     # optional shared utilities
```

**SKILL.md frontmatter** must have `name` and `description` fields. The `description` must include trigger phrases that Claude uses to match user requests to skills.

**Config pattern**: Skills store config in `~/.centertest/<skill-name>.json`. Resolution order: env var > config file > interactive prompt.

**Python detection**: Always use `python3` first, fall back to `python`. Never use `command -v` (breaks on Windows Git Bash).

## Skills

| Skill | Purpose | Scripts |
|-------|---------|---------|
| **centertest-healthcheck** | Java code quality analysis — 27 rules, HTML+Excel reports | 8 modules + 10 rule files |
| **cssid-finder** | Find getter chains for Guidewire CSS IDs | 1 script |
| **ddt-analyzer** | DDT structure analysis, 15-sheet Excel report | 1 script |
| **ddt-tools** | Validate DC refs, diff xlsx, cleanup unused codes | 6 scripts + shared config |

## Commands

```bash
# Run healthcheck on a CenterTest project
python3 skills/centertest-healthcheck/scripts/eir_analyzer.py --path /path/to/project

# Find a CSS ID getter
python3 skills/cssid-finder/scripts/find_getter.py pc "SomeCssId"

# Analyze DDT structure
python3 skills/ddt-analyzer/scripts/ddt-analyzer.py

# Validate DDT references
python3 skills/ddt-tools/scripts/xlsx-validate-refs.py
```

## Development Guidelines

- **Python 3**, no heavy dependencies. `openpyxl` for Excel, `javalang` for Java parsing.
- **Never commit** generated output (healthcheck/, results/, *.xlsx reports)
- Skills are installed via symlink or copy to `~/.claude/skills/`
- Each skill should work standalone — no cross-skill imports at runtime
- `datadriven` package is excluded by default in healthcheck (generated code)

## Gotchas

- The `eir_analyzer.py` filename is historical (Eir was the Java predecessor). The skill is called `centertest-healthcheck`.
- Rule files in `rules/` are auto-discovered via `__init__.py` — drop a `rule_*.py` file and it registers automatically.
- `@dataclass(eq=False)` is critical on Method, ClassEntry, Field — rules 2001/2002 depend on subset equality.
- Method bodies are extracted via source-position slicing from javalang AST positions, not from javalang itself (it doesn't store body text).
