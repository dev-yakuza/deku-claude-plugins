"""Path resolution for the scanner (m0d1a-plan §7): lexical and real paths, the nearest existing
ancestor, git discovery by reading .git (no child processes), comparison keys, and the one file-system gateway (`FS`).
"""

import os
import stat
import unicodedata

from . import limits


class FS(object):
    """Every file-system access of the scanner goes through here (counted; tests may subclass)."""

    def __init__(self, max_calls=limits.MAX_FS_CALLS):
        self.calls = 0
        self.reads = 0
        self.max_calls = max_calls
        self._stat = {}

    def _count(self):
        self.calls += 1
        if self.calls > self.max_calls:
            raise limits.LimitExceeded("fs-calls")

    def stat(self, path):
        """os.stat result, None when missing, 'error' when it cannot be checked."""
        if path in self._stat:
            return self._stat[path]
        self._count()
        try:
            r = os.stat(path)
        except FileNotFoundError:
            r = None
        except NotADirectoryError:
            r = None
        except OSError:
            r = "error"
        self._stat[path] = r
        return r

    def exists(self, path):
        r = self.stat(path)
        return r is not None and r != "error"

    def isdir(self, path):
        r = self.stat(path)
        return r is not None and r != "error" and stat.S_ISDIR(r.st_mode)

    def isfile(self, path):
        r = self.stat(path)
        return r is not None and r != "error" and stat.S_ISREG(r.st_mode)

    def is_exec(self, path):
        return self.isfile(path) and os.access(path, os.X_OK)

    def realpath(self, path):
        self._count()
        return os.path.realpath(path)

    def read(self, path, limit=limits.MAX_FILE_READ, count_read=True):
        self._count()
        if count_read:
            self.reads += 1
            if self.reads > limits.MAX_FILE_READS:
                return None
        try:
            with open(path, "rb") as f:
                data = f.read(limit)
        except OSError:
            return None
        return data.decode("utf-8", "replace")

    def listdir(self, path):
        self._count()
        try:
            return os.listdir(path)
        except OSError:
            return None


class Resolved(object):
    FIELDS = ("text", "abs", "real", "exists", "anchor", "tail", "repo", "cmp", "special", "stat_error")

    def __init__(self, **kw):
        for f in self.FIELDS:
            setattr(self, f, kw.get(f))

    def to_dict(self):
        d = {f: getattr(self, f) for f in self.FIELDS}
        if self.repo is not None:
            d["repo"] = self.repo.to_dict()
        return d

    def __repr__(self):
        return "Resolved(%r)" % (self.abs,)


class GitRepo(object):
    def __init__(self, worktree, git_dir, common_dir):
        self.worktree, self.git_dir, self.common_dir = worktree, git_dir, common_dir

    def to_dict(self):
        return {"worktree": self.worktree, "git_dir": self.git_dir, "common_dir": self.common_dir}

    def __eq__(self, other):
        return isinstance(other, GitRepo) and self.to_dict() == other.to_dict()

    def __hash__(self):
        return hash(self.worktree)


SPECIAL = ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/stdin", "/dev/tty")


class Where(object):
    """Resolution with per-scan caches."""

    def __init__(self, fs, env):
        self.fs = fs
        self.env = env
        self._git = {}
        self._ci = {}

    def home(self, env_set=None):
        return (env_set or {}).get("HOME") or self.env.get("HOME") or os.path.expanduser("~")

    def absolute(self, text, cwd):
        """Lexical absolute path (tilde already expanded by the caller), or None when cwd is unknown."""
        if os.path.isabs(text):
            p = text
        elif cwd is None:
            return None
        else:
            p = os.path.join(cwd, text)
        p = os.path.normpath(p)
        if p.startswith("//"):
            p = "/" + p.lstrip("/")
        return p

    def resolve(self, text, cwd):
        """Resolved for a literal path text; cwd None → abs None (unknown)."""
        if text is None:
            return None
        special = text in SPECIAL or text.startswith("/dev/fd/")
        a = self.absolute(text, cwd)
        if a is None:
            return Resolved(text=text, abs=None, special=special)
        anchor, tail, err = a, "", False
        while True:
            st = self.fs.stat(anchor)
            if st == "error":
                err = True
            elif st is not None:
                break
            parent = os.path.dirname(anchor)
            if parent == anchor:
                break
            tail = os.path.basename(anchor) + ("/" + tail if tail else "")
            anchor = parent
        real_anchor = self.fs.realpath(anchor)
        real = os.path.join(real_anchor, tail) if tail else real_anchor
        repo = self.git_repo(anchor)
        return Resolved(text=text, abs=a, real=real, exists=(tail == "" and not err), anchor=anchor, tail=tail,
                        repo=repo, cmp=self.cmp_key(real), special=special, stat_error=err)

    # ---- git discovery (reads .git files only) ----

    def git_repo(self, path):
        """GitRepo for the worktree containing `path` (an existing path), or None."""
        d = path if self.fs.isdir(path) else os.path.dirname(path)
        seen = []
        repo = None
        while True:
            if d in self._git:
                repo = self._git[d]
                break
            seen.append(d)
            dotgit = os.path.join(d, ".git")
            st = self.fs.stat(dotgit)
            if st is not None and st != "error":
                repo = self._from_dotgit(d, dotgit)
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        for s in seen:
            self._git[s] = repo
        return repo

    def _from_dotgit(self, worktree, dotgit):
        if self.fs.isdir(dotgit):
            git_dir = dotgit
        else:
            text = self.fs.read(dotgit, 4096, count_read=False) or ""
            line = text.strip().splitlines()[0] if text.strip() else ""
            if not line.startswith("gitdir:"):
                return None
            g = line[len("gitdir:"):].strip()
            git_dir = os.path.normpath(g if os.path.isabs(g) else os.path.join(worktree, g))
        common = git_dir
        cf = os.path.join(git_dir, "commondir")
        if self.fs.isfile(cf):
            c = (self.fs.read(cf, 4096, count_read=False) or "").strip()
            if c:
                common = os.path.normpath(c if os.path.isabs(c) else os.path.join(git_dir, c))
        return GitRepo(self.fs.realpath(worktree), self.fs.realpath(git_dir), self.fs.realpath(common))

    # ---- comparison ----

    def case_insensitive(self, path):
        """Whether the volume holding `path` ignores case (checked once per top-level dir)."""
        parts = path.split("/")
        key = "/".join(parts[:3]) or "/"
        if key in self._ci:
            return self._ci[key]
        probe = None
        p = path
        while p and p != "/":
            base = os.path.basename(p)
            if base.lower() != base.upper() and self.fs.exists(p):
                probe = p
                break
            p = os.path.dirname(p)
        result = False
        if probe:
            base = os.path.basename(probe)
            swapped = os.path.join(os.path.dirname(probe), base.swapcase())
            a, b = self.fs.stat(probe), self.fs.stat(swapped)
            result = b not in (None, "error") and a not in (None, "error") and a.st_ino == b.st_ino
        self._ci[key] = result
        return result

    def cmp_key(self, path):
        if path is None:
            return None
        k = unicodedata.normalize("NFC", path)
        return k.casefold() if self.case_insensitive(path) else k

    def path_class(self, real, env):
        """Every class that applies, e.g. ["repo:<worktree>", "tmp"] for a sandbox repository under a
        temp folder; ["home"] / ["other"] when nothing else applies."""
        if real is None:
            return ["other"]
        out = []
        anc = real
        while anc not in ("/", "") and not self.fs.exists(anc):
            anc = os.path.dirname(anc)
        repo = self.git_repo(anc) if anc not in ("/", "") else None
        if repo:
            out.append("repo:" + repo.worktree)
        tmp_roots = ["/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp", "/private/var/folders", "/var/folders"]
        t = env.get("TMPDIR")
        if t:
            tmp_roots.append(os.path.realpath(t).rstrip("/"))
        for r in tmp_roots:
            if real == r or real.startswith(r.rstrip("/") + "/"):
                out.append("scratch" if "/scratchpad" in real and "/claude-" in real else "tmp")
                break
        if out:
            return out
        home = env.get("HOME")
        if home and (real == home or real.startswith(home.rstrip("/") + "/")):
            return ["home"]
        return ["other"]


def which(name, path_value, fs):
    """Absolute executable path for `name` on a PATH string, or None."""
    if not name or "/" in name or path_value is None:
        return None
    for d in path_value.split(":"):
        if not d:
            d = "."
        p = os.path.join(d, name)
        if fs.is_exec(p):
            return p
    return None
