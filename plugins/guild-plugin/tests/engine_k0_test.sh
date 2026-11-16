#!/usr/bin/env bash
# Verification for the issue-flow engine, milestone K0 — the read-only platform
# (design: design/guild/23-engine/design.md §2.0, §2.5, §2.10, §6, §10.1 K0).
#
# Runs the Python unittest suite under tests/engine/:
#   • golden-fixture round-trip: every record kind (labels, loopback, needs-human, followups,
#     manual-qa, auditor:execute/violation, stage outputs, decision log) parses and renders back
#     byte for byte — real sprint-log records 0.82.4–0.99.2 (sanitized) and 0.101.0 prose shapes;
#     engine-rendered shapes (§6.2 C1/C2/C4/C12/C13/C14) are pinned under fixtures/engine/rendered.
#   • consumer contracts: the jq/grep/bash readers EXTRACTED from the live prose (Section A,
#     status.md, monitoring.md, daily.md, retro.md, Section M, the supervisor's stage_of /
#     loopback_mark / split_head_needs_human / RL_LAST, batch's case arms) agree with the engine.
#   • status output comparison: status.md's own examples verbatim, pinned outputs per fixture
#     Issue, resume routing order, the monitoring board, the CLI entry point.
#   • K0 is inert: nothing in the plugin calls the engine; the gh adapter refuses writes; tests
#     run with a `gh` that always fails first on PATH (no network).
#
# Usage: bash plugins/guild-plugin/tests/engine_k0_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE="$HERE/../skills/gld/engine/gld_engine.py"
[ -f "$ENGINE" ] || { echo "missing: $ENGINE" >&2; exit 1; }
PY="${PY:-python3}"

gld_skip() { echo "SKIP: $1" >&2; [ "${GLD_ALLOW_SKIP:-0}" = 1 ] && exit 0; \
            echo "FAIL  스킵은 통과가 아닙니다 — GLD_ALLOW_SKIP=1 로 명시하십시오." >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null \
  || gld_skip "$PY is not Python 3.9+ — the engine's floor"
command -v jq >/dev/null 2>&1 || gld_skip "jq is not installed — the consumer-contract tests replay jq readers"

WORK="$(mktemp -d)" || { echo "mktemp -d failed" >&2; exit 1; }
trap 'rm -rf "$WORK"' EXIT
OUT="$WORK/unittest.out"
( cd "$HERE/engine" && PYTHONDONTWRITEBYTECODE=1 TMPDIR="$WORK" "$PY" -m unittest discover -s . -p 'test_*.py' -v ) >"$OUT" 2>&1
RC=$?
grep -E '\.\.\. (ok|FAIL|ERROR|skipped)' "$OUT" | sed -E 's/^(.*) \.\.\. ok$/  PASS  \1/; s/^(.*) \.\.\. (FAIL|ERROR)$/  FAIL  \1/; s/^(.*) \.\.\. skipped.*$/  SKIP  \1/'
PASS=$(grep -cE '\.\.\. ok$' "$OUT")
FAIL=$(grep -cE '\.\.\. (FAIL|ERROR)$' "$OUT")
if [ "$RC" -ne 0 ]; then
  sed -n '/^======/,$p' "$OUT"
fi
echo "engine K0: $PASS passed, $FAIL failed"
# ⚠ Keep equal to the measured PASS count; raise it only when tests are added on purpose. A
#   test module that fails to import is reported as one ERROR, not as its N missing tests.
ENGINE_K0_MIN_TESTS=132
if [ "$((PASS + FAIL))" -lt "$ENGINE_K0_MIN_TESTS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${ENGINE_K0_MIN_TESTS}건)."
  exit 1
fi
[ "$RC" -eq 0 ] && [ "$FAIL" -eq 0 ]
