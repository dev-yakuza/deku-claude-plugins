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

printf '\nsprint_supervisor: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
