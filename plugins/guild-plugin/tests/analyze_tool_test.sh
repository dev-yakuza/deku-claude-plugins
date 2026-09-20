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

# ── §11 유인 SUB 적분 — **로직 검사** ───────────────────────────────────
# ⚠ 라운드 15 에서 이 코드는 처음에 **SUB share 0.0%** 를 냈다. 파싱이 조용히 실패해도
# 「0%」는 그럴듯해 보이고, 그 수는 곧바로 §3.1c 와 M10 의 도달 범위 논거로 들어간다.
# 존재 검사로는 안 잡히므로 **가짜 트랜스크립트를 만들어 실제로 합산되는지** 본다.
SUBI="$($PY - "$TOOL" <<'SBPY'
import importlib.util, json, os, sys, tempfile
spec = importlib.util.spec_from_file_location("t", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
sid = "0000-lead"
def rec(i, pre):
    return json.dumps({"type": "assistant", "sessionId": sid,
                       "message": {"id": i, "usage": {"cache_read_input_tokens": pre}}})
with open(os.path.join(d, sid + ".jsonl"), "w") as f:
    for i in range(12):
        f.write(rec("L%d" % i, 100) + "\n")
sub = os.path.join(d, sid, "subagents")
os.makedirs(sub)
with open(os.path.join(sub, "agent-1.jsonl"), "w") as f:
    for i in range(5):
        f.write(rec("S%d" % i, 400) + "\n")
    f.write(rec("S0", 400) + "\n")          # 중복 id — 세면 안 된다
S = m.load_attended(d)
bad = []
if len(S) != 1:
    bad.append("세션 %d (기대 1)" % len(S))
else:
    if S[0].get("nsub") != 1:
        bad.append("nsub=%r" % S[0].get("nsub"))
    if S[0].get("subint") != 2000:
        bad.append("subint=%r (기대 2000 — 중복 id 1건 제외)" % S[0].get("subint"))
print("OK" if not bad else "BROKEN | " + " | ".join(bad))
SBPY
)"
if [ "$SUBI" = "OK" ]; then ok "§11: 유인 SUB 적분이 실제로 합산된다 (중복 id 제외)"
else bad "§11: 유인 SUB 적분이 실제로 합산된다" "$SUBI"; fi

# ── M3 잔여 회수액 — **노출액과 구별하는가** ──────────────────────────────
# ⚠⚠ 초안은 `$294.80`(429 세션 총 지출)을 **기대 효과**로 적었다. 그것은 회수 가능액이 아니다
# — 슈퍼바이저가 이미 재시도하고 **라벨에서 재개**하므로 완료된 스테이지는 보존된다.
# `--resume` 이 추가로 사는 것은 **죽은 스테이지 «내부»의 부분 진행**뿐이다(실측 $39.58 =
# 노출액의 13.4%). 두 수를 같은 줄에 찍되 **이름을 다르게** 붙이는지 본다.
hasfx_tool2 "M3: 노출액과 잔여 회수액을 **구별해서** 찍는다" '429/미완료 **노출액**'
hasfx_tool2 "M3: 잔여 회수액을 따로 찍는다" '**잔여 회수액**'
# ⚠ 마지막 **라벨 전이 이후** 턴만 세는 것이 이 계산의 전부다 — 그 앞은 라벨이 건너뛴다.
M3CUT="$(grep -c 'seq\[last + 1:\]' "$TOOL")"
if [ "${M3CUT:-0}" -ge 2 ]; then ok "M3: 마지막 라벨 전이 이후 턴만 센다"
else bad "M3: 마지막 라벨 전이 이후 턴만 센다" "seq[last+1:] 2곳" "${M3CUT:-0}곳"; fi
# ⚠⚠ **방향이 반대인 두 누락**을 적었는가. 하나만 적으면 「하한」/「상한」 중 하나로 오독된다
# — 실제로 첫 판이 «하한이다» 와 «상한 추정이다» 를 **같은 블록에 동시에** 적고 있었다.
hasfx_tool2 "M3: 두 누락의 방향이 반대임을 적는다" '하한도 상한도 아니다'

# ── M12 티어 상승분 — **집합 교차를 검사한다** ────────────────────────────
# ⚠ M12 의 달러는 「루프백 합집합 **∩** opus 선언」이라는 **교차**에서 나온다. 한쪽만 보면
# 수가 조용히 부풀거나(합집합 밖 opus 15건까지 셈) 0 이 된다. 실측에서 43 opus 중 **28**만
# 합집합 안이었다 — 교차를 안 하면 **54% 과대**다. 존재 검사로는 안 잡히므로 코드를 읽는다.
M12CHK="$(grep -c 'union_ids and parent in union_ids' "$TOOL")"
M12ELSE="$(grep -c 'other_opus_n += 1' "$TOOL")"
if [ "${M12CHK:-0}" -ge 1 ] && [ "${M12ELSE:-0}" -ge 1 ]; then
  ok "M12: 합집합 ∩ opus 교차로 세고, 합집합 밖 opus 를 따로 센다"
else
  bad "M12: 합집합 ∩ opus 교차" "교차 + 제외 카운터" "교차=$M12CHK 제외=$M12ELSE"
fi
# ⚠ 「관측 0건」 경로가 **있어야** 한다 — 다른 레포에서 opus 스폰이 없으면 0 을 내는 게 아니라
#    「관측 0건」이라고 말해야 한다(M2·M10 과 같은 규율).
hasfx_tool2 "M12: opus 스폰이 없으면 «관측 0건» 을 말한다" '**관측 0건** — opus 선언 스폰이'
# ⚠ 이 수를 「절감」으로 읽으면 안 된다는 경고가 코드에 있어야 한다 — 루프백은 이미
#    「뭔가 틀렸다」가 확인된 자리이고, 상승 제거는 재시도 품질을 낮추는 것이다.
hasfx_tool2 "M12: 절감이 아니라 가격표라고 못박는다" '절감이 아니라 가격표다'

# ── 문서 정합 검사기 — **합성 픽스처로 로직을 검사한다** ─────────────────
# ⚠⚠ 이 작업에서 가장 많이 재발한 결함은 **「같은 이름의 권위 있는 수가 두 문서에서 갈리는
# 것」** 이고 라운드 15~18 만으로 **네 번** 나왔다(규율 5↔8 · 결정표 · 게이트 10↔11 ·
# 규율 7 위반수 2↔5). 전부 결정 문서가 맞고 원장이 낡아 있었다.
#
# ⚠ 두 문서는 **gitignore 안**이라 CI·새 클론에는 없다. 「없으면 통과」로 짜면 그거야말로 이
# 작업이 다섯 번 만든 **발화할 수 없는 검사**다. 그래서 **로직을 합성 픽스처로** 돌린다 —
# 문서가 있든 없든 이 검사는 항상 무언가를 판정한다. 실제 문서 대조는 `--docs` 로 따로 돌리고,
# 문서가 없으면 **exit 2**(0 이 아니다)를 낸다.
DOCCHK="$HERE/../../../design/guild/tools/doc_consistency.py"
if [ ! -f "$DOCCHK" ]; then
  bad "문서 정합 검사기가 있다" "doc_consistency.py" "없음: $DOCCHK"
else
  DC="$($PY - "$DOCCHK" <<'DCPY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("dc", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
bad = []

# ① 절 번호 결번 — 라운드 15 에서 플랜이 §10 → §12 로 뛰고 있었다
if m.section_gaps("## 1. a\n## 2. b\n## 4. d\n") != [3]:
    bad.append("section_gaps: 결번 3 을 못 잡는다")
if m.section_gaps("## 1. a\n## 2. b\n") != []:
    bad.append("section_gaps: 결번 없는데 잡는다")

# ② 스위트 개수 — 라운드 17 의 BLOCKER
if m.suite_counts("게이트는 **10개 스위트** 전부 green") != [10]:
    bad.append("suite_counts: 개수를 못 뽑는다")
# ⚠ 「초안」 절 안의 수는 **당시 값이 맞다** — 보존 규율과 충돌하면 안 된다
if m.suite_counts("### 초안의 표\n10 스위트 green\n") != []:
    bad.append("suite_counts: 초안 절을 덜어내지 못한다")
# ⚠ §12 의 «라운드 N» 절은 **무엇이 틀렸었는지**를 그대로 인용한다 — 당시 값이라 맞다
if m.suite_counts("### 12.17 라운드 19 — x\n게이트를 10 스위트로 적고 있었다\n") != []:
    bad.append("suite_counts: 라운드 기록 절을 덜어내지 못한다")
# ⚠⚠ **더 깊은 제목은 절을 끝내지 않는다** — 첫 구현이 여기서 샜다(실측: «### 라운드 19» 안의
#    «#### …» 하위 제목이 스킵을 풀어 라운드 기록 본문이 다시 대조 대상이 됐다).
#    ⚠ 이 픽스처의 **첫 판은 공허했다**: 본문을 «10 스위트» 로 썼는데 `_SUITE_COUNT` 는 굵은
#    강조나 「개」를 요구하므로 스킵이 풀려도 애초에 0건이었다. **막으려는 회귀를 실제로 넣어
#    붉어지는지 확인**하는 규칙이 픽스처 자체에도 적용된다.
if m.suite_counts("### 12.17 라운드 19\n#### 하위\n**10개 스위트**\n") != []:
    bad.append("suite_counts: 하위 제목이 스킵을 해제한다")
# 같은 레벨 제목은 절을 **끝낸다**
if m.suite_counts("### 라운드 19\n10 스위트\n### 현재\n**11개 스위트**\n") != [11]:
    bad.append("suite_counts: 동급 제목에서 스킵이 안 풀린다")
if m.suite_counts("### 초안의 표\nx\n## 현재\n**11개 스위트**\n") != [11]:
    bad.append("suite_counts: 초안 절 뒤에서 다시 세지 못한다")

# ③ 커밋 해시 — 7자리만. 8자리는 세션 UUID 라 오검출이 났었다(실측)
if m.cited_hashes("커밋 `753f68b` 과 세션 `9b1ef612`") != ["753f68b"]:
    bad.append("cited_hashes: 7자리만 골라내지 못한다")
if m.cited_hashes("`9e91e361….jsonl`") != []:
    bad.append("cited_hashes: 말줄임 뒤 토큰을 거른다")

# ④ 폐기 수치 재인용 — 이 작업에서 **세 번** 일어난 클래스(0.7087 · 4.0배 · +41.7~49.5%)
REG = "## 10b.\n| 폐기된 값 | 대체 | 무엇 |\n| `4.0배` | **2.0배** | x |\n\n## 12.\n"
if m.retracted_values(REG) != [("4.0배", "2.0배")]:
    bad.append("retracted_values: §10b 표를 못 읽는다")
v = m.retraction_violations(REG + "## M1\n손익분기는 4.0배다.\n")
if not any("4.0배" in x for x in v):
    bad.append("retraction_violations: 표식 없는 재인용을 못 잡는다")
if m.retraction_violations(REG + "## M1\n~~4.0배~~ 였다.\n"):
    bad.append("retraction_violations: 취소선 표식을 인정하지 않는다")
if m.retraction_violations(REG + "## M1\n라운드 5 이전에는 4.0배였다.\n"):
    bad.append("retraction_violations: 「이전」 표식을 인정하지 않는다")
# ⚠ §10b **표 자신**은 당연히 폐기값을 담는다 — 자기 자신을 신고하면 안 된다
if m.retraction_violations(REG):
    bad.append("retraction_violations: §10b 표 자신을 신고한다")
if not m.retraction_violations("## 12.\n아무 표도 없다\n"):
    bad.append("retraction_violations: §10b 표 부재를 신고하지 않는다")

# ⑤ 원장 줄 수 주장 — **두 번 낡았다**(951→1,051, 1,051→1,866)
if m.plan_line_claim("근거는 `08-plan.md`(**1,866줄**)에 있다") != 1866:
    bad.append("plan_line_claim: 굵은 강조 표기를 못 읽는다")
if m.plan_line_claim("근거는 `08-plan.md`(1,051줄)에") != 1051:
    bad.append("plan_line_claim: 평문 표기를 못 읽는다")
if m.plan_line_claim("줄 수를 안 적은 문서") is not None:
    bad.append("plan_line_claim: 없는데 있다고 한다")

# ⑥ 조치별 상태 정합 — **이 작업에서 가장 많이 갈린 축**인데 검사에서 빠져 있었다
PLAN_T = ("### 4.0 결정 요약\n| 조치 | 경로 | 상태 |\n| **M5** x | 공통 | \u2705 **출하** |\n"
          "| **M1** y | sprint | 막힘 |\n### 4.1 상세\n| **M5** | 이름 | 공통 | 기대효과 |\n")
DEC_T = ("## 2. 결정표\n| 조치 | 경로 | 상태 |\n| **M5** x | 공통 | \u2705 **출하됨** |\n"
         "| **M1** y | sprint | 막힘 |\n### 미분류\n")
if m.measure_status(PLAN_T, "### 4.0 결정 요약") != {"M5": "done", "M1": "blocked"}:
    bad.append("measure_status: §4.0 표를 정확히 읽지 못한다 (§4.1 이 덮어쓰는가?)")
if m.status_mismatches(PLAN_T, DEC_T):
    bad.append("status_mismatches: 일치하는데 불일치라 한다")
# ⚠ 「부분 철회」는 **출하** 를 부분 문자열로 포함하는 칸에 붙는다 — 어휘 순서가 뒤면
#    done 으로 먹혀 조용히 「일치」라고 보고한다(실측: M9 반증 후 이 칸에서 바로 났다).
P_REV = "### 4.0 결정 요약\n| a | b | c |\n| **M9** x | 공통 | \u26a0 **부분 철회**(출하됨 이후) |\n"
D_REV = "## 2. 결정표\n| a | b | c |\n| **M9** x | 공통 | \u26a0 **부분 철회** |\n"
if m.measure_status(P_REV, "### 4.0 결정 요약") != {"M9": "partly-reverted"}:
    bad.append("measure_status: 「부분 철회」가 done 으로 먹힌다 (어휘 순서)")
if m.status_mismatches(P_REV, D_REV):
    bad.append("status_mismatches: 양쪽 다 부분 철회인데 불일치라 한다")

DEC_BAD = DEC_T.replace("| **M5** x | 공통 | \u2705 **출하됨** |", "| **M5** x | 공통 | 막힘 |")
if not any("M5" in x for x in m.status_mismatches(PLAN_T, DEC_BAD)):
    bad.append("status_mismatches: M5 출하↔막힘 불일치를 못 잡는다")
DEC_MISSING = DEC_T.replace("| **M5** x | 공통 | \u2705 **출하됨** |\n", "")
if not any("M5" in x and "결정표에 없다" in x for x in m.status_mismatches(PLAN_T, DEC_MISSING)):
    bad.append("status_mismatches: 결정표의 행 누락을 못 잡는다")

# ⑦ check() 가 실제로 문제를 **낸다** — 통과만 하는 함수가 아니다
probs = m.check("## 1. a\n## 3. c\n**9개 스위트**\n", "**9개 스위트**\n", 11)
if not any("결번" in x for x in probs):
    bad.append("check: 결번을 보고하지 않는다")
if len([x for x in probs if "스위트 개수" in x]) != 2:
    bad.append("check: 두 문서의 스위트 불일치를 각각 보고하지 않는다")
if not any("정본" in x for x in probs):
    bad.append("check: 규율 정본 지시 누락을 보고하지 않는다")
print("OK" if not bad else "BROKEN | " + " | ".join(bad))
DCPY
)"
  if [ "$DC" = "OK" ]; then ok "문서 정합 검사기: 로직 25종이 합성 픽스처에서 발화한다"
  else bad "문서 정합 검사기: 로직 25종" "$DC"; fi

  # 실제 문서가 있으면 대조까지 한다. 없으면 **그 사실을 출력**한다 — 조용히 넘어가지 않는다.
  DOCDIR="$HERE/../../../design/guild"
  if [ -f "$DOCDIR/08-plan.md" ] && [ -f "$DOCDIR/08-decisions.md" ]; then
    if OUT="$("$PY" "$DOCCHK" --docs "$DOCDIR" --tests "$HERE" 2>&1)"; then
      ok "문서 정합: 원장 ↔ 결정 문서 ($OUT)"
    else
      bad "문서 정합: 원장 ↔ 결정 문서" "일치" "$OUT"
    fi
  else
    ok "문서 정합: 원장이 이 환경에 없다 (gitignore) — 로직 검사만 돌았다"
  fi
fi

# ── freeze_corpus — **실제로 얼려서** 본다 ───────────────────────────────
# ⚠⚠ 이 작업에서 코퍼스를 **두 번** 잃었다: arm-A 동결본이 `/tmp` 정리로, `word_app` 의
# 유인 `/gld dev` 트랜스크립트 **133개**가 호스트 회전으로. 후자는 **A2·M10 을 닫을 유일한
# 데이터**였고 복구 경로가 없다. 이 도구는 그 재발을 막는다 — 그러니 **도구 자신이 조용히
# 반쪽 복사를 하면 안 된다.** 문자열이 아니라 임시 트리를 실제로 얼리고 검증한다.
FRZ="$HERE/../../../design/guild/tools/freeze_corpus.py"
if [ ! -f "$FRZ" ]; then
  bad "freeze_corpus.py 가 있다" "파일" "없음"
else
  ok "freeze_corpus.py 가 있다"
  FW="$(mktemp -d)"; mkdir -p "$FW/src/sub"
  printf 'aaa' > "$FW/src/one.log"; printf 'bbbb' > "$FW/src/sub/two.log"
  if "$PY" "$FRZ" --src "$FW/src" --name t --archive "$FW/arc" >/dev/null 2>&1; then
    D="$(find "$FW/arc/t" -maxdepth 1 -mindepth 1 -type d | head -1)"
    # ① 하위 디렉터리까지 옮겼는가 · MANIFEST 가 있는가
    if [ -f "$D/sub/two.log" ] && [ -f "$D/MANIFEST.json" ]; then
      ok "freeze: 하위 트리까지 얼리고 MANIFEST 를 쓴다"
    else bad "freeze: 하위 트리 + MANIFEST" "둘 다" "누락"; fi
    # ② 검증이 통과하는가
    if "$PY" "$FRZ" --verify "$D" >/dev/null 2>&1; then ok "freeze: 갓 얼린 것은 검증을 통과한다"
    else bad "freeze: 갓 얼린 것의 검증" "통과" "실패"; fi
    # ③ ⚠ **변조를 잡는가** — 못 잡으면 이 도구는 안심만 주고 아무것도 안 한다
    printf 'x' >> "$D/one.log"
    if "$PY" "$FRZ" --verify "$D" >/dev/null 2>&1; then
      bad "freeze: 변조를 잡는다" "검증 실패해야" "통과했다"
    else ok "freeze: 변조를 잡는다 (sha256)"; fi
    # ④ ⚠ **원본이 변해도 동결본은 그대로** — 이것이 존재 이유다
    printf 'ccc' > "$FW/src/three.log"
    M3="$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['files'])" "$D/MANIFEST.json")"
    if [ "$M3" = "2" ]; then ok "freeze: 원본이 늘어도 동결본의 MANIFEST 는 불변"
    else bad "freeze: 동결본 불변" "2파일" "$M3"; fi
  else
    bad "freeze: 임시 트리를 얼린다" "성공" "실패"
  fi
  # ⑤ ⚠⚠ **심볼릭 링크를 조용히 빠뜨리지 않는가.** 첫 판이 `islink` 를 전부 건너뛰어
  #    **Guild 자신의 `memory` 링크**(런의 신호를 워크트리 밖으로 나르는 그것)가 말없이
  #    빠졌다. 파일 링크는 따라가고, 디렉터리 링크는 **MANIFEST 에 기록**돼야 한다.
  FS="$(mktemp -d)"; mkdir -p "$FS/src/real" "$FS/src/inner"
  printf 'd' > "$FS/src/real/m.md"; printf 'f' > "$FS/src/inner/f.txt"
  ln -s "$FS/src/real" "$FS/src/memory"; ln -s "$FS/src/inner/f.txt" "$FS/src/link.txt"
  if "$PY" "$FRZ" --src "$FS/src" --name s --archive "$FS/arc" >/dev/null 2>&1; then
    SD="$(find "$FS/arc/s" -maxdepth 1 -mindepth 1 -type d | head -1)"
    NF="$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['files'])" "$SD/MANIFEST.json")"
    NS="$("$PY" -c "import json,sys;print(len(json.load(open(sys.argv[1])).get('skipped') or []))" "$SD/MANIFEST.json")"
    # 파일 2개 + 파일링크 1개 = 3 · 디렉터리 링크 1개는 기록
    if [ "$NF" = "3" ]; then ok "freeze: 파일 심볼릭 링크를 따라가 얼린다"
    else bad "freeze: 파일 링크를 얼린다" "3파일" "$NF"; fi
    if [ "$NS" = "1" ]; then ok "freeze: 디렉터리 링크를 MANIFEST 에 기록한다 (조용히 빠뜨리지 않는다)"
    else bad "freeze: 디렉터리 링크 기록" "1건" "$NS"; fi
  else bad "freeze: 심볼릭 링크가 있는 트리를 얼린다" "성공" "실패"; fi
  # ⑥ ⚠⚠ **같은 초에 두 번** 얼려도 죽지 않는가 — 첫 판은 FileExistsError 트레이스백이었다.
  #    ⚠ 그냥 두 번 부르면 **두 호출이 다른 초에 떨어져** 충돌이 안 난다 — 실제로 그렇게 만든
  #    첫 검사는 변이(접미사 로직 제거)에 **발화하지 않았다**. 그래서 **현재 초의 디렉터리를
  #    미리 만들어** 충돌을 결정적으로 일으킨다.
  # ⚠ 한 초만 선점하면 **초 경계를 스쳐** 충돌이 안 난다(실측: 변이가 두 번 연속 발화 실패).
  #    now±2초를 전부 선점해 충돌을 **결정적으로** 만든다.
  "$PY" - "$FS/arc/s" <<'CLPY'
import datetime, os, sys
base = sys.argv[1]
now = datetime.datetime.now()
for d in range(-2, 3):
    os.makedirs(os.path.join(base, (now + datetime.timedelta(seconds=d)).strftime("%Y%m%d-%H%M%S")),
                exist_ok=True)
CLPY
  if "$PY" "$FRZ" --src "$FS/src" --name s --archive "$FS/arc" >/dev/null 2>&1; then
    ok "freeze: 같은 초의 디렉터리가 이미 있어도 죽지 않는다"
  else bad "freeze: 같은 초 충돌" "접미사로 회피" "죽었다"; fi
  # ⑦ ⚠⚠ **archive 가 src 안이면 거부**해야 한다 — 아니면 동결본이 자기를 삼킨다(실측 1→3파일)
  if "$PY" "$FRZ" --src "$FS/src" --name inner --archive "$FS/src/arc" >/dev/null 2>&1; then
    bad "freeze: archive 가 src 안이면 거부" "실패해야" "얼렸다"
  else ok "freeze: archive 가 src 안이면 거부한다 (자기 포함 방지)"; fi
  rm -rf "$FS"

  # ⑨ ⚠⚠ **복사가 실패하면 반쪽 동결본을 남기지 않는가.** 첫 판은 읽기 권한 없는 파일 하나에
  #    트레이스백으로 죽으면서 **MANIFEST 없는 디렉터리**를 남겼다 — 나중에 동결본처럼 보이고,
  #    절반만 얼린 코퍼스로 잰 수는 되돌릴 수 없다.
  FP="$(mktemp -d)"; mkdir -p "$FP/src"; printf 'ok' > "$FP/src/a.log"; printf 'x' > "$FP/src/no.log"
  chmod 000 "$FP/src/no.log"
  "$PY" "$FRZ" --src "$FP/src" --name p --archive "$FP/arc" >/dev/null 2>&1
  _left="$(find "$FP/arc" -mindepth 2 -maxdepth 2 -type d 2>/dev/null | wc -l | tr -d ' ')"
  chmod 644 "$FP/src/no.log"
  if [ "$_left" = "0" ]; then ok "freeze: 복사 실패 시 반쪽 동결본을 지운다"
  else bad "freeze: 반쪽 동결본 정리" "0개" "${_left}개 남음"; fi
  rm -rf "$FP"

  # ⑧ **기본 archive 가 /tmp 도 레포 안도 아니어야 한다** — 그게 이 파일의 존재 이유다
  if grep -q 'DEFAULT_ARCHIVE = os.path.expanduser("~/.claude/guild-corpus")' "$FRZ"; then
    ok "freeze: 기본 보관 경로가 /tmp 밖이다"
  else bad "freeze: 기본 보관 경로" "~/.claude/guild-corpus" "다른 값"; fi
  rm -rf "$FW"
fi

# ── 문법 ─────────────────────────────────────────────────────────────────
if $PY -m py_compile "$TOOL" 2>/dev/null; then ok "도구가 컴파일된다"; else bad "도구가 컴파일된다" "py_compile 실패"; fi

# ⚠ 바닥선 — 나머지 10 스위트와 같은 규약. 실측 PASS 와 정확히 일치시킨다.
TOOL_MIN_CHECKS=49
echo
echo "analyze_tool: $PASS passed, $FAIL failed"
if [ "$((PASS + FAIL))" -lt "$TOOL_MIN_CHECKS" ]; then
  echo "  FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 $TOOL_MIN_CHECKS 건) — 따옴표가 나머지를 삼켰을 수 있습니다"
  exit 1
fi
[ "$FAIL" -eq 0 ] || exit 1
