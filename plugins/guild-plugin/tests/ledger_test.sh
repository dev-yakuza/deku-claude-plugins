#!/usr/bin/env bash
# Verification for `ledger.py` — reading and compacting the evolve ledger
# (design: design/guild/10-ledger-hygiene.md · callers: evolve.md Phase 0 / Phase 6 step 7,
# rollback.md, _data_sufficiency.md, _preflight.md Item 7).
#
# The cases that matter most:
#   • compact never loses a line: every chunk it read is in the active file or the archive
#     afterwards, exactly once, and a second compact moves nothing.
#   • the run number stays continuous after runs leave the active file (next = highest + 1).
#   • both shipped heading shapes, out-of-order runs, non-run sections and fenced headings.
#   • the skip-list of archived runs is carried by `context`, one bounded line per item.
#
# Usage: bash plugins/guild-plugin/tests/ledger_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LEDGER="$HERE/../skills/gld/commands/atoms/ledger.py"
[ -f "$LEDGER" ] || { echo "missing: $LEDGER" >&2; exit 1; }
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

L() { "$PY" "$LEDGER" --root "$R" "$@"; }
newrepo() { R="$WORK/$1"; mkdir -p "$R/.git" "$R/.claude/guild"; A="$R/.claude/guild/evolution-log.md"; B="$R/.claude/guild/evolution-log.archive.md"; }
# gen <shape> <numbers…> — one run per number, ~200 chars each, written in the given order.
gen() {
  "$PY" - "$A" "$@" <<'PYGEN'
import sys
path, shape, nums = sys.argv[1], sys.argv[2], sys.argv[3:]
out = ["# Evolution Log\n\n| 날짜 | 요약 |\n|---|---|\n| 2026-07-20 | 표는 서문이다 |\n\n"]
for n in nums:
    head = "## Run — evolve #%s (2026-08-%02d)" % (n, int(n) % 28 + 1) if shape == "omc" \
        else "## 2026-08-%02d — evolve #%s" % (int(n) % 28 + 1, n)
    out.append(head + "\n\n### [applied]\n- 항목 %s: " % n + "가" * 150 + "\n\n")
open(path, "w", encoding="utf-8").write("".join(out))
PYGEN
}
# Every non-blank line of the input files is in the output files the same number of times.
conserved() {   # conserved <case> <snapshot-file>
  local miss
  miss="$("$PY" - "$2" "$A" "$B" <<'PYC'
import sys, os
from collections import Counter
def lines(p):
    if not os.path.exists(p): return Counter()
    return Counter(l.rstrip("\r") for l in open(p, encoding="utf-8", newline="").read().split("\n") if l.strip())
before = lines(sys.argv[1])
after = lines(sys.argv[2]) + lines(sys.argv[3])
hdr = Counter(l for l in """# Evolution Log — archive
> Runs moved out of `evolution-log.md` by `ledger.py compact` (oldest first). Nothing here is
> read whole at runtime: `ledger.py context` re-reads the `[rejected]` skip-list from it and
> `ledger.py where <n>` finds a run for `/gld rollback`.""".split("\n"))
print("missing=%d extra=%d" % (sum((before - after).values()), sum((after - before - hdr).values())))
PYC
)"
  eq "$1" "$miss" "missing=0 extra=0"
}
snap() { cat "$A" > "$WORK/snap" 2>/dev/null; [ -f "$B" ] && cat "$B" >> "$WORK/snap"; }

echo "== no ledger yet"
newrepo empty
eq "status on a repo with no ledger" "$(L status)" "ledger: runs=0 next=1 last=- window=- archived=0 lines=0"
out="$(L context)"; rc=$?
eq "context with no ledger exits 0" "$rc" 0
has "context with no ledger prints an empty skip-list" "$out" "opens a run (0) ---"
out="$(L compact)"; rc=$?
eq "compact with no ledger exits 0" "$rc" 0
has "compact with no ledger says so" "$out" "no ledger"
[ ! -e "$A" ] && [ ! -e "$B" ] && ok "compact with no ledger creates nothing" || bad "compact with no ledger creates nothing" "files appeared"
L where 1 >/dev/null; eq "where on an empty ledger exits 1" "$?" 1

echo "== one-man-company shape: 12 runs, a preamble table"
newrepo omc; gen omc 1 2 3 4 5 6 7 8 9 10 11 12; snap
st="$(L status)"
has "12 runs counted" "$st" "runs=12 next=13"
has "window is the newest 10" "$st" "window=#3-#12"
has "last date comes from the highest run" "$st" "last=2026-08-13"
out="$(L compact)"; rc=$?
eq "compact exits 0" "$rc" 0
has "compact moved the two oldest" "$out" "moved=2 (#1,#2)"
has "compact names both files to stage" "$out" "stage: .claude/guild/evolution-log.md .claude/guild/evolution-log.archive.md"
conserved "compact lost and invented nothing" "$WORK/snap"
has "preamble table stays in the active file" "$(cat "$A")" "| 2026-07-20 | 표는 서문이다 |"
lacks "run #1 left the active file" "$(cat "$A")" "evolve #1 ("
has "run #3 stays in the active file" "$(cat "$A")" "## Run — evolve #3 ("
has "archive got a header" "$(head -1 "$B")" "# Evolution Log — archive"
has "run #1 is in the archive" "$(cat "$B")" "## Run — evolve #1 ("
st="$(L status)"
has "next run number unchanged after compact" "$st" "runs=12 next=13"
has "archived count reported" "$st" "archived=2"
snap; out="$(L compact)"
has "second compact moves nothing" "$out" "moved=0"
has "second compact stages only the active file" "$out" "stage: .claude/guild/evolution-log.md"
lacks "second compact does not stage the archive" "$out" "archive.md"
conserved "second compact is a no-op on content" "$WORK/snap"
w="$(L where 1)"
has "where finds an archived run" "$w" ".claude/guild/evolution-log.archive.md:"
ln="${w##*:}"; ln="${ln%-*}"; line="$(sed -n "${ln}p" "$B")"
has "where's line is the run heading" "$line" "## Run — evolve #1 ("
w="$(L where 12)"
has "where finds an active run" "$w" ".claude/guild/evolution-log.md:"
L where 99 >/dev/null; eq "where on a missing run exits 1" "$?" 1

echo "== a run number that is a prefix of another (#1 vs #12)"
w="$(L where 1)"
eq "where 1 matches only run #1" "$(printf '%s\n' "$w" | wc -l | tr -d ' ')" 1

echo "== word_app shape: an init section, out-of-order runs"
newrepo wa
cat > "$A" <<'EOF'
# Evolution Log

## 2026-07-16 — init

초기화.

EOF
for n in 1 2 3 4 5 6 8 7 9 10 11 12 13; do printf '## 2026-08-%02d — evolve #%s\n\n본문 %s\n\n' "$n" "$n" "$n" >> "$A"; done
snap
has "out-of-order runs counted" "$(L status)" "runs=13 next=14"
out="$(L compact)"
has "compact moves #1..#3" "$out" "moved=3 (#1,#2,#3)"
has "the init section stays in the active file" "$(cat "$A")" "## 2026-07-16 — init"
lacks "the init section is not archived" "$(cat "$B")" "— init"
conserved "out-of-order compact lost nothing" "$WORK/snap"
# archive more: shrink the window by adding runs, check sort order in the archive
for n in 14 15 16 17 18 19 20; do printf '## 2026-09-%02d — evolve #%s\n\n본문 %s\n\n' "$n" "$n" "$n" >> "$A"; done
snap; L compact >/dev/null
seven="$(grep -n "evolve #7$" "$B" | cut -d: -f1)"; eight="$(grep -n "evolve #8$" "$B" | cut -d: -f1)"
[ -n "$seven" ] && [ -n "$eight" ] && [ "$seven" -lt "$eight" ] && ok "archive is in run order (#7 before #8)" || bad "archive is in run order" "7=$seven 8=$eight"
conserved "second wave lost nothing" "$WORK/snap"
has "archived 10 runs" "$(L status)" "archived=10"
has "next continues past the archive" "$(L status)" "next=21"

echo "== character budget"
newrepo big
"$PY" - "$A" <<'PYB'
import sys
open(sys.argv[1], "w", encoding="utf-8").write("".join(
    "## Run — evolve #%d (2026-09-01)\n\n%s\n\n" % (n, "나" * 9000) for n in range(1, 6)))
PYB
has "huge runs still keep the minimum of 3" "$(L status)" "window=#3-#5"
newrepo mid
"$PY" - "$A" <<'PYM'
import sys
open(sys.argv[1], "w", encoding="utf-8").write("".join(
    "## Run — evolve #%d (2026-09-01)\n\n%s\n\n" % (n, "다" * 6000) for n in range(1, 7)))
PYM
has "a 4th 6000-char run would pass 20000 chars" "$(L status)" "window=#4-#6"
newrepo small
"$PY" - "$A" <<'PYS'
import sys
open(sys.argv[1], "w", encoding="utf-8").write("".join(
    "## Run — evolve #%d (2026-09-01)\n\n%s\n\n" % (n, "x" * 1000) for n in range(1, 16)))
PYS
has "small runs are capped at 10" "$(L status)" "window=#6-#15"

echo "== gaps and duplicates"
newrepo gap
printf '## 2026-08-01 — evolve #1\n\na\n\n## 2026-08-02 — evolve #2\n\nb\n\n## 2026-08-05 — evolve #5\n\nc\n' > "$A"
has "next is highest + 1 across a gap" "$(L status)" "runs=3 next=6"
newrepo dup
printf '## 2026-08-01 — evolve #1\n\na\n\n## 2026-08-04 — evolve #4\n\nfirst\n\n## 2026-08-04 — evolve #4\n\nsecond\n' > "$A"
has "a duplicated run number is warned" "$(L status)" "warning: run #4 has 2 entries"
has "duplicates count once as a run" "$(L status)" "runs=2 next=5"

echo "== headings that are not runs"
newrepo fence
cat > "$A" <<'EOF'
# Evolution Log

## Run — evolve #1 (2026-08-01)

```markdown
## 노트 (inside a fence)
### [rejected] fenced
- not an item
```

### evolve #42 is mentioned in a level-3 heading

EOF
st="$(L status)"
has "a fenced heading is not a run, a level-3 mention is not a run" "$st" "runs=1 next=2"

echo "== skip-list carried from archived runs"
newrepo skip
"$PY" - "$A" <<'PYK'
import sys
runs = []
runs.append("""## Run — evolve #1 (2026-08-01)

### [applied]
- applied item

### [rejected] — skip-list (declined-stays-declined)
- **P2 ③ tech-lead habit** dropped by the panel
  - degradation: long reasoning that must not be carried
  - 재제안 조건: only after the code moves
- **P3 ⑥ fact** declined by the human

### [rejected] — 없음.

### 메모
- **[rejected]** tagged bullet outside the section
""")
runs.append("""## 2026-08-02 — evolve #2

### [rejected] 항목 1건
거절 사유가 불릿 없이 문단으로 적혔다.
둘째 줄은 싣지 않는다.
""")
runs.append("""## 2026-08-03 — evolve #3

### [rejected]
- %s
""" % ("길" * 400))
for n in range(4, 14):
    runs.append("## 2026-08-%02d — evolve #%d\n\n### [rejected]\n- window item %d\n" % (n, n, n))
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYK
ctx="$(L context)"
has "top-level bullet of a [rejected] section is carried" "$ctx" "[evolve #1] **P2 ③ tech-lead habit** dropped by the panel"
has "second declined item is carried" "$ctx" "[evolve #1] **P3 ⑥ fact** declined by the human"
lacks "sub-bullet reasoning is not carried" "$ctx" "long reasoning that must not be carried"
lacks "an empty [rejected] heading carries nothing" "$ctx" "없음."
has "a tagged bullet elsewhere is carried" "$ctx" "[evolve #1] **[rejected]** tagged bullet outside the section"
has "a paragraph-only section carries its first line" "$ctx" "[evolve #2] 거절 사유가 불릿 없이 문단으로 적혔다."
lacks "only the first line of a paragraph" "$ctx" "둘째 줄은 싣지 않는다."
has "a long item is cut with an ellipsis" "$ctx" "…"
n3="$(printf '%s\n' "$ctx" | grep '^\[evolve #3\]' | "$PY" -c 'import sys; print(len(sys.stdin.read().rstrip("\n")) - len("[evolve #3] "))')"
eq "a cut item is 240 characters" "$n3" 240
has "the carried count is printed" "$ctx" "opens a run (5) ---"
lacks "window runs' items are not duplicated into the skip-list" "$ctx" "[evolve #4] window item 4"
has "window runs are printed verbatim" "$ctx" "- window item 13"
first="$(printf '%s\n' "$ctx" | grep -n '^## 2026-08-04 — evolve #4' | cut -d: -f1)"
last="$(printf '%s\n' "$ctx" | grep -n '^## 2026-08-13 — evolve #13' | cut -d: -f1)"
[ -n "$first" ] && [ -n "$last" ] && [ "$first" -lt "$last" ] && ok "window runs oldest first" || bad "window runs oldest first" "4=$first 13=$last"
snap; L compact >/dev/null
eq "context after compact differs only in its status line" "$(L context | sed 1d)" "$(printf '%s\n' "$ctx" | sed 1d)"
conserved "skip fixture compact lost nothing" "$WORK/snap"

echo "== what context carries past the window"
newrepo carry
"$PY" - "$A" <<'PYT'
import sys
runs = ["""## Run — evolve #1 (2026-08-01)

### [applied]
- **③ developer habit** that a human later undid
- **⑥ fact** applied alongside

[reverted 2026-08-09 — by the commit that carries this note]
""", """## Run — evolve #2 (2026-08-02)

- model-tier-item: developer raise sonnet→opus · filed under tech-lead · share 4/6, 5/9, 3/5
""", """## Run — evolve #3 (2026-08-03)

### model-tier scorecard
- window start `2026-08-02` · 분모 3 · 분자 2 · share 2/3
"""]
for n in range(4, 26):
    runs.append("## Run — evolve #%d (2026-08-%02d)\n\n- **model-tier**: qualifying · share %d/6\n- overseer: theming · 대비 위험 반복 수용 · 모드 분기 #%d\n" % (n, n, n % 6, n))
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYT
ctx="$(L context)"
has "a reverted run's note is carried" "$ctx" "[evolve #1] [reverted 2026-08-09"
has "and what it applied" "$ctx" "[evolve #1] **③ developer habit** that a human later undid"
has "a model-tier item is carried from any run" "$ctx" "[evolve #2] - model-tier-item: developer raise sonnet→opus"
has "tagged rows of runs before the window are carried" "$ctx" "[evolve #9] - **model-tier**: qualifying · share 3/6"
lacks "the series stops 12 runs before the window" "$ctx" "[evolve #3] ### model-tier scorecard"
eq "a model-tier-item line is not counted as a row" "$(printf '%s\n' "$ctx" | grep -c 'model-tier-item')" 1
has "the series header counts 12 runs" "$ctx" "model-tier rows of the 12 runs before the window, oldest first (12)"
newrepo legacy
"$PY" - "$A" <<'PYL'
import sys
runs = ["""## Run — evolve #1 (2026-08-01)

### model-tier scorecard
- window start `2026-08-02` · 분모 3 · 분자 2
""", """## Run — evolve #2 (2026-08-02)

### model-tier scorecard — escalated 0건, HR 없음.
"""]
for n in range(3, 14):
    runs.append("## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n))
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYL
ctx="$(L context)"
has "a legacy heading row takes its first body line" "$ctx" "[evolve #1] ### model-tier scorecard - window start"
has "a legacy row in the heading is kept as is" "$ctx" "[evolve #2] ### model-tier scorecard — escalated 0건, HR 없음."

echo "== tagged"
newrepo tag
printf '## 2026-08-01 — evolve #1\n\n- overseer: old lesson\n\n## 2026-08-02 — evolve #2\n\n- overseer: theming · 대비\n- **overseer**: layout · 간격\n- not an overseer: line\n\n## 2026-08-03 — evolve #3\n\nno overseer rows here\n' > "$A"
tg="$(L tagged overseer)"
has "tagged reads the newest run that has the tag" "$tg" "[evolve #2]"
has "a plain tagged line" "$tg" "- overseer: theming · 대비"
has "a bold tagged line" "$tg" "- **overseer**: layout · 간격"
lacks "an older run's lines are not mixed in" "$tg" "old lesson"
lacks "a line that only mentions the word is not tagged" "$tg" "not an overseer"
newrepo notag; gen omc 1 2
eq "no tagged line prints none" "$(L tagged overseer)" "none"
L tagged "Bad Tag" >/dev/null 2>&1; eq "a malformed tag exits 64" "$?" 64

echo "== a failed write leaves both files as they were"
newrepo fail; gen omc 1 2 3 4 5 6 7 8 9 10 11 12
cp "$A" "$WORK/fail.active"
"$PY" - "$LEDGER" "$R" <<'PYF' >"$WORK/fail.out" 2>&1
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ledger", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
real, calls = m.atomic_write, []
def flaky(path, text):
    calls.append(path)
    if len(calls) == 2:
        raise OSError("disk full")
    real(path, text)
m.atomic_write = flaky
sys.exit(m.main(["compact", "--root", sys.argv[2]]))
PYF
eq "a failed write exits 65" "$?" 65
has "it says nothing was moved" "$(cat "$WORK/fail.out")" "nothing was moved"
cmp -s "$A" "$WORK/fail.active" && ok "the active file is untouched" || bad "the active file is untouched" "changed"
[ ! -e "$B" ] && ok "a new archive is removed again" || bad "a new archive is removed again" "archive left behind"

echo "== an interrupted compact (archive written, active not)"
newrepo intr; gen omc 1 2 3 4 5 6 7 8 9 10 11 12
L compact >/dev/null
cp "$A" "$WORK/active.after"
"$PY" - "$A" "$B" <<'PYI'
import sys
a, b = sys.argv[1], sys.argv[2]
arch = open(b, encoding="utf-8").read()
run1 = arch[arch.index("## Run — evolve #1 ("):arch.index("## Run — evolve #2 (")]
act = open(a, encoding="utf-8").read()
i = act.index("## Run — evolve #3 (")
open(a, "w", encoding="utf-8").write(act[:i] + run1 + act[i:])
PYI
has "the half-moved run is reported as a duplicate" "$(L status)" "warning: run #1 has 2 entries"
L compact >/dev/null
eq "the half-moved run is written once" "$(grep -c "evolve #1 (" "$B")" 1
lacks "and leaves the active file" "$(cat "$A")" "evolve #1 ("
lacks "no duplicate warning afterwards" "$(L status)" "warning"

echo "== CRLF ledger"
newrepo crlf
printf '# Log\r\n\r\n' > "$A"
for n in 1 2 3 4 5 6 7 8 9 10 11; do printf '## 2026-08-%02d — evolve #%s\r\n\r\nbody %s\r\n\r\n' "$n" "$n" "$n" >> "$A"; done
snap
has "CRLF runs are counted" "$(L status)" "runs=11 next=12"
L compact >/dev/null; eq "CRLF compact exits 0" "$?" 0
conserved "CRLF compact lost nothing" "$WORK/snap"
has "CRLF bytes of a moved run are kept" "$(od -c "$B" | tr -d ' \n')" 'body1\r\n'

echo "== an unreadable ledger"
newrepo bin
printf '## 2026-08-01 — evolve #1\n\n\xff\xfe broken\n' > "$A"
cp "$A" "$WORK/bin.before"
L status >/dev/null 2>"$WORK/err"; eq "invalid UTF-8 exits 65" "$?" 65
has "the error names the file" "$(cat "$WORK/err")" "evolution-log.md"
L compact >/dev/null 2>&1; eq "compact on invalid UTF-8 exits 65" "$?" 65
cmp -s "$A" "$WORK/bin.before" && ok "nothing was written on error" || bad "nothing was written on error" "file changed"
[ ! -e "$B" ] && ok "no archive created on error" || bad "no archive created on error" "archive exists"

echo "== usage"
newrepo use; gen omc 1 2
L where >/dev/null 2>&1; eq "where without a number exits 64" "$?" 64
L status 3 >/dev/null 2>&1; eq "status with a number exits 64" "$?" 64
L where x >/dev/null 2>&1; eq "where with a non-number exits 64" "$?" 64
L context overseer >/dev/null 2>&1; eq "context with an argument exits 64" "$?" 64
L bogus >/dev/null 2>&1; eq "an unknown mode exits 64" "$?" 64

echo "== repo root from a subdirectory"
mkdir -p "$R/sub/dir"
out="$(cd "$R/sub/dir" && "$PY" "$LEDGER" status)"
has "walks up to the directory holding .git" "$out" "runs=2 next=3"
out="$(cd "$R/sub/dir" && "$PY" "$LEDGER" where 1)"
eq "where prints a repo-relative path and line range from a subdirectory" "$out" ".claude/guild/evolution-log.md:7-10"

echo "== fences follow CommonMark (a stray fence must not hide later runs)"
newrepo fence1
"$PY" - "$A" <<'PYF1'
import sys
runs = []
for n in range(1, 16):
    body = "body %d\n" % n
    if n == 5:
        body += "```bash 원문 인용 한 줄```\n"
    runs.append("## Run — evolve #%d (2026-08-%02d)\n\n%s" % (n, n, body))
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYF1
has "a one-line backtick span is not a fence" "$(L status)" "runs=15 next=16"
L where 12 >/dev/null; eq "where still finds a later run" "$?" 0
newrepo fence2
printf '## 2026-08-01 — evolve #1\n\n```text\n~~~ 물결\n## not a run\n```\n\n## 2026-08-02 — evolve #2\n\nb\n\n## 2026-08-03 — evolve #3\n\nc\n' > "$A"
has "a different fence character does not close a fence" "$(L status)" "runs=3 next=4"
newrepo fence3
printf '## 2026-08-01 — evolve #1\n\n````md\n```\n- overseer: quoted, not a lesson\n```\n- overseer: still quoted\n````\n\n- overseer: real lesson\n\n## 2026-08-02 — evolve #2\n\nb\n' > "$A"
tg="$(L tagged overseer)"
has "a shorter fence does not close a longer one" "$tg" "- overseer: real lesson"
lacks "nothing inside the longer fence is read" "$tg" "still quoted"
newrepo fence4
"$PY" - "$A" <<'PYF4'
import sys
runs = ["""## Run — evolve #1 (2026-08-01)

### [rejected]
```text
- fenced line is not an item
```
- real declined item

### 메모
```md
### [rejected] quoted in a fence
```
- a note after a quoted heading is not declined
"""]
for n in range(2, 14):
    runs.append("## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n))
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYF4
ctx="$(L context)"
has "an item after a fenced block is carried" "$ctx" "[evolve #1] real declined item"
lacks "a fenced line is not carried" "$ctx" "fenced line is not an item"
lacks "a [rejected] heading inside a fence opens no section" "$ctx" "a note after a quoted heading is not declined"

echo "== item shapes in a [rejected] section"
newrepo shapes
"$PY" - "$A" <<'PYSH'
import sys
runs = ["""## Run — evolve #1 (2026-08-01)

### [rejected] — 번호 목록
1. **P1 A** declined
2. **P2 B** declined
   - reasoning under P2 is not an item

### [rejected] — 하위 제목
#### P3 C declined
본문
#### P4 D declined

### [rejected] — 표
| 제안 | 사유 |
|---|---|
| P5 E | 패널 drop |
| P6 F | 사람 거절 |

### [rejected] — 들여쓴 불릿
  - P7 G declined
  - P8 H declined

### [applied] — run 3 [rejected] 항목의 재제안
- applied item must not read as declined
"""]
for n in range(2, 14):
    runs.append("## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n))
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYSH
ctx="$(L context)"
for item in "**P1 A** declined" "**P2 B** declined" "#### P3 C declined" "#### P4 D declined" "| P5 E | 패널 drop |" "| P6 F | 사람 거절 |" "P7 G declined" "P8 H declined"; do
  has "carried: $item" "$ctx" "[evolve #1] $item"
done
lacks "a nested reason is not an item" "$ctx" "reasoning under P2"
lacks "a table header row is not an item" "$ctx" "| 제안 | 사유 |"
lacks "a heading that only mentions [rejected] is not a skip-list section" "$ctx" "applied item must not read as declined"

echo "== a level-2 section inside a run stays with the run"
newrepo h2
"$PY" - "$A" <<'PYH'
import sys
open(sys.argv[1], "w", encoding="utf-8").write("# Log\n\n## 2026-07-16 — init\n\n초기화.\n\n" + "".join(
    "## Run — evolve #%d (2026-08-%02d)\n\n- body %d\n\n## 감독자 회고\n\n- overseer: lesson %d\n\n" % (n, n, n, n)
    for n in range(1, 13)))
PYH
snap
has "inner level-2 sections are not runs" "$(L status)" "runs=12 next=13"
has "tagged reads a line under an inner level-2 section" "$(L tagged overseer)" "- overseer: lesson 12"
L compact >/dev/null
eq "no orphaned inner section stays in the active file" "$(grep -c '## 감독자 회고' "$A")" 10
has "the init section before the first run stays" "$(cat "$A")" "## 2026-07-16 — init"
conserved "inner sections move with their run" "$WORK/snap"

echo "== line counting matches Read and wc -l"
newrepo lines
printf '# Log\n\nform\xe2\x80\xa8feed \x0c here\n\n## 2026-08-01 — evolve #1\n\na\n\n## 2026-08-02 — evolve #2\n\nb\n' > "$A"
eq "where counts only \\n as a line break" "$(L where 2)" ".claude/guild/evolution-log.md:9-11"
has "lines= equals wc -l" "$(L status)" "lines=$(wc -l < "$A" | tr -d ' ')"

echo "== file modes survive compact"
newrepo mode; gen omc 1 2 3 4 5 6 7 8 9 10 11 12
chmod 644 "$A"; L compact >/dev/null
eq "the active file keeps 0644" "$("$PY" -c 'import os,stat,sys; print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode)))' "$A")" "0o644"
amode="$("$PY" -c 'import os,stat,sys; print(stat.S_IMODE(os.stat(sys.argv[1]).st_mode) & 0o044)' "$B")"
eq "a new archive is group/other readable (not mkstemp's 0600)" "$amode" "36"

echo "== window edge and output bound"
newrepo edge
"$PY" - "$A" <<'PYE'
import sys
head = "## Run — evolve #%d (2026-09-01)\n\n"
runs = []
for n in range(1, 6):
    h = head % n
    runs.append(h + "x" * (4500 - len(h) - 1) + "\n")   # each run exactly 4500 characters
open(sys.argv[1], "w", encoding="utf-8").write("".join(runs))
PYE
has "four runs of exactly 18000 characters fit the window" "$(L status)" "window=#2-#5"
newrepo huge
"$PY" - "$A" <<'PYU'
import sys
open(sys.argv[1], "w", encoding="utf-8").write("".join(
    "## Run — evolve #%d (2026-09-01)\n\n### [applied]\n%s\n" % (n, "".join("- item %d.%d %s\n" % (n, k, "나" * 300) for k in range(40)))
    for n in range(1, 6)))
PYU
ctx="$(L context)"
n="$(printf '%s' "$ctx" | "$PY" -c 'import sys; print(len(sys.stdin.read()))')"
[ "$n" -le 28700 ] && ok "context stays under the output bound ($n chars)" || bad "context stays under the output bound" "$n chars"
has "oversized window runs are shown as outlines" "$ctx" "as outlines"
has "an outline says how to open the run" "$ctx" "(outline — \`ledger.py where 3\` opens the full run)"

echo "== conservation refuses a lossy rewrite"
newrepo cons; gen omc 1 2 3 4 5 6 7 8 9 10 11 12
cp "$A" "$WORK/cons.active"
"$PY" - "$LEDGER" "$R" <<'PYX' >"$WORK/cons.out" 2>&1
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ledger", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
real = m.join
m.join = lambda pieces: real(pieces[:-1])   # drop the last chunk of each file
sys.exit(m.main(["compact", "--root", sys.argv[2]]))
PYX
eq "a lossy rewrite exits 65" "$?" 65
has "it names the conservation check" "$(cat "$WORK/cons.out")" "conservation check failed"
cmp -s "$A" "$WORK/cons.active" && ok "nothing was written by a lossy rewrite" || bad "nothing was written by a lossy rewrite" "changed"
[ ! -e "$B" ] && ok "no archive from a lossy rewrite" || bad "no archive from a lossy rewrite" "archive exists"

newrepo fenceinfo
printf '## 2026-08-01 — evolve #1\n\n```text\n``` not a closing fence\n- overseer: still inside the fence\n```\n\n- overseer: outside\n' > "$A"
tg="$(L tagged overseer)"
has "a fence closes only on a bare fence line" "$tg" "- overseer: outside"
lacks "a fence line with text after it does not close" "$tg" "still inside the fence"

echo "== an unclosed fence never hides a later run"
for ch in '~~~' '```'; do
  newrepo "unclosed$([ "$ch" = '~~~' ] && echo t || echo b)"
  printf '## 2026-08-01 — evolve #1\n\na\n\n## 2026-08-02 — evolve #2\n\n### 되돌리기\n%s 대략 이 정도\n\n## 2026-08-03 — evolve #3\n\nc\n\n## 2026-08-04 — evolve #4\n\nd\n' "$ch" > "$A"
  has "an unclosed $ch fence: later runs still count" "$(L status)" "runs=4 next=5"
  eq "an unclosed $ch fence: where finds the next run" "$(L where 4)" ".claude/guild/evolution-log.md:14-16"
done

echo "== run headings: shapes, stray mentions, BOM, indentation"
newrepo shape2
printf '\xef\xbb\xbf## 2026-08-01 — evolve #1\n\na\n\n   ## Run — evolve #2 (2026-08-02)\n\nb\n\n## Follow-up of evolve #1\n\nnote on run 2\n\n## evolve #3 — 2026-08-03\n\nc\n' > "$A"
st="$(L status)"
has "a BOM before the first heading does not hide run #1" "$st" "runs=3 next=4"
eq "a heading indented by up to 3 spaces is a run" "$(L where 2)" ".claude/guild/evolution-log.md:5-11"
lacks "a heading that only mentions a run is not a second entry" "$st" "warning"
newrepo stray
printf '## 2026-08-01 — evolve #1\n\na\n\n## see also evolve #7 (planned)\n\nb\n' > "$A"
st="$(L status)"
has "a number named only in a non-run heading is never reused" "$st" "runs=1 next=8"
has "and it is reported" "$st" "warning: a level-2 heading names evolve #7 but is not read as a run"

echo "== outlines keep what later runs act on"
newrepo keep
"$PY" - "$A" <<'PYK2'
import sys
pad = "".join("- filler %d %s\n" % (k, "가" * 200) for k in range(50))
runs = []
for n in range(1, 5):
    runs.append("""## Run — evolve %s (2026-08-0%d)

### [applied]
- applied target %d

%s
model-tier: qualifying · share %d/6
model-tier-item: developer raise · run %d
overseer: theming · lesson %d
[reverted 2026-08-09 — by the commit that carries this note] run %d

| 표 | 값 |
|---|---|
| table row %d | x |
""" % ("#%d" % n, n, n, pad, n, n, n, n, n))
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYK2
ctx="$(L context)"
has "the window is outlined here" "$ctx" "as outlines"
for n in 2 3 4; do
  has "outlined run #$n keeps its model-tier row" "$ctx" "model-tier: qualifying · share $n/6"
  has "outlined run #$n keeps its model-tier item" "$ctx" "model-tier-item: developer raise · run $n"
  has "outlined run #$n keeps its overseer line" "$ctx" "overseer: theming · lesson $n"
  has "outlined run #$n keeps its reverted note" "$ctx" "the commit that carries this note] run $n"
  has "outlined run #$n keeps its applied target" "$ctx" "applied target $n"
done

echo "== the newest survives every bound"
newrepo newest
"$PY" - "$A" <<'PYN'
import sys
open(sys.argv[1], "w", encoding="utf-8").write("".join(
    "## Run — evolve #%d (2026-09-01)\n\n### [applied]\n%smodel-tier: qualifying · run %d\n" % (
        n, "".join("- item %d.%d %s\n" % (n, k, "나" * 200) for k in range(120)), n)
    for n in range(1, 4)))
PYN
ctx="$(L context)"
n="$(printf '%s' "$ctx" | "$PY" -c 'import sys; print(len(sys.stdin.read()))')"
[ "$n" -le 28700 ] && ok "context stays under the bound with 3 huge runs ($n chars)" || bad "context stays under the bound with 3 huge runs" "$n chars"
has "the newest run's row survives" "$ctx" "model-tier: qualifying · run 3"
has "an older run is left out before the newest is cut" "$ctx" "(run #1 left out"

echo "== carried sections keep the newest and stay in the budget"
newrepo many
"$PY" - "$A" <<'PYM2'
import sys
runs = []
for n in range(1, 60):
    runs.append("## Run — evolve #%d (2026-08-01)\n\n### [rejected]\n- declined item of run %d %s\n" % (n, n, "다" * 200))
for n in range(60, 63):
    runs.append("## Run — evolve #%d (2026-09-01)\n\n%s\n" % (n, "라" * 7000))
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYM2
ctx="$(L context)"
has "the newest declined item is kept" "$ctx" "declined item of run 59"
lacks "the oldest declined item gives way" "$ctx" "declined item of run 1 "
has "the dropped count is printed" "$ctx" "older not shown"
n="$(printf '%s' "$ctx" | "$PY" -c 'import sys; print(len(sys.stdin.read()))')"
[ "$n" -le 28700 ] && ok "carried sections count against the bound ($n chars)" || bad "carried sections count against the bound" "$n chars"

echo "== a failed write puts an existing archive back byte for byte"
newrepo refail; gen omc 1 2 3 4 5 6 7 8 9 10 11 12
L compact >/dev/null
gen omc 1 2 3 4 5 6 7 8 9 10 11 12 13 14   # two more runs, so #3 and #4 must move now
cp "$A" "$WORK/refail.a"; cp "$B" "$WORK/refail.b"
"$PY" - "$LEDGER" "$R" <<'PYF2' >/dev/null 2>&1
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ledger", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
real, calls = m.atomic_write, []
def flaky(path, text):
    calls.append(path)
    if len(calls) == 2:
        raise OSError("disk full")
    real(path, text)
m.atomic_write = flaky
sys.exit(m.main(["compact", "--root", sys.argv[2]]))
PYF2
eq "a failed write on an existing archive exits 65" "$?" 65
cmp -s "$B" "$WORK/refail.b" && ok "the existing archive is restored" || bad "the existing archive is restored" "changed"
cmp -s "$A" "$WORK/refail.a" && ok "the active file is untouched" || bad "the active file is untouched" "changed"

echo "== conservation also guards the preamble"
newrepo pre; gen omc 1 2 3 4 5 6 7 8 9 10 11 12
cp "$A" "$WORK/pre.a"
"$PY" - "$LEDGER" "$R" <<'PYP' >"$WORK/pre.out" 2>&1
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ledger", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
real = m.join
m.join = lambda pieces: real([pieces[0].replace("표는 서문이다", "바뀐 서문")] + list(pieces[1:]))
sys.exit(m.main(["compact", "--root", sys.argv[2]]))
PYP
eq "a changed preamble exits 65" "$?" 65
cmp -s "$A" "$WORK/pre.a" && ok "nothing written when the preamble would change" || bad "nothing written when the preamble would change" "changed"

echo "== moved runs stay separated"
newrepo tight
for n in 1 2 3 4 5 6 7 8 9 10 11 12; do printf '## 2026-08-%02d — evolve #%s\nbody %s\n' "$n" "$n" "$n" >> "$A"; done
L compact >/dev/null
eq "every archived heading follows a blank line" "$(grep -B1 '^## 2026' "$B" | grep -c '^body')" 0

echo "== a paragraph-only [rejected] section that starts with a blank line"
newrepo para
"$PY" - "$A" <<'PYP2'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\n### [rejected]\n\n사람이 거절한 이유가 문단으로 적혔다.\n"]
runs += ["## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n) for n in range(2, 14)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYP2
has "the first non-blank line is carried" "$(L context)" "[evolve #1] 사람이 거절한 이유가 문단으로 적혔다."

echo "== tagged reads only the window, with a legacy fallback"
newrepo tagwin
"$PY" - "$A" <<'PYW'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\n- overseer: stale lesson from an old run\n"]
runs += ["## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n) for n in range(2, 14)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYW
eq "a lesson older than the window is not brought back" "$(L tagged overseer)" "none"
newrepo taglegacy
printf '## Run — evolve #1 (2026-08-01)\n\n### 감독자 회고 — **인사이트**. 대비 위험을 반복 수용\n\n## Run — evolve #2 (2026-08-02)\n\n- **감독자 회고**: 스코프 분할보다 완결 선호\n' > "$A"
has "a legacy bold label is read" "$(L tagged overseer)" "**감독자 회고**: 스코프 분할보다 완결 선호"
printf '## Run — evolve #1 (2026-08-01)\n\n### 감독자 회고 — **인사이트**. 대비 위험을 반복 수용\n' > "$A"
has "a legacy heading row is read" "$(L tagged overseer)" "### 감독자 회고 — **인사이트**. 대비 위험을 반복 수용"

echo "== run heading shapes an LLM may write"
newrepo shapes3
printf '%s\n\nbody\n\n' "## Run — evolve #1 (2026-08-01)" "## 2026-08-02 · evolve #2 · applied-onto: abc" "## [2026-08-03] (evolve #3)" "## **evolve run #4** (2026-08-04)" "## Run 2026-08-05 — evolve #5" "## Run · evolve #6" > "$A"
st="$(L status)"
has "six shapes are six runs" "$st" "runs=6 next=7"
lacks "and none is warned" "$st" "warning"
newrepo notrun
printf '%s\n\nbody\n\n' "## Run — evolve #1 (2026-08-01)" "## Run — evolve #2 (2026-08-02)" "## Notes on evolve #9 later" "## Run — evolve #10 (2026-08-10)" > "$A"
st="$(L status)"
has "a heading with other words first is not a run" "$st" "runs=3 next=11"
has "an unattributed number below the highest is still warned" "$st" "warning: a level-2 heading names evolve #9 but is not read as a run"
eq "where finds a heading that is not in the run shape" "$(L where 9)" ".claude/guild/evolution-log.md:9-11"

echo "== a [reverted] note counts only at the start of a line, outside code"
newrepo revprose
"$PY" - "$A" <<'PYR'
import sys
runs = ["""## Run — evolve #1 (2026-08-01)

### [applied]
- applied in run 1

이 실행은 나중에 [reverted] 될 수도 있다는 문장일 뿐이다.

```text
[reverted 2026-08-09 — quoted]
```
"""]
runs += ["## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n) for n in range(2, 14)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYR
ctx="$(L context)"
has "prose and fenced mentions do not mark a run reverted" "$ctx" "runs a human reverted: the note and what they applied (0) ---"

echo "== an open model-tier raise is never capped away"
newrepo openitem
"$PY" - "$A" <<'PYO'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\nmodel-tier-item: developer raise sonnet→opus · OPEN since run 1\n"]
runs += ["## Run — evolve #%d (2026-08-01)\n\nmodel-tier-item: tester raise · follow-up done: kept · run %d %s\n" % (n, n, "가" * 150) for n in range(2, 30)]
runs += ["## Run — evolve #%d (2026-09-01)\n\nbody\n" % n for n in range(30, 33)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYO
ctx="$(L context)"
has "the open raise from the oldest run is kept" "$ctx" "[evolve #1] model-tier-item: developer raise sonnet→opus · OPEN since run 1"
has "finished items give way" "$ctx" "older not shown"

echo "== tagged output is bounded"
newrepo tagcap
"$PY" - "$A" <<'PYC2'
import sys
open(sys.argv[1], "w", encoding="utf-8").write("## Run — evolve #1 (2026-08-01)\n\n" + "".join(
    "- overseer: lesson %d %s\n" % (k, "나" * 100) for k in range(300)))
PYC2
tg="$(L tagged overseer)"
n="$(printf '%s' "$tg" | "$PY" -c 'import sys; print(len(sys.stdin.read()))')"
[ "$n" -le 4400 ] && ok "tagged stays near its cap ($n chars)" || bad "tagged stays near its cap" "$n chars"
has "and says how many it left out" "$tg" "more — \`ledger.py where 1\` opens the run"
newrepo legacy600
printf '## Run — evolve #1 (2026-08-01)\n\n- **감독자 회고**: %s\n' "$("$PY" -c 'print("다"*2000)')" > "$A"
n="$(L tagged overseer | "$PY" -c 'import sys; print(max(len(l) for l in sys.stdin.read().split("\n")))')"
eq "a legacy overseer line is cut to 600 characters" "$n" 600

echo "== legacy rows prefer the scorecard heading"
newrepo prefer
"$PY" - "$A" <<'PYP3'
import sys
runs = ["""## Run — evolve #1 (2026-08-01)

### [applied] model-tier HR item — developer raise
- target developer

### model-tier scorecard
- window start 2026-07-30 · 분모 4 · 분자 3
"""]
runs += ["## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n) for n in range(2, 14)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYP3
ctx="$(L context)"
has "the scorecard heading gives the row" "$ctx" "[evolve #1] ### model-tier scorecard - window start 2026-07-30"
lacks "the HR item heading is not a row" "$ctx" "[evolve #1] ### [applied] model-tier HR item"

echo "== a longer closing fence closes"
newrepo longclose
printf '## 2026-08-01 — evolve #1\n\n```text\n- overseer: quoted\n````\n\n- overseer: after a longer close\n' > "$A"
tg="$(L tagged overseer)"
has "a longer closing fence closes the block" "$tg" "- overseer: after a longer close"
lacks "and what was inside stays quoted" "$tg" "quoted"

echo "== the newest window run is never left out"
newrepo newest2
"$PY" - "$A" <<'PYN2'
import sys
runs = ["## Run — evolve #%d (2026-09-01)\n\n### [applied]\n%s" % (n, "".join("- item %d.%d %s\n" % (n, k, "나" * 200) for k in range(40))) for n in (1, 2)]
runs.append("## Run — evolve #3 (2026-09-03)\n\n### [applied]\n%s" % "".join("- newest item %d %s\n" % (k, "라" * 200) for k in range(400)))
open(sys.argv[1], "w", encoding="utf-8").write("".join(runs))
PYN2
ctx="$(L context)"
lacks "the newest run is not left out" "$ctx" "(run #3 left out"
has "a newest outline still too long is cut, with a notice" "$ctx" "(cut at 28500 characters"
n="$(printf '%s' "$ctx" | "$PY" -c 'import sys; print(len(sys.stdin.read()))')"
[ "$n" -le 28700 ] && ok "the hard cut keeps the bound ($n chars)" || bad "the hard cut keeps the bound" "$n chars"
has "the newest run's heading is in the output" "$ctx" "## Run — evolve #3 (2026-09-03)"

echo "== a word after the number makes a heading not a run"
newrepo wordafter
printf '%s\n\nbody\n\n' "## Run — evolve #1 (2026-08-01)" "## Run — evolve #2 (2026-08-02)" "## evolve #1 retro notes" "## Run — evolve #2 follow-up" "## 2026-08-02 · evolve #2 정정" "## Run — evolve #3 (2026-08-03)" > "$A"
st="$(L status)"
has "three headings with a word after the number are not runs" "$st" "runs=3 next=4"
lacks "so no run has two entries" "$st" "has 2 entries"
eq "and they stay inside run #2" "$(L where 2)" ".claude/guild/evolution-log.md:5-19"

echo "== where exit codes"
newrepo wherecode
printf '%s\n\nbody\n\n' "## Run — evolve #1 (2026-08-01)" "## Report on evolve #2" > "$A"
L where 1 >/dev/null; eq "a run heading exits 0" "$?" 0
out="$(L where 2)"; rc=$?
eq "a number under a heading that is not a run exits 2" "$rc" 2
eq "and still prints its range" "$out" ".claude/guild/evolution-log.md:5-7"

echo "== a [rejected] heading that names the theme"
newrepo themehead
"$PY" - "$A" <<'PYT2'
import sys
runs = ["""## Run — evolve #1 (2026-08-01)

### [rejected] tech-lead habit: skeleton parity
- reason: too noisy
- evidence: gt#1

### [rejected] — 없음.

### [rejected] 항목 1건
- **P9 Z** declined with its theme in the bullet
"""]
runs += ["## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n) for n in range(2, 14)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYT2
ctx="$(L context)"
has "a heading's theme over several lines is its own item" "$ctx" "[evolve #1] tech-lead habit: skeleton parity
[evolve #1] reason: too noisy
[evolve #1] evidence: gt#1"
has "a count heading keeps its bullets as items" "$ctx" "[evolve #1] **P9 Z** declined with its theme in the bullet"

echo "== every reverted run outside the window is carried"
newrepo tworev
"$PY" - "$A" <<'PYR2'
import sys
runs = []
for n in (1, 2):
    runs.append("## Run — evolve #%d (2026-08-0%d)\n\n### [applied]\n- [applied] habit %d — developer.md\n\n[reverted 2026-08-09 — by the commit that carries this note] run %d\n" % (n, n, n, n))
runs.append("## Run — evolve #3 (2026-08-03)\n\n### [applied]\n- applied 3\n\n> [reverted 2026-08-10 — by the commit that carries this note] quoted run 3\n")
runs.append("## Run — evolve #4 (2026-08-04)\n\n### [applied]\n- applied 4\n\n**[reverted 2026-08-11 — by the commit that carries this note]** bold run 4\n")
runs += ["## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n) for n in range(5, 15)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYR2
ctx="$(L context)"
has "the first reverted run is carried" "$ctx" "[evolve #1] [reverted 2026-08-09"
has "the second reverted run is carried" "$ctx" "[evolve #2] [reverted 2026-08-09"
has "a blockquoted note counts" "$ctx" "[evolve #3] > [reverted 2026-08-10"
has "a bold note counts" "$ctx" "[evolve #4] **[reverted 2026-08-11"
has "and what they applied" "$ctx" "[evolve #2] [applied] habit 2 — developer.md"

echo "== narrower outlines come before leaving runs out"
newrepo narrow
"$PY" - "$A" <<'PYNW'
import sys
open(sys.argv[1], "w", encoding="utf-8").write("".join(
    "## Run — evolve #%d (2026-09-01)\n\n### [applied]\n%s" % (n, "".join("- item %d.%d %s\n" % (n, k, "나" * 200) for k in range(70)))
    for n in range(1, 4)))
PYNW
ctx="$(L context)"
lacks "no run is left out when narrower outlines fit" "$ctx" "left out"
w="$(printf '%s\n' "$ctx" | grep '^- item 1\.' | "$PY" -c 'import sys; print(max(len(l) for l in sys.stdin.read().split("\n") if l))')"
[ "$w" -le 80 ] && ok "the oldest run is outlined at 80 characters ($w)" || bad "the oldest run is outlined at 80 characters" "$w"

echo "== open raises do not crowd out the bound"
newrepo crowd
"$PY" - "$A" <<'PYCR'
import sys
runs = ["## Run — evolve #%d (2026-08-01)\n\nmodel-tier-item: raise %d still open %s\n" % (n, n, "가" * 200) for n in range(1, 120)]
runs += ["## Run — evolve #%d (2026-08-01)\n\nmodel-tier-item: raise · follow-up done: kept %d\n" % (n, n) for n in range(120, 160)]
runs += ["## Run — evolve #%d (2026-09-01)\n\n### [rejected]\n- newest window item %d\n" % (n, n) for n in range(160, 163)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYCR
ctx="$(L context)"
sec="$(printf '%s\n' "$ctx" | sed -n '/^--- model-tier items/,/^--- model-tier rows/p')"
n="$(printf '%s' "$sec" | "$PY" -c 'import sys; print(len(sys.stdin.read()))')"
[ "$n" -le 1700 ] && ok "the items section stays near its cap ($n chars)" || bad "the items section stays near its cap" "$n chars"
has "the newest open raise is kept" "$sec" "raise 119 still open"
has "the window still shows" "$ctx" "- newest window item 162"

echo "== a themed [rejected] heading keeps the theme and every line"
newrepo theme2
"$PY" - "$A" <<'PYT3'
import sys
runs = ["""## Run — evolve #1 (2026-08-01)

### [rejected] (human-declined)
- **leader.md**: scope habit declined
- **developer.md**: grep habit declined

### [rejected] Leader scope-split habit
- evidence one #185
- evidence two #132
"""]
runs += ["## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n) for n in range(2, 14)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYT3
ctx="$(L context)"
has "a field-looking sibling is not dropped" "$ctx" "[evolve #1] **developer.md**: grep habit declined"
has "the first field-looking item is kept" "$ctx" "[evolve #1] **leader.md**: scope habit declined"
has "a theme over prose items is kept" "$ctx" "[evolve #1] Leader scope-split habit"
has "and its items too" "$ctx" "[evolve #1] evidence two #132"

echo "== a left-out window run keeps what later runs need"
newrepo leftfacts
"$PY" - "$A" <<'PYL2'
import sys
runs = ["## Run — evolve #%d (2026-08-01)\n\n### [rejected]\n- filler %d %s\n\nmodel-tier: small · run %d %s\n" % (n, n, "가" * 200, n, "나" * 200) for n in range(1, 28)]
for n in range(28, 31):
    runs.append("## Run — evolve #%d (2026-09-01)\n\n### [applied]\n%s\n### [rejected]\n- [rejected] UNIQUE-THEME-%d — declined\n\n[reverted 2026-09-09 — by the commit that carries this note] run %d\n" % (
        n, "".join("- item %d.%d %s\n" % (n, k, "다" * 200) for k in range(100)), n, n))
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYL2
ctx="$(L context)"
has "a run is left out here" "$ctx" "(run #28 left out"
has "its declined theme survives" "$ctx" "UNIQUE-THEME-28"
has "its reverted note survives" "$ctx" "the commit that carries this note] run 28"
n="$(printf '%s' "$ctx" | "$PY" -c 'import sys; print(len(sys.stdin.read()))')"
[ "$n" -le 28700 ] && ok "and the bound holds ($n chars)" || bad "and the bound holds" "$n chars"

echo "== the legacy overseer fallback stops once tags are used"
newrepo tagmix
printf '## Run — evolve #1 (2026-08-01)\n\n- overseer: tagged lesson\n\n## Run — evolve #2 (2026-08-02)\n\n### Overseer row\n- none this run\n' > "$A"
tg="$(L tagged overseer)"
has "the tagged lesson is found" "$tg" "- overseer: tagged lesson"
lacks "a newer heading-only legacy match does not hide it" "$tg" "Overseer row"

echo "== a follow-up line closes the raise it names"
newrepo closeraise
"$PY" - "$A" <<'PYCL'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\nmodel-tier-item: developer raise · OPEN-1 %s\n" % ("가" * 200)]
runs += ["## Run — evolve #%d (2026-08-01)\n\nmodel-tier-item: tester raise · run %d %s\n" % (n, n, "나" * 200) for n in range(2, 9)]
runs += ["## Run — evolve #%d (2026-08-01)\n\nmodel-tier-item: tester raise of evolve #%d — follow-up done: kept\n" % (n, n - 7) for n in range(9, 16)]
runs += ["## Run — evolve #%d (2026-09-01)\n\nbody\n" % n for n in range(16, 26)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYCL
sec="$(L context | sed -n '/^--- model-tier items/,/^--- model-tier rows/p')"
has "the one raise no follow-up names stays, though it is the oldest" "$sec" "OPEN-1"

echo "== run lines written before the heading was fixed still count toward next"
newrepo oldshape
printf '# Log\n\n### evolve #1 — 2026-08-01\n\na\n\n**evolve #2** (2026-08-02)\n\nb\n\n### [rejected] 사유는 evolve #9 규정 참조\n\nc\n' > "$A"
st="$(L status)"
has "a level-3 run heading and a bold run line raise next" "$st" "runs=0 next=3"
has "and they are warned on one line" "$st" "warning: evolve #1,#2 written as a run but not as a level-2 heading"
lacks "a heading that only mentions a run is not run-shaped" "$st" "evolve #9"

echo "== a follow-up closes one raise, not every raise of its run"
newrepo tworaise
"$PY" - "$A" <<'PYTR'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\nbody\n",
        "## Run — evolve #2 (2026-08-02)\n\nmodel-tier-item: developer raise sonnet→opus · DEV-2\nmodel-tier-item: tester raise sonnet→opus · TESTER-2 still open\n"]
runs += ["## Run — evolve #%d (2026-08-03)\n\nmodel-tier-item: qa raise of evolve #%d — follow-up done: kept %s\n" % (n, n, "가" * 200) for n in range(3, 11)]
runs.append("## Run — evolve #11 (2026-08-11)\n\nmodel-tier-item: developer raise of evolve #2 — follow-up done: kept\nmodel-tier-item: security raise · NEW-11 same run as a done line\n")
runs += ["## Run — evolve #%d (2026-09-01)\n\nbody\n" % n for n in range(12, 22)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYTR
sec="$(L context | sed -n '/^--- model-tier items/,/^--- model-tier rows/p')"
has "the other role's raise in the same run stays open" "$sec" "TESTER-2 still open"
has "a done line does not close a new raise in its own run" "$sec" "NEW-11 same run as a done line"
t2="$(printf '%s\n' "$sec" | grep -n 'TESTER-2' | cut -d: -f1)"; n11="$(printf '%s\n' "$sec" | grep -n 'NEW-11' | cut -d: -f1)"
[ -n "$t2" ] && [ -n "$n11" ] && [ "$t2" -lt "$n11" ] && ok "items print in run order" || bad "items print in run order" "tester=$t2 new=$n11"
d10="$(printf '%s\n' "$sec" | grep -n 'qa raise of evolve #10' | cut -d: -f1)"
[ -n "$d10" ] && [ -n "$n11" ] && [ "$d10" -lt "$n11" ] && ok "finished and open items interleave in run order" || bad "finished and open items interleave in run order" "done10=$d10 new11=$n11"

newrepo windowdone
"$PY" - "$A" <<'PYWD'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\nmodel-tier-item: developer raise sonnet→opus · RAISE-1\nmodel-tier-item: tester raise sonnet→opus · RAISE-T\n"]
runs += ["## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n) for n in range(2, 13)]
runs.append("## Run — evolve #13 (2026-08-13)\n\nmodel-tier-item: developer raise of evolve #1 — follow-up done: kept\n")
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYWD
sec="$(L context | sed -n '/^--- model-tier items/,/^--- model-tier rows/p')"
has "a raise with no follow-up is marked pending" "$sec" "RAISE-T (follow-up pending)"
has "a raise closed by a follow-up in the window is listed" "$sec" "RAISE-1"
lacks "and not marked pending" "$sec" "RAISE-1 (follow-up pending)"

echo "== warnings stay one line each, however many"
newrepo manywarn
"$PY" - "$A" <<'PYMW'
import sys
open(sys.argv[1], "w", encoding="utf-8").write("".join("#### evolve #%d — 2026-08-01\n\nbody\n\n" % n for n in range(1, 60)))
PYMW
st="$(L status)"
eq "fifty-nine level-4 run lines give one warning line" "$(printf '%s\n' "$st" | grep -c '^warning')" 1
has "a level-4 run line counts toward next" "$st" "runs=0 next=60"

echo "== a decorated role still matches its follow-up"
newrepo decorated
"$PY" - "$A" <<'PYDR'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\nmodel-tier-item: `developer` raise sonnet→opus · DECORATED-1\n"]
runs += ["## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n) for n in range(2, 13)]
runs.append("## Run — evolve #13 (2026-08-13)\n\nmodel-tier-item: developer raise of evolve #1 — follow-up done: kept\n")
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYDR
lacks "a backticked role is closed by a plain follow-up" "$(L context)" "DECORATED-1 (follow-up pending)"

echo "== a raise in a run a human reverted is not pending"
newrepo revraise
"$PY" - "$A" <<'PYRR'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\nmodel-tier-item: developer raise sonnet→opus · share 4/6\nmodel-tier-item: developer lower note · not a raise\n\n[reverted 2026-08-03 — by the commit that carries this note]\n"]
runs.append("## Run — evolve #2 (2026-08-02)\n\nmodel-tier-item: qa note · NOT-A-RAISE-2\n")
runs += ["## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n) for n in range(3, 15)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYRR
sec="$(L context | sed -n '/^--- model-tier items/,/^--- model-tier rows/p')"
lacks "a reverted run's raise is not marked pending" "$sec" "share 4/6 (follow-up pending)"
has "it is marked reverted instead" "$sec" "share 4/6 (reverted by human)"
lacks "a line that is not a raise is never pending" "$sec" "not a raise (follow-up pending)"
lacks "a non-raise line in a kept run is never pending" "$sec" "NOT-A-RAISE-2 (follow-up pending)"

echo "== a left-out run's tagged lines are capped too"
newrepo keepcap
"$PY" - "$A" <<'PYKC'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\n%s%s" % ("".join("overseer: lesson %d %s\n" % (k, "가" * 150) for k in range(60)),
        "".join("- filler 1.%d %s\n" % (k, "나" * 200) for k in range(330)))]
runs += ["## Run — evolve #%d (2026-08-0%d)\n\n%s" % (n, n, "".join("- filler %d.%d %s\n" % (n, k, "다" * 200) for k in range(140))) for n in (2, 3)]
open(sys.argv[1], "w", encoding="utf-8").write("".join(runs))
PYKC
ctx="$(L context)"
stub="$(printf '%s\n' "$ctx" | sed -n '/(run #1 left out/,/^$/p')"
n="$(printf '%s' "$stub" | "$PY" -c 'import sys; print(len(sys.stdin.read()))')"
[ "$n" -le 1400 ] && ok "the left-out stub stays near 1200 characters ($n)" || bad "the left-out stub stays near 1200 characters" "$n"
lacks "the newest run is not cut for it" "$ctx" "(cut at 28500 characters"

echo "== a left-out run lends its unused half to the other list"
for kind in applied rejected; do
  newrepo "half$kind"
  "$PY" - "$A" "$kind" <<'PYHF'
import sys
kind = sys.argv[2]
runs = ["## Run — evolve #1 (2026-08-01)\n\n### [%s]\n%s\n%s" % (
    kind, "".join("- [%s] theme%d %s — target/f%d.md\n" % (kind, k, "x" * 110, k) for k in range(12)),
    "".join("- filler 1.%d %s\n" % (k, "가" * 200) for k in range(330)))]
runs += ["## Run — evolve #%d (2026-08-0%d)\n\n%s" % (n, n, "".join("- filler %d.%d %s\n" % (n, k, "나" * 200) for k in range(330))) for n in (2, 3)]
open(sys.argv[1], "w", encoding="utf-8").write("".join(runs))
PYHF
  ctx="$(L context)"
  has "with only $kind items the run is left out" "$ctx" "(run #1 left out"
  n="$(printf '%s\n' "$ctx" | sed -n '/(run #1 left out/,/^$/p' | grep -c "^- \[$kind\]")"
  [ "$n" -ge 6 ] && ok "$kind items take more than half the room ($n lines)" || bad "$kind items take more than half the room" "$n lines"
done

echo "== a left-out run keeps its applied targets, and says what it cut"
newrepo leftapplied
"$PY" - "$A" <<'PYLA'
import sys
runs = ["## Run — evolve #%d (2026-08-01)\n\n### [rejected]\n- filler %d %s\n\nmodel-tier: small · run %d %s\n" % (n, n, "가" * 200, n, "나" * 200) for n in range(1, 28)]
for n in range(28, 31):
    runs.append("## Run — evolve #%d (2026-09-01)\n\n### [applied]\n- [applied] TARGET-%d — developer.md\n%s\n### [rejected]\n%s" % (
        n, n, "".join("- item %d.%d %s\n" % (n, k, "다" * 200) for k in range(100)),
        "".join("- [rejected] theme %d.%d %s\n" % (n, k, "라" * 150) for k in range(12))))
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYLA
ctx="$(L context)"
has "a left-out run here" "$ctx" "(run #28 left out"
has "its applied target survives, marked once" "$ctx" "- [applied] TARGET-28 — developer.md"
has "and the cut is marked" "$ctx" "… "

echo "== a reason written as a paragraph under a theme heading is kept"
newrepo parareason
"$PY" - "$A" <<'PYPR'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\n### [rejected] cache layer for agents\nDeclined: owner wants no new infra\n- evidence: 2 runs\n- panel: 2/3 against\n"]
runs += ["## Run — evolve #%d (2026-08-%02d)\n\nbody\n" % (n, n) for n in range(2, 14)]
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYPR
has "the paragraph reason is carried" "$(L context)" "[evolve #1] Declined: owner wants no new infra"

echo "== an outline cut at the bound keeps what later runs act on"
newrepo outcut
"$PY" - "$A" <<'PYOC'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\nbody\n", "## Run — evolve #2 (2026-08-02)\n\nbody\n"]
runs.append("## Run — evolve #3 (2026-08-03)\n\n%s- [rejected] keep-me — declined\nmodel-tier-item: developer raise · LATE-RAISE\n" % "".join(
    "- item %d %s\n" % (k, "나" * 200) for k in range(700)))
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(runs))
PYOC
ctx="$(L context)"
has "the bound is hit here" "$ctx" "(cut at 28500 characters"
has "a declined bullet at the end of the newest run survives the cut" "$ctx" "- [rejected] keep-me — declined"
has "a model-tier item at the end survives the cut" "$ctx" "LATE-RAISE"

echo "== a left-out stub counts must-keep lines it cut"
newrepo mkcount
"$PY" - "$A" <<'PYMK'
import sys
runs = ["## Run — evolve #1 (2026-08-01)\n\n%s%s" % ("".join("overseer: lesson %d %s\n" % (k, "가" * 150) for k in range(20)),
        "".join("- filler 1.%d %s\n" % (k, "나" * 200) for k in range(330)))]
runs += ["## Run — evolve #%d (2026-08-0%d)\n\n%s" % (n, n, "".join("- filler %d.%d %s\n" % (n, k, "다" * 200) for k in range(140))) for n in (2, 3)]
open(sys.argv[1], "w", encoding="utf-8").write("".join(runs))
PYMK
stub="$(L context | sed -n '/(run #1 left out/,/^$/p')"
kept="$(printf '%s\n' "$stub" | grep -c '^overseer:')"
more="$(printf '%s\n' "$stub" | sed -n 's/^… \([0-9]*\) more$/\1/p')"
eq "kept plus counted must-keep lines add up to all 20" "$((kept + ${more:-0}))" 20

PYC="$(find "$HERE/../skills" -name 'ledger*.pyc' 2>/dev/null)"
[ -z "$PYC" ] && ok "no ledger .pyc written beside the plugin's scripts" || bad "pycache" "$PYC"

echo
echo "ledger: $PASS passed, $FAIL failed"
# ⚠ Keep equal to the measured PASS count; raise it only when checks are added on purpose. A
#   quote that swallows the rest of the file runs fewer checks and still ends green otherwise.
LEDGER_MIN_CHECKS=261
if [ "$((PASS + FAIL))" -lt "$LEDGER_MIN_CHECKS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${LEDGER_MIN_CHECKS}건)."
  exit 1
fi
[ "$FAIL" -eq 0 ]
