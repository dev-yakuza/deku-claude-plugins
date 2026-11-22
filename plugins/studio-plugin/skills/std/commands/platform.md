# PLATFORM

A repository's platform rules: `.claude/studio/platforms/<name>.md` — who the platform is for (`audience`), the
shapes it takes (`outputs`), the copy's limits and notices (the `studio:rules` block) and the help pages they were
checked against (`sources`). Only the person changes these files: you draft, a script writes after their answer.
`/std platform list | add <name> | refresh <name> | remove <name>`.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a
variable in command position. Shared rules: `atoms/_contract.md`.
Run Studio commands exactly as written: no `| head`, `; echo $?`, `2>&1 | …`, variables or `&&` chains (only
`cd <repo> &&`), and read the whole output. Do not repeat a call whose output is already in the conversation. Show
files to the person with `open <path>` only (never `code`, `vim` or another editor).

## list

`python3 "<<SKILL_DIR>>/scripts/setup.py" platform list` — each platform: `audience`, outputs, `checked` and its
age in days, the rules version, the videos in progress that name it, and a `warning` when it is not checked or was
checked more than 180 days ago. Show it to the person.

## add `<name>` · refresh `<name>`

`add` writes rules for a new platform (the name must not exist: letters, digits, `_` and `-`); `refresh` checks an
existing one again (also how a shipped file gets its first `checked`).

1. Search the web with **only** the platform's name and these fixed phrases, nothing from the repository:
   `<Name> video upload title length limit`, `<Name> caption character limit`, `<Name> hashtags limit`,
   `<Name> AI-generated content label`, `<Name> video aspect ratio length`. Open only the platform's own help pages.
   An internal platform (the organization's own sharing place) has no help pages: ask the person for its rules.
2. Write the draft with Write to `.claude/studio/local/drafts/platforms/<name>.md`. For `refresh`, start from the
   current file (for a shipped platform whose file lacks `audience` or names another output, start from the
   plugin's template the refusal names). The draft has this shape, with `checked` empty:

   ~~~
   ---
   platform: <name>
   # audience: public or internal (a kind's videos may name only platforms of its audience)
   audience: public
   checked: ""
   outputs:
     # name: an output name (platforms that accept the same shape share it); aspect: 16:9, 9:16 or 1:1;
     # max_duration: seconds, or null
     - name: shorts
       aspect: "9:16"
       max_duration: 180
   sources:
     - https://<the platform's help page>
   ---
   # <Name>
   <!-- studio:rules -->
   ```json
   {"title_max": 100, "description_max_bytes": 5000, "hashtags_max": 15, "required": ["<notice>"],
    "chapters": "none", "link": "body"}
   ```
   <!-- /studio:rules -->
   ~~~

   `title_max` may be `null` (the platform has no title); give exactly one of `description_max_bytes` and
   `description_max_chars`; `hashtags_max` may be 0; `chapters` is `required` or `none`; `link` (the source link line
   in the description) is `body` or `none`. Then the copy notes and the upload checklist in prose, as the shipped
   `youtube.md` has them. No home paths, no in-house terms. Comments go on their own lines (`# …`), never after a
   value.
3. `python3 "<<SKILL_DIR>>/scripts/setup.py" platform preview <name>` — it checks the draft (exit 1: fix what it
   says, then preview again) and prints `lines` (one per key the rules set, and a last line `본문 sha <sha12> (<n>줄)`
   for the body after the frontmatter — the rules block and the prose the distributor follows), `h12` and `label`.
   `open` the draft for the person, and in your message before the question show the body: for `refresh`, the diff
   of the draft against the current file (`diff -u .claude/studio/platforms/<name>.md
   .claude/studio/local/drafts/platforms/<name>.md`); for `add`, the whole body. The person approves the body too.
4. Ask with AskUserQuestion: the question shows the preview's `h12` and **every line of `lines`, pasted unchanged**
   (the guard compares each character) and states that the person compared them with the sources; options: the fixed
   label `플랫폼 <h12>` and
   "그만두기". Then, alone as your next tool call, in the same turn, right after the answer — do not wait for the
   person; never in the same assistant message as the question — run
   `python3 "<<SKILL_DIR>>/scripts/setup.py" platform apply <name> --expect <h12>`. It writes the platform file with
   `checked` = today and deletes the draft.
5. Commit like in `/std init` step 6 (the harness commit; its question shows the platform file).

## remove `<name>`

1. `python3 "<<SKILL_DIR>>/scripts/setup.py" platform remove-preview <name>` — `lines`, `h12`, `label`; `refused`
   when a video in progress names the platform in its brief: tell the person the way out it names (`abandon`, or
   `state.py exclude-output <video> <output>` when the platform is the only one on that output — a platform that
   shares its output with another cannot be excluded alone) and stop.
2. Ask as in add step 4 with the remove line and `플랫폼 <h12>`; then, alone as your next tool call, in the same turn,
   right after the answer — do not wait for the person; never in the same assistant message as the question — run
   `python3 "<<SKILL_DIR>>/scripts/setup.py" platform remove <name> --expect <h12>`.
3. Commit like in `/std init` step 6.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
> Exception: when the refusal itself says 'This is not a stop', do what it says — that is not
> reaching the same effect another way.
<!-- /studio:guard-refusal -->
