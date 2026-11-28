"""Checks before anything leaves the machine (design §7.6 "밖으로 내보내는 내용", §7.12 S5 S10) — U10.

  - every external write (comment, PR body, label text, follow-up issue): the body itself
    through the plugin-install-path `gates/gate_precommit.py --scan-text --stdin`
    (0.98.7 secret patterns, reused — no new list). A hit → SecretDetected → needs_human.
  - before every push: the recorded-base range `git diff -a` and
    `git log --format=%an%n%ae%n%B` through the same scanner; plus the close-keyword
    check: a close/fix/resolve-family keyword together with an issue reference in a
    commit message → CloseKeyword → needs_human (S10).
  - role text placed into PR body / comments: `@` → `＠`, `#` → `＃`, and this repo's
    issue/PR URLs → `＃N` (S10). The one closing line is written by the engine.

The close-keyword rule is line-based and deliberately wider than GitHub's own parser: a
keyword (as a word) and an issue reference anywhere on the same line stop the push, even
where GitHub would not close anything (`fix: x (#42)`). False stops go to a human; a
missed one closes an Issue.
"""

import os
import re
import subprocess
import sys

from . import gitops

CLOSE_KEYWORDS = ("close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved")

GATE_REL = os.path.join("skills", "gld", "gates", "gate_precommit.py")
SCAN_TIMEOUT_S = 120
FULLWIDTH_AT = "＠"     # ＠
FULLWIDTH_HASH = "＃"   # ＃

_KEYWORD_RE = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(CLOSE_KEYWORDS) + r")(?![A-Za-z0-9_])", re.IGNORECASE)
# An issue reference as GitHub links it: #N, owner/repo#N, GH-N, or an issues/pull URL.
_REF_RE = re.compile(
    r"#[0-9]+\b"
    r"|(?<![A-Za-z0-9_])GH-[0-9]+\b"
    r"|https?://[^\s/]+/[^\s/]+/[^\s/]+/(?:issues|pull)/[0-9]+",
    re.IGNORECASE)
_SCAN_LINE_RE = re.compile(r"^SECRET-TEXT ([0-9]+)$")


class SecretDetected(Exception):
    """The scanner reported a secret line. `.lines` = reported line numbers, `.source` = what was scanned."""

    def __init__(self, lines, source="text"):
        super().__init__(f"secret pattern in {source} at line(s) {', '.join(map(str, lines))}")
        self.lines = list(lines)
        self.source = source


class CloseKeyword(Exception):
    """A commit message would close an issue (S10). `.commit` sha, `.line`."""

    def __init__(self, commit, line):
        super().__init__(f"commit {commit[:12]} has a closing keyword with an issue reference: {line!r}")
        self.commit = commit
        self.line = line


class ScanError(Exception):
    """The secret scanner could not give a verdict (missing, crashed, unexpected output) → infra.
    Never read as "clean" (fail-closed)."""


def gate_script(plugin_root):
    """Absolute path of the plugin-install-path scanner; ScanError when it is not a regular file."""
    if not isinstance(plugin_root, str) or not os.path.isabs(plugin_root):
        raise ScanError(f"plugin_root must be an absolute path, got {plugin_root!r}")
    path = os.path.join(plugin_root, GATE_REL)
    if not os.path.isfile(path):
        raise ScanError(f"secret scanner not found at {path}")
    return path


def scan_text(text, plugin_root):
    """Run `gate_precommit.py --scan-text --stdin` from the plugin install path; list of hit lines.

    A scanner that cannot run is NOT a pass: raise (→ infra), never return [] (fail-closed).
    `text` may be str or bytes. A text with no non-whitespace character is returned as
    clean without a call (every pattern needs a non-space character; the scanner refuses an
    empty stdin as a usage error).
    """
    script = gate_script(plugin_root)
    data = text if isinstance(text, bytes) else str(text).encode("utf-8", "surrogateescape")
    if not data.strip():
        return []
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}   # the scanner needs no credentials
    try:
        p = subprocess.run([sys.executable, "-I", script, "--scan-text", "--stdin"], input=data,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                           cwd=plugin_root, timeout=SCAN_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ScanError(f"secret scanner did not run: {e}") from None
    lines, other = [], []
    for raw in p.stdout.decode("utf-8", "replace").splitlines():
        m = _SCAN_LINE_RE.match(raw.strip())
        if m:
            lines.append(int(m.group(1)))
        elif raw.strip():
            other.append(raw)
    err = p.stderr.decode("utf-8", "replace").strip()
    if other:
        raise ScanError(f"secret scanner printed unexpected output: {other[:3]!r}")
    if p.returncode == 0 and not lines:
        return []
    if p.returncode == 1 and lines:
        return lines
    raise ScanError(f"secret scanner gave no verdict (rc={p.returncode}, hits={len(lines)}): {err[:300]}")


def _repo_url_re(repo):
    owner, name = repo.split("/", 1)
    return re.compile(
        r"https?://(?:www\.)?github\.com/" + re.escape(owner) + "/" + re.escape(name)
        + r"/(?:issues|pull|pulls)/([0-9]+)(?:[/#?][^\s<>()\[\]\"'`]*)?",
        re.IGNORECASE)


def neutralise(text, repo):
    """Full-width @ and #, same-repo issue/PR URLs → ＃N (S10).

    Order: URLs first (they may carry a `#issuecomment-…` fragment), then every `@` and
    `#`. Applies to the whole text — engine markup that needs a real `#` (the closing line)
    is added after this call; engine bodies use setext / bold headings instead of `#`.
    """
    if not isinstance(repo, str) or repo.count("/") != 1:
        raise ValueError(f"repo must be owner/name, got {repo!r}")
    text = _repo_url_re(repo).sub(lambda m: FULLWIDTH_HASH + m.group(1), str(text))
    return text.replace("@", FULLWIDTH_AT).replace("#", FULLWIDTH_HASH)


def check_text(text, plugin_root, source="text"):
    """Scan `text` exactly as it will be sent; raise SecretDetected on a hit."""
    hits = scan_text(text, plugin_root)
    if hits:
        raise SecretDetected(hits, source)
    return text


def prepare_text(text, repo, plugin_root):
    """neutralise + scan; return the text safe to send or raise SecretDetected."""
    return check_text(neutralise(text, repo), plugin_root)


def find_close_keywords(log_text):
    """Commit-message lines that pair a close keyword with an issue reference."""
    return [line for line in str(log_text).splitlines()
            if _KEYWORD_RE.search(line) and _REF_RE.search(line)]


def check_push_range(ctx, head_sha, plugin_root):
    """Scan diff -a + log of merge-base..HEAD; raise SecretDetected / CloseKeyword.

    Order: commit messages (close keywords, per commit so the stop names the commit), then
    the log text and the diff through the secret scanner. Any scanner failure → ScanError.
    """
    for sha, message in gitops.commit_messages(ctx, head_sha):
        hits = find_close_keywords(message)
        if hits:
            raise CloseKeyword(sha, hits[0])
    check_text(gitops.log_text(ctx, head_sha), plugin_root, "log")
    check_text(gitops.diff_text(ctx, head_sha), plugin_root, "diff")
