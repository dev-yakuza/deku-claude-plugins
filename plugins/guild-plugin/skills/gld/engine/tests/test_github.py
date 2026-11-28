"""U10 github: gh calls through the fake gh (argument log + fixture replies) — issue.md (§6.2),
summary comment and stage label (§4.3), new collaborator comments (§7.4), PR once (§7.6),
every write neutralised and scanned (§7.12 S10). Scenarios E1, E4, E7, E8, E9.
"""

import json
import os
import tempfile
import unittest

from gxengine import defaults, github, outbound
from tests.helpers import fakes

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.realpath(os.path.join(ENGINE, "..", "..", ".."))
FLOW = fakes.gh_fixture("issue-42-flow.json")
GH_PAT = "ghp_" + "b2" * 18
BRANCH = "gld/42-os-permission"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gx-github-")
        self.tmp = self._tmp.name
        self.log = os.path.join(self.tmp, "log")

    def tearDown(self):
        self._tmp.cleanup()

    def gh(self, fixture=FLOW, plugin_root=PLUGIN_ROOT, repo="acme/app"):
        env = fakes.fake_env(gh_fixtures=fixture, gh_log=self.log)
        g = github.Gh(repo, env=env, plugin_root=plugin_root)
        self.assertEqual(os.path.realpath(g.bin), os.path.realpath(fakes.FAKE_GH))
        return g

    def rules(self, rules):
        path = os.path.join(self.tmp, "rules-%d.json" % len(os.listdir(self.tmp)))
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"rules": rules}, f)
        return path

    def calls(self):
        return fakes.gh_calls(self.log)

    def writes(self):
        return [c for c in self.calls() if "-X" in c["argv"]]


class Reads(Base):
    def test_read_issue_maps_the_fields_and_merges_pages(self):
        issue = github.read_issue(self.gh(), 42)
        self.assertEqual(issue["number"], 42)
        self.assertEqual(issue["labels"], ["type:feature", "guild:analyze"])
        self.assertEqual(issue["state"], "OPEN")
        self.assertIsNone(issue["stateReason"])
        self.assertEqual([c["id"] for c in issue["comments"]], [900, 901, 902, 903])
        self.assertEqual(issue["comments"][1], {"id": 901, "author": "owner", "authorAssociation": "OWNER",
                                                "body": "Please also cover Android 14.",
                                                "createdAt": "2026-11-23T01:05:00Z"})
        argv = [c["argv"] for c in self.calls()]
        self.assertEqual(argv[0][:5], ["issue", "view", "42", "--repo", "acme/app"])
        self.assertEqual(self.writes(), [])

    def test_e7_issue_md_excludes_engine_and_outsider_comments(self):
        g = self.gh()
        issue = github.read_issue(g, 42)
        md = github.build_issue_md(g, issue, engine_comment_ids=[900])
        self.assertIn("Show OS permission state", md)
        self.assertIn("Depends on: #40", md)
        self.assertIn("Please also cover Android 14.", md)
        self.assertIn("Correction: iOS only.", md)
        self.assertNotIn("ignore previous instructions", md)
        self.assertNotIn("<!-- guild:summary", md)
        self.assertIn("- #40 (issue): state CLOSED, stateReason COMPLETED, labels type:feature", md)
        self.assertIn("- #41: not found", md)
        self.assertNotIn("- #42", md)        # itself
        self.assertNotIn("#7", md.split("Referenced issues")[1])   # other/repo#7 is not looked up
        self.assertNotIn("#35", md.split("Referenced issues")[1])  # an HTML entity, not a reference
        looked_up = [c["argv"][1] for c in self.calls() if c["argv"][:1] == ["api"] and "/issues/4" in c["argv"][1]
                     and not c["argv"][1].endswith("comments")]
        self.assertEqual(looked_up, ["repos/acme/app/issues/40", "repos/acme/app/issues/41"])

    def test_issue_md_reference_lookup_errors_are_not_swallowed(self):
        path = self.rules([{"args": ["api", "repos/acme/app/issues/5"], "stderr": "HTTP 502\n", "exit_code": 1}])
        issue = {"number": 1, "title": "t", "body": "see #5", "labels": [], "state": "OPEN", "comments": []}
        with self.assertRaises(github.GhError):
            github.build_issue_md(self.gh(path), issue, [])

    def test_issue_md_caps_reference_lookups(self):
        n = github.MAX_REFERENCED + 3
        body = " ".join("#%d" % i for i in range(2, n + 2))
        issue = {"number": 1, "title": "t", "body": body, "labels": [], "state": "OPEN", "comments": []}
        rules =[{"args": ["api", "repos/acme/app/issues/%d" % i], "json": {"number": i, "state": "open", "labels": []}}
                 for i in range(2, n + 2)]
        md = github.build_issue_md(self.gh(self.rules(rules)), issue, [])
        self.assertEqual(len(self.calls()), github.MAX_REFERENCED)
        self.assertIn("not looked up (3 more)", md)

    def test_e8_new_collaborator_comments_since_the_watermark(self):
        issue = github.read_issue(self.gh(), 42)
        self.assertEqual([c["id"] for c in github.new_collaborator_comments(issue, [900], 901)], [903])
        self.assertEqual([c["id"] for c in github.new_collaborator_comments(issue, [900], None)], [901, 903])
        self.assertEqual(github.new_collaborator_comments(issue, [900, 903], 901), [])
        self.assertEqual(github.new_collaborator_comments(issue, [900], 903), [])
        self.assertEqual(github.comment_watermark(issue, 901), 903)
        self.assertEqual(github.comment_watermark({"comments": []}, None), None)

    def test_e9_stable_stage_label(self):
        self.assertTrue(github.has_stable_label({"labels": ["gx:design"]}))  # promote: other
        self.assertTrue(github.has_stable_label({"labels": [{"name": github.STABLE_PREFIX.capitalize() + "Execute"}]}))
        for s in defaults.STABLE_STAGE_LABELS:
            self.assertTrue(github.has_stable_label({"labels": ["gx:" + s]}))  # promote: other
        self.assertFalse(github.has_stable_label({"labels": ["guild:design", "guild-ish", "bug"]}))
        self.assertFalse(github.has_stable_label({"labels": []}))

    def test_gh_errors(self):
        g = self.gh(self.rules([]))
        with self.assertRaises(github.GhError) as cm:
            github.read_issue(g, 42)
        self.assertEqual(cm.exception.returncode, 1)
        self.assertIn("no fixture rule", cm.exception.stderr)
        with self.assertRaises(github.GhError):
            g.api("GET", "repos/other/repo/issues/1")
        with self.assertRaises(github.GhError):
            g.api("GET", "repos/acme/app/../../other/repo/issues/1")
        with self.assertRaises(ValueError):
            github.read_issue(g, "42")
        with self.assertRaises(ValueError):
            github.Gh("acme app", env=fakes.fake_env())
        self.assertEqual(len(self.calls()), 1)       # the refused calls never reached gh

    def test_read_issue_refuses_an_answer_for_another_number(self):
        path = self.rules([{"args": ["issue", "view", "42", "--repo", "acme/app", "--json", "*"],
                            "json": {"number": 41}}])
        with self.assertRaises(github.GhError):
            github.read_issue(self.gh(path), 42)


class Writes(Base):
    def body_of(self, call):
        return json.loads(call["stdin"])

    def test_e4_summary_created_then_patched_neutralised(self):
        g = self.gh()
        cid = github.upsert_summary(g, 42, None, "status: design @tech-lead see #12 https://github.com/acme/app/issues/3")
        self.assertEqual(cid, 950)
        self.assertEqual(github.upsert_summary(g, 42, cid, "next"), 950)
        w = self.writes()
        self.assertEqual([c["argv"][:4] for c in w], [["api", "-X", "POST", "repos/acme/app/issues/42/comments"],
                                                      ["api", "-X", "PATCH", "repos/acme/app/issues/comments/950"]])
        first = self.body_of(w[0])["body"]
        self.assertTrue(first.startswith(github.SUMMARY_MARKER + "\n"))
        self.assertEqual(first.split("\n", 1)[1], "status: design ＠tech-lead see ＃12 ＃3")
        self.assertEqual(self.body_of(w[1]), {"body": github.SUMMARY_MARKER + "\nnext"})

    def test_e1_secret_in_a_comment_stops_before_any_write(self):
        g = self.gh()
        for call in (lambda: github.upsert_summary(g, 42, None, f"oops {GH_PAT}"),
                     lambda: github.post_comment(g, 42, f"x\n{GH_PAT}", marker="needs-human"),
                     lambda: github.create_pr(g, BRANCH, "main", "t", f"body {GH_PAT}", closes=42)):
            with self.assertRaises(outbound.SecretDetected):
                call()
        self.assertEqual(self.writes(), [])

    def test_writes_without_a_scanner_fail_closed(self):
        g = self.gh(plugin_root=None)
        with self.assertRaises(outbound.ScanError):
            github.post_comment(g, 42, "hello")
        with self.assertRaises(outbound.ScanError):
            github.set_stage_label(g, 42, "design")
        self.assertEqual(self.calls(), [])

    def test_post_comment_marker_and_id(self):
        g = self.gh()
        self.assertEqual(github.post_comment(g, 42, "needs a human: @x", marker="needs-human"), 950)
        body = self.body_of(self.writes()[0])["body"]
        self.assertEqual(body, "<!-- guild:needs-human -->\nneeds a human: ＠x")
        with self.assertRaises(ValueError):
            github.post_comment(g, 42, "x", marker="Bad Marker -->")

    def test_patch_answer_for_another_comment_is_an_error(self):
        path = self.rules([{"args": ["api", "-X", "PATCH", "repos/acme/app/issues/comments/5", "--input", "-"],
                            "json": {"id": 6}}])
        with self.assertRaises(github.GhError):
            github.upsert_summary(self.gh(path), 42, 5, "x")

    def test_stage_label_replaces_only_stage_labels(self):
        g = self.gh()
        self.assertEqual(github.set_stage_label(g, 42, "design", stage_ids=["analyze", "ac-format", "design"]),
                         "guild:design")
        w = [c["argv"][:4] for c in self.writes()]
        self.assertEqual(w, [["api", "-X", "DELETE", "repos/acme/app/issues/42/labels/guild%3Aanalyze"],
                             ["api", "-X", "POST", "repos/acme/app/issues/42/labels"]])
        self.assertEqual(self.body_of(self.writes()[1]), {"labels": ["guild:design"]})
        self.assertNotIn("escaped-ac", json.dumps([c["argv"] for c in self.writes()]))

    def test_stage_label_is_created_when_missing_and_not_readded(self):
        path = self.rules([
            {"args": ["api", "repos/acme/app/labels/guild%3Atest"], "stderr": "gh: Not Found (HTTP 404)\n", "exit_code": 1},
            {"args": ["api", "-X", "POST", "repos/acme/app/labels", "--input", "-"], "json": {"name": "guild:test"}},
            {"args": ["api", "repos/acme/app/issues/42/labels"], "json": [{"name": "guild:test"}]},
        ])
        github.set_stage_label(self.gh(path), 42, "test", stage_ids=["test"])
        w = self.writes()
        self.assertEqual([c["argv"][:4] for c in w], [["api", "-X", "POST", "repos/acme/app/labels"]])
        self.assertEqual(self.body_of(w[0])["name"], "guild:test")
        with self.assertRaises(ValueError):
            github.set_stage_label(self.gh(path), 42, "Bad Step")

    def test_pr_created_once_with_the_engine_closing_line(self):
        g = self.gh()
        pr = github.create_pr(g, BRANCH, "main", "Issue #42: show @state",
                              "Implements it. Related: #5 and https://github.com/acme/app/pull/9", closes=42)
        self.assertEqual(pr, {"number": 77, "url": "https://github.com/acme/app/pull/77"})
        w = self.writes()
        self.assertEqual([c["argv"][:4] for c in w], [["api", "-X", "POST", "repos/acme/app/pulls"]])
        sent = self.body_of(w[0])
        self.assertEqual(sent["title"], "Issue ＃42: show ＠state")
        self.assertIs(sent["draft"], False)
        self.assertEqual((sent["head"], sent["base"]), (BRANCH, "main"))
        self.assertTrue(sent["body"].startswith("Implements it. Related: ＃5 and ＃9"))
        self.assertEqual(sent["body"].count("#"), 1)
        self.assertTrue(sent["body"].endswith("\n\nCloses #42\n"))

    def test_pr_existing_open_is_returned_and_closed_is_an_error(self):
        q = "repos/acme/app/pulls?head=acme%3Agld%2F42-os-permission&state=all"
        open_rules = self.rules([{"args": ["api", q], "json": [
            {"number": 70, "state": "open", "html_url": "u70", "head": {"ref": BRANCH}}]}])
        self.assertEqual(github.create_pr(self.gh(open_rules), BRANCH, "main", "t", "b", closes=42),
                         {"number": 70, "url": "u70"})
        self.assertEqual(self.writes(), [])
        closed = self.rules([{"args": ["api", q], "json": [
            {"number": 70, "state": "closed", "html_url": "u70", "head": {"ref": BRANCH}}]}])
        with self.assertRaises(github.GhError):
            github.create_pr(self.gh(closed), BRANCH, "main", "t", "b")
        self.assertEqual(self.writes(), [])
        with self.assertRaises(ValueError):
            github.create_pr(self.gh(closed), "--head=x", "main", "t", "b")

    def test_pr_closed_before_this_run_is_skipped_but_not_a_merged_one(self):
        q = "repos/acme/app/pulls?head=acme%3Agld%2F42-os-permission&state=all"
        start = "2026-11-24T01:15:40Z"
        old = {"number": 70, "state": "closed", "html_url": "u70", "head": {"ref": BRANCH},
               "created_at": "2026-11-23T10:00:00Z", "merged_at": None}
        rules = self.rules([{"args": ["api", q], "json": [old]},
                            {"args": ["api", "-X", "POST", "repos/acme/app/pulls", "--input", "-"], "json": {"number": 71, "html_url": "u71"}}])
        self.assertEqual(github.create_pr(self.gh(rules), BRANCH, "main", "t", "b", not_before=start),
                         {"number": 71, "url": "u71"})
        for pr in (dict(old, created_at="2026-11-24T02:00:00Z"),       # closed during this run
                   dict(old, merged_at="2026-11-23T11:00:00Z")):     # merged earlier
            rules = self.rules([{"args": ["api", q], "json": [pr]}])
            with self.assertRaises(github.GhError):
                github.create_pr(self.gh(rules), BRANCH, "main", "t", "b", not_before=start)
        rules = self.rules([{"args": ["api", q], "json": [old]}])
        with self.assertRaises(github.GhError):
            github.create_pr(self.gh(rules), BRANCH, "main", "t", "b")


S3 = fakes.gh_fixture("issue-42-stage3.json")
S3_FAILS = fakes.gh_fixture("issue-42-stage3-create-fails.json")
KEY_D1 = "D1:0a1b2c3d"          # the marker the stage-3 fixture's second search returns (TF5)
NOW = "2026-11-25T01:02:03Z"


def item(key=KEY_D1, kind="bug", disposition="followup", title="Fix #12 for @alice", body="role note #3 @bob",
         labels=None, type_label="type:bug", target=None, private_path=False):
    labels = [github.FOLLOWUP_LABEL] if labels is None and disposition == "followup" else (labels or [])
    return {"key": key, "source": key.split(":")[0], "kind": kind, "disposition": disposition,
            "title": title if disposition == "followup" else None, "body": body, "labels": labels,
            "type_label": type_label if disposition == "followup" else None, "target": target,
            "private_path": private_path}


class Followups(Base):
    """Stage 3 V8 (E19–E21, A4): candidates, marker search, create / comment, labels, dry run (TF4–TF11)."""

    def setUp(self):
        super().setUp()
        self.tmp = os.path.realpath(self.tmp)       # fsafe refuses the /var → /private/var link on macOS
        self.log = os.path.join(self.tmp, "log")

    def apply(self, g, items, **kw):
        kw.setdefault("issue", 42)
        kw.setdefault("dry_run", False)
        kw.setdefault("now", lambda: NOW)
        return github.apply_followups(g, items, **kw)

    def posts(self, path):
        return [c for c in self.writes() if c["argv"][3] == "repos/acme/app/" + path]

    def test_candidates_merge_both_labels_newest_first(self):
        got = github.followup_candidates(self.gh(S3))
        self.assertEqual(got, [{"number": 81, "title": "Stable follow-up", "labels": ["type:bug"]},
                               {"number": 77, "title": "Old debt in src/a.py", "labels": ["guild:followup"]}])
        self.assertEqual([c["argv"][1] for c in self.calls()], [
            "repos/acme/app/issues?labels=guild%3Afollowup&state=open&sort=updated&direction=desc&per_page=30",
            "repos/acme/app/issues?labels=gx%3Afollowup&state=open&sort=updated&direction=desc&per_page=30"])  # promote: other
        self.assertEqual(self.writes(), [])
        with self.assertRaises(ValueError):
            github.followup_candidates(self.gh(S3), limit=0)

    def test_candidates_skip_pull_requests_and_closed_and_cut_at_the_limit(self):
        q = "repos/acme/app/issues?labels=%s&state=open&sort=updated&direction=desc&per_page=2"
        rows = [{"number": 5, "title": "pr", "pull_request": {}, "updated_at": "2026-11-25T00:00:00Z"},
                {"number": 6, "title": "a", "state": "open", "updated_at": "2026-11-20T00:00:00Z"},
                {"number": 7, "title": "b", "state": "closed", "updated_at": "2026-11-25T00:00:00Z"},
                {"number": 8, "title": "c", "state": "open", "updated_at": "2026-11-21T00:00:00Z", "labels": ["x"]}]
        path = self.rules([{"args": ["api", q % "guild%3Afollowup"], "json": rows},
                           {"args": ["api", q % "gx%3Afollowup"], "json": [rows[1]]}])  # promote: other
        self.assertEqual([c["number"] for c in github.followup_candidates(self.gh(path), limit=2)], [8, 6])

    def test_label_names_and_marker(self):
        self.assertEqual(github.label_names(self.gh(S3)), {"type:bug", "type:refactor", "guild:followup"})
        self.assertEqual(github.followup_marker(42, KEY_D1), "<!-- guild:followup origin=42 key=D1:0a1b2c3d -->")
        for bad in ("D0:0a1b2c3d", "D1:0A1B2C3D", "x:0a1b2c3d", "D1"):
            with self.assertRaises(ValueError):
                github.followup_marker(42, bad)
        k1 = github.followup_key("D1", {"kind": "bug", "note": "a"})
        self.assertRegex(k1, r"^D1:[0-9a-f]{8}$")
        self.assertEqual(k1, github.followup_key("D1", {"note": "a", "kind": "bug"}))
        self.assertNotEqual(k1, github.followup_key("D1", {"kind": "bug", "note": "b"}))
        self.assertRegex(github.followup_key("deferred", ["R3"]), r"^deferred:[0-9a-f]{8}$")
        with self.assertRaises(ValueError):
            github.followup_key("F1", {})

    def test_find_followup_reads_only_the_first_line(self):
        q = "repos/acme/app/issues?labels=guild%3Afollowup&state=all&per_page=100"
        marker = github.followup_marker(42, KEY_D1)
        path = self.rules([{"args": ["api", q, "--paginate"], "json": [
            {"number": 3, "body": "quoted:\n" + marker},
            {"number": 9, "body": marker + "\nbody"}, {"number": 4, "body": marker, "pull_request": {}}]}])
        self.assertEqual(github.find_followup(self.gh(path), marker), 9)

    def test_tf4_followup_and_duplicate_are_written_neutralised_with_the_marker_first(self):
        g = self.gh(S3)
        rows = []
        got = self.apply(g, [item(), item("D2:11111111", kind="debt", disposition="duplicate", target=77,
                                          body="same debt @carol")], on_row=rows.append)
        self.assertEqual(got, rows)
        self.assertEqual(got, [
            {"key": KEY_D1, "kind": "bug", "disposition": "followup", "number": 90, "comment_id": None,
             "dry_run": False, "private_path": False, "at": NOW},
            {"key": "D2:11111111", "kind": "debt", "disposition": "duplicate", "number": 77, "comment_id": 9101,
             "dry_run": False, "private_path": False, "at": NOW}])
        [made] = self.posts("issues")
        sent = json.loads(made["stdin"])
        self.assertEqual(sent["title"], "Fix ＃12 for ＠alice")
        self.assertEqual(sent["body"], github.followup_marker(42, KEY_D1) + "\nrole note ＃3 ＠bob")
        self.assertEqual(sent["labels"], ["guild:followup", "type:bug"])
        [comment] = self.posts("issues/77/comments")
        self.assertEqual(json.loads(comment["stdin"])["body"],
                         github.followup_marker(42, "D2:11111111") + "\nsame debt ＠carol")
        self.assertEqual(self.posts("labels"), [], "guild:followup already exists")
        self.assertEqual([c["argv"][1] for c in self.calls()].count("repos/acme/app/labels?per_page=100"), 1)

    def test_tf5_a_resume_after_a_crash_does_not_create_twice(self):
        def crash(row):
            raise KeyboardInterrupt("engine killed after the Issue was made")
        with self.assertRaises(KeyboardInterrupt):
            self.apply(self.gh(S3), [item()], on_row=crash)
        self.assertEqual(len(self.posts("issues")), 1)
        got = self.apply(self.gh(S3), [item()])          # resume: state.followups has nothing yet
        self.assertEqual(got[0]["number"], 90)
        self.assertEqual(len(self.posts("issues")), 1, "the marker search found the Issue")
        self.assertEqual(self.apply(self.gh(S3), [item()], done_keys=[KEY_D1]), [])

    def test_a_duplicate_comment_is_not_repeated(self):
        marker = github.followup_marker(42, "D2:11111111")
        path = self.rules([{"args": ["api", "repos/acme/app/labels?per_page=100", "--paginate"], "json": []},
                           {"args": ["api", "repos/acme/app/issues/77/comments", "--paginate"],
                            "json": [{"id": 4, "body": "hi"}, {"id": 8, "body": marker + "\nx"}]}])
        got = self.apply(self.gh(path), [item("D2:11111111", disposition="duplicate", target=77)])
        self.assertEqual((got[0]["number"], got[0]["comment_id"]), (77, 8))
        self.assertEqual(self.writes(), [])

    def test_tf8_private_security_followup_gets_the_security_label(self):
        it = item("D3:22222222", kind="security", labels=[github.FOLLOWUP_LABEL, github.SECURITY_LABEL])
        got = self.apply(self.gh(S3), [it])
        self.assertEqual(got[0]["number"], 90)
        [label] = self.posts("labels")
        self.assertEqual(json.loads(label["stdin"])["name"], "guild:security")
        self.assertEqual(json.loads(self.posts("issues")[0]["stdin"])["labels"],
                         ["guild:followup", "guild:security", "type:bug"])

    def test_tf9_private_path_writes_nothing_to_github(self):
        sec = os.path.join(self.tmp, "security-findings.md")
        got = self.apply(self.gh(S3), [item("D3:22222222", kind="security", private_path=True)],
                         security_md="# Security findings\n", security_path=sec)
        self.assertEqual(got[0]["number"], None)
        self.assertTrue(got[0]["private_path"])
        self.assertEqual(self.calls(), [], "not even a read")
        with open(sec, encoding="utf-8") as f:
            self.assertEqual(f.read(), "# Security findings\n")

    def test_tf10_a_failed_create_raises_and_keeps_the_rows_before(self):
        rows = []
        before = item("D2:11111111", kind="security", private_path=True)
        with self.assertRaises(github.GhError):
            self.apply(self.gh(S3_FAILS), [before, item(type_label="type:bug")], on_row=rows.append)
        self.assertEqual([r["key"] for r in rows], ["D2:11111111"])
        [failed] = self.posts("issues")
        self.assertEqual(json.loads(failed["stdin"])["labels"], ["guild:followup"], "type:bug does not exist there")

    def test_tf11_dry_run_records_and_writes_nothing(self):
        rec = os.path.join(self.tmp, defaults.FOLLOWUPS_DRY_RUN_FILE)
        items = [item(), item("D2:11111111", kind="debt", disposition="duplicate", target=77)]
        got = self.apply(self.gh(S3), items, dry_run=True, dry_run_path=rec)
        self.assertEqual([(r["number"], r["comment_id"], r["dry_run"]) for r in got], [(None, None, True)] * 2)
        self.assertEqual(self.writes(), [])
        self.assertEqual([c["argv"][1] for c in self.calls()], ["repos/acme/app/labels?per_page=100"])
        self.apply(self.gh(S3), items[:1], dry_run=True, dry_run_path=rec)    # a resume upserts by key
        with open(rec, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f]
        self.assertEqual([r["key"] for r in lines], ["D2:11111111", KEY_D1])
        made = lines[1]
        self.assertEqual((made["action"], made["title"], made["labels"]),
                         ("create-issue", "Fix ＃12 for ＠alice", ["guild:followup", "type:bug"]))
        self.assertEqual(made["body"], github.followup_marker(42, KEY_D1) + "\nrole note ＃3 ＠bob")
        self.assertEqual((lines[0]["action"], lines[0]["target"], lines[0]["title"]), ("comment", 77, None))
        with self.assertRaises(ValueError):
            self.apply(self.gh(S3), items, dry_run=True)

    def test_secret_stops_before_any_write_in_both_modes(self):
        rec = os.path.join(self.tmp, "dry.jsonl")
        for kw in ({}, {"dry_run": True, "dry_run_path": rec}):
            with self.assertRaises(outbound.SecretDetected):
                self.apply(self.gh(S3), [item(body=f"leaked {GH_PAT}")], **kw)
            with self.assertRaises(outbound.SecretDetected):
                self.apply(self.gh(S3), [item("D4:33333333", title=f"t {GH_PAT}")], **kw)
        self.assertEqual(self.writes(), [])
        self.assertFalse(os.path.exists(rec))

    def test_items_are_checked(self):
        g = self.gh(self.rules([]))
        for bad in ([item(), item()], [item(key="F1:00000000")], [item(disposition="ignore")],
                    [item(title="")], [item("D2:11111111", disposition="duplicate", target=None)]):
            with self.assertRaises(ValueError):
                self.apply(g, bad)
        self.assertEqual(self.calls(), [])

    def test_add_label_and_update_pr(self):
        path = self.rules([
            {"args": ["api", "repos/acme/app/labels/guild%3Airreversible"], "stderr": "gh: Not Found (HTTP 404)\n",
             "exit_code": 1},
            {"args": ["api", "-X", "POST", "repos/acme/app/labels", "--input", "-"], "json": {}},
            {"args": ["api", "-X", "POST", "repos/acme/app/issues/42/labels", "--input", "-"], "json": []},
            {"args": ["api", "-X", "PATCH", "repos/acme/app/pulls/7", "--input", "-"],
             "json": {"number": 7, "html_url": "u7"}},
            {"args": ["api", "-X", "PATCH", "repos/acme/app/pulls/8", "--input", "-"], "json": {"number": 9}}])
        g = self.gh(path)
        self.assertEqual(github.add_label(g, 42, github.IRREVERSIBLE_LABEL), "guild:irreversible")
        self.assertEqual(github.update_pr(g, 7, "see #90 @x", closes=42), {"number": 7, "url": "u7"})
        w = self.writes()
        self.assertEqual([c["argv"][3] for c in w], ["repos/acme/app/labels", "repos/acme/app/issues/42/labels",
                                                     "repos/acme/app/pulls/7"])
        self.assertEqual(json.loads(w[1]["stdin"]), {"labels": ["guild:irreversible"]})
        self.assertEqual(json.loads(w[2]["stdin"]), {"body": "see ＃90 ＠x\n\nCloses #42\n"})
        with self.assertRaises(github.GhError):
            github.update_pr(g, 8, "x")
        with self.assertRaises(outbound.SecretDetected):
            github.update_pr(g, 7, GH_PAT)
        with self.assertRaises(ValueError):
            github.add_label(g, 42, "bad\nlabel")

    def test_prbody_items_run_through_the_op(self):
        from gxengine import prbody
        index = [{"id": "D1", "kind": "bug", "where": "a.py", "blocks_current_ac": False, "role": "auditor",
                  "note": "n1"},
                 {"id": "D2", "kind": "security", "where": "b.py", "blocks_current_ac": False, "role": "auditor",
                  "note": "secret-ish detail"},
                 {"id": "D3", "kind": "debt", "where": "c.py", "blocks_current_ac": False, "role": "developer",
                  "note": "n3"}]
        answer = {"answer": "approve", "note": "ok", "discoveries": [
            {"id": "D1", "disposition": "followup", "title": "Bug in a", "duplicate_of": None},
            {"id": "D2", "disposition": "followup", "title": "Sec", "duplicate_of": None},
            {"id": "D3", "disposition": "duplicate", "title": None, "duplicate_of": 77}]}
        items = prbody.followup_items(42, 7, index, answer, is_private=None)
        sec = os.path.join(self.tmp, defaults.SECURITY_FINDINGS_FILE)
        rows = self.apply(self.gh(S3), items, security_md=prbody.security_findings_md(42, index, answer),
                          security_path=sec)
        self.assertEqual([(r["number"], r["private_path"]) for r in rows], [(90, False), (None, True), (77, False)])
        sent = " ".join(c["stdin"] or "" for c in self.writes())
        self.assertNotIn("secret-ish detail", sent)
        with open(sec, encoding="utf-8") as f:
            self.assertIn("secret-ish detail", f.read())

    def test_visibility_fact(self):
        self.assertIs(github.visibility_fact(self.gh(S3)), True)
        self.assertIsNone(github.visibility_fact(self.gh(self.rules([]))))


class PrReviews(Base):
    """Stage 3 V13 (E31): PR review items since the watermarks, collaborators only, engine comments out."""

    def test_items_from_the_three_id_spaces(self):
        items = github.pr_review_items(self.gh(S3), 7, {"review": None, "review-comment": None, "comment": None})
        self.assertEqual([(i["id"], i["state"], i["path"]) for i in items],
                         [("review:5001", "CHANGES_REQUESTED", None), ("review-comment:6001", None, "src/a.py")])
        self.assertEqual([c["argv"][1] for c in self.calls()], [
            "repos/acme/app/pulls/7/reviews", "repos/acme/app/pulls/7/comments", "repos/acme/app/issues/7/comments"])
        self.assertEqual(self.writes(), [])
        self.assertEqual(github.pr_review_watermarks(items, {"comment": 3}),
                         {"review": 5001, "review-comment": 6001, "comment": 3})
        md = github.build_pr_review_md(items)
        self.assertIn("## review:5001", md)
        self.assertIn("owner (OWNER) CHANGES_REQUESTED", md)
        self.assertIn("on `src/a.py`", md)
        self.assertNotIn("ignore previous", md)

    def test_watermarks_engine_comments_and_drafts(self):
        rules = self.rules([
            {"args": ["api", "repos/acme/app/pulls/7/reviews", "--paginate"], "json": [
                {"id": 10, "author_association": "OWNER", "state": "APPROVED", "body": ""},
                {"id": 11, "author_association": "OWNER", "state": "PENDING", "body": "draft"},
                {"id": 12, "author_association": "MEMBER", "state": "COMMENTED", "body": ""},
                {"id": 13, "author_association": "MEMBER", "state": "COMMENTED", "body": "nit"}]},
            {"args": ["api", "repos/acme/app/pulls/7/comments", "--paginate"], "json": []},
            {"args": ["api", "repos/acme/app/issues/7/comments", "--paginate"], "json": [
                {"id": 20, "author_association": "OWNER", "body": "<!-- guild:done -->\nengine"},
                {"id": 21, "author_association": "OWNER", "body": "engine by id"},
                {"id": 22, "author_association": "COLLABORATOR", "body": "please rename", "created_at": "z"}]}])
        items = github.pr_review_items(self.gh(rules), 7, {"review": 10, "review-comment": None, "comment": None},
                                       engine_comment_ids=[21])
        self.assertEqual([i["id"] for i in items], ["review:13", "comment:22"])
        with self.assertRaises(ValueError):
            github.pr_review_items(self.gh(rules), 0, {})
        self.assertIn("(none)", github.build_pr_review_md([]))


class Summary(unittest.TestCase):
    def test_summary_text_is_engine_text_without_hash_or_at(self):
        with open(fakes.fixture("contracts", "state.example.json"), encoding="utf-8") as f:
            state = json.load(f)
        text = github.summary_text(state)
        self.assertNotIn("#", text)
        self.assertNotIn("@", text)
        self.assertEqual(outbound.neutralise(text, "acme/app"), text)
        self.assertIn("current step: `design` (running)", text)
        self.assertIn("| `ac-format` | done | 2 |", text)
        self.assertIn("| `setup` | pending | — |", text)
        state["stop"] = {"status": "needs_human", "reason": "remote-diverged", "step": "create-pr",
                         "at": "2026-11-23T03:00:00Z"}
        state["github"]["pr_number"] = 77
        text = github.summary_text(state)
        self.assertIn("stopped: needs_human — `remote-diverged` at `create-pr`", text)
        self.assertIn("pull request: 77", text)


if __name__ == "__main__":
    unittest.main()
