"""Shared test helpers for Studio (m0-plan §2).

- Isolation: tests never touch the real home, ~/.s2v, ~/.claude or $CLAUDE_CONFIG_DIR.
  `run.py` isolates the whole run; `StudioTestCase` gives each test fresh folders.
- script2video: found only through STUDIO_TEST_S2V (no personal default path). Tests that need
  it are skipped in a default run and fail in `run_tests.sh --full` when it is missing.
- Every s2v call gets a fake `uv` (exit 97) first on PATH and S2V_TTS=mock, so no model server
  can start by mistake.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", ".."))
SKILL = os.path.join(PLUGIN, "skills", "std")
SCRIPTS = os.path.join(SKILL, "scripts")
TEMPLATES = os.path.join(SKILL, "templates")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from stdo import machine, paths  # noqa: E402

MIN_S2V = (0, 12, 1)
LEAK_VARS = ("S2V_HEAVY_LOCK_TOKEN", "S2V_ACTOR_LOCK_TOKEN")
FAKE_UV_EXIT = 97
S2V_ENV = "STUDIO_TEST_S2V"
FULL_ENV = "STUDIO_TEST_FULL"


class LeakedToken(RuntimeError):
    pass


def check_no_leaked_tokens(env=None):
    """A lock token in the test environment would let s2v re-enter a real lock: refuse to run."""
    env = os.environ if env is None else env
    leaked = [name for name in LEAK_VARS if env.get(name)]
    if leaked:
        raise LeakedToken(
            "lock token(s) leaked into the test environment: %s — unset them and run again"
            % ", ".join(leaked)
        )


check_no_leaked_tokens()


def full_mode(env=None):
    env = os.environ if env is None else env
    return env.get(FULL_ENV) == "1"


# ---------- script2video ----------


def parse_semver(text):
    core = str(text).split("+", 1)[0].split("-", 1)[0]
    parts = core.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError("not a semver: %r" % (text,))
    return tuple(int(p) for p in parts)


def check_version_info(info):
    """Problems with `s2v --version --json` for Studio (empty list = usable)."""
    problems = []
    try:
        if parse_semver(info.get("version")) < MIN_S2V:
            problems.append(
                "s2v %s is older than %s" % (info.get("version"), ".".join(map(str, MIN_S2V)))
            )
    except ValueError as e:
        problems.append(str(e))
    if info.get("stale_build") is not False:
        problems.append("s2v dist is stale or unknown (run yarn build in the s2v repository)")
    if not info.get("id"):
        problems.append("s2v --version --json has no id")
    return problems


GUIDANCE = (
    "set %s to the absolute path of a script2video checkout (0.12.1 or later, built with "
    "`yarn build`) to run this test; `run_tests.sh --full` requires it" % S2V_ENV
)


def s2v_main(path):
    return os.path.join(path, "packages", "cli", "dist", "main.js")


def resolve_s2v(env=None):
    """The s2v repository from STUDIO_TEST_S2V, or None with the reason (no version check)."""
    env = os.environ if env is None else env
    value = env.get(S2V_ENV)
    if not value:
        return None, "%s is not set: %s" % (S2V_ENV, GUIDANCE)
    if not os.path.isabs(value):
        return None, "%s must be an absolute path: %r" % (S2V_ENV, value)
    if not os.path.isfile(s2v_main(value)):
        return None, "%s=%s has no packages/cli/dist/main.js: %s" % (S2V_ENV, value, GUIDANCE)
    return value, None


_s2v_cache = {}


def s2v_path(case=None):
    """The checked s2v repository. Unset STUDIO_TEST_S2V: skip (default run) or fail (--full).
    Set but unusable (missing, older than 0.12.1, stale build): fail in any mode."""
    if "result" not in _s2v_cache:
        unset = not os.environ.get(S2V_ENV)
        path, why = resolve_s2v()
        if path:
            info, err = _version_info(path)
            problems = [err] if err else check_version_info(info)
            if problems:
                path, why = None, "%s: %s" % (path, "; ".join(problems))
        _s2v_cache["result"] = (path, why, unset)
    path, why, unset = _s2v_cache["result"]
    if path:
        return path
    if unset and not full_mode():
        raise unittest.SkipTest("needs script2video: " + why)
    raise AssertionError("script2video unusable: " + why)


def _version_info(path):
    root = tempfile.mkdtemp(prefix="studio-s2v-version-")
    try:
        env = s2v_env(root)
        out = subprocess.run(
            ["node", s2v_main(path), "--version", "--json"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        if out.returncode != 0:
            return None, "s2v --version --json exited %d: %s" % (out.returncode, out.stderr.strip())
        return json.loads(out.stdout), None
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return None, "s2v --version --json failed: %s" % e
    finally:
        shutil.rmtree(root, ignore_errors=True)


def fake_bin(root):
    """A folder with a fake `uv` that exits 97 (put first on PATH for every s2v call)."""
    d = os.path.join(root, "fake-bin")
    os.makedirs(d, exist_ok=True)
    uv = os.path.join(d, "uv")
    with open(uv, "w") as f:
        f.write("#!/bin/sh\necho 'fake uv: no model servers in Studio tests' >&2\nexit %d\n"
                % FAKE_UV_EXIT)
    os.chmod(uv, 0o755)
    return d


STRIP_PREFIXES = ("S2V_", "STUDIO_", "CLAUDE_CODE_")
STRIP_NAMES = ("CLAUDECODE", "XDG_CONFIG_HOME")
KEEP_NAMES = (S2V_ENV, FULL_ENV, "STUDIO_TEST_REAL_HOME", "STUDIO_TEST_DENY_TERMS_FILE")


def isolated_env(root, base=None):
    """Environment with every per-user location under `root` (created). Claude Code session
    markers, every S2V_* and STUDIO_* variable (except the test switches) and XDG_CONFIG_HOME
    from outside are dropped; the needed ones are set again below."""
    env = dict(os.environ if base is None else base)
    for name in list(env):
        if name in KEEP_NAMES:
            continue
        if name in STRIP_NAMES or name.startswith(STRIP_PREFIXES):
            del env[name]
    dirs = {
        "HOME": "home",
        "S2V_STATE_DIR": "s2v-state",
        "STUDIO_HOME": "studio-home",
        "CLAUDE_CONFIG_DIR": "claude-config",
    }
    for name, sub in dirs.items():
        p = os.path.join(root, sub)
        os.makedirs(p, exist_ok=True)
        env[name] = p
    gitconfig = os.path.join(root, "gitconfig")
    if not os.path.exists(gitconfig):
        with open(gitconfig, "w") as f:
            f.write("[user]\n\tname = Studio Test\n\temail = studio-test@example.invalid\n"
                    "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n")
    env["GIT_CONFIG_GLOBAL"] = gitconfig
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def s2v_env(root, base=None):
    """Isolated environment for running s2v: fake uv first on PATH, mock TTS, no pages."""
    env = isolated_env(root, base)
    env["PATH"] = fake_bin(root) + os.pathsep + env.get("PATH", "")
    env["S2V_TTS"] = "mock"
    env["S2V_NO_OPEN"] = "1"
    for name in ("S2V_TTS_PORT", "S2V_ALIGNER_PORT", "S2V_TAKES_ALL"):
        env.pop(name, None)
    return env


def run_s2v(case, args, cwd=None, timeout=300):
    """Run s2v under the case's isolated s2v environment."""
    path = s2v_path(case)
    return subprocess.run(
        ["node", s2v_main(path)] + list(args),
        cwd=cwd or case.tmp, env=case.s2v_environ, capture_output=True, text=True,
        timeout=timeout,
    )


# ---------- test case ----------


class StudioTestCase(unittest.TestCase):
    """Fresh temporary home, s2v state, Studio home and Claude config folder for each test."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="studio-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._saved_env = dict(os.environ)
        self.addCleanup(self._restore_env)
        env = isolated_env(self.tmp)
        os.environ.clear()
        os.environ.update(env)
        self.s2v_environ = s2v_env(self.tmp, env)

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._saved_env)


# ---------- repositories ----------


def render_template(text, values):
    for key, value in values.items():
        text = text.replace("{{%s}}" % key, value)
    if "{{" in text:
        start = text.index("{{")
        raise ValueError("unfilled placeholder: %s" % text[start:text.index("}}", start) + 2])
    return text


def template(rel, values):
    with open(os.path.join(TEMPLATES, rel)) as f:
        return render_template(f.read(), values)


def git(repo, *args, check=True):
    out = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)
    if check and out.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), out.stderr))
    return out


def make_repo(tmp, name="repo", harness=True, marker=False, local=False, studio_root="studio",
              language="ko", s2v="/abs/script2video"):
    """A git repository (s2v looks for voices/ up to .git, so fixtures are always repos)."""
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
    git(repo, "init", "-q")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("# Fixture\n")
    if harness:
        values = {
            "LANGUAGE": language, "S2V_PATH": s2v or "",
            "PROJECT_NAME": "Fixture", "PRIORITIES_BY_KIND": "fixture", "PURPOSE": "fixture",
            "STUDIO_ROOT": studio_root,
        }
        cfg = json.loads(template("studio/config.json.tmpl", values))
        os.makedirs(os.path.join(repo, ".claude", "studio"))
        with open(os.path.join(repo, ".claude", "studio", "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        with open(os.path.join(repo, ".claude", "studio", "charter.md"), "w") as f:
            f.write(template("studio/charter.md.tmpl", values))
        with open(os.path.join(repo, ".gitignore"), "w") as f:
            f.write(template("studio/gitignore.tmpl", values))
        os.makedirs(os.path.join(repo, studio_root, "voices"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")
    if harness and s2v:
        machine.write(repo, s2v)  # this machine's s2v path (ignored; m1-plan §3.1)
    if local:
        os.makedirs(os.path.join(repo, studio_root, "local"), exist_ok=True)
        os.makedirs(os.path.join(repo, ".claude", "studio", "local"), exist_ok=True)
    if marker:
        m = paths.marker_path(repo)
        os.makedirs(os.path.dirname(m), exist_ok=True)
        with open(m, "w") as f:
            json.dump({"studio_root": studio_root}, f)
    return repo


# ---------- Claude Code hook inputs ----------


def hook_input(tool, tool_input, cwd, transcript=None, mode="default", session_id="test-session",
               tool_use_id="toolu_test"):
    """A PreToolUse hook input (fields to be checked against the M0d-0 measurement)."""
    return {
        "session_id": session_id,
        "transcript_path": transcript,
        "cwd": cwd,
        "permission_mode": mode,
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": tool_use_id,
    }


def fake_transcript(path, events):
    """A transcript JSONL. Placeholder: the real line format is fixed by measurement M0d-0."""
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return path
