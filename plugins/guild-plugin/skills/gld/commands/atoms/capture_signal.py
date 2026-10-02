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

Writes to  <repo-root>/.claude/guild/memory/ground-truth.jsonl  (append-only, one JSON per line,
gitignored). Creates the dir/file if missing. Best-effort: on any failure it warns to stderr
and exits non-zero WITHOUT raising, so a logging problem never blocks the spine.

Two READ-ONLY modes support the stage-exit capture reconciliation (_signals.md Section C,
"Capture reconciliation"). Nothing in the spine checked that a capture actually happened, and
in one repo 2–4 members per sprint ended `done` with zero entries:
    capture_signal.py --mark --issue 893 --stage execute
        records the stage start (UTC) in <memory>/stage-start/893-execute.txt and prints it —
        a FILE, because a stamp held only in context does not survive a compaction, which is
        the very case the reconciliation exists for
    capture_signal.py --count --issue 893 --stage execute --kind correction --since auto
        prints how many entries for that Issue, stage (and kind, when given) have ts >= the
        marked start — reconciled per kind, so one kind's surplus cannot hide another's gap
        (`--since <ISO>` takes an explicit YYYY-MM-DDTHH:MM:SSZ instead)
    capture_signal.py --now
        prints the current UTC time
"""
import re

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
import argparse, json, os, sys

LOG_REL = os.path.join(".claude", "guild", "memory", "ground-truth.jsonl")
# "revert" is intentionally NOT a kind: a git revert is a durable signal, read on-demand
# via scan_git at evolve time (_signals.md Section A/C) — it is never captured to this
# log. Accepting it here would silently contradict that contract.
#
# "accepted-risk" IS accepted here but nothing in the spine calls it — that is deliberate, not
# an oversight. The source of record for an accepted risk is the human-edited
# `.claude/guild/gates/dismissed.md` registry (_signals.md Section C): the human made the call,
# so the human's own file is the anchor, and auto-appending a second copy here would double-count
# it in the data-sufficiency volume. The kind is kept so a future auto-capture path has a stable
# name to use. ⚠ If you wire it, also update `_data_sufficiency.md` — its Axis-1 breakdown
# deliberately omits accepted-risk from the counted set today.
KINDS = ("correction", "verify-gap", "accepted-risk", "stagnation")


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
    ap.add_argument("--now", action="store_true",
                    help="read-only: print the current UTC time and exit")
    ap.add_argument("--mark", action="store_true",
                    help="record the stage start for --issue/--stage in the memory dir "
                         "(stage-start/<issue>-<stage>.txt), print it, and exit")
    ap.add_argument("--count", action="store_true",
                    help="read-only: print how many entries match --issue/--stage with "
                         "ts >= --since, and exit (stage-exit capture reconciliation)")
    ap.add_argument("--since", default=None,
                    help="with --count: `auto` (the --mark file) or an ISO-8601 UTC "
                         "YYYY-MM-DDTHH:MM:SSZ lower bound")
    ap.add_argument("--kind", choices=KINDS)
    ap.add_argument("--summary")
    ap.add_argument("--issue", default=None)
    ap.add_argument("--stage", default=None)
    ap.add_argument("--role", default=None)
    ap.add_argument("--area", default=None,
                    help="path-prefix or short area keyword the signal touches "
                         "(e.g. 'lib/theme' or 'auth') — used for runtime working-memory "
                         "retrieval at pre-flight (_preflight.md Item 8). Optional.")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--surprise", action="store_true")
    ap.add_argument("--escalated", action="store_true",
                     help="this loop-back's retry ran the redone role one tier above its "
                          "default (_model_tiering.md Section A/B). A bump marker only — "
                          "evolve's model-tier test (Section C) does not read it.")
    ap.add_argument("--log", default=None,
                    help="override log path (default: <repo-root>/" + LOG_REL + ")")
    args = ap.parse_args()

    if args.now:
        print(now_iso())
        return 0
    log_path = args.log or os.path.join(repo_root(), LOG_REL)
    mark_dir = os.path.join(os.path.dirname(log_path), "stage-start")
    issue_key = str(args.issue or "").lstrip("#")
    if args.mark:
        if not (issue_key and args.stage):
            sys.stderr.write("capture_signal: --mark needs --issue and --stage\n")
            return 2
        stamp = now_iso()
        try:
            os.makedirs(mark_dir, exist_ok=True)
            with open(os.path.join(mark_dir, f"{issue_key}-{args.stage}.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write(stamp + "\n")
        except OSError as e:
            sys.stderr.write(f"capture_signal: could not write the stage-start mark ({e})\n")
            return 1
        print(stamp)
        return 0
    if args.count and args.since == "auto":
        try:
            with open(os.path.join(mark_dir, f"{issue_key}-{args.stage}.txt"),
                      encoding="utf-8") as fh:
                args.since = fh.read().strip()
        except OSError:
            sys.stderr.write("capture_signal: no stage-start mark for this issue/stage — "
                             "run --mark at Step 0\n")
            return 2
    if args.count and args.since and not ISO_RE.match(args.since):
        # A malformed bound compares wrongly as a string and returns a plausible 0, which
        # reads as "nothing recorded" and triggers duplicate backfills. Refuse instead.
        sys.stderr.write(f"capture_signal: --since {args.since!r} is not YYYY-MM-DDTHH:MM:SSZ\n")
        return 2
    if args.count:
        # Counted from the ACTIVE log only: it is written during the stage being reconciled,
        # and evolve's consolidation (which moves lines to consolidated.jsonl) never runs
        # inside a stage. A missing log is a count of 0, which is exactly the finding.
        if not (args.issue and args.stage and args.since):
            sys.stderr.write("capture_signal: --count needs --issue, --stage and --since\n")
            return 2
        n = 0
        try:
            with open(log_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if (str(e.get("issue")) == str(args.issue).lstrip("#")
                            and e.get("stage") == args.stage
                            and (args.kind is None or e.get("kind") == args.kind)
                            and str(e.get("ts") or "") >= args.since):
                        n += 1
        except FileNotFoundError:
            pass
        except OSError as e:
            sys.stderr.write(f"capture_signal: could not read ({e})\n")
            return 1
        print(n)
        return 0
    if not args.kind or not args.summary:
        sys.stderr.write("capture_signal: --kind and --summary are required to capture\n")
        return 2

    issue = None
    if args.issue not in (None, "", "null"):
        try:
            issue = int(args.issue)
        except (TypeError, ValueError):
            issue = args.issue  # keep non-numeric as-is rather than dropping the signal
            # An UNSUBSTITUTED doc placeholder is the one non-numeric value that is never
            # legitimate: `_bash_rules.md` item 9 requires `$1`/`<N>`/`<issue>` to be replaced
            # with the literal before the call, and every caller writes one of those forms.
            # Silently accepting it wrote `"issue": "$1"` into the ground-truth log, where it
            # survives as a permanent un-joinable row — evolve dedups and ranks by issue, so the
            # signal is not just wrong, it is invisible. Warn loudly; still record it (dropping
            # the signal would lose the observation entirely), but make the mistake findable.
            if str(args.issue).startswith(("$", "<")):
                sys.stderr.write(
                    f"capture_signal: WARNING — --issue {args.issue!r} looks like an "
                    f"unsubstituted placeholder. Substitute the literal issue number before "
                    f"the Bash call (_bash_rules.md item 9). Recording it as-is.\n")

    entry = {
        "ts": now_iso(),
        "kind": args.kind,
        "issue": issue,
        "stage": args.stage,
        "role": args.role,
        "area": (args.area or "").strip()[:80] or None,
        "summary": args.summary.strip()[:200],
        "evidence": (args.evidence or "").strip()[:200] or None,
        "surprise": bool(args.surprise),
        "escalated": bool(args.escalated),
    }

    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        sys.stderr.write(f"capture_signal: could not append ({e}) — spine continues\n")
        return 1

    print(f"captured {entry['kind']}" + (" [surprise]" if entry["surprise"] else "")
          + (" [escalated]" if entry["escalated"] else "") + f" → {log_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:            # never crash the caller
        sys.stderr.write(f"capture_signal failed: {e}\n")
        sys.exit(1)
