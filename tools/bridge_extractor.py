"""Cross-repo API bridge extractor — Layer 1.5 of the graphify/descriptive-index plan.

Emits `graphify-out/bridge.json` with:
  - matched:        frontend const -> backend endpoint edges
  - dead_routes:    frontend consts with no backend match
  - orphan_endpoints: backend endpoints no frontend const points at

Runs standalone on stdlib only. Paths are hardcoded to the two sibling repos;
override via CLI args if layout changes.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

FE_REPO_DEFAULT = Path(r"c:\code\vowerp3ui")
BE_REPO_DEFAULT = Path(r"c:\code\vowerp3be")
API_URL_RUNTIME_PREFIX = "/api"  # ${API_URL} resolves to /api in the FastAPI layout

FE_ROUTE_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*:\s*`\$\{API_URL\}([^`]+)`\s*,?\s*(?://.*)?$"
)
FE_OBJECT_OPEN_RE = re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*\{")
FE_OBJECT_CLOSE_RE = re.compile(r"^\s*\}\s*;?\s*(?://.*)?$")

BE_IMPORT_RE = re.compile(
    r"^from\s+(src\.[\w\.]+)\s+import\s+(\w+)\s+as\s+(\w+)\s*$"
)
BE_INCLUDE_RE = re.compile(
    r'^\s*app\.include_router\(\s*(\w+)\s*,\s*prefix\s*=\s*"([^"]+)"'
)


def _decorator_regex(var_name: str) -> re.Pattern[str]:
    return re.compile(
        rf'^\s*@{re.escape(var_name)}\.(get|post|put|delete|patch)\(\s*"([^"]+)"'
    )


def _api_route_regex(var_name: str) -> re.Pattern[str]:
    return re.compile(
        rf'^\s*@{re.escape(var_name)}\.api_route\(\s*"([^"]+)"\s*,\s*methods\s*=\s*\[([^\]]+)\]'
    )

SKIP_DIR_PARTS = {"test", "models", "config", "__pycache__", ".venv", "migrations"}
SKIP_FILE_BASENAMES = {"query.py", "models.py", "constants.py", "schemas.py"}


@dataclass
class FrontendRoute:
    const_name: str
    persona_family: str
    url_path: str  # what follows ${API_URL}, e.g. "/itemMaster/get_all_item_groups"
    fe_file: str
    fe_line: int


@dataclass
class BackendEndpoint:
    method: str
    prefix: str
    path: str
    full_path: str
    be_file: str
    be_line: int


@dataclass
class BridgeEdge:
    const_name: str
    persona_family: str
    url_path: str
    fe_location: str
    be_method: str
    be_prefix: str
    be_path: str
    be_location: str
    match_kind: str  # "exact" | "stripped_params"


@dataclass
class Report:
    generated_at: str
    frontend_file: str
    backend_root: str
    assumptions: dict
    stats: dict
    matched: list[dict] = field(default_factory=list)
    dead_routes: list[dict] = field(default_factory=list)
    orphan_endpoints: list[dict] = field(default_factory=list)


def parse_frontend(api_ts: Path) -> list[FrontendRoute]:
    routes: list[FrontendRoute] = []
    current_family: str | None = None
    with api_ts.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            if m := FE_OBJECT_OPEN_RE.match(raw):
                current_family = m.group(1)
                continue
            if current_family and FE_OBJECT_CLOSE_RE.match(raw):
                current_family = None
                continue
            if current_family is None:
                continue
            if m := FE_ROUTE_RE.match(raw):
                routes.append(
                    FrontendRoute(
                        const_name=m.group(1),
                        persona_family=current_family,
                        url_path=m.group(2),
                        fe_file=str(api_ts),
                        fe_line=lineno,
                    )
                )
    return routes


def parse_main_py(main_py: Path) -> dict[str, tuple[str, str, str]]:
    """alias -> (module_dotted, imported_var_name, prefix).

    Most routers import `router as X`, but a few import a differently-named
    variable (e.g. `common_router as auth_router` from authorization.routers).
    We track both so the per-file decorator regex can use the right name.
    """
    imports: dict[str, tuple[str, str]] = {}  # alias -> (module, imported_name)
    includes: dict[str, str] = {}
    with main_py.open(encoding="utf-8") as f:
        for raw in f:
            if m := BE_IMPORT_RE.match(raw):
                module, imported_name, alias = m.group(1), m.group(2), m.group(3)
                imports[alias] = (module, imported_name)
            elif m := BE_INCLUDE_RE.match(raw):
                alias, prefix = m.group(1), m.group(2)
                includes[alias] = prefix
    mapping: dict[str, tuple[str, str, str]] = {}
    for alias, prefix in includes.items():
        if pair := imports.get(alias):
            module, imported_name = pair
            mapping[alias] = (module, imported_name, prefix)
    return mapping


def module_to_path(be_repo: Path, module_dotted: str) -> Path:
    return be_repo / Path(*module_dotted.split(".")).with_suffix(".py")


def parse_router_file(
    py_file: Path, prefix: str, router_var: str
) -> list[BackendEndpoint]:
    endpoints: list[BackendEndpoint] = []
    decorator_re = _decorator_regex(router_var)
    api_route_re = _api_route_regex(router_var)
    with py_file.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            if m := decorator_re.match(raw):
                method, path = m.group(1).upper(), m.group(2)
                endpoints.append(
                    BackendEndpoint(
                        method=method,
                        prefix=prefix,
                        path=path,
                        full_path=prefix + path,
                        be_file=str(py_file),
                        be_line=lineno,
                    )
                )
            elif m := api_route_re.match(raw):
                path = m.group(1)
                methods_raw = m.group(2)
                methods = [
                    mm.strip().strip("\"'").upper()
                    for mm in methods_raw.split(",")
                    if mm.strip()
                ]
                for method in methods:
                    endpoints.append(
                        BackendEndpoint(
                            method=method,
                            prefix=prefix,
                            path=path,
                            full_path=prefix + path,
                            be_file=str(py_file),
                            be_line=lineno,
                        )
                    )
    return endpoints


def collect_backend_endpoints(
    be_repo: Path, router_map: dict[str, tuple[str, str, str]]
) -> list[BackendEndpoint]:
    endpoints: list[BackendEndpoint] = []
    for _alias, (module_dotted, router_var, prefix) in router_map.items():
        py_file = module_to_path(be_repo, module_dotted)
        if not py_file.exists():
            continue
        endpoints.extend(parse_router_file(py_file, prefix, router_var))
    return endpoints


def strip_trailing_params(full_path: str) -> str:
    """Collapse trailing `/{param}` segments (up to 3 deep) for frontend-FE matching.
    Frontend constants are the static prefix; IDs are appended in the hook.
    """
    cleaned = full_path
    for _ in range(3):
        new = re.sub(r"/\{[^/]+\}$", "", cleaned)
        if new == cleaned:
            break
        cleaned = new
    return cleaned


def build_backend_index(
    endpoints: list[BackendEndpoint],
) -> dict[str, list[BackendEndpoint]]:
    """Key endpoints by the path a frontend constant would use (strip /api prefix and trailing params)."""
    index: dict[str, list[BackendEndpoint]] = {}
    for ep in endpoints:
        fe_equivalent = ep.full_path
        if fe_equivalent.startswith(API_URL_RUNTIME_PREFIX):
            fe_equivalent = fe_equivalent[len(API_URL_RUNTIME_PREFIX):]
        stripped = strip_trailing_params(fe_equivalent)
        index.setdefault(stripped, []).append(ep)
        if stripped != fe_equivalent:
            index.setdefault(fe_equivalent, []).append(ep)
    return index


def match_routes(
    fe_routes: list[FrontendRoute],
    be_endpoints: list[BackendEndpoint],
) -> tuple[list[BridgeEdge], list[FrontendRoute], list[BackendEndpoint]]:
    be_index = build_backend_index(be_endpoints)
    seen_eps: set[tuple[str, str]] = set()
    matched: list[BridgeEdge] = []
    dead: list[FrontendRoute] = []

    for fr in fe_routes:
        lookup_path = fr.url_path
        hits = be_index.get(lookup_path)
        match_kind = "exact"
        if not hits:
            hits = be_index.get(strip_trailing_params(lookup_path))
            match_kind = "stripped_params" if hits else match_kind
        if not hits:
            dead.append(fr)
            continue
        for ep in hits:
            matched.append(
                BridgeEdge(
                    const_name=fr.const_name,
                    persona_family=fr.persona_family,
                    url_path=fr.url_path,
                    fe_location=f"{fr.fe_file}:{fr.fe_line}",
                    be_method=ep.method,
                    be_prefix=ep.prefix,
                    be_path=ep.path,
                    be_location=f"{ep.be_file}:{ep.be_line}",
                    match_kind=match_kind,
                )
            )
            seen_eps.add((ep.be_file, f"{ep.method} {ep.full_path}"))

    orphans = [
        ep
        for ep in be_endpoints
        if (ep.be_file, f"{ep.method} {ep.full_path}") not in seen_eps
    ]
    return matched, dead, orphans


def build_report(
    fe_routes: list[FrontendRoute],
    be_endpoints: list[BackendEndpoint],
    matched: list[BridgeEdge],
    dead: list[FrontendRoute],
    orphans: list[BackendEndpoint],
    fe_repo: Path,
    be_repo: Path,
) -> Report:
    matched_const_count = len({m.const_name for m in matched})
    match_rate = matched_const_count / len(fe_routes) if fe_routes else 0.0
    return Report(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        frontend_file=str(fe_repo / "src" / "utils" / "api.ts"),
        backend_root=str(be_repo / "src"),
        assumptions={
            "api_url_runtime_prefix": API_URL_RUNTIME_PREFIX,
            "skip_dir_parts": sorted(SKIP_DIR_PARTS),
            "skip_file_basenames": sorted(SKIP_FILE_BASENAMES),
        },
        stats={
            "fe_constants": len(fe_routes),
            "be_endpoints": len(be_endpoints),
            "matched_edges": len(matched),
            "matched_constants": matched_const_count,
            "dead_routes": len(dead),
            "orphan_endpoints": len(orphans),
            "match_rate": round(match_rate, 3),
        },
        matched=[asdict(m) for m in matched],
        dead_routes=[
            {
                "const_name": r.const_name,
                "persona_family": r.persona_family,
                "url_path": r.url_path,
                "fe_location": f"{r.fe_file}:{r.fe_line}",
            }
            for r in dead
        ],
        orphan_endpoints=[
            {
                "method": e.method,
                "prefix": e.prefix,
                "path": e.path,
                "full_path": e.full_path,
                "be_location": f"{e.be_file}:{e.be_line}",
            }
            for e in orphans
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fe-repo", type=Path, default=FE_REPO_DEFAULT)
    parser.add_argument("--be-repo", type=Path, default=BE_REPO_DEFAULT)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Defaults to {be-repo}/graphify-out/bridge.json",
    )
    args = parser.parse_args()

    output = args.output or (args.be_repo / "graphify-out" / "bridge.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    api_ts = args.fe_repo / "src" / "utils" / "api.ts"
    main_py = args.be_repo / "src" / "main.py"

    fe_routes = parse_frontend(api_ts)
    router_map = parse_main_py(main_py)
    be_endpoints = collect_backend_endpoints(args.be_repo, router_map)

    matched, dead, orphans = match_routes(fe_routes, be_endpoints)
    report = build_report(
        fe_routes, be_endpoints, matched, dead, orphans, args.fe_repo, args.be_repo
    )

    with output.open("w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, sort_keys=False)

    s = report.stats
    print(f"[bridge] fe_constants={s['fe_constants']} be_endpoints={s['be_endpoints']}")
    print(
        f"[bridge] matched_constants={s['matched_constants']} "
        f"dead={s['dead_routes']} orphans={s['orphan_endpoints']} "
        f"match_rate={s['match_rate']}"
    )
    print(f"[bridge] wrote {output}")


if __name__ == "__main__":
    main()
