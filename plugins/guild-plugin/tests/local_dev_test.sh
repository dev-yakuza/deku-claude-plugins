#!/usr/bin/env bash
# Verification for `local_dev.py` — the opt-in local-model developer (implementation only).
#
# Real git repos and a real detached worker; only Ollama is a stub — a small HTTP server that
# answers /api/tags and serves scripted /api/chat replies in order (each may sleep first), and
# records the order in which jobs reached the model.
#
# The cases that matter most:
#   • a fallback always restores the implementation files and keeps what the model wrote as a diff
#   • liveness is a held lock, never a pid: a just-started worker never reads as dead, a reused
#     pid never keeps a dead ticket alive, two settlers of one dead job write one record
#   • queue wait is NOT active time — a job held behind the queue past total_timeout still runs
#   • an attended job never waits: a busy queue is an immediate `queue_busy`
#   • first come, first served across jobs
#   • a resumed leader re-running `start` gets the same job, not a second one
#   • replies are parsed the way models write them (fences, CRLF) and files keep their line endings
#
# Usage: bash plugins/guild-plugin/tests/local_dev_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LD="$HERE/../skills/gld/commands/atoms/local_dev.py"
[ -f "$LD" ] || { echo "missing: $LD" >&2; exit 1; }
PY="${PY:-python3}"
WORK="$(mktemp -d)" || { echo "mktemp -d failed" >&2; exit 1; }
[ -n "$WORK" ] && [ -d "$WORK" ] || { echo "mktemp -d gave no directory" >&2; exit 1; }
SERVER_PID=""; HOLDERS=""
cleanup() {
  [ -n "$SERVER_PID" ] && { kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; }
  for p in $HOLDERS; do kill "$p" 2>/dev/null; done
  pkill -f "$WORK/" 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT
PASS=0; FAIL=0

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
unset GIT_CONFIG GIT_CONFIG_COUNT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
export GIT_CONFIG_NOSYSTEM=1 HOME="$WORK/home"; mkdir -p "$HOME"
git config --global init.defaultBranch main
git config --global core.autocrlf false
export GLD_LOCAL_DEV_QUEUE_DIR="$WORK/queue"

gld_skip() { echo "SKIP: $1" >&2; [ "${GLD_ALLOW_SKIP:-0}" = 1 ] && exit 0; \
            echo "FAIL  스킵은 통과가 아닙니다 — GLD_ALLOW_SKIP=1 로 명시하십시오." >&2; exit 1; }
"$PY" -c "pass" >/dev/null 2>&1 || gld_skip "$PY is not usable — this suite is python-based"
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n        expected: %s\n        got:      %s\n' "$1" "$2" "$3"; }
eq()  { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "$2" "$3"; fi; }

# ---------------------------------------------------------------- fake Ollama
cat > "$WORK/fake_ollama.py" <<'PYEOF'
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
D = sys.argv[1]
LOCK = threading.Lock()
def pop():
    with LOCK:
        p = os.path.join(D, "replies.jsonl")
        lines = open(p).read().splitlines() if os.path.exists(p) else []
        if not lines:
            return {"content": "no scripted reply", "done_reason": "stop"}
        open(p, "w").write("\n".join(lines[1:]) + ("\n" if lines[1:] else ""))
        return json.loads(lines[0])
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        try: self.wfile.write(b)
        except OSError: pass
    def do_GET(self):
        self._send({"models": [{"name": n} for n in open(os.path.join(D, "models")).read().split()]})
    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = req["messages"][-1]["content"]
        issue = user.split("Issue #", 1)[1].split(" ", 1)[0] if "Issue #" in user else "?"
        with LOCK:
            open(os.path.join(D, "order"), "a").write(issue + "\n")
            open(os.path.join(D, "last_options.json"), "w").write(json.dumps(req.get("options")))
            open(os.path.join(D, "last_prompt.txt"), "w").write(user)
            open(os.path.join(D, "last_think.json"), "w").write(json.dumps(req.get("think")))
        r = pop()
        time.sleep(r.get("sleep", 0))
        self._send({"message": {"role": "assistant", "content": r["content"],
                                "thinking": r.get("thinking", "hmm")},
                    "done_reason": r.get("done_reason", "stop"),
                    "prompt_eval_count": 100, "eval_count": 10})
s = ThreadingHTTPServer(("127.0.0.1", 0), H)
open(os.path.join(D, "port"), "w").write(str(s.server_address[1]))
s.serve_forever()
PYEOF
FAKE="$WORK/fake"; mkdir -p "$FAKE"; echo "qwen-test:latest" > "$FAKE/models"
"$PY" "$WORK/fake_ollama.py" "$FAKE" & SERVER_PID=$!
for _ in $(seq 50); do [ -s "$FAKE/port" ] && break; sleep 0.1; done
[ -s "$FAKE/port" ] || { echo "fake ollama did not start" >&2; exit 1; }
URL="http://127.0.0.1:$(cat "$FAKE/port")"

reply() { "$PY" -c 'import json,sys; print(json.dumps({"content": sys.argv[1], "done_reason": sys.argv[2], "sleep": float(sys.argv[3])}))' "$1" "${2:-stop}" "${3:-0}" >> "$FAKE/replies.jsonl"; }
# reply_cut THINKING — cut off at the cap while still reasoning: no content at all
reply_cut() { "$PY" -c 'import json,sys; print(json.dumps({"content": "", "thinking": sys.argv[1], "done_reason": "length"}))' "$1" >> "$FAKE/replies.jsonl"; }
FIX_BLOCK=$'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
WRONG_BLOCK=$'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = STILL_BROKEN\n>>>>>>> REPLACE'
MISS_BLOCK=$'impl.txt\n<<<<<<< SEARCH\nno such line\n=======\nx\n>>>>>>> REPLACE'
OUTSIDE_BLOCK=$'other.txt\n<<<<<<< SEARCH\nkeep me\n=======\nchanged\n>>>>>>> REPLACE'

# mkrepo <dir> <issue> <local_developer json> [lint]
mkrepo() {
  local d="$1" n="$2" ld="$3" lint="${4:-null}"
  mkdir -p "$d/.claude/guild/memory" "$d/docs/specs/$n" "$d/test"
  git -C "$d" init -q
  printf 'status = BROKEN\n' > "$d/impl.txt"
  printf 'keep me\n' > "$d/other.txt"
  printf '#!/bin/sh\ngrep -q "status = FIXED" impl.txt || { echo "expected FIXED"; exit 1; }\n' > "$d/check.sh"
  printf '#!/bin/sh\n(sleep 60 &)\ngrep -q "status = FIXED" impl.txt || exit 1\n' > "$d/check_bg.sh"
  printf 'memory/\n' > "$d/.claude/guild/.gitignore"
  printf '# skeleton for #%s\nset status to FIXED\n' "$n" > "$d/docs/specs/$n/skeleton.md"
  printf 'v1\n' > "$d/test/impl_test.txt"
  "$PY" - "$d/.claude/guild/config.json" "$ld" "$lint" <<'PYEOF'
import json, sys
ld = json.loads(sys.argv[2]); lint = None if sys.argv[3] == "null" else sys.argv[3]
json.dump({"version": "t", "commands": {"test": "sh check.sh", "lint": lint},
           "local_developer": ld}, open(sys.argv[1], "w"))
PYEOF
  git -C "$d" add -A && git -C "$d" commit -qm base
  git -C "$d" switch -qc "fix-$n"
  printf 'v2 — expects FIXED\n' > "$d/test/impl_test.txt"
  git -C "$d" commit -qam "test: red test"
}
LDJSON() { "$PY" -c 'import json,sys; d={"enabled":True,"model":"qwen-test","ollama_url":sys.argv[1],"max_attempts":3,"attempt_timeout_min":0.5,"total_timeout_min":1,"test_cmd":"sh check.sh {files}"}; d.update(json.loads(sys.argv[2] or "{}")); print(json.dumps(d))' "$URL" "${1:-}"; }
ld() { (cd "$1" && shift && "$PY" "$LD" "$@"); }
field() { "$PY" -c 'import json,sys; t=sys.stdin.read().split(">>> LOCAL-DEV <<<\n")[-1]; d=json.loads(t); v=d
for k in sys.argv[1].split("."): v=v[int(k)] if isinstance(v,list) else v.get(k)
print(v)' "$1"; }
start() { local r="$1" n="$2"; shift 2; ld "$r" start --issue "$n" --base main --files impl.txt --tests test/impl_test.txt "$@"; }
waitjob() { ld "$1" wait --issue "$2" --max-seconds "${3:-30}"; }
followup_field() { "$PY" -c 'import json,sys; print([json.loads(l) for l in open(sys.argv[1]) if "\"followup\"" in l][-1][sys.argv[2]])' "$1/.claude/guild/memory/local-dev/runs.jsonl" "$2"; }
# hold — a live ticket older than any job's: a background python holding the ticket's flock; sets $H.
# ⚠ Never call it as $(hold): the holder would inherit the capture pipe and block it.
hold() {
  mkdir -p "$GLD_LOCAL_DEV_QUEUE_DIR"
  "$PY" -c 'import fcntl,os,sys,time; fd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT); fcntl.flock(fd,fcntl.LOCK_EX); time.sleep(300)' \
    "$GLD_LOCAL_DEV_QUEUE_DIR/00000000000000000001-1-aaaaaa.ticket" >/dev/null 2>&1 & H=$!
  HOLDERS="$HOLDERS $H"; sleep 0.5
}
release() { kill "$H" 2>/dev/null; wait "$H" 2>/dev/null; }

# ---------------------------------------------------------------- 1. eligibility
echo "== eligibility"
R="$WORK/r1"; mkrepo "$R" 1 "$(LDJSON '{"enabled": false}')"
eq "disabled → fallback ineligible:disabled" "ineligible:disabled" "$(start "$R" 1 | field reason)"
R="$WORK/r2"; mkrepo "$R" 2 "$(LDJSON '{"ollama_url": "http://127.0.0.1:9"}')"
eq "server down → server_down" "server_down" "$(start "$R" 2 | field reason)"
R="$WORK/r3"; mkrepo "$R" 3 "$(LDJSON '{"model": "absent-model"}')"
eq "model not pulled → ineligible:model_not_pulled" "ineligible:model_not_pulled" "$(start "$R" 3 | field reason)"
R="$WORK/r3b"; mkrepo "$R" 3 "$(LDJSON '{"test_cmd": "sh check.sh"}')"
eq "a test_cmd without {files} → ineligible:no_test_cmd" "ineligible:no_test_cmd" "$(start "$R" 3 | field reason)"
R="$WORK/r4"; mkrepo "$R" 4 "$(LDJSON)"
try4() { local got; got="$(ld "$R" start --issue 4 --base "$3" --files "$1" --tests test/impl_test.txt | field reason)"; ld "$R" ack --issue 4 >/dev/null; eq "$2" "$4" "$got"; }
try4 test/impl_test.txt "a test file passed as an implementation file is refused" main "ineligible:file_not_allowed:test/impl_test.txt"
try4 ./test/impl_test.txt "…also when spelled ./test/…" main "ineligible:file_not_allowed:test/impl_test.txt"
try4 ./.claude/guild/config.json "a ./.claude/ path is refused" main "ineligible:file_not_allowed:.claude/guild/config.json"
try4 ../outside.txt "a path outside the repo is refused" main "ineligible:file_outside_repo:../outside.txt"
try4 nope.txt "a missing file is refused" main "ineligible:file_missing:nope.txt"
try4 impl.txt "tests unchanged against the base → ineligible" HEAD "ineligible:tests_unchanged_vs_base"
printf 'dirty\n' >> "$R/impl.txt"
try4 impl.txt "uncommitted implementation edits → ineligible" main "ineligible:uncommitted_changes"
git -C "$R" checkout -q -- impl.txt
printf '\xff\xfe\n' > "$R/bin.txt"; git -C "$R" add bin.txt; git -C "$R" commit -qm bin
try4 bin.txt "a non-UTF-8 file → ineligible:not_utf8" main "ineligible:not_utf8:bin.txt"
printf 'new\n' > "$R/test/new_test.txt"
got="$(ld "$R" start --issue 4 --base main --files impl.txt --tests test/new_test.txt | field reason)"; ld "$R" ack --issue 4 >/dev/null
eq "an untracked test → ineligible:test_untracked" "ineligible:test_untracked:test/new_test.txt" "$got"
rm "$R/test/new_test.txt"
R="$WORK/r4b"; mkrepo "$R" 4 "$(LDJSON)"; rm "$R/docs/specs/4/skeleton.md"
eq "no skeleton → ineligible:no_skeleton" "ineligible:no_skeleton" "$(start "$R" 4 | field reason)"
R="$WORK/r5"; mkrepo "$R" 5 "$(LDJSON '{"num_ctx": 20100, "max_output_tokens": 1000, "max_output_tokens_retry": 1000}')"
eq "a prompt over the context budget → ineligible" "ineligible:context_too_large" "$(start "$R" 5 | field reason)"
R="$WORK/r5b"; mkrepo "$R" 7 "$(LDJSON '{"num_ctx": 21000, "max_output_tokens": 1000, "max_output_tokens_retry": 1000}')"
"$PY" -c 'import sys; open(sys.argv[1],"a").write("설계 " * 4000)' "$R/docs/specs/7/skeleton.md"; git -C "$R" commit -qam big
eq "CJK text is counted near 1 token/char — 12k chars of Korean overflow a 1k prompt budget" "ineligible:context_too_large" "$(start "$R" 7 | field reason)"
R="$WORK/r6"; mkrepo "$R" 6 "$(LDJSON)"; printf 'status = FIXED\n' > "$R/impl.txt"; git -C "$R" commit -qam already
start "$R" 6 >/dev/null
eq "tests already green before any edit → ineligible:tests_already_green" "ineligible:tests_already_green" "$(waitjob "$R" 6 | field reason)"
R="$WORK/r6b"; mkrepo "$R" 6 "$(LDJSON '{"test_cmd": "no-such-runner {files}"}')"
start "$R" 6 >/dev/null
eq "a test command the shell cannot run (127) → ineligible:test_cmd_not_runnable" "ineligible:test_cmd_not_runnable" "$(waitjob "$R" 6 | field reason)"
: > "$FAKE/replies.jsonl"

# ---------------------------------------------------------------- 2. pass on the first attempt
echo "== pass"
R="$WORK/r10"; mkrepo "$R" 10 "$(LDJSON)"; : > "$FAKE/replies.jsonl"; : > "$FAKE/order"
reply "$FIX_BLOCK" stop 2
S="$(start "$R" 10 --note "root cause: status never set")"
case "$(echo "$S" | field state)" in queued|running) ok "start returns at once with a live job";; *) bad "start returns at once" "queued|running" "$(echo "$S" | field state)";; esac
DEAD=0; for _ in 1 2 3 4 5 6 7 8; do [ "$(ld "$R" status --issue 10 | field state)" = fallback ] && DEAD=1; done
eq "a just-started worker never reads as dead (lock handed down before spawn)" "0" "$DEAD"
OUT="$(waitjob "$R" 10)"
eq "first-attempt pass → local_pass" "local_pass" "$(echo "$OUT" | field state)"
eq "the implementation now carries the fix" "status = FIXED" "$(cat "$R/impl.txt")"
eq "one attempt, outcome pass" "pass|1" "$(echo "$OUT" | field attempts.0.outcome)|$(echo "$OUT" | field attempt_count)"
eq "tree: uncommitted" "uncommitted" "$(echo "$OUT" | field tree)"
grep -q "root cause: status never set" "$FAKE/last_prompt.txt" && ok "--note reaches the model" || bad "--note in prompt" "present" "absent"
EV="$(echo "$OUT" | field evidence)"
[ -s "$R/$EV" ] && ok "raw test output saved as evidence" || bad "evidence file" "non-empty $EV" "missing"
eq "runs.jsonl got one run line" "1" "$(grep -c '"type": "run"' "$R/.claude/guild/memory/local-dev/runs.jsonl")"
eq "num_predict carries max_output_tokens" "8000" "$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["num_predict"])' "$FAKE/last_options.json")"
eq "a second start returns the same job (resume-safe)" "$(echo "$OUT" | field job_id)" "$(start "$R" 10 | field job_id)"
git -C "$R" add impl.txt
ld "$R" revert --issue 10 >/dev/null
eq "revert puts staged and working copies back (a refused commit)" "status = BROKEN|" "$(cat "$R/impl.txt")|$(git -C "$R" status --porcelain -- impl.txt)"
eq "…and status then says tree: restored" "restored" "$(ld "$R" status --issue 10 | field tree)"
printf 'status = FIXED\n' > "$R/impl.txt"; git -C "$R" commit -qam impl
eq "after the leader committed, tree: committed (a resumed leader skips the commit)" "committed" "$(ld "$R" status --issue 10 | field tree)"
ld "$R" ack --issue 10 >/dev/null
eq "after ack, status is none" "none" "$(ld "$R" status --issue 10 | field state)"
eq "status --last still finds the acknowledged pass, its code in the tree" "local_pass|True" "$(ld "$R" status --issue 10 --last | field state)|$(ld "$R" status --issue 10 --last | field local_code_in_tree)"
printf 'status = FIXED  # redone\n' > "$R/impl.txt"
eq "…and reports local_code_in_tree false once a redo changed the files" "False" "$(ld "$R" status --issue 10 --last | field local_code_in_tree)"
git -C "$R" checkout -q -- impl.txt
ld "$R" note --issue 10 --event "tech-lead-blocked: missing guard" >/dev/null
eq "note attaches to the consumed job" "local_pass" "$(followup_field "$R" job_final)"
eq "a note spends the exemption — local_code_in_tree false afterwards" "False" "$(ld "$R" status --issue 10 --last | field local_code_in_tree)"
eq "report counts what happened after a pass" "1" "$(ld "$R" report | field after_pass.tech-lead-blocked)"
eq "the job folder is gitignored (memory/)" "" "$(git -C "$R" status --porcelain -- .claude)"

# red tests a test-running pre-commit hook refused: staged, not committed
R="$WORK/r10s"; mkrepo "$R" 19 "$(LDJSON)"; : > "$FAKE/replies.jsonl"
git -C "$R" reset -q --soft HEAD~1                      # undo the red-test commit, keep it staged
reply "$FIX_BLOCK" stop 0
start "$R" 19 >/dev/null; OUT="$(waitjob "$R" 19)"
eq "staged (uncommitted) red tests are accepted and the job passes" "local_pass|uncommitted" "$(echo "$OUT" | field state)|$(echo "$OUT" | field tree)"
grep -q "expects FIXED" "$FAKE/last_prompt.txt" && ok "…and the staged test diff reaches the model" || bad "staged test diff in prompt" "present" "absent"
eq "…the staged tests are left as they were" "M  test/impl_test.txt" "$(git -C "$R" status --porcelain -- test)"

# ---------------------------------------------------------------- 3. three failures → fallback
echo "== fallback after max_attempts"
R="$WORK/r11"; mkrepo "$R" 11 "$(LDJSON)"; : > "$FAKE/replies.jsonl"
reply "$WRONG_BLOCK"; reply "$MISS_BLOCK"; reply "thinking forever" length
OUT="$(start "$R" 11 >/dev/null; waitjob "$R" 11)"
eq "fallback reason max_attempts" "max_attempts" "$(echo "$OUT" | field reason)"
eq "attempt outcomes test_fail, apply_fail, output_cap" "test_fail apply_fail output_cap" \
  "$(echo "$OUT" | field attempts.0.outcome) $(echo "$OUT" | field attempts.1.outcome) $(echo "$OUT" | field attempts.2.outcome)"
eq "implementation restored to its pre-job content" "status = BROKEN" "$(cat "$R/impl.txt")"
eq "working tree clean after the fallback" "" "$(git -C "$R" status --porcelain -- impl.txt)"
LDF="$R/$(echo "$OUT" | field last_diff)"
grep -q "STILL_BROKEN" "$LDF" && ok "last-local.diff keeps what the model wrote" || bad "last-local.diff" "contains STILL_BROKEN" "$(head -3 "$LDF" 2>&1)"
J="$(echo "$OUT" | field job_dir)"
grep -q "Previous attempt failed" "$R/$J/attempt2.prompt.txt" 2>/dev/null \
  && ok "a retry is a fresh prompt carrying the failure" || bad "retry prompt" "feedback section" "missing"
eq "the cap stays at max_output_tokens until an attempt hits it" "8000 8000 8000" \
  "$(echo "$OUT" | field attempts.0.num_predict) $(echo "$OUT" | field attempts.1.num_predict) $(echo "$OUT" | field attempts.2.num_predict)"

# an attempt cut off at the cap raises the cap of the next one
R="$WORK/r11c"; mkrepo "$R" 18 "$(LDJSON)"; : > "$FAKE/replies.jsonl"
reply "thinking forever" length; reply "$FIX_BLOCK" stop 1
OUT="$(start "$R" 18 >/dev/null; waitjob "$R" 18)"
eq "output_cap → the next attempt runs at max_output_tokens_retry and passes" "8000 16000 local_pass" \
  "$(echo "$OUT" | field attempts.0.num_predict) $(echo "$OUT" | field attempts.1.num_predict) $(echo "$OUT" | field state)"
eq "…the raised cap reached the model" "16000" "$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["num_predict"])' "$FAKE/last_options.json")"
REP="$(ld "$R" report)"
eq "report counts how raised-cap attempts ended" "1" "$(echo "$REP" | field raised_cap_outcomes.pass)"
case "$(echo "$REP" | field warnings.0)" in *"over attempt_timeout_min"*) ok "report warns when the retry cap cannot be generated in attempt_timeout_min";;
  *) bad "retry-cap time warning" "a warning" "$(echo "$REP" | field warnings)";; esac
eq "an attempt cut off with some edit text keeps reasoning on" "None" "$(echo "$OUT" | field attempts.1.think)"

# cut off while still reasoning, no edit written: the next attempt gets the reasoning's tail, reasoning off
R="$WORK/r11d"; mkrepo "$R" 17 "$(LDJSON)"; : > "$FAKE/replies.jsonl"
reply_cut "$("$PY" -c 'print("x" * 20000 + " PLAN-TAIL: replace BROKEN with FIXED")')"; reply "$FIX_BLOCK"
OUT="$(start "$R" 17 >/dev/null; waitjob "$R" 17)"
eq "reasoning cut off → the next attempt runs with think false and passes" "None False local_pass" \
  "$(echo "$OUT" | field attempts.0.think) $(echo "$OUT" | field attempts.1.think) $(echo "$OUT" | field state)"
eq "…think: false reached the model" "false" "$(cat "$FAKE/last_think.json")"
grep -q "PLAN-TAIL: replace BROKEN with FIXED" "$FAKE/last_prompt.txt" && grep -q "Your earlier analysis" "$FAKE/last_prompt.txt" \
  && ok "…its prompt carries the cut-off reasoning's tail" || bad "carried reasoning" "tail in prompt" "missing"
eq "…only the last CARRY_CHARS of it" "True" "$("$PY" -c 'import re,sys; print(max(map(len, re.findall("x+", open(sys.argv[1]).read()))) < 12000)' "$FAKE/last_prompt.txt")"
eq "a first attempt sends no think field" "null" "$(R2="$WORK/r11e"; mkrepo "$R2" 16 "$(LDJSON)"; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"; start "$R2" 16 >/dev/null; waitjob "$R2" 16 >/dev/null; cat "$FAKE/last_think.json")"

# ---------------------------------------------------------------- 4. reply parsing
echo "== reply parsing and file safety"
R="$WORK/r12"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply "$OUTSIDE_BLOCK"$'\n\n'"$FIX_BLOCK"
OUT="$(start "$R" 12 >/dev/null; waitjob "$R" 12)"
eq "an edit to a non-allowed file fails the whole reply" "apply_fail" "$(echo "$OUT" | field attempts.0.outcome)"
eq "…and nothing was written, not even the allowed block" "status = BROKEN|keep me" "$(cat "$R/impl.txt")|$(cat "$R/other.txt")"
R="$WORK/r12b"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply $'Here is the fix:\n\nimpl.txt\n```text\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE\n```'
eq "a fenced block (path, then a \`\`\` line) is applied" "local_pass" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)"
R="$WORK/r12c"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply "$(printf '%s' "$FIX_BLOCK" | sed 's/$/\r/')"
eq "a CRLF reply is applied" "local_pass" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)"
R="$WORK/r12d"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
printf 'head\r\nstatus = BROKEN\r\ntail\r\n' > "$R/impl.txt"; git -C "$R" commit -qam crlf
reply "$FIX_BLOCK"
start "$R" 12 >/dev/null; waitjob "$R" 12 >/dev/null
eq "a CRLF file keeps its CRLF endings — only the edited line changes" "1 1" "$(git -C "$R" diff --numstat -- impl.txt | awk '{print $1, $2}')"
R="$WORK/r12e"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
printf 'Title\n=======\nstatus = BROKEN\n' > "$R/impl.txt"; git -C "$R" commit -qam md
reply $'impl.txt\n<<<<<<< SEARCH\nTitle\n=======\nstatus = BROKEN\n=======\nTitle\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
start "$R" 12 >/dev/null; waitjob "$R" 12 >/dev/null
eq "a ======= line inside SEARCH: the longest split that matches once wins" "Title|=======|status = FIXED" "$(tr '\n' '|' < "$R/impl.txt" | sed 's/|$//')"
R="$WORK/r12g"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
printf 'a = 1\nstatus = BROKEN\n' > "$R/impl.txt"; git -C "$R" commit -qam two
reply $'impl.txt\n<<<<<<< SEARCH\na = 1\n=======\na = 2\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
eq "a second block without its filename repeated edits the same file" "local_pass|a = 2" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)|$(head -1 "$R/impl.txt")"
R="$WORK/r12f"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
: > "$R/impl.txt"; git -C "$R" commit -qam empty
reply $'impl.txt\n<<<<<<< SEARCH\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
eq "an empty SEARCH fills an empty file" "local_pass" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)"
R="$WORK/r12dup"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply "$FIX_BLOCK"$'\nsecond thoughts…\n'"$FIX_BLOCK"
eq "a block repeated verbatim is applied once" "local_pass|status = FIXED" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)|$(cat "$R/impl.txt")"
R="$WORK/r12h"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply $'drafting inline:\n'"$WRONG_BLOCK"$'\n</think>\n\n'"$FIX_BLOCK"
eq "blocks drafted before an inline </think> are ignored — only the final answer applies" "local_pass|status = FIXED" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)|$(cat "$R/impl.txt")"
R="$WORK/r12i"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply "$FIX_BLOCK"$'\n</think>\nDone.'
eq "…but a </think> with no block after it does not discard the blocks before it" "local_pass" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)"

# ---------------------------------------------------------------- 5. lint gate + checks
echo "== lint and checks"
R="$WORK/r13"; mkrepo "$R" 13 "$(LDJSON '{"max_attempts": 1}')" "! grep -q TODO impl.txt"; : > "$FAKE/replies.jsonl"
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = FIXED # TODO\n>>>>>>> REPLACE'
eq "a lint failure that was green at baseline is lint_fail" "lint_fail" "$(start "$R" 13 >/dev/null; waitjob "$R" 13 | field attempts.0.outcome)"
R="$WORK/r14"; mkrepo "$R" 14 "$(LDJSON '{"max_attempts": 1}')" "false"; : > "$FAKE/replies.jsonl"
reply "$FIX_BLOCK"
eq "lint already red at baseline is ignored" "local_pass" "$(start "$R" 14 >/dev/null; waitjob "$R" 14 | field state)"
ld "$R" revert --issue 14 >/dev/null; ld "$R" ack --issue 14 >/dev/null
eq "a reverted pass never reads as local code in the tree" "False" "$(ld "$R" status --issue 14 --last | field local_code_in_tree)"
R="$WORK/r14b"; mkrepo "$R" 14 "$(LDJSON '{"max_attempts": 1, "test_cmd": "sh check_bg.sh {files}"}')"; : > "$FAKE/replies.jsonl"
reply "$FIX_BLOCK"
OUT="$(start "$R" 14 >/dev/null; waitjob "$R" 14)"
eq "a test command leaving a background child still passes" "local_pass" "$(echo "$OUT" | field state)"
"$PY" -c 'import sys; sys.exit(0 if float(sys.argv[1]) < 20 else 1)' "$(echo "$OUT" | field active_s)" \
  && ok "…without waiting on the child ($(echo "$OUT" | field active_s) s)" || bad "lingering child" "< 20 s" "$(echo "$OUT" | field active_s)"

# ---------------------------------------------------------------- 6. time budgets
echo "== timeouts"
R="$WORK/r15"; mkrepo "$R" 15 "$(LDJSON '{"max_attempts": 1, "attempt_timeout_min": 0.03, "total_timeout_min": 5}')"; : > "$FAKE/replies.jsonl"
reply "$FIX_BLOCK" stop 6
eq "a model call past attempt_timeout is attempt_timeout" "attempt_timeout" "$(start "$R" 15 >/dev/null; waitjob "$R" 15 | field attempts.0.outcome)"
R="$WORK/r16"; mkrepo "$R" 16 "$(LDJSON '{"max_attempts": 3, "attempt_timeout_min": 5, "total_timeout_min": 0.04}')"; : > "$FAKE/replies.jsonl"
reply "$FIX_BLOCK" stop 6
OUT="$(start "$R" 16 >/dev/null; waitjob "$R" 16)"
eq "active time past total_timeout → fallback total_timeout" "total_timeout" "$(echo "$OUT" | field reason)"
eq "…restored" "status = BROKEN" "$(cat "$R/impl.txt")"
sleep 6   # let the fake server finish the abandoned reply before the next case pops one

# ---------------------------------------------------------------- 7. the queue
echo "== queue"
R="$WORK/r20"; mkrepo "$R" 20 "$(LDJSON '{"total_timeout_min": 0.05}')"; : > "$FAKE/replies.jsonl"
reply "$FIX_BLOCK"
hold
start "$R" 20 >/dev/null
sleep 5
eq "while another ticket is ahead the job reports queued" "queued" "$(ld "$R" status --issue 20 | field state)"
release
OUT="$(waitjob "$R" 20)"
eq "queue wait past total_timeout is not counted — the job still passes" "local_pass" "$(echo "$OUT" | field state)"
W="$(echo "$OUT" | field queue_wait_s)"
"$PY" -c 'import sys; sys.exit(0 if float(sys.argv[1]) >= 3 else 1)' "$W" && ok "queue_wait_s recorded ($W s)" || bad "queue_wait_s" ">= 3" "$W"
"$PY" -c 'import sys; sys.exit(0 if float(sys.argv[1]) < 3 else 1)' "$(echo "$OUT" | field active_s)" \
  && ok "active_s excludes the wait" || bad "active_s" "< 3" "$(echo "$OUT" | field active_s)"

R="$WORK/r21"; mkrepo "$R" 21 "$(LDJSON)"
hold
eq "attended + busy queue → immediate queue_busy" "queue_busy" "$(start "$R" 21 --attended | field reason)"
release
grep -q '"reason": "queue_busy"' "$R/.claude/guild/memory/local-dev/runs.jsonl" && ok "queue_busy is logged" || bad "queue_busy logged" "runs.jsonl line" "missing"
ld "$R" ack --issue 21 >/dev/null; : > "$FAKE/replies.jsonl"; reply "$WRONG_BLOCK" stop 2
# attempt 2 edits the file as attempt 1 left it
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = STILL_BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
start "$R" 21 --attended >/dev/null; sleep 1
eq "an attended job holds its ticket for the whole job" "1" "$(ls "$GLD_LOCAL_DEV_QUEUE_DIR" | grep -c '\.ticket$')"
OUT="$(waitjob "$R" 21)"
eq "…so its second attempt never waits (passes on attempt 2)" "local_pass|2" "$(echo "$OUT" | field state)|$(echo "$OUT" | field attempt_count)"
eq "…and gives the ticket back at the end" "0" "$(ls "$GLD_LOCAL_DEV_QUEUE_DIR" | grep -c '\.ticket$')"

mkdir -p "$GLD_LOCAL_DEV_QUEUE_DIR"; printf '{}' > "$GLD_LOCAL_DEV_QUEUE_DIR/00000000000000000002-$$-dead00.ticket"
printf '{}' > "$GLD_LOCAL_DEV_QUEUE_DIR/00000000000000000003-1-half00.ticket.new"; touch -t 202001010000 "$GLD_LOCAL_DEV_QUEUE_DIR/00000000000000000003-1-half00.ticket.new"

R="$WORK/r22"; mkrepo "$R" 22 "$(LDJSON)"; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"
eq "an unlocked ticket whose pid is alive (reused) never wedges the queue" "local_pass" "$(start "$R" 22 >/dev/null; waitjob "$R" 22 | field state)"
eq "an abandoned half-made ticket is cleaned up" "0" "$(ls "$GLD_LOCAL_DEV_QUEUE_DIR" | grep -c '\.new$')"

RA="$WORK/r23"; mkrepo "$RA" 23 "$(LDJSON)"; RB="$WORK/r24"; mkrepo "$RB" 24 "$(LDJSON)"
: > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"; reply "$FIX_BLOCK"; : > "$FAKE/order"
hold
start "$RA" 23 >/dev/null; sleep 3; start "$RB" 24 >/dev/null; sleep 3
release
waitjob "$RA" 23 >/dev/null; waitjob "$RB" 24 >/dev/null
eq "first come, first served across jobs" "23 24" "$(tr '\n' ' ' < "$FAKE/order" | sed 's/ $//')"

# ---------------------------------------------------------------- 8. a dead worker
echo "== worker death"
R="$WORK/r30"; mkrepo "$R" 30 "$(LDJSON '{"attempt_timeout_min": 5, "total_timeout_min": 10}')"; : > "$FAKE/replies.jsonl"
reply "$FIX_BLOCK" stop 30
S="$(start "$R" 30)"
sleep 3
J="$(echo "$S" | field job_dir)"
WP="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["worker_pid"])' "$R/$J/job.json")"
printf 'half-written\n' > "$R/impl.txt"
kill -9 "$WP" 2>/dev/null; sleep 0.5
ld "$R" status --issue 30 >/dev/null & S1=$!; ld "$R" status --issue 30 >/dev/null & S2=$!; wait "$S1" "$S2"
OUT="$(waitjob "$R" 30 5)"
eq "a dead worker becomes fallback worker_died" "worker_died" "$(echo "$OUT" | field reason)"
eq "…and the implementation is restored" "status = BROKEN" "$(cat "$R/impl.txt")"
eq "two concurrent settlers write ONE record" "1" "$(grep -c worker_died "$R/.claude/guild/memory/local-dev/runs.jsonl")"

# ---------------------------------------------------------------- 9. report + usage
echo "== report"
REP="$(ld "$WORK/r11" report)"
eq "report counts the fallback" "1" "$(echo "$REP" | field final.fallback)"
eq "report counts attempt outcomes" "1" "$(echo "$REP" | field attempt_outcomes.output_cap)"
eq "report: pass at attempt 2" "1" "$(ld "$WORK/r21" report | field pass_at_attempt.2)"
ld "$WORK/r10" start --issue 1 >/dev/null 2>&1; eq "usage error → exit 64" "64" "$?"
mkdir -p "$WORK/nocfg" && git -C "$WORK/nocfg" init -q
ld "$WORK/nocfg" status --issue 1 >/dev/null 2>&1; eq "no Guild config → exit 65" "65" "$?"
R="$WORK/rcap1"; mkrepo "$R" 1 "$(LDJSON '{"max_output_tokens_retry": 4000}')"
ld "$R" status --issue 1 >/dev/null 2>&1; eq "a retry cap below max_output_tokens → exit 65" "65" "$?"
R="$WORK/rcap2"; mkrepo "$R" 1 "$(LDJSON '{"max_output_tokens_retry": 60000}')"
ld "$R" status --issue 1 >/dev/null 2>&1; eq "a retry cap leaving no room for the prompt in num_ctx → exit 65" "65" "$?"

echo
echo "local_dev: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
