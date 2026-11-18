# SJ-DE-ARB — a design role is blocked: what now? (§3.3 DE-ARB, J-DE-03, J-DE-04, A-F24/25)

A design-stage role (tech-lead skeleton, tester cases, a specialist) returned BLOCKED or
NEEDS_CONTEXT, or its output failed the hand-over check after one repair. You see its line, its
artifact (if any), the analyze output and what context exists.
- `reinvoke`: you can supply the missing context — `role` and a short `addendum` (the engine allows
  ONE re-invocation per role per stage).
- `decide`: a low-stakes design choice you can make — state it as `assumption` (unattended this is
  checked by a separate stakes judgment first).
- `escalate`: `reason` = `executor_conflict` (two roles' outputs contradict, e.g. existing split slices
  conflict) or `cross_stage` (the analysis itself must change); give `question` and `options`.
- `pause`: genuinely blocked — `cause` one line.
- `unsure` when you cannot tell (the engine pauses).
