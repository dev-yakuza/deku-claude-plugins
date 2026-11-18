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
import contextlib
import shlex
import shutil
import tempfile

from guildcore import checks as CH
from guildcore import fsafe as FS
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
FRESH_DIRS = ("build", "coverage", ".gradle", "target", ".pytest_cache", "__pycache__")
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
    rest = re.sub(r"^(?:::|—|-|:)\s*", "", rest.strip()).strip()
    rest = re.sub(r"\s*\(\s*\)$|^\(\s*|\s*\)$", "", rest).strip()      # `name (path)` leftovers
    pairs = {"'": "'", '"': '"', "`": "`", "«": "»"}
    if len(rest) > 1 and rest[0] in pairs and rest[-1] == pairs[rest[0]] and rest.count(rest[0]) == 1 + (
            rest[0] == pairs[rest[0]]):
        rest = rest[1:-1]                               # one wrapping pair only — inner quotes stay
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


def masked(text, runner):
    """`code_only` with string CONTENTS replaced by `x` (quotes kept): an `expect(` inside a
    string literal is no assertion (K2r2-B1), and a masked literal is still a constant."""
    last, chars = 0, []
    for i, c, s in _scan(text, runner):
        if i != last:
            chars.append("\n" * text.count("\n", last, i))
        chars.append("x" if s and c not in "'\"`\n" else c)
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
    code = _drop_unreachable(masked(snippet, runner), runner)
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

def rx_escape(s):
    """Escape only regex SYNTAX characters (K2r2-m4): Python's `re.escape` also escapes spaces,
    which a unicode-mode JS RegExp (`-t` in newer jest/vitest) rejects; Dart and JS accept this."""
    return re.sub(r"([.*+?^${}()|\[\]\\/])", r"\\\1", s)


def single_command(cfg, runner, path, name):
    tmpl = (cfg.get("commands") or {}).get("test_one")
    q = shlex.quote
    if tmpl:
        return tmpl.replace("{file}", q(path)).replace("{name}", q(name or ""))
    if not name:
        return None
    exact = "(^| )%s$" % rx_escape(name.split(" › ")[-1] if " › " in name else name)
    if runner in ("flutter", "dart"):
        # --no-pub: checks have no network; dependencies are the engine deps step (K1r4-M2)
        return "%s test %s%s --name %s" % ("flutter" if runner == "flutter" else "dart", q(path),
                                          " --no-pub" if runner == "flutter" else "", q(exact))
    if runner == "jest":
        return "npx jest %s -t %s" % (q(path), q(exact))
    if runner == "vitest":
        return "npx vitest run %s -t %s" % (q(path), q(exact))
    if runner == "pytest":
        return "python3 -m pytest -v -rs %s" % q("%s::%s" % (path, name.replace(".", "::")))
    if runner == "unittest":
        mod = path[:-3].replace("/", ".") if path.endswith(".py") else path
        return "python3 -m unittest -v %s" % q(mod + "." + name.replace("::", "."))
    if runner == "go":
        d = os.path.dirname(path) or "."
        return "go test -v ./%s -run %s" % (d, q("^%s$" % rx_escape(name)))
    return None


def counts(raw, runner):
    """(executed, skipped) of one run — sub-tests and parametrised cases count as their ONE
    parent (go top-level `=== RUN Name`, pytest `path::name[…]` grouped). None when unreadable."""
    raw = raw or ""
    if runner == "go":
        top = set(x for x in re.findall(r"(?m)^=== RUN\s+(\S+)$", raw) if "/" not in x)
        skipped = set(re.findall(r"(?m)^--- SKIP: (\S+)", raw))
        return len(top - skipped), len(skipped)
    s = CH.parse_summary(raw, runner)
    if runner == "pytest":
        nodes = re.findall(r"(?m)^\S+::(\S+?)(?:\[[^\]]*\])? (PASSED|FAILED|SKIPPED|ERROR)", raw)
        if nodes:
            ran = set(n for n, st in nodes if st != "SKIPPED")
            sk = set(n for n, st in nodes if st == "SKIPPED") - ran
            return len(ran), len(sk)
    if s is None:
        return None
    return s.passed + s.failed, s.skipped


FL_RUN_RE = re.compile(r"^\d\d:\d\d \+\d+(?: ~\d+)?(?: -\d+)?: (.+?)(?: \[E\])?\s*$")


def loop_family(raw, runner, name, executed=None):
    """K2r4-m1: a family of tests generated in a loop — the same literal name across iterations,
    or under per-iteration groups (`group(ko/ja/en)`) — counts as ONE test, like a pytest
    parametrize or a go sub-test: every test the filter ran ends with the cited literal name."""
    if runner not in ("flutter", "dart") or not name:
        return False
    short = name.split(" › ")[-1]
    ran, lines = set(), 0
    for ln in (raw or "").split("\n"):
        m = FL_RUN_RE.match(ln)
        if m and not m.group(1).startswith(("loading ", "(setUpAll)", "(tearDownAll)", "All tests", "Some tests")):
            ran.add(m.group(1))
            lines += 1
    # every executed test must have shown up by name (a run whose other tests are invisible is not
    # a family — the runner prints at least one progress line per test)
    return bool(ran) and all(x == short or x.endswith(" " + short) for x in ran) and \
        (executed is None or lines >= executed)


LOOP_HEAD_RE = re.compile(r"\bfor\s*\(|\.forEach\s*\(|\.map\s*\(|\bwhile\s*\(")


def loop_site(text, name):
    """K2r5-m1: a loop family is allowed only when the cited literal appears in exactly ONE
    `test(`/`testWidgets(` call in the file and that call sits inside a loop (`for`, `forEach`,
    `map`, `while` — an enclosing block's header). Two separate tests sharing a name are not a
    family."""
    if not text or not name:
        return False
    short = name.split(" › ")[-1]
    hits = [m.start() for q in ("'", '"') for m in re.finditer(
        r"\b(?:test|testWidgets)\s*\(\s*%s" % re.escape(q + short + q), text)]
    if len(hits) != 1:
        return False
    stack = []
    for i, ch in enumerate(text[:hits[0]]):
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            stack.pop()
    for b in stack:
        seg = text[max(text.rfind("}", 0, b), text.rfind("{", 0, b)) + 1:b + 1]
        depth, cut = 0, 0                          # the last statement only (`;` at paren depth 0)
        for i, ch in enumerate(seg):
            depth += ch == "("
            depth -= ch == ")"
            if ch == ";" and depth == 0:
                cut = i + 1
        if LOOP_HEAD_RE.search(seg[cut:]):
            return True
    return False


def rerun_kind(raw, runner, name, passed, family=True):
    """assertion | passed | runtime | load_error | none_ran | ambiguous | unknown (K2-B1, r2-B1)."""
    raw = raw or ""
    for rx in CH.LOAD_ERROR_RES.get(runner, ()):            # collection / compile stage only
        if re.search(rx, raw, re.M):
            return "load_error"
    c = counts(raw, runner)
    if c is not None and c[0] == 0:
        return "none_ran"
    if c is not None and c[0] != 1 and not (family and loop_family(raw, runner, name, c[0])):
        return "ambiguous"
    short = (name or "").split(" › ")[-1].split("::")[-1].split(".")[-1]
    s = CH.parse_summary(raw, runner)
    if runner == "go":
        if not re.search(r"(?m)^--- FAIL: %s\b" % re.escape(name or ""), raw):
            return "passed" if (passed or re.search(r"(?m)^--- PASS: ", raw)) else "unknown"
        if "panic:" in raw:
            return "runtime"
        return "assertion" if re.search(r"(?m)^\s+\w+_test\.go:\d+: ", raw) else "runtime"
    if s is None:
        return "passed" if passed else "unknown"
    if s.failed == 0:
        return "passed"
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
            return "runtime"
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


# K2r3-M1 / K2r4-M1 / K2r6-B1: changes to the BUILD inputs of the warm-up — what decides the
# dependency and hook state: build hooks (`hook/`), the pub manifests (`pubspec.yaml|lock`,
# `pubspec_overrides.yaml`) and any `flutter_test_config.dart` (it wraps EVERY test `main` of its
# subtree, the warm-up's included). `analysis_options*` and `build*.yaml` are NOT build inputs of the
# warm-up (r6: neither changes the hook or dependency state).
HOOK_RE = re.compile(r"(^|/)hook/|(^|/)pubspec(_overrides)?\.(yaml|lock)$|(^|/)flutter_test_config\.dart$")
# K3 (K2r6 carry-over): when `commands.test` runs build_runner, the build_runner configuration is a
# build input again — `build.yaml` / `build.<target>.yaml` decide which builders (code) run
BUILD_YAML_RE = re.compile(r"(^|/)build(\.[A-Za-z0-9_-]+)?\.yaml$")


def uses_build_runner(cmds):
    return any("build_runner" in (c or "") for c in (cmds if isinstance(cmds, (list, tuple)) else [cmds]))


def hook_changes(root, base, extra=(), build_runner=False):
    """Files the change touched that are build inputs of the warm-up (HOOK_RE, + `build*.yaml` when
    the suite runs build_runner) — `base...HEAD` plus `extra` (the suite's uncommitted overlay).
    An unknown base counts as changed."""
    if not base:
        return ["(no base)"]
    out = G.run(root, "diff", "--name-only", "%s...HEAD" % base, check=False).decode()
    names = [f for f in out.split("\n") if f] + list(extra or [])
    return sorted(set(f for f in names if HOOK_RE.search(f) or (build_runner and BUILD_YAML_RE.search(f))))


def build_inputs(root, base, extra=(), build_runner=False):
    """(kind, files) of the change's build inputs (K2r6-B1, K2r7-M1):
    `none` — nothing changed → warm a pristine <base>, then advance to HEAD;
    `deps` — ONLY the root `pubspec.yaml`/`pubspec.lock` changed and the HEAD root has no `hook/`
             and no `flutter_test_config.dart` → candidate for a HEAD warm-up. The pubspec TEXT is
             not trusted (a renamed key above `path:`, quoted keys, `hosted:` shorthand,
             `workspace:` all read as "hosted" to a line regex — r7): the warm-up first runs
             `pub get` alone, then `resolved_check` decides from the RESOLVED lock and package
             config before any hook or test runs;
    `other` — anything else (own hooks, a test config, overrides file, no base) →
              `halted: env build-inputs-changed`."""
    files = hook_changes(root, base, extra, build_runner)
    if not files:
        return "none", []
    if not base or any(f not in ("pubspec.yaml", "pubspec.lock") for f in files):
        return "other", files
    for own in ("hook", "flutter_test_config.dart"):
        if G.ok(root, "cat-file", "-e", "HEAD:%s" % own):
            return "other", files
    return "deps", files


PUB_HOSTS = ("https://pub.dev", "https://pub.dartlang.org")


def parse_lock(text):
    """`pubspec.lock` → {name: {"source": str, "description": dict|str, "version": str}} (the
    fixed layout pub writes: 2-space package names, 4-space keys, 6-space description keys)."""
    out, cur, in_pk, in_desc = {}, None, False, False
    for ln in (text or "").split("\n"):
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        ind = len(ln) - len(ln.lstrip())
        key, _, val = ln.strip().partition(":")
        key, val = key.strip().strip('"'), val.strip().strip('"')
        if ind == 0:
            in_pk = key == "packages"
            cur = None
            continue
        if not in_pk:
            continue
        if ind == 2:
            cur = out.setdefault(key, {"source": None, "description": {}, "version": None})
            in_desc = False
        elif ind == 4 and cur is not None:
            in_desc = key == "description" and not val
            if key == "description" and val:
                cur["description"] = val
            elif key in ("source", "version"):
                cur[key] = val
        elif ind >= 6 and cur is not None and in_desc and isinstance(cur["description"], dict):
            cur["description"][key] = val
    return out


def _pub_cache_roots():
    roots = [os.environ.get("PUB_CACHE") or os.path.expanduser("~/.pub-cache")]
    return [os.path.realpath(r) for r in roots if r]


def resolved_check(tree, root, base, sdk_roots=()):
    """K2r7-M1: after `pub get` on the HEAD copy and BEFORE any hook or test runs — None when only
    hosted pub.dev packages, SDK packages and path/git/workspace packages IDENTICAL to <base> are
    in the resolved graph; else the reason (→ `halted: env build-inputs-changed`). Reads the
    resolved `pubspec.lock` (`source:`) and `.dart_tool/package_config.json` (`rootUri`)."""
    import json as _json
    try:
        with open(os.path.join(tree, "pubspec.lock"), encoding="utf-8") as fh:
            lock = parse_lock(fh.read())
        with open(os.path.join(tree, ".dart_tool", "package_config.json"), encoding="utf-8") as fh:
            pc = _json.load(fh)
    except (IOError, OSError, ValueError) as e:
        return "resolved graph unreadable (%s)" % e
    base_lock = parse_lock(G.run(root, "show", "%s:pubspec.lock" % base, check=False).decode("utf-8", "replace"))
    real_tree = os.path.realpath(tree)

    def changed(rel):
        return bool(G.run(root, "diff", "--name-only", "%s...HEAD" % base, "--", rel or ".", check=False).strip())
    for name, e in sorted(lock.items()):
        src, desc = e.get("source"), e.get("description")
        if src == "hosted":
            url = (desc.get("url") if isinstance(desc, dict) else None) or ""
            if url.rstrip("/") not in PUB_HOSTS:
                return "%s: hosted on a non-pub.dev server (%s)" % (name, url or "?")
        elif src == "sdk":
            continue
        elif src == "git":
            if base_lock.get(name) != e:
                return "%s: git dependency new or changed since base" % name
        elif src == "path":
            pth = desc.get("path") if isinstance(desc, dict) else desc
            rel = os.path.normpath(pth or "")
            if os.path.isabs(rel) or rel.startswith(".."):
                return "%s: path dependency outside the repository (%s)" % (name, pth)
            if changed(rel):
                return "%s: path package %s changed since base" % (name, rel)
        else:
            return "%s: dependency source %r" % (name, src)
    allowed = _pub_cache_roots() + [os.path.realpath(x) for x in sdk_roots]
    dt = os.path.join(tree, ".dart_tool")
    for pk in pc.get("packages") or []:
        uri = pk.get("rootUri") or ""
        if uri.startswith("file://"):
            loc = os.path.realpath(uri[len("file://"):])
        elif ":" in uri.split("/")[0]:
            return "%s: package root %s" % (pk.get("name"), uri)
        else:
            loc = os.path.realpath(os.path.join(dt, uri))
        if loc == real_tree:
            continue
        if loc.startswith(real_tree + os.sep):                     # path / workspace member in the repo
            rel = os.path.relpath(loc, real_tree)
            if changed(rel):
                return "%s: in-repo package %s changed since base" % (pk.get("name"), rel)
            continue
        if (lock.get(pk.get("name")) or {}).get("source") == "sdk":     # flutter, flutter_test, …
            continue
        if any(loc == a or loc.startswith(a + os.sep) for a in allowed):
            continue
        return "%s: package outside the pub cache and the repository (%s)" % (pk.get("name"), loc)
    return None


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


# K2r4-M3: what a revert may touch — implementation only. Docs (`*.md`, `docs/`, `design/`), tests
# (TEST_PATH_RE) and non-code assets (images, goldens) are never reverted; a change made only of
# those is TEST-ONLY → `effective: n/a(test-only)`.
NON_IMPL_RE = re.compile(r"(^|/)(docs?|design)/|\.(md|mdx|markdown|rst|txt|adoc)$|"
                         r"\.(png|jpe?g|gif|webp|svg|ico|pdf)$|(^|/)goldens?/|(^|/)(LICENSE|CHANGELOG|README)[^/]*$", re.I)


def is_impl(f):
    return bool(f) and not TEST_PATH_RE.search(f) and not NON_IMPL_RE.search(f)


def impl_detail(root, base, given=None):
    """K2r5-M2: the revert scope and `n/a(test-only)` come from the ACTUAL diff `base...HEAD`
    (changed files minus tests/docs/assets — `is_impl`), never from the developer's `impl_files`.
    The developer's list is only compared: unsafe entries are rejected (K2-B4), and a list that
    disagrees with the diff is recorded (`mismatch`: given-only and diff-only files)."""
    out = G.run(root, "diff", "--name-only", "%s...HEAD" % base, check=False).decode()
    derived = []
    for f in [x for x in out.split("\n") if x]:
        s_ = safe_rel(root, f, ("HEAD", base))
        if s_ and is_impl(s_):
            derived.append(s_)
    bad, given_ok = [], []
    for f in list(given or []):
        s_ = safe_rel(root, f, ("HEAD", base))
        if not s_:
            bad.append(f)
        elif is_impl(s_):
            given_ok.append(s_)
    mismatch = None
    if given is not None and given and set(given_ok) != set(derived):
        mismatch = {"given_only": sorted(set(given_ok) - set(derived)),
                    "diff_only": sorted(set(derived) - set(given_ok))}
    src = "derived" if not given else ("result" if mismatch is None else "derived(impl_files mismatch)")
    return {"files": derived, "source": src, "rejected": bad, "mismatch": mismatch}


def impl_files(root, base, given=None):
    """(files, source, rejected) — see `impl_detail`."""
    d = impl_detail(root, base, given)
    return d["files"], d["source"], d["rejected"]


DEP_DIRS = ("node_modules", ".venv", "venv", "vendor", "Pods")


_LINKED = {}                          # temp tree → main-checkout dirs it symlinks (read exceptions)
TEMP_PARENT = None                    # where temp trees go (None = the system temp dir; a harness sets it)


def engine_owned(path):
    base = os.environ.get("GLD_ENGINE_RUNS") or os.path.join(os.path.expanduser("~"), ".cache", "guild-engine")
    b = os.path.realpath(base)
    return path == b or path.startswith(b + os.sep)


def linked_dirs(tree):
    return list(_LINKED.get(os.path.realpath(tree or ""), ()))


def materialize(root, rev, dest):
    """A PRISTINE copy of `rev`'s tracked files in `dest` — no `.git`, no link to the repository's
    git dir (K2r4-M2: the check sandbox denies the common dir). `git archive` → tar with the
    `data` filter (no absolute or escaping members/links)."""
    import io
    import tarfile
    blob = G.run(root, "archive", "--format=tar", rev)
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        tf.extractall(dest, filter="data")


class TempTree(object):
    """A pristine copy of HEAD (`materialize`, no `.git`) in a fresh temp dir; `revert(full)` puts
    the impl files back to `base` (full: base-absent files removed; partial: ADDED files kept — the
    r2 second step for a compile error), written by the engine from the object store. Removed on
    exit, also when entering fails (K2-m6). Every path operated on must resolve inside the temp
    tree with no symlink component (K2-B4).
    `overlay=True` (the suite's tree, K2r4-M2) also carries the main worktree's uncommitted
    TRACKED edits and untracked NON-ignored files (never an ignored one).
    Ignored entries (K2r2-M1): NO ignored FILE is ever copied (generated secrets like
    `lib/env/env.dart` stay out); `.dart_tool` is copied without compile caches; tool-output
    dirs are fresh; dependency dirs (`node_modules` …) are symlinked read-only (`linked_dirs` —
    the check sandbox re-allows reading exactly those); everything else is left out and named
    in `skipped_ignored`."""

    def __init__(self, root, base, files, parent=None, overlay=False, rev="HEAD", defer_ignored=False):
        self.root, self.base, self.files = root, base, files
        self.parent = parent
        self.overlay = overlay
        self.rev = rev
        self.defer_ignored = defer_ignored
        self.path = None
        self.skipped_ignored = []
        self.copied = []
        self.refused = []
        self.linked = []
        self.warm = None

    def copy_listed(self, paths):
        """The repo's opt-in `engine.effective.copy_ignored` (K2 r3): explicit relative paths of
        git-IGNORED files/dirs, copied for the OFFLINE re-runs only — call it AFTER the networked
        warm-up. Same containment as B4: normalised, relative, no `..`, no symlink anywhere in the
        source or destination path, the source's realpath inside the repo, git-ignored there."""
        real_root = os.path.realpath(self.root)
        for raw in paths or []:
            rel = os.path.normpath(raw or "")
            bad = (not raw or os.path.isabs(raw) or rel.startswith("..") or rel == "." or any(c in raw for c in "*?[")
                   or not G.ok(self.root, "check-ignore", "-q", "--", rel))
            src = os.path.join(self.root, rel)
            if not bad:
                cur = self.root
                for part in rel.split(os.sep):
                    cur = os.path.join(cur, part)
                    if os.path.islink(cur):
                        bad = True
                        break
            if not bad and (not os.path.exists(src) or not os.path.realpath(src).startswith(real_root + os.sep)):
                bad = True
            dst = None if bad else self._inside(rel)
            if bad or dst is None:
                self.refused.append(raw)
                continue
            try:                                          # K3r6-B1: never through a link
                FS.rmtree(self.path, rel)
                FS.copytree_in(self.path, rel, src) if os.path.isdir(src) else FS.copy_in(self.path, rel, src)
            except FS.UnsafePath:
                self.refused.append(raw)
                continue
            self.copied.append(rel)
            self.skipped_ignored = [x for x in self.skipped_ignored
                                    if x.rstrip("/") != rel and not rel.startswith(x.rstrip("/") + "/")]

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
        d = tempfile.mkdtemp(dir=self.parent or TEMP_PARENT)   # no fixed prefix (K2r3-m3)
        self.path = d
        try:
            materialize(self.root, self.rev, d)
            if not self.defer_ignored:
                self.finish_ignored()
            for f in self.files:
                if self._inside(f) is None:
                    raise ValueError("impl path escapes the temp tree: %s" % f)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def revert(self, full=True):
        """full → every impl file to base (absent at base → removed); partial → only the files
        that EXIST at base go back, files the change added are restored from HEAD."""
        for f in self.files:
            dst = self._inside(f)
            if dst is None:
                raise ValueError("impl path escapes the temp tree: %s" % f)
            at_base = G.ok(self.root, "cat-file", "-e", "%s:%s" % (self.base, f))
            if at_base:
                self._put(self.base, f, dst)
            elif full:
                if os.path.lexists(dst):
                    os.remove(dst)
            else:
                self._put("HEAD", f, dst)

    def finish_ignored(self):
        """After the tree reached HEAD: the worktree overlay (suite trees) and the ignored entries."""
        if self.overlay:
            self._overlay()
        self._ignored()
        _LINKED[os.path.realpath(self.path)] = list(self.linked)

    def advance(self, to="HEAD"):
        """K2r4-M1: the tree was materialized at `self.rev` (pristine <base>, warmed IN PLACE so the
        build-hook caches keep their paths); move its tracked files to `to` — files that differ are
        written by the engine, files absent at `to` removed."""
        names = G.run(self.root, "diff", "--name-only", "-z", "--no-renames", self.rev, to).decode("utf-8", "replace")
        for f in [x for x in names.split("\0") if x]:
            n = os.path.normpath(f)
            dst = self._inside(n)
            if dst is None:
                raise ValueError("path escapes the temp tree: %s" % f)
            if G.ok(self.root, "cat-file", "-e", "%s:%s" % (to, n)):
                self._put(to, n, dst)
            elif os.path.lexists(dst) and not os.path.isdir(dst):
                os.remove(dst)
        self.rev = to

    def _put(self, rev, f, dst):
        """`rev:f` written by the engine (regular files only; the mode's exec bit kept)."""
        ent = G.run(self.root, "ls-tree", rev, "--", f).decode().split()
        if not ent or ent[0] not in ("100644", "100755"):
            raise ValueError("not a regular file at %s: %s" % (rev, f))
        data = G.run(self.root, "cat-file", "blob", "%s:%s" % (rev, f))
        FS.remove(self.path, os.path.normpath(f))
        FS.write_bytes(self.path, os.path.normpath(f), data, 0o755 if ent[0] == "100755" else 0o644)

    def _overlay(self):
        """Uncommitted tracked edits + untracked non-ignored files of the main worktree (regular
        files only); tracked files deleted there are deleted here."""
        mod = G.run(self.root, "ls-files", "-z", "-m", "-o", "--exclude-standard", check=False).decode("utf-8", "replace")
        gone = G.run(self.root, "ls-files", "-z", "-d", check=False).decode("utf-8", "replace")
        for rel in [x for x in gone.split("\0") if x]:
            dst = self._inside(os.path.normpath(rel))
            if dst and os.path.lexists(dst) and not os.path.isdir(dst):
                FS.remove(self.path, os.path.normpath(rel))
        for rel in sorted(set(x for x in mod.split("\0") if x)):
            n = os.path.normpath(rel)
            src = os.path.join(self.root, n)
            if n.startswith("..") or os.path.isabs(n) or os.path.islink(src) or not os.path.isfile(src):
                continue
            dst = self._inside(n)
            if dst is None:
                continue
            try:
                FS.remove(self.path, n)
                FS.copy_in(self.path, n, src)
            except FS.UnsafePath:
                continue

    def _ignored(self):
        lines = G.run(self.root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard",
                      "--directory", check=False).decode("utf-8", "replace").split("\0")
        for e in [x for x in lines if x]:
            rel = os.path.normpath(e.rstrip("/"))
            if rel.startswith("..") or os.path.isabs(rel):
                continue
            src = os.path.join(self.root, rel)
            base = os.path.basename(rel)
            if base in DEP_DIRS and os.path.islink(src) and engine_owned(os.path.realpath(src)):
                src = os.path.realpath(src)             # the engine's own node install (K3r5-M1), read-only
            dst = self._inside(rel)
            if dst is None or os.path.lexists(dst) or not os.path.exists(src) or os.path.islink(src):
                continue
            if not os.path.isdir(src):
                self.skipped_ignored.append(rel)        # never copy an ignored file (secrets)
                continue
            try:
                if base == ".dart_tool":
                    FS.copytree_in(self.path, rel, src, skip=("build", "flutter_build", "build_resolvers", "flutterfire"))
                elif base in FRESH_DIRS:
                    FS.makedirs(self.path, rel)
                elif base in DEP_DIRS:
                    FS.symlink(self.path, rel, src)    # read-only: the check sandbox denies main writes
                    self.linked.append(os.path.realpath(src))
                else:
                    self.skipped_ignored.append(rel + "/")
            except FS.UnsafePath:
                self.skipped_ignored.append(rel + "/")

    def __exit__(self, *exc):
        if self.path:
            _LINKED.pop(os.path.realpath(self.path), None)
            shutil.rmtree(self.path, True)
        return False


def warm_detail(r):
    """The warm-up's proxy summary and redacted output tail, for the decision log (K2r7-m1)."""
    if r is None or not hasattr(r, "raw"):
        return None
    px = getattr(r, "proxy", None) or {}
    hosts = ", ".join("%s=%s" % (k, v) for k, v in sorted(px.items()) if k != "placeholders")
    tail = [x for x in (r.raw or "").split("\n") if x.strip()][-4:]
    return "proxy: %s | tail: %s" % (hosts or "none", CH.redact_lines(" / ".join(" ".join(t.split()) for t in tail))[:400])


def warm_status(r):
    """`ok | failed(<line>) | skipped(<why>)` of a warm-up result (K2r5-m3)."""
    if r is None:
        return "skipped(no flutter package or a root flutter_test_config.dart)"
    if not hasattr(r, "passed"):
        return "ok"
    if r.passed:
        return "ok"
    line = (r.red_line() if hasattr(r, "red_line") else None) or \
        ([x for x in (r.raw or "").split("\n") if x.strip()] or ["?"])[-1]
    return "failed(%s)" % CH.redact_lines(" ".join(line.split()))[:160]


@contextlib.contextmanager
def prepared_tree(root, base, files, warm=None, copy_list=(), overlay=False, build_runner=False, target="HEAD"):
    """The ONE preparation of every temp tree that runs role-written code (K2r5-B1, K2r6-B1).
    By the change's build inputs (`build_inputs`):
      none        — a pristine <base> warmed IN PLACE under the network, then `advance(HEAD)`;
      deps        — the pristine HEAD copy: `pub get` alone, then `resolved_check` (non-hosted or
                    changed path/git/workspace packages → halt), only then the engine's empty test;
      other       — no warm-up and `info["halt"] = "build-inputs-changed"` (the caller stops).
    Then the worktree overlay (suite trees), the ignored entries, the opt-in `copy_ignored` —
    offline from there on. Yields (tree, info{warm, build_inputs, build_files, halt})."""
    info = {"warm": None, "warm_detail": None, "build_inputs": None, "build_files": [], "halt": None,
            "build_hook_changed": []}
    kind = None
    if warm is not None:
        extra = []
        if overlay:
            extra = [x for x in G.run(root, "ls-files", "-m", check=False).decode("utf-8", "replace").split("\n") if x]
        kind, bfiles = build_inputs(root, base, extra, build_runner)
        info.update(build_inputs=kind, build_files=bfiles, build_hook_changed=bfiles)
        if kind == "other":
            info["halt"] = "build-inputs-changed"
            info["warm"] = "skipped(build-inputs-changed: %s)" % ", ".join(bfiles[:3])
    warm_rev = {"none": base, "deps": "HEAD"}.get(kind) if warm is not None else None
    # `target` (K3r3-M3): the rev the tree ends at — HEAD for the suite/re-runs, the refactor net's proof
    # point for the engine's net run (warm <base> in place, then move to the proof)
    if warm_rev == "HEAD" and target != "HEAD":
        warm_rev = None                          # a deps-class HEAD warm-up does not apply to another rev
    with TempTree(root, base, files, overlay=overlay, rev=warm_rev or target, defer_ignored=bool(warm_rev)) as tt:
        if warm_rev:
            res = warm(warm_rev, tt.path) if warm_rev != "HEAD" else \
                warm(warm_rev, tt.path, lambda t: resolved_check(t, root, base))
            info["warm"], info["warm_detail"] = warm_status(res), warm_detail(res)
            if getattr(res, "halt", None):          # the resolved graph has non-hosted changes
                info["halt"] = "build-inputs-changed"
                info["build_files"] = list(info["build_files"]) + [res.halt]
            if warm_rev != "HEAD":
                tt.advance(target)
            tt.finish_ignored()
        tt.copy_listed(copy_list or [])
        yield tt, info


# ---- per AC ------------------------------------------------------------------------------------

class CheckOutcome(object):
    def __init__(self, ac, test, result, why, kind=None, line=None, cmd=None):
        self.ac, self.test, self.result, self.why, self.kind = ac, test, result, why, kind
        self.line, self.cmd = line, cmd

    def as_field(self):
        s = "%s=%s" % (self.ac, self.result)
        if self.result in ("unverified", "n/a"):
            s += "(%s)" % self.why
        return s

    def detail(self):
        """§9.5 citation material: the test, its assertion line, the re-run and its class."""
        return {"ac": self.ac, "test": self.test, "assert": self.line, "cmd": self.cmd,
                "rerun": self.kind, "result": self.result, "why": self.why}


def static_check(p, cfg, ac, covers):
    """① for every cover → (outcome|None, [(cover, path, name, line)])."""
    if not covers:
        return CheckOutcome(ac, None, "unsure", "no covering test named by the tester"), []
    runner = runner_of(cfg)
    if runner is None or runner not in ASSERT_RES:
        return CheckOutcome(ac, covers[0].get("test"), "unverified", "runner not drivable by the engine"), []
    items = []
    for cv in covers:
        path, name = parse_test_ref(cv.get("test"))
        text = p.read_file(path) if path else None
        if text is None:
            return CheckOutcome(ac, cv.get("test"), "unsure", "cited test file not found"), []
        tb = test_body(text, name, runner)
        if tb is None:
            return CheckOutcome(ac, cv.get("test"), "unsure", "cited test body not found (name required)"), []
        ok, off = has_assertion(tb[0], runner)
        if not ok:
            return CheckOutcome(ac, cv.get("test"), "fail", "no reachable non-trivial assertion in the cited test"), []
        items.append((cv, path, name, "%s:%d" % (path, tb[1] + off)))
    return None, items


def _verdict_head(kind, tree, raw=""):
    """The HEAD run must execute exactly the cited test and pass (r2-B1)."""
    if kind == "passed":
        return None
    if kind == "none_ran":
        return ("unsure", "the cited test did not run at HEAD (skipped or filtered out) — covers nothing")
    if kind == "ambiguous":
        return ("unverified", "filter ran more than one test")
    if (getattr(tree, "warm", None) or "").startswith("failed") and kind in ("load_error", "runtime", "unknown"):
        return ("unverified", "warm-up failed: %s" % tree.warm[len("failed("):-1])     # K2r5-m3
    if tree.skipped_ignored and kind in ("load_error", "runtime", "unknown"):
        named = [x for x in tree.skipped_ignored if x.rstrip("/") and x.rstrip("/") in (raw or "")]
        return ("unverified", "secret-required: the test needs git-ignored files the engine does not copy (%s)"
                % ", ".join((named or tree.skipped_ignored)[:3]))
    return ("unverified", "the cited test does not pass at HEAD in the temp tree (%s)" % kind)


def run(p, cfg, effective_acs, covers_by_ac, base, given_impl=None, timeout_s=900):
    """Check every AC the judge called effective. Returns ({ac: CheckOutcome}, meta).
    Order (design §3.3 as revised by K2 r2): ① static → temp tree at HEAD (engine warm-up) →
    HEAD run of each cited test (exactly one ran and passed) → full revert → re-run → for a
    compile/collection error: partial revert (added files kept) → re-run → classify."""
    out, meta = {}, {"impl_source": None, "rejected": [], "base": base, "bypassed": False}
    if not effective_acs:
        return out, meta
    if not base and p.root and os.path.isdir(p.root) and G.ok(p.root, "rev-parse", "--git-dir"):
        base = default_base(p.root)
        meta.update(base=base, base_source="merge-base" if base else None)
    runner = runner_of(cfg)
    pending = {}                      # ac → [(cv, path, name, line, cmd)]
    for ac in effective_acs:
        o, items = static_check(p, cfg, ac, covers_by_ac.get(ac, []))
        if o is not None:
            out[ac] = o
            continue
        rows = []
        for cv, path, name, line in items:
            cmd = single_command(cfg, runner, path, name)
            if not cmd:
                out[ac] = CheckOutcome(ac, cv.get("test"), "unverified", "no exact single-test command", line=line)
                break
            rows.append((cv, path, name, line, cmd))
        else:
            pending[ac] = rows
    if not pending:
        return out, meta
    if not (p.root and os.path.isdir(p.root) and G.ok(p.root, "rev-parse", "--git-dir")):
        for ac, rows in pending.items():
            out[ac] = CheckOutcome(ac, rows[0][0].get("test"), "unverified", "not a git worktree", line=rows[0][3])
        return out, meta
    det = impl_detail(p.root, base, given_impl) if base else {"files": [], "source": None, "rejected": [],
                                                              "mismatch": None}
    impl, src, bad = det["files"], det["source"], det["rejected"]
    meta.update(impl_source=src, rejected=bad, test_only=bool(base) and not impl,
                impl_given_mismatch=det["mismatch"])
    warm = getattr(p, "warm", None)
    try:
        # K2r4-M1: with a warm-up, the tree starts as a PRISTINE checkout of <base> (reviewed code,
        # no ignored file); the networked warm-up runs there, in place (hook caches keep their
        # paths); only then does the tree move to HEAD and get its ignored entries, then the
        # opt-in copy_ignored files — offline from there on (`prepared_tree`)
        copy_list = ((cfg.get("engine") or {}).get("effective") or {}).get("copy_ignored")
        with prepared_tree(p.root, base, impl, warm, copy_list) as (tt, info):
            meta["warm"], meta["warm_detail"] = info["warm"], info.get("warm_detail")
            if info["halt"]:
                # K2r6-B1: own hooks / path-git-override deps / a test config changed — no warm-up
                # may run them with the network and the offline run cannot build → unverified (the
                # suite of the same Issue has already halted the stage: env build-inputs-changed)
                meta["build_hook_changed"] = info["build_files"]
                for ac, rows in pending.items():
                    out[ac] = CheckOutcome(ac, rows[0][0].get("test"), "unverified",
                                           "build-inputs-changed: %s" % ", ".join(info["build_files"][:3]),
                                           line=rows[0][3])
                return out, meta
            tt.warm = info["warm"]
            meta["skipped_ignored"] = tt.skipped_ignored
            meta.update(ignored_copied=tt.copied, ignored_refused=tt.refused)
            _phases(p, runner, pending, tt, base, impl, out, timeout_s)
    except Exception as e:                          # a failed temp tree is "could not check"
        for ac, rows in pending.items():
            out.setdefault(ac, CheckOutcome(ac, rows[0][0].get("test"), "unverified", "temp tree: %s" % e,
                                            line=rows[0][3]))
    news = [o for ac, o in out.items() if any(r[0].get("kind") == "new" for r in pending.get(ac, []))]
    meta["bypassed"] = bool(news) and all(o.result == "unverified" and o.kind == "load_error" for o in news)
    return out, meta


def _phases(p, runner, pending, tt, base, impl, out, timeout_s):
    live = {}
    for ac, rows in pending.items():                 # HEAD run (r2-B1)
        for cv, path, name, line, cmd in rows:
            r = p.check(cmd, tt.path, "tester", timeout_s, [tt.path])
            kind = "timeout" if r.timed_out else rerun_kind(r.raw, runner, name, r.passed,
                                                             loop_site(p.read_file(path), name))
            v = _verdict_head(kind, tt, r.raw)
            if v:
                out[ac] = CheckOutcome(ac, cv.get("test"), v[0], v[1], "head:" + kind, line, cmd)
                break
        else:
            news = [x for x in rows if x[0].get("kind") == "new"]
            if not news:
                out[ac] = CheckOutcome(ac, rows[0][0].get("test"), "pass", "assertion present; runs and passes at HEAD",
                                       None, rows[0][3], rows[0][4])
            elif not base:
                out[ac] = CheckOutcome(ac, news[0][0].get("test"), "unverified", "no base", line=news[0][3])
            elif not impl:
                # K2r4-M3: nothing but tests/docs changed — there is no implementation whose
                # absence the test could detect; the judge's verdict stands, nothing loops back
                out[ac] = CheckOutcome(ac, news[0][0].get("test"), "n/a", "test-only", "head:passed",
                                       news[0][3], news[0][4])
            else:
                live[ac] = news
    if not live:
        return
    tt.revert(full=True)
    retry = {}
    for ac, rows in live.items():
        res = _rerun(p, runner, tt, rows, timeout_s)
        if res[0] == "load_error":
            retry[ac] = rows
        else:
            out[ac] = _outcome(ac, rows, res)
    if retry:
        tt.revert(full=False)                        # second step: added files kept
        for ac, rows in retry.items():
            out[ac] = _outcome(ac, rows, _rerun(p, runner, tt, rows, timeout_s), second=True)


def _rerun(p, runner, tt, rows, timeout_s):
    for cv, path, name, line, cmd in rows:
        r = p.check(cmd, tt.path, "tester", timeout_s, [tt.path])
        kind = "timeout" if r.timed_out else rerun_kind(r.raw, runner, name, r.passed,
                                                         loop_site(p.read_file(path), name))
        if kind != "assertion":
            return kind, cv, line, cmd
    return "assertion", rows[0][0], rows[0][3], rows[0][4]


def _outcome(ac, rows, res, second=False):
    kind, cv, line, cmd = res
    t = cv.get("test")
    if kind == "assertion":
        return CheckOutcome(ac, t, "pass", "assertion present; reacts to the reverted impl", kind, line, cmd)
    if kind in ("passed", "runtime", "none_ran"):
        why = {"passed": "test still passes with the impl reverted",
               "runtime": "re-run failed with a non-assertion error",
               "none_ran": "the test did not run after the revert"}[kind]
        return CheckOutcome(ac, t, "unsure", why, kind, line, cmd)
    why = {"load_error": "compile/collection error after the revert%s" % (" (added files kept, too)" if second else ""),
           "ambiguous": "filter did not run exactly one test", "unknown": "re-run output unreadable",
           "timeout": "re-run timed out"}[kind]
    return CheckOutcome(ac, t, "unverified", why, kind, line, cmd)
