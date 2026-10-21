"""M0d-2 §2: the person's answer from the transcript — measured shapes, forged and replayed answers, turn
and session binding, large and half-written files (m0d2-plan §11.2)."""

import json
import os
import time

import transcripts as TR
from helpers import StudioTestCase
from stdo.guard import transcript as X

LABEL = "승인 3f2a9c0d1e4b"


class Base(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.env = dict(os.environ)
        self.path = TR.transcript_path(self.env)

    def hook(self, t, call="toolu_cmd1", prompt=None, sid="sess-1"):
        return {"session_id": sid, "prompt_id": prompt or t.prompt, "tool_use_id": call,
                "transcript_path": self.path}

    def find(self, t, tail="", **kw):
        t.write(self.path, tail)
        return X.find(self.hook(t, **kw), self.env)

    def code(self, t, label=LABEL, h12="3f2a9c0d1e4b", tail="", **kw):
        try:
            a = self.find(t, tail, **kw)
            X.choose(a, label, h12)
        except X.NoEvidence as e:
            return e.code
        return "ok"


class Measured(Base):
    """The anonymized real excerpts (2.1.304)."""

    def lines_until(self, name, call):
        out = []
        for d in TR.fixture_lines(name):
            out.append(d)
            c = (d.get("message") or {}).get("content")
            if d.get("type") == "assistant" and isinstance(c, list) and any(b.get("id") == call for b in c):
                break
        return out

    def run_fixture(self, name, call, prompt, label, h12=None):
        lines = self.lines_until(name, call)
        sid = lines[0]["sessionId"]
        path = TR.transcript_path(self.env, sid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            for d in lines:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        hook = {"session_id": sid, "prompt_id": prompt, "tool_use_id": call, "transcript_path": path}
        stamp = [d for d in lines if d.get("toolUseResult")][-1]["timestamp"] if any(d.get("toolUseResult") for d in lines) else "2026-10-20T12:30:00Z"
        now = X._epoch(stamp) + 5
        a = X.find(hook, self.env, now=now)
        return a, X.choose(a, label, h12)

    def test_one_question_label(self):
        a, (i, text, note) = self.run_fixture("ask-one", "toolu_01PdQhQk2PG2hXdSwsGiBmeS",
                                              "017d1537-36d1-4f34-a650-a531d920c9bc", "승인 abc123def456")
        self.assertEqual((i, text, a.tool_use_id), (0, "이 결과를 승인할까?", "toolu_016zN3dWZhn45yHQP8z8YHKV"))
        self.assertEqual(a.entrypoint, "cli")

    def test_four_questions_other_is_not_a_label(self):
        call, prompt = "toolu_01FjYp2cMyxcvYC3FoWN87rB", "c5efd994-a5ff-4466-a713-eac0dc317a29"
        a, (i, _t, _n) = self.run_fixture("ask-four-other", call, prompt, "B")
        self.assertEqual(i, 1)  # Q2 = B
        with self.assertRaises(X.NoEvidence) as cm:
            self.run_fixture("ask-four-other", call, prompt, "자유 입력")  # Q3 Other text
        self.assertEqual(cm.exception.code, "label-not-chosen")
        with self.assertRaises(X.NoEvidence) as cm:
            self.run_fixture("ask-four-other", call, prompt, "A")  # Q1 and Q4
        self.assertEqual(cm.exception.code, "ambiguous")

    def test_newer_unpaired_answer_is_not_skipped(self):
        """Review repro A: an older paired answer must not win over a newer answer whose question line is not on
        disk yet."""
        t = TR.approval_turn(TR.T(), LABEL)
        t.lines.pop()  # no current call line (interactive)
        q2 = [TR.question("다시 보여 드릴까요? 3f2a9c0d1e4b", [LABEL, "수정해 줘"])]
        t.answer("toolu_ask2", q2, {q2[0]["question"]: "수정해 줘"})  # its tool_use line is not flushed
        self.assertEqual(self.code(t, call="toolu_late"), "unflushed")
        # any newer unpaired result (whatever its shape) means the transcript is still being written (review MINOR-1)
        t = TR.approval_turn(TR.T(), LABEL)
        t.lines.pop()
        t.tool_result("toolu_unpaired")
        self.assertEqual(self.code(t, call="toolu_late"), "unflushed")
        # an unpaired result OLDER than the answer (same turn) does not matter
        t = TR.T()
        qs = [TR.question("q 3f2a9c0d1e4b", [LABEL])]
        t.user_prompt("x")
        t.tool_result("toolu_old_unpaired")
        t.ask("a1", qs)
        t.answer("a1", qs, {qs[0]["question"]: LABEL})
        self.assertEqual(self.code(t, call="toolu_late"), "ok")

    def test_answer_written_after_the_current_call(self):
        """An answer that reached the transcript only after the current call's line is not its evidence."""
        t = TR.T()
        qs = [TR.question("q 3f2a9c0d1e4b", [LABEL])]
        t.user_prompt("x")
        t.ask("a1", qs)
        t.tool_use("Bash", "toolu_cmd1")
        t.answer("a1", qs, {qs[0]["question"]: LABEL})
        self.assertEqual(self.code(t), "no-question")

    def test_same_message_even_out_of_order(self):
        """The question and the current call in one assistant line are never an answer-then-command, whatever the
        order the lines were flushed in."""
        t = TR.T()
        qs = [TR.question("q 3f2a9c0d1e4b", [LABEL])]
        t.user_prompt("x")
        t.answer("a1", qs, {qs[0]["question"]: LABEL})
        d = t._base("assistant", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "a1", "name": "AskUserQuestion", "input": {"questions": qs}},
            {"type": "tool_use", "id": "toolu_cmd1", "name": "Bash", "input": {"command": "x"}}]})
        t.add(d)
        self.assertEqual(self.code(t), "no-question")

    def test_question_sent_with_other_calls(self):
        """Review MINOR-1: content blocks of one message flushed as separate lines."""
        t = TR.T()
        qs = [TR.question("q 3f2a9c0d1e4b", [LABEL])]
        t.user_prompt("x")
        t.ask("a1", qs)
        mid = t.lines[-1]["message"]["id"]
        t.answer("a1", qs, {qs[0]["question"]: LABEL})
        d = t._base("assistant", message={"id": mid, "role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_sib", "name": "Bash", "input": {"command": "y"}}]})
        t.add(d)
        self.assertEqual(self.code(t, call="toolu_late"), "no-question")

    def test_measured_late_current_call(self):
        """The anonymized U1 transcript: the AskUserQuestion answer is on disk, the Bash call's line is not."""
        lines = TR.fixture_lines("ask-then-bash-late")
        sid = lines[0].get("sessionId") or [d for d in lines if d.get("sessionId")][0]["sessionId"]
        path = TR.transcript_path(self.env, sid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        hook = {"session_id": sid, "prompt_id": "664441d5-ce43-4267-a383-b0f2c69eb2d7",
                "tool_use_id": "toolu_01S6TLSnog4DSeRjvL515tQ3", "transcript_path": path}
        for upto in (11, len(lines)):  # at PreToolUse (through the attachment); with the later request copies too
            with open(path, "w") as f:
                for d in lines[:upto]:
                    f.write(json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n")
            res = [d for d in lines[:upto] if isinstance(d.get("toolUseResult"), dict)][-1]
            a = X.find(hook, self.env, now=X._epoch(res["timestamp"]) + 5)
            i, text, _n = X.choose(a, "승인 c26611707a0e", "c26611707a0e")
            self.assertEqual((i, a.tool_use_id), (0, "toolu_01Y6w5y1X1jC7bmUgaNo2vX5"))

    def test_esc_then_new_turn(self):
        with self.assertRaises(X.NoEvidence) as cm:
            self.run_fixture("ask-esc", "toolu_01QZaz73LgCFxApp8jNmmuQo", "8b7178dc-09fb-4a3d-bd32-f0d63d306350", "예")
        self.assertEqual(cm.exception.code, "no-question")

    def test_builder_matches_measured_keys(self):
        real = TR.fixture_lines("ask-one")
        r_res = [d for d in real if isinstance(d.get("toolUseResult"), dict) and "answers" in d["toolUseResult"]][0]
        t = TR.approval_turn(TR.T(), LABEL)
        b_res = [d for d in t.lines if isinstance(d.get("toolUseResult"), dict) and "answers" in d["toolUseResult"]][0]
        need = {"parentUuid", "isSidechain", "promptId", "type", "message", "uuid", "timestamp", "toolUseResult",
                "sourceToolAssistantUUID", "permissionDecision", "sessionId", "entrypoint", "version", "userType", "cwd"}
        self.assertTrue(need <= set(r_res), sorted(need - set(r_res)))
        self.assertTrue(need <= set(b_res), sorted(need - set(b_res)))
        self.assertEqual(set(r_res["toolUseResult"]), set(b_res["toolUseResult"]))
        self.assertEqual(set(r_res["permissionDecision"]), set(b_res["permissionDecision"]))
        r_esc = [d for d in TR.fixture_lines("ask-esc") if d.get("toolUseResult") == "User rejected tool use"]
        self.assertTrue(r_esc)
        b = TR.T()
        b.user_prompt("x")
        b.ask("a", [TR.question("q", ["예"])])
        b.cancel("a")
        self.assertEqual(b.lines[-1]["toolUseResult"], r_esc[0]["toolUseResult"])
        self.assertIn("toolDenialKind", r_esc[0])


class Evidence(Base):
    def test_label_chosen(self):
        t = TR.approval_turn(TR.T(), LABEL)
        a = self.find(t)
        self.assertEqual(X.choose(a, LABEL, "3f2a9c0d1e4b")[0], 0)

    def test_other_answers(self):
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, chosen="수정해 줘")), "label-not-chosen")
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, chosen="승인 3f2a9c0d1e4b ")), "label-not-chosen")
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, chosen="승인 000000000000")), "label-not-chosen")
        # an "Other" text equal to a label that is not among the options
        t = TR.T()
        qs = [TR.question("승인할까요? 3f2a9c0d1e4b", ["예", "아니오"])]
        t.user_prompt("x")
        t.ask("a1", qs)
        t.answer("a1", qs, {qs[0]["question"]: LABEL})
        t.tool_use("Bash", "toolu_cmd1")
        self.assertEqual(self.code(t), "label-not-chosen")

    def test_hash_must_show_in_the_question(self):
        t = TR.approval_turn(TR.T(), LABEL, qtext="이 결과를 승인할까요?")
        self.assertEqual(self.code(t), "hash-not-shown")

    def test_esc_same_turn(self):
        t = TR.T()
        qs = [TR.question("q 3f2a9c0d1e4b", [LABEL])]
        t.user_prompt("x")
        t.ask("a1", qs)
        t.cancel("a1")
        t.tool_use("Bash", "toolu_cmd1")
        self.assertEqual(self.code(t), "cancelled")

    def test_error_result_with_answers_is_not_an_answer(self):
        t = TR.approval_turn(TR.T(), LABEL)
        t.lines[-2]["message"]["content"][0]["is_error"] = True
        self.assertEqual(self.code(t), "cancelled")

    def test_permission_decision(self):
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, source="hook")), "not-a-person")
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, source="config")), "not-a-person")
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, decision="reject")), "not-a-person")
        # absent: not the person's mark (M0f U1–U8: every human answer carried it; Q8 closed)
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, permission=False)), "not-a-person")
        t = TR.approval_turn(TR.T(), LABEL, permission=False, entrypoint="sdk-cli")
        self.assertEqual(self.code(t), "non-interactive")
        # what U8 measured for hook-filled answers (PreToolUse / PermissionRequest updatedInput)
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, source="hook")), "not-a-person")
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, source="user_temporary")), "ok")
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, source="user_permanent")), "ok")

    def test_non_interactive(self):
        self.assertEqual(self.code(TR.approval_turn(TR.T(entrypoint="sdk-cli"), LABEL)), "non-interactive")
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, entrypoint="sdk-ts")), "non-interactive")

    def test_turn_binding(self):
        t = TR.approval_turn(TR.T(), LABEL)
        call = t.lines.pop()  # the person says something after answering, then the command
        t.user_prompt("잠깐, 다시 보자")
        t.add(call)
        self.assertEqual(self.code(t), "no-question")
        # the hook's prompt id is another turn's
        t2 = TR.approval_turn(TR.T(), LABEL)
        self.assertEqual(self.code(t2, prompt="another-prompt"), "no-question")
        # no prompt id at all
        t3 = TR.approval_turn(TR.T(), LABEL)
        t3.write(self.path)
        h = self.hook(t3)
        h.pop("prompt_id")
        with self.assertRaises(X.NoEvidence) as cm:
            X.find(h, self.env)
        self.assertEqual(cm.exception.code, "no-turn")

    def test_compacted(self):
        t = TR.approval_turn(TR.T(), LABEL)
        call = t.lines.pop()
        t.compact()
        t.add(call)
        self.assertEqual(self.code(t), "other-turn")

    def test_other_session_and_sidechain(self):
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, session_id="sess-2")), "other-session")
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, sidechain=True)), "sidechain")

    def test_newer_question_wins(self):
        t = TR.T()
        q1 = [TR.question("첫 질문 3f2a9c0d1e4b", [LABEL, "거부"])]
        q2 = [TR.question("둘째 질문 3f2a9c0d1e4b", [LABEL, "거부"])]
        t.user_prompt("x")
        t.ask("a1", q1)
        t.answer("a1", q1, {q1[0]["question"]: LABEL})
        t.ask("a2", q2)
        t.answer("a2", q2, {q2[0]["question"]: "거부"})
        t.tool_use("Bash", "toolu_cmd1")
        self.assertEqual(self.code(t), "label-not-chosen")
        # other tool calls between the answer and the command are fine (state.py next …)
        t = TR.approval_turn(TR.T(), LABEL)
        call = t.lines.pop()
        t.tool_use("Bash", "toolu_mid", {"command": "state.py next v"})
        t.tool_result("toolu_mid")
        t.add(call)
        self.assertEqual(self.code(t), "ok")

    def test_parallel_call_has_no_answer_yet(self):
        t = TR.T()
        qs = [TR.question("q 3f2a9c0d1e4b", [LABEL])]
        t.user_prompt("x")
        d = t._base("assistant", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "a1", "name": "AskUserQuestion", "input": {"questions": qs}},
            {"type": "tool_use", "id": "toolu_cmd1", "name": "Bash", "input": {"command": "x"}}]})
        t.add(d)
        self.assertEqual(self.code(t), "no-question")

    def test_duplicates_multiselect_and_changed_questions(self):
        t = TR.T()
        qs = [TR.question("같은 질문 3f2a9c0d1e4b", [LABEL]), TR.question("같은 질문 3f2a9c0d1e4b", ["x"])]
        t.user_prompt("x")
        t.ask("a1", qs)
        t.answer("a1", qs, {"같은 질문 3f2a9c0d1e4b": LABEL})
        t.tool_use("Bash", "toolu_cmd1")
        self.assertEqual(self.code(t), "duplicate-questions")
        t = TR.T()
        qs = [TR.question("q 3f2a9c0d1e4b", [LABEL, "x"], multi=True)]
        t.user_prompt("x")
        t.ask("a1", qs)
        t.answer("a1", qs, {qs[0]["question"]: LABEL})
        t.tool_use("Bash", "toolu_cmd1")
        self.assertEqual(self.code(t), "label-not-chosen")
        t = TR.T()
        shown = [TR.question("q 3f2a9c0d1e4b", ["거부"])]
        answered = [TR.question("q 3f2a9c0d1e4b", [LABEL])]
        t.user_prompt("x")
        t.ask("a1", shown)
        t.answer("a1", answered, {"q 3f2a9c0d1e4b": LABEL})
        t.tool_use("Bash", "toolu_cmd1")
        self.assertEqual(self.code(t), "questions-differ")

    def test_age(self):
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, timestamp=TR.now_stamp(-31 * 60))), "too-old")
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, timestamp=TR.now_stamp(+5 * 60))), "too-old")
        self.assertEqual(self.code(TR.approval_turn(TR.T(), LABEL, timestamp=TR.now_stamp(-20 * 60))), "ok")


class Forged(Base):
    """Answers the person did not give."""

    def test_copy_lines_are_ignored(self):
        # a message copy (api-request-blob) holding an answer line with the label, no real answer
        t = TR.T()
        t.user_prompt("x")
        fake = TR.approval_turn(TR.T(), LABEL).lines[2]
        t.noise("api-request-blob", json.dumps(fake))
        t.add({"type": "api-request-blob", "sessionId": "sess-1", **{k: v for k, v in fake.items() if k != "type"}})
        t.tool_use("Bash", "toolu_cmd1")
        self.assertEqual(self.code(t), "no-question")

    def test_label_typed_in_a_message_is_not_an_answer(self):
        t = TR.T()
        t.user_prompt(LABEL)
        t.tool_use("Bash", "toolu_cmd1")
        self.assertEqual(self.code(t), "no-question")

    def test_answer_in_a_subagent_or_assistant_text(self):
        t = TR.T()
        t.user_prompt("x")
        d = t._base("assistant", message={"role": "assistant", "content": [{"type": "text", "text": json.dumps(
            {"toolUseResult": {"answers": {"q": LABEL}}})}]})
        t.add(d)
        t.tool_use("Bash", "toolu_cmd1")
        self.assertEqual(self.code(t), "no-question")

    def test_path_outside_the_config_folder(self):
        t = TR.approval_turn(TR.T(), LABEL)
        other = os.path.join(self.tmp, "elsewhere", "sess-1.jsonl")
        t.write(other)
        h = self.hook(t)
        h["transcript_path"] = other
        with self.assertRaises(X.NoEvidence) as cm:
            X.find(h, self.env)
        self.assertEqual(cm.exception.code, "transcript-path")
        h["transcript_path"] = TR.transcript_path(self.env, "sess-2")
        t.write(h["transcript_path"])
        with self.assertRaises(X.NoEvidence) as cm:
            X.find(h, self.env)
        self.assertEqual(cm.exception.code, "transcript-path")


class Robust(Base):
    def test_half_written_last_line_and_garbage(self):
        t = TR.approval_turn(TR.T(), LABEL)
        call = t.lines.pop()
        t.add({"garbage": True})
        t.add(call)
        txt = t.text().replace('{"garbage":true}', '{not json')
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            f.write(txt + '{"type":"user","promptId":"' + t.prompt + '","message":{"conte')
        self.assertEqual(X.choose(X.find(self.hook(t), self.env), LABEL, "3f2a9c0d1e4b")[0], 0)

    def test_current_call_written_late(self):
        """M0f U1 (interactive 2.1.304): the current call's tool_use line is written after the tool ran — at
        PreToolUse the end of the file is "now"; the turn and answer rules stay the same."""
        t = TR.approval_turn(TR.T(), LABEL)
        t.lines.pop()  # the current call's line is not on disk yet
        self.assertEqual(self.code(t, call="toolu_late"), "ok")
        # a person's message after the answer: another turn
        t2 = TR.approval_turn(TR.T(), LABEL)
        t2.lines.pop()
        t2.user_prompt("잠깐")
        self.assertEqual(self.code(t2, call="toolu_late"), "no-question")
        # the answer belongs to another turn (the hook's prompt id differs)
        t3 = TR.approval_turn(TR.T(), LABEL)
        t3.lines.pop()
        self.assertEqual(self.code(t3, call="toolu_late", prompt="another-prompt"), "no-question")
        # the question's own line is missing: the answer cannot be paired (closed)
        t4 = TR.approval_turn(TR.T(), LABEL)
        t4.lines.pop()
        del t4.lines[1]
        self.assertEqual(self.code(t4, call="toolu_late"), "unflushed")
        # results written after the current call (when it is present) are not its evidence
        t5 = TR.T()
        qs = [TR.question("q 3f2a9c0d1e4b", [LABEL])]
        t5.user_prompt("x")
        d = t5._base("assistant", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "a1", "name": "AskUserQuestion", "input": {"questions": qs}},
            {"type": "tool_use", "id": "toolu_cmd1", "name": "Bash", "input": {"command": "x"}}]})
        t5.add(d)
        t5.answer("a1", qs, {qs[0]["question"]: LABEL})
        self.assertEqual(self.code(t5), "no-question")

    def test_large_copy_lines_between_answer_and_command(self):
        """v2 MINOR 2: 4 × 4 MB copy lines between the answer and the command are skipped unparsed."""
        t = TR.approval_turn(TR.T(), LABEL)
        call = t.lines.pop()
        big = "x" * (4 * 1024 * 1024)
        for _ in range(4):
            t.noise("api-request-blob", big)
        t.add(call)
        t.write(self.path)
        X.STATS.parsed = 0
        start = time.monotonic()
        a = X.find(self.hook(t), self.env)
        took = time.monotonic() - start
        self.assertEqual(X.choose(a, LABEL, "3f2a9c0d1e4b")[0], 0)
        self.assertLess(X.STATS.parsed, 10)
        self.assertLess(took, 1.5)
        print("\n[perf] transcript with 16 MB of copies between answer and command: %.0f ms" % (took * 1000))

    def test_answer_too_far_back(self):
        t = TR.approval_turn(TR.T(), LABEL)
        call = t.lines.pop()
        for i in range(3):
            t.tool_use("Bash", "toolu_m%d" % i)
            t.tool_result("toolu_m%d" % i, "y" * (4 * 1024 * 1024))
        t.add(call)
        old = X.MAX_BYTES
        X.MAX_BYTES = 8 * 1024 * 1024
        try:
            self.assertEqual(self.code(t), "transcript-too-large")
        finally:
            X.MAX_BYTES = old

    def test_big_file_answer_near_end(self):
        t = TR.T()
        for i in range(200):
            t.user_prompt("old %d" % i)
            t.tool_use("Bash", "toolu_o%d" % i)
            t.tool_result("toolu_o%d" % i, "z" * 200000)
        TR.approval_turn(t, LABEL)
        t.write(self.path)
        self.assertGreater(os.path.getsize(self.path), 40 * 1024 * 1024)
        start = time.monotonic()
        a = X.find(self.hook(t), self.env)
        took = time.monotonic() - start
        self.assertEqual(X.choose(a, LABEL, "3f2a9c0d1e4b")[0], 0)
        self.assertLess(took, 0.3)
        print("\n[perf] 40 MB transcript, answer near the end: %.1f ms" % (took * 1000))
