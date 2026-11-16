"""guildcore.roles.settings — the `--settings` JSON every engine-spawned `claude -p` runs under (§5.1).

Every session runs with `--setting-sources ""` (user, project and local settings all OFF) plus
`--settings <run>/in/settings.json` rendered here, so the effective allow list is exactly the
role's list (§1.4: dontAsk's allow = `--allowedTools` ∪ every loaded `permissions.allow`).
Turning the sources off also drops things that must survive, so the engine carries them over,
merged user → project → local:

* `permissions.deny` — the UNION of every source (monotone safe) + ALWAYS_DENY + the role's own;
* `env`            — merged, returned for the CHILD PROCESS env (never written into the
                     settings file: settings `env` would be applied over the engine's §5.1 env
                     contract, and the contract must win);
* `sandbox`        — the effective block (dicts merged, lists unioned, later scalars win).

`permissions.allow` and user hooks are NOT carried. Hooks come from the project settings of the
BASE snapshot (`git show <base>:.claude/settings.json`), never the branch HEAD: a developer's
`sed -i .claude/settings.json` + commit must not change the next role's INV2 gate (R7C-m2).
The gate scripts are exported from the same base with `git archive` into `<run>/in/gates/`
and the hook commands' `${CLAUDE_PROJECT_DIR}/.claude/guild/gates/` is rewritten to that path
(R7F-m1). Local settings (`.claude/settings.local.json`, gitignored) come from the MAIN
checkout. Base sha and every source path are recorded in the returned meta (→ ctx).
"""

import copy
import json
import os
import subprocess

from guildcore.roles import permissions

GATES_REL = ".claude/guild/gates"
PROJECT_REL = ".claude/settings.json"
LOCAL_REL = ".claude/settings.local.json"
GATES_VAR_FORMS = ("${CLAUDE_PROJECT_DIR}/" + GATES_REL + "/", "$CLAUDE_PROJECT_DIR/" + GATES_REL + "/")
# model-routing keys: guarded like the process env (§5.1 엔드포인트 가드)
ROUTING_KEYS = ("ANTHROPIC_BASE_URL", "ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_VERTEX_BASE_URL",
                "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                "ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                "CLAUDE_CODE_SUBAGENT_MODEL")


class SettingsError(Exception):
    pass


def user_settings_path(env=None):
    env = os.environ if env is None else env
    base = env.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "settings.json")


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (IOError, OSError):
        return None
    except ValueError as e:
        raise SettingsError("unreadable settings %s: %s" % (path, e))
    return d if isinstance(d, dict) else None


def _git(cwd, *args):
    p = subprocess.run(["git"] + list(args), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout


def base_project_settings(worktree, base):
    """(settings|None, base_sha) of `<base>:.claude/settings.json`."""
    rc, sha = _git(worktree, "rev-parse", "--verify", base + "^{commit}")
    if rc != 0:
        raise SettingsError("base %r does not resolve in %s" % (base, worktree))
    sha = sha.decode().strip()
    rc, out = _git(worktree, "show", "%s:%s" % (sha, PROJECT_REL))
    if rc != 0:
        return None, sha
    try:
        d = json.loads(out.decode("utf-8"))
    except ValueError as e:
        raise SettingsError("base %s .claude/settings.json is not JSON: %s" % (sha[:12], e))
    return (d if isinstance(d, dict) else None), sha


def main_checkout(worktree):
    """The main checkout of the repo (the worktree of `git rev-parse --git-common-dir`)."""
    rc, out = _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc != 0:
        raise SettingsError("not a git repository: %s" % worktree)
    common = out.decode().strip()
    return os.path.dirname(common) if os.path.basename(common) == ".git" else common


def export_gates(worktree, base_sha, dest):
    """`git archive <base>:.claude/guild/gates` into `dest`; returns True when the base has gates."""
    rc, _ = _git(worktree, "cat-file", "-e", "%s:%s" % (base_sha, GATES_REL))
    if rc != 0:
        return False
    os.makedirs(dest, exist_ok=True)
    arch = subprocess.Popen(["git", "archive", "--format=tar", "%s:%s" % (base_sha, GATES_REL)],
                            cwd=worktree, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    tar = subprocess.run(["tar", "-x", "-C", dest], stdin=arch.stdout, stderr=subprocess.PIPE)
    arch.stdout.close()
    if arch.wait() != 0 or tar.returncode != 0:
        raise SettingsError("could not export gates from %s" % base_sha[:12])
    return True


def merge_values(a, b):
    """Deep merge for `sandbox`/`env`: dicts recurse, lists union in order, scalars → b."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = copy.deepcopy(a)
        for k, v in b.items():
            out[k] = merge_values(out[k], v) if k in out else copy.deepcopy(v)
        return out
    if isinstance(a, list) and isinstance(b, list):
        out = list(a)
        for x in b:
            if x not in out:
                out.append(x)
        return out
    return copy.deepcopy(b)


def rewrite_hook_commands(hooks, gates_dir):
    """Hooks with `${CLAUDE_PROJECT_DIR}/.claude/guild/gates/` → `<gates_dir>/`."""
    hooks = copy.deepcopy(hooks or {})
    target = os.path.abspath(gates_dir).rstrip("/") + "/"
    for event, groups in hooks.items():
        for g in groups or []:
            for h in g.get("hooks") or []:
                cmd = h.get("command")
                if isinstance(cmd, str):
                    for form in GATES_VAR_FORMS:
                        cmd = cmd.replace(form, target)
                    h["command"] = cmd
    return hooks


class Rendered(object):
    def __init__(self, settings, env, meta, path=None):
        self.settings = settings
        self.env = env          # merged settings env → child process env (under the contract)
        self.meta = meta
        self.path = path


def render(role, task=None, worktree=None, base=None, run_dir=None, issue=None, toolchain=(),
           extra_allow=(), user_settings=None, hooks=True, extra_hooks=None, env=None):
    """Render the settings for one session. `role="judge"` (and explorer/auditor callers that pass
    hooks=False) get no hooks. `user_settings` = path override (tests); default is the running
    session's config dir. Writes `<run_dir>/in/settings.json` when run_dir is given."""
    user_p = user_settings or user_settings_path(env)
    user = _load(user_p) or {}
    project, base_sha, local, local_p, main = None, None, {}, None, None
    if worktree:
        if base:
            project, base_sha = base_project_settings(worktree, base)
        main = main_checkout(worktree)
        local_p = os.path.join(main, LOCAL_REL)
        local = _load(local_p) or {}
    project = project or {}
    sources = [("user", user), ("project", project), ("local", local)]
    allow, deny = permissions.role_rules(role, task, run_dir=run_dir, worktree=worktree,
                                         issue=issue, toolchain=toolchain, extra_allow=extra_allow)
    for _, s in sources:
        for d in ((s.get("permissions") or {}).get("deny") or []):
            if isinstance(d, str) and d not in deny:
                deny.append(d)
    merged_env, sandbox = {}, None
    for _, s in sources:
        if isinstance(s.get("env"), dict):
            merged_env.update({str(k): str(v) for k, v in s["env"].items()})
        if isinstance(s.get("sandbox"), dict):
            sandbox = merge_values(sandbox, s["sandbox"]) if sandbox is not None else copy.deepcopy(s["sandbox"])
    out = {"permissions": {"allow": allow, "deny": deny}}
    if sandbox is not None:
        out["sandbox"] = sandbox
    gates_dir = None
    if hooks and project.get("hooks"):
        h = project["hooks"]
        if run_dir and base_sha and export_gates(worktree, base_sha, os.path.join(run_dir, "in", "gates")):
            gates_dir = os.path.join(run_dir, "in", "gates")
            h = rewrite_hook_commands(h, gates_dir)
        out["hooks"] = copy.deepcopy(h)
    if extra_hooks:
        hk = out.setdefault("hooks", {})
        for ev, groups in extra_hooks.items():
            hk.setdefault(ev, [])
            hk[ev] = list(hk[ev]) + list(groups)
    meta = {"user_settings": user_p, "project_base": base, "project_base_sha": base_sha,
            "local_settings": local_p, "main_checkout": main, "gates_dir": gates_dir,
            "routing_in_settings_env": sorted(k for k in merged_env if k in ROUTING_KEYS)}
    path = None
    if run_dir:
        os.makedirs(os.path.join(run_dir, "in"), exist_ok=True)
        path = os.path.join(run_dir, "in", "settings.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
    return Rendered(out, merged_env, meta, path)
