"""workflows.dev.ports — the LIVE ports a stage runs on (the K1 platform underneath).

Inert until K5 wires `gld_engine.py dev run`: nothing in the plugin calls this module. Contracts
kept from K1:
* roles: RoleCall → RoleSpec (prompt = `roles/prompts/<role>-<task>.md`, persona from the repo's
  `.claude/agents/<role>.md`, the §5.2 result schema) → `Runner.run_role`;
* suites and the TEST `effective` re-runs execute role-written code, so they run under the OWNING
  role's sandbox block (`settings.role_sandbox`, K1r3-B1) with the role's scrubbed env; the engine
  re-baselines the drift snapshot after its own steps (`Runner.rebaseline`, K1r2-B3);
* the qa push: only when the local branch is ahead of the remote head, after `drift_check`, to the
  fixed URL resolved before any role ran (`adapters.git.push`, hooks off).
"""

import json
import os
import re
import shlex
import subprocess

from guildcore import capture as CAP
from guildcore import fsafe as FS
from guildcore import checks as CH
from guildcore.adapters import claude as C
from guildcore.adapters import git as G
from guildcore.roles import runner as RR
from guildcore.roles import settings as S
from guildcore.roles.result import RESULT_SCHEMAS
from guildcore.checks import visual as V
from workflows.dev import effective as EFF
from workflows.dev import preflight as PF
from workflows.dev.stages.base import Ports

WARMUP_DART = ("import 'package:flutter_test/flutter_test.dart';\n\n"
               "void main() {\n  test('guild engine warm-up', () {});\n}\n")
PROMPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roles", "prompts")


def prompt(call, issue):
    path = os.path.join(PROMPTS, "%s-%s.md" % (call.role, call.task))
    if not os.path.exists(path) and call.task == "review":           # K3: 3.5b specialists share one
        path = os.path.join(PROMPTS, "specialist-review.md")
    with open(path, encoding="utf-8") as fh:
        text = fh.read().replace("{issue}", str(issue))
    if call.addendum:
        text = text.rstrip("\n") + "\n\n" + call.addendum + "\n"
    return text


def repo_roots(root):
    """Every checkout of the repository — the main one and each linked worktree (`git worktree
    list`) — plus the shared git dir (`--git-common-dir`), realpaths (K2r4-M2)."""
    out = []
    lst = G.run(root, "worktree", "list", "--porcelain", check=False).decode("utf-8", "replace")
    for ln in lst.split("\n"):
        if ln.startswith("worktree "):
            out.append(os.path.realpath(ln[len("worktree "):]))
    common = G.run(root, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False).decode().strip()
    if common:
        out.append(os.path.realpath(common))
    out.append(os.path.realpath(root))
    return list(dict.fromkeys(out))


def tree_sandbox(tree, run_dir, repo_root, issue=None, extra_roots=()):
    """K2r4-M2: the ONE sandbox of code the engine runs in a temp tree — the suite, the effective
    re-runs and the networked warm-up. Reader-grade (tester-verify + toolchain caches) with write
    access to the temp tree; reads AND writes of every checkout of the repository and of the
    shared git dir are denied (no secret original, no other worktree, no refs/objects). The only
    read exceptions are the dependency dirs the tree symlinks (`node_modules` …)."""
    sb = S.role_sandbox("tester-verify", None, run_dir, issue, toolchain=True, tool_writes=S.toolchain_writes(tree))
    fs = dict(sb["filesystem"])
    roots = repo_roots(repo_root) + [os.path.realpath(x) for x in extra_roots]
    tr = os.path.realpath(tree)
    if any((tr + "/").startswith(r + "/") for r in roots):
        raise ValueError("temp tree inside a checkout of the repository: %s" % tr)
    fs["denyRead"] = list(fs.get("denyRead") or []) + [r + "/**" for r in roots]
    fs["denyWrite"] = list(fs.get("denyWrite") or []) + [r + "/**" for r in roots]
    fs["allowWrite"] = [a for a in fs.get("allowWrite") or []
                        if not any(os.path.realpath(a.rstrip("*").rstrip("/")) == r or
                                   os.path.realpath(a.rstrip("*").rstrip("/")).startswith(r + "/") for r in roots)]
    fs["allowWrite"].append(tr + "/**")
    fs["allowRead"] = [d + "/**" for d in EFF.linked_dirs(tree)]
    return dict(sb, filesystem=fs)


warm_sandbox = tree_sandbox                 # r3 name


MISSING_ASSET_RE = re.compile(r"No file or variants found for asset: ([^\s]+?)\.?$", re.M)
WARMUP_DIR = "guild_engine_warmup"           # outside test/: no test/flutter_test_config.dart wraps it


def warm_in_place(root, tree, run_dir, env, issue=None, proxy_hosts=None, extra_roots=(), inspect=None):
    """K2r4-M1: the networked warm-up NEVER runs the developer's tree. `tree` holds a PRISTINE
    checkout of `<base>` (reviewed code, no ignored file, no `.git`): `pub get` + an ENGINE-written
    empty test (in a new dir outside `test/`) under the deps proxy, in `tree_sandbox`. The caller
    has classified the build inputs (`effective.build_inputs`): `none` → this is <base> and the
    caller then moves it to HEAD (`TempTree.advance`); `hosted-deps` → this is the HEAD copy (only
    hosted third-party package hooks run; no test config exists at its root). The warm-up dir and any
    placeholder are removed. With `inspect` (the HEAD copy, K2r7-M1) the warm-up is split: `pub get`
    ALONE (resolves, runs no hook and no test) → `inspect(tree)` on the resolved graph → a reason
    stops here (`r.halt`, nothing else runs) → only then the empty test. Returns (CheckResult|None,
    proxy summary); the result also carries `proxy` (K2r7-m1)."""
    import shutil
    if not os.path.exists(os.path.join(tree, "pubspec.yaml")):
        return None, {}
    if os.path.exists(os.path.join(tree, "flutter_test_config.dart")):
        return None, {"skipped": "root flutter_test_config.dart"}
    wdir = os.path.join(tree, WARMUP_DIR)
    os.makedirs(wdir)
    rel = os.path.join(WARMUP_DIR, "warmup_test.dart")
    with open(os.path.join(tree, rel), "w", encoding="utf-8") as fh:
        fh.write(WARMUP_DART)
    placeholders = []
    try:
        sb = tree_sandbox(tree, run_dir, root, issue, extra_roots)
        tmp = os.path.join(run_dir, "tmp")
        if inspect is None:
            r, px = CH.deps_step(["flutter pub get", "flutter test --no-pub %s" % rel], tree, sb, tmp,
                                 env=env, hosts=proxy_hosts)
        else:
            r, px = CH.deps_step(["flutter pub get"], tree, sb, tmp, env=env, hosts=proxy_hosts)
            r.proxy = px
            if not r.passed:
                return r, px
            why = inspect(tree)
            if why:
                r = CH.CheckResult(False, None, False, "resolved graph: %s\n" % why, r.steps, r.ceiling_s)
                r.halt, r.proxy = why, px
                return r, px
            r, px2 = CH.deps_step(["flutter test --no-pub %s" % rel], tree, sb, tmp, env=env, hosts=proxy_hosts)
            for k, v in px2.items():
                px[k] = px.get(k, 0) + v if isinstance(v, int) else v
        # a pristine checkout lacks the git-ignored ASSETS pubspec lists (word_app: assets/data.db),
        # and the asset bundle is built before the hooks. The engine writes EMPTY placeholders
        # (never an original: this step has the network) and retries, at most twice.
        for _ in range(2):
            missing = [m for m in MISSING_ASSET_RE.findall(r.raw or "") if m not in placeholders]
            if r.passed or not missing:
                break
            for m in missing:
                n = os.path.normpath(m)
                dst = os.path.join(tree, n)
                if n.startswith("..") or os.path.isabs(n) or os.path.lexists(dst) or \
                        not os.path.realpath(dst).startswith(os.path.realpath(tree) + os.sep):
                    continue
                try:
                    FS.write_bytes(tree, n, b"")              # K3r6-B1: never through a link
                except FS.UnsafePath:
                    continue
                placeholders.append(n)
            r, px2 = CH.deps_step(["flutter test --no-pub %s" % rel], tree, sb, tmp, env=env, hosts=proxy_hosts)
            for k, v in px2.items():
                px[k] = px.get(k, 0) + v if isinstance(v, int) else v
        if placeholders:
            px = dict(px, placeholders=placeholders)
        r.proxy = px
        return r, px
    finally:
        shutil.rmtree(wdir, True)
        # the test asset bundle built by the warm-up is ALWAYS dropped (K2r6-m1): it may hold the
        # EMPTY placeholders (measured, word_app: `no such table: words`) or <base>'s assets that
        # HEAD deleted or changed — the offline run rebuilds it from the tree it actually tests
        shutil.rmtree(os.path.join(tree, "build", "unit_test_assets"), True)
        for n in placeholders:
            try:
                FS.remove(tree, n)
            except (OSError, FS.UnsafePath):
                pass


def safety_net(r, info, has_base=True):
    """K2r7-M2: a red offline suite becomes `halted: env build-inputs-changed` only when the
    dependency state is in doubt — build inputs changed, OR the warm-up failed/was skipped (no base
    included), OR the dependency signature shows up while LOADING/COMPILING (before any test body
    runs). A `SocketException` inside a running test is an ordinary test failure."""
    if r.passed:
        return False
    doubt = (info.get("build_inputs") not in (None, "none")) or \
        (info.get("warm") or "").startswith(("failed", "skipped")) or not has_base
    return PF.dependency_failure(r.raw, r.rc, load_only=not doubt, report=getattr(r, "report", None),
                                 expect_report=bool(getattr(r, "report_expected", False)))


def with_json_report(cmd, path):
    """K3 (K2r8-m1): flutter's machine reporter beside the human one, into the run's tmp."""
    if "--file-reporter" in cmd or not FLUTTER_TEST_RE.match(cmd):
        return cmd
    return FLUTTER_TEST_RE.sub(lambda m: "%s --file-reporter json:%s" % (m.group(1), path), cmd, count=1)


FLUTTER_TEST_RE = re.compile(r"^(\s*(?:fvm\s+)?flutter\s+test)(?=\s|$)")


def offline_cmd(cmd):
    """The suite is OFFLINE; `flutter test` runs an implicit `pub get` that contacts pub.dev even
    when everything is resolved (measured, word_app: `dart pub get --example` → advisories fetch →
    `Failed host lookup: 'pub.dev'`, rc 69). Dependencies come from the engine's deps step and
    warm-up, so the engine adds `--no-pub` to a `flutter test` command that lacks it."""
    if "--no-pub" in cmd or "--pub" in cmd.split():
        return cmd
    return FLUTTER_TEST_RE.sub(r"\1 --no-pub", cmd, count=1)


def suite_in_tree(worktree, base, cmds, owner, timeout_s, run_dir, env, copy_list=(), issue=None,
                  extra_roots=(), journal=None, warm=True):
    """K2r4-M2 / K2r5-B1: the main suite in a temp tree prepared exactly like the effective re-runs
    (`effective.prepared_tree`): pristine <base> warmed in place under the deps proxy (unless the
    build inputs changed or there is no base) → HEAD + the worktree's uncommitted non-ignored files
    → ignored entries → `copy_ignored`; then the suite offline in `tree_sandbox`. Golden failure
    images come back to the worktree. The result carries `warm`, `skipped_ignored`,
    `ignored_copied` and — when red — `missing_ignored` (the git-ignored paths the output names)."""
    import shutil
    from workflows.dev import preflight as PF

    if not base and warm:                           # K2r7-m2: the same derivation as the effective check
        base = EFF.default_base(worktree)

    def _warm(b, tree, inspect=None):
        r, _px = warm_in_place(worktree, tree, run_dir, env, issue, extra_roots=extra_roots, inspect=inspect)
        return r
    use_warm = _warm if (warm and base) else None
    cmds = [offline_cmd(c) for c in cmds]
    with EFF.prepared_tree(worktree, base, [], use_warm, copy_list, overlay=True,
                           build_runner=EFF.uses_build_runner(cmds)) as (tt, info):
        if info["halt"]:
            # K2r6-B1: own hooks / path-git-override deps / a test config changed → nothing runs
            r = CH.CheckResult(False, None, False, "", [], int(timeout_s))
            r.warm, r.build_inputs_changed, r.missing_ignored = info["warm"], info["build_files"], []
            r.warm_detail, r.build_inputs = info.get("warm_detail"), info["build_inputs"]
            r.skipped_ignored, r.ignored_copied, r.tree_kb = list(tt.skipped_ignored), [], None
            return r
        sb = tree_sandbox(tt.path, run_dir, worktree, issue, extra_roots)
        reports = [os.path.join(run_dir, "tmp", "report-%d.jsonl" % i) for i in range(len(cmds))]
        os.makedirs(os.path.join(run_dir, "tmp"), exist_ok=True)
        r = CH.run_command([with_json_report(c, rp) for c, rp in zip(cmds, reports)], timeout_s, cwd=tt.path,
                           env=env, journal=journal, who="check-%s" % owner, sandbox=sb, tmp=os.path.join(run_dir, "tmp"))
        texts = []
        for i, c in enumerate(cmds):                 # a repo-configured `--file-reporter json:<rel>` wins
            m = re.search(r"--file-reporter[ =]json:(\S+)", c)
            if m and not os.path.isabs(m.group(1)):
                reports[i] = os.path.join(tt.path, m.group(1))
        for rp in reports:
            if os.path.exists(rp):
                with open(rp, encoding="utf-8", errors="replace") as fh:
                    texts.append(fh.read())
        r.report = "\n".join(texts) if texts else None
        r.report_expected = any(FLUTTER_TEST_RE.match(c) for c in cmds)
        for img in V.failing_images(r.raw):
            rel = os.path.relpath(img, tt.path) if os.path.isabs(img) else img
            src = tt._inside(os.path.normpath(rel)) if not rel.startswith("..") else None
            if src and os.path.isfile(src) and not os.path.islink(src) and rel.endswith(".png"):
                try:
                    FS.copy_in(worktree, rel, src)            # K3r6-B1
                except FS.UnsafePath:
                    pass
        r.missing_ignored = [] if r.passed else PF.missing_ignored(r.raw, worktree, tt.skipped_ignored, tt.path)
        # Option A safety net (K2r6-B1): a red offline run with a dependency-resolution/download
        # signature is an environment problem, not a test failure
        r.build_inputs_changed = (info["build_files"] or ["(dependency state)"]) \
            if safety_net(r, info, bool(base)) else None
        try:                                       # K2r5-m2: the per-run cost, on record
            du = subprocess.run(["du", "-sk", tt.path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
            r.tree_kb = int(du.stdout.split()[0]) if du.stdout else None
        except (OSError, subprocess.SubprocessError, ValueError):
            r.tree_kb = None
        r.raw = r.raw.replace(os.path.realpath(tt.path), worktree).replace(tt.path, worktree)
        r.warm = info["warm"] or ("skipped(no base)" if not base else None)
        r.warm_detail = info.get("warm_detail")
        r.build_inputs = info["build_inputs"]
        r.skipped_ignored = list(tt.skipped_ignored)
        r.ignored_copied = list(tt.copied)
        return r


# K3 (K2r6-m4): the live engine runs the K1 deps step in the Issue worktree before every suite —
# `pub get` ONLY (resolution runs no package code — review-k2-r8), so only the REGISTRY hosts are
# reachable (no GitHub release hosts: those serve native-asset hooks, which run in the warm-up).
DEPS_MAIN_CMDS = {"pubspec.yaml": ["flutter pub get"], "package.json": ["npm ci --ignore-scripts"]}   # (npm: see deps_main)
REGISTRY_HOSTS = {"pubspec.yaml": ("pub.dev", "pub.dartlang.org", "storage.googleapis.com"),
                  "package.json": ("registry.npmjs.org", "registry.yarnpkg.com")}


def read_allowlist(tree, run_dir):
    """K3 carry-over 3: what a networked step may read — the tree, the toolchain caches and SDK,
    the run dir, the engine's process-tool copies."""
    out = [os.path.realpath(tree) + "/**", os.path.realpath(run_dir) + "/**"]
    # the toolchain caches and SDK — NOT the per-user system temp dir (writable for `mktemp -t`, but
    # it holds every other process's temp files; the step's own TMPDIR is the run dir)
    shared_tmp = [r for r in ("/private/var/folders", "/var/folders")]
    out += [w for w in S.toolchain_writes(tree) if not any(os.path.realpath(w.rstrip("*").rstrip("/")).startswith(t)
                                                           for t in shared_tmp)]
    tools = os.path.join(os.path.expanduser("~"), ".cache", "guild-engine", "bin")
    out.append(tools + "/**")
    if os.path.exists(os.path.join(tree, "pubspec.yaml")):
        # measured (K3, word_app): the flutter tool lists the Android SDK at startup (any command,
        # `pub get` included) and exits on EPERM — an SDK, so in the allowlist (read only)
        for sdk in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                    os.path.join(os.path.expanduser("~"), "Library", "Android", "sdk")):
            if sdk and os.path.isdir(sdk):
                out.append(os.path.realpath(sdk) + "/**")
    if os.path.exists(os.path.join(tree, "package.json")):
        # measured (K3r2, word_app): npm is a script inside the node install (nvm puts it under the home
        # dir) — the node toolchain's prefix is an SDK, read only
        for pre in node_prefixes():
            out.append(pre + "/**")
    # git's xcrun shim reads its cache in the per-user temp dir (noise, not a failure, when denied)
    try:
        ut = subprocess.run(["getconf", "DARWIN_USER_TEMP_DIR"], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL).stdout.decode().strip()
        if ut:
            out.append(os.path.join(os.path.realpath(ut), "xcrun_db"))
    except OSError:
        pass
    return list(dict.fromkeys(out))


def node_prefixes():
    """K3r3-m1: the node install dir(s) — ONLY a `<prefix>/bin/<tool>` layout, never the home dir, an
    ancestor of it or `~/.local` (a `~/bin/node` would otherwise open the whole home)."""
    import shutil as _sh
    home = os.path.realpath(os.path.expanduser("~"))
    bad = {home, os.path.join(home, ".local"), "/", "/usr", "/opt", "/Users"}
    out = []
    for tool in ("node", "npm", "npx"):
        w = _sh.which(tool)
        if not w:
            continue
        real = os.path.realpath(w)
        pre = os.path.dirname(os.path.dirname(real))
        if os.path.basename(os.path.dirname(real)) != "bin" and "/lib/node_modules/" not in real:
            continue
        if "/lib/node_modules/" in real:
            pre = real.split("/lib/node_modules/")[0]
        if pre in bad or home.startswith(pre + "/"):
            continue
        if pre not in out:
            out.append(pre)
    return out


def deps_sandbox(tree, run_dir, repo_root, copy_list=(), issue=None, extra_roots=()):
    """The K1 deps step's sandbox in the Issue worktree: writes to the tree and the toolchain caches,
    reads limited to `read_allowlist`, the `copy_ignored` ORIGINALS denied (they sit in this tree),
    every OTHER checkout of the repo and the shared git dir denied."""
    sb = S.role_sandbox("tester-verify", None, run_dir, issue, toolchain=True, tool_writes=S.toolchain_writes(tree))
    fs = dict(sb["filesystem"])
    tr = os.path.realpath(tree)
    others = [r for r in repo_roots(repo_root) + [os.path.realpath(x) for x in extra_roots] if r != tr]
    fs["denyRead"] = list(fs.get("denyRead") or []) + [r + "/**" for r in others] + \
        [os.path.join(tr, os.path.normpath(c)) + ("/**" if os.path.isdir(os.path.join(tr, c)) else "")
         for c in copy_list or [] if c and not os.path.isabs(c) and not os.path.normpath(c).startswith("..")]
    fs["denyWrite"] = list(fs.get("denyWrite") or []) + [r + "/**" for r in others] + [tr + "/.git/**"]
    fs["allowWrite"] = [a for a in fs.get("allowWrite") or [] if not a.startswith(tr)] + [tr + "/**"]
    fs["readOnlyAllow"] = read_allowlist(tree, run_dir)
    fs["denyRead"] = list(fs["denyRead"]) + [os.path.join(pre, "etc", "npmrc") for pre in node_prefixes()]
    return dict(sb, filesystem=fs)


def base_manifests(worktree, base):
    """{name: bytes} of <base>'s package.json / package-lock.json (K3r4-M1: the CHECK TOOLS come from
    <base>, never from the branch's manifests)."""
    out = {}
    for f in ("package.json", "package-lock.json"):
        if base and G.ok(worktree, "cat-file", "-e", "%s:%s" % (base, f)):
            out[f] = G.run(worktree, "show", "%s:%s" % (base, f))
    return out


def node_dir(worktree, manifests=None, tools=(), kind="tools"):
    """The ENGINE-owned node_modules home, keyed by <base>'s manifests (+ the extra check tools):
    outside every role's allowWrite; roles see it only through the `node_modules` symlink the engine
    (re)creates. Shared by the repo's Issues with the same base manifests (installs are locked)."""
    import hashlib
    h = hashlib.sha256()
    for f in sorted(manifests or {}):
        h.update(f.encode() + b"\0" + manifests[f])
    h.update(("\0".join(sorted(tools))).encode())
    h.update(b"\0kind=" + kind.encode())        # K3r5-M1: the check tools (base) and the suite deps (branch) never share
    # beside the run root (`~/.cache/guild-engine/<repo-hash>/`): engine-owned, no role allowWrite reaches
    # it, readable by the sandboxes (the shared git dir is not — the deps step denies it)
    root = os.path.dirname(os.path.dirname(RR.run_root(worktree, 0)))
    return os.path.join(root, "node", h.hexdigest()[:16])


def link_node_modules(worktree, nd):
    """Replace whatever `node_modules` the worktree has (a role may have changed it) by a symlink to
    the engine's prepared dir."""
    import shutil as _sh
    FS.symlink(worktree, "node_modules", os.path.join(nd, "node_modules"))   # atomic, never through a link


def install_check_tools(worktree, run_dir, env, mans, tools, copy_list=(), issue=None, timeout_s=1800, kind="tools"):
    """`npm install --ignore-scripts` of <base>'s manifests (+ `--no-save` extra tools) into the shared
    engine dir, under an exclusive lock (K3r4-m5), into a temp dir renamed into place (atomic), cached:
    an existing complete install is reused. Returns (CheckResult|None, proxy, node_bin|None)."""
    import fcntl
    import shutil as _sh
    import tempfile
    nd = node_dir(worktree, mans, tools, kind)
    os.makedirs(os.path.dirname(nd), exist_ok=True)
    with open(nd + ".lock", "w") as lk:      # fs-ok: engine cache dir, no role writes there
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            if os.path.exists(os.path.join(nd, ".complete")):
                return None, {}, os.path.join(nd, "node_modules", ".bin")
            tmp = tempfile.mkdtemp(prefix=os.path.basename(nd) + ".tmp", dir=os.path.dirname(nd))
            for f, data in mans.items():
                with open(os.path.join(tmp, f), "wb") as fh:
                    fh.write(data)
            pkg = {}
            try:
                pkg = json.loads(mans["package.json"].decode("utf-8"))
            except ValueError:
                pass
            have = set(pkg.get("dependencies") or {}) | set(pkg.get("devDependencies") or {})
            cmds = ["npm ci --ignore-scripts --no-audit --no-fund" if "package-lock.json" in mans else
                    "npm install --ignore-scripts --no-audit --no-fund --no-package-lock"]
            extra = [t for t in tools if t not in have and re.match(r"^[@\w./-]+$", t)]
            if extra:
                cmds.append("npm install --ignore-scripts --no-audit --no-fund --no-package-lock --no-save %s"
                            % " ".join(shlex.quote(t) for t in extra))
            sb = deps_sandbox(worktree, run_dir, worktree, copy_list, issue)
            sb["filesystem"]["allowWrite"] = list(sb["filesystem"]["allowWrite"]) + [tmp + "/**"]
            sb["filesystem"]["readOnlyAllow"] = list(sb["filesystem"]["readOnlyAllow"]) + [tmp + "/**"]
            r, px = CH.deps_step(cmds, tmp, sb, os.path.join(run_dir, "tmp"), env=env,
                                 hosts=REGISTRY_HOSTS["package.json"], timeout_s=timeout_s)
            if not (r.passed and os.path.isdir(os.path.join(tmp, "node_modules"))):
                _sh.rmtree(tmp, True)
                return r, px, None
            open(os.path.join(tmp, ".complete"), "w").close()
            if os.path.exists(nd):
                _sh.rmtree(nd, True)
            os.rename(tmp, nd)                    # fs-ok: engine cache dir
            return r, px, os.path.join(nd, "node_modules", ".bin")
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def deps_main(worktree, run_dir, env, copy_list=(), issue=None, timeout_s=1800, tools=(), base=None):
    """The K1 deps step for EVERY manifest, resolve/download only, under the registry-only proxy:
    pubspec → `flutter pub get` in the worktree; package.json → the CHECK TOOLS from <base>'s
    package.json/lock (K3r4-M1 — a branch manifest cannot break or substitute them) installed
    (`--ignore-scripts`, plus the `npx` tools the 1L checks call, `--no-save`) into the ENGINE-owned,
    locked, cached `node_dir`, then the worktree's `node_modules` → a symlink to it.
    The pubspec result is the step's verdict; the node step is best-effort (a 1L check that needs a tool
    it did not prepare is then `skipped(env)` by the engine's precondition). Returns CheckResult (with
    `.proxy`, `.notes`, `.node_bin`) or None when the repo has no known manifest."""
    import shutil as _sh
    first, notes, node_bin = None, [], None
    if os.path.exists(os.path.join(worktree, "pubspec.yaml")):
        sb = deps_sandbox(worktree, run_dir, worktree, copy_list, issue)
        first, px = CH.deps_step(["flutter pub get"], worktree, sb, os.path.join(run_dir, "tmp"), env=env,
                                 hosts=REGISTRY_HOSTS["pubspec.yaml"], timeout_s=timeout_s)
        first.proxy = px
    # K3r5-M1 — TWO node installs: the SUITE's (and the roles') from the BRANCH's manifests, linked into
    # the worktree; the 1L CHECK TOOLS from <base>'s manifests, engine-owned, used only by the checks
    branch_mans = {}
    for f in ("package.json", "package-lock.json"):
        fp = os.path.join(worktree, f)
        if os.path.isfile(fp) and not os.path.islink(fp):
            with open(fp, "rb") as fh:
                branch_mans[f] = fh.read()
    suite_node = None
    if "package.json" in branch_mans:
        rb, pxb, bin_b = install_check_tools(worktree, run_dir, env, branch_mans, (), copy_list, issue, timeout_s,
                                             kind="suite")
        if bin_b:
            suite_node = os.path.dirname(os.path.dirname(bin_b))
            link_node_modules(worktree, suite_node)
        if first is None:
            first = rb if rb is not None else CH.CheckResult(True, 0, False, "", [], 0)
            first.proxy = pxb
        elif rb is not None and not rb.passed:
            first = CH.CheckResult(False, rb.rc, False, (first.raw or "") + "\n" + (rb.raw or ""), first.steps + rb.steps,
                                   first.ceiling_s)
            first.proxy = pxb
    mans = base_manifests(worktree, base) if base else {}
    if "package.json" in mans and tools is not None:
        r, px, node_bin = install_check_tools(worktree, run_dir, env, mans, tools, copy_list, issue, timeout_s)
        if not node_bin:
            notes.append("check tools (<base> manifests) failed: %s"
                         % CH.redact_lines(((r.raw if r else "").strip().split("\n") or ["?"])[-1]))
        if first is None:
            first = CH.CheckResult(True, 0, False, "", [], 0)
            first.proxy = px
    if first is not None:
        first.suite_node = suite_node
    if first is not None:
        first.notes, first.node_bin = notes, node_bin
    return first


def role_spec(call, issue, worktree, config, base=None, branch=None, unattended=True):
    per = config.persona(call.role) if hasattr(config, "persona") else None
    model = getattr(call, "model", None) or (per.model if per else None) or "sonnet"
    return RR.RoleSpec(call.role, call.task, prompt(call, issue), issue, call.stage, call.step, worktree,
                       model, persona=(per.body if per else ""), inputs=call.inputs, base=base,
                       branch=branch, attempt=call.attempt,
                       result_schema=call.schema or (RESULT_SCHEMAS.get(call.schema_role) if call.role != "designer" else None),
                       allowed_status=call.allowed_status or RR.R.STATUSES,
                       language=getattr(config, "language", "en"), unattended=unattended,
                       toolchain=("test",) if call.role in ("tester", "qa") else (),
                       pre_check=getattr(call, "pre_check", None))


def live(issue, worktree, base, branch, config, clock, gh, writer, decisions, runner, judge_runner,
         journal=None, unattended=True, push_url=None, host=None, plugin=None, impl_files=None):
    root_env = dict(runner.parent_env)
    if worktree and os.path.isdir(worktree):
        recover_check_backup(worktree)       # K3r6-m2: any stage's entry repairs an interrupted 1L check swap

    def run_role(call):
        return runner.run_role(role_spec(call, issue, worktree, config, base, branch, unattended))

    def _tree_run(cmds, tree, owner, timeout_s):
        run_dir = RR.new_run_dir(RR.run_root(worktree, issue, root_env), "check", owner)
        sb = tree_sandbox(tree, run_dir, worktree, issue)
        env = C.child_env(root_env, {}, role_dir=run_dir)
        r = CH.run_command(cmds, timeout_s, cwd=tree, env=env, journal=journal, who="check-%s" % owner,
                           sandbox=sb, tmp=os.path.join(run_dir, "tmp"))
        runner.rebaseline(worktree, issue)
        return r

    def _copy_list():
        raw = getattr(config, "raw", None) or (config if isinstance(config, dict) else {})
        return ((raw.get("engine") or {}).get("effective") or {}).get("copy_ignored") or []

    def suite(cmds, owner, timeout_s):
        """K2r5-B1: `suite_in_tree` — never in the checkout (no ignored original is reachable)."""
        run_dir = RR.new_run_dir(RR.run_root(worktree, issue, root_env), "check", owner)
        r = suite_in_tree(worktree, base, cmds, owner, timeout_s, run_dir, C.child_env(root_env, {}, role_dir=run_dir),
                          _copy_list(), issue, journal=journal)
        runner.rebaseline(worktree, issue)
        return r

    def check(cmd, cwd, owner, timeout_s, write_dirs):
        # OFFLINE (K2r2-M1): the role-written test and the reverted impl get no network at all;
        # `cwd` is the effective check's temp tree
        return _tree_run([cmd], cwd, owner, timeout_s)

    def warm(rev, tree, inspect=None):
        """The engine's own warm-up (K2r4-M1, K2r7-M1): `warm_in_place` on the pristine tree."""
        run_dir = RR.new_run_dir(RR.run_root(worktree, issue, root_env), "check", "warmup")
        r, _px = warm_in_place(worktree, tree, run_dir, C.child_env(root_env, {}, role_dir=run_dir), issue,
                               inspect=inspect)
        return r

    def capture(kind, stage, role, summary, evidence, area, surprise):
        return CAP.capture(worktree, kind, issue, stage, role, summary, evidence, area, surprise, clock=clock)

    def mark(stage):
        return CAP.mark(worktree, issue, stage, clock=clock)

    def push():
        if not push_url or not branch:
            return False
        local = G.run(worktree, "rev-parse", "refs/heads/%s" % branch, check=False).decode().strip()
        remote = G.run(worktree, "ls-remote", push_url, "refs/heads/%s" % branch, check=False).decode().split()
        if not local or (remote and remote[0] == local):
            return False
        bad = runner.drift_check(worktree, issue)
        if bad:
            raise RuntimeError("drift before the engine push: %s" % bad)
        G.push(worktree, push_url, "refs/heads/%s:refs/heads/%s" % (branch, branch))
        return local                    # the pushed sha (qa's PR CI reads its check-runs)

    ports = Ports(issue, gh, writer, decisions, clock, config, worktree, unattended=unattended,
                 run_role=run_role, judge=judge_runner.judge, suite=suite, check=check, capture=capture,
                 mark=mark, journal=journal, push=push, host=host, plugin=plugin, branch=branch,
                 base=base, impl_files=impl_files)
    ports.warm = warm
    return ports


# ---- K3: the execute stage's live ports ------------------------------------------------------------

def live_execute(issue, main, variant, config, clock, gh, writer, decisions, runner, judge_runner,
                 push_url, journal=None, unattended=True, host=None, plugin=None, env=None, local_dev_py=None,
                 worktree_path=None):
    """Resolve base/branch/worktree FIRST (the role/suite closures of `live()` bind the worktree),
    then the shared ports plus the execute ones: vcs, deps (K1 deps step in the worktree before
    every suite), push_branch (drift check → fixed URL → hooks off; never force), remote_has_branch,
    local_dev / commit_local (1L), run_tmp, the sprint stack/draft env. A branch problem is kept
    and raised by `p.prepare` inside the stage, which turns it into the needs-human exit."""
    import json as _json
    from guildcore.records import loopback as _LB
    from guildcore.records import markers as _M
    from workflows.dev import branching as BR
    from workflows.dev import variants as VR
    from workflows.dev import vcs as VC
    from workflows.dev.stages import execute as X
    env = dict(env if env is not None else os.environ)
    raw = getattr(config, "raw", None) or (config if isinstance(config, dict) else {})
    copy_list = ((raw.get("engine") or {}).get("effective") or {}).get("copy_ignored") or []
    lb = _LB.from_comments(_M.trusted(gh.comments(issue)))
    lb_branch = lb.latest_active().get("branch") if lb is not None and lb.not_yet_handled() else None
    prepared, problem = None, None
    try:
        default = BR.default_branch(main)
        base = BR.resolve_base(main, env.get("GLD_SPRINT_BASE"), "origin/%s" % default if default else None, issue)
        miss = BR.recover_base(main, base, default)
        if miss:
            raise BR.BranchProblem("base-missing", miss)
        cur = G.run(main, "rev-parse", "--abbrev-ref", "HEAD", check=False).decode().strip()

        def related(name, log):
            d = judge_runner.judge(__import__("workflows.dev.judging", fromlist=["x"]).spec(
                None, "BRANCH", [("issue", "#%d %s" % (issue, gh.issue(issue).get("title") or "")),
                                 ("branch", name), ("log", log[:3000])], "execute", "X0"))
            return d.choice
        cands = BR.candidates(main, issue, base, cur, related)
        branch = BR.decide(cands, lb_branch, cur)
        fresh = branch is None
        if fresh:
            tpl = (raw.get("engine") or {}).get("branch_template")
            branch = VR.branch_name(variant, issue, gh.issue(issue).get("title"), tpl)
        path = worktree_path or BR.worktree_path(main, issue)
        got = BR.prepare(main, path, branch, base, fresh, copy_list)
        prepared = dict(got, branch=branch, base=base, fresh=fresh)
    except BR.BranchProblem as bp:
        problem = bp
    worktree = prepared["path"] if prepared else main
    p = live(issue, worktree, prepared["base"] if prepared else None, prepared["branch"] if prepared else None,
             config, clock, gh, writer, decisions, runner, judge_runner, journal=journal, unattended=unattended,
             push_url=push_url, host=host, plugin=plugin)
    root_env = dict(runner.parent_env)

    def prepare(_lb_branch):
        if problem is not None:
            raise problem
        return prepared
    p.prepare = prepare
    if prepared:
        recover_check_backup(worktree)                  # a crash during an earlier run's 1L checks
    p.vcs = VC.Vcs(worktree)
    p.remote_url = push_url
    p.default_branch = BR.default_branch(main)
    p.draft = env.get("GLD_SPRINT_DRAFT") == "1"
    try:
        p.stack = _json.loads(env.get("GLD_SPRINT_STACK_JSON") or "null")
    except ValueError:
        p.stack = None

    def run_tmp(tag):
        return RR.new_run_dir(RR.run_root(worktree, issue, root_env), "check", tag)
    p.run_tmp = run_tmp

    def base_checks():
        from workflows.dev import local_checks as LC
        lh = None
        for name in ("lefthook.yml", "lefthook.yaml", ".lefthook.yml", ".lefthook.yaml"):     # K3r3-m4
            if p.base and G.ok(worktree, "cat-file", "-e", "%s:%s" % (p.base, name)):
                lh = G.run(worktree, "show", "%s:%s" % (p.base, name)).decode("utf-8", "replace")
                break
        skipped = []
        return LC.derive(lh, raw, skipped), skipped

    state = {"deps": None}

    def deps():
        from workflows.dev import local_checks as LC
        rd = run_tmp("deps")
        tools = LC.npx_tools(base_checks()[0]) if ((raw.get("local_developer") or {}).get("enabled")) else ()
        r = deps_main(worktree, rd, C.child_env(root_env, {}, role_dir=rd), copy_list, issue, tools=tools, base=p.base)
        state["deps"] = r if r is not None else CH.CheckResult(True, 0, False, "", [], 0)
        runner.rebaseline(worktree, issue)
        return r
    p.deps = deps

    def push_branch():
        """D-5.1/D-5.9: drift check → fixed-URL push (hooks off) → verify the remote ref."""
        bad = runner.drift_check(worktree, issue)
        if bad:
            raise X.PushProblem("defect", "drift before the engine push: %s" % bad)
        local = G.run(worktree, "rev-parse", "refs/heads/%s" % p.branch, check=False).decode().strip()
        try:
            G.push(worktree, push_url, "refs/heads/%s:refs/heads/%s" % (p.branch, p.branch))
        except G.GitError as e:
            msg = str(e)
            if re.search(r"non-fast-forward|fetch first|rejected", msg):
                raise X.PushProblem("diverged", msg)
            if re.search(r"protected|permission|denied|403", msg, re.I):
                raise X.PushProblem("defect", "push refused for %s — %s" % (p.branch, msg.split("\n")[0]))
            raise X.PushProblem("transient", "push failed for %s — %s" % (p.branch, msg.split("\n")[0]))
        remote = G.run(worktree, "ls-remote", push_url, "refs/heads/%s" % p.branch, check=False).decode().split()
        if not remote or remote[0] != local:
            raise X.PushProblem("defect", "pushed %s but the remote ref does not show it" % p.branch)
        runner.rebaseline(worktree, issue)
        return local
    p.push_branch = push_branch

    def remote_has_branch(name):
        """D-5.2 tri-state: True (exists), False (exit 0, empty), None (the call failed)."""
        try:
            return bool(G.run(worktree, "ls-remote", "--heads", push_url, name, timeout=120).strip())
        except (G.GitError, subprocess.SubprocessError):
            return None
    p.remote_has_branch = remote_has_branch

    ld_py = local_dev_py or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "commands",
                                         "atoms", "local_dev.py")

    def local_dev(args):
        """K3r1-B3 (P1): local_dev.py runs model-written code (`test_cmd`, `lint_cmd` over the local
        model's impl and the role's tests) — so it runs in the check sandbox with the scrubbed role
        env; the only network is the local model's loopback port."""
        rd = run_tmp("local-dev")
        env = C.child_env(root_env, {}, role_dir=rd)
        env.update(S.render_gitconfig(worktree, os.path.join(rd, "in", "gitconfig")))
        port = ollama_port(raw)
        cmd = " ".join(shlex.quote(x) for x in ["python3", os.path.abspath(ld_py)] + list(args))
        r = CH.run_command([cmd], 7200, cwd=worktree, env=env, sandbox=local_sandbox(worktree, rd, issue),
                           tmp=os.path.join(rd, "tmp"), allow_ports=(port,) if port else ())
        out = r.raw or ""
        if r.rc != 0 or ">>> LOCAL-DEV <<<" not in out:
            raise RuntimeError((out.strip().split("\n") or ["?"])[-1])
        return _json.loads(out.split(">>> LOCAL-DEV <<<", 1)[1].strip().split("\n", 1)[0])
    p.local_dev = local_dev

    def commit_local(files, tests, variant="implement"):
        """1L-5 (K3r1-B4, K3r2-M2): the pre-commit hook's own checks (from <base>'s lefthook.yml —
        `local_checks.derive`) run OFFLINE in the 1L sandbox over the staged files, then <base>'s
        gate `--git-hook` (rc ≠ 0 refuses), then the engine commit with hooks off. A check that cannot
        run for an environment reason is `skipped(env)` (decision log + PR unattended log), never a
        refusal. Only paths the worktree really changed are staged (`--literal-pathspecs`, K3r2-m4)."""
        from workflows.dev import local_checks as LC
        from workflows.dev.stages import base as SB
        import shutil as _sh
        recover_check_backup(worktree)
        if state["deps"] is None:                       # K3r3-M2: a 1L commit never precedes the deps step
            p.deps()
        if not getattr(state["deps"], "passed", True):  # K3r5-m1: never analyze over a stale package config
            return False, "dependency step failed — %s" % CH.redact_lines(
                ((state["deps"].raw or "").strip().split("\n") or ["?"])[-1])
        changed = set(x[3:] for x in G.run(worktree, "status", "--porcelain", "-uall").decode("utf-8", "replace")
                      .split("\n") if len(x) > 3)
        paths = [x for x in dict.fromkeys(list(files) + list(tests)) if x in changed]
        if not paths:
            return False, "nothing the local job changed is in the worktree"
        G.run(worktree, "--literal-pathspecs", "add", "--", *paths)
        rd = run_tmp("gate")
        sb = local_sandbox(worktree, rd, issue)
        env = C.child_env(root_env, {}, role_dir=rd)
        env.update(S.render_gitconfig(worktree, os.path.join(rd, "in", "gitconfig")))
        env["npm_config_offline"] = "true"           # measured: npx otherwise waits ~70 s for the registry
        staged = [x for x in G.run(worktree, "diff", "--cached", "--name-only").decode("utf-8", "replace").split("\n") if x]
        node_bin = getattr(state["deps"], "node_bin", None)
        tools_node = os.path.dirname(os.path.dirname(node_bin)) if node_bin and os.path.isdir(node_bin) else None
        base_dir = os.path.join(rd, "in", "base-scripts")
        base_sha = G.run(worktree, "rev-parse", p.base).decode().strip()

        def base_has(path):
            n = os.path.normpath(path)
            return not n.startswith("..") and not os.path.isabs(n) and G.ok(worktree, "cat-file", "-e", "%s:%s" % (base_sha, n))

        def base_export(path):
            n = os.path.normpath(path)
            os.makedirs(base_dir, exist_ok=True)
            return FS.write_bytes(base_dir, n, G.run(worktree, "show", "%s:%s" % (base_sha, n)), 0o555)
        checks, dropped = base_checks()
        try:
            restore = base_check_configs(worktree, base_sha, p, tools_node,     # K3r4-m3 / K3r5: <base> configs
                                         getattr(state["deps"], "suite_node", None))   # and <base> tools for the checks
        except CheckConfigLink as e:                                            # K3r6-B1
            SB.record_code(p, "execute", "check-config-link", "refused", refs=e.rel, reason=str(e))
            return False, str(e)
        try:
            refused = run_checks(p, worktree, checks, staged, node_bin, base_has, base_export, sb, env, rd)
        finally:
            restore()
        if refused:
            return False, refused
        base_sha = G.run(worktree, "rev-parse", p.base).decode().strip()
        gates = S.export_gates_readonly(worktree, base_sha)[0]
        gate = os.path.join(gates, "scripts", "gate_precommit.py") if gates else None
        if gate and not os.path.exists(gate):
            gate = os.path.join(gates, "gate_precommit.py")
        if gate and os.path.exists(gate):
            genv = dict(env, GUILD_GATE_CONFIG=S.gate_config_path(gates))
            r = CH.run_command(["python3 %s --git-hook </dev/null" % shlex.quote(gate)], 600, cwd=worktree, env=genv,
                               sandbox=sb, tmp=os.path.join(rd, "tmp"))
            if not r.passed:
                return False, "gate: " + CH.redact_lines((r.raw.strip().split("\n") or ["gate refused"])[0])
        kind = {"debug": "fix", "refactor": "refactor"}.get(variant, "feat")
        G.commit(worktree, "%s(#%d): local model implementation" % (kind, issue))
        runner.rebaseline(worktree, issue)
        return True, None
    p.commit_local = commit_local

    def net_run(rev, files):
        """K3r2-M3 / K3r3-M3: the engine's own net run — `net_in_tree` (the suite's preparation)."""
        rd = run_tmp("net")
        r = net_in_tree(worktree, p.base, rev, files, raw, copy_list, rd, C.child_env(root_env, {}, role_dir=rd), issue)
        runner.rebaseline(worktree, issue)
        return r
    p.net_run = net_run
    return p


def ollama_port(raw):
    import re as _re
    url = ((raw or {}).get("local_developer") or {}).get("ollama_url") or "http://127.0.0.1:11434"
    m = _re.match(r"^https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::(\d+))?", url)
    return int(m.group(1) or 80) if m else None


def local_sandbox(worktree, run_dir, issue=None):
    """The developer's check sandbox for engine-run, model-written code (1L): worktree writes, the
    Guild memory dir writable (local_dev's job state), but the harness files stay denied — the gate,
    its config, settings, agents."""
    sb = S.role_sandbox("developer", worktree, run_dir, issue, toolchain=True, tool_writes=S.toolchain_writes(worktree))
    fs = dict(sb["filesystem"])
    wt = os.path.realpath(worktree)
    cl = os.path.join(wt, ".claude")
    fs["denyWrite"] = [d for d in fs.get("denyWrite") or [] if os.path.realpath(d.rstrip("*").rstrip("/")) != cl] + \
        [os.path.join(cl, x) for x in ("settings.json", "settings.local.json", "agents/**", "guild/gates/**",
                                       "guild/config.json", "guild/knowledge/**", "commands/**", "skills/**")]
    fs["allowWrite"] = list(fs.get("allowWrite") or []) + [os.path.join(cl, "guild", "memory") + "/**"]
    return dict(sb, filesystem=fs)


def net_command(raw, files):
    """A per-file command for the configured runner (no snapshot writes), or None."""
    from workflows.dev import effective as _E
    rn = _E.runner_of(raw or {})
    q = " ".join(shlex.quote(f) for f in files)
    return {"flutter": "flutter test --no-pub %s", "dart": "dart test %s", "jest": "npx jest --ci %s",
            "vitest": "npx vitest run %s", "pytest": "python3 -m pytest -q %s",
            "unittest": "python3 -m unittest -v %s"}.get(rn, "") % q if rn in (
        "flutter", "dart", "jest", "vitest", "pytest", "unittest") else None


def net_in_tree(worktree, base, rev, files, raw, copy_list, run_dir, env, issue=None, timeout_s=1800):
    """The refactor net's files run by the ENGINE at `rev` in a tree prepared EXACTLY like the suite
    (K3r3-M3): pristine <base> warmed in place (native-assets hooks keep their cache paths), then moved
    to `rev` (the proof — unchanged production + the net — or HEAD), ignored entries + `copy_ignored`,
    then the files offline in `tree_sandbox` with the machine reporter. A dependency/build failure (the
    safety net of the suite) marks the result `.env` — the caller records `unverified(net: env)`, never
    RED. None when the runner cannot be driven per file."""
    cmd = net_command(raw, files)
    if not cmd:
        return None

    def _warm(b, tree, inspect=None):
        r, _px = warm_in_place(worktree, tree, run_dir, env, issue, inspect=inspect)
        return r
    os.makedirs(os.path.join(run_dir, "tmp"), exist_ok=True)
    rep = os.path.join(run_dir, "tmp", "net-report.jsonl")
    with EFF.prepared_tree(worktree, base, [], _warm if base else None, copy_list, target=rev) as (tt, info):
        if info["halt"]:
            r = CH.CheckResult(False, None, False, "", [], int(timeout_s))
            r.env = "build inputs: %s" % ", ".join(info["build_files"][:3])
            r.warm = info["warm"]
            return r
        sb = tree_sandbox(tt.path, run_dir, worktree, issue)
        c = with_json_report(offline_cmd(cmd), rep)
        r = CH.run_command([c], timeout_s, cwd=tt.path, env=env, sandbox=sb, tmp=os.path.join(run_dir, "tmp"))
        r.report = open(rep, encoding="utf-8", errors="replace").read() if os.path.exists(rep) else None
        r.report_expected = bool(FLUTTER_TEST_RE.match(c))
        r.warm = info["warm"]
        r.env = net_env(info, r)
        return r


def net_env(info, r):
    """K3r4-m1: `env` from ENGINE-side signals only — the warm-up's result and the tree preparation.
    A failure while the role-written net tests load or run (loader errors included) is RED."""
    w = (info or {}).get("warm") or ""
    if r.passed:
        return None
    if w.startswith(("failed", "skipped")):        # K3r5: a skipped warm-up is engine-side too
        return "warm-up %s" % w
    return None


CHECK_CONFIGS = (".remarkrc", ".remarkrc.json", ".remarkrc.js", ".remarkrc.cjs", ".remarkrc.mjs", ".remarkrc.yml",
                 ".remarkrc.yaml", ".remarkignore", "cspell.json", ".cspell.json", "cspell.config.json",
                 "cspell.config.yaml", "cspell.config.yml", "cspell.yaml", "cspell.yml", ".cspell.config.json",
                 "analysis_options.yaml", ".markdownlint.json", ".markdownlintignore", ".prettierrc", ".prettierignore",
                 ".editorconfig")


WORDLIST_MAX_BYTES = 2 * 1024 * 1024
WORDLIST_MAX_LINES = 200000


class CheckConfigLink(Exception):
    """A check config (or a word list) the engine would swap sits on a symlink / is not a plain file."""

    def __init__(self, rel, why):
        Exception.__init__(self, "check config is not a plain in-tree file: %s (%s)" % (rel, why))
        self.rel = rel


CSPELL_JSON = ("cspell.json", ".cspell.json", "cspell.config.json", ".cspell.config.json")


def check_backup_path(worktree):
    """Where the swap of the check configs is journaled (engine-owned, outside the worktree)."""
    import hashlib
    root = os.path.dirname(os.path.dirname(RR.run_root(worktree, 0)))
    return os.path.join(root, "check-backup-%s.json" % hashlib.sha256(os.path.realpath(worktree).encode()).hexdigest()[:12])


def recover_check_backup(worktree):
    """K3r5 crash safety: an engine killed while the checks ran left <base> configs (and the tools'
    node_modules link) in the worktree — put the branch's bytes back. Returns the restored paths."""
    import base64
    bp = check_backup_path(worktree)
    if not os.path.exists(bp):
        return []
    with open(bp) as fh:
        rec = json.load(fh)
    done = []
    for ent in rec.get("files") or []:              # K3r6-B1: restores go through fsafe as well
        try:
            if ent["data"] is None:
                FS.remove(worktree, ent["rel"])
            else:
                FS.write_bytes(worktree, ent["rel"], base64.b64decode(ent["data"]))
            done.append(ent["rel"])
        except FS.UnsafePath:
            pass                                    # a link planted since: left alone, never followed
    if "node_link" in rec:
        try:
            if rec["node_link"]:
                FS.symlink(worktree, "node_modules", rec["node_link"])
            else:
                FS.remove(worktree, "node_modules")
            done.append("node_modules")
        except FS.UnsafePath:
            pass
    os.remove(bp)
    return done


def merge_cspell(base_bytes, branch_bytes):
    """<base>'s cspell config + ONLY the branch's dictionary word ADDITIONS (`words`); the branch's
    ignorePaths / ignoreRegExpList / enabled / language settings never apply. Returns (bytes, added)."""
    try:
        b = json.loads(base_bytes.decode("utf-8"))
        r = json.loads(branch_bytes.decode("utf-8")) if branch_bytes else {}
    except ValueError:
        return base_bytes, []
    have = set(b.get("words") or [])
    added = [w for w in (r.get("words") or []) if isinstance(w, str) and w not in have]
    if added:
        b["words"] = list(b.get("words") or []) + added
    return json.dumps(b, ensure_ascii=False, indent=2).encode("utf-8"), added


def base_check_configs(worktree, base_sha, p=None, tools_node=None, suite_node=None):
    """K3r4-m3 / K3r5: the config files the check tools read are <base>'s (cspell: + the branch's added
    dictionary words, and lines added to word-list files <base>'s config references), and the
    worktree's `node_modules` points at the <base> TOOLS install for the checks only. The branch's bytes
    are journaled OUTSIDE the worktree first (`check_backup_path`) — `recover_check_backup` repairs a
    crash; the returned function restores normally. Differences go to the decision log."""
    import base64
    recover_check_backup(worktree)
    files, swaps = [], []

    def note(point, rel, reason):
        if p is not None:
            from workflows.dev.stages import base as SB
            SB.record_code(p, "execute", point, "base-used", refs=rel, reason=reason)
    dict_files = []
    def read_branch(rel):
        """K3r6-B1: the branch's bytes, read only when no component of the path is a symlink — a link
        anywhere refuses the whole swap (CheckConfigLink → the 1L commit is refused)."""
        try:
            dst = FS.resolve(worktree, rel)
        except FS.UnsafePath as e:
            raise CheckConfigLink(rel, str(e))
        if not os.path.lexists(dst):
            return None
        if not os.path.isfile(dst):
            raise CheckConfigLink(rel, "not a regular file")
        if os.path.getsize(dst) > WORDLIST_MAX_BYTES:
            raise CheckConfigLink(rel, "larger than %d bytes" % WORDLIST_MAX_BYTES)
        with open(dst, "rb") as fh:
            return fh.read()
    for rel in CHECK_CONFIGS:
        at_base = G.ok(worktree, "cat-file", "-e", "%s:%s" % (base_sha, rel))
        cur = read_branch(rel)
        here = cur is not None
        if not at_base and not here:
            continue
        base_bytes = G.run(worktree, "show", "%s:%s" % (base_sha, rel)) if at_base else None
        if rel in CSPELL_JSON and base_bytes is not None:
            try:
                for d in (json.loads(base_bytes.decode("utf-8")).get("dictionaryDefinitions") or []):
                    if isinstance(d, dict) and isinstance(d.get("path"), str):
                        dict_files.append(os.path.normpath(d["path"].lstrip("./")))
            except ValueError:
                pass
        if cur == base_bytes:
            continue
        want = base_bytes
        if rel in CSPELL_JSON and base_bytes is not None and cur is not None:
            want, added = merge_cspell(base_bytes, cur)
            if added:
                note("check-dictionary-words", rel, "words the branch added, kept for the checks: %s"
                     % ", ".join(added[:40]))
        if want == cur:
            continue
        files.append({"rel": rel, "data": base64.b64encode(cur).decode() if cur is not None else None})
        swaps.append((rel, want))
        note("check-config-changed", rel, "the branch %s %s; the 1L checks ran with <base>'s%s" % (
            "added" if not at_base else ("removed" if not here else "changed"), rel,
            " (+ its added dictionary words)" if rel in CSPELL_JSON else ""))
    for rel in dict_files:                         # word-list files: <base> + lines the branch ADDED
        if rel.startswith("..") or not G.ok(worktree, "cat-file", "-e", "%s:%s" % (base_sha, rel)):
            continue
        cur = read_branch(rel)
        if cur is None:
            continue
        base_bytes = G.run(worktree, "show", "%s:%s" % (base_sha, rel))
        if cur == base_bytes:
            continue
        bl = set(base_bytes.decode("utf-8", "replace").split("\n"))        # K3r6-m1: linear, capped
        lines = cur.decode("utf-8", "replace").split("\n")
        if len(lines) > WORDLIST_MAX_LINES:
            added = []
            note("check-dictionary-words", rel, "word list over %d lines — <base>'s list used" % WORDLIST_MAX_LINES)
        else:
            added = [w for w in lines if w.strip() and w not in bl]
        want = (base_bytes.decode("utf-8", "replace").rstrip("\n") + "\n" + "\n".join(added) + "\n").encode("utf-8")
        files.append({"rel": rel, "data": base64.b64encode(cur).decode()})
        swaps.append((rel, want))
        if added:
            note("check-dictionary-words", rel, "words the branch added, kept for the checks: %s" % ", ".join(added[:40]))
    rec = {"files": files}
    nm = os.path.join(worktree, "node_modules")
    if tools_node:
        rec["node_link"] = os.readlink(nm) if os.path.islink(nm) else (suite_node or None)
    bp = check_backup_path(worktree)
    os.makedirs(os.path.dirname(bp), exist_ok=True)
    with open(bp + ".tmp", "w") as fh:            # fs-ok: engine cache (the journal)
        json.dump(rec, fh)
    os.replace(bp + ".tmp", bp)                     # fs-ok: journaled BEFORE the worktree is touched
    for rel, want in swaps:
        if want is None:
            FS.remove(worktree, rel)
        else:
            FS.write_bytes(worktree, rel, want)
    if tools_node:
        link_node_modules(worktree, tools_node)

    def restore():
        recover_check_backup(worktree)
    return restore


def run_checks(p, worktree, checks, staged, node_bin, base_has, base_export, sb, env, rd):
    """Each derived check: engine-observed preconditions (`local_checks.prepare`) → skipped(env) on the
    record, else run offline in the 1L sandbox; a non-zero exit refuses. Returns the refusal or None."""
    import shutil as _sh
    from workflows.dev import local_checks as LC
    from workflows.dev.stages import base as SB
    for chk in checks:
        cmd = chk.command(staged)
        if cmd is None:
            continue
        run_cmd, why = LC.prepare(cmd, base_has, base_export, node_bin,
                                  lambda name: _sh.which(name, path=env.get("PATH")))
        if why:                                      # an ENGINE-observed precondition failed
            SB.record_code(p, "execute", "local-check", "skipped(env: %s)" % why[:120], refs=chk.name,
                           reason="check `%s` not run — %s" % (chk.name, why))
            continue
        r = CH.run_command([run_cmd], 1800, cwd=worktree, env=env, sandbox=sb, tmp=os.path.join(rd, "tmp"))
        if LC.classify(r) == "fail":
            return "check `%s`: %s" % (chk.name, CH.redact_lines((r.raw.strip().split("\n") or ["failed"])[-1]))
    return None
