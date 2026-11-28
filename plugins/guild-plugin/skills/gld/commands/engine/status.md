# STATUS — stage-1 engine (`/gld status <N>`)

**Read-only** — except step 3's removal, which only follows the human's explicit pick. Merges the engine's three
records of the Issue — `state.json` (step states, stop, totals), `log.jsonl` (the last events) and the attempt
folders — and shows whether an engine is running. It never posts or labels.

`$1` = Issue number · empty → step 3 only.

> **Bash**: one command per Bash call (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`).

1. Resolve `owner/repo` (its own Bash call):
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   ```
2. Show the status (inside the sandbox is fine — it only reads `~/.gld/`):
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py status --repo OWNER/REPO --issue N
   ```
   Relay the output as is: the running / finished line, the stop (reason, step, note) and
   the allowed answers, the PR, attempts · cost · measurement warnings, one line per step;
   in stage 2 also the leader recommendation / failure of the stop, `waiting for the leader`
   for a `needs_leader` stop, `closed as decided` and one line per leader decision; in stage 3 also
   the step requests, irreversible changes (`WAITING for a human` = the open question), raised
   sessions, included fixes, follow-ups and the engine-local security findings (a public
   repository: they exist only here - never copy them to GitHub).
   A whole sprint: `commands/engine/sprint.md` (`sprint status`). For a machine-readable view add `--json`. When a stop is shown, point to `/gld resume N`.
3. **Engine records nobody touched for 90 days** (readiness R1 — the only place they are named; nothing is removed
   silently). Its own Bash call, read-only:
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py records stale --json
   ```
   `items` empty → say nothing. Otherwise, after the status above, one block from the engine's fields only:
   ```
   ▎90일 넘게 손대지 않은 엔진 기록 <items 수>건 (합계 <records_bytes+tmp_bytes 합 MB>)
     1. <pick> — 마지막 활동 <last_activity 날짜> (<age_days>일) · <records_bytes+tmp_bytes MB>
     …
     지울 번호를 말씀해 주세요(예: 1 2 · 모두 · 없음). 사건이 참조하는 기록과 실행 중인 엔진의 기록은 목록에 없습니다.
   ```
   Then **stop and wait for the answer**. No answer, *없음* or anything unclear → remove nothing. Only for the numbers the
   human named, one call (outside the sandbox like `dev` — `commands/engine/dev.md` step 1.3 — it removes engine records):
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py records stale --apply --pick OWNER/REPO#N --pick OWNER/REPO#M
   ```
   It checks each pick again and refuses one that is no longer stale, now named by an incident, or running (exit 4 —
   relay its line; the others were still removed). Never `rm` anything under `~/.gld/` yourself. A worktree
   (`.gld-<repo>-<N>`) is not an engine record and is not touched here.

Other machines see the Issue's progress in its GitHub summary comment and `guild:<step>`
label; the engine state itself is local to the machine that ran `/gld dev`.
