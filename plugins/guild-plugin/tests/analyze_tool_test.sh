#!/usr/bin/env bash
# 11번째 스위트 — `design/guild/tools/analyze_sprint_logs.py` 의 회귀 검사.
#
# ⚠ 왜 이 스위트가 필요한가. 그 도구는 **일곱 번 틀렸고** 그때마다 최상위 결론이 뒤집혔다
# (「모델 출력 44.2%」 → 실제 0.46%). 그런데 검사가 0건이었다. 나머지 10개 스위트는 전부
# bash 이고 `tests/` 에 파이썬 검사가 없어서, 도구를 고치는 작업에 「10 스위트 green」
# 게이트를 걸면 **공허하게 통과**한다.
#
# ⚠ 이 스위트는 **절감을 주장하지 않는다** — 계측의 정확성만 본다. 플랜 §6 규율 1의 예외.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOL="$HERE/../../../design/guild/tools/analyze_sprint_logs.py"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s — %s\n' "$1" "$2"; }

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then echo "python3 없음 — 스위트 중단"; exit 1; fi
if [ ! -f "$TOOL" ]; then
  bad "도구가 레포에 있다" "$TOOL 없음 — .gitignore 가 design/guild/* + !design/guild/tools/ 인지 확인"
  echo; echo "analyze_tool: $PASS passed, $FAIL failed"; exit 1
fi
ok "도구가 레포에 있다 (리뷰 가능·버전 관리 안)"

# ── `_classes()` 의 다섯 결함 ─────────────────────────────────────────────
# 라운드 6에서 무작위 표본 40건 중 「혼합」의 **87%가 오분류**로 드러나 전면 재작성된 함수다.
# 네 가지 기계적 원인 + 파이프 생산자 규칙을 각각 한 줄로 고정한다.
CASES="$($PY - "$TOOL" <<'PYEOF'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("t", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
# (입력, 기대 집합, 무엇을 막는가)
cases = [
    ("ls docs/specs/289 2>&1",                  "list",      "D1 2>&1 의 & 가 분리자로 매칭돼 세그먼트 `1` 이 커맨드가 된다"),
    # ⚠ 판별력 있는 입력으로 골라야 한다. `grep -E "a|b" f.md` 는 순진하게 쪼개도 `[0]` 이
    # 여전히 `grep` 으로 시작해 **발화하지 않는다**(실증). `;` 를 쓰면 뒤 조각이 커맨드가 된다.
    ('grep "a;b" f.md',                         "search",    "D2 따옴표 안의 분리자가 세그먼트를 쪼갠다"),
    ("cat <<EOF\n# hi\nimport os\nEOF",         "read",      "D3 heredoc 본문이 줄마다 커맨드로 세어진다"),
    ("cd /x && sed -n 1,50p f.md",              "read",      "D4 cd 가 감쌀 대상 없이 디렉터리 경로를 커맨드로 만든다"),
    # ⚠ D5(파이프 생산자 규칙)는 **검사로 만들 수 없다.** `_split_top(seg,("|",))[0]` 을 지워도
    # `_head_of()` 가 어차피 첫 낱말을 고르므로 결과가 같다 — 실측: snap37 의 Bash 9,436건 중
    # 분류가 달라지는 것 **0건**. 즉 그 줄은 **dead code** 이고, 그것을 「검사」한다고 적으면
    # 발화할 수 없는 검사가 된다. 아래 둘은 D5 가 아니라 **`_head_of` 의 첫낱말 규칙**을 고정한다.
    ("flutter test 2>&1 | tail -100",           "cmd",       "파이프가 있어도 첫 낱말이 커맨드면 커맨드"),
    ("cat x | grep y",                          "read",      "파이프가 있어도 첫 낱말이 읽기면 읽기"),
    ('echo "==" && cat f.md',                   "cmd,read",  "진짜 혼합은 혼합으로 남아야 한다"),
    ("for f in a b; do cat $f; done",           "read",      "루프 키워드는 바이트를 내지 않는다"),
    ('D="/tmp/x" && cat $D/f.md',               "read",      "변수 대입은 바이트를 내지 않는다"),
    ("git diff main -- x.yml",                  "cmd",       "순수 커맨드"),
]
for arg, want, why in cases:
    got = ",".join(sorted(m._classes(arg)))
    print(("OK" if got == want else "NG") + "\t" + why + "\t" + got + "\t" + want)
PYEOF
)"
while IFS=$'\t' read -r st why got want; do
  [ -z "${st:-}" ] && continue
  if [ "$st" = "OK" ]; then ok "_classes: $why"; else bad "_classes: $why" "got [$got] want [$want]"; fi
done <<< "$CASES"

# ── 자기검사 3축이 존재하고 exit 1 을 낼 수 있는가 ────────────────────────
# ⚠ 존재 검사가 아니라 **발화 가능성** 검사다. 이 도구의 결함 중 둘은 「검사가 있는데
# 발화할 수 없는」 형태였다.
AX="$(grep -c "sys.exit(1)" "$TOOL" || true)"
if [ "${AX:-0}" -ge 2 ]; then ok "자기검사가 exit 1 경로를 갖는다 ($AX 곳)"
else bad "자기검사가 exit 1 경로를 갖는다" "sys.exit(1) 이 ${AX:-0} 곳뿐"; fi

for ax in "턴↔결과 귀속" "결과바이트↔delta 상관" "정합성"; do
  if grep -qF -- "$ax" "$TOOL"; then ok "자기검사 축: $ax"
  else bad "자기검사 축: $ax" "문자열 없음"; fi
done

# ── 알려진 모델 결함이 기록돼 있는가 (A17) ───────────────────────────────
# 압축 요약 출력을 `cap * keep * 0.05` 로 잡는데 실측은 10,503~26,078 tok 이다(3~56배 과소).
# 고치기 전까지 **그 사실이 코드에 적혀 있어야** 한다 — 그렇지 않으면 다음 사람이 그 수를
# 정본으로 쓴다(이 작업에서 실제로 일어났다).
if grep -qF "cap * keep * 0.05" "$TOOL"; then
  if grep -qiE "과소|A17|실측 요약" "$TOOL"; then ok "A17(압축 요약 비용 과소)이 코드에 기록돼 있다"
  else bad "A17 이 코드에 기록돼 있다" "cap*keep*0.05 가 있는데 경고 주석이 없다"; fi
else ok "A17: 압축 요약 비용 모델이 수정됐다"; fi

# ── 유인 프런트엔드(§11) — §3 의 수를 코드가 내는가 ──────────────────────
# ⚠ §3(유인 경로 측정) 전체가 임시 스크립트 위에 있었다 — 규율 7(「도구가 찍지 않는 수는
# 쓰지 않는다」) 위반. M11 의 근거인 «유인 8.5% 압축» 도 재현 가능한 코드가 없었다.
for _fn in "load_attended" "def attended"; do
  if grep -qF -- "$_fn" "$TOOL"; then ok "§11: $_fn 이 있다"
  else bad "§11: $_fn 이 있다" "없음 — §3 의 수가 다시 임시 스크립트로 내려간다"; fi
done
# ⚠ 유인 로그에는 `result`/비용 레코드가 **없다.** 그 한계를 코드가 적어야 다음 사람이
# 「§3 에서 달러를 뽑자」로 가지 않는다.
hasfx_tool() { if grep -qF -- "$2" "$TOOL"; then ok "$1"; else bad "$1" "not found: $2"; fi; }
hasfx_tool "§11: 달러를 낼 수 없다는 한계를 적는다" '달러를 낼 수 없다'
hasfx_tool "§11: 자기검사 3축 중 하나가 유인에 없음을 적는다" '원리적으로 없다'
hasfx_tool "§11: 세션 중복(디스크 복제본)을 제거한다" 'sessionId 로 제거'
hasfx_tool "§11: postTokens 비와 시뮬 keep 의 정의가 다름을 적는다" '정의가 다르다'
hasfx_tool "§11: 코퍼스가 얼어 있지 않음을 적는다" '얼어 있지 않다'

# ── 문법 ─────────────────────────────────────────────────────────────────
if $PY -m py_compile "$TOOL" 2>/dev/null; then ok "도구가 컴파일된다"; else bad "도구가 컴파일된다" "py_compile 실패"; fi

# ⚠ 바닥선 — 나머지 10 스위트와 같은 규약. 실측 PASS 와 정확히 일치시킨다.
TOOL_MIN_CHECKS=24
echo
echo "analyze_tool: $PASS passed, $FAIL failed"
if [ "$((PASS + FAIL))" -lt "$TOOL_MIN_CHECKS" ]; then
  echo "  FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 $TOOL_MIN_CHECKS 건) — 따옴표가 나머지를 삼켰을 수 있습니다"
  exit 1
fi
[ "$FAIL" -eq 0 ] || exit 1
