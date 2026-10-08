# CenterTest Database Schema Reference

## Overview

The CenterTest database uses a JPA/Hibernate-managed schema with two main schemas:
- **centertest** - Test execution and analytics data
- **data** - Database validation and metadata

## Centertest Schema Tables

### ExecutionLog
Root container for test execution sessions.

| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR (PK) | Unique identifier |
| creationDate | TIMESTAMP | When execution started |
| hostname | VARCHAR | Machine running tests |
| environment | VARCHAR | Target environment |
| run | VARCHAR | Run identifier |
| mode | VARCHAR | Execution mode |
| performanceTest | BOOLEAN | Performance test flag |
| centertestProperties | TEXT (LOB) | Configuration properties |

**Collections:**
- `ExecutionSystemProperties` - System properties at execution time
- `ExecutionEnvironmentVariables` - Environment variables at execution time

---

### ExecutionResult
Individual test case results (child of ExecutionLog).

| Column | Type | Description |
|--------|------|-------------|
| id | BIGINT (PK) | Auto-generated ID |
| testName | VARCHAR | Name of the test |
| testCode | VARCHAR | Test code/identifier |
| stepName | VARCHAR | Current step name |
| threadName | VARCHAR | Thread executing test |
| threadCount | INT | Number of threads |
| startTime | TIMESTAMP | Test start time |
| endTime | TIMESTAMP | Test end time |
| executionInMillis | BIGINT | Duration in milliseconds |
| testOutcome | VARCHAR | PASS/FAIL/SKIP status |
| datasource | VARCHAR | Data source used |
| assertionCause | TEXT (LOB) | Assertion failure details |
| exceptionCause | TEXT (LOB) | Exception details |

**Relationships:**
- Many-to-One: ExecutionLog
- One-to-Many: ExecutionAction, ExecutionRequestData, ExecutionResponseData

**Collections:**
- `testDataIdentifier` - Key-value pairs for test data identification
- `data` - Generic key-value data map (3000 char limit)

---

### ExecutionAction
Actions/steps performed during test execution.

| Column | Type | Description |
|--------|------|-------------|
| id | BIGINT (PK) | Auto-generated ID |
| type | VARCHAR | Action type |
| originType | VARCHAR | Origin of the action |
| actual | VARCHAR | Actual value |
| expected | VARCHAR | Expected value |
| application | VARCHAR | Target application |
| assertionCall | VARCHAR | Assertion method called |
| startTime | TIMESTAMP | Action start time |
| endTime | TIMESTAMP | Action end time |
| durationTime | BIGINT | Duration in ms |
| cssId | TEXT (LOB) | CSS selector ID |
| analyticId | TEXT (LOB) | Analytics identifier |
| ajaxResponse | TEXT (LOB) | AJAX response data |
| client | VARCHAR | Client identifier |

---

### ExecutionRequestData
HTTP request details captured during execution.

| Column | Type | Description |
|--------|------|-------------|
| id | BIGINT (PK) | Auto-generated ID |
| requestId | VARCHAR | HTTP request ID |
| loaderId | VARCHAR | Page loader ID |
| frameId | VARCHAR | Frame identifier |
| type | VARCHAR | Request type |
| method | VARCHAR | HTTP method (GET/POST/etc) |
| url | VARCHAR | Request URL |
| initiatorType | VARCHAR | What initiated request |
| initiatorUrl | VARCHAR | Initiator URL |
| eventSource | TEXT (LOB) | Event source data |
| objFocusId | TEXT (LOB) | Focus object ID |

---

### ExecutionResponseData
HTTP response metrics and performance data.

| Column | Type | Description |
|--------|------|-------------|
| id | BIGINT (PK) | Auto-generated ID |
| requestId | VARCHAR | Matching request ID |
| loaderId | VARCHAR | Page loader ID |
| frameId | VARCHAR | Frame identifier |
| type | VARCHAR | Response type |
| url | VARCHAR | Response URL |
| status | INT | HTTP status code |
| dataLength | BIGINT | Response size in bytes |
| proxyTime | DOUBLE | Proxy processing time |
| dnsTime | DOUBLE | DNS lookup time |
| connectTime | DOUBLE | Connection time |
| sslTime | DOUBLE | SSL handshake time |
| sendTime | DOUBLE | Request send time |
| pushTime | DOUBLE | Server push time |
| responseTime | DOUBLE | Response receive time |
| latency | DOUBLE | Total latency |

---

### AssertionError
Failed assertion messages and stack traces.

| Column | Type | Description |
|--------|------|-------------|
| id | BIGINT (PK) | Auto-increment ID |
| message | TEXT (LOB) | Error message (100KB max) |

---

### GeneratorLog
Test script generation execution logs.

| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR (PK) | Unique identifier |
| centertestProperties | TEXT (LOB) | Generator configuration |
| hostname | VARCHAR | Machine running generator |

**Collections:**
- `GeneratorSystemProperties` - System properties during generation
- `GeneratorEnvironmentVariables` - Environment variables during generation

---

### AnalyticsData
Element-level analytics and page performance data.

| Column | Type | Description |
|--------|------|-------------|
| id | BIGINT (PK) | Auto-generated ID |
| buildVersion | VARCHAR | Application build version |
| center | VARCHAR | Guidewire center name |
| client | VARCHAR | Client identifier |
| centerVersion | VARCHAR | Center version |
| source | VARCHAR | Data source |
| page | VARCHAR | Page name |
| pageStatus | VARCHAR | Page load status |
| element | VARCHAR | UI element name |
| elementStatus | VARCHAR | Element status |
| elementType | VARCHAR | Type of element |
| analyticId | VARCHAR | Analytics tracking ID |
| property | VARCHAR | Property being tracked |
| propertyStatus | VARCHAR | Property status |
| value | VARCHAR | Property value |

---

### AnalyticsBaseVersion
Base version tracking for analytics.

| Column | Type | Description |
|--------|------|-------------|
| id | BIGINT (PK) | Auto-generated ID |
| client | VARCHAR | Client identifier |
| center | VARCHAR | Guidewire center |
| centerVersion | VARCHAR | Center version |

---

## Data Schema Tables

### TableChecks
Database table validation rules.

| Column | Type | Description |
|--------|------|-------------|
| id | BIGINT (PK) | Auto-generated ID |
| structure | VARCHAR | Table structure type |
| tableName | VARCHAR | Target table name |
| queryText | TEXT | Validation query |
| queryToIdentifyRows | TEXT | Row identification query |
| description | VARCHAR | Rule description |
| version | VARCHAR | Schema version |
| dbType | VARCHAR | Database type |

---

### Metadata
Foreign key and table relationship metadata.

| Column | Type | Description |
|--------|------|-------------|
| id | BIGINT (PK) | Auto-generated ID |
| center | VARCHAR | Guidewire center |
| version | VARCHAR | Schema version |
| name | VARCHAR | Relationship name |
| parentTable | VARCHAR | Parent table name |
| parentColumn | VARCHAR | Parent column name |
| referencedTable | VARCHAR | Referenced table |
| referencedColumn | VARCHAR | Referenced column |

---

### SourceBasedKeys
Version-specific foreign key information.

| Column | Type | Description |
|--------|------|-------------|
| id | BIGINT (PK) | Auto-generated ID |
| center | VARCHAR | Guidewire center |
| guidewireVersion | VARCHAR | GW version |
| platformMajorVersion | INT | Platform major version |
| platformMinorVersion | INT | Platform minor version |
| metadataMajorVersion | INT | Metadata major version |
| metadataMinorVersion | INT | Metadata minor version |
| extensionVersion | INT | Extension version |
| name | VARCHAR | Key name |
| parentTable | VARCHAR | Parent table |
| parentColumn | VARCHAR | Parent column |
| referencedTable | VARCHAR | Referenced table |
| referencedColumn | VARCHAR | Referenced column |

---

### DataSequence
Sequence number generation for data.

| Column | Type | Description |
|--------|------|-------------|
| id | BIGINT (PK) | Auto-increment ID |
| sequenceKey | VARCHAR | Sequence identifier |
| sequenceNumber | BIGINT | Current sequence value |

---

### Obfuscation
Data obfuscation mapping rules.

| Column | Type | Description |
|--------|------|-------------|
| obfuscationKey | VARCHAR (PK) | Primary key |
| id | VARCHAR | Record identifier |
| tableName | VARCHAR | Target table |
| sharedUid | VARCHAR | Shared unique ID |
| idColumnName | VARCHAR | ID column name |
| code | VARCHAR | Obfuscation code |
| database | VARCHAR | Database name |
| procId | VARCHAR | Process identifier |

---

## Key Relationships Diagram

```
ExecutionLog (1)
    └── ExecutionResult (*)
            ├── ExecutionAction (*)
            ├── ExecutionRequestData (*)
            └── ExecutionResponseData (*)

GeneratorLog (1)
    └── AnalyticsData (*)
```

## Common Queries

### Get test execution summary
```sql
SELECT
    el.id, el.creationDate, el.hostname, el.environment,
    COUNT(er.id) as total_tests,
    SUM(CASE WHEN er.testOutcome = 'PASS' THEN 1 ELSE 0 END) as passed,
    SUM(CASE WHEN er.testOutcome = 'FAIL' THEN 1 ELSE 0 END) as failed
FROM ExecutionLog el
LEFT JOIN ExecutionResult er ON er.executionLog_id = el.id
GROUP BY el.id, el.creationDate, el.hostname, el.environment
ORDER BY el.creationDate DESC;
```

### Get failed tests with details
```sql
SELECT
    er.testName, er.testCode, er.stepName,
    er.executionInMillis, er.assertionCause
FROM ExecutionResult er
WHERE er.testOutcome = 'FAIL'
ORDER BY er.startTime DESC
LIMIT 50;
```

### Get performance metrics
```sql
SELECT
    erd.url,
    AVG(erd.responseTime) as avg_response,
    MAX(erd.responseTime) as max_response,
    AVG(erd.latency) as avg_latency,
    COUNT(*) as request_count
FROM ExecutionResponseData erd
GROUP BY erd.url
ORDER BY avg_response DESC
LIMIT 20;
```

### Get analytics by page
```sql
SELECT
    page, pageStatus,
    COUNT(*) as element_count,
    COUNT(DISTINCT element) as unique_elements
FROM AnalyticsData
GROUP BY page, pageStatus
ORDER BY element_count DESC;
```
