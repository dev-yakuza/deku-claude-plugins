# Contract (shared rules)

Status: contract only (M0). The handoff details (prompts, model tiers, loops, signals) are
written with M1.

## A. Roles

- The **producer** is the main session: it runs the flow, runs every deterministic command
  (script2video, the Studio scripts), judges results and asks people. It is not spawned.
- Other roles are spawned with their persona (`.claude/agents/std-*.md`) and receive **files
  only** as input; they write only the outputs listed for them in `_stages.md`.
- Roles never approve, never commit and never run script2video approval commands.

## B. Result contract

<!-- studio:result-contract -->
> Every spawned role ends its reply with exactly one result line:
> `>>> RESULT <<< <STATUS>: <one-line summary>` where `<STATUS>` is one of
> `DONE` · `DONE_WITH_CONCERNS` · `BLOCKED` · `NEEDS_CONTEXT` · `FAIL`.
> `DONE_WITH_CONCERNS` lists each concern on its own line before the result line.
> `BLOCKED` and `NEEDS_CONTEXT` say what is missing; the producer decides, never the role.
<!-- /studio:result-contract -->

## C. Guard

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
