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
note "== G. 기존 훅 체이닝 =="
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
