#!/usr/bin/env bash
# Empirical verification of the Guild commit gate, both modes, against the SHIPPED files.
#
# Every case in section A is a bypass that a previous version of the gate allowed, and
# every case in section B is a false positive it produced. Both sets are regression tests:
# they encode the reason the gate is shaped the way it is.
#
# Usage: bash plugins/guild-plugin/tests/gate_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
GATE="${1:-$HERE/../skills/gld/gates/gate_precommit.py}"
HOOK="${2:-$HERE/../skills/gld/gates/pre-commit.sh}"
for f in "$GATE" "$HOOK"; do
  [ -f "$f" ] || { echo "missing: $f" >&2; exit 1; }
done
WORK="$(mktemp -d)"
PASS=0; FAIL=0

note() { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s (expected %s, got %s)\n' "$1" "$2" "$3"; }

fresh_repo() {
  rm -rf "$WORK/r"; mkdir -p "$WORK/r"; cd "$WORK/r"
  git init -q .; git config user.email t@t; git config user.name t
  mkdir -p .claude/guild/gates/scripts .claude/guild/gates/rules .claude/guild/memory
  printf '{"gates":{"enabled":true}}' > .claude/guild/config.json
  cp "$GATE" .claude/guild/gates/scripts/gate_precommit.py
  # install the shipped hook exactly as `/gld init` does
  cp "$HOOK" .git/hooks/pre-commit
  chmod +x .git/hooks/pre-commit
  mkdir -p test
  printf 'def test_a():\n    assert 1 == 1\n    assert 2 == 2\n    assert 3 == 3\n    assert 4 == 4\n' > test/t_test.py
  printf 'hello\n' > README.md
  git add -A >/dev/null 2>&1
  git -c core.hooksPath=/dev/null commit -qm base >/dev/null 2>&1
}

# run a command; expect git commit to be BLOCKED (nonzero) or ALLOWED (zero)
expect_commit() {  # $1=label $2=expected(block|allow) $3...=command
  local label="$1" want="$2"; shift 2
  bash -c "$*" >/dev/null 2>&1
  local rc=$?
  local got="allow"; [ $rc -ne 0 ] && got="block"
  if [ "$got" = "$want" ]; then ok "$label"; else bad "$label" "$want" "$got"; fi
}

# run the PreToolUse mode directly with a payload
expect_pre() {  # $1=label $2=expected(deny|allow) $3=command-string
  local label="$1" want="$2" cmd="$3"
  printf '{"tool_input":{"command":%s}}' "$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$cmd")" \
    | python3 .claude/guild/gates/scripts/gate_precommit.py >/dev/null 2>&1
  local rc=$?
  local got="allow"; [ $rc -eq 2 ] && got="deny"
  if [ "$got" = "$want" ]; then ok "$label"; else bad "$label" "$want" "$got"; fi
}

note ""
note "== A. 우회 시나리오 (git 훅이 반드시 잡아야 함) =="
fresh_repo
expect_commit "복합: 시크릿 생성+add+commit 한 줄" block \
  "echo AKIAIOSFODNN7EXAMPLE > s.txt && git add s.txt && git commit -m x"
fresh_repo
expect_commit "복합: assertion 제거 후 commit -am" block \
  "sed -i.bak 's/    assert.*//g' test/t_test.py && rm -f test/t_test.py.bak && git commit -am x"
fresh_repo
expect_commit "복합: 테스트 파일 삭제 후 commit" block \
  "git rm -q test/t_test.py && git commit -m x"
fresh_repo
expect_commit "복합: skip 추가 후 commit -am" block \
  "printf 'import pytest\n@pytest.mark.skip\ndef test_b(): assert 1\n' >> test/t_test.py && git commit -am x"
fresh_repo
expect_commit "focus 지시자(it.only) 추가" block \
  "mkdir -p spec && printf 'it.only(\"x\", () => { expect(1).toBe(1) })\n' > spec/a.spec.js && git add spec/a.spec.js && git commit -m x"

note ""
note "== B. 오탐 회귀 (반드시 통과해야 함) =="
fresh_repo
expect_commit ".env.example 커밋 허용" allow \
  "printf 'API_KEY=\n' > .env.example && git add .env.example && git commit -m x"
fresh_repo
expect_commit "무관한 untracked .env 있어도 다른 파일 커밋 허용" allow \
  "printf 'SECRET=abc\n' > .env && printf 'more\n' >> README.md && git add README.md && git commit -m x"
fresh_repo
expect_commit "더러운 테스트 워킹트리에도 무관한 파일 커밋 허용" allow \
  "sed -i.bak 's/    assert.*//g' test/t_test.py && rm -f test/t_test.py.bak && printf 'more\n' >> README.md && git add README.md && git commit -m x"
fresh_repo
expect_commit "주석 처리된 assertion 삭제는 허용" allow \
  "printf '# assert 1\n# assert 2\n# assert 3\n# assert 4\n' >> test/t_test.py && git commit -qam c1 && sed -i.bak '/^# assert/d' test/t_test.py && rm -f test/t_test.py.bak && git commit -am x"
fresh_repo
expect_commit "Dart Iterable.skip(3) 은 skip 지시자 아님" allow \
  "printf 'void main(){ var x = [1,2,3].skip(2); expect(x, isNotNull); }\n' > test/w_test.dart && git add test/w_test.dart && git commit -m x"

note ""
note "== C. 진짜 시크릿은 계속 차단 =="
fresh_repo
expect_commit "실제 .env 커밋 차단" block \
  "printf 'SECRET=abc\n' > .env && git add .env && git commit -m x"
fresh_repo
expect_commit "Anthropic 키 인라인 차단" block \
  "printf 'K = \"sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAA\"\n' > c.py && git add c.py && git commit -m x"
fresh_repo
expect_commit "id_rsa 차단" block \
  "printf 'x\n' > id_rsa && git add id_rsa && git commit -m x"

note ""
note "== D. PreToolUse 모드 (조기 경고) =="
fresh_repo
printf 'SECRET=abc\n' > .env
expect_pre "단순 커밋인데 무관한 untracked .env → 허용(오탐 없음)" allow "git commit -m x"
expect_pre "git add .env && commit → 거부" deny "git add .env && git commit -m x"
fresh_repo
expect_pre "git log | grep commit → 커밋 아님" allow "git log --oneline | grep -i commit"
fresh_repo
printf 'SECRET=abc\n' > .env; git add .env >/dev/null 2>&1
expect_pre "staged .env → 거부" deny "git commit -m x"
expect_pre "git  -C  .  commit (이중 공백) → 인식하여 거부" deny "git  -C  .  commit -m x"
expect_pre "sudo/env 접두사 → 인식하여 거부" deny "GIT_AUTHOR_NAME=x git commit -m x"
expect_pre "git commit-tree → 커밋 아님" allow "git commit-tree HEAD^{tree} -m x"

note ""
note "== E. off-switch =="
fresh_repo
printf '{"gates":{"enabled":false}}' > .claude/guild/config.json
expect_commit "gates.enabled=false → 통과" allow \
  "printf 'SECRET=abc\n' > .env && git add .env && git commit -m x"

note ""
note "== F. 강제층 제어 파일 가드 (--guard-config) =="
# expects: ask (사람 확인 요구) | pass (통과)
expect_guard() {  # $1=label $2=expected(ask|pass) $3=json payload
  local label="$1" want="$2"
  local out
  out="$(printf '%s' "$3" | python3 .claude/guild/gates/scripts/gate_precommit.py --guard-config 2>/dev/null)"
  local got="pass"
  case "$out" in *'"ask"'*) got="ask" ;; esac
  if [ "$got" = "$want" ]; then ok "$label"; else bad "$label" "$want" "$got"; fi
}
fresh_repo
expect_guard "config.json 의 gates.enabled 끄기 → 확인 요구" ask \
  '{"tool_name":"Write","tool_input":{"file_path":"/r/.claude/guild/config.json","content":"{\"gates\":{\"enabled\":false}}"}}'
expect_guard "dismissed.md 수정 → 확인 요구" ask \
  '{"tool_name":"Edit","tool_input":{"file_path":"/r/.claude/guild/gates/dismissed.md","new_string":"- .env — ok"}}'
expect_guard "게이트 스크립트 수정 → 확인 요구" ask \
  '{"tool_name":"Write","tool_input":{"file_path":"/r/.claude/guild/gates/scripts/gate_precommit.py","content":"pass"}}'
expect_guard "config.json 의 language 변경 → 통과" pass \
  '{"tool_name":"Write","tool_input":{"file_path":"/r/.claude/guild/config.json","content":"{\"language\":\"ko\"}"}}'
expect_guard "일반 소스 파일 수정 → 통과" pass \
  '{"tool_name":"Write","tool_input":{"file_path":"/r/lib/main.dart","content":"void main(){}"}}'

note ""
note "== G. 재사용 스캔 CLI (--scan-paths / --scan-text) =="
# audit_readiness 와 contribute 가 게이트의 패턴을 손으로 베끼지 않고 호출하도록 하는 모드.
# 두 소비자와 커밋 게이트가 "무엇이 시크릿인가" 에 대해 절대 어긋나지 않는 것이 요점.
expect_scan() { # $1=label $2=mode $3=expected-exit $4=stdin $5=expected-substring(또는 "")
  local out rc
  out="$(printf '%s' "$4" | python3 .claude/guild/gates/scripts/gate_precommit.py "$2" 2>&1)"; rc=$?
  if [ "$rc" != "$3" ]; then bad "$1" "exit $3" "exit $rc"; return; fi
  if [ -n "$5" ]; then
    case "$out" in *"$5"*) ok "$1" ;; *) bad "$1" "$5" "$(printf '%s' "$out" | tr '\n' ' ')" ;; esac
  else
    ok "$1"
  fi
}
fresh_repo
expect_scan "--scan-paths 가 실제 시크릿 경로를 잡음" --scan-paths 1 \
  '.env
lib/main.dart
id_rsa
' "SECRET-PATH id_rsa"
expect_scan "--scan-paths 가 허용 목록을 존중 (.env.example)" --scan-paths 0 \
  '.env.example
google-services.json
lib/main.dart
' ""
expect_scan "--scan-text 가 줄번호만 보고 (값 미출력)" --scan-text 1 \
  'ordinary
KEY = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAA"
' "SECRET-TEXT 2"
expect_scan "--scan-text 깨끗한 본문은 통과" --scan-text 0 \
  'just prose
no keys here
' ""
# dismissed.md 를 존중해야 한다 — 커밋 게이트가 통과시키는 항목을 audit 이 BLOCKER 로
# 보고하면 두 소비자가 어긋난다. 실제 저장소(21개 flavor의 iOS 배포 인증서 63개 +
# 릴리스 keystore)에서 이 불일치가 드러났다: 사람이 이미 수용한 위험을 매 audit 마다
# 다시 기각해야 했고, 그건 검사 자체를 무시하게 만든다.
# ⚠ 항목은 마크다운 백틱으로 감싸는 것이 이 파일의 자연스러운 표기이며, 파일 자신의 형식
# 예시와 실제 레포의 사람 작성 항목이 모두 그렇게 쓴다. 백틱을 못 벗기던 시절 이 레지스트리는
# 조용히 아무 일도 하지 않았다 — 사람은 수용 위험을 적었는데 게이트는 계속 차단했고, 왜인지
# 알려주는 신호가 없었다. 두 표기 모두 회귀 케이스로 고정한다.
printf '# accepted\n- `env` — flavor별 배포 인증서 (비공개 레포 정책)\n' > .claude/guild/gates/dismissed.md
expect_scan "--scan-paths 가 백틱 표기 dismissed 를 존중" --scan-paths 0 \
  'env/koreanwords/ios/distribution.p12
lib/main.dart
' ""
# 괄호 부연이 붙은 형태 (실제 레포에서 관측된 형태)
printf '# accepted\n- `env` (`distribution.p12` 등) — 사유\n' > .claude/guild/gates/dismissed.md
expect_scan "--scan-paths 가 괄호 부연이 붙어도 경로만 추출" --scan-paths 0 \
  'env/koreanwords/ios/distribution.p12
' ""
printf '# accepted\n- env — flavor별 배포 인증서 (비공개 레포 정책)\n' > .claude/guild/gates/dismissed.md
expect_scan "--scan-paths 가 백틱 없는 표기도 존중" --scan-paths 0 \
  'env/koreanwords/ios/distribution.p12
lib/main.dart
' ""
expect_scan "dismissed 밖의 시크릿은 계속 잡음" --scan-paths 1 \
  'env/koreanwords/ios/distribution.p12
.env
' "SECRET-PATH .env"
printf '' > .claude/guild/gates/dismissed.md

# 값이 새어나가지 않는지 명시적으로 확인 (INV5)
LEAK="$(printf 'K="sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAA"\n' | python3 .claude/guild/gates/scripts/gate_precommit.py --scan-text 2>&1)"
case "$LEAK" in *sk-ant*) bad "스캔 출력에 시크릿 값이 없음" "no value" "value leaked" ;; *) ok "스캔 출력에 시크릿 값이 없음 (INV5)" ;; esac

note ""
note "== I. 레포 로컬 게이트 확장 (scripts/local/*.py) =="
# update 가 중앙 스크립트를 덮어써도 살아남아야 하는 자리. 이 메커니즘이 없어서 어떤
# 레포는 중앙 파일을 직접 확장했고, update 가 그 검사를 조용히 지워 confirmed 규칙이
# 무력화됐다 — 파일은 남아 있는데 아무도 읽지 않는 상태.
fresh_repo
mkdir -p .claude/guild/gates/scripts/local .claude/guild/gates/rules
printf '# Rule: 테스트명에 이슈번호 금지\nstatus: confirmed\n' > .claude/guild/gates/rules/test-naming.md
cat > .claude/guild/gates/scripts/local/test_naming.py <<'LOCAL'
import re
PAT = re.compile(r"(Issue|PR|이슈)\s*#\d+")
def check(ctx):
    text, confirmed = ctx.rule_file("test-naming.md")
    if not text:
        return [], []
    block, warn, cur = [], [], "?"
    for ln in ctx.changed_diff().splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            if cur.endswith(".dart") and PAT.search(ln) and not ctx.is_dismissed(cur):
                msg = f"테스트/주석의 외부 참조: {cur}"
                (block if confirmed else warn).append(msg)
                ctx.record("test-naming:issue-ref", "block" if confirmed else "warn", cur)
    return block, warn
LOCAL
expect_commit "로컬 확장이 confirmed 규칙으로 차단" block \
  "mkdir -p lib && printf 'void f() { /* see Issue #123 */ }\n' > lib/a.dart && git add lib/a.dart && git commit -m x"
# ⚠ 차단된 커밋의 파일은 인덱스에 남는다 — 다음 케이스가 그걸 물려받으면 무엇을 검증하는지
# 알 수 없게 된다. 케이스마다 인덱스를 비운다.
git reset -q >/dev/null 2>&1; rm -f lib/a.dart
expect_commit "로컬 확장에 안 걸리는 변경은 통과" allow \
  "printf 'more\n' >> README.md && git add README.md && git commit -m x"
git reset -q >/dev/null 2>&1
# status 판정은 양쪽으로 틀릴 수 있다. init 이 쓰는 형태(--- 없는 헤더)는 인정해야 하고,
# 산문 속 언급은 인정하면 안 된다 — 전자를 놓치면 모든 기존 레포의 confirmed 규칙이 조용히
# 죽고, 후자를 잡으면 draft 규칙이 멋대로 차단을 시작한다.
printf -- '---\nstatus: confirmed\n---\n# Rule\n' > .claude/guild/gates/rules/test-naming.md
git reset -q >/dev/null 2>&1; rm -f lib/*.dart
expect_commit "frontmatter 형태의 confirmed 인정" block \
  "mkdir -p lib && printf 'void h() { /* Issue #7 */ }\n' > lib/c.dart && git add lib/c.dart && git commit -m x"
git reset -q >/dev/null 2>&1; rm -f lib/*.dart
printf '# Rule\nstatus: draft\n\n이 문서는 `status: confirmed` 가 되면 차단으로 승격된다.\n' > .claude/guild/gates/rules/test-naming.md
expect_commit "산문 속 status: confirmed 언급은 무시" allow \
  "mkdir -p lib && printf 'void i() { /* Issue #8 */ }\n' > lib/d.dart && git add lib/d.dart && git commit -m x"
# draft 로 내리면 경고만 (INV6)
git reset -q >/dev/null 2>&1; rm -f lib/*.dart
printf '# Rule\nstatus: draft\n' > .claude/guild/gates/rules/test-naming.md
expect_commit "규칙이 draft 면 통과 (경고만)" allow \
  "mkdir -p lib && printf 'void g() { /* see Issue #99 */ }\n' > lib/b.dart && git add lib/b.dart && git commit -m x"
# 깨진 확장은 게이트를 막지 않아야 한다 (fail-open)
fresh_repo
mkdir -p .claude/guild/gates/scripts/local
printf 'this is not valid python(\n' > .claude/guild/gates/scripts/local/broken.py
expect_commit "깨진 로컬 확장이 커밋을 막지 않음" allow \
  "printf 'x\n' >> README.md && git add README.md && git commit -m x"

note ""
note "== H. 기존 훅 체이닝 =="
fresh_repo
printf '#!/bin/sh\necho local-hook-ran >&2\nexit 0\n' > .git/hooks/pre-commit.local
chmod +x .git/hooks/pre-commit.local
expect_commit "기존 훅 통과 시 커밋 진행" allow \
  "printf 'more\n' >> README.md && git add README.md && git commit -m x"
fresh_repo
printf '#!/bin/sh\nexit 1\n' > .git/hooks/pre-commit.local
chmod +x .git/hooks/pre-commit.local
expect_commit "기존 훅 실패 시 커밋 중단" block \
  "printf 'more\n' >> README.md && git add README.md && git commit -m x"

note ""
note "결과: PASS=$PASS FAIL=$FAIL"
cd /; rm -rf "$WORK"
[ "$FAIL" -eq 0 ]
