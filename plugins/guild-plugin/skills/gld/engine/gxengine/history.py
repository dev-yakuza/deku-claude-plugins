"""Readiness E4 (#1910): read-only git facts about an Issue — mechanical, never a verdict.

Three users, one rule: the engine collects, a human (or a role) judges.

  1. The bug guard of the plan-gate (rule 1): is this a bug Issue? `bug_evidence` — a bug label on the
     Issue (defaults.BUG_LABELS), or an analysis.md of this Issue's branch that recorded `type: bug`, or a
     procedure that already runs a template with a repro-red step.
  2. The not-reproduced stop (rule 2): the reproduction test (paths, size, its test declarations), the
     repro-red runs on the code before the fix, and the commits on the recorded base since the Issue was
     written that touched a RELATED file. The engine never concludes "already fixed": a green run cannot
     tell "fixed already" from "the test is wrong" or "cannot be reproduced here".
  3. in:git-history.md of analyze (rule 3, an aid only): commits since the Issue was written on the paths
     the Issue names, where the Issue's code tokens are at the base, and which commits since then added or
     removed them. Nothing here decides anything.

Related files (rule 2), in this order, each kept only when it exists in the recorded base tree:
  a. the reproduction files themselves (a reproduction that edits an existing test file);
  b. what a reproduction file imports: quoted specs of import / export / part / from / require / include
     lines, Python `from x.y import` / `import x.y`; resolved relative to the file, `package:<name>/…` of the
     repository's own Dart package (pubspec.yaml `name:`) to `lib/…`, dotted modules to paths, then tried
     as-is and with the usual source suffixes;
  c. paths named in diagnosis.md and analysis.md at HEAD, and in the Issue body: a token that is a tree
     path (a `:line` suffix and a leading `./` dropped), or a bare file name that names exactly one tree
     file.
At most defaults.HISTORY_RELATED_FILES_MAX. Commits: `git log --since=<Issue createdAt> <base> -- <related>`
(committer date, so a change merged after the Issue was written counts), newest first, at most
defaults.HISTORY_COMMITS_MAX. No Issue time (GitHub did not say) → no commit list, and the facts say so.

Every git call goes through gitops (pinned, hooks off, literal pathspecs, full SHAs only).
"""

import os
import posixpath
import re

from . import acparse, codes, defaults, gitops

_ISO_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z$")
_REC, _UNIT = "\x1e", "\x1f"

SOURCE_SUFFIXES = ("", ".dart", ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rb", ".kt", ".java",
                   ".swift", "/index.ts", "/index.tsx", "/index.js", "/__init__.py")
_QUOTED_IMPORT_RE = re.compile(
    r"""(?:^|[\s;(])(?:import|export|part|from|require\s*\(|import\s*\(|#?include)\b[^'"\n]*?['"<]([^'"<>\s]+)['">]""")
_PY_FROM_RE = re.compile(r"^\s*from\s+(\.*[\w.]*)\s+import\b")
_PY_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+)\s*(?:as\s+\w+)?\s*$")
_PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_.@+\-/]+")
_LINE_SUFFIX_RE = re.compile(r"(?::\d+(?:[-:]\d+)*)+$")
_CODE_TOKEN_RE = re.compile(r"`([^`\n]{3,80})`")
_PUBSPEC_NAME_RE = re.compile(r"^name:\s*([A-Za-z0-9_]+)\s*$", re.M)
_TEST_DECL_RE = re.compile(
    r"^\s*(?:(?:test|testWidgets|it|describe|group|context|test\.each|it\.each|blocTest)\s*(?:<[^>]*>)?\s*\(|"
    r"(?:async\s+)?def\s+test\w*|func\s+Test\w*|@Test\b|fn\s+test_\w*|#\[test\])")


class HistoryError(Exception):
    """A git fact could not be collected (the caller writes that down; it never decides on it)."""


# --- rule 1: the bug Issue ---------------------------------------------------------------------

def is_bug_label(name):
    """True for a label in defaults.BUG_LABELS (lower-case, trimmed)."""
    return isinstance(name, str) and name.strip().lower() in defaults.BUG_LABELS


def analysis_types(ctx, base_sha, head_sha, rel):
    """[(commit sha, analysis type or None)] of every commit of base..head that changed `rel`, oldest
    first — what each recorded analysis said (acparse.machine_field, lenient)."""
    try:
        shas = gitops.git(ctx, "log", "--format=%H", "--reverse", f"{base_sha}..{head_sha}", "--", rel).split()
        out = []
        for sha in shas:
            got = gitops.blob(ctx, sha, rel)
            data = got[2] if got is not None and gitops.is_regular_mode(got[0]) else None
            text = data.decode("utf-8", "replace") if data is not None else None
            out.append((sha, acparse.machine_field(text, "type")))
        return out
    except gitops.GitError as e:
        raise HistoryError(f"analysis history: {e}") from e


def bug_evidence(labels, analysis_records, running_template=None):
    """The reasons this Issue is a bug Issue, as short lines; [] = not a bug Issue.

    `labels` = the Issue's label names, `analysis_records` = analysis_types(...), `running_template` = the
    name of the template the procedure already runs when it has a repro-red step (else None)."""
    out = []
    bugs = [n for n in labels or () if is_bug_label(n)]
    if bugs:
        out.append("Issue label " + ", ".join(f"`{n}`" for n in bugs))
    first = next((sha for sha, t in analysis_records or () if t == codes.AnalysisType.BUG.value), None)
    if first is not None:
        out.append(f"analysis.md at {first[:12]} recorded `type: bug`")
    if running_template:
        out.append(f"the procedure already runs template `{running_template}` (repro-red)")
    return out


# --- trees, imports, path names -----------------------------------------------------------------

def tree_paths(ctx, sha):
    """Every file path of a commit's tree."""
    try:
        return {p for p in gitops.git(ctx, "ls-tree", "-r", "--name-only", "-z", "--full-tree", sha).split("\0") if p}
    except gitops.GitError as e:
        raise HistoryError(f"tree of {sha[:12]}: {e}") from e


def _text_at(ctx, sha, path):
    got = gitops.blob(ctx, sha, path)
    if got is None or not gitops.is_regular_mode(got[0]) or got[2] is None:
        return None
    return got[2].decode("utf-8", "replace")


def dart_package(ctx, sha):
    """The repository's own Dart package name (pubspec.yaml `name:` at `sha`), or None."""
    try:
        text = _text_at(ctx, sha, "pubspec.yaml")
    except gitops.GitError:
        return None
    m = _PUBSPEC_NAME_RE.search(text or "")
    return m.group(1) if m else None


def _first_existing(cands, tree):
    for c in cands:
        c = posixpath.normpath(c) if c else c
        if not c or c.startswith("../") or c == "..":
            continue
        for suf in SOURCE_SUFFIXES:
            if c + suf in tree:
                return c + suf
    return None


def import_specs(text):
    """The import targets a source text names: (spec, kind) with kind "quoted" or "python"."""
    out = []
    for line in (text or "").splitlines():
        m = _PY_FROM_RE.match(line) or _PY_IMPORT_RE.match(line)
        if m and m.group(1):
            out.append((m.group(1), "python"))
            continue
        for q in _QUOTED_IMPORT_RE.findall(line):
            out.append((q, "quoted"))
    return out


def resolve_import(spec, kind, from_path, tree, package=None):
    """The tree path an import spec names, or None (an outside package, nothing in the tree)."""
    here = posixpath.dirname(from_path)
    if kind == "python":
        dots = len(spec) - len(spec.lstrip("."))
        mod = spec[dots:].replace(".", "/")
        if dots:
            base = here
            for _ in range(dots - 1):
                base = posixpath.dirname(base)
            return _first_existing([posixpath.join(base, mod) if mod else base], tree)
        return _first_existing([mod, posixpath.join(here, mod)], tree)
    if spec.startswith("package:"):
        name, _, rest = spec[len("package:"):].partition("/")
        return _first_existing(["lib/" + rest], tree) if package and name == package and rest else None
    if ":" in spec or spec.startswith(("//", "/")):
        return None                       # dart:core, node:fs, a URL, an absolute path
    if spec.startswith("."):
        return _first_existing([posixpath.join(here, spec)], tree)
    return _first_existing([spec, posixpath.join(here, spec)], tree)


def named_paths(text, tree):
    """Tree paths a free text names: a path token in the tree, or a bare file name of exactly one tree file."""
    by_name = {}
    for p in tree:
        by_name.setdefault(posixpath.basename(p), []).append(p)
    out = []
    for tok in _PATH_TOKEN_RE.findall(text or ""):
        tok = _LINE_SUFFIX_RE.sub("", tok.strip(".,;:()")).removeprefix("./")
        if not tok or tok in out:
            continue
        if tok in tree:
            out.append(tok)
        elif "/" not in tok and "." in tok and len(by_name.get(tok, ())) == 1:
            p = by_name[tok][0]
            if p not in out:
                out.append(p)
    return out


def related_files(ctx, base_sha, head_sha, repro_files, documents, issue_body):
    """[{"path", "why"}] (module docstring a–c), at most defaults.HISTORY_RELATED_FILES_MAX.
    `documents` = [(name, text)] (diagnosis.md, analysis.md at HEAD)."""
    tree = tree_paths(ctx, base_sha)
    package = dart_package(ctx, base_sha)
    out, seen = [], set()

    def add(path, why):
        if path and path in tree and path not in seen and len(out) < defaults.HISTORY_RELATED_FILES_MAX:
            seen.add(path)
            out.append({"path": path, "why": why})

    for f in repro_files:
        add(f, "reproduction test")
    for f in repro_files:
        try:
            text = _text_at(ctx, head_sha, f)
        except gitops.GitError:
            text = None
        for spec, kind in import_specs(text):
            add(resolve_import(spec, kind, f, tree, package), f"imported by {f}")
    for name, text in documents:
        for p in named_paths(text, tree):
            add(p, f"named in {name}")
    for p in named_paths(issue_body, tree):
        add(p, "named in the Issue")
    return out


# --- commits ------------------------------------------------------------------------------------

def valid_time(value):
    """An ISO-8601 UTC time GitHub gives (`2026-11-11T09:36:40Z`), or None."""
    return value if isinstance(value, str) and _ISO_RE.match(value) else None


def commits_since(ctx, rev, since, paths=None, limit=None, pickaxe=None):
    """[{"sha", "date", "subject", "files"}] of `git log --since=<since> <rev> [-S<pickaxe>] [-- paths]`,
    newest first; (list, more) — `more` = commits past `limit`. `files` = the commit's changed files
    (inside `paths` when given), at most defaults.HISTORY_COMMIT_FILES_MAX."""
    if valid_time(since) is None:
        raise HistoryError(f"not an ISO-8601 UTC time: {since!r}")
    limit = defaults.HISTORY_COMMITS_MAX if limit is None else limit
    args = ["log", f"--since={since}", f"--format={_REC}%H{_UNIT}%cI{_UNIT}%s", "--name-only", "--no-renames",
            f"--max-count={limit + 1}"]
    if pickaxe is not None:
        args.append("-S" + pickaxe)
    args.append(rev)
    if paths is not None:
        if not paths:
            return [], 0
        args += ["--", *paths]
    try:
        raw = gitops.git(ctx, *args)
    except gitops.GitError as e:
        raise HistoryError(f"git log: {e}") from e
    out = []
    for rec in raw.split(_REC)[1:]:
        head, _, rest = rec.partition("\n")
        sha, date, subject = (head.split(_UNIT) + ["", ""])[:3]
        files = [f for f in rest.splitlines() if f.strip()]
        out.append({"sha": sha, "date": date, "subject": subject, "files": files[:defaults.HISTORY_COMMIT_FILES_MAX],
                    "files_more": max(0, len(files) - defaults.HISTORY_COMMIT_FILES_MAX)})
    more = max(0, len(out) - limit)
    return out[:limit], more


def count_since(ctx, rev, since):
    """How many commits `rev` has since `since` (all paths)."""
    try:
        return int(gitops.git(ctx, "rev-list", "--count", f"--since={since}", rev).strip() or 0)
    except (gitops.GitError, ValueError) as e:
        raise HistoryError(f"rev-list: {e}") from e


def _commit_lines(commits, more):
    lines = []
    for c in commits:
        lines.append(f"- {c['sha'][:12]} {c['date']} {c['subject']}")
        lines += [f"  - {f}" for f in c["files"]]
        if c.get("files_more"):
            lines.append(f"  - … and {c['files_more']} more file(s)")
    if more:
        lines.append(f"- … and more commits (only the newest {len(commits)} are listed)")
    return lines


# --- rule 2: the not-reproduced facts -----------------------------------------------------------

def test_summary(text):
    """{"lines", "decls"} of a test file: its line count and its test declaration lines (cut)."""
    lines = (text or "").splitlines()
    decls = [ln.strip()[:160] for ln in lines if _TEST_DECL_RE.match(ln)]
    return {"lines": len(lines), "decls": decls[:defaults.HISTORY_TEST_LINES_MAX],
            "decls_more": max(0, len(decls) - defaults.HISTORY_TEST_LINES_MAX)}


def _verdict(r):
    if not isinstance(r, dict):
        return "not run"
    return "timed out" if r.get("timed_out") else f"exit {r.get('exit_code')}"


def not_reproduced_facts(ctx, *, base_sha, head_sha, run, attempt, issue_created, documents, issue_body):
    """The facts of a not-reproduced stop (module docstring, rule 2). `run` = the facts `run` object of the
    last repro-red attempt (`attempt`). A fact that cannot be collected is named in `problems`."""
    ev = (run or {}).get("evidence") or {}
    files = [f.get("path") for f in (ev.get("overlay") or {}).get("files") or () if f.get("path")]
    problems, tests = [], []
    for f in files:
        try:
            text = _text_at(ctx, head_sha, f)
        except gitops.GitError as e:
            text = None
            problems.append(f"{f}: {e}")
        tests.append(dict(test_summary(text), path=f, present=text is not None))
    runs = {k: _verdict((run or {}).get(k)) for k in ("head", "head_rerun", "base_run", "base_rerun")}
    try:
        related = related_files(ctx, base_sha, head_sha, files, documents, issue_body)
    except (HistoryError, gitops.GitError) as e:
        related = []
        problems.append(f"related files: {e}")
    commits, more, since = None, 0, valid_time(issue_created)
    if since is None:
        problems.append("the Issue's creation time is unknown — no commit list")
    elif related:
        try:
            commits, more = commits_since(ctx, base_sha, since, [r["path"] for r in related])
        except HistoryError as e:
            problems.append(str(e))
    else:
        commits = []
    return {"base_sha": base_sha, "head_sha": head_sha, "attempt": attempt, "author": (ev.get("scope") or {}).get("step"),
            "tests": tests, "runs": runs, "issue_created": since, "related": related, "commits": commits,
            "commits_more": more, "problems": problems}


ANSWERS = (
    ("close-as-decided", "--answer close-as-decided --close-reason completed --note-file NOTE",
     "already fixed (or not wanted): the engine posts NOTE and closes the Issue, no PR"),
    ("rerun", "--answer rerun --step reproduce --note-file NOTE",
     "reproduce again: NOTE says what the reproduction missed (it reaches the developer as leader-decision.md)"),
    ("rerun", "--answer rerun --step analyze --note-file NOTE",
     "analyze again from the start with NOTE (the bug template stays)"),
    ("escalate", "--answer escalate", "leave it stopped; a human takes it over outside the engine"),
)
"""The human's answers to a not-reproduced stop (codes.STAGE3_ALLOWED_ANSWERS row), as resume options."""


def not_reproduced_md(facts, issue):
    """The full facts file (records `defaults.NOT_REPRODUCED_FILE`) — data for a human, no verdict."""
    f = facts
    lines = [f"Not reproduced — Issue #{issue}", "=" * 30, "",
             "The reproduction test was not red twice on the code before the fix, after every retry of the "
             "reproduce step. The engine does not say why: the bug may be fixed already, the test may be wrong, "
             "or the bug may not reproduce in this environment. A human decides.", "",
             "## Reproduction test", ""]
    if not f["tests"]:
        lines.append("- (the reproduce step left no test file inside the test-code rule)")
    for t in f["tests"]:
        lines.append(f"- `{t['path']}` — {t['lines']} line(s) at HEAD {f['head_sha'][:12]}"
                     + ("" if t["present"] else " (not readable)"))
        lines += [f"  - {d}" for d in t["decls"]]
        if t.get("decls_more"):
            lines.append(f"  - … and {t['decls_more']} more test declaration(s)")
    r = f["runs"]
    lines += ["", f"## Runs on the code before the fix (repro-red attempt {f['attempt']}, step `{f.get('author') or '?'}` "
                  "wrote the test)", "",
              f"- recorded base {f['base_sha'][:12]} + the reproduction test: `test` {r['head']}; again: {r['head_rerun']} "
              "(red twice was needed)",
              f"- recorded base alone: {r['base_run']}" + (f"; again: {r['base_rerun']}" if r["base_rerun"] != "not run" else ""),
              "", "## Commits on the recorded base since the Issue was written, on related files", ""]
    lines.append(f"- Issue written at: {f['issue_created'] or 'unknown'}")
    if f["commits"] is None:
        lines.append("- (not listed: no Issue time)")
    elif not f["commits"]:
        lines.append("- none")
    else:
        lines += _commit_lines(f["commits"], f["commits_more"])
    lines += ["", "Related files (the rule: the reproduction files, what they import, the paths diagnosis.md / "
                  "analysis.md / the Issue name — each only when it exists in the recorded base tree):", ""]
    lines += [f"- `{x['path']}` ({x['why']})" for x in f["related"]] or ["- none found"]
    if f["problems"]:
        lines += ["", "## Not collected", ""] + [f"- {p}" for p in f["problems"]]
    lines += ["", "## Answers (`/gld resume` — engine.py resume --repo OWNER/REPO --issue N …)", ""]
    lines += [f"- `{a}` — `{cmd}`: {what}" for a, cmd, what in ANSWERS]
    return "\n".join(lines) + "\n"


def not_reproduced_note(facts, path_hint):
    """The stop note (status, the needs-human comment): the same facts, short."""
    f = facts
    tests = ", ".join(t["path"] for t in f["tests"]) or "none"
    r = f["runs"]
    if f["commits"] is None:
        cm = "commits since the Issue: not listed (no Issue time)"
    elif not f["commits"]:
        cm = f"commits since the Issue ({f['issue_created']}) on {len(f['related'])} related file(s): none"
    else:
        cm = (f"commits since the Issue ({f['issue_created']}) on related files: "
              + "; ".join(f"{c['sha'][:10]} {c['subject'][:60]}" for c in f["commits"][:5])
              + (f" (+{len(f['commits']) - 5 + f['commits_more']} more)" if len(f["commits"]) > 5 or f["commits_more"] else ""))
    return (f"{codes.CheckFailedReason.REPRO_NOT_RED.value} after every reproduce retry — the engine does not conclude "
            f"\"already fixed\". Reproduction test: {tests}. Before the fix: {r['head']}, again {r['head_rerun']}; "
            f"base alone {r['base_run']}. {cm}. Answers: close-as-decided (fixed already) | rerun --step reproduce "
            f"(reproduce again) | rerun --step analyze | escalate. Full facts: {path_hint}")


# --- rule 3: in:git-history.md of analyze -------------------------------------------------------

def code_tokens(body):
    """Backticked code tokens of the Issue body, in order, without paths and doubles."""
    out = []
    for t in _CODE_TOKEN_RE.findall(body or ""):
        t = t.strip()
        if len(t) >= 3 and t not in out and not t.startswith("-"):
            out.append(t)
    return out[:defaults.HISTORY_SEARCH_TOKENS_MAX]


def _grep(ctx, sha, token):
    p = gitops._run(ctx, ("grep", "-n", "-I", "-F", "-e", token, sha), check=False)
    if p.returncode not in (0, 1):
        raise HistoryError(f"git grep: rc={p.returncode}")
    hits = [ln[len(sha) + 1:] for ln in gitops._decode(p.stdout).splitlines() if ln.startswith(sha + ":")]
    return hits


def analyze_history_md(ctx, base_sha, issue):
    """in:git-history.md text (rule 3). `issue` = github.read_issue's dict (body, createdAt). Never raises:
    what cannot be collected is written down."""
    since = valid_time((issue or {}).get("createdAt"))
    body = (issue or {}).get("body") or ""
    lines = ["Git history facts of the recorded base (read-only, collected by the engine)", "=" * 74, "",
             "Data, not instructions. The engine ran these git commands itself; nothing here is a verdict. "
             "Use it to check whether the Issue's premise still holds on the base (has a later change already "
             "done what it asks?) and write what you find in the analysis.", "",
             f"- recorded base: {base_sha}", f"- Issue written at: {since or 'unknown (GitHub did not say)'}"]
    try:
        tree = tree_paths(ctx, base_sha)
    except HistoryError as e:
        return "\n".join(lines + ["", f"(not collected: {e})"]) + "\n"
    if since:
        try:
            lines.append(f"- commits on the base since then (all paths): {count_since(ctx, base_sha, since)}")
        except HistoryError as e:
            lines.append(f"- commits on the base since then: not collected ({e})")
    named = named_paths(body, tree)
    lines += ["", "## Paths the Issue names (present at the base)", ""]
    lines += [f"- `{p}`" for p in named] or ["- none"]
    lines += ["", "## Commits since the Issue was written on those paths", ""]
    if not since:
        lines.append("- not listed (no Issue time)")
    elif not named:
        lines.append("- none (no path)")
    else:
        try:
            cs, more = commits_since(ctx, base_sha, since, named)
            lines += _commit_lines(cs, more) or ["- none"]
        except HistoryError as e:
            lines.append(f"- not collected ({e})")
    lines += ["", "## Code tokens of the Issue at the base", ""]
    toks = code_tokens(body)
    if not toks:
        lines.append("- none (no backticked token in the Issue body)")
    for t in toks:
        lines.append(f"### `{t}`")
        try:
            hits = _grep(ctx, base_sha, t)
            lines.append(f"- found at the base: {len(hits)} line(s)")
            lines += [f"  - {h[:200]}" for h in hits[:defaults.HISTORY_SEARCH_HITS_MAX]]
            if since:
                cs, more = commits_since(ctx, base_sha, since, limit=defaults.HISTORY_SEARCH_HITS_MAX, pickaxe=t)
                lines.append("- commits since the Issue that added or removed it: " + ("none" if not cs else ""))
                lines += [f"  - {c['sha'][:12]} {c['date']} {c['subject']}" for c in cs]
                if more:
                    lines.append("  - … and more")
        except (HistoryError, gitops.GitError) as e:
            lines.append(f"- not collected ({e})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_text(path, text, root):
    """Write a records file through fsafe (the records root never follows a link)."""
    from . import fsafe
    fsafe.make_dirs(os.path.dirname(path), root=root)
    fsafe.write_text(path, text, root=root, mode=0o600)
