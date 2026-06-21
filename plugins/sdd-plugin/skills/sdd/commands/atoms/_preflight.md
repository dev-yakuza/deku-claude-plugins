# PRE-FLIGHT (shared procedures)

**Not an atom.** This file documents the pre-flight context discovery procedure called at **Step 0** of every work atom (analyze/design/implement/test). Read the section matching the atom's tier when the calling atom instructs you to.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

---

## Section A — Tier definitions

Each work atom runs only the items matching its tier. Lower tiers are subsets of higher tiers.

| Tier | Items | Applies to (default) |
|---|---|---|
| Light | 1 + 2 | `analyze_work`, `implement_pr` |
| Medium | 1 + 2 + 3 + 5 | `design_work`, `test_work` |
| Heavy | 1 + 2 + 3 + 4 + 5 | `implement_plan` |
| Code-focused | 4 + 5 | `implement_red`, `implement_green`, `implement_refactor`, `implement_e2e` |

### Depth label overrides

If the Issue has a depth label, the tier is adjusted **for every work atom in this Issue**:

- `sdd:review:deep` → all atoms run **Heavy** tier (plus extended ranges per Section B)
- `sdd:review:shallow` → all atoms run **Light** tier (items 3, 4, and 5 are skipped regardless of default tier)
- (no label) → atom's default tier

---

## Section B — Items

### Item 1: Project conventions (always safe, no external dependency)

1. Check for convention files:
   ```bash
   ls CLAUDE.md AGENTS.md README.md
   ```
2. For each file present in the output: Read it.
3. Extract: code style, naming conventions, architecture rules, testing conventions, project goals.

**Budget**: 3 Read calls max.

**Failure**: If `ls` shows no files, log "no convention files found" and proceed.

### Item 2: Commit message style (always safe)

1. ```bash
   git log --oneline -20
   ```
   (For `sdd:review:deep` label, use `-50` instead of `-20`.)

2. Observe: prefix conventions (`feat:`, `fix:`, `refactor:`, etc.), version-bump format (e.g., `feat: v0.X.0 — …`), em-dash usage, capitalization.

**Failure**: If `git log` fails (shallow clone, no history), log "no commit history available" and proceed.

### Item 3: Similar past PRs (conditional — `gh` required)

1. **Derive search keywords** from the Issue:
   - Prefer concrete nouns from the Issue title (e.g., "Add OAuth login" → `oauth`, `login`).
   - If the title is generic (`Fix bug`, `Add feature`, `Refactor`), fall back to the first noun phrase in the Issue body.
   - For child Issues, also consider the parent Issue's title.
   - Limit: 1~2 keywords.

2. **Search merged PRs** (each line is its own Bash call):
   ```bash
   gh pr list --state merged --search "<keyword>" --limit 3 --json number,title
   ```
   (For `sdd:review:deep` label, use `--limit 5`.)

3. **Handle results**:
   - **0 results** → graceful skip. Log "no similar PRs found"; proceed without. Common on new repos, non-GitHub, or projects where the keyword doesn't match merged work.
   - **1+ results** → for up to 2 most recent matches:
     ```bash
     gh pr diff <PR_NUM>
     ```
     **Skip the diff** if it exceeds 1000 lines (likely squash-merge noise that buries actual feature work).

4. **Conflict resolution**: if 2 PR diffs show *different* patterns (e.g., one uses early-return, another uses nested-if), prefer the **most recent merged** one — it best reflects the current codebase state.

**Budget**: 2 `gh pr list` + 2 `gh pr diff` max.

**Failure modes**:
- `gh` CLI unavailable (non-GitHub remote, missing auth) → log "gh unavailable; skipping similar PR lookup" and proceed with items 1, 2, (4) only.
- Auth failure → same as above.

### Item 4: Target directory survey (`implement_*` only)

1. **Derive the target directory** from the design output's File Structure section (read from `<!-- sdd:design:output -->` comment).

2. List the directory:
   ```bash
   ls <target-dir>
   ```

3. Identify the 2 most recently modified files (by `git log -1 --format="%ai %f" -- <file>`-like inspection, or by `ls -lt`). Read both.

4. Extract patterns: import style, error handling, naming, file organization, test structure.

**Budget**: 2 Read calls max (one per file).

**Failure**: If the target dir doesn't exist yet (greenfield change), proceed without; the atom will create the dir.

---

### Item 5: Project-specific stage rules (conditional — Medium + Heavy + Code-focused)

Check for a project-maintained rules index for the current SDD stage. Load only the rule files relevant to this specific task.

**Stage name**: Use the current stage identifier — `implement` for all implement atoms, `design` for `design_work`, `test` for `test_work`.

1. **Check index existence** (its own Bash call):
   ```bash
   ls .claude/sdd/rules/<stage>.md
   ```

2. **If the file exists**: Read `.claude/sdd/rules/<stage>.md`.

3. **Select relevant rule files**: Read the index table. For each listed rule file, decide whether its **scope** or **trigger keywords** overlap with what is being implemented in this task (use the Issue title, design output summary, and target files as signals). When uncertain, **include rather than exclude**.

4. **Load selected files**: Read each chosen rule file. Budget: 3 Read calls max.

5. **Apply as hard constraints**: Treat the loaded rules with the same authority as project conventions from CLAUDE.md — they are mandatory, not optional suggestions.

**Budget**: 1 Read (index) + 3 Reads (rule files) = 4 Read calls max.

**Failure**:
- Index file does not exist → skip silently (zero overhead, no log).
- A rule file listed in the index cannot be read → log `rule file missing: <path>` and skip that file only; continue with others.

---

## Section C — Budget interaction with review atoms

Step 0 budgets (this file) are **SEPARATE** from review atoms' codebase exploration budgets (15 Read / 10 Grep / 5 Glob per `_review_helpers.md` Section D).

- Step 0 runs in **work atoms** only.
- Codebase exploration runs in **review atoms** only.
- No atom invocation hits both budgets — they cannot conflict.

---

## Section D — Failure handling (summary)

All items are **best-effort**. No individual item failure blocks the atom.

| Failure | Behavior |
|---|---|
| Convention files absent | Silently proceed (no nudge to create) |
| `git log` fails | Proceed without commit convention guidance |
| `gh` CLI unavailable | Skip Item 3 only; proceed with others |
| Empty PR search result | Skip Item 3 only; proceed with others |
| Target dir doesn't exist (Item 4) | Proceed; atom will create dir |
| `.claude/sdd/rules/<stage>.md` does not exist (Item 5) | Skip silently (zero overhead) |
| Rule file listed in index cannot be read (Item 5) | Log `rule file missing: <path>`; skip that file only |
| Read tool fails | Log + proceed without that file |

The atom **records** which Step 0 items succeeded vs were skipped in the `<details>` self-review trace.

---

## Section E — Retry behavior

On **round 2 or later** retry, work atoms **SKIP Step 0** entirely. The context gathered in round 1 is retained in the atom's reasoning context (and surfaced in the round-1 `<details>` self-review trace, which the round-2 atom can reread if needed).

This saves ~30K tokens per retry round.

Orchestrators detect retry by the presence of `$2` (or `$3` for `implement_pr`) — when retry feedback is provided, Step 0 is skipped.

---

## Section F — Output: self-review trace

After Step 0 completes (or is skipped per Section E), the work atom records findings for the `<details>` self-review trace embedded in its output. Example:

```markdown
<details>
<summary>Pre-flight context (Step 0)</summary>

- [x] CLAUDE.md read (4 sections extracted)
- [x] git log -20 examined (commit prefix: `feat:`/`fix:`)
- [x] 2 similar PRs found: #142 (OAuth refactor), #138 (login redirect) — followed #142's DI pattern
- [ ] Target dir survey: N/A (Medium tier)
- [ ] sdd/rules/design.md: not found — skipped

</details>
```

Skip the block entirely if Step 0 was skipped (retry round) — atom can reference round-1 output instead.

---

## Section G — Atom guidance

Each work atom's `Work` section begins with:

```markdown
### Step 0: Pre-flight context discovery

If retry mode (`$2` or `$3` provided) → **skip this step entirely**.

Otherwise, follow `<<SKILL_DIR>>/commands/atoms/_preflight.md`
Section A for the tier matching this atom (<TIER>). Execute Section B
items per the tier; apply Section D failure handling.

Record findings for the Section F self-review trace.
```

Where `<TIER>` is one of: `Light`, `Medium`, `Heavy`, `Code-focused`. Atom file substitutes its own tier name.

---

## Hard rules

- This file is **not an atom** — does not execute on its own. Each work atom references it.
- All Step 0 actions are **read-only** (no Edit/Write/code modification).
- Step 0 must complete (or fail gracefully) before the atom proceeds to Step 1.
- On retry rounds, Step 0 is **always skipped** — no exceptions.
