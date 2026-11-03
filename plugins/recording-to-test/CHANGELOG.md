# Changelog

Releases are git tags `recording-to-test-v<major>.<minor>.<patch>`. The top entry must name the
current `plan schemaVersion` and `project schemaVersion` from `scripts/schema.py`
(`tests/test_changelog.py` checks it).

## 2.0.0 — scenario wizard

- plan schemaVersion 2
- project schemaVersion 2

### Engine

- `scripts/ct.py` is the single entry point for the engine commands.
- Plans and `project.json` carry `schemaVersion`; the skill stops on a higher one than it knows.
- New plan fields: `facadeSequence`, `existingTests`, `dcColumns`, `dataRowCandidates`,
  `restartCandidates`, `seedPointCandidates`, `narration`, `parts`, `chain`.
- New project facts from `scan_project.py`: `dataWorkbooks`, `sharedValuesUsage`,
  `negativeProtocol`, `suites`, `componentEffects`, `testFlows`.
- Workbook reader (`xlsx_read.py`) for the project's data workbooks, standard library only.
- Client profiles (`client_profile.py`, `profile/`): per-client conventions kept outside the skill.
- Gap reports (`gap_report.py`): what the recording needs that the project does not yet have.

### Skill

- Six-phase wizard with one phase file each under `skills/recording-to-test/phases/`, read when
  the phase starts.
- The wizard reads the project's `.claude/client-profile.md` and follows it within the hard rules.

### CI

- Test workflow `.github/workflows/tests.yml` runs the suite on Linux, macOS and Windows.
