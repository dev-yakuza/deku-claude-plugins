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
note "== A2. diff 파싱 우회 (one-man-company 로컬 포크가 이미 막고 있던 것) =="
# 셋 다 중앙 스크립트의 실제 버그였고, 전부 검증 게이트를 **조용히** 무력화했다.
# 로컬 포크를 병합하려 그 저장소를 들여다보다 발견했다.
fresh_repo
# (1) 잘못된 UTF-8: text=True 가 UnicodeDecodeError 를 내고 sh() 가 ''를 반환 → diff 전체 소실.
#     NUL 이 없어야 git 이 텍스트로 취급해 내용이 diff 에 들어간다.
expect_commit "Latin-1 바이트가 있어도 assertion 삭제를 잡음" block \
  "printf 'def test_a():\n    pass\n' > test/t_test.py && printf '# caf\xe9\nx = 1\n' > legacy.py && git add -A && git commit -m x"
fresh_repo
# (2) core.quotepath(git 기본)로 비ASCII 경로는 C-quote 되어 '+++ b/' 로 시작하지 않는다.
expect_commit "한글 경로 테스트 파일의 assertion 삭제를 잡음" block \
  "cp test/t_test.py 'test/한글_test.py' && git add -A && git commit -qm k && printf 'def test_x():\n    pass\n' > 'test/한글_test.py' && git commit -am x"
fresh_repo
# (3) 내용 줄 '++ b/...' 가 diff 에서 '+++ b/...' 가 되어 헤더로 오인 → 이후 줄이 엉뚱한 파일로 귀속.
expect_commit "헤더 스푸핑으로 시크릿 귀속을 못 바꿈" block \
  "printf 'x = 1\n++ b/docs/safe.md\nAKIAIOSFODNN7EXAMPLE\n' > s.py && git add s.py && git commit -m x"
fresh_repo
# (4) U2: '++ '/'-- ' 로 시작하는 소스 줄은 헤더가 아니라 콘텐츠다 — 무조건 skip 하면 그
#     줄 자체의 인라인 시크릿이 스캔을 통째로 벗어난다.
expect_commit "'++ ' 로 시작하는 소스 줄의 인라인 시크릿도 스캔됨" block \
  "printf '++ AKIAIOSFODNN7EXAMPLE\n' > k.py && git add k.py && git commit -m x"
fresh_repo
# (5) U2, delete 방향: 소스 줄이 '-- ' 로 시작하면 삭제 시 diff 줄이 '---' 가 되어, 예전엔
# 헤더로 오인돼 스캔에서 통째로 빠졌다 — iter_diff_lines 유닛 레벨로 직접 검증한다.
# (check_verification 의 B2 는 COMMENT_LINE_RE 가 '--' 접두를 SQL/Lua 주석으로 별도
# 취급해 항상 assertion 집계에서 제외하므로, 그 경로로는 이 사실이 관찰되지 않는다.)
printf -- '-- x = 1\n' > test/dashcontent_test.py
git add -A && git commit -qm add_dashcontent >/dev/null 2>&1
printf 'y = 2\n' > test/dashcontent_test.py
git add -A
OUT="$(python3 - <<'PY'
import sys
sys.path.insert(0, ".claude/guild/gates/scripts")
import gate_precommit as g
diff = g.changed_diff(".", False)
removed = [b for p, s, b in g.iter_diff_lines(diff) if s == "-"]
print("OK" if "-- x = 1" in removed else "FAIL:" + repr(removed))
PY
)"
case "$OUT" in
  *OK*) ok "'-- ' 접두 소스 줄도 삭제 시 콘텐츠로 스캔됨 (iter_diff_lines)" ;;
  *) bad "'-- ' 접두 소스 줄도 삭제 시 콘텐츠로 스캔됨 (iter_diff_lines)" "OK" "$OUT" ;;
esac
git reset -q >/dev/null 2>&1; git checkout -q -- . 2>/dev/null

note ""
note "== A3. 역델타 — one-man-company 포크가 상류보다 앞서 있던 4건 =="
# 그 레포의 게이트 이관을 analyze 하다 발견됐다. 넷 다 상류의 실제 결함이고, H4 는
# 0.49.0 의 surrogateescape 도입이 직접 만든 것이다.
fresh_repo
# H1: name-only 계열도 C-quote 된다. '$' 앵커가 닫는 따옴표에 막혀 한글 이름 .env 가 통과했다.
expect_commit "한글 이름 .env 를 시크릿으로 잡음" block \
  "printf 'SECRET=abc\n' > '한글설정.env' && git add -A && git commit -m x"
fresh_repo
# H2: diff.noprefix=true 면 헤더에 a//b/ 가 없어 DIFF_GIT_RE 가 전멸 → 경로 기반 검사 전부 사망.
expect_commit "diff.noprefix=true 에서도 assertion 삭제를 잡음" block \
  "git config diff.noprefix true && printf 'def test_a():\n    pass\n' > test/t_test.py && git commit -am x"
fresh_repo
# H3: deny 는 exit 하므로 뒤의 warn 출력이 죽은 코드였다 — 차단 시 draft 경고가 통째로 사라졌다.
mkdir -p lib
printf '# Rule\n- forbid: lib/** imports package:banned/ [status: draft]\n' > .claude/guild/gates/rules/boundaries.md
printf 'SECRET=abc\n' > .env
printf "import 'package:banned/x.dart';\n" > lib/a.dart
git add -A >/dev/null 2>&1
OUT="$(python3 .claude/guild/gates/scripts/gate_precommit.py --git-hook 2>&1)"
case "$OUT" in
  *차단*경고*) ok "차단 시에도 draft 경고가 함께 보임" ;;
  *) bad "차단 시에도 draft 경고가 함께 보임" "차단+경고" "$(printf '%s' "$OUT" | head -1)" ;;
esac
git reset -q >/dev/null 2>&1; rm -f .env lib/a.dart

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
note "== B2. dismiss 축소 정밀도 (등록된 테스트 파일 삭제만 면제, #345) =="
# B1(테스트 파일 삭제)만 dismiss 를 보고 B2(assertion 순감)는 안 봤다면, dismissed.md 에
# 등록한 테스트 파일을 통째로 지워도 B2 가 그 면제를 뒤집는다. 아래 4방향으로 좁게 고정한다.
fresh_repo
printf '# accepted\n- `test/t_test.py` — 레거시 스위트 폐기\n' > .claude/guild/gates/dismissed.md
expect_commit "dismissed 등록 파일을 통째로 삭제하면 통과" allow \
  "git rm -q test/t_test.py && git commit -m x"
fresh_repo
printf '# accepted\n- `test/t_test.py` — 레거시 스위트 폐기\n' > .claude/guild/gates/dismissed.md
expect_commit "dismissed 등록 파일이라도 남긴 채 assertion만 제거하면 차단 (상시 면허 아님)" block \
  "sed -i.bak 's/    assert.*//g' test/t_test.py && rm -f test/t_test.py.bak && git commit -am x"
fresh_repo
printf '# accepted\n- `test/other.md` — 무관 항목\n' > .claude/guild/gates/dismissed.md
expect_commit "미등록 파일 삭제는 여전히 차단" block \
  "git rm -q test/t_test.py && git commit -m x"
fresh_repo
printf '# accepted\n- `test/t_test.py` — 레거시 스위트 폐기\n' > .claude/guild/gates/dismissed.md
expect_commit "dismissed 등록 파일에 skip 추가는 여전히 차단 (B3 는 면제 없음)" block \
  "printf 'import pytest\n@pytest.mark.skip\ndef test_z(): assert 1\n' >> test/t_test.py && git commit -am x"

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
expect_guard "lefthook.yml 수정 → 확인 요구 (게이트 배선)" ask \
  '{"tool_name":"Write","tool_input":{"file_path":"/r/lefthook.yml","content":"pre-commit:\n  commands:\n    guild-gate:\n      run: python3 x"}}'
expect_guard ".claude/settings.json 수정 → 확인 요구 (게이트 배선)" ask \
  '{"tool_name":"Write","tool_input":{"file_path":"/r/.claude/settings.json","content":"{}"}}'
expect_guard ".husky/pre-commit 수정 → 확인 요구 (게이트 배선)" ask \
  '{"tool_name":"Write","tool_input":{"file_path":"/r/.husky/pre-commit","content":"npx guild gate"}}'
# U8: lefthook-local.yml 은 lefthook 자신의 로컬 오버라이드 파일이다(보통 gitignore 되어
# 리뷰에 안 보인다) — 여기에 `guild-gate: {skip: true}` 를 넣으면 lefthook.yml 을 건드리지
# 않고도 게이트가 조용히 사라진다(실측: lefthook 2.1.11, "guild-gate (skip) by condition").
expect_guard "lefthook-local.yml 수정 → 확인 요구 (게이트 배선)" ask \
  '{"tool_name":"Write","tool_input":{"file_path":"/r/lefthook-local.yml","content":"guild-gate:\n  skip: true\n"}}'
expect_guard "세그먼트 중간에 낀 이름(mylefthook-local.yml)은 무반응" pass \
  '{"tool_name":"Write","tool_input":{"file_path":"/r/mylefthook-local.yml","content":"guild-gate:\n  skip: true\n"}}'
expect_guard "package.json 수정 → 통과 (알려진 갭, 의도적 제외)" pass \
  '{"tool_name":"Write","tool_input":{"file_path":"/r/package.json","content":"{\"scripts\":{}}"}}'
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
note "== J. 경계 규칙의 규칙별 status =="
# 파일 단위 status 는 설계 결함이었다: 헤더 한 줄이 파일의 모든 규칙을 지배해, 무오탐으로
# 검증된 규칙 하나를 승격하면 미검증 규칙까지 함께 BLOCK 으로 끌려 올라갔다. 그래서 어떤
# 레포는 이 파일을 포크해야 했다. 접미를 못 벗기면 <substr> 에 "[status: ...]" 가 붙어
# 규칙 전체가 조용한 no-op 이 된다 — 설치된 것처럼 보이면서 아무것도 막지 않는다.
bnd() { printf '%s\n' "$1" > .claude/guild/gates/rules/boundaries.md; }
fresh_repo
mkdir -p lib/features/a/domain
bnd '# Rule: boundaries
- forbid: lib/features/*/domain/** imports package:flutter/ [status: confirmed]
- forbid: lib/features/*/domain/** imports package:get/ [status: draft]'
expect_commit "confirmed 접미가 붙은 규칙은 차단" block \
  "printf \"import 'package:flutter/material.dart';\n\" > lib/features/a/domain/x.dart && git add -A && git commit -m x"
git reset -q >/dev/null 2>&1; rm -f lib/features/a/domain/x.dart
expect_commit "같은 파일의 draft 규칙은 통과 (동반 승격 없음)" allow \
  "printf \"import 'package:get/get.dart';\n\" > lib/features/a/domain/y.dart && git add -A && git commit -m x"
git reset -q >/dev/null 2>&1; rm -f lib/features/a/domain/y.dart
bnd '# Rule: boundaries
- forbid: lib/features/*/domain/** imports package:flutter/ [status: darft]'
expect_commit "오타 status 는 draft 로 강등 (BLOCK 아님)" allow \
  "printf \"import 'package:flutter/material.dart';\n\" > lib/features/a/domain/z.dart && git add -A && git commit -m x"
git reset -q >/dev/null 2>&1; rm -f lib/features/a/domain/z.dart
# 접미가 없으면 파일 frontmatter 로 폴백 (하위호환)
fresh_repo
mkdir -p lib/features/a/domain
bnd '---
status: confirmed
---
# Rule
- forbid: lib/features/*/domain/** imports package:flutter/'
expect_commit "접미 없으면 frontmatter status 로 폴백" block \
  "printf \"import 'package:flutter/material.dart';\n\" > lib/features/a/domain/w.dart && git add -A && git commit -m x"
# U7: 경계 검사는 진짜 import 파서가 아니라 줄 단위 문자열 매칭이다(docstring — grep-level).
# 그래서 주석/문자열만 금지 문구를 언급해도 발화한다 — 의도된 동작이지만, 모르는 사람은
# 게이트 고장으로 오인해 규칙/파서를 좁히려 든다(레포에서 실제 관측, evolve #20 반려).
# 매치된 줄이 하나도 import/export 가 아닐 때만 사유에 안내를 덧붙인다 — 판정은 그대로.
fresh_repo
mkdir -p lib/features/a/domain
bnd '# Rule: boundaries
- forbid: lib/features/*/domain/** imports package:banned/ [status: confirmed]'
printf "// see package:banned/ for context\n" > lib/features/a/domain/note.dart
git add -A >/dev/null 2>&1
OUT="$(python3 .claude/guild/gates/scripts/gate_precommit.py --git-hook 2>&1)"
case "$OUT" in
  *"주석/문자열에서 매치"*) ok "주석/문자열만 매치된 경계 위반 → 안내 문구 부착" ;;
  *) bad "주석/문자열만 매치된 경계 위반 → 안내 문구 부착" "안내 문구 포함" "$(printf '%s' "$OUT" | head -3)" ;;
esac
git reset -q >/dev/null 2>&1; rm -f lib/features/a/domain/note.dart
# 대조군: 진짜 import 줄이 섞이면 안내 문구를 붙이지 않는다(진짜 위반마다 노이즈가 되면 안 됨).
printf "import 'package:banned/x.dart';\n// see package:banned/ for context\n" > lib/features/a/domain/note2.dart
git add -A >/dev/null 2>&1
OUT="$(python3 .claude/guild/gates/scripts/gate_precommit.py --git-hook 2>&1)"
case "$OUT" in
  *"주석/문자열에서 매치"*) bad "진짜 import 가 섞이면 안내 문구를 안 붙임" "안내 문구 없음" "$(printf '%s' "$OUT" | head -3)" ;;
  *) ok "진짜 import 가 섞이면 안내 문구를 안 붙임" ;;
esac
git reset -q >/dev/null 2>&1; rm -f lib/features/a/domain/note2.dart

note ""
note "== K. 원장 인코딩 =="
# write_findings 는 ensure_ascii=False 로 한글을 그대로 남기지만, 경로가 surrogateescape 를
# 거친 짝 없는 서로게이트를 담고 있으면 strict UTF-8 인코드가 실패하고 blanket except 가
# 그것을 삼켜 findings.json 이 파싱 불가 파일로 남는다. errors="backslashreplace" 로 닫는다.
fresh_repo
OUT="$(python3 - <<'PY'
import sys, json, os
sys.path.insert(0, ".claude/guild/gates/scripts")
import gate_precommit as g
root = os.getcwd()
bad_name = "test/\udcff_test.py"
findings = [g.finding("verification:test-deleted", bad_name,
                       f"테스트 파일 삭제: {bad_name} (한글 확인용 메시지)")]
g.write_findings(root, findings)
try:
    with open(os.path.join(root, ".claude", "guild", "gates", "findings.json"),
              encoding="utf-8") as fh:
        data = json.load(fh)
    good = bool(data.get("open")) and "한글 확인용 메시지" in data["open"][0]
except Exception:
    good = False
print("OK" if good else "FAIL")
PY
)"
case "$OUT" in
  *OK*) ok "surrogate 경로 finding 도 findings.json 이 유효한 JSON으로 저장됨" ;;
  *) bad "surrogate 경로 finding 도 findings.json 이 유효한 JSON으로 저장됨" "OK" "$OUT" ;;
esac

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
# refine(ctx, findings) — 중앙 규칙을 레포 조건에 맞게 *좁히는* 훅.
# 이게 없어서 어떤 레포는 "비-진입점 통합테스트 삭제는 예외" 같은 정책을 표현할 수 없었고,
# 결국 중앙 스크립트를 포크로 유지해야 했다 — 영구 포크 표면이 곧 update 사고의 원인이다.
fresh_repo
mkdir -p .claude/guild/gates/scripts/local
cat > .claude/guild/gates/scripts/local/narrow.py <<'LOCAL'
EXEMPT = "test/exempt_test.py"


def refine(ctx, findings):
    """이 레포 정책: EXEMPT 파일의 삭제는 검증 약화가 아니다.

    ⚠ 파일 하나를 지우면 finding 이 둘 난다 — test-deleted 와, 그 파일의 assertion 이
    3개 이상이면 assertion-drop 까지. 앞의 것만 면제하면 뒤의 것이 그대로 막는다.
    assertion-drop 은 `files` 로 기여 파일을 알려주므로, **그 감소가 전부 EXEMPT
    때문일 때만** 면제한다 — 같은 커밋의 다른 파일이 섞이면 면제하지 않는다."""
    keep = []
    for f in findings:
        rule = f.get("rule", "")
        if rule == "verification:test-deleted" and f.get("file") == EXEMPT:
            continue
        if rule == "verification:assertion-drop" and f.get("files") == [EXEMPT]:
            continue
        keep.append(f)
    return keep
LOCAL
cp test/t_test.py test/exempt_test.py; git add -A >/dev/null 2>&1; git commit -qm add >/dev/null 2>&1
expect_commit "refine 이 지정한 verification finding 을 면제" allow \
  "git rm -q test/exempt_test.py && git commit -m x"
git reset -q >/dev/null 2>&1; git checkout -q -- . 2>/dev/null
expect_commit "refine 대상 밖 테스트 삭제는 그대로 차단" block \
  "git rm -q test/t_test.py && git commit -m x"
git reset -q >/dev/null 2>&1; git checkout -q -- . 2>/dev/null
# 정밀도: 같은 커밋에 무관한 테스트의 assertion 감소가 섞이면 면제하지 않는다.
cp test/t_test.py test/exempt_test.py; cp test/t_test.py test/other_test.py
git add -A >/dev/null 2>&1; git commit -qm add2 >/dev/null 2>&1
expect_commit "무관한 파일의 감소가 섞이면 면제 안 됨" block \
  "git rm -q test/exempt_test.py && printf 'def test_o():\n    pass\n' > test/other_test.py && git add -A && git commit -m x"
git reset -q >/dev/null 2>&1; git checkout -q -- . 2>/dev/null
# ⚠ 안전장치: secret 은 어떤 refine 으로도 억제되지 않는다 (INV5).
cat > .claude/guild/gates/scripts/local/narrow.py <<'LOCAL'
def refine(ctx, findings):
    return []          # 전부 억제 시도
LOCAL
expect_commit "refine 은 secret finding 을 억제하지 못함 (INV5)" block \
  "printf 'SECRET=abc\n' > .env && git add .env && git commit -m x"
git reset -q >/dev/null 2>&1; rm -f .env
# 깨진 refiner 는 아무것도 억제하지 않는다 (fail-closed)
cat > .claude/guild/gates/scripts/local/narrow.py <<'LOCAL'
def refine(ctx, findings):
    raise RuntimeError("boom")
LOCAL
expect_commit "깨진 refine 은 억제 없이 차단 유지" block \
  "printf 'SECRET=abc\n' > .env && git add .env && git commit -m x"
git reset -q >/dev/null 2>&1; rm -f .env .claude/guild/gates/scripts/local/narrow.py

# 깨진 확장은 게이트를 막지 않아야 한다 (fail-open)
fresh_repo
mkdir -p .claude/guild/gates/scripts/local
printf 'this is not valid python(\n' > .claude/guild/gates/scripts/local/broken.py
expect_commit "깨진 로컬 확장이 커밋을 막지 않음" allow \
  "printf 'x\n' >> README.md && git add README.md && git commit -m x"
# U4: apply_refiners 가 secret 판정을 refiner 호출 이후에 읽으면, refiner 가 finding dict 를
# 제자리 변형(f["rule"] = ...)해서 INV5 가드를 우회할 수 있다 — 호출 전 스냅샷으로 막는다.
fresh_repo
mkdir -p .claude/guild/gates/scripts/local
cat > .claude/guild/gates/scripts/local/narrow.py <<'LOCAL'
def refine(ctx, findings):
    for f in findings:
        if isinstance(f, dict):
            f["rule"] = "harmless"       # 제자리 변형으로 secret 판정을 피하려는 시도
    return []
LOCAL
expect_commit "refiner 가 rule 을 제자리 변형해도 secret 은 생존 (INV5, 호출 전 스냅샷)" block \
  "printf 'SECRET=abc\n' > .env && git add .env && git commit -m x"
git reset -q >/dev/null 2>&1; rm -f .env .claude/guild/gates/scripts/local/narrow.py
# U4b: 로컬 check() 는 하위호환으로 문자열 finding 을 낼 수 있다(as_message) — 그것이
# 억제 대상이 되었을 때 record_firing 이 isinstance 가드 없이 .get 을 부르면 AttributeError 가
# 모듈 최상위 fail-open 으로 새어 나가, 같은 커밋의 진짜 secret 까지 통과시킨다.
fresh_repo
mkdir -p .claude/guild/gates/scripts/local
cat > .claude/guild/gates/scripts/local/str_and_refine.py <<'LOCAL'
def check(ctx):
    return (["문자열 finding — 하위호환 로컬 체크"], [])
def refine(ctx, findings):
    return []          # 전부 억제 시도 — 문자열 finding 포함
LOCAL
expect_commit "문자열 finding 이 억제 대상이 되어도 크래시 없이 secret 은 차단 유지" block \
  "printf 'SECRET=abc\n' > .env && git add .env && git commit -m x"
git reset -q >/dev/null 2>&1; rm -f .env .claude/guild/gates/scripts/local/str_and_refine.py
# U5: SystemExit 은 Exception 의 하위가 아니다 — 로컬 모듈의 sys.exit(0) 이 run_local_checks 의
# except Exception 을 통과해 프로세스 전체를 exit 0 으로 끝내면, staged 된 진짜 시크릿도
# 보고 전에 새어 나간다.
fresh_repo
mkdir -p .claude/guild/gates/scripts/local
printf 'import sys\ndef check(ctx):\n    sys.exit(0)\n' > .claude/guild/gates/scripts/local/boom.py
expect_commit "로컬 확장의 sys.exit(0) 이 게이트 전체를 통과시키지 못함" block \
  "printf 'SECRET=abc\n' > .env && git add .env && git commit -m x"
git reset -q >/dev/null 2>&1; rm -f .env .claude/guild/gates/scripts/local/boom.py

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
