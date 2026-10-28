"""A person's answer from the Claude Code transcript (m0d2-plan §2). Read only; no child processes.

Measured shape (Claude Code 2.1.304, m0-measure B and m0d2-plan §2.1): the AskUserQuestion result is a
`user` line with `promptId`, `entrypoint`, `permissionDecision {decision, source}` and
`toolUseResult {questions, answers, annotations}`; the current call's `tool_use` line is already in the
file at its PreToolUse. The guard reads backwards from that line to the start of the current user turn
(the first `user` line with another `promptId`), pairs results with their `tool_use` lines and takes the
nearest AskUserQuestion result. Anything that does not have the expected shape is no evidence (closed)."""

import calendar
import collections
import json
import os
import time

MAX_BYTES = 128 * 1024 * 1024
WALL = 1.5
BLOCK = 64 * 1024
HEAD = 400
AGE = 30 * 60
SKEW = 60
INTERACTIVE = frozenset(["cli"])
ASK = "AskUserQuestion"

# reasons -> the sentence the deny message uses
REASONS = {
    "no-transcript": "the session's transcript is not available",
    "transcript-path": "the transcript is not where Claude Code keeps this session's transcript",
    "transcript-too-large": "the transcript between the answer and this command is too large to check — ask again",
    "current-call-not-found": "this command is not in the transcript yet (the transcript format was not recognized)",
    "no-turn": "the session gave no prompt id for this turn",
    "no-question": "no AskUserQuestion was answered in this turn",
    "other-turn": "the answer is from an earlier turn (the person said something since) — ask again",
    "other-session": "the answer is from another session",
    "sidechain": "the answer is from a subagent",
    "non-interactive": "the answer did not come from a person at an interactive session (claude -p or a program)",
    "not-a-person": ("the answer is not marked as the person's (permissionDecision source user_*) — the person "
                     "answers in the default permission mode, with no allow rule for AskUserQuestion"),
    "cancelled": "the question was cancelled",
    "format": "the answer's format was not recognized",
    "questions-differ": "the questions shown differ from the questions answered",
    "duplicate-questions": "two questions in that AskUserQuestion have the same text",
    "too-old": "the answer is too old (or from the future) — ask again",
    "label-not-chosen": "the person did not choose that option",
    "ambiguous": "more than one question was answered with that option",
    "hash-not-shown": "the question text does not show the hash of the option",
    "video-not-shown": "the question text does not show the video as [<video>] (brackets included)",
    "consumed": "this answer was used already — ask again",
    "record-unreadable": "the repository's record of used answers cannot be read, so the answer cannot be checked "
                         "(tell the user)",
    "unflushed": "the latest answer's question is not in the transcript yet — ask again",
    "summary-not-shown": "the question does not show the commit's summary line as --stage printed it",
    "values-not-shown": "the question does not show every line of the value block as --stage printed it (the "
                        "protected values, or the overflow file and its counts)",
    "gate-lines-not-shown": "the question does not show every line the gate needs (for ①: each commit to the source "
                            "after begin, as record-source printed it)",
}


class NoEvidence(Exception):
    def __init__(self, code, detail=""):
        Exception.__init__(self, code)
        self.code = code
        self.detail = detail

    def sentence(self):
        s = REASONS.get(self.code, self.code)
        return s + (" (%s)" % self.detail if self.detail else "")


class Answer(object):
    def __init__(self, tool_use_id, questions, answers, annotations, line):
        self.tool_use_id = tool_use_id
        self.questions = questions
        self.answers = answers
        self.annotations = annotations
        self.prompt_id = line.get("promptId")
        self.timestamp = line.get("timestamp")
        self.entrypoint = line.get("entrypoint")
        self.version = line.get("version")


class Stats(object):
    def __init__(self):
        self.bytes = 0
        self.lines = 0
        self.parsed = 0
        self.opened = 0


STATS = Stats()  # tests count how often a transcript is opened


def config_dir(env):
    return env.get("CLAUDE_CONFIG_DIR") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".claude")


def check_path(path, session_id, env):
    if not isinstance(path, str) or not path or not os.path.isabs(path):
        raise NoEvidence("no-transcript")
    if not session_id or os.path.basename(path) != session_id + ".jsonl":
        raise NoEvidence("transcript-path")
    projects = os.path.realpath(os.path.join(config_dir(env), "projects"))
    real = os.path.realpath(path)
    rel = os.path.relpath(real, projects)
    if rel.startswith("..") or rel.count(os.sep) != 1:
        raise NoEvidence("transcript-path")
    return real


def _reverse_lines(f, size, deadline):
    """Complete lines from the end (a last line without its newline is still being written: dropped)."""
    pos = size
    pending = collections.deque()
    drop = True  # the segment after the last newline
    read = 0
    while pos > 0:
        if time.monotonic() > deadline:
            raise NoEvidence("transcript-too-large")
        n = min(BLOCK, pos)
        pos -= n
        f.seek(pos)
        chunk = f.read(n)
        read += n
        STATS.bytes += n
        if read > MAX_BYTES:
            raise NoEvidence("transcript-too-large")
        while True:
            i = chunk.rfind(b"\n")
            if i < 0:
                pending.appendleft(chunk)
                break
            line = chunk[i + 1:] + b"".join(pending)
            pending.clear()
            chunk = chunk[:i]
            if drop:
                drop = False
                continue
            if line:
                yield line
    if not drop:
        line = b"".join(pending)
        if line:
            yield line


def _kind(line):
    """user | assistant | system | maybe (a parentUuid line that may be an assistant line) | None (skip)."""
    h = line[:HEAD]
    if h.startswith(b'{"type":"'):
        end = h.find(b'"', 9)
        t = h[9:end] if end > 0 else b""
        if t in (b"user", b"assistant", b"system"):
            return t.decode()
        return None  # api-request-blob, attachment, mode, … (copies of messages live here)
    if b'"attachment":' in h and b'"message":' not in h:
        return None
    if b'"type":"system"' in h:
        return "system"
    if b'"type":"user"' in h:
        return "user"
    return "maybe"


def _parse(line):
    STATS.parsed += 1
    try:
        d = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return d if isinstance(d, dict) else None


def _content(d):
    m = d.get("message")
    c = m.get("content") if isinstance(m, dict) else None
    return c if isinstance(c, list) else []


def _epoch(stamp):
    if not isinstance(stamp, str) or len(stamp) < 19:
        return None
    try:
        return calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def _norm_questions(qs):
    if not isinstance(qs, list) or not qs:
        return None
    out = []
    for q in qs:
        if not isinstance(q, dict) or not isinstance(q.get("question"), str) or not isinstance(q.get("options"), list):
            return None
        labels = []
        for o in q["options"]:
            if not isinstance(o, dict) or not isinstance(o.get("label"), str):
                return None
            labels.append(o["label"])
        out.append((q["question"], tuple(labels), bool(q.get("multiSelect"))))
    return out


def find(hook, env, now=None):
    """The nearest answered AskUserQuestion of this turn (an Answer), or NoEvidence."""
    session_id = hook.get("session_id")
    prompt_id = hook.get("prompt_id")
    cur = hook.get("tool_use_id")
    path = check_path(hook.get("transcript_path"), session_id, env)
    if not prompt_id:
        raise NoEvidence("no-turn")
    if not isinstance(cur, str) or not cur:
        raise NoEvidence("current-call-not-found")
    now = time.time() if now is None else now
    deadline = time.monotonic() + WALL
    cur_b = json.dumps(cur).encode("utf-8")
    STATS.opened += 1
    try:
        f = open(path, "rb")
    except OSError:
        raise NoEvidence("no-transcript")
    with f:
        size = os.fstat(f.fileno()).st_size
        # The current call's tool_use line is usually already written at PreToolUse (measured in -p and the M0d-0
        # session), but in an interactive 2.1.304 session it was written only after the tool ran (M0f U1). So the
        # scan starts at the end of the file as "now"; when the current call's line is met, whatever came after it
        # is dropped (nothing after the current call can be its evidence).
        found = False
        results = []  # (order, tool_use_id, item, line) nearest first
        uses = {}  # tool_use_id -> (name, input, ids of the same assistant line, message id)
        msgs = []  # (order, message id) of assistant lines
        boundary = None
        chosen = None
        order = 0
        limited = None
        try:
            for raw in _reverse_lines(f, size, deadline):
                order += 1
                STATS.lines += 1
                k = _kind(raw)
                if k is None:
                    continue
                if k == "system":
                    if boundary is None and b"compact_boundary" in raw:
                        boundary = order
                    continue
                if k == "maybe" and b'"tool_use"' not in raw and b'"tool_result"' not in raw and \
                        b'"promptId"' not in raw:
                    continue
                d = _parse(raw)
                if d is None:
                    continue
                t = d.get("type")
                if t == "user":
                    if d.get("promptId") != prompt_id:
                        break  # the start of this turn
                    for b in _content(d):
                        if isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str):
                            results.append((order, b["tool_use_id"], b, d))
                elif t == "assistant":
                    ids = [b["id"] for b in _content(d) if isinstance(b, dict) and b.get("type") == "tool_use"
                           and isinstance(b.get("id"), str)]
                    m = d.get("message")
                    mid = m.get("id") if isinstance(m, dict) else None
                    msgs.append((order, mid))
                    for b in _content(d):
                        if isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("id"), str):
                            uses[b["id"]] = (b.get("name"), b.get("input"), ids, mid)
                    if cur in ids and not found:
                        found = True
                        # anything after the current call (written later) is not evidence for it
                        results = [r for r in results if r[0] > order]
                        boundary = boundary if boundary is not None and boundary > order else None
                        continue
                    chosen = _nearest(results, uses)
                    if chosen is not None:
                        break
        except NoEvidence as e:
            limited = e
        if chosen is None:
            chosen = _nearest(results, uses, final=limited is None)
        if chosen is None:
            if limited is not None:
                raise limited
            raise NoEvidence("no-question")
        if cur in uses[chosen[1]][2]:
            raise NoEvidence("no-question", "the question and this command were in the same message")
        # content blocks of one message flushed as separate lines: a later line of the question's own message means
        # the question was asked together with other calls (parallel) — not an answer before this command
        ask_mid = uses[chosen[1]][3]
        if ask_mid and any(o < chosen[0] and m == ask_mid for o, m in msgs):
            raise NoEvidence("no-question", "the question was sent together with other calls")
    order_, tuid, item, line = chosen
    if boundary is not None and boundary < order_:
        raise NoEvidence("other-turn", "the conversation was compacted")
    return _validate(tuid, item, line, uses[tuid][1], session_id, now)


ASK_TEXTS = ("Your questions have been answered", "The user answered")


def _ask_like(r):
    """A result that looks like an AskUserQuestion answer even without its tool_use line."""
    item, line = r[2], r[3]
    tur = line.get("toolUseResult")
    if isinstance(tur, dict) and isinstance(tur.get("questions"), list) and isinstance(tur.get("answers"), dict):
        return True
    c = item.get("content")
    text = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c if isinstance(x, dict)) \
        if isinstance(c, list) else ""
    return text.lstrip().startswith(ASK_TEXTS)


def _nearest(results, uses, final=False):
    """The nearest result whose tool_use is AskUserQuestion; None while a nearer result is still unpaired.
    `final` (the turn was read to its start): an unpaired result is skipped — unless it looks like an answer to a
    question, which then is the nearest answer and cannot be checked (closed: "unflushed")."""
    for r in results:
        u = uses.get(r[1])
        if u is None:
            if final:
                # a newer result whose call is not on disk yet (whatever it is): the transcript is still being
                # written around the answer — closed (the current call has no result yet, so it never counts here)
                raise NoEvidence("unflushed")
            return None
        if u[0] == ASK:
            return r
    return None


def _validate(tuid, item, line, ask_input, session_id, now):
    if line.get("sessionId") != session_id:
        raise NoEvidence("other-session")
    if line.get("isSidechain") is not False:
        raise NoEvidence("sidechain")
    if item.get("is_error") is True:
        raise NoEvidence("cancelled")
    tur = line.get("toolUseResult")
    if not isinstance(tur, dict):
        raise NoEvidence("cancelled" if isinstance(tur, str) or tur is None else "format")
    if line.get("entrypoint") not in INTERACTIVE:
        raise NoEvidence("non-interactive", "entrypoint %s" % line.get("entrypoint"))
    # the person's mark (M0f U1–U8, 2.1.304): every human answer in default, auto and acceptEdits carried
    # {decision: accept, source: user_temporary}; answers filled by a hook (PreToolUse or PermissionRequest
    # updatedInput) carried source "hook". An answer without the mark is not evidence (m0f-plan Q8, closed).
    pd = line.get("permissionDecision")
    if not isinstance(pd, dict) or pd.get("decision") != "accept" or \
            not str(pd.get("source") or "").startswith("user_"):
        raise NoEvidence("not-a-person")
    answers = tur.get("answers")
    if not isinstance(answers, dict) or not answers:
        raise NoEvidence("format")
    shown = _norm_questions((ask_input or {}).get("questions") if isinstance(ask_input, dict) else None)
    answered = _norm_questions(tur.get("questions"))
    if shown is None or answered is None:
        raise NoEvidence("format")
    if shown != answered:
        raise NoEvidence("questions-differ")
    texts = [q[0] for q in answered]
    if len(set(texts)) != len(texts):
        raise NoEvidence("duplicate-questions")
    t = _epoch(line.get("timestamp"))
    if t is None or now - t > AGE or t - now > SKEW:
        raise NoEvidence("too-old")
    ann = tur.get("annotations")
    return Answer(tuid, answered, answers, ann if isinstance(ann, dict) else {}, line)


def choose(answer, label, hash12=None, video=None):
    """(question index, question text, note) of the one question answered with exactly `label`, which must be
    one of that question's options (an "Other" text cannot be told from a label — only option labels count).
    A video's question shows the video literally as `[<video>]` (m1-plan §3.2): the brackets are part of the match,
    so `[v1]` never stands for `v10`."""
    hits = []
    for i, (text, labels, multi) in enumerate(answer.questions):
        if answer.answers.get(text) == label and label in labels and not multi:
            hits.append((i, text))
    if not hits:
        raise NoEvidence("label-not-chosen")
    if len(hits) > 1:
        raise NoEvidence("ambiguous")
    i, text = hits[0]
    if hash12 and hash12 not in text:
        raise NoEvidence("hash-not-shown")
    if video is not None and "[%s]" % video not in text:
        raise NoEvidence("video-not-shown")
    note = answer.annotations.get(text)
    if isinstance(note, dict):
        note = note.get("notes")
    return i, text, note if isinstance(note, str) and note else None
