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

echo ""
echo "== B. rate-limit 판정 (배포 스크립트에서 그대로 추출) =="
# batch.sh 의 판정 블록을 함수로 감싸 시나리오별로 호출한다.
python3 - "$WORK/batch.sh" "$WORK/detect.sh" <<'PY'
import re, sys
body = open(sys.argv[1]).read()
start = body.index('RESET_AT=$(jq -r')
end = body.index('# Genuine failure (not rate limit)')
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
  LOG="$1"; EXIT_CODE="${2:-1}"; RL_TRIES=0; ISSUE=0
  WAIT_MAX=14400
  FAILED=0; FAILED_ISSUES=()
%s
  echo "NOT_RATE_LIMITED"
}
''' % '\n'.join('  ' + l for l in block.splitlines())
open(sys.argv[2], 'w').write(harness)
PY

run_case() { # $1=label $2=expected-token $3=logfile [$4=exit-code, default 1]
  local out; out="$("$SH" -c ". '$WORK/detect.sh'; detect '$3' '${4:-1}'" 2>&1)"
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
run_case "(4) 지난 리셋 + exit≠0 → 백오프(`-le 0` 유지)"  "SLEEP=300" "$WORK/past.log"
# (4) 지난 리셋 + exit 0 → CLI 가 이미 기다려낸 것이므로 한도로 인정하지 않는다.
run_case "(4) 지난 리셋 + exit 0 → 한도 아님"             "NOT_RATE_LIMITED" "$WORK/past.log" 0

# ── 신설: 천장. 이 스크립트는 맨 `sleep` 을 쓰므로 반드시 필요하다 ────────────────
SIX=$(( $(date +%s) + 6*3600 ))
printf '{"type":"rate_limit_event","rate_limit_info":{"status":"limited","resetsAt":%s}}\n' "$SIX" > "$WORK/sixh.log"
run_case "6시간 뒤 리셋 → 4h 천장 초과로 포기"            "GAVE_UP" "$WORK/sixh.log"

echo ""
echo "결과: PASS=$PASS FAIL=$FAIL"
rm -rf "$WORK"
[ "$FAIL" -eq 0 ]
