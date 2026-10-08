---
name: reportportal-api
description: Query and interact with ReportPortal API for test results, launches, test items, logs, and analytics. Use when working with ReportPortal data, building dashboards, analyzing test trends, or integrating with test management.
---

# ReportPortal API Integration

This skill provides knowledge for working with the ReportPortal API to query test results, launches, and analytics.

## ReportPortal API Overview

ReportPortal is a test results aggregation and analysis platform. The API follows REST conventions with JWT authentication.

## Authentication

### API Token
Users generate API tokens in ReportPortal UI: User Profile → API Keys

### Request Headers
```
Authorization: Bearer <api_token>
Content-Type: application/json
```

### Python Client Setup
```python
import requests

class ReportPortalClient:
    def __init__(self, base_url: str, token: str, project: str):
        self.base_url = base_url.rstrip('/')
        self.project = project
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        })

    def _url(self, endpoint: str) -> str:
        return f'{self.base_url}/api/v1/{self.project}/{endpoint}'

    def get(self, endpoint: str, params: dict = None) -> dict:
        response = self.session.get(self._url(endpoint), params=params)
        response.raise_for_status()
        return response.json()
```

## Core API Endpoints

### Projects
```
GET /api/v1/project/list
GET /api/v1/project/{projectName}
```

### Launches

**List Launches (paginated)**
```
GET /api/v1/{project}/launch
```

Query Parameters:
- `page.page` - Page number (0-based)
- `page.size` - Items per page (default 20)
- `page.sort` - Sort field (e.g., `startTime,DESC`)
- `filter.eq.name` - Filter by name
- `filter.btw.startTime` - Date range filter

Example:
```python
def get_launches(self, page: int = 0, size: int = 20) -> dict:
    return self.get('launch', params={
        'page.page': page,
        'page.size': size,
        'page.sort': 'startTime,DESC'
    })
```

**Get Launch by ID**
```
GET /api/v1/{project}/launch/{launchId}
```

**Get Launch Statistics**
```
GET /api/v1/{project}/launch/{launchId}/statistics
```

Response:
```json
{
  "executions": {
    "total": 100,
    "passed": 85,
    "failed": 10,
    "skipped": 5
  },
  "defects": {
    "product_bug": {"total": 3},
    "automation_bug": {"total": 2},
    "system_issue": {"total": 1},
    "to_investigate": {"total": 4}
  }
}
```

### Test Items

**List Test Items**
```
GET /api/v1/{project}/item
```

Query Parameters:
- `filter.eq.launchId` - Filter by launch
- `filter.eq.type` - Filter by type (SUITE, TEST, STEP)
- `filter.eq.status` - Filter by status (PASSED, FAILED, SKIPPED)
- `filter.has.attributeKey` - Filter by attribute

Example:
```python
def get_failed_tests(self, launch_id: int) -> dict:
    return self.get('item', params={
        'filter.eq.launchId': launch_id,
        'filter.eq.status': 'FAILED',
        'page.size': 100
    })
```

**Get Test Item by ID**
```
GET /api/v1/{project}/item/{itemId}
```

**Get Test Item History**
```
GET /api/v1/{project}/item/history
```

### Logs

**Get Logs for Test Item**
```
GET /api/v1/{project}/log
```

Query Parameters:
- `filter.eq.item` - Test item ID
- `filter.eq.level` - Log level (ERROR, WARN, INFO, DEBUG)

Example:
```python
def get_error_logs(self, item_id: int) -> dict:
    return self.get('log', params={
        'filter.eq.item': item_id,
        'filter.in.level': 'ERROR,WARN',
        'page.size': 50
    })
```

### Widgets & Dashboards

**Get Dashboard**
```
GET /api/v1/{project}/dashboard/{dashboardId}
```

**Get Widget Data**
```
GET /api/v1/{project}/widget/{widgetId}
```

## Common Queries

### Get Latest Launch
```python
def get_latest_launch(self) -> dict:
    result = self.get('launch', params={
        'page.size': 1,
        'page.sort': 'startTime,DESC'
    })
    return result['content'][0] if result['content'] else None
```

### Get Launches by Date Range
```python
from datetime import datetime, timedelta

def get_launches_last_week(self) -> dict:
    end = datetime.now()
    start = end - timedelta(days=7)
    return self.get('launch', params={
        'filter.btw.startTime': f'{int(start.timestamp()*1000)},{int(end.timestamp()*1000)}',
        'page.size': 100
    })
```

### Get Flaky Tests (failed then passed)
```python
def get_flaky_tests(self, launch_ids: list) -> list:
    # Get test history for multiple launches
    flaky = []
    for launch_id in launch_ids:
        items = self.get('item', params={
            'filter.eq.launchId': launch_id,
            'filter.eq.type': 'TEST'
        })
        # Compare with previous results...
    return flaky
```

### Calculate Pass Rate
```python
def calculate_pass_rate(self, launch_id: int) -> float:
    stats = self.get(f'launch/{launch_id}')
    total = stats['statistics']['executions']['total']
    passed = stats['statistics']['executions']['passed']
    return (passed / total * 100) if total > 0 else 0
```

## Filter Syntax

ReportPortal uses a specific filter syntax:

| Condition | Syntax | Example |
|-----------|--------|---------|
| Equals | `filter.eq.field` | `filter.eq.status=FAILED` |
| Not Equals | `filter.ne.field` | `filter.ne.status=PASSED` |
| Contains | `filter.cnt.field` | `filter.cnt.name=login` |
| In | `filter.in.field` | `filter.in.status=FAILED,SKIPPED` |
| Between | `filter.btw.field` | `filter.btw.startTime=1234,5678` |
| Greater | `filter.gt.field` | `filter.gt.startTime=1234` |
| Less | `filter.lt.field` | `filter.lt.endTime=5678` |
| Has Attribute | `filter.has.attributeKey` | `filter.has.browser` |

## Error Handling

```python
from requests.exceptions import HTTPError

class ReportPortalError(Exception):
    pass

class AuthenticationError(ReportPortalError):
    pass

class NotFoundError(ReportPortalError):
    pass

def handle_response(response):
    try:
        response.raise_for_status()
    except HTTPError as e:
        if response.status_code == 401:
            raise AuthenticationError('Invalid API token')
        elif response.status_code == 404:
            raise NotFoundError('Resource not found')
        else:
            raise ReportPortalError(f'API error: {e}')
    return response.json()
```

## Pagination Helper

```python
def get_all_pages(self, endpoint: str, params: dict = None) -> list:
    """Fetch all pages of a paginated endpoint."""
    params = params or {}
    params['page.page'] = 0
    params['page.size'] = 100

    all_items = []
    while True:
        result = self.get(endpoint, params)
        all_items.extend(result.get('content', []))

        page_info = result.get('page', {})
        if page_info.get('number', 0) >= page_info.get('totalPages', 1) - 1:
            break
        params['page.page'] += 1

    return all_items
```

## References

- ReportPortal API Documentation: `https://<your-instance>/api`
- Swagger UI available at: `https://<your-instance>/api/swagger-ui.html`
