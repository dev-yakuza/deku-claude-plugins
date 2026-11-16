"""guildcore.roles.runner — `run_role(RoleSpec) -> RoleResult`, the §5 role-execution contract.

    run dir   $TMPDIR/guild-engine/<repo-hash>/<N>/runs/<seq>-<stage>-<who>/{in/,out/,stream.jsonl}
    settings  guildcore.roles.settings.render → <run>/in/settings.json (`--setting-sources ""`)
    argv      adapters.claude.role_argv (dontAsk + role allow list + always-deny, `--add-dir <run>`)
    env       adapters.claude.child_env over the parent env + merged settings env (endpoint guard)
    task.md   on stdin: the task template + the allowed-commands paragraph + the result contract
              (byte-identical to `_handoff.md`'s `guild:result-contract` block) + the result.json
              instructions + the long-command line + `Write output in <language>.`

After the session:
1. P-RES on the last assistant text (§5.2-1); `out/result.json` (or the guild-result fence)
   validated against the task schema (§5.2-2); DONE's named artifacts must exist (§5.2-3).
2. Invalid → ONE repair on the same session (`--resume <id>`, one-line instruction, no redo);
   resume impossible → one fresh spawn; still invalid → status `INVALID` (caller: ask/pause
   `role-result-invalid`, H§C:361–367 wording) (§5.4).
3. Permission denials (stream `permission_denied` events / `permission_denials`) are journaled
   `{role, command, class}`. `BLOCKED: permission — …` or a denial followed by a non-DONE end →
   ONE `--resume` with the denied command and the allowed list (the list is never widened
   automatically); still blocked → status `PERMISSION` (caller: ask/pause `permission`) (§5.1).
4. Scope check (§5.1) — for a parallel group the caller runs `scope.check` over the union.
5. One cost row per session (`guildcore.cost`), one SessionRL per session (`guildcore.ratelimit`).
A `HALT` (kill switch) observed while waiting kills the group and returns `HALTED` before any
repair or retry (§2.4 valve --now).
"""

import hashlib
import os
import shutil
import uuid

from guildcore import cost as COST
from guildcore import ratelimit as RL
from guildcore.adapters import claude as C
from guildcore.roles import permissions as P
from guildcore.roles import result as R
from guildcore.roles import scope as SC
from guildcore.roles import settings as S

TIMEOUTS_S = {"developer": 3600, "tester": 2700, "qa": 2700, "explorer": 1800, "judge": 600}
BUDGETS_USD = {"developer": 15.0, "explorer": 3.0}
DEFAULT_TIMEOUT_S = 1800
DEFAULT_BUDGET_USD = 6.0
LONG_COMMAND_LINE = ("A command that can run longer than 10 minutes must be given an explicit Bash "
                     "`timeout` argument (milliseconds, at most BASH_MAX_TIMEOUT_MS) — the default "
                     "kills it at 600 seconds.")
RESULT_JSON_LINE = ("Write your machine fields as JSON to `{out}/result.json` (schema below). If you "
                    "cannot write that file, put the same JSON in a fenced block ```guild-result … ``` "
                    "in your final message instead.")
PERMISSION_BRIEF = ("The command `{cmd}` was refused by the permission rules. Allowed commands for "
                    "this task: {allowed}. {engine_does}Do not retry the refused command; finish the "
                    "task with the allowed commands, or return BLOCKED: permission — <command> if "
                    "it truly cannot be done.")
ENGINE_DOES = "That operation (push/merge/PR/Issue edits/comments) is done by the engine — just return your result. "


def result_contract():
    """The canonical `guild:result-contract` block, read from `_handoff.md` (byte-identical)."""
    p = os.path.join(os.path.dirname(__file__), "..", "..", "..", "commands", "atoms", "_handoff.md")
    with open(os.path.abspath(p), encoding="utf-8") as fh:
        text = fh.read()
    a = text.index("<!-- guild:result-contract -->")
    b = text.index("<!-- /guild:result-contract -->") + len("<!-- /guild:result-contract -->")
    return text[a:b]


class RoleSpec(object):
    def __init__(self, role, task, template, issue, stage, step, worktree, model, persona="",
                 inputs=None, base=None, branch=None, attempt=1, timeout_s=None, budget_usd=None,
                 result_schema=None, allowed_status=R.STATUSES, cache="5m", language="en",
                 tier=None, toolchain=(), extra_allow=(), effort=None, agent=None, who=None,
                 unattended=False, kind="score", arm=None, experiment_id=None, scope_check=True,
                 hooks=True, remote_check=True):
        self.role, self.task, self.template = role, task, template
        self.issue, self.stage, self.step = issue, stage, step
        self.worktree, self.model, self.persona = worktree, model, persona
        self.inputs = inputs or {}
        self.base, self.branch, self.attempt = base, branch, attempt
        self.timeout_s = timeout_s or TIMEOUTS_S.get(role, DEFAULT_TIMEOUT_S)
        self.budget_usd = budget_usd if budget_usd is not None else BUDGETS_USD.get(role, DEFAULT_BUDGET_USD)
        self.result_schema = result_schema
        self.allowed_status = allowed_status
        self.cache, self.language, self.tier = cache, language, tier or model
        self.toolchain, self.extra_allow = list(toolchain), list(extra_allow)
        self.effort, self.agent = effort, agent
        self.who = who or ("%s-%s" % (role, task) if task else role)
        self.unattended = unattended
        self.kind, self.arm, self.experiment_id = kind, arm, experiment_id
        self.scope_check, self.hooks = scope_check, hooks
        self.remote_check = remote_check        # Q22 push tripwire (git ls-remote before/after)


class RoleResult(object):
    def __init__(self, status, line=None, extras=None, artifacts=(), session_id=None, cost=0.0,
                 denials=(), violations=(), rl=None, run_dir=None, notes=(), pres=None):
        self.status = status          # DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT | FAIL
        self.line = line              # | INVALID | PERMISSION | TIMEOUT | HALTED | SCOPE
        self.extras = extras or {}
        self.artifacts = list(artifacts)
        self.session_id = session_id
        self.cost = cost
        self.denials = list(denials)
        self.violations = list(violations)
        self.rl = rl
        self.run_dir = run_dir
        self.notes = list(notes)
        self.pres = pres


def repo_hash(worktree):
    return hashlib.sha1(os.path.abspath(S.main_checkout(worktree)).encode()).hexdigest()[:12]


def run_root(worktree, issue, env=None):
    env = os.environ if env is None else env
    tmp = env.get("TMPDIR") or "/tmp"
    return os.path.join(tmp, "guild-engine", repo_hash(worktree), str(issue), "runs")


def new_run_dir(root, stage, who):
    os.makedirs(root, exist_ok=True)
    seq = len([d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]) + 1
    d = os.path.join(root, "%03d-%s-%s" % (seq, stage, who))
    for sub in ("in", "out"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def stage_inputs(run_dir, inputs):
    """inputs = {name: path | {"text": …}} → copies under <run>/in/; returns {name: abs path}."""
    out = {}
    for name, src in (inputs or {}).items():
        dst = os.path.join(run_dir, "in", name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if isinstance(src, dict):
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(src.get("text") or "")
        elif os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copyfile(src, dst)
        out[name] = dst
    return out


def render_task(spec, run_dir, staged, schema_text=None):
    lines = [spec.template.rstrip("\n"), ""]
    if staged:
        lines.append("Inputs (read them; they are files, not pasted):")
        lines += ["- %s: %s" % (k, v) for k, v in sorted(staged.items())]
        lines.append("")
    lines.append(P.summary(spec.role, spec.task, spec.toolchain))
    lines.append("")
    lines.append(LONG_COMMAND_LINE)
    if spec.unattended:
        lines.append("Unattended: narrate in plain ASCII-safe one-line progress notes; no questions to a human.")
    lines.append("")
    if spec.result_schema is not None:
        lines.append(RESULT_JSON_LINE.format(out=os.path.join(run_dir, "out")))
        lines.append("```json\n%s\n```" % (schema_text or _dump(spec.result_schema)))
        lines.append("")
    lines.append(result_contract())
    lines.append("")
    lines.append("Write output in %s." % spec.language)
    return "\n".join(lines) + "\n"


def _dump(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)


def _rule_matches(rule, sub):
    import fnmatch
    import re
    m = re.match(r"^Bash\((.*)\)$", rule)
    if not m:
        return False
    body = m.group(1)
    if body.endswith(":*"):
        p = body[:-2]
        return sub == p or sub.startswith(p + " ")
    if "*" in body:
        return fnmatch.fnmatchcase(sub, body)
    return sub == body


def denial_class(cmd):
    c = " ".join((cmd or "").split())
    if any(_rule_matches(r, c) for r in P.ALWAYS_DENY + P.GH_API_DENY_EXTRA):
        return "forbidden"
    first = c.split(" ", 1)[0] if c else ""
    if first in P.C0_READ_SHELL:
        return "C0"
    if first == "git":
        return "C1" if any(c.startswith(p) for p in P.C1_GIT_READ) else "C3"
    if first == "gh":
        return "C2"
    return "other"


class Runner(object):
    """Holds the adapters: `spawn(argv, env, cwd, stdin, stream_path, stderr_path, timeout_s,
    on_start, halt_check) -> ProcResult` (default: adapters.claude.run_process) and the journal."""

    def __init__(self, journal=None, common_dir=None, parent_env=None, allow_local=False,
                 allowed_endpoints=(), spawn=None, halt_check=None, user_settings=None,
                 claude=None, run_root_dir=None, version=None):
        self.journal = journal
        self.common_dir = common_dir
        self.parent_env = dict(os.environ if parent_env is None else parent_env)
        self.allow_local = allow_local
        self.allowed_endpoints = list(allowed_endpoints)
        self.spawn = spawn or C.run_process
        self.halt_check = halt_check
        self.user_settings = user_settings
        self.claude = claude or C.claude_binary(self.parent_env)
        self.run_root_dir = run_root_dir
        self.version = version

    # -- one session ----------------------------------------------------------------------
    def _session(self, spec, run_dir, rendered, env, stdin_text, tag, resume=None, session_id=None):
        allow = rendered.settings["permissions"]["allow"]
        deny = rendered.settings["permissions"]["deny"]
        argv = C.role_argv(spec.model, spec.persona, allow, deny, run_dir, rendered.path,
                           session_id=session_id, resume=resume, effort=spec.effort,
                           agent=spec.agent, budget_usd=spec.budget_usd, claude=self.claude)
        stream_p = os.path.join(run_dir, "%s.stream.jsonl" % tag)

        def on_start(rec):
            if self.journal is not None:
                self.journal.record_pid(spec.who, rec["pid"], rec["pgid"], rec["start_time"],
                                        session_id=resume or session_id)
        proc = self.spawn(argv, env, spec.worktree, stdin_text, stream_p, stream_p + ".stderr",
                          spec.timeout_s, on_start, self.halt_check)
        st = C.read_stream(stream_p)
        return proc, st

    def _cost(self, spec, st, endpoint, persona_chars, brief_chars):
        row = COST.from_result(st.result, issue=spec.issue, stage=spec.stage, step=spec.step,
                               who=spec.who, model=spec.model, tier=spec.tier, local=False,
                               attempt=spec.attempt, arm=spec.arm, experiment_id=spec.experiment_id,
                               kind=spec.kind, persona_chars=persona_chars, brief_chars=brief_chars,
                               endpoint=endpoint, version=self.version)
        if self.common_dir:
            COST.record(self.common_dir, row)
        return row

    def _denials(self, spec, st):
        out = []
        for d in st.denial_records():
            cls = denial_class(d.get("command")) if d.get("tool") == "Bash" else "tool:%s" % d.get("tool")
            rec = {"role": spec.who, "command": d.get("command") or d.get("tool"), "class": cls,
                   "reason_type": d.get("reason_type")}
            out.append(rec)
            if self.journal is not None:
                self.journal.record_denial(spec.who, rec["command"], cls, d.get("reason_type"))
        return out

    # -- the contract -------------------------------------------------------------------------
    def run_role(self, spec):
        root = self.run_root_dir or run_root(spec.worktree, spec.issue, self.parent_env)
        run_dir = new_run_dir(root, spec.stage, spec.who)
        staged = stage_inputs(run_dir, spec.inputs)
        rendered = S.render(spec.role, spec.task, worktree=spec.worktree, base=spec.base,
                            run_dir=run_dir, issue=spec.issue, toolchain=spec.toolchain,
                            extra_allow=spec.extra_allow, user_settings=self.user_settings,
                            hooks=spec.hooks, env=self.parent_env)
        endpoint = C.endpoint_guard(self.parent_env, rendered.env, self.allow_local,
                                    self.allowed_endpoints)
        env = C.child_env(self.parent_env, rendered.env, cache=spec.cache)
        task = render_task(spec, run_dir, staged)
        with open(os.path.join(run_dir, "in", "task.md"), "w", encoding="utf-8") as fh:
            fh.write(task)
        before = SC.snapshot(spec.worktree, remote=spec.remote_check) if spec.scope_check else None
        sid = str(uuid.uuid4())
        notes, denials, costs, rls = [], [], 0.0, []
        proc, st = self._session(spec, run_dir, rendered, env, task, "s1", session_id=sid)
        sid = st.session_id or sid

        def account(st_):
            row = self._cost(spec, st_, endpoint, len(spec.persona or ""), len(task))
            rls.append(RL.observe(st_))
            denials.extend(self._denials(spec, st_))
            return row["total_cost_usd"]
        costs += account(st)

        def finish(status, line=None, extras=None, pres=None, violations=()):
            return RoleResult(status, line, extras, session_id=sid, cost=costs, denials=denials,
                              violations=violations, rl=RL.verdict(rls), run_dir=run_dir,
                              notes=notes, pres=pres)
        if proc.killed_by == "halt":
            return finish("HALTED", "halted at the kill switch")
        if RL.verdict(rls).rejected():
            return finish("RATE_LIMITED", "rate limit")
        if proc.timed_out:
            return finish("TIMEOUT", "%s exceeded %d s" % (spec.who, spec.timeout_s))
        pres, obj, errs = self._judge_reply(spec, run_dir, st)
        # §5.1 permission: BLOCKED: permission — … or a denial followed by a non-DONE end
        perm_blocked = pres.ok and pres.status == "BLOCKED" and (pres.text or "").startswith("permission")
        if (perm_blocked or (denials and not (pres.ok and pres.status.startswith("DONE")))):
            cmd = (denials[-1]["command"] if denials else (pres.text or "").split("—", 1)[-1].strip())
            forb = denials and denials[-1]["class"] == "forbidden"
            brief = PERMISSION_BRIEF.format(cmd=cmd, allowed=P.summary(spec.role, spec.task, spec.toolchain),
                                            engine_does=ENGINE_DOES if forb else "")
            notes.append("permission-resume")
            proc, st = self._session(spec, run_dir, rendered, env, brief, "s2-permission", resume=sid)
            costs += account(st)
            if proc.killed_by == "halt":
                return finish("HALTED", "halted at the kill switch")
            pres, obj, errs = self._judge_reply(spec, run_dir, st)
            if pres.ok and pres.status == "BLOCKED" and (pres.text or "").startswith("permission"):
                return finish("PERMISSION", pres.line, pres=pres)
        # §5.4 format repair: same session once, else a fresh spawn once
        if not pres.ok or errs:
            notes.append("repair-resume")
            instr = R.repair_instruction(pres, errs)
            proc, st = self._session(spec, run_dir, rendered, env, instr, "s3-repair", resume=sid)
            costs += account(st)
            if proc.killed_by == "halt":
                return finish("HALTED", "halted at the kill switch")
            if proc.rc != 0 and not st.result:
                notes.append("repair-fresh")
                sid = str(uuid.uuid4())
                proc, st = self._session(spec, run_dir, rendered, env, task + "\n" + instr,
                                         "s4-fresh", session_id=sid)
                costs += account(st)
            pres, obj, errs = self._judge_reply(spec, run_dir, st)
            if not pres.ok or errs:
                return finish("INVALID", "%s returned no valid RESULT line" % spec.role, pres=pres,
                              extras={"errors": errs})
        violations = []
        if spec.scope_check:
            after = SC.snapshot(spec.worktree, remote=spec.remote_check)
            violations = SC.check(spec.worktree, before, after, [P.role_key(spec.role, spec.task)],
                                  issue=spec.issue, branch=spec.branch)
            if violations:
                return finish("SCOPE", SC.render_pause_line(spec.role, violations), obj, pres,
                              violations)
        return finish(pres.status, pres.line, obj, pres)

    def _judge_reply(self, spec, run_dir, st):
        pres = R.parse_pres(st.last_text, spec.allowed_status)
        obj, errs = None, []
        if spec.result_schema is not None and pres.ok:
            obj, _src, err = R.read_result_json(run_dir, st.last_text)
            errs = [err] if err else R.validate(obj, spec.result_schema, pres.status)
            if not errs and pres.status.startswith("DONE"):
                miss = R.missing_artifacts(obj, spec.worktree, run_dir)
                errs = ["artifact missing: %s" % m for m in miss]
        return pres, obj, errs
