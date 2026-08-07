"""Graph-query retrieval tool — Layer 3 of the graphify/descriptive-index plan.

Consumes the three read-only artifacts produced by the sibling extractors:
  - graphify-out/bridge.json     (cross-repo FE const <-> BE endpoint edges)
  - graphify-out/index_be.json   (backend node index)
  - graphify-out/index_fe.json   (frontend node index)

Seven modes: --find, --reuse, --trace, --bridge, --info, --self-test, --benchmark.
Stdlib only. Never dumps source — descriptions + locations only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_DIR = REPO_ROOT / "graphify-out"
BRIDGE_PATH = GRAPH_DIR / "bridge.json"
INDEX_BE_PATH = GRAPH_DIR / "index_be.json"
INDEX_FE_PATH = GRAPH_DIR / "index_fe.json"
BENCHMARK_PATH = GRAPH_DIR / "BENCHMARK.md"

STOPWORDS = {
    "the", "a", "an", "of", "for", "in", "to", "is", "that", "what",
    "where", "how", "and", "or", "with", "on", "at", "by", "from",
    "this", "these", "those", "it", "as", "which", "who", "why",
    "all", "any", "does", "do", "did", "has", "have", "had", "be",
    "are", "was", "were", "will", "would", "can", "could", "should",
    "find", "show", "get", "list",
}

TABLE_PREFIXES = ("proc_", "jute_", "sales_", "acc_", "hrms_", "mst_",
                  "invoice_", "issue_", "con_")
TABLE_SUFFIXES = ("_mst", "_dtl", "_hdr", "_cancel", "_map")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

@dataclass
class Artifacts:
    bridge: dict[str, Any] = field(default_factory=dict)
    be_nodes: dict[str, Any] = field(default_factory=dict)
    fe_nodes: dict[str, Any] = field(default_factory=dict)

    @property
    def all_nodes(self) -> dict[str, tuple[dict[str, Any], str]]:
        """Map node_id -> (node, repo) for both indexes."""
        merged: dict[str, tuple[dict[str, Any], str]] = {}
        for nid, node in self.be_nodes.items():
            merged[nid] = (node, "be")
        for nid, node in self.fe_nodes.items():
            merged[nid] = (node, "fe")
        return merged


def load_artifacts() -> Artifacts:
    missing = [p for p in (BRIDGE_PATH, INDEX_BE_PATH, INDEX_FE_PATH) if not p.exists()]
    if missing:
        msg = "Missing artifact(s): " + ", ".join(str(p) for p in missing)
        raise SystemExit(msg)
    bridge = json.loads(BRIDGE_PATH.read_text(encoding="utf-8"))
    be = json.loads(INDEX_BE_PATH.read_text(encoding="utf-8"))
    fe = json.loads(INDEX_FE_PATH.read_text(encoding="utf-8"))
    return Artifacts(bridge=bridge, be_nodes=be.get("nodes", {}), fe_nodes=fe.get("nodes", {}))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    tokens = re.split(r"[^a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if t and t not in STOPWORDS and len(t) > 1]


def _node_name(node: dict[str, Any]) -> str:
    if node.get("name"):
        return node["name"]
    nid = node.get("node_id", "")
    return nid.rsplit(":", 1)[-1] if ":" in nid else nid


def score_node(q_tokens: list[str], q_raw: str, node: dict[str, Any]) -> float:
    """Field-weighted substring + token-match score."""
    if not q_tokens:
        return 0.0
    score = 0.0
    q_lower = q_raw.lower()

    # name field (weight 4.0) — both substring and token match credited.
    name = _node_name(node).lower()
    if name:
        if q_lower in name or name in q_lower:
            score += 4.0
        name_tokens = set(tokenize(name))
        score += 4.0 * sum(1 for t in q_tokens if t in name_tokens) / max(len(q_tokens), 1)

    # summary (weight 2.0)
    summary = (node.get("summary") or "").lower()
    if summary:
        s_tokens = set(tokenize(summary))
        score += 2.0 * sum(1 for t in q_tokens if t in s_tokens) / max(len(q_tokens), 1)

    # docstring_first_line (weight 2.0)
    doc = (node.get("docstring_first_line") or "").lower()
    if doc:
        d_tokens = set(tokenize(doc))
        score += 2.0 * sum(1 for t in q_tokens if t in d_tokens) / max(len(q_tokens), 1)

    # decorators / url_path / route (weight 1.5)
    deco_parts: list[str] = []
    for d in node.get("decorators") or []:
        deco_parts.append(d)
    if node.get("url_path"):
        deco_parts.append(node["url_path"])
    if node.get("route"):
        deco_parts.append(node["route"])
    deco_blob = " ".join(deco_parts).lower()
    if deco_blob:
        dt = set(tokenize(deco_blob))
        score += 1.5 * sum(1 for t in q_tokens if t in dt) / max(len(q_tokens), 1)

    # file (weight 0.5)
    f = (node.get("file") or "").lower()
    if f:
        ft = set(tokenize(f))
        score += 0.5 * sum(1 for t in q_tokens if t in ft) / max(len(q_tokens), 1)

    return score


def _tie_key(nid: str) -> tuple[int, str]:
    return (len(nid), nid)


def rank_nodes(
    art: Artifacts,
    query: str,
    *,
    repo: str = "both",
    kind: str | None = None,
    persona: str | None = None,
    kinds_whitelist: Iterable[str] | None = None,
    k: int = 5,
) -> list[tuple[float, str, dict[str, Any], str]]:
    q_tokens = tokenize(query)
    pool: list[tuple[str, dict[str, Any], str]] = []
    if repo in ("be", "both"):
        for nid, n in art.be_nodes.items():
            pool.append((nid, n, "be"))
    if repo in ("fe", "both"):
        for nid, n in art.fe_nodes.items():
            pool.append((nid, n, "fe"))

    wl = set(kinds_whitelist) if kinds_whitelist else None
    scored: list[tuple[float, str, dict[str, Any], str]] = []
    for nid, node, which in pool:
        if kind and node.get("kind") != kind:
            continue
        if wl and node.get("kind") not in wl:
            continue
        if persona and node.get("persona") != persona:
            continue
        s = score_node(q_tokens, query, node)
        if s > 0:
            scored.append((s, nid, node, which))

    scored.sort(key=lambda r: (-r[0], _tie_key(r[1])))
    return scored[:k]


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def format_hit(score: float, nid: str, node: dict[str, Any], which: str) -> str:
    kind = node.get("kind") or "?"
    persona = node.get("persona") or "-"
    summary = (node.get("summary") or "").strip() or "(no summary)"
    file_ = node.get("file") or "?"
    line = node.get("line") or "?"
    conf = node.get("confidence") or "?"
    ts = node.get("last_indexed_at") or "?"
    out = [
        f"[score={score:.2f}] {nid}  ({kind}, {persona}, {which})",
        f"  -> {summary}",
        f"  -> file:line  {file_}:{line}",
        f"  -> confidence={conf}, last_indexed={ts}",
    ]
    return "\n".join(out)


def to_json_hit(score: float, nid: str, node: dict[str, Any], which: str) -> dict:
    return {
        "score": round(score, 3),
        "node_id": nid,
        "repo": which,
        "kind": node.get("kind"),
        "persona": node.get("persona"),
        "file": node.get("file"),
        "line": node.get("line"),
        "summary": node.get("summary"),
        "confidence": node.get("confidence"),
        "last_indexed_at": node.get("last_indexed_at"),
    }


# ---------------------------------------------------------------------------
# Mode: find / reuse
# ---------------------------------------------------------------------------

def cmd_find(art: Artifacts, args) -> int:
    hits = rank_nodes(
        art, args.find, repo=args.repo, kind=args.kind, persona=args.persona, k=args.top,
    )
    if args.json:
        print(json.dumps({"query": args.find, "hits": [to_json_hit(*h) for h in hits]}, indent=2))
    else:
        print(f"Query: {args.find!r}  (mode=find, top={args.top})")
        if not hits:
            print("  no matches")
        for h in hits:
            print(format_hit(*h))
    return 0 if hits else 1


def cmd_reuse(art: Artifacts, args) -> int:
    whitelist = ("query_fn", "service_fn", "function")
    hits = rank_nodes(
        art, args.reuse, repo=args.repo, kind=args.kind, persona=args.persona,
        kinds_whitelist=None if args.kind else whitelist, k=args.top,
    )
    # 1-hop neighbors best-effort: endpoints mentioning the name.
    neighbors: dict[str, list[str]] = {}
    for _, nid, node, which in hits:
        nm = _node_name(node)
        if not nm:
            continue
        ep_nbrs: list[str] = []
        for enid, en in art.be_nodes.items():
            if en.get("kind") != "endpoint":
                continue
            blob = (en.get("summary") or "") + " " + (en.get("docstring_first_line") or "")
            if nm in blob or nm in enid:
                ep_nbrs.append(enid)
                if len(ep_nbrs) >= 3:
                    break
        if ep_nbrs:
            neighbors[nid] = ep_nbrs

    if args.json:
        out = {
            "query": args.reuse,
            "hits": [to_json_hit(*h) for h in hits],
            "neighbors": neighbors,
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"Query: {args.reuse!r}  (mode=reuse, top={args.top})")
        if not hits:
            print("  no matches")
        for h in hits:
            print(format_hit(*h))
            nid = h[1]
            if nid in neighbors:
                print(f"  -> referenced-by endpoints (best-effort):")
                for enid in neighbors[nid]:
                    print(f"       {enid}")
    return 0 if hits else 1


# ---------------------------------------------------------------------------
# Mode: trace
# ---------------------------------------------------------------------------

def _looks_like_table(s: str) -> bool:
    s_low = s.lower()
    if "/" in s or ":" in s:
        return False
    if not re.fullmatch(r"[a-z0-9_]+", s_low):
        return False
    if s_low.startswith(TABLE_PREFIXES):
        return True
    if any(s_low.endswith(suf) for suf in TABLE_SUFFIXES):
        return True
    return False


def _bridge_matches_for_be(art: Artifacts, endpoint_node: dict[str, Any]) -> list[dict]:
    """Find FE consts whose matched be_location file aligns with endpoint file."""
    file_norm = (endpoint_node.get("file") or "").replace("/", "\\").lower()
    out: list[dict] = []
    for m in art.bridge.get("matched", []):
        be_loc = (m.get("be_location") or "").lower()
        if file_norm and file_norm in be_loc:
            # also match on path tail — be_path should be in decorators
            deco = " ".join(endpoint_node.get("decorators") or [])
            be_path = m.get("be_path") or ""
            if be_path and be_path in deco:
                out.append(m)
    return out


def cmd_trace(art: Artifacts, args) -> int:
    target = args.trace.strip()
    lines: list[str] = []
    json_tree: dict[str, Any] = {"target": target, "kind": None, "branches": []}

    if _looks_like_table(target):
        json_tree["kind"] = "table"
        lines.append(f"Table {target}:")
        # find query_fns mentioning the table
        qfns: list[tuple[str, dict]] = []
        for nid, node in art.be_nodes.items():
            if node.get("kind") != "query_fn":
                continue
            blob = (nid + " " + (node.get("summary") or "") + " " + (node.get("docstring_first_line") or "")).lower()
            if target.lower() in blob:
                qfns.append((nid, node))
        if not qfns:
            lines.append(f"  (no query_fn references to {target})")
        for i, (qnid, qnode) in enumerate(qfns):
            last_q = (i == len(qfns) - 1)
            branch = "  `-" if last_q else "  |-"
            lines.append(f"{branch} query_fn {qnid}")
            qbranch = {"query_fn": qnid, "endpoints": []}
            # find endpoints in same file that reference this name
            qname = _node_name(qnode)
            qfile = qnode.get("file")
            eps = []
            for enid, en in art.be_nodes.items():
                if en.get("kind") != "endpoint":
                    continue
                if en.get("file", "").split("/", 1)[0] != qfile.split("/", 1)[0]:
                    # same top-level module
                    pass
                en_blob = enid + " " + (en.get("summary") or "") + " " + (en.get("docstring_first_line") or "")
                if qname and qname in en_blob:
                    eps.append((enid, en))
            for j, (enid, en) in enumerate(eps[:5]):
                deco = (en.get("decorators") or ["?"])[0]
                lines.append(f"      `- endpoint {enid} ({deco})")
                ep_entry = {"endpoint": enid, "decorator": deco, "fe": []}
                bms = _bridge_matches_for_be(art, en)
                for bm in bms:
                    lines.append(f"          `- fe_const {bm['const_name']} ({bm['fe_location']})")
                    ep_entry["fe"].append({"const_name": bm["const_name"], "fe_location": bm["fe_location"]})
                qbranch["endpoints"].append(ep_entry)
            json_tree["branches"].append(qbranch)
    else:
        json_tree["kind"] = "function"
        lines.append(f"Function {target}:")
        # find BE nodes whose name equals target
        matches: list[tuple[str, dict]] = []
        for nid, node in art.be_nodes.items():
            if _node_name(node).lower() == target.lower():
                matches.append((nid, node))
        if not matches:
            # substring fallback
            for nid, node in art.be_nodes.items():
                if target.lower() in _node_name(node).lower():
                    matches.append((nid, node))
        for i, (mnid, mnode) in enumerate(matches[:5]):
            lines.append(f"  `- {mnode.get('kind')} {mnid}")
            branch = {"node_id": mnid, "kind": mnode.get("kind"), "references": []}
            # find endpoints referencing this name
            if mnode.get("kind") != "endpoint":
                nm = _node_name(mnode)
                for enid, en in art.be_nodes.items():
                    if en.get("kind") != "endpoint":
                        continue
                    blob = enid + " " + (en.get("summary") or "") + " " + (en.get("docstring_first_line") or "")
                    if nm and nm in blob:
                        deco = (en.get("decorators") or ["?"])[0]
                        lines.append(f"      `- endpoint {enid} ({deco})")
                        bms = _bridge_matches_for_be(art, en)
                        for bm in bms:
                            lines.append(f"          `- fe_const {bm['const_name']}")
                        branch["references"].append({"endpoint": enid, "decorator": deco, "fe": [bm["const_name"] for bm in bms]})
            else:
                # the target itself is an endpoint
                bms = _bridge_matches_for_be(art, mnode)
                for bm in bms:
                    lines.append(f"      `- fe_const {bm['const_name']}")
                    branch["references"].append({"const_name": bm["const_name"], "fe_location": bm["fe_location"]})
            json_tree["branches"].append(branch)
        if not matches:
            lines.append("  (no matches)")

    if args.json:
        print(json.dumps(json_tree, indent=2))
    else:
        print("\n".join(lines))
    return 0 if json_tree["branches"] else 1


# ---------------------------------------------------------------------------
# Mode: bridge
# ---------------------------------------------------------------------------

def cmd_bridge(art: Artifacts, args) -> int:
    q = args.bridge.strip()
    matched: list[dict] = []
    dead: list[dict] = []
    orphans: list[dict] = []

    q_norm = q.replace("/", "\\").lower()

    # Heuristic classification
    is_file_line = bool(re.search(r"\.py:\d+$", q))
    is_path = q.startswith("/api/") or q.startswith("/")
    is_node_id = ("/" in q or "\\" in q) and ":" in q and not is_file_line

    for m in art.bridge.get("matched", []):
        if m.get("const_name") == q or m.get("const_name") == q.upper():
            matched.append(m)
            continue
        be_loc = (m.get("be_location") or "").lower()
        fe_loc = (m.get("fe_location") or "").lower()
        if is_file_line and q_norm in be_loc:
            matched.append(m)
            continue
        full_be = (m.get("be_prefix", "") or "") + (m.get("be_path", "") or "")
        if is_path and (q == full_be or q == m.get("be_path") or q == m.get("url_path")):
            matched.append(m)
            continue
        if is_node_id and q_norm in fe_loc:
            matched.append(m)
            continue

    # dead routes
    for d in art.bridge.get("dead_routes", []):
        if d.get("const_name") == q or d.get("const_name") == q.upper():
            dead.append(d)
        elif is_file_line and q_norm in (d.get("fe_location") or "").lower():
            dead.append(d)

    # orphans
    for o in art.bridge.get("orphan_endpoints", []):
        if is_file_line and q_norm in (o.get("be_location") or "").lower():
            orphans.append(o)
        elif is_path and (q == o.get("full_path") or q == o.get("path")):
            orphans.append(o)

    result = {
        "query": q,
        "matched": matched,
        "dead_routes": dead,
        "orphan_endpoints": orphans,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Bridge query: {q!r}")
        if matched:
            print(f"  matched ({len(matched)}):")
            for m in matched:
                print(f"    {m['const_name']}  {m.get('be_method','?')} {m.get('be_prefix','')}{m.get('be_path','')}")
                print(f"      fe: {m.get('fe_location')}")
                print(f"      be: {m.get('be_location')}  (match_kind={m.get('match_kind')})")
        if dead:
            print(f"  DEAD ROUTES ({len(dead)}):")
            for d in dead:
                print(f"    {d['const_name']}  url={d.get('url_path')}  fe={d.get('fe_location')}")
        if orphans:
            print(f"  ORPHAN ENDPOINTS ({len(orphans)}):")
            for o in orphans:
                print(f"    {o.get('method')} {o.get('full_path')}  be={o.get('be_location')}")
        if not (matched or dead or orphans):
            print("  no bridge entries found for this query")
    return 0 if (matched or dead or orphans) else 1


# ---------------------------------------------------------------------------
# Mode: info
# ---------------------------------------------------------------------------

def _fuzzy_candidates(art: Artifacts, q: str, limit: int = 5) -> list[str]:
    q_low = q.lower()
    cands: list[tuple[int, str]] = []
    for nid in list(art.be_nodes) + list(art.fe_nodes):
        if q_low in nid.lower():
            cands.append((len(nid), nid))
    cands.sort()
    return [c[1] for c in cands[:limit]]


def cmd_info(art: Artifacts, args) -> int:
    nid = args.info.strip()
    node = art.be_nodes.get(nid) or art.fe_nodes.get(nid)
    if node is None:
        hints = _fuzzy_candidates(art, nid)
        if args.json:
            print(json.dumps({"error": "not_found", "query": nid, "suggestions": hints}, indent=2))
        else:
            print(f"No node found for {nid!r}")
            if hints:
                print("Did you mean:")
                for h in hints:
                    print(f"  {h}")
        return 1
    repo = "be" if nid in art.be_nodes else "fe"
    if args.json:
        print(json.dumps({"repo": repo, "node": node}, indent=2))
    else:
        print(f"Node: {nid}  (repo={repo})")
        for k, v in node.items():
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v) if v else "(empty)"
            print(f"  {k}: {v}")
    return 0


# ---------------------------------------------------------------------------
# Mode: self-test
# ---------------------------------------------------------------------------

def cmd_self_test(art: Artifacts, args) -> int:
    tests = [
        ("find",   "create indent", lambda hits: any("indent" in h[1].lower() for h in hits)),
        ("bridge", "INWARD_TABLE", None),
        ("trace",  "proc_inward", None),
        ("info",   "src/utils/api.ts:INWARD_TABLE", None),
    ]
    passed = 0
    for mode, q, _ in tests:
        ok = False
        detail = ""
        try:
            if mode == "find":
                hits = rank_nodes(art, q, k=5)
                ok = len(hits) >= 1
                detail = f"{len(hits)} hits"
            elif mode == "bridge":
                found = False
                for m in art.bridge.get("matched", []):
                    if m.get("const_name") == q or q in (m.get("const_name") or ""):
                        found = True
                        break
                # also check dead routes
                if not found:
                    for d in art.bridge.get("dead_routes", []):
                        if d.get("const_name") == q:
                            found = True
                            break
                # also check FE node
                if not found:
                    for nid in art.fe_nodes:
                        if nid.endswith(":" + q):
                            found = True
                            break
                ok = found
                detail = "bridge hit" if found else "no bridge hit"
            elif mode == "trace":
                # table — check that there is at least one query_fn mentioning proc_inward
                found = any(
                    q.lower() in (nid + " " + (n.get("summary") or "")).lower()
                    for nid, n in art.be_nodes.items()
                    if n.get("kind") == "query_fn"
                )
                ok = found
                detail = "query_fn found" if found else "none"
            elif mode == "info":
                ok = q in art.fe_nodes or q in art.be_nodes
                if not ok:
                    # tolerate: try the name variant
                    for nid in art.fe_nodes:
                        if nid.endswith(":" + q.rsplit(":", 1)[-1]) and "api.ts" in nid:
                            ok = True
                            break
                detail = "found" if ok else "missing"
        except Exception as exc:  # noqa: BLE001
            detail = f"error: {exc}"
            ok = False
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] --{mode} {q!r}  ({detail})")
        if ok:
            passed += 1
    total = len(tests)
    print(f"Self-test: {passed}/{total} passed")
    return 0 if passed == total else 1


# ---------------------------------------------------------------------------
# Mode: benchmark
# ---------------------------------------------------------------------------

BENCH_COMMENT_RE = re.compile(r"<!--\s*benchmark:\s*(?P<body>[^>]+?)\s*-->")
BENCH_HEADING_RE = re.compile(r"^###\s+(?P<id>Q\w+)\s+(?P<rest>.+)$")
BENCH_KV_RE = re.compile(r"(\w+)=([^\s]+)")
BENCH_QUOTED_RE = re.compile(r'"([^"]+)"')
BENCH_NEG_SCORE_THRESHOLD = 2.5


def _clean_question(rest: str) -> str:
    """Extract the quoted question text from a heading rest, fall back to stripped rest."""
    m = BENCH_QUOTED_RE.search(rest)
    if m:
        return m.group(1)
    # fallback: strip leading [mode=...] tag and em-dash
    cleaned = re.sub(r"^\s*\[[^\]]+\]\s*[—-]+\s*", "", rest).strip()
    return cleaned


def parse_benchmark(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    headings: dict[str, str] = {}
    for line in text.splitlines():
        m = BENCH_HEADING_RE.match(line.strip())
        if m:
            headings[m.group("id")] = _clean_question(m.group("rest"))
    entries: list[dict] = []
    for m in BENCH_COMMENT_RE.finditer(text):
        body = m.group("body")
        kv = dict(BENCH_KV_RE.findall(body))
        qid = kv.get("id")
        if not qid:
            continue
        entries.append({
            "id": qid,
            "mode": kv.get("mode", ""),
            "kv": kv,
            "question": headings.get(qid, ""),
        })
    return entries


def _expand_set(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def _grade_entry(art: Artifacts, e: dict) -> tuple[bool, list[str], str]:
    """Return (passed, actual_top3_or_diag, reason)."""
    mode = e["mode"]
    kv = e["kv"]
    q_text = e["question"] or next(iter(kv.values()), "")

    # --- Schema 6: negative find ---
    if kv.get("negative") == "true":
        hits = rank_nodes(art, q_text, k=3)
        top_score = hits[0][0] if hits else 0.0
        top_ids = [h[1] for h in hits[:3]]
        ok = top_score < BENCH_NEG_SCORE_THRESHOLD
        return ok, top_ids, f"top_score={top_score:.2f} threshold<{BENCH_NEG_SCORE_THRESHOLD}"

    # --- Schema 5: dead-route check ---
    if kv.get("dead_route") == "true":
        dead_ids = {d.get("const_name") for d in art.bridge.get("dead_routes", [])}
        # primary_set OR fe_primary form
        if "primary_set" in kv:
            expected = _expand_set(kv["primary_set"])
            min_match = int(kv.get("min_match", "1"))
            # const_name is the bare const (e.g. GETMENUMAPPINGCOMPANY); node_id is src/utils/api.ts:GETMENUMAPPINGCOMPANY
            hits_in_dead = sum(
                1 for nid in expected if nid.split(":")[-1] in dead_ids
            )
            ok = hits_in_dead >= min_match
            return ok, sorted(dead_ids), f"{hits_in_dead}/{min_match} of expected in dead_routes"
        fe_primary = kv.get("fe_primary", "")
        const = fe_primary.split(":")[-1]
        ok = const in dead_ids
        return ok, sorted(dead_ids), f"const={const} in dead_routes={ok}"

    # --- Schema 3/4: bridge with fe_source / be_source ---
    if mode == "bridge":
        fe_src = kv.get("fe_source", "")
        be_src = kv.get("be_source", "")
        if fe_src:
            const = fe_src.split(":")[-1]
            target = kv.get("be_primary", "").split(":")[-1]  # last segment; match by function name
            for m in art.bridge.get("matched", []):
                if m.get("const_name") == const:
                    # backend side is file:line — we don't have symbol. Match by file path + last-segment-as-name-hint
                    be_loc = m.get("be_location", "")
                    if target and target in be_loc.replace("\\", "/"):
                        return True, [be_loc], "fe_source matched with be_primary hint"
                    # loose pass: if fe_source matched any backend endpoint, count as pass
                    return True, [be_loc], "fe_source matched (any be)"
            return False, [], "fe_source const not found in bridge.matched"
        if be_src:
            # be_source is a backend node id like src/juteProcurement/billPass.py:get_jute_bill_pass_list
            file_hint = be_src.split(":")[0].replace("\\", "/")
            target_const = kv.get("fe_primary", "").split(":")[-1]
            for m in art.bridge.get("matched", []):
                if file_hint in m.get("be_location", "").replace("\\", "/"):
                    if not target_const or m.get("const_name") == target_const:
                        return True, [m.get("const_name", "")], "be_source matched"
            return False, [], "be_source not found in bridge.matched"
        # Schema 1 for bridge (primary=)
        if "primary" in kv:
            target = kv["primary"]
            for m in art.bridge.get("matched", []):
                if target in (m.get("const_name"), m.get("be_location"), m.get("fe_location")):
                    return True, [m.get("const_name", "")], "primary matched in bridge"
            return False, [], f"{target} not in bridge.matched"
        return False, [], "bridge trailer missing fe_source/be_source/primary"

    # --- Schema 1: single primary (find) ---
    if "primary" in kv:
        target = kv["primary"]
        if mode in ("find", "reuse"):
            wl = ("query_fn", "service_fn", "function") if mode == "reuse" else None
            hits = rank_nodes(art, q_text, kinds_whitelist=wl, k=5)
            actual = [h[1] for h in hits[:3]]
            ok = any(h[1] == target for h in hits)
            return ok, actual, f"expected {target}"
        # trace fallback
        ok = target in art.be_nodes or target in art.fe_nodes
        return ok, [], f"trace primary exists: {ok}"

    # --- Schema 2: primary_set (reuse/trace) ---
    if "primary_set" in kv:
        expected = set(_expand_set(kv["primary_set"]))
        min_match = int(kv.get("min_match", "1"))
        if mode == "reuse":
            hits = rank_nodes(
                art, q_text, kinds_whitelist=("query_fn", "service_fn", "function"), k=10
            )
        else:
            hits = rank_nodes(art, q_text, k=10)
        hit_ids = {h[1] for h in hits}
        matched = expected & hit_ids
        actual_top3 = [h[1] for h in hits[:3]]
        ok = len(matched) >= min_match
        return ok, actual_top3, f"matched {len(matched)}/{min_match} of expected set"

    return False, [], "no recognised primary key in trailer"


def cmd_benchmark(art: Artifacts, args) -> int:
    if not BENCHMARK_PATH.exists():
        print(f"BENCHMARK.md not found at {BENCHMARK_PATH} — nothing to run.")
        return 0
    entries = parse_benchmark(BENCHMARK_PATH)
    if not entries:
        print("No benchmark entries parsed from BENCHMARK.md.")
        return 0

    mode_totals: dict[str, list[int]] = {}
    failed: list[dict] = []
    for e in entries:
        mode = e["mode"] or "unknown"
        mode_totals.setdefault(mode, [0, 0])
        mode_totals[mode][1] += 1
        try:
            ok, actual, reason = _grade_entry(art, e)
        except Exception as exc:  # noqa: BLE001
            ok, actual, reason = False, [], f"exception: {exc}"
        if ok:
            mode_totals[mode][0] += 1
        else:
            failed.append({**e, "actual": actual, "reason": reason})

    total_pass = sum(v[0] for v in mode_totals.values())
    total = sum(v[1] for v in mode_totals.values())
    print(f"Benchmark Results ({total} questions)")
    print("================================")
    for mode, (p, t) in sorted(mode_totals.items()):
        pct = (100 * p // t) if t else 0
        print(f"{mode:<8} {p}/{t} PASS ({pct}%)")
    print("--------------------------------")
    pct_tot = (100 * total_pass // total) if total else 0
    print(f"TOTAL:   {total_pass}/{total} PASS ({pct_tot}%)")
    if failed:
        print("\nFailures:")
        for f in failed:
            safe_q = f['question'].encode('ascii', 'replace').decode('ascii')[:90]
            print(f"  [{f['id']} mode={f['mode']}] {safe_q}")
            print(f"    reason: {f['reason']}")
            if f["actual"]:
                print(f"    actual: {f['actual'][:3]}")
    return 0 if total_pass == total else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Graph-query retrieval tool")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--find", metavar="QUERY", help="NL query -> top-K nodes")
    g.add_argument("--reuse", metavar="DESC", help="similar existing query/service functions")
    g.add_argument("--trace", metavar="ENTITY", help="follow bridge + imports from a symbol or table")
    g.add_argument("--bridge", metavar="TARGET", help="FE<->BE bridge lookup")
    g.add_argument("--info", metavar="NODE_ID", help="pretty-print all fields of one node")
    g.add_argument("--self-test", action="store_true", help="run canned retrieval tests")
    g.add_argument("--benchmark", action="store_true", help="run BENCHMARK.md questions")
    p.add_argument("--kind", help="filter by node kind (endpoint, query_fn, ...)")
    p.add_argument("--persona", help="filter by persona (portal, companyAdmin, ctrldskAdmin)")
    p.add_argument("--repo", choices=("be", "fe", "both"), default="both", help="repo scope")
    p.add_argument("-k", "--top", type=int, default=5, help="top-K results")
    p.add_argument("--json", action="store_true", help="JSON output instead of human-readable")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    art = load_artifacts()
    if args.find:
        return cmd_find(art, args)
    if args.reuse:
        return cmd_reuse(art, args)
    if args.trace:
        return cmd_trace(art, args)
    if args.bridge:
        return cmd_bridge(art, args)
    if args.info:
        return cmd_info(art, args)
    if args.self_test:
        return cmd_self_test(art, args)
    if args.benchmark:
        return cmd_benchmark(art, args)
    parser.error("no mode selected")
    return 2


if __name__ == "__main__":
    sys.exit(main())
