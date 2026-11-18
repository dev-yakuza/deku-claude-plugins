# L0-INTEGRATE — do the children add up to the parent? (§3.2 G-INTEGRATE, J-DEV-07/08, A-F9/10)

Every child of this split parent is done. You see the parent AC and design output, the roster, each
child's PR / test output / closed-as-decided or human-merged flag and the tech-lead's
`coverage.json`. You may Read/Grep the repository.
- `coverage`: each parent AC → the child that satisfies it (`#n`), `결정대로 닫힘`, or `gap`.
- `gaps[]`: `kind` coverage | consistency (seams, data shapes, interfaces disagree; duplicated or
  orphaned work) | dod | slicing (the split itself caused it); `child_to_fix` when one child's PR
  would fix it; `needs_decision` when a person must choose.
- `verdict`: `clean` | `gap` | `unsure` (the engine treats unsure as a gap that needs a decision).
