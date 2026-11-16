"""workflows.dev.effective — the TEST `effective` code check (§3.3, R6J-M2, R7J-m1). No Claude call.

A judge's `effective` verdict for an AC stands only when the code agrees. Per AC the check
returns one of

    pass        ① and (for `kind: new`) ② hold
    fail        ① fails: the cited test's own body has no reachable, non-trivial assertion
    unsure      the evidence says NOT effective: test file/body not found, the re-run still
                passes with the impl reverted, or it fails with a non-assertion (runtime) error
    unverified  the check could not run as intended (no base, runner the engine cannot drive,
                no exact single-test command, the filter ran ≠ 1 test, a compile/import error
                after the revert, the temp tree failed, timeout) — the SJ-TEST verdict STANDS,
                the decision is flagged for the §9.5 human sample (K2 review B3: "cannot check"
                is not "ineffective" — a loop-back there regresses a healthy Issue)

① assertion present — scoped to the cited test's OWN block (a per-runner block parser: the
   `test(...)`/`testWidgets(...)`/`it(...)` call, `def name` indented body, `func Name` braces);
   comments are stripped, `if false {…}` / `if False:` blocks dropped, and an assertion whose
   argument is constant-only (`expect(1).toBe(1)`, `assert True`, `assertEqual(True, True)`,
   `expect(1, 1)`) does not count. No test name → `unsure` (never the whole file).
② revert-and-rerun (`kind: new` only) — a TEMPORARY worktree at HEAD with the developer's impl
   files reverted to `<base>` (only tracked, relative paths that resolve inside the temp tree —
   K2-B4), the test re-run alone with an EXACT filter; it counts only when the runner's own
   ASSERTION-failure signature is attributed to that test (flutter `Expected:`/`Actual:`, jest
   `expect(received)`/`Received:`, pytest `E   assert`/`AssertionError`, go `x_test.go:N:` with no
   `panic:`, unittest `FAIL:` + `AssertionError`) — K2-B1.
The temp tree gets the main worktree's gitignored FILES copied; `.dart_tool/` is re-created with its
top-level files copied; other ignored directories are symlinked read-only (the check's sandbox
denies writes to the main worktree — ports.py).
"""

import os
import re
import shlex
import shutil
import tempfile

from guildcore import checks as CH
from guildcore.adapters import git as G

BRACE = ("flutter", "dart", "jest", "vitest", "go")
ASSERT_RES = {
    "flutter": r"\b(expect|expectLater|expectAsync\d?|matchesGoldenFile|fail)\s*\(",
    "jest": r"\b(expect|assert(?:\.\w+)?)\s*\(",
    "pytest": r"(^|\s)assert\b|\bself\.assert\w+\s*\(|\bpytest\.raises\s*\(",
    "unittest": r"\bself\.assert\w+\s*\(|(^|\s)assert\b",
    "go": r"\bt\.(Error|Errorf|Fatal|Fatalf|Fail|FailNow)\s*\(|\b(assert|require)\.\w+\s*\(",
}
ASSERT_RES["dart"] = ASSERT_RES["flutter"]
ASSERT_RES["vitest"] = ASSERT_RES["jest"]
TEST_FILE_RE = re.compile(r"[\w./-]*?(?:_test\.dart|_test\.go|\.test\.[jt]sx?|\.spec\.[jt]sx?|"
                          r"(?:^|/)test_\w+\.py|_test\.py|\.vitest\.[jt]sx?)")
# test paths for the DERIVED impl list (K2-m8): directories and file-name conventions, not a bare
# `test_` prefix anywhere (lib/test_utils.dart is source)
TEST_PATH_RE = re.compile(r"(^|/)(test|tests|__tests__|spec|integration_test|testdata)/|_test\.(dart|go|py)$|"
                          r"\.(test|spec)\.[jt]sx?$|(^|/)test_[^/]*\.py$")
EXCERPT_CAP = 200
LITERAL_WORDS = {"true", "false", "null", "none", "nil", "and", "or", "not", "is", "in", "istrue",
                 "isfalse", "isnull", "isnotnull", "equals", "undefined", "tobe", "toequal", "tobetruthy",
                 "tobedefined", "tobefalsy"}


# ---- runner ------------------------------------------------------------------------------------

def runner_of(cfg, path=""):
    """The runner the configured command shows. A command that does not name one (`npm test`,
    `turbo test`, `make test` …) → None (K2-B3: no guessing by extension) unless
    `commands.test_one` is set (then its own text decides)."""
    cmds = cfg.get("commands") or {}
    for key in ("test_one", "test"):
        cmd = cmds.get(key) or ""
        cmd = " ".join(cmd) if isinstance(cmd, list) else cmd
        for k, rn in (("flutter", "flutter"), ("dart test", "dart"), ("vitest", "vitest"), ("jest", "jest"),
                      ("pytest", "pytest"), ("go test", "go"), ("unittest", "unittest")):
            if k in cmd:
                return rn
    return None


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


# ---- a linear scanner: code without comments, string spans known ---------------------------------

def _scan(text, runner):
    """Yield (index, char, in_string) for code characters; comments are skipped."""
    i, n = 0, len(text)
    py = runner in ("pytest", "unittest")
    quote = None
    while i < n:
        c = text[i]
        if quote:
            if c == "\\":
                yield i, c, True
                if i + 1 < n:
                    yield i + 1, text[i + 1], True
                i += 2
                continue
            if text.startswith(quote, i):
                for k in range(len(quote)):
                    yield i + k, text[i + k], True
                i += len(quote)
                quote = None
                continue
            yield i, c, True
            i += 1
            continue
        if py and c == "#":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if not py and text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if not py and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        for q in ('"""', "'''", '"', "'", "`"):
            if text.startswith(q, i) and (q != "`" or not py):
                quote = q
                for k in range(len(q)):
                    yield i + k, text[i + k], True
                i += len(q)
                break
        else:
            yield i, c, False
            i += 1


def code_only(text, runner):
    """`text` with comments removed (strings kept)."""
    last, chars = 0, []
    for i, c, _s in _scan(text, runner):
        if i != last:
            chars.append("\n" * text.count("\n", last, i))     # keep line structure
        chars.append(c)
        last = i + 1
    return "".join(chars)


def _balanced_end(text, start, runner):
    """Index after the bracket that closes the first `(`/`{` at or after `start`."""
    depth, opened = 0, False
    for i, c, s in _scan(text[start:], runner):
        if s:
            continue
        if c in "({[":
            depth += 1
            opened = True
        elif c in ")}]":
            depth -= 1
            if opened and depth == 0:
                return start + i + 1
    return None


def test_body(text, name, runner):
    """(body, first_line) of the named test's own block, or None."""
    if not name or not text:
        return None
    if runner in ("pytest", "unittest"):
        short = re.split(r"::|\.", name)[-1]
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            m = re.match(r"^(\s*)(?:async\s+)?def\s+%s\s*\(" % re.escape(short), ln)
            if m:
                ind = len(m.group(1))
                body = [ln]
                for nxt in lines[i + 1:]:
                    if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= ind:
                        break
                    body.append(nxt)
                return "\n".join(body), i + 1
        return None
    if runner == "go":
        m = re.search(r"(?m)^func\s+%s\s*\(" % re.escape(name.split("/")[-1]), text)
        if not m:
            return None
        brace = text.find("{", m.end())
        end = _balanced_end(text, brace, runner) if brace >= 0 else None
        return (text[m.start():end], text.count("\n", 0, m.start()) + 1) if end else None
    rx = re.compile(r"\b(?:test|testWidgets|testGoldens|it|blocTest|patrolTest)\s*\(\s*(['\"`])(.*?)\1")
    for m in rx.finditer(text):
        lit = m.group(2)
        if lit and (lit == name or name.endswith(" " + lit) or name.endswith("› " + lit)):
            paren = text.find("(", m.start())
            end = _balanced_end(text, paren, runner)
            if end:
                return text[m.start():end], text.count("\n", 0, m.start()) + 1
    return None


def _drop_unreachable(code, runner):
    if runner in ("pytest", "unittest"):
        lines, out, skip = code.split("\n"), [], None
        for ln in lines:
            ind = len(ln) - len(ln.lstrip())
            if skip is not None:
                if ln.strip() and ind <= skip:
                    skip = None
                else:
                    continue
            if re.match(r"^\s*if\s+(False|0|None)\s*:", ln):
                skip = ind
                continue
            out.append(ln)
        return "\n".join(out)
    while True:
        m = re.search(r"\bif\s*\(?\s*(false|0)\s*\)?\s*\{", code)
        if not m:
            return code
        end = _balanced_end(code, m.end() - 1, runner)
        if not end:
            return code
        code = code[:m.start()] + "\n" * code.count("\n", m.start(), end) + code[end:]


def _args(code, open_idx, runner):
    end = _balanced_end(code, open_idx, runner)
    return code[open_idx + 1:end - 1] if end else ""


def _constant_only(expr):
    s = re.sub(r"(\"\"\"|''')[\s\S]*?\1|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`[^`]*`", " 0 ", expr)
    for w in re.findall(r"[A-Za-z_]\w*", s):
        if w.lower() not in LITERAL_WORDS and w != "t":
            return False
    return True


def has_assertion(snippet, runner):
    """(bool, line_offset|None): a reachable, non-trivial assertion in `snippet` (one test's
    block). Comments never count; an assertion over constants only does not count."""
    rx = ASSERT_RES.get(runner)
    if not rx or not snippet:
        return False, None
    code = _drop_unreachable(code_only(snippet, runner), runner)
    if runner == "go":
        for m in re.finditer(rx, code):
            line = code.count("\n", 0, m.start())
            if m.group(1):                       # t.Error*: the guarding `if` condition decides
                head = code[:m.start()]
                cond = re.findall(r"\bif\s+([^{]*)\{", head)
                if cond and _constant_only(cond[-1]):
                    continue
                return True, line
            paren = code.find("(", m.end() - 1)
            if not _constant_only(_args(code, paren, runner)):
                return True, line
        return False, None
    for m in re.finditer(rx, code, re.M):
        line = code.count("\n", 0, m.start())
        if runner in ("pytest", "unittest") and not m.group(0).strip().startswith(("self", "pytest")):
            expr = code[m.end():code.find("\n", m.end()) if code.find("\n", m.end()) >= 0 else len(code)]
            if not _constant_only(expr.split(",")[0]):
                return True, line
            continue
        paren = code.find("(", m.end() - 1)
        args = _args(code, paren, runner)
        first = args.split(",")[0] if runner in ("flutter", "dart", "jest", "vitest") and \
            m.group(0).lstrip().startswith("expect") else args
        if m.group(0).strip().startswith("fail"):
            return True, line
        if not _constant_only(first):
            return True, line
    return False, None


# ---- the exact single-test command and its verdict -----------------------------------------------

def single_command(cfg, runner, path, name):
    tmpl = (cfg.get("commands") or {}).get("test_one")
    q = shlex.quote
    if tmpl:
        return tmpl.replace("{file}", q(path)).replace("{name}", q(name or ""))
    if not name:
        return None
    exact = "(^| )%s$" % re.escape(name.split(" › ")[-1] if " › " in name else name)
    if runner in ("flutter", "dart"):
        return "%s test %s --name %s" % ("flutter" if runner == "flutter" else "dart", q(path), q(exact))
    if runner == "jest":
        return "npx jest %s -t %s" % (q(path), q(exact))
    if runner == "vitest":
        return "npx vitest run %s -t %s" % (q(path), q(exact))
    if runner == "pytest":
        return "python3 -m pytest %s" % q("%s::%s" % (path, name.replace(".", "::")))
    if runner == "unittest":
        mod = path[:-3].replace("/", ".") if path.endswith(".py") else path
        return "python3 -m unittest -v %s" % q(mod + "." + name.replace("::", "."))
    if runner == "go":
        d = os.path.dirname(path) or "."
        return "go test -v ./%s -run %s" % (d, q("^%s$" % re.escape(name)))
    return None


def _executed(raw, runner):
    if runner == "go":
        return len(set(re.findall(r"(?m)^=== RUN\s+(\S+)$", raw or "")))
    s = CH.parse_summary(raw, runner)
    return (s.passed + s.failed) if s is not None else None


def rerun_kind(raw, runner, name, passed):
    """assertion | passed | runtime | load_error | ambiguous | unknown (K2-B1)."""
    raw = raw or ""
    n = _executed(raw, runner)
    if n is not None and n != 1:
        return "ambiguous"
    short = (name or "").split(" › ")[-1].split("::")[-1].split(".")[-1]
    s = CH.parse_summary(raw, runner)
    if runner == "go":
        if passed or re.search(r"(?m)^--- PASS: ", raw) and not re.search(r"(?m)^--- FAIL: ", raw):
            return "passed"
        if not re.search(r"(?m)^--- FAIL: %s\b" % re.escape(name or ""), raw):
            return "load_error" if re.search(r"\[build failed\]|\[setup failed\]", raw) else "unknown"
        if "panic:" in raw:
            return "runtime"
        return "assertion" if re.search(r"(?m)^\s+\w+_test\.go:\d+: ", raw) else "runtime"
    if s is None:
        return "passed" if passed else "unknown"
    if s.failed == 0:
        return "passed"
    for rx in CH.LOAD_ERROR_RES.get(runner, ()):
        if re.search(rx, raw, re.M) and runner != "unittest":
            return "load_error"
    if runner in ("flutter", "dart"):
        if not re.search(r"(?m)^\d\d:\d\d \+\d+(?: ~\d+)? -\d+: .*%s.* \[E\]\s*$" % re.escape(short), raw):
            return "unknown"
        return "assertion" if re.search(r"(?m)^\s*Expected: ", raw) and re.search(r"(?m)^\s*Actual: ", raw) else "runtime"
    if runner in ("jest", "vitest"):
        if not re.search(r"●.*%s" % re.escape(short), raw) and not re.search(r"(×|FAIL).*%s" % re.escape(short), raw):
            return "unknown"
        return "assertion" if ("expect(received)" in raw or (re.search(r"(?m)^\s*Expected:", raw) and
                                                             re.search(r"(?m)^\s*Received:", raw))) else "runtime"
    if runner == "pytest":
        if not re.search(r"(?m)^FAILED \S*%s" % re.escape(short), raw):
            return "unknown"
        err = re.findall(r"(?m)^E\s+(\w+(?:Error|Exception))\b", raw)
        if err and err[0] != "AssertionError":
            return "runtime"
        return "assertion" if re.search(r"(?m)^E\s+assert\b", raw) or "AssertionError" in raw else "runtime"
    if runner == "unittest":
        if re.search(r"(?m)^ERROR: ", raw):
            ie = re.search(r"ImportError|ModuleNotFoundError|SyntaxError|_FailedTest", raw)
            return "load_error" if ie else "runtime"
        return "assertion" if re.search(r"(?m)^FAIL: %s\b" % re.escape(short), raw) and "AssertionError" in raw else "runtime"
    return "unknown"


# ---- impl files and the temporary tree -----------------------------------------------------------

def safe_rel(root, f, revs):
    """`f` normalised, relative, no `..`, tracked at one of `revs` — else None (K2-B4)."""
    if not f or os.path.isabs(f) or "\0" in f:
        return None
    n = os.path.normpath(f)
    if n.startswith("..") or n == "." or os.path.isabs(n):
        return None
    if not any(G.ok(root, "cat-file", "-e", "%s:%s" % (r, n)) for r in revs if r):
        return None
    return n


def default_base(root):
    """`git merge-base <origin default> HEAD` when the caller has no base (K2-B3)."""
    ref = G.run(root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD", check=False).decode().strip()
    cands = [ref] if ref else []
    cands += ["refs/remotes/origin/main", "refs/remotes/origin/master"]
    for c in cands:
        mb = G.run(root, "merge-base", c, "HEAD", check=False).decode().strip()
        if mb and mb != G.run(root, "rev-parse", "HEAD", check=False).decode().strip():
            return mb
    return None


def impl_files(root, base, given=None):
    """(files, source, rejected): the developer's `impl_files` (execute's result.json) or, when
    absent, files changed since `base` that are not test paths (`derived`). Unsafe entries are
    rejected (K2-B4) and returned for the decision log."""
    if given:
        raw, src = list(given), "result"
    else:
        out = G.run(root, "diff", "--name-only", "%s...HEAD" % base, check=False).decode()
        raw, src = [f for f in out.split("\n") if f and not TEST_PATH_RE.search(f)], "derived"
    ok, bad = [], []
    for f in raw:
        s = safe_rel(root, f, ("HEAD", base))
        (ok if s else bad).append(s or f)
    return ok, src, bad


class TempTree(object):
    """`git worktree add --detach` at HEAD with impl files reverted to `base`; removed on exit
    (also when entering fails half way — K2-m6). Every path operated on must resolve inside the
    temp tree with no symlink component (K2-B4)."""

    def __init__(self, root, base, files, parent=None):
        self.root, self.base, self.files = root, base, files
        self.parent = parent
        self.path = None

    def _inside(self, rel):
        real_root = os.path.realpath(self.path)
        cur = self.path
        for part in rel.split(os.sep):
            cur = os.path.join(cur, part)
            if os.path.islink(cur):
                return None
        dst = os.path.join(self.path, rel)
        if not os.path.realpath(dst).startswith(real_root + os.sep):
            return None
        return dst

    def __enter__(self):
        d = tempfile.mkdtemp(prefix="gld-eff-", dir=self.parent)
        os.rmdir(d)
        self.path = d
        try:
            G.run(self.root, "worktree", "add", "--detach", "--quiet", d, "HEAD")
            self._ignored()
            for f in self.files:
                dst = self._inside(f)
                if dst is None:
                    raise ValueError("impl path escapes the temp tree: %s" % f)
                if G.ok(self.root, "cat-file", "-e", "%s:%s" % (self.base, f)):
                    G.run(d, "checkout", self.base, "--", f)
                elif os.path.lexists(dst):
                    os.remove(dst)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return d

    def _ignored(self):
        lines = G.run(self.root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard",
                      "--directory", check=False).decode("utf-8", "replace").split("\0")
        for e in [x for x in lines if x]:
            rel = os.path.normpath(e.rstrip("/"))
            if rel.startswith("..") or os.path.isabs(rel):
                continue
            src = os.path.join(self.root, rel)
            dst = self._inside(rel)
            if dst is None or os.path.lexists(dst) or not os.path.exists(src) or os.path.islink(src):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(src):
                if os.path.basename(rel) == ".dart_tool":
                    os.makedirs(dst)                   # its own build state; package config copied
                    for fn in os.listdir(src):
                        if os.path.isfile(os.path.join(src, fn)):
                            shutil.copy2(os.path.join(src, fn), os.path.join(dst, fn))
                else:
                    os.symlink(src, dst)               # read-only use: writes denied by the check sandbox
            else:
                shutil.copy2(src, dst)

    def __exit__(self, *exc):
        if self.path:
            G.run(self.root, "worktree", "remove", "--force", self.path, check=False)
            shutil.rmtree(self.path, True)
            G.run(self.root, "worktree", "prune", check=False)
        return False


# ---- per AC ------------------------------------------------------------------------------------

class CheckOutcome(object):
    def __init__(self, ac, test, result, why, kind=None, line=None, cmd=None):
        self.ac, self.test, self.result, self.why, self.kind = ac, test, result, why, kind
        self.line, self.cmd = line, cmd

    def as_field(self):
        s = "%s=%s" % (self.ac, self.result)
        if self.result == "unverified":
            s += "(%s)" % self.why
        return s

    def detail(self):
        """§9.5 citation material: the test, its assertion line, the re-run and its class."""
        return {"ac": self.ac, "test": self.test, "assert": self.line, "cmd": self.cmd,
                "rerun": self.kind, "result": self.result, "why": self.why}


def check_ac(p, cfg, ac, covers, base, tree=None, timeout_s=900, tree_error=None):
    if not covers:
        return CheckOutcome(ac, None, "unsure", "no covering test named by the tester")
    runner = runner_of(cfg)
    if runner is None or runner not in ASSERT_RES:
        return CheckOutcome(ac, covers[0].get("test"), "unverified", "runner not drivable by the engine")
    first_line, last_cmd = None, None
    for cv in covers:
        path, name = parse_test_ref(cv.get("test"))
        text = p.read_file(path) if path else None
        if text is None:
            return CheckOutcome(ac, cv.get("test"), "unsure", "cited test file not found")
        tb = test_body(text, name, runner)
        if tb is None:
            return CheckOutcome(ac, cv.get("test"), "unsure", "cited test body not found (name required)")
        ok, off = has_assertion(tb[0], runner)
        if not ok:
            return CheckOutcome(ac, cv.get("test"), "fail", "no reachable non-trivial assertion in the cited test")
        first_line = first_line or "%s:%d" % (path, tb[1] + off)
        if cv.get("kind") != "new":
            continue
        if not base:
            return CheckOutcome(ac, cv.get("test"), "unverified", "no base", line=first_line)
        if tree is None:
            return CheckOutcome(ac, cv.get("test"), "unverified", "temp tree: %s" % (tree_error or "unavailable"),
                                line=first_line)
        cmd = single_command(cfg, runner, path, name)
        if not cmd:
            return CheckOutcome(ac, cv.get("test"), "unverified", "no exact single-test command", line=first_line)
        last_cmd = cmd
        r = p.check(cmd, tree, "tester", timeout_s, [tree])
        kind = "timeout" if r.timed_out else rerun_kind(r.raw, runner, name, r.passed)
        if kind == "assertion":
            continue
        if kind in ("passed", "runtime"):
            why = {"passed": "test still passes with the impl reverted",
                   "runtime": "re-run failed with a non-assertion error"}[kind]
            return CheckOutcome(ac, cv.get("test"), "unsure", why, kind, first_line, cmd)
        why = {"load_error": "compile/import error after the revert", "ambiguous": "filter did not run exactly one test",
               "unknown": "re-run output unreadable", "timeout": "re-run timed out"}[kind]
        return CheckOutcome(ac, cv.get("test"), "unverified", why, kind, first_line, cmd)
    return CheckOutcome(ac, covers[0].get("test"), "pass", "assertion present; reacts to the reverted impl",
                        "assertion" if last_cmd else None, first_line, last_cmd)


def run(p, cfg, effective_acs, covers_by_ac, base, given_impl=None, timeout_s=900):
    """Check every AC the judge called effective. Returns ({ac: CheckOutcome}, meta)."""
    out, meta = {}, {"impl_source": None, "rejected": [], "base": base}
    if not effective_acs:
        return out, meta
    if not base and p.root and os.path.isdir(p.root) and G.ok(p.root, "rev-parse", "--git-dir"):
        base = default_base(p.root)
        meta.update(base=base, base_source="merge-base" if base else None)
    needs_tree = any(cv.get("kind") == "new" for ac in effective_acs for cv in covers_by_ac.get(ac, []))
    tree_err = None
    if needs_tree and base:
        impl, src, bad = impl_files(p.root, base, given_impl)
        meta.update(impl_source=src, rejected=bad)
        if impl:
            try:
                with TempTree(p.root, base, impl) as tree:
                    for ac in effective_acs:
                        out[ac] = check_ac(p, cfg, ac, covers_by_ac.get(ac, []), base, tree, timeout_s)
                return out, meta
            except Exception as e:                  # a failed temp tree is "could not check"
                tree_err = "%s" % e
        else:
            tree_err = "no impl files to revert"
    for ac in effective_acs:
        out[ac] = check_ac(p, cfg, ac, covers_by_ac.get(ac, []), base, None, timeout_s, tree_err)
    return out, meta
