#!/usr/bin/env bash
# Structural checks for the Herald plugin (plan §7 "구조").
#
# - SKILL.md routing list == commands/*.md
# - every command/atom reference points at an existing file
# - the result-contract block is byte-identical wherever it appears
# - persona templates: frontmatter keys, one marker region, no {{placeholders}} inside it
# - JSON templates parse after placeholder strings are substituted
# - plugin.json version == marketplace.json entry
#
# Usage: bash plugins/herald-plugin/tests/structure_test.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$HERE/.."
PY="${PY:-python3}"
"$PY" -c 'import sys' 2>/dev/null || { echo "FAIL  python3 not runnable"; exit 1; }

"$PY" - "$PLUGIN" <<'EOF'
import glob, json, os, re, sys
plugin = sys.argv[1]
skill = os.path.join(plugin, "skills", "hrd")
fails = []
def check(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        fails.append(msg)

# routing
text = open(os.path.join(skill, "SKILL.md")).read()
m = re.search(r"Valid commands: (.*?)\.\n", text, re.S)
routed = set(re.findall(r"`([a-z-]+)`", m.group(1))) if m else set()
files = {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(skill, "commands", "*.md"))}
check(routed == files, "SKILL.md routing == commands/*.md (missing files: %s, unrouted: %s)"
      % (sorted(routed - files), sorted(files - routed)))

# references to atoms/commands/templates
for p in glob.glob(os.path.join(skill, "commands", "**", "*.md"), recursive=True) + [os.path.join(skill, "SKILL.md")]:
    body = open(p).read()
    for ref in set(re.findall(r"`(?:<<SKILL_DIR>>/)?((?:commands/)?atoms/_[a-z_]+\.md)`", body)):
        path = os.path.join(skill, ref if ref.startswith("commands/") else os.path.join("commands", ref))
        check(os.path.exists(path), "%s → %s exists" % (os.path.relpath(p, skill), ref))
    for ref in set(re.findall(r"`([a-z-]+\.md)`", body)):
        if ref in ("write.md", "ship.md", "status.md", "monitoring.md", "init.md", "resume.md"):
            check(os.path.exists(os.path.join(skill, "commands", ref)), "%s → commands/%s exists" % (os.path.relpath(p, skill), ref))

# every command that acquires the checkout lock also releases it
for p in glob.glob(os.path.join(skill, "commands", "*.md")):
    body = open(p).read()
    if "lock acquire" in body:
        check("lock release" in body or "release on every exit" in body,
              "%s releases the lock it acquires" % os.path.basename(p))

# result contract identical
canon = None
blocks = []
for p in glob.glob(os.path.join(skill, "**", "*.md"), recursive=True):
    for b in re.findall(r"<!-- herald:result-contract -->\n(.*?)\n<!-- /herald:result-contract -->", open(p).read(), re.S):
        blocks.append((p, re.sub(r"^> ?", "", b, flags=re.M)))
check(len(blocks) >= 1, "result-contract block present")
if blocks:
    canon = blocks[0][1]
    for p, b in blocks:
        check(b == canon, "result-contract identical in %s" % os.path.relpath(p, skill))

# personas
agents = sorted(glob.glob(os.path.join(skill, "templates", "agents", "*.md")))
expected = {"editor-in-chief", "content-strategist", "researcher", "writer", "fact-checker", "editor",
            "subject-expert", "search-discovery", "illustrator", "translator", "distributor"}
check({os.path.basename(a)[:-3] for a in agents} == expected, "11 persona templates present")
for a in agents:
    t = open(a).read()
    name = os.path.basename(a)[:-3]
    fm = re.match(r"---\nname: (.+)\ndescription: (.+)\nmodel: (\w+)\n---\n", t)
    check(bool(fm) and fm.group(1).strip() == name, "%s frontmatter name/description/model" % name)
    check(t.count("<!-- herald:persona:start -->") == 1 and t.count("<!-- herald:persona:end -->") == 1,
          "%s has exactly one marker region" % name)
    region = t.split("<!-- herald:persona:start -->")[-1].split("<!-- herald:persona:end -->")[0]
    check("{{" not in region, "%s marker region has no placeholders" % name)
    check("<!-- herald:persona:habits -->" in t, "%s has habits marker" % name)

# json templates
for p in glob.glob(os.path.join(skill, "templates", "**", "*.json.tmpl"), recursive=True):
    raw = open(p).read()
    filled = re.sub(r':\s*"\{\{[A-Z_]+\}\}"', ': 0', raw)
    filled = re.sub(r"\{\{[A-Z_]+\}\}", "x", filled)
    try:
        json.loads(filled); ok = True
    except ValueError:
        ok = False
    check(ok, "%s parses as JSON after substitution" % os.path.relpath(p, skill))

# version sync
pv = json.load(open(os.path.join(plugin, ".claude-plugin", "plugin.json")))["version"]
mk = json.load(open(os.path.join(plugin, "..", "..", ".claude-plugin", "marketplace.json")))
mv = [x["version"] for x in mk["plugins"] if x["name"] == "herald-plugin"]
check(mv == [pv], "plugin.json version (%s) == marketplace.json %s" % (pv, mv))

print("\n%d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
EOF
