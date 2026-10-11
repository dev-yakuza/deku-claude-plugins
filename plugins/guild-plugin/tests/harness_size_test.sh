#!/usr/bin/env bash
# Verification for `harness_size.py` — which evolve-grown files are over their size bar
# (design: design/guild/10-ledger-hygiene.md D10/D11 · callers: evolve.md Phase 3, audit.md B/C).
#
# The bars are what evolve acts on, so each is pinned at its edge: exactly at the bar is within
# it, one over is reported. Output order is furthest-over first — evolve takes only the head.
#
# Usage: bash plugins/guild-plugin/tests/harness_size_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SIZE="$HERE/../skills/gld/commands/atoms/harness_size.py"
[ -f "$SIZE" ] || { echo "missing: $SIZE" >&2; exit 1; }
PY="${PY:-python3}"
WORK="$(mktemp -d)" || { echo "mktemp -d failed" >&2; exit 1; }
[ -n "$WORK" ] && [ -d "$WORK" ] || { echo "mktemp -d gave no directory" >&2; exit 1; }
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
export PYTHONDONTWRITEBYTECODE=1

gld_skip() { echo "SKIP: $1" >&2; [ "${GLD_ALLOW_SKIP:-0}" = 1 ] && exit 0; \
            echo "FAIL  스킵은 통과가 아닙니다 — GLD_ALLOW_SKIP=1 로 명시하십시오." >&2; exit 1; }
"$PY" -c "pass" >/dev/null 2>&1 || gld_skip "$PY is not usable — this suite is python-based"
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s — %s\n' "$1" "$2"; }
eq()  { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "got [$2] want [$3]"; fi; }
has() { case "$2" in *"$3"*) ok "$1" ;; *) bad "$1" "[$3] not in [$2]" ;; esac; }
lacks() { case "$2" in *"$3"*) bad "$1" "[$3] unexpectedly in [$2]" ;; *) ok "$1" ;; esac; }

S() { "$PY" "$SIZE" --root "$R" "$@"; }
R="$WORK/repo"; mkdir -p "$R/.git" "$R/.claude/agents" "$R/.claude/guild/knowledge/facts/ui"
# agent <role> <bullet-length…> — a persona with a central region and one habit per length.
agent() {
  "$PY" - "$R/.claude/agents/$1.md" "${@:2}" <<'PYA'
import sys
path, lens = sys.argv[1], [int(x) for x in sys.argv[2:]]
body = "---\nname: x\n---\n<!-- guild:persona:start -->\n- 중앙 불릿 " + "중" * 3000 + "\n<!-- guild:persona:end -->\n\n## 역할 습관\n<!-- guild:persona:habits -->\n"
# a bullet's length includes its "- ", so n text characters measure n + 2
body += "".join("- " + "가" * n + "\n" for n in lens)
open(path, "w", encoding="utf-8").write(body)
PYA
}
chars() { "$PY" -c 'import sys; open(sys.argv[1], "w", encoding="utf-8").write("나" * int(sys.argv[2]))' "$1" "$2"; }

echo "== nothing to report"
eq "an empty repo is within bars" "$(S)" "harness: within bars"
S >/dev/null; eq "exit 0" "$?" 0
agent quiet 100 100
eq "two short habits are within bars" "$(S)" "harness: within bars"

echo "== habit bars at their edges"
agent five 10 10 10 10 10
eq "exactly 5 habits is within the bar" "$(S)" "harness: within bars"
agent six 10 10 10 10 10 10
has "6 habits is reported" "$(S)" "habits six: count=6"
rm "$R/.claude/agents/six.md"
agent long800 798
eq "a habit of 800 characters is within the bar" "$(S)" "harness: within bars"
agent long801 799
has "a habit of 801 characters is reported" "$(S)" "habits long801: count=1 chars=801 longest=801"
rm "$R/.claude/agents/long801.md"
agent total 598 598 598
eq "3 habits of 600 = 1800 characters is within the bar" "$(S)" "harness: within bars"
agent total2 698 698 698
has "3 habits of 700 = 2100 characters is reported" "$(S)" "habits total2: count=3 chars=2100"
lacks "the central region never counts toward habits" "$(S)" "habits quiet"
rm "$R/.claude/agents/total2.md"

echo "== a habit's continuation lines belong to it"
"$PY" - "$R/.claude/agents/cont.md" <<'PYC'
import sys
open(sys.argv[1], "w", encoding="utf-8").write(
    "## 역할 습관\n<!-- guild:persona:habits -->\n- " + "가" * 500 + "\n  " + "나" * 400 + "\n\n## 다음 절\n- " + "다" * 900 + "\n")
PYC
out="$(S)"
has "a wrapped habit is measured whole" "$out" "habits cont: count=1"
lacks "a later section's bullets are not habits" "$out" "longest=900"
rm "$R/.claude/agents/cont.md"

echo "== a habits section ends at the next heading, a comment, and skips fences"
"$PY" - "$R/.claude/agents/notes.md" <<'PYN'
import sys
open(sys.argv[1], "w", encoding="utf-8").write(
    "## 역할 습관\n<!-- guild:persona:habits -->\n- one habit\n```text\n- fenced example 1\n- fenced example 2\n- fenced example 3\n- fenced example 4\n- fenced example 5\n```\n## 다음 절\n- " + "가" * 900 + "\n")
PYN
eq "fenced lines and a later level-2 section are not habits" "$(S)" "harness: within bars"
rm "$R/.claude/agents/notes.md"
"$PY" - "$R/.claude/agents/grouped.md" <<'PYG'
import sys
open(sys.argv[1], "w", encoding="utf-8").write(
    "## 역할 습관\n<!-- guild:persona:habits -->\n<!-- init: placeholder note -->\n### 설계\n- a\n- b\n- c\n### 실행\n- d\n- e\n- f\n<!-- guild:persona:end -->\n- not a habit\n")
PYG
has "habits grouped under ### headings, after an init comment, are all counted" "$(S)" "habits grouped: count=6"
rm "$R/.claude/agents/grouped.md"
printf -- '## 역할 습관\n<!-- guild:persona:habits -->\n- a\n<!-- %s -->\n- b\n- c\n- d\n- e\n- f\n' "$("$PY" -c 'print("주"*900)')" > "$R/.claude/agents/commented.md"
has "a comment after a habit is not part of it" "$(S)" "habits commented: count=6 chars=18 longest=3"
rm "$R/.claude/agents/commented.md"
agent grouped 1
rm "$R/.claude/agents/grouped.md"

echo "== a persona without a habits marker"
printf -- '---\nname: old\n---\n- %s\n' "$("$PY" -c 'print("가"*900)')" > "$R/.claude/agents/old.md"
eq "no marker → not measured" "$(S)" "harness: within bars"
rm "$R/.claude/agents/old.md"

echo "== knowledge bars"
chars "$R/.claude/guild/knowledge/index.md" 4000
eq "an index of 4000 characters is within the bar" "$(S)" "harness: within bars"
chars "$R/.claude/guild/knowledge/index.md" 4001
has "an index of 4001 characters is reported" "$(S)" "index: chars=4001 (bar 4000)"
chars "$R/.claude/guild/knowledge/facts/a11y.md" 12000
lacks "a fact of 12000 characters is within the bar" "$(S)" "fact a11y.md"
chars "$R/.claude/guild/knowledge/facts/ui/deep.md" 12001
has "a nested fact over the bar is reported with its path" "$(S)" "fact facts/ui/deep.md: chars=12001 (bar 12000)"
printf 'Hello\n' > "$R/.claude/guild/knowledge/facts/en.md"
"$PY" -c 'open("'"$R"'/.claude/guild/knowledge/facts/bytes.md","w",encoding="utf-8").write("한"*5000)'
lacks "characters, not bytes (5000 Hangul = 15000 bytes)" "$(S)" "bytes.md"

echo "== furthest over first"
agent far 10 10 10 10 10 10 10 10 10 10 10 10 10 10 10   # 15 habits = 3x the count bar
out="$(S)"
eq "the first line is the furthest over" "$(printf '%s\n' "$out" | head -1 | cut -d: -f1)" "habits far"
eq "the last line is the least over (12001/12000 < 4001/4000)" "$(printf '%s\n' "$out" | tail -1 | cut -d: -f1)" "fact facts/ui/deep.md"
eq "three lines reported" "$(printf '%s\n' "$out" | wc -l | tr -d ' ')" 3

echo "== robustness"
printf '\xff\xfe' > "$R/.claude/agents/broken.md"
out="$(S 2>"$WORK/err")"; rc=$?
eq "an unreadable persona does not fail the run" "$rc" 0
has "an unreadable persona is named on stderr" "$(cat "$WORK/err")" "skipped"
lacks "a skipped file never takes one of the measured lines" "$out" "skipped"
rm "$R/.claude/agents/broken.md"
printf -- '## 역할 습관\n<!-- guild:persona:habits -->\n1. a\n2. b\n3. c\n4. d\n5. e\n6. f\n' > "$R/.claude/agents/numbered.md"
has "numbered habits are counted one by one" "$(S)" "habits numbered: count=6"
S extra >/dev/null 2>&1; eq "an unexpected argument exits 64" "$?" 64
mkdir -p "$R/sub"; out="$(cd "$R/sub" && "$PY" "$SIZE")"
has "walks up to the repo root" "$out" "habits far"

PYC="$(find "$HERE/../skills" -name 'harness_size*.pyc' 2>/dev/null)"
[ -z "$PYC" ] && ok "no harness_size .pyc written beside the plugin's scripts" || bad "pycache" "$PYC"

echo
echo "harness_size: $PASS passed, $FAIL failed"
# ⚠ Keep equal to the measured PASS count; raise it only when checks are added on purpose. A
#   quote that swallows the rest of the file runs fewer checks and still ends green otherwise.
SIZE_MIN_CHECKS=31
if [ "$((PASS + FAIL))" -lt "$SIZE_MIN_CHECKS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${SIZE_MIN_CHECKS}건)."
  exit 1
fi
[ "$FAIL" -eq 0 ]
