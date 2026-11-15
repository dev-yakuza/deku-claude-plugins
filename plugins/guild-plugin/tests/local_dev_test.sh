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
        if self.path == "/api/show":
            cp = os.path.join(D, "caps")
            caps = open(cp).read().split() if os.path.exists(cp) else ["completion", "tools"]
            return self._send({"capabilities": caps} if caps != ["none"] else {})
        user = req["messages"][-1]["content"]
        firsts = [m.get("content") or "" for m in req["messages"] if "Issue #" in (m.get("content") or "")]
        issue = firsts[0].split("Issue #", 1)[1].split(" ", 1)[0] if firsts else "?"
        with LOCK:
            open(os.path.join(D, "order"), "a").write(issue + "\n")
            open(os.path.join(D, "last_options.json"), "w").write(json.dumps(req.get("options")))
            open(os.path.join(D, "last_prompt.txt"), "w").write(user)
            open(os.path.join(D, "last_think.json"), "w").write(json.dumps(req.get("think")))
            open(os.path.join(D, "last_request.json"), "w").write(json.dumps(req))
            qd = os.environ.get("GLD_LOCAL_DEV_QUEUE_DIR", "")
            n = len([f for f in os.listdir(qd) if f.endswith(".ticket")]) if os.path.isdir(qd) else 0
            open(os.path.join(D, "tickets_at_call"), "a").write(f"{n}\n")
            names = sorted(f for f in os.listdir(qd) if f.endswith(".ticket")) if os.path.isdir(qd) else []
            open(os.path.join(D, "ticket_names"), "a").write(",".join(names) + "\n")
        r = pop()
        time.sleep(r.get("sleep", 0))
        msg = {"role": "assistant", "content": r["content"], "thinking": r.get("thinking", "hmm")}
        if r.get("tool_calls"):
            msg["tool_calls"] = r["tool_calls"]
        self._send({"message": msg,
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
R="$WORK/r5"; mkrepo "$R" 5 "$(LDJSON '{"num_ctx": 7500, "max_output_tokens": 1000}')"
eq "a prompt over the context budget → ineligible" "ineligible:context_too_large" "$(start "$R" 5 | field reason)"
R="$WORK/r5b"; mkrepo "$R" 7 "$(LDJSON '{"num_ctx": 14000, "max_output_tokens": 1000}')"
"$PY" -c 'import sys; open(sys.argv[1],"a").write("설계 " * 4000)' "$R/docs/specs/7/skeleton.md"; git -C "$R" commit -qam big
eq "CJK text is counted near 1 token/char — 12k chars of Korean overflow a 6k prompt budget" "ineligible:context_too_large" "$(start "$R" 7 | field reason)"
R="$WORK/r5c"; mkrepo "$R" 7 "$(LDJSON '{"num_ctx": 14000, "max_output_tokens": 1000}')"
"$PY" -c 'import sys; open(sys.argv[1],"a").write("plan " * 2400)' "$R/docs/specs/7/skeleton.md"; git -C "$R" commit -qam big
eq "…while 12k chars of ASCII fit it" "queued" "$(start "$R" 7 | field state)"; waitjob "$R" 7 >/dev/null; ld "$R" ack --issue 7 >/dev/null
R="$WORK/r4c"; mkrepo "$R" 4 "$(LDJSON)"; printf '  \n' > "$R/docs/specs/4/skeleton.md"; git -C "$R" commit -qam empty
eq "an empty skeleton → ineligible:no_skeleton" "ineligible:no_skeleton" "$(start "$R" 4 | field reason)"
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
R="$WORK/r10u"; mkrepo "$R" 19 "$(LDJSON)"; printf 'v3 — unstaged\n' >> "$R/test/impl_test.txt"
eq "a test with unstaged edits → ineligible:tests_unstaged (the leader commits the index)" "ineligible:tests_unstaged:test/impl_test.txt" "$(start "$R" 19 | field reason)"
R="$WORK/r10m"; mkrepo "$R" 19 "$(LDJSON)"; chmod +x "$R/test/impl_test.txt"
case "$(start "$R" 19 | field reason)" in *tests_unstaged*) bad "a file-mode change alone" "eligible" "tests_unstaged";; *) ok "a file-mode change alone is not an unstaged test edit";; esac
waitjob "$R" 19 >/dev/null; ld "$R" ack --issue 19 >/dev/null

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
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN' length; reply "$FIX_BLOCK" stop 1
OUT="$(start "$R" 18 >/dev/null; waitjob "$R" 18)"
eq "output_cap → the next attempt runs at max_output_tokens_retry and passes" "8000 16000 local_pass" \
  "$(echo "$OUT" | field attempts.0.num_predict) $(echo "$OUT" | field attempts.1.num_predict) $(echo "$OUT" | field state)"
eq "…the raised cap reached the model" "16000" "$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["num_predict"])' "$FAKE/last_options.json")"
REP="$(ld "$R" report)"
eq "report counts how raised-cap attempts ended" "1" "$(echo "$REP" | field raised_cap_outcomes.pass)"
case "$(echo "$REP" | field warnings.0)" in *"over attempt_timeout_min"*) ok "report warns when the retry cap cannot be generated in attempt_timeout_min";;
  *) bad "retry-cap time warning" "a warning" "$(echo "$REP" | field warnings)";; esac
eq "an attempt cut off mid-block keeps reasoning on (it was already writing edits)" "None" "$(echo "$OUT" | field attempts.1.think)"

# cut off while still reasoning, no edit written: the next attempt gets the reasoning's tail, reasoning off
R="$WORK/r11d"; mkrepo "$R" 17 "$(LDJSON)"; : > "$FAKE/replies.jsonl"
reply_cut "$("$PY" -c 'print("x" * 20000 + " PLAN-TAIL: replace BROKEN with FIXED")')"; reply "$FIX_BLOCK"
OUT="$(start "$R" 17 >/dev/null; waitjob "$R" 17)"
eq "reasoning cut off → the next attempt runs with think false and passes" "None False local_pass" \
  "$(echo "$OUT" | field attempts.0.think) $(echo "$OUT" | field attempts.1.think) $(echo "$OUT" | field state)"
eq "…think: false reached the model" "false" "$(cat "$FAKE/last_think.json")"
grep -q "PLAN-TAIL: replace BROKEN with FIXED" "$FAKE/last_prompt.txt" && grep -q "Your analysis from the attempt that hit the output limit" "$FAKE/last_prompt.txt" \
  && ok "…its prompt carries the cut-off reasoning's tail" || bad "carried reasoning" "tail in prompt" "missing"
eq "…only the last CARRY_CHARS of it" "True" "$("$PY" -c 'import re,sys; print(max(map(len, re.findall("x+", open(sys.argv[1]).read()))) < 12000)' "$FAKE/last_prompt.txt")"
# prose but no block before the cut is still "no edit written"; the test feedback of an earlier
# attempt rides along with the carry; a failed model call does not spend the carry
R="$WORK/r11f"; mkrepo "$R" 15 "$(LDJSON '{"max_attempts": 4}')"; : > "$FAKE/replies.jsonl"
reply "$WRONG_BLOCK"
"$PY" -c 'import json; print(json.dumps({"content": "Let me think about it", "thinking": "PLAN-TAIL2", "done_reason": "length"}))' >> "$FAKE/replies.jsonl"
"$PY" -c 'import json; print(json.dumps({"content": "x", "done_reason": "stop", "sleep": 40}))' >> "$FAKE/replies.jsonl"
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = STILL_BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
OUT="$(start "$R" 15 >/dev/null; waitjob "$R" 15 90)"
eq "prose without a block before the cut → reasoning off; a timed-out call keeps the carry" "test_fail output_cap attempt_timeout pass local_pass False" \
  "$(for k in 0 1 2 3; do echo "$OUT" | field attempts.$k.outcome; done | tr '\n' ' ')$(echo "$OUT" | field state) $(echo "$OUT" | field attempts.3.think)"
grep -q "PLAN-TAIL2" "$FAKE/last_prompt.txt" && grep -q "expected FIXED" "$FAKE/last_prompt.txt" \
  && ok "…the last prompt carries both the reasoning tail and the earlier test failure" || bad "carry + feedback" "both in prompt" "$(grep -c "PLAN-TAIL2\|expected FIXED" "$FAKE/last_prompt.txt")"
R="$WORK/r11g"; mkrepo "$R" 14 "$(LDJSON)"; : > "$FAKE/replies.jsonl"
reply "$WRONG_BLOCK"; "$PY" -c 'import json; print(json.dumps({"content": "still going", "thinking": "", "done_reason": "length"}))' >> "$FAKE/replies.jsonl"
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = STILL_BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
OUT="$(start "$R" 14 >/dev/null; waitjob "$R" 14)"
grep -q "expected FIXED" "$FAKE/last_prompt.txt" && grep -q "hit the output limit" "$FAKE/last_prompt.txt" \
  && ok "a cut-off without reasoning keeps the last test failure beside the output-limit note" || bad "test failure after a cut-off" "both" "$(tail -5 "$FAKE/last_prompt.txt")"
# earlier edits grow the files: the next attempt's cap shrinks to fit num_ctx, or the job falls back
GROW() { "$PY" -c 'import sys; print("impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = STILL_BROKEN\n# " + "y" * int(sys.argv[1]) + "\n>>>>>>> REPLACE")' "$1"; }
R="$WORK/rfit1"; mkrepo "$R" 13 "$(LDJSON '{"num_ctx": 12000, "max_output_tokens": 2000, "max_output_tokens_retry": 2000}')"; : > "$FAKE/replies.jsonl"
reply "$(GROW 30000)"; reply $'impl.txt\n<<<<<<< SEARCH\nstatus = STILL_BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
OUT="$(start "$R" 13 >/dev/null; waitjob "$R" 13)"
eq "a prompt grown by earlier edits gets a smaller cap, never past num_ctx" "local_pass True" \
  "$(echo "$OUT" | field state) $(echo "$OUT" | field attempts.1.num_predict | "$PY" -c 'import sys; v=int(sys.stdin.read()); print(1000 <= v < 2000)')"
R="$WORK/rfit2"; mkrepo "$R" 13 "$(LDJSON '{"num_ctx": 12000, "max_output_tokens": 2000, "max_output_tokens_retry": 2000}')"; : > "$FAKE/replies.jsonl"
reply "$(GROW 36000)"
eq "…and one that no longer fits falls back with context_overflow" "fallback context_overflow" "$(OUT="$(start "$R" 13 >/dev/null; waitjob "$R" 13)"; echo "$(echo "$OUT" | field state) $(echo "$OUT" | field reason)")"
# the carry is shortened before the cap when a grown prompt no longer fits
R="$WORK/rfit3"; mkrepo "$R" 13 "$(LDJSON '{"num_ctx": 16000, "max_output_tokens": 2000, "max_output_tokens_retry": 2000}')"; : > "$FAKE/replies.jsonl"
reply "$(GROW 36000)"; reply_cut "$("$PY" -c 'print("z" * 11000 + " CARRY-END")')"
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = STILL_BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
OUT="$(start "$R" 13 >/dev/null; waitjob "$R" 13)"
eq "a grown prompt with a carry: the carry shrinks, the cap stays" "local_pass 2000" "$(echo "$OUT" | field state) $(echo "$OUT" | field attempts.2.num_predict)"
grep -q "CARRY-END" "$FAKE/last_prompt.txt" && ok "…and the carry's tail is what remains" || bad "carry tail kept" "CARRY-END" "missing"
eq "…shortened below its eligibility length" "True" "$("$PY" -c 'import re,sys; print(max(map(len, re.findall("z+", open(sys.argv[1]).read()))) < 6000)' "$FAKE/last_prompt.txt")"
eq "a context_overflow fallback leaves an attempt record" "context_overflow" "$(ld "$WORK/rfit2" status --issue 13 --last | field attempts.1.outcome)"
# a check run that rewrites a test file (a snapshot, a formatter) is not a pass
R="$WORK/rtm"; mkrepo "$R" 9 "$(LDJSON '{"max_attempts": 1, "test_cmd": "sh -c \"echo touched >> test/impl_test.txt; sh check.sh\" {files}"}')"; : > "$FAKE/replies.jsonl"
reply "$FIX_BLOCK"
OUT="$(start "$R" 9 >/dev/null; waitjob "$R" 9)"
eq "a test file changed by a check run → fallback tests_modified" "fallback tests_modified" "$(echo "$OUT" | field state) $(echo "$OUT" | field reason)"
eq "…and the test is put back as it was at start" "" "$(git -C "$R" status --porcelain -- test)"
grep -q touched "$R/$(echo "$OUT" | field job_dir)/tests-changed/test/impl_test.txt" 2>/dev/null && ok "…what changed it is kept in the job folder" || bad "changed test kept" "tests-changed/ copy" "missing"
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
R="$WORK/r12j"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = HALF\n</think>\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nstatus = HALF\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
eq "a </think> line inside a block body is code, not a cut" "local_pass|status = FIXED </think>" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)|$(tr '\n' ' ' < "$R/impl.txt" | sed 's/ $//')"

R="$WORK/r12k"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = WRONG\nhmm, no\n</think>\n'"$FIX_BLOCK"
eq "a draft block left unclosed before </think> is dropped, not applied up to the next REPLACE" "local_pass|status = FIXED" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)|$(cat "$R/impl.txt")"
R="$WORK/r12l"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply "$WRONG_BLOCK"$'\nno, that is wrong.</think>\n'"$FIX_BLOCK"
eq "a </think> glued to the end of a prose line still cuts" "local_pass|status = FIXED" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)|$(cat "$R/impl.txt")"
R="$WORK/r12m"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply $'I will write a\n<<<<<<< SEARCH\nblock now.\n\n'"$FIX_BLOCK"
eq "a lone SEARCH line in prose before a real block → refused (ambiguous), nothing written" "fallback" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)"
R="$WORK/r12n"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
printf 'DOC = """\n<<<<<<< SEARCH\n"""\nstatus = BROKEN\n' > "$R/impl.txt"; git -C "$R" commit -qam doc
reply $'impl.txt\n<<<<<<< SEARCH\nDOC = """\n<<<<<<< SEARCH\n"""\nstatus = BROKEN\n=======\nDOC = """\n<<<<<<< SEARCH\n"""\nstatus = FIXED\n>>>>>>> REPLACE'
eq "a block whose body holds a SEARCH line (a file documenting the format) still applies" "local_pass" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)"
# an unclosed draft for an allowed file, rewritten without a </think> between: the draft goes
R="$WORK/r12o"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = WRONG\n'"$FIX_BLOCK"
eq "an unclosed draft with its divider, then the real block → refused, the file untouched" "fallback|status = BROKEN" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)|$(cat "$R/impl.txt")"
R="$WORK/r12p"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n'"$FIX_BLOCK"
eq "…a draft cut before its divider too" "fallback|status = BROKEN" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)|$(cat "$R/impl.txt")"
R="$WORK/r12q"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
printf 'a = 1\nstatus = BROKEN\n' > "$R/impl.txt"; git -C "$R" commit -qam two
reply $'impl.txt\n<<<<<<< SEARCH\na = 1\n=======\na = 2\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = WRONG\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
eq "…an unnamed second block's draft is refused, never applied with its markers (no path is handed on)" "fallback|a = 1 status = BROKEN" "$(start "$R" 12 >/dev/null; waitjob "$R" 12 | field state)|$(tr '\n' ' ' < "$R/impl.txt" | sed 's/ $//')"
eq "drop_tokens removes the shortest head worth n estimated tokens (ASCII and CJK)" "True True True" "$("$PY" -c '
import importlib.util,sys
sp=importlib.util.spec_from_file_location("ld",sys.argv[1]); m=importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
a=all(len(m.drop_tokens("x"*(3*n+10), n))==10 for n in range(1,500))
c=len(m.drop_tokens("설"*50, 10))==40
e=all(m.estimate_tokens(t)-m.estimate_tokens(m.drop_tokens(t,7))>=7 for t in ["ab설cd"*20,"설계 plan "*30])
print(a,c,e)' "$LD")"
R="$WORK/r12r"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
printf 'DOC = """\n<<<<<<< SEARCH\n"""\nstatus = BROKEN\n' > "$R/impl.txt"; git -C "$R" commit -qam doc
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n\nother.txt\n<<<<<<< SEARCH\nkeep me\n=======\nchanged\n>>>>>>> REPLACE\nimpl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
eq "a draft in a file that documents the format, then a block for another file → refused, neither file written" "fallback|keep me" \
  "$(ld "$R" start --issue 12 --base main --files impl.txt other.txt --tests test/impl_test.txt >/dev/null; waitjob "$R" 12 | field state)|$(cat "$R/other.txt")"
R="$WORK/r12s"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
printf 'Example:\nother.txt\n<<<<<<< SEARCH\nkeep me\n=======\nx\nstatus = BROKEN\n' > "$R/impl.txt"; git -C "$R" commit -qam doc
reply $'impl.txt\n<<<<<<< SEARCH\nExample:\nother.txt\n<<<<<<< SEARCH\nkeep me\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
eq "a doc quoting another allowed file's block is edited as the doc — the content decides, the other file is untouched" "local_pass|keep me" \
  "$(ld "$R" start --issue 12 --base main --files impl.txt other.txt --tests test/impl_test.txt >/dev/null; waitjob "$R" 12 | field state)|$(cat "$R/other.txt")"
R="$WORK/r12t"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
printf 'DOC = """\n<<<<<<< SEARCH\n"""\nstatus = BROKEN\n' > "$R/impl.txt"; git -C "$R" commit -qam doc
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = WRONG\n\nother.txt\n<<<<<<< SEARCH\nkeep me\n=======\nchanged\n>>>>>>> REPLACE\nimpl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
eq "a draft with a divider in a file that documents the format never takes the next block as its REPLACE" "fallback|keep me|0" \
  "$(ld "$R" start --issue 12 --base main --files impl.txt other.txt --tests test/impl_test.txt >/dev/null; waitjob "$R" 12 | field state)|$(cat "$R/other.txt")|$(grep -c 'other.txt' "$R/impl.txt")"
R="$WORK/r12u"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
printf 'FIX = """\nother.txt\n<<<<<<< SEARCH\nkeep me\n=======\nchanged\n>>>>>>> REPLACE\n"""\nstatus = BROKEN\n' > "$R/impl.txt"; git -C "$R" commit -qam doc
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nFIX2 = """\nother.txt\n<<<<<<< SEARCH\nkeep me\n=======\nchanged\n"""\nstatus = FIXED\n>>>>>>> REPLACE'
OUT="$(ld "$R" start --issue 12 --base main --files impl.txt other.txt --tests test/impl_test.txt >/dev/null; waitjob "$R" 12)"
eq "a marker written into the REPLACE text is refused — never applied to another file" "fallback|keep me" "$(echo "$OUT" | field state)|$(cat "$R/other.txt")"
R="$WORK/r12v"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
reply $'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n'"$FIX_BLOCK"
OUT="$(start "$R" 12 >/dev/null; waitjob "$R" 12)"
grep -q "Write each block once" "$R/$(echo "$OUT" | field job_dir)/job.json" && ok "a refused draft tells the model to write each block once, complete" || bad "nested-SEARCH feedback" "message" "missing"
R="$WORK/r12w"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
printf 'Example:\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\nstatus = BROKEN\n' > "$R/impl.txt"; git -C "$R" commit -qam doc
reply $'impl.txt\n<<<<<<< SEARCH\nExample:\n<<<<<<< SEARCH\nold\n=======\nExample:\n<<<<<<< SEARCH\nnewer\n\nother.txt\n<<<<<<< SEARCH\nkeep me\n=======\nchanged\n>>>>>>> REPLACE'
eq "a block for a file that documents the format, missing its REPLACE, never takes the next block in" "fallback|keep me|0" \
  "$(ld "$R" start --issue 12 --base main --files impl.txt other.txt --tests test/impl_test.txt >/dev/null; waitjob "$R" 12 | field state)|$(cat "$R/other.txt")|$(grep -c 'other.txt' "$R/impl.txt")"
R="$WORK/r12x"; mkrepo "$R" 12 "$(LDJSON '{"max_attempts": 1}')"; : > "$FAKE/replies.jsonl"
printf 'status = BROKEN\nq = 0\n' > "$R/impl.txt"; printf 'keep me\nq = 0\n' > "$R/other.txt"; git -C "$R" commit -qam two
A=$'impl.txt\n<<<<<<< SEARCH\nstatus = BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE\n'; B=$'other.txt\n<<<<<<< SEARCH\nkeep me\n=======\nchanged\n>>>>>>> REPLACE\n'
reply "$A$B$A"$'<<<<<<< SEARCH\nq = 0\n=======\nq = 9\n>>>>>>> REPLACE'
eq "an unnamed block after a removed duplicate belongs to the duplicate's file" "local_pass|q = 9|q = 0" \
  "$(ld "$R" start --issue 12 --base main --files impl.txt other.txt --tests test/impl_test.txt >/dev/null; waitjob "$R" 12 | field state)|$(tail -1 "$R/impl.txt")|$(tail -1 "$R/other.txt")"
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

# ---------------------------------------------------------------- 8b. the developer persona
echo "== persona"
# persona <repo> [extra] — a developer persona: template part (above the end marker) and the
# repo-grown part below it, optionally padded with [extra]
persona() {
  mkdir -p "$1/.claude/agents"
  "$PY" - "$1/.claude/agents/developer.md" "${2:-}" <<'PY2'
import sys
open(sys.argv[1], "w").write("---\nname: developer\n---\n# Developer\n<!-- guild:persona:start -->\n"
  "TEMPLATE-ONLY return >>> RESULT <<<\n<!-- guild:persona:end -->\n\n## Project specifics\n"
  "- PROJECT-RULE import order dart: first\n\n## Habits\n<!-- guild:persona:habits -->\n"
  "- HABIT-LESSON check every guard\n" + sys.argv[2])
PY2
}
lastrun() { "$PY" -c 'import json,sys; r=[json.loads(l) for l in open(sys.argv[1]) if "\"run\"" in l][-1]; v=r
for k in sys.argv[2].split("."): v=v[int(k)] if isinstance(v,list) else v.get(k)
print(v)' "$1/.claude/guild/memory/local-dev/runs.jsonl" "$2"; }
R="$WORK/rp1"; mkrepo "$R" 21 "$(LDJSON)"; persona "$R"; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK" stop 2
start "$R" 21 >/dev/null
printf -- '- EDITED-MID-JOB\n' >> "$R/.claude/agents/developer.md"
OUT="$(waitjob "$R" 21)"
grep -q "PROJECT-RULE" "$FAKE/last_prompt.txt" && grep -q "HABIT-LESSON" "$FAKE/last_prompt.txt" \
  && ok "the persona's repo-grown part reaches the model" || bad "persona in prompt" "PROJECT-RULE + HABIT-LESSON" "missing"
grep -q "TEMPLATE-ONLY\|guild:persona" "$FAKE/last_prompt.txt" \
  && bad "template part left out" "absent" "present" || ok "…its template part and markers do not"
grep -q "EDITED-MID-JOB" "$FAKE/last_prompt.txt" \
  && bad "persona snapshot" "start-time copy" "edited copy" || ok "…as it was at start (an evolve run mid-job changes nothing)"
eq "runs.jsonl records the persona as used, and per attempt" "local_pass used True" \
  "$(echo "$OUT" | field state) $(lastrun "$R" persona) $(lastrun "$R" attempts.0.persona)"
R="$WORK/rp2"; mkrepo "$R" 22 "$(LDJSON '{"persona": false}')"; persona "$R"; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"
start "$R" 22 >/dev/null; waitjob "$R" 22 >/dev/null
grep -q "PROJECT-RULE" "$FAKE/last_prompt.txt" && bad "persona off" "absent" "present" || ok "persona: false keeps it out"
eq "…recorded as off" "off" "$(lastrun "$R" persona)"
R="$WORK/rp3"; mkrepo "$R" 23 "$(LDJSON)"; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"
start "$R" 23 >/dev/null
eq "no persona file → the job runs without it (missing)" "local_pass missing" "$(echo "$(waitjob "$R" 23 | field state) $(lastrun "$R" persona)")"
R="$WORK/rp4"; mkrepo "$R" 24 "$(LDJSON)"; persona "$R"; sed -i.bak '/persona:end/d' "$R/.claude/agents/developer.md"; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"
start "$R" 24 >/dev/null
eq "a persona without its end marker is left out (no_marker)" "local_pass no_marker" "$(echo "$(waitjob "$R" 24 | field state) $(lastrun "$R" persona)")"
R="$WORK/rp5"; mkrepo "$R" 25 "$(LDJSON)"; persona "$R" "$("$PY" -c 'print("- long habit\n" * 700)')"; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"
start "$R" 25 >/dev/null; waitjob "$R" 25 >/dev/null
eq "a repo-grown part over 8000 chars is left out whole, never cut (too_long)" "too_long" "$(lastrun "$R" persona)"
grep -q "HABIT-LESSON" "$FAKE/last_prompt.txt" && bad "too_long persona" "absent" "present" || ok "…and none of it is sent"
R="$WORK/rp6"; mkrepo "$R" 26 "$(LDJSON '{"num_ctx": 14000, "max_output_tokens": 1000}')"; persona "$R" "$("$PY" -c 'print("설" * 5800)')"; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"
eq "a persona that would push the job out of num_ctx is dropped, the job still runs (no_room)" "queued" "$(start "$R" 26 | field state)"
waitjob "$R" 26 >/dev/null
eq "…recorded as no_room" "no_room" "$(lastrun "$R" persona)"
# earlier edits grow the files: the persona goes before the cap shrinks, for the rest of the job
R="$WORK/rp7"; mkrepo "$R" 27 "$(LDJSON '{"num_ctx": 12000, "max_output_tokens": 2000, "max_output_tokens_retry": 2000}')"
persona "$R" "$("$PY" -c 'print("p" * 6000)')"; : > "$FAKE/replies.jsonl"
reply "$(GROW 30000)"; reply $'impl.txt\n<<<<<<< SEARCH\nstatus = STILL_BROKEN\n=======\nstatus = FIXED\n>>>>>>> REPLACE'
OUT="$(start "$R" 27 >/dev/null; waitjob "$R" 27)"
eq "a grown prompt drops the persona first: attempt 1 with it, attempt 2 without" "local_pass True False dropped" \
  "$(echo "$OUT" | field state) $(lastrun "$R" attempts.0.persona) $(lastrun "$R" attempts.1.persona) $(lastrun "$R" persona)"
grep -q "HABIT-LESSON" "$FAKE/last_prompt.txt" && bad "dropped persona" "absent" "present" || ok "…and the second prompt carries none of it"
R="$WORK/rp8"; mkrepo "$R" 28 "$(LDJSON '{"persona": "yes"}')"
start "$R" 28 >/dev/null 2>&1; eq "persona must be a boolean → exit 65" "65" "$?"
: > "$FAKE/replies.jsonl"

# ---------------------------------------------------------------- 8c. lessons for evolve
echo "== lessons"
R="$WORK/rl"; mkrepo "$R" 31 "$(LDJSON)"; mkdir -p "$R/.claude/guild/memory/local-dev"
"$PY" - "$R/.claude/guild/memory/local-dev/runs.jsonl" <<'PY2'
import json, sys
def run(issue, ts, final, attempts, reason=None):
    return {"type": "run", "ts": ts, "issue": issue, "final": final, "reason": reason, "attempts": attempts}
L1 = "  error • The getter 'fooBar' isn't defined for the type 'Sync' • lib/a/sync.dart:120:7 • undefined_getter\n2 issues found.\n[exit 1]"
L2 = "  error • The getter 'other' isn't defined for the type 'Iap' • lib/b/iap.dart:9:3 • undefined_getter\n  warning • Unused import: 'x.dart' • lib/b/iap.dart:1:8 • unused_import"
rows = [
    run(1, "2026-11-01T00:00:00+09:00", "local_pass", [{"outcome": "lint_fail", "error": L1}, {"outcome": "pass"}]),
    run(2, "2026-11-02T00:00:00+09:00", "fallback", [{"outcome": "lint_fail", "error": L2},
        {"outcome": "apply_fail", "error": "SEARCH matched 0 times in lib/b/iap.dart:\n  x"},
        {"outcome": "output_cap"}], "max_attempts"),
    run(3, "2026-11-03T00:00:00+09:00", "fallback", [], "ineligible:context_too_large"),
    {"type": "followup", "ts": "2026-11-04T00:00:00+09:00", "issue": 1, "job_id": "j1", "job_final": "local_pass", "event": "loopback-review: null check missing"},
    {"type": "followup", "ts": "2026-11-04T00:00:00+09:00", "issue": 2, "job_id": "j2", "job_final": "fallback", "event": "loopback-test: x"},
]
open(sys.argv[1], "w").write("".join(json.dumps(r) + "\n" for r in rows))
PY2
OUT="$(ld "$R" lessons)"
eq "the same diagnostic in two Issues (different names, places) is one recurring key" "1 [1, 2]" \
  "$(echo "$OUT" | "$PY" -c 'import json,sys; d=json.loads(sys.stdin.read().split(">>> LOCAL-DEV <<<\n")[-1]); r=d["recurring_diagnostics"]; print(len(r), r[0]["issues"])')"
eq "…a diagnostic seen in one Issue only is not offered" "False" \
  "$(echo "$OUT" | "$PY" -c 'import json,sys; d=json.loads(sys.stdin.read().split(">>> LOCAL-DEV <<<\n")[-1]); print(any("unused_import" in r["key"] for r in d["recurring_diagnostics"]))')"
eq "…nor a runner's summary line" "False" \
  "$(echo "$OUT" | "$PY" -c 'import json,sys; d=json.loads(sys.stdin.read().split(">>> LOCAL-DEV <<<\n")[-1]); print(any("found" in r["key"] for r in d["recurring_diagnostics"]))')"
eq "a local pass sent back later is a lesson; a fallback's follow-up is not" "[1]" \
  "$(echo "$OUT" | "$PY" -c 'import json,sys; d=json.loads(sys.stdin.read().split(">>> LOCAL-DEV <<<\n")[-1]); print([r["issue"] for r in d["rejected_passes"]])')"
eq "how the model failed to answer is friction, never a lesson" "1 1 1" \
  "$(echo "$OUT" | "$PY" -c 'import json,sys; f=json.loads(sys.stdin.read().split(">>> LOCAL-DEV <<<\n")[-1])["friction"]; print(f.get("apply_fail:SEARCH matched N times"), f.get("output_cap"), f.get("ineligible:context_too_large"))')"
eq "--since leaves older runs out" "0 []" \
  "$(ld "$R" lessons --since 2026-11-02T12:00:00 | "$PY" -c 'import json,sys; d=json.loads(sys.stdin.read().split(">>> LOCAL-DEV <<<\n")[-1]); print(len(d["recurring_diagnostics"]), [r["issue"] for r in d["rejected_passes"]][:0])')"
eq "no runs.jsonl → an empty lesson set, exit 0" "0 0" \
  "$(R2="$WORK/rl2"; mkrepo "$R2" 32 "$(LDJSON)"; ld "$R2" lessons | field runs) $?"

# ---------------------------------------------------------------- 8d. agent mode
echo "== agent mode"
# tcall NAME ARGS_JSON [NAME ARGS_JSON ...] — one reply with tool calls through the API
tcall() { "$PY" -c 'import json,sys; a=sys.argv[1:]; print(json.dumps({"content": "", "tool_calls": [{"function": {"name": a[i], "arguments": json.loads(a[i+1])}} for i in range(0, len(a), 2)]}))' "$@" >> "$FAKE/replies.jsonl"; }
treply() { "$PY" -c 'import json,sys; d={"content": sys.argv[1], "done_reason": sys.argv[2]}; d.update({"thinking": sys.argv[3]} if len(sys.argv)>3 else {}); print(json.dumps(d))' "$@" >> "$FAKE/replies.jsonl"; }
AG='{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000}'
EDIT_OK='{"path": "impl.txt", "search": "status = BROKEN", "replace": "status = FIXED"}'
tool_results() { "$PY" -c 'import json,sys; m=json.load(open(sys.argv[1]))["messages"]; print("\n=====\n".join(x["content"] for x in m if x["role"]=="tool"))' "$FAKE/last_request.json"; }
transcript_tools() { "$PY" -c 'import json,sys; print("\n=====\n".join(json.loads(l)["content"] for l in open(sys.argv[1]) if json.loads(l)["role"]=="tool"))' "$1/$(ld "$1" status --issue "$2" --last | field job_dir)/transcript.jsonl"; }

R="$WORK/ra1"; mkrepo "$R" 41 "$(LDJSON "$AG")"; : > "$FAKE/replies.jsonl"
tcall read_file '{"path": "impl.txt"}'; tcall edit_file "$EDIT_OK"; tcall run_tests '{}'
OUT="$(start "$R" 41 >/dev/null; waitjob "$R" 41)"
eq "agent: read → edit → run_tests green → local_pass" "local_pass agent status = FIXED" "$(echo "$OUT" | field state) $(echo "$OUT" | field mode) $(cat "$R/impl.txt")"
eq "…every request carries the tools and keep_alive, reasoning off by default" "5 30m False" \
  "$("$PY" -c 'import json,sys; r=json.load(open(sys.argv[1])); print(len(r["tools"]), r["keep_alive"], r["think"])' "$FAKE/last_request.json")"
eq "…runs.jsonl: mode agent, three turns, one final check" "agent 3 pass False" "$(lastrun "$R" mode) $(lastrun "$R" turns | "$PY" -c 'import ast,sys; print(len(ast.literal_eval(sys.stdin.read())))') $(lastrun "$R" attempts.0.outcome) $(lastrun "$R" attempts.0.intermediate)"
grep -q "status = BROKEN" "$R/$(echo "$OUT" | field job_dir)/transcript.jsonl" && ok "…the transcript keeps what the model read" || bad "transcript" "read result" "missing"
eq "a oneshot request sends no keep_alive (oneshot unchanged)" "None" \
  "$(R2="$WORK/ra1b"; mkrepo "$R2" 42 "$(LDJSON)"; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"; start "$R2" 42 >/dev/null; waitjob "$R2" 42 >/dev/null; "$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("keep_alive"))' "$FAKE/last_request.json")"

# what the tools refuse
R="$WORK/ra2"; mkrepo "$R" 43 "$(LDJSON "$AG")"; : > "$FAKE/replies.jsonl"
printf 'secret\n' > "$R/untracked.txt"; mkdir -p "$R/.claude/guild/memory/x"; printf 'other job\n' > "$R/.claude/guild/memory/x/p.txt"
printf 'outside\n' > "$WORK/outside.txt"; ln -s "$WORK" "$R/linkdir"; ln -s .claude "$R/dotlink"
tcall edit_file '{"path": "other.txt", "search": "keep me", "replace": "changed"}' \
      edit_file '{"path": "test/impl_test.txt", "search": "v2", "replace": "v3"}' \
      read_file '{"path": "untracked.txt"}' read_file '{"path": ".claude/guild/memory/x/p.txt"}' \
      read_file '{"path": "../outside.txt"}' read_file '{"path": "linkdir/outside.txt"}' \
      read_file '{"path": "dotlink/guild/memory/x/p.txt"}' read_file '{"path": ".GIT/config"}'
tcall read_file '{"path": "test/impl_test.txt"}' read_file '{"path": ".CLAUDE/guild/memory/x/p.txt"}'
tcall search '{"pattern": "-Otouch pwned"}' search '{"pattern": "keep", "path": ":(exclude)impl.txt"}' search '{"pattern": "keep", "path": "."}'
tcall edit_file "$EDIT_OK" run_tests '{}'
OUT="$(start "$R" 43 >/dev/null; waitjob "$R" 43)"
T="$(transcript_tools "$R" 43)"
eq "agent: still passes after the refused calls" "local_pass" "$(echo "$OUT" | field state)"
eq "…a file outside --files and a test are not editable" "keep me|v2 — expects FIXED" "$(cat "$R/other.txt")|$(cat "$R/test/impl_test.txt")"
eq "…refusals: untracked, memory dir, ../, symlinked dir, symlink into .claude, .GIT and .CLAUDE case" "7" \
  "$(echo "$T" | grep -v "(exclude)" | grep -c "not a tracked file\|cannot be read\|outside the repository\|does not exist\|is a directory")"
echo "$T" | grep -q "secret\|other job\|^outside" && bad "no forbidden content read" "none" "leaked" || ok "…and none of their content reaches the model"
echo "$T" | grep -q "v2 — expects FIXED" && ok "…a test file can be read" || bad "test readable" "content" "missing"
[ -e "$R/pwned" ] || [ -e "$R/touch" ] && bad "search pattern as option" "no file" "created" || ok "search: a pattern starting with - is a pattern, not an option"
echo "$T" | grep -q "other.txt:1:keep me" && ok "…search over . finds tracked text" || bad "search ." "other.txt:1" "$(echo "$T" | grep -n keep | head -3)"
echo "$T" | grep -q "(exclude)" && ok "…a pathspec-magic path is taken literally (refused)" || bad "pathspec magic" "refused" "$(echo "$T" | sed -n '/exclude/p')"

# edit misses: 0 matches → nearest region; 2 matches → line numbers; near_line picks; CRLF kept
R="$WORK/ra3"; mkrepo "$R" 44 "$(LDJSON "$AG")"
"$PY" -c 'import sys; open(sys.argv[1],"w").write("status = BROKEN\n" + "pad\n"*30 + "dup line\n" + "pad\n"*30 + "dup line\n")' "$R/impl.txt"
git -C "$R" commit -qam dup; : > "$FAKE/replies.jsonl"
tcall edit_file '{"path": "impl.txt", "search": "status  =  BROKEN\nzzz", "replace": "x"}' \
      edit_file '{"path": "impl.txt", "search": "dup line", "replace": "one"}' \
      edit_file '{"path": "impl.txt", "search": "dup line", "replace": "picked", "near_line": 60}'
tcall edit_file "$EDIT_OK"; tcall run_tests '{}'
OUT="$(start "$R" 44 >/dev/null; waitjob "$R" 44)"
T="$(transcript_tools "$R" 44)"
echo "$T" | grep -q "closest place (line 1)" && ok "edit: 0 matches → the closest region's current text" || bad "nearest" "closest place" "$(echo "$T" | head -3)"
echo "$T" | grep -q "matches 2 times in impl.txt, starting at lines \[32, 63\]" && ok "…2 matches → their line numbers" || bad "two matches" "[32, 63]" "$(echo "$T" | grep matches)"
eq "…near_line far enough apart picks the nearest one" "1 picked" "$(grep -c '^dup line$' "$R/impl.txt") $(sed -n 63p "$R/impl.txt")"
eq "…misses are counted apart from checks" "2 1" "$(lastrun "$R" edit_misses) $(lastrun "$R" attempts | "$PY" -c 'import ast,sys; print(len(ast.literal_eval(sys.stdin.read())))')"
R="$WORK/ra4"; mkrepo "$R" 45 "$(LDJSON "$AG")"; printf 'status = BROKEN\r\nnext\r\n' > "$R/impl.txt"; git -C "$R" commit -qam crlf; : > "$FAKE/replies.jsonl"
tcall edit_file '{"path": "impl.txt", "search": "status = BROKEN\nnext", "replace": "status = FIXED\nnext"}' run_tests '{}'
start "$R" 45 >/dev/null; waitjob "$R" 45 >/dev/null
eq "edit keeps a CRLF file CRLF, no \\r\\r\\n" "status = FIXED\r\nnext\r\n" "$("$PY" -c 'import sys; print(repr(open(sys.argv[1],"rb").read().decode())[1:-1])' "$R/impl.txt")"

# text replies
R="$WORK/ra5"; mkrepo "$R" 46 "$(LDJSON "$AG")"; : > "$FAKE/replies.jsonl"
treply "I think I am done." stop
treply 'For example {"name": "edit_file", "arguments": {"path": "impl.txt", "search": "status = BROKEN", "replace": "status = FIXED"}} would work.' stop
treply '<think>maybe <tool_call>{"name": "run_tests", "arguments": {}}</tool_call></think>Now: <tool_call>{"name": "edit_file", "arguments": {"path": "impl.txt", "search": "status = BROKEN", "replace": "status = FIXED"}}</tool_call>' stop
treply "Done now." stop
OUT="$(start "$R" 46 >/dev/null; waitjob "$R" 46)"
eq "text: a call written as <tool_call> after the reasoning runs; a done-claim after an edit triggers the check" "local_pass 1 False" \
  "$(echo "$OUT" | field state) $(lastrun "$R" attempts | "$PY" -c 'import ast,sys; print(len(ast.literal_eval(sys.stdin.read())))') $(lastrun "$R" attempts.0.intermediate)"
eq "…a JSON example inside prose is not executed, and an unchanged done-claim runs no check" "None 1" \
  "$(lastrun "$R" turns.1.text_calls) $(lastrun "$R" turns.2.text_calls)"

# stuck, max_turns, length cut, timeouts
R="$WORK/ra6"; mkrepo "$R" 47 "$(LDJSON "$AG")"; : > "$FAKE/replies.jsonl"
for _ in 1 2 3 4 5 6 7; do tcall read_file '{"path": "impl.txt"}'; done
OUT="$(start "$R" 47 >/dev/null; waitjob "$R" 47)"
eq "the same read again and again → stuck after 6 turns without progress" "fallback stuck 7" "$(echo "$OUT" | field state) $(echo "$OUT" | field reason) $(lastrun "$R" turns | "$PY" -c 'import ast,sys; print(len(ast.literal_eval(sys.stdin.read())))')"
grep -q "unchanged — same as your read_file result at turn 1" "$R/$(echo "$OUT" | field job_dir)/transcript.jsonl" && ok "…a repeated read of an intact result is answered by reference" || bad "read dedupe" "reference" "missing"
R="$WORK/ra7"; mkrepo "$R" 48 "$(LDJSON '{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000, "max_turns": 2}')"; : > "$FAKE/replies.jsonl"
tcall edit_file '{"path": "impl.txt", "search": "status = BROKEN", "replace": "status = HALF"}'; tcall read_file '{"path": "impl.txt"}'
OUT="$(start "$R" 48 >/dev/null; waitjob "$R" 48)"
eq "max_turns → fallback, files restored, the model's diff kept" "fallback max_turns status = BROKEN" "$(echo "$OUT" | field state) $(echo "$OUT" | field reason) $(cat "$R/impl.txt")"
grep -q "status = HALF" "$R/$(ld "$R" status --issue 48 --last | field last_diff)" && ok "…last-local.diff has the half-done edit" || bad "last diff" "HALF" "missing"
R="$WORK/ra8"; mkrepo "$R" 49 "$(LDJSON '{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000, "agent_think": true}')"; : > "$FAKE/replies.jsonl"
treply "" length "PLAN-TAIL the fix is to set FIXED"; tcall edit_file "$EDIT_OK" run_tests '{}'
OUT="$(start "$R" 49 >/dev/null; waitjob "$R" 49)"
eq "a turn cut off while reasoning: its tail is carried, reasoning off after" "local_pass False" "$(echo "$OUT" | field state) $(cat "$FAKE/last_think.json" | "$PY" -c 'import json,sys; print(json.load(sys.stdin))')"
grep -q "PLAN-TAIL" "$FAKE/last_prompt.txt" "$FAKE/last_request.json" && ok "…and the carry reached the next request" || bad "carry" "PLAN-TAIL" "missing"
R="$WORK/ra9"; mkrepo "$R" 50 "$(LDJSON '{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000, "attempt_timeout_min": 0.02}')"; : > "$FAKE/replies.jsonl"
reply "slow" stop 3; reply "slow" stop 3
OUT="$(start "$R" 50 >/dev/null; waitjob "$R" 50 60)"
eq "two timed-out calls in a row → fallback attempt_timeout" "fallback attempt_timeout" "$(echo "$OUT" | field state) $(echo "$OUT" | field reason)"
sleep 4; : > "$FAKE/replies.jsonl"

# writes outside the editable set
R="$WORK/ra10"; mkrepo "$R" 51 "$(LDJSON '{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000, "test_cmd": "sh -c \"mktemp ./stray.XXXXXX >/dev/null; mkdir -p failures; mktemp failures/g.XXXXXX >/dev/null; sh check.sh\" {files}"}')"; : > "$FAKE/replies.jsonl"
tcall run_tests '{}'; tcall edit_file "$EDIT_OK" run_tests '{}'
OUT="$(start "$R" 51 >/dev/null; waitjob "$R" 51)"
eq "a check's new untracked files are moved into the job folder; baseline artifacts may change — no fallback" "local_pass" "$(echo "$OUT" | field state)"
eq "…none left in the tree" "" "$(git -C "$R" status --porcelain -- . ':!.claude' | grep -v '^ M impl.txt' | grep -v '^M  impl.txt')"
[ -n "$(ls "$R/$(echo "$OUT" | field job_dir)/stray" 2>/dev/null)" ] && ok "…they are kept under stray/" || bad "stray kept" "files" "none"
eq "…a green check that lost a file is run again before it counts" "1" "$(lastrun "$R" rechecked)"
eq "…and the leader sees what was moved" "True" "$(echo "$OUT" | "$PY" -c 'import json,sys; d=json.loads(sys.stdin.read().split(">>> LOCAL-DEV <<<\n")[-1]); print(bool(d.get("stray")))')"
R="$WORK/ra11"; mkrepo "$R" 52 "$(LDJSON '{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000, "test_cmd": "sh -c \"grep -q FIXED impl.txt && echo hacked > other.txt; sh check.sh\" {files}"}')"; : > "$FAKE/replies.jsonl"
tcall edit_file "$EDIT_OK" run_tests '{}'
OUT="$(start "$R" 52 >/dev/null; waitjob "$R" 52)"
eq "a check that changes a tracked file → fallback out_of_scope_write, the file put back" "fallback out_of_scope_write keep me other.txt" \
  "$(echo "$OUT" | field state) $(echo "$OUT" | field reason) $(cat "$R/other.txt") $(echo "$OUT" | field out_of_scope.0)"
R="$WORK/ra12"; mkrepo "$R" 53 "$(LDJSON '{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000, "test_cmd": "sh -c \"date +%N >> other.txt; sh check.sh\" {files}"}')"; : > "$FAKE/replies.jsonl"
tcall edit_file "$EDIT_OK" run_tests '{}'
OUT="$(start "$R" 53 >/dev/null; waitjob "$R" 53)"
eq "a tracked file the runner changes every run (baseline too, like a lock file) — reference is after baseline" "fallback out_of_scope_write" "$(echo "$OUT" | field state) $(echo "$OUT" | field reason)"
R="$WORK/ra12b"; mkrepo "$R" 54 "$(LDJSON '{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000, "test_cmd": "sh -c \"echo lock > other.txt; sh check.sh\" {files}"}')"; : > "$FAKE/replies.jsonl"
tcall edit_file "$EDIT_OK" run_tests '{}'
eq "…one the baseline already changed the same way is not a fallback" "local_pass" "$(start "$R" 54 >/dev/null; waitjob "$R" 54 | field state)"

# the unattended ticket is let go while checks run
R="$WORK/ra13"; mkrepo "$R" 55 "$(LDJSON '{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000, "test_cmd": "sh -c \"ls \\\"$GLD_LOCAL_DEV_QUEUE_DIR\\\" | grep -c ticket >> tickets.log; sh check.sh\" {files}"}')"
printf 'tickets.log\n' >> "$R/.git/info/exclude"; : > "$FAKE/replies.jsonl"
tcall edit_file "$EDIT_OK" run_tests '{}'
start "$R" 55 >/dev/null; waitjob "$R" 55 >/dev/null
eq "unattended: no ticket is held while the checks run" "0" "$(sort -u "$R/tickets.log" | tr '\n' ' ' | xargs)"
: > "$FAKE/tickets_at_call"; : > "$FAKE/ticket_names"; R="$WORK/ra13b"; mkrepo "$R" 63 "$(LDJSON "$AG")"; : > "$FAKE/replies.jsonl"
tcall read_file '{"path": "impl.txt"}'; tcall edit_file "$EDIT_OK"; tcall run_tests '{}'
start "$R" 63 >/dev/null; waitjob "$R" 63 >/dev/null
eq "…and one is held during every model turn" "1" "$(sort -u "$FAKE/tickets_at_call" | tr '\n' ' ' | xargs)"
eq "…the same ticket across consecutive turns (not re-taken per call — the prefix cache)" "1" "$(sort -u "$FAKE/ticket_names" | grep -c .)"

# context: one batched elision, a re-read of an elided result gets the text again
R="$WORK/ra14"; mkrepo "$R" 56 "$(LDJSON '{"mode": "agent", "num_ctx": 40000, "max_output_tokens": 1000, "max_turns": 14}')"
"$PY" -c 'import sys; open(sys.argv[1],"w").write("status = BROKEN\n" + "".join(f"line {i} " + "x"*90 + "\n" for i in range(2,1300)))' "$R/impl.txt"
git -C "$R" commit -qam big; : > "$FAKE/replies.jsonl"
for s in 1 101 201 301 401 501 601 701 801 901 1001; do tcall read_file "{\"path\": \"impl.txt\", \"start_line\": $s, \"end_line\": $((s+99))}"; done
tcall read_file '{"path": "impl.txt", "start_line": 1, "end_line": 100}'; tcall edit_file "$EDIT_OK" run_tests '{}'
OUT="$(start "$R" 56 >/dev/null; waitjob "$R" 56)"
eq "agent: many reads in a small num_ctx still pass (old results elided)" "local_pass" "$(echo "$OUT" | field state)"
grep -q "elided to save context" "$FAKE/last_request.json" && ok "…old tool results were elided" || bad "elision" "marker" "none"
eq "…and a re-read of an elided result returns the text, not a reference" "True" \
  "$("$PY" -c 'import json,sys; t=[m["content"] for m in json.load(open(sys.argv[1]))["messages"] if m["role"]=="tool"]; print(any("     1| status = BROKEN" in x for x in t[-3:]))' "$FAKE/last_request.json")"
eq "…elision happened in one batch, not every turn" "1" "$(lastrun "$R" turns | "$PY" -c 'import ast,sys; print(sum(1 for t in ast.literal_eval(sys.stdin.read()) if t.get("elided")))')"

# eligibility and config
R="$WORK/ra15"; mkrepo "$R" 57 "$(LDJSON "$AG")"; echo "completion" > "$FAKE/caps"
eq "a model without tools → ineligible:model_no_tools" "ineligible:model_no_tools" "$(start "$R" 57 | field reason)"
echo "none" > "$FAKE/caps"; ld "$R" ack --issue 57 >/dev/null
eq "…also when Ollama lists no capabilities at all" "ineligible:model_no_tools" "$(start "$R" 57 | field reason)"
rm -f "$FAKE/caps"
R="$WORK/ra16"; mkrepo "$R" 58 "$(LDJSON '{"mode": "agent", "num_ctx": 20000, "max_output_tokens": 1000}')"
eq "agent with a num_ctx too small for its working room → ineligible:context_too_large (not a config error)" "ineligible:context_too_large" "$(start "$R" 58 | field reason)"
R="$WORK/ra17"; mkrepo "$R" 59 "$(LDJSON '{"mode": "auto", "num_ctx": 40000, "max_output_tokens": 1000}')"; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"
eq "auto: a job that fits one-shot runs one-shot" "oneshot" "$(start "$R" 59 | field mode)"; waitjob "$R" 59 >/dev/null
R="$WORK/ra18"; mkrepo "$R" 60 "$(LDJSON '{"mode": "auto", "num_ctx": 40000, "max_output_tokens": 1000}')"
"$PY" -c 'import sys; open(sys.argv[1],"w").write("status = BROKEN\n" + "y"*100000 + "\n")' "$R/impl.txt"; git -C "$R" commit -qam big; : > "$FAKE/replies.jsonl"
tcall edit_file "$EDIT_OK" run_tests '{}'
eq "auto: a file too big for one-shot runs as agent" "agent" "$(start "$R" 60 | field mode)"; waitjob "$R" 60 >/dev/null
for bad_cfg in '{"mode": "swarm"}' '{"max_turns": 0}' '{"agent_think": "no"}'; do
  R="$WORK/ra19"; rm -rf "$R"; mkrepo "$R" 61 "$(LDJSON "$bad_cfg")"; start "$R" 61 >/dev/null 2>&1
  eq "config $bad_cfg → exit 65" "65" "$?"
done

# more agent behaviour
R="$WORK/ra21"; mkrepo "$R" 64 "$(LDJSON "$AG")"; : > "$FAKE/empty.txt"; cp "$FAKE/empty.txt" "$R/empty.txt"; printf 'caf\xe9\n' > "$R/latin.txt"
git -C "$R" add empty.txt latin.txt; git -C "$R" commit -qm extra; : > "$FAKE/replies.jsonl"
tcall read_file '{"path": "empty.txt"}' read_file '{"path": "impl.txt", "start_line": "abc"}' search '{"pattern": "x", "context": "x"}' read_file '{"path": "impl.txt", "start_line": 1e400}'
"$PY" -c 'import json; print(json.dumps({"content": "", "tool_calls": [{"function": {"name": ["read_file"], "arguments": {}}}, {"function": {"name": "edit_file", "arguments": {"path": "impl.txt", "search": "status = BROKEN", "replace": "status = FIXED", "near_line": True}}}, "junk"]}))' >> "$FAKE/replies.jsonl"
tcall edit_file "$EDIT_OK" run_tests '{}'
OUT="$(start "$R" 64 >/dev/null; waitjob "$R" 64)"
T="$(transcript_tools "$R" 64)"
eq "bad arguments, an empty file, an odd tool name: error strings, the job goes on and passes" "local_pass" "$(echo "$OUT" | field state)"
echo "$T" | grep -q "empty.txt is empty (0 lines)" && ok "…an empty file reads as empty" || bad "empty read" "0 lines" "$(echo "$T" | head -2)"
eq "…each bad argument named back to the model" "5" "$(echo "$T" | grep -c "must be an integer\|unknown tool")"
echo "$T" | grep -q "edited impl.txt. Lines 1-1 now:" && echo "$T" | grep -q "     1| status = FIXED" && ok "…an applied edit returns the region with its line numbers" || bad "edit reply" "Lines 1-1 + numbered" "$(echo "$T" | grep -A2 edited)"
R="$WORK/ra22"; mkrepo "$R" 65 "$(LDJSON "$AG")"
"$PY" -c 'import sys; open(sys.argv[1],"w").write("status = BROKEN\n" + "dup line\n" + "pad\n"*5 + "dup line\n" + "a\nb\nc\n")' "$R/impl.txt"; git -C "$R" commit -qam dup2; : > "$FAKE/replies.jsonl"
tcall edit_file '{"path": "impl.txt", "search": "dup line", "replace": "z", "near_line": 2}' edit_file '{"path": "impl.txt", "search": "a\n", "replace": "A\n"}' edit_file '{"path": "impl.txt", "search": "b\n", "replace": "B\n"}' edit_file '{"path": "impl.txt", "search": "c\n", "replace": "C\n"}'
tcall edit_file "$EDIT_OK"; tcall run_tests '{}'
OUT="$(start "$R" 65 >/dev/null; waitjob "$R" 65)"
eq "near_line too close to the other match is not applied" "2" "$(grep -c '^dup line$' "$R/impl.txt")"
eq "three edits without run_tests → one automatic check, marked intermediate" "red True" \
  "$(lastrun "$R" attempts.0.outcome | sed 's/test_fail/red/') $(lastrun "$R" attempts.0.intermediate)"
R="$WORK/ra23"; mkrepo "$R" 67 "$(LDJSON '{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000, "max_turns": 3}')"
printf '#!/bin/sh\n[ -L impl.txt ] || { rm impl.txt; ln -s other.txt impl.txt; }\nexit 1\n' > "$WORK/linkit.sh"
J="$(printf '{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000, "max_turns": 2, "test_cmd": "sh %s {files}"}' "$WORK/linkit.sh")"
R="$WORK/ra23"; rm -rf "$R"; mkrepo "$R" 67 "$(LDJSON "$J")"; : > "$FAKE/replies.jsonl"
tcall edit_file "$EDIT_OK"; tcall edit_file "$EDIT_OK"
OUT="$(start "$R" 67 >/dev/null; waitjob "$R" 67)"
grep -q "not a plain file\|not editable" "$R/$(echo "$OUT" | field job_dir)/transcript.jsonl" && ok "edit_file refuses a --files path a check turned into a symlink" || bad "symlink edit" "refused" "$(tail -2 "$R/$(echo "$OUT" | field job_dir)/transcript.jsonl")"
eq "…the link target is untouched and the file is remade at fallback" "keep me regular status = BROKEN" "$(cat "$R/other.txt") $([ -L "$R/impl.txt" ] && echo link || echo regular) $(cat "$R/impl.txt")"
R="$WORK/ra24"; mkrepo "$R" 68 "$(LDJSON '{"mode": "agent", "num_ctx": 65536, "max_output_tokens": 2000, "agent_think": true, "attempt_timeout_min": 0.02}')"; : > "$FAKE/replies.jsonl"
reply "slow" stop 3; tcall edit_file "$EDIT_OK" run_tests '{}'
OUT="$(start "$R" 68 >/dev/null; waitjob "$R" 68 60)"
eq "one timed-out call: a shorter retry with reasoning off, then a pass" "local_pass False" "$(echo "$OUT" | field state) $("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["think"])' "$FAKE/last_request.json")"
grep -q "The previous call failed (attempt_timeout)" "$FAKE/last_request.json" && ok "…the retry says why" || bad "timeout note" "present" "missing"
sleep 3; : > "$FAKE/replies.jsonl"
AGENT_PY="$HERE/../skills/gld/commands/atoms"
eq "check signature ignores timings (jest ms, dart reporter clock)" "True True" "$("$PY" -c '
import sys; sys.path.insert(0, sys.argv[1]); import local_dev_agent as a
j1 = a.check_signature("test_fail", "  ✕ adds (3 ms)\n  ✕ subs (12 ms)")
j2 = a.check_signature("test_fail", "  ✕ adds (7 ms)\n  ✕ subs (1 ms)")
d1 = a.check_signature("test_fail", "00:03 +1 -1: x [E]\nSome tests failed.")
d2 = a.check_signature("test_fail", "01:09 +1 -1: x [E]\nSome tests failed.")
print(j1 == j2, d1 == d2)' "$AGENT_PY")"
eq "lessons ignore an agent's intermediate checks" "0" "$(R2="$WORK/rl3"; mkrepo "$R2" 69 "$(LDJSON)"; mkdir -p "$R2/.claude/guild/memory/local-dev"
  "$PY" -c 'import json,sys
L = "  error • The getter x isnt defined • lib/a.dart:1:1 • undefined_getter"
rows = [{"type": "run", "ts": "t", "issue": i, "final": "local_pass", "mode": "agent", "attempts": [{"outcome": "lint_fail", "error": L, "intermediate": True}, {"outcome": "pass", "intermediate": False}]} for i in (1, 2)]
open(sys.argv[1], "w").write("".join(json.dumps(r) + "\n" for r in rows))' "$R2/.claude/guild/memory/local-dev/runs.jsonl"
  ld "$R2" lessons | "$PY" -c 'import json,sys; print(len(json.loads(sys.stdin.read().split(">>> LOCAL-DEV <<<\n")[-1])["recurring_diagnostics"]))')"
eq "restore: a symlinked parent (even inside the repo) is not written through → restore_failed" "['lib/a.txt'] other-content" "$("$PY" -c '
import os, sys, tempfile; sys.path.insert(0, sys.argv[1]); import local_dev as ld
r = tempfile.mkdtemp(); jd = os.path.join(r, "job")
os.makedirs(os.path.join(jd, "originals", "lib")); open(os.path.join(jd, "originals", "lib", "a.txt"), "w").write("orig")
os.makedirs(os.path.join(r, "other")); open(os.path.join(r, "other", "a.txt"), "w").write("other-content")
os.symlink("other", os.path.join(r, "lib"))
print(ld.restore(r, jd, ["lib/a.txt"]), open(os.path.join(r, "other", "a.txt")).read())' "$AGENT_PY")"
eq "restore: a removed parent is made again; a directory in the file's place is restore_failed, not a crash" "['b.txt'] o" "$("$PY" -c '
import os, sys, tempfile; sys.path.insert(0, sys.argv[1]); import local_dev as ld
r = tempfile.mkdtemp(); jd = os.path.join(r, "job")
for f in ("x/a.txt", "b.txt"):
    os.makedirs(os.path.dirname(os.path.join(jd, "originals", f)), exist_ok=True); open(os.path.join(jd, "originals", f), "w").write("o")
os.makedirs(os.path.join(r, "b.txt"))
print(ld.restore(r, jd, ["x/a.txt", "b.txt"]), open(os.path.join(r, "x", "a.txt")).read())' "$AGENT_PY")"

R="$WORK/ra25"; mkrepo "$R" 70 "$(LDJSON "$AG")"; ln "$R/impl.txt" "$WORK/hardlink.txt"
eq "agent: a hardlinked --files entry is ineligible (its edits would reach the link)" "ineligible:file_hardlinked:impl.txt" "$(start "$R" 70 | field reason)"
R="$WORK/ra26"; mkrepo "$R" 71 "$(LDJSON "$AG")"; printf 'impl.txt\n' >> "$R/.gitignore"; git -C "$R" add .gitignore; git -C "$R" commit -qm ign; : > "$FAKE/replies.jsonl"
tcall read_file '{"path": "impl.txt"}' edit_file "$EDIT_OK" run_tests '{}'
eq "an ignore pattern over a tracked --files entry does not lock the model out of it" "local_pass" "$(start "$R" 71 >/dev/null; waitjob "$R" 71 | field state)"
eq "a dead agent worker's scope is settled by listing, never by putting files back" "changed-later ['other.txt']" "$("$PY" - "$AGENT_PY" <<'PY2'
import json, os, subprocess, sys, tempfile
sys.path.insert(0, sys.argv[1]); import local_dev as ld, local_dev_agent as ag
r = tempfile.mkdtemp(); g = lambda *a: subprocess.run(["git", "-C", r, *a], capture_output=True)
g("init", "-q"); open(os.path.join(r, "other.txt"), "w").write("keep\n"); open(os.path.join(r, "impl.txt"), "w").write("x\n")
g("add", "-A"); g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b")
jd = os.path.join(r, ".claude", "guild", "memory", "local-dev", "1", "j"); os.makedirs(jd)
job = {"files": ["impl.txt"], "tests": []}
sc = ag.Scope(ld, r, jd, job); sc.before_baseline(); sc.after_baseline()
open(os.path.join(r, "other.txt"), "w").write("changed-later\n")   # a human, after the worker died
ag.settle_scope(ld, r, jd, job)
print(open(os.path.join(r, "other.txt")).read().strip(), job.get("restore_failed"))
PY2
)"
eq "outline: typed and untyped methods in, calls and test DSL out" "class A|  int add(int a) {|    render() {|  const A({super.key});|const useX = () => {" "$("$PY" - "$AGENT_PY" <<'PY2'
import sys; sys.path.insert(0, sys.argv[1]); import local_dev_agent as ag
src = """class A {
  const A({super.key});
  int add(int a) {
    setState(() {
    });
    showDialog(
    return a;
  }
    render() {
  it('works', () => {
}
const useX = () => {
"""
got = [l for _, l in ag.outline_lines(src)]
want = ["class A {", "  int add(int a) {", "    render() {", "  const A({super.key});", "const useX = () => {"]
print("|".join(w.rstrip(" {") if w == "class A {" else w for w in want) if sorted(got) == sorted(want) else got)
PY2
)"

# a helper passed with the tests is protected but never handed to the runner
R="$WORK/rh1"; mkrepo "$R" 72 "$(LDJSON '{"test_cmd": "sh -c '"'"'echo \"$*\" >> ran.log; sh check.sh'"'"' x {files}"}')"
printf 'helper v1\n' > "$R/test/capture_helper.txt"; git -C "$R" add test/capture_helper.txt; git -C "$R" commit -qm helper
printf 'ran.log\n' >> "$R/.git/info/exclude"; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"
OUT="$(ld "$R" start --issue 72 --base main --files impl.txt --tests test/impl_test.txt test/capture_helper.txt >/dev/null; waitjob "$R" 72)"
eq "runner gets the test files only, not a helper passed with them" "local_pass 0" "$(echo "$OUT" | field state) $(grep -c capture_helper "$R/ran.log")"
grep -q "test/impl_test.txt" "$R/ran.log" && ok "…the real test is still run" || bad "test run" "impl_test" "$(cat "$R/ran.log")"
R="$WORK/rh2"; mkrepo "$R" 73 "$(LDJSON '{"test_file_patterns": "x"}')"
start "$R" 73 >/dev/null 2>&1; eq "test_file_patterns must be a list → exit 65" "65" "$?"

# restore never writes through a planted symlink (all modes)
printf 'precious\n' > "$WORK/precious.txt"
printf '#!/bin/sh\ngrep -q FIXED impl.txt && { rm impl.txt; ln -s "$1" impl.txt; }\nexit 1\n' > "$WORK/swap.sh"
J="$(printf '{"max_attempts": 1, "test_cmd": "sh %s %s {files}"}' "$WORK/swap.sh" "$WORK/precious.txt")"
R="$WORK/ra20"; mkrepo "$R" 62 "$(LDJSON "$J")"
chmod 755 "$R/impl.txt"; git -C "$R" commit -qam mode; : > "$FAKE/replies.jsonl"; reply "$FIX_BLOCK"
OUT="$(start "$R" 62 >/dev/null; waitjob "$R" 62)"
eq "a fallback after a check swapped a file for a symlink: link removed, file remade, target untouched" "fallback regular status = BROKEN precious" \
  "$(echo "$OUT" | field state) $([ -L "$R/impl.txt" ] && echo link || echo regular) $(cat "$R/impl.txt") $(cat "$WORK/precious.txt")"
eq "…with its mode kept" "755" "$(stat -f %Lp "$R/impl.txt" 2>/dev/null || stat -c %a "$R/impl.txt")"

# report and lessons
printf '%s\n' '{"type": "run", "issue": 1, "final": "local_pass", "attempts": [{"outcome": "pass"}]}' >> "$WORK/ra14/.claude/guild/memory/local-dev/runs.jsonl"
eq "report splits by mode; a line without mode counts as oneshot; agent checks stay out of the top-level outcomes" "1 1 1" \
  "$(ld "$WORK/ra14" report | "$PY" -c 'import json,sys; d=json.loads(sys.stdin.read().split(">>> LOCAL-DEV <<<\n")[-1]); print(d["by_mode"]["agent"]["runs"], d["by_mode"]["oneshot"]["runs"], sum(d["attempt_outcomes"].values()))')"
: > "$FAKE/replies.jsonl"

# ---------------------------------------------------------------- 9. report + usage
echo "== report"
REP="$(ld "$WORK/r11" report)"
eq "report counts the fallback" "1" "$(echo "$REP" | field final.fallback)"
eq "report counts attempt outcomes" "1" "$(echo "$REP" | field attempt_outcomes.output_cap)"
eq "report: pass at attempt 2" "1" "$(ld "$WORK/r21" report | field pass_at_attempt.2)"
ld "$WORK/r10" start --issue 1 >/dev/null 2>&1; eq "usage error → exit 64" "64" "$?"
mkdir -p "$WORK/nocfg" && git -C "$WORK/nocfg" init -q
ld "$WORK/nocfg" status --issue 1 >/dev/null 2>&1; eq "no Guild config → exit 65" "65" "$?"
R="$WORK/rcap1"; mkrepo "$R" 1 "$(LDJSON '{"max_output_tokens_retry": 4000}')"; : > "$FAKE/replies.jsonl"
reply "thinking forever" length; reply "$FIX_BLOCK"
eq "a retry cap below max_output_tokens is not an error — the cap just stays" "8000 8000 local_pass" \
  "$(OUT="$(start "$R" 1 >/dev/null; waitjob "$R" 1)"; echo "$(echo "$OUT" | field attempts.0.num_predict) $(echo "$OUT" | field attempts.1.num_predict) $(echo "$OUT" | field state)")"
R="$WORK/rcap2"; mkrepo "$R" 1 "$(LDJSON '{"num_ctx": 32768}')"; : > "$FAKE/replies.jsonl"
reply "thinking forever" length; reply "$FIX_BLOCK"
OUT="$(start "$R" 1 >/dev/null; waitjob "$R" 1)"
eq "num_ctx 32768 (valid before the retry cap existed) still runs" "local_pass" "$(echo "$OUT" | field state)"
eq "…its raised cap shrinks to what num_ctx leaves beside the prompt and the carry" "True" \
  "$(echo "$OUT" | field attempts.1.num_predict | "$PY" -c 'import sys; v=int(sys.stdin.read()); print(8000 <= v < 16000)')"

echo
echo "local_dev: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
