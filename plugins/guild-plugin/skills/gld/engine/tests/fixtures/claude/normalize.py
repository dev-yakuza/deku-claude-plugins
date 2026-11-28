#!/usr/bin/env -S python3 -I
"""Copy recorded stream-json into fixtures, normalised for a public repository.

    python3 -I normalize.py --src <dir of *.jsonl> --dst <fixture dir> \
        --replace <recorded experiment root>=/tmp/gx-exp --replace <home>=/Users/user

For every string in every event:
  - each `--replace OLD=NEW` (applied longest OLD first);
  - every `NAME=value` line (an `env` dump) becomes `NAME=<redacted>` — variable names stay,
    values never land in the repo (one recording carried a session messaging token).
Events, their order and every other field are kept, so the fixture replays like the
original. Re-record when the CLI version changes (scope §6.2) and run this again.
"""

import argparse
import json
import os
import re
import sys

ENV_LINE = re.compile(r"(?m)^([A-Za-z_][A-Za-z0-9_]*)=.*$")


def _walk(x, fn):
    if isinstance(x, str):
        return fn(x)
    if isinstance(x, list):
        return [_walk(v, fn) for v in x]
    if isinstance(x, dict):
        return {k: _walk(v, fn) for k, v in x.items()}
    return x


def normalise_text(s, replacements):
    for old, new in replacements:
        s = s.replace(old, new)
    return ENV_LINE.sub(lambda m: f"{m.group(1)}=<redacted>", s)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--replace", action="append", default=[], help="OLD=NEW")
    args = ap.parse_args(argv)
    reps = sorted((tuple(r.split("=", 1)) for r in args.replace), key=lambda p: -len(p[0]))
    os.makedirs(args.dst, exist_ok=True)
    for name in sorted(os.listdir(args.src)):
        if not name.endswith(".jsonl"):
            continue
        out = []
        with open(os.path.join(args.src, name), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    out.append(json.dumps(_walk(json.loads(line), lambda s: normalise_text(s, reps)), ensure_ascii=False))
        with open(os.path.join(args.dst, name), "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        print(f"{name}: {len(out)} events")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
