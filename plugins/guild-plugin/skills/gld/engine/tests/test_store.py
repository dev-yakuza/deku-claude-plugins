"""U2 — state.json / log.jsonl / attempt files (store.py, design §4.3, §7.2-3; scope §5.2 S10, S12)."""

import copy
import json
import os
import shutil
import tempfile
import unittest

from gxengine import codes, fsafe, store
from gxengine import paths as P

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ENGINE, "tests", "fixtures", "contracts")
SHA_A = "a" * 40
SHA_B = "b" * 40


def example(name):
    with open(os.path.join(CONTRACTS, name + ".example.json"), encoding="utf-8") as f:
        return json.load(f)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-store-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.ep = P.EnginePaths(self.home, "acme/app", 42)


class State(Base):
    def test_now_ts_matches_schema_form(self):
        self.assertRegex(store.now_ts(), r"\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")
        self.assertEqual(store.now_ts(0), "1970-01-01T00:00:00Z")

    def test_new_state(self):
        st = store.new_state(42, 1, ["analyze", "plan"], SHA_A, base_sha=SHA_A, repo="acme/app")
        self.assertEqual(st["format"], 1)
        self.assertEqual(st["steps"], [{"id": "analyze", "status": "pending", "latest_attempt": None},
                                       {"id": "plan", "status": "pending", "latest_attempt": None}])
        self.assertEqual((st["last_head"], st["base_sha"]), (SHA_A, SHA_A))

    def test_new_state_refusals(self):
        with self.assertRaises(ValueError):
            store.new_state(42, 1, ["a", "a"], SHA_A)
        with self.assertRaises(ValueError):
            store.new_state(42, 1, [], SHA_A)
        with self.assertRaises(ValueError):
            store.new_state(42, 1, ["a"], SHA_A, steps=[])
        with self.assertRaises(store.CorruptFile):
            store.new_state(42, 1, ["a"], "main")              # a ref name is not a SHA (S5)
        with self.assertRaises(store.CorruptFile):
            store.new_state(42, 1, ["a"], SHA_A, typo_field=1)  # additionalProperties false

    def test_roundtrip_example(self):
        st = example("state")
        self.assertIsNone(store.load_state(self.ep))
        store.save_state(self.ep, st)
        self.assertEqual(store.load_state(self.ep), st)
        self.assertTrue(os.path.isfile(os.path.join(self.home, "records/acme/app/42/state.json")))

    def test_save_refuses_invalid_and_keeps_old_file(self):
        st = example("state")
        store.save_state(self.ep, st)
        bad = copy.deepcopy(st)
        bad["steps"][0]["status"] = "almost-done"
        with self.assertRaises(store.CorruptFile):
            store.save_state(self.ep, bad)
        self.assertEqual(store.load_state(self.ep), st)
        other = copy.deepcopy(st)
        other["issue"] = 43
        with self.assertRaises(ValueError):
            store.save_state(self.ep, other)
        dup = copy.deepcopy(st)
        dup["steps"][1]["id"] = "analyze"
        with self.assertRaises(ValueError):
            store.save_state(self.ep, dup)

    def test_enum_members_are_stored_as_strings(self):
        st = store.new_state(42, 1, ["a"], SHA_A)
        st["steps"][0]["status"] = codes.StepStatus.RUNNING
        store.save_state(self.ep, st)
        with open(self.ep.state) as f:
            self.assertIn('"status": "running"', f.read())

    def test_corrupt_files(self):
        os.makedirs(self.ep.issue_dir)
        cases = {
            "not json": "{",
            "duplicate key": '{"format": 1, "format": 1}',
            "nan": '{"format": NaN}',
            "not an object": "[]",
        }
        for why, text in cases.items():
            with self.subTest(why=why):
                with open(self.ep.state, "w") as f:
                    f.write(text)
                with self.assertRaises((store.CorruptFile, store.FormatMismatch)):
                    store.load_state(self.ep)
        st = example("state")
        st["issue"] = 43
        with open(self.ep.state, "w") as f:
            json.dump(st, f)
        with self.assertRaises(store.CorruptFile):
            store.load_state(self.ep)

    def test_s10_format_mismatch(self):
        os.makedirs(self.ep.issue_dir)
        for fmt in (2, 0, None, "1", True):
            st = example("state")
            st["format"] = fmt
            with open(self.ep.state, "w") as f:
                json.dump(st, f)
            with self.subTest(fmt=fmt):
                with self.assertRaises(store.FormatMismatch):
                    store.load_state(self.ep)
        st = example("state")
        del st["format"]
        with open(self.ep.state, "w") as f:
            json.dump(st, f)
        with self.assertRaises(store.FormatMismatch):
            store.load_state(self.ep)

    def test_converter_is_applied(self):
        os.makedirs(self.ep.issue_dir)
        old = example("state")
        old["format"] = 0
        old["head"] = old.pop("last_head")          # pretend format 0 named the field `head`

        def conv(o):
            o = dict(o)
            o["last_head"] = o.pop("head")
            o["format"] = 1
            return o
        store.CONVERTERS[("state", 0)] = conv
        self.addCleanup(store.CONVERTERS.pop, ("state", 0))
        with open(self.ep.state, "w") as f:
            json.dump(old, f)
        self.assertEqual(store.load_state(self.ep), example("state"))

    def test_converter_loop_refused(self):
        store.CONVERTERS[("state", 5)] = lambda o: dict(o, format=5)
        self.addCleanup(store.CONVERTERS.pop, ("state", 5))
        with self.assertRaises(store.FormatMismatch):
            store.convert("state", {"format": 5})

    def test_s12_link_in_records_refused(self):
        os.makedirs(os.path.join(self.home, "records", "acme"))
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        os.symlink(elsewhere, os.path.join(self.home, "records", "acme", "app"))
        with self.assertRaises(fsafe.UnsafePath):
            store.save_state(self.ep, example("state"))
        with self.assertRaises(fsafe.UnsafePath):
            store.load_state(self.ep)
        with self.assertRaises(fsafe.UnsafePath):
            store.append_log(self.ep, "engine-start")
        self.assertEqual(os.listdir(elsewhere), [])

    def test_state_json_link_refused(self):
        os.makedirs(self.ep.issue_dir)
        target = os.path.join(self.tmp, "victim.json")
        with open(target, "w") as f:
            json.dump(example("state"), f)
        os.symlink(target, self.ep.state)
        with self.assertRaises(fsafe.UnsafePath):
            store.load_state(self.ep)
        with self.assertRaises(fsafe.UnsafePath):
            store.save_state(self.ep, example("state"))

    def test_engine_home_link_refused(self):
        real = os.path.join(self.tmp, "real")
        os.makedirs(real)
        os.symlink(real, self.home)
        with self.assertRaises(fsafe.UnsafePath):
            store.save_state(self.ep, example("state"))


class Log(Base):
    def test_append_and_read(self):
        a = store.append_log(self.ep, codes.LogEvent.ENGINE_START)
        b = store.append_log(self.ep, "status", step="test", attempt=2, code="check-failed",
                             detail="run-nonzero", note="exit 1", data={"exit_code": 1},
                             **{"from": "running", "to": "failed"})
        c = store.append_log(self.ep, "request", who="role:developer", trigger="ui-change", note="n")
        lines = list(store.read_log(self.ep))
        self.assertEqual(lines, [a, b, c])
        self.assertEqual(a["event"], "engine-start")
        self.assertEqual((b["from"], b["to"]), ("running", "failed"))
        with open(self.ep.log, encoding="utf-8") as f:
            raw = f.read()
        self.assertEqual(raw.count("\n"), 3)
        for line in raw.splitlines():
            json.loads(line)

    def test_none_fields_dropped(self):
        line = store.append_log(self.ep, "engine-exit", step=None, code=None)
        self.assertNotIn("step", line)
        self.assertNotIn("code", line)

    def test_invalid_lines_refused(self):
        for kw in ({"event": "made-up"}, {"event": "status", "to": "almost"},
                   {"event": "stop", "who": "robot"}, {"event": "status", "trigger": "because"},
                   {"event": "status", "mystery": 1}, {"event": "status", "issue": 9}):
            with self.subTest(kw=kw):
                kw = dict(kw)
                ev = kw.pop("event")
                with self.assertRaises((store.CorruptFile, ValueError, TypeError)):
                    store.append_log(self.ep, ev, **kw)
        self.assertFalse(os.path.exists(self.ep.log))

    def test_newline_in_note_stays_one_line(self):
        store.append_log(self.ep, "warning", note="a\nb")
        with open(self.ep.log) as f:
            self.assertEqual(f.read().count("\n"), 1)
        self.assertEqual(next(store.read_log(self.ep))["note"], "a\nb")

    def test_read_empty_and_broken(self):
        self.assertEqual(list(store.read_log(self.ep)), [])
        store.append_log(self.ep, "engine-start")
        with open(self.ep.log, "a") as f:
            f.write('{"format":1')
        with self.assertRaises(store.CorruptFile):
            list(store.read_log(self.ep))

    def test_log_example_and_u19_fields(self):
        ex = example("log-line")
        fields = {k: v for k, v in ex.items() if k not in ("format", "ts", "issue", "who", "event")}
        line = store.append_log(self.ep, ex["event"], who=ex["who"], ts=ex["ts"], **fields)
        self.assertEqual(line, ex)
        stop = store.append_log(self.ep, "stop", step="test", to="needs_human", code="on-fail-exceeded")
        self.assertEqual((stop["to"], stop["code"]), ("needs_human", "on-fail-exceeded"))


class Attempts(Base):
    def setUp(self):
        super().setUp()
        self.state = store.new_state(42, 1, ["analyze", "test"], SHA_A)

    def test_new_attempt_numbers_and_dirs(self):
        n1 = store.new_attempt(self.ep, self.state, "test")
        n2 = store.new_attempt(self.ep, self.state, "test")
        self.assertEqual((n1, n2), (1, 2))
        self.assertEqual(self.state["steps"][1]["latest_attempt"], 2)
        self.assertTrue(os.path.isdir(self.ep.in_dir("test", 2)))
        self.assertFalse(os.path.exists(self.ep.state), "new_attempt does not save state")

    def test_leftover_folder_is_skipped_not_reused(self):
        os.makedirs(self.ep.attempt_dir("test", 1))
        with open(os.path.join(self.ep.attempt_dir("test", 1), "stream.jsonl"), "w") as f:
            f.write("old")
        n = store.new_attempt(self.ep, self.state, "test")
        self.assertEqual(n, 2)
        with open(os.path.join(self.ep.attempt_dir("test", 1), "stream.jsonl")) as f:
            self.assertEqual(f.read(), "old")

    def test_link_attempt_folder_not_followed(self):
        os.makedirs(self.ep.step_dir("test"))
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        os.symlink(elsewhere, self.ep.attempt_dir("test", 1))
        n = store.new_attempt(self.ep, self.state, "test")
        self.assertEqual(n, 2)
        self.assertEqual(os.listdir(elsewhere), [])

    def test_unknown_step(self):
        with self.assertRaises(KeyError):
            store.new_attempt(self.ep, self.state, "nope")

    def test_brief_and_facts(self):
        brief, facts = example("brief"), example("facts")
        step, att = facts["step"], facts["attempt"]
        st = store.new_state(42, 1, [step], SHA_A)
        self.assertEqual(store.new_attempt(self.ep, st, step), att)
        store.write_facts(self.ep, step, att, facts)
        self.assertEqual(store.read_facts(self.ep, step, att), facts)
        bstep, batt = brief["step"], brief["attempt"]
        p = store.write_brief(self.ep, bstep, batt, brief)
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f), brief)

    def test_brief_facts_refusals(self):
        facts = example("facts")
        step, att = facts["step"], facts["attempt"]
        with self.assertRaises(ValueError):
            store.write_facts(self.ep, step, att + 1, facts)       # attempt mismatch
        bad = copy.deepcopy(facts)
        del bad["exit_code"]                                         # a judgment fact (§9.3)
        with self.assertRaises(store.CorruptFile):
            store.write_facts(self.ep, step, att, bad)
        with self.assertRaises(store.CorruptFile):
            store.write_brief(self.ep, "x", 1, {"format": 1})

    def test_result_as_received(self):
        store.write_result(self.ep, "review", 1, {"status": "done", "anything": [1]})
        with open(self.ep.attempt_file("review", 1, "result.json")) as f:
            self.assertEqual(json.load(f), {"status": "done", "anything": [1]})
        store.write_result(self.ep, "review", 2, '{"not": "validated"')
        with open(self.ep.attempt_file("review", 2, "result.json")) as f:
            self.assertEqual(f.read(), '{"not": "validated"')

    def test_result_with_a_lone_surrogate_is_recorded_as_escapes(self):
        """review-q0 D9 (Q8): nothing is replaced, nothing crashes; role and leader share the function."""
        bad = {"note": "a \ud83d b", "bad \ud800 key": ["\udfff"], "ok": "é"}
        for path in (store.write_result(self.ep, "review", 3, bad), store.write_leader_result(self.ep, 1, bad)):
            with open(path, "rb") as f:
                raw = f.read()
            self.assertIn(b"\\ud83d", raw)
            self.assertEqual(json.loads(raw.decode("ascii")), bad)
        path = store.write_result(self.ep, "review", 4, json.dumps(bad, ensure_ascii=False))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), bad)
        path = store.write_result(self.ep, "review", 5, {"ok": "é \U0001f600"})     # valid text stays UTF-8
        with open(path, encoding="utf-8") as f:
            self.assertIn("é \U0001f600", f.read())

    def test_in_file_keeps_a_non_utf8_byte_of_the_review_diff(self):
        text = b"+caf\xe9\n".decode("utf-8", "surrogateescape")
        p = store.write_in_file(self.ep, "review-design", 1, codes.InFile.REVIEW_DIFF, text)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"+caf\xe9\n")

    def test_leader_in_file_keeps_a_non_utf8_byte_too(self):
        # Q4: a needs_leader call's in/ files take the same byte round trip (P5 #1797)
        text = b"Issue caf\xe9\n".decode("utf-8", "surrogateescape")
        p = store.write_leader_in_file(self.ep, 1, codes.InFile.ISSUE.value, text)
        self.assertEqual(p, os.path.join(self.ep.leader_in_dir(1), "issue.md"))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"Issue caf\xe9\n")

    def test_in_files(self):
        p = store.write_in_file(self.ep, "analyze", 1, codes.InFile.ISSUE, "# Issue\n")
        self.assertEqual(p, os.path.join(self.ep.in_dir("analyze", 1), "issue.md"))
        for bad in ("state.json", "../x", "issue.md/../../state.json", "notes.md"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    store.write_in_file(self.ep, "analyze", 1, bad, "x")


class CoreFields(unittest.TestCase):
    def test_core_fields_are_required_in_example(self):
        st = example("state")
        for k in store.STATE_CORE_FIELDS:
            self.assertIn(k, st)
        for s in st["steps"]:
            for k in store.STATE_STEP_CORE_FIELDS:
                self.assertIn(k, s)

    def test_no_converters_in_format_1(self):
        self.assertEqual(store.CONVERTERS, {})


if __name__ == "__main__":
    unittest.main()
