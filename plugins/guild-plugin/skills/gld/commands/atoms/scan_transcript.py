#!/usr/bin/env python3
"""
scan_transcript.py — Guild growth-loop foundation (①), bundled best-effort transcript reader.

Reads Claude Code transcripts for a repo and extracts FRICTION signals evolve can propose from:
repeated permission denials, recurring tool errors, rediscovery, repeated commands.

Contract & rationale: see atoms/_signals.md Section F. The CC transcript format is undocumented
and the on-disk dir name is a LOSSY encoding of the cwd, so this is deliberately best-effort:
it matches transcripts by the in-record `cwd` field (which carries the true path), skips
unparseable lines, and exits non-zero with a one-line reason if it cannot read at all — the
caller then degrades to the durable git/CI/gate backbone.

Invoked as ONE bash call (atomic-bash exception, plan §8 정정):
    python3 <SKILL_DIR>/commands/atoms/scan_transcript.py --repo-cwd <abs-repo-path>

Frequency is measured by DISTINCT session count (>=K), not recency, so there is no time-window
flag: a --since-days filter over the fragile, undocumented transcript timestamps was error-prone
(undated sessions, mixed ISO formats) for no real benefit — the evolve ledger skip-list and the
"already in init/knowledge" filter handle staleness instead (plan 부록 D 3중 리뷰 P3 결정).

Read-only. Never writes transcripts. Prints a `>>> RESULT <<<` line then a JSON object.
"""
import argparse, glob, json, os, re, sys
from collections import defaultdict

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

# --- friction signatures (kill-gate validated) -------------------------------
PERMISSION_RE = re.compile(
    r"Permission to use \w+ with command (.+?) has been denied"
    r"|The user doesn't want to proceed"
)
# tool_result error body -> (label, mapping). Order matters; first match wins.
ERROR_SIGS = [
    (re.compile(r"Cancelled: parallel tool call"),      None),  # DISCOUNT: symptom of a sibling failure
    (re.compile(r"has not been read yet"),              ("edit-before-read", "③ habit")),
    (re.compile(r"Could not resolve to a Repository"),  ("gh-repo-unresolved", "⑥ fact")),
    (re.compile(r"command not found"),                  ("command-not-found", "⑥ fact")),
    (re.compile(r"No such file or directory"),          ("no-such-file", "⑥ fact")),
    (re.compile(r"Caller does not have .* permission"), ("auth-permission", "⑥ fact")),
]
# rediscovery / identity-probe commands (a subset of repeated bash commands)
REDISCOVERY_RE = re.compile(r"^\s*(gh repo view|gh auth (status|switch)|gh api repos/|cat .*config|printenv)")


def text_of(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c
    parts = []
    if isinstance(c, list):
        for x in c:
            if not isinstance(x, dict):
                continue
            t = x.get("type")
            if t == "text":
                parts.append(x.get("text", ""))
            elif t == "tool_result":
                r = x.get("content")
                if isinstance(r, str):
                    parts.append(r)
                elif isinstance(r, list):
                    parts.append(" ".join(y.get("text", "") for y in r if isinstance(y, dict)))
    return " ".join(parts)


def bash_commands(msg):
    """Yield each Bash tool_use command string in an assistant message."""
    c = msg.get("content")
    if not isinstance(c, list):
        return
    for x in c:
        if isinstance(x, dict) and x.get("type") == "tool_use" and x.get("name") == "Bash":
            cmd = (x.get("input") or {}).get("command")
            if isinstance(cmd, str) and cmd.strip():
                yield cmd.strip()


def file_matches_repo(path, repo_cwd):
    """Best-effort: does any record in this transcript carry cwd == repo_cwd?"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i > 400:            # cwd appears early; bound the probe
                    break
                line = line.strip()
                if not line or '"cwd"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("cwd") == repo_cwd:
                    return True
    except OSError:
        return False
    return False


def scan_file(path):
    """Return per-session friction: (perms:set, errors:list, cmds:set) or None if unreadable."""
    perms, errors, cmds = set(), [], set()
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                msg = d.get("message") or {}
                txt = text_of(msg)
                if txt:
                    m = PERMISSION_RE.search(txt)
                    if m:
                        perms.add((m.group(1) or "user-vetoed-edit").strip()[:80])
                    for rx, label in ERROR_SIGS:
                        if rx.search(txt):
                            if label:                       # None => discounted cascade
                                errors.append(label)
                            break
                for cmd in bash_commands(msg):
                    cmds.add(cmd[:80])
    except OSError:
        return None
    return perms, errors, cmds


def rank(sessions):
    if sessions >= 6:
        return "high"
    if sessions >= 3:
        return "med"
    return "low"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-cwd", required=True)
    args = ap.parse_args()

    repo_cwd = os.path.abspath(os.path.expanduser(args.repo_cwd))

    if not os.path.isdir(PROJECTS_DIR):
        sys.stderr.write("no ~/.claude/projects dir — transcript source unavailable\n")
        return 2

    files = glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))
    matched = [f for f in files if file_matches_repo(f, repo_cwd)]
    if not matched:
        sys.stderr.write(f"no transcripts matched cwd={repo_cwd} (lossy encoding / none this repo)\n")
        return 3

    # aggregate DISTINCT sessions per signal key
    perm_sessions = defaultdict(int)
    err_sessions = defaultdict(lambda: [0, ""])   # label -> [sessions, mapping]
    cmd_sessions = defaultdict(int)
    scanned = 0
    for f in matched:
        r = scan_file(f)
        if r is None:
            continue
        scanned += 1
        perms, errors, cmds = r
        for p in perms:
            perm_sessions[p] += 1
        for label, mapping in set(errors):
            err_sessions[label][0] += 1
            err_sessions[label][1] = mapping
        for c in cmds:
            cmd_sessions[c] += 1

    signals = []
    for cmd, n in perm_sessions.items():
        if n >= 2:
            # A generic veto with no captured command is heterogeneous and not mappable to one
            # allow-rule — kill-gate Tier C. Surface it, but cap confidence so it never outranks
            # a specific, actionable signal.
            if cmd == "user-vetoed-edit":
                signals.append({"confidence": "low", "class": "permission",
                                "summary": "일반 편집 거부(명령 특정 안 됨)", "evidence": f"{n} sessions",
                                "sessions": n, "mapping": "노이즈 후보 — 이질적, 단일 룰 매핑 불가"})
            else:
                signals.append({"confidence": rank(n), "class": "permission",
                                "summary": f"반복 거부된 명령: {cmd}", "evidence": f"{n} sessions",
                                "sessions": n, "mapping": "allow-rule (위험 명령이면 기각)"})
    for label, (n, mapping) in err_sessions.items():
        if n >= 2:
            signals.append({"confidence": rank(n), "class": "tool-error",
                            "summary": f"반복 툴 에러: {label}", "evidence": f"{n} sessions",
                            "sessions": n, "mapping": mapping})
    for cmd, n in cmd_sessions.items():
        if n >= 3:
            cls = "rediscovery" if REDISCOVERY_RE.match(cmd) else "repeated-cmd"
            signals.append({"confidence": rank(n), "class": cls,
                            "summary": f"반복 명령: {cmd}", "evidence": f"{n} sessions",
                            "sessions": n, "mapping": "⑥ fact / allow-rule"})

    conf_rank = {"high": 3, "med": 2, "low": 1}
    signals.sort(key=lambda s: (conf_rank.get(s["confidence"], 0), s["sessions"]), reverse=True)
    out = {
        "feasibility": f"{scanned}/{len(matched)} transcripts parsed for {repo_cwd}",
        "degraded": False,
        "signals": signals,
    }
    print(">>> RESULT <<<")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                       # never crash the caller; degrade
        sys.stderr.write(f"scan_transcript failed: {e}\n")
        sys.exit(1)
