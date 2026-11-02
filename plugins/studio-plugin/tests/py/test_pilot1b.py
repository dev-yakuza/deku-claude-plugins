"""Pilot 1 fixes (0.0.24): P6 — Studio's documents are printed by `setup.py doc <name>` (never opened with Read, which
asks the person for every file outside the working directories), and the guard allows exactly that call in any
folder; P7 — `init analyze` drafts the domains, brand colours and logos with evidence, and init.md turns drafts into
options (no "type it yourself" option, narrator after the language, husky only when found)."""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys

import helpers
from helpers import StudioTestCase
from stdo.guard import judge
from stdo.setup import doc
from test_guard_judge import JudgeCase

SETUP = os.path.join(helpers.SCRIPTS, "setup.py")
GUARD = os.path.join(helpers.SCRIPTS, "guard.py")
COMMANDS = os.path.join(helpers.SKILL, "commands")
ATOMS = ("_actors", "_auditor", "_contract", "_invariants", "_stages")
BAD_NAMES = ("nope", "../SKILL", "/etc/passwd", "commands/../../SKILL.md", "atoms/../make.md", ".env", "",
             "make;id", "SKILL", "SKILL.md", "make.md", "commands/atoms/../make.md", "MAKE")


def plugin_version():
    with open(os.path.join(helpers.PLUGIN, ".claude-plugin", "plugin.json")) as f:
        return json.load(f)["version"]


def routed():
    text = open(os.path.join(helpers.SKILL, "SKILL.md")).read()
    m = re.search(r"Valid commands: (.*?)\.\n", text, re.S)
    return set(re.findall(r"`([a-z-]+)`", m.group(1)))


def run_doc(*args):
    out, err = io.StringIO(), io.StringIO()
    code = doc.main(list(args), script=SETUP, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------- P6: setup.py doc

class Docs(StudioTestCase):
    def test_make_is_header_and_bytes(self):
        code, out, err = run_doc("make")
        self.assertEqual(code, 0, err)
        head, body = out.split("\n", 1)
        self.assertEqual(head, "# Studio document make (commands/make.md · plugin %s). Other Studio documents named in "
                               "it (commands/…, atoms/…): python3 \"%s\" doc <name> — never open them with Read."
                         % (plugin_version(), SETUP))
        raw = open(os.path.join(COMMANDS, "make.md"), encoding="utf-8").read()
        self.assertEqual(body, raw.replace("<<SKILL_DIR>>", helpers.SKILL))

    def test_spellings(self):
        make = run_doc("make")[1]
        for s in ("commands/make.md",):
            self.assertEqual(run_doc(s)[1], make)
        contract = run_doc("_contract")[1]
        self.assertIn("(commands/atoms/_contract.md · plugin", contract)
        for s in ("atoms/_contract.md", "commands/atoms/_contract.md"):
            self.assertEqual(run_doc(s)[1], contract)

    def test_every_output(self):
        for n in doc.names():
            code, out, err = run_doc(n)
            self.assertEqual(code, 0, err)
            self.assertNotIn("<<SKILL_DIR>>", out, n)
            self.assertLessEqual(len(out), 20000, n)  # the Bash tool truncates long output (~30,000, unverified)

    def test_unknown(self):
        for bad in BAD_NAMES:
            code, out, err = run_doc(bad)
            self.assertEqual((code, out), (2, ""), bad)
            self.assertIn("std doc: unknown document %s — one of: " % bad, err)
        code, out, err = run_doc("make", "brief")
        self.assertEqual((code, out), (2, ""))

    def test_listing(self):
        code, out, err = run_doc()
        self.assertEqual(code, 0, err)
        listed = re.findall(r"(?m)^- (\S+) — ", out)
        self.assertEqual(listed, doc.names() + ["s2v-syntax"])  # 0.0.25 P10: the fixed name comes last
        self.assertIn("- make — MAKE (make.md)", out)
        self.assertIn("- _contract — ", out)
        self.assertNotIn("<<SKILL_DIR>>", out)

    def test_names_are_routes_and_atoms(self):
        self.assertEqual(set(doc.names()), routed() | set(ATOMS))
        self.assertEqual(doc.NAMES, frozenset(doc.names()) | {"s2v-syntax"})  # 0.0.25 P10

    def snapshot(self, *roots):
        out = {}
        for r in roots:
            for d, dirs, files in os.walk(r):
                for n in dirs + files:
                    p = os.path.join(d, n)
                    st = os.lstat(p)
                    out[p] = (st.st_size, st.st_mtime_ns)
        return out

    def test_process_outside_git_writes_nothing(self):
        cwd = os.path.join(self.tmp, "not-a-repo")
        os.makedirs(cwd)
        env = dict(os.environ)
        env.pop("PYTHONDONTWRITEBYTECODE", None)  # setup.py itself must write no bytecode
        before = self.snapshot(helpers.PLUGIN, cwd)
        r = subprocess.run([sys.executable, SETUP, "doc", "make"], cwd=cwd, capture_output=True, text=True, env=env,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, run_doc("make")[1])
        r = subprocess.run([sys.executable, SETUP, "doc", "../SKILL"], cwd=cwd, capture_output=True, text=True,
                           env=env, timeout=60)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("std doc: unknown document ../SKILL", r.stderr)
        self.assertEqual(self.snapshot(helpers.PLUGIN, cwd), before)

    def test_symlinked_setup_imports_the_plugin(self):
        """A link to setup.py next to a planted stdo/ runs the plugin's code (setup.py: dirname(realpath))."""
        x = os.path.join(self.tmp, "x")
        os.makedirs(os.path.join(x, "stdo", "setup"))
        for rel in ("stdo/__init__.py", "stdo/setup/__init__.py"):
            open(os.path.join(x, rel), "w").close()
        with open(os.path.join(x, "stdo", "setup", "cli.py"), "w") as f:
            f.write("def entry():\n    print('PLANTED')\n    return 0\n")
        os.symlink(SETUP, os.path.join(x, "setup.py"))
        r = subprocess.run([sys.executable, "-B", os.path.join(x, "setup.py"), "doc", "help"], cwd=self.tmp,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("PLANTED", r.stdout)
        self.assertIn("# HELP", r.stdout)


# ---------------------------------------------------------------- P6: the guard allows the document command

class DocsGuard(JudgeCase):
    def setUp(self):
        super().setUp()
        self.plain = os.path.join(self.tmp, "plain")
        os.makedirs(self.plain)
        helpers.git(self.plain, "init", "-q")
        self.before = os.path.join(self.tmp, "before-init")  # a site that has not run /std init yet
        os.makedirs(os.path.join(self.before, "src", "content"))
        helpers.git(self.before, "init", "-q")
        with open(os.path.join(self.before, "src", "content", "a.md"), "w") as f:
            f.write("# a\n")
        helpers.git(self.before, "add", "-A")
        helpers.git(self.before, "commit", "-q", "-m", "site")
        self.nogit = os.path.join(self.tmp, "nogit")
        os.makedirs(self.nogit)
        self.folders = (self.repo, self.plain, self.before, self.nogit)

    def run_hook(self, cmd, cwd=None):
        return judge.decide(self.hook("Bash", {"command": cmd}, cwd), self.env, snapshot_loader=self.loader)

    def assertDocAllow(self, cmd, cwd=None):
        deny, ctx = self.run_hook(cmd, cwd)
        self.assertIsNone(deny, "%s: %s" % (cmd, deny and deny.message()))
        self.assertEqual([k for _, k, _ in ctx.candidates], ["doc"], cmd)
        self.assertTrue(ctx.allow, "%s in %s: no allow" % (cmd, cwd))
        self.assertIn("setup.py doc", ctx.allow)
        return ctx

    def assertFallThrough(self, cmd, cwd=None):
        deny, ctx = self.run_hook(cmd, cwd)
        self.assertIsNone(deny, "%s: %s" % (cmd, deny and deny.message()))
        self.assertIsNone(ctx.allow, "%s in %s: allowed" % (cmd, cwd))
        return ctx

    def pending(self):
        return os.path.exists(os.path.join(self.repo, ".claude", "studio", "local", "pending-approval.json"))

    def test_allowed_everywhere(self):
        for cwd in self.folders:
            for cmd in ("python3 %s doc make" % SETUP, 'python3 "%s" doc make' % SETUP, "python3 %s doc" % SETUP,
                        "python3 %s doc help" % SETUP, "python3 %s doc _contract" % SETUP,
                        "python3 -B %s doc init" % SETUP, "python3 %s doc make 2>&1" % SETUP,
                        "cd %s && python3 %s doc make" % (cwd, SETUP)):
                self.assertDocAllow(cmd, cwd)
        self.assertFalse(self.pending())  # no evidence asked for, none written

    def test_falls_through(self):
        other = os.path.join(self.tmp, "copy")
        os.makedirs(other)
        shutil.copy(SETUP, os.path.join(other, "setup.py"))
        for cwd in self.folders:
            for cmd in ("python3 %s doc make; echo x" % SETUP, "python3 %s doc make | cat" % SETUP,
                        "python3 %s doc make && python3 %s doc brief" % (SETUP, SETUP),
                        "python3 %s doc make > out.txt" % SETUP, "python3 %s doc $(echo make)" % SETUP,
                        "python3 %s doc nope" % SETUP, "python3 %s doc commands/make.md" % SETUP,
                        "python3 %s doc ../SKILL" % SETUP, "python3 %s doc make extra" % SETUP,
                        "python3 %s doc --x" % SETUP, "python3 %s doc" % os.path.join(other, "setup.py"),
                        "PYTHONPATH=/tmp/x python3 %s doc make" % SETUP, "python %s doc make" % SETUP,
                        "python3 %s config get" % SETUP, "(python3 %s doc make)" % SETUP,
                        "python3 %s doc make &" % SETUP):
                deny, ctx = self.run_hook(cmd, cwd)
                self.assertIsNone(ctx.allow, "%s in %s: allowed" % (cmd, cwd))
        # a relative spelling of the plugin's own setup.py is not one of the two accepted spellings
        self.assertFallThrough("cd %s && python3 ./setup.py doc make" % self.nogit, cwd=self.nogit)

    def test_repository_copy_denied_with_a_harness(self):
        local = os.path.join(self.repo, ".claude", "studio", "scripts", "setup.py")
        shutil.copy(SETUP, local)
        deny, ctx = self.run_hook("python3 .claude/studio/scripts/setup.py doc make")
        self.assertEqual(deny.rule, "G-APPROVAL")
        self.assertIsNone(ctx.allow)

    def test_unknown_option_in_a_harness_repo(self):
        """`doc --x`: no evidence asked (labels.needs_evidence), so doc.py answers "unknown document"."""
        from stdo.setup import labels
        self.assertFalse(labels.needs_evidence(["doc", "--x"], ["public_domains"]))
        self.assertFalse(labels.needs_evidence(["doc", "make"], ["public_domains"]))
        self.assertFalse(labels.needs_evidence(["doc"], ["public_domains"]))
        self.assertFallThrough("python3 %s doc --x" % SETUP)
        self.assertFalse(self.pending())
        r = subprocess.run([sys.executable, "-B", SETUP, "doc", "--x"], cwd=self.repo, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("std doc: unknown document --x", r.stderr)

    def test_symlinked_setup_no_allow(self):
        x = os.path.join(self.plain, "x")
        os.makedirs(os.path.join(x, "stdo", "setup"))
        with open(os.path.join(x, "stdo", "setup", "cli.py"), "w") as f:
            f.write("def entry():\n    print('PLANTED')\n")
        os.symlink(SETUP, os.path.join(x, "setup.py"))
        self.assertFallThrough("python3 %s doc make" % os.path.join(x, "setup.py"), cwd=self.plain)
        self.assertFallThrough("python3 x/setup.py doc make", cwd=self.plain)
        link = os.path.join(self.tmp, "linked-scripts")
        os.symlink(helpers.SCRIPTS, link)  # a linked folder: neither accepted spelling
        self.assertFallThrough("python3 %s/setup.py doc make" % link, cwd=self.plain)
        # an accepted spelling that is itself a link to the plugin's setup.py (lstat, not only realpath)
        spelled = os.path.join(self.tmp, "spelled")
        os.makedirs(spelled)
        os.symlink(SETUP, os.path.join(spelled, "setup.py"))
        saved = judge.DOC_SCRIPTS
        judge.DOC_SCRIPTS = (saved[0], os.path.join(spelled, "setup.py"))
        try:
            self.assertFallThrough("python3 %s/setup.py doc make" % spelled, cwd=self.plain)
            self.assertDocAllow("python3 %s doc make" % saved[0], cwd=self.plain)
        finally:
            judge.DOC_SCRIPTS = saved

    def venv(self, root):
        v = os.path.join(root, ".venv")
        os.makedirs(os.path.join(v, "bin"))
        with open(os.path.join(v, "pyvenv.cfg"), "w") as f:
            f.write("home = /usr/bin\n")
        os.symlink(os.path.join(self.bin, "python3"), os.path.join(v, "bin", "python3"))
        return os.path.join(v, "bin")

    def with_path(self, path):
        self.env["PATH"] = path
        self.snap_with = self.make_snapshot()

    def test_repository_venv_no_allow(self):
        for root in (self.plain, self.repo, self.nogit):
            vbin = self.venv(root)
            self.with_path(vbin + ":" + self.bin + ":/usr/bin:/bin")
            self.assertFallThrough("python3 %s doc make" % SETUP, cwd=root)
            self.assertFallThrough("cd %s && python3 %s doc make" % (root, SETUP), cwd=self.tmp)
            self.assertDocAllow("python3 %s doc make" % SETUP, cwd=self.before)  # another folder's venv: not this one
            self.with_path(self.bin + ":/usr/bin:/bin")
            self.assertDocAllow("python3 %s doc make" % SETUP, cwd=root)

    def test_venv_reached_through_a_linked_folder_no_allow(self):
        """PATH names a folder outside the repository that is a link to the repository's venv (pyvenv.cfg rule)."""
        self.venv(self.plain)
        link = os.path.join(self.tmp, "venv-link")
        os.symlink(os.path.join(self.plain, ".venv"), link)
        self.with_path(os.path.join(link, "bin") + ":/usr/bin:/bin")
        self.assertFallThrough("python3 %s doc make" % SETUP, cwd=self.plain)
        self.assertDocAllow("python3 %s doc make" % SETUP, cwd=self.nogit)

    def test_interpreter_resolving_into_the_repository_no_allow(self):
        inner = os.path.join(self.plain, "tools")
        os.makedirs(inner)
        real = os.path.join(inner, "python3")
        shutil.copy(os.path.join(self.bin, "python3"), real)
        outer = os.path.join(self.tmp, "outer-bin")
        os.makedirs(outer)
        os.symlink(real, os.path.join(outer, "python3"))  # outside the repository, but resolves into it
        self.with_path(outer + ":/usr/bin:/bin")
        self.assertFallThrough("python3 %s doc make" % SETUP, cwd=self.plain)
        self.assertDocAllow("python3 %s doc make" % SETUP, cwd=self.nogit)

    def test_plugin_inside_the_run_folder_no_allow(self):
        """Developing Studio with the plugin enabled: the run folder's root holds the plugin."""
        self.assertFallThrough("python3 %s doc make" % SETUP, cwd=helpers.PLUGIN)
        self.assertFallThrough("cd %s && python3 %s doc make" % (helpers.SCRIPTS, SETUP), cwd=self.nogit)
        self.assertFallThrough("python3 %s doc make" % SETUP, cwd=helpers.SCRIPTS)

    def test_exactly_one_candidate(self):
        for cwd in self.folders:
            deny, ctx = self.run_hook("python3 %s doc make" % SETUP, cwd)
            self.assertEqual(len(ctx.candidates), 1, cwd)

    def test_finish_with_a_warning_gives_no_allow(self):
        for warn in (False, True):
            ctx = judge.Context(self.hook("Bash", {"command": "python3 %s doc make" % SETUP}, self.plain), self.env,
                                snapshot_loader=self.loader)
            judge.decide_bash(ctx, "python3 %s doc make" % SETUP)
            if warn:
                ctx.warnings.append("injected")
            judge.finish(ctx)
            self.assertEqual(bool(ctx.allow), not warn)

    def test_guard_process_and_time(self):
        import time
        hook = dict(self.hook("Bash", {"command": 'python3 "%s" doc make' % SETUP}, self.plain),
                    hook_event_name="PreToolUse")
        env = dict(self.env, PYTHONDONTWRITEBYTECODE="1")
        times = []
        for _ in range(3):
            s = time.monotonic()
            out = subprocess.run([sys.executable, "-B", GUARD], input=json.dumps(hook), capture_output=True,
                                 text=True, env=env, timeout=30)
            times.append(time.monotonic() - s)
            self.assertEqual(json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"], "allow", out.stdout)
        times.sort()
        print("\n[perf] guard.py process, setup.py doc: p50 %.0f ms" % (times[1] * 1000))
        self.assertLess(times[1], 5.0)  # the hook's timeout is 20 s
        s = time.monotonic()
        for _ in range(10):
            self.run_hook("python3 %s doc make" % SETUP, self.plain)
        per = (time.monotonic() - s) / 10
        print("[perf] doc judgement in-process: %.1f ms" % (per * 1000))
        self.assertLess(per, 0.25)


# ---------------------------------------------------------------- P6: the skill's text

RULE = 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py" doc *)'


class SkillText(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.text = open(os.path.join(helpers.SKILL, "SKILL.md"), encoding="utf-8").read()
        m = re.match(r"---\n(.*?)\n---\n", self.text, re.S)
        self.front, self.body = m.group(1), self.text[m.end():]

    def test_allowed_tools_is_that_rule(self):
        tail = self.front.split("allowed-tools:\n", 1)[1]
        items = []
        for line in tail.splitlines():
            if not line.startswith("  - "):
                break
            items.append(line[4:])
        self.assertEqual(items, ["'%s'" % RULE])  # YAML single quotes around the rule

    def test_body(self):
        cmd = 'python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py" doc <name>'
        self.assertGreaterEqual(self.body.count(cmd), 2)
        self.assertIn("Never use Read, Grep or Glob on the skill folder", self.body)
        self.assertIn("first compare `$0` with the valid commands below", self.body)
        self.assertIn("never `$0` itself", self.body)
        self.assertIn("Empty `$0` → `doc help`", self.body)
        self.assertNotIn("<<SKILL_DIR>>", self.body)
        for a in ATOMS:
            self.assertIn("`doc %s`" % a, self.body)

    def test_rule_matches_the_command(self):
        """The rule's prefix, with the skill folder substituted, is the prefix of every routed command."""
        import fnmatch
        skill = "/opt/plugins/studio-plugin/skills/std"
        pattern = RULE[len("Bash("):-1].replace("${CLAUDE_SKILL_DIR}", skill)
        for name in sorted(routed()) + list(ATOMS):
            line = 'python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py" doc <name>'.replace("<name>", name)
            self.assertTrue(fnmatch.fnmatchcase(line.replace("${CLAUDE_SKILL_DIR}", skill), pattern), name)

    def test_documents_name_documents_by_doc(self):
        bad = []
        for d, _dirs, files in os.walk(helpers.SKILL):
            for n in files:
                if not n.endswith(".md"):
                    continue
                p = os.path.join(d, n)
                for i, line in enumerate(open(p, encoding="utf-8"), 1):
                    if "<<SKILL_DIR>>/commands/" in line or (re.search(r"commands/[A-Za-z_/]+\.md", line) and
                                                            "setup.py doc" not in line):
                        bad.append("%s:%d" % (os.path.relpath(p, helpers.SKILL), i))
        self.assertEqual(bad, [])
        mk = open(os.path.join(COMMANDS, "make.md"), encoding="utf-8").read()
        pos = [mk.find("`setup.py doc %s`" % d) for d in ("source", "brief", "script", "verify", "board", "render",
                                                          "copy")]
        self.assertTrue(all(p >= 0 for p in pos) and pos == sorted(pos), pos)
        self.assertIn("never open it with Read", mk)
        for stub in ("move", "platform", "review", "evolve", "rollback", "audit", "cast"):
            self.assertIn('`python3 "<<SKILL_DIR>>/scripts/setup.py" doc help`',
                          open(os.path.join(COMMANDS, stub + ".md"), encoding="utf-8").read(), stub)
        for d in ("init", "config", "update"):
            self.assertNotIn("replace `<<SKILL_DIR>>`", open(os.path.join(COMMANDS, d + ".md"), encoding="utf-8").read())


# ---------------------------------------------------------------- P7: init analyze drafts

def png(w, h):
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x06\x00\x00\x00"


BANNER = "/*!\n * Bootstrap v4.3.1 (https://getbootstrap.com/)\n * Licensed under MIT\n */\n"


def css_uses(color, n, prop="color"):
    return "".join(".c%d { %s: %s; }\n" % (i, prop, color) for i in range(n))


class AnalyzeCase(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.top = os.path.join(self.tmp, "site")
        os.makedirs(self.top)
        helpers.git(self.top, "init", "-q")

    def put(self, files, commit=True):
        for rel, body in files.items():
            p = os.path.join(self.top, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb" if isinstance(body, bytes) else "w") as f:
                f.write(body)
        if commit:
            helpers.git(self.top, "add", "-A")
            helpers.git(self.top, "commit", "-q", "--no-verify", "-m", "site")

    def analyze(self):
        from stdo import paths
        from stdo.commit.gitx import Git
        from stdo.setup import analyze
        return analyze.analyze(self.top, Git(self.top, paths.git_env()), "studio")


class AnalyzeDomains(AnalyzeCase):
    def test_cname_and_astro_one_host(self):
        self.put({"public/CNAME": "\nWords.Sample.dev\n", "astro.config.mjs":
                  "export default defineConfig({\n  site: 'https://words.sample.dev/',\n});\n"})
        self.assertEqual(self.analyze()["public_domains"],
                         [{"host": "words.sample.dev", "from": ["public/CNAME", "astro.config.mjs site"]}])

    def test_each_source_alone(self):
        for files, host, src in (({"hugo.toml": "baseURL = 'https://hugo.sample.dev/'\n"}, "hugo.sample.dev",
                                   "hugo.toml baseURL"),
                                  ({"_config.yml": "baseurl: /x\nurl: \"https://jk.sample.dev\"\n"}, "jk.sample.dev",
                                   "_config.yml url"),
                                  ({"docs/CNAME": "docs.sample.dev:443\n"}, "docs.sample.dev", "docs/CNAME"),
                                  ({"mkdocs.yml": "site_url: https://mk.sample.dev/en/\n"}, "mk.sample.dev",
                                   "mkdocs.yml site_url"),
                                  ({"gatsby-config.js": "module.exports = { siteMetadata: { siteUrl: `https://g.sample"
                                    ".dev` } }\n"}, "g.sample.dev", "gatsby-config.js siteUrl")):
            shutil.rmtree(self.top)
            os.makedirs(self.top)
            helpers.git(self.top, "init", "-q")
            self.put(files)
            self.assertEqual(self.analyze()["public_domains"], [{"host": host, "from": [src]}], files)

    def test_homepage_only_when_another_source_agrees(self):
        self.put({"package.json": json.dumps({"homepage": "https://github.com/someone/site"})})
        self.assertEqual(self.analyze()["public_domains"], [])
        self.put({"package.json": json.dumps({"homepage": "https://words.sample.dev/"}), "CNAME": "words.sample.dev\n"})
        self.assertEqual(self.analyze()["public_domains"],
                         [{"host": "words.sample.dev", "from": ["CNAME", "package.json homepage"]}])

    def test_dropped(self):
        self.put({"public/CNAME": "example.com\n", "astro.config.mjs": "export default { site: 'http://localhost:4321' }\n",
                  "static/CNAME": "127.0.0.1\n", "CNAME": "www.example.org.\n", "docs/CNAME": "bad..host\n"})
        self.assertEqual(self.analyze()["public_domains"], [])

    def test_untracked_and_env_never_read(self):
        from stdo.setup import analyze
        self.put({".env": "SITE_URL=https://secret.sample.dev\n", ".env.production": "SITE=https://p.sample.dev\n",
                  "src/a.css": ".a { color: #ec174f; }\n"})
        self.put({"public/CNAME": "untracked.sample.dev\n"}, commit=False)
        read = []
        orig = analyze.Walk.read

        def spy(walk, rel, *a, **kw):
            read.append(rel)
            return orig(walk, rel, *a, **kw)
        analyze.Walk.read = spy
        try:
            a = self.analyze()
        finally:
            analyze.Walk.read = orig
        self.assertEqual(a["public_domains"], [])
        self.assertTrue(read)
        self.assertFalse([r for r in read if os.path.basename(r).startswith(".env")], read)
        for rel in (".env", ".env.local", "config/.env.production", "a/b.min.css", "node_modules/x/logo.svg",
                    "vendor/a.css", "studio/videos/v/x.css", ".claude/studio/a.css", "themes/t/a.css", "_site/a.css"):
            self.assertTrue(analyze._skip(rel), rel)
        for rel in ("src/plugins/x.css", "lib/a.css", "build/a.css", "out/a.css", "public/assets/plugins/a.css"):
            self.assertFalse(analyze._skip(rel), rel)

    def test_shared_host_pattern(self):
        from stdo.setup import analyze, common, initcmd
        self.assertIs(initcmd.HOST, common.HOST)
        self.assertIs(analyze.HOST, common.HOST)
        for h in ("example.com", "a.b.co", "xn--hxa.xn--p1ai", "words.sample.dev"):
            self.assertTrue(common.HOST.match(h), h)
        for h in ("a..com", "-a.com", "1.2.3.4", "localhost", "x.com.", "A.com", ".a.com", "a.c"):
            self.assertFalse(common.HOST.match(h), h)
        self.assertEqual(analyze.host_of("HTTPS://user@Words.Sample.dev.:8080/path?q#f"), "words.sample.dev")


class AnalyzeColors(AnalyzeCase):
    def pilot(self):
        """The pilot site's counts: a Bootstrap build (banner) with --primary #47b0df, a vendored bootstrap.css under
        assets/plugins/ (banner), and the site's own #ec174f in 7 files (52 uses), #c81144 7 times."""
        files = {"public/assets/css/theme.css": BANNER + ":root { --primary: #47b0df; }\n" + css_uses("#47b0df", 37),
                 "public/assets/plugins/bootstrap/css/bootstrap.css": BANNER + css_uses("#dc3545", 84),
                 "public/assets/css/blog-post.css": css_uses("#ec174f", 40) + css_uses("#c81144", 7) +
                 css_uses("#333", 30) + css_uses("#ffffff", 30, "background"),
                 "public/assets/css/vendor.min.css": css_uses("#0000ff", 99)}
        for i in range(6):
            files["src/styles/part%d.css" % i] = css_uses("#EC174F", 2) + "#ec174f { margin: 0; }\n"
        return files

    def test_pilot_counts(self):
        self.put(self.pilot())
        bc = self.analyze()["brand_colors"]
        self.assertEqual(bc[0], {"color": "#EC174F", "from": "public/assets/css/blog-post.css",
                                 "evidence": "used 52 times in 7 files (most in public/assets/css/blog-post.css)"})
        colors = [c["color"] for c in bc]
        for absent in ("#47B0DF", "#DC3545", "#0000FF", "#333333", "#FFFFFF", "#C81144"):  # C81144: a shade of EC174F
            self.assertNotIn(absent, colors)
        self.assertLessEqual(len(bc), 3)

    def test_theme_color_beats_all(self):
        files = self.pilot()
        files["src/layouts/Base.astro"] = '<head><meta name="theme-color" content="#1a7f37"></head>\n'
        files["src/layouts/Other.astro"] = '<meta content="#ffffff" name="theme-color">\n'  # not chromatic: ignored
        files["src/styles/brand.css"] = ":root { --brand: #6f42c1; --bs-primary: #0d6efd; }\n"
        self.put(files)
        bc = self.analyze()["brand_colors"]
        self.assertEqual([c["color"] for c in bc], ["#1A7F37", "#6F42C1", "#EC174F"])
        self.assertEqual(bc[0]["evidence"], "theme-color in src/layouts/Base.astro")
        self.assertEqual(bc[1]["evidence"], "--brand in src/styles/brand.css")

    def test_manifest_and_tailwind(self):
        self.put({"public/site.webmanifest": json.dumps({"theme_color": "#e36"}),
                  "tailwind.config.js": "module.exports = { theme: { extend: { colors: { primary: '#0ea5e9' } } } }\n",
                  "src/a.css": css_uses("#ec174f", 5) + css_uses("#2e86de", 2)})
        # #EC174F is a shade of the manifest's #EE3366 (hue within 10°, lightness within 0.1): collapsed into it
        self.assertEqual([c["color"] for c in self.analyze()["brand_colors"]], ["#EE3366", "#0EA5E9", "#2E86DE"])

    def test_brand_property_beats_frequency(self):
        self.put({"src/styles/a.scss": ":root { --primary-dark: #8e44ad; --primary: #e83e8c; }\n" + css_uses("#ec174f", 50),
                  "src/plugins/x.css": css_uses("#2e86de", 3),
                  "src/App.vue": "<template></template>\n<style>\n.a { color: #10ac84; }\n</style>\n"})
        bc = self.analyze()["brand_colors"]
        self.assertEqual([c["color"] for c in bc], ["#E83E8C", "#8E44AD", "#EC174F"])
        self.put({"src/styles/a.scss": css_uses("#ec174f", 50)})
        bc = self.analyze()["brand_colors"]
        self.assertEqual([c["color"] for c in bc], ["#EC174F", "#2E86DE", "#10AC84"])  # src/plugins/ and <style> count

    def test_vendor_primary_not_offered(self):
        self.put({"public/assets/css/theme.css": BANNER + ":root { --primary: #47b0df; }\n"})
        self.assertEqual(self.analyze()["brand_colors"], [])

    def test_greys_never(self):
        self.put({"a.css": css_uses("#333", 9) + css_uses("#f5f5f5", 9) + css_uses("#000", 9) + css_uses("#fafbfc", 9)})
        self.assertEqual(self.analyze()["brand_colors"], [])


JPEG = b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x03\x00\x04\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xd9"


class AnalyzeLogos(AnalyzeCase):
    def analyze_all_logos(self):
        from stdo.setup import analyze
        saved = analyze.MAX_LOGOS
        analyze.MAX_LOGOS = 99
        try:
            return self.analyze()["logos"]
        finally:
            analyze.MAX_LOGOS = saved

    def test_pilot_logo_first(self):
        self.put({"astro.config.mjs": "export default {}\n", "public/assets/images/logo.png": png(205, 205),
                  "public/assets/images/favicon-48.png": png(48, 48),
                  "public/assets/images/apple-touch-icon.png": png(180, 180), "public/favicon.ico": b"\0\0\1\0"})
        lg = self.analyze()["logos"]
        self.assertEqual([l["path"] for l in lg], ["public/assets/images/logo.png",
                                                   "public/assets/images/apple-touch-icon.png",
                                                   "public/assets/images/favicon-48.png"])
        self.assertEqual(lg[0], {"path": "public/assets/images/logo.png", "from": "logo file name", "size": [205, 205],
                                 "video": True})  # 0.0.26: whether the video can show it

    def test_order(self):
        """0.0.26 (fix-0026 §1.4): PNG, then JPEG, then SVG/WebP — the video shows only PNG and JPEG (`video`)."""
        self.put({"public/logo-white.png": png(800, 200), "public/logo.png": png(400, 100), "public/logo.svg": "<svg/>",
                  "docs/logo.svg": "<svg/>", "astro.config.mjs": "export default {}\n"})
        lg = self.analyze()["logos"]
        self.assertEqual([(l["path"], l["video"]) for l in lg], [("public/logo.png", True), ("public/logo.svg", False),
                                                                 ("docs/logo.svg", False)])
        self.assertIsNone(lg[1]["size"])
        os.remove(os.path.join(self.top, "public", "logo.svg"))
        self.put({"public/logo.webp": b"RIFF\0\0\0\0WEBP", "public/logo.jpg": JPEG,
                  "public/brand.jpeg": b"<svg/>"})
        lg = self.analyze()["logos"]
        self.assertEqual([(l["path"], l["video"]) for l in lg], [("public/logo.png", True), ("public/logo.jpg", True),
                                                                 ("public/logo.webp", False)])
        self.assertIn({"path": "public/brand.jpeg", "from": "logo file name", "size": None, "video": False},
                      self.analyze_all_logos())  # SVG bytes under a .jpeg name: not for the video

    def test_fallback_by_size(self):
        self.put({"public/favicon-32.png": png(32, 32), "public/android-chrome-512x512.png": png(512, 512),
                  "public/favicon.ico": b"\0", "public/apple-touch-icon-180.png": png(180, 180)})
        self.assertEqual([l["path"] for l in self.analyze()["logos"]], ["public/android-chrome-512x512.png",
                                                                       "public/apple-touch-icon-180.png",
                                                                       "public/favicon-32.png"])

    def test_untracked_and_skipped_never(self):
        self.put({"node_modules/pkg/logo.svg": "<svg/>", "dist/logo.svg": "<svg/>", "a.txt": "x"})
        self.assertIn("dist/logo.svg", helpers.git(self.top, "ls-files").stdout)  # tracked, but a skipped folder
        self.put({"public/logo.svg": "<svg/>"}, commit=False)
        self.assertEqual(self.analyze()["logos"], [])


class AnalyzeMisc(AnalyzeCase):
    def test_ask_husky(self):
        self.put({"a.txt": "x"})
        a = self.analyze()
        self.assertEqual((a["hook_manager"], a["ask_husky"]), ("plain", False))
        self.put({"lefthook.yml": "pre-commit:\n"})
        a = self.analyze()
        self.assertEqual((a["hook_manager"], a["ask_husky"]), ("lefthook", False))
        os.remove(os.path.join(self.top, "lefthook.yml"))
        self.put({".husky/pre-commit": "npm test\n", "package.json": json.dumps({"devDependencies": {"husky": "9"}})})
        a = self.analyze()
        self.assertEqual((a["hook_manager"], a["ask_husky"]), ("husky", True))
        from stdo.setup import analyze
        a = analyze.analyze(self.top, None)
        self.assertNotIn("hook_manager", a)
        self.assertEqual((a["ask_husky"], a["public_domains"], a["brand_colors"], a["logos"], a["partial"]),
                         (False, [], [], [], False))

    def test_speed_and_budget(self):
        import time
        from stdo.setup import analyze
        files = {"src/s%04d.css" % i: ".a { color: #ec174f; }\n" for i in range(3000)}
        self.put(files)
        s = time.monotonic()
        a = self.analyze()
        took = time.monotonic() - s
        print("\n[perf] init analyze, 3,000 tracked styles: %.0f ms" % (took * 1000))
        self.assertLess(took, 2.0)
        self.assertEqual(a["brand_colors"][0]["evidence"],
                         "used 3000 times in 3000 files (most in src/s0000.css)")
        self.assertFalse(a["partial"])
        saved = analyze.BUDGET_FILES
        analyze.BUDGET_FILES = 100
        try:
            a = self.analyze()
        finally:
            analyze.BUDGET_FILES = saved
        self.assertTrue(a["partial"])
        self.assertEqual(a["brand_colors"][0]["evidence"], "used 100 times in 100 files (most in src/s0000.css)")

    def test_links_and_fifo_never_opened(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "CNAME"), "w") as f:
            f.write("evil.sample.dev\n")
        fifo = os.path.join(outside, "pipe")
        os.mkfifo(fifo)
        self.put({"a.txt": "x"})
        os.makedirs(os.path.join(self.top, "public"))
        os.symlink(os.path.join(outside, "CNAME"), os.path.join(self.top, "public", "CNAME"))
        os.makedirs(os.path.join(self.top, "src"))
        os.symlink(fifo, os.path.join(self.top, "src", "a.css"))
        os.symlink(fifo, os.path.join(self.top, "logo.png"))
        helpers.git(self.top, "add", "-A")
        helpers.git(self.top, "commit", "-q", "--no-verify", "-m", "links")
        r = subprocess.run([sys.executable, "-B", SETUP, "init", "analyze"], cwd=self.top, capture_output=True,
                           text=True, timeout=30)  # a FIFO opened for reading would block: the timeout fails it
        self.assertEqual(r.returncode, 0, r.stderr)
        a = json.loads(r.stdout)
        self.assertEqual((a["public_domains"], a["brand_colors"], a["logos"]), ([], [], []))

    def test_folder_linked_out_of_the_repository(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "CNAME"), "w") as f:
            f.write("evil.sample.dev\n")
        self.put({"public/CNAME": "words.sample.dev\n"})
        shutil.rmtree(os.path.join(self.top, "public"))
        os.symlink(outside, os.path.join(self.top, "public"))  # the tracked path now reaches outside
        self.assertEqual(self.analyze()["public_domains"], [])


# ---------------------------------------------------------------- P7: init.md (mirrored in structure_test.sh)

TYPE_IT = ("직접 입력", "Other로", "기타")


class InitText(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.raw = open(os.path.join(COMMANDS, "init.md"), encoding="utf-8").read()
        self.text = " ".join(self.raw.split())

    def test_no_type_it_option(self):
        """Option labels only (every backquoted value): the rule naming them and the free-text line may say 직접 입력."""
        bad = []
        for line in self.raw.splitlines():
            if "Never add an option that means" in line:
                continue
            bad += [w for w in re.findall(r"`([^`]+)`", line) if any(t in w for t in TYPE_IT)]
        self.assertEqual(bad, [])

    def test_rules(self):
        for s in ('Never add an option that means "I\'ll type it"', "Only the first question says so: its text ends "
                  "with one line in the repository's language", "the other questions do not repeat it",
                  "목록에 없으면 직접 입력해 주세요", "never naming a UI label",
                  "at most 4 questions per call and 2–4 options per question",
                  "Only after the language is answered: the default narrator",
                  "never put a question in the same call as a question it depends on",
                  "**in a plain message**", "One value only → do not ask", "`#2563EB` (Studio's default)",
                  "`로고 없음`", "`도메인 없음`", "`multiSelect`", "open up to two logo candidates",
                  "never mention hooks in a question", "edit `.claude/studio/brand.json`",
                  "which writing is public is always asked", "`공개 글 없음`"):
            self.assertIn(s, self.text)
        for key in ("ask_husky", "public_domains", "brand_colors", "logos", "project_names", "image_folders",
                    "narrator_candidates", "via_web_root", "video: true"):
            self.assertIn("`%s`" % key, self.text)
        self.assertLess(self.text.find("script2video checkout"), self.text.find("## 3."))  # §1, before the interview
