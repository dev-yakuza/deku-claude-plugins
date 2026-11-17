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


def missing_ignored(raw, root, skipped, tree=None):
    """The git-ignored paths a red suite run names as missing: every `skipped_ignored` entry the
    output mentions (path-bounded), plus asset/compile 'not found' paths git ignores."""
    raw = raw or ""
    out = []
    for x in skipped or []:
        rel = x.rstrip("/")
        if rel and re.search(r"(^|[/\s'\"(])%s(?=$|[/\s'\":),.])" % re.escape(rel), raw, re.M) and rel not in out:
            out.append(rel)
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
    for p in sorted(_ignored(root, found)):
        if p not in out:
            out.append(p)
    return out


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


def dependency_failure(raw, rc=None, load_only=False):
    """True when a red run's output carries a dependency-resolution/download signature — with
    `load_only`, only in the loading/compiling phase (K2r7-M2)."""
    raw = load_phase_text(raw) if load_only else (raw or "")
    return any(rx.search(raw) for rx in DEP_FAILURE_RES)
