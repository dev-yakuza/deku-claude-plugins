#!/usr/bin/env bash
# Structural checks over the 16 role-persona templates in skills/gld/templates/agents/.
#
# WHY THIS FILE EXISTS. `/gld update` never touched `.claude/agents/*` — INV4 declared the
# whole file LOCAL-owned because there was no line to cut along: central template text and
# locally-grown text sat mixed together. The persona-merge design draws that line with a
# marker pair, exactly the way `CLAUDE.md` is already merged:
#
#     ---                                   frontmatter  (name/description = central keys)
#     # <Role> — {{PROJECT_NAME}}           H1           (local — one line, two owners)
#                                           (blank)
#     <!-- guild:persona:start -->          ┐
#     …central body…                        │ update replaces exactly this
#     <!-- guild:persona:end -->            ┘
#
#     ## 프로젝트 특화                       local, stays put
#     ## 역할 습관                           local, evolve grows it
#     <!-- guild:persona:habits -->
#
# Every machine check downstream (update's marker-region replacement, the migration anchor,
# evolve's boundary gate) keys on this shape. If a template drifts out of it, those checks
# do not fail loudly — they mis-target. Case 2 is the sharpest: a `{{PLACEHOLDER}}` between
# the markers would be copied verbatim into a repo by `update`, because the central region
# is replaced WITHOUT a fill step. That is only safe while the region has no placeholders.
#
# Usage: bash plugins/guild-plugin/tests/persona_structure_test.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
AGENTS="$HERE/../skills/gld/templates/agents"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s (expected %s, got %s)\n' "$1" "$2" "$3"; }

# Interpreter, by name and FUNCTIONALLY probed — an interpreter that exists but cannot run
# (broken venv, a shim that exits non-zero) would otherwise report as structural drift with
# an empty diagnostic. Same reasoning as prompt_structure_test.sh.
PY="${PY:-python3}"
"$PY" -c "pass" >/dev/null 2>&1 || { echo "SKIP: $PY is not usable — this suite is python-based" >&2; exit 0; }

[ -d "$AGENTS" ] || { echo "FAIL  템플릿 디렉터리를 찾을 수 없습니다: $AGENTS"; exit 1; }

echo ""
echo "== 페르소나 템플릿 골격 =="

# The whole suite is one python pass per file: cases 3/4/5/6 are POSITION comparisons, and
# expressing them in shell would mean re-deriving line numbers per check with grep -n | cut,
# which is where an off-by-one hides. Python returns one `CASE<n> ok|<detail>` line per case
# and the shell scores them, so a python-side crash surfaces as missing lines, not as green.
RESULT="$("$PY" - "$AGENTS" <<'PYX'
import os, re, sys

AGENTS = sys.argv[1]
OPEN, END, HABITS = ("<!-- guild:persona:start -->",
                     "<!-- guild:persona:end -->",
                     "<!-- guild:persona:habits -->")
ANCHOR = "## 프로젝트 특화"

def only(lines, pred):
    return [i for i, l in enumerate(lines, 1) if pred(l)]

for name in sorted(f for f in os.listdir(AGENTS) if f.endswith(".md")):
    lines = open(os.path.join(AGENTS, name), encoding="utf-8").read().split("\n")
    o = only(lines, lambda l: l.strip() == OPEN)
    e = only(lines, lambda l: l.strip() == END)
    h = only(lines, lambda l: l.strip() == HABITS)
    heads2 = only(lines, lambda l: l.startswith("## "))
    h1 = only(lines, lambda l: l.startswith("# "))
    anc = only(lines, lambda l: l.startswith(ANCHOR))
    fence = only(lines, lambda l: l.rstrip() == "---")

    # 1 — three markers, one each, in order.
    if len(o) == len(e) == len(h) == 1 and o[0] < e[0] < h[0]:
        print(f"{name}\tCASE1\tok")
    else:
        print(f"{name}\tCASE1\tstart={len(o)} end={len(e)} habits={len(h)} "
              f"pos={o or '-'}/{e or '-'}/{h or '-'}")

    # 2 — no {{placeholder}} between the markers. update replaces this region with no fill.
    if len(o) == 1 and len(e) == 1:
        inner = lines[o[0]:e[0] - 1]
        found = [l for l in inner if "{{" in l]
        print(f"{name}\tCASE2\t" + ("ok" if not found else f"{len(found)} placeholders: {found[0][:40]}"))
    else:
        print(f"{name}\tCASE2\tskipped — markers malformed")

    # 3 — exactly two `## ` headings below persona:end (project-specialization + role-habits).
    #     Counted, not named: the headings are localized by init, the markers never are.
    if len(e) == 1:
        below = [n for n in heads2 if n > e[0]]
        print(f"{name}\tCASE3\t" + ("ok" if len(below) == 2 else f"{len(below)} headings below end"))
    else:
        print(f"{name}\tCASE3\tskipped — end marker malformed")

    # 4 — the later of those two sits immediately above the habits marker.
    if len(e) == 1 and len(h) == 1:
        below = [n for n in heads2 if n > e[0]]
        print(f"{name}\tCASE4\t" + ("ok" if len(below) == 2 and below[1] == h[0] - 1
                                    else f"habits at {h[0]}, heading above it at {below[1] if len(below) == 2 else '-'}"))
    else:
        print(f"{name}\tCASE4\tskipped — markers malformed")

    # 5 — anchor exactly once, H1 exactly once, H1 above the anchor. This is the migration
    #     guard (§7.4a) asserted on the template side: if it does not hold here it cannot
    #     hold in a repo that init rendered from here.
    if len(anc) == 1 and len(h1) == 1 and h1[0] < anc[0]:
        print(f"{name}\tCASE5\tok")
    else:
        print(f"{name}\tCASE5\tanchor={len(anc)} h1={len(h1)} order={h1[0] < anc[0] if (anc and h1) else '-'}")

    # 6 — persona:start sits below the closing frontmatter fence AND below the H1.
    #     Without this a start marker placed above the frontmatter passes 1/2/3/4/5 and then
    #     update replaces the YAML fence with body text — the sub-agent stops registering.
    if len(o) == 1 and len(h1) == 1 and len(fence) >= 2:
        print(f"{name}\tCASE6\t" + ("ok" if o[0] > fence[1] and o[0] > h1[0]
                                    else f"start={o[0]} fence2={fence[1]} h1={h1[0]}"))
    else:
        print(f"{name}\tCASE6\tstart={len(o)} h1={len(h1)} fences={len(fence)}")
PYX
)" || { echo "FAIL  구조 검사 스크립트가 실행되지 않았습니다"; exit 1; }

while IFS=$'\t' read -r file case detail; do
  [ -z "${file:-}" ] && continue
  if [ "$detail" = "ok" ]; then ok "$file $case"; else bad "$file $case" "ok" "$detail"; fi
done <<< "$RESULT"

echo ""
echo "  PASS=$PASS FAIL=$FAIL"

# ⚠ A FLOOR ON THE CHECK COUNT. The python block above emits one line per case; if it dies
# partway (or the heredoc is broken by an edit) the `while` loop simply reads fewer lines and
# the suite reports FAIL=0 over checks that never ran — "green over a hole", the exact shape
# this file exists to prevent. 16 templates x 6 cases = 96.
MIN_CHECKS=96
if [ "$((PASS + FAIL))" -lt "$MIN_CHECKS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 $MIN_CHECKS건) —"
  echo "      python 블록이 도중에 죽었거나 템플릿 수가 줄었을 가능성이 큽니다."
  exit 1
fi
[ "$FAIL" -eq 0 ]
