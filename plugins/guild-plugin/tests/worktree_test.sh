#!/usr/bin/env bash
# Verification for the git-worktree mechanics the sprint design RESTS ON (design: 02-sprint.md
# §8.1a · §8.1b · §12.3).
#
# Why this file exists: §8.1b's safety argument is not a code path — it is a set of claims
# about how `git worktree` and `.gitignore` behave. Every one of them was established by
# measurement during design, and every one is invisible to the other suites: they read the
# supervisor's TEXT, not git's behaviour. If a future git changes any of these, the supervisor
# keeps passing every structural check while silently deleting the human's growth signals.
#
# The single most important case is D2: `git worktree remove` must NOT follow the `memory`
# SYMLINK. If it ever does, an unattended sprint destroys the human's accumulated
# ground-truth — the exact loss §8.1b's symlink exists to prevent, and it happens with exit 0.
#
# Nothing here touches the plugin or the user's repos: every case builds its own repo under
# `mktemp -d`. No network.
#
# Usage: bash plugins/guild-plugin/tests/worktree_test.sh
set -uo pipefail
# ⚠ REALPATH, not the raw mktemp path. `git worktree list --porcelain` prints realpaths
# (case A proves it), and on macOS `mktemp -d` returns `/var/folders/...` whose realpath is
# `/private/var/folders/...`. Section F compared a raw path against that listing, so its
# "still registered?" count was ALWAYS 0 and the assertion could not fail — deleting the
# `worktree prune` call under test still gave 16/16 (measured).
#
# ⚠⚠ AND THE NORMALISATION MUST BE GUARDED, because the trap below is `rm -rf "$WORK"`.
# `WORK="$(cd "$(mktemp -d)" && pwd -P)"` was measured to be DESTRUCTIVE: in bash `cd ""`
# SUCCEEDS and stays put, so a failing `mktemp -d` (read-only /tmp, a bad TMPDIR, quota) made
# WORK the CURRENT DIRECTORY — and the trap then ran `chmod -R u+w .; rm -rf .` on the repo the
# suite was invoked from, while still printing "19 passed, 0 failed". Never let an unguarded
# command substitution feed an `rm -rf`.
WORK="$(mktemp -d)" || { echo "mktemp -d failed" >&2; exit 1; }
[ -n "$WORK" ] && [ -d "$WORK" ] || { echo "mktemp -d gave no directory" >&2; exit 1; }
WORK_REAL="$(cd "$WORK" && pwd -P)" || { echo "cannot resolve $WORK" >&2; exit 1; }
case "$WORK_REAL" in
  /*/*) WORK="$WORK_REAL" ;;                      # a plausible temp path
  *) echo "refusing to use [$WORK_REAL] as a scratch dir" >&2; exit 1 ;;
esac
# Last line of defence: never point the trap at a directory that is not ours.
if [ "$WORK" = "/" ] || [ "$WORK" = "$HOME" ] || [ "$WORK" = "$(pwd -P)" ]; then
  echo "refusing to rm -rf [$WORK]" >&2; exit 1
fi
trap 'chmod -R u+w "$WORK" 2>/dev/null; rm -rf "$WORK"' EXIT
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
command -v "$PY" >/dev/null 2>&1 || { echo "SKIP: $PY not on PATH — this suite needs it for nothing yet, but keep the contract uniform" >&2; exit 0; }
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s — %s\n' "$1" "$2"; }

command -v git >/dev/null 2>&1 || { echo "git not available — cannot verify anything here" >&2; exit 1; }
echo "git $(git --version | awk '{print $3}')"

# newrepo <name> — a repo with one commit on `develop` and a `.gitignore` carrying `memory/`,
# which is exactly the shape `/gld init` leaves behind.
newrepo() {
  local d="$WORK/$1"
  mkdir -p "$d"
  git -C "$d" init -q -b develop 2>/dev/null || { git -C "$d" init -q; git -C "$d" symbolic-ref HEAD refs/heads/develop; }
  git -C "$d" config user.email t@example.invalid
  git -C "$d" config user.name  tester
  # ⚠ Pin hooksPath LOCALLY. A global `core.hooksPath` (lefthook, husky, pre-commit — this very
  # project uses one) makes git ignore `.git/hooks`, and section G then reported "the gate did
  # not run, so an unattended sprint commits past it" — a false and alarming conclusion about
  # the caller's machine (measured: 3 of 19 failed).
  # ABSOLUTE, not `.git/hooks`: a relative hooksPath is resolved against the CWD, so from a
  # LINKED worktree it points at that worktree's own (nonexistent) `.git/hooks` and the hook
  # never runs — measured, 3 of 19 failed with the same alarming message as the global-override
  # case this line exists to defeat.
  git -C "$d" config core.hooksPath "$d/.git/hooks"
  # ⚠ And the directory may not exist: a global `init.templateDir` pointing at an empty template
  # leaves `.git/hooks` absent, and `cat > .../pre-commit` then failed silently (no `set -e`).
  mkdir -p "$d/.git/hooks"
  mkdir -p "$d/.claude/guild"
  printf 'memory/\n' > "$d/.claude/guild/.gitignore"
  printf 'x\n' > "$d/src.txt"
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" commit -qm init >/dev/null 2>&1
  printf '%s' "$d"
}

echo "== A. worktree topology =="

R="$(newrepo a)"
git -C "$R" worktree add --detach -q "$WORK/a_wt1" develop 2>/dev/null
git -C "$WORK/a_wt1" worktree add --detach -q "$WORK/a_wt1/nested" develop 2>/dev/null
N="$(git -C "$R" worktree list --porcelain | grep -c '^worktree ')"
if [ "$N" -eq 3 ]; then
  ok "worktrees are FLAT: a worktree created from a worktree registers in the same repo (3 entries)"
else
  bad "worktrees are FLAT" "expected 3 registrations in the one repo, got $N"
fi

# The design's container is one flat directory of sibling worktrees BECAUSE of the above: a
# "worktree of a worktree" is not a child, so nesting buys nothing and costs a confusing path.
OUT="$(git -C "$R" worktree add --detach "$WORK/a_wt2" develop 2>&1)"
if printf '%s' "$OUT" | grep -q 'HEAD is now at'; then
  ok "\`worktree add\` prints 'HEAD is now at …' on STDOUT (why the supervisor redirects it)"
else
  bad "\`worktree add\` prints 'HEAD is now at …' on STDOUT" "got: $(printf '%s' "$OUT" | head -1)"
fi

OUT="$(git -C "$R" worktree add "$WORK/a_wt3" develop 2>&1)"; RC=$?
if [ "$RC" -ne 0 ] && printf '%s' "$OUT" | grep -qi 'already used by worktree'; then
  ok "a branch lives in AT MOST ONE worktree (hence --detach for the supervisor's own)"
else
  bad "a branch lives in at most one worktree" "rc=$RC out=$(printf '%s' "$OUT" | head -1)"
fi

LP="$(git -C "$R" worktree list --porcelain | sed -n 's/^worktree //p' | sed -n 2p)"
RP="$(cd "$WORK/a_wt1" && pwd -P)"
if [ "$LP" = "$RP" ]; then
  ok "\`worktree list --porcelain\` prints REALPATHs (why \$CONTAINER is normalised once)"
else
  bad "\`worktree list --porcelain\` prints REALPATHs" "list=[$LP] realpath=[$RP]"
fi

echo "== B. removal refuses to destroy work =="

R="$(newrepo b)"
git -C "$R" worktree add --detach -q "$WORK/b_wt" develop 2>/dev/null
printf 'uncommitted source\n' > "$WORK/b_wt/src.txt"
OUT="$(git -C "$R" worktree remove "$WORK/b_wt" 2>&1)"; RC=$?
if [ "$RC" -ne 0 ] && [ -f "$WORK/b_wt/src.txt" ]; then
  ok "removal REFUSES a worktree with modified tracked files (git's refusal IS the safety net)"
else
  bad "removal refuses a worktree with modified tracked files" "rc=$RC — the file is gone: this is INV3 territory"
fi

git -C "$WORK/b_wt" checkout -q -- src.txt 2>/dev/null
printf 'untracked doc\n' > "$WORK/b_wt/NOTES.md"
OUT="$(git -C "$R" worktree remove "$WORK/b_wt" 2>&1)"; RC=$?
if [ "$RC" -ne 0 ]; then
  ok "removal refuses for UNTRACKED files too (the tech-writer-ADR case \`daily\` must explain)"
else
  bad "removal refuses for untracked files too" "it removed the worktree, losing the untracked file"
fi

rm -f "$WORK/b_wt/NOTES.md"
git -C "$R" worktree remove "$WORK/b_wt" 2>/dev/null; RC=$?
if [ "$RC" -eq 0 ] && [ ! -d "$WORK/b_wt" ]; then
  ok "removal SUCCEEDS once the tree is clean"
else
  bad "removal succeeds once the tree is clean" "rc=$RC"
fi

echo "== C. a gitignored directory is deleted SILENTLY — the whole reason for the symlink =="

R="$(newrepo c)"
git -C "$R" worktree add --detach -q "$WORK/c_wt" develop 2>/dev/null
mkdir -p "$WORK/c_wt/.claude/guild/memory"
printf '{"signal":1}\n' > "$WORK/c_wt/.claude/guild/memory/ground-truth.jsonl"
IGN="$(git -C "$WORK/c_wt" check-ignore .claude/guild/memory 2>/dev/null; echo "rc=$?")"
git -C "$R" worktree remove "$WORK/c_wt" 2>/dev/null; RC=$?
if [ "$RC" -eq 0 ] && [ ! -e "$WORK/c_wt" ]; then
  ok "a gitignored dir does NOT block removal and is deleted with exit 0 ($IGN) — silent data loss"
else
  bad "a gitignored dir does not block removal" "rc=$RC — if this now refuses, §8.1b's symlink rationale changed"
fi

echo "== D. the symlink defence =="

R="$(newrepo d)"
mkdir -p "$R/.claude/guild/memory"
printf '{"signal":"human"}\n' > "$R/.claude/guild/memory/ground-truth.jsonl"
git -C "$R" worktree add --detach -q "$WORK/d_wt" develop 2>/dev/null
mkdir -p "$WORK/d_wt/.claude/guild"
ln -s "$R/.claude/guild/memory" "$WORK/d_wt/.claude/guild/memory"

# D1 — `.gitignore`'s `memory/` is a DIRECTORY pattern and does not match a SYMLINK. This is
# why `info/exclude` registration is mandatory: without it the symlink shows as untracked, the
# worktree is dirty, removal is refused, and NO worktree is ever released.
git -C "$WORK/d_wt" check-ignore -q .claude/guild/memory 2>/dev/null; ICG=$?
ST="$(git -C "$WORK/d_wt" status --porcelain 2>/dev/null)"
if [ "$ICG" -ne 0 ] && printf '%s' "$ST" | grep -q 'memory'; then
  ok "\`memory/\` (a directory pattern) does NOT match the symlink — info/exclude is REQUIRED"
else
  bad "\`memory/\` does not match the symlink" "check-ignore rc=$ICG status=[$ST] — if this now matches, the info/exclude step is dead code"
fi

EXC="$(git -C "$R" rev-parse --git-path info/exclude)"
case "$EXC" in /*) ;; *) EXC="$R/$EXC" ;; esac
if [ "$EXC" = "$R/.git/info/exclude" ]; then
  ok "\`rev-parse --git-path\` returns a REPO-RELATIVE path (why the supervisor absolutises it)"
else
  bad "\`rev-parse --git-path\` returns a repo-relative path" "got [$EXC]"
fi
mkdir -p "$(dirname "$EXC")"; printf '.claude/guild/memory\n' >> "$EXC"

# D2 — THE case. Removal must not follow the link.
git -C "$R" worktree remove "$WORK/d_wt" 2>"$WORK/d.err"; RC=$?
if [ "$RC" -eq 0 ] && [ ! -e "$WORK/d_wt" ] \
   && [ -f "$R/.claude/guild/memory/ground-truth.jsonl" ]; then
  ok "★ \`worktree remove\` does NOT follow the memory symlink — the human's signals survive"
else
  bad "★ \`worktree remove\` does NOT follow the memory symlink" \
      "rc=$RC target-exists=$([ -f "$R/.claude/guild/memory/ground-truth.jsonl" ] && echo yes || echo NO) err=$(head -1 "$WORK/d.err" 2>/dev/null) — an unattended sprint would DESTROY the human's growth data"
fi

# D3 — and writes THROUGH the link land in the human's copy, which is the point of doing this.
git -C "$R" worktree add --detach -q "$WORK/d_wt2" develop 2>/dev/null
mkdir -p "$WORK/d_wt2/.claude/guild"
ln -s "$R/.claude/guild/memory" "$WORK/d_wt2/.claude/guild/memory"
printf '{"signal":"from-worktree"}\n' >> "$WORK/d_wt2/.claude/guild/memory/ground-truth.jsonl"
if grep -q 'from-worktree' "$R/.claude/guild/memory/ground-truth.jsonl"; then
  ok "a write through the link lands in the human's copy (so evolve sees the sprint's signals)"
else
  bad "a write through the link lands in the human's copy" "the append did not reach the target"
fi

echo "== E. fetching a base without touching the human's branches =="

R="$(newrepo e)"
git -C "$WORK" init -q --bare e_origin.git
git -C "$R" remote add origin "$WORK/e_origin.git"
git -C "$R" push -q -u origin develop 2>/dev/null
git -C "$R" worktree add --detach -q "$WORK/e_sup" develop 2>/dev/null

OUT="$(git -C "$WORK/e_sup" fetch origin "develop:develop" 2>&1)"; RC=$?
if [ "$RC" -ne 0 ] && printf '%s' "$OUT" | grep -qi 'refusing to fetch\|checked out at'; then
  ok "\`fetch origin <b>:<b>\` is REFUSED while <b> is checked out anywhere (even elsewhere)"
else
  bad "\`fetch origin <b>:<b>\` is refused while <b> is checked out" "rc=$RC out=$(printf '%s' "$OUT" | head -1)"
fi

BEFORE="$(git -C "$R" rev-parse develop)"
git -C "$WORK/e_sup" fetch -q origin "develop:refs/remotes/origin/develop" 2>/dev/null; RC=$?
AFTER="$(git -C "$R" rev-parse develop)"
if [ "$RC" -eq 0 ] && [ "$BEFORE" = "$AFTER" ]; then
  ok "fetching into refs/remotes/ SUCCEEDS and leaves the human's local branch untouched"
else
  bad "fetching into refs/remotes/ succeeds without touching the local branch" "rc=$RC before=$BEFORE after=$AFTER"
fi

echo "== F. \`worktree prune\` is repo-global (why prune_safe exists) =="

R="$(newrepo f)"
git -C "$R" worktree add --detach -q "$WORK/f_human_side" develop 2>/dev/null
git -C "$R" worktree add --detach -q "$WORK/f_container/issue-101" develop 2>/dev/null
mv "$WORK/f_human_side" "$WORK/f_moved_away"          # the human moved their own worktree
PRUNABLE="$(git -C "$R" worktree list --porcelain | grep -c '^prunable')"
git -C "$R" worktree prune 2>/dev/null
STILL="$(git -C "$R" worktree list --porcelain | grep -c "^worktree $WORK/f_human_side\$")"
if [ "$PRUNABLE" -ge 1 ] && [ "$STILL" -eq 0 ]; then
  ok "\`worktree prune\` drops an UNRELATED worktree's registration — it takes no path argument"
else
  bad "\`worktree prune\` drops an unrelated worktree's registration" \
      "prunable=$PRUNABLE still-registered=$STILL — if prune became scoped, prune_safe can be simplified"
fi
if [ -d "$WORK/f_moved_away" ]; then
  ok "…the directory itself survives as an orphan (recoverable, but the human must notice)"
else
  bad "the moved directory survives" "prune deleted it"
fi

echo "== G. INV2 — the commit gate FIRES inside an issue worktree =="
# §11 claims INV2 holds because "게이트 스크립트·rules·config는 추적 파일이므로 워크트리에 존재하고
# … 워크트리에서도 정상 발화한다". That was the one invariant with NO mechanical evidence: §0.4
# withdrew the install_test.sh extension saying `gate_test.sh` covers hook firing, but
# `grep -c worktree tests/gate_test.sh` is 0 — it never makes a worktree. Every commit an
# unattended sprint produces happens in a worktree, so this is the half that was untested.
#
# What is checked here is git's behaviour, not the gate's rules (gate_test.sh owns those): a
# linked worktree must resolve `hooks` to the COMMON dir and must actually run pre-commit.

R="$(newrepo g)"
# ⚠ The hook leaves a WITNESS FILE. "the commit count did not go up" is not evidence that the
# hook ran — nothing staged, no user.email, a bad index all produce the same count, and removing
# the hook entirely still gave 19/19 (measured). The witness is what distinguishes "blocked by
# the gate" from "failed for some other reason".
cat > "$R/.git/hooks/pre-commit" <<'HOOK'
#!/bin/sh
echo ran >> "$(git rev-parse --git-common-dir)/hook-ran"
if grep -q FORBIDDEN "$(git rev-parse --show-toplevel)/src.txt" 2>/dev/null; then
  echo "gate: refusing" >&2
  exit 1
fi
exit 0
HOOK
chmod +x "$R/.git/hooks/pre-commit"
git -C "$R" worktree add --detach -q "$WORK/g_wt" develop 2>/dev/null

HP="$(git -C "$WORK/g_wt" rev-parse --git-path hooks)"
if [ "$HP" = "$R/.git/hooks" ]; then
  ok "a linked worktree resolves \`hooks\` to the COMMON dir (so the installed gate is reachable)"
else
  bad "a linked worktree resolves hooks to the common dir" "expected $R/.git/hooks, got $HP"
fi

printf 'FORBIDDEN\n' > "$WORK/g_wt/src.txt"
git -C "$WORK/g_wt" add -A >/dev/null 2>&1
git -C "$WORK/g_wt" commit -qm "should be blocked" >/dev/null 2>&1
N="$(git -C "$WORK/g_wt" log --oneline 2>/dev/null | grep -c . || true)"
RAN="$(grep -c . "$R/.git/hook-ran" 2>/dev/null || echo 0)"
if [ "$N" = "1" ] && [ "$RAN" -ge 1 ]; then
  ok "★ pre-commit FIRES in the worktree and blocks the commit (INV2's untested half)"
elif [ "$RAN" -lt 1 ]; then
  bad "★ pre-commit fires in the worktree" \
      "the hook left no witness — it never ran (commit count $N says nothing on its own)"
else
  bad "★ pre-commit blocks the commit in the worktree" "the hook ran but $N commits landed"
fi

printf 'clean\n' > "$WORK/g_wt/src.txt"
git -C "$WORK/g_wt" add -A >/dev/null 2>&1
git -C "$WORK/g_wt" commit -qm "should pass" >/dev/null 2>&1
N2="$(git -C "$WORK/g_wt" log --oneline 2>/dev/null | grep -c . || true)"
if [ "$N2" = "2" ]; then
  ok "…and a clean commit still goes through (the hook is not blocking everything)"
else
  bad "a clean commit still goes through" "$N2 commits — the control case failed"
fi

# The honest limit, stated: `.git/hooks/` does not survive a clone (_invariants.md says so), and
# a worktree of a FRESH clone therefore has no gate. That is the fail-open case install_test.sh
# section D already covers; it is not a worktree property.

echo
printf 'worktree: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
