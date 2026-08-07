"""CI tripwire: no application SQL may read the unbounded weaving/winding/spinning views.

The FREEZE-NOTHING views recompute every derived column over the WHOLE table on each
read; day-scoped inline SQL replaces them. This test flat-scans every .py under src/
(excluding src/test) for the forbidden view names so a regression can't sneak back in.

Flat case-SENSITIVE substring match — deliberately dumb. For vw_weaving_daily we match
'FROM vw_weaving_daily' (SQL keywords are uppercase in this repo, per the shared contract)
so prose docstrings in untouched routers ("come from vw_weaving_daily", "LEFT JOIN
vw_weaving_daily — ..." in weaving_entry.py) don't trip it; the other two views match on
the bare name (their only remaining mentions are allowlisted).
"""

import os

SRC_ROOT = os.path.join(os.path.dirname(__file__), "..")

FORBIDDEN = (
    "FROM vw_weaving_daily",          # zero allowlist entries, ever
    "vw_winding_daily_reconciled",
    "vw_spinning_planning_grid",
)

# (relative posix path, forbidden string) pairs that are known-legit TODAY.
# ponytail: Phase 2 removes the winding reconciliation view reader in spinning_query.py;
# delete its entry when that lands. vw_weaving_daily must NEVER gain an entry.
ALLOWLIST = {
    ("juteProduction/spinning_query.py", "vw_winding_daily_reconciled"),  # Phase 2: remove
}


def _py_files():
    for dirpath, dirnames, filenames in os.walk(SRC_ROOT):
        # skip src/test — tests may legitimately name the views in strings/docs.
        rel_dir = os.path.relpath(dirpath, SRC_ROOT).replace(os.sep, "/")
        if rel_dir == "test" or rel_dir.startswith("test/"):
            continue
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def test_no_unbounded_view_readers():
    violations = []
    for path in _py_files():
        rel = os.path.relpath(path, SRC_ROOT).replace(os.sep, "/")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        for needle in FORBIDDEN:
            if needle in content and (rel, needle) not in ALLOWLIST:
                violations.append(f"{rel}: contains '{needle}'")
    assert not violations, (
        "Unbounded view readers found (use the day-scoped inline SQL instead):\n"
        + "\n".join(violations)
    )
