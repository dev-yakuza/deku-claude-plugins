"""URL sources (m2-plan §6): `begin --url` (public kinds, public_domains, the overlay's hosts and terms), capture.py
source and recheck through the fake s2v capture (the copy's files, capture-files.json, page.md, a page that is not
usable, a signal), page.md's rendering (golden, every TextKind, each escape), record-source's URL branch (a tampered
copy refused, the ① capture line), resolve_assets and check_scope for page pictures (img-<sha12>, floors by host, no
bytes, WebP, merged refs, an overlay host), the analyst's excerpts and ruby pairs against page.md and page-ruby.json,
record-recheck (a changed file, an old number), the promotion (a tampered recheck, a cut-short promotion finished by
a rerun, two promotions before an approval, the classes kept across a reordered page), source-diff.txt (bytes and the
gate's hash12), the folders kept, and the commit's recheck rule (24 hours counted at staging, never in the hook). No
network: the fake s2v only."""

import contextlib
import datetime
import hashlib
import inspect
import io
import json
import os
import shutil
import unittest
from unittest import mock

import helpers
import state_fixtures as F
from approve_base import ApproveCase
from helpers import StudioTestCase
from stdo import paths
from stdo.capture import cli as ccli, files
from stdo.claims import cli as claims_cli
from stdo.commit import video as cvideo
from stdo.source import cli as scli_src, page
from stdo.state import cli, collect, labels, schema, shown, store, urlsource
from stdo.state.collect import CollectError, Providers

FAKE_ROOT = os.path.join(helpers.HERE, "drivers", "fake_s2v_cli")
URL = "https://example.com/posts/airport"
CFG = {"public_domains": ["example.com", "blog.example.org"], "internal_overlay": "required",
       "capture": {"hosts": [], "allow_hosts": []}}
OVERLAY = {"internal": {"hosts": ["corp.example", "cdn.example.com"], "terms": ["Bluebird"],
                        "sources": [{"url": "https://example.com/internal/memo"}]}}
PNG = ("89504e470d0a1a0a0000000d4948445200000001000000010800000000"
       "3a7e9b550000000a4944415478da6368000000820081da45083b0000000049454e44ae426082")
JPEG = "ffd8ffc0001108000100010301220002110103110100ffd9"
WEBP = "52494646" + "1a000000" + "57454250" + "5650382000000000"


def sha_hex(h):
    return hashlib.sha256(bytes.fromhex(h)).hexdigest()


TEXT = [{"kind": "heading", "text": "공항 단어"},
        {"kind": "paragraph", "text": "The cat sat on the mat. It was warm.",
         "ruby": [{"base": "空港", "reading": "くうこう"}]},
        {"kind": "list-item", "text": "- dash first"}]


def page_result(text=TEXT, images=None, **more):
    r = {"title": "Airport words", "lang": "ko", "text": text,
         "images": images if images is not None else [{"src": "https://example.com/a.png", "hex": PNG, "alt": "a"}]}
    r.update(more)
    return r


def need_node():
    if shutil.which("node"):
        return
    if helpers.full_mode():
        raise AssertionError("--full needs node for the fake s2v CLI")
    raise unittest.SkipTest("needs node (the fake s2v CLI)")


# ---------------------------------------------------------------- page.md (pure)

class Page(unittest.TestCase):
    def test_golden(self):
        data = {"url": "https://example.com/a", "title": "# T <x>", "text": [
            {"kind": "heading", "text": "H1\nmore"}, {"kind": "paragraph", "text": "- not a list & 1. x\n2. y"},
            {"kind": "list-item", "text": "a\nb"}, {"kind": "quote", "text": "q\nr",
                                                    "ruby": [{"base": "空港", "reading": "くうこう"}]},
            {"kind": "code", "text": "```js"}, {"kind": "table-cell", "text": "| c"}, {"kind": "caption", "text": "cap"},
            {"kind": "figcaption", "text": "+ fig"}, {"kind": "weird", "text": "* odd"}, {"kind": "paragraph", "text": " "},
            {"kind": "paragraph", "text": "=== ~~~ 3) z"}]}
        md, ruby = page.render(data)
        self.assertEqual(md, "<!-- url: https://example.com/a -->\n\n# \\# T &lt;x&gt;\n\n## H1 more\n\n"
                             "\\- not a list &amp; 1. x\n\\2. y\n\n- a\n  b\n\n> q\n> r\n\n    \\```js\n\n| \\| c\n\n"
                             "cap\n\n\\+ fig\n\n\\* odd\n\n\\=== ~~~ 3) z\n")
        self.assertEqual(ruby, '{\n  "3": [["空港", "くうこう"]]\n}\n')
        self.assertEqual(page.render(data), (md, ruby))  # the same JSON, the same bytes
        self.assertEqual(page.ruby_pairs(ruby), {("空港", "くうこう")})
        for kind in ("heading", "paragraph", "list-item", "quote", "code", "table-cell", "caption", "figcaption"):
            self.assertIn(kind, page.KIND_PREFIX)  # every TextKind of s2v's extract.ts

    def test_comment_and_controls(self):
        md, ruby = page.render({"url": "https://example.com/a-->b", "title": "", "text": [
            {"kind": "paragraph", "text": "a\x00b\tc"}]})
        self.assertTrue(md.startswith("<!-- url: https://example.com/a-%2D%3Eb -->\n\na b c\n"), md)
        self.assertEqual(ruby, "{}\n")
        self.assertEqual(md.count("-->"), 1)

    def test_escapes(self):
        for line, want in (("# h", "\\# h"), ("- l", "\\- l"), ("+ p", "\\+ p"), ("* s", "\\* s"),
                           ("> q", "&gt; q"), ("1. n", "\\1. n"), ("```", "\\```"), ("a <b> & c", "a &lt;b&gt; &amp; c"),
                           ("plain", "plain"), ("2026년", "2026년")):
            self.assertEqual(page.escape_line(line), want, line)


# ---------------------------------------------------------------- a repository with a URL video

class URLCase(StudioTestCase):
    def setUp(self):
        need_node()
        super().setUp()
        store.enable_writes()
        self.repo = helpers.make_repo(self.tmp, s2v=FAKE_ROOT)
        cp = os.path.join(self.repo, ".claude", "studio", "config.json")
        with open(cp) as f:
            cfg = json.load(f)
        cfg.update(CFG)
        with open(cp, "w") as f:
            json.dump(cfg, f, indent=2)
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "public domains")
        self.overlay(OVERLAY)
        self.scen = os.path.join(self.tmp, "scenario.json")
        self.scenario({URL: page_result()})
        self.ver = {"id": "0.13.2+abc", "version": "0.13.2", "commit": "c0ffee", "dirty": False, "stale_build": False}
        self.providers = Providers(version=lambda ctx: dict(self.ver))
        self.vdir = os.path.join(self.repo, "studio", "videos", "v1")
        self.sdir = os.path.join(self.vdir, "work", "source")

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

    def scenario(self, capture):
        with open(self.scen, "w") as f:
            json.dump({"capture": capture}, f)

    def env(self):
        return dict(os.environ, STUDIO_TEST_FAKE_S2V_SCENARIO=self.scen)

    def st(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), providers=self.providers, cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def cap(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ccli.main(list(argv), env=self.env(), cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def tool(self, fn, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fn(list(argv), cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def calls(self):
        p = os.path.join(self.tmp, "calls.log")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(x) for x in f if x.strip()]

    def state(self):
        return store.read_state(self.vdir)

    def edit_state(self, fn):
        store.write(self.vdir, {"event": "test"}, fn)

    def begun(self, kind="sns"):
        self.assertEqual(self.st("begin", "v1", "--url", URL, "--kind", kind), 0, self.err)

    def sourced(self, analyst=None):
        """capture.py source → record-source → resolve_assets → the analyst's source.md → check_scope → record-source."""
        self.begun()
        self.assertEqual(self.cap("source", "v1"), 0, self.err)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        self.assertEqual(self.tool(scli_src.resolve_main, "v1"), 0, self.err)
        self.write_analyst(analyst)
        self.assertEqual(self.tool(scli_src.scope_main, "v1"), 0, self.err)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)

    def write_analyst(self, classes=None, extra=""):
        data = json.load(open(os.path.join(self.vdir, "work", "assets.json")))
        cls = classes if classes is not None else {i["id"]: {"class": "diagram", "reason": "r"} for i in data["images"]}
        with open(os.path.join(self.vdir, "work", "source.md"), "w") as f:
            f.write("# Source\n\n## Claims\n- %s: c\n  > The cat sat on the mat.\n\n## Ruby pairs\n%s\n## Images\n"
                    "<!-- studio:images -->\n```json\n%s\n```\n<!-- /studio:images -->\n"
                    % (F.claim_id("The cat sat on the mat."), extra, json.dumps(cls)))

    def recheck(self, result=None, record=True):
        if result is not None:
            self.scenario({URL: result})
        code = self.cap("recheck", "v1")
        n = int(self.out.strip().splitlines()[-1].split()[-1])
        if record:
            self.assertEqual(self.st("record-recheck", "v1", str(n)), 0, self.err)
        return code, n

    def approve_1(self):
        """Gate ① approved on the current copy (what approve 1 records, written directly)."""
        def fn(s):
            h = s["source"]["frozen_hash"]
            s["langs"]["ko"]["approved"]["1"] = {"tuple": {"source_hash": h}, "approved_by": "human"}
            s["source"]["approved_hash"] = h
        self.edit_state(fn)


class Begin(URLCase):
    def test_begin_url(self):
        self.begun()
        st = self.state()
        self.assertEqual(st["source"], {"kind": "url", "url": URL, "host": "example.com", "images": [],
                                        "frozen_hash": None, "capture": None, "rechecks": [], "approved_hash": None})
        self.assertEqual((st["kind"], st["scope"], st["location"]), ("sns", "public", "public"))
        self.assertIn("capture.py source v1", self.out)

    def test_refusals(self):
        for argv, code in ((["--url", "https://other.net/a", "--kind", "sns"], 2),         # not a public domain
                           (["--url", "https://example.com/bluebird", "--kind", "sns"], 2),  # an overlay term
                           (["--url", "https://example.com/%62luebird", "--kind", "sns"], 2),
                           (["--url", URL, "--source", "README.md", "--kind", "sns"], 2),
                           (["--url", URL, "--kind", "onboarding"], 2), (["--url", URL, "--kind", "explainer"], 2),
                           (["--url", URL + "#top", "--kind", "sns"], 2),
                           (["--url", "https://example.com/a?token=x", "--kind", "sns"], 2),
                           (["--url", "http://example.com/a", "--kind", "sns"], 2),
                           (["--kind", "sns"], 2)):
            self.assertEqual(self.st("begin", "v9", *argv), code, (argv, self.err))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "studio", "videos", "v9")))
        os.remove(os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json"))
        self.assertEqual(self.st("begin", "v9", "--url", URL, "--kind", "sns"), 4)
        self.assertIn("overlay is missing", self.err)

    def test_an_older_studio_refuses_the_kind(self):
        self.begun()
        st = dict(self.state(), source={"kind": "notion", "url": URL})
        with self.assertRaises(CollectError):
            collect.default_source({"repo": self.repo, "vdir": self.vdir}, st)


class Source(URLCase):
    def test_capture_and_record(self):
        self.begun()
        self.assertEqual(self.cap("source", "v1"), 0, self.err)
        names = sorted(os.listdir(self.sdir))
        self.assertEqual(names, ["assets", "capture-files.json", "capture.json", "capture.png", "page-ruby.json",
                                 "page.md"])
        rec, why = files.verify(self.sdir)
        self.assertIsNone(why)
        self.assertEqual(rec["url"], URL)
        self.assertEqual(sorted(rec["files"]), ["assets/%s.png" % sha_hex(PNG), "capture.json", "capture.png",
                                               "page-ruby.json", "page.md"])
        with open(os.path.join(self.sdir, "page.md")) as f:
            md = f.read()
        self.assertEqual(md, "<!-- url: %s -->\n\n# Airport words\n\n## 공항 단어\n\n"
                             "The cat sat on the mat. It was warm.\n\n- \\- dash first\n" % URL)
        argv = self.calls()[-1]["argv"]
        self.assertIn("--assets-dir", argv)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        st = self.state()
        cj = json.load(open(os.path.join(self.sdir, "capture.json")))
        self.assertEqual(st["source"]["frozen_hash"], cj["contentHash"])
        self.assertEqual(st["source"]["copy_sha"], files.sha(os.path.join(self.sdir, "page.md")))
        cap = st["source"]["capture"]
        self.assertEqual((cap["url"], cap["blocked"], cap["opaque_in_capture"], cap["s2v"]),
                         (URL, 0, 0, "0.13.2+abc"))
        line = labels.source_commit_lines(st)[0]
        self.assertTrue(line.startswith("원본 페이지 캡처: %s · %s" % (URL, cap["at"])), line)
        self.assertIn("%s — put this line in the ① question" % line, self.out)
        # the router reads the frozen copy without fetching
        live, text = collect.default_source({"repo": self.repo, "vdir": self.vdir}, st)
        self.assertEqual((live, text), (cj["contentHash"], md))
        n = len(self.calls())
        self.assertEqual(self.st("record-source", "v1", "--url", URL), 2)  # the address is begin's
        self.assertEqual(len(self.calls()), n)

    def test_tampered_copy(self):
        self.begun()
        self.assertEqual(self.cap("source", "v1"), 0, self.err)
        with open(os.path.join(self.sdir, "page.md"), "a") as f:
            f.write("an injected line\n")
        self.assertEqual(self.st("record-source", "v1"), 1)
        self.assertIn("changed after capture.py wrote them", self.err)
        os.remove(os.path.join(self.sdir, files.NAME))
        self.assertEqual(self.st("record-source", "v1"), 1)
        # a recorded copy changed later: the router refuses until record-source again
        self.assertEqual(self.cap("source", "v1"), 0, self.err)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        self.scenario({URL: page_result(text=[{"kind": "paragraph", "text": "Another text."}])})
        self.assertEqual(self.cap("source", "v1"), 0, self.err)  # before ①: a new capture is allowed
        with self.assertRaises(CollectError) as cm:
            collect.default_source({"repo": self.repo, "vdir": self.vdir}, self.state())
        self.assertIn("run state.py record-source v1 again", str(cm.exception))

    def test_not_usable(self):
        self.begun()
        for scen, code, why in (({"exit": 1, "stderr": "the page answered 404"}, 1, "404"),
                                ([{"idle": False}, {"idle": False}], 1, "unreachable"),
                                (dict(page_result(), contentHash=None), 1, "contentHash"),
                                ({"url": "https://www.example.com/posts/airport"}, 1, "capture the final address"),
                                ({"signal": "SIGTERM"}, 1, "interrupted"), ({"exit": 2}, 2, "Studio defect")):
            for p in (os.path.join(self.tmp, "calls.log"), os.path.join(self.sdir, "last-attempt.json")):
                if os.path.exists(p):
                    os.remove(p)
            self.scenario({URL: scen})
            self.assertEqual(self.cap("source", "v1"), code, scen)
            self.assertIn(why, self.err, scen)
            left = [x for x in os.listdir(self.sdir) if x != ".capture.lock"]
            self.assertEqual(left, [] if code != 1 or why == "interrupted" else ["last-attempt.json"], scen)
            if left:
                self.assertIn(why, json.load(open(os.path.join(self.sdir, "last-attempt.json")))["reason"], scen)
                self.assertNotIn("last-attempt.json", files.listing(self.sdir))  # never part of a copy
        self.scenario({URL: page_result(blocked=[{"url": "https://cdn.other.net/a.js", "reason": "host"}],
                                        opaque=[{"kind": "iframe", "src": None, "bbox": [0, 0, 1, 1],
                                                 "inCapture": True}])})
        self.assertEqual(self.cap("source", "v1"), 0, self.err)
        self.assertIn("blocked: cdn.other.net", self.out)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        cap = self.state()["source"]["capture"]
        self.assertEqual((cap["blocked"], cap["opaque_in_capture"]), (1, 1))

    def test_refused_after_gate_1(self):
        self.sourced()
        self.approve_1()
        n = len(self.calls())
        self.assertEqual(self.cap("source", "v1"), 3)
        self.assertIn("capture.py recheck v1", self.err)
        self.assertEqual(len(self.calls()), n)

    def test_not_a_url_source(self):
        vdir = os.path.join(self.repo, "studio", "videos", "md")
        os.makedirs(vdir)
        s = F.state()
        s["video"] = "md"
        store.create(vdir, s)
        self.assertEqual(self.cap("source", "md"), 2)
        self.assertIn("begin --url", self.err)
        self.assertEqual(self.st("record-source", "md", "--from-recheck", "1"), 2)


class Assets(URLCase):
    def test_floors_bytes_formats_and_refs(self):
        imgs = [{"src": "https://example.com/a.png", "hex": PNG, "alt": "own"},
                {"src": "https://img.other.net/b.jpg", "hex": JPEG, "alt": "theirs"},
                {"src": "https://example.com/a-copy.png", "hex": PNG, "alt": ""},  # the same bytes: one entry
                {"src": "https://example.com/c.webp", "hex": WEBP, "ext": "webp"},
                {"src": "https://example.com/d.png"},                                # no bytes
                {"src": "data:image/png;base64,AAAA", "hex": JPEG + "00"},
                {"src": "https://cdn.example.com/e.png", "hex": PNG + "00"}]          # an overlay host
        self.scenario({URL: page_result(images=imgs)})
        self.begun()
        self.assertEqual(self.cap("source", "v1"), 0, self.err)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        self.assertEqual(self.tool(scli_src.resolve_main, "v1"), 0, self.err)
        data = json.load(open(os.path.join(self.vdir, "work", "assets.json")))
        by = {i["ref"]: i for i in data["images"]}
        self.assertEqual(len(data["images"]), 6)
        a = by["https://example.com/a.png"]
        self.assertEqual((a["id"], a["status"], a["floor"], a["script_src"]),
                         ("img-" + sha_hex(PNG)[:12], "ok", "public", "assets/src-%s.png" % sha_hex(PNG)[:12]))
        self.assertEqual([r["src"] for r in a["refs"]], ["https://example.com/a.png", "https://example.com/a-copy.png"])
        self.assertEqual(a["resolved"], "studio/videos/v1/assets/src-%s.png" % sha_hex(PNG)[:12])
        with open(os.path.join(self.vdir, "assets", "src-%s.png" % sha_hex(PNG)[:12]), "rb") as f:
            self.assertEqual(f.read(), bytes.fromhex(PNG))
        b = by["https://img.other.net/b.jpg"]
        self.assertEqual((b["status"], b["floor"], b["script_src"]), ("ok", "third-party",
                                                                      "assets/src-%s.jpg" % sha_hex(JPEG)[:12]))
        self.assertEqual((by["https://example.com/c.webp"]["status"], by["https://example.com/c.webp"]["reason"]),
                         ("unusable", "format"))
        d = by["https://example.com/d.png"]
        self.assertEqual((d["status"], d["reason"], d["sha256"]), ("unusable", "no-bytes", None))
        self.assertEqual(by["data:image/png;base64,AAAA"]["floor"], "unknown")
        self.assertEqual(self.tool(scli_src.scope_main, "v1"), 0, self.out + self.err)  # no source.md: all unknown
        self.write_analyst()
        self.assertEqual(self.tool(scli_src.scope_main, "v1"), 0, self.err)
        data = json.load(open(os.path.join(self.vdir, "work", "assets.json")))
        by = {i["ref"]: i for i in data["images"]}
        self.assertEqual((by["https://example.com/a.png"]["scope"], by["https://img.other.net/b.jpg"]["scope"]),
                         ("public", "third-party"))
        e = by["https://cdn.example.com/e.png"]
        self.assertEqual((e["internal"], e["status"], e["reason"]), (True, "unusable", "internal"))
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        st = self.state()
        data_img = by["data:image/png;base64,AAAA"]  # usable, at the scope unknown (no host to tell)
        self.assertEqual((data_img["status"], data_img["scope"]), ("ok", "unknown"))
        self.assertEqual(sorted(st["source"]["images"]), sorted([a["resolved"], b["resolved"], data_img["resolved"]]))
        self.assertIsNotNone(st["source"]["assets_sha"])

    def test_scope_refuses_an_internal_page(self):
        self.begun()
        self.assertEqual(self.cap("source", "v1"), 0, self.err)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        self.assertEqual(self.tool(scli_src.resolve_main, "v1"), 0, self.err)
        self.overlay({"internal": {"sources": [{"url": URL}]}})
        self.assertEqual(self.tool(scli_src.scope_main, "v1"), 1)
        self.assertIn("internal source of the overlay", self.err)
        self.overlay({"internal": {"terms": ["airport"]}})
        self.assertEqual(self.tool(scli_src.scope_main, "v1"), 1)
        self.assertIn("in-house term", self.err)
        os.remove(os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json"))
        self.assertEqual(self.tool(scli_src.scope_main, "v1"), 4)


class Analyst(URLCase):
    def test_excerpts_and_ruby(self):
        self.sourced()
        argv = ["v1", "--source"]
        self.write_analyst(extra="- 空港 → くうこう\n")
        self.assertEqual(self.tool(claims_cli.main, *argv), 0, self.out)
        self.write_analyst(extra="- 空港 → くうこう\n- 出口 → でぐち\n")
        self.assertEqual(self.tool(claims_cli.main, *argv), 1)
        self.assertIn("ruby pair 出口 → でぐち is not a reading the page gives", self.out)
        with open(os.path.join(self.vdir, "work", "source.md"), "w") as f:
            f.write("## Claims\n- %s: c\n  > Not on the page.\n" % F.claim_id("Not on the page."))
        self.assertEqual(self.tool(claims_cli.main, *argv), 1)


class Recheck(URLCase):
    def test_record(self):
        self.sourced()
        h0 = self.state()["source"]["frozen_hash"]
        code, n = self.recheck()
        self.assertEqual((code, n), (0, 1))
        self.assertIn("the page is as the recorded copy", self.out)
        self.assertEqual(sorted(os.listdir(os.path.join(self.sdir, "recheck-1"))),
                         ["assets", "capture-files.json", "capture.json", "capture.png", "page-ruby.json", "page.md",
                          "result.json"])
        r = self.state()["source"]["rechecks"][0]
        self.assertEqual((r["n"], r["hash"], r["reachable"]), (1, h0, True))
        self.assertEqual(self.st("record-recheck", "v1", "1"), 3)  # not above the last one
        # a changed file
        code, n = self.recheck(record=False)
        with open(os.path.join(self.sdir, "recheck-%d" % n, "page.md"), "a") as f:
            f.write("x\n")
        self.assertEqual(self.st("record-recheck", "v1", str(n)), 1)
        self.assertIn("changed after capture.py wrote them", self.err)
        # unreachable: recorded, no hash
        code, n = self.recheck([{"idle": False}, {"idle": False}])
        self.assertEqual(code, 1)
        last = self.state()["source"]["rechecks"][-1]
        self.assertEqual((last["n"], last["reachable"], last["hash"]), (n, False, None))
        self.assertIn("could not be read", self.out)
        # a changed page: the promotion line
        code, n = self.recheck(page_result(text=[{"kind": "paragraph", "text": "The cat sat on the mat."}]))
        self.assertIn("record-source v1 --from-recheck %d" % n, self.out)
        self.assertEqual(self.st("record-recheck", "v1", "x"), 2)
        self.assertEqual(self.st("record-recheck", "v1"), 2)

    def test_needs_a_recorded_source(self):
        self.begun()
        self.assertEqual(self.cap("recheck", "v1"), 2)
        self.assertIn("record-source", self.err)


class Promote(URLCase):
    CHANGED = [{"kind": "heading", "text": "공항 단어"},
               {"kind": "paragraph", "text": "The cat sat on the mat. It was warm. It rained."}]

    def promote(self, n):
        return self.st("record-source", "v1", "--from-recheck", str(n))

    def test_promotion(self):
        self.sourced()
        self.approve_1()
        h0 = self.state()["source"]["frozen_hash"]
        old_md = open(os.path.join(self.sdir, "page.md")).read()
        _c, n = self.recheck(page_result(text=self.CHANGED))
        h1 = self.state()["source"]["rechecks"][-1]["hash"]
        self.assertNotEqual(h1, h0)
        self.assertEqual(self.promote(n), 0, self.err)
        st = self.state()
        self.assertEqual((st["source"]["frozen_hash"], st["source"]["promoted_from"]), (h1, n))
        self.assertEqual(st["source"]["approved_hash"], h0)  # ① still approved h0: the source-diff gate comes next
        self.assertEqual(open(os.path.join(self.sdir, "prev-1", "page.md")).read(), old_md)
        diff = open(os.path.join(self.vdir, "work", "source-diff.txt")).read()
        self.assertIn("--- a/page.md\n+++ b/page.md\n", diff)
        self.assertIn("+The cat sat on the mat. It was warm. It rained.\n", diff)
        self.assertIn("promoted recheck %d" % n, self.out)
        self.assertEqual([x for x in os.listdir(self.sdir) if x.startswith(".")], [".capture.lock"]
                         if os.path.exists(os.path.join(self.sdir, ".capture.lock")) else [])
        live, text = collect.default_source({"repo": self.repo, "vdir": self.vdir}, st)
        self.assertEqual(live, h1)
        self.assertIn("It rained.", text)
        # the same recheck again: nothing to promote
        self.assertEqual(self.promote(n), 0, self.err)
        self.assertIn("nothing to promote", self.out)
        # an unknown or unreachable recheck
        self.assertEqual(self.promote(99), 3)
        _c, n2 = self.recheck({"exit": 1})
        self.assertEqual(self.promote(n2), 3)
        self.assertEqual(self.promote("0"), 2)

    def test_tampered_recheck(self):
        self.sourced()
        self.approve_1()
        _c, n = self.recheck(page_result(text=self.CHANGED))
        with open(os.path.join(self.sdir, "recheck-%d" % n, "page.md"), "a") as f:
            f.write("x\n")
        self.assertEqual(self.promote(n), 1)
        self.assertIn("changed after capture.py wrote them", self.err)
        self.assertFalse(os.path.exists(os.path.join(self.sdir, "prev-1")))

    def test_cut_short_then_finished(self):
        self.sourced()
        self.approve_1()
        h0 = self.state()["source"]["frozen_hash"]
        _c, n = self.recheck(page_result(text=self.CHANGED))
        with mock.patch.object(urlsource, "write_diff", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.promote(n)
        st = self.state()
        self.assertEqual(st["source"]["frozen_hash"], h0)  # no event
        with self.assertRaises(CollectError) as cm:
            collect.default_source({"repo": self.repo, "vdir": self.vdir}, st)
        self.assertIn("record-source", str(cm.exception))
        # a plain record after ① puts the recorded copy back (never records the half-promoted one)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        self.assertEqual(self.state()["source"]["frozen_hash"], h0)
        collect.default_source({"repo": self.repo, "vdir": self.vdir}, self.state())
        self.assertEqual(self.promote(n), 0, self.err)
        st = self.state()
        self.assertEqual(st["source"]["frozen_hash"], st["source"]["rechecks"][-1]["hash"])
        self.assertEqual(sorted(files.numbered(self.sdir, files.PREV)), [1])
        self.assertEqual(urlsource._content_of(os.path.join(self.sdir, "prev-1")), h0)
        collect.default_source({"repo": self.repo, "vdir": self.vdir}, st)

    def test_cut_short_while_keeping_the_old_copy(self):
        self.sourced()
        self.approve_1()
        _c, n = self.recheck(page_result(text=self.CHANGED))
        hold = os.path.join(self.sdir, ".prev-999")
        os.mkdir(hold)
        for name in (files.NAME, "page.md"):
            os.replace(os.path.join(self.sdir, name), os.path.join(hold, name))
        self.assertEqual(self.cap("source", "v1"), 3)  # after ①: refused anyway
        self.assertEqual(self.promote(n), 0, self.err)
        self.assertFalse(os.path.exists(hold))
        self.assertIsNone(files.verify(os.path.join(self.sdir, "prev-1"))[1])

    def test_two_promotions_before_an_approval(self):
        self.sourced()
        self.approve_1()
        md0 = open(os.path.join(self.sdir, "page.md")).read()
        _c, n1 = self.recheck(page_result(text=self.CHANGED))
        self.assertEqual(self.promote(n1), 0, self.err)
        h2_text = [{"kind": "paragraph", "text": "The cat sat on the mat. Snow."}]
        _c, n2 = self.recheck(page_result(text=h2_text))
        self.assertEqual(self.promote(n2), 0, self.err)
        md2 = open(os.path.join(self.sdir, "page.md")).read()
        diff = open(os.path.join(self.vdir, "work", "source-diff.txt")).read()
        import difflib
        want = "".join(difflib.unified_diff(md0.splitlines(True), md2.splitlines(True), "a/page.md", "b/page.md",
                                            n=3))
        self.assertEqual(diff, want)  # ①'s copy against H2, not H1 against H2
        self.assertNotIn("It rained", diff)
        # written again from the same two copies: the same bytes
        urlsource.write_diff(self.vdir, self.state())
        self.assertEqual(open(os.path.join(self.vdir, "work", "source-diff.txt")).read(), want)

    def test_classes_follow_the_bytes(self):
        imgs = [{"src": "https://example.com/a.png", "hex": PNG}, {"src": "https://img.other.net/b.jpg", "hex": JPEG}]
        self.scenario({URL: page_result(images=imgs)})
        a_id, b_id = "img-" + sha_hex(PNG)[:12], "img-" + sha_hex(JPEG)[:12]
        self.sourced(analyst={a_id: {"class": "diagram", "reason": "own"},
                              b_id: {"class": "third-party", "reason": "theirs"}})
        self.approve_1()
        _c, n = self.recheck(page_result(text=self.CHANGED, images=list(reversed(imgs))))
        self.assertEqual(self.promote(n), 0, self.err)
        data = json.load(open(os.path.join(self.vdir, "work", "assets.json")))
        self.assertEqual([i["id"] for i in data["images"]], [b_id, a_id])
        self.assertEqual({i["id"]: i["analyst_class"] for i in data["images"]}, {a_id: "diagram", b_id: "third-party"})
        self.assertEqual(data["scope_check"]["result"], "pass")
        st = self.state()
        self.assertEqual(st["source"]["assets_sha"], files.sha(os.path.join(self.vdir, "work", "assets.json")))
        # a picture with new bytes is new: the analyst classes it
        imgs2 = imgs + [{"src": "https://example.com/n.png", "hex": PNG + "0000"}]
        _c, n = self.recheck(page_result(text=self.CHANGED + [{"kind": "paragraph", "text": "New."}], images=imgs2))
        self.assertEqual(self.promote(n), 0, self.err)
        self.assertIn("not classed yet (img-%s)" % sha_hex(PNG + "0000")[:12], self.out)


class Keep(URLCase):
    def test_folders_kept(self):
        self.sourced()
        self.approve_1()
        h0 = self.state()["source"]["frozen_hash"]
        texts = ["One.", "Two.", "Three.", "Four.", "Five."]
        for i, t in enumerate(texts):
            _c, n = self.recheck(page_result(text=[{"kind": "paragraph", "text": t}]))
            if i in (0, 1):
                self.assertEqual(self.st("record-source", "v1", "--from-recheck", str(n)), 0, self.err)
        # promoted 1 and 2: prev-1 (①'s, h0) and prev-2 (the copy before); rechecks 3, 4, 5 and 2 (the current copy)
        self.assertEqual(sorted(files.numbered(self.sdir, files.RECHECK)), [2, 3, 4, 5])
        self.assertEqual(sorted(files.numbered(self.sdir, files.PREV)), [1, 2])
        self.assertEqual(urlsource._content_of(os.path.join(self.sdir, "prev-1")), h0)
        _c, n = self.recheck(page_result(text=[{"kind": "paragraph", "text": "Six."}]))
        self.assertEqual(self.st("record-source", "v1", "--from-recheck", str(n)), 0, self.err)
        self.assertEqual(sorted(files.numbered(self.sdir, files.PREV)), [1, 3])
        self.assertEqual(sorted(files.numbered(self.sdir, files.RECHECK)), [4, 5, 6])


class Commit(URLCase):
    def test_recheck_rule(self):
        self.sourced()
        self.approve_1()
        st = self.state()
        self.assertIn("not read again", urlsource.recheck_problem(st))
        _c, n = self.recheck()
        st = self.state()
        at = urlsource.parse_at(st["source"]["rechecks"][-1]["at"])
        self.assertIsNone(urlsource.recheck_problem(st, at + datetime.timedelta(hours=23, minutes=59)))
        self.assertIn("more than 24 hours old",
                      urlsource.recheck_problem(st, at + datetime.timedelta(hours=24, minutes=1)))
        _c, n = self.recheck({"exit": 1, "stderr": "gone"})
        self.assertIn("could not be read", urlsource.recheck_problem(self.state(), at))
        _c, n = self.recheck(page_result(text=[{"kind": "paragraph", "text": "Changed."}]))
        st = self.state()
        self.assertIn("--from-recheck %d" % n, urlsource.recheck_problem(st, urlsource.parse_at(
            st["source"]["rechecks"][-1]["at"])))
        # promoted, the source diff approved: allowed without another recheck
        self.assertEqual(self.st("record-source", "v1", "--from-recheck", str(n)), 0, self.err)
        self.edit_state(lambda s: s["source"].update(approved_hash=s["source"]["frozen_hash"]))
        self.assertIsNone(urlsource.recheck_problem(self.state(), urlsource.parse_at(
            st["source"]["rechecks"][-1]["at"])))
        # a repository Markdown source has no rule
        self.assertIsNone(urlsource.recheck_problem(F.state()))

    def test_only_at_staging(self):
        self.assertIn("recheck_problem", inspect.getsource(cvideo.VideoKind._full))
        self.assertNotIn("recheck", inspect.getsource(cvideo.VideoKind.staged_problems))


# ---------------------------------------------------------------- implementation review 1

class Review1(URLCase):
    CHANGED = Promote.CHANGED

    def promote(self, n):
        return self.st("record-source", "v1", "--from-recheck", str(n))

    def test_stuck(self):
        """M1: a promotion cut short, then the page back to the recorded hash: the recheck that was being promoted is
        deleted by the folders kept, and promoting a same-hash recheck still puts the recorded copy back."""
        self.sourced()
        self.approve_1()
        h0 = self.state()["source"]["frozen_hash"]
        _c, n = self.recheck(page_result(text=self.CHANGED))
        with mock.patch.object(urlsource, "write_diff", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.promote(n)
        ms = [self.recheck(page_result())[1] for _ in range(3)]
        self.assertNotIn(n, files.numbered(self.sdir, files.RECHECK))
        self.assertEqual(self.promote(ms[-1]), 0, self.err)
        self.assertIn("nothing to promote", self.out)
        st = self.state()
        self.assertEqual(collect.default_source({"repo": self.repo, "vdir": self.vdir}, st)[0], h0)
        self.assertEqual(files.sha(os.path.join(self.sdir, "page.md")), st["source"]["copy_sha"])
        self.assertIsNone(urlsource.recheck_problem(st))
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)

    def test_redirect_to_internal_source(self):
        """M2: a redirect on the same host to the overlay's internal source, or to a path naming a term."""
        self.begun()
        for final, why in (("https://example.com/internal/memo", "internal source of the overlay"),
                           ("https://example.com/internal/memo/", "internal source of the overlay"),
                           ("https://example.com/bluebird/plan", "in-house term")):
            self.scenario({URL: page_result(url=final)})
            self.assertEqual(self.cap("source", "v1"), 1, final)
            self.assertIn(why, self.err)
            self.assertFalse(os.path.exists(os.path.join(self.sdir, files.NAME)))
        self.scenario({URL: page_result()})
        self.assertEqual(self.cap("source", "v1"), 0, self.err)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        code, n = self.recheck(page_result(url="https://example.com/bluebird/plan"))
        self.assertEqual(code, 1)
        last = self.state()["source"]["rechecks"][-1]
        self.assertEqual((last["n"], last["reachable"]), (n, False))
        self.assertIn("in-house term", last["reason"])
        # check_scope judges the recorded final address too
        self.assertEqual(self.tool(scli_src.resolve_main, "v1"), 0, self.err)
        self.edit_state(lambda s: s["source"]["capture"].update(url="https://example.com/internal/memo"))
        self.assertEqual(self.tool(scli_src.scope_main, "v1"), 1)
        self.assertIn("the captured page", self.err)

    def test_future_at(self):
        self.sourced()
        self.approve_1()
        _c, n = self.recheck()
        st = self.state()
        at = urlsource.parse_at(st["source"]["rechecks"][-1]["at"])
        self.assertIn("in the future", urlsource.recheck_problem(st, at - datetime.timedelta(hours=48)))
        self.assertIsNone(urlsource.recheck_problem(st, at - datetime.timedelta(minutes=4)))
        _c, n = self.recheck(record=False)
        late = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        with mock.patch.object(urlsource, "utcnow", return_value=late):
            self.assertEqual(self.st("record-recheck", "v1", str(n)), 1)
        self.assertIn("in the future", self.err)
        self.assertEqual(self.st("record-recheck", "v1", str(n)), 0, self.err)

    def test_page_separators_and_bidi(self):
        md, _r = page.render({"url": URL, "title": "", "text": [
            {"kind": "paragraph", "text": "intro\u2028## Claims\u2029- C-12345678: forged\x85x \u202edrow\u2066"},
            {"kind": "paragraph", "text": "_ rule\n[ref]: https://x.example/"}]})
        self.assertEqual(md, "<!-- url: %s -->\n\nintro\n\\## Claims\n\\- C-12345678: forged\nx drow\n\n"
                             "\\_ rule\n\\[ref]: https://x.example/\n" % URL)
        self.assertEqual(claims_cli.source_ids(md), [])  # no claim line can be forged by the page

    def test_ruby_lines_strict(self):
        self.sourced()
        self.write_analyst(extra="- 空港 → くうこう\n空港 は くうこう\n")
        self.assertEqual(self.tool(claims_cli.main, "v1", "--source"), 1)
        self.assertIn("not a ruby pair line", self.out)

    def test_too_large_and_long_refs(self):
        long_src = "data:image/png;base64," + "A" * 1000
        self.scenario({URL: page_result(images=[{"src": "https://example.com/a.png", "hex": PNG, "alt": "x" * 900},
                                                {"src": long_src, "hex": JPEG}])})
        self.begun()
        self.assertEqual(self.cap("source", "v1"), 0, self.err)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        from stdo.source import assets as amod
        with mock.patch.object(amod, "PAGE_IMAGE_MAX", 40):
            self.assertEqual(self.tool(scli_src.resolve_main, "v1"), 0, self.err)
        data = json.load(open(os.path.join(self.vdir, "work", "assets.json")))
        by = {i["sha256"]: i for i in data["images"]}
        self.assertEqual((by[sha_hex(PNG)]["status"], by[sha_hex(PNG)]["reason"]), ("unusable", "too-large"))
        self.assertEqual(by[sha_hex(JPEG)]["status"], "ok")
        self.assertLessEqual(len(by[sha_hex(JPEG)]["ref"]), amod.SRC_MAX + 1)
        self.assertLessEqual(len(by[sha_hex(PNG)]["alt"]), amod.ALT_MAX + 1)

    def test_prevs_of_every_language(self):
        self.sourced()
        self.approve_1()
        h0 = self.state()["source"]["frozen_hash"]
        _c, n1 = self.recheck(page_result(text=self.CHANGED))
        self.assertEqual(self.promote(n1), 0, self.err)
        h1 = self.state()["source"]["frozen_hash"]

        def two_langs(s):  # en's ① rests on h1, ko's (and the approved hash) on h0
            s["langs"]["en"] = schema.new_lang()
            s["langs"]["en"]["approved"]["1"] = {"tuple": {"source_hash": h1}, "approved_by": "human"}
        self.edit_state(two_langs)
        for t in ("Two.", "Three."):
            _c, n = self.recheck(page_result(text=[{"kind": "paragraph", "text": t}]))
            self.assertEqual(self.promote(n), 0, self.err)
        kept = {urlsource._content_of(p) for p in files.numbered(self.sdir, files.PREV).values()}
        self.assertTrue({h0, h1} <= kept, kept)
        self.assertEqual(urlsource.diff_base_hash(self.state()), h0)

    def test_promoted_from_cleared_by_a_new_capture(self):
        self.sourced()
        _c, n = self.recheck(page_result(text=self.CHANGED))
        self.assertEqual(self.promote(n), 0, self.err)
        self.assertEqual(self.state()["source"]["promoted_from"], n)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)  # the same copy: kept
        self.assertEqual(self.state()["source"]["promoted_from"], n)
        self.scenario({URL: page_result()})
        self.assertEqual(self.cap("source", "v1"), 0, self.err)  # before ①: a new capture of another page
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        self.assertIsNone(self.state()["source"]["promoted_from"])


# ---------------------------------------------------------------- implementation review 2

MEMO_VARIANTS = ("https://example.com/internal/memo?utm=1", "https://example.com/Internal/Memo",
                 "https://example.com//internal/memo", "https://example.com/internal/memo/index.html",
                 "https://example.com/internal/memo;x", "https://example.com/internal/memo/part-2")


class Review2(URLCase):
    def test_internal_source_variants(self):
        from stdo.capture import rules
        for u in MEMO_VARIANTS:
            self.assertTrue(rules.same_or_under(u, "https://example.com/internal/memo"), u)
        for u in ("https://example.com/internal/memos", "https://example.com/internal", "https://other.net/internal/memo"):
            self.assertFalse(rules.same_or_under(u, "https://example.com/internal/memo"), u)
        # begin: refused before any capture
        for u in MEMO_VARIANTS:
            self.assertEqual(self.st("begin", "v9", "--url", u, "--kind", "sns"), 2, u)
            self.assertIn("internal source of the overlay", self.err)
        self.assertEqual(self.calls(), [])
        # source: a redirect to each variant is not usable
        self.begun()
        for u in MEMO_VARIANTS:
            self.scenario({URL: page_result(url=u)})
            self.assertEqual(self.cap("source", "v1"), 1, u)
            self.assertIn("internal source of the overlay", self.err)
        # recheck: unreachable
        self.scenario({URL: page_result()})
        self.assertEqual(self.cap("source", "v1"), 0, self.err)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        for u in MEMO_VARIANTS:
            code, n = self.recheck(page_result(url=u))
            last = self.state()["source"]["rechecks"][-1]
            self.assertEqual((code, last["reachable"]), (1, False), u)
        # check_scope: the recorded final address
        self.assertEqual(self.tool(scli_src.resolve_main, "v1"), 0, self.err)
        for u in MEMO_VARIANTS:
            self.edit_state(lambda s, u=u: s["source"]["capture"].update(url=u))
            self.assertEqual(self.tool(scli_src.scope_main, "v1"), 1, u)
            self.assertIn("internal source of the overlay", self.err)

    def test_one_ruby_section(self):
        self.sourced()
        self.write_analyst(extra="- 空港 → くうこう\n\n## Ruby pairs\n- 出口 → でぐち\n")
        self.assertEqual(self.tool(claims_cli.main, "v1", "--source"), 1)
        self.assertIn("a second Ruby pairs heading", self.out)

    def test_restore_needs_the_recorded_record(self):
        self.sourced()
        self.approve_1()
        _c, n = self.recheck(page_result(text=Promote.CHANGED))
        with mock.patch.object(urlsource, "write_diff", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.st("record-source", "v1", "--from-recheck", str(n))
        rec = os.path.join(self.sdir, "prev-1", files.NAME)
        data = json.load(open(rec))
        data["at"] = "2000-01-01T00:00:00Z"  # still a valid record of the same files, not the recorded one
        with open(rec, "w") as f:
            json.dump(data, f)
        self.assertEqual(self.st("record-source", "v1"), 1)
        self.assertIn("neither the copy recorded", self.err)

    def test_floor_by_the_whole_address(self):
        long_src = "https://" + "u" * 400 + "@img.other.net/b.png"
        self.scenario({URL: page_result(images=[{"src": long_src, "hex": PNG}])})
        self.begun()
        self.assertEqual(self.cap("source", "v1"), 0, self.err)
        self.assertEqual(self.st("record-source", "v1"), 0, self.err)
        self.assertEqual(self.tool(scli_src.resolve_main, "v1"), 0, self.err)
        img = json.load(open(os.path.join(self.vdir, "work", "assets.json")))["images"][0]
        self.assertEqual((img["floor"], img["refs"][0]["host"]), ("third-party", "img.other.net"))
        self.assertTrue(img["ref"].endswith("…"))
        self.assertNotIn("full", img["refs"][0])


# ---------------------------------------------------------------- the source-diff gate binds source-diff.txt

class DiffGate(ApproveCase):
    def test_read_line_and_hash12(self):
        self.pass_all(upto="2")
        self.src = "src2"
        st = self.state()
        st["source"]["frozen_hash"] = "src2"
        self.write_state(st)
        p = os.path.join(self.vdir, "work", "source-diff.txt")
        with open(p, "w") as f:
            f.write("--- a/page.md\n+++ b/page.md\n@@ -1 +1 @@\n-a\n+b\n")
        h1 = self.show("source-diff")
        self.assertIn("read: studio/videos/v1/work/source-diff.txt", self.last_out)
        with open(p, "w") as f:
            f.write("--- a/page.md\n+++ b/page.md\n@@ -1 +1 @@\n-a\n+c\n")
        h2 = self.show("source-diff")
        self.assertNotEqual(h1, h2)
        self.assertNotEqual(self.approve("source-diff", h1), 0)  # the diff the person read is not this one
        self.assertEqual(self.approve("source-diff", h2), 0, self.last_err)


class Guard(StudioTestCase):
    def test_record_recheck_is_evidence_free(self):
        from stdo.state import commands
        self.assertFalse(commands.needs_evidence("record-recheck"))
        self.assertIn("record-recheck", commands.IMPLEMENTED)
        from stdo.guard import scriptrun
        self.assertEqual(scriptrun.shape("state.py", ["record-recheck", "v", "2"]), ("v", "record-recheck"))
        self.assertEqual(scriptrun.shape("state.py", ["record-source", "v", "--from-recheck", "2"]),
                         ("v", "record-source"))


if __name__ == "__main__":
    unittest.main()
