# SPRINT RUN (unattended development of a sprint's members to PRs — the engine's supervisor)

**This file only asks the human and starts the engine.** The supervisor is fixed engine code
(`<<SKILL_DIR>>/engine/engine.py sprint run`, `commands/engine/sprint.md`): it develops every
member with the same engine run as `/gld dev`, one after the other, in dependency order, stacking
a PR where a dependency has not landed yet. No LLM takes part, no permission is bypassed, nothing
merges (INV1). The human reviews and merges concurrently; the supervisor never touches their
working tree, index or local branches.

**Arguments.** A token starting with `--` is a **flag** and its position does not matter. The
ad-hoc/resume decision is made from the **first non-flag argument**: numbers (comma-separated)
→ ad-hoc sprint, none → **resume the active sprint**.

The known flags are **`--readiness`** · **`--window`** · **`--duration`** (= an alias of
`--window`) · **`--allow-red-base`** · **`--take-over`** and nothing else.

- ⚠ **Any other `--` token is REFUSED**, with the valid list printed. Never ignored.
  `FAIL: unknown flag <token> — valid flags: --readiness, --window=<HH:MM-HH:MM|none>,
  --duration=<same>, --allow-red-base, --take-over`. An unknown flag that is silently dropped
  (`--duration 22:00-10:00`) leaves no non-flag argument, which reads as *"resume the active
  sprint"* and starts a **24-hour unattended run with no window at all**.
- ⚠ **A flag's VALUE token is not counted as a non-flag argument.** Consume the value first.
- ⚠ **`--window` and `--duration` accept BOTH a space and an `=`**: `--window 22:00-10:00` and
  `--duration=22:00-10:00` are the same input.
- ⚠ **A leftover non-flag token is not ignored either.** `/gld sprint run 101 102` (spaces
  instead of a comma) would lose 102 silently. Refuse and show the `101,102` form.
- ⚠ **`--readiness` is the one exception to all of this** — it prints the Phase 0 table and
  **stops**. It must never fall through to *"resume"*.
- **`--allow-red-base`** · **`--take-over`** are the human's own words: pass one on only when the
  human typed it for THIS run. Never suggest, add or repeat one on your own.

**`--window <HH:MM-HH:MM>`** (alias `--duration`) limits when this run may **start a new
member**; a member that has started runs to its end.

- 24-hour clock, **zero padding required**. Validate against this literal:
  **`HH:MM-HH:MM (24h, zero-padded)`**; `~` is accepted as the separator.
- The **end is exclusive**; **start == end is refused** (*"omit the window instead"*).
- `--window none` runs this one time with **no** window.
- Precedence: **flag > the previous run (the engine keeps it) > `config.sprint.window`**.

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State/labels: `_handoff.md`. Membership ·
> edges: `_sprint_dag.md`. **Output language**: `config.language`; machine tokens stay ASCII.

---

## Phase 0 — Preflight

`--readiness` prints this table and stops; otherwise a blocking row stops the command. Guild
never starts a run unattended: `printenv GLD_UNATTENDED` → `1` → return
`OK: unattended — starting a sprint run requires a human` (before anything else).

**What is NOT checked here any more**: whether the base is red. The engine checks the named
commands of the repository settings on the fetched default branch itself, before the first member
and before any window wait, and **refuses to start on a red base** (`halted:base-red`); CI is not
read. `--allow-red-base` starts anyway — the members' own verdicts do not change.

**Base CI** (read by `sprint plan` Phase 2 only — it warns the planner; `run` itself never reads CI) — is the default branch already red? Each its own Bash call:
1. `gh repo view <owner>/<repo> --json defaultBranchRef --jq .defaultBranchRef.name` → `<d>`.
2. `gh api repos/<owner>/<repo>/commits/<d>/check-runs --paginate --jq '.check_runs[] | {id, name, conclusion, annotations: .output.annotations_count}'` (`qa.md`'s stream form — `--paginate` reads past the 30-run page).
3. **No run at all** (CI runs on PRs only — one-man-company) → the last merged PR:
   `gh pr list --repo <owner>/<repo> --state merged --base <d> --limit 20 --json number,headRefOid,mergedAt --jq 'if length == 0 then null else (max_by(.mergedAt) | {number, headRefOid}) end'`
   (the list is in creation order, so `--limit 1` may not be the last merge — the largest `mergedAt` of 20); `null` → Base CI `없음`, done. Otherwise the call of 2 for `commits/<headRefOid>/check-runs`.
4. For each run with `conclusion == "failure"` and `annotations > 0` (at most 3), `qa.md`'s annotation call — a `was not started` message is `ci-blocked`, kept apart from red.

**Which runs count**: one per check **name** — when a name appears more than once (a re-run), keep the run with the **highest `id`** (the latest attempt; measured one-man-company PR #647: an earlier failed attempt beside its green re-run). **Which verdict**: `qa.md` Step 2's *Which one* rule over those runs — conclusion `failure` · `timed_out` · `cancelled` · `action_required` → red (a never-started one → `ci-blocked`); else any `null` → still running, read as `green` with `(진행 중)`; else green (`neutral` and `skipped` are not red). The result always **names the checks it judged**, because a default branch may carry only non-code checks:
Result: `green(<checks…>)` · `red(<checks…>) (근거: <d> 최신 커밋 | 마지막 머지 PR #<p>)` · `ci-blocked(<checks…>)` · `없음` · `unavailable` (a call failed).

| Check | How | Verdict |
|---|---|---|
| Guild initialized | `ls .claude/guild/harness.json` | **block** |
| **Engine settings committed** | `git ls-files --error-unmatch .claude/guild/config.json CLAUDE.md` (and spot-check `.claude/agents/`, `docs/standards/`) — the engine reads them from the **remote default branch**, so an uncommitted or unpushed one does not exist for it | **block** |
| Engine can run unsandboxed | the pattern `python3 -I <<SKILL_DIR>>/engine/engine.py:*` is in `sandbox.excludedCommands`, or the human approves the one unsandboxed call of Phase 3 (`commands/engine/dev.md` step 1.3) | **block** |
| `guild:sprint` label exists | `gh label list --limit 200 --json name --jq '[.[].name]'` | **block** |
| GitHub credential | *Phase 0b*, the `gh auth status` check | **block** when it says so |
| Merge strategy | `gh repo view <owner>/<repo> --json mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed` (the repo is positional) | warn — tell the human what the engine will do: merge commits allowed → plain stacked PRs; not allowed and 상한 근거 `squash-sync` / `human-override` → stacked PRs open as **drafts**, `/gld sprint sync` readies them after each merge; `merge-commit-forbidden`, any other token, or an unreadable answer → no stack: a dependant waits as `dep-unmerged` until its dependency has merged |
| The stable Guild is not running here | name it in the final ask: a stable-edition sprint or dev on this repository and this engine do not see each other's locks | **block** when it is |
| Plan record committed | `git status --porcelain -uall -- docs/specs/` — any line under `docs/specs/sprint-<tracker number>/` | warn, once — *"plan 기록이 커밋되지 않았습니다: <paths> — 커밋해 두지 않으면 잊기 쉽습니다"* |
| **Not already running** | Phase 1 step 3 — the lock is the engine's; another machine's run needs the human | **block** |

### Phase 0b — credential and window questions, asked HERE (before the final ask)

**Always — window or not — check which GitHub credential the supervisor will inherit: `gh auth
status`, its own Bash call, exactly that command.** It masks the token (`gho_****`) and names the
source of every account. Judge by the **output text, not the exit code** — one expired keyring
account alone makes it exit 1:
- a line `✓ … (GH_TOKEN)` → `GH_TOKEN` is in use; with a window, item 3 below warns and asks.
- a line `X … (GH_TOKEN)` → `GH_TOKEN` is invalid. **Stop before the run, in every run**:
  *"GH_TOKEN 을 설정한 곳(셸 프로필·Claude settings 의 env)에서 갱신하거나 지운 뒤 Claude 세션을
  다시 시작하세요"*. `gh auth login` does not fix it — `GH_TOKEN` overrides the keyring.
- `(GITHUB_TOKEN)` overrides the keyring the same way; read it the same way.
- no `(GH_TOKEN)`/`(GITHUB_TOKEN)` → the keyring account is used; its active account line `X` →
  stop: "gh 로그인이 만료됐습니다 — `gh auth login` 후 다시 실행하세요".

⚠ **Never `gh auth status --show-token`, `gh auth token`, or a command that prints a secret
environment variable's value (`env`, `printenv GH_TOKEN`, `echo`)**, and never
`test -n "${GH_TOKEN:-}"` (`_bash_rules.md` — quoted variable substitution).

Resolve the effective window: the flag; else the previous run's (`sprint status --json`, Phase 1
step 3: `.sprint.window`); else `config.sprint.window` (`.claude/guild/harness.json` — the engine
never reads that file, so a config window is passed on as `--window`). `none` → no window. Then,
**when there is a window**:

1. **Window shorter than 120 minutes → WARN.** ⚠ **Count MINUTES, not the `HHMM` difference**:
   **`23:00-00:30`** and **`00:30-02:00`** are both 90 minutes → both WARN. ⚠ **The engine
   does not judge window length** — this is the only judge.
2. **DST warning, with the WARN.** A window that falls entirely inside the hour a
   daylight-saving transition **skips** does not open that day.
3. **`GH_TOKEN` + a window → warn and ask** (`✓ … (GH_TOKEN)` in the `gh auth status` check above). A GitHub App installation token lasts an hour and a
   window structurally guarantees an idle gap. The supervisor tolerates 18 consecutive marker
   failures while waiting (about three hours); it cannot absorb a permanent expiry.
4. **`caffeinate`.** The engine starts the supervisor under `caffeinate -i` itself when a window is
   in effect and `caffeinate` is installed; it cannot hold a closed lid. Say it plainly:
   *"뚜껑을 닫으면 감독자는 잡니다. 밤새 돌리시려면 전원을 연결하고 뚜껑을 열어 두시거나 `pmset`
   스케줄을 쓰십시오 — Guild가 대신 해 드릴 수 없습니다."*

Finally, show the warnings and the plan (members, order, window), then ask once: *"이대로 무인
실행할까요?"* ⚠ **When a window is set the ask must
name four things** — the window, the estimated number of nights, that `plan --create` and
`retro` will be refused for the whole run, and how to stop it (`engine.py sprint stop`). A person
approving at 21:00 otherwise cannot know they are approving 03:00 three days later.

## Phase 1 — Resolve the sprint

1. **Resolve `{owner}/{repo}`** once (`_handoff.md` Section F) and the repository root
   (`git rev-parse --show-toplevel`).
2. **Find the sprint.**
   - `$1` empty → the open `guild:sprint` Issue. None → *"활성 스프린트가 없습니다. `/gld sprint plan`으로 먼저 계획하세요."* Two or more → ask which.
   - `$1` = numbers → **create a tracking Issue for them first**, running `plan.md` Phase 0 step 5 (merge strategy → 상한 근거; on a squash-only repo `squash-sync` unless the human declines), Phase 4 (cycles → linearize → order → depth) and Phase 6 on the given set, with goal "즉석 스프린트", capacity "사람 지정" and 리팩토링 슬롯 `skip (ad-hoc)` — and, for the `plan.md` Phase 6 template's machine fields, `구분` = `goal` for every member, `- capacity: n/a`, `- shortfall: n/a`, `- adhoc: true`. ⚠ The ad-hoc path is **not** allowed to skip the container: the engine knows only a tracking Issue.
3. **Duplicate-run guard and the previous run** — one read-only call:
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py sprint status --repo OWNER/REPO --tracker T --json
   ```
   `"running": true` → refuse: *"이미 실행 중입니다 (pid N, 시작 YYYY-MM-DD HH:MM). 상태는
   `engine.py sprint status`."* ⚠ **With the date** — a windowed run lives for days. Otherwise the
   engine's own locks decide at the start (exit 3). **Another machine's run** (the tracker's
   `<!-- guild:sprint:run -->` marker names another host and has not ended) is refused by the engine as
   `halted:other-host`: show the human the marker's host and heartbeat; only when they say that run
   is gone, start again with `--take-over`.
3b. **A tracker that Guild 0.98.7 planned or ran** (readiness T3 P8 — word_app #1923 is one). When
   step 3's `"sprint"` is `null` (this machine's engine has never run this tracker) **and** either the
   tracker carries a `<!-- guild:sprint:run -->` comment (`daily.md` step 3's marker call) or a member has
   an open pull request whose branch is not `gld/<N>`, the engine can **read** the tracker — the member
   table and its plan hash are the same format — but it does **not take over** what 0.98.7 did. It
   counts a member as finished only from this machine's `state.json` or from the member Issue being
   `CLOSED` · `COMPLETED`; labels, 0.98.7 branches (`feature/#N-…`, `fix/#N-…`) and their PRs are never
   read as done. Show this checklist before the final ask, in `config.language`, and ask whether every
   item holds; an item that does not hold stops the command here (nothing was started):
   ```
   0.98.7 스프린트 이어가기 — 시작 전에 사람이 할 일
   ① 0.98.7 멤버 PR 을 먼저 리뷰해 머지하거나 닫습니다. 열린 PR 이 이미 닫는 멤버는 엔진이 시작하지 않고
      거부합니다(open-closing-pr — 두 번째 PR 을 만들지 않음). 그 멤버에 의존하는 멤버도 막힙니다.
   ② 머지한 멤버의 Issue 가 '완료'로 닫혔는지 봅니다. 기본 브랜치가 아닌 곳(스택)에 머지한 PR 은 Issue 를
      닫지 않습니다 — 열려 있으면 직접 '완료'로 닫으세요. 닫힌 멤버는 엔진이 closed 로 넘어갑니다.
   ③ PR 을 닫고 다시 개발할 멤버는 guild:done 라벨을 떼세요. 남아 있으면 엔진이 완료 여부를 모른다며
      거부합니다(done-unconfirmed).
   ④ 0.98.7 감독이 이 기계에서 돌고 있지 않아야 합니다: pgrep -fl "sprint-<T>.sh" 결과가 비어 있어야
      합니다. 엔진은 0.98.7 감독의 잠금을 보지 못합니다.
   ⑤ 실행 시간 창은 --window 로 직접 주세요. 엔진은 0.98.7 마커의 window 를 읽지 않습니다
      (harness.json 의 sprint.window 가 있으면 그 값을 넘깁니다).
   ⑥ 0.98.7 마커 댓글의 원장 키(retries·board_* 등)는 엔진의 첫 마커 갱신에서 사라집니다. 남겨 둘
      것이 있으면 시작 전에 그 댓글을 복사해 두세요. 실행 중 보드 카드는 움직이지 않습니다.
   ⑦ 시작한 뒤 daily·retro 는 0.98.7 의 .sprint-logs/<T>/failures.jsonl 을 이 스프린트의 실패로
      읽지 않습니다(엔진 실행 전 기록).
   ```
   Item ④ is the one call here, its own Bash call: `pgrep -fl "sprint-<T>.sh"` (it matches the 0.98.7
   supervisor's script name; empty output and exit 1 = none). A line → stop: *"0.98.7 감독(pid <pid>)이 아직
   돌고 있습니다 — 끝나거나 멈춘 뒤 다시 실행하세요"*. Never `kill` it yourself. The other items are the
   human's word — do not check them by reading PRs or labels here: the engine refuses what is still open,
   member by member, and names it (member outcome `refused` with `open-closing-pr` or `done-unconfirmed`).
4. **Verify the plan** — no write:
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py sprint check --repo OWNER/REPO --tracker T
   ```
   It prints the order the run will follow. Exit 4 → stop and show the line: a malformed member
   table, a cycle, a plan-hash mismatch or a `blocked:` member (an epic, an open pull request that closes it, a
   `gld/<N>` left on the remote, `guild:done` on the open Issue — readiness T1 P7) means running `/gld sprint plan`
   again — never edit the
   table by hand. A mismatch can mean `plan --create` died mid-Phase 6: when the tracker carries a
   `<!-- guild:sprint:slot-net -->` comment whose slot Issue's body still lacks `<!-- guild:safety-net -->`,
   tell the human to re-run `/gld sprint plan` first and choose to **add** to the open sprint — that
   path applies the approved Safety net. The same when a `<!-- guild:sprint:plan-decisions -->` line is
   missing from its member's body: running now would send the member to an unattended `analyze`
   that stops on the very question the human already answered.

## Phase 3 — Start the supervisor

1. Start it **outside the conversation's sandbox** (as `commands/engine/dev.md` step 1.3), one call
   — with `--window W` when a window is in effect (Phase 0b), and the two human flags only when typed:
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py sprint run --repo OWNER/REPO --tracker T --checkout REPO_ROOT
   ```
   The command detaches the supervisor and returns at once, printing its log path. Exit 3 = a
   supervisor of this repository runs already; exit 4 = refused, the line says why; exit 2 = a usage
   error. ⚠ **Never read the supervisor log or anything under `~/.gld/records/` into the conversation.**
2. Report: sprint number, member count, and *"진행 상황은 `engine.py sprint status`. 할당량은 리셋이
   4시간 이내면 기다려 재개하고, 더 멀면 그 멤버를 막아 두고 끝냅니다 — 리셋 뒤 `/gld sprint run` 을
   다시 치면 그 멤버부터 이어집니다."* **When a window is in effect, this must also carry**:
   - **The window**, and *"창 밖에서는 새 멤버를 시작하지 않고 기다립니다"*.
   - **An estimated number of nights, as a RANGE**: `ceil(members × 60min ÷ window minutes)`
     rendered as *"대략 1~3밤"*; a window shorter than 90 minutes → the member count.
   - ***"낮의 편집은 무효입니다"*** — the member set was fixed at launch.
   - ***"완주 통지는 없습니다 — 아침에 `engine.py sprint status` 로 확인하십시오."***
   - **How to stop it**: `engine.py sprint stop` — *"대기 중이면 최대 60초, 멤버 작업 중이면 그 멤버가
     끝난 뒤에 멈춥니다. `kill -9` 는 쓰지 마십시오."*
3. Attended follow-up: the human may poll with `sprint status … --wait 540` (short output only) or end
   the conversation — the supervisor outlives it.

**What the supervisor does** (so this file is readable on its own; the engine is canonical):
per member — wait for the window · read the Issue, its dependency and its state fresh · blocked?
record it and go on · fetch the base into `refs/remotes/origin/` only · run
`engine.py dev --foreground --mode unattended` for it and wait · judge by exit code and state.json ·
update the tracker's one `<!-- guild:sprint:run -->` comment at least every 10 minutes. A member that
stopped blocks only the members on it; a boundary failure (canary, self check, init) ends the run.
A repository command waits for other repository commands on this machine.

## Phase 4 — On completion

When the status output says `finished` or `halted`:

1. Report per-member outcomes with counts and cost: `done` · `closed` · `stopped` · `blocked` (and by
   what) · `skipped-locked` · `refused` · `failed`. A `stopped` member is answered with
   `/gld resume <n>` (`commands/engine/dev.md` section 3), then `/gld sprint run` again — it never
   starts a `done` member twice, and it continues the blocked ones.
2. List the kept member worktrees and their size (`sprint report --json` → `members[].worktree`) —
   they are needed for `resume --pr-review`; removing one is the human's.
3. State both termination axes (`sprint.md` — run finished vs sprint finished).

`halted:<reason>` — name the action, never only the counts:

| `halt` | What to say |
|---|---|
| `base-red` | The default branch is red (the tracker comment names the commands). Fix it, or — the human's call — `--allow-red-base`. When the base could not be checked at all, only fixing that helps |
| `boundary` | The sandbox / gate / canary of THIS machine failed — `commands/engine/dev.md` section 3 (`canary-failed`); the next member would stop at the same place |
| `marker-unwritable` | The tracker could not be written several times in a row (usually an expired token or a network outage). The reason is in `engine.py sprint status` |
| `plan-hash-mismatch` | The tracker body changed after planning — run `/gld sprint plan` again |
| `other-host` | Phase 1 step 3 |
| `signal` | Someone stopped it. The running member finished first; re-run to continue |
| `engine-error` | An engine failure, or the engine's files changed during the run (an update). The supervisor log has the traceback; re-run after it is fixed |

⚠ **Never report a `halted:*` run with the normal counts alone.**

## Return

`OK: run started — sprint #<t>, <N> members` · `OK: run finished — done <N> / closed <C> / stopped <M> / blocked <J> / failed <K>` ·
`OK: already running (pid <p>, since <t>)` · `OK: run halted — <reason>` ·
`OK: unattended — starting a sprint run requires a human` ·
`FAIL: preflight blocked — <row>` · `FAIL: <reason>`

---

## Hard rules

- **Nothing merges** (INV1), nothing is force-pushed, no permission prompt is bypassed: every role
  session of every member runs with the engine's own rendered settings.
- **Never answer a stop on the human's behalf.** The only thing a run answers itself is a quota
  stop whose reset time has passed (the human re-typing `run` is that answer).
- **Never touch the human's working tree, index or local branches** — neither does the supervisor.
- **The engine decides, not this file.** No label, log line or comment is read here to judge an
  outcome; `sprint status` / `sprint report` are the only sources.
