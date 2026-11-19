#!/usr/bin/env python3
"""replay.k6_downgrade_drill — the OFFLINE half of the §10.2-4(b) / §10.2-5 downgrade drill (K6 item 17).

What a 0.102 engine and supervisor can leave behind, checked against what the rollback target (0.101.3) reads —
statically, from the two trees in git. No model, no plugin install, no GitHub.

1. every `halted:<reason>` the 0.102 supervisor can write (its `HALT_REASON=` literals + the engine's `env_halt`
   / `halted: env <r>` reasons through the supervisor's `engine-env-<r>` mapping) — is it named by 0.101.3's
   `run.md` (what the person is told), `_handoff.md` (the closed set) and `daily.md` (the classifier)?
2. the four 0.101.3 sentences of design §10.3 are in that tree;
3. the engine-only records start with a `<!-- guild:` marker (0.101.3 H§M skips those) — decision log,
   unattended log, split plan, notes.

The live half (install 0.101.3 through the wrapper marketplace, run it on engine records, re-upgrade) needs a real
Claude session — §10.2-5, after the quota recovers.

    k6_downgrade_drill.py --repo <engine repo> [--old <rev of 0.101.3>] [--new <rev, default HEAD>] --out <dir>
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

P = "plugins/guild-plugin/skills/gld/"
OLD_FILES = {"run.md": P + "commands/sprint/run.md", "_handoff.md": P + "commands/atoms/_handoff.md",
             "daily.md": P + "commands/sprint/daily.md", "_execute_spine.md": P + "commands/atoms/_execute_spine.md"}


def show(repo, rev, path):
    try:
        return subprocess.check_output(["git", "-C", repo, "show", "%s:%s" % (rev, path)],
                                       stderr=subprocess.DEVNULL).decode("utf-8", "replace")
    except subprocess.CalledProcessError:
        return None


def ls(repo, rev, prefix):
    out = subprocess.check_output(["git", "-C", repo, "ls-tree", "-r", "--name-only", rev, prefix]).decode()
    return [x for x in out.split("\n") if x.endswith(".py")]


def emitted_reasons(repo, rev):
    """{reason: where} for every halted reason the `rev` supervisor can write."""
    sup = show(repo, rev, P + "templates/sprint-supervisor.sh") or ""
    out = {}
    for m in re.finditer(r'HALT_REASON="([a-z][a-zA-Z0-9-]*)"', sup):
        out.setdefault(m.group(1), "supervisor literal")
    out.pop("sig", None)
    for s in ("sigTERM", "sigHUP"):
        out.setdefault(s, "supervisor signal trap")
    env = set()
    for f in ls(repo, rev, P + "engine/"):
        t = show(repo, rev, f) or ""
        env.update(re.findall(r'env_halt\("([a-z-]+)"', t))
        env.update(re.findall(r'halted: env ([a-z][a-z-]*)', t))
    env.discard("other")                 # `halted: env other` is the generic wording — never a reason by itself
    for r in sorted(env):
        out.setdefault("engine-env-%s" % r, "engine env_halt via the supervisor's engine-env-<r>")
    return out


def _enumerated(text):
    """Reasons a 0.101.3 file lists through an `engine-env-<a|b|c>` enumeration."""
    got = set()
    for m in re.finditer(r"engine-env-<([a-z|` ·-]+)>", text or ""):
        for r in re.split(r"[|·`\s]+", m.group(1)):
            if r and r != "reason":
                got.add("engine-env-%s" % r)
    return got


def generic(text):
    return bool(re.search(r"engine-env-<reason>", text or ""))


def check(repo, old, new):
    old_t = dict((k, show(repo, old, v)) for k, v in OLD_FILES.items())
    rows = []
    for reason, where in sorted(emitted_reasons(repo, new).items()):
        r = {"reason": reason, "emitted_by": where}
        for k in ("run.md", "_handoff.md", "daily.md"):
            t = old_t.get(k) or ""
            if re.search(r"(?<![a-z-])%s(?![a-z-])" % re.escape(reason), t) or reason in _enumerated(t):
                r[k] = "named"
            elif reason.startswith("engine-env-") and generic(t):
                r[k] = "generic engine-env-<reason>"
            else:
                r[k] = "MISSING"
        rows.append(r)
    sentences = {
        "guild-answer lines are answers, not directives": bool(re.search(r"guild-answer:", old_t["_handoff.md"] or "")),
        "audit head: lines and [id:F<k>]": bool(re.search(r"head: <sha>|\[id:F", old_t["_execute_spine.md"] or "")),
        "unattended-log section left alone": bool(re.search(r"guild:unattended-log", old_t["_execute_spine.md"] or "")),
        "new halted reasons in the closed set": "plugin-version-changed" in (old_t["_handoff.md"] or ""),
        "busy / busy-skipped classes": "busy-skipped" in (old_t["daily.md"] or ""),
    }
    return rows, sentences


def markers_ok():
    """The engine's record markers (every one a `<!-- guild:` marker — 0.101.3's H§M skips those)."""
    return {"engine_marker_names": sorted(ls_engine_markers())}


def ls_engine_markers():
    pat = re.compile(r"<!-- guild:([a-z][a-z0-9:-]*) -->")
    found = set()
    for root, _d, files in os.walk(os.path.join(ENGINE, "guildcore", "records")):
        for f in files:
            if f.endswith(".py"):
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    found.update(pat.findall(fh.read()))
    return found


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--old", default="4b7d49c")
    ap.add_argument("--new", default="HEAD")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rows, sentences = check(a.repo, a.old, a.new)
    missing = [r for r in rows if "MISSING" in (r.get("run.md"), r.get("_handoff.md"), r.get("daily.md"))]
    rep = {"old": a.old, "new": a.new, "reasons": rows, "sentences_0_101_3": sentences,
           "reasons_missing_somewhere": [r["reason"] for r in missing], "markers": markers_ok(),
           "not_checked_here": "the live drill (§10.2-5): wrapper-marketplace install, plugin list per worktree, "
                               "supervisor halt, engine exit 6, 0.101.3 finishing an engine-started Issue, re-upgrade"}
    os.makedirs(a.out, exist_ok=True)  # fs-ok: report dir chosen by the caller
    with open(os.path.join(a.out, "downgrade_drill.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, ensure_ascii=False)
    print(json.dumps({"reasons": len(rows), "missing": rep["reasons_missing_somewhere"],
                      "sentences": sentences}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
