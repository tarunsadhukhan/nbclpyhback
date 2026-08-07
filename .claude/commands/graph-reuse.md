---
description: Find existing query functions / service functions / helpers that do something similar
argument-hint: <description of what you want to do>
---

Find reusable existing code in the VoWERP3 codebase before writing new. Run:

```bash
python tools/graph_query.py --reuse "$ARGUMENTS" -k 5
```

Then:

1. Report the top 3-5 candidates. For each:
   - summary (what it does)
   - one-sentence "why it might match"
   - `file:line`
2. If the tool surfaces 1-hop neighbors (e.g. endpoints that call a query function), mention them briefly — that signals real-world reuse.
3. If the top candidate scores high, **recommend reusing it** over writing new code. If scores are mediocre, say reuse is unclear and suggest reading the top 1-2 candidates before deciding.
4. Flag any `confidence: low` or `stale: true` results.
5. No raw source. Summaries only.
