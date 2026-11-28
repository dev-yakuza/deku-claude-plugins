"""Environment builders and log readers for the fake `claude` and `gh` (tests/fakes/bin).

    env = fake_env(claude_scenarios=[scn("ok-judge.json")], claude_log=d1,
                   gh_fixtures=gh_fixture("issue-42.json"), gh_log=d2)
    subprocess.run(["claude", "-p", "x", …], env=env)   # resolves to the fake
    calls = claude_calls(d1); gh = gh_calls(d2)
"""

import json
import os

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE_BIN = os.path.join(TESTS, "fakes", "bin")
FAKE_CLAUDE = os.path.join(FAKE_BIN, "claude")
FAKE_GH = os.path.join(FAKE_BIN, "gh")
FIXTURES = os.path.join(TESTS, "fixtures")


def assert_fakes_first(env):
    """Raise unless `claude` and `gh` resolve to the fakes on env's PATH.

    Every test that spawns something which may call `claude` or `gh` must call this on its
    env first: a real `claude` is a paid call and a real `gh` writes to GitHub.
    """
    import shutil
    for name, fake in (("claude", FAKE_CLAUDE), ("gh", FAKE_GH)):
        got = shutil.which(name, path=env.get("PATH", ""))
        if got is None or os.path.realpath(got) != os.path.realpath(fake):
            raise AssertionError(f"{name} resolves to {got!r}, not the fake {fake} — refusing to run")


def fixture(*parts):
    """Absolute path of a file under tests/fixtures."""
    return os.path.join(FIXTURES, *parts)


def scn(name):
    """A fake-claude scenario under fixtures/claude/scenarios."""
    return fixture("claude", "scenarios", name)


def gh_fixture(name):
    return fixture("gh", name)


def fake_env(base=None, claude_scenarios=None, claude_log=None, claude_version=None, gh_fixtures=None, gh_log=None):
    """A copy of `base` (default os.environ) with tests/fakes/bin first on PATH and the fake settings."""
    env = dict(os.environ if base is None else base)
    env["PATH"] = FAKE_BIN + os.pathsep + env.get("PATH", "/usr/bin:/bin")
    for k in ("GLD_FAKE_CLAUDE_SCENARIO", "GLD_FAKE_CLAUDE_SCENARIOS", "GLD_FAKE_CLAUDE_LOG", "GLD_FAKE_CLAUDE_VERSION",
              "GLD_FAKE_CLAUDE_INIT", "GLD_FAKE_CLAUDE_CANARY",
              "GLD_FAKE_GH_FIXTURES", "GLD_FAKE_GH_LOG"):
        env.pop(k, None)
    if claude_scenarios:
        env["GLD_FAKE_CLAUDE_SCENARIOS"] = os.pathsep.join(claude_scenarios)
    if claude_log:
        env["GLD_FAKE_CLAUDE_LOG"] = claude_log
    if claude_version:
        env["GLD_FAKE_CLAUDE_VERSION"] = claude_version
    if gh_fixtures:
        env["GLD_FAKE_GH_FIXTURES"] = gh_fixtures
    if gh_log:
        env["GLD_FAKE_GH_LOG"] = gh_log
    assert_fakes_first(env)
    return env


def claude_calls(log_dir):
    """The recorded fake-claude calls in order: [{argv, cwd, env, scenario}]."""
    if not os.path.isdir(log_dir):
        return []
    names = sorted((f for f in os.listdir(log_dir) if f.startswith("call-")), key=lambda f: int(f[5:-5]))
    out = []
    for n in names:
        with open(os.path.join(log_dir, n), encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def gh_calls(log_dir):
    """The recorded fake-gh calls in order: [{argv, cwd, stdin, rule}]."""
    path = os.path.join(log_dir, "calls.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_stream(path):
    """Parse a stream-json file into a list of events."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
