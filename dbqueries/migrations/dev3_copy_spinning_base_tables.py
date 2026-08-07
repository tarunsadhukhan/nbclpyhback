#!/usr/bin/env python3
"""Copy missing spinning base-table schemas from sls -> dev3.

The spinning feature reuses several "base" tables that already exist in sls (the
mature tenant) but may be missing in dev3 (the sandbox tenant). For each base
table this script:
  1. checks whether it exists in dev3;
  2. if missing, runs SHOW CREATE TABLE on sls;
  3. creates the same table (structure only, no data) in dev3.

Credentials are read from env/database.env (DATABASE_USER / DATABASE_PASSWORD /
DATABASE_HOST / DATABASE_PORT). The two tenant database names (sls, dev3) are
hardcoded below since database.env only carries DATABASE_DEFAULT=vowconsole3.

DRY-RUN BY DEFAULT: prints what it would do. Pass --apply to actually create
the missing tables in dev3.

Usage:
    python dev3_copy_spinning_base_tables.py            # dry run
    python dev3_copy_spinning_base_tables.py --apply    # create missing tables

stdlib + pymysql only.
"""

import os
import sys

import pymysql

# Source (mature tenant) and target (sandbox tenant) databases.
SOURCE_DB = "sls"
TARGET_DB = "dev3"

# Base tables the spinning feature reuses. Order is informational only — each is
# created independently (no FK dependencies are copied by SHOW CREATE TABLE here).
BASE_TABLES = [
    "daily_doff_tbl",
    "daily_doff_frames_winding",
    "trolly_mst",
    "spinning_quality_mst",
    "spinning_type_mst",
    "daily_attendance",
    "daily_ebmc_attendance",
    "hrms_ed_personal_details",
    "hrms_ed_official_details",
    "designation_mst",
]


def _find_env_file():
    """Locate env/database.env relative to this script (…/dbqueries/migrations/)."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", ".."))
    candidate = os.path.join(repo_root, "env", "database.env")
    if not os.path.exists(candidate):
        print(f"ERROR: could not find env file at {candidate}", file=sys.stderr)
        sys.exit(1)
    return candidate


def load_db_credentials():
    """Parse env/database.env for the credential variable names."""
    env_path = _find_env_file()
    creds = {}
    with open(env_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            creds[key.strip()] = value.strip()
    user = creds.get("DATABASE_USER")
    password = creds.get("DATABASE_PASSWORD")
    host = creds.get("DATABASE_HOST")
    port = int(creds.get("DATABASE_PORT", "3306"))
    if not all([user, password, host]):
        print("ERROR: DATABASE_USER / DATABASE_PASSWORD / DATABASE_HOST missing from database.env",
              file=sys.stderr)
        sys.exit(1)
    return {"user": user, "password": password, "host": host, "port": port}


def connect(creds, database):
    return pymysql.connect(
        host=creds["host"],
        port=creds["port"],
        user=creds["user"],
        password=creds["password"],
        database=database,
    )


def table_exists(conn, table_name):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            """,
            (table_name,),
        )
        return cur.fetchone()[0] > 0


def get_create_table_sql(conn, table_name):
    with conn.cursor() as cur:
        cur.execute(f"SHOW CREATE TABLE `{table_name}`")
        row = cur.fetchone()
        # SHOW CREATE TABLE returns (table_name, "CREATE TABLE ...")
        return row[1] if row else None


def main():
    apply_changes = "--apply" in sys.argv[1:]
    mode = "APPLY" if apply_changes else "DRY-RUN"
    print(f"=== dev3_copy_spinning_base_tables ({mode}) ===")
    print(f"Source: {SOURCE_DB}   Target: {TARGET_DB}\n")

    creds = load_db_credentials()
    src_conn = connect(creds, SOURCE_DB)
    tgt_conn = connect(creds, TARGET_DB)

    created = []
    skipped_present = []
    missing_in_source = []

    try:
        for table in BASE_TABLES:
            if table_exists(tgt_conn, table):
                skipped_present.append(table)
                print(f"[ OK     ] {table}: already present in {TARGET_DB}")
                continue

            if not table_exists(src_conn, table):
                missing_in_source.append(table)
                print(f"[ MISSING] {table}: NOT found in {SOURCE_DB} either — cannot copy")
                continue

            create_sql = get_create_table_sql(src_conn, table)
            if not create_sql:
                missing_in_source.append(table)
                print(f"[ MISSING] {table}: SHOW CREATE TABLE returned nothing in {SOURCE_DB}")
                continue

            if apply_changes:
                with tgt_conn.cursor() as cur:
                    cur.execute(create_sql)
                tgt_conn.commit()
                created.append(table)
                print(f"[ CREATED] {table}: created in {TARGET_DB} from {SOURCE_DB} schema")
            else:
                created.append(table)
                print(f"[ WOULD  ] {table}: would create in {TARGET_DB} (schema from {SOURCE_DB})")
    finally:
        src_conn.close()
        tgt_conn.close()

    print("\n--- Summary ---")
    print(f"Already present in {TARGET_DB}: {len(skipped_present)} -> {skipped_present}")
    verb = "Created" if apply_changes else "Would create"
    print(f"{verb} in {TARGET_DB}: {len(created)} -> {created}")
    print(f"Missing in {SOURCE_DB} (skipped): {len(missing_in_source)} -> {missing_in_source}")
    if not apply_changes:
        print("\nDRY-RUN only. Re-run with --apply to create the missing tables.")


if __name__ == "__main__":
    main()
