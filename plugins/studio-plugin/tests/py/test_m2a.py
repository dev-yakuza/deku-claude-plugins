"""Four video kinds (m2-plan §2): the kinds and their scope and location at begin, a local video's files under
<sr>/local/ (stdo/vpaths.py, the guard's role-output rule, backups, begin's leftover check), the audience check at
record-brief, the per-scope checks (check_scope's internal flag, board credits, the copy's in-house terms), local
`done`, and update's audience line."""

import contextlib
import io
import json
import os
from unittest import mock

import helpers
import state_fixtures as F
from approve_base import ApproveCase
from helpers import StudioTestCase
from stdo import board, vpaths
from stdo.commit import approvals
from stdo.distribute import check as copy_check
from stdo.guard import judge
from stdo.setup import render, update
from stdo.source import scope
from stdo.state import backup, cli, schema, store
from test_guard_autoallow import AllowCase
from test_m1b import FlowCase


def run_cli(repo, *argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv), cwd=repo)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------- kinds at begin

class Kinds(FlowCase):
    def test_begin_per_kind(self):
        want = {"youtube": ("public", "public"), "sns": ("public", "public"),
                "onboarding": ("internal", "local"), "explainer": ("internal", "local")}
        self.assertEqual(set(schema.KINDS), set(want))
        for n, (kind, (sc, loc)) in enumerate(sorted(want.items())):
            vid = "k%d" % n
            self.assertEqual(self.cli("begin", vid, "--source", "docs/a.md", "--kind", kind), 0, self.last_err)
            sub = ("local", "videos") if loc == "local" else ("videos",)
            vdir = os.path.join(self.repo, "studio", *sub, vid)
            st = store.read_state(vdir)
            self.assertEqual((st["kind"], st["scope"], st["location"]), (kind, sc, loc))
            self.assertEqual(store.video_dir(self.repo, "studio", vid), vdir)
            self.assertEqual(vpaths.video_dir(self.repo, "studio", st), vdir)
            self.assertEqual("never committed" in self.last_out, loc == "local", self.last_out)
        self.assertEqual(self.cli("begin", "k9", "--source", "docs/a.md", "--kind", "shorts"), 2)
        self.assertIn("--kind must be one of", self.last_err)

    def test_begin_refuses_leftovers(self):
        for n, rel in enumerate(("out/{v}/ko", "copy/{v}", "local/out/{v}", "local/copy/{v}/ko")):
            vid = "left%d" % n
            os.makedirs(os.path.join(self.repo, "studio", rel.format(v=vid)))
            self.assertEqual(self.cli("begin", vid, "--source", "docs/a.md", "--kind", "explainer"), 3, rel)
            self.assertIn("exists already", self.last_err)
            self.assertFalse(os.path.exists(os.path.join(self.repo, "studio", "local", "videos", vid)))

    def test_next_prints_scope_and_folders(self):
        self.assertEqual(self.cli("begin", "pub", "--source", "docs/a.md", "--kind", "sns"), 0, self.last_err)
        self.assertEqual(self.cli("begin", "loc", "--source", "docs/a.md", "--kind", "onboarding"), 0, self.last_err)
        self.cli("next", "pub")
        self.assertIn("scope: public\nout: studio/out/pub/ko/\ncopy: studio/copy/pub/ko/\n", self.last_out)
        self.cli("next", "loc")
        self.assertIn("scope: internal (no external audit before ③)\nout: studio/local/out/loc/ko/\n"
                      "copy: studio/local/copy/loc/ko/\n", self.last_out)
        self.cli("next", "loc", "--json")
        res = json.loads(self.last_out.splitlines()[0])
        self.assertEqual((res["scope"], res["out"], res["copy"]),
                         ("internal", "studio/local/out/loc/ko/", "studio/local/copy/loc/ko/"))


class Paths(StudioTestCase):
    def test_vpaths(self):
        pub, loc = {"video": "v", "location": "public"}, {"video": "v", "location": "local"}
        j = os.path.join
        self.assertEqual(vpaths.out_dir("/r", "studio", pub, "ko"), j("/r", "studio", "out", "v", "ko"))
        self.assertEqual(vpaths.copy_file("/r", "studio", pub, "ko", "youtube"),
                         j("/r", "studio", "copy", "v", "ko", "youtube.md"))
        self.assertEqual(vpaths.out_dir("/r", "studio", loc, "ko"), j("/r", "studio", "local", "out", "v", "ko"))
        self.assertEqual(vpaths.copy_dir("", "st", loc, "ko"), j("st", "local", "copy", "v", "ko"))
        self.assertEqual(vpaths.audition_dir("/r", "studio", loc, "ko"),
                         j("/r", "studio", "local", "out", "v", "ko", "audition"))
        self.assertEqual(backup.local_dirs("/r", "st", loc), [("_out", j("/r", "st", "local", "out", "v")),
                                                             ("_copy", j("/r", "st", "local", "copy", "v"))])


# ---------------------------------------------------------------- the audience at record-brief

class BriefAudience(StudioTestCase):
    def setUp(self):
        super().setUp()
        store.enable_writes()
        self.repo = helpers.make_repo(self.tmp)

    def video(self, kind):
        st = F.state()
        st.update(video="v-" + kind, kind=kind, scope=schema.KINDS[kind], location=schema.location_of(kind))
        vdir = vpaths.video_dir(self.repo, "studio", st)
        os.makedirs(vdir)
        store.create(vdir, st)
        F.brief_ready(self.repo, vdir)
        F.write_format(self.repo, kind=kind)
        return vdir

    def record(self, vdir, platforms):
        p = os.path.join(vdir, "work", "brief.json")
        with open(p, "w") as f:
            json.dump({"claims": [F.C1], "roles": [{"name": "narrator"}], "outputs": ["youtube"],
                       "platforms": {k: ["youtube"] for k in platforms}}, f)
        return run_cli(self.repo, "record-brief", os.path.basename(vdir), "--from", p)

    def test_audience_must_match_the_kind(self):
        F.write_platforms(self.repo, ("team",), audience="internal")
        pub, loc = self.video("sns"), self.video("explainer")
        code, _out, err = self.record(pub, ["team"])
        self.assertEqual(code, 1)
        self.assertIn("platform team is for internal videos", err)
        code, _out, err = self.record(loc, ["youtube"])  # brief_ready's platforms are public
        self.assertEqual(code, 1)
        self.assertIn("platform youtube is for public videos", err)
        self.assertEqual(self.record(pub, ["youtube", "sns"])[0], 0)
        self.assertEqual(self.record(loc, ["team"])[0], 0)

    def test_missing_audience_is_refused(self):
        vdir = self.video("youtube")
        d = os.path.join(self.repo, ".claude", "studio", "platforms")
        for name, text in (("old", "---\nplatform: old\nchecked: \"\"\n---\n"),
                           ("odd", "---\nplatform: odd\naudience: everyone\n---\n"),
                           ("bare", "# no frontmatter\naudience: public\n")):
            with open(os.path.join(d, name + ".md"), "w") as f:
                f.write(text)
            code, _out, err = self.record(vdir, [name])
            self.assertEqual(code, 1, name)
            self.assertIn("has no audience line", err)
            self.assertIn("audience: public", err)  # the line a person adds
        code, _out, err = self.record(vdir, ["none"])  # no file at all
        self.assertEqual(code, 1)
        self.assertIn("has no audience line", err)


# ---------------------------------------------------------------- the guard's role output for a local video

class RoleOutputs(AllowCase):
    def test_distributor_writes_its_location_only(self):
        def allowed(rel):
            hook = self.hook("Write", {"file_path": os.path.join(self.repo, "studio", rel), "content": "x\n"})
            hook.update({"agent_id": "a1", "agent_type": "std-distributor"})
            deny, ctx = judge.decide(hook, self.env, snapshot_loader=self.loader)
            self.assertIsNone(deny, rel)
            return bool(ctx.allow)
        self.assertTrue(allowed("copy/v/ko/youtube.md"))  # v is public
        self.assertTrue(allowed("local/copy/w/ko/youtube.md"))  # w is local
        self.assertFalse(allowed("copy/w/ko/youtube.md"))
        self.assertFalse(allowed("local/copy/v/ko/youtube.md"))
        self.assertFalse(allowed("local/copy/w/fr/youtube.md"))
        self.assertFalse(allowed("local/copy/w/ko/tiktok.md"))


# ---------------------------------------------------------------- a local video's files, backups and done

class LocalVideo(ApproveCase):
    location = "local"

    def test_files_land_under_local(self):
        self.pass_gate("1")
        for stage in self.STAGES["2"]:
            self.assertEqual(self.cli("stage-done", "v1", stage), 0, self.last_err)
        h = self.show("2")
        self.assertIn("② 오디션 — studio/local/out/v1/ko/audition/narrator.wav", self.last_out)
        self.assertEqual(self.approve("2", h), 0, self.last_err)
        self.pass_gate("3")
        self.pass_gate("4a")
        s = self.state()
        self.assertTrue(os.path.isfile(os.path.join(self.repo, "studio", "local", "out", "v1", "ko",
                                                    "youtube.ko.frames", "index.json")))
        self.copy_file("youtube")
        self.assertEqual(self.cli("stage-done", "v1", "copy", "--platform", "youtube"), 0, self.last_err)
        self.cli("shown", "v1", "4b", "--platform", "youtube")
        self.assertIn("④b 배포용 글 — studio/local/copy/v1/ko/youtube.md", self.last_out)
        for gone in ("out", "copy"):
            self.assertFalse(os.path.exists(os.path.join(self.repo, "studio", gone)), gone)
        self.assertEqual(s["location"], "local")
        st = helpers.git(self.repo, "status", "--porcelain", "--ignored", "--untracked-files=all").stdout
        paths = [l[3:] for l in st.splitlines()]
        self.assertTrue(paths and all(p.startswith("studio/local/") for p in paths if p.startswith("studio/")),
                        paths)

    def test_backup_takes_out_and_copy(self):
        d = os.path.join(self.repo, "studio", "local", "out", "v1", "ko")
        os.makedirs(d)
        with open(os.path.join(d, "youtube.ko.srt"), "w") as f:
            f.write("1\n")
        self.copy_file("youtube", "the copy")
        self.pass_gate("1")
        with open(os.path.join(backup.root(self.repo, "v1"), "copy.1", "manifest.json")) as f:
            m = json.load(f)
        paths = [e["path"] for e in m["files"]]
        self.assertIn(os.path.join("_out", "ko", "youtube.ko.srt"), paths)
        self.assertIn(os.path.join("_copy", "ko", "youtube.md"), paths)
        self.assertIn(os.path.join("work", "state.json"), paths)

    def done(self):
        return self.cli("done", "v1")

    def test_done_without_a_commit(self):
        self.pass_all("4a")
        self.assertEqual(self.done(), 1)  # ④b is missing
        self.assertIn("gate 4b(youtube) is not approved", self.last_err)
        self.copy_file("youtube")
        self.pass_gate("4b")
        self.assertEqual(self.done(), 0, self.last_err)
        self.assertIn("ko: done (a local video", self.last_out)
        self.assertEqual(self.state()["langs"]["ko"]["status"], "done")
        ev = self.events()[-1]
        self.assertEqual((ev["event"], ev.get("local")), ("done", True))
        with open(os.path.join(backup.root(self.repo, "v1"), "copy.1", "manifest.json")) as f:
            self.assertIn(os.path.join("_copy", "ko", "youtube.md"), [e["path"] for e in json.load(f)["files"]])
        self.assertEqual(self.done(), 2)  # finished already

    def set_proxy(self, gate_path):
        st = self.state()
        rec = st["langs"]["ko"]["approved"]
        for k in gate_path:
            rec = rec[k]
        rec["approved_by"] = "proxy"
        self.write_state(st)
        log = os.path.join(self.vdir, "work", "approvals.jsonl")
        with open(log) as f:
            events = [json.loads(l) for l in f]
        for e in events:
            if e.get("event") == "approve" and e.get("gate") == gate_path[0]:
                e["record"]["approved_by"] = "proxy"
        with open(log, "w") as f:
            f.write("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))

    def test_done_refuses_proxy_approvals(self):
        self.copy_file("youtube")
        self.pass_all()
        self.set_proxy(("4a", "youtube"))
        self.assertEqual(self.done(), 4)
        self.assertIn("approved by proxy", self.last_err)
        self.assertEqual(self.state()["langs"]["ko"]["status"], "active")

    def test_done_refuses_a_proxy_credit(self):
        self.copy_file("youtube")
        self.pass_all()
        st = self.state()
        st["credits"] = {"img.png": {"hash": "h", "approved_by": "proxy"}}
        self.write_state(st)
        self.assertEqual(self.done(), 4)
        self.assertIn("credit of img.png was approved in the proxy mode", self.last_err)

    def test_commit_check_still_refuses(self):
        self.copy_file("youtube")
        self.pass_all()
        msgs = [p.message for p in approvals.light_check(self.vdir, "v1")]
        self.assertIn("video v1 is a local (machine-only) video — it is never committed", msgs)
        self.assertEqual(approvals.light_check(self.vdir, "v1", local_done=True), [])


# ---------------------------------------------------------------- per-scope checks

class InternalImages(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.vdir = os.path.join(self.tmp, "v")
        os.makedirs(os.path.join(self.vdir, "work"))
        self.data = {"schema": 1, "source_copy_sha": "c", "images": [
            {"id": "img-01", "status": "ok", "reason": None, "floor": "public", "resolved": "docs/a.png",
             "script_src": "../../docs/a.png"},
            {"id": "img-02", "status": "ok", "reason": None, "floor": "third-party", "resolved": "docs/b.png",
             "script_src": "../../docs/b.png"},
            {"id": "img-03", "status": "ok", "reason": None, "floor": "public", "resolved": "secret/c.png",
             "script_src": "../../secret/c.png"},
            {"id": "img-04", "status": "unusable", "reason": "format", "floor": "public", "resolved": "docs/d.webp",
             "script_src": None}]}
        overlay = {"internal": {"sources": [{"path": "secret/**"}]}}
        self.overlay = overlay

    def classes(self, mapping):
        with open(os.path.join(self.vdir, "work", "source.md"), "w") as f:
            f.write("<!-- studio:images -->\n```json\n%s\n```\n<!-- /studio:images -->\n" % json.dumps(
                {k: {"class": v, "reason": "r"} for k, v in mapping.items()}))

    def run_check(self, video_scope):
        with open(os.path.join(self.vdir, "work", "assets.json"), "w") as f:
            json.dump(self.data, f)
        st = {"scope": video_scope, "source": {"path": "docs/a.md"}}
        cfg = {"visibility": {"public": ["docs/**"]}}
        out = scope.check(self.tmp, self.vdir, st, cfg, "c", "ok", self.overlay, {})
        self.data = out
        return {i["id"]: i for i in out["images"]}

    def test_class_internal_is_unknown_and_flagged(self):
        self.assertEqual(scope.CLASSES["internal"], "unknown")
        self.classes({"img-01": "internal", "img-02": "internal"})
        imgs = self.run_check("public")  # the source does not fail
        self.assertEqual((imgs["img-01"]["scope"], imgs["img-01"]["internal"]), ("unknown", True))
        # MJ1: third-party floor + class internal stays third-party AND internal — never usable in a public video
        self.assertEqual((imgs["img-02"]["scope"], imgs["img-02"]["internal"]), ("third-party", True))
        self.assertTrue(imgs["img-03"]["internal"])  # an overlay internal source
        for i in ("img-01", "img-02", "img-03"):
            self.assertEqual((imgs[i]["status"], imgs[i]["reason"]), ("unusable", "internal"), i)
        self.assertEqual((imgs["img-04"]["reason"], imgs["img-04"]["internal"]), ("format", False))
        # the analyst changes its mind: the next run judges again
        self.classes({"img-01": "photo"})
        imgs = self.run_check("public")
        self.assertEqual((imgs["img-01"]["status"], imgs["img-01"]["internal"]), ("ok", False))
        self.assertEqual(imgs["img-02"]["status"], "ok")
        self.assertEqual(imgs["img-03"]["status"], "unusable")

    def test_a_check_from_before_the_flag_is_stale(self):
        """A public video begun before 0.2.0: its assets.json has no `internal` flags (check_scope of version 27), so
        record-source, the commit check and board ask for check_scope again."""
        from stdo.state import flow
        old = {"schema": 1, "scope_check": {"scripts_version": "27"}, "images": [{"id": "img-01", "status": "ok"}]}
        self.assertIn("run check_scope.py again", flow.stale_scope_check(old, True))
        self.assertIsNone(flow.stale_scope_check(old, False))  # an internal video ignores the flag
        self.classes({})
        new = self.run_check("public")
        self.assertIsNone(flow.stale_scope_check(self.data, True))
        self.assertTrue(all("internal" in i for i in new.values()))
        del self.data["images"][0]["internal"]
        self.assertIn("run check_scope.py again", flow.stale_scope_check(self.data, True))
        self.data["images"][0]["internal"] = False
        self.data["scope_check"]["scripts_version"] = "27"
        self.assertIn("run check_scope.py again", flow.stale_scope_check(self.data, True))
        with open(os.path.join(self.vdir, "work", "assets.json"), "w") as f:
            json.dump(self.data, f)
        fp = {}  # run_check's fingerprint
        imgs, sha, note = flow._checked_assets(self.vdir, "c", fp)
        self.assertEqual((imgs, sha), ([], None))
        self.assertIn("run check_scope.py again, then record-source again", note)
        self.assertIsNotNone(flow._checked_assets(self.vdir, "c", fp, public=False)[1])

    def test_internal_video_ignores_the_flag(self):
        self.classes({"img-01": "internal"})
        imgs = self.run_check("internal")
        self.assertEqual((imgs["img-01"]["status"], imgs["img-01"]["internal"]), ("ok", True))
        self.assertEqual(imgs["img-03"]["status"], "ok")


class BoardCredits(StudioTestCase):
    """board.picture_problems per scope: a used internal image in a public video is refused whatever its credit; an
    internal video needs a person's CREDITS entry for every picture, a license for third-party, no public_ok."""

    def setUp(self):
        super().setUp()
        self.repo = helpers.make_repo(self.tmp)
        self.vdir = os.path.join(self.repo, "studio", "videos", "v1")
        os.makedirs(os.path.join(self.vdir, "work"))
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x01" * 2 + b"\x08\x02\x00\x00\x00" + b"x" * 8
        self.shas = {}
        imgs = []
        import hashlib
        for n, (floor, internal) in enumerate((("unknown", False), ("third-party", False), ("third-party", True)), 1):
            name = "i%d.png" % n
            with open(os.path.join(self.vdir, name), "wb") as f:
                f.write(png + bytes([n]))
            sha = hashlib.sha256(png + bytes([n])).hexdigest()
            self.shas[name] = sha
            imgs.append({"id": "img-%02d" % n, "status": "unusable" if internal else "ok",
                         "reason": "internal" if internal else None, "scope": floor, "floor": floor,
                         "internal": internal, "script_src": name, "sha256": sha})
        with open(os.path.join(self.vdir, "work", "assets.json"), "w") as f:
            json.dump({"schema": 1, "images": imgs}, f)

    def credits(self, **extra):
        from stdo import credits
        entries = {n: dict({"path": n, "sha256": s, "source": "x", "credit_line": "c %s" % n,
                            "license": "CC-BY-4.0", "floor": "unknown"}, **extra.get(n, {}))
                   for n, s in self.shas.items()}
        with open(os.path.join(self.vdir, credits.FILE), "w") as f:
            f.write(credits.dumps(entries))
        return {n: {"hash": credits.entry_hash(e), "approved_by": "human"} for n, e in entries.items()}

    def problems(self, video_scope, files, **extra):
        approved = self.credits(**extra)
        st = {"scope": video_scope, "credits": approved}
        ins = {"files": [{"path": n, "kind": "image"} for n in files]}
        return board.picture_problems(self.repo, self.vdir, st, ins)

    def test_public_video_begun_before_the_flag(self):
        with open(os.path.join(self.vdir, "work", "assets.json")) as f:
            data = json.load(f)
        del data["images"][0]["internal"]
        with open(os.path.join(self.vdir, "work", "assets.json"), "w") as f:
            json.dump(data, f)
        ok = {"i1.png": {"public_ok": True}}
        got = self.problems("public", ["i1.png"], **ok)
        self.assertEqual(got, ["i1.png was checked before images could be internal — run check_scope.py again (the "
                               "source stage)"])
        self.assertEqual(self.problems("internal", ["i1.png"]), [])

    def test_public(self):
        got = self.problems("public", ["i1.png", "i2.png"])
        self.assertTrue(any("i1.png is unknown: a public video needs public_ok" in p for p in got), got)
        ok = {"i1.png": {"public_ok": True}, "i2.png": {"public_ok": True}, "i3.png": {"public_ok": True}}
        self.assertEqual(self.problems("public", ["i1.png", "i2.png"], **ok), [])
        got = self.problems("public", ["i3.png"], **ok)
        self.assertEqual(got, ["i3.png is an internal image (made inside the organization): a public video cannot "
                               "show it"])

    def test_internal(self):
        self.assertEqual(self.problems("internal", ["i1.png", "i2.png"]), [])  # no public_ok anywhere
        got = self.problems("internal", ["i2.png"], **{"i2.png": {"license": ""}})
        self.assertTrue(any("i2.png is third-party: it needs a license" in p for p in got), got)
        self.assertEqual(self.problems("internal", ["i1.png"], **{"i1.png": {"license": ""}}), [])  # unknown: free
        os.remove(os.path.join(self.vdir, "CREDITS.yaml"))
        got = board.picture_problems(self.repo, self.vdir, {"scope": "internal", "credits": {}},
                                     {"files": [{"path": "i1.png", "kind": "image"}]})
        self.assertTrue(any("every picture of an internal video needs one" in p for p in got), got)


class CopyTerms(StudioTestCase):
    def test_in_house_terms_per_scope(self):
        repo = helpers.make_repo(self.tmp)
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(vdir)
        copy = os.path.join(self.tmp, "copy.md")
        with open(copy, "w") as f:
            f.write("---\ntitle: \"t\"\nhashtags: []\n---\nAbout Zorblax today.\n")
        rules = ({"title_max": 100, "description_max_bytes": 5000, "hashtags_max": 5, "required": []}, "2026-11-01")
        for sc, overlay, hit in (("public", "ok", True), ("internal", "ok", False), ("internal", "missing", False)):
            st = F.state()
            st["scope"] = sc
            with mock.patch.object(copy_check.rules_mod, "read", return_value=rules), \
                    mock.patch.object(copy_check, "overlay_terms", return_value=(overlay, ["Zorblax"])), \
                    mock.patch.object(copy_check, "excerpt_problems", return_value=[]):
                got = copy_check.problems(repo, vdir, st, "ko", {"repo": repo, "studio_root": "studio"}, "youtube",
                                          {}, {}, copy)
            self.assertEqual(any("in-house term" in p for p in got), hit, (sc, got))
            self.assertEqual(any("overlay is missing" in p for p in got), overlay == "missing", (sc, got))


# ---------------------------------------------------------------- update's audience line and the templates

class Templates(StudioTestCase):
    def test_every_kind_has_a_format(self):
        for kind in schema.KINDS:
            rel = ".claude/studio/formats/%s.md" % kind
            self.assertIn(rel, render.TEMPLATED)
            self.assertTrue(os.path.isfile(os.path.join(render.TEMPLATES, render.TEMPLATED[rel])), kind)
        from stdo import criteria
        for kind in schema.KINDS:
            with open(os.path.join(render.TEMPLATES, "formats", "%s.md" % kind), encoding="utf-8") as f:
                crit = criteria.parse(f.read(), ("ko",))
            self.assertLess(crit["length_seconds"]["min"], crit["length_seconds"]["max"])

    def test_shipped_platforms_have_an_audience(self):
        from stdo.distribute import rules
        for name, aud in (("youtube", "public"), ("youtube-shorts", "public"), ("internal", "internal")):
            with open(os.path.join(render.TEMPLATES, "platforms", name + ".md"), encoding="utf-8") as f:
                self.assertIn("\naudience: %s\n" % aud, f.read())
            self.assertIn(aud, rules.AUDIENCES)

    def test_add_audience(self):
        old = "---\nplatform: youtube\nchecked: \"2026-10-30\"\noutputs:\n  - name: youtube\n---\n# body\naudience: x\n"
        new = update.add_audience(old, "public")
        self.assertEqual(new, old.replace("platform: youtube\n", "platform: youtube\naudience: public\n"))
        self.assertIsNone(update.add_audience(new, "public"))
        self.assertIsNone(update.add_audience("# no frontmatter\n", "public"))

    def test_update_plan_adds_the_line(self):
        repo = helpers.make_repo(self.tmp)
        d = os.path.join(repo, ".claude", "studio", "platforms")
        os.makedirs(d)
        with open(os.path.join(d, "youtube.md"), "w") as f:
            f.write("---\nplatform: youtube\nchecked: \"2026-10-30\"\n---\n# mine\n")
        with open(os.path.join(d, "internal.md"), "w") as f:
            f.write("---\nplatform: internal\naudience: internal\n---\n")
        p = update.plan(repo)
        self.assertEqual([(a["path"], a["audience"]) for a in p["audience"]],
                         [(".claude/studio/platforms/youtube.md", "public")])
        before = p["h12"]
        os.remove(os.path.join(d, "youtube.md"))
        self.assertEqual(update.plan(repo)["audience"], [])
        self.assertNotEqual(update.plan(repo)["h12"], before)

    def test_new_formats_are_optional(self):
        """init leaves the newer kinds' formats out (the first commit's value block must fit its question); update
        offers each as `optional` (no conflict), and adds it when the person takes it."""
        self.assertEqual(set(render.INIT_SKIP), {".claude/studio/formats/%s.md" % k for k in schema.KINDS
                                                 if k != "youtube"})
        repo = helpers.make_repo(self.tmp)
        p = update.plan(repo)
        states = {i["path"]: i["state"] for i in p["templates"]}
        for rel in render.INIT_SKIP:
            self.assertEqual(states[rel], "optional")
            self.assertNotIn(rel, p["conflicts"])
        self.assertEqual(set(p["templates"][[i["path"] for i in p["templates"]].index(
            ".claude/studio/formats/sns.md")]["diff"]), {"criteria"})  # no full diff of an optional format
        took = update.plan(repo, ".claude/studio/formats/sns.md=new")
        item = [i for i in took["templates"] if i["path"] == ".claude/studio/formats/sns.md"][0]
        self.assertEqual(item["action"], "write-new")
        self.assertNotEqual(took["h12"], p["h12"])

    def test_a_declined_format_is_not_asked_again(self):
        repo = helpers.make_repo(self.tmp)
        sns = ".claude/studio/formats/sns.md"
        with self.assertRaises(Exception):
            update.plan(repo, ".claude/studio/formats/youtube.md=decline")  # decline is for optional formats only
        with mock.patch.object(update, "with_evidence", lambda top, argv, label, proxy, fn, cmd: fn()):
            p = update.plan(repo, sns + "=decline")
            update.apply(repo, p["h12"], sns + "=decline", ["update", "apply"])
        with open(os.path.join(repo, render.INSTALLED)) as f:
            inst = json.load(f)
        self.assertTrue(inst["templates"][sns]["declined"])
        p = update.plan(repo)
        item = [i for i in p["templates"] if i["path"] == sns][0]
        self.assertEqual((item["state"], item["resolved"]), ("declined", True))
        self.assertNotIn("diff", item)
        self.assertFalse(os.path.exists(os.path.join(repo, sns)))
        onb = [i for i in p["templates"] if i["path"] == ".claude/studio/formats/onboarding.md"][0]
        self.assertEqual(onb["state"], "optional")  # only the declined one
        # the plugin's format changes: asked again
        inst["templates"][sns]["declined"] = "0" * 64
        with open(os.path.join(repo, render.INSTALLED), "w") as f:
            json.dump(inst, f)
        self.assertEqual([i["state"] for i in update.plan(repo)["templates"] if i["path"] == sns], ["optional"])
