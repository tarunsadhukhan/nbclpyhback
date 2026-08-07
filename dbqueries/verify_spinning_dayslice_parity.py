"""Parity harness: day-slice spinning query vs vw_spinning_planning_grid on a live tenant DB.

Proves that the output of the production query builder
``get_spinning_planning_slice_query()`` (the day-slice rewrite) matches the
CURRENT ``vw_spinning_planning_grid`` reference oracle view row-for-row and
column-for-column on the key (spell_id, machine_id, item_id).

Deliberate slice-vs-view deltas:
  * the slice adds ``AND bm.co_id = :co_id`` on the driver (tenant safety);
    the oracle side is equally co-filtered by this harness's outer
    ``WHERE co_id = :co_id`` on the view, so the compared key sets align.
  * ORACLE NONDETERMINISM (target-map tie-break): the view (and the legacy
    ``resolve_param`` helper) resolve target-map values with
    ``ORDER BY effective_date DESC LIMIT 1`` — NO tie-break — so two active
    rows sharing the max effective_date (e.g. dev3 machine 16 target speed,
    spng_target_map_id 4=3700 vs 5=3900, both 2026-06-14) make the oracle's
    pick arbitrary. The slice tie-breaks deterministically with
    ``spng_target_map_id DESC`` (latest insert wins). Such mismatches are NOT
    slice bugs: this harness verifies both values against the tied duplicate
    set in jute_prod_spng_target_map and reports them as AMBIGUOUS (exit 0)
    instead of failing. Any value NOT in the tied set still hard-fails.

Column-name mapping (cosmetic, not semantic):
  * the view aliases im.item_code as ``quality_code``; the slice calls it
    ``item_code`` — mapped below.
  * the slice emits ``item_name`` (display-only) which the view lacks, and the
    view emits ``eb_id`` (CAST NULL placeholder) which the slice lacks — only
    the intersection of columns is compared; skipped columns are printed once.

Usage (Windows-friendly, run from repo root):

    python dbqueries/verify_spinning_dayslice_parity.py --database dev3
    python dbqueries/verify_spinning_dayslice_parity.py --database dev3 --dates 2026-07-01,2026-07-02
    python dbqueries/verify_spinning_dayslice_parity.py --host h --port 3306 --user u --password p --database dev3

Connection defaults are read from env/database.env when flags are omitted.
Exit code 0 = full parity (including 0-row runs on empty tenants, with a
warning), 1 = mismatches found, 2 = setup/usage error.
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

from src.juteProduction.spinning_query import get_spinning_planning_slice_query  # noqa: E402

TOLERANCE = 0.011  # covers ROUND() edge differences between slice and view
VIEW = "vw_spinning_planning_grid"
COL_MAP = {"item_code": "quality_code"}  # slice name -> view name
KEY_COLS = ("spell_id", "machine_id", "item_id")

# Target-map-derived columns eligible for the AMBIGUOUS waiver (see docstring):
# col -> (id_type, param, value_role, key index of ref_id in KEY_COLS order)
TM_COLS = {
    "spindles": ("mcid", "spindles", "standard", 1),
    "std_speed": ("mcid", "speed", "standard", 1),
    "actual_speed": ("mcid", "speed", "actual", 1),
    "target_speed": ("mcid", "speed", "target", 1),
    "std_tpi": ("qid", "tpi", "standard", 2),
    "actual_tpi": ("qid", "tpi", "actual", 2),
    "target_tpi": ("qid", "tpi", "target", 2),
    "std_eff": ("qid", "eff", "standard", 2),
    "target_eff": ("qid", "eff", "target", 2),
}

TM_DUP_SQL = text(
    """
    SELECT t.value FROM jute_prod_spng_target_map t
    WHERE t.co_id = :co_id AND t.id_type = :id_type AND t.ref_id = :ref_id
      AND t.param = :param AND t.value_role = :value_role AND t.active = 1
      AND t.effective_date = (
          SELECT MAX(t2.effective_date) FROM jute_prod_spng_target_map t2
          WHERE t2.co_id = :co_id AND t2.id_type = :id_type AND t2.ref_id = :ref_id
            AND t2.param = :param AND t2.value_role = :value_role AND t2.active = 1
            AND t2.effective_date <= :tran_date
      )
    """
)


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
        description="Verify day-slice spinning query parity against vw_spinning_planning_grid."
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
    """Execute; return (dict rows keyed by (spell,machine,item), ordered column keys).

    Duplicate composite keys collapse (last row wins); both sides drive off the
    same frames table so a dup appears on both — warn so it is visible.
    """
    result = conn.execute(query, params)
    keys = list(result.keys())
    rows = {}
    raw = 0
    for r in result.fetchall():
        d = dict(r._mapping)
        rows[tuple(d[k] for k in KEY_COLS)] = d
        raw += 1
    if raw != len(rows):
        print("  WARNING: %d duplicate (spell,machine,item) keys collapsed" % (raw - len(rows)))
    return rows, keys


def build_view_query(conn, slice_columns):
    """Reference SELECT over vw_spinning_planning_grid with the slice's column list.

    Column list is introspected from the dayslice result keys, mapped through
    COL_MAP and intersected with the view's actual columns (information_schema)
    so the two sides always compare identical columns even if either evolves.
    """
    view_cols = {
        r[0]
        for r in conn.execute(
            text(
                "SELECT COLUMN_NAME FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = :t"
            ),
            {"t": VIEW},
        )
    }
    parts, skipped = [], []
    for c in slice_columns:
        src = COL_MAP.get(c, c)
        if src in view_cols:
            parts.append("v.%s AS %s" % (src, c))
        else:
            skipped.append(c)
    if skipped and not getattr(build_view_query, "_noted", False):
        build_view_query._noted = True
        print("  NOTE: slice columns absent from view, not compared: %s" % ", ".join(skipped))
    col_sql = ",\n            ".join(parts)
    return text(
        """
        SELECT
            %s
        FROM vw_spinning_planning_grid v
        WHERE v.co_id = :co_id
          AND v.tran_date = :tran_date
          AND (:spell_id IS NULL OR v.spell_id = :spell_id)
          AND (:branch_id IS NULL OR v.branch_id = :branch_id)
        """
        % col_sql
    )


def is_oracle_ambiguous(conn, co_id, tran_date, key, col, sval, vval):
    """True iff BOTH values sit in a same-max-effective-date active duplicate set
    of jute_prod_spng_target_map — the view's LIMIT-1-without-tie-break makes the
    oracle's pick arbitrary there (see module docstring). Tightly scoped: any
    value outside the tied set is still a real mismatch."""
    meta = TM_COLS.get(col)
    if meta is None or sval is None or vval is None:
        return False
    id_type, param, value_role, ref_idx = meta
    candidates = [
        float(r[0])
        for r in conn.execute(
            TM_DUP_SQL,
            {
                "co_id": co_id,
                "tran_date": tran_date,
                "id_type": id_type,
                "param": param,
                "value_role": value_role,
                "ref_id": key[ref_idx],
            },
        ).fetchall()
    ]
    if len(candidates) < 2:
        return False
    return all(
        any(abs(float(x) - c) <= TOLERANCE for c in candidates) for x in (sval, vval)
    )


def compare_pair(slice_rows, view_rows, mismatches, ambiguous, tag, ambig_check):
    """Compare two key-keyed dicts; append (tag, key, column, dayslice_val, view_val)."""
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
                if ambig_check(rid, col, s[col], v[col]):
                    ambiguous.append((tag, rid, col, s[col], v[col]))
                else:
                    mismatches.append((tag, rid, col, s[col], v[col]))
    return rows_compared


def run_check(conn, dayslice_q, co_id, tran_date, spell_id, branch_id, mismatches, ambiguous, tag):
    params = {
        "co_id": co_id,
        "tran_date": tran_date,
        "spell_id": spell_id,
        "branch_id": branch_id,
        "spinning_type": "Spinning",
    }
    slice_rows, keys = fetch_rows(conn, dayslice_q, params)
    view_rows, _ = fetch_rows(conn, build_view_query(conn, keys), params)
    before = len(mismatches)
    before_amb = len(ambiguous)

    def ambig_check(key, col, sval, vval):
        return is_oracle_ambiguous(conn, co_id, tran_date, key, col, sval, vval)

    n = compare_pair(slice_rows, view_rows, mismatches, ambiguous, tag, ambig_check)
    status = "PASS" if len(mismatches) == before else "FAIL"
    amb_note = ""
    if len(ambiguous) != before_amb:
        amb_note = "  ambiguous=%d" % (len(ambiguous) - before_amb)
    print(
        "[%s] %s  rows=%d  (dayslice=%d view=%d)%s"
        % (status, tag, n, len(slice_rows), len(view_rows), amb_note)
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
    dayslice_q = get_spinning_planning_slice_query()
    mismatches = []
    ambiguous = []
    total_rows = 0
    dates_checked = 0
    filter_sample = None  # (co_id, tran_date, spell_id, branch_id) for the filtered re-runs

    # Discovery: frames table has no co_id — resolve it via machine -> dept -> branch,
    # exactly the driver's join spine.
    discover_sql = (
        "SELECT DISTINCT bm.co_id, f.tran_date "
        "FROM daily_doff_frames_winding f "
        "INNER JOIN machine_mst m ON m.machine_id = f.mc_eb_id "
        "INNER JOIN dept_mst d ON d.dept_id = m.dept_id "
        "INNER JOIN branch_mst bm ON bm.branch_id = d.branch_id "
        "WHERE f.spg_wdg = 'S' AND f.item_id IS NOT NULL "
        "AND (f.active = 1 OR f.active IS NULL) "
    )

    with engine.connect() as conn:
        if args.dates:
            wanted = [d.strip() for d in args.dates.split(",") if d.strip()]
            pairs = conn.execute(
                text(
                    discover_sql + "AND f.tran_date IN :dates ORDER BY bm.co_id, f.tran_date"
                ).bindparams(bindparam("dates", expanding=True)),
                {"dates": wanted},
            ).fetchall()
        else:
            pairs = conn.execute(
                text(discover_sql + "ORDER BY bm.co_id, f.tran_date")
            ).fetchall()
        if args.limit:
            pairs = pairs[: args.limit]
        if not pairs:
            # Unlike the weaving harness this is NOT a usage error: small QA
            # tenants may simply have no S-frame mappings yet. Report clean.
            print(
                "WARNING: no (co_id, tran_date) pairs found -- "
                "daily_doff_frames_winding has no active spg_wdg='S' rows with item_id. "
                "0 rows compared; parity vacuously OK."
            )
            print("Summary: dates=0  rows_compared=0  mismatches=0")
            print("PARITY OK")
            sys.exit(0)

        for co_id, tran_date in pairs:
            tag = "co=%s date=%s" % (co_id, tran_date)
            n, slice_rows = run_check(
                conn, dayslice_q, co_id, tran_date, None, None, mismatches, ambiguous, tag
            )
            total_rows += n
            dates_checked += 1
            if filter_sample is None and slice_rows:
                any_row = next(iter(slice_rows.values()))
                filter_sample = (co_id, tran_date, any_row["spell_id"], any_row["branch_id"])

        # Filter parity: re-run one populated day with the spell_id bind
        # (the slice has no machine_id bind — spell + branch are its only
        # optional filters).
        if filter_sample:
            co_id, tran_date, spell_id, branch_id = filter_sample
            n, _ = run_check(
                conn,
                dayslice_q,
                co_id,
                tran_date,
                spell_id,
                None,
                mismatches,
                ambiguous,
                "FILTERED co=%s date=%s spell=%s" % (co_id, tran_date, spell_id),
            )
            total_rows += n

            # Branch parity: prove filtered-inside-slice == filtered-after-view.
            # Driver INNER JOINs dept/branch, so branch_id is never NULL here.
            if branch_id is not None:
                n, _ = run_check(
                    conn,
                    dayslice_q,
                    co_id,
                    tran_date,
                    None,
                    branch_id,
                    mismatches,
                    ambiguous,
                    "BRANCH co=%s date=%s branch=%s" % (co_id, tran_date, branch_id),
                )
                total_rows += n

    print()
    print("=" * 60)
    print(
        "Summary: dates=%d  rows_compared=%d  mismatches=%d  ambiguous=%d"
        % (dates_checked, total_rows, len(mismatches), len(ambiguous))
    )
    if ambiguous:
        print(
            "AMBIGUOUS (oracle nondeterministic -- same-effective-date duplicate "
            "target-map rows; both values verified in the tied set; NOT slice bugs):"
        )
        for tag, rid, col, sval, vval in ambiguous[:50]:
            print("  [%s] key=%s col=%s dayslice=%r view=%r" % (tag, rid, col, sval, vval))
    if mismatches:
        print("First %d mismatches:" % min(50, len(mismatches)))
        for tag, rid, col, sval, vval in mismatches[:50]:
            print("  [%s] key=%s col=%s dayslice=%r view=%r" % (tag, rid, col, sval, vval))
        sys.exit(1)
    print("PARITY OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
