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
# Usage: bash plugins/guild-plugin/tests/engine_k2_test.sh
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
PASS=$(grep -cE '\.\.\. ok$' "$OUT")
FAIL=$(grep -cE '\.\.\. (FAIL|ERROR)$' "$OUT")
if [ "$RC" -ne 0 ]; then
  sed -n '/^======/,$p' "$OUT"
fi
echo "engine K3: $PASS passed, $FAIL failed"
# ⚠ Keep equal to the measured PASS count; raise it only when tests are added on purpose.
ENGINE_K3_MIN_TESTS=150
if [ "$((PASS + FAIL))" -lt "$ENGINE_K3_MIN_TESTS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${ENGINE_K3_MIN_TESTS}건)."
  exit 1
fi
[ "$RC" -eq 0 ] && [ "$FAIL" -eq 0 ]
