"""M0b-2 with the real script2video inspect (m0b2-plan §7.5; --full)."""

import contextlib
import io
import json
import os

import helpers
import state_fixtures as F
from approve_base import SESSION, stamp
from helpers import StudioTestCase
from stdo.state import cli, evidence, store
from stdo.state.argv import argv_sha
from stdo.state.collect import run_inspect
from stdo.state.hashes import brief_core, hash_of

SCRIPT = "---\ntitle: Test\nlang: en\noutputs:\n  youtube: { aspect: \"16:9\" }\n---\n\n# Intro {#intro}\n\nHello there.\n"


class RealApprove(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.s2v = helpers.s2v_path(self)
        os.environ.update(self.s2v_environ)
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        store.enable_writes()
        self.repo = helpers.make_repo(self.tmp, s2v=self.s2v)
        os.makedirs(os.path.join(self.repo, "docs"))
        with open(os.path.join(self.repo, "docs", "a.md"), "w") as f:
            f.write("# A\n\nHello there.\n")
        self.vdir = os.path.join(self.repo, "studio", "videos", "v1")
        os.makedirs(os.path.join(self.vdir, "work", "source"))
        with open(os.path.join(self.vdir, "work", "source", "a.md"), "w") as f:
            f.write("# A\n\nHello there.\n")
        with open(os.path.join(self.vdir, "script.en.md"), "w") as f:
            f.write(SCRIPT)
        os.makedirs(os.path.join(self.vdir, "work", "en"))
        with open(os.path.join(self.vdir, "work", "en", "claims-map.json"), "w") as f:
            json.dump({"excerpts": ["Hello there."], "copy_excerpts": {}}, f)
        self.script = os.path.join(self.vdir, "script.en.md")
        st = F.state()
        st["source_lang"] = "en"
        st["langs"] = {"en": st["langs"]["ko"]}
        ver = json.loads(helpers.run_s2v(self, ["--version", "--json"]).stdout)
        st["s2v"] = {k: ver.get(k) for k in ("id", "version", "commit", "dirty")}
        from stdo.state.hashes import source_hash_repo_md
        live = source_hash_repo_md(self.repo, "docs/a.md", [])
        st["source"]["frozen_hash"] = live
        st["brief"]["core"] = brief_core(["C-1"], [{"name": "narrator"}])
        store.create(self.vdir, st)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), cwd=self.repo)
        return code, out.getvalue(), err.getvalue()

    def test_f1_hash_version_1_is_the_default(self):
        self.assertEqual(run_inspect(self.s2v, self.script)["hashes"],
                         run_inspect(self.s2v, self.script, hash_version=1)["hashes"])

    def test_f2_unsupported_old_method_stops_repin(self):
        st = store.read_state(self.vdir)
        st["langs"]["en"]["approved"]["1"] = {"tuple": {}, "hash_version": 2}
        st["s2v"]["id"] = "0.0.1+old"
        with open(os.path.join(self.vdir, "work", "state.json"), "w") as f:
            json.dump(st, f)
        to_id = run_inspect(self.s2v, self.script)["s2v_version"]
        h = hash_of({"video": "v1", "from_id": "0.0.1+old", "to_id": to_id})[:12]
        argv = ["repin", "v1", "--expect", h]
        self.pend(argv, "재고정 %s" % h)
        before = store.read_state(self.vdir)
        code, _, err = self.run_cli(*argv)
        self.assertEqual(code, 4, err)
        self.assertIn("cannot compute hash_version 2", err)
        self.assertEqual(store.read_state(self.vdir), before)

    def pend(self, argv, answer):
        ev = {"schema": 1, "argv_sha": argv_sha(argv), "session_id": SESSION, "tool_use_id": "toolu_real",
              "question_index": 0, "question": "?", "answer": answer, "mode": "human", "written_at": stamp()}
        os.makedirs(evidence.local_dir(self.repo), exist_ok=True)
        with open(evidence.pending_path(self.repo), "w") as f:
            json.dump(ev, f)

    def test_f3_approve_1_with_the_real_inspect(self):
        for st in ("script", "verify"):
            self.assertEqual(self.run_cli("stage-done", "v1", st)[0], 0)
        code, out, err = self.run_cli("shown", "v1", "1")
        self.assertEqual(code, 0, err)
        h = out.split()[1]
        argv = ["approve", "v1", "1", "--expect", h]
        self.pend(argv, "승인 %s" % h)
        code, _, err = self.run_cli(*argv)
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_cli("next", "v1", "--json")
        self.assertEqual(json.loads(out)["redo"]["stage"], "cast")
