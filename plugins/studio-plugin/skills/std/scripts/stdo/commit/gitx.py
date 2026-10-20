"""git for check_commit and hooks.py (m0e-plan §2): hardened calls (no fsmonitor, pager, external diff
or textconv; none of the commands used runs hooks, and core.hooksPath must stay readable) that keep the
caller's GIT_INDEX_FILE / GIT_DIR — inside a pre-commit hook the index of `git commit -a` or a pathspec
commit is a temporary one and must be the one we read."""

import os
import subprocess

HARDEN = ["-c", "core.fsmonitor=false", "-c", "core.pager=cat",
          "-c", "diff.external=", "-c", "core.quotePath=false", "--no-pager"]
EMPTY_TREE_SHA1 = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class GitError(Exception):
    pass


class Git(object):
    def __init__(self, cwd, env=None):
        self.cwd = cwd
        env = dict(os.environ if env is None else env)
        for k in ("GIT_EXTERNAL_DIFF", "GIT_PAGER"):
            env.pop(k, None)
        env["GIT_OPTIONAL_LOCKS"] = "0"
        env["LC_ALL"] = "C"
        self.env = env
        self._empty = None
        self._info = None
        self._head = False
        self._config = None
        self._blobs = {}

    def run(self, *args, **kw):
        data = kw.get("input")
        out = subprocess.run(["git"] + HARDEN + list(args), cwd=self.cwd, env=self.env, input=data,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=None if data is not None
                             else subprocess.DEVNULL, timeout=kw.get("timeout", 60))
        if kw.get("check", True) and out.returncode != 0:
            raise GitError("git %s: %s" % (" ".join(args), out.stderr.decode("utf-8", "replace").strip()))
        return out

    def text(self, *args, **kw):
        return self.run(*args, **kw).stdout.decode("utf-8", "surrogateescape")

    def ok(self, *args):
        return self.run(*args, check=False).returncode == 0

    # --- places (one rev-parse for all of them; a hook is short-lived, so values are cached) ---
    def _places(self):
        if self._info is None:
            lines = self.text("rev-parse", "--path-format=absolute", "--show-toplevel", "--absolute-git-dir",
                              "--git-common-dir").splitlines()
            if len(lines) != 3:
                raise GitError("git rev-parse: unexpected output (a bare repository?)")
            self._info = lines
        return self._info

    def toplevel(self):
        return self._places()[0]

    def git_dir(self):
        return self._places()[1]

    def common_dir(self):
        return self._places()[2]

    def git_path(self, name):
        """A per-worktree file of the git dir (MERGE_HEAD, rebase-merge, index); `hooks` asks git
        (core.hooksPath)."""
        if name == "hooks":
            return self.text("rev-parse", "--path-format=absolute", "--git-path", name).strip()
        return os.path.join(self.git_dir(), name)

    def head(self):
        if self._head is False:
            out = self.run("rev-parse", "-q", "--verify", "HEAD^{commit}", check=False)
            self._head = out.stdout.decode().strip() if out.returncode == 0 else None
        return self._head

    def empty_tree(self):
        if self._empty is None:
            self._empty = self.text("hash-object", "-t", "tree", "--stdin", input=b"").strip()
        return self._empty

    def config(self, name):
        """The effective value (the last one), like `git config --get`; keys compared case-insensitively
        (section and variable names are)."""
        if self._config is None:
            out = self.run("config", "--list", "-z", check=False)
            conf = {}
            for rec in out.stdout.decode("utf-8", "surrogateescape").split("\0"):
                if rec:
                    k, _, v = rec.partition("\n")
                    conf[k.lower()] = v
            self._config = conf
        return self._config.get(name.lower())

    def ignorecase(self):
        return (self.config("core.ignorecase") or "").lower() == "true"

    # --- content ---
    def staged(self, base):
        """[(status, path)] of the index against `base` (a tree-ish), renames as delete + add."""
        raw = self.text("diff", "--cached", "--name-status", "-z", "--no-renames", "--no-ext-diff",
                        "--no-textconv", base, "--")
        parts = raw.split("\0")
        out = []
        i = 0
        while i + 1 < len(parts):
            st, p = parts[i], parts[i + 1]
            if not st:
                break
            out.append((st[:1], p))
            i += 2
        return out

    def write_tree(self):
        return self.text("write-tree").strip()

    def show(self, spec):
        """Bytes of `<rev>:<path>` or `:<path>` (index), None when absent."""
        if spec not in self._blobs:
            self.prefetch([spec])
        return self._blobs[spec]

    def prefetch(self, specs):
        """Read several blobs with one `cat-file --batch`."""
        want = [s for s in specs if s not in self._blobs and "\n" not in s]
        if not want:
            return
        out = self.run("cat-file", "--batch", input=("\n".join(want) + "\n").encode("utf-8", "surrogateescape"))
        data, pos = out.stdout, 0
        for spec in want:
            nl = data.index(b"\n", pos)
            head = data[pos:nl].split()
            pos = nl + 1
            if len(head) == 3 and head[1] == b"blob":
                size = int(head[2])
                self._blobs[spec] = data[pos:pos + size]
                pos += size + 1
            elif len(head) == 3:
                pos += int(head[2]) + 1  # not a blob (a tree): treat as absent
                self._blobs[spec] = None
            else:
                self._blobs[spec] = None

    def index_changed(self):
        """Forget cached index blobs (after staging)."""
        self._blobs = {k: v for k, v in self._blobs.items() if not k.startswith(":")}

    def index_blobs(self, paths):
        """{path: sha} of stage-0 index entries (conflicted entries: the string "conflict")."""
        if not paths:
            return {}
        raw = self.text("ls-files", "-s", "-z", "--", *[":(literal)" + p for p in paths])
        out = {}
        for rec in raw.split("\0"):
            if not rec:
                continue
            meta, path = rec.split("\t", 1)
            _mode, sha, stage = meta.split()
            out[path] = sha if stage == "0" else "conflict"
        return out

    def tree_blobs(self, rev, paths):
        if not paths:
            return {}
        raw = self.text("ls-tree", "-r", "-z", rev, "--", *paths)
        out = {}
        for rec in raw.split("\0"):
            if not rec:
                continue
            meta, path = rec.split("\t", 1)
            out[path] = meta.split()[2]
        return out
