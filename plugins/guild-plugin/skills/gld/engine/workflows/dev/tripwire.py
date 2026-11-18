"""workflows.dev.tripwire — the execute-stage auditor's mutation tripwire (catalog B P35a.2–P35a.9,
D-M1–D-M7, D-A1; design §3.4 MUTATION).

Readings (engine git, hooks off — never the worktree's own config):
    numstat   `git diff --numstat --no-renames <mb>`      → {(path, added, deleted)}
    status    `git status --porcelain -uall`               → only `??` paths kept (D-M1)
    head      `git rev-parse HEAD`
    content   sha1 + bytes (≤ 256 KiB each, 4 MiB total) of every path in either set, so a
              whitespace-only rewrite can be told from a semantic one without the auditor's help
The before-reading lives in the ENGINE's run dir (`<run>/in/mutation-before.json`), never in the
worktree (the legacy file was inside the tree and had to be excluded by construction, D-M6). A
missing/unreadable before-file on compare means mutation (D-M7). Ignored on both sides:
`.claude/guild/gates/findings.json` (the gate's own report) and the legacy before-file path.

compare() — D-M2 equal → clean; D-M3 a `??` path vanished while a numstat triple appeared on the
same path → benign (committed/staged by a hook); D-M4 a `??` vanished with no triple → mutation;
D-M5 any other triple appearing/vanishing/changing → `attribute`: whitespace-only against the
before bytes → formatter (proceed + narrate), a new untracked path matching a cache glob →
artifact (note), everything else → the MUTATION judge (sonnet; unsure → mutation). The caller
re-takes the after-reading ONCE before concluding (D-M7).
"""

import fnmatch
import hashlib
import json
import os

from guildcore.adapters import git as G

IGNORED = (".claude/guild/gates/findings.json", ".claude/guild/memory/mutation-before.json")
CACHE_GLOBS = ("__pycache__/*", "*/__pycache__/*", ".pytest_cache/*", ".ruff_cache/*", ".mypy_cache/*",
               "coverage.xml", ".coverage", "node_modules/.cache/*", ".dart_tool/*", "build/*",
               "coverage/*", "*.pyc", ".gradle/*", "target/*")
MAX_ONE, MAX_ALL = 256 * 1024, 4 * 1024 * 1024


def _numstat(root, mb):
    out = set()
    for ln in G.run(root, "diff", "--numstat", "--no-renames", mb, check=False).decode("utf-8", "replace").split("\n"):
        parts = ln.split("\t")
        if len(parts) == 3 and parts[2] not in IGNORED:
            out.add((parts[2], parts[0], parts[1]))
    return out


def _untracked(root):
    raw = G.run(root, "status", "--porcelain", "-uall", "-z", check=False).decode("utf-8", "replace")
    return set(e[3:] for e in raw.split("\0") if e.startswith("?? ") and e[3:] not in IGNORED)


def _content(root, paths):
    out, total = {}, 0
    for p in sorted(paths):
        fp = os.path.join(root, p)
        try:
            if os.path.islink(fp) or not os.path.isfile(fp):
                out[p] = None
                continue
            hs = hashlib.sha1()
            with open(fp, "rb") as fh:
                data = fh.read(MAX_ONE + 1)
                hs.update(data)
                for chunk in iter(lambda: fh.read(1 << 20), b""):     # K3r1-m14: the WHOLE file's hash
                    hs.update(chunk)
        except OSError:
            out[p] = None
            continue
        h = hs.hexdigest()
        keep = None
        if len(data) <= MAX_ONE and total + len(data) <= MAX_ALL:
            keep = data.decode("utf-8", "replace")
            total += len(data)
        out[p] = {"sha1": h, "text": keep}
    return out


def readings(root, mb):
    ns = _numstat(root, mb)
    ut = _untracked(root)
    head = G.run(root, "rev-parse", "HEAD", check=False).decode().strip()
    return {"numstat": sorted([list(t) for t in ns]), "untracked": sorted(ut), "head": head,
            "content": _content(root, set(t[0] for t in ns) | ut)}


def save(path, r):
    from guildcore import fsafe as FS
    os.makedirs(os.path.dirname(path), exist_ok=True)  # fs-ok: engine run dir (the tripwire's before snapshot)
    # created before anything reads it (P35a.2 ordering); never through a link (K3r6-B1)
    FS.write_text(os.path.dirname(path), os.path.basename(path), json.dumps(r))


def load(path):
    try:
        with open(path) as fh:
            r = json.load(fh)
        return r if isinstance(r, dict) and "numstat" in r else None
    except (OSError, ValueError):
        return None


def _ws(t):
    return "".join((t or "").split())


def compare(before, after, root=None):
    """→ {verdict: clean | benign | mutation | attribute, paths, formatter, artifacts, residue}."""
    if before is None:
        return {"verdict": "mutation", "paths": ["(before-reading missing)"], "formatter": [],
                "artifacts": [], "residue": []}
    bn = set(tuple(x) for x in before["numstat"])
    an = set(tuple(x) for x in after["numstat"])
    bu, au = set(before["untracked"]), set(after["untracked"])
    # content hashes too: equal numstat triples can hide an edit (one line swapped for another keeps
    # `1 1`) — the legacy D-M2 compared counts only; the engine also compares the bytes it read
    bc, ac = before.get("content") or {}, after.get("content") or {}
    edited = sorted(p for p in set(bc) & set(ac) if (bc[p] or {}).get("sha1") != (ac[p] or {}).get("sha1"))
    head_moved = before.get("head") != after.get("head")      # K3r1-m14: a hook commit during the scan
    if bn == an and bu == au and not edited and not head_moved:
        return {"verdict": "clean", "paths": [], "formatter": [], "artifacts": [], "residue": []}
    vanished_u = bu - au
    new_triples = an - bn
    new_paths = set(t[0] for t in new_triples)
    gone_paths = set(t[0] for t in bn - an)
    benign, mutation = [], []
    for p in sorted(vanished_u):
        (benign if p in new_paths else mutation).append(p)            # D-M3 / D-M4
    residue = sorted((new_paths | gone_paths | (au - bu) | set(edited)) - set(benign)) + \
        (["(HEAD moved %s→%s)" % ((before.get("head") or "")[:8], (after.get("head") or "")[:8])] if head_moved else [])
    if mutation:
        return {"verdict": "mutation", "paths": sorted(mutation) + residue, "formatter": [],
                "artifacts": [], "residue": residue}
    if not residue:
        return {"verdict": "benign", "paths": benign, "formatter": [], "artifacts": [], "residue": []}
    fmt, art, rest = [], [], []
    for p in residue:
        if p in (au - bu) and any(fnmatch.fnmatch(p, g) for g in CACHE_GLOBS):
            art.append(p)
            continue
        b = (before.get("content") or {}).get(p)
        a = (after.get("content") or {}).get(p)
        if b and a and b.get("text") is not None and a.get("text") is not None and \
                _ws(b["text"]) == _ws(a["text"]):
            fmt.append(p)
            continue
        rest.append(p)
    return {"verdict": "attribute" if rest else "formatter" if fmt else "artifact",
            "paths": residue, "formatter": fmt, "artifacts": art, "residue": rest}


def audited_remainder(before, issue, own_spec_paths=()):
    """D-A1 / J-A1: both readings minus `docs/specs/…` except this Issue's own developer output
    there (paths the developer named, or anything under `docs/specs/<N>/` when unclear — audited
    and the provenance recorded by the caller). Returns (paths, discounted, provenance_unclear)."""
    paths = set(t[0] for t in before["numstat"]) | set(before["untracked"])
    own = "docs/specs/%d/" % int(issue)
    keep, disc, unclear = [], [], []
    for p in sorted(paths):
        if p.startswith("docs/specs/"):
            if p.startswith(own):
                keep.append(p)
                if p not in own_spec_paths:
                    unclear.append(p)
                continue
            disc.append(p)
            continue
        keep.append(p)
    return keep, disc, unclear


def violation_note(issue, before, after, cmp, head, language="ko"):
    """The `<!-- guild:auditor-violation -->` note (a NEW comment per violation, never PATCHed).
    The resolution protocol is in the note; the resolved marker is quoted inside a code span so the
    note itself never reads as resolved (resolution is by POSITION — the last non-blank line)."""
    from guildcore.records import markers
    paths = ", ".join(cmp["paths"][:20]) or "-"
    if language == "ko":
        body = [markers.open_tag("auditor-violation"),
                "## 외부 감사자 위반 — #%d" % int(issue),
                "",
                "감사 스캔 동안 작업 트리가 바뀌었다 — 감사자 또는 레포 hook.",
                "- 스캔 전 HEAD: %s" % head,
                "- 달라진 경로: %s" % markers.value(paths),
                "- 전: numstat %d · untracked %d / 후: numstat %d · untracked %d" % (
                    len(before["numstat"]) if before else 0, len(before["untracked"]) if before else 0,
                    len(after["numstat"]), len(after["untracked"])),
                "",
                "해결: 이 checkout 에서 다른 Issue 를 돌리기 전에 위 경로의 변경을 되돌리고, 이 코멘트의 "
                "닫는 마커 아래 마지막 줄에 `<!-- guild:auditor-violation:resolved -->` 를 덧붙이세요.",
                markers.close_tag("auditor-violation")]
    else:
        body = [markers.open_tag("auditor-violation"),
                "## External auditor violation — #%d" % int(issue), "",
                "The working tree changed during the scan — the auditor or a repo hook.",
                "- HEAD before the scan: %s" % head,
                "- Changed paths: %s" % markers.value(paths), "",
                "To resolve: revert those changes before running any other Issue in this checkout, then "
                "append `<!-- guild:auditor-violation:resolved -->` as the last line below the closing marker.",
                markers.close_tag("auditor-violation")]
    return "\n".join(body)
