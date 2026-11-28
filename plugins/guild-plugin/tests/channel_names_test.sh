#!/usr/bin/env bash
# readiness T4 (R4-4 V1, V2): this plugin, promoted to the other channel, differs from it by the channel names only.
#   V1 round trip: build this tree into the other channel, build that back with the promoted copy of the promote tool,
#      and the result is this tree byte for byte (tools/out, tools/decisions and PROMOTED.md left out, plugin.json
#      compared without its version).
#   V2 both ways: this tree names the other channel only on tagged lines (rename_test does the same), and the promoted
#      tree names this channel only on its tagged lines.
#   In a promoted tree the same test runs from that side.
# Usage: bash plugins/guild-plugin/tests/channel_names_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$HERE/.." && pwd -P)"
PY="${PYTHON:-python3}"
TOOL="$ROOT/tools/promote/promote.py"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS  $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "$2" | head -n 60; }
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT

out="$("$PY" -I -B "$TOOL" roundtrip --src "$ROOT" --keep "$W/rt" 2>&1)"; rc=$?
[ "$rc" = 0 ] && ok "V1: $(printf '%s\n' "$out" | tail -n 1 | sed "s#; work .*)#)#")" || bad "V1: the round trip changed more than names" "$out"

out="$("$PY" -I -B "$TOOL" check-names "$ROOT" 2>&1)"; rc=$?
[ "$rc" = 0 ] && ok "V2 this tree: $(printf '%s\n' "$out" | tail -n 1)" || bad "V2 this tree" "$out"

built="$(find "$W/rt/one" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [ -n "$built" ] && [ -f "$built/tools/promote/promote.py" ]; then
  out="$("$PY" -I -B "$built/tools/promote/promote.py" check-names "$built" 2>&1)"; rc=$?
  [ "$rc" = 0 ] && ok "V2 the promoted tree ($(basename "$built")): $(printf '%s\n' "$out" | tail -n 1)" \
    || bad "V2 the promoted tree names this channel outside a tag" "$out"
  out="$("$PY" -I -B "$TOOL" check-names "$built" 2>&1)"; rc=$?
  [ "$rc" = 0 ] && ok "V2 the promoted tree, checked by this copy of the tool too" || bad "V2 (this copy of the tool)" "$out"
else
  bad "the round trip left no promoted tree to check"
fi
echo; echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = 0 ]
