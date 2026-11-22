"""0.102.7 — the review-0102-6 fixes (M1, m1–m5) and the word_app #1797 auditor write refusal, through the real code
paths (the real call sites' briefs, the conservative gate, the analyze / execute stages, `Runner.run_group`,
`grade.select`, the role permission rules and the Runner's argv / env).

* M1 / m1  security is read from the judge's structured `security_concern` (any language); true, missing or not a
           boolean → a person decides; the role-source rule stays; the text trigger is issue phrases only.
* m2       a group's drift question shows exactly what its fingerprint binds; every item rides on the block.
* m3       the PR title never doubles a conventional-commit prefix.
* m4       every `by: code` · `grade: trigger` block is a grading-sheet row (one rule).
* m5       nested KICKOFF readings: the narrowest is taken without a person when every condition holds.
* auditor  its own out/ is writable (the scrubbed-env CLI refused out/result.json); a DONE_WITH_CONCERNS with valid
           findings is an audit, not a pause.
"""
import json
import os
import re
import unittest

import _util  # noqa: F401
import test_k3_execute_stage as K3
import test_k6_0102_6 as T6
from _k1 import Clock, FakeSpawn, git, repo, stream_lines, tmpdir
from _k2 import decision
from _k3 import XHarness, auditor, dev, finding
from _k4 import ANCHOR_OK, K4, evidence, kickoff, stakes

from guildcore.decisions import DecisionLog
from guildcore.roles import permissions as P
from guildcore.roles import runner as RR
from guildcore.roles.runner import RoleResult
from workflows.dev import analysis as AN
from workflows.dev import conservative as CONS
from workflows.dev import grade as G
from workflows.dev import judging as JG
from workflows.dev.stages import analyze as A
from workflows.dev.stages import base as B
from workflows.dev.stages import execute as X
from workflows.dev.stages import qa as Q

JUDGES = os.path.join(os.path.dirname(JG.__file__), "judges")


def _blocks(h, n=7):
    return DecisionLog.load(h.gh.comments(n)).blocks


# ---- M1 / m1: the structured security reading -----------------------------------------------------------------------

class _Briefs(T6.B2Security):
    """The 0.102.6 builders of the REAL call sites' specs (qa._judge, arbitration.blocked / stakes, execute.ex_arb) —
    only the builders; the 0.102.6 tests are not run again here."""
    def test_de_arb_over_a_blocked_security_role_still_asks(self):
        pass

    def test_qa_pass_over_a_security_finding_still_asks(self):
        pass

    def test_the_real_call_sites_table(self):
        pass

    def test_every_table_part_is_a_part_a_call_site_builds(self):
        pass

    def test_a_blocked_security_role_asks_through_the_gate(self):
        pass

    def test_an_unverified_ex_arb_never_dismisses_a_security_finding(self):
        pass


def _d(choice, concern, **f):
    fields = dict(f)
    if concern is not _MISSING:
        fields[CONS.SECURITY_FIELD] = concern
    return decision(choice, fields)


_MISSING = object()


class M1StructuredField(_Briefs):
    def test_every_post_hoc_group_that_can_carry_security_requires_the_field(self):
        for g in CONS.SECURITY_FIELD_GROUPS:
            with self.subTest(group=g):
                sch = JG.schema(g)
                self.assertIn(CONS.SECURITY_FIELD, sch["required"])
                self.assertEqual(sch["properties"][CONS.SECURITY_FIELD], {"type": "boolean"})
                self.assertIn(CONS.SECURITY_REASON, sch["properties"])
                with open(os.path.join(JUDGES, g + ".md"), encoding="utf-8") as fh:
                    text = fh.read()
                # the definition: an issue, never a feature; any language; doubt → true
                for want in ("`security_concern`", "vulnerability", "auth / security FEATURE", "memory leak",
                             "whatever\nlanguage", "Doubt → `true`"):
                    self.assertIn(want, text.replace("language they", "language they"), (g, want))
        # 0.102.8 (lead decision 1): every gated group and KICKOFF / EX-ARB
        self.assertEqual(set(CONS.SECURITY_FIELD_GROUPS), set(CONS.GATED) | {"EX-ARB", "KICKOFF"})

    def test_the_field_decides_in_any_language(self):
        # the briefs carry no English issue word: only the judge's field can say it is security
        rows = [
            ("QA ko", lambda: self._qa(["토큰 저장 방식 확인 — 실기기"]), "pass", {"verdict": "pass"}),
            ("DE-ARB ko", lambda: self._dearb("tech-lead", "리프레시 토큰을 어디에 둘지"), "decide",
             {"action": "decide", "assumption": "기존 저장소 유지"}),
            ("STAKES ja", lambda: self._stakes("tech-lead", "トークンの保存場所"), "low",
             {"level": "low", "local_reversible_reason": "revert"}),
        ]
        for name, make, choice, f in rows:
            spec = make()
            with self.subTest(case=name):
                self.assertFalse(CONS.security(spec), "the brief alone must not decide it")
                for concern, want in ((True, True), (False, False), (_MISSING, True), ("false", True), (None, True)):
                    d = _d(choice, concern, **f)
                    self.assertEqual(CONS.security(spec, d), want, concern)
                    self.assertEqual(CONS.posthoc(T6.P(), spec.group, spec, decision=d), not want, concern)

    def test_the_role_source_rule_stays(self):
        spec = self._dearb("security", "which module?")
        self.assertTrue(CONS.security(spec, _d("decide", False, action="decide", assumption="x")))

    def test_the_gate_asks_a_security_decision_and_names_why(self):
        from test_k6_r1 import _h, _run
        for concern, asks in ((True, True), (_MISSING, True), (False, False)):
            with self.subTest(concern=concern):
                h = _h(self)
                h.p.valves = {}
                h.p.unverified = frozenset(["QA"])
                f = {"defects": [], "checklist": ["확인"], "quality_bar_met": "yes", "verdict": "pass",
                     CONS.SECURITY_REASON: "API 키가 평문 로그에 남음"}
                d = _d("pass", concern, **f)
                if asks:
                    with self.assertRaises(CONS.Ask) as cm:
                        _run(h, "QA", "v1", lambda spec: d)
                    self.assertIn("보안", cm.exception.line)
                else:
                    out = _run(h, "QA", "v1", lambda spec: d)
                    self.assertEqual(out.post_hoc, "unverified QA")

    def test_an_unverified_kickoff_with_a_security_concern_is_confirmed(self):
        for concern, pends in ((True, True), (False, False)):
            with self.subTest(concern=concern):
                k = kickoff()
                k.fields[CONS.SECURITY_FIELD] = concern
                h = K4(self, roles=[evidence(self)] * 2, judges={"KICKOFF": k})
                h.p._first_sprint = False
                h.p.unverified = frozenset(["KICKOFF"])
                h.p.valves = {}
                A.run(h.p)
                pend = [b for b in _blocks(h) if b.get("status") == "pending-human"]
                self.assertEqual(bool(pend), pends)
                kb = h.decisions_of("KICKOFF")[-1]
                self.assertEqual(kb.get("post_hoc"), None if pends else "unverified KICKOFF")

    def _exarb_run(self, sev, concern):
        f = {"findings": [{"id": "F1", "verdict": "dismiss", "reason": "guarded",
                           "evidence": [{"path": "lib/a.dart", "line": 1, "quote": "int a() => 2;"}]}],
             "summary": "s"}
        if concern is not _MISSING:
            f[CONS.SECURITY_FIELD] = concern
        h = XHarness(self, roles=[dev(), K3.TL_DONE, auditor([finding(sev)])] + [dev(), K3.TL_DONE, auditor()],
                     suites=[K3.GREEN] * 4, judges={"EX-ARB": [decision("s", f)]})
        return h, X.run(h.p, "implement")

    def test_ex_arb_never_dismisses_under_a_security_concern(self):
        # BLOCKER: a dispute (a person decides); MAJOR: accepted (fixed, never dropped unasked)
        h, r = self._exarb_run("BLOCKER", True)
        self.assertEqual(r.cause, "disputed auditor BLOCKER")
        h, r = self._exarb_run("MAJOR", _MISSING)
        ex = [b for b in _blocks(h) if b.get("point") == "EX-ARB"][0]
        self.assertEqual(ex.get("choice"), "F1:accept")
        self.assertEqual(ex.get("security"), "F1")
        h, r = self._exarb_run("MAJOR", False)
        ex = [b for b in _blocks(h) if b.get("point") == "EX-ARB"][0]
        self.assertEqual(ex.get("choice"), "F1:dismiss")


class M1TextTrigger(_Briefs):
    """The extra trigger (no decision yet): issue phrases in en / ko / ja — never feature or bug words (m1)."""

    def _check(self, rows):
        bad = ["%s: security=%s, want %s" % (n, CONS.security(m()), w) for n, m, w in rows if CONS.security(m()) != w]
        self.assertEqual(bad, [], "\n".join(bad))

    def test_issue_phrases_in_the_repos_language(self):
        self._check([
            ("QA ko", lambda: self._qa(["API 키가 로그에 평문으로 기록됨 — 보안 문제"]), True),
            ("QA ja", lambda: self._qa(["APIキーが平文でログに出力される（セキュリティ上の問題）"]), True),
            ("DE-ARB ko", lambda: self._dearb("tech-lead", "리프레시 토큰을 SharedPreferences 에 평문 저장 — 보안 취약점"), True),
            ("STAKES ko", lambda: self._stakes("tech-lead", "토큰 저장 위치가 다른 앱에 노출된다(보안)"), True),
            ("QA secret", lambda: self._qa(["the Firebase admin secret is committed in lib/config.dart"]), True),
            ("QA credentials", lambda: self._qa(["store credentials are hard-coded in the app bundle"]), True),
            ("QA password", lambda: self._qa(["the user's password is sent to the analytics event"]), True),
            ("QA unencrypted", lambda: self._qa(["the refresh token is stored unencrypted on disk"]), True),
            ("DE-ARB exposed", lambda: self._dearb("tech-lead", "the admin endpoint is exposed without a check"), True),
        ])

    def test_feature_and_bug_words_are_not_issues(self):
        self._check([
            ("dependency injection", lambda: self._dearb("tech-lead", "use dependency injection (get_it) for the repo"),
             False),
            ("memory leak", lambda: self._qa(["memory leak: the StreamController is not closed on dispose"]), False),
            ("unauthenticated feature", lambda: self._qa(["unauthenticated users are redirected to the login screen"]),
             False),
            ("401 feature", lambda: self._stakes("tech-lead", "show the re-login dialog on 401 Unauthorized?"), False),
            ("keychain feature", lambda: self._qa(["the token now lives in the keychain — 재설치 후 확인"]), False),
            ("encrypt feature", lambda: self._qa(["encrypt the backup file before upload — 확인"]), False),
            ("보안 저장소 feature", lambda: self._qa(["보안 저장소(Keychain)에 토큰 저장 확인"]), False),
            ("노출 UI", lambda: self._qa(["설정 화면에 문제 유형 항목이 노출되는지 확인"]), False),
            ("INJECTION_RAW", lambda: self._qa(["INJECTION_RAW 테스트 출력 확인"]), False),
        ])


# ---- m2: the group drift question -----------------------------------------------------------------------------------

class M2GroupDrift(T6.M2DriftAccept):
    def test_the_question_carries_every_change_and_its_fingerprint(self):
        pass

    def test_accept_is_bound_to_the_drift_that_was_shown(self):
        pass

    def test_the_runner_accepts_only_the_fingerprint_it_showed(self):
        pass

    def test_a_group_question_shows_what_its_fingerprint_binds(self):
        wt = repo(self, {"lib/a.dart": "a\n"})
        git(wt, "switch", "-q", "-c", "fix/1")
        r = self._runner(wt)

        def spec(role_name, task):
            return RR.RoleSpec(role_name, task, "t", issue=1, stage="s", step="x", worktree=wt, model="sonnet",
                               base="main", branch="fix/1", remote_check=False)
        self.assertEqual(r.run_role(spec("developer", "implement")).status, "DONE")
        T6._w(wt, "lib/a.dart", "a person's edit\n")
        real = r.drift_check

        def drift_check(*a, **k):
            late = real(*a, **k)
            T6._w(wt, "lib/orphan.dart", "an orphan's write right after the read\n")
            return late
        r.drift_check = drift_check
        res = r.run_group([spec("tester", "cases")])[0]
        self.assertEqual(res.status, "DRIFT")
        shown = " ".join(res.violations)
        self.assertNotIn("lib/orphan.dart", shown)
        r.drift_check = real
        # the fingerprint is the shown snapshot's: the orphan's write is a change since → not accepted, asked again
        again = r.accept_drift(wt, 1, res.extras["drift_fp"])
        self.assertIsNotNone(again)
        self.assertIn("lib/orphan.dart", " ".join(again[0]))

    def test_every_item_rides_on_the_block_and_only_the_line_is_cut(self):
        items = ["path lib/feature_%03d/really/long/directory/name/widget_file_%03d.dart" % (i, i) for i in range(120)]
        vals, listed = B.drift_chunks(items)
        self.assertEqual(listed, 120)
        self.assertEqual(" ;; ".join(vals).split(" ;; "), items)
        self.assertTrue(all(len(v) <= B.DRIFT_CHUNK for v in vals))
        many = items * 20
        vals, listed = B.drift_chunks(many)
        self.assertEqual(len(vals), B.DRIFT_CHUNKS)
        self.assertEqual(" ;; ".join(vals).split(" ;; "), many[:listed])
        from _k2 import Harness, fixture
        h = Harness(self, fixture(labels=("guild:design",)))
        h.p.unattended = False
        B.drift_question(h.p, "design", "tester", many, "fp1")
        q = [b for b in _blocks(h) if b.get("kind") == B.DRIFT_KIND][-1]
        self.assertEqual(q.get("drift_items_unlisted"), str(len(many) - listed))
        self.assertIn("listed on this question, all %d" % len(many), q.get("question") or "")


# ---- m3: the PR title -----------------------------------------------------------------------------------------------

class M3PrTitle(unittest.TestCase):
    def _title(self, variant, issue_title, roles):
        h = XHarness(self, roles=roles, suites=[K3.GREEN, K3.GREEN])
        h.gh.fx["issues"]["7"]["title"] = issue_title
        r = X.run(h.p, variant)
        self.assertEqual(r.kind, "ADVANCE", r.token())
        return h.gh.fx["prs"][-1]["title"]

    def test_through_the_execute_stage(self):
        self.assertEqual(self._title("debug", "fix: 한자 상세 로드 오류 문구",
                                     [dev(), dev(red=["00:01 +0 -1: Some tests failed."]), K3.TL_DONE, auditor()]),
                         "fix: 한자 상세 로드 오류 문구")
        self.assertEqual(self._title("implement", "feat(kanji): 획순 섹션", [dev(), K3.TL_DONE, auditor()]),
                         "feat(kanji): 획순 섹션")
        self.assertEqual(self._title("implement", "획순 섹션 추가", [dev(), K3.TL_DONE, auditor()]), "feat: 획순 섹션 추가")

    def test_the_prefix_forms(self):
        for t, want in (("fix: a", "fix: a"), ("refactor!: a", "refactor!: a"), ("chore(deps): a", "chore(deps): a"),
                        ("Note: a", "feat: Note: a"), ("a: b c", "feat: a: b c"), ("Fix: a", "Fix: a"), ("v2.0: x", "feat: v2.0: x"),
                        ("fix:a", "fix:a")):                       # 0.102.8 m4: no space is a prefix too
            self.assertEqual(X.pr_title("implement", t), want, t)


# ---- m4: code trigger blocks are rows -------------------------------------------------------------------------------

class M4TriggerRows(unittest.TestCase):
    def test_every_code_trigger_block_is_a_row(self):
        net = T6.Blk(3, point="net-unverified", stage="execute", by="code", choice="unverified(net)",
                     grade="trigger", reason="env at HEAD — sqlite native asset")
        fl = T6.Blk(4, point="flake", stage="test", by="code", choice="green", grade="trigger", reason="t1")
        plain = T6.Blk(5, point="tripwire", stage="execute", by="code", choice="benign")
        sel = G.select({7: [net, fl, plain]}, "o/r", False, 0.0, lambda i, x: None)
        rows = dict((x[1].id, x[2]) for x in sel)
        self.assertTrue(rows["D3"].startswith("triggered: net-unverified — env at HEAD"))
        self.assertTrue(rows["D4"].startswith("triggered: flake — "))
        self.assertNotIn("D5", rows)

    def test_the_real_net_unverified_block_is_a_row(self):
        from _k2 import Harness, fixture
        h = Harness(self, fixture(labels=("guild:execute",)))
        X.net_unverified(h.p, "env at HEAD — x")
        b = [x for x in _blocks(h) if x.get("point") == "net-unverified"][-1]
        self.assertTrue(G.code_trigger_row(b))
        self.assertTrue(G.select({7: [b]}, "o/r", False, 0.0, lambda i, x: None))


# ---- m5: nested KICKOFF readings ------------------------------------------------------------------------------------

EXTRA = {"lib/settings/settings.dart": "int s = 1;\n", "lib/theme/theme.dart": "int t = 1;\n",
         "supabase/migrations/001.sql": "create table t();\n"}


def _nested(narrow=None, chosen="B", concern=False, broad_areas=("lib/app", "lib/settings", "lib/theme")):
    """#1797 D5 in small: C (entry point only) ⊂ A (+ the fix) ⊂ B (+ a refactor); the judge recommends A."""
    k = kickoff(constraint="partial", anchors={"constraint": ANCHOR_OK}, areas=("lib/app", "lib/settings"),
                ac=("the entry point shows the type", "the fix keeps the summary right"))
    nar = {"id": "C", "summary": "진입점 추가만", "areas": ["lib/app"], "nested_in": ["A", "B"],
           "keeps_issue_ac": True, "ac": ["the entry point shows the type"],
           "drops": ["exampleReading 불일치 수정", "공용 위젯 추출"]}
    nar.update(narrow or {})
    k.fields["interpretations"] = [
        {"id": "A", "summary": "진입점 + 불일치 수정", "areas": ["lib/app", "lib/settings"], "nested_in": ["B"]},
        {"id": "B", "summary": "진입점 + 수정 + 공용 위젯 추출", "areas": list(broad_areas)},
        nar]
    k.fields["chosen"] = chosen
    k.fields[CONS.SECURITY_FIELD] = concern
    k.fields["readiness"]["constraint"]["about_readings"] = True       # 0.102.8: the open question IS the reading
    return k


class M5Narrowest(unittest.TestCase):
    def _run(self, k, unverified=False):
        h = K4(self, roles=[evidence(self, areas=("lib/app", "lib/settings", "lib/theme"))] * 2, extra_files=EXTRA,
               judges={"KICKOFF": k, "STAKES": stakes("high")})
        h.p._first_sprint = False
        h.p.valves = {}
        h.p.unverified = frozenset(["KICKOFF"]) if unverified else frozenset()
        return h, A.run(h.p)

    def test_the_narrowest_nested_reading_is_taken_without_a_person(self):
        h, r = self._run(_nested())
        self.assertNotEqual(r.kind, "PAUSE", r.token())
        self.assertEqual([b for b in _blocks(h) if b.get("status") == "pending-human"], [])
        kb = h.decisions_of("KICKOFF")[-1]
        tok = kb.get("auto_narrow")
        self.assertEqual(kb.get("chosen"), tok)
        self.assertEqual(kb.get("post_hoc"), AN.NARROW_POST_HOC)
        self.assertEqual(kb.get("follow_ups"), "exampleReading 불일치 수정 ;; 공용 위젯 추출")
        self.assertEqual(kb.get("areas"), "lib/app")
        out = h.body_with("analyze:output")
        self.assertIn("the entry point shows the type", out)
        acs = out.split("### 수용 기준")[1].split("###")[0]
        self.assertNotIn("the fix keeps the summary right", acs)              # the chosen reading's AC are not its
        self.assertIn("(빠진 AC) the fix keeps the summary right", out)       # 0.102.8 M4: but on record
        self.assertIn("후속 Issue 후보: exampleReading 불일치 수정", out)
        # the post-hoc row on the grading sheet
        self.assertTrue([b for b in _blocks(h) if b.get("post_hoc") == AN.NARROW_POST_HOC])
        # and QA lists the dropped parts as follow-up candidates
        fu = Q.narrowed_followups(h.gh.comments(7))
        self.assertEqual([x["title"] for x in fu], ["exampleReading 불일치 수정", "공용 위젯 추출",
                                                    "AC: the fix keeps the summary right"])

    def test_any_condition_missing_asks_as_before(self):
        rows = [
            ("not nested in every reading", _nested({"nested_in": ["B"]})),
            ("drops an AC of the Issue", _nested({"keeps_issue_ac": False})),
            ("keeps_issue_ac missing", _nested({"keeps_issue_ac": None})),
            ("no own AC (not chosen)", _nested({"ac": []})),
            ("nothing dropped named", _nested({"drops": []})),
            ("security concern", _nested(concern=True)),
            ("security field missing", _nested(concern=None)),
            ("areas not inside the others", _nested({"areas": ["lib/app", "lib/theme"]})),
            ("unknown own footprint", _nested({"areas": []})),
            ("irreversible", _nested({"areas": ["lib/app", "supabase/migrations"]},
                                     broad_areas=("lib/app", "lib/settings", "lib/theme", "supabase/migrations"))),
        ]
        for name, k in rows:
            with self.subTest(case=name):
                if k.fields.get(CONS.SECURITY_FIELD) is None:
                    k.fields.pop(CONS.SECURITY_FIELD, None)
                for i in k.fields["interpretations"]:
                    if i.get("keeps_issue_ac") is None and "nested_in" in i and i["id"] == "C":
                        i.pop("keeps_issue_ac", None)
                h, r = self._run(k)
                self.assertEqual(r.kind, "PAUSE", name)
                self.assertTrue([b for b in _blocks(h) if b.get("status") == "pending-human"], name)
                self.assertIsNone(h.decisions_of("KICKOFF")[-1].get("auto_narrow"), name)

    def test_a_judge_that_already_chose_the_narrowest_keeps_its_ac(self):
        h, r = self._run(_nested(chosen="C"))
        self.assertNotEqual(r.kind, "PAUSE", r.token())
        out = h.body_with("analyze:output")
        self.assertIn("the fix keeps the summary right", out)               # the judge's own AC for its pick

    def test_the_evidence_case_shape(self):
        # word_app #1797 D5: i3 (entry point only) ⊂ i1 (+ fix) ⊂ i2 (+ refactor) by areas — the engine's check
        k = AN.Kickoff()
        root = repo(self, dict((d + "/x.dart", "x\n") for d in (
            "lib/controller", "lib/features/review_screen/widgets", "lib/features/setting_screen/widgets",
            "lib/helpers/languages", "lib/widgets", "test")))
        i3 = ["lib/features/setting_screen/widgets", "lib/helpers/languages", "test"]
        i1 = ["lib/controller", "lib/features/review_screen/widgets"] + i3
        i2 = i1 + ["lib/widgets"]
        k.interpretations = [{"id": "i1", "summary": "r1 + 불일치 수정", "orig": "r2"},
                             {"id": "i2", "summary": "r2 + 공용 위젯 추출", "orig": "r3"},
                             {"id": "i3", "summary": "진입점 추가만", "orig": "r1"}]
        k.chosen = "i1"
        k.own_footprints = {"i1": {"areas": i1, "nested_in": ["r3"]}, "i2": {"areas": i2},
                            "i3": {"areas": i3, "nested_in": ["r2", "r3"], "keeps_issue_ac": True,
                                   "ac": ["설정에 문제 유형 항목"], "drops": ["exampleReading 불일치 수정"]}}
        cap = [{"token": "i1", "areas": i1}, {"token": "i2", "areas": i2}, {"token": "i3", "areas": i3}]
        tok, own, drops = AN.narrowest(k, cap, root, False, False)
        self.assertEqual((tok, drops), ("i3", ["exampleReading 불일치 수정"]))


# ---- the #1797 auditor: its own out/ is writable --------------------------------------------------------------------

class AuditorOut(unittest.TestCase):
    def test_every_role_and_task_may_write_its_own_out(self):
        for key in P.ROLE_CLASSES:
            role, task = {"tech-lead-design": ("tech-lead", "design"), "tech-lead-review": ("tech-lead", "conformance"),
                          "tester-cases": ("tester", "cases"), "tester-verify": ("tester", "verify"),
                          "reviewer": ("security", None)}.get(key, (key, None))
            with self.subTest(role=key):
                allow, deny = P.role_rules(role, task, run_dir="/r")
                self.assertIn("Write(//r/out/**)", allow)
                self.assertNotIn("Write", deny)
        a, _ = P.role_rules("auditor", None, run_dir="/r", worktree="/w")
        self.assertFalse([x for x in a if x.startswith(("Write(//w", "Edit(//w", "Bash"))])    # still reads the repo only

    def test_a_read_only_task_writes_its_result_under_the_scrubbed_env(self):
        # the CLI as 2.1.323 behaves under CLAUDE_CODE_SUBPROCESS_ENV_SCRUB: permission mode forced to `default` —
        # a tool runs only when `--allowedTools` lists it; else the write is refused and the role falls back
        wt = repo(self, {"lib/a.dart": "a\n"})
        runs = os.path.join(tmpdir(self), "runs")
        seen = {}

        def cli(argv, env, cwd, stdin):
            seen["scrub"] = env.get("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB")
            allow = argv[argv.index("--allowedTools") + 1].split(",")
            run_dir = argv[argv.index("--add-dir") + 1]
            target = os.path.join(run_dir, "out", "result.json")
            ok = any(re.match(r"^Write\(/(/.*)/\*\*\)$", a) and target.startswith(
                re.match(r"^Write\(/(/.*)/\*\*\)$", a).group(1) + "/") for a in allow)
            seen["write_allowed"] = ok
            if ok:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "w") as fh:
                    json.dump({"findings": []}, fh)

        spawn = FakeSpawn([{"stream": stream_lines(texts=[">>> RESULT <<<\nDONE: audited"]), "check": cli,
                            "stderr": "⚠ Permission mode forced to default — CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is set"}])
        r = RR.Runner(journal=T6.EvJournal(), parent_env={"PATH": os.environ["PATH"]}, spawn=spawn,
                      user_settings=os.path.join(tmpdir(self), "u"), run_root_dir=runs, claude="claude", clock=Clock())
        res = r.run_role(RR.RoleSpec("auditor", "scan", "audit", issue=1, stage="execute", step="X3.5a", worktree=wt,
                                     model="sonnet", remote_check=False,
                                     result_schema={"type": "object", "required": ["findings"],
                                                    "properties": {"findings": {"type": "array"}}}))
        self.assertEqual(seen, {"scrub": "1", "write_allowed": True})
        self.assertEqual(res.status, "DONE", res.line)
        self.assertEqual(res.extras.get("findings"), [])

    def test_a_concerned_auditor_with_valid_findings_is_an_audit_not_a_pause(self):
        # #1797 runs 018/020: the write was refused, the findings came in the guild-result block with
        # DONE_WITH_CONCERNS — 0 BLOCKER/MAJOR: the attempt advances
        # 0.102.8 (M3): the runner saw the Write of out/result.json refused and read the findings from the fence
        dwc = RoleResult("DONE_WITH_CONCERNS", "out/result.json 쓰기 권한이 거부되어 guild-result 블록으로 제출",
                         {"findings": [finding("MINOR")]}, result_source="fence",
                         denials=[{"role": "auditor", "command": "Write", "class": "tool:Write", "tool": "Write",
                                   "path": "/runs/020-execute-auditor-scan/out/result.json"}])
        h = XHarness(self, roles=[dev(), K3.TL_DONE, dwc], suites=[K3.GREEN])
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE", r.token())
        self.assertTrue([b for b in _blocks(h) if b.get("point") == "auditor-result"])
        # an unreadable reply still stops (nothing parsed)
        bad = RoleResult("DONE_WITH_CONCERNS", "x", {})
        h = XHarness(self, roles=[dev(), K3.TL_DONE, bad, bad], suites=[K3.GREEN])
        r = X.run(h.p, "implement")
        self.assertIn("auditor scan failed", r.token())


if __name__ == "__main__":
    unittest.main()
