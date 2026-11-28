"""P3-Z end-to-end world: the REAL engine units (session, facts, results, runner, rules,
budget, prbody, github, gitops) with the fake `claude`, the fake `gh` executable, a local
bare remote, a temporary git repository and the REAL srt (scope §6.2). No paid call.

    w = ZWorld(tmp)                              # acme/app, Issue 42, the plugin feature template
    w.script(["analyze", "test-cases", ...])     # one fake-claude scenario per role session, in order
    rc = w.run()                                 # driver.run_issue with driver.Units() (real modules)

What is real: srt (self check, every run step, verify-gate with the 0.98.7 gate), the
plugin check scripts, git, the outbound secret scan, the fake gh subprocess. What is fake:
the CLI (tests/fakes/bin/claude replays tests/fixtures/claude/f2/r4.jsonl with the init
event filled from argv) and GitHub (tests/fakes/bin/gh + rule file). The canary records
the driver requires (I9) are written by `write_canary_records` — the paid canary is P4.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from gxengine import canaryrun, driver, instructions, paths as pathsmod, store
from tests import c_world as W
from tests.helpers import fakes
from tests.test_render import find_srt

ENGINE = W.ENGINE
PLUGIN_ROOT = W.PLUGIN_ROOT
REPO = W.REPO
ISSUE = W.ISSUE
SPECS = W.SPECS
STREAM = os.path.join(fakes.FIXTURES, "claude", "f2", "r4.jsonl")
CLI_VERSION = "2.1.323"

GITCONFIG = """[user]
\tname = Role Test
\temail = role-test@example.invalid
[core]
\thooksPath = /dev/null
\tfsmonitor = false
[commit]
\tgpgsign = false
"""

TEST_CASES = f"""# Test cases — #{ISSUE}

## Quiz type row [AC #1]

- C1 [AC #1]: the settings screen shows the quiz type row.
"""

SKELETON = "# Skeleton\n\n- `src/app.py`: `x` holds the quiz type flag.\n"
CHECKLIST = "# Manual test checklist\n\n- [ ] AC #1: open settings, see the quiz type row.\n"

# Every named command of the plugin feature template. `setup` unpacks a control-named file
# under a gitignored folder (P3-Z decision 6: allowed for a run, not compared afterwards).
COMMANDS = {
    "setup": {"cmd": "mkdir -p node_modules/x && printf 'package rules\\n' > node_modules/x/AGENTS.md"},
    "lint": {"cmd": "python3 -I -B -c \"import ast; ast.parse(open('src/app.py').read())\""},
    "typecheck": {"cmd": "true"},
    "test": {"cmd": "python3 -I -B tests/test_app.py"},
    "build": {"cmd": "true"},
    "e2e": {"cmd": "true"},
    "ac-format": {"plugin": "ac-format"},
    "ac-coverage": {"plugin": "ac-coverage"},
    "verify-gate": {"plugin": "verify-gate"},
}


def config(extra=None):
    c = {"format": 1, "commands": json.loads(json.dumps(COMMANDS)),
         "path_rules": [{"kind": "verification", "globs": ["tests/**"]}],
         "registry_hosts": ["registry.npmjs.org"]}
    c.update(extra or {})
    return c


def feature_steps(stage=1):
    """The plugin default feature template, unchanged (every step of `stage`: from 2 with the done-gate)."""
    return instructions.load_default_template("feature", stage=stage)["steps"]


def work_result(outputs=(), note="done"):
    return {"status": "done", "outputs": list(outputs), "requests": [], "blocked_by": None,
            "discoveries": [], "note": note}


def review_result(checks, reviewed=("src/app.py", "tests/test_app.py"), verdict="pass", findings=()):
    r = work_result()
    r.update({"verdict": verdict, "reviewed": list(reviewed),
              "checks": [{"id": c, "result": "pass", "note": ""} for c in checks], "findings": list(findings)})
    return r


def _write(path, content):
    return {"op": "write", "path": path, "content": content}


def _git(*args):
    return {"op": "git", "args": list(args)}


def role_scenario(step, cost=1.0, **over):
    """The fake-claude scenario dict of one happy role session of the feature template."""
    s = f"{SPECS}"
    table = {
        "analyze": (work_result([f"{s}/analysis.md"]), [_write(f"{s}/analysis.md", W.ANALYSIS)]),
        "test-cases": (work_result([f"{s}/test-cases.md"]), [_write(f"{s}/test-cases.md", TEST_CASES)]),
        "design": (work_result([f"{s}/skeleton.md"]), [_write(f"{s}/skeleton.md", SKELETON)]),
        "implement": (work_result(note="ran: tests/test_app.py OK"), [
            _write("src/app.py", "x = 2\n"),
            _write("tests/test_app.py", "import sys\nsys.path.insert(0, 'src')\nimport app\n"
                                        "assert app.x == 2\nprint('OK')\n"),
            _git("add", "-A"), _git("commit", "-q", "-m", "feat: show the quiz type")]),
        "review-design": (review_result(["design-conformance"]), []),
        "review-tests": (review_result(["test-quality", "test-change-review"]), []),
        "review-audit": (review_result(["diff-review"]), []),
        "qa": (dict(review_result(["qa-acceptance"]), outputs=[f"{s}/manual-test-checklist.md"]),
               [_write(f"{s}/manual-test-checklist.md", CHECKLIST)]),
    }
    structured, actions = table[step]
    scn = {"format": 1, "description": f"P3-Z e2e: {step}", "stream": STREAM, "init_from_argv": True,
           "structured_output": structured, "actions": actions,
           "result": {"total_cost_usd": cost}}
    scn.update(over)
    return scn


ROLE_STEPS = ["analyze", "test-cases", "design", "implement", "review-design", "review-tests",
              "review-audit", "qa"]


class ZWorld(W.World):
    """c_world.World + real units: fake claude log/scenarios, real srt, canary records."""

    def __init__(self, tmp, cfg=None, steps=None, extra_files=None, gh=None):
        self.srt = find_srt()
        if self.srt is None:
            raise AssertionError("srt not found (GLD_TEST_SRT / ~/.gld/srt / PATH) — a stage-1 start condition")
        files = {".gitignore": "node_modules/\nbuild/\n",
                 "tests/test_app.py": "import sys\nsys.path.insert(0, 'src')\nimport app\nprint('OK')\n"}
        files.update(extra_files or {})
        super().__init__(tmp, steps=steps or feature_steps(), cfg=cfg or config(), extra_files=files, gh=gh)
        self.subprocess_gh = True
        with open(os.path.join(self.home, ".gitconfig"), "w", encoding="utf-8") as f:
            f.write(GITCONFIG)
        self.scn_dir = os.path.join(self.tmp, "scenarios")
        self.claude_log = os.path.join(self.tmp, "claude-log")
        os.makedirs(self.scn_dir)
        self._n = 0
        self.scenarios = []
        self._environ()
        write_canary_records(self.engine_home, cfg or config(), self.environ)

    def _environ(self):
        self.environ = fakes.fake_env(base=self.environ, claude_scenarios=self.scenarios or None,
                                      claude_log=self.claude_log, gh_fixtures=self.gh_file, gh_log=self.gh_log)
        self.environ["GLD_SRT_BIN"] = self.srt

    def add(self, scn):
        """Append one scenario (dict) to the fake-claude call sequence."""
        self._n += 1
        path = os.path.join(self.scn_dir, f"{self._n:02d}-{scn.get('description', 'x').split()[-1]}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(scn, f, indent=1)
        self.scenarios.append(path)
        self._environ()
        return path

    def script(self, steps, costs=None):
        for st in steps:
            self.add(role_scenario(st, cost=(costs or {}).get(st, 1.0)))

    def units(self, **over):
        over.setdefault("make_gh", self.make_gh)
        return driver.Units(**over)

    def run(self, units=None, answer=None, stage=1, mode="attended"):
        return driver.run_issue(REPO, ISSUE, mode, PLUGIN_ROOT, self.environ, checkout=self.repo.path,
                                units=units or self.units(), out=self.out, answer=answer, stage=stage)

    def claude_calls(self):
        return fakes.claude_calls(self.claude_log)

    def engine_cli(self, *args, stage=None):
        """argv of `engine.py <args>` (the real CLI, run by a test as a subprocess). `stage` given:
        the same entry (`cli.main`) with that engine stage instead of defaults.ENGINE_STAGE — a
        stage-1 world (no done-gate in its template) passes 1 since the default is 2 (Q6, D21)."""
        if stage is None:
            return [sys.executable, "-I", "-B", os.path.join(ENGINE, "engine.py"), *args]
        launcher = ("import sys; sys.path.insert(0, sys.argv[1]); from gxengine import cli; "
                    "sys.exit(cli.main(sys.argv[3:], stage=int(sys.argv[2])))")
        return [sys.executable, "-I", "-B", "-c", launcher, ENGINE, str(int(stage)), *args]


def write_canary_records(engine_home, config=None, environ=None):
    """Passing role canary records for both role classes (I9 — the paid canary is P4); the
    work key follows the repository's sandbox exceptions (P5 F2), every key the account of `environ` (FC F2)."""
    d = os.path.join(engine_home, "canary")
    os.makedirs(d, exist_ok=True)
    for rc in ("work", "judge"):
        key = canaryrun.role_key(CLI_VERSION, rc, config, environ=environ)
        name = "".join(c if c.isalnum() or c in "-._" else "_" for c in key) + ".json"
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump({"ok": True, "key": key}, f)


def new_tmp():
    """A temp root under /tmp (never under this session's /tmp/claude-<uid>, F4)."""
    return os.path.realpath(tempfile.mkdtemp(prefix="gx-e2e-", dir="/tmp"))


def rmtree(path):
    subprocess.run(["chmod", "-R", "u+w", path], capture_output=True)
    shutil.rmtree(path, ignore_errors=True)


# --- stage 3 (Q4): bug / refactor templates, follow-ups, the real stage-3 units -------------------------
#
#     w = Z3World(tmp, cfg=config3())               # acme/app, Issue 42, a private repository, stage-3 gh rules
#     w.add(role_scenario3("analyze", analysis=BUG_ANALYSIS)); w.add(leader_scenario(...)); ...
#     rc = w.run(stage=3)
#
# The test command runs every tests/test_*.py of the tree it is started in (the overlay tree of
# repro-red too), so a regression test written by `reproduce` is red until `fix` changes src/app.py.

TEST3_CMD = ("python3 -I -B -c \"import glob, runpy; "
             "[runpy.run_path(p, run_name='__main__') for p in sorted(glob.glob('tests/test_*.py'))]\"")
STAGE3_PLUGIN_COMMANDS = ("repro-red", "safety-net-proof", "verification-frozen", "no-production-change")
TEST_CODE_GLOBS = ["tests/test_*.py"]
SAFETY_NET_GLOBS = ["tests/test_safety_net_*.py"]


def config3(extra=None):
    """Stage-3 settings: every named command of the five templates, the test-code and safety-net rules."""
    c = config()
    c["commands"]["test"] = {"cmd": TEST3_CMD}
    for n in STAGE3_PLUGIN_COMMANDS:
        c["commands"][n] = {"plugin": n}
    c["path_rules"] = [{"kind": "verification", "globs": ["tests/**"]},
                       {"kind": "test-code", "globs": list(TEST_CODE_GLOBS)},
                       {"kind": "safety-net", "globs": list(SAFETY_NET_GLOBS)}]
    c.update(extra or {})
    return c


def analysis3(type_="bug", safety_net="none", ac="x is 2 after the fix."):
    return f"""# Analysis — #{ISSUE}

type: {type_}
size: small
risk: low
split: none
prerequisite: none
safety_net: {safety_net}

## Acceptance criteria

- AC #1: {ac} [must]

## Requirement map

| Issue requirement | AC |
|---|---|
| Make x right | AC #1 |

## Assumptions

- The value lives in src/app.py.
"""


TEST_CASES3 = f"""# Test cases — #{ISSUE}

## The value of x [AC #1]

- C1 [AC #1] (regression): x is 2.
"""

DIAGNOSIS = "# Diagnosis\n\n- Reproduce: import app; app.x is 1.\n- Root cause: src/app.py sets x = 1.\n"
REGRESSION_TEST = "import sys\nsys.path.insert(0, 'src')\nimport app\nassert app.x == 2, app.x\nprint('OK bug')\n"
SAFETY_NET_TEST = "import sys\nsys.path.insert(0, 'src')\nimport app\nassert app.x == 1, app.x\nprint('OK net')\n"
REVIEWED3 = ("src/app.py", "tests/test_bug.py")


def work_result3(outputs=(), note="done", requests=(), discoveries=(), irreversible=(), golden_reasons=()):
    """A stage-3 work result (result-work-s3: requests / irreversible / golden_reasons are required)."""
    r = work_result(outputs, note)
    r.update({"requests": list(requests), "discoveries": list(discoveries), "irreversible": list(irreversible),
              "golden_reasons": list(golden_reasons)})
    return r


def review_result3(checks, reviewed=REVIEWED3, verdict="pass", findings=(), discoveries=(), requests=()):
    """A stage-3 review result (result-review-s3)."""
    r = review_result(checks, reviewed, verdict, findings)
    r.update({"requests": list(requests), "discoveries": list(discoveries), "irreversible": []})
    return r


def role_scenario3(step, cost=1.0, analysis=None, **over):
    """The fake-claude scenario of one happy role session of the stage-3 bug / refactor templates."""
    s = f"{SPECS}"
    table = {
        "analyze": (work_result3([f"{s}/analysis.md"]), [_write(f"{s}/analysis.md", analysis or analysis3())]),
        "test-cases": (work_result3([f"{s}/test-cases.md"]), [_write(f"{s}/test-cases.md", TEST_CASES3)]),
        "diagnose": (work_result3([f"{s}/diagnosis.md"]), [_write(f"{s}/diagnosis.md", DIAGNOSIS)]),
        "design": (work_result3([f"{s}/skeleton.md"]), [_write(f"{s}/skeleton.md", SKELETON)]),
        "reproduce": (work_result3(["tests/test_bug.py"], note="tests/test_bug.py is red on the base"), [
            _write("tests/test_bug.py", REGRESSION_TEST),
            _git("add", "-A"), _git("commit", "-q", "-m", "test: reproduce the wrong x")]),
        "fix": (work_result3(note="x is 2 now"), [
            _write("src/app.py", "x = 2\n"), _git("add", "-A"), _git("commit", "-q", "-m", "fix: x is 2")]),
        "safety-net": (work_result3(["tests/test_safety_net_x.py"]), [
            _write("tests/test_safety_net_x.py", SAFETY_NET_TEST),
            _git("add", "-A"), _git("commit", "-q", "-m", "test: safety net of x")]),
        "transform": (work_result3(note="the same value, a clearer name"), [
            _write("src/app.py", "VALUE = 1\nx = VALUE\n"), _git("add", "-A"), _git("commit", "-q", "-m", "refactor: name it")]),
        "review-design": (review_result3(["root-cause-addressed"]), []),
        "review-tests": (review_result3(["test-quality", "regression-proof", "test-change-review"]), []),
        "review-audit": (review_result3(["diff-review"]), []),
        "qa": (dict(review_result3(["qa-acceptance"]), outputs=[f"{s}/manual-test-checklist.md"]),
               [_write(f"{s}/manual-test-checklist.md", CHECKLIST)]),
    }
    structured, actions = table[step]
    scn = {"format": 1, "description": f"Q4 stage-3 e2e: {step}", "stream": STREAM, "init_from_argv": True,
           "structured_output": structured, "actions": actions, "result": {"total_cost_usd": cost}}
    scn.update(over)
    return scn


BUG_ROLE_STEPS = ["test-cases", "diagnose", "reproduce", "fix", "review-design", "review-tests", "review-audit", "qa"]


def leader_scenario(what, structured, cost=0.4, **over):
    """One fake-claude leader session (the stream of the role sessions, init from argv)."""
    scn = {"format": 1, "description": f"Q4 leader: {what}", "stream": STREAM, "init_from_argv": True,
           "structured_output": structured, "actions": [], "result": {"total_cost_usd": cost}}
    scn.update(over)
    return scn


def envelope(answer, reason, step=None, note="", recommendation=None, **extra):
    d = {"answer": answer, "reason": reason, "step": step, "note": note, "recommendation": recommendation}
    d.update(extra)
    return d


def plan3(template="bug", note="The bug template fits the one requirement.", **plan):
    """A stage-3 plan-gate answer (leader-answer-plan-gate-s3). No `adjust` field by default: with no
    usable catalog entry in this world the filled schema has none ({catalog_steps} = [] drops it)."""
    p = {"template": template, "models": [], "new_template_candidate": False}
    p.update(plan)
    return envelope("plan", "fits-template", note=note, requirements=[{"row": "R1", "covered": True}],
                    missing_requirements=[], plan=p, close=None)


def approve3(evidence="tests/test_bug.py asserts x == 2", **extra):
    """A stage-3 done-gate approve: `why_not_automated` null for a met AC (E5), one `summary` line."""
    extra.setdefault("summary", ["src/app.py returns the right value."])
    return envelope("approve", "acceptance-met", note="AC #1 is met.",
                    ac_verdicts=[{"ac": 1, "status": "met", "evidence": evidence, "why_not_automated": None}], **extra)


FOLLOWUP_CANDIDATE = {"number": 61, "title": "Old debt in src/legacy.py", "state": "open",
                      "labels": [{"name": "guild:followup"}], "body": "x", "updated_at": "2026-11-24T01:02:03Z"}


def gh_rules3(private=True, made=()):
    """c_world.gh_rules + what a stage-3 run reads and writes on GitHub (labels, follow-up candidates, the
    marker search, follow-up Issues / comments, the PR PATCH). `made` = Issues the marker search finds."""
    rules = W.gh_rules()
    q = "&state=open&sort=updated&direction=desc&per_page=30"
    rules["rules"][:0] = [
        {"args": ["repo", "view", REPO, "--json", "isPrivate"], "json": {"isPrivate": private}},
        {"args": ["api", f"repos/{REPO}/labels?per_page=100", "--paginate"],
         "json": [{"name": "type:bug"}, {"name": "type:refactor"}, {"name": "guild:followup"}]},
        {"args": ["api", f"repos/{REPO}/issues?labels=guild%3Afollowup{q}"], "json": [FOLLOWUP_CANDIDATE]},
        {"args": ["api", f"repos/{REPO}/issues?labels=gx%3Afollowup{q}"], "json": []},  # promote: other
        {"args": ["api", f"repos/{REPO}/issues?labels=guild%3Afollowup&state=all&per_page=100", "--paginate"],
         "json": list(made)},
        {"args": ["api", "-X", "POST", f"repos/{REPO}/labels", "--input", "-"], "json": {"name": "created"}},
        {"args": ["api", "-X", "POST", f"repos/{REPO}/issues", "--input", "-"],
         "json": {"number": 90, "html_url": f"https://github.com/{REPO}/issues/90"}},
        {"args": ["api", f"repos/{REPO}/issues/61/comments", "--paginate"], "json": []},
        {"args": ["api", "-X", "POST", f"repos/{REPO}/issues/61/comments", "--input", "-"], "json": {"id": 9101}},
        {"args": ["api", "-X", "PATCH", f"repos/{REPO}/pulls/77", "--input", "-"],
         "json": {"number": 77, "html_url": f"https://github.com/{REPO}/pull/77"}},
    ]
    return rules


class Z3World(ZWorld):
    """ZWorld at stage 3: the feature repository copy in its stage-3 form, the stage-3 gh rules."""

    def __init__(self, tmp, cfg=None, extra_files=None, gh=None, private=True):
        super().__init__(tmp, cfg=cfg or config3(), steps=feature_steps(stage=3), extra_files=extra_files,
                         gh=gh or gh_rules3(private=private))

    def run(self, units=None, answer=None, stage=3, mode="attended"):
        return super().run(units=units, answer=answer, stage=stage, mode=mode)

    def posts(self, path_end):
        """The JSON bodies the engine POSTed / PATCHed to an API path: `repos/…` = that path, `/…` = a suffix."""
        def hit(a):
            return a.endswith(path_end) if path_end.startswith("/") else a == path_end
        return [json.loads(c["stdin"]) for c in self.gh_calls()
                if c["argv"][:2] == ["api", "-X"] and hit(c["argv"][3]) and c["stdin"]]


__all__ = ["ZWorld", "Z3World", "ROLE_STEPS", "BUG_ROLE_STEPS", "role_scenario", "role_scenario3", "work_result",
           "review_result", "work_result3", "review_result3", "config", "config3", "analysis3", "leader_scenario",
           "envelope", "plan3", "approve3", "gh_rules3", "new_tmp", "rmtree", "pathsmod", "store"]
