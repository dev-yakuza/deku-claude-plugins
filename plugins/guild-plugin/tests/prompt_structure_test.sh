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
for T in $(grep -oE 'board_col "\$ISSUE" [a-z_]+ [a-z:-]+' "$TPL" | awk '{print $3}' | sort -u) \
         $(grep -oE 'board_col "\$BOARD_BI" [a-z_]+ [a-z:-]+' "$TPL" | awk '{print $3}' | sort -u); do
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
echo "결과: PASS=$PASS FAIL=$FAIL"

# ⚠ A FLOOR ON THE CHECK COUNT. This file is a long list of `hasfx`/`lacksfx` calls, and an
# unterminated quote in any one of them swallows every line after it into a string — the suite
# then reports FAIL=0 over silently skipped checks. That happened: PASS fell from 62 to 38 with
# zero failures, which is the exact "green over a hole" shape these tests exist to prevent.
# Raise the floor whenever checks are added on purpose.
BOARD_MIN_CHECKS=75
if [ "$((PASS + FAIL))" -lt "$BOARD_MIN_CHECKS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${BOARD_MIN_CHECKS}건) —"
  echo "      어딘가에서 인용이 닫히지 않아 이후 검사가 문자열로 삼켜졌을 가능성이 큽니다."
  exit 1
fi
[ "$FAIL" -eq 0 ]
