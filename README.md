# CenterTest Skills

A collection of Claude Code skills for CenterTest development and automation.

**GitHub**: `https://github.com/Kimputing/centertest-skills`

## Structure

```
centertest-skills/
├── skills/
│   └── <skill-name>/
│       ├── SKILL.md          # Skill definition (frontmatter + instructions)
│       ├── scripts/          # Supporting scripts (if any)
│       └── README.md         # Skill documentation & latest version info
└── README.md                 # This file
```

## Skills

| Skill | Description | Status |
|-------|-------------|--------|
| [cssid-finder](skills/cssid-finder/) | Find Java getter chains for Guidewire UI CSS IDs | Active |

## Installation

Copy a skill folder into your Claude Code skills directory:

```bash
# Copy a single skill
cp -r skills/cssid-finder ~/.claude/skills/cssid-finder

# Or symlink for auto-updates when you pull
ln -s "$(pwd)/skills/cssid-finder" ~/.claude/skills/cssid-finder
```

## Updating Skills

Each skill's `README.md` contains a link to its latest version on GitHub. To update:

```bash
git pull origin main
```

If you installed via symlink, skills update automatically on pull.

## Contributing

1. Create a new folder under `skills/` with your skill name
2. Add `SKILL.md` with frontmatter (`name`, `description`) and usage instructions
3. Add `README.md` with latest version info and GitHub link
4. Add any supporting scripts in `scripts/`
5. Update this README's skills table
