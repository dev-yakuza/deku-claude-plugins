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
    r"serviceAccount.*\.json|.*-service-account.*\.json|"
    r"\.env|\.env\..*"
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
]
TEST_PATH_RE = re.compile(r"(^|/)(test|tests|__tests__|spec)/|_test\.|\.test\.|\.spec\.", re.IGNORECASE)
ASSERT_RE = re.compile(r"\b(assert|expect|verify|should|test|it)\b\s*\(", re.IGNORECASE)
SKIP_RE = re.compile(r"\b(xit|xdescribe|\.skip|@Skip|@Ignore|@Disabled|pytest\.mark\.skip|todo!\()", re.IGNORECASE)


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
    """Accepted-risk registry: substrings listed in dismissed.md are downgraded to warn."""
    try:
        with open(os.path.join(root, ".claude", "guild", "gates", "dismissed.md"), encoding="utf-8") as fh:
            return [ln.strip("-* \t").split("—")[0].split("#")[0].strip()
                    for ln in fh if ln.strip().startswith(("-", "*"))]
    except Exception:
        return []


def is_git_commit(cmd):
    if not cmd:
        return False
    # tolerate flags/env prefixes; require a `git ... commit` that actually commits
    if not re.search(r"\bgit\b", cmd) or not re.search(r"\bcommit\b", cmd):
        return False
    # skip `git commit --amend`? still a commit → gate it. skip commit-message-only helpers? no.
    return True


def staged_names(root):
    out = sh(["git", "-C", root, "diff", "--cached", "--name-only"])
    return [n for n in out.splitlines() if n.strip()]


def staged_deleted_names(root):
    out = sh(["git", "-C", root, "diff", "--cached", "--name-only", "--diff-filter=D"])
    return [n for n in out.splitlines() if n.strip()]


def check_secrets(root, dismiss):
    findings = []
    for n in staged_names(root):
        if SECRET_PATH_ALLOW_RE.search(n) or any(d and d in n for d in dismiss):
            continue
        if SECRET_PATH_RE.search(n):
            findings.append(f"민감 파일 staged: {n}")
            record_firing("secret", "block", n)
    # inline: scan the staged diff added lines only
    diff = sh(["git", "-C", root, "diff", "--cached", "--unified=0"])
    line_no = 0
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
    return findings


def check_verification(root, dismiss):
    findings = []
    # (B1) deleted test files
    for n in staged_deleted_names(root):
        if TEST_PATH_RE.search(n) and not any(d and d in n for d in dismiss):
            findings.append(f"테스트 파일 삭제: {n} (INV2 — 검증 약화)")
            record_firing("verification", "block", n)
    # (B2/B3) net assertion removal / skip additions in staged test diffs
    diff = sh(["git", "-C", root, "diff", "--cached", "--unified=0"])
    cur = "?"
    add_assert = rm_assert = add_skip = 0
    per_file = {}
    for ln in diff.splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            if TEST_PATH_RE.search(cur):
                if ASSERT_RE.search(ln):
                    add_assert += 1
                if SKIP_RE.search(ln):
                    add_skip += 1
                    per_file[cur] = per_file.get(cur, 0)
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
    diff = sh(["git", "-C", root, "diff", "--cached", "--unified=0"])
    cur, added = "?", {}
    for ln in diff.splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            added.setdefault(cur, []).append(ln[1:])
    for glob, forb in rules:
        for f, lines in added.items():
            if any(d and d in f for d in dismiss):
                continue
            if fnmatch.fnmatch(f, glob) or fnmatch.fnmatch(f, glob.rstrip("*") + "*"):
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
    if block:
        write_findings(root, block)
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
