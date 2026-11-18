"""guildcore.version — the ACTIVE plugin version check (design §10.3 R5C-m1, R5F-m6).

Source of truth = `claude plugin list --json` run with `cwd` = the worktree and the SAME `CLAUDE_CONFIG_DIR`
as the session being checked; `claude` is the absolute executable path (`shutil.which` — a shell function
prints an account banner into stdout and breaks the JSON); timeout 10 s. The engine never reads its own
`plugin.json` to answer "which version is active": the plugin cache keeps every version's directory, so the
file next to the running code always agrees with itself.

Outcomes (`check`):
* exactly one enabled `guild-plugin@*` ∧ version == mine → ("ok", ver)
* one enabled with another version, or ≥ 2 enabled → ("mismatch", detail) — exit 6 `halted: plugin version
  mismatch` (the supervisor maps it to `halted:plugin-version-changed`)
* none enabled → `GLD_ENGINE_DEV=1` (isolated config dir, `--plugin-dir` development) → ("dev", "unlisted (dev)");
  else ("not-listed", …) — exit 6 `halted: env plugin-not-listed`
* the CLI failed / timed out / printed no JSON → one retry after 5 s → ("unavailable", why): a warning
  `version-check-unavailable`, the run goes on (`version: unknown`, never recorded as a match).
"""

import json
import os
import shutil
import subprocess
import time

PLUGIN = "guild-plugin"


def own_version(here=None):
    """The version of the code that is running (its own plugin.json — used only as "mine")."""
    here = here or os.path.dirname(os.path.abspath(__file__))
    for up in range(1, 7):
        cand = os.path.join(here, *([".."] * up + [".claude-plugin", "plugin.json"]))
        if os.path.isfile(cand):
            try:
                with open(cand, encoding="utf-8") as fh:
                    return json.load(fh).get("version")
            except (IOError, ValueError):
                return None
    return None


def _run(argv, cwd, env, timeout):
    p = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode != 0:
        raise OSError("claude plugin list exited %d" % p.returncode)
    return p.stdout.decode("utf-8", "replace")


def active(cwd, env=None, claude=None, runner=None, timeout=10):
    """[version of each ENABLED guild-plugin@* entry]; raises on a CLI / parse failure."""
    env = dict(os.environ if env is None else env)
    claude = claude or shutil.which("claude", path=env.get("PATH"))
    if not claude:
        raise OSError("claude not on PATH")
    out = (runner or _run)([os.path.realpath(claude), "plugin", "list", "--json"], cwd, env, timeout)
    data = json.loads(out)
    if not isinstance(data, list):
        raise ValueError("plugin list is not a JSON array")
    return [str(e.get("version")) for e in data
            if isinstance(e, dict) and str(e.get("id") or "").split("@")[0] == PLUGIN and e.get("enabled")]


def check(mine, cwd, env=None, claude=None, runner=None, sleep=time.sleep):
    env = os.environ if env is None else env
    last = None
    for attempt in (1, 2):
        try:
            vers = active(cwd, env, claude, runner)
            break
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            last = "%s: %s" % (e.__class__.__name__, e)
            if attempt == 1:
                sleep(5)
    else:
        return "unavailable", last
    if len(vers) == 1 and vers[0] == str(mine):
        return "ok", vers[0]
    if len(vers) >= 2:
        return "mismatch", "%d enabled guild-plugin entries (%s)" % (len(vers), ", ".join(vers))
    if len(vers) == 1:
        return "mismatch", "active %s, this engine %s" % (vers[0], mine)
    if env.get("GLD_ENGINE_DEV") == "1":
        return "dev", "unlisted (dev)"
    return "not-listed", "no enabled guild-plugin in this config dir"
