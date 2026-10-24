"""M1c (m1-plan §5): setup.py init · config · narrator · update, the harness commit's value block (settings and
machine parts, overflow file, first-install-overflow), the builtin narrator in harness commits, the pronounce leftover
left out of a harness commit (v5.1 T2), the guard's setup.py approvals, the overlay question's key counts (J29), and
init apply → the first harness commit end to end (real guard, hook and git)."""

import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import unittest

import helpers
import transcripts as TR
from approve_base import stamp
from e2e_runner import Session
from helpers import StudioTestCase
from stdo import SCRIPTS_VERSION, criteria, machine, narrator, paths
from stdo.commit import okfile, values
from stdo.setup import cli as setup_cli, initcmd, render, update
from stdo.state import evidence, harnessgate
from stdo.state.argv import argv_sha
from test_guard_judge import JudgeCase

FAKE_ROOT = os.path.join(helpers.HERE, "drivers", "fake_s2v_cli")
SETUP = os.path.join(helpers.SCRIPTS, "setup.py")
SID = "sess-m1c"
VERSION = {"id": "0.12.2+fakec0de0001", "version": "0.12.2", "stale_build": False, "commit": "f" * 40, "dirty": False}


def need_node():
    if shutil.which("node"):
        return
    if helpers.full_mode():
        raise AssertionError("--full needs node for the fake s2v CLI")
    raise unittest.SkipTest("needs node (the fake s2v CLI)")


class InitCase(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, "src", "content", "blog"))
        os.makedirs(os.path.join(self.repo, "public", "blog-images"))
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        with open(os.path.join(self.repo, "src", "content", "blog", "a.md"), "w") as f:
            f.write("# 공항 단어\n\n공항은 くうこう.\n")
        with open(os.path.join(self.repo, "public", "blog-images", "a.png"), "wb") as f:
            f.write(b"\x89PNG")
        with open(os.path.join(self.repo, "astro.config.mjs"), "w") as f:
            f.write("export default {}\n")
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "-m", "site")
        self.pybin = os.path.join(self.tmp, "pybin")
        os.makedirs(self.pybin)
        os.symlink(sys.executable, os.path.join(self.pybin, "python3"))
        os.environ["PATH"] = self.pybin + os.pathsep + os.environ.get("PATH", "")
        self.version = dict(VERSION)
        self.tool = 0

    def answers(self, **over):
        a = {"language": "ko", "project_name": "공항 어휘", "public_domains": ["example.com"],
             "web_roots": {"/": "public/"}, "visibility_public": ["src/content/blog/**", "public/blog-images/**"],
             "narrator": {"style": "차분하게"}, "s2v_path": FAKE_ROOT}
        a.update(over)
        return a

    def setup(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = setup_cli.main(list(argv), cwd=self.repo, env=dict(os.environ),
                                  version=lambda p: dict(self.version))
        self.last_out, self.last_err = out.getvalue(), err.getvalue()
        return code

    def out_json(self):
        return json.loads(self.last_out)

    def init(self, **over):
        p = os.path.join(self.tmp, "answers.json")
        with open(p, "w") as f:
            json.dump(self.answers(**over), f, ensure_ascii=False)
        self.assertEqual(self.setup("init", "plan", "--answers", p), 0, self.last_err)
        self.assertEqual(self.setup("init", "apply"), 0, self.last_err)

    def commit_all(self, msg="harness"):
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", msg)

    def script(self, name, *args, env=None):
        e = dict(env or os.environ)
        e.pop("CLAUDECODE", None)
        e.pop("CLAUDE_CODE_SESSION_ID", None)
        return subprocess.run([sys.executable, "-B", os.path.join(self.repo, ".claude", "studio", "scripts", name)]
                              + list(args), cwd=self.repo, capture_output=True, text=True, env=e)

    def pend(self, argv, answer, question="?"):
        self.tool += 1
        ev = {"schema": 1, "argv_sha": argv_sha(list(argv)), "session_id": SID, "tool_use_id": "toolu_%d" % self.tool,
              "question_index": 0, "question": question, "answer": answer, "mode": "human", "written_at": stamp()}
        os.makedirs(evidence.local_dir(self.repo), exist_ok=True)
        with open(evidence.pending_path(self.repo), "w") as f:
            json.dump(ev, f, ensure_ascii=False)

    def cfg(self):
        with open(os.path.join(self.repo, ".claude", "studio", "config.json")) as f:
            return json.load(f)


# ---------------------------------------------------------------- init

class Init(InitCase):
    def test_analyze(self):
        self.assertEqual(self.setup("init", "analyze"), 0, self.last_err)
        a = self.out_json()
        self.assertEqual((a["web_roots"], a["web_roots_from"]), ({"/": "public/"}, "astro.config.mjs"))
        self.assertEqual(a["content_folders"], [{"folder": "src/content/blog/", "markdown_files": 1}])
        self.assertIsNone(a["studio_root_problem"])
        with open(os.path.join(self.repo, "astro.config.mjs"), "w") as f:
            f.write("export default { publicDir: './static' }\n")
        self.setup("init", "analyze")
        self.assertEqual(self.out_json()["web_roots"], {})  # static/ does not exist
        os.makedirs(os.path.join(self.repo, "static"))
        self.setup("init", "analyze")
        self.assertEqual(self.out_json()["web_roots"], {"/": "static/"})
        os.remove(os.path.join(self.repo, "astro.config.mjs"))
        with open(os.path.join(self.repo, "hugo.toml"), "w") as f:
            f.write("title = 'x'\n")
        self.setup("init", "analyze")
        self.assertEqual(self.out_json()["web_roots"], {"/": "static/"})
        os.remove(os.path.join(self.repo, "hugo.toml"))
        self.setup("init", "analyze")
        self.assertEqual(self.out_json()["web_roots"], {})

    def test_plan_is_deterministic_and_complete(self):
        a = self.answers()
        p1 = initcmd.plan(self.repo, a, version=lambda p: dict(self.version))
        p2 = initcmd.plan(self.repo, copy.deepcopy(a), version=lambda p: dict(self.version))
        self.assertEqual(p1, p2)
        for rel in (".claude/studio/config.json", ".claude/studio/charter.md", ".claude/studio/brand.json",
                    ".claude/studio/formats/youtube.md", ".claude/studio/platforms/youtube.md",
                    ".claude/studio/guides/script.md", ".claude/studio/guides/board.md",
                    ".claude/studio/guides/copy.md", ".claude/studio/pronounce.json",
                    ".claude/agents/std-auditor.md", ".claude/agents/std-writer.md",
                    "studio/cast/narrator/profile.md", "studio/cast/narrator/status.json"):
            self.assertIn(rel, p1["files"])
        self.assertNotIn(".claude/agents/std-translator.md", p1["files"])  # conditional roles come with M3
        self.assertNotIn("setup.py", p1["scripts"])
        self.assertFalse([s for s in p1["scripts"] if s.startswith(("stdo/setup/", "stdo/guard/"))])
        self.assertEqual(p1["s2v"]["id"], VERSION["id"])
        a2 = self.answers(project_name="다른 이름")
        self.assertNotEqual(initcmd.plan(self.repo, a2, version=lambda p: dict(self.version))["sha"], p1["sha"])

    def test_answers_are_checked(self):
        bad = [dict(language="zh"), dict(studio_root="../x"), dict(studio_root=".claude"),
               dict(brand={"accent_color": "red"}), dict(brand={"logo": "missing.png"}),
               dict(public_domains=["not a host"]), dict(web_roots={"/": "nope/"}), dict(web_roots={"x": "public/"}),
               dict(visibility_public=["**"]), dict(visibility_public=["../outside/**"]),
               dict(narrator={"engine": "qwen:Nobody"}), dict(narrator={"id": "Narrator"}), dict(s2v_path="rel"),
               dict(unknown=1)]
        for over in bad:
            with self.assertRaises(initcmd.SetupError, msg=over) as e:
                initcmd.plan(self.repo, self.answers(**over), version=lambda p: dict(self.version))
            self.assertEqual(e.exception.code, 2, over)
        for v, why in (({"stale_build": True}, "stale"), ({"version": "0.12.0"}, "older"), ({"id": None}, "no id")):
            self.version = dict(VERSION, **v)
            with self.assertRaises(initcmd.SetupError) as e:
                initcmd.plan(self.repo, self.answers(), version=lambda p: dict(self.version))
            self.assertIn(why, str(e.exception))

    def test_p5_existing_files_are_marked(self):
        os.makedirs(os.path.join(self.repo, ".claude", "agents"))
        with open(os.path.join(self.repo, ".claude", "agents", "std-writer.md"), "w") as f:
            f.write("an earlier copy\n")
        p = os.path.join(self.tmp, "answers.json")
        with open(p, "w") as f:
            json.dump(self.answers(), f)
        self.assertEqual(self.setup("init", "plan", "--answers", p), 0, self.last_err)
        self.assertEqual(self.out_json()["replaces"], [".claude/agents/std-writer.md — exists, will be replaced"])

    def test_studio_folder_conflict(self):
        os.makedirs(os.path.join(self.repo, "studio"))
        initcmd.plan(self.repo, self.answers(), version=lambda p: dict(self.version))  # empty: fine
        with open(os.path.join(self.repo, "studio", "notes.txt"), "w") as f:
            f.write("not Studio's")
        with self.assertRaises(initcmd.SetupError) as e:
            initcmd.plan(self.repo, self.answers(), version=lambda p: dict(self.version))
        self.assertEqual(e.exception.code, 3)
        self.assertIn("choose another studio_root", str(e.exception))
        p = initcmd.plan(self.repo, self.answers(studio_root="media"), version=lambda p: dict(self.version))
        self.assertIn("media/cast/narrator/status.json", p["files"])

    def test_apply_writes_the_harness(self):
        self.init()
        cfg = self.cfg()
        self.assertEqual(cfg["s2v"], {"min_version": "0.12.1"})
        self.assertEqual(cfg["visibility"]["public"], ["src/content/blog/**", "public/blog-images/**"])
        self.assertEqual(cfg["web_roots"], {"/": "public/"})
        self.assertEqual(machine.s2v_path(self.repo), FAKE_ROOT)
        with open(os.path.join(self.repo, "studio", "cast", "narrator", "status.json")) as f:
            st = json.load(f)
        self.assertEqual(narrator.problems(st, "narrator"), [])
        self.assertEqual(st["voice"]["ko"]["engine"], "qwen:Sohee")
        with open(os.path.join(self.repo, ".claude", "studio", "pronounce.json")) as f:
            self.assertEqual(json.load(f), {})
        crit = criteria.read(self.repo, "youtube")
        self.assertEqual((crit["chars_per_sec"]["ko"], crit["cer_max"]["ko"]), (5.5, 0.15))
        with open(os.path.join(self.repo, ".claude", "studio", "installed.json")) as f:
            inst = json.load(f)
        self.assertEqual(inst["scripts_version"], SCRIPTS_VERSION)
        self.assertIn(".claude/agents/std-fact-checker.md", inst["templates"])
        self.assertTrue(inst["templates"][".claude/agents/std-writer.md"]["persona"])
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "studio", "scripts", "setup.py")))
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".claude", "studio", "scripts", "state.py")))
        with open(os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json"), "rb") as f:
            raw = f.read()
        import hashlib
        with open(os.path.join(paths.backup_root(), paths.repo_key(self.repo), "overlay.sha")) as f:
            self.assertEqual(f.read().strip(), hashlib.sha256(raw).hexdigest())
        self.assertTrue(os.path.exists(paths.marker_path(self.repo)))
        with open(os.path.join(self.repo, ".gitignore")) as f:
            self.assertIn("/.claude/studio/local/", f.read())
        # not committed yet: a video cannot start (begin refuses an uncommitted harness) — E1b
        res = harnessgate.check(self.repo)
        self.assertTrue(res.blocking)
        self.assertIn(".claude/studio/config.json", res.paths)
        self.assertIn("studio/cast/narrator/status.json", res.paths)

    def test_apply_again_is_refused(self):
        """§5.1: a harness in the work tree, the index or HEAD, or only a marker → 3."""
        self.init()
        self.assertEqual(self.setup("init", "apply"), 3)
        self.assertIn("already here", self.last_err)
        self.commit_all()
        cfg = os.path.join(self.repo, ".claude", "studio", "config.json")
        # in the index (and HEAD), the work tree file gone
        os.remove(cfg)
        self.assertIn("index", initcmd.existing(self.repo))
        # in HEAD only
        helpers.git(self.repo, "rm", "-q", "--cached", ".claude/studio/config.json")
        self.assertIn("HEAD", initcmd.existing(self.repo))
        self.assertEqual(self.setup("init", "apply"), 3)
        # the history without the harness, the marker of an earlier install left
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "drop config")
        self.assertIn("traces of an earlier Studio install", initcmd.existing(self.repo))
        os.remove(paths.marker_path(self.repo))
        self.assertIsNone(initcmd.existing(self.repo))

    def test_plan_must_still_match(self):
        p = os.path.join(self.tmp, "answers.json")
        with open(p, "w") as f:
            json.dump(self.answers(), f)
        self.assertEqual(self.setup("init", "plan", "--answers", p), 0, self.last_err)
        self.version["id"] = "0.12.2+changed"
        self.assertEqual(self.setup("init", "apply"), 1)
        self.assertIn("no longer matches", self.last_err)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "studio", "config.json")))


# ---------------------------------------------------------------- config and narrator

class Config(InitCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.commit_all()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SID

    def test_unprotected_keys_need_no_answer(self):
        self.assertEqual(self.setup("config", "preview", "commit_audio", "true"), 0, self.last_err)
        self.assertFalse(self.out_json()["protected"])
        self.assertEqual(self.setup("config", "set", "commit_audio", "true"), 0, self.last_err)
        self.assertIs(self.cfg()["commit_audio"], True)
        self.assertEqual(self.setup("config", "set", "commit_audio", "true"), 3)  # already
        self.assertEqual(self.setup("config", "set", "nonsense", "1"), 2)
        self.assertEqual(self.setup("config", "set", "studio_root", '"media"'), 2)
        self.assertIn("not changed by config", self.last_err)
        self.assertEqual(self.setup("config", "get", "commit_audio"), 0)
        self.assertIs(self.out_json()["value"], True)

    def test_protected_key_needs_the_persons_answer(self):
        self.assertEqual(self.setup("config", "preview", "visibility.public", '["src/**"]'), 0)
        p = self.out_json()
        self.assertTrue(p["protected"])
        self.assertEqual(p["line"], '설정 visibility.public: ["src/content/blog/**","public/blog-images/**"] → '
                                    '["src/**"]')
        argv = ["config", "set", "visibility.public", '["src/**"]']
        self.assertEqual(self.setup(*argv), 2)  # no --expect: what to ask
        self.assertIn(p["label"], self.last_err)
        argv += ["--expect", p["h12"]]
        self.assertEqual(self.setup(*argv), 6)  # no evidence
        self.pend(argv, "설정 000000000000")
        self.assertEqual(self.setup(*argv), 6)
        self.pend(argv, p["label"])
        self.assertEqual(self.setup(*argv[:-1], "0" * 12), 1)  # another --expect
        self.assertEqual(self.setup(*argv), 0, self.last_err)
        self.assertEqual(self.cfg()["visibility"]["public"], ["src/**"])
        self.pend(argv, p["label"], question="again")
        self.assertEqual(self.setup(*argv + ["--proxy"]), 2)

    def test_p4_no_path_in_config(self):
        self.assertEqual(self.setup("config", "set", "s2v", '{"min_version": "0.12.1", "path": "/x"}'), 2)
        self.assertIn("config set s2v.path", self.last_err)
        self.assertNotIn("path", self.cfg()["s2v"])

    def test_s2v_path(self):
        other = os.path.join(self.tmp, "s2v2")
        os.makedirs(os.path.join(other, "packages", "cli", "dist"))
        with open(os.path.join(other, "packages", "cli", "dist", "main.js"), "w") as f:
            f.write("")
        self.assertEqual(self.setup("config", "preview", "s2v.path", other), 0, self.last_err)
        p = self.out_json()
        self.assertTrue(p["protected"])
        argv = ["config", "set", "s2v.path", other, "--expect", p["h12"]]
        self.pend(argv, p["label"])
        self.assertEqual(self.setup(*argv), 0, self.last_err)
        self.assertEqual(machine.s2v_path(self.repo), other)
        self.assertNotIn("path", self.cfg()["s2v"])
        self.assertEqual(self.setup("config", "preview", "s2v.path", "/no/such/s2v"), 2)

    def test_no_harness(self):
        bare = os.path.join(self.tmp, "bare")
        subprocess.run(["git", "init", "-q", bare], check=True)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = setup_cli.main(["config", "set", "commit_audio", "true"], cwd=bare)
        self.assertEqual(code, 2)
        self.assertIn("no Studio harness", err.getvalue())

    def test_narrator(self):
        self.assertEqual(self.setup("narrator", "preview", "ko", "--engine", "qwen:Nobody", "--style", "x"), 2)
        self.assertEqual(self.setup("narrator", "preview", "ko", "--engine", "qwen:Sohee", "--style", "밝게"), 0)
        p = self.out_json()
        self.assertEqual(p["line"], '설정 내레이터 narrator ko: qwen:Sohee "차분하게" → qwen:Sohee "밝게"')
        argv = ["narrator", "set", "ko", "--engine", "qwen:Sohee", "--style", "밝게", "--expect", p["h12"]]
        self.assertEqual(self.setup(*argv), 6)
        self.pend(argv, p["label"])
        self.assertEqual(self.setup(*argv), 0, self.last_err)
        with open(os.path.join(self.repo, "studio", "cast", "narrator", "status.json")) as f:
            self.assertEqual(json.load(f)["voice"]["ko"]["style"], "밝게")
        # the harness commit carries it, with the narrator line in the summary's value block
        r = self.script("check_commit.py", "--stage", "harness")
        self.assertEqual(r.returncode, 0, r.stderr)
        ok, _ = okfile.read(self.repo)
        self.assertEqual(ok["paths"], ["studio/cast/narrator/status.json"])
        self.assertEqual(ok["values_shown"], ['내레이터: narrator ko qwen:Sohee "차분하게" → qwen:Sohee "밝게"'])


# ---------------------------------------------------------------- the harness commit: narrator files, value block

class HarnessCommit(InitCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.commit_all()

    def stage(self):
        return self.script("check_commit.py", "--stage", "harness")

    def unstage(self):
        helpers.git(self.repo, "reset", "-q")

    def test_builtin_narrator_files_only(self):
        with open(os.path.join(self.repo, "studio", "cast", "narrator", "profile.md"), "a") as f:
            f.write("more\n")
        self.assertEqual(self.stage().returncode, 0)
        self.unstage()
        with open(os.path.join(self.repo, "studio", "cast", "narrator", "voice.wav"), "wb") as f:
            f.write(b"RIFF")
        res = harnessgate.check(self.repo)
        self.assertNotIn("studio/cast/narrator/voice.wav", res.paths)  # not a harness file
        os.remove(os.path.join(self.repo, "studio", "cast", "narrator", "voice.wav"))
        # another cast member (not builtin) is not a harness file; a broken builtin record is refused
        sp = os.path.join(self.repo, "studio", "cast", "narrator", "status.json")
        with open(sp) as f:
            st = json.load(f)
        os.makedirs(os.path.join(self.repo, "studio", "cast", "actor1"))
        with open(os.path.join(self.repo, "studio", "cast", "actor1", "status.json"), "w") as f:
            json.dump(dict(st, id="actor1", kind="actor"), f)
        self.assertNotIn("studio/cast/actor1/status.json", harnessgate.check(self.repo).paths)
        st["voice"]["ko"]["engine"] = "qwen:Nobody"
        with open(sp, "w") as f:
            json.dump(st, f)
        r = self.stage()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a builtin narrator record", r.stderr)

    def test_each_uncommitted_piece_blocks_begin(self):
        """§5.5: config.json · pronounce.json · installed.json · the narrator's files · the .gitignore block."""
        edits = {
            ".claude/studio/config.json": lambda t: t.replace('"commit_audio": false', '"commit_audio": true'),
            ".claude/studio/pronounce.json": lambda t: '{"空港": "쿠우코오"}\n',
            ".claude/studio/installed.json": lambda t: t.replace('"schema": 1', '"schema": 1, "x": 1'),
            "studio/cast/narrator/profile.md": lambda t: t + "more\n",
            "studio/cast/narrator/status.json": lambda t: t.replace("차분하게", "밝게"),
            ".gitignore": lambda t: t.replace("/studio/out/\n", ""),
        }
        for rel, f in edits.items():
            p = os.path.join(self.repo, rel)
            with open(p) as fh:
                before = fh.read()
            with open(p, "w") as fh:
                fh.write(f(before))
            res = harnessgate.check(self.repo)
            self.assertIn(rel, res.paths, rel)
            with open(p, "w") as fh:
                fh.write(before)
        self.assertFalse(harnessgate.check(self.repo).blocking)

    def test_value_block_and_hook(self):
        cfg = self.cfg()
        cfg["public_domains"] = ["example.com", "docs.example.com"]
        with open(os.path.join(self.repo, ".claude", "studio", "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        r = self.stage()
        self.assertEqual(r.returncode, 0, r.stderr)
        ok, _ = okfile.read(self.repo)
        line = 'public_domains: ["example.com"] → ["example.com","docs.example.com"]'
        self.assertEqual((ok["values_settings"], ok["values_machine"], ok["values_shown"], ok["overflow"]),
                         ([line], [], [line], None))
        self.assertIn(line, r.stdout)
        # the hook recomputes the settings part: a commit-ok with another block is refused
        bad = dict(ok, values_settings=["public_domains: [] → []"], values_shown=["public_domains: [] → []"])
        okfile.write(self.repo, bad)
        c = subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "x"], capture_output=True, text=True,
                           env=dict(os.environ))
        self.assertNotEqual(c.returncode, 0)
        self.assertIn("value block differs", c.stderr)
        okfile.write(self.repo, ok)
        c = subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "x"], capture_output=True, text=True,
                           env=dict(os.environ))
        self.assertEqual(c.returncode, 0, c.stderr)

    def test_p1_criteria_in_the_value_block(self):
        f = os.path.join(self.repo, ".claude", "studio", "formats", "youtube.md")
        with open(f) as fh:
            body = fh.read()
        with open(f, "w") as fh:
            fh.write(body.replace('"ko": 0.15', '"ko": 0.1'))
        with open(os.path.join(self.repo, ".claude", "studio", "charter.md"), "a") as fh:
            fh.write("\n추가.\n")
        r = self.stage()
        self.assertEqual(r.returncode, 0, r.stderr)
        ok, _ = okfile.read(self.repo)
        import hashlib
        with open(f, "rb") as fh:
            sha12 = hashlib.sha256(fh.read()).hexdigest()[:12]
        self.assertIn("criteria.youtube.cer_max.ko: 0.15 → 0.1", ok["values_shown"])
        self.assertIn(".claude/studio/formats/youtube.md: %s (바뀜)" % sha12, ok["values_shown"])
        self.assertTrue([l for l in ok["values_shown"] if l.startswith(".claude/studio/charter.md: ")])
        c = subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "x"], capture_output=True, text=True)
        self.assertEqual(c.returncode, 0, c.stderr)  # the hook recomputes the same lines
        # criteria a check cannot read are refused (P3)
        with open(f, "w") as fh:
            fh.write(body.replace('"ko": 0.15', '"ko": NaN'))
        r = self.stage()
        self.assertEqual(r.returncode, 1)
        self.assertIn("criteria are not usable", r.stderr)
        helpers.git(self.repo, "reset", "-q")
        with open(f, "w") as fh:  # the repository's language (ko) left out of cer_max
            fh.write(body.replace('"cer_max": {"ko": 0.15, ', '"cer_max": {'))
        r = self.stage()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no value for ko", r.stderr)

    def test_the_hook_compares_the_answer_with_the_block(self):
        """The guard records the value lines the person saw (approval.values); the hook refuses another record."""
        cfg = self.cfg()
        cfg["public_domains"] = ["b.example.com"]
        with open(os.path.join(self.repo, ".claude", "studio", "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        env = dict(os.environ, CLAUDECODE="1", CLAUDE_CODE_SESSION_ID=SID)
        p = os.path.join(self.repo, ".claude", "studio", "local", "guard-ran.json")
        with open(p, "w") as f:
            json.dump({"schema": 1, "sessions": {SID: "2026-10-24T00:00:00Z"}}, f)
        r = subprocess.run([sys.executable, "-B", os.path.join(self.repo, ".claude/studio/scripts/check_commit.py"),
                            "--stage", "harness"], cwd=self.repo, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        ok, _ = okfile.read(self.repo)

        def approve(vals):
            okfile.set_approval(self.repo, {"mode": "human", "tree": ok["tree"], "head": ok["head"],
                                            "session_id": SID, "answer": ok["label"], "summary": ok["summary"],
                                            "values": vals, "tool_use_id": "t%d" % len(str(vals)),
                                            "question_index": 0, "at": "2026-10-24T00:00:00Z"})
        approve(["public_domains: [] → []"])
        c = subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "x"], capture_output=True, text=True,
                           env=env)
        self.assertNotEqual(c.returncode, 0)
        self.assertIn("did not see the value block", c.stderr)
        approve(ok["values_shown"])
        c = subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "x"], capture_output=True, text=True,
                           env=env)
        self.assertEqual(c.returncode, 0, c.stderr)

    def test_overflow(self):
        cfg = self.cfg()
        cfg["visibility"]["public"] = ["src/content/blog/post-%03d/**" % i for i in range(30)]  # one long value
        with open(os.path.join(self.repo, ".claude", "studio", "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        r = self.stage()
        self.assertEqual(r.returncode, 0, r.stderr)
        ok, _ = okfile.read(self.repo)
        ov = ok["overflow"]
        self.assertEqual(ov["reason"], "overflow")
        self.assertEqual(ok["values_shown"][0], values.file_line(ov["file"], ov["sha12"]))
        self.assertIn("visibility.public: 30개 (+30 −2)", ok["values_shown"])
        self.assertIn("open %s" % ov["file"], r.stdout)
        with open(os.path.join(self.repo, ov["file"])) as f:
            self.assertIn("src/content/blog/post-029/**", f.read())
        # a changed overflow file is refused by the hook
        with open(os.path.join(self.repo, ov["file"]), "a") as f:
            f.write("x\n")
        c = subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "x"], capture_output=True, text=True)
        self.assertNotEqual(c.returncode, 0)
        self.assertIn("value block file", c.stderr)
        # staging again keeps only the newest summary file
        self.unstage()
        cfg["visibility"]["public"] = ["src/content/blog/other-%03d/**" % i for i in range(30)]
        with open(os.path.join(self.repo, ".claude", "studio", "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        self.assertEqual(self.stage().returncode, 0)
        files = [n for n in os.listdir(os.path.join(self.repo, ".claude", "studio", "local"))
                 if n.startswith("commit-summary-")]
        self.assertEqual(len(files), 1)

    def test_t2_pronounce_leftover_is_left_out(self):
        """v5.1 T2: the approved additions of a video in progress are not staged by a harness commit (a warning)."""
        pj = os.path.join(self.repo, ".claude", "studio", "pronounce.json")
        with open(pj, "w") as f:
            f.write('{"出口": "데구치"}')
        from stdo.state import harnessgate as hg
        real = hg.pronounce_verdict

        def exempt(ctx, providers=None, ctx_of=None):
            return hg.Verdict(discard=True, exempted=True, videos={"v1"})
        hg.pronounce_verdict = exempt
        try:
            from stdo.commit import checks, kinds
            from stdo.commit.gitx import Git
            from stdo.commit.harness import HarnessKind
            ctx = checks.Ctx(Git(self.repo, paths.git_env()), dict(os.environ), kinds.registry({}))
            col = HarnessKind().collect(ctx, None)
            self.assertNotIn(".claude/studio/pronounce.json", col.paths)
            self.assertIn("v1", col.warnings[0])
            hg.pronounce_verdict = lambda ctx, providers=None, ctx_of=None: hg.Verdict(discard=False)
            col = HarnessKind().collect(ctx, None)
            self.assertIn(".claude/studio/pronounce.json", col.paths)
        finally:
            hg.pronounce_verdict = real


class GuardValues(InitCase):
    """The guard's evidence for a harness commit (m1-plan §5.1): every line of the block, as printed."""

    def setUp(self):
        super().setUp()
        self.init()
        self.commit_all()
        self.s = Session(self.repo, dict(os.environ), dict(os.environ), SID)

    def staged(self, cfg_change):
        cfg = self.cfg()
        cfg_change(cfg)
        with open(os.path.join(self.repo, ".claude", "studio", "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        r = self.s.bash("python3 .claude/studio/scripts/check_commit.py --stage harness")
        self.assertEqual(r.code, 0, r)
        import re
        from test_e2e_m0 import values_of
        line = re.search(r"put this line in the question as it is:\n(.+)\n", r.out).group(1)
        return line, line.split(" | ")[0], values_of(r.out)

    def commit_with(self, text, label):
        self.s.ask(text, [label, "고칠 곳이 있다"], label)
        return self.s.bash('git commit -m "studio: settings"')

    def test_a_changed_value_line(self):
        line, label, vals = self.staged(lambda c: c.__setitem__("public_domains", ["a.example.com"]))
        self.assertEqual(vals, ['public_domains: ["example.com"] → ["a.example.com"]'])
        r = self.commit_with(line + "\n" + vals[0].replace("a.example", "b.example"), label)
        self.assertEqual(r.decision, "deny")
        r = self.commit_with(line + "\n" + vals[0], label)
        self.assertEqual((r.decision, r.code), ("allow", 0), r)

    def test_overflow_question(self):
        long = ["src/content/blog/post-%03d/**" % i for i in range(30)]
        line, label, vals = self.staged(lambda c: c["visibility"].__setitem__("public", long))
        ok, _ = okfile.read(self.repo)
        full = ok["values_settings"]
        # the whole (long) block without the file line: refused (only the file and its counts approve it)
        r = self.commit_with(line + "\n" + "\n".join(full), label)
        self.assertEqual(r.decision, "deny")
        # the file line without the counts: refused
        r = self.commit_with(line + "\n" + vals[0], label)
        self.assertEqual(r.decision, "deny")
        r = self.commit_with(line + "\n" + "\n".join(vals), label)
        self.assertEqual((r.decision, r.code), ("allow", 0), r)


class FirstInstall(InitCase):
    def test_first_install_value_block(self):
        need_node()
        self.init()
        r = self.script("check_commit.py", "--stage", "harness")
        self.assertEqual(r.returncode, 0, r.stderr)
        ok, _ = okfile.read(self.repo)
        self.assertEqual(ok["values_machine"], values.machine_lines(FAKE_ROOT, "0.12.2+fakec0de0001"))
        self.assertIn('visibility: (없음) → {"default":"unknown","public":["src/content/blog/**",'
                      '"public/blog-images/**"]}', ok["values_shown"])
        self.assertIn('내레이터: narrator ko qwen:Sohee "차분하게" (새로)', ok["values_shown"])
        self.assertIn("criteria.youtube.cer_max.ko: (없음) → 0.15", ok["values_shown"])
        self.assertIn("criteria.youtube.length_seconds.max: (없음) → 480", ok["values_shown"])
        for f in (".claude/studio/charter.md", ".claude/studio/formats/youtube.md", ".claude/studio/platforms/youtube.md"):
            self.assertTrue([l for l in ok["values_shown"] if l.startswith(f + ": ") and l.endswith("(새로)")], f)
        self.assertIsNone(ok["overflow"])
        # the hook never runs s2v (the machine part is not recomputed there): a broken s2v does not matter to it
        machine.write(self.repo, "/no/such/s2v")
        c = subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "harness"], capture_output=True, text=True)
        self.assertEqual(c.returncode, 0, c.stderr)

    def test_first_install_overflow(self):
        need_node()
        self.init(visibility_public=["src/content/blog/post-%03d/**" % i for i in range(30)])
        r = self.script("check_commit.py", "--stage", "harness")
        self.assertEqual(r.returncode, 0, r.stderr)
        ok, _ = okfile.read(self.repo)
        self.assertEqual(ok["overflow"]["reason"], values.FIRST_INSTALL_OVERFLOW)
        self.assertTrue([l for l in ok["values_shown"] if l.startswith(values.FIRST_INSTALL_OVERFLOW)])
        self.assertIn("first-install-overflow", r.stderr)  # the warning
        with open(os.path.join(self.repo, ok["overflow"]["file"])) as f:
            body = f.read()
        self.assertIn("s2v id: 0.12.2+fakec0de0001", body)  # the machine part is in the file

    def test_s2v_unreadable_at_first_install(self):
        self.init()
        machine.write(self.repo, os.path.join(self.tmp, "no-s2v"))
        r = self.script("check_commit.py", "--stage", "harness")
        self.assertEqual(r.returncode, 2)
        self.assertIn("first harness commit", r.stderr)


class ValuesUnit(StudioTestCase):
    KEYS = {"visibility", "web_roots", "public_domains", "allow_internal_commits"}

    def test_lines_limits_counts(self):
        old = {"visibility": {"default": "unknown", "public": ["a/**"]}, "web_roots": {}, "public_domains": [],
               "allow_internal_commits": False}
        new = copy.deepcopy(old)
        new["allow_internal_commits"] = True
        b = values.block(old, new, self.KEYS, [], [], "t" * 40, False)
        self.assertEqual(b["shown"], ["allow_internal_commits: false → true"])
        self.assertIsNone(b["overflow"])
        new["web_roots"] = {"/": "x" * 395}  # the value's JSON is 403 characters
        self.assertEqual(len(values.canon(new["web_roots"])), 403)
        b = values.block(old, new, self.KEYS, [], [], "t" * 40, False)
        self.assertEqual(b["overflow"]["reason"], "overflow")
        self.assertEqual(b["shown"][1:], ["allow_internal_commits: 값 바뀜", "web_roots./: 값 바뀜"])
        new["web_roots"] = {"/": "x" * 392}  # exactly 400: fits
        self.assertIsNone(values.block(old, new, self.KEYS, [], [], "t" * 40, False)["overflow"])
        many = {"k%d" % i: i for i in range(45)}
        b = values.block({}, many, set(many), [], [], "t" * 40, True)
        self.assertEqual(b["overflow"]["reason"], values.FIRST_INSTALL_OVERFLOW)  # 45 lines
        big = {"k%d" % i: "y" * 150 for i in range(30)}
        b = values.block({}, big, set(big), [], [], "t" * 40, False)
        self.assertTrue(b["overflow"])  # 30 lines but over 4 KB
        crit = [(".claude/studio/formats/youtube.md", None,
                 b'<!-- studio:criteria -->\n```json\n{"length_seconds": {"min": 1, "max": 2}, "chars_per_sec": '
                 b'{"ko": 5}, "cer_max": {"ko": 0.1}}\n```\n<!-- /studio:criteria -->\n')]
        b = values.block({}, many, set(many), [], [], "t" * 40, False, crit)
        self.assertIn("criteria.youtube: 4개 바뀜", b["shown"])
        self.assertTrue([l for l in b["shown"] if l.startswith(".claude/studio/formats/youtube.md: ")])
        self.assertIn("criteria.youtube.cer_max.ko: (없음) → 0.1", b["settings"])
        out = values.counts({"visibility": {"public": ["a", "b"]}}, {"visibility": {"public": ["b", "c", "d"]}},
                            {"visibility"})
        self.assertEqual(out, ["visibility.public: 3개 (+2 −1)"])
        self.assertEqual(values.counts({}, {"roles": {"a": True}}, {"roles"}), ["roles.a: 값 바뀜"])


# ---------------------------------------------------------------- update

class Update(InitCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.commit_all()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SID

    def plan(self, take=None):
        args = ["update", "plan"] + (["--take", take] if take else [])
        self.assertEqual(self.setup(*args), 0, self.last_err)
        return self.out_json()

    def item(self, p, path):
        return [i for i in p["templates"] if i["path"] == path][0]

    def apply(self, p, take=None):
        argv = ["update", "apply", "--expect", p["h12"]] + (["--take", take] if take else [])
        self.pend(argv, p["label"])
        return self.setup(*argv)

    def set_version(self, v):
        import re
        f = os.path.join(self.repo, ".claude", "studio", "scripts", "stdo", "__init__.py")
        with open(f) as fh:
            body = fh.read()
        with open(f, "w") as fh:
            fh.write(re.sub(r'SCRIPTS_VERSION = "\d+"', 'SCRIPTS_VERSION = "%d"' % v, body))

    def test_versions(self):
        p = self.plan()
        self.assertEqual(p["scripts"], {"replace": [], "add": [], "remove": []})
        self.assertTrue(all(i["state"] == "same" for i in p["templates"]))
        self.set_version(int(SCRIPTS_VERSION) + 1)
        p = self.plan()
        self.assertIn("newer than this plugin", p["refused"])
        self.assertEqual(self.apply(p), 3)
        self.set_version(int(SCRIPTS_VERSION) - 1)
        os.remove(os.path.join(self.repo, ".claude", "studio", "scripts", "stdo", "criteria.py"))
        with open(os.path.join(self.repo, ".claude", "studio", "scripts", "stdo", "old.py"), "w") as f:
            f.write("# gone in the new version\n")
        p = self.plan()
        self.assertIsNone(p["refused"])
        self.assertEqual((p["scripts"]["replace"], p["scripts"]["add"], p["scripts"]["remove"]),
                         (["stdo/__init__.py"], ["stdo/criteria.py"], ["stdo/old.py"]))
        argv = ["update", "apply", "--expect", p["h12"]]
        self.assertEqual(self.setup(*argv), 6)  # the person's answer first
        self.assertEqual(self.apply(p), 0, self.last_err)
        self.assertIsNone(update.repo_scripts_version(self.repo) - int(SCRIPTS_VERSION) or None)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "studio", "scripts", "stdo", "old.py")))
        self.assertEqual(self.plan()["scripts"], {"replace": [], "add": [], "remove": []})

    def write(self, rel, text):
        with open(os.path.join(self.repo, rel), "w") as f:
            f.write(text)

    def read(self, rel):
        with open(os.path.join(self.repo, rel)) as f:
            return f.read()

    def fake_new_templates(self, changes):
        """A newer plugin's templates: render.templated returns these texts for the listed files."""
        real = render.templated

        def newer(vals):
            out = real(vals)
            for rel, f in changes.items():
                out[rel] = f(out[rel])
            return out
        render.templated = newer
        self.addCleanup(setattr, render, "templated", real)

    def test_three_ways(self):
        g = ".claude/studio/guides/board.md"
        w = ".claude/agents/std-writer.md"
        fc = ".claude/agents/std-fact-checker.md"
        b = ".claude/studio/guides/copy.md"
        c = ".claude/studio/guides/script.md"
        self.write(b, self.read(b) + "- the channel's own rule\n")  # local changed, new == base → kept
        self.write(c, self.read(c) + "- local rule\n")  # both changed → conflict
        self.fake_new_templates({
            g: lambda t: t + "- new upstream rule\n",  # local == base → updated
            c: lambda t: t + "- upstream rule\n",
            w: lambda t: t.replace("## Rules", "## Rules\n- upstream persona rule"),
            fc: lambda t: t.replace("## Rules", "## Rules\n- upstream checker rule"),  # P-PERS: needs a choice
        })
        p = self.plan()
        st = {i["path"]: i["state"] for i in p["templates"]}
        # P1: every item that is not `same` carries what the person looks at
        self.assertIn("+- new upstream rule", self.item(p, g)["diff"]["unified"])
        self.assertIn("upstream persona rule", self.item(p, w)["diff"]["unified"])
        self.assertNotIn("diff", self.item(p, ".claude/studio/charter.md"))
        self.assertEqual((st[g], st[b], st[c], st[w], st[fc]),
                         ("update", "keep-local", "conflict", "update", "protected-needs-choice"))
        self.assertEqual(sorted(p["conflicts"]), sorted([c, fc]))
        # a local edit outside the persona block stays when the block is updated
        self.write(w, self.read(w) + "\nlocal note outside the block\n")
        p = self.plan()
        self.assertEqual(self.apply(p), 0, self.last_err)
        self.assertIn("new upstream rule", self.read(g))
        self.assertIn("the channel's own rule", self.read(b))
        self.assertIn("local rule", self.read(c))
        self.assertNotIn("upstream rule\n", self.read(c).replace("local rule", ""))
        self.assertIn("upstream persona rule", self.read(w))
        self.assertIn("local note outside the block", self.read(w))
        self.assertNotIn("upstream checker rule", self.read(fc))
        # unresolved ones are offered again; the person's choices are part of the hash
        p2 = self.plan()
        self.assertEqual(sorted(p2["conflicts"]), sorted([c, fc]))
        # keeping the local file of a conflict changes nothing on disk but settles it: still another hash
        self.assertNotEqual(self.plan(take="%s=local" % c)["h12"], p2["h12"])
        p3 = self.plan(take="%s=new,%s=local" % (fc, c))
        self.assertNotEqual(p3["h12"], p2["h12"])
        self.assertEqual(self.apply(p3, take="%s=new,%s=local" % (fc, c)), 0, self.last_err)
        self.assertIn("upstream checker rule", self.read(fc))
        self.assertIn("local rule", self.read(c))
        self.assertEqual(self.plan()["conflicts"], [])
        self.assertEqual(self.setup("update", "plan", "--take", "nope.md=new"), 2)

    def test_p1_criteria_diff(self):
        f = ".claude/studio/formats/youtube.md"
        self.fake_new_templates({f: lambda t: t.replace('"ko": 0.15', '"ko": 0.12')})
        d = self.item(self.plan(), f)["diff"]
        self.assertEqual(d["criteria"], ["criteria.youtube.cer_max.ko: 0.15 → 0.12"])

    def test_p2_persona_new_keeps_the_frontmatter(self):
        w = ".claude/agents/std-writer.md"
        self.write(w, self.read(w).replace("model: sonnet", "model: opus") + "\nlocal note\n")
        self.write(w, self.read(w).replace("## Rules", "## Rules\n- local persona rule"))
        self.fake_new_templates({w: lambda t: t.replace("## Rules", "## Rules\n- upstream persona rule")})
        self.assertEqual(self.item(self.plan(), w)["state"], "conflict")
        h_new = self.plan(take="%s=new" % w)["h12"]
        h_file = self.plan(take="%s=new-file" % w)["h12"]
        self.assertNotEqual(h_new, h_file)
        self.assertEqual(self.apply(self.plan(take="%s=new" % w), take="%s=new" % w), 0, self.last_err)
        text = self.read(w)
        self.assertIn("model: opus", text)  # the person's frontmatter stays
        self.assertIn("local note", text)
        self.assertIn("upstream persona rule", text)
        self.assertNotIn("local persona rule", text)
        self.write(w, text.replace("upstream persona rule", "local again"))
        self.assertEqual(self.apply(self.plan(take="%s=new-file" % w), take="%s=new-file" % w), 0, self.last_err)
        self.assertNotIn("model: opus", self.read(w))  # the whole file
        self.write(w, "no persona markers\n")
        self.assertEqual(self.setup("update", "plan", "--take", "%s=new" % w), 2)
        self.assertIn("new-file", self.last_err)

    def test_min_version_with_videos_in_progress(self):
        cfg = self.cfg()
        cfg["s2v"]["min_version"] = "0.12.0"
        with open(os.path.join(self.repo, ".claude", "studio", "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        p = self.plan()
        self.assertTrue(p["min_version"]["raise"])
        self.assertIsNone(p["refused"])
        d = os.path.join(self.repo, "studio", "videos", "v1", "work")
        os.makedirs(d)
        with open(os.path.join(d, "state.json"), "w") as f:
            json.dump({"video": "v1", "langs": {"ko": {"status": "active"}}}, f)
        p = self.plan()
        self.assertIn("videos are in progress (v1)", p["refused"])
        self.assertEqual(self.apply(p), 3)
        with open(os.path.join(d, "state.json"), "w") as f:
            json.dump({"video": "v1", "langs": {"ko": {"status": "done"}}}, f)
        p = self.plan()
        self.assertEqual(self.apply(p), 0, self.last_err)
        self.assertEqual(self.cfg()["s2v"]["min_version"], "0.12.1")


# ---------------------------------------------------------------- the guard

class GuardSetup(JudgeCase):
    def setUp(self):
        super().setUp()
        self.tpath = TR.transcript_path(self.env)

    def turn(self, label, qtext):
        t = TR.approval_turn(TR.T(), label, qtext=qtext)
        t.write(self.tpath)
        self.t = t

    def run_hook(self, cmd, cwd=None):
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd or self.repo, "session_id": "sess-1",
                "transcript_path": self.tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                "prompt_id": getattr(self, "t", None) and self.t.prompt or "p-none"}
        from stdo.guard import judge
        return judge.decide(hook, self.env, snapshot_loader=self.loader)

    def pending(self):
        try:
            with open(os.path.join(self.repo, ".claude", "studio", "local", "pending-approval.json")) as f:
                return json.load(f)
        except OSError:
            return None

    def test_no_harness_no_judgement(self):
        bare = os.path.join(self.tmp, "plain")
        subprocess.run(["git", "init", "-q", bare], check=True)
        for cmd in ("python3 %s init apply" % SETUP, "python3 %s init plan --answers /tmp/a.json" % SETUP,
                    "rm -rf build", "git commit -m x"):
            deny, ctx = self.run_hook(cmd, cwd=bare)
            self.assertIsNone(deny, "%s: %s" % (cmd, deny and deny.message()))
            self.assertIsNone(ctx.allow, cmd)

    def test_setup_approvals(self):
        from stdo.setup import labels as sl
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        cfg = json.load(open(os.path.join(self.repo, ".claude", "studio", "config.json")))
        old = cfg["public_domains"]
        new = ["example.com"]
        h = sl.setting_hash("public_domains", old, new)
        line = sl.config_line("public_domains", old, new)
        cmd = "python3 %s config set public_domains '[\"example.com\"]' --expect %s" % (SETUP, h)
        deny, ctx = self.run_hook(cmd)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.turn("설정 %s" % h, "설정을 바꿀까요? %s" % h)  # the change line missing
        deny, ctx = self.run_hook(cmd)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn("value block", deny.message())
        self.turn("설정 %s" % h, "설정을 바꿀까요? %s\n%s" % (h, line))
        deny, ctx = self.run_hook(cmd)
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)
        self.assertEqual(self.pending()["answer"], "설정 %s" % h)
        # without --expect: no label to check
        deny, _ = self.run_hook("python3 %s config set public_domains '[\"example.com\"]'" % SETUP)
        self.assertEqual(deny.rule, "G-APPROVAL")
        # --proxy is never accepted for setup approvals
        deny, _ = self.run_hook(cmd + " --proxy")
        self.assertEqual(deny.rule, "G-PROXY")
        # an unprotected key, a get, a preview, an update plan: no judgement
        for c in ("python3 %s config set commit_audio true" % SETUP, "python3 %s config get" % SETUP,
                  "python3 %s config preview public_domains '[]'" % SETUP, "python3 %s update plan" % SETUP):
            deny, ctx = self.run_hook(c)
            self.assertIsNone(deny, "%s: %s" % (c, deny and deny.message()))
            self.assertIsNone(ctx.allow, c)
        # update apply and narrator set need the answer
        for c in ("python3 %s update apply --expect %s" % (SETUP, h),
                  "python3 %s narrator set ko --engine qwen:Sohee --style x --expect %s" % (SETUP, h)):
            self.t = None
            if os.path.exists(self.tpath):
                os.remove(self.tpath)
            deny, _ = self.run_hook(c)
            self.assertEqual(deny.rule, "G-EVIDENCE", c)
        self.turn("갱신 %s" % h, "업데이트할까요? %s" % h)
        deny, ctx = self.run_hook("python3 %s update apply --expect %s" % (SETUP, h))
        self.assertIsNone(deny, deny and deny.message())

    def test_installed_json_is_wiring(self):
        d = self.decide("Write", {"file_path": os.path.join(self.repo, ".claude/studio/installed.json"), "content": "{}"})
        self.assertEqual(d.rule, "G-PROT")
        d = self.decide("Write", {"file_path": os.path.join(self.repo, ".claude/studio/local/commit-summary-a.txt"),
                                  "content": "x"})
        self.assertEqual(d.rule, "G-PROT")


class OverlayQuestion(InitCase):
    """J29 (M1b review Y10): the overlay question shows every key with its number of entries."""

    def test_counts_must_be_shown(self):
        from stdo.state import cli as scli, store
        self.init()
        self.commit_all()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SID
        store.enable_writes()
        src = os.path.join(self.tmp, "overlay.json")
        data = {"internal": {"hosts": ["wiki.example.invalid"], "terms": ["Kestrel", "Osprey"]}}
        raw = json.dumps(data).encode()
        with open(src, "wb") as f:
            f.write(raw)
        import hashlib
        h = hashlib.sha256(raw).hexdigest()[:12]
        argv = ["overlay", "--from", src, "--expect", h]

        def run():
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                return scli.main(list(argv), cwd=self.repo), err.getvalue()
        self.pend(argv, "사내설정 %s" % h, question="사내설정을 바꿀까요? %s" % h)
        code, err = run()
        self.assertEqual(code, 6)
        self.assertIn("internal.terms: 2개", err)
        lines = "\n".join(["internal.hosts: 1개", "internal.sources: 0개", "internal.terms: 2개",
                           "internal.videos: 0개", "internal.actors: 0개"])
        self.pend(argv, "사내설정 %s" % h, question="사내설정을 바꿀까요? %s\n%s" % (h, lines.replace("2개", "3개")))
        self.assertEqual(run()[0], 6)
        self.pend(argv, "사내설정 %s" % h, question="사내설정을 바꿀까요? %s\n%s" % (h, lines))
        code, err = run()
        self.assertEqual(code, 0, err)


# ---------------------------------------------------------------- end to end: init apply → the first harness commit

class InitE2E(InitCase):
    def test_init_then_first_harness_commit(self):
        need_node()
        env = dict(os.environ)
        s = Session(self.repo, env, env, SID)
        answers = os.path.join(self.tmp, "answers.json")
        with open(answers, "w") as f:
            json.dump(self.answers(), f, ensure_ascii=False)
        # no harness yet: the guard judges nothing about setup.py init
        r = s.bash("python3 %s init plan --answers %s" % (SETUP, answers))
        self.assertEqual((r.decision, r.code), (None, 0), r)
        r = s.bash("python3 %s init apply" % SETUP)
        self.assertEqual(r.code, 0, r)
        r = s.bash("python3 .claude/studio/scripts/check_commit.py --stage harness")
        self.assertEqual(r.code, 0, r)
        import re
        line = re.search(r"put this line in the question as it is:\n(.+)\n", r.out).group(1)
        label = line.split(" | ")[0]
        from test_e2e_m0 import values_of
        vals = values_of(r.out)
        self.assertIn("s2v id: 0.12.2+fakec0de0001", vals)
        # the summary line alone is not enough
        s.ask("하네스를 커밋할까요?\n" + line, [label, "고칠 곳이 있다"], label)
        r = s.bash('git commit -m "studio: harness"')
        self.assertEqual(r.decision, "deny", r)
        self.assertIn("value block", r.reason)
        # with every value line
        s.ask("하네스를 커밋할까요?\n" + line + "\n" + "\n".join(vals), [label, "고칠 곳이 있다"], label)
        r = s.bash('git commit -m "studio: harness"')
        self.assertEqual((r.decision, r.code), ("allow", 0), r)
        self.assertFalse(harnessgate.check(self.repo).blocking)

    def test_proxy_mode_cannot_make_the_first_harness_commit(self):
        need_node()
        self.init()
        env = dict(os.environ, STUDIO_SANDBOX="1")
        with open(paths.sandbox_file(), "w") as f:
            json.dump({"sandbox_root": self.tmp}, f)
        s = Session(self.repo, env, env, SID)
        r = s.bash("python3 .claude/studio/scripts/check_commit.py --stage harness")
        self.assertEqual(r.code, 0, r)
        r = s.bash('git commit -m "studio: harness"')
        self.assertEqual(r.decision, "deny", r)
        self.assertIn("protected settings", r.reason)


class Criteria(StudioTestCase):
    def test_reader(self):
        with open(os.path.join(render.TEMPLATES, "formats", "youtube.md")) as f:
            c = criteria.parse(f.read())
        self.assertEqual(c["length_seconds"], {"min": 180, "max": 480})
        tpl = open(os.path.join(render.TEMPLATES, "formats", "youtube.md")).read()
        for bad in (tpl.replace('"ko": 0.15', '"ko": NaN'), tpl.replace('"ko": 0.15', '"ko": Infinity'),
                    tpl.replace('"ko": 0.15', '"ko": true'), tpl.replace('"min": 180', '"min": false')):
            with self.assertRaises(criteria.Missing):
                criteria.parse(bad)
        criteria.parse(tpl, ("ko", "en"))
        with self.assertRaises(criteria.Missing) as e:
            criteria.parse(tpl, ("ko", "fr"))
        self.assertIn("fr", str(e.exception))
        for bad in ("no block", "<!-- studio:criteria -->\n```json\n{}\n```\n<!-- /studio:criteria -->",
                    '<!-- studio:criteria -->\n```json\n{"length_seconds": {"min": 5, "max": 1}, "chars_per_sec": '
                    '{"ko": 1}, "cer_max": {"ko": 0.1}}\n```\n<!-- /studio:criteria -->'):
            with self.assertRaises(criteria.Missing):
                criteria.parse(bad)

