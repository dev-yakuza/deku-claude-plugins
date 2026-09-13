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

# ── §9 스테이지 귀속 — **로직 검사** ─────────────────────────────────────
# ⚠⚠ 이 스위트의 검사가 전부 「문자열 존재」였기 때문에, `cur` 갱신의 **47% 가 전이가 아닌
# 마커 문자열**로 정해지던 버그가 24건 green 아래에 있었다. 오귀속은 같은 role 의 재스폰 쌍을
# 다른 그룹으로 쪼개 **위음성**을 만든다(합집합 37 ↔ 44, 침묵률 43.2% ↔ 52.3%,
# M1 손익분기 2.2 ↔ 2.0). **문자열이 아니라 동작을 검사한다.**
STAGE="$($PY - "$TOOL" <<'STPY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("t", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
Q = chr(34)
cases = [
    ("gh issue edit 42 --add-label " + Q + "guild:execute" + Q, "execute", "라벨 전이"),
    ("gh api x --jq select(.body|contains(" + Q + "guild:design:output" + Q + "))", None, "코멘트 마커"),
    ("cat <<EOF\n<!-- guild:test-evidence:step-1 -->\nEOF", None, "test-evidence"),
    ("gh issue edit 42 --add-label guild:qa", "qa", "따옴표 없는 전이"),
]
bad = []
for arg, want, why in cases:
    g = m._STAGE_TRANSITION.search(arg)
    g = g.group(1) if g else None
    if g != want:
        bad.append(why + ": got=" + str(g) + " want=" + str(want))
print("OK" if not bad else "BROKEN | " + " | ".join(bad))
STPY
)"
if [ "$STAGE" = "OK" ]; then
  ok "§9: 스테이지 귀속이 라벨 **전이** 만 인정한다 (마커 문자열 아님)"
else
  bad "§9: 스테이지 귀속이 라벨 전이만 인정한다" "$STAGE"
fi
hasfx_tool2() { if grep -qF -- "$2" "$TOOL"; then ok "$1"; else bad "$1" "not found: $2"; fi; }
hasfx_tool2 "§9: 본문 폴백이 이중 인코딩을 고려한다" '이중 인코딩'

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
# ⚠ A20 은 **해소됐다**(스냅샷을 떠 도구로 재현 확인: 동결본 = 라이브). 그러나 라이브
# 디렉터리에 대고 돌리면 여전히 수가 변하므로, 도구는 **「동결본에 대고 돌려라」** 를 적어야
# 한다 — 그 지시가 사라지면 A20 이 그대로 돌아온다.
hasfx_tool "§11: 동결 스냅샷에 대고 돌리라고 지시한다" '동결 스냅샷에 대고 돌려라'
hasfx_tool "§11: 동결본과 라이브가 일치함을 기록한다" '동결본과 라이브가'

# ── §4c 표준 파일별 내역 — **로직 검사** ─────────────────────────────────
# ⚠ `_preflight.md` Item 2 는 「`verification.md` 하나가 1.4%」라고 지시한다. 그 수를 내는
# 것이 이 내역이고, 내역이 사라지면 지시문의 수가 **출처를 잃는다**(라운드 6 에서 실제로
# 그 상태였다). 존재가 아니라 **추출이 되는지**를 본다 — 정규식이 깨지면 전부 「파일명 불명」
# 한 줄로 뭉쳐 표가 조용히 무의미해지기 때문이다.
STD="$($PY - "$TOOL" <<'SDPY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("t", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
cases = [
    ("cat docs/standards/verification.md", "verification.md"),
    ("sed -n 1,80p /x/y/docs/standards/quality-bar.md", "quality-bar.md"),
    ("cat docs/specs/12/plan.md", None),
]
bad = []
for arg, want in cases:
    g = m._STD_FILE.search(arg)
    g = g.group(1) if g else None
    if g != want:
        bad.append(arg + ": got=" + str(g) + " want=" + str(want))
print("OK" if not bad else "BROKEN | " + " | ".join(bad))
SDPY
)"
if [ "$STD" = "OK" ]; then ok "§4c: 표준 파일별 내역이 파일명을 뽑아낸다"
else bad "§4c: 표준 파일별 내역이 파일명을 뽑아낸다" "$STD"; fi

# ── 문법 ─────────────────────────────────────────────────────────────────
if $PY -m py_compile "$TOOL" 2>/dev/null; then ok "도구가 컴파일된다"; else bad "도구가 컴파일된다" "py_compile 실패"; fi

# ⚠ 바닥선 — 나머지 10 스위트와 같은 규약. 실측 PASS 와 정확히 일치시킨다.
TOOL_MIN_CHECKS=28
echo
echo "analyze_tool: $PASS passed, $FAIL failed"
if [ "$((PASS + FAIL))" -lt "$TOOL_MIN_CHECKS" ]; then
  echo "  FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 $TOOL_MIN_CHECKS 건) — 따옴표가 나머지를 삼켰을 수 있습니다"
  exit 1
fi
[ "$FAIL" -eq 0 ] || exit 1
