#!/usr/bin/env -S python3 -I
"""Base-green check of a settings proposal (design §7.10, §7.12 S8) — a thin shell around gxengine.basecheck (stage 4 VB1).

    python3 -I base_check.py --repo-root <checkout> --rev <base> --config <config.json>
                             --srt <path to srt> --work <folder> --out <report folder>
                             [--prepare-from <main checkout>] [--name NAME] [--keep-cache]
                             [--override NAME=command …] [--exception local-binding|weaker-network|user-tmp|host:<name> …]

The check itself is the engine's (`engine.py base-check`, the sprint supervisor and init run the same
function): a fresh worktree of the revision, toolchain prepare, every named repository command under the
run boundary, red twice on the same tree = red. This shell keeps it away from the real engine home — its
records, cache and temporary worktree live in `<work>/<name>/engine`, removed afterwards (`--keep-cache`
keeps the Guild cache) — and writes `base-check.json` / `base-check.md` / `logs/` for the proposal's
review. `--override` / `--exception` are what-if runs of a proposal (nothing is written to it).

`--repo-root` should be a scratch clone (`git clone --local --no-hardlinks <repo> <scratch>`):
`git worktree add` / `remove` write `.git/worktrees/` of that checkout. `--work` must not be under /tmp
(§7.6: records and worktrees outside the temp areas a session may write).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ENGINE_ROOT)

from gxengine import basecheck, defaults, gitops, paths as pathsmod, repoconfig, store  # noqa: E402

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(ENGINE_ROOT)))
REPO = "gld/base-check"                   # the scratch engine layout has one repository
TAIL_FAIL, TAIL_OK = 120, 25
EXCEPTIONS = {"local-binding": "allow_local_binding", "weaker-network": "weaker_network_isolation"}


def user_tmp():
    """`getconf DARWIN_USER_TEMP_DIR`, canonical — the value of the allow_write token {user_tmp} — or None."""
    try:
        p = subprocess.run(["getconf", "DARWIN_USER_TEMP_DIR"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return None
    path = p.stdout.strip().rstrip("/")
    return os.path.realpath(path) if p.returncode == 0 and path.startswith("/") else None


def refuse_work(work):
    real = os.path.realpath(work)
    for forbidden in ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/"):
        if (real + "/").startswith(forbidden):
            raise SystemExit(f"error: --work must not be under {forbidden} (§7.6: records/worktrees outside Claude's default-writable temp areas)")


def what_if(raw, overrides, exceptions):
    """(the settings with the what-if changes, [note])."""
    raw, notes = json.loads(json.dumps(raw)), []
    for ov in overrides or []:
        name, _, cmd = ov.partition("=")
        if "cmd" not in raw["commands"].get(name, {}) or not cmd:
            raise SystemExit(f"error: --override {ov!r}: unknown command or empty text")
        raw["commands"][name]["cmd"] = cmd
        notes.append(f"command {name} overridden: {cmd}")
    for ex in exceptions or []:
        sx = raw.setdefault("sandbox_exceptions", {})
        if ex in EXCEPTIONS:
            sx[EXCEPTIONS[ex]] = True
        elif ex == "user-tmp":
            sx.setdefault("allow_write", []).append(defaults.USER_TMP_TOKEN)
        elif ex.startswith("host:") and ex[5:]:
            sx.setdefault("allow_hosts", []).append(ex[5:])
        else:
            raise SystemExit(f"error: --exception {ex!r} (local-binding | weaker-network | user-tmp | host:<name>)")
        notes.append(f"sandbox exception {ex}")
    return raw, notes


def tail(path, n):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "\n".join(f.read().splitlines()[-n:])
    except OSError:
        return ""


def check(args):
    main = os.path.realpath(args.repo_root)
    name = args.name or os.path.basename(main)
    work = os.path.abspath(args.work)
    refuse_work(work)
    with open(args.config, "rb") as f:
        text = f.read().decode("utf-8")
    raw, notes = what_if(repoconfig.RepoConfig.from_text(text).raw, args.override, args.exception)
    checked = json.dumps(raw, ensure_ascii=False) if notes else text
    sha = gitops._plain_git(main, ["rev-parse", "--verify", args.rev + "^{commit}"])
    base_dir = os.path.join(work, name)
    home = os.path.realpath(os.path.join(base_dir, "engine"))
    out_dir = os.path.abspath(args.out)
    logs_dir = os.path.join(out_dir, "logs")
    os.makedirs(home, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)
    for stale in os.listdir(logs_dir):          # a report folder describes one run only
        if stale.endswith(".log"):
            os.unlink(os.path.join(logs_dir, stale))
    started = time.time()
    try:
        res = basecheck.check(basecheck.BaseCheckRequest(
            repo=REPO, checkout=main, sha=sha, config_text=checked, engine_home=home, plugin_root=PLUGIN_ROOT,
            environ=dict(os.environ, GLD_ENGINE_HOME=home), srt=os.path.abspath(args.srt), user_tmp=user_tmp(), force=True,
            out=sys.stdout), prepare_from=args.prepare_from)
        rec = store.read_record(pathsmod.EnginePaths(home, REPO, 1), res.record, "base-green")
        summary = summarise(name, args, sha, text, res, rec, notes, logs_dir, time.time() - started)
    finally:
        for sub in ("records", "tmp") if args.keep_cache else ("",):
            basecheck._force_rmtree(os.path.join(home, sub) if sub else base_dir)
    with open(os.path.join(out_dir, "base-check.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "base-check.md"), "w", encoding="utf-8") as f:
        f.write(render_md(summary))
    return summary


def summarise(name, args, sha, config_text, res, rec, notes, logs_dir, seconds):
    """The report of one check; copies the last run's log of every command into `logs_dir`."""
    results, base = [], res.record[:-len(".json")] + ".logs"
    cmds = json.loads(config_text)["commands"]
    for c in rec["commands"]:
        if not c["runs"]:
            results.append({"name": c["name"], "cmd": cmds.get(c["name"], {}).get("cmd", ""), "skipped": "not run (setup was red)"})
            continue
        last = c["runs"][-1]
        log = os.path.join(base, last["log_file"])
        if os.path.isfile(log):
            shutil.copyfile(log, os.path.join(logs_dir, c["name"] + ".log"))
        results.append({"name": c["name"], "cmd": cmds.get(c["name"], {}).get("cmd", ""), "rc": last["exit_code"],
                        "seconds": last["duration_s"], "timed_out": last["timed_out"], "dirty": c["dirty_files"], "ok": c["ok"],
                        "flaky": c["name"] in rec["flaky"], "tail": tail(log, TAIL_OK if c["ok"] else TAIL_FAIL)})
    return {"repo": name, "base": sha, "rev": args.rev, "srt": args.srt, "host": sys.platform, "seconds": round(seconds, 1),
            "config_sha256": basecheck.config_sha256(config_text), "what_if": bool(notes), "notes": notes, "ok": res.ok,
            "red": res.red, "problem": res.problem, "results": results}


def render_md(s):
    L = [f"# base-green check — {s['repo']} @ {s['base'][:12]}", "",
         f"- rev: `{s['rev']}`  host: {s['host']}  total: {s['seconds']} s", f"- srt: `{s['srt']}`",
         f"- config sha256: `{s.get('config_sha256', '?')}`" + (" (what-if: overrides / exceptions — see notes)" if s.get("what_if") else ""),
         "- policy: the engine's own base check (gxengine.basecheck: red twice on the same tree = red)"]
    if s.get("problem"):
        L.append(f"- **problem**: `{s['problem']}` — the check could not be carried out (refused like red)")
    L += ["", "| command | result | seconds | note |", "|---|---|---|---|"]
    for r in s["results"]:
        if "skipped" in r:
            L.append(f"| `{r['name']}` | skipped | | {r['skipped']} |")
            continue
        state = "timeout" if r["timed_out"] else ("**green**" if r["ok"] else f"**RED (rc={r['rc']})**")
        if r.get("dirty"):
            state += " + run-dirty-tree"
        L.append(f"| `{r['name']}` | {state} | {r['seconds']} | {'flaky: red, then green on the same tree' if r.get('flaky') else ''} |")
    for r in s["results"]:
        if "skipped" in r:
            continue
        L += ["", f"### `{r['name']}` — `{r['cmd'][:200]}`", ""]
        if r.get("dirty"):
            L += ["dirty tree after the run:", "```"] + r["dirty"] + ["```"]
        L += ["```", r["tail"], "```"]
    if s["notes"]:
        L += ["", "### notes", ""] + [f"- {n}" for n in s["notes"]]
    return "\n".join(L) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(prog="base_check.py", description=__doc__.split("\n")[0])
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--rev", required=True, help="the base revision")
    ap.add_argument("--config", required=True, help="the proposed settings (config.json)")
    ap.add_argument("--srt", required=True, help="path of the srt executable")
    ap.add_argument("--work", required=True, help="folder for the scratch engine home (not under /tmp)")
    ap.add_argument("--out", required=True, help="where base-check.md / .json / logs go")
    ap.add_argument("--name")
    ap.add_argument("--prepare-from", help="where worktree_prepare copies come from (default: --repo-root; only read)")
    ap.add_argument("--override", action="append", help="what-if: NAME=command text replacing one command (not written anywhere)")
    ap.add_argument("--exception", action="append", help="what-if sandbox exception: local-binding | weaker-network | user-tmp | host:<name>")
    ap.add_argument("--keep-cache", action="store_true", help="keep the Guild cache between runs (debugging)")
    args = ap.parse_args(argv)
    s = check(args)
    print(f"{s['repo']}: " + ("all green" if s["ok"] else (f"refused ({s['problem']})" if s["problem"] else "RED: " + ", ".join(s["red"]))))
    return 0 if s["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
