"""Claude Code transcripts in the measured shape (2.1.304, m0-measure B; m0d2-plan §2.1) for the guard's
evidence tests. `tests/fixtures/claude-code/2.1.304/ask-*.jsonl` are anonymized real excerpts; a test checks
that the lines built here carry the same keys."""

import datetime
import json
import os
import uuid

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "claude-code", "2.1.304")
VERSION = "2.1.304"


def now_stamp(delta=0):
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=delta)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (t.microsecond // 1000)


def question(text, labels, header="Gate", multi=False):
    return {"question": text, "header": header,
            "options": [{"label": l, "description": "option %s" % l} for l in labels], "multiSelect": multi}


class T(object):
    """Lines of one session's transcript, oldest first."""

    def __init__(self, session_id="sess-1", entrypoint="cli", cwd="/repo"):
        self.sid = session_id
        self.entrypoint = entrypoint
        self.cwd = cwd
        self.lines = []
        self.last_uuid = None
        self.prompt = None

    def _base(self, typ, **kw):
        u = str(uuid.uuid4())
        d = {"parentUuid": self.last_uuid, "isSidechain": False}
        d.update(kw.pop("_head", {}))
        d.update({"type": typ, "uuid": u, "timestamp": kw.pop("timestamp", None) or now_stamp(),
                  "userType": "external", "entrypoint": kw.pop("entrypoint", self.entrypoint), "cwd": self.cwd,
                  "sessionId": kw.pop("sessionId", self.sid), "version": VERSION, "gitBranch": "main"})
        d.update(kw)
        self.last_uuid = u
        return d

    def add(self, d):
        self.lines.append(d)
        return self

    def user_prompt(self, text, prompt_id=None):
        self.prompt = prompt_id or str(uuid.uuid4())
        head = {"promptId": self.prompt}
        return self.add(self._base("user", _head=head, message={"role": "user", "content": text}))

    def tool_use(self, name, tool_id, inp=None, sidechain=False):
        d = self._base("assistant", message={"model": "claude-test", "id": "msg_" + tool_id, "type": "message",
                                             "role": "assistant",
                                             "content": [{"type": "tool_use", "id": tool_id, "name": name,
                                                          "input": inp or {}}]},
                       requestId="req_" + tool_id)
        d["isSidechain"] = sidechain
        return self.add(d)

    def ask(self, tool_id, questions):
        return self.tool_use("AskUserQuestion", tool_id, {"questions": questions})

    def answer(self, tool_id, questions, answers, source="user_temporary", prompt_id=None, annotations=None,
               timestamp=None, entrypoint=None, decision="accept", session_id=None, sidechain=False,
               permission=True):
        text = "Your questions have been answered: " + ", ".join('"%s"="%s"' % kv for kv in answers.items())
        head = {"promptId": prompt_id or self.prompt}
        kw = {"_head": head, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id,
                                                                      "content": text}]},
              "toolUseResult": {"questions": questions, "answers": answers, "annotations": annotations or {}},
              "sourceToolAssistantUUID": self.last_uuid, "timestamp": timestamp,
              "entrypoint": entrypoint or self.entrypoint}
        if session_id:
            kw["sessionId"] = session_id
        if permission:
            kw["permissionDecision"] = {"decision": decision, "source": source}
        d = self._base("user", **kw)
        d["isSidechain"] = sidechain
        return self.add(d)

    def cancel(self, tool_id):
        """Esc on the question (measured): is_error, toolUseResult a string, no permissionDecision."""
        d = self._base("user", _head={"promptId": self.prompt},
                       message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id,
                                                             "is_error": True,
                                                             "content": "The user doesn't want to proceed with this "
                                                                        "tool use."}]},
                       toolUseResult="User rejected tool use", toolDenialKind="user",
                       sourceToolAssistantUUID=self.last_uuid)
        return self.add(d)

    def tool_result(self, tool_id, text="ok"):
        d = self._base("user", _head={"promptId": self.prompt},
                       message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id,
                                                             "content": text}]},
                       toolUseResult={"stdout": text, "stderr": "", "interrupted": False},
                       permissionDecision={"decision": "accept", "source": "config"},
                       sourceToolAssistantUUID=self.last_uuid)
        return self.add(d)

    def noise(self, kind="api-request-blob", payload=""):
        """A line Claude Code keeps beside the conversation (a copy of messages, attachments, …)."""
        if kind == "attachment":
            return self.add({"parentUuid": self.last_uuid, "isSidechain": False,
                             "attachment": {"type": "hook_success", "content": payload}, "type": "attachment",
                             "uuid": str(uuid.uuid4()), "timestamp": now_stamp(), "sessionId": self.sid})
        return self.add({"type": kind, "sessionId": self.sid, "hash": uuid.uuid4().hex, "content": payload})

    def compact(self):
        return self.add(self._base("system", subtype="compact_boundary", content="Conversation compacted"))

    def text(self):
        return "".join(json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n" for d in self.lines)

    def write(self, path, tail=""):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.text() + tail)
        return path


def transcript_path(env, session_id="sess-1", key="-repo"):
    cfg = env.get("CLAUDE_CONFIG_DIR")
    return os.path.join(cfg, "projects", key, session_id + ".jsonl")


def default_qtext(label):
    parts = label.split(" ")
    if len(parts) >= 3:  # "<word> <video> <hash or lang …>"
        return "[%s] 이 결과를 승인할까요? (%s)" % (parts[1], " ".join(parts[2:]))
    return "이 결과를 승인할까요? (%s)" % label.split(" ", 1)[-1]


def approval_turn(t, label, ask_id="toolu_ask1", call_id="toolu_cmd1", qtext=None, other_label="수정해 줘",
                  chosen=None, **answer_kw):
    """A turn: the person's prompt, an AskUserQuestion with the fixed label, the answer, then the command's tool_use.
    The default question text shows what the guard needs: `[<video>]` first for a video's label, and the hash."""
    qtext = qtext or default_qtext(label)
    qs = [question(qtext, [label, other_label])]
    t.user_prompt("진행해")
    t.ask(ask_id, qs)
    t.answer(ask_id, qs, {qtext: chosen if chosen is not None else label}, **answer_kw)
    t.tool_use("Bash", call_id, {"command": "x"})
    return t


def fixture_lines(name):
    with open(os.path.join(FIXTURES, name + ".jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def relabeled(name, video):
    """A copy of a measured fixture in the M1a label form (m1-plan §3.3): every `<word> <hash12>` label becomes
    `<word> <video> <hash12>` and every AskUserQuestion text starts with `[<video>]` (keys of `answers` and the
    result text included). The measured files themselves stay as recorded."""
    import re
    lines = fixture_lines(name)
    texts = set()
    for d in lines:
        for b in ((d.get("message") or {}).get("content") or []) if isinstance(d.get("message"), dict) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion":
                for q in (b.get("input") or {}).get("questions") or []:
                    texts.add(q["question"])
    label_re = re.compile(r"(승인|거부|재고정|제외) ([0-9a-f]{12})\b")

    def fix(s):
        s = label_re.sub(lambda m: "%s %s %s" % (m.group(1), video, m.group(2)), s)
        for q in sorted(texts, key=len, reverse=True):
            if q in s and ("[%s] %s" % (video, q)) not in s:
                s = s.replace(q, "[%s] %s" % (video, q))
        return s

    def walk(o):
        if isinstance(o, dict):
            return {(fix(k) if isinstance(k, str) else k): walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return fix(o) if isinstance(o, str) else o
    return [walk(d) for d in lines]
