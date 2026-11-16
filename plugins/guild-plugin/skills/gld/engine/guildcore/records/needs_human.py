"""guildcore.records.needs_human — the `<!-- guild:needs-human -->` pause comment.

Shape (H§H "Name the cause", H§M, C §5.5): line 1 the marker; line 2 the cause line at column 0
— `defect: …` / `ambiguity: …` / `env: <ci-blocked|base-red|credential|service|other> — …`;
line 3 optionally a habit stop's directive line (`사람 지시 확인: …` / `적용 가능한 사람 지시: …`);
then prose. The engine adds the `guild-answer:` guidance AFTER those lines (C13 — daily reads
lines 1–2 only, so it is unaffected). One comment per pause, never PATCHed.
"""

import re

from guildcore.records import markers

NAME = "needs-human"
ENV_KEYS = ("ci-blocked", "base-red", "credential", "service", "other")
# H§H's self-check grep: `grep -nE -m1 '^(defect: |ambiguity: |env: (…) — )'` must print `2:`.
CAUSE_CHECK_RE = re.compile(r"^(defect: |ambiguity: |env: (ci-blocked|base-red|credential|service|other) — )")
# daily.md step 3's looser jq: `test("^(defect|ambiguity|env):")`.
DAILY_CAUSE_RE = re.compile(r"^(defect|ambiguity|env):")
DIRECTIVE_PREFIXES = ("사람 지시 확인:", "적용 가능한 사람 지시:")
ANSWER_HINT_T = ("답하려면 이 이슈에 'guild-answer: D{k} <token>' 한 줄을 남기고 "
                 "guild:needs-human 라벨을 떼세요 (선택지: {options})")


class Pause(object):
    def __init__(self, body, comment_id=None, created_at=None):
        self.body = body
        self.comment_id = comment_id
        self.created_at = created_at
        lines = [markers.clean(x) for x in body.split("\n")]
        self.lines = lines
        self.cause_line = lines[1] if len(lines) > 1 and CAUSE_CHECK_RE.match(lines[1]) else None
        self.cause_kind = None
        self.env_key = None
        if self.cause_line:
            self.cause_kind = self.cause_line.split(":", 1)[0]
            if self.cause_kind == "env":
                self.env_key = self.cause_line[len("env: "):].split(" ", 1)[0]
        self.directive_line = None
        if len(lines) > 2 and lines[2].startswith(DIRECTIVE_PREFIXES):
            self.directive_line = lines[2]

    def render(self):
        return self.body

    def cause_check_ok(self):
        """The H§H grep: first matching line is line 2."""
        for i, ln in enumerate(self.lines, 1):
            if CAUSE_CHECK_RE.match(ln):
                return i == 2
        return False

    def daily_cause(self):
        """sprint/daily.md step 3's jq, as code: first `^(defect|ambiguity|env):` line anywhere,
        else first `^## ` heading, else `(원인 줄 없음)`."""
        for ln in self.body.split("\n"):
            if DAILY_CAUSE_RE.search(ln):
                return ln
        for ln in self.body.split("\n"):
            if ln.startswith("## "):
                return ln
        return "(원인 줄 없음)"


def from_comments(comments):
    """Every pause comment, in id order (the last one is the latest pause — daily step 3)."""
    out = []
    for c in sorted(markers.containing(comments, NAME), key=lambda c: c.get("id") or 0):
        out.append(Pause(markers.body_of(c), c.get("id"), c.get("created_at")))
    return out


def cause_line(kind, text, env_key=None):
    text = " ".join((text or "").split())
    if kind == "env":
        if env_key not in ENV_KEYS:
            raise ValueError("env key must be one of %s" % (ENV_KEYS,))
        return "env: %s — %s" % (env_key, text)
    if kind not in ("defect", "ambiguity"):
        raise ValueError("cause kind must be defect|ambiguity|env")
    return "%s: %s" % (kind, text)


def answer_hint(k, options):
    return ANSWER_HINT_T.format(k=k, options=" | ".join(options))


def render(cause, prose="", directive_line=None, answer=None):
    """`cause` = a rendered cause line; `answer` = (decision number, [tokens]) or None.
    Redaction is the last step (INV5) and runs over everything below the marker."""
    lines = [cause]
    if directive_line:
        lines.append(directive_line)
    if answer:
        lines.append(answer_hint(answer[0], answer[1]))
    if prose:
        lines.append("")
        lines.append(prose.rstrip("\n"))
    out = markers.open_tag(NAME) + "\n" + markers.finish("\n".join(lines))
    if not Pause(out).cause_check_ok():
        raise ValueError("rendered pause fails the cause-line check")
    return markers.assert_own_markers(out, NAME)
