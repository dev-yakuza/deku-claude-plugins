#!/usr/bin/env python3
"""
gate_precommit.py — Guild deterministic commit gate (M3 강제층, minimal set).

Wired as a repo-level `PreToolUse(Bash)` hook (installed into `.claude/settings.json` by
`/gld init`). On every Bash tool call it reads the PreToolUse payload from stdin; if the
command is a `git commit`, it runs the **minimal enforcement gates** against the *staged*
diff and BLOCKS the commit on a confirmed violation. Non-commit Bash calls pass through
untouched. Plan §11 (프롬프트=요청, 하네스=강제) · §14 M3 (게이트 최소: 시크릿 + 검증약화금지).

Two gates (the only M3 set — structure/boundary gates are v2):
  A. secret       — a sensitive file (keystore/.p12/.jks/.pem/serviceAccount/.env) or an
                    inline private-key/API-token is staged. BLOCKER.
  B. verification — the staged diff weakens tests/gates (deletes a test file, net-removes
                    assertions, or adds skips) — INV2 "검증은 어떤 자동 프로세스도 약화 못 함".
                    Heuristic (rename/semantic evasion possible — not airtight, plan §11).

Safety / status model:
- **Off-switch** (plan §11): if `.claude/guild/config.json` `gates.enabled` is false → allow all.
- **draft→confirm→enforce** (INV6): these two gates are universal + non-hallucinated, so init
  installs them **confirmed = block**. A gate whose rule file is `status: draft` only WARNS
  (printed, not blocked). Stack-specific structure rules (v2) start draft.
- **Accepted-risk registry**: a path/pattern listed in `.claude/guild/gates/dismissed.md`
  (with a stated reason) is downgraded to a warning (human already accepted it).
- Never prints secret VALUES — only file path / line number.
- Best-effort: any internal error → allow (fail-open) + a warning, so the gate never wedges
  the repo. (A gate that hard-fails commits would violate "never destructive / off-switch".)

Fail-open rationale: a gate that crashes must not block all commits. Real enforcement comes
from the checks succeeding; a broken gate degrades to advisory, matching the off-switch spirit.

Block mechanism: prints the PreToolUse deny JSON on stdout AND exits 2 (belt-and-suspenders;
see _handoff/gates wiring). Allow: exit 0, no output.
"""
import fnmatch, json, os, re, subprocess, sys

# --- rule-firing log (항목 3a) — episodic tier, gitignored, best-effort append ---
# Feeds the evolve rule scorecard (3b) + rule HR demote/retire (3c). Each firing is one line.
FIRINGS_REL = os.path.join(".claude", "guild", "memory", "gate-firings.jsonl")
_FIRINGS = []  # collected during the run, flushed once in main()


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


def flush_firings(root):
    """Append the queued firings to the gitignored episodic log. Best-effort — a
    logging failure never affects the gate verdict (fail-open spirit)."""
    if not _FIRINGS:
        return
    try:
        p = os.path.join(root, FIRINGS_REL)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        ts = now_iso()
        with open(p, "a", encoding="utf-8") as fh:
            for f in _FIRINGS:
                fh.write(json.dumps({"ts": ts, **f}, ensure_ascii=False) + "\n")
    except Exception:
        pass

# --- sensitive file patterns (BLOCK) — the "진짜 위험" set (audit 뉘앙스: 공개 식별자 제외) ---
SECRET_PATH_RE = re.compile(
    r"(^|/)("
    r".*\.keystore|.*\.jks|.*\.p12|.*\.pfx|.*\.pem|"
    r".*service[_-]?account.*\.json|"
    r".*\.env|.*\.env\..*"
    r")$", re.IGNORECASE)
# Public client identifiers that Flutter/Firebase conventionally commit — do NOT block
# (audit finding: google-services.json / firebase_options.dart are public app identifiers).
SECRET_PATH_ALLOW_RE = re.compile(
    r"(^|/)(google-services\.json|GoogleService-Info\.plist|firebase_options\.dart)$", re.IGNORECASE)
# high-signal inline secrets (value never printed)
INLINE_SECRET_RES = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    re.compile(r"gh[pousr]_[0-9A-Za-z]{36,}"),
    re.compile(r"sk_live_[0-9A-Za-z]{16,}"),
]
TEST_PATH_RE = re.compile(
    # test_*.py is specifically pytest's own discovery convention — restricted to .py so
    # this doesn't false-positive on other languages' prod files that happen to start with
    # "test_" (e.g. a Dart/JS helper named test_environment_detector.*).
    r"(^|/)(test|tests|__tests__|spec)/|_test\.|\.test\.|\.spec\.|(^|/)test_[^/]+\.py$",
    re.IGNORECASE)
ASSERT_RE = re.compile(
    r"\b(expect|verify|should)\b\s*\(|"  # JS/Dart-style matcher calls: expect(...), verify(...), should(...)
    r"\bassert\w*\s*\(|"  # assert(...) and unittest-style assertEqual(/assertTrue(/assertIn(...
    r"\bassert\b",  # bare Python `assert expr[, msg]` statement (no parens)
    re.IGNORECASE)
SKIP_RE = re.compile(
    r"\b(xit|xdescribe|pytest\.mark\.skip|todo!\()"
    r"|\.skip\(\s*(?:\)|['\"])"  # .skip()/.skip('reason')/.skip("reason") — test-skip directives,
    # not e.g. Dart's Iterable.skip(n) (a plain positional count arg, never empty/string-first)
    r"|(?<![\w.])@(Skip|Ignore|Disabled)\b",  # IGNORECASE 의도적 — @skip 등 소문자/혼용도 차단
    re.IGNORECASE)


def sh(args):
    """Run a git command, return stdout (empty on error)."""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return ""


def repo_root():
    d = sh(["git", "rev-parse", "--show-toplevel"]).strip()
    return d or os.getcwd()


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
    """Accepted-risk registry: path/pattern entries listed in dismissed.md are downgraded
    to warn (matched as a whole path-segment via dismiss_matches, not an arbitrary
    substring — a short entry like "config" must not silently exempt every file that
    happens to contain "config" anywhere in its name)."""
    try:
        with open(os.path.join(root, ".claude", "guild", "gates", "dismissed.md"), encoding="utf-8") as fh:
            return [ln.strip("-* \t").split("—")[0].split("#")[0].strip()
                    for ln in fh if ln.strip().startswith(("-", "*"))]
    except Exception:
        return []


def dismiss_matches(path, entries):
    """True if `path` is covered by an accepted-risk entry. Matches the full path, or a
    complete path segment (bounded by `/` or string start/end) — not an arbitrary
    substring, so a broad-looking entry can't accidentally exempt unrelated files."""
    for d in entries:
        if not d:
            continue
        if d == path or re.search(r"(^|/)" + re.escape(d) + r"(/|$)", path):
            return True
    return False


GIT_COMMIT_RE = re.compile(
    # `\bgit\b` alone (no command-boundary anchor) deliberately still matches after `sudo `,
    # an absolute path (`/usr/bin/git`), `time `, a subshell `(`, or an env-var prefix
    # (`GIT_AUTHOR_NAME=x git ...`) — an earlier version anchored on a strict boundary
    # (`^`/`;`/`&`/`|`/newline) immediately before `git`, which incorrectly required `git`
    # to be the very first token and silently let all of those common prefixes bypass the
    # gate entirely (a real commit went undetected → unchecked). The only thing that must
    # directly follow `git` is optional flags then `commit` — that's what excludes the
    # original false-positive this regex was written to fix (`git log ... | grep -i commit`,
    # where `commit` never directly follows `git`).
    r"\bgit\s+"
    r"(?:-{1,2}[A-Za-z][A-Za-z0-9-]*(?:[= ]\S+)?\s+)*"  # optional git global flags (-C dir, -c k=v, --no-pager)
    r"commit\b")


def is_git_commit(cmd):
    if not cmd:
        return False
    # `commit` must be the actual subcommand directly following `git` (+ optional env/flags),
    # not merely present anywhere in the string — otherwise a read-only command whose text
    # happens to mention "commit" (e.g. `git log --oneline | grep -i commit`, or a `commit`
    # substring inside a piped grep target) is wrongly treated as a commit and gated.
    return bool(GIT_COMMIT_RE.search(cmd))


def changed_names(root, diff_filter=None):
    """Union of staged (--cached) and unstaged **tracked** changes. Unstaged tracked
    changes matter because `git commit -a`/`-am` stages them WHILE the command executes —
    after this PreToolUse hook already ran and inspected `--cached` — so a stale
    `--cached`-only check would miss exactly the content about to be committed (TOCTOU).
    Scanning the union is a safe superset. `diff_filter` uses git's own syntax; a
    lowercase letter excludes that status (e.g. "d" = all except deleted).
    ⚠ Does **not** cover a brand-new file that is still untracked at hook-fire time (e.g.
    a compound `git add newfile && git commit ...` — `git add` hasn't run yet when this
    hook fires, so the file is untracked, and `git diff`/`git diff --cached` NEVER show
    untracked files regardless of flags) — see `untracked_names()` for that case."""
    names = set()
    for extra_args in (["--cached"], []):
        args = ["git", "-C", root, "diff"] + extra_args + ["--name-only"]
        if diff_filter:
            args += [f"--diff-filter={diff_filter}"]
        out = sh(args)
        names.update(n for n in out.splitlines() if n.strip())
    return names


def untracked_names(root):
    """Files git doesn't track yet (`git status --porcelain` `??` entries). Necessary
    because `changed_names`/`changed_diff` are `git diff`-based and `git diff` never shows
    untracked files, staged or not — a file created by an earlier tool call (still
    untracked) and then staged-and-committed in ONE compound Bash call
    (`git add newfile.env && git commit ...`) is untracked at the exact moment this
    PreToolUse hook fires, since `git add` hasn't executed yet. Without this, a brand-new
    secret file committed this way would silently bypass `check_secrets` entirely — verified
    empirically (`.env` created, immediate `git add .env && git commit`, gate exit 0/allow)."""
    out = sh(["git", "-C", root, "status", "--porcelain", "--untracked-files=all"])
    return {ln[3:].strip() for ln in out.splitlines() if ln.startswith("??") and ln[3:].strip()}


def changed_diff(root):
    """Union of staged and unstaged diff content, unified=0. Same TOCTOU rationale as
    changed_names — content staged by -a/-am during this call must still be visible.
    Same untracked-file blind spot as `changed_names` — see `untracked_names()`."""
    return "\n".join(
        sh(["git", "-C", root, "diff"] + extra_args + ["--unified=0"])
        for extra_args in (["--cached"], [])
    )


def read_untracked_lines(root, names):
    """Read each untracked file's raw content as a list of lines, for scans that need to
    see it directly (it appears in no `git diff`). Best-effort per file: unreadable/binary/
    huge files are skipped, never raise — this must not crash the gate (fail-open spirit).
    Caps at 2MB per file — large untracked files are almost always generated/binary
    artifacts, not something a secret/boundary scan needs to read line-by-line."""
    result = {}
    for n in names:
        path = os.path.join(root, n)
        try:
            if os.path.getsize(path) > 2_000_000:
                continue
            with open(path, encoding="utf-8", errors="ignore") as fh:
                result[n] = fh.read().splitlines()
        except OSError:
            continue
    return result


def check_secrets(root, dismiss):
    findings = []
    untracked = untracked_names(root)
    # exclude deletions ("d" = all statuses except D) — removing a secret file is a
    # remediation, not a violation; flagging it blocks exactly the cleanup INV5 wants.
    # Untracked files are unioned in — see untracked_names()'s docstring (TOCTOU: a
    # brand-new file staged-and-committed in one compound Bash call is untracked at
    # hook-fire time, invisible to every `git diff` variant).
    for n in changed_names(root, diff_filter="d") | untracked:
        if SECRET_PATH_ALLOW_RE.search(n) or dismiss_matches(n, dismiss):
            continue
        if SECRET_PATH_RE.search(n):
            findings.append(f"민감 파일 staged: {n}")
            record_firing("secret", "block", n)
    # inline: scan added lines across staged + unstaged (TOCTOU — see changed_diff)
    diff = changed_diff(root)
    cur_file = "?"
    for ln in diff.splitlines():
        if ln.startswith("+++ b/"):
            cur_file = ln[6:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            for rx in INLINE_SECRET_RES:
                if rx.search(ln):
                    findings.append(f"인라인 시크릿 추정: {cur_file} (값 미표시)")
                    record_firing("secret", "block", cur_file)
                    break
    # inline, untracked: these never appear in `changed_diff` at all (no git diff shows
    # untracked content) — read each file directly and scan the same way.
    for n, lines in read_untracked_lines(root, untracked).items():
        if dismiss_matches(n, dismiss):
            continue
        for ln in lines:
            for rx in INLINE_SECRET_RES:
                if rx.search(ln):
                    findings.append(f"인라인 시크릿 추정: {n} (값 미표시)")
                    record_firing("secret", "block", n)
                    break
    return findings


def check_verification(root, dismiss):
    findings = []
    # (B1) deleted test files (staged + unstaged — TOCTOU)
    for n in changed_names(root, diff_filter="D"):
        if TEST_PATH_RE.search(n) and not dismiss_matches(n, dismiss):
            findings.append(f"테스트 파일 삭제: {n} (INV2 — 검증 약화)")
            record_firing("verification", "block", n)
    # (B2/B3) net assertion removal / skip additions (staged + unstaged — TOCTOU)
    diff = changed_diff(root)
    cur = "?"
    add_assert = rm_assert = add_skip = 0
    for ln in diff.splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
        elif ln.startswith("--- a/"):
            # a fully-deleted file has NO "+++ b/..." header (its new-side header is
            # "+++ /dev/null"), so without this branch `cur` stays stuck on whatever file
            # preceded it in the diff — misattributing this file's removed assertions to
            # the previous one. Harmless to also set it here for a normal modify/rename
            # (the "+++ b/" line right after immediately overwrites it with the same/new path).
            cur = ln[6:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            if TEST_PATH_RE.search(cur):
                if ASSERT_RE.search(ln):
                    add_assert += 1
                if SKIP_RE.search(ln):
                    add_skip += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            if TEST_PATH_RE.search(cur) and ASSERT_RE.search(ln):
                rm_assert += 1
    if add_skip:
        findings.append(f"테스트 skip 추가 {add_skip}건 (INV2 — 검증 약화 의심)")
        record_firing("verification", "block", "test-skip")
    if rm_assert - add_assert >= 3:
        findings.append(f"테스트 assertion 순감소 (~{rm_assert - add_assert}줄, INV2 — 검증 약화 의심)")
        record_firing("verification", "block", "assertion-drop")
    return findings


def check_boundaries(root, dismiss):
    """Structure/boundary gate (v2, rule-driven). Read gates/rules/boundaries.md; return
    (block, warn). A whole-file `status: confirmed` makes its rules BLOCK; otherwise (draft)
    they only WARN (T3/INV6 — hallucinated structure rules never block until confirmed).
    Rule line: `- forbid: <path-glob> imports <substr>` — a staged file matching <path-glob>
    whose ADDED lines contain <substr> violates it. Best-effort (grep-level, not a real parser)."""
    block, warn = [], []
    try:
        text = open(os.path.join(root, ".claude", "guild", "gates", "rules", "boundaries.md"),
                    encoding="utf-8").read()
    except Exception:
        return block, warn
    confirmed = bool(re.search(r"status:\s*confirmed", text, re.I))
    rules = [(m.group(1).strip(), m.group(2).strip())
             for m in (re.match(r"\s*-\s*forbid:\s*(\S+)\s+imports?\s+(.+)", ln, re.I)
                       for ln in text.splitlines()) if m]
    if not rules:
        return block, warn
    diff = changed_diff(root)  # union staged+unstaged — same TOCTOU rationale as the other checks
    cur, added = "?", {}
    for ln in diff.splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            added.setdefault(cur, []).append(ln[1:])
    # untracked files never appear in `changed_diff` (no git diff shows untracked content)
    # — a brand-new file staged-and-committed in one compound call would otherwise bypass
    # boundary checking entirely; treat its whole content as "added" lines, same as check_secrets.
    for n, lines in read_untracked_lines(root, untracked_names(root)).items():
        added.setdefault(n, []).extend(lines)
    for glob, forb in rules:
        for f, lines in added.items():
            if dismiss_matches(f, dismiss):
                continue
            # fallback treats a wildcard-less glob (e.g. "lib/data") as a directory prefix —
            # "lib/data/*" (path-segment bounded), NOT "lib/data*" (bare string prefix), which
            # would also match an unrelated sibling like "lib/database_helper.dart".
            if fnmatch.fnmatch(f, glob) or fnmatch.fnmatch(f, glob.rstrip("/") + "/*"):
                if any(forb in l for l in lines):
                    msg = f"경계 위반: {f} → 금지 참조 '{forb}' (rule: {glob} imports {forb})"
                    (block if confirmed else warn).append(msg)
                    record_firing(f"boundary:{glob} imports {forb}", "block" if confirmed else "warn", f)
    return block, warn


def write_findings(root, findings):
    try:
        p = os.path.join(root, ".claude", "guild", "gates")
        os.makedirs(p, exist_ok=True)
        with open(os.path.join(p, "findings.json"), "w", encoding="utf-8") as fh:
            json.dump({"open": findings}, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def deny(reasons):
    msg = "🚫 Guild 게이트 차단 (커밋 거부):\n- " + "\n- ".join(reasons) + \
          "\n\n수용된 위험이면 `.claude/guild/gates/dismissed.md`에 사유와 함께 등록하거나 " \
          "`/gld config`로 게이트를 끄세요. 시크릿은 키 회전·히스토리 정리가 필요할 수 있습니다(사람 조치)."
    # PreToolUse deny (finalized against the current hook schema during wiring)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": msg,
    }}))
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def main():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    cmd = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
        cmd = (payload.get("tool_input") or {}).get("command", "") or ""
    except Exception:
        cmd = raw  # degrade: treat the raw text as the command
    if not is_git_commit(cmd):
        return 0  # not a commit → allow silently
    root = repo_root()
    if not gates_enabled(root):
        return 0  # off-switch
    dismiss = dismissed(root)
    block = check_secrets(root, dismiss) + check_verification(root, dismiss)
    b_block, b_warn = check_boundaries(root, dismiss)
    block += b_block
    flush_firings(root)  # log all firings (block + warn) before any deny-exit (항목 3a)
    # Always rewrite findings.json so it reflects THIS commit's gate state, not a stale
    # snapshot: when a previously-blocked item is later dismissed (or fixed), block is now
    # empty and this clears it to {"open": []}. Writing only inside `if block:` left the
    # last-blocked findings fossilised — a phantom open item other readers (evolve/audit)
    # misread as unresolved.
    write_findings(root, block)
    if block:
        deny(block)  # exits 2
    if b_warn:
        # draft boundary rules WARN only (do not block) — advisory until confirmed
        sys.stderr.write("⚠ Guild 게이트 경고 (draft 경계 규칙 — 차단 안 함, confirm 시 차단):\n- "
                         + "\n- ".join(b_warn) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # fail-open: a broken gate must never wedge commits (off-switch spirit)
        sys.stderr.write(f"guild gate: internal error, allowing commit ({e})\n")
        sys.exit(0)
