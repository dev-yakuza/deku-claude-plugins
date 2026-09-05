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
"$PY" -c "pass" >/dev/null 2>&1 || { echo "SKIP: $PY is not usable — this suite is python-based" >&2; exit 0; }
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s (expected %s, got %s)\n' "$1" "$2" "$3"; }

echo ""
echo "== 2. 감사자 캘리브레이션 코어 동일성 =="

OUT="$("$PY" - "$SPINE" "$REVIEW" <<'PYX'
import re, sys

OPEN  = '<!-- guild:severity-core -->'
CLOSE = '<!-- /guild:severity-core -->'
PREFIX = re.compile(r'^  > ?')

def extract(path):
    """Return (opens, closes, core_lines_or_None) for one file."""
    lines = open(path, encoding='utf-8').read().split('\n')
    opens  = [i for i, l in enumerate(lines) if OPEN in l]
    closes = [i for i, l in enumerate(lines) if CLOSE in l]
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
hasfx "board.md: Phase S 가 그것을 갱신한다" "$BOARD" "Write the outcome to `config.sprint.board.column_by_verified`"
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

# 11. run.md — 보드 값은 렌더 토큰이 아니라 **데이터 파일**이다. 이 클래스가 세 번 나왔다:
#     소스 보간(실행됨) → 인용 heredoc(개행이 탈출) → 데이터 파일.
lacksfx "template: 보드 렌더 토큰이 남아 있지 않다" "$TPL" "<BOARD_NUMBER>"
lacksfx "run.md: 폐기된 토큰 표가 남아 있지 않다" "$RUNMD2" "<BOARD_COL_READY>"
hasfx "run.md: 보드 설정 파일을 쓰는 단계가 있다" "$RUNMD2" ".gld-sprint-<tracker>.board"
hasfx "run.md: 값을 인용하지 말라고 말한다" "$RUNMD2" "Do not quote them"
hascode "template: 설정 파일을 읽는다" "$TPL" 'BOARD_CONF="$HUMAN_REPO/.claude/guild/.gld-sprint-$TRACKER.board"'
# 11a. 보드를 끌 때는 파일을 **지워야** 한다. 안 쓰기만 하면 낡은 파일이 읽혀 보드가 켜진다.
hasfx "run.md: 보드가 null 이면 설정 파일을 지운다" "$RUNMD2" "rm -f .claude/guild/.gld-sprint-<tracker>.board"
# 11b. run.md 가 요구하는 열 개 키와 템플릿의 case 분기가 일치한다 — 한쪽만 늘면 조용히 빈다
BOARD_KEY_MISS=""
for K in number owner field field_needs_human verified_as \
         col_ready col_in_progress col_blocked col_in_review col_done; do
  grep -qF -- "$K=" "$RUNMD2" || BOARD_KEY_MISS="$BOARD_KEY_MISS run.md:$K"
  grep -qE "^ +$K\)" "$TPL"  || BOARD_KEY_MISS="$BOARD_KEY_MISS tpl:$K"
done
if [ -z "$BOARD_KEY_MISS" ]; then
  ok "보드 설정 키 10개가 run.md 와 템플릿 양쪽에 있다"
else
  bad "보드 설정 키 불일치" "all present" "missing:$BOARD_KEY_MISS"
fi

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
CONFMD="$GLD/commands/config.md"
INITMD="$GLD/commands/init.md"

# ── 19. 상태 토큰이 다섯 파일에 있고, plan.md 는 인접성 스코프 안에 있는가 ────────
# ⚠ 명세는 **여섯** 파일(+ `design/guild/02-sprint.md`)을 요구하지만 `design/` 는 이 플러그인이
#   배포하는 트리가 아니고 리포에서 gitignore 된다 — 여기서 단정할 수 있는 것은 다섯이다.
#   여섯째는 설계 문서 자체의 정정이고, 검사할 파일이 없다는 사실을 여기 적어 둔다.
for F in "$HANDOFF" "$DAILY" "$RETRO" "$PLAN" "$BOARD"; do
  hasfx "창 토큰이 $(basename "$F") 에 열거돼 있다" "$F" "waiting-for-window-"
done
# ⚠ 인접성 스코프. 파일 전체 grep 이면 다른 언급(예: 거부 문구)이 남아 통과하고, `plan.md:44`
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
  bad "template: :151 주석의 주장" "$IFC"
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
MISSING=""
for c in $(sed -n 's/^- Valid commands: //p' "$SKILLMD" | tr -d '`' | tr ',' ' '); do
  [ -f "$GLD/commands/$c.md" ] || MISSING="$MISSING $c"
done
if [ -z "$MISSING" ]; then ok "SKILL.md: valid-command 가 전부 commands/*.md 로 해석된다"
else bad "SKILL.md: valid-command 가 전부 해석된다" "모두 존재" "없음:$MISSING"; fi

# (b) atom 열거 줄의 경로가 전부 실재하는가. 줄 번호로 고정하지 않는다 — C 가 민다.
BADATOM=""
for a in $(grep -o 'commands/atoms/_[a-z_]*\.md' "$SKILLMD" | sort -u); do
  [ -f "$GLD/$a" ] || BADATOM="$BADATOM $a"
done
if [ -z "$BADATOM" ]; then ok "SKILL.md: atom 경로가 전부 resolve 된다"
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
EXPECT = {"commands/test.md":1, "commands/design.md":3, "commands/qa.md":2,
          "commands/analyze.md":1, "commands/atoms/_execute_spine.md":2,
          "commands/plan.md":2, "commands/sprint/plan.md":1}
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
for rel, want in EXPECT.items():
    body = open(os.path.join(gld, rel), encoding="utf-8").read().split("\n")
    opens = [n for n, l in enumerate(body) if strip(l) == OPEN]
    closes = [n for n, l in enumerate(body) if strip(l) == CLOSE]
    if len(opens) != want or len(closes) != want:
        problems.append("%s: %d pairs, want %d" % (rel, min(len(opens), len(closes)), want))
        continue
    for a, b in zip(opens, closes):
        total += 1
        if [strip(x) for x in body[a+1:b]] != canon:
            problems.append("%s:%d drifted from canonical" % (rel, a+2))
names = re.findall(r"`([A-Z_]+)(?::|`)", canon[0]) if canon else []
tbl = "\n".join(lines[:o])
missing = [n for n in set(names) if "`%s" % n not in tbl]
if missing:
    problems.append("enum missing from Section C table: %s" % ",".join(sorted(missing)))
print("OK %d" % total if not problems else "PROBLEMS " + " | ".join(problems))
PYC
OUTC="$("$PY" "$WORK3/contract.py" "$GLD")"
case "$OUTC" in
  "OK 12") ok "result-contract: 사본 12개가 정본과 바이트 동일하고 개수가 맞다" ;;
  OK*)     bad "result-contract: 사본 12개" "OK 12" "$OUTC" ;;
  *)       bad "result-contract: 사본이 정본과 동일" "OK 12" "$OUTC" ;;
esac

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

# D 폐기가 기록으로 남아 있는가 — 다음 사람이 같은 가설을 다시 세우지 않도록.
hasfx "_bash_rules.md: 무인 완화 폐기 사유가 기록돼 있다" "$GLD/commands/atoms/_bash_rules.md" 'Asked and answered: the atomic rule is NOT relaxed'
# ── 39. enum 축소 문장이 Section C 표와 어긋나지 않는가 (회귀 검사) ──────────
# B 는 12곳의 계약 문장을 펜스로 갈아끼웠다. 섹션 37 은 펜스 *사본* 을 본다. 이 검사는 펜스
# *밖* 에 남는 사이트별 축소 문장을 본다 — 어떤 스폰이 5개 중 3개만 허용한다고 다시 적은 줄들.
# 오늘 7곳이 전부 통과하는 것이 정상이다. 이것은 모양 검사가 아니라 회귀 검사이고, Section C
# 표에 상태가 추가·개명됐는데 사본이 안 따라올 때 발화한다.
# ⚠ 공집합도 부분집합이다 — 축소 문장이 통째로 지워지면(B 가 만들 수 있는 사고) 빈 집합이
# 그린을 찍는다. 그래서 사이트 수 바닥선을 함께 둔다.
cat > "$WORK3/enum.py" <<'PYE'
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
if sites < 7:
    problems.append("only %d reduction sites, want >= 7 — a narrowing sentence was dropped" % sites)
print("OK %d" % sites if not problems else "PROBLEMS " + " | ".join(problems))
PYE
OUTE="$("$PY" "$WORK3/enum.py" "$GLD")"
case "$OUTE" in
  OK*) ok "enum 축소 문장이 Section C 표의 부분집합이고 사이트가 남아 있다 (${OUTE#OK })" ;;
  *)   bad "enum 축소 문장이 Section C 표와 정합" "OK >=7" "$OUTE" ;;
esac
echo "결과: PASS=$PASS FAIL=$FAIL"

# ⚠ A FLOOR ON THE CHECK COUNT. This file is a long list of `hasfx`/`lacksfx` calls, and an
# unterminated quote in any one of them swallows every line after it into a string — the suite
# then reports FAIL=0 over silently skipped checks. That happened: PASS fell from 62 to 38 with
# zero failures, which is the exact "green over a hole" shape these tests exist to prevent.
# Raise the floor whenever checks are added on purpose.
BOARD_MIN_CHECKS=203   # ⚠ 실측 PASS 와 같게 유지한다 (04-sprint-window-tests.md T9)
if [ "$((PASS + FAIL))" -lt "$BOARD_MIN_CHECKS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${BOARD_MIN_CHECKS}건) —"
  echo "      어딘가에서 인용이 닫히지 않아 이후 검사가 문자열로 삼켜졌을 가능성이 큽니다."
  exit 1
fi
[ "$FAIL" -eq 0 ]
