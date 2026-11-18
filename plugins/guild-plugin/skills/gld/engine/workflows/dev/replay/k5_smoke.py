"""replay.k5_smoke — the K5 call path end to end on a throwaway clone, against the LOCAL model only.

It launches `gld_engine.py dev run --issue N --unattended [--only STAGE]` as a separate process exactly the way the
sprint supervisor does (same env guards, GLD_SUPERVISOR_VERSION, cwd = the clone), with:
* the repository = a throwaway clone of word_app (`replay.calibrate.prepare` — `git clone file://`, never the
  real checkout), an isolated CLAUDE_CONFIG_DIR with this plugin installed from the engine worktree (so the
  §10.3 active-version check passes for real), a fake HOME and a dead HTTPS proxy;
* the model = Ollama qwen through `replay.proxy` forward mode with every tier name rewritten to qwen, the proxy
  listed in the clone's `config.engine.allowed_endpoints` (the production path for a local endpoint);
* GitHub = a FILE-backed fake (`GLD_ENGINE_TEST=1` + `GLD_ENGINE_GH_FIXTURE`) — no `gh`, no network.
It records the process's stdout (the §2.4 contract), exit code, the fake GitHub after the run, the progress
side file and the role/judge stream logs. Claims: plumbing only (CLI → preflight → lock → restart check →
FSM → stage → verified writes → stdout events), not judgment quality. No paid call, no GitHub write.

    k5_smoke.py --work DIR --repo ~/projects/word_app --out EVIDENCE_DIR [--stages analyze,design] [--timeout S]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from workflows.dev.replay import calibrate as CA              # noqa: E402
from workflows.dev.replay import proxy as PX                  # noqa: E402

OLLAMA = "http://127.0.0.1:11434"
QWEN = "qwen3.8:27b"
ISSUE = 9001
BODY = ("단어 목록 화면 상단에 현재 목록의 단어 수를 표시한다.\n\n"
        "- 사용자가 목록을 필터링하면 표시되는 수도 함께 바뀐다.\n- 오프라인에서도 동작해야 한다.\n")


def install_plugin(cfg, env):
    """This worktree's plugin into the isolated config dir (local marketplace — no network)."""
    repo = os.path.abspath(os.path.join(ENGINE, "..", "..", "..", "..", ".."))
    e = dict(env, CLAUDE_CONFIG_DIR=cfg, HOME=env["HOME"])
    claude = shutil.which("claude")
    out = []
    for argv in ([claude, "plugin", "marketplace", "add", repo], [claude, "plugin", "install",
                                                                  "guild-plugin@deku-claude-plugins", "--scope", "user"]):
        p = subprocess.run(argv, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        out.append(p.stdout.decode("utf-8", "replace")[-300:])
    p = subprocess.run([claude, "plugin", "list", "--json"], env=e, stdout=subprocess.PIPE, timeout=60)
    return out, json.loads(p.stdout.decode() or "[]")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stages", default="analyze")
    ap.add_argument("--timeout", type=int, default=5400)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    dirs = CA.prepare(a.work, a.repo)
    clone = dirs["clone"]
    srv, url = PX.serve_background(logdir=os.path.join(a.out, "proxy"), mode="forward", upstream=OLLAMA,
                                   model_override=QWEN)
    env = CA.base_env(dirs, url)
    env["PATH"] = os.pathsep.join([os.path.dirname(shutil.which("claude")), os.path.dirname(sys.executable),
                                   "/usr/bin", "/bin", "/usr/sbin", "/sbin", "/opt/homebrew/bin"])
    inst, plist = install_plugin(dirs["cfg"], env)
    # the clone's Guild config: the local endpoint allowed (the production path for an offload endpoint)
    cfgp = os.path.join(clone, ".claude", "guild", "config.json")
    with open(cfgp, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg.setdefault("engine", {})["allowed_endpoints"] = [url]
    with open(cfgp, "w", encoding="utf-8") as fh:  # fs-ok: the throwaway clone's config (smoke setup)
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    fxp = os.path.join(a.out, "github.json")
    fx = {"repo": "o/r", "viewer": "guild-bot", "issues": {str(ISSUE): {
        "number": ISSUE, "title": "단어 목록에 단어 수 표시", "body": BODY, "state": "OPEN",
        "author_association": "OWNER", "user": {"login": "owner"}, "labels": [], "comments": [], "timeline": [],
        "url": "https://github.com/o/r/issues/%d" % ISSUE}}, "prs": []}
    with open(fxp, "w", encoding="utf-8") as fh:  # fs-ok: evidence dir (smoke)
        json.dump(fx, fh, ensure_ascii=False, indent=1)
    from guildcore.version import own_version
    run_env = dict(env, GLD_ENGINE_TEST="1", GLD_ENGINE_GH_FIXTURE=fxp, GLD_UNATTENDED="1",
                   GLD_SUPERVISOR_VERSION=own_version() or "", CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0",
                   CLAUDE_CODE_DISABLE_BACKGROUND_TASKS="1", BASH_DEFAULT_TIMEOUT_MS="600000",
                   BASH_MAX_TIMEOUT_MS="3600000")
    runs = []
    try:
        for stage in [x for x in a.stages.split(",") if x]:
            t0 = time.time()
            argv = [sys.executable, os.path.join(ENGINE, "gld_engine.py"), "dev", "run", "--issue", str(ISSUE),
                    "--unattended", "--only", stage]
            try:
                p = subprocess.run(argv, cwd=clone, env=run_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=a.timeout)
                rc, so, se = p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
            except subprocess.TimeoutExpired as ex:
                rc, so, se = "timeout", (ex.stdout or b"").decode("utf-8", "replace"), ""
            with open(fxp, encoding="utf-8") as fh:
                it = json.load(fh)["issues"][str(ISSUE)]
            runs.append({"stage": stage, "secs": round(time.time() - t0, 1), "exit": rc,
                         "stdout_lines": [ln for ln in so.split("\n") if ln.strip()], "stderr_tail": se[-600:],
                         "labels": sorted(lb["name"] if isinstance(lb, dict) else lb for lb in it.get("labels", [])),
                         "comments": [c["body"].split("\n")[0] for c in it.get("comments", [])]})
            print(json.dumps({k: runs[-1][k] for k in ("stage", "secs", "exit", "labels")}, ensure_ascii=False))
            if rc != 0:
                break
    finally:
        srv.shutdown()
    from guildcore.adapters import git as G
    common = G.run(clone, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False).decode().strip()
    prog = os.path.join(common, "guild", "engine", str(ISSUE), "progress.log")
    res = {"install": inst, "plugin_list": plist, "proxy": url, "runs": runs,
           "progress": open(prog, encoding="utf-8").read() if os.path.exists(prog) else None}
    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as fh:  # fs-ok: evidence output (smoke)
        json.dump(res, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
