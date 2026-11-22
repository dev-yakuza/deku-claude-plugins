"""0.102.13 — the review-0102-12 fixes (B1, B2, M1–M4, m1–m7), through the real code paths (the role runner's result
reading and scope revert, the design gate and the test stage's units, the integrity hash, the missing-ignored-input
reading, the cover name check, the QA follow-ups, the Corepack classification and seed, the traceback redaction). The
reviewer's repros (scratchpad `r0102_12/`) are the first tests of their classes; each failed on 0.102.12 (`c5d2874`).
Two of them were controls that pinned the OLD behaviour the lead decision changes — kept here in their new form (B1:
the design specialist schema now requires its file or `none_applicable`; M1: the design gate now refuses prose AC
mentions; R1797: a read failure counts only for a file the main checkout really holds).

Lead decisions (k6-notes "0.102.13"):
B1  out/result.json stands in for an unreadable status line ONLY when (a) the final message has no BLOCKED / FAIL /
    NEEDS_CONTEXT / HALTED token anywhere (any case or form), (b) at most one RESULT marker, (c) the task's schema has
    required fields, all present and non-empty (SPECIALIST_SCHEMA / PO_SCHEMA now have them); else the repair session
    (0.102.11). A lowercase / variant BLOCKED / FAIL status line is read as BLOCKED / FAIL, never DONE.
B2/M2  the copies of reverted files go to an engine-owned dir outside the role-writable tree (`<issue>/reverted/<run>`),
    made and written with fsafe; the revert never follows a link (a link is recorded as a link, its target never read)
    and never opens a FIFO / device (recorded, left in place).
M1  prose AC mentions do not satisfy the design gate (tag / list / table entries only); the untagged-legacy soft rule
    only for a test-cases.md that exists at the base commit.
M3  the integrity hash of local git config covers execution-relevant keys only (branch.*, remote.*.fetch, gc.*,
    maintenance.*, vscode-* bookkeeping out; unknown keys in).
M4  a skipped ignored path is a missing input only on a read-failure (not write) line, still absent from the temp tree
    after the run and present as a git-ignored file in the main checkout; tool outputs never.
minor  DWC concerns into design's concern list; repo.yarnpkg.com for yarn ≥ 2; cover names by the file's real
    group / test structure; an object-shaped followups.json read or recorded; `Usage Error: This project is configured
    to use` a package-manager mismatch; traceback redaction over the whole text; the Corepack seed from the user's
    `v1/` layout (read-only copy works offline).
"""

import json
import os
import stat
import subprocess
import unittest
from unittest import mock

import _util  # noqa: F401
from _k1 import FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir

from guildcore.checks import pmcache as PMC
from guildcore.roles import result as R
from guildcore.roles import runner as RR
from guildcore.roles import scope as SC
from workflows.dev import cases as CS
from workflows.dev import escalation as ESC
from workflows.dev import handoff as HO
from workflows.dev import ports as PO
from workflows.dev import preflight as PF
from workflows.dev.stages import test as T

GATE = ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "FAIL")      # execute.gates_step
LINES = ["BLOCKED", "BLOCKED.  the token is written to the log", "Status: BLOCKED — the token is written to the log",
         "blocked: the token is written to the log", "BLOCKED → the token is written to the log",
         "FAIL. could not finish the review"]


def _settings(case):
    user = os.path.join(tmpdir(case), "settings.json")
    with open(user, "w") as fh:
        fh.write("{}")
    return user


# ---- B1: an unreadable BLOCKED / FAIL line is never DONE --------------------------------------------------------------

class B1BlockedNeverDone(unittest.TestCase):
    def setUp(self):
        self.wt = repo(self, {"lib/a.dart": "a\n"})
        git(self.wt, "switch", "-q", "-c", "feat")
        self.user = _settings(self)

    def _run(self, reply, result=None, schema=None, allowed=GATE, second=">>> RESULT <<<\nBLOCKED: token logged"):
        root = os.path.join(tmpdir(self), "runs")
        rd = os.path.join(root, "001-execute-security-review")
        files = {os.path.join(rd, "out", "result.json"): json.dumps(result or {
            "file": "out/security.md", "evidence": "lib/a.dart:1 logs the token"}),
            os.path.join(rd, "out", "security.md"): "# security\nBLOCKER: token logged\n"}
        self.spawn = FakeSpawn([{"stream": stream_lines(texts=[reply]), "files": files},
                                {"stream": stream_lines(texts=[second])}])
        r = RR.Runner(journal=RecJournal(), common_dir=tmpdir(self), parent_env={"PATH": os.environ["PATH"]},
                      spawn=self.spawn, user_settings=self.user, run_root_dir=root, claude="claude")
        return r.run_role(RR.RoleSpec("security", "review", "t", issue=9, stage="execute", step="X3.5b",
                                      worktree=self.wt, model="sonnet", base="HEAD", branch="feat", remote_check=False,
                                      result_schema=schema or R.RESULT_SCHEMAS["specialist"], allowed_status=allowed))

    def test_r0102_12_an_unreadable_blocked_line_is_never_done(self):
        bad = []
        for ln in LINES:
            res = self._run("review done.\n>>> RESULT <<<\n" + ln)
            if res.status.startswith("DONE"):
                bad.append((ln, res.status, res.line))
        self.assertEqual(bad, [])

    def test_r0102_12_a_second_sentinel_saying_blocked_is_never_done(self):
        res = self._run(">>> RESULT <<<\nDONE: draft\n\nOn second thought:\n>>> RESULT <<<\nBLOCKED: token logged")
        self.assertFalse(res.status.startswith("DONE"), (res.status, res.line))
        self.assertEqual(len(self.spawn.calls), 2)                        # the repair session (0.102.11)

    def test_r0102_12_the_design_specialist_schema_requires_its_file(self):
        from workflows.dev.stages import design as D
        self.assertTrue(R.validate({"evidence": "x"}, D.SPECIALIST_SCHEMA, None))     # changed: was [] on 0.102.12
        self.assertEqual(R.validate({"file": "out/ux.md"}, D.SPECIALIST_SCHEMA, None), [])
        self.assertEqual(R.validate({"none_applicable": True}, D.SPECIALIST_SCHEMA, None), [])
        p = R.parse_pres(">>> RESULT <<<\nBLOCKED", R.STATUSES)
        alt = R.structured_pres(p, {"evidence": "x"}, R.STATUSES, ">>> RESULT <<<\nBLOCKED", D.SPECIALIST_SCHEMA)
        self.assertTrue(alt is None or alt.status != "DONE", alt and alt.line)

    def test_r0102_12_a_disallowed_fail_line_is_not_overridden_by_a_json_status(self):
        qa = ("DONE", "DONE_WITH_CONCERNS", "BLOCKED")
        reply = ">>> RESULT <<<\nFAIL: the app crashes on launch"
        p = R.parse_pres(reply, qa)
        alt = R.structured_pres(p, {"status": "DONE", "plan": "x", "human_items": ["y"]}, qa, reply,
                                R.RESULT_SCHEMAS["qa"])
        self.assertTrue(alt is None or alt.status != "DONE", alt and alt.line)

    def test_r0102_12_a_bare_concerns_line_keeps_its_concern(self):
        reply = ">>> RESULT <<<\n**DONE_WITH_CONCERNS**\n- the e2e never ran"
        p = R.parse_pres(reply, R.STATUSES)
        alt = R.structured_pres(p, {"file": "x"}, R.STATUSES, reply, R.RESULT_SCHEMAS["specialist"])
        self.assertTrue(alt is None or alt.status != "DONE", alt and alt.line)

    def test_variant_lines_parse_as_that_status(self):
        for ln, want in (("BLOCKED", ("BLOCKED", None)), ("blocked: x", ("BLOCKED", "x")),
                         ("Status: BLOCKED — x", ("BLOCKED", "x")), ("BLOCKED.  x", ("BLOCKED", "x")),
                         ("BLOCKED → x", ("BLOCKED", "x")), ("FAIL. x", ("FAIL", "x")), ("failed: x", ("FAIL", "x")),
                         ("**Blocked**: x", ("BLOCKED", "x")), ("needs context: x", ("NEEDS_CONTEXT", "x"))):
            p = R.parse_pres(">>> RESULT <<<\n" + ln)
            self.assertEqual((p.ok, p.status, p.text), (True,) + want, ln)
        for ln in ("Failing tests fixed — all green", "DONEX", "done"):
            self.assertFalse(R.parse_pres(">>> RESULT <<<\n" + ln).ok, ln)

    def test_a_token_anywhere_in_the_reply_means_repair(self):
        s = R.RESULT_SCHEMAS["tech-lead"]
        for reply in ("The build failed once.\n>>> RESULT <<<\nAll set", "Halted on review.\nall set",
                      "needs_context?\n>>> RESULT <<<\nok"):
            p = R.parse_pres(reply, R.STATUSES)
            self.assertIsNone(R.structured_pres(p, {"skeleton": "out/s.md"}, R.STATUSES, reply, s), reply)
        reply = "skeleton written.\n>>> RESULT <<<\nAll set"
        p = R.parse_pres(reply, R.STATUSES)
        self.assertEqual(R.structured_pres(p, {"skeleton": "out/s.md"}, R.STATUSES, reply, s).status, "DONE")

    def test_required_fields_must_be_present_and_non_empty(self):
        reply = "work done\n>>> RESULT <<<\nall set"
        p = R.parse_pres(reply, R.STATUSES)
        no_req = {"type": "object", "properties": {"a": {"type": "string"}}}
        self.assertIsNone(R.structured_pres(p, {"a": "x"}, R.STATUSES, reply, no_req))
        self.assertIsNone(R.structured_pres(p, {"skeleton": ""}, R.STATUSES, reply, R.RESULT_SCHEMAS["tech-lead"]))
        self.assertIsNone(R.structured_pres(p, {"plan": "x", "human_items": []}, R.STATUSES, reply,
                                            R.RESULT_SCHEMAS["qa"]))
        from workflows.dev.stages import analyze as A
        self.assertEqual(A.PO_SCHEMA.get("required"), ["ac_patch", "non_goals"])
        self.assertTrue(R.validate({"evidence": "x"}, A.PO_SCHEMA, None))
        self.assertIsNotNone(R.structured_pres(p, {"ac_patch": [{"id": "AC #1", "text": "t"}], "non_goals": ["n"]},
                                               R.STATUSES, reply, A.PO_SCHEMA))

    def test_a_runner_reply_with_a_blocked_word_takes_the_repair_session(self):
        res = self._run("I was blocked by the sandbox for a while.\n>>> RESULT <<<\nreview complete",
                        second=">>> RESULT <<<\nDONE: reviewed")
        self.assertEqual((res.status, len(self.spawn.calls)), ("DONE", 2))

    def test_the_687_reply_still_takes_one_session(self):
        reply = _read_fixture("one-man-company-687-tech-lead-reply.txt")
        from workflows.dev.stages import design as D
        res = self._run(reply, result={"skeleton": "out/security.md"}, schema=R.RESULT_SCHEMAS["tech-lead"],
                        allowed=D.TL_STATUSES)
        self.assertEqual((res.status, len(self.spawn.calls)), ("DONE", 1))
        self.assertTrue(res.line.startswith("DONE: concerns — "), res.line)


def _read_fixture(name):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "engine", "real", name)
    with open(p, encoding="utf-8") as fh:
        return fh.read()


class m1DesignConcerns(unittest.TestCase):
    def test_a_narrowed_tech_lead_concern_is_a_design_concern(self):
        import test_k4_design as K4D
        from _k4 import out_role, tester_ok
        from workflows.dev.stages import design as D
        tl = out_role(self, "DONE", "DONE: concerns — 실질 macOS 한정",                 # the runner's narrowed line
                      files={"skeleton.md": "# Skeleton\n- [ ] Home.count stays in lib/app\n",
                             "split.json": {"split": False}},
                      skeleton="out/skeleton.md", split_path="out/split.json")
        h = K4D.design_h(self, roles=[tester_ok(self, (1, 2), visual=True), tl, K4D.spec_ok(self)])
        D.run(h.p)
        out = h.body_with("design:output")
        self.assertIn("### 우려", out)
        self.assertIn("tech-lead: DONE: concerns — 실질 macOS 한정", out)


# ---- B2 / M2: the revert's copies — engine-owned, never through a link ------------------------------------------------

class B2KeepDirIsEngineOwned(unittest.TestCase):
    def test_r0102_12_the_engine_never_writes_through_a_link_in_out(self):
        main = repo(self, {"lib/a.dart": "a\n", "test/a_test.dart": "t\n"})
        wt = os.path.join(tmpdir(self), "wt")
        git(main, "worktree", "add", "-q", "-b", "feat", wt)
        victim = os.path.join(tmpdir(self), "victim-home-ssh")
        os.makedirs(victim)
        inner = FakeSpawn([{"stream": stream_lines(texts=[">>> RESULT <<<\nDONE: ok"])}])

        def spawn(argv, env, cwd, stdin_text, stdout_path, *a, **k):
            out = os.path.join(os.path.dirname(stdout_path), "out")
            os.makedirs(out, exist_ok=True)
            os.symlink(victim, os.path.join(out, "reverted"))
            with open(os.path.join(cwd, "authorized_keys"), "w") as fh:
                fh.write("ssh-ed25519 AAAA attacker\n")
            return inner(argv, env, cwd, stdin_text, stdout_path, *a, **k)
        runs = os.path.join(tmpdir(self), "issue", "runs")
        r = RR.Runner(journal=RecJournal(), common_dir=tmpdir(self), parent_env={"PATH": os.environ["PATH"]},
                      spawn=spawn, user_settings=_settings(self), run_root_dir=runs, claude="claude")
        res = r.run_role(RR.RoleSpec("tester", "verify", "t", issue=7, stage="test", step="T1", worktree=wt,
                                     model="sonnet", base="HEAD", branch="feat", remote_check=False))
        self.assertEqual(sorted(os.listdir(victim)), [], "engine wrote %s (status %s)" % (os.listdir(victim), res.status))
        # the copy is in the engine's own dir beside runs/, the worktree clean again
        self.assertEqual(res.reverted_dir, os.path.join(os.path.dirname(runs), "reverted", os.path.basename(res.run_dir)))
        with open(os.path.join(res.reverted_dir, "authorized_keys")) as fh:
            self.assertIn("attacker", fh.read())
        self.assertFalse(os.path.exists(os.path.join(wt, "authorized_keys")))

    def test_the_keep_dir_is_made_without_following_a_link(self):
        base = tmpdir(self)
        runs = os.path.join(base, "runs")
        os.makedirs(os.path.join(runs, "001-test-tester-verify"))
        victim = tmpdir(self)
        os.symlink(victim, os.path.join(base, "reverted"))
        from guildcore import fsafe as FS
        with self.assertRaises(FS.UnsafePath):
            RR.reverted_keep_dir(os.path.join(runs, "001-test-tester-verify"))
        self.assertEqual(os.listdir(victim), [])

    def test_a_link_keep_dir_reverts_nothing(self):
        wt = repo(self, {"lib/a.dart": "a\n"})
        with open(os.path.join(wt, "new.txt"), "w") as fh:
            fh.write("n\n")
        victim = tmpdir(self)
        keep = os.path.join(tmpdir(self), "keep")
        os.symlink(victim, keep)
        self.assertEqual(SC.revert_writes(wt, ["new.txt"], keep_dir=keep, after=SC.snapshot(wt)), [])
        self.assertEqual(os.listdir(victim), [])
        self.assertTrue(os.path.exists(os.path.join(wt, "new.txt")))

    def test_a_link_inside_the_keep_dir_is_refused(self):
        wt = repo(self, {"lib/a.dart": "a\n"})
        os.makedirs(os.path.join(wt, "lib2"))
        with open(os.path.join(wt, "lib2", "x.txt"), "w") as fh:
            fh.write("x\n")
        keep = tmpdir(self)
        victim = tmpdir(self)
        os.symlink(victim, os.path.join(keep, "lib2"))               # planted beforehand: never trusted
        got = SC.revert_writes(wt, ["lib2/x.txt"], keep_dir=keep, after=SC.snapshot(wt))
        self.assertEqual(got, [])                                    # not copied → not reverted
        self.assertEqual(os.listdir(victim), [])
        self.assertTrue(os.path.exists(os.path.join(wt, "lib2", "x.txt")))


SECRET = "-----BEGIN OPENSSH PRIVATE KEY----- b3BlbnNzaC1rZXktdjEAAAAABG5vbmU= not-for-the-role\n"


class M2RevertNeverFollowsALink(unittest.TestCase):
    def test_r0102_12_a_link_is_never_read_or_copied(self):
        wt = repo(self, {"lib/a.dart": "a\n"})
        sec = os.path.join(tmpdir(self), "id_ed25519")
        with open(sec, "w") as fh:
            fh.write(SECRET)
        os.symlink(sec, os.path.join(wt, "release_notes.txt"))
        after = SC.snapshot(wt)
        keep = os.path.join(tmpdir(self), "run", "out", "reverted")
        got = SC.revert_writes(wt, ["release_notes.txt"], keep_dir=keep, after=after)
        texts = " ".join(t for _p, t in got)
        copied = ""
        cp = os.path.join(keep, "release_notes.txt")
        if os.path.isfile(cp) and not os.path.islink(cp):
            copied = open(cp).read()
        self.assertNotIn("not-for-the-role", texts + copied, (got, copied[:60]))
        self.assertTrue(os.path.exists(sec))
        # recorded as a link (its target string), removed as a link
        man = json.load(open(os.path.join(keep, "manifest.json")))
        self.assertEqual((man[0]["kind"], man[0]["link"], man[0]["copy"]), ("link", sec, None))
        self.assertEqual(got, [("release_notes.txt", "(symlink to %s)" % sec)])
        self.assertFalse(os.path.lexists(os.path.join(wt, "release_notes.txt")))

    def test_a_tracked_file_replaced_by_a_link_is_restored_without_reading_the_target(self):
        wt = repo(self, {"notes.txt": "orig\n"})
        sec = os.path.join(tmpdir(self), "secret")
        with open(sec, "w") as fh:
            fh.write("not-for-the-role\n")
        os.remove(os.path.join(wt, "notes.txt"))
        os.symlink(sec, os.path.join(wt, "notes.txt"))
        keep = tmpdir(self)
        got = SC.revert_writes(wt, ["notes.txt"], keep_dir=keep, after=SC.snapshot(wt))
        self.assertNotIn("not-for-the-role", " ".join(t for _p, t in got))
        for base, _d, files in os.walk(keep):
            for f in files:
                self.assertNotIn("not-for-the-role", open(os.path.join(base, f), errors="replace").read(), f)
        self.assertFalse(os.path.islink(os.path.join(wt, "notes.txt")))
        self.assertEqual(open(os.path.join(wt, "notes.txt")).read(), "orig\n")
        self.assertEqual(open(sec).read(), "not-for-the-role\n")

    def test_a_link_to_a_fifo_never_blocks(self):
        wt = repo(self, {"lib/a.dart": "a\n"})
        fifo = os.path.join(tmpdir(self), "pipe")
        os.mkfifo(fifo)
        os.symlink(fifo, os.path.join(wt, "notes.txt"))
        got = SC.revert_writes(wt, ["notes.txt"], keep_dir=tmpdir(self), after=SC.snapshot(wt))
        self.assertEqual(got, [("notes.txt", "(symlink to %s)" % fifo)])

    def test_a_fifo_is_never_opened_and_stays(self):
        wt = repo(self, {"lib/a.dart": "a\n"})
        os.mkfifo(os.path.join(wt, "pipe"))
        keep = tmpdir(self)
        got = SC.revert_writes(wt, ["pipe"], keep_dir=keep, after=SC.snapshot(wt))
        self.assertEqual(got, [])
        self.assertTrue(stat.S_ISFIFO(os.lstat(os.path.join(wt, "pipe")).st_mode))
        man = json.load(open(os.path.join(keep, "manifest.json")))
        self.assertEqual(man[0]["kind"], "fifo")
        self.assertIn("never opened", man[0]["error"])


# ---- M1: the design gate and the legacy soft rule ---------------------------------------------------------------------

DOC = ("# Test cases — #42\nScope: AC #1, AC #2, AC #3.\n\n"
       "- C1: the badge shows the allowed state\n- C2: the button opens the OS settings\n")
ACS = ["AC #1", "AC #2", "AC #3"]


class M1FreshDocuments(unittest.TestCase):
    def test_r0102_12_the_design_gate_refuses_prose_mentions(self):
        bad = HO.cases_bad(DOC, [1, 2, 3], False)                      # changed: passed on 0.102.12
        self.assertEqual(len(bad), 1)
        self.assertIn("#1, #2, #3", bad[0])

    def test_r0102_12_an_ac_without_any_case_stays_a_hard_unit(self):
        units, _m, _a = CS.judged_units(DOC, (), ACS)
        self.assertIn("AC #3", units, "units %s" % units)
        self.assertEqual(CS.soft_units(DOC, units, ACS), [])

    def test_tags_lists_and_table_rows_pass_the_gate(self):
        doc = ("- C1 [AC #1] a\n| C2 | AC #2 | b |\n- AC #3: c\n")
        self.assertEqual(HO.cases_bad(doc, [1, 2, 3], False), [])
        self.assertTrue(HO.cases_bad("| C1 | 1 | a |\n| C2 | 2 | b |\n", [1, 2], False))   # a number column is no tag

    def test_legacy_means_present_at_the_base_commit(self):
        class P(object):
            pass
        d = repo(self, {"docs/specs/7/test-cases.md": "| C1 | a |\n", "a.txt": "a\n"})
        p = P()
        p.root = d
        p.base = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=d, stdout=subprocess.PIPE,
                                universal_newlines=True).stdout.strip()
        git(d, "switch", "-q", "-c", "feat")
        self.assertTrue(T.doc_predates_run(p, "docs/specs/7/test-cases.md"))
        os.makedirs(os.path.join(d, "docs", "specs", "8"))
        with open(os.path.join(d, "docs", "specs", "8", "test-cases.md"), "w") as fh:
            fh.write("| C1 | a |\n")
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "this run's doc")
        self.assertFalse(T.doc_predates_run(p, "docs/specs/8/test-cases.md"))
        p.base = None
        self.assertFalse(T.doc_predates_run(p, "docs/specs/7/test-cases.md"))


# ---- M3: branch bookkeeping is no drift -------------------------------------------------------------------------------

class M3ConfigBookkeeping(unittest.TestCase):
    def test_r0102_12_a_branch_section_change_is_not_an_integrity_change(self):
        wt = repo(self, {"a.txt": "a\n"})
        git(wt, "branch", "tmp/integration-check")
        git(wt, "config", "branch.tmp/integration-check.remote", "origin")
        git(wt, "config", "branch.tmp/integration-check.merge", "refs/heads/tmp/integration-check")
        before = SC.integrity(wt)
        git(wt, "branch", "-D", "tmp/integration-check")
        git(wt, "config", "branch.main.vscode-merge-base", "origin/main")
        after = SC.integrity(wt)
        self.assertEqual({k: v for k, v in after.items() if before.get(k) != v}, {})

    def test_r0102_12_control_a_hooks_path_change_still_is(self):
        wt = repo(self, {"a.txt": "a\n"})
        before = SC.integrity(wt)
        git(wt, "config", "core.hooksPath", "/tmp/evil-hooks")
        self.assertNotEqual(before, SC.integrity(wt))

    def test_bookkeeping_out_execution_keys_and_unknown_keys_in(self):
        wt = repo(self, {"a.txt": "a\n"})
        for k, v in (("remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"), ("gc.auto", "0"),
                     ("maintenance.strategy", "incremental"), ("branch.x.merge", "refs/heads/x")):
            before = SC.integrity(wt)
            git(wt, "config", k, v)
            self.assertEqual(before, SC.integrity(wt), k)
        for k, v in (("include.path", "/tmp/x.inc"), ("alias.st", "!sh -c id"), ("filter.lfs.clean", "cat"),
                     ("diff.png.textconv", "cat"), ("url.https://evil/.insteadOf", "https://github.com/"),
                     ("credential.helper", "store"), ("remote.origin.url", "https://evil/x.git"),
                     ("core.fsmonitor", "/tmp/m"), ("core.sshCommand", "ssh -i x"), ("zzz.unknown", "1")):
            before = SC.integrity(wt)
            git(wt, "config", k, v)
            self.assertNotEqual(before, SC.integrity(wt), k)


# ---- M4: a tool-written log is no missing input ----------------------------------------------------------------------

RAW = ("00:28 +1107 -1: test/a_test.dart: x\n"
       "Oops; flutter has exited unexpectedly: \"Bad state: LiveTest.run() may not be called for a closed test.\".\n"
       "A crash report has been written to %s/flutter_01.log\n")


class M4MissingIgnored(unittest.TestCase):
    def test_r0102_12_a_log_the_run_wrote_is_not_a_missing_input(self):
        root = repo(self, {".gitignore": "*.log\n", "a.txt": "a\n"})
        with open(os.path.join(root, "flutter_01.log"), "w") as fh:
            fh.write("old crash\n")
        tree = root + "-tree"
        self.assertEqual(PF.missing_ignored(RAW % tree, root, ["flutter_01.log"], tree), [])

    def test_r0102_12_control_a_read_failure_still_counts(self):
        # changed: condition (3) — the main checkout must hold the ignored file (the reviewer's control had none)
        root = repo(self, {".gitignore": "*.env\n", "a.txt": "a\n"})
        os.makedirs(os.path.join(root, "assets"))
        with open(os.path.join(root, "assets", "app.env"), "w") as fh:
            fh.write("K=v\n")
        raw = "Error when reading 'assets/app.env': No such file or directory\n"
        self.assertEqual(PF.missing_ignored(raw, root, ["assets/app.env"], root + "-tree"), ["assets/app.env"])

    def test_the_three_conditions(self):
        root = repo(self, {".gitignore": "*.env\nsecrets/\n", "a.txt": "a\n"})
        os.makedirs(os.path.join(root, "secrets"))
        for rel in ("x.env", "secrets/k.json"):
            with open(os.path.join(root, rel), "w") as fh:
                fh.write("v\n")
        tree = tmpdir(self)
        # (1) a mention that is no read failure, or a write
        self.assertEqual(PF.missing_ignored("loaded x.env fine\n", root, ["x.env"], tree), [])
        self.assertEqual(PF.missing_ignored("Writing x.env: not found before, created\n", root, ["x.env"], tree), [])
        self.assertEqual(PF.missing_ignored("Cannot open x.env\n", root, ["x.env"], tree), ["x.env"])
        # (2) the run made it — present in the temp tree after the run
        with open(os.path.join(tree, "x.env"), "w") as fh:
            fh.write("v\n")
        self.assertEqual(PF.missing_ignored("Cannot open x.env\n", root, ["x.env"], tree), [])
        # (3) not in the main checkout
        self.assertEqual(PF.missing_ignored("ENOENT: secrets/none.json\n", root, ["secrets/none.json"], tmpdir(self)), [])
        self.assertEqual(PF.missing_ignored("ENOENT: secrets/k.json\n", root, ["secrets/k.json"], tmpdir(self)),
                         ["secrets/k.json"])

    def test_tool_outputs_never_count(self):
        root = repo(self, {".gitignore": "*.log\nbuild/\n.dart_tool/\ncoverage/\n", "a.txt": "a\n"})
        rels = ["flutter_03.log", "run.log", "build/app.dill", ".dart_tool/pc.json", "coverage/lcov.info",
                "pkg/flutter_01.log"]
        for rel in rels:
            os.makedirs(os.path.dirname(os.path.join(root, rel)) or root, exist_ok=True)
            with open(os.path.join(root, rel), "w") as fh:
                fh.write("x\n")
        raw = "".join("Cannot open %s: No such file\n" % r for r in rels)
        self.assertEqual(PF.missing_ignored(raw, root, rels, tmpdir(self)), [])


# ---- minors -----------------------------------------------------------------------------------------------------------

SRC = """void main() {
  group('SettingsScreen', () {
    testWidgets('shows the badge', (t) async {
      await t.pumpWidget(const App(locale: 'ko'));
      expect(find.text('허용됨'), findsOneWidget);
    });
    group('when denied', () {
      test('shows the $count prompt', () {});
    });
  });
  // group('Commented', () { test('ghost', () {}); });
}
"""


class m3CoverStructure(unittest.TestCase):
    def test_r0102_12_a_name_made_of_unrelated_literals_is_no_test(self):
        self.assertFalse(T.name_in_source(SRC, "SettingsScreen 허용됨", "flutter"))
        self.assertFalse(T.name_in_source(SRC, "ko 허용됨", "flutter"))

    def test_r0102_12_a_wrong_group_is_no_test(self):
        self.assertFalse(T.name_in_source(SRC, "OtherScreen › shows the badge", "flutter"))

    def test_real_structures_are_tests(self):
        for name in ("shows the badge", "SettingsScreen shows the badge", "SettingsScreen › shows the badge",
                     "SettingsScreen > when denied > shows the $count prompt", "when denied shows the 3 prompt",
                     "SettingsScreen when denied shows the 7 prompt"):
            self.assertTrue(T.name_in_source(SRC, name, "flutter"), name)
        for name in ("when denied shows a badge", "shows the badge SettingsScreen", "Commented ghost", "ghost",
                     "SettingsScreen"):
            self.assertFalse(T.name_in_source(SRC, name, "flutter"), name)

    def test_jest_describe_it(self):
        js = "describe('Cart', () => {\n  it.each([1])('adds %s item', () => {});\n  it('empties', () => {});\n});\n"
        self.assertTrue(T.name_in_source(js, "Cart empties", "jest"))
        self.assertFalse(T.name_in_source(js, "Other empties", "jest"))


class m4FollowupsObject(unittest.TestCase):
    def _r(self, v):
        class R_(object):
            extras = {"followups": v}
        return R_()

    def test_r0102_12_a_followups_object_is_not_silently_dropped(self):
        from workflows.dev.stages import qa as Q
        got = Q._followup_items(self._r({"followups": [{"title": "fix the toggle", "keywords": ["toggle"]}]}))
        self.assertEqual(got, [{"title": "fix the toggle", "rationale": None, "keywords": "toggle"}])

    def test_an_unreadable_shape_is_recorded(self):
        from workflows.dev.stages import qa as Q
        rec = []

        class P(object):
            class decisions(object):
                @staticmethod
                def record(f):
                    rec.append(f)
        self.assertEqual(Q._followup_items(self._r({"other": 1}), P()), [])
        self.assertEqual(Q._followup_items(self._r(42), P()), [])
        self.assertEqual([r_["point"] for r_ in rec], ["followups-unreadable"] * 2)
        self.assertIn("keys: other", rec[0]["reason"])


class m5Mismatch(unittest.TestCase):
    RAW = ("$ yarn test\nUsage Error: This project is configured to use pnpm because /w/package.json has a "
           "\"packageManager\" field\n")

    def test_r0102_12_a_package_manager_mismatch_is_not_an_offline_cache_stop(self):
        self.assertIsNone(PMC.offline_fetch_failure(self.RAW))

    def test_it_is_a_mismatch_line(self):
        self.assertIn("configured to use pnpm", PMC.mismatch_failure(self.RAW))
        d = tmpdir(self)
        with open(os.path.join(d, "package.json"), "w") as fh:
            fh.write('{"packageManager": "pnpm@8.15.0"}')
        line = PMC.mismatch_line("test suite", self.RAW, d)
        self.assertTrue(line.startswith("engine-env-package-manager-mismatch: test suite"), line)
        self.assertIn("pnpm@8.15.0", line)
        self.assertNotIn("corepack install", line)


class m2YarnBerryHost(unittest.TestCase):
    def test_repo_yarnpkg_com_is_a_registry_host(self):
        self.assertIn("repo.yarnpkg.com", PO.REGISTRY_HOSTS["package.json"])


class m6WholeTextRedaction(unittest.TestCase):
    def test_r0102_12_probe(self):
        tb = ("Traceback (most recent call last):\n"
              "OSError: npm ERR! //registry.npmjs.org/:_authToken=npm_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789\n"
              "json.decoder.JSONDecodeError: x -- body: {\"password\": \"hunter2-very-secret\", \"token\": \"t0k3n\"}\n"
              "ValueError: bad header Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123def456\n"
              "TypeError: sequence item 8: expected str instance, list found\n")
        out = ESC.redacted_trace(tb)
        for leak in ("npm_AbCdEf", "hunter2", "t0k3n", "abc123def456"):
            self.assertNotIn(leak, out)
        self.assertIn("TypeError: sequence item 8", out)

    def test_a_multi_line_pem_is_cut_whole_and_the_rest_stays(self):
        tb = ("Traceback (most recent call last):\nValueError: -----BEGIN OPENSSH PRIVATE KEY-----\n"
              "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ\nAAAAmiddlelinesecret\n-----END OPENSSH PRIVATE KEY-----\n"
              "TypeError: after the key\n")
        out = ESC.redacted_trace(tb)
        self.assertNotIn("middlelinesecret", out)
        self.assertNotIn("b3BlbnNzaC1rZXkt", out)
        self.assertIn("TypeError: after the key", out)


class m7CorepackSeed(unittest.TestCase):
    def test_the_v1_layout_of_a_user_cache_is_seeded(self):
        uh = tmpdir(self)
        src = os.path.join(uh, ".cache", "node", "corepack", "v1", "pnpm", "8.15.0")
        os.makedirs(os.path.join(src, "bin"))
        with open(os.path.join(src, ".corepack"), "w") as fh:
            fh.write('{"locator": {"name": "pnpm", "reference": "8.15.0"}}')
        os.chmod(src, 0o555)                                          # a read-only source is fine
        self.addCleanup(os.chmod, src, 0o755)
        repo_ = tmpdir(self)
        with open(os.path.join(repo_, "package.json"), "w") as fh:
            fh.write('{"packageManager": "pnpm@8.15.0+sha512.abc"}')
        dest = os.path.join(tmpdir(self), "home")
        note = PMC.seed(repo_, env={}, user_home=uh, dest=dest)
        self.assertIn("seeded pnpm@8.15.0", note)
        self.assertTrue(PMC.present(dest, "pnpm", "8.15.0"))


if __name__ == "__main__":
    unittest.main()
