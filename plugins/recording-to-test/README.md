# recording-to-test

Turns a CenterTest Recorder recording (the `.zip` an analyst sends, or its folder) into a CenterTest
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

## What it does not do (yet)

DDT data sheets, `RestartPoints`, ReportPortal configuration, editing existing files.
