#!/usr/bin/env python3
"""base_ci.py — is the default branch already red? One line for `sprint run` Phase 0 and
`sprint plan` Phase 2 (0.99.2 A9; the rule is 0.98.7 Z3's, the computation moved here).

Usage:
  python3 base_ci.py --repo <owner>/<repo>

WHAT IT DOES (fixed order — every gh call is its own subprocess; `_bash_rules.md` sanctioned
exception 1, one bundled python call):
  1. `gh repo view <owner>/<repo> --json defaultBranchRef --jq .defaultBranchRef.name` → <d>.
  2. `gh api repos/<owner>/<repo>/commits/<d>/check-runs --paginate --jq '.check_runs[] | {id,
     name, conclusion, annotations: .output.annotations_count}'` — one JSON object per run
     (`--paginate` reads past the 30-run page; `--jq` runs per page, so the stream is gathered
     here, never in jq).
  3. **Only when 2 found no run at all** (CI runs on PRs only — one-man-company): the last merged
     PR, `gh pr list --repo <owner>/<repo> --state merged --base <d> --limit 20 --json
     number,headRefOid,mergedAt --jq 'if length == 0 then null else (max_by(.mergedAt) |
     {number, headRefOid}) end'` (the list is in creation order, so `--limit 1` may not be the
     last merge); `null` → `없음`. Otherwise call 2 for `commits/<headRefOid>/check-runs`.
     A branch that has runs never reaches this call (measured word_app: main had runs and the
     leader still read the last merged PR).
  4. **Dedupe by check name — keep the run with the highest `id`** (a re-run is a newer id;
     measured one-man-company PR #616: `Conventional 접두어 검증` three times; word_app main:
     `Dependabot` four times). Everything below sees the deduped runs only — reading the
     annotations before the dedupe spent #616's three reads on duplicates and never reached
     `Analyze & Test`.
  5. The verdict — the same rule as `qa.md` Step 2's *Which one*: conclusion `failure` ·
     `timed_out` · `cancelled` · `action_required` → red; else any `null` → still running;
     else green (`neutral` and `skipped` are not red).
  6. For the deduped `failure` runs with annotations (at most 3, by name):
     `gh api repos/<owner>/<repo>/check-runs/<id>/annotations --jq '.[] | {annotation_level,
     message}'`. Only `failure`-level annotations are a cause (measured #617: a `warning`-level
     `Node.js 20 is deprecated …` and a `notice` come with the real failure); one whose message
     contains `was not started` makes that check `ci-blocked` (never started — billing), kept
     apart from red.

OUTPUT (stdout) — `Base CI: <result>`, one line; a second line `ci-blocked: <names>` only when
red and ci-blocked are mixed. Names are the checks judged, sorted, joined by `, `:
  green(<names>) · green(<names>) (진행 중) · red(<names>) (근거: <d> 최신 커밋 | 마지막 머지 PR
  #<p>) · ci-blocked(<names>) · 없음 · unavailable (a call failed — the reason on stderr).
The caller prints it verbatim (`run.md` Phase 0) — never paraphrased.

Exit: 0 (judged, whatever the result) · 64 usage · 65 gh unavailable (`unavailable`).
"""

import sys

# Same reason as sprint_dag.py: no __pycache__ beside a plugin file updated in place.
sys.dont_write_bytecode = True

import argparse
import json
import subprocess

EXIT_USAGE = 64
EXIT_ENV = 65

RED = ("failure", "timed_out", "cancelled", "action_required")
NOT_STARTED = "was not started"
MAX_ANNOTATION_READS = 3
RUNS_JQ = ".check_runs[] | {id, name, conclusion, annotations: .output.annotations_count}"
LAST_MERGED_JQ = ("if length == 0 then null else (max_by(.mergedAt) | {number, headRefOid}) end")
ANNOTATIONS_JQ = ".[] | {annotation_level, message}"


class EnvError(Exception):
    pass


def gh_text(args):
    try:
        p = subprocess.run(["gh"] + args, capture_output=True, text=True)
    except OSError as exc:   # no gh on PATH, not executable — `unavailable`, 65, never a traceback
        raise EnvError("gh %s: %s" % (" ".join(args[:2]), exc))
    if p.returncode != 0:
        raise EnvError("gh %s: %s" % (" ".join(args[:2]), (p.stderr or p.stdout).strip()[:200]))
    return p.stdout


def json_stream(text):
    """Every JSON value in `text`, in order — `--paginate --jq` prints one value per line, and a
    page boundary is just more lines."""
    out, dec, i = [], json.JSONDecoder(), 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        try:
            obj, i = dec.raw_decode(text, i)
        except ValueError:
            raise EnvError("gh returned non-JSON")
        out.append(obj)
    return out


def check_runs(repo, ref):
    runs = []
    for o in json_stream(gh_text(["api", "repos/%s/commits/%s/check-runs" % (repo, ref),
                                  "--paginate", "--jq", RUNS_JQ])):
        if isinstance(o, dict) and isinstance(o.get("id"), int) and o.get("name"):
            runs.append(o)
    return runs


def dedupe(runs):
    """One run per check name: the highest id (the latest attempt)."""
    best = {}
    for r in runs:
        if r["name"] not in best or r["id"] > best[r["name"]]["id"]:
            best[r["name"]] = r
    return [best[n] for n in sorted(best)]


def not_started(repo, run_id):
    for a in json_stream(gh_text(["api", "repos/%s/check-runs/%d/annotations" % (repo, run_id),
                                  "--jq", ANNOTATIONS_JQ])):
        if (isinstance(a, dict) and a.get("annotation_level") == "failure"
                and NOT_STARTED in str(a.get("message") or "")):
            return True
    return False


def verdict(repo, d):
    """→ (result, second_line or None)."""
    runs = check_runs(repo, d)
    basis = "%s 최신 커밋" % d
    if not runs:
        last = json_stream(gh_text(["pr", "list", "--repo", repo, "--state", "merged", "--base", d,
                                    "--limit", "20", "--json", "number,headRefOid,mergedAt",
                                    "--jq", LAST_MERGED_JQ]) or "null")
        last = last[0] if last else None
        if not isinstance(last, dict) or not last.get("headRefOid"):
            return "없음", None
        basis = "마지막 머지 PR #%s" % last.get("number")
        runs = check_runs(repo, last["headRefOid"])
        if not runs:
            return "없음", None
    runs = dedupe(runs)
    red = [r for r in runs if str(r.get("conclusion") or "").lower() in RED]
    blocked = set()
    reads = [r for r in red if str(r.get("conclusion")).lower() == "failure"
             and isinstance(r.get("annotations"), int) and r["annotations"] > 0]
    for r in reads[:MAX_ANNOTATION_READS]:
        if not_started(repo, r["id"]):
            blocked.add(r["name"])
    real = [r["name"] for r in red if r["name"] not in blocked]
    names = lambda xs: ", ".join(sorted(xs))
    if real:
        second = ("ci-blocked: %s" % names(blocked)) if blocked else None
        return "red(%s) (근거: %s)" % (names(real), basis), second
    if blocked:
        return "ci-blocked(%s)" % names(blocked), None
    judged = names(r["name"] for r in runs)
    if any(r.get("conclusion") is None for r in runs):
        return "green(%s) (진행 중)" % judged, None
    return "green(%s)" % judged, None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="base_ci.py", add_help=True)
    ap.add_argument("--repo", required=True)
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else 0
    if a.repo.count("/") != 1 or not all(a.repo.split("/")):
        sys.stderr.write("base_ci: --repo must be <owner>/<repo>\n")
        return EXIT_USAGE
    try:
        d = gh_text(["repo", "view", a.repo, "--json", "defaultBranchRef",
                     "--jq", ".defaultBranchRef.name"]).strip()
        if not d:
            raise EnvError("no default branch")
        result, second = verdict(a.repo, d)
    except EnvError as exc:
        sys.stderr.write("base_ci: %s\n" % exc)
        print("Base CI: unavailable")
        return EXIT_ENV
    print("Base CI: %s" % result)
    if second:
        print(second)
    return 0


if __name__ == "__main__":
    sys.exit(main())
