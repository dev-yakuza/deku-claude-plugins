"""workflows.dev.preflight — repo-level environment checks before a stage runs code (K2r5-B1).

The suite and the effective re-runs run in a temp tree that holds NO git-ignored file except the
repo's opt-in `engine.effective.copy_ignored`. A repo whose TRACKED code needs an ignored file
(word_app: `lib/env/env.dart` imported by `lib/main.dart`; `assets/data.db` listed in pubspec)
would go red there for a reason no code change can fix — an environment problem, not a test
failure: `halted: env ignored-missing` (never a loop-back, never stagnation).
"""

import os
import re

from guildcore.adapters import git as G

IMPORT_RE = re.compile(r"""^\s*(?:import|export|part)\s+['"]([^'"]+)['"]""", re.M)
PKG_NAME_RE = re.compile(r"^name:\s*([\w-]+)\s*$", re.M)
ASSET_LINE_RE = re.compile(r"^\s*-\s+(?:path:\s*)?['\"]?([^'\"#\s]+)['\"]?\s*$")


def _tracked(root, pattern):
    out = G.run(root, "ls-files", "-z", "--", pattern, check=False).decode("utf-8", "replace")
    return [x for x in out.split("\0") if x]


def _ignored(root, paths):
    """The subset of `paths` git ignores (`check-ignore --stdin`, one batch)."""
    if not paths:
        return set()
    out = G.run(root, "check-ignore", "--no-index", "--stdin", input="\n".join(paths).encode(),
                check=False).decode("utf-8", "replace")
    return set(x for x in out.split("\n") if x)


def _covered(path, copy_list):
    for c in copy_list or []:
        c = os.path.normpath(c)
        if path == c or path.startswith(c.rstrip("/") + "/"):
            return True
    return False


def pubspec_assets(text):
    """Asset paths listed under `flutter: assets:` (files and dirs, as written)."""
    out, inside, ind = [], False, None
    for ln in (text or "").split("\n"):
        if re.match(r"^\s*assets:\s*$", ln):
            inside, ind = True, len(ln) - len(ln.lstrip())
            continue
        if inside:
            if ln.strip() and (len(ln) - len(ln.lstrip())) <= ind and not ln.lstrip().startswith("-"):
                inside = False
                continue
            m = ASSET_LINE_RE.match(ln)
            if m:
                out.append(m.group(1))
    return out


def _imports(root, f, pkg):
    try:
        with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except (IOError, OSError):
        return []
    out = []
    for uri in IMPORT_RE.findall(text):
        if uri.startswith("package:"):
            if pkg and uri.startswith("package:%s/" % pkg):
                out.append(os.path.normpath(os.path.join("lib", uri[len("package:%s/" % pkg):])))
        elif ":" not in uri:
            out.append(os.path.normpath(os.path.join(os.path.dirname(f), uri)))
    return [x for x in out if not x.startswith("..") and not os.path.isabs(x)]


def ignored_needed(root, copy_list=()):
    """Git-ignored paths the TESTS need and `copy_ignored` does not cover: the transitive Dart
    `import`/`export`/`part` closure of the tracked test files (`*_test.dart`, own
    `package:<name>/…` and relative URIs) — a library only `lib/main.dart` imports does not count —
    plus the pubspec assets (the test bundle is built from them). Sorted; [] for a non-Dart repo."""
    pub = os.path.join(root, "pubspec.yaml")
    if not os.path.exists(pub):
        return []
    with open(pub, encoding="utf-8", errors="replace") as fh:
        spec = fh.read()
    m = PKG_NAME_RE.search(spec)
    pkg = m.group(1) if m else None
    tracked = set(_tracked(root, "*.dart"))
    # the suite's tests: `*_test.dart` outside `integration_test/` (e2e, never run by the engine)
    todo = [f for f in tracked if (f.endswith("_test.dart") or os.path.basename(f) == "flutter_test_config.dart")
            and not f.startswith("integration_test/") and "/integration_test/" not in f]
    seen, cands = set(todo), set()
    while todo:
        f = todo.pop()
        for t in _imports(root, f, pkg):
            if t in tracked:
                if t not in seen:
                    seen.add(t)
                    todo.append(t)
            else:
                cands.add(t)
    for a in pubspec_assets(spec):
        cands.add(os.path.normpath(a.rstrip("/")))
    cands = sorted(c for c in cands if not c.startswith("..") and not os.path.isabs(c))
    ign = _ignored(root, cands)
    return sorted(c for c in ign if not _covered(c, copy_list))


MISSING_PATH_RES = (
    re.compile(r"No file or variants found for asset: ([^\s]+?)\.?$", re.M),        # flutter assets
    re.compile(r"Error when reading '([^']+)'"),                                     # dart compile
    re.compile(r"Error: Couldn't resolve the package '[^']+' in '([^']+)'"),
)


# 0.102.13 (review-0102-12 M4, word_app #1797 — lead decision): a skipped git-ignored path counts as a MISSING input only
# when (1) a line naming it reads as a read failure and not as a write, (2) the temp tree still lacks it after the run
# and (3) the main checkout holds it as a git-ignored file; tool outputs never count. Everything else is a normal red.
READ_FAIL_RE = re.compile(r"No such file|not found|does not exist|Error when reading|Unable to load|Cannot open|"
                          r"ENOENT|FileSystemException: Cannot (?:open|read)|Failed to load|No file or variants found|"
                          r"Couldn't resolve", re.I)
WRITE_CTX_RE = re.compile(r"written to|crash report|Writing|Saved|Generated|Created", re.I)
TOOL_OUTPUT_RE = re.compile(r"(^|/)flutter_\d+\.log$|^[^/]+\.log$|(^|/)(build|\.dart_tool|coverage)(/|$)")


def _read_failure_line(raw, rel):
    """A line of `raw` naming `rel` (path-bounded) in a read-failure context and not a write context."""
    rx = re.compile(r"(^|[/\s'\"(])%s(?=$|[/\s'\":),.])" % re.escape(rel))
    for ln in raw.split("\n"):
        if rx.search(ln) and READ_FAIL_RE.search(ln) and not WRITE_CTX_RE.search(ln):
            return True
    return False


def missing_ignored(raw, root, skipped, tree=None):
    """The git-ignored paths a red suite run names as missing: `skipped_ignored` entries the output names on a
    read-failure line, plus asset/compile 'not found' paths git ignores — 0.102.13 (M4): each only when the temp tree
    still lacks it after the run and the main checkout holds it as a git-ignored file, tool outputs
    (`flutter_N.log`, a root `*.log`, `build/`, `.dart_tool/`, `coverage/`) never."""
    raw = raw or ""
    cands = []
    for x in skipped or []:
        rel = x.rstrip("/")
        if rel and _read_failure_line(raw, rel) and rel not in cands:
            cands.append(rel)
    found = []
    for rx in MISSING_PATH_RES:
        for m in rx.findall(raw):
            p = m
            for base in [b for b in (tree, root) if b]:
                if p.startswith(os.path.realpath(base) + "/"):
                    p = p[len(os.path.realpath(base)) + 1:]
                elif p.startswith(base.rstrip("/") + "/"):
                    p = p[len(base.rstrip("/")) + 1:]
            if not os.path.isabs(p):
                found.append(os.path.normpath(p))
    for p in sorted(found):
        if p not in cands:
            cands.append(p)
    cands = [c for c in cands if not TOOL_OUTPUT_RE.search(c)]
    cands = [c for c in cands if not (tree and os.path.lexists(os.path.join(tree, c)))]
    cands = [c for c in cands if os.path.lexists(os.path.join(root, c))]
    ign = _ignored(root, cands)
    return [c for c in cands if c in ign]


# K2r6-B1 option A: an offline run that failed on dependency resolution or a download (a hook
# fetching a prebuilt binary, `pub get`) — never a test failure
DEP_FAILURE_RES = (
    re.compile(r"Couldn't resolve the package '"),
    re.compile(r"Failed host lookup: '"),
    re.compile(r"\bSocketException\b.*\b(Failed host lookup|Connection refused|Network is unreachable|"
               r"nodename nor servname)"),
    re.compile(r"Building native assets failed"),
    re.compile(r"pub get failed|Failed to update packages|Could not resolve dependencies|"
               r"version solving failed|Because \w+ depends on .* which doesn't match any versions"),
    re.compile(r"Error: Couldn't find package config|package_config\.json.* does not exist|"
               r"The pubspec\.yaml file has changed since the pubspec\.lock file was generated"),
)


PROGRESS_RE = re.compile(r"^\d\d:\d\d \+\d+(?: ~\d+)?(?: -\d+)?: (.*?)(?: \[E\])?\s*$")


def load_phase_text(raw):
    """The output of the LOADING/COMPILING phase: text before the first test progress line, plus
    every `… loading <file> [E]` failure block (flutter). A failing test BODY's block is excluded."""
    out, cur_load, seen_progress = [], None, False
    for ln in (raw or "").split("\n"):
        m = PROGRESS_RE.match(ln)
        if m:
            seen_progress = True
            cur_load = m.group(1).startswith("loading ") and ln.rstrip().endswith("[E]")
            if cur_load:
                out.append(ln)
            continue
        if not seen_progress or cur_load:
            out.append(ln)
    return "\n".join(out)


def json_load_errors(report):
    """K3 (K2r8-m1): the LOADING failures from flutter's machine reporter (`--file-reporter json:`),
    which a test body cannot forge (it writes stdout, not the report file): `error` events whose
    test is a loader pseudo-test — `testStart` named `loading <file>` with no source location
    (`line`/`url` null; a user test named "loading x" carries its line). Returns the joined error
    texts, "" when there was no load failure, None when the report is absent/unreadable."""
    import json as _json
    if not report:
        return None
    loaders, out, ok = set(), [], False
    for ln in report.split("\n"):
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            e = _json.loads(ln)
        except ValueError:
            continue
        ok = True
        if e.get("type") == "testStart":
            t = e.get("test") or {}
            if str(t.get("name") or "").startswith("loading ") and t.get("line") is None and t.get("url") is None:
                loaders.add(t.get("id"))
        elif e.get("type") == "error" and e.get("testID") in loaders:
            out.append("%s\n%s" % (e.get("error") or "", e.get("stackTrace") or ""))
    return "\n".join(out) if ok else None


def pre_progress_text(raw):
    out = []
    for ln in (raw or "").split("\n"):
        if PROGRESS_RE.match(ln):
            break
        out.append(ln)
    return "\n".join(out)


def dependency_failure(raw, rc=None, load_only=False, report=None, expect_report=False):
    """True when a red run's output carries a dependency-resolution/download signature — with
    `load_only`, only in the loading/compiling phase (K2r7-M2): from the machine report when there
    is one (K2r8-m1 — a fake `loading … [E]` line in stdout no longer counts), else the text."""
    if load_only and report is not None:
        txt = json_load_errors(report)
        if txt is not None:
            return any(rx.search(txt) for rx in DEP_FAILURE_RES)
    if load_only and expect_report:
        # the run was given a machine report but it is missing/unreadable: only the text BEFORE any
        # test progress counts (no test body has run there); the forgeable `loading … [E]` blocks do not
        raw = pre_progress_text(raw)
        return any(rx.search(raw) for rx in DEP_FAILURE_RES)
    raw = load_phase_text(raw) if load_only else (raw or "")
    return any(rx.search(raw) for rx in DEP_FAILURE_RES)
