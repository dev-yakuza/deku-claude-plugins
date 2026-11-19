"""workflows.dev.stages.base — what every stage shares: ports, results, entry, pause, FAIL (C-F-6).

A stage is code over injected PORTS (design §2.0 — fakes in tests and the procedure replay):

    gh        reads   issue · comments · timeline · pr · pr_search · check_runs · annotations ·
                      issue_search
    writer    guildcore.records.write.GhWriter (every GitHub write, verified by re-read)
    decisions guildcore.decisions.DecisionWriter (the decision log)
    run_role  RoleCall -> guildcore.roles.runner.RoleResult (the role runner; the engine hands the
              role its Issue/PR/comment content as `in/` files — roles never touch GitHub, Q23)
    judge     guildcore.judges.runner.JudgeSpec -> Decision
    suite     (cmd, owner_role, timeout_s) -> guildcore.checks.CheckResult — the engine runs the
              suite itself (§2.8) under the owning role's sandbox (K1r3-B1 contract)
    check     (cmd, cwd, owner_role, timeout_s, write_dirs) -> CheckResult (TEST `effective`)
    capture   (kind, stage, role, summary, evidence, area, surprise) -> row|None (ground truth —
              captured AT the decision, C-F-22; `--mark` is kept for 0.101.x `--count`)
    mark      (stage) -> ISO stamp
Return tokens (C §1.3) are rendered by `StageResult.token()` — the supervisor judges by labels,
the tokens are for the human report and logs.
"""

import hashlib
import os

from guildcore import ask as ASK
from guildcore import pause as PAUSE
from guildcore import state as ST
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import Halted, RateLimited
from guildcore.records import markers

NEEDS_HUMAN = "guild:needs-human"


class StageError(Exception):
    """A defect in the engine's own stage code path (caller: FAIL defect)."""


class RoleCall(object):
    """What a stage asks of a role. The real port builds a guildcore.roles.runner.RoleSpec."""

    def __init__(self, role, task, stage, step, inputs=None, addendum=None, schema_role=None,
                 allowed_status=None, attempt=1, schema=None, model=None, pre_check=None, replay_salt=None):
        self.role, self.task, self.stage, self.step = role, task, stage, step
        self.inputs = inputs or {}
        self.addendum = addendum
        self.schema_role = schema_role or role
        self.allowed_status = allowed_status
        self.attempt = attempt
        self.schema = schema              # a task-narrowed result.json schema (else the §5.2 role's)
        self.model = model                # a tier override (execute attempt 2: +1 rung, MT §A)
        self.pre_check = pre_check        # K3: runs before the scope check (refactor net cleanup)
        # K5r8-m2: state the role reads that is not in `inputs` (qa: a callable → the checkout's HEAD) — part of the
        # conservative replay signature only (a push between a question and its answer runs the role live)
        self.replay_salt = replay_salt


class StageResult(object):
    ADVANCE, DONE, LOOPBACK, PAUSE, ASK, FAIL = "ADVANCE", "DONE", "LOOPBACK", "PAUSE", "ASK", "FAIL"
    SPLIT = "SPLIT"                   # K4 design: `OK SPLIT: <N> children` (nxt = N)
    # K5r1-M2: a run stopped on purpose at a step boundary (attended `hold`, a budget `stop`, a busy child) —
    # never DONE: a parent driving children stops there and never goes on to the next child or integration
    HOLD = "HOLD"

    def __init__(self, kind, nxt=None, cause=None, line=None, qid=None, fail_class=None, notes=()):
        self.kind = kind
        self.nxt = nxt
        self.cause = cause            # PAUSE: the text after `needs-human — `
        self.line = line              # ASK: the NEEDS_HUMAN line; FAIL: the reason
        self.qid = qid
        self.fail_class = fail_class  # prevalidate | prevalidate_env | gh_auth | transient | defect
        self.notes = list(notes)
        self.retry_at = None          # K5r1 decision 2: an unattended unknown-create pause the supervisor retries (epoch)

    def token(self):
        if self.kind == self.ADVANCE:
            return "OK ADVANCE: %s" % self.nxt
        if self.kind == self.DONE:
            return "OK DONE: %s" % self.line if self.line else "OK DONE"
        if self.kind == self.SPLIT:
            return "OK SPLIT: %s children" % self.nxt
        if self.kind == self.LOOPBACK:
            return "OK LOOPBACK: execute"
        if self.kind == self.HOLD:
            return "OK HOLD: %s" % (self.line or "held")
        if self.kind == self.PAUSE:
            return "OK PAUSE: needs-human — %s" % self.cause
        if self.kind == self.ASK:
            return "NEEDS_HUMAN: %s" % self.line
        if self.fail_class == "needs_context":
            return "NEEDS_CONTEXT: %s" % self.line
        return "FAIL: %s" % self.line

    def __repr__(self):
        return "<StageResult %s>" % self.token()


class Ports(object):
    def __init__(self, issue, gh, writer, decisions, clock, config, root, unattended=True,
                 run_role=None, judge=None, suite=None, check=None, capture=None, mark=None,
                 journal=None, events=None, push=None, host=None, plugin=None, branch=None,
                 base=None, impl_files=None, git_dir=None):
        self.issue = int(issue)
        self.gh, self.writer, self.decisions, self.clock = gh, writer, decisions, clock
        self.config = config
        self.root = root
        self.unattended = unattended
        self.run_role = run_role
        self.judge = judge
        self.suite, self.check = suite, check
        self.capture = capture or (lambda *a, **k: None)
        self.mark = mark or (lambda stage: None)
        self.journal, self.events = journal, events
        self.push = push                  # () -> None: the engine's push (qa committed tests)
        self.host = host                  # "macOS arm64" etc. (VIS-ENV pre-filter)
        self.plugin = plugin
        self.branch, self.base = branch, base
        self.impl_files = impl_files      # developer result.json `impl_files` (execute's ctx)
        self.git_dir = git_dir
        self.valves = {}                  # K5: the soft valves in force (guildcore.valves.effective), read at run start
        self.directives = []              # K5: attended `dev note` texts of this Issue (by: human, point: directive)
        # the procedure replay's injection list (§10.2-2): legacy values that are not the
        # engine's to decide (loop-back reason/signature …). Empty in every live run.
        self.inject = {}
        self.warm = None                  # (base, tree) → CheckResult|None: the engine warm-up, in place on pristine <base>
        self.suite_warm = None            # the last suite run's warm-up status (K2r5-m3)
        self.suite_warm_detail = None     # its proxy summary + redacted output tail (K2r7-m1)

    # -- judging (K5r5-M3: every L0/SJ decision passes the §9.5 conservative path) -----------------------------
    @property
    def judge(self):
        raw = self.__dict__.get("_judge_raw")
        if raw is None:
            return None

        def judged(spec):
            from workflows.dev import conservative as CONS
            return CONS.gate(self, spec, raw)
        judged.raw = raw
        return judged

    @judge.setter
    def judge(self, fn):
        self.__dict__["_judge_raw"] = getattr(fn, "raw", fn)

    @property
    def run_role(self):
        """K5r6-M1: role calls pass the conservative path's tape (replayed, not re-run, after an answer)."""
        raw = self.__dict__.get("_run_role_raw")
        if raw is None:
            return None

        def ran(call):
            from workflows.dev import conservative as CONS
            return CONS.role(self, call, raw)
        ran.raw = raw
        return ran

    @run_role.setter
    def run_role(self, fn):
        self.__dict__["_run_role_raw"] = getattr(fn, "raw", fn)

    # -- config ---------------------------------------------------------------------------
    def cfg(self, dotted, default=None):
        c = self.config
        if c is None:
            return default
        if hasattr(c, "get") and not isinstance(c, dict):
            return c.get(dotted, default)
        cur = c
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    @property
    def language(self):
        return self.cfg("language", "en") or "en"

    def engine_cfg(self, key, default=None):
        from guildcore import valves as VALVES
        over = VALVES.engine_overlay(getattr(self, "valves", None))
        if key in over:                   # §10.5: a valve beats the committed config
            return over[key]
        eng = getattr(self.config, "engine", None)
        if isinstance(eng, dict) and key in eng:
            return eng[key]
        return self.cfg("engine." + key, default)

    # -- repo files -----------------------------------------------------------------------
    def read_file(self, rel):
        try:
            with open(os.path.join(self.root, rel), encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except (IOError, OSError, TypeError):
            return None

    def exists(self, rel):
        return bool(self.root) and os.path.exists(os.path.join(self.root, rel))

    def now(self):
        return self.clock.now()


class Entry(object):
    def __init__(self, labels, state, found_stage, recheck=False, stage=None):
        self.stage = stage
        self.labels = labels          # every label name at Step 0 (FOUND_LABELS ∪ others)
        self.state = state            # guildcore.state.IssueState
        self.found_stage = found_stage  # the stage label Step 0 found (None when it was empty)
        self.recheck = recheck        # `--only test` on `done` (C12)

    @property
    def paused(self):
        return NEEDS_HUMAN in self.labels


# ---- entry (T0.1–T0.7 / Q0.1–Q0.7) ------------------------------------------------------------

# §2.2 environment-level halts (exit 6, `halted: env <reason>` → supervisor `halted:engine-env-<reason>`):
# the closed set. `ignored-missing` (K2r5-B1): tracked tests need git-ignored files the engine's temp
# tree does not have and `engine.effective.copy_ignored` does not list — no code change can fix it.
# `build-inputs-changed` (K2r6-B1): the change touched build inputs the engine cannot prepare
# offline (own `hook/`, path/git/override deps, a test config), or the offline suite failed on
# dependency resolution/download — a person runs it; never a loop-back or stagnation.
ENV_HALT_REASONS = ("endpoint", "python", "uninitialized", "plugin-not-listed", "ignored-missing",
                    "build-inputs-changed")


def env_halt(reason, line, detail=""):
    assert reason in ENV_HALT_REASONS, reason
    return StageResult(StageResult.FAIL, line=line, fail_class="prevalidate_env",
                       notes=["halted: env %s%s" % (reason, (" — " + detail) if detail else "")])


def ignored_missing(paths, where):
    """The `ignored-missing` halt with the missing paths and the config hint."""
    lst = ", ".join(paths[:6]) + (" …" if len(paths) > 6 else "")
    hint = "list them in .claude/guild/config.json `engine.effective.copy_ignored` (explicit relative paths)"
    return env_halt("ignored-missing", "%s: the tests need git-ignored files the engine's temp tree does not have "
                    "(%s) — %s" % (where, lst, hint), "%s; %s" % (lst, hint))


def build_inputs_changed(files, where, warm=None, warm_detail=None):
    lst = ", ".join(files[:6]) + (" …" if len(files) > 6 else "")
    extra = "".join(" [%s]" % x for x in (warm, warm_detail) if x)          # K2r7-m1: why, on record
    return env_halt("build-inputs-changed", "%s: the change's build inputs cannot be prepared offline by the "
                    "engine (%s) — run the suite by hand (dependency step + tests) and continue%s"
                    % (where, lst, extra), lst + extra)


def enter(p, stage, config_present=True, only=None):
    """Preflight → Issue validation → label read → `--mark` → split-parent guard → stage
    precondition (C-F-1) → entry label. Returns Entry or a FAIL StageResult (no label written)."""
    if not config_present:
        return env_halt("uninitialized", "Guild not initialized (run /gld init)")
    issue = p.gh.issue(p.issue)
    if "/pull/" in (issue.get("url") or ""):
        return StageResult(StageResult.FAIL, line="#%d is a pull request, not an Issue" % p.issue,
                           fail_class="prevalidate")
    labels = ST.label_names(issue.get("labels"))
    state = ST.derive(labels)
    if state.sprint:
        return StageResult(StageResult.FAIL, fail_class="prevalidate",
                           line="#%d is a sprint tracking Issue — use /gld sprint daily" % p.issue)
    p.mark(stage)                                    # after init + validation (T0.5)
    if "guild:children" in labels:
        return StageResult(StageResult.FAIL, fail_class="prevalidate", line=(
            "#%d is a split parent (guild:children) — its work is its children's, not its own. "
            "Run `/gld dev %d` (or `/gld resume %d`) to drive the children." % (p.issue, p.issue, p.issue)))
    found = state.stage if state.stage != "none" else None
    recheck = False
    if found not in (None, stage):
        if stage == "test" and found == "done" and only == "test":
            recheck = True                           # C12 — a re-verification only
        else:
            return StageResult(StageResult.FAIL, fail_class="prevalidate", line=(
                "#%d is at guild:%s — /gld %s runs only at guild:%s (use /gld rollback stage to "
                "move back)" % (p.issue, found, stage, stage)))
    if found is None:
        p.writer.labels_apply(p.issue, add=["guild:" + stage])
    return Entry(labels, state, found, recheck, stage)


def transition(p, entry, to, extra_add=()):
    """Remove the stage label Step 0 found (never guild:child), add `to`, and remove
    guild:needs-human only when Step 0 saw it (H§A). Verified by GhWriter."""
    remove = ["guild:" + (entry.found_stage or entry.stage)]
    if entry.paused:
        remove.append(NEEDS_HUMAN)
    p.writer.labels_apply(p.issue, add=["guild:" + to] + list(extra_add), remove=remove)


# ---- records (K2-M5) ----------------------------------------------------------------------------

def records(p, issue=None):
    """The comments records may come from: engine-written or by write-access authors."""
    own = p.journal.own_comment_ids() if p.journal is not None else ()
    return markers.trusted(p.gh.comments(issue or p.issue), own)


def note_untrusted(p, stage):
    """Each marker-carrying comment by a non-member is ignored as a record — noted once."""
    own = p.journal.own_comment_ids() if p.journal is not None else ()
    raw = p.gh.comments(p.issue)
    bad = markers.untrusted_markers(raw, own)
    if not bad:
        return []
    noted = set(b.get("refs") for b in DecisionLog.load(markers.trusted(raw, own)).blocks
                if b.get("point") == "ignored_marker_comment")
    for c in bad:
        if str(c.get("id")) not in noted:
            record_code(p, stage, "ignored_marker_comment", "ignored", refs=str(c.get("id")),
                        reason="marker comment by %s (%s) is not a record" % (
                            (c.get("user") or {}).get("login"), c.get("author_association")))
    return bad


# ---- decisions ------------------------------------------------------------------------------

def digest(*parts):
    h = hashlib.sha256()
    for x in parts:
        h.update((x if isinstance(x, str) else repr(x)).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:12]


def record_judgment(p, stage, point, refs, dec, choice=None, reason=None, extra=None):
    """One decision-log block per SJ decision (§2.5 — every L0/SJ decision is logged; §9.5 grades
    from these fields). Returns D<n>."""
    f = {"point": point, "refs": refs, "stage": stage, "by": dec.by, "inputs": dec.digest[:12],
         "choice": choice if choice is not None else dec.choice,
         "unsure": "true" if dec.unsure else "false",
         "coerced": "true" if dec.coerced else "false"}
    if dec.coerced:
        f["coerced_by"] = dec.coerced_by or "rule"
        f["raw_choice"] = dec.raw_choice
    if reason:
        f["reason"] = reason
    f.update(extra or {})
    return p.decisions.record(f)


def record_code(p, stage, point, choice, reason=None, refs=None, extra=None):
    f = {"point": point, "stage": stage, "by": "code", "choice": choice, "refs": refs}
    if reason:
        f["reason"] = reason
    f.update(extra or {})
    return p.decisions.record(f)


def pending_answer(p, stage, kind, comments=None):
    """A human answer to this stage's `kind` question that has not been applied yet:
    (pending_block, resolution_block) or (None, None). Applied = a later `point: applied`
    block whose `refs` names the resolution (durable, survives a lost journal)."""
    log = DecisionLog.load(comments if comments is not None else records(p))
    applied = set(b.get("refs") for b in log.blocks if b.get("point") == "applied")
    for blk in reversed(log.blocks):
        if blk.get("kind") != kind or blk.get("stage") != stage or blk.get("status") != "pending-human":
            continue
        res = [b for b in log.blocks if b.get("resolves") == blk.id and b.get("by") == "human"
               and b.get("choice")]
        if res and res[-1].id not in applied:
            return blk, res[-1]
        return None, None
    return None, None


def mark_applied(p, stage, resolution):
    return record_code(p, stage, "applied", resolution.get("choice"), refs=resolution.id)


# ---- pause / ask / FAIL ---------------------------------------------------------------------

def pause(p, stage, cause_kind, line, token_cause, prose="", env_key=None, question=None,
          directive_line=None, extra_labels=(), remove_labels=()):
    """Unattended pause (guildcore.pause order: decision block → needs-human comment → label).
    `extra_labels`/`remove_labels` ride in the SAME label write (test's pending regeneration
    moves guild:test → guild:execute together with guild:needs-human)."""
    token = None
    if question is not None:
        # K6 predict-first (§2.6, R5J-M4): forced on → the pending block carries `recommended_sha` only, the nonce
        # journaled first; the pause comment never names the recommendation. K5r3-M1: the one enforcement point
        # also checks every text that goes out with the question (refused → not a blind answer)
        from workflows.dev import predict as PF
        PF.apply(p, question, stage, texts=(line, prose, directive_line, token_cause))
        if question.neutralized:
            # K5r5-M1: a blind pause shows only engine text — the neutral wording, the cause kind, the option list;
            # the judge's line / prose are withheld (journaled with the nonce, revealed with the recommendation)
            line = question.text
            token_cause = "%s: %s" % (cause_kind, question.text)
            prose, directive_line = PF.enumeration(question), None
        token = ASK.journal_nonce(p.journal, question)
    pz = PAUSE.Pause(cause_kind, line, prose, env_key, directive_line)
    if extra_labels or remove_labels:
        did = None
        from guildcore.records import needs_human
        cause = needs_human.cause_line(cause_kind, line, env_key)
        if question is not None:
            f = question.pending_fields(stage=stage)
            f["cause"] = cause
            did = p.decisions.record(f)
            p.decisions.stamp_server_time(did)
            ASK.journal_qid(p.journal, token, did)
        answer = (int(did[1:]), [o["token"] for o in question.options]) if did else None
        c = p.writer.create_comment(p.issue, needs_human.render(cause, prose, directive_line, answer))
        if did:
            p.decisions.amend(did, "pause_comment", c["id"])
        p.writer.labels_apply(p.issue, add=[NEEDS_HUMAN] + list(extra_labels), remove=list(remove_labels))
        return StageResult(StageResult.PAUSE, cause=token_cause, qid=did)
    res = PAUSE.pause(p.writer, p.decisions, p.issue, pz, question=question, stage=stage)
    ASK.journal_qid(p.journal, token, res["did"])
    return StageResult(StageResult.PAUSE, cause=token_cause, qid=res["did"])


def ask(p, stage, question, needs_human_line, pause_args=None):
    """Attended → pending block + `ask` event (StageResult ASK); unattended → pause with the
    question (`pause_args` = kwargs of `pause`)."""
    if not p.unattended:
        from guildcore.records import needs_human
        from workflows.dev import predict as PF
        pa = pause_args or {}
        # K6 predict-first: the ask event hides the recommendation; K5r3-M1: the one enforcement point checks every
        # text that goes out with the question (the event, the pending block's cause) — refused → not a blind answer
        PF.apply(p, question, stage, texts=(needs_human_line, pa.get("line"), pa.get("prose")))
        needs_human_line = PF.swap(question, needs_human_line)        # K5r5-M1: blind → the neutral wording only
        try:
            cause = needs_human.cause_line(pa.get("cause_kind") or "ambiguity",
                                           PF.swap(question, pa.get("line")) or needs_human_line, pa.get("env_key"))
        except ValueError:
            cause = needs_human.cause_line("ambiguity", needs_human_line)
        qid = ASK.surface(question, True, p.decisions, events=p.events, clock=p.clock, issue=p.issue,
                          stage=stage, journal=p.journal, cause=cause)
        return StageResult(StageResult.ASK, line=needs_human_line, qid=qid)
    return pause(p, stage, question=question, **(pause_args or {}))


def fail(p, stage, reason, cls="defect", env_key="service"):
    """C-F-6 / C6: an unattended FAIL is never a silent exit 0. defect → needs-human +
    `defect: engine FAIL — <reason>`; transient → `env: service — …`; gh_auth → exit 3 (no
    write: the needs-human write would fail too); prevalidate → no label (the caller exits 0/6)."""
    if cls in ("prevalidate", "prevalidate_env", "gh_auth") or not p.unattended:
        return StageResult(StageResult.FAIL, line=reason, fail_class=cls)
    if cls == "transient":
        r = pause(p, stage, "env", reason, "service unavailable — %s" % reason, env_key=env_key)
    else:
        r = pause(p, stage, "defect", "engine FAIL — %s" % reason, "engine FAIL — %s" % reason)
    r.fail_class = cls
    r.line = reason
    return r


def unknown_create(p, stage, reason, ex):
    """An Issue create whose landing is unknown (`GhWriteError("ambiguous")`): the `env: service` pause, never a
    re-send. K5r1 user decision 2: unattended, the result carries `retry_at` — the FSM ends with exit 75 at that
    time so the supervisor resumes by itself (the re-check: found → continue, absent → create again; a late
    duplicate is surfaced by the orphan check). Attended: the FAIL line as before."""
    import time as _t
    r = fail(p, stage, reason, "transient")
    if p.unattended and r.kind == StageResult.PAUSE:
        r.retry_at = max(int(getattr(ex, "retry_at", None) or 0), int(_t.time()) + 60)
    return r


def role_outcome(p, stage, role, res):
    """RoleResult statuses outside the P-RES five (K1 A9) → the stage's answer, or None when the
    status is one of DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT / FAIL (caller's)."""
    st = res.status
    if st == "HALTED":
        raise Halted()
    if st == "RATE_LIMITED":
        raise RateLimited(res.rl)
    if st == "INVALID":
        line = "%s returned no valid RESULT line" % role
        q = ASK.Question("role-result-invalid", "%s returned no valid RESULT line for #%d" % (role, p.issue),
                         [{"token": "retry", "label": "retry"}, {"token": "stop", "label": "stop"}])
        return ask(p, stage, q, "%s returned no valid RESULT line for #%d" % (role, p.issue),
                   {"cause_kind": "defect", "line": line, "token_cause": line})
    if st == "PERMISSION":
        cmd = (res.denials[-1].get("command") if res.denials else None) or (res.line or "?")
        line = "역할 권한 거부: %s" % cmd
        q = ASK.Question("permission", "%s was refused `%s`" % (role, cmd),
                         [{"token": "once", "label": "allow once"}, {"token": "stop", "label": "stop"}])
        return ask(p, stage, q, "%s was refused a command — %s" % (role, cmd), {
            "cause_kind": "env", "env_key": "other", "line": line, "token_cause": line,
            "prose": 'config.engine.role_allow.%s 에 "<pattern>" 을 추가하면 다음부터 허용' % role})
    if st == "DRIFT" and "not run" in (res.notes or []):
        # K4r3-m4(a): the role never started — the worktree was already wrong; the line names the
        # worktree, not the role (no scope violation in the role's ledger). An overlay left there is env.
        paths = ", ".join(str(v) for v in res.violations[:5]) or (res.line or "")
        overlay = all(str(v).startswith("lefthook overlay ") for v in res.violations or [])
        line = "%s not started — the worktree needs a person first: %s" % (role, paths)
        if overlay and res.violations:
            return pause(p, stage, "env", line, "env: other — %s" % line, env_key="other") if p.unattended else \
                StageResult(StageResult.FAIL, line=line, fail_class="defect")
        return pause(p, stage, "defect", line, line) if p.unattended else \
            StageResult(StageResult.FAIL, line=line, fail_class="defect")
    if st in ("SCOPE", "DRIFT"):
        paths = ", ".join(str(v) for v in res.violations[:5]) or (res.line or "")
        line = "%s wrote outside its scope — %s" % (role, paths)
        return pause(p, stage, "defect", line, line) if p.unattended else \
            StageResult(StageResult.FAIL, line=line, fail_class="defect")
    if st == "TIMEOUT":
        line = "%s timed out" % role
        return pause(p, stage, "defect", line, line) if p.unattended else \
            StageResult(StageResult.FAIL, line=line, fail_class="defect")
    return None


def register_exact(p):
    """K4 (P1): role text the stage posts is redacted by VALUE too — the `engine.effective.copy_ignored`
    files' strings (K3r1-M4), scoped to this run."""
    from guildcore.records import redact as RD
    RD.clear_exact()
    raw = getattr(p.config, "raw", None) or (p.config if isinstance(p.config, dict) else {})
    lst = ((raw.get("engine") or {}).get("effective") or {}).get("copy_ignored") or []
    if lst and p.root:
        RD.register_exact_from_files(p.root, lst)


def one_line(text, cap=300):
    t = " ".join((text or "").split())
    return t if len(t) <= cap else t[:cap - 1] + "…"


def neutral(text):
    return markers.value(text)


# ---- the Issue text a role or judge reads (K5 — K4r2-m10 carry-over: every execute/test/qa read) -----------

def issue_text(p, issue, cap=None):
    """'# title\n\nbody' for a role input or a judge brief, read through the THREE-valued author trust
    (P2): member → as is; outsider (or a child split from an outsider's Issue) → `OUTSIDER_PREFACE` first,
    so the body is data, not instructions; unknown → `analyze.TrustUnknown` propagates (the caller stops
    with `unknown_trust_result` — never a guess either way)."""
    from workflows.dev.stages import analyze as A
    t, _assoc = A.author_trust(p, issue)
    body = issue.get("body") or ""
    if cap is not None:
        body = body[:cap]
    text = "# %s\n\n%s" % (issue.get("title") or "", body)
    return text if t == "member" else A.OUTSIDER_PREFACE + text


def title_text(p, issue, n=None):
    """K5r1-m1: an Issue TITLE for a judge brief through the same author trust as `issue_text` — `#N title`
    as is for a member; an outsider's (or an unreadable association's — a title is short, so this one folds
    unknown into the marked side instead of stopping) gets `OUTSIDER_PREFACE` first. auth / rate-limit
    re-raise (exit 3 / 75)."""
    from workflows.dev.stages import analyze as A
    num = int(n if n is not None else (issue.get("number") or p.issue))
    try:
        t, _assoc = A.author_trust(p, issue, _issue=num)
    except A.TrustUnknown:
        t = "unknown"
    text = "#%d %s" % (num, issue.get("title") or "")
    return text if t == "member" else A.OUTSIDER_PREFACE + text


# ---- a split parent's own children (K4r3-B1 / m1 / m5) -------------------------------------------------

class ChildrenStop(Exception):
    """K4r4-m2/m4: the engine's child set needs a person (an orphan create, a deleted/transferred child)."""

    def __init__(self, line, cls="defect"):
        Exception.__init__(self, line)
        self.line, self.cls = line, cls


def _gone_error(text):
    from guildcore.records.write import gone_error
    return gone_error(text)


def import_children(p, prefix):
    """K5 (K4 carry-over 8 — host portability): the child numbers the parent's split record on GitHub names,
    for keys this clone's journal does not know (another host made them, or a fresh clone). Each one is
    confirmed BY NUMBER before it is journaled (`imported`): its body carries `slice-key <key>` and
    `Parent Issue: #<parent>`, the engine's own login wrote it, and it is in this repository — a number that
    fails any of these is not adopted (the stop / re-create paths that follow are the usual ones)."""
    from workflows.dev.stages.design import read_plan_record
    _text, kids = read_plan_record(records(p))
    if not kids:
        return
    j = p.writer._ij()
    known_keys = set(str(e.get("key") or "") for e in j.own_issues())
    known_nums = set(int(e["number"]) for e in j.own_issues())
    repo = None
    for key, n in sorted(kids.items()):
        if not key.startswith(prefix) or key in known_keys or int(n) in known_nums:
            continue
        repo = repo if repo is not None else p.writer.home_repo(p.issue)
        try:
            row, why = p.writer.own_issue_row(int(n), repo)
        except Exception:                                     # noqa: BLE001 — not adopted; the usual paths decide
            continue
        body = (row or {}).get("body") or ""
        if why is None and ("<!-- guild:slice-key %s -->" % key) in body and ("Parent Issue: #%d" % p.issue) in body \
                and p.writer._by_engine(row):
            j.own_write("issue", key=key, number=int(n), token=None, imported=True)


def own_children(p, include_withdrawn=False):
    """The child Issues THIS engine created for `p.issue`: the numbers its journal holds (keys
    `<parent>-…`), each read by number (`GET /repos/{o}/{r}/issues/N`) — never a listing, never the
    search index, never author association. An unresolved create (lost reply / crash between POST and
    record) is resolved first by its token through the REST list (`GhWriter.resolve_creates`; still
    unknown → `GhWriteError("ambiguous")`). A child a person closed as not planned is withdrawn and
    left out unless `include_withdrawn`. Rows: {number, title, body, state, stateReason, labels, key},
    ascending.
    K4r4: a create the engine had abandoned that landed after all (`GhWriter.orphan_creates`) → a person
    (`ChildrenStop`), never silently ignored (m2). A child read that fails as gone (404/410) or answers a
    different number / repository (deleted or transferred, m4) → recorded and a person; on the resume that
    follows it counts as withdrawn — no journal hand-edit, no crash loop. Closed as DUPLICATE is withdrawn
    only when a live child holds the same journal key (m5); otherwise the row carries `closed_as`."""
    from guildcore.adapters.gh import GhError, GhWriteError, classify_error
    from guildcore.records.write import closed_duplicate, withdrawn
    prefix = "%d-" % int(p.issue)
    import_children(p, prefix)
    p.writer.resolve_creates(prefix=prefix)
    orphans = p.writer.orphan_creates(prefix)
    if orphans:
        raise ChildrenStop("child Issue(s) of #%d outside the engine's journal: %s — a create the engine had given up "
                           "on (absent %d minutes after it was sent) landed after all; the engine does not drive it. "
                           "Close the extra one as not planned, then /gld resume %d" % (
                               p.issue, ", ".join("%s → #%d" % (k, n) for k, n in orphans),
                               p.writer.SETTLE_S // 60, p.issue))
    j = p.writer._ij()
    gone_seen = p.writer.gone_numbers()
    repo = p.writer.home_repo(p.issue)            # K4r5-m5: the parent's own row, not the configured name
    seen, rows, gone_now = set(), [], []
    for e in j.own_issues():
        k, n = str(e.get("key") or ""), int(e["number"])
        if not k.startswith(prefix) or n in seen:
            continue
        seen.add(n)
        if n in gone_seen:
            r, why = None, "recorded gone"
        else:
            try:
                r, why = p.writer.own_issue_row(n, repo)        # K4r5-m1: one judgement, shared with issue_create
            except GhWriteError as ex:
                if ex.kind in ("auth", "ratelimit"):
                    raise
                raise GhWriteError("issue:row", "child #%d: %s" % (n, one_line(ex.message, 160)), ex.kind)
        if why is not None:
            if n not in gone_seen:
                gone_now.append((k, n, why))
                continue
            r = {"number": n, "title": "", "body": "", "state": "CLOSED", "stateReason": "NOT_PLANNED",
                 "labels": [], "gone": True}
        r["key"] = k
        rows.append(r)
    if gone_now:
        for k, n, why in gone_now:
            j.own_write("issue-gone", key=k, number=n, why=why)
        raise ChildrenStop("child Issue(s) of #%d gone from this repository: %s — recorded; /gld resume %d counts "
                           "%s as withdrawn (the same as closing it as not planned). Restore the Issue first if "
                           "it must still be driven" % (
                               p.issue, "; ".join("#%d (%s) %s" % (n, k, why) for k, n, why in gone_now),
                               p.issue, "it" if len(gone_now) == 1 else "them"))
    live_keys = set(r["key"] for r in rows if not withdrawn(r) and not closed_duplicate(r))
    out = []
    for r in rows:
        if closed_duplicate(r):
            if r["key"] in live_keys:
                r["stateReason"] = "NOT_PLANNED"          # verified: a live child holds its key
                r["closed_as"] = "duplicate (verified)"
            else:
                r["closed_as"] = "duplicate (no live child holds %s)" % r["key"]
        if withdrawn(r) and not include_withdrawn:
            continue
        out.append(r)
    return sorted(out, key=lambda r: int(r["number"]))


def own_children_or_stop(p, stage, include_withdrawn=False):
    """(rows, None) or (None, StageResult): an unknown create stops for a person (`env: service`
    unattended, FAIL attended) — nothing is created or driven while it is unknown; auth / rate limit
    re-raise (exit 3 / 75); an orphan / gone child (`ChildrenStop`) → a person (K4r4-m2/m4)."""
    from guildcore.adapters.gh import GhWriteError
    try:
        return own_children(p, include_withdrawn), None
    except ChildrenStop as ex:
        return None, fail(p, stage, ex.line, ex.cls)
    except GhWriteError as ex:
        if ex.kind in ("auth", "ratelimit"):
            raise
        line = "child Issues of #%d — %s" % (p.issue, one_line(str(ex), 260))
        if ex.kind == "ambiguous":
            return None, unknown_create(p, stage, line, ex)
        return None, fail(p, stage, line, "transient" if ex.kind == "transient" else "defect")
