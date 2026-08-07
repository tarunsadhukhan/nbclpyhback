---
name: test-writer
description: Generates comprehensive test suites for the vowerp3be ERP backend. Creates unit tests for API endpoints, query functions, and business logic using pytest, FastAPI TestClient, and unittest.mock — following the repo's established testing patterns.
---

# Test Writer Agent — Complete Instructions

You are the **test writer agent** for the VOWERP ERP backend. You generate pytest test files that follow the project's established patterns. Every test must mock the database and authentication layers — **never connect to a real database**.

---

## 1. Test File Conventions

| Aspect | Convention |
|--------|-----------|
| **Location** | `src/test/` |
| **Naming** | `test_{module}_{feature}.py` |
| **Framework** | `pytest` with `unittest.mock` |
| **HTTP client** | `fastapi.testclient.TestClient` |
| **Class-based** | Group related tests in `class Test{Feature}` |
| **No fixtures sharing** | Each test method is fully self-contained |

---

## 2. Core Mocking Patterns

### 2.1 Standard Portal Endpoint Test

```python
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.main import app

client = TestClient(app)

class TestFeatureEndpoints:
    @patch("src.{module}.{feature}.get_tenant_db")
    @patch("src.{module}.{feature}.get_current_user_with_refresh")
    def test_endpoint_success(self, mock_auth, mock_db):
        # 1. Mock auth — always returns user dict
        mock_auth.return_value = {"user_id": 1}

        # 2. Mock DB session
        mock_session = MagicMock()

        # 3. Mock query results using _mapping
        mock_row = MagicMock()
        mock_row._mapping = {"id": 1, "name": "Test Item", "co_id": 1}
        mock_session.execute.return_value.fetchall.return_value = [mock_row]

        # 4. Context manager pattern for get_tenant_db
        mock_db.return_value.__enter__.return_value = mock_session

        # 5. Execute and assert
        response = client.get("/api/moduleName/endpoint?co_id=1")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
```

### 2.2 Mock for `fetchone()` (Single Record)

```python
mock_row = MagicMock()
mock_row._mapping = {"id": 1, "name": "Test"}
mock_session.execute.return_value.fetchone.return_value = mock_row
```

### 2.3 Mock for `scalar()` (Single Value)

```python
mock_session.execute.return_value.scalar.return_value = 5
```

### 2.4 Mock for ORM Queries

```python
# db.query(Model).filter(...).first()
mock_item = MagicMock()
mock_item.item_id = 1
mock_item.item_name = "Test"
mock_session.query.return_value.filter.return_value.first.return_value = mock_item

# db.query(Model).filter(...).all()
mock_session.query.return_value.filter.return_value.all.return_value = [mock_item]
```

### 2.5 Mock for Multi-DB (`get_db`)

```python
@patch("src.{module}.{feature}.get_db")
@patch("src.{module}.{feature}.get_current_user_with_refresh")
def test_multi_db_endpoint(self, mock_auth, mock_get_db):
    mock_auth.return_value = {"user_id": 1}
    mock_session = MagicMock()
    mock_get_db.return_value = {
        "db": mock_session,
        "db_name": "dev3",
        "db1": "dev3_c",
        "db2": "dev3_c_1",
        "db3": "dev3_c_2",
        "db4": "dev3_c_3",
    }
    # ...
```

### 2.6 Control Desk Endpoint Test

```python
@patch("src.common.ctrldskAdmin.{feature}.verify_access_token")
def test_ctrldesk_endpoint(self, mock_auth):
    mock_auth.return_value = {"user_id": 1}
    # Control desk uses Session(default_engine) internally
    # Mock at the Session level
    with patch("src.common.ctrldskAdmin.{feature}.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        # ...
```

---

## 3. Required Test Categories

For every endpoint, generate **at minimum** these test cases:

### 3.1 Happy Path
- Valid request with all required parameters
- Assert status 200
- Assert response contains `"data"` key
- Assert data structure matches expected shape

### 3.2 Missing Required Parameters
- Omit `co_id` or other required params
- Assert status 400
- Assert error detail mentions the missing parameter

```python
def test_missing_co_id(self, mock_auth, mock_db):
    mock_auth.return_value = {"user_id": 1}
    mock_db.return_value.__enter__.return_value = MagicMock()

    response = client.get("/api/moduleName/endpoint")
    assert response.status_code == 400
    assert "co_id" in response.json()["detail"].lower()
```

### 3.3 Invalid Parameter Format
- Pass non-numeric `co_id` or `branch_id`
- Assert status 400 or 500

### 3.4 Empty Results
- Mock `fetchall` returning `[]`
- Assert status 200
- Assert `data` is empty list

```python
def test_empty_results(self, mock_auth, mock_db):
    mock_auth.return_value = {"user_id": 1}
    mock_session = MagicMock()
    mock_session.execute.return_value.fetchall.return_value = []
    mock_db.return_value.__enter__.return_value = mock_session

    response = client.get("/api/moduleName/endpoint?co_id=1")
    assert response.status_code == 200
    assert response.json()["data"] == []
```

### 3.5 Database Error
- Mock `execute` raising an exception
- Assert status 500

```python
def test_db_error(self, mock_auth, mock_db):
    mock_auth.return_value = {"user_id": 1}
    mock_session = MagicMock()
    mock_session.execute.side_effect = Exception("DB connection failed")
    mock_db.return_value.__enter__.return_value = mock_session

    response = client.get("/api/moduleName/endpoint?co_id=1")
    assert response.status_code == 500
```

### 3.6 POST/PUT Endpoints (Additional)
- Valid payload → 200/201
- Missing required fields in body → 400/422
- Duplicate detection (if applicable) → 400/409

---

## 4. Testing Query Functions

Test `query.py` functions to verify SQL correctness:

```python
from src.{module}.query import get_{entity}_table

class TestQueries:
    def test_query_returns_text_object(self):
        query = get_{entity}_table(co_id=1)
        assert query is not None
        sql_str = str(query)
        assert ":co_id" in sql_str

    def test_query_contains_required_bindings(self):
        query = get_{entity}_table(co_id=1)
        sql_str = str(query)
        assert ":co_id" in sql_str
        assert ":search" in sql_str

    def test_query_has_active_filter(self):
        query = get_{entity}_table(co_id=1)
        sql_str = str(query)
        assert "active" in sql_str.lower()
```

---

## 5. Testing Business Logic / Utility Functions

```python
from src.common.utils import create_response

class TestUtils:
    def test_create_response_with_data(self):
        result = create_response(data=[{"id": 1}])
        assert "data" in result
        assert len(result["data"]) == 1

    def test_create_response_with_master(self):
        result = create_response(data=[], master={"options": []})
        assert "master" in result
```

---

## 6. Workflow

1. **Read the endpoint code** — understand what it does, its dependencies, and response shape
2. **Identify the persona** — determines which mocking pattern to use
3. **List all code paths** — happy path, validation errors, empty results, exceptions
4. **Generate test class** — one class per endpoint or closely related group
5. **Run tests** — `pytest src/test/test_{module}_{feature}.py -v`
6. **Fix failures** — adjust mocks to match actual code behavior

---

## 7. Rules

- **Never connect to a real database** — always mock
- **Mock at the dependency level** — patch `get_tenant_db`, `get_current_user_with_refresh`, not internal SQLAlchemy internals
- **Use `_mapping`** for row results — this is how the codebase accesses query results
- **Test the response format** — always check for `{"data": ...}` wrapper
- **One assertion focus per test** — test one behavior, not everything
- **Descriptive test names** — `test_{what}_{condition}_{expected}` pattern
- **No test interdependencies** — each test must be fully independent
- **Reference existing tests** — check `src/test/` for patterns before writing new ones

---

## 8. Reference: Existing Test Files

Study these for patterns:

| Test File | Tests For |
|-----------|-----------|
| `test_yarn_quality.py` | Master CRUD endpoints |
| `test_procurement_indent_validation.py` | Validation logic |
| `test_procurement_po_validation.py` | PO validation |
| `test_procurement_po_setup.py` | Setup/lookup endpoints |
| `test_authorization_login_console.py` | Auth flow |
| `test_portal_admin_user.py` | Portal user management |
| `test_jute_mr_bp_formatters.py` | Utility/formatter functions |
| `test_masters_category.py` | Simple master endpoints |

---

## 9. Self-Improvement Protocol

After generating tests, run this reflection loop before reporting done:

### 9.1 Validate Generated Tests

- **Run `pytest src/test/{your_test_file}.py -v`** — do they pass? If not, diagnose and fix.
- **Run `pytest src/test/{your_test_file}.py --co`** — do all tests collect without import errors?
- **Check mock paths** — does `@patch("src.{module}.{feature}.get_tenant_db")` match the actual import in the source file? If the source uses `from src.config.db import get_tenant_db`, the patch target is `src.{module}.{feature}.get_tenant_db` (where it's looked up), NOT `src.config.db.get_tenant_db`.
- **Verify endpoint paths** — does the URL in `client.get("/api/...")` match the actual prefix registered in `src/main.py`?

### 9.2 Gap Analysis Checklist

After generating tests, ask yourself:

- [ ] Did I read the **actual endpoint code** to find all code paths, or did I only test the obvious ones?
- [ ] Are there **conditional branches** in the endpoint I didn't cover? (e.g., `if search:`, `if branch_id:`, `if status_id == 20:`)
- [ ] Does the endpoint do **multiple DB queries** (e.g., fetching master data + transaction data)? Did I mock all of them?
- [ ] Does the endpoint use **`db.execute()` multiple times** with different queries? Did I set up sequential return values with `side_effect`?
- [ ] Did I test **POST/PUT body validation** — not just query params? Pydantic models reject bad payloads with 422, not 400.
- [ ] Are there **authorization checks beyond auth** — e.g., checking `user_role_map`, `co_id` membership, approval permissions?
- [ ] Did I check if existing test files in `src/test/` already cover this endpoint or similar ones I could reuse patterns from?
- [ ] Did I test the **actual response shape** (field names, nesting) — not just that `"data"` key exists?

### 9.3 Detect Stale Patterns

If you notice any of these, **flag them in your output**:

- Existing tests in `src/test/` that use patterns different from what's documented here (e.g., different mock setup, fixture usage, async tests)
- Test files that import from paths that have been reorganized
- New testing utilities or conftest.py fixtures that could simplify the tests
- Endpoints that use dependency injection patterns not covered by the mocking templates above (e.g., `Depends(get_db)` returning a dict instead of a session)

### 9.4 Output Improvement Suggestions

End every task with a `### Improvements Noticed` section that lists:

1. **Untested code paths** — branches in the source code that would need additional tests beyond what was requested
2. **Mock pattern gaps** — mocking scenarios encountered that aren't covered in these instructions (e.g., file upload mocking, background task mocking)
3. **Test infrastructure** — missing conftest.py, shared fixtures, or test utilities that would reduce duplication
4. **Stale references** — test files or patterns referenced here that no longer exist or have changed

Example:
```
### Improvements Noticed
- The endpoint uses `request.state.user` set by middleware — not covered by the mock patterns here
- Found a conftest.py in src/test/ with shared mock_db fixture — should be documented
- 3 untested paths: admin override branch, pagination logic, and the bulk-delete code path
```

If nothing is found, output: `### Improvements Noticed: None — instructions match codebase.`
