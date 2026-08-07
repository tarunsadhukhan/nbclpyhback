"""Layer 1 content indexer — backend descriptive JSON for the graphify substrate.

Walks `src/**/*.py`, emits one node per module-level function, class, and method
(one level deep). Output: `graphify-out/index_be.json` keyed by node_id
(`relpath:qualname`). Deterministic summaries only; no LLM call.

Stdlib only. Style mirrors tools/bridge_extractor.py.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BE_REPO_DEFAULT = Path(r"c:\code\vowerp3be")

SKIP_REL_PREFIXES = (
    "src/test/",
    "src/config/",
)
SKIP_DIR_PARTS = {"__pycache__", ".venv", ".git"}

ROUTER_DECORATOR_RE = re.compile(
    r"^@\s*\w+\.(get|post|put|delete|patch|api_route)\b"
)
TABLE_PORTAL_PARTS = {
    "masters",
    "procurement",
    "sales",
    "inventory",
    "hrms",
    "accounting",
    "juteProcurement",
    "juteSQC",
    "bomcosting",
}
MIXED_REL_FILES = {
    "src/common/routers.py",
    "src/common/companydata.py",
}


@dataclass
class IndexNode:
    node_id: str
    kind: str
    persona: str | None
    file: str
    line: int
    signature: str
    docstring_first_line: str
    decorators: list[str] = field(default_factory=list)
    summary: str = ""
    confidence: str = "low"
    hash: str = ""
    last_indexed_at: str = ""


@dataclass
class Report:
    generated_at: str
    backend_root: str
    stats: dict
    nodes: dict


def rel_posix(path: Path, repo: Path) -> str:
    return path.relative_to(repo).as_posix()


def should_skip(rel: str) -> bool:
    if any(rel.startswith(p) for p in SKIP_REL_PREFIXES):
        return True
    parts = set(rel.split("/"))
    return bool(parts & SKIP_DIR_PARTS)


def iter_python_files(repo: Path) -> list[Path]:
    src = repo / "src"
    files: list[Path] = []
    for p in src.rglob("*.py"):
        rel = rel_posix(p, repo)
        if should_skip(rel):
            continue
        files.append(p)
    return files


def classify_persona(rel: str) -> str | None:
    # rel is posix-style relative to repo root, always starts with "src/"
    if rel in MIXED_REL_FILES:
        return "mixed"
    parts = rel.split("/")
    if len(parts) < 2:
        return None
    if parts[0] != "src":
        return None
    if len(parts) >= 3 and parts[1] == "common":
        sub = parts[2]
        if sub == "ctrldskAdmin":
            return "ctrldskAdmin"
        if sub == "companyAdmin":
            return "companyAdmin"
        if sub == "portal":
            return "portal"
    if parts[1] in TABLE_PORTAL_PARTS:
        return "portal"
    if parts[1] == "authorization":
        return "mixed"
    return None


def safe_unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def build_signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        args = ast.unparse(fn.args)
    except Exception:
        args = ""
    ret = safe_unparse(fn.returns)
    sig = f"({args})"
    if ret:
        sig += f" -> {ret}"
    return sig


def first_docline(node: ast.AST) -> str:
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def extract_decorators(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> list[str]:
    out: list[str] = []
    for dec in node.decorator_list:
        src = safe_unparse(dec)
        if src:
            out.append("@" + src)
    return out


def pick_router_decorator(decorators: list[str]) -> str | None:
    for d in decorators:
        if ROUTER_DECORATOR_RE.match(d):
            return d
    return None


def tablename_from_class(cls: ast.ClassDef) -> str | None:
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__tablename__":
                    if isinstance(stmt.value, ast.Constant) and isinstance(
                        stmt.value.value, str
                    ):
                        return stmt.value.value
        elif isinstance(stmt, ast.AnnAssign):
            tgt = stmt.target
            if isinstance(tgt, ast.Name) and tgt.id == "__tablename__":
                if (
                    stmt.value is not None
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    return stmt.value.value
    return None


def class_is_model(cls: ast.ClassDef, rel: str) -> bool:
    if rel.startswith("src/models/"):
        return True
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id in {"Base", "DeclarativeBase"}:
            return True
        if isinstance(base, ast.Attribute) and base.attr in {
            "Base",
            "DeclarativeBase",
        }:
            return True
    return False


def classify_kind(
    node: ast.AST,
    rel: str,
    decorators: list[str],
    in_class: bool,
) -> tuple[str, str | None]:
    """Return (kind, router_decorator_match) tuple."""
    if isinstance(node, ast.ClassDef):
        return ("model" if class_is_model(node, rel) else "class", None)
    # Functions
    router_dec = pick_router_decorator(decorators)
    if router_dec:
        return ("endpoint", router_dec)
    if Path(rel).name == "query.py":
        return ("query_fn", None)
    if in_class:
        return ("method", None)
    return ("function", None)


def first_n_lines_of_source(node: ast.AST, n: int = 30) -> str:
    src = safe_unparse(node)
    if not src:
        return ""
    return "\n".join(src.splitlines()[:n])


def make_hash(signature: str, docstring: str, source_head: str) -> str:
    payload = (signature + "\n" + docstring + "\n" + source_head).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_summary(
    node: ast.AST,
    kind: str,
    name: str,
    signature: str,
    docline: str,
    rel: str,
    persona: str | None,
    router_dec: str | None,
    class_ctx: str | None,
) -> str:
    def fallback(label: str) -> str:
        return docline if docline else label

    if kind == "endpoint":
        dec = router_dec or "@router.?"
        persona_tag = persona or "unknown"
        body = fallback(name)
        return f"{dec} -- {body} [persona={persona_tag}]"

    if kind == "query_fn":
        body = fallback("query builder")
        return f"{name}{signature} -- {body} (in {rel})"

    if kind == "model" and isinstance(node, ast.ClassDef):
        tbl = tablename_from_class(node)
        if tbl:
            return f"{name} -> table {tbl} ({rel})"
        return f"{name} -- SQLAlchemy model ({rel})"

    if kind == "class" and isinstance(node, ast.ClassDef):
        bases = [safe_unparse(b) for b in node.bases]
        bases = [b for b in bases if b]
        bases_str = f"({', '.join(bases)})" if bases else ""
        body = fallback("class definition")
        return f"{name}{bases_str} -- {body}"

    if kind == "method":
        body = fallback("method")
        prefix = f"{class_ctx}." if class_ctx else ""
        return f"{prefix}{name}{signature} -- {body}"

    # function
    body = fallback("function")
    return f"{name}{signature} -- {body}"


def make_node(
    repo: Path,
    py_file: Path,
    node: ast.AST,
    rel: str,
    persona: str | None,
    class_ctx: str | None,
    now_iso: str,
) -> IndexNode | None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        decorators = extract_decorators(node)
        in_class = class_ctx is not None
        kind, router_dec = classify_kind(node, rel, decorators, in_class)
        name = node.name
        signature = build_signature(node)
    elif isinstance(node, ast.ClassDef):
        decorators = extract_decorators(node)
        kind, router_dec = classify_kind(node, rel, decorators, False)
        name = node.name
        signature = ""
    else:
        return None

    docline = first_docline(node)
    qualname = f"{class_ctx}.{name}" if class_ctx else name
    node_id = f"{rel}:{qualname}"
    summary = build_summary(
        node, kind, name, signature, docline, rel, persona, router_dec, class_ctx
    )
    source_head = first_n_lines_of_source(node, 30)
    h = make_hash(signature, docline, source_head)
    confidence = "medium" if docline else "low"

    return IndexNode(
        node_id=node_id,
        kind=kind,
        persona=persona,
        file=rel,
        line=getattr(node, "lineno", 0),
        signature=signature,
        docstring_first_line=docline,
        decorators=decorators,
        summary=summary,
        confidence=confidence,
        hash=h,
        last_indexed_at=now_iso,
    )


def extract_from_tree(
    tree: ast.Module,
    repo: Path,
    py_file: Path,
    rel: str,
    persona: str | None,
    now_iso: str,
) -> list[IndexNode]:
    out: list[IndexNode] = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            n = make_node(repo, py_file, stmt, rel, persona, None, now_iso)
            if n:
                out.append(n)
        elif isinstance(stmt, ast.ClassDef):
            n = make_node(repo, py_file, stmt, rel, persona, None, now_iso)
            if n:
                out.append(n)
            # One level deep: methods
            for inner in stmt.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m = make_node(
                        repo, py_file, inner, rel, persona, stmt.name, now_iso
                    )
                    if m:
                        out.append(m)
    return out


def build_index(repo: Path) -> tuple[dict[str, IndexNode], int]:
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    nodes: dict[str, IndexNode] = {}
    parse_errors = 0
    for py_file in iter_python_files(repo):
        rel = rel_posix(py_file, repo)
        persona = classify_persona(rel)
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            parse_errors += 1
            continue
        file_nodes = extract_from_tree(tree, repo, py_file, rel, persona, now_iso)
        for n in file_nodes:
            # Collisions: append line to node_id to keep unique.
            node_id = n.node_id
            if node_id in nodes:
                node_id = f"{node_id}@{n.line}"
                n.node_id = node_id
            nodes[node_id] = n
    return nodes, parse_errors


def compute_stats(
    nodes: dict[str, IndexNode], parse_errors: int, out_path: Path
) -> dict:
    by_kind: dict[str, int] = {}
    by_persona: dict[str, int] = {}
    for n in nodes.values():
        by_kind[n.kind] = by_kind.get(n.kind, 0) + 1
        k = n.persona if n.persona is not None else "null"
        by_persona[k] = by_persona.get(k, 0) + 1
    size_bytes = out_path.stat().st_size if out_path.exists() else 0
    return {
        "total": len(nodes),
        "by_kind": dict(sorted(by_kind.items(), key=lambda x: -x[1])),
        "by_persona": dict(sorted(by_persona.items(), key=lambda x: -x[1])),
        "parse_errors": parse_errors,
        "output_bytes": size_bytes,
        "output_mb": round(size_bytes / (1024 * 1024), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--be-repo", type=Path, default=BE_REPO_DEFAULT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    output = args.output or (args.be_repo / "graphify-out" / "index_be.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    nodes, parse_errors = build_index(args.be_repo)

    report = Report(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        backend_root=str(args.be_repo / "src"),
        stats={},  # filled after write so we can measure file size too
        nodes={nid: asdict(n) for nid, n in nodes.items()},
    )

    with output.open("w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, sort_keys=False)

    stats = compute_stats(nodes, parse_errors, output)
    report.stats = stats
    # Rewrite with stats populated
    with output.open("w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, sort_keys=False)

    print(f"[index_be] total={stats['total']} parse_errors={stats['parse_errors']}")
    print("[index_be] by_kind:")
    for k, v in stats["by_kind"].items():
        print(f"    {k}: {v}")
    print("[index_be] by_persona:")
    for k, v in stats["by_persona"].items():
        print(f"    {k}: {v}")
    print(f"[index_be] output={output} size={stats['output_mb']} MB")

    # 3 sample entries per kind
    samples_by_kind: dict[str, list[IndexNode]] = {}
    for n in nodes.values():
        samples_by_kind.setdefault(n.kind, []).append(n)
    print("[index_be] samples:")
    for kind, lst in samples_by_kind.items():
        print(f"  -- {kind} --")
        for s in lst[:3]:
            print(f"    {s.node_id}")
            print(f"      summary: {s.summary[:140]}")


if __name__ == "__main__":
    main()
