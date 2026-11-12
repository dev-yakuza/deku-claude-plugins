# RESUME

Continue a video after a stop (M1i). The video id is the first argument of `/std resume`.

Rules: one command per Bash call, literal values. Shared rules: `atoms/_contract.md`.
Run Studio commands exactly as written: no `| head`, `; echo $?`, `2>&1 | …`, variables or `&&` chains (only
`cd <repo> &&`), and read the whole output. Do not repeat a call whose output is already in the conversation. Show
files to the person with `open <path>` only (never `code`, `vim` or another editor).

1. `python3 .claude/studio/scripts/state.py next <video>` — it says the stage to go to, or the held state.
2. **held:lock** (the machine lock was busy): `python3 .claude/studio/scripts/state.py release-lock <video>` — no
   person's answer needed; exit 4 while the lock is still busy (say so and stop). Then run `next` again.
3. **Any other held state** is the person's:
   - `source-diff` (the source changed after ①): show the diff (`state.py shown <video> source-diff`), then ask —
     `승인 <video> <h12>` keeps the approvals (`state.py approve <video> source-diff --expect <h12>`), `거부 <video>
     <h12>` sends the work back (`state.py reject-source-diff <video> --expect <h12>`).
   - `stagnation`, `render` and the others: ask the person what to do; `해제 <video> <lang> <held>` then
     `state.py unlock <video> --expect <held>`.
   Every such answer is asked with AskUserQuestion, and the command runs alone as your next tool call, in the same
   turn, right after the answer — do not wait for the person; never in the same assistant message as the question.
4. Not held: go to the stage `next` named (`setup.py doc make` lists the stage documents).

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
> Exception: when the refusal itself says 'This is not a stop', do what it says — that is not
> reaching the same effect another way.
<!-- /studio:guard-refusal -->
