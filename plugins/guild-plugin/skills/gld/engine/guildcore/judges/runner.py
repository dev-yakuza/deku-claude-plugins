"""guildcore.judges.runner — `judge(JudgeSpec) -> Decision`, the §3.1 judgment call.

    cwd   <run>/in (no tools) | the repo (Read/Grep groups: TEST, EX-ARB, INTEGRATE)
    env   §5.1 contract + CLAUDE_CODE_DISABLE_CLAUDE_MDS/AUTO_MEMORY;
          DISABLE_PROMPT_CACHING=1 (single-shot, no tools) | FORCE_PROMPT_CACHING_5M=1 (tools)
    argv  claude -p --model <tier> --output-format json --json-schema '<inline>' --system-prompt …
          --tools "" --strict-mcp-config --disable-slash-commands --setting-sources ""
          --settings <rendered: tool group's Read/Grep allow only, no hooks>
          --no-session-persistence --max-budget-usd <n>   < brief (stdin)

Then, in order: re-validate `structured_output` against the schema (the CLI's check is not
trusted); a violation → ONE re-call naming it → still invalid → one rung up (haiku → sonnet →
opus) → still invalid → `JudgeFailed` (the caller's ladder). `unsure` (every verdict enum has it,
JR-M1) → the group's documented conservative default, `unsure=True` recorded. Coercions
(`coerce(fields) -> (fields, coerced_by|None)`) run last; `raw_choice` keeps the judge's own.
`needs_more: [path]` → the engine adds those files to the brief and re-calls ONCE.
Cache: key = (point, inputs, tier, sha(system + schema), valve snapshot, plugin) (§2.5 rule 4) in
the journal — the same brief and the same judgment configuration give the same decision.
Brief cap: ordinary parts keep head + tail with an elision mark; a `no_elide` part that does not
fit raises `BriefTooLarge` (caller: tool mode, else pause `defect: brief too large for <group>`).
"""

import hashlib
import json
import os
import uuid

from guildcore import cost as COST
from guildcore import journal as J
from guildcore import ratelimit as RL
from guildcore import schema as SCH
from guildcore.adapters import claude as C
from guildcore.roles import settings as S

TIER_LADDER = ("haiku", "sonnet", "opus")
ESCALATION_LADDER = ("code", "MJ", "SJ", "L0", "human")
BRIEF_CAPS = {"L0": 40000, "SJ": 25000, "MJ": 6000, "MJ+": 12000}
ELISION = "\n…[elided %d chars]…\n"


class BriefTooLarge(Exception):
    pass


class RateLimited(Exception):
    """A judge session ended rate-limited: no retry, no tier-up — the engine stops with 75."""

    def __init__(self, verdict):
        Exception.__init__(self, "judge rate-limited")
        self.verdict = verdict


class Halted(Exception):
    pass


class JudgeFailed(Exception):
    def __init__(self, group, why):
        Exception.__init__(self, "judge %s failed: %s" % (group, why))
        self.group = group
        self.why = why


class JudgeSpec(object):
    def __init__(self, group, model, schema, system_parts, brief_parts, point=None, tools="",
                 no_elide=(), choice_key="choice", unsure_default=None, coercions=(),
                 allowed_escalations=(), budget_usd=0.5, cap_chars=25000, needs_more_fn=None,
                 cwd=None, issue=None, stage=None, step=None, kind="score", effort=None,
                 valves=None, plugin=None, arm=None, experiment_id=None):
        SCH.check_schema(schema)
        self.group, self.model, self.schema = group, model, schema
        self.system_parts, self.brief_parts = list(system_parts), list(brief_parts)
        self.point = point or group
        self.tools = tools
        self.no_elide = set(no_elide)
        self.choice_key = choice_key
        self.unsure_default = unsure_default
        self.coercions = list(coercions)
        self.allowed_escalations = list(allowed_escalations)
        self.budget_usd, self.cap_chars = budget_usd, cap_chars
        self.needs_more_fn = needs_more_fn
        self.cwd = cwd
        self.issue, self.stage, self.step, self.kind = issue, stage, step, kind
        self.effort = effort
        self.valves, self.plugin = valves or {}, plugin
        self.arm, self.experiment_id = arm, experiment_id


class Decision(object):
    def __init__(self, choice, fields, by, digest, unsure=False, coerced=False, coerced_by=None,
                 raw_choice=None, cost=0.0, cached=False, model=None):
        self.choice, self.fields, self.by, self.digest = choice, fields, by, digest
        self.unsure, self.coerced, self.coerced_by = unsure, coerced, coerced_by
        self.raw_choice, self.cost, self.cached, self.model = raw_choice, cost, cached, model

    def as_dict(self):
        return {"choice": self.choice, "fields": self.fields, "by": self.by, "digest": self.digest,
                "unsure": self.unsure, "coerced": self.coerced, "coerced_by": self.coerced_by,
                "raw_choice": self.raw_choice, "model": self.model}

    @classmethod
    def from_dict(cls, d):
        return cls(d["choice"], d["fields"], d["by"], d["digest"], d.get("unsure", False),
                   d.get("coerced", False), d.get("coerced_by"), d.get("raw_choice"), 0.0, True,
                   d.get("model"))


def assemble(parts, cap, no_elide=()):
    """parts = [(name, text)] → brief text within `cap` chars."""
    texts = [(n, t or "") for n, t in parts]
    total = sum(len(t) for _, t in texts) + 2 * len(texts)
    if total <= cap:
        return "\n\n".join(t for _, t in texts)
    fixed = sum(len(t) for n, t in texts if n in no_elide)
    if fixed > cap:
        raise BriefTooLarge("no-elide parts alone are %d chars (cap %d)" % (fixed, cap))
    elidable = [(n, t) for n, t in texts if n not in no_elide]
    budget = cap - fixed - 2 * len(texts) - len(ELISION % 10 ** 9) * len(elidable)
    share = max(200, budget // max(1, len(elidable)))
    out = []
    for n, t in texts:
        if n in no_elide or len(t) <= share:
            out.append(t)
        else:
            h = share // 2
            out.append(t[:h] + (ELISION % (len(t) - 2 * h)) + t[-h:])
    return "\n\n".join(out)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tier_up(model):
    for i, t in enumerate(TIER_LADDER):
        if t in model:
            return TIER_LADDER[min(i + 1, len(TIER_LADDER) - 1)]
    return "opus"


def _get(fields, dotted):
    cur = fields
    for p in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _set(fields, dotted, value):
    parts = dotted.split(".")
    cur = fields
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


class JudgeRunner(object):
    def __init__(self, journal=None, common_dir=None, parent_env=None, allow_local=False,
                 allowed_endpoints=(), spawn=None, run_root_dir=None, user_settings=None,
                 claude=None, version=None, halt_check=None):
        self.halt_check = halt_check
        self.journal = journal
        self.common_dir = common_dir
        self.parent_env = dict(os.environ if parent_env is None else parent_env)
        self.allow_local, self.allowed_endpoints = allow_local, list(allowed_endpoints)
        self.spawn = spawn or C.run_process
        self.run_root_dir = run_root_dir
        self.user_settings = user_settings
        self.claude = claude or C.claude_binary(self.parent_env)
        self.version = version

    def _run_dir(self, spec):
        root = self.run_root_dir or os.path.join(self.parent_env.get("TMPDIR") or "/tmp",
                                                 "guild-engine", "judges")
        d = os.path.join(root, "%s-%s" % (spec.group, uuid.uuid4().hex[:8]))
        for sub in ("in", "out"):
            os.makedirs(os.path.join(d, sub), exist_ok=True)
        return d

    def _call(self, spec, model, system, brief, run_dir, tag, attempt=1):
        allow = ["Read", "Grep", "Glob"] if spec.tools else []
        settings = {"permissions": {"allow": allow, "deny": []}}
        rendered = S.render("judge", None, run_dir=None, user_settings=self.user_settings,
                            hooks=False, env=self.parent_env)
        settings["permissions"]["deny"] = rendered.settings["permissions"]["deny"]
        if "sandbox" in rendered.settings:
            settings["sandbox"] = rendered.settings["sandbox"]
        sp = os.path.join(run_dir, "in", "settings.json")
        with open(sp, "w", encoding="utf-8") as fh:  # fs-ok: engine-owned judge run dir (no role runs there)
            json.dump(settings, fh, indent=1, sort_keys=True)
        endpoint = C.endpoint_guard(self.parent_env, rendered.env, self.allow_local,
                                    self.allowed_endpoints)
        env = C.child_env(self.parent_env, rendered.env, cache="5m" if spec.tools else "off",
                          judge=True)
        argv = C.judge_argv(model, system, spec.schema, sp, tools=spec.tools,
                            budget_usd=spec.budget_usd, effort=spec.effort, claude=self.claude)
        with open(os.path.join(run_dir, "in", "%s.brief.md" % tag), "w", encoding="utf-8") as fh:
            fh.write(brief)
        out = os.path.join(run_dir, "out", "%s.json" % tag)
        cwd = spec.cwd if spec.tools and spec.cwd else os.path.join(run_dir, "in")

        def on_start(rec):
            if self.journal is not None:
                self.journal.record_pid("J:%s" % spec.group, rec["pid"], rec["pgid"], rec["start_time"])
        proc = self.spawn(argv, env, cwd, brief, out, out + ".stderr", 600, on_start, self.halt_check)
        st = C.read_stream(out)
        row = COST.from_result(st.result, issue=spec.issue, stage=spec.stage, step=spec.step,
                               who="J:%s" % spec.group, model=model, tier=model, local=False,
                               attempt=attempt, kind=spec.kind, stream=st, session_kind=tag, persona_chars=len(system),
                               brief_chars=len(brief), endpoint=endpoint, version=self.version,
                               arm=spec.arm, experiment_id=spec.experiment_id)
        if self.common_dir:
            COST.record(self.common_dir, row)
        return proc, st, row["total_cost_usd"]

    def judge(self, spec):
        system = "\n\n".join(spec.system_parts)
        brief = assemble(spec.brief_parts, spec.cap_chars, spec.no_elide)
        sys_sha = _sha(system + json.dumps(spec.schema, sort_keys=True))
        key = J.cache_key(spec.point, _sha(brief), spec.model, sys_sha, spec.valves, spec.plugin)
        if self.journal is not None:
            hit = self.journal.cache_get(spec.point, key)
            if hit:
                return Decision.from_dict(hit)
        run_dir = self._run_dir(spec)
        model, cost, used_more = spec.model, 0.0, False
        attempt, calls, fields, errs = 0, 0, None, None
        while True:
            attempt += 1
            calls += 1
            b = brief if not errs else brief + "\n\nYour previous output violated the schema: %s. " \
                "Return output that satisfies it." % "; ".join(errs[:5])
            proc, st, c = self._call(spec, model, system, b, run_dir, "call%d" % calls, attempt)
            cost += c
            if getattr(proc, "killed_by", None) == "halt":
                raise Halted("judge %s halted" % spec.group)
            v = RL.verdict([RL.observe(st)])
            if v.rejected():                     # K1-B6: never a "schema violation"
                raise RateLimited(v)
            fields = st.structured
            if fields is None and isinstance(st.last_text, str):
                try:
                    fields = json.loads(st.last_text)
                except ValueError:
                    fields = None
            errs = ["no structured output"] if fields is None else SCH.errors(fields, spec.schema)
            if not errs and fields.get("needs_more") and spec.needs_more_fn and not used_more:
                used_more = True
                brief = brief + "\n\n" + spec.needs_more_fn(fields["needs_more"])
                errs = None
                attempt -= 1                     # K1-m10: needs_more does not use up an attempt
                continue
            if not errs:
                break
            if attempt == 2:
                model = tier_up(model)          # violated twice → one rung up
            elif attempt >= 3:
                raise JudgeFailed(spec.group, "; ".join(errs[:3]))
        raw = _get(fields, spec.choice_key)
        unsure = raw == "unsure" or bool(fields.get("unsure") is True)
        choice = raw
        if raw == "unsure" and spec.unsure_default is not None:
            choice = spec.unsure_default
            _set(fields, spec.choice_key, choice)
        coerced_by = None
        for co in spec.coercions:
            fields, by = co(fields)
            if by:
                coerced_by = coerced_by or by
        final = _get(fields, spec.choice_key)
        coerced = coerced_by is not None and final != raw
        d = Decision(final, fields, "judge:%s" % model, key[:12], unsure, coerced or coerced_by is not None,
                     coerced_by, raw if (coerced or unsure) else None, cost, False, model)
        if self.journal is not None:
            self.journal.cache_put(spec.point, key, d.as_dict())
            self.journal.append("mj", point=spec.point, group=spec.group, choice=final,
                                unsure=unsure, coerced_by=coerced_by, model=model)
        return d


def escalate(level):
    """The next rung of the §4.1 ladder (code → MJ → SJ → L0 → human)."""
    i = ESCALATION_LADDER.index(level)
    return ESCALATION_LADDER[min(i + 1, len(ESCALATION_LADDER) - 1)]
