---
description: Find a node (endpoint/page/hook/model/function) by natural-language description
argument-hint: <natural language query>
---

Query the VoWERP3 knowledge graph to locate a node matching the user's description. Run:

```bash
python tools/graph_query.py --find "$ARGUMENTS" -k 5
```

Then:

1. Report the top 3 hits. Format each as a single line:
   `[kind] node_id — summary — file:line`
2. For any result flagged `confidence: low` or `stale: true`, note it explicitly and recommend reading the source file to verify the summary.
3. If no result scores above the tool's confidence threshold (or the tool reports "no strong match"), say so plainly and suggest: broaden the query, try `/graph-reuse` for similar-functionality search, or fall back to Grep.
4. Do not dump source code. Summaries and locations only.

Keep the response scannable. No preamble.
