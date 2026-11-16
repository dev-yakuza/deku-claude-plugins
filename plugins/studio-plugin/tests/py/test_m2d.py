"""capture.py (m2-plan §5.1, §5.3): the URL and selector rules (host lists, no query or fragment and a short path in a
picture's address, the internal overlay's hosts and terms, a missing overlay → 4, selector characters), the `capture`
setting (host names only, protected: `설정 <h12>`), the run through the fake s2v capture (the command line Studio
builds, a redirect to another host, apex → www, s2v's exit codes, a signal, `idle: false`, blocked hosts, the files
and captures.json), S2V_CAPTURE_NO_SANDBOX refused, one capture per video, and the fake's JSON keys against s2v's
`CaptureJson`. No network: the fake s2v only; `helpers.run_s2v` refuses `capture`."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import unittest

import helpers
import state_fixtures as F
from helpers import StudioTestCase
from stdo import machine, paths
from stdo.capture import cli, rules, run as crun
from stdo.guard import web
from stdo.setup import common, configcmd
from stdo.setup.common import SetupError
from stdo.state import store

FAKE_ROOT = os.path.join(helpers.HERE, "drivers", "fake_s2v_cli")
# s2v packages/cli/src/capture/extract.ts:194-214 (`CaptureJson`, s2v 0.13.2 at 754443c): compare by hand when s2v's
# version changes. The fake's keys must be a subset; Studio reads only these (run.JSON_KEYS).
CAPTURE_JSON = {"url", "status", "title", "lang", "idle", "text", "images", "opaque", "notShown", "blocked",
                "websockets", "contentHash"}
TEXT_KEYS, RUBY_KEYS = {"kind", "text", "ruby"}, {"base", "reading"}
IMAGE_KEYS = {"src", "kind", "bbox", "alt", "inCapture", "sha256"}
OPAQUE_KEYS, BLOCKED_KEYS, WS_KEYS = {"kind", "src", "bbox", "inCapture"}, {"url", "reason"}, {"url", "host"}

CFG = {"public_domains": ["example.com", "blog.example.org"], "internal_overlay": "required",
       "capture": {"hosts": ["docs.thirdparty.net"], "allow_hosts": ["cdn.example.net", "wiki.corp.example"]}}
OVERLAY = {"internal": {"hosts": ["corp.example"], "terms": ["Bluebird", "사내전용", "abc"],
                        "sources": [{"url": "https://wiki.intra.example/page"}], "videos": ["secret-plan"]}}


def items(data=OVERLAY):
    return "ok", set(web.internal_items(data)[0]), web.internal_items(data)[1]


class Rules(StudioTestCase):
    def shot(self, url, public=True, cfg=CFG, it=None):
        return rules.shot_url(url, cfg, it or items(), public)

    def refused(self, code, fn, *a):
        with self.assertRaises(rules.CaptureError) as cm:
            fn(*a)
        self.assertEqual(cm.exception.code, code, str(cm.exception))
        return str(cm.exception)

    def test_shot_hosts(self):
        self.assertEqual(self.shot("https://example.com/a")[1], "example.com")
        self.assertEqual(self.shot("https://example.com")[1], "example.com")
        self.assertEqual(self.shot("https://docs.thirdparty.net/x")[1], "docs.thirdparty.net")
        # a capture.hosts page for an internal video: public_domains only
        self.assertIn("internal video", self.refused(3, self.shot, "https://docs.thirdparty.net/x", False))
        self.assertEqual(self.shot("https://example.com/a", False)[1], "example.com")
        # outside both lists, a subdomain of a public domain included (exact hosts)
        for u in ("https://other.net/a", "https://www.example.com/a"):
            self.assertIn("neither public_domains nor capture.hosts", self.refused(3, self.shot, u))

    def test_shot_address_shape(self):
        for u in ("https://example.com/a?x=1", "https://example.com/a?", "https://example.com/a#top",
                  "https://example.com/a#", "https://example.com/" + "p" * 200, "http://example.com/a",
                  "https://user@example.com/a", "https://example.com:443/a", "https://93.184.216.34/a",
                  "https://[::1]/a", "https://example.com/a b", "ftp://example.com/a",
                  "https://example.com/\"a", "", "x" * 600):
            self.refused(2, self.shot, u)
        self.assertEqual(self.shot("https://example.com/" + "p" * 199)[1], "example.com")
        self.assertEqual(self.shot("https://Example.com/a")[1], "example.com")  # host names are case-blind

    def test_overlay_hosts_and_terms(self):
        cfg = dict(CFG, capture={"hosts": ["wiki.corp.example", "wiki.intra.example"], "allow_hosts": []})
        for u in ("https://wiki.corp.example/a", "https://wiki.intra.example/b"):
            self.assertIn("internal host", self.refused(3, self.shot, u, True, cfg))
        for u in ("https://example.com/bluebird-launch", "https://example.com/%EC%82%AC%EB%82%B4%EC%A0%84%EC%9A%A9",
                  "https://example.com/posts/secret-plan", "https://example.com/BLUEBIRD"):
            self.assertIn("in-house term", self.refused(3, self.shot, u))
        # short terms (under 4 characters) and words that only contain a term pass
        self.assertEqual(self.shot("https://example.com/abc/bluebirds")[1], "example.com")
        # the source page (begin --url later): the same overlay check
        self.assertIn("in-house term", self.refused(3, rules.page_host, "https://example.com/bluebird", CFG, items()))
        self.assertEqual(rules.page_host("https://blog.example.org/p/1", CFG, items()), "blog.example.org")
        self.refused(3, rules.page_host, "https://docs.thirdparty.net/x", CFG, items())
        # an overlay source on a public host does not make the whole public domain internal (as guard/web.py)
        pub = {"internal": {"sources": [{"url": "https://example.com/internal/x"}]}}
        self.assertEqual(self.shot("https://example.com/a", it=items(pub))[1], "example.com")

    def test_review1(self):
        # m1: a subdomain of a public domain named by the overlay is internal (only an exact public domain is exempt)
        cfg = dict(CFG, capture={"hosts": ["intra.example.com"], "allow_hosts": []})
        it = items({"internal": {"hosts": ["intra.example.com"]}})
        self.assertIn("internal host", self.refused(3, self.shot, "https://intra.example.com/a", True, cfg, it))
        self.assertEqual(self.shot("https://example.com/a", True, cfg, items({"internal": {"hosts": ["example.com"]}}))[1],
                         "example.com")
        # m2: decoded until stable, invisible format characters dropped; encoded ? and # refused
        for u in ("https://example.com/%2562luebird", "https://example.com/%252562luebird",
                  "https://example.com/blue%E2%80%8Bbird", "https://example.com/blue\u200bbird"):
            self.assertIn("in-house term", self.refused(3, self.shot, u), u)
        # review 2: encoded more often than the rounds read → refused (2), whatever it hides
        for u in ("https://example.com/%25252562luebird", "https://example.com/%2525252541"):
            self.assertIn("percent-encoded more than", self.refused(2, self.shot, u), u)
        self.assertEqual(self.shot("https://example.com/100%25-off")[1], "example.com")
        for u in ("https://example.com/a%3Fx=1", "https://example.com/a%23top", "https://example.com/a%253Fx"):
            self.assertIn("encoded", self.refused(2, self.shot, u), u)
        self.refused(2, rules.selector, "#blue\u200bbird", items())  # a selector is ASCII: refused before the terms
        # m3: a selector is never a flag
        for v in ("-x", "--out", "--out=a.png"):
            self.refused(2, rules.selector, v, items())
        argv = crun.argv_for("/s", "https://example.com/", "o.png", "o.json", selector="-x")
        self.assertIn("--selector=-x", argv)
        self.assertNotIn("--selector", argv)
        # n4: the final address carries no port or user
        for final in ("https://example.com:8443/a", "https://u@example.com/a", "https://u:p@example.com/a"):
            self.assertEqual(crun.judge("example.com", 0, {"url": final}, "")["status"], "unusable", final)

    def test_overlay_missing(self):
        for st in ("missing",):
            self.assertIn("overlay is missing", self.refused(4, self.shot, "https://example.com/a", True, CFG,
                                                             (st, set(), [])))
        self.assertEqual(self.shot("https://example.com/bluebird", it=("none", set(), []))[1], "example.com")

    def test_selector(self):
        self.assertEqual(rules.selector("main > article:nth-child(2) .hero[data-x=y]", items()),
                         "main > article:nth-child(2) .hero[data-x=y]")
        self.assertIsNone(rules.selector(None, items()))
        for s in ("a;b", "a{b}", "a[x='y']", 'a[x="y"]', "a`b", "a\\b", "a/b", "", "a" * 201, "a\nb", "a@b"):
            self.refused(2, rules.selector, s, items())
        self.assertIn("in-house term", self.refused(3, rules.selector, "#bluebird-panel", items()))

    def test_sizes_and_allow_hosts(self):
        self.assertEqual((rules.size("--width", "320"), rules.size("--width", "4096")), (320, 4096))
        for v in ("319", "4097", "0", "-1", "12.5", "1e3", "abc"):
            self.refused(2, rules.size, "--width", v)
        self.assertEqual(rules.allow_hosts(CFG, ("ok", {"corp.example"}, [])), ["cdn.example.net"])

    def test_config_shape(self):
        self.assertEqual(rules.capture_config({}), ([], []))
        self.assertIsNone(rules.config_problem({"hosts": [], "allow_hosts": ["a.example.com"]}))
        for bad in ([], {"hosts": "a.com"}, {"hosts": ["https://a.com"]}, {"hosts": ["*.a.com"]},
                    {"allow_hosts": ["A.com"]}, {"hosts": ["a.com:8080"]}, {"extra": []}, {"hosts": [1]}):
            self.assertIsNotNone(rules.config_problem(bad), bad)
            self.refused(2, rules.capture_config, {"capture": bad})

    def test_shared_with_the_plugin(self):
        self.assertEqual(rules.HOST.pattern, common.HOST.pattern)
        self.assertEqual(rules.MIN_TERM, web.MIN_TERM)
        from stdo.guard import scriptrun
        self.assertEqual(scriptrun.SHOT_NAME.pattern, cli.SHOT_NAME.pattern)

    def test_overlay_items_read_as_the_guard_reads(self):
        repo = helpers.make_repo(self.tmp)
        p = os.path.join(repo, ".claude", "studio", "local", "config.internal.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        raw = json.dumps(OVERLAY).encode("utf-8")
        with open(p, "wb") as f:
            f.write(raw)
        cfg = {"internal_overlay": "required"}
        self.assertEqual(rules.overlay_items(repo, cfg, os.environ)[0], "missing")
        d = os.path.join(paths.backup_root(), paths.repo_key(repo))
        os.makedirs(d)
        with open(os.path.join(d, "overlay.sha"), "w") as f:
            f.write(hashlib.sha256(raw).hexdigest() + "\n")
        st, hosts, terms = rules.overlay_items(repo, cfg, os.environ)
        gst, data = web.overlay(repo, cfg, os.environ)
        ghosts, gterms, _ids = web.internal_items(data)
        self.assertEqual((st, hosts, terms), (gst, ghosts, gterms))
        self.assertEqual(rules.overlay_items(repo, {}, os.environ)[0], "none")
        with open(p, "ab") as f:
            f.write(b" ")
        self.assertEqual(rules.overlay_items(repo, cfg, os.environ)[0], "missing")


# ---------------------------------------------------------------- the `capture` setting

class Setting(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.repo = helpers.make_repo(self.tmp)

    def test_template_and_protection(self):
        from stdo.commit.summary import FIXED_PROTECTED
        from stdo.guard.repos import RepoInfo
        with open(os.path.join(self.repo, ".claude", "studio", "config.json")) as f:
            cfg = json.load(f)
        self.assertEqual(cfg["capture"], {"hosts": [], "allow_hosts": []})
        self.assertIn("capture", cfg["protected_keys"])
        self.assertIn("capture", FIXED_PROTECTED)
        self.assertIn("capture", RepoInfo.protected_keys.fget(type("R", (), {"config": {}})()))
        # an older config without the key or its protected_keys entry: still protected, still settable
        del cfg["capture"]
        cfg["protected_keys"].remove("capture")
        with open(os.path.join(self.repo, ".claude", "studio", "config.json"), "w") as f:
            json.dump(cfg, f)
        p = configcmd.preview(self.repo, "capture.hosts", '["docs.thirdparty.net"]')
        self.assertTrue(p["protected"])
        self.assertEqual(p["line"], '설정 capture.hosts: (없음) → ["docs.thirdparty.net"]')

    def test_set_needs_the_answer_and_host_names(self):
        argv = ["config", "set", "capture.hosts", '["docs.thirdparty.net"]']
        with self.assertRaises(SetupError) as cm:
            configcmd.set_(self.repo, "capture.hosts", argv[3], None, argv)
        self.assertIn("needs the person's answer", str(cm.exception))
        for bad in ('["https://x.com"]', '"x.com"', '["X.com"]', '[1]'):
            with self.assertRaises(SetupError) as cm:
                configcmd.preview(self.repo, "capture.hosts", bad)
            self.assertEqual(cm.exception.code, common.USAGE, bad)
        with self.assertRaises(SetupError):
            configcmd.preview(self.repo, "capture", '{"hosts": [], "other": []}')
        self.assertTrue(configcmd.preview(self.repo, "capture.allow_hosts", '["cdn.example.net"]')["protected"])

    def test_guard_requires_the_answer(self):
        from stdo.setup import labels as sl
        self.assertTrue(sl.needs_evidence(["config", "set", "capture.hosts", "[]"], set(["capture"])))
        from stdo.guard.repos import RepoInfo
        ri = RepoInfo.__new__(RepoInfo)
        ri.config = {}
        self.assertTrue(sl.needs_evidence(["config", "set", "capture.allow_hosts", "[]"], ri.protected_keys))


# ---------------------------------------------------------------- the fake s2v capture

class Fake(StudioTestCase):
    def setUp(self):
        if not shutil.which("node"):
            if helpers.full_mode():
                raise AssertionError("--full needs node for the fake s2v CLI")
            raise unittest.SkipTest("needs node (the fake s2v CLI)")
        super().setUp()
        self.scen = os.path.join(self.tmp, "scenario.json")
        self.write_scenario({})

    def write_scenario(self, data):
        with open(self.scen, "w") as f:
            json.dump(data, f)

    def env(self, **more):
        e = dict(os.environ, STUDIO_TEST_FAKE_S2V_SCENARIO=self.scen)
        e.update(more)
        return e

    def calls(self):
        p = os.path.join(self.tmp, "calls.log")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(x) for x in f if x.strip()]


class FakeCapture(Fake):
    def node(self, *args):
        import subprocess
        return subprocess.run(["node", os.path.join(FAKE_ROOT, "packages", "cli", "dist", "main.js"), "capture"]
                              + list(args), capture_output=True, text=True, env=self.env(), cwd=self.tmp)

    def test_keys_are_a_subset_of_s2v(self):
        self.write_scenario({"capture": {"*": {
            "title": "t", "text": [{"kind": "heading", "text": "h", "ruby": [{"base": "漢", "reading": "かん"}]}],
            "images": [{"src": "https://example.com/a.png", "bytes": "png", "ext": "png"}],
            "opaque": [{"kind": "iframe", "src": None, "bbox": [0, 0, 1, 1], "inCapture": True}],
            "blocked": [{"url": "https://cdn.x.net/a.js", "reason": "host"}],
            "websockets": [{"url": "wss://example.com/s", "host": "example.com"}]}}})
        out = os.path.join(self.tmp, "o")
        r = self.node("https://example.com/a", "--out", os.path.join(out, "a.png"), "--text",
                      os.path.join(out, "a.json"), "--assets-dir", os.path.join(out, "assets"), "--allow-host",
                      "cdn.example.net", "--allow-host", "x.example.net", "--timeout", "30")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(out, "a.json")) as f:
            data = json.load(f)
        self.assertLessEqual(set(data), CAPTURE_JSON)
        self.assertEqual(set(crun.JSON_KEYS), CAPTURE_JSON)
        for key, keys in (("images", IMAGE_KEYS), ("opaque", OPAQUE_KEYS), ("blocked", BLOCKED_KEYS),
                          ("websockets", WS_KEYS), ("text", TEXT_KEYS)):
            self.assertTrue(data[key], key)
            for x in data[key]:
                self.assertLessEqual(set(x), keys, key)
        for t in data["text"]:
            for rb in t["ruby"]:
                self.assertLessEqual(set(rb), RUBY_KEYS)
        sha = data["images"][0]["sha256"]
        self.assertTrue(os.path.isfile(os.path.join(out, "assets", sha + ".png")))
        with open(os.path.join(out, "a.png"), "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")

    def test_usage(self):
        for args in (["https://93.184.216.34/", "--out", "a.png"], ["https://example.com/", "--out", "a.png", "--x", "1"],
                     ["https://example.com/"], ["ftp://example.com/", "--out", "a.png"],
                     ["https://u:p@example.com/", "--out", "a.png"]):
            self.assertEqual(self.node(*args).returncode, 2, args)

    def test_helpers_never_run_the_real_capture(self):
        with self.assertRaises(AssertionError):
            helpers.run_s2v(self, ["capture", "https://example.com/", "--out", "a.png"])
        with self.assertRaises(AssertionError):
            helpers.run_s2v(self, ["--quiet", "capture", "https://example.com/"])
        with self.assertRaises(AssertionError):  # review 1 n1: anywhere in the arguments
            helpers.run_s2v(self, ["--", "capture", "https://example.com/"])


class Shot(Fake):
    """capture.py shot through the fake s2v in a Studio repository (overlay present)."""

    def setUp(self):
        super().setUp()
        store.enable_writes()
        self.repo = helpers.make_repo(self.tmp, s2v=FAKE_ROOT)
        cp = os.path.join(self.repo, ".claude", "studio", "config.json")
        with open(cp) as f:
            cfg = json.load(f)
        cfg.update(CFG)
        with open(cp, "w") as f:
            json.dump(cfg, f)
        self.overlay(OVERLAY)
        self.vdir = self.video("v1", "public")
        self.ldir = self.video("l1", "local")

    def overlay(self, data):
        p = os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        raw = json.dumps(data).encode("utf-8")
        with open(p, "wb") as f:
            f.write(raw)
        d = os.path.join(paths.backup_root(), paths.repo_key(self.repo))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "overlay.sha"), "w") as f:
            f.write(hashlib.sha256(raw).hexdigest() + "\n")

    def video(self, vid, location):
        sub = ("local", "videos") if location == "local" else ("videos",)
        vdir = os.path.join(self.repo, "studio", *sub, vid)
        os.makedirs(vdir)
        st = F.state()
        st["video"] = vid
        if location == "local":
            st.update(location="local", kind="onboarding", scope="internal")
        store.create(vdir, st)
        return vdir

    def cap(self, *argv, **env):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), env=self.env(**env), cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def shots(self, vdir=None):
        with open(os.path.join(vdir or self.vdir, "work", "captures.json")) as f:
            return json.load(f)["shots"]

    def test_ok(self):
        self.assertEqual(self.cap("shot", "v1", "hero", "--url", "https://example.com/a", "--selector", "main",
                                  "--width", "1080", "--height", "1920"), 0, self.err)
        self.assertIn("captured hero: studio/videos/v1/assets/capture-hero.png (example.com)", self.out)
        png = os.path.join(self.vdir, "assets", "capture-hero.png")
        js = os.path.join(self.vdir, "work", "captures", "hero.json")
        rec = self.shots()["hero"]
        self.assertEqual((rec["status"], rec["url"], rec["selector"], rec["width"], rec["height"], rec["idle"]),
                         ("ok", "https://example.com/a", "main", 1080, 1920, True))
        self.assertEqual((rec["png"], rec["json"]), ("assets/capture-hero.png", "work/captures/hero.json"))
        self.assertEqual(rec["png_sha"], hashlib.sha256(open(png, "rb").read()).hexdigest())
        self.assertEqual(rec["json_sha"], hashlib.sha256(open(js, "rb").read()).hexdigest())
        argv = self.calls()[-1]["argv"]
        main_js = os.path.join(FAKE_ROOT, "packages", "cli", "dist", "main.js")
        self.assertEqual(argv[:2], ["capture", "https://example.com/a"])
        self.assertIn("--selector=main", argv)  # one word: a value is never read as a flag
        self.assertEqual(argv[argv.index("--timeout") + 1], "30")
        self.assertEqual([argv[i + 1] for i, a in enumerate(argv) if a == "--allow-host"], ["cdn.example.net"])
        self.assertNotIn("--assets-dir", argv)
        self.assertTrue(os.path.isfile(main_js))
        # no temporary folder left, the lock file only
        self.assertEqual(sorted(os.listdir(os.path.join(self.vdir, "work", "captures"))), ["hero.json"])
        # a third-party page of capture.hosts for the public video
        self.assertEqual(self.cap("shot", "v1", "doc", "--url", "https://docs.thirdparty.net/x"), 0, self.err)

    def test_refusals_before_running(self):
        for argv, code in ((["shot", "v1", "h", "--url", "https://example.com/a?x=1"], 2),
                           (["shot", "v1", "h", "--url", "https://example.com/a#b"], 2),
                           (["shot", "v1", "h", "--url", "https://example.com/" + "a" * 201], 2),
                           (["shot", "v1", "h", "--url", "https://wiki.corp.example/a"], 3),
                           (["shot", "v1", "h", "--url", "https://example.com/bluebird"], 3),
                           (["shot", "v1", "h", "--url", "https://example.com/a", "--selector", "#bluebird"], 3),
                           (["shot", "v1", "h", "--url", "https://example.com/a", "--selector", "a;b"], 2),
                           (["shot", "v1", "h", "--url", "https://example.com/a", "--selector", "a{b}"], 2),
                           (["shot", "v1", "h", "--url", "https://example.com/a", "--selector", "a[x='y']"], 2),
                           (["shot", "l1", "h", "--url", "https://docs.thirdparty.net/x"], 3),
                           (["shot", "v1", "h", "--url", "https://other.net/x"], 3),
                           (["shot", "v1", "h", "--url", "https://example.com/a", "--width", "100"], 2),
                           (["shot", "v1", "H", "--url", "https://example.com/a"], 2),
                           (["shot", "v1", "h"], 2), (["shot", "v1", "h", "--url", "https://example.com/a", "--x", "1"], 2),
                           (["shot", "nosuch", "h", "--url", "https://example.com/a"], 2),
                           (["fetch", "v1"], 2), (["source", "v1"], 2), (["recheck", "v1"], 2),
                           (["source", "v1", "--url", "https://example.com/a"], 2)):
            self.assertEqual(self.cap(*argv), code, (argv, self.err))
        self.assertEqual(self.calls(), [])
        self.assertFalse(os.path.exists(os.path.join(self.vdir, "work", "captures.json")))
        self.cap("source", "v1")
        self.assertIn("has no URL source", self.err)

    def test_no_sandbox_refused(self):
        for v in ("1", "0", ""):
            self.assertEqual(self.cap("shot", "v1", "h", "--url", "https://example.com/a",
                                      S2V_CAPTURE_NO_SANDBOX=v), 2)
            self.assertIn("browser sandbox", self.err)
        self.assertEqual(self.calls(), [])
        self.assertNotIn(crun.NO_SANDBOX, crun.child_env({crun.NO_SANDBOX: "1", "A": "b"}))

    def test_overlay_missing(self):
        os.remove(os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json"))
        self.assertEqual(self.cap("shot", "v1", "h", "--url", "https://example.com/a"), 4)
        self.assertIn("overlay is missing", self.err)
        self.assertEqual(self.calls(), [])

    def test_redirects(self):
        self.write_scenario({"capture": {"https://example.com/a": {"url": "https://www.example.com/a"},
                                         "https://example.com/b": {"url": "https://evil.example.net/b"},
                                         "https://example.com/c": {"url": "http://example.com/c"},
                                         "https://example.com/d": {"url": "https://example.com/d/"}}})
        for n in "abc":
            self.assertEqual(self.cap("shot", "v1", n, "--url", "https://example.com/" + n), 1, n)
            self.assertIn("capture the final address", self.err)
            self.assertEqual(self.shots()[n]["status"], "unusable")
            self.assertFalse(os.path.exists(os.path.join(self.vdir, "assets", "capture-%s.png" % n)))
        self.assertEqual(self.cap("shot", "v1", "d", "--url", "https://example.com/d"), 0, self.err)

    def test_s2v_exit_codes(self):
        self.write_scenario({"capture": {"https://example.com/404": {"exit": 1, "status": 404,
                                                                      "stderr": "the page answered 404"},
                                         "https://example.com/bad": {"exit": 2, "stderr": "usage: x"},
                                         "https://example.com/sig": {"signal": "SIGTERM"}}})
        # an earlier picture of the name goes when the new run is not usable
        self.assertEqual(self.cap("shot", "v1", "p", "--url", "https://example.com/a"), 0, self.err)
        self.assertEqual(self.cap("shot", "v1", "p", "--url", "https://example.com/404"), 1)
        self.assertIn("the page answered 404", self.err)
        self.assertEqual((self.shots()["p"]["status"], self.shots()["p"]["reason"]), ("unusable", "the page answered 404"))
        self.assertFalse(os.path.exists(os.path.join(self.vdir, "assets", "capture-p.png")))
        self.assertFalse(os.path.exists(os.path.join(self.vdir, "work", "captures", "p.json")))
        before = self.shots()
        self.assertEqual(self.cap("shot", "v1", "q", "--url", "https://example.com/bad"), 2)
        self.assertIn("Studio defect", self.err)
        self.assertEqual(self.cap("shot", "v1", "q", "--url", "https://example.com/sig"), 1)
        self.assertIn("interrupted", self.err)
        self.assertEqual(self.shots(), before)  # nothing recorded for either
        self.assertEqual(os.listdir(os.path.join(self.vdir, "work", "captures")), [])

    def test_idle_and_blocked(self):
        self.write_scenario({"capture": {"https://example.com/slow": {
            "idle": False, "blocked": [{"url": "https://cdn.other.net/a.js", "reason": "not allowed"},
                                       {"url": "https://cdn.other.net/b.js", "reason": "not allowed"}]}}})
        self.assertEqual(self.cap("shot", "v1", "slow", "--url", "https://example.com/slow"), 0, self.err)
        self.assertIn("warning: the page did not settle", self.out)
        self.assertEqual(self.out.count("blocked: cdn.other.net"), 1)
        self.assertIn("capture.allow_hosts", self.out)
        rec = self.shots()["slow"]
        self.assertEqual((rec["idle"], rec["blocked"], len(rec["warnings"])), (False, ["cdn.other.net"], 1))
        self.assertEqual(len(self.calls()), 1)  # a picture is not retried

    def test_internal_video(self):
        self.assertEqual(self.cap("shot", "l1", "hero", "--url", "https://example.com/a"), 0, self.err)
        self.assertTrue(os.path.isfile(os.path.join(self.ldir, "assets", "capture-hero.png")))
        self.assertIn("studio/local/videos/l1/assets/capture-hero.png", self.out)

    def test_one_capture_per_video(self):
        with store.Lock(os.path.join(self.vdir, "work", ".capture.lock"), wait=0.0):
            self.assertEqual(self.cap("shot", "v1", "h", "--url", "https://example.com/a"), 5)
            self.assertEqual(self.cap("shot", "l1", "h", "--url", "https://example.com/a"), 0, self.err)

    def test_links_are_not_followed(self):
        os.symlink(self.tmp, os.path.join(self.vdir, "assets"))
        self.assertEqual(self.cap("shot", "v1", "h", "--url", "https://example.com/a"), 2)
        self.assertIn("symbolic link", self.err)

    def test_no_s2v_path(self):
        os.remove(machine.path(self.repo))
        self.assertEqual(self.cap("shot", "v1", "h", "--url", "https://example.com/a"), 2)

    def test_entry_script(self):
        import subprocess
        r = subprocess.run(["python3", "-B", os.path.join(helpers.SCRIPTS, "capture.py"), "shot", "v1", "hero",
                            "--url", "https://example.com/a"], cwd=self.repo, env=self.env(), capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.shots()["hero"]["status"], "ok")


class PageRun(Fake):
    """The source rules of run.capture (`page=True`; wired to `capture.py source|recheck` with URL sources)."""

    def go(self, scen):
        self.write_scenario({"capture": {"https://example.com/p": scen}})
        out = os.path.join(self.tmp, "o")
        os.makedirs(out, exist_ok=True)
        return crun.capture(FAKE_ROOT, "https://example.com/p", "example.com", os.path.join(out, "c.png"),
                            os.path.join(out, "c.json"), self.env(), self.tmp, assets_dir=os.path.join(out, "assets"),
                            page=True)

    def timeouts(self):
        return [c["argv"][c["argv"].index("--timeout") + 1] for c in self.calls()]

    def test_settled(self):
        r = self.go({})
        self.assertEqual((r["status"], r["attempts"], self.timeouts()), ("ok", 1, ["30"]))
        self.assertIn("--assets-dir", self.calls()[0]["argv"])

    def test_retry_once(self):
        r = self.go([{"idle": False}, {"idle": True}])
        self.assertEqual((r["status"], r["attempts"], self.timeouts()), ("ok", 2, ["30", "60"]))

    def test_unreachable(self):
        r = self.go([{"idle": False}, {"idle": False}])
        self.assertEqual((r["status"], r["attempts"]), ("unusable", 2))
        self.assertIn("unreachable", r["reason"])
        os.remove(os.path.join(self.tmp, "calls.log"))
        r = self.go({"contentHash": None})
        self.assertEqual((r["status"], r["attempts"]), ("unusable", 1))
        self.assertIn("contentHash", r["reason"])

    def test_judge(self):
        self.assertEqual(crun.judge("example.com", -15, None, "")["status"], "interrupted")
        self.assertEqual(crun.judge("example.com", 130, None, "")["status"], "interrupted")
        self.assertEqual(crun.judge("example.com", 3, None, "")["status"], "defect")
        self.assertEqual(crun.judge("example.com", 0, None, "")["status"], "defect")
        self.assertEqual(crun.judge("example.com", 0, {"url": "https://EXAMPLE.com/x"}, "")["status"], "ok")
        self.assertEqual(crun.judge("example.com", 0, {"url": "https://example.com.evil.net/"}, "")["status"],
                         "unusable")


if __name__ == "__main__":
    unittest.main()
