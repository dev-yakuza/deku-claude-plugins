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
harness = '''#!/bin/bash
set -uo pipefail
detect() {
  LOG="$1"; RL_TRIES=0; ISSUE=0
  FAILED=0; FAILED_ISSUES=()
%s
  echo "NOT_RATE_LIMITED"
}
''' % '\n'.join('  ' + l for l in block.splitlines())
open(sys.argv[2], 'w').write(harness)
PY

run_case() { # $1=label $2=expected-token $3=logfile
  local out; out="$("$SH" -c ". '$WORK/detect.sh'; detect '$3'" 2>&1)"
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

echo ""
echo "결과: PASS=$PASS FAIL=$FAIL"
rm -rf "$WORK"
[ "$FAIL" -eq 0 ]
