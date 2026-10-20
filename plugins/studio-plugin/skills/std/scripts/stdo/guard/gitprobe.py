"""The guard's only child processes (m0d1b-plan §6.5.1): `git clean -n` previews and plumbing diffs.

Hardened: no fsmonitor, hooks, pager, external diff or textconv; stdin /dev/null; timeouts. Any
failure is reported as None and the caller denies (closed side).
"""

import os
import shutil
import subprocess

TIMEOUT = 5.0
TOTAL = 8.0
SAFE = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.pager=cat",
        "-c", "diff.external=", "-c", "core.untrackedCache=false", "--no-pager"]
UNSAFE_CONFIG = ("core.fsmonitor", "core.hookspath", "core.sshcommand", "core.editor", "diff.external",
                 "core.pager", "core.askpass", "credential.helper", "core.gitproxy", "uploadpack.packobjectshook")


class Probe(object):
    def __init__(self, env, budget=TOTAL, runner=None):
        self.env = dict(env)
        for k in list(self.env):
            # the user's repository selection and injected config never reach a preview; the command's own
            # GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE are passed per call (judge.git_target)
            if k in ("GIT_EXTERNAL_DIFF", "GIT_PAGER", "PAGER", "GIT_ASKPASS", "SSH_ASKPASS", "GIT_SSH_COMMAND",
                     "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_CONFIG_COUNT",
                     "GIT_CONFIG_PARAMETERS") or k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
                del self.env[k]
        self.env["GIT_OPTIONAL_LOCKS"] = "0"
        self.env["LC_ALL"] = "C"
        self.env["GIT_TERMINAL_PROMPT"] = "0"
        self.left = budget
        self.calls = 0
        self.runner = runner or subprocess.run
        self.git = shutil.which("git", path=self.env.get("PATH")) or ("/usr/bin/git" if os.path.exists("/usr/bin/git") else None)

    def run(self, cwd, args, pre=(), env=None, ok_codes=(0,)):
        """stdout text, or None (failure, timeout, no git, budget spent)."""
        if self.git is None or cwd is None or self.left <= 0 or self.calls >= 6:
            return None
        self.calls += 1
        t = min(TIMEOUT, self.left)
        import time
        start = time.monotonic()
        try:
            run_env = dict(self.env)
            run_env.update(env or {})
            out = self.runner([self.git] + SAFE + list(pre) + list(args), cwd=cwd, env=run_env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=t)
        except (OSError, subprocess.SubprocessError):
            return None
        finally:
            self.left -= time.monotonic() - start
        if out.returncode not in ok_codes:
            return None
        return out.stdout if out.returncode == 0 else ""

    def clean_preview(self, cwd, configs, args, pre=(), env=None):
        """Paths `git clean` would remove (absolute), or None."""
        cfg = []
        for k, v in configs:
            cfg += ["-c", "%s=%s" % (k, v)]
        keep = []
        skip_value = False
        for a in args:
            if skip_value:
                keep.append(a)
                skip_value = False
                continue
            if a in ("-f", "--force", "-i", "--interactive", "-ff"):
                continue
            if a in ("-e", "--exclude"):
                keep.append(a)
                skip_value = True
                continue
            if a.startswith("-") and not a.startswith("--"):
                # a short-option cluster: drop f/i before an attached -e value, keep the value untouched
                head, sep, tail = a[1:].partition("e")
                head = head.replace("f", "").replace("i", "")
                a = "-" + head + sep + tail if (head or sep) else ""
                if not a:
                    continue
                if sep and not tail:
                    skip_value = True
            keep.append(a)
        out = self.run(cwd, cfg + ["-c", "core.quotePath=false", "clean", "-n"] + keep, pre=pre, env=env)
        if out is None:
            return None
        paths = []
        for line in out.splitlines():
            if line.startswith("Would remove "):
                p = line[len("Would remove "):]
                paths.append(os.path.normpath(os.path.join(cwd, p)))
        return paths

    def is_rev(self, cwd, name, pre=(), env=None):
        """True / False whether `name` names a commit; None when it cannot be checked."""
        out = self.run(cwd, ["rev-parse", "--verify", "-q", "--end-of-options", name + "^{commit}"], pre=pre, env=env,
                       ok_codes=(0, 1))
        if out is None:
            return None
        return bool(out.strip())

    def studio_changes(self, cwd, pathspecs, pre=(), env=None):
        """Uncommitted (staged, unstaged, or untracked before the first commit) paths under pathspecs.
        Note: diff-index may run the repository's own filter.<driver>.clean for racily-clean files; the
        guard accepts that (a filter configured in the repository runs on every `git status` too)."""
        # pathspecs are relative to the work-tree root whatever the command's cwd (`:(top)` magic)
        pathspecs = [p if p.startswith(":") else ":(top)" + p for p in pathspecs]
        head = self.run(cwd, ["rev-parse", "--verify", "-q", "HEAD"], pre=pre, env=env, ok_codes=(0, 1))
        if head is None:
            return None
        if head.strip():
            a = self.run(cwd, ["diff-index", "--name-only", "--no-ext-diff", "--no-textconv", "HEAD", "--"] + pathspecs,
                         pre=pre, env=env)
            b = self.run(cwd, ["diff-index", "--cached", "--name-only", "--no-ext-diff", "--no-textconv", "HEAD", "--"]
                         + pathspecs, pre=pre, env=env)
            if a is None or b is None:
                return None
            return sorted(set(x for x in (a + b).splitlines() if x))
        a = self.run(cwd, ["ls-files", "--others", "--exclude-standard", "--"] + pathspecs, pre=pre, env=env)
        b = self.run(cwd, ["ls-files", "--cached", "--"] + pathspecs, pre=pre, env=env)
        if a is None or b is None:
            return None
        return sorted(set(x for x in (a + b).splitlines() if x))


def unsafe(gitinfo):
    """Options that would make a preview run something: deny without previewing."""
    for k, _v in gitinfo.configs:
        kl = (k or "").lower()
        if kl in UNSAFE_CONFIG or kl.startswith("alias."):
            return k
    return None
