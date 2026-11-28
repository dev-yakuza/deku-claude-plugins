Design the change and write the **skeleton** to `docs/specs/<issue>/skeleton.md`: module boundaries, data flow, extension seams, file structure, and the technical direction — read `analysis.md`, `test-cases.md` and the repository (`docs/standards/architecture.md` when present) first.

The skeleton is read twice: by the developer, who implements from it, and by you later (a different session of the same role), who checks the finished diff against it. Write it so that the later check is decidable: state boundaries and seams as **checkable items** (which module may import which, which layer owns what, which file holds what), not as prose.

If the work needs more than one pull request (a split into child issues), the engine cannot do that in this version: return `status: blocked` with `blocked_by.kind: other` and a note starting `split:` that proposes the slices.

Write only the skeleton file.
