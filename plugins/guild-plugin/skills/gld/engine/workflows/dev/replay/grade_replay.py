#!/usr/bin/env python3
"""replay.grade_replay — the §9.5 grader over a corpus of decisions with an answer key (K6 items 11 + 22).

    grade_replay.py --corpus <json> --judge fake|ollama|claude [--model qwen3.8:27b] [--base http://127.0.0.1:11434]
                    --out <dir>

* corpus: [{id, group, block{…decision block fields}, issue_text, ac, brief, evidence, untrusted,
  expect{given_info, blind}}] — the same `grader.grade` the live `dev grade --grader` runs (two calls, citation
  checks, suppression rules, flags), with the original brief's evidence and the AC (§10.2-6 "정답성 표본" shape);
* `--judge fake`: a deterministic grader that answers the key with a verbatim citation — the harness and the
  engine-side rules only (settle/demotion/flags), no model;
* `--judge ollama`: the local model through Ollama's chat API with the grader's JSON schema (`format`), the
  grader's own system prompt and brief — the PROMPTS and rules against a real (weak, local) model; never Claude,
  never paid. It does NOT measure the opus grader's quality (§10.2-6 / item 22 — a paid run);
* `--judge claude` (K6 item 22 — the paid run): the grader's own `JudgeRunner` (`claude -p`, the grader's tier, opus by
  default) — the live `dev grade --grader` call path. It refuses to run without an explicit `CLAUDE_CONFIG_DIR` (an
  isolated config dir, never the default `~/.claude`); each decision's `cost_usd` and the total go to the report;
* report: per decision (blind choice, raw / settled given_info, demotion, expected) and totals — settled agreement
  with the key, raw agreement, demotion rate, `ok`→`unsure` suppressions, seconds and tokens per call.
"""

import argparse
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from guildcore.judges.runner import Decision, assemble        # noqa: E402
from guildcore.records.decisions import DecisionBlock           # noqa: E402
from workflows.dev import grader as GD                          # noqa: E402


def fake_judge(item):
    """Answers the key: blind = expect.blind, reveal = expect.given_info with the first evidence line cited."""
    ev_line = next((ln.strip() for ln in (item.get("evidence") or "").split("\n") if len(ln.strip()) > 20), "")

    def judge(spec):
        if spec.choice_key == "choice":
            return Decision(item["expect"]["blind"], {"choice": item["expect"]["blind"], "reason": "key",
                                                      "cited_evidence": [ev_line] if ev_line else []},
                            "judge:fake", "f1")
        gi = item["expect"]["given_info"]
        return Decision(gi, {"given_info": gi, "outcome": "consistent" if gi == "ok" else "inconsistent",
                             "reason": "key", "cited_evidence": [ev_line] if ev_line else []}, "judge:fake", "f2")
    return judge


class Ollama(object):
    def __init__(self, base, model, log):
        self.base, self.model, self.log = base.rstrip("/"), model, log
        self.calls = []

    def __call__(self, spec):
        system = "\n\n".join(spec.system_parts)
        brief = assemble(spec.brief_parts, spec.cap_chars, spec.no_elide)
        # the local mlx runner has no structured output (`format` → 501): the schema rides in the prompt and the
        # first JSON object of the answer is taken — the engine's own checks (settle) run on it as on any output
        body = {"model": self.model, "stream": False, "think": False,
                "options": {"temperature": 0, "num_ctx": 16384},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": brief + "\n\nAnswer with ONE JSON object only, matching "
                              "this JSON schema:\n" + json.dumps(spec.schema)}]}
        t0 = time.time()
        req = urllib.request.Request(self.base + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1800) as r:
            out = json.loads(r.read().decode("utf-8"))
        dt = time.time() - t0
        txt = (out.get("message") or {}).get("content") or "{}"
        fields = first_json(txt)
        self.calls.append({"point": spec.point, "seconds": round(dt, 1), "prompt_tokens": out.get("prompt_eval_count"),
                           "output_tokens": out.get("eval_count"), "valid_json": bool(fields)})
        with open(self.log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"point": spec.point, "seconds": round(dt, 1), "content": txt[:4000]},
                                ensure_ascii=False) + "\n")
        ch = fields.get(spec.choice_key)
        return Decision(ch, fields, "judge:%s" % self.model, "o%d" % len(self.calls))


def first_json(txt):
    """The first top-level JSON object in a model's text (fenced or not) — {} when none parses."""
    t = str(txt or "")
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch == "{":
            try:
                obj, _end = dec.raw_decode(t[i:])
                if isinstance(obj, dict):
                    return obj
            except ValueError:
                continue
    return {}


def block_of(item, n):
    return DecisionBlock(n, list((item.get("block") or {}).items()))


class Claude(object):
    """K6 item 22: the real grader call — `JudgeRunner.judge` (claude -p), cost per decision summed by the caller."""

    def __init__(self, out_dir, runner=None):
        from guildcore.judges.runner import JudgeRunner
        self.runner = runner or JudgeRunner(parent_env=dict(os.environ), run_root_dir=os.path.join(out_dir, "runs"))
        self.cost = 0.0

    def __call__(self, spec):
        d = self.runner.judge(spec)
        self.cost += float(getattr(d, "cost", 0) or 0)
        return d


def run(corpus, judge_kind, out_dir, base=None, model=None, runner=None):
    os.makedirs(out_dir, exist_ok=True)  # fs-ok: report dir chosen by the caller
    log = os.path.join(out_dir, "grade_replay_calls.jsonl")
    if os.path.exists(log):
        os.remove(log)  # fs-ok: our own call log in the caller's report dir
    oll = Ollama(base, model, log) if judge_kind == "ollama" else None
    cl = Claude(out_dir, runner) if judge_kind == "claude" else None
    rows = []
    for n, item in enumerate(corpus, 1):
        judge = oll if oll is not None else (cl if cl is not None else fake_judge(item))
        c0 = cl.cost if cl is not None else 0.0
        t0 = time.time()
        try:
            row = GD.grade(judge, block_of(item, n), int(item.get("issue") or 900 + n), item["group"],
                           item.get("evidence") or "", tier="opus", issue_text=item.get("issue_text") or "",
                           gv="replay", untrusted=item.get("untrusted") or "", brief=item.get("brief"),
                           ac=item.get("ac") or "")
            err = None
        except Exception as e:                                   # noqa: BLE001 — a model's broken output is data
            row, err = {}, "%s: %s" % (e.__class__.__name__, str(e)[:200])
        exp = item["expect"]
        rows.append({"id": item["id"], "group": item["group"], "expected": exp["given_info"],
                     "expected_blind": exp["blind"], "blind_choice": row.get("blind_choice"),
                     "blind_agrees": GD.same_choice(item["group"], row.get("blind_choice") or "", exp["blind"])
                     if row else False,
                     "raw_given_info": row.get("raw_given_info"), "given_info": row.get("given_info"),
                     "demoted": row.get("demoted"), "flagged": row.get("flagged"), "error": err,
                     "seconds": round(time.time() - t0, 1)})
        if cl is not None:
            rows[-1]["cost_usd"] = round(cl.cost - c0, 4)
    n = float(len(rows)) or 1.0
    tot = {"decisions": len(rows), "judge": judge_kind if not oll else "ollama:%s" % model,
           "settled_agreement": sum(1 for r in rows if r["given_info"] == r["expected"]) / n,
           "raw_agreement": sum(1 for r in rows if r["raw_given_info"] == r["expected"]) / n,
           "blind_agreement": sum(1 for r in rows if r["blind_agrees"]) / n,
           "demoted": sum(1 for r in rows if r["demoted"]) / n,
           "wrong_caught": "%d/%d" % (sum(1 for r in rows if r["expected"] == "wrong" and r["given_info"] == "wrong"),
                                      sum(1 for r in rows if r["expected"] == "wrong")),
           "wrong_flagged": "%d/%d" % (sum(1 for r in rows if r["expected"] == "wrong" and r["flagged"]),
                                       sum(1 for r in rows if r["expected"] == "wrong")),
           "ok_called_wrong": sum(1 for r in rows if r["expected"] == "ok" and r["given_info"] == "wrong"),
           "errors": sum(1 for r in rows if r["error"])}
    if oll is not None:
        c = oll.calls
        tot["calls"] = len(c)
        tot["seconds_per_call"] = round(sum(x["seconds"] for x in c) / (len(c) or 1), 1)
        tot["prompt_tokens_per_decision"] = int(sum(x["prompt_tokens"] or 0 for x in c) / n)
        tot["output_tokens_per_decision"] = int(sum(x["output_tokens"] or 0 for x in c) / n)
        tot["valid_json"] = "%d/%d" % (sum(1 for x in c if x["valid_json"]), len(c))
    if cl is not None:
        tot["cost_usd"] = round(cl.cost, 4)
        tot["cost_per_decision"] = round(cl.cost / n, 4)
    rep = {"totals": tot, "rows": rows}
    with open(os.path.join(out_dir, "grade_replay_%s.json" % judge_kind), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, ensure_ascii=False)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--judge", choices=("fake", "ollama", "claude"), default="fake")
    ap.add_argument("--model", default="qwen3.8:27b")
    ap.add_argument("--base", default="http://127.0.0.1:11434")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.judge == "ollama" and not a.base.startswith(("http://127.0.0.1", "http://localhost")):
        print("refusing a non-local model endpoint", file=sys.stderr)
        return 64
    if a.judge == "claude" and not os.environ.get("CLAUDE_CONFIG_DIR"):
        print("refusing --judge claude without an explicit (isolated) CLAUDE_CONFIG_DIR", file=sys.stderr)
        return 64
    with open(a.corpus, encoding="utf-8") as fh:
        corpus = json.load(fh)
    rep = run(corpus, a.judge, a.out, a.base, a.model)
    print(json.dumps(rep["totals"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
