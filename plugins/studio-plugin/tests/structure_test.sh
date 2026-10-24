#!/usr/bin/env bash
# Structural checks for the Studio plugin (m0-plan §2).
#
# - plugin.json fields; SCRIPTS_VERSION is a whole number; marketplace entry (when registered) matches
# - hooks/hooks.json registers the guard (M0d-1b); the commit checks and hook templates (M0e)
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
hj = os.path.join(plugin, "hooks", "hooks.json")
check(os.path.exists(hj), "hooks/hooks.json exists (M0d-1b)")
if os.path.exists(hj):
    hooks = json.load(open(hj)).get("hooks", {})
    pre = hooks.get("PreToolUse", [])
    ok = len(pre) == 1 and len(pre[0].get("hooks", [])) == 1 and set(hooks) == {"PreToolUse"}
    h = pre[0]["hooks"][0] if ok else {}
    check(ok and h.get("onFailure") == "block" and h.get("timeout") == 20 and h.get("type") == "command"
          and h.get("command") == 'python3 "${CLAUDE_PLUGIN_ROOT}/skills/std/scripts/guard.py"',
          "the guard hook: one PreToolUse command, timeout 20, onFailure block, quoted plugin path")
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
IMPLEMENTED_CMDS = {"help", "init", "config", "update", "source"}  # M1c · M1d
for c in files - IMPLEMENTED_CMDS:
    check("Not implemented yet" in open(os.path.join(skill, "commands", c + ".md")).read(),
          "commands/%s.md says not implemented yet" % c)
for c in IMPLEMENTED_CMDS - {"help"}:
    check("Not implemented yet" not in open(os.path.join(skill, "commands", c + ".md")).read(),
          "commands/%s.md is implemented (M1c)" % c)

# parallel-call contract (m1-plan §3.5): every command document that runs an approval asks first and runs the
# approval command alone in a later message
for p in glob.glob(os.path.join(skill, "commands", "**", "*.md"), recursive=True):
    body = open(p).read()
    if re.search(r"state\.py (approve|overlay)(?![-\w])|setup\.py (config set|narrator set|update apply)", body):
        check("never in the same message" in body,
              "%s: a gate is the question, then (a later message) one approval command" % os.path.relpath(p, skill))

# no variable in command position (M1a review NIT A): a command document runs Studio's scripts (run_s2v.py, lock.py,
# state.py, …) or a literal path — never "$S2V …", "${X} …" or a backquoted command word (the guard refuses those)
cmd_re = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
for p in glob.glob(os.path.join(skill, "commands", "**", "*.md"), recursive=True):
    body = open(p).read()
    fenced = re.findall(r"```[^\n]*\n(.*?)```", body, re.S)
    inline = re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", body, flags=re.S))
    bad = []
    for sn in [l for f in fenced for l in f.splitlines()] + inline:
        for seg in cmd_re.split(sn.strip()):
            words = [w for w in seg.strip().split() if not re.match(r"^[A-Z_][A-Z0-9_]*=", w)]
            if words and ("$" in words[0] or "`" in words[0]):
                bad.append(seg.strip()[:60])
            if "main.js" in seg and "$" in seg:
                bad.append(seg.strip()[:60])
    check(not bad, "%s: no variable in command position (%s)" % (os.path.relpath(p, skill), "; ".join(bad[:3])))

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
check(len(agents) == 10, "10 persona templates (6 spine + 3 conditional + the external auditor)")
aud = open(os.path.join(skill, "templates", "agents", "std-auditor.md")).read()
check(re.search(r"^tools: Read, Grep, Glob$", aud, re.M) is not None, "std-auditor reads only (tools: Read, Grep, Glob)")
# J29 (M1b review Y10): the overlay question lists every key with its number of entries
cfgdoc = open(os.path.join(skill, "commands", "config.md")).read()
for k in ("hosts", "sources", "terms", "videos", "actors"):
    check(("internal.%s: <N>개" % k) in cfgdoc, "config.md: the overlay question shows internal.%s and its count" % k)
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

# the guard's scanner (M0d-1a): no subprocesses, no state writes
gdir = os.path.join(skill, "scripts", "stdo", "guard")
for p in sorted(glob.glob(os.path.join(gdir, "*.py"))):
    body = open(p).read()
    rel = os.path.relpath(p, skill)
    if os.path.basename(p) != "gitprobe.py":  # the guard's only child processes (git previews, M0d-1b)
        check("subprocess" not in body and "os.system" not in body and "os.popen" not in body,
              "%s starts no subprocess" % rel)
    check(not re.search(r"from \.\.state import .*(store|gates|backup|evidence|cli)|import store|stdo\.state\.(store|gates|backup|evidence|cli)", body),
          "%s does not import state writers" % rel)
# ...and not transitively either: lockargs (shared with lock.py) owns UsageError so that the guard
# does not import locks -> dirlock (which run `ps` through subprocess)
import subprocess as _sp
probe = _sp.run([sys.executable, "-B", "-c", "import sys; sys.path.insert(0, %r); import stdo.guard; "
                 "print('subprocess' in sys.modules)" % os.path.join(skill, "scripts")], capture_output=True, text=True)
check(probe.stdout.strip() == "False", "importing stdo.guard loads no subprocess module (%s)" % probe.stdout.strip())

# M0e: commit checks and the hook installer
scripts = os.path.join(skill, "scripts")
for name in ("check_commit.py", "hooks.py"):
    body = open(os.path.join(scripts, name)).read()
    check("sys.dont_write_bytecode = True" in body, "%s writes no bytecode" % name)
    check(os.access(os.path.join(scripts, name), os.X_OK), "%s is executable" % name)
for mod in ("commit/cli.py", "commit/checks.py", "commit/stage.py", "commit/rangecheck.py", "commit/okfile.py",
            "commit/kinds.py", "commit/approvals.py", "commit/inprogress.py", "commit/spaths.py", "commit/gitx.py",
            "hooks/cli.py", "hooks/install.py", "hooks/templates.py", "ignore.py", "guard/hookfiles.py"):
    check(os.path.exists(os.path.join(scripts, "stdo", mod)), "stdo/%s exists" % mod)
sys.path.insert(0, scripts)
sys.dont_write_bytecode = True
from stdo import ignore as _ign
from stdo.hooks import templates as _tpl
check(open(os.path.join(skill, "templates", "studio", "gitignore.tmpl")).read() == _ign.TEMPLATE,
      "the ignore block in stdo/ignore.py == templates/studio/gitignore.tmpl")
for nm, text in (("runner", _tpl.runner(["studio"])), ("shim", _tpl.shim()), ("husky", _tpl.husky_block()),
                 ("lefthook", _tpl.lefthook_block())):
    check(_tpl.MARK in text, "hook template %s carries the studio:hook mark" % nm)
    check(not re.search(r"/(Users|home)/[A-Za-z]", text) and "~/" not in text, "hook template %s has no home path" % nm)
for d in ("commit", "hooks"):
    for p in glob.glob(os.path.join(scripts, "stdo", d, "*.py")):
        check(not re.search(r"\bguard\b", "".join(l for l in open(p) if l.startswith(("from", "import")))),
              "%s (copied into repositories) does not import the guard (plugin only)" % os.path.relpath(p, skill))
check(sv and sv.group(1) == "12", "SCRIPTS_VERSION is 12 (M1d: resolve_assets, check_scope, checked images)")
from stdo import manifest as _man
_mp = os.path.join(scripts, _man.NAME)
check(os.path.exists(_mp) and open(_mp).read() == _man.render(scripts, sv.group(1)),
      "scripts/MANIFEST.sha256 lists every copied script with its sha (run tests/tools/manifest.py)")
check("stdo/guard/judge.py" not in open(_mp).read() and "guard.py" not in _man.files(scripts),
      "the manifest leaves out the guard (plugin only)")
check("setup.py" not in _man.files(scripts) and not [f for f in _man.files(scripts) if f.startswith("stdo/setup/")],
      "the manifest leaves out setup.py and stdo/setup/ (plugin only, m1-plan §5.1)")
check(os.access(os.path.join(scripts, "setup.py"), os.X_OK) and
      "sys.dont_write_bytecode = True" in open(os.path.join(scripts, "setup.py")).read(),
      "setup.py is executable and writes no bytecode")
_bad = [os.path.relpath(p, skill) for p in glob.glob(os.path.join(scripts, "stdo", "*", "*.py")) +
        glob.glob(os.path.join(scripts, "stdo", "*.py")) if "/stdo/setup/" not in p and "/stdo/guard/" not in p
        and re.search(r"^\s*(from|import) .*\bsetup\b", open(p).read(), re.M)]
check(not _bad, "the copied scripts do not import setup (plugin only): %s" % ", ".join(_bad))

if fails:
    print("structure: %d failure(s)" % len(fails))
    sys.exit(1)
print("structure: ok")
PYEOF
