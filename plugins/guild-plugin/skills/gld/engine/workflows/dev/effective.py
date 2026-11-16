"""workflows.dev.effective — the TEST `effective` code check (§3.3, R6J-M2, R7J-m1). No Claude call.

A judge's `effective` verdict for an AC stands only when the code agrees:

① assertion present — the cited test's body (the named test's ±40 lines, else the file) has an
   assertion line for its runner, trivial ones excluded (`toBeTruthy()`, `toBeDefined()`,
   `assert True`, `assertTrue(True)`, `expect(true, isTrue)`, `expect(true).toBe(true)`).
② revert-and-rerun — for a tester `covers` entry of `kind: new` only (`guard` → ① only): in a
   TEMPORARY worktree at HEAD with the developer's impl files (`impl_files`, base-relative diff)
   reverted to `<base>` (added files removed), the test alone is re-run under the owning role's
   sandbox (the `check` port) and must FAIL WITH AN ASSERTION/TEST FAILURE as classified by the
   §2.8 parser (`checks.failure_kind`) — a collection/compile/import error, a pass, or an
   unreadable output is `unsure`.
Any miss → the AC's verdict becomes `unsure` (caller: tester mapping repair once, then uncovered,
no capture). The temporary worktree gets the main worktree's gitignored entries (directories
symlinked, files copied — build caches, generated sources) so the re-run needs no network.
"""

import os
import re
import shlex
import shutil
import tempfile

from guildcore import checks as CH
from guildcore.adapters import git as G

ASSERT_RES = {
    "flutter": r"\b(expect|expectLater|expectAsync\d?|matchesGoldenFile)\s*\(",
    "jest": r"\bexpect\s*\(|\bassert(\.\w+)?\s*\(",
    "pytest": r"^\s*assert\b|\bself\.assert\w+\s*\(|\bpytest\.raises\s*\(",
    "unittest": r"\bself\.assert\w+\s*\(|^\s*assert\b",
    "go": r"\bt\.(Error|Errorf|Fatal|Fatalf|Fail|FailNow)\s*\(|\b(assert|require)\.\w+\s*\(",
}
ASSERT_RES["dart"] = ASSERT_RES["flutter"]
ASSERT_RES["vitest"] = ASSERT_RES["jest"]
TRIVIAL_RES = (r"\.toBeTruthy\(\s*\)", r"\.toBeDefined\(\s*\)", r"^\s*assert\s+True\b",
               r"assertTrue\(\s*True\s*\)", r"expect\(\s*true\s*,\s*(isTrue|true)\s*\)",
               r"expect\(\s*true\s*\)\.toBe\(\s*true\s*\)")
TEST_FILE_RE = re.compile(r"[\w./-]*?(?:_test\.dart|_test\.go|\.test\.[jt]sx?|\.spec\.[jt]sx?|"
                          r"(?:^|/)test_\w+\.py|_test\.py|\.vitest\.[jt]sx?)")
TEST_PATH_RE = re.compile(r"(^|/)(test|tests|__tests__|spec|integration_test)/|_test\.|\.test\.|\.spec\.|(^|/)test_")
EXCERPT = 40


def runner_of(cfg, path=""):
    cmd = (cfg.get("commands") or {}).get("test") or ""
    cmd = " ".join(cmd) if isinstance(cmd, list) else cmd
    for key, rn in (("flutter", "flutter"), ("dart test", "dart"), ("vitest", "vitest"), ("jest", "jest"),
                    ("pytest", "pytest"), ("go test", "go"), ("unittest", "unittest")):
        if key in cmd:
            return rn
    ext = os.path.splitext(path)[1]
    return {".dart": "flutter", ".py": "pytest", ".go": "go", ".ts": "jest", ".tsx": "jest",
            ".js": "jest", ".jsx": "jest"}.get(ext)


def parse_test_ref(ref):
    """`covers[].test` → (file, name|None): `path::name`, `path — name`, `name (path)`, `path`."""
    ref = (ref or "").strip()
    m = TEST_FILE_RE.search(ref)
    if not m:
        return None, ref or None
    path = m.group(0)
    rest = (ref[:m.start()] + " " + ref[m.end():]).strip()
    rest = rest.strip(" \t()«»:—-'\"`")
    return path, (rest or None)


def excerpt(text, name):
    lines = (text or "").split("\n")
    if name:
        for i, ln in enumerate(lines):
            if name in ln:
                return "\n".join(lines[max(0, i - EXCERPT):i + EXCERPT + 1])
    return "\n".join(lines[:EXCERPT * 10])


def has_assertion(snippet, runner):
    rx = ASSERT_RES.get(runner)
    if not rx:
        return False
    for ln in (snippet or "").split("\n"):
        if re.search(rx, ln) and not any(re.search(t, ln) for t in TRIVIAL_RES):
            return True
    return False


def single_command(cfg, runner, path, name):
    tmpl = (cfg.get("commands") or {}).get("test_one")
    q = shlex.quote
    if tmpl:
        return tmpl.replace("{file}", q(path)).replace("{name}", q(name or ""))
    if runner == "flutter":
        return "flutter test %s%s" % (q(path), " --plain-name %s" % q(name) if name else "")
    if runner == "dart":
        return "dart test %s%s" % (q(path), " --plain-name %s" % q(name) if name else "")
    if runner == "jest":
        return "npx jest %s%s" % (q(path), " -t %s" % q(name) if name else "")
    if runner == "vitest":
        return "npx vitest run %s%s" % (q(path), " -t %s" % q(name) if name else "")
    if runner == "pytest":
        return "python3 -m pytest %s%s" % (q(path), " -k %s" % q(name) if name else "")
    if runner == "unittest":
        mod = path[:-3].replace("/", ".") if path.endswith(".py") else path
        return "python3 -m unittest -v %s" % q(mod + ("." + name if name else ""))
    if runner == "go":
        d = os.path.dirname(path) or "."
        return "go test ./%s%s" % (d, " -run %s" % q("^%s$" % name) if name else "")
    return None


def impl_files(root, base, given=None):
    """The developer's `impl_files` (execute's result.json), else derived: files changed since
    `base` that are not test paths (recorded as `impl_source: derived`)."""
    if given:
        return list(given), "result"
    out = G.run(root, "diff", "--name-only", "%s...HEAD" % base, check=False).decode()
    return [f for f in out.split("\n") if f and not TEST_PATH_RE.search(f)], "derived"


class TempTree(object):
    """`git worktree add --detach` at HEAD with impl files reverted to `base`; removed on exit."""

    def __init__(self, root, base, files, parent=None):
        self.root, self.base, self.files = root, base, files
        self.parent = parent
        self.path = None

    def __enter__(self):
        d = tempfile.mkdtemp(prefix="gld-eff-", dir=self.parent)
        os.rmdir(d)
        self.path = d
        G.run(self.root, "worktree", "add", "--detach", "--quiet", d, "HEAD")
        ignored = G.run(self.root, "ls-files", "--others", "--ignored", "--exclude-standard",
                        "--directory", check=False).decode().split("\n")
        for e in [x for x in ignored if x]:
            src, dst = os.path.join(self.root, e.rstrip("/")), os.path.join(d, e.rstrip("/"))
            if os.path.lexists(dst) or not os.path.exists(src):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(src):
                os.symlink(src, dst)
            else:
                shutil.copy2(src, dst)
        for f in self.files:
            if G.ok(self.root, "cat-file", "-e", "%s:%s" % (self.base, f)):
                G.run(d, "checkout", self.base, "--", f)
            elif os.path.lexists(os.path.join(d, f)):
                os.remove(os.path.join(d, f))
        return d

    def __exit__(self, *exc):
        if self.path:
            G.run(self.root, "worktree", "remove", "--force", self.path, check=False)
            shutil.rmtree(self.path, True)
            G.run(self.root, "worktree", "prune", check=False)
        return False


class CheckOutcome(object):
    def __init__(self, ac, test, result, why, kind=None):
        self.ac, self.test, self.result, self.why, self.kind = ac, test, result, why, kind

    def as_field(self):
        return "%s=%s" % (self.ac, self.result)


def check_ac(p, cfg, ac, covers, base, impl, tree=None, timeout_s=900):
    """One AC the judge called `effective`. `covers` = that AC's tester entries. Returns a
    CheckOutcome with result `pass` | `fail` (no assertion) | `unsure`."""
    if not covers:
        return CheckOutcome(ac, None, "unsure", "no covering test named by the tester")
    for cv in covers:
        path, name = parse_test_ref(cv.get("test"))
        runner = runner_of(cfg, path or "")
        text = p.read_file(path) if path else None
        if text is None:
            return CheckOutcome(ac, cv.get("test"), "unsure", "cited test file not found")
        if not has_assertion(excerpt(text, name), runner):
            return CheckOutcome(ac, cv.get("test"), "fail", "no non-trivial assertion in the cited test")
        if cv.get("kind") != "new":
            continue
        if tree is None or not base:
            return CheckOutcome(ac, cv.get("test"), "unsure", "no base to revert against")
        cmd = single_command(cfg, runner, path, name)
        if not cmd:
            return CheckOutcome(ac, cv.get("test"), "unsure", "no single-test command for runner %s" % runner)
        r = p.check(cmd, tree, "tester", timeout_s, [tree])
        kind = "load_error" if r.timed_out else CH.failure_kind(r.raw, runner, passed=r.passed)
        if kind != "assertion":
            why = {"passed": "test still passes with the impl reverted",
                   "load_error": "re-run failed to load/compile — not an assertion failure",
                   "unknown": "re-run output unreadable"}[kind]
            return CheckOutcome(ac, cv.get("test"), "unsure", why, kind)
    return CheckOutcome(ac, covers[0].get("test"), "pass", "assertion present; reacts to the reverted impl")


def run(p, cfg, effective_acs, covers_by_ac, base, given_impl=None, timeout_s=900):
    """Check every AC the judge called effective. Returns ({ac: CheckOutcome}, impl_source)."""
    out = {}
    needs_tree = any(cv.get("kind") == "new" for ac in effective_acs for cv in covers_by_ac.get(ac, []))
    if not effective_acs:
        return out, None
    impl, src = impl_files(p.root, base, given_impl) if base else ([], None)
    if needs_tree and base and impl:
        with TempTree(p.root, base, impl) as tree:
            for ac in effective_acs:
                out[ac] = check_ac(p, cfg, ac, covers_by_ac.get(ac, []), base, impl, tree, timeout_s)
    else:
        for ac in effective_acs:
            out[ac] = check_ac(p, cfg, ac, covers_by_ac.get(ac, []), base, impl, None, timeout_s)
    return out, src
