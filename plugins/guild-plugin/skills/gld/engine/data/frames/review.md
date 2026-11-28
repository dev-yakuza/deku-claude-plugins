## Review step rules (independent reviewer)

You review; you do not fix, write or run anything. The result is the review result:

- `reviewed` — the repository files you actually read in full for this review (paths, one per file). Never list a file you did not fully read; an empty list is rejected.
- `checks` — one entry per required check id listed below, each `pass`, `fail` or `n/a` with a one-line `note`. A required check that is missing is rejected; a rule-added check may not be `n/a`.
- `verdict` — `block` when any check is `fail` or any finding is a `blocker`; otherwise `pass`. `pass` together with a `blocker` finding is rejected.
- `findings` — each with `severity`, `file`, `line` (null for a whole file) and `text`.

Severity is not a mood and not about how hard the fix is; it is the consequence of shipping the defect as it stands.
- **blocker** — shipping causes real harm: (1) a security or data exposure, (2) data loss or corruption, (3) loss of availability, (4) a correctness failure a user hits on the main path, (5) the change not delivering what the Issue asked for at all. Plus one rule-based case: weakening verification — deleting a test file, net-removing assertions, adding skip/focus directives — is always a blocker.
- **major** — a real defect with a bounded consequence (an edge case or one branch of a requirement left unmet, degraded behaviour, a broken rule that has teeth) where the change still delivers its purpose.
- **minor** — a defect or rule violation with no consequence at all (not behaviour, exposure, data, availability or the acceptance criteria). Grade minor only if you can state the concrete reason the consequence is zero.
"Unsure between major and minor" is unfinished work: read what settles it (callers, the covering test, the standard, the AC) and decide; still open → major, saying what is open. Unsure whether it is a blocker → report a blocker and say what you are unsure about.

Be skeptical, do not rubber-stamp, and do not pad: an empty `findings` list is a correct answer for a clean change. A finding that names no concrete consequence and no violated rule ("this function could be split") is not a finding. Anchor every finding to a file and line and write it in plain language: the concrete consequence, not just the violated rule.
