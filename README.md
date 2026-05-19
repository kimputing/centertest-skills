# CenterTest Skills — Claude Code plugin marketplace

A Claude Code plugin marketplace distributing skills for CenterTest test automation development.

**GitHub**: `https://github.com/Kimputing/centertest-skills`

## Plugins

| Plugin | Description | Status |
|--------|-------------|--------|
| [centertest-healthcheck](plugins/centertest-healthcheck/) | Java code quality analysis — 27 rules, HTML dashboard + Excel reports | Active |
| [cssid-finder](plugins/cssid-finder/) | Find Java getter chains for Guidewire UI CSS IDs | Active |
| [ddt-analyzer](plugins/ddt-analyzer/) | Analyze DDT structure and generate 15-sheet Excel report | Active |
| [ddt-tools](plugins/ddt-tools/) | Validate DC references, diff xlsx, report unused codes | Active |

## Installation

Inside Claude Code, add the marketplace and install the plugins you want:

```text
/plugin marketplace add Kimputing/centertest-skills
/plugin install centertest-healthcheck@centertest-skills
/plugin install cssid-finder@centertest-skills
/plugin install ddt-analyzer@centertest-skills
/plugin install ddt-tools@centertest-skills
```

Each plugin is independent — install only the ones you need.

## Updating

```text
/plugin marketplace update centertest-skills
```

Every commit to `main` becomes a new version automatically (no `version` field is pinned in `plugin.json`).

## Structure

```
centertest-skills/                                  # marketplace repo
├── .claude-plugin/
│   └── marketplace.json                            # catalog of plugins
├── plugins/
│   └── <plugin-name>/
│       ├── .claude-plugin/plugin.json              # plugin manifest
│       ├── skills/<plugin-name>/SKILL.md           # skill definition
│       ├── scripts/                                # python scripts (resolved via ${CLAUDE_PLUGIN_ROOT})
│       ├── README.md                               # public docs
│       └── CLAUDE.md                               # dev context for Claude Code
└── README.md                                       # this file
```

## Contributing a new plugin

1. Create `plugins/<plugin-name>/` with `.claude-plugin/plugin.json`, `skills/<plugin-name>/SKILL.md`, and `scripts/`
2. In `SKILL.md`, reference scripts via `${CLAUDE_PLUGIN_ROOT}/scripts/<file>.py` so the path resolves to the plugin's install location
3. Add a new entry to `.claude-plugin/marketplace.json` under `plugins`
4. Update the table above
5. Run `claude plugin validate .` from the repo root to catch JSON / frontmatter errors

See the [Claude Code plugin marketplace docs](https://code.claude.com/docs/en/plugin-marketplaces) for the full schema.
