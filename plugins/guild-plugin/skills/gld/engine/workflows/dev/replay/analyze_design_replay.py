#!/usr/bin/env python3
"""replay.analyze_design_replay — the K4 procedure replay for analyze / design (§10.2-2) over the recorded
word_app sprint logs, in two honestly separated parts.

1. **By construction** (record grammar + label sequencing only): each legacy analyze episode's own
   values — the Readiness tokens and AC ids parsed from its `guild:analyze:output`, its `type:` edit —
   are INJECTED as the KICKOFF decision (stakes injected as the legacy outcome); the engine's analyze
   stage renders and transitions. Compared: the label-edit sequence (stage + `type:`), the Readiness
   tokens, the AC id count, the marker pair. A match here proves the renderer reproduces what it was
   given — not that the engine would have judged the same.
2. **Consistency** (not by construction — the engine's CODE meets real legacy artifacts):
   a. the engine's tolerant parser on every legacy analyze:output (Readiness found, AC ≥ 1);
   b. the analyze→design contract (§3.6) on those outputs, unattended;
   c. the design→execute contract on the REAL `docs/specs/<N>/{skeleton,test-cases}.md` from word_app's
      history (read through a `--shared` bare scratch clone, `git show` only) against the AC ids of the
      Issue's legacy analyze output — how often the engine would ask the tester / tech-lead for a repair;
   d. the PO forcing rule (unattended ∧ a partial dimension) against whether the legacy leader convened
      the product-owner; the STAKES calls the engine would make (one per partial/unclear dimension).
   Child Issues: the logs hold NO split (0 `guild:children:output` writes, the one `gh issue create` is a
   follow-up) — the split path has scenario tests only.

    analyze_design_replay.py --logs '<glob>' --repo <word_app path> --out <dir>
"""

import argparse
import collections
import glob
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from guildcore.adapters import git as G                           # noqa: E402
from guildcore.adapters.gh import FakeGh, FakeGhWrite            # noqa: E402
from guildcore.decisions import DecisionWriter                    # noqa: E402
from guildcore.judges.runner import Decision                     # noqa: E402
from guildcore.records.write import GhWriter                      # noqa: E402
from guildcore.roles.runner import RoleResult                     # noqa: E402
from workflows.dev import analysis as AN                          # noqa: E402
from workflows.dev import handoff as HO                           # noqa: E402
from workflows.dev.stages import analyze as A                     # noqa: E402
from workflows.dev.stages import base as B                        # noqa: E402

WRAP_RE = re.compile(r"skills/gld/commands/(analyze|design|implement|debug|refactor|test|qa)\.md")
LABEL_RE = re.compile(r"--(add|remove)-label[ =]\"?((?:guild|type):[a-z-]+)\"?")
ISSUE_RE = re.compile(r"issue-(\d+)-")


class Clock(object):
    def __init__(self):
        self.n = 0

    def now(self):
        self.n += 1
        return "2026-11-18T00:%02d:%02dZ" % (self.n // 60, self.n % 60)


def events(path):
    """[(kind, payload)] in order: ('wrap', name) · ('write', body) · ('label', (op, label)) · ('agent', desc)."""
    out = []
    with open(path, errors="replace") as fh:
        for ln in fh:
            if not ln.startswith("{"):
                continue
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("type") != "assistant" or r.get("parent_tool_use_id"):
                continue
            for c in r["message"].get("content", []):
                if c.get("type") != "tool_use":
                    continue
                i = c.get("input") or {}
                if c["name"] == "Read" and WRAP_RE.search(i.get("file_path", "")):
                    out.append(("wrap", WRAP_RE.search(i["file_path"]).group(1)))
                elif c["name"] == "Write" and (i.get("content") or "").startswith("<!-- guild:"):
                    out.append(("write", i["content"]))
                elif c["name"] == "Bash":
                    cmd = i.get("command", "")
                    m = WRAP_RE.search(cmd)
                    if m and ("cat " in cmd or "sed " in cmd):
                        out.append(("wrap", m.group(1)))
                    if "gh issue edit" in cmd:
                        for op, lb in LABEL_RE.findall(cmd):
                            out.append(("label", (op, lb)))
                elif c["name"] == "Agent":
                    out.append(("agent", i.get("description") or ""))
    return out


def episodes(path):
    """Cut the log at wrapper reads: one analyze and/or one design episode per log."""
    ev = events(path)
    cur, eps = None, {}
    for kind, val in ev:
        if kind == "wrap":
            cur = val if val in ("analyze", "design") else None
            if cur:
                eps.setdefault(cur, {"writes": [], "labels": [], "agents": []})
            continue
        if cur is None:
            continue
        e = eps[cur]
        if kind == "write":
            e["writes"].append(val)
        elif kind == "label":
            e["labels"].append(val)
        elif kind == "agent":
            e["agents"].append(val)
    return eps


def last_marker(writes, name):
    hit = [w for w in writes if w.startswith("<!-- guild:%s -->" % name)]
    return hit[-1] if hit else None


# ---- 1. by construction ---------------------------------------------------------------------------

def construct(n, legacy_out, legacy_labels, scratch_root):
    rec = AN.parse_output(legacy_out)
    if rec.readiness is None or not rec.ac:
        return {"skip": "legacy output unparseable (see consistency a)"}
    type_edits = [(op, lb) for op, lb in legacy_labels if lb.startswith("type:")]
    orig = next((lb[5:] for op, lb in type_edits if op == "remove"), None)
    added = next((lb[5:] for op, lb in type_edits if op == "add"), None)
    work_type = added or orig or rec.work_type or "feature"
    if orig is None and added is None and rec.work_type and rec.work_type != "feature":
        orig = rec.work_type                                   # the label already said it — no edit
    body = "legacy issue body — anchor text for the injected readiness"
    rd = {}
    for d in AN.DIMS:
        r = rec.readiness[d]
        rd[d] = {"rating": r, "anchor": {"source": "issue", "quote": "anchor text for the injected readiness"},
                 "choice_needed": "legacy %s" % d}
    fields = {"interpretations": [{"id": "legacy", "summary": "legacy chosen interpretation"}], "chosen": "legacy",
              "assumptions": [], "readiness": rd, "plan_decisions": [], "close": {"decide": "none"},
              "ac": [{"text": a["text"] or a["id"], "priority": ""} for a in rec.ac], "work_type": work_type,
              "cast": {"participation": [], "gates": []}, "po": {"convene": False}, "ui_surface": False,
              "safety_net_visual": False, "areas": [], "surface_to_human": {"ask": False}, "verdict": "ready"}
    fresh = ("add", "guild:analyze") in legacy_labels           # T1 happened in the episode → start unlabelled
    labels = ([] if fresh else [{"name": "guild:analyze"}]) + ([{"name": "type:%s" % orig}] if orig else [])
    fx = {"repo": "o/r", "issues": {str(n): {"number": n, "title": "t", "body": body, "state": "OPEN",
                                             "author_association": "OWNER", "labels": labels, "comments": [],
                                             "timeline": []}}, "prs": []}
    gh = FakeGh(fx)
    clock = Clock()
    w = FakeGhWrite(gh, clock)
    writer = GhWriter(gh, w, sleep=lambda s: None)
    dw = DecisionWriter(writer, n, clock)

    def role(call):
        return RoleResult("DONE", None, {"ac_patch": []} if call.role == "product-owner" else {})

    def judge(spec):
        if spec.group == "KICKOFF":
            return Decision("ready", json.loads(json.dumps(fields)), "judge:opus", "r" * 12)
        if spec.group == "STAKES":                             # injected: legacy advanced → low
            return Decision("low", {"level": "low", "local_reversible_reason": "legacy advanced"}, "judge:opus", "s" * 12)
        raise RuntimeError("unexpected judge %s" % spec.group)
    p = B.Ports(n, gh, writer, dw, clock, {"language": "ko"}, scratch_root, unattended=True, run_role=role, judge=judge)
    p.spec_store = os.path.join(scratch_root, ".specs")
    r = A.run(p)
    out = next((c["body"] for c in fx["issues"][str(n)]["comments"] if c["body"].startswith("<!-- guild:analyze:output -->")), "")
    eng = AN.parse_output(out)
    eng_labels = []
    for c in w.calls:
        if c[0] == "edit_labels":
            eng_labels += [("add", x) for x in c[2]] + [("remove", x) for x in c[3]]
    want = [x for x in legacy_labels if x[1] != "guild:needs-human"]
    got = [x for x in eng_labels if x[1] != "guild:needs-human"]
    why = None
    if ("add", "type:feature") in want and orig is None and ("add", "type:feature") not in got:
        why = "intentional: legacy added type:feature to an Issue with no type label (absent = feature, catalog D1.3 — the engine writes nothing)"
    if "하네스/게이트" in r.token():
        why = "intentional:R7C-m1 harness guard (an AC names .claude/settings*.json or .claude/guild/gates/**)"
    return {"token": r.token(), "labels_match": sorted(want) == sorted(got), "difference": why, "legacy_labels": want, "engine_labels": got,
            "readiness_match": eng.readiness == rec.readiness, "ac_count_match": len(eng.ac) == len(rec.ac),
            "markers_ok": out.startswith("<!-- guild:analyze:output -->") and out.rstrip().endswith("<!-- /guild:analyze:output -->")}


# ---- 2. consistency ---------------------------------------------------------------------------------

def git_show(bare, n, name):
    sha = G.run(bare, "log", "--all", "--format=%H", "-1", "--", "docs/specs/%d/%s" % (n, name), check=False).decode().strip()
    if not sha:
        return None
    out = G.run(bare, "show", "%s:docs/specs/%d/%s" % (sha, n, name), check=False)
    return out.decode("utf-8", "replace") if out else None


def run(logs, repo, out_dir):
    tmp = tempfile.mkdtemp(prefix="k4-replay-")
    bare = os.path.join(tmp, "wa.git")
    G.run(tmp, "clone", "-q", "--bare", "--shared", repo, bare)
    scratch = os.path.join(tmp, "root")
    os.makedirs(scratch)
    G.run(scratch, "init", "-q")
    by_issue = collections.defaultdict(list)
    for p in sorted(logs):
        m = ISSUE_RE.search(os.path.basename(p))
        if m:
            by_issue[int(m.group(1))].append(p)
    S = collections.Counter()
    eps = []
    for n, files in sorted(by_issue.items()):
        a_out, d_out, a_labels, a_agents, d_agents = None, None, [], [], []
        for f in sorted(files):
            e = episodes(f)
            if "analyze" in e and last_marker(e["analyze"]["writes"], "analyze:output"):
                a_out = last_marker(e["analyze"]["writes"], "analyze:output")
                a_labels = e["analyze"]["labels"]
                a_agents = e["analyze"]["agents"]
            if "design" in e and last_marker(e["design"]["writes"], "design:output"):
                d_out = last_marker(e["design"]["writes"], "design:output")
                d_agents = e["design"]["agents"]
        if a_out is None and d_out is None:
            continue
        row = {"issue": n}
        if a_out is not None:
            S["analyze_episodes"] += 1
            rec = AN.parse_output(a_out)
            row["readiness"] = rec.readiness
            row["ac"] = len(rec.ac)
            S["a.readiness_parsed"] += rec.readiness is not None
            S["a.ac_parsed"] += bool(rec.ac)
            bad = A.analyze_to_design([{"id": 1, "body": a_out}], [], True)
            row["analyze_to_design"] = bad
            S["b.contract_pass"] += not bad
            for x in bad:
                S["b.fail:%s" % x] += 1
            po = any(d.startswith("product-owner") for d in a_agents)
            partial = bool(rec.readiness) and "partial" in rec.readiness.values()
            open_dims = sum(1 for v in (rec.readiness or {}).values() if v in ("partial", "unclear"))
            S["d.stakes_calls"] += open_dims
            S["d.partial_episodes"] += partial
            S["d.partial_and_legacy_po"] += partial and po
            S["d.clear_and_legacy_po"] += (not partial) and po
            S["d.legacy_po"] += po
            stage_labels = [x for x in a_labels if x[1].startswith("guild:")]
            if ("add", "guild:design") in stage_labels:
                c = construct(n, a_out, [x for x in a_labels if x[1] in ("guild:analyze", "guild:design", "guild:needs-human")
                                         or x[1].startswith("type:")], scratch)
                row["construct"] = c
                if "skip" in c:
                    S["c1.skipped"] += 1
                else:
                    S["c1.episodes"] += 1
                    for k in ("labels_match", "readiness_match", "ac_count_match", "markers_ok"):
                        S["c1.%s" % k] += bool(c[k])
                        S["c1.%s_excl" % k] += bool(c[k]) or bool(c.get("difference"))
                    S["c1.intentional"] += bool(c.get("difference"))
                    S["c1.advance"] += c["token"] == "OK ADVANCE: design"
            else:
                S["a.legacy_not_advanced"] += 1
        if d_out is not None:
            S["design_episodes"] += 1
            tc = git_show(bare, n, "test-cases.md")
            sk = git_show(bare, n, "skeleton.md")
            ids = [a["n"] for a in AN.parse_output(a_out).ac] if a_out else []
            mv = re.search(r"시각 케이스 (\d+)\s*건", d_out)
            visual = "<!-- guild:visual-cases -->" in (tc or "") or bool(mv and int(mv.group(1)) > 0)
            if tc is None or sk is None:
                S["c.spec_missing_in_history"] += 1
                row["design_contract"] = "spec files not in history"
            elif not ids:
                S["c.no_ac_ids"] += 1
                row["design_contract"] = "no AC ids from the analyze output"
            else:
                bad = HO.design_to_execute(sk, tc, ids, visual)
                row["design_contract"] = bad
                S["c.checked"] += 1
                S["c.pass"] += not bad
                for x in bad:
                    S["c.fail:%s" % re.sub(r"#\d+(, #\d+)*", "#…", x)] += 1
            row["design_specialists"] = [d for d in d_agents if " design #" in d and not d.startswith(("tech-lead", "tester"))]
            S["d.design_specialist_spawns"] += len(row["design_specialists"])
        eps.append(row)
    pct = lambda a, b: round(100.0 * a / b, 2) if b else None      # noqa: E731
    summary = {
        "data": {"logs": len(logs), "issues_with_analyze_or_design": len(eps), "analyze_episodes": S["analyze_episodes"],
                 "design_episodes": S["design_episodes"], "child_split_episodes": 0},
        "by_construction": {
            "what": "legacy Readiness/AC/type injected as the KICKOFF decision (stakes injected low); the engine renders "
                    "and transitions. Proves the record grammar + label sequencing only.",
            "episodes": S["c1.episodes"], "skipped_unparseable": S["c1.skipped"],
            "advance_pct": pct(S["c1.advance"], S["c1.episodes"]),
            "labels_match_pct": pct(S["c1.labels_match"], S["c1.episodes"]),
            "readiness_match_pct": pct(S["c1.readiness_match"], S["c1.episodes"]),
            "ac_count_match_pct": pct(S["c1.ac_count_match"], S["c1.episodes"]),
            "markers_ok_pct": pct(S["c1.markers_ok"], S["c1.episodes"]),
            "intentional_differences": S["c1.intentional"],
            "excluding_intentional": dict((k, pct(S["c1.%s_excl" % k], S["c1.episodes"]))
                                          for k in ("labels_match", "readiness_match", "ac_count_match", "markers_ok"))},
        "consistency": {
            "what": "the engine's code on real legacy artifacts — no injected decision",
            "a_parser_readiness_pct": pct(S["a.readiness_parsed"], S["analyze_episodes"]),
            "a_parser_ac_pct": pct(S["a.ac_parsed"], S["analyze_episodes"]),
            "b_analyze_to_design_pass_pct": pct(S["b.contract_pass"], S["analyze_episodes"]),
            "b_failures": dict((k[7:], v) for k, v in S.items() if k.startswith("b.fail:")),
            "c_design_to_execute_checked": S["c.checked"],
            "c_design_to_execute_pass_pct": pct(S["c.pass"], S["c.checked"]),
            "c_failures": dict((k[7:], v) for k, v in S.items() if k.startswith("c.fail:")),
            "c_spec_missing_in_history": S["c.spec_missing_in_history"], "c_no_ac_ids": S["c.no_ac_ids"],
            "d_partial_episodes": S["d.partial_episodes"],
            "d_po_forced_by_engine": S["d.partial_episodes"],
            "d_legacy_po_when_partial": S["d.partial_and_legacy_po"],
            "d_legacy_po_when_clear": S["d.clear_and_legacy_po"],
            "d_stakes_calls_engine_would_make": S["d.stakes_calls"],
            "d_legacy_design_specialist_spawns": S["d.design_specialist_spawns"]},
        "legacy_not_advanced_in_episode": S["a.legacy_not_advanced"],
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:  # fs-ok: measurement output (replay)
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "episodes.json"), "w", encoding="utf-8") as fh:  # fs-ok: measurement output (replay)
        json.dump(eps, fh, ensure_ascii=False, indent=1)
    shutil.rmtree(tmp, True)  # fs-ok: the replay's own mkdtemp
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    s = run(glob.glob(a.logs), a.repo, a.out)
    print(json.dumps(s, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
