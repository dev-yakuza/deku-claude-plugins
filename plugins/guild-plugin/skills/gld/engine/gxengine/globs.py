"""The one path-glob dialect of the engine — U3.

Used by procedure outputs (ownership, judge write scope), repository path rules,
control-file patterns, secret paths. Worktree-relative POSIX paths. gitignore-like:
`**` matches any number of directories (including none), `*` and `?` stay inside one
path segment, a pattern without `/` matches at any depth only when it starts with `**/`
(no implicit basename matching — say `**/CLAUDE.md`). `{issue}` must be substituted
before matching.

Details (U3):
  - a segment that is exactly `**`: leading `**/x` = `x` at any depth, `a/**/b` = zero
    or more directories between, trailing `a/**` = everything strictly inside `a`, a
    lone `**` = every path. `**` inside a longer segment (`a**b`) is a plain `*`.
  - a trailing `/` means "everything inside": `dir/` = `dir/**`.
  - no character classes and no escapes: `[`, `]`, `\\` are literal characters.
  - matching is case-sensitive by default (`fold=False`); `fold=True` folds case. The
    security judgments fold ALWAYS, whatever the platform (P3-A, fail-closed — macOS and
    Windows file systems are case-insensitive: `.Claude/x` writes `.claude/x`, and a
    judgment must not depend on where the engine runs): `is_control_file`,
    `names_control_file`, `is_secret_path` and the ownership test (`match(..., fold=True)`
    in results.py). The judge write-scope test stays exact (case-sensitive): there, a
    path that differs only in case from an output is OUTSIDE the outputs (fail-closed).
  - patterns and paths must be relative and normalised (no leading `/`, no `.`/`..`
    or empty segments) — anything else is a ValueError, never a silent non-match.
"""

import functools
import re

from . import defaults

GLOB_CHARS = frozenset("*?")


def _check_rel(s, what):
    if not isinstance(s, str) or not s:
        raise ValueError(f"empty {what}")
    if s.startswith("/"):
        raise ValueError(f"{what} must be relative: {s!r}")
    if "\0" in s:
        raise ValueError(f"NUL in {what}: {s!r}")
    body = s[:-1] if what == "pattern" and s.endswith("/") else s
    for seg in body.split("/"):
        if seg in ("", ".", ".."):
            raise ValueError(f"{what} is not normalised: {s!r}")


def _segment_re(seg):
    out = []
    i = 0
    while i < len(seg):
        c = seg[i]
        if c == "*":
            while i + 1 < len(seg) and seg[i + 1] == "*":
                i += 1
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


@functools.lru_cache(maxsize=1024)
def _compile(pattern):
    if "{issue}" in pattern:
        raise ValueError(f"unsubstituted {{issue}} in pattern {pattern!r}")
    _check_rel(pattern, "pattern")
    if pattern.endswith("/"):
        pattern += "**"
    segs = []
    for seg in pattern.split("/"):
        if not (seg == "**" and segs and segs[-1] == "**"):
            segs.append(seg)                       # `**/**` is one `**`
    if segs == ["**"]:
        return re.compile(r"\A.+\Z", re.S)
    parts = []
    n = len(segs)
    for i, seg in enumerate(segs):
        last = i == n - 1
        if seg == "**":
            if i == 0:
                parts.append(r"(?:.+/)?")          # leading: zero or more directories
            elif last:
                parts.append(r"/.+")               # trailing: something strictly inside
            else:
                parts.append(r"/(?:.+/)?")         # middle: zero or more directories
            continue
        prev_star = i > 0 and segs[i - 1] == "**"
        if i > 0 and not prev_star:
            parts.append("/")
        parts.append(_segment_re(seg))
    return re.compile(r"\A" + "".join(parts) + r"\Z", re.S)


def _check_path(path):
    _check_rel(path, "path")
    if path.endswith("/"):
        raise ValueError(f"path is not normalised: {path!r}")


def _matches(pattern, path, fold):
    if fold:
        return _compile(pattern.lower()).match(path.lower()) is not None
    return _compile(pattern).match(path) is not None


def match(pattern, path, fold=False):
    """True when the worktree-relative `path` matches `pattern` (`fold`: ignore case)."""
    _check_path(path)
    _compile(pattern)          # a bad pattern is a ValueError whatever the case
    return _matches(pattern, path, fold)


def match_any(patterns, path, fold=False):
    """The first pattern of `patterns` matching `path`, or None (`fold`: ignore case)."""
    _check_path(path)
    for p in patterns:
        _compile(p)
        if _matches(p, path, fold):
            return p
    return None


def is_secret_path(path, patterns):
    """True when `path` matches one of the repository secret globs — case folded always
    (P3-A: secret-path judgments are case-insensitive, fail-closed)."""
    return match_any(patterns, path, fold=True) is not None


def is_glob(pattern):
    """True when `pattern` has a wildcard (otherwise it names one path)."""
    return any(c in GLOB_CHARS for c in pattern) or pattern.endswith("/")


def literal_prefix(pattern):
    """The leading segments of `pattern` before the first wildcard segment (as a list)."""
    out = []
    for seg in pattern.rstrip("/").split("/"):
        if any(c in GLOB_CHARS for c in seg):
            break
        out.append(seg)
    return out


def _fixed_ends(seg):
    """(chars before the first wildcard, chars after the last wildcard) of one segment."""
    i = min(seg.index(c) for c in GLOB_CHARS if c in seg)
    j = max(seg.rindex(c) for c in GLOB_CHARS if c in seg)
    return seg[:i], seg[j + 1:]


def _last_segments_compatible(a, b):
    sa, sb = a.rstrip("/").split("/")[-1], b.rstrip("/").split("/")[-1]
    if a.endswith("/") or b.endswith("/") or "**" in (sa, sb):
        return True
    wa, wb = is_glob(sa), is_glob(sb)
    if not wa and not wb:
        return sa == sb
    if not wa:
        return re.fullmatch(_segment_re(sb), sa) is not None
    if not wb:
        return re.fullmatch(_segment_re(sa), sb) is not None
    (ha, ta), (hb, tb) = _fixed_ends(sa), _fixed_ends(sb)
    return (ha.startswith(hb) or hb.startswith(ha)) and (ta.endswith(tb) or tb.endswith(ta))


def may_overlap(a, b):
    """Conservative overlap test of two patterns: True unless they surely match no common path.

    Two literals overlap when equal; a literal and a glob when the glob matches it. Two
    globs overlap unless their fixed leading directories differ or their last segments
    cannot match the same name (fail-closed: anything not provably disjoint overlaps).
    """
    _compile(a), _compile(b)
    ga, gb = is_glob(a), is_glob(b)
    if not ga and not gb:
        return a == b
    if not ga:
        return match(b, a)
    if not gb:
        return match(a, b)
    pa, pb = literal_prefix(a), literal_prefix(b)
    k = min(len(pa), len(pb))
    if pa[:k] != pb[:k]:
        return False
    return _last_segments_compatible(a, b)


def _cover_segments(pattern):
    """The segments of a pattern for `covers`: "**" or a token string ("*" = a run of stars, "?" = one character,
    anything else literal) — the same normalisation as _compile (trailing "/" = "/**", "**/**" = "**")."""
    _compile(pattern)
    if pattern.endswith("/"):
        pattern += "**"
    out = []
    for seg in pattern.split("/"):
        if seg == "**":
            if not (out and out[-1] == "**"):
                out.append("**")
        else:
            out.append(re.sub(r"\*+", "*", seg))
    return out


def _least(segs, i):
    """The fewest path segments segment `i` stands for: a lone or trailing `**` at least one, any other `**` none."""
    if segs[i] != "**":
        return 1
    return 1 if len(segs) == 1 or i == len(segs) - 1 else 0


def _segment_covers(o, n):
    """True when every name the inner segment `n` matches is matched by the outer segment `o` (token alignment:
    an outer `*` takes any run of inner tokens, an outer `?` one inner literal or `?`, a literal itself)."""
    @functools.lru_cache(maxsize=None)
    def go(i, j):
        if i == len(o):
            return j == len(n)
        if o[i] == "*":
            return go(i + 1, j) or (j < len(n) and go(i, j + 1))
        if j == len(n) or n[j] == "*":
            return False
        if o[i] == "?":
            return go(i + 1, j + 1)
        return n[j] == o[i] and go(i + 1, j + 1)
    return go(0, 0)


def covers(outer, inner):
    """Does every path `inner` matches also match `outer`? → True (proved), False (an inner path without wildcards
    that `outer` does not match), None (not proved — the caller treats it as "cannot tell", fail-closed).

    The proof aligns the two patterns (sound, not complete): an outer `**` takes any run of inner segments that
    stands for at least as many path segments as it needs (U3: a lone or trailing `**` needs one), any other outer
    segment one inner segment it covers token by token (_segment_covers). An inner `**` is taken only by an outer
    `**`. Case-sensitive; a proof holds for the case-folded match too (folding keeps the alignment)."""
    A, B = _cover_segments(outer), _cover_segments(inner)
    if not is_glob(inner):
        return match(outer, inner)

    @functools.lru_cache(maxsize=None)
    def go(a, b):
        if a == len(A):
            return b == len(B)
        if A[a] == "**":
            need, have = _least(A, a), 0
            for k in range(b, len(B) + 1):
                if have >= need and go(a + 1, k):
                    return True
                if k < len(B):
                    have += _least(B, k)
            return False
        return b < len(B) and B[b] != "**" and _segment_covers(A[a], B[b]) and go(a + 1, b + 1)
    return True if go(0, 0) else None


CONTROL_FOLDERS = (".claude",)
"""Folder names that make everything inside them a control file at any depth (`**/.claude/**`)."""
CONTROL_NAMES = ("claude.md", "claude.local.md", "agents.md")
"""Lower-cased file names that are control files at any depth (`**/CLAUDE.md` …)."""


def names_control_file(pattern, issue):
    """True when an output pattern names — or MAY match — a control file (case-insensitive).

    A path: it is a control file. A glob (P3-Z decision 10, fail-closed: any possible
    overlap is refused at the procedure check):
      - its fixed leading directories are inside a control folder (`.claude/...`);
      - any directory segment may be a control folder: a literal `.claude`, a wildcard
        segment that can match `.claude` (`.c*`), and `**` (it can be `.claude` —
        `docs/**/x.md` matches `docs/.claude/x.md`);
      - the last segment may be a control file or folder name: a literal `CLAUDE.md`, a
        wildcard that can match one (`*.md`, `AGENTS*`), `**`, a trailing `/`;
      - it may match this Issue's procedure.yaml (`docs/specs/42/*.yaml`).
    `docs/specs/42/qa-*.md` passes: no segment can be `.claude` and `qa-*.md` matches no
    control name.
    """
    _compile(pattern)
    if not is_glob(pattern):
        return is_control_file(pattern, issue)
    low = pattern.lower()
    prefix = literal_prefix(low)
    for g in control_globs(issue):
        gl = g.lower()
        if gl.endswith("/**") and is_glob(gl) and not gl.startswith("**"):
            folder = gl[:-3].split("/")
            if prefix[:len(folder)] == folder:
                return True
    if low.endswith("/"):
        return True
    segs = low.split("/")
    dirs, last = segs[:-1], segs[-1]
    for seg in dirs:
        if seg == "**" or any(re.fullmatch(_segment_re(seg), name) for name in CONTROL_FOLDERS):
            return True
    if last == "**":
        return True
    if any(re.fullmatch(_segment_re(last), name) for name in CONTROL_NAMES + CONTROL_FOLDERS):
        return True
    proc = control_globs(issue)[-1].lower()
    if proc.endswith("procedure.yaml") and match(low, proc):
        return True
    return False


def control_globs(issue):
    """defaults.CONTROL_FILE_GLOBS with `{issue}` substituted."""
    if isinstance(issue, bool) or not isinstance(issue, int) or issue < 1:
        raise ValueError(f"bad issue number {issue!r}")
    return tuple(g.replace("{issue}", str(issue)) for g in defaults.CONTROL_FILE_GLOBS)


def is_control_file(path, issue):
    """True when `path` matches defaults.CONTROL_FILE_GLOBS for this Issue (§7.6).

    Case-insensitive (fail-closed on case-insensitive file systems).
    """
    _check_path(path)
    low = path.lower()
    return any(_compile(g.lower()).match(low) is not None for g in control_globs(issue))
