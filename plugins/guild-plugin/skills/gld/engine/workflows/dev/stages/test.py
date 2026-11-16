"""workflows.dev.stages.test — the `test` stage as code (C §2.T; design §2.8, §3.3 TEST/VIS-ENV).

    T0  enter (preflight, label read, --mark, split-parent guard, C-F-1 precondition, entry label)
        → interrupted loop-back (steps 6–7 only) → an applied human loop-back answer
    T1  the ENGINE runs `commands.test` (+ `commands.vrt` when VISUAL_RUN) under the tester's
        sandbox and parses the raw output (§2.8); unknown format → MJ-RUNNER, `unsure` → pause
        `env: other — 테스트 요약 형식을 읽지 못함 — commands.test_summary 를 설정하세요`;
        the tester role maps coverage (`covers`), judges E2E and writes the honesty statement
    T2  verify (code): raw is the only proof of green; tester claim vs raw → `verify-gap`
        capture (surprise when a claimed pass was red)
    T3  raw green → SJ-TEST per AC + the `effective` code check; not_covering/unsure → tester
        mapping repair ONCE → re-judge → still → uncovered (unsure-derived: no capture);
        vacuous → uncovered. Raw red with visual failures → pending regeneration (⊆ P rows:
        label → execute + needs-human, no loop-back) / environment suspect (host ∉ visual.env,
        else SJ-VIS-ENV; unsure → NH) / regression (red).
        test:output is posted (replace-in-place) before the transition; pass → test→qa handoff
        check → `guild:test → guild:qa` → ADVANCE; fail → attended: `loopback-*` lines + ask
        `loopback`; unattended: the loop-back procedure (`from: test`).
`--only test` on `done` (C12): suite only → a `<!-- guild:note -->` `recheck test <ts>: …`.
"""

import os
import re

from guildcore import ask as ASK
from guildcore import checks as CH
from guildcore.checks import visual as V
from guildcore.records import markers
from guildcore.records import outputs as OUT
from workflows.dev import cases as CS
from workflows.dev import effective as EFF
from workflows.dev import handoff as HO
from workflows.dev import judging as JG
from workflows.dev.stages import base as B
from workflows.dev.stages import loopback as LP
from workflows.dev.stages import render as R

STAGE = "test"
EVIDENCE = "test-evidence:step-1"
CEILING_S = 3600
# H§C:292 keyword pre-filter (MJ-DWC only when an input-reading word is near a partial word)
DWC_RE = re.compile(r"(읽|read|load|열).{0,24}(일부|부분|part|잘|truncat|cut)|(일부|부분|part(ial)?ly?|truncat|잘린).{0,24}(읽|read|load)", re.I)
RUNNER_PAUSE = "테스트 요약 형식을 읽지 못함 — commands.test_summary 를 설정하세요"


def cfg_dict(p):
    c = p.config
    return getattr(c, "raw", None) or (c if isinstance(c, dict) else {})


def commands_list(v):
    if not v:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def case_ids(text):
    return CS.case_ids(text)


def deferred_cases(evidence_body):
    blk = V.block_text(evidence_body, V.SAFETY_NET) or ""
    out = []
    for ln in blk.split("\n"):
        c = markers.clean(ln)
        if c.startswith("deferred:"):
            out += [x.strip() for x in c[len("deferred:"):].split(",") if x.strip() and x.strip() != "none"]
    return out


def summary_line(raw, summ):
    if summ is not None:
        for ln in reversed((raw or "").split("\n")):
            if re.search(r"All tests passed|Some tests failed|^Tests:|passed|failed|^ok |^FAIL|^Ran \d+", ln):
                return " ".join(ln.split())[:200]
        return "passed %d failed %d" % (summ.passed, summ.failed)
    tail = [l for l in (raw or "").split("\n") if l.strip()]
    return " ".join(tail[-1].split())[:200] if tail else ""


def _covers_by_ac(covers):
    out = {}
    for c in covers or []:
        out.setdefault(c.get("ac"), []).append(c)
    return out


def run(p, only=None, config_present=True):
    e = B.enter(p, STAGE, config_present, only)
    if isinstance(e, B.StageResult):
        return e
    B.note_untrusted(p, STAGE)
    comments = B.records(p)
    cfg = cfg_dict(p)
    if e.recheck:
        return _recheck(p, cfg)
    blk = LP.interrupted(comments, "guild:test", e.labels)                 # T0.9
    if blk is not None:
        q0, r0 = B.pending_answer(p, STAGE, "loopback", comments)
        if r0 is not None and (blk.get("decided") or "") == "human":
            B.mark_applied(p, STAGE, r0)                  # the answer's block landed before a crash
        return LP.finish_interrupted(p, STAGE, blk)
    q, res = B.pending_answer(p, STAGE, "loopback", comments)
    if res is not None:
        return apply_answer(p, STAGE, "test:output", q, res, comments)

    ev_body = markers.body_of(markers.find(comments, EVIDENCE))
    ledger = V.visual_ledger(ev_body)
    tc_rel = "docs/specs/%d/test-cases.md" % p.issue
    test_cases = p.read_file(tc_rel) or ""
    visual_cases = "<!-- guild:visual-cases -->" in test_cases
    vrun = V.visual_run(cfg, visual_cases, ledger)
    deferred = deferred_cases(ev_body)
    cmds = commands_list((cfg.get("commands") or {}).get("test"))
    if vrun:
        cmds += commands_list((cfg.get("commands") or {}).get("vrt"))
    runner = EFF.runner_of(cfg)

    # T1 — the engine runs the suite (§2.8)
    r = p.suite(cmds, "tester", CEILING_S)
    summ = CH.parse_summary(r.raw, runner, (cfg.get("commands") or {}).get("test_summary"))
    if summ is None and not r.timed_out:
        d = p.judge(JG.spec(p, "RUNNER", [("raw", r.raw[-4000:])], STAGE, "T2.3"))
        if d.choice not in ("green", "red"):
            return B.pause(p, STAGE, "env", RUNNER_PAUSE, "test summary unreadable", env_key="other")
        raw_green = d.choice == "green" and r.passed
    else:
        raw_green = bool(r.passed and not r.timed_out and (summ is None or summ.green))
    s_line = r.red_line() or summary_line(r.raw, summ)

    t = _tester(p, cfg, tc_rel, r, s_line, deferred, visual_cases, vrun)
    if isinstance(t, B.StageResult):
        return t
    tres = t
    covers = tres.extras.get("covers") or []
    e2e, e2e_ok = R.e2e_line(tres.extras.get("e2e") if isinstance(tres.extras.get("e2e"), str) else "")
    claim_pass = tres.status in ("DONE", "DONE_WITH_CONCERNS")

    # T2 — verify gate (code)
    gap = None
    if claim_pass and not raw_green:
        gap = ("claimed pass, raw red", True)
    elif tres.status == "FAIL" and raw_green:
        gap = ("claimed fail, raw green", False)

    # T3
    uncovered, vac, coverage, rows_unc, checks_field, tdec = [], [], [], [], "", None
    pending, env_suspect, images = False, None, []
    if raw_green:
        out = _judge_coverage(p, cfg, test_cases, covers, r.raw, ledger, visual_cases, tc_rel, deferred)
        if isinstance(out, B.StageResult):
            return out
        uncovered, vac, coverage, rows_unc, checks_field, tdec = out
    else:
        images = V.failing_images(r.raw)
        if images and V.confined_to_pending(images, ledger):
            pending = True
        elif images:
            env_suspect = _vis_env(p, cfg, images)
    failed_names = list(summ.failed_names) if summ else []
    uncovered_all = sorted(set(uncovered + rows_unc))
    passed = raw_green and not uncovered_all and gap is None

    # test:output (Step 2 — before any return that follows)
    ran = cmds
    not_run = {"e2e": (cfg.get("commands") or {}).get("e2e") or "없음", "more": []}
    vis = cfg.get("visual") or {}
    if (vis.get("tests") or vis.get("baselines")) and vis.get("runnable") is not True:
        not_run["more"].append(R.VRT_NOT_RUN_T % (vis.get("env") or "visual.env"))
    for d in deferred:
        not_run["more"].append("safety net deferred: %s" % d)
    verbatim = [b for b in (V.block_text(ev_body), V.block_text(ev_body, V.SAFETY_NET)) if b]
    verify_line = ("green — %s" % s_line) if raw_green else ("red — %s" % s_line)
    claim_line = "일치" if gap is None else "불일치 — %s" % gap[0]
    steps = [(st["cmd"].split(" -c ")[-1].strip("'") if "sandbox-exec" in st["cmd"] else st["cmd"],
              st["rc"], s_line if i == len(r.steps) - 1 else "") for i, st in enumerate(r.steps)] or \
        [(" && ".join(cmds), r.rc, s_line)]
    body = R.test_output(p.issue, steps, r.raw, verify_line, claim_line, coverage, ran, not_run,
                         verbatim, [x for x in images if p.exists(x)], e2e)
    p.writer.upsert_comment(p.issue, R.TEST, body)

    area = "#%d" % p.issue
    if gap is not None:
        p.capture("verify-gap", STAGE, "tester", "tester claim vs raw — %s" % gap[0], s_line, area, gap[1])
    if pending:
        return _pending(p, cfg, ledger, images)
    if env_suspect:
        return _env_pause(p, cfg, images)
    if passed:
        bad = HO.test_to_qa(B.records(p), cfg)
        if bad:
            return B.fail(p, STAGE, "test→qa handoff check failed on the engine's own output — %s" % "; ".join(bad))
        B.transition(p, e, "qa")
        return B.StageResult(B.StageResult.ADVANCE, nxt="qa")

    # verify failed (red, ceiling-killed, claim ≠ raw, AC gap)
    sig = sorted(set(failed_names + uncovered_all))
    if not sig:
        sig = ["timeout:%s" % (r.last_running or "unknown")] if r.timed_out else \
            (["claim-mismatch"] if gap else ["suite:red"])
    reason = _reason(raw_green, s_line, uncovered_all, vac, gap)
    if not (tdec is not None and set(uncovered_all) <= set(_unsure_derived(tdec))):
        p.capture("verify-gap", STAGE, "tester", reason, s_line, area, False)
    if not p.unattended:
        return ask_loopback(p, STAGE, R.TEST, reason, sig, "tests not green / AC gap — %s" % reason)
    return LP.run(p, STAGE, "test", reason, sig)


def _unsure_derived(tdec):
    return tdec.get("unsure_acs", []) if isinstance(tdec, dict) else []


def _reason(raw_green, s_line, uncovered, vac, gap):
    if not raw_green:
        return "tests not green — %s" % B.one_line(s_line, 160)
    if gap:
        return "tester claim ≠ raw — %s" % gap[0]
    if vac:
        return "vacuous tests for %s" % ", ".join(sorted(vac))
    return "AC gap — %s" % ", ".join(uncovered)


def _tester(p, cfg, tc_rel, r, s_line, deferred, visual_cases, vrun, addendum=None, task="verify"):
    inputs = {"raw-output.txt": r.raw, "suite-summary.txt": s_line,
              "visual.txt": "VISUAL_CASES = %s\nVISUAL_RUN = %s\ncommands.vrt = %s\nvisual.env = %s\n" % (
                  "yes" if visual_cases else "no", "yes" if vrun else "no",
                  (cfg.get("commands") or {}).get("vrt"), (cfg.get("visual") or {}).get("env")),
              "safety-net-deferred.txt": "\n".join(deferred) or "none",
              "test-cases-path.txt": tc_rel}
    res = p.run_role(B.RoleCall("tester", task, STAGE, "T1", inputs=inputs, addendum=addendum))
    o = B.role_outcome(p, STAGE, "tester", res)
    if o is not None:
        return o
    if res.status == "DONE_WITH_CONCERNS" and task == "verify" and DWC_RE.search(res.line or "") and \
            p.judge(JG.spec(p, "DWC", [("concern", res.line or "")], STAGE, "T1")).choice == "partial_read":
        res2 = p.run_role(B.RoleCall("tester", task, STAGE, "T1", inputs=inputs, attempt=2,
                                     addendum="Your report said you read an input only in part. Read every "
                                              "input file whole and redo the mapping."))
        o = B.role_outcome(p, STAGE, "tester", res2)
        return o if o is not None else res2
    return res


def _excerpts(p, covers, cfg, tool_mode=False):
    """The cited tests' OWN blocks (no-elide) — or, in tool mode (K2-M4: the blocks do not fit the
    brief), `path:line` pointers the judge reads with Read/Grep."""
    runner = EFF.runner_of(cfg)
    parts = []
    for c in covers:
        path, name = EFF.parse_test_ref(c.get("test"))
        txt = p.read_file(path) if path else None
        tb = EFF.test_body(txt, name, runner) if txt is not None else None
        if tb is None:
            parts.append("### %s (AC %s)\n(body not found)" % (c.get("test"), c.get("ac")))
        elif tool_mode:
            parts.append("- %s (AC %s): %s:%d-%d" % (c.get("test"), c.get("ac"), path, tb[1],
                                                     tb[1] + tb[0].count("\n")))
        else:
            parts.append("### %s (AC %s) — %s:%d\n%s" % (c.get("test"), c.get("ac"), path, tb[1],
                                                         "\n".join(tb[0].split("\n")[:EFF.EXCERPT_CAP])))
    return "\n\n".join(parts) or "(no excerpt — cited test files not found)"


def merge_covers(old, new, weak):
    """K2-M2: a repair answers for the WEAK ids only — their entries are replaced, every other
    AC keeps the first mapping (a repair that touches a non-weak AC is ignored)."""
    keep = [c for c in old if c.get("ac") not in weak]
    return keep + [c for c in (new or []) if c.get("ac") in weak]


def _judge_once(p, cfg, tc_rel, test_cases, covers, ledger, raw, attempt):
    from guildcore.judges.runner import BriefTooLarge
    for tool_mode in (False, True):
        brief = [("ac", "AC / test cases (%s):\n%s" % (tc_rel, test_cases or "(test-cases.md missing)")),
                 ("covers", "Tester covers:\n" + "\n".join("- %s ← %s (%s)" % (c.get("ac"), c.get("test"), c.get("kind"))
                                                           for c in covers)),
                 ("excerpts", ("Read these test blocks with the Read tool:\n" if tool_mode else "") +
                  _excerpts(p, covers, cfg, tool_mode)),
                 ("visual", "Visual ledger:\n%s" % (ledger.text if ledger else "none")),
                 ("raw", "Raw run tail:\n" + "\n".join((raw or "").split("\n")[-80:]))]
        try:
            return p.judge(JG.spec(p, "TEST", brief, STAGE, "T3.4", cwd=p.root,
                                   point="TEST" if attempt == 1 else "TEST:repair")), tool_mode
        except BriefTooLarge:
            continue
    return None, True


def _judge_coverage(p, cfg, test_cases, covers, raw, ledger, visual_cases, tc_rel, deferred):
    acs = [a for a in CS.case_ids(test_cases) if a not in deferred]
    ac_source = "test-cases"
    if not acs:                 # B2: legacy proceeds; the design→execute gap is recorded, not a stop
        acs = sorted(set(c.get("ac") for c in covers if c.get("ac")) - set(deferred))
        ac_source = "tester" if acs else "none"
    if not acs:
        B.record_code(p, STAGE, "TEST", "unjudged", reason="%s has no case ids and the tester mapped none" % tc_rel,
                      refs="T-AC-COVER", extra={"ac_source": "none", "grade": "trigger"})
        return [], [], [], [], "", {"unsure_acs": []}
    attempt, weak, outcomes, meta, d = 0, [], {}, {}, None
    while True:
        attempt += 1
        d, tool_mode = _judge_once(p, cfg, tc_rel, test_cases, covers, ledger, raw, attempt)
        if d is None:
            return B.fail(p, STAGE, "brief too large for TEST")
        per = {a.get("id"): a for a in d.fields.get("ac") or []}
        verdicts = {ac: (per.get(ac) or {}).get("verdict", "unsure") for ac in acs}
        eff = [ac for ac, v in verdicts.items() if v == "effective"]
        outcomes, meta = EFF.run(p, cfg, eff, _covers_by_ac(covers), p.base, p.impl_files)
        for ac, oc in outcomes.items():
            if oc.result in ("fail", "unsure"):
                verdicts[ac] = "unsure"
        weak = [ac for ac, v in verdicts.items() if v in ("not_covering", "unsure")]
        _record_test(p, d, acs, verdicts, outcomes, meta, ac_source, attempt, tool_mode)
        if weak and attempt == 1:
            rep = p.run_role(B.RoleCall("tester", "repair-mapping", STAGE, "T3.4", attempt=2,
                                        inputs={"weak-acs.txt": "\n".join(weak)},
                                        addendum="Map these AC ids to the tests that cover them (or say none "
                                                 "does): %s. Re-write covers only — do not re-run the suite." % ", ".join(weak)))
            o = B.role_outcome(p, STAGE, "tester", rep)
            if o is not None:
                return o
            covers = merge_covers(covers, rep.extras.get("covers"), set(weak))
            continue
        break
    vac = [ac for ac, v in verdicts.items() if v == "vacuous"]
    unsure_acs = [ac for ac, v in verdicts.items() if v == "unsure"]
    uncovered = sorted(ac for ac, v in verdicts.items() if v != "effective")
    rows_unc = [r_.get("row") for r_ in d.fields.get("visual_rows") or [] if r_.get("verdict") != "covered"] \
        if visual_cases else []
    coverage = [(ac, verdicts[ac] if not (ac in outcomes and outcomes[ac].result == "unverified")
                 else "effective (unverified)",
                 [c.get("test") for c in _covers_by_ac(covers).get(ac, [])],
                 (outcomes[ac].why if ac in outcomes else (per.get(ac) or {}).get("why")))
                for ac in acs]
    checks_field = ",".join(o_.as_field() for o_ in outcomes.values())
    return uncovered, vac, coverage, [x for x in rows_unc if x], checks_field, {"unsure_acs": unsure_acs}


def _record_test(p, d, acs, verdicts, outcomes, meta, ac_source, attempt, tool_mode):
    """K2-M3: every SJ-TEST call is a decision block; per AC the cited test, its assertion line,
    the re-run command and class (§9.5 citation material); `unverified` checks flag the
    decision for the human sample (`grade: trigger` — K2-B3)."""
    eff = sorted(ac for ac, v in verdicts.items() if v == "effective")
    unc = sorted(ac for ac, v in verdicts.items() if v != "effective")
    unver = [o for o in outcomes.values() if o.result == "unverified"]
    detail = ";".join("%s|%s|%s|%s|%s" % (o.ac, o.test, o.line, o.cmd, o.kind) for o in outcomes.values())
    B.record_judgment(p, STAGE, "TEST" if attempt == 1 else "TEST:repair", "T-AC-COVER,T-VACUOUS,T-VISUAL-COV", d,
                      choice="effective:%s;uncovered:%s" % (",".join(eff) or "none", ",".join(unc) or "none"),
                      reason=d.fields.get("reason"),
                      extra={"attempt": attempt, "checks": ",".join(o.as_field() for o in outcomes.values()) or None,
                             "check_detail": detail or None, "impl_source": meta.get("impl_source"),
                             "impl_rejected": ",".join(meta.get("rejected") or []) or None,
                             "base_source": meta.get("base_source"), "ac_source": ac_source,
                             "brief": "tool" if tool_mode else None,
                             "unsure_acs": ",".join(ac for ac, v in verdicts.items() if v == "unsure") or None,
                             "grade": "trigger" if unver or ac_source != "test-cases" else None})


def _vis_env(p, cfg, images):
    env = (cfg.get("visual") or {}).get("env")
    if (cfg.get("visual") or {}).get("runnable") is not True:
        return True                                   # goldens ran in commands.test anyway (T3.3)
    mm = V.env_mismatch(p.host, env)
    if mm is True:
        return True
    d = p.judge(JG.spec(p, "VIS-ENV", [("failing", "Failing images:\n" + "\n".join(images)),
                                       ("env", "visual.env = %s\nhost = %s" % (env, p.host))], STAGE, "T3.3"))
    B.record_judgment(p, STAGE, "VIS-ENV", "J-V3,T-VISUAL-ENV", d)
    return d.choice != "regression"


def _pending(p, cfg, ledger, images):
    env = (cfg.get("visual") or {}).get("env") or "visual.env"
    paths = ", ".join(images)
    text = "%d images pending regeneration in %s — %s; after committing them, run /gld resume %d (it re-enters execute)" % (
        len(images), env, paths, p.issue)
    if not p.unattended:
        p.writer.labels_apply(p.issue, add=["guild:execute", B.NEEDS_HUMAN], remove=["guild:test"])
        q = ASK.Question("pending-regeneration", text, [{"token": "ok", "label": "ok"}])
        return B.ask(p, STAGE, q, text)
    return B.pause(p, STAGE, "env", text, "pending regeneration", env_key="other",
                   extra_labels=["guild:execute"], remove_labels=["guild:test"])


def _env_pause(p, cfg, images):
    from workflows.dev import directive as DR
    env = (cfg.get("visual") or {}).get("env") or "visual.env"
    text = "visual failures look environmental — %s vs %s; %d images" % (env, p.host or "this host", len(images))
    g = DR.gather(p.gh, p.issue)
    kind, dline, dd = DR.judge(p, STAGE, g, text, "T3.3")
    if dd is not None:
        B.record_judgment(p, STAGE, "DIRECTIVE", "J-H1,Q-DIRECTIVE", dd, reason=dline)
    if not p.unattended:
        q = ASK.Question("visual-env", text, [{"token": "ok", "label": "ok — I will look"}])
        return B.ask(p, STAGE, q, text)
    return B.pause(p, STAGE, "env", text, "visual environment", env_key="other", directive_line=dline)


def ask_loopback(p, stage, output_name, reason, sig, prefix):
    """Attended asking-first: readings only, `loopback-*` lines into the stage output, then the
    `loopback` question (the human decides — no recommendation)."""
    rd = LP.readings(p, stage, sig)
    cur = OUT.find(B.records(p), output_name)
    if cur is not None:
        p.writer.upsert_comment(p.issue, output_name, R.add_loopback_lines(cur.body, output_name, reason, sig))
    line = LP.ask_line(prefix, rd)
    q = ASK.Question("loopback", line, [{"token": "loop-back", "label": "loop back"},
                                        {"token": "stop", "label": "stop"}], point="loopback-ask:%s" % stage)
    return B.ask(p, stage, q, line)


def apply_answer(p, stage, output_name, q, res, comments):
    """The human's loop-back answer: `loop-back` → procedure steps 1, 4–7 with `decided: human`
    (reason/signature from the output's `loopback-*` lines); `stop` → PAUSE. Owes no captures."""
    if res.get("choice") != "loop-back":
        B.mark_applied(p, stage, res)
        return B.StageResult(B.StageResult.PAUSE, cause="stopped by the human (%s)" % q.id)
    so = OUT.find(comments, output_name)
    reason = markers.unescape(so.loopback_reason or "") if so else ""
    sig = markers.unescape(so.loopback_signature or "") if so else ""
    if not reason or not sig:
        return B.fail(p, stage, "loop-back answer without loopback-reason/-signature lines in %s" % output_name)
    out = LP.run(p, stage, stage, reason, sig, decided_human=True)
    if out.kind == B.StageResult.LOOPBACK:              # K2-m5: marked only after the block landed
        B.mark_applied(p, stage, res)
    return out


def _recheck(p, cfg):
    cmds = commands_list((cfg.get("commands") or {}).get("test"))
    r = p.suite(cmds, "tester", CEILING_S)
    summ = CH.parse_summary(r.raw, EFF.runner_of(cfg))
    green = bool(r.passed and (summ is None or summ.green))
    p.writer.create_comment(p.issue, OUT.render_recheck_note(p.now(), green, r.red_line() or summary_line(r.raw, summ)))
    return B.StageResult(B.StageResult.DONE, notes=["recheck: %s" % ("green" if green else "red")])
