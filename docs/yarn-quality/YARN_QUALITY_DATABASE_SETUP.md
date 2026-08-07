# Yarn Quality Master - Database Setup

## Critical: Database Tables Must Be Created

The Yarn Quality Master API endpoints require two database tables. Follow these steps to create them in your MySQL database.

## Setup Steps

### 1. Navigate to the Migration Script

Location: `dbqueries/create_yarn_quality_tables.sql`

### 2. Execute in MySQL

**Option A: Using MySQL Command Line**
```bash
# Connect to your MySQL database
mysql -h <host> -u <username> -p <database_name> < dbqueries/create_yarn_quality_tables.sql
```

**Option B: Using MySQL Workbench**
1. Open MySQL Workbench
2. Open File → Open SQL Script → Select `dbqueries/create_yarn_quality_tables.sql`
3. Click Execute (Lightning bolt icon)
4. Check messages for success confirmation

**Option C: Using Docker MySQL Container** (if applicable)
```bash
docker exec <mysql_container_name> mysql -u<username> -p<password> <database> < create_yarn_quality_tables.sql
```

### 3. Verify Tables Were Created

**List tables:**
```sql
SHOW TABLES LIKE '%yarn%';
```

Expected output:
```
+----------------------------------+
| Tables_in_vowconsole3 (yarn%)    |
+----------------------------------+
| jute_yarn_type_mst               |
| yarn_quality_master              |
+----------------------------------+
```

**Check table structure:**
```sql
DESCRIBE jute_yarn_type_mst;
DESCRIBE yarn_quality_master;
```

## What the Migration Creates

### Table 1: jute_yarn_type_mst
Stores yarn type reference data.

**Columns:**
- `jute_yarn_type_id` (INT, Primary Key, Auto Increment)
- `jute_yarn_type_name` (VARCHAR 255)
- `co_id` (INT)
- `updated_by` (INT)
- `updated_date_time` (DATETIME)

**Indexes:**
- Primary Key: `jute_yarn_type_id`
- Unique: `co_id, jute_yarn_type_name` (one name per company)

---

### Table 2: yarn_quality_master
Stores yarn quality specifications.

**Columns:**
- `yarn_quality_id` (INT, Primary Key, Auto Increment)
- `quality_code` (VARCHAR 255)
- `jute_yarn_type_id` (INT, Foreign Key)
- `twist_per_inch` (DECIMAL 10,2)
- `std_count` (DECIMAL 10,2)
- `std_doff` (INT)
- `std_wt_doff` (DECIMAL 10,2)
- `is_active` (TINYINT, Default: 1)
- `branch_id` (INT)
- `co_id` (INT)
- `updated_by` (INT)
- `updated_date_time` (DATETIME)

**Indexes:**
- Primary Key: `yarn_quality_id`
- Unique: `co_id, quality_code` (one code per company)
- Foreign Key: `jute_yarn_type_id` → `jute_yarn_type_mst.jute_yarn_type_id`

---

## Troubleshooting

### Error: "Table already exists"
The tables may already exist in your database. Skip this migration and verify the schema matches the expected structure.

### Error: "Cannot add or update a child row: a foreign key constraint fails"
The foreign key references may be incorrect. Verify:
1. `jute_yarn_type_mst` table exists and has `jute_yarn_type_id` column
2. No data exists yet (for clean install)

### Error: "Unknown database"
Specify the correct database name in the command:
```bash
mysql -h localhost -u root -p <correct_database_name> < create_yarn_quality_tables.sql
```

### Error: "Access denied for user"
Check MySQL credentials are correct.

---

## Testing After Setup

Once tables are created, test the API endpoints:

```bash
# 1. Start the backend
cd /path/to/vowerp3be
source .venv/Scripts/activate
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 2. In another terminal, test the create setup endpoint
curl "http://localhost:8000/api/masters/yarn_quality_create_setup?co_id=1"

# 3. Expected response (if no yarn types exist yet):
{
  "data": {
    "yarn_types": []
  }
}

# 4. If you get this response, the database tables are working correctly!
```

---

## Next Steps

After database setup:

1. **Insert test data** (optional):
   ```sql
   INSERT INTO jute_yarn_type_mst (jute_yarn_type_name, co_id, updated_by, updated_date_time)
   VALUES ('Premium', 1, 1, NOW());
   
   INSERT INTO yarn_quality_master (
     quality_code, jute_yarn_type_id, twist_per_inch, std_count,
     std_doff, std_wt_doff, is_active, co_id, updated_by, updated_date_time
   ) VALUES ('YQ001', 1, 25.5, 100, 10, 50.0, 1, 1, 1, NOW());
   ```

2. **Test all endpoints** - Use the API documented in `YARN_QUALITY_MASTER_SUMMARY.md`

3. **Test frontend** - Navigate to the Yarn Quality Master page in the UI

4. **Run tests** - Execute the test suite:
   ```bash
   pytest src/test/test_yarn_quality.py -v
   ```

---

**Status:** 🔴 Tables not yet created - Run migration now!
**Once completed:** ✅ Ready for API testing
