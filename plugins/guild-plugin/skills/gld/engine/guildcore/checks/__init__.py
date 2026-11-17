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

K1r3-B1: the engine's own checks run the code roles wrote (tests, caches), so they run under
the SAME rendered sandbox block as the role that owns them — on macOS through `sandbox-exec`
with a profile built from it (writes only where the role could write, denyWrite and denyRead as
rendered, no network but loopback; package registries are not reachable from checks — dependency
fetching is a role's or the engine's explicit step). Python bytecode caches in the worktree are
never executed (`PYTHONPYCACHEPREFIX` → a fresh dir) nor written (`PYTHONDONTWRITEBYTECODE`).
The env is the role's scrubbed env (no tokens, no GH_*).
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


SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def _sb_str(p):
    return '"%s"' % p.replace("\\", "\\\\").replace('"', '\\"')


def _sb_target(entry):
    e = entry
    if e.endswith("/**"):
        base = e[:-3]
        real = os.path.realpath(base) if os.path.exists(base) else base
        return "(subpath %s)" % _sb_str(real)
    real = os.path.realpath(e) if os.path.exists(os.path.dirname(e) or "/") else e
    return "(literal %s)" % _sb_str(real)


def sandbox_profile(block, extra_write=()):
    """An SBPL profile from a rendered `sandbox` block (last matching rule wins)."""
    fs = (block or {}).get("filesystem") or {}
    lines = ["(version 1)", "(allow default)", "(deny file-write*)",
             "(allow file-write* (literal \"/dev/null\") (literal \"/dev/tty\") (subpath \"/dev/fd\"))"]
    for a in list(fs.get("allowWrite") or []) + [x.rstrip("/") + "/**" for x in extra_write]:
        lines.append("(allow file-write* %s)" % _sb_target(a))
    for d in fs.get("denyWrite") or []:
        lines.append("(deny file-write* %s)" % _sb_target(d if d.endswith("/**") or not os.path.isdir(d) else d + "/**"))
    for r in fs.get("denyRead") or []:
        tgt = r if not os.path.isdir(r) else r.rstrip("/") + "/**"
        lines.append("(deny file-read* %s)" % _sb_target(tgt))
    # bash/sh here-document temp files (`sh-thd*`) land wherever the shell finds a writable
    # spot, not necessarily TMPDIR (verified) — allowed by NAME, after the denies (last wins)
    lines.append("(allow file-write* (regex #\"/sh-thd[^/]*$\"))")
    lines += ["(deny network-outbound)",
              "(allow network-outbound (remote ip \"localhost:*\"))",
              "(allow network-outbound (remote unix-socket))"]
    return "\n".join(lines) + "\n"


def check_env(role_env, tmp):
    """The checks env: the role's scrubbed env + no bytecode reuse/writes + a private TMPDIR."""
    e = dict(role_env or os.environ)
    os.makedirs(tmp, exist_ok=True)
    pyc = os.path.join(tmp, "pycache")
    os.makedirs(pyc, exist_ok=True)
    e.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": pyc, "TMPDIR": tmp})
    tools = process_tools_dir()
    if tools:
        e["PATH"] = tools + os.pathsep + e.get("PATH", "")
    return e


def sandboxed(cmd, block, tmp):
    """`cmd` (a shell string) wrapped in sandbox-exec with the profile; raises when the host has
    no sandbox-exec (the engine must not run role-written code unconfined)."""
    if not os.path.exists(SANDBOX_EXEC):
        raise RuntimeError("no sandbox-exec on this host — checks refuse to run unconfined")
    prof = os.path.join(tmp, "checks.sb")
    with open(prof, "w") as fh:
        fh.write(sandbox_profile(block, extra_write=[tmp]))
    return "%s -f %s /bin/sh -c %s" % (SANDBOX_EXEC, _shq(prof), _shq(cmd))


def _shq(s):
    return "'" + s.replace("'", "'\\''") + "'"


def run_command(cmd, timeout_s=UNATTENDED_CEILING_S, cwd=".", env=None, journal=None,
                who="checks", poll_s=0.5, sandbox=None, tmp=None):
    """`sandbox` = the owning role's rendered sandbox block (required for code a role wrote);
    `tmp` = a private temp dir (the run dir's tmp/)."""
    cmds = list(cmd) if isinstance(cmd, (list, tuple)) else [cmd]
    if sandbox is not None:
        if not tmp:
            raise ValueError("a sandboxed check needs a private tmp dir outside the worktree")
        env = check_env(env, tmp)
        cmds = [sandboxed(c, sandbox, tmp) for c in cmds]
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


def _unittest(raw):
    """python -m unittest (K2: the TEST effective check's own fixtures, and stdlib projects)."""
    m = re.search(r"^Ran (\d+) tests? in [\d.]+s\s*$", raw, re.M)
    if not m:
        return None
    total = int(m.group(1))
    f = re.search(r"^FAILED \(([^)]*)\)\s*$", raw, re.M)
    failures = errors = 0
    if f:
        x = re.search(r"failures=(\d+)", f.group(1))
        y = re.search(r"errors=(\d+)", f.group(1))
        failures, errors = int(x.group(1)) if x else 0, int(y.group(1)) if y else 0
    sk = re.search(r"skipped=(\d+)", raw)
    names = re.findall(r"^(?:FAIL|ERROR): (\S+)", raw, re.M)
    s = Summary("unittest", total - failures - errors, failures + errors, int(sk.group(1)) if sk else 0, names)
    s.errors = errors
    return s


PARSERS = (("flutter", _flutter), ("dart", _flutter), ("jest", _jest), ("vitest", _vitest),
           ("pytest", _pytest), ("go", _go), ("unittest", _unittest))


# K2 — R7J-m1: a failing re-run counts for the TEST `effective` check only when the runner
# reports an ASSERTION / test failure; a collection, compile or import error is no evidence
# that the assertion reacts to the code (it would fail with any edit) → `unsure`.
LOAD_ERROR_RES = {
    # COLLECTION / COMPILE stage only (K2r2-B1) — a runtime error (`is not a function`,
    # ReferenceError, NameError, a runtime `Error:` log line) is an assertion-less FAILURE
    "flutter": (r"Failed to load \"", r"Compilation failed", r"(?m)^\S+\.dart:\d+:\d+: Error: "),
    "jest": (r"Test suite failed to run", r"Failed to load url"),
    "pytest": (r"ERROR collecting", r"errors? during collection", r"ImportError while importing test module"),
    "go": (r"\[build failed\]", r"\[setup failed\]"),
    "unittest": (r"unittest\.loader\._FailedTest", r"(?s)^ERROR: .*?(?:ImportError|ModuleNotFoundError|SyntaxError)"),
}
LOAD_ERROR_RES["dart"] = LOAD_ERROR_RES["flutter"]
LOAD_ERROR_RES["vitest"] = LOAD_ERROR_RES["jest"]


def failure_kind(raw, runner=None, passed=None):
    """`passed` | `assertion` | `load_error` | `unknown` for one (re-)run's raw output."""
    s = parse_summary(raw, runner)
    if s is None:
        return "passed" if passed else "unknown"
    rn = runner or s.runner
    if s.failed == 0:
        return "passed" if (s.passed > 0 or passed) else "unknown"
    for rx in LOAD_ERROR_RES.get(rn, ()):
        if re.search(rx, raw or "", re.M):
            return "load_error"
    if getattr(s, "errors", 0) and s.failed == s.errors:
        return "runtime"
    return "assertion"


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


# K1r4-M2: the engine's explicit dependency step — before roles and checks — with network to
# these hosts only (through checks.netproxy; sandbox-exec itself allows loopback only).
# Measured with word_app: pub needs pub.dev; the sqlite3 native-assets build hook downloads a
# prebuilt binary from GitHub RELEASES (github.com → release-assets.githubusercontent.com,
# read-only GETs; api.github.com is never listed).
DEPS_HOSTS = {
    "pubspec.yaml": ("pub.dev", "pub.dartlang.org", "storage.googleapis.com", "github.com",
                     "objects.githubusercontent.com", "release-assets.githubusercontent.com"),
    "package.json": ("registry.npmjs.org", "registry.yarnpkg.com"),
    "pyproject.toml": ("pypi.org", "files.pythonhosted.org"),
    "requirements.txt": ("pypi.org", "files.pythonhosted.org"),
    "go.mod": ("proxy.golang.org", "sum.golang.org"),
    "Cargo.toml": ("crates.io", "static.crates.io", "index.crates.io"),
}


def deps_hosts(worktree):
    out = []
    for f, hosts in DEPS_HOSTS.items():
        if os.path.exists(os.path.join(worktree, f)):
            out += [h for h in hosts if h not in out]
    return out


def deps_step(cmds, worktree, sandbox, tmp, env=None, hosts=None, timeout_s=1800):
    """Run dependency commands (e.g. `flutter pub get`, a `--no-pub` warm-up test, `npm ci`)
    under the role's sandbox profile with network limited to `hosts` via the allowlist proxy.
    Returns (CheckResult, proxy summary {host:port allowed|DENIED: n})."""
    from guildcore.checks.netproxy import AllowlistProxy
    with AllowlistProxy(hosts if hosts is not None else deps_hosts(worktree)) as px:
        e = dict(env or os.environ)
        e.update(px.env())
        r = run_command(cmds, timeout_s, cwd=worktree, env=e, sandbox=sandbox, tmp=tmp)
        return r, px.summary()


# Process lookups inside the sandboxes (user decision, K1r5): macOS refuses to exec SETUID
# binaries from any sandboxed process — `/bin/ps` fails with EPERM under both the CLI sandbox
# and sandbox-exec (measured), which broke word_app's process-tree test. The engine provides an
# ad-hoc-signed, NON-setuid copy of ps that sees this user's processes (as far as the sandbox's
# process-info rule allows: same-sandbox for the CLI, all of the user's for checks) and puts it
# first on PATH. pgrep/pkill are not setuid and work unchanged.
SETUID_TOOLS = ("/bin/ps",)


def process_tools_dir(home=None):
    """`~/.cache/guild-engine/bin` with the non-setuid tool copies (created once, re-made when the
    system binary changes). Returns the dir, or None when it cannot be prepared."""
    import hashlib
    import shutil as _sh
    base = os.path.join(home or os.path.expanduser("~"), ".cache", "guild-engine", "bin")
    os.makedirs(base, exist_ok=True)
    for src in SETUID_TOOLS:
        if not os.path.exists(src):
            continue
        dst = os.path.join(base, os.path.basename(src))
        stamp = dst + ".src-sha256"
        with open(src, "rb") as fh:
            want = hashlib.sha256(fh.read()).hexdigest()
        have = open(stamp).read().strip() if os.path.exists(stamp) else None
        if have != want or not os.path.exists(dst):
            tmp = dst + ".tmp"
            _sh.copyfile(src, tmp)
            os.chmod(tmp, 0o755)
            p = subprocess.run(["codesign", "-s", "-", "--force", tmp], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            if p.returncode != 0:
                return None
            os.replace(tmp, dst)
            with open(stamp, "w") as fh:
                fh.write(want + "\n")
    return base


from guildcore.checks.visual import visual_ledger  # noqa: E402,F401  (§2.0 interface: checks.visual_ledger)
