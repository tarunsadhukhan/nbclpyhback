"""Store a company logo in <tenant>.co_mst.co_logo as a base64 data URI.

Same representation the /companyAdmin/upload_co_logo endpoint writes, so the
sidebar and portal splash pick it up with no other change. Use this for seeding
a tenant directly; day to day, Tenant Admin -> Company Management uploads it.

    python set_co_logo.py nbjcl nbj-logo.png NORTHBROOK

Args: <database> <png path> <substring of co_name to match>.
Dry-run by default -- pass --commit to actually write.
"""
import base64
import os
import sys

import pymysql

HOST = os.environ.get("DATABASE_HOST", "45.58.59.64")
PORT = int(os.environ.get("DATABASE_PORT", "3306"))
USER = os.environ.get("DATABASE_USER", "Tarun")
PASSWORD = os.environ.get("DATABASE_PASSWORD", "")


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--commit"]
    commit = "--commit" in sys.argv
    if len(args) != 3:
        print(__doc__)
        return 2
    database, png_path, name_match = args

    if not PASSWORD:
        print("Set DATABASE_PASSWORD (see pyhback/.env) before running.")
        return 2

    with open(png_path, "rb") as fh:
        raw = fh.read()
    data_uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    print(f"{png_path}: {len(raw)} bytes -> data URI of {len(data_uri)} chars")

    conn = pymysql.connect(host=HOST, port=PORT, user=USER, password=PASSWORD, database=database)
    try:
        cur = conn.cursor()

        # A base64 data URI is tens of KB; the original column was VARCHAR(255),
        # which silently truncates (or errors under strict mode). Widen first.
        cur.execute(
            "select column_type from information_schema.columns "
            "where table_schema=%s and table_name='co_mst' and column_name='co_logo'",
            (database,),
        )
        row = cur.fetchone()
        if row is None:
            print("co_mst.co_logo not found -- wrong database?")
            return 1
        col_type = row[0]
        print(f"co_logo column type: {col_type}")
        if "longtext" not in col_type.lower():
            print("  -> needs ALTER TABLE co_mst MODIFY COLUMN co_logo LONGTEXT NULL")
            if commit:
                cur.execute("ALTER TABLE co_mst MODIFY COLUMN co_logo LONGTEXT NULL")
                print("  -> altered")

        cur.execute(
            "select co_id, co_name, char_length(coalesce(co_logo,'')) from co_mst "
            "where co_name like %s",
            (f"%{name_match}%",),
        )
        matches = cur.fetchall()
        if len(matches) != 1:
            print(f"Expected exactly 1 company matching {name_match!r}, got {len(matches)}:")
            for m in matches:
                print("   ", m)
            return 1

        co_id, co_name, existing_len = matches[0]
        print(f"target: co_id={co_id} co_name={co_name!r} existing co_logo chars={existing_len}")

        if not commit:
            print("\nDRY RUN -- re-run with --commit to write.")
            return 0

        cur.execute("update co_mst set co_logo=%s where co_id=%s", (data_uri, co_id))
        conn.commit()

        cur.execute("select char_length(co_logo) from co_mst where co_id=%s", (co_id,))
        stored = cur.fetchone()[0]
        print(f"stored co_logo chars={stored}")
        if stored != len(data_uri):
            print("MISMATCH -- value was truncated; check the column type.")
            return 1
        print("OK")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
