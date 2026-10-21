"""Approval commands with a person's answer (m0d2-plan §3): the guard checks the transcript, writes
`.claude/studio/local/pending-approval.json` (m0b2-plan §1 contract) for state.py to consume, and offers
`allow` (judge decides whether the call is that one command alone, §4.4).

Read-only towards the state: the consumption record is read here (state.py checks it again under its lock);
nothing of state.py's writers is imported (structure rule)."""

import datetime
import json
import os

from ..state import labels
from . import proxy, transcript
from .repos import has_exclude_block

S2V_MILESTONE = "M3b"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_dir(worktree):
    return os.path.join(worktree, ".claude", "studio", "local")


def consumed(worktree, key):
    try:
        with open(os.path.join(local_dir(worktree), "consumed-answers.jsonl"), encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and (e.get("session_id"), e.get("tool_use_id"), e.get("question_index")) == key:
                    return True
    except OSError:
        pass
    return False


def write_pending(ri, data):
    """Atomic write; raises OSError."""
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
        label, h12 = labels.expected(argv, ri.worktree, ri.studio_root)
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
        idx, text, note = transcript.choose(ans, label, h12)
        key = (sid, ans.tool_use_id, idx)
        if consumed(ri.worktree, key):
            raise transcript.NoEvidence("consumed")
    except transcript.NoEvidence as e:
        return Verdict("G-EVIDENCE", evidence_text("state.py %s" % sub, label, e))
    base.update({"tool_use_id": ans.tool_use_id, "question_index": idx, "question": text, "answer": label,
                 "mode": "human"})
    if note:
        base["reason"] = note
    return Verdict(pending=base, ri=ri, reason="answer %s#%d (%s)" % (ans.tool_use_id, idx, label))


def labels_argv_sha(argv):
    from ..state.argv import argv_sha
    return argv_sha(argv)


def evidence_text(what, label, e):
    return ("%s records a person's decision, and the guard found no answer \"%s\" in this turn: %s. Ask with "
            "AskUserQuestion — show the artifact and its hash and offer the fixed option \"%s\" (each question text "
            "unique) — then run the command alone right after the answer." % (what, label, e.sentence(), label))


def s2v(hook, env, ri, words):
    """s2v approval commands: allowed only in the sandbox proxy mode until actors (M3b)."""
    what = "s2v " + " ".join(words)
    if in_subagent(hook):
        return Verdict("G-MAIN", "%s runs only in the main session." % what)
    if ri is not None and proxy.active(env, ri.worktree):
        return Verdict(reason="proxy mode: %s" % what)
    return Verdict("G-APPROVAL", "%s records a person's decision: actor approvals arrive with actors (%s). Ask the "
                                 "user; do not run it another way." % (what, S2V_MILESTONE))
