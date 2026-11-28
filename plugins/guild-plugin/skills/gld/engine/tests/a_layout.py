"""P3-A test layout: a temp repository + Issue worktree + engine records + fake home.

Used by test_session / test_facts / test_results (U6–U8). Everything lives under one temp
dir; HOME is a fake home (a .gitconfig with an identity, hooks off), CLAUDE_CONFIG_DIR a
folder inside it — never the user's. `claude` is always the fake (absolute path, and the
env passes tests.helpers.fakes.assert_fakes_first).

    with tempfile.TemporaryDirectory() as tmp:
        lay = Layout(tmp)                      # issue 42, base = the initial commit
        inp = lay.role_input("design", "tech-lead", attempt=1, outputs=["docs/specs/42/design.md"])
        res = session.run_session(inp, lay.attempt_dir("design", 1), lay.env(scenarios=[...]),
                                  claude_bin=fakes.FAKE_CLAUDE)
"""

import json
import os

from gxengine import codes, defaults, gitops, paths as P, procedure as PR, render, session
from tests.helpers import fakes, gitrepo

ISSUE = 42

BASE_FILES = {
    "README.md": "app\n",
    "src/a.py": "x = 1\n",
    "CLAUDE.md": "# repo rules\n",
    ".claude/agents/developer.md": "---\nname: developer\n---\nbody\n",
    ".claude/guild/config.json": '{"format": 1}\n',
    ".gitignore": "ignored/\n.claude/local/\nnode_modules/\n",
}

GITCONFIG = """[user]
\tname = Role Test
\temail = role-test@example.invalid
[core]
\thooksPath = /dev/null
\tfsmonitor = false
[commit]
\tgpgsign = false
"""

# A small feature-like procedure: analyze (judge) → design (judge) → developer (work) →
# test (run) → review (judge, checks) → qa (judge) → create-pr.
PROCEDURE = {
    "format": 1, "issue": ISSUE, "revision": 1,
    "origin": {"template": "feature", "version": "test", "start": "test"},
    "steps": [
        {"id": "analyze", "role": "requirements-engineer", "inputs": ["in:issue.md"],
         "outputs": [f"docs/specs/{ISSUE}/analysis.md"]},
        {"id": "design", "role": "tech-lead", "inputs": [f"docs/specs/{ISSUE}/analysis.md"],
         "outputs": [f"docs/specs/{ISSUE}/design.md"], "on_fail": {"back_to": "design", "max": 2}},
        {"id": "implement", "role": "developer", "inputs": [f"docs/specs/{ISSUE}/design.md"],
         "outputs": [], "on_fail": {"back_to": "implement", "max": 3}},
        {"id": "test", "run": "test", "on_fail": {"back_to": "implement", "max": 3}},
        {"id": "review", "role": "tech-lead", "inputs": ["in:review.diff"], "outputs": [],
         "checks": ["diff-review", "design-conformance"], "on_fail": {"back_to": "implement", "max": 3}},
        {"id": "qa", "role": "qa", "inputs": [], "outputs": [f"docs/specs/{ISSUE}/qa-*.md"],
         "on_fail": {"back_to": "implement", "max": 2}},
        {"id": "pr", "op": "create-pr"},
    ],
}


def work_result(**over):
    r = {"status": "done", "outputs": [], "requests": [], "blocked_by": None, "discoveries": [], "note": "t"}
    r.update(over)
    return r


def review_result(**over):
    r = work_result()
    r.update({"verdict": "pass", "reviewed": ["src/a.py"],
              "checks": [{"id": "diff-review", "result": "pass", "note": ""},
                         {"id": "design-conformance", "result": "pass", "note": ""}],
              "findings": []})
    r.update(over)
    return r


class Layout:
    def __init__(self, tmp, issue=ISSUE, base_files=None):
        tmp = os.path.realpath(tmp)
        self.tmp = tmp
        self.issue = issue
        self.home = os.path.join(tmp, "home")
        os.makedirs(self.home)
        with open(os.path.join(self.home, ".gitconfig"), "w", encoding="utf-8") as f:
            f.write(GITCONFIG)
        self.config_dir = os.path.join(self.home, ".claude-cfg")
        os.makedirs(self.config_dir)
        self.plugin_root = os.path.join(tmp, "plugin")
        os.makedirs(self.plugin_root)
        projects = os.path.join(self.home, "projects")
        os.makedirs(projects)
        self.repo = gitrepo.GitRepo.create(projects, name="app", files=dict(base_files or BASE_FILES))
        self.base_sha = self.repo.head()
        wt = os.path.join(projects, f".gld-app-{issue}")
        self.git_env = gitrepo.git_env(projects)
        self.ctx = gitops.create_issue_worktree(self.repo.path, wt, f"gld/{issue}", self.base_sha,
                                                base_env=self.git_env)
        self.wt = self.ctx.work_tree
        self.ep = P.EnginePaths(os.path.join(self.home, ".gld"), "acme/app", issue)
        os.makedirs(os.path.join(self.wt, "docs", "specs", str(issue)), exist_ok=True)
        self.procedure = PR.Procedure(json.loads(json.dumps(PROCEDURE).replace(f"/{ISSUE}/", f"/{issue}/")
                                                 .replace(f'"issue": {ISSUE}', f'"issue": {issue}')))
        self.config = {"format": 1, "commands": {"test": {"cmd": "true"}}}

    # --- files --------------------------------------------------------------------
    def write(self, rel, text):
        full = os.path.join(self.wt, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
        return full

    def commit(self, message="work", paths=None):
        return self.repo.commit(message, paths=paths, cwd=self.wt)

    def git(self, *args):
        return self.repo.git(*args, cwd=self.wt)

    # --- engine folders -----------------------------------------------------------
    def attempt_dir(self, step, attempt):
        d = self.ep.attempt_dir(step, attempt)
        os.makedirs(os.path.join(d, "in"), exist_ok=True)
        os.makedirs(self.ep.run_tmp(step, attempt), exist_ok=True)
        os.makedirs(self.ep.cache, exist_ok=True)
        return d

    def render_paths(self, step, attempt):
        self.attempt_dir(step, attempt)
        return {
            "home": self.home, "claude_config_dir": self.config_dir, "worktree": self.wt,
            "main_checkout": self.repo.path, "git_common_dir": self.ctx.common_dir,
            "own_worktree": self.ctx.git_dir, "engine_records": self.ep.records,
            "in_dir": self.ep.in_dir(step, attempt), "run_tmp": self.ep.run_tmp(step, attempt),
            "cache": self.ep.cache, "plugin_root": self.plugin_root, "issue": self.issue,
            "other_worktrees": [], "other_repo_roots": [],
        }

    def role_input(self, step, role, attempt=1, outputs=(), checks=False, resume=None, budget=None,
                   model=None, effort=None, instruction="Do the step."):
        rc = codes.role_class(role)
        key = role if role in defaults.MODEL_EFFORT else f"{role}/{'review' if checks else step}"
        m, e = defaults.MODEL_EFFORT.get(key, ("sonnet", "medium"))
        return render.RenderInput(
            kind="role", role=role, role_class=rc, step=step, attempt=attempt, issue=self.issue,
            outputs=list(outputs), paths=self.render_paths(step, attempt), config=self.config,
            model=model or m, effort=effort or e, tools=list(defaults.TOOLS[rc]),
            max_budget_usd=budget if budget is not None else session.session_budget(role),
            json_schema="result-review" if checks else "result-work",
            instruction=instruction, system_prompt="# role\n", resume=resume,
            bash_timeout_ms=60000)

    def env(self, scenarios=(), log=None, version=None):
        base = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        base["HOME"] = self.home
        env = fakes.fake_env(base=base, claude_scenarios=[fakes.scn(s) if "/" not in s else s for s in scenarios],
                             claude_log=log, claude_version=version)
        fakes.assert_fakes_first(env)
        return env

    def scenario(self, name, obj):
        """Write an inline scenario file into the temp dir; return its path."""
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return path
