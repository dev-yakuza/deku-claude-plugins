"""Helpers for the K4 engine tests (analyze · design · children · the issue FSM): a real temp git repo
as the main checkout, the fake GitHub of K2, canned roles whose artifacts live in a real run dir's
`out/`, canned judges."""

import json
import os

import _util  # noqa: F401
from _k1 import Clock, git, repo, tmpdir  # noqa: F401
from _k2 import CFG, Harness, comment, decision, fixture  # noqa: F401

from guildcore.roles.runner import RoleResult

ROSTER = ("leader", "tech-lead", "developer", "tester", "qa", "product-owner", "designer", "security")
REPO_FILES = {"README.md": "hi\n", "lib/app/home.dart": "class Home {\n  // shows the word list\n  int count() => 3;\n}\n",
              "lib/app/settings.dart": "int s = 1;\n",
              "docs/standards/charter.md": "# Charter\nLearners first: keep every screen offline.\n",
              "docs/standards/conventions.md": "status: confirmed\n# Conventions\nUse const widgets.\n"}
for _r in ROSTER:
    REPO_FILES[".claude/agents/%s.md" % _r] = "---\nmodel: sonnet\n---\n# %s\n" % _r


def main_repo(case, extra=None):
    files = dict(REPO_FILES)
    files.update(extra or {})
    return repo(case, files)


def out_role(case, status="DONE", line=None, files=None, links=None, **extras):
    """A RoleResult whose run dir really holds `out/<files>` (and optional symlinks `links`)."""
    rd = tmpdir(case)
    os.makedirs(os.path.join(rd, "out"))
    for rel, text in (files or {}).items():
        path = os.path.join(rd, "out", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False))
    for rel, dest in (links or {}).items():
        os.symlink(dest, os.path.join(rd, "out", rel))
    return RoleResult(status, line, extras, run_dir=rd)


def evidence(case, areas=("lib/app",)):
    return out_role(case, "DONE", files={
        "evidence.json": {"readings": [{"id": "r1", "summary": "list count", "per_dimension": {}}],
                          "areas": [{"path": a, "irreversible_kinds": []} for a in areas]},
        "evidence.md": "notes"}, evidence_path="out/evidence.json")


def kickoff(goal="clear", constraint="clear", success="clear", ac=("the count shows 3",), anchors=None,
            work_type="feature", cast=None, po=False, ui=False, net_visual=False, areas=("lib/app",),
            close=None, surface=False, plan_decisions=(), untagged=(), extra_ac=()):
    anchors = anchors or {}
    rd = {}
    for dim, r in (("goal", goal), ("constraint", constraint), ("success", success)):
        rd[dim] = {"rating": r, "anchor": anchors.get(dim), "choice_needed": "choose %s" % dim}
    f = {"interpretations": [{"id": "A", "summary": "show the count"}, {"id": "B", "summary": "hide the count"}],
         "chosen": "A", "assumptions": [{"text": "offline only"}], "readiness": rd,
         "plan_decisions": list(plan_decisions), "untagged_premises": list(untagged),
         "close": close or {"decide": "none"}, "features": ["count"],
         "ac": [{"text": t, "priority": "must"} for t in ac] + list(extra_ac),
         "work_type": work_type, "split_hint": False,
         "cast": cast or {"participation": [], "gates": [], "skipped": []}, "po": {"convene": po, "reason": "r"},
         "ui_surface": ui, "safety_net_visual": net_visual, "areas": list(areas),
         "surface_to_human": {"ask": surface}, "verdict": "ready", "security_concern": False}
    bad = [d for d in (goal, constraint, success) if d != "clear"]
    return decision("not_ready" if bad else "ready", f, by="judge:opus")


def took(k, orig):
    """K6 r5 M1: the KICKOFF judge `k` TAKES the person's reading (its interpretation `orig`) the way the brief asks —
    under the fixed engine id `analysis.PERSON_READING_ID`, `chosen` = that id. Returns `k`."""
    from workflows.dev import analysis as AN
    for i in k.fields["interpretations"]:
        if i["id"] == orig:
            i["id"] = AN.PERSON_READING_ID
    k.fields["chosen"] = AN.PERSON_READING_ID
    return k


def stakes(level="low", reason="local to one widget, a revert undoes it"):
    return decision(level, {"level": level, "local_reversible_reason": reason, "cites": []}, by="judge:opus")


ANCHOR_OK = {"cite": "lib/app/home.dart:3", "quote": "int count() => 3;"}
ANCHOR_BAD = {"cite": "lib/app/home.dart:3", "quote": "this text is not in the file"}

ANALYZE_OUT = ("<!-- guild:analyze:output -->\n## Guild analyze — #7\n\nReadiness: Goal=clear · Constraint=clear · "
               "Success=clear\nwork-type: feature\ncast: none\n\n### 수용 기준\n- AC #1: the count shows 3\n"
               "- AC #2: settings stay\n<!-- /guild:analyze:output -->")


class K4(Harness):
    """A K2 Harness whose root is a real git repo (the main checkout) and whose spec store is a temp dir."""

    def __init__(self, case, labels=("guild:analyze",), comments=(), body="Issue body", roles=(), judges=None,
                 unattended=True, config=None, extra_files=None, author="OWNER", issues=None, n=7, prs=(),
                 foreign=()):
        root = main_repo(case, extra_files)
        fx = fixture(labels=labels, comments=comments, body=body, n=n, prs=prs, extra_issues=issues)
        fx["issues"][str(n)]["author_association"] = author
        Harness.__init__(self, case, fx, roles=roles, judges=judges, unattended=unattended, root=root,
                         config=config or CFG, n=n, test_cases=None)
        # K4r3-B1: the engine knows its children by its journal — a real one, and the fixture's child
        # Issues of #n are seeded as created by this engine unless listed in `foreign`
        from guildcore.journal import Journal
        self.common = os.path.join(tmpdir(case), "common")
        self.journal = Journal(self.common, n, self.clock)
        self.writer.journal = self.journal
        self.writer.clock = self.clock
        for k, it in sorted((issues or {}).items(), key=lambda kv: int(kv[0])):
            self.seed_child(int(k), it, foreign)
        self.p.spec_store = os.path.join(tmpdir(case), "specs")
        self.p.git_dir = os.path.join(root, ".git")
        self.events = []

        class Ev(object):
            def emit(_s, what, at, **kw):
                self.events.append((what, kw))
        self.p.events = Ev()

    def seed_child(self, k, it, foreign=()):
        import re as _re
        names = [lb["name"] if isinstance(lb, dict) else lb for lb in it.get("labels", [])]
        if k in foreign or "guild:child" not in names or ("Parent Issue: #%d" % self.n) not in (it.get("body") or ""):
            return
        m = _re.search(r"<!-- guild:slice-key (\S+) -->", it.get("body") or "")
        self.journal.own_write("issue", key=m.group(1) if m else "%d-fx%d" % (self.n, k), number=k, token="fx%d" % k)

    def _judge(self, spec):
        """The fake transport + the group's coercions, as the real JudgeRunner applies them."""
        d = Harness._judge(self, spec)
        import copy
        f = copy.deepcopy(d.fields)
        by = None
        for co in spec.coercions:
            f, b = co(f)
            by = by or b
        if by:
            from guildcore.judges.runner import Decision
            ch = f.get(spec.choice_key, d.choice)
            return Decision(ch, f, d.by, d.digest, d.unsure, True, by, d.choice)
        return d

    def specs(self):
        try:
            return sorted(os.listdir(self.p.spec_store))
        except OSError:
            return []

    def spec(self, name):
        with open(os.path.join(self.p.spec_store, name), encoding="utf-8") as fh:
            return fh.read()

    def decisions_of(self, point):
        from guildcore.decisions import DecisionLog
        return [b for b in DecisionLog.load(self.gh.comments(self.n)).blocks if b.get("point") == point]


def cases_md(ids=(1,), visual=False):
    t = "# cases\n" + "".join("| C%d | AC #%d | case |\n" % (i, i) for i in ids)
    if visual:
        t += "\n## 시각 케이스\n<!-- guild:visual-cases -->\n| home · default · all · phone · AC #1 |\n"
    return t


def tester_ok(case, ids=(1,), visual=False):
    return out_role(case, "DONE", files={"test-cases.md": cases_md(ids, visual)}, covers=[])


def techlead_ok(case, split=None):
    return out_role(case, "DONE", "skeleton at docs/specs/7/skeleton.md — ok",
                    files={"skeleton.md": "# Skeleton\n- [ ] Home.count stays in lib/app\n",
                           "split.json": split or {"split": False}},
                    skeleton="out/skeleton.md", split_path="out/split.json")
