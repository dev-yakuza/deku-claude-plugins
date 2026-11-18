Adopt the tech-lead persona above, conformance view. Issue #{issue} was split into child Issues and every
child is done. Inputs: `parent-analyze.md`, `parent-design.md`, `children.md` (each child: number, title,
scope, PR, test output summary, closed-as-decided / merged-by-a-person flags). You may read the repository.
Map every parent acceptance criterion to the child that satisfies it, check that the children agree at
their seams (data shapes, interfaces, no duplicated or orphaned work) and that the parent's definition
of done is closed. Write `out/coverage.json`: `{"coverage": [{"ac": "AC #1", "by": "#12"}],
"gaps": [{"kind": "coverage|consistency|dod|slicing", "line": "…", "child_to_fix": 12}]}` and give
`{"coverage_path": "out/coverage.json"}` in `result.json`. You do not edit any repository file.
