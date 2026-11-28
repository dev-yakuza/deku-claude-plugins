#!/usr/bin/env bash
# readiness T4 R4-2: tools/promote/promote.py on a small synthetic plugin tree.
#   build: names renamed by the line tags (self / other / literal / blocks), the shared paths kept, FILE_KINDS,
#   the version rule (R4-5), plugin.json / PROMOTED.md / the marketplace copy, left-out folders, the executable bit,
#   binary files; where it refuses to write. check-names (V2) and roundtrip (V1) on the synthetic tree, good and broken.
#   Channel-neutral: in the promoted tree the same test runs the other way (stable → development).
# Usage: bash plugins/guild-plugin/tests/promote_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$HERE/.." && pwd -P)"
PY="${PYTHON:-python3}"
TOOL="$ROOT/tools/promote/promote.py"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS  $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "$2" | head -n 30; }
same() { [ "$2" = "$3" ] && ok "$1" || bad "$1" "$(printf 'expected: %s\n     got: %s' "$3" "$2")"; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
jq_() { "$PY" -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print(eval(sys.argv[2], {"d": d}))' "$@"; }

SELF_NAME="$(jq_ "$ROOT/.claude-plugin/plugin.json" 'd["name"]')"
# promote: literal-begin — which way this copy of the test runs
if [ "$SELF_NAME" = "guild-exp" ]; then
  SRC_VER=1.2.0-exp.4; DST_VER=1.2.0; DST_NAME=guild-plugin; DST_DIR=guild-plugin
  SRC_DESC="Guild experimental (redesign: procedure-driven engine). Guild - x"; DST_DESC="Guild - x"
else
  SRC_VER=1.2.0; DST_VER=1.3.0-exp.1; DST_NAME=guild-exp; DST_DIR=guild-exp-plugin
  SRC_DESC="Guild - x"; DST_DESC="Guild experimental (redesign: procedure-driven engine). Guild - x"
fi
# promote: literal-end

# --- a synthetic plugin tree of this channel --------------------------------------------------------------------------
S="$T/src"
mkdir -p "$S/.claude-plugin" "$S/skills/gld/engine/tools/out" "$S/skills/gld/engine/tools/decisions" "$S/bin" \
  "$S/tools/promote" "$S/skills/gld/data"
cp "$TOOL" "$S/tools/promote/promote.py"
"$PY" -I -c 'import json,sys; json.dump({"name": sys.argv[1], "description": sys.argv[2], "version": sys.argv[3],
  "author": {"name": "a"}}, open(sys.argv[4], "w"), indent=2); open(sys.argv[4], "a").write("\n")' \
  "$SELF_NAME" "$SRC_DESC" "$SRC_VER" "$S/.claude-plugin/plugin.json"
A_SRC="$S/skills/gld/a.md"
cat > "$A_SRC" <<'EOF'
run /gld dev 42 — labels guild:analyze, <!-- guild:sprint:plan -->, branch gld/42, home ~/.gld, worktree .gld-app-42
settings .claude/guild/config.json and the shared .claude/guild/knowledge/index.md and .claude/guild-channel
EOF
printf '%s\n' 'refuse gx:analyze, use /gldx — this one is /gld <!-- promote: other -->' >> "$A_SRC"
printf '%s\n' 'Guild 0.98.7 kept .claude/guild/config.json <!-- promote: literal -->' >> "$A_SRC"
printf '%s\n' 'GLD_ENGINE_HOME=x GLD_UNATTENDED=1 gxengine gx-canary' >> "$A_SRC"
cat > "$S/skills/gld/b.py" <<'EOF'
PREFIX = "guild:"
OTHER_PREFIX = "gx:"   # promote: other
# promote: literal-begin
TABLE = {"gldx": 1, "gld": 2}
# promote: literal-end
PATH = ("skills", "gld", ".claude", "guild")
PART = os.path.join(root, ".claude", "guild", "x")
EOF
printf '%s\n' '{"label": "gx:followup", "own": "guild:followup"}' > "$S/skills/gld/data/swap.json"  # promote: other
printf 'secret log\n' > "$S/skills/gld/engine/tools/out/run.log"
printf '{}\n' > "$S/skills/gld/engine/tools/decisions/x.json"
printf '#!/bin/sh\necho /gld\n' > "$S/bin/tool"; chmod +x "$S/bin/tool"
printf 'data\000binary\377' > "$S/skills/gld/data/blob.bin"
# the swapped JSON file is listed as `other` in this copy of the tool (FILE_KINDS) — patch the synthetic copy only
"$PY" -I - "$S/tools/promote/promote.py" <<'PYE'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
s = s.replace("FILE_KINDS = {\n", 'FILE_KINDS = {\n    "skills/gld/data/swap.json": "other",\n', 1)
open(p, "w", encoding="utf-8").write(s)
PYE

# --- build ---------------------------------------------------------------------------------------------------------
OUT="$T/out"
"$PY" -I -B "$S/tools/promote/promote.py" build --src "$S" --out "$OUT" --no-marketplace --json > "$T/rep.json" 2> "$T/err"
rc=$?; same "build exits 0" "$rc" 0
D="$OUT/$DST_DIR"
same "plugin.json name" "$(jq_ "$D/.claude-plugin/plugin.json" 'd["name"]')" "$DST_NAME"
same "plugin.json version (R4-5)" "$(jq_ "$D/.claude-plugin/plugin.json" 'd["version"]')" "$DST_VER"
same "plugin.json description" "$(jq_ "$D/.claude-plugin/plugin.json" 'd["description"]')" "$DST_DESC"
same "plugin.json other fields kept" "$(jq_ "$D/.claude-plugin/plugin.json" 'd["author"]["name"]')" "a"
same "skill folder renamed" "$(cd "$D" && ls skills)" "gldx"                                      # promote: other
A="$D/skills/gldx/a.md"                                                                               # promote: other
same "self names renamed" "$(sed -n 1p "$A")" \
  "run /gldx dev 42 — labels gx:analyze, <!-- gx:sprint:plan -->, branch gx/42, home ~/.gldx, worktree .gldx-app-42"  # promote: other
same "settings renamed, shared paths kept" "$(sed -n 2p "$A")" \
  "settings .claude/guild-exp/config.json and the shared .claude/guild/knowledge/index.md and .claude/guild-channel"  # promote: other
same "an other line is swapped" "$(sed -n 3p "$A")" \
  'refuse guild:analyze, use /gld — this one is /gldx <!-- promote: other -->'
same "a literal line stays" "$(sed -n 4p "$A")" 'Guild 0.98.7 kept .claude/guild/config.json <!-- promote: literal -->'
same "engine variables renamed, internal names kept" "$(sed -n 5p "$A")" 'GX_ENGINE_HOME=x GLD_UNATTENDED=1 gxengine gx-canary'  # promote: other
B="$D/skills/gldx/b.py"                                                                               # promote: other
same "code: own prefix" "$(sed -n 1p "$B")" 'PREFIX = "gx:"'                                     # promote: other
same "code: other prefix swapped" "$(sed -n 2p "$B")" 'OTHER_PREFIX = "guild:"   # promote: other'
same "code: literal block kept" "$(sed -n 4p "$B")" 'TABLE = {"gldx": 1, "gld": 2}'                 # promote: literal
same "code: path parts" "$(sed -n 6p "$B")" 'PATH = ("skills", "gldx", ".claude", "guild-exp")'         # promote: other
same "code: os.path.join parts" "$(sed -n 7p "$B")" 'PART = os.path.join(root, ".claude", "guild-exp", "x")'  # promote: other
SWAP="$D/skills/gldx/data/swap.json"; DE="$D/skills/gldx/engine"                                     # promote: other
same "FILE_KINDS other: the whole file swapped" "$(cat "$SWAP")" '{"label": "guild:followup", "own": "gx:followup"}'  # promote: other
[ ! -e "$DE/tools/out" ] && [ ! -e "$DE/tools/decisions" ] \
  && ok "tools/out and tools/decisions are left out (R4-6)" || bad "tools/out or tools/decisions was copied"
[ -x "$D/bin/tool" ] && ok "the executable bit is kept" || bad "bin/tool lost its executable bit"
same "a binary file is copied as it is" "$(cmp -s "$S/skills/gld/data/blob.bin" "$D/skills/gldx/data/blob.bin" && echo same)" same  # promote: other
same "the copied tool says the other channel" "$(grep -c '^CHANNEL = "gldx"' "$D/tools/promote/promote.py")" 1  # promote: other
if [ "$DST_NAME" = guild-plugin ]; then                                                             # promote: literal
  grep -q "promoted from: $SELF_NAME $SRC_VER" "$D/PROMOTED.md" && ok "PROMOTED.md names the source and version" \
    || bad "PROMOTED.md" "$(cat "$D/PROMOTED.md" 2>&1)"
else
  [ ! -e "$D/PROMOTED.md" ] && ok "no PROMOTED.md in a development-channel build" || bad "PROMOTED.md in a development build"
fi

# --- refusals ------------------------------------------------------------------------------------------------------
"$PY" -I -B "$S/tools/promote/promote.py" build --src "$S" --out "$OUT" --no-marketplace > /dev/null 2> "$T/err"
same "an existing build is not replaced without --replace (exit 2)" "$?" 2
"$PY" -I -B "$S/tools/promote/promote.py" build --src "$S" --out "$OUT" --no-marketplace --replace > /dev/null 2>&1
same "--replace makes it again" "$?" 0
mkdir -p "$T/market/.claude-plugin"; printf '{"plugins": []}\n' > "$T/market/.claude-plugin/marketplace.json"
"$PY" -I -B "$S/tools/promote/promote.py" build --src "$S" --out "$T/market/plugins" --no-marketplace > /dev/null 2> "$T/err"
rc=$?
[ "$rc" = 2 ] && [ ! -e "$T/market/plugins" ] && grep -q "marketplace repository" "$T/err" \
  && ok "refuses to write inside a marketplace repository" || bad "wrote into a marketplace repository (rc $rc)" "$(cat "$T/err")"
"$PY" -I -c 'import json,sys; d=json.load(open(sys.argv[1])); d["version"]="1.2.0-rc.1"; json.dump(d, open(sys.argv[1], "w"))' \
  "$S/.claude-plugin/plugin.json"
"$PY" -I -B "$S/tools/promote/promote.py" build --src "$S" --out "$T/o2" --no-marketplace > /dev/null 2> "$T/err"
rc=$?
[ "$rc" = 2 ] && grep -q "does not follow" "$T/err" && ok "a version off the channel rule is refused (R4-5)" \
  || bad "version rule not enforced (rc $rc)" "$(cat "$T/err")"
"$PY" -I -c 'import json,sys; d=json.load(open(sys.argv[1])); d["version"]=sys.argv[2]; json.dump(d, open(sys.argv[1], "w"), indent=2); open(sys.argv[1], "a").write("\n")' \
  "$S/.claude-plugin/plugin.json" "$SRC_VER"

# --- the marketplace copy ------------------------------------------------------------------------------------------
cat > "$T/m.json" <<EOF
{
  "name": "deku",
  "plugins": [
    {
      "name": "other",
      "version": "9.9.9"
    },
    {
      "name": "$DST_NAME",
      "source": "./plugins/$DST_DIR",
      "version": "0.1.0"
    }
  ]
}
EOF
"$PY" -I -B "$S/tools/promote/promote.py" build --src "$S" --out "$T/o3" --marketplace "$T/m.json" > /dev/null 2> "$T/err"
same "build with a marketplace file exits 0" "$?" 0
same "the marketplace copy has the new version" \
  "$(jq_ "$T/o3/marketplace.json" '[p["version"] for p in d["plugins"]]')" "['9.9.9', '$DST_VER']"
same "only the version line differs" "$(diff "$T/m.json" "$T/o3/marketplace.json" | grep -c '^[<>]')" 2
cmp -s "$T/m.json" "$T/m.json" && ok "the given marketplace file is not written"

# --- V2 / V1 on the synthetic tree -----------------------------------------------------------------------------------
"$PY" -I -B "$S/tools/promote/promote.py" check-names "$S" > "$T/n1" 2>&1
same "check-names: the synthetic source is clean" "$?" 0
"$PY" -I -B "$D/tools/promote/promote.py" check-names "$D" > "$T/n2" 2>&1
same "check-names: its build is clean" "$?" 0
"$PY" -I -B "$S/tools/promote/promote.py" roundtrip --src "$S" > "$T/rt" 2>&1
same "roundtrip: build and build back give the source again (V1)" "$?" 0
printf '%s\n' 'forgot a tag: gx:analyze' >> "$A_SRC"                                            # promote: other
"$PY" -I -B "$S/tools/promote/promote.py" check-names "$S" > "$T/n3" 2>&1
rc=$?
[ "$rc" = 1 ] && grep -q '^skills/gld/a.md:6:' "$T/n3" && ok "check-names finds an untagged other-channel name (V2)" \
  || bad "check-names missed the untagged name (rc $rc)" "$(cat "$T/n3")"
"$PY" -I -B "$S/tools/promote/promote.py" roundtrip --src "$S" > "$T/rt2" 2>&1
rc=$?
[ "$rc" = 1 ] && grep -q 'skills/gld/a.md: differs' "$T/rt2" && ok "roundtrip fails on it too (V1)" \
  || bad "roundtrip passed a tree that does not come back (rc $rc)" "$(cat "$T/rt2")"

echo; echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = 0 ]
