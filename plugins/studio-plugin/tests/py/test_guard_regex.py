"""fix-0103 (0.1.3): the guard's regexes and its process timer. RegexBudget times every collected guard regex (G1 and
the frozen copy) on adversarial inputs at its call site's input bound, and checks that the time does not grow
quadratically; RegexEquivalence checks each rewrite against its old text; HookDeadline runs guard.py past
limits.HOOK_DEADLINE (a plain folder at 15 s, and fast variants through drivers/guard_deadline.py at 3 s)."""

import ast
import glob
import importlib
import json
import os
import pkgutil
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import helpers
import test_guard_backstop as TB
import transcripts as TR
from guard_base import GuardCase, snapshot_text
from stdo.guard import limits

GUARD = os.path.join(helpers.SCRIPTS, "guard.py")
GUARD_DIR = os.path.join(helpers.SCRIPTS, "stdo", "guard")
DRIVERS = os.path.join(helpers.HERE, "drivers")
OPS = ("search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split")
FLAG_NAMES = {"I", "M", "S", "X", "A", "IGNORECASE", "MULTILINE", "DOTALL", "VERBOSE", "ASCII"}
BUDGET_MS = 50.0
BOUND = 4096
# call sites whose input is bounded below BOUND: (file, pattern) → characters
BOUNDS = {}
# patterns the budget does not hold, each with its reason: (file, pattern) → reason
ALLOW = {}
_ARITH = ("walk.py", "ARITH_DYN_ASSIGN_RE", "ARITH_ASSIGN_RE")
_SED_OLD = r"(^|[;{}\n])\s*(\d+|\$|/[^/]*/)?\s*e(\s|;|$)"
ALLOW[("legacy/walk.py", _SED_OLD)] = (
    "the frozen 0.0.26 copy (hash-pinned) keeps HEAD's sed `e` regex, cubic on blank lines; G1's copy is rewritten "
    "and the process timer turns the frozen one into G-LIMIT (HookDeadline.test_plain_folder_sed_row)")
_SNAP_REASON = (
    "matched once per line of Claude Code's shell snapshot (the user's own shell, written by Claude Code, not by a "
    "tool call); quadratic only on a line holding a long blank run with no `{` where the pattern needs it (25 ms at "
    "4 KB); the frozen copy parses the same lines with the same pattern and cannot change, so a G1 rewrite would not "
    "bound the call; the process timer bounds both")
for _f in ("snapshot.py", "legacy/snapshot.py"):
    ALLOW[(_f, r"^(?:function\s+)?([^\s(){};|&<>'\"$`]+)\s*(?:\(\))?\s*\{")] = _SNAP_REASON
    ALLOW[(_f, r"^\s*(?:function\s+([^\s(){};|&<>'\"$`]+)\s*(?:\(\))?\s*\{|([^\s(){};|&<>'\"$`]+)\s*\(\)\s*\{)")] = \
        _SNAP_REASON


def _flags(call):
    n = 0
    for a in list(call.args[1:]) + [k.value for k in call.keywords]:
        for x in ast.walk(a):
            if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and x.value.id == "re" \
                    and x.attr in FLAG_NAMES:
                n |= getattr(re, x.attr)
    return n


def _norm(flags):
    return int(flags) & ~int(re.UNICODE)


def collect():
    """Every regex of stdo/guard/*.py and stdo/guard/legacy/*.py: literals passed to re.<fn>, `NAME = re.compile(LIT)`,
    `NAME_RE = "…"` strings, and every compiled pattern the modules hold at import time (composed ones). Returns
    {(pattern, flags): {"where": set of "file:line|NAME", "files": set, "ops": set, "names": set}}; ops come from the
    call sites (`re.<op>(LIT`, `NAME.<op>(`, `re.<op>(NAME`), and none found means every op."""
    files = sorted(glob.glob(os.path.join(GUARD_DIR, "*.py"))) + \
        sorted(glob.glob(os.path.join(GUARD_DIR, "legacy", "*.py")))
    sources = {}
    sites = {}

    def site(key, rel, where):
        s = sites.setdefault(key, {"where": set(), "files": set(), "ops": set(), "names": set()})
        s["where"].add("%s:%s" % (rel, where))
        s["files"].add(rel)
        return s

    for path in files:
        rel = os.path.relpath(path, GUARD_DIR).replace(os.sep, "/")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        sources[rel] = text
        tree = ast.parse(text)
        assigned = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                assigned[id(node.value)] = node.targets[0].id
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in OPS + (
                    "compile",) and isinstance(node.func.value, ast.Name) and node.func.value.id == "re" and node.args:
                a = node.args[0]
                if not (isinstance(a, ast.Constant) and isinstance(a.value, str)):
                    continue
                s = site((a.value, _norm(_flags(node))), rel, node.lineno)
                if node.func.attr != "compile":
                    s["ops"].add(node.func.attr)
                elif id(node) in assigned:
                    s["names"].add(assigned[id(node)])
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and node.targets[0].id.endswith("_RE") and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                site((node.value.value, 0), rel, node.lineno)["names"].add(node.targets[0].id)
    # compiled at import time (composed patterns the literal scan misses)
    import stdo.guard as g
    import stdo.guard.legacy as lg
    for pkg, pre in ((g, "stdo.guard."), (lg, "stdo.guard.legacy.")):
        for _f, n, _p in pkgutil.iter_modules(pkg.__path__):
            m = importlib.import_module(pre + n)
            rel = (pre + n)[len("stdo.guard."):].replace(".", "/") + ".py"
            for k, v in vars(m).items():
                if isinstance(v, type(re.compile(""))):
                    site((v.pattern, _norm(v.flags)), rel, k)["names"].add(k)
    alltext = "\n".join(sources.values())
    for s in sites.values():
        for name in s["names"]:
            s["ops"].update(re.findall(r"\b%s\.(\w+)\(" % re.escape(name), alltext))
            s["ops"].update(re.findall(r"\bre\.(\w+)\(\s*%s\b" % re.escape(name), alltext))
        s["ops"] = {"sub" if o == "subn" else o for o in s["ops"] if o in OPS}
        if not s["ops"]:
            s["ops"] = {"search", "match", "fullmatch"}
    return sites


def _allowed(key, s):
    reasons = [ALLOW.get((f, key[0])) for f in s["files"]]
    return reasons[0] if reasons and all(reasons) else None


def _bound(key, s):
    if all(f == _ARITH[0] for f in s["files"]) and s["names"] & set(_ARITH[1:]):
        return 512  # walk.ARITH_MAX: longer `(( … ))` text never reaches these (fix-0103 §2)
    return BOUND


class RegexBudget(unittest.TestCase):
    def test_collected(self):
        sites = collect()
        self.assertGreater(len(sites), 150)
        for f, pat in ALLOW:
            self.assertTrue(any(k[0] == pat and f in s["files"] for k, s in sites.items()), (f, pat))
        from stdo.guard import walk
        self.assertEqual(_bound(*next((k, s) for k, s in sites.items() if "ARITH_ASSIGN_RE" in s["names"])),
                         walk.ARITH_MAX)

    def test_budget_and_growth(self):
        sites = collect()
        rows = []
        for i, (key, s) in enumerate(sorted(sites.items())):
            if _allowed(key, s):
                continue
            b = _bound(key, s)
            rows.append({"id": i, "pattern": key[0], "flags": key[1], "ops": sorted(s["ops"]), "bound": b,
                         "growth": b >= BOUND, "budget_ms": BUDGET_MS, "where": sorted(s["where"])})
        n = max(1, min(4, os.cpu_count() or 1))
        tmp = tempfile.mkdtemp(prefix="studio-regex-")
        procs = []
        try:
            for w in range(n):
                p = os.path.join(tmp, "rows%d.json" % w)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(rows[w::n], f)
                procs.append(subprocess.Popen([sys.executable, "-B", os.path.join(DRIVERS, "regex_budget.py"), p],
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            out = {}
            for p in procs:
                o, e = p.communicate(timeout=900)
                self.assertEqual(p.returncode, 0, e[-800:])
                for line in o.splitlines():
                    r = json.loads(line)
                    out[r["id"]] = r
        finally:
            for p in procs:
                if p.poll() is None:
                    p.kill()
                    p.wait()
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(len(out), len(rows))
        bad = []
        for row in rows:
            r = out[row["id"]]
            if r["worst_ms"] is None or r["worst_ms"] >= BUDGET_MS:
                bad.append("%s %r: %s ms on %s" % (row["where"], row["pattern"][:80], r["worst_ms"], r["case"]))
            for g in r["growth"]:
                bad.append("%s %r: grows %s → %s ms from 4 KB to 32 KB on %s" % (
                    row["where"], row["pattern"][:80], g["t4_ms"], g["t32_ms"], g["case"]))
        self.assertEqual(bad, [], "\n".join(bad))


class _Late(BaseException):
    pass


def _late(signum, frame):
    raise _Late()


def _timed(fn, limit=0.2):
    """fn()'s answer, or _Late past `limit` (the old texts backtrack without bound on some inputs)."""
    old = signal.signal(signal.SIGALRM, _late)
    signal.setitimer(signal.ITIMER_REAL, limit)
    try:
        return fn()
    except _Late:
        return _Late
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


# (name, old text, new text, op, alphabet): the rewrites of fix-0103 §1-§2
REWRITES = [
    ("walk SAFE_ARRAY_RE", r"^\(\s*(?:[A-Za-z0-9_./,:@%=-]+\s*)*\)$", r"^\([\sA-Za-z0-9_./,:@%=-]*\)$", "match",
     "( )a/.\t\n$\"=,"),
    ("walk ${X::=…}", r"(?:[^$`'\"\\~*?\[]|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)*",
     r"(?:[^$`'\"\\~*?\[]|\$(?:\{[A-Za-z_][A-Za-z0-9_]*(?:\}|(?![A-Za-z0-9_}]))|[A-Za-z_][A-Za-z0-9_]*"
     r"(?![A-Za-z0-9_])))*", "fullmatch", "$a{}_1 `*b"),
    ("walk sed e", _SED_OLD, r"(^|[;{}\n])[^\S\n]*(?:(?:\d+|\$|/[^/]*/)\s*)?e(\s|;|$)", "search", "\n ;{}1$/e x\t"),
    ("walk QUAL_CODE_RE", r"\([^)]*[e+]", r"\([^()e+]*[e+]", "search", "()e+a f"),
    ("walk note_definitions", r"([^\s;&|(){}<>'\"]+)\s*\(\s*\)",
     r"(?<![^\s;&|(){}<>'\"])([^\s;&|(){}<>'\"]+)\s*\(\s*\)", "findall", "ab ()\t;{}'\"f&"),
    ("cmdopts GIT_CONFIG_PARAMETERS", r"'([^'=]*)'?=?'?([^']*)'", r"'(?=[^']*')([^'=]*)'?=?'?([^']*)'", "findall",
     "'=ab. "),
    ("judge unparsable_glob_group", r"\([^()]*\|[^()]*\)", r"\([^()|]*\|[^()]*\)", "search", "()|a "),
]


class RegexEquivalence(unittest.TestCase):
    N = 30000

    def test_rewrites_in_place(self):
        g1 = {k[0] for k, s in collect().items() if any(not f.startswith("legacy/") for f in s["files"])}
        for name, old, new, _op, _alpha in REWRITES:
            self.assertIn(new, g1, name)
            self.assertNotIn(old, g1, name)
        from stdo.guard import walk
        self.assertEqual(walk.ARITH_MAX, 512)

    def test_equal_answers(self):
        for name, old, new, op, alpha in REWRITES:
            po, pn = re.compile(old), re.compile(new)
            rnd = random.Random(7)
            diffs, slow = [], 0
            for _i in range(self.N):
                s = "".join(rnd.choice(alpha) for _j in range(rnd.randint(0, 14)))
                a = _timed(lambda: getattr(po, op)(s))
                if a is _Late:
                    slow += 1
                    continue
                b = getattr(pn, op)(s)
                if op != "findall":
                    a, b = bool(a), bool(b)
                if a != b:
                    diffs.append(s)
            self.assertEqual(diffs[:5], [], name)
            self.assertLess(slow, self.N // 100, name)

    def test_rstrip_for_sub(self):  # judge.py exiftool option names: `$` also matches before a final newline (NIT)
        rnd = random.Random(3)
        for _i in range(self.N):
            lv = "".join(rnd.choice("ab-:0129+!#") for _j in range(rnd.randint(0, 12)))
            self.assertEqual(lv.rstrip("+!#").rstrip("0123456789:"), re.sub(r"[0-9:]+$", "", lv.rstrip("+!#")), lv)


class ArithCap(GuardCase):
    def test_long_arith_in_a_snapshot_function(self):  # fix-0103 §2: ARITH_MAX
        from stdo import guard
        from stdo.guard import walk
        from stdo.guard.scanctx import ScanCtx
        long = " + ".join(["n"] * 200)
        self.assertGreater(len(long), walk.ARITH_MAX)
        funcs = "arshort () {\n\t(( n = 1 ))\n}\narlong () {\n\t(( n = %s ))\n}\nevalin () {\n\teval x\n}\n" % long
        snap = self.use_snapshots(snapshot_text(functions=funcs))
        ctx = ScanCtx(self.env, guard.FS(), snapshot=snap)
        self.assertEqual(walk.snapshot_function_effects(ctx, "arshort")["globals"], {"n"})
        self.assertIsNone(walk.snapshot_function_effects(ctx, "evalin"))
        self.assertIsNone(walk.snapshot_function_effects(ctx, "arlong"))  # as an eval in it: effects unknown
        self.mk("a")
        self.assertEqual(self.one(self.ok("cd a; arlong; touch x"), "touch").cwds, [])
        self.assertEqual(self.one(self.ok("cd a; arshort; touch x"), "touch").cwds, [os.path.join(self.root, "a")])


# ---- the process timer (fix-0103 §3) ----

DEADLINE_TEXT = "Studio guard [G-LIMIT]: the call needs more checks than the guard's time allows"
# the frozen copy's sed regex is cubic on blank lines; 0.1.4: a source in a function the call defines (never called)
# routes the call to it (G1 alone is linear) and leaves its sed check as without it
SED_ROW = "f(){ source /dev/null; }; sed -n -e '" + "\n" * 6000 + "p' a.txt"
_PLAIN = {}


def setUpModule():
    """The 15 s plain-folder run starts first and is collected by its test, so the module's other tests overlap it."""
    root = tempfile.mkdtemp(prefix="studio-deadline-")
    env = helpers.isolated_env(root)
    env.pop("CLAUDE_PLUGIN_DATA", None)
    plain = os.path.join(root, "plain")
    os.makedirs(plain)
    hook = helpers.hook_input("Bash", {"command": SED_ROW}, plain)
    p = subprocess.Popen([sys.executable, GUARD], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env, cwd=plain)
    t0 = time.monotonic()
    p.stdin.write(json.dumps(hook).encode())  # ~6 KB: within the pipe's buffer
    p.stdin.close()
    p.stdin = None  # written and closed (Python 3.9's communicate flushes it otherwise)

    def collect():
        # the process's own run time, not the time until its test is reached (the module's other tests run first)
        _PLAIN["result"] = p.communicate(timeout=60)
        _PLAIN["dt"] = time.monotonic() - t0
    th = threading.Thread(target=collect, daemon=True)
    th.start()
    _PLAIN.update(root=root, proc=p, t0=t0, thread=th)


def tearDownModule():
    p = _PLAIN.get("proc")
    if p is not None and p.poll() is None:
        p.kill()
        p.wait()
    if _PLAIN.get("root"):
        shutil.rmtree(_PLAIN["root"], ignore_errors=True)


def _deny_lines(stdout):
    lines = stdout.strip().splitlines()
    return [json.loads(x)["hookSpecificOutput"] for x in lines]


class HookDeadline(TB.BackstopCase):
    """guard.py past the deadline. The fast variants run guard.py's main through drivers/guard_deadline.py with
    HOOK_DEADLINE 3 s and 5 s sleeps patched in (no switch in the production code)."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        with open(os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"), "w") as f:
            json.dump({"video": "v", "source_lang": "ko"}, f)
        self.tpath = TR.transcript_path(self.env)
        self.t = TR.approval_turn(TR.T(), "승인 v %s" % TB.H)
        self.t.write(self.tpath)
        self.denv = dict(self.env, PYTHONDONTWRITEBYTECODE="1")
        self.denv.pop("CLAUDE_PLUGIN_DATA", None)

    def hook(self, tool, ti, cwd=None):
        h = super().hook(tool, ti, cwd)
        h.update({"transcript_path": self.tpath, "tool_use_id": "toolu_cmd1", "prompt_id": self.t.prompt})
        return h

    def local(self, name):
        return os.path.join(self.repo, ".claude", "studio", "local", name)

    def drive(self, scenario, command, deadline=3, stdin=None):
        data = stdin if stdin is not None else json.dumps(self.hook("Bash", {"command": command}))
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, "-B", os.path.join(DRIVERS, "guard_deadline.py"), scenario,
                            str(deadline)], input=data, capture_output=True, text=True, env=self.denv,
                           cwd=self.repo, timeout=60)
        return r, time.monotonic() - t0

    def assert_limit(self, r, dt, lo=2.9, hi=4.5):
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        out = _deny_lines(r.stdout)
        self.assertEqual(len(out), 1, r.stdout)
        self.assertEqual(out[0]["permissionDecision"], "deny")
        self.assertTrue(out[0]["permissionDecisionReason"].startswith(DEADLINE_TEXT), out[0])
        self.assertIn("(INV9)", out[0]["permissionDecisionReason"])
        self.assertTrue(lo <= dt <= hi, dt)

    def test_plain_folder_sed_row(self):
        p = _PLAIN["proc"]
        _PLAIN["thread"].join(60)
        out, err = _PLAIN["result"]
        dt = _PLAIN["dt"]
        self.assertEqual(p.returncode, 0, err[-800:])
        lines = _deny_lines(out.decode())
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0]["permissionDecisionReason"].startswith(DEADLINE_TEXT), lines[0])
        self.assertTrue(14.5 <= dt <= 17.0, dt)

    def test_g1_overrun(self):
        self.assert_limit(*self.drive("g1_sleep", "ls"))

    def test_slow_deny_write(self):  # review 2 M: the timer is stopped before the G-LIMIT write
        self.assert_limit(*self.drive("g1_sleep_slow_deny", "ls"))

    def test_large_input_write(self):  # review 2 M: and before the too-large write
        r, dt = self.drive("big_input_slow_deny", None, stdin="{}" + " " * 64)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        out = _deny_lines(r.stdout)
        self.assertEqual(len(out), 1, r.stdout)
        self.assertIn("the tool input is too large for the guard", out[0]["permissionDecisionReason"])
        self.assertGreaterEqual(dt, 5.0)

    def test_frozen_overrun_has_no_effects(self):
        r, dt = self.drive("legacy_sleep", TB.APPROVE + "; source /dev/null")  # 0.1.4: both guards judge it
        self.assert_limit(r, dt)
        self.assertFalse(os.path.exists(self.local("pending-approval.json")))
        self.assertFalse(os.path.exists(self.local("guard-ran.json")))
        r, _dt = self.drive("none", TB.APPROVE)  # the same call in time: allowed, with its evidence
        self.assertEqual(_deny_lines(r.stdout)[0]["permissionDecision"], "allow", r.stdout)
        self.assertTrue(os.path.exists(self.local("pending-approval.json")))

    def test_slow_record_after_pass(self):  # review 1 M1
        r, dt = self.drive("record_sleep", "git status")
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr[-800:])
        self.assertGreaterEqual(dt, 5.0)
        self.assertTrue(os.path.exists(self.local("guard-ran.json")))

    def test_slow_record_after_deny(self):
        r, dt = self.drive("record_sleep", "rm -rf studio/local")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        out = _deny_lines(r.stdout)
        self.assertEqual(len(out), 1, r.stdout)
        self.assertTrue(out[0]["permissionDecisionReason"].startswith("Studio guard [G-DEL]"), out[0])
        self.assertGreaterEqual(dt, 5.0)

    def test_swallowed_once_fires_again(self):
        r, dt = self.drive("swallow_once", "ls")
        self.assertIn("swallowed", r.stderr)
        self.assert_limit(r, dt, lo=3.2)

    def test_no_timer_judged_as_before(self):
        r, _dt = self.drive("arm_raises", "rm -rf studio/local")
        self.assertIn("arm raised", r.stderr)
        out = _deny_lines(r.stdout)
        self.assertEqual(len(out), 1, r.stdout)
        self.assertTrue(out[0]["permissionDecisionReason"].startswith("Studio guard [G-DEL]"), out[0])
        r, _dt = self.drive("arm_raises", "git status")
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr[-800:])

    def test_former_hangs_in_time(self):  # fix-0103 §1 repros through guard.py
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain, exist_ok=True)
        cases = (('arr=(/opt/work/projects/sdd-plugin/plugins/x "$x"); echo $arr', plain, ""),
                 (": ${X::=" + "$aaaaaaaaaaaa" * 8 + "*}", plain, ""),
                 ("sed -n -e '" + "\n" * 6000 + "p' a.txt", self.repo, "Studio guard [G-OPAQUE]"))
        for cmd, cwd, want in cases:
            hook = helpers.hook_input("Bash", {"command": cmd}, cwd)
            t0 = time.monotonic()
            r = subprocess.run([sys.executable, GUARD], input=json.dumps(hook), capture_output=True, text=True,
                               env=self.denv, cwd=cwd, timeout=60)
            dt = time.monotonic() - t0
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            if want:
                self.assertTrue(_deny_lines(r.stdout)[0]["permissionDecisionReason"].startswith(want), r.stdout)
            else:
                self.assertEqual(r.stdout, "", cmd[:40])
            self.assertLess(dt, 2.0, cmd[:40])


class Timer(unittest.TestCase):
    """limits.arm / disarm in process (the signal handler and timer are restored after each test)."""

    def setUp(self):
        self.saved = signal.getsignal(signal.SIGALRM)
        self.addCleanup(signal.signal, signal.SIGALRM, self.saved)
        self.addCleanup(signal.setitimer, signal.ITIMER_REAL, 0)
        self.addCleanup(limits.disarm)

    def test_deadline_is_not_an_exception(self):
        self.assertTrue(issubclass(limits.HookDeadline, BaseException))
        self.assertFalse(issubclass(limits.HookDeadline, Exception))
        self.assertLess(limits.HOOK_DEADLINE + 2, 20)  # the hook's timeout (hooks.json)

    def test_arm_fires_and_refires(self):
        old = limits.HOOK_DEADLINE
        limits.HOOK_DEADLINE = 0.05
        try:
            limits.arm()
        finally:
            limits.HOOK_DEADLINE = old
        hits = 0
        end = time.monotonic() + 3
        while True:
            try:
                if hits >= 2 or time.monotonic() > end:
                    limits.disarm()
                    break
                time.sleep(0.5)
            except limits.HookDeadline:
                hits += 1
        self.assertEqual(hits, 2)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))

    def test_armed_only_once_the_timer_runs(self):
        orig = signal.setitimer

        def boom(*a):
            raise OSError("no timer")
        signal.setitimer = boom
        try:
            with self.assertRaises(OSError):
                limits.arm()
        finally:
            signal.setitimer = orig
        self.assertEqual(limits._ARMED, [])

    def test_disarm_never_raises(self):
        limits.disarm()  # not armed: a no-op
        limits._ARMED[:] = [True]
        orig = signal.setitimer

        def boom(*a):
            raise OSError("broken")
        signal.setitimer = boom
        try:
            limits.disarm()
        finally:
            signal.setitimer = orig
        self.assertEqual(limits._ARMED, [])

    def test_late_signal_after_disarm_is_dropped(self):
        limits.arm()
        limits.disarm()
        limits._late(signal.SIGALRM, None)  # a signal queued before the disarm: nothing


if __name__ == "__main__":
    unittest.main()
