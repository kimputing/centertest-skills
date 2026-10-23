# recording-to-test

Turns a CenterTest Recorder recording (the `.zip` an analyst sends, its folder, or its `session.json`) into a CenterTest
test that follows the project's own structure: the test class in its `tests/<center>/<lob>/<txn>/`
layout, the project's login facade, new reusable step classes for the recorded screens, and the
recorded checks as widget assertions.

## Prerequisites

- Python 3.9+ (no packages needed)
- A CenterTest project whose generated page objects are available: the `*-generated` dependency in
  the Gradle/Maven cache (it bundles `cssids/`), or a `*-generated` checkout next to the project.

## Use

In the project directory: "create a test from ~/Downloads/2026-10-01_174907_test1.zip".
The skill shows a table of what it will generate and waits for your approval before writing files.

## Checks → assertions

The Recorder names each check (`isEqualTo`, `optionsContains`, …); the generated test calls the
matching widget assertion. A soft check (*Continue the test if this fails*) uses the `…Soft` variant,
which records the failure and lets the test go on.

| Recorder check | Generated call |
|---|---|
| `isEqualTo` / `isNotEqualTo` | `assertEquals` / `assertNotEquals` |
| `isEqualToNumeric` / `isNotEqualToNumeric` | `assertEqualsNumeric` / `assertNotEqualsNumeric` |
| `contains` / `notContains` | `assertContains` / `assertNotContains` |
| `isIn` | `assertIsIn` |
| `isEmpty` / `isNotEmpty` | `assertEmpty` / `assertNotEmpty` |
| `isChecked` / `isVisible` / `isRequired` | `assertChecked` / `assertVisible` / `assertRequired` (`true` or `false`) |
| `optionsContains` / `optionsEquals` / `optionsNotContains` | `assertOptionsContain` / `assertOptionsEqual` / `assertOptionsNotContain` |
| `isEnabled` / `isDisabled` | `assertEnabled` / `assertDisabled` |
| `isEditable` / `isReadonly` | `assertEditable` / `assertReadOnly` |
| `isLabelEqualTo` | `assertLabel` |
| Message shown: exact / contains | `MessagesUtil.assertMessageWith` / `assertMessageContaining` |
| No errors | `MessagesUtil.getErrorMessages` is empty, in `CenterTestAssertion` |

`MessagesUtil` has no soft form, so a soft message check is wrapped in
`CenterTestAssertion…softAssertThat(() -> …)`.

## What it does not do (yet)

DDT data sheets, `RestartPoints`, ReportPortal configuration, editing existing files (it tells you
which suite file to add the test to; you add it).
