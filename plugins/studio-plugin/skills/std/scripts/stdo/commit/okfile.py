"""`.claude/studio/local/commit-ok.json` (m0e-plan §7.1) — the contract with the guard (M0d-2).
Written only by check_commit.py --stage; bound to the tree, HEAD, the Studio paths, the videos' state
seqs and the Claude Code session. The question label is "커밋 <tree12>"."""

import datetime
import json
import os

SCHEMA = 1
REL = os.path.join(".claude", "studio", "local", "commit-ok.json")
LABEL = "커밋 %s"
FIELDS = ("schema", "tree", "head", "kind", "target", "studio_root", "paths", "states", "session_id", "label",
          "in_progress", "scripts_version", "approval", "written_at")


def path(top):
    return os.path.join(top, REL)


def read(top):
    """(dict, None) or (None, reason)."""
    try:
        with open(path(top), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError) as e:
        return None, "unreadable (%s)" % e
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("tree"), str) or \
            not isinstance(data.get("paths"), list):
        return None, "malformed"
    return data, None


def write(top, data):
    data = dict(data)
    data["schema"] = SCHEMA
    data["label"] = LABEL % data["tree"][:12]
    data.setdefault("approval", None)
    data["written_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    p = path(top)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: data.get(k) for k in FIELDS}, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return data
