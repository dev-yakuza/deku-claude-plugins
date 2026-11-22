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
import re
import subprocess

from guildcore.fsafe import tmp_name
from guildcore.roles import permissions
from guildcore.roles import scope as SC

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
    os.makedirs(dest, exist_ok=True)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
    arch = subprocess.Popen(["git", "archive", "--format=tar", "%s:%s" % (base_sha, GATES_REL)],
                            cwd=worktree, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    tar = subprocess.run(["tar", "-x", "-C", dest], stdin=arch.stdout, stderr=subprocess.PIPE)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
    arch.stdout.close()
    if arch.wait() != 0 or tar.returncode != 0:
        raise SettingsError("could not export gates from %s" % base_sha[:12])
    # K3 (k1-notes 발견): the gate's config — its `gates` off-switch above all — comes from <base>
    # too. The gate reads `GUILD_GATE_CONFIG` when set (hooks and the role env carry it); a branch
    # that edits `.claude/guild/config.json` cannot turn the gate off for its own commits.
    rc, cfg = _git(worktree, "show", "%s:.claude/guild/config.json" % base_sha)
    with open(os.path.join(dest, GATE_CONFIG_NAME), "w", encoding="utf-8") as fh:  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
        fh.write(cfg.decode("utf-8", "replace") if rc == 0 else "{}\n")
    return True


GATE_CONFIG_NAME = ".config.json"

# lefthook's own config search order — the one list in `scope` (K4r2-m9: the 1L checks read the same)
LEFTHOOK_NAMES = SC.LEFTHOOK_NAMES


def base_lefthook_env(worktree, base_sha, dest_dir):
    """User decision (2026-11-18, K3 carry-over 7): a role's own `git commit` runs the lefthook
    pre-commit with <base>'s config — the SAME source as the engine's 1L checks — never the branch's
    (editing lefthook.yml on the branch stays allowed; it just does not gate the branch's own
    commits). The base copy goes into the run dir's `in/` (roles denyWrite) and lefthook reads it via
    `LEFTHOOK_CONFIG`; a base without any lefthook config → `LEFTHOOK=0` (a config the branch added
    never runs as the hook); no base (or no worktree) → `LEFTHOOK=0` too — fail closed (K4r2-m2).
    lefthook still merges a `lefthook-local.*` overlay on top of `LEFTHOOK_CONFIG`; no role can
    create or change one (K4r2-m1: `scope.PROTECTED`, denyWrite in every role sandbox, watched by the
    integrity snapshot even when gitignored), and a writer role does not start while one exists that
    <base> does not carry (`runner.lefthook_local_problem`)."""
    if not worktree or not base_sha or not dest_dir:
        return {"LEFTHOOK": "0"}
    for name in LEFTHOOK_NAMES:
        rc, out = _git(worktree, "show", "%s:%s" % (base_sha, name))
        if rc == 0:
            path = os.path.join(dest_dir, "lefthook-base." + name.rsplit(".", 1)[1])
            os.makedirs(dest_dir, exist_ok=True)  # fs-ok: the run dir's in/ — created by the engine, roles denyWrite in/
            with open(path, "wb") as fh:  # fs-ok: the run dir's in/ — the base lefthook copy, roles denyWrite in/
                fh.write(out)
            os.chmod(path, 0o444)  # fs-ok: the run dir's in/ — the base lefthook copy made read-only
            return {"LEFTHOOK_CONFIG": path}
    return {"LEFTHOOK": "0"}


def gate_config_path(gates_dir):
    return os.path.join(gates_dir, GATE_CONFIG_NAME) if gates_dir else None


def with_gate_config(hooks, gates_dir):
    """Prefix every hook command that runs an exported gate script with the base config path."""
    if not gates_dir:
        return hooks
    hooks = copy.deepcopy(hooks or {})
    path = gate_config_path(gates_dir)
    for _event, groups in hooks.items():
        for g in groups or []:
            for h in g.get("hooks") or []:
                cmd = h.get("command")
                if isinstance(cmd, str) and gates_dir in cmd and "GUILD_GATE_CONFIG=" not in cmd:
                    h["command"] = "GUILD_GATE_CONFIG='%s' %s" % (path, cmd)
    return hooks


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


SECRET_READ_PATHS = (".ssh", ".config/gh", ".claude", ".claude-personal", ".aws", ".netrc",
                     ".git-credentials", ".config/git/credentials", "Library/Keychains", ".gnupg",
                     ".docker/config.json", ".pub-cache/credentials.json", ".config/gcloud",
                     ".kube", ".npmrc", ".pypirc",
                     # K1r3-M5: shell history/rc files (exported tokens), git config, app stores
                     ".zsh_history", ".bash_history", ".python_history", ".node_repl_history",
                     ".psql_history", ".mysql_history", ".lesshst", ".zshrc", ".zprofile",
                     ".zshenv", ".bashrc", ".bash_profile", ".profile", ".gitconfig",
                     ".config/git/config", ".config/hub", ".config/op", ".config/configstore",
                     "Library/Application Support", "Library/Cookies", ".env", ".envrc")
BUILD_DIRS = (".dart_tool", "build", "coverage", ".pytest_cache", "node_modules/.cache", "target",
              ".gradle", "__pycache__")
WRITER_ROLES = ("developer", "qa")
SCOPED_WRITERS = ("tester-cases", "tech-writer")


def claude_tmp_root():
    """The TMPDIR the CLI sandbox gives every Bash command (shared by ALL of this user's Claude
    Code sessions — K1r2-M2)."""
    return os.path.join("/private/tmp", "claude-%d" % os.getuid())


def engine_home(common_dir):
    """Engine-owned state: `<git-common-dir>/guild/engine` — never writable by a role (K1r2-B2)."""
    return os.path.join(common_dir, "guild", "engine")


def tracked_top_level(worktree):
    rc, out = _git(worktree, "ls-files", "-z")
    tops = set()
    for f in out.decode("utf-8", "replace").split("\0"):
        if f:
            tops.add(f.split("/", 1)[0] + ("/" if "/" in f else ""))
    return sorted(tops)


def role_sandbox(role_key, worktree, run_dir, issue=None, homes=(), config_dir=None,
                 toolchain=False, tool_writes=()):
    """The Q23 sandbox block, forced AFTER the merge (a user/local `enabled:false`,
    `excludedCommands` or `allowUnsandboxedCommands` cannot weaken it). denyWrite beats
    allowWrite in the CLI sandbox (verified), which every rule below relies on.

    * writes: `<run>/out/**` and the role's private `<run>/tmp/**` only; developer/qa the
      worktree and exactly the git internals a commit touches (never `<common>/guild/**`,
      hooks/config/info, other worktrees — K1r2-B2); readers with the toolchain class get the
      gitignored build dirs (`.dart_tool`, `build`, …) and nothing tracked (K1r2-M3);
    * `<run>/in/**`, the engine home (gates, journal, runs) and every other Claude session's
      TMPDIR subtree are denyWrite (K1r2-B1, M2);
    * reads: secrets under every HOME (gh/ssh/claude/aws/keychains/…) are denyRead (K1r2-M1);
    * network: package registries for writers only; readers get none."""
    allow_w, deny_w, deny_r = [], [], []
    if run_dir:
        r = os.path.abspath(run_dir)
        allow_w += [r + "/out/**", r + "/tmp/**"]
        deny_w += [r + "/in/**"]
    if worktree:
        wt = os.path.abspath(worktree)
        gitdir, common = git_dirs(worktree)
        if role_key in WRITER_ROLES:
            allow_w.append(wt + "/**")
            # exactly what `git commit` / `git switch` on the own branch write
            allow_w += [common + "/objects/**", common + "/refs/heads/**", common + "/logs/**",
                        common + "/packed-refs", common + "/packed-refs.lock"]
            if gitdir == common:
                allow_w += [common + x for x in ("/index", "/index.lock", "/HEAD", "/HEAD.lock",
                                                 "/ORIG_HEAD", "/COMMIT_EDITMSG", "/FETCH_HEAD")]
            else:
                allow_w.append(gitdir + "/**")
            wts = os.path.join(common, "worktrees")
            if os.path.isdir(wts):
                for d in sorted(os.listdir(wts)):
                    if os.path.join(wts, d) != gitdir:
                        deny_w.append(os.path.join(wts, d) + "/**")
        elif role_key == "tester-cases" and issue is not None:
            allow_w.append(os.path.join(wt, "docs", "specs", str(issue)) + "/**")
        elif role_key == "tech-writer":
            allow_w.append(os.path.join(wt, "docs") + "/**")
        if role_key not in WRITER_ROLES + SCOPED_WRITERS:
            # the sandbox lets a command write its cwd by default — a reader must not; with the
            # toolchain it may write gitignored build output, never a tracked path
            # Every tracked top-level path is denyWrite (not the worktree root itself: a deny on
            # the cwd breaks bash heredocs in the sandbox — verified); a new untracked file is the
            # post-role check's. With the toolchain, gitignored build dirs are writable.
            if toolchain:
                allow_w += [os.path.join(wt, d) + "/**" for d in BUILD_DIRS]
            for top in tracked_top_level(worktree):
                deny_w.append(os.path.join(wt, top.rstrip("/")) + ("/**" if top.endswith("/") else ""))
        for g in sorted(set([gitdir, common])):
            deny_w += [g + "/hooks/**", g + "/config", g + "/config.worktree", g + "/info/**"]
        deny_w += [engine_home(common) + "/**", common + "/guild/**",
                   wt + "/.claude/**", os.path.join(main_checkout(worktree), ".claude") + "/**"]
        # K4r2-m1: the lefthook-local overlay (gitignored, merged over LEFTHOOK_CONFIG) — path literals,
        # existing or not, in this worktree and the main checkout
        deny_w += SC.lefthook_local_files(wt) + SC.lefthook_local_files(main_checkout(worktree))
    # other Claude Code sessions' TMPDIR subtrees (scratchpads, tasks/*.output): denyWrite —
    # except the one holding this worktree/run (a harness; production keeps worktrees outside)
    tmp = claude_tmp_root()
    # the sandbox forces TMPDIR=/tmp/claude-<uid> for Bash (setting TMPDIR does not change it —
    # verified); heredocs need it writable, so allow it and deny every session subtree in it
    allow_w.append(tmp + "/**")
    keep = [os.path.realpath(x) for x in (worktree, run_dir) if x]
    # a glob for session dirs created AFTER this render (K1r3-m1) — kept alongside the
    # enumerated ones; whether the CLI honours a mid-path glob is recorded in k1-notes
    if not any(k.startswith(tmp + "/-") for k in keep):
        deny_w.append(tmp + "/-*/**")
    if os.path.isdir(tmp):
        for d in sorted(os.listdir(tmp)):
            full = os.path.join(tmp, d)
            if d.startswith("-") and not any(k.startswith(full + "/") for k in keep):
                deny_w.append(full + "/**")
    for h in [os.path.expanduser("~")] + list(homes):
        for rel in SECRET_READ_PATHS:
            deny_r.append(os.path.join(h, rel))
    if config_dir:
        deny_r.append(os.path.abspath(config_dir))
    if role_key in WRITER_ROLES or toolchain:
        allow_w += list(tool_writes)
    # 0.102.16 (review-0102-15 S1): the engine's pnpm store and the user's own are never writable — by a role, a suite,
    # a flake / effective re-run or the refactor net (only the engine's networked `pnpm fetch` lifts the engine one)
    from guildcore.checks import pmcache as PMC
    deny_w += [x + "/**" for x in PMC.protected_stores()]
    deny_w = list(dict.fromkeys(deny_w))
    deny_r = list(dict.fromkeys(deny_r))
    weaker_net = (role_key in WRITER_ROLES and bool(worktree)
                  and os.path.exists(os.path.join(worktree, "pubspec.yaml")))
    return {"enabled": True, "allowUnsandboxedCommands": False, "autoAllowBashIfSandboxed": False,
            "excludedCommands": [],
            # Dart (pub) verifies TLS through macOS trustd, unreachable in the sandbox without
            # this (measured: CERTIFICATE_VERIFY_FAILED; curl unaffected) — writers of Flutter
            # repos only (K1r4-M2); the CLI documents it as a weaker isolation (trustd channel)
            "enableWeakerNetworkIsolation": weaker_net,
            "filesystem": {"allowWrite": allow_w, "denyWrite": deny_w, "denyRead": deny_r},
            # loopback binding: test runners (flutter_tester, jest workers) serve on localhost —
            # measured: `flutter test` fails at HttpServer.bind without it (K1r4-M2)
            "network": {"allowedDomains": registry_domains(worktree) if role_key in WRITER_ROLES else [],
                        "allowLocalBinding": True,
                        # process listing (pgrep/ps-style lookups; user decision K1r5): the
                        # narrowest switch — the one mach service pgrep needs (measured:
                        # "sysmond service not found" without it). No signalling rights.
                        "allowMachLookup": ["com.apple.sysmond"]}}


HOOK_RUNNERS = ("python3", "python", "sh", "bash", "node", "ruby", "perl")
_PROJ_REF = re.compile(r"\$\{?CLAUDE_PROJECT_DIR\}?/([^\s\"']+)")


def base_only_hooks(worktree, base_sha, hooks):
    """Every project hook must execute ONLY bytes from the base snapshot (K1r3-B2: hooks run
    outside the sandbox). A command's `${CLAUDE_PROJECT_DIR}/<path>` references are exported
    from `<base>` (the referenced file's directory) into the read-only engine home and
    rewritten there. A hook that would still run something from the worktree — no project
    reference at all (`npx prettier`, `npm run x`), a launcher outside HOOK_RUNNERS, a
    reference left unrewritten — is DROPPED and reported. Returns (hooks, [(dir, digest)],
    [dropped command])."""
    _gitdir, common = git_dirs(worktree)
    out, files, dropped = {}, [], []
    for event, groups in (hooks or {}).items():
        keep_groups = []
        for g in groups or []:
            keep = []
            for hk in g.get("hooks") or []:
                cmd = hk.get("command")
                if not isinstance(cmd, str):
                    dropped.append({"event": event, "matcher": g.get("matcher"), "hook": hk})
                    continue
                gates_root = os.path.join(engine_home(common), "gates")
                ok = True
                for rel in sorted(set(_PROJ_REF.findall(cmd))):
                    d = os.path.dirname(rel) or "."
                    dest, digest = export_tree_readonly(worktree, base_sha, d,
                                                        os.path.join(engine_home(common), "hooks", base_sha, d))
                    if not dest:
                        ok = False
                        break
                    files.append((dest, digest))
                    cmd = re.sub(r"\$\{?CLAUDE_PROJECT_DIR\}?/" + re.escape(rel),
                                 os.path.join(dest, os.path.basename(rel)), cmd)
                words = cmd.split()
                first = words[0].strip("\"'") if words else ""
                launcher_ok = os.path.basename(first) in HOOK_RUNNERS or first.startswith(engine_home(common))
                refs_engine = engine_home(common) in cmd or gates_root in cmd
                if not ok or "CLAUDE_PROJECT_DIR" in cmd or not launcher_ok or not refs_engine:
                    dropped.append({"event": event, "matcher": g.get("matcher"), "hook": hk})
                    continue
                keep.append(dict(hk, command=cmd))
            if keep:
                keep_groups.append(dict(g, hooks=keep))
        if keep_groups:
            out[event] = keep_groups
    return out, files, dropped


def export_tree_readonly(worktree, base_sha, rel_dir, dest):
    """`git archive <base>:<rel_dir>` into dest once, read-only, digest-stamped; (dest, digest)
    or (None, None) when the base has no such tree."""
    stamp = dest + ".sha256"
    if os.path.isdir(dest) and os.path.exists(stamp):
        with open(stamp) as fh:
            want = fh.read().strip()
        if tree_digest(dest) == want:
            return dest, want
        import shutil
        for base, _d, _f in os.walk(dest):
            os.chmod(base, 0o755)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
        shutil.rmtree(dest)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
    rc, _ = _git(worktree, "cat-file", "-e", "%s:%s" % (base_sha, rel_dir if rel_dir != "." else ""))
    if rc != 0:
        return None, None
    os.makedirs(os.path.dirname(dest), exist_ok=True)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
    tmp = tmp_name(dest)          # review-k6-r10 m5 / m6: unique per call, so two engines never share it
    tree = "%s:%s" % (base_sha, rel_dir) if rel_dir != "." else base_sha
    try:
        os.mkdir(tmp)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
        arch = subprocess.Popen(["git", "archive", "--format=tar", tree], cwd=worktree,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            tar = subprocess.run(["tar", "-x", "-C", tmp], stdin=arch.stdout, stderr=subprocess.PIPE)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
        finally:
            arch.stdout.close()
            arch.wait()
        if arch.returncode != 0 or tar.returncode != 0:
            return None, None
        return _publish_readonly(tmp, dest)
    finally:
        _drop_tree(tmp)           # review-k6-r12 m3: the extraction too — whatever failed, no litter


SAFE_GIT_KEYS = re.compile(r"^(init\.defaultbranch|core\.autocrlf|core\.symlinks|core\.ignorecase|"
                           r"core\.precomposeunicode|core\.quotepath|filter\.lfs\.[a-z]+|"
                           r"pull\.rebase|merge\.conflictstyle|diff\.algorithm|color\.[a-z.]+)$")


def render_gitconfig(worktree, dest):
    """The role's GLOBAL git config (K1r4-M1): `~/.gitconfig` is denyRead and git aborts on an
    unreadable global config (rc 128), so the engine — outside the sandbox — writes a SAFE one:
    user.name/email as resolved for this worktree (includeIf honoured) and a short list of
    harmless keys. Never credential helpers, aliases, includes, url rewrites, hooksPath,
    sshCommand or signing (keys are denyRead)."""
    lines = []
    p = subprocess.run(["git", "config", "--global", "--list"], cwd=worktree or None,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    kept = {}
    for ln in p.stdout.decode("utf-8", "replace").splitlines():
        if "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        if SAFE_GIT_KEYS.match(k.lower()):
            kept[k.lower()] = v
    for k in ("user.name", "user.email"):
        q = subprocess.run(["git", "config", "--get", k], cwd=worktree or None,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        v = q.stdout.decode().strip()
        if v:
            kept[k] = v
    sections = {}
    for k, v in sorted(kept.items()):
        parts = k.split(".")
        sec = parts[0] if len(parts) == 2 else '%s "%s"' % (parts[0], ".".join(parts[1:-1]))
        sections.setdefault(sec, []).append((parts[-1], v))
    for sec, kvs in sections.items():
        lines.append("[%s]" % sec)
        lines += ["\t%s = %s" % (k, v.replace("\\", "\\\\").replace('"', '\\"')) for k, v in kvs]
    os.makedirs(os.path.dirname(dest), exist_ok=True)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
    with open(dest, "w", encoding="utf-8") as fh:  # fs-ok: engine home export / run dir in/ (roles denyWrite)
        fh.write("\n".join(lines) + "\n")
    return {"GIT_CONFIG_GLOBAL": dest, "GIT_CONFIG_NOSYSTEM": "1"}


def flutter_sdk(worktree):
    """The Flutter SDK a worktree uses (`.fvm/flutter_sdk`, `.fvmrc`, or `flutter` on PATH)."""
    if not worktree or not os.path.exists(os.path.join(worktree, "pubspec.yaml")):
        return None
    link = os.path.join(worktree, ".fvm", "flutter_sdk")
    if os.path.exists(link):
        return os.path.realpath(link)
    try:
        with open(os.path.join(worktree, ".fvmrc"), encoding="utf-8") as fh:
            v = json.load(fh).get("flutter")
        cand = os.path.join(os.path.expanduser("~"), "fvm", "versions", str(v))
        if v and os.path.isdir(cand):
            return cand
    except (IOError, OSError, ValueError):
        pass
    import shutil as _sh
    f = _sh.which("flutter")
    if f:
        return os.path.dirname(os.path.dirname(os.path.realpath(f)))
    return None


TOOLCHAIN_CACHES = {
    "pubspec.yaml": (".pub-cache", ".dart-tool", ".dartServer", ".flutter", ".flutter-devtools",
                     ".config/flutter", "fvm", "Library/Caches/flutter_engine"),
    # 0.102.16 (review-0102-15 S1): no `Library/pnpm` — the engine installs pnpm dependencies itself (offline, from its
    # own store); a suite or a role writing a pnpm store would poison every later install (the user's, outside any
    # sandbox, too). Every pnpm store is denyWrite in every sandbox (`role_sandbox`).
    "package.json": (".npm", ".yarn", "Library/Caches/Yarn", ".cache/node-gyp"),
    "pyproject.toml": (".cache/pip", "Library/Caches/pip", ".cache/uv"),
    "requirements.txt": (".cache/pip", "Library/Caches/pip"),
    "go.mod": ("go/pkg/mod", "Library/Caches/go-build"),
    "Cargo.toml": (".cargo/registry", ".cargo/git"),
}


def toolchain_writes(worktree, user_sandbox=None, home=None):
    """Tool caches a toolchain writes on EVERY run (K1r4-M2, measured with word_app): the SDK
    itself (`bin/cache` stamps), the per-manifest caches, plus the user's own
    `sandbox.filesystem.allowWrite` entries (this user listed fvm, pub-cache, gradle, Xcode,
    cocoapods for exactly this reason). Never anything under SECRET_READ_PATHS."""
    home = home or os.path.expanduser("~")
    out = []
    # the per-user system temp dir (`mktemp -t` falls back to it — word_app's
    # verify_test_coverage.sh, measured EPERM): private to this user, not shared with other
    # Claude sessions
    try:
        ut = subprocess.run(["getconf", "DARWIN_USER_TEMP_DIR"], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL).stdout.decode().strip()
        if ut:
            out.append(os.path.realpath(ut).rstrip("/") + "/**")
    except OSError:
        pass
    sdk = flutter_sdk(worktree)
    if sdk:
        out.append(sdk + "/**")
    for f, rels in TOOLCHAIN_CACHES.items():
        if worktree and os.path.exists(os.path.join(worktree, f)):
            out += [os.path.join(home, r) + "/**" for r in rels]
    for a in ((user_sandbox or {}).get("filesystem") or {}).get("allowWrite") or []:
        a2 = os.path.expanduser(a)
        homes_ = {home, os.path.expanduser("~")}
        if not any(a2.startswith(os.path.join(h, sec)) for h in homes_ for sec in SECRET_READ_PATHS):
            out.append(a2 if a2.endswith("/**") else a2.rstrip("/") + "/**")
    return list(dict.fromkeys(out))


def gates_home(common_dir, base_sha):
    return os.path.join(engine_home(common_dir), "gates", base_sha)


def tree_digest(root):
    import hashlib
    h = hashlib.sha256()
    for base, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        for f in sorted(files):
            fp = os.path.join(base, f)
            h.update(os.path.relpath(fp, root).encode())
            with open(fp, "rb") as fh:
                h.update(hashlib.sha256(fh.read()).digest())
    return h.hexdigest()


def export_gates_readonly(worktree, base_sha):
    """Export `<base>:.claude/guild/gates` ONCE per base into the engine home (outside every
    role's allowWrite, and denyWrite), make it read-only, and return (dir, digest) — or
    (None, None) when the base has no gates (K1r2-B1). An existing export is re-verified."""
    _gitdir, common = git_dirs(worktree)
    dest = gates_home(common, base_sha)
    stamp = dest + ".sha256"
    if os.path.isdir(dest) and os.path.exists(stamp):
        with open(stamp) as fh:
            want = fh.read().strip()
        if tree_digest(dest) == want:
            return dest, want
        import shutil
        for base, dirs, files in os.walk(dest):
            os.chmod(base, 0o755)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
        shutil.rmtree(dest)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
    os.makedirs(os.path.dirname(dest), exist_ok=True)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
    tmp = tmp_name(dest)          # review-k6-r10 m5 / m6: unique per call, so two engines never share it
    try:
        if not export_gates(worktree, base_sha, tmp):
            return None, None
        return _publish_readonly(tmp, dest)
    finally:
        _drop_tree(tmp)           # review-k6-r11 m1: whatever failed (or nothing left after the rename) — no litter


def _drop_tree(path):
    """Remove an engine-owned temp export (read-only after `_publish_readonly`'s chmod) — quietly."""
    if not os.path.lexists(path):
        return
    for base, _d, _f in os.walk(path):
        try:
            os.chmod(base, 0o755)  # fs-ok: engine export dir (our own temp tree) — engine-owned destination
        except OSError:
            pass
    import shutil
    shutil.rmtree(path, ignore_errors=True)  # fs-ok: engine export dir (our own temp tree) — engine-owned destination


def _publish_readonly(tmp, dest):
    """Make the extracted `tmp` read-only and rename it to `dest`, then stamp its digest — (dest, digest).
    review-k6-r10 m6: two engines (two Issues of one sprint, same base) may export the same `dest` at once. The
    directory rename fails for the later one (`dest` already there, non-empty): when `dest` holds the SAME tree (its
    digest equals ours) the later engine uses it and drops its own temp tree; a different tree raises as before. The
    stamp is written through a temp file + `os.replace`, so a reader never sees it half written."""
    try:
        return _publish(tmp, dest)
    finally:
        _drop_tree(tmp)           # review-k6-r11 m1: a chmod / rename / stamp failure leaves no temp tree behind


def _publish(tmp, dest):
    digest = tree_digest(tmp)
    for base, _dirs, fs in os.walk(tmp, topdown=False):
        for f in fs:
            fp = os.path.join(base, f)
            os.chmod(fp, 0o555 if os.access(fp, os.X_OK) else 0o444)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
        os.chmod(base, 0o555)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
    try:
        os.replace(tmp, dest)  # fs-ok: engine home export / run dir in/ (roles denyWrite)
    except OSError:
        if not (os.path.isdir(dest) and not os.path.islink(dest) and tree_digest(dest) == digest):
            raise
        # the other engine's export of the same base — identical; use it (the caller drops our temp tree)
    stamp_tmp = tmp_name(dest + ".sha256")
    try:
        with open(stamp_tmp, "x") as fh:  # fs-ok: engine home export / run dir in/ (roles denyWrite)
            fh.write(digest + "\n")
        os.replace(stamp_tmp, dest + ".sha256")  # fs-ok: engine home export / run dir in/ (roles denyWrite)
    finally:
        if os.path.lexists(stamp_tmp):
            os.unlink(stamp_tmp)  # fs-ok: our own temp stamp (review-k6-r11 m1)
    return dest, digest


def verify_gates(gates_dir, digest):
    """Before each session: the hook scripts are still the exported bytes."""
    return bool(gates_dir) and os.path.isdir(gates_dir) and tree_digest(gates_dir) == digest


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
        e = env or os.environ
        homes = [x for x in (e.get("HOME"),) if x]
        tw = toolchain_writes(worktree, merged_sandbox, home=os.path.expanduser("~"))
        forced = role_sandbox(rk, worktree, run_dir, issue, homes=homes,
                              config_dir=e.get("CLAUDE_CONFIG_DIR"),
                              toolchain="C4" in (permissions.ROLE_CLASSES.get(rk) or ()),
                              tool_writes=tw)
        out["sandbox"] = forced      # Q23: the role sandbox is the engine's, not merged
    elif merged_sandbox is not None:
        out["sandbox"] = merged_sandbox
    gates_dir, gates_digest, hook_files, dropped = None, None, [], []
    if hooks and project.get("hooks"):
        h = project["hooks"]
        if base_sha:
            gates_dir, gates_digest = export_gates_readonly(worktree, base_sha)
            if gates_dir:
                h = rewrite_hook_commands(h, gates_dir)
            h, hook_files, dropped = base_only_hooks(worktree, base_sha, h)
            h = with_gate_config(h, gates_dir)
        else:
            dropped = ["(no base snapshot) every project hook"]
            h = {}
        if h:
            out["hooks"] = copy.deepcopy(h)
    wrapped, skipped = [], []
    if dropped and isinstance(dropped[0], dict):
        # K1r4 (a): a hook that must run worktree code (`npx prettier`, `npm run format`) runs
        # inside the role's own sandbox via sandbox-exec instead of being dropped
        from guildcore.checks import SANDBOX_EXEC, sandbox_profile
        if run_dir and out.get("sandbox") and os.path.exists(SANDBOX_EXEC):
            prof = os.path.join(run_dir, "in", "hook-sandbox.sb")
            os.makedirs(os.path.dirname(prof), exist_ok=True)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
            with open(prof, "w") as fh:  # fs-ok: engine home export / run dir in/ (roles denyWrite)
                fh.write(sandbox_profile(out["sandbox"]))
            os.chmod(prof, 0o444)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
            hk = out.setdefault("hooks", {})
            for d in dropped:
                cmd = d["hook"].get("command")
                if not isinstance(cmd, str):
                    skipped.append(d)
                    continue
                new_cmd = "%s -f '%s' /bin/sh -c %s" % (SANDBOX_EXEC, prof, "'" + cmd.replace("'", "'\\''") + "'")
                grp = {"hooks": [dict(d["hook"], command=new_cmd)]}
                if d.get("matcher") is not None:
                    grp["matcher"] = d["matcher"]
                hk.setdefault(d["event"], []).append(grp)
                wrapped.append(cmd)
        else:
            skipped = list(dropped)
    if extra_hooks:
        hk = out.setdefault("hooks", {})
        for ev, groups in extra_hooks.items():
            hk.setdefault(ev, [])
            hk[ev] = list(hk[ev]) + list(groups)
    meta = {"user_settings": user_p, "project_base": base, "project_base_sha": base_sha,
            "local_settings": local_p, "main_checkout": main, "gates_dir": gates_dir,
            "gates_digest": gates_digest, "hook_files": hook_files,
            "hooks_sandboxed": wrapped,
            "hooks_skipped": [d["hook"].get("command") if isinstance(d, dict) else d for d in skipped],
            "routing_in_settings_env": sorted(k for k in merged_env if k in ROUTING_KEYS)}
    path = None
    if run_dir:
        os.makedirs(os.path.join(run_dir, "in"), exist_ok=True)  # fs-ok: engine export dir (base content) or the run dir in/ — engine-owned destination
        path = os.path.join(run_dir, "in", "settings.json")
        with open(path, "w", encoding="utf-8") as fh:  # fs-ok: engine home export / run dir in/ (roles denyWrite)
            json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
    return Rendered(out, merged_env, meta, path)
