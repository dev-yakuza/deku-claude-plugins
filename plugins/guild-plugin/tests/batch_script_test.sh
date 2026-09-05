#!/usr/bin/env bash
# Verification for the supervisor script embedded in commands/batch.md.
#
# The script is not a file in this repo — `/gld batch` Phase 3 generates it from the ```bash
# block in batch.md. So this test extracts that block from the shipped Markdown and exercises
# it, which means a regression in the doc is caught the same way a regression in a real file
# would be.
#
# Every case below is a bug that shipped:
#   - the plain-text rate limit was counted FAILED (the fallback re-ran the identical jq that
#     had just returned empty, so it could never produce a reset time)
#   - a non-epoch resetsAt fed straight into shell arithmetic
#   - an empty issue set aborted with `ISSUES[@]: unbound variable` under bash 3.2 + set -u
#
# Usage: bash plugins/guild-plugin/tests/batch_script_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DOC="${1:-$HERE/../skills/gld/commands/batch.md}"
[ -f "$DOC" ] || { echo "missing: $DOC" >&2; exit 1; }
# bash 3.2 is the macOS default /bin/bash and the oldest interpreter this script must survive.
SH="${SH:-/bin/bash}"
WORK="$(mktemp -d)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s (expected %s, got %s)\n' "$1" "$2" "$3"; }

python3 - "$DOC" "$WORK/batch.sh" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
m = re.search(r'```bash\n(#!/usr/bin/env bash.*?)\n```', src, re.S)
if not m:
    sys.exit("could not extract the supervisor script from batch.md")
body = m.group(1).replace('<ISSUE_NUMBERS>', '1 2').replace('<PLUGIN_VERSION>', 'test')
open(sys.argv[2], 'w').write(body)
PY
[ -s "$WORK/batch.sh" ] || { echo "extraction failed" >&2; exit 1; }

echo ""
echo "== A. 생성 스크립트 자체 =="
# ⚠ `bash -n` EXITS 0 ON A SYNTAX ERROR on macOS bash 3.2.57 — measured, and not a wrapper
# artifact (a control `false` returns 1 in the same shell). So the exit code cannot be the
# signal: this check read `if "$SH" -n …; then ok` and therefore COULD NEVER FAIL. The only
# reliable signal is whether -n wrote to stderr. Found while building /gld sprint's own
# supervisor test, which needed the same check.
"$SH" -n "$WORK/batch.sh" 2>"$WORK/syn.err" || true
if [ -s "$WORK/syn.err" ]; then
  bad "bash 3.2 문법 검사" "syntax ok" "$(head -1 "$WORK/syn.err")"
else
  ok "bash 3.2 문법 검사"
fi
# Control: the detector must actually see an error. If this stops failing, the check above is
# inert again — exactly the state this replaced.
printf 'X=(<PLACEHOLDER>)\n' > "$WORK/syn_control.sh"
"$SH" -n "$WORK/syn_control.sh" 2>"$WORK/syn_control.err" || true
if [ -s "$WORK/syn_control.err" ]; then
  ok "문법 검출기 자체 검증 (대조군이 오류로 잡힘)"
else
  bad "문법 검출기 자체 검증" "대조군이 오류로 잡힘" "대조군이 통과 — 검출기가 무력하다"
fi

# 빈 큐: set -u + bash 3.2 에서 "${ISSUES[@]}" 무가드 전개가 죽던 자리
sed 's/^ISSUES=(1 2)/ISSUES=()/' "$WORK/batch.sh" > "$WORK/empty.sh"
OUT="$(cd "$WORK" && "$SH" empty.sh 2>&1)"
case "$OUT" in
  *"nothing to do"*) ok "빈 이슈 집합 → 깔끔히 종료" ;;
  *unbound*)         bad "빈 이슈 집합 → 깔끔히 종료" "clean exit" "unbound variable" ;;
  *)                 bad "빈 이슈 집합 → 깔끔히 종료" "clean exit" "$(printf '%s' "$OUT" | tail -1)" ;;
esac

# ── batch.md 의 펜스 **밖** 불변식. cmp.py 는 펜스 바이트만 보고, 감독자 스위트의 핀은 $TPL
#   만 본다 — 그래서 아래 셋은 어느 검사에도 잡히지 않은 채 전 스위트를 통과했다(실측).
# ⚠ Against a COMMENT-STRIPPED copy of the fenced script. `$DOC` is Markdown — mostly prose — so
# a whole-file grep is satisfied by the very line that records what was removed (`# was: …`).
# Two regressions shipped green that way: an unconditional `COMPLETED=1` (the run deletes its own
# re-run script) and a commented-out jq preflight.
python3 - "$DOC" "$WORK/doc_code.txt" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
m = re.search(r'```bash\n(#!/usr/bin/env bash.*?)\n```', src, re.S)
body = m.group(1) if m else src
open(sys.argv[2], 'w').write(
    "\n".join(l for l in body.split("\n") if not l.strip().startswith("#")))
PY
bfix() { # bfix <label> <fixed-string>
  if grep -qF -- "$2" "$WORK/doc_code.txt"; then ok "$1"
  else bad "$1" "$2" "not found in batch.md's CODE"; fi
}
# 한도로 포기한 run 은 스크립트를 남겨야 한다. 무조건 COMPLETED=1 이면 EXIT 트랩이 지우고,
# 사람은 재실행할 수단을 잃는다 — 이 파일 스스로 "끝나지 않은 run 은 스크립트를 남긴다"고 적었다.
bfix "batch: 미완이면 스크립트를 지우지 않는다" 'if [ "$((FAILED + INCOMPLETE))" -eq 0 ]; then COMPLETED=1; fi'
# 이 상한이 batch 의 rate-limit 루프에 존재하는 유일한 경계다. 백오프는 RL_TRIES*300 이고
# WAIT_MAX 로 다시 검사되지 않으므로, 상한이 느슨해지면 잠자는 시간이 년 단위가 된다.
# ⚠ POSITION and ABORT, checked with offsets — NOT a multi-line `grep -qF`. grep treats a
# multi-line pattern as an OR of its lines, so the "sequence" form asserted only that one of
# them existed and the regression it exists to stop stayed green (measured: moving the cap back
# inside the no-reset branch gave 1,883 child sessions in 25 seconds, all suites passing).
python3 - "$DOC" <<'PY' > "$WORK/bpin.txt"
import sys
src = open(sys.argv[1]).read()
inc  = src.find('RL_TRIES=$((RL_TRIES + 1))')
cap  = src.find('if [ "$RL_TRIES" -gt 6 ]; then')
nores= src.find('if [ -z "$WAIT" ] || [ "$WAIT" -le 0 ]; then')
pre  = src.find("| jq -r -R '(fromjson? // empty)")
ab   = src.find('exit 1', pre) if pre >= 0 else -1
prend= src.find('\nfi', pre) if pre >= 0 else -1
bad = []
if not (0 <= inc < cap):            bad.append("increment must precede the cap")
if not (0 <= cap < nores):          bad.append("the cap must sit OUTSIDE (before) the no-reset branch")
if not (0 <= ab < prend):           bad.append("the jq preflight must abort with exit 1")
print("OK" if not bad else "; ".join(bad))
PY
if [ "$(cat "$WORK/bpin.txt")" = "OK" ]; then
  ok "batch: 상한이 no-reset 갈래 밖이고 preflight 이 중단한다"
else
  bad "batch: 위치/중단" "position+abort" "$(cat "$WORK/bpin.txt")"
fi
# 감지는 jq 로 판정한다 — 없거나 깨진 jq 는 조용히 감지를 죽인다.
bfix "batch: jq preflight (필터를 실제로 돌린다)" "| jq -r -R '(fromjson? // empty)"
# 펜스 뒤의 우선순위 게이트. 없으면 완주한 멤버가 로그 속 한도 때문에 FAILED 로 집계된다.
bfix "batch: 보고용 jq 도 비JSON 줄을 견딘다" "jq -r -R 'fromjson? | objects | select(.type == \"result\")"
bfix "batch: 완주 라벨이 한도를 이기는 게이트" 'case "$STATE" in *guild:needs-human*|*guild:done* ) RATE_LIMITED=0 ;; esac'

echo ""
echo "== B. rate-limit 판정 (배포 스크립트에서 그대로 추출) =="
# batch.sh 의 판정 블록을 함수로 감싸 시나리오별로 호출한다.
python3 - "$WORK/batch.sh" "$WORK/detect.sh" <<'PY'
import re, sys
body = open(sys.argv[1]).read()
# ⚠ The fence's first code line. It moved from `RESET_AT=$(jq -r` to `RL_LAST=$(jq -r` when
# detection became a single pass over the LAST rate_limit_event; a stale anchor here raises and
# the harness is never written, so all of section B reports "detect: command not found".
# ⚠ Start at the STATE read, not at the fence. The priority gate that follows the fence needs
# `$STATE`, and it is the whole reason the fence could be hoisted above the exit-0 guard — a
# harness that skips it cannot see a `guild:done` member being counted FAILED.
start = body.index('    STATE=""')
# ⚠ The GUARD, not the genuine-failure marker. The fence and its handler now sit ABOVE
# `if [ "$EXIT_CODE" -eq 0 ]` (they were dead code on exit 0 below it), so the old end anchor
# would swallow the whole arms block into this harness.
end = body.index('if [ "$EXIT_CODE" -eq 0 ]; then')
block = body[start:end].rstrip()
# `break` only means something inside the shipped loop; make it observable here instead.
block = block.replace('break\n', 'echo "GAVE_UP"; return 0\n')
block = re.sub(r'\bsleep "\$WAIT"', 'echo "SLEEP=$WAIT"', block)
block = block.replace('continue', 'return 0')
# ⚠ EXIT_CODE is a PARAMETER, not a constant. The shared region gates its text fallback on
# `EXIT_CODE != 0` and demotes an already-past reset when `EXIT_CODE == 0`, so both values must
# be exercisable. Fixing it at 1 makes the exit-0 cases below unwritable; fixing it at 0 makes
# `plaintext.log` (whose only structured event is `status:"allowed"`) stop being detected.
# ⚠ WAIT_MAX too: the region can now report a reset up to 30 days out and the script clamps it.
harness = '''#!/bin/bash
set -uo pipefail
detect() {
  LOG="$1"; EXIT_CODE="${2:-1}"; STATE_STUB="${3:-}"; RL_TRIES=0; ISSUE=0
  WAIT_MAX=14400
  OWNER_REPO="o/r"
  gh() { printf '%s' "$STATE_STUB"; }
  FAILED=0; FAILED_ISSUES=()
@@REGION@@
  echo "NOT_RATE_LIMITED"
}
'''
# ⚠ A placeholder, not %-formatting: the stub bodies above contain `printf '%s'`, which the
# format operator consumes — the harness is then never written and every case in this section
# reports "detect: command not found".
open(sys.argv[2], 'w').write(harness.replace('@@REGION@@', '\n'.join('  ' + l for l in block.splitlines())))
PY

run_case() { # $1=label $2=expected-token $3=logfile [$4=exit-code=1] [$5=label-stub]
  local out; out="$("$SH" -c ". '$WORK/detect.sh'; detect '$3' '${4:-1}' '${5:-}'" 2>&1)"
  case "$out" in
    *"$2"*) ok "$1" ;;
    *)      bad "$1" "$2" "$(printf '%s' "$out" | tr '\n' ' ')" ;;
  esac
}

FUT=$(( $(date +%s) + 600 ))
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"limited","resetsAt":%s}}\n' "$FUT" > "$WORK/structured.log"
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}\n{"type":"result","result":"Error: rate limit exceeded, try again later"}\n' > "$WORK/plaintext.log"
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"limited","resetsAt":"2026-08-22T10:00:00Z"}}\n' > "$WORK/iso.log"
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}\n{"type":"result","result":"Error: command not found: flutter"}\n' > "$WORK/crash.log"

run_case "구조화 resetsAt → reset 시각까지 대기"        "SLEEP=" "$WORK/structured.log"
run_case "평문 rate limit → 백오프 (FAILED 로 안 떨어짐)" "SLEEP=" "$WORK/plaintext.log"
run_case "ISO-8601 resetsAt → 산술 대신 백오프"          "SLEEP=" "$WORK/iso.log"
run_case "무관한 크래시 → rate limit 아님"               "NOT_RATE_LIMITED" "$WORK/crash.log"

# ── 신설: 공유 영역이 exit 코드에 따라 갈리는 것을 행동으로 고정한다 ──────────────
# ⚠ 이 둘이 없으면 "구조화는 모든 종료코드 · 폴백은 exit≠0" 를 지키는 것이 문자열 grep 하나뿐이다.
run_case "구조화 한도 + exit 0 → 여전히 감지"            "SLEEP=" "$WORK/structured.log" 0
run_case "평문 한도 + exit 0 → 감지 안 됨(폴백은 exit≠0)" "NOT_RATE_LIMITED" "$WORK/plaintext.log" 0

# ── 신설: jq 가 로그를 통째로 잃는 두 경로 (측정된 회귀) ──────────────────────────
# 선두 stderr 잡음: jq 는 첫 파싱 에러에서 중단하므로 `-R 'fromjson?'` 없이는 두 감지기가 동시에 죽는다.
printf 'Error: some startup noise on stderr\n{"type":"rate_limit_event","rate_limit_info":{"status":"limited","resetsAt":%s}}\n' "$FUT" > "$WORK/headnoise.log"
run_case "선두 stderr 잡음 + 구조화 한도 → 감지"          "SLEEP=" "$WORK/headnoise.log"
# rate_limit_info 없는 이벤트: `null` 이 출력되어 `jq -e` 가 1 을 반환한다 → `objects` 가 막는다.
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected"}}\n{"type":"rate_limit_event"}\n' > "$WORK/noinfo.log"
run_case "rate_limit_info 부재 이벤트 → 여전히 감지"      "SLEEP=" "$WORK/noinfo.log"
# 맨 JSON 스칼라: `.type` 인덱싱 에러로 `jq -e` 가 5 를 반환한다 → 같은 `objects` 가 막는다.
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected"}}\n999\n' > "$WORK/scalar.log"
run_case "맨 JSON 스칼라 줄 → 여전히 감지"                "SLEEP=" "$WORK/scalar.log"

# ── 신설: 소독 각 단계 ────────────────────────────────────────────────────────────
# (1b) 20자리는 bash 3.2 에서 `[` 를 rc=2 로 죽여 (2)(3) 을 모두 건너뛰게 만든다.
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"limited","resetsAt":99999999999999999999}}\n' > "$WORK/d20.log"
run_case "(1b) 20자리 resetsAt → 폐기 후 백오프"          "SLEEP=300" "$WORK/d20.log"
# (2) 밀리초는 전부 숫자라 (1) 을 통과한다 — 나누지 않으면 ~56,000년을 기다린다.
MS=$(( FUT * 1000 ))
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"limited","resetsAt":%s}}\n' "$MS" > "$WORK/ms.log"
run_case "(2) 밀리초 resetsAt → 초로 환산"                "SLEEP=6" "$WORK/ms.log"
# (3) 60일 뒤. ⚠ 10자리라 (1b) 를 통과하므로 (3) 의 *존재*가 관측되는 유일한 자리다.
FAR=$(( $(date +%s) + 60*86400 ))
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"limited","resetsAt":%s}}\n' "$FAR" > "$WORK/far.log"
run_case "(3) 60일 뒤 resetsAt → 폐기 후 백오프"          "SLEEP=300" "$WORK/far.log"
# (4) 지난 리셋 + exit≠0. ⚠ 이 스크립트는 신뢰 판정을 `-le 0` 로 **유지**하므로 WAIT=0 이
# 백오프 갈래로 떨어진다 — /gld sprint 는 `-ge 0` 로 통일해 즉시 재시도한다. 이 단정이
# 그 결정을 고정한다: `-ge 0` 로 바꾸면 `sleep 0` 무한 스핀이 되어 여기가 깨진다(상한이
# no-reset 갈래 **안**에 있어 WAIT=0 은 그 상한에 영원히 닿지 못한다).
PAST=$(( $(date +%s) - 600 ))
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"limited","resetsAt":%s}}\n' "$PAST" > "$WORK/past.log"
run_case '(4) 지난 리셋 + exit≠0 → 백오프 (-le 0 유지)'  "SLEEP=300" "$WORK/past.log"
# (4) 지난 리셋 + exit 0 → CLI 가 이미 기다려낸 것이므로 한도로 인정하지 않는다.
run_case "(4) 지난 리셋 + exit 0 → 한도 아님"             "NOT_RATE_LIMITED" "$WORK/past.log" 0

# ── 신설: 천장. 이 스크립트는 맨 `sleep` 을 쓰므로 반드시 필요하다 ────────────────
SIX=$(( $(date +%s) + 6*3600 ))
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"limited","resetsAt":%s}}\n' "$SIX" > "$WORK/sixh.log"
run_case "6시간 뒤 리셋 → 4h 천장 초과로 포기"            "GAVE_UP" "$WORK/sixh.log"

# ── 신설: 판정을 "마지막 이벤트" 로 바꾼 것의 두 결과 ─────────────────────────────
# 한도에 걸렸다가 회복한 로그(마지막 이벤트가 allowed) → 한도로 세지 않는다. status 는 현재 상태
# 텔레메트리이므로, 로그 어디든 non-allowed 가 있으면 잡는 방식은 건강한 멤버를 6회 재우고 만다.
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":%s}}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}\n' "$FUT" > "$WORK/recovered.log"
run_case "한도→회복(마지막이 allowed) → 한도 아님"        "NOT_RATE_LIMITED" "$WORK/recovered.log"
# 리셋 없는 살아있는 이벤트가 뒤에 오면, 앞 이벤트의 낡은 리셋을 물려받아선 안 된다.
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":%s}}\n{"type":"rate_limit_event","rate_limit_info":{"status":"rejected"}}\n' "$(( $(date +%s) - 600 ))" > "$WORK/stale.log"
run_case "낡은 형제가 살아있는 미지 리셋을 가리지 않는다"   "SLEEP=300" "$WORK/stale.log"
# 개행 없는 stderr 조각이 이벤트 줄에 붙는 경우. `\r` 스피너는 개행을 내지 않고, $LOG 는
# `> "$LOG" 2>&1` 이라 stdout/stderr 가 오프셋을 공유한다.
printf 'Loading\rLoading.\r{"type":"rate_limit_event","rate_limit_info":{"status":"limited","resetsAt":%s}}\n' "$FUT" > "$WORK/glued.log"
run_case "붙은 stderr 조각 + 구조화 한도 → 감지"          "SLEEP=" "$WORK/glued.log"

# ── 신설: 우선순위 게이트. 펜스를 exit-0 가드 위로 올리면서 팔이 갖던 우선권이 뒤집혔다 ────
# 완주한 멤버의 로그에 rate_limit_event 가 있기만 해도 FAILED 로 집계되던 회귀(실측).
run_case "guild:done 이 로그 속 한도를 이긴다"            "NOT_RATE_LIMITED" "$WORK/structured.log" 0 "guild:done"
run_case "guild:needs-human 도 이긴다"                    "NOT_RATE_LIMITED" "$WORK/structured.log" 0 "guild:needs-human"
run_case "guild:children 은 이기지 않는다"                "SLEEP=" "$WORK/structured.log" 0 "guild:children"

# ── 신설: 건강한 로그가 한도로 오인되지 않는다 (구제의 오검출 방향) ──────────────────────
# JSON 뒤에 개행 없이 stderr 가 붙은 줄. rindex 가 다루는 경우의 거울상이고, 개수 비교식
# 구제는 여기서 발화해 정상 멤버를 매 재실행마다 차단했다(실측).
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}Loading\r\n' > "$WORK/h7.log"
run_case "JSON 뒤 stderr 조각 → 한도 아님"                "NOT_RATE_LIMITED" "$WORK/h7.log"
printf '{"type":"rate_limit_event","rate_limit_info":null}\n' > "$WORK/h4.log"
run_case "rate_limit_info 가 null → 한도 아님"            "NOT_RATE_LIMITED" "$WORK/h4.log"
# 공백 있는 status: `#* ` 는 리셋 대신 "limited <epoch>" 를 넘겨 소독이 폐기한다.
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"rate limited","resetsAt":%s}}\n' "$FUT" > "$WORK/spacestatus.log"
run_case "공백 있는 status → 리셋을 살려낸다"             "(10m " "$WORK/spacestatus.log"
# 한도가 먼저, 정상 객체가 뒤 — 한 줄. 구제에 rindex 가 있으면 두 번째 객체가 깨끗이 디코드돼
# "디코드 실패" 가 거짓이 되고, tail -1 은 앞의 allowed 를 집는다.
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}\n{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":%s}}{"type":"assistant","m":1}\n' "$FUT" > "$WORK/limitfirst.log"
run_case "한도가 먼저인 겹친 줄 → 감지"                   "SLEEP=" "$WORK/limitfirst.log"

# ⚠ A floor. Without it an argument-count error or an unbalanced quote truncates the run and the
# suite reports success on a fraction of its checks. This file now carries four invariants that
# no other suite sees: the COMPLETED gate, the jq preflight, the priority gate, the reporting jq.
BAT_MIN_CHECKS=33
if [ "$((PASS + FAIL))" -lt "$BAT_MIN_CHECKS" ]; then
  printf '\nFAIL  ran only %d checks (floor %d) — the run was truncated.\n' \
    "$((PASS + FAIL))" "$BAT_MIN_CHECKS"
  rm -rf "$WORK"; exit 1
fi

echo ""
echo "결과: PASS=$PASS FAIL=$FAIL"
rm -rf "$WORK"
[ "$FAIL" -eq 0 ]
