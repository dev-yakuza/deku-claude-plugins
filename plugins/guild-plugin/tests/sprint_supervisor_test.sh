#!/usr/bin/env bash
# Verification for the sprint supervisor template (design: 02-sprint.md §8 · §12.2).
#
# Scope, honestly: this cannot test that an unattended sprint *works* — that needs GitHub, a
# real repo and hours. It tests everything decidable locally, and every case below is here
# because it actually bit during implementation:
#   A  valid bash AFTER placeholder substitution (it is NOT valid before — `ORDER=(<ORDER>)`
#      is a syntax error, exactly as batch's `ISSUES=(<ISSUE_NUMBERS>)` is)
#   B  stays inside bash 3.2 (macOS /bin/bash), where `declare -A` passes `bash -n` and dies
#      only at RUNTIME — a syntax check alone cannot catch it
#   C  the marker-fenced core is byte-identical to batch.md's supervisor (§12.2) — the whole
#      drift defence for a deliberately duplicated script (D10)
#   D  structural rules a byte comparison cannot express: `case` arm ORDER, no --force,
#      no `worktree add -b`, no cd into the container, guarded sprint_dag.py exits
#   E  it runs: an empty queue exits 0 cleanly
#
# ⚠ `bash -n` exits 0 on a syntax error on macOS bash 3.2.57 (measured). Every syntax check
# here therefore keys on STDERR, not on the exit code — see syntax_err().
#
# ⚠ Python helpers are written to temp FILES, never as heredocs inside `$( … )`. bash
# mis-parses parentheses and quotes inside a heredoc nested in a command substitution — that
# cost a debugging round here.
#
# Usage: bash plugins/guild-plugin/tests/sprint_supervisor_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TPL="$HERE/../skills/gld/templates/sprint-supervisor.sh"
BATCH="$HERE/../skills/gld/commands/batch.md"
RUNMD="$HERE/../skills/gld/commands/sprint/run.md"
for f in "$TPL" "$BATCH"; do
  [ -f "$f" ] || { echo "missing: $f" >&2; exit 1; }
done
SH="${SH:-/bin/bash}"
PY="${PY:-python3}"
WORK="$(mktemp -d)" || { echo "mktemp -d failed" >&2; exit 1; }
[ -n "$WORK" ] && [ -d "$WORK" ] || { echo "mktemp -d gave no directory" >&2; exit 1; }
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0

# ── 환경 격리 (라운드 5) ──────────────────────────────────────────────────
# ⚠ `GIT_DIR`/`GIT_WORK_TREE` are ALWAYS exported inside a git hook — and this plugin installs
# hooks. Leaving them set made every `git -C <tmp>` in this file operate on the caller's repo:
# 16 of 19 cases failed with messages blaming the gate (measured). `GIT_INDEX_FILE` and
# `GIT_CONFIG_*` do the same for staging and config.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
unset GIT_CONFIG GIT_CONFIG_COUNT
# ⚠ And refuse to run at all without the interpreter, rather than reporting its absence
# as a structural defect with an empty diagnostic.
# A FUNCTIONAL probe, not `command -v`: an interpreter that exists but cannot run
# (a broken venv, a shim that exits non-zero) produced five confusing structural
# failures with empty diagnostics — measured.
"$PY" -c "pass" >/dev/null 2>&1 || { echo "SKIP: $PY is not usable — this suite is python-based" >&2; exit 0; }
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s — %s\n' "$1" "$2"; }

# ⚠ `bash -n` EXITS 0 ON A SYNTAX ERROR on macOS bash 3.2.57 — measured, and not masked by
# any wrapper (a control `false` returns 1 in the same shell). The only reliable signal is
# whether it wrote to stderr. Testing the exit code, which is the obvious thing to do and
# what tests/batch_script_test.sh:40 currently does, produces a check that CAN NEVER FAIL.
syntax_err() {   # syntax_err <file> — echoes the first error line, empty when clean
  "$SH" -n "$1" 2>"$WORK/syn.err" || true
  head -1 "$WORK/syn.err" 2>/dev/null || true
}

# ── the per-document placeholder map (round-2 review predicted this exact need) ──
cat > "$WORK/render.py" <<'PY'
import sys
tpl, order, install, human = sys.argv[1:5]
# Optional: a real container path and a real sprint_dag.py, for the end-to-end section.
container = sys.argv[5] if len(sys.argv) > 5 else "/tmp/gld-test-container"
dag = sys.argv[6] if len(sys.argv) > 6 else "/tmp/gld-test-dag.py"
# The board's ten values are NOT render tokens any more — they live in a data file the
# supervisor reads (`$HUMAN_REPO/.claude/guild/.gld-sprint-$TRACKER.board`). Three injections
# came out of substituting them into bash source. `board_number` here writes that file instead;
# empty means "no file", which is what a board-less repo looks like.
board_number = sys.argv[7] if len(sys.argv) > 7 else ""
import os
_bconf = os.path.join(human, ".claude", "guild", ".gld-sprint-99.board")
if not board_number:
    # ⚠ REMOVE it. Leaving a file from an earlier board-ON render made the board-OFF case read
    # that config and fire real calls — the D2 check passed for the wrong reason.
    if os.path.exists(_bconf):
        os.remove(_bconf)
else:
    d = os.path.dirname(_bconf)
    os.makedirs(d, exist_ok=True)
    with open(_bconf, "w") as fh:
        fh.write("number=%s\n" % board_number)
        fh.write("owner=@me\nfield=Guild board\nfield_needs_human=Needs human\n")
        fh.write("verified_as=tester\n")
        fh.write("col_ready=Ready\ncol_in_progress=In progress\ncol_blocked=Blocked\n")
        fh.write("col_in_review=In review\ncol_done=Done\n")
src = open(tpl).read()
for k, v in {
    "<PLUGIN_VERSION>": "0.0.0-test", "<TRACKER>": "99", "<ORDER>": order,
    "<OWNER_REPO>": "acme/widget", "<DEFAULT_BRANCH>": "develop",
    "<CONTAINER>": container, "<HUMAN_REPO>": human,
    "<DAG_PATH>": dag, "<INSTALL_CMDS>": install,
}.items():
    src = src.replace(k, v)
sys.stdout.write(src)
PY

echo "== A. syntax =="

# Control: the stderr-based check must SEE the placeholder errors. If this stops failing, a
# placeholder was resolved inside the template itself (or the detector broke).
if [ -n "$(syntax_err "$TPL")" ]; then
  ok "detector works: raw template reports errors (placeholders are literal)"
else
  bad "detector works: raw template reports errors" "clean — a placeholder must have been resolved in the template, or syntax_err is broken"
fi

"$PY" "$WORK/render.py" "$TPL" "101 102 103" "'yarn install'" "/tmp/gld-test-repo" > "$WORK/sup.sh"
E="$(syntax_err "$WORK/sup.sh")"
if [ -z "$E" ]; then ok "renders to valid bash"; else bad "renders to valid bash" "$E"; fi

"$PY" "$WORK/render.py" "$TPL" "" "" "/tmp/gld-test-repo" > "$WORK/sup_empty.sh"
E="$(syntax_err "$WORK/sup_empty.sh")"
if [ -z "$E" ]; then ok "renders to valid bash with an EMPTY order"; else bad "renders to valid bash with an EMPTY order" "$E"; fi

# An empty install list and a multi-step one must both parse. The single-string form used to
# be inlined directly, so an empty value produced `( cd "$WT" &&  )` — a PARSE error that no
# runtime guard can prevent. That is why INSTALL_CMDS is an array.
"$PY" "$WORK/render.py" "$TPL" "101" "'pnpm i --frozen-lockfile' 'pnpm build'" "/tmp/gld-test-repo" > "$WORK/sup_multi.sh"
E="$(syntax_err "$WORK/sup_multi.sh")"
if [ -z "$E" ]; then ok "renders to valid bash with MULTIPLE install steps"; else bad "renders to valid bash with MULTIPLE install steps" "$E"; fi

echo "== B. bash 3.2 compatibility =="

BAD3="$(grep -nE '^[^#]*(declare[[:space:]]+-A|mapfile|readarray)' "$TPL" || true)"
if [ -z "$BAD3" ]; then ok "no declare -A / mapfile / readarray"; else bad "no declare -A / mapfile / readarray" "$BAD3"; fi

# Show the trap this guards against so the rule is not folklore. ⚠ This case used to call
# ok() in ALL THREE branches — it could not fail, exactly the defect §12.2a found in
# batch_script_test.sh. The claim being tested is narrow and falsifiable: on THIS bash,
# `declare -A` must not be BOTH accepted by `-n` and accepted at runtime, because then the
# rule above cannot be validated here at all and the check is folklore for this host.
# ⚠ MEASURED, and worse than the rule's usual justification: on bash 3.2.57 `declare -A m`
# prints `declare: -A: invalid option` and the script CONTINUES — the final `m[a]=1` succeeds,
# so the whole script EXITS 0. It does not "die at runtime"; it runs on with a silently empty
# map. So neither `bash -n` nor the exit code can express this rule. Only stderr can.
printf '#!/bin/bash\ndeclare -A m\nm[a]=1\n' > "$WORK/assoc.sh"
"$SH" "$WORK/assoc.sh" 2>"$WORK/assoc.err" >/dev/null; ARC=$?
if [ -n "$(syntax_err "$WORK/assoc.sh")" ]; then
  ok "control: declare -A is a syntax error on this bash"
elif [ -s "$WORK/assoc.err" ]; then
  ok "control: declare -A passes -n and EXITS $ARC while erroring on stderr — why neither -n nor \$? is enough"
else
  bad "control: declare -A must be rejected somewhere on this host" \
      "silent success — this host cannot demonstrate the rule; run the suite on bash 3.2"
fi

echo "== C. verbatim core vs batch.md (§12.2) =="

cat > "$WORK/cmp.py" <<'PY'
import difflib, re, sys
tpl = open(sys.argv[1]).read()
batch = open(sys.argv[2]).read()
fences = [f for f in re.findall(r"```bash\n(.*?)\n```", batch, re.S)
          if "Guild Batch " in f and "LOG_DIR" in f]
if len(fences) != 1:
    print("ERR found %d supervisor fences in batch.md, want 1" % len(fences)); raise SystemExit(0)
fence = fences[0]

# BOTH sides are addressed by the same marker pair now. Content anchors were the earlier
# scheme and they made the region's BOUNDARIES untestable: whatever sat between the marker and
# the anchor was outside the comparison, so arbitrary code could be inserted there.
B_FROM = T_FROM = "# <!-- guild:supervisor-core:ratelimit -->"
B_TO = T_TO = "# <!-- /guild:supervisor-core:ratelimit -->"
try:
    b = fence[fence.index(B_FROM):fence.index(B_TO, fence.index(B_FROM))]
except ValueError:
    print("ERR batch.md's supervisor fence has no guild:supervisor-core:ratelimit markers")
    raise SystemExit(0)
try:
    t = tpl[tpl.index(T_FROM):tpl.index(T_TO)]
except ValueError:
    print("ERR template markers not found"); raise SystemExit(0)

# Comments are dropped from BOTH sides and nothing is truncated. The earlier version cut the
# template list at the batch region's first line — so arbitrary code could be inserted inside
# the marker, before the anchor, and still compare as identical (measured). Dropping comments
# symmetrically removes the need to truncate, and any inserted statement is a code line.
norm = lambda s: [l.strip() for l in s.splitlines()
                  if l.strip() and not l.strip().startswith("#")]
bl, tl = norm(b), norm(t)
d = list(difflib.unified_diff(bl, tl, "batch", "sprint", lineterm="", n=0))
print("OK %d code lines identical" % len(tl) if not d else "DIFF\n" + "\n".join(d[:24]))
PY
CMP="$("$PY" "$WORK/cmp.py" "$TPL" "$BATCH")"
case "$CMP" in
  OK*)  ok "ratelimit core is byte-identical to batch ($CMP)" ;;
  *)    bad "ratelimit core is byte-identical to batch" "$CMP" ;;
esac

for M in selfdelete emptyguard arms ratelimit; do
  O="$(grep -c "# <!-- guild:supervisor-core:$M -->" "$TPL" || true)"
  C="$(grep -c "# <!-- /guild:supervisor-core:$M -->" "$TPL" || true)"
  if [ "$O" = "1" ] && [ "$C" = "1" ]; then
    ok "marker pair :$M is balanced"
  else
    bad "marker pair :$M is balanced" "open=$O close=$C"
  fi
done

# The markers must be bash COMMENTS — a bare HTML comment is a syntax error, which is what
# broke the first design of this defence.
printf '#!/bin/bash\n<!-- x -->\n' > "$WORK/htm.sh"
if [ -n "$(syntax_err "$WORK/htm.sh")" ]; then
  ok "control: bare HTML comment is a bash syntax error (hence the comment prefix)"
else
  bad "control: bare HTML comment is a bash syntax error" "it parsed"
fi

echo "== D. structural rules =="

cat > "$WORK/arms.py" <<'PY'
import sys
src = open(sys.argv[1]).read()
want = ["*guild:needs-human*)", "*guild:done*)", "*guild:children*)"]
idx = []
for w in want:
    n = src.count(w)
    if n != 1:
        print("COUNT %s appears %d times, want 1" % (w, n)); raise SystemExit(0)
    idx.append(src.index(w))
print("OK" if idx == sorted(idx) else "WRONG %s" % (idx,))
PY
POS="$("$PY" "$WORK/arms.py" "$TPL")"
if [ "$POS" = "OK" ]; then
  ok "case arms: needs-human before done and children"
else
  bad "case arms: needs-human before done and children" "$POS"
fi

# ⚠ An allow-list, not a deny-list. Every deny-list form of this check was trivially
# bypassable (measured): `-f` instead of `--force`, `WTF=--force` then `$WTF`, and a `\\`
# line continuation putting `--force` on the next line all passed. So: tokenise each
# `worktree add|remove` invocation (joined across continuations) and reject ANY option that is
# not explicitly allowed, plus any unquoted `$` word — which is how indirection arrives.
cat > "$WORK/wt.py" <<'PY'
import re, shlex, sys
ALLOWED = {"--detach"}
lines = open(sys.argv[1]).read().splitlines()
joined, i = [], 0
while i < len(lines):
    ln, start = lines[i], i
    while ln.rstrip().endswith("\\") and i + 1 < len(lines):
        i += 1; ln = ln.rstrip()[:-1] + " " + lines[i]
    joined.append((start + 1, ln)); i += 1
problems = []
for no, ln in joined:
    st = ln.strip()
    if st.startswith("#") or "worktree" not in ln:
        continue
    # Only ACTUAL git invocations — an `echo "worktree add failed"` is not one.
    m = re.search(r"\bgit\s+(?:-C\s+\S+\s+)?worktree\s+(add|remove)\b(.*)$", ln)
    if not m:
        continue
    rest = m.group(2)
    for cut in ("&&", "||", ";", "|", "2>", ">"):     # stop at the next shell operator
        if cut in rest:
            rest = rest.split(cut)[0]
    try:
        toks = shlex.split(rest, comments=True)
    except ValueError:
        problems.append("%d: unparseable: %s" % (no, st)); continue
    for t in toks:
        if t.startswith("-") and t not in ALLOWED:
            problems.append("%d: disallowed option %r in: %s" % (no, t, st))
        # shlex strips quotes, so an unquoted "$X" is indistinguishable here; catch it in raw
    for raw in re.findall(r"(?<![\"'])\$\{?[A-Za-z_][A-Za-z_0-9]*\}?", rest):
        if ('"%s"' % raw) not in rest and ("'%s'" % raw) not in rest:
            problems.append("%d: unquoted %s (flag indirection hides here): %s" % (no, raw, st))
print("OK" if not problems else "\n".join(problems[:6]))
PY
WT="$("$PY" "$WORK/wt.py" "$TPL")"
if [ "$WT" = "OK" ]; then
  ok "worktree add/remove use only allow-listed options (no --force, no -f, no -b, no indirection)"
else
  bad "worktree add/remove use only allow-listed options" "$WT"
fi

# `cd` in ANY form — `cd "$SUP"`, `cd "${SUP}"`, `( cd "$SUP" && … )`. The old anchor required
# `cd` at the start of the line, so a subshell form passed; the template itself uses `( cd …`.
cat > "$WORK/cd.py" <<'PY'
import re, sys
problems = []
for no, ln in enumerate(open(sys.argv[1]).read().splitlines(), 1):
    if ln.strip().startswith("#"):
        continue
    # `CONTAINER="$(cd "$CONTAINER" && pwd -P)"` is path NORMALISATION, not entering the tree
    # to do work — it is the fix for the realpath mismatch and is explicitly allowed.
    if "pwd -P" in ln:
        continue
    for m in re.finditer(r"(?:^|[;&|(]|&&|\|\|)\s*cd\s+(\S+)", ln):
        arg = m.group(1)
        if re.search(r"\$\{?(SUP|CONTAINER)\b", arg):
            problems.append("%d: %s" % (no, ln.strip()))
print("OK" if not problems else "\n".join(problems[:4]))
PY
CD="$("$PY" "$WORK/cd.py" "$TPL")"
if [ "$CD" = "OK" ]; then
  ok "supervisor never cd's into the container or supervisor worktree (uses git -C)"
else
  bad "supervisor never cd's into the container or supervisor worktree" "$CD"
fi

if grep -q 'cd "$WT" && GLD_UNATTENDED=1' "$TPL"; then
  ok "child session runs inside the issue worktree"
else
  bad "child session runs inside the issue worktree" "the subshell cd is missing — isolation would be inert"
fi

if grep -q 'GLD_SPRINT_BASE=' "$TPL"; then ok "base is injected via GLD_SPRINT_BASE"; else bad "base is injected via GLD_SPRINT_BASE" "missing"; fi

if grep -q 'refs/remotes/origin/\$DEFAULT_BRANCH' "$TPL"; then
  ok "base refresh fetches into refs/remotes/"
else
  bad "base refresh fetches into refs/remotes/" "missing"
fi
if grep -q 'origin[[:space:]]*"\$DEFAULT_BRANCH:\$DEFAULT_BRANCH"' "$TPL"; then
  bad "no plain <b>:<b> refspec fetch" "found — that form is refused whenever the branch is checked out anywhere"
else
  ok "no plain <b>:<b> refspec fetch"
fi

# The label `case` needs its DEFAULT arm: without it an exit-0 child that reached no known
# label falls through silently and the Issue is counted done. ⚠ Scoped to the ARMS region — a
# file-wide grep for `*)` passes on any other case statement in the script, which is how a
# deleted default arm survived this check once already.
cat > "$WORK/defarm.py" <<'DEFARM'
import re, sys
src = open(sys.argv[1]).read()
O, C = "# <!-- guild:supervisor-core:arms -->", "# <!-- /guild:supervisor-core:arms -->"
try:
    region = src[src.index(O):src.index(C)]
except ValueError:
    print("ERR arms markers not found"); raise SystemExit(0)
arms = re.findall(r"^\s*([^\s].*?\))\s*$", region, re.M)
if any(a.strip() == "*)" for a in arms):
    print("OK")
else:
    print("MISSING default arm; arms found: %s" % arms)
DEFARM
DA="$("$PY" "$WORK/defarm.py" "$TPL")"
if [ "$DA" = "OK" ]; then
  ok "the label case has a default arm (an unknown label must not read as success)"
else
  bad "the label case has a default arm" "$DA"
fi

# The re-resume loop must stay BOUNDED. Raising the bound is invisible to every other check
# here, and an unbounded re-resume burns the whole rate-limit budget on one stuck Issue.
if grep -qE 'RESUME_TRIES" -le [1-3] \]' "$TPL"; then
  ok "re-resume is bounded at <= 3 attempts"
else
  bad "re-resume is bounded at <= 3 attempts" "$(grep -n 'RESUME_TRIES" -le' "$TPL" | head -2)"
fi

# The discovered-children query must exclude guild:done, or a child finished in an earlier
# run is re-queued on every pass and TOTAL grows without bound.
if grep -qF 'index(\"guild:done\") | not' "$TPL"; then
  ok "discovered-children query excludes guild:done"
else
  bad "discovered-children query excludes guild:done" "already-done children would be re-queued each run"
fi

# Truth is the LABEL, not the exit code (_handoff.md Section A). Removing this read and
# trusting exit 0 passed every earlier check while turning a mid-spine stop into "done".
if grep -q 'gh issue view "\$ISSUE"' "$TPL" && grep -q 'json labels' "$TPL"; then
  ok "completion is judged by reading the Issue's labels, not by exit 0"
else
  bad "completion is judged by reading the Issue's labels" "the gh issue view label read is missing"
fi

# worktree_acquire's STDOUT IS ITS RETURN VALUE. Any echo without >&2 inside it, and any
# `worktree add` without >/dev/null, corrupts the path — and link_memory then CREATES the
# corrupted path, so `cd` succeeds and the child runs outside the repo (measured).
cat > "$WORK/wtout.py" <<'PY'
import re, sys
# ⚠ Join line continuations and strip command substitutions REPEATEDLY. One pass of
# `\$\([^()]*\)` cannot remove a nested `$( $( ) )`, so the outer body's echo stayed visible;
# and a `worktree add` split across two lines hid its own `>/dev/null` (both measured).
raw = open(sys.argv[1]).read()
raw = re.sub(r"\\\n\s*", " ", raw)
lines = raw.splitlines()
start = next((i for i, l in enumerate(lines) if l.startswith("worktree_acquire()")), None)
if start is None:
    print("ERR worktree_acquire not found"); raise SystemExit(0)
end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
problems = []
for i in range(start, end):
    ln = lines[i]
    if ln.strip().startswith("#"):
        continue
    # An echo INSIDE $( … ) feeds that substitution, not this function's stdout — strip those
    # before judging, or a legitimate `x="$(… || echo 0)"` reads as a leak.
    outer, prev = ln, None
    while outer != prev:                      # peel nested $( … ) from the inside out
        prev = outer
        outer = re.sub(r"\$\([^()]*\)", "", outer)
    outer = re.sub(r"`[^`]*`", "", outer)     # and backtick substitution
    if re.search(r"\becho\b", outer) and ">&2" not in outer:
        problems.append("%d: echo without >&2: %s" % (i + 1, ln.strip()))
    if re.search(r"\bgit\s+(?:-C\s+\S+\s+)?worktree add", ln) and ">/dev/null" not in ln:
        problems.append("%d: worktree add without >/dev/null (it prints 'HEAD is now at' on "
                        "STDOUT): %s" % (i + 1, ln.strip()))
print("OK" if not problems else "\n".join(problems[:4]))
PY
WO="$("$PY" "$WORK/wtout.py" "$TPL")"
if [ "$WO" = "OK" ]; then
  ok "worktree_acquire writes NOTHING to stdout except the path"
else
  bad "worktree_acquire writes NOTHING to stdout except the path" "$WO"
fi

# marker_write's scratch files live in $D, so removing $D first makes the final write fail
# silently and the marker stays on the last `running` heartbeat (measured).
cat > "$WORK/order.py" <<'PY'
import sys
src = open(sys.argv[1]).read()
try:
    rm = src.index('rm -rf "$D"')
except ValueError:
    print("ERR no rm -rf $D"); raise SystemExit(0)
fin = src.find('marker_write "finished"')
if fin < 0:
    print("ERR no final marker_write"); raise SystemExit(0)
print("OK" if fin < rm else "WRONG rm -rf $D at %d precedes marker_write finished at %d" % (rm, fin))
PY
OR="$("$PY" "$WORK/order.py" "$TPL")"
if [ "$OR" = "OK" ]; then
  ok "state:finished is written BEFORE \$D is removed"
else
  bad "state:finished is written BEFORE \$D is removed" "$OR"
fi

# The supervisor worktree must actually be created — every `git -C "$SUP"` depends on it, and
# without it the whole run is a no-op that reports its dependents as merely "blocked".
if grep -q 'worktree add --detach "\$SUP"' "$TPL" && grep -q '^ensure_container || exit 1' "$TPL"; then
  ok "supervisor worktree is created, and before the main loop"
else
  bad "supervisor worktree is created, and before the main loop" \
      "without it every issue reports worktree-unavailable and the run does nothing"
fi

# `rev-parse --git-path` returns a path relative to THE REPO; this script never cd's, so the
# relative form resolved against the launch directory and the exclusions never landed.
if grep -q 'EXCLUDE="\$HUMAN_REPO/\$EXCLUDE"' "$TPL"; then
  ok "info/exclude path is absolutised (rev-parse --git-path returns a repo-relative path)"
else
  bad "info/exclude path is absolutised" \
      "the memory symlink would stay untracked, every worktree would be judged dirty, and none removed"
fi

# RL_TRIES must advance on EVERY rate-limit encounter. Incrementing it only in the no-reset
# branch meant an API that keeps reporting resetsAt never reached the cap.
cat > "$WORK/rl.py" <<'PY'
import sys
src = open(sys.argv[1]).read()
i = src.index("RL_TRIES=$((RL_TRIES + 1))")
guard = src.index('if [ -z "$WAIT" ] || [ "$WAIT" -le 0 ]; then', src.index("RATE_LIMITED"))
print("OK" if i < guard else "WRONG RL_TRIES is incremented inside the no-reset branch only")
PY
RL="$("$PY" "$WORK/rl.py" "$TPL")"
if [ "$RL" = "OK" ]; then
  ok "RL_TRIES advances on every rate-limit encounter (cap is reachable)"
else
  bad "RL_TRIES advances on every rate-limit encounter" "$RL"
fi

if grep -q 'WAIT" -gt "\$WAIT_MAX"' "$TPL"; then
  ok "rate-limit wait is clamped (a millisecond resetsAt is all-digits and yields ~56,000 years)"
else
  bad "rate-limit wait is clamped" "an unbounded wait heartbeats forever, so the duplicate-run guard reads it as healthy"
fi

if grep -q 'hb_sleep "\$WAIT"' "$TPL"; then
  ok "rate-limit wait uses the chunked hb_sleep"
else
  bad "rate-limit wait uses the chunked hb_sleep" "a bare sleep would go ~115 min without a heartbeat"
fi
# ANY indentation, including column 0 — the old `^[[:space:]]+` anchor let a column-0 form
# through. hb_sleep sleeps on "$chunk", never on "$WAIT", so this string is always wrong here.
if grep -qE '^[^#]*[^_]sleep "\$WAIT"' "$TPL"; then
  bad "no bare 'sleep \$WAIT' anywhere (hb_sleep sleeps on \$chunk)" "$(grep -n 'sleep "\$WAIT"' "$TPL" | head -2)"
else
  ok "no bare 'sleep \$WAIT' anywhere (hb_sleep sleeps on \$chunk)"
fi

# sprint_dag.py returns MEANINGFUL non-zero codes (base=2, depth=4, cycles=3). Under
# `set -e` + `pipefail` an unguarded command substitution in an assignment kills the run
# instead of letting the supervisor read the code as data.
cat > "$WORK/guard.py" <<'PY'
import re, sys
lines = open(sys.argv[1]).read().splitlines()
bad = []
for i, ln in enumerate(lines):
    # `"$DAG"`, `$DAG` and `${DAG}` — seeing only the quoted form let a caller drop the quotes
    # AND the guard together and pass. And `|| true` is not the only safe form: `|| RC=$?`,
    # `|| :` and `if ! …` all read the code as data under `set -e`, and the file itself uses the
    # first of those. Requiring the literal `|| true` rejected a better-written guard.
    if re.search(r"\$\{?DAG\}?", ln) and "#" != ln.strip()[:1]:
        window = " ".join(lines[i:i + 3])
        if not re.search(r"\|\|\s*(true|:|[A-Z_]+=\$\?)", window):
            bad.append("%d: %s" % (i + 1, ln.strip()))
print("OK" if not bad else "\n".join(bad))
PY
# ⚠ `${DAG}` too, and NOT inside a comment. `\$(PY|DAG)` as a literal missed the braced form,
# and `${DAG}` combined with a removed `|| true` passed BOTH this and the guard check below
# (measured). Conversely, a comment that says "always quote $DAG" used to FAIL this check — so
# documenting the rule broke the rule's test.
cat > "$WORK/quote.py" <<'QUOTEPY'
import re, sys
bad = []
for no, ln in enumerate(open(sys.argv[1]).read().splitlines(), 1):
    if ln.strip().startswith("#"):
        continue
    code = ln.split("#", 1)[0] if " #" in ln else ln
    for m in re.finditer(r'(?<!")\$\{?(PY|DAG)\}?(?!")', code):
        seg = code[max(0, m.start() - 1):m.end() + 1]
        if seg.startswith('"') and seg.endswith('"'):
            continue
        bad.append("%d: %s" % (no, ln.strip()))
        break
print("OK" if not bad else "\n".join(bad[:3]))
QUOTEPY
QT="$("$PY" "$WORK/quote.py" "$TPL")"
if [ "$QT" = "OK" ]; then
  ok "\$PY and \$DAG are always quoted, braced form included (rendered paths may contain spaces)"
else
  bad "\$PY and \$DAG are always quoted, braced form included" "$QT"
fi

G="$("$PY" "$WORK/guard.py" "$TPL")"
if [ "$G" = "OK" ]; then
  ok "every sprint_dag.py call guards its exit code"
else
  bad "every sprint_dag.py call guards its exit code" "$G"
fi

# The heredoc trap that cost a round: a `|| { … }` whose closing brace lands on the next line
# is eaten by the heredoc body.
if grep -qE "<<'PY'.*\|\|[[:space:]]*\{[[:space:]]*$" "$TPL"; then
  bad "no '|| {' at the end of a heredoc opener" "the closing brace would be swallowed by the heredoc body"
else
  ok "no '|| {' at the end of a heredoc opener"
fi

cat > "$WORK/prune.py" <<'PRUNE'
import re, sys
lines = open(sys.argv[1]).read().splitlines()
try:
    fn_start = next(i for i, l in enumerate(lines) if l.startswith("prune_safe()"))
except StopIteration:
    print("MISSING prune_safe is not defined"); raise SystemExit(0)
fn_end = next(i for i in range(fn_start + 1, len(lines)) if lines[i] == "}")
outside = []
for i, l in enumerate(lines):
    if fn_start <= i <= fn_end or l.strip().startswith("#"):
        continue
    if "worktree prune" in l:
        outside.append("%d: %s" % (i + 1, l.strip()))
body = lines[fn_start:fn_end]
# The guard must come BEFORE the prune, not merely exist somewhere in the function.
guard_at = next((i for i, l in enumerate(body) if "foreign" in l and "=1" in l), None)
prune_at = next((i for i, l in enumerate(body) if "worktree prune" in l
                 and not l.strip().startswith("#")), None)
if outside:
    print("BARE prune outside prune_safe:\n" + "\n".join(outside[:3]))
elif guard_at is None:
    print("UNGUARDED prune_safe does not detect a prunable entry outside $CONTAINER")
elif prune_at is None:
    print("EMPTY prune_safe never prunes anything")
elif guard_at > prune_at:
    print("ORDER prune_safe prunes at line %d, before its guard at line %d"
          % (prune_at + 1, guard_at + 1))
else:
    print("OK")
PRUNE
PR="$("$PY" "$WORK/prune.py" "$TPL")"
if [ "$PR" = "OK" ]; then
  ok "every \`worktree prune\` goes through prune_safe, which refuses when a FOREIGN entry is prunable"
else
  bad "every \`worktree prune\` goes through prune_safe" \
      "$PR — prune takes no path argument, so it would drop a registration of the human's"
fi

# ── signal handling ──────────────────────────────────────────────────────────
# `trap cleanup EXIT INT TERM` was wrong: bash runs the handler and then CARRIES ON, so a
# `kill` did not stop the run, the loop overwrote `halted:interrupted` with `finished`, and
# COMPLETED reached 1 — a killed run reported success and deleted its own re-run script.
cat > "$WORK/sig.py" <<'SIGPY'
import re, sys
src = open(sys.argv[1]).read()
problems = []
if re.search(r"^trap\s+cleanup\s+EXIT\s+\w", src, re.M):
    problems.append("cleanup is trapped on a SIGNAL as well as EXIT; the handler does not exit, "
                    "so the script continues and overwrites state:finished")
# ⚠ Parse the trap's SIGNAL LIST, do not pattern-match the whole line. `\s*$` rejected a
# trailing comment (this file's dominant style) and one greedy group saw only the LAST signal,
# so `trap '…' TERM HUP` read as "no TERM trap" (measured). And derive the handler NAME from the
# trap instead of hardcoding `on_signal` — the check should test the wiring, not the naming.
handler, sigs = None, set()
for m in re.finditer(r"^\s*trap\s+(\S+|'[^']*'|\"[^\"]*\")\s+([A-Za-z0-9 ]+?)\s*(?:#.*)?$", src, re.M):
    action, names = m.group(1), m.group(2).split()
    sigs.update(names)
    if "EXIT" not in names:
        h = re.search(r"([A-Za-z_][A-Za-z_0-9]*)", action.strip("'\""))
        if h:
            handler = h.group(1)
if "TERM" not in sigs:
    problems.append("no TERM trap — `kill` is how a human stops an unattended run")
m = re.search(r"^%s\(\)\s*\{(.*?)^\}" % re.escape(handler or "on_signal"), src, re.M | re.S)
if not m:
    problems.append("the signal trap's handler (%s) is not defined" % (handler or "on_signal"))
elif not re.search(r"\bexit\b", m.group(1)):
    problems.append("on_signal does not exit, so the run continues after the signal")
elif re.search(r"\bexit\s+0\b", m.group(1)):
    problems.append("on_signal exits 0 — a killed run would report success to whatever launched it")
# Ctrl-C cannot be handled for a background job of a non-interactive shell (SIGINT arrives
# SIG_IGN and cannot be reset). Claiming otherwise sends the reader down a dead end.
# ⚠ Judge inside the SAME comment block. Searching the whole file for "cannot be" matched three
# unrelated lines, so a comment that positively claimed "Ctrl-C IS handled" passed (measured).
# Judge the CLAIM, not the presence of a disclaimer. Looking for "cannot be …" anywhere let a
# comment assert "Ctrl-C IS handled" while a later line in the same block still carried the
# disclaimer — contradictory, and green (measured).
for m in re.finditer(r"^#.*Ctrl-C.*$", src, re.M):
    line = m.group(0)
    if re.search(r"Ctrl-C\s+(IS|is)\s+(handled|caught|trapped)"
                 r"|handles?\s+Ctrl-C"
                 r"|catch(es)?\s+Ctrl-C", line):
        problems.append("a comment claims Ctrl-C is handled, which is impossible for a "
                        "background job of a non-interactive shell: %s" % line.strip()[:70])
        continue
    start = src.rfind("\n\n", 0, m.start())
    end = src.find("\n\n", m.end())
    block = src[(start if start >= 0 else 0):(end if end >= 0 else len(src))]
    if not re.search(r"cannot be (trapped|handled|reset|delivered)|not one of the cases", block):
        problems.append("a comment mentions Ctrl-C without saying it cannot be handled: %s"
                        % line.strip()[:70])
print("OK" if not problems else "; ".join(problems))
SIGPY
SG="$("$PY" "$WORK/sig.py" "$TPL")"
if [ "$SG" = "OK" ]; then
  ok "signal traps are separate from EXIT and they exit (a killed run must not report finished)"
else
  bad "signal traps are separate from EXIT and they exit" "$SG"
fi

# ── the member set is not the queue ─────────────────────────────────────────
# Writing only the queue drops a member that already reached guild:done, and `--mode base`
# then answers DEFAULT for its dependants — the PR stack collapses onto the default branch.
# ⚠ Two tokens in the same paragraph, not a frozen sentence. Requiring the exact wording
# `every row of the member table, not just the queue` meant re-phrasing the instruction — normal
# work on an LLM prompt — reported a design regression (measured).
if "$PY" - "$RUNMD" <<'MEMPY'
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
# Anchor on the numbered STEP that writes the file, and stop at the next step. A loose
# `find("members.json")`-to-`\n2.` slice fell through to the end of the file when the step was
# rewritten, and then matched the required phrases somewhere else entirely (measured).
m = re.search(r"^1\.\s+\*\*Write `members\.json`\*\*(.*?)^\s*2\.\s", src, re.M | re.S)
if not m:
    print("no numbered `Write members.json` step found", file=sys.stderr)
    raise SystemExit(1)
step = m.group(1)
ok = ("member table" in step
      and re.search(r"not (just|only) the queue|whole member (set|table)|every row", step)
      and not re.search(r"one entry per queued member", step))
raise SystemExit(0 if ok else 1)
MEMPY
then
  ok "run.md writes members.json for the WHOLE member set, not the queue"
else
  bad "run.md writes members.json for the WHOLE member set" \
      "a resume would drop done members and silently lose the PR stack"
fi

# ── an ambiguous branch is a BLOCK, and it reports its own reason ───────────
cat > "$WORK/amb.py" <<'AMBPY'
import re, sys
src = open(sys.argv[1]).read()
m = re.search(r"^worktree_acquire\(\)\s*\{(.*?)^\}", src, re.M | re.S)
if not m:
    print("ERR worktree_acquire not found"); raise SystemExit(0)
body = m.group(1)
problems = []
i = body.find("-gt 1")
if i < 0:
    problems.append("no multi-candidate guard")
else:
    # ⚠ Block boundary, not a byte window. A 700-char window left 148 characters of slack in a
    # file whose comment-to-code ratio is 3:1, so adding two explanatory comments inside the arm
    # made the check report "does not return 2" while `return 2` sat right there (measured).
    arm = body[i:body.find("\n  fi", i) if body.find("\n  fi", i) > i else i + 1200]
    arm_code = "\n".join(l for l in arm.splitlines() if not l.strip().startswith("#"))
    if "wt.err" not in arm_code:
        problems.append("the ambiguous arm does not write $D/wt.err, so the caller reports the "
                        "PREVIOUS issue's error as the reason")
    if "return 2" not in arm:
        problems.append("the ambiguous arm does not return 2, so it cannot be told apart from a failure")
# and one match must be announced, not assumed silently
if "branch-assumed" not in body:
    problems.append("a single token match is accepted without recording the assumption")
# ⚠ the FIRST occurrence is inside a comment in the function itself; take the real call site.
call = [i for i, l in enumerate(src.splitlines())
        if l.strip().startswith('WT="$(worktree_acquire')]
caller = "\n".join(src.splitlines()[call[0]:call[0] + 30]) if call else ""
# ⚠ Any comparison against 2, in either direction. Requiring the literal `-eq 2` rejected an
# equivalent `-ne 2` with the branches swapped (measured) — the claim is that the caller
# DISTINGUISHES rc=2, not that it spells the test one way.
if not re.search(r"(-eq|-ne|==|!=)\s*2\b", caller):
    problems.append("the caller does not distinguish rc=2 from a failure")
print("OK" if not problems else "; ".join(problems))
AMBPY
AM="$("$PY" "$WORK/amb.py" "$TPL")"
if [ "$AM" = "OK" ]; then
  ok "an ambiguous branch blocks with its own reason; a single match is recorded, not silent"
else
  bad "an ambiguous branch blocks with its own reason" "$AM"
fi

# ── a MERGED PR outranks a recorded failure ────────────────────────────────
# (The "a MERGED PR outranks a stale failed.txt entry" grep lived here. It asserted the shape
# of one python line, and an inverted `and`→`or` in that same line passed it (measured). §H3 now
# runs the real thing on real input, which is what the claim was always about — a grep of a
# line's spelling was never evidence that the precedence works.)

echo "== E. execution smoke =="

mkdir -p "$WORK/repo"
git -C "$WORK/repo" init -q 2>/dev/null || true
"$PY" "$WORK/render.py" "$TPL" "" "" "$WORK/repo" > "$WORK/smoke.sh"
SMOKE_OUT="$("$SH" "$WORK/smoke.sh" 2>&1)"; SMOKE_RC=$?
if [ "$SMOKE_RC" -eq 0 ] && printf '%s' "$SMOKE_OUT" | grep -q "No members to run"; then
  ok "empty order exits 0 with a clear message"
else
  bad "empty order exits 0 with a clear message" "rc=$SMOKE_RC out=$(printf '%s' "$SMOKE_OUT" | head -3)"
fi


echo "== F. end-to-end: a real 2-issue stack, run to completion =="
# ⚠ THIS is the section that was missing, and its absence is why every defect below shipped
# past 179 green cases. Section E renders with an EMPTY order, so it exits at the empty guard
# without touching $SUP, worktree_acquire, marker_write, the ledger or `rm -rf "$D"` — i.e.
# without executing the supervisor's actual job. One issue in the queue is all it took.
#
# What is faked: `gh` (a shell stub over JSON files) and `claude` (a stub that does what the
# spine does — cut a branch from $GLD_SPRINT_BASE, commit, push, register a PR). What is REAL:
# git, the worktrees, the branches, the refs, sprint_dag.py, and the whole supervisor script.

if ! command -v git >/dev/null 2>&1; then
  echo "  SKIP  end-to-end (git not available)"
else
E="$WORK/e2e"
mkdir -p "$E/bin"
git init -q --bare "$E/origin.git"
git init -q -b develop "$E/repo" 2>/dev/null || { git init -q "$E/repo"; git -C "$E/repo" symbolic-ref HEAD refs/heads/develop; }
git -C "$E/repo" config user.email t@example.invalid
git -C "$E/repo" config user.name  tester
mkdir -p "$E/repo/.claude/guild"
printf 'memory/\n' > "$E/repo/.claude/guild/.gitignore"
printf 'x\n' > "$E/repo/a.txt"
git -C "$E/repo" add -A >/dev/null 2>&1
git -C "$E/repo" commit -qm init >/dev/null 2>&1
git -C "$E/repo" remote add origin "$E/origin.git"
git -C "$E/repo" push -q -u origin develop >/dev/null 2>&1

cat > "$E/bin/gh" <<'GHEOF'
#!/bin/bash
ARGS="$*"
case "$ARGS" in
  *"issues/99/comments"*)          echo '[]' ;;
  "issue comment"*)                echo "MARKER_CREATE" >> "$E_TRACE"; exit 0 ;;
  *"-X PATCH"*)                    echo "MARKER_PATCH" >> "$E_TRACE"; exit 0 ;;
  "pr list"*)                      cat "$E_PRS" ;;
  "issue list"*guild:child*)       : ;;
  "issue list"*)                   cat "$E_ISSUES" ;;
  "issue view"*)                   cat "$E_STATE" ;;
  "issue edit"*)                   exit 0 ;;
  *)                               echo '[]' ;;
esac
GHEOF
cat > "$E/bin/claude" <<'CLEOF'
#!/bin/bash
# Stand-in for the spine: it must behave like _execute_spine.md Step 0 + Step 5.
ISSUE="$(printf '%s' "$*" | sed -n 's/.*\/gld dev \([0-9]*\).*/\1/p')"
{ echo "RAN=$ISSUE"
  echo "PWD_$ISSUE=$PWD"
  echo "ISREPO_$ISSUE=$(git rev-parse --is-inside-work-tree 2>/dev/null || echo NO)"
  echo "BASE_$ISSUE=$GLD_SPRINT_BASE"
  echo "ANCESTOR_$ISSUE=$(git merge-base --is-ancestor "$GLD_SPRINT_BASE" HEAD 2>/dev/null && echo yes || echo no)"
} >> "$E_TRACE"
B="feature/#${ISSUE}-work"
git switch --no-track -c "$B" "$GLD_SPRINT_BASE" >/dev/null 2>&1 || exit 3
printf 'work %s\n' "$ISSUE" > "f${ISSUE}.txt"
git add -A >/dev/null 2>&1
git -c user.email=t@example.invalid -c user.name=tester commit -qm "feat: $ISSUE" >/dev/null 2>&1
git push -q -u origin "$B" >/dev/null 2>&1
"$E_PY" - "$E_PRS" "$ISSUE" "$B" <<'PY'
import json, sys
p, i, b = sys.argv[1], int(sys.argv[2]), sys.argv[3]
d = json.load(open(p))
d.append({"number": 200 + i, "headRefName": b, "baseRefName": "develop", "state": "OPEN",
          "mergedAt": None, "reviewDecision": None,
          "closingIssuesReferences": [{"number": i}]})
json.dump(d, open(p, "w"))
PY
echo '{"type":"result","is_error":false,"usage":{"input_tokens":1,"output_tokens":1}}'
CLEOF
chmod +x "$E/bin/gh" "$E/bin/claude"

export E_TRACE="$E/trace.txt" E_PRS="$E/prs.json" E_ISSUES="$E/issues.json"
export E_STATE="$E/state.txt" E_PY="$PY"
: > "$E_TRACE"; echo '[]' > "$E_PRS"
echo '[{"number":101,"labels":[]},{"number":102,"labels":[]}]' > "$E_ISSUES"
printf 'guild:done\n' > "$E_STATE"

DAGPY="$HERE/../skills/gld/commands/atoms/sprint_dag.py"
"$PY" "$WORK/render.py" "$TPL" "101 102" "" "$E/repo" "$E/cont" "$DAGPY" > "$E/sup.sh"
mkdir -p "$E/repo/.claude/guild/.sprint-logs/99/dag"
printf '[{"number":101,"base_deps":[],"split":false},{"number":102,"base_deps":[101],"split":false}]\n' \
  > "$E/repo/.claude/guild/.sprint-logs/99/dag/members.json"
cp "$E/sup.sh" "$E/repo/.claude/guild/.gld-sprint-99.sh"

# Run from a NEUTRAL cwd: the supervisor must never depend on where it was launched.
mkdir -p "$E/neutral"
E2E_OUT="$(cd "$E/neutral" && PATH="$E/bin:$PATH" "$SH" "$E/repo/.claude/guild/.gld-sprint-99.sh" 2>&1)"
E2E_RC=$?
TR="$(cat "$E_TRACE" 2>/dev/null || true)"

_has() { printf '%s' "$2" | grep -qF "$1"; }

if [ "$E2E_RC" -eq 0 ] && _has "Done: 2" "$E2E_OUT" && _has "Failed: 0" "$E2E_OUT"; then
  ok "e2e: both members reach guild:done"
else
  bad "e2e: both members reach guild:done" "rc=$E2E_RC $(printf '%s' "$E2E_OUT" | grep -E 'Total:|FAIL|✗' | head -3)"
fi

if _has "BASE_101=origin/develop" "$TR" && _has "BASE_102=feature/#101-work" "$TR"; then
  ok "e2e: the PR STACK forms — #102's base is #101's branch, not the default branch"
else
  bad "e2e: the PR stack forms" "$(printf '%s' "$TR" | grep '^BASE_' | tr '\n' ' ')"
fi

if _has "ISREPO_101=true" "$TR" && _has "ISREPO_102=true" "$TR"; then
  ok "e2e: each child runs inside a real git worktree"
else
  bad "e2e: each child runs inside a real git worktree" \
      "$(printf '%s' "$TR" | grep -E '^(ISREPO|PWD)_' | tr '\n' ' ') — a polluted \$WT would land it outside the repo"
fi

if _has "ANCESTOR_101=yes" "$TR" && _has "ANCESTOR_102=yes" "$TR"; then
  ok "e2e: each worktree really is cut from its injected base"
else
  bad "e2e: each worktree really is cut from its injected base" "$(printf '%s' "$TR" | grep '^ANCESTOR_' | tr '\n' ' ')"
fi

EXC="$E/repo/.git/info/exclude"
if grep -q '\.claude/guild/memory' "$EXC" 2>/dev/null \
   && grep -q '\.claude/guild/\.sprint-logs' "$EXC" 2>/dev/null; then
  ok "e2e: the gitignored infra is registered in the REAL repo's info/exclude"
else
  bad "e2e: the gitignored infra is registered in the REAL repo's info/exclude" \
      "rev-parse --git-path returns a REPO-relative path; resolved against the launch dir it lands nowhere"
fi

if [ ! -e "$E/neutral/.git" ]; then
  ok "e2e: nothing is written outside the declared paths (no stray .git at the launch dir)"
else
  bad "e2e: nothing is written outside the declared paths" "a .git appeared at the launch directory"
fi

if [ -z "$(git -C "$E/repo" status --porcelain 2>/dev/null)" ]; then
  ok "e2e: the human's working tree is untouched"
else
  bad "e2e: the human's working tree is untouched" "$(git -C "$E/repo" status --porcelain | head -3)"
fi

if [ ! -d "$E/cont" ] || [ -z "$(ls -A "$E/cont" 2>/dev/null)" ]; then
  ok "e2e: every worktree is released and the container is cleaned"
else
  bad "e2e: every worktree is released and the container is cleaned" "left: $(ls -A "$E/cont" | tr '\n' ' ')"
fi

if [ ! -f "$E/repo/.claude/guild/.gld-sprint-99.sh" ]; then
  ok "e2e: a clean run deletes its own script"
else
  bad "e2e: a clean run deletes its own script" "the script is still there after Done: 2"
fi

# The marker must be written at least once per issue plus the final `finished`.
MC="$(printf '%s' "$TR" | grep -c 'MARKER_' || true)"
if [ "${MC:-0}" -ge 3 ]; then
  ok "e2e: the run marker is written throughout and at the end ($MC writes)"
else
  bad "e2e: the run marker is written throughout and at the end" "only $MC writes — heartbeats or state:finished are missing"
fi

# ── F2: a FAILING child must be classified, recorded, and must block dependents ──
E2="$WORK/e2e_fail"
mkdir -p "$E2/bin" "$E2/neutral2"
git init -q --bare "$E2/origin.git"
git init -q -b develop "$E2/repo" 2>/dev/null || { git init -q "$E2/repo"; git -C "$E2/repo" symbolic-ref HEAD refs/heads/develop; }
git -C "$E2/repo" config user.email t@example.invalid
git -C "$E2/repo" config user.name  tester
mkdir -p "$E2/repo/.claude/guild"
printf 'memory/\n' > "$E2/repo/.claude/guild/.gitignore"
printf 'x\n' > "$E2/repo/a.txt"
git -C "$E2/repo" add -A >/dev/null 2>&1
git -C "$E2/repo" commit -qm init >/dev/null 2>&1
git -C "$E2/repo" remote add origin "$E2/origin.git"
git -C "$E2/repo" push -q -u origin develop >/dev/null 2>&1
cp "$E/bin/gh" "$E2/bin/gh"
# ⚠ It must FAIL *AFTER* leaving a branch behind — that is the only shape that tests
# `terminal:failed`. A stub that dies immediately leaves #101 with no branch, so #102 comes
# back `dep-no-branch` whether or not the failure ever reached the DAG input, and the
# assertion below would pass with the producer deleted.
cat > "$E2/bin/claude" <<'CLFAIL'
#!/bin/bash
ISSUE="$(printf '%s' "$*" | sed -n 's/.*\/gld dev \([0-9]*\).*/\1/p')"
B="feature/#${ISSUE}-work"
git switch --no-track -c "$B" "$GLD_SPRINT_BASE" >/dev/null 2>&1
printf 'partial %s\n' "$ISSUE" > "f${ISSUE}.txt"
git add -A >/dev/null 2>&1
git -c user.email=t@example.invalid -c user.name=tester commit -qm "wip: $ISSUE" >/dev/null 2>&1
git push -q -u origin "$B" >/dev/null 2>&1
echo '{"type":"result","is_error":true,"result":"boom"}'
exit 1
CLFAIL
chmod +x "$E2/bin/gh" "$E2/bin/claude"
: > "$E2/trace.txt"; echo '[]' > "$E2/prs.json"
echo '[{"number":101,"labels":[]},{"number":102,"labels":[]}]' > "$E2/issues.json"
printf 'guild:execute\n' > "$E2/state.txt"
mkdir -p "$E2/repo/.claude/guild/.sprint-logs/99/dag"
printf '[{"number":101,"base_deps":[],"split":false},{"number":102,"base_deps":[101],"split":false}]\n' \
  > "$E2/repo/.claude/guild/.sprint-logs/99/dag/members.json"
"$PY" "$WORK/render.py" "$TPL" "101 102" "" "$E2/repo" "$E2/cont" "$DAGPY" > "$E2/sup.sh"
cp "$E2/sup.sh" "$E2/repo/.claude/guild/.gld-sprint-99.sh"
F_OUT="$(cd "$E2/neutral2" && E_TRACE="$E2/trace.txt" E_PRS="$E2/prs.json" E_ISSUES="$E2/issues.json" \
         E_STATE="$E2/state.txt" E_PY="$PY" PATH="$E2/bin:$PATH" \
         "$SH" "$E2/repo/.claude/guild/.gld-sprint-99.sh" 2>&1)"
[ -n "${GLD_E2E_DEBUG:-}" ] && { echo "--- F2 OUT ---"; printf '%s\n' "$F_OUT"; }
FJ="$E2/repo/.claude/guild/.sprint-logs/99/failures.jsonl"
if [ -f "$FJ" ] && grep -q '"class"' "$FJ"; then
  ok "e2e: a failure is recorded to failures.jsonl, where a LATER session can read it"
else
  bad "e2e: a failure is recorded to failures.jsonl" \
      "the class exists only on the supervisor's stdout, which \`daily\` cannot read"
fi
# #101 failed but DID leave a branch, so only `terminal:failed` can stop #102 — the
# branch-name fallback would happily hand `feature/#101-work` back as its base.
if _has "Failed: 1" "$F_OUT" && _has "Blocked: 1" "$F_OUT" \
   && printf '%s' "$F_OUT" | grep -q 'dep-failed'; then
  ok "e2e: a failed member BLOCKS its dependents even though it left a branch (terminal:failed)"
else
  bad "e2e: a failed member blocks its dependents even though it left a branch" \
      "$(printf '%s' "$F_OUT" | grep -E 'Total:|⊘' | head -2) — without terminal:failed, #102 stacks onto broken work"
fi
if [ -f "$E2/repo/.claude/guild/.gld-sprint-99.sh" ]; then
  ok "e2e: a run with failures KEEPS its script (it is the record of what it would do)"
else
  bad "e2e: a run with failures keeps its script" "a 100%-failed run deleted its own evidence"
fi
fi


echo "== H. end-to-end: the control flow the grep checks never execute =="
# ⚠ WHY THIS EXISTS. Round 5 found three BLOCKERs living under a fully green suite, and the
# reason was uniform: the checks added for those code paths were regexes. They assert what the
# implementation is WRITTEN as, not what it DOES — so an infinite loop, a stdout leak and an
# inverted precedence all passed. §F already had a real harness; these cases put the new control
# flow through it.
#
# Faked: `gh` and `claude` (shell stubs). Real: git, the worktrees, the branches, and the whole
# supervisor script.

if ! command -v git >/dev/null 2>&1; then
  echo "  SKIP  end-to-end control flow (git not available)"
else
H="$WORK/h"
mkdir -p "$H/bin" "$H/neutral"

# hrepo — a fresh repo + bare origin for one scenario
hrepo() {
  local d="$H/$1"
  git init -q --bare "$d.git"
  git init -q -b develop "$d" 2>/dev/null || { git init -q "$d"; git -C "$d" symbolic-ref HEAD refs/heads/develop; }
  git -C "$d" config user.email t@example.invalid
  git -C "$d" config user.name  tester
  mkdir -p "$d/.claude/guild"
  printf 'memory/\n' > "$d/.claude/guild/.gitignore"
  printf 'x\n' > "$d/a.txt"
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" commit -qm init >/dev/null 2>&1
  git -C "$d" remote add origin "$d.git"
  git -C "$d" push -q -u origin develop >/dev/null 2>&1
  mkdir -p "$d/.claude/guild/.sprint-logs/99/dag"
}

# hrender <repo> <order> <container> -> path of the rendered script
hrender() {
  "$PY" "$WORK/render.py" "$TPL" "$2" "" "$1" "$3" "$DAGPY"
}

# ── H1. a split parent is BOUNDED even when the child count never settles ────
# Round 5 measured 79 child sessions in 25s on an empty `gh` reply, and 62 on a count that
# oscillated 3→2→3→2. Both spawn `claude -p` without limit: real money, and `kill` is deferred.
hrepo split
cat > "$H/bin/gh" <<'GHSPLIT'
#!/bin/bash
case "$*" in
  *"issues/99/comments"*) echo '[]' ;;
  "issue comment"*|*"-X PATCH"*) exit 0 ;;
  "pr list"*) echo '[]' ;;
  "issue list"*guild:child*)
      I=$(cat "$H_IDX"); N=$(sed -n "$((I+1))p" "$H_SEQ"); [ -z "$N" ] && N=$(tail -1 "$H_SEQ")
      echo $((I+1)) > "$H_IDX"
      [ "$N" = "E" ] || echo "$N" ;;
  "issue list"*) echo '[{"number":101,"labels":[]}]' ;;
  "issue view"*) echo 'guild:children' ;;
  "issue edit"*) exit 0 ;;
  *) echo '[]' ;;
esac
GHSPLIT
printf '#!/bin/bash\necho S >> "$H_SPAWN"\necho %s\n' '{"type":"result","is_error":false,"usage":{}}' > "$H/bin/claude"
chmod +x "$H/bin/gh" "$H/bin/claude"
printf '[{"number":101,"base_deps":[],"split":false}]\n' > "$H/split/.claude/guild/.sprint-logs/99/dag/members.json"
hrender "$H/split" "101" "$H/split_c" > "$H/split.sh"

split_run() {   # split_run <sequence>  -> echoes "<rc> <spawns>"
  printf '%s\n' $1 > "$H/seq.txt"; echo 0 > "$H/idx.txt"; : > "$H/spawn.txt"
  rm -rf "$H/split_c"
  local out rc
  out="$(cd "$H/neutral" && PATH="$H/bin:$PATH" H_SEQ="$H/seq.txt" H_IDX="$H/idx.txt" \
        H_SPAWN="$H/spawn.txt" timeout 60 "$SH" "$H/split.sh" 2>&1)"; rc=$?
  printf '%s %s' "$rc" "$(grep -c S "$H/spawn.txt" 2>/dev/null || echo 0)"
}

R="$(split_run "E E E E E E E E E E E E E E E E E E E E E E E E")"
set -- $R
if [ "$1" -eq 0 ] && [ "$2" -le 6 ]; then
  ok "e2e: an EMPTY child count is bounded ($2 sessions) — it used to be unbounded"
else
  bad "e2e: an EMPTY child count is bounded" "rc=$1 sessions=$2 (124 = it hung)"
fi

R="$(split_run "3 2 3 2 3 2 3 2 3 2 3 2 3 2 3 2 3 2 3 2 3 2 3 2")"
set -- $R
if [ "$1" -eq 0 ] && [ "$2" -le 16 ]; then
  ok "e2e: an OSCILLATING child count is bounded ($2 sessions) — progress alone never ran out"
else
  bad "e2e: an OSCILLATING child count is bounded" "rc=$1 sessions=$2 (124 = it hung)"
fi

R="$(split_run "4 3 2 1 0 0 0 0 0 0")"
set -- $R
if [ "$1" -eq 0 ] && [ "$2" -ge 5 ] && [ "$2" -le 12 ]; then
  ok "e2e: a DECREASING count keeps going while it advances ($2 sessions)"
else
  bad "e2e: a DECREASING count keeps going while it advances" "rc=$1 sessions=$2 — a stalled bound would cut it short"
fi

# ── H2. worktree_acquire's stdout stays clean even when record_event FAILS ───
# `_record`'s warning used to go to stdout, and worktree_acquire's stdout IS its return value:
# the child ran outside the repo while the run reported Done: 1 and deleted its own script.
hrepo leak
git -C "$H/leak" branch chore/101-notes >/dev/null 2>&1     # a human's scratch branch
cat > "$H/bin/gh" <<'GHLEAK'
#!/bin/bash
case "$*" in
  *"issues/99/comments"*) echo '[]' ;;
  "issue comment"*|*"-X PATCH"*) exit 0 ;;
  "pr list"*) echo '[]' ;;
  "issue list"*guild:child*) : ;;
  "issue list"*) echo '[{"number":101,"labels":[]}]' ;;
  "issue view"*) echo 'guild:done' ;;
  "issue edit"*) exit 0 ;;
  *) echo '[]' ;;
esac
GHLEAK
cat > "$H/bin/claude" <<'CLLEAK'
#!/bin/bash
{ echo "PWD=$PWD"; echo "ISREPO=$(git rev-parse --is-inside-work-tree 2>/dev/null || echo NO)"; } >> "$H_TRACE"
echo '{"type":"result","is_error":false,"usage":{}}'
CLLEAK
chmod +x "$H/bin/gh" "$H/bin/claude"
printf '[{"number":101,"base_deps":[],"split":false}]\n' > "$H/leak/.claude/guild/.sprint-logs/99/dag/members.json"
# make the event log unwritable so _record fails and warns
mkdir -p "$H/leak/.claude/guild/.sprint-logs/99/failures.jsonl"
hrender "$H/leak" "101" "$H/leak_c" > "$H/leak.sh"
: > "$H/trace.txt"
LEAK_OUT="$(cd "$H/neutral" && PATH="$H/bin:$PATH" H_TRACE="$H/trace.txt" \
           timeout 60 "$SH" "$H/leak.sh" 2>&1)" || true
if grep -q 'ISREPO=true' "$H/trace.txt" 2>/dev/null; then
  ok "e2e: the child runs inside the repo even when record_event fails (no stdout leak)"
else
  bad "e2e: the child runs inside the repo even when record_event fails" \
      "$(grep '^ISREPO' "$H/trace.txt" 2>/dev/null | head -1) — a warning on stdout became part of \$WT"
fi

# ── H3. a MERGED dependency is never a blocker, whatever failed.txt says ────
cat > "$WORK/merged.json" <<'MJ'
{"members":[{"number":101,"base_deps":[],"split":false},{"number":102,"base_deps":[101],"split":false}],
 "prs":[{"issue":101,"branch":"feature/#101-a","state":"MERGED"},
        {"issue":101,"branch":"feature/#101-b","state":"MERGED"}],
 "branches":["feature/#101-a","feature/#101-b"],
 "terminal":{"101":"failed"},"default_branch":"develop"}
MJ
MB="$("$PY" "$DAGPY" --input "$WORK/merged.json" --mode base 2>/dev/null | tr '\n' '|')"
MK="$("$PY" "$DAGPY" --input "$WORK/merged.json" --mode blocked 2>/dev/null | tr '\n' '|')"
if [ "${MB#*102 DEFAULT}" != "$MB" ] && [ -z "$MK" ]; then
  ok "e2e: two MERGED PRs + a stale failed.txt still answer DEFAULT and block nothing"
else
  bad "e2e: two MERGED PRs + a stale failed.txt answer DEFAULT" \
      "base=[$MB] blocked=[$MK] — the work is IN; nothing the human can do would clear a block here"
fi
fi


echo "== I. board projection: the seven write points (03-sprint-board.md §5.2·§9.1) =="

# Structural first, then behavioural. The structural checks here are deliberately narrow —
# they only assert that a point EXISTS at the anchor the design names, because 02-sprint.md
# §23.7 is the reason this file has an §F/§H at all: a grep that "passes" while the control
# flow never runs is how three BLOCKERs survived 249 green checks.
BOARD_SRC="$(cat "$TPL")"

# ⚠ LINE-BASED, AND A COMMENT DOES NOT COUNT. The first version matched the fixed string
# anywhere in the whole file, so mutation-testing showed that turning any projection point
# into `: # board_col "$ISSUE" in_progress` left every one of these checks green — seven
# points, all "verified", none wired. A check whose title says "P1 WRITES in_progress" must
# at minimum fail when the write is commented out.
# The comparison looks only at the part of each line BEFORE the first `#`. A leading-`#`
# test is not enough: the mutation that actually survived was `: # board_col …`, which does
# not start with `#` and so passed a start-of-line check. Anything after a `#` is a comment
# as far as this file is concerned — none of the strings asserted here contain one.
lacksline() { # lacksline <case> <fixed-string> — must NOT appear as code anywhere
  if awk -v t="$2" '{ i=index($0,"#"); pre=(i?substr($0,1,i-1):$0);
                      if (index(pre,t)) { found=1; exit } }
                    END { exit !found }' "$TPL"; then
    bad "$1" "absent" "still present as code: $2"
  else
    ok "$1"
  fi
}

hasline() {   # hasline <case> <fixed-string>   — must appear as CODE, not inside a comment
  if awk -v t="$2" '{ i=index($0,"#"); pre=(i?substr($0,1,i-1):$0);
                      if (index(pre,t)) { found=1; exit } }
                    END { exit !found }' "$TPL"; then
    ok "$1"
  elif grep -qF -- "$2" "$TPL"; then
    bad "$1" "found ONLY inside a comment: $2"
  else
    bad "$1" "not found: $2"
  fi
}

hasline "I: P1 writes in_progress"                'board_col "$ISSUE" in_progress'
hasline "I: P2 writes blocked/needs-human"        'board_col "$ISSUE" blocked needs-human'
hasline "I: P3 refreshes before judging"          'refresh_dag_input || true'
hasline "I: P3 has the split-children branch"     'board_col "$ISSUE" in_review split-children'
hasline "I: P7 lives in cleanup, guarded"         'board_col "$ISSUE" blocked interrupted'
hasline "I: P7 requires FINISHED -eq 0"           'if [ "$FINISHED" -eq 0 ]; then'
hasline "I: writes are node-ID addressed (1 point, not 104)" 'gh project item-edit --id "$item" --project-id "$BOARD_PROJECT_ID" --field-id "$fid"'
hasline "I: ids are resolved once per run"                   'board_resolve'
lacksline "I: no name-addressed write survives"              '--field "$2" --value "$3"'
hasline "I: value-less project_set is set -u safe" 'if [ -n "${3:-}" ]; then'
hasline "I: board_col has a default arm"          'BOARD_BUGS=$((BOARD_BUGS+1)); return 0 ;;'
hasline "I: cache is truncated per run"           ': > "$D/board.txt"'
hasline "I: ledger keys ride in heartbeat"        'ledger_set board_fails "$BOARD_FAILS"'

# P4 must be wired at ALL EIGHT record_failure sites. Counting is not enough — a missing one
# leaves that failure class stuck on `In progress` and nothing else notices, so each class is
# asserted by name.
for CLS in dag-input-failed base-decision-failed worktree-create-failed deps-install-failed \
           split-stalled incomplete-mid-spine rate-limit-exhausted child-session-failed; do
  hasline "I: P4 wired for $CLS" "board_col \"\$ISSUE\" blocked failed:$CLS"
done

# ⚠ record_event sites must NOT write. `dependency-blocked`/`base-unresolved`/
# `branch-ambiguous` are waits, not failures: §4.1 keeps them in `Ready` because `Blocked`
# means "nothing will move without the human". If a future edit adds a board write next to
# one of these, the Blocked column starts reading as "will resolve itself" and people stop
# looking at it.
# ⚠ The rule is "a wait must not be written as anything but `ready`", not "no board_col may
# appear near a record_event". `ready` next to one IS legitimate and load-bearing: on a re-run
# the previous run may have left the card on `Blocked` with a now-resolved `failed:<class>`, and
# the empty cache is what says "this run has not formed an opinion yet".
#
# ⚠ Scan the whole BRANCH, to its `continue`. A fixed 3-line window was tried and was vacuous:
# a comment block between the `record_event` and the write pushed the write out of the window,
# so the check saw nothing at all — and a mutation writing `blocked` there survived.
BOARD_EV_BAD="$("$PY" - "$TPL" <<'PY'
import re, sys
lines = open(sys.argv[1]).read().split("\n")
bad = []
for i, ln in enumerate(lines):
    if 'record_event "$ISSUE" dependency-blocked' not in ln:
        continue
    # walk to the end of this branch: the `continue` that leaves the queue loop
    for j in range(i + 1, min(i + 40, len(lines))):
        code = lines[j].split("#", 1)[0]
        if "board_col" in code:
            # the permitted repair is exactly `ready`; anything else is a wait mislabelled
            if not re.search(r"board_col\s+\S+\s+ready\b", code):
                bad.append("line%d" % (j + 1))
        if re.match(r"\s*continue\b", code):
            break
    else:
        bad.append("line%d:no-continue-found" % (i + 1))
print(" ".join(bad))
PY
)"
BOARD_EV_N=$(grep -c 'record_event "\$ISSUE" dependency-blocked' "$TPL" || true)
if [ -z "$BOARD_EV_BAD" ] && [ "$BOARD_EV_N" -ge 2 ]; then
  ok "I: every dependency-blocked branch writes only \`ready\` (waits stay in Ready)"
else
  bad "I: dependency-blocked branches write only ready" "clean, sites>=2" \
      "offenders:[$BOARD_EV_BAD] sites=$BOARD_EV_N"
fi

# P6 must sit between the queue loop and the teardown that removes $SUP, because
# refresh_dag_input reads `git -C "$SUP" branch`. Line order is the only way to check this.
# ⚠ The CALL, not the anchor comment. Grepping `# P6 (03-sprint-board` constrained where a
# comment sits: a mutation that left the comment and moved (or unreachable-ified) the two
# calls kept this green. `board_sweep_merged$` matches the invocation, never the definition
# (which is `board_sweep_merged() {`) and never a comment mentioning it.
I_P6=$(grep -n '^[[:space:]]*board_sweep_merged$' "$TPL" | tail -1 | cut -d: -f1)
I_SUP=$(grep -n 'worktree remove "\$SUP"' "$TPL" | head -1 | cut -d: -f1)
if [ -n "$I_P6" ] && [ -n "$I_SUP" ] && [ "$I_P6" -lt "$I_SUP" ]; then
  ok "I: P6 runs before \$SUP is removed"
else
  bad "I: P6 runs before \$SUP is removed" "P6=$I_P6 SUP=$I_SUP"
fi

# ── behavioural: render with the board ON and a gh stub, then assert the wire ──────────
# This is the part the structural checks above cannot do. §H exists for the same reason.
I_WORK="$WORK/board"; mkdir -p "$I_WORK/bin" "$I_WORK/repo"

# ⚠ A SHARED fragment answers the three reads node-ID addressing needs (`project view`,
# `field-list`, `item-list`). Node-ID writes cost 1 GraphQL point against 104 for the name form
# (measured), so the supervisor resolves ids once per run — and a stub that does not answer
# those makes `board_resolve` switch the board OFF, which is correct behaviour and a useless
# fixture. One file, so a later case rewriting `$I_WORK/bin/gh` cannot silently lose it.
cat > "$I_WORK/ids.sh" <<'IDS'
gh_ids() {
  case "$2" in
    view)
      printf '{"id":"PVT_test","number":7}\n'; exit 0 ;;
    field-list)
      printf '%s\n' '{"fields":[
        {"id":"F_col","name":"Guild board","type":"ProjectV2SingleSelectField","options":[
          {"id":"o_ready","name":"Ready"},{"id":"o_prog","name":"In progress"},
          {"id":"o_block","name":"Blocked"},{"id":"o_rev","name":"In review"},
          {"id":"o_done","name":"Done"}]},
        {"id":"F_nh","name":"Needs human","type":"ProjectV2Field"}],"totalCount":2}'
      exit 0 ;;
    item-list)
      printf '%s\n' '[]'; exit 0 ;;
    item-add)
      printf '{"id":"I_%s"}\n' "$(printf '%s' "$*" | sed -n 's|.*/issues/\([0-9]*\).*|\1|p')"
      exit 0 ;;
  esac
}
IDS

cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
exit 0
STUB
chmod +x "$I_WORK/bin/gh"
export GH_IDS="$I_WORK/ids.sh"

# Drive project_set/board_col directly out of the rendered script: source the definitions
# and call them. Sourcing the whole file would run the sprint, so cut at the marker that
# closes the helper block — the functions are all above it.
"$PY" "$WORK/render.py" "$TPL" "101" "" "$I_WORK/repo" "/tmp/c" "/tmp/dag.py" "7" \
  > "$I_WORK/full.sh"
sed -n '1,/^# <!-- guild:supervisor-core:selfdelete -->/p' "$I_WORK/full.sh" \
  | grep -v '^trap ' > "$I_WORK/helpers.sh"

I_run() {   # I_run <body>
  : > "$I_WORK/calls.txt"
  GH_CALLS="$I_WORK/calls.txt" PATH="$I_WORK/bin:$PATH" \
    "$SH" -c 'set -euo pipefail; . '"$I_WORK/helpers.sh"'; board_resolve; : > "$GH_CALLS"; '"$1" >"$I_WORK/out.txt" 2>&1
  I_RC=$?
  I_CALLS="$(cat "$I_WORK/calls.txt" 2>/dev/null || true)"
}

I_run 'board_col 101 in_progress'
case "$I_CALLS" in
  *'--field-id F_col --single-select-option-id o_prog'*) ok "I: board_col maps in_progress -> the option id" ;;
  *) bad "I: board_col maps in_progress -> the option id" "calls=[$(printf '%s' "$I_CALLS" | tr '\n' '|')] rc=$I_RC" ;;
esac

I_run 'board_col 101 blocked failed:deps-install-failed'
case "$I_CALLS" in
  *'--field-id F_nh --text failed:deps-install-failed'*) ok "I: reason token goes to the Needs human field" ;;
  *) bad "I: reason token goes to the Needs human field" "calls=[$(printf '%s' "$I_CALLS" | tr '\n' '|')]" ;;
esac

# Both writes are deduped, each on its own key: the column on (issue, column), the reason on
# (issue, column, reason). §7.2 asks for the reason "at most once per outcome" — an earlier
# implementation wrote it on EVERY call, which is O(N x sweeps) extra gh calls against the same
# budget the breaker trips on and `refresh_dag_input`'s correctness reads share.
I_run 'board_col 101 in_progress; board_col 101 in_progress'
I_COLW=$(printf '%s\n' "$I_CALLS" | grep -c -- '--field-id F_col --single-select-option-id o_prog' || true)
I_NHW=$(printf '%s\n' "$I_CALLS" | grep -c -- '--field-id F_nh --clear' || true)
if [ "$I_COLW" -eq 1 ] && [ "$I_NHW" -eq 1 ]; then
  ok "I: an identical repeated board_col writes nothing twice"
else
  bad "I: repeated board_col must dedupe both writes" "column=$I_COLW reason=$I_NHW"
fi

# ⚠ But a CHANGED reason must go out. Deduping on the issue alone would freeze the first reason
# a card ever got, so `failed:deps-install-failed` would still be showing after the retry that
# turned it into `interrupted`.
I_run 'board_col 101 blocked failed:deps-install-failed; board_col 101 blocked interrupted'
I_R1=$(printf '%s\n' "$I_CALLS" | grep -c -- '--text failed:deps-install-failed' || true)
I_R2=$(printf '%s\n' "$I_CALLS" | grep -c -- '--text interrupted' || true)
if [ "$I_R1" -eq 1 ] && [ "$I_R2" -eq 1 ]; then
  ok "I: a changed reason is written even when the column is unchanged"
else
  bad "I: a changed reason must be written" "first=$I_R1 second=$I_R2"
fi

# ── 원장을 쓰는 검사는 원장 함수가 있는 컷을 써야 한다 ─────────────────────
# ⚠ 이 검사의 첫 버전은 **발화할 수 없었다.** `ledger_set`/`ledger_get` 은 `helpers.sh` 의 컷
# 뒤에 정의돼 있어서 `ledger_get` 이 `command not found` 였고, `$( )` 가 빈 문자열이 되어
# 관측값이 `[]` 였고, 그것이 통과 분기(`*'['*`)에 맞았다 — 코드가 무엇을 하든 초록이었다.
# 그래서 (a) 원장 함수까지 포함하는 컷을 따로 뽑고, (b) **프로브 자체가 작동하는지 대조군을
# 먼저 확인한다.** 실패 방식이 `command not found` 와 구별되지 않는 검사는 대조군이 필요하다.
mkdir -p "$I_WORK/repo_lg"
"$PY" "$WORK/render.py" "$TPL" "101" "" "$I_WORK/repo_lg" "/tmp/c" "/tmp/dag.py" "7" \
  > "$I_WORK/full_lg.sh"
sed -n '1,/^EVENTS=/p' "$I_WORK/full_lg.sh" | grep -v '^trap ' > "$I_WORK/helpers_lg.sh"

I_lg() {   # I_lg <body>
  : > "$I_WORK/calls.txt"
  GH_CALLS="$I_WORK/calls.txt" PATH="$I_WORK/bin:$PATH" \
    "$SH" -c 'set -euo pipefail; . '"$I_WORK/helpers_lg.sh"'; board_resolve; : > "$GH_CALLS"; '"$1" >"$I_WORK/lg.txt" 2>&1
  I_LG_RC=$?
}

# 대조군: 프로브가 실제로 원장을 읽을 수 있는가
I_lg 'ledger_set probe 42; printf "[%s]" "$(ledger_get probe none)"'
case "$(cat "$I_WORK/lg.txt")" in
  *'[42]'*) ok "I: (control) the ledger probe itself works" ;;
  *) bad "I: the ledger probe is broken — every ledger check below is meaningless" \
         "out=[$(cat "$I_WORK/lg.txt")] rc=$I_LG_RC" ;;
esac

# 성공한 쓰기는 실제 투영 시각을 남긴다 — 모든 신선도 표시의 유일한 정직한 출처다.
I_lg 'board_col 101 ready; printf "[%s]" "$(ledger_get board_last_write none)"'
case "$(cat "$I_WORK/lg.txt")" in
  *'[none]'*) bad "I: board_last_write must be recorded" "a timestamp" "out=[$(cat "$I_WORK/lg.txt")]" ;;
  *[0-9]*)    ok "I: a successful projection records board_last_write" ;;
  *) bad "I: board_last_write" "a timestamp" "out=[$(cat "$I_WORK/lg.txt")]" ;;
esac

# 그리고 캐시에 걸려 gh 호출이 0건인 board_col 은 시각을 올리지 않는다 — 안 움직인 카드를
# *"방금 움직였다"* 고 말하지 않기 위해서다.
I_lg 'board_col 101 ready
      T1="$(ledger_get board_last_write 0)"
      sleep 1
      : > "$GH_CALLS"
      board_col 101 ready
      T2="$(ledger_get board_last_write 0)"
      printf "[%s][%s][%s]" "$T1" "$T2" "$(grep -c . "$GH_CALLS" 2>/dev/null || echo 0)"'
I_LG_OUT="$(cat "$I_WORK/lg.txt")"
I_T1="$(printf '%s' "$I_LG_OUT" | awk -F'[][]' '{print $2}')"
I_T2="$(printf '%s' "$I_LG_OUT" | awk -F'[][]' '{print $4}')"
I_T3="$(printf '%s' "$I_LG_OUT" | awk -F'[][]' '{print $6}')"
if [ -n "$I_T1" ] && [ "$I_T1" = "$I_T2" ] && [ "$I_T3" = 0 ]; then
  ok "I: a fully deduped board_col does not bump board_last_write"
else
  bad "I: a no-op board_col must not bump the timestamp" "T1==T2 and 0 gh calls" \
      "T1=[$I_T1] T2=[$I_T2] calls=[$I_T3] raw=[$I_LG_OUT]"
fi

# ── 보드가 아예 안 켜진 이유가 원장에 남는다 ───────────────────────────────
# 변이로 드러난 구멍이다: 이 줄을 주석 처리해도 스위트가 초록이었다 — 검사가 `grep -qF` 라
# 주석까지 통과시켰다. 이 값이 없으면 신호는 감독자 stdout 의 `echo` 하나뿐이고, `daily` 는
# 그 스트림을 읽을 수 없다고 스스로 명시한다. 그러면 6시간 run 이 손대지 않은 보드에 대해
# *"투영 기록 없음"* 으로 렌더되고, 그것은 *"run 이 아직 시작 안 됨"* 과 구별되지 않는다.
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
case "$2" in
  view) exit 1 ;;
esac
. "$GH_IDS"; gh_ids "$@"
exit 0
STUB
chmod +x "$I_WORK/bin/gh"
I_lg 'board_resolve
      if [ -n "$BOARD_OFF_REASON" ]; then ledger_set board_off_reason "\"$BOARD_OFF_REASON\"" || true; fi
      printf "[%s][%s]" "${BOARD_NUMBER:-OFF}" "$(ledger_get board_off_reason none)"'
case "$(cat "$I_WORK/lg.txt")" in
  *'[OFF][project-unreadable]'*)
    ok "I: a board that cannot come up records WHY in the ledger" ;;
  *) bad "I: board_off_reason must reach the ledger" "[OFF][project-unreadable]" \
         "out=[$(cat "$I_WORK/lg.txt")]" ;;
esac
# 그리고 그 지점이 실제로 배선돼 있는지 — 주석이 아니라 코드로
hasline "I: off_reason is wired at run start" 'ledger_set board_off_reason'

# 스텁 복구
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
exit 0
STUB
chmod +x "$I_WORK/bin/gh"

# ── 원장의 보드 키는 run 시작 시 버려진다 (run 간 오염) ────────────────────
# 낡은 `board_disabled_after` 가 남으면, 모든 카드를 정확히 옮긴 run 이 *"연속 실패로 투영을
# 중단했습니다"* 를 보고한다 — 그리고 `daily` 는 그 키를 **먼저** 검사한다.
I_LG_LEDGER="$I_WORK/repo_lg/.claude/guild/.sprint-logs/99/dag/ledger.json"
mkdir -p "$(dirname "$I_LG_LEDGER")"
printf '%s\n' '{"board_disabled_after":34,"board_account_mismatch":"a != b","board_reason_disabled":1,"retries":{"101":2}}' > "$I_LG_LEDGER"
I_lg 'printf "[%s][%s][%s][%s]" "$(ledger_get board_disabled_after none)" "$(ledger_get board_account_mismatch none)" "$(ledger_get board_reason_disabled none)" "$(ledger_get retries.101 none)"'
case "$(cat "$I_WORK/lg.txt")" in
  *'[none][none][none][2]'*) ok "I: run start drops the board keys and keeps the rest" ;;
  *) bad "I: stale board keys must be dropped at run start" \
         "[none][none][none][2]" "out=[$(cat "$I_WORK/lg.txt")]" ;;
esac

# board_col_of is what P7's guard reads. It must answer with the LAST value written.
I_run 'board_col 101 in_progress; board_col 101 blocked x; printf "[%s]" "$(board_col_of 101)"'
case "$(cat "$I_WORK/out.txt")" in
  *'[blocked]'*) ok "I: board_col_of returns the last column written" ;;
  *) bad "I: board_col_of returns the last column written" "out=[$(cat "$I_WORK/out.txt")]" ;;
esac

# The cache holds ONE LINE PER ISSUE. Appending instead would be observationally identical
# in today's flow (a column is never rewritten to an older value within a run), so this
# asserts the property directly rather than a symptom: with duplicate lines, a later
# `board_col <n> <old-column>` hits the stale line and silently skips a real write.
I_run 'board_col 101 in_progress; board_col 101 blocked x; board_col 102 ready; printf "[%s]" "$(grep -c . "$D/board.txt")"'
case "$(cat "$I_WORK/out.txt")" in
  *'[2]'*) ok "I: cache keeps one line per issue (101 rewritten, 102 added)" ;;
  *) bad "I: cache keeps one line per issue" "out=[$(cat "$I_WORK/out.txt")] file=[$(tr '\n' '|' < "$I_WORK/repo/.claude/guild/.sprint-logs/99/dag/board.txt" 2>/dev/null || echo n/a)]" ;;
esac

# An unknown token is our bug, counted apart from gh failures, and writes nothing.
I_run 'board_col 101 nosuchtoken; printf "[%s][%s]" "$BOARD_BUGS" "$BOARD_FAILS"'
if [ -z "$I_CALLS" ]; then
  case "$(cat "$I_WORK/out.txt")" in
    *'[1][0]'*) ok "I: unknown token -> BOARD_BUGS, no gh call, BOARD_FAILS untouched" ;;
    *) bad "I: unknown token accounting" "out=[$(cat "$I_WORK/out.txt")]" ;;
  esac
else
  bad "I: unknown token makes no gh call" "calls=[$(printf '%s' "$I_CALLS" | tr '\n' '|')]"
fi

# D2: board off -> zero calls, and no `set -u` death on the value-less form.
# ⚠ A SEPARATE repo dir. The board's config now lives in a file under `$HUMAN_REPO`, so
# rendering "off" into the same repo deletes the ON case's file and every later case in this
# section silently becomes a board-off case — which passes for the wrong reason.
mkdir -p "$I_WORK/repo_off"
"$PY" "$WORK/render.py" "$TPL" "101" "" "$I_WORK/repo_off" "/tmp/c" "/tmp/dag.py" "" \
  > "$I_WORK/off.sh"
sed -n '1,/^# <!-- guild:supervisor-core:selfdelete -->/p' "$I_WORK/off.sh" \
  | grep -v '^trap ' > "$I_WORK/helpers_off.sh"
: > "$I_WORK/calls.txt"
GH_CALLS="$I_WORK/calls.txt" PATH="$I_WORK/bin:$PATH" \
  "$SH" -c 'set -euo pipefail; . '"$I_WORK/helpers_off.sh"'; board_col 101 in_progress; project_set 101 "Needs human"' \
  >/dev/null 2>&1
I_OFF_RC=$?
if [ "$I_OFF_RC" -eq 0 ] && [ ! -s "$I_WORK/calls.txt" ]; then
  ok "I: board off -> zero gh calls, value-less project_set survives set -u (D2)"
else
  bad "I: board off -> zero gh calls" "rc=$I_OFF_RC calls=[$(tr '\n' '|' < "$I_WORK/calls.txt")]"
fi

# ⚠ THE `|| true` CASE. A stub that only fails `item-edit` never exercises it, because the
# retry's `item-add` succeeds and the missing guard costs nothing. Make item-add fail too:
# the body of `if ! …; then` is NOT exempt from `set -e`, so without `|| true` the caller
# dies here — which is exactly what killed a run at its first member.
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
exit 1
STUB
chmod +x "$I_WORK/bin/gh"
I_run 'board_col 101 in_progress; echo SURVIVED'
if [ "$I_RC" -eq 0 ]; then
  case "$(cat "$I_WORK/out.txt")" in
    *SURVIVED*) ok "I: every gh call failing still does not kill the caller (the || true case)" ;;
    *) bad "I: every gh call failing must not kill the caller" "out=[$(cat "$I_WORK/out.txt")]" ;;
  esac
else
  bad "I: every gh call failing must not kill the caller" "rc=$I_RC out=[$(cat "$I_WORK/out.txt")]"
fi

# gh failing must be absorbed and COUNTED, and must not kill the caller under set -e.
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$2" in item-edit) exit 1 ;; esac
exit 0
STUB
chmod +x "$I_WORK/bin/gh"
I_run 'board_col 101 in_progress; printf "[%s]" "$BOARD_FAILS"; echo AFTER'
if [ "$I_RC" -eq 0 ]; then
  case "$(cat "$I_WORK/out.txt")" in
    *AFTER*) ok "I: gh failure is absorbed — the caller keeps running (D9)" ;;
    *) bad "I: gh failure absorbed" "out=[$(cat "$I_WORK/out.txt")]" ;;
  esac
  case "$(cat "$I_WORK/out.txt")" in
    *'[2]'*|*'[1]'*) ok "I: gh failure increments BOARD_FAILS" ;;
    *) bad "I: gh failure increments BOARD_FAILS" "out=[$(cat "$I_WORK/out.txt")]" ;;
  esac
else
  bad "I: gh failure must not kill the caller" "rc=$I_RC out=[$(cat "$I_WORK/out.txt")]"
fi


# ── 낡은 보드 설정 파일 (조용히 보드가 켜지는 경로) ────────────────────────
# 파일이 스크립트보다 오래 살면, 사람이 config 에서 보드를 끄고 같은 스프린트를 재실행할 때
# `run.md` 2b 는 파일을 쓰지 않을 뿐이므로 낡은 파일이 그대로 읽히고 보드가 계속 켜진다.
# 깨끗이 끝난 run 은 스크립트와 함께 이 파일도 지워야 한다.
hasline "I: a clean run removes the board config file too" 'rm -f "$SCRIPT_PATH" "$BOARD_CONF"'
# ── P3 의 기본 전이: 자기 PR 이 있으면 in_review ────────────────────────────
# 변이로 드러났다: `board_col "$ISSUE" in_review` 를 지워도 스위트 전체가 초록이었다.
# hasline 은 `in_review split-children` 만 보고 맨 `in_review` 는 보지 않았다. 이것이 보드에서
# 가장 흔한 전이이고, 지워지면 완료된 멤버가 영원히 `In progress` 에 남아 **`In review` 칸이
# 영구히 빈다** — 리뷰하고 머지하라고 말하는 유일한 칸이다.
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
exit 0
STUB
chmod +x "$I_WORK/bin/gh"
if awk '{ i=index($0,"#"); pre=(i?substr($0,1,i-1):$0);
          if (pre ~ /board_col "\$ISSUE" in_review$/) { found=1; exit } }
        END { exit !found }' "$TPL"; then
  ok "I: P3 writes plain in_review for a member with its own PR"
else
  bad "I: P3 writes plain in_review" "no bare \`board_col \"\$ISSUE\" in_review\` on a code line"
fi

# ── P7 의 캐시 가드: 이미 in_review 인 카드는 덮지 않는다 ───────────────────
# v12 의 BLOCKER 수정이 여기 걸려 있다. 가드를 지우면 `kill` 이 리뷰 대기 중인 PR 의 카드를
# `Blocked`/`interrupted` 로 덮는다 — 리뷰 대기 PR 이 보드에서 사라진다.
#
# ⚠ **실제 `cleanup` 을 부른다.** 처음 쓴 버전은 가드 조건을 테스트 문자열에 **다시 타이핑**해서
# 템플릿의 가드를 지워도 초록이었다 — 자기 복사본을 시험하는 검사였다. 이제 EXIT 트랩이 부르는
# 그 함수를 그대로 실행한다.
# ⚠ `cleanup` is defined INSIDE the selfdelete marker block, i.e. after the cut `helpers.sh`
# uses. Extract through the CLOSING marker for these cases — that pulls in the ledger init and
# the empty-queue guard too, which is why `<ORDER>` must be non-empty here.
#
# ⚠ And render into a SEPARATE repo dir. `cleanup` on a completed run does
# `rm -f "$SCRIPT_PATH" "$BOARD_CONF"` — so running it against the shared repo deletes the board
# config file and every later case in this section silently becomes a board-off case. That is
# the third time the shared data file has done this; the pattern is one repo dir per scenario.
mkdir -p "$I_WORK/repo_cl"
"$PY" "$WORK/render.py" "$TPL" "101" "" "$I_WORK/repo_cl" "/tmp/c" "/tmp/dag.py" "7" \
  > "$I_WORK/full_cl.sh"
sed -n '1,/^# <!-- \/guild:supervisor-core:selfdelete -->/p' "$I_WORK/full_cl.sh" \
  | grep -v '^trap ' > "$I_WORK/helpers_cl.sh"

I_cleanup_case() {   # I_cleanup_case <case> <pre-column> <expect-write: yes|no>
  : > "$I_WORK/calls.txt"
  GH_CALLS="$I_WORK/calls.txt" PATH="$I_WORK/bin:$PATH" \
    "$SH" -c 'set -euo pipefail; . '"$I_WORK/helpers_cl.sh"'
       board_resolve
       board_col 101 '"$2"'
       : > "$GH_CALLS"
       ISSUE=101; FINISHED=0; COMPLETED=0
       cleanup' >"$I_WORK/cl.txt" 2>&1 || true
  I_CL="$(cat "$I_WORK/calls.txt" 2>/dev/null || true)"
  case "$I_CL" in
    *'--single-select-option-id o_block'*) [ "$3" = yes ] && ok "$1" || bad "$1" "no write" "calls=[$(printf '%s' "$I_CL" | tr '\n' '|')]" ;;
    *)                   [ "$3" = no ]  && ok "$1" || bad "$1" "a Blocked write" "calls=[$(printf '%s' "$I_CL" | tr '\n' '|')]" ;;
  esac
}
I_cleanup_case "I: cleanup leaves an in_review card alone (P7 guard)"      in_review   no
I_cleanup_case "I: cleanup relabels an in_progress card as interrupted"    in_progress yes

# FINISHED=1 이면 완주한 run 이므로 P7 은 발화하지 않아야 한다 — 마지막 멤버를 *"중단됐다"* 고
# 거짓 진술하는 것을 막는 가드다.
# ⚠ `COMPLETED=0`: COMPLETED=1 분기는 `rm -f "$SCRIPT_PATH" …` 를 돌리고, `bash -c` 아래에서는
# `$0` 가 `bash` 이므로 `SCRIPT_PATH` 가 인터프리터를 가리킨다. 프로덕션(`bash /path/script.sh`)
# 에서는 정확하지만 이 하네스에서는 밟을 수 없다. 이 케이스가 보려는 것은 P7 의 발화 여부뿐이다.
: > "$I_WORK/calls.txt"
GH_CALLS="$I_WORK/calls.txt" PATH="$I_WORK/bin:$PATH" \
  "$SH" -c 'set -euo pipefail; . '"$I_WORK/helpers_cl.sh"'
     board_resolve
     board_col 101 in_progress
     : > "$GH_CALLS"
     ISSUE=101; FINISHED=1; COMPLETED=0
     cleanup' >/dev/null 2>&1 || true
if ! grep -q -- '--single-select-option-id o_block' "$I_WORK/calls.txt" 2>/dev/null; then
  ok "I: a finished run does not relabel its last member as interrupted"
else
  bad "I: FINISHED=1 must suppress P7" "calls=[$(tr '\n' '|' < "$I_WORK/calls.txt")]"
fi
# 구조 검사는 남겨둔다 — 위 셋과 다른 것을 본다(가드가 그 자리에 있는지)
hasline "I: P7 is guarded by the column cache" 'board_col_of "$ISSUE")" = "in_progress"'

# ── board_sweep_merged — P5/P6 의 실체. 여기에 검사가 하나도 없었다 ──────────
# 변이 테스트가 드러낸 구멍: `state == "MERGED"` 필터를 지워도 22+88건이 전부 초록이었다.
# 그 변이의 결과는 *"열려 있는 PR의 이슈까지 Done 으로 옮긴다"* — 머지되지 않은 일을 완료로
# 표시하는 것이고, 보드가 낼 수 있는 거짓 중 가장 나쁜 쪽이다.
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
exit 0
STUB
chmod +x "$I_WORK/bin/gh"
I_DAG="$I_WORK/repo/.claude/guild/.sprint-logs/99/dag"
mkdir -p "$I_DAG"
printf '%s\n' '{"prs":[{"issue":101,"state":"MERGED"},{"issue":102,"state":"OPEN"}]}' \
  > "$I_DAG/run.json"
I_run 'board_sweep_merged'
I_DONE101=$(printf '%s\n' "$I_CALLS" | grep -c -- '--id I_101 --project-id PVT_test --field-id F_col --single-select-option-id o_done' || true)
I_DONE102=$(printf '%s\n' "$I_CALLS" | grep -c -- '--id I_102 --project-id PVT_test --field-id F_col --single-select-option-id o_done' || true)
if [ "$I_DONE101" -eq 1 ] && [ "$I_DONE102" -eq 0 ]; then
  ok "I: sweep moves the MERGED issue to Done and leaves the OPEN one alone"
else
  bad "I: sweep filters on MERGED" "merged=$I_DONE101 open=$I_DONE102 calls=[$(printf '%s' "$I_CALLS" | tr '\n' '|')]"
fi

# run.json 이 없으면 sweep 은 무동작이어야 한다 — 없는 입력으로 전량을 Done 으로 쓸어버리는
# 것보다 아무 것도 하지 않는 편이 낫다.
rm -f "$I_DAG/run.json"
I_run 'board_sweep_merged; echo AFTER'
if [ "$I_RC" -eq 0 ] && [ -z "$I_CALLS" ]; then
  ok "I: sweep with no run.json makes zero calls and does not die"
else
  bad "I: sweep with no run.json" "rc=$I_RC calls=[$(printf '%s' "$I_CALLS" | tr '\n' '|')]"
fi

# ── 실패한 쓰기는 캐시되지 않는다 (자기치유 재시도) ────────────────────────
# 변이 테스트: `BOARD_LAST_OK=0` 을 지우면 실패한 쓰기가 성공으로 캐시되고, 그 run 내내 같은
# 카드에 대한 재시도가 전부 건너뛰어진다 — 카드는 계속 틀리고 BOARD_FAILS 도 더는 늘지 않는다.
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
# 첫 컬럼 쓰기만 실패하고 그 뒤로는 성공한다. (노드 ID 전환 이후 board_col 은 필드당 1콜이다 —
# 예전의 edit→add→edit 3연타가 없어졌으므로 "두 번"이 아니라 "첫 번"이다.)
if [ "$(grep -c -- 'field-id F_col' "$GH_CALLS")" -le 1 ]; then exit 1; fi
exit 0
STUB
chmod +x "$I_WORK/bin/gh"
I_run 'board_col 101 in_progress; board_col 101 in_progress; printf "[%s]" "$BOARD_FAILS"'
I_TRIES=$(printf '%s\n' "$I_CALLS" | grep -c -- '--field-id F_col --single-select-option-id o_prog' || true)
# 실패 → 캐시되지 않음 → 다음 board_col 이 같은 컬럼을 다시 쓴다. 캐시했다면 1회뿐이다.
if [ "$I_TRIES" -ge 2 ]; then
  ok "I: a failed column write is not cached — the next board_col retries it"
else
  bad "I: failed write must not be cached" "attempts=$I_TRIES calls=[$(printf '%s' "$I_CALLS" | tr '\n' '|')]"
fi

# ── 서킷 브레이커 — 죽은 보드에 계속 값을 치르지 않는다 ────────────────────
# D9 는 실패를 흡수하라고 요구하지만 영원히 대가를 치르라고 요구하지는 않는다. 실패 경로는
# board_col 당 gh 호출이 2회가 아니라 6회이고, 캐시는 성공 시에만 채워지므로 P1 이 재시도마다
# 다시 발화한다. rate limit 아래에서 이것은 자기증식이고, 감독자의 정합성 호출과 예산을 공유한다.
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
exit 1
STUB
chmod +x "$I_WORK/bin/gh"
I_run 'i=101; while [ $i -le 130 ]; do board_col $i ready; i=$((i+1)); done
       printf "[%s][%s]" "$BOARD_FAILS" "${BOARD_NUMBER:-OFF}"'
I_ALL=$(printf '%s\n' "$I_CALLS" | grep -c 'project item-edit' || true)
case "$(cat "$I_WORK/out.txt")" in
  *'[OFF]'*)
    if [ "$I_ALL" -lt 60 ]; then
      ok "I: the breaker turns the board off after a streak of failures (calls=$I_ALL, not 180)"
    else
      bad "I: breaker fired but calls kept flowing" "calls=$I_ALL"
    fi ;;
  *) bad "I: breaker must turn the board off" "out=[$(cat "$I_WORK/out.txt")] calls=$I_ALL" ;;
esac

# ── 부분 장애에서도 브레이커가 발화한다 ───────────────────────────────────
# 변이로 드러난 구멍이다: 연속 실패를 project_set 단위로 세면 두 쓰기 중 **하나만** 성공해도
# 스트릭이 초기화되므로, 브레이커는 *"모든 gh 호출이 실패하는"* 경우(= rate limit)에만 발화했다.
# 흔한 쪽은 부분 장애다 — 사람이 UI 에서 컬럼 필드를 개명했거나 필드별 권한이 걸린 경우. 그때
# 보드는 영원히 "켜진" 상태로 board_col 당 4콜을 계속 냈다(실측: 60회에 240콜).
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
# 컬럼 필드 쓰기만 실패한다. Needs human 쪽은 계속 성공한다.
case "$*" in *"--field-id F_col"*) exit 1 ;; esac
exit 0
STUB
chmod +x "$I_WORK/bin/gh"
I_run 'i=101; while [ $i -le 160 ]; do board_col $i ready; i=$((i+1)); done
       printf "[%s]" "${BOARD_NUMBER:-OFF}"'
I_PART=$(printf '%s\n' "$I_CALLS" | grep -c 'project item' || true)
case "$(cat "$I_WORK/out.txt")" in
  *'[OFF]'*)
    if [ "$I_PART" -lt 120 ]; then
      ok "I: the breaker fires on a PARTIAL outage too (calls=$I_PART, not 240)"
    else
      bad "I: partial outage tripped the breaker but calls kept flowing" "calls=$I_PART"
    fi ;;
  *) bad "I: the breaker must fire when only the column write fails" \
         "out=[$(cat "$I_WORK/out.txt")] calls=$I_PART" ;;
esac

# 한 번이라도 성공하면 연속 실패는 끊긴다 — 산발적 실패로 보드가 꺼지면 안 된다.
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
if [ "$(grep -c . "$GH_CALLS")" -eq 1 ]; then exit 1; fi
exit 0
STUB
chmod +x "$I_WORK/bin/gh"
I_run 'i=101; while [ $i -le 130 ]; do board_col $i ready; i=$((i+1)); done
       printf "[%s]" "${BOARD_NUMBER:-OFF}"'
case "$(cat "$I_WORK/out.txt")" in
  *'[7]'*) ok "I: an intermittent failure does not trip the breaker" ;;
  *) bad "I: intermittent failure must not disable the board" "out=[$(cat "$I_WORK/out.txt")]" ;;
esac

# ── 빈 컬럼 이름은 --clear 가 아니라 우리 버그다 ───────────────────────────
# 빈 이름은 project_set 에 값 없는 호출로 도달해 --clear 가 되고, 카드는 조용히 널 버킷
# (= Issues, *"구체화 필요"*)으로 간다. 캐시는 의도한 토큰을 기록하고 카운터는 둘 다 그대로다.
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
exit 0
STUB
chmod +x "$I_WORK/bin/gh"
I_run 'BOARD_COL_READY=""; board_col 101 ready; printf "[%s][%s]" "$BOARD_BUGS" "$BOARD_FAILS"'
if [ -z "$I_CALLS" ]; then
  case "$(cat "$I_WORK/out.txt")" in
    *'[1][0]'*) ok "I: an empty column name is a bug, not a --clear" ;;
    *) bad "I: empty column name accounting" "out=[$(cat "$I_WORK/out.txt")]" ;;
  esac
else
  bad "I: empty column name must not write" "calls=[$(printf '%s' "$I_CALLS" | tr '\n' '|')]"
fi

# ── 보드 설정은 코드가 아니라 데이터다 (실측된 주입 3종) ──────────────────
# 이 클래스가 세 번 나왔다. (1) `VAR="<TOKEN>"` — `Done $(touch …)` 이 감독자 시작 시 실행되고,
# 백슬래시로 끝나는 이름이 뒤 줄을 삼켜 set -u 로 **로드 시점에** 죽였다(트랩·빈큐 가드·gh 호출
# 전이므로 컬럼 이름 하나가 스프린트를 시작조차 못 하게 했다). (2) 인용 heredoc — 앞의 둘은
# 막았지만 **개행**이 여전히 탈출해 그 뒤가 최상위 셸이 됐다. bash 3.2.57 에서 `bash -n` 은 셋 다
# 침묵했다. 이제 값은 별도 데이터 파일에 있고 셸 소스에 닿지 않는다.
I_BCONF="$I_WORK/repo_inj/.claude/guild/.gld-sprint-99.board"
mkdir -p "$I_WORK/repo_inj"
rm -f "$I_WORK/PWNED"
mkdir -p "$(dirname "$I_BCONF")"
cat > "$I_BCONF" <<INJ
number=7
owner=@me
field=Guild board
field_needs_human=Needs human
verified_as=tester
col_ready=Ready
col_in_progress=In progress
col_blocked=Blocked \\
col_in_review=In review \$(touch "$I_WORK/PWNED")
col_done=Done
INJ
"$PY" "$WORK/render.py" "$TPL" "101" "" "$I_WORK/repo_inj" "/tmp/c" "/tmp/dag.py" "" \
  > "$I_WORK/inj_full.sh"
# render.py 는 board_number 가 비면 파일을 지우므로, 렌더 후에 적대적 파일을 다시 놓는다
cat > "$I_BCONF" <<INJ
number=7
owner=@me
field=Guild board
field_needs_human=Needs human
verified_as=tester
col_ready=Ready
col_in_progress=In progress
col_blocked=Blocked \\
col_in_review=In review \$(touch "$I_WORK/PWNED")
col_done=Done
INJ
sed -n '1,/^# <!-- guild:supervisor-core:selfdelete -->/p' "$I_WORK/inj_full.sh" \
  | grep -v '^trap ' > "$I_WORK/inj_helpers.sh"
I_INJ_OUT="$("$SH" -c 'set -euo pipefail; . '"$I_WORK/inj_helpers.sh"'; printf "[%s][%s][%s]" "$BOARD_COL_BLOCKED" "$BOARD_COL_IN_REVIEW" "$BOARD_NUMBER"' 2>&1)"
if [ ! -e "$I_WORK/PWNED" ]; then
  ok "I: a display name cannot execute — command substitution stays inert"
else
  bad "I: board config is executed as code" "PWNED was created"
fi
case "$I_INJ_OUT" in
  *'[Blocked \]'*) ok "I: a trailing backslash stays literal and swallows nothing" ;;
  *) bad "I: trailing backslash in a display name" "out=[$I_INJ_OUT]" ;;
esac
case "$I_INJ_OUT" in
  *'$(touch'*) ok "I: command substitution survives as literal text" ;;
  *) bad "I: command substitution should be literal" "out=[$I_INJ_OUT]" ;;
esac

# 개행이 든 값 — 예전 heredoc 을 탈출했다. 이제는 최악이 *"그 이름이 비었다"* 이고, 검증이
# 보드를 끈다. 실행은 어떤 경우에도 없다.
rm -f "$I_WORK/PWNED2"
printf 'number=7\nowner=@me\nfield=Guild board\nfield_needs_human=Needs human\nverified_as=tester\ncol_ready=Ready\ncol_in_progress=In progress\ncol_blocked=Blocked\ncol_in_review=In review\ncol_done=Done\nGLD_BOARD_CONF\ntouch "%s"\n' \
  "$I_WORK/PWNED2" >> "$I_BCONF"
I_NL_OUT="$("$SH" -c 'set -euo pipefail; . '"$I_WORK/inj_helpers.sh"'; printf "[%s]" "$BOARD_NUMBER"' 2>&1)"
if [ ! -e "$I_WORK/PWNED2" ]; then
  ok "I: a stray heredoc terminator in the data file executes nothing"
else
  bad "I: data file escaped into code" "PWNED2 was created"
fi

# 숫자가 아닌 number → 보드 OFF + WARN 1줄. 렌더러가 토큰을 빠뜨린 경우도 여기로 온다.
printf 'number=<BOARD_NUMBER>\nowner=@me\nfield=F\nfield_needs_human=N\nverified_as=t\ncol_ready=R\ncol_in_progress=P\ncol_blocked=B\ncol_in_review=V\ncol_done=D\n' > "$I_BCONF"
I_BAD_OUT="$("$SH" -c 'set -euo pipefail; . '"$I_WORK/inj_helpers.sh"'; printf "[%s][%s]" "${BOARD_NUMBER:-OFF}" "$BOARD_WAS_ON"' 2>&1)"
case "$I_BAD_OUT" in
  *'board config unusable'*)
    case "$I_BAD_OUT" in
      *'[OFF][0]'*) ok "I: a non-numeric project number turns the board off, loudly" ;;
      *) bad "I: non-numeric number accounting" "out=[$I_BAD_OUT]" ;;
    esac ;;
  *) bad "I: a non-numeric project number must WARN" "out=[$I_BAD_OUT]" ;;
esac

# field_needs_human 이 비면 board_col 이 매 쓰기마다 `--field "" --clear` 를 냈다 — 20/20 실패.
printf 'number=7\nowner=@me\nfield=F\nfield_needs_human=\nverified_as=t\ncol_ready=R\ncol_in_progress=P\ncol_blocked=B\ncol_in_review=V\ncol_done=D\n' > "$I_BCONF"
I_NH_OUT="$("$SH" -c 'set -euo pipefail; . '"$I_WORK/inj_helpers.sh"'; printf "[%s]" "${BOARD_NUMBER:-OFF}"' 2>&1)"
case "$I_NH_OUT" in
  *'[OFF]'*) ok "I: an empty needs-human field name turns the board off (it is used every write)" ;;
  *) bad "I: empty field_needs_human must turn the board off" "out=[$I_NH_OUT]" ;;
esac

# ── 파싱의 조용한 실패 네 경로 (전부 시끄러워야 한다) ─────────────────────
# 리뷰가 실측으로 잡았다: 아래 넷 다 `number` 를 잃고, 검증의 빈-문자열 분기가 **의도적으로**
# 아무 말도 안 하므로(그게 D2 의 보드 OFF 경로다) 보드가 조용히 6시간 동안 안 갱신됐다.
I_conf_case() {   # I_conf_case <case> <printf-format-for-the-file>
  printf "$2" > "$I_BCONF"
  I_CC_OUT="$("$SH" -c 'set -euo pipefail; . '"$I_WORK/inj_helpers.sh"'; printf "[%s][%s]" "${BOARD_NUMBER:-OFF}" "$BOARD_WAS_ON"' 2>&1)"
  case "$I_CC_OUT" in
    *'board config unusable'*)
      case "$I_CC_OUT" in
        *'[OFF][0]'*) ok "$1" ;;
        *) bad "$1" "board off + WARN" "out=[$I_CC_OUT]" ;;
      esac ;;
    *) bad "$1" "a WARN line" "SILENT — out=[$I_CC_OUT]" ;;
  esac
}
# 두 부류로 나뉜다. **관용**해야 하는 것(고칠 수 있는 사소한 형태 차이 → 정상 동작)과
# **시끄러워야** 하는 것(무엇이 옳은지 알 수 없음 → 보드 OFF + WARN 1줄).
I_conf_ok() {   # I_conf_ok <case> <printf-format> — 관용: 보드가 켜져야 한다
  printf "$2" > "$I_BCONF"
  I_CC_OUT="$("$SH" -c 'set -euo pipefail; . '"$I_WORK/inj_helpers.sh"'; printf "[%s]" "${BOARD_NUMBER:-OFF}"' 2>&1)"
  case "$I_CC_OUT" in
    *'[7]'*) ok "$1" ;;
    *) bad "$1" "board ON" "out=[$I_CC_OUT]" ;;
  esac
}
# 1. 마지막 줄에 개행이 없다 — run.md 는 "어떤 순서로든" 이라 number 가 마지막일 수 있다.
#    예전에는 `read` 가 그 줄에서 non-zero 를 내고 본문이 안 돌아 **키가 조용히 사라졌다**.
I_conf_ok "I: an unterminated final line is still parsed" \
  'owner=@me\nfield=F\nfield_needs_human=N\nverified_as=t\ncol_ready=R\ncol_in_progress=P\ncol_blocked=B\ncol_in_review=V\ncol_done=D\nnumber=7'
# 2. 키에 앞쪽 공백 — IFS='=' 는 기본 공백 집합을 **대체**하므로 아무 것도 다듬지 않았다
I_conf_ok "I: whitespace around a key, and around the number, is trimmed" \
  '  number= 7 \n  owner=@me\nfield=F\nfield_needs_human=N\nverified_as=t\ncol_ready=R\ncol_in_progress=P\ncol_blocked=B\ncol_in_review=V\ncol_done=D\n'
# ⚠ 그러나 **표시 이름의 공백은 다듬지 않는다.** GitHub 이 옵션 이름의 뒤 공백을 다듬는지는
# 미측정이고, 여기서 다듬으면 보드에 없는 이름을 쓰게 된다. 바이트 그대로 보존을 고정한다.
printf 'number=7\nowner=@me\nfield=Guild board \nfield_needs_human=N\nverified_as=t\ncol_ready=R\ncol_in_progress=P\ncol_blocked=B\ncol_in_review=V\ncol_done=D\n' > "$I_BCONF"
I_KEEP="$("$SH" -c 'set -euo pipefail; . '"$I_WORK/inj_helpers.sh"'; printf "[%s]" "$BOARD_FIELD"' 2>&1)"
case "$I_KEEP" in
  *'[Guild board ]'*) ok "I: a display name keeps its trailing space (byte-exact)" ;;
  *) bad "I: display names must be byte-exact" "out=[$I_KEEP]" ;;
esac
# 3. 통째로 쓰레기 (Write 가 중간에 끊긴 경우) — 무엇이 옳은지 알 수 없으므로 시끄러워야 한다
I_conf_case "I: a garbage config file is loud" 'not a config\n'
# 4. 빈 파일
I_conf_case "I: an empty config file is loud" ''
# 5. 읽을 수 없는 파일 — [ -f ] 는 참이고 리다이렉트만 실패해 우리 WARN 이 없었다
printf 'number=7\nowner=@me\nfield=F\nfield_needs_human=N\nverified_as=t\ncol_ready=R\ncol_in_progress=P\ncol_blocked=B\ncol_in_review=V\ncol_done=D\n' > "$I_BCONF"
chmod 000 "$I_BCONF"
I_UNREAD="$("$SH" -c 'set -euo pipefail; . '"$I_WORK/inj_helpers.sh"'; printf "[%s]" "${BOARD_NUMBER:-OFF}"' 2>&1)"
chmod 644 "$I_BCONF"
case "$I_UNREAD" in
  *'not readable'*) ok "I: an unreadable config file is named, not left to bash" ;;
  *) bad "I: unreadable config file" "our own WARN" "out=[$I_UNREAD]" ;;
esac

# ── 사유 필드만 못 쓰는 경우: 사유만 끄고 컬럼은 계속 간다 ─────────────────
# 리뷰가 실측으로 잡았다: 스트릭에 두 쓰기의 AND 를 먹이면, `Needs human` 이 TEXT 가 아니라
# 단일선택으로 만들어진 것만으로도 10멤버 뒤에 **컬럼 투영까지** 꺼졌다 — 컬럼 쓰기 10건이
# 전부 성공한 상태에서. 사람이 읽는 것은 컬럼이고 사유는 주석이다.
printf 'number=7\nowner=@me\nfield=Guild board\nfield_needs_human=Needs human\nverified_as=t\ncol_ready=Ready\ncol_in_progress=In progress\ncol_blocked=Blocked\ncol_in_review=In review\ncol_done=Done\n' > "$I_BCONF"
cat > "$I_WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$*" in *"--field-id F_nh"*) exit 1 ;; esac
exit 0
STUB
chmod +x "$I_WORK/bin/gh"
: > "$I_WORK/calls.txt"
GH_CALLS="$I_WORK/calls.txt" PATH="$I_WORK/bin:$PATH" \
  "$SH" -c 'set -euo pipefail; . '"$I_WORK/inj_helpers.sh"'
     board_resolve
     : > "$GH_CALLS"
     i=101; while [ $i -le 130 ]; do board_col $i ready; i=$((i+1)); done
     printf "[%s]" "${BOARD_NUMBER:-OFF}"' > "$I_WORK/rsn.txt" 2>&1
I_RSN_COL=$(grep -c -- '--field-id F_col' "$I_WORK/calls.txt" || true)
case "$(cat "$I_WORK/rsn.txt")" in
  *'[7]'*)
    if [ "$I_RSN_COL" -ge 25 ]; then
      ok "I: a broken reason field disables only the reason (columns=$I_RSN_COL still went out)"
    else
      bad "I: columns must keep going" "columns>=25" "columns=$I_RSN_COL"
    fi ;;
  *) bad "I: a broken reason field must not disable the board" "out=[$(cat "$I_WORK/rsn.txt")]" ;;
esac
case "$(cat "$I_WORK/rsn.txt")" in
  *'unwritable'*) ok "I: and it says so once" ;;
  *) bad "I: the reason-disabled notice is missing" "out=[$(cat "$I_WORK/rsn.txt")]" ;;
esac

# 파일이 아예 없으면 = 보드 OFF, 그리고 **조용해야** 한다 — 기존 사용자 전원이 이 경우다.
rm -f "$I_BCONF"
I_NOF_OUT="$("$SH" -c 'set -euo pipefail; . '"$I_WORK/inj_helpers.sh"'; printf "[%s][%s]" "${BOARD_NUMBER:-OFF}" "$BOARD_WAS_ON"' 2>&1)"
case "$I_NOF_OUT" in
  *'WARN'*) bad "I: no board file must be silent" "out=[$I_NOF_OUT]" ;;
  *'[OFF][0]'*) ok "I: no board config file -> board off, and silent (D2)" ;;
  *) bad "I: no board file accounting" "out=[$I_NOF_OUT]" ;;
esac

printf '\nsprint_supervisor: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
