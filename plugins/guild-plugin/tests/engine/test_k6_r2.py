"""review-k6-r2 — the fixes, each over every gated group / option where the finding is structural.

M1  a gated group with ONE non-conservative option (derived from the option tables: INTEGRATE, TEST, QA, AN-PO,
    VIS-ENV, EX-DWC) asks only when the judge chose that option — the question's existence is the recommendation:
    its answer is never an `ok` nor a wrong candidate; every such question is a grading-sheet row and the group is
    released by the person's sheet verdicts on those decisions (table: every GATED group × every option);
M2  the KICKOFF block written before a blind interpretation question does not depend on the judge's pick (two runs
    differing only in it — attended and unattended); the run after the answer writes the footprint openly;
M3  a blind label keeps the scope clauses of its asides / tails, cuts the remarks, refuses what it cannot classify;
    m4: the ㅂ-irregular `자연스러운` rates;
M4  a clone without the tape applies the answer only when the judge it calls picks the person's or the asked option;
m1  `open` candidates are merged across `dev grade` scopes;
m2  a sampled non-conservative pick is dual-judged before its question (journal only) and the applied block carries it;
m3  `engine-env-*` is not folded (0.101.3's wildcard row), its note still reaches the ledger.
"""

import json
import os
import tempfile
import unittest

import _util  # noqa: F401
import test_k5_r9 as R9
import test_k5_r10 as R10
import test_k6_r1 as R1
from _k1 import tmpdir
from _k2 import role
from _k4 import K4, evidence, kickoff
from test_k2_qa_stage import qa_harness

from guildcore import ask as ASK
from guildcore import journal as J
from guildcore import valves as VALVES
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import Decision
from workflows.dev import conservative as CONS
from workflows.dev import grade as G
from workflows.dev import health as HE
from workflows.dev import judging as JG
from workflows.dev import predict as PF
from workflows.dev import unverified as UV
from workflows.dev.stages import analyze as A
from workflows.dev.stages import base as B
from workflows.dev.stages import design as DS
from workflows.dev.stages.base import StageResult

_blocks, _pending, _stale, _h, _ask, _answer, _run, _Judge = (R1._blocks, R1._pending, R1._stale, R1._h, R1._ask,
                                                              R1._answer, R1._run, R1._Judge)


def _options(g):
    return CONS.options_of(JG.spec(None, g, [("x", "y")], "qa", "S"))


class M1Inherent(unittest.TestCase):
    def test_derived_from_the_option_tables(self):
        self.assertEqual(sorted(CONS.INHERENT), sorted(["INTEGRATE", "TEST", "QA", "AN-PO", "VIS-ENV", "EX-DWC"]))
        for g in CONS.GATED:
            with self.subTest(group=g):
                nc = [o for o in _options(g) if o != JG.UNSURE.get(g)]
                self.assertEqual(g in CONS.INHERENT, len(nc) == 1)
                if g in CONS.INHERENT:
                    self.assertEqual(CONS.INHERENT[g], nc[0])

    def test_the_gate_asks_exactly_for_the_inherent_option(self):
        """Every GATED group × every option: the set of picks that raise the question — one for an inherent group."""
        for g in CONS.GATED:
            asked = []
            for o in _options(g):
                h = _h(self)
                h.p.valves = {"group.%s.conservative" % g: True}
                if o in (R10.SHAPES.get(g) or {}):
                    j = _Judge(g, o)
                else:
                    j = lambda spec, o=o: Decision(o, {spec.choice_key: o}, "judge:sonnet", "dg-" + o)  # noqa: E731
                try:
                    _run(h, g, "v1", j)
                except CONS.Ask as a:
                    asked.append(o)
                    self.assertEqual(bool(a.question.inherent), g in CONS.INHERENT, (g, o))
            with self.subTest(group=g):
                self.assertEqual(len(asked) == 1, g in CONS.INHERENT, asked)

    def test_inherent_answers_are_never_blind_judgments(self):
        """Every inherent group × (the person agrees, disagrees, stops): no `ok`, no wrong candidate — one sheet row
        (`inherent-gate`, the judge's pick) that holds the release until the person imports it."""
        for g, opt in sorted(CONS.INHERENT.items()):
            for ans in (opt, JG.UNSURE[g], "stop"):
                with self.subTest(group=g, answer=ans):
                    h = _h(self)
                    h.p.valves = {"group.%s.conservative" % g: True}
                    _ask(h, g, "v1", _Judge(g, opt))
                    blk = _pending(h)[-1]
                    self.assertTrue(str(blk.get("predict_first_counted")).startswith("false — inherent"), blk.fields)
                    _answer(h, ans)
                    ok, cands = G.predict_first_judgments(_blocks(h), 7)
                    self.assertEqual(ok, [])
                    self.assertEqual([(r["decision_id"], r["mode"], r["choice"], r["group"]) for r in cands],
                                     [(blk.id, G.INHERENT_MODE, opt, g)])

    def test_other_gated_groups_still_count(self):
        for g in sorted(set(CONS.GATED) - set(CONS.INHERENT)):
            y = R1._nonsafe(g)[0]
            with self.subTest(group=g):
                h = _h(self)
                h.p.valves = {"group.%s.conservative" % g: True}
                _ask(h, g, "v1", _Judge(g, y))
                self.assertIsNone(_pending(h)[-1].get("predict_first_counted"))
                _answer(h, y)
                ok, _c = G.predict_first_judgments(_blocks(h), 7)
                self.assertEqual(len(ok), 1)

    def test_release_paths_partition_the_groups(self):
        blind = set(CONS.GATED) - set(CONS.INHERENT) | {"KICKOFF"}
        for g in VALVES.GROUPS:
            with self.subTest(group=g):
                self.assertEqual(sum([g in blind, g in UV.SHEET_RELEASED, g in UV.EXEMPT]), 1)
        for g in CONS.INHERENT:
            self.assertIn(g, UV.SHEET_RELEASED)
            self.assertEqual(UV.SHEET_CHOICE[g], CONS.INHERENT[g])

    def test_inherent_group_releases_on_sheet_verdicts_of_its_pick_only(self):
        for g, opt in sorted(CONS.INHERENT.items()):
            with self.subTest(group=g):
                common = tmpdir(self)
                row = lambda i, ch, mode=G.INHERENT_MODE: {"issue": i, "decision_id": "D%d" % i, "group": g,  # noqa: E731
                                                          "given_info": "ok", "mode": mode, "choice": ch}
                G.apply_judgments(common, [row(i, opt, "predict-first") for i in range(1, 9)], "o/r", "predict-first")
                G.apply_judgments(common, [row(i, JG.UNSURE[g], "first-sprint") for i in range(10, 18)], "o/r", "human")
                self.assertIn(g, UV.pending(common))                        # blind oks / conservative picks: nothing
                cands = [dict(row(i, opt), given_info="") for i in range(20, 25)]
                G.apply_judgments(common, [], "o/r", "predict-first", candidates=cands)
                G.apply_judgments(common, [row(i, opt) for i in range(20, 24)], "o/r", "human")
                self.assertIn(g, UV.pending(common))                        # 4 verdicts, one row still open
                out = G.apply_judgments(common, [row(24, opt)], "o/r", "human")
                self.assertEqual(out.get("unverified_released"), [g])

    def test_import_takes_choice_and_mode_from_the_log(self):
        h = _h(self)
        h.p.valves = {"group.QA.conservative": True}
        _ask(h, "QA", "v1", _Judge("QA", "pass"))
        blk = _pending(h)[-1]
        _answer(h, "block")
        edited = {"decision_id": blk.id, "issue": 7, "group": "QA", "mode": "first-sprint", "choice": "block",
                  "given_info": "ok"}
        rows, rej = G.verify_rows([edited], lambda n: _blocks(h))
        self.assertEqual(rej, [])
        self.assertEqual((rows[0]["mode"], rows[0]["choice"]), (G.INHERENT_MODE, "pass"))
        self.assertTrue(UV.counts(rows[0], "human"))
        self.assertFalse(UV.counts(rows[0], "predict-first"))

    def test_the_source_line_names_the_sheet(self):
        class P(object):
            valves = {}
            unverified = frozenset(["QA", "STAKES"])
        self.assertIn("grading-sheet", PF.conservative_label(P(), "QA"))
        self.assertNotIn("grading-sheet", PF.conservative_label(P(), "STAKES"))


EXTRA = {"lib/settings/settings.dart": "int s = 1;\n", "lib/theme/theme.dart": "int t = 1;\n"}
SEALED = ("chosen_sha", "footprint_sha", "id", "inputs", "at")


def _kick_run(case, chosen, unattended=False, journal=False):
    k = kickoff(ui=(chosen == "B"), areas=(("lib/settings",) if chosen == "A" else
                                           ("lib/settings", "lib/theme", "lib/app")))
    k.fields["interpretations"] = [{"id": "A", "summary": "설정 화면만 다크 모드"},
                                   {"id": "B", "summary": "앱 전체 다크 모드"}]
    k.fields["chosen"] = chosen
    h = K4(case, unattended=unattended, roles=[evidence(case, areas=("lib/settings", "lib/theme", "lib/app"))] * 2,
           judges={"KICKOFF": k}, extra_files=EXTRA)
    h.p._first_sprint = True
    if journal:
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r2-"), 7, h.clock)
    if unattended:
        h.p.valves = {"group.KICKOFF.conservative": True}
    r = A.run(h.p)
    blocks = DecisionLog.load(h.gh.comments(7)).blocks
    kb = [b for b in blocks if b.get("point") == "KICKOFF"][-1]
    return h, r, dict((k_, v) for k_, v in dict(kb.fields).items() if k_ not in SEALED)


class M2KickoffFootprint(unittest.TestCase):
    def test_visible_block_does_not_depend_on_the_hidden_pick(self):
        for unattended in (False, True):
            with self.subTest(unattended=unattended):
                ha, ra, va = _kick_run(self, "A", unattended)
                hb, rb, vb = _kick_run(self, "B", unattended)
                self.assertEqual((ra.kind, rb.kind), (StageResult.PAUSE, StageResult.PAUSE) if unattended
                                 else (StageResult.ASK, StageResult.ASK))
                pend = [b for b in DecisionLog.load(ha.gh.comments(7)).blocks if b.get("status") == "pending-human"]
                self.assertTrue(pend[-1].get("predict_first"))
                self.assertEqual(va, vb)
                for f in PF.KICKOFF_FOOTPRINT:
                    self.assertNotIn(f, va)
                self.assertEqual(va.get("footprint"), PF.FOOTPRINT_WITHHELD)

    def test_footprint_is_journaled_and_written_openly_after_the_answer(self):
        h, r, _v = _kick_run(self, "A", journal=True)
        seals = [e for e in h.p.journal.entries if e.get("what") == "predict-first-seal"
                 and e.get("field") == "KICKOFF.footprint"]
        self.assertEqual(json.loads(seals[-1]["value"])["areas"], ["lib/settings"])
        pend = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("status") == "pending-human"][-1]
        from workflows.dev import analysis as AN
        interp = [{"id": "A", "summary": "설정 화면만 다크 모드"}, {"id": "B", "summary": "앱 전체 다크 모드"}]
        order = sorted(range(2), key=lambda n: AN.canon_key(interp[n]))
        tok = "i%d" % (order.index(0) + 1)                               # the engine token of reading A
        ASK.answer(h.decisions, h.writer, 7, pend.id, tok, journal=h.p.journal)
        res = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("resolves") == pend.id][-1]
        self.assertIn("KICKOFF footprint", str(res.get("revealed_question") or res.fields))
        A.run(h.p)
        kick = DS.kickoff_block(h.gh.comments(7))
        self.assertEqual(kick.get("areas"), "lib/settings")
        self.assertEqual(kick.get("ui_surface"), "false")
        self.assertIsNone(kick.get("footprint_sha"))

    def test_no_question_no_seal(self):
        k = kickoff(ui=False, areas=("lib/settings",))
        h = K4(self, unattended=False, roles=[evidence(self, areas=("lib/settings",))], judges={"KICKOFF": k},
               extra_files=EXTRA)
        h.p._first_sprint = False
        A.run(h.p)
        kick = DS.kickoff_block(h.gh.comments(7))
        self.assertEqual(kick.get("areas"), "lib/settings")
        self.assertIsNone(kick.get("footprint_sha"))


SCOPE_PAIRS = (
    ("앱 전체 다크 모드 (설정 화면 제외)", "설정 화면까지 앱 전체 다크 모드", "(설정 화면 제외)"),
    ("단어장 CSV 내보내기 (관리자만)", "단어장 CSV·PDF 내보내기", "(관리자만)"),
    ("Retry failed uploads, but never on 4xx", "Retry every failed request", "never on 4xx"),
    ("Add response caching — read endpoints only", "Add caching to reads and writes", "read endpoints only"),
    ("Delete the account (soft delete, keep audit log)", "Delete the account and all its data", "keep audit log"),
    ("ログイン画面の刷新（パスワード再設定は対象外）", "ログインとパスワード再設定の刷新", "対象外"),
    ("Remove the legacy v1 API (keep /v1/health)", "Remove v1 and v2 legacy routes", "keep /v1/health"),
    ("푸시 알림 추가 — iOS 만", "iOS·Android 푸시 알림 추가", "iOS 만"),
)


class M3ScopeAsides(unittest.TestCase):
    def test_scope_is_shown_or_the_question_refused(self):
        for a, b, qual in SCOPE_PAIRS:
            with self.subTest(label=a):
                shown = PF.blind_labels([a, b])
                self.assertTrue(shown[0] is None or qual in shown[0], shown)

    def test_clause_kinds(self):
        for t, k in (("설정 화면 제외", "scope"), ("iOS 만", "scope"), ("keep audit log", "scope"),
                     ("`_runAutoSync`", "scope"), ("v2.0", "scope"), ("제목 그대로", "remark"),
                     ("as the request reads", "remark"), ("가능성 높음", "remark"), ("narrow but safe", "other"),
                     ("최소 범위", "other"), ("over-scoped", "other"), ("맞지 않음", "scope-rating")):
            with self.subTest(clause=t):
                self.assertEqual(PF.clause_kind(t), k)

    def test_remark_cut_other_refused_scope_kept(self):
        self.assertEqual(PF.neutral_label("로그인만 (제목이 말하는 범위)"), "로그인만")
        self.assertIsNone(PF.neutral_label("Login only (narrow but safe)"))
        self.assertEqual(PF.neutral_label("다크 모드 (앱 전체, 가능성 높음)"), "다크 모드 (앱 전체)")
        self.assertEqual(PF.neutral_label("dashboard (`AdminView`)"), "dashboard (`AdminView`)")

    def test_blind_question_end_to_end(self):
        h = qa_harness(self, roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])])
        h.p._first_sprint = False
        a, b, qual = SCOPE_PAIRS[0]
        q = ASK.Question("interpretation-surface", "어느 해석?", [{"token": "i1", "label": a}, {"token": "i2", "label": b},
                                                             {"token": "stop", "label": "stop"}],
                         recommended="i1", recommended_by="judge:opus", raised_by="confirm",
                         neutral=PF.neutral_text("interpretation", 7))
        PF.apply(h.p, q, "analyze")
        self.assertTrue(q.neutralized)
        self.assertIn(qual, dict((o["token"], o["label"]) for o in q.options)["i1"])

    def test_m4_b_irregular_stem(self):
        for s in ("자연스러운 범위", "자연스럽게 확장", "자연스러움"):
            self.assertTrue(PF.rates(s), s)


class M4RemoteJudgment(unittest.TestCase):
    RAW, RAW2 = "test/a_test.dart: 3 tests passed (0.8s)", "test/a_test.dart: 3 tests passed (1.4s)"

    def _case(self, remote, now):
        h = qa_harness(self, roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])] * 4)
        h.p.valves = {"group.TEST.conservative": True}
        h.p.git_dir = None
        h.p.journal = None
        CONS._MEM.clear()

        def run(raw, excerpt, choice, calls):
            CONS.begin(h.p)
            CONS.role(h.p, B.RoleCall("tester", "verify", "test", "T1", inputs={"raw-output.txt": raw}),
                      lambda c: role("DONE", line="covers", plan="covers.json", human_items=[], followups=[]))

            def judge(spec):
                calls.append(1)
                return Decision(choice, {spec.choice_key: choice}, "judge:sonnet", "dg-" + choice)
            return CONS.gate(h.p, JG.spec(h.p, "TEST", [("excerpts", excerpt), ("raw", raw)], "test", "T3.4"), judge)
        try:
            run(self.RAW, "expect(login(bad), isFalse)", "all_effective", [])
            raise AssertionError("no question")
        except CONS.Ask as a:
            CONS.surface(h.p, "test", a)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, "all_effective")
        if remote:
            CONS._MEM.clear()
        calls = []
        d = run(self.RAW2, "expect(true, isTrue)", now, calls)
        return d, _stale(h), calls

    def test_remote_applies_only_with_the_judge(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                d, stale, calls = self._case(remote, "gap")
                self.assertEqual((d.choice, d.by, len(stale), len(calls)), ("gap", "judge:sonnet", 1, 1))
                d, stale, calls = self._case(remote, "all_effective")
                self.assertEqual((d.choice, d.by, len(stale)), ("all_effective", "human", 0))
                self.assertEqual(len(calls), 1 if remote else 1)


class M1OpenAcrossScopes(unittest.TestCase):
    def _r(self, i, gi):
        return {"issue": i, "decision_id": "D%d" % i, "group": "SPLIT", "given_info": gi, "mode": "predict-first"}

    def test_older_scope_candidate_holds_the_release(self):
        common = tmpdir(self)
        G.apply_judgments(common, [self._r(i, "ok") for i in (1, 2, 3)], "o/r", "predict-first",
                          candidates=[self._r(4, "")])
        out = G.apply_judgments(common, [self._r(i, "ok") for i in (11, 12)], "o/r", "predict-first", candidates=[])
        self.assertNotIn("unverified_released", out)
        self.assertIn("SPLIT", UV.pending(common))
        self.assertEqual(dict((r["group"], r) for r in UV.report(common))["SPLIT"]["open_candidates"], 1)
        out = G.apply_judgments(common, [self._r(4, "ok")], "o/r", "human")
        self.assertEqual(out.get("unverified_released"), ["SPLIT"])


class M2DualBeforeTheQuestion(unittest.TestCase):
    def test_non_conservative_pick_is_sampled(self):
        h = _h(self)
        h.p.valves = {"group.QA.conservative": True}
        h.p.dual_rate = 1.0
        j = _Judge("QA", "pass")
        _ask(h, "QA", "v1", j)
        self.assertEqual(j.calls, 2)                                     # the pick + its dual (other tier)
        pend = _pending(h)[-1]
        for f in ("dual", "dual_choice", "dual_model"):
            self.assertIsNone(pend.get(f))                               # never before the answer
        _answer(h, "pass")
        d = _run(h, "QA", "v1", j)
        self.assertEqual((d.by, d.dual), ("human", "agree"))
        B.record_judgment(h.p, "qa", "QA", "x", d)
        m = HE.metrics({7: _blocks(h)})
        self.assertEqual(m.get("dual_disagree"), 0.0)


class M3EnvNotFolded(unittest.TestCase):
    def setUp(self):
        from workflows.dev.replay import k6_downgrade_drill as DR
        self.DR = DR
        if DR.show(R1.REPO, R1.OLD, DR.P + "commands/sprint/run.md") is None:
            self.skipTest("0.101.3 not in this clone")

    def test_env_reasons_pass_through_and_are_documented(self):
        rows = dict((r["token"], r) for r in self.DR.fold_check(R1.REPO, R1.OLD, "HEAD", sup=R1._sup()))
        for t in ("halted:engine-env-unknown", "halted:engine-env-missing", "halted:engine-env-ignored-missing",
                  "halted:engine-env-build-inputs-changed"):
            with self.subTest(token=t):
                self.assertEqual(rows[t]["folded"], t)
                self.assertTrue(rows[t]["documented_0_101_3"])
                self.assertTrue(rows[t].get("note"))
        self.assertEqual(rows["halted:engine-gh-auth"]["folded"], "halted:marker-unwritable")
        missing, _s = self.DR.check(R1.REPO, R1.OLD, "HEAD")
        self.assertEqual([r["reason"] for r in missing if "MISSING" in (r["run.md"], r["_handoff.md"], r["daily.md"])
                          and r["reason"].startswith("engine-env-")], [])

    def test_ledger_carries_the_note_unfolded(self):
        import subprocess
        d = tmpdir(self)
        led = os.path.join(d, "ledger.json")
        with open(led, "w") as fh:
            json.dump({"state": "running"}, fh)
        funcs = "".join(self.DR._fn(R1._sup(), f) for f in ("compat_fold", "compat_note", "ledger_set", "marker_write"))
        env = dict(os.environ, LEDGER=led, D=d, PY="python3", OWNER_REPO="o/r", TRACKER="3")
        subprocess.run(["bash", "-c", funcs + '\ngh() { return 1; }; marker_write "halted:engine-env-unknown"'],
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with open(led) as fh:
            st = json.load(fh)
        self.assertEqual(st["state"], "halted:engine-env-unknown")
        self.assertEqual(st["halt_reason"], "engine-env-unknown")
        self.assertIn("issue-<N>", st["halt_note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
