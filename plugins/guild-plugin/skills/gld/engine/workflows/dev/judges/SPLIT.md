# L0-SPLIT — is this a genuine multi-PR split? (§3.2 G-SPLIT, J-DE-05, A-F22/23)

The tech-lead's `split.json` proposes splitting this Issue into child Issues. You see it, the parent
AC, the existing children (number, title, slice key) and the skeleton's split section.
- `single`: one PR is fine (most Issues).
- `split`: independently deliverable slices, each its own PR + tests. Every parent AC id must belong
  to some slice (`ac_ids`); `key` is a short stable slug (`[a-z0-9-]`), `order` the dependency order.
  Slices whose key matches an existing child are listed too (they are not created again).
- `unsure` when you cannot tell — a split is hard to undo, so the engine asks a person.
