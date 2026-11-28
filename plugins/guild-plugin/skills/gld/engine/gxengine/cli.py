"""Engine command line (design §7.3, U18) — U18.

    python3 -I <plugin>/skills/gld/engine/engine.py dev    --repo owner/name --issue N [--mode attended|unattended] [--checkout DIR] [--foreground]
    python3 -I <plugin>/skills/gld/engine/engine.py resume --repo owner/name --issue N [--answer <answer>] [--step S] [--reason R] [--note-file F] [--close-reason completed|not-planned] [--template NAME] [--foreground]
    python3 -I <plugin>/skills/gld/engine/engine.py resume --repo owner/name --issue N --pr-review | --dismiss STEP --reason-file F [--foreground]
    python3 -I <plugin>/skills/gld/engine/engine.py status --repo owner/name --issue N [--json] [--wait SECONDS]
    python3 -I <plugin>/skills/gld/engine/engine.py owned  --repo owner/name --issue N [--json]     (readiness T1 P5)
    python3 -I <plugin>/skills/gld/engine/engine.py taken  --repo owner/name [--json]               (readiness T1 P7)
    python3 -I <plugin>/skills/gld/engine/engine.py channel show [--checkout DIR] [--json]          (readiness T1 R4-14)
    python3 -I <plugin>/skills/gld/engine/engine.py channel set <channel> --repo owner/name [--checkout DIR] [--dry-run] [--json]
    python3 -I <plugin>/skills/gld/engine/engine.py canary [--role-class work|judge] [--srt-only|--no-srt] [--config FILE] [--model M] [--effort E] [--max-usd X] [--budget-probe] [--json]

`dev`/`resume` detach (lifecycle.spawn_detached) unless --foreground, print the engine
log path and exit 0. `status` merges state.json, log.jsonl and the attempt folders
(§4.3). Exit codes: 0 ok / detached, 2 usage, 3 lock held, 4 refused (self check,
stable label, format mismatch), 10 stopped needs_human, 11 stopped needs_leader.

U18 choices (the P3-C report lists them):
  - `--checkout` (default: the current directory) names the main checkout; only `dev`
    on a new Issue uses it.
  - `resume --answer` is required when the Issue is stopped and refused when it is not;
    a resume of an engine that died mid-step (state `running`, no live lock) needs no
    answer (S9). The answer is checked BEFORE detaching (exit 4 at once, nothing written);
    the detached engine applies it under the lock.
  - `--note-file` is read before detaching (UTF-8, at most 64 KiB) and passed on through a
    file in the engine records, never through argv.
  - `status --wait S` blocks until the detached engine has written engine.rc or S seconds
    passed, then prints the status — the conversation polls with it instead of tailing
    engine.log (no engine log flows into the conversation, §7.3). Its exit code is the
    engine's (0/10/11/…) once finished, 0 while still running.
  - `canary` (P4): the PAID role canary for both role classes (or `--role-class`) with the
    real `claude` (haiku / low by default, total stop at `--max-usd`, default
    defaults.CANARY_TOTAL_MAX_USD) plus the free srt canary (`--config` = a repository
    config whose sandbox exceptions shape the run template and the work-role template —
    P5 F2; none = the default templates).
    Records go to `<engine home>/canary/` (canaryrun). Exit 0 when every canary passed,
    4 when one failed. Needed by hand only after a failed one: a stage-3 engine runs a missing
    role canary itself (K8-1), but never again a failed one. `--repo` is accepted for symmetry and only echoed.

Stage 2 (scope §2.7, D17, D24, V9): `dev` / `resume` run with defaults.ENGINE_STAGE (2 since
the stage-2 merge, Q6; `main(stage=)` for tests). resume takes the stage-2 answers
(plan, rerun, close-as-decided, approve, replan, continue, escalate — no D4 narrowing for
the human); `--close-reason completed|not-planned` goes with close-as-decided only and that
answer needs it; a `needs_leader` stop takes NO answer (exit 4 on one) — resume without an
answer calls the leader again. `status` shows the leader recommendation / failure of the
stop, "waiting for the leader" (exit 11), a close-as-decided, and one line per leader call.

Stage 3 (scope §2.12, V15): resume takes `continue` / `rerun` at an irreversible-change stop
(a human decides, no leader), `continue` / `skip` (with `--step` = the step to skip) /
`escalate` at step-removal-request, `continue` / `escalate` at step-add-limit. `--template`
goes with `--answer plan` only: the template as it is (without it: the one of the analysis
type). `status` adds the role requests and how they ended, the irreversible changes, the
retry raises, the included fixes, the follow-ups and — public repository — the engine-local
security findings. `--pr-review` (a finished Issue with a PR: the collaborators' new reviews go
to the leader, the same PR is updated) and `--dismiss STEP --reason-file F` (a human overrules
the block of the review that stopped the Issue) take no `--answer`; both are refused before
detaching when the state does not fit.

Stage 4 (stage-4 scope; the commands below are refused, exit 4, by an earlier stage — H23):

    engine.py sprint run    --repo O/N --tracker T --checkout DIR [--window W] [--allow-red-base] [--take-over] [--foreground]
    engine.py sprint status --repo O/N --tracker T [--json] [--wait S]
    engine.py sprint report --repo O/N --tracker T --json
    engine.py sprint check  --repo O/N --tracker T
    engine.py sprint stop   --repo O/N --tracker T
    engine.py init doctor|propose|answer|check|write --repo O/N [--checkout DIR] …
    engine.py init roles --repo O/N [--checkout DIR] [--json]          (readiness T2 R4-3: which role files init writes)
    engine.py init migrate --repo O/N [--checkout DIR] [--apply] [--json]   (readiness T2 P4: a 0.98.x install → this channel)
    engine.py base-check --repo O/N [--checkout DIR] [--sha SHA] [--config FILE] [--force] [--json]
    engine.py resume … --answer rerun --step S --allow-test-change PATH … --note-file F     (E9-2, H21)

Readiness R1 (design/guild/24-redesign/readiness/incidents.md; any stage — they only read or remove engine records):

    engine.py incidents list [--json]                     every incident + its verdict against data/fixed-defects.json
    engine.py incidents prune [--apply] [--json]          retro: remove the `fixed` ones (without --apply: say which)
    engine.py records prune --repo O/N --tracker T [--issue N …] [--apply] [--json]   retro: finished members' records
    engine.py records stale [--days 90] [--json]          status: Issue records untouched for --days
    engine.py records stale --apply --pick O/N#M …        status: remove the ones a human picked (checked again)

`sprint run` detaches like dev (supervisor.log / supervisor.rc in the sprint's records; under `caffeinate -i`
with a window); `--foreground` is the supervisor itself. Exit: 0 finished / detached, 3 another supervisor of the
repository, 4 refused or halted. `sprint status --wait S` waits for supervisor.rc like `status`. A window is
validated here too, before detaching; without `--window` the previous run's is inherited, `--window none` is this
run without one. Hidden arguments of a sprint member (H6, D6): `dev --base-sha --base-branch [--draft] --sprint`
(unattended, foreground only) and `resume --foreground --answer rerun --sprint T` (the sprint seat). Every unknown
or left-over argument is refused.
"""

import argparse
import json
import os
import shutil
import sys
import time

from . import (basecheck, canary, canaryrun, channel as channelmod, codes, defaults, driver, fsafe, github, gitops,
               incidents, initconfig, initharness, lifecycle, paths as pathsmod, repoconfig, retention, sprint as sprintmod,
               sprintdag, sprinttracker, store, testchange)

EXIT_OK = driver.EXIT_OK
EXIT_USAGE = driver.EXIT_USAGE
EXIT_LOCKED = driver.EXIT_LOCKED
EXIT_REFUSED = driver.EXIT_REFUSED
EXIT_NEEDS_HUMAN = driver.EXIT_NEEDS_HUMAN
EXIT_NEEDS_LEADER = driver.EXIT_NEEDS_LEADER

NOTE_MAX_BYTES = 64 * 1024
NOTE_FILE = "resume-note.txt"
WAIT_POLL_S = 2.0


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        raise SystemExit(EXIT_USAGE)


def _issue_number(v):
    try:
        n = int(v, 10)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an Issue number: {v!r}") from None
    if n < 1 or str(n) != v:
        raise argparse.ArgumentTypeError(f"not an Issue number: {v!r}")
    return n


def _sha(v):
    if not gitops._is_sha(v):
        raise argparse.ArgumentTypeError(f"not a full commit sha: {v!r}")
    return v


def _repo(v):
    try:
        pathsmod.split_repo(v)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None
    return v


def build_parser():
    """argparse parser for the commands above."""
    p = _Parser(prog="engine.py", description="guild-plugin engine (/gld)")
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)

    def common(sp):
        sp.add_argument("--repo", required=True, type=_repo, help="owner/name")
        sp.add_argument("--issue", required=True, type=_issue_number)

    d = sub.add_parser("dev", help="start (or continue) an Issue")
    common(d)
    d.add_argument("--mode", choices=codes.RunMode.values(), default=codes.RunMode.ATTENDED.value)
    d.add_argument("--checkout", help="the main checkout (default: the current directory)")
    d.add_argument("--foreground", action="store_true", help="run here instead of detaching")
    # stage 4 (H6): the start input of a sprint member — the supervisor's only
    d.add_argument("--base-sha", type=_sha, help=argparse.SUPPRESS)
    d.add_argument("--base-branch", help=argparse.SUPPRESS)
    d.add_argument("--draft", action="store_true", help=argparse.SUPPRESS)
    d.add_argument("--sprint", type=_issue_number, help=argparse.SUPPRESS)

    r = sub.add_parser("resume", help="answer a stop and continue")
    common(r)
    r.add_argument("--answer", choices=codes.LeaderAnswer.values())
    r.add_argument("--step", help="step id for rerun (stage 3: for skip, the step to skip)")
    r.add_argument("--reason", choices=codes.LeaderReason.values())
    r.add_argument("--note-file", help="a UTF-8 file whose text goes to leader-decision.md")
    r.add_argument("--close-reason", choices=codes.CloseReason.values(),
                   help="stage 2: close-as-decided only (the note file is the closing comment)")
    r.add_argument("--template", choices=codes.STAGE3_TEMPLATES,
                   help="stage 3: plan only - this template instead of the analysis type's")
    r.add_argument("--pr-review", action="store_true",
                   help="stage 3: after the PR - the leader looks at the new pull request reviews")
    r.add_argument("--dismiss", metavar="STEP", help="stage 3: overrule the block of this review step (needs --reason-file)")
    r.add_argument("--reason-file", help="a UTF-8 file with the reason of --dismiss (shown in the PR)")
    r.add_argument("--allow-test-change", action="append", metavar="PATH",
                   help="stage 4: rerun only - a base verification file this Issue may modify (one path each; needs --step "
                        "and --note-file)")
    r.add_argument("--foreground", action="store_true")
    r.add_argument("--note-from-records", action="store_true", help=argparse.SUPPRESS)
    r.add_argument("--sprint", type=_issue_number, help=argparse.SUPPRESS)     # stage 4 (D6): the sprint seat

    s = sub.add_parser("status", help="state + log + attempts of an Issue")
    common(s)
    s.add_argument("--json", action="store_true")
    s.add_argument("--wait", type=float, default=0.0, help="wait up to SECONDS for the engine to finish")

    tk = sub.add_parser("taken", help="readiness T1 P7: the Issues an open pull request closes (any branch) or whose "
                                      "gld/N is on the remote — read only, for sprint plan")
    tk.add_argument("--repo", required=True, type=_repo, help="owner/name")
    tk.add_argument("--json", action="store_true")

    o = sub.add_parser("owned", help="readiness T1 P5: is the Issue the engine's? (records here, gld/N on the remote, "
                                     "an engine summary comment) — read only; exit 0 no, 4 yes or unknown")
    common(o)
    o.add_argument("--json", action="store_true")

    c = sub.add_parser("canary", help="boundary canary (P4) — the role canary is a PAID call")
    c.add_argument("--repo", type=_repo)
    c.add_argument("--role-class", choices=codes.RoleClass.values())
    g = c.add_mutually_exclusive_group()
    g.add_argument("--srt-only", action="store_true", help="only the free srt canary")
    g.add_argument("--no-srt", action="store_true", help="skip the srt canary")
    c.add_argument("--config", help="a repository config (.claude/guild/config.json): its sandbox exceptions shape the srt canary and the work-role canary")
    c.add_argument("--model", default="haiku")
    c.add_argument("--effort", default="low")
    c.add_argument("--max-usd", type=float, default=None)
    c.add_argument("--budget-probe", action="store_true", help="also record the CLI's budget-end shape")
    c.add_argument("--keep-layout", action="store_true", help=argparse.SUPPRESS)
    c.add_argument("--json", action="store_true")
    _stage4_parsers(sub)
    _retention_parsers(sub)
    _channel_parsers(sub)
    return p


def _channel_parsers(sub):
    """Readiness T1 R4-14: one channel per repository — show the verdict (routing), set the active channel."""
    ch = sub.add_parser("channel", help="the repository's active Guild channel").add_subparsers(
        dest="action", required=True, parser_class=_Parser)
    x = ch.add_parser("show", allow_abbrev=False, help="may this channel's commands run here? exit 0 yes, 4 no")
    x.add_argument("--checkout", help="the checkout (default: the current directory)")
    x.add_argument("--json", action="store_true")
    x = ch.add_parser("set", allow_abbrev=False, help="make a channel the repository's active one")
    x.add_argument("target", choices=channelmod.CHANNELS)
    x.add_argument("--repo", required=True, type=_repo, help="owner/name")
    x.add_argument("--checkout", help="the checkout (default: the current directory)")
    x.add_argument("--dry-run", action="store_true", help="say what would change, write nothing")
    x.add_argument("--json", action="store_true")


def _retention_parsers(sub):
    """Readiness R1: incidents (daily shows, retro prunes) · records (retro prunes members, status lists stale)."""
    inc = sub.add_parser("incidents", help="engine incidents: list / prune the fixed ones").add_subparsers(
        dest="action", required=True, parser_class=_Parser)
    x = inc.add_parser("list", allow_abbrev=False)
    x.add_argument("--json", action="store_true")
    x = inc.add_parser("prune", allow_abbrev=False, help="remove the incidents the fixed-defects list explains")
    x.add_argument("--apply", action="store_true", help="remove (without it: only say what would go)")
    x.add_argument("--json", action="store_true")
    rec = sub.add_parser("records", help="engine records: prune a sprint's finished members / list stale ones")\
        .add_subparsers(dest="action", required=True, parser_class=_Parser)
    x = rec.add_parser("prune", allow_abbrev=False, help="members whose pull requests are all merged or closed")
    x.add_argument("--repo", required=True, type=_repo, help="owner/name")
    x.add_argument("--tracker", required=True, type=_issue_number, help="the sprint tracking Issue")
    x.add_argument("--issue", action="append", type=_issue_number, help="only these members (one each)")
    x.add_argument("--apply", action="store_true")
    x.add_argument("--json", action="store_true")
    x = rec.add_parser("stale", allow_abbrev=False, help="Issue records untouched for --days (default 90)")
    x.add_argument("--days", type=int, default=retention.STALE_DAYS)
    x.add_argument("--apply", action="store_true", help="remove the --pick ones (checked again first)")
    x.add_argument("--pick", action="append", metavar="OWNER/REPO#N", default=[])
    x.add_argument("--json", action="store_true")


def _stage4_parsers(sub):
    """sprint · init · base-check (stage 4): parsers only — the modules behind them belong to the branches."""
    sp = sub.add_parser("sprint", help="stage 4: run / show a sprint").add_subparsers(
        dest="action", required=True, parser_class=_Parser)

    def one(name, **kw):
        x = sp.add_parser(name, allow_abbrev=False, **kw)
        x.add_argument("--repo", required=True, type=_repo, help="owner/name")
        x.add_argument("--tracker", required=True, type=_issue_number, help="the sprint tracking Issue")
        return x
    x = one("run", help="run the members one after the other, unattended")
    x.add_argument("--checkout", required=True)
    x.add_argument("--window", help="HH:MM-HH:MM or none")
    x.add_argument("--allow-red-base", action="store_true")
    x.add_argument("--take-over", action="store_true")
    x.add_argument("--foreground", action="store_true")
    x = one("status")
    x.add_argument("--json", action="store_true")
    x.add_argument("--wait", type=float, default=0.0)
    x = one("report")
    x.add_argument("--json", action="store_true", required=True)
    one("check", help="read the member table, hash and order; writes nothing")
    one("stop", help="ask the supervisor to stop after the running member")

    it = sub.add_parser("init", help="stage 4: make the engine settings of a repository").add_subparsers(
        dest="action", required=True, parser_class=_Parser)
    for name in initconfig.ACTIONS:
        x = it.add_parser(name, allow_abbrev=False)
        x.add_argument("--repo", required=True, type=_repo, help="owner/name")
        x.add_argument("--checkout", help="the main checkout (default: the current directory)")
        x.add_argument("--json", action="store_true")
        if name == "propose":
            x.add_argument("--compare", action="store_true", help="only the differences to the committed settings")
        if name == "answer":
            x.add_argument("--question", required=True, choices=codes.InitQuestion.values())
            x.add_argument("--item", help="what the question is about")
            g = x.add_mutually_exclusive_group(required=True)
            g.add_argument("--answer", help="the human's answer")
            g.add_argument("--answer-file", help="a UTF-8 file with the human's answer")
            x.add_argument("--note", required=True, help="who answered and why")
    for name in initharness.ACTIONS:                      # readiness T2: the harness parts the engine decides
        x = it.add_parser(name, allow_abbrev=False)
        x.add_argument("--repo", required=True, type=_repo, help="owner/name")
        x.add_argument("--checkout", help="the main checkout (default: the current directory)")
        x.add_argument("--json", action="store_true")
        if name == "migrate":
            x.add_argument("--apply", action="store_true", help="make the migration (default: a dry run)")

    b = sub.add_parser("base-check", allow_abbrev=False, help="stage 4: are the named commands green on a base commit?")
    b.add_argument("--repo", required=True, type=_repo, help="owner/name")
    b.add_argument("--checkout", help="the main checkout (default: the current directory)")
    b.add_argument("--sha", type=_sha, help="the base commit (default: the checkout's HEAD)")
    b.add_argument("--config", help="settings to check instead of the committed ones")
    b.add_argument("--force", action="store_true", help="run again although a green record exists")
    b.add_argument("--json", action="store_true")


def _plugin_root():
    # gxengine/ → engine/ → <skill>/ → skills/ → <plugin root>
    here = os.path.dirname(os.path.realpath(__file__))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here))))


def _paths(args, environ):
    return pathsmod.EnginePaths(pathsmod.engine_home(environ), args.repo, args.issue)


# --- status ---------------------------------------------------------------------------------

def status_report(paths, stage=None):
    """{state, stop, question, running, rc, lock, steps, last_events, attempts} from the three records.

    Stage 2 also: `leader_calls` (state.leader_calls) and `closed` (close-as-decided). Stage 3:
    `requests`, `irreversible`, `raised` (log), `included_fixes`, `followups`, `security_findings`
    (the engine-local text, E21)."""
    stage = defaults.ENGINE_STAGE if stage is None else stage
    state = store.load_state(paths)
    log = list(store.read_log(paths))
    holder = lifecycle.lock_holder(paths)
    rc = lifecycle.read_rc(paths)
    out = {"repo": paths.repo, "issue": paths.issue, "records": paths.issue_dir,
           "engine_log": paths.engine_log, "running": holder is not None and holder.get("issue") == paths.issue,
           "lock": holder, "rc": rc, "state": None, "stop": None, "question": None, "steps": [],
           "totals": None, "pr": None, "last_events": log[-10:], "leader_calls": [], "closed": None,
           "requests": [], "irreversible": None, "raised": [], "included_fixes": [], "followups": [],
           "security_findings": None, "notices": _notices(log),
           "exists": state is not None}   # readiness T1 P5: this machine has engine records (a state.json) of the Issue
    if state is None:
        return out
    soft = lifecycle.soft_budget_answered(paths)
    out["state"] = {"revision": state["revision"], "last_head": state["last_head"],
                    "branch": state.get("branch"), "worktree": (state.get("git") or {}).get("work_tree"),
                    "updated_at": state.get("updated_at")}
    out["stop"] = state.get("stop")
    if not out["running"]:
        out["question"] = lifecycle.pending_question(state, stage, soft_answered=soft)
    out["totals"] = state.get("totals")
    out["leader_calls"] = state.get("leader_calls") or []
    out["closed"] = state.get("closed")
    for key in ("requests", "included_fixes", "followups"):
        out[key] = state.get(key) or []
    irr = state.get("irreversible")
    if irr:
        out["irreversible"] = dict(irr, waiting=lifecycle.unapproved_irreversible(state))
    out["raised"] = [{"step": l.get("step"), "attempt": l.get("attempt"), **(l.get("data") or {})}
                     for l in log if l["event"] == codes.LogEvent.MODEL_RAISED.value]
    out["security_findings"] = driver.read_security_findings(paths)
    g = state.get("github") or {}
    if g.get("pr_number"):
        out["pr"] = {"number": g["pr_number"], "url": g.get("pr_url")}
    for s in state["steps"]:
        n = s.get("latest_attempt")
        attempts = []
        if n:
            try:
                attempts = sorted(int(x) for x in os.listdir(paths.step_dir(s["id"])) if x.isdigit())
            except FileNotFoundError:
                attempts = []
        out["steps"].append({"id": s["id"], "status": s["status"], "latest_attempt": n,
                             "attempts": len(attempts), "on_fail_count": s.get("on_fail_count", 0),
                             "reason": s.get("reason")})
    return out


def _notices(log):
    """Readiness T1: what the conversation relays once — the latest notice of each kind (an attended child of an
    epic, P3). [{kind, note}]"""
    latest = {}
    for line in log:
        kind = (line.get("data") or {}).get("kind")
        if line.get("event") == codes.LogEvent.WARNING.value and kind == driver.EPIC_CHILD_NOTICE:
            latest[kind] = {"kind": kind, "note": line.get("note")}
    return list(latest.values())


def _stage3_lines(rep):
    """The stage-3 part of the status text (§2.12): nothing when nothing happened."""
    lines = []
    if rep.get("requests"):
        lines.append("- step requests:")
        lines += [f"  {q['from_step']:<16} {q['op']} {q['step']} ({q['trigger']}): {q['outcome']}"
                  + (f" ({q['reason']})" if q.get("reason") else "") for q in rep["requests"]]
    irr = rep.get("irreversible") or {}
    if irr.get("detected"):
        lines.append("- irreversible changes:")
        for d in irr["detected"]:
            mark = "WAITING for a human" if d in irr["waiting"] else d["level"]
            lines.append(f"  {d['category']:<22} {d['code'] or d['path']} (step {d['step']}): {mark}"
                         + (f" - lowered by the settings from {d['default_level']}" if d["lowered"] else ""))
    if rep.get("raised"):
        lines.append("- raised sessions:")
        for r in rep["raised"]:
            up = [f"{k} {v[0]} -> {v[1]}" for k, v in (r.get("raised") or {}).items() if v]
            lines.append(f"  {r['step']:<16} attempt {r['attempt']}: {', '.join(up) or 'nothing left to raise'}"
                         + (" (top of the allow-list)" if r.get("capped") else ""))
    if rep.get("included_fixes"):
        lines.append("- included fixes (they block an acceptance criterion):")
        lines += [f"  {f['id']:<4} {f['kind']} at {f['where']} - handled by {f['handled_by']}, "
                  f"{f['verdict'] or 'not judged yet'}" for f in rep["included_fixes"]]
    if rep.get("followups"):
        lines.append("- follow-ups:")
        for f in rep["followups"]:
            what = "local record only" if f["private_path"] else "dry run" if f["dry_run"] else f"issue {f['number']}"
            lines.append(f"  {f['key']:<14} {f['kind']} {f['disposition']}: {what}")
    if rep.get("security_findings"):
        lines.append("- security findings (engine-local - they were never written to GitHub):")
        lines += ["  " + x for x in rep["security_findings"].rstrip("\n").split("\n")]
    return lines


def _format_status(rep):
    lines = [f"Issue {rep['repo']}#{rep['issue']}"]
    if rep["running"]:
        lines.append(f"- engine running (pid {rep['lock'].get('pid')})")
    elif rep["rc"] is not None:
        lines.append(f"- engine finished, exit {rep['rc']}")
    for n in rep.get("notices") or ():
        lines.append(f"- notice: {n['note']}")
    if rep["state"] is None:
        lines.append("- no engine state (not started)")
        refused = [e for e in rep["last_events"] if (e.get("data") or {}).get("refused")]
        if refused:
            lines.append(f"- refused: {refused[-1].get('note') or refused[-1].get('code')}")
    else:
        if rep["stop"]:
            st = rep["stop"]
            lines.append(f"- stopped: {st['status']} — {st['reason']} at {st.get('step') or '—'}"
                         + (f" ({st['note']})" if st.get("note") else ""))
            rec = st.get("recommendation")
            if rec:
                lines.append(f"- leader recommendation: {rec['answer']}" + (f" {rec['step']}" if rec.get("step") else "")
                             + f" (reason {rec['reason']})" + (f" — {rec['note']}" if rec.get("note") else ""))
            failed = st.get("leader_failed")
            if failed:
                lines.append(f"- the leader could not answer: {failed['code']}"
                             + (f" / {failed['detail']}" if failed.get("detail") else ""))
        q = rep["question"]
        if q and q.get("leader_turn"):
            lines.append("- waiting for the leader: resume WITHOUT an answer calls the leader again (exit 11)")
        elif q and q.get("allowed_answers"):
            lines.append(f"- answers: {', '.join(q['allowed_answers'])}")
        elif q and q.get("crashed"):
            lines.append(f"- the engine died while `{q['step']}` was running — resume reruns it")
        if rep["pr"]:
            lines.append(f"- pull request {rep['pr']['number']} {rep['pr'].get('url') or ''}".rstrip())
        if rep.get("closed"):
            lines.append(f"- closed as decided ({rep['closed']['reason']}) — no pull request")
        if rep.get("leader_calls"):
            lines.append("- leader decisions:")
            for c in rep["leader_calls"]:
                what = c.get("answer") or f"no answer ({c.get('failed') or 'stopped'})"
                lines.append(f"  {c['situation']:<26} {what}" + (f" {c['step']}" if c.get("step") else "")
                             + (f" ({c['reason']})" if c.get("reason") else "")
                             + (f" ${c['cost_usd']:.2f}" if isinstance(c.get("cost_usd"), (int, float)) else ""))
        lines += _stage3_lines(rep)
        t = rep["totals"] or {}
        lines.append(f"- attempts {t.get('attempts', 0)}, cost ${t.get('cost_usd', 0.0):.2f}, "
                     f"warnings {t.get('warnings', 0)}")
        for s in rep["steps"]:
            lines.append(f"  {s['id']:<16} {s['status']:<12} attempt {s['latest_attempt'] or '—'}"
                         + (f"  on_fail {s['on_fail_count']}" if s["on_fail_count"] else ""))
    lines.append(f"- records: {rep['records']}")
    return "\n".join(lines) + "\n"


def _status(args, environ, out, stage=None):
    paths = _paths(args, environ)
    deadline = time.time() + max(0.0, args.wait)
    while args.wait > 0 and lifecycle.read_rc(paths) is None and time.time() < deadline:
        time.sleep(min(WAIT_POLL_S, max(0.0, deadline - time.time())))
    rep = status_report(paths, stage)
    if args.json:
        out.write(json.dumps(rep, ensure_ascii=False, indent=2, default=str) + "\n")
    else:
        out.write(_format_status(rep))
    rc = rep["rc"]
    if rep["running"] or rc is None:
        return EXIT_OK
    return rc if rc in (EXIT_OK, EXIT_LOCKED, EXIT_REFUSED, EXIT_NEEDS_HUMAN, EXIT_NEEDS_LEADER) else EXIT_NEEDS_HUMAN


# --- owned (readiness T1 P5) ---------------------------------------------------------------

def owned_report(paths, gh):
    """{owned, records, remote_branch, open_pr, summary_comment, problem}: the three marks of an Issue the engine
    works on — engine records on this machine (state.json), its branch gld/<N> on the remote (and that branch's open
    pull request), the engine's summary comment on the Issue. `owned` is True when one is there, False when none
    is, None when a GitHub fact could not be read (`problem` says which) — the stage commands refuse on True and
    on None (_preflight.md Section 0)."""
    try:                                                 # lexists first: a read never creates the engine home
        records = os.path.lexists(paths.state) and store.load_state(paths) is not None
    except (store.CorruptFile, store.FormatMismatch, fsafe.UnsafePath):
        records = True                                   # a broken state.json is still the engine's
    rep = {"repo": paths.repo, "issue": paths.issue, "owned": None, "records": records, "remote_branch": None,
           "open_pr": None, "summary_comment": None, "problem": None}
    try:
        remote = sprinttracker.remote_state(gh, paths.issue)
        rep["remote_branch"], rep["open_pr"] = remote["branch"], remote["open_pr"]
        rows = gh.api("GET", gh.path("issues", paths.issue, "comments"), paginate=True) or []
        if not isinstance(rows, list):
            raise github.GhError("comments: not a list")
        ids = [c.get("id") for c in rows if isinstance(c, dict)
               and (c.get("body") or "").split("\n", 1)[0].strip() == github.SUMMARY_MARKER]
        rep["summary_comment"] = min(ids) if ids else None
    except github.GhError as e:
        rep["problem"] = str(e)[:300]
    marks = records or bool(rep["remote_branch"]) or rep["open_pr"] is not None or rep["summary_comment"] is not None
    rep["owned"] = True if marks else (None if rep["problem"] else False)
    return rep


def _owned(args, environ, out, units=None):
    paths = _paths(args, environ)
    gh = (units or driver.Units()).make_gh(args.repo, environ, _plugin_root())
    rep = owned_report(paths, gh)
    if args.json:
        out.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n")
    elif rep["owned"]:
        what = [w for w, on in (("engine records on this machine", rep["records"]),
                                (f"{driver.BRANCH_PREFIX}{paths.issue} on the remote", rep["remote_branch"]),
                                (f"its pull request #{rep['open_pr']}", rep["open_pr"] is not None),
                                ("the engine's summary comment", rep["summary_comment"] is not None)) if on]
        out.write(f"engine Issue {paths.repo}#{paths.issue}: {', '.join(what)} — use /gld resume {paths.issue} "
                  f"(state: /gld status {paths.issue})\n")
    elif rep["owned"] is None:
        out.write(f"cannot tell whether the engine works on {paths.repo}#{paths.issue}: {rep['problem']}\n")
    else:
        out.write(f"not an engine Issue: {paths.repo}#{paths.issue}\n")
    return EXIT_OK if rep["owned"] is False else EXIT_REFUSED


def _taken(args, environ, out, units=None):
    """`engine.py taken`: {closing_prs: {N: [{number, head, via}]}, engine_branches: [N]}. Exit 0; 4 when GitHub
    does not answer (sprint plan then decides nothing from it)."""
    gh = (units or driver.Units()).make_gh(args.repo, environ, _plugin_root())
    try:
        closing, branches = github.open_closing_map(gh), sprinttracker.engine_branches(gh)
    except github.GhError as e:
        out.write(f"refused: cannot tell which Issues are taken: {e}\n")
        return EXIT_REFUSED
    if args.json:
        out.write(json.dumps({"closing_prs": {str(n): v for n, v in sorted(closing.items())},
                              "engine_branches": branches}, ensure_ascii=False, indent=2) + "\n")
        return EXIT_OK
    taken = sorted(set(closing) | set(branches))
    out.write(f"taken Issues of {args.repo}: {len(taken)}\n")
    for n in taken:
        what = []
        if n in closing:
            what.append("open pull request " + ", ".join("#%d (%s)" % (p["number"], p["head"]) for p in closing[n]))
        if n in branches:
            what.append(f"{driver.BRANCH_PREFIX}{n} on the remote")
        out.write(f"  #{n}: {' · '.join(what)}\n")
    return EXIT_OK


# --- dev / resume --------------------------------------------------------------------------

def _note_path(paths):
    return os.path.join(paths.issue_dir, NOTE_FILE)


def _read_note(path):
    with open(path, "rb") as f:
        data = f.read(NOTE_MAX_BYTES + 1)
    if len(data) > NOTE_MAX_BYTES:
        raise ValueError(f"the note file is larger than {NOTE_MAX_BYTES} bytes")
    return data.decode("utf-8")


def _pr_mode(args):
    return bool(args.pr_review or args.dismiss)


def _mode_problem(args, stage):
    """Stage 3: --pr-review / --dismiss stand alone. None when the arguments fit together."""
    if args.reason_file and not args.dismiss:
        return "--reason-file goes with --dismiss only"
    if not _pr_mode(args):
        return None
    if stage < 3:
        return "--pr-review and --dismiss exist from stage 3"
    if args.pr_review and args.dismiss:
        return "--pr-review and --dismiss are two different resumes"
    if args.allow_test_change or args.sprint:
        return "--pr-review / --dismiss take no --allow-test-change or --sprint"
    if args.answer or args.step or args.close_reason or args.template or args.note_file or args.reason:
        return "--pr-review / --dismiss take no answer, step, note or reason code"
    if args.dismiss and not (args.reason_file or args.note_from_records):
        return "--dismiss needs --reason-file"
    return None


def _stage4_problem(args, stage, note):
    """Stage 4: --allow-test-change (H21) and --sprint (D6) of a resume. None when the arguments fit together."""
    if args.sprint:
        if stage < codes.STAGE4:
            return "--sprint exists from stage 4"
        if not args.foreground or args.answer != codes.LeaderAnswer.RERUN.value or args.step or args.allow_test_change:
            return "--sprint goes with --foreground --answer rerun and nothing else"
    if args.allow_test_change:
        if stage < codes.STAGE4:
            return "--allow-test-change exists from stage 4"
        return testchange.args_problem(args.answer, args.step, args.allow_test_change, note)
    return None


def _check_resume(args, paths, out, stage=None):
    """Validate a resume before detaching. Returns an exit code or None (go on).

    Stage 2: a needs_leader stop takes no answer (D24 — the engine calls the leader again);
    `--close-reason` goes with close-as-decided only and close-as-decided needs it (D17)."""
    stage = defaults.ENGINE_STAGE if stage is None else stage
    if args.close_reason and args.answer != codes.LeaderAnswer.CLOSE_AS_DECIDED.value:
        out.write("refused: --close-reason goes with --answer close-as-decided only\n")
        return EXIT_REFUSED
    if args.answer == codes.LeaderAnswer.CLOSE_AS_DECIDED.value and not args.close_reason:
        out.write(f"refused: close-as-decided needs --close-reason {'|'.join(codes.CloseReason.values())}\n")
        return EXIT_REFUSED
    if args.template and (args.answer != codes.LeaderAnswer.PLAN.value or stage < 3):
        out.write("refused: --template goes with --answer plan only (from stage 3)\n")
        return EXIT_REFUSED
    holder = lifecycle.lock_holder(paths)
    if holder is not None:
        out.write(f"locked: an engine (pid {holder.get('pid')}, issue {holder.get('issue')}) is running\n")
        return EXIT_LOCKED
    try:
        state = store.load_state(paths)
    except store.FormatMismatch as e:
        out.write(f"refused: {e}\n")
        return EXIT_REFUSED
    if state is None:
        out.write("refused: there is no engine state for this Issue (run dev first)\n")
        return EXIT_REFUSED
    if _pr_mode(args):
        problem = lifecycle.pr_review_problem(state) if args.pr_review else \
            lifecycle.dismiss_problem(paths, state, args.dismiss)
        if problem:
            out.write(f"refused: {problem}\n")
            return EXIT_REFUSED
        return None
    q = lifecycle.pending_question(state, stage, soft_answered=lifecycle.soft_budget_answered(paths))
    if q is None:
        if args.answer:
            out.write("refused: the Issue is not stopped — nothing to answer\n")
            return EXIT_REFUSED
        return None
    if q["crashed"]:
        if args.answer:
            out.write("refused: the engine died mid-step; resume without --answer reruns that step\n")
            return EXIT_REFUSED
        return None
    if q.get("leader_turn"):
        if args.answer:
            out.write(f"refused: the leader answers the {q['reason']} stop (needs_leader) — resume without "
                      "--answer calls the leader again\n")
            return EXIT_REFUSED
        return None
    if not args.answer:
        out.write(f"refused: stopped for {q['reason']} at {q.get('step') or '—'}; "
                  f"--answer one of: {', '.join(q['allowed_answers'])}\n")
        return EXIT_REFUSED
    if args.answer not in q["allowed_answers"]:
        out.write(f"refused: answer {args.answer!r} is not allowed for {q['reason']}; "
                  f"allowed: {', '.join(q['allowed_answers'])}\n")
        return EXIT_REFUSED
    return None


def _detach(paths, argv_tail, environ, out):
    root = store._root(paths)
    fsafe.make_dirs(paths.issue_dir, root=root)
    if lifecycle.lock_holder(paths) is not None:
        out.write("locked: an engine is already running for this Issue or repository\n")
        return EXIT_LOCKED
    argv = lifecycle.engine_argv(_plugin_root(), argv_tail + ["--foreground"])
    pid = lifecycle.spawn_detached(argv, paths.engine_log, paths.engine_rc, env=environ, cwd=os.getcwd())
    out.write(f"engine started (pid {pid})\nlog: {paths.engine_log}\nrc: {paths.engine_rc}\n")
    return EXIT_OK


def _dev(args, environ, out, units=None, stage=None):
    paths = _paths(args, environ)
    tail = ["dev", "--repo", args.repo, "--issue", str(args.issue), "--mode", args.mode]
    checkout = os.path.realpath(args.checkout or os.getcwd())
    tail += ["--checkout", checkout]
    stage = defaults.ENGINE_STAGE if stage is None else stage
    start = _start_options(args)
    if start is not None:
        problem = start.problem(args.mode, stage) or (
            None if args.foreground else "a sprint member runs in the foreground (the supervisor starts it)")
        if problem:
            out.write(f"refused: {problem}\n")
            return EXIT_REFUSED
    if not args.foreground:
        return _detach(paths, tail, environ, out)
    return driver.run_issue(args.repo, args.issue, args.mode, _plugin_root(), environ, checkout=checkout,
                            units=units, out=out, stage=stage, **({"start": start} if start is not None else {}))


def _start_options(args):
    """driver.StartOptions of the hidden sprint arguments, or None when none was given."""
    if args.base_sha is None and args.base_branch is None and not args.draft and args.sprint is None:
        return None
    return driver.StartOptions(args.base_sha, args.base_branch, args.draft, args.sprint)


def _resume(args, environ, out, units=None, stage=None):
    paths = _paths(args, environ)
    note = ""
    problem = _mode_problem(args, defaults.ENGINE_STAGE if stage is None else stage)
    if problem:
        out.write(f"refused: {problem}\n")
        return EXIT_REFUSED
    note_file = args.reason_file or args.note_file
    if args.note_from_records:
        try:
            note = _read_note(_note_path(paths))
        except FileNotFoundError:
            note = ""
    elif note_file:
        try:
            note = _read_note(note_file)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            out.write(f"refused: cannot read the note file: {e}\n")
            return EXIT_REFUSED
    problem = _stage4_problem(args, defaults.ENGINE_STAGE if stage is None else stage, note)
    if problem:
        out.write(f"refused: {problem}\n")
        return EXIT_REFUSED
    if args.foreground and (args.close_reason and args.answer != codes.LeaderAnswer.CLOSE_AS_DECIDED.value):
        out.write("refused: --close-reason goes with --answer close-as-decided only\n")
        return EXIT_REFUSED
    if args.foreground and args.template and args.answer != codes.LeaderAnswer.PLAN.value:
        out.write("refused: --template goes with --answer plan only (from stage 3)\n")
        return EXIT_REFUSED
    if not args.foreground:
        rc = _check_resume(args, paths, out, stage)
        if rc is not None:
            return rc
        tail = ["resume", "--repo", args.repo, "--issue", str(args.issue)]
        if args.answer:
            tail += ["--answer", args.answer]
        if args.step:
            tail += ["--step", args.step]
        if args.reason:
            tail += ["--reason", args.reason]
        if args.close_reason:
            tail += ["--close-reason", args.close_reason]
        if args.template:
            tail += ["--template", args.template]
        for p in args.allow_test_change or ():
            tail += ["--allow-test-change", p]
        if args.pr_review:
            tail += ["--pr-review"]
        if args.dismiss:
            tail += ["--dismiss", args.dismiss]
        if note or args.dismiss:
            root = store._root(paths)
            fsafe.make_dirs(paths.issue_dir, root=root)
            fsafe.write_text(_note_path(paths), note, root=root, mode=0o600)
            tail += ["--note-from-records"]
        return _detach(paths, tail, environ, out)
    answer = None
    if args.answer:
        answer = {"answer": args.answer, "step": args.step, "reason": args.reason, "note": note,
                  "close_reason": args.close_reason, "template": args.template}
        if args.allow_test_change:
            answer["allow_test_change"] = list(args.allow_test_change)
        if args.sprint:
            answer["sprint"] = args.sprint
    elif args.pr_review:
        answer = {"pr_review": True}
    elif args.dismiss:
        answer = {"dismiss": args.dismiss, "note": note}
    rc = driver.run_issue(args.repo, args.issue, codes.RunMode.ATTENDED.value, _plugin_root(), environ,
                          units=units, out=out, answer=answer, stage=defaults.ENGINE_STAGE if stage is None else stage)
    if args.note_from_records:
        try:
            os.unlink(_note_path(paths))
        except FileNotFoundError:
            pass
    return rc


def _canary_summary(rec):
    line = f"{rec['kind']} canary {rec['key']}: {'PASS' if rec.get('ok') else 'FAIL'}"
    if rec.get("cost_usd") is not None:
        line += f" (cost ${rec['cost_usd']:.4f})"
    lines = [line]
    for i, (want, got) in sorted((rec.get("failed") or {}).items()):
        lines.append(f"  - {i}: expected {want}, got {got}")
    for n in rec.get("notes") or []:
        lines.append(f"  note: {n}")
    for i, why in sorted((rec.get("unprobed") or {}).items()):
        lines.append(f"  unprobed {i}: {why}")
    return "\n".join(lines) + "\n"


def _canary(args, environ, out):
    """`engine.py canary` (P4): role canary (paid) and/or srt canary (free) → records, exit 0/4."""
    home = pathsmod.engine_home(environ)
    os.makedirs(home, mode=0o700, exist_ok=True)
    plugin_root = _plugin_root()
    recs = []
    cfg = {}
    if args.config:
        with open(args.config, "rb") as f:
            cfg = repoconfig.RepoConfig.from_text(f.read().decode("utf-8")).raw
    exc = cfg.get("sandbox_exceptions") or {}
    user_tmp = driver._user_tmp() if defaults.USER_TMP_TOKEN in (exc.get("allow_write") or []) else None
    if not args.srt_only:
        classes = [args.role_class] if args.role_class else [codes.RoleClass.WORK.value, codes.RoleClass.JUDGE.value]
        cap = args.max_usd if args.max_usd is not None else defaults.CANARY_TOTAL_MAX_USD
        spent = 0.0
        with canaryrun.role_canary_lock(home):            # K8-1: never beside an engine's own canary
            for rc in classes:
                work = rc == codes.RoleClass.WORK.value   # P5 F2: the developer's key includes the exceptions
                rec = canaryrun.run_role_canary(rc, environ, plugin_root, home, model=args.model, effort=args.effort,
                                                max_total_usd=cap, spent_before=spent,
                                                budget_probe=args.budget_probe and rc == classes[-1],
                                                keep_layout=args.keep_layout, out=None if args.json else out,
                                                sandbox_exceptions=(exc or None) if work else None,
                                                user_tmp=user_tmp if work else None)
                spent += float(rec.get("cost_usd") or 0.0)
                recs.append(rec)
    if not args.no_srt:
        srt = driver.default_srt_bin(pathsmod.EnginePaths(home, "gld/canary", 1), environ)
        if srt is None:
            out.write("refused: srt is not installed (GLD_SRT_BIN, ~/.gld/srt or PATH)\n")
            return EXIT_REFUSED
        recs.append(canaryrun.run_srt_canary(srt, home, sandbox_exceptions=exc or None,
                                             registry_hosts=cfg.get("registry_hosts"),
                                             secret_paths=cfg.get("secret_paths"), user_tmp=user_tmp,
                                             base_env=environ, out=None if args.json else out))
    if args.json:
        out.write(json.dumps(recs, ensure_ascii=False, indent=2) + "\n")
    else:
        for r in recs:
            out.write(_canary_summary(r))
    return EXIT_OK if recs and all(r.get("ok") is True for r in recs) else EXIT_REFUSED


# --- stage 4: sprint · init · base-check -------------------------------------------------------------

def _outside(environ):
    """(srt path or None, user temp folder or None) — what the sprint / init / base-check modules may not look up
    themselves (they import no driver)."""
    home = pathsmod.engine_home(environ)
    return driver.default_srt_bin(pathsmod.EnginePaths(home, "gld/canary", 1), environ), driver._user_tmp()


def _sprint(args, environ, out, stage, units=None):
    home = pathsmod.engine_home(environ)
    sp = pathsmod.SprintPaths(home, args.repo, args.tracker)
    if args.action == "status":
        deadline = time.time() + max(0.0, args.wait)
        while args.wait > 0 and sprintmod.read_rc(sp) is None and time.time() < deadline:
            time.sleep(min(WAIT_POLL_S, max(0.0, deadline - time.time())))
        return sprintmod.status(sp, out, as_json=args.json)
    if args.action == "report":
        return sprintmod.report(sp, out, as_json=args.json)
    if args.action == "check":
        gh = (units or driver.Units()).make_gh(args.repo, environ, _plugin_root())
        return sprintmod.check(gh, args.tracker, out, home=home)
    if args.action == "stop":
        return sprintmod.stop(sp, out)
    if args.window is not None:
        sprintdag.parse_window(args.window)                      # a bad window is refused here, before detaching
    checkout = os.path.realpath(args.checkout)
    if not args.foreground:
        return _sprint_detach(args, sp, checkout, environ, out)
    srt, user_tmp = _outside(environ)
    options = sprintmod.SprintOptions(
        repo=args.repo, tracker=args.tracker, checkout=checkout, plugin_root=_plugin_root(),
        engine_home=home, environ=environ, out=out, window=args.window, allow_red_base=args.allow_red_base,
        take_over=args.take_over, srt=srt, user_tmp=user_tmp, stage=stage)
    return sprintmod.run(options, units or sprintmod.default_units(
        lambda: _sprint_self_check(args.repo, args.tracker, home, environ, out, stage)))


def _sprint_self_check(repo, tracker, home, environ, out, stage):
    """D3: the engine's own start checks (srt, the gate hook), once for the whole sprint. (ok, message)."""
    env = driver.IssueEnv(pathsmod.EnginePaths(home, repo, tracker), repo, tracker, codes.RunMode.UNATTENDED.value,
                          _plugin_root(), environ, driver.Units(), stage, out)
    ok, message = env.units.self_check(env)
    return (ok, message) if not ok else canary.check_hook_script(_plugin_root())


def _sprint_detach(args, sp, checkout, environ, out):
    """The supervisor outlives the conversation (lifecycle.spawn_detached). §2.6: with a window in effect and
    `caffeinate` on PATH it runs under `caffeinate -i` (no idle sleep; a closed lid still sleeps)."""
    holder = lifecycle.sprint_lock_holder(sp)
    if holder is not None:
        out.write(f"locked: a supervisor (pid {holder.get('pid')}, sprint {holder.get('issue')}) runs for this repository\n")
        return EXIT_LOCKED
    argv = ["sprint", "run", "--repo", args.repo, "--tracker", str(args.tracker), "--checkout", checkout]
    argv += ["--window", args.window] if args.window is not None else []
    argv += [flag for flag, on in (("--allow-red-base", args.allow_red_base), ("--take-over", args.take_over)) if on]
    argv = lifecycle.engine_argv(_plugin_root(), argv + ["--foreground"])
    window = sprintdag.parse_window(args.window) if args.window is not None else (store.load_sprint(sp) or {}).get("window")
    awake = shutil.which("caffeinate", path=environ.get("PATH", "")) if window else None
    if awake:
        argv = [os.path.realpath(awake), "-i"] + argv
    fsafe.make_dirs(sp.dir, root=store._root(sp))
    pid = lifecycle.spawn_detached(argv, sp.supervisor_log, sp.supervisor_rc, env=environ, cwd=checkout)
    out.write(f"sprint supervisor started (pid {pid})" + (f", window {window}" if window else "")
              + f"\nlog: {sp.supervisor_log}\nrc: {sp.supervisor_rc}\n")
    return EXIT_OK


def _stage4(args, environ, out, stage, units=None):
    """sprint · init · base-check: refused before stage 4; a shell that has no body yet refuses too."""
    if stage < codes.STAGE4:
        out.write(f"refused: `{args.command}` exists from stage 4 (this engine runs stage {stage})\n")
        return EXIT_REFUSED
    try:
        if args.command == "sprint":
            return _sprint(args, environ, out, stage, units)
        if args.command == "init" and args.action in initharness.ACTIONS:
            gh = None
            if args.action == "migrate" and not args.repo.startswith("local/"):
                try:
                    gh = (units or driver.Units()).make_gh(args.repo, environ, _plugin_root())
                except (github.GhError, ValueError):
                    gh = None                                    # the labels line then says why they were not read
            return initharness.run(args.action, args, environ, out, plugin_root=_plugin_root(), gh=gh)
        srt, user_tmp = _outside(environ)
        kw = {"plugin_root": _plugin_root(), "srt": srt, "user_tmp": user_tmp}
        if args.command == "init":
            return initconfig.run(args.action, args, environ, out, **kw)
        return basecheck.run_cli(args, environ, out, **kw)
    except NotImplementedError as e:
        out.write(f"refused: `{args.command}` is not available in this engine ({e})\n")
        return EXIT_REFUSED


# --- readiness R1: incidents · records -------------------------------------------------------------------------

def _mb(n):
    return f"{(n or 0) / 1048576:.1f} MB"


def _incident_line(s):
    if "problem" in s:
        return f"  [?] {s['slug']} — unreadable: {s['problem']}\n      {s['path']}\n"
    last = s["last"]
    where = f"{last['repo']}" + (f"#{last['issue']}" if last.get("issue") else f" sprint #{last['tracker']}")
    fix = {"unfixed": "", "fixed": f" · fixed ({', '.join(s['fixes'])}) — the next retro removes it",
           "recurred": f" · RECURRED after {', '.join(s['fixes'])}"}[s["fix_status"]]
    return (f"  [{s['kind']}] {s['signature']} — {s['count']}x · last {where}"
            + (f" {last['step']}" if last.get("step") else "") + f" ({(last.get('at') or '')[:10]}){fix}\n"
            + f"      {s['path']}\n")


def _incidents(args, environ, out, units=None):
    home = pathsmod.engine_home(environ)
    if args.action == "list":
        rows = incidents.summaries(home)
        if args.json:
            out.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        else:
            kinds = {k: sum(1 for r in rows if r.get("kind") == k) for k in incidents.KINDS}
            out.write(f"engine incidents: {len(rows)} (defect {kinds['defect']} · suspect {kinds['suspect']})\n")
            for r in rows:
                out.write(_incident_line(r))
        return EXIT_OK
    rows = incidents.prune(home, apply=args.apply)
    if args.json:
        out.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        return EXIT_OK
    for r in rows:
        if "problem" in r:
            out.write(f"kept (unreadable): {r['slug']} — {r['problem']}\n")
            continue
        fixes = " · ".join(f"{f['id']} ({f['version']}" + (f" {f['commit']}" if f["commit"] else "") + f") {f['summary']}"
                           for f in r["fixes"])
        if r["action"] in ("removed", "would-remove"):
            out.write(f"{r['action']}: {r['signature']} — {fixes}\n")
        elif r["fix_status"] == incidents.FIX_RECURRED:
            out.write(f"kept, recurred: {r['signature']} — after {', '.join(f['id'] for f in r['fixes'])}, "
                      f"occurrence(s) {', '.join(map(str, r['recurred']))} · {r['path']}\n")
        else:
            out.write(f"kept: {r['signature']} (not in the fixed-defects list)\n")
    return EXIT_OK


def _member_pr_facts(gh):
    def facts(issue, state):
        return sprinttracker.member_prs(gh, issue)
    return facts


def _records(args, environ, out, units=None):
    home = pathsmod.engine_home(environ)
    if args.action == "prune":
        gh = (units or driver.Units()).make_gh(args.repo, environ, _plugin_root())
        try:
            rows = retention.prune_members(home, args.repo, args.tracker, _member_pr_facts(gh), apply=args.apply,
                                           only=args.issue)
        except retention.Refused as e:
            out.write(f"refused: {e}\n")
            return EXIT_REFUSED
        if args.json:
            out.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
            return EXIT_OK
        for r in rows:
            prs = ", ".join(f"#{p['number']} {p['state']}" for p in r["prs"]) or "—"
            out.write(f"#{r['issue']}: {r['action']} ({r['why']}) — records {_mb(r['records_bytes'])}, "
                      f"tmp {_mb(r['tmp_bytes'])} · PR {prs}\n")
        return EXIT_OK
    if args.days < 1:
        out.write("refused: --days must be at least 1\n")
        return EXIT_REFUSED
    if args.apply != bool(args.pick):
        out.write("refused: --apply goes with one or more --pick OWNER/REPO#N (and --pick with --apply)\n")
        return EXIT_REFUSED
    if args.apply:
        rows = retention.remove_stale(home, args.pick, days=args.days)
        if args.json:
            out.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        else:
            for r in rows:
                out.write(f"{r['pick']}: {r['action']}" + (f" ({r['why']})" if r["why"] else "")
                          + (f" — {_mb(sum(r['removed'].values()))}" if r["removed"] else "") + "\n")
        return EXIT_OK if all(r["action"] == "removed" for r in rows) else EXIT_REFUSED
    rep = retention.stale(home, days=args.days)
    if args.json:
        out.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n")
        return EXIT_OK
    total = sum(i["records_bytes"] + i["tmp_bytes"] for i in rep["items"])
    out.write(f"engine records untouched for more than {rep['days']} days: {len(rep['items'])} ({_mb(total)})\n")
    for n, i in enumerate(rep["items"], 1):
        out.write(f"  {n}. {i['pick']} — last activity {i['last_activity'][:10]} ({i['age_days']} days) · "
                  f"{_mb(i['records_bytes'] + i['tmp_bytes'])}\n")
    for k in rep["kept"]:
        out.write(f"  kept: {k['pick']} ({k['why']})\n")
    return EXIT_OK


# --- readiness T1 R4-14: one channel per repository ---------------------------------------------------------------

WRITE_COMMANDS = ("dev", "resume", "sprint", "init", "base-check")
"""The engine commands that act on a repository: refused at their entry when the repository's active channel is the
other one (sprint: `run` only — status / report / check read, stop only stops)."""


def _entry_checkout(args, environ):
    """The checkout a write command acts on, or None (nothing to check)."""
    if args.command == "sprint":
        return args.checkout if args.action == "run" else None
    if args.command == "resume":
        try:
            state = store.load_state(_paths(args, environ))
        except (store.CorruptFile, store.FormatMismatch, fsafe.UnsafePath, ValueError):
            return None                                   # the resume path itself refuses it
        return ((state or {}).get("git") or {}).get("main_checkout")
    return getattr(args, "checkout", None) or os.getcwd()


def _channel_entry(args, environ, out):
    """None, or EXIT_REFUSED after saying why (the repository's active channel is not this one)."""
    if args.command not in WRITE_COMMANDS:
        return None
    checkout = _entry_checkout(args, environ)
    problem = channelmod.entry_problem(os.path.realpath(checkout), environ) if checkout else None
    if problem:
        out.write(f"refused: {problem}\n")
        return EXIT_REFUSED
    return None


def _channel(args, environ, out):
    checkout = os.path.realpath(args.checkout or os.getcwd())
    if args.action == "show":
        v = channelmod.verdict(checkout, environ)
        out.write(channelmod.show_json(v) if args.json else channelmod.format_show(v))
        return EXIT_OK if v["allowed"] else EXIT_REFUSED
    try:
        rep = channelmod.switch(args.target, args.repo, checkout, environ, _plugin_root(), dry_run=args.dry_run)
    except channelmod.ChannelError as e:
        out.write(f"refused: {e}\n")
        return EXIT_REFUSED
    out.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n" if args.json else channelmod.format_switch(rep))
    return EXIT_REFUSED if rep["refused"] else EXIT_OK


def main(argv=None, environ=None, out=None, units=None, stage=None):
    """Entry point; returns an exit code. `stage` = the engine stage (default
    defaults.ENGINE_STAGE, 2 since Q6 — stage-1 tests pass 1, D21)."""
    environ = dict(os.environ if environ is None else environ)
    out = out or sys.stdout
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return EXIT_USAGE if e.code not in (0, None) else EXIT_OK
    try:
        refused = _channel_entry(args, environ, out)
        if refused is not None:
            return refused
        if args.command == "channel":
            return _channel(args, environ, out)
        if args.command == "status":
            return _status(args, environ, out, stage)
        if args.command == "owned":
            return _owned(args, environ, out, units)
        if args.command == "taken":
            return _taken(args, environ, out, units)
        if args.command == "dev":
            return _dev(args, environ, out, units, stage)
        if args.command == "resume":
            return _resume(args, environ, out, units, stage)
        if args.command == "canary":
            return _canary(args, environ, out)
        if args.command in ("sprint", "init", "base-check"):
            return _stage4(args, environ, out, defaults.ENGINE_STAGE if stage is None else stage, units)
        if args.command in ("incidents", "records"):
            try:
                return (_incidents if args.command == "incidents" else _records)(args, environ, out, units)
            except fsafe.UnsafePath as e:
                out.write(f"refused: {e}\n")
                return EXIT_REFUSED
    except (ValueError, OSError, repoconfig.ConfigError, store.CorruptFile, store.FormatMismatch,
            canaryrun.CanaryRunError) as e:
        out.write(f"refused: {e}\n")
        return EXIT_REFUSED
    return EXIT_USAGE
