"""A video driven through the real M0b-2 commands (stage-done → shown → approve) with injected
inspect values and evidence written the way the guard (M0d-2) will write it."""

import contextlib
import copy
import io
import json
import os
import time

import checkfix
import helpers
import state_fixtures as F
from helpers import StudioTestCase
from stdo.state import cli, evidence, store
from stdo.state.argv import argv_sha
from stdo.state.collect import Providers
from stdo.state.hashes import brief_core

SESSION = "sess-test"


def stamp(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if t is None else t))


class ApproveCase(StudioTestCase):
    outputs = ("youtube",)
    platforms = {"youtube": ["youtube"]}
    location = "public"
    auto_checks = True  # stage-done finds a passing check result written over the current inputs (checkfix)

    def setUp(self):
        super().setUp()
        store.enable_writes()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.repo = helpers.make_repo(self.tmp)
        sub = ("local", "videos") if self.location == "local" else ("videos",)
        self.vdir = os.path.join(self.repo, "studio", *sub, "v1")
        os.makedirs(self.vdir)
        st = F.state(outputs=self.outputs, platforms=self.platforms)
        st["location"] = self.location
        st["brief"]["core"] = brief_core([F.C1], [{"name": "narrator"}])  # what record-brief computes
        store.create(self.vdir, st)
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write("# script\n")
        self.claims({"excerpts": ["The cat sat on the mat."],
                     "copy_excerpts": {p: ["It was warm."] for p in self.platforms}})
        c = F.current(outputs=self.outputs, platforms=tuple(self.platforms))
        self.ins = {"s2v_version": c["s2v_version"], "stale_build": False, "hash_version": 1, "lang": "ko",
                    "hashes": {"content": c["content"], "voice": c["voice"], "audio": c["audio"],
                               "presentation_by_output": dict(c["presentation"]), "engine": dict(c["engine"])},
                    "reasons": {}, "outputs": [{"name": o} for o in self.outputs]}
        self.src = "src1"
        self.text = "The cat sat on the mat.\nIt was warm."
        self.old_ins = {}
        self.ver = {"id": c["s2v_version"], "version": "0.12.1", "commit": "c0ffee", "dirty": False,
                    "stale_build": False}
        self.providers = Providers(inspect=lambda ctx: copy.deepcopy(self.ins),
                                   source=lambda ctx, st: (self.src, self.text),
                                   inspect_at=lambda ctx, hv: copy.deepcopy(self.old_ins[hv]),
                                   version=lambda ctx: dict(self.ver),
                                   sentences=lambda ctx: [{"id": "s:0:0", "lock": None}])
        self.tool = 0

    # ---------- running ----------

    def cli(self, *argv):
        if self.auto_checks:
            checkfix.before_stage_done(self.repo, list(argv), self.providers)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), providers=self.providers, cwd=self.repo)
        self.last_out, self.last_err = out.getvalue(), err.getvalue()
        return code

    def state(self):
        return store.read_state(self.vdir)

    def pend(self, argv, answer, session=SESSION, tool=None, index=0, mode="human", written_at=None,
             question="Approve?", reason=None):
        if tool is None:
            self.tool += 1
            tool = "toolu_%d" % self.tool
        ev = {"schema": 1, "argv_sha": argv_sha(list(argv)), "session_id": session, "tool_use_id": tool,
              "question_index": index, "question": question, "answer": answer, "mode": mode,
              "written_at": written_at or stamp()}
        if reason:
            ev["reason"] = reason
        os.makedirs(evidence.local_dir(self.repo), exist_ok=True)
        with open(evidence.pending_path(self.repo), "w") as f:
            json.dump(ev, f)
        return ev

    def hash12_of(self):
        line = [l for l in self.last_out.splitlines() if l.startswith("hash12 ")]
        return line[0].split()[1] if line else None

    def approve(self, gate, expect, *extra, answer=None, **pend):
        argv = ["approve", "v1", gate, "--expect", expect] + list(extra)
        self.pend(argv, answer or "승인 v1 %s" % expect, **pend)
        return self.cli(*argv)

    # ---------- moving a video along ----------

    def frames(self, o, content=b'{"stills": 1}'):
        d = os.path.join(self.repo, "studio", "out", "v1", "ko", "%s.ko.frames" % o)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "index.json")
        tmp = p + ".new"
        with open(tmp, "wb") as f:
            f.write(content)
        os.replace(tmp, p)  # a new file (new inode), as s2v writes it

    def show(self, gate, scope=None):
        if gate == "3":
            self.assertEqual(self.cli("shown", "v1", "3", "--output", scope, "--begin"), 0, self.last_err)
            self.frames(scope)
            code = self.cli("shown", "v1", "3", "--output", scope, "--end")
        elif gate in ("4a",):
            code = self.cli("shown", "v1", gate, "--output", scope)
        elif gate == "4b":
            code = self.cli("shown", "v1", gate, "--platform", scope)
        else:
            code = self.cli("shown", "v1", gate)
        self.assertEqual(code, 0, self.last_err)
        return self.hash12_of()

    STAGES = {"1": ["script", "verify"], "2": ["cast", "tts", "audition"], "3": ["board", "visual-check"],
              "4a": ["render"], "4b": ["copy"]}

    def scopes(self, gate):
        if gate in ("3", "4a"):
            return list(self.outputs)
        if gate == "4b":
            return list(self.platforms)
        return [None]

    def pass_gate(self, gate):
        for sc in self.scopes(gate):
            for st in self.STAGES[gate]:
                args = ["stage-done", "v1", st]
                if gate in ("3", "4a"):
                    args += ["--output", sc]
                if gate == "4b":
                    args += ["--platform", sc]
                self.assertEqual(self.cli(*args), 0, "%s %s: %s" % (st, sc, self.last_err))
        h = None
        for sc in self.scopes(gate):
            h = self.show(gate, sc)
        self.assertTrue(h, "no hash12 after showing %s" % gate)
        self.assertEqual(self.approve(gate, h), 0, self.last_err)
        return h

    def pass_all(self, upto="4b"):
        for g in ("1", "2", "3", "4a", "4b"):
            self.pass_gate(g)
            if g == upto:
                return

    def render_files(self, o, body=b"mp4"):
        d = os.path.join(self.repo, "studio", "out", "v1", "ko")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "%s.ko.mp4" % o), "wb") as f:
            f.write(body)

    def copy_file(self, p, body="copy"):
        d = os.path.join(self.repo, "studio", "copy", "v1", "ko")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "%s.md" % p), "w") as f:
            f.write(body)

    def claims(self, body):
        d = os.path.join(self.vdir, "work", "ko")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "claims-map.json"), "w") as f:
            f.write(body if isinstance(body, str) else json.dumps(body))

    def brief(self, outputs, platforms):
        F.brief_ready(self.repo, self.vdir)  # what record-brief reads (M1e)
        p = os.path.join(self.vdir, "work", "brief.json")
        with open(p, "w") as f:
            json.dump({"claims": [F.C1], "roles": [{"name": "narrator"}], "outputs": list(outputs),
                       "platforms": platforms}, f)
        return p

    def write_state(self, st):
        with open(os.path.join(self.vdir, "work", "state.json"), "w") as f:
            json.dump(st, f)

    def events(self):
        return store.read_log(self.vdir)
