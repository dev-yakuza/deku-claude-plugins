"""`setup.py agent-model preview|set <role> <model>` (0.1.2, pilot-2 P20): the model a role runs on — the `model:` line
of `.claude/agents/<role>.md`, which Claude Code uses when the Agent call passes no model of its own.

Every role needs the person's `설정 <h12>` answer (h12 binds the role, the old and the new model): the model of a gate
role (the fact-checker, the auditor) changes what an approval rests on. The question must also show the line
`설정 <role> model: <old> → <new>`; the guard compares it, and `set` checks the pending answer's question itself before
using it up (after a `source` the 0.0.26 guard checks only the label). Only the `model:` line changes (or is added
after `description:`); `tools:` and the persona stay. A harness commit follows (its question shows `모델 <role>: …`).
`--proxy` is refused."""

import os

from ..commit.values import model_lines, read_model
from . import labels as L, render
from .common import FAIL, NO_EVIDENCE, REFUSED, USAGE, SetupError, read_config, with_evidence, write_text

MODELS = ("haiku", "sonnet", "opus", "inherit")


def rel(role):
    return ".claude/agents/%s.md" % role


def line(role, old, new):
    return L.agent_model_line(role, old, new)


def model_hash(role, old, new):
    return L.agent_model_hash(role, old, new)


def _read(top, role):
    if role not in render.AGENTS:
        raise SetupError(USAGE, "the role is one of %s" % ", ".join(render.AGENTS))
    try:
        with open(os.path.join(top, rel(role)), encoding="utf-8", newline="") as f:  # keep CRLF as it is
            return f.read()
    except OSError:
        raise SetupError(FAIL, "%s is missing — /std init or /std update installs it" % rel(role))


def preview(top, role, model):
    """What `set` would change, its label and the line the question shows (no writes)."""
    read_config(top)  # a harness is here
    if model not in MODELS:
        raise SetupError(USAGE, "the model is one of %s" % ", ".join(MODELS))
    text = _read(top, role)
    found = model_lines(text)
    if found is None:
        raise SetupError(FAIL, "%s has no frontmatter (--- … ---)" % rel(role))
    if len(found) > 1:
        raise SetupError(FAIL, "%s has %d model: lines — keep one by hand" % (rel(role), len(found)))
    old = read_model(text)
    h = model_hash(role, old, model)
    return {"role": role, "path": rel(role), "old": old, "new": model, "changes": old != model, "h12": h,
            "label": "설정 %s" % h, "line": line(role, old, model)}


def rewrite(text, model):
    """The file with its frontmatter's `model:` line set (added after `description:`, else before the closing ---)."""
    lines = text.split("\n")  # a CRLF file keeps its \r on every line
    cr = "\r" if lines and lines[0].endswith("\r") else ""
    found = model_lines(text)
    if found:
        i = found[0][0]
        lines[i] = "model: %s%s" % (model, cr)
        return "\n".join(lines)
    end = next(i for i in range(1, len(lines)) if lines[i].rstrip() == "---")
    at = next((i + 1 for i in range(1, end) if lines[i].startswith("description:")), end)
    return "\n".join(lines[:at] + ["model: %s%s" % (model, cr)] + lines[at:])


def set_(top, role, model, expect, argv, proxy=False):
    if proxy:
        raise SetupError(USAGE, "a role's model is the person's choice: the proxy mode cannot (--proxy refused)")
    p = preview(top, role, model)
    if not p["changes"]:
        raise SetupError(REFUSED, "%s already runs on %s" % (role, model))
    if not expect:
        raise SetupError(USAGE, "this needs the person's answer: show them `%s`, ask for the option \"%s\", then run "
                                "this again with --expect %s" % (p["line"], p["label"], p["h12"]))
    if expect != p["h12"]:
        raise SetupError(FAIL, "--expect %s does not match this change (%s) — show it to the person again"
                         % (expect, p["h12"]))

    def shown(ev):  # before the answer is used up: the question showed the change line
        from ..commit.summary import first_missing, missing_text
        q = ev.get("question")
        miss = first_missing([p["line"]], q if isinstance(q, str) else "")
        if miss:
            raise SetupError(NO_EVIDENCE, "values-not-shown: %s" % missing_text(miss, "the preview"))

    def write():
        write_text(top, p["path"], rewrite(_read(top, role), model))
        return p["path"]
    return dict(p, wrote=with_evidence(top, argv, p["label"], False, write, "agent-model set", ev_check=shown))
