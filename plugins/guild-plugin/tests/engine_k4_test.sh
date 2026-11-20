#!/usr/bin/env bash
# Verification for the issue-flow engine, milestone K4 — analyze, design, child Issues and the issue FSM
# (design: design/guild/23-engine/design.md §2.2, §2.5, §3.2, §3.3 AN-PO/DE-ARB/HANDOFF, §3.6, §10.1 K4).
#
# Runs the Python unittest modules tests/engine/test_k4_*.py:
#   • analyze: KICK-EXPLORE (evidence only from its out/), L0-KICKOFF + the code coercions (anchors re-read
#     from tracked files, safety-net AC restored, areas = real dirs, cast ∩ roster), the P2 trust gate on the
#     Issue body (plan-decision / safety-net / premise / close only from a member's body), SJ-STAKES per
#     question (irreversible → never low), product-owner forcing + AN-PO, close-as-decided T3 order, the
#     harness guard, attended asks and applied answers, the analyze→design hand-over;
#   • design: tester (AC only, first) → tech-lead → specialists, artifacts from out/ (P1), one repair then
#     SJ-HANDOFF, DE-ARB (one re-invocation), VISUAL as code, the split (L0-SPLIT, child Issues with hidden
#     keys, A-F38 order, leaf guard, partial-creation stop before the flip);
#   • the issue FSM: engine-start first, routing, variants, stage_start, execute→test + SJ-HANDOFF (loop-back
#     `from: leader`), NEEDS_CONTEXT map, exit codes 0/3/6/75 + the stdout contract, §2.5 resume
#     (superseded, answer line, label removed = re-judge, interrupted pause, attended re-ask), children
#     2b/2c (T8 cleanup, stop on a paused child, G-INTEGRATE, fix child);
#   • platform + K3 carry-overs: gh forms, issue close, pause `cause:`, roleout, spec store install,
#     base config, H§M line on execute env stops, legacy unreadable pending lines, sub-directory check
#     configs, the AST raw-write lint, O_NOFOLLOW reads.
#   • review r1 (test_k4_r1.py): the FSM's test/qa ports (late-bound branch, engine push, no main-checkout
#     fallback), fail-closed author trust, the split resumed only from its recorded plan with idempotent
#     child creation and B.fail failures, every FSM end on the exit-code contract, close only from an exact
#     member plan line, the minors, and the user decisions of 2026-11-18 (PO forcing, outsider text vs the
#     harness guard, the role commit's lefthook config from <base>).
#   • review r2 (test_k4_r2.py): child-creation dedup by the label listing under a STALE search index,
#     three-valued author trust (unknown pauses), close only from the structured close form, PO forcing
#     for partial OR unclear ∧ stakes ≥ medium, the lefthook-local overlay closed + LEFTHOOK=0 without a
#     base + one lefthook name list, the fallback push branch, superseded/stale split plans, planted keys,
#     the outsider mark on fix children and the 2c inputs.
#   • review r3 (test_k4_r3.py): no search-backed read decides anything about child Issues (the fake's
#     labelled listing AND search are stale) — journal-first creates with a token, a lost reply / crash
#     resolved through the paginated REST list and confirmed by number, an unknown create pauses and is
#     never re-sent, 2b's duplicate-key check, withdrawn / foreign children never driven, children known by
#     the journal (not author association), execute's net marker only from a member body, a role that
#     never started is not blamed, plan blocks in fences / quotes not read.
#   • review r4 (test_k4_r4.py): a create is "refused" only on a definite non-landing signal (HTTP 4xx, rate
#     limit, not logged in) — unknown text / empty stderr / stream error / 5xx / signal take the ambiguous
#     path for Issue, comment and PR creates; the restart check records a found create's number; an abandoned
#     create that landed later is surfaced; deleted / transferred children stop clearly then count as
#     withdrawn; the duplicate check by journal key; closed-as-duplicate only when verified; an unclosed fence
#     does not hide a later plan-decision block.
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
    -m unittest discover -s . -p 'test_k4_*.py' -v ) >"$OUT" 2>&1
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
SKIPPED=$(printf '%s' "$SUMMARY" | sed -nE 's/.*(\(|, )skipped=([0-9]+).*/\2/p'); SKIPPED=${SKIPPED:-0}
FAILURES=$(printf '%s' "$SUMMARY" | sed -nE 's/.*(\(|, )failures=([0-9]+).*/\2/p'); FAILURES=${FAILURES:-0}
ERRORS=$(printf '%s' "$SUMMARY" | sed -nE 's/.*(\(|, )errors=([0-9]+).*/\2/p'); ERRORS=${ERRORS:-0}
COUNTED=$((RAN - SKIPPED))
FAIL=$((FAILURES + ERRORS))
PASS=$((COUNTED - FAIL))
[ -n "$SUMMARY" ] || { FAIL=$((FAIL + 1)); echo "FAIL  unittest 요약 줄(OK / FAILED)이 없습니다."; }
echo "engine K4: $PASS passed, $FAIL failed (ran $RAN, skipped $SKIPPED)"
# ⚠ Keep equal to the measured count (ran − skipped); raise it only when tests are added on purpose.
ENGINE_K4_MIN_TESTS=212
if [ "$COUNTED" -lt "$ENGINE_K4_MIN_TESTS" ]; then
  echo "FAIL  실행된 검사가 ${COUNTED}건뿐입니다 (스킵 제외, 최소 ${ENGINE_K4_MIN_TESTS}건)."
  exit 1
fi
[ "$RC" -eq 0 ] && [ "$FAIL" -eq 0 ]
