#!/usr/bin/env bash
# Structural checks over the prompt Markdown in skills/gld/.
#
# Test 2 — calibration-core identity. The external auditor is spawned from two places:
# `commands/atoms/_execute_spine.md` Step 3.5a (pre-PR) and `commands/review.md` Step 2.5
# (post-PR). The two prompts are deliberately duplicated, not shared, and the spine states
# the contract: they must stay "calibrated identically". The severity/axis definitions are
# fenced in both copies by `<!-- guild:severity-core -->` … `<!-- /guild:severity-core -->`
# so a drift in one copy is caught here instead of showing up as a systematic offset in the
# severity distribution the two stages are supposed to be comparable across.
#
# Each core line carries the enclosing blockquote's `  > ` prefix; the comparison strips
# that prefix and trailing whitespace, so re-wrapping the blockquote does not fail the test
# but changing a word does. The stage-consequence line is deliberately OUTSIDE the markers —
# it is the one intended difference between the copies.
#
# Usage: bash plugins/guild-plugin/tests/prompt_structure_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
GLD="${1:-$HERE/../skills/gld}"
[ -d "$GLD" ] || { echo "missing: $GLD" >&2; exit 1; }
SPINE="$GLD/commands/atoms/_execute_spine.md"
REVIEW="$GLD/commands/review.md"
for f in "$SPINE" "$REVIEW"; do
  [ -f "$f" ] || { echo "missing: $f" >&2; exit 1; }
done
PASS=0; FAIL=0

# ── 환경 격리 (라운드 5) ──────────────────────────────────────────────────
# ⚠ `GIT_DIR`/`GIT_WORK_TREE` are ALWAYS exported inside a git hook — and this plugin installs
# hooks. Leaving them set made every `git -C <tmp>` in this file operate on the caller's repo:
# 16 of 19 cases failed with messages blaming the gate (measured). `GIT_INDEX_FILE` and
# `GIT_CONFIG_*` do the same for staging and config.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
unset GIT_CONFIG GIT_CONFIG_COUNT
# ⚠ Interpreter, once and by name. Hardcoding `python3` made "no python3 on PATH" report as
# THREE structural drift failures with an empty diagnostic — the same shape as the `$PY`
# undefined defect this suite already had once.
PY="${PY:-python3}"
# A FUNCTIONAL probe, not `command -v`: an interpreter that exists but cannot run
# (a broken venv, a shim that exits non-zero) produced five confusing structural
# failures with empty diagnostics — measured.
# ⚠ 스킵은 통과가 아니다. 이 줄이 `exit 0` 이던 동안, python3 가 없는 컨테이너에서는
# 스위트 전체가 **검사 0건으로 성공을 보고**했다 — 0eb3e7e 가 스위트 *안* 의 SKIP 에 대해
# 고친 것과 똑같은 결함이 스위트 *자체* 에 남아 있었다. 의도적으로 건너뛰려면
# GLD_ALLOW_SKIP=1 을 명시한다.
gld_skip() { echo "SKIP: $1" >&2; [ "${GLD_ALLOW_SKIP:-0}" = 1 ] && exit 0; \
            echo "FAIL  스킵은 통과가 아닙니다 — GLD_ALLOW_SKIP=1 로 명시하십시오." >&2; exit 1; }
"$PY" -c "pass" >/dev/null 2>&1 || gld_skip "$PY is not usable — this suite is python-based"
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s (expected %s, got %s)\n' "$1" "$2" "$3"; }

echo ""
echo "== 2. 감사자 캘리브레이션 코어 동일성 =="

OUT="$("$PY" - "$SPINE" "$REVIEW" <<'PYX'
import re, sys

OPEN  = '<!-- guild:severity-core -->'
CLOSE = '<!-- /guild:severity-core -->'
PREFIX = re.compile(r'^  > ?')

def is_marker(line, marker):
    # Match only a line that IS the marker (after the "  > " prompt-quote prefix).
    # A prose mention of the marker name is legitimate — review.md Step 4 cites it
    # when it tells the leader to grade scrutiny notes through the same core — and
    # counting that as a second opening marker aborted this whole check, which is
    # how the two cores went unverified while the suite still reported a pass.
    return PREFIX.sub('', line).strip() == marker


def extract(path):
    """Return (opens, closes, core_lines_or_None) for one file."""
    lines = open(path, encoding='utf-8').read().split('\n')
    opens  = [i for i, l in enumerate(lines) if is_marker(l, OPEN)]
    closes = [i for i, l in enumerate(lines) if is_marker(l, CLOSE)]
    if len(opens) != 1 or len(closes) != 1:
        return opens, closes, None
    if closes[0] < opens[0]:
        return opens, closes, None
    body = lines[opens[0] + 1:closes[0]]
    return opens, closes, [PREFIX.sub('', l).rstrip() for l in body]

results = {}
for path in sys.argv[1:3]:
    results[path] = extract(path)

# marker pairs: 0 or 1 per file, and never a lone marker
for path, (opens, closes, core) in results.items():
    n_open, n_close = len(opens), len(closes)
    if n_open > 1 or n_close > 1:
        print('MARKERS_FAIL %s open=%d close=%d' % (path, n_open, n_close))
        raise SystemExit
    if n_open != n_close:
        print('MARKERS_FAIL %s open=%d close=%d' % (path, n_open, n_close))
        raise SystemExit
    if n_open == 1 and core is None:
        print('MARKERS_FAIL %s close-before-open' % path)
        raise SystemExit
print('MARKERS_OK')

spine, review = sys.argv[1], sys.argv[2]
sc = results[spine][2]
rc = results[review][2]

if sc is None and rc is None:
    # Neither copy carries the core yet — the pre-D3a state. Nothing to compare.
    print('CORE_ABSENT')
    raise SystemExit
if sc is None or rc is None:
    print('CORE_ONE_SIDED %s' % ('review only' if sc is None else 'spine only'))
    raise SystemExit
if not sc:
    print('CORE_EMPTY')
    raise SystemExit
if sc == rc:
    print('CORE_IDENTICAL %d' % len(sc))
    raise SystemExit

print('CORE_DIFFERS')
import difflib
for d in list(difflib.unified_diff(sc, rc, 'spine', 'review', lineterm='', n=1))[:24]:
    print('  ' + d)
PYX
)"

case "$OUT" in
  *MARKERS_OK*) ok "마커 쌍이 파일당 0개 또는 1개" ;;
  *)            bad "마커 쌍이 파일당 0개 또는 1개" "0 or 1 pair" "$(printf '%s' "$OUT" | tr '\n' ' ')" ;;
esac

case "$OUT" in
  *CORE_IDENTICAL*) ok "두 사본의 코어가 바이트 동일 ($(printf '%s' "$OUT" | sed -n 's/.*CORE_IDENTICAL \([0-9]*\).*/\1/p')줄)" ;;
  *CORE_ABSENT*)    ok "두 사본 모두 코어 없음 (도입 전 상태)" ;;
  *MARKERS_FAIL*)   : ;;
  *)                bad "두 사본의 코어가 바이트 동일" "identical cores" "$(printf '%s' "$OUT" | tr '\n' ' ')" ;;
esac

echo ""
echo "== 3. sprint 서브커맨드 집합의 정합성 =="
# The router's table, the files on disk, and the claims other files make about them drifted
# twice during development: `retro` was documented as shipping "in a later version" in five
# places at once, and `status.md` grew a render rule for a field its own jq did not produce.
# A router row with no file is a dead command; a file with no row is unreachable.
#
# ⚠ Python helpers are written to temp FILES. A heredoc inside `$( … )` is mis-parsed by bash
# whenever the body contains a backtick — and these checks match on Markdown backticks. That
# is the same trap `_sprint_dag.md` Section F documents, and it bit this file too.

WORK3="$(mktemp -d)" || { echo "mktemp -d failed" >&2; exit 1; }
[ -n "$WORK3" ] && [ -d "$WORK3" ] || { echo "mktemp -d gave no directory" >&2; exit 1; }
trap 'rm -rf "$WORK3"' EXIT

SPRINT_ROUTER="$GLD/commands/sprint.md"
SPRINT_DIR="$GLD/commands/sprint"
RETRO="$SPRINT_DIR/retro.md"
HANDOFF="$GLD/commands/atoms/_handoff.md"
TPL="$GLD/templates/sprint-supervisor.sh"
DAILY="$SPRINT_DIR/daily.md"

if [ ! -f "$SPRINT_ROUTER" ]; then
  echo "  SKIP  sprint 라우터 없음 (도입 전 상태)"
else

cat > "$WORK3/router.py" <<'ROUTERPY'
import os, re, sys
router, d = sys.argv[1], sys.argv[2]
src = open(router, encoding="utf-8").read()

# ⚠ Anchor on the ROUTING TABLE, strip markup properly, and compare the NAME against the PATH.
# Three measured defects in the earlier one-line regex: a single `.` before the name ate the
# first character of an unquoted cell (`| plan |` routed `lan`) and matched nothing at all for a
# bold cell; any row containing `commands/sprint/` counted as a route, so a token-reference table
# reported `plan-hash` as a dead route; and the name and the path were never compared, so rows
# pointing at each other's files passed.
m = re.search(r"^\|[^\n]*\|[^\n]*Action[^\n]*\|\s*$", src, re.M)
if not m:
    print("no routing table (a header row containing `Action`) found"); raise SystemExit(0)
rows, seen_sep = [], False
# ⚠ From the line AFTER the header. `src[m.end():].splitlines()` starts with the empty remainder
# of the header's own line, which does not begin with "|", so the loop broke immediately and
# every file looked like an orphan (measured).
for line in src[m.end():].lstrip("\n").splitlines():
    if not line.startswith("|"):
        break
    if not seen_sep and re.match(r"^\|[\s:|-]+\|\s*$", line):
        seen_sep = True; continue
    rows.append(line)

def strip_markup(cell):
    return re.sub(r"[`*_\s]", "", cell)

routes, problems = {}, []
for line in rows:
    cells = line.strip().strip("|").split("|")
    if len(cells) < 2:
        continue
    name = strip_markup(cells[0])
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name or ""):
        continue                                  # *(empty)*, a number list, `--readiness`, …
    paths = re.findall(r"commands/sprint/([A-Za-z0-9_-]+)\.md", "|".join(cells[1:]))
    if not paths:
        continue
    routes[name] = paths[0]

files = {f[:-3] for f in os.listdir(d) if f.endswith(".md")} if os.path.isdir(d) else set()
for name, target in sorted(routes.items()):
    if target not in files:
        problems.append("router routes `%s` at commands/sprint/%s.md, which does not exist" % (name, target))
    elif name != target:
        problems.append("router routes `%s` at commands/sprint/%s.md — name and file disagree" % (name, target))
for orphan in sorted(files - set(routes)):
    problems.append("commands/sprint/%s.md exists but the router never routes to it" % orphan)
print("OK %d subcommands" % len(routes) if not problems else "; ".join(problems))
ROUTERPY
OUT3="$("$PY" "$WORK3/router.py" "$SPRINT_ROUTER" "$SPRINT_DIR")"
case "$OUT3" in
  OK*) ok "라우터 표와 파일이 정확히 대응 ($OUT3)" ;;
  *)   bad "라우터 표와 파일이 정확히 대응" "one file per row" "$OUT3" ;;
esac

# A command that exists must not be advertised as unavailable. ⚠ Scoped to the sprint surface:
# `$GLD` was the whole plugin, which made "later version" a repo-wide banned English phrase —
# an unrelated command legitimately describing its own roadmap failed this check (measured).
STALE="$(grep -l 'later version' "$SPRINT_ROUTER" "$SPRINT_DIR"/*.md "$GLD/commands/help.md" "$GLD/SKILL.md" 2>/dev/null | xargs -I{} sh -c 'grep -q "sprint" {} && echo {}' 2>/dev/null || true)"
if [ -z "$STALE" ]; then
  ok "구현된 서브커맨드를 '추후 버전'으로 안내하는 곳이 없음"
else
  bad "구현된 서브커맨드를 '추후 버전'으로 안내하는 곳이 없음" "none" "$(printf '%s' "$STALE" | tr '\n' ' ')"
fi

if [ -f "$RETRO" ]; then
  # retro closes the tracking Issue and _handoff.md forbids closing Issues. The two MUST be a
  # matched pair — the rule naming its exception, and retro citing the rule.
  if ! grep -q 'gh issue close' "$RETRO"; then
    bad "retro가 추적 이슈를 닫는다" "gh issue close" "absent — the sprint could never be closed"
  elif "$PY" - "$HANDOFF" <<'EXCPY'
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
# ⚠ Judge inside the ROW that states the rule. Two bare greps over the whole file were satisfied
# by unrelated marker-table rows, so deleting the exception paragraph entirely still passed
# (measured).
rows = [l for l in src.splitlines() if "closes a" in l and "Issue" in l]
ok = any(("sprint retro" in r or "sprint/retro" in r) and "tracking Issue" in r for r in rows)
raise SystemExit(0 if ok else 1)
EXCPY
  then
    ok "retro가 추적 이슈를 닫고, _handoff.md의 그 규칙 행이 예외를 명시한다"
  else
    bad "retro가 추적 이슈를 닫고, _handoff.md의 규칙 행이 예외를 명시한다" \
        "the exception is named in the rule's own row" "the rule row still forbids it outright"
  fi

  # design §10.3: evolve is called with NO arguments. `--dry-run` would suppress the growth,
  # `--apply` would skip past the per-item approval gate (INV1). ⚠ Checking only the LINE that
  # names evolve.md was bypassable: putting the argument in the next paragraph reads as the same
  # instruction to an LLM and passed (measured). Scan the whole section that invokes it.
  cat > "$WORK3/evolvearg.py" <<'EVOLVEPY'
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
if "commands/evolve.md" not in src:
    print("MISSING retro.md never invokes commands/evolve.md"); raise SystemExit(0)
# ⚠ Judge the INVOCATION, not the appearance of a flag name. Two measured defects: writing down
# WHY the flags are not passed ("not `--apply` … and not `--dry-run`") failed the check, so
# documenting the rule broke it; and splitting on `## ` alone made the whole check vacuous when
# a heading was demoted to `###`.
bad, invocations = [], 0
for m in re.finditer(r"commands/evolve\.md", src):
    near = src[max(0, m.start() - 150):m.end() + 150]
    # ⚠ Only an INVOCATION counts. The header blockquote lists evolve.md as a pointer, and
    # measuring 400 characters from THAT picked up Phase 0's own `$1 == --dry-run` declaration
    # (measured) — a flag of retro's, nothing to do with evolve.
    if not re.search(r"\bexecute\b", near):
        continue
    invocations += 1
    seg = src[max(0, m.start() - 200):m.end() + 300]
    for flag in ("--apply", "--dry-run"):
        for fm in re.finditer(re.escape(flag), seg):
            ctx = seg[max(0, fm.start() - 60):fm.start()]
            if re.search(r"\b(not|never|no|without|instead of|do not|don't)\b|passing nothing", ctx, re.I):
                continue          # a prohibition, which is what this rule wants stated
            bad.append("%s appears at the evolve invocation without a negation" % flag)
if invocations == 0:
    bad.append("commands/evolve.md is mentioned but never invoked (no `execute` nearby)")
print("OK" if not bad else "; ".join(sorted(set(bad))))
EVOLVEPY
  EA="$("$PY" "$WORK3/evolvearg.py" "$RETRO")"
  if [ "$EA" = "OK" ]; then
    ok "retro가 evolve를 인자 없이 호출한다 (그 절 전체에 인자 언급 없음)"
  else
    bad "retro가 evolve를 인자 없이 호출한다" "no arguments in that section" "$EA"
  fi
fi
fi

echo ""
echo "== 4. 실패 분류 어휘 — 문서가 코드보다 크게 말하지 않는가 =="
# `daily.md` once enumerated 8 classes while the supervisor wrote 4, and `retro` now COUNTS
# them. The list is a machine-token contract (`_handoff.md` Section K), so drift here silently
# makes a documented reason unreachable — and a reason nobody can reach reads as "never happened".
if [ -f "$TPL" ] && [ -f "$DAILY" ]; then
cat > "$WORK3/classes.py" <<'CLASSPY'
import re, sys
tpl = open(sys.argv[1], encoding="utf-8").read()
daily = open(sys.argv[2], encoding="utf-8").read()

# ── code side ────────────────────────────────────────────────────────────────
# Join line continuations first, then allow the class to be quoted and to have no hyphen.
# Measured: `record_failure "$ISSUE" "new-class"`, `… timeout` (no hyphen) and a `\`-wrapped
# call each slipped past the earlier pattern, so a new class could be added with no doc entry.
# Comments mention the function names in prose ("record_event — append one line"), so they
# must go first or the prose words are read as class names.
body = "\n".join(l for l in tpl.splitlines() if not l.strip().startswith("#"))
flat = re.sub(r"\\\n\s*", " ", body)
code = set()
for m in re.finditer(r"record_(?:event|failure)\s+\"?\$\{?\w+\}?\"?\s+(\"?)([a-z][a-z0-9_-]*)\1", flat):
    code.add(m.group(2))

# ── doc side ─────────────────────────────────────────────────────────────────
# Anchored on the CLASS TABLE, not on keywords: a row whose verdict wording changes must not
# silently drop out of the comparison. The surrounding prose also discusses `state` values,
# which share the shape (`installing-deps`), so the table boundary is what separates them.
lines = daily.splitlines()
# ⚠ The header anchor tolerates a translated first cell, and only the FIRST cell of each row is
# read. Two measured defects: hardcoding `| class | 실패인가? |` broke when the header was
# localized, and scanning the whole row read a backticked word in the VERDICT cell as a class.
hdr = next((i for i, l in enumerate(lines)
            if l.startswith("|") and ("실패인가" in l or "failure?" in l.lower())), None)
if hdr is None:
    print("ERR daily.md has no class table (a header row asking whether each class is a failure)")
    raise SystemExit(0)
docd = set()
for l in lines[hdr + 2:]:
    if not l.startswith("|"):
        break
    first = l.strip().strip("|").split("|")[0]
    docd.update(re.findall(r"[`]([a-z][a-z0-9_-]*)[`]", first))
missing = sorted(c for c in code if c not in docd)
extra = sorted(c for c in docd if c not in code)
out = []
if missing:
    out.append("the code records but daily.md never names: " + ", ".join(missing))
if extra:
    out.append("daily.md names but the code never records: " + ", ".join(extra))
print("OK %d classes" % len(code) if not out else "; ".join(out))
CLASSPY
OUT4="$("$PY" "$WORK3/classes.py" "$TPL" "$DAILY")"
case "$OUT4" in
  OK*) ok "daily.md의 분류 목록이 감독자가 실제로 쓰는 것과 일치 ($OUT4)" ;;
  *)   bad "daily.md의 분류 목록이 감독자와 일치" "the same set" "$OUT4" ;;
esac
fi

echo ""
echo "== 5. 보드 투영 — 프롬프트가 설계와 같은 것을 말하는가 (03-sprint-board.md §9.2) =="

# ⚠ 여기의 검사는 전부 **철자**다. 동작은 tests/board_write_test.sh 와
# tests/sprint_supervisor_test.sh §I 가 잡는다 — 02번 §23.7 이 값을 치른 구별이다.
# 철자 검사만으로 지킬 수 있는 것은 "설계가 철회한 규칙이 프롬프트에 되살아나지 않는 것"뿐이다.
PLAN="$GLD/commands/sprint/plan.md"
BOARD="$GLD/commands/sprint/board.md"
RUNMD2="$GLD/commands/sprint/run.md"

hasfx() {   # hasfx <case> <file> <fixed-string>   — prose OR code; comments count
  if [ -f "$2" ] && grep -qF -- "$3" "$2"; then ok "$1"; else bad "$1" "present" "not found: $3"; fi
}

# ⚠ For the SUPERVISOR TEMPLATE, `hasfx` is not enough — it is a shell script, and a mutation
# that turns a wired call into `: # ledger_set board_off_reason` satisfies a fixed-string grep.
# That happened: the `board_off_reason` mutation survived the whole suite. This variant looks
# only at the part of each line BEFORE the first `#`, the same rule
# `sprint_supervisor_test.sh`'s `hasline` uses. A leading-`#` test is NOT sufficient — the
# surviving mutation was `: # …`, which does not start with `#`.
hascode() {  # hascode <case> <file> <fixed-string>   — must appear as CODE, not in a comment
  if awk -v t="$3" '{ i=index($0,"#"); pre=(i?substr($0,1,i-1):$0);
                      if (index(pre,t)) { found=1; exit } }
                    END { exit !found }' "$2"; then
    ok "$1"
  elif grep -qF -- "$3" "$2"; then
    bad "$1" "as code" "found ONLY inside a comment: $3"
  else
    bad "$1" "as code" "not found: $3"
  fi
}
# ⚠ A MISSING FILE IS A BROKEN PROBE, NOT A CLEAN FILE. The first version fell into `ok` when
# `$2` did not exist, so a renamed or mistyped path read as "the forbidden string is absent".
lacksfx() { # lacksfx <case> <file> <fixed-string>
  if [ ! -f "$2" ]; then bad "$1" "the file to exist" "no such file: $2"; return; fi
  if [ -f "$2" ] && grep -qF -- "$3" "$2"; then bad "$1" "absent" "found: $3"; else ok "$1"; fi
}

# 1. 판정 대상이 배포된 Phase 1 후보 집합을 그대로 쓴다 (별도 목록을 만들지 않는다)
hasfx "plan.md: 분류가 Phase 1 후보를 그대로 쓴다" "$PLAN" "The candidate set is Phase 1's, unchanged."
# 2. 카드 값 가드 — 이것이 v14 의 유일한 보호 장치다
hasfx "plan.md: 카드 값 가드(비었거나 backlog/ready)" "$PLAN" 'bucket), `backlog` or `ready`'
lacksfx "plan.md: 옛 경계(다섯 값 거부)가 남아 있지 않다" "$PLAN" "The five values the supervisor writes"
# 3. 라벨 기반 제외가 되살아나지 않았다 — 세 번 샜다. 세 번 새면 표현도 세 가지다:
#    한 문구만 막으면 영어로, 다른 라벨로, 다른 동사로 돌아온다(변이로 확인).
#    변이 테스트는 이 검사가 한 문구에만 고정돼 있어 영어로 되살아난 재도입을 놓친다고 지적했다.
#    프로즈에 정규식을 거는 것으로는 못 고친다 — 실제로 시도했고, Phase 1 의 **정당한** 후보 제외
#    (`guild:done`·`guild:child`)와, 왜 사유를 비우는지 설명하는 ⚠ 문단까지 잡았다. 늑대를 계속
#    외치는 검사는 결국 지워지므로, 문구 고정은 그대로 두고 **코드 쪽 불변식**을 대신 세운다.
lacksfx "plan.md: 라벨 기반 제외 문구가 없다" "$PLAN" "보드 쓰기 제외 = guild:needs-human"
# 3b. 경계가 라벨일 수 없다는 것을 코드로 고정한다 — board_write.py 는 라벨을 아예 모른다.
#     입력에 라벨 필드가 없고 스크립트가 라벨을 읽지 않으면, 프롬프트가 어떻게 표현하든
#     라벨 기반 제외는 구현할 방법이 없다. 이것은 프로즈가 아니라 사실이다.
BW_PY="$GLD/commands/atoms/board_write.py"
if grep -qiE 'label' "$BW_PY"; then
  bad "board_write.py: 라벨을 읽지 않는다" "no label" "$(grep -niE 'label' "$BW_PY" | head -1)"
else
  ok "board_write.py: 라벨을 읽지 않는다 (경계가 라벨일 수 없다)"
fi
# 4. 절단 시 정지하지 않는다 (retro 의 절차를 빌려오면 대형 레포에서 plan 이 멈춘다)
hasfx "plan.md: 절단은 명시하고 진행한다" "$PLAN" "continue anyway"
# 5. 멤버 시딩이 needs_human 필드를 비운다 — 캐리오버 자기모순 카드 방지.
#    ⚠ 이름을 리터럴로 적으면 안 된다: 사람이 UI 에서 필드를 개명하면 plan 의 쓰기만 죽고
#    감독자는 살아 있어서 증상이 비대칭이 된다. config 에서 가져오는 형태여야 한다.
hasfx "plan.md: 시딩이 needs_human 을 비운다" "$PLAN" '"clear":["<fields.needs_human>"]'
lacksfx "plan.md: 필드 이름을 리터럴로 적지 않는다" "$PLAN" '"clear":["Needs human"]'
# 5b. 입력 문서의 여섯 키가 다 적혀 있다 — 하나만 빠져도 exit 64 이고 보드가 통째로 빈다
BOARD_KEY_MISS=""
for K in '"number"' '"owner"' '"repo"' '"field"' '"columns"' '"writes"'; do
  grep -qF -- "$K" "$PLAN" || BOARD_KEY_MISS="$BOARD_KEY_MISS $K"
done
if [ -z "$BOARD_KEY_MISS" ]; then
  ok "plan.md: board_write 입력의 필수 6키가 적혀 있다"
else
  bad "plan.md: 필수 키 누락" "all present" "missing:$BOARD_KEY_MISS"
fi
# 5c. 분류는 보드가 없어도 돈다 (§12 롤백이 판정까지 끄면 안 된다)
hasfx "plan.md: 분류가 보드 없이도 돈다" "$PLAN" "runs whether or not a board is configured"
# 5d. 멤버와 비멤버 쓰기 집합이 분리돼 있다
hasfx "plan.md: 두 쓰기 집합이 분리된다" "$PLAN" "disjoint"
# 5e. 추적 이슈 본문의 보드 URL 은 마커 밖이다 (안이면 plan-hash 가 깨진다)
hasfx "plan.md: 보드 URL 이 마커 밖" "$PLAN" "The board line goes OUTSIDE the marker"
# 6. board_write.py 를 한 번 부른다 (Bash 툴 콜 123회가 되지 않게)
hasfx "plan.md: board_write.py 를 호출한다" "$PLAN" "board_write.py --input"
# owned 는 선택적 키다(하위 호환). 그래서 호출자가 조용히 빼면 D1 이 다시 "의도"로 돌아가고
# 스위트는 전부 초록이다 — 실제로 변이가 살아남았다. 양쪽 호출자를 고정한다.
hasfx "plan.md: owned 를 넘긴다" "$PLAN" '"owned":   <config.sprint.board.owned, verbatim>'
hasfx "board.md: --reset 도 owned 를 넘긴다" "$BOARD" "verbatim from config"
# 7. plan 이 카드를 치우지 않는다 — v7 의 청소 규칙 철회를 고정한다.
#    ⚠ `item-archive` 한 문자열만 막으면 `item-delete` 로 되살아난다(변이로 확인).
if grep -qE 'item-archive|item-delete|archiveProjectV2Item|deleteProjectV2Item' "$PLAN"; then
  bad "plan.md: 카드를 치우는 호출이 없다" "absent" "found a card-removal call"
else
  ok "plan.md: 카드를 치우는 호출이 없다"
fi
# 7b. 절단 재조회의 한계값이 유지된다
hasfx "plan.md: 절단 시 --limit 500 으로 재조회" "$PLAN" "--limit 500"
# 8. board.md — Column by 는 verticalGroupByFields 다 (groupByFields 는 Swimlanes)
hasfx "board.md: Column by = verticalGroupByFields" "$BOARD" "verticalGroupByFields"
# 9. board.md — --reset 이 Guild board 는 건드리지 않는다
hasfx "board.md: --reset 이 Guild board 를 비우지 않는다" "$BOARD" '**`Guild board` is NOT cleared.**'
# 9b. Phase S 는 viewer 가 아니라 소유자에 루트해야 한다 — org 보드에서 null 이 온다
hasfx "board.md: Column by 조회가 owner 에 루트한다" "$BOARD" "organization(login:\$o)"
lacksfx "board.md: viewer 루트가 남아 있지 않다" "$BOARD" "viewer{ projectV2(number:\$n)"
# 9c. Phase 3 의 mutation 은 viewId 를 어디서 얻는지 말한다
hasfx "board.md: viewId 출처를 명시한다" "$BOARD" 'Get `<viewId>` first'
# 9d. 채택 경로는 제거됐다 — Guild 는 항상 자기 프로젝트와 자기 필드를 만든다.
#     사용자 결정(2026-08-28): 옵션 자체가 불필요하다. `Status` 채택이 이슈를 닫으므로 기존
#     프로젝트의 대부분에서 그 경로는 어휘 매핑을 다 돌린 뒤 Phase 4 와 같은 곳에 도착했다.
hasfx "board.md: 채택 경로가 없다고 명시한다" "$BOARD" "There is no adopt path"
# 폐기된 플래그는 **이름을 불러야** 한다. `$1` 이 `--setup` 이므로, 이 행이 없으면 사람이
# 프로젝트 5 를 채택해 달라고 했는데 새 프로젝트가 생기고 아무 말도 안 나온다.
hasfx "board.md: 폐기된 --project 를 삼키지 않는다" "$BOARD" "--project is no longer supported"
# 산문만 고정하면 **행**을 지워도 초록이다 — 그러면 삼킴 버그가 그대로 돌아온다.
hasfx "board.md: 폐기 라우팅 행이 있다" "$BOARD" '| `--setup --project <n>` |'
hasfx "board.md: --project 를 라우팅보다 먼저 잡는다" "$BOARD" "before any routing"
# `ready` 를 plan 소유로 옮긴 만큼, 진행 중인 run 과 겹치는 것을 막는 거부가 유일한 보호막이다.
# 그것을 `host` 일치에 걸면 다른 기계·컨테이너의 run 이 그대로 통과한다.
hasfx "plan.md: 진행 중 run 거부가 하트비트 기준이다" "$PLAN" "Do NOT gate this on \`host\` matching"
# ⚠ 근거 산문이 아니라 **판정**을 고정한다. 라운드 1 과 같은 모양이었다: 정당화는 검사되고
# 가드는 안 되는 상태. `refuse` 를 `warn and continue` 로 바꿔도 446건이 전부 초록이었다.
hasfx "plan.md: 살아 있는 run 이면 --create 를 거부한다" "$PLAN" 'within 15 minutes | **refuse'
lacksfx "plan.md: 거부가 경고로 약해지지 않았다" "$PLAN" "within 15 minutes | **warn"
# MAJOR 3: 마커 읽기 실패는 "마커 없음"과 구별돼야 한다 — 빈 출력이 같아서 fail-open 이었다
hasfx "plan.md: 마커 읽기 실패에 분기가 있다" "$PLAN" "cannot prove no supervisor is running"
hasfx "plan.md: ready 가 plan 소유가 된 결과를 적었다" "$PLAN" "unguarded seeding"
hasfx "board.md: 항상 자기 프로젝트·필드를 만든다" "$BOARD" "its own field. Always"
if grep -qE '^### 6b\.|Phase 6b' "$BOARD"; then
  bad "board.md: Phase 6b 가 남아 있지 않다" "absent" "$(grep -nE 'Phase 6b' "$BOARD" | head -1)"
else
  ok "board.md: Phase 6b 가 남아 있지 않다"
fi
if grep -qF 'auto_done"' "$BOARD"; then
  bad "board.md: auto_done 키가 없다" "absent" "$(grep -nF 'auto_done"' "$BOARD" | head -1)"
else
  ok "board.md: auto_done 키가 없다"
fi
# 10. board.md — 측정되지 않은 UI 메뉴 이름을 안내하지 않는다
lacksfx "board.md: Auto-add 의 UI 경로를 적지 않는다" "$BOARD" "Workflows → Auto-add to project"
# 10b. daily.md — 실패 건수를 읽기만 하고 렌더하지 않으면 D9 가 무의미해진다
DAILY="$GLD/commands/sprint/daily.md"
hasfx "daily.md: 신선도는 board_last_write 에서만 온다" "$DAILY" "never from \`heartbeat\`"
# 실패 줄이 신선도 줄을 "대체"하는 것은 이제 표 구조가 보장한다 — 첫 일치 행이 줄 전체다.
hasfx "daily.md: 보드 줄은 첫 일치 행 하나다" "$DAILY" "Pick the first matching row"
hasfx "daily.md: 실패 행이 신선도 대신 마지막 성공을 낸다" "$DAILY" "마지막 성공 <board_last_write>"
hasfx "daily.md: 부재는 0 이 아니다" "$DAILY" "Absent is not zero"
hasfx "daily.md: 실패 0 이 투영됐다는 뜻이 아니다" "$DAILY" "does not mean anything was projected"
hasfx "board.md: last_projected 를 마지막 투영으로 쓰지 않는다" "$BOARD" 'Never print `config.sprint.board.last_projected`'
# ⚠ 규칙을 도출한 파일에만 검사를 걸면, 같은 값을 렌더하는 다른 파일은 초록으로 남는다 —
# 실제로 config.md 가 `마지막 투영 <last_projected>` 를 찍고 있었다. 전 파일을 본다.
BOARD_LP_BAD=""
for F in "$BOARD" "$DAILY" "$PLAN" "$GLD/commands/config.md" "$RUNMD2"; do
  grep -qF -- '마지막 투영 <last_projected>' "$F" && BOARD_LP_BAD="$BOARD_LP_BAD $(basename "$F")"
done
if [ -z "$BOARD_LP_BAD" ]; then
  ok "어느 파일도 last_projected 를 \"마지막 투영\" 으로 찍지 않는다"
else
  bad "last_projected 를 마지막 투영으로 찍는 파일" "none" "offenders:$BOARD_LP_BAD"
fi
# #8: run.md 의 "in full" 쓰기 목록에 .board 파일이 있다 (열거의 가치는 전수성이다)
hasfx "run.md: 쓰기 목록에 .board 파일이 있다" "$RUNMD2" ".gld-sprint-<tracker>.board\` (step 2b"
# #7: daily 는 카드를 읽지 않고 파생한다
hasfx "daily.md: split-children 을 파생으로 얻는다" "$DAILY" "Derive it, do not read the card"
# #2: 컬럼 개명은 Guild 버그가 아니다
hascode "template: 컬럼 개명에 전용 카운터가 있다" "$TPL" "BOARD_UNKNOWN_COL"
hascode "template: 보드가 안 켜진 이유를 원장에 남긴다" "$TPL" "ledger_set board_off_reason"
# ⚠ field-list 한계는 **세 읽는 곳이 같아야** 한다. 감독자는 짧은 읽기를 치명으로 다뤄 보드를
# 끄는데, 진단 명령이 더 멀리 읽으면 *"감독자는 죽고 진단은 정상이라 보고"* 하는 상태가 된다.
# 새 프로젝트만 해도 GitHub 내장 13개 + Guild 5개다.
# ⚠ 파일마다 형태가 다르다 — `board_write.py` 는 `field-list` 와 `--limit` 이 다른 줄에 있어서
# 한 줄 정규식으로는 **보이지 않는다**(그렇게 만든 첫 버전은 변이를 놓쳤다). 파일별로 본다.
BOARD_FL_BAD=""
grep -qE 'field-list.*--limit 100' "$TPL"   || BOARD_FL_BAD="$BOARD_FL_BAD template"
grep -qE 'field-list.*--limit 100' "$BOARD" || BOARD_FL_BAD="$BOARD_FL_BAD board.md"
grep -qE '"--limit", "100"' "$BW_PY"        || BOARD_FL_BAD="$BOARD_FL_BAD board_write.py"
if [ -z "$BOARD_FL_BAD" ]; then
  ok "field-list 한계가 세 읽는 곳에서 100 으로 같다"
else
  bad "field-list 한계가 갈렸다" "100 in all three" "not 100 in:$BOARD_FL_BAD"
fi
hasfx "board.md: 상태 경로 반환값이 따로 있다" "$BOARD" "The bare status route has its own tokens"
hasfx "board.md: 진행 중 run 에게 거짓 약속을 하지 않는다" "$BOARD" "Is a supervisor running right now"
# 읽는 키는 쓰는 곳이 있어야 한다 — owned 가 사문화됐던 것과 같은 종류의 실수를 반복하지 않는다
hasfx "board.md: column_by_verified 를 config 에 쓴다" "$BOARD" '"column_by_verified"'
hasfx "board.md: Phase S 가 그것을 갱신한다" "$BOARD" 'Write the outcome to `config.sprint.board.column_by_verified`'
hasfx "daily.md: column_by_verified 를 읽는다" "$DAILY" "column_by_verified"
# 감독자가 쓰는 사유 토큰은 board.md 의 어휘 목록에 있어야 한다 — 없으면 사람이 카드에서
# 해독할 수 없는 문자열을 본다. 새 토큰을 추가할 때 한쪽만 늘어나는 것을 막는다.
BOARD_TOK_UNDOC=""
# ⚠ `$4`, not `$3`. The match is `board_col "$ISSUE" <column> <reason>`, so `$3` is the COLUMN
# (`blocked`) — this loop verified the four column names over and over and never once checked a
# reason token. Every new reason token shipped unverified until this was fixed.
for T in $(grep -oE 'board_col "\$ISSUE" [a-z_]+ [a-z:-]+' "$TPL" | awk '{print $4}' | sort -u) \
         $(grep -oE 'board_col "\$BOARD_BI" [a-z_]+ [a-z:-]+' "$TPL" | awk '{print $4}' | sort -u); do
  case "$T" in
    failed:*) T="failed:<class>" ;;
  esac
  grep -qF -- "$T" "$BOARD" || BOARD_TOK_UNDOC="$BOARD_TOK_UNDOC $T"
done
if [ -z "$BOARD_TOK_UNDOC" ]; then
  ok "board.md: 감독자가 쓰는 사유 토큰이 모두 문서화돼 있다"
else
  bad "board.md: 문서화되지 않은 사유 토큰" "all documented" "missing:$BOARD_TOK_UNDOC"
fi
# 반대 방향도 본다. 위 검사만으로는 **투영 지점을 통째로 지워도** 어휘 목록이 남아 있으면
# 초록이었다(변이로 확인). 문서에 있는 토큰이 템플릿에도 실제로 쓰이는지 확인한다.
BOARD_TOK_UNUSED=""
for T in pr-unknown dep-unresolved branch-ambiguous base-unresolved split-children interrupted; do
  grep -qE "board_col [^#]*$T" "$TPL" || BOARD_TOK_UNUSED="$BOARD_TOK_UNUSED $T"
done
if [ -z "$BOARD_TOK_UNUSED" ]; then
  ok "template: board.md 가 문서화한 토큰이 모두 실제로 쓰인다"
else
  bad "template: 문서에만 있는 사유 토큰" "all used" "unused:$BOARD_TOK_UNUSED"
fi
hascode "template: 실제 투영 시각을 남긴다" "$TPL" "ledger_set board_last_write"
# ── 노드 ID 주소지정 (측정: 이름 기반 104포인트 vs 노드 ID 1포인트) ───────────
hascode "template: 노드 ID 로 쓴다" "$TPL" '--id "$item" --project-id "$BOARD_PROJECT_ID" --field-id "$fid"'
hascode "template: run 시작 시 id 를 해석한다" "$TPL" "board_resolve"
hasfx "run.md: 비용과 준비 조회를 설명한다" "$RUNMD2" "resolves node ids once at run start"
hasfx "board_write.py: 노드 ID 해석이 있다" "$BW_PY" "def resolve_ids"
hasfx "board_write.py: 해석 실패 시 쓰지 않는다" "$BW_PY" "refusing to write"
# 이름 형태가 되살아나면 비용이 100배로 돌아온다 — 양쪽 파일 모두 고정한다
if grep -qE '\-\-field "\$2" --value|--field '"'"'\{|item-edit.*--url.*--field ' "$TPL"; then
  bad "template: 이름 기반 쓰기가 없다" "absent" "$(grep -nE 'item-edit.*--url.*--field ' "$TPL" | head -1)"
else
  ok "template: 이름 기반 쓰기가 없다"
fi
if grep -qE '"--field", cfg\["field"\]|"--value"' "$BW_PY"; then
  bad "board_write.py: 이름 기반 쓰기가 없다" "absent" "$(grep -nE '"--value"' "$BW_PY" | head -1)"
else
  ok "board_write.py: 이름 기반 쓰기가 없다"
fi
hasfx "daily.md: 계정 불일치를 렌더한다" "$DAILY" "board_account_mismatch"
# 10c. retro 는 보드를 건드리지 않는다 (설계 §7.4)
RETRO="$GLD/commands/sprint/retro.md"
# ⚠ retro 는 보드에 **쓰지** 않는다. 그러나 언급조차 금지하면 §5.4 의 가장 큰 대가가 영구화되는
# 순간(트래커 닫기)에 사람에게 아무 말도 하지 않게 된다 — 그래서 검사를 "언급 금지"에서
# "쓰기 금지"로 바꾼다. 고지는 허용, gh project 호출은 금지.
# ⚠ 부정 문맥(`no gh project call`)은 위반이 아니다 — 그것까지 잡으면 "쓰지 않는다"고 적는 것이
# 금지되고, 그건 검사가 지키려는 것의 반대다. 코드 펜스 안의 실제 호출만 본다.
# ⚠ NO LITERAL BACKTICK anywhere in this block. A heredoc — or even a single-quoted awk
# program — containing backticks, nested inside a $( ) command substitution, breaks bash's
# parser (measured twice: "unexpected EOF while looking for matching"). The fence is built with
# sprintf instead.
RETRO_WRITES="$(awk 'BEGIN { fence = sprintf("%c%c%c", 96, 96, 96); inside = 0 }
  substr($0,1,3) == fence { inside = !inside; next }
  inside && /gh project|item-edit|item-add|item-archive|board_write\.py/ { printf "line%d ", NR }' \
  "$RETRO")"
if [ -z "$RETRO_WRITES" ]; then
  ok "retro.md: 보드에 쓰지 않는다 (고지는 허용)"
else
  bad "retro.md: 보드에 쓰지 않는다" "no board write in any code fence" "offenders:$RETRO_WRITES"
fi
hasfx "retro.md: 얼어붙음을 사람에게 고지한다" "$RETRO" "이 시점 이후 카드는 갱신되지 않습니다"
# 10d. retro Phase 7 — 정리. 지우는 단계라서 안전 장치 문구가 사라지면 안 된다.
#      스프린트 밖의 브랜치, 쌓인 PR 의 base, 머지 뒤에 생긴 커밋을 지우는 것이 각각의 실패 모양이다.
ROLLBACK="$GLD/commands/rollback.md"
hasfx "retro.md: 정리 단계가 있다" "$RETRO" "## Phase 7 — Cleanup"
hasfx "retro.md: DRY 분기가 정리를 포함한다" "$RETRO" "*deleting worktrees and branches*"
hasfx "retro.md: DRY 는 아무것도 지우지 않는다" "$RETRO" "아무것도 삭제하지 않습니다"
hasfx "retro.md: 이름 패턴으로 브랜치를 찾지 않는다" "$RETRO" "**Never** find branches by name pattern"
hasfx "retro.md: prune 은 컨테이너 안일 때만" "$RETRO" "only when every \`prunable\` entry is inside the container"
hasfx "retro.md: 포크 PR 의 브랜치는 후보가 아니다" "$RETRO" "\`isCrossRepository\` is \`false\`"
hasfx "retro.md: 다른 PR 의 base 인 브랜치는 후보가 아니다" "$RETRO" "names **no PR outside the confirmed set**"
hasfx "retro.md: 원격 조회는 전체 ref 로 한다" "$RETRO" "git ls-remote origin refs/heads/<branch>"
hasfx "retro.md: 지우기 직전에 run 을 다시 확인한다" "$RETRO" "**Re-check the run**"
hasfx "retro.md: 닫기 실패는 손으로 닫지 말고 재실행" "$RETRO" "closing it failed — re-run /gld sprint retro"
hasfx "retro.md: 닫힌 스프린트는 --cleanup 으로 정리한다" "$RETRO" 'any argument `--cleanup` → set **CLEANUP**'
hasfx "settings.json.tmpl: branch -D 는 ask" "$GLD/templates/settings.json.tmpl" '"Bash(git branch -D:*)"'
hasfx "settings.json.tmpl: 원격 브랜치 삭제는 ask" "$GLD/templates/settings.json.tmpl" '"Bash(git push origin --delete:*)"'
hasfx "settings.json.tmpl: push --delete 도 ask" "$GLD/templates/settings.json.tmpl" '"Bash(git push --delete:*)"'
hasfx "settings.json.tmpl: push origin -d 도 ask" "$GLD/templates/settings.json.tmpl" '"Bash(git push origin -d:*)"'
hasfx "retro.md: 멤버 판정에 숫자 경계" "$RETRO" 'test("Sprint: #<tracker>([^0-9]|$)")'
lacksfx "retro.md: 멤버 판정이 contains 가 아니다 (#38 이 #389 에 걸린다)" "$RETRO" 'contains("Sprint: #<tracker>")'
hasfx "retro.md: --cleanup 은 열린 트래커를 거절한다" "$RETRO" "is still open — run /gld sprint retro"
hasfx "retro.md: --cleanup 은 스프린트가 아닌 Issue 를 거절한다" "$RETRO" "is not a sprint tracking Issue"
hasfx "retro.md: --cleanup 도 무인 실행을 거절한다" "$RETRO" "(In **CLEANUP** mode there is no Phase 3"
cat > "$WORK3/cleanup.py" <<'CLEANPY'
import re, sys
retro = open(sys.argv[1], encoding="utf-8").read()
rollback = open(sys.argv[2], encoding="utf-8").read()
problems = []
# 정리는 트래커를 닫은 뒤에 온다 — 정리 실패가 끝난 스프린트를 열어 두면 안 된다.
close = retro.find("gh issue close")
p7 = retro.find("## Phase 7")
ret = retro.find("## Return")
if close < 0 or p7 < 0 or ret < p7 or p7 < close:
    print("PROBLEMS Phase 7 must exist after the tracker close and before Return"); raise SystemExit
if "**skip Phase 7**" not in retro:
    problems.append("a failed close does not skip Phase 7")
sec = retro[p7:ret]
# ⚠ 코드 펜스만 보면 안 된다 — Phase 7 의 명령은 인라인 코드다. 문단 단위로 판정한다.
paras = re.split(r"\n\s*\n|\n(?=\s*(?:\d+\.|-) )", sec)
NEG = re.compile(r"\b(never|not|no|nor)\b", re.I)
for p in paras:
    flat = " ".join(p.split())
    for m in re.finditer(r"--force\b|push -f\b|worktree remove -f\b", flat):
        if not NEG.search(flat[max(0, m.start() - 40):m.start()]):
            problems.append("unnegated force near: " + flat[max(0, m.start() - 40):m.end()])
    for m in re.finditer(r"git branch -d\b", flat):
        if not NEG.search(flat[max(0, m.start() - 20):m.start()]):
            problems.append("git branch -d offered: it trusts the upstream and skips the tip check")
    for m in re.finditer(r"git branch -D <", flat):
        if "equal" not in flat or "headRefOid" not in flat:
            problems.append("branch -D without the tip == headRefOid guard in the same item")
    if "push origin --delete <" in flat and "headRefOid" not in flat:
        problems.append("remote delete without the headRefOid guard in the same item")
# 캐리오버와 닫힌-미머지 브랜치는 지우지 않는다.
for row in ("carryover", "closed-unmerged"):
    line = next((l for l in sec.splitlines() if l.startswith("| " + row)), "")
    if line.count("keep") < 2:
        problems.append("the %s row does not keep both branches" % row)
# 기본 브랜치와 현재 브랜치는 후보가 아니다.
if "defaultBranchRef" not in sec or "branch --show-current" not in sec:
    problems.append("default/current branch exclusion missing")
# gh repo view 에는 --repo 가 없다 (unknown flag). 저장소는 위치 인자다.
if "gh repo view --repo" in sec or "gh repo view <owner>/<repo>" not in sec:
    problems.append("gh repo view must take the repo positionally")
# 확인 호출이 판정에 쓰는 필드를 실제로 가져온다 — 문장만 남고 데이터가 빠지면 가드가 빈다.
m = re.search(r"gh pr view <pr>[^\n]*--json ([^ ]+)", sec)
fields = set(m.group(1).split(",")) if m else set()
for f in ("headRefOid", "isCrossRepository", "closingIssuesReferences", "body", "state"):
    if f not in fields:
        problems.append("gh pr view --json lacks " + f)
def item(head):
    i = sec.find(head)
    if i < 0:
        problems.append("missing item: " + head); return ""
    j = re.search(r"\n\d+\. \*\*|\n\*\*DRY\*\*|\nA failed", sec[i + 1:])
    return " ".join(sec[i:i + 1 + (j.start() if j else len(sec))].split())
for head in ("2. **Local branches**", "3. **Remote branches**"):
    it = item(head)
    if "merged rows only" not in it:
        problems.append(head + " is not limited to merged rows")
    if not re.search(r"\*\*exactly equal\*\* to `headRefOid`", it):
        problems.append(head + " does not require the tip to equal headRefOid")
    if re.search(r"\b(different from|whatever|informational|any SHA)\b", it):
        problems.append(head + " weakens the tip test")
if "Right before each delete, re-read the remote ref" not in item("3. **Remote branches**"):
    problems.append("remote delete trusts the pre-approval ls-remote")
rc = item("0. **Re-check the run**")
if "ps -p <pid> -o command=" not in rc or ".gld-sprint-" not in rc or "remove **nothing**" not in rc:
    problems.append("run re-check lacks the pid probe or the stop")
row = next((l for l in sec.splitlines() if l.startswith("| merged")), "")
if row.count("iff tip == `headRefOid`") != 2:
    problems.append("merged row does not guard both branch deletions")
dry = " ".join(sec[sec.find("**DRY**: run 1"):].split("\n\n")[0].split()) if "**DRY**: run 1" in sec else ""
if "skip 3" not in dry or "delete nothing" not in dry:
    problems.append("DRY does not skip the apply step")
if "`.sprint-logs/<tracker>/` is **never** a candidate" not in " ".join(sec.split()):
    problems.append(".sprint-logs is not excluded")
if "no `OPEN` PR at all" not in sec:
    problems.append("a branch that is the base of an open PR can be deleted")
flat = " ".join(sec.split())
for phrase, why in (
    ("`ls -A .claude/guild/`", "run files are dotfiles; plain ls hides them"),
    ("--head <headRefName>", "no check for PRs headed by the branch"),
    ("only the line whose ref is **exactly** `refs/heads/<branch>`", "ls-remote tail match not guarded"),
    ("`git ls-files .claude/guild/<file>`", "tracked run files are not excluded"),
    ("This re-check is never skipped", "the run re-check may be skipped"),
    ("disagree on `headRefOid`", "two merged PRs with different heads are not kept"),
    ("Phase 1's branch test, `(^|[^0-9])#?<N>([^0-9]|$)`", "the branch-name token test is missing or weakened"),
    ("`closes` is exactly **one** number", "membership no longer needs exactly one closed Issue"),
    ("re-run step 1's `--head` and `--base` calls with `--state open`", "the remote delete skips the open-PR re-check"),
    ("the **same live states**", "the run re-check no longer names Phase 0's live states"),
    ("`release/…` or `v<digits>…`", "release/version lines can become candidates"),
    ("does **not** block the local delete", "an absent remote ref blocks the local delete"),
    ("finding **no open PR**", "the local delete skips the open-PR re-check"),
    ("Phase 0 step 0's per-Issue lookup", "children have no truncation fallback"),
    ("Reuse Phase 1's S and its children", "Phase 7 no longer reuses Phase 1's children"),
    ("Read its `permissions.ask` first", "the prompt claim is not checked against the repo's settings"),
):
    if phrase not in flat:
        problems.append(why)
whole = " ".join(retro.split())
for phrase, why in (
    ("\"Closes #<m>\" in:body", "CLEANUP search is not bounded to a closing reference"),
    ("**equals the limit** is truncated", "a truncated CLEANUP lookup reads as no PR"),
    # 0.98.0: 자식 검색은 Phase 1 로 옮겼다 — 숫자 경계는 거기서 지킨다.
    ("test(\"Parent Issue: #<m>([^0-9]|$)\")", "children search lost its digit boundary"),
    ("look up each member **and each child of S**", "CLEANUP per-Issue lookup does not cover the children"),
):
    if phrase not in whole:
        problems.append(why)
if re.search(r"\bskip (this|the) re-check", " ".join(rc.split())):
    problems.append("the run re-check may be skipped")
# rm 은 run 파일만 — 재귀 삭제나 .sprint-logs 삭제는 부정 문맥에서만 언급된다.
for p_ in paras:
    f_ = " ".join(p_.split())
    for m in re.finditer(r"rm -r\b|rm [^`]*\.sprint-logs", f_):
        if not NEG.search(f_[max(0, m.start() - 20):m.start()]):
            problems.append("unnegated rm near: " + f_[max(0, m.start() - 20):m.end()])
# 원격 삭제는 ask 에 걸리는 한 가지 철자로만. 다른 철자는 경고 문단에서만 나온다.
warn = next((" ".join(p_.split()) for p_ in paras if "Use exactly these spellings" in p_), "")
rest = flat.replace(warn, "") if warn else flat
for alt in ("push origin :<", "push --delete origin", "push -d origin", "push origin -d ", "-C <dir> branch -D"):
    if alt in rest:
        problems.append("delete spelled as " + alt + " outside the warning")
# rollback.md 의 branch -D 금지 행이 retro 예외를 명시한다 (issue close 와 _handoff.md 의 짝과 같다).
rows = [l for l in rollback.splitlines() if "branch -D" in l]
if not any("sprint retro" in r and "headRefOid" in r for r in rows):
    problems.append("rollback.md's branch -D rule does not name the retro exception")
# Hard rules 도 같은 부정 검사를 받는다 — Phase 7 밖에서 강제를 허용하면 같은 지시가 된다.
if retro.find("## Hard rules") < 0:
    problems.append("Hard rules section missing")
hr = retro[retro.find("## Hard rules"):] if retro.find("## Hard rules") >= 0 else ""
for line in hr.split("\n- "):
    f_ = " ".join(line.split())
    for m in re.finditer(r"--force\b|git branch -d\b", f_):
        if not NEG.search(f_[max(0, m.start() - 40):m.start()]):
            problems.append("Hard rules allow: " + f_[max(0, m.start() - 40):m.end()])
print("OK" if not problems else "PROBLEMS " + "; ".join(problems))
CLEANPY
CLEAN="$("$PY" "$WORK3/cleanup.py" "$RETRO" "$ROLLBACK")"
if [ "$CLEAN" = "OK" ]; then
  ok "retro.md: 정리는 닫은 뒤, 강제·-d 없음, 삭제는 headRefOid 일치일 때만, rollback.md 가 예외를 명시한다"
else
  bad "retro.md: 정리의 안전 장치" "OK" "$CLEAN"
fi

# 10e. sprint sync 가 머지된 멤버 카드를 Done 으로 옮긴다 (0.94.0, 03-sprint-board.md §5.5).
#     가드를 끄고 쓰므로 안전 장치는 (a) 대상 목록이 스크립트(done_members)에서만 온다,
#     (b) 쓰는 컬럼이 done 하나다, (c) --check 에서는 쓰지 않는다 — 셋이다.
SYNCMD="$GLD/commands/sprint/sync.md"
hasfx "sync.md: 보드가 있으면 --done-cards 를 넘긴다" "$SYNCMD" 'Add `--done-cards` when `config.sprint.board` is set'
hasfx "sync.md: done-cards 줄은 상태가 아니다(attention 에 세지 않는다)" "$SYNCMD" 'line is not a status'
hasfx "sync.md: 대상을 손으로 고르지 않는다" "$SYNCMD" "the script's list is the guard"
hasfx "retro.md: sync 는 열린 스프린트만 다룬다고 고지한다" "$RETRO" "열린 스프린트만 다룹니다"
hasfx "help.md: sync 가 카드를 Done 으로 옮긴다" "$GLD/commands/help.md" "move merged members' cards to Done"
hasfx "sprint.md: sync 가 카드를 Done 으로 옮긴다" "$GLD/commands/sprint.md" 'move the merged members'"'"' cards to `Done`'
hasfx "stack_sync.py: done-cards 는 MERGED 와 CLOSED 를 둘 다 요구한다" "$GLD/commands/atoms/stack_sync.py" '⚠ Both halves, not either.'
hascode "stack_sync.py: done-cards 는 stateReason COMPLETED 를 요구한다" "$GLD/commands/atoms/stack_sync.py" '== "COMPLETED"'
cat > "$WORK3/syncboard.py" <<'SYNCPY'
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
errs = []
a = s.find("5. **Board"); b = s.find("## Return")
if a < 0 or b < a:
    print("step 5 (Board) not found before ## Return"); sys.exit(0)
step = s[a:b]
js = re.search(r"```json\n(.*?)```", step, re.S)
if not js:
    errs.append("no json input block in step 5")
else:
    j = js.group(1)
    for k in ("number", "owner", "repo", "field", "columns", "owned", "writes"):
        if not re.search(r'"%s":' % k, j):
            errs.append("input lacks %s" % k)
    if not re.search(r'"guard":\s*false', j): errs.append('"guard": false missing')
    # read: false — a read is item-list at board size (~500 points) on every sync
    if not re.search(r'"read":\s*false', j): errs.append('"read": false missing')
    cols = re.findall(r'"column":\s*"([^"]*)"', j)
    if cols != ["done"]: errs.append("columns written must be exactly [done], got %r" % cols)
    if "fields.needs_human" not in j: errs.append("Needs human is not cleared")
    if re.search(r'"fields":', j): errs.append("writes a data field besides the column")
    for v in ("columns, verbatim", "owned, verbatim"):
        if v not in j: errs.append("%s missing" % v)
chk = [ln for ln in step.split("\n   - ") if "with `--check`" in ln]
if not chk or "write nothing" not in chk[0]:
    errs.append("--check bullet does not say write nothing")
hr = s[s.find("## Hard rules"):]
m = re.search(r"- \*\*The board gets `Done` and nothing else\*\*(.*?)(?=\n- |\Z)", hr, re.S)
if not m or "never under `--check`" not in m.group(1):
    errs.append("Hard rule for the board missing or lacks never under --check")
print("; ".join(errs) or "OK")
SYNCPY
SB="$("$PY" "$WORK3/syncboard.py" "$SYNCMD")"
if [ "$SB" = "OK" ]; then
  ok "sync.md: Done 하나만, 가드 끔은 목록이 정할 때만, --check 는 쓰지 않는다, Needs human 을 비운다"
else
  bad "sync.md: 보드 단계의 안전 장치" "OK" "$SB"
fi

# 10f. sprint plan 이 PO·tech-lead 판정 원문과 config.json 을 커밋·push 한다 (0.95.0).
#     잊고 run 하던 미커밋 파일을 없애되 — 사람의 다른 변경을 섞거나, 기능 브랜치에 올리거나,
#     사람이 push 하지 않은 커밋을 함께 내보내거나, 거부된 push 로 기본 브랜치를 갈라 두면 안 된다.
PLANMD="$GLD/commands/sprint/plan.md"
lacksfx "plan.md: 정의되지 않은 <slug> 가 남아 있지 않다" "$PLANMD" "sprint-<slug>"
hasfx "plan.md: PO 산출물은 고정된 초안 디렉터리에 쓴다" "$PLANMD" 'docs/specs/sprint-draft/po.md'
hasfx "plan.md: tech-lead 산출물은 고정된 초안 디렉터리에 쓴다" "$PLANMD" 'docs/specs/sprint-draft/deps.md'
hasfx "run.md: 미커밋 plan 기록을 경고한다 (-uall)" "$RUNMD2" "git status --porcelain -uall -- docs/specs/"
cat > "$WORK3/plancommit.py" <<'PLANPY'
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
errs = []
a = s.find("6. **Record the plan in git**"); b = s.find("Body template:")
five = s.find("5. **Project onto the board**")
if a < 0 or b < a or not (0 <= five < a):
    print("step 6 missing, or not after step 5 and before the body template"); sys.exit(0)
st = s[a:b]
subs = {}
for m in re.finditer(r"^   (\d)\. \*\*(.*?)\*\*", st, re.M):
    subs[int(m.group(1))] = m.start()
if sorted(subs) != list(range(1, 9)):
    print("step 6 must have sub-steps 1..8, got %r" % sorted(subs)); sys.exit(0)
def sub(n):
    return st[subs[n]:subs[n + 1]] if n + 1 in subs else st[subs[n]:st.find("**Retry by hand**")]
need = {
    1: ["git status --porcelain -uall -- .claude/guild/config.json docs/specs/sprint-draft/`.", "skip the rest"],
    2: ["mkdir -p docs/specs/sprint-<tracker>", "mv docs/specs/sprint-draft/<name> docs/specs/sprint-<tracker>/<stem><suffix>.md",
        "**one suffix for the whole run**", "git ls-files --error-unmatch", "Denied → stop"],
    3: ["git branch --show-current", "must equal the default branch", "→ stop"],
    4: ["git diff --cached --name-only", "Anything →\n      stop"],
    5: ["git config branch.<branch>.remote", "git config branch.<branch>.merge",
        "git config branch.<branch>.pushRemote", "git remote get-url <remote>",
        "`git fetch <remote>` — it fails → stop", "or not fetched → stop). Behind → stop",
        "`git config remote.pushDefault` must both print\n        nothing",
        "git remote get-url --push <remote>", "git rev-list --count @{u}..HEAD",
        "(a) push them\n        together with the record, (b) commit the record but push nothing, (c) commit nothing",
        "An unanswered or ambiguous reply is (b)"],
    6: ["git diff HEAD -- .claude/guild/config.json", "unanswered or ambiguous reply is (c)",
        "if nothing is left in the record, stop"],
    7: ["git add -- <record paths>", 'git commit -m "<message>" -- <record paths>',
        "at least one path after `--`", "git restore --staged --", "one call each", "timeout",
        "**Never `--no-verify`.**"],
    8: ["git push <remote> HEAD:<merge>", "timeout", "git ls-remote <remote> <merge>",
        "must equal the commit just\n      made", "git rev-parse HEAD", "git reset --soft HEAD~1",
        "git restore --staged -- <path>", "**Never `--force`, never pull or rebase"],
}
for n, items in need.items():
    body = sub(n)
    for x in items:
        if x not in body:
            errs.append("sub-step %d lacks: %s" % (n, x.replace("\n", "\\n")))
if "Not on `run.md`'s ad-hoc path" not in st[:subs[1]]:
    errs.append("step 6 does not exclude run.md's ad-hoc path")
if "**Retry by hand**" not in st:
    errs.append("no retry line")
# a forbidden spelling may appear only right after "never"/"Never" (with an optional backtick)
for bad in (r"git add \.", r"git add -A", r"--all\b", r"--no-verify", r"--force", r"(?<![\w-])-a(?:m)?\b",
            r"git reset --(?:hard|mixed|merge|keep)", r"git stash", r"git push`", r"git pull",
            r"git diff -- \.claude", r"Behind → (?!stop)", r"--amend", r"git reset (?!--soft)",
            r"git push (?!<remote> HEAD:<merge>)"):
    for m in re.finditer(bad, st):
        pre = st[max(0, m.start() - 9):m.start()]
        if not re.search(r"[Nn]ever `?$", pre) and not re.search(r"bare `$", pre):
            errs.append("unnegated %s in step 6: …%s" % (bad, st[max(0, m.start() - 30):m.end() + 10].replace("\n", " ")))
# the sub-agents' prompts themselves must name the draft paths, and Phase 2 clears them first
po = [l for l in s.splitlines() if "Adopt the persona in `.claude/agents/product-owner.md`. Read the candidate list" in l]
tl = [l for l in s.splitlines() if "Adopt the persona in `.claude/agents/tech-lead.md`. From CANDIDATES (tech-lead) (below)" in l]
if len(po) != 1 or "`docs/specs/sprint-draft/po.md`" not in po[0]:
    errs.append("the PO prompt does not write docs/specs/sprint-draft/po.md")
if len(tl) != 1 or "`docs/specs/sprint-draft/deps.md`" not in tl[0]:
    errs.append("the tech-lead prompt does not write docs/specs/sprint-draft/deps.md")
if "\n  기록: 만들면 판정 원문(docs/specs/sprint-<트래커 번호>/)과 config.json 을" not in s:
    errs.append("Phase 5 does not disclose the commit and push")
if "`rm -f docs/specs/sprint-draft/po.md docs/specs/sprint-draft/deps.md docs/specs/sprint-draft/deps-slot.md`" not in s:
    errs.append("Phase 2 does not clear the last run's verdicts")
hr = s[s.find("## Hard rules"):]
if "**The plan commit holds this run's verdict files and `config.json` — nothing else**" not in hr:
    errs.append("Hard rule for the plan commit missing")
ret = s[s.find("## Return"):s.find("## Hard rules")]
for t in ("plan recorded <sha> pushed", "plan recorded <sha> local", "plan not recorded (<reason>)"):
    if t not in ret:
        errs.append("Return lacks " + t)
print("; ".join(errs) or "OK")
PLANPY
PC="$("$PY" "$WORK3/plancommit.py" "$PLANMD")"
if [ "$PC" = "OK" ]; then
  ok "plan.md: 기록 커밋은 이름 붙인 경로만, 기본 브랜치·빈 인덱스·원격과 같을 때만, 거부되면 되돌린다"
else
  bad "plan.md: plan 기록 커밋의 안전 장치" "OK" "$PC"
fi

# 11. run.md — 보드 값은 렌더 토큰이 아니라 **데이터 파일**이다. 이 클래스가 세 번 나왔다:
#     소스 보간(실행됨) → 인용 heredoc(개행이 탈출) → 데이터 파일.
lacksfx "template: 보드 렌더 토큰이 남아 있지 않다" "$TPL" "<BOARD_NUMBER>"
lacksfx "run.md: 폐기된 토큰 표가 남아 있지 않다" "$RUNMD2" "<BOARD_COL_READY>"
hasfx "run.md: 보드 설정 파일을 쓰는 단계가 있다" "$RUNMD2" ".gld-sprint-<tracker>.board"
hasfx "run.md: 값을 인용하지 말라고 말한다" "$RUNMD2" "Do not quote them"
hascode "template: 설정 파일을 읽는다" "$TPL" 'BOARD_CONF="$HUMAN_REPO/.claude/guild/.gld-sprint-$TRACKER.board"'
# 11a. 보드를 끌 때는 파일을 **지워야** 한다. 안 쓰기만 하면 낡은 파일이 읽혀 보드가 켜진다.
hasfx "run.md: 보드가 null 이면 설정 파일을 지운다" "$RUNMD2" "rm -f .claude/guild/.gld-sprint-<tracker>.board"
# 11b. run.md 가 쓰는 키와 템플릿이 읽는 키가 **같은 집합인가.**
# ⚠ 옛 판은 열 개 이름을 손으로 적어 놓고 양쪽에 있는지만 봤다. 그래서 주석이 말하는
#   "한쪽만 늘면 조용히 빈다" 를 정작 탐지하지 못했다 — run.md 에만 `col_icebox=` 를 더해도,
#   템플릿에만 `col_icebox)` 를 더해도 234/0 그린이었다(실측). 양쪽에서 **집합을 뽑아** 비교한다.
cat > "$WORK3/boardkeys.py" <<'PYBK'
import re, sys
runmd, tpl = sys.argv[1], sys.argv[2]
# run.md step 2b 의 conf 본문: `<key>=<...>` 형태의 줄
wrote = set(re.findall(r"^\s{2,}([a-z][a-z0-9_]*)=<", open(runmd, encoding="utf-8").read(), re.M))
# 템플릿의 conf 파서: `<key>)` case 분기
# ⚠ 손으로 적은 접두사 화이트리스트를 쓰지 않는다. 그 밖의 이름으로 case 분기를 더하면
#   보이지 않았다(실측: `swimlane)` 추가 -> OK 10 keys). conf 파서 블록 안의 분기를 통째로 본다.
src = open(tpl, encoding="utf-8").read()
i = src.find("BOARD_CONF=")
j = src.find("esac", i) if i >= 0 else -1
if i < 0 or j < 0:
    print("PROBLEMS cannot locate the board conf parser in the template")
    raise SystemExit
read = set(re.findall(r"^\s+([a-z][a-z0-9_]*)\)", src[i:j], re.M))
problems = []
if len(wrote) != 10:
    problems.append("run.md yields %d keys (%s), expected exactly 10"
                    % (len(wrote), ",".join(sorted(wrote))))
if wrote - read:
    problems.append("run.md writes keys the template never reads: %s" % ",".join(sorted(wrote - read)))
if read - wrote:
    problems.append("template reads keys run.md never writes: %s" % ",".join(sorted(read - wrote)))
print("OK %d keys" % len(wrote) if not problems else "PROBLEMS " + " | ".join(problems))
PYBK
OUTBK="$("$PY" "$WORK3/boardkeys.py" "$RUNMD2" "$TPL")"
case "$OUTBK" in
  OK*) ok "보드 설정 키가 run.md 와 템플릿에서 같은 집합이다 (${OUTBK#OK })" ;;
  *)   bad "보드 설정 키 집합 일치" "OK" "$OUTBK" ;;
esac

# 11c. 중복 실행 가드의 cmdline 매치 문자열이 실제로 디스크에 써지는 스크립트 이름의
#      부분문자열이어야 한다. 마커의 `pid` 는 감독자 스크립트 자신의 `$$`(template 의
#      `marker_write`)이므로 `ps -p <pid> -o command=` 는 `bash .claude/guild/.gld-sprint-<N>.sh`
#      를 찍는다. 한때 이 자리가 `sprint-supervisor`(= **템플릿 파일명**)를 찾았고, 그 문자열은
#      그 출력에 절대 나타나지 않아 LIVE 감독자가 "pid 재사용 → 없는 것으로 취급" 행으로
#      떨어졌다 — 두 번째 감독자가 같은 워크트리와 같은 트래커 마커에 붙는다.
#      ⚠ 파일명 참조(step 2 의 `templates/sprint-supervisor.sh`)는 정당하므로 문장 단위로 본다.
hasfx  "run.md: 중복 실행 가드가 .gld-sprint- 를 찾는다" "$RUNMD2" \
       'Output containing **`.gld-sprint-`**'
lacksfx "run.md: 가드가 템플릿 파일명을 찾지 않는다" "$RUNMD2" \
       'Output containing `sprint-supervisor`'
# 11d. 그 문자열이 run.md 가 스스로 쓰라고 지시하는 경로의 부분문자열인가 (유도형 교차검증)
GUARD_TOK=".gld-sprint-"
if grep -qF -- "bash .claude/guild/${GUARD_TOK}" "$RUNMD2"; then
  ok "가드 문자열이 run.md 가 실행하라는 경로의 부분문자열이다"
else
  bad "가드 문자열이 실행 경로와 맞는다" "substring of the launched path" \
      "run.md 의 launch 줄에 ${GUARD_TOK} 가 없다"
fi

# 12. §9.2 가 요구했으나 없던 검사 셋 ─────────────────────────────────────────
# 12a. plan 의 보드 쓰기 게이트 세 조건
hasfx "plan.md: 쓰기는 --create/승인 시점에만" "$PLAN" 'Phase 6 — Create (`--create` or explicit approval)'
hasfx "plan.md: 무인 모드는 만들지 않는다" "$PLAN" "GLD_UNATTENDED=1"
hasfx "plan.md: 쓰기는 board 설정 시에만" "$PLAN" 'only when `config.sprint.board` is set'
# 12b. --reset 의 절단 대조와 확인 프롬프트
hasfx "board.md: --reset 이 totalCount 를 대조한다" "$BOARD" 'against `totalCount`'
hasfx "board.md: --reset 이 사람에게 묻는다" "$BOARD" "Show the count and ask"
hasfx "board.md: --reset 취소 반환값" "$BOARD" 'OK: reset — 취소됨'
# 12c. --reset 이 외부 레포와 드래프트를 걸러낸다 (같은 번호의 우리 이슈를 지우는 경로였다)
hasfx "board.md: --reset 이 다른 레포 항목을 뺀다" "$BOARD" 'is not `<owner>/<repo>`'
hasfx "board.md: --reset 이 드래프트를 뺀다" "$BOARD" "those are **drafts**"
# 12d. 롤백 순서 (config 를 먼저 비우면 --reset 이 아무 것도 못 한다)
hasfx "board.md: --reset 이 config 정리보다 먼저다" "$BOARD" "Run this BEFORE removing the board from config"


echo ""
echo "== 13. 실행 시간대 창 — 산문 단정 (04-sprint-window.md · -tests.md §3.5) =="
# ⚠ 아래는 LLM 이 읽는 markdown 에 대한 검사다. **문장이 존재하면 통과하고, 주변 논리가
#   모순돼도 통과한다.** 초록을 "검증됐다"로 읽지 않는다. 다만 선언된 한계가 곧 어쩔 수 없는
#   한계는 아니다 — 아래 19·21·23·28·33 은 스코프를 좁혀 실제로 발화하게 만들었다.
HANDOFF="$GLD/commands/atoms/_handoff.md"
RETRO="$GLD/commands/sprint/retro.md"
# ⚠⚠ **M11 — 압축 내성.** 세 게이트가 «두 시점을 비교하는» 구조인데 before 半이 컨텍스트에만
# 있었다. 압축이 그 사이에 들어오면 **기본값이 「변화 없음」** 이 되어 셋 다 조용히 통과한다.
# 실측: 유인 세션의 **8.5%** 가 1M 천장에서 압축하고, 세 파일 모두 **공통 경로**다.
# 토큰 조치가 아니라 **오늘 이미 발생 중인 품질 결함**이다.
# ⚠⚠ **M9 — `docs/specs/<issue>/` 재독 축소.** 적분의 **16.9%**(guild 지시문 전체의 2배).
# 원리는 「덜 읽기」가 아니라 「늦게 읽기」다 — billed input 이 `Σ_turn prefix` 라 앞턴 바이트가
# 몇 배 비싸다. ⚠ 그래서 **전수 독자 다섯은 예외**이고, 그중 **셋은 서브에이전트라
# `_preflight.md` 를 읽지 않으므로 요구가 스폰 프롬프트에 있어야 한다.**
# ⚠⚠ **M5 — 셸 파일 읽기 → Read 도구.** 규칙은 별도 절의 «prefer» 로만 있었고 무시됐다
# (`cat` 1,076 · `sed` 1,228 · `grep` 1,558 / 37세션). 규범으로 승격한다.
# ⚠ 핵심은 **도구 치환이 아니다** — `cat x` → `Read x` 는 delta 항등이라 절감이 **정확히 $0**.
# 게이트는 4d 의 「파일을 끌어오는 것」 50.6% 하락으로 건다.
PFMD="$GLD/commands/atoms/_preflight.md"
# ⚠ **M13 — `docs/standards/` 재독 축소**(적분 3.36%, `verification.md` 홀로 **1.44%** —
# 도구 §4c 의 「파일별 내역」이 찍는다. 라운드 6 이전에는 그 내역을 도구가 안 찍어서
# 지시문의 수가 근거 없이 떠 있었고, 반올림도 1.5% 로 틀려 있었다).
# M9 와 같은 모양이지만 **하나가 다르다**: 이 Item 은 같은 문단에서 `status: confirmed` 를
# **하드 제약**으로 다루라고 요구한다. 안 연 파일의 status 는 알 수 없으므로, 좁히기와
# 그 요구가 충돌한다 → `^status:` Grep 한 번으로 분할 판정을 공짜로 끝낸다.
hasfx "M13: docs/standards 를 선택적으로 읽는다" "$PFMD" 'Retrieve, do not whole-load'
hasfx "M13: confirmed/draft 분할을 status Grep 으로 보전한다" "$PFMD" 'one Grep for `^status:`'
hasfx "M13: Grep 기본 출력이 파일명이라 content 를 명시한다" "$PFMD" 'output_mode: "content"'
hasfx "M13: 예산이 하드 제약에 양보한다" "$PFMD" 'the budget yields to a hard constraint'
hasfx "M13: 빈손이 「confirmed 없음」과 다르다고 못박는다" "$PFMD" 'Zero matches is not the same'

BRMD="$GLD/commands/atoms/_bash_rules.md"
hasfx "M5: 권고가 아니라 규칙이다" "$BRMD" 'This is a rule, not a preference'
hasfx "M5: 도구를 바꾸는 것으로는 절감이 없다고 못박는다" "$BRMD" '**saves exactly nothing**'
hasfx "M5: 파일 읽기 비중을 범위로 적는다" "$BRMD" '**50.6–62.1%**'
hasfx "M5: 커맨드 출력은 증거이지 절감 대상이 아니다" "$BRMD" 'is not a target — it is the evidence'
hasfx "M5: INV5 가 이긴다고 못박는다" "$BRMD" 'wins** — it is an invariant and this rule is not'
hasfx "M5: 질의 축소는 허용된다" "$BRMD" 'Narrowing the QUERY is a different act'
hasfx "M5: 스필 재독은 2차 효과라 이중 계상 금지" "$BRMD" 'count it twice'
# ⚠ **정합성** — Read 도구 몫(17.9%p)을 적어야 「도구를 바꿔도 총량은 안 준다」가 근거를 갖는다.
if grep -qF -- 'Read tool is 17.9 of those' "$BRMD"; then
  ok "M5: Read 도구 몫을 명시해 치환 무익을 실측으로 뒷받침한다"
else
  bad "M5: Read 도구 몫을 명시한다" "17.9%p" "없다 — 「치환은 무익」이 근거 없는 주장이 된다"
fi

PFMD="$GLD/commands/atoms/_preflight.md"
ESMD="$GLD/commands/atoms/_execute_spine.md"
IMPMD="$GLD/commands/implement.md"
RFMD="$GLD/commands/refactor.md"
TSTMD="$GLD/commands/test.md"
hasfx "M9: Item 4 가 디렉터리가 아니라 산출물을 지정한다" "$PFMD" 'not the directory'
hasfx "M9: 전수 독자 다섯이 예산 밖이라고 못박는다" "$PFMD" 'five jobs compare the CHANGE against the WHOLE intent'
hasfx "M9: 셋이 서브에이전트라 이 파일을 안 읽는다고 적는다" "$PFMD" 'sub-agents that never read this file'
hasfx "M9: 3.5b 는 전수 독자가 아니라고 못박는다" "$PFMD" '**3.5b specialists are NOT on that list**'
hasfx "M9: refactor 리더도 아니라고 못박는다" "$PFMD" 'The `refactor` leader is not on it either'
hasfx "M9: 페이징이 더 비싸다고 적는다" "$PFMD" 'each added turn re-bills the entire prefix'
hasfx "M9: Read 잘림에 표시가 없다고 적는다" "$PFMD" 'adds no truncation marker'
# ⚠ **정합성 ①** — 서브에이전트 셋의 스폰 프롬프트에 통독 요구가 **실제로** 있어야 한다.
# 카브아웃에 이름만 올리는 것은 의도를 적을 뿐 전달하지 않는다.
M9N=0
grep -qF -- 'Read it whole, in one Read' "$IMPMD" && M9N=$((M9N+1))
grep -qF -- 'Read it whole, in one Read' "$RFMD"  && M9N=$((M9N+1))
grep -qF -- 'whole, in one Read' "$TSTMD"         && M9N=$((M9N+1))
grep -qF -- 'read the intent whole, not a slice' "$ESMD" && M9N=$((M9N+1))
# ⚠⚠ **존재 검사만으로는 부족했다 — 실증.** 이 ⚠ 절을 삽입하면서 `test.md` 의 스폰 프롬프트에서
# `docs/specs/$1/test-cases.md` 가 **문장 중간에 쪼개졌는데**(`…test-cases.` + 300자 + `.md`)
# 위 네 줄은 전부 PASS 했다. 파일 경로가 **온전한 한 토큰으로** 있는지 본다.
PATHOK="$("$PY" - "$GLD" <<'PATHPY'
import os, re, sys
# ⚠ **파일 전체를 보면 안 된다.** 같은 경로가 리더의 Step 0 줄에도 있어서, 스폰 프롬프트에서
# 경로가 쪼개져도 통과한다(실증). **스폰 프롬프트 줄 안에서만** 찾는다.
gld = sys.argv[1]
want = {
    "commands/test.md":      (r"Adopt the persona in `\.claude/agents/tester\.md`",
                              r"`docs/specs/\$1/test-cases\.md`"),
    "commands/implement.md": (r"Review the implementation on the current branch",
                              r"`docs/specs/\$1/skeleton\.md`"),
    "commands/refactor.md":  (r"Review the refactor on the current branch",
                              r"`docs/specs/\$1/skeleton\.md`"),
}
bad = []
for rel, (marker, pat) in want.items():
    hit = False
    for ln in open(os.path.join(gld, rel), encoding="utf-8"):
        if re.search(marker, ln) and re.search(pat, ln):
            hit = True
            break
    if not hit:
        bad.append(rel)
print("OK" if not bad else "BROKEN " + " ".join(bad))
PATHPY
)"
if [ "$PATHOK" = "OK" ]; then
  ok "M9: 스폰 프롬프트의 산출물 경로가 온전하다 (문장 중간에 안 쪼개졌다)"
else
  bad "M9: 스폰 프롬프트의 산출물 경로가 온전하다" "온전" "$PATHOK — ⚠ 절을 경로 한가운데 끼워 넣었다"
fi
if [ "$M9N" -eq 4 ]; then
  ok "M9: 서브에이전트 스폰 프롬프트 4곳에 통독 요구가 있다"
else
  bad "M9: 서브에이전트 스폰 프롬프트에 통독 요구가 있다" "4곳" "${M9N}곳 — 카브아웃에 이름만 올렸다"
fi
# ⚠ **정합성 ②** — `qa.md` 의 `Load:` 열거가 깨지지 않았는가.
# 라운드 3과 이번에 **두 번** 같은 사고를 냈다: ⚠ 절을 문장 중간에 끼워 넣으면서
# `and the hotspot list` 가 열거에서 떨어져 무의미한 꼬리가 됐다. 소비자가 실재한다(Step 1).
# ⚠ **문자열 존재로 판정하면 안 된다** — 떨어져 나간 꼬리도 같은 문자열을 만족한다(실증).
# `Load:` 와 `⚠` 사이, 즉 **열거 구간 안에** 있는지를 위치로 본다.
QAPOS="$("$PY" - "$GLD/commands/qa.md" <<'QAPY'
import sys
# Locate the Load: line by content, not by a fixed index — a line added above the Step 0
# paragraph (the 0.87.0 stage-start mark) shifted it and broke a check about something else.
_lines = [l for l in open(sys.argv[1], encoding="utf-8").read().split("\n") if "Load:" in l]
if len(_lines) != 1:
    print("BROKEN"); raise SystemExit
ln = _lines[0]
try:
    lo = ln.index("Load:"); hi = ln.index("⚠", lo); h = ln.index("hotspot list", lo)
except ValueError:
    print("BROKEN"); raise SystemExit
print("OK" if lo < h < hi else "BROKEN")
QAPY
)"
if [ "$QAPOS" = "OK" ]; then
  ok "M9: qa Load 열거 **안에** hotspot list 가 있다"
else
  bad "M9: qa Load 열거 안에 hotspot list 가 있다" "Load: 와 ⚠ 사이" "그 밖으로 떨어졌다 — Step 1 의 리스크 기반 계획이 입력을 잃는다"
fi

ESMD="$GLD/commands/atoms/_execute_spine.md"
STMD="$GLD/commands/atoms/_stagnation.md"
QAMD="$GLD/commands/qa.md"
hasfx "M11-①: 3.5a 트립와이어의 before 판독이 파일로 남는다" "$ESMD" 'mutation-before.json'
hasfx "M11-①: 파일이 없으면 기억으로 대체하지 않는다" "$ESMD" 'do not fall back to memory'
hasfx "M11-②: 정체 가드가 audit record 에서 사유를 읽는다" "$STMD" "read them from the Issue's"
# ⚠ **execute 경로로 스코프돼야 한다.** 무조건이면 audit record 가 없는 무인 `test`/`qa`
# 루프백이 매번 `OK PAUSE: needs-human` 으로 멈춘다 — 품질 조치가 무인 경로에 정지 결함을
# 만드는 모양이고, 같은 파일이 세 줄 위에서 「종전대로 동작한다」고 적는 것과도 모순이었다.
hasfx "M11-②: 그 규칙의 범위 — 기록이 둘(audit record · loop-back record)" "$STMD" '**Scope — where the "before" half is read.**'
# ⚠⚠ **정합성 — 읽는 쪽과 쓰는 쪽.** 정체 가드는 **두 축**(역할 · 감사자)을 비교하는데,
# 기록 스키마가 감사자 findings 만 적으면 역할 축은 여전히 컨텍스트에만 산다 = 절반만 닫힌다.
if grep -qF -- 'record this attempt' "$ESMD" && grep -qF -- 'ROLE axis too' "$ESMD"; then
  ok "M11-②: 기록 스키마에 **역할 축**도 있다 (읽는 쪽 ↔ 쓰는 쪽 정합)"
else
  bad "M11-②: 기록 스키마에 역할 축도 있다" "있음" "없음 — `_stagnation.md` 가 읽으라는 것을 `_execute_spine.md` 가 쓰지 않는다"
fi
hasfx "M11-②: 숫자 상한이 대체재가 아니라고 못박는다" "$STMD" 'a **backstop, not a substitute**'
hasfx "M11-③: PR 본문을 파일로 먼저 받는다" "$QAMD" 'gld-pr-<PR_NUM>-body.md'
hasfx "M11-③: 파일이 비면 쓰지 않는다" "$QAMD" '**If the file is missing or empty, do NOT write**'
# ⚠ **정합성 검사** — 존재 검사만으로는 부족하다. 세 곳이 **같은 근거(8.5%)** 를 들어야 한다.
# 한 축만 고치고 나머지를 두는 것이 이 작업에서 가장 자주 재발한 결함이다.
M11N=0
for _f in "$ESMD" "$STMD" "$QAMD"; do
  grep -qE -- '(^|[^0-9.])8\.5%' "$_f" && M11N=$((M11N+1))   # ⚠ -F 였을 때 98.5% 도 통과했다
done
if [ "$M11N" -eq 3 ]; then
  ok "M11: 세 곳이 같은 근거(유인 8.5% 압축)를 든다"
else
  bad "M11: 세 곳이 같은 근거를 든다" "3곳" "${M11N}곳 — 한 축만 고치고 나머지를 뒀다"
fi

CONFMD="$GLD/commands/config.md"
INITMD="$GLD/commands/init.md"

# ── 19. 상태 토큰이 다섯 파일에 있고, plan.md 는 인접성 스코프 안에 있는가 ────────
# ⚠ 명세는 **여섯** 파일(+ `design/guild/02-sprint.md`)을 요구하지만 `design/` 는 이 플러그인이
#   배포하는 트리가 아니고 리포에서 gitignore 된다 — 여기서 단정할 수 있는 것은 다섯이다.
#   여섯째는 설계 문서 자체의 정정이고, 검사할 파일이 없다는 사실을 여기 적어 둔다.
for F in "$HANDOFF" "$DAILY" "$RETRO" "$PLAN" "$BOARD"; do
  hasfx "창 토큰이 $(basename "$F") 에 열거돼 있다" "$F" "waiting-for-window-"
done
# ⚠ 인접성 스코프. 파일 전체 grep 이면 다른 언급(예: 거부 문구)이 남아 통과하고, `plan.md:23`
#   의 `proceed` 로 떨어지는 파괴적 변이를 놓친다 — 6라운드 실측.
cat > "$WORK3/adj.py" <<'ADJPY'
import re, sys
src = open(sys.argv[1]).read()
anchor, needle, span = sys.argv[2], sys.argv[3], int(sys.argv[4])
i = src.find(anchor)
if i < 0:
    print("MISSING anchor: %s" % anchor); raise SystemExit(0)
print("OK" if needle in src[i:i + len(anchor) + span]
      else "NOT within %d chars of `%s`" % (span, anchor))
ADJPY

cat > "$WORK3/blk.py" <<'BLKPY'
import sys
src = open(sys.argv[1]).read()
start, end, needle = sys.argv[2], sys.argv[3], sys.argv[4]
i = src.find(start)
if i < 0:
    print("MISSING block start: %s" % start); raise SystemExit(0)
j = src.find(end, i)
if j < 0:
    print("MISSING block end: %s" % end); raise SystemExit(0)
print("OK" if needle in src[i:j] else "NOT inside the block: %s" % needle)
BLKPY
ADJ="$("$PY" "$WORK3/adj.py" "$PLAN" '`rate-limited-*`' 'waiting-for-window-' 60)"
if [ "$ADJ" = OK ]; then
  ok "plan.md: 창 토큰이 \`rate-limited-*\` 열거 **안**에 있다 (인접성 스코프)"
else
  bad "plan.md: 창 토큰이 열거 안에 있다" "adjacent" "$ADJ"
fi
ADJ2="$("$PY" "$WORK3/adj.py" "$RETRO" '`rate-limited-*`' 'waiting-for-window-' 60)"
if [ "$ADJ2" = OK ]; then
  ok "retro.md: 창 토큰이 \`rate-limited-*\` 열거 **안**에 있다"
else
  bad "retro.md: 창 토큰이 열거 안에 있다" "adjacent" "$ADJ2"
fi
ADJ3="$("$PY" "$WORK3/adj.py" "$BOARD" '`rate-limited-*`' 'waiting-for-window-' 60)"
if [ "$ADJ3" = OK ]; then
  ok "board.md: 창 토큰이 \`rate-limited-*\` 열거 **안**에 있다"
else
  bad "board.md: 창 토큰이 열거 안에 있다" "adjacent" "$ADJ3"
fi
# halted 사유 다섯이 정본 열거(_handoff Section K)에 있는가
for R in window-invalid marker-unwritable container-lost sigTERM sigHUP; do
  hasfx "_handoff.md: halted 사유 \`$R\` 가 정본에 열거돼 있다" "$HANDOFF" "\`$R\`"
done
hasfx "_handoff.md: 재파생 불가 원장 키에 window 가 있다"     "$HANDOFF" '**`window`**'
hasfx "_handoff.md: 재파생 불가 원장 키에 completion 이 있다" "$HANDOFF" '**`completion`**'

# ── 20. `--duration` 별칭과 알 수 없는 플래그 거부 ────────────────────────────
# ⚠ `--duration` 이 없으면 비플래그 인자가 없다는 이유로 *"재개"* 로 떨어져 **창 없이 24시간
#   무인 run** 이 된다. 요구 원문이 `--duration` 이므로 이것이 가장 개연적인 첫 입력이다.
# ⚠ 파일 전체 grep 으로는 안 된다 — `--duration` 은 거부 메시지·설명·예시에도 나오므로
#   **알려진 플래그 문장**에서 이름을 빼도 통과한다(변이 실측, 이 라운드). 그 문장을 스코프로
#   잡고, 그 안에 셋이 다 있는지 본다.
FLG="$("$PY" "$WORK3/blk.py" "$RUNMD2" 'The known flags are' 'and nothing else' '`--duration`')"
if [ "$FLG" = OK ]; then
  ok "run.md: --duration 이 **알려진 플래그 문장 안**에 열거돼 있다 (요구 원문이 이것이다)"
else
  bad "run.md: --duration 의 위치" "inside the known-flags sentence" "$FLG"
fi
for F in '`--readiness`' '`--window`'; do
  FL="$("$PY" "$WORK3/blk.py" "$RUNMD2" 'The known flags are' 'and nothing else' "$F")"
  if [ "$FL" = OK ]; then ok "run.md: 알려진 플래그 문장에 $F 가 있다"
  else bad "run.md: 알려진 플래그 $F" "inside the sentence" "$FL"; fi
done
hasfx "run.md: 알려진 플래그 목록이 있다"                  "$RUNMD2" 'The known flags are'
hasfx "run.md: 그 밖의 -- 토큰은 거부한다"                 "$RUNMD2" 'Any other `--` token is REFUSED'
hasfx "run.md: 거부 시 유효 목록을 찍는다"                 "$RUNMD2" 'FAIL: unknown flag'
hasfx "run.md: 플래그 값 토큰은 비플래그 인자로 세지 않는다" "$RUNMD2" 'is not counted as a non-flag argument'
hasfx "run.md: 공백과 = 를 둘 다 받는다"                   "$RUNMD2" 'accept BOTH a space and an `=`'
hasfx "run.md: 남는 비플래그 토큰도 거부한다"              "$RUNMD2" 'A leftover non-flag token is not ignored'
lacksfx "run.md: 옛 \$1 계약 한 줄이 남아 있지 않다"       "$RUNMD2" '`--readiness` = print the preflight verdict and stop.'

# ── 21. `--readiness` 예외가 **인자 계약 블록 안**인가 (블록 스코프) ──────────
# ⚠ `:27` 의 *"`--readiness` prints this table and stops"* 는 표의 캡션이고 개정과 무관하게
#   남으므로, 파일 전체 grep 은 파괴적 변이(계약 블록에서 예외를 빼는 것)를 놓친다.
BLK="$("$PY" "$WORK3/blk.py" "$RUNMD2" '**Arguments.**' '## Phase 0' \
        '`--readiness` is the one exception')"
if [ "$BLK" = OK ]; then
  ok "run.md: --readiness 예외가 인자 계약 블록 **안**에 있다 (블록 스코프)"
else
  bad "run.md: --readiness 예외의 위치" "inside the argument block" "$BLK"
fi

# ── 22. 검증 규칙 **세 벌**이 같은 리터럴 예시를 쓰는가 ──────────────────────
# ⚠ 스크립트의 `case` 글롭이 느슨해져도 산문은 그대로다 — 그래서 셋을 한 리터럴로 묶는다.
W_LIT='HH:MM-HH:MM (24h, zero-padded)'
W_LIT_MISS=""
for F in "$RUNMD2" "$CONFMD" "$TPL"; do
  grep -qF -- "$W_LIT" "$F" || W_LIT_MISS="$W_LIT_MISS $(basename "$F")"
done
if [ -z "$W_LIT_MISS" ]; then
  ok "검증 규칙 세 벌이 같은 리터럴을 쓴다 (run.md · config.md · 템플릿)"
else
  bad "검증 규칙 세 벌의 리터럴" "all three" "missing:$W_LIT_MISS"
fi

# ── 23. daily 의 다섯 행 판정표 ──────────────────────────────────────────────
# ⚠ 표가 step 2 에 놓여도 문자열 grep 은 통과한다 — 조건 헤딩 **안**인지 본다. step 2/3 은
#   모든 state 에 대해 host/pid 를 읽으므로, 거기 두면 창을 안 쓰는 모든 run 이 host 불일치
#   시 잘못된 판정을 받는다.
DBLK="$("$PY" "$WORK3/blk.py" "$DAILY" \
        '#### `state: waiting-for-window-*`' '**6. Termination' 'ps -p <pid> -o command=')"
if [ "$DBLK" = OK ]; then
  ok "daily.md: 생사 판정표가 waiting-for-window-* **조건 헤딩 안**에 있다"
else
  bad "daily.md: 판정표의 스코프" "inside the conditional heading" "$DBLK"
fi
for ROW in '확인할 수 없습니다' '죽었습니다' '정상 대기 중'; do
  DR="$("$PY" "$WORK3/blk.py" "$DAILY" '#### `state: waiting-for-window-*`' '**6. Termination' "$ROW")"
  if [ "$DR" = OK ]; then ok "daily.md: 판정표에 \`$ROW\` 행이 있다"
  else bad "daily.md: 판정표 행 \`$ROW\`" "present in the block" "$DR"; fi
done
# ⚠ 문자열은 `.gld-sprint-` 다. `sprint-supervisor` 는 **템플릿 파일명**이고 `ps` 출력에 절대
#   나타나지 않는다 — 그것을 찾으면 LIVE 감독자가 "pid 재사용 → 없는 것으로 취급" 으로 떨어진다.
DGL="$("$PY" "$WORK3/blk.py" "$DAILY" '#### `state: waiting-for-window-*`' '**6. Termination' '.gld-sprint-')"
if [ "$DGL" = OK ]; then
  ok "daily.md: 판정표가 \`.gld-sprint-\` 를 찾는다 (sprint-supervisor 가 아니다)"
else
  bad "daily.md: 판정표의 매치 문자열" ".gld-sprint-" "$DGL"
fi
lacksfx "daily.md: 판정표가 템플릿 파일명을 찾지 않는다" "$DAILY" 'contains `sprint-supervisor`'
hasfx   "daily.md: 두 사본이 다른 이유를 daily.md 안에 적었다" "$DAILY" \
        'is the **template** filename and never appears in that'
hasfx   "daily.md: 뒤의 셋을 죽었다고 뭉개지 말라고 말한다" "$DAILY" \
        'Do not collapse the last three'

# ── 24. caffeinate 이중 게이트 ───────────────────────────────────────────────
hasfx "run.md: caffeinate 를 감싸는 조건이 이중이다" "$RUNMD2" 'a DOUBLE gate'
hasfx "run.md: 창이 설정됐을 때만"                   "$RUNMD2" '**a window is set**'
hasfx "run.md: command -v 성공 시에만"               "$RUNMD2" 'command -v caffeinate'
hasfx "run.md: -i 만 쓴다"                           "$RUNMD2" '`-i` only'
hasfx "run.md: 뚜껑을 닫으면 못 막는다고 적었다"      "$RUNMD2" 'a closed lid sleeps regardless'
lacksfx "run.md: caffeinate -u 를 쓰지 않는다"        "$RUNMD2" 'caffeinate -u'
lacksfx "run.md: caffeinate -s 를 쓰지 않는다"        "$RUNMD2" 'caffeinate -s'

# ── 25. config.md 의 지점들 + init.md 의 키 집합 교차검증 (방어 ④) ───────────
hasfx "config.md: 셋터 요약 목록에 --window= 가 있다" "$CONFMD" '- `--window=<HH:MM-HH:MM|none>`'
hasfx "config.md: 렌더에 window 가 있다"              "$CONFMD" 'window=<HH:MM-HH:MM|미설정>'
hasfx "config.md: 전용 섹션이 있다"                   "$CONFMD" '### `--window=<HH:MM-HH:MM|none>`'
hasfx "config.md: M1 스키마에 window 가 있다"         "$CONFMD" 'history[], board, window}'
hasfx "config.md: 갭 문장이 window 를 제외한다"       "$CONFMD" '`sprint.window` does **not**'
# ⚠ **검증 규칙이 실제로 사는 곳**은 "Set a value" step 2 의 목록이고, 그것이 비면 위의
#   나머지 여섯 지점이 전부 발화할 대상이 없다. 블록 스코프로 본다.
# ⚠ 리터럴이 **블록 안에 있는가**로는 안 된다 — 그 블록의 설명문에도 같은 리터럴이 있어서
#   규칙 줄을 느슨하게 고쳐도 통과했다(변이 실측, 이 라운드). 규칙 **줄 자체**를 잡는다.
CBLK="$("$PY" "$WORK3/blk.py" "$CONFMD" '2. Validate the key/value:' '3. Update the key' \
        '- `window` — **`HH:MM-HH:MM (24h, zero-padded)`**')"
if [ "$CBLK" = OK ]; then
  ok "config.md: 창 검증 규칙이 \"Set a value\" step 2 의 검증 목록 **안**에 있다"
else
  bad "config.md: 검증 규칙의 위치" "inside the validate list" "$CBLK"
fi
CBLK2="$("$PY" "$WORK3/blk.py" "$CONFMD" '2. Validate the key/value:' '3. Update the key' \
        'start == end')"
if [ "$CBLK2" = OK ]; then
  ok "config.md: 그 목록이 start == end 도 거부한다"
else
  bad "config.md: start == end 거부" "inside the validate list" "$CBLK2"
fi
# init.md 의 sprint 객체와 config.md 의 스키마에서 키 집합을 뽑아 교차검증
cat > "$WORK3/sprintkeys.py" <<'SKPY'
import re, sys
init, conf = open(sys.argv[1]).read(), open(sys.argv[2]).read()
m = re.search(r'"sprint":\s*\{(.*?)\}', init, re.S)
if not m:
    print('ERR init.md has no "sprint" object'); raise SystemExit(0)
body = m.group(1)
ikeys = set(re.findall(r'"([a-z_]+)":', body))
m2 = re.search(r"sprint\{([^}]*)\}", conf)
if not m2:
    print("ERR config.md has no sprint schema"); raise SystemExit(0)
ckeys = set(k.strip().replace("[]", "") for k in m2.group(1).split(","))
problems = []
if "window" not in ikeys:
    problems.append('init.md\'s "sprint" object has no `window` key')
elif not re.search(r'"window"\s*:\s*null', body):
    problems.append("init.md's `window` default is not `null` — the window is opt-in and a "
                    "windowless run must be byte-identical to today")
for k in sorted(ikeys - ckeys):
    problems.append("init.md writes `%s` but config.md's schema does not list it" % k)
for k in sorted(ckeys - ikeys):
    problems.append("config.md's schema lists `%s` but init.md does not write it" % k)
print("OK %d keys" % len(ikeys) if not problems else "; ".join(problems))
SKPY
SK="$("$PY" "$WORK3/sprintkeys.py" "$INITMD" "$CONFMD")"
case "$SK" in
  OK*) ok "init.md 의 sprint 키 집합이 config.md 스키마와 일치하고 window 기본값이 null ($SK)" ;;
  *)   bad "sprint 키 집합 교차검증" "the same set, window=null" "$SK" ;;
esac

# ── 26. `.git/info/exclude` 열거가 **세 줄 그대로**인가 ──────────────────────
# ⚠ 창 파일을 여기 넣으면 **창을 안 쓰는 모든 run** 이 존재하지 않을 파일의 ignore 줄을 사람
#   repo 에 영구히 쓰고 트래커마다 누적된다. `.board` 도 오늘 거기 없다.
EXC_N="$(grep -c '^  for E in ".claude/guild/.gld-sprint-\$TRACKER.sh" ".claude/guild/.sprint-logs" ".claude/guild/memory"; do$' "$TPL" || true)"
if [ "$EXC_N" = "1" ]; then
  ok "template: info/exclude 루프가 세 항목 그대로다 (창 파일도 .board 도 넣지 않는다)"
else
  bad "template: info/exclude 열거" "the same three entries" "the loop line changed"
fi
lacksfx "run.md: info/exclude 에 창 파일을 넣지 않는다고 적었다는 것" "$RUNMD2" \
        '`.gld-sprint-<tracker>.window` to `.git/info/exclude`'
hasfx "run.md: 그 이유를 적었다" "$RUNMD2" 'Nothing is added to `.git/info/exclude`'
hasfx "run.md: '두 곳'의 in full 목록에 창 파일이 있다" "$RUNMD2" '`.gld-sprint-<tracker>.window`'
W_INFULL="$(grep -c 'gld-sprint-<tracker>.window' "$RUNMD2" || true)"
if [ "$W_INFULL" -ge 3 ]; then
  ok "run.md: 창 파일이 최소 세 곳(step 2c + in full 목록 둘)에 열거돼 있다"
else
  bad "run.md: 창 파일 열거 개수" ">=3" "found $W_INFULL"
fi

# ── 28. :151-152 주석 정정이 **결론을 유지**하는가 (주석의 *주장*을 판정) ─────
# ⚠ 정정문이 *"`&&` 도 안전하다"* 로 쓰이면 다음 사람이 되돌리고, 그 줄이 함수 끝으로 이동하는
#   순간 **보드 없는 run = 기존 사용자 전원**이 죽는다. `sig.py` 의 선례를 따른다.
cat > "$WORK3/ifclaim.py" <<'IFPY'
import re, sys
src = open(sys.argv[1]).read()
m = re.search(r"((?:^#.*\n)+)^if \[ -n \"\$BOARD_NUMBER\" \]; then BOARD_WAS_ON=1; fi", src, re.M)
if not m:
    print("MISSING the BOARD_WAS_ON line or its comment block"); raise SystemExit(0)
block = m.group(1)
problems = []
if not re.search(r"`if`, not", block):
    problems.append("the block no longer states the `if` rule")
if not re.search(r"[Kk]eep the `if`|Do not \"simplify\"|conclusion is unchanged", block):
    problems.append("the corrected comment does not KEEP the conclusion (use `if`) — the next "
                    "person will revert it on the old, false reasoning")
if re.search(r"`&&`\s+(is|are)\s+safe|also safe|equally safe", block):
    problems.append("the comment now says `&&` is safe, which invites the revert")
if not re.search(r"last statement|as its last|function\b.*last|WHERE IT SITS", block):
    problems.append("the correction does not say WHY it is position-dependent")
print("OK" if not problems else "; ".join(problems))
IFPY
IFC="$("$PY" "$WORK3/ifclaim.py" "$TPL")"
if [ "$IFC" = OK ]; then
  ok "template: :151 주석 정정이 이유를 고치면서 결론(\`if\` 를 쓸 것)을 유지한다"
else
  bad "template: :151 주석의 주장" "OK" "$IFC"
fi

# ── 29. run.md Phase 4 의 halted:* 아암 ──────────────────────────────────────
# ⚠ 없으면 오타로 즉사한 run 에 대해 사람이 *"done 0 / failed 0"* 류의 무의미한 보고를 본다.
PBLK="$("$PY" "$WORK3/blk.py" "$RUNMD2" '## Phase 4' '## Return' 'halted:window-invalid')"
if [ "$PBLK" = OK ]; then
  ok "run.md: Phase 4 에 halted:window-invalid 아암이 있다"
else
  bad "run.md: Phase 4 의 halted 아암" "inside Phase 4" "$PBLK"
fi
for R in marker-unwritable container-lost sigTERM interrupted; do
  PB="$("$PY" "$WORK3/blk.py" "$RUNMD2" '## Phase 4' '## Return' "halted:$R")"
  if [ "$PB" = OK ]; then ok "run.md: Phase 4 에 halted:$R 아암이 있다"
  else bad "run.md: Phase 4 의 halted:$R" "inside Phase 4" "$PB"; fi
done
hasfx "run.md: halted 를 정상 카운트만으로 보고하지 말라고 말한다" "$RUNMD2" \
      'Never report a `halted:*` run with the normal counts alone'
hasfx "run.md: marker-unwritable 의 사유가 원장에만 있을 수 있다고 적었다" "$RUNMD2" \
      'ledger.json'

# ── 30. *"완주 통지는 없다"* 가 run.md step 6 과 daily 둘에 ──────────────────
RB="$("$PY" "$WORK3/blk.py" "$RUNMD2" '6. Report: sprint number' '**What the supervisor does' \
      '완주 통지는 없습니다')"
if [ "$RB" = OK ]; then
  ok "run.md: '완주 통지는 없습니다' 가 Phase 3 step 6 안에 있다"
else
  bad "run.md: 완주 통지 문장의 위치" "inside step 6" "$RB"
fi
hasfx "daily.md: 완주 통지가 없다는 사실을 적었다" "$DAILY" 'There is no completion notification'
hasfx "daily.md: state: finished 시 completion 을 렌더한다" "$DAILY" 'completion` key'
hasfx "daily.md: 워크트리 판정은 git status 로 재도출한다" "$DAILY" 're-derive the source-vs-docs judgement'
hasfx "daily.md: paused_issues 를 먼저 렌더한다" "$DAILY" '`paused_issues` first'
hasfx "daily.md: kept_worktrees 의 reason 을 렌더한다" "$DAILY" 'is `{path, reason}`'
hasfx "daily.md: elapsed_s 를 시:분으로 렌더한다" "$DAILY" 'as h:m'
hasfx "daily.md: board_last_write 신선도 예외가 있다" "$DAILY" '투영은 <HH:MM>에 재개'
hasfx "daily.md: kill <pid> 안내가 있다" "$DAILY" '중단: `kill <pid>`'

# ── 31. Phase 0 의 GH_TOKEN + 창 동시 조건 경고 ─────────────────────────────
GBLK="$("$PY" "$WORK3/blk.py" "$RUNMD2" '### Phase 0b' '## Phase 1' 'GH_TOKEN')"
if [ "$GBLK" = OK ]; then
  ok "run.md: Phase 0 에 GH_TOKEN + 창 동시 조건 경고가 있다"
else
  bad "run.md: GH_TOKEN 경고의 위치" "inside Phase 0" "$GBLK"
fi
hasfx "run.md: 18 이 영구 만료를 흡수할 수 없다고 적었다" "$RUNMD2" 'cannot absorb a permanent'

# ── 33. 창 길이 WARN · DST 경고가 **마지막 ask 앞**이고 판별 케이스가 박혔는가 ─
# ⚠ Phase 3 step 6 에 두면 배경 작업 시작 **후**에 경고가 나온다.
WBLK="$("$PY" "$WORK3/blk.py" "$RUNMD2" '### Phase 0b' 'Finally, show the warnings' \
        'shorter than 120 minutes')"
if [ "$WBLK" = OK ]; then
  ok "run.md: 창 길이 WARN 이 Phase 0 의 마지막 ask **앞**에 있다"
else
  bad "run.md: 창 길이 WARN 의 위치" "before the final ask" "$WBLK"
fi
DBL="$("$PY" "$WORK3/blk.py" "$RUNMD2" '### Phase 0b' 'Finally, show the warnings' 'DST')"
if [ "$DBL" = OK ]; then
  ok "run.md: DST 경고가 같은 자리에 있다"
else
  bad "run.md: DST 경고의 위치" "before the final ask" "$DBL"
fi
# ⚠ 판별 케이스를 리터럴로 박아 grep 가능하게 한다 — HHMM 차로 계산하면 둘의 답이 갈린다.
for C in '23:00-00:30' '00:30-02:00'; do
  CB="$("$PY" "$WORK3/blk.py" "$RUNMD2" '### Phase 0b' 'Finally, show the warnings' "$C")"
  if [ "$CB" = OK ]; then ok "run.md: 판별 케이스 \`$C\` 가 산문에 리터럴로 박혔다"
  else bad "run.md: 판별 케이스 \`$C\`" "literal in the prose" "$CB"; fi
done
hasfx "run.md: 분으로 센다고 말한다"                  "$RUNMD2" 'Count MINUTES, not the `HHMM` difference'
hasfx "run.md: 스크립트는 길이를 판정하지 않는다"     "$RUNMD2" 'does not judge window length'
# ⚠ 그리고 스크립트에 실제로 없어야 한다 — 두 곳이 판정하면 다른 답을 낼 수 있다.
if grep -qE '(120|7200)' "$TPL" && grep -q 'window' "$TPL" && grep -qE 'WIN_(START|END).*120' "$TPL"; then
  bad "template: 스크립트가 창 길이를 판정하지 않는다" "no length judgement" "found a 120-minute test"
else
  ok "template: 스크립트가 창 길이를 판정하지 않는다 (판정자는 run.md 하나뿐)"
fi
hasfx "run.md: N nights 를 범위로 낸다"               "$RUNMD2" 'as a RANGE'
hasfx "run.md: 낮의 편집은 무효라고 말한다"           "$RUNMD2" '낮의 편집은 무효입니다'
hasfx "run.md: 창 있는 run 의 ask 가 네 가지를 말한다" "$RUNMD2" 'the ask must
name four things'

# ── 35. plan-hash 마커가 window·completion 을 보존하는가 ─────────────────────
# ⚠ 지우면 다음 재개에 창이 사라지고 **낮에 무제한 무인 run** 이 된다. 사람에게 가는 신호가
#   하나도 없다 — `window` 를 지우는 writer 가 둘이므로 `:75` 만 가드하면 안 된다.
HBLK="$("$PY" "$WORK3/blk.py" "$RUNMD2" 'halted:plan-hash-mismatch' '5. **Rebuild the queue' \
        'PRESERVE THE MARKER')"
if [ "$HBLK" = OK ]; then
  ok "run.md: plan-hash 마커가 기존 키를 보존하라고 명시한다"
else
  bad "run.md: plan-hash 마커의 보존 규칙" "inside step 4" "$HBLK"
fi
for K in window completion; do
  HB="$("$PY" "$WORK3/blk.py" "$RUNMD2" 'halted:plan-hash-mismatch' '5. **Rebuild the queue' "\`$K\`")"
  if [ "$HB" = OK ]; then ok "run.md: 보존 대상에 \`$K\` 가 리터럴로 열거돼 있다"
  else bad "run.md: 보존 대상 \`$K\`" "enumerated in step 4" "$HB"; fi
done
# 재개 경로: 창 파일 복원이 run 필드 clear **앞**이고, 복원 실패 시 rm -f 대신 사람에게 묻는다
hasfx "run.md: 재개 시 창 파일을 먼저 복원한다"   "$RUNMD2" 'restore the window file from the marker'
hasfx "run.md: window 는 clear 대상이 아니다"     "$RUNMD2" '`window` is not a run field'
hasfx "run.md: 복원 실패 시 사람에게 묻는다"      "$RUNMD2" '**ask the human** instead of deleting it'
hasfx "run.md: step 2c 가 창 파일을 쓴다"          "$RUNMD2" '2c. **Write the run window file**'
hasfx "run.md: 창이 없으면 rm -f 한다"             "$RUNMD2" 'rm -f .claude/guild/.gld-sprint-<tracker>.window'
hasfx "run.md: 거부 문구에 날짜가 들어간다"        "$RUNMD2" '시작 YYYY-MM-DD HH:MM'

# ── 36. SKILL.md 축약이 규범과 라우팅을 잃지 않았는가 ────────────────────────
# 이 스위트는 지금까지 SKILL.md 를 stale-phrase grep 의 입력으로만 봤다. C 가 그 파일의
# 61% 를 README 로 옮기므로, 남겨야 하는 것이 남았는지 볼 검사가 필요하다.
SKILLMD="$GLD/SKILL.md"

# (a) 라우팅 표의 valid-command 가 전부 실재하는 파일인가.
MISSING=""; NCMD=0
for c in $(sed -n 's/^- Valid commands: //p' "$SKILLMD" | tr -d '`' | tr ',' ' '); do
  NCMD=$((NCMD+1)); [ -f "$GLD/commands/$c.md" ] || MISSING="$MISSING $c"
done
# ⚠ 바닥선이 없으면 라우팅 줄을 통째로 지워도 빈 목록이 "전부 해석됨"으로 통과한다 — 이 검사가
#   막으려던 사고(축약이 남겨야 할 것을 지움)가 정확히 그 형태다. 오늘 25개.
if [ "$NCMD" -lt 20 ]; then bad "SKILL.md: 라우팅 표가 남아 있다" "커맨드 20개 이상" "$NCMD 개"
elif [ -z "$MISSING" ]; then ok "SKILL.md: valid-command $NCMD 개가 전부 commands/*.md 로 해석된다"
else bad "SKILL.md: valid-command 가 전부 해석된다" "모두 존재" "없음:$MISSING"; fi

# (b) atom 열거 줄의 경로가 전부 실재하는가. 줄 번호로 고정하지 않는다 — C 가 민다.
BADATOM=""; NATOM=0
for a in $(grep -o 'commands/atoms/_[a-z_]*\.md' "$SKILLMD" | sort -u); do
  NATOM=$((NATOM+1)); [ -f "$GLD/$a" ] || BADATOM="$BADATOM $a"
done
# 같은 바닥선. atom 열거를 산문으로 바꿔치기해도 0건이 "전부 resolve"로 통과했다. 오늘 10개.
if [ "$NATOM" -lt 8 ]; then bad "SKILL.md: atom 열거가 남아 있다" "8개 이상" "$NATOM 개"
elif [ -z "$BADATOM" ]; then ok "SKILL.md: atom 경로 $NATOM 개가 전부 resolve 된다"
else bad "SKILL.md: atom 경로가 전부 resolve 된다" "모두 존재" "없음:$BADATOM"; fi

# (c) 규범 3건이 SKILL.md 에 남아 있는가. 이주가 아니라 유지가 결정이었다 —
#     README 로 옮기면 런타임에 도달하지 않는다.
hasfx "SKILL.md: 용어 규범(Guild, not org)이 남아 있다" "$SKILLMD" 'Do NOT surface the internal shorthand'
hasfx "SKILL.md: 로스터 규범(디렉터리가 로스터)이 남아 있다" "$SKILLMD" 'that directory is the roster'
hasfx "SKILL.md: commit/gitignore 규범이 남아 있다" "$SKILLMD" 'gitignore** `.claude/guild/memory/`'

# (d) 삭제된 절을 가리키던 교차참조가 갱신됐는가.
lacksfx "retro.md: --guard-config 근거를 SKILL.md 로 인용하지 않는다" "$GLD/commands/sprint/retro.md" 'confirmation prompt (`SKILL.md`)'
lacksfx "_model_tiering.md: 삭제된 SKILL.md 절을 인용하지 않는다" "$GLD/commands/atoms/_model_tiering.md" "Operationalizes SKILL.md's"

# (e) 사용자 대면 산문에 내부 약어 org 가 남지 않았는가 (백틱 CLI 토큰은 대상 아님).
lacksfx "help.md: 산문 org 가 남지 않았다" "$GLD/commands/help.md" 'Terminal snapshot: org'
lacksfx "monitoring.md: 산문 org 가 남지 않았다" "$GLD/commands/monitoring.md" 'an org table'

# (f) README 3종의 절 개수가 같은가 — ja/ko 가 조용히 짧아지는 것을 막는다.
RM="$GLD/../../README.md"; RK="$GLD/../../README.ko.md"; RJ="$GLD/../../README.ja.md"
NM=$(grep -c '^## ' "$RM"); NK=$(grep -c '^## ' "$RK"); NJ=$(grep -c '^## ' "$RJ")
if [ "$NM" = "$NK" ] && [ "$NM" = "$NJ" ]; then ok "README 3종의 절 개수가 같다 ($NM)"
else bad "README 3종의 절 개수가 같다" "동일" "en=$NM ko=$NK ja=$NJ"; fi
# ⚠ `## ` 만 세면 이 검사는 자기가 막으려던 드리프트를 못 본다. C 가 옮긴 본문은 전부 `### `
#   하위 절이므로, ja/ko 가 그것을 "영문을 보라"는 요약 한 덩어리로 대체해도 `## ` 수는 그대로다.
#   실제로 그렇게 됐다 — en=4 ko=0 ja=0 인 채 그린이었다. 하위 절까지 센다.
SM=$(grep -c '^### ' "$RM"); SK=$(grep -c '^### ' "$RK"); SJ=$(grep -c '^### ' "$RJ")
if [ "$SM" = "$SK" ] && [ "$SM" = "$SJ" ]; then ok "README 3종의 하위 절(### ) 개수가 같다 ($SM)"
else bad "README 3종의 하위 절 개수가 같다" "동일" "en=$SM ko=$SK ja=$SJ"; fi
# 그리고 번역본이 영문을 가리키는 껍데기로 되돌아가지 않았는가 — 절 수만으로는 못 잡는 모양이다.
lacksfx "README.ko: Reference 가 영문 참조 요약으로 되돌아가지 않았다" "$RK" '이 요약은 각 항목의 존재와 위치만'
lacksfx "README.ja: Reference 가 영문 참조 요약으로 되돌아가지 않았다" "$RJ" 'この要約は各項目の存在と位置のみ'

# (g) A 가 남긴 run.md 계약 셀 — 어느 스위트도 보지 않던 곳이다.
# `--install-cmd` 를 "shell-quoted" 로 되돌리면 모든 워크트리의 의존성 설치가 깨지는데,
# 렌더러는 정상 종료하고 bash -n 도 조용하다. 계약은 이 표에만 적혀 있으므로 여기서 고정한다.
hasfx "run.md: --install-cmd 가 raw 로 넘어간다는 계약이 남아 있다" "$RUNMD2" 'passed **raw and unquoted**'
lacksfx "run.md: --install-cmd 를 pre-quote 하라고 다시 적지 않았다" "$RUNMD2" 'shell-quoted'
hasfx "run.md: 메타문자 거부의 근거(simple command)가 표에 남아 있다" "$RUNMD2" 'must be a **simple command**'
# 그리고 복합 명령의 *처방* — 파이썬 거부는 이중 안전장치일 뿐 구제책이 아니다. 이 지시가
# 없으면 레거시 설치에서 step 2 가 non-zero 로 끝나고 2d 가 실행을 세운다.
hasfx "run.md: 레거시 복합 config.commands 정규화 지시가 있다" "$RUNMD2" 'Split such a value yourself before building argv'
hasfx "run.md: 정규화가 처방이고 파이썬 거부는 이중 안전장치임을 밝힌다" "$RUNMD2" 'second safety net behind it, not the remedy'
hasfx "run.md: --human-repo 거부 두 건이 표에 적혀 있다" "$RUNMD2" 'Rejected if it is **not absolute**'
# ⚠ 세 곳이 같은 목록을 말한다: `init.md:163`(계약) · `render_supervisor.py` 의 `_METACHAR`(집행)
#   · `run.md`(문서). 이들을 묶는 검사가 없었기 때문에 연속 두 릴리스가 정규식만 넓혔고,
#   `run.md` 는 옛 목록을 그대로 두었다. 결과는 `eslint src/**/*.ts` 처럼 init 이 허용하는 값을
#   가진 레포에서 sprint 가 기동 불가가 된 것이다 — 라운드 5 가 잡았다. 셋을 함께 고정한다.
RSPY="$GLD/commands/atoms/render_supervisor.py"
hasfx "render_supervisor.py: _METACHAR 가 init.md 목록과 정확히 같다" "$RSPY" \
  '_METACHAR = re.compile(r"\$\(|`|&&|\|\||[|;<>&\n]")'
lacksfx "render_supervisor.py: 글롭을 다시 막지 않았다 (과잉 차단 회귀)" "$RSPY" '*?{}'
# ⚠ 파일을 **열거하는** 검사는 세 라운드 연속으로 사이트를 놓쳤다: 라운드 6 은 다섯 중 셋을
#   맞췄고, 라운드 7 은 "다섯 곳" 을 훑어 일곱 중 다섯을 맞췄으며, 그때 놓친 하나는 라운드 6 이
#   직접 쓴 줄이었다. 목록을 손으로 적는 한 같은 일이 반복된다.
#   → **발견하는** 검사로 바꾼다. 트리 전체를 훑어 금지 목록처럼 생긴 줄을 전부 찾고, 그것이
#     `config.commands` 계약을 말하는 것이면 정본 열거와 일치할 것을 요구한다. 분류할 수 없는
#     사이트는 **통과가 아니라 실패** 다 — 새 사이트가 조용히 생기는 것을 막는 유일한 방법이다.
cat > "$WORK3/banlist.py" <<'PYBAN'
import os, sys
gld = sys.argv[1]
# 정본 아홉 항목. 각 항목마다 **허용되는 표기** 를 함께 적는다 — 같은 규칙을 영문/한글로,
# 낱말로/기호로 적은 판이 실제로 공존하고, 그것들은 전부 정당하다.
ITEMS = [
    ("substitution", ["$(...)", "$(…)"]),
    ("backtick",     ["backtick", "백틱", "`..`", "`…`"]),
    ("&&",           ["⺠AND⺠"]),
    ("||",           ["⺠OR⺠"]),
    ("|",            ["|"]),
    (";",            [";"]),
    ("&",            ["&"]),
    ("newline",      ["newline", "개행", "\\n"]),
    ("redirection",  ["redirection", "리다이렉션", "`<`, `>`"]),
]
# 금지 목록을 **도입하는** 어구. 토큰 개수로 찾으면 실제 셸 코드가 12건 오검출된다.
LEAD = ("MUST NOT contain", "must not contain", "never contains", "never contain",
        "forbids", "forbid ", "disallow", "rejects", "거부한다", "금지하는", "금지한다",
        "ban list", "허용하지 않는")
# `commands.*` 계약을 말하고 있다는 표지 — LEAD 는 있는데 `$(...)` 가 없을 때 후보로 남길지 정한다.
CONFIGWORD = ("commands.*", "config.commands", "commands.test", "stored command", "stored form",
              "--install-cmd", "INSTALL_CMDS", "config normalis", "config normaliz",
              "저장을 금지", "in these")
BASHRULE = ("_bash_rules.md", "simple calls only", "simple Bash tool call", "one simple call",
            "its own simple Bash", "each its own Bash call", "its own Bash call")
def norm(t):
    # `&&`/`||` 를 먼저 치환해야 낱개 `&`/`|` 검사가 그것들에 흡수되지 않는다.
    return t.replace("&&", "⺠AND⺠").replace("||", "⺠OR⺠")
problems, sites = [], 0
for root, dirs, files in os.walk(gld):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in sorted(files):
        if not f.endswith((".md", ".py", ".sh")):
            continue
        path = os.path.join(root, f)
        rel = os.path.relpath(path, gld)
        lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
        for n, line in enumerate(lines, 1):
            if not any(k in line for k in LEAD):
                continue
            # 열거가 두 줄에 걸치는 곳이 있다(run.md 산문, die() 문자열). **앞이 아니라 뒤로만**
            # 본다 — 예전 판은 앞 줄까지 포함해서, 사이트 자신이 틀린 말을 해도 위/아래 이웃이
            # 항목을 대신 공급하면 통과했다(실측: `render_supervisor.py:62` 는 아홉 항목 전부를
            # 이웃에게서 받고 있었다).
            win = " ".join(lines[n - 1:n + 3])
            # ⚠ 예전 판은 `$(...)` 가 없으면 **조용히 건너뛰었다.** 그래서 가장 위험한 누락 —
            #   열거에서 `$(...)` 자체를 빼는 것 — 이 사이트를 통째로 사라지게 만들었고, 검사는
            #   `OK sites=8` 을 찍었다(실측). 건너뛰기는 통과가 아니다. `commands` 문맥이면
            #   후보로 남겨 실패시키고, 무관한 `forbids`(예: "INV5 forbids leaving the machine")
            #   만 떨어뜨린다.
            if not any(v in win for v in ITEMS[0][1]):
                # ⚠ 문맥 판정은 **히트 줄 자신** 에서만 한다. 창으로 보면 이웃이 문맥을 대신
                #   공급한다 — `run.md:74`("this repo forbids merge commits")가 네 줄 아래의
                #   `config.commands` 를 빌려 후보가 됐다. 토큰 검사에서 고친 것과 같은 결함이
                #   분류기 쪽에 남아 있었다.
                if not any(k in line for k in CONFIGWORD):
                    continue
                sites += 1
                problems.append("%s:%d claims a ban list but does not name `$(...)` — the one "
                                "omission that would hide the site itself" % (rel, n))
                continue
            ctx = "\n".join(lines[max(0, n - 4):n + 2])
            if any(k in ctx for k in BASHRULE) and "commands" not in win:
                continue
            sites += 1
            w = norm(win)
            missing = [name for name, spellings in ITEMS
                       if not any(sp in w for sp in (norm(x) for x in spellings))]
            if missing:
                problems.append("%s:%d enumerates the ban list but omits %s"
                                % (rel, n, ",".join(missing)))
# ⚠ 바닥선이 아니라 **정확값** 이다. `>= 8` 이었을 때 아홉 중 하나가 통째로 사라져도 통과했다.
#   사이트가 늘거나 주는 것은 의도적 변경이므로 이 숫자를 함께 고치게 만든다.
if sites != 9:
    problems.append("found %d ban-list sites, expected exactly 9 — a site appeared or vanished; "
                    "update this number deliberately" % sites)
print("OK sites=%d" % sites if not problems else "PROBLEMS " + " | ".join(problems))
PYBAN
# ── file:line 인용이 여전히 그 줄을 가리키는가 ────────────────────────────────
# 실측: `_bash_rules.md` 의 예외 목록 위에 두 줄만 끼워 넣으면 인용 다섯 건이 전부 어긋나는데
# **열 개 스위트가 전부 rc=0** 이었다. 인용을 지키는 검사가 하나도 없었다.
# 사이트를 손으로 적지 않는다 — 트리에서 찾고, 표에 없는 인용은 통과가 아니라 실패다.
cat > "$WORK3/cites.py" <<'PYCITE'
import os, re, sys
gld = sys.argv[1]
# 인용 -> 그 줄에 반드시 있어야 하는 조각. 새 인용이 생기면 여기에 항목을 추가해야 한다.
EXPECT = {
    ("_bash_rules.md", 204): "A generated OS-level",
    ("_bash_rules.md", 206): "guild:auditor-violation",
    ("board_write.py", 4):  "Why this is code and not a series of Bash calls",
    ("config.md", 15):      "unknown/unsupported config key",
    ("init.md", 163):       "normalized, simple-bash-safe",
    ("run.md", 78):         "Not already running",
    ("sprint.md", 32):      "unknown subcommand",
}
pat = re.compile(r"`?([A-Za-z_][A-Za-z0-9_./-]*\.(?:md|py|sh|json))`?:(\d+)")
idx = {}
found = {}
for root, dirs, files in os.walk(gld):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in files:
        idx.setdefault(f, []).append(os.path.join(root, f))
        if not f.endswith((".md", ".py", ".sh")):
            continue
        path = os.path.join(root, f)
        for line in open(path, encoding="utf-8", errors="replace").read().split("\n"):
            for m in pat.finditer(line):
                found.setdefault((m.group(1), int(m.group(2))), 0)
                found[(m.group(1), int(m.group(2)))] += 1
problems = []
for key, count in sorted(found.items()):
    f, n = key
    if key not in EXPECT:
        problems.append("%s:%d cited %dx but is not in the table — add it or fix the citation"
                        % (f, n, count))
        continue
    tgt = idx.get(f, [])
    if len(tgt) != 1:
        problems.append("%s resolves to %d files; cannot verify :%d" % (f, len(tgt), n))
        continue
    lines = open(tgt[0], encoding="utf-8", errors="replace").read().split("\n")
    if n - 1 >= len(lines):
        problems.append("%s:%d is past EOF (%d lines)" % (f, n, len(lines)))
    elif EXPECT[key] not in lines[n - 1]:
        problems.append("%s:%d no longer contains %r — it drifted" % (f, n, EXPECT[key]))
for key in EXPECT:
    if key not in found:
        problems.append("%s:%d is in the table but nothing cites it — stale table entry" % key)
print("OK %d citations" % len(found) if not problems else "PROBLEMS " + " | ".join(problems))
PYCITE
# ── 페르소나 16종의 센티널과 상태 enum ────────────────────────────────────────
# `_handoff.md` 는 정확한 `>>> RESULT <<<` 센티널이 없는 응답을 **호출 실패** 로 분류한다.
# 그런데 16개 템플릿의 센티널·enum 은 어느 검사도 보지 않았다 — `>>> OUTCOME <<<` 로 바꿔도
# 세 스위트가 전부 그린이었다(실측). 그 역할의 모든 반환이 실패하게 되는 드리프트다.
cat > "$WORK3/persona_enum.py" <<'PYPE'
import glob, os, re, sys
gld = sys.argv[1]
STATUS = {"DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT", "FAIL"}
SENT = ">>> RESULT <<<"
# ⚠ 일반 대문자 토큰으로 뽑는다. 예전 판은 다섯 이름만 열거한 alternation 으로 뽑아 놓고
#   `names <= STATUS` 를 검사했다 — **정의상 항상 참인 죽은 코드** 였다. `| \`DEFERRED\`` 를
#   덧붙여도 열 스위트가 그린이었고, 그 페르소나는 `.claude/agents/` 에 설치되므로 서브에이전트가
#   소비자 규칙이 호출 실패로 분류하는 상태를 반환하게 된다. 같은 파일의 `enum.py` 는 처음부터
#   일반 토큰 + 부정목록으로 옳게 하고 있었다.
# 상태처럼 생겼지만 상태가 아닌 것들 — 확장 시 여기에 추가한다(`enum.py` 와 같은 규칙).
NOT_STATUS = {"RESULT", "OK", "SOURCE", "CANDIDATES", "AC", "PR", "QA", "UI", "UX", "E2E",
              "JSON", "TDD", "HTML", "INV", "README", "BLOCKER", "GLD_UNATTENDED", "CI", "API",
              "ADR", "DOMAIN", "HITL", "LEADER_NOTES", "NEEDS_HUMAN", "PROJECT_NAME"}
# ⚠ 백틱을 요구하지 않는다. 페르소나는 다섯 개를 `` `A | B | C` `` 처럼 **한 쌍의 백틱 안에**
#   적으므로, 백틱 앞머리를 요구하면 첫 이름만 잡혀 열거 형태 판정이 무너진다(실측: full 10 -> 6).
TOKEN = re.compile(r"\b([A-Z][A-Z_]{2,})\b")

problems, checked, full, partial = [], 0, 0, 0
for f in sorted(glob.glob(os.path.join(gld, "templates/agents/*.md"))):
    rel = os.path.basename(f)
    body = open(f, encoding="utf-8").read()
    hits = [l for l in body.split("\n") if "반환 상태" in l or "RESULT" in l]
    if not hits:
        continue
    # ⚠ leader 는 세 번째로 같은 예외다(2차 포인터·개명 원장에 이어). 리더는 스폰되는
    #   서브에이전트가 아니라 메인 세션이 체현하는 역할이라 상태를 **반환하지 않고 읽는다** —
    #   센티널이 없는 것이 맞다. enum 이름 정합은 그대로 검사한다.
    if rel == "leader.md":
        foreign = set(TOKEN.findall(body)) - NOT_STATUS - STATUS
        if foreign:
            problems.append("leader.md names %s, not in the Section C enum"
                            % ",".join(sorted(foreign)))
        if SENT in body:
            problems.append("leader.md gained a `%s` sentinel — it embodies the main session and "
                            "reads statuses, it does not return them" % SENT)
        continue
    checked += 1
    if SENT not in body:
        problems.append("%s mentions a return status but not the exact `%s` sentinel" % (rel, SENT))
    for l in hits:
        # 적합성(외래 토큰)과 형태(다섯 중 몇 개)를 **따로** 센다. 한 집합으로 겸하면
        # 무관한 대문자 토큰 하나가 열거 형태 판정을 통째로 뒤흔든다.
        toks = set(TOKEN.findall(l)) - NOT_STATUS
        foreign = toks - STATUS
        if foreign:
            problems.append("%s names %s, not in the Section C enum"
                            % (rel, ",".join(sorted(foreign))))
        names = toks & STATUS
        if names == STATUS:
            full += 1
        elif names:
            partial += 1
        # 부분집합 위반만 여기서 잡는다. 축소 자체는 정당할 수 있다 — `infra.md` 는 검토 전용이라
        # `DONE | DONE_WITH_CONCERNS | BLOCKED` 로 좁히고 그 근거를 바로 위에 적어 둔다.
        # ⚠ 그러면 "다섯 → 둘" 같은 **드리프트** 는 부분집합 검사로 못 잡는다. 그래서 아래에
        #   전량 열거 페르소나 수의 바닥선을 따로 둔다. 처음 쓴 판은 "전부 아니면 전무" 라는
        #   규칙을 넣었다가 첫 실행에서 infra.md 를 잡았고, 틀린 쪽은 사실이 아니라 규칙이었다.
# ⚠ 정확값. `< 14` 이었을 때 페르소나 **하나가 반환 계약을 통째로 잃어도** 열 스위트가 그린이었다
#   (실측: dba.md 에서 enum 과 센티널을 함께 지웠더니 `OK 14 personas`). 그것이 이 검사의 존재
#   이유인 드리프트다 — `_handoff.md` 는 센티널 없는 응답을 호출 실패로 분류한다.
if checked != 15:
    problems.append("%d personas carry a return-status line, expected exactly 15 — one gained or "
                    "lost its return contract" % checked)
# ⚠ 전량 열거 페르소나 수의 바닥선. 부분집합 검사만으로는 `DONE | DONE_WITH_CONCERNS | BLOCKED
#   | NEEDS_CONTEXT | FAIL` 이 `DONE | BLOCKED` 로 줄어드는 드리프트를 못 잡는다(실측: 그린이었다).
#   오늘 열 개가 전량 열거이고, 축소가 정당한 곳은 infra 하나다. 의도적으로 바꿀 때만 조정한다.
if full != 10:
    problems.append("%d personas enumerate all five statuses, expected exactly 10 — one narrowed "
                    "or widened" % full)
if partial != 1:
    problems.append("%d personas enumerate a strict subset, expected exactly 1 (infra.md, "
                    "review-only)" % partial)
# 소비자 쪽 규칙도 같은 다섯을 알아야 한다.
ho = open(os.path.join(gld, "commands/atoms/_handoff.md"), encoding="utf-8").read()
i = ho.find("Sentinel present, but the next non-empty line is not")
if i < 0:
    problems.append("_handoff.md lost the consumer rejection rule")
else:
    seg = ho[i:i + 400]
    miss = [s for s in STATUS if s not in seg]
    if miss:
        problems.append("_handoff.md consumer rule omits %s" % ",".join(sorted(miss)))
print("OK %d personas" % checked if not problems else "PROBLEMS " + " | ".join(problems))
PYPE
OUTPE="$("$PY" "$WORK3/persona_enum.py" "$GLD")"
case "$OUTPE" in
  OK*) ok "페르소나의 센티널·상태 enum 이 정본과 일치한다 (${OUTPE#OK })" ;;
  *)   bad "페르소나 센티널·enum 정합" "OK" "$OUTPE" ;;
esac

# ── init.md 의 허용목록 서술이 실제 템플릿과 맞는가 ──────────────────────────
# 실측: 서술은 "네 개(gh git jq ls)" 라고 적혀 있었고 템플릿은 여덟 개를 싣는다. 뒤 네 개
# (python3·bash·chmod·ps)는 묶음 A 가 만든 렌더/기동 경로가 쓰는 것이라, 서술을 믿고 넷으로
# 줄이면 무인 경로에서 `/gld sprint run` 이 프롬프트를 띄우거나 실패한다. 둘을 함께 건다.
NALLOW="$(grep -c '"Bash(' "$GLD/templates/settings.json.tmpl")"
NALLOW_ALLOW="$($PY - "$GLD/templates/settings.json.tmpl" <<'PYAL'
import json, sys
print(len(json.load(open(sys.argv[1], encoding="utf-8"))["permissions"]["allow"]))
PYAL
)"
if [ "$NALLOW_ALLOW" = "8" ]; then ok "settings.json.tmpl 의 permissions.allow 가 8개다"
else bad "settings.json.tmpl allow 개수" "8" "$NALLOW_ALLOW"; fi
hasfx "init.md: 허용목록이 여덟 개라고 적는다" "$GLD/commands/init.md" 'lists only the **eight** commands'
hasfx "init.md: 넷으로 줄이지 말라고 못박는다" "$GLD/commands/init.md" 'Do not trim it to four'
for B in python3 bash chmod ps; do
  hasfx "settings.json.tmpl: Bash($B:*) 가 있다" "$GLD/templates/settings.json.tmpl" "\"Bash($B:*)\""
done

OUTCI="$("$PY" "$WORK3/cites.py" "$GLD")"
case "$OUTCI" in
  OK*) ok "file:line 인용이 전부 여전히 그 줄을 가리킨다 (${OUTCI#OK })" ;;
  *)   bad "file:line 인용 정합" "OK" "$OUTCI" ;;
esac

OUTB="$("$PY" "$WORK3/banlist.py" "$GLD")"
case "$OUTB" in
  OK*) ok "금지 목록을 열거하는 모든 사이트가 정본과 일치한다 (${OUTB#OK })" ;;
  *)   bad "금지 목록 사이트 전수 일치" "OK" "$OUTB" ;;
esac
# 정본 문자열 자체는 여전히 글자 그대로 건다 — 위 검사는 *구성 요소* 를 보므로 어순이나
# 표현이 바뀌어도 통과한다. 둘 다 필요하다.
BANLIST='MUST NOT contain `$(...)` or backticks, `&&`, `||`, `|`, `;`, `&`, newlines, or redirections'
for BF in "commands/init.md" "commands/atoms/scan_repo.md" "commands/atoms/render_supervisor.py" \
          "commands/sprint/run.md"; do
  hasfx "$BF: 금지 목록이 정본과 글자 그대로 같다" "$GLD/$BF" "$BANLIST"
done
# run.md 산문 열거는 **두 줄** 이다. 라운드 7 은 첫 줄만 걸었고, 그 검사의 제목이 주장하는
# `||`·`&`·개행은 정작 둘째 줄에 있어 보호되지 않았다 — 라운드 7 의 발견이 한 단계 아래에서
# 그대로 재현된 것이다. 두 줄을 다 건다.
hasfx "run.md: 산문 열거 첫 줄(백틱)" "$RUNMD2" '`$(...)`, backticks,'
hasfx "run.md: 산문 열거 둘째 줄(||·&·개행)" "$RUNMD2" '`&&`, `||`, `|`, `;`, `<`, `>`, `&`, newlines'
# ⚠ 백틱은 `$(...)` 의 옛 표기인데 두 계약 문서 어디에도 없었고 집행기는 거부하고 있었다.
#   "exactly … and nothing more" 를 문자 그대로 믿은 다음 사람이 _METACHAR 를 다섯 개로 좁히면
#   `` `id` `` 가 템플릿의 `eval "$IC"` 에 닿는다. 세 문서를 같은 목록으로 맞추고 함께 고정한다.
hasfx "scan_repo.md: 백틱도 shell substitution 으로 처방된다" "$GLD/commands/atoms/scan_repo.md" \
  '**Shell substitution** — `$(...)` **or backticks**'
hasfx "run.md: 금지 목록이 init.md 것과 같음을 명시한다" "$RUNMD2" \
  "rejects \`init.md:163\`'s ban list"
# ⚠ "exactly … and nothing beyond it" 은 세 번째로 틀렸다. `_METACHAR` 는 파서가 아니라 **문자
#   클래스** 라, 인용부호 안의 메타문자도 거부한다(`jest -t "renders <Button/>"`). 그 사실을
#   적었는지 함께 건다 — 안 적으면 다음 사람이 또 "정확히 그것만" 으로 되돌린다.
hasfx "run.md: 문자 클래스라는 한계를 밝힌다" "$RUNMD2" 'It is a **character class**, not a parser'
hasfx "run.md: 글롭·\$VAR·~ 가 합법임을 명시한다" "$RUNMD2" 'Globs, `$VAR` and `~` are legal and pass'
hasfx "run.md: --order 도 숫자만 받는다는 것이 표에 있다" "$RUNMD2" 'Each value is **digits only**, same as `--tracker`'
# ⚠ 2d 가드 **자체**를 고정한다. 스위트는 그 가드가 읽는 신호의 *생산자* 만 고정하고 있었다
#   (sprint_supervisor T10 의 stderr 계약 문구). 소비자를 아무도 보지 않아서, `2d.` 블록을 통째로
#   지워도 열 개 스위트가 전부 그린이었다 — 그러면 렌더가 죽어도 step 5 가 백그라운드로 기동하고
#   실행은 "started" 를 보고한다. 설계가 ⚠⚠ 로 적은 바로 그 실패다.
hasfx "run.md: 2d 렌더 검증 단계가 있다"       "$RUNMD2" '2d. **Verify the render'
hasfx "run.md: 2d 가 stderr 계약 줄을 읽는다"  "$RUNMD2" 'render_supervisor: wrote'
hasfx "run.md: 2d 가 step 5 를 막는다"         "$RUNMD2" 'do not run step 5'
# 그리고 순서 — 렌더 호출과 기동 사이에 있어야 한다. 뒤로 밀리면 이미 떠 있는 것을 검증한다.
RB2D="$($PY - "$RUNMD2" <<'PY2D'
import re, sys
t = open(sys.argv[1], encoding="utf-8").read()
def at(pat):
    m = re.search(pat, t, re.M)
    return m.start() if m else -1
r, g, s5 = at(r"^\s*python3 .*render_supervisor\.py"), at(r"^2d\. \*\*Verify the render"), at(r"^5\. \*\*Start it")
print("OK" if -1 not in (r, g, s5) and r < g < s5 else "render=%d guard=%d start=%d" % (r, g, s5))
PY2D
)"
[ "$RB2D" = OK ] && ok "run.md: 2d 가 렌더 호출과 기동 사이에 있다" \
                 || bad "run.md: 2d 의 위치" "render < 2d < step 5" "$RB2D"

# ⚠ B 의 2차 포인터 — 절감 43.5k 전부가 여기 걸려 있는데 병합 게이트는 commands/ 만 본다.
# 템플릿 **한 개**만 옛 접미로 되돌려도 세 스위트가 전부 그린이었다(persona_migrate 의 원장 검사는
# 헤딩이 *어느* 템플릿엔가 있기만 하면 통과하므로 부분 회귀를 못 본다).
# ⚠ leader.md 는 **제외한다 — 의도된 예외다.** 리더는 스폰되는 서브에이전트가 아니라 메인
#   세션이 체현하는 역할이고, 그 세션은 이미 `_handoff.md` 를 들고 있다. 포인터를 떼도 아끼는
#   것이 없다. B 는 16개 중 15개를 고쳤고 `0d7de0d` 가 그 이유를 기록한다. 이 검사는 처음 돌 때
#   leader.md 를 잡았고, 틀린 쪽은 사실이 아니라 검사의 범위였다.
TAGENTS="$GLD/templates/agents"
NP2="$(grep -rc '_handoff\.md` Section C' "$TAGENTS" 2>/dev/null | grep -v '/leader\.md:' \
       | awk -F: '{n+=$2} END{print n+0}')"
NTPL="$(ls "$TAGENTS"/*.md 2>/dev/null | wc -l | tr -d ' ')"
if [ "$NTPL" -lt 10 ]; then
  bad "페르소나 템플릿 집합" "10개 이상" "${NTPL}개 — 경로가 틀렸다면 0건은 통과가 아니다"
elif [ "$NP2" = "0" ]; then
  ok "페르소나 템플릿 ${NTPL}개(leader 제외)에 Section C 2차 포인터가 0건이다"
else
  bad "페르소나 2차 포인터" "0건" "${NP2}건 — 서브에이전트가 다시 53KB 를 읽는다"
fi
# 그리고 leader.md 의 예외가 *살아 있는지* — 예외라고 적어 놓고 조용히 사라지면 이 검사는
# 아무것도 안 하는 검사가 된다.
hasfx "leader.md: 리더의 Section C 참조는 그대로다 (의도된 예외)" "$TAGENTS/leader.md" '`_handoff.md` Section C'
echo ""
# ── 37. result-contract 펜스: 사본이 정본과 바이트 동일하고, 개수가 맞는가 ──────
# B 는 12개 스폰 프롬프트에서 "per `_handoff.md` Section C" 를 없애고 계약 본문을 인라인했다.
# 진실 원본은 여전히 _handoff.md Section C 의 펜스이므로, 사본이 그것과 갈라지면 서브에이전트가
# 받는 계약과 리더가 믿는 계약이 달라진다. 개수 바닥선이 함께 필요하다 — 어떤 사이트가 펜스와
# Section C 언급을 둘 다 잃으면 앵커드 grep 은 0건(통과)이고 비교할 사본이 없어(통과) 계약을
# 전혀 못 받는 상태가 그린이 된다.
cat > "$WORK3/contract.py" <<'PYC'
import os, re, sys
gld = sys.argv[1]
# ⚠ 파일 목록을 손으로 적지 않는다. 라운드 8 이 다른 검사에서 없앤 바로 그 모양이 여기 남아
#   있었고, 목록 밖 파일(`commands/review.md`)에 13번째 펜스를 심으면 열 스위트가 그린이었다
#   — 그 펜스는 서브에이전트에게 `>>> OUTCOME <<<` 를 내라고 지시했고, 소비자 규칙은 그것을
#   호출 실패로 분류한다. 트리에서 찾고, **총 개수를 정확값** 으로 건다.
import glob as _glob
OPEN, CLOSE = "<!-- guild:result-contract -->", "<!-- /guild:result-contract -->"
strip = lambda l: re.sub(r"^\s*>\s?", "", l).rstrip("\n")
lines = open(os.path.join(gld, "commands/atoms/_handoff.md"), encoding="utf-8").read().split("\n")
try:
    o = lines.index(OPEN); c = lines.index(CLOSE)
except ValueError:
    print("CANON_MISSING"); raise SystemExit
canon = lines[o+1:c]
problems = []; total = 0
if len(canon) != 1:
    problems.append("canonical block is %d lines, want 1" % len(canon))
# ⚠ `templates/agents/` 도 훑는다. 서브에이전트 정의가 실제로 사는 곳인데 두 훑기 모두
#   `commands/` 에서 멈춰 있었다 — 라운드 9 가 `review.md` 에서 잡은 13번째 펜스를 한 디렉터리
#   옆으로 옮기면 그대로 통과했다(실측).
SCAN = (_glob.glob(os.path.join(gld, "commands/**/*.md"), recursive=True)
        + _glob.glob(os.path.join(gld, "templates/agents/*.md")))
for f in sorted(SCAN):
    rel = os.path.relpath(f, gld)
    if rel == "commands/atoms/_handoff.md":
        continue                      # 정본 자신
    body = open(f, encoding="utf-8").read().split("\n")
    opens = [n for n, l in enumerate(body) if strip(l) == OPEN]
    closes = [n for n, l in enumerate(body) if strip(l) == CLOSE]
    if len(opens) != len(closes):
        problems.append("%s: %d opens vs %d closes" % (rel, len(opens), len(closes)))
        continue
    for a, b in zip(opens, closes):
        total += 1
        if [strip(x) for x in body[a+1:b]] != canon:
            problems.append("%s:%d drifted from canonical" % (rel, a+2))
if total != 12:
    problems.append("found %d result-contract copies, expected exactly 12 — one appeared or "
                    "vanished; update this number deliberately" % total)
# 스폰 프롬프트 안의 센티널은 **정확히 하나** 여야 한다. 펜스 본문이 정본과 같아도, 펜스 밖
# 블록쿼트에 다른 센티널을 적어 넣으면 서브에이전트는 그것을 따른다.
for f in sorted(SCAN):
    rel = os.path.relpath(f, gld)
    for n, l in enumerate(open(f, encoding="utf-8").read().split("\n"), 1):
        # 페르소나는 블록쿼트가 아니라 본문에 센티널을 적는다 — 그래서 `^>` 로 거르면 안 된다.
        if rel.startswith("templates/agents/"):
            pass
        elif not re.match(r"^\s*>", l):
            continue
        for m in re.findall(r">>>\s*([A-Z_]+)\s*<<<", l):
            if m != "RESULT":
                problems.append("%s:%d spawn prompt names a `>>> %s <<<` sentinel, not RESULT"
                                % (rel, n, m))
# ⚠ 양방향으로 본다. 한쪽만(펜스 ⊆ 표) 보면 표가 6번째 상태를 얻어도 사본은 전부 동일하고
# 이름도 전부 실재해 그린이다 — 리더의 표는 어떤 서브에이전트도 들어본 적 없는 상태를 허용하게
# 되고, `_handoff.md` 자신의 "keep the enum names in step with the table above" 가 무집행이 된다.
# 실측: 표에 `DEFERRED` 행을 추가해도 PASS=217 FAIL=0 이었다.
names = set(re.findall(r"`([A-Z_]+)(?::|`)", canon[0])) if canon else set()
tbl = "\n".join(lines[:o])
rows = set()
for line in tbl.split("\n"):
    m = re.match(r"^\|\s*`([A-Z][A-Z_]*)(?::[^`]*)?`\s*\|", line)
    if m:
        rows.add(m.group(1))
if not rows:
    problems.append("Section C status table not found (row parse returned nothing)")
if names - rows:
    problems.append("enum missing from Section C table: %s" % ",".join(sorted(names - rows)))
if rows - names:
    problems.append("Section C table has status(es) the fence never states: %s"
                    % ",".join(sorted(rows - names)))
print("OK %d" % total if not problems else "PROBLEMS " + " | ".join(problems))
PYC
OUTC="$("$PY" "$WORK3/contract.py" "$GLD")"
case "$OUTC" in
  "OK 12") ok "result-contract: 트리 전체에서 사본 12개, 전부 정본과 바이트 동일" ;;
  OK*)     bad "result-contract: 사본 12개" "OK 12" "$OUTC" ;;
  *)       bad "result-contract: 사본이 정본과 동일" "OK 12" "$OUTC" ;;
esac

# 펜스가 블록 *끝* 에 붙으면 `_execute_spine.md:6` 의 언어 불변조건("모든 스폰 프롬프트는
# `Write output in \`config.language\`.` 로 끝난다")이 조용히 깨진다 — 계약은 전달되고 언어
# 지시만 밀려난다. 12개 사본 중 10곳이 그 불변조건의 대상이다(0.97.1: sprint plan 의 PO 프롬프트도
# 언어 줄로 끝난다 — 리더가 직접 덧붙여야 했다(dry-run 2차). plan 계열 나머지 2곳은 파일 머리의
# "Output language" 줄로 대신하므로 그 줄의 존재를 대신 단언한다).
cat > "$WORK3/lang.py" <<'PYL'
import os, re, sys
gld = sys.argv[1]
EXPECT = {"commands/test.md":1, "commands/design.md":3, "commands/qa.md":2,
          "commands/analyze.md":1, "commands/atoms/_execute_spine.md":2,
          "commands/plan.md":0, "commands/sprint/plan.md":1}
OPEN = "<!-- guild:result-contract -->"
TAIL = "Write output in `config.language`."
strip = lambda l: re.sub(r"^\s*>\s?", "", l).rstrip()
problems, total = [], 0
for rel, want in EXPECT.items():
    lines = open(os.path.join(gld, rel), encoding="utf-8").read().split("\n")
    got = 0; blocks = 0; i = 0
    while i < len(lines):
        if not re.match(r"^\s*>", lines[i]):
            i += 1; continue
        j = i
        while j < len(lines) and (re.match(r"^\s*>", lines[j]) or not lines[j].strip()):
            j += 1
        body = [strip(l) for l in lines[i:j] if re.match(r"^\s*>", l)]
        if OPEN in body:
            blocks += 1
            ne = [x for x in body if x.strip()]
            if ne and ne[-1].endswith(TAIL):
                got += 1
        i = j
    total += got
    if got != want:
        problems.append("%s: %d/%d blocks end with the language sentence (%d fenced)"
                        % (rel, got, want, blocks))
# plan 계열 3곳은 파일 머리 줄로 대신한다 — 0 이 "그냥 없다" 로 읽히지 않게 못박는다.
for rel in ("commands/plan.md", "commands/sprint/plan.md"):
    head = open(os.path.join(gld, rel), encoding="utf-8").read()
    if "**Output language**" not in head:
        problems.append("%s: neither per-prompt nor file-level language instruction" % rel)
print("OK %d" % total if not problems else "PROBLEMS " + " | ".join(problems))
PYL
OUTL="$("$PY" "$WORK3/lang.py" "$GLD")"
case "$OUTL" in
  "OK 10") ok "스폰 프롬프트 10곳이 여전히 언어 지시로 끝난다 (펜스가 뒤에 붙지 않았다)" ;;
  *)      bad "스폰 프롬프트가 언어 지시로 끝난다" "OK 10" "$OUTL" ;;
esac

# 은퇴한 문구가 정본 파일에 남아 있지 않은가 — 같은 규칙의 두 판본이 남으면 하나만 검사를 받는다.
lacksfx "_handoff.md: 펜스로 대체된 옛 문구가 남지 않았다" "$GLD/commands/atoms/_handoff.md" 'keep RESULT to one summary line'

# 앵커드 grep 0건 — 어떤 사이트도 Section C 를 이름으로 부르지 않는다.
LEFT="$(grep -rn '^  > .*_handoff\.md` Section C' "$GLD/commands/" 2>/dev/null || true)"
if [ -z "$LEFT" ]; then ok "스폰 프롬프트에 Section C 이름 참조가 남지 않았다"
else bad "스폰 프롬프트에 Section C 이름 참조가 남지 않았다" "0건" "$(echo "$LEFT" | head -2)"; fi
# ── 38. 무인 narration 예외(F/L2)가 Section K 에 살아 있는가 ──────────────────
# L2 는 리더가 조건부로 첨부하는 한 줄로만 전달된다. 그 문안이 Section K 에서 사라지면
# 리더가 무엇을 붙여야 하는지 알 수 없고, 실패는 조용하다 — 무인 실행이 계속 config.language
# 로 narration 할 뿐 아무것도 깨지지 않는다.
HANDOFF="$GLD/commands/atoms/_handoff.md"
hasfx "Section K: 무인 narration 예외가 있다" "$HANDOFF" 'Unattended exception — narration only'
hasfx "Section K: 리더가 붙일 문안이 verbatim 으로 있다" "$HANDOFF" 'write free narration (anything before the `>>> RESULT <<<` sentinel) in **ASCII English**'
hasfx "Section K: 조건부 문장이 아니라 조건부 포함임을 못박는다" "$HANDOFF" 'do not include it with a condition attached'
hasfx "Section K: 범위가 dev.md 경로로 한정돼 있다" "$HANDOFF" 'Scope: the `dev.md` drive path only'
# 열거를 지우지 않았는가 — 예외는 추가이지 삭제가 아니다.
hasfx "Section K: RESULT 요약이 config.language 열거에 남아 있다" "$HANDOFF" '`>>> RESULT <<<` one-line summaries'

# 언어 불변조건이 이 예외 조항을 가리키는가. 안 가리키면 불변조건만 읽은 사람은 무인 실행의
# narration 줄을 위반으로 읽고 "고친다".
hasfx "_execute_spine.md: 언어 불변조건이 무인 예외를 가리킨다" "$GLD/commands/atoms/_execute_spine.md" 'unattended narration carve-out'

# attended 누출 정적 검사 — 예외 문안이 **스폰 프롬프트 본문에 상주**하면 안 된다. 리더가
# 조건부로 붙이는 한 줄이어야 하는데(조건은 Section K 가 규정한다), 어느 커맨드 파일이 프롬프트
# 안에 박아 넣으면 attended 실행도 ASCII 로 narration 하게 되고 아무것도 깨지지 않으므로 조용하다.
# ⚠ 앵커는 `^  > ` — 스폰 프롬프트 줄만 본다. 파일 전역 grep 은 예외를 *가리키는* 산문
#   (`_execute_spine.md:6` 의 불변조건 포인터)까지 누출로 신고했다. 언급은 누출이 아니다.
LEAKF="$(grep -rn --include='*.md' '^  > .*ASCII English' "$GLD/commands/" 2>/dev/null || true)"
if [ -z "$LEAKF" ]; then ok "무인 narration 문안이 스폰 프롬프트에 상주하지 않는다"
else bad "무인 narration 문안이 스폰 프롬프트에 상주하지 않는다" "0건" "$(printf '%s' "$LEAKF" | head -2 | tr '\n' ' ')"; fi

# Section E 참조 카운트 — 정보성이다. 0건 차단은 Section C 패턴에만 적용한다(위 섹션 37).
# E 는 리더가 읽는 절이므로 스폰 프롬프트에서 이름으로 불러도 무방하지만, 개수가 조용히
# 변하면 B 의 범위가 이동했다는 신호다. 오늘 3건(qa.md ×2 · _execute_spine.md ×1)이 정상.
NSE="$(grep -rc '^  > .*_handoff\.md` Section E' "$GLD/commands/" 2>/dev/null | awk -F: '{n+=$2} END{print n+0}')"
if [ "$NSE" = "3" ]; then ok "Section E 참조가 기대값 3건이다 (정보성 드리프트 신호)"
else bad "Section E 참조 개수" "3 (정보성)" "$NSE — B 의 범위가 이동했는지 확인하라"; fi

# D 폐기가 기록으로 남아 있는가 — 다음 사람이 같은 가설을 다시 세우지 않도록.
hasfx "_bash_rules.md: 무인 완화 폐기 사유가 기록돼 있다" "$GLD/commands/atoms/_bash_rules.md" 'Asked and answered: the atomic rule is NOT relaxed'
# ── 39. enum 축소 문장이 Section C 표와 어긋나지 않는가 (회귀 검사) ──────────
# B 는 12곳의 계약 문장을 펜스로 갈아끼웠다. 섹션 37 은 펜스 *사본* 을 본다. 이 검사는 펜스
# *밖* 에 남는 사이트별 축소 문장을 본다 — 어떤 스폰이 5개 중 3개만 허용한다고 다시 적은 줄들.
# 오늘 7곳이 전부 통과하는 것이 정상이다. 이것은 모양 검사가 아니라 회귀 검사이고, Section C
# 표에 상태가 추가·개명됐는데 사본이 안 따라올 때 발화한다.
# ⚠ 잡는 것과 못 잡는 것을 정직하게 적는다. **잡는다**: 표에 없는 상태를 부르는 축소 문장,
#   축소 사이트의 소멸(바닥선 7). **못 잡는다**: 표에 *있는* 상태들만으로 잘못 좁힌 문장
#   (예: `BLOCKED` 를 허용해야 할 스폰이 `DONE`/`FAIL` 만 나열) — 그것은 부분집합이므로
#   통과한다. 그 판정은 사이트마다 다르고 기계가 아니라 사람이 내려야 한다.
# ⚠ 공집합도 부분집합이다 — 축소 문장이 통째로 지워지면(B 가 만들 수 있는 사고) 빈 집합이
# 그린을 찍는다. 그래서 사이트 수 바닥선을 함께 둔다.
# ⚠ Not `enum.py`: a script's own directory is first on sys.path, so that name shadowed the stdlib
#   `enum` that `re` imports — Python 3.9 (macOS's python3) failed this and the tier check after it.
cat > "$WORK3/enum_check.py" <<'PYE'
import glob, os, re, sys
gld = sys.argv[1]
canon = None
for line in open(os.path.join(gld, "commands/atoms/_handoff.md"), encoding="utf-8"):
    if line.startswith("Return EXACTLY one status line"):
        canon = line.rstrip("\n"); break
if canon is None:
    print("CANON_MISSING"); raise SystemExit
TABLE = set(re.findall(r"`(DONE_WITH_CONCERNS|NEEDS_CONTEXT|BLOCKED|DONE|FAIL)", canon))
TOK = re.compile(r"`([A-Z][A-Z_]{2,})")
# 상태처럼 생겼지만 상태가 아닌 것들 — 확장 시 여기에 추가한다
NOT_STATUS = {"RESULT", "OK", "SOURCE", "CANDIDATES", "AC", "PR", "QA", "UI", "UX", "E2E", "JSON", "TDD", "HTML"}
strip = lambda l: re.sub(r"^\s*>\s?", "", l).rstrip("\n")
problems, sites = [], 0
for f in sorted(glob.glob(os.path.join(gld, "commands/**/*.md"), recursive=True)):
    rel = os.path.relpath(f, gld)
    for n, line in enumerate(open(f, encoding="utf-8"), 1):
        if not re.match(r"^\s*>\s", line):
            continue
        if strip(line) == canon:          # 정본 펜스 사본은 섹션 37 소관
            continue
        # 반환을 *지시하는* 줄만 본다. 머신 토큰을 설명하는 산문(`_readiness.md` 의 "the `RESULT`
        # keywords")이나 다른 블록쿼트의 대문자 토큰은 대상이 아니다
        # (`README`, `BLOCKER`, `INV`, `GLD_UNATTENDED` …) — 그것들은 이 게이트의 대상이 아니다.
        if not ("Return " in line or "Narrowed for this" in line or "Surface AC ambiguity" in line
                or "BLOCKED:" in line or "`BLOCKED` line" in line):
            continue
        toks = set(TOK.findall(line)) - NOT_STATUS
        if not toks:
            continue
        sites += 1
        if not toks <= TABLE:
            problems.append("%s:%d names %s, not in Section C" % (rel, n, ",".join(sorted(toks - TABLE))))
# ⚠ 라운드 9 의 규칙 ①(바닥선은 측정값과 같게)이 여기만 빠져 있었다 — 8번째 축소 사이트가
#   생겨도 통과했다.
if sites != 7:
    problems.append("found %d reduction sites, expected exactly 7 — one appeared or was dropped"
                    % sites)
print("OK %d" % sites if not problems else "PROBLEMS " + " | ".join(problems))
PYE
OUTE="$("$PY" "$WORK3/enum_check.py" "$GLD")"
case "$OUTE" in
  OK*) ok "enum 축소 문장이 Section C 표의 부분집합이고 사이트가 남아 있다 (${OUTE#OK })" ;;
  *)   bad "enum 축소 문장이 Section C 표와 정합" "OK >=7" "$OUTE" ;;
esac
# ── 스폰 프롬프트의 문장 융합 ────────────────────────────────────────────
# ⚠ 라운드 13: `test.md:30` 이 «…page from there if they differ **Verify gate:** your pass
# claim MUST…» 로 끝나 있었다. B1 을 고치며 ⚠ 절을 끼워 넣다 **마침표를 먹었다** — M-3 과
# 같은 클래스이고, 벌써 세 번째다(`_preflight.md` 꼬리 유실 · `qa.md` 열거 파손).
# ⚠ **한계 고지**: 일반적인 「문장 융합」 검사는 노이즈가 너무 크다(실측 — `Section A:`,
# `Do TDD:`, `Check TWO things:` 가 전부 정상인데 걸린다). 그래서 **스폰 프롬프트에서 항상
# 문장을 여는 라벨**로 범위를 좁힌다. 이것이 막는 것은 그 라벨들 앞의 융합뿐이다.
FUSE="$("$PY" - "$GLD" <<'FZPY'
import io, os, re, sys
gld = sys.argv[1]
FUSE = re.compile(r"[a-z] (?=(?:Verify|Evidence|Conformance) gate:|Honesty-of-scope)")
bad = []
for rel in ("test.md", "implement.md", "refactor.md", "debug.md", "qa.md",
            "atoms/_execute_spine.md"):
    f = os.path.join(gld, "commands", rel)
    if not os.path.exists(f):
        continue
    for i, line in enumerate(io.open(f, encoding="utf-8"), 1):
        if FUSE.search(line):
            bad.append(os.path.basename(f) + ":" + str(i))
print(" ".join(bad))
FZPY
)"
if [ -z "$FUSE" ]; then ok "스폰 프롬프트: 라벨 앞 문장 경계가 살아 있다"
else bad "스폰 프롬프트: 라벨 앞 문장 경계가 살아 있다" "융합 없음" "융합: $FUSE"; fi

# ── M11-① 스냅샷 순서 — **실제로 돌려서** 위양성이 없는지 본다 ────────────
# ⚠⚠ 이것은 문자열 검사가 아니라 **실행 검사**다. 라운드 11 에서 이 한 줄이 BLOCKER 였다:
# `git status --porcelain -uall` 을 **파일 생성 전에** 찍으면, 감사자 복귀 후의 status 에
# `?? .claude/guild/memory/mutation-before.json` 이 새로 나타나 **감사자가 건드리지 않은 변경**
# 으로 보고된다. `.claude/guild/memory/` 는 init 이 `.gitignore` 에 negation 을 넣어야 했던
# 레포에서만 무시되므로, `.claude` 가 애초에 무시되지 않는 레포에서는 **매 실행마다** 터진다.
# 지시문에서 스니펫을 뽑아 **임시 레포에서 실제로 실행**하고 before/after 를 대조한다.
SNIP="$("$PY" - "$ESMD" <<'SNPY'
import io, re, sys
s = io.open(sys.argv[1], encoding="utf-8").read()
m = [l for l in s.split("\n") if l.startswith("python3 -c") and "mutation-before.json" in l]
print(m[0] if m else "")
SNPY
)"
if [ -z "$SNIP" ]; then
  bad "M11-①: 스냅샷 스니펫이 지시문에 있다" "python3 -c … mutation-before.json" "없음"
else
  WORKM="$(mktemp -d)"
  (
    cd "$WORKM" && git init -q && git config user.email t@t && git config user.name t \
      && echo a > a.txt && git add . && git commit -qm init
    MB="$(git rev-parse HEAD)"
    eval "${SNIP//<mb>/$MB}"
    B="$("$PY" -c "import json;print(json.load(open('.claude/guild/memory/mutation-before.json'))['status'],end='')")"
    A="$(git status --porcelain -uall)"
    [ "$B" = "$A" ]
  ) >/dev/null 2>&1
  if [ $? -eq 0 ]; then ok "M11-①: 스냅샷이 자기 자신 때문에 어긋나지 않는다 (임시 레포 실행)"
  else bad "M11-①: 스냅샷이 자기 자신 때문에 어긋나지 않는다" "before == after" "어긋남 — 위양성"; fi
  rm -rf "$WORKM"
fi

# ── M11-② 문단 순서 — 규칙 → 근거 → 예외 ────────────────────────────────
# ⚠ **위치 검사다.** M-2 의 scope 삽입이 규칙의 **근거**("before/after pair")를 **예외** 블록
# 안으로 밀어 넣었고, 그래서 읽는 사람에게 근거가 예외의 근거로 읽혔다 — 문자열은 셋 다
# 있었으므로 존재 검사로는 안 잡힌다. 세 조각의 **순서**를 본다.
SGMD="$GLD/commands/atoms/_stagnation.md"
_r=$(grep -n 'do not read those strings from memory' "$SGMD" | head -1 | cut -d: -f1)
_w=$(grep -n 'The comparison is a \*before/after pair\*' "$SGMD" | head -1 | cut -d: -f1)
_e=$(grep -n 'Scope — where the "before" half is read' "$SGMD" | head -1 | cut -d: -f1)
if [ -n "$_r" ] && [ -n "$_w" ] && [ -n "$_e" ] && [ "$_r" -le "$_w" ] && [ "$_w" -lt "$_e" ]; then
  ok "M11-②: 규칙($_r) → 근거($_w) → 예외($_e) 순서다"
else
  bad "M11-②: 규칙 → 근거 → 예외 순서" "규칙≤근거<예외" "규칙=$_r 근거=$_w 예외=$_e"
fi

# ── M9 통째읽기 요건이 **네 스폰 사이트 전부**에 있는가 ───────────────────
# ⚠ **정합 검사다.** `_preflight.md` 의 carve-out 은 「전수 독자의 통째읽기 요건은 각자의 스폰
# 프롬프트에 있다」고 단언한다. 그 단언과 실제 사이트가 어긋나면, ① 요건이 빠진 채 예산만
# 좁혀지거나 ② 라운드 10 처럼 **이미 있는데 없다고 적힌** 상태가 된다 — 후자는 읽는 사람이
# 보장이 없다고 믿게 만든다. 사이트를 세고 carve-out 이 그 수를 아는지 본다.
_WR=0
for _pair in "$GLD/commands/implement.md:Read it whole" \
             "$GLD/commands/refactor.md:Read it whole" \
             "$GLD/commands/test.md:Read that file whole" \
             "$GLD/commands/atoms/_execute_spine.md:read the intent whole"; do
  _file="${_pair%%:*}"; _needle="${_pair#*:}"
  if grep -qF -- "$_needle" "$_file"; then _WR=$((_WR+1))
  else bad "M9: 통째읽기 요건 — $(basename "$_file")" "'$_needle' 있음" "없음"; fi
done
if [ "$_WR" -eq 4 ]; then ok "M9: 통째읽기 요건이 네 스폰 사이트 전부에 있다"; fi
# carve-out 이 그 사실을 알고 있는가 (없다고 적혀 있으면 위 4건과 모순)
if grep -qF -- "until it does, do not assert" "$PFMD"; then
  bad "M9: carve-out 이 스폰 사이트의 실제 상태와 맞는다" "요건 있음을 반영" "아직 없다고 적혀 있다"
else
  ok "M9: carve-out 이 스폰 사이트의 실제 상태와 맞는다"
fi

# ── retro: 질의 축소가 되돌아가지 않는가 ─────────────────────────────────
# ⚠⚠ `sprint/retro.md` 는 검사가 **0건**이었다. 실측(dev-yakuza/one-man-company, 스프린트 389):
#   이슈 목록 556,413B → 981B · PR 목록 53,458B → 569B · 감사 기록 39,843B → 71B.
#   전부 **Phase 1~2**, 즉 앞쪽에서 들어오므로 §1 의 적분으로 retro 의 남은 전 구간에
#   재청구된다 — Phase 5 의 `evolve` 실행 전체를 포함해서.
# ⚠ **존재 검사가 아니라 정합 검사다**: `--json` 에 `body` 를 요청하면서 `--jq` 가 없으면
#   본문이 통째로 돌아온다. 그 조합을 금지한다.
RETRO="$GLD/commands/sprint/retro.md"
if [ ! -f "$RETRO" ]; then
  bad "retro.md 가 있다" "파일" "없음"
else
  # ⚠ **세 파일 전부**를 본다. retro 만 걸었더니 `plan`·`daily` 가 같은 모양으로 남아 있었고,
  #    `daily` 의 PR 목록은 **123,617 B**(그중 `statusCheckRollup` 이 57%)였다.
  #    무거운 필드는 `body` 만이 아니다 — 렌더링에 한 글자만 쓰는 `statusCheckRollup` 도 같다.
  # ⚠⚠ **범위가 곧 발견의 범위다.** retro 에만 걸었더니 plan·daily 가 남아 있었고, sprint 로
  #    넓혔더니 `/gld dev` 경로(`qa.md`)·`status.md`·`review.md` 가 남아 있었다. 실측:
  #    qa 67,906→80 B · review 68,663→233 B · status(PR) 67,989→97 B · status(comments) 64,941→176 B.
  #    이제 `commands/**` 전부를 본다.
  _bad_calls="$("$PY" - "$GLD/commands" <<'RTPY'
import glob, io, os, sys
d = sys.argv[1]
HEAVY = ("body", "statusCheckRollup", "comments")
bad = []
for fp in sorted(glob.glob(os.path.join(d, "*.md")) + glob.glob(os.path.join(d, "*", "*.md"))):
    f = os.path.relpath(fp, d)
    if True:
        for line in io.open(fp, encoding="utf-8").read().split("\n"):
            t = line.strip()
            if not t.startswith("gh ") or "--json" not in t:
                continue
            # ⚠ **`--json` 의 필드 목록만 본다.** 줄 전체에서 찾으면 `--search '"x" in:body'` 의
            #    `body` 를 잡는다 — 실측 오검출(plan.md 의 마커 검색 호출).
            fields = t.split("--json", 1)[1].strip().split(" ", 1)[0]
            if not any(h in fields.split(",") for h in HEAVY):
                continue
            if "--jq" not in t:
                bad.append(f + ": " + t[:50])
print(" | ".join(bad))
RTPY
)"
  if [ -z "$_bad_calls" ]; then
    ok "commands/**: 무거운 필드(body·statusCheckRollup·comments)를 요청하는 gh 호출은 전부 --jq 로 좁힌다"
  else
    bad "commands/**: 무거운 필드 요청은 --jq 로 좁힌다" "전부 좁혀짐" "맨 호출: $_bad_calls"
  fi
  # ⚠⚠ CI 집계의 **방향**을 고정한다. 순진한 `test("FAIL|ERROR|CANCEL")` 판은 `TIMED_OUT` 을
  #    **pass** 로 냈다(합성 입력으로 발견 — 이 레포의 PR 200건엔 그 경우가 없었다).
  #    일간 보드에서 **모르는 CI 상태가 초록으로 보이면 안 된다** → pass 는 화이트리스트로만.
  DAILY="$GLD/commands/sprint/daily.md"
  hasfx "daily: CI 집계의 pass 가 화이트리스트다 (모르면 fail)" "$DAILY" 'test("^(SUCCESS|NEUTRAL|SKIPPED)$")'
  hasfx "daily: 진행 중이 판정보다 먼저다" "$DAILY" 'then "pending"'
  # plan 의 body 는 **재료**다 — 줄이지 말라는 경고가 남아 있어야 한다.
  hasfx "plan: body 는 트리아지 재료라고 못박는다" "$GLD/commands/sprint/plan.md" 'it is the material, not overhead'
  # ⚠⚠ **B-1 회귀 방지.** retro 의 멤버 PR 필터를 `closingIssuesReferences` 만으로 걸면
  #    멤버 PR 을 놓친다 — 실측 **167 PR 중 70건(42%)이 그 참조가 없고**, 그중 하나는
  #    `#398 fix/153-…`(MERGED, 멤버 #153)다. 놓친 PR 은 「머지 안 됨」으로 읽히고
  #    **Phase 4 가 그 수를 config.json 에 쓴다.** 브랜치명 대체 경로가 살아 있어야 한다.
  hasfx "retro: 멤버 PR 을 브랜치명으로도 찾는다 (참조만으로는 42%를 놓친다)" "$RETRO" '(.headRefName // "") | test("(^|[^0-9])#?'
  # ⚠ 그리고 어느 신호가 맞았는지 구별해 돌려줘야 한다 — `branch` 는 휴리스틱이라
  #    `feat/200-refs-153-followup` 같은 것을 못 막는다. 사실이 아니라 **확인 대상**이다.
  hasfx "retro: 매칭 신호를 via 로 구별한다" "$RETRO" 'via: (if ($c | length) > 0 then "closes" else "branch" end)'
  # ⚠⚠ **판단 경로를 지우지 않았는가.** qa·review·status 의 PR 찾기는 «closing 참조 **또는**
  #    제목/본문이 명백히 연결을 보여주면» 이다. 뒤 절반은 **판단**이고, regex 매치만 내보내는
  #    jq 는 그것을 조용히 삭제한다 — retro 의 B-1 과 같은 클래스(참조만 보면 42% 를 놓쳤다).
  #    `strict`(권위) + `candidates`(제목만, 본문 없음) 둘 다 나와야 한다.
  for _f in qa review status; do
    _p="$GLD/commands/$_f.md"
    if grep -q 'strict:' "$_p" && grep -q 'candidates:' "$_p"; then
      ok "$_f: PR 찾기가 strict + candidates 를 둘 다 낸다 (판단 경로 보존)"
    else
      bad "$_f: PR 찾기가 판단 경로를 보존한다" "strict + candidates" "누락"
    fi
  done
  # ⚠⚠ **jq 가 죽으면 호출 전체가 에러다** — 큰 페이로드보다 나쁘다. 그 단계가 PR 을 하나도
  #    못 받는다. 실측: `headRefName` 이 null 이면 «null cannot be matched» 로 종료하고,
  #    `statusCheckRollup` 항목이 객체가 아니면 «Cannot index string» 으로 종료한다.
  hasfx "daily: CI 집계가 스키마 변화에 죽지 않는다" "$DAILY" '(.conclusion? // .status? // .state? // "") | tostring'
  # 절단 검사는 `total` 이 같은 호출에서 돌아오는 것에 의존한다 — 그게 사라지면
  # 「개수를 별도 호출로 세라」던 옛 형태로 되돌아가고, 그 단계는 건너뛰기 쉽다.
  hasfx "retro: 절단 검사용 total 을 같은 호출에서 받는다" "$RETRO" 'total: length'
  # 감사 기록은 전문이 아니라 집계로 받는다 — 루프백이 많을수록 커지는 유일한 항목이다.
  hasfx "retro: 감사 기록을 jq 로 집계한다 (전문 아님)" "$RETRO" 'match("### audit-record "'
  # ⚠ 세 토큰은 평범한 낱말이라 단어 경계가 필요하다(`prefixed` 오검출).
  hasfx "retro: disposition 토큰에 단어 경계를 건다" "$RETRO" 'match("\\bfixed\\b"'
  # A clean scan writes `findings: none` (0.85.2) so that a MISSING record means no attempt
  # reached the record write (auditor did not run, 3.5a stopped first, or a pre-0.85.2 run). The writer (spine), the token list (Section K) and the counter (retro) must name the
  # same literal — if one drifts, retro silently reads every clean member as unaudited again.
  hasfx "spine: a clean auditor scan still writes a block (findings: none)" "$SPINE" 'A clean scan writes a block too: `findings: none`'
  hasfx "handoff K: findings: none / scan: none are machine tokens" "$HANDOFF" 'the clean-scan / no-scan lines `findings: none` / `scan: none`'
  hasfx "retro: counts clean blocks (findings: none)" "$RETRO" 'clean: ([$b | match("findings: none";"g")] | length)'
  hasfx "retro: counts never-scanned blocks (scan: none)" "$RETRO" 'no_scan: ([$b | match("scan: none";"g")] | length)'
  # violation must read the WHOLE comment list ($all), not the filtered auditor bodies — the
  # first draft ran `.[]` over the joined strings and would have errored on every member.
  # --paginate --jq runs per page; a long Issue prints one object per page (verified, per_page=2 on
  # an Issue with a violation: records and violation landed in different objects).
  hasfx "retro: per-page objects must be summed" "$RETRO" 'One object per PAGE — add them up.'
  hasfx "retro: violation count reads all comments in the same call" "$RETRO" 'violation: ([$all[] | select((.body // "") | contains("<!-- guild:auditor-violation -->"))] | length)'
  # The behaviour, not just the spelling: the PR section is omitted only when the record holds
  # no finding, and its header must not key on "non-empty" (every audited run is non-empty now).
  hasfx "spine: PR auditor section omitted only when no block holds a finding" "$SPINE" 'or every block in it is `findings: none` / `scan: none`'
  hasfx "spine: PR auditor section header keys on a finding, not on non-empty" "$SPINE" 'mandatory whenever that record holds at least one finding'
  hasfx "spine: findings: none is auditor-axis only (role reason kept)" "$SPINE" '`findings: none` describes the **auditor axis only**'
  lacksfx "spine: old 'writes no block when nothing to record' is gone" "$SPINE" 'writes no block when there is nothing at all to record'
  lacksfx "spine: old 'mandatory whenever that record is non-empty' is gone" "$SPINE" 'mandatory whenever that record is non-empty'
  lacksfx "review: old 'both are absent when execute found nothing' is gone" "$GLD/commands/review.md" 'both are absent when execute found nothing'
  lacksfx "spine: free-prose no-scan marker is gone (scan: none replaces it)" "$SPINE" 'no scan this attempt'
  hasfx "spine: a scan: none attempt still re-states pending findings" "$SPINE" 'A `scan: none` attempt still **re-states every finding the previous block left at `looped-back`**'
  # Clean advance blocks now sit between loop-backs; the stagnation «before» half must skip them,
  # or a repeated BLOCKED after a test/qa re-entry compares against "nothing" and never escalates.
  hasfx "stagnation: «before» half is judged per axis, not by block shape" "$GLD/commands/atoms/_stagnation.md" 'carries no loop-back reason ON THAT AXIS'
  hasfx "stagnation: a scan: none block is read on the role axis" "$GLD/commands/atoms/_stagnation.md" 'carries the verify-gap reason and is read on the role axis'
  lacksfx "spine: no shape-based skip list (scan: none carries a role reason)" "$SPINE" 'blocks that did not loop back (`findings: none`, `scan: none`'
  hasfx "spine: Step 4 guard points at the most recent loop-back block" "$SPINE" 'the most recent audit-record block that carries a loop-back reason on that axis'
  hasfx "spine: Step 4 guard reads a scan: none block on the role axis" "$SPINE" 'normally carries the verify-gap reason and **is** read on the role axis'
fi

echo "== 14. 리팩토링 슬롯 — 예약이지 할당량이 아니다 =="

# 슬롯이 "무조건"으로 변하면 근거 없는 리팩토링이 리뷰 처리량을 먹는다. 철자로 지킬 수 있는 것은
# 게이트·용량·기록 토큰·의존 위치 네 가지다.
PLAN14="$GLD/commands/sprint/plan.md"
RETRO14="$GLD/commands/sprint/retro.md"
CONFIG14="$GLD/commands/config.md"
INIT14="$GLD/commands/init.md"
hasfx "plan.md: 슬롯은 예약이지 강제가 아니다" "$PLAN14" "**reserved, not mandatory**"
hasfx "plan.md: 슬롯도 readiness·크기 게이트를 면제받지 않는다" "$PLAN14" "the slot gets **no exemption**"
hasfx "plan.md: 슬롯은 용량 안에서 센다" "$PLAN14" "counts inside the capacity, not on top of it"
hasfx "plan.md: 슬롯은 준비하는 멤버의 기반으로 들어간다" "$PLAN14" "enters the graph as a foundation"
hasfx "plan.md: 초안은 사람 승인 뒤 Phase 6 에서 만든다" "$PLAN14" "Create the refactor slot's Issue"
hasfx "plan.md: 자리표시자는 기존 멤버보다 큰 번호다" "$PLAN14" "placeholder **\`999999999\`**"
# 자리표시자 0 은 굵게·평문 어느 철자로도 되살아나면 안 된다 (fixed-string 이라 두 철자를 모두 막는다)
lacksfx "plan.md: 자리표시자 0 이 되살아나지 않았다(평문)" "$PLAN14" "placeholder \`0\`"
lacksfx "plan.md: 자리표시자 0 이 되살아나지 않았다(굵게)" "$PLAN14" "placeholder **\`0\`**"
hasfx "plan.md: 슬롯이 깊이를 더할 때만 물러난다" "$PLAN14" "with-slot depth ≤ \`max(EFFECTIVE_CAP, without-slot depth)\`"
hasfx "plan.md: 슬롯이 돌려준 자리는 기능 멤버로 채운다" "$PLAN14" "A seat the slot gives back is refilled"
hasfx "plan.md: PO 가 refactor 후보 전부를 평가한다" "$PLAN14" "rate every candidate tagged \`refactor\` or \`refactor-slot\`, whether or not you selected it"
hasfx "plan.md: 기각은 슬롯을 비우지 않는다(재스폰 1회)" "$PLAN14" "Rejecting a pick does not empty the slot — one re-spawn"
hasfx "plan.md: 준비 실패한 초안도 재스폰한다" "$PLAN14" "a draft rejected **only** because it prepares no selected member"
hasfx "plan.md: 기각된 PO 기능 픽은 기능 후보로 돌아간다" "$PLAN14" "A rejected pick the product-owner ranked as a feature goes back to the feature picks"
hasfx "plan.md: 어떤 이유로든 슬롯이 떠나면 보충" "$PLAN14" "**for any reason**"
hasfx "plan.md: stack-cap 슬롯만 재입장 가능" "$PLAN14" "**only a \`skip (stack-cap)\` slot**"
lacksfx "plan.md: 준비 확인이 용량 컷 이전 문구로 돌아가지 않았다" "$PLAN14" "After the feature picks are settled, require"
hasfx "retro.md: PR 없이 닫힌 슬롯 이슈는 refused" "$RETRO14" "none, **slot Issue closed**"
hasfx "plan.md: 재실행은 고아 슬롯 이슈를 먼저 쓴다" "$PLAN14" "**A resumed slot**"
hasfx "plan.md: 초안 본문에 Files 가 들어간다" "$PLAN14" "(Why · Files ·"
hasfx "plan.md: fetch 는 리더가 한다(서브에이전트는 읽기 전용)" "$PLAN14" "The fetch is the leader's, not the sub-agent's"
hasfx "retro.md: paths 는 Files 에서 온다" "$RETRO14" "from the slot Issue's **Files** section"
hasfx "plan.md: 슬롯은 선택된 멤버를 준비해야 한다" "$PLAN14" "The slot must prepare this sprint's work"
hasfx "plan.md: 재스폰은 (c) 만 deps-slot.md 에 쓴다" "$PLAN14" "asking for **(c) only**"
hasfx "plan.md: 재스폰은 기각된 번호를 넘긴다" "$PLAN14" "Pass the rejected numbers, not"
hasfx "plan.md: fetch 는 refspec 형식이다" "$PLAN14" "git fetch origin <d>:refs/remotes/origin/<d>"
hasfx "plan.md: fetch 실패 경로" "$PLAN14" "PAST SLOTS: unverifiable"
hasfx "plan.md: CANDIDATES 에 tag 필드" "$PLAN14" "tag (\`refactor-slot\` | \`refactor\` | \`—\`)"
hasfx "plan.md: 재개 슬롯은 최신 트래커 이후 생성분만" "$PLAN14" "**and** it was created after"
hasfx "plan.md: 자리는 슬롯 아니면 보충분, 둘 다는 아니다" "$PLAN14" "The seat is the slot's or the refill's, never both"
hasfx "retro.md: 슬롯 본문을 따로 읽는다" "$RETRO14" "gh issue view <slot> --json body"
hasfx "plan.md: fetch 실패 대체 규칙이 tech-lead 가 읽는 절에 있다" "$PLAN14" "**DEFAULT BRANCH \`unavailable\`** (the fetch failed)"
hasfx "plan.md: unverifiable 이어도 항목은 넘긴다" "$PLAN14" "**keep the entries**"
hasfx "plan.md: 트래커가 한 번도 없으면 시간 조건 충족" "$PLAN14" "tracker has ever existed → the bound is met"
hasfx "plan.md: 보충이 촉발한 재계산은 슬롯을 다시 들이지 않는다" "$PLAN14" "that the slot's own refill triggers never re-admits the slot"
hasfx "plan.md: PAST SLOTS 는 merged/refused 만 본다" "$PLAN14" "**Only \`merged\` and \`refused\` entries are checked**"
hasfx "plan.md: 출처와 무관하게 라벨 없는 슬롯에 라벨을 묻는다" "$PLAN14" "of any origin: draft, resumed or existing"
hasfx "plan.md: 자리표시자가 본문·보드에 새지 않는다" "$PLAN14" "\`999999999\` must not reach"
lacksfx "plan.md: 'rerun Phase 4' 지시가 되살아나지 않았다" "$PLAN14" "rerun Phase 4"
hasfx "plan.md: 재실행이 같은 슬롯 이슈를 찾는 마커" "$PLAN14" "<!-- guild:refactor-slot -->"
hasfx "plan.md: 트래커에 슬롯 줄이 항상 있다" "$PLAN14" "The 리팩토링 슬롯 line is always written"
hasfx "plan.md: 슬롯 기록 토큰 집합" "$PLAN14" "skip (<disabled|no-candidate|not-ready|capacity|stack-cap|human-declined|epic-overlap|ad-hoc>)"
hasfx "plan.md: git 스캔은 Step 0·1 만" "$PLAN14" "**Step 0 and Step 1 only**"
hasfx "plan.md: 슬롯 조상에게는 간선을 걸지 않는다(순환 방지)" "$PLAN14" "Never add the edge to an ancestor of the slot"
hasfx "plan.md: 슬롯이 기능 멤버의 스택 자리를 빼앗지 않는다" "$PLAN14" "The slot never costs a feature member its place in the stack"
hasfx "plan.md: 상한 초과 시 슬롯은 통째로 물러난다(간선 일부 삭제 금지)" "$PLAN14" "Do **not** keep the slot by deleting some of its edges"
hasfx "plan.md: 준비 안 된 기존 refactor 이슈는 초안 경로를 막지 않는다" "$PLAN14" "does not end the search"
hasfx "plan.md: (c) 는 슬롯이 바꿀 파일을 적는다" "$PLAN14" "**Files** — the source files the slot reshapes"
hasfx "plan.md: PAST SLOTS 는 기본 브랜치를 읽는다" "$PLAN14" "git log origin/<default-branch> --since=<date>"
hasfx "plan.md: 라벨 확인은 Phase 0 의 --limit 200 목록을 쓴다" "$PLAN14" "**Phase 0 step 2's label list**"
hasfx "plan.md: --create 가 라벨 생성을 승인하지 않는다" "$PLAN14" "Ask this even under \`--create\`"
hasfx "plan.md: 슬롯 readiness 는 더 엄격하다" "$PLAN14" "its readiness gate is **stricter**"
hasfx "retro.md: refused 에 closed_at 을 쓴다" "$RETRO14" "\`closed_at\` — the slot PR's \`closedAt\`"
hasfx "retro.md: PR 조회가 closedAt 을 가져온다" "$RETRO14" "mergedAt,closedAt,reviewDecision"
hasfx "retro.md: history 에 merged_at 을 쓴다" "$RETRO14" "\`merged_at\` — the slot PR's \`mergedAt\`"
hasfx "run.md: 즉석 경로는 skip (ad-hoc) 를 쓴다" "$GLD/commands/sprint/run.md" "리팩토링 슬롯 \`skip (ad-hoc)\`"
hasfx "retro.md: 슬롯 결과에 refused 가 있다" "$RETRO14" "\`refused\` is the signal, \`skip\` is not"
hasfx "retro.md: history 에 refactor 필드를 쓴다" "$RETRO14" '"refactor": { "issue": 140, "outcome": "merged"'
hasfx "retro.md: 슬롯 줄이 없는 옛 트래커는 결과를 지어내지 않는다" "$RETRO14" "do not invent \`skip\`"
hasfx "config.md: refactor_slot setter" "$CONFIG14" "--refactor-slot=<on|off>"
hasfx "config.md: 키가 없으면 on" "$CONFIG14" "An absent key means \`on\`"
hasfx "init.md: 기본 config 에 refactor_slot" "$INIT14" '"refactor_slot": true'

# ── 규율 7 기계화 — 지시문의 모든 백분율이 등재돼 있는가 ──────────────────
# ⚠ **존재 검사가 아니라 전수 대조다.** 라운드 6 에서 `verification.md 1.5%` 가 ① 도구가
# 찍지 않는 수이면서 ② 반올림까지 틀린 채로 출하돼 있었다 — 검사가 없었기 때문이다.
# 이 검사는 「값이 맞는가」를 못 본다(코퍼스가 레포에 없다). **출처 없는 수가 들어오는 것**을
# 막는다. 새 수를 쓰려면 `design/guild/tools/measured-figures.tsv` 에 「어느 절이 찍는가」를
# 함께 적어야 하고, 그 강제가 곧 재현 경로의 보존이다.
LEDGER="$HERE/../../../design/guild/tools/measured-figures.tsv"
if [ ! -f "$LEDGER" ]; then
  bad "규율 7: 측정치 원장이 있다" "원장 파일" "없음: $LEDGER"
else
  # ⚠ 추출을 파이썬으로 한다. 라운드 12 에서 셸 정규식판이 **공허**했다 — `**~23**` 도
  #    `**p90 is 54**` 도 못 잡아서, 미등재 턴 수를 넣어도 통과했다(변이로 확인). 굵은 강조
  #    안이든 밖이든 **"turn(s)" 가까이의 정수**와 모든 백분율을 잡는다.
  _unlisted="$("$PY" - "$LEDGER" "$GLD" <<'LGPY'
import io, os, re, sys
ledger, gld = sys.argv[1], sys.argv[2]
known = set()
for line in io.open(ledger, encoding="utf-8"):
    if line.startswith("#") or "\t" not in line:
        continue
    known.add(line.split("\t")[0].strip())
PCT = re.compile(r"[0-9]+(?:\.[0-9]+)?(?:–[0-9]+(?:\.[0-9]+)?)?%")
# ⚠ **인접만 인정한다.** 30자 창을 두면 "Step 0 … turn" 이 걸려 노이즈가 된다(라운드 12
#    실측: `_preflight.md:0`·`:1` 오검출). 대신 지시문 쪽이 수와 "turns" 를 붙여 쓰도록
#    표현을 맞췄다 — 검사가 물 수 있게 만드는 것도 작업의 일부다.
# ⚠ `k−1 turns` 의 1 을 실측치로 오인하지 않도록 앞자리를 막는다(라운드 12 실측).
TURN = re.compile(r"(?<![\w\-\u2212])([0-9]+)\*{0,2} turns?\b")
bad = []
for rel in ("atoms/_bash_rules.md", "atoms/_preflight.md", "atoms/_execute_spine.md",
            "atoms/_stagnation.md", "qa.md", "test.md", "implement.md", "refactor.md"):
    f = os.path.join(gld, "commands", rel)
    if not os.path.exists(f):
        continue
    txt = io.open(f, encoding="utf-8").read()
    got = set()
    for m in PCT.findall(txt):
        got.update(x.rstrip("%") + "%" for x in m.split("–"))
    got.update(TURN.findall(txt))
    for v in sorted(got):
        if v not in known:
            bad.append(os.path.basename(f) + ":" + v)
print(" ".join(bad))
LGPY
)"
  if [ -z "$_unlisted" ]; then
    ok "규율 7: 지시문의 모든 실측치(백분율·턴 수)가 원장에 등재돼 있다"
  else
    bad "규율 7: 지시문의 모든 실측치(백분율·턴 수)가 원장에 등재돼 있다" "전부 등재" "미등재 —$_unlisted"
  fi
fi

echo "== persona spawns take their tier from the role file (_model_tiering.md Section 0) =="
# A spawn that names a literal tier makes the role file's `model:` inert, so evolve's default-tier
# review has nothing it can edit — the historical reason this wiring exists: in one repo the review
# that proposed acting on tech-lead/execute escalations found it could not apply anything. Every spawn whose prompt adopts a `.claude/agents/<role>.md` persona must read the tier
# from that file; non-persona spawns (auditor, scans, readiness) keep their literal.
cat > "$WORK3/tier.py" <<'TIERPY'
import glob, os, re, sys
gld = sys.argv[1]
lit = re.compile(r"`model`:\s*`(haiku|sonnet|opus)`")
persona, wrong = 0, []
for f in sorted(glob.glob(os.path.join(gld, "commands/**/*.md"), recursive=True)):
    L = open(f, encoding="utf-8").read().split("\n")
    for i, line in enumerate(L):
        if "subagent_type" not in line:
            continue
        nxt = "\n".join(L[i:i + 4])
        if "Adopt the persona in `.claude/agents/" not in nxt:
            continue
        persona += 1
        if lit.search(line) or "role file's `model:`" not in line:
            wrong.append("%s:%d" % (os.path.relpath(f, gld), i + 1))
print("%d %s" % (persona, " ".join(wrong)))
TIERPY
_tier="$("$PY" "$WORK3/tier.py" "$GLD")"
_tier_n="${_tier%% *}"; _tier_bad="${_tier#* }"; [ "$_tier_bad" = "$_tier" ] && _tier_bad=""
if [ -z "$_tier_bad" ] && [ "${_tier_n:-0}" -ge 14 ]; then
  ok "every persona spawn reads its tier from the role file ($_tier_n sites)"
else
  bad "every persona spawn reads its tier from the role file" ">=14 sites, none literal" "n=$_tier_n literal/missing: $_tier_bad"
fi
hasfx "tiering: Section 0 defines the role-file default and its fallback" "$GLD/commands/atoms/_model_tiering.md" 'Accept exactly `haiku`, `sonnet` or `opus`'
hasfx "tiering: Section C says a role-file change moves every stage of that role" "$GLD/commands/atoms/_model_tiering.md" 'which **other** stages that role runs in will move with it'
# Execute-stage escalations are FILED under the role that rejected the work, but the redone work is
# the developer's. Proposing on the filing role raises the reviewer and leaves the failing attempt
# unchanged (adversarial review of 0.86.0, round 1).
hasfx "tiering: proposal targets the role whose output was redone" "$GLD/commands/atoms/_model_tiering.md" '**The target — the role whose output was redone**'
# The trigger is a measurable share (Issues with a rejected execute first attempt / Issues
# executed), not an escalation rate — `--escalated` is set on every retried execute loop-back and
# carries no information (adversarial review of 0.86.0, rounds 2–3).
hasfx "tiering: trigger is the first-attempt rejection share per window" "$GLD/commands/atoms/_model_tiering.md" '**The measure — the first-attempt rejection share, per window.**'
hasfx "tiering: the bar is >=50% in >=3 consecutive windows of >=3 Issues" "$GLD/commands/atoms/_model_tiering.md" '**≥ 50% in each of ≥3 consecutive qualifying windows**'
hasfx "tiering: a raise is followed up and may be reverted, with a hold" "$GLD/commands/atoms/_model_tiering.md" 'do **not** re-propose the raise for the next **3 windows**'
hasfx "tiering: hard rule names the revert exception" "$GLD/commands/atoms/_model_tiering.md" '**One exception**: reverting a raise'
lacksfx "tiering: no claim that the retry tier is doing the real work" "$GLD/commands/atoms/_model_tiering.md" 'the retry tier is doing the real work most of the time anyway'
lacksfx "evolve: no claim that the retry tier is doing the real work" "$GLD/commands/evolve.md" 'the retry tier is already doing the real work'
hasfx "evolve: model-tier items are excluded from the per-signal regression match" "$GLD/commands/evolve.md" '**Model-tier items are not matched here**'
# The share needs a denominator (merged PRs → Issues) and a per-Issue numerator; both come from
# scan_corrections as slim lists, and the numerator is counted at ANY time — an Issue's loop-back
# usually lands a run before its PR merges (adversarial review of 0.86.0, round 4: both BLOCKERs).
hasfx "scan_corrections: emits execute_rejections for the scorecard" "$GLD/commands/atoms/scan_corrections.md" '**Also emit `execute_rejections[]`**'
hasfx "scan_corrections: emits merged_prs with a range search (no > in the arg)" "$GLD/commands/atoms/scan_corrections.md" 'gh pr list --state merged --search "merged:<window-start>..*"'
hasfx "tiering: numerator counts rejections at any time, not only in the window" "$GLD/commands/atoms/_model_tiering.md" '**at any time**, not only inside the window'
hasfx "tiering: window starts at the previous evolve commit time" "$GLD/commands/atoms/_model_tiering.md" 'the committer timestamp of the commit whose subject starts `chore(guild): evolve #<n-1> —`'
hasfx "tiering: window start excludes rollback reverts" "$GLD/commands/atoms/_model_tiering.md" 'anchored so a rollback'
lacksfx "spine: no stale 'never pass --escalated' on auditor captures" "$GLD/commands/atoms/_execute_spine.md" 'Never pass `--escalated` on this capture'
# Consolidation moves an applied item's evidence out of the active log; reading only the active
# log would deflate the follow-up's "before" share and the revert could never fire (round 5).
hasfx "scan_corrections: execute_rejections also reads consolidated.jsonl" "$GLD/commands/atoms/scan_corrections.md" 'Read `.claude/guild/memory/consolidated.jsonl` too, with the same filter'
lacksfx "scan_corrections: escalated no longer said to feed the scorecard" "$GLD/commands/atoms/scan_corrections.md" "feeds evolve's Phase 2.5 model-tier scorecard"
hasfx "evolve: window start is subject-anchored (a rollback revert cannot match)" "$GLD/commands/evolve.md" 'git log -1 --format=%cI --grep="^chore(guild): evolve #<n-1> —"'
hasfx "tiering: an unmeasured run neither passes nor breaks the streak" "$GLD/commands/atoms/_model_tiering.md" 'A run with **no measurement at all**'
# The bar and the follow-up read PAST windows; without a ledger row per run there is no series
# to read and a raise can never be proposed from durable data (round 6).
hasfx "evolve: Phase 7 writes a model-tier scorecard row every run, with a status" "$GLD/commands/evolve.md" '- **Model-tier scorecard** — **every run writes one row**, measured or not'
lacksfx "spine: auditor cap no longer cites an escalated rate" "$GLD/commands/atoms/_execute_spine.md" 'would inflate the `--escalated` rate'
lacksfx "audit: escalation rate is not read as evidence a higher tier was needed" "$GLD/commands/audit.md" 'most recent loop-backs needed the bumped tier'
hasfx "evolve: model-tier HR targets the redone role" "$GLD/commands/evolve.md" 'propose raising **the role whose output was redone**'
hasfx "spine: --escalated only when the tier was actually raised" "$GLD/commands/atoms/_execute_spine.md" 'add `--escalated` when Step 4 actually raised the retry'

echo "== capture reconciliation at stage exit (_signals.md Section C) =="
# Nothing checked that a capture happened; members ended `done` with zero entries three sprints
# running. Each stage stamps its start and reconciles recorded vs owed before every return.
hasfx "signals: capture reconciliation is defined" "$GLD/commands/atoms/_signals.md" '### Capture reconciliation (stage exit — execute, test, qa)'
hasfx "signals: review captures the human's own finding" "$GLD/commands/atoms/_signals.md" 'Human finds a defect **themselves** at PR review'
hasfx "review: the human's own fixed finding is captured" "$GLD/commands/review.md" "**Also capture the human's OWN finding**"
for _st in "$SPINE" "$GLD/commands/test.md" "$GLD/commands/qa.md"; do
  hasfx "$(basename "$_st"): marks the stage start durably" "$_st" 'capture_signal.py --mark --issue'
  hasfx "$(basename "$_st"): reconciles captures before returning" "$_st" '*Capture reconciliation'
done
# The Step 0 mark line also contains "*Capture reconciliation", so the loop above cannot tell
# whether the exit-side pointer survived; pin the exit-side sentences themselves (round 3).
hasfx "test.md: Step 3 reconciles immediately before each return" "$GLD/commands/test.md" '**Capture reconciliation immediately before each return line below**'
hasfx "qa.md: Step 3 reconciles immediately before each return" "$GLD/commands/qa.md" '**Capture reconciliation immediately before each return line below**'
hasfx "spine: Step 6 reconciles first" "$SPINE" '**Capture reconciliation first**'
hasfx "qa.md: a defect is captured before the Step 2 return" "$GLD/commands/qa.md" '**make the capture in the next bullet first**, then return'

hasfx "spine: audit-record blocks carry the invocation line" "$SPINE" 'Each block also carries the ASCII line `invocation: <stage-start>`'
hasfx "handoff K: invocation: is a machine token" "$HANDOFF" 'the `invocation: <ISO>` line'
hasfx "signals: owed is counted per axis (auditor-only and MAJOR owe nothing)" "$GLD/commands/atoms/_signals.md" 'a loop-back driven only by the auditor owes'
hasfx "review: the human's own finding uses the non-roster role human" "$GLD/commands/review.md" 'Same call with `--role human`'
hasfx "scan_corrections: role human is in the strongest (human) tier" "$GLD/commands/atoms/scan_corrections.md" 'a defect the human found **themselves** at PR review (`role: human`'
hasfx "evolve: role human is never an HR subject" "$GLD/commands/evolve.md" '`role: auditor` and `role: human` are never HR subjects'
hasfx "signals: reconcile per kind" "$GLD/commands/atoms/_signals.md" 'Per kind, because a total lets one kind'
hasfx "signals: a missing mark at exit is skipped, never re-marked" "$GLD/commands/atoms/_signals.md" '**Exit 2 (no mark) → skip the reconciliation and say so in the narration.**'
# The read-only modes must actually work: --count filters by issue, stage and time.
_cs="$GLD/commands/atoms/capture_signal.py"; _cl="$WORK3/gt_count.jsonl"
"$PY" "$_cs" --kind correction --issue 5 --stage execute --role tech-lead --summary s --log "$_cl" >/dev/null 2>&1
"$PY" "$_cs" --kind correction --issue 6 --stage execute --role tech-lead --summary s --log "$_cl" >/dev/null 2>&1
"$PY" "$_cs" --kind verify-gap --issue 5 --stage test --role tester --summary s --log "$_cl" >/dev/null 2>&1
_c1="$("$PY" "$_cs" --count --issue 5 --stage execute --since 2000-01-01T00:00:00Z --log "$_cl" 2>/dev/null)"
_c2="$("$PY" "$_cs" --count --issue 5 --stage execute --since 2999-01-01T00:00:00Z --log "$_cl" 2>/dev/null)"
_c3="$("$PY" "$_cs" --count --issue 7 --stage execute --since 2000-01-01T00:00:00Z --log "$WORK3/absent.jsonl" 2>/dev/null)"
_now="$("$PY" "$_cs" --now 2>/dev/null)"
if [ "$_c1" = "1" ] && [ "$_c2" = "0" ] && [ "$_c3" = "0" ] && printf '%s' "$_now" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'; then
  ok "capture_signal: --count filters issue/stage/time, absent log = 0, --now is ISO UTC"
else
  bad "capture_signal: --count / --now" "1 0 0 <ISO>" "$_c1 $_c2 $_c3 $_now"
fi
# --mark persists the start (a compaction must not lose it); --since auto reads it back; a stage
# with no mark and a malformed bound are REFUSED (exit 2, no number) — a plausible 0 would
# trigger duplicate backfills (adversarial review of 0.87.0, round 1).
# A capture made BEFORE the mark must not be counted — the property re-marking broke (round 2).
printf '%s\n' '{"ts": "2000-01-01T00:00:00Z", "kind": "correction", "issue": 9, "stage": "qa", "role": "qa", "summary": "old"}' >> "$_cl"
"$PY" "$_cs" --mark --issue 9 --stage qa --log "$_cl" >/dev/null 2>&1
"$PY" "$_cs" --kind correction --issue 9 --stage qa --role qa --summary s --log "$_cl" >/dev/null 2>&1
_m1="$("$PY" "$_cs" --count --issue 9 --stage qa --since auto --log "$_cl" 2>/dev/null)"
"$PY" "$_cs" --count --issue 9 --stage test --since auto --log "$_cl" >/dev/null 2>&1; _m2=$?
"$PY" "$_cs" --count --issue 9 --stage qa --since 2026-10-02T09:00:00+09:00 --log "$_cl" >/dev/null 2>&1; _m3=$?
_m4="$("$PY" "$_cs" --count --issue 9 --stage qa --kind stagnation --since auto --log "$_cl" 2>/dev/null)"
if [ "$_m1" = "1" ] && [ "$_m2" = "2" ] && [ "$_m3" = "2" ] && [ "$_m4" = "0" ]; then
  ok "capture_signal: --mark + --since auto; --kind filters; unmarked stage and malformed --since are refused"
else
  bad "capture_signal: --mark / auto / --kind / refusal" "1 2 2 0" "$_m1 $_m2 $_m3 $_m4"
fi

# ── 시각 회귀 (golden / VRT) — 쓰고, 돌리고, 사람에게 보여 준다 (0.88.0) ─────────────
# 사람은 코드보다 이미지를 빨리 검토한다. 그래서 UI 이슈는 시각 케이스를 쓰고(design),
# 기준 이미지로 만들고(execute), 돌리고(test), designer 가 이미지를 직접 열고(qa), PR 이
# 이미지 비교로 안내한다(spine Step 5). 동시에 기준 이미지 갱신은 기대값 자체를 바꾸므로
# 어느 단계도 갱신 명령을 "빨간 테스트를 초록으로" 쓰지 못하게 한다(INV2).
echo "== 시각 회귀 =="
SCAN="$GLD/commands/atoms/scan_repo.md"
hasfx "scan_repo: vrt 범주가 있다" "$SCAN" '**`vrt`** (visual regression'
hasfx "scan_repo: 기준 이미지 위치를 vrt_baselines 로 기록" "$SCAN" '"vrt_baselines":'
hasfx "scan_repo: 갱신 명령은 vrt_create(범위 한정 레시피)에만" "$SCAN" 'This is the **only** place an update command is recorded'
hasfx "scan_repo: TTY 필요한 명령은 -it 를 뺀다" "$SCAN" 'Drop `-i`/`-t`/`-it`'
hasfx "scan_repo: 추측한 glob 금지" "$SCAN" 'Only globs you have seen committed images under'
hasfx "init: config 에 commands.vrt" "$GLD/commands/init.md" '"vrt": "<simple cmd or null>"'
hasfx "init: config 에 visual.baselines" "$GLD/commands/init.md" '"visual": { "baselines":'
hasfx "init: VISUAL_TEST_SETUP 토큰을 안다" "$GLD/commands/init.md" '{{VISUAL_TEST_SETUP}}'
hasfx "update: 0.88.0 이전 레포는 감지 후 확인받아 기록" "$GLD/commands/update.md" 'run `atoms/scan_repo.md` **Section 2 step 3b only**'
hasfx "config: visual 을 보여 준다" "$GLD/commands/config.md" 'visual:     runnable='
hasfx "audit_readiness: UI 레포의 시각 회귀 부재를 지적" "$GLD/commands/atoms/audit_readiness.md" 'id: no-visual-test'
hasfx "verification.md 템플릿: 시각 회귀 행" "$GLD/templates/standards/verification.md" '{{VRT_CMD}}'
hasfx "tester 템플릿: 시각 케이스" "$GLD/templates/agents/tester.md" '화면이 바뀌는 이슈면 시각 케이스도 쓴다'
hasfx "tester 템플릿: 갱신 명령 금지" "$GLD/templates/agents/tester.md" '기준 이미지를 **갱신하는 명령은 실행하지 않고**'
hasfx "tester 템플릿: 프로젝트 특화 토큰" "$GLD/templates/agents/tester.md" '{{VISUAL_TEST_SETUP}}'
hasfx "designer 템플릿: 이미지를 직접 Read" "$GLD/templates/agents/designer.md" '이미지를 직접 Read로 열어'
DESIGN="$GLD/commands/design.md"
hasfx "design: VISUAL 판정을 스폰 전에" "$DESIGN" 'Visual decision first'
hasfx "design: tester 프롬프트가 VISUAL 을 받는다" "$DESIGN" 'Visual cases — `VISUAL = <yes|no>`'
hasfx "design: 시각 케이스 마커는 번역하지 않는다" "$DESIGN" '`<!-- guild:visual-cases -->` on its own line — the marker is **never translated**'
hasfx "design: 시각 케이스는 동작 케이스를 대체하지 않는다" "$DESIGN" 'A visual case never replaces a behavior case'
SPINE="$GLD/commands/atoms/_execute_spine.md"
hasfx "spine: 생성·갱신은 visual.create 로, 범위 한정" "$SPINE" '**or whose screen you changed** (a color/style fix touches no test file but changes its images), never the whole suite'
hasfx "spine: developer 가 baselines: 로 자기보고 (A 는 case 인용)" "$SPINE" '`A <path> — case: <visual case / ux.md state>`'
hasfx "spine: 자기보고를 git 으로 대조 (--no-renames)" "$SPINE" "git diff --name-status --no-renames <base>...HEAD -- ':(glob)<baseline-glob>'"
hasfx "spine: 미신고 변경은 not-green" "$SPINE" 'undeclared visual change: <paths>'
hasfx "spine: PR 시각 변경 섹션 마커" "$SPINE" '<!-- guild:visual-changes -->'
hasfx "spine: 비교 설정 → 갱신 → 추가 순서" "$SPINE" 'a changed comparison setting changes what *every* image means'
hasfx "implement: 시각 케이스를 golden/VRT 로 구현" "$GLD/commands/implement.md" 'implement each row as a golden / VRT test'
hasfx "refactor: 원장에 C/M/D 없음" "$GLD/commands/refactor.md" 'must hold **no `C`, `M`, `D`, `P` or replacing `A`, and no `A` without an existing visual case**'
hasfx "debug: 버그를 기록한 기준 이미지" "$GLD/commands/debug.md" 'whose existing baseline *recorded the bug*'
TESTMD="$GLD/commands/test.md"
hasfx "test: VISUAL_CASES / VISUAL_RUN 판정" "$TESTMD" '`VISUAL_CASES = yes` when `test-cases.md` carries'
hasfx "test: commands.vrt 를 실행" "$TESTMD" 'run `commands.vrt` after the test command'
hasfx "test: 갱신 명령·비교 설정 금지" "$TESTMD" 'Never run a create/update/approve command'
hasfx "test: 커버 안 된 시각 케이스는 미커버 AC" "$TESTMD" 'is **uncovered**, exactly like an AC with no test'
hasfx "test: 검증 범위에 원장 블록을 그대로" "$TESTMD" '(c) **the `<!-- guild:visual-baselines -->` block copied verbatim**'
lacksfx "test: 시각 QA 를 통째로 '안 돌린 것' 으로 두지 않는다" "$TESTMD" 'and manual/visual QA** (deferred / the human in M1)'
QAMD="$GLD/commands/qa.md"
hasfx "qa: 시각 주장도 자동화 먼저" "$QAMD" '**Visual claims** (a state renders'
hasfx "qa: designer 가 이미지 목록을 받는다" "$QAMD" '**Images — `<image list>`**'
hasfx "qa: designer 게이트는 읽기 전용" "$QAMD" 'this gate is read-only'
hasfx "qa: 바뀐 시각 기대값은 사람 체크리스트" "$QAMD" '**changed visual expectations**'
REVIEWMD="$GLD/commands/review.md"
hasfx "review: 기준 이미지는 기계적 산출물이 아니다" "$REVIEWMD" 'Visual baselines are not mechanical'
lacksfx "review: golden 이미지를 lockfile 과 함께 가볍게 묶지 않는다" "$REVIEWMD" 'generated artifacts (golden images, lockfiles)'
for R in README.md README.ko.md README.ja.md; do
  hasfx "$R: 시각 회귀 설명" "$GLD/../../$R" 'visual.baselines'
done
# 1회차 적대적 리뷰 — 단일 정의(Section L)와 그 구멍들
HO="$GLD/commands/atoms/_handoff.md"
hasfx "handoff: Section L 이 있다" "$HO" '## Section L — Visual tests (golden / VRT)'
hasfx "handoff L.1: runnable 이 없으면 false" "$HO" '**Absent → treat as `false`**'
hasfx "handoff L.3: 원장 마커는 ASCII" "$HO" '<!-- guild:visual-baselines -->'
hasfx "handoff L.3: 재진입 시 사유를 이어받는다" "$HO" '**carries reasons forward**'
hasfx "handoff L.4: 케이스 없는 A 는 위장된 재작성" "$HO" '**An `A` that cites no existing case is a rewrite in disguise**'
hasfx "handoff L.4: 비교 설정 완화도 검증 약화" "$HO" 'loosening a comparison setting, or excluding a test **to hide a difference the Issue did not intend**'
hasfx "handoff L.5: 환경 의심은 재작성 사유가 아니다" "$HO" '**L.5 Environment, not regression.**'
hasfx "scan_repo: 모노레포는 도구의 디렉터리 플래그로" "$SCAN" 'Every step runs from the repo root'
hasfx "scan_repo: test 에 이미 포함된 golden 은 vrt 로 두 번 기록하지 않음" "$SCAN" 'recording them twice runs them twice'
hasfx "design: VISUAL 은 VISUAL_AVAILABLE(runnable) 기준" "$DESIGN" '`VISUAL_AVAILABLE` per `_handoff.md` Section L.1'
hasfx "spine: developer 의 시각 실행은 visual.run_file 로 범위 한정" "$SPINE" 'run `<visual.run_file>` for each visual test file you touched or whose screen you changed'
hasfx "test: 환경 의심은 developer 루프 대신 사람에게" "$TESTMD" 'visual failures look environmental'
hasfx "test: diff 이미지는 이 호스트에 있을 때만" "$TESTMD" '**only if they exist on this host**'
hasfx "qa: designer 이미지 상한 12" "$QAMD" '**at most 12 in all**'
hasfx "review: PR head 가 체크아웃일 때만 Read" "$REVIEWMD" '**only when the PR head is the current checkout**'
lacksfx "implement: spine 규칙을 되풀이하지 않는다 (Section A)" "$GLD/commands/implement.md" 'and the `baselines:` line when'
lacksfx "handoff: 시각 QA 를 통째로 사람 몫으로 두지 않는다" "$HO" "and manual/visual QA is the human's step."
# 2회차 적대적 리뷰
hasfx "handoff L.0: visual.tests (게이트가 테스트 경로로 취급)" "$HO" '| `visual.tests` |'
hasfx "handoff L.0: visual.packages (패키지 단위 적용)" "$HO" '| `visual.packages` |'
hasfx "handoff L.0: env 에 아키텍처" "$HO" '**with the CPU architecture**'
hasfx "handoff L.4: 의도한 화면 변경의 재작성은 정상 경로" "$HO" '**When a rewrite is right**'
hasfx "handoff L.4: case 는 리더가 존재를 확인" "$HO" 'checked by the leader, not taken from the developer'"'"'s text'
hasfx "handoff L.3: 교체(A … replaces) 행" "$HO" 'A <path> — replaces <old path> — <reason>'
hasfx "spine: 인라인 비교 설정·이미지 인자 변경을 -G 로 찾는다" "$SPINE" "git diff --name-only -G 'comparatorOptions|"
hasfx "spine: case 를 직접 대조" "$SPINE" '**Check every `case:` yourself**'
hasfx "spine: runnable 이 아니면 생성 금지를 대입" "$SPINE" 'else "none — do not create or rewrite images here'
hasfx "spine: PATCH 시 visual-changes 블록도 교체·제거" "$SPINE" 'and the `<!-- guild:visual-changes -->` block replaced or appended'
hasfx "scan_repo: 스크립트 이름만으로는 VRT 아님" "$SCAN" '**a script name alone (`test:view`, `vrt`) is not evidence**'
hasfx "scan_repo: vrt_create 는 vrt 와 같은 태그·환경" "$SCAN" '**same tag/selection flags and environment**'
hasfx "design: visual.packages 안의 UI 만" "$DESIGN" '**inside `visual.packages`**'
hasfx "test: 모든 시각 실패에 환경 의심 예외" "$TESTMD" '- **Visual failures** (any golden/VRT failure'
hasfx "test: 케이스 이름을 남기는 verbose reporter" "$TESTMD" '`--reporter=verbose`'
hasfx "update: 로컬 영역의 시각 설정 줄은 확인받아 추가 제안" "$GLD/commands/update.md" 'also **offer** (one confirm, additive — INV4)'
# 3회차 적대적 리뷰
hasfx "handoff L.3: 원장 첫 줄 run: (시각 케이스 없이도 시각 스위트 실행)" "$HO" 'run: <yes|no>'
hasfx "handoff L.0: 커스텀 매처 visual.matchers" "$HO" '| `visual.matchers` |'
hasfx "handoff L.0: 범위 한정 비교 레시피 visual.run_file" "$HO" '| `visual.run_file` |'
hasfx "handoff L.0: config_files 는 레포 루트 기준 + setupFiles" "$HO" '**repo-root-relative** paths or globs'
hasfx "spine: pathspec 없는 git diff 를 막는다" "$SPINE" 'a `git diff` with no pathspec would list every changed file'
hasfx "spine: 커스텀 Screenshot 매처까지 -G 로" "$SPINE" 'to[A-Za-z]*Screenshot|matches(Golden|Reference)File'
hasfx "spine: 이전 원장은 페이지네이션해 읽는다" "$SPINE" 'paginated and checked for truncation exactly like Step 4'
hasfx "spine: 패키지 변경 여부를 run: 에" "$SPINE" 'git diff --name-only <base>...HEAD -- <visual.packages dir 1>'
hasfx "test: run: yes 면 시각 케이스 없이도 VRT" "$TESTMD" 'the execute ledger'"'"'s first line reads `run: yes`'
hasfx "test: 리포터 플래그 외 커맨드 변경 금지" "$TESTMD" '**a reporter flag is the only change you may make to the command**'
hasfx "test: runnable 아니면 VRT 미실행을 밝힌다" "$TESTMD" '`commands.vrt` 미실행'
hasfx "scan_repo: skip: 관용구는 --run-skipped" "$SCAN" '**`flutter test --tags golden --run-skipped`**'
hasfx "scan_repo: runnable 은 시험 실행으로" "$SCAN" '**Decide `vrt_runnable` from evidence when you can**'
# 4회차 적대적 리뷰
hasfx "handoff L.0: run_file 은 runnable 일 때만" "$HO" 'Used **only when `visual.runnable` is `true`**'
hasfx "handoff L.4: 화면을 바꾼 테스트의 이미지도 재작성 범위" "$HO" '**or whose screen it changed**'
hasfx "handoff L.3: 시각 매처 순감소는 C 행" "$HO" 'visual assertion removed: <reason>'
hasfx "spine: developer 시각 실행은 runnable 일 때만" "$SPINE" 'and `visual.run_file` is set **and `visual.runnable` is `true`**'
hasfx "spine: 색·스타일 수정의 이미지 재작성 허용" "$SPINE" 'scoped to the visual test files you touched **or whose screen you changed**'
hasfx "spine: 한 매처가 여러 이미지(-dark)를 쓰는 경우" "$SPINE" 'map the argument to every image it produces'
hasfx "update: 부분 visual 블록도 빠진 키만 감지" "$GLD/commands/update.md" 'or `visual` missing any key of `_handoff.md` Section L.0'
lacksfx "scan_repo: 비실행 예시에 run_file 을 두지 않는다" "$SCAN" '"vrt_run_file": "flutter test --tags golden <file>"'
# 5회차 적대적 리뷰
hasfx "debug: 버그를 기록한 이미지는 수정 후 red + M 행이 증거" "$GLD/commands/debug.md" '**One carve-out — a visual-only bug whose existing image recorded the bug**'
hasfx "spine: execute 에서도 L.5 환경 의심은 사람에게" "$SPINE" '**Environment, not regression (`_handoff.md` Section L.5)**'
hasfx "scan_repo: exclude_tags 는 --tags 로 못 뒤집는다" "$SCAN" '**`exclude_tags: golden` cannot be overridden by `--tags`**'
hasfx "scan_repo: 0건 실행은 깨진 커맨드" "$SCAN" '**A run that reports zero tests'
hasfx "design: 한 호출이 여러 이미지를 쓰면 한 행" "$DESIGN" 'one row covers all of them'
hasfx "handoff L.4: 의도 밖 재작성 이미지는 되돌린다" "$HO" 'Restore those to their merge-base state before committing'
hasfx "init: 시각 매처 삭제는 경고 (차단 아님)" "$GLD/commands/init.md" 'dropping its screenshot matcher calls **warns**'
# 6회차 적대적 리뷰
hasfx "handoff L.3: 바이트 동일 이동은 R 한 행" "$HO" 'R <old path> -> <new path> — moved, unchanged'
hasfx "handoff L.3: 재생성 필요 P 행" "$HO" '`P` (pending regeneration)'
hasfx "spine: 정확한 이동은 --find-renames=100%" "$SPINE" 'git diff --name-status --find-renames=100% <base>...HEAD'
hasfx "spine: PR 에 재생성 필요 행" "$SPINE" '**재생성 필요**'
hasfx "refactor: R 이동은 허용" "$GLD/commands/refactor.md" '(an `R` — the image moved byte-for-byte with its component — is fine)'
hasfx "debug: 재작성 전에 red 를 먼저 남긴다" "$GLD/commands/debug.md" '**first** run `visual.run_file` on that test file against the old image'
hasfx "qa: P 행은 재생성 체크리스트" "$QAMD" '에서 재생성 필요한 기준 이미지'
lacksfx "handoff L.1: expect.element 를 단언으로 세지 않는다" "$HO" '`expect.element(`/`expectLater(` count as assertions'
# 7회차 적대적 리뷰
hasfx "spine: 이전 원장의 P 행을 이어받는다" "$SPINE" '**carry forward every `P` row of the previous block**'
hasfx "handoff L.3: P 는 git 에 안 보여도 유지" "$HO" '`P` rows carry forward too, though git never lists them'
hasfx "handoff L.1: 실행 불가여도 원장·P 는 적용" "$HO" 'the ledger and the developer'"'"'s `P` declarations still apply'
hasfx "handoff L.0: 제품 스타일시트는 config_files 아님" "$HO" '**never the product stylesheets a setup file imports**'
hasfx "review: P 행을 먼저, 확인할 점으로" "$REVIEWMD" '`P` rows (재생성 필요'
# 8회차 적대적 리뷰
hasfx "handoff L.3: P 는 철회할 수 있다" "$HO" '`P-withdrawn <path> — <reason>`'
hasfx "spine: developer 가 P 를 철회" "$SPINE" 'a `P-withdrawn` line drops its `P`'
hasfx "spine: 100% 이름 변경은 replaces 가 아니라 R" "$SPINE" '**unless call 4 pairs the old and new image as a 100% rename**'
hasfx "spine: create 가 null 이면 none 대입" "$SPINE" 'when visual.runnable is true and visual.create is non-null'
hasfx "handoff L.4: 시각 케이스 없는 이슈의 A 는 추가(근거)" "$HO" 'an `A` with a reason there is a plain addition'
hasfx "test: P 경로만의 실패는 루프 대신 사람에게" "$TESTMD" '**Except pending regeneration**'
# 9회차 적대적 리뷰
hasfx "spine: developer 에게 이전 P 행을 넘긴다" "$SPINE" '(earlier `P` rows: `<P rows of the previous block, or none>`)'
hasfx "spine: 되돌리기는 merge base 로 (HEAD 아님)" "$SPINE" '`git checkout <mb> -- <path>`, or `git rm` it when `<mb>` has no such file'
hasfx "spine: 케이스 없는 이슈의 A <path> — <reason> 형식" "$SPINE" 'Use `A <path> — <reason>` (no `case:`) only when'
hasfx "spine: 철회는 PR 에 보인다" "$SPINE" '- 철회 — `<path>`'
hasfx "handoff L.4: 되돌리기는 merge base 로" "$HO" '(`git checkout <mb> -- <path>`, or `git rm` when the merge base has no such file'
hasfx "test: 재생성 대기 시 라벨을 execute 로 되돌린다 (resume 이 execute 로 재진입)" "$TESTMD" '**move the stage label back to execute** in the same call that pauses'
hasfx "debug: 실행 불가 시각 버그는 PR 전에 멈추지 않는다" "$GLD/commands/debug.md" 'do not pause before the PR exists'
hasfx "spine: 철회만 있어도 PR 섹션을 만든다" "$SPINE" 'or this invocation recorded a `P-withdrawn`'
lacksfx "handoff: HEAD 로 되돌리지 않는다" "$HO" '`git checkout HEAD -- <path>`) instead of declaring'

# ── 리팩토링 슬롯의 안전망 (0.89.0) ─────────────────────────────────────────
# 테스트가 부족한 핫스팟을 리팩토링하면 "기존 테스트 green" 이 아무것도 증명하지 못한다.
# 안전망은 리팩토링 전에, 바뀌지 않은 코드에서 green 으로 깔고, 이후 손대지 않는다.
# 린트 룰은 반복 실패라는 근거가 필요하므로 evolve 경로에 남긴다.
echo "== 리팩토링 슬롯 안전망 =="
PLANMD="$GLD/commands/sprint/plan.md"
RFMD="$GLD/commands/refactor.md"
hasfx "plan: 공백 검사 (테스트·시각)" "$PLANMD" '**The gap check**'
hasfx "plan: 안전망만 하는 2b 초안" "$PLANMD" '2b. **A safety-net-only draft**'
hasfx "plan: 2b 는 공백 근거가 있어야" "$PLANMD" 'a hotspot that is already tested is no reason to fill the slot'
hasfx "plan: 린트 룰은 슬롯에 넣지 않는다" "$PLANMD" '**Lint rules are not part of the slot.**'
hasfx "plan: 안전망 규칙 — 리팩토링 전 자기 커밋에서 green" "$PLANMD" '*Added before the refactor, in their own commit, and green on the unchanged code*'
hasfx "plan: 안전망 규칙 — 공개 동작만" "$PLANMD" '*Public behavior only*'
hasfx "plan: 안전망 규칙 — 의심 버그는 고정하지 않음" "$PLANMD" '*Never pin a suspected bug*'
hasfx "plan: 크기 초과면 안전망을 남기고 리팩토링을 미룸" "$PLANMD" 'keep the net and drop the refactor to a later'
hasfx "plan: 안전망만 마커" "$PLANMD" '<!-- guild:safety-net-only -->'
hasfx "plan: 사람에게 안전망 줄을 보여 준다" "$PLANMD" '🧹 리팩토링 슬롯 (안전망만)'
hasfx "refactor: SAFETY_NET 판정" "$RFMD" 'Hold `SAFETY_NET` = `only` when the second is present'
hasfx "refactor: 프로덕션 파일보다 먼저 안전망" "$RFMD" 'Otherwise do this **first, before touching any production file**'
hasfx "refactor: 안전망 커밋에서 green 실행 증거" "$RFMD" 'RESULT extras for this paragraph: `safety-net: <commit sha (net laid first) or tree sha (step 6)>`'
hasfx "refactor: 안전망 커밋에 프로덕션 변경 없음을 git 으로" "$RFMD" 'git diff --name-only <mb> <sha>'
hasfx "refactor: 구현 고정 테스트는 BLOCKED" "$RFMD" 'a test that pins implementation, or one that cannot fail, is a `BLOCKED`'
hasfx "refactor: only 는 구조 개선 대신 커버리지 검사" "$RFMD" 'For `only`, check (2) and this coverage check **instead of** (1)'
hasfx "README.md: 리팩토링 슬롯 안전망" "$GLD/../../README.md" 'safety-net-only slot'
hasfx "README.ko.md: 리팩토링 슬롯 안전망" "$GLD/../../README.ko.md" '안전망만 까는 자리'
hasfx "README.ja.md: 리팩토링 슬롯 안전망" "$GLD/../../README.ja.md" '安全網だけを敷く枠'
# SN 1회차 적대적 리뷰
hasfx "plan: 공백 검사는 동작 단위 (파일 단위 아님)" "$PLANMD" '**per behavior, not per file**'
hasfx "plan: 테스트 없이 고친 fix 커밋이 공백 근거" "$PLANMD" '**Fix commits that changed no runnable test**'
hasfx "plan: 기존 refactor Issue 에도 공백 검사" "$PLANMD" '**Run the gap check on it too**'
hasfx "plan: 안전망 ASCII 마커" "$PLANMD" '`<!-- guild:safety-net -->` (never'
hasfx "plan: 안전망 줄은 Success-criterion 이기도" "$PLANMD" '**Each line is also a'
hasfx "plan: 2b 의 Files 는 프로덕션 파일" "$PLANMD" '**production** hotspot file(s) the net covers'
hasfx "plan: 라벨 없으면 2b 는 빠진다 (human-declined)" "$PLANMD" 'the 2b is dropped (`skip (human-declined)`)'
hasfx "plan: 크기 탈락 초안은 2b 로 전환" "$PLANMD" 'the leader converts it to a 2b instead of skipping'
hasfx "plan: 2b 머지 이력은 같은 경로 제외에서 면제" "$PLANMD" 'is exempt from this exclusion'
hasfx "plan: 기존 Issue 에 안전망을 덧붙인다" "$PLANMD" '**For an existing or resumed slot that gained a Safety net**'
hasfx "plan: tech-lead 스폰에 VISUAL 전달" "$PLANMD" 'VISUAL: <available or not per `_handoff.md` Section L.1'
hasfx "retro: 슬롯 kind 기록" "$GLD/commands/sprint/retro.md" '`kind` — `"safety-net-only"` when'
hasfx "analyze: 안전망 줄은 각각 AC (safety net)" "$GLD/commands/analyze.md" 'every line of that section becomes its own AC, tagged `(safety net)`'
hasfx "design: 안전망 시각 케이스면 VISUAL=yes" "$DESIGN" '**Safety net override**'
hasfx "design: 안전망만 슬롯의 skeleton" "$DESIGN" '구조 변경 없음 — 커버리지만'
hasfx "design: tester 의 안전망 케이스는 red-first 아님" "$DESIGN" 'passes on today'"'"'s code (it is not red-first)'
hasfx "refactor: 안전망은 test-cases 의 (safety net) 케이스" "$RFMD" 'The cases tagged `(safety net)` in `docs/specs/$1/test-cases.md`'
hasfx "refactor: 이동·import 만 수정은 허용" "$RFMD" 'git diff --name-status -M <sha> <branch>'
hasfx "refactor: post-transform-net 은 증명 안 됨으로 표시" "$RFMD" '`post-transform-net: <path @ blob sha, one per file — or none>`'
hasfx "refactor: 시임 없으면 테스트 불가 → 보고" "$RFMD" 'untestable without a seam: <behavior> — needs <seam>'
hasfx "refactor: 실패할 수 없는 테스트는 BLOCKED" "$RFMD" 'would each **fail if their behavior broke**'
hasfx "test: 안전망 케이스에 vacuous 가드, deferred 는 미실행으로" "$TESTMD" '**Safety-net cases**'
# SN 2회차 적대적 리뷰
hasfx "refactor: 이름 변경 검사는 pathspec 없이 (git 은 주어진 경로끼리만 짝짓는다)" "$RFMD" '(no pathspec on the last call'
hasfx "refactor: 안전망 증거 ASCII 블록" "$RFMD" '<!-- guild:safety-net-evidence -->'
hasfx "refactor: 재진입 시 안전망을 다시 깔지 않는다" "$RFMD" '**If an earlier block says `verified: yes`, the net already exists**'
hasfx "refactor: 안전망은 자기 새 파일에" "$RFMD" 'Write the net in **new test files of its own**'
hasfx "refactor: 시각 안전망 이미지는 안전망 커밋 안에" "$RFMD" 'an image made after the transform pins the transformed code'
hasfx "refactor: post-transform-net 은 추가만" "$RFMD" '**added in new files only**'
hasfx "refactor: deferral 은 tech-lead 가 확인" "$RFMD" 'confirm the developer'"'"'s "tried" line'
hasfx "refactor: deferred 동작 위로 변환 금지" "$RFMD" 'the transform must not proceed over it'
hasfx "plan: 이미 안전망 있으면 다시 안 붙임" "$PLANMD" 'never a second net'
hasfx "plan: analyze 이후 단계 Issue 는 안전망 없음" "$PLANMD" 'already **past analyze**'
hasfx "plan: fix 커밋 노이즈 제거" "$PLANMD" '**Drop noise** by subject'
hasfx "plan: 같은 브랜치 fix 는 하나로" "$PLANMD" '**Collapse one branch'"'"'s fixes**'
hasfx "plan: 지금도 미커버인지 확인" "$PLANMD" '**Check it is still uncovered today**'
hasfx "plan: 2b 는 라벨 거절 시 빠진다" "$PLANMD" '(없으면 이 안전망 슬롯은 빠집니다'
hasfx "plan: 시각 불가 2b 는 (로직만)" "$PLANMD" '`(로직만)` — the human approving'
hasfx "design: 시각 행도 (safety net) 태그 유지" "$DESIGN" 'behavior row **and** visual row alike'
hasfx "test: deferred 케이스를 tester 에게 넘긴다" "$TESTMD" '**Safety-net deferred cases —'
# SN 3회차 적대적 리뷰
hasfx "refactor: verified: no 면 증명만 다시" "$RFMD" '**If it says `verified: no`**'
hasfx "refactor: 증거 블록은 Step 2 의 한 번의 PATCH 안에서" "$RFMD" 'writes **inside Step 2'"'"'s one PATCH of that comment**'
hasfx "refactor: run 은 모든 net 파일 실행을 보여야" "$RFMD" 'does not show every net file **in `sha`** (by its path there'
hasfx "refactor: 동작 케이스는 commands.test 러너 파일에" "$RFMD" '**Behavior cases go in files the `commands.test` runner picks up**'
hasfx "refactor: 안전망 이미지는 safety-net- 접두사" "$RFMD" 'with a `safety-net-`'
hasfx "refactor: 다시 증명하되 reset 하지 않는다" "$RFMD" '**Re-prove, never reset**'
lacksfx "refactor: reset --hard 를 지시하지 않는다 (INV3)" "$RFMD" '(`git reset --hard <mb>`'
hasfx "refactor: tech-lead 에 deferred 줄 대입" "$RFMD" '`<the deferred: lines of the safety-net evidence block, or none>`'
hasfx "design: 2b 안전망은 항상 새 파일" "$DESIGN" 'always a **new** file beside the existing tests'
hasfx "plan: 2b 전환 시 Title·마커·Prepares 도 다시 씀" "$PLANMD" 'reduced to the members whose files share a file with the narrowed Files'
hasfx "plan: 공백 검사 예산 명시" "$PLANMD" '≤ ~3 commit diffs **in total**'
hasfx "plan: step 0/1 로그는 디렉터리 범위" "$PLANMD" 'scoped to the Files'"'"' **directories**, not the files'
hasfx "plan: analyze 이후라 안전망 없음을 사람에게" "$PLANMD" '안전망: 없음 — 이미 <stage> 단계라'
hasfx "plan: step 3 은 슬롯 멤버 먼저" "$PLANMD" '**Do the slot member first.**'
hasfx "plan: PAST SLOTS 항목에 kind" "$PLANMD" '{issue, outcome, kind, paths, merged_at,'
# SN 4회차 적대적 리뷰
hasfx "refactor: 증명은 커밋 없이 write-tree (훅·ref·브랜치 없음)" "$RFMD" 'that **tree** sha is the proof'
lacksfx "refactor: update-ref 를 쓰지 않는다 (사용자 설정에서 거부)" "$RFMD" 'git update-ref'
hasfx "refactor: --no-verify 금지 명시" "$RFMD" 'Never use `--no-verify`'
hasfx "refactor: 잔여물 검사는 브랜치가 정해진 뒤 (BRANCH + RESUME PROBE)" "$RFMD" 'run the EVIDENCE RULE'"'"'s **proof residue check** here — after the branch is bound'
hasfx "refactor: detached 판정은 symbolic-ref 로" "$RFMD" '`git symbolic-ref -q HEAD` (prints `refs/heads/<name>` on a branch'
hasfx "refactor: detached + 스테이징은 HEAD 가 base 의 조상일 때만 crash 로" "$RFMD" 'git merge-base --is-ancestor HEAD <base>'
hasfx "refactor: 복사본은 내용이 branch 에 있을 때만 (이름만으로는 안 됨)" "$RFMD" 'it never makes a path a proof copy by itself'
hasfx "refactor: 다른 브랜치의 스테이징은 이 Issue 일이 아님" "$RFMD" '**On another branch**'
hasfx "refactor: switch 실패는 버리지 않고 사람에게" "$RFMD" 'never by discarding them'
hasfx "refactor: 브랜치 위 스테이징은 tip 이 mb 여도 작업" "$RFMD" 'even when the branch tip still equals `<mb>`'
hasfx "refactor: developer 복귀 후 detached 면 브랜치로 되돌린다" "$RFMD" 'Right after the developer returns with nothing staged: `git switch <branch>`'
hasfx "refactor: 스냅샷 이동 전 대상 디렉터리 생성" "$RFMD" 'create a missing destination directory first with `mkdir -p`'
hasfx "refactor: 증거 블록에 leftover 줄" "$RFMD" 'leftover: <untracked paths a proof run left behind'
hasfx "spine: 변형의 전환 전 검사 훅이 슬롯 표에" "$SPINE" 'any check the variant runs after (a) binds an existing branch and **before** (c) switches to it'
hasfx "refactor: 브랜치 위 스테이징은 작업이지 잔여물 아님" "$RFMD" 'that is work, never residue'
hasfx "refactor: 증명 실행은 no-write 모드" "$RFMD" 'with the runner'"'"'s **no-write** mode'
hasfx "refactor: 스냅샷도 함께 git mv" "$RFMD" '`git mv` each net file **and its snapshot/screenshot files**'
hasfx "refactor: switch 전 index 가 mb 인지 확인" "$RFMD" 'confirm `git diff --cached --quiet` (the index is `<mb>` again) before'
lacksfx "refactor: 추적 안 되는 파일을 rm 하지 않는다" "$RFMD" 'and delete (`rm`) any untracked file'
hasfx "test: 안전망 증거 블록은 시각 설정과 무관하게 복사" "$TESTMD" 'block whenever the execute evidence has one** (independent of any visual config)'
hasfx "refactor: 정리는 mb 대비 새 파일만 rm" "$RFMD" 'git diff --cached --name-only --diff-filter=A <mb>'
hasfx "refactor: 추적 파일 미커밋 변경 없음을 확인" "$RFMD" '`git diff --quiet` and `git diff --cached --quiet`'
hasfx "refactor: 증명 트리가 사라지면 재증명" "$RFMD" '**A proof tree that is gone**'
hasfx "refactor: 증명에 없는 net 스냅샷은 not-done" "$RFMD" 'a **snapshot file of a net test** appears as `A`'
hasfx "refactor: only 검사도 branch 기준" "$RFMD" 'git diff --name-only <mb>...<branch>'
hasfx "run: 해시 불일치 + 미적용 slot-net 이면 plan 재실행 안내" "$GLD/commands/sprint/run.md" 'tell the human to re-run `/gld sprint plan` first'
hasfx "refactor: 스냅샷 파일도 net" "$RFMD" 'a `.snap` written after the transform would pin the transformed output'
hasfx "plan: 거절된 2b 는 2b 만 막는다" "$PLANMD" 'the human rejected that coverage, not a refactor of them'
lacksfx "refactor: -net-proof 브랜치를 만들지 않는다 (브랜치 탐색과 충돌)" "$RFMD" 'git switch -c <branch>-net-proof'
hasfx "refactor: 이동 후 안전망은 mb 시점 경로로 옮겨 증명" "$RFMD" 's tests live **at `<mb>`**'
hasfx "refactor: developer 프롬프트에 mb·branch 대입" "$RFMD" 'merge base `<mb>`, branch `<branch>`**'
hasfx "refactor: 재증명 시 post-transform-net 비움" "$RFMD" 'and `post-transform-net:` is cleared'
hasfx "refactor: verified 는 감사자 net 지적도 확인" "$RFMD" 'neither the tech-lead nor the 3.5a auditor named a net finding'
lacksfx "refactor: revert 로 되살리지 않는다 (안전망 수정까지 되돌림)" "$RFMD" 'git revert --no-edit'
hasfx "refactor: verified 는 tech-lead 확인 후" "$RFMD" '**At Step 4, once the tech-lead'"'"'s verdict is in, PATCH the block once more**'
hasfx "refactor: 모듈 경로만 바뀐 줄 허용 (jest.mock 포함)" "$RFMD" 'only in a quoted module path'
hasfx "refactor: post-transform-net 은 blob 으로 동결" "$RFMD" 'differs from the blob recorded when it was added'
hasfx "refactor: PR 있고 미검증이면 사람에게" "$RFMD" 'safety net has no evidence on an open PR'
hasfx "refactor: tech-lead 에 실행 가능한 러너 목록" "$RFMD" 'a tool Guild cannot run here does not count against the deferral'
hasfx "refactor: 분리 불가 deferred 는 무인 처리 포함" "$RFMD" 'OK PAUSE: needs-human — deferred net behavior'
hasfx "plan: Guild 가 돌릴 수 있는 단언만 커버리지" "$PLANMD" '**Only an assertion Guild can run counts as coverage**'
hasfx "plan: 2b 라벨 거절은 Phase 5 에서 human-declined" "$PLANMD" '(`skip (human-declined)`, the seat refilled per Phase 3'
hasfx "plan: 승인된 안전망을 트래커 코멘트에 보관" "$PLANMD" '<!-- guild:sprint:slot-net -->'
hasfx "plan: Phase 0 에서 끊긴 안전망 덧붙이기를 마친다" "$PLANMD" '**An interrupted net splice** — only now, after the verdict above is `proceed`'
hasfx "design: safety-net 마커에도 슬롯 지침" "$DESIGN" 'carries `<!-- guild:refactor-slot -->` or `<!-- guild:safety-net -->`'
# SN 5회차 적대적 리뷰
hasfx "plan: 러너가 다룰 수 없는 동작은 공백 아닌 finding" "$PLANMD" '**but only if it can be'
hasfx "plan: 안전망은 최대 5줄" "$PLANMD" '**at most 5 net lines in all**'
hasfx "plan: slot-net 코멘트에 slot 번호와 두 부분" "$PLANMD" 'a `slot: #<n>` line, then the three parts to splice'
hasfx "plan: --create 2b 드롭 후 다시 제시" "$PLANMD" 'the sprint is presented again before anything is created — the'
hasfx "refactor: 바이트 동일 이동은 reshaping 아님" "$RFMD" 'a byte-identical move (`R100`) does not reshape it'
hasfx "refactor: 기존 VRT 미실행을 PR 에" "$RFMD" 'existing VRT not run here'

# 후속 Issue 판정 (0.90.0) — 이슈를 만들지 말지를 사람에게 되던지지 않는다
FUMD="$GLD/commands/review.md"; FQMD="$GLD/commands/qa.md"; FIMD="$GLD/commands/init.md"
hasfx "review: 범위 밖 MAJOR 는 후속 Issue 등록 필요 판정" "$FUMD" '→ 후속 Issue 등록 필요 (MAJOR) — <이번 PR에서 고치지 않는 근거'
hasfx "review: BLOCKER 는 미루지 않는다" "$FUMD" '`BLOCKER` is **never** deferred'
hasfx "review: Step 5 에서 한 번만 묻는다" "$FUMD" '**후속 Issue (binary per item — asked once, before the 종합 판정).**'
hasfx "review: qa 의 unfiled 만 묻는다" "$FUMD" 'every `unfiled` line in the Issue'"'"'s `<!-- guild:followups -->` comment'
hasfx "review: 후속 Issue 항목마다 권장 의견을 붙인다" "$FUMD" '**Every `후속 Issue 등록 필요` item also carries your recommendation**'
hasfx "review: 권장은 두 단어 중 하나 + 근거" "$FUMD" '**`등록 권장 — <근거>`** / **`등록 권장하지 않음 — <근거>`**'
hasfx "review: 권장 판정이 금지어 규칙의 유일한 예외" "$FUMD" 'this recommendation verdict is the one exception to the hedge ban'
hasfx "review: 금지어 규칙 문장이 예외를 가리킨다" "$FUMD" 'the same hedge ban as Step 4, with the one exception for the recommendation below'
hasfx "review: 아무것도 가리키지 않는 근거는 금지" "$FUMD" 'and so does a 근거 that names nothing'
hasfx "review: 문구는 config.language 를 따른다" "$FUMD" '(ko wording; the strings follow `config.language` like every verdict)'
hasfx "review: 설계 유예는 기본이 권장" "$FUMD" '**(b) item → `등록 권장` by default**'
hasfx "review: 권장하지 않음은 qa 이후 바뀐 것이 있을 때만" "$FUMD" '**`등록 권장하지 않음` only when something changed after qa recorded it**: a commit made after qa last ran that altered the item'"'"'s premise without doing the work'
hasfx "review: 비교 기준은 committer 날짜, rebase 는 변경 아님" "$FUMD" 'the commit'"'"'s committer date is later than the `<!-- guild:qa:output -->` comment'"'"'s `updated_at`'
hasfx "review: 설계 문서를 다시 읽지 않는다" "$FUMD" 'do not re-read the design docs'
hasfx "review: 번호만 답하면 더한다" "$FUMD" 'a reply of numbers alone **adds** them to the recommended set (it never replaces it)'
hasfx "review: N만 은 목록을 바꾼다" "$FUMD" '"N만" **replaces** the set with N'
hasfx "review: 네/아니요가 아니면 확인 후 생성" "$FUMD" '**Any answer other than a plain yes or a flat no**: say the final set in one line'
hasfx "review: 불필요 항목을 지목해도 이유 없이 등록하지 않는다" "$FUMD" 'is not registered unless the human says why the covering Issue does not cover it'
hasfx "review: 권장하지 않음만 있을 때 아니요는 unfiled 유지" "$FUMD" 'a no leaves them `unfiled`, to be asked again by the next review'
hasfx "review: rebase 만 한 커밋은 변경이 아니다" "$FUMD" 'a commit that only rebased what qa already saw is not a change'
hasfx "qa: 네/아니요가 아니면 확인 후 생성" "$FQMD" 'any answer other than a plain yes or a flat no → echo the final set and create only on confirm'
hasfx "review: 기준 시각은 qa 만 쓰는 qa:output 의 updated_at" "$FUMD" 'the `<!-- guild:qa:output -->` comment'"'"'s `updated_at`, which only qa writes'
hasfx "review: 후보가 있을 때만 따로 읽는다" "$FUMD" 'Read that time only when an item is a candidate, as its own call'
hasfx "review: 아니요는 권장하지 않음 줄을 unfiled 로 둔다" "$FUMD" 'except a `등록 권장하지 않음` line, which a no leaves `unfiled`'
hasfx "review: 보류 결과의 기록 형식" "$FUMD" '`unfiled (보류 — 다음 review에서 다시 묻습니다)`'
hasfx "review: 생성 실패한 (a) 는 두 결과를 함께" "$FUMD" '`등록 권장 → unfiled (생성 실패) → 수정 필요로 복귀`'
hasfx "qa: 답변 해석은 review 와 같다" "$FQMD" 'except that numbers alone mean only those numbers'
hasfx "review: 권장하지 않은 항목의 기록을 질문에 밝힌다" "$FUMD" 'a yes that left out a `등록 권장하지 않음` line the question named as recorded so'
hasfx "review: 코멘트 기록은 권장 → 결과" "$FUMD" 'each item as `<recommendation> → <outcome>`'
lacksfx "review: 옛 질문 문구가 남지 않았다" "$FUMD" '위 등록 필요 2건을'
hasfx "qa: 대화형 후속 항목에도 권장 표시" "$FQMD" '→ 등록 권장 — <남는 결과: 무엇이 어떻게 문제가 되는지>'
hasfx "qa: 권장 표시는 금지어의 유일한 예외" "$FQMD" 'The one exception is the attended prompt below'
hasfx "qa: review 는 설계 문서를 다시 읽지 않는다 (review 와 일치)" "$FQMD" 'it does not re-read the design docs'
lacksfx "qa: 옛 질문 문구가 남지 않았다" "$FQMD" '위 등록 필요 <k>건을'
hasfx "review: 범위 밖 MAJOR 는 항상 등록 권장" "$FUMD" '**(a) finding → always `등록 권장`**'
hasfx "review: 질문의 기본값은 권장 항목" "$FUMD" '권장 2건(①②)을 등록하고, 권장하지 않은 ③은 등록하지 않음으로 기록할까요?'
hasfx "review: 권장 항목이 없어도 물어본다" "$FUMD" '권장하는 항목은 없습니다 — ③을 등록하지 않음으로 기록할까요?'
lacksfx "review: 맨 판정만 보여 주던 예시가 남지 않았다" "$FUMD" '→ 후속 Issue 등록 필요 — <이번 PR에서 고치지 않는 근거>'
hasfx "review: 등록돼야만 머지 판정에서 빠진다" "$FUMD" '**A `후속 Issue 등록 필요` finding counts as addressed only when it is actually tracked**'
hasfx "review: 생성 실패는 미등록" "$FUMD" 'no URL printed means **not registered**'
lacksfx "review: '후속 Issue를 제안할 것' 이 사라졌다" "$FUMD" '후속 Issue를 제안할 것'
hasfx "qa: 항목마다 판정 먼저" "$FQMD" '**Every examined item gets exactly one verdict, stated before any question**'
hasfx "qa: 후속 기록은 별도 코멘트" "$FQMD" 'It is a **separate comment, not a section of `<!-- guild:qa:output -->`**'
hasfx "qa: declined 는 다시 묻지 않는다" "$FQMD" 'carry it forward as `declined` and **do not ask again**'
lacksfx "qa: 판정 없는 '지금 이슈로 만들까요?' 가 사라졌다" "$FQMD" '— 지금 이슈로 만들까요?'
lacksfx "qa: 언어 고정 헤딩 '### 미등록 후속 항목' 이 사라졌다" "$FQMD" '### 미등록 후속 항목'
hasfx "handoff: guild:followups 마커" "$GLD/commands/atoms/_handoff.md" '| `<!-- guild:followups -->` … `<!-- /guild:followups -->` | qa (leader, Step 2.6);'
hasfx "init: 갭마다 판정 먼저" "$FIMD" 'Every **BLOCKER/MAJOR** gap gets **exactly one verdict, stated before any question**'
hasfx "init: MINOR 는 한 줄 카운트" "$FIMD" '`등록 불필요 <n>건 (MINOR — 리포트에만 기록)`'
lacksfx "init: 'offer MINOR too' 가 사라졌다" "$FIMD" 'offer MINOR too'
lacksfx "init: 선택지를 고르게 하지 않는다" "$FIMD" 'user picks which to file'

# 후속 Issue 1회차 적대적 리뷰
hasfx "review: PR 번호면 Issue 를 따로 해석" "$FUMD" '3. **Resolve the Issue too — `<ISSUE>`**'
hasfx "review: Step 5 답을 followups 에 기록" "$FUMD" '**Record the (b) outcomes on the Issue'
hasfx "review: (a) 는 열린 Issue 만 추적으로 친다" "$FUMD" '**For an (a) finding, only an OPEN Issue covers it**'
hasfx "qa: followups 는 페이지네이션해 읽는다" "$FQMD" 'issues/$1/comments --paginate --jq'
hasfx "qa: filed/declined 를 매번 이월" "$FQMD" '**every rewrite carries both forward**'
hasfx "handoff K: followups 토큰" "$GLD/commands/atoms/_handoff.md" "- the follow-up record's status tokens"
hasfx "init: GitHub 레포 없으면 기록만" "$FIMD" '`기록만 — GitHub 레포 없음`'
# 후속 Issue 2회차 적대적 리뷰
hasfx "review: 답이 무엇이든 followups 에 기록" "$FUMD" '**Record the (b) outcomes on the Issue — always, whatever the answer**'
hasfx "review: 일괄 거절은 모두 declined" "$FUMD" '**a flat no makes every asked line `declined`**'
hasfx "review: 구버전 섹션이면 followups 새로 생성" "$FUMD" '**create** a new `<!-- guild:followups -->` comment on `<ISSUE>`'
hasfx "review: PR 이면 임의 번호의 closing 참조" "$FUMD" "not item 2's regex, which is anchored on"
lacksfx "review: docs/specs/\$1 예시를 쓰지 않는다" "$FUMD" '[설계 유예] <제목> — docs/specs/$1/<file>'
hasfx "qa: 미계획으로 닫힌 Issue 는 거절로 존중" "$FQMD" '`등록 불필요 — #<n> 미계획으로 닫힘`'
hasfx "qa: 무인 실행은 PR 에도 알린다" "$FQMD" '`<!-- guild:followups:pr:$1 -->`'
hasfx "handoff F: 후속 Issue 생성 실패는 스테이지를 멈추지 않는다" "$GLD/commands/atoms/_handoff.md" '**Follow-up Issue creates are not stage state either.**'
hasfx "init: 화면에는 BLOCKER/MAJOR 만" "$FIMD" '**On screen, show only BLOCKER/MAJOR gaps plus the summary count**'
# 후속 Issue 3회차 적대적 리뷰
hasfx "init: inline-secret 에 git rm --cached 를 제안하지 않는다" "$FIMD" 'for `inline-secret` the file is ordinary source, so **never** offer `git rm --cached`'
hasfx "qa: 이전 기록의 declined 는 판정으로" "$FQMD" '**`등록 불필요 — 이전에 거절됨`**'
hasfx "qa: 자기 Issue 는 덮는 Issue 가 아니다" "$FQMD" '**Never count `#$1` itself**'
hasfx "review: 자기 Issue 는 덮는 Issue 가 아니다" "$FUMD" '**Never count `<ISSUE>` itself, or any Issue in this PR'"'"'s `closingIssuesReferences`, as the covering Issue**'
hasfx "qa: PR 알림을 기록과 맞춘다 (두 분기 모두)" "$FQMD" '**Keep the PR notice in step with the record — in every mode and on both branches above.**'
hasfx "review: PR 알림은 (b) 가 비어도 정리" "$FUMD" '**The PR notice is settled separately, and even when (b) was empty**'
hasfx "review: Issue 쪽 \$1 은 <ISSUE>" "$FUMD" '**From here on, every Issue-side use of `$1` in this command means `<ISSUE>`**'
lacksfx "qa: 정의되지 않은 <N> 을 쓰지 않는다" "$FQMD" '/gld review <N>'
# 후속 Issue 4회차 적대적 리뷰
hasfx "init: inline-secret 로컬 조치는 안내만" "$FIMD" '**printed as guidance only, never applied**'
hasfx "review: <ISSUE> 가 없으면 PR 알림을 건드리지 않는다" "$FUMD" 'but never when `<ISSUE>` = none'
hasfx "qa: DUPLICATE 는 원본을 따라간다" "$FQMD" '`DUPLICATE` → follow it to the Issue it duplicates'
hasfx "review: DUPLICATE 는 원본을 따라간다" "$FUMD" '`DUPLICATE` → follow it to the Issue it duplicates'
# 후속 Issue 5회차 적대적 리뷰
lacksfx "qa: Issue 번호 없는 PR 알림 마커를 쓰지 않는다" "$FQMD" '<!-- guild:followups:pr -->'
hasfx "review: 자기 Issue 의 알림만 정리" "$FUMD" 'match exactly `<!-- guild:followups:pr:<ISSUE> -->`'
lacksfx "review: 기록이 없다고 알림을 처리됨으로 바꾸지 않는다" "$FUMD" '(or there is no record)'
# 후속 Issue 6회차 적대적 리뷰 (MINOR 정리)
hasfx "review: 기록을 읽거나 쓴 경우에만 알림 정리" "$FUMD" 'record was actually read or written in this run and now holds no `unfiled` line'
hasfx "review: 구버전 헤딩은 의미로 인식" "$FUMD" 'recognise it by meaning, not by the literal string'

# ── evolve 산출물 위생 (design/guild/10-ledger-hygiene.md) ─────────────────────────────────────
# 원장을 통째로 Read 하던 곳이 하나라도 남으면 383KB 가 다시 매 실행에 실린다. 그래서 각 독자가
# ledger.py 를 거친다는 것과, 이동이 게이트 뒤·커밋 앞이라는 순서를 고정한다.
EVO="$GLD/commands/evolve.md"
hasfx "evolve: Phase 0 은 원장을 ledger.py context 로만 읽는다" "$EVO" 'python3 <<SKILL_DIR>>/commands/atoms/ledger.py context'
lacksfx "evolve: Phase 0 이 원장 전체를 Read 하지 않는다" "$EVO" 'Load the ledger** (skip-list / prior context) — Read `.claude/guild/evolution-log.md`'
hasfx "evolve: <n> 은 next= 값이다" "$EVO" '`<n>` = **the `next=` value that call printed**'
lacksfx "evolve: <n> 을 항목 수로 세지 않는다" "$EVO" 'the count of run entries already in the ledger, plus 1'
hasfx "evolve: 거절 목록 한 줄은 색인일 뿐 — 일치하면 원문을 연다" "$EVO" 'A carried line is only an index'
hasfx "evolve: 원장 항목 추가는 꼬리만 읽는다" "$EVO" 'reading only its tail (`offset` = Phase 0'"'"'s `lines=` value minus 30, at least 1)'
hasfx "evolve: compact 는 게이트 뒤에 돈다" "$EVO" '**after** the gate, so a gate failure never has an archive to restore'
hasfx "evolve: 0건 실행도 compact 한다" "$EVO" 'run the same `ledger.py compact` + `git add` as Phase 6 step 7'
hasfx "evolve: compact 실패는 커밋을 막지 않는다" "$EVO" 'Non-zero exit → it put both files back; commit without it'
hasfx "evolve: ③ 습관도 densify 한다" "$EVO" '**Densify (③ habits and ⑥ knowledge — growth = density):**'
hasfx "evolve: 크기 기준은 harness_size.py 에서 온다" "$EVO" 'python3 <<SKILL_DIR>>/commands/atoms/harness_size.py'
hasfx "evolve: 한 실행은 최대 3줄만 다룬다" "$EVO" 'Take **at most the first 3 lines** this run'
hasfx "evolve: 병합은 조건·예외·근거를 모두 보존" "$EVO" 'keeps **every condition, exception and evidence ref**'
hasfx "evolve: 습관 정리는 나이만으로 하지 않는다" "$EVO" 'never age alone'
hasfx "evolve: degradation 렌즈가 병합 손실을 본다" "$EVO" 'does the new text drop a condition, exception or evidence ref of what it replaces?'
hasfx "evolve: 새 습관은 400자 이내" "$EVO" 'Keep a new or rewritten habit within 400 characters.'
hasfx "evolve: Bash 예외에 새 스크립트가 들어 있다" "$EVO" '`ledger.py`, `harness_size.py`'
hasfx "rollback: 항목은 where 로 찾는다" "$GLD/commands/rollback.md" 'ledger.py where <n>'
hasfx "rollback: evolve 실행은 원장 없이 되돌린다" "$GLD/commands/rollback.md" '**An evolve run is reverted without its ledger**'
hasfx "rollback: 되돌림 표시는 자기 해시를 쓰지 않는다" "$GLD/commands/rollback.md" '[reverted <date> — by the commit that carries this note]'
hasfx "data_sufficiency: 실행 수는 ledger.py status" "$GLD/commands/atoms/_data_sufficiency.md" 'the `runs=` value of `python3 <<SKILL_DIR>>/commands/atoms/ledger.py status`'
lacksfx "data_sufficiency: 헤더를 세지 않는다" "$GLD/commands/atoms/_data_sufficiency.md" 'count the run headers'
hasfx "review: 실행 수는 ledger.py status" "$GLD/commands/review.md" 'commands/atoms/ledger.py status'
hasfx "audit: E 는 ledger.py context" "$GLD/commands/audit.md" 'commands/atoms/ledger.py context'
hasfx "audit: C 는 harness_size.py" "$GLD/commands/audit.md" 'commands/atoms/harness_size.py'
lacksfx "audit: 한 화면 기준이 남지 않았다" "$GLD/commands/audit.md" 'a screenful, not sprawling'
hasfx "monitoring: 실행 수는 ledger.py status" "$GLD/commands/monitoring.md" 'never Read `evolution-log.md`'
hasfx "onboard: 점수표는 overseer 줄만" "$GLD/commands/onboard.md" 'ledger.py tagged overseer'
hasfx "preflight: Item 7 은 overseer 줄만" "$GLD/commands/atoms/_preflight.md" 'ledger.py tagged overseer'
hasfx "preflight: Item 7 은 무인 실행이면 호출하지 않는다" "$GLD/commands/atoms/_preflight.md" '**Attended only — unattended, skip without a call.**'
hasfx "review: 페이딩은 overseer 줄만" "$GLD/commands/review.md" 'ledger.py tagged overseer'
hasfx "retro: 원장 인용은 ledger.py" "$GLD/commands/sprint/retro.md" 'ledger.py status`, or `where <n>` and a ranged Read'
hasfx "evolve: model-tier 행은 태그 한 줄" "$EVO" 'Write the row as one line starting `model-tier:`, status first'
hasfx "evolve: model-tier 항목은 태그 한 줄" "$EVO" 'write the item as one line starting `model-tier-item: <role> raise`'
hasfx "evolve: overseer 줄은 태그" "$EVO" 'each starting `overseer:`'
hasfx "evolve: 게이트 실패 롤백은 HEAD 에서" "$EVO" '`git checkout HEAD -- <path>` when it existed before this run, `git rm -f <path>` when it is new'
hasfx "rollback: PR 경로도 evolve 실행을 알아본다" "$GLD/commands/rollback.md" 'leaving out any that end `— 0 changes applied` (nothing to undo)'
hasfx "rollback: evolve 커밋 제목은 앞부분 고정으로만 인식" "$GLD/commands/rollback.md" "If the subject **starts** \`chore(guild): evolve #<n> —\`"
hasfx "rollback: PR 은 evolve 커밋만, 자기 oid 로 되돌린다" "$GLD/commands/rollback.md" 'Revert the run'"'"'s commit by its own `oid` from `commits`'
hasfx "rollback: PR 커밋을 먼저 fetch" "$GLD/commands/rollback.md" '`git fetch origin pull/<p>/head <baseRefName>`'
hasfx "rollback: 실행이 여럿이면 사람에게 묻는다" "$GLD/commands/rollback.md" 'several → ask the human which, and undo each chosen run newest first with its own note'
hasfx "rollback: evolve 실행이 없는 merge PR 은 -m 1" "$GLD/commands/rollback.md" 'a merge commit (`git rev-list --parents -n 1 <mergeCommit.oid>` prints three hashes) is reverted with `-m 1`'
hasfx "rollback: 커밋 제목의 변경 수는 <k>" "$GLD/commands/rollback.md" 'chore(guild): evolve #<n> — <k> changes applied'
lacksfx "rollback: 여러 커밋 PR 에서 SHA 를 되묻지 않는다" "$GLD/commands/rollback.md" 'ask the human for the SHA of the commit that carries the run'
hasfx "rollback: merge·squash SHA 는 PR 경로로" "$GLD/commands/rollback.md" 'or a subject ending `(#<p>)` — may carry an evolve run inside it'
hasfx "evolve: 커밋 제목의 변경 수는 <k>" "$EVO" 'chore(guild): evolve #<n> — <k> changes applied'
hasfx "rollback: PR 번호와 실행 번호를 다른 자리표시자로" "$GLD/commands/rollback.md" '(any number — not `<p>`)'
hasfx "rollback: evolve 없는 rebase PR 은 커밋별로" "$GLD/commands/rollback.md" 'revert the PR'"'"'s commits by their `oid`s from `commits`, newest first, which is right for both'
hasfx "rollback: 충돌 주석을 커밋 메시지에서 뺀다" "$GLD/commands/rollback.md" '`git commit --no-edit --cleanup=strip`'
hasfx "rollback: 0건 실행만 있는 PR 은 멈춘다" "$GLD/commands/rollback.md" 'if the PR'"'"'s commits were all `— 0 changes applied` runs, there is nothing to undo: say so and stop'
hasfx "rollback: baseRefName 을 읽는다" "$GLD/commands/rollback.md" 'headRefName,baseRefName,mergeCommit'
hasfx "rollback: 머지 방식과 무관하게 동작" "$GLD/commands/rollback.md" 'that works however the PR was merged (merge, squash or rebase'
hasfx "evolve: 꼬리 읽기 offset 은 최소 1" "$EVO" 'minus 30, at least 1)'
hasfx "evolve: 0건 실행도 꼬리만 읽어 덧붙인다" "$EVO" 'write the entry here (appended after a tail Read, as in Phase 6 step 7)'
hasfx "audit: 배너는 status 한 줄" "$GLD/commands/audit.md" '`runs=` from `python3 <<SKILL_DIR>>/commands/atoms/ledger.py status`, one line'
hasfx "audit: E 가 범위일 때만 context" "$GLD/commands/audit.md" 'made only when this dimension is in scope'
hasfx "evolve: 실행 제목 형식이 고정돼 있다" "$EVO" 'exactly `## Run — evolve #<n> (<YYYY-MM-DD>)`'
hasfx "evolve: 항목을 쓴 뒤 where 로 읽히는지 확인" "$EVO" 'Then confirm the entry is readable as run `<n>`'
hasfx "evolve: warning 줄은 사람 말로 알린다" "$EVO" 'A `warning:` line → tell the human in one plain sentence'
hasfx "evolve: 게이트 거부는 Phase 7 커밋도 없다" "$EVO" '**do not commit — and write no Phase 7 entry either**'
hasfx "rollback: 3단계 revert 충돌은 예상된 것" "$GLD/commands/rollback.md" '(a non-zero exit from a conflict is expected here — go on)'
hasfx "rollback: 같은 번호 두 항목은 applied-onto 로 고른다" "$GLD/commands/rollback.md" 'the entry is the one whose `applied-onto:` equals the evolve commit'"'"'s parent'
hasfx "monitoring: 추세는 runs 2 이상일 때만" "$GLD/commands/monitoring.md" 'made only when `status` printed `runs=` of 2 or more'
hasfx "evolve: where 는 exit 0 만 통과" "$EVO" 'Only exit 0 passes. Exit 2 (found, but under a heading that is not a run heading)'
hasfx "evolve: 거절 항목 첫 줄에 주제" "$EVO" 'its first line `- [rejected] <theme> — <reason>`'
hasfx "evolve: 적용 항목 첫 줄에 주제" "$EVO" 'its first line `- [applied] <theme> — <target>`'
lacksfx "evolve: 커밋 거부 시 원장 항목을 지우는 분기가 없다" "$EVO" 'take the move back out'
hasfx "evolve: compact 가 못 되돌린 파일은 stderr 지시를 따른다" "$EVO" 'If its stderr line names a file it could not put back'
hasfx "rollback: 0건 실행은 1단계에서 멈춘다" "$GLD/commands/rollback.md" 'there is nothing to undo, so say so and stop here, before step 2'
hasfx "rollback: 훅이 거부하면 이유를 알리고 중단" "$GLD/commands/rollback.md" 'report the hook'"'"'s reason and `git revert --abort`'
hasfx "rollback: PR 커밋의 부모는 rev-parse" "$GLD/commands/rollback.md" '`git rev-parse <oid>^`, since `commits` lists no parents'
hasfx "rollback: where exit 2 도 범위를 쓴다" "$GLD/commands/rollback.md" '(exit 2: found under a heading not in the run shape — use that range all the same)'
hasfx "rollback: 되돌림 표시는 줄 맨 앞" "$GLD/commands/rollback.md" 'marking it with a line of its own, `[reverted <date>'
hasfx "bash_rules: 새 스크립트가 예외 목록에 있다" "$GLD/commands/atoms/_bash_rules.md" '`ledger.py` (evolve ledger read/compact'
lacksfx "preflight: Item 8 이 원장을 열지 않는다" "$GLD/commands/atoms/_preflight.md" 'newer than the last evolve run recorded in `evolution-log.md`'
hasfx "ask: 보관 파일도 범위만 읽는다" "$GLD/commands/ask.md" 'evolution-log.archive.md'
hasfx "update: 보관 파일도 보존한다" "$GLD/commands/update.md" '`.claude/guild/evolution-log.md` + `.claude/guild/evolution-log.archive.md` (⑤)'
hasfx "knowledge: index 기준은 harness_size.py" "$GLD/commands/atoms/_knowledge.md" 'If it outgrows its size bar (`harness_size.py` prints an `index:` line'
# ── 0.95.1: 스캔/감지 입력은 인자로, 플러그인 사본으로 ────────────────────────────
# Bash 도구는 stdin 을 /dev/null 로 붙인다. "stdin = 그 파일" 로 문서화된 호출은 늘 빈 입력을 읽어
# clean / none 을 냈다(contribute 의 INV5 스캔 무조건 통과, init 의 관리형 훅 덮어쓰기). 그리고 저장소
# 사본은 update 가 갱신을 건너뛰면 옛 스크립트라 새 인자를 무시하므로 플러그인 사본을 부른다.
G95="$(grep -rnE 'gate_precommit\.py --(scan-paths|scan-text|detect-hook-manager|firing-log)' "$GLD/commands" | grep -vE '<<SKILL_DIR>>/gates/gate_precommit\.py|<GATE_SCRIPT>' || true)"
[ -z "$G95" ] && ok "스캔/감지/로그 호출은 모두 플러그인 사본(<<SKILL_DIR>> / <GATE_SCRIPT>)" \
  || bad "스캔/감지 호출이 저장소 사본을 부름" "none" "$(printf '%s' "$G95" | head -3 | tr '\n' '|')"
G95b="$(grep -rnE '[(,] ?stdin = ' "$GLD/commands" || true)"
[ -z "$G95b" ] && ok "\"stdin = …\" 로 입력을 넘기라는 지시가 없음" || bad "stdin 지시 잔존" "none" "$(printf '%s' "$G95b" | head -3 | tr '\n' '|')"
G95c="$(grep -rn -- "--paginate --jq '\[" "$GLD/commands" "$GLD/templates" || true)"
[ -z "$G95c" ] && ok "--paginate --jq 가 배열형 '[…]' 이 아님 (페이지마다 배열이 따로 나온다)" \
  || bad "--paginate --jq 배열형" "none" "$(printf '%s' "$G95c" | head -3 | tr '\n' '|')"
hasfx "audit_readiness: GATE_SCRIPT 는 호출자가 넘김 (대체 경로 없음)" "$GLD/commands/atoms/audit_readiness.md" 'There is no fallback'
hasfx "audit_readiness: 0/1 외 종료 코드는 판정 불가" "$GLD/commands/atoms/audit_readiness.md" 'anything else (2 = could not scan, 64 = no input) = NOT judged'
hasfx "init: 서브에이전트 프롬프트에 GATE_SCRIPT" "$GLD/commands/init.md" '`GATE_SCRIPT` = `<<SKILL_DIR>>/gates/gate_precommit.py`'
hasfx "audit: GATE_SCRIPT 전달" "$GLD/commands/audit.md" 'execute it with `GATE_SCRIPT`'
hasfx "init: absent 분기" "$GLD/commands/init.md" '**`absent`** → no hook yet'
hasfx "update: absent 분기" "$GLD/commands/update.md" '**`absent` / `guild` / `none`**'
hasfx "contribute: 판정 불가면 반출 중단" "$GLD/commands/contribute.md" 'means NOT scanned, not clean'
hasfx "evolve: firing 로그는 --firing-log 로만" "$GLD/commands/evolve.md" '**Never read `gate-firings.jsonl` directly**'
hasfx "evolve: NOLOG 는 never fires 가 아님" "$GLD/commands/evolve.md" 'never** read it as "the rule never fires"'
hasfx "audit: rule health 도 --firing-log" "$GLD/commands/audit.md" '--firing-log --out'
hasfx "audit: NOLOG 면 stale 판정 금지" "$GLD/commands/audit.md" 'never "stale"'
hasfx "audit: --firing-log 출력 행 수 대조" "$GLD/commands/audit.md" 'confirm its last line number equals `n`'
hasfx "evolve: --firing-log 출력 행 수 대조" "$GLD/commands/evolve.md" 'confirm its last line number equals `n`'

# ── 0.96.0: test/qa → execute 루프백 ─────────────────────────────────────────
# 예전엔 "≤2회 루프백" 문장만 있고 카운터·라벨·기록이 없었다: 사람이 "execute 로" 라고 답해도 dev 는
# 같은 단계(test)를 다시 돌렸고, 무인 실행이 끊기면 라벨이 test 에 남아 의도·횟수가 사라졌으며,
# 정체 가드는 컴팩션 뒤 비교할 "직전 이유" 가 없었다.
HOMD="$GLD/commands/atoms/_handoff.md"
for f in "$HOMD" "$GLD/commands/dev.md" "$GLD/commands/test.md" "$GLD/commands/qa.md"; do
  hasfx "OK LOOPBACK 토큰 — $(basename "$f")" "$f" 'OK LOOPBACK: execute'
done
hasfx "Section D 에 OK LOOPBACK 행" "$HOMD" '| `OK LOOPBACK: execute` |'
hasfx "Section A: execute 로의 역전이는 정확히 둘" "$HOMD" '**Backward transitions into `guild:execute` — exactly two.**'
hasfx "Section B: 네 가지 예외" "$HOMD" '**four documented exceptions**'
hasfx "Section B: loopback 은 누적형 (네 번째 예외)" "$HOMD" 'and, fourth, `<!-- guild:loopback -->` is **cumulative**'
hasfx "Section B: 마커 표에 guild:loopback 행" "$HOMD" '| `<!-- guild:loopback -->` … `<!-- /guild:loopback -->` |'
hasfx "Section B: 활성 블록 단일 정의" "$HOMD" '**Loop-back record — active blocks (the single definition;'
hasfx "Section B: 접두 문자열로 세지 않는다" "$HOMD" 'Never count by the prefix `### loopback`'
hasfx "Section B: 루프백 절차 단일 정의" "$HOMD" '**Loop-back procedure — the steps test, qa and the leader all run'
hasfx "Section B: 중단된 루프백 재진입" "$HOMD" '**Interrupted loop-back** (test/qa Step 0'
hasfx "Section K: loopback 토큰 등재" "$HOMD" 'the loop-back record (`<!-- guild:loopback -->`, Section B): the headings'
hasfx "Section K: 다섯 가지 멤버" "$HOMD" 'That class currently has five members:'
hasfx "Section H: 상한은 여기서만 정의" "$HOMD" '**this row defines the cap; every other file says `<cap>`**'
# 상한 리터럴은 Section H 한 곳만 — 표시 문구는 <cap> 자리표시자
for f in test.md qa.md dev.md batch.md status.md resume.md; do
  if grep -qE 'loop-backs so far: [^<]|≤ ?2 attempts|bounded loop-back to execute \(≤2' "$GLD/commands/$f"; then
    bad "상한 리터럴 없음 — $f" "<cap> 만" "리터럴 2"
  else ok "상한 리터럴 없음 — $f"; fi
done
# 루프백 조회는 스트림형 (A-1 의 다중 페이지 결함을 재현하지 않음)
hasfx "loopback 조회는 --paginate 스트림형" "$HOMD" "contains(\"<!-- guild:loopback -->\")) | {id, body}'"
hasfx "dev: 사람의 루프백 답은 같은 래퍼가 처리" "$GLD/commands/dev.md" 'the wrapper itself records the loop-back and returns `OK LOOPBACK: execute`'
hasfx "dev: 리더 루프백도 같은 절차 (from: leader)" "$GLD/commands/dev.md" 'the loop-back procedure with `from: leader`'
hasfx "dev 2b: 자식의 루프백 질문은 인라인 예외" "$GLD/commands/dev.md" '**The one inline exception — a test/qa "loop back to execute?" `NEEDS_HUMAN` (attended)**'
hasfx "dev 2b: 자식의 OK LOOPBACK 처리" "$GLD/commands/dev.md" '`OK LOOPBACK: execute` → handle it exactly as Phase 2 does, for `C`'
hasfx "qa: Step 2 조기 NEEDS_HUMAN 반환 제거" "$GLD/commands/qa.md" "never an early \`NEEDS_HUMAN\` from here"
hasfx "test: 루프백 진입점" "$GLD/commands/test.md" '**Loop-back entries (right after the label read, before any other work):**'
hasfx "qa: 루프백 진입점" "$GLD/commands/qa.md" '**Loop-back entries (right after the label read, before any other work):**'
hasfx "execute Step 0: 미처리 루프백 읽기" "$GLD/commands/atoms/_execute_spine.md" '**Pending loop-back** (its own `gh api` call, before the branch work)'
hasfx "execute Step 0(a): 루프백 branch 우선" "$GLD/commands/atoms/_execute_spine.md" 'If `<loopback>` is set and its `branch:` is among them'
hasfx "execute Step 1: resume 문구 교체" "$GLD/commands/atoms/_execute_spine.md" 'replace everything after the summary slot with'
hasfx "execute Step 6: consumed 재조회 판정" "$GLD/commands/atoms/_execute_spine.md" "re-read the \`<!-- guild:loopback -->\` record now — not Step 0's reading from memory"
hasfx "execute Step 6: consumed 실패 시 전진 금지" "$GLD/commands/atoms/_execute_spine.md" 'still missing → do **not** advance'
hasfx "_signals: 루프백 재진입은 owed 0" "$GLD/commands/atoms/_signals.md" '**test / qa — owed = 0** on the two loop-back re-entries'
hasfx "_bash_rules: loopback 도 누적형 id·body 동시 조회" "$GLD/commands/atoms/_bash_rules.md" '`<!-- guild:loopback -->` has the same cumulative shape'
hasfx "rollback: loopback-reset" "$GLD/commands/rollback.md" '### loopback-reset'
hasfx "status: 활성 루프백 수 표시" "$GLD/commands/status.md" 'Loop-backs: <active>/<cap>'
hasfx "test: 무인 분기는 루프백 절차를 호출" "$GLD/commands/test.md" 'run the **loop-back procedure** (`_handoff.md` Section B) with `from: test`'
hasfx "qa: 무인 분기는 루프백 절차를 호출" "$GLD/commands/qa.md" 'run the **loop-back procedure** (`_handoff.md` Section B) with `from: qa`'
# 사람의 답이 가드에 다시 뒤집히지 않는다 (사람이 "loop back" 해도 정체 판정이 PAUSE 로 막던 회귀)
hasfx "답 재실행은 steps 1, 4–7 (가드 2–3 은 질문에 이미 반영)" "$HOMD" 'and runs steps 1, 4–7 — **not** 2–3'
lacksfx "답 재실행이 steps 1–7 을 돌지 않음" "$HOMD" 'and runs steps 1–7.'
hasfx "질문에 상한/정체 표시" "$HOMD" ' — cap reached; yes overrides it'
hasfx "질문에 정체 접미사" "$HOMD" ' — same failure as loop-back <n>; yes tries again anyway'
hasfx "test: 질문이 접미사를 참조" "$GLD/commands/test.md" 'with the cap / stagnation suffix'
hasfx "qa: 질문이 접미사를 참조" "$GLD/commands/qa.md" 'with the cap / stagnation suffix'
hasfx "Asking first 는 리더에게도" "$HOMD" '**Asking first (attended — test, qa, and the leader alike)**'
hasfx "리더 변형: output 댓글·NEEDS_HUMAN 없음" "$HOMD" 'and **never returns `NEEDS_HUMAN`**'
hasfx "리더 변형: '아니오' 처리" "$HOMD" 'On "no" it does not loop back: it continues the'
hasfx "step 6: 현재 stage 라벨을 제거 (리더 루프백)" "$HOMD" 'the stage label the Issue carries now — guild:test or guild:qa, as just read'
hasfx "정체 캡처 --stage (리더 루프백)" "$HOMD" 'with `--stage` = the stage that'
hasfx "needs-human 제거 지점은 decided: human 블록" "$HOMD" 'one whose block carries `decided: human`'

hasfx "dev: attended 리더 루프백은 사람에게 묻는다" "$GLD/commands/dev.md" 'its *Asking first*: you put the readings to the human'
hasfx "override 는 기록에서 재계산" "$HOMD" 'never from memory of what the question said'
hasfx "_signals: 질문만 한 실행은 stagnation 을 빚지지 않음" "$GLD/commands/atoms/_signals.md" 'owes its `verify-gap` /'
hasfx "_stagnation: 루프백 질문은 Asking first 를 따름" "$GLD/commands/atoms/_stagnation.md" '**Not for a test / qa / leader → execute loop-back**'
_cap_n="$(grep -c '`<cap>` = 2' "$HOMD")"
[ "$_cap_n" = 1 ] && ok "_handoff 안에서도 상한 숫자는 Section H 한 곳" || bad "_handoff 상한 정의 개수" "1" "$_cap_n"
lacksfx "Section A 의 무조건 needs-human 제거 문구 제거" "$HOMD" 'removing `guild:needs-human` in the same call when present.'
lacksfx "루프백 프롬프트에 '중단된 실행' 전제 잔존 금지" "$GLD/commands/atoms/_execute_spine.md" 'with "keep committed work unrelated to the failure below"\'
hasfx "사람 결정 루프백은 decided: human 으로 기록 (중단 재진입도 needs-human 제거)" "$HOMD" 'step 6 reads `decided: human` from'
hasfx "직접 호출 test 는 리더가 묻고 재실행" "$GLD/commands/test.md" 'is asked by the leader right here (`AskUserQuestion`)'
hasfx "직접 호출 qa 는 리더가 묻고 재실행" "$GLD/commands/qa.md" 'the leader asks a `NEEDS_HUMAN` loop-back question itself'
hasfx "execute: 루프백 시 partial-work 요약 슬롯 유지" "$GLD/commands/atoms/_execute_spine.md" 'keep the partial-work summary slot itself'
lacksfx "execute: 'the documented exception' 단수 표현 제거" "$GLD/commands/atoms/_execute_spine.md" 'This marker is the documented exception'
lacksfx "_stagnation: 상한 리터럴 (≤2) 제거" "$GLD/commands/atoms/_stagnation.md" 'numeric cap (≤2)'
# 접두 문자열로 세는 지시 금지 — `### loopback` 은 reset 블록에도 맞는다
_pfx="$(grep -rnE '(count|세)[^.]{0,40}`### loopback`' "$GLD/commands" | grep -vi 'never count by' || true)"
[ -z "$_pfx" ] && ok "어떤 파일도 '### loopback' 접두로 세지 않음" || bad "접두로 세는 지시" "none" "$(printf '%s' "$_pfx" | head -2 | tr '\n' '|')"
_lb_files="$(grep -rl 'guild:loopback' "$GLD/commands" | sed 's#.*/##' | sort | tr '\n' ' ')"
for want in _handoff.md test.md qa.md _execute_spine.md _stagnation.md rollback.md status.md resume.md review.md _bash_rules.md; do
  case " $_lb_files " in *" $want "*) ok "guild:loopback 철자 — $want" ;; *) bad "guild:loopback 철자 — $want" "present" "missing" ;; esac
done

# ── 0.97.0: sprint plan — 목표 하나 + 용량까지 채움 + 결정 질문 ──────────────────────────
# one-man-company: capacity 10 인데 계획은 9→7→4→3→3→3→2→1→3→3, 전부 머지·캐리오버 0. 착수 가능한 목표 외
# 후보가 빠졌고(#545: #164 #210 #246), Phase 3 이 history 를 처리량으로 읽어 3 안팎으로 줄였으며, unclear 후보는
# 결정할 기회 없이 제외됐다.
SPP="$GLD/commands/sprint/plan.md"
hasfx "plan: 인자 순서 무관 --create/--no-ask" "$SPP" '`$1`, `$2` = flags, in either order: `--create`'
hasfx "plan: PO 가 목표 외 순위를 낸다" "$SPP" '(c) **other-ranked**: every other candidate worth starting now'
hasfx "plan: PO 목표는 제목 — 나열 금지" "$SPP" 'it becomes the tracker'"'"'s title, so it names the aim, never a list of the issues'
hasfx "plan: PO 가 unclear 차원마다 결정 초안" "$SPP" 'draft the decision that would settle it'
lacksfx "plan: unclear 제외 권고 문장 교체됨" "$SPP" '**Recommend excluding any candidate with an `unclear` dimension**'
hasfx "plan: po.md 절 헤더 고정" "$SPP" '`## goal` · `## goal-picks` · `## other-ranked` · `## readiness`'
hasfx "plan: history 로 C 를 줄이지 않는다" "$SPP" '**Never shrink `C` from history.**'
hasfx "plan: 채우기 순서 1 goal-picks" "$SPP" '1. **goal-picks** — the feature gates as before'
hasfx "plan: 채우기 순서 3 other-ranked" "$SPP" '3. **other-ranked** — the same gates.'
hasfx "plan: 1b 구체화 필요는 자동으로 담지 않음(analyze 이하만)" "$SPP" '구체화 필요 **at stage `none` or `guild:analyze`** is never filled automatically, whatever the'
hasfx "plan: needs-human 후보는 자동으로 담지 않음" "$SPP" 'does **not** carry
   `guild:needs-human`'
hasfx "plan: 질문은 attended·--no-ask 아님" "$SPP" '2. **Decision questions for goal-related candidates** — attended and not `--no-ask` only'
hasfx "plan: 질문 대상 stage none/analyze" "$SPP" 'whose stage is
  `none` or `guild:analyze`'
hasfx "plan: 건너뛰기는 위치로 판정" "$SPP" 'judged by being the last option, never by its text'
hasfx "plan: 질문 시점엔 아무것도 쓰지 않음" "$SPP" '**Nothing is written now.**'
hasfx "plan: 추가 경로엔 새 규칙 미적용" "$SPP" '**Adding to an open sprint** (Phase 0 step 4'"'"'s "add"): none of the above applies'
hasfx "plan: plan-decisions 댓글은 step 2 직후" "$SPP" 'post them as one
   tracker comment before any member body is touched'
hasfx "plan: 결정 블록은 Sprint 줄과 같은 rewrite" "$SPP" 'its decision block in the same rewrite'
hasfx "plan: 기존 결정 줄은 건드리지 않음" "$SPP" 'leave existing lines
   alone — a different value there is a human'"'"'s edit'
hasfx "plan: 구분 열은 표의 마지막" "$SPP" '| # | 이슈 | base 의존 | 원래 의존 | 비고 | 구분 |'
hasfx "plan: capacity 기계 줄" "$SPP" '- capacity: <C 정수 | n/a>'
hasfx "plan: shortfall 기계 줄" "$SPP" '- shortfall: <none | supply | depth | human-cut | n/a>'
hasfx "plan: 선행 미포함 경고 필수" "$SPP" '**`⚠ 선행 미포함:` (required)**'
hasfx "plan: 크기 N 만 human-cut" "$SPP" 'Record `shortfall: human-cut` **only** in this case'
hasfx "plan: C 출처 경고" "$SPP" '⚠ 용량 <C> 는 아직 실측된 적 없는 크기입니다(실측 최대 <M>)'
hasfx "plan: 재실행이 빠진 결정 줄 복구" "$SPP" 'the decision lines the tracker'"'"'s `<!-- guild:sprint:plan-decisions -->` comment'
hasfx "plan: order 는 kind 로 동순위" "$SPP" '**Every member in the `base_deps` file carries its `kind`**'
hasfx "run: order.json 에 kind" "$GLD/commands/sprint/run.md" '`{"members":[{"number":<n>,"base_deps":[…],"kind":"<goal|other|slot>"}, …]}`'
hasfx "run: ad-hoc 기계 값" "$GLD/commands/sprint/run.md" '`- capacity: n/a`, `- shortfall: n/a`, `- adhoc: true`'
hasfx "retro: 권고 우선순위 — adhoc 권고 없음" "$GLD/commands/sprint/retro.md" '| ① | `adhoc: true` | **권고 없음**'
hasfx "retro: human-cut 이면 capacity = planned" "$GLD/commands/sprint/retro.md" '| ③ | `shortfall: human-cut` | **`capacity = planned`**'
hasfx "retro: supply/depth 는 +1 차단" "$GLD/commands/sprint/retro.md" '**유지 — +1 은 하지 않는다.**'
hasfx "retro: 목표 달성 지표" "$GLD/commands/sprint/retro.md" '| 목표 달성 |'
hasfx "retro: history capacity·shortfall" "$GLD/commands/sprint/retro.md" '"capacity": 7, "shortfall": "none",'
hasfx "daily: 목표/목표 외 줄" "$GLD/commands/sprint/daily.md" '`목표: 머지 <g_merged>/<g> · 목표 외: 머지 <o_merged>/<o>`'
hasfx "analyze: 계획 중 결정 블록을 근거로" "$GLD/commands/analyze.md" '**Decisions already made in sprint planning.**'
hasfx "_handoff: plan-decision 마커" "$HOMD" '| `<!-- guild:plan-decision -->` … `<!-- /guild:plan-decision -->` |'
hasfx "_handoff: K 에 구분·기계 줄" "$HOMD" "the sprint plan's fill record: the member table's \`구분\` values"
hasfx "plan: 이미 결정된 차원은 다시 묻지 않음" "$SPP" '**Already decided**: a candidate whose body'
hasfx "plan: CANDIDATES 에 decided 줄 — 그 질문만 해결" "$SPP" 'rate the rest of that dimension as usual'
hasfx "plan: analyze 지난 후보는 readiness 게이트 없음" "$SPP" '**A candidate already past analyze**'
hasfx "plan: history 없으면 실측 최대·경고 생략" "$SPP" 'No usable history entry'
hasfx "plan: 추가 경로는 새 이슈 없어도 Phase 6 복구" "$SPP" 'Phase 6 runs even when the human approves no new issue'
hasfx "plan: 답한 후보는 1b 게이트 통과" "$SPP" 'passes the 1b gate as well'
hasfx "plan: 첫 스프린트 C=5 로 같은 채우기" "$SPP" 'use `C` = 5 for the fill below'
hasfx "plan: PO 목표 외에 결정 하나로 착수 가능한 unclear 포함" "$SPP" 'include one that is `unclear` when a single decision would make it startable'
hasfx "plan: Phase 0 에서 미반영 결정 보고" "$SPP" '결정 N건이 본문에 반영되지 못했습니다: #a … — "추가" 를'
hasfx "run: 해시 불일치 안내에 plan-decisions 조건" "$GLD/commands/sprint/run.md" 'that stops on the very question the human already answered'
hasfx "retro: 슬롯은 목표 쪽에 센다(daily 와 같은 기준)" "$GLD/commands/sprint/retro.md" '슬롯은 목표 쪽에 센다 — `daily` 와 같은 기준'
lacksfx "retro: plan 이 history 추세를 읽는다는 옛 문장 제거" "$GLD/commands/sprint/retro.md" '`plan` reads the trend'
hasfx "_sprint_dag: 표의 구분 열 설명" "$GLD/commands/atoms/_sprint_dag.md" 'The member table'"'"'s **last** column is **`구분`**'
lacksfx "plan: 용량 판단 옛 참조 제거" "$SPP" 'say so in **용량 판단**'
hasfx "sprint.md: 용량을 이력으로 줄이지 않음" "$GLD/commands/sprint.md" 'never
shrinks that number from history'

# ── 0.97.1: sprint plan dry-run 결함 — 에픽 후보·본문 전달·목록 밖 사유·조건부 크기·선행 대기·1b 막힘 ──
# one-man-company dry-run(2026-10-18): 용량 10 중 2개. 에픽 7개(자식 36건)에 닿을 길이 없었고, 후보 한 줄
# JSON(156,923 B)을 Read 가 앞부분만 보여 PO·tech-lead 가 본문을 못 봤으며, 선행 Issue 미완이 human-work 로 섞였다.
# 2-2 Phase 1 스트림 형식 — 첫 줄이 개수
hasfx "plan: Phase 1 후보는 스트림 형식(첫 줄 개수)" "$SPP" "--jq 'length, (.[] | {number, title, labels: [.labels[].name], body})'"
lacksfx "plan: 한 줄 {total, candidates} 형식 제거" "$SPP" '{total: length, candidates:'
hasfx "plan: count 는 첫 줄" "$SPP" '(`count` in Phase 1b is that line)'
hasfx "plan: 1b 재조회도 같은 스트림 형식" "$SPP" 're-read with `--limit 500` (the same command, same stream form)'
hasfx "plan: 파일로 빠지면 offset/limit 로 끝까지" "$SPP" 'read it to the end with Read'"'"'s `offset`/`limit`'
hasfx "plan: 측정 문장 갱신(시점 명시)" "$SPP" 'of 60 open Issues, 36–38 (depending on the moment) carried `guild:child`'
lacksfx "plan: 낡은 측정(0 of 51) 문장 제거" "$SPP" 'saves nothing worth having either'
hasfx "plan: CANDIDATES 끝에 리더가 쓴 명령" "$SPP" 'BODIES: <the Phase 1 command **the leader actually ran**'
hasfx "plan: PO 는 본문으로 판정" "$SPP" '**Judge from the bodies, not the one-line scope**'
hasfx "plan: TL 도 BODIES 명령을 직접 실행" "$SPP" 'Judge from the bodies: run the BODIES command yourself'
hasfx "plan: CANDIDATES 에픽 자식 대응(바닥 선행 미완 포함)" "$SPP" '`children: #c1(<stage>) #c2(<stage>) … (remaining <k> · blocked <#c…|—> · closed-not-done <#c…|—> · 바닥 선행 미완 <#d…|—>)`'
# 2-1 에픽 후보
lacksfx "plan: 에픽을 사람에게 돌려줄 수 있다는 옛 문장 제거" "$SPP" 'and may hand it back to the human'
hasfx "plan: 에픽은 run 이 끝까지 진행 — 후보 하나" "$SPP" 'it is not handed to the human), so the epic is one candidate like any other'
hasfx "plan: 자식 조회 호출(state all, 500, 스트림)" "$SPP" "gh issue list --label guild:child --state all --limit 500 --json number,body,labels,state --jq 'length, ("
hasfx "plan: 자식 parent 캡처는 tonumber" "$SPP" 'match("Parent Issue: #([0-9]+)").captures[0].string | tonumber'
hasfx "plan: depends_text 는 첫 문장" "$SPP" 'match("Depends on:?[^\n]*"; "g").string | split(". ")[0]'
hasfx "plan: 자식 조회 절단이면 에픽 자동 미포함" "$SPP" '**Count == 500 → the epics cannot be judged**'
hasfx "plan: remaining 은 done 아닌 자식(state 무관)" "$SPP" '**without `guild:done`**, whatever their'
hasfx "plan: k=0 은 통합 점검 대기" "$SPP" '`통합 점검 대기 — /gld dev #e`'
hasfx "plan: 확장 의존 바닥 — 자기·부모·형제 기계 제거" "$SPP" "**minus each line's own Issue, its parent (the epic) and its siblings"
hasfx "plan: Depends on 읽기 규칙은 모든 Depends on 에" "$SPP" '**`Depends on` reading rule** applies to every `Depends on` this file reads'
hasfx "plan: Depends on: 없음/none 은 의존 없음" "$SPP" 'or `Depends on: none` (any case) is **no dependency at all**'
hasfx "plan: 의존 무시 표시" "$SPP" '`의존 무시: #e ← #d (본문: «<그 문장>»)`'
hasfx "plan: 의존 유지 편집" "$SPP" '- **`의존 유지 #d`** → put `#d` back'
hasfx "plan: 안내 줄에 의존 유지·목표 편집·스택 없음" "$SPP" '(드롭 / 추가 / 크기 N / 의존 유지 #d / 목표 <문장> / 재범위 / 재정렬 [/ 스택 없음] 요청 가능)'
lacksfx "plan: 스택 없음 없는 안내 줄 제거" "$SPP" '(드롭 / 추가 / 크기 N / 의존 유지 #d / 목표 <문장> / 재범위 / 재정렬 요청 가능)'
lacksfx "plan: 목표 편집 없는 안내 줄 제거" "$SPP" '(드롭 / 추가 / 크기 N / 의존 유지 #d / 재범위 / 재정렬 요청 가능)'
lacksfx "plan: 옛 안내 줄 제거" "$SPP" '(드롭 / 추가 / 크기 N / 재범위 / 재정렬 요청 가능)'
hasfx "plan: 자식을 가리키는 의존 매핑" "$SPP" 'target child `c` closed or `guild:done` → judged as `c` itself'
hasfx "plan: 에픽 파일 = 남은 자식 파일 합집합" "$SPP" '**An epic'"'"'s files** = the union of the files its remaining children will touch'
hasfx "plan: PO 에픽을 후보 하나로 순위" "$SPP" 'rank the epic as one candidate, exactly like the others'
hasfx "plan: PO 에픽에 결정 질문 금지" "$SPP" 'Do not draft decision questions for an epic'
hasfx "plan: PO 에픽 note 열 decide-in" "$SPP" '(`decide-in: #<c>`)'
hasfx "plan: 1b 에픽은 남은 자식 본문 기준" "$SPP" 'An **epic** (`guild:children`) is judged by its **remaining children'"'"'s bodies**'
hasfx "plan: 에픽은 past-analyze 면제 아님" "$SPP" '⚠ **Not an epic**: `guild:children` has no stage ordinal'
hasfx "plan: TL 에픽 크기 epic ×k + 자식마다" "$SPP" '`epic ×<k>` (k = its remaining children) **and a ✅/⚠ for each child to be sized**'
hasfx "plan: ⚠ 자식 있는 에픽은 strong default 제외" "$SPP" '`제외: #e (에픽 · 자식 #c 분할 예상)`'
hasfx "plan: 에픽 크기 규칙" "$SPP" '**An epic'"'"'s size is `epic ×<k>`, judged per child to be sized**'
hasfx "plan: 채우기 — 에픽은 남은 자식 모두 ✅" "$SPP" '`epic ×<k>` with every child to be sized ✅ (Phase 1; `depends:` and mixed verdicts are not ✅ — Phase 2)'
lacksfx "plan: 옛 채우기 조건(size ✅ 또는 epic ×k) 제거" "$SPP" 'size ✅ or `epic ×<k>`'
hasfx "plan: TL 보정은 추가만" "$SPP" 'add only, never remove one a body states'
hasfx "plan: TL 의존성 절 글머리 줄 추가" "$SPP" 'in a `## 의존성` section (`- #161 … (선행 필수)`), is a dependency too'
hasfx "plan: blocked_children 는 자동 미포함" "$SPP" '**`blocked_children` present → not filled automatically**'
hasfx "plan: 자식 needs-human 대기 사유" "$SPP" '`사람 작업 필요: #e (자식 #c needs-human 대기 — /gld resume c)`'
hasfx "plan: 에픽 규칙 (i) 확장 의존 모두 닫힘/done" "$SPP" '**(i) Every extended-dependency target is closed or `guild:done`.**'
hasfx "plan: 매핑된 선행 대기 표시(대상 쪽)" "$SPP" '`선행 대기(미포함): #e ← #d(자식 #c…)`'
hasfx "plan: 매핑된 선행 대기 표시(직접+자식)" "$SPP" '`선행 대기(미포함): #e ← #d(+자식 #c…)`'
hasfx "plan: 매핑된 선행 미포함 표시(대상 쪽)" "$SPP" '`⚠ 선행 미포함: #q ← #d(자식 #c…)`'
lacksfx "plan: 옛 매핑 표시(양쪽 표시) 제거" "$SPP" '`선행 대기(미포함): #e ← #e2(자식 #c)`'
lacksfx "plan: 옛 선행 미포함 매핑 표시 제거" "$SPP" '`⚠ 선행 미포함: #q ← #e(자식 #c)`'
hasfx "plan: 에픽 규칙 (ii) 순위가 이김" "$SPP" '**(ii) The fill order (rank) wins — a member already filled is never pushed out.**'
hasfx "plan: 하류 멤버가 먼저 담김" "$SPP" '`제외: #e (하류 멤버 #q 가 먼저 담김)`'
hasfx "plan: 선행 에픽과 같은 스프린트 불가" "$SPP" '`제외: #q (선행 에픽 #e 와 같은 스프린트에 쌓을 수 없음)`'
hasfx "plan: 재채움도 밀어내지 않음" "$SPP" 'a pick they rule out is skipped, never a member pushed out'
hasfx "plan: 에픽 독립 — 최종 그래프에서 하류" "$SPP" '`제외: #e (에픽 — 스프린트 안 의존 있음)`'
hasfx "plan: Phase 4 최종 그래프 재검사" "$SPP" '⚠ **Epic members are re-checked on the final graph**'
hasfx "plan: 사람 편집 경고 — q 가 에픽에 의존" "$SPP" '`⚠ #q 는 에픽 #e 에 의존합니다 — 에픽은 자기 PR 이 없어 #q 는 기본 브랜치에서 시작합니다(자식 코드 없이). 그대로 둘까요?`'
hasfx "plan: 사람 편집 경고 — 에픽이 q 에 의존" "$SPP" '`⚠ 에픽 #e 가 #q 에 의존합니다 — 자식 PR 들이 #q 의 브랜치 위에 쌓이고 sprint sync 대상이 아닙니다. 그대로 둘까요?`'
hasfx "plan: 사람 편집은 자동 제외 대신 경고" "$SPP" 'gets Phase 3'"'"'s two direction warnings'
hasfx "plan: Phase 5 사유 우선순위 — 에픽은 한 줄" "$SPP" '**Phase 5 order of reasons — one line per epic**'
hasfx "plan: 에픽 결정 필요 자식 사유" "$SPP" '`제외: #e (에픽 · 자식 #c 결정 필요 — 그 자식 Issue 에서 정해 주세요)`'
lacksfx "plan: 에픽 결정 필요 사유에 /gld plan 안내 제거" "$SPP" '그 자식 Issue 에서 정하거나 /gld plan'
hasfx "plan: 에픽 Phase 5 표시" "$SPP" '`#e (에픽 · 남은 자식 k개 — PR 최대 k개)`'
hasfx "plan: 남은 자식 많으면 경고" "$SPP" '`⚠ #e 는 남은 자식 <k>개 — 한 run 안에 끝나지 않을 수 있습니다`'
hasfx "plan: 자식 PR 스택 경고" "$SPP" '`⚠ #e 의 자식 PR 은 서로 쌓일 수 있고 sprint sync 대상이 아닙니다`'
lacksfx "plan(0.98.0): retro·daily 에픽 집계 한계 줄 제거" "$SPP" 'ⓘ 에픽 멤버는 retro·daily 지표에서 아직 미머지로 보일 수 있습니다(다음 버전에서 수정)'
lacksfx "plan: 버전 번호 약속 문구 제거" "$SPP" '(0.97.2 에서 수정)'
hasfx "plan: 슬롯은 에픽 멤버를 건드리지 않음" "$SPP" '⚠ **A slot never touches an epic member.**'
hasfx "plan: 재스폰 조건에 에픽 파일 회피" "$SPP" '*"do not touch the epic members'"'"' files"*'
hasfx "plan: skip (epic-overlap)" "$SPP" '`skip (epic-overlap)` when it overlaps'
hasfx "plan: 질문 대상 — 담긴 에픽에 의존하지 않음" "$SPP" 'and not dependent on an epic already filled'
hasfx "plan: 에픽·에픽 자식은 질문 대상 아님" "$SPP" '**Never an epic, nor an epic'"'"'s child**: an epic'"'"'s stage is'
# 2-3 목록 밖 후보·목표 정합
hasfx "plan: PO not-ranked 절(questions 뒤)" "$SPP" '· `## not-ranked` (every candidate you put in neither goal-picks nor other-ranked'
hasfx "plan: not-ranked 사유 표시는 다른 사유 줄이 없을 때만" "$SPP" '**only when no other line already gives it a reason**'
lacksfx "plan: not-ranked 전부 표시하던 옛 문장 제거" "$SPP" '`제외: #n (PO: <사유>)` — every candidate in the product-owner'"'"'s `## not-ranked`'
hasfx "plan: 목표 정합은 멤버가 바뀔 때마다" "$SPP" '**The goal matches the members — re-checked whenever the member set changes**'
hasfx "plan: 목표 수정 표시" "$SPP" '`목표 수정: 원래 «…» — <이유>`'
hasfx "plan: 목표 멤버 없음 경고" "$SPP" '`⚠ 목표 멤버 없음 — 목표를 정하거나 드롭/추가하세요`'
# 2-4 조건부 크기
hasfx "plan: TL 조건부 크기 depends:" "$SPP" '`depends: <option>→✅, <option>→⚠`, saying in plain words'
hasfx "plan: 질문 대상 size ✅ 또는 어떤 답이면 ✅" "$SPP" 'or ✅ under some answer (a `depends:`'
hasfx "plan: ⚠ 로 이어지는 선택지 라벨" "$SPP" '`(이 답이면 이번 스프린트에서 빠집니다)`'
hasfx "plan: 답 뒤 ⚠ 면 결정했지만 제외" "$SPP" '`결정했지만 제외: #n (답 <X> → 분할 예상)`'
hasfx "plan: depends 인데 질문 없음" "$SPP" '`제외: #n (크기가 결정에 달림 — <tech-lead 의 조건> — Issue 에서 정해 주세요)`'
# 2-5 human-work 분류·prerequisite·1b 막힘
hasfx "plan: human-work upstream 은 다른 저장소" "$SPP" '`human-work: <credential|device|upstream|other>` instead of a question (`upstream` = a fix that must land first in **another repository**)'
hasfx "plan: 선행 Issue 미완은 human-work 아님(차원은 unclear)" "$SPP" '**An unfinished prerequisite Issue is not human work**: rate that dimension (usually Constraint) `unclear` and write `prerequisite: #<d>` instead'
lacksfx "plan: upstream 이 선행 미완도 덮는다는 옛 문장 제거" "$SPP" '(`upstream` also covers a gap that exists only because a prerequisite Issue is unfinished)'
hasfx "plan: questions 항목은 셋 중 정확히 하나(권장 선택지 먼저)" "$SPP" 'then exactly one of: `Q: <question>` and `- A) …` lines, the option you recommend first as `- A) <answer> (recommended) — <reason>` (`(recommended)` stays in English; one option only) (a goal-picks or other-ranked candidate only), `human-work: <class>`, or `prerequisite: #<d>`)'
lacksfx "plan: 권장 없는 questions 형식 제거" "$SPP" 'then exactly one of: `Q: <question>` and `- A) …` lines (a goal-picks'
lacksfx "plan: questions 옛 형식(또는) 제거" "$SPP" 'lines, or `human-work: <class>`, or `prerequisite: #<d>`)'
hasfx "plan: prerequisite 차원은 묻지 않음" "$SPP" '**A `prerequisite: #d` dimension is not asked**'
hasfx "plan: 선행 대기(미포함) 접두" "$SPP" '`선행 대기(미포함): #n ← #d`'
lacksfx "plan: 선행 미완 = human-work: upstream 옛 문장 제거" "$SPP" 'A dimension whose gap is an unfinished prerequisite is `human-work: upstream`'
lacksfx "plan: 선행 미완이 사람 작업 필요로 가던 옛 문장 제거" "$SPP" '`사람 작업 필요` otherwise'
hasfx "plan: 1b 세 번째 판정 막힘" "$SPP" '| **막힘** | what to build is decided, but something only a human can clear blocks it'
hasfx "plan: 1b 보고 첫 줄 정의" "$SPP" '`판정 <후보 수>개 · 착수 가능 <a> · 구체화 필요 <b> · 막힘 <c> · 제외 <Phase 1 에서 뺀 수> · 절단 <없음|있음>`'
lacksfx "plan: 1b 옛 보고 첫 줄 제거" "$SPP" '판정 47개 중 41개 · 제외 6개 · 절단 없음'
hasfx "plan: 1b 보고에 막힘 그룹" "$SPP" '■ 막힘 — 사람만 풀 수 있습니다'
hasfx "plan: 막힘은 자동으로 담지 않음" "$SPP" 'one reported as **막힘** is'
hasfx "plan: 답으로 1b 통과는 구체화 필요만" "$SPP" '막힘 is not cleared by an answer'
hasfx "plan: 막힘 Phase 5 사유" "$SPP" '`사람 작업 필요: #n (<credential|device|upstream|other>)` — a Phase 1b **막힘** candidate'
hasfx "plan: 막힘 카드는 null bucket" "$SPP" '(구체화 필요 and 막힘 — both the null bucket)'
hasfx "board: null bucket 에 1b 막힘" "$GLD/commands/sprint/board.md" 'blocked on something only a human can clear (1b 막힘)'
# 2-6 경미
hasfx "plan: 재스폰 — 번호 없는 초안은 제목으로" "$SPP" '*"exclude the draft «<title>»"*'
hasfx "plan: Prepares 확인은 채우기가 끝난 뒤" "$SPP" 'Once the Phase 3 fill is done (whether or not it cut anything)'
lacksfx "plan: capacity cut 이후 옛 시점 제거" "$SPP" 'Once Phase 3 has cut the feature picks to capacity'
lacksfx "plan: 재스폰 capacity cut 옛 시점 제거" "$SPP" 'it always runs **after the Phase 3 capacity cut**'
hasfx "plan: 선행 미포함은 하드 간선만" "$SPP" "soft ordering recommendation of the tech-lead's) that is **open**"
hasfx "plan: TL 소프트 순서 권고는 의존 아님" "$SPP" 'A soft ordering recommendation (better after another, not required) is not a dependency'
hasfx "plan: retro 먼저면 아무것도 하지 않음" "$SPP" '**"retro first" → `plan` does nothing more**'
hasfx "plan: retro 먼저 반환" "$SPP" '`OK: open sprint #<t> — run /gld sprint retro first` (Phase 0 step 4'
hasfx "plan: sprint-draft mkdir 단독 호출" "$SPP" 'its own call, `mkdir -p docs/specs/sprint-draft`'
# retro·_handoff
hasfx "retro: 슬롯 skip 토큰에 epic-overlap" "$GLD/commands/sprint/retro.md" '`human-declined` · `epic-overlap` · `ad-hoc` | — | `skip:<token>` |'
hasfx "retro: skip:epic-overlap 은 결함 아님" "$GLD/commands/sprint/retro.md" 'neither is `skip:epic-overlap`'
hasfx "_handoff: K 에 not-ranked 절" "$HOMD" '`## questions` · `## not-ranked`'
hasfx "_handoff: K 에 prerequisite" "$HOMD" '`prerequisite: #<d>` (a third form of a `## questions` entry'
hasfx "_handoff: K 에 epic ×k" "$HOMD" '`epic ×<k>` (an epic, k remaining children)'
hasfx "_handoff: K 에 depends:" "$HOMD" '`depends: <option>→✅, <option>→⚠` in `deps.md`'
hasfx "_handoff: K 에 1b 막힘" "$HOMD" 'the Phase 1b verdict `막힘`'
hasfx "_handoff: K 에 슬롯 skip 토큰(epic-overlap)" "$HOMD" 'human-declined|epic-overlap|ad-hoc>)`, read back by `retro`'
lacksfx "_handoff: K 옛 human-work 순서 제거" "$HOMD" '`human-work: <credential|upstream|device|other>` classes'

hasfx "plan: 자식 목록 절단 시 에픽 제외 사유" "$PLAN" '`제외: #e (에픽 · 자식 목록이 500건에서 잘려 판정 불가)`'
hasfx "plan: 1b 가 closed-not-done 자식 본문을 직접 읽음" "$PLAN" '`gh issue view <c> --json body` (one call per such child; rare)'
hasfx "plan: 슬롯 재스폰도 BODIES 를 받음(tech-lead 목록)" "$PLAN" 'CANDIDATES (tech-lead): <the same entries as the first spawn — tags and `slot:` fields included>'
lacksfx "plan: 재스폰 옛 CANDIDATES 문구 제거" "$PLAN" 'with the same CANDIDATES (tags included)'
hasfx "plan: 슬롯 반납 재채움 시점은 Phase 3 fill 뒤" "$PLAN" 'Whenever the slot leaves after the Phase 3'
lacksfx "plan: 슬롯 반납 옛 시점(capacity cut) 제거" "$PLAN" 'Whenever the slot leaves after the capacity'
hasfx "plan: 사람이 Add 한 에픽의 자식 대기 경고" "$PLAN" '`⚠ #e 는 자식 #c needs-human 대기 — run 이 그 자식에서 멈춥니다`'

# ── 0.97.1 보강: dry-run 2차 — 공급 차단 규칙 완화 (design-relax v9-final) ──
# 1-1 에픽 자식의 depends:·섞인 판정 — 자동 채움은 남은 자식 모두 ✅ 만
lacksfx "plan: ⚠ 자식 없으면 epic 통과 옛 규칙 제거" "$PLAN" 'With no ⚠ child'
lacksfx "plan: epic ×k passes too 옛 문장 제거" "$PLAN" '`epic ×<k>` passes too'
hasfx "plan: 에픽은 남은 자식 모두 ✅ 일 때만 크기 통과" "$PLAN" '**An epic passes the size'
hasfx "plan: 섞인 판정 자식은 ⚠" "$PLAN" 'a mixed child (above) counts as ⚠, a `⚠ depends:` child as `depends:`'
hasfx "plan: 판정 없는 자식 사유" "$PLAN" '`제외: #e (에픽 · 자식 #c 크기 판정 없음)`'
hasfx "plan: Epics in the fill — 모든 자식 ✅ 게이트" "$PLAN" '- **Every child to be sized ✅** (Phase 2, the epic'"'"'s size — a child at `guild:execute` or later'
hasfx "plan: Add 경고 — 분할 예상 자식은 일시정지 (0.98.2 R2)" "$PLAN" '`⚠ #e 의 자식 #c 는 분할 예상 — run 이 그 자식에서 사람 대기로 멈추고 에픽은 일시정지됩니다(재시도 없음)`'
hasfx "plan: Add 경고 — 결정 필요 자식" "$PLAN" '`⚠ #e 의 자식 #c 는 결정이 필요합니다 — design 에서 정해지지 않으면 그 자식에서 멈출 수 있습니다`'
lacksfx "plan: Add 경고 옛 문구(다시 나뉠 수 없어) 제거" "$PLAN" '자식은 다시 나뉠 수 없어 run 이 그 자식에서 멈춥니다'
# 1-2 tech-lead satisfied 메모 → Phase 5 의견 줄 (규칙 불변)
hasfx "plan: TL satisfied 별도 메모" "$PLAN" 'write a **separate note** `satisfied: #<e> ← #<d> — via #<x> — <evidence>`'
hasfx "plan: 의견 줄(괄호 없음 — 그 뒤의 장벽 줄로)" "$PLAN" '- `의견: #e ← #d 는 이미 충족됐을 수 있습니다(tech-lead: <근거>, via #x) — 맞으면 <#e 본문|자식 #c 본문>의 Depends on 을 고치세요`'
lacksfx "plan: 의견 줄 옛 괄호 제거" "$PLAN" '(그 뒤에도 자식 #c 결정 필요)'
lacksfx "plan: Phase 5 예시의 옛 괄호 제거" "$PLAN" '(그 뒤에도 자식 #506 결정 필요)'
hasfx "plan: satisfied 의견 줄은 선행 대기로 빠진 후보만" "$PLAN" 'This `satisfied` 의견 line is shown'
hasfx "plan: satisfied 의견 줄 조건 본문" "$PLAN" '**only when that candidate (an epic or not)'
hasfx "_handoff: K 에 satisfied 메모" "$HOMD" '`satisfied: #<e> ← #<d> — via #<x> — <evidence>`'
# 1-3 크기를 정하는 질문
lacksfx "plan: depends 인데 세 차원 clear 면 제외 옛 규칙 제거" "$PLAN" 'three dimensions `clear` has no question to settle it'
hasfx "plan: 리더가 만드는 크기 질문" "$PLAN" '- **A size question the leader drafts**'
hasfx "plan: 크기 질문 선택지 ✅ 하나 ⚠ 하나" "$PLAN" '**one on the condition'"'"'s ✅ side'
hasfx "plan: 크기 질문 차원 키 Constraint" "$PLAN" 'dimension key is **`Constraint`**'
hasfx "plan: 크기 질문은 랭크 후보만" "$PLAN" '(never not-ranked — the product-owner'"'"'s'
hasfx "plan: PO Q 매핑은 차원이 아니라 내용" "$PLAN" '**no product-owner `Q:` for it maps** onto the tech-lead'"'"'s condition'
hasfx "plan: decided Constraint 줄이 있으면 재범위" "$PLAN" '`제외: #n (결정 줄이 있는데도 크기 미정 — 재범위 필요: <tech-lead 의 조건>)`'
hasfx "plan: design 단계 depends 후보 사유" "$PLAN" '`제외: #n (크기가 결정에 달림 — <tech-lead 의 조건> — 다음 design 에서 정하거나 재범위)`'
hasfx "plan: execute 이후는 크기 무시 ✅" "$PLAN" 'so the tech-lead'"'"'s size and its `depends:` are ignored and it counts as ✅'
hasfx "plan: 선택지 매핑은 명시적일 때만 ✅" "$PLAN" '**An option maps to ✅ only when its wording explicitly meets the tech-lead'"'"'s ✅ condition**'
hasfx "plan: 1b 통과는 PO Q 답만" "$PLAN" '**Only the answer to a product-owner `Q:`** clears 1b'
hasfx "plan: TL decided 줄은 크기 근거" "$PLAN" 'are evidence for the size — a decision a decided line already made is not a `depends:`'
# 1-4 PO 에게 막힘 후보를 넘기지 않음·목표 승격
hasfx "plan: 두 후보 목록" "$PLAN" '**Two candidate lists — what the leader already knows is left out of the product-owner'"'"'s.**'
hasfx "plan: PO CANDIDATES 이름" "$PLAN" '> CANDIDATES (product-owner): <number'
hasfx "plan: TL CANDIDATES 이름" "$PLAN" 'CANDIDATES (tech-lead): <the product-owner'"'"'s entry format, for **every** candidate'
hasfx "plan: slot: ineligible 필드" "$PLAN" 'field `slot: ineligible` (a field of its own — the `tag` enumeration does not change)'
hasfx "plan: (c) 는 ineligible 후보를 고르지 않음" "$PLAN" 'CANDIDATES entry carries `slot: ineligible` is never (c)**'
hasfx "plan: 막힌 refactor-slot 후보는 리더가 skip (not-ready)" "$PLAN" 'the leader records `skip (not-ready)` now, before the spawn'
hasfx "plan: PO 목록 밖 번호는 순위·목표·Q 대상 아님" "$PLAN" '**A number that is not in CANDIDATES (product-owner) is never ranked, made the goal, or given a `Q:`**'
hasfx "plan: 바닥 선행 미완 에픽은 담기지 않음(PO 지시)" "$PLAN" 'is not taken this sprint** — do not make it the center of the goal'
hasfx "plan: 바닥 선행 미완 판정 불가" "$PLAN" '`바닥 선행 미완 판정 불가`'
hasfx "plan: PO 미평가 행" "$PLAN" '`readiness: —(PO 미평가)`'
hasfx "plan: PO 판단 human-work 줄" "$PLAN" '`사람 작업 필요: #n (<class> · PO 판단, 1b 는 <착수 가능|구체화 필요>)`'
lacksfx "plan: 막힘이 PO clear 여도라는 옛 문장 제거" "$PLAN" 'even when the product-owner rated it `clear`'
lacksfx "plan: PO human-work 로 class 를 쓰던 옛 문장 제거" "$PLAN" 'the product-owner'"'"'s `human-work:` when it gave one'
hasfx "plan: 목표 승격" "$PLAN" '`목표 수정: 원래 «…» — 목표 후보가'
hasfx "plan: 목표 승격은 Phase 3 안에서만" "$PLAN" 'This promotion happens **only in the Phase 3 fill and in the refill a'
# 1-5 Phase 5 표시
hasfx "plan: 의존 무시는 멤버만" "$PLAN" '- `의존 무시: #e ← #d (본문: «<그 문장>»)` — **for members only**'
hasfx "plan: 에픽 구체화 필요 사유" "$PLAN" '`제외: #e (에픽 · 구체화 필요 — 자식 <#c|결정할 자식 전체> 본문을 구체화하세요)`'
hasfx "plan: 1b 보고 — 에픽은 자식 본문 구체화 안내" "$PLAN" '→ 자식 #503 본문을 구체화하세요'
hasfx "plan: 에픽은 /gld plan 으로 보내지 않음" "$PLAN" '⚠ **An epic is never pointed at `/gld plan`**'
# 1-6 PO 출력 형식
hasfx "plan: questions 항목은 정확히 하나" "$PLAN" '**Each `## questions` entry is exactly one of `Q:` / `human-work:` / `prerequisite:`**'
hasfx "plan: Q 는 랭크 후보에만" "$PLAN" '**Write `Q:` only for a candidate you put in goal-picks or other-ranked**'
hasfx "_handoff: K questions 항목 하나" "$HOMD" 'each entry is exactly one of `Q:` / `human-work:` / `prerequisite:`'
# 1-7 언어 줄
hasfx "plan: 역할 프롬프트는 Section K 언어 줄로 끝남" "$PLAN" 'Every role prompt below (product-owner, tech-lead, the slot re-spawn) ends with Section K'"'"'s'
hasfx "plan: 재스폰 템플릿이 언어 줄로 끝남" "$PLAN" 'SELECTED FEATURE MEMBERS: <number · title · files from (b) of each feature member the Phase 3 fill selected>. <`_handoff.md` Section K'"'"'s language line, rendered in `config.language` — the same line as the product-owner'"'"'s> Write output in `config.language`.'

hasfx "plan(보강): PO 목록에서 빼는 대상" "$PLAN" 'a Phase 1b **막힘** one, one carrying'
hasfx "plan(보강): refactor-slot 제외 시 슬롯 off·fetch 생략" "$PLAN" 'tech-lead with REFACTOR SLOT `off` (no (c) is asked for'
hasfx "plan(보강): fetch 는 두 목록 판정 뒤" "$PLAN" 'decide that after *Two candidate'
hasfx "plan(보강): 에픽 사유 ① 사람 작업 먼저" "$PLAN" '1b 막힘 → `사람 작업 필요: #e (<class>)` — first'
hasfx "plan(보강): 목표 승격 금지 범위" "$PLAN" 'Never after Phase 4'
hasfx "plan(보강): 에픽 크기 게이트 핵심 절" "$PLAN" '**An epic passes the size gate only when every child to be sized is ✅**'
hasfx "plan(보강): 의견 줄 표시 조건 핵심 절" "$PLAN" '**only when that candidate (an epic or not) is out as `선행 대기`**'
hasfx "plan(보강): tech-lead 프롬프트 끝 언어 줄" "$PLAN" "the same line as the product-owner's> Write output in \`config.language\`."
hasfx "plan(보강): 재스폰 프롬프트는 전체 템플릿" "$PLAN" '  > Adopt the persona in `.claude/agents/tech-lead.md`. This is a second request, for the sprint'"'"'s refactor slot only: produce **(c) only**'
lacksfx "plan(보강): 재스폰 옛 순서 문장 제거" "$PLAN" 'and ending with the same Section K language line, plus'

# ── 0.97.1 보강 2: dry-run 3차 — 판정 대상 자식·⚠ depends·사유 한 줄 (design-relax2 v4-final) ──
# ① 판정 대상 자식
hasfx "plan(보강2): 자식 stage 는 Section A 식으로" "$PLAN" '- **Each remaining child'"'"'s stage** = the `labels` of this child query with `_handoff.md` Section'
hasfx "plan(보강2): 판정 종류마다 경계" "$PLAN" '**The children each judgment reads — the bound differs by kind of judgment**'
hasfx "plan(보강2): 크기 판정 대상 = design 이하" "$PLAN" '- **Children to be sized** (the tech-lead'"'"'s ✅ / ⚠ / `depends:` / mixed verdict, and a missing'
hasfx "plan(보강2): 결정 판정 대상 = analyze 이하" "$PLAN" '- **Children to be decided** (the product-owner'"'"'s `decide-in: #c`, a readiness `unclear` that'
hasfx "plan(보강2): 모든 남은 자식(막힘·바닥·파일·k)" "$PLAN" '- **Every remaining child**, whatever its stage: 1b **막힘**'
hasfx "plan(보강2): 결정 대상 0 → 에픽 readiness 면제" "$PLAN" '- **No child to be decided** → the epic is not held to the readiness gate either'
hasfx "plan(보강2): 에픽 이월 표시" "$PLAN" '`이월(에픽 · 자식 모두 <stage> 이후)`'
hasfx "plan(보강2): fill step 1 의 에픽 readiness 예외" "$PLAN" '**unless it has no child to be decided**'
hasfx "plan(보강2): 1b — 막힘은 모든 자식, 구체화 필요는 결정 대상만" "$PLAN" 'every remaining child, 구체화 필요 only from the children to be decided**'
hasfx "plan(보강2): PO 지시 — analyze 이후 자식에 decide-in 금지" "$PLAN" '**A child whose stage in `children:` is later than `guild:analyze` gets no `decide-in:`, and leave it out of the readiness judgment**'
hasfx "plan(보강2): TL 지시 — execute 이후 자식은 크기 판정 안 함" "$PLAN" '**do not size a child whose stage in `children:` is `guild:execute` or later**'
hasfx "plan(보강2): TL 지시 — (a)·파일은 계속" "$PLAN" 'keep writing its (a) dependencies and its files'
hasfx "plan(보강2): design 자식 depends 사유" "$PLAN" '`제외: #e (에픽 · 자식 #c 결정 필요 — 다음 design 에서 정하거나 재범위)`'
hasfx "plan(보강2): 일반 후보 execute 이후 ⚠ 무시" "$PLAN" '**Except at `guild:execute` or later**: design does not run on it again, so it cannot split'
hasfx "plan(보강2): 슬롯 크기 기준에도 stage 면제" "$PLAN" 'candidate at stage `guild:execute` or later counts as ✅ — design can no longer split it, the'
hasfx "plan(보강2): Add 경고는 판정 대상 자식만" "$PLAN" 'a `decide-in: #c` on a child to be decided — Phase 1'"'"'s bounds; a child past them gets no such warning'
hasfx "plan(보강2): 그 뒤의 장벽 줄도 판정 대상 자식만" "$PLAN" 'child Phase 1'"'"'s bounds judge (a child to be sized, or one to be decided).'
lacksfx "plan(보강2): TL 옛 자식마다 판정 문구 제거" "$PLAN" '**and a ✅/⚠ for each remaining child**'
# ② ⚠ depends:
hasfx "plan(보강2): ⚠ depends 는 depends 로 읽음" "$PLAN" '**`⚠ depends: …` is read as `depends:`** (an ordinary candidate or a child)'
hasfx "plan(보강2): 섞임 = ⚠ 와 depends 사이 분할 근거" "$PLAN" '**Mixed** is only a verdict with a **split rationale written between the ⚠ and the `depends:`**'
hasfx "plan(보강2): TL 지시 — depends 에 ⚠ 금지" "$PLAN" '**do not put ⚠ in front of `depends:`**'
lacksfx "plan(보강2): 옛 섞임 측정 문구 제거" "$PLAN" '(measured #503: *"⚠ … depends: …"*)'
# ③ 일반 후보 사유 한 줄
lacksfx "plan(보강2): 일반 후보 사유 여러 줄 옛 규칙 제거" "$PLAN" 'keeps one line per'
hasfx "plan(보강2): 일반 후보 사유 순서 절" "$PLAN" '**Phase 5 order of reasons — ordinary candidates: one line each, the first gate it failed.**'
hasfx "plan(보강2): ② 묻지 않은 1b 구체화 필요(analyze 이하만)" "$PLAN" '② 1b 구체화 필요 at stage `none` or `guild:analyze` **not asked about** — `제외: #n (구체화 필요 — 1b)`'
hasfx "plan(보강2): ③ 선행 대기가 not-ranked 보다 먼저" "$PLAN" 'ahead of not-ranked even for a'
hasfx "plan(보강2): ⑥ 묻지 않음 형식" "$PLAN" '`제외: #n (<dim>=unclear · 묻지 않음)`'
hasfx "plan(보강2): ⑥ 여러 차원 결합" "$PLAN" '(`Goal·Success=unclear · 건너뜀`)'
hasfx "plan(보강2): ⑥ 덧붙임 — PO Q 매핑" "$PLAN" '`— 크기도 이 답에 달림`'
hasfx "plan(보강2): ⑥ 덧붙임 — 리더 크기 질문" "$PLAN" '`— 크기 질문도 건너뜀`'
hasfx "plan(보강2): 결정했지만 제외가 ⑦–⑨ 대신" "$PLAN" '**in place of ⑦–⑨**'
hasfx "plan(보강2): fill step 1 은 게이트 — 사유 순서는 아래" "$PLAN" 'This list is the gates, not the order of Phase 5'"'"'s reason lines'
hasfx "plan(보강2): PO 줄 — 일반 후보는 ④" "$PLAN" 'An ordinary candidate gets it as ④ of its order of reasons'
hasfx "plan(보강2): PO 줄 — 에픽은 다른 줄 없을 때만" "$PLAN" 'has no not-ranked — measured #161) **only when no other line already gives it a reason**'
# ④ 크기 사유 범위
hasfx "plan(보강2): 크기 사유는 채우기가 판정하는 후보만" "$PLAN" '**The size reasons below and `⚠ 분할 예상` are given only to a candidate the fill'"'"'s walk'

hasfx "plan(보강2): 에픽 구체화 안내는 결정할 자식만" "$PLAN" '자식 <#c|결정할 자식 전체> 본문을 구체화하세요'
lacksfx "plan(보강2): 옛 '남은 자식 전체' 안내 제거" "$PLAN" '남은 자식 전체'
lacksfx "plan(보강2): 옛 표제 Every remaining child ✅ 제거" "$PLAN" '**Every remaining child ✅**'
hasfx "plan(보강2): 자동 채움은 크기 판정 대상 자식 모두 ✅" "$PLAN" 'Only an epic whose children to be sized are **all** ✅'

# ── 0.97.2: sprint plan 남은 지시문 결함 (design 16 v10-final) ──
# A. 이월 후보의 1b 구체화 필요는 게이트가 아님
lacksfx "plan(0.97.2): stage 조건 없는 1b 게이트 문장 제거" "$PLAN" '구체화 필요 is never filled automatically, whatever the product-owner rated'
hasfx "plan(0.97.2): analyze 이후 1b 구체화 필요는 게이트 아님" "$PLAN" '**later than analyze** (`guild:design` or after — a carry-over) 구체화 필요 is not a gate, for'
hasfx "plan(0.97.2): 1b 보고의 이월 표시" "$PLAN" '#133 · #140 (이월 — 채우기를 막지 않음)'
hasfx "plan(0.97.2): 이월 후보에는 /gld plan 안내 없음" "$PLAN" '**A carried-over 구체화 필요** — an ordinary candidate (not an epic) at stage `guild:design` or'
hasfx "plan(0.97.2): 묻지 않은 1b 사유도 analyze 이하만" "$PLAN" '구체화 필요 candidate at stage `none` or `guild:analyze` not asked about'
# B. 중앙 관리 파일 — 정의는 Refactor slot 절 한 곳, Phase 5 는 경고 줄
_cof_n="$(grep -cF 'A central-owned file is one `/gld update` refreshes from the plugin' "$PLAN")"
if [ "$_cof_n" = 1 ]; then ok "plan(0.97.2): 중앙 관리 파일 정의는 정확히 한 곳"
else bad "plan(0.97.2): 중앙 관리 파일 정의는 정확히 한 곳" "1" "$_cof_n"; fi
_cof_in="$("$PY" - "$PLAN" <<'COFPY'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
a = s.find("### Refactor slot"); b = s.find("Collect both RESULTs")
i = s.find("A central-owned file is one `/gld update` refreshes from the plugin")
print("OK" if 0 <= a < i < b else "OUT %d %d %d" % (a, i, b))
COFPY
)"
if [ "$_cof_in" = OK ]; then ok "plan(0.97.2): 중앙 관리 파일 정의가 tech-lead 가 읽는 Refactor slot 절 안"
else bad "plan(0.97.2): 중앙 관리 파일 정의 위치" "OK" "$_cof_in"; fi
hasfx "plan(0.97.2): 파일명 토큰 앞 경계" "$PLAN" '- **`gate_precommit.py`** as a file-name token — the character before it is none of'
hasfx "plan(0.97.2): 파일명 토큰 합성 양성 사례" "$PLAN" '`gate_precommit.py.`, `gate_precommit.py를` and `gate_precommit.py` followed by `:` and a line'
hasfx "plan(0.97.2): 파일명 토큰 합성 음성 사례" "$PLAN" 'number are it; `gate_precommit.py.bak`, `gate_precommit.pyc` and `test_gate_precommit.py` are'
hasfx "plan(0.97.2): 경로 접두는 .claude/guild/gates/ 만" "$PLAN" 'quote), it counts only when that path begins `.claude/guild/gates/` or `./.claude/guild/gates/`'
hasfx "plan(0.97.2): 규칙 두 파일은 gates/rules/ 접미로만" "$PLAN" '- **`secrets.md`, `verification.md`** — only with `gates/rules/` right in front'
hasfx "plan(0.97.2): (c) 는 중앙 관리 파일을 제안하지 않음(2b 포함)" "$PLAN" 'So **do not propose (c) whose Files include a'
hasfx "plan(0.97.2): 중재 — 중앙 관리 파일 (c) 는 2b 전환 없이 거절" "$PLAN" '- **Files that include a central-owned file** (*Central-owned files*, above) → do not take it,'
hasfx "plan(0.97.2): 재스폰 최종 시도 매핑에 중앙 관리 파일" "$PLAN" '`skip (not-ready)` when it failed readiness or size or its Files include a central-owned file,'
hasfx "plan(0.97.2): 슬롯 줄 꼬리 (중앙 관리 파일)" "$PLAN" 'with `(중앙 관리 파일)`.'
hasfx "plan(0.97.2): 경고 줄 형식(스크립트)" "$PLAN" '`⚠ #n 은 중앙 관리 파일 <file> 을 고칩니다 — 다음 /gld update 는 이 로컬 수정을 덮어쓰자고 제안합니다(새 check 추가일 때만 scripts/local/ 이관을 묻습니다); 플러그인 저장소(plugin.json 의 repository)에서 고칠 일인지 확인하세요`'
hasfx "plan(0.97.2): 경고 줄 형식(규칙 파일)" "$PLAN" '`⚠ #n 은 중앙 관리 파일 <file> 을 고칩니다 — 다음 /gld update 가 게이트 스크립트와 함께 덮어씁니다; 플러그인 저장소(plugin.json 의 repository)에서 고칠 일인지 확인하세요`.'
hasfx "plan(0.97.2): 경고 줄은 정본을 가리킴" "$PLAN" 'section (*Central-owned files*), the one place they are written. Read that body: does it name'
hasfx "plan(0.97.2): 경고일 뿐 게이트 아님" "$PLAN" '`/gld contribute`: it takes only overlay and evolve candidates. **A warning, not a gate** — the'
hasfx "plan(0.97.2): 중앙 관리 파일 수정만으로는 upstream 아님" "$PLAN" '⚠ **Changing a central-owned file is not by itself `upstream`** (*Central-owned files*, in the'
# C. 목표 부분 불일치 — 기계적 기준
hasfx "plan(0.97.2): 목표 재확인은 goal-picks 출신이 있을 때 기계적" "$PLAN" '- **At least one filled `goal` member came from the product-owner'"'"'s goal-picks** (a member made'
hasfx "plan(0.97.2): 빠진 목표 후보 표시" "$PLAN" '`목표 수정: 원래 «…» — 빠진 목표 후보 #a · #b`'
hasfx "plan(0.97.2): 사람이 정한 목표는 재계산 안 함" "$PLAN" '- **A goal the human set** with Phase 5'"'"'s `목표 <문장>` edit is never recomputed; only'
hasfx "plan(0.97.2): 목표 편집" "$PLAN" '- **`목표 <문장>`** → the human'"'"'s sentence becomes the goal (and the tracker'"'"'s title). The goal'
lacksfx "plan(0.97.2): 판단에 맡기던 옛 목표 재확인 문장 제거" "$PLAN" 'does the goal sentence describe the'
# D. 권장 선택지
hasfx "plan(0.97.2): 권장 선택지 렌더링" "$PLAN" '**The recommended option** — the product-owner'"'"'s option carrying `(recommended)`, written'
hasfx "plan(0.97.2): 권장 + ⚠ 꼬리표 함께" "$PLAN" '`(권장) (이 답이면 이번 스프린트에서 빠집니다)`; the leader never drops the warning. A draft'
hasfx "plan(0.97.2): 크기 질문은 권장 없음" "$PLAN" 'size question (below) has no recommendation: it is not a product judgment — the ✅ side first,'
hasfx "plan(0.97.2): 기록되는 답은 꼬리표를 뗀 문구" "$PLAN" '  with its tags removed: `(recommended)` together with the `— <reason>` right after it'
hasfx "plan(0.97.2): 크기 매핑도 꼬리표 뗀 문구로" "$PLAN" '  is settled — the mapping reads the option'"'"'s wording with its tags removed (`(recommended)` and'
hasfx "_handoff(0.97.2): K 에 (recommended) 토큰" "$HOMD" 'the recommended-option token `(recommended)` on one `## questions` option line'
# E. 재스폰 프롬프트 전체 템플릿 (결과 계약 펜스 없음 — 사본 12개 유지)
hasfx "plan(0.97.2): 재스폰 subagent_type 줄" "$PLAN" '`description`: `tech-lead sprint slot re-spawn`'
hasfx "plan(0.97.2): 재스폰 템플릿 — Refactor slot 절만 읽기" "$PLAN" 'produce **(c) only** — one refactor-slot proposal (rules: the "Refactor slot" section of `<<SKILL_DIR>>/commands/sprint/plan.md` — read that section before writing (c), not the whole file); do not redo (a) or (b).'
hasfx "plan(0.97.2): 재스폰 템플릿 — 에픽 파일 회피 조건부" "$PLAN" '<only when epic members are selected: Do not touch the epic members'"'"' files: <their files>.>'
hasfx "plan(0.97.2): 재스폰 템플릿 — deps-slot.md 에 쓰기" "$PLAN" 'Write (c) to a FILE `docs/specs/sprint-draft/deps-slot.md`. Return one `>>> RESULT <<<` line.'
hasfx "plan(0.97.2): 재스폰 리더 지시는 블록 밖" "$PLAN" '**The slot re-spawn** (tech-lead, (c) only — the one re-spawn above). Pass the rejected numbers, not *"step 1 is exhausted"*: another'
lacksfx "plan(0.97.2): 재스폰 옛 산문 인용 제거" "$PLAN" 'asking for **(c) only** — *"exclude #<n>[, #<m>]; continue the search order'
# G. 머지 설정은 읽기 권한으로 되는 조회
hasfx "plan(0.97.2): 머지 설정 조회 gh repo view" "$PLAN" 'gh repo view <owner>/<repo> --json mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed,deleteBranchOnMerge'
lacksfx "plan(0.97.2): REST 필드 이름 제거" "$PLAN" 'allow_merge_commit'
hasfx "run(0.97.2): 머지 설정 조회 gh repo view" "$RUNMD2" 'gh repo view <owner>/<repo> --json mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed,deleteBranchOnMerge'
lacksfx "run(0.97.2): REST 필드 이름 제거" "$RUNMD2" 'allow_merge_commit'
hasfx "run(0.97.2): 조회 실패 시 토큰만으로 진행" "$RUNMD2" '*"머지 설정을 확인하지 못했습니다"*'
hasfx "run(0.97.2): 멈춤은 기본이 아닌 base 가 있을 때만" "$RUNMD2" '**and** the member table has a base that is not the default branch (a `base 의존` cell other than `—`)'
lacksfx "retro(0.97.2): 옛 필드 이름 제거" "$GLD/commands/sprint/retro.md" 'delete_branch_on_merge'
hasfx "plan(0.97.2): 조회 실패는 상한 1" "$PLAN" '- **The call fails, or `mergeCommitAllowed` is missing from its output** → do not assume the'
hasfx "plan(0.97.2): 조회 실패 Phase 5 형태(수락 전)" "$PLAN" '`머지 전략: 알 수 없음(조회 실패) → 스택 없음(상한 1) · 브랜치 자동삭제 ?`'
hasfx "plan(0.97.2): 조회 실패 Phase 5 형태(수락 후)" "$PLAN" '`머지 전략: 알 수 없음(조회 실패) → squash-sync(상한 <n>) — 하단 PR 머지 뒤 /gld sprint sync · 브랜치 자동삭제 ?`'
hasfx "plan(0.97.2): 머지 전략 squash-sync 형태" "$PLAN" '`merge commit 불허 → squash-sync(상한 <n>) — 하단 PR 머지 뒤 /gld sprint sync` (`squash-sync`) /'
hasfx "plan(0.97.2): 머지 전략 스택 거절 형태" "$PLAN" '`merge commit 불허 · 스택 거절 → 스택 없음(상한 1)` (`merge-commit-forbidden`), then'
hasfx "plan(0.97.2): 트래커 머지 전략 줄도 같은 형태" "$PLAN" '- 머지 전략: <Phase 5 의 머지 전략: 줄과 같은 형태 — merge commit 허용 ✅ |'
lacksfx "plan(0.97.2): 트래커 옛 머지 전략 줄 제거" "$PLAN" '- 머지 전략: <merge commit 허용 여부> · 브랜치 자동삭제 <여부>'
# H. 매핑 표시·그 뒤의 장벽
hasfx "plan(0.97.2): 매핑은 대상 쪽만" "$PLAN" '**The mapping is shown on the'
hasfx "plan(0.97.2): 그 뒤의 장벽 규칙" "$PLAN" '`그 뒤의 장벽: #e(자식 #c 결정 필요, #c2 분할 예상) · #e2(…)` — the words in the bracket are'
hasfx "plan(0.97.2): Phase 5 예시의 그 뒤의 장벽 줄" "$PLAN" '  그 뒤의 장벽: #161(자식 #506 결정 필요)'

hasfx "plan(0.97.2 r1): upstream 은 다른 저장소 선수정일 때만(핵심 절)" "$PLAN" 'only when the body requires a fix to land first in another'
hasfx "plan(0.97.2 r1): 이월 후보는 /gld plan 줄 없음(핵심 절)" "$PLAN" '`→ /gld plan <n>` line: past analyze'
hasfx "plan(0.97.2 r1): fill 게이트 문장에 이월 구체화 필요" "$PLAN" '착수 가능 in Phase 1b, or 구체화 필요 past analyze'
hasfx "plan(0.97.2 r1): 이유는 (recommended) 바로 뒤만 뗌" "$PLAN" 'the `— <reason>` right after it'
hasfx "plan(0.97.2 r1): 목표 후보가 돌아오면 승격 메시지 대체" "$PLAN" 'once a goal-pick is back, this rule'
hasfx "plan(0.97.2 r1): 멤버 대상 매핑 표기" "$PLAN" '`선행 대기: #e ← #d(자식 #c…)(이번 스프린트)`'
hasfx "plan(0.97.2 r1): 그 뒤의 장벽 괄호 문구" "$PLAN" '`자식 #c 크기 판정 없음`, `구체화 필요`'
hasfx "plan(0.97.2 r1): 재스폰 입력은 템플릿 한 곳" "$PLAN" 'its inputs are'
lacksfx "plan(0.97.2 r1): 재스폰 입력 중복 열거 제거" "$PLAN" 'the slot re-spawn prompt** (after this list) — with the same'

# 0.97.2 r2 — dry-run 4차·오프라인 판정 보강
# a. 중앙 관리 파일 판정 모호점
hasfx "plan(0.97.2 r2): 조건부 수정도 지목" "$PLAN" '**A conditional change counts**: written as one branch of the work ("if the investigation'
hasfx "plan(0.97.2 r2): 배제하려는 언급은 지목 아님" "$PLAN" '**A mention made to rule the change out does not**: when every'
hasfx "plan(0.97.2 r2): 경고 줄 <file> 은 파일명" "$PLAN" '`<file>` in the line is the **file name** (`gate_precommit.py`, `secrets.md`,'
# b. 결정이 수정을 모두 배제하면 경고 없음
hasfx "plan(0.97.2 r2): 결정 배제 예외(두 조건)" "$PLAN" 'unchanged — **unless a decision rules the change out**, which takes both: (1) a decision (one'
hasfx "plan(0.97.2 r2): 결정이 그 파일·묶인 항목을 다룸" "$PLAN" 'with **that file, or a change item the body ties to that file**, and (2) an answer that rules'
hasfx "plan(0.97.2 r2): 수정 갈래 모두 배제" "$PLAN" 'out **every** change branch the body writes for that file (measured #349: "3건 모두 명시적'
hasfx "plan(0.97.2 r2): 일부 배제·무관 결정이면 경고" "$PLAN" 'file changes of defects 1 and 2 remain), or one unrelated to that file → the line.'
# c. tech-lead 도 같은 규칙 · 조건부 관계는 메모
hasfx "plan(0.97.2 r2): TL 은 슬롯 값과 무관하게 정본 문단을 읽음" "$PLAN" '**Whatever REFACTOR SLOT is, read the *Central-owned files* paragraph of the "Refactor slot" section of `<<SKILL_DIR>>/commands/sprint/plan.md`**'
hasfx "plan(0.97.2 r2): TL 중앙 관리 파일 수정만으로는 선수정 아님" "$PLAN" 'changing a central-owned file is not by itself a fix that must land first in another repository — judge size and dependencies on the work in this repository'
hasfx "plan(0.97.2 r2): TL 조건부 관계는 별도 메모" "$PLAN" '`conditional: #<a> ← #<b> (조건: <condition>) — <note>` (apart from (b)'"'"'s `depends:` size form)'
hasfx "plan(0.97.2 r2): TL decided 줄이 조건을 정하면 참/거짓" "$PLAN" 'when a body'"'"'s `decided:` line already settles the condition, it is true → a dependency in (a), or false → left out'
hasfx "plan(0.97.2 r2): 조건부 의견 줄" "$PLAN" '- `의견: #a ← #b (조건: <조건>) — <tech-lead 메모>` — the tech-lead'"'"'s `conditional:` note (a'
hasfx "plan(0.97.2 r2): 조건부 의견 줄은 둘 다 멤버일 때만" "$PLAN" 'shown **only when both `#a` and `#b` are members**'
hasfx "plan(0.97.2 r2): 조건부 메모는 의존으로 쓰지 않음" "$PLAN" 'line. The direction is the note'"'"'s — never `↔`. The leader never uses the note as a dependency:'
hasfx "plan(0.97.2 r2): 선행 미포함은 조건부 메모 제외" "$PLAN" 'conditional note or soft ordering recommendation of the tech-lead'"'"'s) that is **open** (in'
hasfx "plan(0.97.2 r2): 사유 순서 ③ 은 satisfied 의견 줄" "$PLAN" 'not-ranked candidate, so that the `satisfied` `의견:` line (shown only for a candidate out as'
lacksfx "plan(0.97.2 r2): 옛 의견 줄 일반 조건 제거" "$PLAN" 'so that the `의견:` line (shown only for a candidate out as `선행 대기`)'
# e. k=0 에픽
hasfx "plan(0.97.2 r2): 1b 제외에 k=0 에픽 포함" "$PLAN" '(`<후보 수>` = a + b + c; `제외` = the Issues Phase 1'"'"'s exclusions removed from the read, **k = 0'
hasfx "plan(0.97.2 r2): k=0 에픽은 에픽마다 한 줄, 사람 작업 필요 다음" "$PLAN" 'candidate: Phase 5 `통합 점검 대기 — /gld dev #e`, one line per such epic, right after the'
hasfx "plan(0.97.2 r2): Phase 5 템플릿에 통합 점검 대기 줄" "$PLAN" '  통합 점검 대기 — /gld dev #458'
# f. 후보 N개 중 M개
hasfx "plan(0.97.2 r2): 첫 줄 M·N 정의" "$PLAN" 'The first line, `후보 N개 중 M개`: M = the members taken (a new slot draft included), N = the'
hasfx "plan(0.97.2 r2): M 이 N 을 넘을 수 있음" "$PLAN" 'candidates judged (1b'"'"'s `<후보 수>`) — a new slot draft is not among the N, so M can exceed N.'
# g. 앞서 구체화 필요로 보고한 — 세 번째 결말
hasfx "plan(0.97.2 r2): 1b 안내에 세 결말" "$PLAN" '(`앞서 구체화 필요로 보고한 #n — 이번에 답해 담았습니다 / 건너뛰었습니다 / 이번에 답했지만 빠졌습니다(결정했지만 제외 줄 참고)`)'
lacksfx "plan(0.97.2 r2): 두 결말만 있던 옛 문구 제거" "$PLAN" '이번에 답해 담았습니다 / 건너뛰었습니다`)'
hasfx "plan(0.97.2 r2): Phase 5 세 번째 결말" "$PLAN" '`이번에 답했지만 빠졌습니다(결정했지만 제외 줄 참고)` — answered but out of the sprint (size,'
hasfx "plan(0.97.2 r2): 사유는 결정했지만 제외 줄에만" "$PLAN" 'depth, a dependency, a drop — whichever): the reason is written on its `결정했지만 제외:` line'
# h. 스택 없음 편집
hasfx "plan(0.97.2 r2): Phase 0 거절은 스택 없음 편집" "$PLAN" '(no stacking; every PR targets the default branch) — Phase 5'"'"'s **`스택 없음`** edit.'
hasfx "plan(0.97.2 r2): 스택 없음은 squash-sync 일 때만" "$PLAN" '- **`스택 없음`** → offered **only when 상한 근거 is `squash-sync`** — including a `squash-sync`'
hasfx "plan(0.97.2 r2): 안내 줄 스택 없음은 squash-sync 일 때만" "$PLAN" '`[/ 스택 없음]` is shown **only when 상한 근거 is `squash-sync`** (Edits, `스택 없음`), rendered without'
hasfx "plan(0.97.2 r2): 스택 없음 → merge-commit-forbidden·상한 1·sync 안내 제거" "$PLAN" 'stacking (Phase 0 step 5): rewrite 상한 근거 to `merge-commit-forbidden` and `EFFECTIVE_CAP` to'
hasfx "plan(0.97.2 r2): 스택 없음은 컷 제안으로" "$PLAN" '**This edit leads to a cut proposal**: a depth over 1 gets step 4'"'"'s usual proposal to cut.'
hasfx "plan(0.97.2 r2): 깊이 수락은 스택 없음을 무름" "$PLAN" '**Accepting that depth instead of the cut switches back to `squash-sync`** (step 4) — it undoes'
hasfx "plan(0.97.2 r2): 스택 없음이면 슬롯은 stack-cap 으로 빠짐" "$PLAN" '`스택 없음`. A slot, if there is one, leaves by itself once the depth is 1 (the cut accepted —'
hasfx "plan(0.97.2 r2): config 일 때 스택 없음 답" "$PLAN" 'line: `merge commit 이 허용되어 스택은 그대로 머지됩니다 — 깊이를 줄이려면 크기 N 이나 드롭`.'

hasfx "_handoff: K 에 conditional: 메모 토큰" "$HOMD" '`conditional: #<a> ← #<b> (조건: <condition>) — <note>`'

hasfx "plan(0.97.2 r2 cr): 스택 없음 안내 렌더링" "$PLAN" 'the line then ends `재정렬 / 스택 없음 요청 가능)`'
hasfx "plan(0.97.2 r2 cr): 슬롯은 깊이 1 이 된 뒤 빠짐" "$PLAN" 'leaves by itself once the depth is 1'
hasfx "plan(0.97.2 r2 cr): stack-cap 비움 문구" "$PLAN" '`🧹 리팩토링 슬롯: 비움 (stack-cap) — 스택 없음(상한 1)에서는 슬롯이 스택을 늘립니다`'


# 0.98.0 — retro·daily 의 에픽(분할) 멤버: S·자식 발견, PR 필터 멤버∪자식, 두 축, 판단 불가
D98="$GLD/commands/sprint/daily.md"
R98="$GLD/commands/sprint/retro.md"
P98="$GLD/commands/sprint/plan.md"
# 1-1 자식 발견 — daily·retro 같은 명령(스트림, 첫 줄 = 개수)
CHILD98='gh issue list --label guild:child --state all --limit 500 --json number,title,body,labels,state --jq '"'"'length, (.[] | {number, title, state, labels: [.labels[].name], parent: ((.body // "") | (match("Parent Issue: #([0-9]+)").captures[0].string | tonumber)? // null)})'"'"
hasfx "daily(0.98.0): 자식 발견 호출" "$D98" "$CHILD98"
hasfx "retro(0.98.0): 자식 발견 호출(daily 와 같음)" "$R98" "$CHILD98"
SUPP98='gh issue list --state all --search '"'"'"Parent Issue: #<m>" in:body'"'"' --limit 200 --json number,title,body,labels,state --jq '"'"'length, (.[] | select((.body // "") | test("Parent Issue: #<m>([^0-9]|$)")) | {number, title, state, labels: [.labels[].name], parent: <m>})'"'"
hasfx "daily(0.98.0): 자식 보충 — 같은 객체 형태" "$D98" "$SUPP98"
hasfx "retro(0.98.0): 자식 보충 — 같은 객체 형태" "$R98" "$SUPP98"
hasfx "daily(0.98.0): S 정의" "$D98" '**S** (the split members) = every member that is some child'"'"'s `parent`, plus every member'
hasfx "retro(0.98.0): S 정의" "$R98" '**S** = every member that is some child'"'"'s `parent`, plus every member labelled'
hasfx "daily(0.98.0): 자식 절단 시 done·children 멤버 전부 보충" "$D98" 'for **every** member labelled `guild:done` or `guild:children` — by label, whether'
hasfx "daily(0.98.0): 보충 실패는 판단 불가" "$D98" 'first line equals 200** → the children cannot be known: the sprint is **판단 불가** (step 6).'
hasfx "retro(0.98.0): 보충 실패는 지표 FAIL" "$R98" '`FAIL: could not find every child of #<m> — the metrics would be wrong and'
# 1-2 daily 멤버 호출 = retro 형식
MEM98='gh issue list --state all --limit 200 --json number,title,labels,state,body --jq '"'"'{total: length, members: [.[] | select((.body // "") | test("Sprint: #<tracker>([^0-9]|$)")) | {number, title, state, labels: [.labels[].name]}]}'"'"
hasfx "daily(0.98.0): 멤버 호출이 retro 와 같음" "$D98" "$MEM98"
hasfx "retro(0.98.0): 멤버 호출(daily 와 같음)" "$R98" "$MEM98"
hasfx "daily(0.98.0): 멤버 절단 시 서버 검색" "$D98" '`total` equal to the limit → re-read with the server-side filter `--search '"'"'"Sprint: #<tracker>" in:body'"'"'`'
if grep -qxF 'gh issue list --state all --limit 200 --json number,title,labels,state' "$D98"; then
  bad "daily(0.98.0): 옛 무필터 멤버 호출 제거" "absent" "found the unfiltered members call"
else
  ok "daily(0.98.0): 옛 무필터 멤버 호출 제거"
fi
lacksfx "daily(0.98.0): 옛 자식 호출(전체 --limit 200) 제거" "$D98" 'children: [.[] | select((.body // "") | test("Parent Issue: #<parent>([^0-9]|$)"))'
# 1-3 PR 호출 — 같은 형태, 멤버∪자식, 스트림
hasfx "daily(0.98.0): PR 호출 스트림·멤버∪자식 필터" "$D98" "--jq '[<m1>,<m2>,<c1>] as \$m | length, (map(.number) | min // 0), (.[] | ([.closingIssuesReferences[]? | select(.repository.owner.login == \"<owner>\" and .repository.name == \"<repo>\") | .number] | map(select(. as \$n | \$m | index(\$n)))) as \$c | ((.headRefName // \"\") | test(\"(^|[^0-9])#?(<m1>|<m2>|<c1>)([^0-9]|\$)\")) as \$b | select((\$c | length) > 0 or \$b) | {number, headRefName, baseRefName, state, mergedAt, reviewDecision, closes: \$c, via:"
hasfx "daily(0.98.0): PR 호출 필드" "$D98" 'gh pr list --state all --limit 200 --json number,headRefName,baseRefName,state,mergedAt,reviewDecision,statusCheckRollup,closingIssuesReferences --jq'
hasfx "retro(0.98.0): PR 호출 스트림·멤버∪자식 필터" "$R98" "--jq '[<m1>,<m2>,<c1>] as \$m | length, (map(.number) | min // 0), (.[] | ([.closingIssuesReferences[]? | select(.repository.owner.login == \"<owner>\" and .repository.name == \"<repo>\") | .number] | map(select(. as \$n | \$m | index(\$n)))) as \$c | ((.headRefName // \"\") | test(\"(^|[^0-9])#?(<m1>|<m2>|<c1>)([^0-9]|\$)\")) as \$b | select((\$c | length) > 0 or \$b) | {number, headRefName, baseRefName, state, mergedAt, closedAt, reviewDecision, closes: \$c, via:"
lacksfx "daily(0.98.0): 옛 PR 한 줄 형태 제거" "$D98" "--jq '{total: length, prs: [.[] | {number"
lacksfx "retro(0.98.0): 옛 PR 한 줄 형태 제거" "$R98" '[<m1>,<m2>,<m3>] as $m | {total: length, prs:'
hasfx "daily(0.98.1): PR 완전성 판정 실패 → 500 재읽기" "$D98" 'Otherwise re-read with `--limit 500` and apply the same test. **The 완전성 판정 still'
hasfx "daily(0.98.1): 완전성 판정 실패 시 per-Issue 보충 없음" "$D98" 'fails → no per-Issue fallback**: a `"Closes #<m>" in:body` search cannot find a PR linked only by'
hasfx "retro(0.98.0): PR 절단은 per-Issue 보충 없이 FAIL" "$R98" '⚠ **No per-Issue fallback on this'
hasfx "daily(0.98.0): branch 연결은 확인 후" "$D98" 'confirm, not a fact — the same check as `retro.md` Phase 1 — and only a confirmed one joins that'
hasfx "daily(0.98.0): 호출 순서" "$D98" '**In this order — members, then children, then PRs**'
# 1-4 두 축·에픽 결말
hasfx "daily(0.98.0): 머지 축" "$D98" '- **Merge axis** (the counts — the goal line here, `retro`'"'"'s metrics): any `MERGED` PR → **머지**'
hasfx "daily(0.98.0): 종료 축" "$D98" '- **Finish axis** (the table above): no `OPEN` PR and not 거절. An Issue whose first PR was'
hasfx "daily(0.98.0): sprint finished 정의" "$D98" '| **sprint finished** | run finished **AND**, for every ordinary member and every child of S: no `OPEN` PR **AND** not 거절 (below) |'
hasfx "retro(0.98.0): sprint finished 정의(같음)" "$R98" '| **sprint finished** | run finished **AND**, for every ordinary member and every child of S: no `OPEN` PR **AND** not 거절'
lacksfx "daily(0.98.0): 옛 PR 단위 finished 제거" "$D98" 'no member PR is `CLOSED` unmerged'
lacksfx "retro(0.98.0): 옛 PR 단위 finished 제거" "$R98" 'no member PR is `CLOSED` unmerged'
hasfx "daily(0.98.0): 에픽은 한 자리 — 머지 조건" "$D98" '- **An epic (a member of S) is one seat.** It is 머지 ⇔ the parent is `guild:done` **and** every'
hasfx "daily(0.98.0): 에픽 결말 — 거절·진행 중" "$D98" 'Parent `guild:done` and a child 거절 → **미머지(자식 PR 거절)**; else a child'
hasfx "daily(0.98.0): 에픽 결말 — 미착수·캐리오버" "$D98" 'else a child 미착수 (no PR — a `closed-not-done` child, say) → **미머지(자식 PR 없음)**. Parent'
lacksfx "daily(0.98.0): done 도달 분할 부모 조건 제거" "$D98" 'reached `guild:done` by being split'
# 1-5 retro 지표
hasfx "retro(0.98.0): 이행률은 머지 축·에픽 한 자리" "$R98" '머지 축(`daily.md` step 6). 에픽은 한 자리, 자식이 모두 머지돼야 머지'
hasfx "retro(0.98.0 17b): 사람 대기 — 에픽(부모 또는 done 아닌 자식)" "$R98" '에픽은 부모 또는 done 이 아닌 자식 중 하나라도 `guild:needs-human` 이면 1'
lacksfx "retro(0.98.0 17b): 옛 S 의 자식 사람 대기 정의 제거" "$R98" '에픽은 부모 또는 S 의 자식 중 하나라도'
hasfx "retro(0.98.0): 닫힌-미머지는 자식 PR 포함" "$GLD/commands/sprint/retro.md" '— **자식 PR 도 같은 범위로 센다**'
hasfx "retro(0.98.0): 변경 요청률·스택은 멤버 PR 만" "$R98" '리뷰 변경 요청률과 스택 따라잡기만 **멤버 PR 만** 센다'
hasfx "retro(0.98.0 17b): 에픽 행 자식 머지 x/y" "$R98" '`자식 머지 <x>/<y>`'
lacksfx "retro(0.98.0 17b): 옛 자식 PR 머지 제거" "$R98" '자식 PR 머지'
hasfx "retro(0.98.0): history·권고 표 불변" "$R98" 'The `history` schema and the recommendation table do not change.'
# 1-6 daily 목표 줄·판단 불가·분할 부모 줄
hasfx "daily(0.98.0): 목표 줄 판단 불가" "$D98" '`목표: 판단 불가(<이유>)`'
hasfx "daily(0.98.1): 스프린트 판단 불가(완전성 판정 실패)" "$D98" '`스프린트 종료: 판단 불가 — PR 목록 500건이 가장 오래된 멤버까지 닿지 않아 판정할 수 없습니다(retro 도 같은 이유로 실패합니다)`'
hasfx "daily(0.98.0): 판단 불가면 회고 가능 안내 없음" "$D98" 'and do **not** suggest `회고 가능`'
hasfx "daily(0.98.0): Return 에 undetermined" "$D98" 'sprint <finished|open PRs N|undetermined>`'
hasfx "daily(0.98.0): 분할 부모 줄은 S 전체" "$D98" '⚠ **Add the split-parent line** for every member of S (step 3), whatever its state, with its'
hasfx "daily(0.98.0 17b): 진행 중 분할 부모 문구" "$D98" '`#e 은 자식으로 진행 중입니다(머지 안 된 자식 <n>개)`'
lacksfx "daily(0.98.0 17b): 옛 남은 자식 k 문구 제거" "$D98" '(남은 자식 <k>개)'
lacksfx "daily(0.98.0): 옛 분할 부모 조건 제거" "$D98" 'the same condition step 6'
hasfx "daily(0.98.0): Hard rules 호출 수" "$D98" '- Five `gh` calls (sprint list · tracker comments · members · child discovery · PR list) plus'
lacksfx "daily(0.98.0): 옛 Hard rules 호출 수 제거" "$D98" '- Four `gh` calls (issue list · tracker comments · PR list · issue list)'
hasfx "daily(0.98.0): Gather 호출 수" "$D98" '**3. Gather — four `gh` calls here plus one `git`; five `gh` in total, counting step 1**'
# CLEANUP·Phase 1·Phase 7
hasfx "retro(0.98.0): CLEANUP 호출 목록" "$R98" 'Then Phase 1'"'"'s members call, child-discovery'
hasfx "retro(0.98.0): CLEANUP per-Issue 대상에 자식" "$R98" 'look up each member **and each'
lacksfx "retro(0.98.0): 옛 CLEANUP 호출 목록 제거" "$R98" 'Then Phase 1'"'"'s members call and PR call for'
hasfx "retro(0.98.0): Phase 1 같은 세 호출" "$R98" 'the same three calls in the same order'
lacksfx "retro(0.98.0): 옛 same three gh calls 제거" "$R98" 'same three `gh` calls, same derivation'
hasfx "retro(0.98.0): 개수 설명(total·첫 줄)" "$R98" '`total` in the members call, the first line of the child and PR calls.'
hasfx "retro(0.98.0): Phase 7 은 Phase 1 의 S·자식 재사용" "$R98" '- **Split children.** Reuse Phase 1'"'"'s S and its children (the child call and, when it was'
lacksfx "retro(0.98.0): Phase 7 의 마커 자식 읽기 제거" "$R98" 'Take the children from the run marker'"'"'s discovered children'
lacksfx "retro(0.98.0): Phase 7 의 번호만 자식 검색 제거" "$R98" "--json number,body --jq 'map(select((.body // \"\") | test(\"Parent Issue: #<m>([^0-9]|\$)\")) | .number)'"
# 1-7 plan
hasfx "plan(0.98.0): Known limit 에서 daily 제외" "$P98" '(`_handoff.md` Section I, `status.md`) still read `--limit 200`; in a repo with more'
hasfx "plan(0.98.0): daily·retro 는 --label guild:child --limit 500" "$P98" '(`daily` and `retro` read `--label guild:child --limit 500`, as Phase 1 does.)'
lacksfx "plan(0.98.0): Known limit 의 daily.md 제거" "$P98" '(`_handoff.md` Section I, `status.md`, `daily.md`) still read'
lacksfx "plan(0.98.0): 다음 버전 안내 문구 제거" "$P98" '(다음 버전에서 수정)'

hasfx "daily(0.98.0 cr): 자식 보충 실패 시 스프린트 판단 불가" "$GLD/commands/sprint/daily.md" '`스프린트 종료: 판단 불가 — #<m> 의 자식을 모두 찾지 못했습니다(retro 도 같은 이유로 실패합니다)`'
hasfx "retro(0.98.0 cr): CLEANUP 자식 보충 실패는 보고 후 제외" "$GLD/commands/sprint/retro.md" 'A child supplement that fails (an error, or its first line equals 200 — Phase 1) → report'
hasfx "retro(0.98.0 cr): CLEANUP 은 Phase 0 step 0 경로" "$GLD/commands/sprint/retro.md" '(CLEANUP: Phase 0 step 0 instead)'
hasfx "retro(0.98.0 cr): 닫힌-미머지는 자식 PR 도 같은 범위" "$GLD/commands/sprint/retro.md" '**자식 PR 도 같은 범위로 센다**(멤버 PR 만이 아님)'
hasfx "plan(0.98.0 cr): 에픽 머지는 부모 done + 자식 모두 머지" "$PLAN" 'merged when it is `guild:done` and all its children are merged'

# 0.98.0 보강(17b) — 감사자 자식 합산 · 사람이 닫음과 에픽 · 분할 부모 줄 · 리뷰 대기의 자식 PR · Phase 6 묶음 · 사소
# f. 마커의 discovered children 읽기 제거 · 판단 불가 목표 줄은 구분 열이 있을 때만 · 완료 N/M 은 라벨
lacksfx "daily(0.98.0 17b): 마커의 discovered children 읽기 제거" "$D98" 'per-issue retries, discovered children'
hasfx "daily(0.98.0 17b): 자식은 마커가 아니라 자식 발견 호출" "$D98" 'The children are **not** read from the marker — they come from step 3'"'"'s child call'
hasfx "daily(0.98.0 17b): 판단 불가 목표 줄은 구분 열이 있을 때만" "$D98" '**and the table has the `구분`'
hasfx "daily(0.98.0 17b): 구분 열 없는 트래커는 목표 줄 없음" "$D98" 'not shown; a table without the column still gets no goal line at all.'
hasfx "daily(0.98.0 17b): 완료 N/M 은 라벨 기준" "$D98" '- **`완료 N/M` on the 진행 line counts labels** (`guild:done`)'
# c. 분할 부모 줄
hasfx "daily(0.98.0 17b): n = 머지 축에서 머지 아닌 자식" "$D98" 'children that are **not 머지 on step 6'"'"'s merge axis**, whatever their labels.'
hasfx "daily(0.98.0 17b): 부모 닫힘·미done 이면 사람이 닫음 우선" "$D98" '0. Parent `CLOSED` and not `guild:done` → step 6'"'"'s *"사람이 닫음"* line takes precedence'
hasfx "daily(0.98.0 17b): 통합 점검 대기 문구" "$D98" '`통합 점검 대기 — run 이 끝난 뒤에도 남아 있으면 /gld dev #e (run 진행 중에는 run 이 이어갈 수 있으니 동시에 실행하지 마세요)`'
lacksfx "daily(0.98.0 17b): 옛 k = done 아닌 자식 정의 제거" "$D98" '`k` = its children **without'
hasfx "daily(0.98.0 17b): 에픽의 사람 대기 정의" "$D98" 'without `guild:done`, carries `guild:needs-human`**'
hasfx "daily(0.98.0 17b): 분할 부모 줄 사람 대기 표기" "$D98" 'append ` · 사람 대기 #<번호>`'
hasfx "daily(0.98.0 17b): done 부모 — 거절 자식" "$D98" '2. Parent `guild:done` — step 6'"'"'s epic order, unchanged: a child 거절 → `#e 미머지(자식 PR 거절)`'
hasfx "daily(0.98.0 17b): 거절 자식 줄에 열린 자식 PR" "$D98" 'plus ` · 열린 자식 PR #<pr>` for each open child PR'
hasfx "daily(0.98.0 17b): done 부모 — 진행 중 자식" "$D98" '`#e done·미머지 — 자식 PR 리뷰·머지 대기(머지 안 된 자식 <n>개)`'
hasfx "daily(0.98.0 17b): done 부모 — 미착수 자식" "$D98" '`#e 미머지(자식 PR 없음)`'
hasfx "daily(0.98.0 17b): 모두 머지 문구" "$D98" '`#e 은 자식 PR 로 완료됩니다 — 보드 카드는 부모에 남습니다`'
hasfx "daily(0.98.0 17b): 자식 needs-human 은 사람 대기 섹션에" "$D98" '`#e 자식 #c needs-human 대기 — /gld resume <c> (그 뒤'
hasfx "daily(0.98.0 17b): step 6 캐리오버는 지표 그대로" "$D98" '진행 중 or 사람이 닫음; the count stays 캐리오버)'
# d. 리뷰 대기의 자식 PR 위치
hasfx "daily(0.98.0 17b): 자식 PR 은 부모 자리" "$D98" '- **A child PR sits in its parent'"'"'s place**, not after the member PRs'
hasfx "daily(0.98.0 17b): 자식 PR 줄 형식·N = 목록 순번" "$D98" '`PR #<pr>  #<c>(#<e> 자식) 제목 → base`. The **N in "N번 먼저" is the list position**'
hasfx "daily(0.98.0 17b): 에픽 의존 멤버는 남은 마지막 자식 PR" "$D98" 'that depends on the epic → the position of the **last of that epic'"'"'s child PRs still in the'
hasfx "daily(0.98.0 17b): 순서 권고이지 스택 경고 아님" "$D98" 'split-completed parent), so for it the marker is an **order recommendation, not a stack'
# b. 사람이 닫음
hasfx "daily(0.98.0 17b): 사람이 닫음 판정 — CLOSED·미done" "$D98" 'judged from data already in hand: the member Issue is `CLOSED`, is **not `guild:done`**, and'
hasfx "daily(0.98.0 17b): 사람이 닫음 판정 — 머지 PR 없음" "$D98" 'has **no `MERGED` PR mapped to it** (step 3'"'"'s PR list) — the same definition as `retro.md`'
hasfx "daily(0.98.0 17b): 사람이 닫음 한계(직접 push)" "$D98" 'by a `fixes #N` commit pushed directly, with no PR, lands here too.'
hasfx "daily(0.98.0 17b): done 부모 에픽은 사람이 닫음 아님" "$D98" '- **Not for an epic whose parent is `guild:done`** (a member of S)'
hasfx "daily(0.98.0 17b): 거절과 겹치면 한 줄" "$D98" '`… · 사람이 닫음 · 닫힌 PR #<n>`'
# a. 감사자
hasfx "retro(0.98.0 17b): 감사자 행 — 분할 멤버는 자식 이슈" "$R98" '| 감사자 루프백 | 멤버 이슈(분할 멤버는 자식 이슈)의 감사자 레코드에서'
hasfx "retro(0.98.0 17b): 감사자는 멤버 PR 만 목록에 없음" "$R98" '넣지 않는다 — PR 이 아니라 Issue 의 레코드이고, 분할 멤버는 자식 이슈를 읽는다'
hasfx "retro(0.98.0 17b): 감사자 호출 — 멤버 또는 S 의 자식마다" "$R98" '**감사자 루프백** — one call per member or per child of S is acceptable here'
lacksfx "retro(0.98.0 17b): 옛 멤버당 1회 문구 제거" "$R98" 'one call per member is acceptable here'
hasfx "retro(0.98.0 17b): dismissed 번호 — 멤버 또는 자식" "$R98" 'The call is per member or'
lacksfx "retro(0.98.0 17b): 옛 The call is per member 제거" "$R98" 'The call is per member,'
hasfx "retro(0.98.0 17b): 자식이 발견된 부모는 빼고 자식을 조회" "$R98" '⚠ **Which Issues — an epic is read through its children.** Look up every member **except a'
hasfx "retro(0.98.0 17b): 숫자는 합산, 판정은 자식별" "$R98" '- **Numbers are summed, verdicts are not.**'
hasfx "retro(0.98.0 17b): 에픽 감사자 줄 형식" "$R98" '`#146 에픽(자식 합산) records 11 · looped-back 4 · 기록 없음 #<c>`'
hasfx "retro(0.98.0 17b): 미착수 자식은 따로" "$R98" 'A child that is **미착수** on the merge axis (no PR) is written apart as `미착수 #<c>` and left'
hasfx "retro(0.98.0 17b): 이전 스프린트 자식 레코드 누적" "$R98" 'The record is cumulative, so a child finished in an **earlier** sprint still adds its records'
# f. 자식 머지 x/y
hasfx "retro(0.98.0 17b): 에픽 행 예시" "$R98" '`#146 에픽 — done·미머지 · 자식 머지 2/3`'
# e. Phase 6 묶음 · 다음 안내
lacksfx "retro(0.98.0 17b): 옛 착지 못한 모든 멤버 한 목록 제거" "$R98" '1. **Name the carryover explicitly** — every member that did not land'
hasfx "retro(0.98.0 17b): 미머지 멤버는 정확히 한 묶음" "$R98" 'falls in **exactly one** group:'
hasfx "retro(0.98.0 17b): 1번 캐리오버" "$R98" '1. **캐리오버 — 다음 plan 이 이어받음**: an `OPEN` Issue, not `guild:done`.'
hasfx "retro(0.98.0 17b): 1b 통합 점검 대기" "$R98" '1b. **`통합 점검 대기 — /gld dev #e (다음 plan 후보 아님)`**'
hasfx "retro(0.98.0 17b): 2번 사람이 닫음" "$R98" '2. **사람이 닫음 — 다음 plan 대상 아님**: `CLOSED` and not `guild:done`'
hasfx "retro(0.98.0 17b): 3번 done·열린 PR" "$R98" '3. **done·미머지 — 열린 PR 리뷰·머지 필요**: `guild:done` with an `OPEN` PR.'
hasfx "retro(0.98.0 17b): 3번 에픽 표기" "$R98" '`#e — 열린 자식 PR #<pr>(#<c>)`, plus `· 거절 #<c>`'
hasfx "retro(0.98.0 17b): 4번 done·PR 거절/없음" "$R98" '4. **done·미머지 — PR 거절/없음(사람이 판단)**: `guild:done` with **no open PR**'
hasfx "retro(0.98.0 17b): 지표 캐리오버 = 1+1b+2" "$R98" 'The carryover **metric** (Phase 2) is unchanged by this grouping: it is groups 1 + 1b + 2'
hasfx "retro(0.98.0 17b): 다음 안내 — 다음 plan 대상" "$R98" '캐리오버 <n>개(다음 plan 대상 — 사람 대기 <m>개 제외)가 최우선 후보입니다'
lacksfx "retro(0.98.0 17b): 옛 다음 안내 제거" "$R98" '캐리오버 <n>개가'

hasfx "daily(17b cr): 사람 대기 예시가 자식 needs-human 형식" "$GLD/commands/sprint/daily.md" '  #107 자식 #112 needs-human 대기 — /gld resume 112'
hasfx "daily(17b cr): resume 뒤 남은 자식 안내" "$GLD/commands/sprint/daily.md" '(그 뒤 남은 자식은 /gld dev #e 또는 sprint run 재실행)'
hasfx "daily(17b cr): 자식 PR 은 부모 자리" "$GLD/commands/sprint/daily.md" 'a child PR takes its parent'"'"'s place in it'
hasfx "daily(17b cr): 자식은 하나씩 — PR 없어도 사람 대기" "$GLD/commands/sprint/daily.md" 'stopped epic often shows only children with no PR or already merged'
hasfx "daily(17b cr): step 6 괄호에 사람이 닫음" "$GLD/commands/sprint/daily.md" 'it as 통합 점검 대기, 진행 중 or 사람이 닫음'
hasfx "retro(17b cr): 미착수 자식 숫자는 합산" "$GLD/commands/sprint/retro.md" '(its numbers, if any, still go into the epic'"'"'s sum)'

hasfx "daily(0.98.0 verify): completion 은 run 종료 시점 스냅샷" "$GLD/commands/sprint/daily.md" 'is rendered with ` (run 종료 시점)` after it'
hasfx "daily(0.98.0 verify): 완료된 에픽 부모는 닫으라고 안내" "$GLD/commands/sprint/daily.md" 'plus ` — #e 를 닫으세요` while the'
hasfx "retro(0.98.0 verify): 그룹 3 에픽은 머지 뒤 닫기 안내" "$GLD/commands/sprint/retro.md" '`— 자식 PR 이 모두 머지되면 #e 를 닫으세요`'
hasfx "retro(0.98.0 verify): 자식 판정에 mixed 를 쓰지 않음" "$GLD/commands/sprint/retro.md" '(not called "mixed": that word below means a'
hasfx "retro(0.98.0 verify): 캐리오버 0 문구" "$GLD/commands/sprint/retro.md" '(n = 0 → *"다음 plan 이 이어받을'

hasfx "retro(0.98.0 final): 머지된 열린 에픽 부모 닫기 안내" "$GLD/commands/sprint/retro.md" '`#e — 자식이 모두 머지됨, #e 를 닫으세요`'
hasfx "retro(0.98.0 final): 거절 자식이 있으면 닫기 안내 없음" "$GLD/commands/sprint/retro.md" 'child needs the human'"'"'s call first, so that case gets no close line'
hasfx "retro(0.98.0 final): 리뷰·머지 대기 PR 수 문장과 k 정의" "$GLD/commands/sprint/retro.md" '`k` = the open PRs in group 3, child PRs'
hasfx "retro(0.98.0 final): n=0 이어도 사람 대기 m 표기" "$GLD/commands/sprint/retro.md" 'm > 0 → add *"(사람 대기 <m>개는 직접 처리)"*'
lacksfx "retro(0.98.0 final): 자식 판정 나열에 mixed 없음" "$GLD/commands/sprint/retro.md" '`no_scan == records`, mixed, `violation`'

# 0.98.1 — PR 목록 절단 시 완전성 판정 · 같은 저장소 참조만 · CLEANUP 조건
hasfx "daily(0.98.1): PR 출력 둘째 줄 = 창의 최소 PR 번호" "$D98" 'second line = the smallest PR number in'
hasfx "retro(0.98.1): PR 출력 둘째 줄 = 창의 최소 PR 번호" "$R98" 'second line = the smallest PR number in the window'
hasfx "daily(0.98.1): PR 은 셋째 줄부터" "$D98" 'then one filtered PR per line from the third line on:'
hasfx "retro(0.98.1): PR 은 셋째 줄부터" "$R98" 'then one filtered PR per line from the third line on:'
lacksfx "daily(0.98.1): 옛 출력 형태(첫 줄 다음 바로 PR) 제거" "$D98" 'first line = the total PR count, then one'
lacksfx "retro(0.98.1): 옛 출력 형태(첫 줄 다음 바로 PR) 제거" "$R98" 'first line = the total PR count, then one'
hasfx "daily(0.98.1): 완전성 판정 — 둘째 줄 < 최소(첫 줄)" "$D98" 'First line == the limit → **second line < the smallest number'
hasfx "daily(0.98.1): 완전성 판정 — 재조회 없음" "$D98" 'among the members and the children of S → complete; do not re-read** (at 200 too'
hasfx "retro(0.98.1): 완전성 판정 — 재조회 없음" "$R98" 'and the children of S → complete, do not re-read** (at 200 too)'
hasfx "retro(0.98.1): 완전성 판정 실패 → FAIL" "$R98" 'The 완전성 판정 still fails → **stop**: `FAIL: could not read the sprint'"'"'s PRs in full'
hasfx "retro(0.98.1): 전제 — 공유 번호 카운터" "$R98" 'PRs from **one shared counter** (a fork'"'"'s PR too)'
hasfx "retro(0.98.1): 전제 — 생성순 = 번호순" "$R98" 'returns PRs in creation order, newest first (createdAt DESC) = number order, descending'
hasfx "retro(0.98.1): 전제 — 같은 저장소 참조만" "$R98" 'The premise holds **only for same-repo references**'
hasfx "retro(0.98.1): 한계 — 본문 수정·사이드바·이전 Issue 예외" "$R98" 'a later Issue, and an Issue transferred from another repo (it gets a new number) are exceptions'
hasfx "retro(0.98.1): 하한 — 가장 작은 멤버 번호" "$R98" 'The real floor is the smallest **member** number (a child is created after its'
hasfx "retro(0.98.1): 하한 — 오래된 이월 멤버는 500 에서도 FAIL" "$R98" 'a very old carryover member (say #50) leaves even the 500 window'
lacksfx "retro(0.98.1): 옛 '500 넘으면 측정 불가' 문장 제거" "$R98" 'cannot be measured here yet'
hasfx "retro(0.98.1): 500 넘는 저장소도 측정 가능" "$R98" 'A repo past 500 PRs **can** be measured now'
hasfx "retro(0.98.1): CLEANUP 조건 — Phase 1 완전성 판정 실패" "$R98" 'in CLEANUP, when Phase 1'"'"'s 완전성 판정 fails (the PR list is not complete even at 500), look up each member'
lacksfx "retro(0.98.1): 옛 CLEANUP 조건(limit 와 같음) 제거" "$R98" 'when the PR list still equals the limit'
hasfx "retro(0.98.1): Phase 7 자식 CLEANUP 조건" "$R98" 'In CLEANUP when Phase 1'"'"'s 완전성 판정 fails, the children'"'"'s PRs'
lacksfx "retro(0.98.1): 옛 Phase 7 truncated 조건 제거" "$R98" 'In CLEANUP with a truncated PR list'
SAMEREPO='[.closingIssuesReferences[]? | select(.repository.owner.login == "<owner>" and .repository.name == "<repo>") | .number]'
hasfx "daily(0.98.1): PR 호출 — 같은 저장소 참조만" "$D98" "$SAMEREPO"
hasfx "retro(0.98.1): PR 호출 — 같은 저장소 참조만" "$R98" "$SAMEREPO"
hasfx "retro(0.98.1): Phase 7 확인 호출 — 같은 저장소 참조만" "$R98" 'closes: ([.closingIssuesReferences[] | select(.repository.owner.login == "<owner>" and .repository.name == "<repo>") | .number] + ['
lacksfx "daily(0.98.1): 옛 번호만 비교 제거" "$D98" '[.closingIssuesReferences[]?.number]'
lacksfx "retro(0.98.1): 옛 번호만 비교 제거(Phase 1)" "$R98" '[.closingIssuesReferences[]?.number]'
lacksfx "retro(0.98.1): 옛 번호만 비교 제거(Phase 7)" "$R98" 'closes: ([.closingIssuesReferences[].number]'
hasfx "daily(0.98.1): Gather 재조회는 완전성 판정 실패 때만" "$D98" 'for the PR list, only when its 완전성 판정 fails'
hasfx "daily(0.98.1): Hard rules 재조회는 완전성 판정 실패 때만" "$D98" 'only when the PR list'"'"'s 완전성 판정 fails at 200, the PR'
hasfx "daily(0.98.1): 판단 불가는 완전성 판정 실패" "$D98" 'When step 3'"'"'s 완전성 판정 fails at 500'
lacksfx "daily(0.98.1): 옛 'still truncated at 500' 제거" "$D98" 'still truncated at 500'
lacksfx "daily(0.98.1): 옛 '500건에서 잘려' 판단 불가 문구 제거" "$D98" 'PR 목록이 500건에서 잘려'

hasfx "retro(0.98.1 cr): 완전성 비교 방향" "$GLD/commands/sprint/retro.md" '**second line < the smallest number among the members'

# 0.98.2 (1차) — 보안 문제와 run 이 멈추는 문제 (design 20)
P2_RUN="$GLD/commands/sprint/run.md"; P2_PLAN="$GLD/commands/sprint/plan.md"; P2_DAILY="$GLD/commands/sprint/daily.md"
P2_RETRO="$GLD/commands/sprint/retro.md"; P2_DEV="$GLD/commands/dev.md"; P2_HO="$GLD/commands/atoms/_handoff.md"
P2_BR="$GLD/commands/atoms/_bash_rules.md"; P2_INIT="$GLD/commands/init.md"
# S1 — init 의 dismissed.md 형식
hasfx "init(0.98.2 S1): dismissed.md 형식은 백틱 경로" "$P2_INIT" '`` - `<path/pattern>` — <reason> `` (backticks recommended, optional)'
hasfx "init(0.98.2 S1): 형식 줄은 불릿이 아닌 > 인용·문장" "$P2_INIT" 'as a `>` quote or a plain sentence — never as a bullet'
lacksfx "init(0.98.2 S1): 옛 백틱 없는 형식 제거" "$P2_INIT" '(header only; `- <path/pattern> — <reason>` downgrades'
# S3 — gh auth status 로만 판정, 값 출력 금지
hasfx "run(0.98.2 S3): GH_TOKEN 확인은 창과 무관하게 항상, 정확히 gh auth status" "$P2_RUN" '**Always — window or not — check which GitHub credential the supervisor will inherit: `gh auth
status`, its own Bash call, exactly that command.**'
hasfx "run(0.98.2 S3): 출력 텍스트로 판정 (종료 코드 아님)" "$P2_RUN" 'Judge by the **output text, not the exit code** — one expired keyring
account alone makes it exit 1:'
hasfx "run(0.98.2 S3): X (GH_TOKEN) 은 모든 run 에서 중단" "$P2_RUN" '**Stop before the run, in every run**'
hasfx "run(0.98.2 S3): 창 경고+질문은 ✓ (GH_TOKEN) 일 때만" "$P2_RUN" '3. **`GH_TOKEN` + a window → warn and ask** (`✓ … (GH_TOKEN)` in the `gh auth status` check above).'
hasfx "run(0.98.2 S3): ✓ … (GH_TOKEN) → 사용 중" "$P2_RUN" '- a line `✓ … (GH_TOKEN)` → `GH_TOKEN` is in use'
hasfx "run(0.98.2 S3): X … (GH_TOKEN) → 무효, 갱신·삭제 후 세션 재시작" "$P2_RUN" '"GH_TOKEN 을 설정한 곳(셸 프로필·Claude settings 의 env)에서
  갱신하거나 지운 뒤 Claude 세션을 다시 시작하세요"'
hasfx "run(0.98.2 S3): GITHUB_TOKEN 도 keyring 을 덮어씀" "$P2_RUN" '`(GITHUB_TOKEN)` overrides the keyring the same way'
hasfx "run(0.98.2 S3): 값 출력 금지 문장" "$P2_RUN" '**Never `gh auth status --show-token`, `gh auth token`, or a command that prints a secret
environment variable'"'"'s value (`env`, `printenv GH_TOKEN`, `echo`)**'
hasfx "_bash_rules(0.98.2 S3): 비밀 값 출력 금지 일반 규칙" "$P2_BR" '비밀(토큰·키) 환경 변수의 값은 출력하지 않는다 — 존재·출처는 그 도구의 상태 명령으로'
hasfx "_bash_rules(0.98.2 S3): 비밀 아닌 printenv 는 그대로" "$P2_BR" '`printenv` of a variable that is not a secret (e.g. `printenv BASH_MAX_TIMEOUT_MS`) stays as it is.'
ST_OUT="$("$PY" - "$GLD/commands/atoms/scan_transcript.py" <<'PYX'
import importlib.util, sys
sys.dont_write_bytecode = True
s = importlib.util.spec_from_file_location("st", sys.argv[1]); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
print(bool(m.GUILD_MANDATED_RE.match("gh auth status")), bool(m.GUILD_MANDATED_RE.match("gh auth status --show-token")),
      bool(m.REDISCOVERY_RE.match("gh auth switch")))
PYX
)"
[ "$ST_OUT" = "True False True" ] && ok "scan_transcript(0.98.2 S3): run 의 gh auth status 는 Guild 지정 호출 (재탐색 아님), 다른 형태는 그대로" \
  || bad "scan_transcript(0.98.2 S3): gh auth status 분류" "True False True" "$ST_OUT"
# 같은 판정을 실제 분류 경로로: 세션 4개에 반복된 `gh auth status`(지정 호출)와 대조군 `gh auth switch`
ST_HOME="$(mktemp -d)"; mkdir -p "$ST_HOME/.claude/projects/p"
for i in 1 2 3 4; do
  printf '%s\n' '{"cwd":"/st/repo","type":"user","message":{"content":"hi"}}' \
    '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"gh auth status"}},{"type":"tool_use","name":"Bash","input":{"command":"gh auth switch"}}]}}' \
    > "$ST_HOME/.claude/projects/p/s$i.jsonl"
done
ST_RUN="$(HOME="$ST_HOME" "$PY" -B "$GLD/commands/atoms/scan_transcript.py" --repo-cwd /st/repo 2>/dev/null | "$PY" -c '
import json, sys
t = sys.stdin.read(); d = json.loads(t.split(">>> RESULT <<<", 1)[1])
sig = d.get("signals") or []
st = [s["class"] for s in sig if s.get("summary", "").endswith("gh auth status")]
sw = [s["class"] for s in sig if s.get("summary", "").endswith("gh auth switch")]
print("status=%s switch=%s" % (",".join(st) or "none", ",".join(sw) or "none"))')"
rm -rf "$ST_HOME"
[ "$ST_RUN" = "status=none switch=rediscovery" ] && ok "scan_transcript(0.98.2 S3): 반복된 gh auth status 는 마찰 신호가 아님 (실제 분류 경로; 대조군 gh auth switch 는 rediscovery)" \
  || bad "scan_transcript(0.98.2 S3): 실제 분류 경로" "status=none switch=rediscovery" "$ST_RUN"
# S4 — BODIES 는 명령으로만
hasfx "plan(0.98.2 S4): BODIES 를 파일로 넘기지 않음" "$P2_PLAN" '⚠ **BODIES 는 명령으로만 넘긴다 — 본문을 파일로 저장해 넘기지 마라(공유 /tmp·저장소 안 모두).**'
hasfx "plan(0.98.2 S4): 도구가 옮긴 파일은 Read 로 끝까지" "$P2_PLAN" '도구 출력이 파일로 넘어가는 것은 도구의 동작이며 Read 의 offset/limit 으로 끝까지 읽는다.'
# R1 — 사람이 머지한 자식 정리
hasfx "dev(0.98.2 R1): 자식 발견 쿼리에 state" "$P2_DEV" '--json number,title,body,labels,state --jq '"'"'[.[] | select((.body // "") | test("Parent Issue: #<parent>([^0-9]|$)"))] | sort_by(.number) | .[] | {number, title, state, labels: [.labels[].name]}'"'"
hasfx "dev(0.98.2 R1): CLOSED 자식만 PR 조회" "$P2_DEV" 'whose `state` is **`CLOSED`** — only those; an open child is step 2'"'"'s'
hasfx "dev(0.98.2 R1): closedByPullRequestsReferences 명령" "$P2_DEV" 'gh issue view <c> --json closedByPullRequestsReferences'
hasfx "dev(0.98.2 R1): 같은 저장소 PR 마다 state,mergedAt" "$P2_DEV" 'gh pr view <p> --json state,mergedAt'
hasfx "dev(0.98.2 R1): 실제로 있는 라벨만 제거" "$P2_DEV" 'removing only the labels the discovery output **actually shows** on it'
hasfx "dev(0.98.2 R1): 부모 기록 한 줄" "$P2_DEV" '`자식 #c 는 PR #p 로 머지되어 done 으로 정리함`'
hasfx "dev(0.98.2 R1): MERGED 없으면 1b 는 아무것도 안 함 (step 2 가 순서대로 멈춤)" "$P2_DEV" '**No `MERGED` PR** (a human closed it without merging) → no action here — step 2 reaches it in order and stops on it as today.'
lacksfx "dev(0.98.2 R1): 1b 에서 조기 중단하지 않음" "$P2_DEV" 'stop here as today: report the child'
hasfx "dev(0.98.2 R1): 1b 정리 자식은 step 2 에서 done 으로" "$P2_DEV" 'A child cleaned up here counts as `guild:done` in step 2'
hasfx "dev(0.98.2 R1): revert·스택 한계" "$P2_DEV" 'A **stacked** child PR does not close its Issue, so an `OPEN` child whose PR is `MERGED` but which is not `guild:done` is not handled here'
hasfx "dev(0.98.2 R1): Phase 2c 사람 머지 표기" "$P2_DEV" '`test 출력 없음 — 사람 머지`'
hasfx "_handoff(0.98.2 R1): guild:done 예외" "$P2_HO" '자식이 같은 저장소 PR 의 머지로 사람에 의해 닫히면 dev Phase 2b 가 done 으로 정리한다(QA 를 거치지 않음)'
hasfx "_handoff(0.98.2 R1): OK DONE 행의 예외" "$P2_HO" 'The one `guild:done` that `OK DONE` does not set'
hasfx "_handoff(0.98.2 R1): needs-human 제거 지점 = forward-progress" "$P2_HO" 'is a forward-progress transition of this first kind — the merge is the evidence the pause was resolved.'
hasfx "daily(0.98.2 R1): 머지됐지만 done 아닌 자식 대체 줄" "$P2_DAILY" '`#e 자식 #c 는 머지됐지만 done 이 아닙니다 — 다음 run 이 정리합니다(할 일 없음)`'
hasfx "daily(0.98.2 R1): 대체 — needs-human 줄 대신" "$P2_DAILY" 'gets, **instead of** that line:'
hasfx "daily(0.98.2 R1): 사람 대기 정의에서 제외" "$P2_DAILY" '**단 `CLOSED` 이면서 같은 저장소 `MERGED` PR'
hasfx "daily(0.98.2 R1): via: branch 는 근거 아님" "$P2_DAILY" '(a `via: branch` row is not evidence — `dev` judges by `closedByPullRequestsReferences`, so the'
hasfx "retro(0.98.2 R1): 사람 대기 횟수는 그대로 셈" "$P2_RETRO" '⚠ 도달 수이므로 그 정의의 제외(`CLOSED` + 같은 저장소 `MERGED` PR 자식)는 여기 적용하지 않는다 — 사람이 머지한 것도 개입이다. 제외는 아래 현재 대기 목록에만'
hasfx "plan(0.98.2 R1): blocked_children — CLOSED+needs-human 자식만 PR 판정" "$P2_PLAN" 'for each `guild:needs-human` child that is closed, run
  `gh issue view <c> --json closedByPullRequestsReferences`'
hasfx "plan(0.98.2 R1): blocked_children — MERGED 제외" "$P2_PLAN" 'A `MERGED` one → not blocked (`dev` Phase 2b cleans the child up to `guild:done`'
hasfx "plan(0.98.2 R1): closed-not-done 머지됨 표시" "$P2_PLAN" '`#c(머지됨 — run 이 정리)`'
hasfx "plan(0.98.2 R1 r2): 머지됨 자식은 읽지 않고 readiness·sizing·count 에서 제외" "$P2_PLAN" 'it is not read,
  and it is excluded from readiness, sizing and the `remaining`/`epic ×<k>` counts.'
hasfx "plan(0.98.2 R1 r2): remaining k 에 머지됨 자식 미포함" "$P2_PLAN" 'A child marked `(머지됨 — run 이 정리)` (below) is **not counted in `k`**'
hasfx "plan(0.98.2 R1 r2): 에픽 판정(막힘/구체화)에서 머지됨 자식 제외" "$P2_PLAN" '**Except a child marked
`(머지됨 — run 이 정리)`**: it is not read and is no remaining child for this judgment'
hasfx "plan(0.98.2 R1 r2): PO 프롬프트 — 머지됨 자식 읽지 않음" "$P2_PLAN" 'a `closed-not-done` one you read with `gh issue view <c> --json body` — **except one marked `(머지됨 — run 이 정리)`: do not read it, and leave it out of the readiness judgment**'
hasfx "plan(0.98.2 R1 r2): CANDIDATES 의 closed-not-done 필드가 표시를 실음" "$P2_PLAN" '· closed-not-done <#c…|—> · 바닥 선행 미완 <#d…|—>)` — in `closed-not-done`, a child a same-repo `MERGED` PR closed is written `#c(머지됨 — run 이 정리)` (Phase 1)'
lacksfx "plan(0.98.2 R1 r2): 표시 없이 모든 closed-not-done 을 읽으라는 옛 문구 없음" "$P2_PLAN" 'a `closed-not-done` child'"'"'s body via `gh issue view <c> --json body`.'
TLN="$(grep -cF 'a `closed-not-done` child'"'"'s body via `gh issue view <c> --json body` — **except one marked `(머지됨 — run 이 정리)`: do not read it, do not size it, and do not count it in `epic ×<k>`**' "$P2_PLAN")"
[ "$TLN" = 2 ] && ok "plan(0.98.2 R1 r2): tech-lead 프롬프트 2곳(선택·리팩터 슬롯) 모두 머지됨 자식 제외" || bad "plan(0.98.2 R1 r2): tech-lead 프롬프트 2곳" "2" "$TLN"
# R2 — split 부모 PAUSED
hasfx "run(0.98.2 R2): guild:children 행의 PAUSED 경로" "$P2_RUN" '**The one exception — PAUSED** (0.98.2 R2): when, after a pass, the parent'"'"'s smallest outstanding child'
hasfx "run(0.98.2 R2): 하류 dep-needs-human" "$P2_RUN" 'the parent goes into `dag/paused.txt` so its dependants block as `dep-needs-human`'
hasfx "run(0.98.2 R2): paused.txt 재실행 초기화" "$P2_RUN" "python3 -c \"open('.claude/guild/.sprint-logs/<tracker>/dag/paused.txt','w').close()\""
hasfx "run(0.98.2 R2 r2): failed.txt 설명이 '두 누적 파일 중 하나'" "$P2_RUN" '`failed.txt` is the supervisor'"'"'s **working state for one run, not a record**, and it is one
   of the two dag files that **accumulate across runs** (the other is `paused.txt`, below)'
lacksfx "run(0.98.2 R2 r2): 옛 'the one dag file' 문구 없음" "$P2_RUN" 'and it is the one
   dag file that **accumulates across runs**'
PSO="$(awk '/the retry counts live in the run marker\./{a=NR} /Then truncate `paused.txt` the same way/{b=NR} END{print (a && b && a < b) ? "ok" : "bad"}' "$P2_RUN")"
[ "$PSO" = ok ] && ok "run(0.98.2 R2 r2): paused.txt 문단은 failed.txt 설명 뒤" || bad "run(0.98.2 R2 r2): paused.txt 문단 위치" "after failed.txt paragraphs" "$PSO"
hasfx "run(0.98.2 R2): 'No other dag file' 문장 갱신" "$P2_RUN" '⚠ **No other dag file needs this** — `failed.txt` and `paused.txt` are the two that'
hasfx "run(0.98.2 R2): Do not hand it to the human 의 예외 (별도 문장)" "$P2_RUN" 'exactly as they would outside a sprint. **The one exception — PAUSED**'
hasfx "run(0.98.2 R2): 예외 근거 문장" "$P2_RUN" '`dep-needs-human`. 단 가장 작은 대기 자식이 needs-human 이면 PAUSED — 근거는 completion 의 `#e (child #c)`(라벨은 `guild:children` 그대로).'
hasfx "run(0.98.2 R2): label-truthful 보고의 예외 (별도 문장)" "$P2_RUN" 'Report such a member as paused on `#c`, not by the parent'"'"'s label.'
lacksfx "run(0.98.2 R2): 영어 문장 중간에 끼운 예외 없음" "$P2_RUN" 'Do **not** hand it to the human — 단'
hasfx "retro(0.98.2 R2): 분할 일시정지 예외" "$P2_RETRO" '단 가장 작은 대기 자식이 needs-human 이면 PAUSED — 근거는 completion 의 `#e (child #c)`(라벨은 `guild:children` 그대로)'
hasfx "daily(0.98.2 R2): paused_issues 의 #e (child #c)" "$P2_DAILY" '`#e (child #c)` 는 자식이 needs-human — 부모 라벨은 `guild:children`'
hasfx "plan(0.98.2 R2): 예고 문구 — 일시정지(재시도 없음)" "$P2_PLAN" 'the supervisor pauses the epic (`#e (child #c)`, no
  re-try, not `split-stalled`)'
lacksfx "plan(0.98.2 R2): 옛 예고 문구 제거" "$P2_PLAN" 'unattended it may re-try and end the epic `split-stalled`'
lacksfx "plan(0.98.2 R2): 옛 Add 경고 제거" "$P2_PLAN" '몇 번 다시 시도한 뒤 split-stalled(미완)로 끝날 수 있습니다'
hascode "supervisor(0.98.2 R2): 부모 재호출 전 새 함수" "$GLD/templates/sprint-supervisor.sh" 'SPLIT_HEAD="$(split_head_needs_human "$ISSUE")"'
hascode "supervisor(0.98.2 R2): paused.txt 쓰기는 별도 함수" "$GLD/templates/sprint-supervisor.sh" 'record_paused "$ISSUE"'
hascode "supervisor(0.98.2 R2): paused.txt 없으면 만든다" "$GLD/templates/sprint-supervisor.sh" '[ -f "$D/paused.txt" ] || : > "$D/paused.txt"'
hasfx "supervisor(0.98.2 R2): children 일 때만 needs-human" "$GLD/templates/sprint-supervisor.sh" 'if line.isdigit() and terminal.get(line) == "children":'
# R3 — plan 의 중앙 관리 파일 정의 옆
hasfx "plan(0.98.2 R3): 실행 중 변경은 커밋 게이트가 알림" "$P2_PLAN" '실행 중 변경은 커밋 게이트가 정보 경고로 알린다'

echo "결과: PASS=$PASS FAIL=$FAIL"

# ⚠ A FLOOR ON THE CHECK COUNT. This file is a long list of `hasfx`/`lacksfx` calls, and an
# unterminated quote in any one of them swallows every line after it into a string — the suite
# then reports FAIL=0 over silently skipped checks. That happened: PASS fell from 62 to 38 with
# zero failures, which is the exact "green over a hole" shape these tests exist to prevent.
# Raise the floor whenever checks are added on purpose.
BOARD_MIN_CHECKS=1595   # ⚠ 실측 PASS 와 같게 유지한다 (04-sprint-window-tests.md T9)
if [ "$((PASS + FAIL))" -lt "$BOARD_MIN_CHECKS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${BOARD_MIN_CHECKS}건) —"
  echo "      어딘가에서 인용이 닫히지 않아 이후 검사가 문자열로 삼켜졌을 가능성이 큽니다."
  exit 1
fi
[ "$FAIL" -eq 0 ]
