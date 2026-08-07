"""Parity harness: day-slice weaving query vs vw_weaving_daily on a live tenant DB.

Proves that the output of the production query builder
``get_weaving_entries_by_date_query()`` (the day-slice rewrite) matches the
CURRENT ``vw_weaving_daily`` view row-for-row and column-for-column.

Usage (Windows-friendly, run from repo root):

    python dbqueries/verify_weaving_dayslice_parity.py --database dev3
    python dbqueries/verify_weaving_dayslice_parity.py --database dev3 --dates 2026-06-23,2026-06-24
    python dbqueries/verify_weaving_dayslice_parity.py --host h --port 3306 --user u --password p --database dev3

Connection defaults are read from env/database.env when flags are omitted.
Exit code 0 = full parity, 1 = mismatches found, 2 = setup/usage error.
"""

import argparse
import datetime
import decimal
import os
import sys

# Bootstrap: make `src.` importable when run from anywhere.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from urllib.parse import quote_plus  # noqa: E402

from sqlalchemy import bindparam, create_engine, text  # noqa: E402

from src.juteProduction.weaving_query import get_weaving_entries_by_date_query  # noqa: E402

TOLERANCE = 0.011  # covers ROUND() edge differences between slice and view


def load_env_defaults():
    """Very small key=value parser for env/database.env (skips comments)."""
    defaults = {}
    path = os.path.join(REPO_ROOT, "env", "database.env")
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                defaults[k.strip()] = v.strip()
    return defaults


def parse_args():
    env = load_env_defaults()
    p = argparse.ArgumentParser(
        description="Verify day-slice weaving query parity against vw_weaving_daily."
    )
    p.add_argument("--host", default=env.get("DATABASE_HOST", "localhost"))
    p.add_argument("--port", type=int, default=int(env.get("DATABASE_PORT", 3306)))
    p.add_argument("--user", default=env.get("DATABASE_USER", "root"))
    p.add_argument("--password", default=env.get("DATABASE_PASSWORD", ""))
    p.add_argument(
        "--database",
        required=True,
        help="Target tenant DB (REQUIRED; suggest dev3 for QA parity runs)",
    )
    p.add_argument(
        "--dates",
        default=None,
        help="Comma-separated YYYY-MM-DD list; default = auto-discover all active days",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of (co_id, tran_date) pairs checked (default: all)",
    )
    return p.parse_args()


def values_equal(a, b):
    """None==None; numerics within TOLERANCE; dates str-normalized; rest exact."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    num_types = (int, float, decimal.Decimal)
    if isinstance(a, num_types) and isinstance(b, num_types):
        return abs(float(a) - float(b)) <= TOLERANCE
    if isinstance(a, (datetime.date, datetime.datetime)) or isinstance(
        b, (datetime.date, datetime.datetime)
    ):
        return str(a) == str(b)
    return a == b


def fetch_rows(conn, query, params):
    """Execute; return (dict rows keyed by weaving_daily_id, ordered column keys)."""
    result = conn.execute(query, params)
    keys = list(result.keys())
    rows = {}
    for r in result.fetchall():
        d = dict(r._mapping)
        rows[d["weaving_daily_id"]] = d
    return rows, keys


def build_view_query(columns):
    """Reference SELECT over vw_weaving_daily with the SAME column list + filters.

    Column list is introspected from the dayslice result keys so the two sides
    always compare identical columns even if the builder's SELECT list evolves.
    """
    col_sql = ",\n            ".join("v.%s" % c for c in columns)
    return text(
        """
        SELECT
            %s
        FROM vw_weaving_daily v
        WHERE v.co_id = :co_id
          AND v.tran_date = :tran_date
          AND (:spell_id IS NULL OR v.spell_id = :spell_id)
          AND (:machine_id IS NULL OR v.machine_id = :machine_id)
          AND (:branch_id IS NULL OR v.branch_id = :branch_id OR v.branch_id IS NULL)
        ORDER BY v.mech_code, v.weaving_daily_id DESC
        """
        % col_sql
    )


def compare_pair(slice_rows, view_rows, mismatches, tag):
    """Compare two id-keyed dicts; append (tag, id, column, dayslice_val, view_val)."""
    rows_compared = 0
    slice_ids = set(slice_rows)
    view_ids = set(view_rows)
    for missing in sorted(view_ids - slice_ids):
        mismatches.append((tag, missing, "<row missing in dayslice>", None, "present"))
    for extra in sorted(slice_ids - view_ids):
        mismatches.append((tag, extra, "<extra row in dayslice>", "present", None))
    for rid in sorted(slice_ids & view_ids):
        s, v = slice_rows[rid], view_rows[rid]
        rows_compared += 1
        for col in sorted(set(s) & set(v)):
            if not values_equal(s[col], v[col]):
                mismatches.append((tag, rid, col, s[col], v[col]))
    return rows_compared


def run_check(conn, dayslice_q, co_id, tran_date, spell_id, machine_id, mismatches, tag):
    params = {
        "co_id": co_id,
        "tran_date": tran_date,
        "spell_id": spell_id,
        "machine_id": machine_id,
        "branch_id": None,
    }
    slice_rows, keys = fetch_rows(conn, dayslice_q, params)
    view_rows, _ = fetch_rows(conn, build_view_query(keys), params)
    before = len(mismatches)
    n = compare_pair(slice_rows, view_rows, mismatches, tag)
    status = "PASS" if len(mismatches) == before else "FAIL"
    print(
        "[%s] %s  rows=%d  (dayslice=%d view=%d)"
        % (status, tag, n, len(slice_rows), len(view_rows))
    )
    return n, slice_rows


def main():
    args = parse_args()
    url = "mysql+pymysql://%s:%s@%s:%d/%s" % (
        args.user,
        quote_plus(args.password),
        args.host,
        args.port,
        args.database,
    )
    engine = create_engine(url)
    dayslice_q = get_weaving_entries_by_date_query()
    mismatches = []
    total_rows = 0
    dates_checked = 0
    filter_sample = None  # (co_id, tran_date, spell_id, machine_id) for the filtered re-run

    with engine.connect() as conn:
        if args.dates:
            wanted = [d.strip() for d in args.dates.split(",") if d.strip()]
            pairs = conn.execute(
                text(
                    "SELECT DISTINCT co_id, tran_date FROM jute_prod_weaving_daily "
                    "WHERE active = 1 AND tran_date IN :dates "
                    "ORDER BY co_id, tran_date"
                ).bindparams(bindparam("dates", expanding=True)),
                {"dates": wanted},
            ).fetchall()
        else:
            pairs = conn.execute(
                text(
                    "SELECT DISTINCT co_id, tran_date FROM jute_prod_weaving_daily "
                    "WHERE active = 1 ORDER BY co_id, tran_date"
                )
            ).fetchall()
        if args.limit:
            pairs = pairs[: args.limit]
        if not pairs:
            print("No (co_id, tran_date) pairs to check — jute_prod_weaving_daily empty?")
            sys.exit(2)

        for co_id, tran_date in pairs:
            tag = "co=%s date=%s" % (co_id, tran_date)
            n, slice_rows = run_check(
                conn, dayslice_q, co_id, tran_date, None, None, mismatches, tag
            )
            total_rows += n
            dates_checked += 1
            if filter_sample is None and slice_rows:
                any_row = next(iter(slice_rows.values()))
                filter_sample = (co_id, tran_date, any_row["spell_id"], any_row["machine_id"])

        # Filter parity: re-run one populated day with spell_id + machine_id filters.
        if filter_sample:
            co_id, tran_date, spell_id, machine_id = filter_sample
            n, _ = run_check(
                conn,
                dayslice_q,
                co_id,
                tran_date,
                spell_id,
                machine_id,
                mismatches,
                "FILTERED co=%s date=%s spell=%s mc=%s"
                % (co_id, tran_date, spell_id, machine_id),
            )
            total_rows += n

        # Branch parity: re-run one populated day with a real non-NULL branch_id
        # (reviewer finding: branch predicate moved inside the slice for the
        # entries query; prove filtered-inside == filtered-after-view).
        if filter_sample:
            co_id, tran_date, _, _ = filter_sample
            branch_row = conn.execute(
                text(
                    "SELECT branch_id FROM jute_prod_weaving_daily "
                    "WHERE active = 1 AND co_id = :co_id AND tran_date = :tran_date "
                    "AND branch_id IS NOT NULL LIMIT 1"
                ),
                {"co_id": co_id, "tran_date": tran_date},
            ).fetchone()
            if branch_row:
                branch_id = branch_row[0]
                params = {
                    "co_id": co_id,
                    "tran_date": tran_date,
                    "spell_id": None,
                    "machine_id": None,
                    "branch_id": branch_id,
                }
                tag = "BRANCH co=%s date=%s branch=%s" % (co_id, tran_date, branch_id)
                slice_rows, keys = fetch_rows(conn, dayslice_q, params)
                view_rows, _ = fetch_rows(conn, build_view_query(keys), params)
                before = len(mismatches)
                n = compare_pair(slice_rows, view_rows, mismatches, tag)
                status = "PASS" if len(mismatches) == before else "FAIL"
                print(
                    "[%s] %s  rows=%d  (dayslice=%d view=%d)"
                    % (status, tag, n, len(slice_rows), len(view_rows))
                )
                total_rows += n

    print()
    print(
        "WARNING: plan-driver (planning_grid) composition is NOT oracle-diffed here; "
        "it embeds this same slice branch-UNfiltered (old view-join semantics) and is "
        "pinned structurally by src/test/test_weaving_dayslice.py."
    )

    print()
    print("=" * 60)
    print(
        "Summary: dates=%d  rows_compared=%d  mismatches=%d"
        % (dates_checked, total_rows, len(mismatches))
    )
    if mismatches:
        print("First %d mismatches:" % min(50, len(mismatches)))
        for tag, rid, col, sval, vval in mismatches[:50]:
            print("  [%s] id=%s col=%s dayslice=%r view=%r" % (tag, rid, col, sval, vval))
        sys.exit(1)
    print("PARITY OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
