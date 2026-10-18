#!/usr/bin/env bash
# Runs every Herald test suite. Usage: bash plugins/herald-plugin/tests/run_tests.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
rc=0
echo "== structure"; bash "$HERE/structure_test.sh" || rc=1
echo "== python (deterministic layer, plan §7 safety tests)"
( cd "$HERE/py" && python3 -W ignore -m unittest -q test_core test_guard_gate_measure test_batch test_multilingual test_refresh test_social test_social_growth test_token_opt test_batch_ratelimit ) || rc=1
exit $rc
