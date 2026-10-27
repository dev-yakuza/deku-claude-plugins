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
# 파이프 입력은 `--stdin` 을 명시해야 한다 — 인자 없는 `--scan-paths` 는 git 추적 목록을 스스로
# 읽고, `--scan-text` 는 파일 경로를 받는다(Bash 도구는 stdin 을 /dev/null 로 붙여 문서대로
# 호출하면 빈 입력 = "clean" 이 되던 결함). $2 는 공백으로 나뉜 여러 인자일 수 있다.
expect_scan() { # $1=label $2=mode-args $3=expected-exit $4=stdin $5=expected-substring(또는 "")
  local out rc
  # shellcheck disable=SC2086
  out="$(printf '%s' "$4" | python3 .claude/guild/gates/scripts/gate_precommit.py $2 2>&1)"; rc=$?
  if [ "$rc" != "$3" ]; then bad "$1" "exit $3" "exit $rc"; return; fi
  if [ -n "$5" ]; then
    case "$out" in *"$5"*) ok "$1" ;; *) bad "$1" "$5" "$(printf '%s' "$out" | tr '\n' ' ')" ;; esac
  else
    ok "$1"
  fi
}
fresh_repo
expect_scan "--scan-paths --stdin 가 실제 시크릿 경로를 잡음" "--scan-paths --stdin" 1 \
  '.env
lib/main.dart
id_rsa
' "SECRET-PATH id_rsa"
expect_scan "--scan-paths --stdin 가 허용 목록을 존중 (.env.example)" "--scan-paths --stdin" 0 \
  '.env.example
google-services.json
lib/main.dart
' ""
expect_scan "--scan-text 가 줄번호만 보고 (값 미출력)" "--scan-text --stdin" 1 \
  'ordinary
KEY = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAA"
' "SECRET-TEXT 2"
expect_scan "--scan-text 깨끗한 본문은 통과" "--scan-text --stdin" 0 \
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
expect_scan "--scan-paths --stdin 가 백틱 표기 dismissed 를 존중" "--scan-paths --stdin" 0 \
  'env/koreanwords/ios/distribution.p12
lib/main.dart
' ""
# 괄호 부연이 붙은 형태 (실제 레포에서 관측된 형태)
printf '# accepted\n- `env` (`distribution.p12` 등) — 사유\n' > .claude/guild/gates/dismissed.md
expect_scan "--scan-paths --stdin 가 괄호 부연이 붙어도 경로만 추출" "--scan-paths --stdin" 0 \
  'env/koreanwords/ios/distribution.p12
' ""
printf '# accepted\n- env — flavor별 배포 인증서 (비공개 레포 정책)\n' > .claude/guild/gates/dismissed.md
expect_scan "--scan-paths --stdin 가 백틱 없는 표기도 존중" "--scan-paths --stdin" 0 \
  'env/koreanwords/ios/distribution.p12
lib/main.dart
' ""
expect_scan "dismissed 밖의 시크릿은 계속 잡음" "--scan-paths --stdin" 1 \
  'env/koreanwords/ios/distribution.p12
.env
' "SECRET-PATH .env"
printf '' > .claude/guild/gates/dismissed.md

# 값이 새어나가지 않는지 명시적으로 확인 (INV5)
# exit 1 도 함께 단언한다 — 출력이 비어 있으면(스캔이 아예 안 돈 경우) 값도 당연히 없어서
# 값 미출력 검사만으로는 "아무것도 안 함" 을 통과시킨다.
LEAK="$(printf 'K="sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAA"\n' | python3 .claude/guild/gates/scripts/gate_precommit.py --scan-text --stdin 2>&1)"; LRC=$?
case "$LRC:$LEAK" in
  1:*sk-ant*) bad "스캔 출력에 시크릿 값이 없음" "no value" "value leaked" ;;
  1:*SECRET-TEXT*) ok "스캔 출력에 시크릿 값이 없음 (INV5)" ;;
  *) bad "스캔이 실제로 검출하고 값은 숨김" "exit 1 + SECRET-TEXT" "exit $LRC: $LEAK" ;;
esac

note ""
note "== G2. 스캔 입력은 인자로 — 빈 입력은 clean 이 아니다 =="
G="python3 .claude/guild/gates/scripts/gate_precommit.py"
fresh_repo
# 인자 없는 --scan-paths 는 git 추적 파일을 스스로 읽는다
printf 'k\n' > id_rsa; git add id_rsa >/dev/null 2>&1
OUT="$($G --scan-paths </dev/null 2>&1)"; RC=$?
[ "$RC" = 1 ] && case "$OUT" in *"SECRET-PATH id_rsa"*) true ;; *) false ;; esac \
  && ok "--scan-paths 가 추적 목록을 직접 읽어 시크릿 경로를 잡음" || bad "--scan-paths git 모드" "exit 1 + id_rsa" "exit $RC: $OUT"
git rm -q --cached id_rsa >/dev/null 2>&1; rm -f id_rsa
$G --scan-paths </dev/null >/dev/null 2>&1; RC=$?
[ "$RC" = 0 ] && ok "--scan-paths git 모드, 깨끗한 저장소 → 0" || bad "--scan-paths 깨끗한 저장소" "0" "$RC"
# git 저장소 밖 → 판정 불가(2). 예전처럼 "추적 파일 없음 = clean" 으로 읽히면 안 된다.
NG="$WORK/nogit"; mkdir -p "$NG"
( cd "$NG" && python3 "$WORK/r/.claude/guild/gates/scripts/gate_precommit.py" --scan-paths </dev/null >/dev/null 2>&1 ); RC=$?
[ "$RC" = 2 ] && ok "--scan-paths git 저장소 밖 → 2 (판정 불가)" || bad "--scan-paths 저장소 밖" "2" "$RC"
# 빈 stdin → 64 (Bash 도구의 /dev/null stdin 이 바로 이 경우)
for m in "--scan-paths --stdin" "--scan-text --stdin" "--scan-text"; do
  # shellcheck disable=SC2086
  $G $m </dev/null >/dev/null 2>&1; RC=$?
  [ "$RC" = 64 ] && ok "$m 에 입력 없음 → 64" || bad "$m 빈 입력" "64" "$RC"
done
# 파일 인자
printf 'ordinary\nKEY = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAA"\n' > "$WORK/body.txt"
OUT="$($G --scan-text "$WORK/body.txt" </dev/null 2>&1)"; RC=$?
[ "$RC" = 1 ] && [ "$OUT" = "SECRET-TEXT 2" ] && ok "--scan-text <file> 가 줄번호를 보고" || bad "--scan-text <file>" "1 / SECRET-TEXT 2" "$RC / $OUT"
: > "$WORK/empty.txt"
$G --scan-text "$WORK/empty.txt" </dev/null >/dev/null 2>&1; RC=$?
[ "$RC" = 0 ] && ok "--scan-text 빈 파일은 정당하게 clean(0)" || bad "--scan-text 빈 파일" "0" "$RC"
# 읽을 수 없는 입력 → 2. 디렉터리 경로를 쓴다(권한 기반은 root CI 에서 읽혀 버린다).
for bad_path in "$WORK/does-not-exist" "$WORK"; do
  $G --scan-text "$bad_path" </dev/null >/dev/null 2>&1; RC=$?
  [ "$RC" = 2 ] && ok "--scan-text 읽을 수 없는 경로 → 2 ($(basename "$bad_path"))" || bad "--scan-text 읽기 실패" "2" "$RC"
done
# 레거시 인코딩(Latin-1) 본문은 크래시(→ 판정 불가) 없이 스캔된다
printf '# caf\351\nKEY = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAA"\n' > "$WORK/latin1.txt"
OUT="$($G --scan-text "$WORK/latin1.txt" </dev/null 2>&1)"; RC=$?
[ "$RC" = 1 ] && ok "--scan-text Latin-1 파일도 판정 (1)" || bad "--scan-text Latin-1" "1" "$RC: $OUT"
printf 'caf\351\nplain\n' | $G --scan-text --stdin >/dev/null 2>&1; RC=$?
[ "$RC" = 0 ] && ok "--scan-text --stdin Latin-1 입력도 판정 (0)" || bad "--scan-text --stdin Latin-1" "0" "$RC"
# 비 UTF-8 시크릿 경로명 — 파일을 만들지 않고 인덱스에 주입한다(APFS 는 비 UTF-8 파일명 생성을
# 거부). 출력은 strict stdout 에서 크래시하지 않아야 한다: Python ≤3.14 는 UTF-8 로캘 + UTF-8
# mode 꺼짐에서 stdout 이 strict 다. C 로캘은 PEP 538/540 으로 surrogateescape 가 되어 수정 전
# 코드도 통과하므로 UTF-8 로캘을 고정하고, 그래도 strict 가 아니면 SKIP 으로 표시한다.
BLOB="$(printf 'k' | git hash-object -w --stdin)"
printf '100644 %s\tcl\351.pem\0' "$BLOB" | git update-index -z --index-info
U8="en_US.UTF-8"; [ "$(uname)" = Linux ] && U8="C.UTF-8"
STRICT="$(LC_ALL=$U8 PYTHONUTF8=0 python3 -c 'import sys; print(sys.stdout.errors)' 2>/dev/null)"
OUT="$(LC_ALL=$U8 PYTHONUTF8=0 $G --scan-paths </dev/null 2>&1)"; RC=$?
if [ "$RC" = 1 ] && case "$OUT" in *"SECRET-PATH cl"*".pem"*) true ;; *) false ;; esac; then
  if [ "$STRICT" = strict ]; then ok "비 UTF-8 시크릿 경로명 → 1 + SECRET-PATH (strict stdout)"
  else ok "비 UTF-8 시크릿 경로명 → 1 + SECRET-PATH (SKIP: 이 인터프리터의 stdout 은 $STRICT — strict 경로 미검증)"; fi
else
  bad "비 UTF-8 시크릿 경로명" "exit 1 + SECRET-PATH" "exit $RC: $OUT"
fi
git rm -q --cached -- "$(printf 'cl\351.pem')" >/dev/null 2>&1

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
note "== V. 시각 기준 이미지 (golden / VRT) — 경고만, 차단 없음 =="
# 시각 테스트의 assertion 은 코드 줄이 아니라 기준 이미지다. `--update-goldens` / `vitest -u`
# 는 기대값 자체를 다시 쓰므로 B1~B3 어느 것도 반응하지 않는다. 정상적인 UI 변경도 매번
# 기준 이미지를 바꾸므로 차단은 틀리고, 경고 + PR 공개가 맞다(INV1 — 사람이 PR 에서 본다).
# 설정(visual.baselines)이 없으면 아무 것도 하지 않는다 — 추측한 glob 이 일반 에셋에 걸리면
# 아이콘 하나 바꿀 때마다 경고가 나고, 사람은 경고를 읽지 않게 된다.
visual_repo() {
  fresh_repo
  printf '{"gates":{"enabled":true},"visual":{"baselines":["**/__screenshots__/**","test/goldens/**"]}}' > .claude/guild/config.json
  mkdir -p src/a/__screenshots__ __screenshots__ test/goldens assets
  printf 'PNG1' > src/a/__screenshots__/btn.png
  printf 'PNG1' > __screenshots__/root.png
  printf 'PNG1' > test/goldens/card.png
  printf 'PNG1' > assets/icon.png
  git add -A >/dev/null 2>&1
  git -c core.hooksPath=/dev/null commit -qm baselines >/dev/null 2>&1
}
# $1=label $2=want rc(allow|block) $3=grep pattern that MUST appear ('' = none) $4=pattern that must NOT appear $5..=cmd
expect_visual() {
  local label="$1" want="$2" must="$3" mustnot="$4"; shift 4
  local out; out="$(bash -c "$*" 2>&1)"; local rc=$?
  local got="allow"; [ $rc -ne 0 ] && got="block"
  if [ "$got" != "$want" ]; then bad "$label" "$want" "$got"; return; fi
  if [ -n "$must" ] && ! printf '%s' "$out" | grep -qF -- "$must"; then bad "$label" "output has '$must'" "absent"; return; fi
  if [ -n "$mustnot" ] && printf '%s' "$out" | grep -qF -- "$mustnot"; then bad "$label" "output lacks '$mustnot'" "present"; return; fi
  ok "$label"
}
visual_repo
expect_visual "V1 기준 이미지 갱신 → 통과 + 시각 경고" allow "시각 기준 이미지 갱신 1건: src/a/__screenshots__/btn.png" "draft 규칙" \
  "printf 'PNG2' > src/a/__screenshots__/btn.png && git commit -qam x"
visual_repo
expect_visual "V2 루트의 __screenshots__ 도 **/ 앞부분 없이 매치" allow "__screenshots__/root.png" "" \
  "printf 'PNG2' > __screenshots__/root.png && git commit -qam x"
visual_repo
expect_visual "V3 테스트 경로 밖 기준 이미지 삭제 → 통과 + 삭제 경고" allow "시각 기준 이미지 삭제 1건" "" \
  "git rm -q src/a/__screenshots__/btn.png && git commit -qm x"
visual_repo
# ⚠ 예전엔 "B1 이 이미 막으니 시각 경고는 생략" 이었다 — 로컬 refiner 가 B1 을 억제하면 차단도
# 경고도 없이 통과했다(1회차 리뷰). 이제 경고는 항상 나고, 차단은 B1 그대로다.
expect_visual "V4 test/ 아래 기준 이미지 삭제: B1 차단 + 시각 삭제 경고도 함께" block "시각 기준 이미지 삭제 1건: test/goldens/card.png" "" \
  "git rm -q test/goldens/card.png && git commit -qm x"
visual_repo
expect_visual "V5 glob 밖 이미지(assets/) 변경은 경고 없음" allow "" "시각 기준 이미지" \
  "printf 'PNG2' > assets/icon.png && git commit -qam x"
visual_repo
printf -- '- `src/a/__screenshots__` — 이 컴포넌트는 매 릴리스 갱신\n' > .claude/guild/gates/dismissed.md
expect_visual "V6 dismissed.md 에 등록된 경로는 경고 없음" allow "" "시각 기준 이미지" \
  "printf 'PNG2' > src/a/__screenshots__/btn.png && git commit -qam x"
fresh_repo
mkdir -p src/__screenshots__; printf 'PNG1' > src/__screenshots__/a.png
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm b >/dev/null 2>&1
expect_visual "V7 visual.baselines 설정이 없으면 검사 자체가 없음" allow "" "시각 기준 이미지" \
  "printf 'PNG2' > src/__screenshots__/a.png && git commit -qam x"
visual_repo
for i in 1 2 3 4 5 6 7; do printf 'PNG1' > "src/a/__screenshots__/s$i.png"; done
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm more >/dev/null 2>&1
expect_visual "V8 다수 갱신은 5건만 나열하고 나머지는 개수로" allow "외 3건" "" \
  "for i in 1 2 3 4 5 6 7; do printf 'PNG2' > src/a/__screenshots__/s\$i.png; done; printf 'PNG2' > src/a/__screenshots__/btn.png && git commit -qam x"
visual_repo
expect_visual "V9 차단 메시지에도 시각 경고가 자기 헤더로 접힌다 (draft 헤더 아님)" block "시각 기준 이미지·비교 설정 — 차단 안 함, PR 공개 필요" "draft 규칙" \
  "printf 'PNG2' > src/a/__screenshots__/btn.png && git rm -q test/t_test.py && git commit -qam x"
visual_repo
printf 'PNG2' > src/a/__screenshots__/btn.png
git add -A >/dev/null 2>&1
PRE_OUT="$(printf '{"tool_input":{"command":"git commit -m x"}}' | python3 .claude/guild/gates/scripts/gate_precommit.py 2>&1)"; PRE_RC=$?
if [ $PRE_RC -eq 0 ] && printf '%s' "$PRE_OUT" | grep -qF "시각 기준 이미지 갱신 1건"; then
  ok "V10 PreToolUse 모드: 통과(exit 0) + 시각 경고"
else
  bad "V10 PreToolUse 모드" "exit 0 + warn" "rc=$PRE_RC"
fi
git commit -qm x >/dev/null 2>&1  # git 훅(권위 있는 층)이 기록한다 — V27
if grep -q 'verification:baseline-updated' .claude/guild/memory/gate-firings.jsonl 2>/dev/null; then
  ok "V11 경고가 gate-firings 에 기록된다 (evolve 의 규칙 성적표 입력)"
else
  bad "V11 gate-firings 기록" "verification:baseline-updated" "absent"
fi

# ── 1회차 적대적 리뷰에서 나온 것들 ──
# (V12) 문서 예시 glob `test/**/goldens/**` 가 Flutter 의 가장 흔한 배치 `test/goldens/` 를
#       놓쳤다 — fnmatch 의 중간 `/**/` 는 디렉터리 0개를 매치하지 않는다. git :(glob) 와 같게.
fresh_repo
printf '{"gates":{"enabled":true},"visual":{"baselines":["test/**/goldens/**"]}}' > .claude/guild/config.json
mkdir -p test/goldens; printf 'PNG1' > test/goldens/a.png
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm b >/dev/null 2>&1
expect_visual "V12 중간 **/ 는 디렉터리 0개도 매치 (test/**/goldens/** ⊃ test/goldens/a.png)" allow "시각 기준 이미지 갱신 1건: test/goldens/a.png" "" \
  "printf 'PNG2' > test/goldens/a.png && git commit -qam x"
# (V13) rename: git 이 같은 바이트의 삭제+추가를 R 로 묶어 M/D 필터를 빠져나갔다.
visual_repo
expect_visual "V13 이름 변경(내용 동일)된 기준 이미지도 삭제로 경고" allow "시각 기준 이미지 삭제 1건: src/a/__screenshots__/btn.png" "" \
  "git mv src/a/__screenshots__/btn.png src/a/__screenshots__/btn2.png && git commit -qm x"
visual_repo
expect_visual "V14 glob 밖으로 옮긴 기준 이미지 = 삭제 경고" allow "시각 기준 이미지 삭제 1건" "" \
  "mkdir -p moved && git mv src/a/__screenshots__/btn.png moved/btn.png && git commit -qm x"
# (V15) 비교 설정 완화: 이미지가 그대로여도 '같은 화면' 의 정의가 바뀐다.
visual_repo
printf '{"gates":{"enabled":true},"visual":{"baselines":["**/__screenshots__/**"],"config_files":["vitest.config.ts"]}}' > .claude/guild/config.json
printf 'export default { threshold: 0 }\n' > vitest.config.ts
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm cfg >/dev/null 2>&1
expect_visual "V15 비교 설정 파일 변경 → 통과 + 경고" allow "시각 비교 설정 파일 변경 1건: vitest.config.ts" "draft 규칙" \
  "printf 'export default { threshold: 0.5 }\n' > vitest.config.ts && git commit -qam x"
# (V16) 잘못된 타입의 visual.baselines 가 게이트를 크래시시키고, fail-open 이 시크릿까지 통과시켰다.
for BAD in 'true' '5' '{"a":1}' '"**/__screenshots__/**"'; do
  fresh_repo
  printf '{"gates":{"enabled":true},"visual":{"baselines":%s,"config_files":%s}}' "$BAD" "$BAD" > .claude/guild/config.json
  expect_commit "V16 visual.baselines=$BAD 여도 시크릿 차단은 유지" block \
    "printf 'SECRET=abc\n' > .env && git add .env && git commit -m x"
done
# (V17) visual 설정은 게이트가 무엇을 보고하는지를 정한다 — 비우는 편집은 사람 확인.
fresh_repo
expect_guard "V17 config.json 의 visual.baselines 편집 → 확인 요구" ask \
  '{"tool_name":"Edit","tool_input":{"file_path":"/r/.claude/guild/config.json","new_string":"\"baselines\": []"}}'
# (V18) 다수 갱신이 firing 로그를 파일당 1줄씩 채워 evolve 의 규칙 성적표 이력을 밀어냈다.
visual_repo
for i in $(seq 1 40); do printf 'PNG1' > "src/a/__screenshots__/m$i.png"; done
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm many >/dev/null 2>&1
rm -f .claude/guild/memory/gate-firings.jsonl
bash -c "for i in \$(seq 1 40); do printf 'PNG2' > src/a/__screenshots__/m\$i.png; done; git commit -qam x" >/dev/null 2>&1
FN="$(grep -c 'baseline-updated' .claude/guild/memory/gate-firings.jsonl 2>/dev/null || echo 0)"
if [ "$FN" -eq 1 ]; then ok "V18 갱신 40건이어도 firing 은 종류당 1줄 (실측 $FN)"; else bad "V18 firing 볼륨" "1" "$FN"; fi

# ── 2회차 적대적 리뷰 ──
# (V19) 실제 VRT 테스트 파일명(index.vitest.tsx)은 TEST_PATH_RE 밖이라 삭제·skip 이 B1~B3 를 통과했다.
vt_repo() {
  fresh_repo
  printf '{"gates":{"enabled":true},"visual":{"baselines":["**/__screenshots__/**"],"tests":["**/*.vitest.tsx"],"config_files":["**/flutter_test_config.dart"]}}' > .claude/guild/config.json
  mkdir -p src/btn/__screenshots__
  printf 'PNG1' > src/btn/__screenshots__/a.png
  printf "it('a', async () => {\n  await expect.element(el).toMatchScreenshot('a')\n  await expect.element(el2).toMatchScreenshot('b')\n  await expect.element(el3).toMatchScreenshot('c')\n})\n" > src/btn/index.vitest.tsx
  git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm b >/dev/null 2>&1
}
vt_repo
expect_commit "V19 visual.tests 의 테스트 파일 삭제 → 차단" block "git rm -q src/btn/index.vitest.tsx && git commit -qm x"
vt_repo
expect_commit "V20 visual.tests 의 it.skip 추가 → 차단" block \
  "printf \"it.skip('z', () => {})\n\" >> src/btn/index.vitest.tsx && git commit -qam x"
vt_repo
# (5회차) expect.element( 는 더 이상 B2 의 단언 줄이 아니다 — 시각 단언 삭제는 B4 경고 + 원장 C 행.
expect_visual "V21 toMatchScreenshot 단언 3줄 삭제 → 통과 + 시각 단언 순감소 경고" allow "시각 단언(스크린샷/golden 매처) 순감소 3건" "" \
  "printf \"it('a', async () => {\n})\n\" > src/btn/index.vitest.tsx && git commit -qam x"
fresh_repo
mkdir -p test; printf "void main() {\n  testWidgets('a', (t) async {\n    await expectLater(find.byType(A), matchesGoldenFile('a.png'));\n    await expectLater(find.byType(B), matchesGoldenFile('b.png'));\n    await expectLater(find.byType(C), matchesGoldenFile('c.png'));\n  });\n}\n" > test/a_test.dart
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm b >/dev/null 2>&1
expect_commit "V22 Dart expectLater(matchesGoldenFile) 3줄 삭제 → 차단" block \
  "printf \"void main() {\n  testWidgets('a', (t) async {});\n}\n\" > test/a_test.dart && git commit -qam x"
# (V23) 새 디렉터리별 flutter_test_config.dart (glob) 도 비교 설정이다.
vt_repo
expect_visual "V23 config_files glob(**/flutter_test_config.dart) 의 수정은 경고" allow "시각 비교 설정 파일 변경 1건: test/flutter_test_config.dart" "" \
  "mkdir -p test && printf 'a\n' > test/flutter_test_config.dart && git add -A && git -c core.hooksPath=/dev/null commit -qm c && printf 'b\n' > test/flutter_test_config.dart && git commit -qam x"
# (V24) 문자 클래스와 / 에 붙지 않은 ** — git :(glob) 와 같게.
fresh_repo
printf '{"gates":{"enabled":true},"visual":{"baselines":["shots/*.[pP][nN][gG]","**.jpg"]}}' > .claude/guild/config.json
mkdir -p shots/sub; printf 'P' > 'shots/p(1).png'; printf 'J' > shots/sub/x.jpg; printf 'J' > root.jpg
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm b >/dev/null 2>&1
expect_visual "V24a 문자 클래스 glob 이 매치한다 (shots/*.[pP][nN][gG])" allow "shots/p(1).png" "" \
  "printf 'Q' > 'shots/p(1).png' && git commit -qam x"
expect_visual "V24b / 에 붙지 않은 ** 는 / 를 넘지 않는다 (**.jpg ⊅ shots/sub/x.jpg)" allow "" "시각 기준 이미지" \
  "printf 'K' > shots/sub/x.jpg && git commit -qam x"
# (V25) 타입 변경(T) — 심볼릭 링크로 바꾸기 — 도 갱신이다.
visual_repo
expect_visual "V25 기준 이미지를 심볼릭 링크로 바꿈(T) → 갱신 경고" allow "시각 기준 이미지 갱신 1건" "" \
  "rm src/a/__screenshots__/btn.png && ln -s ../../../README.md src/a/__screenshots__/btn.png && git add -A && git commit -qm x"
# (V26) 자연 정렬 키가 '²' 같은 isdigit-but-not-decimal 문자에서 터지면 그 그룹 경고가 통째로 사라졌다.
visual_repo
printf 'PNG1' > 'src/a/__screenshots__/s1²2.png'; git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm sup >/dev/null 2>&1
expect_visual "V26 '²' 가 섞인 이름도 경고가 사라지지 않는다" allow "시각 기준 이미지 갱신 2건" "" \
  "printf 'PNG2' > 'src/a/__screenshots__/s1²2.png' && printf 'PNG2' > src/a/__screenshots__/btn.png && git commit -qam x"
# (V27) PreToolUse 와 git 훅이 같은 커밋을 두 번 기록했다 — 차단하지 않은 PreToolUse 는 본 로그가
#       아니라 pending 에 둔다(훅이 대체). 상세는 section L.
visual_repo
rm -f .claude/guild/memory/gate-firings.jsonl
printf 'PNG2' > src/a/__screenshots__/btn.png
printf '{"tool_input":{"command":"git commit -am x"}}' | python3 .claude/guild/gates/scripts/gate_precommit.py >/dev/null 2>&1
P27="$(grep -c 'baseline-updated' .claude/guild/memory/gate-firings.jsonl 2>/dev/null || echo 0)"
if [ "$P27" = "0" ]; then ok "V27 PreToolUse 모드는 시각 firing 을 기록하지 않는다"; else bad "V27 PreToolUse firing" "0" "$P27"; fi
git checkout -q -- . >/dev/null 2>&1
# (V28) guard-config: old_string 으로 visual 블록을 지우거나, Write 로 visual 을 빼면 확인 요구.
#       실제 파일을 읽어 편집을 시뮬레이션하므로 절대 경로의 실재 config.json 을 쓴다.
visual_repo
CFG="$PWD/.claude/guild/config.json"
J() { python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1"; }
expect_guard "V28a Edit 의 old_string 으로 visual 블록 삭제 → 확인 요구" ask \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":$(J "$CFG"),\"old_string\":$(J ',"visual":{"baselines":["**/__screenshots__/**","test/goldens/**"]}'),\"new_string\":\"\"}}"
expect_guard "V28b glob 을 아무것도 안 맞게 좁힘 → 확인 요구" ask \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":$(J "$CFG"),\"old_string\":$(J '"**/__screenshots__/**"'),\"new_string\":$(J '"nothing/**"')}}"
expect_guard "V28c Write 로 visual 을 뺀 config → 확인 요구" ask \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":$(J "$CFG"),\"content\":$(J '{"gates":{"enabled":true},"language":"ko"}')}}"
expect_guard "V28d 같은 파일에 무관한 키 추가 → 통과" pass \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":$(J "$CFG"),\"old_string\":$(J '{"gates"'),\"new_string\":$(J '{"language":"ko","gates"')}}"

# ── 3회차 적대적 리뷰 ──
# (V29) expect.any(...) 같은 비대칭 매처를 단언으로 세면, Prettier 가 toEqual({...}) 를 한 줄로
#       접는 것만으로 "assertion 순감소" 차단이 났다(옛 게이트는 통과). 진입점만 센다.
fresh_repo
mkdir -p spec; printf "it('a', () => {\n  expect(obj).toEqual({\n    a: expect.any(String),\n    b: expect.any(Number),\n    c: expect.objectContaining({}),\n  })\n})\n" > spec/r.spec.ts
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm b >/dev/null 2>&1
expect_commit "V29 비대칭 매처가 든 toEqual 을 한 줄로 접는 reflow 는 통과" allow \
  "printf \"it('a', () => {\n  expect(obj).toEqual({ a: expect.any(String), b: expect.any(Number), c: expect.objectContaining({}) })\n})\n\" > spec/r.spec.ts && git commit -qam x"
# (V30) 레포 자체 래퍼 매처(toMatchThemeScreenshot)의 줄만 지우면 `await expect.element(x)` 만 남아
#       아무것도 단언하지 않는다. 매처 호출 횟수(B4)로 잡는다 — 임계 1.
vt_repo
printf "it('a', async () => {\n  await expect\n    .element(el)\n    .toMatchThemeScreenshot('a.png')\n})\n" > src/btn/index.vitest.tsx
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm theme >/dev/null 2>&1
expect_visual "V30 커스텀 스크린샷 매처 한 줄 삭제 → 통과 + 시각 단언 순감소 경고 (4회차: 차단→경고)" allow "시각 단언(스크린샷/golden 매처) 순감소 1건" "" \
  "printf \"it('a', async () => {\n  await expect\n    .element(el)\n})\n\" > src/btn/index.vitest.tsx && git commit -qam x"
vt_repo
printf "it('a', async () => {\n  await expect\n    .element(el)\n    .toMatchThemeScreenshot('a.png')\n})\n" > src/btn/index.vitest.tsx
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm theme >/dev/null 2>&1
expect_commit "V31 같은 매처를 한 줄로 접는 reflow 는 통과 (호출 횟수 불변)" allow \
  "printf \"it('a', async () => {\n  await expect.element(el).toMatchThemeScreenshot('a.png')\n})\n\" > src/btn/index.vitest.tsx && git commit -qam x"
fresh_repo
mkdir -p test; printf "void main() {\n  testWidgets('a', (t) async {\n    await expectLater(\n      find.byType(A),\n      matchesGoldenFile('a.png'),\n    );\n  });\n}\n" > test/g_test.dart
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm b >/dev/null 2>&1
expect_commit "V32 Dart expectLater(…, matchesGoldenFile) 를 한 줄로 접는 reflow 는 통과" allow \
  "printf \"void main() {\n  testWidgets('a', (t) async {\n    await expectLater(find.byType(A), matchesGoldenFile('a.png'));\n  });\n}\n\" > test/g_test.dart && git commit -qam x"
# (V33) visual.matchers 에 적은 이름도 센다.
fresh_repo
printf '{"gates":{"enabled":true},"visual":{"tests":["**/*.vt.ts"],"matchers":["snapPage"]}}' > .claude/guild/config.json
printf "test('a', async () => {\n  await snapPage(page, 'a')\n})\n" > a.vt.ts
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm b >/dev/null 2>&1
expect_visual "V33 visual.matchers 의 이름 호출 삭제 → 시각 단언 경고" allow "시각 단언(스크린샷/golden 매처) 순감소 1건" "" \
  "printf \"test('a', async () => {\n})\n\" > a.vt.ts && git commit -qam x"
# (V34) 잘못된 visual.tests glob 이 경고를 내거나 크래시해도 시크릿 차단은 유지된다.
fresh_repo
printf '{"gates":{"enabled":true},"visual":{"tests":["[[:alpha:]]*.x","["]}}' > .claude/guild/config.json
expect_commit "V34 이상한 visual.tests glob 이어도 시크릿 차단 유지 (PYTHONWARNINGS=error)" block \
  "printf 'SECRET=abc\n' > .env && git add .env && PYTHONWARNINGS=error git commit -m x"
# (V35) guard-config: 상대 경로 + payload cwd, 그리고 이상한 payload 모양에서도 크래시 없이 판단.
visual_repo
expect_guard "V35a 상대 file_path 를 payload cwd 기준으로 시뮬레이션 → 확인 요구" ask \
  "{\"cwd\":$(J "$PWD"),\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\".claude/guild/config.json\",\"old_string\":$(J '"**/__screenshots__/**"'),\"new_string\":$(J '"nomatch"')}}"
expect_guard "V35b old_string 이 숫자인 이상한 payload 도 크래시 없이 키 grep 으로 → 확인 요구" ask \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":$(J "$PWD/.claude/guild/config.json"),\"old_string\":5,\"new_string\":$(J '"visual": {}')}}"

# ── 4회차 적대적 리뷰 ── B4 를 차단으로 두면 커버리지를 유지하는 정상 리팩터가 막혔고
#    (두 매처를 레포 래퍼 하나로 합치기, 매처를 테스트 경로 밖 헬퍼로 옮기기), 의도한 삭제는
#    dismissed.md 로도 통과할 길이 없었다. 경고 + PR 공개(원장의 C 행)로 내렸다.
vt_repo
printf "it('a', async () => {\n  await expect.element(el).toMatchScreenshot('light')\n  await expect.element(el).toMatchScreenshot('dark')\n})\n" > src/btn/index.vitest.tsx
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm two >/dev/null 2>&1
expect_visual "V36 두 매처를 래퍼 하나로 합치는 리팩터 → 통과 (경고만)" allow "시각 단언(스크린샷/golden 매처) 순감소 1건" "Guild 게이트 차단" \
  "printf \"it('a', async () => {\n  await expect.element(el).toMatchThemeScreenshot('a')\n})\n\" > src/btn/index.vitest.tsx && git commit -qam x"
vt_repo
expect_visual "V37 test 파일 통째 삭제는 B1 차단만, 시각 단언 경고는 중복하지 않음" block "테스트 파일 삭제" "시각 단언" \
  "git rm -q src/btn/index.vitest.tsx && git commit -qm x"
vt_repo
printf "it('a', () => {\n  page.toggleScreenshot(true)\n  page.toggleScreenshot(false)\n  expect(1).toBe(1)\n})\n" > src/btn/index.vitest.tsx
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm tog >/dev/null 2>&1
expect_visual "V38 .toggleScreenshot( 같은 비-매처 호출은 시각 단언이 아니다" allow "" "시각 단언" \
  "printf \"it('a', () => {\n  expect(1).toBe(1)\n})\n\" > src/btn/index.vitest.tsx && git commit -qam x"
vt_repo
expect_visual "V39 새 flutter_test_config.dart 추가(A)도 비교 설정 변경 경고" allow "시각 비교 설정 파일 변경 1건: test/flutter_test_config.dart" "" \
  "mkdir -p test && printf 'a\n' > test/flutter_test_config.dart && git add -A && git commit -qm x"

# ── 5회차 적대적 리뷰 ── `expect.element(` 를 한 줄 단언으로 셌더니, Prettier 가 긴 체인을
#    `await expect` / `.element(...)` 로 쪼개는 reflow 3건이 B2 차단이 됐다(원래 게이트는 통과).
fresh_repo
mkdir -p src; printf "it('a', async () => {\n  await expect.element(page.getByRole('button', { name: 'A' })).toBeVisible()\n  await expect.element(page.getByRole('button', { name: 'B' })).toBeVisible()\n  await expect.element(page.getByRole('button', { name: 'C' })).toBeVisible()\n})\n" > src/f.browser.test.tsx
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm b >/dev/null 2>&1
expect_commit "V40 expect.element 체인을 여러 줄로 쪼개는 reflow 는 통과 (원래 게이트와 동일)" allow \
  "printf \"it('a', async () => {\n  await expect\n    .element(page.getByRole('button', { name: 'Submit the order now A' }))\n    .toBeVisible()\n  await expect\n    .element(page.getByRole('button', { name: 'Submit the order now B' }))\n    .toBeVisible()\n  await expect\n    .element(page.getByRole('button', { name: 'Submit the order now C' }))\n    .toBeVisible()\n})\n\" > src/f.browser.test.tsx && git commit -qam x"
# (V41) B4 경고는 PreToolUse 모드에서도 통과(exit 0) + 시각 헤더로 나온다.
vt_repo
printf "it('a', async () => {\n})\n" > src/btn/index.vitest.tsx; git add -A >/dev/null 2>&1
PRE41="$(printf '{"tool_input":{"command":"git commit -m x"}}' | python3 .claude/guild/gates/scripts/gate_precommit.py 2>&1)"; RC41=$?
if [ $RC41 -eq 0 ] && printf '%s' "$PRE41" | grep -qF "시각 단언(스크린샷/golden 매처) 순감소 3건"; then
  ok "V41 PreToolUse 모드: B4 경고 + exit 0"
else
  bad "V41 PreToolUse B4" "exit 0 + warn" "rc=$RC41"
fi
git reset -q >/dev/null 2>&1

# ── 7회차 ── 정규식 번역(`[^/]*a[^/]*a…`)은 `src/*a*a*a*a*a*a*a*b` 같은 glob 에서 경로 하나에
#    수 초~무한 백트래킹했다(차단 경로 위). 세그먼트 단위 2-포인터 매처로 바꿨다 — 시간 상한 검사.
fresh_repo
printf '{"gates":{"enabled":true},"visual":{"tests":["src/*a*a*a*a*a*a*a*a*a*a*b"]}}' > .claude/guild/config.json
mkdir -p src; LONG="src/$(printf 'a%.0s' $(seq 1 200))c.ts"; printf 'x\n' > "$LONG"
git add -A >/dev/null 2>&1; git -c core.hooksPath=/dev/null commit -qm b >/dev/null 2>&1
T0=$(date +%s)
printf 'y\n' > "$LONG"; git commit -qam x >/dev/null 2>&1
T1=$(date +%s)
if [ $((T1 - T0)) -le 10 ]; then ok "V42 병적인 visual.tests glob 도 커밋이 멈추지 않는다 ($((T1 - T0))s)"; else bad "V42 glob 백트래킹" "≤10s" "$((T1 - T0))s"; fi

# ── 8회차 ── 재귀 매처가 ~1000 세그먼트 경로에서 RecursionError → "테스트 경로 아님"으로 조용히 통과.
#    파일시스템 경로 길이 한계 때문에 실제 커밋으로는 만들 수 없어, 함수 단위로 직접 검사한다.
R43="$(python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('g', '$GATE'); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
p = '/'.join(['d'] * 3000) + '/a.vt.ts'
print(g.is_test_path(p, ('**/*.vt.ts',)))
" 2>&1)"
if [ "$R43" = "True" ]; then ok "V43 3000 세그먼트 경로도 visual.tests 로 인식 (재귀 한계 없음)"; else bad "V43 깊은 경로" "True" "$R43"; fi

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
note "== L. 발동 로그 — 커밋당 한 번 기록 (pending → 훅 대체 → 승격) =="
# PreToolUse 와 git 훅이 같은 커밋을 각각 기록해 warn 이 두 번 셌다(draft 경계 규칙은 warn 전용이라
# evolve 의 강등/폐기 성적표에서 두 배로 시끄러워 보였다). 그러나 훅이 없는 새 클론에서는 PreToolUse
# 기록이 유일하므로 그냥 버릴 수도 없다.
LOGF=.claude/guild/memory/gate-firings.jsonl
PENDF=.claude/guild/memory/gate-firings.pending.jsonl
cnt() { [ -f "$1" ] && grep -c "$2" "$1" || echo 0; }
visual_repo
printf 'PNG2' > src/a/__screenshots__/btn.png
printf '{"tool_input":{"command":"git commit -am x"}}' | python3 .claude/guild/gates/scripts/gate_precommit.py >/dev/null 2>&1
[ "$(cnt $LOGF baseline-updated)" = 0 ] && [ "$(cnt $PENDF baseline-updated)" = 1 ] \
  && ok "L1 차단 없는 PreToolUse → 본 로그 0, pending 1" || bad "L1 pending" "log 0 / pending 1" "log $(cnt $LOGF baseline-updated) / pending $(cnt $PENDF baseline-updated)"
git commit -qam x >/dev/null 2>&1
[ "$(cnt $LOGF baseline-updated)" = 1 ] && [ ! -f "$PENDF" ] \
  && ok "L2 git 훅이 pending 을 대체 → 본 로그 1줄, pending 없음" || bad "L2 훅 대체" "log 1 / no pending" "log $(cnt $LOGF baseline-updated) / pending $([ -f $PENDF ] && echo yes || echo no)"
grep -q '"v": 2' "$LOGF" && ok "L3 새 행은 v:2" || bad "L3 v:2" "v 2" "$(head -1 $LOGF)"
# 훅을 건너뛰는 커밋(--no-verify)은 반영되는데 훅이 대체 기록을 남기지 않는다 → PreToolUse 기록이 유일
visual_repo
printf 'PNG2' > src/a/__screenshots__/btn.png
printf '{"tool_input":{"command":"git commit --no-verify -am x"}}' | python3 .claude/guild/gates/scripts/gate_precommit.py >/dev/null 2>&1
git commit -q --no-verify -am x >/dev/null 2>&1
printf 'more\n' >> README.md; git commit -qam y >/dev/null 2>&1
[ "$(cnt $LOGF baseline-updated)" = 1 ] && ok "L3b --no-verify 커밋의 경고는 본 로그에 (다음 훅이 지우지 않음)" \
  || bad "L3b --no-verify" "log 1" "log $(cnt $LOGF baseline-updated) / pending $(cnt $PENDF baseline-updated)"
# 차단된 PreToolUse 는 커밋이 훅에 닿지 않으므로 본 로그에 바로 쓴다
fresh_repo
printf 'k\n' > id_rsa; git add id_rsa >/dev/null 2>&1
printf '{"tool_input":{"command":"git commit -m x"}}' | python3 .claude/guild/gates/scripts/gate_precommit.py >/dev/null 2>&1
[ "$(cnt $LOGF '"secret"')" = 1 ] && [ ! -f "$PENDF" ] \
  && ok "L4 차단된 PreToolUse → 본 로그 1줄, pending 없음" || bad "L4 차단 기록" "log 1 / no pending" "log $(cnt $LOGF '"secret"')"
git rm -q --cached id_rsa >/dev/null 2>&1; rm -f id_rsa
# 차단된 실행의 warn 도 함께 본 로그로 (그 커밋은 훅에 닿지 않으므로 유일한 기록)
visual_repo
printf 'PNG2' > src/a/__screenshots__/btn.png; printf 'k\n' > id_rsa; git add -A >/dev/null 2>&1
printf '{"tool_input":{"command":"git commit -m x"}}' | python3 .claude/guild/gates/scripts/gate_precommit.py >/dev/null 2>&1
[ "$(cnt $LOGF '"secret"')" = 1 ] && [ "$(cnt $LOGF baseline-updated)" = 1 ] && [ ! -f "$PENDF" ] \
  && ok "L4b 차단 시 block 과 warn 이 함께 본 로그에" || bad "L4b block+warn" "secret 1 / baseline 1" "secret $(cnt $LOGF '"secret"') / baseline $(cnt $LOGF baseline-updated)"
# 훅이 없는 저장소: 오래된 pending 은 다음 게이트 실행이 승격한다
fresh_repo; rm -f .git/hooks/pre-commit
OLD="$(python3 -c 'import time;print(time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime(time.time()-700)))')"
printf '{"v": 2, "ts": "%s", "mode": "pre-tool-use", "rule": "boundary:x", "action": "warn", "file": "a"}\n' "$OLD" > "$PENDF"
printf 'more\n' >> README.md
printf '{"tool_input":{"command":"git commit -am y"}}' | python3 .claude/guild/gates/scripts/gate_precommit.py >/dev/null 2>&1
[ "$(cnt $LOGF boundary:x)" = 1 ] && [ "$(cnt $PENDF boundary:x)" = 0 ] \
  && ok "L5 10분 넘은 pending 은 다음 실행에서 본 로그로 승격" || bad "L5 승격" "log 1 / pending 0" "log $(cnt $LOGF boundary:x) / pending $(cnt $PENDF boundary:x)"
# 동시 기록: 잠금이 append 를 잃지 않는다 (sprint worktree 들이 memory 를 공유)
fresh_repo
GP="$PWD/.claude/guild/gates/scripts/gate_precommit.py"
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  python3 - "$GP" "$PWD" "$i" <<'PY' &
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1]); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
g.record_firing("boundary:c%s" % sys.argv[3], "warn", "f"); g.flush_firings(sys.argv[2], "git-hook")
PY
done
wait
[ "$(cnt $LOGF 'boundary:c')" = 12 ] && ok "L6 동시 flush 12개 → 12줄 (유실 없음)" || bad "L6 동시 flush" "12" "$(cnt $LOGF 'boundary:c')"
# L6 는 O_APPEND 의 원자성만으로도 통과한다. 잠금이 실제로 지키는 것은 pending 의 읽기-수정-쓰기와
# 승격이므로, 잠금이 없으면 실패하는 형태로 따로 잰다: 여러 프로세스가 동시에 pending 에 쓰고
# (재작성 경쟁 → 유실), 동시에 같은 오래된 행을 승격한다(→ 중복).
fresh_repo
GP="$PWD/.claude/guild/gates/scripts/gate_precommit.py"
printf '{"v": 2, "ts": "%s", "mode": "pre-tool-use", "rule": "boundary:old", "action": "warn", "file": "o"}\n' "$OLD" > "$PENDF"
for i in $(seq 1 24); do
  python3 - "$GP" "$PWD" "$i" <<'PY' &
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1]); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
for k in range(4):
    g._FIRINGS[:] = []
    g.record_firing("boundary:p%s_%d" % (sys.argv[3], k), "warn", "f"); g.flush_firings(sys.argv[2], "pre-tool-use", pending=True)
PY
done
wait
[ "$(cnt $PENDF 'boundary:p')" = 96 ] && ok "L7 동시 pending 쓰기 96건 → 96줄 (재작성 경쟁 유실 없음)" || bad "L7 동시 pending" "96" "$(cnt $PENDF 'boundary:p')"
# (L8 은 잠금을 빼도 대개 통과한다 — 프로세스 시작이 엇갈려 같은 행을 동시에 읽는 창이 좁다. 잠금 회귀는
#  L7 이 잡는다(잠금 제거 변이에서 96 → 93 실측). L8 은 정상 경로의 중복 승격 부재만 확인한다.)
[ "$(cnt $LOGF 'boundary:old')" = 1 ] && ok "L8 동시 승격 → 오래된 행 정확히 1번" || bad "L8 중복 승격" "1" "$(cnt $LOGF 'boundary:old')"

note ""
note "== M. --firing-log (evolve / audit 의 읽기 경로) =="
fresh_repo
OUTF="$WORK/fl.jsonl"
OUT="$($G --firing-log --out "$OUTF" </dev/null 2>&1)"; RC=$?
[ "$RC" = 0 ] && case "$OUT" in "ROWS 0 $OUTF NOLOG") true ;; *) false ;; esac \
  && ok "M1 로그 없음 → ROWS 0 … NOLOG (0건과 구분)" || bad "M1 NOLOG" "ROWS 0 $OUTF NOLOG" "$RC: $OUT"
$G --firing-log --out rel.jsonl </dev/null >/dev/null 2>&1; RC=$?
[ "$RC" = 64 ] && ok "M2 상대 경로 --out → 64" || bad "M2 상대 경로" "64" "$RC"
# 레거시(v 없음) 짝 제거: 1:1, Δts 0 포함, 600초 경계
cat > "$LOGF" <<'J'
{"ts": "2026-10-01T00:00:00Z", "mode": "pre-tool-use", "rule": "boundary:a", "action": "warn", "file": "x"}
{"ts": "2026-10-01T00:00:00Z", "mode": "git-hook", "rule": "boundary:a", "action": "warn", "file": "x"}
{"ts": "2026-10-01T01:00:00Z", "mode": "pre-tool-use", "rule": "boundary:b", "action": "warn", "file": "y"}
{"ts": "2026-10-01T01:00:01Z", "mode": "pre-tool-use", "rule": "boundary:b", "action": "warn", "file": "y"}
{"ts": "2026-10-01T01:00:05Z", "mode": "git-hook", "rule": "boundary:b", "action": "warn", "file": "y"}
{"ts": "2026-10-01T02:00:00Z", "mode": "pre-tool-use", "rule": "boundary:c", "action": "warn", "file": "z"}
{"ts": "2026-10-01T03:00:00Z", "mode": "pre-tool-use", "rule": "secret", "action": "block", "file": "k"}
{"ts": "2026-10-01T03:00:30Z", "mode": "git-hook", "rule": "secret", "action": "block", "file": "k"}
{"ts": "2026-10-01T04:00:00Z", "mode": "pre-tool-use", "rule": "boundary:d", "action": "warn", "file": "w"}
{"ts": "2026-10-01T04:11:00Z", "mode": "git-hook", "rule": "boundary:d", "action": "warn", "file": "w"}
{"v": 2, "ts": "2026-10-02T00:00:00Z", "mode": "pre-tool-use", "rule": "boundary:e", "action": "warn", "file": "v"}
{"v": 2, "ts": "2026-10-03T00:00:00Z", "mode": "pre-tool-use", "rule": "boundary:h", "action": "block", "file": "q"}
{"v": 2, "ts": "2026-10-03T00:00:30Z", "mode": "git-hook", "rule": "boundary:h", "action": "block", "file": "q"}
J
OUT="$($G --firing-log --out "$OUTF" </dev/null 2>&1)"
fl() { grep -c "$1" "$OUTF"; }
[ "$(fl boundary:a)" = 1 ] && ok "M3 Δts=0 짝 → 1줄" || bad "M3 Δts 0" "1" "$(fl boundary:a)"
[ "$(fl boundary:b)" = 2 ] && ok "M4 PreToolUse 2 + 훅 1 → 2줄 (1:1 짝)" || bad "M4 1:1" "2" "$(fl boundary:b)"
[ "$(fl boundary:c)" = 1 ] && ok "M5 짝 없는 레거시 PreToolUse 는 유일 기록이라 보존" || bad "M5 단독 보존" "1" "$(fl boundary:c)"
[ "$(fl '"secret"')" = 1 ] && ok "M6 레거시 block 행도 짝 제거" || bad "M6 block 짝" "1" "$(fl '"secret"')"
[ "$(fl boundary:d)" = 2 ] && ok "M7 600초 넘게 떨어진 행은 짝이 아님" || bad "M7 경계" "2" "$(fl boundary:d)"
[ "$(fl boundary:e)" = 1 ] && ok "M8 v2 행은 그대로" || bad "M8 v2" "1" "$(fl boundary:e)"
[ "$(fl boundary:h)" = 2 ] && ok "M8b v2 PreToolUse 행은 같은 키의 훅 행이 있어도 짝 제거 대상 아님" || bad "M8b v2 짝 제외" "2" "$(fl boundary:h)"
case "$OUT" in *NOLOG*) bad "M9 로그 있으면 NOLOG 아님" "no NOLOG" "$OUT" ;; *) ok "M9 로그 있으면 NOLOG 아님" ;; esac
$G --firing-log --out "$OUTF" --since 2026-10-01T03:30:00Z </dev/null >/dev/null 2>&1
[ "$(fl boundary:a)" = 0 ] && [ "$(fl boundary:e)" = 1 ] && ok "M10 --since 필터" || bad "M10 --since" "a 0 / e 1" "a $(fl boundary:a) / e $(fl boundary:e)"
# pending 만 있을 때: 10분 미만이면 NOLOG, 넘으면 데이터
rm -f "$LOGF"
NOW="$(python3 -c 'import time;print(time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()))')"
printf '{"v": 2, "ts": "%s", "mode": "pre-tool-use", "rule": "boundary:f", "action": "warn", "file": "u"}\n' "$NOW" > "$PENDF"
OUT="$($G --firing-log --out "$OUTF" </dev/null 2>&1)"
case "$OUT" in "ROWS 0 "*NOLOG) ok "M11 10분 미만 pending 만 → NOLOG" ;; *) bad "M11 young pending" "ROWS 0 … NOLOG" "$OUT" ;; esac
printf '{"v": 2, "ts": "%s", "mode": "pre-tool-use", "rule": "boundary:g", "action": "warn", "file": "u"}\n' "$OLD" >> "$PENDF"
OUT="$($G --firing-log --out "$OUTF" </dev/null 2>&1)"
case "$OUT" in "ROWS 1 $OUTF") ok "M12 10분 넘은 pending 은 데이터로 포함 (NOLOG 아님)" ;; *) bad "M12 old pending" "ROWS 1 $OUTF" "$OUT" ;; esac
[ "$(cnt $PENDF boundary)" = 2 ] && ok "M13 --firing-log 는 읽기 전용 (pending 그대로)" || bad "M13 읽기 전용" "2" "$(cnt $PENDF boundary)"
# 읽을 수 없는 로그 → 판정 불가(2). "발동 0건" 으로 읽히면 audit 이 stale 로 보고한다.
printf '{"v": 2, "ts": "2026-10-01T00:00:00Z", "mode": "git-hook", "rule": "boundary:a", "action": "warn", "file": "x"}\n' > "$LOGF"
if [ "$(id -u)" != 0 ]; then
  chmod 000 "$LOGF"
  $G --firing-log --out "$OUTF" </dev/null >/dev/null 2>&1; RC=$?
  chmod 644 "$LOGF"
  [ "$RC" = 2 ] && ok "M14 읽을 수 없는 로그 → 2" || bad "M14 읽기 실패" "2" "$RC"
else
  ok "M14 읽을 수 없는 로그 → 2 (SKIP: root 는 권한으로 막을 수 없음)"
fi
# 최상위 크래시 분기: 질문하는 모드의 크래시는 0(=clean/없음) 이 아니라 2. --out 의 부모가 파일이면
# makedirs 가 예외를 던져 그 분기를 실제로 지난다.
printf 'x' > "$WORK/notadir"
$G --firing-log --out "$WORK/notadir/o.jsonl" </dev/null >/dev/null 2>&1; RC=$?
[ "$RC" = 2 ] && ok "M15 스캔/로그 모드의 내부 크래시 → 2 (fail-open 0 아님)" || bad "M15 크래시 분기" "2" "$RC"
rm -f "$PENDF"
# 큰 로그에서도 짝 짓기가 빠르다 (이중 루프는 짝 없는 5000행에서 ~50초 — Bash 기본 타임아웃 근처)
python3 - "$LOGF" <<'PY'
import sys, time
with open(sys.argv[1], "w") as fh:
    for i in range(2500):
        t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1700000000 + i * 1000))
        fh.write('{"ts": "%s", "mode": "pre-tool-use", "rule": "boundary:r%d", "action": "warn", "file": "f"}\n' % (t, i))
        fh.write('{"ts": "%s", "mode": "git-hook", "rule": "boundary:h%d", "action": "warn", "file": "f"}\n' % (t, i))
PY
S0=$(date +%s); $G --firing-log --out "$OUTF" </dev/null >/dev/null 2>&1; S1=$(date +%s)
[ $((S1 - S0)) -le 10 ] && [ "$(wc -l < "$OUTF" | tr -d ' ')" = 5000 ] && ok "M16 짝 없는 5000행 → 10초 이내, 5000행 보존 ($((S1 - S0))s)" \
  || bad "M16 성능" "≤10s / 5000" "$((S1 - S0))s / $(wc -l < "$OUTF")"

note ""
note "== N. 0.98.2 — dismissed.md 앞부분만 경로 · -C 인자 해석 · 중앙 관리 파일 정보 경고 =="
INFO_H='ℹ guild gate — 정보(차단 안 함)'
DRAFT_H='draft 규칙 — 차단 안 함, confirm 시 차단'
# dtok — dismissed() 가 돌려준 토큰을 | 로 잇고, 정보 경고 개수를 붙인다.
dtok() {
  python3 -B - "$PWD/.claude/guild/gates/scripts/gate_precommit.py" "$PWD" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1]); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
print("|".join(g.dismissed(sys.argv[2])) + " W=%d" % len(g.dismissed_warnings()))
PY
}
# commit_out — 명령을 실행해 "<rc>␟<stderr+stdout>" 를 돌려준다
commit_out() { local o; o="$(bash -c "$1" 2>&1)"; printf '%s\037%s' "$?" "$o"; }
want_tok() { # $1=label $2=dismissed.md 내용 $3=기대 dtok 출력
  printf '%b' "$2" > .claude/guild/gates/dismissed.md
  local got; got="$(dtok)"
  if [ "$got" = "$3" ]; then ok "$1"; else bad "$1" "$3" "$got"; fi
}
fresh_repo
# S1 — #349 회귀: 맨 경로 항목의 사유가 인용한 경로가 면제되면 안 된다
want_tok "N1 사유 안 백틱 경로는 경로가 아님 (#349 회귀)" \
  '- test/other.md — 이동: `test/t_test.py` 로 옮김\n' 'test/other.md W=0'
R="$(commit_out "git rm -q test/t_test.py && git commit -m x")"
[ "${R%%$'\037'*}" != 0 ] && ok "N1b 사유가 인용한 테스트 파일 삭제는 여전히 차단" || bad "N1b #349 회귀" "block" "allow"
fresh_repo
want_tok "N2 :310 형태(백틱 + 괄호 꼬리) 그대로" '- `env` (`distribution.p12` 등) — 사유\n' 'env W=0'
want_tok "N3 word_app :7 형태 — dismissed() 토큰이 그대로 (…dart:494)" \
  '- `lib/features/part_screen/controller/part_screen_controller.dart:494` (`_updateWord` 성공 시각 저장, `preferences?.setInt(k, ...)`) — 이 클래스의 다른 `preferences` 접근과 달리\n' \
  'lib/features/part_screen/controller/part_screen_controller.dart:494 W=0'
want_tok "N4 백틱 시작이면 구분자 무관 (- · : · en dash)" \
  '- `a/x` - 사유\n- `b/y`: 사유\n- `c/z` – 사유\n' 'a/x|b/y|c/z W=0'
want_tok "N5 * · + · 탭 불릿, 앞쪽 ** 강조" \
  '* `a/x` — r\n+ `b/y` — r\n-\t`c/z` — r\n- **`d/w`** — r\n' 'a/x|b/y|c/z|d/w W=0'
want_tok "N6 **주의** · --- · > 인용 · ONCE-B2 줄은 불릿이 아님" \
  '**주의** `x/y` 는 면제 아님\n---\n> - `q/r` — 인용 안\nONCE-B2 | `p/q` | `s` | 사유 열자 이상입니다 | me | 2026-10-01\n' ' W=0'
fresh_repo
printf -- '- test/t_test.py — 레거시 스위트 폐기\n' > .claude/guild/gates/dismissed.md
expect_commit "N7 맨 경로 항목은 그대로 면제" allow "git rm -q test/t_test.py && git commit -m x"
fresh_repo
printf -- '- `test/other.md` — r\n  - `test/t_test.py` — 하위 설명\n' > .claude/guild/gates/dismissed.md
[ "$(dtok)" = "test/other.md W=1" ] && ok "N8 하위 불릿은 무시 + 정보 경고 1건" || bad "N8 하위 불릿" "test/other.md W=1" "$(dtok)"
R="$(commit_out "git rm -q test/t_test.py && git commit -m x")"
case "${R%%$'\037'*}:${R#*$'\037'}" in
  0:*) bad "N8b 하위 불릿 경로 삭제는 차단 + 정보 머리말" "block" "allow" ;;
  *"$INFO_H"*"하위 불릿"*) ok "N8b 하위 불릿 경로 삭제는 차단, 정보 머리말로 알림" ;;
  *) bad "N8b 하위 불릿 정보 경고" "$INFO_H" "$(printf '%s' "${R#*$'\037'}" | tr '\n' ' ' | cut -c1-120)" ;;
esac
fresh_repo
printf -- '- test/t_test.py (`x`) — r\n' > .claude/guild/gates/dismissed.md
[ "$(dtok)" = " W=1" ] && ok "N9 맨 경로 + 백틱 괄호는 무시 + 정보 경고" || bad "N9 맨 경로+괄호" " W=1" "$(dtok)"
R="$(commit_out "git rm -q test/t_test.py && git commit -m x")"
[ "${R%%$'\037'*}" != 0 ] && ok "N9b 그 경로 삭제는 차단 (면제 안 됨)" || bad "N9b 맨 경로+괄호" "block" "allow"
fresh_repo
printf -- '- 설명 `README.md` — r\n' > .claude/guild/gates/dismissed.md
printf 'more\n' >> README.md
R="$(commit_out "git commit -am x")"
case "${R%%$'\037'*}:${R#*$'\037'}" in
  0:*"$DRAFT_H"*) bad "N10 정보 경고는 draft 머리말이 아님" "no WARN_HEADER" "WARN_HEADER used" ;;
  0:*"$INFO_H"*"백틱이 섞여"*) ok "N10 통과 커밋에도 정보 머리말(WARN_HEADER 아님)로 알림" ;;
  *) bad "N10 정보 머리말" "rc 0 + $INFO_H" "$(printf '%s' "$R" | tr '\n\037' '  ' | cut -c1-120)" ;;
esac
[ "$(tr -d ' \n' < .claude/guild/gates/findings.json)" = '{"open":[]}' ] && ok "N10b 정보 경고는 findings.json 에 넣지 않음" \
  || bad "N10b findings.json" '{"open":[]}' "$(tr -d '\n' < .claude/guild/gates/findings.json)"
SO="$(printf 'env/a.p12\n' | $G --scan-paths --stdin 2>/dev/null)"; SE="$(printf 'env/a.p12\n' | $G --scan-paths --stdin 2>&1 >/dev/null)"
case "$SO|$SE" in
  "SECRET-PATH env/a.p12|"*"$INFO_H"*) ok "N11 --scan-paths 의 정보 경고는 stderr 로 (stdout 은 SECRET-PATH 줄만)" ;;
  *) bad "N11 --scan-paths stderr" "SECRET-PATH only on stdout" "$(printf '%s|%s' "$SO" "$SE" | tr '\n' ' ' | cut -c1-120)" ;;
esac

# S2 — `git -C <arg>` 는 셸 토큰 하나로 해석, 못 하면 조기 경고만 건너뜀
pre_out() { # $1=command-string → "<rc>␟<stderr>"
  local o; o="$(printf '{"tool_input":{"command":%s}}' "$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")" \
    | python3 .claude/guild/gates/scripts/gate_precommit.py 2>&1 >/dev/null)"; printf '%s\037%s' "$?" "$o"
}
SKIPN='-C 경로를 해석하지 못해 조기 경고를 건너뜁니다'
fresh_repo
printf 'SECRET=abc\n' > .env; git add .env >/dev/null 2>&1
R="$(pre_out 'd=/tmp; git -C "$d" commit -m x')"
if [ "${R%%$'\037'*}" = 0 ] && case "${R#*$'\037'}" in *"$SKIPN"*) true ;; *) false ;; esac \
   && [ ! -e '"$d"' ] && [ ! -e '$d' ]; then
  ok "N12 git -C \"\$d\" commit → 건너뜀 메시지 · exit 0 · 디렉터리 생성 없음"
else
  bad "N12 git -C \"\$d\"" "rc 0 + skip note + no dir" "$(printf '%s' "$R" | tr '\n\037' '  ' | cut -c1-100) / $(ls -a | tr '\n' ' ')"
fi
expect_pre "N13 정상 -C <절대 경로> → 그 저장소를 검사(거부)" deny "git -C $PWD commit -m x"
expect_pre "N13b 따옴표 친 -C 경로도 따옴표를 벗겨 검사(거부)" deny "git -C \"$PWD\" commit -m x"
R="$(HOME="$WORK" pre_out 'git -C ~/r commit -m x')"
[ "${R%%$'\037'*}" = 2 ] && ok "N14 따옴표 없는 ~ 경로는 확장해 검사(거부)" || bad "N14 ~ 확장" "rc 2" "$(printf '%s' "$R" | tr '\n\037' '  ' | cut -c1-100)"
R="$(HOME="$WORK" pre_out 'git -C "~/r" commit -m x')"
case "${R%%$'\037'*}:${R#*$'\037'}" in
  0:*"$SKIPN"*) ok "N15 따옴표 안 \"~/r\" 는 확장하지 않음 → 건너뜀" ;;
  *) bad "N15 따옴표 안 ~" "rc 0 + skip" "$(printf '%s' "$R" | tr '\n\037' '  ' | cut -c1-100)" ;;
esac
R="$(pre_out 'git -C "/tmp/x commit -m y')"
case "${R%%$'\037'*}:${R#*$'\037'}" in
  0:*"$SKIPN"*) ok "N16 따옴표 불균형 → 건너뜀 · exit 0" ;;
  *) bad "N16 따옴표 불균형" "rc 0 + skip" "$(printf '%s' "$R" | tr '\n\037' '  ' | cut -c1-100)" ;;
esac
R="$(pre_out "git -C $WORK/nope-not-a-repo commit -m x")"
case "${R%%$'\037'*}:${R#*$'\037'}" in
  0:*"$SKIPN"*) ok "N17 저장소가 아닌 -C → cwd 로 폴백하지 않고 건너뜀" ;;
  *) bad "N17 비저장소 -C" "rc 0 + skip (no cwd fallback)" "$(printf '%s' "$R" | tr '\n\037' '  ' | cut -c1-100)" ;;
esac
git reset -q .env >/dev/null 2>&1; rm -f .env
# `#` 이 든 경로: shlex 기본값이면 `/…/h#b` 가 `/…/h` 로 잘린다
rm -rf "$WORK/h#b"; mkdir -p "$WORK/h#b"; (cd "$WORK/h#b" && git init -q . && cp -R "$WORK/r/.claude" . && printf 'SECRET=abc\n' > .env && git add .env >/dev/null 2>&1)
expect_pre "N18 -C 경로의 # 은 주석이 아님 → 그 저장소를 검사(거부)" deny "git -C $WORK/h#b commit -m x"
# 공백이 든 따옴표 경로는 GIT_COMMIT_RE 가 커밋으로 보지 않는다 — 조기층 미도달, git 훅이 검사
rm -rf "$WORK/a b"; mkdir -p "$WORK/a b"
(cd "$WORK/a b" && git init -q . && git config user.email t@t && git config user.name t \
  && cp -R "$WORK/r/.claude" . && cp "$HOOK" .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit \
  && printf 'SECRET=abc\n' > .env && git add .env >/dev/null 2>&1)
R="$(pre_out "git -C \"$WORK/a b\" commit -m x")"
case "${R%%$'\037'*}:${R#*$'\037'}" in
  0:*"$SKIPN"*) bad "N19 공백 따옴표 경로는 조기층이 커밋으로 인식하지 않음" "silent allow" "skip note" ;;
  0:*) ok "N19 공백 따옴표 경로는 조기층이 커밋으로 인식하지 않음 (지금 동작 고정)" ;;
  *) bad "N19 공백 따옴표 경로" "rc 0" "$(printf '%s' "$R" | tr '\n\037' '  ' | cut -c1-100)" ;;
esac
expect_commit "N19b 같은 커밋은 git 훅이 차단 (권위층)" block "git -C \"$WORK/a b\" commit -m x"
# write_findings / flush_firings — git 저장소가 아니면 쓰지 않고, $PWD(논리 경로)는 그대로 쓴다
fresh_repo
GP="$PWD/.claude/guild/gates/scripts/gate_precommit.py"
rm -rf "$WORK/nogit"; mkdir -p "$WORK/nogit"
python3 -B - "$GP" "$WORK/nogit" "$PWD" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1]); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
g.record_firing("boundary:nogit", "warn", "f")
g.write_findings(sys.argv[2], []); g.flush_firings(sys.argv[2], "git-hook")
g.write_findings(sys.argv[3], [g.finding("secret", "k", "logical-path")])
PY
[ -z "$(ls -A "$WORK/nogit")" ] && ok "N20 git 저장소가 아닌 root → findings/firings 를 쓰지 않음" || bad "N20 비저장소 쓰기" "empty dir" "$(ls -A "$WORK/nogit" | tr '\n' ' ')"
case "$PWD" in /private/*) P_NOTE="(논리=실제)" ;; *) P_NOTE="(논리 $PWD ≠ 실제 경로일 수 있음)" ;; esac
grep -q 'logical-path' .claude/guild/gates/findings.json 2>/dev/null && ok "N21 \$PWD 논리 경로 root 는 그대로 기록 $P_NOTE" \
  || bad "N21 \$PWD 논리 경로" "findings.json written" "missing"
# 다른 repo_root 호출부는 지금 동작(실패 시 cwd) 그대로
mkdir -p "$WORK/nogit/.claude/guild/gates"; printf -- '- `env` — r\n' > "$WORK/nogit/.claude/guild/gates/dismissed.md"
R="$(cd "$WORK/nogit" && printf 'env/a.p12\n' | python3 "$GP" --scan-paths --stdin 2>&1)"; RC=$?
[ "$RC" = 0 ] && ok "N22 --scan-paths --stdin 은 비저장소에서 cwd 의 dismissed.md 를 그대로 읽음" || bad "N22 scan-paths cwd 폴백" "0" "$RC: $R"
R="$(cd "$WORK/nogit" && python3 "$GP" --firing-log --out "$WORK/nogit-fl.jsonl" </dev/null 2>&1)"
case "$R" in "ROWS 0 $WORK/nogit-fl.jsonl NOLOG") ok "N23 --firing-log 는 비저장소에서 cwd 기준 그대로 (NOLOG)" ;; *) bad "N23 firing-log cwd" "ROWS 0 … NOLOG" "$R" ;; esac

# R3 — 중앙 관리 파일이 스테이지되면 정보 경고(차단 아님), 파일별 문구
fresh_repo
printf 'status: confirmed\n- local tweak\n' > .claude/guild/gates/rules/verification.md
R="$(commit_out "git add .claude/guild/gates/rules/verification.md && git commit -m x")"
case "${R%%$'\037'*}:${R#*$'\037'}" in
  0:*"$DRAFT_H"*) bad "N24 규칙 파일 정보 경고는 WARN_HEADER 아님" "info header" "WARN_HEADER" ;;
  0:*"$INFO_H"*"rules/verification.md 는 다음 /gld update 가 게이트 스크립트를 갱신할 때 함께 덮어씁니다"*) ok "N24 rules/verification.md 스테이지 → 정보 경고 · 통과" ;;
  *) bad "N24 규칙 파일 정보 경고" "rc 0 + info" "$(printf '%s' "$R" | tr '\n\037' '  ' | cut -c1-120)" ;;
esac
[ "$(tr -d ' \n' < .claude/guild/gates/findings.json)" = '{"open":[]}' ] && ok "N24b 중앙 관리 파일 경고는 findings.json 에 없음" || bad "N24b findings" '{"open":[]}' "$(tr -d '\n' < .claude/guild/gates/findings.json)"
printf '# local edit\n' >> .claude/guild/gates/scripts/gate_precommit.py
R="$(commit_out "git commit -am x")"
case "${R%%$'\037'*}:${R#*$'\037'}" in
  0:*"$INFO_H"*"gate_precommit.py 는 /gld update 가 갱신하는 중앙 관리 파일입니다"*"scripts/local/"*) ok "N25 게이트 스크립트 스테이지 → 스크립트용 문구 · 통과" ;;
  *) bad "N25 게이트 스크립트 정보 경고" "rc 0 + script wording" "$(printf '%s' "$R" | tr '\n\037' '  ' | cut -c1-120)" ;;
esac
printf 'status: confirmed\n' > .claude/guild/gates/rules/secrets.md; git add .claude/guild/gates/rules/secrets.md >/dev/null 2>&1
R="$(pre_out "git commit -m x")"
case "${R%%$'\037'*}:${R#*$'\037'}" in
  0:*"$INFO_H"*"rules/secrets.md"*) ok "N26 PreToolUse 에서도 같은 정보 경고 · 통과" ;;
  *) bad "N26 PreToolUse 정보 경고" "rc 0 + info" "$(printf '%s' "$R" | tr '\n\037' '  ' | cut -c1-120)" ;;
esac
git commit -qm y >/dev/null 2>&1
printf 'status: draft\n' > .claude/guild/gates/rules/boundaries.md; printf 'more\n' >> README.md
R="$(commit_out "git add -A && git commit -m x")"
case "${R%%$'\037'*}:${R#*$'\037'}" in
  0:*"$INFO_H"*) bad "N27 다른 경로(boundaries.md·README)는 경고 없음" "no info" "info shown" ;;
  0:*) ok "N27 다른 경로(boundaries.md·README)는 경고 없음" ;;
  *) bad "N27 다른 경로" "rc 0" "$(printf '%s' "$R" | tr '\n\037' '  ' | cut -c1-100)" ;;
esac

note ""
note "결과: PASS=$PASS FAIL=$FAIL"
cd /; rm -rf "$WORK"
# ⚠ 검사 개수 바닥. 이 파일도 긴 목록이고, 검사 하나가 조용히 사라져도 `FAIL=0` 이면
#   그린이다 — 설계가 기록한 "190 통과가 옛 바닥선 184를 넘어 4건 소실이 묻혔다" 와 같은
#   모양이다. 실측 PASS 와 같게 유지하고, 의도적으로 늘릴 때만 올린다.
GATE_MIN_CHECKS=201
if [ "$((PASS + FAIL))" -lt "$GATE_MIN_CHECKS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${GATE_MIN_CHECKS}건)."
  exit 1
fi
[ "$FAIL" -eq 0 ]
