#!/usr/bin/env python3
"""Integrity entry (plan §3.2.2). `--record --topic T [--sha S]` writes the ledger after its
self-check; `--predeploy` runs step 7 (a)+(b); default runs the step 2 comparison."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hrdlib import integrity, store  # noqa: E402
from hrdlib.config import Config  # noqa: E402
from hrdlib.util import HeraldError, emit, repo_root  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--record", action="store_true")
ap.add_argument("--topic")
ap.add_argument("--sha")
ap.add_argument("--rev")
ap.add_argument("--kind", default="verify")
ap.add_argument("--predeploy", action="store_true")
a = ap.parse_args()
try:
    root = repo_root()
    cfg = Config.load(root)
    if a.record:
        emit(store.ledger_record(root, cfg, a.topic, sha=a.sha, kind=a.kind, rev=a.rev))
        sys.exit(0)
    rep = integrity.predeploy(root, cfg) if a.predeploy else integrity.check(root, cfg, rev=a.rev)
    emit(rep)
    sys.exit(0 if rep["ok"] else 1)
except HeraldError as e:
    sys.stderr.write("integrity: %s\n" % e)
    sys.exit(1)
