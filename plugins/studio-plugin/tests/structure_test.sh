#!/usr/bin/env bash
# Structural checks for the Studio plugin (m0-plan §2).
#
# - plugin.json fields; SCRIPTS_VERSION is a whole number; marketplace entry (when registered) matches
# - no hooks yet (M0a: an empty guard must not ship enabled)
# - SKILL.md routing list == commands/*.md; atom references exist
# - the result-contract block is byte-identical wherever it appears
# - persona templates: frontmatter name == file name, one marker region
# - JSON templates parse after placeholders are filled
# - no home-directory paths in shipped files; optional deny-term list (STUDIO_TEST_DENY_TERMS_FILE)
# - no __pycache__ in the plugin
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/.." && pwd)"
PY="${PY:-python3}"
"$PY" -B - "$PLUGIN" <<'PYEOF'
import glob, json, os, re, sys
plugin = sys.argv[1]
skill = os.path.join(plugin, "skills", "std")
fails = []
def check(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        fails.append(msg)

# manifest
pj = json.load(open(os.path.join(plugin, ".claude-plugin", "plugin.json")))
for k in ("name", "description", "version", "author", "homepage", "repository", "license"):
    check(k in pj, "plugin.json has %s" % k)
check(pj.get("name") == "studio-plugin", "plugin name is studio-plugin")
check(bool(re.fullmatch(r"\d+\.\d+\.\d+", pj.get("version", ""))), "plugin version is semver")
check("hooks" not in pj, "plugin.json declares no hooks (hooks/hooks.json only, from M0d-1)")
check(not os.path.exists(os.path.join(plugin, "hooks")), "no hooks/ yet (M0a)")
sv = re.search(r'SCRIPTS_VERSION = "([^"]+)"', open(os.path.join(skill, "scripts", "stdo", "__init__.py")).read())
check(bool(sv) and sv.group(1).isdigit(), "SCRIPTS_VERSION is a whole number (bumped only when scripts/ change)")
mp = os.path.normpath(os.path.join(plugin, "..", "..", ".claude-plugin", "marketplace.json"))
if os.path.exists(mp):
    entries = [p for p in json.load(open(mp)).get("plugins", []) if p.get("name") == "studio-plugin"]
    check(not entries or entries[0].get("version") == pj.get("version"),
          "marketplace entry absent (before registration) or same version")

# routing
text = open(os.path.join(skill, "SKILL.md")).read()
m = re.search(r"Valid commands: (.*?)\.\n", text, re.S)
routed = set(re.findall(r"`([a-z-]+)`", m.group(1))) if m else set()
files = {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(skill, "commands", "*.md"))}
check(bool(routed) and routed == files, "SKILL.md routing == commands/*.md (missing files: %s, unrouted: %s)"
      % (sorted(routed - files), sorted(files - routed)))
for a in ("_contract", "_stages", "_auditor", "_invariants", "_actors"):
    check(os.path.exists(os.path.join(skill, "commands", "atoms", a + ".md")), "atom %s exists" % a)
for p in glob.glob(os.path.join(skill, "**", "*.md"), recursive=True):
    for ref in set(re.findall(r"`(?:<<SKILL_DIR>>/)?(?:commands/)?(atoms/_[a-z_]+\.md)`", open(p).read())):
        check(os.path.exists(os.path.join(skill, "commands", ref)), "%s → %s exists" % (os.path.relpath(p, skill), ref))
for c in files - {"help"}:
    check("Not implemented yet" in open(os.path.join(skill, "commands", c + ".md")).read(),
          "commands/%s.md says not implemented yet (M0)" % c)

# result contract identical
blocks = []
for p in glob.glob(os.path.join(skill, "**", "*.md"), recursive=True):
    for b in re.findall(r"<!-- studio:result-contract -->\n(.*?)\n<!-- /studio:result-contract -->", open(p).read(), re.S):
        blocks.append((p, b))
check(len(blocks) >= 10, "result-contract block in atoms and every persona (%d)" % len(blocks))
check(len({b for _, b in blocks}) == 1, "result-contract blocks are identical")
guards = {b for p in glob.glob(os.path.join(skill, "**", "*.md"), recursive=True)
          for b in re.findall(r"<!-- studio:guard-refusal -->\n(.*?)\n<!-- /studio:guard-refusal -->", open(p).read(), re.S)}
check(len(guards) == 1, "guard-refusal (INV9) blocks are identical")

# personas
agents = sorted(glob.glob(os.path.join(skill, "templates", "agents", "std-*.md")))
check(len(agents) == 9, "9 persona templates (6 spine + 3 conditional)")
for p in agents:
    body = open(p).read()
    fm = re.match(r"---\n(.*?)\n---\n", body, re.S)
    name = re.search(r"^name: (.+)$", fm.group(1), re.M).group(1) if fm else None
    check(name == os.path.basename(p)[:-3], "%s frontmatter name" % os.path.basename(p))
    check(body.count("<!-- studio:persona:start -->") == 1 and body.count("<!-- studio:persona:end -->") == 1,
          "%s has one persona marker region" % os.path.basename(p))

# JSON templates
for p in glob.glob(os.path.join(skill, "templates", "**", "*.json.tmpl"), recursive=True):
    try:
        json.loads(re.sub(r"\{\{[A-Z_]+\}\}", "x", open(p).read()))
        ok = True
    except ValueError:
        ok = False
    check(ok, "%s parses after placeholders" % os.path.relpath(p, skill))

# shipped text: no home paths; optional deny terms from a file outside the repository
deny = []
df = os.environ.get("STUDIO_TEST_DENY_TERMS_FILE")
if df:
    deny = [l.strip().lower() for l in open(df) if l.strip() and not l.startswith("#")]
shipped = [p for p in glob.glob(os.path.join(plugin, "**", "*"), recursive=True)
           if os.path.isfile(p) and "__pycache__" not in p]
home_re = re.compile(r"/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+")
for p in shipped:
    try:
        body = open(p, encoding="utf-8").read()
    except (UnicodeDecodeError, OSError):
        continue
    rel = os.path.relpath(p, plugin)
    if home_re.search(body):
        check(False, "%s has a home-directory path" % rel)
    low = body.lower()
    for t in deny:
        if t in low:
            check(False, "%s contains a denied term" % rel)
check(True, "home-path scan over %d files%s" % (len(shipped), "" if df else " (deny terms: STUDIO_TEST_DENY_TERMS_FILE not set)"))

check(not glob.glob(os.path.join(plugin, "**", "__pycache__"), recursive=True), "no __pycache__ in the plugin")

if fails:
    print("structure: %d failure(s)" % len(fails))
    sys.exit(1)
print("structure: ok")
PYEOF
