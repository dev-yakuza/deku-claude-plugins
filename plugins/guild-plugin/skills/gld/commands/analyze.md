# ANALYZE (stage)

**Stage: analyze.** Role: **leader** (embodied by the main session). Runs the **discuss gate**, analyzes requirements, classifies work type, posts the analysis. Invocable directly (`/gld analyze <issue>`) or as the first stage of `/gld dev`.

`$1` = Issue number. Returns a Section D line (`_handoff.md`).

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State/handoff: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.

---

## Step 0 — Preflight
Follow `<<SKILL_DIR>>/commands/atoms/_preflight.md` **Light tier** (items 1–3: config + role defs, conventions + standards, commit style). If `.claude/guild/config.json` is absent → `FAIL: Guild not initialized (run /gld init)`.

Validate `$1` is an Issue (not a PR):
```bash
gh issue view $1 --json url --jq .url
```
URL contains `/pull/` → `FAIL: #$1 is a Pull Request, not an Issue`.

Ensure the entry label (direct invocation): if the Issue has no `guild:*` stage label, add `guild:analyze`:
```bash
gh issue edit $1 --add-label "guild:analyze"
```

Read the Issue:
```bash
gh issue view $1
```

## Step 1 — discuss gate (required, plan §4)
Before analyzing, as the leader:
1. State the **assumptions** and interpretations you're making about the request.
2. Offer **2–3 substantively different interpretations/approaches** where the request is ambiguous (not one "obvious" reading).
3. If any material ambiguity affects scope/approach → return `NEEDS_HUMAN: <the choice needed>` so the main session prompts the user. Do not proceed past a real ambiguity on your own.

If the request is unambiguous, record the single interpretation explicitly and proceed (note in the output that discuss found no material ambiguity).

## Step 2 — Requirement analysis
- Enumerate the requested features/changes (What + Why, not How).
- Derive **acceptance criteria (AC)** — verifiable, checkable statements. These are the contract the tester will design against (design stage) without seeing the implementation.
- Assign priorities where multiple items exist.

## Step 3 — Work-type classification / reclassification
- Read the Issue's `type:` label if present (`feature`/`bug`/`refactor`).
- Reclassify if reality differs (plan §4) — e.g. "labeled feature but needs a refactor first." Note the mismatch and, if it implies splitting, flag it for design (child-issue split is decided in design). In M1, execute is always `implement`, but record the true type for the humans.

## Step 4 — Post analysis output
Write the analysis body to a temp file with the marker pair, then post via the temp-file pattern (`_bash_rules.md` → temp-file section / `_handoff.md` Section B):
- Marker: `<!-- guild:analyze:output -->` … `<!-- /guild:analyze:output -->`.
- Contents: interpretation chosen (discuss), feature list, **acceptance criteria**, work-type classification, priorities. Append a `<details>` pre-flight trace (`_preflight.md` Section C).
- Duplicate-prevention search + POST (new) or PATCH (existing) per the temp-file pattern.

## Step 5 — Transition + return
On success, transition the label (this stage owns it):
```bash
gh issue edit $1 --remove-label "guild:analyze" --add-label "guild:design"
```
Return:
```
>>> RESULT <<<
OK ADVANCE: design
```

Other returns: `NEEDS_HUMAN: <...>` (discuss ambiguity — do NOT transition), `FAIL: <reason>` (hard error — do NOT transition).

## Hard rules
- **Read-only against the working tree.** Analyze creates no branches/commits/code — only the Issue comment + label.
- Discuss gate is **mandatory** — do not skip to analysis when there is real ambiguity.
- All Bash per `_bash_rules.md`; comment body via Write tool + `--body-file`.
