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
this file tried to close it by unioning untracked files and unstaged changes into every
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
import fnmatch, json, os, re, subprocess, sys

# --- rule-firing log — episodic tier, gitignored, best-effort append ---
# Feeds the evolve rule scorecard + rule HR demote/retire. Each firing is one line.
FIRINGS_REL = os.path.join(".claude", "guild", "memory", "gate-firings.jsonl")
_FIRINGS = []  # collected during the run, flushed once in main()


class GateUnavailable(Exception):
    """A git call timed out, so the gate could not see the commit's real content.
    Distinct from a crash: unverified is not the same as verified-clean."""


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
        with open(p, "a", encoding="utf-8") as fh:
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
        out = subprocess.run(full, capture_output=True, text=True, timeout=20).stdout
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


def dismissed(root):
    """Accepted-risk registry: entries in dismissed.md are downgraded to warn (matched as a
    whole path-segment via dismiss_matches, not an arbitrary substring — a short entry like
    "config" must not silently exempt every file whose name contains "config")."""
    try:
        with open(os.path.join(root, ".claude", "guild", "gates", "dismissed.md"), encoding="utf-8") as fh:
            return [ln.strip("-* \t").split("—")[0].split("#")[0].strip()
                    for ln in fh if ln.strip().startswith(("-", "*"))]
    except Exception:
        return []


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
    # silently unrecognised when the separator was double-spaced.
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
        names.update(n for n in sh(args, root=root).splitlines() if n.strip())
    return names


def untracked_names(root, enabled):
    """Files git doesn't track yet. Only collected when the command being run will `git add`
    them (see commit_scope) — an unconditional repo-wide `--untracked-files=all` sweep both
    read the entire tree on every commit and blocked commits over files that were never
    going to be included."""
    if not enabled:
        return set()
    out = sh(["git", "status", "--porcelain", "--untracked-files=all"], root=root)
    return {ln[3:].strip() for ln in out.splitlines() if ln.startswith("??") and ln[3:].strip()}


def changed_diff(root, include_unstaged=False):
    """Diff content in scope, unified=0. Same scoping rationale as changed_names."""
    scopes = [["--cached"]] + ([[]] if include_unstaged else [])
    return "\n".join(sh(["git", "diff"] + extra + ["--unified=0"], root=root) for extra in scopes)


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
            findings.append(f"민감 파일 커밋 시도: {n}")
            record_firing("secret", "block", n)
    # inline: added lines
    cur_file = "?"
    for ln in changed_diff(root, include_unstaged).splitlines():
        if ln.startswith("+++ b/"):
            cur_file = ln[6:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            for rx in INLINE_SECRET_RES:
                if rx.search(ln):
                    findings.append(f"인라인 시크릿 추정: {cur_file} (값 미표시)")
                    record_firing("secret", "block", cur_file)
                    break
    # inline, untracked: never appears in any git diff — read directly.
    for n, lines in read_untracked_lines(root, untracked).items():
        if dismiss_matches(n, dismiss):
            continue
        for ln in lines:
            if any(rx.search(ln) for rx in INLINE_SECRET_RES):
                findings.append(f"인라인 시크릿 추정: {n} (값 미표시)")
                record_firing("secret", "block", n)
                break
    return findings


def check_verification(root, dismiss, scope):
    include_unstaged, _ = scope
    findings = []
    # (B1) deleted test files
    for n in changed_names(root, diff_filter="D", include_unstaged=include_unstaged):
        if TEST_PATH_RE.search(n) and not dismiss_matches(n, dismiss):
            findings.append(f"테스트 파일 삭제: {n} (INV2 — 검증 약화)")
            record_firing("verification", "block", n)
    # (B2/B3) net assertion removal / skip additions
    cur = "?"
    add_assert = rm_assert = add_skip = 0
    skip_files = set()
    for ln in changed_diff(root, include_unstaged).splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
        elif ln.startswith("--- a/"):
            # a fully-deleted file has no "+++ b/..." header (its new-side header is
            # "+++ /dev/null"), so without this branch `cur` stays stuck on the previous
            # file and misattributes this file's removed assertions to it.
            cur = ln[6:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            body = ln[1:]
            if TEST_PATH_RE.search(cur) and not COMMENT_LINE_RE.match(body):
                if ASSERT_RE.search(body):
                    add_assert += 1
                if SKIP_RE.search(body):
                    add_skip += 1
                    skip_files.add(cur)
        elif ln.startswith("-") and not ln.startswith("---"):
            body = ln[1:]
            if TEST_PATH_RE.search(cur) and not COMMENT_LINE_RE.match(body) and ASSERT_RE.search(body):
                rm_assert += 1
    if add_skip:
        where = ", ".join(sorted(skip_files)) or "test"
        findings.append(f"테스트 skip/focus 지시자 추가 {add_skip}건: {where} (INV2 — 검증 약화)")
        record_firing("verification", "block", "test-skip")
    if rm_assert - add_assert >= 3:
        findings.append(f"테스트 assertion 순감소 (~{rm_assert - add_assert}줄, INV2 — 검증 약화 의심)")
        record_firing("verification", "block", "assertion-drop")
    return findings


FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n(.*?)\n---\s*(\n|\Z)", re.S)


def rule_file_confirmed(text):
    """True only if the **frontmatter** says `status: confirmed`.

    Scanning the whole document (the earlier behaviour) meant any prose that merely mentions
    the string armed every rule in the file. That is not hypothetical: the bundled
    charter.md / architecture.md templates contain the literal `status: confirmed` inside
    explanatory blockquotes, and that house style migrating into a rules file would have
    silently promoted draft rules to blocking — precisely the INV6 violation the
    draft→confirm→enforce design exists to prevent."""
    m = FRONTMATTER_RE.match(text)
    head = m.group(1) if m else ""
    return bool(re.search(r"^\s*status:\s*confirmed\s*$", head, re.I | re.M))


def check_boundaries(root, dismiss, scope):
    """Structure/boundary gate (v2, rule-driven). Read gates/rules/boundaries.md; return
    (block, warn). Frontmatter `status: confirmed` makes its rules BLOCK; otherwise (draft)
    they only WARN (INV6 — hallucinated structure rules never block until confirmed).
    Rule line: `- forbid: <path-glob> imports <substr>`. Best-effort (grep-level)."""
    include_unstaged, include_untracked = scope
    block, warn = [], []
    try:
        with open(os.path.join(root, ".claude", "guild", "gates", "rules", "boundaries.md"),
                  encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return block, warn
    rules = [(m.group(1).strip(), m.group(2).strip())
             for m in (re.match(r"\s*-\s*forbid:\s*(\S+)\s+imports?\s+(.+)", ln, re.I)
                       for ln in text.splitlines()) if m]
    if not rules:
        return block, warn
    confirmed = rule_file_confirmed(text)
    cur, added = "?", {}
    for ln in changed_diff(root, include_unstaged).splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            added.setdefault(cur, []).append(ln[1:])
    for n, lines in read_untracked_lines(root, untracked_names(root, include_untracked)).items():
        added.setdefault(n, []).extend(lines)
    for glob, forb in rules:
        for f, lines in added.items():
            if dismiss_matches(f, dismiss):
                continue
            # the fallback treats a wildcard-less glob ("lib/data") as a directory prefix —
            # "lib/data/*" (path-segment bounded), NOT "lib/data*" (bare string prefix),
            # which would also match an unrelated sibling like "lib/database_helper.dart".
            if fnmatch.fnmatch(f, glob) or fnmatch.fnmatch(f, glob.rstrip("/") + "/*"):
                if any(forb in l for l in lines):
                    msg = f"경계 위반: {f} → 금지 참조 '{forb}' (rule: {glob} imports {forb})"
                    (block if confirmed else warn).append(msg)
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
        with open(os.path.join(p, "findings.json"), "w", encoding="utf-8") as fh:
            json.dump({"open": findings}, fh, ensure_ascii=False, indent=2)
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


def block_message(reasons):
    return "🚫 Guild 게이트 차단 (커밋 거부):\n- " + "\n- ".join(reasons) + "\n\n" + HUMAN_NOTE


def deny_pretooluse(reasons):
    msg = block_message(reasons)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": msg,
    }}))
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def run_checks(root, scope):
    dismiss = dismissed(root)
    block = check_secrets(root, dismiss, scope) + check_verification(root, dismiss, scope)
    b_block, b_warn = check_boundaries(root, dismiss, scope)
    return block + b_block, b_warn


def main_git_hook():
    """Mode 1 — authoritative. Git has already finalised the index; scan exactly it."""
    root = repo_root()
    if not gates_enabled(root):
        return 0
    scope = (False, False)  # the index IS the commit at this point
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
        sys.stderr.write(block_message(block) + "\n")
        return 1
    if warn:
        sys.stderr.write("⚠ Guild 게이트 경고 (draft 경계 규칙 — 차단 안 함, confirm 시 차단):\n- "
                         + "\n- ".join(warn) + "\n")
    return 0


def main_pretooluse():
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
    flush_firings(root, "pretooluse")
    write_findings(root, block)
    if block:
        deny_pretooluse(block)  # exits 2
    if warn:
        sys.stderr.write("⚠ Guild 게이트 경고 (draft 경계 규칙 — 차단 안 함, confirm 시 차단):\n- "
                         + "\n- ".join(warn) + "\n")
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
GATES_KEY_RE = re.compile(r"\"gates\"|gates\.enabled|\"enabled\"")


def main_guard_config():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    ti = payload.get("tool_input") or {}
    path = (ti.get("file_path") or ti.get("path") or "").replace("\\", "/")
    if not path:
        return 0
    body = " ".join(str(ti.get(k, "")) for k in ("content", "new_string", "edits"))
    if GATE_CONTROL_RE.search(path):
        what = "게이트 규칙/스크립트"
    elif CONFIG_PATH_RE.search(path) and GATES_KEY_RE.search(body):
        what = "게이트 off-switch (gates.enabled)"
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
    hits = 0
    for raw in sys.stdin:
        name = raw.strip().replace("\\", "/")
        if not name or SECRET_PATH_ALLOW_RE.search(name):
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
    return main_pretooluse()


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
