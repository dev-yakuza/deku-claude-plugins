#!/usr/bin/env bash
# readiness T4 R4-5: the channel version rule — `promote.py check-version`.
#   development channel: X.Y.Z-exp.N (a marketplace entry, if any, has the same version);
#   stable channel: X.Y.Z = the development version it was promoted from without -exp.N (PROMOTED.md), and the
#   marketplace entry has the same version (plugin.json and marketplace.json change together — CLAUDE.md).
#   This plugin is checked as it is (with the marketplace file of the repository it sits in, when there is one — the
#   public repository's CI runs this), then synthetic trees of both channels, good and broken.
# Usage: bash plugins/guild-plugin/tests/version_rule_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$HERE/.." && pwd -P)"
PY="${PYTHON:-python3}"
TOOL="$ROOT/tools/promote/promote.py"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS  $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "$2" | head -n 20; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
check() { "$PY" -I -B "$TOOL" check-version "$@" > "$T/out" 2>&1; echo $?; }

# --- this plugin ---------------------------------------------------------------------------------------------------
MK=""
[ -f "$ROOT/../../.claude-plugin/marketplace.json" ] && MK="$(cd "$ROOT/../../.claude-plugin" && pwd -P)/marketplace.json"
if [ -n "$MK" ]; then rc="$(check "$ROOT" --marketplace "$MK")"; else rc="$(check "$ROOT")"; fi
[ "$rc" = 0 ] && ok "this plugin: $(tail -n 1 "$T/out")${MK:+ (with $MK)}" || bad "this plugin breaks the version rule" "$(cat "$T/out")"

# --- synthetic trees -----------------------------------------------------------------------------------------------
tree() {  # tree DIR NAME VERSION [PROMOTED-FROM]
  mkdir -p "$1/.claude-plugin"
  printf '{"name": "%s", "version": "%s"}\n' "$2" "$3" > "$1/.claude-plugin/plugin.json"
  [ -n "${4:-}" ] && printf -- '- promoted from: guild-plugin %s (`x`)\n' "$4" > "$1/PROMOTED.md"
  return 0
}
market() { printf '{"plugins": [{"name": "%s", "version": "%s"}]}\n' "$2" "$3" > "$1"; }
# promote: literal-begin — both channels' plugin names, the same in both trees
tree "$T/dev" guild-exp 1.1.0-exp.2
same_rc() { [ "$2" = "$3" ] && ok "$1" || bad "$1 (rc $2, expected $3)" "$(cat "$T/out")"; }
same_rc "development X.Y.Z-exp.N passes" "$(check "$T/dev")" 0
tree "$T/dev2" guild-exp 1.1.0
same_rc "development without -exp.N fails" "$(check "$T/dev2")" 1
market "$T/m1.json" guild-exp 1.1.0-exp.1
same_rc "development: a marketplace entry with another version fails" "$(check "$T/dev" --marketplace "$T/m1.json")" 1
market "$T/m2.json" guild-plugin 1.0.0
same_rc "development: no entry of its own in the marketplace passes" "$(check "$T/dev" --marketplace "$T/m2.json")" 0
tree "$T/st" guild-plugin 1.0.0 1.0.0-exp.5
same_rc "stable X.Y.Z promoted from X.Y.Z-exp.N passes" "$(check "$T/st" --marketplace "$T/m2.json")" 0
same_rc "stable without a marketplace file passes" "$(check "$T/st")" 0
tree "$T/st2" guild-plugin 1.0.0-exp.5 1.0.0-exp.5
same_rc "stable with -exp.N fails" "$(check "$T/st2")" 1
tree "$T/st3" guild-plugin 1.0.1 1.0.0-exp.5
same_rc "stable that is not its source version without -exp.N fails" "$(check "$T/st3")" 1
grep -q "so the version is 1.0.0, not 1.0.1" "$T/out" && ok "… and says which version it should be" || bad "no expected version" "$(cat "$T/out")"
tree "$T/st4" guild-plugin 1.0.0
same_rc "stable without PROMOTED.md fails (made by hand)" "$(check "$T/st4")" 1
market "$T/m3.json" guild-plugin 0.102.16
same_rc "stable: plugin.json and the marketplace entry differ → fails" "$(check "$T/st" --marketplace "$T/m3.json")" 1
grep -q "update both" "$T/out" && ok "… and says to update both files" || bad "no 'update both'" "$(cat "$T/out")"
printf '{"plugins": []}\n' > "$T/m4.json"
same_rc "stable: no marketplace entry fails" "$(check "$T/st" --marketplace "$T/m4.json")" 1
# promote: literal-end

echo; echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = 0 ]
