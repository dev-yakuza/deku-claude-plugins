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

import os
import re
import subprocess

from guildcore import capture as CAP
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
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                open(dst, "wb").close()
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
                os.remove(os.path.join(tree, n))
            except OSError:
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
                dst = os.path.join(worktree, rel)
                if os.path.realpath(dst).startswith(os.path.realpath(worktree) + os.sep):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copyfile(src, dst)
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
DEPS_MAIN_CMDS = {"pubspec.yaml": ["flutter pub get"], "package.json": ["npm ci --ignore-scripts"]}
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
    # git's xcrun shim reads its cache in the per-user temp dir (noise, not a failure, when denied)
    try:
        ut = subprocess.run(["getconf", "DARWIN_USER_TEMP_DIR"], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL).stdout.decode().strip()
        if ut:
            out.append(os.path.join(os.path.realpath(ut), "xcrun_db"))
    except OSError:
        pass
    return list(dict.fromkeys(out))


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
    return dict(sb, filesystem=fs)


def deps_main(worktree, run_dir, env, copy_list=(), issue=None, timeout_s=1800):
    """Run the manifest's resolve-only dependency command in the worktree under the registry-only
    proxy. Returns CheckResult (with `.proxy`) or None when the repo has no known manifest."""
    for manifest, cmds in DEPS_MAIN_CMDS.items():
        if os.path.exists(os.path.join(worktree, manifest)):
            sb = deps_sandbox(worktree, run_dir, worktree, copy_list, issue)
            r, px = CH.deps_step(cmds, worktree, sb, os.path.join(run_dir, "tmp"), env=env,
                                 hosts=REGISTRY_HOSTS[manifest], timeout_s=timeout_s)
            r.proxy = px
            return r
    return None


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
                 push_url, journal=None, unattended=True, host=None, plugin=None, env=None):
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
        path = BR.worktree_path(main, issue)
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

    def deps():
        rd = run_tmp("deps")
        r = deps_main(worktree, rd, C.child_env(root_env, {}, role_dir=rd), copy_list, issue)
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

    ld_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "commands", "atoms", "local_dev.py")

    def local_dev(args):
        r = subprocess.run(["python3", os.path.abspath(ld_py)] + list(args), cwd=worktree, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=7200)
        out = r.stdout.decode("utf-8", "replace")
        if r.returncode != 0 or ">>> LOCAL-DEV <<<" not in out:
            raise RuntimeError((r.stderr.decode("utf-8", "replace").strip().split("\n") or ["?"])[-1])
        return _json.loads(out.split(">>> LOCAL-DEV <<<", 1)[1].strip().split("\n", 1)[0])
    p.local_dev = local_dev

    def commit_local(files, tests):
        """1L-5: the base's commit gate over the staged change, sandboxed, then the engine commit
        (hooks off — the gate already ran from <base> bytes; the suite runs right after)."""
        paths = list(dict.fromkeys(list(files) + list(tests)))
        G.run(worktree, "add", "--", *paths)
        gates = S.export_gates_readonly(worktree, G.run(worktree, "rev-parse", p.base).decode().strip())[0]
        if gates:
            gate = os.path.join(gates, "scripts", "gate_precommit.py")
            if os.path.exists(gate):
                rd = run_tmp("gate")
                sb = S.role_sandbox("developer", worktree, rd, issue, toolchain=True,
                                    tool_writes=S.toolchain_writes(worktree))
                r = CH.run_command(["python3 %s" % gate], 600, cwd=worktree,
                                   env=C.child_env(root_env, {"GUILD_GATE_CONFIG": os.path.join(gates, ".config.json")},
                                                   role_dir=rd), sandbox=sb, tmp=os.path.join(rd, "tmp"))
                if not r.passed:
                    return False, (r.raw.strip().split("\n") or ["gate refused"])[0]
        G.commit(worktree, "feat(#%d): local model implementation" % issue)
        runner.rebaseline(worktree, issue)
        return True, None
    p.commit_local = commit_local
    return p
