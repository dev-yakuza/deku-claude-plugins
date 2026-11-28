#!/usr/bin/env bash
# guild-plugin engine tests: unittest discover over skills/gld/engine/tests (standard library only).
#   python3 -I (no cwd / PYTHON* on the import path), -B (no __pycache__ in the plugin).
# Usage: bash plugins/guild-plugin/tests/engine_test.sh [-v] [-k pattern]
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ENGINE="$HERE/../skills/gld/engine"
cd "$ENGINE" || exit 1
python3 -I -B -m unittest discover -s tests -t . -p 'test_*.py' "$@"
rc=$?
if [ "$rc" = 0 ]; then echo "engine: PASS"; else echo "engine: FAIL (rc=$rc)"; fi
exit "$rc"
