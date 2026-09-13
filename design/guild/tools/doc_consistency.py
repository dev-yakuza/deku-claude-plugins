#!/usr/bin/env python3
"""원장(`08-plan.md`)과 결정 문서(`08-decisions.md`)의 **기계적 정합성** 검사.

⚠ 왜 필요한가. 이 작업에서 가장 많이 재발한 결함은 **「같은 이름의 권위 있는 수가 두 문서에서
갈리는 것」** 이고, 라운드 15~18 만으로 **네 번** 나왔다:

    규율 목록      플랜 §10  5개   ↔  결정 문서 §6  8개
    결정표         플랜 §4.0 구현이전 ↔  결정 문서 §2  현재
    커밋 게이트    플랜 §5.1 10 스위트 ↔  결정 문서 §6  11 스위트
    규율 7 위반수  플랜 §7.1 2회    ↔  결정 문서 §6  5회

전부 **결정 문서가 맞고 원장이 낡아** 있었다. 원장은 「근거는 안 변한다」는 암묵적 가정 아래
방치됐는데, **근거는 안 변해도 「무엇이 끝났는가」는 변한다.**

⚠⚠ **이 두 문서는 gitignore 안에 있다**(`design/guild/*` + `!design/guild/tools/`). 그래서
CI 나 새 클론에서는 **파일이 없다.** 없을 때 조용히 통과하면 그거야말로 이 작업이 다섯 번
만든 「발화할 수 없는 검사」다. 그래서 구조를 이렇게 나눴다:

  · 검사 **로직**은 이 파일의 순수 함수들이고, `analyze_tool_test.sh` 가 **합성 픽스처**로
    돌린다 — 문서가 없어도 로직은 항상 검사된다.
  · 실제 문서 대조는 `--docs <dir>` 로 돌리며, 문서가 없으면 **exit 2 와 명시적 메시지**를
    낸다(0 이 아니다 — 「통과」로 읽히면 안 된다).

사용: `python3 doc_consistency.py --docs design/guild [--tests plugins/guild-plugin/tests]`
"""
import glob
import os
import re
import subprocess
import sys

_SECTION = re.compile(r"^## (\d+)\. ", re.M)
_SUITE_COUNT = re.compile(r"\*\*(\d+)\s*(?:개)?\s*스위트\*\*|\*\*(\d+)개\*\* 스위트|(\d+)개 스위트")
# ⚠ **정확히 7자리만** 커밋으로 본다. 이 문서들은 커밋을 git 기본 축약(7자리)으로 인용하고,
#    8자리 16진은 **세션 UUID 앞부분**(`9b1ef612`·`9e91e361`)이라 오검출이 난다 — 실측.
_RETRACT_ROW = re.compile(r"^\| `([^`]+)` \| \*\*([^*]+)\*\* \|", re.M)
# 철회 표식 — 이 중 하나라도 같은 줄에 있으면 「과거를 인용한 것」으로 인정한다.
# ⚠ 철회 표식 — 하나라도 같은 줄에 있으면 「과거를 인용한 것」으로 인정한다.
#    아래 넷은 **실측 오검출에서 추가**했다: 「초과분」(§3.1c 의 초과분 기록 블록) ·
#    「틀렸」(«0.7087 은 이 절이 스스로 틀렸다고 선언한 모델의 값이다») ·
#    「임시 스크립트」(도구 이전 값을 밝히는 문장) · 「직후」(«구현 직후 이 표는 …»).
# ⚠⚠ **표식을 붙여 현재 주장을 숨기는 것은 이 규칙의 악용이다** — 그러라고 만든 통로가 아니다.
_RETRACT_MARK = ("~~", "정정", "철회", "유령", "초안", "라운드", "이전", "당시", "폐기",
                 "초과분", "틀렸", "임시 스크립트", "직후")


def retracted_values(plan):
    """§10b 「폐기된 수치」 표에서 (폐기값, 대체값) 쌍을 읽는다."""
    if "## 10b." not in plan:
        return []
    body = plan[plan.index("## 10b."):]
    body = body[:body.index("\n## ") if "\n## " in body else len(body)]
    return [(m.group(1), m.group(2)) for m in _RETRACT_ROW.finditer(body)]


def retraction_violations(plan):
    """폐기값이 **철회 표식 없는 줄**에 나타나면 위반이다.

    ⚠ 이 작업에서 **세 번** 일어난 클래스다 — 자기 문서가 철회한 수를 다른 절이 현행으로
    인용하는 것(0.7087 · 4.0배 · +41.7~49.5%). 셋 다 결론을 바꾸는 자리였다.
    """
    pairs = retracted_values(plan)
    if not pairs:
        return ["§10b 「폐기된 수치」 표가 없다"]
    bad = []
    in_10b = False
    for line in plan.split("\n"):
        if line.startswith("## "):
            in_10b = line.startswith("## 10b.")
        if in_10b:
            continue
        if any(k in line for k in _RETRACT_MARK):
            continue
        for old, new in pairs:
            if old in line:
                bad.append("폐기값 `%s`(→ %s)를 철회 표식 없이 인용: %s"
                           % (old, new, line.strip()[:60]))
    return bad


_HASH = re.compile(r"`([0-9a-f]{7})(?![0-9a-f…])")
_PLAN_LINES = re.compile(r"`08-plan\.md`\(\*?\*?([\d,]+)줄\*?\*?\)")


def plan_line_claim(decisions):
    """결정 문서가 주장하는 원장 줄 수. 없으면 None.

    ⚠ 이 수는 **두 번 낡았다**(라운드 7: 951 → 1,051, 라운드 24: 1,051 → 1,866).
    라운드마다 손으로 갱신해야 하는 수는 반드시 낡으므로 기계가 본다.
    """
    m = _PLAN_LINES.search(decisions)
    return int(m.group(1).replace(",", "")) if m else None


def section_gaps(text):
    """`## N.` 최상위 절 번호의 **결번**을 돌려준다.

    ⚠ 라운드 15 에서 플랜이 §10 다음에 바로 §12 로 뛰고 있었다. 신규 독자는 §11 을 찾다가
    없다는 것을 알게 되는데, 그때 「문서가 잘렸나」와 「번호만 빈 건가」를 구별할 수 없다.
    """
    nums = sorted({int(m.group(1)) for m in _SECTION.finditer(text)})
    if not nums:
        return []
    return [n for n in range(nums[0], nums[-1] + 1) if n not in nums]


_HISTORICAL = ("초안", "라운드")


def _strip_historical(text):
    """제목에 「초안」 또는 「라운드」가 들어간 절을 **덜어낸다**.

    ⚠ 이 문서들은 낡은 표를 지우지 않고 «초안의 표 (비교용으로 남긴다)» 로 보존하고, §12 의
    «라운드 N» 절들은 **무엇이 어떻게 틀렸었는지**를 그대로 인용한다 — 둘 다 그 안의 수가
    **당시 값이라 맞는 것**이다. 현재 값과 대조하면 안 된다. 보존 규율과 정합 검사가 충돌하는
    지점이고 여기서 화해시킨다.

    ⚠⚠ **대가를 명시한다**: 라운드 기록 **안의** 진짜 오류는 이 검사가 못 잡는다. 라운드
    기록은 구성상 과거 서술이므로 감수하지만, **「라운드」를 제목에 넣어 현재 주장을 숨기는
    것**은 이 규칙의 악용이다 — 그러라고 만든 통로가 아니다.
    """
    out, skip_at = [], None
    for line in text.split("\n"):
        if line.startswith("#"):
            lvl = len(line) - len(line.lstrip("#"))
            # ⚠ **더 깊은 제목은 절을 끝내지 않는다.** 처음 구현은 `#` 로 시작하는 모든 줄에서
            #    스킵을 풀었고, 그래서 «### 12.17 라운드 19» 안의 «#### …» 하위 제목이 스킵을
            #    해제해 라운드 기록 본문이 다시 대조 대상이 됐다(실측 — 이 파일의 첫 실행에서
            #    바로 드러났다).
            if skip_at is not None and lvl > skip_at:
                pass
            elif any(k in line for k in _HISTORICAL):
                skip_at = lvl
            else:
                skip_at = None
        if skip_at is None:
            out.append(line)
    return "\n".join(out)


def suite_counts(text):
    """「N개 스위트」류 표기를 전부 뽑는다 — 두 문서와 실제 파일 수가 같아야 한다."""
    out = []
    for m in _SUITE_COUNT.finditer(_strip_historical(text)):
        out.append(int(next(g for g in m.groups() if g)))
    return sorted(set(out))


def cited_hashes(text):
    """백틱 안의 7~40자리 16진 토큰. 커밋 해시 후보다."""
    return sorted({m.group(1) for m in _HASH.finditer(text)})


def unknown_hashes(hashes, repo="."):
    """실제로 존재하지 않는 커밋 해시만 돌려준다.

    ⚠ 16진처럼 보이는 것이 전부 커밋은 아니다(`fileKey`, sha256 조각 …). 그래서 **존재하지
    않는다** 는 것만으로 실패시키지 않고, 호출부가 길이 7~8 인 것에 한정해 쓴다 — 그 길이는
    이 문서들에서 커밋을 가리키는 관용이다.
    """
    bad = []
    for h in hashes:
        r = subprocess.run(["git", "-C", repo, "cat-file", "-t", h],
                           capture_output=True, text=True)
        if r.returncode != 0 or r.stdout.strip() != "commit":
            bad.append(h)
    return bad


def check(plan, decisions, n_suites, repo="."):
    """두 문서 + 실제 스위트 수를 받아 **문제 목록**을 돌려준다. 빈 리스트 = 정합."""
    problems = []

    gaps = section_gaps(plan)
    if gaps:
        problems.append("플랜 절 번호 결번: " + ", ".join("§%d" % g for g in gaps))

    for name, text in (("플랜", plan), ("결정문서", decisions)):
        counts = suite_counts(text)
        wrong = [c for c in counts if c != n_suites]
        if wrong:
            problems.append("%s 의 스위트 개수 표기 %s — 실제 %d"
                            % (name, wrong, n_suites))

    # 원장이 「규율의 정본은 결정 문서」임을 명시하는가
    if "정본은 `08-decisions.md` §6" not in plan:
        problems.append("플랜 §10 이 규율의 정본(결정 문서 §6)을 가리키지 않는다")

    problems += retraction_violations(_strip_historical(plan))

    claim = plan_line_claim(decisions)
    if claim is None:
        problems.append("결정 문서가 원장 줄 수를 밝히지 않는다")
    else:
        actual = len(plan.split("\n"))
        # ⚠ ±2% 허용 — 한 줄 고칠 때마다 갱신을 요구하면 규칙이 지켜지지 않는다.
        if abs(claim - actual) > max(20, actual * 0.02):
            problems.append("결정 문서의 원장 줄 수 %d 이 실제 %d 과 어긋난다" % (claim, actual))

    for name, text in (("플랜", plan), ("결정문서", decisions)):
        short = [h for h in cited_hashes(text) if 7 <= len(h) <= 8]
        bad = unknown_hashes(short, repo)
        if bad:
            problems.append("%s 가 존재하지 않는 커밋을 인용: %s" % (name, ", ".join(bad)))

    return problems


def main():
    if "--docs" not in sys.argv:
        print(__doc__)
        return 2
    d = sys.argv[sys.argv.index("--docs") + 1]
    tests = "plugins/guild-plugin/tests"
    if "--tests" in sys.argv:
        tests = sys.argv[sys.argv.index("--tests") + 1]
    pp, dp = os.path.join(d, "08-plan.md"), os.path.join(d, "08-decisions.md")
    if not (os.path.exists(pp) and os.path.exists(dp)):
        print("문서가 없다 (gitignore 안이다): %s\n"
              "→ 이 실행은 **통과가 아니라 미실행**이다. exit 2." % d, file=sys.stderr)
        return 2
    n = len(glob.glob(os.path.join(tests, "*_test.sh")))
    probs = check(open(pp, encoding="utf-8").read(),
                  open(dp, encoding="utf-8").read(), n)
    if not probs:
        print("정합 OK (스위트 %d개 기준)" % n)
        return 0
    for p in probs:
        print("불일치: " + p)
    return 1


if __name__ == "__main__":
    sys.exit(main())
