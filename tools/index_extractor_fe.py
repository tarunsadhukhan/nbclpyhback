"""Layer 1 frontend content index extractor for vowerp3ui.

Walks the Next.js App Router frontend with a surgical scope:
  - pages (src/app/**/page.tsx)
  - hooks (src/**/use*.ts{,x})
  - service_fn (src/utils/*Service.ts)
  - api_route_const (src/utils/api.ts)
  - domain_component (src/components/**/*.tsx, excluding src/components/ui/)

Emits {be-repo}/graphify-out/index_fe.json keyed by node_id. Stdlib only,
regex-based (no real AST) — the goal is declaration-level info, not type
checking. Paired with tools/bridge_extractor.py (cross-repo API mapping) and
the backend sibling tools/index_extractor_be.py.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

FE_REPO_DEFAULT = Path(r"c:\code\vowerp3ui")
BE_REPO_DEFAULT = Path(r"c:\code\vowerp3be")
OUTPUT_DEFAULT = BE_REPO_DEFAULT / "graphify-out" / "index_fe.json"

# -------- regexes --------
PAGE_DEFAULT_FN_RE = re.compile(r"^\s*export\s+default\s+(?:async\s+)?function\s+(\w+)", re.M)
PAGE_DEFAULT_IDENT_RE = re.compile(r"^\s*export\s+default\s+(\w+)\s*;?\s*$", re.M)
CONST_COMP_RE = re.compile(
    r"^\s*(?:const|function)\s+(\w+)\s*[:=]?\s*(?:\([^)]*\)|\w+)?\s*(?:=|=>|\{)?",
    re.M,
)

HOOK_FN_RE = re.compile(r"^\s*export\s+(?:async\s+)?function\s+(use\w+)\s*\(", re.M)
HOOK_CONST_RE = re.compile(r"^\s*export\s+const\s+(use\w+)\s*=\s*(?:async\s+)?\(", re.M)

SVC_FN_RE = re.compile(r"^\s*export\s+(?:async\s+)?function\s+(\w+)\s*\(", re.M)
SVC_CONST_RE = re.compile(r"^\s*export\s+const\s+(\w+)\s*=\s*(?:async\s+)?\(", re.M)

FE_ROUTE_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*:\s*`\$\{API_URL\}([^`]+)`")
FE_OBJECT_OPEN_RE = re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*\{")
FE_OBJECT_CLOSE_RE = re.compile(r"^\s*\}\s*;?\s*(?://.*)?$")

IMPORT_RE = re.compile(
    r"^\s*import\s+(?:type\s+)?(?:(\*\s+as\s+\w+)|\{([^}]+)\}|(\w+)(?:\s*,\s*\{([^}]+)\})?)?\s*from\s+['\"]([^'\"]+)['\"]",
    re.M,
)

INTERNAL_PREFIXES = ("@/", "./", "../", "src/")
PERSONA_MAP = {
    "dashboardportal": "portal",
    "dashboardadmin": "companyAdmin",
    "dashboardctrldesk": "ctrldskAdmin",
}


# -------- data --------
@dataclass
class Node:
    node_id: str
    kind: str
    persona: str | None
    file: str
    line: int
    name: str
    exports: str  # "default" | "named"
    summary: str
    confidence: str
    hash: str
    last_indexed_at: str
    imports_of_interest: list[str] = field(default_factory=list)
    route: str | None = None
    url_path: str | None = None
    persona_family: str | None = None


# -------- helpers --------
def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def file_hash(head_lines: list[str], decl_line: str) -> str:
    blob = "".join(head_lines[:30]) + "\n" + decl_line
    return hashlib.sha256(blob.encode("utf-8", errors="replace")).hexdigest()[:16]


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def head_lines(text: str, n: int = 30) -> list[str]:
    return text.splitlines(keepends=True)[:n]


def infer_persona_from_path(rel_path: str) -> str | None:
    parts = rel_path.split("/")
    for seg in parts:
        if seg in PERSONA_MAP:
            return PERSONA_MAP[seg]
    return None


def line_of_match(text: str, match: re.Match[str]) -> int:
    return text.count("\n", 0, match.start()) + 1


def extract_imports(text: str) -> list[tuple[list[str], str]]:
    out: list[tuple[list[str], str]] = []
    for m in IMPORT_RE.finditer(text):
        star_as, named, default, default_named, module = m.groups()
        if not module.startswith(INTERNAL_PREFIXES):
            continue
        idents: list[str] = []
        if default:
            idents.append(default)
        if default_named:
            idents.extend(s.strip().split(" as ")[0].strip() for s in default_named.split(","))
        if named:
            idents.extend(s.strip().split(" as ")[0].strip() for s in named.split(","))
        if star_as:
            idents.append(star_as.split(" as ")[-1].strip())
        idents = [i for i in idents if i]
        if idents:
            out.append((idents, module))
    return out


def imports_of_interest(text: str, limit: int = 5) -> list[str]:
    flagged: list[str] = []
    for idents, module in extract_imports(text):
        is_hook = any(i.startswith("use") and len(i) > 3 and i[3].isupper() for i in idents)
        is_service = "Service" in module or module.endswith("Service")
        is_api = module.endswith("/api") or module.endswith("utils/api") or "/api.ts" in module
        if is_hook or is_service or is_api:
            flagged.extend(idents)
    # Deduplicate preserving order
    seen: set[str] = set()
    unique = []
    for name in flagged:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique[:limit]


def route_from_page(rel_path: str) -> str:
    assert rel_path.startswith("src/app/") and rel_path.endswith("/page.tsx")
    inner = rel_path[len("src/app/"): -len("/page.tsx")]
    return "/" + inner


def detect_default_export(text: str) -> tuple[str | None, int]:
    m = PAGE_DEFAULT_FN_RE.search(text)
    if m:
        return m.group(1), line_of_match(text, m)
    m = PAGE_DEFAULT_IDENT_RE.search(text)
    if m:
        return m.group(1), line_of_match(text, m)
    return None, 0


# -------- scanners --------
def scan_pages(fe_root: Path) -> Iterable[tuple[Node, Path]]:
    app_dir = fe_root / "src" / "app"
    for path in app_dir.rglob("page.tsx"):
        if ".next" in path.parts:
            continue
        text = read_text(path)
        if text is None:
            yield None, path  # type: ignore[misc]
            continue
        name, line = detect_default_export(text)
        if not name:
            # anonymous export default; fall back to folder name
            name = path.parent.name or "Page"
            line = 1
        rel_path = rel(path, fe_root)
        route = route_from_page(rel_path)
        persona = infer_persona_from_path(rel_path)
        hooks_svcs = imports_of_interest(text)
        summary = (
            f"{route} — Next.js page component {name}"
            + (f"; uses {', '.join(hooks_svcs[:3])}" if hooks_svcs else "")
        )
        head = head_lines(text)
        decl = text.splitlines()[line - 1] if 0 < line <= len(text.splitlines()) else ""
        node = Node(
            node_id=f"{rel_path}:{name}",
            kind="page",
            persona=persona,
            file=rel_path,
            line=line,
            name=name,
            exports="default",
            summary=summary,
            confidence="low",
            hash=file_hash(head, decl),
            last_indexed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            imports_of_interest=hooks_svcs,
            route=route,
        )
        yield node, path


def _is_hook_file(path: Path) -> bool:
    name = path.name
    if not name.startswith("use"):
        return False
    if ".test." in name:
        return False
    if name.endswith(".d.ts"):
        return False
    return name.endswith(".ts") or name.endswith(".tsx")


def scan_hooks(fe_root: Path) -> Iterable[tuple[Node, Path]]:
    src_dir = fe_root / "src"
    for path in src_dir.rglob("use*.*"):
        if not _is_hook_file(path):
            continue
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        text = read_text(path)
        if text is None:
            yield None, path  # type: ignore[misc]
            continue
        rel_path = rel(path, fe_root)
        persona = infer_persona_from_path(rel_path)
        head = head_lines(text)
        lines = text.splitlines()
        found_any = False
        for regex in (HOOK_FN_RE, HOOK_CONST_RE):
            for m in regex.finditer(text):
                found_any = True
                name = m.group(1)
                line = line_of_match(text, m)
                decl = lines[line - 1] if 0 < line <= len(lines) else ""
                # first-line signature: trim up to first closing paren
                sig_end = decl.find(")")
                signature = decl[: sig_end + 1] if sig_end != -1 else decl.strip()
                summary = (
                    f"{name} — custom React hook in {rel_path}; signature: {signature.strip()}"
                )
                node = Node(
                    node_id=f"{rel_path}:{name}",
                    kind="hook",
                    persona=persona,
                    file=rel_path,
                    line=line,
                    name=name,
                    exports="named",
                    summary=summary,
                    confidence="low",
                    hash=file_hash(head, decl),
                    last_indexed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    imports_of_interest=imports_of_interest(text),
                )
                yield node, path
        if not found_any:
            # fallback: name derived from filename
            base = path.stem
            node = Node(
                node_id=f"{rel_path}:{base}",
                kind="hook",
                persona=persona,
                file=rel_path,
                line=1,
                name=base,
                exports="named",
                summary=f"{base} — custom React hook in {rel_path}",
                confidence="low",
                hash=file_hash(head, ""),
                last_indexed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                imports_of_interest=imports_of_interest(text),
            )
            yield node, path


def scan_services(fe_root: Path) -> Iterable[tuple[Node, Path]]:
    utils = fe_root / "src" / "utils"
    for path in utils.glob("*Service.ts"):
        if ".test." in path.name:
            continue
        text = read_text(path)
        if text is None:
            yield None, path  # type: ignore[misc]
            continue
        rel_path = rel(path, fe_root)
        head = head_lines(text)
        lines = text.splitlines()
        seen_names: set[str] = set()
        for regex in (SVC_FN_RE, SVC_CONST_RE):
            for m in regex.finditer(text):
                name = m.group(1)
                if name in seen_names:
                    continue
                seen_names.add(name)
                line = line_of_match(text, m)
                decl = lines[line - 1] if 0 < line <= len(lines) else ""
                summary = f"{name} — service function in {rel_path}"
                node = Node(
                    node_id=f"{rel_path}:{name}",
                    kind="service_fn",
                    persona=None,
                    file=rel_path,
                    line=line,
                    name=name,
                    exports="named",
                    summary=summary,
                    confidence="low",
                    hash=file_hash(head, decl),
                    last_indexed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    imports_of_interest=imports_of_interest(text),
                )
                yield node, path


def scan_api_routes(fe_root: Path) -> Iterable[tuple[Node, Path]]:
    api_ts = fe_root / "src" / "utils" / "api.ts"
    text = read_text(api_ts)
    if text is None:
        return
    rel_path = rel(api_ts, fe_root)
    head = head_lines(text)
    current_family: str | None = None
    for lineno, raw in enumerate(text.splitlines(keepends=True), start=1):
        if m := FE_OBJECT_OPEN_RE.match(raw):
            current_family = m.group(1)
            continue
        if current_family and FE_OBJECT_CLOSE_RE.match(raw):
            current_family = None
            continue
        if current_family is None:
            continue
        if m := FE_ROUTE_RE.match(raw):
            const_name = m.group(1)
            url_path = m.group(2)
            summary = f"{const_name} = {current_family}.{url_path}"
            node = Node(
                node_id=f"{rel_path}:{const_name}",
                kind="api_route_const",
                persona=None,
                file=rel_path,
                line=lineno,
                name=const_name,
                exports="named",
                summary=summary,
                confidence="low",
                hash=file_hash(head, raw),
                last_indexed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                url_path=url_path,
                persona_family=current_family,
            )
            yield node, api_ts


def scan_domain_components(fe_root: Path) -> Iterable[tuple[Node, Path]]:
    comp_dir = fe_root / "src" / "components"
    if not comp_dir.exists():
        return
    for path in comp_dir.rglob("*.tsx"):
        parts_lower = [p.lower() for p in path.relative_to(comp_dir).parts]
        if parts_lower and parts_lower[0] == "ui":
            continue
        if ".test." in path.name or path.name.endswith(".stories.tsx"):
            continue
        text = read_text(path)
        if text is None:
            yield None, path  # type: ignore[misc]
            continue
        name, line = detect_default_export(text)
        if not name:
            continue  # only index default-exported components
        rel_path = rel(path, fe_root)
        head = head_lines(text)
        lines = text.splitlines()
        decl = lines[line - 1] if 0 < line <= len(lines) else ""
        summary = f"{name} — domain component at {rel_path}"
        node = Node(
            node_id=f"{rel_path}:{name}",
            kind="domain_component",
            persona=infer_persona_from_path(rel_path),
            file=rel_path,
            line=line,
            name=name,
            exports="default",
            summary=summary,
            confidence="low",
            hash=file_hash(head, decl),
            last_indexed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            imports_of_interest=imports_of_interest(text),
        )
        yield node, path


# -------- driver --------
def build_index(fe_root: Path) -> tuple[dict[str, dict], dict]:
    nodes: dict[str, dict] = {}
    files_scanned: set[str] = set()
    parse_errors = 0
    by_kind: dict[str, int] = {}
    by_persona: dict[str, int] = {}

    scanners = [
        ("page", scan_pages),
        ("hook", scan_hooks),
        ("service_fn", scan_services),
        ("api_route_const", scan_api_routes),
        ("domain_component", scan_domain_components),
    ]

    for _kind_name, scanner in scanners:
        for node, path in scanner(fe_root):
            files_scanned.add(str(path))
            if node is None:
                parse_errors += 1
                continue
            if node.node_id in nodes:
                continue
            data = asdict(node)
            # drop None-valued optional keys to keep JSON tight
            for opt_key in ("route", "url_path", "persona_family"):
                if data.get(opt_key) is None:
                    data.pop(opt_key, None)
            nodes[node.node_id] = data
            by_kind[node.kind] = by_kind.get(node.kind, 0) + 1
            persona_key = node.persona or "null"
            by_persona[persona_key] = by_persona.get(persona_key, 0) + 1

    stats = {
        "total": len(nodes),
        "by_kind": by_kind,
        "by_persona": by_persona,
        "parse_errors": parse_errors,
        "files_scanned": len(files_scanned),
    }
    return nodes, stats


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fe-repo", type=Path, default=FE_REPO_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    nodes, stats = build_index(args.fe_repo)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "frontend_root": str(args.fe_repo / "src"),
        "stats": stats,
        "nodes": nodes,
    }
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=False)

    print(f"[index_fe] total={stats['total']} by_kind={stats['by_kind']}")
    print(f"[index_fe] by_persona={stats['by_persona']}")
    print(
        f"[index_fe] parse_errors={stats['parse_errors']} "
        f"files_scanned={stats['files_scanned']}"
    )
    print(f"[index_fe] wrote {args.output}")


if __name__ == "__main__":
    main()
