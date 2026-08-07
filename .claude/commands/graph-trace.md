---
description: Trace the chain from table / function / entity across query functions, endpoints, and frontend
argument-hint: <table_name | function_name | entity_name>
---

Trace how an entity flows through the VoWERP3 stack. Run:

```bash
python tools/graph_query.py --trace "$ARGUMENTS"
```

Then:

1. If the tool's tree output is under ~30 lines, render it verbatim in a fenced block.
2. If longer, summarize the main chain: table → query functions → endpoints → frontend hooks/pages. Keep it scannable.
3. If the trace surfaces a header/detail/cancel traceability chain (e.g. `proc_indent_dtl → proc_po_dtl → proc_inward_dtl → issue_li`, or any `*_dtl → *_dtl_cancel`), call it out explicitly — these chains are documented in the backend CLAUDE.md and must be preserved when extending downstream tables.
4. Flag any `confidence: low` or `stale: true` nodes.
5. If no chain is found, suggest checking the spelling of the table or function name, or trying `/graph-find` to locate the entity first.
6. Summaries and locations only. No source dumps.
