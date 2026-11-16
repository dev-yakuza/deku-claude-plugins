"""workflows.status.render — fixed strings of the status/resume/board output.

status/resume strings are the ones status.md and resume.md print today (English skeleton, the
C-F-18 rows in Korean as §2.10 specifies them). The board follows `config.language` (`ko`
default text is monitoring.md's own section names; `en` is the fallback for any other language).
ASCII tokens (labels, markers, stage names, counts) are never localized (H§K).
"""

STAGE_RENDER = {
    "analyze": "analyze", "design": "design", "execute": "execute", "test": "test", "qa": "qa",
    "children": "orchestrating (split parent)", "done": "done",
}
NOT_STARTED = "not started"
HARNESS_NONE = "harness remediation — not started"
SPRINT = "sprint (tracking Issue)"
PAUSED_LINE = "⏸ PAUSED — needs a human decision (see the <!-- guild:needs-human --> comment)"
ROWS = (("Analyze", "analyze", "analyze"), ("Design", "design", "design"),
        ("Execute", "evidence", "execute"), ("Test", "test", "test"), ("QA", "qa", "qa"))
DONE_DECIDED = "결정대로 닫힘 — 해당 없음"
DONE_HUMAN_MERGE = "사람 머지 — 기록 없음"
DONE_LABEL_ONLY = "기록 없음(라벨만 done)"
SUPERSEDED = "superseded (퇴역 대기)"

ROUTE = {
    "not_issue": "#{n} is not an Issue",
    "uninitialized": "Guild not initialized (run `/gld init`).",
    "done": "Issue #{n} is already done.",
    "sprint": "FAIL: #{n} is a sprint tracking Issue — use /gld sprint daily",
    "children": "Split parent mid-orchestration — hand off to /gld dev {n} (child orchestration, Phase 2b)",
    "spine": "Resume at {stage} — hand off to /gld dev {n}",
    "harness": "Harness remediation not started — hand off to /gld dev {n} to start it fresh",
    "none": "Nothing to resume — no guild:* stage label; start fresh with /gld dev {n}",
}

BOARD = {
    "ko": {
        "title": "Guild 모니터링 스냅샷",
        "focus": "포커스: {section}",
        "org": "조직 ③", "knowledge": "지식 ⑥ / 기억 ④", "evolution": "진화 이력 ⑤",
        "gates": "게이트", "standards": "표준 ②", "work": "활성 작업",
        "none": "없음",
        "paused": "{k}개 이슈 사람 대기 중",
        "sprint": "활성 스프린트 {k}건 ({nums}) — /gld sprint daily",
        "roles": "역할 {k}개 설치", "boilerplate": "기본 문구 그대로: {names}",
        "slices": "지식 색인 {k}줄", "gt": "기억 {k}건 (ground-truth.jsonl)",
        "findings": "열린 위반 {k}건", "enabled": "게이트 {state}", "on": "켜짐", "off": "꺼짐",
        "dismissed": "수용된 위험 {k}건",
        "std": "draft {d} · confirmed {c}",
        "bucket": "{stage} {k}",
        "snapshot": "읽은 시각 {ts} 기준 스냅샷 — 실시간 아님",
        "invalid": "알 수 없는 섹션 '{s}' — org|knowledge|gates|work|evolution|standards 중 하나. 전체 스냅샷을 보여 줍니다.",
    },
    "en": {
        "title": "Guild monitoring snapshot",
        "focus": "Focus: {section}",
        "org": "Organization ③", "knowledge": "Knowledge ⑥ / Memory ④", "evolution": "Evolution ⑤",
        "gates": "Gates", "standards": "Standards ②", "work": "Active work",
        "none": "none",
        "paused": "{k} Issue(s) waiting on a human",
        "sprint": "{k} active sprint(s) ({nums}) — /gld sprint daily",
        "roles": "{k} roles installed", "boilerplate": "still day-1 boilerplate: {names}",
        "slices": "{k} knowledge index lines", "gt": "{k} memory entries (ground-truth.jsonl)",
        "findings": "{k} open violation(s)", "enabled": "gates {state}", "on": "on", "off": "off",
        "dismissed": "{k} accepted risk(s)",
        "std": "draft {d} · confirmed {c}",
        "bucket": "{stage} {k}",
        "snapshot": "Snapshot at {ts} — not live",
        "invalid": "unknown section '{s}' — one of org|knowledge|gates|work|evolution|standards. Showing the full snapshot.",
    },
}
SECTIONS = ("org", "knowledge", "gates", "work", "evolution", "standards")


def board_text(language):
    return BOARD.get(language) or BOARD["en"]


def checkbox(done):
    return "- [x] " if done else "- [ ] "
