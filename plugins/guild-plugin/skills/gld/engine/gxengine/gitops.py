"""The engine's git layer (design §7.6 git row, commit and push, §7.12 S4 S5, §4.4-3) — U10.

Every engine git call:
  - pins GIT_DIR=<common>/worktrees/<own>, GIT_COMMON_DIR=<common>, GIT_WORK_TREE=<wt>
    recorded at Issue start (absolute paths, state.json `git`) — a gitfile/commondir
    tampered with by a role cannot redirect it (S4, scenario E6);
  - adds `-c core.hooksPath=/dev/null -c core.fsmonitor=false`;
  - runs outside the sandbox (engine side), never with a shell.
Ranges never use ref names: merge-base(<recorded base SHA>, <HEAD SHA>)..<HEAD SHA> (S5).
Push: recorded URL + explicit refspec `<HEAD SHA>:refs/heads/<branch>`, always
`--no-verify`, never force; a non-fast-forward refusal is RemoteDiverged → needs_human.
Engine commits of judge outputs: `commit --no-verify` after the file is checked to be a
regular file inside the step's outputs (§7.6).

Hardening beyond the list above (all fail-closed):
  - before every call the worktree's link files (`<git_dir>/commondir`, `<wt>/.git`) must
    still point where they did at Issue start, else Tampered — git reads the commondir FILE
    for refs even when GIT_COMMON_DIR is set, so pinning alone does not cover it (E6);
  - every revision argument must be a full hex SHA — a ref name is refused before git runs;
  - every path argument must be a plain repository-relative path, and pathspecs are literal
    (GIT_LITERAL_PATHSPECS=1) so `:(glob)`-style magic cannot widen a commit;
  - inherited GIT_* variables are dropped except identity / ssh / global-config ones, so a
    stray GIT_INDEX_FILE / GIT_CONFIG_PARAMETERS in the engine's env cannot redirect a call;
  - diffs run with `--no-ext-diff --no-textconv` (no configured program runs on a diff);
  - `protocol.ext.allow=never` (the `ext::` transport runs commands).
"""

import os
import re
import subprocess

from . import globs

SAFE_CONFIG = (
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "protocol.ext.allow=never",
)
# Inherited GIT_* variables the engine keeps (who commits, how ssh authenticates, which
# global config file). Every other GIT_* is dropped before the pinned ones are set.
ENV_KEEP = (
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
    "GIT_SSH", "GIT_SSH_COMMAND", "GIT_SSH_VARIANT", "GIT_ASKPASS",
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
)
TIMEOUT_S = 300            # local calls
NETWORK_TIMEOUT_S = 600    # push / fetch
# `fetch` destination: remote-tracking refs under the conventional name. The engine never
# reads them for a range (S5); they are for roles that read remote state locally (§7.6).
FETCH_REFSPEC = "+refs/heads/*:refs/remotes/origin/*"

_SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_SCP_RE = re.compile(r"^(?:[^@/\s]+@)?[^:/\s]+:[^\s]+$")
_REGULAR_MODES = ("100644", "100755")


class GitError(Exception):
    """A git call failed. `.args_`, `.returncode`, `.stderr`. Judgment-fact failures → infra (§9.3)."""

    def __init__(self, message, args_=(), returncode=None, stderr=""):
        super().__init__(message)
        self.args_ = tuple(args_)
        self.returncode = returncode
        self.stderr = stderr


class RemoteDiverged(Exception):
    """Push refused as non-fast-forward (§7.6 — "원격 브랜치가 갈라짐")."""

    def __init__(self, message, stderr=""):
        super().__init__(message)
        self.stderr = stderr


class UnsafePath(GitError):
    """A path handed to the engine's git layer is not a plain regular file / relative path
    (symlink, `..`, absolute, outside the worktree). → unsafe-path stop, never a commit."""


class Tampered(UnsafePath):
    """The worktree's git link files no longer match what was recorded at Issue start
    (`<git_dir>/commondir`, `<wt>/.git`, an appeared `config.worktree`, a symlinked admin
    dir). Raised BEFORE the git call. Roles cannot write these (render deny, S4); seeing
    one changed is a boundary failure → stop, never "follow the new link".

    Why a check and not only the pinned variables: git 2.50 still reads the `commondir`
    FILE for the refs store even when GIT_COMMON_DIR is set (objects and config follow the
    variable, refs do not) — a tampered commondir would make refs resolve elsewhere.
    """


def _read_link_file(path, what):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise Tampered(f"{what} {path} is missing") from None
    import stat as _stat
    if not _stat.S_ISREG(st.st_mode):
        raise Tampered(f"{what} {path} is not a regular file")
    with open(path, encoding="utf-8", errors="surrogateescape") as f:
        return f.read().strip()


def verify_pins(ctx):
    """Refuse (Tampered) unless the worktree's link files still point where they did at Issue start."""
    if ctx.git_dir == ctx.common_dir:
        return
    if os.path.realpath(ctx.git_dir) != ctx.git_dir:
        raise Tampered(f"worktree admin dir {ctx.git_dir} is reached through a link")
    target = _read_link_file(os.path.join(ctx.git_dir, "commondir"), "commondir")
    if os.path.realpath(os.path.join(ctx.git_dir, target)) != os.path.realpath(ctx.common_dir):
        raise Tampered(f"commondir of {ctx.git_dir} no longer points to {ctx.common_dir}")
    line = _read_link_file(os.path.join(ctx.work_tree, ".git"), "gitfile")
    if not line.startswith("gitdir: ") or os.path.realpath(
            os.path.join(ctx.work_tree, line[len("gitdir: "):])) != os.path.realpath(ctx.git_dir):
        raise Tampered(f"gitfile of {ctx.work_tree} no longer points to {ctx.git_dir}")
    if os.path.lexists(os.path.join(ctx.git_dir, "config.worktree")):
        raise Tampered(f"{ctx.git_dir}/config.worktree appeared (per-worktree config is never engine-made)")


def _is_sha(value):
    return isinstance(value, str) and bool(_SHA_RE.match(value))


def _need_sha(value, what):
    if not _is_sha(value):
        raise GitError(f"{what} must be a full hex commit SHA, got {value!r} (S5: no ref names)")
    return value


def _need_branch(branch):
    if not isinstance(branch, str) or not branch or branch.startswith("-") or branch.startswith("refs/") \
            or any(c.isspace() for c in branch):
        raise GitError(f"not a plain branch name: {branch!r}")
    return branch


def _need_relpath(path):
    """A plain repository-relative path: no absolute, no `..`/`.` segment, no empty segment."""
    if not isinstance(path, str) or not path or "\0" in path or "\\" in path:
        raise UnsafePath(f"not a repository-relative path: {path!r}")
    if path.startswith("/") or path.endswith("/"):
        raise UnsafePath(f"not a repository-relative path: {path!r}")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts) or parts[0] == ".git":
        raise UnsafePath(f"not a repository-relative path: {path!r}")
    return path


def _abspath(value, what):
    if not isinstance(value, str) or not os.path.isabs(value):
        raise GitError(f"{what} must be an absolute path, got {value!r} (S4)")
    return os.path.normpath(value)


def _decode(b):
    return b.decode("utf-8", "surrogateescape")


def is_fixed_url(url):
    """A URL, an absolute path or an scp-style `[user@]host:path` — never a remote NAME (S4)."""
    if not isinstance(url, str) or not url or url.startswith("-") or any(c.isspace() for c in url):
        return False
    if url.lower().startswith("ext::"):
        return False
    if "://" in url or os.path.isabs(url):
        return True
    return bool(_SCP_RE.match(url))


def _base_env(base_env):
    src = os.environ if base_env is None else base_env
    env = {k: v for k, v in src.items() if not k.startswith("GIT_") or k in ENV_KEEP}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_LITERAL_PATHSPECS": "1"})
    return env


class GitContext:
    """The pinned git environment of one Issue.

    Attributes: git_dir, common_dir, work_tree, main_checkout, base_sha, remote_url, branch.
    `base_env` (optional, default os.environ at call time) is the engine's own environment
    the pinned variables are laid over — tests pass an isolated one.
    """

    def __init__(self, git_dir, common_dir, work_tree, main_checkout, base_sha, remote_url, branch,
                 base_env=None):
        self.git_dir = _abspath(git_dir, "git_dir")
        self.common_dir = _abspath(common_dir, "common_dir")
        self.work_tree = _abspath(work_tree, "work_tree")
        self.main_checkout = _abspath(main_checkout, "main_checkout")
        self.base_sha = _need_sha(base_sha, "base_sha")
        self.remote_url = remote_url
        self.branch = branch
        self.base_env = base_env

    @classmethod
    def from_state(cls, state, base_env=None):
        g = state.get("git") or {}
        try:
            return cls(g["git_dir"], g["common_dir"], g["work_tree"], g["main_checkout"],
                       state["base_sha"], state.get("remote_url"), state.get("branch"), base_env=base_env)
        except KeyError as e:
            raise GitError(f"state.json lacks the recorded git field {e}") from None

    def state_fields(self):
        """The state.json fields this context was built from (`git` object + top-level keys)."""
        return {
            "git": {"git_dir": self.git_dir, "common_dir": self.common_dir,
                    "work_tree": self.work_tree, "main_checkout": self.main_checkout},
            "base_sha": self.base_sha, "remote_url": self.remote_url, "branch": self.branch,
        }

    def env(self):
        env = _base_env(self.base_env)
        env.update({"GIT_DIR": self.git_dir, "GIT_COMMON_DIR": self.common_dir,
                    "GIT_WORK_TREE": self.work_tree})
        return env

    def __repr__(self):
        return f"GitContext(work_tree={self.work_tree!r}, base_sha={self.base_sha[:12]}…, branch={self.branch!r})"


def _spawn(argv, env, cwd, input, timeout):
    if isinstance(input, str):
        input = input.encode("utf-8", "surrogateescape")
    try:
        return subprocess.run(argv, env=env, cwd=cwd, input=input,
                              stdin=None if input is not None else subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GitError(f"git {' '.join(argv[len(SAFE_CONFIG) + 1:])}: timed out after {timeout}s",
                       argv, None, "timeout") from None
    except OSError as e:
        raise GitError(f"git could not start: {e}", argv, None, str(e)) from None


def _run(ctx, args, input=None, check=True, timeout=TIMEOUT_S):
    """One pinned git call → CompletedProcess (bytes). Raises GitError when check and rc != 0,
    Tampered (before running) when the worktree's link files moved."""
    verify_pins(ctx)
    argv = ["git", *SAFE_CONFIG, *args]
    p = _spawn(argv, ctx.env(), ctx.work_tree, input, timeout)
    if check and p.returncode != 0:
        err = _decode(p.stderr).strip()
        raise GitError(f"git {' '.join(args)}: rc={p.returncode}: {err[:500]}", args, p.returncode, err)
    return p


def git(ctx, *args, input=None, check=True):
    """Run one pinned git command; return stdout (str). Raises GitError when check and rc != 0."""
    return _decode(_run(ctx, args, input=input, check=check).stdout)


def _git_bytes(ctx, *args, input=None):
    return _run(ctx, args, input=input).stdout


def _plain_git(cwd, args, base_env=None, timeout=TIMEOUT_S):
    """A git call before any GitContext exists (Issue start, trusted state). Hooks off."""
    env = _base_env(base_env)
    p = _spawn(["git", *SAFE_CONFIG, *args], env, cwd, None, timeout)
    if p.returncode != 0:
        err = _decode(p.stderr).strip()
        raise GitError(f"git {' '.join(args)}: rc={p.returncode}: {err[:500]}", args, p.returncode, err)
    return _decode(p.stdout).strip()


def _resolve_admin(path, common_dir):
    """The admin dir `<common>/worktrees/<name>` of a worktree the engine has JUST created
    (its gitfile has not been exposed to any role yet). Refuses anything outside."""
    gitfile = os.path.join(path, ".git")
    st = os.lstat(gitfile)
    import stat as _stat
    if not _stat.S_ISREG(st.st_mode):
        raise UnsafePath(f"{gitfile} is not a regular gitfile")
    with open(gitfile, encoding="utf-8") as f:
        line = f.read().strip()
    if not line.startswith("gitdir: "):
        raise GitError(f"{gitfile}: unexpected content")
    admin = line[len("gitdir: "):]
    if not os.path.isabs(admin):
        admin = os.path.join(path, admin)
    admin = os.path.realpath(admin)
    if os.path.dirname(admin) != os.path.join(common_dir, "worktrees"):
        raise GitError(f"worktree admin dir {admin} is not under {common_dir}/worktrees")
    return admin


def create_issue_worktree(main_checkout, worktree, branch, base_sha, remote="origin", base_env=None):
    """`git worktree add -b <branch> <worktree> <base_sha>` (hooks off) and return a GitContext.

    Also records, at this trusted moment, the absolute common dir, the new worktree's admin
    dir and the push URL of `remote` (state.json `git`, `remote_url` — S4). A missing remote
    or an unresolvable URL is an error, not a default.
    """
    _need_sha(base_sha, "base_sha")
    _need_branch(branch)
    main_checkout = os.path.realpath(_abspath(main_checkout, "main_checkout"))
    worktree = _abspath(worktree, "worktree")
    if os.path.lexists(worktree):
        raise GitError(f"worktree path already exists: {worktree}")
    common = _plain_git(main_checkout, ["rev-parse", "--path-format=absolute", "--git-common-dir"], base_env)
    common = os.path.realpath(common)
    got = _plain_git(main_checkout, ["rev-parse", "--verify", "--quiet", base_sha + "^{commit}"], base_env)
    if got != base_sha:
        raise GitError(f"base {base_sha} is not a commit of {main_checkout}")
    _plain_git(main_checkout, ["check-ref-format", "refs/heads/" + branch], base_env)
    url = _plain_git(main_checkout, ["remote", "get-url", "--push", remote], base_env)
    if not is_fixed_url(url):
        raise GitError(f"push URL of {remote!r} is not a fixed URL: {url!r}")
    _plain_git(main_checkout, ["worktree", "add", "-q", "-b", branch, worktree, base_sha], base_env)
    worktree = os.path.realpath(worktree)
    admin = _resolve_admin(worktree, common)
    ctx = GitContext(admin, common, worktree, main_checkout, base_sha, url, branch, base_env=base_env)
    if head(ctx) != base_sha:
        raise GitError("new worktree HEAD is not the base SHA")
    return ctx


def head(ctx):
    """HEAD SHA of the worktree."""
    sha = git(ctx, "rev-parse", "--verify", "HEAD^{commit}").strip()
    return _need_sha(sha, "HEAD")


def merge_base(ctx, head_sha):
    """merge-base(base_sha, head_sha) (S5)."""
    _need_sha(head_sha, "head_sha")
    sha = git(ctx, "merge-base", ctx.base_sha, head_sha).strip()
    return _need_sha(sha, "merge-base")


def _status_entries(ctx):
    """`status --porcelain=v1 -z` → [(xy, path, orig_path_or_None)], untracked included."""
    raw = _decode(_git_bytes(ctx, "-c", "status.relativePaths=false", "status", "--porcelain=v1", "-z",
                             "--untracked-files=all", "--ignore-submodules=none", "--no-renames"))
    out = []
    fields = raw.split("\0")
    i = 0
    while i < len(fields):
        f = fields[i]
        i += 1
        if not f:
            continue
        xy, path = f[:2], f[3:]
        orig = None
        if xy[0] in "RC" or xy[1] in "RC":
            orig = fields[i]
            i += 1
        out.append((xy, path, orig))
    return out


def tree_state(ctx):
    """{"clean": bool, "dirty_files": [...]} — tracked changes + untracked non-ignored files."""
    files = sorted({p for _, p, _ in _status_entries(ctx)})
    return {"clean": not files, "dirty_files": files}


_CHANGE = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied", "T": "type-changed"}


def _name_status(ctx, *args):
    """`diff --name-status -z -M` → [(change, path, from)]. Unknown status letters → GitError."""
    raw = _decode(_git_bytes(ctx, "diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z", "-M",
                             "--ignore-submodules=none", *args))
    fields = raw.split("\0")
    out = []
    i = 0
    while i < len(fields):
        st = fields[i]
        i += 1
        if not st:
            continue
        letter = st[0]
        if letter not in _CHANGE:
            raise GitError(f"unexpected diff status {st!r}")
        if letter in "RC":
            src, dst = fields[i], fields[i + 1]
            i += 2
            out.append((_CHANGE[letter], dst, src))
        else:
            out.append((_CHANGE[letter], fields[i], None))
            i += 1
    return out


def changed_files(ctx, head_sha):
    """facts.json `changed_files`: merge-base..HEAD (renames: both paths) + worktree + untracked."""
    mb = merge_base(ctx, head_sha)
    out = [{"path": p, "change": c, "from": f, "where": "committed"}
           for c, p, f in _name_status(ctx, mb, head_sha)]
    out += [{"path": p, "change": c, "from": f, "where": "worktree"}
            for c, p, f in _name_status(ctx, head_sha)]
    raw = _decode(_git_bytes(ctx, "ls-files", "-z", "--others", "--exclude-standard"))
    out += [{"path": p, "change": "added", "from": None, "where": "untracked"}
            for p in sorted(x for x in raw.split("\0") if x)]
    return out


def changed_between(ctx, old_sha, new_sha):
    """Paths changed between two commits (both rename paths) — §4.4-3 re-verification input."""
    _need_sha(old_sha, "old_sha")
    _need_sha(new_sha, "new_sha")
    paths = set()
    for _, p, f in _name_status(ctx, old_sha, new_sha):
        paths.add(p)
        if f:
            paths.add(f)
    return sorted(paths)


def commits_between(ctx, old_sha, new_sha):
    """[{sha, subject}] of old..new, oldest first."""
    return [{"sha": sha, "subject": msg.split("\n", 1)[0]} for sha, msg in _messages(ctx, old_sha, new_sha)]


def _messages(ctx, old_sha, new_sha):
    _need_sha(old_sha, "old_sha")
    _need_sha(new_sha, "new_sha")
    raw = _decode(_git_bytes(ctx, "log", "--no-color", "--reverse", "-z", "--format=%H%x00%B",
                             f"{old_sha}..{new_sha}"))
    fields = raw.split("\0")
    out = []
    for i in range(0, len(fields) - 1, 2):
        sha = fields[i].strip()
        if not sha:
            continue
        out.append((_need_sha(sha, "log sha"), fields[i + 1]))
    return out


def commit_messages(ctx, head_sha):
    """[(sha, full message)] of merge-base..HEAD, oldest first — the close-keyword input (S10)."""
    return _messages(ctx, merge_base(ctx, head_sha), head_sha)


def is_forward(ctx, old_sha, new_sha):
    """True when new_sha descends from old_sha (I7 re-entry fact)."""
    _need_sha(old_sha, "old_sha")
    _need_sha(new_sha, "new_sha")
    p = _run(ctx, ("merge-base", "--is-ancestor", old_sha, new_sha), check=False)
    if p.returncode == 0:
        return True
    if p.returncode == 1:
        return False
    raise GitError(f"merge-base --is-ancestor: rc={p.returncode}: {_decode(p.stderr).strip()}",
                   ("merge-base",), p.returncode, _decode(p.stderr))


def blob(ctx, rev, path):
    """(mode, sha, bytes) of `path` at `rev` via ls-tree + cat-file; None if absent.

    Control files (repo config, templates, role files, CLAUDE.md) are read ONLY this way
    from the recorded base SHA (S3); judge outputs only from the engine's commit (§7.6).
    `rev` must be a full SHA. A non-blob entry (directory, submodule) returns its mode and
    sha with `None` for the bytes; a symlink returns its target as bytes — callers check
    `is_regular_mode` before using the content.
    """
    _need_sha(rev, "rev")
    _need_relpath(path)
    raw = _decode(_git_bytes(ctx, "ls-tree", "-z", "--full-tree", rev, "--", path))
    entries = [e for e in raw.split("\0") if e]
    for e in entries:
        meta, _, name = e.partition("\t")
        if name != path:
            continue
        mode, typ, sha = meta.split()
        if typ != "blob":
            return (mode, sha, None)
        return (mode, sha, _git_bytes(ctx, "cat-file", "blob", sha))
    return None


def is_regular_mode(mode):
    """True for 100644 / 100755."""
    return mode in _REGULAR_MODES


def _check_regular_in_tree(ctx, path):
    """`path` (relative) is a regular file in the worktree, reached through real directories only."""
    _need_relpath(path)
    import stat as _stat
    cur = ctx.work_tree
    parts = path.split("/")
    for i, part in enumerate(parts):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            raise UnsafePath(f"{path}: does not exist in the worktree") from None
        last = i == len(parts) - 1
        if last and not _stat.S_ISREG(st.st_mode):
            raise UnsafePath(f"{path}: not a regular file")
        if not last and not _stat.S_ISDIR(st.st_mode):
            raise UnsafePath(f"{path}: parent {part!r} is not a real directory")


def commit_paths(ctx, paths, message):
    """Engine commit of exactly `paths` (`--no-verify`, hooksPath=/dev/null). Returns the new SHA.

    Each path must be a regular file in the worktree reached through real directories
    (UnsafePath otherwise). Other staged changes stay out of the commit (`--only`). When the
    files already equal HEAD, nothing is committed and the current HEAD is returned. The
    commit is re-read: touching any path outside `paths` is a GitError.
    """
    paths = list(paths)
    if not paths:
        raise GitError("commit_paths: no paths")
    for p in paths:
        _check_regular_in_tree(ctx, p)
    if not isinstance(message, str) or not message.strip():
        raise GitError("commit_paths: empty message")
    before = head(ctx)
    git(ctx, "add", "--", *paths)
    if _run(ctx, ("diff", "--cached", "--quiet", before, "--", *paths), check=False).returncode == 0:
        return before
    git(ctx, "commit", "-q", "--no-verify", "--only", "-m", message, "--", *paths)
    after = head(ctx)
    touched = [x for x in _decode(_git_bytes(ctx, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z",
                                             "--no-renames", before, after)).split("\0") if x]
    extra = sorted(set(touched) - set(paths))
    if extra:
        raise GitError(f"engine commit {after} touched paths outside the list: {extra}")
    return after


def _check_push_target(ctx):
    if not is_fixed_url(ctx.remote_url):
        raise GitError(f"recorded remote URL is not a fixed URL: {ctx.remote_url!r} (S4)")
    _need_branch(ctx.branch)
    git(ctx, "check-ref-format", "refs/heads/" + ctx.branch)


def push(ctx, head_sha):
    """Push `<head_sha>:refs/heads/<branch>` to the recorded URL with --no-verify, no force.

    Raises RemoteDiverged on a non-fast-forward refusal. The caller runs the §4.4-3 check
    and outbound.check_push_range first. Any other refusal (hook declined, protected
    branch) is a GitError. Returns the porcelain status flag (` ` fast-forward, `*` new
    branch, `=` already up to date).
    """
    _need_sha(head_sha, "head_sha")
    _check_push_target(ctx)
    ref = "refs/heads/" + ctx.branch
    p = _run(ctx, ("push", "--no-verify", "--porcelain", "--no-recurse-submodules", ctx.remote_url,
                   f"{head_sha}:{ref}"), check=False, timeout=NETWORK_TIMEOUT_S)
    out, err = _decode(p.stdout), _decode(p.stderr)
    flag = None
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) >= 3 and cols[1].endswith(":" + ref):
            flag, summary = cols[0], cols[2]
            break
    if flag == "!":
        if "non-fast-forward" in summary or "fetch first" in summary:
            raise RemoteDiverged(f"push of {head_sha[:12]} to {ref} refused: {summary}", err)
        raise GitError(f"push refused: {summary}: {err.strip()[:500]}", ("push",), p.returncode, err)
    if p.returncode != 0 or flag not in (" ", "*", "="):
        if "non-fast-forward" in err or "(fetch first)" in err:
            raise RemoteDiverged(f"push of {head_sha[:12]} to {ref} refused as non-fast-forward", err)
        raise GitError(f"push failed: rc={p.returncode} flag={flag!r}: {err.strip()[:500]}",
                       ("push",), p.returncode, err)
    return flag


def fetch(ctx):
    """`git fetch` from the recorded URL before a step that needs remote info (§7.6)."""
    _check_push_target(ctx)
    _run(ctx, ("fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
               ctx.remote_url, FETCH_REFSPEC), timeout=NETWORK_TIMEOUT_S)


class Diverged(GitError):
    """Stage 3 (E31): the remote Issue branch and the local one have both moved — `remote-diverged`."""


def fast_forward(ctx):
    """`resume --pr-review` (E31): fetch the recorded URL, then fast-forward the Issue worktree to the
    remote branch when the remote is strictly ahead (a human's commits). Returns
    {from, to, commits} or None (remote equal, behind, or missing). Never merges, never rewrites:
    both moved → Diverged; a dirty worktree → GitError (the engine never discards files). Hooks are
    off like every engine call (S4).
    """
    fetch(ctx)
    ref = "refs/remotes/origin/" + _need_branch(ctx.branch)
    p = _run(ctx, ("rev-parse", "--verify", "--quiet", ref + "^{commit}"), check=False)
    if p.returncode != 0:
        return None
    remote = _need_sha(_decode(p.stdout).strip(), "remote head")
    local = head(ctx)
    if remote == local or is_forward(ctx, remote, local):
        return None
    if not is_forward(ctx, local, remote):
        raise Diverged(f"remote {ctx.branch} {remote[:12]} and local {local[:12]} have diverged")
    if not tree_state(ctx)["clean"]:
        raise GitError("the Issue worktree is not clean — no fast-forward over uncommitted files")
    commits = len(_messages(ctx, local, remote))
    git(ctx, "merge", "--ff-only", "-q", "--no-edit", remote)
    if head(ctx) != remote:
        raise GitError("fast-forward did not reach the remote head")
    return {"from": local, "to": remote, "commits": commits}


# --- stage 4: the base of a sprint member (H6, H10, D1) ---------------------------------------------

def main_context(checkout, remote="origin", base_env=None):
    """A GitContext of a main checkout (no Issue worktree): its common dir, HEAD as the base, the push URL of
    `remote`. For the sprint supervisor, which reads objects and updates remote-tracking refs only."""
    checkout = os.path.realpath(_abspath(checkout, "checkout"))
    top = _plain_git(checkout, ["rev-parse", "--show-toplevel"], base_env)
    if os.path.realpath(top) != checkout:
        raise GitError(f"{checkout} is not the top of a git checkout (top: {top})")
    common = os.path.realpath(_plain_git(checkout, ["rev-parse", "--path-format=absolute", "--git-common-dir"], base_env))
    sha = _need_sha(_plain_git(checkout, ["rev-parse", "--verify", "HEAD^{commit}"], base_env), "HEAD")
    url = _plain_git(checkout, ["remote", "get-url", "--push", remote], base_env)
    if not is_fixed_url(url):
        raise GitError(f"push URL of {remote!r} is not a fixed URL: {url!r}")
    return GitContext(common, common, checkout, checkout, sha, url, None, base_env=base_env)


def fetch_branches(ctx, branches):
    """{branch: sha}: fetch exactly these branches into `refs/remotes/origin/<branch>` and read what arrived.
    No local branch, HEAD or FETCH_HEAD is touched. A missing branch or a failed fetch is a GitError."""
    if not is_fixed_url(ctx.remote_url):
        raise GitError(f"recorded remote URL is not a fixed URL: {ctx.remote_url!r} (S4)")
    for b in branches:
        _need_branch(b)
        git(ctx, "check-ref-format", "refs/heads/" + b)
    _run(ctx, ("fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head", ctx.remote_url,
               *(f"+refs/heads/{b}:refs/remotes/origin/{b}" for b in branches)), timeout=NETWORK_TIMEOUT_S)
    return {b: _need_sha(git(ctx, "rev-parse", "--verify", f"refs/remotes/origin/{b}^{{commit}}").strip(), b)
            for b in branches}


def remote_branch_sha(ctx, branch):
    """The sha of `branch` at the recorded URL, or None when it is not there (H10). Writes nothing."""
    if not is_fixed_url(ctx.remote_url):
        raise GitError(f"recorded remote URL is not a fixed URL: {ctx.remote_url!r} (S4)")
    ref = "refs/heads/" + _need_branch(branch)
    out = _decode(_run(ctx, ("ls-remote", "--heads", ctx.remote_url, ref), timeout=NETWORK_TIMEOUT_S).stdout)
    for line in out.splitlines():
        sha, _, name = line.partition("\t")
        if name == ref:
            return _need_sha(sha, "ls-remote")
    return None


def control_changes(ctx, base_sha, head_sha, issue):
    """D1: the control files (§7.6, for Issue `issue`) that differ between merge-base(base, head) and head — a
    stack base is read as trusted settings (S3), so there may be none. Sorted paths."""
    _need_sha(base_sha, "base_sha")
    _need_sha(head_sha, "head_sha")
    mb = _need_sha(git(ctx, "merge-base", base_sha, head_sha).strip(), "merge-base")
    out = set()
    for _, path, old in _name_status(ctx, mb, head_sha):
        for p in (path, old):
            try:
                if p and globs.is_control_file(p, issue):
                    out.add(p)
            except ValueError:
                out.add(p)                  # a path the rules cannot judge is never "unchanged"
    return sorted(out)


def diff_text(ctx, head_sha):
    """`git diff -a merge-base..HEAD` — the push scan input.

    `--no-renames` so a renamed file shows its whole content (the scan must see every line
    that leaves), `--no-ext-diff --no-textconv --no-color` so no configured program runs.
    """
    mb = merge_base(ctx, head_sha)
    return git(ctx, "diff", "-a", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
               "--ignore-submodules=none", f"{mb}..{head_sha}")


def review_diff_text(ctx, head_sha):
    """The review diff (in:review.diff): `diff_text` without `-a`, so a binary file is one
    "Binary files … differ" line (P5 real run: golden PNGs filled the review input with bytes).
    The push scan keeps `diff_text` (it must see every byte that leaves)."""
    mb = merge_base(ctx, head_sha)
    return git(ctx, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
               "--ignore-submodules=none", f"{mb}..{head_sha}")


def log_text(ctx, head_sha):
    """`git log --format=%an%n%ae%n%B merge-base..HEAD` — the push scan input (§7.6)."""
    mb = merge_base(ctx, head_sha)
    return git(ctx, "log", "--no-color", "--format=%an%n%ae%n%B", f"{mb}..{head_sha}")


def detached_worktree(ctx, path, sha):
    """`worktree add --detach <path> <sha>` and a GitContext pinned to it (same base, no push
    target). For the verify-gate temp tree and the I8 base run."""
    _need_sha(sha, "sha")
    path = _abspath(path, "path")
    if os.path.lexists(path):
        raise GitError(f"temporary worktree path already exists: {path}")
    git(ctx, "worktree", "add", "-q", "--detach", path, sha)
    path = os.path.realpath(path)
    admin = _resolve_admin(path, os.path.realpath(ctx.common_dir))
    return GitContext(admin, ctx.common_dir, path, ctx.main_checkout, ctx.base_sha, None, None,
                      base_env=ctx.base_env)


def temp_tree_for_gate(ctx, head_sha, path):
    """verify-gate (§2.1, F5): `worktree add --detach <path> <base>` + `read-tree -m -u <base> <head>`.

    <base> is merge-base(recorded base, head) (S5). Afterwards the temp tree's HEAD is the
    base, its index and files are `head_sha`'s tree, so `diff --cached` = base..head.
    Returns the GitContext of the temp tree (remove it with remove_worktree).
    """
    mb = merge_base(ctx, head_sha)
    tmp = detached_worktree(ctx, path, mb)
    try:
        git(tmp, "read-tree", "-m", "-u", mb, head_sha)
    except Exception:
        remove_worktree(ctx, tmp.work_tree)
        raise
    return tmp


def remove_worktree(ctx, path):
    """Remove a temporary worktree (verify-gate, I8 base run). Never the Issue worktree or the main checkout."""
    path = os.path.realpath(_abspath(path, "path"))
    if path in (os.path.realpath(ctx.work_tree), os.path.realpath(ctx.main_checkout)):
        raise GitError(f"refusing to remove {path}: it is the Issue worktree or the main checkout")
    git(ctx, "worktree", "remove", "--force", "--force", path)
