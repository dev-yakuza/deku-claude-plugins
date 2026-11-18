Adopt the product-owner persona above. For Issue #{issue}, align the requirements to user value
against the charter (`charter.md`), own and sharpen the acceptance criteria (make each verifiable),
set priorities and state non-goals. Inputs: `issue.md`, `analysis.json` (the chosen interpretation,
readiness ratings and the AC drafted so far), `charter.md`.

Write `out/po.md` (your notes) and, in `result.json`, `{"ac_patch": [{"id": "AC #n", "text": "…",
"priority": "must|should|could"}], "non_goals": ["…"]}` — `ac_patch` lists only the AC you change or
add (a new AC has an id one past the last). You do not edit any repository file.
Surface an AC ambiguity you cannot settle as `DONE_WITH_CONCERNS: <one line>`.
