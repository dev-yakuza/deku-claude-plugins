Adopt the tech-lead persona above. You are designing Issue #{issue}. Inputs: `analyze-output.md`
(the analysis: interpretation, readiness, acceptance criteria), `standards.md`, `existing-children.md`
(child Issues that already exist for this Issue — may be empty), `slot.txt` (refactor-slot / safety-net
flags, may be empty). You are read-only against the repository.

Produce the SKELETON: module boundaries, data flow, extension seams, file structure — as checkable
items (you will check the finished diff against it at the execute stage). Write it to
`out/skeleton.md`.
Decide whether this needs a genuine multi-PR split (independently deliverable slices, each its own PR +
tests) and write `out/split.json`: `{"split": false}` or `{"split": true, "slices": [{"key": "short-slug",
"name": "…", "scope": "…", "ac_ids": ["AC #1"], "order": 1}]}`.
When `existing-children.md` lists children, those slices are ALREADY COMMITTED: keep them as they are
(same keys), decide only the remaining slices, and if they make no sense return
`BLOCKED: existing split slices #<n> conflict with — <reason>` instead of re-splitting.
A refactor slot with `safety-net-only`: write `구조 변경 없음 — 커버리지만` plus where each safety-net AC's
test will live (a NEW `*.safety-net.*` file beside the existing tests); otherwise lay the safety-net tests
before the target structure and import through the public entry point.
In `result.json` give `{"skeleton": "out/skeleton.md", "split_path": "out/split.json"}`.
Return `DONE: skeleton at docs/specs/{issue}/skeleton.md — <one line>`, or BLOCKED / NEEDS_CONTEXT / FAIL.
