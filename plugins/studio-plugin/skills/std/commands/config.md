# CONFIG

Show or change Studio's settings (M1c). Protected settings, this machine's s2v path, the narrator and the internal
overlay change only with the person's answer; every change to a committed file then goes through a harness commit.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a
variable in command position. Shared rules: `atoms/_contract.md`.
Run Studio commands exactly as written: no `| head`, `; echo $?`, `2>&1 | …`, variables or `&&` chains (only
`cd <repo> &&`), and read the whole output. Do not repeat a call whose output is already in the conversation. Show
files to the person with `open <path>` only (never `code`, `vim` or another editor).

## Show

`python3 <<SKILL_DIR>>/scripts/setup.py config get` (everything) or `… config get <key>` (a dotted key, or
`s2v.path` for this machine's s2v).

## Change a setting

1. `python3 <<SKILL_DIR>>/scripts/setup.py config preview <key> <value>` — the value is JSON (`'["a/**"]'`,
   `false`) or plain text. It says whether the key is protected.
2. Not protected: `python3 <<SKILL_DIR>>/scripts/setup.py config set <key> <value>`.
3. Protected (the template's `protected_keys`, and `s2v.path`): ask with AskUserQuestion — the question shows the
   preview's `line` exactly (`설정 <key>: <old> → <new>`) and its `h12`; options: the fixed label `설정 <h12>` and
   "그만두기". Then, alone as your next tool call, in the same turn, right after the answer — do not wait for the person;
   never in the same assistant message as the question — run
   `python3 <<SKILL_DIR>>/scripts/setup.py config set <key> <value> --expect <h12>`.
`studio_root` cannot be changed here (moving Studio's folder is not part of M1).

Images of public posts often live outside the writing's folder (`public/blog-images/**`): put that folder in
`visibility.public` too, or its images are `unknown` and need a licence at board. Never suggest removing such a glob.
Videos in progress pick the change up when the source stage runs again (`/std source <video>`).

## The brand

`.claude/studio/brand.json` (`name`, `accent_color` `#RRGGBB`, `logo`) is edited as a file, then committed in the
harness commit below. The logo is a PNG or JPEG file of the repository that is **already committed** (or `""` for no
logo): the board check refuses an uncommitted brand.json or logo, and the harness commit warns about an uncommitted
logo. Videos past board run `/std board <video>` again (its check reads the brand).

## The default narrator

The speakers to offer are `narrator_candidates` of `python3 <<SKILL_DIR>>/scripts/setup.py init analyze` for the
language: the language's native built-in speaker(s) first (suggested), then up to two others, each described as "<its
language> native speaker — may carry an accent and fail the ② pronunciation check (CER ≤ 0.15)". The speaking style is
its own question.

`python3 <<SKILL_DIR>>/scripts/setup.py narrator preview <lang> --engine qwen:<speaker> --style "<one line>"` shows
the line and `h12`; ask (fixed label `설정 <h12>`, the line in the question), then, alone as your next tool call, in the
same turn, right after the answer — do not wait for the person; never in the same assistant message as the question —
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

(`0개` for a key the file does not have); options: the fixed label `사내설정 <sha12>` and "그만두기". Then, alone as your next
tool call, in the same turn, right after the answer — do not wait for the person; never in the same assistant message
as the question — `python3 .claude/studio/scripts/state.py overlay --from <file> --expect <sha12>` (it refuses an
answer whose question did not show those lines).

## Then: the harness commit

A change to `.claude/studio/**` or the narrator is committed like in `/std init` step 6 (stage, open the criteria files
the value block lists, show the summary line and every value line, `커밋 <tree12>`, then `git commit` alone
as your next tool call, in the same turn, right after the answer — do not wait for the person; never in the same
assistant message as the question). `s2v.path` and the overlay are this
machine's files: nothing to commit.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
> Exception: when the refusal itself says 'This is not a stop', do what it says — that is not
> reaching the same effect another way.
<!-- /studio:guard-refusal -->
