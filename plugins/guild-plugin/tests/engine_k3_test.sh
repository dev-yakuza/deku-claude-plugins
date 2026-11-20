#!/usr/bin/env bash
# Verification for the issue-flow engine, milestone K3 — the execute stage
# (design: design/guild/23-engine/design.md §3.3 EX-ARB, §3.4, §4.2, §5.1, §6.2 C1–C2, §10.1 K3, §10.2-2).
#
# Runs the Python unittest modules tests/engine/test_k3_*.py:
#   • Step 4 as code (exec_audit): severity policy, MAJOR budget, cap, re-statement (`fixed` /
#     `looped-back` / `recorded`, never `fixed` on `scan: none`), unattended BLOCKER never dismissed,
#     carry-forward (D-4.4), finding identity (IDENT, C2 ids), stagnation (both axes, timeouts),
#     EX-ARB quote coercion, the PR auditor section (D-5.5), retro counts;
#   • the auditor tripwire D-M1–D-M7 and the refactor Safety net D-R1–D-R9 on real git repos, plus the
#     §5.1 refactor-net scope fixture (R7C-M1: cleanup before the scope check, BRANCH not SCOPE);
#   • the execute stage end to end (real temp worktree, fake GitHub): advance, retry with tier bump,
#     stagnation, cap, gate INV2, auditor mutation + violation guard, gate-config guard, disputes,
#     loop-back `consumed:` + audit `loopback: <n>` + handoff.execute_to_test, PR create/splice, push
#     divergence, env halts, deps-before-suite, debug red→green, refactor net block;
#   • the K2 carry-overs: gate config from base (GUILD_GATE_CONFIG), PGP keys, engine push hooks off,
#     worktrees outside $TMPDIR + copy_ignored, the networked steps' read allowlist (real sandbox-exec),
#     build*.yaml under build_runner, the machine-report loading detector (K2r8-m1).
# No test calls `claude`, a model or GitHub (a failing `gh` is first on PATH).
#
# Usage: bash plugins/guild-plugin/tests/engine_k3_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE="$HERE/../skills/gld/engine/gld_engine.py"
[ -f "$ENGINE" ] || { echo "missing: $ENGINE" >&2; exit 1; }
PY="${PY:-python3}"

gld_skip() { echo "SKIP: $1" >&2; [ "${GLD_ALLOW_SKIP:-0}" = 1 ] && exit 0; \
            echo "FAIL  스킵은 통과가 아닙니다 — GLD_ALLOW_SKIP=1 로 명시하십시오." >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null \
  || gld_skip "$PY is not Python 3.9+ — the engine's floor"
command -v git >/dev/null 2>&1 || gld_skip "git is not installed"

WORK="$(mktemp -d)" || { echo "mktemp -d failed" >&2; exit 1; }
trap 'chmod -R u+w "$WORK" 2>/dev/null; rm -rf "$WORK"' EXIT
OUT="$WORK/unittest.out"
( cd "$HERE/engine" && PYTHONDONTWRITEBYTECODE=1 TMPDIR="$WORK" "$PY" -W ignore::ResourceWarning \
    -m unittest discover -s . -p 'test_k3_*.py' -v ) >"$OUT" 2>&1
RC=$?
grep -E '\.\.\. (ok|FAIL|ERROR|skipped)' "$OUT" | sed -E 's/^(.*) \.\.\. ok$/  PASS  \1/; s/^(.*) \.\.\. (FAIL|ERROR)$/  FAIL  \1/; s/^(.*) \.\.\. skipped.*$/  SKIP  \1/'
if [ "$RC" -ne 0 ]; then
  sed -n '/^======/,$p' "$OUT"
fi
# review-k6-r10 m3: count from unittest's own summary — `Ran N` minus the skipped tests (a skip is not a pass), and the
# failures + errors of its `FAILED (...)` line. A line a test splits by printing mid-line (r9: a SyntaxWarning, a
# thread's traceback) no longer drops a test from the count, and a test turned into a skip lowers it.
RAN=$(sed -nE 's/^Ran ([0-9]+) tests? in .*/\1/p' "$OUT" | tail -1); RAN=${RAN:-0}
SUMMARY=$(grep -E '^(OK|FAILED)( \(.*\))?$' "$OUT" | tail -1)
SKIPPED=$(printf '%s' "$SUMMARY" | sed -nE 's/.*[(, ]skipped=([0-9]+).*/\1/p'); SKIPPED=${SKIPPED:-0}
FAILURES=$(printf '%s' "$SUMMARY" | sed -nE 's/.*[(, ]failures=([0-9]+).*/\1/p'); FAILURES=${FAILURES:-0}
ERRORS=$(printf '%s' "$SUMMARY" | sed -nE 's/.*[(, ]errors=([0-9]+).*/\1/p'); ERRORS=${ERRORS:-0}
COUNTED=$((RAN - SKIPPED))
FAIL=$((FAILURES + ERRORS))
PASS=$((COUNTED - FAIL))
[ -n "$SUMMARY" ] || { FAIL=$((FAIL + 1)); echo "FAIL  unittest 요약 줄(OK / FAILED)이 없습니다."; }
echo "engine K3: $PASS passed, $FAIL failed (ran $RAN, skipped $SKIPPED)"
# ⚠ Keep equal to the measured count (ran − skipped); raise it only when tests are added on purpose.
ENGINE_K3_MIN_TESTS=188
if [ "$COUNTED" -lt "$ENGINE_K3_MIN_TESTS" ]; then
  echo "FAIL  실행된 검사가 ${COUNTED}건뿐입니다 (스킵 제외, 최소 ${ENGINE_K3_MIN_TESTS}건)."
  exit 1
fi
[ "$RC" -eq 0 ] && [ "$FAIL" -eq 0 ]
