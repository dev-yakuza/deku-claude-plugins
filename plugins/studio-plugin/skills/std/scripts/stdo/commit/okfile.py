"""`.claude/studio/local/commit-ok.json` (m0e-plan §7.1) — the contract with the guard (M0d-2).
Written only by check_commit.py --stage; bound to the tree, HEAD, the Studio paths, the videos' state
seqs and the Claude Code session. The question label is "커밋 <tree12>"."""

import datetime
import json
import os

from .. import paths as _paths, writes

SCHEMA = 1
REL = os.path.join(".claude", "studio", "local", "commit-ok.json")
LABEL = "커밋 %s"
FIELDS = ("schema", "tree", "head", "kind", "target", "studio_root", "paths", "states", "session_id", "label",
          "summary", "protected_changes", "in_progress", "scripts_version", "approval", "written_at",
          # M1c (m1-plan §5.1): the value block — settings (the hook recomputes them), machine (first install), the
          # lines the question must show, and the overflow file {file, sha12, reason} or null
          "values_settings", "values_machine", "values_shown", "overflow", "warnings")


def path(top):
    return os.path.join(top, REL)


def read(top):
    """(dict, None) or (None, reason)."""
    try:
        raw = _paths.read_local(top, "commit-ok.json")
    except _paths.UnsafeLocal as e:
        return None, "not readable safely (%s)" % e
    except OSError as e:
        return None, "unreadable (%s)" % e
    if raw is None:
        return None, "missing"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return None, "unreadable (%s)" % e
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("tree"), str) or \
            not isinstance(data.get("paths"), list):
        return None, "malformed"
    return data, None


def _check(top):
    why = _paths.local_problem(top)
    if why:
        raise OSError(why)


def write(top, data):
    writes.check("commit-ok.json")
    data = dict(data)
    data["schema"] = SCHEMA
    data["label"] = LABEL % data["tree"][:12]
    data.setdefault("approval", None)
    data["written_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _check(top)
    p = path(top)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: data.get(k) for k in FIELDS}, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    _check(top)  # written through a folder swapped meanwhile: say so (closed)
    return data


VIDEO_RECORD = "commit-ok.json"  # <sr>/videos/<video>/work/commit-ok.json (P-STATE, M1b review Y3)


def video_record_path(top, studio_root, video):
    return os.path.join(top, studio_root, "videos", video, "work", VIDEO_RECORD)


def keep_for_video(top, studio_root, ok):
    """The hook passed a video commit with the person's answer: keep that commit-ok in the video's own folder, so
    `state.py done` still finds it after later commits overwrite commit-ok.json (M1b review Y3). Returns the path or
    None (not a video commit)."""
    writes.check("a video's commit record")
    target = ok.get("target") if isinstance(ok, dict) else None
    ap = ok.get("approval") if isinstance(ok, dict) else None
    if ok.get("kind") != "video" or not isinstance(target, str) or not target or "/" in target or \
            target in (".", "..") or not isinstance(ap, dict) or ap.get("mode") != "human":
        return None
    p = video_record_path(top, studio_root, target)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: ok.get(k) for k in FIELDS}, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return p


def read_video_record(top, studio_root, video):
    try:
        with open(video_record_path(top, studio_root, video), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA else None


def set_approval(top, approval):
    """The guard records the answer it checked (m0d2-plan §5.5-6, M0e Q12): every other field is kept as read."""
    data, why = read(top)
    if data is None:
        raise OSError("commit-ok.json is %s" % why)
    data["approval"] = approval
    _check(top)
    p = path(top)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: data.get(k) for k in FIELDS}, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    _check(top)  # written through a folder swapped meanwhile: say so (closed)
    return data
