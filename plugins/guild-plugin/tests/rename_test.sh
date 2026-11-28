#!/usr/bin/env bash
# Channel-name check (U0, readiness T4 R4-2): this tree names the other Guild channel only on tagged lines.
#   The names and the tags are tools/promote/promote.py's, checked with Python regular expressions. (The U0 version
#   grepped with `grep -P`; macOS's BSD grep has no -P, the error went to /dev/null, and the test passed without
#   checking anything.) RENAME_EXCEPTIONS.md explains the tags.
#   1. control: the checker finds an untagged other-channel name and a loose spelling of this channel's name, and
#      accepts the tagged forms (so an empty result below means "checked", not "did not run").
#   2. promote.py check-names over this plugin: no problem (V2, this tree's side).
#   3. every file holding a `rename-exception` tag is listed in RENAME_EXCEPTIONS.md.
#   4. the other-channel label refusal is in both entry docs; the other channel's skill folder is not here.
# Usage: bash plugins/guild-plugin/tests/rename_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$HERE/.." && pwd -P)"
PY="${PYTHON:-python3}"
TOOL="$ROOT/tools/promote/promote.py"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS  $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "$2" | head -n 40; }

# --- 1. control --------------------------------------------------------------------------------------------------
CTL="$(mktemp -d)"; trap 'rm -rf "$CTL"' EXIT
mkdir -p "$CTL/.claude-plugin" "$CTL/docs"
cp "$ROOT/.claude-plugin/plugin.json" "$CTL/.claude-plugin/plugin.json"
{
  echo 'an untagged label gx:analyze'                                  # promote: other
  echo 'an untagged command /gldx dev 42'                                  # promote: other
  echo 'tagged gx:analyze <!-- promote: other -->'
  echo 'tagged /gld <!-- promote: literal -->'
  echo 'shared .claude/guild/knowledge/index.md'
  echo 'a loose spelling gldx_scratch'                                    # promote: literal
  echo 'this channel /gld dev 42 guild:analyze .claude/guild/x'
} > "$CTL/docs/a.md"
out="$("$PY" -I -B "$TOOL" check-names "$CTL" 2>&1)"
n="$(printf '%s\n' "$out" | grep -c '^docs/a.md:')"
lines="$(printf '%s\n' "$out" | grep '^docs/a.md:' | cut -d: -f2 | sort -u | tr '\n' ' ')"
[ "$n" = 3 ] && [ "$lines" = "1 2 6 " ] && ok "control: 3 problems on lines 1, 2 and 6 (tagged, shared and own names pass)" \
  || bad "control: expected problems on lines 1 2 6, got $n on: $lines" "$out"

# --- 2. this tree --------------------------------------------------------------------------------------------------
out="$("$PY" -I -B "$TOOL" check-names "$ROOT" 2>&1)"; rc=$?
[ "$rc" = 0 ] && ok "no other-channel name outside a promote tag ($(printf '%s\n' "$out" | tail -n 1))" \
  || bad "other-channel names outside a promote tag (RENAME_EXCEPTIONS.md)" "$out"

# --- 3. tagged files are listed ------------------------------------------------------------------------------------
tagged="$(cd "$ROOT" && grep -rl --exclude-dir=.claude-plugin --exclude-dir=out --exclude-dir=decisions \
  --exclude-dir=__pycache__ 'rename-exception' . \
  | sed 's#^\./##' | sort)"
for f in $tagged; do
  case "$f" in RENAME_EXCEPTIONS.md|tests/rename_test.sh) continue;; esac
  grep -qF "\`$f\`" "$ROOT/RENAME_EXCEPTIONS.md" && ok "exception file listed: $f" || bad "tagged file missing from RENAME_EXCEPTIONS.md: $f"
done

# --- 4. the refusal and the folder ----------------------------------------------------------------------------------
for f in skills/gld/commands/dev.md skills/gld/commands/resume.md; do
  grep -qF "Refuse the other Guild channel's Issue" "$ROOT/$f" && ok "$f has the other-channel label refusal" \
    || bad "$f lacks the other-channel label refusal"
done
[ ! -e "$ROOT/skills/gldx" ] && ok "no skills folder of the other channel" || bad "the other channel's skills folder exists"  # promote: other
echo; echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = 0 ]
