"""workflows.dev.flake — a red suite with at most two failing tests is re-run once, those tests only (0.102.5).

#1945 (word_app): a load-sensitive performance test failed once in the full `--concurrency=12` suite and passed alone
(~15 ms); `--fail-fast` then aborted the other runners and the flutter tool's temp-dir cleanup printed
`PathNotFoundException: Deletion failed` — the suite was read as red and a person had to stop the loop-back by hand.

The rule (deterministic, no judgment):
* only a red, finished run (no timeout) whose failing tests the engine can NAME with their file — flutter/dart from the
  machine report (`--file-reporter json:`), pytest `FAILED|ERROR path::name`, unittest `FAIL:/ERROR: name
  (mod.Class.name)` — and that number is 1 or 2; a compile / collection error (`checks.LOAD_ERROR_RES`) is never
  re-run. 0.102.6 (review-0102-5 B1): every failure the runner COUNTS must be named — the summary's failed + error
  count equals the named tests, and a flutter hidden test (`setUpAll`/`tearDownAll`) that failed makes it ineligible;
* each failing test runs ONCE more, alone, with the runner's exact single-test command, in the SAME temp tree, sandbox
  and env as the suite (`run(cmd)` — `ports.suite_in_tree` binds it);
* 0.102.6 (B1): ALWAYS, besides the failing tests passing alone, the whole suite — every command of `commands.test`,
  not only the first (the first red command stopped the rest: they never ran) — runs once more and must be green
  (`run_suite()`). An order-dependent failure (red in the suite every time, green alone) stays red there;
* green → the result carries `flake` {tests, reruns, full_rerun} — the stage records a flake note (journal event +
  decision block, a grading-sheet row `triggered: flake` — `grade.select`) and goes on as green; still red → `flake` =
  None and nothing is masked. A confirmed `wrong` on a flake row sets `group.flake.conservative`: from then on a flake
  never turns a red suite green (`off(p)`).
"""

import json
import re

from guildcore import checks as CH

MAX_FLAKY = 2


def runner_of(cmds):
    from workflows.dev import effective as EFF
    return EFF.runner_of({"commands": {"test": list(cmds or [])}})


def _flutter_failing(report):
    """[(path, name)] of the non-hidden tests that ended `failure`/`error` in flutter's json report, or None."""
    if not report:
        return None
    suites, tests, out = {}, {}, []
    for ln in report.split("\n"):
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        t = ev.get("type")
        if t == "suite":
            s = ev.get("suite") or {}
            suites[s.get("id")] = s.get("path")
        elif t == "testStart":
            te = ev.get("test") or {}
            tests[te.get("id")] = (te.get("name"), te.get("suiteID"))
        elif t == "testDone" and ev.get("result") in ("failure", "error"):
            if ev.get("hidden"):
                return None                                  # a setUpAll / tearDownAll failed: not a named test
            name, sid = tests.get(ev.get("testID"), (None, None))
            if name and suites.get(sid):
                out.append((suites[sid], name))
    return list(dict.fromkeys(out))


def failing(r, runner):
    """[(path, name)] the engine can re-run alone, or None (unknown / not this runner)."""
    raw = r.raw or ""
    if runner in ("flutter", "dart"):
        return _flutter_failing(getattr(r, "report", None))
    if runner == "pytest":
        out = []
        for node in re.findall(r"(?m)^(?:FAILED|ERROR) (\S+?::\S+)", raw):
            path, _s, name = node.partition("::")
            out.append((path, name.split(" ")[0]))
        return list(dict.fromkeys(out)) or None
    if runner == "unittest":
        out = re.findall(r"(?m)^(?:FAIL|ERROR): (\w+) \(([\w.]+)\)", raw)
        return list(dict.fromkeys(("", full if full.endswith("." + n) else "%s.%s" % (full, n)) for n, full in out)) or None
    return None


INTERP_RE = re.compile(r"(\S+)\s+-m\s+(?:unittest|pytest)\b")


def single(runner, path, name, root=None, cmds=()):
    from workflows.dev import effective as EFF
    interp = next((m.group(1) for m in (INTERP_RE.search(c or "") for c in cmds) if m), None)
    if runner == "unittest":
        return "%s -m unittest -v %s" % (interp or "python3", name)
    if runner == "pytest" and interp:
        import shlex
        return "%s -m pytest -v -rs %s" % (interp, shlex.quote("%s::%s" % (path, name.replace(".", "::"))))
    if runner in ("flutter", "dart") and path and root:
        import os
        for rt in (root, os.path.realpath(root)):
            if path.startswith(rt.rstrip("/") + "/"):
                path = path[len(rt.rstrip("/")) + 1:]
                break
    return EFF.single_command({}, runner, path, name)


def _passed(res, runner, name):
    from workflows.dev import effective as EFF
    if res.timed_out or not res.passed:
        return False
    short = name.split(".")[-1] if runner == "unittest" else name
    return EFF.rerun_kind(res.raw, runner, short, res.passed) in ("passed",) or \
        (runner == "unittest" and bool(re.search(r"(?m)^OK\b", res.raw or "")))


def recheck(r, cmds, run, run_suite=None, root=None):
    """The flake rule (module doc) for one finished suite result `r` of `cmds`. `run(cmd)` runs one command in the
    suite's own tree / sandbox / env; `run_suite()` the whole suite again (for a cut-short run). Returns the note
    {tests, reruns, full_rerun, green} or None (not eligible). `green` False = still red: nothing changes."""
    if r is None or r.passed or r.timed_out:
        return None
    runner = runner_of(cmds)
    raw = r.raw or ""
    for rx in CH.LOAD_ERROR_RES.get(runner, ()):
        if re.search(rx, raw, re.M):
            return None
    fails = failing(r, runner)
    if not fails or len(fails) > MAX_FLAKY:
        return None
    summ = CH.parse_summary(raw, runner)
    if summ is None or summ.failed != len(fails):
        return None                                      # 0.102.6 B1: a failure (an ERROR row …) the names miss
    one = []
    for path, name in fails:
        c = single(runner, path, name, root, cmds)
        if not c:
            return None
        one.append((c, name))
    note = {"tests": [n for _c, n in one], "reruns": [], "full_rerun": False, "green": False}
    for c, name in one:
        res = run(c)
        ok = _passed(res, runner, name)
        note["reruns"].append({"cmd": c, "passed": ok})
        if not ok:
            return note                                      # deterministic: still red — never masked
    # 0.102.6 B1: always the whole suite once more (every command) — an order-dependent failure, a later command that
    # never ran and a failure the names missed are all red there again
    if run_suite is None:
        return note
    full = run_suite()
    note["full_rerun"] = True
    if full is None or not full.passed or full.timed_out:
        return note
    note["full_raw_tail"] = CH.redact_lines("\n".join((full.raw or "").strip().split("\n")[-2:]))
    note["green"] = True
    return note


def off(p):
    """0.102.6: a confirmed `wrong` on a flake row (the count rule's `group.flake.conservative`, or a person's) — a red
    suite stays red, no flake is taken."""
    from workflows.dev import predict as PF
    return bool(PF._truthy((getattr(p, "valves", None) or {}).get(VALVE)))


VALVE = "group.flake.conservative"


def line(note):
    """The one evidence / log line of a green re-run."""
    return "flaky on the first run: %s — re-run alone green%s" % (
        ", ".join(note.get("tests") or []), "; the whole suite (every command) re-run green"
        if note.get("full_rerun") else "")


def record(p, stage, note):
    """The flake note: a decision block (`point: flake`, `grade: trigger` — a grading-sheet row of its own, `grade.select`)
    and a journal event."""
    from workflows.dev.stages import base as B
    B.record_code(p, stage, "flake", "green-on-rerun", refs=",".join(note.get("tests") or [])[:200],
                  reason=B.one_line(line(note), 300), extra={"grade": "trigger"})
    j = getattr(p, "journal", None)
    if j is not None:
        j.append("event", what="flake", stage=stage, tests=note.get("tests") or [],
                 full_rerun=bool(note.get("full_rerun")))
