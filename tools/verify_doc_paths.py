#!/usr/bin/env python3
"""Verify documentation integrity across vowerp3be and vowerp3ui.

Checks (both repos, assumed to be sibling directories):
  1. Every path-like token in the curated doc set points at a file/dir that exists.
  2. No stale Windows machine paths (c:\\code, C:\\Users) outside whitelisted historical dirs.
  3. Every .claude/agents/*.md and .claude/skills/*/SKILL.md has YAML frontmatter with a
     unique, non-empty `name` and a non-empty `description`.
  4. The module-* agent names/descriptions are identical across the two repos.
  5. Module guide docs carry a `Last verified:` stamp.
  6. Every approval-flows.md contains at least one mermaid block.

Stdlib only. Run from anywhere:  python tools/verify_doc_paths.py
Exit code 0 = clean, 1 = problems found (listed on stdout).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BE = Path(__file__).resolve().parent.parent
UI = BE.parent / "vowerp3ui"

# Files whose path references we verify
DOC_SETS = {
    BE: [
        "CLAUDE.md",
        "DOCUMENTATION_INDEX.md",
        ".claude/agents/*.md",
        ".claude/skills/*/SKILL.md",
    ],
    UI: [
        "CLAUDE.md",
        ".claude/agents/*.md",
        ".claude/skills/*/SKILL.md",
        "docs/claude/TEAM.md",
        "docs/claude/roles-and-users.md",
        "docs/claude/modules/**/*.md",
    ],
}

# Historical dirs where Windows paths are tolerated
WINDOWS_PATH_WHITELIST = (
    "docs/superpowers/",
    "docs/plans/",
    ".github/prompts/",
    "docs/yarn-quality/",  # historical feature docs
    "graphify-out/",
)

WINDOWS_RE = re.compile(r"[Cc]:[\\/](code|Users)")

# Path-like tokens we attempt to resolve: backtick-quoted, containing a slash,
# starting with a known root.
TOKEN_RE = re.compile(r"`([^`\n]+)`")
KNOWN_ROOTS = (
    "src/", "docs/", "dbqueries/", "tools/", "env/", ".claude/", ".github/",
    "graphify-out/", "../vowerp3be/", "../vowerp3ui/",
)
STANDALONE_FILES = (
    "CLAUDE.md", "DOCUMENTATION_INDEX.md", "AGENTS_GUIDE.md", "instructions.md", "README.md",
)
SKIP_CHARS = ("{", "}", "*", "<", ">", "$", "...", "|", "(", " OR ")

# Paths that are legitimate "create targets" (written at runtime / on first scaffold)
ALLOW_MISSING = (
    ".claude/agents/learnings/",
    "src/components/dashboard/widgets",
)

problems: list[str] = []


def note(msg: str) -> None:
    problems.append(msg)


def iter_docs(repo: Path):
    for pattern in DOC_SETS[repo]:
        yield from sorted(repo.glob(pattern))


def candidate_paths(text: str):
    for tok in TOKEN_RE.findall(text):
        tok = tok.strip().rstrip("/")
        # strip :line / :line-line suffixes
        tok = re.sub(r":\d+(-\d+)?$", "", tok)
        if any(s in tok for s in SKIP_CHARS):
            continue
        if tok in STANDALONE_FILES:
            yield tok
            continue
        if "/" not in tok:
            continue
        if tok.startswith(KNOWN_ROOTS):
            yield tok


def check_paths(repo: Path) -> None:
    sibling = UI if repo is BE else BE
    for doc in iter_docs(repo):
        text = doc.read_text(encoding="utf-8", errors="replace")
        rel_doc = doc.relative_to(repo)
        seen: set[str] = set()
        for tok in candidate_paths(text):
            if tok in seen:
                continue
            seen.add(tok)
            if tok.endswith(".log") or tok.startswith(ALLOW_MISSING):
                continue
            # Docs reference cross-repo files both with an explicit ../vowerp3{be,ui}/ prefix
            # and bare (when a table column / scope header states the repo) — accept either.
            if (repo / tok).resolve().exists() or (sibling / tok).resolve().exists():
                continue
            note(f"[missing-path] {repo.name}/{rel_doc}: `{tok}` not found in either repo")


def check_windows_paths(repo: Path) -> None:
    for md in sorted(repo.rglob("*.md")):
        rel = md.relative_to(repo).as_posix()
        if "node_modules" in rel:
            continue
        if any(rel.startswith(w) for w in WINDOWS_PATH_WHITELIST):
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        for m in WINDOWS_RE.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            note(f"[windows-path] {repo.name}/{rel}:{line_no}: stale machine path")
            break  # one report per file is enough


def parse_frontmatter(path: Path) -> dict[str, str] | None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fm: dict[str, str] = {}
    key = None
    for line in lines[1:]:
        if line.strip() == "---":
            return fm
        m = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if m:
            key = m.group(1)
            fm[key] = m.group(2).strip()
        elif key and line.startswith(" "):
            fm[key] += " " + line.strip()
    return None  # never closed


def check_frontmatter(repo: Path) -> dict[str, dict[str, str]]:
    seen: dict[str, Path] = {}
    agents: dict[str, dict[str, str]] = {}
    files = sorted(repo.glob(".claude/agents/*.md")) + sorted(repo.glob(".claude/skills/*/SKILL.md"))
    for f in files:
        rel = f.relative_to(repo)
        fm = parse_frontmatter(f)
        if fm is None:
            note(f"[frontmatter] {repo.name}/{rel}: missing or unclosed YAML frontmatter")
            continue
        name = fm.get("name", "")
        desc = fm.get("description", "")
        if not name:
            note(f"[frontmatter] {repo.name}/{rel}: empty `name`")
        if not desc:
            note(f"[frontmatter] {repo.name}/{rel}: empty `description`")
        if name in seen:
            note(f"[frontmatter] {repo.name}/{rel}: duplicate name `{name}` (also {seen[name]})")
        seen[name] = rel
        if name.startswith("module-"):
            agents[name] = {"description": desc}
    return agents


def check_module_parity(be_agents, ui_agents) -> None:
    for name in sorted(set(be_agents) | set(ui_agents)):
        if name not in be_agents:
            note(f"[parity] module agent `{name}` exists in vowerp3ui but not vowerp3be")
        elif name not in ui_agents:
            note(f"[parity] module agent `{name}` exists in vowerp3be but not vowerp3ui")
        elif be_agents[name]["description"] != ui_agents[name]["description"]:
            note(f"[parity] module agent `{name}`: descriptions differ between repos")


def check_stamps_and_mermaid() -> None:
    stamped = (
        list(UI.glob(".claude/agents/module-*.md"))
        + list(BE.glob(".claude/agents/module-*.md"))
        + list(UI.glob("docs/claude/modules/**/*.md"))
        + [UI / "docs/claude/TEAM.md", UI / "docs/claude/roles-and-users.md"]
    )
    for f in stamped:
        if not f.exists():
            continue
        repo = UI if str(f).startswith(str(UI)) else BE
        text = f.read_text(encoding="utf-8", errors="replace")
        if "Last verified:" not in text:
            note(f"[stamp] {repo.name}/{f.relative_to(repo)}: missing `Last verified:` stamp")
    for f in UI.glob("docs/claude/modules/*/approval-flows.md"):
        if "```mermaid" not in f.read_text(encoding="utf-8", errors="replace"):
            note(f"[mermaid] {f.relative_to(UI)}: approval-flows.md without a mermaid block")


def main() -> int:
    for repo in (BE, UI):
        if not repo.exists():
            print(f"FATAL: repo not found: {repo}")
            return 1
    for repo in (BE, UI):
        check_paths(repo)
        check_windows_paths(repo)
    be_agents = check_frontmatter(BE)
    ui_agents = check_frontmatter(UI)
    check_module_parity(be_agents, ui_agents)
    check_stamps_and_mermaid()

    if problems:
        print(f"{len(problems)} problem(s) found:\n")
        for p in problems:
            print(" -", p)
        return 1
    print("All documentation checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
