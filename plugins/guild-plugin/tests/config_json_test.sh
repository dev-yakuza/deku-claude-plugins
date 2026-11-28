#!/usr/bin/env bash
# readiness T3 P9: the command documents never send an LLM command to `config.json` again.
#   `.claude/guild/config.json` is the ENGINE's settings file (format 1). Its schema refuses every
#   key of the LLM commands' settings (`harness.json`: version, language, roles, commands, automation,
#   sprint — and `visual`, which this edition does not write at all), and one such key makes the engine
#   refuse every Issue (H13). So in the command documents, READMEs and templates:
#   1. every line that names `config.json` must say it is the engine's (engine / 엔진 / エンジン on the
#      same line), unless it is in ALLOW below (file + a fixed piece of that line, with the reason);
#   2. no line pairs `config.json` with an LLM-settings key, and `config.version` / `config.gates` are gone;
#   3. the corrected sentences stay (update writes no `visual`, evolve HR edits harness.json roles, …).
#   A control run proves the checks catch the old wording (BSD grep: -E only, no -P).
# Usage: bash plugins/guild-plugin/tests/config_json_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$HERE/.." && pwd -P)"
SCOPE="README.md README.ko.md README.ja.md skills/gld/SKILL.md skills/gld/commands skills/gld/templates"
NAME='(^|[^A-Za-z0-9_])config\.json'                 # not `regconfig.json`
ENGINE='engine|엔진|エンジン'
KEYS='config\.json`?('"'"'s)?`? *(→ *)?`?(roles|language|version|commands|automation|sprint|visual|history|capacity)\b|config\.(version|gates|visual)\b'
# file|fixed piece of the line|why it may name config.json without "engine" on that line
ALLOW='skills/gld/commands/init.md|re-running detects `.claude/guild/harness.json` at P0|init completeness set lists the engine settings written by P2.9 (T2 file)
skills/gld/commands/init.md|present → a 0.98.x Guild may have set this folder up|P0 step 3: the 0.98.x settings file, not the engine'"'"'s (T2 P4)
skills/gld/commands/init.md|P0 step 3 found `.claude/guild/config.json` and no `harness.json`|P0b: the 0.98.x settings file migrate reads (T2 P4)
skills/gld/commands/init.md|a `config.json` that is no JSON object|P0b: a refusal of init migrate about the 0.98.x file (T2 P4)
skills/gld/commands/init.md|`change` config.json — `gates` taken out|P0b: init migrate takes `gates` out of the 0.98.x file (T2 P4)
skills/gld/commands/init.md|Say that `config.json` stays the 0.98.x file until P2.9|P0b: the 0.98.x file stays until P2.9 writes the engine settings (T2 P4)
skills/gld/commands/init.md|the changed config.json / .gitignore / gate script|P0b: committing the migrated 0.98.x file (T2 P4)'
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS  $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "$2" | head -n 20; }

# lines (path:line:text) under DIR naming config.json without an engine word, minus ALLOW
unmarked() {
  local dir="$1" hits
  hits="$(cd "$dir" && grep -rnE "$NAME" $SCOPE 2>/dev/null | grep -viE "$ENGINE")"
  while IFS='|' read -r f piece _why; do
    [ -z "$f" ] && continue
    hits="$(printf '%s\n' "$hits" | grep -vF "$f:" ; printf '%s\n' "$hits" | grep -F "$f:" | grep -vF -- "$piece")"
  done <<< "$ALLOW"
  printf '%s\n' "$hits" | sed '/^$/d'
}
paired() { (cd "$1" && grep -rnE "$KEYS" $SCOPE 2>/dev/null); }

# --- control: the checks catch the old wording -------------------------------------------------
CTL="$(mktemp -d)"; trap 'rm -rf "$CTL"' EXIT
mkdir -p "$CTL/skills/gld/commands" "$CTL/skills/gld/templates"
: > "$CTL/README.md"; : > "$CTL/README.ko.md"; : > "$CTL/README.ja.md"; : > "$CTL/skills/gld/SKILL.md"
cat > "$CTL/skills/gld/commands/old.md" <<'EOF'
an **HR change** → `config.json` `roles` + the agent file.
1. **Scope**: only roles that are BOTH in `config.json`'s `roles` AND have a central
- `config.version` ≥ plugin → check the git hook
6. **Commit `config.json` on its own**
**L.0 Config** (`config.json`, written by `init`/`update` from `scan_repo.md` Section 2 step 3b):
`regconfig.json` (a visual-test tool's file — not ours)
`config.json` is the engine's settings file.
EOF
c1="$(unmarked "$CTL" | grep -c .)"; c2="$(paired "$CTL" | grep -c .)"
[ "$c1" = 4 ] && ok "control: 4 old unmarked lines found (regconfig.json and the engine line pass)" \
  || bad "control: expected 4 unmarked lines, got $c1" "$(unmarked "$CTL")"
[ "$c2" = 3 ] && ok "control: 3 old key pairings found" || bad "control: expected 3 key pairings, got $c2" "$(paired "$CTL")"

# --- the plugin ------------------------------------------------------------------------------
h="$(unmarked "$ROOT")"
[ -z "$h" ] && ok "every config.json line in the command docs names the engine (or is allowed)" \
  || bad "config.json named without the engine — use harness.json for the commands' settings" "$h"
h="$(paired "$ROOT")"
[ -z "$h" ] && ok "no config.json + LLM-settings key pairing, no config.version / config.gates" \
  || bad "config.json paired with an LLM-settings key" "$h"
while IFS='|' read -r f piece _why; do
  [ -z "$f" ] && continue
  grep -qF -- "$piece" "$ROOT/$f" && ok "allow entry still used: $f" || bad "stale allow entry (drop it): $f — $piece"
done <<< "$ALLOW"

# --- the corrected sentences stay --------------------------------------------------------------
has() { grep -qF -- "$2" "$ROOT/$1" && ok "$1: $3" || bad "$1: lost — $3"; }
has skills/gld/commands/update.md 'Write no `visual` block anywhere.' "update writes no visual block"
has skills/gld/commands/update.md '**Config** → `.claude/guild/harness.json` **only**' "update's Config step targets harness.json"
has skills/gld/commands/evolve.md 'an **HR change** → `.claude/guild/harness.json` `roles`' "evolve HR edits harness.json roles"
has skills/gld/commands/atoms/_handoff.md 'no command writes a `visual` block' "Section L.0 says no visual block is written"
has skills/gld/commands/sprint/retro.md '**Commit `harness.json` on its own**' "retro commits harness.json"
has skills/gld/commands/monitoring.md 'read `.claude/guild/harness.json` (language, roles)' "monitoring reads harness.json"

echo; echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = 0 ]
