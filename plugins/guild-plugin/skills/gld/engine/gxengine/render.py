"""Render the boundary of a role session or a run (design §6.2, §7.6, §7.12 S1 S2 S4 S7 S8 S9) — U5.

One function family turns (role, step, paths, repository settings) into:

  settings  the `--settings` JSON of a role session: permissions {allow, deny},
            sandbox {fixed values, filesystem, network}, hooks {PreToolUse Bash gate}
  srt       the `srt --settings` JSON of a run: network + filesystem, all required keys
  argv      the `claude` argument list (§6.2 execution contract, F1/F2) / the `srt` one
  env       the process environment (auth scrubbed, SCRUB=1, cache env, BASH_MAX_TIMEOUT_MS)

Same path lists in two places (S1): sandbox filesystem rules AND permission denies
Read/Grep/Glob/Edit/Write. Write rules are rendered as `Edit(//…)` (F1: `Write(...)`
rules have no effect; they may be rendered too but nothing relies on them). A run gets
the developer's boundary (§7.1). Reads: allowed by default + an explicit deny list (F3).

Two phases (I9): `template(...)` renders with placeholders ({worktree}, {in_dir}, …) —
its hash is the canary key; `substitute(...)` fills the real paths. Example inputs and
outputs: tests/fixtures/render/*.json (key structure frozen in P2-0; the rule lists are
U5's to finalise — interfaces.md).

Rule lists (U5, stage 1):

  read deny     home secrets (defaults.HOME_SECRETS) · the Claude config dir, ~/.claude,
                ~/.claude.json · repository secret globs in the main checkout, the Issue
                worktree and every other worktree · other repository roots · engine records
                (sandbox: the whole records folder, re-opened only for this attempt's in/;
                permissions: per record file name, because a deny on the folder would beat
                the in/ allow — interfaces.md 해석 20)
  write deny    control files (defaults.CONTROL_FILE_GLOBS) in the worktree AND the main
                checkout (S2) · git hooks/config/info/alternates, own worktree
                commondir/gitdir/config.worktree, the worktree gitfile (S4) · `**/.claude`
                and `**/.git` under every write-allowed root and under the sandbox's own
                temp dirs /tmp/claude* (see below) · engine records · everything on the
                read-deny list
  permission    every denied path P is rendered as `T(//P)` AND `T(//P/**)` so the rule holds
                whether P is a file or a folder and whichever glob dialect the CLI applies
  allow write   developer / run: the worktree, the run temp dir, the Guild cache, the git
                common dir's objects/refs/heads/logs/packed-refs and the own worktree git dir
                (§7.6 git row); judge: the step's outputs only (+ the run temp dir)
  network       developer / run: repository registry hosts (+ approved extra hosts);
                judge: none (no Bash)

Why `**/.claude` and `**/.git` are denied under every write-allowed root: the 0.98.7
PreToolUse gate runs OUTSIDE the sandbox and, for `git -C <dir> commit`, resolves `<dir>`
as the repository — it reads `<dir>/.claude/guild/config.json` and imports
`<dir>/.claude/guild/gates/scripts/local/*.py`, and runs git with that repository's
own config. A role that could create a repository with those files in its temp dir would
run code outside the sandbox. Verified against srt 0.0.83: the denies refuse `git init`,
a gitfile, a symlink and a rename onto `.git` / `.claude` (tests/test_render.py). The cost:
a test suite that runs `git init` in its temp dir is red inside the sandbox (the base-green
check shows it; §7.10).

Everything that could weaken the boundary is refused with RenderError (fail-closed):
unsafe or non-canonical paths, a write root that contains a protected path, cache env
outside the Guild cache, unsupported sandbox exceptions, a tool outside the role class
set, a model / effort outside the allow-list, a missing session budget.

Approved sandbox exceptions (repo-config `sandbox_exceptions`, §7.10, P3-B):
  allow_hosts               developer and run: extra network hosts (never a judge role)
  allow_local_binding       developer and run: srt `network.allowLocalBinding: true`;
                            Claude settings `sandbox.network.allowLocalBinding: true`
  weaker_network_isolation  developer and run: srt top-level `enableWeakerNetworkIsolation:
                            true`; Claude settings `sandbox.enableWeakerNetworkIsolation: true`
  allow_write               developer and run: extra write roots (srt / Claude settings
                            `filesystem.allowWrite`); the token `{user_tmp}` is
                            `paths.user_tmp` (macOS `getconf DARWIN_USER_TEMP_DIR`, given
                            canonical by the caller — required when the token is used). Each
                            root is checked like every other write root and gets the nested
                            `.git` / `.claude` deny (sandbox and permission layer).
P5 F2 (coordinator decision, reverses §7.13 "exceptions for runs only"): the developer
session gets the same toolchain environment as a run — cache env, `run_env` and these three
exceptions — so it can run the repository's tests itself (red → green, read the failure).
A judge session never gets them (no Bash; `template()` refuses). The Claude Code key names
are the documented ones (code.claude.com settings reference, CLI 2.1.323). Every exception
is part of the work-role and run templates (`template(..., exceptions=…)`), so turning one
on changes the template hash and forces a new role canary / srt canary (I9).
The developer's PATH and HOME stay the user's (the gate hook and git run OUTSIDE the
sandbox with the session env, so no role-writable folder may enter PATH): the work frame
tells it to run tools with the named command's own `export PATH=… HOME=…` prefix.
A run's srt starts in an EMPTY folder chosen by the runner and the command `cd`s into the
worktree (`export TMPDIR=<run_tmp>; cd <worktree> && <command>`): srt applies its own
built-in write denies (.git/hooks, .git/config, .idea, .vscode, shell rc names, …) to its
whole cwd subtree (measured by the base-green check, session 5).
`run_env` (literal, non-path values) is added to a run's and the developer's env after the scrub.
"""

import fnmatch
import hashlib
import itertools
import json
import os
import re
import shlex

from . import codes, defaults
from . import schema as S

PLACEHOLDERS = (
    "home", "claude_config_dir", "worktree", "main_checkout", "git_common_dir", "own_worktree",
    "engine_records", "in_dir", "run_tmp", "cache", "plugin_root", "issue", "srt_tmpdir",
)
"""Scalar placeholders. List placeholders: {other_worktrees}, {other_repo_roots}, {outputs},
{secret_paths}, {registry_hosts}."""

LIST_PLACEHOLDERS = ("other_worktrees", "other_repo_roots", "outputs", "secret_paths",
                     "registry_hosts", "allow_hosts", "allow_write", "worktree_dirs")
"""`allow_hosts` = repo-config sandbox_exceptions.allow_hosts (approved extra hosts, §7.10);
`allow_write` = sandbox_exceptions.allow_write resolved to absolute roots (run and developer);
`worktree_dirs` = run only: the worktree folders git does NOT ignore (see RUN_NAMED_CONTROL)."""

RUN_NAMED_CONTROL = ("**/CLAUDE.md", "**/CLAUDE.local.md", "**/AGENTS.md")
"""P3-Z decision 6a: in a RUN's srt settings these control-file globs of the worktree are
rendered per folder — `<folder>/CLAUDE.md` for every folder git does not ignore
(`paths.worktree_dirs`, from `git ls-files -co --exclude-standard`, given by the runner) —
so a dependency install may unpack such files under a gitignored folder (node_modules).
A folder entry `<path>/**` (an unsafe name below a safe folder) keeps the whole subtree
denied. Without `paths.worktree_dirs` the glob stays `<worktree>/**/<name>` (fail-closed).
`.claude/**` and procedure.yaml stay denied everywhere; role sessions keep every glob."""

EXCEPTION_FLAGS = ("allow_write", "allow_local_binding", "weaker_network_isolation")
"""The sandbox exceptions of runs and the developer (work role); their on/off state is part
of the run template and the work-role template (I9). Never a judge."""


def exception_flags_of(config):
    """The EXCEPTION_FLAGS a repository config turns on → {flag: True} (the `exceptions`
    argument of template() for a run or a work-role session)."""
    exc = (config or {}).get("sandbox_exceptions") or {}
    flags = {}
    if exc.get("allow_write"):
        flags["allow_write"] = True
    for f in ("allow_local_binding", "weaker_network_isolation"):
        if exc.get(f) is True:
            flags[f] = True
    return flags

DERIVED_PLACEHOLDERS = ("issue_tmp",)
"""Computed from the input, never given: issue_tmp = the parent of run_tmp (every attempt's
temp dir of this Issue — one rule covers them all, so a run and the developer share it)."""

CLAUDE_FIXED_FLAGS = (
    "--output-format", "stream-json", "--verbose",
    "--setting-sources", "",
    "--disable-slash-commands",
    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
    "--permission-mode", "default", "--permission-prompts", "none",
)
"""§6.2 / F1 / F2 flags every role session gets, in this order, right after `-p <prompt>`.
They keep the user's settings, plugins, MCP servers and slash commands out of the session. Since
FC decision D (2026-11-28) nothing verifies that from the session's `system/init`."""

FORBIDDEN_FLAGS = ("--max-turns", "--agent", "--agents", "--dangerously-skip-permissions",
                   "--allowedTools", "--add-dir")

TEMPLATE_FORMAT = 1
"""Bump when the template's meaning changes without its text changing (forces new canaries)."""

RECORD_FILES = (
    "state.json", "log.jsonl", "engine.log", "engine.rc", "lock",
    "brief.json", "result.json", "facts.json", "stream.jsonl", "stderr.log",
    "settings.json", "srt.json", "run.log",
    "repo.lock", "resume-note.txt",
)
"""Engine record file names (paths.py layout) denied by name to the permission layer.
`leader-decision.md` is NOT here: the engine copies it into each attempt's `in/` as a role
input, and a name deny would also block that copy (deny beats allow — P5 real run)."""

GATE_HOOK_REL = "skills/gld/gates/gate_precommit.py"
"""The 0.98.7 PreToolUse gate inside the experimental plugin install (S9)."""

GIT_COMMON_WRITE = ("objects", "refs/heads", "logs", "packed-refs", "packed-refs.lock")
GIT_COMMON_DENY = ("hooks", "config", "info", "objects/info/alternates", "objects/info/http-alternates")
GIT_OWN_DENY = ("commondir", "gitdir", "config.worktree")
NESTED_DENY = (".claude", ".git")
"""Denied (write) anywhere under a write-allowed root — see the module docstring."""

SANDBOX_OWN_TMP = ("/tmp/claude*", "/private/tmp/claude*")
"""Folders the sandbox itself keeps writable whatever allowWrite says: srt gives every
command TMPDIR=/tmp/claude and lets it create and write there (measured, srt 0.0.83);
Claude Code's sandbox does the same for /tmp/claude-<uid> (F4). NESTED_DENY applies there
too, so no repository / .claude can be prepared there for the gate either."""

ENV_SCRUB_EXTRA = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG*", "GIT_SSH*", "GIT_EXEC_PATH",
    "GIT_TEMPLATE_DIR", "GIT_PROXY_COMMAND", "GIT_EXTERNAL_DIFF",
    "*SECRET*", "*PASSWORD*", "*PASSWD*", "*API_KEY*", "*APIKEY*", "*CREDENTIAL*",
    "*_AUTH", "*_AUTH_*", "npm_config_*", "NPM_CONFIG_*", "DOCKER_*", "KUBECONFIG",
    "DYLD_*", "LD_PRELOAD", "LD_LIBRARY_PATH", "BASH_ENV", "ENV", "PROMPT_COMMAND",
)
"""Removed in addition to defaults.ENV_SCRUB_PATTERNS (U5): git redirection variables (the
engine pins its own, S4), other credential shapes, npm config (may point at a user
.npmrc), and shell / loader injection points. fnmatch, case-sensitive."""

ENV_RESERVED = ("PATH", "HOME", "TMPDIR", "BASH_MAX_TIMEOUT_MS", "CLAUDE_CONFIG_DIR")
DEFAULT_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
SRT_TMPDIR_MAX = 40
"""srt puts a unix socket in its TMPDIR (`srt-mux-<pid>-0.sock`); a long path cannot listen (F0)."""

SANDBOX_TMP_FORBIDDEN = (defaults.SANDBOX_TMP_FORBIDDEN_PREFIX, "/private" + defaults.SANDBOX_TMP_FORBIDDEN_PREFIX)

RESULT_SCHEMAS = ("result-work", "result-review")
CLI_SCHEMA_DROP = ("$schema", "$id")
"""Top-level keys never passed to `claude --json-schema` (P4: the CLI refuses the 2020-12 meta-schema)."""

_SAFE_PATH = re.compile(r"^(/[A-Za-z0-9._@+-]+)+$")
_SAFE_GLOB = re.compile(r"^(?!/)[A-Za-z0-9._@+*?/-]+$")
_HOST = re.compile(r"^(\*\.)?[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")   # never starts with '-' (a flag)
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RenderError(ValueError):
    """The input cannot be rendered into a safe boundary. The engine must not start the step."""


# --- input -------------------------------------------------------------------------

def _check_path(name, value, canonical=True):
    if not isinstance(value, str) or not _SAFE_PATH.match(value):
        raise RenderError(f"paths.{name}: not a safe absolute path: {value!r} "
                          "(allowed characters: A-Z a-z 0-9 . _ @ + - /)")
    if os.path.normpath(value) != value:
        raise RenderError(f"paths.{name}: not normalised: {value!r}")
    if canonical and os.path.realpath(value) != value:
        raise RenderError(f"paths.{name}: not canonical (a symlink in the path?): {value!r} → "
                          f"{os.path.realpath(value)!r} — rules must name the real path")
    return value


def _check_relglob(what, value):
    if not isinstance(value, str) or not _SAFE_GLOB.match(value):
        raise RenderError(f"{what}: not a safe relative glob: {value!r}")
    parts = value.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise RenderError(f"{what}: empty, '.' or '..' component: {value!r}")
    return value


def _at_or_under(p, d):
    return p == d or p.startswith(d.rstrip("/") + "/")


def _strip_glob_tail(g):
    return g[:-3] if g.endswith("/**") else g


class RenderInput:
    """Everything a render needs. All paths absolute.

    Attributes:
      kind              "role" | "run"
      role              role name (run: "developer" — a run gets the developer boundary, §7.1)
      role_class        codes.RoleClass value
      step, attempt, issue
      outputs           worktree-relative globs the step may write (judge roles, §7.6)
      paths             dict with the PLACEHOLDERS keys plus lists other_worktrees,
                        other_repo_roots
      config            the repository settings dict (schemas/repo-config) — secret_paths,
                        registry_hosts, cache_env, sandbox_exceptions, run timeouts
      model, effort, tools, max_budget_usd     session parameters (role only)
      json_schema       the result schema: "result-work" | "result-review" (a schema
                        file name) or a schema dict (role only)
      instruction       the work instruction text (-p, role only)
      system_prompt     CLAUDE.md + .claude/CLAUDE.md + role body, joined (role only)
      resume            session id for --resume or None (developer only, §6.2)
      command           the named command string (run only)
      bash_timeout_ms   BASH_MAX_TIMEOUT_MS = the run time limit (I13)

    The constructor validates everything and raises RenderError (fail-closed).
    """

    ROLE_FIELDS = ("model", "effort", "tools", "max_budget_usd", "json_schema", "instruction",
                   "system_prompt", "resume")
    RUN_FIELDS = ("command",)
    COMMON = ("kind", "role", "role_class", "step", "attempt", "issue", "outputs", "paths",
              "config", "bash_timeout_ms")

    def __init__(self, **fields):
        known = set(self.COMMON) | set(self.ROLE_FIELDS) | set(self.RUN_FIELDS)
        unknown = set(fields) - known
        if unknown:
            raise RenderError(f"unknown RenderInput fields: {sorted(unknown)}")
        self.kind = fields.get("kind")
        if self.kind not in ("role", "run"):
            raise RenderError(f"kind must be role or run, got {self.kind!r}")
        for k in known:
            setattr(self, k, fields.get(k))
        if self.outputs is None:
            self.outputs = []
        self._check_common()
        if self.kind == "role":
            self._check_role()
            extra = [k for k in self.RUN_FIELDS if fields.get(k) is not None]
        else:
            self._check_run()
            extra = [k for k in self.ROLE_FIELDS if fields.get(k) is not None]
        if extra:
            raise RenderError(f"fields not used by a {self.kind} render: {extra}")
        self.outputs = list(self.outputs or [])
        self.paths = dict(self.paths)
        self.config = dict(self.config)

    @classmethod
    def from_json(cls, obj):
        """Build from the `input` object of a tests/fixtures/render/*.json fixture."""
        if not isinstance(obj, dict):
            raise RenderError("render input must be an object")
        return cls(**json.loads(json.dumps(obj)))

    # validation ---------------------------------------------------------------------

    def _check_common(self):
        if not isinstance(self.role, str) or not _NAME.match(self.role):
            raise RenderError(f"role: bad name {self.role!r}")
        if self.role_class != codes.role_class(self.role):
            raise RenderError(f"role_class {self.role_class!r} does not match role {self.role!r} "
                              f"(I4: {codes.role_class(self.role)!r})")
        if self.kind == "run" and (self.role != "developer" or self.role_class != codes.RoleClass.WORK.value):
            raise RenderError("a run gets the developer boundary (§7.1): role must be developer")
        if not isinstance(self.step, str) or not _NAME.match(self.step):
            raise RenderError(f"step: bad id {self.step!r}")
        for name in ("attempt", "issue"):
            v = getattr(self, name)
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise RenderError(f"{name}: must be a positive integer, got {v!r}")
        if not isinstance(self.outputs, list):
            raise RenderError("outputs: must be a list")
        for o in self.outputs:
            _check_relglob("outputs", o)
        ms = self.bash_timeout_ms
        if self.kind == "role" or ms is not None:
            if not isinstance(ms, int) or isinstance(ms, bool) or ms <= 0:
                raise RenderError(f"bash_timeout_ms: must be a positive integer, got {ms!r}")
        self._check_config()
        self._check_paths()

    def _check_config(self):
        cfg = self.config
        if not isinstance(cfg, dict):
            raise RenderError("config: must be the repository settings object")
        errs = S.errors(cfg, S.load_schema("repo-config"))
        if errs:
            raise RenderError("config: not a valid repo-config: " + "; ".join(errs[:5]))
        for s in cfg.get("secret_paths", defaults.REPO_SECRET_DEFAULTS):
            _check_relglob("config.secret_paths", s)
        for h in cfg.get("registry_hosts", []):
            if not _HOST.match(h):
                raise RenderError(f"config.registry_hosts: bad host {h!r}")
        exc = cfg.get("sandbox_exceptions") or {}
        for flag in ("allow_local_binding", "weaker_network_isolation"):
            if flag in exc and not isinstance(exc[flag], bool):
                raise RenderError(f"config.sandbox_exceptions.{flag}: must be true or false")
        for w in exc.get("allow_write", []):
            if w != defaults.USER_TMP_TOKEN:
                _check_path("config.sandbox_exceptions.allow_write", w, canonical=False)
                low = [c.lower() for c in w.split("/")]
                if any(c.lower() in low for c in defaults.ALLOW_WRITE_FORBIDDEN_COMPONENTS):
                    raise RenderError(f"config.sandbox_exceptions.allow_write {w!r}: names a git, "
                                      "control-file or secret component")
        for h in exc.get("allow_hosts", []):
            if not _HOST.match(h):
                raise RenderError(f"config.sandbox_exceptions.allow_hosts: bad host {h!r}")
        cache_names = set(cfg.get("cache_env") or {})
        for k, v in (cfg.get("run_env") or {}).items():
            if not re.fullmatch(defaults.RUN_ENV_NAME, k) or k in ENV_RESERVED \
                    or k in defaults.RUN_ENV_RESERVED or k.startswith(defaults.RUN_ENV_RESERVED_PREFIXES) \
                    or any(w in k for w in defaults.RUN_ENV_SECRET_WORDS) or k in defaults.ENV_SESSION_SET \
                    or _scrubbed(k, ()) or k in cache_names:
                raise RenderError(f"config.run_env: {k!r} may not be set as a run variable")
            if not isinstance(v, str) or any(c in v for c in "{}") or any(ord(c) < 32 or ord(c) == 127 for c in v):
                raise RenderError(f"config.run_env.{k}: a literal value without braces or control characters")
        for k, v in (cfg.get("cache_env") or {}).items():
            if not _ENV_NAME.match(k) or k in ENV_RESERVED or k in defaults.ENV_SESSION_SET \
                    or any(fnmatch.fnmatchcase(k, pat) for pat in defaults.ENV_SCRUB_PATTERNS):
                raise RenderError(f"config.cache_env: {k!r} may not be set as a cache variable")
            if not (v == "{cache}" or v.startswith("{cache}/")):
                raise RenderError(f"config.cache_env.{k}: must point into the Guild cache "
                                  f"({{cache}}/…, §7.12 S8), got {v!r}")
            rest = v[len("{cache}"):].lstrip("/")
            if rest:
                _check_relglob(f"config.cache_env.{k}", rest)
                if any(c in rest for c in "*?"):
                    raise RenderError(f"config.cache_env.{k}: no glob in a cache path")

    def _check_paths(self):
        p = self.paths
        if not isinstance(p, dict):
            raise RenderError("paths: must be an object")
        need = ["home", "claude_config_dir", "worktree", "main_checkout", "git_common_dir",
                "own_worktree", "engine_records", "run_tmp", "cache", "plugin_root"]
        need += ["in_dir"] if self.kind == "role" else ["srt_tmpdir"]
        for k in need:
            if p.get(k) is None:
                raise RenderError(f"paths.{k}: required for a {self.kind} render")
            if k != "srt_tmpdir":   # srt's own TMPDIR: only an env value, never a rule (checked below)
                _check_path(k, p[k])
        if "in_dir" not in need and p.get("in_dir") is not None:
            _check_path("in_dir", p["in_dir"])
        if p.get("issue") != self.issue:
            raise RenderError(f"paths.issue {p.get('issue')!r} != issue {self.issue!r}")
        for k in ("other_worktrees", "other_repo_roots"):
            v = p.get(k, [])
            if not isinstance(v, list):
                raise RenderError(f"paths.{k}: must be a list")
            for x in v:
                _check_path(k, x)
        wd = p.get("worktree_dirs")
        if wd is not None:
            if self.kind != "run" or not isinstance(wd, list) or not wd:
                raise RenderError("paths.worktree_dirs: a non-empty list, run renders only")
            for x in wd:
                base = x[:-3] if isinstance(x, str) and x.endswith("/**") else x
                _check_path("worktree_dirs", base)
                if not _at_or_under(base, p["worktree"]):
                    raise RenderError(f"paths.worktree_dirs: {x!r} is not the worktree or under it")
        if self.kind == "run":
            t = p["srt_tmpdir"]
            if not isinstance(t, str) or not _SAFE_PATH.match(t) or not t.startswith(defaults.SRT_TMP_PREFIX) \
                    or len(t) > SRT_TMPDIR_MAX or os.path.normpath(t) != t:
                raise RenderError(f"paths.srt_tmpdir: must be a short {defaults.SRT_TMP_PREFIX}<id> path "
                                  f"(≤ {SRT_TMPDIR_MAX} chars, F0), got {t!r}")
        home, records = p["home"], p["engine_records"]
        for k in ("engine_records", "run_tmp", "in_dir", "cache"):
            v = p.get(k)
            if v and any(_at_or_under(v, f.rstrip("-")) or v.startswith(f) for f in SANDBOX_TMP_FORBIDDEN):
                raise RenderError(f"paths.{k}: under the Claude sandbox temp dir {v!r} (§7.3, F4)")
        if p.get("in_dir") is not None:
            d = p["in_dir"]
            if not _at_or_under(d, records) or d == records or os.path.basename(d) != "in":
                raise RenderError(f"paths.in_dir must be an attempt's in/ under engine_records: {d!r}")
        if not _at_or_under(p["own_worktree"], p["git_common_dir"] + "/worktrees") \
                or p["own_worktree"] == p["git_common_dir"] + "/worktrees":
            raise RenderError("paths.own_worktree must be <git_common_dir>/worktrees/<name>")
        if p["worktree"] == p["main_checkout"]:
            raise RenderError("paths.worktree is the main checkout — roles run in the Issue worktree (§7.3)")
        protected = [home, p["claude_config_dir"], records, home + "/.claude", home + "/.claude.json"]
        protected += [home + "/" + s for s in defaults.HOME_SECRETS]
        protected += [p["main_checkout"], p["plugin_root"]] + list(p.get("other_repo_roots", []))
        protected += list(p.get("other_worktrees", []))
        roots = {"worktree": p["worktree"], "run_tmp": p["run_tmp"], "cache": p["cache"],
                 "issue_tmp": os.path.dirname(p["run_tmp"]), "own_worktree": p["own_worktree"]}
        for i, r in enumerate(self.allow_write_roots()):
            roots[f"sandbox_exceptions.allow_write[{i}]"] = r
            protected_extra = [p["worktree"], p["git_common_dir"], p["engine_records"], p["cache"]]
            for q in protected_extra:
                if _at_or_under(q, r):
                    raise RenderError(f"allow_write root {r!r} contains {q!r} (it would widen a fixed rule)")
        for name, r in roots.items():
            if r == "/":
                raise RenderError(f"{name}: the file-system root cannot be write-allowed")
            for q in protected:
                if name == "own_worktree" and q == p["main_checkout"]:
                    continue  # the own git dir lives inside the main checkout's .git by design
                if _at_or_under(q, r):
                    raise RenderError(f"write root {name} {r!r} contains protected path {q!r}")
                if q != home and _at_or_under(r, q):
                    raise RenderError(f"write root {name} {r!r} lies inside protected path {q!r}")

    def _check_role(self):
        allowed_models = self.config.get("allowed_models") or defaults.ALLOWED_MODELS
        allowed_efforts = self.config.get("allowed_efforts") or defaults.ALLOWED_EFFORTS
        if self.model not in allowed_models:
            raise RenderError(f"model {self.model!r} is outside the allow-list {list(allowed_models)} (§7.8)")
        if self.effort not in allowed_efforts:
            raise RenderError(f"effort {self.effort!r} is outside the allow-list {list(allowed_efforts)} (§7.8)")
        tools = self.tools
        if not isinstance(tools, list) or not tools or len(set(tools)) != len(tools):
            raise RenderError(f"tools: a non-empty list without duplicates, got {tools!r}")
        allowed = defaults.TOOLS[self.role_class]
        bad = [t for t in tools if t not in allowed]
        if bad:
            raise RenderError(f"tools {bad} are outside the {self.role_class} set {list(allowed)} (I4)")
        b = self.max_budget_usd
        if not isinstance(b, (int, float)) or isinstance(b, bool) or not b > 0 or b != b or b == float("inf"):
            raise RenderError(f"max_budget_usd: every session needs a positive budget cap (§7.9), got {b!r}")
        js = self.json_schema
        if isinstance(js, str):
            if js not in RESULT_SCHEMAS:
                raise RenderError(f"json_schema: {js!r} is not one of {RESULT_SCHEMAS}")
        elif not isinstance(js, dict):
            raise RenderError("json_schema: a result schema name or a schema object")
        elif S.schema_tokens(js):           # an enum template that was not filled (stage 2 leader, stage 3 results)
            raise RenderError(f"json_schema: unfilled enum tokens {sorted(S.schema_tokens(js))}")
        for name in ("instruction", "system_prompt"):
            v = getattr(self, name)
            if not isinstance(v, str) or "\x00" in v:
                raise RenderError(f"{name}: must be a string without NUL")
        if not self.instruction.strip():
            raise RenderError("instruction: empty")
        if self.instruction.startswith("-"):
            raise RenderError("instruction: may not start with '-' (it would be read as a flag)")
        r = self.resume
        if r is not None:
            if not isinstance(r, str) or not _SESSION_ID.match(r):
                raise RenderError(f"resume: bad session id {r!r}")
            if self.role != "developer":
                raise RenderError("resume: only a returning developer resumes its session (§6.2)")

    def _check_run(self):
        c = self.command
        if not isinstance(c, str) or not c.strip() or "\x00" in c:
            raise RenderError("command: the named command string, non-empty, no NUL")

    # values ---------------------------------------------------------------------------

    def gets_toolchain(self):
        """True for a run and a work-role (developer) session: they get the repository's
        sandbox exceptions and run_env (P5 F2). A judge session never does."""
        return self.kind == "run" or self.role_class == codes.RoleClass.WORK.value

    def allow_write_roots(self):
        """sandbox_exceptions.allow_write resolved to absolute roots — a run and the developer
        ([] for a judge).

        `{user_tmp}` → paths.user_tmp (required then, canonical). A literal entry must be
        canonical too (rules must name the real path)."""
        if not self.gets_toolchain():
            return []
        exc = self.config.get("sandbox_exceptions") or {}
        out = []
        for w in exc.get("allow_write", []):
            if w == defaults.USER_TMP_TOKEN:
                ut = self.paths.get("user_tmp")
                if ut is None:
                    raise RenderError("sandbox_exceptions.allow_write uses {user_tmp} but paths.user_tmp "
                                      "is not given (getconf DARWIN_USER_TEMP_DIR) — refused")
                w = _check_path("user_tmp", ut)
            else:
                _check_path("sandbox_exceptions.allow_write", w)
            if w not in out:
                out.append(w)
        return out

    def exception_flags(self):
        """The sandbox exceptions that are on — the `exceptions` argument of template() ({} for a judge)."""
        if not self.gets_toolchain():
            return {}
        return exception_flags_of(self.config)

    def run_env(self):
        """repo-config run_env (literal values) — a run and the developer ({} for a judge)."""
        if not self.gets_toolchain():
            return {}
        return dict(self.config.get("run_env") or {})

    def scalars(self):
        out = {k: self.paths.get(k) for k in PLACEHOLDERS}
        out["issue"] = self.issue
        out["issue_tmp"] = os.path.dirname(self.paths["run_tmp"])
        return out

    def lists(self):
        exc = self.config.get("sandbox_exceptions") or {}
        return {
            "other_worktrees": list(self.paths.get("other_worktrees", [])),
            "other_repo_roots": list(self.paths.get("other_repo_roots", [])),
            "outputs": list(self.outputs),
            "secret_paths": list(self.config.get("secret_paths", defaults.REPO_SECRET_DEFAULTS)),
            "registry_hosts": list(self.config.get("registry_hosts", [])),
            "allow_hosts": list(exc.get("allow_hosts", [])),
            "allow_write": self.allow_write_roots(),
            "worktree_dirs": (list(self.paths["worktree_dirs"]) if self.paths.get("worktree_dirs")
                              else [self.paths["worktree"] + "/**"]),
        }

    def json_schema_text(self):
        """The `--json-schema` value: the schema without its top-level `$schema` / `$id`.

        P4 (real canary, CLI 2.1.323): the CLI refuses a schema that names the draft 2020-12
        meta-schema — `--json-schema is not a valid JSON Schema: no schema with key or ref
        "https://json-schema.org/draft/2020-12/schema"` — and exits before system/init. The
        result schemas use only keywords every draft shares (type / properties / required /
        additionalProperties / items / enum), so the body is unchanged; the engine still
        re-checks result.json with the full schema (gxengine/schema.py)."""
        js = self.json_schema
        obj = S.load_schema(js) if isinstance(js, str) else js
        if isinstance(obj, dict):
            obj = {k: v for k, v in obj.items() if k not in CLI_SCHEMA_DROP}
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


# --- template ------------------------------------------------------------------------

def _read_deny_paths():
    """Sandbox-form read-deny paths except the engine records (see _deny)."""
    out = ["{home}/" + s for s in defaults.HOME_SECRETS]
    out += ["{claude_config_dir}", "{home}/.claude", "{home}/.claude.json"]
    for root in ("{main_checkout}", "{worktree}", "{other_worktrees}"):
        out.append(root + "/**/{secret_paths}")
    out.append("{other_repo_roots}")
    return out


def _write_deny_paths():
    out = []
    for root in ("{worktree}", "{main_checkout}"):
        for g in defaults.CONTROL_FILE_GLOBS:
            out.append(root + "/" + _strip_glob_tail(g))
    out += ["{git_common_dir}/" + x for x in GIT_COMMON_DENY]
    out += ["{own_worktree}/" + x for x in GIT_OWN_DENY]
    out.append("{worktree}/.git")
    write_roots = ["{worktree}", "{issue_tmp}", "{cache}", "{own_worktree}"]
    write_roots += ["{git_common_dir}/" + x for x in GIT_COMMON_WRITE if not x.startswith("packed-refs")]
    write_roots += list(SANDBOX_OWN_TMP)
    for root in write_roots:
        for name in NESTED_DENY:
            out.append(root + "/**/" + name)
    out.append("{engine_records}")
    out += _read_deny_paths()
    return out


def _perm(tool, path):
    return [f"{tool}(/{path})", f"{tool}(/{path}/**)"]


def _settings_template(role_class, exceptions=None):
    work = role_class == codes.RoleClass.WORK.value
    exc = _normalise_exceptions(exceptions)
    if exc and not work:
        raise RenderError("sandbox exceptions are never rendered into a judge session")
    read_deny = _read_deny_paths()
    write_deny = _write_deny_paths()
    if exc.get("allow_write"):
        # gate escape guard (module docstring): no repository / .claude in an extra root either
        write_deny += ["{allow_write}/**/" + n for n in NESTED_DENY]
    deny = []
    for p in read_deny + ["{engine_records}/**/" + f for f in RECORD_FILES]:
        for t in ("Read", "Grep", "Glob"):
            deny += _perm(t, p)
    for p in write_deny:
        for t in ("Edit", "Write"):
            deny += _perm(t, p)
    deny += list(defaults.AUX_BASH_DENY) + ["WebFetch", "WebSearch"]
    if work:
        allow = ["Bash", "Read(/{in_dir}/**)", "Edit(/{worktree}/**)", "Edit(/{run_tmp}/**)",
                 "Edit(/{cache}/**)"]
        allow_write = ["{worktree}", "{run_tmp}", "{cache}"]
        allow_write += ["{git_common_dir}/" + x for x in GIT_COMMON_WRITE] + ["{own_worktree}"]
        if exc.get("allow_write"):
            allow_write.append("{allow_write}")   # Bash only: no Edit(...) allow for an extra root
        domains = ["{registry_hosts}", "{allow_hosts}"]
    else:
        allow = ["Read(/{in_dir}/**)", "Edit(/{worktree}/{outputs})"]
        allow_write = ["{worktree}/{outputs}", "{run_tmp}"]
        domains = []
    sandbox = dict(defaults.SANDBOX_FIXED)
    sandbox["excludedCommands"] = list(defaults.SANDBOX_FIXED["excludedCommands"])
    sandbox["filesystem"] = {
        "denyRead": read_deny + ["{engine_records}"],
        "allowRead": ["{in_dir}"],
        "allowWrite": allow_write,
        "denyWrite": write_deny,
    }
    sandbox["network"] = {"allowedDomains": domains}
    if exc.get("allow_local_binding"):
        sandbox["network"]["allowLocalBinding"] = True
    if exc.get("weaker_network_isolation"):
        sandbox["enableWeakerNetworkIsolation"] = True
    hooks = {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python3 -I {plugin_root}/" + GATE_HOOK_REL + " --no-records"}]}]}
    return {"permissions": {"allow": allow, "deny": deny}, "sandbox": sandbox, "hooks": hooks}


def _normalise_exceptions(exceptions):
    exceptions = exceptions or {}
    if not isinstance(exceptions, dict) or set(exceptions) - set(EXCEPTION_FLAGS) \
            or not all(v is True or v is False for v in exceptions.values()):
        raise RenderError(f"exceptions: a dict of {EXCEPTION_FLAGS} → bool, got {exceptions!r}")
    return {k: True for k, v in exceptions.items() if v}


def _srt_template(exceptions=None):
    exc = _normalise_exceptions(exceptions)
    fs = _settings_template(codes.RoleClass.WORK.value)["sandbox"]["filesystem"]
    named = {"{worktree}/" + g: "{worktree_dirs}/" + g[3:] for g in RUN_NAMED_CONTROL}
    out = {
        "network": {"allowedDomains": ["{registry_hosts}", "{allow_hosts}"], "deniedDomains": []},
        "filesystem": {
            "denyRead": list(fs["denyRead"]),
            "allowRead": ["{plugin_root}"],
            "allowWrite": list(fs["allowWrite"]),
            "denyWrite": [named.get(x, x) for x in fs["denyWrite"]],
        },
    }
    if len([x for x in out["filesystem"]["denyWrite"] if x.startswith("{worktree_dirs}/")]) != len(named):
        raise RenderError("internal: the run control-file denies were not all rendered per folder")
    if exc.get("allow_write"):
        out["filesystem"]["allowWrite"].append("{allow_write}")
        # gate escape guard (module docstring): no repository / .claude in an extra root either
        out["filesystem"]["denyWrite"] += ["{allow_write}/**/" + n for n in NESTED_DENY]
    if exc.get("allow_local_binding"):
        out["network"]["allowLocalBinding"] = True
    if exc.get("weaker_network_isolation"):
        out["enableWeakerNetworkIsolation"] = True
    return out


def _env_template(kind, exceptions=None, role_class=codes.RoleClass.WORK.value):
    env = {"scrub": list(defaults.ENV_SCRUB_PATTERNS) + list(ENV_SCRUB_EXTRA),
           "path_drop_under": ["{worktree}", "{issue_tmp}", "{cache}", "{git_common_dir}",
                               "{engine_records}"],
           "cache_env": "{cache}"}
    if _normalise_exceptions(exceptions).get("allow_write"):
        env["path_drop_under"].append("{allow_write}")
    if kind == "role":
        env["keep"] = list(defaults.ENV_KEEP_EVEN_IF_MATCHED)
        env["set"] = dict(defaults.ENV_SESSION_SET)
        env["set"]["BASH_MAX_TIMEOUT_MS"] = "<bash_timeout_ms>"
        env["set"]["TMPDIR"] = "{run_tmp}"
        if role_class == codes.RoleClass.WORK.value:
            env["run_env"] = "after the scrub"   # P5 F2: the developer gets the run's toolchain env
    else:
        env["keep"] = []
        env["drop"] = ["CLAUDE_CONFIG_DIR"]
        env["set"] = {"TMPDIR": "{srt_tmpdir}"}
        env["run_env"] = "after the scrub"
    return env


COMMAND_PREFIX = "export TMPDIR={run_tmp}; cd {worktree} && "
"""How a run's `-c` string starts (values shell-quoted at render time)."""


def template(role_class, kind="role", exceptions=None):
    """The placeholder settings + srt template for a role class (I9). Pure, deterministic.

    Role: {"format", "kind", "role_class", "tools", "claude_flags", "forbidden_flags", "env",
    "settings"}; run: {"format", "kind", "role_class", "env", "srt", "command_prefix"}.
    Everything that shapes the boundary is in it, so a change to any rule, flag or env rule
    changes `template_hash` and forces a new canary (I9). `exceptions` (a run or a work-role
    session) = the sandbox exceptions that are on (RenderInput.exception_flags()); none → the
    default template. A judge with exceptions is refused.
    """
    if role_class not in (codes.RoleClass.WORK.value, codes.RoleClass.JUDGE.value):
        raise RenderError(f"unknown role class {role_class!r}")
    exc = _normalise_exceptions(exceptions)
    if kind == "role":
        if exc and role_class != codes.RoleClass.WORK.value:
            raise RenderError("sandbox exceptions other than allow_hosts are never rendered for a judge role")
        out = {
            "format": TEMPLATE_FORMAT, "kind": "role", "role_class": role_class,
            "tools": list(defaults.TOOLS[role_class]),
            "claude_flags": list(CLAUDE_FIXED_FLAGS), "forbidden_flags": list(FORBIDDEN_FLAGS),
            "env": _env_template("role", exceptions, role_class),
            "settings": _settings_template(role_class, exceptions),
        }
        if exc:
            out["exceptions"] = sorted(exc)
        return out
    if kind == "run":
        if role_class != codes.RoleClass.WORK.value:
            raise RenderError("a run gets the developer (work) boundary (§7.1)")
        out = {
            "format": TEMPLATE_FORMAT, "kind": "run", "role_class": role_class,
            "env": _env_template("run", exceptions),
            "srt": _srt_template(exceptions),
            "command_prefix": COMMAND_PREFIX,
        }
        if _normalise_exceptions(exceptions):
            out["exceptions"] = sorted(_normalise_exceptions(exceptions))
        return out
    raise RenderError(f"kind must be role or run, got {kind!r}")


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(obj):
    """sha256 hex of canonical JSON — template hashes and brief.session.settings_sha256."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def template_hash(role_class, kind="role", exceptions=None):
    """sha256 hex of the canonical JSON of `template(...)` — the I9 canary-key part."""
    return sha256_json(template(role_class, kind, exceptions))


def input_template_hash(inp):
    """The template hash of what `inp` renders (run / developer: with its exception flags) — the canary key part."""
    return template_hash(inp.role_class, inp.kind, inp.exception_flags())


def substitute(tmpl, paths, lists):
    """Replace placeholders in a template; list placeholders expand to one rule per value.

    `paths` maps scalar placeholders (PLACEHOLDERS + DERIVED_PLACEHOLDERS) to values;
    `lists` maps LIST_PLACEHOLDERS to lists. A string inside a list with list placeholders
    becomes the cross product (first placeholder outermost); an empty list removes it. A
    list placeholder outside a list, an unknown placeholder or a None value → RenderError.
    Values are inserted once (never re-scanned). Lists are de-duplicated, order kept.
    """
    def one(s, in_list):
        names = _PLACEHOLDER.findall(s)
        for n in names:
            if n in LIST_PLACEHOLDERS:
                if not in_list:
                    raise RenderError(f"list placeholder {{{n}}} outside a list: {s!r}")
                if n not in lists:
                    raise RenderError(f"no value for list placeholder {{{n}}}")
            elif n in PLACEHOLDERS or n in DERIVED_PLACEHOLDERS:
                if paths.get(n) is None:
                    raise RenderError(f"placeholder {{{n}}} has no value (used in {s!r})")
            else:
                raise RenderError(f"unknown placeholder {{{n}}} in {s!r}")
        list_names = []
        for n in names:
            if n in LIST_PLACEHOLDERS and n not in list_names:
                list_names.append(n)
        combos = itertools.product(*[lists[n] for n in list_names]) if list_names else [()]
        out = []
        for combo in combos:
            vals = dict(zip(list_names, combo))

            def rep(m):
                n = m.group(1)
                v = vals[n] if n in vals else paths[n]
                return str(v)
            out.append(_PLACEHOLDER.sub(rep, s))
        return out

    def walk(node, in_list=False):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            res = []
            for x in node:
                if isinstance(x, str):
                    for y in one(x, True):
                        if y not in res:
                            res.append(y)
                else:
                    res.append(walk(x))
            return res
        if isinstance(node, str):
            got = one(node, False)
            return got[0]
        return node

    return walk(tmpl)


# --- output checks (srt ignores unknown keys — verified with 0.0.83 — so a typo would
# silently drop a rule; the engine checks its own output instead) -------------------

def _check_path_list(where, v, allow_glob=True):
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise RenderError(f"{where}: must be a list of strings")
    for x in v:
        if not x.startswith("/") or "{" in x or "}" in x or "\x00" in x or ".." in x.split("/"):
            raise RenderError(f"{where}: not an absolute rendered path: {x!r}")
        if not allow_glob and any(c in x for c in "*?["):
            raise RenderError(f"{where}: no glob allowed here: {x!r}")


def check_srt_settings(obj):
    """Raise RenderError unless `obj` has exactly the srt keys (F0 — all required ones) with
    absolute, fully substituted paths. The only optional keys are the approved exceptions
    `network.allowLocalBinding` and top-level `enableWeakerNetworkIsolation`, each exactly true."""
    if not isinstance(obj, dict) or set(obj) - {"enableWeakerNetworkIsolation"} != {"network", "filesystem"}:
        raise RenderError("srt settings: keys must be exactly network, filesystem "
                          "(+ enableWeakerNetworkIsolation when approved)")
    if "enableWeakerNetworkIsolation" in obj and obj["enableWeakerNetworkIsolation"] is not True:
        raise RenderError("srt settings: enableWeakerNetworkIsolation is only rendered as true")
    net, fs = obj["network"], obj["filesystem"]
    if not isinstance(net, dict) or set(net) - {"allowLocalBinding"} != {"allowedDomains", "deniedDomains"}:
        raise RenderError("srt settings: network keys must be exactly allowedDomains, deniedDomains "
                          "(+ allowLocalBinding when approved)")
    if "allowLocalBinding" in net and net["allowLocalBinding"] is not True:
        raise RenderError("srt settings: network.allowLocalBinding is only rendered as true")
    for k in ("allowedDomains", "deniedDomains"):
        if not isinstance(net[k], list) or not all(isinstance(h, str) and _HOST.match(h) for h in net[k]):
            raise RenderError(f"srt settings: network.{k} must be a list of host names")
    _check_fs("srt settings", fs)
    return obj


def _check_fs(where, fs):
    if not isinstance(fs, dict) or set(fs) != {"denyRead", "allowRead", "allowWrite", "denyWrite"}:
        raise RenderError(f"{where}: filesystem keys must be exactly denyRead, allowRead, allowWrite, denyWrite")
    for k in ("denyRead", "allowRead", "allowWrite", "denyWrite"):
        _check_path_list(f"{where}: filesystem.{k}", fs[k], allow_glob=(k != "allowRead"))
    if not fs["denyWrite"] or not fs["denyRead"]:
        raise RenderError(f"{where}: empty deny lists")


def check_role_settings(obj):
    """Raise RenderError unless `obj` is a complete role `--settings` (S1, S9 shape). The only
    optional keys are the approved exceptions `sandbox.network.allowLocalBinding` and
    `sandbox.enableWeakerNetworkIsolation` (Claude Code settings names), each exactly true,
    and only in a session with Bash (the developer — never a judge)."""
    if not isinstance(obj, dict) or set(obj) != {"permissions", "sandbox", "hooks"}:
        raise RenderError("settings: keys must be exactly permissions, sandbox, hooks")
    perms = obj["permissions"]
    if not isinstance(perms, dict) or set(perms) != {"allow", "deny"}:
        raise RenderError("settings: permissions keys must be exactly allow, deny")
    for k in ("allow", "deny"):
        if not isinstance(perms[k], list) or not all(isinstance(r, str) and "{" not in r for r in perms[k]):
            raise RenderError(f"settings: permissions.{k} must be rendered rule strings")
    if [r for r in perms["allow"] if r.startswith("Write(")]:
        raise RenderError("settings: write allows are Edit(...) rules (F1)")
    for r in defaults.AUX_BASH_DENY + ("WebFetch", "WebSearch"):
        if r not in perms["deny"]:
            raise RenderError(f"settings: deny is missing {r}")
    sb = obj["sandbox"]
    want = set(defaults.SANDBOX_FIXED) | {"filesystem", "network"}
    if not isinstance(sb, dict) or set(sb) - {"enableWeakerNetworkIsolation"} != want:
        raise RenderError(f"settings: sandbox keys must be exactly {sorted(want)} "
                          "(+ enableWeakerNetworkIsolation when approved)")
    for k, v in defaults.SANDBOX_FIXED.items():
        if sb[k] != v:
            raise RenderError(f"settings: sandbox.{k} must be {v!r}")
    if "enableWeakerNetworkIsolation" in sb and sb["enableWeakerNetworkIsolation"] is not True:
        raise RenderError("settings: sandbox.enableWeakerNetworkIsolation is only rendered as true")
    _check_fs("settings: sandbox", sb["filesystem"])
    net = sb["network"]
    if not isinstance(net, dict) or set(net) - {"allowLocalBinding"} != {"allowedDomains"} \
            or not isinstance(net["allowedDomains"], list):
        raise RenderError("settings: sandbox.network must be exactly {allowedDomains: [...]} "
                          "(+ allowLocalBinding when approved)")
    if "allowLocalBinding" in net and net["allowLocalBinding"] is not True:
        raise RenderError("settings: sandbox.network.allowLocalBinding is only rendered as true")
    if ("allowLocalBinding" in net or "enableWeakerNetworkIsolation" in sb) and "Bash" not in perms["allow"]:
        raise RenderError("settings: sandbox exceptions only in a session with Bash (never a judge)")
    hooks = obj["hooks"]
    try:
        pre = hooks["PreToolUse"]
        ok = set(hooks) == {"PreToolUse"} and len(pre) == 1 and pre[0]["matcher"] == "Bash" \
            and pre[0]["hooks"][0]["type"] == "command" and GATE_HOOK_REL in pre[0]["hooks"][0]["command"]
    except (KeyError, IndexError, TypeError):
        ok = False
    if not ok:
        raise RenderError("settings: hooks must be exactly the PreToolUse Bash gate (S9)")
    return obj


# --- renders -------------------------------------------------------------------------

def _filled(inp, kind):
    return substitute(template(inp.role_class, kind, inp.exception_flags()), inp.scalars(), inp.lists())


def render_settings(inp):
    """The `--settings` dict of a role session (fixture key "settings")."""
    if inp.kind != "role":
        raise RenderError("render_settings is for role sessions")
    return check_role_settings(_filled(inp, "role")["settings"])


def render_srt(inp):
    """The srt settings dict of a run (fixture key "srt"). Every required key present (F0)."""
    if inp.kind != "run":
        raise RenderError("render_srt is for run steps")
    return check_srt_settings(_filled(inp, "run")["srt"])


def role_sandbox_as_srt(settings):
    """The srt settings equivalent of a role's `sandbox` block (Claude Code's sandbox is
    sandbox-runtime): used by the free tests and the srt canary to exercise the role rules.
    The approved exceptions map 1:1 (`sandbox.network.allowLocalBinding` → srt
    `network.allowLocalBinding`, `sandbox.enableWeakerNetworkIsolation` → srt top level)."""
    sb = settings["sandbox"]
    out = {
        "network": {"allowedDomains": list(sb["network"]["allowedDomains"]), "deniedDomains": []},
        "filesystem": {k: list(v) for k, v in sb["filesystem"].items()},
    }
    if "allowLocalBinding" in sb["network"]:
        out["network"]["allowLocalBinding"] = sb["network"]["allowLocalBinding"]
    if "enableWeakerNetworkIsolation" in sb:
        out["enableWeakerNetworkIsolation"] = sb["enableWeakerNetworkIsolation"]
    return check_srt_settings(out)


def _check_bin(name, path):
    if not isinstance(path, str) or not os.path.isabs(path) or "\x00" in path:
        raise RenderError(f"{name}: must be an absolute path, got {path!r}")


def render_claude_argv(inp, claude_bin, settings_path):
    """The claude argument list (fixture key "argv"): `[claude_bin, "-p", instruction,
    *CLAUDE_FIXED_FLAGS, "--settings", settings_path, "--tools", ",".join(tools),
    "--model", m, "--effort", e, "--max-budget-usd", b, "--json-schema", <compact JSON>,
    "--append-system-prompt", system_prompt, ("--resume", id)?]`."""
    if inp.kind != "role":
        raise RenderError("render_claude_argv is for role sessions")
    _check_bin("claude_bin", claude_bin)
    _check_bin("settings_path", settings_path)
    argv = [claude_bin, "-p", inp.instruction, *CLAUDE_FIXED_FLAGS,
            "--settings", settings_path,
            "--tools", ",".join(inp.tools),
            "--model", inp.model,
            "--effort", inp.effort,
            "--max-budget-usd", str(float(inp.max_budget_usd)),
            "--json-schema", inp.json_schema_text(),
            "--append-system-prompt", inp.system_prompt]
    if inp.resume is not None:
        argv += ["--resume", inp.resume]
    bad = [a for a in argv if a in FORBIDDEN_FLAGS]
    if bad:
        raise RenderError(f"forbidden flags in argv: {bad}")
    return argv


def render_srt_argv(inp, srt_bin, srt_settings_path):
    """The srt argument list of a run (fixture key "argv"): `[srt_bin, "--settings", path,
    "-c", "export TMPDIR=<run_tmp>; cd <worktree> && <command>"]` — the command's TMPDIR is
    set inside (F0) and srt itself is started in an empty folder by the runner (its built-in
    denies cover its cwd subtree), so the command changes into the worktree first."""
    if inp.kind != "run":
        raise RenderError("render_srt_argv is for run steps")
    _check_bin("srt_bin", srt_bin)
    _check_bin("srt_settings_path", srt_settings_path)
    return [srt_bin, "--settings", srt_settings_path, "-c",
            f"export TMPDIR={shlex.quote(inp.paths['run_tmp'])}; "
            f"cd {shlex.quote(inp.paths['worktree'])} && {inp.command}"]


def _scrubbed(name, keep):
    if name in keep:
        return False
    pats = tuple(defaults.ENV_SCRUB_PATTERNS) + ENV_SCRUB_EXTRA
    return any(fnmatch.fnmatchcase(name, p) for p in pats)


def is_scrubbed(name, keep=()):
    """True when an env name is removed before a role session / run (defaults.ENV_SCRUB_PATTERNS
    + ENV_SCRUB_EXTRA) — also used for the toolchain-prepare env (runner)."""
    return _scrubbed(name, tuple(keep))


def clean_path(value, drop_under):
    """PATH without empty / relative entries and entries under `drop_under` (DEFAULT_PATH when empty)."""
    return _clean_path(value, list(drop_under))


def _clean_path(value, drop_under):
    out = []
    for entry in (value or "").split(":"):
        if not entry or not os.path.isabs(entry) or os.path.normpath(entry) != entry.rstrip("/") and entry != "/":
            continue
        e = os.path.normpath(entry)
        if any(_at_or_under(e, d) for d in drop_under):
            continue
        if e not in out:
            out.append(e)
    return ":".join(out) if out else DEFAULT_PATH


def render_env(inp, base_env):
    """The child environment (fixture key "env"): `base_env` minus defaults.ENV_SCRUB_PATTERNS,
    plus cache env with {cache} filled. Role: + ENV_SESSION_SET, BASH_MAX_TIMEOUT_MS,
    TMPDIR=run_tmp, CLAUDE_CONFIG_DIR kept (the CLI's own login; SCRUB hides it from Bash,
    F1). Run (the srt process): CLAUDE_CONFIG_DIR dropped too, TMPDIR = the short
    /tmp/gx-<id> (`inp.paths["srt_tmpdir"]`); the command's TMPDIR is set inside -c;
    repo-config `run_env` is added after the scrub (P3-0) — for a run and, since P5 F2, the
    developer (never a judge). PATH never gains a toolchain folder: the cache stays out of it.

    U5 additions (fail-closed): ENV_SCRUB_EXTRA is removed too; PATH loses empty, relative
    and role-writable entries (the gate hook and git run OUTSIDE the sandbox with this
    PATH); HOME and CLAUDE_CONFIG_DIR must match the rendered paths, or the deny list would
    protect the wrong folders.
    """
    if not isinstance(base_env, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                 for k, v in base_env.items()):
        raise RenderError("base_env: must map names to strings")
    p = inp.paths
    if "HOME" in base_env and os.path.normpath(base_env["HOME"]) != p["home"]:
        raise RenderError(f"base_env HOME {base_env['HOME']!r} != paths.home {p['home']!r}")
    cfg_dir = base_env.get("CLAUDE_CONFIG_DIR")
    if inp.kind == "role":
        want = os.path.normpath(cfg_dir) if cfg_dir else p["home"] + "/.claude"
        if want != p["claude_config_dir"]:
            raise RenderError(f"the CLI's config dir {want!r} != paths.claude_config_dir "
                              f"{p['claude_config_dir']!r} — the deny list would miss it")
    keep = tuple(defaults.ENV_KEEP_EVEN_IF_MATCHED) if inp.kind == "role" else ()
    env = {}
    for k, v in base_env.items():
        if _scrubbed(k, keep) or k in defaults.ENV_SESSION_SET:
            continue
        if inp.kind == "run" and k == "CLAUDE_CONFIG_DIR":
            continue
        env[k] = v
    sc = inp.scalars()
    drop_under = [sc["worktree"], sc["issue_tmp"], sc["cache"], sc["git_common_dir"], sc["engine_records"]]
    drop_under += inp.allow_write_roots()
    env["PATH"] = _clean_path(base_env.get("PATH"), drop_under)
    for k, v in (inp.config.get("cache_env") or {}).items():
        env[k] = p["cache"] + v[len("{cache}"):]
    env.update(inp.run_env())   # run only; names checked against the scrub / reserved lists
    if inp.kind == "role":
        env.update(defaults.ENV_SESSION_SET)
        env["BASH_MAX_TIMEOUT_MS"] = str(inp.bash_timeout_ms)
        env["TMPDIR"] = p["run_tmp"]
    else:
        env["TMPDIR"] = p["srt_tmpdir"]
    return env


def render(inp, base_env, bins, files):
    """All four at once → dict {settings|srt, argv, env} — the shape of a fixture's `expected`.

    `bins` = {"claude": path, "srt": path}; `files` = {"settings": path, "srt": path}.
    """
    if inp.kind == "role":
        return {"settings": render_settings(inp),
                "argv": render_claude_argv(inp, bins["claude"], files["settings"]),
                "env": render_env(inp, base_env)}
    return {"srt": render_srt(inp),
            "argv": render_srt_argv(inp, bins["srt"], files["srt"]),
            "env": render_env(inp, base_env)}
