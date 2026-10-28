"""The protected-path table (m0d1b-plan §5) and path matching. Data, not decisions: judge.py decides.

Patterns are relative to a repository root; `<sr>` is the repository's studio_root; `**` matches zero
or more directories. Matching uses comparison keys (NFC, case-folded on case-insensitive volumes).
"""

import fnmatch
import os
import unicodedata

# id, patterns, class, who may write (for messages)
TABLE = [
    ("P-STATE", ("<sr>/**/videos/*/work/state.json", "<sr>/**/videos/*/work/approvals.jsonl",
                 "<sr>/**/videos/*/work/.state.lock", "<sr>/**/videos/*/work/**/shown.json",
                 "<sr>/**/videos/*/work/**/verify.json", "<sr>/**/videos/*/work/**/verify.md",
                 "<sr>/**/videos/*/work/**/checks/**",
                 "<sr>/**/videos/*/work/assets.json", "<sr>/**/videos/*/work/commit-ok.json",
                 "<sr>/**/videos/*/work/source/**",
                 "<sr>/**/videos/*/work/**/pronounce-approved.json",
                 "<sr>/**/cast/*/status.json", "<sr>/**/cast/*/approvals.json",
                 "<sr>/**/cast/*/shown.json", ".claude/studio/local/commit-ok.json",
                 ".claude/studio/local/pending-approval.json", ".claude/studio/local/guard-ran.json",
                 ".claude/studio/local/guard-ran.lock", ".claude/studio/local/consumed-answers.jsonl",
                 ".claude/studio/local/consumed-answers.lock", ".claude/studio/local/last-checked.json",
                 ".claude/studio/local/commit-summary-*.txt"),
     "state", "state.py, the Studio check scripts (run_s2v.py, …), check_commit.py and the guard"),
    ("P-CRIT", (".claude/studio/charter.md", ".claude/studio/formats/**", ".claude/studio/platforms/**"),
     "criteria", "the person"),
    ("P-PERS", (".claude/agents/std-fact-checker.md", ".claude/agents/std-source-analyst.md"), "persona", "the person"),
    ("P-WIRE", (".claude/studio/scripts/**", ".claude/studio/installed.json"), "wiring",
     "the person (/std update; installed.json: setup.py)"),
    ("P-CONF", (".claude/studio/config.json",), "config", "the person (protected keys)"),
    ("P-CONF-L", (".claude/studio/local/config.internal.json", ".claude/studio/local/machine.json"), "config",
     "the person (/std config; machine.json: /std config s2v.path)"),
    ("P-CHAR", ("<sr>/**/cast/*/character/**",), "character", "s2v and lock.py actor-op (write character.yaml.draft)"),
    ("P-CRED", ("<sr>/**/CREDITS.yaml",), "credits", "state.py credit (write CREDITS.draft.yaml)"),
    ("P-VOICE", ("<sr>/**/voices/**",), "voices", "s2v"),
    ("P-AUDIO", ("<sr>/**/videos/*/audio/**",), "audio", "s2v"),
    ("P-LOCAL", ("<sr>/local/**", ".claude/studio/local/consent/**"), "local", "the person (deletion)"),
]
BY_ID = {t[0]: t for t in TABLE}
# entries s2v owns (its arguments under these are not agent writes)
S2V_OWNED = {"P-VOICE", "P-AUDIO", "P-CHAR"}
DRAFT_OK = {"P-CHAR": "character.yaml.draft"}
# names that make a protected path when they end a dynamic word's literal tail
TAIL_NAMES = {"local", "character", "voices", "audio", "consent", "state.json", "approvals.jsonl", "shown.json",
              "verify.json", "verify.md", "CREDITS.yaml", "status.json", "approvals.json", "charter.md", "config.json",
              "commit-ok.json", "pending-approval.json", "guard-ran.json", "last-checked.json", "assets.json",
              "pronounce-approved.json", "installed.json"}

READ_ALLOW = {"cat", "head", "tail", "less", "more", "ls", "stat", "file", "du", "wc", "shasum", "sha256sum",
              "sha1sum", "md5", "md5sum", "cmp", "diff", "grep", "egrep", "fgrep", "rg", "ag", "jq", "ffprobe",
              "afplay", "open", "realpath", "readlink", "basename", "dirname", "test", "[", "tree", "find", "bfs",
              "echo", "printf", "true", ":", "pwd", "cd", "pushd", "popd", "xxd", "hexdump", "od", "strings",
              "sort", "uniq", "cut", "column", "nl", "bat", "exiftool", "mdls"}
GIT_READ = {"diff", "status", "log", "show", "ls-files", "rev-parse", "blame", "grep", "branch", "describe",
            "ls-tree", "cat-file", "shortlog", "reflog", "remote", "config", "fetch", "tag", "stash"}
GIT_PATHSPEC_WRITE = {"add", "rm", "mv", "restore", "checkout"}
FIND_WRITE = ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls")
DELETE_PROGS = {"rm", "rmdir", "unlink", "trash", "shred", "srm", "rimraf", "del", "trash-put", "trash-rm",
                "del-cli", "rimraf-cli"}


# programs that can put a link, a moved folder or a copied tree at a path (dest of ln/mv/cp/…)
CREATORS = {"ln", "mv", "cp", "gcp", "install", "rsync", "ditto"}
LOCAL_ANCHORS = ((".claude", "studio", "local"), ("<sr>", "local"))


def local_anchor(parts, sr, fold):
    """`parts` is a machine-local folder (`.claude/studio/local`, `<sr>/local`) or a folder above one."""
    if not parts:
        return False
    for anc in LOCAL_ANCHORS:
        full = []
        for x in anc:
            full += [y for y in sr.strip("/").split("/") if y] if x == "<sr>" else [x]
        if len(parts) <= len(full) and all((a.casefold() == b.casefold()) if fold else a == b
                                           for a, b in zip(parts, full)):
            return True
    return False


def may_hold_protected(parts, sr, fold):
    """A folder at `parts` could hold a protected path (any table entry, local/ included)."""
    return bool(parts) and any(_may_contain(parts, _expand(p, sr), fold) for _t, pats, _c, _w in TABLE for p in pats)


def norm(p):
    return unicodedata.normalize("NFC", p)


def _expand(pattern, sr):
    return pattern.replace("<sr>", sr.strip("/") or "studio").split("/")


def _match(parts, pat, fold):
    """Full match of path parts against pattern parts (`**` = zero or more parts)."""
    def eq(a, b):
        if fold:
            a, b = a.casefold(), b.casefold()
        return fnmatch.fnmatchcase(a, b)

    memo = {}

    def rec(i, j):
        k = (i, j)
        if k in memo:
            return memo[k]
        if j == len(pat):
            r = i == len(parts)
        elif pat[j] == "**":
            r = rec(i, j + 1) or (i < len(parts) and rec(i + 1, j))
        else:
            r = i < len(parts) and eq(parts[i], pat[j]) and rec(i + 1, j + 1)
        memo[k] = r
        return r
    return rec(0, 0)


def _may_contain(parts, pat, fold):
    """Whether some path under directory `parts` (or parts itself) can match the pattern."""
    def eq(a, b):
        if fold:
            a, b = a.casefold(), b.casefold()
        return fnmatch.fnmatchcase(a, b)

    memo = {}

    def rec(i, j):
        k = (i, j)
        if k in memo:
            return memo[k]
        if i == len(parts):
            r = True  # the rest of the pattern can match below the directory
        elif j == len(pat):
            r = False
        elif pat[j] == "**":
            r = rec(i, j + 1) or rec(i + 1, j)
        else:
            r = eq(parts[i], pat[j]) and rec(i + 1, j + 1)
        memo[k] = r
        return r
    return rec(0, 0)


def rel_parts(abs_path, root, fold):
    """Parts of abs_path relative to root, or None when outside."""
    a, r = norm(abs_path), norm(root.rstrip("/"))
    if fold:
        a2, r2 = a.casefold(), r.casefold()
    else:
        a2, r2 = a, r
    if a2 == r2:
        return []
    if not a2.startswith(r2 + "/"):
        return None
    return [x for x in a[len(r) + 1:].split("/") if x]


def classify(parts, sr, fold, include_local=False):
    """The first table entry a repository-relative path matches, or None."""
    for tid, pats, _cls, _who in TABLE:
        if tid == "P-LOCAL" and not include_local:
            continue
        for p in pats:
            if _match(parts, _expand(p, sr), fold):
                if tid in DRAFT_OK and parts and parts[-1] == DRAFT_OK[tid]:
                    break
                return tid
    return None


def delete_hits(parts, sr, fold, is_dir=True):
    """Entry id when deleting/moving `parts` would remove protected data (a directory: anything that
    may be below it; a file or a missing path: the path itself)."""
    roots = [_expand(sr, sr), [".claude", "studio"]]
    for root in roots:
        if len(parts) <= len(root) and _may_contain(parts, root, fold) and \
                all((a.casefold() == b.casefold()) if fold else a == b for a, b in zip(parts, root)):
            return "P-ANC"
    order = [t for t in TABLE if t[0] == "P-LOCAL"] + [t for t in TABLE if t[0] != "P-LOCAL"]
    for tid, pats, _cls, _who in order:
        for p in pats:
            pat = _expand(p, sr)
            if _match(parts, pat, fold) or (is_dir and _may_contain(parts, pat, fold)):
                return tid
    return None


def tail_hits(skeleton):
    """A dynamic word whose literal tail names a protected thing (`\\0/local`, `\\0/character/x`)."""
    tail = skeleton.split("\0")[-1]
    segs = [s for s in tail.split("/") if s]
    return any(s in TAIL_NAMES for s in segs)


def protected_names():
    out = set()
    for _tid, pats, _c, _w in TABLE:
        for p in pats:
            last = p.split("/")[-1]
            if "*" not in last and last not in ("**",):
                out.add(last)
    return sorted(out)


def out_of_repo(user_dir, state_dirs):
    """(path, kind) for files outside repositories: kind "file", "dir" or "prefix"."""
    items = [(os.path.join(user_dir, "studio-sandbox.json"), "file"), (os.path.join(user_dir, "studio-backup"), "dir")]
    for s in state_dirs:
        items.append((os.path.join(s, "heavy.lock.d"), "prefix"))
        items.append((os.path.join(s, "resident.json"), "file"))
    return items
