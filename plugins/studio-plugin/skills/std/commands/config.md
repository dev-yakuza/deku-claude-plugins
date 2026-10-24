# CONFIG

Show or change Studio's settings (M1c). Protected settings, this machine's s2v path, the narrator and the internal
overlay change only with the person's answer; every change to a committed file then goes through a harness commit.

Rules: one command per Bash call, literal values (replace `<<SKILL_DIR>>` and every `<…>` before the call), never a
variable in command position. Shared rules: `atoms/_contract.md`.

## Show

`python3 <<SKILL_DIR>>/scripts/setup.py config get` (everything) or `… config get <key>` (a dotted key, or
`s2v.path` for this machine's s2v).

## Change a setting

1. `python3 <<SKILL_DIR>>/scripts/setup.py config preview <key> <value>` — the value is JSON (`'["a/**"]'`,
   `false`) or plain text. It says whether the key is protected.
2. Not protected: `python3 <<SKILL_DIR>>/scripts/setup.py config set <key> <value>`.
3. Protected (the template's `protected_keys`, and `s2v.path`): ask with AskUserQuestion — the question shows the
   preview's `line` exactly (`설정 <key>: <old> → <new>`) and its `h12`; options: the fixed label `설정 <h12>` and
   "그만두기". Then, in a later message and alone — never in the same message as the question — run
   `python3 <<SKILL_DIR>>/scripts/setup.py config set <key> <value> --expect <h12>`.
`studio_root` cannot be changed here (moving Studio's folder is not part of M1).

## The default narrator

`python3 <<SKILL_DIR>>/scripts/setup.py narrator preview <lang> --engine qwen:<speaker> --style "<one line>"` shows
the line and `h12`; ask (fixed label `설정 <h12>`, the line in the question), then, in a later message and alone,
`python3 <<SKILL_DIR>>/scripts/setup.py narrator set <lang> --engine qwen:<speaker> --style "<one line>" --expect <h12>`.
Videos already cast keep their narrator; new videos use the new one.

## The internal overlay (internal hosts, sources, terms, video and actor ids)

The overlay file is written by the person (outside the repository). Compute its sha256 (`shasum -a 256 <file>`), then
ask with AskUserQuestion: the question shows the file's path, the first 12 characters of the sha and **every key with
its number of entries, one per line, exactly like this**:

    internal.hosts: <N>개
    internal.sources: <N>개
    internal.terms: <N>개
    internal.videos: <N>개
    internal.actors: <N>개

(`0개` for a key the file does not have); options: the fixed label `사내설정 <sha12>` and "그만두기". Then, in a later
message and alone, `python3 .claude/studio/scripts/state.py overlay --from <file> --expect <sha12>` (it refuses an
answer whose question did not show those lines).

## Then: the harness commit

A change to `.claude/studio/**` or the narrator is committed like in `/std init` step 6 (stage, open the criteria files
the value block lists, show the summary line and every value line, `커밋 <tree12>`, then `git commit` alone in a later
message). `s2v.path` and the overlay are this
machine's files: nothing to commit.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
