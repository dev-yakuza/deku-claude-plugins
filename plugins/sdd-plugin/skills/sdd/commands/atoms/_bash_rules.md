# Bash Command Execution Rules (shared)

Canonical rules for every Bash tool invocation inside any atom, orchestrator, or stage sub-agent. Extracted from `SKILL.md` so every caller has one source of truth.

Read this file when the calling atom/orchestrator instructs you to.

---

## Purpose

To keep automated runs (`/sdd auto`, `/sdd batch`) unattended, every Bash tool invocation MUST be a **simple command** that matches the project's `permissions.allow` patterns (typically `Bash(gh:*)`, `Bash(git:*)`, `Bash(jq:*)`, etc.).

---

## FORBIDDEN inside a single Bash tool call

- Variable assignment with command substitution: `VAR=$(command)`
- Compound commands: `cmd1 && cmd2`, `cmd1 || cmd2`, `cmd1; cmd2`, `cmd1 | cmd2`
- Subshells / groups: `(...)`, `{...}`
- Process substitution: `<(...)`, `>(...)`
- Heredocs that wrap multiple commands (`<<EOF ... EOF` containing more than the body of one tool call)
- **Shell variable substitution inside double-quoted arguments**: `"...${VAR}..."` or `"...$VAR..."`. Substitute the literal value before invoking Bash instead.
- **Output redirection / discard**: `> file`, `2>/dev/null`, `2>&1`, `&>file`. These count as compound shell syntax under Claude Code's argument heuristic and trigger the same safeguard prompt. If you need to ignore stderr, just run the command and parse the tool result yourself.
- **Recursive / broad `find` searches outside the repo root**: `find /`, `find /Users`, `find /private`, `find ~`, `find ~/<anything>`, or any `find` whose start path is not the repo root (`.`) or a subdirectory of it. These trigger Claude Code's recursive-broad-search safeguard, which is a **separate** prompt that `permissions.allow`, `--dangerously-skip-permissions`, and `sandbox.enabled = false` cannot suppress. For symbol/file discovery, use the **Grep tool** or **Glob tool** (bound to the working tree) instead of `find` — those don't trip the safeguard and don't shell out.
- **Documentation placeholders in command arguments**: tokens like `<<SKILL_DIR>>`, `<owner>/<repo>`, `<branch-name>`, `<N>`, or `$1` / `$2` shown in this skill's docs are *reference syntax*, not values. They must be replaced with the literal value **before** the Bash tool call. Never pass them through unresolved (e.g. `gh issue view $1` as a literal `$1`) — that will fail or trigger an argument-parsing prompt.

---

## Why these rules exist

- Items 1–5 above: Claude Code's permission matcher evaluates compound expressions and cannot match single-token allow patterns like `Bash(gh:*)`. Each such call therefore raises a permission prompt, breaking unattended runs.
- Item 6 (quoted variable substitution): triggers Claude Code's "brace with quote character (expansion obfuscation)" argument heuristic, which is a **separate** safeguard that `permissions.allow`, `--dangerously-skip-permissions`, and `sandbox.enabled = false` cannot suppress. Even with all permission gates bypassed, this prompt still fires and breaks unattended runs.
- Item 7 (output redirection): redirections like `2>/dev/null` and `2>&1` are flagged by the same compound-shell-syntax heuristic that catches `;` and `|`; they cannot be auto-approved.
- Item 8 (broad `find`): Claude Code applies a recursive-broad-search safeguard whenever `find` is given an absolute start path that crosses out of the working tree (or `/`, `~`). The prompt is independent of permission settings.
- Item 9 (unresolved doc placeholders): tokens like `<<SKILL_DIR>>` or `$1` reach the shell as literal text, which usually fails — and `${VAR}` patterns specifically also trip the "expansion obfuscation" heuristic (item 6).

---

## How to chain results between commands

1. Run the first simple command in its own Bash tool call.
2. Read the output yourself from the tool result.
3. Substitute the **literal** value (not a shell variable, not a `$(...)`) into the next simple Bash tool call.

### Example

- Forbidden: `VAR=$(gh repo view ...); gh api repos/$VAR/...` — compound disables `Bash(gh:*)` matching.
- Correct: run `gh repo view --json nameWithOwner -q .nameWithOwner` as Bash call 1; observe the literal output (e.g. `owner/repo`); inline that literal into `gh api repos/owner/repo/...` as Bash call 2.

Parallel-independent commands (e.g. `gh issue view ...` and `git status ...`) should be issued as **multiple Bash tool calls in a single message**, not chained with `&&`. Cleanup steps that need ordering should be issued as **separate sequential Bash tool calls**, not chained with `&&` or `;`.

---

## Scope

This rule set applies to every Bash tool invocation inside any atom, orchestrator, or stage sub-agent in the SDD plugin — including snippets shown in this skill's Markdown files. Those snippets are templates for tool calls, not literal shell scripts to paste.

---

## Codebase exploration: prefer Grep/Glob/Read over Bash

For finding symbols, files, or content: use the **Grep tool**, **Glob tool**, and **Read tool** directly. They are bound to the working tree and don't trigger the safeguards that `find`/`grep`/`cat` via Bash do. See `_review_helpers.md` Section D for budget caps on review-atom exploration.
