#!/usr/bin/env python3
"""replay.label_audit — the blind-label sample audit over the replay corpus (K6 items 29 + 1).

A blind question shows each option's own summary with its evaluative clauses cut (`predict.neutral_label`); a label
that still rates refuses the blind answer (`predict_first_refused` — the answer is then never a §9.5 judgment). Two
failure directions, measured offline:

* FALSE REFUSAL — a descriptive summary read as a rating (the blind answer lost for nothing). Corpus: the real
  descriptive one-liners of word_app's legacy sprint logs (acceptance criteria `AC #n: …` — the closest the logs have
  to the summaries a KICKOFF judge writes for its interpretations: what is built, never how good it is);
* LEAK — an evaluative label that passes uncut. Corpus: the review paraphrases (r7 16, r10 m5 16 — fit / faithfulness
  language) and their mirror descriptive set (r8 9 + r10 m5 descriptive 12).

    label_audit.py --logs '<glob>' --out <dir> [--sample 400] [--heldout <set.json> …]

K6 r1 M4: the paraphrase lists above are the CALIBRATION set (FIT was tuned on them — a 0/32 there is by
construction). The leak is measured on HELD-OUT sets (`--heldout`): written by another model (local qwen, sealed by
sha256 before the measurement, never read to tune a word list), each label paired with its neighbour and shown
through `predict.blind_labels` exactly as a blind question shows two options. A label shown unchanged is a leak.

Output: rates over the corpus, every flagged descriptive line (for the person to confirm as a false refusal or a real
rating), the leak list. No model; the logs are only read.
"""

import argparse
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from workflows.dev import predict as PF                         # noqa: E402

AC_RE = re.compile(r'AC ?#?[0-9]+[:：.] ([^"\\|]{8,140})')

# review-k5-r7 m2 (16, cut since r9) + review-k5-r10 m5 (16 new paraphrases that leaked)
EVALUATIVE = (
    "앱 전체 (제목 그대로 해석)", "앱 전체 — 요청 그대로의 범위", "앱 전체 (요청 그대로 구현)", "ログイン画面のみ（タイトル通りに解釈）",
    "アプリ全体（本文通りに読む）", "Whole app (taking the title literally)", "Whole app (matches the title text)",
    "Login only (the title's literal sense)", "Login only (literal scope)", "Whole app (typical scope)",
    "Whole app (the typical case)", "로그인만 (근거가 약해 보임)", "로그인만 (근거: 제목)", "Whole app (follows the title text)",
    "ログインのみ（根拠：タイトル）", "Whole app (read the title literally)",
    # r10 m5
    "로그인만 (제목 그대로 반영)", "앱 전체 (이슈 설명에 충실한 해석)", "앱 전체 (제목에서 벗어난 해석)", "앱 전체 (요청을 확대 해석)",
    "로그인만 (본문 내용과 상통)", "로그인만 (제목의 취지에 부합하는 범위)", "ログインのみ（タイトルを文字通り解釈）",
    "ログインのみ（タイトルに忠実な解釈）", "アプリ全体（依頼内容からは外れる）", "アプリ全体（説明と食い違う）",
    "Login only (aligns with the title)", "Login only (faithful to the request)", "Whole app (goes beyond the request)",
    "Login only (strict reading of the title)", "Login only (literal take on the title)",
    "Whole app (departs from the description)",
)
DESCRIPTIVE = (
    "로그인 화면에 제목 그대로 표시", "본문 그대로 표시", "タイトル通りに表示", "Literal string search", "Match title case",
    "근거 자료 링크 추가", "Read the title field literally from the API", "Typical value range 0–100",
    "Title text follows the design", "제목 그대로 표시하고 줄임표 처리", "요청 본문을 그대로 서버에 전달", "タイトル文字列をそのまま保存",
)


def corpus(logs, sample):
    seen = set()
    for p in sorted(logs):
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                t = fh.read()
        except OSError:
            continue
        for m in AC_RE.finditer(t):
            s = " ".join(m.group(1).split()).strip(" -—*`")
            if 8 <= len(s) <= 140 and s not in seen:
                seen.add(s)
    lines = sorted(seen, key=lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest())   # deterministic sample
    return lines[:sample] if sample else lines


def judge_line(s):
    nl = PF.neutral_label(s)
    return {"text": s, "rates": PF.rates(s), "shown": nl, "refused": nl is None, "cut": nl not in (None, s)}


def run(logs, out_dir, sample=400):
    desc = [judge_line(s) for s in corpus(logs, sample)]
    ev = [judge_line(s) for s in EVALUATIVE]
    dd = [judge_line(s) for s in DESCRIPTIVE]
    n = float(len(desc)) or 1.0
    rep = {"corpus": {"source": "word_app legacy sprint/batch logs — acceptance-criteria lines", "lines": len(desc)},
           "descriptive_corpus": {"flagged_rates": sum(1 for x in desc if x["rates"]) / n,
                                  "refused": sum(1 for x in desc if x["refused"]) / n,
                                  "cut": sum(1 for x in desc if x["cut"]) / n},
           "evaluative_paraphrases": {"n": len(ev), "leaked": [x["text"] for x in ev if not x["rates"]]},
           "descriptive_mirror": {"n": len(dd), "false_refusals": [x["text"] for x in dd if x["refused"] or x["cut"]]},
           "flagged_descriptive_lines": [x for x in desc if x["rates"]]}
    os.makedirs(out_dir, exist_ok=True)  # fs-ok: report dir chosen by the caller
    with open(os.path.join(out_dir, "label_audit.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, ensure_ascii=False)
    return rep


def heldout(path):
    """{kind: {n, unchanged, cut, refused}, "leaked": [...]} — `path` = {"sets": {lang: {"evaluative": [...],
    "descriptive": [...]}}}; labels paired (i, i+1) per language through `predict.blind_labels`."""
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    d = json.loads(raw)
    out = {"file": os.path.basename(path), "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
           "generator": d.get("generator"), "leaked": [], "descriptive_changed": []}
    for kind in ("evaluative", "descriptive"):
        t = {"n": 0, "unchanged": 0, "cut": 0, "refused": 0}
        for lang, v in sorted((d.get("sets") or {}).items()):
            labels = list(v.get(kind) or [])
            for i in range(0, len(labels) - 1, 2):
                pair = labels[i:i + 2]
                for s0, shown in zip(pair, PF.blind_labels(pair)):
                    t["n"] += 1
                    k = "refused" if shown is None else "unchanged" if shown == s0 else "cut"
                    t[k] += 1
                    if kind == "evaluative" and k == "unchanged":
                        out["leaked"].append(s0)
                    if kind == "descriptive" and k != "unchanged":
                        out["descriptive_changed"].append([s0, shown])
        out[kind] = t
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample", type=int, default=400)
    ap.add_argument("--heldout", action="append", default=[])
    a = ap.parse_args(argv)
    rep = run(glob.glob(a.logs, recursive=True), a.out, a.sample)
    if a.heldout:
        rep["heldout"] = [heldout(h) for h in a.heldout]
        with open(os.path.join(a.out, "label_audit.json"), "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=1, ensure_ascii=False)
        for h in rep["heldout"]:
            print("held-out %s: evaluative %s · descriptive %s" % (h["file"], h["evaluative"], h["descriptive"]))
    print(json.dumps(dict((k, v) for k, v in rep.items() if k != "flagged_descriptive_lines"), ensure_ascii=False)[:1500])
    print("flagged descriptive:", len(rep["flagged_descriptive_lines"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
