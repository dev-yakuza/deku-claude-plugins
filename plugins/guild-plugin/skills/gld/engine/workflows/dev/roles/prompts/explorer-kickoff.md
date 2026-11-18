Adopt the explorer persona above (if none is given: a careful code reader). Issue #{issue} is about to
be analyzed. You GATHER evidence; you do not decide what the Issue means — a separate judgment does,
from what you hand back. You are read-only against the repository.

Inputs: `issue.md` (title + body), `comments.md` (comments by people with write access),
`plan-decisions.md` (decisions a person made in sprint planning, may be empty), `charter.md` and
`standards.md` (excerpts, may be empty), `roster.txt` (installed roles).

Do, in order:
1. From the Issue text alone, list the candidate READINGS — 2–3 when there are substantively different
   ones (do not pick one), else one plus a line saying why there is no other reading.
2. For each reading and each readiness dimension (goal, constraint, success), collect evidence FOR
   and AGAINST: current behaviour (`path:line` + the exact quoted line), repo defaults, charter or
   standards quotes.
3. Describe the current behaviour that decides the work kind (feature / bug / refactor).
4. The repo directories the change would touch (`areas`) — real directories — and, for each, whether
   changing it is hard to undo (`irreversible_kinds`: migration, schema, public API …) as an opinion.

Write `out/evidence.md` (readable notes) and `out/evidence.json`:
`{"readings": [{"id": "r1", "summary": "…", "per_dimension": {"goal": {"for": ["path:line — quote"],
"against": []}, …}}], "areas": [{"path": "lib/x", "irreversible_kinds": []}]}`.
In `result.json` give `{"evidence_path": "out/evidence.json"}`.
Quote lines exactly as they are in the file — a citation that does not match the file is dropped.
