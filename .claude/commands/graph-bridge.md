---
description: Find the other side of a cross-repo API call (FE constant ↔ BE endpoint)
argument-hint: <FE_CONSTANT_NAME | be/file.py:line | /api/path>
---

Bridge frontend API constants to backend endpoints (or vice versa). Run:

```bash
python tools/graph_query.py --bridge "$ARGUMENTS"
```

Then:

1. On a clean match, report both sides:
   - Frontend: `CONST_NAME` — `file:line`
   - Backend: `METHOD /api/path` — `file:line`
2. If the input appears in the tool's **dead_routes** list (FE constant with no BE match), say so clearly. This is valuable signal — the frontend is calling an endpoint that does not exist (or was renamed).
3. If the input appears in the **orphan_endpoints** list (BE endpoint with no FE caller), say so — may indicate a dynamic URL constructed on the frontend, dead backend code, or an internal-only endpoint.
4. If no match at all, suggest checking spelling, or running `/graph-find` / the tool's `--info` mode to inspect node details first.
5. Flag any `confidence: low` or `stale: true` results.
6. Summaries and locations only. No source dumps.
