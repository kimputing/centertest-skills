---
name: postgresql-query
description: Query PostgreSQL databases for the CenterTest project. This skill should be used when the user wants to run SQL queries, list tables, inspect table schemas, or explore data in the centertest PostgreSQL database. Triggers on requests like "query the database", "show me tables", "run SQL", "check the database", "show test results", "get execution logs", or any database-related queries.
---

# PostgreSQL Query

## Overview

This skill enables querying the CenterTest PostgreSQL database which stores test execution data, analytics, and metadata. The database has two schemas:
- **centertest** - Test execution logs, results, actions, HTTP request/response data, and analytics
- **data** - Database validation rules, metadata, and obfuscation mappings

For detailed schema information, read `references/schema.md`.

## Connection Details

The connection comes from the standard PostgreSQL environment variables `PGHOST`, `PGPORT`,
`PGDATABASE`, `PGUSER` and `PGPASSWORD`. Where one is unset, the commands below fall back to the
local CenterTest development database: `localhost:5432`, database, user and password all
`centertest`. To query another database, set the variables in your shell profile; never write a
real password into this skill or a command you share.

`${CLAUDE_PLUGIN_ROOT}/scripts/postgresql-query.sh "<SQL>" [-x] [-c] [-t]` wraps the same
connection (`-x` expanded, `-c` CSV, `-t` timing).

## Key Tables Quick Reference

### Test Execution Tables
| Table | Purpose |
|-------|---------|
| ExecutionLog | Root container for test sessions (id, creationDate, hostname, environment) |
| ExecutionResult | Individual test results (testName, testOutcome, executionInMillis) |
| ExecutionAction | Steps performed during tests (type, actual, expected, durationTime) |
| ExecutionRequestData | HTTP requests captured (method, url, requestId) |
| ExecutionResponseData | HTTP response metrics (status, responseTime, latency) |
| AssertionError | Failed assertion messages |

### Analytics Tables
| Table | Purpose |
|-------|---------|
| GeneratorLog | Test generation logs |
| AnalyticsData | Page/element analytics (page, element, elementStatus) |
| AnalyticsBaseVersion | Version tracking |

### Data Schema Tables
| Table | Purpose |
|-------|---------|
| TableChecks | Database validation rules |
| Metadata | Foreign key relationships |
| SourceBasedKeys | Version-specific FK info |
| DataSequence | Sequence generation |
| Obfuscation | Data obfuscation mappings |

## Quick Reference Commands

### List All Tables

```bash
PGPASSWORD="${PGPASSWORD:-centertest}" psql -h "${PGHOST:-localhost}" -p "${PGPORT:-5432}" -U "${PGUSER:-centertest}" -d "${PGDATABASE:-centertest}" -c "\dt"
```

### Inspect Table Schema

```bash
PGPASSWORD="${PGPASSWORD:-centertest}" psql -h "${PGHOST:-localhost}" -p "${PGPORT:-5432}" -U "${PGUSER:-centertest}" -d "${PGDATABASE:-centertest}" -c "\d <table_name>"
```

### Run a SELECT Query

```bash
PGPASSWORD="${PGPASSWORD:-centertest}" psql -h "${PGHOST:-localhost}" -p "${PGPORT:-5432}" -U "${PGUSER:-centertest}" -d "${PGDATABASE:-centertest}" -c "<SQL_QUERY>"
```

For multi-line or complex queries, use a heredoc:

```bash
PGPASSWORD="${PGPASSWORD:-centertest}" psql -h "${PGHOST:-localhost}" -p "${PGPORT:-5432}" -U "${PGUSER:-centertest}" -d "${PGDATABASE:-centertest}" <<EOF
SELECT column1, column2
FROM table_name
WHERE condition
ORDER BY column1
LIMIT 100;
EOF
```

## Common Queries

### Test Execution Summary
```sql
SELECT
    el.id, el.creationdate, el.hostname, el.environment,
    COUNT(er.id) as total_tests,
    SUM(CASE WHEN er.testoutcome = 'PASS' THEN 1 ELSE 0 END) as passed,
    SUM(CASE WHEN er.testoutcome = 'FAIL' THEN 1 ELSE 0 END) as failed
FROM executionlog el
LEFT JOIN executionresult er ON er.executionlog_id = el.id
GROUP BY el.id, el.creationdate, el.hostname, el.environment
ORDER BY el.creationdate DESC
LIMIT 20;
```

### Recent Failed Tests
```sql
SELECT testname, testcode, stepname, executioninmillis, assertioncause
FROM executionresult
WHERE testoutcome = 'FAIL'
ORDER BY starttime DESC
LIMIT 50;
```

### Performance Metrics by URL
```sql
SELECT
    url,
    AVG(responsetime) as avg_response,
    MAX(responsetime) as max_response,
    AVG(latency) as avg_latency,
    COUNT(*) as request_count
FROM executionresponsedata
GROUP BY url
ORDER BY avg_response DESC
LIMIT 20;
```

### Analytics by Page
```sql
SELECT page, pagestatus, COUNT(*) as element_count
FROM analyticsdata
GROUP BY page, pagestatus
ORDER BY element_count DESC;
```

## Workflows

### Exploring the Database

When the user wants to explore the database:

1. First list all tables using `\dt`
2. If asked about a specific table, show its schema using `\d table_name`
3. Run queries as requested
4. For detailed schema info, read `references/schema.md`

### Running Queries

When executing user queries:

1. Always use SELECT queries only (read-only access)
2. Add `LIMIT 100` to queries without a limit to prevent large result sets
3. Format output for readability when needed using `-x` flag for expanded display
4. Note: PostgreSQL uses lowercase table/column names by default

### Understanding Relationships

Key relationships in the database:
- ExecutionLog (1) -> ExecutionResult (many)
- ExecutionResult (1) -> ExecutionAction (many)
- ExecutionResult (1) -> ExecutionRequestData (many)
- ExecutionResult (1) -> ExecutionResponseData (many)
- GeneratorLog (1) -> AnalyticsData (many)

### Exporting Execution Data to CSV

When the user requests CSV export of execution log data (e.g., "export last 3 runs", "export execution logs X, Y, Z to CSV"), export all related tables to the db drop folder.

**Output folder:** the folder the user names; ask if they didn't. Website demo exports have gone to the Dropbox folder `Kimputing, Inc. Dropbox/General/Marketing/Website/Demo Test/suite new/db drop/`.

**Selection methods:**
- By count: `SELECT id FROM centertest.executionlog ORDER BY creationdate DESC LIMIT N`
- By ID list: `WHERE id IN ('id1', 'id2', 'id3')`
- By date range: `WHERE creationdate BETWEEN 'start' AND 'end'`

**Tables to export (9 files):**

1. **executionlog.csv** - Main execution logs with LOB deserialization
```bash
docker exec postgres_db psql -U centertest -d centertest -c "
COPY (
  SELECT
    id,
    convert_from(lo_get(centertestproperties), 'UTF8') as centertestproperties,
    creationdate, environment, hostname, mode, performancetest, run
  FROM centertest.executionlog
  WHERE id IN (<LOG_ID_SELECTION>)
  ORDER BY creationdate DESC
) TO STDOUT WITH CSV HEADER;
" > "<OUTPUT_FOLDER>/executionlog.csv"
```

2. **executionresult.csv** - Test results with assertion/exception causes
```bash
docker exec postgres_db psql -U centertest -d centertest -c "
COPY (
  SELECT er.id, er.testname, er.testcode, er.testcontainer, er.stepname, er.testoutcome,
         er.starttime, er.endtime, er.executioninmillis, er.datasource, er.threadname,
         er.threadcount, er.testdata, er.executionlog_id,
         convert_from(lo_get(er.assertioncause::oid), 'UTF8') as assertioncause,
         convert_from(lo_get(er.exceptioncause::oid), 'UTF8') as exceptioncause
  FROM centertest.executionresult er
  WHERE er.executionlog_id IN (<LOG_ID_SELECTION>)
  ORDER BY er.starttime
) TO STDOUT WITH CSV HEADER;
" > "<OUTPUT_FOLDER>/executionresult.csv"
```

3. **executionaction.csv** - Test actions/steps with LOB fields
```bash
docker exec postgres_db psql -U centertest -d centertest -c "
COPY (
  SELECT
    ea.id, ea.actual,
    convert_from(lo_get(ea.ajaxresponse), 'UTF8') as ajaxresponse,
    convert_from(lo_get(ea.analyticid), 'UTF8') as analyticid,
    ea.application, ea.assertioncall, ea.client,
    convert_from(lo_get(ea.cssid), 'UTF8') as cssid,
    ea.durationtime, ea.endtime, ea.expected, ea.origintype, ea.starttime, ea.type, ea.executionresult_id
  FROM centertest.executionaction ea
  JOIN centertest.executionresult er ON ea.executionresult_id = er.id
  WHERE er.executionlog_id IN (<LOG_ID_SELECTION>)
  ORDER BY ea.id
) TO STDOUT WITH CSV HEADER;
" > "<OUTPUT_FOLDER>/executionaction.csv"
```

4. **executionrequestdata.csv** - HTTP request data with LOB fields
```bash
docker exec postgres_db psql -U centertest -d centertest -c "
COPY (
  SELECT
    erd.id,
    convert_from(lo_get(erd.eventsource), 'UTF8') as eventsource,
    erd.frameid, erd.initiatiortype, erd.initiatiorurl, erd.loaderid, erd.method,
    convert_from(lo_get(erd.objfocusid), 'UTF8') as objfocusid,
    erd.requestid, erd.type, erd.url, erd.executionresult_id
  FROM centertest.executionrequestdata erd
  JOIN centertest.executionresult er ON erd.executionresult_id = er.id
  WHERE er.executionlog_id IN (<LOG_ID_SELECTION>)
  ORDER BY erd.id
) TO STDOUT WITH CSV HEADER;
" > "<OUTPUT_FOLDER>/executionrequestdata.csv"
```

5. **executionresponsedata.csv** - HTTP response data with URL LOB
```bash
docker exec postgres_db psql -U centertest -d centertest -c "
COPY (
  SELECT
    eresp.id, eresp.connecttime, eresp.datalength, eresp.dnstime, eresp.frameid,
    eresp.latency, eresp.loaderid, eresp.proxytime, eresp.pushtime, eresp.requestid,
    eresp.responsetime, eresp.sendtime, eresp.ssltime, eresp.status, eresp.type,
    convert_from(lo_get(eresp.url::oid), 'UTF8') as url,
    eresp.executionresult_id
  FROM centertest.executionresponsedata eresp
  JOIN centertest.executionresult er ON eresp.executionresult_id = er.id
  WHERE er.executionlog_id IN (<LOG_ID_SELECTION>)
  ORDER BY eresp.id
) TO STDOUT WITH CSV HEADER;
" > "<OUTPUT_FOLDER>/executionresponsedata.csv"
```

6. **assertionerror.csv** - Assertion error messages
```bash
docker exec postgres_db psql -U centertest -d centertest -c "
COPY (
  SELECT
    ae.id,
    convert_from(lo_get(ae.message), 'UTF8') as message,
    ae.executionresult_id
  FROM centertest.assertionerror ae
  JOIN centertest.executionresult er ON ae.executionresult_id = er.id
  WHERE er.executionlog_id IN (<LOG_ID_SELECTION>)
  ORDER BY ae.id
) TO STDOUT WITH CSV HEADER;
" > "<OUTPUT_FOLDER>/assertionerror.csv"
```

7. **data.csv** - Test data key-value pairs
```bash
docker exec postgres_db psql -U centertest -d centertest -c "
COPY (
  SELECT d.*
  FROM centertest.data d
  JOIN centertest.executionresult er ON d.result_id = er.id
  WHERE er.executionlog_id IN (<LOG_ID_SELECTION>)
  ORDER BY d.result_id, d.datakey
) TO STDOUT WITH CSV HEADER;
" > "<OUTPUT_FOLDER>/data.csv"
```

8. **executionsystemproperties.csv** - System properties for logs
```bash
docker exec postgres_db psql -U centertest -d centertest -c "
COPY (
  SELECT esp.*
  FROM centertest.executionsystemproperties esp
  WHERE esp.log_id IN (<LOG_ID_SELECTION>)
  ORDER BY esp.log_id, esp.propertykey
) TO STDOUT WITH CSV HEADER;
" > "<OUTPUT_FOLDER>/executionsystemproperties.csv"
```

9. **executionenvironmentvariables.csv** - Environment variables for logs
```bash
docker exec postgres_db psql -U centertest -d centertest -c "
COPY (
  SELECT eev.*
  FROM centertest.executionenvironmentvariables eev
  WHERE eev.log_id IN (<LOG_ID_SELECTION>)
  ORDER BY eev.log_id, eev.variablekey
) TO STDOUT WITH CSV HEADER;
" > "<OUTPUT_FOLDER>/executionenvironmentvariables.csv"
```

**LOB fields summary (must use convert_from(lo_get(...), 'UTF8')):**
| Table | LOB Columns |
|-------|-------------|
| executionlog | centertestproperties |
| executionresult | assertioncause, exceptioncause |
| executionaction | ajaxresponse, analyticid, cssid |
| executionrequestdata | eventsource, objfocusid |
| executionresponsedata | url (stored as OID in varchar) |
| assertionerror | message |

**Example user requests:**
- "Export last 3 execution logs to CSV" → Use LIMIT 3
- "Export logs 20251204-112150.305 and 20251204-111939.085" → Use ID list
- "Export all logs from today" → Use date filter

## Tips

- Use `\x` or `-x` flag for expanded (vertical) output on wide tables
- Use `\timing` to show query execution time
- For CSV output, use: `-A -F',' -c "<query>"`
- PostgreSQL table/column names are lowercase (executionlog, not ExecutionLog)
- LOB columns (centertestproperties, assertioncause, etc.) may contain large text

## Example Usage

**User:** "Show me recent test executions"
**Action:** Query ExecutionLog ordered by creationdate DESC

**User:** "What tests failed today?"
**Action:** Query ExecutionResult where testoutcome = 'FAIL' and filter by date

**User:** "Show performance metrics"
**Action:** Query ExecutionResponseData for response times and latency

**User:** "List all tables"
**Action:** Run `\dt` to list tables
