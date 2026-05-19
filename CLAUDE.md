# CLAUDE.md

## What This Is

Claude Code plugin marketplace distributing skills for CenterTest test automation development. Each skill is wrapped as its own plugin under `plugins/<name>/`. The marketplace catalog lives in `.claude-plugin/marketplace.json` at the repo root.

## Repository Layout

```
.claude-plugin/
└── marketplace.json                    # marketplace catalog (name, owner, plugins[])

plugins/<plugin-name>/
├── .claude-plugin/
│   └── plugin.json                     # plugin manifest (name, description, author, ...)
├── skills/<plugin-name>/
│   └── SKILL.md                        # YAML frontmatter (name, description w/ triggers) + instructions
├── scripts/                            # python scripts, referenced via ${CLAUDE_PLUGIN_ROOT}/scripts/
│   ├── main_script.py
│   └── helper.py
├── README.md                           # public docs, prerequisites
└── CLAUDE.md                           # dev context for Claude Code
```

**Conventions**:
- `plugin.json` deliberately omits `version` so each git commit becomes a new version automatically (per Claude Code marketplace docs).
- Plugin name == inner skill name (e.g. plugin `cssid-finder` contains skill `cssid-finder`).
- SKILL.md frontmatter must have `name` and `description`. The description must include trigger phrases.
- Inside `SKILL.md`, scripts must be referenced as `"${CLAUDE_PLUGIN_ROOT}/scripts/<file>.py"` — never via `~/.claude/skills/...` (that path doesn't exist in plugin install).
- Config pattern (unchanged): skills store user config in `~/.centertest/<skill-name>.json`. Resolution order: env var > config file > interactive prompt.
- Python detection: use `python3` first, fall back to `python`. Never use `command -v` (breaks on Windows Git Bash).

## Plugins

| Plugin | Purpose | Scripts |
|--------|---------|---------|
| **centertest-healthcheck** | Java code quality analysis — 27 rules, HTML+Excel reports | 8 modules + 10 rule files |
| **cssid-finder** | Find getter chains for Guidewire CSS IDs | 1 script |
| **ddt-analyzer** | DDT structure analysis, 15-sheet Excel report | 1 script |
| **ddt-tools** | Validate DC refs, diff xlsx, cleanup unused codes | 6 scripts + shared config |

## Running scripts during development

These commands run scripts directly from the repo checkout (useful for dev/debug — not the path Claude uses at runtime, which is `${CLAUDE_PLUGIN_ROOT}`):

```bash
# Run healthcheck on a CenterTest project
python3 plugins/centertest-healthcheck/scripts/eir_analyzer.py --path /path/to/project

# Find a CSS ID getter
python3 plugins/cssid-finder/scripts/find_getter.py pc "SomeCssId"

# Analyze DDT structure
python3 plugins/ddt-analyzer/scripts/ddt-analyzer.py

# Validate DDT references
python3 plugins/ddt-tools/scripts/xlsx-validate-refs.py
```

## Validating the marketplace

```bash
# Syntactic check — catches JSON errors, malformed frontmatter, duplicate names
claude plugin validate .

# Local install test (run from a directory that is NOT this repo)
claude plugin marketplace add /Users/arkadiuszfrankowski/projects/Azure_Kimputing/centertest-skills
claude plugin install cssid-finder@centertest-skills
```

## Development Guidelines

- **Python 3**, no heavy dependencies. `openpyxl` for Excel, `javalang` for Java parsing.
- **Never commit** generated output (`healthcheck/`, `results/`, `*.xlsx` reports).
- Plugins are independent — no cross-plugin imports at runtime. Plugins are copied into a cache dir on install, so `../other-plugin/...` paths break.
- `datadriven` package is excluded by default in healthcheck (generated code).
- When adding a plugin: create `plugins/<name>/`, add the entry to `marketplace.json`, run `claude plugin validate .`.

## Gotchas

- The `eir_analyzer.py` filename is historical (Eir was the Java predecessor). The plugin/skill is `centertest-healthcheck`.
- Rule files in `centertest-healthcheck/scripts/rules/` are auto-discovered via `__init__.py` — drop a `rule_*.py` file and it registers automatically.
- `@dataclass(eq=False)` is critical on Method, ClassEntry, Field — rules 2001/2002 depend on subset equality.
- Method bodies are extracted via source-position slicing from javalang AST positions, not from javalang itself (it doesn't store body text).
- The old `skills/` directory was removed in the marketplace refactor — git history preserves the original layout. Anyone with copies/symlinks of the old `~/.claude/skills/<name>` paths should remove them after switching to `/plugin install`.
