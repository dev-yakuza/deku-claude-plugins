#!/usr/bin/env python3
"""
capture_signal.py — Guild growth-loop foundation (①), the sanctioned ground-truth appender.

Appends ONE entry to the episodic ground-truth log at the moment an ephemeral signal occurs
(a human correction at a discuss gate, or a verify self-report↔runner gap). Contract: see
atoms/_signals.md Sections C & D. This is the ONLY sanctioned write in the growth-loop
foundation — it exists because atomic-bash (_bash_rules.md) forbids `>>` redirection, so the
append runs as a single bundled command instead.

Invoked as ONE bash call from a gate handler:
    python3 <SKILL_DIR>/commands/atoms/capture_signal.py --kind correction \
        --issue 893 --stage design --role tech-lead \
        --summary "전역 테마 토큰 수정안을 사람이 위젯 레벨로 override" \
        --evidence "discuss 3안 중 A안(위젯) 선택; PR #895" --surprise

Writes to  <cwd>/.claude/guild/memory/ground-truth.jsonl  (append-only, one JSON per line,
gitignored). Creates the dir/file if missing. Best-effort: on any failure it warns to stderr
and exits non-zero WITHOUT raising, so a logging problem never blocks the spine.
"""
import argparse, json, os, sys

LOG_REL = os.path.join(".claude", "guild", "memory", "ground-truth.jsonl")
KINDS = ("correction", "verify-gap", "revert", "accepted-risk")


def repo_root():
    """Resolve the repo root by walking up for a .git entry, so the log lands at
    the repo-local memory dir even when a stage runs from a subdir or worktree
    (a worktree's .git is a file, which os.path.exists still matches). Falls back
    to cwd if no .git is found — prevents a silent per-subdir log split."""
    d = start = os.getcwd()
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return start
        d = parent


def now_iso():
    try:
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True, choices=KINDS)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--issue", default=None)
    ap.add_argument("--stage", default=None)
    ap.add_argument("--role", default=None)
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--surprise", action="store_true")
    ap.add_argument("--log", default=None, help="override log path (default: <cwd>/" + LOG_REL + ")")
    args = ap.parse_args()

    issue = None
    if args.issue not in (None, "", "null"):
        try:
            issue = int(args.issue)
        except (TypeError, ValueError):
            issue = args.issue  # keep non-numeric as-is rather than dropping the signal

    entry = {
        "ts": now_iso(),
        "kind": args.kind,
        "issue": issue,
        "stage": args.stage,
        "role": args.role,
        "summary": args.summary.strip()[:200],
        "evidence": (args.evidence or "").strip()[:200] or None,
        "surprise": bool(args.surprise),
    }

    log_path = args.log or os.path.join(repo_root(), LOG_REL)
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        sys.stderr.write(f"capture_signal: could not append ({e}) — spine continues\n")
        return 1

    print(f"captured {entry['kind']}" + (" [surprise]" if entry["surprise"] else "") + f" → {LOG_REL}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:            # never crash the caller
        sys.stderr.write(f"capture_signal failed: {e}\n")
        sys.exit(1)
