"""P3-C test world: a temp repository + bare remote, fake gh, and fake P3-A/P3-B units.

The driver reaches session / facts / results / runner / prbody through `driver.Units`;
while those modules are stubs (P3-A, P3-B) the driver tests plug in the fakes below. The
fakes are deliberately simple and deterministic: a scripted session writes files in the
worktree (and commits for the developer), facts are read from real git, results return
scripted Outcomes. Nothing here calls the real `claude` or `gh`.
"""

import fnmatch
import io
import json
import os
import subprocess
import time

from gxengine import codes, driver, fsafe, github, gitops, leader as leadermod, statemachine, store
from tests.helpers import fakes
from tests.helpers.gitrepo import GitRepo

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.realpath(os.path.join(ENGINE, "..", "..", ".."))
REPO = "acme/app"
ISSUE = 42
SPECS = f"docs/specs/{ISSUE}"

ANALYSIS = """# Analysis — #42

type: feature
size: small
risk: low
split: none
prerequisite: none

## Acceptance criteria

- AC #1: The settings screen shows a quiz type row. [must]

## Requirement map

| Issue requirement | AC |
|---|---|
| Show the quiz type | AC #1 |

## Assumptions

- The existing selector sheet is reused.
"""

START_STEPS = ["analyze", "ac-format", "plan"]


def template(steps=None):
    """A short feature template: implement → test → review → pr (or `steps`)."""
    if steps is None:
        steps = [
            {"id": "implement", "role": "developer",
             "inputs": [f"docs/specs/{{issue}}/analysis.md", "in:failure-summary.md", "in:leader-decision.md"],
             "outputs": [], "on_fail": {"back_to": "implement", "max": 2}},
            {"id": "test", "run": "test", "on_fail": {"back_to": "implement", "max": 2}},
            {"id": "review", "role": "tester",
             "inputs": ["in:review.diff", "docs/specs/{issue}/analysis.md", "in:leader-decision.md"],
             "outputs": [], "checks": ["test-quality"], "on_fail": {"back_to": "implement", "max": 2}},
            {"id": "pr", "op": "create-pr", "inputs": ["docs/specs/{issue}/analysis.md"]},
        ]
    return {"format": 1, "template": "feature", "version": "c-test-1", "steps": steps}


def stage2_steps():
    """The template above with the stage-2 done-gate right before create-pr (D19)."""
    steps = template()["steps"]
    steps.insert(len(steps) - 1, {"id": "done-gate", "check": "done-gate",
                                  "inputs": ["in:issue.md", "in:review.diff", "in:leader-decision.md",
                                             "docs/specs/{issue}/analysis.md"]})
    return steps


def config(extra=None):
    c = {"format": 1,
         "commands": {"ac-format": {"plugin": "ac-format"}, "test": {"cmd": "true"}},
         "path_rules": [{"kind": "verification", "globs": ["tests/**"]}],
         "registry_hosts": ["registry.npmjs.org"]}
    c.update(extra or {})
    return c


def gh_rules(issue_state="OPEN", labels=(), comments_seq=None, title="Show the quiz type"):
    """Fake-gh rules for one Issue. `comments_seq` = list of comment lists, one per read
    (the last one repeats) — a new collaborator comment appears when the list grows."""
    rules = [
        {"args": ["repo", "view", REPO, "--json", "defaultBranchRef"], "json": {"defaultBranchRef": {"name": "main"}}},
        {"args": ["issue", "view", str(ISSUE), "--repo", REPO, "--json", "number,title,body,labels,state,stateReason,createdAt"],
         "json": {"number": ISSUE, "title": title, "body": "Please show the quiz type.", "state": issue_state,
                  "stateReason": None, "labels": [{"name": n} for n in labels]}},
    ]
    seq = comments_seq or [[]]
    for i, cs in enumerate(seq):
        rule = {"args": ["api", f"repos/{REPO}/issues/{ISSUE}/comments", "--paginate"], "stdout": json.dumps(cs) + "\n"}
        if i < len(seq) - 1:
            rule["times"] = 1
        rules.append(rule)
    for n in range(60):
        rules.append({"args": ["api", "-X", "POST", f"repos/{REPO}/issues/{ISSUE}/comments", "--input", "-"],
                      "json": {"id": 5001 + n}, "times": 1})
    rules += [
        {"args": ["api", "-X", "PATCH", f"repos/{REPO}/issues/comments/5001", "--input", "-"], "json": {"id": 5001}},
        {"args": ["api", f"repos/{REPO}/labels/*"], "json": {"name": "guild:x"}},
        {"args": ["api", f"repos/{REPO}/issues/{ISSUE}/labels"], "json": []},
        {"args": ["api", "-X", "POST", f"repos/{REPO}/issues/{ISSUE}/labels", "--input", "-"], "json": []},
        {"args": ["api", "-X", "DELETE", f"repos/{REPO}/issues/{ISSUE}/labels/*"], "json": []},
        {"args": ["api", f"repos/{REPO}/pulls?head=*"], "json": []},
        # readiness T1 P2: a stage-4 start reads the open pull requests that close the Issue (none here)
        {"args": ["pr", "list", "--repo", REPO, "--state", "open", "--limit", "*", "--json",
                  "number,headRefName,body,closingIssuesReferences"], "json": []},
        {"args": ["api", "-X", "POST", f"repos/{REPO}/pulls", "--input", "-"],
         "json": {"number": 77, "html_url": f"https://github.com/{REPO}/pull/77"}},
    ]
    return {"rules": rules}


def collab(cid, body="Correction: iOS only.", assoc="MEMBER"):
    return {"id": cid, "user": {"login": "member"}, "author_association": assoc, "body": body,
            "created_at": "2026-11-23T02:00:00Z"}


class InProcGh(github.Gh):
    """github.Gh with the fake-gh rule semantics in process (no subprocess per call).

    Same rule file as tests/fakes/bin/gh; the outbound secret scan still runs the real
    plugin scanner. `calls` = [{argv, stdin, rule}]."""

    def __init__(self, repo, rules_file, plugin_root):
        self.repo = repo
        self.owner = repo.split("/", 1)[0]
        self.env = {}
        self.bin = "in-process-fake-gh"
        self.plugin_root = plugin_root
        self.rules_file = rules_file
        self.uses = {}
        self.calls = []

    def call(self, *args, input=None):
        with open(self.rules_file, encoding="utf-8") as f:
            rules = json.load(f)["rules"]
        argv = list(args)
        chosen = None
        for i, r in enumerate(rules):
            pat = r["args"]
            if len(pat) != len(argv) or not all(fnmatch.fnmatchcase(a, p) for a, p in zip(argv, pat)):
                continue
            if r.get("times") is not None and self.uses.get(i, 0) >= r["times"]:
                continue
            chosen = i
            break
        self.calls.append({"argv": argv, "stdin": input, "rule": chosen})
        if chosen is None:
            raise github.GhError(f"fake gh: no fixture rule matches {argv}", args, 1, "no fixture")
        self.uses[chosen] = self.uses.get(chosen, 0) + 1
        r = rules[chosen]
        if r.get("exit_code"):
            raise github.GhError(f"gh {' '.join(argv[:4])}: rc={r['exit_code']}", args, r["exit_code"],
                                 r.get("stderr", ""))
        if "json" in r:
            return json.dumps(r["json"]) + "\n"
        return r.get("stdout", "")


class World:
    """One temp repository `acme/app` (main checkout `<tmp>/app`, bare remote) + engine env."""

    @classmethod
    def attach(cls, tmp):
        """The World of an existing temp folder (another process created it)."""
        w = cls.__new__(cls)
        w.tmp = os.path.realpath(tmp)
        w.repo = GitRepo(w.tmp, os.path.join(w.tmp, "app"), os.path.join(w.tmp, "app.git"))
        w._paths_only()
        w.gh = None
        return w

    def _paths_only(self):
        self.home = os.path.join(self.tmp, "home")
        self.engine_home = os.path.join(self.tmp, "gld")
        self.gh_file = os.path.join(self.tmp, "gh.json")
        self.gh_log = os.path.join(self.tmp, "ghlog")
        base = dict(self.repo.env)
        base.update({"HOME": self.home, "GLD_ENGINE_HOME": self.engine_home,
                     "CLAUDE_CONFIG_DIR": os.path.join(self.home, ".claude-x")})
        self.environ = fakes.fake_env(base=base, gh_fixtures=self.gh_file, gh_log=self.gh_log)
        self.worktree = os.path.join(self.tmp, f".gld-app-{ISSUE}")
        self.out = io.StringIO()
        self.subprocess_gh = False

    def make_gh(self, repo, environ, plugin_root):
        if self.subprocess_gh:
            return github.Gh(repo, env=environ, plugin_root=plugin_root)
        self.gh = InProcGh(repo, self.gh_file, plugin_root)
        return self.gh

    def __init__(self, tmp, steps=None, cfg=None, extra_files=None, gh=None):
        self.tmp = os.path.realpath(tmp)
        files = {
            "README.md": "app\n",
            "src/app.py": "x = 1\n",
            "tests/test_app.py": "def test_x():\n    assert True\n",
            "CLAUDE.md": "Repository rules.\n",
            ".claude/guild/config.json": json.dumps(cfg or config(), indent=2) + "\n",
            ".claude/guild/procedures/feature.yaml": json.dumps(template(steps), indent=2) + "\n",
            ".claude/agents/developer.md": "---\nname: developer\n---\nYou develop.\n",
            ".claude/agents/tester.md": "---\nname: tester\n---\nYou test.\n",
            ".claude/agents/tech-lead.md": "---\nname: tech-lead\n---\nYou lead.\n",
            ".claude/agents/qa.md": "---\nname: qa\n---\nYou check.\n",
        }
        files.update(extra_files or {})
        self.repo = GitRepo.create(self.tmp, name="app", files=files)
        self._paths_only()
        os.makedirs(os.path.join(self.home, ".claude-x"))
        self.gh = None
        self.set_gh(gh or gh_rules())

    def set_gh(self, rules):
        """Replace the gh rules (use counts start again)."""
        with open(self.gh_file, "w", encoding="utf-8") as f:
            json.dump(rules, f)
        uses = os.path.join(self.gh_log, "uses.json")
        if os.path.exists(uses):
            os.unlink(uses)
        if self.gh is not None:
            self.gh.uses = {}

    def gh_calls(self):
        """Every gh call so far: [{argv, stdin, rule}] (subprocess fake log or in-process)."""
        if self.subprocess_gh:
            return fakes.gh_calls(self.gh_log)
        return list(self.gh.calls) if self.gh is not None else []

    def run(self, units, answer=None, stage=1, mode="attended"):
        return driver.run_issue(REPO, ISSUE, mode, PLUGIN_ROOT, self.environ, checkout=self.repo.path,
                                units=units, out=self.out, answer=answer, stage=stage)

    def paths(self):
        from gxengine import paths as pathsmod
        return pathsmod.EnginePaths(os.path.realpath(self.engine_home), REPO, ISSUE)

    def state(self):
        from gxengine import store
        return store.load_state(self.paths())

    def log(self):
        from gxengine import store
        return list(store.read_log(self.paths()))

    def wt_git(self, *args, check=True):
        return self.repo.git(*args, cwd=self.worktree, check=check)


# --- fake units ---------------------------------------------------------------------------

class FakeSessionResult:
    def __init__(self, structured=None, session_id="sess-1", cost=0.5, exit_code=0):
        self.structured = structured
        self.session_id = session_id
        self.cost = cost
        self.exit_code = exit_code
        self.end = codes.SessionEnd.COMPLETED.value


class FakeSession:
    """`actions[step_id]` = list of per-call dicts (the last repeats):
    {"write": {rel: text}, "commit": "msg", "cost": float, "sleep": s, "structured": dict}."""

    def __init__(self, world, actions=None):
        self.world = world
        self.actions = {"analyze": [{"write": {f"{SPECS}/analysis.md": ANALYSIS}}],
                        "implement": [{"write": {"src/app.py": "x = 2\n"}, "commit": "feat: quiz type"}]}
        self.actions.update(actions or {})
        self.calls = []

    def cli_version(self, claude_bin="claude", env=None):
        return "2.1.323"

    def run_session(self, inp, attempt_dir, base_env, claude_bin="claude", limits=None, version=None,
                    budget_key=None):
        n = sum(1 for c in self.calls if c["step"] == inp.step)
        self.calls.append({"step": inp.step, "attempt": inp.attempt, "resume": inp.resume,
                           "instruction": inp.instruction, "in_dir": inp.paths.get("in_dir")})
        seq = self.actions.get(inp.step) or [{}]
        act = seq[min(n, len(seq) - 1)]
        if act.get("sleep"):
            time.sleep(act["sleep"])
        wt = inp.paths["worktree"]
        for rel, text in (act.get("write") or {}).items():
            full = os.path.join(wt, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(text)
        if act.get("commit"):
            self.world.wt_git("add", "-A")
            self.world.wt_git("commit", "-q", "--allow-empty", "-m", act["commit"])
        return FakeSessionResult(structured=act.get("structured", {"status": "done"}),
                                 cost=act.get("cost", 0.5), session_id=f"sess-{inp.step}")


class FakeFacts:
    class FactMissing(Exception):
        pass

    def start_facts(self, ctx, step, attempt, issue, kind):
        head = gitops.head(ctx)
        return {"step": getattr(step, "id", step), "attempt": attempt, "issue": issue, "kind": kind, "start_head": head,
                "start_tree": gitops.tree_state(ctx), "base_sha": ctx.base_sha,
                "merge_base": gitops.merge_base(ctx, head), "started_at": "2026-11-23T01:00:00Z"}

    def finish_facts(self, ctx, start, procedure, step, session=None, run=None):
        end = gitops.head(ctx)
        outputs = []
        for o in step.outputs:
            p = os.path.join(ctx.work_tree, o)
            outputs.append({"path": o, "exists": os.path.lexists(p), "regular": os.path.isfile(p)
                            and not os.path.islink(p), "blob": None})
        sess = None
        if step.kind == codes.StepKind.ROLE.value:
            sess = {"init": {"ok": True, "mismatches": []}, "end": "completed",
                    "structured_output": bool(session and session.structured is not None),
                    "stream_file": "stream.jsonl", "cost_usd": session.cost if session else None}
        exit_code = None
        if session is not None:
            exit_code = session.exit_code
        elif run is not None:
            exit_code = run["exit_code"]
        return {"format": 1, "issue": start["issue"], "step": start["step"], "attempt": start["attempt"],
                "kind": start["kind"], "started_at": start["started_at"], "ended_at": "2026-11-23T01:01:00Z",
                "duration_s": 1.0, "base_sha": start["base_sha"], "merge_base": start["merge_base"],
                "start_head": start["start_head"], "end_head": end, "start_tree": start["start_tree"],
                "end_tree": gitops.tree_state(ctx), "exit_code": exit_code,
                "changed_files": gitops.changed_files(ctx, end), "commits": [], "outputs": outputs,
                "control_files": None, "ownership": None, "judge_writes_outside": None, "reentry": None,
                "session": sess, "run": run, "outcome": None, "warnings": []}

    def changed_paths(self, facts):
        out = set()
        for c in facts["changed_files"]:
            out.add(c["path"])
            if c.get("from"):
                out.add(c["from"])
        return sorted(out)

    def reentry_facts(self, ctx, recorded_head):
        return {"forward_only": True, "dirty_files": gitops.tree_state(ctx)["dirty_files"]}


def done():
    return statemachine.Outcome("done")


def check_failed(detail="verdict-block", back_to=None):
    return statemachine.Outcome("failed", code="check-failed", detail=detail, back_to=back_to)


def output_format(detail="no-structured-output"):
    return statemachine.Outcome("failed", code="output-format", detail=detail, errors=["no structured output"])


def blocked():
    return statemachine.Outcome("blocked")


def stop(reason):
    return statemachine.Outcome("stop", stop=reason)


class FakeResults:
    """`judge[step_id]` = list of Outcome factories (the last repeats; default done)."""

    def __init__(self, judge=None, control_ok=True):
        self.judge = judge or {}
        self.control_ok = control_ok
        self.calls = []

    def _next(self, step_id):
        n = sum(1 for c in self.calls if c == step_id)
        self.calls.append(step_id)
        seq = self.judge.get(step_id) or [done]
        return seq[min(n, len(seq) - 1)]()

    def check_control_files(self, ctx, procedure_commit, issue, head_sha):
        return {"ok": self.control_ok, "changed": [] if self.control_ok else [".claude/agents/x.md"]}

    def check_ownership(self, ctx, procedure, state, step, owner_facts=None, head_sha=None):
        return {"ok": True, "foreign": []}

    def judge_writes_outside(self, procedure, step, changed):
        return []

    def owner_facts(self, paths, state):
        return {}

    def add_boundary_facts(self, ctx, procedure, state, step, facts, procedure_commit, owner_facts=None):
        """The driver fills the boundary facts once through this (P3-Z decision 1)."""
        self.boundary_calls = getattr(self, "boundary_calls", 0) + 1
        facts["control_files"] = self.check_control_files(ctx, procedure_commit, procedure.issue, facts["end_head"])
        facts["ownership"] = self.check_ownership(ctx, procedure, state, step)
        if step.is_judge:
            facts["judge_writes_outside"] = self.judge_writes_outside(procedure, step, [])
        return facts

    def judge_role(self, procedure, step, brief, result, facts, quota_reset_at=None):
        return self._next(step.id)

    def judge_run(self, step, facts, run_outcome=None):
        if not facts["control_files"].get("ok"):
            return stop("control-file")
        if self.judge.get(step.id):
            return self._next(step.id)
        if facts["run"]["exit_code"] == 0:
            return done()
        return check_failed("run-nonzero")

    def commit_judge_outputs(self, ctx, procedure, step, issue, facts=None):
        present = [o for o in step.outputs if os.path.isfile(os.path.join(ctx.work_tree, o))]
        return gitops.commit_paths(ctx, present, f"docs: {step.id} output") if present else gitops.head(ctx)


class FakeRunner:
    """`codes_by_step[step_id]` = list of exit codes (the last repeats; default 0)."""

    def __init__(self, codes_by_step=None):
        self.codes_by_step = codes_by_step or {}
        self.calls = []

    def toolchain_prepare(self, ctx, config, base_env, srt_bin, **kw):
        return []

    def run_step(self, ctx, config, procedure, step, attempt_dir, base_env, srt_bin, plugin_root, *,
                 issue, attempt, paths, prepare_tree=None, control_check=None):
        n = sum(1 for c in self.calls if c == step.id)
        self.calls.append(step.id)
        self.paths_seen = getattr(self, "paths_seen", []) + [dict(paths)]
        seq = self.codes_by_step.get(step.id) or [0]
        rc = seq[min(n, len(seq) - 1)]
        log = os.path.join(attempt_dir, "run.log")
        with open(log, "w", encoding="utf-8") as f:
            f.write(f"fake run {step.name} rc={rc}\n")
        run = {"name": step.name, "exit_code": rc, "timed_out": False, "log_file": "run.log",
               "rerun": None, "base_run": None}
        outcome = {"status": "done", "code": None, "detail": None, "stop": None} if rc == 0 else \
            {"status": "failed", "code": "check-failed", "detail": "run-nonzero", "stop": None}
        return FakeStepRun(run, outcome, gitops.tree_state(ctx), gitops.head(ctx))


class FakeStepRun:
    """runner.StepRun's shape."""

    def __init__(self, run, outcome, end_tree, head):
        self.run, self.outcome, self.end_tree = run, outcome, end_tree
        self.start_head = self.end_head = head
        self.duration_s, self.control_files, self.notes = 0.1, None, []


class FakePrbody:
    def __init__(self):
        self.calls = []

    def build(self, procedure, state, facts_by_step, results_by_step, config, qa_checklist, analysis, **stage2):
        self.calls.append({"facts": sorted(facts_by_step), "acs": analysis["acs"]})
        return "**AC**\n\n- AC 1\n"

    def title(self, issue_title, issue):
        return f"feat: {issue_title}"


def units(world, session=None, results=None, runner=None, prbody=None, **over):
    """driver.Units with every P3-A/B seam faked (srt self check and canary record too)."""
    kw = dict(session=session or FakeSession(world), facts=FakeFacts(), results=results or FakeResults(),
              runner=runner or FakeRunner(), prbody=prbody or FakePrbody(),
              self_check=lambda env: (True, ""), canary_ok=lambda env, rc, v: (True, f"key-{rc}"),
              srt_canary_ok=lambda env, srt, paths: (True, "srt-key"),
              srt_bin=lambda paths, environ: "/usr/bin/true", sleep=lambda s: None, make_gh=world.make_gh)
    kw.update(over)
    return driver.Units(**kw)


def run_git(cwd, *args, env):
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


# --- stage 2: a fake leader (the A ↔ B contract: leader.call(LeaderRequest) -> LeaderResult) ------

def leader_answer(answer, step=None, reason=None, note="", recommendation=None, **extra):
    """One scripted leader outcome: an accepted answer."""
    return {"answer": answer, "step": step, "reason": reason or codes.LeaderReason.OTHER.value, "note": note,
            "recommendation": recommendation, "extra": extra}


class FakeLeader:
    """`script[situation]` = list of outcome dicts (the last repeats): `leader_answer(...)`, or
    {"failed": {...}}, {"stop": reason}, {"quota_reset_at": t}, {"called": False}, {"raise": exc}.
    Each call spawns `sessions` (default 1) fake sessions recorded like session A will:
    check → the next attempt of the check step (store.new_attempt, facts kind check);
    leader → <records>/leader/<k>/facts.json (kind leader). `cost` per session."""

    def __init__(self, world, script=None, cost=0.25):
        self.world = world
        self.script = script or {}
        self.cost = cost
        self.calls = []

    def _facts(self, req, attempt, kind):
        ctx = req.ctx
        head = gitops.head(ctx)
        tree = gitops.tree_state(ctx)
        return {"format": 1, "issue": req.paths.issue, "step": req.step, "attempt": attempt, "kind": kind,
                "started_at": "2026-11-23T01:00:00Z", "ended_at": "2026-11-23T01:01:00Z", "duration_s": 1.0,
                "base_sha": ctx.base_sha, "merge_base": gitops.merge_base(ctx, head), "start_head": head,
                "end_head": head, "start_tree": tree, "end_tree": tree, "exit_code": 0, "changed_files": [],
                "commits": [], "outputs": [], "control_files": None, "ownership": None,
                "judge_writes_outside": None, "reentry": None,
                "session": {"init": {"ok": True, "mismatches": []}, "end": "completed", "structured_output": True,
                            "stream_file": "stream.jsonl", "cost_usd": self.cost},
                "run": None, "outcome": None, "warnings": []}

    def _session(self, req):
        if req.kind == codes.AttemptKind.CHECK.value:
            n = store.new_attempt(req.paths, req.state, req.step)
            store.write_facts(req.paths, req.step, n, self._facts(req, n, "check"))
            return n
        root = store._root(req.paths)
        d = os.path.join(req.paths.issue_dir, leadermod.LEADER_DIR)
        fsafe.make_dirs(d, root=root)
        have = [int(x) for x in os.listdir(d) if x.isdigit()]
        k = max(have, default=0) + 1
        fsafe.make_dirs(os.path.join(d, str(k), "in"), root=root)
        fsafe.write_json(os.path.join(d, str(k), "facts.json"), self._facts(req, k, "leader"), root=root)
        return k

    def call(self, req):
        n = sum(1 for c in self.calls if c["situation"] == req.situation)
        self.calls.append({"situation": req.situation, "kind": req.kind, "step": req.step, "request": req})
        seq = self.script.get(req.situation) or [leader_answer("escalate", recommendation={
            "answer": "escalate", "step": None, "note": "default fake"})]
        act = dict(seq[min(n, len(seq) - 1)])
        if act.get("raise"):
            raise act["raise"]
        if act.get("called") is False:
            return leadermod.LeaderResult(situation=req.situation, called=False)
        k = act.get("sessions", 1)
        sessions = [self._session(req) for _ in range(k)]
        fields = {"situation": req.situation, "called": True, "attempts": k, "sessions": sessions,
                  "cost_usd": round(self.cost * k, 6)}
        for key in ("failed", "stop", "quota_reset_at"):
            if act.get(key) is not None:
                fields[key] = act[key]
        if "answer" in act:
            fields.update({"answer": act["answer"], "step": act["step"], "reason": act["reason"],
                           "note": act["note"], "recommendation": act["recommendation"], "extra": act["extra"]})
        return leadermod.LeaderResult(**fields)
