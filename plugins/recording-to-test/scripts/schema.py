"""Schema versions and the declared top-level plan keys, shared by the engine scripts."""

PLAN_SCHEMA_VERSION = 2
PROJECT_SCHEMA_VERSION = 2

# every top-level key build_plan can emit: always present, conditional, and those later engine steps add
PLAN_FIELDS = frozenset({
    "schemaVersion", "recording", "test", "notes", "apps", "steps", "review", "retries", "blockers",
    "navigation", "noteChecks", "transactionDates", "verifyOnly", "imports",
    "startValues", "policyShape", "outcomeMismatch",
    "facadeSequence", "existingTests", "dcColumns", "dataRowCandidates", "restartCandidates",
    "seedPointCandidates", "narration", "parts", "chain",
})
