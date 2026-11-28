#!/usr/bin/env bash
# Readiness T1 (first promotion — entry guards): the command documents say what the engine guards do.
# Fixed-string checks over the prompts, like prompt_structure_test.sh (design/guild/24-redesign/readiness/promote/t1-guards.md).
#   P3  epics are refused by dev/resume — the documents send the human to the children
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
GLD="${1:-$HERE/../skills/gld}"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
has()   { if grep -qF -- "$3" "$2"; then ok "$1"; else bad "$1 — missing in ${2#"$GLD"/}: $3"; fi; }
lacks() { if grep -qF -- "$3" "$2"; then bad "$1 — still in ${2#"$GLD"/}: $3"; else ok "$1"; fi; }

C="$GLD/commands"

echo "== P3 epic guard"
has   "plan: 에픽 생성 뒤 안내는 자식을 하나씩" "$C/plan.md" '에픽은 아직 지원하지 않습니다 — 자식을 의존성 순서대로 하나씩 `/gld dev <자식>` 으로 개발하세요'
has   "plan: roster 는 dev 오케스트레이션으로 보내지 않는다" "$C/plan.md" 'Epics are not supported yet — develop the children one by one (`/gld dev <child>`); `/gld dev $1` refuses the parent (`unsupported-epic`)'
lacks "plan: 'dev 가 자식을 돌린다' 문구 없음" "$C/plan.md" 'This routes `/gld dev $1` into child orchestration'
lacks "plan: Phase 2b 오케스트레이션 안내 없음" "$C/plan.md" '자식들을 의존성 순서로 오케스트레이션합니다'
has   "design: 분할 반환은 자식 개별 안내" "$C/design.md" 'Epics are not supported yet in this edition: `/gld dev` and `/gld resume` refuse the parent (`unsupported-epic`)'
lacks "design: 'dev 가 자식을 돌린다' 문구 없음" "$C/design.md" 'This routes `/gld dev` into child orchestration'
for f in analyze.md design.md test.md qa.md atoms/_execute_spine.md; do
  has   "$f: 분할 부모 FAIL 은 자식을 개별로" "$C/$f" 'Epics are not supported yet — develop its children one by one (`/gld dev <child>`).'
  lacks "$f: 분할 부모 FAIL 이 dev 로 보내지 않는다" "$C/$f" '`) to drive the children'
done
has   "engine/dev: exit 4 의 unsupported-epic 안내" "$C/engine/dev.md" '에픽은 아직 지원하지 않음 — 자식을 하나씩 `/gld dev <자식>`'
has   "engine/dev: 자식 notice 줄을 전한다" "$C/engine/dev.md" 'A `- notice:` line (stage 4: the Issue is a child of an'

echo "== P2 open closing pull request · R4-12 own stage labels without records"
has   "engine/dev: exit 4 의 open-closing-pr 안내" "$C/engine/dev.md" '`open-closing-pr`: an open pull request on any branch already closes the Issue'
has   "engine/dev: exit 4 의 done-unconfirmed 안내" "$C/engine/dev.md" '`done-unconfirmed`: the Issue carries `guild:done`, is open, and no open pull request closes it'
has   "engine/dev: 기록 없는 단계 라벨은 analyze 부터" "$C/engine/dev.md" 'records here are taken off and the work starts from analyze'

echo "== P5 stage commands refuse an engine Issue"
PF="$C/atoms/_preflight.md"
has   "_preflight: Section 0 엔진 가드" "$PF" '## Section 0 — Engine guard (every stage command, FIRST — before any tier item)'
has   "_preflight: 엔진 질의는 owned" "$PF" 'python3 -I <<SKILL_DIR>>/engine/engine.py owned --repo <owner>/<repo> --issue <N>'
has   "_preflight: 세 표시 — 기록·원격 gld/N·요약 댓글" "$PF" 'engine records on this machine (`engine.py status --json`'
has   "_preflight: 요약 댓글 표식" "$PF" '(`<!-- guild:summary -->`) on the Issue.'
has   "_preflight: 거부 문구는 resume 안내" "$PF" 'REFUSED: #<N> is run by the engine (<the marks the line names>) — continue it with /gld resume <N> (state: /gld status <N>).'
has   "_preflight: 판정 못 하면 통과 아님" "$PF" 'guard could not judge, so it never passes.'
has   "_preflight: 무인도 같은 거부" "$PF" '**Unattended** (`GLD_UNATTENDED=1`): the same — the stage returns `FAIL: engine Issue` and touches nothing.'
for f in analyze.md design.md test.md qa.md atoms/_execute_spine.md; do
  has "$f: Step 0 이 엔진 가드를 먼저 돈다" "$C/$f" '**First, the engine guard** — `_preflight.md` **Section 0**'
done
for f in implement.md debug.md refactor.md; do
  has "$f: 실행 단계는 spine Step 0(엔진 가드 포함)을 돈다" "$C/$f" 'Steps 0–6 of'
done
has   "rollback: 엔진 가드 — stage·PR(gld/ 브랜치)·SHA" "$C/rollback.md" '**Then the engine guard** (`_preflight.md` **Section 0**), before step 1 reads anything else'
has   "rollback: gld/<M> 머리 PR 은 거부" "$C/rollback.md" '`gld/<M>` is the engine'"'"'s branch of Issue `<M>`: refuse as Section 0 does (`/gld resume <M>`)'

echo "== R4-14 one channel per repository"
SK="$GLD/SKILL.md"
has   "SKILL: 라우팅 앞 채널 가드 (channel·help 제외)" "$SK" '**Channel guard — before routing any command except `channel` and `help`**'
has   "SKILL: 가드는 engine.py channel show" "$SK" 'python3 -I <<SKILL_DIR>>/engine/engine.py channel show'
has   "SKILL: exit 4 면 라우팅하지 않는다" "$SK" '**Exit 4 → do not route**'
if sed -n 's/^- Valid commands: //p' "$SK" | grep -qF '`channel`'; then ok "SKILL: channel 이 명령 목록에 있다"; else bad "SKILL: channel 이 명령 목록에 없다"; fi
CH="$C/channel.md"
has   "channel: 드라이런 먼저" "$CH" 'channel set $1 --repo OWNER/REPO --dry-run'
has   "channel: 사람 확인 뒤 전환" "$CH" '**Ask** (`AskUserQuestion`): switch this repository to `$1`'
has   "channel: 무인은 전환하지 않는다" "$CH" '**Unattended** (`GLD_UNATTENDED=1`): never'
has   "channel: 상대 채널 진행 중 실행은 거부·목록" "$CH" 'it lists each Issue / sprint and why it is not finished'
has   "channel: 기계 잠금은 사람 규칙" "$CH" 'heavy-run lock is NOT shared by the two channels'
has   "channel: push 하지 않는다" "$CH" 'never push'
has   "init: 첫 init 이 채널 파일을 쓴다" "$C/init.md" 'python3 -I <<SKILL_DIR>>/engine/engine.py channel set gld --repo <owner>/<repo>'
has   "help: channel 명령" "$C/help.md" '/gld channel <channel>'

echo "== P7 sprint plan leaves out epics, children and taken Issues"
SP="$C/sprint/plan.md"
has   "sprint/plan: 에픽은 후보에서 뺀다" "$SP" '`guild:children` (an **epic** — epics are not supported yet: `/gld dev` refuses it, so it is never a member'
has   "sprint/plan: 자식도 후보에서 뺀다" "$SP" '`guild:child` (a child of an epic — not a sprint member while epics are not supported'
lacks "sprint/plan: '에픽을 빼지 말라' 모순 문장 없음" "$SP" 'Do **not** exclude a `guild:children` parent'
has   "sprint/plan: taken 질의 한 번" "$SP" 'python3 -I <<SKILL_DIR>>/engine/engine.py taken --repo OWNER/REPO --json'
has   "sprint/plan: 열린 PR 이 닫는 이슈 제외" "$SP" '제외: #n (열린 PR #p 가 이미 닫음'
has   "sprint/plan: 원격 엔진 브랜치 남은 이슈 제외" "$SP" '제외: #n (원격 엔진 브랜치 gld/n 남음'
has   "sprint/plan: taken 실패면 계획을 멈춘다" "$SP" 'stop the plan here and report the line'
has   "sprint/plan: 에픽 호출은 이 판에서 건너뛴다" "$SP" '⚠ **Skipped in this edition** (readiness T1 P7)'
has   "sprint/run: check 의 blocked 멤버면 다시 plan" "$C/sprint/run.md" 'a `blocked:` member (an epic, an open pull request that closes it'
has   "engine/sprint: check 가 blocked/note 를 말한다" "$C/engine/sprint.md" 'the members `run` would not start (`blocked:` an epic'

echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
