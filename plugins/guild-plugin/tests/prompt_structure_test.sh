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
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
