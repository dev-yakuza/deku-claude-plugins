"""Stage-3 test world of session B2: doubles of the other sessions' stage-3 functions.

The driver reaches the functions the sessions B1 / C / D / E implement through `driver.Units`
(stage3/interfaces.md §3); this branch has only their signatures, so each double below is a
small implementation of its CONTRACT (the docstrings of gxengine/catalog.py and ladder.py, the
tables of interfaces.md §3). Everything a double does not override is the real module. No
paid call, no real gh: git is real, gh is c_world.InProcGh, the session machinery is faked.
"""

import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from gxengine import (acparse, catalog as catalogmod, codes, defaults, github, gitops, ladder as laddermod,
                      prbody as prbodymod, procedure as procmod, repoconfig, rules, runner as runnermod, schema,
                      store)
from tests import c_world as W

SPECS = W.SPECS
LA = W.leader_answer


class Delegate:
    """A module double: the attributes set here, else the real module's."""

    def __init__(self, real, **over):
        self._real = real
        for k, v in over.items():
            setattr(self, k, v)

    def __getattr__(self, name):
        return getattr(self._real, name)


# --- B1: catalog ---------------------------------------------------------------------------

def _entry(id, role, cls, outputs=(), checks=(), on_fail=None):
    inputs = ["docs/specs/{issue}/analysis.md", "in:leader-decision.md"]
    if cls == "diff-review":
        inputs = ["in:review.diff"] + inputs
    if cls == "fix":
        inputs = ["in:blocking-discoveries.md"] + inputs
    return {"id": id, "role": role, "class": cls, "inputs": inputs, "outputs": list(outputs),
            "checks": list(checks), "on_fail": on_fail, "summary": f"{id} summary"}


_BACK = {"back_to": "@developer", "max": 2}
CATALOG_RAW = [
    _entry("product-review", "product-owner", "design-time", ["docs/specs/{issue}/product.md"]),
    _entry("ux-design", "designer", "design-time", ["docs/specs/{issue}/ux.md"]),
    _entry("ux-review", "designer", "diff-review", (), ["ux-conformance"], _BACK),
    _entry("security-review", "security", "diff-review", (), ["security-review"], _BACK),
    _entry("data-review", "dba", "diff-review", (), ["data-integrity"], _BACK),
    _entry("i18n-review", "i18n", "diff-review", (), ["i18n-completeness"], _BACK),
    _entry("infra-review", "infra", "diff-review", (), ["infra-safety"], _BACK),
    _entry("fix-discovery", "developer", "fix"),
]


class FakeCatalog(Delegate):
    def __init__(self):
        super().__init__(catalogmod)

    def load(self, path=None):
        return {e["id"]: catalogmod.Entry(e) for e in CATALOG_RAW}

    def requestable_ids(self, catalog):
        return [i for i, e in catalog.items() if e.cls != "fix"]

    def usable_ids(self, catalog, roles_available):
        return [i for i in self.requestable_ids(catalog) if catalog[i].role in roles_available]

    def first_review_index(self, procedure, added=()):
        for i, s in enumerate(procedure.steps):
            if s.is_review and s.id not in added:
                return i
        return None

    def developer_step(self, procedure, added=()):
        end = self.first_review_index(procedure, added)
        out = None
        for s in procedure.steps[:end]:
            if s.role_class == "work" and s.id not in added:
                out = s.id
        return out

    def _gate(self, procedure):
        for kind, name in (("check", "done-gate"), ("op", "create-pr")):
            for i, s in enumerate(procedure.steps):
                if s.kind == kind and s.name == name:
                    return i
        return len(procedure.steps)

    def position(self, procedure, statuses, current, entry, added=()):
        here = procedure.index(current)
        pos = here + 1
        if entry.cls == "design-time":
            dev = self.developer_step(procedure, added)
            if dev is None or procedure.index(dev) <= here or statuses.get(dev) == "done":
                return None
        elif entry.cls == "diff-review":
            first = self.first_review_index(procedure, added)
            if first is not None:
                pos = max(pos, first)
        return pos if pos <= self._gate(procedure) else None

    def expand(self, entry, issue, developer):
        sub = lambda p: p.replace("{issue}", str(issue))  # noqa: E731
        raw = {"id": entry.id, "role": entry.role, "inputs": [sub(i) for i in entry.inputs],
               "outputs": [sub(o) for o in entry.outputs]}
        if entry.on_fail is not None:
            if developer is None:
                raise catalogmod.CatalogError(["no developer step"])
            raw["on_fail"] = {"back_to": developer, "max": entry.on_fail["max"]}
        if entry.checks:
            raw["checks"] = list(entry.checks)
        return raw

    def insert(self, procedure, entry_steps, added=()):
        steps = [s.to_json() for s in procedure.steps]
        for off, (i, raw, entry) in enumerate(sorted(entry_steps, key=lambda x: x[0])):
            steps.insert(i + off, copy.deepcopy(raw))
        for _, raw, entry in entry_steps:
            if entry.cls != "design-time":
                continue
            at = next(n for n, s in enumerate(steps) if s["id"] == raw["id"])
            for s in steps[at + 1:]:
                if "role" in s:
                    s["inputs"] = list(s.get("inputs", [])) + [o for o in raw["outputs"] if o not in s.get("inputs", [])]
        return steps

    def evaluate_requests(self, catalog, procedure, statuses, current, requests, *, roles_available, adds_used,
                          added=(), start_steps=(), limit=defaults.CATALOG_ADDS_MAX):
        D = catalogmod.Decision
        out, put = [], []
        dev = self.developer_step(procedure, added)
        have = set(procedure.step_ids)
        for q in requests:
            if q["op"] != "add":
                out.append(D(q, "pending", "removal"))
                continue
            entry = catalog[q["step"]]
            if current in start_steps:
                out.append(D(q, "deferred-to-plan"))
            elif entry.role not in roles_available:
                out.append(D(q, "declined", "role-unavailable"))
            elif entry.id in have:
                out.append(D(q, "noop", "already-present"))
            else:
                pos = self.position(procedure, statuses, current, entry, added)
                if pos is None:
                    out.append(D(q, "declined", "position"))
                elif adds_used + len(put) >= limit:
                    out.append(D(q, "pending", "limit"))
                else:
                    have.add(entry.id)
                    put.append((pos, self.expand(entry, procedure.issue, dev), entry))
                    out.append(D(q, "applied"))
        return out, (self.insert(procedure, put, added) if put else None)

    def skippable_steps(self, procedure, statuses, catalog_adds, requests):
        named = {q["step"] for q in requests if q["op"] in ("remove", "skip")}
        ok = {a["step"] for a in catalog_adds if a["source"] != "mandatory-rule"}
        return [i for i in procedure.step_ids if i in named and i in ok and statuses.get(i) != "done"]


# --- B1: procedure, rules, repoconfig, acparse --------------------------------------------------

_REAL_CHECK = procmod.check
_TOKENS = {codes.path_token(k): k for k in codes.TEMPLATE_PATH_KINDS}


class FakeProcedure(Delegate):
    def __init__(self):
        super().__init__(procmod)

    def check(self, procedure, commands, stage=3):
        errs = _REAL_CHECK(procedure, commands, stage=stage)
        ids = [s.name if s.kind == "op" else None for s in procedure.steps]
        if "create-followups" in ids:
            errs = [e for e in errs if e != "op create-pr must be the last step"]
            if ids.count("create-followups") > 1 or ids[-2:] != ["create-pr", "create-followups"]:
                errs.append("op create-followups must come right after op create-pr, once")
        return errs

    def parse_procedure(self, text, commands=None, stage=3):
        proc = procmod.Procedure(json.loads(text))
        errs = self.check(proc, commands, stage=stage)
        if errs:
            raise procmod.ProcedureError(errs)
        return proc

    def expand_paths(self, template, path_globs):
        t = copy.deepcopy(template)
        for s in t["steps"]:
            for key in ("inputs", "outputs"):
                out = []
                for p in s.get(key, []):
                    if p in _TOKENS:
                        if not path_globs.get(_TOKENS[p]):
                            raise procmod.ProcedureError([f"no path rule of kind {_TOKENS[p]}"])
                        out += path_globs[_TOKENS[p]]
                    else:
                        out.append(p)
                if key in s:
                    s[key] = out
        return t

    def parse_template(self, text, stage=3):
        raw = json.loads(text)
        errs = schema.errors(raw, schema.load_schema("template"))
        if errs:
            raise procmod.ProcedureError(errs)
        procmod.parse_template(json.dumps(self.expand_paths(raw, {k: ["x/**"] for k in codes.TEMPLATE_PATH_KINDS})),
                               stage=stage)
        return raw

    def _joined(self, procedure, template, commands, path_globs):
        t = self.expand_paths(template, path_globs)
        raw = procedure.to_json()
        raw["steps"] = [s.to_json() for s in procedure.steps] + procmod._substituted(t["steps"], procedure.issue)
        raw["revision"] = procedure.revision + 1
        raw["origin"] = {"template": t["template"], "version": t["version"], "start": procedure.origin["start"]}
        return procmod.Procedure(raw)

    def template_problems(self, start, template, issue, commands, path_globs, stage=3):
        try:
            new = self._joined(procmod.build_start(start, issue, commands, stage=stage), template, commands, path_globs)
        except procmod.ProcedureError as e:
            return list(e.errors)
        return self.check(new, commands, stage=stage)

    def attach_plan(self, procedure, template, commands, *, path_globs, catalog, adjust, candidate):
        new = self._joined(procedure, template, commands, path_globs)
        cat = FakeCatalog()
        put, ids = [], []
        for a in adjust or ():
            entry = catalog[a["step"]]
            pos = cat.position(new, {}, "plan", entry)
            if pos is None:
                raise procmod.ProcedureError([f"no position for {entry.id}"])
            put.append((pos, cat.expand(entry, new.issue, cat.developer_step(new)), entry))
            ids.append(entry.id)
        raw = new.to_json()
        if put:
            raw["steps"] = cat.insert(new, put)
        raw["new_template_candidate"] = bool(candidate)
        new = procmod.Procedure(raw)
        errs = self.check(new, commands, stage=3)
        if errs:
            raise procmod.ProcedureError(errs)
        return new, ids


class FakeRules(Delegate):
    def __init__(self, procs):
        super().__init__(rules)
        self.procs = procs
        self.calls = []

    def evaluate(self, proc, state, config, changed, issue, roles_available=None, stage=2, catalog=None):
        self.calls.append({"stage": stage, "catalog": catalog})
        return rules.evaluate(proc, state, config, changed, issue, roles_available)

    def apply(self, proc, state, sup, commands=None, stage=1):
        with mock.patch.object(procmod, "check", self.procs.check):
            return rules.apply(proc, state, sup, commands=commands, stage=stage)


class Config(repoconfig.RepoConfig):
    def path_globs(self, kind):
        value = getattr(kind, "value", kind)
        return [g for r in self.path_rules(value) for g in r["globs"]]

    def irreversible_level(self, category, rule=None):
        default = defaults.IRREVERSIBLE_DEFAULT_LEVEL[category]
        level = (rule or {}).get("level") or (self.raw.get("irreversible_levels") or {}).get(category) or default
        order = defaults.IRREVERSIBLE_LEVEL_ORDER
        return level, default, order.index(level) < order.index(default)

    def followups_dry_run(self):
        return bool(self.raw.get("followups_dry_run", defaults.FOLLOWUPS_DRY_RUN_DEFAULT))


def parse_analysis(text, stage=2):
    net = "none"
    keep = []
    for line in text.split("\n"):
        if line.startswith("safety_net:"):
            net = line.split(":", 1)[1].strip()
        else:
            keep.append(line)
    an = acparse.parse_analysis("\n".join(keep))
    an["safety_net"] = net
    return an


# --- C: ladder, results, facts, runner, session ----------------------------------------------------

class FakeLadder(Delegate):
    def __init__(self, resume_effort_change=None):
        super().__init__(laddermod)
        # Q4 (Z3): by default the real ladder's rule (an effort-only raise keeps --resume)
        self.resume_effort_change = laddermod.EFFORT_CHANGE_RESUMES if resume_effort_change is None \
            else resume_effort_change

    def effort_ladder(self, allowed):
        return [e for e in defaults.EFFORT_LADDER if e in allowed]

    def model_ladder(self, allowed):
        return [m for m in defaults.MODEL_LADDER if m in allowed]

    def raisable(self, step):
        return step.kind == "role" and not step.checks

    def base_choice(self, step, stage, overrides):
        o = (overrides or {}).get(step.id)
        if o:
            return {"model": o["model"], "effort": o["effort"], "layer": o["layer"]}
        table = defaults.model_effort_table(stage)
        for k in ([f"{step.name}/review"] if step.is_review else [f"{step.name}/{step.id}"]) + [step.name]:
            if k in table:
                return {"model": table[k][0], "effort": table[k][1], "layer": "plugin-default"}
        raise laddermod.LadderError(f"no layer-1 default for {step.name}/{step.id}")

    def raised(self, base, returns, allowed_models, allowed_efforts):
        out = {"model": base["model"], "effort": base["effort"]}
        up, capped = {"effort": None, "model": None}, False
        for key, at, rungs in (("effort", defaults.RAISE_EFFORT_AT, self.effort_ladder(allowed_efforts)),
                               ("model", defaults.RAISE_MODEL_AT, self.model_ladder(allowed_models))):
            if base[key] not in rungs:
                raise laddermod.LadderError(f"{key} {base[key]!r} is not on the ladder {rungs}")
            if returns >= at:
                i = rungs.index(base[key])
                if i + 1 < len(rungs):
                    up[key] = [base[key], rungs[i + 1]]
                    out[key] = rungs[i + 1]
                else:
                    capped = True
        out["escalation"] = {"base": dict(base), "returns": returns, "raised": up, "capped": capped}
        return out

    def count_return(self, sstate, cause, sources=()):
        codes.ReturnCause(cause)
        sstate["returns"] = sstate.get("returns", 0) + 1
        sstate["return_sources"] = [{"step": s, "attempt": n, "cause": cause} for s, n in sources]

    def may_resume(self, previous, chosen):
        if previous["model"] != chosen["model"]:
            return False
        return self.resume_effort_change or previous["effort"] == chosen["effort"]


class FakeResults(W.FakeResults):
    def result_schema(self, kind, stage, catalog_steps):
        return schema.fill_enums(schema.load_schema(codes.result_schemas(stage)[kind]),
                                 {"{catalog_steps}": list(catalog_steps)})

    def judge_role(self, procedure, step, brief, result, facts, quota_reset_at=None, stage=2, catalog_steps=(),
                   owned=None):
        self.judged = getattr(self, "judged", []) + [{"step": step.id, "stage": stage,
                                                      "catalog_steps": list(catalog_steps), "owned": owned}]
        return self._next(step.id)

    def owned_files(self, paths, procedure):
        """results.owned_files (session C, K2) — the Q4 driver passes it as `owned=`; {} = by globs."""
        return {}

    def add_boundary_facts(self, ctx, procedure, state, step, facts, procedure_commit, owner_facts=None, owned=None):
        return super().add_boundary_facts(ctx, procedure, state, step, facts, procedure_commit, owner_facts)


class FakeFacts(W.FakeFacts):
    def __init__(self, files=None):
        self.files = files
        self.step_files_calls = []

    def finish_facts(self, ctx, start, procedure, step, session=None, run=None, config=None, stage=2):
        return super().finish_facts(ctx, start, procedure, step, session=session, run=run)

    def step_files(self, paths, step_id, globs):
        self.step_files_calls.append((step_id, list(globs)))
        return self.files or {"attempts": [1], "net": {}, "owned": [], "outside": []}


class FakeRunner(W.FakeRunner):
    """`runs[step id]` = list of extra keys of the facts `run` object (the last repeats)."""

    evidence_author = staticmethod(runnermod.evidence_author)      # session C's (the Q4 driver asks it)

    def __init__(self, codes_by_step=None, runs=None):
        super().__init__(codes_by_step)
        self.runs = runs or {}
        self.s3 = []

    def run_step(self, ctx, config, procedure, step, attempt_dir, base_env, srt_bin, plugin_root, *, issue, attempt,
                 paths, prepare_tree=None, control_check=None, stage=2, step_files=None, path_globs=None,
                 plugin_args=()):
        n = sum(1 for c in self.s3 if c["step"] == step.id)
        self.s3.append({"step": step.id, "stage": stage, "step_files": step_files, "path_globs": path_globs,
                        "plugin_args": list(plugin_args)})
        sr = super().run_step(ctx, config, procedure, step, attempt_dir, base_env, srt_bin, plugin_root, issue=issue,
                              attempt=attempt, paths=paths, prepare_tree=prepare_tree, control_check=control_check)
        seq = self.runs.get(step.id)
        if seq:
            extra = copy.deepcopy(seq[min(n, len(seq) - 1)])
            for name, text in extra.pop("logs", {}).items():
                with open(os.path.join(attempt_dir, name), "w", encoding="utf-8") as f:
                    f.write(text)
            sr.run.update(extra)
        return sr


class FakeSession(W.FakeSession):
    def run_session(self, inp, attempt_dir, base_env, claude_bin="claude", limits=None, version=None, budget_key=None,
                    stage=2):
        n = len(self.calls)
        got = super().run_session(inp, attempt_dir, base_env, claude_bin=claude_bin, limits=limits, version=version,
                                  budget_key=budget_key)
        self.calls[n].update({"model": inp.model, "effort": inp.effort, "stage": stage, "json_schema": inp.json_schema,
                              "max_budget_usd": inp.max_budget_usd, "role": inp.role})
        return got


# --- E: github, gitops, prbody --------------------------------------------------------------------

class FakeGithub(Delegate):
    """GitHub of acme/app for the stage-3 functions: `issues` {number: {...}}, `calls` in order.

    `fail` = {function name: n} raises GhError from its n-th call on (1-based)."""

    def __init__(self, private=True, candidates=(), labels=("type:bug", "type:refactor", "type:docs", "type:feature"),
                 reviews=()):
        super().__init__(github)
        self.private = private
        self.candidates = list(candidates)
        self.labels = set(labels)
        self.reviews = list(reviews)
        self.calls = []
        self.issues = {}
        self.fail = {}

    def _call(self, fn, **kw):
        self.calls.append(dict(kw, fn=fn))
        n = sum(1 for c in self.calls if c["fn"] == fn)
        if self.fail.get(fn) and n >= self.fail[fn]:
            raise github.GhError(f"fake {fn} failed")

    def names(self):
        return [c["fn"] for c in self.calls]

    def repo_is_private(self, gh):
        self._call("repo_is_private")
        if self.private is None:
            raise github.GhError("unknown visibility")
        return self.private

    def followup_candidates(self, gh, limit):
        self._call("followup_candidates", limit=limit)
        return copy.deepcopy(self.candidates[:limit])

    def label_names(self, gh):
        self._call("label_names")
        return set(self.labels)

    def find_followup(self, gh, marker):
        self._call("find_followup", marker=marker)
        return next((n for n, i in self.issues.items() if i["marker"] == marker), None)

    def create_followup(self, gh, title, body, labels, marker):
        found = self.find_followup(gh, marker)           # github.create_followup searches the marker first
        if found is not None:
            return {"number": found, "url": None, "created": False}
        self._call("create_followup", title=title, body=body, labels=list(labels), marker=marker)
        n = 900 + len(self.issues)
        self.issues[n] = {"title": title, "body": body, "labels": list(labels), "marker": marker}
        return {"number": n, "url": f"https://github.com/acme/app/issues/{n}", "created": True}

    def comment_followup(self, gh, number, body, marker):
        self._call("comment_followup", number=number, body=body, marker=marker)
        return 7000 + len(self.calls)

    def add_label(self, gh, number, name):
        self._call("add_label", number=number, name=name)

    def apply_followups(self, gh, items, **kw):
        """Session E's real github.apply_followups (Q4 wiring) over this fake's GitHub functions."""
        with mock.patch.multiple(github, label_names=self.label_names, create_followup=self.create_followup,
                                 comment_followup=self.comment_followup,
                                 ensure_label=lambda gh, name, known: known.add(name)):
            return github.apply_followups(gh, items, **kw)

    def update_pr(self, gh, number, body, closes):
        self._call("update_pr", number=number, body=body, closes=closes)

    def pr_review_items(self, gh, pr, last_seen_ids, engine_comment_ids):
        self._call("pr_review_items", pr=pr, last_seen_ids=dict(last_seen_ids))
        out = []
        for i in self.reviews:
            kind, n = i["id"].split(":")
            if (last_seen_ids.get(kind) or 0) < int(n):
                out.append(dict(i))
        return out

    def build_pr_review_md(self, items):
        return "".join(f"{i['id']}: {i['body']}\n" for i in items)


def fast_forward(ctx):
    """gitops.fast_forward's contract, with real git."""
    gitops.fetch(ctx)
    old = gitops.head(ctx)
    new = gitops.git(ctx, "rev-parse", f"refs/remotes/origin/{ctx.branch}").strip()
    if old == new or gitops.is_forward(ctx, new, old):
        return None
    if not gitops.is_forward(ctx, old, new):
        raise gitops.GitError("diverged")
    gitops.git(ctx, "merge", "--ff-only", "-q", new)
    n = int(gitops.git(ctx, "rev-list", "--count", f"{old}..{new}").strip())
    return {"from": old, "to": new, "commits": n}


class FakePrbody(W.FakePrbody):
    def build(self, procedure, state, facts_by_step, results_by_step, config, qa_checklist, analysis, **kw):
        self.stage3 = getattr(self, "stage3", []) + [kw.get("stage3")]
        return super().build(procedure, state, facts_by_step, results_by_step, config, qa_checklist, analysis)

    # session E's real work list and security record (Q4: the driver runs E's create-followups pipeline)
    followup_items = staticmethod(prbodymod.followup_items)
    security_findings_md = staticmethod(prbodymod.security_findings_md)

    def summary_stage3_lines(self, state, security_count=0):
        out = []
        if (state.get("irreversible") or {}).get("detected"):
            out.append(f"- irreversible: {len(state['irreversible']['detected'])}")
        return out


# --- D: leader ------------------------------------------------------------------------------------

class FakeRequest:
    def __init__(self, **fields):
        self.__dict__.update(fields)

    def __getattr__(self, name):        # like leader.LeaderRequest: an unset field is None
        return None


class FakeLeader(W.FakeLeader):
    LeaderRequest = FakeRequest

    def _session(self, req):
        n = super()._session(req)
        act = self.script.get(req.situation) or []
        i = min(sum(1 for c in self.calls if c["situation"] == req.situation) - 1, len(act) - 1)
        a = act[i] if act else {}
        if "answer" in a:
            obj = dict({"answer": a["answer"], "note": a["note"], "step": a["step"], "reason": a["reason"]},
                       **{k: v for k, v in a["extra"].items() if k != "_input"})
            root = store._root(req.paths)
            if req.kind == "check":
                store.write_result(req.paths, req.step, n, obj)
                if a.get("extra", {}).get("_input"):
                    store.write_in_file(req.paths, req.step, n, "leader-input.json", json.dumps(a["extra"]["_input"]))
            else:
                from gxengine import fsafe
                fsafe.write_json(os.path.join(req.paths.leader_dir(n), "result.json"), obj, root=root)
        return n

    def call(self, req):
        res = super().call(req)
        res.extra.pop("_input", None)
        seq = self.script.get(req.situation) or []
        i = min(sum(1 for c in self.calls if c["situation"] == req.situation) - 1, len(seq) - 1)
        if seq and seq[i].get("input") is not None:
            res.input = seq[i]["input"]
        return res


# --- templates and the world ---------------------------------------------------------------------

def tail_steps():
    return [{"id": "done-gate", "check": "done-gate", "inputs": ["in:issue.md", "in:review.diff", "in:leader-decision.md",
                                                                "docs/specs/{issue}/analysis.md"]},
            {"id": "pr", "op": "create-pr", "inputs": ["docs/specs/{issue}/analysis.md"]},
            {"id": "followups", "op": "create-followups"}]


def review_step(id="review", role="tester", back="implement"):
    return {"id": id, "role": role, "inputs": ["in:review.diff", "docs/specs/{issue}/analysis.md", "in:leader-decision.md"],
            "outputs": [], "checks": ["test-quality"], "on_fail": {"back_to": back, "max": 2}}


def feature_steps():
    return [
        {"id": "design", "role": "tech-lead", "inputs": ["docs/specs/{issue}/analysis.md", "in:failure-summary.md",
                                                        "in:leader-decision.md"],
         "outputs": ["docs/specs/{issue}/skeleton.md"]},
        {"id": "implement", "role": "developer", "inputs": ["docs/specs/{issue}/analysis.md", "in:failure-summary.md",
                                                           "in:blocking-discoveries.md", "in:leader-decision.md"],
         "outputs": [], "on_fail": {"back_to": "implement", "max": 2}},
        {"id": "test", "run": "test", "on_fail": {"back_to": "implement", "max": 2}},
        review_step(),
    ] + tail_steps()


def bug_steps():
    return [
        {"id": "reproduce", "role": "developer", "inputs": ["docs/specs/{issue}/analysis.md", "in:failure-summary.md"],
         "outputs": ["{path:test-code}"], "on_fail": {"back_to": "reproduce", "max": 2}},
        {"id": "repro-red", "run": "repro-red", "on_fail": {"back_to": "reproduce", "max": 2}},
        {"id": "fix", "role": "developer", "inputs": ["docs/specs/{issue}/analysis.md", "in:repro-evidence.md",
                                                     "in:blocking-discoveries.md", "in:failure-summary.md"],
         "outputs": [], "on_fail": {"back_to": "fix", "max": 2}},
        {"id": "test", "run": "test", "on_fail": {"back_to": "fix", "max": 2}},
        review_step(back="fix"),
    ] + tail_steps()


def refactor_steps():
    return [{"id": "transform", "role": "developer", "inputs": ["docs/specs/{issue}/analysis.md"], "outputs": [],
             "on_fail": {"back_to": "transform", "max": 2}},
            {"id": "test", "run": "test", "on_fail": {"back_to": "transform", "max": 2}},
            review_step(back="transform")] + tail_steps()


def tpl(name, steps):
    return json.dumps({"format": 1, "template": name, "version": f"s3-{name}-1", "steps": steps}, indent=2) + "\n"


TEST_CODE = {"kind": "test-code", "globs": ["tests/test_*.py"]}
SAFETY_NET = {"kind": "safety-net", "globs": ["tests/net_*.py"]}


def config(path_rules=None, **extra):
    c = {"format": 1,
         "commands": {"ac-format": {"plugin": "ac-format"}, "test": {"cmd": "true"},
                      "repro-red": {"plugin": "repro-red"}},
         "path_rules": [TEST_CODE, SAFETY_NET] if path_rules is None else path_rules,
         "registry_hosts": ["registry.npmjs.org"]}
    c.update(extra)
    return c


AGENTS = ("designer", "security", "dba", "product-owner", "infra")


def extra_files(templates=None):
    out = {f".claude/agents/{r}.md": f"---\nname: {r}\n---\nYou are {r}.\n" for r in AGENTS}
    t = {"feature": feature_steps(), "bug": bug_steps(), "refactor": refactor_steps(),
         "refactor-net": refactor_steps(), "safety-net": refactor_steps()}
    t.update(templates or {})
    for name, steps in t.items():
        if steps is not None:
            out[f".claude/guild/procedures/{name}.yaml"] = tpl(name, steps)
    return out


def analysis(type="feature", safety_net="none", risk="low"):
    return W.ANALYSIS.replace("type: feature", f"type: {type}\nsafety_net: {safety_net}").replace(
        "risk: low", f"risk: {risk}")


def plan_ok(template="feature", adjust=(), models=(), candidate=False, reason="fits-template", **kw):
    return LA("plan", reason=reason, requirements=[{"row": "R1", "covered": True}], missing_requirements=[],
              plan={"template": template, "adjust": list(adjust), "models": list(models),
                    "new_template_candidate": candidate}, close=None, **kw)


def approve(discoveries=(), included_fixes=(), inp=None, note="", reason="acceptance-met"):
    kw = {"_input": inp} if inp is not None else {}
    return LA("approve", reason=reason, note=note, discoveries=list(discoveries),
              included_fixes=list(included_fixes), **kw)


def request(step, op="add", trigger="ui-change", note=""):
    return {"op": op, "step": step, "trigger": trigger, "note": note}


def discovery(kind="bug", where="src/app.py", note="n", blocks=False):
    return {"kind": kind, "where": where, "note": note, "blocks_current_ac": blocks}


def result(**kw):
    out = {"status": "done", "blocked_by": None, "requests": [], "discoveries": [], "irreversible": []}
    out.update(kw)
    return out


def steps_of(state):
    return {s["id"]: s["status"] for s in state["steps"]}


class Stage3(unittest.TestCase):
    """One acme/app world; `run3` = one engine run at stage 3 with every double above."""

    cfg = None
    templates = None
    extra = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        files = extra_files(self.templates)
        files.update(self.extra or {})
        self.w = W.World(self._tmp.name, steps=feature_steps(), cfg=self.cfg or config(), extra_files=files)
        self.gh = FakeGithub()
        self.catalog = FakeCatalog()
        self.procs = FakeProcedure()
        self.rules = FakeRules(self.procs)
        self.ladder = FakeLadder()
        self.prbody = FakePrbody()
        self.facts = FakeFacts()
        self.session = None
        self.runner = None

    def tearDown(self):
        self._tmp.cleanup()

    def actions(self, **over):
        base = {"analyze": [{"write": {f"{SPECS}/analysis.md": analysis()}, "structured": result()}],
                "design": [{"write": {f"{SPECS}/skeleton.md": "s\n"}, "structured": result()}],
                "implement": [{"write": {"src/app.py": "x = 2\n"}, "commit": "feat: quiz type",
                               "structured": result()}],
                "review": [{"structured": result()}]}
        base.update({k.replace("_", "-"): v for k, v in over.items()})
        return base

    def leader(self, script=None, **kw):
        base = {"plan-gate": [plan_ok()], "done-gate": [approve()]}
        base.update(script or {})
        return FakeLeader(self.w, base, **kw)

    def units(self, leader, session=None, **over):
        self.session = session or self.session or FakeSession(self.w, self.actions())
        self.runner = over.pop("runner", None) or self.runner or FakeRunner()
        self.results = over.pop("results", None) or getattr(self, "results", None) or FakeResults()
        kw = dict(session=self.session, results=self.results, runner=self.runner, prbody=self.prbody, facts=self.facts,
                  leader=leader, catalog=self.catalog, ladder=self.ladder, procedure=self.procs, rules=self.rules,
                  github=self.gh, gitops=Delegate(gitops, fast_forward=fast_forward),
                  repoconfig=Delegate(repoconfig, RepoConfig=Config),
                  acparse=Delegate(acparse, parse_analysis=parse_analysis))
        kw.update(over)
        return W.units(self.w, **kw)

    def run3(self, leader, answer=None, mode="attended", session=None, **over):
        return self.w.run(self.units(leader, session=session, **over), answer=answer, stage=3, mode=mode)

    def sess(self, **actions):
        return FakeSession(self.w, self.actions(**actions))

    def state(self):
        return self.w.state()

    def log(self, event=None):
        return [l for l in self.w.log() if event is None or l["event"] == event]

    def in_file(self, step, attempt, name):
        with open(os.path.join(self.w.paths().in_dir(step, attempt), name), encoding="utf-8") as f:
            return f.read()

    def brief(self, step, attempt):
        with open(self.w.paths().attempt_file(step, attempt, "brief.json"), encoding="utf-8") as f:
            return json.load(f)

    def procedure(self):
        with open(os.path.join(self.w.worktree, SPECS, "procedure.yaml"), encoding="utf-8") as f:
            return json.load(f)

    def sstep(self, step_id):
        return next(s for s in self.state()["steps"] if s["id"] == step_id)

    def ok(self, rc):
        self.assertEqual(rc, 0, self.w.out.getvalue() + json.dumps(self.state().get("stop") if self.state() else None))
