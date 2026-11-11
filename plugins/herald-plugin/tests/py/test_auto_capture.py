"""Automatic capture of public pages a human confirms (design/herald/07-auto-capture.md, 0.16.0):
auto eligibility, the capture ledgers and rule U, the inheritance table, `shot capture` with a fake
tool (never the network: name resolution is patched), confirm/demote, the guard, publish's history
scan, trial and the audit helper. Topics without `capture: auto` stay 0.15.0 (test_screenshots)."""

import json
import os
import shutil
import stat
import subprocess
import sys
import time
import unittest
from unittest import mock

from helpers import SCRIPTS, sh
from test_screenshots import IMG, SLUG, TID, W, ShotCase, png

from hrdlib import shots, store
from hrdlib.config import Config

URL = "https://docs.example.com/settings"
GLOBAL = ["93.184.216.34"]

FAKE_TOOL = r'''#!/usr/bin/env python3
"""A stand-in capture tool: what it does is read from `mode` next to it."""
import hashlib, json, os, struct, subprocess, sys, time, zlib
here = os.path.dirname(os.path.abspath(__file__))
def read(n, d=""):
    p = os.path.join(here, n)
    return open(p).read().strip() if os.path.exists(p) else d
mode = read("mode", "ok")
with open(os.path.join(here, "argv.json"), "w") as f:
    json.dump(sys.argv[1:], f)
out = sys.argv[-1]
if mode == "fail":
    sys.exit(3)
if mode == "none":
    sys.exit(0)
if mode == "text":
    open(out, "w").write("not an image")
    sys.exit(0)
if mode == "sleep":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open(os.path.join(here, "child.pid"), "w").write(str(child.pid))
    time.sleep(60)
def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
pixel = hashlib.sha256((sys.argv[-2] + read("salt")).encode()).digest()[:4]
data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"tEXt", b"Software\x00fake") + chunk(b"IDAT", zlib.compress(b"\x00" + pixel)) + chunk(b"IEND", b""))
open(out, "wb").write(data)
'''


class AutoCase(ShotCase):
    def setUp(self):
        super().setUp()
        self.tooldir = os.path.join(self.tmp, "tool")
        os.makedirs(self.tooldir)
        self.tool = os.path.join(self.tooldir, "fakeshot")
        with open(self.tool, "w") as f:
            f.write(FAKE_TOOL)
        os.chmod(self.tool, os.stat(self.tool).st_mode | stat.S_IEXEC)
        self.set_template([self.tool, "--viewport-size={w},{h}", "--color-scheme={scheme}", "--lang={lang}",
                           "{url}", "{out}"])
        self.manifest([self.shot("s1", "s1-settings.png", url=URL, capture="auto"),
                       self.shot("s2", "s2-token.png", url="https://app.test/t")])

    # helpers
    def set_template(self, t):
        p = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(p))
        if t is None:
            cfg.pop("screenshots", None)
        else:
            cfg["screenshots"] = {"capture": t}
        with open(p, "w") as f:
            json.dump(cfg, f)
        self.cfg = Config.load(self.root)

    def mode(self, m, salt=None):
        open(os.path.join(self.tooldir, "mode"), "w").write(m)
        if salt is not None:
            open(os.path.join(self.tooldir, "salt"), "w").write(salt)

    def cap(self, resolve=GLOBAL):
        kw = {"side_effect": OSError("nope")} if resolve is None else {"return_value": resolve}
        with mock.patch.object(shots, "_resolve", **kw):
            return shots.capture(self.root, self.cfg, TID)

    def plan(self):
        return self.hrd("shot", "plan", "--topic", TID)[0]

    def rec(self, sid="s1"):
        return self.state()["screenshots"]["shots"][sid]

    def captured(self):
        self.plan()
        out = self.cap()
        self.assertEqual(out["captured"], ["s1"], out)
        return out

    def ledger(self, name):
        return shots.ledger_read(os.path.join(self.root, name))

    def confirm(self, *ids):
        return self.hrd("shot", "confirm", "--topic", TID, "--id", ",".join(ids or ("s1",)))[0]

    def s1_bytes(self):
        return open(os.path.join(self.root, IMG, "s1-settings.png"), "rb").read()


class EligibilityTests(AutoCase):
    def st(self):
        return self.state()

    def reasons(self, **kw):
        s = self.shot("s9", "s9-x.png", url=URL, capture="auto")
        s.update(kw)
        return shots.auto_reasons(self.root, self.cfg, TID, self.st(), s)

    def test_each_reason_code(self):
        self.assertEqual(self.reasons(), [])
        self.assertEqual(self.reasons(url="http://docs.example.com/")[0], "url-not-public")
        self.assertEqual(self.reasons(spec={})[0], "no-viewport")
        self.assertEqual(self.reasons(file="%s/s9.jpg" % IMG)[0], "not-png")
        self.assertEqual(self.reasons(mask=["e-mail"])[0], "needs-mask")
        self.assertEqual(self.reasons(spec={"viewport": "1280x800", "crop": "top"})[0], "needs-mask")
        self.set_template([self.tool, "{url}", "{out}"])
        self.assertEqual(self.reasons(spec={"viewport": "1280x800", "theme": "dark"}), ["no-scheme"])
        self.assertEqual(self.reasons(spec={"viewport": "1280x800", "ui_lang": "ko"}), ["no-lang"])
        self.set_template([self.tool, "--lang={lang}", "{url}", "{out}"])
        self.assertEqual(self.reasons(spec={"viewport": "1280x800", "ui_lang": "english"}), ["no-lang"])
        self.set_template(None)
        self.assertEqual(self.reasons()[0], "no-tool")
        self.set_template(["bash", "-lc", "shot {url} {out}"])
        self.assertEqual(self.reasons()[0], "no-tool")
        # every reason, in order, is kept (row 5b needs them all)
        self.assertEqual(self.reasons(mask=["x"]), ["no-tool", "needs-mask"])

    def test_capture_value_is_a_plan_error(self):
        self.manifest([self.shot("s1", "s1-settings.png", url=URL, capture="robot"), self.shot("s2", "s2-token.png")])
        _, p = self.hrd("shot", "plan", "--topic", TID, check=False)
        self.assertIn("capture must be auto or human", p.stderr)

    def test_url_character_set_and_hosts(self):
        for bad in ("https://a.example.com/'x", 'https://a.example.com/"x', "https://a.example.com/$x",
                    "https://a.example.com/`x`", "https://a.example.com/a b", "https://a.example.com/\\x",
                    "https://user@a.example.com/", "https://127.0.0.1/", "https://[::1]/", "https://localhost/",
                    "https://intranet/", "https://wiki.corp.internal/", "https://printer.local/", "https://127.1/",
                    "ftp://a.example.com/", "-https://a.example.com/"):
            self.assertFalse(shots.public_url(bad), bad)
        self.assertTrue(shots.public_url("https://docs.example.com/a/b?q=1&x=(2)#frag"))

    def test_lang_normalization(self):
        self.assertEqual(shots.norm_lang("pt-br"), "pt-BR")
        self.assertEqual(shots.norm_lang("zh-hant"), "zh-Hant")
        self.assertEqual(shots.norm_lang("zh-hant-tw"), "zh-Hant-TW")
        self.assertEqual(shots.norm_lang("es-419"), "es-419")
        self.assertIsNone(shots.norm_lang("--user-data-dir=x"))
        self.assertEqual(self.reasons(spec={"viewport": "1280x800", "ui_lang": "pt-br"}), [])
        # the source-language fallback is checked at plan time (no-lang, a config reason — never bad-value)
        cfg = json.load(open(os.path.join(self.root, ".claude/herald/config.json")))
        cfg["language"] = "english"
        with open(os.path.join(self.root, ".claude/herald/config.json"), "w") as f:
            json.dump(cfg, f)
        self.cfg = Config.load(self.root)
        self.assertEqual(self.reasons(), ["no-lang"])

    def test_retakes_privacy_mismatch_and_other_topics(self):
        st = self.st()
        s = self.shot("s1", "s1-settings.png", url=URL, capture="auto")
        st["retakes"] = [{"target": shots.target(dict(s, url="https://docs.example.com/other")), "kind": "mismatch"}]
        self.assertFalse(shots._retaken(self.root, TID, st, s))  # same id, a new URL: auto again
        st["retakes"] = [{"target": shots.target(s), "kind": "mismatch"}]
        self.assertTrue(shots._retaken(self.root, TID, st, s))
        st["retakes"] = [{"target": dict(shots.target(dict(s, url=None))), "kind": "privacy"}]
        self.assertTrue(shots._retaken(self.root, TID, st, s))  # privacy: by id alone
        # another topic of the same slug (a refresh): url-tuple only, either kind
        st["retakes"] = []
        other = store.new_state("t0002", SLUG)
        other["retakes"] = [{"target": {"id": "s1", "file": "x", "url": URL, "theme": "light", "ui_lang": None},
                             "kind": "privacy"}]
        store.save_state(self.root, "t0002", other)
        self.assertTrue(shots._retaken(self.root, TID, st, s))
        other["retakes"] = [{"target": {"id": "s1", "file": s["file"], "url": None}, "kind": "privacy"}]
        store.save_state(self.root, "t0002", other)
        self.assertFalse(shots._retaken(self.root, TID, st, s))  # its ids are its own numbering


class CaptureTests(AutoCase):
    def test_capture_records_log_then_file(self):
        out = self.plan()
        self.assertEqual(out["auto"], ["s1"])
        out = self.cap()
        self.assertEqual(out["captured"], ["s1"])
        self.assertEqual(out["captures"][0]["url"], URL)
        r = self.rec()
        self.assertEqual((r["status"], r["capture"]), ("captured", "auto"))
        self.assertEqual(r["sha"], shots.blob(self.root, "%s/s1-settings.png" % IMG))
        self.assertNotIn(b"tEXt", self.s1_bytes())  # cleaned like an import
        recs, bad = self.ledger(shots.CAPTURES)
        self.assertEqual((len(recs), bad), (1, []))
        self.assertEqual((recs[0]["topic"], recs[0]["id"], recs[0]["key"], recs[0]["blob"]), (TID, "s1", r["key"], r["sha"]))
        self.assertEqual(recs[0]["at"], r["captured_at"])
        argv = json.load(open(os.path.join(self.tooldir, "argv.json")))
        self.assertEqual(argv[:4], ["--viewport-size=1280,800", "--color-scheme=light", "--lang=en", URL])
        self.assertTrue(os.path.isabs(argv[4]))
        self.assertFalse(os.path.exists(argv[4]))  # the temporary result is gone
        self.assertEqual(out["note"], "screenshots: s1(confirm) s2")
        shots.check_note(out["note"])

    def test_single_pass_substitution(self):
        argv = shots._argv(["t", "--a={w}x{h}", "{url}", "{out}"],
                           {"w": "{url}", "h": "{lang}", "lang": "en", "scheme": "light", "url": "U", "out": "O"})
        self.assertEqual(argv, ["t", "--a={url}x{lang}", "U", "O"])

    def test_failures_lock_to_a_human(self):
        for m, code, resolve in (("none", "no-file", GLOBAL), ("text", "bad-format", GLOBAL),
                                 ("fail", "exit-nonzero", GLOBAL), ("ok", "dns-private", ["10.0.0.7"]),
                                 ("ok", "dns-private", ["93.184.216.34", "127.0.0.1"]), ("ok", "dns-fail", None)):
            with self.subTest(code=code):
                st = self.state()
                st.pop("screenshots", None)
                store.save_state(self.root, TID, st)
                self.mode(m)
                self.plan()
                out = self.cap(resolve)
                self.assertEqual(out["failed"], [{"id": "s1", "code": code}])
                r = self.rec()
                self.assertEqual((r["status"], r["capture"], r["capture_lock"], r["note"]), ("pending", "human", code, code))
                self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "s1-settings.png")))
                # the lock holds: the next plan keeps it a human's, capture does nothing
                self.mode("ok")
                self.assertEqual(self.plan()["auto"], [])
                self.assertEqual(self.cap()["captured"], [])
                self.assertEqual(self.ledger(shots.CAPTURES)[0], [])

    def test_timeout_kills_the_process_group(self):
        self.plan()
        self.mode("sleep")
        with mock.patch.object(shots, "ITEM_TIMEOUT", 1), mock.patch.object(shots, "KILL_GRACE", 1):
            out = self.cap()
        self.assertEqual(out["failed"], [{"id": "s1", "code": "timeout"}])
        pid = int(open(os.path.join(self.tooldir, "child.pid")).read())
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            if subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip() \
                    .startswith("Z"):
                break
            time.sleep(0.1)
        else:
            self.fail("the tool's child survived")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude/herald/memory/shots/tmp", TID, ".pgid")))

    def test_budget_leaves_remaining(self):
        self.plan()
        with mock.patch.object(shots, "BUDGET", 54):
            out = self.cap()
        self.assertEqual(out["remaining"], ["s1"])
        self.assertEqual(self.rec()["status"], "pending")

    def test_changed_body_refused(self):
        self.plan()
        self.write("src/content/blog/%s.md" % SLUG, open(os.path.join(self.root, "src/content/blog/%s.md" % SLUG)).read()
                   + "\nMore.\n")
        with self.assertRaises(Exception) as e:
            self.cap()
        self.assertIn("run it again", str(e.exception))

    def test_inbox_first_is_the_humans(self):
        self.plan()
        time.sleep(0.01)
        self.drop("s1", data=png(pixel=b"\x09\x09\x09\xff"))
        out = self.cap()
        self.assertEqual(out["own"], ["s1"])
        r = self.rec()
        self.assertEqual((r["capture"], r["capture_lock"], r["status"]), ("human", "own", "pending"))
        self.assertEqual(self.hrd("shot", "import", "--topic", TID)[0]["imported"], ["s1"])
        mine = self.s1_bytes()
        # neither the next plan nor capture overwrites it
        self.plan()
        self.cap()
        self.assertEqual(self.s1_bytes(), mine)
        self.assertEqual(self.rec()["status"], "ready")

    def test_older_inbox_file_is_not_taken(self):
        self.plan()
        self.drop("s1", age=3600)
        out = self.cap()
        self.assertEqual(out["captured"], ["s1"])

    def test_failure_then_human_import_never_overwritten(self):
        self.plan()
        self.mode("fail")
        self.cap()
        time.sleep(0.01)
        self.drop("s1", data=png(pixel=b"\x07\x07\x07\xff"))
        self.assertEqual(self.hrd("shot", "import", "--topic", TID)[0]["imported"], ["s1"])
        mine = self.s1_bytes()
        self.mode("ok")
        self.plan()
        self.cap()
        self.assertEqual(self.s1_bytes(), mine)
        self.assertEqual(self.rec()["capture_lock"], "own")

    def test_human_touched_capture_is_moved(self):
        self.captured()
        self.write(IMG + "/s1-settings.png", png(pixel=b"\x01\x01\x01\xff"), binary=True)  # edited by a human
        self.assertEqual(self.plan()["auto"], ["s1"])  # row 6: pending, the edited file moved away
        self.assertIn("s1-settings.png", self.removed())
        self.mode("ok", salt="2")
        self.assertEqual(self.cap()["captured"], ["s1"])


class CaptureErrorsTests(AutoCase):
    def errs(self, t):
        self.set_template(t)
        return shots.capture_errors(self.cfg)

    def test_template_errors(self):
        self.assertEqual(self.errs([self.tool, "{url}", "{out}"]), [])
        self.assertEqual(self.errs(None), [])
        for t in (["bash", "-lc", "x '{url}' {out}"], ["env", "x", "{url}", "{out}"], ["/usr/bin/python3", "{url}", "{out}"],
                  ["tool", "-c", "{url}", "{out}"], ["tool", "--u={url}", "{out}"], ["tool", "{url}", "{out}", "{out}"],
                  ["tool", "{url}", "{out}", "{who}"], [], "tool {url} {out}", ["{url}", "{out}"],
                  ["node18", "{url}", "{out}"], ["CMD.EXE", "/c", "{url}", "{out}"]):
            with self.subTest(t=t):
                self.assertTrue(self.errs(t))

    def test_errors_never_stop_the_harness(self):
        self.set_template(["bash", "-lc", "shot '{url}' {out}"])
        self.assertEqual(self.cfg.validate()[0], [])
        self.hrd("status")
        out, p = self.hrd("config-check")
        self.assertTrue(out["ok"])
        self.assertTrue(out["capture_errors"])
        out = self.plan()
        self.assertEqual(out["auto"], [])
        self.assertTrue(any("no-tool" in w for w in out["warnings"]))


class ConfirmDemoteTests(AutoCase):
    def test_confirm(self):
        self.captured()
        _, p = self.hrd("shot", "confirm", "--topic", TID, "--id", "s1", check=False, env={"HRD_UNATTENDED": "1"})
        self.assertIn("unattended", p.stderr)
        _, p = self.hrd("stage", "pass", "--topic", TID, "--stage", "draft", check=False)
        self.assertIn("waiting for confirmation", p.stderr)
        self.assertIn("confirm", p.stderr)
        self.confirm()
        r = self.rec()
        self.assertEqual((r["status"], r["confirmed_sha"]), ("ready", r["sha"]))
        self.assertEqual(len(self.ledger(shots.CONFIRMATIONS)[0]), 1)
        self.drop("s2")
        self.hrd("shot", "import", "--topic", TID)
        self.hrd("stage", "pass", "--topic", TID, "--stage", "draft")
        # the next plan keeps the confirmed capture (row 4)
        st = self.state()
        st["stage"] = "draft"
        store.save_state(self.root, TID, st)
        self.plan()
        self.assertEqual(self.rec()["status"], "ready")

    def test_confirm_writes_the_ledger_before_the_state(self):
        self.captured()
        with mock.patch.object(store, "save_state", side_effect=RuntimeError("cut")):
            with self.assertRaises(RuntimeError):
                shots.confirm(self.root, self.cfg, TID, "s1")
        self.assertEqual(len(self.ledger(shots.CONFIRMATIONS)[0]), 1)
        self.assertEqual(self.rec()["status"], "captured")

    def test_confirm_refusals(self):
        self.captured()
        recs, _ = self.ledger(shots.CAPTURES)
        os.remove(os.path.join(self.root, shots.CAPTURES))  # another machine's capture
        _, p = self.hrd("shot", "confirm", "--topic", TID, "--id", "s1", check=False)
        self.assertIn("no capture record on this machine", p.stderr)
        self.assertIn("demote", p.stderr)
        self.assertTrue(any("no capture record" in x for x in shots.draft_problems(self.root, self.cfg, TID, self.state())))
        _, p = self.hrd("shot", "confirm", "--topic", TID, "--id", "s2", check=False)
        self.assertIn("not an automatic capture waiting", p.stderr)

    def test_demote_privacy_goes_to_the_writer(self):
        self.captured()
        _, p = self.hrd("shot", "demote", "--topic", TID, "--id", "s1", "--retake-kind", "privacy", check=False,
                        env={"HRD_UNATTENDED": "1"})
        self.assertIn("unattended", p.stderr)
        before = self.state().get("loopbacks", 0)
        out = self.hrd("shot", "demote", "--topic", TID, "--id", "s1", "--retake-kind", "privacy", "--reason",
                       "an e-mail shows")[0]
        self.assertIn("writer", out["next"])
        st = self.state()
        r = st["screenshots"]["shots"]["s1"]
        self.assertEqual((r["status"], r["capture"], r["capture_lock"]), ("pending", "human", "demoted"))
        self.assertIsNone(r["sha"])
        self.assertIsNone(r["captured_at"])
        self.assertIsNone(r["confirmed_sha"])
        self.assertEqual((st["stage"], st["last_loopback"], st["screenshots"]["awaiting"]), ("draft", "human", False))
        self.assertEqual(st.get("loopbacks", 0), before)
        self.assertEqual(st["retakes"][-1]["kind"], "privacy")
        self.assertIn("s1-settings.png", self.removed())
        # the writer fills mask: a human screenshot from now on
        self.manifest([self.shot("s1", "s1-settings.png", url=URL, capture="auto", mask=["e-mail"]),
                       self.shot("s2", "s2-token.png", url="https://app.test/t")])
        self.assertEqual(self.plan()["auto"], [])
        self.assertEqual(self.hrd("shot", "status", "--topic", TID)[0]["note"], "screenshots: s1(retake:privacy) s2")

    def test_demote_mismatch_then_a_new_url_is_auto_again(self):
        self.captured()
        self.hrd("shot", "demote", "--topic", TID, "--id", "s1", "--retake-kind", "mismatch", "--reason", "old menu")
        self.assertEqual(self.plan()["auto"], [])  # same key: the lock holds
        self.manifest([self.shot("s1", "s1-settings.png", url=URL + "/v2", capture="auto"),
                       self.shot("s2", "s2-token.png", url="https://app.test/t")])
        self.assertEqual(self.plan()["auto"], ["s1"])

    def test_demote_own_goes_to_import(self):
        self.captured()
        _, p = self.hrd("shot", "demote", "--topic", TID, "--id", "s1", "--own", check=False)
        self.assertIn("put exactly one file", p.stderr)
        # the capture itself in the inbox is no human's file
        self.drop("s1", data=self.s1_bytes())
        _, p = self.hrd("shot", "demote", "--topic", TID, "--id", "s1", "--own", check=False)
        self.assertIn("automatic capture itself", p.stderr)
        self.drop("s1", data=png(pixel=b"\x05\x06\x07\xff"), age=7200)  # older than the wait: own may take it
        out = self.hrd("shot", "demote", "--topic", TID, "--id", "s1", "--own")[0]
        self.assertIn("import", out["next"])
        self.assertEqual(self.state()["stage"], "draft")
        self.assertEqual(self.hrd("shot", "import", "--topic", TID)[0]["imported"], ["s1"])
        self.assertEqual(self.rec()["capture_lock"], "own")

    def test_demote_refusals(self):
        self.captured()
        _, p = self.hrd("shot", "demote", "--topic", TID, "--id", "s1", check=False)
        self.assertIn("exactly one of", p.stderr)
        st = self.state()
        st["trim"] = {"status": "open"}
        store.save_state(self.root, TID, st)
        _, p = self.hrd("shot", "demote", "--topic", TID, "--id", "s1", "--retake-kind", "mismatch", check=False)
        self.assertIn("trim is open", p.stderr)
        st["trim"] = {}
        st["stage"] = "critique"
        store.save_state(self.root, TID, st)
        _, p = self.hrd("shot", "demote", "--topic", TID, "--id", "s1", "--retake-kind", "mismatch", check=False)
        self.assertIn("loopback --retake", p.stderr)

    def test_import_refusal_wording(self):
        self.captured()
        data = self.s1_bytes()
        self.drop("s1", data=data)
        out = self.hrd("shot", "import", "--topic", TID)[0]
        self.assertTrue(any("automatic capture itself" in x and "confirm" in x for x in out["problems"]), out)
        self.assertTrue(any("waiting for confirmation" in w for w in out["warnings"]))
        os.remove(os.path.join(self.root, ".claude/herald/inbox", TID, "s1.png"))
        self.drop("s2", data=data)  # s1's capture saved as s2
        out = self.hrd("shot", "import", "--topic", TID)[0]
        self.assertTrue(any("take the screen yourself" in x for x in out["problems"]), out)
        self.assertEqual(out["imported"], [])


class GuardTests(AutoCase):
    def guard(self, tool, tool_input, env=None):
        e = dict(os.environ)
        e.update(env or {})
        payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": self.root})
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard.py")], input=payload,
                           capture_output=True, text=True, env=e, cwd=self.root, timeout=60)
        if not p.stdout.strip():
            return "allow"
        return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_confirm_demote_ledger_and_config(self):
        un = {"HRD_UNATTENDED": "1"}
        for cmd in ("python3 .claude/herald/scripts/hrd.py shot confirm --topic t0001 --id s1",
                    "python3 .claude/herald/scripts/hrd.py shot demote --topic t0001 --id s1 --own"):
            self.assertEqual(self.guard("Bash", {"command": cmd}), "ask")
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny")
        self.assertEqual(self.guard("Bash", {"command": "python3 .claude/herald/scripts/hrd.py shot capture --topic t0001"}),
                         "allow")
        for name in (shots.CAPTURES, shots.CONFIRMATIONS):
            self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, name)}), "ask")
            self.assertEqual(self.guard("Bash", {"command": "echo x >> %s" % name}, un), "deny")
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cur = json.load(open(cfgp))
        cur["screenshots"] = {"capture": ["sh", "-c", "{url}"]}
        self.assertEqual(self.guard("Write", {"file_path": cfgp, "content": json.dumps(cur)}), "ask")


class LedgerTests(AutoCase):
    def path(self):
        return os.path.join(self.root, shots.CAPTURES)

    def line(self, i):
        return {"topic": TID, "id": "s%d" % i, "key": "k", "blob": "b%d" % i, "sha256": "h%d" % i, "at": "t"}

    def test_append_and_read_rules(self):
        p = self.path()
        shots.ledger_append(p, self.line(1))
        with open(p, "ab") as f:
            f.write(b'{"topic": "t0001", "id": "s2", "ke')  # a write that stopped
        self.assertEqual(len(shots.ledger_read(p)[0]), 1)  # the unterminated piece is ignored
        self.assertEqual(shots.ledger_read(p)[1], [])
        shots.ledger_append(p, self.line(3))  # cuts it off, then writes
        recs, bad = shots.ledger_read(p)
        self.assertEqual(([r["id"] for r in recs], bad), (["s1", "s3"], []))
        # an editor dropped the final newline of a whole record: kept
        with open(p, "rb+") as f:
            data = f.read()
            f.seek(0)
            f.truncate()
            f.write(data.rstrip(b"\n"))
        self.assertEqual(len(shots.ledger_read(p)[0]), 2)
        shots.ledger_append(p, self.line(4))
        self.assertEqual([r["id"] for r in shots.ledger_read(p)[0]], ["s1", "s3", "s4"])
        # a finished line that is no whole record is damage, with its number
        with open(p, "ab") as f:
            f.write(b'{"topic": "t0001"}\n' + b"\xff\xfe\n")
        self.assertEqual(shots.ledger_read(p)[1], [4, 5])

    def test_damage_refuses_only_with_something_to_judge(self):
        os.makedirs(os.path.dirname(self.path()), exist_ok=True)
        with open(self.path(), "w") as f:
            f.write("not json\n")
        out = self.plan()  # nothing on disk to judge: a warning
        self.assertTrue(any("damaged line" in w and "line 1" in w for w in out["warnings"]))
        with self.assertRaises(Exception) as e:
            self.cap()  # s1 is to be captured
        self.assertIn("tooling: shots ledger damaged line 1", str(e.exception))
        self.drop("s2")
        _, p = self.hrd("shot", "import", "--topic", TID, check=False)
        self.assertIn("damaged line", p.stderr)
        # a topic with no screenshots at all is not stopped
        self.assertEqual(shots.draft_problems(self.root, self.cfg, "t0099", {"slug": "nothing-here"}), [])


class InheritanceTests(AutoCase):
    def test_0_15_0_state_upgrade_keeps_the_humans_file(self):
        self.manifest([self.shot("s1", "s1-settings.png", url=URL), self.shot("s2", "s2-token.png", url="https://app.test/t")])
        self.set_template(None)
        self.plan()
        self.drop("s1")
        self.hrd("shot", "import", "--topic", TID)
        st = self.state()
        for r in st["screenshots"]["shots"].values():  # as 0.15.0 wrote it
            for k in ("capture", "capture_lock", "note", "captured_at", "confirmed_sha"):
                r.pop(k, None)
        store.save_state(self.root, TID, st)
        mine = self.s1_bytes()
        self.set_template([self.tool, "--lang={lang}", "{url}", "{out}"])
        self.manifest([self.shot("s1", "s1-settings.png", url=URL, capture="auto"),
                       self.shot("s2", "s2-token.png", url="https://app.test/t")])
        out = self.plan()
        self.assertEqual(out["auto"], [])
        r = self.rec()
        self.assertEqual((r["status"], r["capture"], r["capture_lock"]), ("ready", "human", "own"))
        self.assertEqual(self.s1_bytes(), mine)

    def test_row2_lock_keeps_waiting_since_and_moves_a_cut_demote(self):
        self.captured()
        cap = self.s1_bytes()
        st = self.state()  # a demote cut before its file moved: state says pending/demoted, the capture is there
        st["screenshots"]["shots"]["s1"].update(status="pending", capture="human", capture_lock="demoted", sha=None,
                                                captured_at=None, waiting_since="2026-11-01T00:00:00+00:00")
        store.save_state(self.root, TID, st)
        self.plan()
        r = self.rec()
        self.assertEqual((r["status"], r["capture_lock"], r["waiting_since"]),
                         ("pending", "demoted", "2026-11-01T00:00:00+00:00"))
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "s1-settings.png")))
        self.assertTrue(cap)

    def test_row2_and_row4_never_equal_on_missing_values(self):
        self.plan()
        self.mode("fail")
        self.cap()  # a lock and no file, sha None
        self.plan()
        self.assertEqual(self.rec()["status"], "pending")
        st = self.state()  # an auto entry never captured: no sha, no confirmed_sha
        st["screenshots"]["shots"]["s1"].update(capture="auto", capture_lock=None, note=None)
        store.save_state(self.root, TID, st)
        self.assertEqual(self.plan()["auto"], ["s1"])
        self.assertEqual(self.rec()["status"], "pending")

    def test_row3_takes_sha_and_time_from_the_file_and_log(self):
        self.captured()
        p = os.path.join(self.root, shots.CAPTURES)
        recs, _ = shots.ledger_read(p)
        recs[0]["blob"] = "0" * 40  # only sha256 matches now (a changed .gitattributes)
        with open(p, "w") as f:
            f.write(json.dumps(recs[0]) + "\n")
        st = self.state()
        st["screenshots"]["shots"]["s1"].update(sha=None, captured_at=None, status="pending")
        store.save_state(self.root, TID, st)
        self.plan()
        r = self.rec()
        self.assertEqual(r["status"], "captured")
        self.assertEqual(r["sha"], shots.blob(self.root, "%s/s1-settings.png" % IMG))
        self.assertEqual(r["captured_at"], recs[0]["at"])
        self.confirm()  # confirm still works: the sha is the file's own

    def test_row3_other_items_capture_moves(self):
        self.captured()
        st = self.state()
        self.manifest([self.shot("s1", "s1-settings.png", url=URL), self.shot("s2", "s2-token.png", url="https://app.test/t")])
        self.plan()  # now a human's: the unconfirmed capture never becomes their file
        self.assertEqual(self.rec()["status"], "pending")
        self.assertIn("s1-settings.png", self.removed())
        self.assertTrue(st)

    def test_row5b_config_reasons_keep_a_confirmed_capture(self):
        self.captured()
        self.confirm()
        self.set_template(None)
        out = self.plan()
        r = self.rec()
        self.assertEqual((r["status"], r["capture"]), ("ready", "auto"))
        # needs-mask is about the screen itself: no-tool must not hide it
        self.manifest([self.shot("s1", "s1-settings.png", url=URL, capture="auto", mask=["e-mail"]),
                       self.shot("s2", "s2-token.png", url="https://app.test/t")])
        self.plan()
        r = self.rec()
        self.assertEqual((r["status"], r["capture"]), ("pending", "human"))
        self.assertIn("s1-settings.png", self.removed())


class PublishTests(AutoCase):
    def setUp(self):
        super().setUp()
        branch = store.branch_name(TID, SLUG)  # the capture template is base's config, not this PR's
        sh(self.root, "git", "switch", "-q", "main")
        self.commit("capture template", ".claude/herald/config.json")
        sh(self.root, "git", "push", "-q", "origin", "main")
        sh(self.root, "git", "switch", "-q", branch)
        sh(self.root, "git", "merge", "-q", "--ff-only", "main")

    def wip(self, files):
        for rel, data in files.items():
            self.write(rel, data, binary=True)
        sh(self.root, "git", "add", "-A", "--", IMG)
        sh(self.root, "git", "commit", "-q", "-m", "wip(herald): x")

    def logged_png(self, pixel):
        data, _ = shots.sanitize(png(pixel=pixel), "png")
        rel = "%s/s1-settings.png" % IMG
        h = shots._bytes_hashes(self.root, rel, data)
        shots.ledger_append(os.path.join(self.root, shots.CAPTURES),
                            {"topic": "t0042", "id": "s1", "key": "k", "file": rel, "blob": h[0], "sha256": h[1], "at": "t"})
        return data, h

    def test_scope_refuses_unconfirmed_auto_but_not_at_a_rev(self):
        self.captured()
        self.drop("s2")
        self.hrd("shot", "import", "--topic", TID)
        sh(self.root, "git", "add", "-A", "--", W, IMG, "src/content/blog/%s.md" % SLUG)
        self.commit("feat(herald): publish")
        self.hrd("shot", "squash", "--topic", TID)
        out, p = self.hrd("scope", "--topic", TID, check=False)
        self.assertTrue(any("no human or agent confirmed" in x for x in out["screenshots"]), out)
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        out, p = self.hrd("scope", "--topic", TID, "--rev", head, check=False)
        self.assertNotIn("screenshots", out or {}, p.stdout)
        # confirmed: the same branch passes
        self.confirm()
        sh(self.root, "git", "add", "-A", "--", W)
        self.commit("feat(herald): confirmed")
        self.hrd("shot", "squash", "--topic", TID)
        out, p = self.hrd("scope", "--topic", TID, check=False)
        self.assertNotIn("screenshots", out, p.stdout)

    def test_history_of_a_topic_without_records(self):
        os.remove(os.path.join(self.root, W, "screenshots.json"))
        data, h = self.logged_png(b"\x0a\x0b\x0c\xff")
        self.wip({IMG + "/copy.png": data})
        os.remove(os.path.join(self.root, IMG, "copy.png"))
        sh(self.root, "git", "add", "-A", "--", IMG)
        sh(self.root, "git", "commit", "-q", "-m", "wip(herald): gone again")
        # rule U runs with no manifest and no records too
        hits = shots._range_blobs(self.root, self.cfg, SLUG)
        self.assertTrue(hits and all(len(b) == 40 for _, _, b in hits))
        out, p = self.hrd("scope", "--topic", TID, check=False)
        self.assertTrue(any("HRD shot squash" in x for x in out["screenshots"]), out)
        self.assertTrue(self.hrd("shot", "squash", "--topic", TID)[0]["squashed"])
        out, p = self.hrd("scope", "--topic", TID, check=False)
        self.assertNotIn("screenshots", out, p.stdout)

    def test_history_in_head_pushed_and_merge_commits(self):
        os.remove(os.path.join(self.root, W, "screenshots.json"))
        data, h = self.logged_png(b"\x0d\x0e\x0f\xff")
        self.wip({IMG + "/kept.png": data})
        self.assertTrue(any("confirm or demote" in x for x in shots.history_problems(self.root, self.cfg, TID, SLUG)[0]))
        self.assertTrue(any("kept.png" in x for x in shots.draft_problems(self.root, self.cfg, TID, self.state())))
        sh(self.root, "git", "push", "-q", "-u", "origin", store.branch_name(TID, SLUG))
        os.remove(os.path.join(self.root, IMG, "kept.png"))
        sh(self.root, "git", "add", "-A", "--", IMG)
        sh(self.root, "git", "commit", "-q", "-m", "wip(herald): drop")
        probs, squashable = shots.history_problems(self.root, self.cfg, TID, SLUG)
        self.assertTrue(any("already pushed" in x for x in probs))
        self.assertFalse(squashable)
        # an evil merge: the merge commit itself brings the blob
        branch = store.branch_name(TID, SLUG)
        sh(self.root, "git", "switch", "-q", "-c", "side", "origin/main")
        self.write("src/content/blog/side.md", "side\n")
        self.commit("side", "src/content/blog/side.md")
        sh(self.root, "git", "switch", "-q", branch)
        other, _ = self.logged_png(b"\x1d\x1e\x1f\xff")
        sh(self.root, "git", "merge", "-q", "--no-ff", "--no-commit", "side")
        self.write(IMG + "/merged.png", other, binary=True)
        sh(self.root, "git", "add", "-A", "--", IMG)
        sh(self.root, "git", "commit", "-q", "-m", "merge side")
        os.remove(os.path.join(self.root, IMG, "merged.png"))
        sh(self.root, "git", "add", "-A", "--", IMG)
        sh(self.root, "git", "commit", "-q", "-m", "drop merged")
        probs, squashable = shots.history_problems(self.root, self.cfg, TID, SLUG)
        self.assertTrue(any("merged.png" in x and "squash" in x for x in probs), probs)
        self.assertTrue(squashable)

    def test_confirmed_content_passes_history(self):
        data, h = self.logged_png(b"\x2a\x2b\x2c\xff")
        shots.ledger_append(os.path.join(self.root, shots.CONFIRMATIONS),
                            {"topic": "t0042", "id": "s1", "key": "k", "blob": h[0], "sha256": h[1], "at": "t"})
        self.wip({IMG + "/ok.png": data})
        self.assertEqual(shots.history_problems(self.root, self.cfg, TID, SLUG)[0], [])


class TrialAndAuditTests(AutoCase):
    def test_trial(self):
        out = self.hrd("shot", "trial")[0]
        self.assertTrue(out["ok"])
        self.assertIn("about:blank", out["argv"])
        self.assertIn("--viewport-size=800,600", out["argv"])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude/herald/memory/shots/tmp/trial")))
        self.assertFalse(os.path.exists(os.path.join(self.root, shots.CAPTURES)))
        self.mode("fail")
        out, p = self.hrd("shot", "trial", check=False)
        self.assertEqual((p.returncode, out["code"]), (1, "exit-nonzero"))
        self.set_template(["sh", "-c", "{url}", "{out}"])
        _, p = self.hrd("shot", "trial", check=False)
        self.assertIn("shell", p.stderr)

    def test_audit_helper(self):
        self.captured()
        self.confirm()
        self.assertEqual(self.hrd("shot", "audit")[0]["anomalies"], [])
        # a state edited by hand to look confirmed
        st = self.state()
        st["screenshots"]["shots"]["s1"]["confirmed_sha"] = "f" * 40
        store.save_state(self.root, TID, st)
        other = store.new_state("t0002", "elsewhere")  # captured on another machine: counted apart
        other["screenshots"] = {"shots": {"s1": {"capture": "auto", "status": "ready", "key": "k", "sha": "a",
                                                 "confirmed_sha": "a"}}}
        store.save_state(self.root, "t0002", other)
        pending = store.new_state("t0003", "pending")  # captured, waiting: normal
        pending["screenshots"] = {"shots": {"s1": {"capture": "auto", "status": "captured", "key": "k"}}}
        store.save_state(self.root, "t0003", pending)
        with open(os.path.join(self.root, shots.CONFIRMATIONS), "a") as f:
            f.write("garbage\n")
        out = self.hrd("shot", "audit")[0]
        self.assertEqual([(a["topic"], a["id"]) for a in out["anomalies"]], [(TID, "s1")])
        self.assertEqual(out["no_record"], 1)
        self.assertEqual(out["damaged"], [{"file": shots.CONFIRMATIONS, "line": 2}])
        self.assertFalse(out["ok"])


class NoteTests(AutoCase):
    def test_confirm_code_in_notes(self):
        shots.check_note("screenshots: s1(confirm) s2 s3(retake:privacy)")
        with self.assertRaises(Exception):
            shots.check_note("screenshots: s1(confirmed)")
        self.hrd("result", "--topic", TID, "--status", "held:screenshots", "--note", "screenshots: s1(confirm)")


class ImplementationReview1Tests(AutoCase):
    """Implementation review round 1 (MINOR m1–m9)."""

    def test_m1_confirm_cut_after_its_ledger_line_stays_captured(self):
        self.captured()
        with mock.patch.object(store, "save_state", side_effect=RuntimeError("cut")):
            with self.assertRaises(RuntimeError):
                shots.confirm(self.root, self.cfg, TID, "s1")
        out = self.plan()
        self.assertEqual(self.rec()["status"], "captured")  # never promoted in plan, never recaptured
        self.assertEqual(out["moved"], [])
        self.confirm()
        self.assertEqual(self.rec()["status"], "ready")

    def test_m2_capture_never_takes_a_retaken_screen_before_plan(self):
        self.captured()
        self.confirm()
        st = self.state()
        st["stage"] = "critique"
        store.save_state(self.root, TID, st)
        self.hrd("loopback", "--topic", TID, "--human", "--retake", "s1", "--retake-kind", "privacy", "--reason", "e")
        self.assertEqual(self.rec()["capture"], "human")
        out = self.cap()
        self.assertEqual(out["captured"], [])
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "s1-settings.png")))
        # capture judges again by itself too (a retake recorded while the item still said auto)
        st = self.state()
        st["screenshots"]["shots"]["s1"]["capture"] = "auto"
        store.save_state(self.root, TID, st)
        out = self.cap()
        self.assertEqual((out["captured"], out["skipped"]), ([], [{"id": "s1", "code": "retaken"}]))
        self.assertEqual(self.rec()["capture"], "human")

    def test_m3_language_only_when_the_template_has_lang(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp))
        cfg["language"] = "english"
        cfg["screenshots"] = {"capture": [self.tool, "{url}", "{out}"]}
        with open(cfgp, "w") as f:
            json.dump(cfg, f)
        self.cfg = Config.load(self.root)
        self.assertEqual(self.plan()["auto"], ["s1"])
        self.assertEqual(self.cap()["captured"], ["s1"])

    def test_m4_key_change_moves_the_capture_and_wording_follows_status(self):
        self.captured()
        self.manifest([self.shot("s1", "s1-settings.png", url="http://docs.example.com/x", capture="auto"),
                       self.shot("s2", "s2-token.png", url="https://app.test/t")])
        out = self.plan()
        self.assertIn("%s/s1-settings.png" % IMG, out["moved"])
        self.assertEqual(self.rec()["status"], "pending")
        self.assertFalse(any("no human or agent confirmed" in x for x in shots.draft_problems(self.root, self.cfg, TID, self.state())))
        # a capture put back under a pending item: plan, then capture/import; under a ready one: a retake
        self.manifest([self.shot("s1", "s1-settings.png", url=URL, capture="auto"),
                       self.shot("s2", "s2-token.png", url="https://app.test/t")])
        self.plan()
        self.cap()
        cap = self.s1_bytes()
        st = self.state()
        st["screenshots"]["shots"]["s1"].update(status="pending", sha=None)
        store.save_state(self.root, TID, st)
        probs = shots.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("no human or agent confirmed" in x and "HRD shot plan" in x for x in probs), probs)
        st["screenshots"]["shots"]["s1"].update(status="ready", sha=shots.blob(self.root, "%s/s1-settings.png" % IMG))
        store.save_state(self.root, TID, st)
        probs = shots.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("no human or agent confirmed" in x and "--human --retake s1" in x for x in probs), probs)
        self.assertTrue(cap)

    def test_m5_import_moves_what_sits_at_the_destination(self):
        self.plan()
        self.write(IMG + "/s2-token.png", png(pixel=b"\x03\x03\x03\xff"), binary=True)  # put there by hand
        time.sleep(0.01)
        self.drop("s2")
        self.assertEqual(self.hrd("shot", "import", "--topic", TID)[0]["imported"], ["s2"])
        self.assertIn("s2-token.png", self.removed())

    def test_m6_numeric_last_labels(self):
        for bad in ("https://127.0.0.0x1/", "https://1.2.3.0x7f/", "https://1.2.3.0X7F/", "https://a.b.0x/",
                    "https://10.0.0.010/"):
            self.assertFalse(shots.public_url(bad), bad)
        self.assertTrue(shots.public_url("https://a.example.co/"))

    def test_m7_shells_anywhere_and_inline_flags(self):
        for t in (["tool", "sh", "{url}", "{out}"], ["timeout", "30", "bash", "{url}", "{out}"],
                  ["npx", "/usr/bin/node", "{url}", "{out}"], ["tool", "-lc", "{url}", "{out}"],
                  ["tool", "-ec", "{url}", "{out}"], ["tool", "--call", "{url}", "{out}"],
                  ["tool", "eval", "{url}", "{out}"]):
            with self.subTest(t=t):
                self.set_template(t)
                self.assertTrue(shots.capture_errors(self.cfg))
        self.set_template(["npx", "--no-install", "playwright", "screenshot", "--viewport-size={w},{h}",
                           "--color-scheme={scheme}", "--lang={lang}", "{url}", "{out}"])
        self.assertEqual(shots.capture_errors(self.cfg), [])

    def test_m8_broken_template_after_plan(self):
        self.plan()
        self.set_template(["bash", "-lc", "{url}", "{out}"])
        with self.assertRaises(Exception) as e:
            self.cap()
        self.assertIn("tooling: shots capture template invalid", str(e.exception))
        atom = open(os.path.join(SCRIPTS, "..", "commands", "atoms", "_screenshots.md")).read()
        self.assertIn("tooling: shots capture template invalid", atom)
        self.assertEqual(self.plan()["auto"], [])  # then plan: no-tool, a human's

    def test_m9_reap_stale_match_and_reuse(self):
        d = os.path.join(self.root, ".claude/herald/memory/shots/tmp", TID)
        os.makedirs(d)
        rec_path = os.path.join(d, ".pgid")
        for matching in (True, False):
            p = subprocess.Popen(["sleep", "60"], start_new_session=True)
            try:
                started = shots._ps(p.pid, "lstart") if matching else "Mon Jan  1 00:00:00 1990"
                with open(rec_path, "w") as f:
                    json.dump({"pgid": p.pid, "started": started, "argv0": "sleep"}, f)
                warnings = []
                shots._reap_stale(self.root, TID, warnings)
                self.assertFalse(os.path.exists(rec_path))
                if matching:
                    self.assertEqual(p.wait(timeout=10), -9)
                    self.assertEqual(warnings, [])
                else:
                    self.assertIsNone(p.poll())  # a reused PID is left alone
                    self.assertTrue(any("does not match" in w for w in warnings))
            finally:
                if p.poll() is None:
                    p.kill()
                    p.wait()

    def test_m9_stale_pgid_of_a_gone_process_is_cleaned(self):
        d = os.path.join(self.root, ".claude/herald/memory/shots/tmp", TID)
        os.makedirs(d)
        p = subprocess.Popen(["true"])
        p.wait()
        with open(os.path.join(d, ".pgid"), "w") as f:
            json.dump({"pgid": p.pid, "started": "x", "argv0": "true"}, f)
        self.plan()
        out = self.cap()
        self.assertEqual(out["warnings"], [])
        self.assertFalse(os.path.exists(os.path.join(d, ".pgid")))

    def test_m9_history_refuses_when_filters_fail(self):
        os.remove(os.path.join(self.root, W, "screenshots.json"))
        data, _ = shots.sanitize(png(pixel=b"\x44\x45\x46\xff"), "png")
        rel = "%s/x.png" % IMG
        h = shots._bytes_hashes(self.root, rel, data)
        shots.ledger_append(os.path.join(self.root, shots.CAPTURES),
                            {"topic": "t0042", "id": "s1", "key": "k", "file": rel, "blob": h[0], "sha256": h[1], "at": "t"})
        self.write(rel, data, binary=True)
        sh(self.root, "git", "add", "--", rel)
        sh(self.root, "git", "commit", "-q", "-m", "wip")
        sh(self.root, "git", "config", "filter.bad.clean", "cat")
        sh(self.root, "git", "config", "filter.bad.smudge", "false")
        sh(self.root, "git", "config", "filter.bad.required", "true")
        self.write(".gitattributes", "*.png filter=bad\n")
        probs, _ = shots.history_problems(self.root, self.cfg, TID, SLUG)
        self.assertTrue(any("cannot read" in x for x in probs), probs)

    def test_m9_rule_u_catches_a_copy_under_another_name(self):
        self.captured()
        shutil.copy(os.path.join(self.root, IMG, "s1-settings.png"), os.path.join(self.root, IMG, "renamed.png"))
        probs = shots.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("renamed.png" in x and "no listed screenshot" in x for x in probs), probs)


if __name__ == "__main__":
    unittest.main()
