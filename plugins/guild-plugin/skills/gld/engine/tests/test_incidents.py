"""Readiness R1: engine incident bundles (design/guild/24-redesign/readiness/incidents.md).

Real records: VW2 app_a#1938 (E1) and VW3 app_a#1938 (E2), cut to the stop and its run (fixtures/incidents,
built from validation-archive; paths anonymised). Both stopped as a done-gate leader escalate (env-problem) — A13
`label`, no engine code — and must still become a `suspect` incident with the signature the fixed-defects list
gives E1 and E2. Plus: the defect kind, merging a recurrence, secret removal (both layers), the retro verdicts
fixed / unfixed / recurred, the driver and CLI wiring. Temp engine homes only; the real ~/.gld is never touched.
"""

import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from gxengine import cli, codes, driver, incidents, outbound, paths as pathsmod, schema, store
from tests import c_world as W

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(ENGINE)))
FIX = os.path.join(ENGINE, "tests", "fixtures", "incidents")
REPO = "owner/app_a"
SIG_ESCALATE = "escalate:env-problem @ done-gate"

GH_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"           # a GitHub classic token shape (fake)
ANT_KEY = "sk-ant-" + "api03-abcdefghijklmnopqrstuvwxyz0123"           # an Anthropic key shape (fake)
ENV_SECRET = "s3cr3t-value-from-the-environment"


def fixed(*ids):
    """fixed-defects entries for the ids, taken from the shipped list (and a made-up E9 for the defect kind)."""
    extra = {"E9": {"id": "E9", "signature": "engine-error @ mutation._control", "kind": "defect",
                    "fixed_in": {"version": "1.0.0-exp.4", "commit": None}, "summary": "s", "appeared_as": "a"}}
    by = {e["id"]: e for e in incidents.load_fixed()}
    by.update(extra)
    return [by[i] for i in ids]


class Home(unittest.TestCase):
    """A temp engine home with a fake CLI config folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        self.home = os.path.join(self.tmp, "gld")
        self.cfg = os.path.join(self.tmp, "claude-cfg")
        os.makedirs(self.home)
        os.makedirs(self.cfg)
        self.environ = {"HOME": self.tmp, "CLAUDE_CONFIG_DIR": self.cfg, "GLD_ENGINE_HOME": self.home,
                        "PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, name, issue=1938, repo=REPO):
        """Copy fixture `name` into records/<repo>/<issue>/; returns (paths, state)."""
        paths = pathsmod.EnginePaths(self.home, repo, issue)
        if os.path.exists(paths.issue_dir):
            shutil.rmtree(paths.issue_dir)
        shutil.copytree(os.path.join(FIX, name), paths.issue_dir)
        return paths, store.load_state(paths)

    def transcript(self, paths, text):
        """The CLI's own transcript of the done-gate session 2 (its session id from stream.jsonl)."""
        with open(paths.attempt_file("done-gate", 2, "stream.jsonl"), encoding="utf-8") as f:
            sid = incidents._session_id(f.read())
        d = os.path.join(self.cfg, "projects", "-home-u-projects--gld-app-a-1938")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "w", encoding="utf-8") as f:
            f.write(text)
        return sid

    def record(self, paths, state, ids=(), **kw):
        return incidents.record_stop(paths, state, plugin_root=PLUGIN_ROOT, environ=self.environ,
                                     fixed=fixed(*ids), **kw)

    def incident(self, sl):
        ip = pathsmod.IncidentPaths(self.home)
        return store.read_record(ip, ip.incident_json(sl), "incident")


class RealRecords(Home):
    def test_vw2_e1_is_a_suspect_incident_with_the_e1_signature(self):
        paths, state = self.put("vw2_1938")
        self.assertEqual(codes.stop_cause(state["stop"]["reason"]), "label")      # not an engine code (A13)
        self.transcript(paths, '{"type":"user","message":"the session as the CLI kept it"}\n')
        sl = self.record(paths, state)
        inc = self.incident(sl)
        self.assertEqual((inc["kind"], inc["signature"], inc["count"]), ("suspect", SIG_ESCALATE, 1))
        self.assertEqual(SIG_ESCALATE, {e["id"]: e for e in incidents.load_fixed()}["E1"]["signature"])
        occ = inc["occurrences"][0]
        self.assertEqual((occ["repo"], occ["issue"], occ["tracker"], occ["step"], occ["escalate_reason"]),
                         (REPO, 1938, 1979, "done-gate", "env-problem"))
        self.assertEqual(occ["at"], state["stop"]["at"])
        self.assertEqual(occ["records"], paths.issue_dir)
        self.assertTrue(any('"event":"stop"' in l and "needs_human" in l for l in occ["log"]))
        self.assertTrue(occ["engine"]["version"])
        files = {f["path"] for f in inc["evidence"]["files"]}
        for want in ("log.jsonl", "mutation-record.json", "sessions/done-gate-2/stream.jsonl",
                     "sessions/done-gate-2/result.json", "sessions/done-gate-2/in/leader-input.json",
                     "sessions/done-gate-2/transcript.jsonl"):
            self.assertIn(want, files)
        ev = pathsmod.IncidentPaths(self.home).evidence_dir(sl)
        with open(os.path.join(ev, "mutation-record.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["rows"][0]["status"], "not-run")             # what E1 looked like
        with open(os.path.join(ev, "log.jsonl"), encoding="utf-8") as f:
            log = f.read()
        self.assertIn('"event":"engine-start"', log)
        self.assertIn('"reason":"env-problem"', log)

    def test_vw3_e2_recurs_into_the_same_incident_without_new_evidence(self):
        paths, state = self.put("vw2_1938")
        sl = self.record(paths, state)
        ev = pathsmod.IncidentPaths(self.home).evidence_dir(sl)
        before = sorted(os.listdir(os.path.join(ev, "sessions")))
        paths, state = self.put("vw3_1938")
        self.assertEqual(self.record(paths, state, ids=("E1",)), sl)
        inc = self.incident(sl)
        self.assertEqual((inc["count"], len(inc["occurrences"]), inc["evidence"]["occurrence"]), (2, 2, 1))
        self.assertEqual(sorted(os.listdir(os.path.join(ev, "sessions"))), before)
        o1, o2 = inc["occurrences"]
        self.assertEqual((o1["engine"]["fixes"], o2["engine"]["fixes"]), ([], ["E1"]))
        self.assertNotEqual(o1["at"], o2["at"])
        self.assertTrue(any("killed" in l for l in o2["log"]) or o2["log"])

    def test_the_same_stop_reported_twice_counts_once(self):
        paths, state = self.put("vw3_1938")
        sl = self.record(paths, state)
        self.assertIsNone(self.record(paths, state))
        self.assertEqual(self.incident(sl)["count"], 1)

    def test_a_human_answer_label_stop_or_an_issue_stop_is_no_incident(self):
        paths, state = self.put("vw3_1938")
        for stop in (dict(state["stop"], recommendation=dict(state["stop"]["recommendation"],
                                                             reason="needs-human-decision")),
                     dict(state["stop"], recommendation=None),
                     {"status": "needs_human", "reason": "new-collaborator-comment", "step": "implement", "at": "x"},
                     {"status": "needs_human", "reason": "pr-review", "step": None, "at": "x"},
                     {"status": "needs_human", "reason": "base-red", "step": "test", "at": "x"},
                     dict(state["stop"], status="needs_leader")):
            with self.subTest(stop=stop.get("reason")):
                self.assertIsNone(incidents.classify(stop))
                self.assertIsNone(self.record(paths, dict(state, stop=stop)))
        self.assertFalse(os.path.isdir(os.path.join(self.home, "incidents")) and
                         [n for n in os.listdir(os.path.join(self.home, "incidents")) if not n.startswith(".")])


class Signatures(unittest.TestCase):
    TB = ('Traceback (most recent call last):\n'
          '  File "/p/skills/gld/engine/gxengine/driver.py", line 3400, in _loop\n    _mutation_proof(env, nxt)\n'
          '  File "/p/skills/gld/engine/gxengine/mutation.py", line 480, in _control\n    run(...)\n'
          '  File "/usr/lib/python3/subprocess.py", line 10, in run\n    raise X\nOSError: boom\n')

    def test_engine_codes_are_defects(self):
        C = incidents.classify
        self.assertEqual(C({"status": "needs_human", "reason": "engine-error", "step": "done-gate"}, self.TB),
                         ("defect", "engine-error @ mutation._control"))
        self.assertEqual(C({"status": "needs_human", "reason": "engine-error", "step": None}, None),
                         ("defect", "engine-error @ unknown"))
        self.assertEqual(C({"status": "needs_human", "reason": "canary-failed", "step": "analyze"}),
                         ("defect", "canary-failed @ analyze"))
        self.assertEqual(C({"status": "needs_human", "reason": "infra-stop", "step": "implement", "detail": "api"}),
                         ("defect", "infra-stop:api @ implement"))
        self.assertEqual(C({"status": "needs_human", "reason": "output-format-twice", "step": None}),
                         ("defect", "output-format-twice @ start"))

    def test_a_quota_stop_is_no_incident(self):
        self.assertIsNone(incidents.classify({"status": "needs_human", "reason": "infra-stop", "step": "test",
                                              "detail": "quota"}))

    def test_suspects(self):
        C = incidents.classify
        self.assertEqual(C({"status": "needs_human", "reason": "blocked", "step": "fix-discovery",
                            "recommendation": {"answer": "rerun", "reason": "env-problem"}}),
                         ("suspect", "escalate:env-problem @ blocked/fix-discovery"))
        self.assertEqual(C({"status": "needs_human", "reason": "done-gate", "step": "done-gate",
                            "leader_failed": {"code": "output-format", "detail": "manual-not-in-checklist"}}),
                         ("suspect", "leader-failed:output-format:manual-not-in-checklist @ done-gate"))

    def test_the_slug(self):
        a, b = incidents.slug("a-b @ c"), incidents.slug("a @ b-c")
        self.assertNotEqual(a, b)
        self.assertTrue(pathsmod.is_incident_slug(a) and pathsmod.is_incident_slug(b))
        self.assertTrue(incidents.slug(SIG_ESCALATE).startswith("escalate-env-problem-done-gate-"))
        self.assertTrue(pathsmod.is_incident_slug(incidents.slug("engine-error @ " + "x" * 300)))
        for bad in ("../x-0123abcd", "a", "A-0123abcd", "x-0123abcz"):
            self.assertFalse(pathsmod.is_incident_slug(bad), bad)

    def test_the_signature_grammar(self):
        K = incidents.signature_kind
        self.assertEqual([K(s) for s in (SIG_ESCALATE, "engine-error @ mutation._control", "canary-failed @ analyze",
                                         "infra-stop:api @ test", "silent @ runner._overlay_runs",
                                         "leader-failed:output-format @ done-gate", "sprint-engine-error @ sprint.go")],
                         ["suspect", "defect", "defect", "defect", "silent", "suspect", "defect"])
        for bad in ("done-gate @ done-gate", "escalate:nope @ done-gate", "infra-stop:nope @ x", "engine-error@x",
                    "new-collaborator-comment @ x", "canary-failed:api @ x", "x"):
            self.assertIsNone(K(bad), bad)


class Secrets(Home):
    def setUp(self):
        super().setUp()
        self.environ["GH_TOKEN"] = ENV_SECRET
        self.paths, self.state = self.put("vw3_1938")
        stream = self.paths.attempt_file("done-gate", 2, "stream.jsonl")
        with open(stream, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "text": f"token {GH_TOKEN} and {ANT_KEY}",
                                "env": f"GH_TOKEN={ENV_SECRET}", "cfg": 'password: "hunter2-hunter2"',
                                "h": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345"}) + "\n")
        self.transcript(self.paths, f'{{"type":"assistant","text":"curl https://bob:pa55word-xyz@example.com {GH_TOKEN}"}}\n')
        self.state["stop"]["note"] = f"the key was {ANT_KEY}"

    def evidence_text(self, sl):
        ev = pathsmod.IncidentPaths(self.home).incident_dir(sl)
        out = []
        for d, _, names in os.walk(ev):
            for n in names:
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    out.append(f.read())
        return "\n".join(out)

    def test_no_secret_value_is_left_anywhere_in_the_bundle(self):
        sl = self.record(self.paths, self.state)
        text = self.evidence_text(sl)
        for secret in (GH_TOKEN, ANT_KEY, ENV_SECRET, "hunter2-hunter2", "abcdefghijklmnopqrstuvwxyz012345",
                       "pa55word-xyz"):
            self.assertNotIn(secret, text)
        self.assertIn("[REDACTED:env:GH_TOKEN]", text)
        self.assertIn("[REDACTED:gate-", text)
        inc = self.incident(sl)
        by = {f["path"]: f for f in inc["evidence"]["files"]}
        self.assertGreaterEqual(by["sessions/done-gate-2/stream.jsonl"]["redacted"], 5)
        self.assertGreaterEqual(by["sessions/done-gate-2/transcript.jsonl"]["redacted"], 2)
        with open(os.path.join(pathsmod.IncidentPaths(self.home).evidence_dir(sl), "sessions", "done-gate-2",
                               "stream.jsonl"), encoding="utf-8") as f:
            for line in f.read().splitlines():
                json.loads(line)                                    # every redacted line is still JSON

    def test_the_gate_layer_removes_a_line_the_first_layer_missed(self):
        with mock.patch.object(incidents, "_GATE_RES", ()):
            sl = self.record(self.paths, self.state)
        text = self.evidence_text(sl)
        self.assertNotIn(GH_TOKEN, text)
        self.assertNotIn(ANT_KEY, text)
        self.assertIn(incidents.REDACTED_LINE, text)

    def test_no_scanner_no_copy(self):
        with mock.patch.object(outbound, "scan_text", side_effect=outbound.ScanError("gone")):
            sl = self.record(self.paths, self.state)
        inc = self.incident(sl)
        self.assertEqual(inc["evidence"]["files"], [])
        self.assertTrue(inc["evidence"]["withheld"])
        self.assertEqual({w["why"] for w in inc["evidence"]["withheld"]}, {"scanner-unavailable"})
        self.assertEqual((inc["occurrences"][0]["log"], inc["occurrences"][0]["note"]), ([], None))
        self.assertFalse(os.path.isdir(pathsmod.IncidentPaths(self.home).evidence_dir(sl)))

    def test_the_engine_list_is_the_gates_list(self):
        gate = os.path.join(PLUGIN_ROOT, "skills", "gld", "gates", "gate_precommit.py")
        spec = importlib.util.spec_from_file_location("gx_gate_for_test", gate)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(tuple(rx.pattern for rx in mod.INLINE_SECRET_RES), incidents.GATE_SECRET_PATTERNS)

    def test_size_caps(self):
        with mock.patch.object(incidents, "FILE_MAX_BYTES", 2000):
            sl = self.record(self.paths, self.state)
        inc = self.incident(sl)
        self.assertIn("too-large", {w["why"] for w in inc["evidence"]["withheld"]})


class Verdicts(Home):
    """Retro: fixed → removed, unfixed → kept, recurred → kept with the mark."""

    def two(self, ids_first=(), ids_second=("E1",)):
        paths, state = self.put("vw2_1938")
        sl = self.record(paths, state, ids=ids_first)
        paths, state = self.put("vw3_1938")
        self.record(paths, state, ids=ids_second)
        return sl

    def test_fixed_every_occurrence_is_explained_and_prune_removes_it(self):
        sl = self.two()                                  # VW2 knew no fix, VW3 knew E1 only — E2 explains it
        inc = self.incident(sl)
        self.assertEqual(incidents.fix_status(inc, fixed("E1", "E2")), ("fixed", ["E1", "E2"], []))
        rows = incidents.prune(self.home, apply=False, fixed=fixed("E1", "E2"))
        self.assertEqual([r["action"] for r in rows], ["would-remove"])
        self.assertTrue(os.path.isdir(rows[0]["path"]))
        rows = incidents.prune(self.home, apply=True, fixed=fixed("E1", "E2"))
        self.assertEqual([r["action"] for r in rows], ["removed"])
        self.assertEqual([f["id"] for f in rows[0]["fixes"]], ["E1", "E2"])
        self.assertFalse(os.path.exists(rows[0]["path"]))
        self.assertEqual(incidents.summaries(self.home, fixed("E1", "E2")), [])

    def test_unfixed_not_in_the_list_is_kept(self):
        sl = self.two()
        self.assertEqual(incidents.fix_status(self.incident(sl), []), ("unfixed", [], []))
        rows = incidents.prune(self.home, apply=True, fixed=fixed("O1", "E3", "E9"))     # other signatures only
        self.assertEqual([r["action"] for r in rows], ["kept"])
        self.assertTrue(os.path.isdir(rows[0]["path"]))

    def test_recurred_after_every_fix_is_kept_and_marked(self):
        sl = self.two(ids_second=("E1", "E2"))           # VW3's stop on an engine that had both fixes
        inc = self.incident(sl)
        self.assertEqual(incidents.fix_status(inc, fixed("E1", "E2")), ("recurred", ["E1", "E2"], [2]))
        rows = incidents.prune(self.home, apply=True, fixed=fixed("E1", "E2"))
        self.assertEqual((rows[0]["action"], rows[0]["fix_status"], rows[0]["recurred"]), ("kept", "recurred", [2]))
        self.assertTrue(os.path.isdir(rows[0]["path"]))
        s = incidents.summaries(self.home, fixed("E1", "E2"))[0]
        self.assertEqual((s["fix_status"], s["fixes"], s["recurred"]), ("recurred", ["E1", "E2"], [2]))

    def test_an_unreadable_incident_is_listed_and_never_removed(self):
        sl = self.two()
        ip = pathsmod.IncidentPaths(self.home)
        with open(ip.incident_json(sl), "w", encoding="utf-8") as f:
            f.write("{broken")
        rows = incidents.prune(self.home, apply=True, fixed=fixed("E1", "E2"))
        self.assertEqual((rows[0]["action"], "problem" in rows[0]), ("kept", True))
        self.assertTrue(os.path.isdir(ip.incident_dir(sl)))


class Wiring(unittest.TestCase):
    def test_an_engine_error_of_a_real_run_leaves_a_defect_incident(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = W.World(tmp)

            class Boom(W.FakeResults):
                def judge_run(self, step, facts, run_outcome=None):
                    if step.id == "test":
                        raise RuntimeError("boom in the judge")
                    return super().judge_run(step, facts, run_outcome)
            self.assertEqual(w.run(W.units(w, results=Boom())), driver.EXIT_NEEDS_HUMAN)
            self.assertEqual(w.state()["stop"]["reason"], "engine-error")
            rows = incidents.summaries(os.path.realpath(w.engine_home), [])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["kind"], "defect")
            self.assertRegex(rows[0]["signature"], r"^engine-error @ driver\.[A-Za-z_]+$")
            self.assertEqual((rows[0]["last"]["issue"], rows[0]["last"]["step"]), (W.ISSUE, "test"))
            self.assertIn("engine incident recorded", w.out.getvalue())

    def test_a_failing_record_changes_neither_the_stop_nor_the_exit(self):
        class Broken:
            @staticmethod
            def record_stop(*a, **k):
                raise OSError("disk full")
        with tempfile.TemporaryDirectory() as tmp:
            w = W.World(tmp)

            class Boom(W.FakeResults):
                def judge_run(self, step, facts, run_outcome=None):
                    raise RuntimeError("boom")
            self.assertEqual(w.run(W.units(w, results=Boom(), incidents=Broken)), driver.EXIT_NEEDS_HUMAN)
            self.assertEqual(w.state()["stop"]["reason"], "engine-error")
            self.assertIn("engine incident not recorded: OSError: disk full", w.out.getvalue())


class Cli(Home):
    def run_cli(self, *argv):
        out = io.StringIO()
        rc = cli.main(list(argv), environ=self.environ, out=out)
        return rc, out.getvalue()

    def test_list_and_prune(self):
        paths, state = self.put("vw2_1938")
        self.record(paths, state)
        rc, text = self.run_cli("incidents", "list", "--json")
        self.assertEqual(rc, 0)
        rows = json.loads(text)
        self.assertEqual((rows[0]["signature"], rows[0]["kind"], rows[0]["count"]), (SIG_ESCALATE, "suspect", 1))
        self.assertEqual(rows[0]["fix_status"], "fixed")                  # the shipped list has E1 and E2
        rc, text = self.run_cli("incidents", "list")
        self.assertIn("[suspect] escalate:env-problem @ done-gate — 1x · last owner/app_a#1938", text)
        rc, text = self.run_cli("incidents", "prune")
        self.assertIn("would-remove: escalate:env-problem @ done-gate — E1 (1.0.0-exp.3 6757d26)", text)
        self.assertTrue(os.listdir(os.path.join(self.home, "incidents")))
        rc, text = self.run_cli("incidents", "prune", "--apply", "--json")
        self.assertEqual([r["action"] for r in json.loads(text)], ["removed"])
        rc, text = self.run_cli("incidents", "list", "--json")
        self.assertEqual(json.loads(text), [])

    def test_the_shipped_list_validates(self):
        self.assertTrue(incidents.load_fixed())
        with open(incidents.FIXED_DEFECTS_FILE, encoding="utf-8") as f:
            schema.validate(json.load(f), "fixed-defects")


if __name__ == "__main__":
    unittest.main()
