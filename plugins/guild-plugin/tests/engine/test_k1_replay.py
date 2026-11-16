"""K1 — replay harness: the scripted/logging proxy, the permission reclassifier against REAL CLI
decisions (calibration fixture), the calibration extractor helpers, canned result.json extraction."""

import http.client
import http.server
import json
import os
import threading
import unittest

import _k1
from _k1 import tmpdir

from workflows.dev.replay import calibrate as CA
from workflows.dev.replay import extract_results as X
from workflows.dev.replay import permissions_check as PC
from workflows.dev.replay import proxy as PX

CAL = os.path.join(_k1.K1FX, "calibration.json")


def post(url, path, body, stream=False):
    host = url.split("//")[1]
    c = http.client.HTTPConnection(host, timeout=10)
    c.request("POST", path, json.dumps(dict(body, stream=stream)), {"content-type": "application/json",
                                                                    "x-api-key": "secret"})
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read().decode()


def sse_events(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.split("\n") if ": " in l)
        out.append((lines.get("event"), json.loads(lines.get("data", "{}"))))
    return out


class Proxy(unittest.TestCase):
    def serve(self, **kw):
        d = tmpdir(self)
        srv, url = PX.serve_background(logdir=d, **kw)
        self.addCleanup(srv.shutdown)
        return url, d

    def test_scripted_turns_by_assistant_count(self):
        url, d = self.serve(mode="script", script={"turns": [
            {"tool_use": {"name": "Bash", "input": {"command": "ls"}}}, {"text": "fin"}]})
        tools = [{"name": "Bash"}]
        st, _h, body = post(url, "/v1/messages", {"model": "m", "tools": tools, "messages": [{"role": "user", "content": "x"}]}, True)
        ev = sse_events(body)
        self.assertEqual(ev[0][0], "message_start")
        start = [e for n, e in ev if n == "content_block_start"][0]
        self.assertEqual(start["content_block"]["name"], "Bash")
        delta = [e for n, e in ev if n == "content_block_delta"][0]
        self.assertEqual(json.loads(delta["delta"]["partial_json"]), {"command": "ls"})
        self.assertEqual([e for n, e in ev if n == "message_delta"][0]["delta"]["stop_reason"], "tool_use")
        st, _h, body = post(url, "/v1/messages", {"model": "m", "tools": tools, "messages": [
            {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}, {"role": "user", "content": "z"}]})
        self.assertEqual(json.loads(body)["content"][0]["text"], "fin")
        log = [json.loads(l) for l in open(os.path.join(d, "requests.jsonl"))]
        self.assertNotIn("x-api-key", log[0]["headers"])               # credentials never logged

    def test_side_request(self):
        url, _ = self.serve(mode="script", script={"turns": []})
        _s, _h, body = post(url, "/v1/messages", {"model": "m", "messages": []})
        self.assertEqual(json.loads(body)["content"][0]["text"], "ok")

    def test_ratelimit_headers_and_429(self):
        url, _ = self.serve(mode="script", script={"turns": [{"text": "x"}]}, ratelimit=("rejected", 123),
                            status429=1)
        st, h, _b = post(url, "/v1/messages", {"model": "m", "tools": [{"name": "Bash"}], "messages": []})
        self.assertEqual(st, 429)
        self.assertEqual(h.get("anthropic-ratelimit-unified-status"), "rejected")
        st, h, _b = post(url, "/v1/messages", {"model": "m", "tools": [{"name": "Bash"}], "messages": []})
        self.assertEqual((st, h.get("anthropic-ratelimit-unified-reset")), (200, "123"))

    def test_forward_streams_upstream(self):
        class Up(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["content-length"]))
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", "9")
                self.end_headers()
                self.wfile.write(b"data: up\n")
        up = http.server.HTTPServer(("127.0.0.1", 0), Up)
        threading.Thread(target=up.serve_forever, daemon=True).start()
        self.addCleanup(up.shutdown)
        url, _ = self.serve(mode="forward", upstream="http://127.0.0.1:%d" % up.server_address[1])
        st, _h, body = post(url, "/v1/messages", {"model": "m", "tools": [{"name": "Bash"}], "messages": []})
        self.assertEqual((st, body), (200, "data: up\n"))

    def test_forward_refuses_non_loopback(self):
        with self.assertRaises(SystemExit):
            PX.make_server(0, tmpdir(self), mode="forward", upstream="https://api.anthropic.com")


class Reclassifier(unittest.TestCase):
    """The predictor against real CLI 2.1.311 decisions recorded by the K1 calibration."""

    @classmethod
    def setUpClass(cls):
        with open(CAL, encoding="utf-8") as fh:
            cls.fx = json.load(fh)

    def agreement(self, rows):
        ok, miss = 0, []
        for r in rows:
            role = self.fx["roles"][r["role"]]
            v, why = PC.predict(r["command"], role["allow"], role["deny"], cwd=self.fx["cwd"],
                                dirs=[role["run"]], home=self.fx["home"])
            if v == r["outcome"]:
                ok += 1
            else:
                miss.append((r["set"], r["id"], v, r["outcome"], why, r["command"][:80]))
        return ok, miss

    def test_calibration_sets_at_least_98(self):
        for s in ("sample", "heldout", "heldout2"):
            rows = [r for r in self.fx["rows"] if r["set"] == s]
            ok, miss = self.agreement(rows)
            self.assertGreaterEqual(len(rows), 195)
            self.assertGreaterEqual(100.0 * ok / len(rows), 98.0, (s, miss))

    def test_probes(self):
        rows = self.fx.get("probes") or []
        if not rows:
            self.skipTest("probe outcomes not recorded")
        ok, miss = self.agreement(rows)
        self.assertGreaterEqual(100.0 * ok / len(rows), 97.0, miss)

    def test_split_and_tokens(self):
        self.assertEqual(PC.split_commands("ls 2>&1 | tail -3; flutter analyze"), ["ls", "tail -3", "flutter analyze"])
        self.assertEqual(PC.split_commands("cat > /tmp/x <<EOF\nhi; rm -rf\nEOF\necho done"), ["cat", "echo done"])
        self.assertEqual(PC.split_commands('echo "a;b" && grep -n "x|y" f'), ['echo "a;b"', 'grep -n "x|y" f'])
        self.assertEqual(PC.parse_commands("git status > o.txt"), [("git status", True)])
        self.assertEqual(PC.parse_commands("ls >/dev/null 2>&1"), [("ls", False)])

    def test_learned_rules(self):
        allow, deny = ["Bash(echo:*)", "Bash(ls:*)", "Bash(cd:*)", "Bash(cat:*)", "Bash(head:*)",
                       "Bash(python3 -:*)", "Bash(grep:*)", "Bash(sed:*)"], ["Bash(git push:*)"]
        cwd = "/w"
        P = lambda c: PC.predict(c, allow, deny, cwd=cwd, dirs=["/r"], home="/h")[0]
        self.assertEqual(P("echo exit=$?"), "deny")                 # P1
        self.assertEqual(P('echo "rc=$?"'), "allow")
        self.assertEqual(P('echo "$PWD"'), "deny")
        self.assertEqual(P("echo $(ls)"), "deny")
        self.assertEqual(P("X=1 ls"), "deny")                        # P2
        self.assertEqual(P("{ ls; }"), "deny")                       # P3
        self.assertEqual(P("python3 - <<EOF\nx\nEOF"), "deny")       # P4
        self.assertEqual(P("python3 - <<'EOF'\nx\nEOF"), "allow")
        self.assertEqual(P("cd /w; ls"), "allow")                    # P5
        self.assertEqual(P("cd /w; ls | head"), "deny")
        self.assertEqual(P("cd lib && ls"), "deny")
        self.assertEqual(P("cat /etc/hosts"), "deny")                # P6
        self.assertEqual(P("cat /r/in/x"), "allow")
        self.assertEqual(P("grep -n '/usr/bin' f"), "allow")
        self.assertEqual(P("ls > out.txt"), "deny")                  # P7 (no path-scoped Write)
        self.assertEqual(PC.predict("ls > out.txt", allow + ["Write(//w/**)"], deny, cwd=cwd)[0], "allow")
        self.assertEqual(P("git push"), "deny")

    def test_v0_kept_for_the_record(self):
        self.assertEqual(PC.predict_v0("ls; echo x", ["Bash(ls:*)", "Bash(echo:*)"], [])[0], "allow")

    def test_rule_matching(self):
        self.assertTrue(PC.rule_matches("Bash(git push:*)", "git push origin x"))
        self.assertFalse(PC.rule_matches("Bash(git push:*)", "git pushx"))
        self.assertTrue(PC.rule_matches("Bash(gh api * -X *)", "gh api repos/o/r -X POST"))
        self.assertFalse(PC.rule_matches("Bash(gh api * -X *)", "gh api -X POST repos/o/r"))   # the K1 finding
        self.assertTrue(PC.rule_matches("Bash(gh api -X*)", "gh api -X POST repos/o/r"))
        self.assertTrue(PC.rule_matches("Bash(env)", "env"))
        self.assertFalse(PC.rule_matches("Bash(env)", "env -u X"))


class Q23Calibration(unittest.TestCase):
    """The predictor (current rules) against real CLI decisions recorded under Q23, and the
    review-r1 probes: each must be stopped by a rule, the sandbox or the post-role check."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(_k1.K1FX, "calibration-q23.json"), encoding="utf-8") as fh:
            cls.rows = json.load(fh)["rows"]

    def predict(self, r):
        from guildcore.roles import permissions as P
        role, task = PC.engine_role(r["role"]) if r["role"] not in ("reviewer",) else ("reviewer", None)
        a, d = P.role_rules(role, task)
        return PC.predict(r["command"], a, d)[0]

    def test_agreement(self):
        by = {}
        for r in self.rows:
            ok, n = by.get(r["set"], (0, 0))
            by[r["set"]] = (ok + (self.predict(r) == r["outcome"]), n + 1)
        for s_, (ok, n) in by.items():
            self.assertGreaterEqual(100.0 * ok / n, 98.0, (s_, ok, n))

    def test_every_probe_is_stopped(self):
        # the only rows the real run did not stop are git commands that do not exist
        loose = sorted(r["command"] for r in self.rows if r["set"].startswith("r1-")
                       and r["stopped_by"] == "NOT STOPPED")
        self.assertEqual(loose, ["git push-x", "git stash-x"])
        self.assertTrue(all(r["stopped_by"] in ("rule", "sandbox", "post-check", "NOT STOPPED")
                            for r in self.rows if r["set"].startswith("r1-")))


LOG = [
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "A1", "name": "Agent",
                                                   "input": {"description": "developer implement #5"}}]}},
    {"type": "assistant", "parent_tool_use_id": "A1", "message": {"content": [
        {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "flutter test test/a_test.dart"}},
        {"type": "tool_use", "id": "w1", "name": "Write",
         "input": {"file_path": "/Users/x/projects/.gld-app-sprint-9/issue-5/lib/a.dart"}}]}},
    {"type": "assistant", "parent_tool_use_id": "A1", "message": {"content": [
        {"type": "text", "text": "Committed on fix/#5-a. Tests in test/a_test.dart."}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "A1", "content": [
        {"type": "text", "text": "[Subagent hand-back] … The report follows:\n  >>> RESULT <<<\n  DONE: lib/a.dart\nagentId: z"}]}]}},
]


class Extraction(unittest.TestCase):
    def log(self):
        d = tmpdir(self)
        p = os.path.join(d, "issue-5.log")
        with open(p, "w") as fh:
            fh.write("noise line\n" + "\n".join(json.dumps(x) for x in LOG) + "\n")
        return p

    def test_episode(self):
        eps = X.episodes(self.log())
        self.assertEqual(len(eps), 1)
        e = eps[0]
        self.assertEqual(e.role, "developer")
        self.assertIn("DONE: lib/a.dart", e.result_text)
        self.assertNotIn("agentId", e.result_text)
        src = e.source()
        self.assertIn("lib/a.dart", src)
        self.assertNotIn("/Users/x/projects", src)

    def test_verify_and_extract_with_fake_model(self):
        e = X.episodes(self.log())[0]
        good = {"tests": ["test/a_test.dart"], "impl_files": ["lib/a.dart"], "baselines": [],
                "branch": "fix/#5-a", "pr_summary_path": ""}
        row = X.extract(e, lambda role, schema, src: good)
        self.assertTrue(row["verified"])
        self.assertIsNone(row["needs"])
        bad = dict(good, impl_files=["lib/invented.dart"])
        row = X.extract(e, lambda role, schema, src: bad)
        self.assertFalse(row["verified"])
        self.assertEqual((row["needs"], row["not_in_source"]), ("haiku", ["lib/invented.dart"]))
        row = X.extract(e, lambda role, schema, src: {"tests": "x"})
        self.assertTrue(row["schema_errors"])
        def boom(*a):
            raise IOError("down")
        self.assertEqual(X.extract(e, boom)["needs"], "haiku")

    def test_parse_json_text(self):
        self.assertEqual(X.parse_json_text('sure:\n```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(X.parse_json_text('x {"a": 2} y'), {"a": 2})
        self.assertIsNone(X.parse_json_text("no json"))


class CalibrationHelpers(unittest.TestCase):
    def test_rewrite_table(self):
        t = CA.rewrite_table("/C", "/T")
        self.assertEqual(CA.rewrite("cd /Users/j-kim/projects/.gld-word_app-sprint-1508/issue-1487 && cat /tmp/x",
                                    t), "cd /C && cat /T/x")
        self.assertEqual(CA.rewrite("ls /Users/j-kim/projects/word_app/lib", t), "ls /C/lib")

    def test_unsafe_filter(self):
        self.assertTrue(CA.UNSAFE.search("cat /Users/other/x"))
        self.assertTrue(CA.UNSAFE.search("sudo ls"))
        self.assertFalse(CA.UNSAFE.search("cat ~/.pub-cache/x"))

    def test_extract_stratified(self):
        d = tmpdir(self)
        p = os.path.join(d, "s1", "issue-1.log")
        os.makedirs(os.path.dirname(p))
        rows = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "A", "name": "Agent",
                                                               "input": {"description": "qa #1"}}]}}]
        for i, c in enumerate(["ls", "git push", "cat /Users/j-kim/projects/word_app/a", "ls", "x" * 700]):
            rows.append({"type": "assistant", "parent_tool_use_id": "A", "message": {"content": [
                {"type": "tool_use", "id": "b%d" % i, "name": "Bash", "input": {"command": c}}]}})
        with open(p, "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in rows))
        doc = CA.extract(os.path.join(d, "*", "issue-*.log"), d, "/C", "/T", n=10)
        self.assertEqual(doc["sample"], 3)
        self.assertEqual(doc["skipped"], {"duplicate": 1, "too-long": 1})
        self.assertIn("cat /C/a", [c["command"] for c in doc["commands"]])


if __name__ == "__main__":
    unittest.main()
