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


# Q23: package registries a role may reach from the OS sandbox (GitHub is never listed — roles
# get Issue/PR content as in/ files and the engine does every GitHub write)
REGISTRY_DOMAINS = {
    "pubspec.yaml": ("pub.dev", "pub.dartlang.org", "storage.googleapis.com"),
    "package.json": ("registry.npmjs.org", "registry.yarnpkg.com"),
    "pyproject.toml": ("pypi.org", "files.pythonhosted.org"),
    "setup.cfg": ("pypi.org", "files.pythonhosted.org"),
    "requirements.txt": ("pypi.org", "files.pythonhosted.org"),
    "go.mod": ("proxy.golang.org", "sum.golang.org"),
    "Cargo.toml": ("crates.io", "static.crates.io", "index.crates.io"),
}
GITHUB_DOMAINS = ("github.com", "api.github.com", "codeload.github.com", "uploads.github.com",
                  "objects.githubusercontent.com", "raw.githubusercontent.com")


def registry_domains(worktree):
    out = []
    for f, doms in REGISTRY_DOMAINS.items():
        if worktree and os.path.exists(os.path.join(worktree, f)):
            out += [d for d in doms if d not in out]
    return out


def git_dirs(worktree):
    """(gitdir, common_dir) of a worktree, absolute."""
    rc, a = _git(worktree, "rev-parse", "--path-format=absolute", "--git-dir")
    rc2, b = _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc or rc2:
        raise SettingsError("not a git repository: %s" % worktree)
    return a.decode().strip(), b.decode().strip()


def role_sandbox(role_key, worktree, run_dir, issue=None):
    """The Q23 sandbox block, forced AFTER the merge (a user/local `enabled:false`,
    `excludedCommands` or `allowUnsandboxedCommands` cannot weaken it)."""
    allow_w = []
    if run_dir:
        allow_w.append(os.path.abspath(run_dir) + "/**")
    deny_w = []
    if worktree:
        wt = os.path.abspath(worktree)
        gitdir, common = git_dirs(worktree)
        if role_key in ("developer", "qa"):
            allow_w.append(wt + "/**")
            # commits write objects/refs/index — in the common dir (and the linked gitdir)
            allow_w += [common + "/**"] + ([gitdir + "/**"] if gitdir != common else [])
        elif role_key == "tester-cases" and issue is not None:
            allow_w.append(os.path.join(wt, "docs", "specs", str(issue)) + "/**")
        elif role_key == "tech-writer":
            allow_w.append(os.path.join(wt, "docs") + "/**")
        if role_key not in ("developer", "qa", "tester-cases", "tech-writer"):
            # the CLI sandbox lets a command write its cwd by default — a reader must not
            # (verified with the real CLI: without this a reader's write to the worktree landed)
            deny_w.append(wt + "/**")
        for g in sorted(set([gitdir, common])):
            deny_w += [g + "/hooks/**", g + "/config", g + "/config.worktree", g + "/info/**"]
        deny_w += [wt + "/.claude/**", os.path.join(main_checkout(worktree), ".claude") + "/**"]
    deny_w = list(dict.fromkeys(deny_w))
    return {"enabled": True, "allowUnsandboxedCommands": False, "autoAllowBashIfSandboxed": False,
            "excludedCommands": [],
            "filesystem": {"allowWrite": allow_w, "denyWrite": deny_w},
            "network": {"allowedDomains": registry_domains(worktree)}}


class Sources(object):
    """User and local settings read ONCE at engine start (K1-B2: a role must not change what a
    later session is rendered from). Project settings come from the base snapshot per render."""

    def __init__(self, user_settings=None, worktree=None, env=None):
        self.user_p = user_settings or user_settings_path(env)
        self.user = _load(self.user_p) or {}
        self.local_p = os.path.join(main_checkout(worktree), LOCAL_REL) if worktree else None
        self.local = (_load(self.local_p) or {}) if self.local_p else {}


def render(role, task=None, worktree=None, base=None, run_dir=None, issue=None, toolchain=(),
           extra_allow=(), user_settings=None, hooks=True, extra_hooks=None, env=None,
           sources=None, sandbox=None):
    """Render the settings for one session. `role="judge"` (and explorer/auditor callers that pass
    hooks=False) get no hooks. `user_settings` = path override (tests); default is the running
    session's config dir. Writes `<run_dir>/in/settings.json` when run_dir is given."""
    src = sources or Sources(user_settings, worktree, env)
    user_p, user, local_p, local = src.user_p, src.user, src.local_p, src.local
    project, base_sha, main = None, None, None
    if worktree:
        if base:
            project, base_sha = base_project_settings(worktree, base)
        main = main_checkout(worktree)
    project = project or {}
    sources = [("user", user), ("project", project), ("local", local)]
    allow, deny = permissions.role_rules(role, task, run_dir=run_dir, worktree=worktree,
                                         issue=issue, toolchain=toolchain, extra_allow=extra_allow)
    for _, s in sources:
        perms = s.get("permissions") or {}
        # `ask` too (K1-M5): under dontAsk an ask is a refusal; dropping it would turn it into an
        # allow once the allow list is bare `Bash`
        for d in list(perms.get("deny") or []) + list(perms.get("ask") or []):
            if isinstance(d, str) and d not in deny:
                deny.append(d)
    merged_env, merged_sandbox = {}, None
    for _, s in sources:
        if isinstance(s.get("env"), dict):
            merged_env.update({str(k): str(v) for k, v in s["env"].items()})
        if isinstance(s.get("sandbox"), dict):
            merged_sandbox = (merge_values(merged_sandbox, s["sandbox"]) if merged_sandbox is not None
                              else copy.deepcopy(s["sandbox"]))
    out = {"permissions": {"allow": allow, "deny": deny}}
    rk = permissions.role_key(role, task)
    if sandbox is None:
        sandbox = permissions.ROLE_CLASSES.get(rk) not in (None, ()) and role != "judge"
    if sandbox:
        forced = role_sandbox(rk, worktree, run_dir, issue)
        out["sandbox"] = forced      # Q23: the role sandbox is the engine's, not merged
    elif merged_sandbox is not None:
        out["sandbox"] = merged_sandbox
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
