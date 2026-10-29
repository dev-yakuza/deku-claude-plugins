"""Approval commands with a person's answer (m0d2-plan §3): the guard checks the transcript, writes
`.claude/studio/local/pending-approval.json` (m0b2-plan §1 contract) for state.py to consume, and offers
`allow` (judge decides whether the call is that one command alone, §4.4).

Read-only towards the state: the consumption record is read here (state.py checks it again under its lock);
nothing of state.py's writers is imported (structure rule)."""

import datetime
import json
import os

from .. import paths
from ..state import labels
from . import proxy, transcript
from .repos import has_exclude_block

S2V_MILESTONE = "M3b"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_dir(worktree):
    return os.path.join(worktree, ".claude", "studio", "local")


def consumed(ri, key):
    """Whether the answer `key` (session, tool_use_id, question index) was used anywhere in the repository: the record
    is in the git common dir, shared by every worktree (m1-plan §3.2). transcript.NoEvidence("record-unreadable")
    when the record cannot be read (closed; the guard runs no git to find the folder)."""
    if not ri.common_dir:
        raise transcript.NoEvidence("record-unreadable", "the repository's git folder is unknown")
    try:
        f = open(paths.consumed_log(ri.worktree, ri.common_dir), encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError as e:
        raise transcript.NoEvidence("record-unreadable", str(e))
    try:
        with f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and (e.get("session_id"), e.get("tool_use_id"), e.get("question_index")) == key:
                    return True
    except OSError as e:
        raise transcript.NoEvidence("record-unreadable", str(e))
    return False


def write_pending(ri, data):
    """Atomic write; raises OSError (also when local/ or a folder above it is a symbolic link)."""
    why = paths.local_problem(ri.worktree)
    if why:
        raise OSError(why)
    local = local_dir(ri.worktree)
    if not os.path.isdir(local):
        if not has_exclude_block(ri):
            raise OSError("%s does not exist and git does not ignore it yet" % local)
        os.makedirs(local, exist_ok=True)
    p = os.path.join(local, "pending-approval.json")
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    why = paths.local_problem(ri.worktree)
    if why:  # the folder was swapped for a link while writing (review V4)
        raise OSError(why)


def in_subagent(hook):
    return bool(hook.get("agent_id") or hook.get("agent_type"))


class Verdict(object):
    """deny (rule, text) or an evidence record + effect."""

    def __init__(self, rule=None, text=None, pending=None, ri=None, reason=None):
        self.rule, self.text, self.pending, self.ri, self.reason = rule, text, pending, ri, reason


def state_py(hook, env, ri, argv):
    """Verdict for `state.py <argv>` (a subcommand that needs a person's answer) in repository `ri`."""
    sub = argv[0] if argv else ""
    if in_subagent(hook):
        return Verdict("G-MAIN", "state.py %s runs only in the main session (a subagent cannot ask the person or "
                                 "carry their answer)." % sub)
    flag = any(a == "--proxy" or a.startswith("--proxy=") for a in argv)
    sandbox = proxy.active(env, ri.worktree)
    if flag and not sandbox:
        return Verdict("G-PROXY", "--proxy is accepted only in the sandbox proxy mode started by the person "
                                  "(STUDIO_SANDBOX).")
    try:
        label, h12, video = labels.expected(argv, ri.worktree, ri.studio_root)
    except labels.NoLabel as e:
        return Verdict("G-APPROVAL", "%s. Ask the user what to do." % e)
    sid = hook.get("session_id")
    base = {"schema": 1, "argv_sha": labels_argv_sha(argv), "session_id": sid, "written_at": _now()}
    if flag:
        tid = hook.get("tool_use_id")
        if not sid or not tid:
            return Verdict("G-EVIDENCE", "state.py %s: the hook gave no session or call id." % sub)
        base.update({"tool_use_id": tid, "question_index": 0, "question": "proxy", "answer": label, "mode": "proxy"})
        return Verdict(pending=base, ri=ri, reason="proxy approval %s" % label)
    try:
        ans = transcript.find(hook, env)
        idx, text, note = transcript.choose(ans, label, h12, video=video)
        key = (sid, ans.tool_use_id, idx)
        if consumed(ri, key):
            raise transcript.NoEvidence("consumed")
        lines = _gate_lines(ri, argv)
        if lines:
            from ..commit.summary import norm
            missing = [l for l in lines if norm(l) not in norm(text)]
            if missing:
                raise transcript.NoEvidence("gate-lines-not-shown")
    except transcript.NoEvidence as e:
        extra = ""
        if e.code == "gate-lines-not-shown":
            extra = " The question shows: %s" % " / ".join(_gate_lines(ri, argv))
        return Verdict("G-EVIDENCE", evidence_text("state.py %s" % sub, label, e) + extra)
    base.update({"tool_use_id": ans.tool_use_id, "question_index": idx, "question": text, "answer": label,
                 "mode": "human"})
    if note:
        base["reason"] = note
    return Verdict(pending=base, ri=ri, reason="answer %s#%d (%s)" % (ans.tool_use_id, idx, label))


def _gate_lines(ri, argv):
    """The lines a gate question must show besides the label: for ①, every commit to the source after begin (M1e
    review S5); for ②, what `shown 2` recorded (M1f review V1). Read from the video's state.json; an unreadable state
    shows nothing here (state.py refuses it)."""
    from ..state.argv import canonical
    c = canonical(argv)
    if c["cmd"] != "approve" or len(c["pos"]) < 2 or c["pos"][1] not in ("1", "2"):
        return []
    try:
        st = labels.read_state(labels.video_dir(ri.worktree, ri.studio_root, c["pos"][0]))
        if c["pos"][1] == "1":
            return labels.source_commit_lines(st)
        return labels.gate2_lines(st, c["opt"].get("--lang"))  # ②: exemptions, readings, conflicts (V1)
    except Exception:  # noqa: BLE001
        return []


def setup_py(hook, env, ri, argv):
    """Verdict for the plugin's `setup.py <argv>` approval commands (m1-plan §5.1, D-M1-5): `config set` of a protected
    key or s2v.path and `narrator set` (설정 <h12>), `update apply` (갱신 <h12>). Never in the proxy mode. A config
    or narrator question must also show the change as a line `설정 <key>: <old> → <new>` — the old value is read here
    (config.json, machine.json, the narrator's status.json), the new one from the command line."""
    from ..setup import labels as sl
    what = "setup.py %s" % " ".join(argv[:2])
    if in_subagent(hook):
        return Verdict("G-MAIN", "%s runs only in the main session." % what)
    if any(a == "--proxy" or a.startswith("--proxy=") for a in argv):
        return Verdict("G-PROXY", "%s records the person's own settings — the proxy mode cannot approve it." % what)
    try:
        label, h12 = sl.expected(argv)
    except labels.NoLabel as e:
        return Verdict("G-APPROVAL", "%s. Run the preview (setup.py config preview / narrator preview / update plan) "
                                     "and ask the person first." % e)
    line = None
    try:
        line = _setup_line(ri, argv, sl)
    except ValueError as e:
        return Verdict("G-APPROVAL", "%s: %s" % (what, e))
    sid = hook.get("session_id")
    base = {"schema": 1, "argv_sha": labels_argv_sha(argv), "session_id": sid, "written_at": _now()}
    try:
        ans = transcript.find(hook, env)
        idx, text, note = transcript.choose(ans, label, h12, video=None)
        if consumed(ri, (sid, ans.tool_use_id, idx)):
            raise transcript.NoEvidence("consumed")
        if line is not None:
            from ..commit.summary import norm
            if norm(line) not in norm(text):
                raise transcript.NoEvidence("values-not-shown")
    except transcript.NoEvidence as e:
        return Verdict("G-EVIDENCE", evidence_text(what, label, e) + (" The question shows: %s" % line if line
                                                                     else ""))
    base.update({"tool_use_id": ans.tool_use_id, "question_index": idx, "question": text, "answer": label,
                 "mode": "human"})
    if note:
        base["reason"] = note
    return Verdict(pending=base, ri=ri, reason="answer %s#%d (%s)" % (ans.tool_use_id, idx, label))


def _setup_line(ri, argv, sl):
    """The change line a config/narrator question must show (None for update apply)."""
    from ..state.argv import canonical
    c = canonical(argv)
    words = [c["cmd"]] + c["pos"]
    if words[:2] == ["config", "set"]:
        if len(words) != 4:
            raise ValueError("config set <key> <value>")
        key, new = words[2], sl.parse_value(words[3])
        if key == "s2v.path":
            from .. import machine
            try:
                old = machine.s2v_path(ri.worktree)
            except paths.UnsafeLocal as e:
                raise ValueError(str(e))
            if isinstance(new, str):
                new = os.path.normpath(new)
            return sl.config_line(key, old, new, old is not None)
        present, old = sl.lookup(ri.config if isinstance(ri.config, dict) else {}, key)
        return sl.config_line(key, old, new, present)
    if words[:2] == ["narrator", "set"]:
        if len(words) != 3:
            raise ValueError("narrator set <lang> --engine … --style …")
        nid = c["opt"].get("--id") or "narrator"
        engine, style = c["opt"].get("--engine"), c["opt"].get("--style")
        if not isinstance(engine, str) or not isinstance(style, str):
            raise ValueError("narrator set needs --engine and --style")
        from .. import narrator as nar
        st = None
        p = os.path.join(ri.worktree, ri.studio_root, "cast", nid, "status.json")
        try:
            with open(p, "rb") as f:
                st = nar.parse(f.read())
        except OSError:
            st = None
        return sl.narrator_line(nid, words[2], nar._voice(st, words[2]) if st else None, (engine, style))
    return None


def labels_argv_sha(argv):
    from ..state.argv import argv_sha
    return argv_sha(argv)


def evidence_text(what, label, e):
    return ("%s records a person's decision, and the guard found no answer \"%s\" in this turn: %s. Ask with "
            "AskUserQuestion — show the artifact and its hash, start a video's question with [<video>], and offer the "
            "fixed option \"%s\" (each question text unique) — then run the command alone in a later message, right "
            "after the answer." % (what, label, e.sentence(), label))


def s2v(hook, env, ri, words):
    """s2v approval commands: allowed only in the sandbox proxy mode until actors (M3b)."""
    what = "s2v " + " ".join(words)
    if in_subagent(hook):
        return Verdict("G-MAIN", "%s runs only in the main session." % what)
    if ri is not None and proxy.active(env, ri.worktree):
        return Verdict(reason="proxy mode: %s" % what)
    return Verdict("G-APPROVAL", "%s records a person's decision: actor approvals arrive with actors (%s). Ask the "
                                 "user; do not run it another way." % (what, S2V_MILESTONE))
