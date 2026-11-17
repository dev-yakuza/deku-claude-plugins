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

from guildcore import capture as CAP
from guildcore import checks as CH
from guildcore.adapters import claude as C
from guildcore.adapters import git as G
from guildcore.roles import runner as RR
from guildcore.roles import settings as S
from guildcore.roles.result import RESULT_SCHEMAS
from workflows.dev.stages.base import Ports

PROMPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roles", "prompts")


def prompt(call, issue):
    with open(os.path.join(PROMPTS, "%s-%s.md" % (call.role, call.task)), encoding="utf-8") as fh:
        text = fh.read().replace("{issue}", str(issue))
    if call.addendum:
        text = text.rstrip("\n") + "\n\n" + call.addendum + "\n"
    return text


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

    def _sandboxed(cmds, cwd, owner, timeout_s, extra_write=()):
        run_dir = RR.new_run_dir(RR.run_root(worktree, issue, root_env), "check", owner)
        sb = S.role_sandbox(owner if owner in S.WRITER_ROLES else "%s-verify" % owner, worktree, run_dir,
                            issue, toolchain=True)
        if extra_write:
            fs = dict(sb.get("filesystem") or {})
            fs["allowWrite"] = list(fs.get("allowWrite") or []) + [x.rstrip("/") + "/**" for x in extra_write]
            if os.path.realpath(cwd) != os.path.realpath(worktree):
                # K2-B4: the temp tree symlinks ignored dirs of the MAIN worktree — read-only here
                fs["denyWrite"] = list(fs.get("denyWrite") or []) + [os.path.abspath(worktree) + "/**"]
            sb = dict(sb, filesystem=fs)
        env = C.child_env(root_env, {}, role_dir=run_dir)
        r = CH.run_command(cmds, timeout_s, cwd=cwd, env=env, journal=journal, who="check-%s" % owner,
                           sandbox=sb, tmp=os.path.join(run_dir, "tmp"))
        runner.rebaseline(worktree, issue)
        return r

    def suite(cmds, owner, timeout_s):
        return _sandboxed(cmds, worktree, owner, timeout_s)

    def check(cmd, cwd, owner, timeout_s, write_dirs):
        # the TEST `effective` re-run in the temp tree re-runs dependency build hooks (word_app:
        # sqlite3 native assets from GitHub releases — measured): the deps step's host allowlist
        from guildcore.checks.netproxy import AllowlistProxy
        with AllowlistProxy(CH.deps_hosts(worktree)) as px:
            root_env.update(px.env())
            try:
                return _sandboxed([cmd], cwd, owner, timeout_s, write_dirs)
            finally:
                for k in px.env():
                    root_env.pop(k, None)

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

    return Ports(issue, gh, writer, decisions, clock, config, worktree, unattended=unattended,
                 run_role=run_role, judge=judge_runner.judge, suite=suite, check=check, capture=capture,
                 mark=mark, journal=journal, push=push, host=host, plugin=plugin, branch=branch,
                 base=base, impl_files=impl_files)
