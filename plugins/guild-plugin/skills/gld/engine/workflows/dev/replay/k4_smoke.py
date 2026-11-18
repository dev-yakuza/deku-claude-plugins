#!/usr/bin/env python3
"""replay.k4_smoke — ONE local-model smoke of the K4 analyze stage through the REAL role and judge runners
(`claude -p`, CLI settings render, sandbox) against the local Ollama model — never a paid endpoint.

The Issue lives in the fake GitHub (no GitHub call); the repository is a throwaway clone of word_app made
by `replay.calibrate.prepare` (isolated CLAUDE_CONFIG_DIR, loopback endpoint through `replay.proxy`
forward mode, HTTPS_PROXY to a dead port). What it checks (plumbing, not judgment quality):
the explorer-kickoff prompt renders and the explorer's `out/evidence.json` comes back through `roleout`;
the KICKOFF schema is accepted by `--json-schema` and re-validated; the code coercions run; the stage
posts analyze:output and moves the label (or pauses with a cause line).

    k4_smoke.py --work DIR --repo ~/projects/word_app --out EVIDENCE_DIR
"""

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from guildcore import config as CF                            # noqa: E402
from guildcore.adapters.gh import FakeGh, FakeGhWrite         # noqa: E402
from guildcore.decisions import DecisionWriter                # noqa: E402
from guildcore.judges import runner as JR                     # noqa: E402
from guildcore.records.write import GhWriter                  # noqa: E402
from workflows.dev import ports as PO                         # noqa: E402
from workflows.dev.replay import proxy as PX                  # noqa: E402
from workflows.dev.replay import smoke as SM                  # noqa: E402
from workflows.dev.stages import analyze as A                 # noqa: E402
from workflows.dev.stages import base as B                    # noqa: E402

ISSUE = 9001
BODY = ("단어 목록 화면 상단에 현재 목록의 단어 수를 표시한다.\n\n"
        "- 사용자가 목록을 필터링하면 표시되는 수도 함께 바뀐다.\n- 오프라인에서도 동작해야 한다.\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ctx = SM.Ctx(a.work, a.repo, a.out)
    os.makedirs(a.out, exist_ok=True)
    srv, url = PX.serve_background(logdir=os.path.join(a.out, "proxy"), mode="forward", upstream=SM.OLLAMA)
    runs = os.path.join(a.out, "runs")
    runner = SM._runner(ctx, url, runs)
    jr = JR.JudgeRunner(parent_env=ctx.parent_env(url), allow_local=True, run_root_dir=os.path.join(a.out, "judges"),
                        user_settings=ctx.user_settings, claude=shutil.which("claude"))
    cfg = CF.load(ctx.clone)
    fx = {"repo": "o/r", "issues": {str(ISSUE): {"number": ISSUE, "title": "단어 목록에 단어 수 표시", "body": BODY,
                                                 "state": "OPEN", "author_association": "OWNER",
                                                 "labels": [], "comments": [], "timeline": []}}, "prs": []}
    gh = FakeGh(fx)

    class Clock(object):
        def now(self):
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    clock = Clock()
    w = FakeGhWrite(gh, clock)
    writer = GhWriter(gh, w, sleep=lambda s: None)
    calls = {"roles": [], "judges": []}

    def run_role(call):
        spec = PO.role_spec(call, ISSUE, ctx.clone, cfg, base="HEAD", unattended=True)
        spec.model = SM.QWEN
        spec.timeout_s, spec.budget_usd = 600, 100.0           # run 1: the explorer hit 1800 s on qwen — partial path
        t0 = time.time()
        r = runner.run_role(spec)
        calls["roles"].append({"role": call.role, "task": call.task, "status": r.status, "line": r.line,
                               "secs": round(time.time() - t0, 1), "extras": r.extras, "run_dir": r.run_dir})
        return r

    def judge(spec):
        tier = spec.model
        spec.model, spec.budget_usd = SM.QWEN, 100.0
        t0 = time.time()
        try:
            d = jr.judge(spec)
        except Exception as e:                                    # noqa: BLE001 — the evidence records it
            calls["judges"].append({"group": spec.group, "error": "%s: %s" % (type(e).__name__, e),
                                    "secs": round(time.time() - t0, 1)})
            raise
        d.by = "judge:%s" % tier            # run 1: `judge:qwen3.8:27b` is not a §2.5 `by:` tier — record the tier it stands in for
        calls["judges"].append({"group": spec.group, "model": SM.QWEN, "choice": d.choice, "unsure": d.unsure, "coerced": d.coerced,
                                "secs": round(time.time() - t0, 1), "fields": d.fields})
        return d
    p = B.Ports(ISSUE, gh, writer, DecisionWriter(writer, ISSUE, clock), clock, cfg, ctx.clone, unattended=True,
                run_role=run_role, judge=judge)
    p.spec_store = os.path.join(a.out, "specs")
    t0 = time.time()
    err = None
    try:
        r = A.run(p)
        token = r.token()
    except Exception as e:                                        # noqa: BLE001
        token, err = None, "%s: %s" % (type(e).__name__, e)
    finally:
        srv.shutdown()
    it = fx["issues"][str(ISSUE)]
    res = {"secs": round(time.time() - t0, 1), "token": token, "error": err,
           "labels": sorted(l["name"] for l in it["labels"]), "calls": calls,
           "comments": [c["body"] for c in it["comments"]]}
    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as fh:  # fs-ok: evidence output (replay)
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    print(json.dumps({k: res[k] for k in ("secs", "token", "error", "labels")}, ensure_ascii=False))
    print(json.dumps([{k: v for k, v in c.items() if k not in ("fields", "extras")} for c in calls["roles"] + calls["judges"]],
                     ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
