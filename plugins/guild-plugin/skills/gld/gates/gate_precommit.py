#!/usr/bin/env python3
"""
gate_precommit.py — Guild deterministic commit gate (M3 강제층, minimal set).

Runs in **two modes**, from one source of truth:

  1. `--git-hook`  — **authoritative enforcement.** Invoked by `.git/hooks/pre-commit`
     (installed by `/gld init`). Git runs it after the working tree and index are final,
     so it sees exactly what is about to be committed. Non-zero exit aborts the commit.
  2. (no args)     — **early warning.** Invoked as a `PreToolUse(Bash)` hook from
     `.claude/settings.json`. Reads the hook payload from stdin and, if the command is a
     `git commit`, checks what it can *before* the command runs, so the agent gets an
     immediate, specific reason instead of burning a turn on a commit the git hook will
     reject anyway.

⚠ **Why two layers.** A `PreToolUse` hook fires *before* the command executes, so a
compound command that creates or mutates content and commits it in one call
(`echo <secret> > f && git add f && git commit -m x`, or
`sed -i '' 's/assert//g' t_test.py && git commit -am x`) is, at hook-fire time, a commit of
content that **does not exist yet**. No `git diff`/`git status` can see it. This is a
property of the hook model, not a bug that regex work can close — an earlier version of
this file tried to close it by merging untracked files and unstaged changes into every
scan, which did **not** catch the compound case (the file is created inside the same
command) and did cause two guaranteed day-one false positives: a single untracked `.env`
anywhere in the repo blocked *every* commit, and any dirty test file in the working tree
blocked commits that did not touch it. The git-hook layer catches the compound case for
real; mode 2 is therefore scoped to exactly what the command being run will actually
commit, which removes both false positives.

Two gates (the only M3 set — structure/boundary gates are v2):
  A. secret       — a sensitive file (keystore/.p12/.jks/.pem/serviceAccount/.env/key
                    material) or an inline private-key/API-token is being committed. BLOCKER.
  B. verification — the commit weakens tests/gates (deletes a test file, net-removes
                    assertions, or adds skip/focus directives) — INV2 "검증은 어떤 자동
                    프로세스도 약화 못 함". Heuristic (rename/semantic evasion possible).
                    Also WARNS (never blocks) when a configured visual baseline
                    (`visual.baselines`) or comparison config file (`visual.config_files`) is
                    changed: the expectation changed, so the PR must disclose it.

Safety / status model:
- **Off-switch**: `.claude/guild/config.json` `gates.enabled: false` → allow all.
- **draft→confirm→enforce** (INV6): the secret/verification gates are universal +
  non-hallucinated, so init installs them confirmed = block. Stack-specific boundary rules
  start `status: draft` in their rule file's **frontmatter** and only WARN until confirmed.
- **Accepted-risk registry**: a path/pattern in `.claude/guild/gates/dismissed.md` is
  downgraded to a warning (a human already accepted it).
- Never prints secret VALUES — only file path / line number.

Fail-open vs fail-closed: an internal *crash* allows the commit (a broken gate must not
wedge the repo). A *timeout* does *not* — an unverified commit is not a verified-clean one,
so mode 1 refuses and says so. Mode 2 warns and defers to the git hook.

Exit codes:
  mode 1 (`--git-hook`): 0 = allow · 1 = block (message on stderr)
  mode 2 (PreToolUse):   0 = allow · 2 = deny (deny JSON on stdout + message on stderr)

Honest scope: this gate constrains commits made through git in this working copy. It does
not survive `--no-verify`, and it does not inspect history already written. It raises the
cost of a mistake; it is not a boundary against a determined bypass.
"""
import fnmatch, functools, json, os, re, subprocess, sys

# --- rule-firing log — episodic tier, gitignored, best-effort append ---
# Feeds the evolve rule scorecard + rule HR demote/retire. Each firing is one line.
FIRINGS_REL = os.path.join(".claude", "guild", "memory", "gate-firings.jsonl")
_FIRINGS = []  # collected during the run, flushed once in main()


class GateUnavailable(Exception):
    """A git call timed out, so the gate could not see the commit's real content.
    Distinct from a crash: unverified is not the same as verified-clean."""


def finding(rule, path, message):
    """One gate finding. Structured rather than a bare string so a repo-local extension can
    *narrow* a central rule (see `refine`) — a plain message gives it nothing to match on."""
    return {"rule": rule, "file": path or "?", "message": message}


def as_message(f):
    """Render a finding for a human. Accepts a plain string for backward compatibility with a
    local `check()` that returns strings."""
    return f["message"] if isinstance(f, dict) else str(f)


def record_firing(rule, action, path):
    """Queue one rule-firing for the log. rule = 'secret' | 'verification' |
    'boundary:<glob> imports <forb>'; action = 'block' | 'warn'."""
    _FIRINGS.append({"rule": rule, "action": action, "file": path or "?"})


def now_iso():
    try:
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


# The log feeds evolve's rule scorecard, so it must keep enough history for a multi-cycle trend
# — and no more. It is gitignored, so nothing prunes it and nothing recovers it either: left
# alone it grows for the life of the repo, on every commit, from three wirings. Cap it by line
# count and keep the NEWEST, since the scorecard reads recent cycles.
FIRINGS_MAX = 5000
FIRINGS_KEEP = 4000


def flush_firings(root, mode):
    """Append the queued firings to the gitignored episodic log, trimming it when it outgrows
    FIRINGS_MAX. Best-effort throughout — a logging or trimming failure never affects the gate
    verdict, which is why the trim is wrapped separately from the append."""
    if not _FIRINGS:
        return
    p = os.path.join(root, FIRINGS_REL)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        ts = now_iso()
        with open(p, "a", encoding="utf-8", errors="backslashreplace") as fh:
            for f in _FIRINGS:
                fh.write(json.dumps({"ts": ts, "mode": mode, **f}, ensure_ascii=False) + "\n")
    except Exception:
        return
    # Trim in a separate try: a failure here must not lose the append that already succeeded.
    try:
        with open(p, encoding="utf-8") as fh:
            lines = fh.readlines()
        if len(lines) <= FIRINGS_MAX:
            return
        with open(p, "w", encoding="utf-8") as fh:
            fh.writelines(lines[-FIRINGS_KEEP:])
    except Exception:
        pass


# --- sensitive file patterns (BLOCK) — the "진짜 위험" set ---
SECRET_PATH_RE = re.compile(
    r"(^|/)("
    r".*\.keystore|.*\.jks|.*\.p12|.*\.pfx|.*\.pem|.*\.key|.*\.p8|.*\.mobileprovision|"
    r".*service[_-]?account.*\.json|credentials\.json|"
    r"id_rsa|id_dsa|id_ecdsa|id_ed25519|"
    r"\.netrc|\.pgpass|\.npmrc|kubeconfig|.*\.tfvars|"
    r"secrets?\.(ya?ml|json|toml)|"
    r".*\.env|.*\.env\..*"
    r")$", re.IGNORECASE)
# Files that merely *look* sensitive but are conventionally committed. Blocking these is a
# guaranteed day-one false positive, which trains the user to switch the gate off entirely.
#   - google-services.json / GoogleService-Info.plist / firebase_options.dart: public app
#     identifiers, not credentials (Flutter/Firebase convention).
#   - .env.example / .env.sample / .env.template / .env.dist: the documented shape of the
#     env file, committed by near every project that uses one.
SECRET_PATH_ALLOW_RE = re.compile(
    r"(^|/)("
    r"google-services\.json|GoogleService-Info\.plist|firebase_options\.dart|"
    r"\.env\.(example|sample|template|dist)|"
    r".*\.example\.env|.*\.sample\.env"
    r")$", re.IGNORECASE)
# high-signal inline secrets (value never printed)
INLINE_SECRET_RES = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),          # AWS long-term access key
    re.compile(r"ASIA[0-9A-Z]{16}"),          # AWS STS temporary credential
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),    # Google API key
    re.compile(r"xox[baprse]-[0-9A-Za-z-]{10,}"),  # Slack tokens (incl. xoxe- refresh)
    re.compile(r"xapp-[0-9]-[0-9A-Za-z-]{10,}"),   # Slack app-level token
    re.compile(r"gh[pousr]_[0-9A-Za-z]{36,}"),     # GitHub classic PAT / OAuth
    re.compile(r"github_pat_[0-9A-Za-z_]{22,}"),   # GitHub fine-grained PAT
    re.compile(r"sk-ant-[0-9A-Za-z\-_]{20,}"),     # Anthropic API key
    re.compile(r"sk-[A-Za-z0-9]{32,}"),            # OpenAI-style API key
    re.compile(r"sk_live_[0-9A-Za-z]{16,}"),       # Stripe live secret
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\."),  # JWT (header.payload.)
]
TEST_PATH_RE = re.compile(
    # test_*.py is specifically pytest's own discovery convention — restricted to .py so
    # this doesn't false-positive on other languages' prod files that happen to start with
    # "test_" (e.g. a Dart/JS helper named test_environment_detector.*).
    r"(^|/)(test|tests|__tests__|spec|e2e|cypress|integration_test)/|"
    r"_test\.|\.test\.|\.spec\.|\.cy\.|"
    r"[A-Za-z0-9]Tests?\.(cs|swift|java|kt)$|"   # .NET/Swift/JVM style: FooTests.cs
    r"(^|/)test_[^/]+\.py$",
    re.IGNORECASE)
ASSERT_RE = re.compile(
    r"\b(expect|verify|should)\b\s*\(|"  # JS/Dart-style matcher calls: expect(...), verify(...)
    # Dart's async `expectLater(` — one token, so no formatter can split it from its paren. NOT
    # `expect.element(` / `.soft(` / `.poll(`: Prettier breaks a long chain into `await expect` /
    # `.element(...)`, so a line-based count of it moved with every reflow and turned three
    # reflowed assertions into a B2 block the original gate never produced. NOT `expect.any(` and
    # friends (asymmetric matchers inside an argument) for the same reason. Visual matchers are
    # counted per occurrence by B4 instead.
    r"\bexpectLater\s*\(|"
    r"\bassert\w*\s*\(|"  # assert(...) and unittest-style assertEqual(/assertTrue(/assertIn(...
    r"\bassert\b",  # bare Python `assert expr[, msg]` statement (no parens)
    re.IGNORECASE)
# Lines that are purely a comment. Counting assertions inside comments made a commit that
# deletes commented-out test code look like it was removing live assertions.
COMMENT_LINE_RE = re.compile(r"^\s*(//|#|\*|/\*|--|<!--)")
SKIP_RE = re.compile(
    r"\b(xit|xdescribe|xtest|xcontext|pytest\.mark\.skip|todo!\()"
    r"|\.skip\(\s*(?:\)|['\"])"  # .skip()/.skip('reason') — a test-skip directive, not
    # Dart's Iterable.skip(n) (a positional count arg, never empty or string-first)
    r"|(?<![\w.])@(Skip|Ignore|Disabled)\b"  # IGNORECASE 의도적 — @skip 등 소문자/혼용도 차단
    r"|\bskip\s*[:=]\s*(true|True)\b"  # Dart `skip: true`, Vitest/node:test `{ skip: true }`
    r"|^\s*#\[ignore\]"  # Rust
    # Focus directives disable EVERY OTHER test in the file — a strictly larger weakening
    # than a single skip, and the one most likely to be committed by accident.
    r"|\b(it|describe|test|context)\.only\s*\(|\b(fit|fdescribe|ftest)\s*\(",
    re.IGNORECASE)


# --- git plumbing (memoized: the checks below each need the same 2-3 queries) -----------
_SH_CACHE = {}


def sh(args, root=None):
    """Run a git command, return stdout. Memoized per process.
    Empty string on ordinary failure (fail-open); GateUnavailable on timeout, which is a
    different thing — see the module docstring."""
    full = tuple(args if root is None else (["git", "-C", root] + args[1:]))
    if full in _SH_CACHE:
        cached = _SH_CACHE[full]
        if isinstance(cached, GateUnavailable):
            raise cached
        return cached
    try:
        # Decode ourselves with surrogateescape rather than passing text=True. ⚠ `text=True`
        # decodes strictly, so ONE byte that is not valid UTF-8 anywhere in the output raises
        # UnicodeDecodeError — which the except below turns into "", i.e. an EMPTY diff, i.e.
        # the verification and inline-secret checks see nothing and the commit sails through.
        # Verified: a Latin-1 encoded source file with no NUL byte (git treats it as *text*, so
        # its content goes into the diff) silently disabled gate B entirely — assertion removal
        # exited 0. Any repo carrying one EUC-KR/Shift-JIS/Latin-1 file was permanently exposed.
        # surrogateescape round-trips undecodable bytes instead of raising; the patterns simply
        # do not match those bytes, which is the correct outcome.
        out = subprocess.run(full, capture_output=True, timeout=20).stdout.decode(
            "utf-8", errors="surrogateescape")
    except subprocess.TimeoutExpired:
        exc = GateUnavailable(" ".join(full))
        _SH_CACHE[full] = exc
        raise exc
    except Exception:
        out = ""
    _SH_CACHE[full] = out
    return out


def repo_root(cwd=None):
    d = sh(["git"] + (["-C", cwd] if cwd else []) + ["rev-parse", "--show-toplevel"]).strip()
    return d or (cwd or os.getcwd())


def gates_enabled(root):
    """Off-switch: config.gates.enabled == false → gate disabled. Default enabled."""
    try:
        with open(os.path.join(root, ".claude", "guild", "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        g = cfg.get("gates") or {}
        return g.get("enabled", True) is not False
    except Exception:
        return True  # no config / unreadable → gate stays on (safe default)


DISMISS_BACKTICK_RE = re.compile(r"`([^`]+)`")


def dismissed(root):
    """Accepted-risk registry: entries in dismissed.md are downgraded to warn (matched as a
    whole path-segment via dismiss_matches, not an arbitrary substring — a short entry like
    "config" must not silently exempt every file whose name contains "config").

    ⚠ This file is **Markdown**, and the natural way to write a path in Markdown is in
    backticks — the file's own format line and every human-written entry observed in a real
    repo do exactly that. The original parser only stripped `-*` and split on the em dash, so
    `` - `env` — reason `` yielded the literal `` `env` `` *including the backticks*, which
    matches no path. The registry therefore silently did nothing: a human wrote down an
    accepted risk, the gate kept blocking on it, and nothing indicated why. Take the first
    backtick-quoted token when there is one; fall back to the pre-em-dash text otherwise.
    A trailing parenthetical (`` `path` (`symbol` …) — reason ``) is dropped with it."""
    entries = []
    try:
        with open(os.path.join(root, ".claude", "guild", "gates", "dismissed.md"),
                  encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception:
        return entries
    for ln in lines:
        if not ln.strip().startswith(("-", "*")):
            continue
        m = DISMISS_BACKTICK_RE.search(ln)
        if m:
            entries.append(m.group(1).strip())
            continue
        raw = ln.strip("-* \t").split("—")[0].split("#")[0].strip()
        if raw:
            entries.append(raw)
    return entries


def dismiss_matches(path, entries):
    """True if `path` is covered by an accepted-risk entry — full path or a complete path
    segment (bounded by `/` or string start/end), never an arbitrary substring."""
    for d in entries:
        if not d:
            continue
        if d == path or re.search(r"(^|/)" + re.escape(d) + r"(/|$)", path):
            return True
    return False


# --- command parsing (mode 2 only) ------------------------------------------------------
GIT_COMMIT_RE = re.compile(
    # `\bgit\b` alone (no command-boundary anchor) deliberately still matches after `sudo `,
    # an absolute path (`/usr/bin/git`), `time `, a subshell `(`, or an env-var prefix
    # (`GIT_AUTHOR_NAME=x git ...`) — an earlier version anchored strictly before `git`,
    # which required `git` to be the very first token and let all of those prefixes bypass
    # the gate. The only thing that must directly follow `git` is optional flags then
    # `commit` — that excludes the original false positive (`git log ... | grep -i commit`,
    # where `commit` never directly follows `git`).
    # `\s+` (not a single space) between a flag and its argument: `git  -C  .  commit` was
    # silently missed when the separator was double-spaced.
    r"\bgit\s+"
    r"(?:-{1,2}[A-Za-z][A-Za-z0-9-]*(?:[=\s]+\S+)?\s+)*"  # global flags (-C dir, -c k=v, --no-pager)
    r"commit\b")
# `git commit-tree` is plumbing, not a commit of the index — `commit\b` alone matched it.
GIT_COMMIT_TREE_RE = re.compile(r"\bgit\s+(?:-{1,2}[A-Za-z][A-Za-z0-9-]*(?:[=\s]+\S+)?\s+)*commit-tree\b")
GIT_C_FLAG_RE = re.compile(r"\bgit\s+(?:-{1,2}[A-Za-z][A-Za-z0-9-]*(?:[=\s]+\S+)?\s+)*?-C\s+(\S+)")


def is_git_commit(cmd):
    """True if `cmd` runs `git commit` — the subcommand directly following `git` (+ optional
    flags), not merely the word "commit" appearing anywhere in the string."""
    if not cmd:
        return False
    if GIT_COMMIT_TREE_RE.search(cmd):
        return False
    return bool(GIT_COMMIT_RE.search(cmd))


def commit_scope(cmd):
    """What will this specific commit command actually put in the commit?

    Returns (include_unstaged, include_untracked).
    - `-a`/`-am`/`--all` stages tracked modifications *while the command runs* — after this
      hook already inspected the index — so those must be scanned too (TOCTOU).
    - a compound `git add ... && git commit ...` stages files that may still be untracked
      right now, so untracked content is in scope for that shape only.
    Anything else commits the index as it stands, and scanning beyond it is what produced
    the "one stray .env blocks every commit" / "any dirty test file blocks every commit"
    false positives.
    """
    tail = cmd.split("commit", 1)[1] if "commit" in cmd else ""
    include_unstaged = bool(re.search(r"(?:^|\s)-[A-Za-z]*a[A-Za-z]*\b|(?:^|\s)--all\b", tail))
    include_untracked = bool(re.search(r"\bgit\s+(?:-\S+\s+)*add\b", cmd))
    return include_unstaged, include_untracked


# --- content collection -----------------------------------------------------------------
def changed_names(root, diff_filter=None, include_unstaged=False):
    """Names of files in scope. Staged always; unstaged tracked changes only when the caller
    says this commit will stage them. `diff_filter` uses git's own syntax; a lowercase
    letter excludes that status (e.g. "d" = all except deleted)."""
    names = set()
    scopes = [["--cached"]] + ([[]] if include_unstaged else [])
    for extra in scopes:
        args = ["git", "diff"] + extra + ["--name-only"]
        if diff_filter:
            args += [f"--diff-filter={diff_filter}"]
        names.update(unquote_git_path(n.strip()) for n in sh(args, root=root).splitlines()
                     if n.strip())
    return names


def untracked_names(root, enabled):
    """Files git doesn't track yet. Only collected when the command being run will `git add`
    them (see commit_scope) — an unconditional repo-wide `--untracked-files=all` sweep both
    read the entire tree on every commit and blocked commits over files that were never
    going to be included."""
    if not enabled:
        return set()
    out = sh(["git", "status", "--porcelain", "--untracked-files=all"], root=root)
    return {unquote_git_path(ln[3:].strip()) for ln in out.splitlines()
            if ln.startswith("??") and ln[3:].strip()}


def changed_diff(root, include_unstaged=False):
    """Diff content in scope, unified=0. Same scoping rationale as changed_names.

    ⚠ `--src-prefix`/`--dst-prefix` are pinned, not left to the repo's config. A repo that sets
    `diff.noprefix = true` (or `diff.mnemonicPrefix`) gets headers like
    `diff --git test/x.py test/x.py` with no `a/`…`b/` at all — `DIFF_GIT_RE` then matches
    nothing, every line falls back to the `"?"` path, and **every path-based check silently
    stops working**: verified, a four-assertion removal exited 0. The gate must not depend on a
    repo-level display preference for its parsing to hold."""
    scopes = [["--cached"]] + ([[]] if include_unstaged else [])
    return "\n".join(
        sh(["git", "diff"] + extra + ["--unified=0", "--src-prefix=a/", "--dst-prefix=b/"],
           root=root)
        for extra in scopes)


C_QUOTE_ESCAPES = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r",
                   "t": "\t", "v": "\v", "\\": "\\", '"': '"'}


def unquote_git_path(p):
    """Decode git's C-style quoting of a path.

    ⚠ With `core.quotepath` on (git's DEFAULT), any path containing a non-ASCII byte is
    emitted **quoted and octal-escaped**: `test/한글_test.py` becomes
    `"test/\\355\\225\\234\\352\\270\\200_test.py"`. So a diff header for such a file reads
    `+++ "b/test/\\355..."` — which does not even start with `+++ b/`, so the parser never
    updated the current file, and every added/removed line in it was attributed to whatever
    file came before. Verified: removing five assertions from a Korean-named test file exited
    0. `TEST_PATH_RE`/`SECRET_PATH_RE` would also never match the escaped form. Non-ASCII
    filenames are ordinary in this plugin's own user base, so this was a live bypass."""
    if len(p) >= 2 and p.startswith('"') and p.endswith('"'):
        p = p[1:-1]
    else:
        return p
    out, i = [], 0
    while i < len(p):
        c = p[i]
        if c != "\\":
            out.append(c.encode("utf-8", "surrogateescape"))
            i += 1
            continue
        nxt = p[i + 1] if i + 1 < len(p) else ""
        if nxt in C_QUOTE_ESCAPES:
            out.append(C_QUOTE_ESCAPES[nxt].encode("utf-8", "surrogateescape"))
            i += 2
        elif nxt.isdigit() and i + 3 < len(p):
            try:
                out.append(bytes([int(p[i + 1:i + 4], 8)]))
                i += 4
            except ValueError:
                out.append(c.encode()); i += 1
        else:
            out.append(c.encode()); i += 1
    return b"".join(out).decode("utf-8", errors="surrogateescape")


DIFF_GIT_RE = re.compile(r'^diff --git (?:"?a/.*?"?) ("?b/.*"?)$')


def iter_diff_lines(diff):
    """Yield `(path, sign, body)` for each added/removed line, with `path` unquoted.

    File boundaries come from the `diff --git a/X b/Y` header, **not** from `+++ b/`.
    ⚠ `+++ b/` is spoofable: with `--unified=0` every content line is prefixed with `+` or
    `-`, so a source line that itself begins with `++ b/evil` arrives as `+++ b/evil`. It is
    never parsed for a path — `diff --git` is the only path authority — so the spoof cannot
    redirect attribution.

    ⚠ But it must still be SCANNED. Skipping every `+++`/`---` line outright (the previous
    shape) meant a source line written as `++ <secret>` or `-- <assertion>` reached no check
    at all: the inline-secret scan, the assertion tally and the boundary rules all never saw
    it. Verified: a one-line file whose only content began with `++ ` yielded nothing.

    So use the markers that a content line CANNOT forge as the frame. `diff --git` and `@@`
    appear at column 0 with no `+`/`-` prefix (a source `@@ x` shows up as `+@@ x`), so they
    are trustworthy; `---`/`+++` are not. `diff --git` opens a header region, `@@` closes it,
    and everything inside the region is header (index/mode/similarity/rename/---/+++) and is
    consumed. Outside it, a `+`/`-` line is content — including one shaped like a header."""
    path, in_header = "?", False
    for ln in diff.splitlines():
        m = DIFF_GIT_RE.match(ln)
        if m:
            b = m.group(1)
            path = unquote_git_path(b)
            if path.startswith("b/"):
                path = path[2:]
            in_header = True
            continue
        if in_header:
            if ln.startswith("@@"):
                in_header = False
            continue          # index/mode/similarity/rename/binary/---/+++ — no content here
        if ln.startswith("@@"):
            continue          # next hunk of the same file
        if ln[:1] in ("+", "-"):
            yield path, ln[0], ln[1:]


def read_untracked_lines(root, names):
    """Read each in-scope untracked file's content, for scans that need to see it directly
    (it appears in no `git diff`). Best-effort per file: unreadable/binary/huge files are
    skipped, never raise. Caps at 2MB per file and 200 files total — beyond that it is a
    generated tree, not something a secret scan needs to read line-by-line."""
    result = {}
    for n in sorted(names)[:200]:
        path = os.path.join(root, n)
        try:
            if os.path.getsize(path) > 2_000_000:
                continue
            with open(path, encoding="utf-8", errors="ignore") as fh:
                result[n] = fh.read().splitlines()
        except OSError:
            continue
    return result


# --- gates ------------------------------------------------------------------------------
def check_secrets(root, dismiss, scope):
    include_unstaged, include_untracked = scope
    findings = []
    untracked = untracked_names(root, include_untracked)
    # exclude deletions ("d" = all statuses except D) — removing a secret file is a
    # remediation, not a violation; flagging it blocks exactly the cleanup INV5 wants.
    for n in changed_names(root, diff_filter="d", include_unstaged=include_unstaged) | untracked:
        if SECRET_PATH_ALLOW_RE.search(n) or dismiss_matches(n, dismiss):
            continue
        if SECRET_PATH_RE.search(n):
            findings.append(finding("secret", n, f"민감 파일 커밋 시도: {n}"))
            record_firing("secret", "block", n)
    # inline: added lines (iter_diff_lines — spoof-proof headers, unquoted paths)
    for cur_file, sign, body in iter_diff_lines(changed_diff(root, include_unstaged)):
        if sign != "+":
            continue
        for rx in INLINE_SECRET_RES:
            if rx.search(body):
                findings.append(finding("secret", cur_file, f"인라인 시크릿 추정: {cur_file} (값 미표시)"))
                record_firing("secret", "block", cur_file)
                break
    # inline, untracked: never appears in any git diff — read directly.
    for n, lines in read_untracked_lines(root, untracked).items():
        if dismiss_matches(n, dismiss):
            continue
        for ln in lines:
            if any(rx.search(ln) for rx in INLINE_SECRET_RES):
                findings.append(finding("secret", n, f"인라인 시크릿 추정: {n} (값 미표시)"))
                record_firing("secret", "block", n)
                break
    return findings


@functools.lru_cache(maxsize=4096)
def _is_test_path_cached(path, extra_globs):
    return bool(TEST_PATH_RE.search(path)) or (bool(extra_globs) and baseline_matches(path, extra_globs))


def is_test_path(path, extra_globs=()):
    """TEST_PATH_RE, plus the repo's own visual-test globs (`visual.tests`). Visual tests often
    use names no convention covers — `index.vitest.tsx`, `*_golden.dart` outside `test/` — and
    then deleting one, or skipping it, passed B1–B3 unseen. Memoized: it runs per diff line."""
    return _is_test_path_cached(path, tuple(extra_globs))


def check_verification(root, dismiss, scope):
    include_unstaged, _ = scope
    findings = []
    vtests = visual_test_globs(root)
    deleted = changed_names(root, diff_filter="D", include_unstaged=include_unstaged)
    # (B1) deleted test files
    for n in deleted:
        if is_test_path(n, vtests) and not dismiss_matches(n, dismiss):
            findings.append(finding("verification:test-deleted", n, f"테스트 파일 삭제: {n} (INV2 — 검증 약화)"))
            record_firing("verification", "block", n)
    # (B2/B3) net assertion removal / skip additions
    add_assert = rm_assert = add_skip = 0
    skip_files = set()
    vis_re = visual_matcher_re(root)
    vis_add = vis_rm = 0
    vis_files = set()
    # Per-file assertion deltas as well as the total. The aggregate alone left the
    # assertion-drop finding with `file: "?"`, so a repo-local `refine()` could not tell whether
    # a drop was attributable to the one deletion it means to exempt or to an unrelated file in
    # the same commit — forcing it to suppress every verification finding at once, which is far
    # broader than any exemption should be.
    per_file = {}
    # `diff --git` carries BOTH sides, so a fully-deleted file (whose new-side header is
    # "+++ /dev/null") still resolves to its real path — the old parser needed a special
    # "--- a/" branch for that, and got the attribution wrong whenever one was missing.
    for cur, sign, body in iter_diff_lines(changed_diff(root, include_unstaged)):
        if not is_test_path(cur, vtests) or COMMENT_LINE_RE.match(body):
            continue
        n_vis = len(vis_re.findall(body))
        if n_vis and sign == "+":
            vis_add += n_vis
        elif n_vis and cur not in deleted:
            # a whole deleted test file is B1's (block, or dismissed) — not repeated here
            vis_rm += n_vis
            vis_files.add(cur)
        if sign == "+":
            if ASSERT_RE.search(body):
                add_assert += 1
                per_file[cur] = per_file.get(cur, 0) - 1
            if SKIP_RE.search(body):
                add_skip += 1
                skip_files.add(cur)
        elif ASSERT_RE.search(body):
            # A dismissal must not be overturned by the very next check. Deleting a test file
            # a human already accepted (B1, above) removes all of its assertions, which B2
            # then counts as a net drop — so the registry silently does nothing for exactly
            # the case it exists for.
            #
            # Both halves of the condition are load-bearing, and both must stay NARROW:
            #  - `cur in deleted`: without it, a dismissal becomes a STANDING LICENCE to strip
            #    assertions from that file forever, in unrelated later commits, while the file
            #    stays in the tree. (Observed in the repo that first shipped this: registry
            #    entry + 6→3 assertions in a later commit → exit 0.)
            #  - the `-` branch only: widening this to the `+` side would turn off B3 (skip
            #    additions) for the path, and since add_skip/add_assert are COMMIT-WIDE
            #    counters, one entry would erase that file's contribution to the whole
            #    commit's tally — one registration becoming a commit-wide off-switch.
            #
            # A legitimate MOVE of assertions to another file needs no exemption: B2 measures
            # the commit-wide net, so the removal and the addition cancel out. Only a whole
            # deletion — which has no addition to cancel it — reaches here.
            if cur in deleted and dismiss_matches(cur, dismiss):
                continue
            rm_assert += 1
            per_file[cur] = per_file.get(cur, 0) + 1
    if vis_rm > vis_add and _VISUAL_DROP is not None:
        # A WARNING, not a block. Counted per OCCURRENCE so a reflow never moves it, threshold 1:
        # deleting the one `.toMatchThemeScreenshot(...)` line leaves `await expect.element(x)` —
        # valid code that asserts nothing, image left behind unchanged. But a threshold-1 BLOCK
        # stopped ordinary refactors that keep coverage (two matchers merged into the repo's own
        # wrapper; matcher calls moved into a non-test helper) and an intended removal had no way
        # through, since dismissed.md only exempts whole-file deletions. So it joins the
        # visual-disclosure family: warn here, and Guild's execute ledger requires the removal to
        # be declared (`C` row) before the Issue can go green. B2 still blocks a 3+ drop of
        # assertion entry points.
        where = ", ".join(sorted(vis_files)) or "test"
        _VISUAL_DROP.append(finding(
            "verification:visual-assertion-drop", where,
            f"시각 단언(스크린샷/golden 매처) 순감소 {vis_rm - vis_add}건: {where} — 그 화면은 더 이상 "
            "비교되지 않습니다. 의도한 삭제면 PR 본문 '시각 변경' 섹션에 근거와 함께 공개하세요 "
            "(INV2 — 검증 약화일 수 있음)"))
        if _RECORD_VISUAL[0]:
            record_firing("verification:visual-assertion-drop", "warn", where)
    if add_skip:
        where = ", ".join(sorted(skip_files)) or "test"
        findings.append(finding("verification:test-skip", where, f"테스트 skip/focus 지시자 추가 {add_skip}건: {where} (INV2 — 검증 약화)"))
        record_firing("verification", "block", "test-skip")
    if rm_assert - add_assert >= 3:
        droppers = sorted(f for f, n in per_file.items() if n > 0)
        # `file` names the single contributing file when there is one, so the common case is
        # matchable; `files` always carries the full set for a refiner that needs it.
        item = finding("verification:assertion-drop",
                       droppers[0] if len(droppers) == 1 else "?",
                       f"테스트 assertion 순감소 (~{rm_assert - add_assert}줄, INV2 — 검증 약화 의심)")
        item["files"] = droppers
        findings.append(item)
        record_firing("verification", "block", "assertion-drop")
    return findings


# --- visual baselines (golden images / VRT screenshots) --------------------------------
# A visual test's assertion is the expected IMAGE, not a line of code — so `--update-goldens` /
# `vitest -u` rewrites the expected value itself, and a regression accepted that way passes every
# check above: no test file deleted, no assertion line removed, no skip added. The same goes for a
# loosened comparison setting (tolerance, threshold, comparator) in a config file. Blocking either
# would be wrong (every intended UI change legitimately updates baselines), so this WARNS, and the
# warning names what the PR must disclose. The human sees the image diff at review (INV1).
#
# Config-driven only: `config.json` → `visual.baselines` (globs) and `visual.config_files`
# (paths), written by init from command-scan (`_handoff.md` Section L.0). Nothing configured → no
# check. There is no built-in default because baseline locations differ per stack and a guessed
# glob that matches ordinary assets would warn on every icon change, which trains the reader to
# skip it.
#
# ⚠ This check must never be able to take the blocking checks down with it: any error inside it
# yields no warning, never an exception (the module-level handler is fail-OPEN, so a crash here
# would let a staged secret through). Observed in review: `"baselines": true` did exactly that.
BASELINE_SHOW_MAX = 5
_RECORD_VISUAL = [False]  # set by main_git_hook
_VISUAL_DROP = []          # B4 warnings, collected by check_verification, emitted by run_checks


def _visual_cfg(root):
    try:
        with open(os.path.join(root, ".claude", "guild", "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        v = cfg.get("visual") if isinstance(cfg, dict) else None
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _str_list(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for g in value:
        if isinstance(g, str) and g.strip():
            g = g.strip().replace("\\", "/")
            while "//" in g:
                g = g.replace("//", "/")
            while "/./" in g:
                g = g.replace("/./", "/")
            while g.startswith("./"):
                g = g[2:]
            out.append(g.lstrip("/"))
    return [g for g in out if g]


def visual_baseline_globs(root):
    return _str_list(_visual_cfg(root).get("baselines"))


def visual_config_files(root):
    return _str_list(_visual_cfg(root).get("config_files"))


# `.toMatchScreenshot(` / `.toHaveScreenshot(` and the repo's own wrappers around them
# (`.toMatchThemeScreenshot(`, `.toMatchHoverScreenshot(` — a real repo had 79 call sites of those
# and none of the stock name), `toMatchImageSnapshot(`, Flutter's `matchesGoldenFile(`, plus any
# names listed in `visual.matchers`.
VISUAL_MATCHER_BASE = (r"\.to(Match|Have)\w*Screenshot\s*\(|\btoMatchImageSnapshot\s*\(|"
                       r"\bmatches(Golden|Reference)File\s*\(")


def visual_matcher_re(root):
    names = []
    try:
        names = [n for n in _str_list(_visual_cfg(root).get("matchers"))
                 if re.fullmatch(r"[A-Za-z_]\w*", n)]
    except Exception:
        names = []
    extra = "".join(r"|\b" + n + r"\s*\(" for n in names)
    return re.compile(VISUAL_MATCHER_BASE + extra)


def visual_test_globs(root):
    try:
        return _str_list(_visual_cfg(root).get("tests"))
    except Exception:
        return []


def _seg_tokens(seg):
    """One path segment of a glob → tokens: ('*',), ('?',), ('lit', c), ('cls', neg, items).
    A `**` inside a segment (`foo**`, `**.png`) is a plain `*` here. Known difference: git lets
    such a `**` cross `/` when text sits to its left (`b**` matches `b/a.png` in git) — write
    `b*/**` or `b/**` instead in `visual.*` globs."""
    toks, i = [], 0
    while i < len(seg):
        c = seg[i]
        if c == "*":
            while i < len(seg) and seg[i] == "*":
                i += 1
            toks.append(("*",))
            continue
        if c == "?":
            toks.append(("?",)); i += 1; continue
        if c == "[":
            k = i + 1
            neg = k < len(seg) and seg[k] in "!^"
            if neg:
                k += 1
            start = k
            if k < len(seg) and seg[k] == "]":
                k += 1                      # a leading `]` is a literal member
            end = seg.find("]", k)
            if end == -1:
                toks.append(("lit", "[")); i += 1; continue
            body, items, m = seg[start:end], [], 0
            while m < len(body):
                if m + 2 < len(body) and body[m + 1] == "-":
                    items.append((body[m], body[m + 2])); m += 3
                else:
                    items.append((body[m], body[m])); m += 1
            toks.append(("cls", neg, tuple(items))); i = end + 1
            continue
        toks.append(("lit", c)); i += 1
    return tuple(toks)


def _tok_ok(t, ch):
    if t[0] == "?":
        return True
    if t[0] == "lit":
        return t[1] == ch
    hit = any(lo <= ch <= hi for lo, hi in t[2])   # a reversed range matches nothing
    return hit != t[1]


def _seg_match(toks, s):
    """Classic two-pointer wildcard match: O(len(toks) * len(s)), no backtracking blow-up.
    The regex translation it replaces (`[^/]*a[^/]*a…`) took seconds per path for a glob
    like `src/*a*a*a*a*a*b` and never finished on long paths — on the blocking path."""
    ti = si = 0
    star_t, star_s = -1, 0
    while si < len(s):
        if ti < len(toks) and toks[ti][0] != "*" and _tok_ok(toks[ti], s[si]):
            ti += 1; si += 1
        elif ti < len(toks) and toks[ti][0] == "*":
            star_t, star_s = ti, si
            ti += 1
        elif star_t != -1:
            ti = star_t + 1
            star_s += 1
            si = star_s
        else:
            return False
    while ti < len(toks) and toks[ti][0] == "*":
        ti += 1
    return ti == len(toks)


@functools.lru_cache(maxsize=256)
def _compile_glob(g):
    """Git `:(glob)` pathspec semantics, so the gate and the spine's `git diff` agree on what a
    glob covers: a `**` segment is zero or more directories, a trailing `/**` everything below
    (a glob ending in `/` names no file), `*`/`?`/`[...]` never cross `/` (`!`/`^` negate; a `]` right after the
    opening or the negation is literal). fnmatch got two cases wrong — its `*` crosses `/`, and a
    mid-path `/**/` needed at least one directory, so the documented `test/**/goldens/**` missed
    `test/goldens/a.png`. A wildcard-less glob is a directory prefix (or the file itself)."""
    if not any(c in g for c in "*?["):
        return ("prefix", g.rstrip("/"))
    segs = g.split("/")
    if segs[-1] == "":
        return ("none",)                    # git: a trailing-slash glob names no file
    below = len(segs) > 1 and segs[-1] == "**"
    if below:
        segs = segs[:-1]
    return ("segs", tuple("**" if sg == "**" else _seg_tokens(sg) for sg in segs), below)


def glob_matches(g, path):
    kind = _compile_glob(g)
    if kind[0] == "none":
        return False
    if kind[0] == "prefix":
        p = kind[1]
        return path == p or path.startswith(p + "/")
    _, segs, below = kind
    parts = path.split("/")
    # Iterative over glob segments, tracking the set of reachable path positions — no recursion
    # (a recursive version hit Python's recursion limit on ~1000-segment paths, and the caught
    # error silently read as "not a test path").
    pos = {0}
    for sg in segs:
        if not pos:
            return False
        if sg == "**":
            pos = set(range(min(pos), len(parts) + 1))
        else:
            pos = {j + 1 for j in pos if j < len(parts) and _seg_match(sg, parts[j])}
    return any((j < len(parts)) if below else (j == len(parts)) for j in pos)


def baseline_matches(path, globs):
    for g in globs:
        try:
            if glob_matches(g, path):
                return True
        except Exception:
            # A bad glob in `visual.tests` feeds the BLOCKING checks — it must cost that one glob,
            # never the gate (the module-level handler is fail-open).
            continue
    return False


def _natural_key(p):
    # isdecimal, not isdigit: '²'.isdigit() is True and int('²') raises.
    return [(0, int(t), "") if t.isdecimal() else (1, 0, t) for t in re.split(r"([0-9]+)", p)]


def _no_rename_status(root, include_unstaged):
    """{path: status letter} with rename detection off. git pairs a deleted baseline with an
    added one of similar (often identical — goldens share bytes) content as `R`, which M/D
    filters never see: renamed-and-regenerated, moved out of the glob, and delete-plus-add all
    went silent that way. One call per scope instead of one per status."""
    st = {}
    scopes = [["--cached"]] + ([[]] if include_unstaged else [])
    for extra in scopes:
        out = sh(["git", "diff"] + extra + ["--name-status", "--no-renames"], root=root)
        for ln in out.splitlines():
            parts = ln.split("\t", 1)
            if len(parts) == 2 and parts[0][:1]:
                st[unquote_git_path(parts[1].strip())] = parts[0][:1]
    return st


def check_visual_baselines(root, dismiss, scope):
    """Warn findings for this commit's changes to expected images and comparison config. Never
    blocks, never raises."""
    try:
        globs, cfg_files = visual_baseline_globs(root), visual_config_files(root)
        if not globs and not cfg_files:
            return []
        include_unstaged, _ = scope
        warn = []
        status = _no_rename_status(root, include_unstaged)
        groups = (
            # T (type change — e.g. replaced by a symlink) rewrites the content as surely as M.
            ("baseline-updated", "MT", "시각 기준 이미지 갱신", lambda n: baseline_matches(n, globs)),
            ("baseline-deleted", "D", "시각 기준 이미지 삭제", lambda n: baseline_matches(n, globs)),
            # A (added) too: a new per-directory flutter_test_config.dart applies to everything under it.
            ("visual-config-changed", "AMTD", "시각 비교 설정 파일 변경",
             lambda n: baseline_matches(n, cfg_files)),
        )
        for kind, flt, label, match in groups:
            hits = sorted((n for n, st in status.items()
                           if st in flt and match(n) and not dismiss_matches(n, dismiss)),
                          key=_natural_key)
            if not hits:
                continue
            shown = ", ".join(hits[:BASELINE_SHOW_MAX])
            if len(hits) > BASELINE_SHOW_MAX:
                shown += f" 외 {len(hits) - BASELINE_SHOW_MAX}건"
            what = ("허용 오차·비교 방식이 바뀌면 이미지가 그대로여도 무엇이 '같은 화면'인지가 바뀝니다"
                    if kind == "visual-config-changed" else "기대값 자체가 바뀝니다")
            warn.append(finding(
                f"verification:{kind}", hits[0],
                f"{label} {len(hits)}건: {shown} — {what}. 의도한 변경이면 PR 본문 '시각 변경' "
                "섹션에 근거와 함께 공개하세요 (INV2 — 회귀를 정답으로 만들 수 있음)"))
            # ONE firing per kind, not per file: a full golden regeneration touches thousands of
            # images, and the firing log is a bounded episodic file that evolve's rule scorecard
            # reads — per-file lines evicted every other rule's history in one commit.
            # Only the authoritative layer records: PreToolUse sees the same commit first (for
            # `-a`), and logging both double-counted every visual change in evolve's scorecard.
            if _RECORD_VISUAL[0]:
                record_firing(f"verification:{kind}", "warn",
                              hits[0] if len(hits) == 1 else f"{len(hits)} files")
        return warn
    except Exception:
        return []


RULE_STATUS_SUFFIX_RE = re.compile(r"\[\s*status\s*:\s*([^\]]*)\]\s*$", re.I)
FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n(.*?)\n---\s*(\n|\Z)", re.S)


HEADER_LINES = 5


def rule_file_confirmed(text):
    """True only if the file's **header** declares `status: confirmed` on its own line.

    Two failure modes, one on each side, and this sits between them:

    - Scanning the **whole document** (the original behavior) let any prose that merely
      mentions the string arm every rule in the file. Not hypothetical: the bundled
      charter.md / architecture.md templates carry the literal `status: confirmed` inside
      explanatory quote blocks, and that house style migrating into a rules file would
      silently promote draft rules to blocking — the exact INV6 violation draft→confirm→enforce
      exists to prevent.
    - Requiring **YAML frontmatter** (the first fix) over-corrected: `init` writes rule files
      as a `# Title` line followed by a bare `status:` line, with no `---` delimiters at all.
      Under that rule *no* rule file could ever be confirmed — every existing repo's confirmed
      rules would have gone silently inert on update, which is strictly worse than arming too
      eagerly. Caught by a test written against a real repo's file shape.

    So: accept frontmatter when present, otherwise the first few lines — and in both cases the
    declaration must be a **standalone line**, which a sentence or a quoted mention is not."""
    m = FRONTMATTER_RE.match(text)
    head = m.group(1) if m else "\n".join(text.splitlines()[:HEADER_LINES])
    return bool(re.search(r"^\s*status:\s*confirmed\s*$", head, re.I | re.M))


def check_boundaries(root, dismiss, scope):
    """Structure/boundary gate (v2, rule-driven). Read gates/rules/boundaries.md; return
    (block, warn). Rule line: `- forbid: <path-glob> imports <substr> [status: <value>]`.
    Best-effort (grep-level, not a real import parser).

    **Status is per rule**, with the file's frontmatter `status:` as the fallback for lines
    that carry no suffix. Only the exact value `confirmed` promotes a rule to BLOCK; anything
    else — a typo (`darft`), a future value (`pending`), or nothing — leaves it at WARN (INV6:
    a structure rule the tooling inferred never blocks until a human confirms it).

    ⚠ File-level-only status was a design flaw, not just a missing feature: one header line
    governed every rule in the file, so promoting a single rule that had been observed
    false-positive-free dragged every *unvalidated* rule in the same file up to BLOCK with it.
    That is the opposite of what draft→confirm→enforce is for, and it made the safe move
    (promote one proven rule) the risky one. Observed in a repo carrying seven boundary rules
    at mixed maturity, which had to fork this file to express it.

    The suffix is stripped from `<substr>` before matching. Without that, a rule line ending in
    `[status: confirmed]` silently matched nothing at all — `<substr>` became
    `package:flutter/ [status: confirmed]`, which appears in no import line — so overwriting
    such a file with a parser that ignores the suffix turns every rule into a **silent no-op**
    while still reading as installed."""
    include_unstaged, include_untracked = scope
    block, warn = [], []
    try:
        with open(os.path.join(root, ".claude", "guild", "gates", "rules", "boundaries.md"),
                  encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return block, warn
    file_confirmed = rule_file_confirmed(text)
    rules = []
    for ln in text.splitlines():
        m = re.match(r"\s*-\s*forbid:\s*(\S+)\s+imports?\s+(.+)", ln, re.I)
        if not m:
            continue
        glob, forb = m.group(1).strip(), m.group(2).strip()
        # Optional PER-RULE status suffix, anchored at end of line.
        sm = RULE_STATUS_SUFFIX_RE.search(forb)
        if sm:
            forb = forb[:sm.start()].strip()
            rule_confirmed = sm.group(1).strip().lower() == "confirmed"
        else:
            rule_confirmed = file_confirmed
        if forb:
            rules.append((glob, forb, rule_confirmed))
    if not rules:
        return block, warn
    added = {}
    for cur, sign, body in iter_diff_lines(changed_diff(root, include_unstaged)):
        if sign == "+":
            added.setdefault(cur, []).append(body)
    for n, lines in read_untracked_lines(root, untracked_names(root, include_untracked)).items():
        added.setdefault(n, []).extend(lines)
    for glob, forb, confirmed in rules:
        for f, lines in added.items():
            if dismiss_matches(f, dismiss):
                continue
            # the fallback treats a wildcard-less glob ("lib/data") as a directory prefix —
            # "lib/data/*" (path-segment bounded), NOT "lib/data*" (bare string prefix),
            # which would also match an unrelated sibling like "lib/database_helper.dart".
            if fnmatch.fnmatch(f, glob) or fnmatch.fnmatch(f, glob.rstrip("/") + "/*"):
                matched = [l for l in lines if forb in l]
                if matched:
                    msg = f"경계 위반: {f} → 금지 참조 '{forb}' (rule: {glob} imports {forb})"
                    # ⚠ This check is deliberately a line-level string match, not a real import
                    # parser (see the docstring above) — a comment or a string literal that merely
                    # *mentions* the forbidden text fires it too. Someone blocked by that, not
                    # knowing it, reads it as the gate being broken and goes to narrow the rule or
                    # the parser instead — observed for real in a repo running this gate (a
                    # proposal to do exactly that was raised and rejected). So when NONE of the
                    # matched lines is an actual import/export directive, say so in the message.
                    # The verdict (block/warn) is unchanged — this only adds an explanation, and
                    # only when every match is comment/string noise, so a real import violation
                    # never carries this line (that would be noise on the common case instead).
                    if not any(re.match(r"\s*(?:import|export)\b", l) for l in matched):
                        msg += ("\n  ※ 실제 import 문이 아니라 주석/문자열에서 매치됐습니다 — 이 검사는 "
                                "줄 단위 문자열 매칭이라 문구만 언급해도 걸립니다(의도된 동작).")
                    item = finding(f"boundary:{glob} imports {forb}", f, msg)
                    (block if confirmed else warn).append(item)
                    record_firing(f"boundary:{glob} imports {forb}",
                                  "block" if confirmed else "warn", f)
    return block, warn


def write_findings(root, findings):
    """Always rewrite findings.json so it reflects THIS commit's gate state, not a stale
    snapshot: writing only when blocking left the last-blocked findings fossilised, and
    other readers (evolve/audit) misread that as an unresolved open item."""
    try:
        p = os.path.join(root, ".claude", "guild", "gates")
        os.makedirs(p, exist_ok=True)
        # errors="backslashreplace" 는 ensure_ascii=False 와 짝이다. 경로는 unquote_git_path 의
        # surrogateescape 디코드를 거치므로 진짜로 잘못된 UTF-8 바이트는 짝 없는 서로게이트로
        # 살아남고, strict 인코드는 그것을 거부한다 — 쓰기가 중간에 끊긴 채 blanket except 가
        # 삼켜, 이 원장이 "파싱 불가 파일"로 남는다. findings.json 은 evolve/audit 이
        # "미해결 위반 목록" 으로 읽는 파일이라, 조용히 빈/깨진 원장은 "로깅 실패" 가 아니라
        # "위반 없음" 으로 오독된다. flush_firings 가 같은 이유로 같은 처리를 한다(L115).
        with open(os.path.join(p, "findings.json"), "w", encoding="utf-8",
                  errors="backslashreplace") as fh:
            json.dump({"open": [as_message(f) for f in findings]}, fh,
                      ensure_ascii=False, indent=2)
    except Exception:
        pass


# --- verdict reporting ------------------------------------------------------------------
# The block message is read by the *agent* as a tool result. An earlier version ended with
# "…dismissed.md에 등록하거나 /gld config로 게이트를 끄세요" — i.e. the refusal handed the
# model two ways to make the refusal go away, one of which (the off-switch) is a plain
# Write call this hook does not see. A gate whose denial text is a bypass tutorial is
# self-defeating. Remediation belongs to the human, so the message says so and stops.
HUMAN_NOTE = ("이 판단을 되돌리는 것은 사람의 몫입니다 — 수용된 위험이라면 저장소 관리자가 "
              "`.claude/guild/gates/dismissed.md`에 사유를 남겨 등록해야 합니다. "
              "시크릿이 이미 커밋된 적이 있다면 키 회전과 히스토리 정리가 필요합니다.")


WARN_HEADER = "⚠ Guild 게이트 경고 (draft 규칙 — 차단 안 함, confirm 시 차단):"
# Baseline warnings are not draft rules and never become blocks — under WARN_HEADER they would
# promise an escalation that does not exist.
VISUAL_WARN_HEADER = "⚠ Guild 게이트 경고 (시각 기준 이미지·비교 설정 — 차단 안 함, PR 공개 필요):"


VISUAL_RULES = {"verification:baseline-updated", "verification:baseline-deleted",
                "verification:visual-config-changed", "verification:visual-assertion-drop"}


def is_visual_warn(w):
    return isinstance(w, dict) and str(w.get("rule", "")) in VISUAL_RULES


def warn_message(warn):
    """The warn section(s), each under its own header. '' when there is nothing to warn."""
    parts = []
    for header, items in ((WARN_HEADER, [w for w in warn if not is_visual_warn(w)]),
                          (VISUAL_WARN_HEADER, [w for w in warn if is_visual_warn(w)])):
        if items:
            parts.append(header + "\n- " + "\n- ".join(as_message(w) for w in items))
    return "\n\n".join(parts)


def block_message(reasons, warn=()):
    """⚠ Warnings must be folded into the block message, not printed after it. `deny_pre_tool_use`
    exits the process, so any `if warn:` that follows the deny call is **dead code** — on a
    blocking run the human saw the block and never the warnings, which are exactly the draft
    rules one step away from blocking too. They are most worth reading on the run that already
    stopped you."""
    out = ("🚫 Guild 게이트 차단 (커밋 거부):\n- "
           + "\n- ".join(as_message(r) for r in reasons))
    if warn:
        out += "\n\n" + warn_message(warn)
    return out + "\n\n" + HUMAN_NOTE


def deny_pre_tool_use(reasons, warn=()):
    msg = block_message(reasons, warn)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": msg,
    }}))
    sys.stderr.write(msg + "\n")
    sys.exit(2)


# --- repo-local gate extensions ---------------------------------------------------------
# This file is central-owned: `/gld update` overwrites it. That is fine for the universal
# checks, and fatal for anything a repo added to it — observed: a repo had hand-extended this
# script with a `test-naming` check reading its own `rules/test-naming.md` at
# `status: confirmed`. The rule was actively blocking commits; an update replaced the script
# and the rule went inert, still on disk, enforcing nothing, with no warning. That is an INV4
# violation, and the root cause is that there was nowhere else to put it.
#
# So: repo-local checks live in `.claude/guild/gates/scripts/local/*.py`, which update
# preserves. Each module defines `check(ctx)` returning `(block, warn)` — two lists of
# one-line human-readable findings. `ctx` exposes what a check needs without importing this
# file (which update may replace under it).
#
# A broken local check must never wedge the repo: an import or runtime failure degrades to a
# warning, exactly like the fail-open rule for this script's own crashes.
class LocalGateContext:
    """The API a repo-local check may rely on. Kept deliberately small and stable."""

    def __init__(self, root, dismiss, scope):
        self.root = root
        self.scope = scope          # (include_unstaged, include_untracked)
        self._dismiss = dismiss

    def changed_names(self, diff_filter=None):
        """Paths in scope for this commit."""
        return changed_names(self.root, diff_filter=diff_filter,
                             include_unstaged=self.scope[0])

    def changed_diff(self):
        """Unified=0 diff text in scope for this commit."""
        return changed_diff(self.root, self.scope[0])

    def is_dismissed(self, path):
        """True if the human registered this path in gates/dismissed.md."""
        return dismiss_matches(path, self._dismiss)

    def rule_file(self, name):
        """Read gates/rules/<name>; returns (text, confirmed). Missing file → ('', False).
        `confirmed` follows the same frontmatter-only rule the boundary gate uses (INV6)."""
        try:
            with open(os.path.join(self.root, ".claude", "guild", "gates", "rules", name),
                      encoding="utf-8") as fh:
                text = fh.read()
        except Exception:
            return "", False
        return text, rule_file_confirmed(text)

    def record(self, rule, action, path):
        """Log a firing so it reaches evolve's rule scorecard like any built-in rule."""
        record_firing(rule, action, path)


def run_local_checks(root, dismiss, scope):
    d = os.path.join(root, ".claude", "guild", "gates", "scripts", "local")
    block, warn, refiners = [], [], []
    if not os.path.isdir(d):
        return block, warn, refiners
    try:
        import importlib.util
        names = sorted(n for n in os.listdir(d) if n.endswith(".py") and not n.startswith("_"))
    except Exception:
        return block, warn, refiners
    # Do not leave a `__pycache__` beside the extension. This directory is inside the repo and
    # Guild-owned, so bytecode dropped here becomes an untracked artifact the human then has to
    # notice and ignore — in a repo whose .gitignore does not already cover it, it lands in the
    # next commit. The gate runs once per commit; caching buys nothing worth that.
    prev_dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    ctx = LocalGateContext(root, dismiss, scope)
    for name in names:
        try:
            spec = importlib.util.spec_from_file_location(
                "guild_local_" + name[:-3], os.path.join(d, name))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fn = getattr(mod, "check", None)
            if fn is not None:
                b, w = fn(ctx)
                block.extend(b or [])
                warn.extend(w or [])
            rf = getattr(mod, "refine", None)
            if rf is not None:
                refiners.append((name, rf))
        # ⚠ SystemExit is not an Exception (it derives from BaseException), so `sys.exit()`
        # inside a local module — deliberate or a stray `exit(0)` in copy-pasted code — walked
        # straight through this handler and ended the whole gate process with that status,
        # before any finding was reported. Verified: a local check calling sys.exit(0) let a
        # staged key file through. A broken extension must degrade to a warning, never decide
        # the verdict. KeyboardInterrupt is deliberately NOT caught (Ctrl-C must still work).
        except (Exception, SystemExit) as e:
            warn.append(f"로컬 게이트 확장 '{name}' 실행 실패 — 이 검사는 건너뜁니다 ({e})")
    sys.dont_write_bytecode = prev_dont_write
    return block, warn, refiners


# A repo may need to NARROW a central rule, not just add its own. Real cases, both from a repo
# whose gate had been forked precisely because this was impossible: "deleting a non-entry-point
# integration test is not a weakening — our architecture has one entry point, so removing the
# others *restores* it", and "this dismissal was too broad and let later unrelated commits strip
# verification permanently, so narrow when it applies". Neither is expressible as an added
# finding, and neither is a static path (so `dismissed.md` cannot carry it) — without this hook
# they stay in a maintained fork forever, which is exactly the failure this whole mechanism
# exists to end.
#
# Guard rails, because suppression is the dangerous direction:
#   - **A `secret` finding can never be suppressed.** INV5 is not a repo-local policy question,
#     and `dismissed.md` (human-written, reviewable) is the sanctioned path for an accepted
#     secret risk. A refiner that returns fewer secret findings is ignored for those.
#   - **Every suppression is logged** as a firing with `action: "suppressed-by-<module>"`, so it
#     reaches evolve's rule scorecard and `/gld audit` rather than vanishing. A silent narrowing
#     would be indistinguishable from the gate being broken.
#   - A refiner that raises leaves the findings untouched (fail-closed for suppression).
def apply_refiners(refiners, findings, ctx):
    for name, rf in refiners:
        # ⚠ Decide what is a secret BEFORE handing the findings over. `list(findings)` is a
        # SHALLOW copy, so the refiner holds the same dict objects this loop will judge — and
        # reading `f["rule"]` afterwards lets `f["rule"] = "harmless"` turn the INV5 guard off.
        # Verified: a refiner that rewrote every rule and returned [] suppressed the secret
        # finding too. The snapshot cannot break an honest refiner: a refiner's job is to CHOOSE
        # which elements survive, and `rule` is an input to that choice, never its output.
        rules = [(f.get("rule", "") if isinstance(f, dict) else "") for f in findings]
        try:
            kept = rf(ctx, list(findings))
        except Exception:
            continue                      # a broken refiner suppresses nothing
        if kept is None:
            continue
        kept_ids = {id(f) for f in kept}
        survivors, dropped = [], []
        for i, f in enumerate(findings):
            if id(f) in kept_ids or rules[i].startswith("secret"):
                survivors.append(f)
            else:
                dropped.append(f)
        for f in dropped:
            # a local `check()` may return plain strings (see as_message) — those have no
            # .get, and an AttributeError here escapes to the module-level fail-open, i.e. a
            # suppression attempt would ALLOW the commit outright.
            record_firing(f.get("rule", "?") if isinstance(f, dict) else "?",
                          f"suppressed-by-{name}",
                          f.get("file", "?") if isinstance(f, dict) else "?")
        findings = survivors
    return findings


def run_checks(root, scope):
    del _VISUAL_DROP[:]  # B4 warnings are per run; never carry one into the next
    dismiss = dismissed(root)
    block = check_secrets(root, dismiss, scope) + check_verification(root, dismiss, scope)
    b_block, b_warn = check_boundaries(root, dismiss, scope)
    v_warn = check_visual_baselines(root, dismiss, scope) + list(_VISUAL_DROP)
    l_block, l_warn, refiners = run_local_checks(root, dismiss, scope)
    all_block = block + b_block + l_block
    if refiners:
        all_block = apply_refiners(refiners, all_block, LocalGateContext(root, dismiss, scope))
    return all_block, b_warn + v_warn + l_warn


def main_git_hook():
    """Mode 1 — authoritative. Git has already fixed the index; scan exactly it."""
    root = repo_root()
    if not gates_enabled(root):
        return 0
    scope = (False, False)  # the index IS the commit at this point
    _RECORD_VISUAL[0] = True
    try:
        block, warn = run_checks(root, scope)
    except GateUnavailable:
        # Unverified is not verified-clean. Refusing here is recoverable (the human can
        # retry or investigate); allowing silently is not.
        sys.stderr.write("🚫 Guild 게이트: 검증을 완료하지 못했습니다 (git 조회 타임아웃). "
                         "커밋을 거부합니다 — 저장소 상태를 확인해 주세요.\n")
        return 1
    flush_firings(root, "git-hook")
    write_findings(root, block)
    if block:
        sys.stderr.write(block_message(block, warn) + "\n")
        return 1
    if warn:
        sys.stderr.write(warn_message(warn) + "\n")
    return 0


def main_pre_tool_use():
    """Mode 2 — early warning. Catches the common single-command case before the turn is
    spent. The git hook is the backstop for everything this cannot see."""
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    cmd = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
        cmd = (payload.get("tool_input") or {}).get("command", "") or ""
    except Exception:
        cmd = raw  # degrade: treat the raw text as the command
    if not is_git_commit(cmd):
        return 0  # not a commit → allow silently
    # honour `git -C <dir> commit` — resolving the root from the hook's own cwd inspected
    # the wrong repository entirely.
    m = GIT_C_FLAG_RE.search(cmd)
    root = repo_root(m.group(1) if m else None)
    if not gates_enabled(root):
        return 0  # off-switch
    scope = commit_scope(cmd)
    try:
        block, warn = run_checks(root, scope)
    except GateUnavailable:
        # Do not block here: the git hook will run the same checks with the tree final.
        sys.stderr.write("⚠ Guild 게이트: 사전 점검을 완료하지 못했습니다 (타임아웃). "
                         "커밋 시점의 git 훅이 다시 검사합니다.\n")
        return 0
    flush_firings(root, "pre-tool-use")
    write_findings(root, block)
    if block:
        deny_pre_tool_use(block, warn)  # exits 2
    if warn:
        sys.stderr.write(warn_message(warn) + "\n")
    return 0


# --- mode 3: guard the gate's own controls ----------------------------------------------
# The commit gate only ever sees Bash. Its off-switch (`config.json` → gates.enabled), its
# accepted-risk registry (`dismissed.md`), its rule files and the gate script itself are all
# plain files — an agent that wants the gate to stop objecting can simply Write to them, and
# no Bash hook fires. That makes the enforcement layer only as strong as the agent's
# willingness to leave it alone.
#
# This does NOT block: `/gld config --gates=off` is a legitimate, documented action, and a
# gate that cannot be turned off is its own hazard. It asks — so disabling the gate becomes
# a decision a human makes on the record, never a side effect the agent takes on its own.
GATE_CONTROL_RE = re.compile(
    r"\.claude/guild/gates/(dismissed\.md|rules/|scripts/)|"
    r"\.git/hooks/pre-commit")
CONFIG_PATH_RE = re.compile(r"\.claude/guild/config\.json$")
# `visual` decides what the gate REPORTS (an emptied `baselines` list silently ends the
# disclosure warning), so editing it asks like `gates.enabled` does.
GATES_KEY_RE = re.compile(r"\"gates\"|gates\.enabled|\"enabled\"|\"visual\"|\"baselines\"|"
                          r"\"config_files\"|\"tests\"|\"runnable\"|\"create\"|\"vrt\"")

# The gate's own WIRING: the files that decide whether it runs at all. Distinct from
# GATE_CONTROL_RE (what it checks) because the remediation and the message differ.
#
# ⚠ `.git/hooks/pre-commit` is only the authoritative layer's home in an UNMANAGED repo. In a
# repo running lefthook/husky/pre-commit/overcommit/simple-git-hooks — the case `init` step 2b
# exists for — the gate is registered as one of the manager's commands, in its COMMITTED config.
# Deleting that one line removes the enforcement layer entirely and leaves no other trace, and
# nothing asked. `.claude/settings.json` is the same class of file: it carries the PreToolUse
# wirings, including this guard's own.
#
# Deliberately NOT included: `package.json`. husky/simple-git-hooks can be configured there,
# but it is edited on nearly every dependency change — asking on it would train click-through,
# which costs more than the case it covers. Recorded as a known gap rather than papered over.
#
# ⚠ `lefthook-local.yml` / `.lefthook/` are lefthook's own LOCAL-OVERRIDE mechanism, and they
# are as dangerous as `lefthook.yml` itself, not less — arguably more. Verified: lefthook
# 2.1.11, a `lefthook-local.yml` containing `guild-gate: {skip: true}` makes the command
# disappear from the run with `guild-gate (skip) by condition`, exit 0, no trace in
# `lefthook.yml`. The file is also the shape lefthook's own docs recommend for `.gitignore`
# (it exists so a developer can carry a personal override), so it is invisible to code review
# by design — a `git diff` over the committed tree never shows it, and `lefthook.yml` staying
# untouched gives no signal that enforcement changed. Anchored the same way as `lefthook.yml`
# (`(^|/)`, segment-start only) so `mylefthook-local.yml` still does not match.
GATE_WIRING_RE = re.compile(
    r"(^|/)\.claude/settings(\.local)?\.json$|"
    r"(^|/)\.?lefthook\.(ya?ml|toml|json)$|"
    r"(^|/)\.?lefthook-local\.(ya?ml|toml|json)$|"
    r"(^|/)\.lefthook/|"
    r"(^|/)\.husky/|"
    r"(^|/)\.pre-commit-config\.ya?ml$|"
    r"(^|/)\.overcommit\.yml$|"
    r"(^|/)\.simple-git-hooks\.(json|js|cjs)$")


# What in config.json decides what the gate enforces or reports. Grepping the NEW text for these
# keys missed the most natural ways to turn them off — an Edit whose old_string holds the whole
# `visual` block and whose new_string is empty, narrowing a glob to match nothing, or a Write of
# a config that simply omits `visual`. A missing `gates` was harmless (it defaults to on); a
# missing `visual` turns the visual checks off. So simulate the edit and compare.
ENFORCEMENT_KEYS = (("gates",), ("visual",), ("commands", "vrt"))


def _pick(cfg, keys):
    cur = cfg
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _apply_edit(text, old, new, replace_all=False):
    if old is None or old == "" or old not in text:
        return None
    return text.replace(old, new or "") if replace_all else text.replace(old, new or "", 1)


def config_enforcement_change(path, ti, body, cwd=None):
    """'' when the edit leaves every enforcement key unchanged; otherwise a label for the prompt.
    Falls back to the key-name grep (now over old_string too) when the edit cannot be simulated
    — including when the simulation itself fails on an odd payload shape."""
    try:
        return _config_enforcement_change(path, ti, body, cwd)
    except Exception:
        return "게이트 설정 (gates / visual)" if GATES_KEY_RE.search(body) else ""


def _config_enforcement_change(path, ti, body, cwd):
    if not os.path.isabs(path) and cwd:
        path = os.path.join(cwd, path)
    try:
        with open(path, encoding="utf-8") as fh:
            before_text = fh.read()
        before = json.loads(before_text)
    except Exception:
        before_text, before = None, None
    after_text = None
    if before_text is not None:
        if "content" in ti:
            after_text = str(ti.get("content") or "")
        elif isinstance(ti.get("edits"), list):
            after_text = before_text
            for e in ti["edits"]:
                if not isinstance(e, dict) or after_text is None:
                    after_text = None
                    break
                after_text = _apply_edit(after_text, e.get("old_string"), e.get("new_string"),
                                         bool(e.get("replace_all")))
        elif "old_string" in ti:
            after_text = _apply_edit(before_text, ti.get("old_string"), ti.get("new_string"),
                                     bool(ti.get("replace_all")))
    if before is not None and after_text is not None:
        try:
            after = json.loads(after_text)
        except Exception:
            after = None  # an edit that breaks the JSON breaks every key — ask
        changed = [k for k in ENFORCEMENT_KEYS
                   if after is None or _pick(before, k) != _pick(after, k)]
        if not changed:
            return ""
        names = {("gates",): "게이트 off-switch (gates)", ("visual",): "시각 검사 설정 (visual)",
                 ("commands", "vrt"): "시각 회귀 실행 커맨드 (commands.vrt)"}
        return " · ".join(names[k] for k in changed)
    if GATES_KEY_RE.search(body):
        return "게이트 설정 (gates / visual)"
    return ""


def main_guard_config():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    ti = payload.get("tool_input") or {}
    if not isinstance(ti, dict):
        return 0
    path = str(ti.get("file_path") or ti.get("path") or "").replace("\\", "/")
    if not path:
        return 0
    body = " ".join(str(ti.get(k, "")) for k in ("content", "new_string", "old_string", "edits"))
    if GATE_CONTROL_RE.search(path):
        what = "게이트 규칙/스크립트"
    elif GATE_WIRING_RE.search(path):
        what = "게이트 배선 (훅 등록·훅 설정)"
    elif CONFIG_PATH_RE.search(path):
        what = config_enforcement_change(path, ti, body, payload.get("cwd"))
        if not what:
            return 0
    else:
        return 0
    msg = (f"⚠ Guild 강제층 변경 확인 필요 — {what} 을(를) 수정하려 합니다 ({path}).\n"
           "이 변경은 커밋 게이트가 무엇을 차단하는지를 바꿉니다. "
           "의도한 것이라면 승인해 주세요.")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": msg,
    }}))
    return 0


# --- mode 4/5: reusable secret scan (the patterns as a CLI) -----------------------------
# `SECRET_PATH_RE`/`INLINE_SECRET_RES` are the repo's single definition of "what counts as a
# secret", but until now they were reachable only from a hook payload — main() parsed stdin and
# self-filtered to `git commit`. So every other consumer that needed the same judgement
# hand-copied the patterns into its own grep: `audit_readiness.md` re-implemented three of them
# inline for its hygiene check, and `contribute.md` was told to "reuse INLINE_SECRET_RES" from a
# script that offered no way to do so. Two copies of a security-critical pattern set, free to
# drift, with the drift invisible until something leaks. These two modes close that by exposing
# the same objects the commit gate uses.
#
#   --scan-paths   stdin = newline-separated paths (e.g. from `git ls-files`)
#                  → one `SECRET-PATH <path>` line per sensitive name, allowlist applied
#   --scan-text    stdin = arbitrary text (e.g. a draft contribution body)
#                  → one `SECRET-TEXT <line-no>` per line containing an inline secret
#
# Exit 1 if anything was found, 0 if clean, so a caller can branch on the status alone.
# Neither mode ever prints the matched value — only a path or a line number (INV5).
def main_scan_paths():
    # Honour the accepted-risk registry, exactly as check_secrets does. Without this the two
    # consumers disagree with the gate they were built to share a definition with: `audit` would
    # report a BLOCKER for every path a human already registered in dismissed.md and the commit
    # gate already lets through. On a repo that deliberately commits signing material (an iOS
    # multi-flavour app tracks a .p12/.p8/.mobileprovision set per flavour) that is dozens of
    # findings the human has to re-dismiss by hand, every audit — which trains them to ignore the
    # check. A dismissal is a decision, and it belongs to every reader of these patterns.
    dismiss = dismissed(repo_root())
    hits = 0
    for raw in sys.stdin:
        name = raw.strip().replace("\\", "/")
        if not name or SECRET_PATH_ALLOW_RE.search(name) or dismiss_matches(name, dismiss):
            continue
        if SECRET_PATH_RE.search(name):
            print(f"SECRET-PATH {name}")
            hits += 1
    return 1 if hits else 0


def main_scan_text():
    hits = 0
    for i, line in enumerate(sys.stdin, 1):
        if any(rx.search(line) for rx in INLINE_SECRET_RES):
            print(f"SECRET-TEXT {i}")
            hits += 1
    return 1 if hits else 0


# --- mode 6: who owns .git/hooks/pre-commit? -------------------------------------------
# Taking over an existing pre-commit hook is right when a human wrote it, and WRONG when a hook
# manager generates it. lefthook/husky/pre-commit/overcommit all regenerate that file on their
# own `install`, so a Guild shim placed there survives only until the next one — and then the
# enforcement layer is gone with no signal, which is the exact failure mode this gate exists to
# avoid. In a managed repo the gate must be registered as one of the manager's own commands
# instead: the manager keeps owning the hook file, and (because its config is committed) the gate
# then travels with a clone, which the .git/hooks path never does.
#
# stdin = the existing hook's text. Prints the manager's name, or `none` for a hand-written or
# absent hook. Exit 0 always — this is a question, not a verdict.
HOOK_MANAGERS = [
    ("lefthook", re.compile(r"\blefthook\b", re.I)),
    ("husky", re.compile(r"\bhusky\b", re.I)),
    ("pre-commit", re.compile(r"pre-commit\.com|INSTALL_PYTHON|pre_commit\b", re.I)),
    ("overcommit", re.compile(r"\bovercommit\b", re.I)),
    ("simple-git-hooks", re.compile(r"simple-git-hooks", re.I)),
]


def main_detect_manager():
    text = sys.stdin.read() if not sys.stdin.isatty() else ""
    if "gate_precommit.py" in text:
        print("guild")          # already ours — safe to overwrite in place
        return 0
    for name, rx in HOOK_MANAGERS:
        if rx.search(text):
            print(name)
            return 0
    print("none")               # absent, or hand-written: the chain-to-.local path applies
    return 0


def main():
    args = sys.argv[1:]
    if "--detect-hook-manager" in args:
        return main_detect_manager()
    if "--git-hook" in args:
        return main_git_hook()
    if "--guard-config" in args:
        return main_guard_config()
    if "--scan-paths" in args:
        return main_scan_paths()
    if "--scan-text" in args:
        return main_scan_text()
    return main_pre_tool_use()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        # fail-open on a crash: a broken gate must never wedge the repo. (A *timeout* is
        # handled separately above — that one does block in git-hook mode.)
        sys.stderr.write(f"guild gate: internal error, allowing commit ({e})\n")
        sys.exit(0)
