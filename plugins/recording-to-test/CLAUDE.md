# CLAUDE.md — recording-to-test

## What It Does

Recorder recording → CenterTest test in the target project's structure. Design:
`docs/superpowers/specs/2026-10-06-recording-to-test-design.md` (repo root).

## Architecture

- `scripts/parse_recording.py` — `session.json` → plan JSON: getter per widget, Java fragment per
  action/check, `review` list, framework `imports`.
- `scripts/scan_project.py` — project → facts (package, layout, roles, step bases and their
  `@FlowTags`, facades, exemplars, cssids source, build commands). Read-only.
- `scripts/find_getter.py` — **vendored, byte-identical** copy of `plugins/cssid-finder/scripts/find_getter.py`.
  Never edit it here; change cssid-finder, then `cp` it over. `tests/test_vendored_sync.py` fails when they differ.
- `skills/recording-to-test/SKILL.md` — the judgment steps (segments, facade matches, names,
  confirmation gate, generation, compile).

## Tests

    python3 -m unittest discover -s plugins/recording-to-test/tests -v

There is no CI in this repo; run them before every commit.

## Gotchas

- A step's `actions` led **to** that step's screen; its checks verify that screen. Segment by the
  widget's page, not by `step.screen`.
- About a third of real widget ids are not in cssids (wizard buttons, tab bar, list-row columns,
  coverage terms in iterators). `resolve_fallback()` builds them in the project's idioms; the
  `raw` rule writes `Widget<Type>.get(id, getContext())`, which OOTB itself uses for coverage terms.
- `find_getter()` prints and exits — call the module's lookup functions, not it.
- OOTB writes `@FlowTags` in two forms (`("…")` and `({"…"})`); the scan reports the annotation as written.
- cssids from the generated jar are extracted to a fresh temp dir per scan.
- Fixture recordings under `tests/fixtures/recordings/real-*` are trimmed copies of real
  recordings; check new ones for sensitive data before committing.
