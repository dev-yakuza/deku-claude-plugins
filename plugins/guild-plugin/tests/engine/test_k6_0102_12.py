"""0.102.12 — the review-0102-11 fixes (M1–M4, m1–m6) and three real-run defects of 0.102.11, through the real code
paths (the test and qa stages, the case parser, the role runner's scope check and revert, the loop-back record, the
Corepack home, the FSM's engine-FAIL path, the RESULT-line parser). The reviewer's repros (scratchpad `r0102_11/`) are
the first tests of their classes; each failed on 0.102.11 (`25ebdef`).

Lead decisions (k6-notes "0.102.12"):
M1  a visual row id in covers (`visual:*`, `VIS-n(…)`) is a visual case — mapped to its row's ACs through the
    visual-cases table, never an orphan id (no id-mapping engine-defect stop).
M2  nothing is lost on a scope revert: every reverted path is copied first to the role's run dir (`out/reverted/`,
    with `<path>.diff` and `manifest.json`), the copy is named in the grading row, the QA finding and the journal.
M3  a rename's source and destination are both in the snapshot; committed paths are read with `--no-renames`; a move
    out of the allowed paths is a violation; a rename is reverted as a pair (m6).
M4  one engine-owned Corepack home (seeded from the user's cache, prefetched by the networked deps step), offline
    runs with `COREPACK_ENABLE_NETWORK=0`; an offline package-manager fetch failure is an `env` stop
    (`engine-env-package-manager-offline`), never "the summary format is unreadable" (japanlifeinfo #227).
m1  a deferred safety-net case answered `kind: none` + reason → a grading row, not a gap.
m2  a test-cases.md that tags no case with an AC: the analyze ACs are judged as soft units (an unconfirmed one is a
    grading row); AC mentions in prose are not units.
m3  `reset` grants exactly one more loop-back for that source; the stagnation history stays.
m4  the cover name check is exact (whitespace normalised; an interpolated name by its literal prefix ≥ 8 chars).
m5  a QA scratch write (tmp / scratch / screenshot / ignored) is reverted with its row only, never a finding.
Real runs: word_app #1797 `engine FAIL — TypeError — sequence item 8` (a list-valued follow-up `keywords` → gh argv)
and every engine FAIL journals its redacted traceback; one-man-company #687 `tech-lead returned no valid RESULT line`
(a narrowed status beside a valid result.json, and the `DONE — …` separators models write).
"""
import json
import os
import unittest

import _util  # noqa: F401
import test_k6_0102_9 as T9
from _k1 import FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir
from _k2 import comment, decision, fixture, judge_qa, judge_test, role, suite

from guildcore import journal as J
from guildcore.adapters import gh as GH
from guildcore.checks import pmcache as PMC
from guildcore.decisions import DecisionLog
from guildcore.records import loopback as LB
from guildcore.roles import result as R
from guildcore.roles import runner as RR
from guildcore.roles import scope as SC
from workflows.dev import cases as CS
from workflows.dev import escalation as ESC
from workflows.dev.stages import qa as Q
from workflows.dev.stages import test as T

REAL = os.path.join(_util.FX, "real")


def _read(name):
    with open(os.path.join(REAL, name), encoding="utf-8") as fh:
        return fh.read()


TC_1797 = _read("word_app-1797-test-cases.md")
TC_1945 = _read("word_app-1945-test-cases.md")
RAW_227 = _read("japanlifeinfo-227-raw.txt")          # 007-check-developer/out/raw.txt (home dir renamed)
REPLY_687 = _read("one-man-company-687-tech-lead-reply.txt")   # 004-design-tech-lead-design s1's last result


def _blocks(h, point):
    return [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == point]


def _test_stage(case, covers, tc, judges, roles_after=(), analyze=None, files=None):
    roles = [role("DONE", covers=covers, e2e="E2E 불요")] + list(roles_after)
    comments = [comment(analyze, 1)] if analyze else []
    h = T9.Harness(case, fixture(comments=comments), roles=roles, judges={"TEST": judges},
                   suites=[T9.suite(T9.FLUTTER_GREEN)])
    h.write_file("docs/specs/7/test-cases.md", tc)
    for rel, text in (files or {"test/a_test.dart": T9.TESTFILE}).items():
        h.write_file(rel, text)
    return h, T.run(h.p)


# ---- word_app #1797 (0.102.11, 07:04Z): `engine FAIL — TypeError — sequence item 8: expected str instance, list found`

class R1797TypeError(unittest.TestCase):
    FOLLOWUPS = json.loads(_read("word_app-1797-followups.json"))      # qa run 211's out/followups.json

    def test_the_real_followups_keywords_are_one_search_text(self):
        self.assertIsInstance(self.FOLLOWUPS[0]["keywords"], list)
        got = Q._followup_items(type("R", (), {"extras": {"followups": self.FOLLOWUPS}})())
        self.assertEqual(got[0]["keywords"], "_allAvailableQuizTypes hasExample exampleReading toggleAllQuizTypes "
                                             "selectedQuizTypes")
        self.assertIsInstance(got[0]["rationale"], str)

    def test_the_gh_argv_never_carries_a_list(self):
        seen = []

        class Cli(GH.GhCli):
            def __init__(self):
                pass

            def _gh(self, argv):
                seen.append(" ".join(argv))           # item 8 — the search text — was the list
                return "[]"

            def _repo_args(self):
                return []
        Cli().issue_search(["a", "b c"], limit=10)
        self.assertIn("--search a b c --json", seen[0])

    def test_the_qa_stage_with_the_real_followups_does_not_raise(self):
        import test_k2_qa_stage as K2Q
        r0 = role("DONE", plan="qa-report.md", human_items=["실기기 확인"], followups=self.FOLLOWUPS)
        h = K2Q.qa_harness(self, roles=[r0], judges={"QA": [judge_qa()]})
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.token(), "OK DONE")
        calls = [c for c in h.gh.calls if c[0] == "issue_search"]
        self.assertTrue(calls and all(isinstance(c[1], str) for c in calls), calls)


class EngineFailTraceback(unittest.TestCase):
    def test_every_engine_fail_journals_its_redacted_traceback(self):
        from _k4 import K4
        from test_k4_fsm import driver

        def boom(p, *a, **k):
            ", ".join(["a", ["b"]] + ["ghp_" + "A" * 36])
        h = K4(self)
        h.p.journal = h.journal                           # the real ports carry the Issue's journal
        driver(h, {"analyze": boom}).run(7)
        self.assertIn("defect: engine FAIL — TypeError", h.body_with("needs-human"))
        esc = [e for e in J.Journal(h.common, 7).entries if e.get("point") == "G-ESCALATE"]
        self.assertTrue(esc and esc[-1].get("traceback"), esc)
        tb = esc[-1]["traceback"]
        self.assertIn("Traceback (most recent call last)", tb)
        self.assertIn("in boom", tb)
        self.assertIn("TypeError: sequence item 1: expected str instance, list found", tb)

    def test_the_trace_is_redacted_line_by_line(self):
        tb = "Traceback\n  File \"x.py\", line 1, in f\nValueError: token=ghp_%s\n" % ("A" * 36)
        got = ESC.redacted_trace(tb)
        self.assertIn('File "x.py", line 1, in f', got)
        self.assertNotIn("ghp_" + "A" * 36, got)

    def test_a_worker_writes_it_to_its_log(self):
        from workflows.dev import fsm as F
        import io
        import sys
        old, buf = sys.stderr, io.StringIO()
        sys.stderr = buf
        try:
            F._worker_trace("TypeError — x", "Traceback\nTypeError: x")
        finally:
            sys.stderr = old
        self.assertIn("guild engine FAIL — TypeError — x\nTraceback", buf.getvalue())


# ---- M1: a visual row cover is no orphan id --------------------------------------------------------------------------

class M1VisualCover(unittest.TestCase):
    TC = "## 케이스\n- C1 — AC #1: a\n- C2 — AC #2: b\n"

    def _run(self, extra, tc=None):
        covers = [{"test": "test/a_test.dart::t", "ac": "C1", "kind": "new"}] + extra   # C2 / AC #2: a REAL gap
        return _test_stage(self, covers, tc or self.TC, [judge_test(["AC #1", "AC #2"])] * 2,
                           roles_after=[role("DONE", covers=covers)])

    def test_r0102_11_o1_a_visual_row_cover_beside_a_real_gap_still_loops_back(self):
        h, r = self._run([{"test": "test/a_test.dart::t", "ac": "visual:single", "kind": "new"}])
        self.assertEqual(r.token(), "OK LOOPBACK: execute")
        self.assertIsNotNone(LB.from_comments(h.gh.comments(7)))

    def test_control_without_a_visual_cover(self):
        self.assertEqual(self._run([])[1].token(), "OK LOOPBACK: execute")

    def test_a_vis_n_cover_is_mapped_to_its_rows_acs_and_fills_no_gap(self):
        tc = self.TC + ("\n<!-- guild:visual-cases -->\n| 화면 | 상태 | AC |\n|---|---|---|\n| 설정 | 요약 1개 | AC #2 |\n")
        h, r = self._run([{"test": "test/a_test.dart::t", "ac": "VIS-1(일본어 모드·ko)", "kind": "new"}], tc)
        self.assertEqual(r.token(), "OK LOOPBACK: execute", "a visual row never covers the behaviour gap of AC #2")

    def test_the_real_visual_tables(self):
        rows = CS.visual_table(TC_1797)
        self.assertEqual([a for _t, a in rows], [["AC #1", "AC #3"], ["AC #3"], ["AC #3", "AC #4"]])
        self.assertEqual(CS.visual_acs("VIS-1(일본어 모드·ko)", CS.visual_table(TC_1945)), ["AC #3", "AC #4", "AC #6"])
        self.assertEqual(CS.visual_acs("visual:3", rows), ["AC #3", "AC #4"])
        self.assertEqual(CS.visual_acs("visual:single", rows), [])          # #1797 run 185's names: no row text
        got = CS.rekey_visual([{"test": "t", "ac": "VIS-2", "kind": "new"}, {"test": "t", "ac": "visual:all"},
                               {"test": "t", "ac": "AC #1"}], TC_1797)
        self.assertEqual([(c["ac"], c.get("case"), c.get("visual")) for c in got],
                         [("AC #3", "VIS-2", True), ("visual:all", None, True), ("AC #1", None, None)])
        self.assertFalse(T.covering(got[0]))


# ---- M2 / M3 / m5 / m6: the scope revert keeps a copy, renames are seen and reverted as a pair -----------------------

def _runner(case, check, journal=None):
    user = os.path.join(tmpdir(case), "settings.json")
    with open(user, "w") as fh:
        fh.write("{}")
    root = os.path.join(tmpdir(case), "runs")
    r = RR.Runner(journal=journal or RecJournal(), common_dir=tmpdir(case), parent_env={"PATH": os.environ["PATH"]},
                  spawn=FakeSpawn([{"stream": stream_lines(texts=[">>> RESULT <<<\nDONE: ok"]), "check": check}]),
                  user_settings=user, run_root_dir=root, claude="claude")
    return r


class EvJournal(RecJournal):
    def __init__(self):
        RecJournal.__init__(self)
        self.events = []

    def append(self, kind, **f):
        self.events.append(dict(f, kind=kind))


class M2RevertKeepsACopy(unittest.TestCase):
    NEW = "// a person's fix, typed while the tester ran\nint hotfix() => 42;\n"

    def test_r0102_11_r1_a_write_during_tester_verify_is_kept_in_the_run_dir(self):
        main = repo(self, {"lib/a.dart": "a\n", "test/a_test.dart": "t\n"})
        wt = os.path.join(tmpdir(self), "wt")
        git(main, "worktree", "add", "-q", "-b", "feat", wt)

        def person(argv, env, cwd, stdin):                    # not the role: someone else in the same worktree
            with open(os.path.join(cwd, "lib", "hotfix.dart"), "w") as fh:
                fh.write(self.NEW)
            with open(os.path.join(cwd, "lib", "a.dart"), "a") as fh:
                fh.write("b\n")
        j = EvJournal()
        res = _runner(self, person, j).run_role(RR.RoleSpec("tester", "verify", "t", issue=7, stage="test", step="T1",
                                                            worktree=wt, model="sonnet", base="HEAD", branch="feat",
                                                            remote_check=False))
        self.assertEqual(res.status, "DONE")
        keep = res.reverted_dir
        # 0.102.13 (review-0102-12 B2): an engine-owned dir beside runs/, never the role's own out/
        self.assertEqual(keep, os.path.join(os.path.dirname(os.path.dirname(res.run_dir)), "reverted",
                                            os.path.basename(res.run_dir)))
        self.assertEqual(open(os.path.join(keep, "lib", "hotfix.dart")).read(), self.NEW)
        self.assertEqual(open(os.path.join(keep, "lib", "a.dart")).read(), "a\nb\n")
        self.assertIn("+b", open(os.path.join(keep, "lib", "a.dart.diff")).read())
        man = {r_["path"]: r_ for r_ in json.load(open(os.path.join(keep, "manifest.json")))}
        self.assertEqual((man["lib/hotfix.dart"]["state"], man["lib/a.dart"]["state"]), ("new", "modified"))
        ev = [e for e in j.events if e.get("what") == "scope-reverted"]
        self.assertEqual((ev[0]["kept"], sorted(ev[0]["paths"])), (keep, ["lib/a.dart", "lib/hotfix.dart"]))
        self.assertTrue(any(keep in n for n in res.notes), res.notes)

    def test_a_path_whose_copy_cannot_be_written_is_not_reverted(self):
        d = repo(self, {"lib/a.dart": "a\n"})
        before = SC.snapshot(d)
        with open(os.path.join(d, "lib", "new.dart"), "w") as fh:
            fh.write("n\n")
        keep = os.path.join(tmpdir(self), "file-not-dir")
        with open(keep, "w") as fh:
            fh.write("x")                                  # a FILE where the keep dir should be
        got = SC.revert_writes(d, ["lib/new.dart"], keep_dir=keep, after=SC.snapshot(d))
        self.assertEqual(got, [])
        self.assertTrue(os.path.exists(os.path.join(d, "lib", "new.dart")))
        self.assertEqual(before["status"], {})

    def test_the_grading_row_and_the_qa_finding_name_the_copy(self):
        import test_k2_qa_stage as K2Q
        r0 = role("DONE", plan="qa-report.md", plan_summary=["릴리스 노트: 추가"])
        r0.reverted = [("release_notes/en.txt", "Pick quiz types from Settings")]
        r0.reverted_dir = "/runs/209-qa-qa-run/out/reverted"
        h = K2Q.qa_harness(self, roles=[r0], judges={"QA": [judge_qa()]})
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.token(), "OK LOOPBACK: execute")
        row = _blocks(h, "scope-reverted")[0]
        self.assertEqual(row.get("reverted_copy"), "/runs/209-qa-qa-run/out/reverted")
        self.assertIn("copies: /runs/209-qa-qa-run/out/reverted", row.get("reason"))
        f = Q.reverted_findings(r0)
        self.assertIn("/runs/209-qa-qa-run/out/reverted/release_notes/en.txt", f[0]["evidence"])


class M3Renames(unittest.TestCase):
    def _d(self):
        return repo(self, {"lib/a.dart": "class A { int f() => 1; }\n" * 20, "test/x_test.dart": "t\n"})

    def test_r0102_11_s2_uncommitted_rename_into_test_dir(self):
        d = self._d()
        before = SC.snapshot(d)
        git(d, "mv", "lib/a.dart", "test/a_moved.dart")
        viol = SC.check(d, before, SC.snapshot(d), ["qa"])
        self.assertTrue(any("lib/a.dart" in v for v in viol), "qa deleted lib/a.dart unseen: %s" % viol)

    def test_r0102_11_s2_committed_rename_into_test_dir(self):
        d = self._d()
        before = SC.snapshot(d)
        git(d, "mv", "lib/a.dart", "test/a_moved.dart")
        git(d, "commit", "-qm", "qa: move")
        viol = SC.check(d, before, SC.snapshot(d), ["qa"], branch="main")
        self.assertTrue(any("lib/a.dart" in v for v in viol), "qa's commit deleting lib/a.dart passes: %s" % viol)

    def test_m6_a_rename_is_reverted_as_a_pair_with_both_sides_kept(self):
        d = self._d()
        before = SC.snapshot(d)
        git(d, "mv", "test/x_test.dart", "lib/x.dart")              # out of qa's scope
        with open(os.path.join(d, "lib", "x.dart"), "a") as fh:
            fh.write("edited\n")
        after = SC.snapshot(d)
        self.assertEqual(SC.rename_partner(after, "lib/x.dart"), "test/x_test.dart")
        viol = SC.check(d, before, after, ["qa"])
        paths = SC.revertable(d, before, after, viol, "qa")
        self.assertEqual(sorted(paths), ["lib/x.dart", "test/x_test.dart"])
        keep = os.path.join(tmpdir(self), "keep")
        got = SC.revert_writes(d, paths, keep_dir=keep, after=after)
        self.assertEqual(sorted(p for p, _t in got), ["lib/x.dart", "test/x_test.dart"])
        self.assertEqual(SC.check(d, before, SC.snapshot(d), ["qa"]), [])
        self.assertEqual(open(os.path.join(d, "test", "x_test.dart")).read(), "t\n")
        self.assertFalse(os.path.exists(os.path.join(d, "lib", "x.dart")))
        self.assertEqual(open(os.path.join(keep, "lib", "x.dart")).read(), "t\nedited\n")
        man = {r_["path"]: r_["state"] for r_ in json.load(open(os.path.join(keep, "manifest.json")))}
        self.assertEqual(man, {"lib/x.dart": "renamed-from test/x_test.dart", "test/x_test.dart": "renamed-to lib/x.dart"})


class m5QaScratch(unittest.TestCase):
    def test_scratch_writes_are_rows_not_findings(self):
        r0 = role("DONE")
        r0.reverted = [("tmp/qa-notes.md", "notes"), ("shots/home.png", "(binary)"), ("qa.log", "x"),
                       ("release_notes/ko.txt", "설정에서 선택")]
        got = Q.reverted_findings(r0)
        self.assertEqual([f["line"].split(":")[0] for f in got], ["release notes missing"])
        self.assertEqual(got[0]["id"], "QA-W1")

    def test_an_ignored_path_is_scratch(self):
        d = repo(self, {".gitignore": "out/\n", "lib/a.dart": "a\n"})
        self.assertTrue(Q.scratch_path("out/qa-report.md", d))
        self.assertFalse(Q.scratch_path("docs/qa-report.md", d))

    def test_a_binary_file_is_kept_as_binary(self):
        d = repo(self, {"lib/a.dart": "a\n"})
        with open(os.path.join(d, "shot.dat"), "wb") as fh:
            fh.write(b"\x89PNG\x00\x01")
        got = SC.revert_writes(d, ["shot.dat"], keep_dir=os.path.join(tmpdir(self), "k"), after=SC.snapshot(d))
        self.assertEqual(got, [("shot.dat", "(binary)")])


# ---- M4: one engine Corepack home, an offline fetch failure is env (japanlifeinfo #227) ----------------------------

class M4Corepack(unittest.TestCase):
    def _proj(self, pm="pnpm@8.15.0+sha256.abc"):
        d = tmpdir(self)
        with open(os.path.join(d, "package.json"), "w") as fh:
            json.dump({"name": "x", "packageManager": pm}, fh)
        return d

    def test_the_real_227_output_is_an_offline_fetch_failure(self):
        self.assertIn("Corepack is about to download https://registry.npmjs.org/pnpm/-/pnpm-8.15.0.tgz",
                      PMC.offline_fetch_failure(RAW_227))
        self.assertIsNone(PMC.offline_fetch_failure(T9.FLUTTER_GREEN))
        self.assertIsNotNone(PMC.offline_fetch_failure(
            "Network access disabled by the environment; can't reach https://registry.npmjs.org/pnpm/-/pnpm-8.15.0.tgz"))
        line = PMC.offline_line("execute suite", RAW_227, self._proj())
        self.assertTrue(line.startswith("engine-env-package-manager-offline: execute suite — the offline suite needed "
                                        "pnpm@8.15.0"), line)
        self.assertIn("corepack install", line)

    def test_package_manager(self):
        self.assertEqual(PMC.package_manager(self._proj()), ("pnpm", "8.15.0"))
        self.assertEqual(PMC.package_manager(self._proj("yarn@4.1.0")), ("yarn", "4.1.0"))
        self.assertIsNone(PMC.package_manager(tmpdir(self)))

    def test_seed_copies_only_a_usable_install_into_the_v1_layout(self):
        uh = tmpdir(self)
        src = os.path.join(uh, ".cache", "node", "corepack")
        os.makedirs(os.path.join(src, "pnpm", "8.15.0", "bin"))               # #227's user cache: pre-0.20, unusable
        proj = self._proj()
        self.assertIsNone(PMC.seed(proj, {}, user_home=uh))
        self.assertFalse(PMC.present(PMC.home(uh), "pnpm", "8.15.0"))
        os.makedirs(os.path.join(src, "v1", "pnpm", "8.15.0", "bin"))
        with open(os.path.join(src, "v1", "pnpm", "8.15.0", ".corepack"), "w") as fh:
            fh.write('{"locator":{"name":"pnpm","reference":"8.15.0"},"hash":"sha256.x"}')
        self.assertIn("seeded pnpm@8.15.0", PMC.seed(proj, {}, user_home=uh))
        self.assertTrue(PMC.present(PMC.home(uh), "pnpm", "8.15.0"))
        self.assertIsNone(PMC.seed(proj, {}, user_home=uh))                     # once

    def test_check_env_points_corepack_at_the_engine_home(self):
        from guildcore import checks as CH
        off = CH.check_env({"PATH": "/bin"}, tmpdir(self))
        self.assertEqual((off["COREPACK_HOME"], off["COREPACK_ENABLE_NETWORK"]), (PMC.home(), "0"))
        self.assertNotEqual(off["XDG_CACHE_HOME"], os.path.dirname(os.path.dirname(off["COREPACK_HOME"])))
        on = CH.check_env({"PATH": "/bin", "GUILD_NETWORK_STEP": "1"}, tmpdir(self))
        self.assertNotIn("COREPACK_ENABLE_NETWORK", on)
        self.assertNotIn("GUILD_NETWORK_STEP", on)
        self.assertEqual(on["COREPACK_HOME"], PMC.home())

    def test_the_deps_sandbox_may_fill_it(self):
        from workflows.dev import ports as PO
        d = repo(self, {"package.json": '{"name":"x"}\n'})
        sb = PO.deps_sandbox(d, tmpdir(self), d)
        self.assertIn(PMC.home() + "/**", sb["filesystem"]["allowWrite"])
        self.assertIn(PMC.home() + "/**", sb["filesystem"]["readOnlyAllow"])

    def test_execute_stops_env_with_the_clear_line(self):
        from _k3 import XHarness, dev
        h = XHarness(self, roles=[dev()], suites=[suite(RAW_227, passed=False, rc=1)])
        from workflows.dev.stages import execute as X
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")
        nh = h.body_with("needs-human")
        self.assertIn("env: other — engine-env-package-manager-offline: execute suite", nh)
        self.assertNotIn("테스트 요약 형식을 읽지 못함", nh)

    def test_the_test_stage_stops_env_too(self):
        h = T9.Harness(self, fixture(), suites=[suite(RAW_227, passed=False, rc=1)])
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK PAUSE: needs-human — engine-env-package-manager-offline")


# ---- m1: a deferred safety-net case answered `kind: none` is a grading row ------------------------------------------

class m1DeferredNet(unittest.TestCase):
    TC = "## 케이스\n- SN1 — AC #1: the export keeps its order\n- SN2 — AC #2: the retry path keeps its delay\n"

    def test_r0102_11_d1_the_stage_advances_when_the_repair_names_the_deferral(self):
        covers = [{"test": "test/a_test.dart::t", "ac": "SN1", "kind": "guard"}]
        repair = covers + [{"test": "", "ac": "SN2", "kind": "none", "reason": "deferred: untestable without a seam"}]
        orig = T.deferred_cases
        T.deferred_cases = lambda body: ["SN2"]
        try:
            h, r = _test_stage(self, covers, self.TC, [judge_test(["AC #1"])] * 2,
                               roles_after=[role("DONE", covers=repair)])
        finally:
            T.deferred_cases = orig
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        row = _blocks(h, "ac-untestable")
        self.assertEqual(row[0].get("ac_untestable"), "AC #2")
        self.assertIn("SN2: deferred: untestable without a seam", row[0].get("reason"))
        rep = [c for c in h.calls["roles"] if c.task == "repair-mapping"][0]
        self.assertEqual(rep.inputs["safety-net-deferred.txt"], "SN2")

    def test_the_repair_prompt_teaches_it(self):
        txt = open(os.path.join(os.path.dirname(T.__file__), "..", "roles", "prompts",
                                "tester-repair-mapping.md")).read()
        self.assertIn('kind: "none", reason: "deferred:', txt)


# ---- m2: an untagged document — soft analyze ACs, no prose units ----------------------------------------------------

def _analyze_out(acs):
    return ("<!-- guild:analyze:output -->\n## Guild analyze — #7\n\nReadiness: Goal=clear · Constraint=clear · "
            "Success=clear\nwork-type: feature\ncast: none\n\n### 수용 기준\n" +
            "".join("- %s: x%s\n" % (a, a[-1]) for a in acs) + "<!-- /guild:analyze:output -->")


class m2Untagged(unittest.TestCase):
    TC = "## 케이스\n| ID | 내용 |\n|---|---|\n| C1 | a |\n| C2 | b |\n"

    def test_the_analyze_acs_are_soft_units(self):
        # 0.102.13 (review-0102-12 M1): only a legacy document (it exists at the base commit) has soft units
        units, _m, amap = CS.judged_units(self.TC, (), ["AC #1", "AC #2"], legacy=True)
        self.assertEqual((units, amap), (["C1", "C2"], {}))
        self.assertEqual(CS.soft_units(self.TC, units, ["AC #1", "AC #2"], legacy=True), ["AC #1", "AC #2"])

    def test_an_unconfirmed_soft_ac_is_a_row_not_a_gap(self):
        covers = [{"test": "test/a_test.dart::t", "ac": "C1", "kind": "guard"},
                  {"test": "test/a_test.dart::t", "ac": "C2", "kind": "guard"}]
        from unittest import mock
        with mock.patch.object(T, "doc_predates_run", lambda p, rel: True):     # 0.102.13 (M1): a legacy document
            h, r = _test_stage(self, covers, self.TC, [judge_test(["C1", "C2"])] * 2,
                               roles_after=[role("DONE", covers=covers)], analyze=_analyze_out(["AC #1", "AC #2"]))
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        row = _blocks(h, "ac-untagged")
        self.assertEqual(row[0].get("ac_untagged"), "AC #1,AC #2")

    def test_prose_mentions_are_no_units(self):
        tc = ("## 케이스\n- C1 — AC #1: a\n\n이번 범위 밖: AC #7 은 #1950 으로 분리했다(対象外).\n"
              "- C2 [AC #3] b\n### 경계 (AC #4)\n")
        self.assertEqual(CS.doc_ac_refs(tc), ["AC #1", "AC #3", "AC #4"])
        units, _m, _a = CS.judged_units(tc)
        self.assertNotIn("AC #7", units)
        self.assertEqual(CS.doc_ac_refs("설명 문장 안의 태그 [AC #5] 도 단위다."), ["AC #5"])


# ---- m3: `reset` grants exactly one more for its source; history stays ----------------------------------------------

def _blk(n, frm, sig):
    return LB.render_block(n, frm, "2026-11-22T0%d:00:00Z" % n, "b", "r — %s" % sig, sig) + \
        "\nconsumed: 2026-11-22T0%d:30:00Z" % n


def _rec(*parts):
    return LB.LoopbackRecord.parse(LB.render_new_record("\n\n".join(parts)))


class m3Reset(unittest.TestCase):
    GRANT = LB.render_reset("2026-11-22T05:00:00Z", by="human", from_="test", grant=1, for_n=3)

    def test_one_more_for_that_source_only(self):
        rec = _rec(_blk(1, "test", "a"), _blk(2, "test", "b"), self.GRANT)
        self.assertFalse(rec.cap_reached("test"))
        rec = _rec(_blk(1, "test", "a"), _blk(2, "test", "b"), self.GRANT, _blk(3, "test", "c"))
        self.assertTrue(rec.cap_reached("test"))
        self.assertFalse(rec.cap_reached("qa"))                    # the grant raised the total ceiling by one too
        self.assertEqual(rec.grants("qa"), (1, 0))

    def test_the_stagnation_history_stays(self):
        rec = _rec(_blk(1, "test", "AC #2"), _blk(2, "test", "AC #3"), self.GRANT)
        self.assertEqual(rec.stagnant_with("AC #3", "test"), 2)

    def test_a_rollback_reset_still_clears(self):
        rec = _rec(_blk(1, "test", "a"), _blk(2, "test", "b"), LB.render_reset("2026-11-22T05:00:00Z"))
        self.assertEqual(rec.active(), [])
        self.assertFalse(rec.cap_reached("test"))

    def test_a_resumed_reset_never_grants_twice(self):
        rec = _rec(_blk(1, "test", "a"), _blk(2, "test", "b"), self.GRANT)
        self.assertTrue(rec.has_grant_for(3))
        self.assertFalse(rec.has_grant_for(4))


# ---- m4: the exact cover name check ---------------------------------------------------------------------------------

SRC_1797 = """void main() {
  group('문제 유형 항목', () {
    for (final hasExample in [true, false]) {
      testWidgets('hasExample=$hasExample: 요약이 선택 개수에 따라 이름·N개·전체로 바뀐다', (t) async {});
    }
    testWidgets('${locale.languageCode} 로케일에서 번역된 제목과 요약이 보인다', (t) async {});
    testWidgets('요약이 N개 선택이다', (t) async {});
  });
  // renders a thing
}
"""


class m4ExactNames(unittest.TestCase):
    def test_the_real_1797_names(self):
        # the covers of #1797 runs 111 (`\\$hasExample`, JSON-escaped) and 185 (`${hasExample}`)
        base = "문제 유형 항목 hasExample=%s: 요약이 선택 개수에 따라 이름·N개·전체로 바뀐다"
        for n in (base % "\\$hasExample", base % "${hasExample}", base % "true"):
            self.assertTrue(T.name_in_source(SRC_1797, n, "flutter"), n)
        self.assertTrue(T.name_in_source(SRC_1797, "문제 유형 항목 요약이 N개 선택이다", "flutter"))
        self.assertTrue(T.name_in_source(SRC_1797, "문제 유형 항목 ›  요약이 N개  선택이다", "flutter"))

    def test_a_short_or_partial_name_is_no_cover(self):
        for n in ("renders", "t", "요약이 N개", "다른 그룹 요약이 N개 선택이다"):
            self.assertFalse(T.name_in_source(SRC_1797, n, "flutter"), n)

    def test_an_interpolated_prefix_shorter_than_8_is_no_match(self):
        self.assertFalse(T.name_in_source(SRC_1797, "문제 유형 항목 ko 로케일에서 번역된 제목과 요약이 보인다", "flutter"))

    def test_pytest_is_the_function_name(self):
        src = "def test_export_keeps_order():\n    assert 1\n"
        self.assertTrue(T.name_in_source(src, "tests/a_test.py::test_export_keeps_order", "pytest"))
        self.assertFalse(T.name_in_source(src, "tests/a_test.py::test_export", "pytest"))


# ---- one-man-company #687: `tech-lead returned no valid RESULT line` -------------------------------------------------

class R687ResultLine(unittest.TestCase):
    def setUp(self):
        self.wt = repo(self, {"lib/a.dart": "a\n"})
        git(self.wt, "switch", "-q", "-c", "feat")
        self.root = os.path.join(tmpdir(self), "runs")
        self.user = os.path.join(tmpdir(self), "settings.json")
        with open(self.user, "w") as fh:
            fh.write("{}")

    def _run(self, sessions, allowed, schema):
        self.spawn = FakeSpawn(sessions)
        r = RR.Runner(journal=RecJournal(), common_dir=tmpdir(self), parent_env={"PATH": os.environ["PATH"]},
                      spawn=self.spawn, user_settings=self.user, run_root_dir=self.root, claude="claude")
        return r.run_role(RR.RoleSpec("tech-lead", "design", "t", issue=687, stage="design", step="E1.1",
                                      worktree=self.wt, model="sonnet", base="HEAD", branch="feat",
                                      remote_check=False, result_schema=schema, allowed_status=allowed))

    def _files(self):
        rd = os.path.join(self.root, "001-design-tech-lead-design")
        return {os.path.join(rd, "out", "result.json"): json.dumps({"skeleton": "out/skeleton.md",
                                                                     "split_path": "out/split.json"}),
                os.path.join(rd, "out", "skeleton.md"): "# s\n", os.path.join(rd, "out", "split.json"): '{"split": false}'}

    def test_the_real_reply_with_a_valid_result_json_is_done_in_one_session(self):
        from workflows.dev.stages import design as D
        res = self._run([{"stream": stream_lines(texts=[REPLY_687]), "files": self._files()}],
                        D.TL_STATUSES, R.RESULT_SCHEMAS["tech-lead"])
        self.assertEqual(res.status, "DONE", res.line)
        self.assertTrue(res.line.startswith("DONE: concerns — skeleton at docs/specs/687/skeleton.md"), res.line)
        self.assertEqual(len(self.spawn.calls), 1)
        self.assertIn("status from result.json: RESULT line narrowed → DONE", res.notes)

    def test_without_a_valid_result_json_the_repair_names_the_allowed_statuses(self):
        from workflows.dev.stages import design as D
        res = self._run([{"stream": stream_lines(texts=[REPLY_687])}, {"stream": stream_lines(texts=[REPLY_687])}],
                        D.TL_STATUSES, R.RESULT_SCHEMAS["tech-lead"])
        self.assertEqual(res.status, "INVALID")
        self.assertIn("This task allows only: DONE / BLOCKED / NEEDS_CONTEXT / FAIL.", self.spawn.calls[1]["stdin"])

    def test_the_separators_models_write(self):
        for line, want in (("DONE — out/test-cases.md", ("DONE", "out/test-cases.md")),
                           ("DONE (out/i18n.md)", ("DONE", "out/i18n.md")),
                           ("DONE - out/a.md", ("DONE", "out/a.md")),
                           ("**DONE_WITH_CONCERNS**: x", ("DONE_WITH_CONCERNS", "x")),
                           ("DONE：노트", ("DONE", "노트")),
                           ("DONE", ("DONE", None))):
            p = R.parse_pres(">>> RESULT <<<\n" + line)
            self.assertTrue(p.ok, line)
            self.assertEqual((p.status, p.text), want)
        for bad in ("DONEX", "DONE-ish", "done"):
            self.assertFalse(R.parse_pres(">>> RESULT <<<\n" + bad).ok, bad)
        # 0.102.13 (review-0102-12 B1): a bare / variant BLOCKED is read as BLOCKED, never left unreadable
        self.assertEqual(R.parse_pres(">>> RESULT <<<\nBLOCKED").status, "BLOCKED")

    def test_structured_status_never_infers_a_failure(self):
        tl = R.RESULT_SCHEMAS["tech-lead"]
        reply = ">>> RESULT <<<\nFAIL: broke"
        p = R.parse_pres(reply, ("DONE", "BLOCKED"))
        self.assertIsNone(R.structured_pres(p, {"skeleton": "x"}, ("DONE", "BLOCKED"), reply, tl))
        p = R.parse_pres("no sentinel at all")
        self.assertEqual(R.structured_pres(p, {"status": "BLOCKED", "skeleton": "x"}, R.STATUSES, "no sentinel at all",
                                           tl).status, "BLOCKED")
        self.assertEqual(R.structured_pres(p, {"skeleton": "x"}, R.STATUSES, "no sentinel at all", tl).status, "DONE")


if __name__ == "__main__":
    unittest.main()
