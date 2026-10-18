"""Usage limits in batch children (design/herald/05-batch-rate-limit.md): the log verdict, and the
runner's hold → wait → resume → release within one run, its ceilings and its lock checks."""

import datetime
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from helpers import HERE, SCRIPTS, sh
import test_batch

from hrdlib import lock, ratelimit, store

NOW = 1_800_000_000  # a fixed "now" for verdicts


def log(*objs, raw=()):
    fd, p = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for o in objs:
            f.write((o if isinstance(o, str) else json.dumps(o)) + "\n")
        for r in raw:
            f.write(r + "\n")
    return p


def ev(status, reset=None, **extra):
    info = {"status": status}
    if reset is not None:
        info["resetsAt"] = reset
    info.update(extra)
    return {"type": "rate_limit_event", "rate_limit_info": info}


def result(text, error=False):
    return {"type": "result", "subtype": "error_during_execution" if error else "success", "is_error": error,
            "result": text}


def assistant(tokens=10):
    return {"type": "assistant", "message": {"usage": {"input_tokens": tokens, "output_tokens": tokens}}}


def scan(*objs, rc=0, raw=()):
    return ratelimit.scan(log(*objs, raw=raw), rc, NOW)


class ScanTests(unittest.TestCase):
    def test_last_event_decides(self):
        self.assertTrue(scan(ev("allowed"), ev("rejected", NOW + 3600))["limited"])
        self.assertFalse(scan(ev("rejected", NOW + 3600), ev("allowed"))["limited"])
        self.assertFalse(scan(ev("allowed_warning", NOW + 3600))["limited"])
        v = scan(ev("rejected", NOW + 3600))
        self.assertEqual((v["source"], v["reset_at"], v["kind"]), ("event", NOW + 3600, "limit"))

    def test_odd_statuses_are_limits(self):
        for st in (429, None, True, "rate limited"):
            self.assertTrue(scan({"type": "rate_limit_event", "rate_limit_info": {"status": st}})["limited"], st)

    def test_calls_after_the_event_or_overage_are_not(self):
        self.assertFalse(scan(ev("rejected", NOW + 3600), assistant())["limited"])
        self.assertTrue(scan(ev("rejected", NOW + 3600), assistant(0))["limited"])
        self.assertFalse(scan(ev("rejected", NOW + 3600, overageStatus="allowed"))["limited"])
        self.assertFalse(scan(ev("rejected", NOW + 3600, isUsingOverage=True))["limited"])

    def test_rc0_success_result_carrying_the_limit(self):  # Guild L1: a limited session can exit 0
        v = scan(ev("rejected"), result("Claude AI usage limit reached|%d" % (NOW + 7200)), rc=0)
        self.assertTrue(v["limited"])
        v = scan(result("Claude AI usage limit reached|%d" % (NOW + 7200)), rc=0)
        self.assertEqual((v["limited"], v["source"], v["reset_at"]), (True, "text", NOW + 7200))

    def test_glued_stderr_and_two_objects(self):
        glued = "\rspinner..." + json.dumps(ev("rejected", NOW + 60))
        self.assertTrue(scan(raw=[glued])["limited"])
        two = json.dumps(ev("allowed")) + json.dumps(ev("rejected", NOW + 60))
        self.assertTrue(scan(raw=[two])["limited"])

    def test_lost_event(self):
        cut = json.dumps(ev("rejected", NOW + 60))[:-12]
        self.assertTrue(scan(ev("allowed"), raw=[cut])["limited"])
        self.assertEqual(scan(ev("allowed"), raw=[cut])["source"], "lost-event")
        # a damaged line BEFORE the last decoded event is history, not the verdict
        self.assertFalse(scan(raw=[cut, json.dumps(ev("allowed"))])["limited"])
        self.assertFalse(scan(raw=['KeyError: "rate_limit_info"'], rc=1)["limited"])

    def test_wording_sources(self):
        self.assertTrue(scan(result("You've hit your limit · resets 3pm", error=True), rc=1)["limited"])
        self.assertTrue(scan(raw=["Error: 429 Too Many Requests"], rc=1)["limited"])
        self.assertFalse(scan(raw=["Error: 429 Too Many Requests"], rc=0)["limited"])  # stderr needs rc≠0
        # prose in a normal result is not a limit; strong wording is
        self.assertFalse(scan(result("I added a note about the API rate limit to the article."))["limited"])
        self.assertTrue(scan(result("5-hour limit reached"))["limited"])
        # not usage limits
        for t in ("Context limit reached", "Connection reset by peer", "API Error: 500 Internal server error",
                  "output token limit exceeded"):
            self.assertFalse(scan(result(t, error=True), rc=1)["limited"], t)

    def test_review2_edges(self):
        # the latest error names the reset time
        v = scan({"type": "assistant", "isApiErrorMessage": True, "error": "API Error: 429 rate limit"},
                 result("5-hour limit reached ∙ resets in 3 hours", error=True), rc=1)
        self.assertEqual(v["reset_at"], NOW + 3 * 3600)
        self.assertFalse(scan(result("| 9012345678 | ok |"))["limited"])  # a table cell is not |<epoch>
        self.assertTrue(scan({"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit"}, rc=1)["limited"])
        self.assertTrue(scan({"type": "assistant", "isApiErrorMessage": True, "error": {"type": "rate_limit"}},
                             rc=1)["limited"])
        self.assertTrue(scan(raw=["429"], rc=1)["limited"])
        self.assertIsNone(ratelimit.extract_reset("resets in 1" + "0" * 400 + " hours", NOW))

    def test_glued_stderr_prefix_and_odd_values(self):
        line = "429 Too Many Requests" + json.dumps(result("x", error=True))
        self.assertTrue(scan(raw=[line], rc=1)["limited"])
        self.assertFalse(scan(raw=[line], rc=0)["limited"])  # stderr counts only when the child failed
        v = scan(raw=['{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":Infinity}}'])
        self.assertEqual((v["limited"], v["reset_at"]), (True, None))
        self.assertFalse(scan(result("max output tokens limit reached", error=True), rc=1)["limited"])
        self.assertFalse(scan(result("context limit reached"))["limited"])

    def test_overloaded(self):
        v = scan(result("API Error: 529 Overloaded", error=True), rc=1)
        self.assertEqual((v["limited"], v["kind"]), (True, "overloaded"))

    def test_sanitize(self):
        self.assertEqual(ratelimit.sanitize(NOW + 60, NOW), NOW + 60)
        self.assertEqual(ratelimit.sanitize((NOW + 60) * 1000, NOW), NOW + 60)
        self.assertEqual(ratelimit.sanitize(str(NOW + 60), NOW), NOW + 60)
        iso = datetime.datetime.fromtimestamp(NOW + 60, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        self.assertEqual(ratelimit.sanitize(iso, NOW), NOW + 60)
        for bad in (True, "soon", None, NOW + 40 * 86400, 10 ** 25, float("nan")):
            self.assertIsNone(ratelimit.sanitize(bad, NOW), bad)

    def test_extract_reset(self):
        e = ratelimit.extract_reset
        self.assertEqual(e("resets in 2 hours", NOW), NOW + 7200)
        tokyo = e("5-hour limit reached ∙ resets 3pm (Asia/Tokyo)", NOW)
        self.assertTrue(NOW - 7200 <= tokyo <= NOW + 22 * 3600)
        self.assertEqual(datetime.datetime.fromtimestamp(tokyo, __import__("zoneinfo").ZoneInfo("Asia/Tokyo")).hour, 15)
        thu = e("resets Thu 5pm (UTC)", NOW)
        d = datetime.datetime.fromtimestamp(thu, datetime.timezone.utc)
        self.assertEqual((d.weekday(), d.hour), (3, 17))
        self.assertEqual(e("Weekly limit reached · resets 3pm", NOW), ratelimit.FAR)
        self.assertEqual(e("weekly usage limit reached", NOW), ratelimit.FAR)
        self.assertIsNone(e("nothing here", NOW))

    def test_passed_reset(self):
        just = datetime.datetime.fromtimestamp(NOW - 60, datetime.timezone.utc)
        text = "usage limit reached · resets %d:%02d%s (UTC)" % ((just.hour % 12) or 12, just.minute,
                                                                "pm" if just.hour >= 12 else "am")
        v = scan(result(text, error=True), rc=0)
        self.assertFalse(v["limited"])
        self.assertTrue(v["demoted"])
        self.assertTrue(scan(result(text, error=True), rc=1)["limited"])  # rc≠0: still a live limit


class RunnerCase(test_batch.BatchCase):
    """BatchCase's fixture without BatchCase's own tests (they run in test_batch)."""

    def setUp(self):
        super().setUp()
        self.calls = os.path.join(self.tmp, "calls.jsonl")

    def run_batch(self, plan, n=3, extra=(), env=None, background=False, reset=None):
        with open(self.plan, "w") as f:
            json.dump(plan, f)
        e = dict(os.environ, HRD_CLAUDE=os.path.join(HERE, "fake_claude.py"), HRD_FAKE_CLAUDE_PLAN=self.plan,
                 HRD_SCRIPTS=SCRIPTS, HRD_FAKE_CALLS=self.calls, HRD_BATCH_TEST_CLOCK=str(NOW))
        if reset is not None:
            e["HRD_FAKE_RESET_AT"] = str(reset)
        e.update(env or {})
        cmd = [sys.executable, os.path.join(SCRIPTS, "batch_runner.py"), "--n", str(n), *extra]
        if background:
            return subprocess.Popen(cmd, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    env=e, stdin=subprocess.DEVNULL)
        return subprocess.run(cmd, cwd=self.root, capture_output=True, text=True, env=e, timeout=900,
                              stdin=subprocess.DEVNULL)

    def summary(self, p):
        return json.loads(p.stdout[p.stdout.index("{"):])

    def call_log(self):
        return [json.loads(x) for x in open(self.calls)] if os.path.exists(self.calls) else []

    def topic(self, tid):
        return store.get_topic(store.load_topics(self.root), tid)

    def origin_log(self):
        return sh(self.root, "git", "log", "--format=%s", "origin/main")


for _name in [n for n in dir(test_batch.BatchCase) if n.startswith("test_")]:
    setattr(RunnerCase, _name, None)


class LimitRunTests(RunnerCase):
    def test_limit_holds_waits_resumes_and_releases(self):
        p = self.run_batch({"t0001": ["branch-limit", "pr"]}, n=1, reset=NOW + 3600)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        s = self.summary(p)
        self.assertEqual([t for t, _ in s["pr"]], ["t0001"])
        self.assertEqual(s["rate_limit_waits"][0]["kind"], "limit")
        calls = self.call_log()
        self.assertEqual([c["prompt"] for c in calls], ["/hrd write t0001", "/hrd resume t0001"])
        run_id = calls[1]["resume_limited"]
        self.assertTrue(run_id)
        self.assertIsNone(calls[0]["resume_limited"])
        self.assertTrue(all(c["clock"] is None for c in calls))  # the test clock never reaches a child
        self.assertEqual(calls[1]["branch"], "main")  # WIP preserved, child starts on base
        hist = self.topic("t0001")["history"]
        self.assertTrue(hist[-2]["note"].startswith("tooling: rate limited until") and "(run %s)" % run_id in hist[-2]["note"])
        self.assertEqual((self.topic("t0001")["state"], hist[-1]["note"]), ("queued", "resumed to PR after a usage limit"))
        origin = self.origin_log()
        self.assertIn("batch hold t0001 (needs-human)", origin)  # pushed before the wait
        self.assertIn("batch release t0001", origin)
        self.assertIn("wip(herald)", sh(self.root, "git", "log", "--format=%s", "herald/t0001--post-t0001"))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude/herald/signals.jsonl")))  # tooling: no signal
        logs = sorted(os.listdir(os.path.join(self.root, ".claude/herald/memory/batch-logs")))
        self.assertEqual([x for x in logs if x.endswith("-t0001-1.jsonl") or x.endswith("-t0001-2.jsonl")].__len__(), 2)

    def test_limit_before_branch_restarts_write(self):
        p = self.run_batch({"t0001": ["limit-exit0", "pr"]}, n=1)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual([c["prompt"] for c in self.call_log()], ["/hrd write t0001", "/hrd write t0001"])
        self.assertNotIn("batch hold", self.origin_log())  # no branch: stays queued, no hold

    def test_tr_topic_resumes_through_translate(self):
        data = store.load_topics(self.root)
        data["topics"] = [{"id": "tr-a-20261018", "title": "T", "state": "queued", "history": [], "reverted_by": []}]
        store.save_topics(self.root, data)
        self.commit("tr"); sh(self.root, "git", "push", "-q", "origin", "main")
        self.run_batch({"tr-a-20261018": ["limit-exit1", "pr"]}, n=1)
        self.assertEqual([c["prompt"] for c in self.call_log()],
                         ["/hrd translate --resume tr-a-20261018", "/hrd translate --resume tr-a-20261018"])

    def test_pr_beats_a_limit_event(self):
        p = self.run_batch({"t0001": "pr-with-limit"}, n=1)
        self.assertEqual(len(self.call_log()), 1)
        self.assertEqual([t for t, _ in self.summary(p)["pr"]], ["t0001"])

    def test_pr_without_result_after_restart(self):
        p = self.run_batch({"t0001": ["branch-h9", "pr-nores"]}, n=1)
        s = self.summary(p)
        self.assertEqual([t for t, _ in s["pr"]], ["t0001"], p.stderr)
        self.assertEqual(self.topic("t0001")["state"], "queued")

    def test_subagent_limit_waits_without_a_signal(self):
        p = self.run_batch({"t0001": ["branch-h9", "pr"]}, n=1)
        self.assertEqual([t for t, _ in self.summary(p)["pr"]], ["t0001"], p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude/herald/signals.jsonl")))

    def test_far_reset_stops_without_sleeping(self):
        p = self.run_batch({"t0001": "branch-limit-far", "t0002": "pr"}, n=2)
        self.assertEqual(p.returncode, 0, p.stderr)
        s = self.summary(p)
        self.assertEqual((s["rate_limited"]["topic"], s["rate_limited"]["until"]), ("t0001", "far"))
        self.assertEqual(len(self.call_log()), 1)  # t0002 never ran
        self.assertEqual(self.topic("t0001")["state"], "held")
        self.assertIsNone(lock.status(self.root))
        self.assertEqual(sh(self.root, "git", "rev-parse", "--abbrev-ref", "HEAD").strip(), "main")

    def test_reset_beyond_five_hours_stops(self):
        p = self.run_batch({"t0001": "branch-limit"}, n=1, reset=NOW + 6 * 3600)
        self.assertEqual(self.summary(p)["rate_limited"]["why"], "reset beyond 5h")
        self.assertEqual(len(self.call_log()), 1)

    def test_seventh_wait_stops_and_one_hold_per_run(self):
        p = self.run_batch({"t0001": "branch-limit-unknown"}, n=1)
        s = self.summary(p)
        self.assertEqual(s["rate_limited"]["why"], "too many waits", p.stderr)
        self.assertEqual(len([w for w in s["rate_limit_waits"] if w["topic"] == "t0001"]), 6)
        self.assertEqual(self.origin_log().count("batch hold t0001"), 1)
        resumed = [c["resume_limited"] for c in self.call_log()[1:]]
        self.assertTrue(resumed and all(resumed))

    def test_overloaded_three_times_then_incomplete(self):
        p = self.run_batch({"t0001": "overloaded"}, n=1)
        s = self.summary(p)
        self.assertEqual(s["incomplete"], ["t0001"], p.stderr)
        self.assertEqual(len([w for w in s["rate_limit_waits"] if w["kind"] == "overloaded"]), 3)
        self.assertEqual(len(self.call_log()), 5)  # first + 3 backoffs + the one retry

    def test_budget_over_on_a_limited_attempt(self):
        # run_once reports "budget" whenever the attempt ended over budget, so the limit branch's own
        # budget guard is defensive; this pins the observable rule: no sleep, a budget hold
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp)); cfg["budget"] = {"per_article_usd": 0.0000001}
        json.dump(cfg, open(cfgp, "w"))
        self.commit("budget"); sh(self.root, "git", "push", "-q", "origin", "main")
        # a child that spends (usage) and then hits the limit: held for the budget, never put to sleep
        p = self.run_batch({"t0001": ["branch-limit", "pr"]}, n=1, env={"HRD_FAKE_SPEND": "1"})
        self.assertEqual(p.returncode, 0, p.stderr)
        s = self.summary(p)
        self.assertEqual(s["held"], [["t0001", "budget"]])
        self.assertNotIn("rate_limit_waits", s)
        self.assertEqual(len(self.call_log()), 1)


class MoreRunTests(RunnerCase):
    def other_clone(self):
        other = os.path.join(self.tmp, "other")
        sh(self.tmp, "git", "clone", "-q", self.origin, other)
        sh(other, "git", "config", "user.email", "o@x"); sh(other, "git", "config", "user.name", "o")
        return other

    def test_overloaded_on_a_branch_restarts(self):
        p = self.run_batch({"t0001": ["branch-overloaded", "pr"]}, n=1)
        self.assertEqual([t for t, _ in self.summary(p)["pr"]], ["t0001"], p.stderr)
        self.assertEqual([c["prompt"] for c in self.call_log()], ["/hrd write t0001", "/hrd resume t0001"])
        self.assertNotIn("batch hold", self.origin_log())  # a short backoff records no hold

    def test_past_reset_in_a_subagent_note_waits_30s(self):
        p = self.run_batch({"t0001": ["branch-h9-past", "pr"]}, n=1, env={"HRD_FAKE_PAST": str(NOW - 100)})
        self.assertEqual(self.summary(p)["rate_limit_waits"][0]["waited_s"], 30, p.stderr)

    def test_passed_reset_then_limit_again_backs_off(self):
        p = self.run_batch({"t0001": ["limit-exit0", "limit-exit0", "pr"]}, n=1, reset=NOW - 100)
        s = self.summary(p)
        self.assertEqual([t for t, _ in s["pr"]], ["t0001"], p.stderr)
        self.assertEqual([w["until"] for w in s["rate_limit_waits"]], ["unknown"])

    def test_run_wait_ceiling(self):
        unk = "branch-limit-unknown"
        p = self.run_batch({"t0001": [unk] * 5 + ["pr"], "t0002": [unk] * 5 + ["pr"], "t0003": [unk, unk, "pr"]}, n=3)
        s = self.summary(p)
        self.assertEqual((s["rate_limited"]["topic"], s["rate_limited"]["why"]), ("t0003", "12h of waiting in this run"),
                         p.stderr)
        self.assertEqual(sorted(t for t, _ in s["pr"]), ["t0001", "t0002"])

    def test_old_reverted_pr_is_not_a_release(self):
        self.set_prs([{"number": 7, "state": "MERGED", "headRefName": "herald/t0001--post-t0001",
                       "mergedAt": "2020-01-01T00:00:00Z", "labels": ["herald", "herald:reverted"]}])
        p = self.run_batch({"t0001": ["branch-limit", "branch-nothing", "branch-nothing"]}, n=1)
        self.assertNotIn("batch release", self.origin_log(), p.stderr)
        self.assertEqual(self.summary(p)["incomplete"], ["t0001"])

    def test_requeued_elsewhere_during_the_wait_is_skipped(self):
        other = self.other_clone()
        proc = self.run_batch({"t0001": ["branch-limit", "pr"], "t0002": "pr"}, n=2, reset=NOW + 4 * 3600,
                              background=True)
        waitf = os.path.join(self.root, ".claude/herald/memory/lock.wait")
        end = time.time() + 120
        while not os.path.exists(waitf) and time.time() < end:
            time.sleep(0.05)
        sh(other, "git", "pull", "-q")
        data = json.load(open(os.path.join(other, ".claude/herald/topics.json")))
        store.set_topic_state([t for t in data["topics"] if t["id"] == "t0001"][0], "queued", note="requeued elsewhere")
        json.dump(data, open(os.path.join(other, ".claude/herald/topics.json"), "w"))
        sh(other, "git", "commit", "-qam", "requeue"); sh(other, "git", "push", "-q")
        out, err = proc.communicate(timeout=300)
        s = json.loads(out[out.index("{"):])
        self.assertEqual([x["topic"] for x in s["skipped"]], ["t0001"], err)
        self.assertIn("local branch", s["skipped"][0]["why"])
        self.assertEqual([c["prompt"] for c in self.call_log()], ["/hrd write t0001", "/hrd write t0002"])

    def test_version_changed_during_the_wait_stops_with_the_hold(self):
        other = self.other_clone()
        proc = self.run_batch({"t0001": ["branch-limit", "pr"]}, n=1, reset=NOW + 4 * 3600, background=True)
        waitf = os.path.join(self.root, ".claude/herald/memory/lock.wait")
        end = time.time() + 120
        while not os.path.exists(waitf) and time.time() < end:
            time.sleep(0.05)
        sh(other, "git", "pull", "-q")
        hp = os.path.join(other, ".claude/herald/scripts/hrd.py")
        src = open(hp).read()
        import re
        open(hp, "w").write(re.sub(r'SCRIPTS_VERSION = "[^"]+"', 'SCRIPTS_VERSION = "99.0.0"', src))
        sh(other, "git", "commit", "-qam", "update"); sh(other, "git", "push", "-q")
        out, err = proc.communicate(timeout=300)
        self.assertIn("99.0.0", json.loads(out[out.index("{"):])["error"], err)
        self.assertEqual(self.topic("t0001")["state"], "held")
        self.assertEqual(len(self.call_log()), 1)

    def test_release_refused_when_changed_elsewhere(self):
        os.environ["HRD_FAKE_OTHER_CLONE"] = self.other_clone()
        try:
            p = self.run_batch({"t0001": ["branch-limit", "pr-and-requeue-elsewhere"]}, n=1)
        finally:
            os.environ.pop("HRD_FAKE_OTHER_CLONE", None)
        s = self.summary(p)
        self.assertEqual(s.get("not_released"), ["t0001"], p.stderr)
        self.assertNotIn("batch release", self.origin_log())

    def test_next_batch_leaves_the_hold_alone(self):
        self.run_batch({"t0001": "branch-limit-far"}, n=1)
        os.remove(self.calls)
        self.run_batch({"t0001": "pr", "t0002": "pr"}, n=1)
        self.assertEqual([c["prompt"] for c in self.call_log()], ["/hrd write t0002"])

    def test_ship_child_limit_is_not_rerun(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp)); cfg["autonomy"]["publish"] = "auto"
        json.dump(cfg, open(cfgp, "w"))
        self.commit("auto"); sh(self.root, "git", "push", "-q", "origin", "main")
        from test_batch import pr_work  # noqa: F401
        sh(self.root, "git", "switch", "-q", "-c", "herald/t0001--post-t0001")
        crit, st = pr_work({"final_round": {"verdict": "PASS", "audit": {}}}, "t0001", "post-t0001")
        self.write(".claude/herald/work/t0001/critique.json", crit)
        self.write(".claude/herald/work/t0001/state.json", st)
        self.write(".claude/herald/work/t0001/verify.json", json.dumps({"counts": {}}))
        self.write("src/content/blog/post-t0001.md", "x")
        self.commit("pr head")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:refs/pull/100/head")
        sh(self.root, "git", "switch", "-q", "main")
        sh(self.root, "git", "branch", "-q", "-D", "herald/t0001--post-t0001")
        p = self.run_batch({"t0001": "pr"}, n=1, env={"HRD_FAKE_SHIP_LIMIT": "1"})
        s = self.summary(p)
        self.assertEqual(s["auto"]["rate_limited"], "limit", p.stderr)
        self.assertFalse(s["auto"]["published"])
        self.assertEqual([c["prompt"] for c in self.call_log()].count("/hrd ship --auto"), 1)


class LockAndSignalTests(RunnerCase):
    def wait_for(self, path, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            if os.path.exists(path):
                return True
            time.sleep(0.05)
        return False

    def test_lock_taken_during_wait(self):
        proc = self.run_batch({"t0001": ["branch-limit", "pr"]}, n=1, reset=NOW + 4 * 3600, background=True)
        waitf = os.path.join(self.root, ".claude/herald/memory/lock.wait")
        self.assertTrue(self.wait_for(waitf))
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        lock.force_unlock(self.root)
        other = lock.acquire(self.root, "status", token="other0000000000")
        out, err = proc.communicate(timeout=300)
        self.assertEqual(proc.returncode, 1, err)
        self.assertIn("lock taken", out)
        self.assertEqual((lock.status(self.root) or {}).get("token"), other)  # not released by the runner
        self.assertEqual(sh(self.root, "git", "rev-parse", "HEAD").strip(), head)  # no git after the theft
        self.assertEqual(len(self.call_log()), 1)

    def test_sigterm_during_wait(self):
        proc = self.run_batch({"t0001": ["branch-limit", "pr"]}, n=1, reset=NOW + 4 * 3600, background=True)
        waitf = os.path.join(self.root, ".claude/herald/memory/lock.wait")
        self.assertTrue(self.wait_for(waitf))
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=120)
        self.assertEqual(proc.returncode, 130)
        self.assertIsNone(lock.status(self.root))
        self.assertFalse(os.path.exists(waitf))
        self.assertEqual(self.topic("t0001")["state"], "held")
        self.assertEqual(sh(self.root, "git", "rev-parse", "--abbrev-ref", "HEAD").strip(), "main")

    def test_checkout_changed_during_wait(self):
        proc = self.run_batch({"t0001": ["branch-limit", "pr"]}, n=1, reset=NOW + 4 * 3600, background=True)
        self.assertTrue(self.wait_for(os.path.join(self.root, ".claude/herald/memory/lock.wait")))
        sh(self.root, "git", "switch", "-q", "herald/t0001--post-t0001")  # a human looks at the branch
        out, err = proc.communicate(timeout=300)
        self.assertEqual(proc.returncode, 0, err)
        self.assertIn("checkout changed", json.loads(out[out.index("{"):])["stopped"])
        self.assertEqual(sh(self.root, "git", "rev-parse", "--abbrev-ref", "HEAD").strip(), "herald/t0001--post-t0001")
        self.assertEqual(len(self.call_log()), 1)

    def test_refusal_names_the_waiting_batch(self):
        tok = lock.acquire(self.root, "batch")
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "batch_runner"])
        try:
            until = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
            from hrdlib.util import write_json
            write_json(lock.wait_path(self.root), {"token": tok, "pid": sleeper.pid, "until": until})
            with self.assertRaises(Exception) as cm:
                lock.acquire(self.root, "write", token="x")
            self.assertIn("waiting for a usage limit", str(cm.exception))
            self.assertIn("kill %d" % sleeper.pid, str(cm.exception))
        finally:
            sleeper.kill()
            sleeper.wait()
        with self.assertRaises(Exception) as cm:  # dead pid: the ordinary message
            lock.acquire(self.root, "write", token="x")
        self.assertIn("--unlock", str(cm.exception))


class LockStatusTests(RunnerCase):
    def test_lock_status_shows_the_wait(self):
        tok = lock.acquire(self.root, "batch")
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "batch_runner"])
        try:
            until = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
            lock.write_wait(self.root, tok, until)
            data = json.load(open(lock.wait_path(self.root)))
            data["pid"] = sleeper.pid
            json.dump(data, open(lock.wait_path(self.root), "w"))
            out, _ = self.hrd("lock", "status")
            self.assertEqual((out["waiting"]["pid"], out["waiting"]["kind"]), (sleeper.pid, "limit"))
        finally:
            sleeper.kill()
            sleeper.wait()
        self.assertIsNone(self.hrd("lock", "status")[0]["waiting"])


class ShipChildTests(RunnerCase):
    def test_child_env_never_inherits_resume_permission(self):
        self.run_batch({"t0001": "pr"}, n=1, env={"HRD_RESUME_LIMITED": "bogus"})
        self.assertIsNone(self.call_log()[0]["resume_limited"])


class DocsTests(unittest.TestCase):
    def test_prompt_rules(self):
        cmds = os.path.join(SCRIPTS, "..", "commands")
        resume = open(os.path.join(cmds, "resume.md")).read()
        self.assertIn("printenv HRD_RESUME_LIMITED", resume)
        self.assertIn("`HRD_RESUME_LIMITED` equal to the `(run <id>)` in the hold's note", resume)
        self.assertIn("6. Unattended: skip this step — the batch runner releases the hold", resume)
        contract = open(os.path.join(cmds, "atoms", "_contract.md")).read()
        self.assertIn('--note "tooling: rate limited: <the error\'s first\nline>"', contract)


if __name__ == "__main__":
    unittest.main()
