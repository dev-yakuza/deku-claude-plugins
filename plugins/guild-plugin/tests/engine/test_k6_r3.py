"""review-k6-r3 — the fixes, as table tests over the cases the findings name.

M1  a person's KICKOFF reading is carried to the next run as the READING (captured when asked — `readings_sha`), never
    as a token the next judge re-binds: the person picks B ≠ the judge's A, the next judge re-words its summaries (the
    canonical order flips) → still B — its summary, tokens and footprint (`areas` · `ui_surface` · `cast`); a judge
    that keeps its own pick pauses; a clone without the journal opens the capture from the answer's resolution;
M2  Issue-wide sealing: a run that stops before its gate (A5 close question) seals the footprint, so the blind
    question asked after `proceed` sees the same text whichever reading the judge chose; an earlier plain footprint /
    `analyze:output` refuses a later blind reading question; STAKES `irreversible` is sealed before the blind question
    and revealed after the answer — §9.5 reads the revealed value (an unrevealed seal = irreversible);
M3  a scope clause wins over a product noun (본문 · issue · requests · 本文 · 依頼 …) — shown, never cut (ko/en/ja);
M4  a directory AREA matches an irreversible / harness glob (`supabase/migrations`, `lib/db`, `migrations`);
m1  a numeric / symbolic rating aside (`(90%)`, `(#1)`, `(★★★)`, `(✓)`, `(9/10)`, `(A+)`) refuses the blind answer;
m2  an INHERENT decision is one release verdict: its applied block and a rule-changed block never count, a re-ask of
    the same point counts once;
m3  an open candidate gone from the decision log is reconciled away (reported) — an unreadable log keeps it;
    `dev health` lists the open keys;
m4  an inherent-gate sheet row carries the post-hoc evidence and never the person's own answer;
m5  a code span is never cut into (`Get.back()`, `foo(a, b)`).
"""

import csv
import json
import os
import tempfile
import unittest

import _util  # noqa: F401
import test_k6_r1 as R1
import test_k6_r2 as R2
from _k1 import tmpdir
from _k4 import K4, evidence, kickoff, stakes
from test_k5_cli import Env

from guildcore import ask as ASK
from guildcore import journal as J
from guildcore.decisions import DecisionLog
from workflows.dev import analysis as AN
from workflows.dev import arbitration as ARB
from workflows.dev import cli as CLI
from workflows.dev import conservative as CONS
from workflows.dev import grade as G
from workflows.dev import predict as PF
from workflows.dev import unverified as UV
from workflows.dev.replay import label_audit as LA
from workflows.dev.stages import analyze as A
from workflows.dev.stages import base as B
from workflows.dev.stages import design as DS
from workflows.dev.stages.base import StageResult

EXTRA = dict(R2.EXTRA, **{"lib/db/local/store.dart": "int d = 1;\n"})
WIDE = ("lib/app", "lib/settings", "lib/theme")
SUMM = {"A": "설정 화면만 다크 모드", "B": "앱 전체 다크 모드"}
REWORD = {"A": "설정 화면 한정 다크 모드", "B": "다크 모드를 앱 전체에"}       # canonical order flips (다 < 설)


def _blocks(h):
    return DecisionLog.load(h.gh.comments(7)).blocks


def _pending(h):
    return [b for b in _blocks(h) if b.get("status") == "pending-human"]


def _kick(chosen, summ=SUMM, own=None, areas=None, ui=None):
    k = kickoff(ui=(chosen == "B") if ui is None else ui,
                areas=areas or (("lib/settings",) if chosen == "A" else WIDE))
    k.fields["interpretations"] = [dict({"id": i, "summary": summ[i]}, **((own or {}).get(i) or {})) for i in ("A", "B")]
    k.fields["chosen"] = chosen
    return k


def _token(summ, orig):
    interp = [{"id": i, "summary": summ[i]} for i in ("A", "B")]
    order = sorted(range(2), key=lambda n: AN.canon_key(interp[n]))
    return "i%d" % (order.index(("A", "B").index(orig)) + 1)


def _run1(case, judge_pick, own=None, unattended=False):
    """Run 1: the judge picks `judge_pick`; the first-sprint confirmation asks the blind reading question."""
    h = K4(case, unattended=unattended, roles=[evidence(case, areas=WIDE)] * 3, judges={"KICKOFF": _kick(judge_pick, own=own)},
           extra_files=EXTRA)
    h.p._first_sprint = True
    h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r3-"), 7, h.clock)
    if unattended:
        h.p.valves = {"group.KICKOFF.conservative": True}
    r = A.run(h.p)
    return h, r


class M1ReadingCarried(unittest.TestCase):
    def _answer_and_rerun(self, judge_pick, person, judge2, journal2="same", answer_journal=True):
        h, r = _run1(self, judge_pick)
        self.assertEqual(r.kind, StageResult.ASK)
        pend = _pending(h)[-1]
        self.assertTrue(pend.get("readings_sha"))                 # the readings are sealed on the question
        ASK.answer(h.decisions, h.writer, 7, pend.id, _token(SUMM, person),
                   journal=h.p.journal if answer_journal else None)
        if journal2 == "fresh":                                   # another clone: none of run 1's journal
            h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r3-b-"), 7, h.clock)
        h.judges["KICKOFF"] = judge2
        r2 = A.run(h.p)
        return h, r2, DS.kickoff_block(h.gh.comments(7))

    def test_person_reading_survives_a_reworded_judge(self):
        """judge × person × wording: the run after the answer carries the person's reading — its summary under its
        question-time token, its footprint — whatever the new judge's summaries are."""
        for judge_pick in ("A", "B"):
            for person in ("A", "B"):
                for summ2 in (SUMM, REWORD):
                    with self.subTest(judge=judge_pick, person=person, reworded=summ2 is REWORD):
                        # the new judge takes the person's reading (the brief names its id) — in re-worded summaries
                        h, r2, kick = self._answer_and_rerun(judge_pick, person, _kick(person, summ=summ2))
                        self.assertEqual(r2.kind, StageResult.ADVANCE)
                        tok = _token(SUMM, person)
                        self.assertIn("- (선택) %s: %s" % (tok, SUMM[person]), h.body_with("analyze:output"))
                        maps = [e["map"] for e in h.p.journal.entries if e.get("what") == "kickoff-tokens"]
                        self.assertEqual([m["orig"] for m in maps[-1] if m["token"] == tok], [person])
                        want_areas = "lib/settings" if person == "A" and judge_pick == "A" else None
                        if want_areas:
                            self.assertEqual(kick.get("areas"), want_areas)
                        else:
                            self.assertNotEqual(kick.get("areas"), "lib/settings")
                        if person == "B":
                            self.assertEqual(kick.get("ui_surface"), "true")   # never the settings-only footprint
                        self.assertIsNone(kick.get("footprint_sha"))

    def test_judge_keeping_its_own_pick_pauses_with_the_persons_footprint(self):
        h, r2, kick = self._answer_and_rerun("A", "B", _kick("A", summ=REWORD))
        self.assertEqual(r2.kind, StageResult.ASK)
        self.assertIn("따르지 않음", _pending(h)[-1].get("question"))
        self.assertNotEqual((kick.get("areas"), kick.get("ui_surface")), ("lib/settings", "false"))
        self.assertIsNone(h.body_with("analyze:output"))
        self.assertFalse([b for b in _blocks(h) if b.get("point") == "applied"])   # carried again next run

    def test_own_footprint_of_the_persons_reading(self):
        own = {"B": {"areas": ["lib/theme"], "ui_surface": True, "cast": {"participation": [], "gates": []}}}
        h, r = _run1(self, "A", own=own)
        pend = _pending(h)[-1]
        ASK.answer(h.decisions, h.writer, 7, pend.id, _token(SUMM, "B"), journal=h.p.journal)
        h.judges["KICKOFF"] = _kick("B", summ=REWORD, areas=("lib/app",))   # its top-level areas differ: ignored
        A.run(h.p)
        kick = DS.kickoff_block(h.gh.comments(7))
        self.assertEqual((kick.get("areas"), kick.get("ui_surface")), ("lib/theme", "true"))

    def test_another_clone_opens_the_capture_from_the_resolution(self):
        h, r2, kick = self._answer_and_rerun("A", "B", _kick("B", summ=REWORD), journal2="fresh")
        self.assertEqual(r2.kind, StageResult.ADVANCE)
        res = [b for b in _blocks(h) if b.get("by") == "human" and b.get("resolves")][-1]
        self.assertTrue(ASK.seal_check(_pending(h)[0].get("readings_sha") or
                                       [b for b in _blocks(h) if b.get("readings_sha")][0].get("readings_sha"),
                                       res.get("readings"), res.get("readings_nonce")))
        self.assertIn("- (선택) %s: %s" % (_token(SUMM, "B"), SUMM["B"]), h.body_with("analyze:output"))

    def test_unopenable_capture_pauses_instead_of_guessing(self):
        h, r2, _kick_ = self._answer_and_rerun("A", "B", _kick("B", summ=REWORD), journal2="fresh",
                                               answer_journal=False)
        self.assertEqual(r2.kind, StageResult.ASK)
        self.assertIn("확인할 수 없음", _pending(h)[-1].get("question"))

    def test_brief_names_the_reading_not_the_token(self):
        seen = []

        def judge(spec):
            seen.append(dict(spec.brief_parts).get("human_answers"))
            return _kick("A") if len(seen) == 1 else _kick("B", summ=REWORD)
        h = K4(self, unattended=False, roles=[evidence(self, areas=WIDE)] * 2, judges={"KICKOFF": judge},
               extra_files=EXTRA)
        h.p._first_sprint = True
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r3-"), 7, h.clock)
        A.run(h.p)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, _token(SUMM, "B"), journal=h.p.journal)
        A.run(h.p)
        self.assertIn("«%s»" % SUMM["B"], seen[-1])
        self.assertIn("id B", seen[-1])


class M2IssueWideSeal(unittest.TestCase):
    def _close_then_proceed(self, pick):
        k = _kick(pick)
        k.fields["close"] = {"decide": "completed", "source": "issue", "line": "already done?"}
        h = K4(self, unattended=False, roles=[evidence(self, areas=WIDE)] * 3, judges={"KICKOFF": k}, extra_files=EXTRA)
        h.p._first_sprint = True
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r3-"), 7, h.clock)
        r1 = A.run(h.p)
        self.assertEqual(r1.kind, StageResult.ASK)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, "proceed", journal=h.p.journal)
        r2 = A.run(h.p)
        return h, r2

    def test_close_question_run_seals_the_footprint(self):
        seen = {}
        for pick in ("A", "B"):
            h, r2 = self._close_then_proceed(pick)
            self.assertEqual(r2.kind, StageResult.ASK)
            q = _pending(h)[-1]
            self.assertTrue(q.get("predict_first"))                        # still blind
            self.assertFalse(q.get("predict_first_refused"))
            shown = []
            for b in _blocks(h):
                f = dict((k, v) for k, v in dict(b.fields).items() if not k.endswith("_sha") and k not in ("id", "at", "inputs"))
                shown.append(f)
                for x in PF.KICKOFF_FOOTPRINT:
                    if b.get("point") == "KICKOFF":
                        self.assertIsNone(b.get(x))
                self.assertNotIn("KICKOFF footprint", json.dumps(dict(b.fields), ensure_ascii=False))
            seen[pick] = shown
        self.assertEqual(seen["A"], seen["B"])

    def test_earlier_plain_footprint_refuses_a_later_blind_reading_question(self):
        h = K4(self, unattended=False, roles=[evidence(self, areas=WIDE)] * 3, judges={"KICKOFF": _kick("A")},
               extra_files=EXTRA)
        h.p._first_sprint = False
        self.assertEqual(A.run(h.p).kind, StageResult.ADVANCE)               # no question: the footprint is open
        h.gh.fx["issues"]["7"]["labels"] = [{"name": "guild:analyze"}]       # a loop-back re-analysis
        h.p._first_sprint = True
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.ASK)
        q = _pending(h)[-1]
        self.assertFalse(q.get("predict_first"))
        self.assertIn("earlier", q.get("predict_first_refused") or "")

    def test_earlier_reading_unit(self):
        h = K4(self, unattended=False, roles=[], judges={}, extra_files=EXTRA)
        self.assertIsNone(PF.earlier_reading(h.p, h.decisions._log()))
        h.decisions.record({"point": "KICKOFF", "stage": "analyze", "by": "judge:opus", "choice": "goal=clear",
                            "footprint": PF.FOOTPRINT_WITHHELD, "footprint_sha": "x"})
        self.assertIsNone(PF.earlier_reading(h.p, h.decisions._log()))         # sealed: nothing shown
        h.decisions.record({"point": "KICKOFF", "stage": "analyze", "by": "judge:opus", "choice": "goal=clear",
                            "areas": "lib/settings"})
        self.assertIn("earlier KICKOFF footprint", PF.earlier_reading(h.p, h.decisions._log()))

    def _stakes_run(self, pick):
        k = kickoff(goal="unclear", areas=(("lib/settings",) if pick == "A" else ("lib/settings", "lib/db/local")))
        k.fields["interpretations"] = [{"id": "A", "summary": "설정 화면에 저장 옵션 추가"},
                                       {"id": "B", "summary": "설정과 함께 로컬 DB 스키마에 저장 옵션 추가"}]
        k.fields["chosen"] = pick
        h = K4(self, unattended=True, roles=[evidence(self, areas=("lib/settings",))] * 3,
               judges={"KICKOFF": k, "STAKES": stakes("medium", "a settings toggle")}, extra_files=EXTRA)
        h.p.valves = {"group.KICKOFF.conservative": True}
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r3-"), 7, h.clock)
        r = A.run(h.p)
        return h, r

    def test_stakes_irreversible_is_sealed_then_revealed(self):
        vis, irr = {}, {}
        for pick in ("A", "B"):
            h, r = self._stakes_run(pick)
            self.assertEqual(r.kind, StageResult.PAUSE)
            st = [b for b in _blocks(h) if b.get("point") == "STAKES"]
            self.assertTrue(st and all(b.get("irreversible_sha") and b.get("irreversible") is None for b in st))
            vis[pick] = [sorted(k for k in dict(b.fields) if k not in ("at",)) + [b.get("choice")] for b in st]
            # before any answer §9.5 reads the seal as irreversible (the stricter class)
            self.assertTrue(G.block_irreversible(st[0], _blocks(h)))
            ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, "i1", journal=h.p.journal)
            A.run(h.p)
            rv = [b for b in _blocks(h) if b.get("point") == ARB.REVEAL]
            self.assertEqual([b.get("refs") for b in rv], [st[0].id])
            irr[pick] = G.block_irreversible(st[0], _blocks(h))
            self.assertEqual(G.engine_view(st[0], _blocks(h))[1], irr[pick])
        self.assertEqual(vis["A"], vis["B"])
        self.assertEqual(irr, {"A": False, "B": True})

    def test_a_forged_reveal_is_not_read(self):
        h, r = self._stakes_run("B")
        st = [b for b in _blocks(h) if b.get("point") == "STAKES"][0]
        h.decisions.record({"point": ARB.REVEAL, "stage": "analyze", "by": "code", "choice": "irreversible",
                            "refs": st.id, "field": "irreversible", "irreversible": "false", "nonce": "00"})
        self.assertTrue(G.block_irreversible(st, _blocks(h)))


SCOPE_PAIRS = (                      # review-k6-r3 repro_aside_classes.ScopeCut + more ko / en / ja
    (("게시글 편집 화면 개편 (본문 편집기 제외)", "게시글 목록 화면 개편"), "본문 편집기 제외"),
    (("알림 설정 추가 (이슈 알림만)", "알림 센터 신설"), "이슈 알림만"),
    (("검색 개선 (설명 필드 제외)", "검색 화면 재설계"), "설명 필드 제외"),
    (("글 목록 개편 — 제목만 표시", "글 목록 전체 재설계"), "제목만 표시"),
    (("Edit posts (title only)", "Rewrite the post editor"), "title only"),
    (("Rate limiting (write requests only)", "Global throttling"), "write requests only"),
    (("Export tickets (except the issue body)", "Export dashboard"), "except the issue body"),
    (("Search (description field excluded)", "Search redesign"), "description field excluded"),
    (("記事編集の刷新（本文は対象外）", "記事一覧の刷新"), "本文は対象外"),
    (("通知設定の追加（依頼通知のみ）", "通知センターの新設"), "依頼通知のみ"),
    (("チケット出力（タイトルを除く）", "ダッシュボード出力"), "タイトルを除く"),
)
REAL_AC = (          # review-k6-r3 M3: content clauses r2 cut silently from the real word_app AC corpus
    ("확장 후 기존 `test_gate_precommit.py`의 회귀 없이 그린이며, 신규 케이스(셸 `#` 주석에 이슈번호가 있으면 게이트가 "
     "차단)를 추가한다.", "이슈번호가 있으면"),
    ("오탐 없음 확인 — 셸 스크립트의 일반적인 `#!/usr/bin/env bash` shebang이나 무관한 `#`을 포함한 문자열 등을 "
     "이슈번호로 오탐하지 않는다.", "이슈번호로 오탐하지 않는다"),
    ("그 뒤 `getAppDBVersion()` 이 그 실행에서 본 최대 sourceVersion 을 돌려준다(다음 실행은 그 버전부터 요청한다).",
     "그 버전부터 요청한다"),
)


class M3ScopeOverProductNoun(unittest.TestCase):
    def test_scope_pairs_show_their_scope(self):
        for pair, scope in SCOPE_PAIRS:
            with self.subTest(label=pair[0]):
                shown = LA.blind_question(list(pair))
                self.assertIsNotNone(shown, pair)
                self.assertIn(scope, shown[0])

    def test_real_ac_content_is_never_cut(self):
        for line, clause in REAL_AC:
            with self.subTest(line=line[:30]):
                nl = PF.neutral_label(line)
                self.assertTrue(nl is None or clause in nl, nl)

    def test_clause_kinds(self):
        for t, k in (("본문 편집기 제외", "scope"), ("write requests only", "scope"), ("本文は対象外", "scope"),
                     ("except the issue body", "scope"), ("이슈 알림만", "scope"),
                     ("only what the request asks", "other"),         # scope + a reading word: refused
                     ("제목이 말하는 범위", "remark"), ("as the request asks", "remark"),
                     ("overreaches the request", "remark"), ("the title does not mention login", "remark"),
                     ("제목과 어울리지 않음", "remark"),
                     ("셸 주석에 이슈번호가 있으면 게이트가 차단", "other"), ("narrow but safe", "other")):
            with self.subTest(clause=t):
                self.assertEqual(PF.clause_kind(t), k)


class M4DirectoryAreas(unittest.TestCase):
    def test_default_globs_match_the_directory_itself(self):
        for d in ("supabase/migrations", "db/migrations", "lib/db", "lib/data/drift_schemas", "migrations",
                  "prisma/migrations", "db", "src/migration", "lib/db/local", "./lib/db"):
            with self.subTest(area=d):
                self.assertEqual(AN.irreversible([d]), [d])
        for d in ("lib/settings", "lib", "lib/dbx", "lib/database", "lib/models", "lib/schema", "docs/migrations.md"):
            with self.subTest(area=d):
                self.assertEqual(AN.irreversible([d]), [])
        self.assertEqual(AN.irreversible(["lib/x.sql", "lib/api/schema.json", "proto/a.proto"]),
                         ["lib/api/schema.json", "lib/x.sql", "proto/a.proto"])

    def test_configured_globs_too(self):
        self.assertEqual(AN.irreversible(["infra/terraform"], ["**/terraform/**"]), ["infra/terraform"])

    def test_harness_directory_area(self):
        self.assertEqual(AN.harness_hit([".claude/guild/gates", ".claude/settings.json", "./.claude/guild/gates/x"]),
                         ["./.claude/guild/gates/x", ".claude/guild/gates", ".claude/settings.json"])
        self.assertEqual(AN.harness_hit([".claude", "lib/claude/settings.json"]), [])

    def test_analyze_stakes_brief_sees_a_db_area(self):
        briefs = []

        def st(spec):
            briefs.append(dict(spec.brief_parts).get("irreversible"))
            return stakes("low", "a settings toggle")
        k = kickoff(goal="partial", areas=("lib/db",), anchors={"goal": {"source": "issue", "quote": "Issue body"}})
        h = K4(self, unattended=True, roles=[evidence(self, areas=("lib/settings",))] * 2,
               judges={"KICKOFF": k, "STAKES": st}, extra_files=EXTRA)
        A.run(h.p)
        self.assertTrue(briefs and "- lib/db" in briefs[0], briefs)
        blk = [b for b in _blocks(h) if b.get("point") == "STAKES"][0]
        self.assertEqual(blk.get("choice"), "medium")                       # §3.2: never low on an irreversible path

    def test_design_reads_the_kickoff_areas(self):
        self.assertEqual(AN.irreversible("lib/app,supabase/migrations".split(",")), ["supabase/migrations"])


LITERAL = (
    ("앱 전체 다크 모드 (90%)", "설정 화면만 다크 모드 (10%)"), ("Whole app (#1)", "Login screen only (#2)"),
    ("アプリ全体（★★★）", "ログイン画面のみ（★）"), ("App-wide dark mode (✓)", "Settings-only dark mode (✗)"),
    ("Whole app (A+)", "Login only (C)"), ("Whole app (9/10)", "Login only (3/10)"),
    ("Whole app (0.9)", "Login only (0.1)"), ("앱 전체 (1위)", "로그인만 (2위)"), ("Whole app (P0)", "Login only (P2)"),
)


class m1NumericRatings(unittest.TestCase):
    def test_rating_asides_refuse(self):
        for pair in LITERAL:
            with self.subTest(pair=pair):
                self.assertIsNone(LA.blind_question(list(pair)))

    def test_bare_rating_in_the_label_refuses(self):
        self.assertIsNone(PF.neutral_label("앱 전체 다크 모드 90%"))
        self.assertIsNone(PF.neutral_label("Whole app, 9/10"))

    def test_literals_still_shown(self):
        for lb in ("dashboard (`AdminView`)", "API (v2.0)", "auth (status: 401)", "push (iOS/Android)", "export (CSV)"):
            with self.subTest(label=lb):
                self.assertEqual(PF.neutral_label(lb), lb)


class m2InherentOnce(unittest.TestCase):
    def test_applied_block_is_no_second_verdict(self):
        h = R1._h(self)
        h.p.unverified = frozenset(["QA"])
        R1._ask(h, "QA", "v1", R1._Judge("QA", "pass"))
        pend = R1._pending(h)[-1]
        R1._answer(h, "pass")
        d = R1._run(h, "QA", "v1", R1._Judge("QA", "pass"))
        did = B.record_judgment(h.p, "qa", "QA", "Q2.5", d)
        blocks = R1._blocks(h)
        rows = [{"decision_id": x, "issue": "7", "given_info": "ok"} for x in (pend.id, did)]
        fixed, rej = G.verify_rows(rows, lambda n: blocks)
        self.assertEqual(rej, [])
        self.assertEqual([r["decision_id"] for r in fixed if UV.counts(r, "human")], [pend.id])
        common = tmpdir(self)
        G.apply_judgments(common, fixed, "o/r", "human")
        self.assertEqual(G.load_state(common)["unverified"]["QA"]["n"], 1)

    def test_rule_changed_block_counts_by_its_effective_choice(self):
        h = R1._h(self)
        did = h.decisions.record({"point": "QA", "stage": "qa", "by": "judge:sonnet", "choice": "block",
                                  "raw_choice": "pass", "coerced": "true", "coerced_by": "rule"})
        fixed, _r = G.verify_rows([{"decision_id": did, "issue": "7", "given_info": "ok"}], lambda n: R1._blocks(h))
        self.assertEqual(fixed[0]["choice"], "block")
        self.assertFalse(UV.counts(fixed[0], "human"))

    def test_reasks_of_one_point_count_once(self):
        st = {}
        for did in ("D2", "D5"):
            row = {"decision_id": did, "issue": 7, "group": "QA", "mode": G.INHERENT_MODE, "choice": "pass",
                   "given_info": "ok", "point_key": "7/" + UV.point_of("conservative:QA:#7:qa:S1:L0" +
                                                                      (":a1" if did == "D5" else ""))}
            UV.count(st, row, "t", source="human")
        self.assertEqual(st["unverified"]["QA"]["n"], 1)
        self.assertEqual(UV.point_of("conservative:QA:#7:qa:S1:L0#2:a3"), "conservative:QA:#7:qa:S1:L0#2")


class m3OpenReconciled(unittest.TestCase):
    def _open(self, common, g="STAKES"):
        cand = {"decision_id": "D9", "issue": 4, "group": g, "mode": "predict-first candidate", "choice": "low"}
        G.apply_judgments(common, [], "o/r", "predict-first", candidates=[cand])
        return "decision_id,issue,group,mode,choice,given_info\nD9,4,%s,predict-first candidate,low,unsure\n" % g

    def _oks(self, common, g="STAKES"):
        oks = [{"decision_id": "D%d" % i, "issue": i, "group": g, "given_info": "ok", "mode": "predict-first",
                "choice": "low"} for i in range(10, 16)]
        return G.apply_judgments(common, oks, "o/r", "predict-first")

    def test_gone_candidate_is_dropped_and_reported(self):
        common = tmpdir(self)
        res = G.import_sheet(common, self._open(common), "o/r", blocks_of=lambda n: [])
        self.assertEqual(res.get("candidates_dropped"), [{"group": "STAKES", "key": "4/D9"}])
        self._oks(common)
        rep = [r for r in UV.report(common) if r["group"] == "STAKES"][0]
        self.assertTrue(rep["released_at"])
        self.assertEqual((rep["open"], rep["dropped"]), ([], ["4/D9"]))

    def test_unreadable_log_keeps_it(self):
        common = tmpdir(self)

        def boom(n):
            raise RuntimeError("502")
        res = G.import_sheet(common, self._open(common), "o/r", blocks_of=boom)
        self.assertFalse(res.get("candidates_dropped"))
        self._oks(common)
        rep = [r for r in UV.report(common) if r["group"] == "STAKES"][0]
        self.assertIsNone(rep["released_at"])
        self.assertEqual(rep["open"], ["4/D9"])                              # health names it

    def test_dev_grade_reconciles_its_scope(self):
        common = tmpdir(self)
        self._open(common)
        out = G.apply_judgments(common, [], "o/r", "predict-first", logs={4: {"D1", "D2"}, 5: set()})
        self.assertEqual(out.get("candidates_dropped"), [{"group": "STAKES", "key": "4/D9"}])
        common2 = tmpdir(self)
        self._open(common2)
        out = G.apply_judgments(common2, [], "o/r", "predict-first", logs={4: {"D9"}})
        self.assertFalse(out.get("candidates_dropped"))


class m4InherentRowEvidence(unittest.TestCase):
    def test_row_never_shows_the_persons_answer(self):
        for ans in ("block", "pass", "stop"):
            q = {"kind": CONS.KIND, "group": "QA", "stage": "qa", "point": "conservative:QA"}

            class Blk(dict):
                id = "D2"
            r = Blk(choice=ans, recommended="pass")
            r.id = "D3"
            row = G.inherent_row(Blk(q), r, 7)
            with self.subTest(answer=ans):
                self.assertNotIn("answered", row["reason"])
                self.assertNotIn("D3", json.dumps(row))
                self.assertEqual(row["choice"], "pass")

    def test_dev_grade_sheet_row_carries_the_evidence(self):
        e = Env(self, config={"version": "0.101.0", "language": "ko", "engine": {"first_sprint_mode": "on"}})
        dec = e.h.decisions
        qid = dec.record({"point": "conservative:QA", "kind": CONS.KIND, "group": "QA", "stage": "qa", "by": "code",
                          "status": "pending-human", "question": "q", "options": ["pass", "block", "stop"],
                          "refs": "conservative:QA:#7:qa:S1:L0", "raised_by": "confirm",
                          "predict_first_counted": "false — inherent: x"})
        dec.resolve(qid, {"point": "conservative:QA", "kind": CONS.KIND, "stage": "qa", "by": "human",
                          "choice": "block", "recommended": "pass"})
        it = e.h.gh.fx["issues"]["7"]
        it["closed_by_prs"] = [{"number": 31, "repo": "o/r"}]
        e.h.gh.fx.setdefault("prs", []).append({"number": 31, "state": "MERGED", "mergedAt": "2026-11-17T00:00:00Z",
                                                 "headRefOid": "abc1234", "url": "u", "body": "Closes #7"})
        out = os.path.join(tmpdir(self), "sheet")
        self.assertEqual(CLI.main(["grade", "--issues", "7", "--out", out], e.d), 0)
        rows = [r for r in csv.DictReader(open(os.path.join(out, "issues.csv"), encoding="utf-8"))
                if r["mode"] == G.INHERENT_MODE]
        self.assertEqual(len(rows), 1)
        self.assertIn("PR #31 merged", rows[0]["evidence"])
        self.assertNotIn("block", rows[0]["reason"] + rows[0]["evidence"] + rows[0]["note"])


class m5CodeSpans(unittest.TestCase):
    def test_code_spans_are_never_cut_into(self):
        for lb in ("Fix back nav (`Get.back()`)", "call `foo(a, b)` only", "jq filter `jq '.[]'`",
                   "guard `canPop()` 유지", "`a - b` 계산 유지"):
            with self.subTest(label=lb):
                self.assertEqual(PF.neutral_label(lb), lb)

    def test_aside_around_a_code_span(self):
        self.assertEqual(PF.neutral_label("설정 (`Get.back()` 만)"), "설정 (`Get.back()` 만)")
        self.assertEqual(PF.neutral_label("설정 (`Get.back()`, 가능성 높음)"), "설정 (`Get.back()`)")
        self.assertEqual(PF.blind_labels(["back `pop(a, b)`, as the request reads", "quiz `q()`: risky reading"]),
                         ["back `pop(a, b)`", "quiz `q()`"])


if __name__ == "__main__":
    unittest.main()
