#!/usr/bin/env bash
# Verification for `base_ci.py` — the Base CI line of `sprint run` Phase 0 / `sprint plan` Phase 2
# (0.99.2 A9 · B3). Only `gh` is a stub: it serves the real check-run snapshots under
# tests/fixtures/real/base-ci/ (one-man-company PRs #616 #617 #647 #657, word_app main) and runs
# the script's OWN `--jq` expressions through jq, so the expressions are tested, not emulated.
#
# The cases that matter most:
#   • dedupe by check name BEFORE the annotation reads — #616's raw stream is 5 runs, 3 names;
#     reading annotations first spent the 3 reads on `Conventional 접두어 검증` duplicates and never
#     reached `Analyze & Test`.
#   • only `failure`-level annotations are a cause — #617 carries a `warning` (Node.js 20) and a
#     `notice` beside the real failure.
#   • a branch that has runs never reads the last merged PR (word_app main — the call was made).
#
# Usage: bash plugins/guild-plugin/tests/base_ci_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BCI="$HERE/../skills/gld/commands/atoms/base_ci.py"
FX="$HERE/fixtures/real/base-ci"
[ -f "$BCI" ] || { echo "missing: $BCI" >&2; exit 1; }
[ -d "$FX" ] || { echo "missing: $FX" >&2; exit 1; }
PY="${PY:-python3}"
WORK="$(mktemp -d)" || { echo "mktemp -d failed" >&2; exit 1; }
[ -n "$WORK" ] && [ -d "$WORK" ] || { echo "mktemp -d gave no directory" >&2; exit 1; }
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0

gld_skip() { echo "SKIP: $1" >&2; [ "${GLD_ALLOW_SKIP:-0}" = 1 ] && exit 0; \
            echo "FAIL  스킵은 통과가 아닙니다 — GLD_ALLOW_SKIP=1 로 명시하십시오." >&2; exit 1; }
"$PY" -c "pass" >/dev/null 2>&1 || gld_skip "$PY is not usable — this suite is python-based"
command -v jq >/dev/null 2>&1 || gld_skip "jq is not on PATH — the stub runs the script's own --jq through it"
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s — %s\n' "$1" "$2"; }
eq()  { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "got [$2] want [$3]"; fi; }

# ── gh stub ──────────────────────────────────────────────────────────────────
# $BC/cr_<ref>.json  — check-runs of <ref> (missing → none) · $BC/merged.json — merged PR list
# $BC/ann_<id>.json  — annotations of one run, else $BC/ann_default.json · $BC/fail_<what> — exit 1
mkdir -p "$WORK/bin"
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env python3
import json, os, subprocess, sys
bc = os.environ["BC"]
a = sys.argv[1:]
open(os.path.join(bc, "calls.txt"), "a").write(" ".join(a) + "\n")
def fail(what):
    if os.path.exists(os.path.join(bc, "fail_" + what)):
        sys.stderr.write("HTTP 502: stub failure (%s)\n" % what); sys.exit(1)
def load(name, key, default):
    p = os.path.join(bc, name)
    if not os.path.exists(p):
        return default
    d = json.load(open(p, encoding="utf-8"))
    return d.get(key, default) if isinstance(d, dict) else d
def jq(q, data):
    p = subprocess.run(["jq", "-c", q], input=json.dumps(data), capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr); sys.exit(1)
    sys.stdout.write(p.stdout)
q = a[a.index("--jq") + 1] if "--jq" in a else "."
if a[:2] == ["repo", "view"]:
    fail("repo"); print("main")
elif a[:1] == ["api"] and a[1].endswith("/check-runs") and "/commits/" in a[1]:
    fail("runs"); ref = a[1].split("/commits/")[1].split("/")[0]
    jq(q, {"check_runs": load("cr_%s.json" % ref, "check_runs", [])})
elif a[:1] == ["api"] and a[1].endswith("/annotations"):
    fail("ann"); rid = a[1].split("/check-runs/")[1].split("/")[0]
    name = "ann_%s.json" % rid if os.path.exists(os.path.join(bc, "ann_%s.json" % rid)) else "ann_default.json"
    jq(q, load(name, "annotations", []))
elif a[:2] == ["pr", "list"]:
    fail("prs"); jq(q, load("merged.json", "prs", []))
else:
    sys.stderr.write("stub: unhandled %r\n" % (a,)); sys.exit(2)
STUB
chmod +x "$WORK/bin/gh"

case_dir() {   # case_dir <name> → fresh $BC
  BC="$WORK/$1"; rm -rf "$BC"; mkdir -p "$BC"; : > "$BC/calls.txt"; export BC
}
run_bci() {    # run_bci [args…] → OUT (stdout) · ERR · RC
  OUT="$(PATH="$WORK/bin:$PATH" "$PY" -B "$BCI" "$@" 2>"$WORK/err")"; RC=$?
  ERR="$(cat "$WORK/err")"
}
n_calls() { grep -c -- "$1" "$BC/calls.txt" | tr -d ' '; }
ann_ids() { grep '/annotations' "$BC/calls.txt" | sed 's|.*/check-runs/\([0-9]*\)/annotations.*|\1|' | sort | tr '\n' ' '; }
ALL3='Analyze & Test, Conventional 접두어 검증, 수동 검증 신선도·케이스 커버리지 검사 (PR 브랜치 스코프)'

echo "── base_ci: 없음 · ci-blocked · red · green (real snapshots) ──"
# (1) main has no run and no PR was merged → 없음
case_dir empty; cp "$FX/empty.json" "$BC/cr_main.json"; printf '{"prs":[]}' > "$BC/merged.json"
run_bci --repo acme/app
eq "empty main + no merged PR → 없음, exit 0" "$RC|$OUT" "0|Base CI: 없음"
eq "empty main → exactly one merged-PR read" "$(n_calls '^pr list')" "1"
has_q() { case "$(cat "$BC/calls.txt")" in *"$2"*) ok "$1" ;; *) bad "$1" "[$2] not in calls" ;; esac; }
has_q "the merged-PR read is the documented form (--limit 20 · max_by(.mergedAt))" \
  "pr list --repo acme/app --state merged --base main --limit 20 --json number,headRefOid,mergedAt --jq if length == 0 then null else (max_by(.mergedAt) | {number, headRefOid}) end"
has_q "the check-run read is the documented stream (--paginate --jq …annotations_count)" \
  "api repos/acme/app/commits/main/check-runs --paginate --jq .check_runs[] | {id, name, conclusion, annotations: .output.annotations_count}"

# (2) #616 — 5 runs, 3 names, every failure never started (billing) → ci-blocked; dedupe first
case_dir pr616; cp "$FX/pr616.json" "$BC/cr_main.json"; cp "$FX/ann-blocked.json" "$BC/ann_default.json"
run_bci --repo acme/app
eq "#616 → ci-blocked(the three real names)" "$RC|$OUT" "0|Base CI: ci-blocked($ALL3)"
eq "#616 → dedupe 5→3: three annotation reads, the highest id per name (Analyze & Test's included)" \
  "$(ann_ids)" "124396379663 124396379917 124403030936 "
eq "#616 → a branch with runs reads no merged PR" "$(n_calls '^pr list')" "0"

# (3) #617 — main empty, the last merged PR (11-03 snapshot) is #617; Analyze & Test failed for real
case_dir pr617; cp "$FX/empty.json" "$BC/cr_main.json"; cp "$FX/merged-prs-1103.json" "$BC/merged.json"
cp "$FX/pr617.json" "$BC/cr_abbdcc4e.json"; cp "$FX/ann-617.json" "$BC/ann_125287689850.json"
run_bci --repo acme/app
eq "#617 → red(Analyze & Test) (근거: 마지막 머지 PR #617)" "$RC|$OUT" "0|Base CI: red(Analyze & Test) (근거: 마지막 머지 PR #617)"
eq "#617 → the head's check-runs are read by its headRefOid" "$(n_calls 'commits/abbdcc4e/check-runs')" "1"
eq "#617 → one annotation read (the one failure)" "$(ann_ids)" "125287689850 "
# a warning- or notice-level `was not started` is no cause: still red (synthetic variant of the real file)
"$PY" - "$BC/ann_125287689850.json" <<'PYX'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
d["annotations"] = [a for a in d["annotations"] if a["annotation_level"] != "failure"]
d["annotations"].append({"annotation_level": "warning", "message": "The job was not started (warning-level text)"})
d["annotations"].append({"annotation_level": "notice", "message": "The job was not started (notice-level text)"})
json.dump(d, open(p, "w"))
PYX
: > "$BC/calls.txt"; run_bci --repo acme/app
eq "#617 variant: warning/notice-level 'was not started' is not a cause → still red" "$OUT" "Base CI: red(Analyze & Test) (근거: 마지막 머지 PR #617)"

# (4) today — the last merged PR is #657 → green on its head
case_dir today; cp "$FX/empty.json" "$BC/cr_main.json"; cp "$FX/merged-prs-today.json" "$BC/merged.json"
cp "$FX/pr657.json" "$BC/cr_3cc675c4.json"
run_bci --repo acme/app
eq "today (largest mergedAt #657) → green on #657's head" "$RC|$OUT" "0|Base CI: green($ALL3)"
eq "today → no annotation read on an all-green head" "$(n_calls '/annotations')" "0"

# (5) #647 — 4 runs, 3 names, all success → green (names, not a basis)
case_dir pr647; cp "$FX/pr647.json" "$BC/cr_main.json"
run_bci --repo acme/app
eq "#647 → 4→3, green(the three real names)" "$RC|$OUT" "0|Base CI: green($ALL3)"

# (6) word_app main — Dependabot ×4, validate_pr skipped, update_release_draft success
case_dir wa; cp "$FX/wa-main.json" "$BC/cr_main.json"; printf '{"prs":[{"number":1,"headRefOid":"x","mergedAt":"2026-01-01T00:00:00Z"}]}' > "$BC/merged.json"
run_bci --repo acme/app
eq "word_app main → 6→3, green(Dependabot, update_release_draft, validate_pr)" "$RC|$OUT" "0|Base CI: green(Dependabot, update_release_draft, validate_pr)"
eq "word_app main → no merged-PR read (the branch has runs)" "$(n_calls '^pr list')" "0"

echo "── base_ci: mixed · still running · failures · usage ──"
# red mixed with never-started → red line + a second ci-blocked line (both printed)
case_dir mixed; cp "$FX/pr617.json" "$BC/cr_main.json"; cp "$FX/ann-617.json" "$BC/ann_125287689850.json"
cp "$FX/ann-blocked.json" "$BC/ann_default.json"
"$PY" - "$BC/cr_main.json" <<'PYX'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
for r in d["check_runs"]:
    if r["name"] == "Conventional 접두어 검증":
        r["conclusion"] = "failure"
json.dump(d, open(p, "w"))
PYX
run_bci --repo acme/app
eq "red + never-started → two lines, the real red first" "$OUT" "Base CI: red(Analyze & Test) (근거: main 최신 커밋)
ci-blocked: Conventional 접두어 검증"
# a run still going (conclusion null), no red → green (진행 중)
case_dir running; cp "$FX/pr657.json" "$BC/cr_main.json"
"$PY" -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["check_runs"][1]["conclusion"]=None; json.dump(d,open(p,"w"))' "$BC/cr_main.json"
run_bci --repo acme/app
eq "a null conclusion, no red → green(…) (진행 중)" "$OUT" "Base CI: green($ALL3) (진행 중)"
# timed_out is red too (qa.md's rule)
"$PY" -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["check_runs"][1]["conclusion"]="timed_out"; json.dump(d,open(p,"w"))' "$BC/cr_main.json"
run_bci --repo acme/app
eq "timed_out → red, no annotation read (not a failure)" "$OUT|$(n_calls '/annotations')" "Base CI: red(Analyze & Test) (근거: main 최신 커밋)|0"
for what in repo runs prs ann; do
  case_dir "f-$what"; cp "$FX/empty.json" "$BC/cr_main.json"; cp "$FX/merged-prs-1103.json" "$BC/merged.json"
  cp "$FX/pr617.json" "$BC/cr_abbdcc4e.json"; cp "$FX/ann-617.json" "$BC/ann_default.json"; : > "$BC/fail_$what"
  run_bci --repo acme/app
  eq "a failed $what call → unavailable, exit 65" "$RC|$OUT" "65|Base CI: unavailable"
  case "$ERR" in "base_ci: gh "*) ok "a failed $what call → one stderr reason line" ;; *) bad "stderr for $what" "[$ERR]" ;; esac
done
# no gh at all (not on PATH) → `unavailable`, 65 — never a traceback (code review r1)
PYABS="$("$PY" -c "import sys; print(sys.executable)")"   # the real binary — a PATH shim would need PATH
OUT="$(PATH="$WORK/empty-path" "$PYABS" -B "$BCI" --repo acme/app 2>"$WORK/err")"; RC=$?; ERR="$(cat "$WORK/err")"
eq "gh not on PATH → unavailable, exit 65" "$RC|$OUT" "65|Base CI: unavailable"
case "$ERR" in *Traceback*) bad "gh not on PATH → no traceback" "[$ERR]" ;; "base_ci: gh "*) ok "gh not on PATH → one stderr reason line, no traceback" ;; *) bad "gh not on PATH stderr" "[$ERR]" ;; esac
run_bci
eq "no --repo → exit 64" "$RC" "64"
run_bci --repo nope
eq "--repo without owner/ → exit 64" "$RC" "64"
PYC="$(ls "$(dirname "$BCI")"/__pycache__/base_ci.* 2>/dev/null)"
[ -z "$PYC" ] && ok "no base_ci .pyc written beside the plugin's scripts" || bad "pycache" "$PYC"

echo
echo "base_ci: $PASS passed, $FAIL failed"
# ⚠ Keep equal to the measured PASS count; raise it only when checks are added on purpose.
BCI_MIN_CHECKS=32
if [ "$((PASS + FAIL))" -lt "$BCI_MIN_CHECKS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${BCI_MIN_CHECKS}건)."
  exit 1
fi
[ "$FAIL" -eq 0 ]
