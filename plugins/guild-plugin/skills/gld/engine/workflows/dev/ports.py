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
from workflows.dev.stages.base import Ports

WARMUP_DART = ("import 'package:flutter_test/flutter_test.dart';\n\n"
               "void main() {\n  test('guild engine warm-up', () {});\n}\n")
PROMPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roles", "prompts")


def prompt(call, issue):
    with open(os.path.join(PROMPTS, "%s-%s.md" % (call.role, call.task)), encoding="utf-8") as fh:
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


def warm_in_place(root, tree, run_dir, env, issue=None, proxy_hosts=None, extra_roots=()):
    """K2r4-M1: the networked warm-up NEVER runs the developer's tree. `tree` holds a PRISTINE
    checkout of `<base>` (reviewed code, no ignored file, no `.git`): `pub get` + an ENGINE-written
    empty test (in a new dir outside `test/`) under the deps proxy, in `tree_sandbox`. The caller
    has classified the build inputs (`effective.build_inputs`): `none` → this is <base> and the
    caller then moves it to HEAD (`TempTree.advance`); `hosted-deps` → this is the HEAD copy (only
    hosted third-party package hooks run; no test config exists at its root). The warm-up dir and any
    placeholder are removed. Returns (CheckResult|None, proxy summary)."""
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
        r, px = CH.deps_step(["flutter pub get", "flutter test --no-pub %s" % rel], tree, sb, tmp,
                             env=env, hosts=proxy_hosts)
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

    def _warm(b, tree):
        r, _px = warm_in_place(worktree, tree, run_dir, env, issue, extra_roots=extra_roots)
        return r
    use_warm = _warm if (warm and base) else None
    cmds = [offline_cmd(c) for c in cmds]
    with EFF.prepared_tree(worktree, base, [], use_warm, copy_list, overlay=True) as (tt, info):
        if info["halt"]:
            # K2r6-B1: own hooks / path-git-override deps / a test config changed → nothing runs
            r = CH.CheckResult(False, None, False, "", [], int(timeout_s))
            r.warm, r.build_inputs_changed, r.missing_ignored = info["warm"], info["build_files"], []
            r.skipped_ignored, r.ignored_copied, r.tree_kb = list(tt.skipped_ignored), [], None
            return r
        sb = tree_sandbox(tt.path, run_dir, worktree, issue, extra_roots)
        r = CH.run_command(cmds, timeout_s, cwd=tt.path, env=env, journal=journal, who="check-%s" % owner,
                           sandbox=sb, tmp=os.path.join(run_dir, "tmp"))
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
            if (not r.passed and PF.dependency_failure(r.raw, r.rc)) else None
        try:                                       # K2r5-m2: the per-run cost, on record
            du = subprocess.run(["du", "-sk", tt.path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
            r.tree_kb = int(du.stdout.split()[0]) if du.stdout else None
        except (OSError, subprocess.SubprocessError, ValueError):
            r.tree_kb = None
        r.raw = r.raw.replace(os.path.realpath(tt.path), worktree).replace(tt.path, worktree)
        r.warm = info["warm"] or ("skipped(no base)" if not base else None)
        r.build_inputs = info["build_inputs"]
        r.skipped_ignored = list(tt.skipped_ignored)
        r.ignored_copied = list(tt.copied)
        return r


def role_spec(call, issue, worktree, config, base=None, branch=None, unattended=True):
    per = config.persona(call.role) if hasattr(config, "persona") else None
    model = (per.model if per else None) or "sonnet"
    return RR.RoleSpec(call.role, call.task, prompt(call, issue), issue, call.stage, call.step, worktree,
                       model, persona=(per.body if per else ""), inputs=call.inputs, base=base,
                       branch=branch, attempt=call.attempt,
                       result_schema=call.schema or (RESULT_SCHEMAS.get(call.schema_role) if call.role != "designer" else None),
                       allowed_status=call.allowed_status or RR.R.STATUSES,
                       language=getattr(config, "language", "en"), unattended=unattended,
                       toolchain=("test",) if call.role in ("tester", "qa") else ())


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

    def warm(base_rev, tree):
        """The engine's own warm-up (K2r4-M1): `warm_in_place` on the pristine <base> tree."""
        run_dir = RR.new_run_dir(RR.run_root(worktree, issue, root_env), "check", "warmup")
        r, _px = warm_in_place(worktree, tree, run_dir, C.child_env(root_env, {}, role_dir=run_dir), issue)
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
