# STATUS

Where every video stands, and what keeps Studio from working as designed here (M1i).

Rules: one command per Bash call, literal values. Shared rules: `atoms/_contract.md`.

1. `python3 .claude/studio/scripts/state.py status` (add `--since-last` to also see whether commits came in since
   the last range check). It lists, per video and language: the stage, a held state, approvals made in the proxy mode
   (a person must approve them again), backup warnings; then the warnings: the guard has not run in this session,
   the pre-commit hook or the ignore blocks are not valid, this machine has no s2v path, a platform file is not
   checked by a person (or was checked more than 180 days ago), "harness changes not committed", and a leftover
   pronunciation merge with how to clear it.
2. Show it to the person in their language. For each held video say what `/std resume <video>` will do.
3. A warning about the hook: `python3 .claude/studio/scripts/hooks.py install` (the person decides for a shared hook
   file). Commits since the last range check: `python3 .claude/studio/scripts/check_commit.py --since-last`.

Change nothing else from here.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
