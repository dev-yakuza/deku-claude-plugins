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


# K2r3-M2 / K2r4-M2: the checks profile's network, MEASURED with word_app `flutter test` under
# sandbox-exec (k2-notes): loopback TCP is required (the flutter tool and flutter_tester talk over a
# loopback port the tool opens itself — without it the test fails at load); NO unix socket is
# required → none allowed. Loopback is narrowed twice (last rule wins): every port ALREADY listening
# when the check starts is denied (local proxies, databases, Ollama, docker, the IDE's daemons —
# flutter's own ports open after the profile is rendered), and a static list of common local
# service/proxy ports is denied as well, in case one starts during the check.
UNIX_SOCKETS_ALLOWED = ()
READ_DENY_ROOTS = ("/Users", "/Volumes", "/private/tmp", "/private/var/folders")
LOOPBACK_DENY_PORTS = (80, 443, 1080, 1081, 1086, 1087, 2375, 2376, 3000, 3128, 3306, 4444, 5000, 5432,
                       5672, 6152, 6153, 6379, 7890, 7891, 7897, 8000, 8001, 8080, 8081, 8118, 8443, 8888,
                       9000, 9050, 9090, 9150, 9200, 9229, 10808, 10809, 11211, 11434, 15672, 27017)
LOOPBACK_PROXY_PORTS = LOOPBACK_DENY_PORTS            # r3 name, kept for callers
# K2r4-M2(a): the LaunchServices / `open` route — a sandboxed process asking launchservicesd to
# open a URL hands it to the user's browser OUTSIDE the sandbox (reviewer probe: `lsappinfo`
# answered under the r3 profile). Denied: the LaunchServices/lsd/coreservices mach services,
# Apple Events, and exec of the helpers that use them.
DENY_MACH_RE = r"^com\.apple\.([Cc]ore[Ss]ervices\.|lsd\.|launchservicesd|LaunchServices|ls\.|nsurlsessiond|" \
               r"appleevents|pasteboard|pboard|sharingd|usernotifications|notificationcenterui)"
DENY_EXEC = ("/usr/bin/open", "/usr/bin/osascript", "/usr/bin/lsappinfo", "/usr/bin/pbcopy",
             "/usr/bin/pbpaste", "/usr/bin/say", "/usr/bin/automator", "/usr/bin/shortcuts")


NETSTAT_LISTEN_RE = re.compile(r"^tcp[46]{0,2}\s+\d+\s+\d+\s+(\S+)\.(\d+)\s+\S+\s+LISTEN\b")


def parse_netstat(text):
    """LISTEN ports from `netstat -anv -p tcp` (macOS: `addr.port` local addresses)."""
    out = set()
    for ln in (text or "").split("\n"):
        m = NETSTAT_LISTEN_RE.match(ln.strip())
        if m:
            out.add(int(m.group(2)))
    return out


def parse_lsof(text):
    out = set()
    for ln in (text or "").split("\n"):
        m = re.match(r"^n.*:(\d+)$", ln.strip())
        if m:
            out.add(int(m.group(1)))
    return out


def _cmd(argv):
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
        return p.stdout.decode("utf-8", "replace") if p.returncode == 0 or p.stdout else None
    except (OSError, subprocess.SubprocessError):
        return None


class PortsUnreadable(RuntimeError):
    pass


def listening_ports():
    """TCP ports in LISTEN state right now — EVERY user's, root daemons included (K2r5-M1):
    `netstat -anv -p tcp` (all sockets, no owner filter) ∪ `lsof` (this user's). Fails CLOSED:
    when neither can be read the check refuses to run (`PortsUnreadable`)."""
    ns = _cmd(["/usr/sbin/netstat", "-anv", "-p", "tcp"])
    ls = _cmd(["/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fn"])
    if ns is None and ls is None:
        raise PortsUnreadable("cannot list listening ports (netstat and lsof both failed)")
    return sorted(parse_netstat(ns) | parse_lsof(ls))


def sandbox_profile(block, extra_write=(), loopback=True, unix_sockets=UNIX_SOCKETS_ALLOWED,
                    deny_ports=None, allow_ports=()):
    """An SBPL profile from a rendered `sandbox` block (last matching rule wins). `deny_ports`:
    loopback ports to deny on top of the static list (the caller passes the ports listening at
    check start); `allow_ports`: the engine's own loopback services (the deps proxy)."""
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
    # K2r4-M2: read exceptions inside a denied tree (dependency dirs the temp tree symlinks)
    for r in fs.get("allowRead") or []:
        tgt = r if not os.path.isdir(r) else r.rstrip("/") + "/**"
        lines.append("(allow file-read* %s)" % _sb_target(tgt))
    # K3 (K2r4/r7 carry-over): a networked step (K1 deps, warm-up) READS only an allowlist — the
    # tree, the toolchain caches, the SDK, the run dir. Everything under the user areas (`/Users`,
    # `/Volumes`, the shared temp roots) is denied first, then the allowlist re-opened (last match
    # wins); system paths stay readable (the tools' own binaries and libraries). Metadata stays
    # readable (path resolution); denyRead entries are re-applied last so an original inside the
    # tree (a `copy_ignored` secret) stays unreadable.
    ro = fs.get("readOnlyAllow")
    if ro is not None:
        for root in READ_DENY_ROOTS:
            lines.append("(deny file-read* (subpath %s))" % _sb_str(os.path.realpath(root) if os.path.exists(root) else root))
        lines.append("(allow file-read-metadata)")
        for r in ro:
            tgt = r if r.endswith("/**") or not os.path.isdir(r) else r.rstrip("/") + "/**"
            lines.append("(allow file-read* %s)" % _sb_target(tgt))
        for r in fs.get("denyRead") or []:
            tgt = r if not os.path.isdir(r) else r.rstrip("/") + "/**"
            lines.append("(deny file-read* %s)" % _sb_target(tgt))
    # bash/sh here-document temp files (`sh-thd*`) land wherever the shell finds a writable
    # spot, not necessarily TMPDIR (verified) — allowed by NAME, after the denies (last wins)
    lines.append("(allow file-write* (regex #\"/sh-thd[^/]*$\"))")
    lines += ["(deny mach-lookup (global-name-regex #\"%s\"))" % DENY_MACH_RE, "(deny appleevent-send)",
              "(deny process-exec %s)" % " ".join("(literal %s)" % _sb_str(x) for x in DENY_EXEC)]
    # NOTE (measured, K2r4): after a filter-less `(deny network-outbound)` a later port-specific
    # deny does NOT take effect (`localhost:*` allow wins) — the r3 profile's port denies were
    # inert. The filtered form below is honoured: deny every ip and every unix socket, allow
    # loopback, then deny the ports (probe: curl to a listening localhost port → rc 7).
    lines += ["(deny network-outbound (remote ip \"*:*\"))", "(deny network-outbound (remote unix-socket))"]
    if loopback:
        lines.append("(allow network-outbound (remote ip \"localhost:*\"))")
        for port in sorted(set(LOOPBACK_DENY_PORTS) | set(deny_ports or ())):
            if port not in (allow_ports or ()):
                lines.append("(deny network-outbound (remote ip \"localhost:%d\"))" % port)
    for u in unix_sockets or ():
        lines.append("(allow network-outbound (remote unix-socket (path-literal %s)))" % _sb_str(u))
    return "\n".join(lines) + "\n"


def check_env(role_env, tmp):
    """The checks env: the role's scrubbed env + no bytecode reuse/writes + a private TMPDIR."""
    e = dict(role_env or os.environ)
    os.makedirs(tmp, exist_ok=True)  # fs-ok: engine-created check tmp / engine process-tools dir, before the check runs
    pyc = os.path.join(tmp, "pycache")
    os.makedirs(pyc, exist_ok=True)  # fs-ok: engine-created check tmp / engine process-tools dir, before the check runs
    e.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": pyc, "TMPDIR": tmp,
              # K3r6-m3: the suite's node_modules is the engine's (read-only) — tool caches go to the run tmp
              "BABEL_CACHE_PATH": os.path.join(tmp, "babel-cache.json"), "XDG_CACHE_HOME": os.path.join(tmp, "cache"),
              "npm_config_cache": os.path.join(tmp, "npm-cache")})
    # 0.102.12 (review-0102-11 M4, japanlifeinfo #227): ONE engine-owned Corepack home (never the run tmp's empty
    # `$XDG_CACHE_HOME/node/corepack`); a networked step (the deps step marks its env) may fetch into it, every other
    # check runs with Corepack's network off
    from guildcore.checks import pmcache as PMC
    networked = e.pop("GUILD_NETWORK_STEP", None) == "1"
    e = PMC.env_for(e, offline=not networked)
    tools = process_tools_dir()
    if tools:
        e["PATH"] = tools + os.pathsep + e.get("PATH", "")
    return e


def sandboxed(cmd, block, tmp, allow_ports=(), deny_ports=None):
    """`cmd` (a shell string) wrapped in sandbox-exec with the profile; raises when the host has
    no sandbox-exec (the engine must not run role-written code unconfined). The loopback ports
    listening NOW are denied (K2r4-M2) unless the caller passes them explicitly."""
    if not os.path.exists(SANDBOX_EXEC):
        raise RuntimeError("no sandbox-exec on this host — checks refuse to run unconfined")
    # `tmp` is writable by the code the previous command of this check ran — a link planted there must
    # not redirect the engine's write (K3r6-B1)
    from guildcore import fsafe as FS
    prof = FS.write_text(tmp, "checks.sb", sandbox_profile(block, extra_write=[tmp], allow_ports=allow_ports,
                                                           deny_ports=listening_ports() if deny_ports is None else deny_ports))
    return "%s -f %s /bin/sh -c %s" % (SANDBOX_EXEC, _shq(prof), _shq(cmd))


def _shq(s):
    return "'" + s.replace("'", "'\\''") + "'"


def run_command(cmd, timeout_s=UNATTENDED_CEILING_S, cwd=".", env=None, journal=None,
                who="checks", poll_s=0.5, sandbox=None, tmp=None, allow_ports=()):
    """`sandbox` = the owning role's rendered sandbox block (required for code a role wrote);
    `tmp` = a private temp dir (the run dir's tmp/)."""
    cmds = list(cmd) if isinstance(cmd, (list, tuple)) else [cmd]
    if sandbox is not None:
        if not tmp:
            raise ValueError("a sandboxed check needs a private tmp dir outside the worktree")
        env = check_env(env, tmp)
        # 0.102.14 (one-man-company #687): the engine's own PWD / PYENV_DIR (pyenv's `python3` shim exports PYENV_DIR =
        # the dir the engine was started in — the main checkout, denyRead here) must not reach the check: pyenv
        # aborted `cannot change working directory`. PWD is the check's cwd; pyenv then reads it.
        env["PWD"] = os.path.abspath(cwd)
        for k in ("PYENV_DIR", "OLDPWD"):
            env.pop(k, None)
        deny = listening_ports()                       # once, before any command of this check starts
        cmds = [sandboxed(c, sandbox, tmp, allow_ports, deny) for c in cmds]
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
        e["GUILD_NETWORK_STEP"] = "1"              # 0.102.12: check_env keeps Corepack's network on for this step
        r = run_command(cmds, timeout_s, cwd=worktree, env=e, sandbox=sandbox, tmp=tmp,
                        allow_ports=(px.srv.server_address[1],))
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
    os.makedirs(base, exist_ok=True)  # fs-ok: engine-created check tmp / engine process-tools dir, before the check runs
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
            _sh.copyfile(src, tmp)  # fs-ok: engine-owned ~/.cache/guild-engine/bin tool copies
            os.chmod(tmp, 0o755)  # fs-ok: engine-created check tmp / engine process-tools dir, before the check runs
            p = subprocess.run(["codesign", "-s", "-", "--force", tmp], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            if p.returncode != 0:
                return None
            os.replace(tmp, dst)  # fs-ok: engine-owned ~/.cache/guild-engine/bin tool copies
            with open(stamp, "w") as fh:  # fs-ok: engine-owned ~/.cache/guild-engine/bin tool copies
                fh.write(want + "\n")
    return base


from guildcore.checks.visual import visual_ledger  # noqa: E402,F401  (§2.0 interface: checks.visual_ledger)
