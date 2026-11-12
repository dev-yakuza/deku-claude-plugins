#!/usr/bin/env bash
# Structural checks for the Studio plugin (m0-plan §2).
#
# - plugin.json fields; SCRIPTS_VERSION is a whole number; the marketplace entry matches plugin.json
# - released wording in the shipped documents; the three READMEs have the same ## headings count (m1k-plan item 7)
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
entries = [p for p in json.load(open(mp)).get("plugins", []) if p.get("name") == "studio-plugin"] \
    if os.path.exists(mp) else []
check(len(entries) == 1, "the marketplace has one studio-plugin entry (0.1.0, m1k-plan item 7)")
for k, want in (("version", pj.get("version")), ("description", pj.get("description")),
                ("source", "./plugins/studio-plugin")):
    check(bool(entries) and entries[0].get(k) == want, "the marketplace entry's %s is plugin.json's" % k)

# the released wording (m1k-plan item 2): no development banner, no 0.0.x, no "not in the marketplace", no internal
# milestone names in what a person or the model reads — the READMEs outside their version notes
VERSION_NOTES = {"README.md": "## Version notes", "README.ko.md": "## 버전 노트", "README.ja.md": "## バージョンノート"}
UNRELEASED = [(re.compile(r"in development", re.I), "in development"), (re.compile("開発中"), "開発中"),
              (re.compile("개발 중"), "개발 중"), (re.compile(r"0\.0\.x"), "0.0.x"),
              (re.compile(r"not in the marketplace", re.I), "not in the marketplace"),
              (re.compile("마켓플레이스에 없"), "마켓플레이스에 없"), (re.compile("マーケットプレイスにな"), "マーケットプレイスにない"),
              (re.compile(r"\bM\d+[a-z]?\b"), "a milestone name")]
heads = {}
for n, notes in VERSION_NOTES.items():
    text = open(os.path.join(plugin, n), encoding="utf-8").read()
    heads[n] = len(re.findall(r"(?m)^## ", text))
    check(notes in text, "%s has its version notes (%s)" % (n, notes))
check(len(set(heads.values())) == 1, "the three READMEs have the same number of ## headings (%s)" % heads)
shipped_docs = [os.path.join(skill, "SKILL.md"), os.path.join(plugin, ".claude-plugin", "plugin.json")] + \
    glob.glob(os.path.join(skill, "commands", "*.md")) + glob.glob(os.path.join(skill, "commands", "atoms", "*.md")) + \
    glob.glob(os.path.join(plugin, "docs", "*.md"))
texts = {os.path.relpath(p, plugin): open(p, encoding="utf-8").read() for p in shipped_docs}
for n, notes in VERSION_NOTES.items():
    text = open(os.path.join(plugin, n), encoding="utf-8").read()
    before, _sep, after = text.partition(notes)
    texts[n + " (outside the version notes)"] = before + ("\n## " + after.split("\n## ", 1)[1] if "\n## " in after
                                                          else "")
for rel, text in sorted(texts.items()):
    found = [label for rx, label in UNRELEASED if rx.search(text)]
    check(not found, "%s: no unreleased wording (%s)" % (rel, ", ".join(found) or "none"))

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
IMPLEMENTED_CMDS = {"help", "init", "config", "update", "source", "brief", "script", "verify", "make", "board", "render", "copy", "status", "resume",
                    "abandon"}  # M1c–M1i
for c in files - IMPLEMENTED_CMDS:
    check("Not implemented yet" in open(os.path.join(skill, "commands", c + ".md")).read(),
          "commands/%s.md says not implemented yet" % c)
for c in IMPLEMENTED_CMDS - {"help"}:
    check("Not implemented yet" not in open(os.path.join(skill, "commands", c + ".md")).read(),
          "commands/%s.md is implemented (M1c)" % c)

# parallel-call contract (m1-plan §3.5; 0.0.25 P15): every command document that runs an approval asks first and runs
# the approval command alone as the next tool call of the same turn, never in the question's assistant message
NEXT_CALL = ("next tool call, in the same turn", "never in the same assistant message")
for p in glob.glob(os.path.join(skill, "commands", "**", "*.md"), recursive=True):
    body = " ".join(open(p).read().split())
    if re.search(r"state\.py (approve|overlay)(?![-\w])|setup\.py (config set|narrator set|update apply)", body):
        check(all(s in body for s in NEXT_CALL),
              "%s: a gate is the question, then (the next tool call) one approval command" % os.path.relpath(p, skill))
    check("in a later message" not in body, "%s: no \"in a later message\" (0.0.25 P15)" % os.path.relpath(p, skill))
# every P15 place (mirrors test_pilot2.P15_PLACES): abandon, resume (unlock) and init (git commit) too
for _d in ("abandon", "verify", "make", "render", "copy", "board", "config", "update", "init", "resume", "atoms/_stages"):
    _b = " ".join(open(os.path.join(skill, "commands", _d + ".md")).read().split())
    check(all(s in _b for s in NEXT_CALL), "commands/%s.md: the approval runs as the next tool call (0.0.25 P15)" % _d)

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
# 0.0.25 (P11, P14): a refusal that says "This is not a stop" is followed — in every block, the contract and every role
NOT_A_STOP = ("Exception: when the refusal itself says 'This is not a stop', do what it says — that is not reaching the "
              "same effect another way.")
_nblocks = [b for p in glob.glob(os.path.join(skill, "**", "*.md"), recursive=True)
            for b in re.findall(r"<!-- studio:guard-refusal -->\n(.*?)\n<!-- /studio:guard-refusal -->", open(p).read(), re.S)]
check(len(_nblocks) == 16 and all(NOT_A_STOP in " ".join(b.replace(">", " ").split()) for b in _nblocks),
      "every guard-refusal block (%d) holds the exception sentence" % len(_nblocks))
READ_WRITE = ("Read files with Read and write your outputs (if any) with Write or Edit. Never use `python -c`, heredocs "
              "or generator scripts for file work: the guard refuses them. For ids, lists and skeletons use the Studio "
              "commands your stage names.")
_ct = open(os.path.join(skill, "commands", "atoms", "_contract.md")).read()
_ca = " ".join(_ct.split("## A.", 1)[1].split("## B.", 1)[0].split())
check(READ_WRITE in _ca, "_contract.md §A: the Read/Write line (0.0.25 P14)")
check(NOT_A_STOP in " ".join(open(os.path.join(skill, "commands", "atoms", "_invariants.md")).read().split()),
      "_invariants.md: INV9 has the exception sentence")
for p in glob.glob(os.path.join(skill, "templates", "agents", "std-*.md")):
    _t = " ".join(open(p).read().split())
    if p.endswith("std-auditor.md"):
        check(READ_WRITE not in _t, "std-auditor keeps its own read-only rule")
        continue
    check(READ_WRITE in _t and NOT_A_STOP in _t, "%s: the Read/Write line and the guard rule's exception (0.0.25)"
          % os.path.basename(p))

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

# fix20: the 0.0.26 guard as a backstop — guard/legacy is the guard of d2028cc (0.0.26), frozen. Each file: line 1 the
# FROZEN header, then HEAD's text with two mechanical rewrites (one more dot on `from ..` import lines; one more
# dirname on the `os.path.abspath(__file__)` lines). Reversed, the sha256 must be HEAD's:
#   git show d2028cc:plugins/studio-plugin/skills/std/scripts/stdo/guard/<name> | shasum -a 256
# Regenerate only if the backstop is ever re-based on another release (tests/README.md).
LEGACY_HEAD = {
    "__init__.py": "af6fc43eec9a405bbadb77c576fba0d949ce4e828ce13627abf2f345615fb287",
    "allowrule.py": "e97908090ae05f4baf51a86a0d3bb14a253b64f7225fe9d3f8db0475b071c8cd",
    "approve.py": "2f048427bb2c36af3ecd01d9a9de6901fe004022dbe440325b165c94d59e5af9",
    "auditor.py": "231d7e25664b625f12be565e50b75559094ff2116425fab3a82ebfdcc9eca039",
    "commitrule.py": "de705c0b707a02c86f8f423dd06c9508927f1fc039f56e9708534f0c78de1042",
    "gitprobe.py": "33617933cdb032c12c5e5e4caaa66f7e4a949262e6e7fca540f1d155be7fd896",
    "hookfiles.py": "33c3dc8b307f11775aed2780be25761e8cd019e839dffa1f926d07578bc5f3c0",
    "judge.py": "0e887364362c577bbbfdc0406efa0f5f0b21402e53079407f670515e0293f590",
    "lex.py": "32ec72022ad312e4db27b4208a810f00b198bd0fccd13f33e11119af8201446c",
    "limits.py": "4344adde3afd65c35e07231a533125ee7987998e10a9dc757f034d763402c7d9",
    "messages.py": "e0cb139b1dcf76bc9b139ca7d5dcdd564357a6b439967b3b2fef064c379c6c92",
    "model.py": "0dff811015ef96843abebf2e4652fbacfdd0b5ab381cb7abe5aa3c94cce90691",
    "parse.py": "5816fd146e3aeff0a4158e34197d7232c7d9ca816b4951667452567578ade11a",
    "patchtargets.py": "67781a53bb418f505bd66e9bee4a82041cb3832c314a004de5d99804fad77bde",
    "protect.py": "2290aef58e675d2a8b583744d9f524ff04a1d9c759bb7f308a6570da1ecb4d43",
    "proxy.py": "68edb3184e9809e61e5a8c397158339896e01cb704dcec4bd50d7ae10d78bc90",
    "push.py": "60d54c4700b742fd3f773f504752336a0094cb6162ac49bb592bbd2a7f1d4d3a",
    "ranlog.py": "58b6443d6b5f4ef7a821c14c68bba7c952348f89bff03e7a163caca60b3736f8",
    "recog.py": "74c5e345cc86489b2564c1b7f404181da9b26b032ba2c8c73fb139acfc83ed42",
    "repos.py": "816578353c6bab01938c8c32df9a72b82eb84417e59aef3349a93c7b68eb47e0",
    "scanctx.py": "c43af0bc81b54117c0f0bf97ce67de6825c55f617cd09298190646e7945b0b43",
    "sedshape.py": "b8f584b8859ae7d74658d94a567182f70e42d51d328f9b2caa91ad12199c13ba",
    "snapshot.py": "78a2552bf3b975aa61822bb7d6f6f0e2834dc93d243bcd15c3467df0374a7c3b",
    "terms.py": "3b16bc83968c75c9d84c7b31014525318c3dad673fa895c7cdf523fc85826487",
    "transcript.py": "6d43c958516e94c94993152fcb82cb9c67a6d952fc4d43ea6a7758000a69a84d",
    "version.py": "b67951616c634a5facdab35d3f5d92f9e84a945ff980bdfa07bac72d7e3b1002",
    "walk.py": "67be6561f9dd0a6d0dd367a2d68087eb9fdf91322ecec39b71c9d3b7936dca26",
    "web.py": "12bdfd1ba97bb1daa7dcfa9d7f33fe0ef4415798bed517914e75911c17d76d47",
    "where.py": "d87213ba54b03991d7d3a7e9d69613a43108f0d757561dbf2fbd18fc222d0b5e",
}
ldir = os.path.join(gdir, "legacy")
check(sorted(n for n in os.listdir(ldir)) == sorted(LEGACY_HEAD),
      "guard/legacy holds exactly the 29 files of the 0.0.26 guard (no __pycache__, nothing else)")
import hashlib as _hl
for _n, _h in sorted(LEGACY_HEAD.items()):
    _p = os.path.join(ldir, _n)
    if not os.path.exists(_p):
        continue
    _lines = open(_p, encoding="utf-8").read().split("\n")
    check(_lines[0] == "# FROZEN copy of guard/%s at d2028cc (0.0.26) \u2014 the backstop (fix20). Do not edit; see "
          "guard/backstop.py." % _n, "legacy/%s starts with the FROZEN header" % _n)
    _back = []
    for _l in _lines[1:]:
        if re.match(r"^\s*from \.\.\.", _l):
            _l = re.sub(r"^(\s*)from \.\.\.", r"\1from ..", _l, count=1)
        _l = _l.replace("os.path.abspath(os.path.dirname(__file__))", "os.path.abspath(__file__)")
        _back.append(_l)
    check(_hl.sha256("\n".join(_back).encode("utf-8")).hexdigest() == _h,
          "legacy/%s is the 0.0.26 file but for the two rewrites (frozen: do not edit)" % _n)
    _body = open(_p).read()
    if _n != "gitprobe.py":
        check("subprocess" not in _body and "os.system" not in _body and "os.popen" not in _body,
              "legacy/%s starts no subprocess" % _n)
    check(not re.search(r"from \.\.\.?state import .*(store|gates|backup|evidence|cli)|import store|"
                        r"stdo\.state\.(store|gates|backup|evidence|cli)", _body),
          "legacy/%s does not import state writers" % _n)
    check(not re.search(r"^\s*from \.\.(?!\.)", _body, re.M), "legacy/%s imports nothing from the guard outside legacy" % _n)
probe = _sp.run([sys.executable, "-B", "-c", "import sys; sys.path.insert(0, %r); import stdo.guard.judge, "
                 "stdo.guard.backstop; print(any(m.startswith('stdo.guard.legacy') for m in sys.modules))"
                 % os.path.join(skill, "scripts")], capture_output=True, text=True)
check(probe.stdout.strip() == "False", "importing the guard does not import guard/legacy (loaded only after G1 passes, "
      "or for its push / commit check) (%s)" % (probe.stdout.strip() or probe.stderr.strip()[-200:]))
_jb = open(os.path.join(gdir, "judge.py")).read()
check("push.check(" not in _jb and "commitrule.evaluate(" not in _jb and "backstop.shared_push(" in _jb and
      "backstop.shared_commit(" in _jb, "the guard's push / commit checks are the frozen 0.0.26 ones, shared with the "
      "backstop (backstop.shared_push / shared_commit; P20-4)")
# P20-9: the 0.0.26 guard also runs the current non-guard modules below (its imports, and theirs). They must stay
# what 0.0.26 shipped, or "legacy" changes silently; an intended change goes into LEGACY_DEPS_CHANGED with its reason,
# and the backstop's stage A (legacy == 0.0.26 on the review corpora) is run again (tests/README.md).
LEGACY_DEPS_HEAD = {
    "stdo/__init__.py": "2d960c8d9fa81f1dbfdfb186a9d83c1ff54fcd4b5d3364afb40531887f48d085",
    "stdo/commit/__init__.py": "bef8ad14e2731cd78c59cdccdede1b18c436be93110299702b4423353c5c4bf7",
    "stdo/commit/approvals.py": "c9fc77c8c6d891583eb681e0204063d9a8d35777305b75f92962d44477882a83",
    "stdo/commit/checks.py": "2db328f7702dca5a8fddb6c48ff64ab6d9ecbaa0f5b4e1a18365ca0f712ca5a1",
    "stdo/commit/gitx.py": "e5a37e5107aa36cf6ed6dec4ef31ed0b1bcaf848ef3948ef805fd1002bbc9103",
    "stdo/commit/inprogress.py": "bcc4048fd629006cb8932aa784d6d22671eee735d82743d6e309ab5f29d68d4d",
    "stdo/commit/kinds.py": "f409629cd4a5ad8643a49c4cf6a5a034c407bc41cafb8f826d6f10b16943b542",
    "stdo/commit/okfile.py": "13f8639adff61a3b502500237c9fa9e698d87555c3fc6534f7c4cb08e9f206cb",
    "stdo/commit/rangecheck.py": "419929606f1b9aa428eb14cc55efa74e133f23682723b74d11e60977116d0222",
    "stdo/commit/spaths.py": "d72edf6c4dceeed771b2c20809bc63d8f5b711b9fd6a6c3355b9ee12ae65409f",
    "stdo/commit/summary.py": "34fece001d63c61500afdbddbb28fec82007471fad157d07c23017f524ddeaac",
    "stdo/hooks/__init__.py": "08f387c86fcf2587a7f735d7b758f68ecbbfd248894568c352b9ca1967012566",
    "stdo/hooks/templates.py": "13499e58f682671f62cd505fd8878c745a5537d0bff169e8bf2d3fb3ac8fc020",
    "stdo/ignore.py": "94f5b3cd3b9c0cd092589331667ba2f1b9d4b0989906321ef120c38061a149e5",
    "stdo/lockargs.py": "1f4d4377aa3c19c763d44bb07a854778d77719a40f9e6da7340f6fef8a2b480e",
    "stdo/machine.py": "727461893226a94047e529ecbc3b4cea8a7e43036374a8a32906307c303a5f22",
    "stdo/manifest.py": "52c83058a0c4207eab77a1a8663a5cfc13c249a243aa8b76c7292e0097151d8b",
    "stdo/narrator.py": "cea9fca6fea4f849ef43f287f142ed3b9e831df35873381152407287f677fac8",
    "stdo/paths.py": "3c18601f099b60cbe59c8670188e85ec7d70d8f7b835b50ab225dbf37b7dc5b4",
    "stdo/s2vcall.py": "96e585e0a429714d0de495845d7a05c9f0817123f7537819c92c03b46088967c",
    "stdo/sandbox.py": "2401e289a6cdff2861d5d6b34329f64adfaeb694a59d3531a97482cc24de18c9",
    "stdo/setup/__init__.py": "535e780a0d274f6306e34626f1217b8e6b9e2dfa4af9b2b8b7563bda75e8f483",
    "stdo/setup/doc.py": "afa4a091bc8102f2136f3f0dcb8ef6cced0c1cd44d4891a272d53d74525e86cc",
    "stdo/setup/labels.py": "fcdcf5a013119cb6738508040b21d2b78317305aa177799ab01e270f8b199982",
    "stdo/state/__init__.py": "df31d9840c93a3e14a9d0bcf104cedaf24b45f3d81df3041bd00a68c436eeb43",
    "stdo/state/argv.py": "012294853f2a276a27733f78bc7917354e84712917bbebb5a71857e281e267a4",
    "stdo/state/commands.py": "4eee67d2b50ceafe58c9364de105de76e733590241f98df39c8342bfef521476",
    "stdo/state/hashes.py": "bc9fa3492a56bcbab622a8d6a4f31eb3cb413179b2f4df6928be2d98d82f69ca",
    "stdo/state/labels.py": "7a2c9970c855a18284338ea987d119bc0beb918112e202f109bdc36393a84fc9",
    "stdo/state/router.py": "ced202b482e6dd6a129e13548e4c049b9b8d132798852d6801af367f3e026e88",
    "stdo/state/schema.py": "15ddffa9433c5e026a0441e5d5bbf45c60c7a0007b2b9f6d132b5290a895d833",
    "stdo/state/store.py": "645591bde86c74a74a83969912fb4a895300785c0d2bd92a79fcc314395bdb01",
    "stdo/state/tuples.py": "d4a5fa75c8863a91fe105d7c3f3811795af879045e370ccf5bfb7c54bdf6b390",
    "stdo/text/__init__.py": "d83f94b333b2d9b7744eae6c6524d396605b58b3694ff16ef776fe12dd395e2e",
    "stdo/text/normalize.py": "a825f44d3a56226d5ed35599a68fd59079939a87f202a831e9760af8986b55fc",
    "stdo/writes.py": "e9c25585c4a4414fe145b901242ca4a47a2cde831bd619ddbc83cf2f11a92c56",
}
# intended changes since d2028cc, each with a one-line reason (none so far; SCRIPTS_VERSION in stdo/__init__.py and
# RUNNER_VERSION in stdo/hooks/templates.py are the likely ones)
LEGACY_DEPS_CHANGED = {
    "stdo/__init__.py": "0.0.28: SCRIPTS_VERSION 25",
    "stdo/state/argv.py": "0.0.28 (fix-0028 §1): --since-last is a flag (status takes no value for it)",
    "stdo/state/commands.py": "0.0.28 (fix-0028 §13): ask-before is evidence-free and implemented (no deny)",
    "stdo/commit/summary.py": "0.0.28 (fix-0028 §11): the value block shows brand.json's name, accent and logo",
    "stdo/state/store.py": "0.0.28 (fix-0028 §1.1): video_dir refuses an id that is not a video id (exit 2)",
}
for _f, _h in sorted(LEGACY_DEPS_HEAD.items()):
    _p = os.path.join(skill, "scripts", _f)
    _cur = _hl.sha256(open(_p, "rb").read()).hexdigest() if os.path.exists(_p) else None
    check(_cur == _h or _f in LEGACY_DEPS_CHANGED,
          "%s, run by the 0.0.26 guard, is unchanged since 0.0.26 (or listed in LEGACY_DEPS_CHANGED)" % _f)

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
_bg = open(os.path.join(skill, "templates", "guides", "board.md")).read()
check("otherwise a text card" not in _bg,
      "guides/board.md does not send board to a text card (blocks are in the content hash: script stage, 0.0.22)")
check(sv and sv.group(1) == "25", "SCRIPTS_VERSION is 25 (0.0.28: the writer's frontmatter lines from next --enter "
      "script, the targetDuration range, every s2v message, ask-before, record-source --url, the ② ③ ④a question "
      "blocks, floor_text, the copy's source line, brand lines in the value block)")
# 0.0.23 (pilot-1 P4): every gate document has the agent paste the printed question block, never retyping a line
for _d in ("make", "copy", "verify", "board"):
    _t = open(os.path.join(skill, "commands", _d + ".md")).read()
    check("`question` block" in _t and "never retype a line" in _t,
          "commands/%s.md asks with the `question` block pasted unchanged (never retype a line)" % _d)
# 0.0.28 (pilot-3 Q13 · Q14): every command document's Rules paragraph has the three shell-habit clauses
for _p in sorted(glob.glob(os.path.join(skill, "commands", "*.md"))):
    _t = open(_p).read()
    _m = re.search(r"^Rules[^\n]*(?:\n(?!\n)[^\n]*)*", _t, re.M)
    if _m:
        _r = " ".join(_m.group(0).split())
        check("Run Studio commands exactly as written: no `| head`" in _r and
              "Do not repeat a call whose output is already in the conversation" in _r and
              "with `open <path>` only" in _r,
              "commands/%s's Rules line has the three shell-habit clauses (exact commands, no repeats, open only)"
              % os.path.basename(_p))
# 0.0.23 (pilot-1 P8): the ignore block re-includes nothing and ignores the credits draft
_gi = open(os.path.join(skill, "templates", "studio", "gitignore.tmpl")).read()
check(not [l for l in _gi.splitlines() if l.startswith("!")] and "/videos/*/CREDITS.draft.yaml" in _gi,
      "gitignore.tmpl has no ! line and ignores videos/*/CREDITS.draft.yaml")
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

# M1j §12.1: make.md composes the stage documents, and the documents agree with the state machine
_cmd = os.path.join(skill, "commands")
_mk = open(os.path.join(_cmd, "make.md")).read()
_order = ["source", "brief", "script", "verify", "board", "render", "copy"]
_pos = [_mk.find("`setup.py doc %s`" % d) for d in _order]
check(all(p >= 0 for p in _pos) and _pos == sorted(_pos), "make.md reads the stage documents in order (%s)" % _pos)
check(all(d in IMPLEMENTED_CMDS for d in _order + ["make"]), "every document make.md reads is implemented")
for d in sorted(IMPLEMENTED_CMDS - {"help", "init", "config", "update"}):
    check("<!-- studio:guard-refusal -->" in open(os.path.join(_cmd, d + ".md")).read(),
          "commands/%s.md carries the INV9 block" % d)
_stage_doc = {"brief": "brief", "script": "script", "verify": "verify", "cast": "make", "tts": "make",
              "audition": "make", "board": "board", "visual-check": "board", "render": "render", "copy": "copy"}
sys.path.insert(0, scripts)
from stdo.state import schema as _schema
for st, d in sorted(_stage_doc.items()):
    body = open(os.path.join(_cmd, d + ".md")).read()
    check(re.search(r"state\.py next <video> --enter %s\b" % re.escape(st), body) is not None,
          "commands/%s.md enters %s with `state.py next --enter`" % (d, st))
    if st in _schema.DONE_STAGES:
        check(re.search(r"state\.py stage-done <video> %s\b" % re.escape(st), body) is not None,
              "commands/%s.md records %s with `state.py stage-done`" % (d, st))


def _item(body, pos):
    """The numbered or bulleted list item (or paragraph) of `body` that holds position `pos`."""
    starts = [m.start() for m in re.finditer(r"(?m)^(\s*(\d+\.|-) |$|#)", body) if m.start() <= pos]
    start = starts[-1] if starts else 0
    m = re.compile(r"(?m)^(\s*(\d+\.|-) |$|#)").search(body, pos + 1)
    return body[start:m.start() if m else len(body)]


def _section(body, pos):
    a = body.rfind("\n#", 0, pos)
    b = body.find("\n#", pos)
    return body[a if a >= 0 else 0:b if b >= 0 else len(body)]


# M1j review A5: the rule is where the approval is — in the same list item as the approve command, after an
# AskUserQuestion of the same section
for gate, d in (("1", "verify"), ("2", "make"), ("3", "board"), ("4a", "render"), ("4b", "copy")):
    body = open(os.path.join(_cmd, d + ".md")).read()
    m = re.search(r"state\.py approve <video> %s --expect" % gate, body)
    item = _item(body, m.start()) if m else ""
    sec = _section(body, m.start()) if m else ""
    item = " ".join(item.split())
    ok = m is not None and all(s in item for s in NEXT_CALL) \
        and 0 <= sec.find("AskUserQuestion") < sec.find("state.py approve <video> %s" % gate)
    check(ok, "gate %s: commands/%s.md asks, then approves alone (the rule in the approve item)" % (gate, d))
_c = _mk.find('`git commit -m "<message>"`')
check(_c >= 0 and all(s in " ".join(_item(_mk, _c).split()) for s in NEXT_CALL) and "AskUserQuestion" in _item(_mk, _c),
      "make.md: the video commit asks, then runs git commit alone")
for p in glob.glob(os.path.join(_cmd, "*.md")):
    body = open(p).read()
    for w in ("lock.py run --kind tts", "run_s2v.py render"):
        for m in re.finditer(re.escape(w), body):
            it = _item(body, m.start())
            if "run_in_background" in it or "python3 .claude" not in it and "`%s" % w not in it:
                continue
            check(False, "%s runs %s in the background (item: %s)" % (os.path.basename(p), w, it.strip()[:80]))

# 0.0.24 (pilot-1 P6): documents are printed by `setup.py doc <name>`, never opened with Read (each read of the plugin
# folder asks the person); the skill pre-approves exactly that command for its first turn
_skill_md = open(os.path.join(skill, "SKILL.md")).read()
_fm = re.match(r"---\n(.*?)\n---\n", _skill_md, re.S)
_rules = re.findall(r"(?m)^  - '(.*)'$", _fm.group(1).split("allowed-tools:", 1)[1]) if _fm and \
    "allowed-tools:" in _fm.group(1) else []
_rule = 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py" doc *)'
check(_rules == [_rule], "SKILL.md allowed-tools is exactly %s (%s)" % (_rule, _rules))
_body = _skill_md[_fm.end():] if _fm else _skill_md
_prefix = _rule[len("Bash("):-len("*)")]
check(_body.count(_prefix + "<name>") >= 2, "SKILL.md runs the same quoted command as its rule (%s<name>)" % _prefix)
check("Never use Read, Grep or Glob on the skill folder" in _body, "SKILL.md: never Read/Grep/Glob the skill folder")
check("never `$0` itself" in _body, "SKILL.md: the name is copied from the list, never $0 itself")
_mds = glob.glob(os.path.join(skill, "**", "*.md"), recursive=True)
check(not [p for p in _mds if "<<SKILL_DIR>>/commands/" in open(p).read()], "no document names <<SKILL_DIR>>/commands/")
_loose = ["%s:%d" % (os.path.relpath(p, skill), i) for p in _mds for i, l in enumerate(open(p), 1)
          if re.search(r"commands/[A-Za-z_/]+\.md", l) and "setup.py doc" not in l]
check(not _loose, "a commands/<name>.md mention only on a line with `setup.py doc` (%s)" % ", ".join(_loose[:5]))
from stdo.setup import doc as _doc
check(set(_doc.names()) == routed | {"_contract", "_stages", "_auditor", "_invariants", "_actors"},
      "setup.py doc names == SKILL.md routing list + the five atoms")

# 0.0.24 (pilot-1 P7): init asks with pickable options (mirrors test_pilot1b.InitText)
_init = open(os.path.join(skill, "commands", "init.md")).read()
_flat = " ".join(_init.split())
_typeit = [w for l in _init.splitlines() if "Never add an option that means" not in l
           for w in re.findall(r"`([^`]+)`", l) if any(t in w for t in ("직접 입력", "Other로", "기타"))]
check(not _typeit, "init.md has no option meaning \"I'll type it\" (%s)" % ", ".join(_typeit))
for _s in ("Never add an option that means", "목록에 없으면 직접 입력해 주세요", "never naming a UI label",
           "Only the first question says so", "the other questions do not repeat it",
           "at most 4 questions per call and 2–4 options per question",
           "Only after the language is answered: the default narrator", "**in a plain message**",
           "never mention hooks in a question", "`ask_husky`", "`public_domains`", "`brand_colors`", "`logos`"):
    check(_s in _flat, "init.md: %s" % _s)

# 0.0.26 (pilot-2 N3 · N4 · N5, fix-0026 §6): init's call sequence (mirrors test_pilot2b_init.InitSequence)
_c = [_flat.find(m) for m in ("**Call 1**", "**Purpose message**", "**Call 2**", "**Call 3**", "**Each question**")]
check(-1 not in _c and _c == sorted(_c), "init.md: Call 1 → purpose message → Call 2 → Call 3")
check("`web_roots`" in _flat[_c[0]:_c[1]] and "accent" not in _flat[_c[0]:_c[1]], "init.md: web_roots in call 1, accent not")
check("logo" not in _flat[_c[2]:_c[3]] and "logo" in _flat[_c[3]:_c[4]], "init.md: the logo in call 3")
for _s in ("The free-input line is on the language question only",
           "may carry an accent and fail the ② pronunciation check (CER ≤ 0.15)",
           "`narrator_candidates`", "`project_names`", "`image_folders`", "`via_web_root: true`",
           "only `logos` entries with `video: true`", "commit the logo first, or choose 로고 없음 now",
           "Never suggest removing a glob the analysis lists"):
    check(_s in _flat, "init.md: %s" % _s)
check(not [s for s in ("it is fixed", "do not ask for the speaker") if s in _flat], "init.md: no fixed narrator sentence")

# 0.0.26 (pilot-2 P16 · P17): board applies the brand's look (the --look lines) and may change the frontmatter's
# presentation; the writer opens with a title scene, gives unused images a reason and never writes the layout
def _f(*parts):
    return " ".join(open(os.path.join(skill, *parts)).read().split())
_gb, _vd, _bd = _f("templates", "guides", "board.md"), _f("templates", "agents", "std-visual-director.md"), \
    _f("commands", "board.md")
for _n, _t in (("guides/board.md", _gb), ("std-visual-director.md", _vd), ("commands/board.md", _bd)):
    check("--look --output" in _t, "%s names check_assets.py --look (0.0.26 P16)" % _n)
    check(all(k in _t for k in ("`theme`", "`logo`", "`transition`")),
          "%s lets board change the frontmatter's theme, logo and transition (0.0.26 P16)" % _n)
check("## Applied" in _vd, "std-visual-director.md: board.md ends with ## Applied (0.0.26)")
_wr, _gs = _f("templates", "agents", "std-writer.md"), _f("templates", "guides", "script.md")
check("Never write `layout` yourself" in _wr and "keep what board wrote" in _wr,
      "std-writer.md: never write layout, keep what board wrote (0.0.26)")
for _n, _t in (("std-writer.md", _wr), ("guides/script.md", _gs)):
    check("Scene 1 is the title scene" in _t and "unused_images" in _t,
          "%s: the title scene and unused_images (0.0.26 P16 · P17)" % _n)
check("unused: <script_src> — <reason>" in _f("commands", "verify.md"), "verify.md pastes the unused: lines at ①")
_lp = [os.path.relpath(p, skill) for p in _mds if "layout: presenter" in open(p).read()]
check(not _lp, "no shipped document writes layout: presenter (%s)" % ", ".join(_lp))

if fails:
    print("structure: %d failure(s)" % len(fails))
    sys.exit(1)
print("structure: ok")
PYEOF
