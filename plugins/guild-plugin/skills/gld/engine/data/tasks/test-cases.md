Write the test cases for this Issue to `docs/specs/<issue>/test-cases.md`, from the acceptance criteria of `analysis.md` ONLY. Do not read any implementation and do not look for a design or skeleton document: the cases must not be shaped by how it will be built (bias-free test design). The developer turns each case into a failing test, so describe **observable behaviour**, never internal structure.

Cover normal, edge and failure paths. An AC tagged `(safety net)` pins behaviour the code already has: its case passes on today's code, keeps the tag, and states the observable result precisely enough that a test written from it fails when that behaviour breaks. If an AC changes how a screen looks and the repository has golden/screenshot tests (look at the existing test layout), add a `## Visual cases` section with one row per image the change should produce — screen or component, state, theme, size — each tied to its AC; a visual case never replaces a behaviour case.

**The AC reference form is fixed** (a check script reads it; it fails closed):
- Every case is one list item or one table row, and ends with its AC tag in parentheses: `- C3: tapping the row opens the sheet. (AC #2)`, or `(AC #2, #5)` for several — each further id has its own `#`. In a table, give the tag its own last cell: `| C5 | one selection shows its name | (AC #3) |`.
- The tag holds nothing but the AC list and counts only at the end of the case's line (or of its table cell). Never put a tag in square brackets: the repository's markdown lint reads them as undefined link references and fails.
- Use the ids exactly as `analysis.md` defines them (`AC #n`, a plain integer). No ranges (`AC #1-3`), no other spellings (`AC1`, `AC-1`), no placeholder like `AC #n` outside backticks.
- A heading may carry the tag for its group: `### Persistence (AC #3, #4)`. Anywhere else an AC named inside a sentence is a prose mention and does not count as coverage — write such a mention without parentheses (`same limit as AC #4`) so it cannot be mistaken for a tag.
- Every AC of `analysis.md` must be referenced by at least one case, and you may not reference an id it does not define. The engine runs the check right after you; a miss sends this step back to you.

Write only that one file.
