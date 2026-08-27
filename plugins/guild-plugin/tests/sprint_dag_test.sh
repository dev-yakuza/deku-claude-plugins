#!/usr/bin/env bash
# Verification for `sprint_dag.py` — the one deterministic computation in `/gld sprint`
# (design: design/guild/02-sprint.md §5.2·§5.4a·§12.1).
#
# Scope, honestly: this is a real unit test, not a "does the LLM follow the prose" check.
# Every case here is a pure function of a JSON file, so a regression shows up as a diff
# rather than as a mis-run sprint. That is why the design pushed topological order, cycle
# detection, linearization, base resolution and the plan-hash into a script at all.
#
# The case that matters most is the LINEARIZATION INVARIANT (§5.4a step 3): for every
# declared dep, that dep must be an ancestor in the base_dep forest. An earlier design
# draft's algorithm satisfied every per-graph expectation below while silently losing
# dependencies in 35% of 6-node DAGs — per-shape expectations alone do not catch it.
#
# Usage: bash plugins/guild-plugin/tests/sprint_dag_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DAG="$HERE/../skills/gld/commands/atoms/sprint_dag.py"
[ -f "$DAG" ] || { echo "missing: $DAG" >&2; exit 1; }
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

# run <name> <json> <mode> <expected-exit> <expected-stdout>
run() {
  local name="$1" json="$2" mode="$3" want_rc="$4" want="$5"
  printf '%s' "$json" > "$WORK/in.json"
  local got rc
  got="$("$PY" "$DAG" --input "$WORK/in.json" --mode "$mode" 2>"$WORK/err")"
  rc=$?
  if [ "$rc" != "$want_rc" ]; then
    bad "$name" "exit $rc, want $want_rc ($(head -1 "$WORK/err"))"; return
  fi
  if [ "$got" != "$want" ]; then
    bad "$name" "stdout mismatch
--- got ---
$got
--- want ---
$want"; return
  fi
  ok "$name"
}

M() { # M 101:  → member with no deps ;  M 103:101,102 → deps
  local out="" first=1 spec n d
  for spec in "$@"; do
    n="${spec%%:*}"; d="${spec#*:}"
    [ "$d" = "$n" ] && d=""
    local ds=""
    if [ -n "$d" ]; then ds="$(printf '%s' "$d" | tr ',' '\n' | sed 's/^/    /' | paste -sd, -)"; fi
    [ $first -eq 0 ] && out="$out,"; first=0
    out="$out{\"number\":$n,\"deps\":[${ds// /}]}"
  done
  printf '%s' "$out"
}
B() { # same but the linearized key
  local out="" first=1 spec n d
  for spec in "$@"; do
    n="${spec%%:*}"; d="${spec#*:}"
    [ "$d" = "$n" ] && d=""
    [ $first -eq 0 ] && out="$out,"; first=0
    out="$out{\"number\":$n,\"base_deps\":[${d}]}"
  done
  printf '%s' "$out"
}

echo "== A. linearize (§5.4a) =="

run "linear chain A<-B<-C" \
  "{\"members\":[$(M 101: 102:101 103:102)]}" linearize 0 \
  "101 -
102 101
103 102"

run "three independents keep no base" \
  "{\"members\":[$(M 103: 101: 102:)]}" linearize 0 \
  "101 -
102 -
103 -"

run "fan-in C<-A,B becomes a chain" \
  "{\"members\":[$(M 101: 102: 103:101,102)]}" linearize 0 \
  "101 -
102 101
103 102"

run "diamond D<-B,C<-A becomes one chain" \
  "{\"members\":[$(M 101: 102:101 103:101 104:102,103)]}" linearize 0 \
  "101 -
102 101
103 102
104 103"

run "3-way fan-in E<-A,B,C,D" \
  "{\"members\":[$(M 101: 102: 103: 104: 105:101,102,103,104)]}" linearize 0 \
  "101 -
102 101
103 102
104 103
105 104"

# The counterexample that broke the earlier algorithm: #104 depends on {#101,#103} while
# #103 already depends on #102. Reassigning #103's base_dep to #101 loses #102.
#
# Depth 4 is OPTIMAL here, not a regression: #104 needs both #101 and #103 as ancestors,
# and #103 needs #102 — so #101 and #102 must BOTH sit above #103, forcing a 4-chain.
# (The first draft of this test expected depth 3 by hand and was wrong. Implementing it
# is what settled the question.)
run "counterexample: no dep is lost" \
  "{\"members\":[$(M 101: 102: 103:102 104:101,103)]}" linearize 0 \
  "101 -
102 101
103 102
104 103"

run "one foundation + many independents stays depth 2" \
  "{\"members\":[$(M 101: 102:101 103:101 104:101 105:101)]}" linearize 0 \
  "101 -
102 101
103 101
104 101
105 101"

run "cycle -> exit 2" "{\"members\":[$(M 101:102 102:101)]}" linearize 2 ""

echo "== B. order / cycles =="

run "order follows base_deps" \
  "{\"members\":[$(B 103:102 101: 102:101)]}" order 0 \
  "101
102
103"

run "order tie-break is issue number" \
  "{\"members\":[$(B 103: 101: 102:)]}" order 0 \
  "101
102
103"

run "cycles: none -> exit 0, empty" "{\"members\":[$(M 101: 102:101)]}" cycles 0 ""
run "cycles: found -> exit 3 with path" \
  "{\"members\":[$(M 101:102 102:101)]}" cycles 3 "#101 -> #102 -> #101"

echo "== C. depth (§5.5) =="

run "depth of a 3-chain" \
  "{\"members\":[$(B 101: 102:101 103:102)],\"max_depth\":3}" depth 0 "depth 3"

run "depth over the cap -> exit 4 + chain" \
  "{\"members\":[$(B 101: 102:101 103:102 104:103)],\"max_depth\":3}" depth 4 \
  "depth 4
chain 101,102,103,104"

run "depth without max_depth never fails" \
  "{\"members\":[$(B 101: 102:101 103:102 104:103)]}" depth 0 "depth 4"

echo "== D. base (§5.3) =="

PRS_OPEN='"prs":[{"issue":101,"branch":"feature/#101-x","state":"OPEN"}]'
PRS_MERGED='"prs":[{"issue":101,"branch":"feature/#101-x","state":"MERGED"}]'
PRS_CLOSED='"prs":[{"issue":101,"branch":"feature/#101-x","state":"CLOSED"}]'
BR='"branches":["feature/#101-x"]'
DEF='"default_branch":"develop"'

run "no dep -> DEFAULT" \
  "{\"members\":[$(B 101:)],$DEF}" base 0 "101 DEFAULT"

run "dep PR OPEN -> that branch" \
  "{\"members\":[$(B 101: 102:101)],$PRS_OPEN,$BR,$DEF}" base 0 \
  "101 DEFAULT
102 feature/#101-x"

run "dep PR MERGED -> DEFAULT" \
  "{\"members\":[$(B 101: 102:101)],$PRS_MERGED,$BR,$DEF}" base 0 \
  "101 DEFAULT
102 DEFAULT"

run "dep PR CLOSED -> BLOCKED" \
  "{\"members\":[$(B 101: 102:101)],$PRS_CLOSED,$BR,$DEF}" base 0 \
  "101 DEFAULT
102 BLOCKED:dep-pr-closed"

run "no PR but branch exists (token fallback)" \
  "{\"members\":[$(B 101: 102:101)],$BR,$DEF}" base 0 \
  "101 DEFAULT
102 feature/#101-x"

run "no PR and no branch -> BLOCKED" \
  "{\"members\":[$(B 101: 102:101)],\"branches\":[],$DEF}" base 0 \
  "101 DEFAULT
102 BLOCKED:dep-no-branch"

run "split-completed parent -> DEFAULT, not BLOCKED" \
  "{\"members\":[{\"number\":101,\"base_deps\":[],\"split\":true},{\"number\":102,\"base_deps\":[101]}],\"branches\":[],$DEF}" base 0 \
  "101 DEFAULT
102 DEFAULT"

run "ambiguous branch token -> BLOCKED, never guessed" \
  "{\"members\":[$(B 101: 102:101)],\"branches\":[\"feature/#101-a\",\"fix/101-b\"],$DEF}" base 0 \
  "101 DEFAULT
102 BLOCKED:dep-branch-ambiguous"

run "two base_deps -> exit 2 (input not linearized)" \
  "{\"members\":[{\"number\":101,\"base_deps\":[]},{\"number\":102,\"base_deps\":[]},{\"number\":103,\"base_deps\":[101,102]}],$DEF}" base 2 ""

echo "== E. blocked (§8.7) =="

run "dep needs-human -> transitive block" \
  "{\"members\":[$(B 101: 102:101 103:102)],\"terminal\":{\"101\":\"needs-human\"}}" blocked 0 \
  "102 dep-needs-human:#101
103 upstream:#102"

run "dep failed -> block" \
  "{\"members\":[$(B 101: 102:101)],\"terminal\":{\"101\":\"failed\"}}" blocked 0 \
  "102 dep-failed:#101"

run "dep done -> nothing blocked" \
  "{\"members\":[$(B 101: 102:101)],\"terminal\":{\"101\":\"done\"},$BR}" blocked 0 ""

run "dep PR closed -> block" \
  "{\"members\":[$(B 101: 102:101)],$PRS_CLOSED,$BR}" blocked 0 \
  "102 dep-pr-closed:#101"

echo "== F. hash (§4.6) =="

BODY='# Sprint: x

<!-- guild:sprint:plan -->
plan-hash: 000000000000
- 목표: 결제 흐름 안정화
| 1 | #101 | — |
<!-- /guild:sprint:plan -->

tail'
H1="$(printf '%s' "$BODY" | "$PY" -c 'import json,sys; print(json.dumps({"text":sys.stdin.read()}))' > "$WORK/h.json"; "$PY" "$DAG" --input "$WORK/h.json" --mode hash)"
[ -n "$H1" ] && ok "hash produces a value ($H1)" || bad "hash produces a value" "empty"

# CRLF round-trip through the GitHub web UI must not change the hash — that is the whole
# reason step 3 of §4.6 strips \r. Without it, a human fixing a typo halts every resume.
H2="$(printf '%s' "${BODY//$'\n'/$'\r\n'}" | "$PY" -c 'import json,sys; print(json.dumps({"text":sys.stdin.read()}))' > "$WORK/h2.json"; "$PY" "$DAG" --input "$WORK/h2.json" --mode hash)"
[ "$H1" = "$H2" ] && ok "hash is CRLF-stable" || bad "hash is CRLF-stable" "$H1 != $H2"

# Trailing whitespace likewise.
H3="$(printf '%s' "${BODY/- 목표: 결제 흐름 안정화/- 목표: 결제 흐름 안정화   }" | "$PY" -c 'import json,sys; print(json.dumps({"text":sys.stdin.read()}))' > "$WORK/h3.json"; "$PY" "$DAG" --input "$WORK/h3.json" --mode hash)"
[ "$H1" = "$H3" ] && ok "hash ignores trailing whitespace" || bad "hash ignores trailing whitespace" "$H1 != $H3"

# A real content change MUST change it, or the check is worthless.
H4="$(printf '%s' "${BODY/| 1 | #101 | — |/| 1 | #999 | — |}" | "$PY" -c 'import json,sys; print(json.dumps({"text":sys.stdin.read()}))' > "$WORK/h4.json"; "$PY" "$DAG" --input "$WORK/h4.json" --mode hash)"
[ "$H1" != "$H4" ] && ok "hash changes on a real member edit" || bad "hash changes on a real member edit" "unchanged: $H1"

# The hash line itself is removed, not blanked — so rewriting it does not change the value.
H5="$(printf '%s' "${BODY/plan-hash: 000000000000/plan-hash: abcdef123456}" | "$PY" -c 'import json,sys; print(json.dumps({"text":sys.stdin.read()}))' > "$WORK/h5.json"; "$PY" "$DAG" --input "$WORK/h5.json" --mode hash)"
[ "$H1" = "$H5" ] && ok "hash excludes its own line" || bad "hash excludes its own line" "$H1 != $H5"

printf '{"text":"no markers here"}' > "$WORK/h6.json"
"$PY" "$DAG" --input "$WORK/h6.json" --mode hash >/dev/null 2>&1
[ $? -eq 64 ] && ok "hash without markers -> exit 64" || bad "hash without markers -> exit 64" "wrong exit"

echo "== G. usage / input errors all exit 64 =="

for t in "missing file:--input $WORK/nope.json --mode order" \
         "unknown mode:--input $WORK/in.json --mode nonsense"; do
  name="${t%%:*}"; args="${t#*:}"
  printf '{"members":[{"number":1,"deps":[]}]}' > "$WORK/in.json"
  # shellcheck disable=SC2086
  "$PY" "$DAG" $args >/dev/null 2>&1
  [ $? -eq 64 ] && ok "$name -> 64" || bad "$name -> 64" "wrong exit"
done

printf 'not json' > "$WORK/bad.json"
"$PY" "$DAG" --input "$WORK/bad.json" --mode order >/dev/null 2>&1
[ $? -eq 64 ] && ok "bad JSON -> 64" || bad "bad JSON -> 64" "wrong exit"

printf '{"members":[]}' > "$WORK/empty.json"
"$PY" "$DAG" --input "$WORK/empty.json" --mode order >/dev/null 2>&1
[ $? -eq 64 ] && ok "empty members -> 64" || bad "empty members -> 64" "wrong exit"

# `default_branch` used to be required and then never read (DEFAULT is a token; the caller
# adds the `origin/` prefix). It is accepted when present and no longer demanded.
printf '{"members":[{"number":101,"base_deps":[]}]}' > "$WORK/nodefault.json"
"$PY" "$DAG" --input "$WORK/nodefault.json" --mode base >/dev/null 2>&1
[ $? -eq 0 ] && ok "base without default_branch -> 0 (the key is unused)" || bad "base without default_branch -> 0" "wrong exit"

echo "== G2. a MISSING required key is an input error, not \"no dependencies\" =="
# The most dangerous shape this script can be handed: the pre-linearization file, which has
# `deps` but not yet `base_deps`. Read as "no dependencies" it returned issue-number order,
# depth 1 and DEFAULT for every base — all with exit 0, so nothing warned.
printf '{"members":[{"number":101,"deps":[]},{"number":102,"deps":[101]},{"number":103,"deps":[104]},{"number":104,"deps":[102]}]}' > "$WORK/nokey.json"
for M in order depth base blocked; do
  "$PY" "$DAG" --input "$WORK/nokey.json" --mode "$M" >/dev/null 2>&1
  [ $? -eq 64 ] && ok "missing base_deps -> 64 (--mode $M)" \
                || bad "missing base_deps -> 64 (--mode $M)" "wrong exit $?"
done
# ...but a member that legitimately has an EMPTY list must still work.
printf '{"members":[{"number":101,"base_deps":[]},{"number":102,"base_deps":[]}]}' > "$WORK/emptylists.json"
OUT="$("$PY" "$DAG" --input "$WORK/emptylists.json" --mode order 2>/dev/null)"; RC=$?
[ "$RC" -eq 0 ] && [ "$OUT" = "101
102" ] && ok "present-but-empty base_deps is NOT an error" \
          || bad "present-but-empty base_deps is NOT an error" "rc=$RC out=$OUT"

echo "== G3. dep VALUES are validated =="
printf '{"members":[{"number":101,"deps":"101"},{"number":1,"deps":[]}]}' > "$WORK/depstr.json"
"$PY" "$DAG" --input "$WORK/depstr.json" --mode linearize >/dev/null 2>&1
[ $? -eq 64 ] && ok "deps as a bare string -> 64 (not iterated character by character)" \
             || bad "deps as a bare string -> 64" "wrong exit"
printf '{"members":[{"number":101,"deps":["abc"]}]}' > "$WORK/depbad.json"
"$PY" "$DAG" --input "$WORK/depbad.json" --mode linearize >/dev/null 2>&1
[ $? -eq 64 ] && ok "non-numeric dep -> 64 (not an uncaught ValueError)" || bad "non-numeric dep -> 64" "wrong exit"
printf '{"members":[{"number":101,"deps":[true]}]}' > "$WORK/depbool.json"
"$PY" "$DAG" --input "$WORK/depbool.json" --mode linearize >/dev/null 2>&1
[ $? -eq 64 ] && ok "boolean dep -> 64 (bool is an int subclass)" || bad "boolean dep -> 64" "wrong exit"

echo "== G4. --help is not an error =="
"$PY" "$DAG" --help >/dev/null 2>&1
[ $? -eq 0 ] && ok "--help -> 0 (only argparse FAILURES remap to 64)" || bad "--help -> 0" "wrong exit"

echo "== G5. a cycle in base_deps is exit 2 from every mode that walks it =="
# 64 would read as "bad JSON / bad flag", and the supervisor treats an unparsed `blocked`
# result as "nothing blocked" — it would run every member on top of a cyclic mess.
printf '{"members":[{"number":101,"base_deps":[102]},{"number":102,"base_deps":[101]}],"terminal":{}}' > "$WORK/bdcyc.json"
"$PY" "$DAG" --input "$WORK/bdcyc.json" --mode blocked >/dev/null 2>&1
[ $? -eq 2 ] && ok "blocked with a base_deps cycle -> 2" || bad "blocked with a base_deps cycle -> 2" "wrong exit"

echo "== G6. a self-dependency is dropped loudly, not reported as a cycle =="
printf '{"members":[{"number":101,"deps":[101]},{"number":102,"deps":[101]}]}' > "$WORK/selfdep.json"
OUT="$("$PY" "$DAG" --input "$WORK/selfdep.json" --mode linearize 2>"$WORK/sd.err")"; RC=$?
if [ "$RC" -eq 0 ] && grep -q "depends on itself" "$WORK/sd.err" && [ "$OUT" = "101 -
102 101" ]; then
  ok "self-dependency dropped with a stderr warning"
else
  bad "self-dependency dropped with a stderr warning" "rc=$RC out=$OUT err=$(head -1 "$WORK/sd.err")"
fi

echo "== G7. a CLOSED attempt's branch must not leak into a later OPEN verdict =="
# An Issue can carry several PRs. MERGED > OPEN > CLOSED decides the state — but the branch
# has to be REPLACED with it, or the abandoned branch is handed back as the stack base and
# this Issue's PR is cut from work the human explicitly rejected.
printf '{"members":[{"number":101,"base_deps":[]},{"number":102,"base_deps":[101]}],"prs":[{"issue":101,"branch":"feature/#101-abandoned","state":"CLOSED"},{"issue":101,"state":"OPEN"}],"branches":["feature/#101-abandoned"],"default_branch":"develop"}' > "$WORK/leak.json"
OUT="$("$PY" "$DAG" --input "$WORK/leak.json" --mode base 2>/dev/null)"
case "$OUT" in
  *"102 BLOCKED:dep-pr-no-branch"*) ok "CLOSED branch does not leak into an OPEN verdict" ;;
  *) bad "CLOSED branch does not leak into an OPEN verdict" "got: $(printf '%s' "$OUT" | tr '\n' '|')" ;;
esac

echo "== G7b. two PRs in the SAME state with different heads is ambiguity, not a tie-break =="
# The earlier code took whichever gh returned first, so reversing the input flipped the base
# between the real branch and an abandoned one — silently. Ambiguity is the one thing this
# module refuses everywhere else.
printf '%s' '{"members":[{"number":101,"base_deps":[]},{"number":102,"base_deps":[101]}],"prs":[{"issue":101,"branch":"feature/#101-a","state":"OPEN"},{"issue":101,"branch":"feature/#101-b","state":"OPEN"}],"branches":["feature/#101-a","feature/#101-b"],"default_branch":"develop"}' > "$WORK/amb1.json"
printf '%s' '{"members":[{"number":101,"base_deps":[]},{"number":102,"base_deps":[101]}],"prs":[{"issue":101,"branch":"feature/#101-b","state":"OPEN"},{"issue":101,"branch":"feature/#101-a","state":"OPEN"}],"branches":["feature/#101-a","feature/#101-b"],"default_branch":"develop"}' > "$WORK/amb2.json"
O1="$("$PY" "$DAG" --input "$WORK/amb1.json" --mode base 2>"$WORK/amb.err")"
O2="$("$PY" "$DAG" --input "$WORK/amb2.json" --mode base 2>/dev/null)"
if [ "$O1" = "$O2" ] && printf '%s' "$O1" | grep -q 'BLOCKED:dep-pr-ambiguous' \
   && grep -qiE 'ambiguous|head branch|different head' "$WORK/amb.err"; then
  ok "same-state rival PRs -> BLOCKED:dep-pr-ambiguous, order-independent, warned on stderr"
else
  bad "same-state rival PRs -> BLOCKED:dep-pr-ambiguous" "a=$(printf '%s' "$O1" | tr '\n' '|') b=$(printf '%s' "$O2" | tr '\n' '|') err=$(head -1 "$WORK/amb.err" 2>/dev/null)"
fi
# ...but the SAME branch twice is not ambiguous, and a more-final PR still wins outright.
printf '%s' '{"members":[{"number":101,"base_deps":[]},{"number":102,"base_deps":[101]}],"prs":[{"issue":101,"branch":"feature/#101-a","state":"OPEN"},{"issue":101,"branch":"feature/#101-a","state":"OPEN"}],"branches":["feature/#101-a"],"default_branch":"develop"}' > "$WORK/amb3.json"
O3="$("$PY" "$DAG" --input "$WORK/amb3.json" --mode base 2>/dev/null)"
case "$O3" in
  *"102 feature/#101-a"*) ok "the same head twice is NOT ambiguous" ;;
  *) bad "the same head twice is NOT ambiguous" "got: $(printf '%s' "$O3" | tr '\n' '|')" ;;
esac
# ⚠ And a recorded ambiguity must be CLEARED when a more-final PR arrives. Two rejected
# attempts plus one live PR is not ambiguous — there is exactly one branch to stack onto. The
# one-line `rival.pop` that does this survived every earlier case (measured), because they all
# had a single state.
printf '%s' '{"members":[{"number":101,"base_deps":[]},{"number":102,"base_deps":[101]}],"prs":[{"issue":101,"branch":"feature/#101-old1","state":"CLOSED"},{"issue":101,"branch":"feature/#101-old2","state":"CLOSED"},{"issue":101,"branch":"feature/#101-live","state":"OPEN"}],"branches":["feature/#101-old1","feature/#101-old2","feature/#101-live"],"default_branch":"develop"}' > "$WORK/amb5.json"
O5="$("$PY" "$DAG" --input "$WORK/amb5.json" --mode base 2>/dev/null)"
case "$O5" in
  *"102 feature/#101-live"*) ok "an ambiguity recorded at a LOWER rank is cleared by a more-final PR" ;;
  *) bad "an ambiguity recorded at a lower rank is cleared by a more-final PR" "got: $(printf '%s' "$O5" | tr '\n' '|')" ;;
esac

printf '%s' '{"members":[{"number":101,"base_deps":[]},{"number":102,"base_deps":[101]}],"prs":[{"issue":101,"branch":"feature/#101-a","state":"OPEN"},{"issue":101,"branch":"feature/#101-b","state":"MERGED"}],"branches":["feature/#101-a","feature/#101-b"],"default_branch":"develop"}' > "$WORK/amb4.json"
O4="$("$PY" "$DAG" --input "$WORK/amb4.json" --mode base 2>/dev/null)"
case "$O4" in
  *"102 DEFAULT"*) ok "a MERGED PR outranks an OPEN rival without becoming ambiguous" ;;
  *) bad "a MERGED PR outranks an OPEN rival" "got: $(printf '%s' "$O4" | tr '\n' '|')" ;;
esac

echo "== G8. hash: pure-formatting edits must NOT change the value =="
# §4.6 exists because a mismatch halts every unattended resume. Trailing whitespace and CRLF
# were normalised but marker-adjacent BLANK LINES were not — one blank line each was stripped,
# so a human adding a second one halted the sprint. Golden value included: without one, a
# normalisation change during a plugin upgrade stops every in-flight sprint at its first check.
cat > "$WORK/hash.py" <<'PY'
import json, subprocess, sys
py, dag, work = sys.argv[1], sys.argv[2], sys.argv[3]
O, C = "<!-- guild:sprint:plan -->", "<!-- /guild:sprint:plan -->"
def h(body):
    p = work + "/hh.json"
    open(p, "w").write(json.dumps({"text": body}))
    r = subprocess.run([py, dag, "--input", p, "--mode", "hash"],
                       capture_output=True, text=True)
    return r.stdout.strip(), r.returncode
table = "| # | issue | base |\n|---|---|---|\n| 1 | #101 | - |"
base, rc = h(O + "\n" + table + "\n" + C)
if rc != 0:
    print("ERR canonical body failed rc=%d" % rc); raise SystemExit(0)
variants = {
    "3 blank lines each side":  O + "\n\n\n\n" + table + "\n\n\n\n" + C,
    "trailing whitespace":      O + "\n" + table.replace("|\n", "|   \n") + "   \n" + C,
    "CRLF throughout":          (O + "\n" + table + "\n" + C).replace("\n", "\r\n"),
    "a plan-hash: line":        O + "\nplan-hash: deadbeefcafe\n" + table + "\n" + C,
    "text outside the markers": "PREAMBLE\n" + O + "\n" + table + "\n" + C + "\nEPILOGUE",
}
for name, body in variants.items():
    got, rc = h(body)
    if rc != 0 or got != base:
        print("DIFF %s -> %s (want %s, rc=%d)" % (name, got, base, rc)); raise SystemExit(0)
changed, _ = h(O + "\n" + table + "\n| 2 | #102 | #101 |\n" + C)
if changed == base:
    print("ERR a real member change did NOT change the hash"); raise SystemExit(0)
print("OK %s" % base)
PY
HS="$("$PY" "$WORK/hash.py" "$PY" "$DAG" "$WORK")"
case "$HS" in
  "OK a980f9fd4b9d") ok "hash: formatting-invariant AND matches the golden value ($HS)" ;;
  OK*)               bad "hash matches the golden value" "formatting-invariant but the value moved: $HS — if this change is intended, every IN-FLIGHT sprint will halt with plan-hash-mismatch" ;;
  *)                 bad "hash is formatting-invariant" "$HS" ;;
esac

printf '{"text":"<!-- /guild:sprint:plan -->\nX\n<!-- guild:sprint:plan -->\nLATER"}' > "$WORK/rev.json"
"$PY" "$DAG" --input "$WORK/rev.json" --mode hash >/dev/null 2>&1
[ $? -eq 64 ] && ok "reversed plan markers -> 64 (presence is not order)" \
             || bad "reversed plan markers -> 64" "wrong exit — it would hash everything after the close marker"

echo "== G9. mode_linearize runs its own post-verification =="
# §5.4a step 3 calls this MANDATORY. Section I below re-implements the invariant, so it
# catches an algorithm regression — but not the removal of the runtime guard itself.
if grep -q 'verify_cover' "$DAG" && "$PY" - "$DAG" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
body = src[src.index("def mode_linearize"):]
body = body[:body.index("\ndef ")]
raise SystemExit(0 if "verify_cover" in body else 1)
PY
then
  ok "mode_linearize calls verify_cover (the runtime guard, not just the test)"
else
  bad "mode_linearize calls verify_cover" "the post-check is gone — per-shape expectations pass while deps are silently lost"
fi

echo "== H. deps outside the sprint are dropped with a warning =="
printf '{"members":[{"number":101,"deps":[999]}]}' > "$WORK/out.json"
OUT="$("$PY" "$DAG" --input "$WORK/out.json" --mode linearize 2>"$WORK/err")"
if [ "$OUT" = "101 -" ] && grep -q '999' "$WORK/err"; then
  ok "outside dep ignored + warned"
else
  bad "outside dep ignored + warned" "stdout=[$OUT] err=[$(cat "$WORK/err")]"
fi

echo "== I. linearization invariant over EVERY small DAG up to N=6 (§5.4a step 3) =="
# This is the case that the earlier algorithm failed. Per-shape expectations above all
# passed for it; only the exhaustive invariant caught the loss.
cat > "$WORK/inv.py" <<'PY'
# In-process: import the real module and call linearize() directly. Spawning the CLI per graph
# was ~1100 subprocesses and dominated the suite's runtime; importing exercises the same code.
import importlib.util, itertools, sys
spec = importlib.util.spec_from_file_location("sprint_dag", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def anc(base, x):
    out, p = set(), base.get(x)
    while p is not None:
        out.add(p); p = base.get(p)
    return out

for n in (3, 4, 5, 6):
    nodes = list(range(101, 101 + n))
    pairs = [(a, b) for a in nodes for b in nodes if a < b]     # acyclic by construction
    for mask in range(1 << len(pairs)):
        deps = {x: [] for x in nodes}
        for k, (a, b) in enumerate(pairs):
            if mask >> k & 1:
                deps[b].append(a)
        base, _ = m.linearize(nodes, deps)
        if base is None:
            print("N=%d mask=%d reported a cycle on an acyclic graph" % (n, mask)); raise SystemExit(0)
        for x in nodes:
            a = anc(base, x)
            if any(d not in a for d in deps[x]):
                print("N=%d mask=%d lost %s" % (n, mask, [(x, d) for d in deps[x] if d not in a]))
                raise SystemExit(0)
        # the forest invariant: at most one parent, and no self-parent
        for x in nodes:
            if base[x] == x:
                print("N=%d mask=%d self-parent at %d" % (n, mask, x)); raise SystemExit(0)
print("OK")
PY
INV="$("$PY" "$WORK/inv.py" "$DAG")"
if [ "$INV" = "OK" ]; then ok "invariant holds for ALL DAGs up to N=6 (33,864 graphs)"; else bad "invariant holds for ALL DAGs up to N=6" "$INV"; fi

echo
printf 'sprint_dag: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
