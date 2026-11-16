"""guildcore.checks — the engine runs the suites itself and reads raw output (§2.8, B-F-1, J-E1).

* `run_command(cmd, timeout_s, cwd)` — `cmd` a string or an ARRAY (element by element, stop at
  the first failure); every element in its own process group (setsid), journaled like a role,
  killed as a group at the ceiling (unattended 3,600,000 ms default). Past the ceiling = RED,
  `suite timed out at <ceiling> ms — last running: <test or file>`.
* `parse_summary(raw, runner=None, config=None)` — built-in parsers (flutter, dart test, jest,
  vitest, pytest, go test) + `config.commands.test_summary {passed_re, failed_re,
  test_name_re}`; an unknown format returns None (caller: MJ-RUNNER, `unsure` → env pause).
* `redact_lines(text)` — INV5 per LINE (a key in one line blanks that line, not the whole
  output — the K0-r3 note for K2).
* `mutation_snapshot/compare` — the auditor tripwire's readings (porcelain + content hash + refs)
  and the formatter pre-filter (`git diff -w --ignore-blank-lines` empty → formatter).
* `branch_candidates(n, branches)` — J-B1's token rule `(?<![0-9.])N(?![0-9])`, release-shaped
  names excluded.
`visual_ledger` (H§L) is K2's (k1-notes).
"""

import os
import re
import subprocess
import time

from guildcore.adapters.claude import process_start, safe_kill_group
from guildcore.records.redact import redact
from guildcore.roles import scope as SC

UNATTENDED_CEILING_S = 3600


class CheckResult(object):
    def __init__(self, passed, rc, timed_out, raw, steps, ceiling_s, last_running=None):
        self.passed = passed
        self.rc = rc
        self.timed_out = timed_out
        self.raw = raw
        self.steps = steps            # [{cmd, rc, timed_out, secs}]
        self.ceiling_s = ceiling_s
        self.last_running = last_running

    def red_line(self):
        if self.timed_out:
            return "suite timed out at %d ms — last running: %s" % (
                self.ceiling_s * 1000, self.last_running or "unknown")
        return None


_LAST_TEST_RES = (
    re.compile(r"^\d\d:\d\d \+\d+(?: ~\d+)?(?: -\d+)?: (.+?)\s*$"),          # flutter/dart
    re.compile(r"^\s*(?:RUNS|PASS|FAIL)\s+(\S+)"),                          # jest
    re.compile(r"^(\S+::\S+)"),                                            # pytest -v
    re.compile(r"^=== RUN\s+(\S+)"),                                       # go -v
)


def last_running(raw):
    for ln in reversed((raw or "").splitlines()):
        for rx in _LAST_TEST_RES:
            m = rx.match(ln)
            if m:
                return m.group(1)
    return None


def run_command(cmd, timeout_s=UNATTENDED_CEILING_S, cwd=".", env=None, journal=None,
                who="checks", poll_s=0.5):
    cmds = list(cmd) if isinstance(cmd, (list, tuple)) else [cmd]
    raw, steps, t0 = [], [], time.time()
    rc, timed_out = 0, False
    for c in cmds:
        left = timeout_s - (time.time() - t0)
        start = time.time()
        p = subprocess.Popen(["/bin/sh", "-c", c], cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, start_new_session=True)
        pg = os.getpgid(p.pid)
        rec = {"pid": p.pid, "pgid": pg, "start_time": process_start(p.pid)}
        if journal is not None:
            journal.record_pid(who, rec["pid"], rec["pgid"], rec["start_time"])
        out = []
        import threading

        def pump():
            for line in iter(p.stdout.readline, b""):
                out.append(line)
        th = threading.Thread(target=pump, daemon=True)
        th.start()
        while True:
            try:
                rc = p.wait(timeout=poll_s)
                break
            except subprocess.TimeoutExpired:
                if time.time() - start > left:
                    timed_out = True
                    safe_kill_group(rec)
                    rc = p.wait()
                    break
        th.join(5)
        text = b"".join(out).decode("utf-8", "replace")
        raw.append(text)
        steps.append({"cmd": c, "rc": rc, "timed_out": timed_out, "secs": round(time.time() - start, 1)})
        if timed_out or rc != 0:
            break
    allraw = "".join(raw)
    return CheckResult(rc == 0 and not timed_out, rc, timed_out, allraw, steps, int(timeout_s),
                       last_running(allraw) if timed_out else None)


def redact_lines(text):
    return "\n".join(redact(ln) for ln in (text or "").split("\n"))


class Summary(object):
    def __init__(self, runner, passed, failed, skipped=0, failed_names=()):
        self.runner = runner
        self.passed = passed
        self.failed = failed
        self.skipped = skipped
        self.failed_names = list(failed_names)

    @property
    def green(self):
        return self.failed == 0 and self.passed > 0

    def as_dict(self):
        return {"runner": self.runner, "passed": self.passed, "failed": self.failed,
                "skipped": self.skipped, "failed_names": self.failed_names, "green": self.green}


def _flutter(raw):
    last = None
    for m in re.finditer(r"^\d\d:\d\d \+(\d+)(?: ~(\d+))?(?: -(\d+))?: (.*)$", raw, re.M):
        last = m
    if not last:
        return None
    names = re.findall(r"^\d\d:\d\d \+\d+(?: ~\d+)? -\d+: (.+?) \[E\]\s*$", raw, re.M)
    return Summary("flutter", int(last.group(1)), int(last.group(3) or 0), int(last.group(2) or 0), names)


def _jest(raw):
    m = re.search(r"^Tests:\s+(.*)$", raw, re.M)
    if not m:
        return None
    seg = m.group(1)

    def n(word):
        x = re.search(r"(\d+) %s" % word, seg)
        return int(x.group(1)) if x else 0
    names = re.findall(r"^\s+● (.+?)\s*$", raw, re.M)
    return Summary("jest", n("passed"), n("failed"), n("skipped"), names)


def _vitest(raw):
    m = re.search(r"^\s*Tests\s+(.*?\(\d+\))\s*$", raw, re.M)
    if not m:
        return None
    seg = m.group(1)

    def n(word):
        x = re.search(r"(\d+) %s" % word, seg)
        return int(x.group(1)) if x else 0
    names = re.findall(r"^\s*(?:×|FAIL)\s+(.+?)\s*$", raw, re.M)
    return Summary("vitest", n("passed"), n("failed"), n("skipped"), names)


def _pytest(raw):
    m = None
    for m2 in re.finditer(r"^=+ (.*?) in [\d.]+s(?: \([^)]*\))? =+$", raw, re.M):
        m = m2
    if not m:
        return None
    seg = m.group(1)

    def n(word):
        x = re.search(r"(\d+) %s" % word, seg)
        return int(x.group(1)) if x else 0
    names = re.findall(r"^FAILED (\S+)", raw, re.M)
    return Summary("pytest", n("passed"), n("failed") + n("error"), n("skipped"), names)


def _go(raw):
    oks = re.findall(r"^ok\s+\S+", raw, re.M)
    fails = re.findall(r"^FAIL\s+\S+", raw, re.M)
    if not oks and not fails:
        return None
    names = re.findall(r"^\s*--- FAIL: (\S+)", raw, re.M)
    passed = len(re.findall(r"^\s*--- PASS: ", raw, re.M)) or len(oks)
    return Summary("go", passed, len(names) or len(fails), 0, names)


PARSERS = (("flutter", _flutter), ("dart", _flutter), ("jest", _jest), ("vitest", _vitest),
           ("pytest", _pytest), ("go", _go))


def parse_summary(raw, runner=None, config=None):
    """Summary or None (unknown format). `config` = commands.test_summary."""
    raw = raw or ""
    if config and config.get("passed_re") and config.get("failed_re"):
        p = re.search(config["passed_re"], raw, re.M)
        f = re.search(config["failed_re"], raw, re.M)
        if p or f:
            names = re.findall(config["test_name_re"], raw, re.M) if config.get("test_name_re") else []
            return Summary("config", int(p.group(1)) if p else 0, int(f.group(1)) if f else 0, 0, names)
    order = [x for x in PARSERS if runner is None or x[0] == runner] or PARSERS
    for name, fn in order:
        s = fn(raw)
        if s is not None:
            if name == "dart":
                s.runner = "dart"
            return s
    return None


def mutation_snapshot(worktree):
    return SC.snapshot(worktree)


def mutation_compare(worktree, before, after):
    """{paths, refs_changed, whitespace_only} — the tripwire readings (D-M*)."""
    paths = SC.changed_paths(before, after)
    refs = sorted(r for r in set(before["refs"]) | set(after["refs"])
                  if before["refs"].get(r) != after["refs"].get(r))
    ws = False
    if paths and not refs:
        p = subprocess.run(["git", "diff", "-w", "--ignore-blank-lines", "--"] + paths, cwd=worktree,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        ws = p.returncode == 0 and not p.stdout.strip()
    return {"paths": paths, "refs_changed": refs, "whitespace_only": ws,
            "head_moved": before["head"] != after["head"]}


_RELEASE = re.compile(r"(^|/)(release|hotfix)[/-]?v?\d+(\.\d+)+$|^v?\d+\.\d+\.\d+")


def branch_candidates(n, branches):
    rx = re.compile(r"(?<![0-9.])%d(?![0-9])" % int(n))
    return [b for b in branches if rx.search(b) and not _RELEASE.search(b)]
