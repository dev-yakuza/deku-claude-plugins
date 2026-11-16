#!/usr/bin/env bash
# Verification for the issue-flow engine, milestone K1 — the executor
# (design: design/guild/23-engine/design.md §2.4–2.9, §3.1, §4, §5, §9.6, §10.1 K1, §10.2-2/3b).
#
# Runs the Python unittest modules tests/engine/test_k1_*.py:
#   • claude adapter: only documented flags, `--setting-sources ""` + rendered `--settings`, the §5.1
#     env contract laid over parent + settings env, the endpoint guard (halt unless
#     --allow-local-endpoint / allowed_endpoints), process groups killed safely, stream-json parsing
#     (real CLI 2.1.311 streams recorded by the K1 local smoke);
#   • §5.1 permission rules and the rendered settings (deny union, env/sandbox carried, allow and
#     user hooks NOT carried, hooks + gate scripts from the BASE snapshot), the after-role scope
#     check (parallel union, HEAD/refs rules, protected paths);
#   • journal write side (fsync, intent/done, entry validity, cache, epoch), worker lock/events,
#     cost rows (TTL split + attribution), ground-truth capture (schema unchanged), rate-limit
#     verdicts, the checks runner and parsers;
#   • verified GitHub writes (Section F + §2.7 re-read), the decision-log writer (numbering race,
#     rollover, at_server), pause order and crash completion, ask/answer/settle (conflict stays);
#   • the role runner (P-RES, result.json, repair, permission resume, timeout/halt/rate limit,
#     scope) and the judge runner (schema re-validation, tier-up, unsure, coercion, needs_more,
#     cache, brief cap) against a fake spawn;
#   • the replay harness: scripted/logging proxy, the permission reclassifier against the REAL
#     CLI decisions of the matcher calibration (≥98% per set), canned result.json extraction.
# No test calls `claude`, a model or GitHub (a failing `gh` is first on PATH).
#
# Usage: bash plugins/guild-plugin/tests/engine_k1_test.sh
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
    -m unittest discover -s . -p 'test_k1_*.py' -v ) >"$OUT" 2>&1
RC=$?
grep -E '\.\.\. (ok|FAIL|ERROR|skipped)' "$OUT" | sed -E 's/^(.*) \.\.\. ok$/  PASS  \1/; s/^(.*) \.\.\. (FAIL|ERROR)$/  FAIL  \1/; s/^(.*) \.\.\. skipped.*$/  SKIP  \1/'
PASS=$(grep -cE '\.\.\. ok$' "$OUT")
FAIL=$(grep -cE '\.\.\. (FAIL|ERROR)$' "$OUT")
if [ "$RC" -ne 0 ]; then
  sed -n '/^======/,$p' "$OUT"
fi
echo "engine K1: $PASS passed, $FAIL failed"
# ⚠ Keep equal to the measured PASS count; raise it only when tests are added on purpose.
ENGINE_K1_MIN_TESTS=236
if [ "$((PASS + FAIL))" -lt "$ENGINE_K1_MIN_TESTS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${ENGINE_K1_MIN_TESTS}건)."
  exit 1
fi
[ "$RC" -eq 0 ] && [ "$FAIL" -eq 0 ]
