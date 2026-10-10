#!/usr/bin/env bash
# Verification for `stack_sync.py` — keeping a squash-merged sprint stack reviewable
# (design: design/guild/09-squash-stack.md · contract: _sprint_dag.md Section G).
#
# Real git end to end: a bare "origin", the human's clone, and a helper clone that plays the
# GitHub side (squash merges, review fixes). Only `gh` is a stub — it serves PR/issue JSON from a
# state file, reads OPEN PR heads live from the bare remote (as GitHub does after a push), and
# records every mutating call.
#
# The cases that matter most:
#   • needs-sync vs stale — a member that already holds the dependency's FINAL head is synced
#     automatically; one cut before the dependency changed is left to the human.
#   • a two-level stack — after the middle PR is synced and squash-merged, the top one must read
#     needs-sync, not stale (our own sync merge is not a "change" to the dependency).
#   • nothing reaches the remote when the merge conflicts or verification fails.
#
# Usage: bash plugins/guild-plugin/tests/stack_sync_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SYNC="$HERE/../skills/gld/commands/atoms/stack_sync.py"
RENDER="$HERE/../skills/gld/commands/atoms/render_supervisor.py"
[ -f "$SYNC" ] || { echo "missing: $SYNC" >&2; exit 1; }
PY="${PY:-python3}"
WORK="$(mktemp -d)" || { echo "mktemp -d failed" >&2; exit 1; }
[ -n "$WORK" ] && [ -d "$WORK" ] || { echo "mktemp -d gave no directory" >&2; exit 1; }
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0

# Hooks export these; left set, every `git -C <tmp>` below would act on the caller's repo.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
unset GIT_CONFIG GIT_CONFIG_COUNT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
export GIT_CONFIG_NOSYSTEM=1 HOME="$WORK/home"; mkdir -p "$HOME"
git config --global init.defaultBranch main
git config --global advice.detachedHead false

gld_skip() { echo "SKIP: $1" >&2; [ "${GLD_ALLOW_SKIP:-0}" = 1 ] && exit 0; \
            echo "FAIL  스킵은 통과가 아닙니다 — GLD_ALLOW_SKIP=1 로 명시하십시오." >&2; exit 1; }
"$PY" -c "pass" >/dev/null 2>&1 || gld_skip "$PY is not usable — this suite is python-based"
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s — %s\n' "$1" "$2"; }
eq()  { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "got [$2] want [$3]"; fi; }
has() { case "$2" in *"$3"*) ok "$1" ;; *) bad "$1" "[$3] not in [$2]" ;; esac; }
lacks() { case "$2" in *"$3"*) bad "$1" "[$3] unexpectedly in [$2]" ;; *) ok "$1" ;; esac; }

# ── gh stub ──────────────────────────────────────────────────────────────────
mkdir -p "$WORK/bin"
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env python3
import json, os, subprocess, sys
st_path, remote, calls = os.environ["STUB_STATE"], os.environ["STUB_REMOTE"], os.environ["STUB_CALLS"]
st = json.load(open(st_path))
a = [x for x in sys.argv[1:]]
if "-R" in a:
    i = a.index("-R"); del a[i:i + 2]
def save(): json.dump(st, open(st_path, "w"))
def log(): open(calls, "a").write(" ".join(sys.argv[1:]) + "\n")
def head(b):
    p = subprocess.run(["git", "--git-dir", remote, "rev-parse", "refs/heads/" + b],
                       capture_output=True, text=True)
    return p.stdout.strip()
if a[:2] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": "acme/app", "defaultBranchRef": {"name": "main"}}))
elif a[:2] == ["issue", "view"]:
    it = st["issues"][a[2]]
    print(json.dumps({"body": it.get("body", ""), "labels": [{"name": l} for l in it["labels"]]}))
elif a[:2] == ["pr", "list"]:
    out = []
    for p in st["prs"]:
        p = dict(p)
        if p["state"] == "OPEN":
            p["headRefOid"] = p.pop("headOverride", None) or head(p["headRefName"])
        p["mergedAt"] = p.get("mergedAt") or ("2026-10-10T00:00:00Z" if p["state"] == "MERGED" else None)
        p.pop("body", None)
        out.append(p)
    print(json.dumps(out))
elif a[:2] == ["pr", "view"]:
    p = [p for p in st["prs"] if str(p["number"]) == a[2]][0]
    print(json.dumps({"body": p.get("body", "")}))
elif a[:2] == ["pr", "edit"]:
    log()
    if os.environ.get("STUB_FAIL_EDIT"):
        sys.stderr.write("HTTP 422\n"); sys.exit(1)
    p = [p for p in st["prs"] if str(p["number"]) == a[2]][0]
    p["baseRefName"] = a[a.index("--base") + 1]; save()
elif a[:2] == ["pr", "ready"]:
    log()
    if os.environ.get("STUB_FAIL_READY"):
        sys.stderr.write("HTTP 502\n"); sys.exit(1)
    p = [p for p in st["prs"] if str(p["number"]) == a[2]][0]
    p["isDraft"] = False; save()
else:
    sys.stderr.write("stub: unhandled %r\n" % (a,)); sys.exit(2)
STUB
chmod +x "$WORK/bin/gh"

# ── scenario builder ─────────────────────────────────────────────────────────
# new_scenario <name> → sets S (dir), R (human clone), T (helper clone), O (bare origin)
new_scenario() {
  S="$WORK/$1"; mkdir -p "$S"; O="$S/origin.git"; R="$S/repo"; T="$S/tool"
  git init -q --bare "$O"
  git clone -q "$O" "$T" 2>/dev/null
  printf 'verified.txt\ninstalled.txt\n' > "$T/.gitignore"; echo base > "$T/base.txt"
  git -C "$T" add . && git -C "$T" commit -qm init && git -C "$T" push -q origin HEAD:main
  git clone -q "$O" "$R"
  mkdir -p "$R/.claude/guild"
  printf '{"commands":{"test":"touch verified.txt","lint":null,"typecheck":null}}\n' \
    > "$R/.claude/guild/config.json"
  : > "$S/calls.txt"
}
# commit_on <branch> <from> <file> <content> — in the helper clone, pushed
commit_on() {
  git -C "$T" checkout -q -B "$1" "$2" && echo "$4" > "$T/$3" && git -C "$T" add "$3" \
    && git -C "$T" commit -qm "$1: $3" && git -C "$T" push -q -f origin "$1"
}
# squash_merge <branch> → echoes the squash commit on main
squash_merge() {
  git -C "$T" fetch -q origin && git -C "$T" checkout -q -B main origin/main \
    && git -C "$T" merge -q --squash "origin/$1" >/dev/null && git -C "$T" commit -qm "squash $1" \
    && git -C "$T" push -q origin main && git -C "$T" rev-parse HEAD
}
sha() { git --git-dir "$O" rev-parse "refs/heads/$1"; }
# pull_ref <pr> <sha> — GitHub keeps every PR head at refs/pull/<n>/head
pull_ref() { git --git-dir "$O" update-ref "refs/pull/$1/head" "$2"; }
# write_state <json> — the gh stub's world
write_state() { printf '%s' "$1" > "$S/state.json"; }
tracker_body() {   # rows: "<issue>:<base dep or ->" ...
  local rows="" r
  for r in "$@"; do
    local i="${r%%:*}" d="${r#*:}"
    if [ "$d" = "-" ]; then rows="$rows| x | #$i | — | — | |\\n"; else rows="$rows| x | #$i | #$d | #$d | |\\n"; fi
  done
  printf '# Sprint\\n<!-- guild:sprint:plan -->\\n| # | 이슈 | base 의존 | 원래 의존 | 비고 |\\n|---|---|---|---|---|\\n%s<!-- /guild:sprint:plan -->\\n' "$rows"
}
STACK_BODY='Closes #12\n<!-- guild:sprint:stack -->\n## 스택 PR\n<!-- /guild:sprint:stack -->'
# pair_state <draft true|false> — #11 merged as $HD/$SQ, #12 open on main
pair_state() {
  write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11)\"},\"12\":{\"labels\":[\"guild:done\"]}},
    \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQ\"},\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":11}]},
     {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"main\",\"mergeCommit\":null,\"isDraft\":$1,\"body\":\"$STACK_BODY\",\"closingIssuesReferences\":[{\"number\":12}]}]}"
}
sync() {   # sync [args…] → stdout; rc in $RC
  OUT="$(cd "$R" && STUB_STATE="$S/state.json" STUB_REMOTE="$O" STUB_CALLS="$S/calls.txt" \
         PATH="$WORK/bin:$PATH" "$PY" "$SYNC" --tracker 10 "$@" 2>"$S/err")"; RC=$?
}
# standard: #11 squash-merged; #12 stacked on it, done, draft with the stack marker
standard() {
  new_scenario "$1"
  commit_on "feature/#11-dep" main a.txt dep
  commit_on "feature/#12-member" "feature/#11-dep" b.txt member
  HD="$(sha 'feature/#11-dep')"
  SQ="$(squash_merge 'feature/#11-dep')"
  write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11)\"},
    \"12\":{\"labels\":[\"guild:done\"]}},
    \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",
      \"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQ\"},\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":11}]},
     {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"feature/#11-dep\",
      \"mergeCommit\":null,\"isDraft\":true,\"body\":\"$STACK_BODY\",\"closingIssuesReferences\":[{\"number\":12}]}]}"
}

echo "── stack_sync: check vs apply ──"
standard s1
BEFORE="$(sha 'feature/#12-member')"
sync --check
eq "check: exit 0" "$RC" "0"
eq "check: needs-sync with every action named" "$OUT" "12 needs-sync #11 merge,retarget,ready"
eq "check: the remote branch is untouched" "$(sha 'feature/#12-member')" "$BEFORE"
eq "check: no mutating gh call" "$(cat "$S/calls.txt")" ""

git -C "$R" fetch -q origin && git -C "$R" branch -q "feature/#12-member" "origin/feature/#12-member"
sync --install-cmd 'touch installed.txt'
eq "apply: exit 0" "$RC" "0"
eq "apply: merged, retargeted, marked ready" "$OUT" "12 synced #11 merge+retarget+ready"
AFTER="$(sha 'feature/#12-member')"
eq "apply: fast-forward, not a rewrite" \
  "$(git --git-dir "$O" merge-base --is-ancestor "$BEFORE" "$AFTER" && echo ff)" "ff"
eq "apply: the PR diff is the member's own change only" \
  "$(git --git-dir "$O" diff --name-only main..."$AFTER")" "b.txt"
has "apply: the merge carries the Guild-Sync trailer" \
  "$(git --git-dir "$O" show -s --format=%B "$AFTER")" "Guild-Sync: #11"
has "apply: verification ran in the worktree" "$(cat "$R"/.claude/guild/.sprint-logs/10/sync-12-*.log)" "touch verified.txt"
has "apply: install ran before verification" "$(cat "$R"/.claude/guild/.sprint-logs/10/sync-12-*.log | tr '\n' ' ')" '$ touch installed.txt $ touch verified.txt' 
has "apply: retargeted to the default branch" "$(cat "$S/calls.txt")" "pr edit 102 --base main"
has "apply: marked ready" "$(cat "$S/calls.txt")" "pr ready 102"
eq "apply: local branch advanced to the pushed head" "$(git -C "$R" rev-parse 'feature/#12-member')" "$AFTER"
eq "apply: throwaway worktree removed" "$(git -C "$R" worktree list | wc -l | tr -d ' ')" "1"
[ ! -e "$R/verified.txt" ] && ok "apply: verification did not run in the human's checkout" \
  || bad "apply: verification location" "verified.txt appeared in the human's checkout"
[ ! -d "$S/.gld-repo-sprint-10" ] && ok "apply: empty container removed" \
  || bad "apply: container cleanup" "$S/.gld-repo-sprint-10 left behind"

: > "$S/calls.txt"
sync
eq "re-run: idempotent" "$OUT" "12 synced #11 none"
eq "re-run: no mutating gh call" "$(cat "$S/calls.txt")" ""
sync --check
eq "re-run --check: silent when there is nothing to do" "$OUT" ""

echo "── stack_sync: what must NOT be synced ──"
# stale: the dependency got a review fix after the member was cut
new_scenario s2
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
commit_on "feature/#11-dep" "feature/#11-dep" a.txt dep-fixed
# GitHub keeps every PR head under refs/pull/<n>/head, even after the branch is deleted — the
# human's clone has never seen this review fix, so the script must fetch it from there.
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"
git -C "$T" push -q origin "$HD:refs/pull/101/head"
git -C "$T" push -q origin --delete "feature/#11-dep"
BEFORE="$(sha 'feature/#12-member')"
write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11)\"},\"12\":{\"labels\":[\"guild:done\"]}},
  \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQ\"},\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":11}]},
   {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"main\",\"mergeCommit\":null,\"isDraft\":true,\"body\":\"$STACK_BODY\",\"closingIssuesReferences\":[{\"number\":12}]}]}"
sync
eq "stale: reported, not synced" "$OUT" "12 stale #11"
eq "stale: remote untouched" "$(sha 'feature/#12-member')" "$BEFORE"
eq "stale: no gh mutation (not even ready)" "$(cat "$S/calls.txt")" ""
# the human catches up by hand (no Guild-Sync trailer) — not ours to ready
git -C "$T" fetch -q origin && git -C "$T" checkout -q -B "feature/#12-member" "origin/feature/#12-member"
git -C "$T" merge -q --no-edit origin/main >/dev/null 2>&1   # add/add on a.txt — resolved by hand
git -C "$T" checkout -q --theirs a.txt && git -C "$T" add a.txt && git -C "$T" commit -q --no-edit \
  && git -C "$T" push -q origin "feature/#12-member"
sync
eq "human catch-up: draft held for the human, not readied" "$OUT" "12 draft-held #11 pr=102"
lacks "human catch-up: no ready call" "$(cat "$S/calls.txt")" "pr ready"
sync --check
eq "human catch-up: --check says so too (daily must not go quiet)" "$OUT" "12 draft-held #11 pr=102"

# clean: merged with a merge commit — the member's diff is already clean
new_scenario s3
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
HD="$(sha 'feature/#11-dep')"
git -C "$T" fetch -q origin && git -C "$T" checkout -q -B main origin/main \
  && git -C "$T" merge -q --no-ff -m "Merge dep" "origin/feature/#11-dep" && git -C "$T" push -q origin main
MC="$(git -C "$T" rev-parse HEAD)"
write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11)\"},\"12\":{\"labels\":[\"guild:done\"]}},
  \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$MC\"},\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":11}]},
   {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"main\",\"mergeCommit\":null,\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":12}]}]}"
sync
eq "merge-commit strategy: clean, nothing done" "$OUT" "12 clean #11 none"
sync --check
eq "merge-commit strategy: --check is silent" "$OUT" ""
"$PY" - "$S/state.json" <<'EOF'
import json, sys; p = sys.argv[1]; s = json.load(open(p))
s["prs"][1].update(isDraft=True, baseRefName="feature/#11-dep", body="<!-- guild:sprint:stack -->")
json.dump(s, open(p, "w"))
EOF
sync
eq "merge-commit strategy: a Guild draft is still retargeted and readied" "$OUT" "12 synced #11 retarget+ready"

# conflict: main moved under the member on the same lines
standard s4
commit_on "other" main b.txt other-change
git -C "$T" checkout -q -B main origin/main && git -C "$T" fetch -q origin \
  && git -C "$T" reset -q --hard origin/main && git -C "$T" merge -q --squash origin/other >/dev/null \
  && git -C "$T" commit -qm "squash other" && git -C "$T" push -q origin main
BEFORE="$(sha 'feature/#12-member')"
sync
eq "conflict: reported with the path" "$OUT" "12 conflict #11 b.txt"
sync --check
eq "conflict: --check says the same (daily must not promise a sync that refuses)" "$OUT" "12 conflict #11 b.txt"
eq "conflict: remote untouched" "$(sha 'feature/#12-member')" "$BEFORE"
eq "conflict: no retarget or ready" "$(cat "$S/calls.txt")" ""
eq "conflict: worktree cleaned up" "$(git -C "$R" worktree list | wc -l | tr -d ' ')" "1"

# verify-failed: nothing is pushed
standard s5
printf '{"commands":{"test":"false","lint":null}}\n' > "$R/.claude/guild/config.json"
BEFORE="$(sha 'feature/#12-member')"
sync
has "verify-failed: reported with the log" "$OUT" "12 verify-failed #11 "
eq "verify-failed: remote untouched" "$(sha 'feature/#12-member')" "$BEFORE"
eq "verify-failed: no retarget or ready" "$(cat "$S/calls.txt")" ""

# a member still in the spine is not touched
standard s6
"$PY" - "$S/state.json" <<'EOF'
import json, sys; p = sys.argv[1]; s = json.load(open(p)); s["issues"]["12"]["labels"] = ["guild:test"]; json.dump(s, open(p, "w"))
EOF
sync
eq "not-done: skipped" "$OUT" "12 skipped #11 not-done"
sync --check
eq "not-done: --check says the same (daily must not promise a sync that refuses)" "$OUT" "12 skipped #11 not-done"
eq "not-done: no gh mutation" "$(cat "$S/calls.txt")" ""

# a branch checked out somewhere (the human's checkout) is not touched
standard s7
git -C "$R" fetch -q origin && git -C "$R" checkout -q -b "feature/#12-member" "origin/feature/#12-member"
sync
# (git prints the realpath — /private/var on macOS — so match the tail)
case "$OUT" in "12 skipped #11 branch-checked-out "*/s7/repo) ok "checked out: skipped, naming the checkout that holds it" ;;
  *) bad "checked out: skipped, naming the checkout" "got [$OUT]" ;; esac

# a draft the human made (no stack marker) is never marked ready
standard s8
"$PY" - "$S/state.json" <<'EOF'
import json, sys; p = sys.argv[1]; s = json.load(open(p)); s["prs"][1]["body"] = "Closes #12"; json.dump(s, open(p, "w"))
EOF
sync
eq "foreign draft: synced but left draft" "$OUT" "12 synced #11 merge+retarget"
lacks "foreign draft: no ready call" "$(cat "$S/calls.txt")" "pr ready"

# retarget fails after the push — say what already happened
standard s9
OUT="$(cd "$R" && STUB_FAIL_EDIT=1 STUB_STATE="$S/state.json" STUB_REMOTE="$O" STUB_CALLS="$S/calls.txt" \
       PATH="$WORK/bin:$PATH" "$PY" "$SYNC" --tracker 10 2>"$S/err")"
has "retarget failure: names what was already done" "$OUT" "12 error #11 retarget failed after merge:"
lacks "retarget failure: never marks ready on an unfixed PR" "$(cat "$S/calls.txt")" "pr ready"

# needs-human on top of done is still not ours to touch
standard s12
"$PY" - "$S/state.json" <<'EOF'
import json, sys; p = sys.argv[1]; s = json.load(open(p)); s["issues"]["12"]["labels"] = ["guild:done", "guild:needs-human"]; json.dump(s, open(p, "w"))
EOF
sync
eq "needs-human: skipped" "$OUT" "12 skipped #11 not-done"

# someone pushed after GitHub last reported the head
standard s13
"$PY" - "$S/state.json" <<'EOF'
import json, sys; p = sys.argv[1]; s = json.load(open(p)); s["prs"][1]["headOverride"] = "0" * 40; json.dump(s, open(p, "w"))
EOF
BEFORE="$(sha 'feature/#12-member')"
sync
eq "head moved: skipped" "$OUT" "12 skipped #11 head-moved"
eq "head moved: remote untouched" "$(sha 'feature/#12-member')" "$BEFORE"

# the dependency was merged into another branch (out of order)
standard s14
"$PY" - "$S/state.json" <<'EOF'
import json, sys; p = sys.argv[1]; s = json.load(open(p)); s["prs"][0]["baseRefName"] = "release"; json.dump(s, open(p, "w"))
EOF
sync
eq "dep merged into a non-default branch: ambiguous" "$OUT" "12 ambiguous #11 dep-merged-into-release"

# a local branch ahead of the remote is never moved backwards or sideways
standard s15
git -C "$R" fetch -q origin && git -C "$R" branch -q "feature/#12-member" "origin/feature/#12-member"
git -C "$R" worktree add -q --detach "$S/tmpwt" "feature/#12-member" && echo local > "$S/tmpwt/l.txt" \
  && git -C "$S/tmpwt" add l.txt && git -C "$S/tmpwt" commit -qm local \
  && git -C "$R" update-ref "refs/heads/feature/#12-member" "$(git -C "$S/tmpwt" rev-parse HEAD)" \
  && git -C "$R" worktree remove "$S/tmpwt"
LOCAL="$(git -C "$R" rev-parse 'feature/#12-member')"
sync
eq "local ahead: remote still synced" "$OUT" "12 synced #11 merge+retarget+ready"
eq "local ahead: local branch left where it was" "$(git -C "$R" rev-parse 'feature/#12-member')" "$LOCAL"

# verification that rewrites a tracked file verified a different tree — nothing is pushed
standard s16
printf '{"commands":{"test":"cp base.txt b.txt"}}\n' > "$R/.claude/guild/config.json"
BEFORE="$(sha 'feature/#12-member')"
sync
has "verify rewrote a tracked file: refused" "$OUT" "12 verify-failed #11 verification changed tracked files"
eq "verify rewrote a tracked file: remote untouched" "$(sha 'feature/#12-member')" "$BEFORE"
has "verify rewrote a tracked file: the kept worktree is reported on stdout" "$OUT" "12 worktree-kept #11 "

# verification leaving untracked, non-ignored output (coverage, junit) is not a kept worktree
standard s41
printf '{"commands":{"test":"touch coverage.out"}}\n' > "$R/.claude/guild/config.json"
sync
eq "untracked verification output: synced, nothing kept" "$OUT" "12 synced #11 merge+retarget+ready"

# unattended: classify yes, push no
standard s17
OUT="$(cd "$R" && GLD_UNATTENDED=1 STUB_STATE="$S/state.json" STUB_REMOTE="$O" STUB_CALLS="$S/calls.txt" \
       PATH="$WORK/bin:$PATH" "$PY" "$SYNC" --tracker 10 2>/dev/null)"; RC=$?
eq "unattended apply: refused (64)" "$RC" "64"
OUT="$(cd "$R" && GLD_UNATTENDED=1 STUB_STATE="$S/state.json" STUB_REMOTE="$O" STUB_CALLS="$S/calls.txt" \
       PATH="$WORK/bin:$PATH" "$PY" "$SYNC" --tracker 10 --check 2>/dev/null)"; RC=$?
eq "unattended --check: allowed" "$RC:$OUT" "0:12 needs-sync #11 merge,retarget,ready"

echo "── stack_sync: what the dependency did before it merged ──"
# GitHub's "Update branch" on the dependency (a clean merge of main) is not a change to its work
new_scenario s18
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
commit_on "other" main o.txt other && SQO="$(squash_merge other)"
git -C "$T" checkout -q -B "feature/#11-dep" "origin/feature/#11-dep" \
  && git -C "$T" merge -q --no-edit origin/main >/dev/null && git -C "$T" push -q origin "feature/#11-dep"
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"
write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11)\"},\"12\":{\"labels\":[\"guild:done\"]}},
  \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQ\"},\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":11}]},
   {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"main\",\"mergeCommit\":null,\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":12}]}]}"
pull_ref 101 "$HD"
sync --check
eq "update-branch merge in the dep: needs-sync, not stale" "$OUT" "12 needs-sync #11 merge"
# …but a merge whose result was edited IS a change to the dependency's work
new_scenario s19
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
commit_on "other" main o.txt other && SQO="$(squash_merge other)"
git -C "$T" checkout -q -B "feature/#11-dep" "origin/feature/#11-dep" \
  && git -C "$T" merge -q --no-commit origin/main >/dev/null; echo edited > "$T/a.txt"
git -C "$T" add a.txt && git -C "$T" commit -qm "merge main (edited)" && git -C "$T" push -q origin "feature/#11-dep"
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"
write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11)\"},\"12\":{\"labels\":[\"guild:done\"]}},
  \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQ\"},\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":11}]},
   {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"main\",\"mergeCommit\":null,\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":12}]}]}"
pull_ref 101 "$HD"
sync --check
eq "edited merge in the dep: stale" "$OUT" "12 stale #11"

# two merged PRs for the dependency (a later hotfix that also closes #11) are not ambiguity
standard s20
commit_on "hotfix" main h.txt hot && SQH="$(squash_merge hotfix)"; HH="$(sha hotfix)"
"$PY" - "$S/state.json" "$HH" "$SQH" <<'EOF'
import json, sys; p, hh, sq = sys.argv[1:]; s = json.load(open(p))
s["prs"].append({"number": 104, "state": "MERGED", "headRefName": "hotfix", "headRefOid": hh,
                 "baseRefName": "main", "mergeCommit": {"oid": sq}, "isDraft": False,
                 "mergedAt": "2026-10-11T00:00:00Z", "closingIssuesReferences": [{"number": 11}]})
json.dump(s, open(p, "w"))
EOF
pull_ref 104 "$HH"
sync --check
eq "two merged dep PRs: the one the member is built on is used" "$OUT" "12 needs-sync #11 merge,retarget,ready"

# the dependency merged another, unmerged branch — not default-branch content
new_scenario s21
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
commit_on "side" main s.txt side
git -C "$T" checkout -q -B "feature/#11-dep" "origin/feature/#11-dep" \
  && git -C "$T" merge -q --no-edit origin/side >/dev/null && git -C "$T" push -q origin "feature/#11-dep"
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"; pull_ref 101 "$HD"
write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11)\"},\"12\":{\"labels\":[\"guild:done\"]}},
  \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQ\"},\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":11}]},
   {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"main\",\"mergeCommit\":null,\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":12}]}]}"
sync --check
eq "dep merged a non-default branch: stale" "$OUT" "12 stale #11"

# the dependency was reverted on main after it landed — syncing would re-land it through #12
standard s22
git -C "$T" fetch -q origin && git -C "$T" checkout -q -B main origin/main \
  && git -C "$T" revert --no-edit HEAD >/dev/null && git -C "$T" push -q origin main
BEFORE="$(sha 'feature/#12-member')"
sync
eq "dep reverted on main: diverged" "$OUT" "12 diverged #11 dep-not-intact-on-main"
eq "dep reverted on main: remote untouched" "$(sha 'feature/#12-member')" "$BEFORE"
eq "dep reverted on main: no gh mutation" "$(cat "$S/calls.txt")" ""

# reverted, then re-landed by another PR without part of it (c.txt) — the member still has it
new_scenario s26
git -C "$T" checkout -q -B "feature/#11-dep" main && echo dep > "$T/a.txt" && echo extra > "$T/c.txt" \
  && git -C "$T" add . && git -C "$T" commit -qm dep && git -C "$T" push -q origin "feature/#11-dep"
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"; pull_ref 101 "$HD"
git -C "$T" revert --no-edit HEAD >/dev/null && git -C "$T" push -q origin main
commit_on "reland" main a.txt dep && SQR="$(squash_merge reland)"; HR="$(sha reland)"; pull_ref 104 "$HR"
write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11)\"},\"12\":{\"labels\":[\"guild:done\"]}},
  \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQ\"},\"isDraft\":false,\"mergedAt\":\"2026-10-10T00:00:00Z\",\"closingIssuesReferences\":[{\"number\":11}]},
   {\"number\":104,\"state\":\"MERGED\",\"headRefName\":\"reland\",\"headRefOid\":\"$HR\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQR\"},\"isDraft\":false,\"mergedAt\":\"2026-10-11T00:00:00Z\",\"closingIssuesReferences\":[{\"number\":11}]},
   {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"main\",\"mergeCommit\":null,\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":12}]}]}"
sync --check
eq "re-landed without part of the dep: diverged" "$OUT" "12 diverged #11 dep-not-intact-on-main"

# re-landed without c.txt AND with a.txt tweaked: the a.txt conflict must not hide the c.txt loss
new_scenario s33
git -C "$T" checkout -q -B "feature/#11-dep" main && printf 'l1\nl2\n' > "$T/a.txt" && echo extra > "$T/c.txt" \
  && git -C "$T" add . && git -C "$T" commit -qm dep && git -C "$T" push -q origin "feature/#11-dep"
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"; pull_ref 101 "$HD"
git -C "$T" revert --no-edit HEAD >/dev/null && git -C "$T" push -q origin main
commit_on "reland" main a.txt "l1
l2-v2" && squash_merge reland >/dev/null
pair_state true
sync --check
eq "conflicting re-land that also dropped a file: still diverged" "$OUT" "12 diverged #11 dep-not-intact-on-main"

# a review fix landed on the dep after the cut, and the dep then landed with a MERGE commit
new_scenario s34
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
commit_on "feature/#11-dep" "feature/#11-dep" a.txt dep-fixed
HD="$(sha 'feature/#11-dep')"; pull_ref 101 "$HD"
git -C "$T" checkout -q -B main origin/main && git -C "$T" merge -q --no-ff -m "Merge dep" "feature/#11-dep" \
  && git -C "$T" push -q origin main && SQ="$(git -C "$T" rev-parse HEAD)"
pair_state true
sync
eq "merge-commit landing after a review fix: stale, not readied" "$OUT" "12 stale #11"
lacks "merge-commit landing after a review fix: no ready call" "$(cat "$S/calls.txt")" "pr ready"

# the human pulled a later review fix of the dep into #12 with an edited conflict resolution
new_scenario s23
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
commit_on "feature/#11-dep" "feature/#11-dep" b.txt dep-touches-b
git -C "$T" checkout -q -B "feature/#12-member" "origin/feature/#12-member"
git -C "$T" merge -q --no-edit "origin/feature/#11-dep" >/dev/null 2>&1   # conflicts on b.txt
echo member-resolved > "$T/b.txt"; git -C "$T" add b.txt && git -C "$T" commit -q --no-edit \
  && git -C "$T" push -q origin "feature/#12-member"
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"; pull_ref 101 "$HD"
write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11)\"},\"12\":{\"labels\":[\"guild:done\"]}},
  \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQ\"},\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":11}]},
   {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"main\",\"mergeCommit\":null,\"isDraft\":true,\"body\":\"$STACK_BODY\",\"closingIssuesReferences\":[{\"number\":12}]}]}"
sync
eq "human's edited catch-up merge: synced but the draft is held" "$OUT" "12 draft-held #11 pr=102"
lacks "human's edited catch-up merge: never readied" "$(cat "$S/calls.txt")" "pr ready"

# the common stack shape: the member edits a file the dependency added — after the squash git's
# own merge base predates that file (add/add); the cut point does not
new_scenario s25
commit_on "feature/#11-dep" main a.txt "l1
l2"
git -C "$T" checkout -q -B "feature/#12-member" "feature/#11-dep" && printf 'l1\nl2-member\n' > "$T/a.txt" \
  && git -C "$T" commit -qam member && git -C "$T" push -q -f origin "feature/#12-member"
commit_on "other" main o.txt other && SQO="$(squash_merge other)"
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"; pull_ref 101 "$HD"
write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11)\"},\"12\":{\"labels\":[\"guild:done\"]}},
  \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQ\"},\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":11}]},
   {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"main\",\"mergeCommit\":null,\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":12}]}]}"
HM12="$(sha 'feature/#12-member')"
sync
eq "member edits the dep's file: synced, no add/add conflict" "$OUT" "12 synced #11 merge"
eq "member edits the dep's file: the PR shows only the member's line" \
  "$(git --git-dir "$O" diff -U0 main..."$(sha 'feature/#12-member')" | grep '^[+-][^+-]' | tr '\n' ' ')" "-l2 +l2-member "
eq "member edits the dep's file: main's other work is in" \
  "$(git --git-dir "$O" show "$(sha 'feature/#12-member'):o.txt")" "other"
P2="$(git --git-dir "$O" show -s --format=%P "$(sha 'feature/#12-member')")"
eq "member edits the dep's file: a real two-parent merge of the member head and main" \
  "$P2" "$HM12 $(sha main)"

# later work on main legitimately edited a line the dependency added — not a revert
new_scenario s27
commit_on "feature/#11-dep" main a.txt "l1
l2"
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"; pull_ref 101 "$HD"
commit_on "followup" main a.txt "l1
l2-followup" && squash_merge followup >/dev/null
pair_state false
sync --check
eq "follow-up edit of the dep's line on main: needs-sync, not diverged" "$OUT" "12 needs-sync #11 merge"

# the member already holds a clean merge of main — not a divergence either
new_scenario s28
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
commit_on "other" main o.txt other && squash_merge other >/dev/null
git -C "$T" checkout -q -B "feature/#12-member" "origin/feature/#12-member" \
  && git -C "$T" merge -q --no-edit origin/main >/dev/null && git -C "$T" push -q origin "feature/#12-member"
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"; pull_ref 101 "$HD"
pair_state false
sync
eq "member holding a clean main merge: synced" "$OUT" "12 synced #11 merge"
eq "member holding a clean main merge: PR shows its own change only" \
  "$(git --git-dir "$O" diff --name-only main..."$(sha 'feature/#12-member')")" "b.txt"

# rebase-merge of a two-commit dependency, then main reverts the FIRST rebased commit
new_scenario s29
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#11-dep" "feature/#11-dep" c.txt dep2
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
HD="$(sha 'feature/#11-dep')"; pull_ref 101 "$HD"
# main must move first: a cherry-pick onto the dep's own parent within the same second recreates
# the identical commit (same SHA) — a fast-forward, not a rebase-merge (flaked as `clean`)
commit_on "other" main o.txt other && squash_merge other >/dev/null
git -C "$T" checkout -q -B main origin/main && git -C "$T" cherry-pick "$HD~1" "$HD" >/dev/null \
  && git -C "$T" push -q origin main && SQ="$(git -C "$T" rev-parse HEAD)"
git -C "$T" revert --no-edit HEAD~1 >/dev/null && git -C "$T" push -q origin main
pair_state false
sync --check
eq "rebase-merge, first commit reverted: diverged" "$OUT" "12 diverged #11 dep-not-intact-on-main"

# a human's CLEAN catch-up merge (no edit) is still not ours to ready
standard s30
git -C "$T" fetch -q origin && git -C "$T" checkout -q -B "feature/#12-member" "origin/feature/#12-member"
git -C "$T" merge -q --no-edit origin/main >/dev/null 2>&1 && git -C "$T" push -q origin "feature/#12-member"
sync
eq "human's clean catch-up: synced by them, draft held for them" "$OUT" "12 draft-held #11 pr=102"
lacks "human's clean catch-up: no ready call" "$(cat "$S/calls.txt")" "pr ready"

# our own sync merged, but `gh pr ready` failed — the re-run readies it
standard s31
OUT="$(cd "$R" && STUB_FAIL_READY=1 STUB_STATE="$S/state.json" STUB_REMOTE="$O" STUB_CALLS="$S/calls.txt" \
       PATH="$WORK/bin:$PATH" "$PY" "$SYNC" --tracker 10 2>/dev/null)"
has "ready failure: reported after the merge" "$OUT" "12 error #11 ready failed after merge+retarget"
sync
eq "ready failure: the re-run readies our own sync" "$OUT" "12 synced #11 ready"

# both merged main after the cut → several merge bases; the member deleted a file the dep added.
# The cut must come from the dep's own line, or the sync silently re-adds the deleted file.
new_scenario s39
git -C "$T" checkout -q -B "feature/#11-dep" main && echo dep > "$T/a.txt" && echo tmp > "$T/tmp.txt" \
  && git -C "$T" add . && git -C "$T" commit -qm dep && git -C "$T" push -q origin "feature/#11-dep"
git -C "$T" checkout -q -B "feature/#12-member" "feature/#11-dep" && git -C "$T" rm -q tmp.txt \
  && echo member > "$T/b.txt" && git -C "$T" add b.txt && git -C "$T" commit -qm member
commit_on "other" main o.txt other && squash_merge other >/dev/null
git -C "$T" checkout -q "feature/#12-member" && git -C "$T" merge -q --no-edit origin/main >/dev/null \
  && git -C "$T" push -q -f origin "feature/#12-member"
git -C "$T" checkout -q -B "feature/#11-dep" "origin/feature/#11-dep" \
  && git -C "$T" merge -q --no-edit origin/main >/dev/null && git -C "$T" push -q origin "feature/#11-dep"
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"; pull_ref 101 "$HD"
pair_state false
sync
eq "several merge bases: synced" "$OUT" "12 synced #11 merge"
eq "several merge bases: the member's deletion survives" \
  "$(git --git-dir "$O" cat-file -e "$(sha 'feature/#12-member'):tmp.txt" 2>/dev/null && echo back || echo gone)" "gone"
eq "several merge bases: the PR shows the member's own change (b.txt added, tmp.txt deleted)" \
  "$(git --git-dir "$O" diff --name-status main..."$(sha 'feature/#12-member')" | tr '\t\n' ': ')" "A:b.txt D:tmp.txt "

# a Guild-Sync merge for ANOTHER dependency does not count as ours for this one
standard s40
git -C "$T" fetch -q origin && git -C "$T" checkout -q -B "feature/#12-member" "origin/feature/#12-member"
git -C "$T" merge -q --no-edit -m "catch up" -m "Guild-Sync: #99" origin/main >/dev/null 2>&1 \
  && git -C "$T" push -q origin "feature/#12-member"
sync --check
eq "Guild-Sync for another dep: the draft is held" "$OUT" "12 needs-sync #11 retarget,held"
standard s42
git -C "$T" fetch -q origin && git -C "$T" checkout -q -B "feature/#12-member" "origin/feature/#12-member"
git -C "$T" merge -q --no-edit -m "catch up" -m "Guild-Sync: #110" origin/main >/dev/null 2>&1 \
  && git -C "$T" push -q origin "feature/#12-member"
sync --check
eq "Guild-Sync #110 is not #11: the draft is held" "$OUT" "12 needs-sync #11 retarget,held"

# a hand-typed Guild-Sync-Base cannot whitelist an edited merge in the dependency
new_scenario s35
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
commit_on "other" main o.txt other && squash_merge other >/dev/null
git -C "$T" checkout -q -B "feature/#11-dep" "origin/feature/#11-dep"
git -C "$T" merge -q --no-commit origin/main >/dev/null; echo sneaky > "$T/a.txt"; git -C "$T" add a.txt
git -C "$T" commit -q -m "merge main" -m "Guild-Sync: #11" -m "Guild-Sync-Base: $(git -C "$T" rev-parse origin/main)" \
  && git -C "$T" push -q origin "feature/#11-dep"
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"; pull_ref 101 "$HD"
pair_state false
sync --check
eq "forged Guild-Sync-Base on an edited merge: stale" "$OUT" "12 stale #11"

# the human merged an unrelated branch into the member — the draft stays held
standard s36
commit_on "side" main s.txt side
git -C "$T" checkout -q -B "feature/#12-member" "origin/feature/#12-member" \
  && git -C "$T" merge -q --no-edit origin/side >/dev/null && git -C "$T" push -q origin "feature/#12-member"
sync
eq "unrelated branch merged into the member: synced, draft held" "$OUT" "12 draft-held #11 pr=102"
has "unrelated branch merged into the member: the merge itself still happened" "$(cat "$S/calls.txt")" "pr edit 102"

# a clean merge of the dep's head into the member (GitHub "Update branch" on the stacked PR) is fine
new_scenario s37
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
commit_on "feature/#11-dep" "feature/#11-dep" c.txt dep-more
git -C "$T" checkout -q -B "feature/#12-member" "origin/feature/#12-member" \
  && git -C "$T" merge -q --no-edit "origin/feature/#11-dep" >/dev/null && git -C "$T" push -q origin "feature/#12-member"
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"; pull_ref 101 "$HD"
pair_state true
sync
eq "update-branch of the member onto its dep: synced and readied" "$OUT" "12 synced #11 merge+ready"

# a crashed earlier sync left its (clean) worktree registered — it is removed and the sync proceeds
standard s38
mkdir -p "$S/.gld-repo-sprint-10" && git -C "$R" fetch -q origin \
  && git -C "$R" worktree add -q --detach "$S/.gld-repo-sprint-10/sync-12" origin/main
sync
eq "leftover clean worktree: recovered" "$OUT" "12 synced #11 merge+retarget+ready"

# two open PRs for the member — which one to sync is a guess
standard s24
"$PY" - "$S/state.json" <<'EOF'
import json, sys; p = sys.argv[1]; s = json.load(open(p))
s["prs"].append(dict(s["prs"][1], number=105, headRefName="feature/#12-retry"))
json.dump(s, open(p, "w"))
EOF
sync --check
eq "two open PRs for the member: ambiguous" "$OUT" "12 ambiguous #11 2-open-prs"

echo "── stack_sync: a two-level stack ──"
new_scenario s10
commit_on "feature/#11-dep" main a.txt dep
commit_on "feature/#12-member" "feature/#11-dep" b.txt member
commit_on "feature/#13-top" "feature/#12-member" c.txt top
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"
TOP_BODY='Closes #13\n<!-- guild:sprint:stack -->\n<!-- /guild:sprint:stack -->'
write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11 13:12)\"},
  \"12\":{\"labels\":[\"guild:done\"]},\"13\":{\"labels\":[\"guild:done\"]}},
  \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQ\"},\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":11}]},
   {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"main\",\"mergeCommit\":null,\"isDraft\":true,\"body\":\"$STACK_BODY\",\"closingIssuesReferences\":[{\"number\":12}]},
   {\"number\":103,\"state\":\"OPEN\",\"headRefName\":\"feature/#13-top\",\"baseRefName\":\"feature/#12-member\",\"mergeCommit\":null,\"isDraft\":true,\"body\":\"$TOP_BODY\",\"closingIssuesReferences\":[{\"number\":13}]}]}"
TOP_BEFORE="$(sha 'feature/#13-top')"
sync
eq "2-level: only the member whose dep merged moves" "$OUT" "12 synced #11 merge+ready"
eq "2-level: the top PR is untouched while its dep is open" "$(sha 'feature/#13-top')" "$TOP_BEFORE"
eq "2-level: the top PR's diff against its base is still its own" \
  "$(git --git-dir "$O" diff --name-only "feature/#12-member"..."feature/#13-top")" "c.txt"
# now the human squash-merges #12 (which holds our sync merge)
HM="$(sha 'feature/#12-member')"; SQ2="$(squash_merge 'feature/#12-member')"
"$PY" - "$S/state.json" "$HM" "$SQ2" <<'EOF'
import json, sys; p, hm, sq = sys.argv[1:]; s = json.load(open(p))
pr = s["prs"][1]; pr.update(state="MERGED", headRefOid=hm, mergeCommit={"oid": sq}, isDraft=False)
json.dump(s, open(p, "w"))
EOF
: > "$S/calls.txt"
sync --check
eq "2-level: our own sync merge does not make the top stale" "$OUT" "13 needs-sync #12 merge,retarget,ready"
sync
eq "2-level: top synced" "$OUT" "13 synced #12 merge+retarget+ready"
eq "2-level: top's diff is its own change only" \
  "$(git --git-dir "$O" diff --name-only main..."$(sha 'feature/#13-top')")" "c.txt"

# the same, when each level edits the file the level below added (the common shape)
new_scenario s32
commit_on "feature/#11-dep" main a.txt "l1
l2
l3"
git -C "$T" checkout -q -B "feature/#12-member" "feature/#11-dep" && printf 'l1\nl2-12\nl3\n' > "$T/a.txt" \
  && git -C "$T" commit -qam m12 && git -C "$T" push -q -f origin "feature/#12-member"
git -C "$T" checkout -q -B "feature/#13-top" "feature/#12-member" && printf 'l1\nl2-12\nl3-13\n' > "$T/a.txt" \
  && git -C "$T" commit -qam m13 && git -C "$T" push -q -f origin "feature/#13-top"
HD="$(sha 'feature/#11-dep')"; SQ="$(squash_merge 'feature/#11-dep')"; pull_ref 101 "$HD"
write_state "{\"issues\":{\"10\":{\"labels\":[\"guild:sprint\"],\"body\":\"$(tracker_body 11:- 12:11 13:12)\"},
  \"12\":{\"labels\":[\"guild:done\"]},\"13\":{\"labels\":[\"guild:done\"]}},
  \"prs\":[{\"number\":101,\"state\":\"MERGED\",\"headRefName\":\"feature/#11-dep\",\"headRefOid\":\"$HD\",\"baseRefName\":\"main\",\"mergeCommit\":{\"oid\":\"$SQ\"},\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":11}]},
   {\"number\":102,\"state\":\"OPEN\",\"headRefName\":\"feature/#12-member\",\"baseRefName\":\"main\",\"mergeCommit\":null,\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":12}]},
   {\"number\":103,\"state\":\"OPEN\",\"headRefName\":\"feature/#13-top\",\"baseRefName\":\"feature/#12-member\",\"mergeCommit\":null,\"isDraft\":false,\"closingIssuesReferences\":[{\"number\":13}]}]}"
sync
eq "2-level, shared file: middle synced" "$OUT" "12 synced #11 merge"
HM="$(sha 'feature/#12-member')"; pull_ref 102 "$HM"; SQ2="$(squash_merge 'feature/#12-member')"
"$PY" - "$S/state.json" "$HM" "$SQ2" <<'EOF'
import json, sys; p, hm, sq = sys.argv[1:]; s = json.load(open(p))
s["prs"][1].update(state="MERGED", headRefOid=hm, mergeCommit={"oid": sq}); json.dump(s, open(p, "w"))
EOF
sync
eq "2-level, shared file: our own cut-point merge does not make the top stale" "$OUT" "13 synced #12 merge+retarget"
eq "2-level, shared file: top's PR shows only its own line" \
  "$(git --git-dir "$O" diff -U0 main..."$(sha 'feature/#13-top')" | grep '^[+-][^+-]' | tr '\n' ' ')" "-l3 +l3-13 "

echo "── stack_sync: input guards ──"
standard s11
sync --install-cmd 'npm ci && rm -rf /'
eq "install-cmd with a metacharacter: refused (64)" "$RC" "64"
"$PY" - "$S/state.json" <<'EOF'
import json, sys; p = sys.argv[1]; s = json.load(open(p)); s["issues"]["10"]["labels"] = []; json.dump(s, open(p, "w"))
EOF
sync --check
eq "not a sprint tracker: refused (64)" "$RC" "64"
printf '{"commands":{"test":null,"lint":null}}\n' > "$R/.claude/guild/config.json"
"$PY" - "$S/state.json" <<'EOF'
import json, sys; p = sys.argv[1]; s = json.load(open(p)); s["issues"]["10"]["labels"] = ["guild:sprint"]; json.dump(s, open(p, "w"))
EOF
sync
eq "no verification command: refused (64) rather than pushing unverified" "$RC" "64"
sync --check
eq "no verification command: --check still works" "$RC" "0"

M1="$("$PY" -c "import sys; sys.dont_write_bytecode=True; sys.path.insert(0, '$(dirname "$SYNC")'); import stack_sync; print(stack_sync._METACHAR.pattern)")"
M2="$("$PY" -c "import sys; sys.path.insert(0, '$(dirname "$RENDER")'); sys.dont_write_bytecode=True; import render_supervisor; print(render_supervisor._METACHAR.pattern)")"
eq "the metacharacter class is the renderer's (init.md:163)" "$M1" "$M2"

echo "── supervisor wiring (run.md --draft-stacked) ──"
RH="$WORK/render"; mkdir -p "$RH"
rflags() { echo --tracker 99 --owner-repo acme/app --default-branch main --container "$RH/c" \
  --human-repo "$RH" --dag-path /x/sprint_dag.py --out -; }
eq "render: --draft-stacked → DRAFT_STACKED=1" \
  "$("$PY" "$RENDER" $(rflags) --draft-stacked 2>/dev/null | grep -m1 '^DRAFT_STACKED=')" "DRAFT_STACKED=1"
eq "render: default → DRAFT_STACKED=0" \
  "$("$PY" "$RENDER" $(rflags) 2>/dev/null | grep -m1 '^DRAFT_STACKED=')" "DRAFT_STACKED=0"
TPL="$("$PY" "$RENDER" --print-template-path)"
has "template: a draft only for a stack base, never for the default branch" "$(cat "$TPL")" \
  'if [ "$DRAFT_STACKED" = 1 ] && [ "$BASE_REF" != "origin/$DEFAULT_BRANCH" ]; then SPRINT_DRAFT=1; fi'
has "template: the child receives GLD_SPRINT_DRAFT" "$(cat "$TPL")" 'GLD_SPRINT_DRAFT="$SPRINT_DRAFT"'
# Only OUR module: other suites import their own, and a shared directory check would blame this one.
PYC="$(ls "$(dirname "$SYNC")"/__pycache__/stack_sync.* 2>/dev/null)"
[ -z "$PYC" ] && ok "no stack_sync .pyc written beside the plugin's scripts" || bad "pycache" "$PYC"

echo
echo "stack_sync: $PASS passed, $FAIL failed"
# ⚠ Keep equal to the measured PASS count; raise it only when checks are added on purpose. A
#   quote that swallows the rest of the file runs fewer checks and still ends green otherwise.
SYNC_MIN_CHECKS=112
if [ "$((PASS + FAIL))" -lt "$SYNC_MIN_CHECKS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${SYNC_MIN_CHECKS}건)."
  exit 1
fi
[ "$FAIL" -eq 0 ]
