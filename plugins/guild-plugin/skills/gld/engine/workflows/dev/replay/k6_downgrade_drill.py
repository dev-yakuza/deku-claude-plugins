#!/usr/bin/env python3
"""replay.k6_downgrade_drill — the OFFLINE half of the §10.2-4(b) / §10.2-5 downgrade drill (K6 item 17).

What a 0.102 engine and supervisor can leave behind, checked against what the rollback target (0.101.3) reads —
statically, from the two trees in git. No model, no plugin install, no GitHub.

1. every `halted:<reason>` the 0.102 supervisor can write (its `HALT_REASON=` literals + the engine's `env_halt`
   / `halted: env <r>` reasons through the supervisor's `engine-env-<r>` mapping) — is it named by 0.101.3's
   `run.md` (what the person is told), `_handoff.md` (the closed set) and `daily.md` (the classifier)?
2. the four 0.101.3 sentences of design §10.3 are in that tree;
3. the engine-only records start with a `<!-- guild:` marker (0.101.3 H§M skips those) — decision log,
   unattended log, split plan, notes;
4. (K6 r1 m6, user decision 2) every token the 0.102 supervisor WRITES where 0.101.3 reads — halted reasons (state),
   event classes (failures.jsonl), wait states (ledger state), board reason tokens — run through the supervisor's
   own `compat_fold` / `compat_note` (bash), and the folded token checked against the 0.101.3 file that renders it
   (run.md's halted rows, daily.md's class table and state shapes, board.md's token set).
   1 reports the halted reasons as named; `_handoff.md` declares `halted:<reason>` a wildcard (r1 m6), so its
   enumeration is not the defect — the missing EXPLANATION row is (4 answers it).

The live half (install 0.101.3 through the wrapper marketplace, run it on engine records, re-upgrade) needs a real
Claude session — §10.2-5, after the quota recovers.

    k6_downgrade_drill.py --repo <engine repo> [--old <rev of 0.101.3>] [--new <rev, default HEAD>] --out <dir>
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

P = "plugins/guild-plugin/skills/gld/"
OLD_FILES = {"run.md": P + "commands/sprint/run.md", "_handoff.md": P + "commands/atoms/_handoff.md",
             "daily.md": P + "commands/sprint/daily.md", "_execute_spine.md": P + "commands/atoms/_execute_spine.md"}


def show(repo, rev, path):
    from guildcore.adapters import git as G
    try:
        return G.run(repo, "show", "%s:%s" % (rev, path)).decode("utf-8", "replace")
    except G.GitError:
        return None


def ls(repo, rev, prefix):
    from guildcore.adapters import git as G
    out = G.run(repo, "ls-tree", "-r", "--name-only", rev, prefix).decode()
    return [x for x in out.split("\n") if x.endswith(".py")]


def emitted_reasons(repo, rev, sup=None):
    """{reason: where} for every halted reason the `rev` supervisor can write."""
    if sup is None:
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


# ── K6 r1 m6 + user decision 2 ("0.102 에서 접어 쓰기"): every token the 0.102 supervisor WRITES, after its fold ─────
def _fn(src, name):
    m = re.search(r"(?ms)^%s\(\) \{.*?^\}\n" % re.escape(name), src)
    return m.group(0) if m else ""


def written_tokens(sup):
    """{token: field} — every 0.102 token the supervisor can write into a field 0.101.3 reads: the halted reasons
    (marker/ledger `state`), the event classes (failures.jsonl `class`), the wait states (ledger `state`) and the
    board reason tokens."""
    out = {}
    for c in set(re.findall(r'record_(?:event|failure) "\$[A-Za-z_]+" ([a-z][a-z-]+)', sup)):
        out[c] = "class"
    for w in set(re.findall(r'\.reason == "([a-z][a-z-]+)"', sup)):
        out["%s-until-1790000000" % w] = "state"
        out["%s-remaining-60s" % w] = "state"
    for b in set(re.findall(r'board_col "\$[A-Za-z_]+" blocked ([a-z][a-z-]+)', sup)):
        out["board:" + b] = "board"
    for b in set(re.findall(r'W_END=([a-z][a-z-]+)', sup)):
        out["board:" + b] = "board"
    return out


def _run_fold(funcs, token):
    import subprocess
    r = subprocess.run(["bash", "-c", funcs + '\ncompat_fold "$1"; printf "\\n"; compat_note "$1"', "_", token],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lines = r.stdout.decode("utf-8", "replace").split("\n")
    return (lines[0] if lines else token), (lines[2] if len(lines) > 2 else "").strip()


def documented(old_t, field, token):
    """Does 0.101.3 document `token` in the file that renders `field`?"""
    if field == "halted":
        r = token[len("halted:"):]
        run = old_t.get("run.md") or ""
        rows = [ln for ln in run.split("\n") if ln.startswith("| `halted:")]
        if any(("`halted:%s`" % r) in ln for ln in rows):
            return True
        if r.startswith("engine-env-"):
            env = [ln for ln in rows if "engine-env-<reason>" in ln]
            return bool(env) and ("`%s`" % r[len("engine-env-"):]) in env[0]
        return False
    if field == "class":
        return bool(re.search(r"`%s`" % re.escape(token), old_t.get("daily.md") or ""))
    if field == "state":
        shape = re.sub(r"-[0-9]+s?$", "-", token)
        return ("`%s<" % shape) in (old_t.get("daily.md") or "")
    if field == "board":
        return ("`%s`" % token[len("board:"):]) in (old_t.get("board.md") or "")
    return False


def fold_check(repo, old, new, sup=None):
    """[{token, field, folded, note, documented_0_101_3}] — every 0.102 token through `compat_fold` (`sup` = the
    supervisor text to check instead of `new`'s — the tests pass the working tree)."""
    if sup is None:
        sup = show(repo, new, P + "templates/sprint-supervisor.sh") or ""
    funcs = _fn(sup, "compat_fold") + _fn(sup, "compat_note")
    old_t = dict((k, show(repo, old, v)) for k, v in OLD_FILES.items())
    old_t["board.md"] = show(repo, old, P + "commands/sprint/board.md")
    toks = dict(("halted:" + r, "halted") for r in emitted_reasons(repo, new, sup))
    toks.update(written_tokens(sup))
    rows = []
    for tok, field in sorted(toks.items()):
        folded, note = _run_fold(funcs, tok) if funcs else (tok, "")
        row = {"token": tok, "field": field, "folded": folded, "documented_0_101_3": documented(old_t, field, folded)}
        if note:
            row["note"] = note
        if folded != tok:
            row["exact_kept_in"] = {"halted": "halt_reason + halt_note (ledger / marker)", "state": "wait_reason",
                                    "class": "class_exact", "board": "failures.jsonl class_exact"}[field]
        rows.append(row)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--old", default="4b7d49c")
    ap.add_argument("--new", default="HEAD")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rows, sentences = check(a.repo, a.old, a.new)
    missing = [r for r in rows if "MISSING" in (r.get("run.md"), r.get("_handoff.md"), r.get("daily.md"))]
    folds = fold_check(a.repo, a.old, a.new)
    rep = {"old": a.old, "new": a.new, "reasons": rows, "sentences_0_101_3": sentences,
           "reasons_missing_somewhere": [r["reason"] for r in missing],
           # K6 r1 m6 / user decision 2: what 0.101.3 READS — every written token after the supervisor's fold
           "written_after_fold": folds,
           "undocumented_after_fold": [f["token"] for f in folds if not f["documented_0_101_3"]],
           "markers": markers_ok(),
           "not_checked_here": "the live drill (§10.2-5): wrapper-marketplace install, plugin list per worktree, "
                               "supervisor halt, engine exit 6, 0.101.3 finishing an engine-started Issue, re-upgrade"}
    os.makedirs(a.out, exist_ok=True)  # fs-ok: report dir chosen by the caller
    with open(os.path.join(a.out, "downgrade_drill.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, ensure_ascii=False)
    print(json.dumps({"reasons": len(rows), "missing": rep["reasons_missing_somewhere"],
                      "written": len(folds), "undocumented_after_fold": rep["undocumented_after_fold"],
                      "sentences": sentences}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
