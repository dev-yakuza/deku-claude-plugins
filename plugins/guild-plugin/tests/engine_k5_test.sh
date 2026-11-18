#!/usr/bin/env bash
# Verification for the issue-flow engine, milestone K5 — the supervisor, the driver and the commands
# (design: design/guild/23-engine/design.md §2.4, §2.5, §2.7, §2.10, §9.5, §9.6, §10.1 K5, §10.3–§10.5).
#
# Runs the Python unittest modules tests/engine/test_k5_*.py:
#   • carry-overs from the K4 review (test_k5_carry.py): deleted / transferred children on the design resume,
#     the parent row as the transfer reference, orphan candidates, the unclosed fence, the restart check;
#   • see k5-notes.md for the full list.
# No test calls `claude`, a model or GitHub (a failing `gh` is first on PATH).
#
# Usage: bash plugins/guild-plugin/tests/engine_k4_test.sh
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
    -m unittest discover -s . -p 'test_k5_*.py' -v ) >"$OUT" 2>&1
RC=$?
grep -E '\.\.\. (ok|FAIL|ERROR|skipped)' "$OUT" | sed -E 's/^(.*) \.\.\. ok$/  PASS  \1/; s/^(.*) \.\.\. (FAIL|ERROR)$/  FAIL  \1/; s/^(.*) \.\.\. skipped.*$/  SKIP  \1/'
PASS=$(grep -cE '\.\.\. ok$' "$OUT")
FAIL=$(grep -cE '\.\.\. (FAIL|ERROR)$' "$OUT")
if [ "$RC" -ne 0 ]; then
  sed -n '/^======/,$p' "$OUT"
fi
echo "engine K5: $PASS passed, $FAIL failed"
# ⚠ Keep equal to the measured PASS count; raise it only when tests are added on purpose.
ENGINE_K5_MIN_TESTS=16
if [ "$((PASS + FAIL))" -lt "$ENGINE_K5_MIN_TESTS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${ENGINE_K5_MIN_TESTS}건)."
  exit 1
fi
[ "$RC" -eq 0 ] && [ "$FAIL" -eq 0 ]
