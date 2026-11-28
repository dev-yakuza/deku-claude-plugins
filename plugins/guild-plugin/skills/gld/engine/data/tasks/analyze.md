Analyze the Issue and write `docs/specs/<issue>/analysis.md` exactly as your role file prescribes (machine fields, `## Acceptance criteria`, `## Requirement map`, `## Assumptions`).

Start from `issue.md` in the engine folder: the Issue body, the collaborators' comments and the state of every Issue it references. Read the code the Issue touches before you write acceptance criteria. When this step was returned (see "Returned" below), fix exactly the listed problems and keep the rest of the document as it was. When `leader-decision.md` is present, it is the human's answer to your earlier question: follow it.

A real ambiguity you cannot narrow to one reading (a dimension whose wrong guess wastes the implementation) is `status: blocked` with `blocked_by.kind: ambiguous` and a note naming the dimension and the choice needed — not a guess. Everything smaller becomes an explicit assumption.
