# Bash Command Execution Rules (shared)

Canonical rules for every Bash tool invocation inside any Guild command, atom, stage, or role agent. Read this file when the calling file instructs you to. (Lifted and adapted from sdd-plugin's proven `_bash_rules.md`.)

---

## Purpose

To keep Guild runs (`/gld dev`, individual stages) smooth and, where possible, unattended, every Bash tool invocation MUST be a **simple command** that matches the repo's `permissions.allow` patterns (typically `Bash(gh:*)`, `Bash(git:*)`, `Bash(jq:*)`, etc.). `/gld init` writes such an allowlist into `.claude/settings.json`.

---

## FORBIDDEN inside a single Bash tool call

- Variable assignment with command substitution: `VAR=$(command)`
- Compound commands: `cmd1 && cmd2`, `cmd1 || cmd2`, `cmd1; cmd2`, `cmd1 | cmd2`
- Subshells / groups: `(...)`, `{...}`
- Process substitution: `<(...)`, `>(...)`
- Heredocs that wrap multiple commands (`<<EOF ... EOF` containing more than the body of one tool call)
- **Shell variable substitution inside double-quoted arguments**: `"...${VAR}..."` or `"...$VAR..."`. Substitute the literal value before invoking Bash instead.
- **Output redirection / discard**: `> file`, `2>/dev/null`, `2>&1`, `&>file`. These count as compound shell syntax under Claude Code's argument heuristic and trigger the same safeguard prompt. If you need to ignore stderr, just run the command and parse the tool result yourself.
- **Recursive / broad `find` searches outside the repo root**: `find /`, `find /Users`, `find ~`, or any `find` whose start path is not the repo root (`.`) or a subdirectory of it. These trigger Claude Code's recursive-broad-search safeguard, a **separate** prompt that `permissions.allow` cannot suppress. For symbol/file discovery, use the **Grep tool** or **Glob tool** (bound to the working tree) instead of `find`.
- **Documentation placeholders in command arguments**: tokens like `<<SKILL_DIR>>`, `<owner>/<repo>`, `<branch-name>`, `<N>`, or `$1` / `$2` shown in Guild's docs are *reference syntax*, not values. Replace them with the literal value **before** the Bash tool call. Never pass them through unresolved.

---

## Why these rules exist

- Items 1–5: Claude Code's permission matcher evaluates compound expressions and cannot match single-token allow patterns like `Bash(gh:*)`. Each such call raises a permission prompt.
- Item 6 (quoted variable substitution): triggers the "brace with quote character (expansion obfuscation)" heuristic, a **separate** safeguard that `permissions.allow`, `--dangerously-skip-permissions`, and `sandbox.enabled = false` cannot suppress.
- Item 7 (output redirection): flagged by the same compound-shell-syntax heuristic that catches `;` and `|`.
- Item 8 (broad `find`): recursive-broad-search safeguard, independent of permission settings.
- Item 9 (unresolved placeholders): tokens like `$1` reach the shell as literal text and fail; `${VAR}` patterns also trip the expansion-obfuscation heuristic.

---

## How to chain results between commands

1. Run the first simple command in its own Bash tool call.
2. Read the output yourself from the tool result.
3. Substitute the **literal** value (not a shell variable, not a `$(...)`) into the next simple Bash tool call.

### Example

- Forbidden: `VAR=$(gh repo view ...); gh api repos/$VAR/...`
- Correct: run `gh repo view --json nameWithOwner -q .nameWithOwner` as Bash call 1; observe the literal output (e.g. `owner/repo`); inline that literal into `gh api repos/owner/repo/...` as Bash call 2.

Parallel-independent commands (e.g. `gh issue view ...` and `git status ...`) should be issued as **multiple Bash tool calls in a single message**, not chained with `&&`. Ordered cleanup steps should be **separate sequential Bash tool calls**.

---

## Codebase exploration: prefer Grep/Glob/Read over Bash

For finding symbols, files, or content: use the **Grep tool**, **Glob tool**, and **Read tool** directly. They are bound to the working tree and don't trigger the safeguards that `find`/`grep`/`cat` via Bash do.

---

## Posting Issue/PR comments: the temp-file pattern (mandatory)

Every Guild comment body is multi-line Markdown containing `#` headers, HTML comment markers (`<!-- ... -->`), and code fences. Passed to `gh` via inline `--body "..."`, Claude Code intercepts the "newline followed by `#` inside a quoted argument" pattern and prompts — a safeguard that permission settings cannot suppress.

**The only sanctioned flow** for posting/updating a comment:

1. **Write tool** — render the full body (with markers) to a deterministic temp file under the scratchpad or `/tmp/` (e.g. `/tmp/guild-<stage>-output-<N>.md`). Never build the body with `echo`/`printf`/heredoc.
2. **Bash** — duplicate-prevention search for an existing comment with the same marker:
   ```bash
   gh api repos/<owner>/<repo>/issues/<N>/comments --jq '.[] | select(.body | contains("<MARKER>")) | .id'
   ```
   (substitute literal `<owner>/<repo>`, `<N>`, and `<MARKER>`; for PR comments `<N>` is the PR number — PR comments share the Issues comments API.)
3. **Bash** — branch on the result:
   - **Empty** → create: `gh issue comment <N> --body-file <path>` (or `gh pr comment <PR> --body-file <path>`).
   - **Has id `<id>`** → update in place: `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@<path>`.

Forbidden alternatives: `gh issue comment <N> --body "<multi-line>"`, `--field body="<multi-line>"`, heredocs, `echo "..." | gh ...`, `printf ... > file && gh ...`.

The same constraint applies to `gh issue create` — write the body to a temp file and pass `--body-file <path>`. Single-line `--title "..."` is safe.

---

## Sanctioned exceptions (the only three)

Several files (`batch.md`, `evolve.md`, `_signals.md`, `scan_transcript.py`'s and `capture_signal.py`'s own docstrings) describe themselves as an "atomic-bash exception" — this section is the list those claims point back to, so a claimed exception can actually be checked against something instead of asserting itself unilaterally. There are exactly three — the first two are carve-outs from the **compound-command** list above, the third from the **comment update-in-place** flow:

1. **A single bundled Python invocation** — `python3 <script>.py --flag value ...` as ONE Bash tool call. The script itself may internally do whatever multi-step logic it needs (git parsing, jq-like filtering) — that's Python code, not shell compounding, so it never trips the compound-command heuristics above. Used by: `capture_signal.py` (ground-truth append), `scan_transcript.py` (transcript friction scan), `sprint_dag.py` (dependency linearisation + `plan-hash`), `board_write.py` (batched board writes — its docstring points back here, and the arithmetic that forced it is 123 tool calls for a 40-issue backlog). This isn't really an "exception" to the FORBIDDEN list at all — a single `python3 script.py <args>` call already satisfies "simple command" on its own; the label exists to reassure a reader who might otherwise assume a Python script implies hidden shell chaining.
2. **A generated OS-level `.sh` script, run once as a single backgrounded Bash tool call** (`bash path/to/generated-script.sh`, `run_in_background: true`) — there are two current instances: `batch.md`'s supervisor script, and `/gld sprint run`'s (`templates/sprint-supervisor.sh`, rendered from a template file rather than a fenced block — deliberately duplicated per the sprint design's D10, not shared). The **script's own contents** (loops, `&&`, `$(...)`, variable substitution) are ordinary shell code the OS interprets when the script runs — they are not subject to this file's rules, which govern **the Bash tool call itself** (one call: `bash <path>`), not what a script file does once it's executing outside Claude Code's per-call heuristics. This is a narrow, deliberate carve-out for exactly this shape (a single generated script file, invoked once) — it does not license writing arbitrary compound commands directly in a Bash tool call's `command` argument.

3. **`<!-- guild:auditor-violation -->` skips the duplicate-prevention search** (step 2 of the comment flow above) and always **creates** a new comment. This is a carve-out from *update-in-place*, not from the temp-file mechanics: the body is still rendered with the Write tool and posted with `--body-file`, exactly as above. The reason is in `_handoff.md` Section B and `_execute_spine.md` Step 3.5a — each violation is an append-only forensic note, and PATCHing them into one comment would both destroy the earlier readings and let a single stale `:resolved` marker disarm the Step 0 re-entry guard for every later violation. (Its sibling `<!-- guild:auditor:execute -->` is **not** an exception to the *create-vs-update* rule — it does PATCH in place — but it does not use the flow verbatim either: it composes its new body as *old body + one appended block*, which means it needs the existing `.body` as well as the `.id`, and `_execute_spine.md` Step 4 requires **`--paginate` on both lookups**. Paginating only one is worse than paginating neither: the `.body` read finds the record while the `.id` read comes back empty, and step 3's "Empty → create" branch then posts a duplicate record comment.)

No other pattern is a sanctioned exception. Any other file claiming one should be checked against this list — if it doesn't match one of the shapes above, the claim is wrong, not the rule.

---

## Scope

This rule set applies to every Bash tool invocation inside any Guild command, atom, stage, or role agent — including snippets shown in Guild's Markdown files. Those snippets are templates for tool calls, not literal shell scripts to paste. See "Sanctioned exceptions" above for the only three carve-outs.
