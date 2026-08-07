# Yarn Quality Master - Quick API Testing Guide

## Prerequisites

1. ✅ Backend running: `uvicorn src.main:app --reload --host 0.0.0.0 --port 8000`
2. ✅ Database migration executed: `dbqueries/create_yarn_quality_tables.sql`
3. ✅ Test data inserted (optional, use curl commands below)

---

## Testing Tools

Choose your preferred tool:
- **curl** (command line)
- **Postman** (GUI - recommended for beginners)
- **Thunder Client** (VS Code extension)
- **HTTPie** (modern curl alternative)

---

## 1. Create Setup - Get Yarn Types for Dropdown

**Endpoint:** `GET /api/masters/yarn_quality_create_setup`

### curl
```bash
curl -X GET "http://localhost:8000/api/masters/yarn_quality_create_setup?co_id=1"
```

### Postman
1. Create new request
2. Method: GET
3. URL: `http://localhost:8000/api/masters/yarn_quality_create_setup?co_id=1`
4. Click Send

### Expected Response (200 OK)
```json
{
  "data": {
    "yarn_types": [
      {
        "jute_yarn_type_id": 1,
        "jute_yarn_type_name": "Type A",
        "co_id": 1,
        "updated_by": 1,
        "updated_date_time": "2025-01-15T10:00:00"
      }
    ]
  }
}
```

### Error Cases
- **400 Bad Request** - Missing `co_id` parameter
- **500 Server Error** - Database tables not created

---

## 2. List Yarn Qualities

**Endpoint:** `GET /api/masters/yarn_quality_table`

### curl
```bash
# Basic list
curl -X GET "http://localhost:8000/api/masters/yarn_quality_table?co_id=1&page=1&page_size=20"

# With search
curl -X GET "http://localhost:8000/api/masters/yarn_quality_table?co_id=1&search=YQ001&page=1&page_size=20"

# With branch filter
curl -X GET "http://localhost:8000/api/masters/yarn_quality_table?co_id=1&branch_id=1&page=1&page_size=20"
```

### Expected Response (200 OK)
```json
{
  "data": [
    {
      "yarn_quality_id": 1,
      "quality_code": "YQ001",
      "jute_yarn_type_id": 1,
      "yarn_type_name": "Type A",
      "twist_per_inch": 25.5,
      "std_count": 100.0,
      "std_doff": 10,
      "std_wt_doff": 50.0,
      "is_active": 1,
      "branch_id": 1,
      "co_id": 1,
      "updated_by": 1,
      "updated_date_time": "2025-01-15T10:00:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

### Query Parameters
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| co_id | integer | Yes | Company ID |
| page | integer | No | Page number (default: 1) |
| page_size | integer | No | Records per page (default: 20) |
| branch_id | integer | No | Filter by branch |
| search | string | No | Search quality_code or yarn_type_name |

---

## 3. Create Yarn Quality

**Endpoint:** `POST /api/masters/yarn_quality_create`

### curl
```bash
curl -X POST "http://localhost:8000/api/masters/yarn_quality_create" \
  -H "Content-Type: application/json" \
  -d '{
    "co_id": 1,
    "quality_code": "YQ001",
    "jute_yarn_type_id": 1,
    "twist_per_inch": 25.5,
    "std_count": 100,
    "std_doff": 10,
    "std_wt_doff": 50.0,
    "is_active": 1,
    "branch_id": 1
  }'
```

### Postman
1. Method: POST
2. URL: `http://localhost:8000/api/masters/yarn_quality_create`
3. Headers: `Content-Type: application/json`
4. Body (raw JSON):
```json
{
  "co_id": 1,
  "quality_code": "YQ001",
  "jute_yarn_type_id": 1,
  "twist_per_inch": 25.5,
  "std_count": 100,
  "std_doff": 10,
  "std_wt_doff": 50.0,
  "is_active": 1,
  "branch_id": 1
}
```

### Expected Response (201 Created)
```json
{
  "message": "Yarn quality created successfully",
  "yarn_quality_id": 1
}
```

### Error Cases
- **400 Bad Request** - Missing required fields (quality_code, jute_yarn_type_id)
- **409 Conflict** - Duplicate quality_code for same company
- **500 Server Error** - Database error (check tables exist)

---

## 4. Edit Setup - Get Current Data for Editing

**Endpoint:** `GET /api/masters/yarn_quality_edit_setup`

### curl
```bash
curl -X GET "http://localhost:8000/api/masters/yarn_quality_edit_setup?co_id=1&yarn_quality_id=1"
```

### Expected Response (200 OK)
```json
{
  "data": {
    "yarn_quality_details": {
      "yarn_quality_id": 1,
      "quality_code": "YQ001",
      "jute_yarn_type_id": 1,
      "yarn_type_name": "Type A",
      "twist_per_inch": 25.5,
      "std_count": 100.0,
      "std_doff": 10,
      "std_wt_doff": 50.0,
      "is_active": 1,
      "branch_id": 1,
      "co_id": 1,
      "updated_by": 1,
      "updated_date_time": "2025-01-15T10:00:00"
    },
    "yarn_types": [
      {
        "jute_yarn_type_id": 1,
        "jute_yarn_type_name": "Type A",
        "co_id": 1,
        "updated_by": 1,
        "updated_date_time": "2025-01-15T10:00:00"
      }
    ]
  }
}
```

### Error Cases
- **400 Bad Request** - Missing co_id or yarn_quality_id
- **404 Not Found** - Yarn quality record not found
- **500 Server Error** - Database error

---

## 5. View Yarn Quality Details

**Endpoint:** `GET /api/masters/yarn_quality_view`

### curl
```bash
curl -X GET "http://localhost:8000/api/masters/yarn_quality_view?co_id=1&yarn_quality_id=1"
```

### Expected Response (200 OK)
```json
{
  "data": {
    "yarn_quality_id": 1,
    "quality_code": "YQ001",
    "jute_yarn_type_id": 1,
    "yarn_type_name": "Type A",
    "twist_per_inch": 25.5,
    "std_count": 100.0,
    "std_doff": 10,
    "std_wt_doff": 50.0,
    "is_active": 1,
    "branch_id": 1,
    "co_id": 1,
    "updated_by": 1,
    "updated_date_time": "2025-01-15T10:00:00"
  }
}
```

---

## 6. Update Yarn Quality

**Endpoint:** `PUT/POST /api/masters/yarn_quality_edit`

### curl
```bash
curl -X POST "http://localhost:8000/api/masters/yarn_quality_edit" \
  -H "Content-Type: application/json" \
  -d '{
    "yarn_quality_id": 1,
    "co_id": 1,
    "quality_code": "YQ001_UPDATED",
    "jute_yarn_type_id": 2,
    "twist_per_inch": 26.0,
    "std_count": 110,
    "std_doff": 11,
    "std_wt_doff": 55.0,
    "is_active": 1
  }'
```

### Postman
1. Method: POST (or PUT)
2. URL: `http://localhost:8000/api/masters/yarn_quality_edit`
3. Body (raw JSON):
```json
{
  "yarn_quality_id": 1,
  "co_id": 1,
  "quality_code": "YQ001_UPDATED",
  "jute_yarn_type_id": 2,
  "twist_per_inch": 26.0,
  "std_count": 110,
  "std_doff": 11,
  "std_wt_doff": 55.0,
  "is_active": 1
}
```

### Expected Response (200 OK)
```json
{
  "data": {
    "message": "Yarn quality updated successfully",
    "yarn_quality_id": 1
  }
}
```

### Error Cases
- **400 Bad Request** - Missing yarn_quality_id
- **404 Not Found** - Yarn quality not found
- **409 Conflict** - Duplicate quality_code
- **500 Server Error** - Database error

---

## Testing Sequence

Follow this order to thoroughly test the API:

### 1. Setup Phase
```bash
# Check if yarn types exist
curl "http://localhost:8000/api/masters/yarn_quality_create_setup?co_id=1"

# If empty, insert test yarn type first (MySQL):
# INSERT INTO jute_yarn_type_mst (jute_yarn_type_name, co_id, updated_by, updated_date_time)
# VALUES ('Standard', 1, 1, NOW());
```

### 2. CRUD Testing
```bash
# 1. List (should be empty initially)
curl "http://localhost:8000/api/masters/yarn_quality_table?co_id=1"

# 2. Create
curl -X POST "http://localhost:8000/api/masters/yarn_quality_create" \
  -H "Content-Type: application/json" \
  -d '{
    "co_id": 1,
    "quality_code": "TEST001",
    "jute_yarn_type_id": 1,
    "twist_per_inch": 25.5,
    "std_count": 100,
    "std_doff": 10,
    "std_wt_doff": 50.0,
    "is_active": 1
  }'
# Note the returned yarn_quality_id (e.g., 1)

# 3. View (use the ID from create response)
curl "http://localhost:8000/api/masters/yarn_quality_view?co_id=1&yarn_quality_id=1"

# 4. Edit Setup
curl "http://localhost:8000/api/masters/yarn_quality_edit_setup?co_id=1&yarn_quality_id=1"

# 5. Edit
curl -X POST "http://localhost:8000/api/masters/yarn_quality_edit" \
  -H "Content-Type: application/json" \
  -d '{
    "yarn_quality_id": 1,
    "co_id": 1,
    "quality_code": "TEST001_UPDATED",
    "jute_yarn_type_id": 1,
    "twist_per_inch": 26.0
  }'

# 6. List again (should show updated record)
curl "http://localhost:8000/api/masters/yarn_quality_table?co_id=1"
```

### 3. Error Testing
```bash
# Missing required parameter
curl "http://localhost:8000/api/masters/yarn_quality_create_setup"
# Expected: 400 Bad Request

# Duplicate code
curl -X POST "http://localhost:8000/api/masters/yarn_quality_create" \
  -H "Content-Type: application/json" \
  -d '{"co_id": 1, "quality_code": "TEST001", ...}'
# Expected: 409 Conflict

# Record not found
curl "http://localhost:8000/api/masters/yarn_quality_view?co_id=1&yarn_quality_id=999"
# Expected: 404 Not Found
```

---

## Postman Collection Template

Create a Postman collection with these requests:

```json
{
  "info": { "name": "Yarn Quality Master", "version": "1.0" },
  "item": [
    {
      "name": "1. Create Setup",
      "request": {
        "method": "GET",
        "url": "http://localhost:8000/api/masters/yarn_quality_create_setup?co_id=1"
      }
    },
    {
      "name": "2. List",
      "request": {
        "method": "GET",
        "url": "http://localhost:8000/api/masters/yarn_quality_table?co_id=1&page=1&page_size=20"
      }
    },
    {
      "name": "3. Create",
      "request": {
        "method": "POST",
        "url": "http://localhost:8000/api/masters/yarn_quality_create",
        "header": [{"key": "Content-Type", "value": "application/json"}],
        "body": {
          "mode": "raw",
          "raw": "{...}"
        }
      }
    }
  ]
}
```

---

## Troubleshooting

### 500 Error: "Table doesn't exist"
**Solution:** Run database migration
```bash
mysql -u <user> -p <db> < dbqueries/create_yarn_quality_tables.sql
```

### 400 Error: "Missing co_id"
**Solution:** Add co_id to query parameters
```bash
# Wrong
curl "http://localhost:8000/api/masters/yarn_quality_table"

# Correct
curl "http://localhost:8000/api/masters/yarn_quality_table?co_id=1"
```

### 404 Error: "Yarn quality not found"
**Solution:** Verify the ID exists first
```bash
# List all records
curl "http://localhost:8000/api/masters/yarn_quality_table?co_id=1"

# Then use a valid ID from the list
curl "http://localhost:8000/api/masters/yarn_quality_view?co_id=1&yarn_quality_id=<valid_id>"
```

### 409 Error: "Quality code already exists"
**Solution:** Use a unique quality_code for your company
```bash
# Check existing codes
curl "http://localhost:8000/api/masters/yarn_quality_table?co_id=1"

# Use a different code in create request
{
  "quality_code": "UNIQUE_CODE_001",
  ...
}
```

---

## Performance Tips

1. **Use pagination** to avoid loading all records
   ```bash
   ?page=1&page_size=50  # Load 50 records per page
   ```

2. **Use search** to narrow down results
   ```bash
   ?search=YQ  # Only records with "YQ" in code
   ```

3. **Use filters** to exclude unwanted results
   ```bash
   ?branch_id=1  # Only records from branch 1
   ```

---

## Next Steps After Testing

1. ✅ All endpoints returning correct responses
2. ✅ Error handling working properly
3. ✅ Data persisting to database
4. **Next:** Test frontend integration
   - Open UI in browser
   - Create/edit/view through web interface
   - Verify data syncs with API

---

**Last Updated:** 2025-01-15
**API Status:** ✅ Ready for Testing
