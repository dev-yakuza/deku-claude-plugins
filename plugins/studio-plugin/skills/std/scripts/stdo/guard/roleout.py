"""0.0.28 §1.2 (fix-0028-plan, pilot-3 Q1): a Studio role's Write/Edit of its own output files gets no prompt (kind
`work`). Data and matching here; judge.decide_file adds the candidate and judge.finish answers through allow_for.

Every condition is a "no allow" condition (the normal prompt), never a deny. Only a subagent (`agent_id` set) whose
`agent_type` is exactly a name below, only in the `default` permission mode (as §1.1), only Write, Edit or MultiEdit,
only a path reached without links. The fact-checker, the auditor and the other roles have no row: their verdict files
keep the prompt, so a forged verify.draft.json is never silent. A role can still write wrong content into its own
file, and the main session can start a role with any instructions (stated in docs/guard-limits.md); the gates and the
checks judge content, as before."""

import json
import os
import re
import stat

from .scriptrun import VIDEO_ID, _inside, _no_link_below, _read, _real_dir

LANG = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]+)?$")
TOOLS = ("Write", "Edit", "MultiEdit")
# agent_type → the files it owns, relative to <repo>/<studio_root>/. `videos/<v>/…` means the video's folder wherever
# store.video_dir finds it (public or local); `copy/<v>/…` stays under <studio_root>/copy (distribute/cli.py).
# No dotfile and no lock file is ever listed.
TABLE = {
    "std-source-analyst": ("videos/<v>/work/source.md",),
    "std-strategist": ("videos/<v>/work/brief.json", "videos/<v>/work/brief.md"),
    "std-writer": ("videos/<v>/script.<lang>.md", "videos/<v>/work/<lang>/claims-map.json"),
    # a language of the video other than its source_lang (the translator never writes the source script)
    "std-translator": ("videos/<v>/script.<lang>.md",),
    # board edits of the script (std-visual-director.md Outputs 1), the credits draft, the board notes
    "std-visual-director": ("videos/<v>/script.<lang>.md", "videos/<v>/CREDITS.draft.yaml",
                            "videos/<v>/work/<lang>/board.md"),
    "std-distributor": ("copy/<v>/<lang>/<platform>.md",),
}


def _match(pattern, parts):
    """{placeholder: value} when parts (a list) fit the pattern, else None. `<lang>` may sit inside a file name."""
    pp = pattern.split("/")
    if len(pp) != len(parts):
        return None
    got = {}
    for p, x in zip(pp, parts):
        if "<" not in p:
            if p != x:
                return None
            continue
        rx = "^" + re.escape(p).replace(re.escape("<v>"), "(?P<v>[^/]+)").replace(
            re.escape("<lang>"), "(?P<lang>[^/]+)").replace(re.escape("<platform>"), "(?P<platform>[^/]+)") + "$"
        m = re.match(rx, x)
        if m is None:
            return None
        for k, val in m.groupdict().items():
            if got.get(k, val) != val:
                return None
            got[k] = val
    return got


def read_state(vdir):
    """The video's state.json (dict) read without following a link, or None."""
    data = _read(os.path.join(vdir, "work", "state.json"))
    if data is None:
        return None
    try:
        s = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return s if isinstance(s, dict) else None


def owned(hook, tool, path, worktree, studio_root):
    """The reason to allow when this subagent writes one of its own outputs, else None."""
    try:
        return _owned(hook, tool, path, worktree, studio_root)
    except Exception:  # noqa: BLE001 — never a deny: the normal prompt
        return None


def _owned(hook, tool, path, worktree, studio_root):
    if hook.get("permission_mode") != "default" or tool not in TOOLS:
        return None
    agent_id, agent_type = hook.get("agent_id"), hook.get("agent_type")
    if not isinstance(agent_id, str) or not agent_id or agent_type not in TABLE:
        return None  # the main session (no agent_id; `claude --agent` sets agent_type alone) has no row
    if not isinstance(path, str) or not os.path.isabs(path) or any(p in (".", "..") for p in path.split("/")):
        return None
    path = os.path.normpath(path)
    real = os.path.realpath(path)
    if not _inside(real, worktree) or real == worktree:
        return None
    rel = real[len(worktree.rstrip("/")) + 1:].split("/")
    # the path as spelled ends in the same components (no link renamed one) below a root that resolves to the
    # repository (a linked root such as /tmp is fine), and no component below that root is a link
    spelled = path.split("/")
    if spelled[-len(rel):] != rel:
        return None
    prefix = "/".join(spelled[:-len(rel)]) or "/"
    if os.path.realpath(prefix) != worktree or not _no_link_below(prefix, rel):
        return None
    sr = [x for x in studio_root.split("/") if x]
    if rel[:len(sr)] != sr:
        return None
    under = rel[len(sr):]
    if under[:1] == ["copy"]:
        loc, v, rest = None, under[1] if len(under) > 1 else "", under
    elif under[:1] == ["videos"]:
        loc, v, rest = "videos", under[1] if len(under) > 1 else "", ["videos"] + under[1:]
    elif under[:2] == ["local", "videos"]:
        loc, v, rest = "local", under[2] if len(under) > 2 else "", ["videos"] + under[2:]
    else:
        return None
    if not VIDEO_ID.match(v):
        return None
    got = None
    for pat in TABLE[agent_type]:
        got = _match(pat, rest)
        if got is not None:
            break
    if got is None or got.get("v") != v:
        return None
    # the folder store.video_dir resolves to: exactly one of public and local, a real folder
    pub = os.path.join(worktree, *(sr + ["videos", v]))
    lcl = os.path.join(worktree, *(sr + ["local", "videos", v]))
    found = [d for d in (pub, lcl) if _real_dir(d)]
    if len(found) != 1:
        return None
    if loc == "videos" and found[0] != pub or loc == "local" and found[0] != lcl:
        return None
    if not _no_link_below(worktree, sr + ["videos" if found[0] == pub else "local"]):
        return None
    state = read_state(found[0])
    if state is None or state.get("video") != v:
        return None
    langs = state.get("langs") if isinstance(state.get("langs"), dict) else {}
    lang = got.get("lang")
    if lang is not None:
        if not LANG.match(lang) or lang not in langs:
            return None
        if agent_type == "std-translator" and lang == state.get("source_lang"):
            return None
    platform = got.get("platform")
    if platform is not None:
        from ..state import schema
        brief = state.get("brief") if isinstance(state.get("brief"), dict) else {}
        plats = brief.get("platforms") or []
        plats = list(plats) if isinstance(plats, (dict, list)) else []  # {platform: [output, …]} (state.json brief)
        if not schema.platform_ok(platform, state.get("kind")) or platform not in plats:
            return None
    try:
        st = os.lstat(real)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:  # a hard link writes elsewhere too
            return None
    except FileNotFoundError:
        pass  # Write creates it
    return "%s writes its own output %s (role output, no link)" % (agent_type, "/".join(rel))
