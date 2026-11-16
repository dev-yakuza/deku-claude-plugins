"""guildcore.roles.permissions — the role allow lists of §5.1 as data, rendered to CLI rules.

One table (`CLASSES`) is the single definition of the command classes C0–C4; the same table
renders the `permissions.allow` rules a role session runs under AND drives the offline
reclassifier (`workflows/dev/replay/permissions_check.py`, the port of `measure/allow3.py`) — so
the K1 matcher calibration (§10.2-3b item 2) compares the CLI's real decisions against a
prediction made from the very rules it was given.

Rule syntax: `Bash(<prefix>:*)` (prefix match, the form the CLI documents for `--allowedTools`);
mid-wildcard deny rules use the space form `Bash(gh api * -X *)` (§5.1 — calibrated in K1).
Paths in file rules are `//<absolute>` (absolute regardless of where the settings file sits).

`ALWAYS_DENY` is §5.1 "항상 금지" verbatim (CR-M6, INV1/INV3): every role, every mode, wins over
any allow. Nothing here ever emits `--dangerously-skip-permissions`.
"""

import os
import re

# ---- §5.1 command classes -------------------------------------------------------------------
C0_READ_SHELL = (
    "cd", "ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "sed", "awk", "jq", "sort",
    "uniq", "diff", "cmp", "stat", "file", "tr", "cut", "echo", "printf", "pwd", "which",
    "command", "date", "test", "[", "xxd", "od", "strings", "readlink", "realpath", "basename",
    "dirname", "mktemp", "sleep", "true", "false", "uptime",
)
# xargs is allowed only in front of a C0 reader (§5.1 "뒤 명령이 허용 부류일 때")
C0_XARGS = ("xargs grep", "xargs cat", "xargs wc", "xargs ls", "xargs head", "xargs rg",
            "xargs basename", "xargs dirname", "xargs stat", "xargs echo")
C0_DENY = ("Bash(find * -delete*)", "Bash(find * -exec *)", "Bash(find * -execdir *)",
           "Bash(find * -ok *)")
C1_GIT_READ = (
    "git status", "git diff", "git log", "git show", "git rev-parse", "git branch",
    "git ls-files", "git blame", "git grep", "git for-each-ref", "git merge-base", "git cat-file",
    "git describe", "git show-ref", "git ls-tree", "git reflog", "git rev-list",
    "git check-ignore", "git tag -l", "git tag --list", "git worktree list", "git config --get",
    "git remote -v", "git fetch",
)
C2_GH_READ = (
    "gh issue view", "gh issue list", "gh pr view", "gh pr list", "gh pr diff", "gh pr checks",
    "gh run view", "gh run list",
)
# §5.1's fallback, taken (K1 calibration): the mid-wildcard denies do NOT cover the flag-first
# and `=` forms (`gh api -X POST …`, `gh api … --method=POST`, `-fa=b`, `--field=a=b` were
# allowed by CLI 2.1.311), so `gh api` is not in C2 — the engine gives roles gh data as input
# files. The denies below stay as defence for a human-approved `role_allow` that adds it.
GH_API_DENY_EXTRA = (
    "Bash(gh api -X*)", "Bash(gh api * -X*)", "Bash(gh api --method*)", "Bash(gh api * --method*)",
    "Bash(gh api -f*)", "Bash(gh api * -f*)", "Bash(gh api -F*)", "Bash(gh api * -F*)",
    "Bash(gh api --field*)", "Bash(gh api * --field*)", "Bash(gh api --raw-field*)",
    "Bash(gh api * --raw-field*)", "Bash(gh api --input*)", "Bash(gh api * --input*)",
)
C3_WORKTREE_WRITE = (
    "mkdir", "cp", "mv", "touch", "rm", "chmod", "sed -i", "perl -pi", "perl -0pi", "tee",
    "python3 -c", "python3 -", "python -c", "git add", "git commit", "git switch", "git restore",
    "git checkout", "git stash push", "git stash pop", "git stash list", "git stash", "git mv",
    "git rm", "git apply",
)
# C4 = repo toolchain: config.commands.* + manifest detection + tracked scripts + wrappers
C4_WRAPPERS = ("timeout", "xvfb-run")
MANIFEST_TOOLS = (
    ("pubspec.yaml", ("flutter", "dart", "fvm")),
    ("package.json", ("npm", "npx", "pnpm", "yarn")),
    ("pyproject.toml", ("pytest", "python -m", "python3 -m", "uv")),
    ("setup.cfg", ("pytest", "python -m", "python3 -m")),
    ("go.mod", ("go",)),
    ("Cargo.toml", ("cargo",)),
    ("Makefile", ("make",)),
    ("lefthook.yml", ("lefthook run",)),
)
SCRIPT_DIRS = ("scripts", "tool", "tools", "bin")

# ---- §5.1 항상 금지 (verbatim) --------------------------------------------------------------
ALWAYS_DENY = (
    "Bash(gh pr merge:*)", "Bash(gh pr close:*)", "Bash(gh pr create:*)", "Bash(gh pr edit:*)",
    "Bash(gh pr comment:*)", "Bash(gh issue close:*)", "Bash(gh issue edit:*)",
    "Bash(gh issue comment:*)", "Bash(gh issue create:*)",
    "Bash(gh api * -X *)", "Bash(gh api * --method *)", "Bash(gh api * -f *)",
    "Bash(gh api * -F *)", "Bash(gh api * --field *)", "Bash(gh api * --raw-field *)",
    "Bash(gh api * --input *)",
    "Bash(git push:*)", "Bash(git reset --hard:*)", "Bash(git rebase:*)",
    "Bash(git filter-branch:*)", "Bash(git checkout -B:*)", "Bash(git checkout -- .:*)",
    "Bash(git restore .:*)", "Bash(git branch -D:*)", "Bash(git clean -f:*)",
    "Bash(git stash drop:*)", "Bash(git stash clear:*)", "Bash(rm -rf /:*)", "Bash(rm -rf ~:*)",
    "Bash(env)", "Bash(printenv:*)", "Agent", "Task", "AskUserQuestion",
)
# Tools the CLI would otherwise offer a role session; never part of a role's job.
DISALLOWED_TOOLS = ("Agent", "Task", "AskUserQuestion")

# ---- §5.1 역할별 허용 -------------------------------------------------------------------------
# (classes, file-tool write scope kind, may run C4 for investigation)
ROLE_CLASSES = {
    "developer": ("C0", "C1", "C2", "C3", "C4"),
    "explorer": ("C0", "C1", "C2"),
    "tech-lead-design": ("C0", "C1", "C2", "C4"),
    "tester-cases": ("C0", "C1", "C2"),
    "tester-verify": ("C0", "C1", "C2", "C4"),
    "tech-lead-review": ("C0", "C1", "C2", "C4"),
    "performance": ("C0", "C1", "C2", "C4"),
    "reviewer": ("C0", "C1", "C2"),                 # 3.5b gate roles, designer gate, PO
    "tech-writer": ("C0", "C1", "C2"),
    "qa": ("C0", "C1", "C2", "C3", "C4"),
    "auditor": (),                                  # Read, Grep, Glob only
    "judge": (),
}
READ_TOOLS = ("Read", "Grep", "Glob")


def role_key(role, task=None):
    """Map (role, task) to a ROLE_CLASSES key."""
    if role in ("developer", "explorer", "qa", "auditor", "judge", "performance", "tech-writer"):
        return role
    if role == "tech-lead":
        return "tech-lead-design" if task in ("design", None) else "tech-lead-review"
    if role == "tester":
        return "tester-cases" if task in ("cases", None) else "tester-verify"
    return "reviewer"


def _bash(prefix):
    return "Bash(%s:*)" % prefix


def toolchain_prefixes(repo_root, commands=None, local_developer=None, tracked_files=None):
    """C4 prefixes for one repo: config.commands.* (+ local_developer test/lint), manifest
    detection, tracked executables under scripts/ tool/ tools/ bin/, wrappers. `tracked_files`
    = `git ls-files` output lines (None → scan nothing)."""
    out = list(C4_WRAPPERS)
    for key in ("test", "lint", "vrt", "e2e", "format", "build"):
        for cmd in _as_list((commands or {}).get(key)):
            p = _cmd_prefix(cmd)
            if p:
                out.append(p)
    for key in ("test_cmd", "lint_cmd"):
        p = _cmd_prefix((local_developer or {}).get(key))
        if p:
            out.append(p)
    for manifest, tools in MANIFEST_TOOLS:
        if repo_root and os.path.exists(os.path.join(repo_root, manifest)):
            out.extend(tools)
    for f in tracked_files or ():
        top = f.split("/", 1)[0]
        if top in SCRIPT_DIRS and "/" in f:
            full = os.path.join(repo_root or "", f)
            if repo_root is None or os.access(full, os.X_OK):
                out.append(f)
                out.append("./" + f)
    seen, res = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            res.append(p)
    return res


def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _cmd_prefix(cmd):
    """The leading words of a configured command that make a stable rule prefix: the executable
    plus a subcommand word (`flutter test`, `npm run test`), never arguments that vary."""
    if not cmd or not isinstance(cmd, str):
        return None
    words = cmd.strip().split()
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words = words[1:]
    if not words:
        return None
    keep = [words[0]]
    for w in words[1:3]:
        if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_:-]*$", w):
            break
        keep.append(w)
    return " ".join(keep)


def bash_prefixes(classes, toolchain=()):
    out = []
    if "C0" in classes:
        out += list(C0_READ_SHELL) + list(C0_XARGS)
    if "C1" in classes:
        out += list(C1_GIT_READ)
    if "C2" in classes:
        out += list(C2_GH_READ)
    if "C3" in classes:
        out += list(C3_WORKTREE_WRITE)
    if "C4" in classes:
        out += list(toolchain)
    return out


def role_rules(role, task=None, run_dir=None, worktree=None, issue=None, toolchain=(),
               extra_allow=()):
    """(allow, deny) rule lists for one role session (§5.1). `extra_allow` =
    `config.engine.role_allow.<role>` patterns a human approved."""
    key = role_key(role, task)
    classes = ROLE_CLASSES[key]
    allow = [_bash(p) for p in bash_prefixes(classes, toolchain)]
    allow += list(READ_TOOLS)
    deny = list(ALWAYS_DENY) + [d for d in GH_API_DENY_EXTRA if d not in ALWAYS_DENY]
    if "C0" in classes:
        deny += list(C0_DENY)
    if "C3" not in classes:
        # a reader's `sed` must not edit in place (C0 excludes -i)
        deny += ["Bash(sed -i:*)", "Bash(sed * -i *)", "Bash(sed * -i)"]
    if key == "developer":
        # path-scoped, not bare: the CLI checks a shell redirect target against Edit/Write PATH
        # rules (K1 calibration — a bare `Write` did not allow `echo x > f`), and a developer
        # has no business writing outside its worktree
        if worktree:
            w = _abs(worktree)
            allow += ["Edit(//%s/**)" % w, "Write(//%s/**)" % w, "NotebookEdit(//%s/**)" % w]
        else:
            allow += ["Edit", "Write", "NotebookEdit"]
    elif key == "qa" and worktree:
        allow += ["Edit(//%s/test/**)" % _abs(worktree), "Write(//%s/test/**)" % _abs(worktree),
                  "Edit(//%s/integration_test/**)" % _abs(worktree),
                  "Write(//%s/integration_test/**)" % _abs(worktree)]
    elif key == "tester-cases" and worktree and issue is not None:
        p = "//%s/docs/specs/%s/test-cases.md" % (_abs(worktree), issue)
        allow += ["Edit(%s)" % p, "Write(%s)" % p]
    elif key == "tech-writer" and worktree:
        allow += ["Edit(//%s/docs/**)" % _abs(worktree), "Write(//%s/docs/**)" % _abs(worktree)]
    if run_dir:
        r = _abs(run_dir)
        allow += ["Read(//%s/in/**)" % r, "Write(//%s/out/**)" % r, "Edit(//%s/out/**)" % r]
    if key == "auditor":
        allow = list(READ_TOOLS) + (["Read(//%s/in/**)" % _abs(run_dir)] if run_dir else [])
    allow += [p for p in extra_allow if p not in allow]
    return allow, deny


def _abs(p):
    return os.path.abspath(p).lstrip("/")


def summary(role, task=None, toolchain=()):
    """The one-paragraph "allowed commands" summary every task.md carries (§5.1 task.md), so the
    role works inside its list from the start."""
    key = role_key(role, task)
    classes = ROLE_CLASSES[key]
    if not classes:
        return ("You may use only the Read, Grep and Glob tools; no shell commands are available. "
                "Your inputs are files under your run directory's in/.")
    parts = []
    if "C0" in classes:
        parts.append("read-only shell (ls, cat, head, grep, rg, find without -delete/-exec, sed "
                     "without -i, awk, jq, sort, diff, …)")
    if "C1" in classes:
        parts.append("read-only git (status, diff, log, show, rev-parse, ls-files, grep, fetch, …)")
    if "C2" in classes:
        parts.append("gh reads (issue/pr view·list, pr diff·checks, run view·list; no gh api)")
    if "C3" in classes:
        parts.append("worktree writes (mkdir, cp, mv, rm, sed -i, python3 -c, git add/commit/"
                     "switch/restore/stash)")
    if "C4" in classes and toolchain:
        parts.append("the repo toolchain (%s)" % ", ".join(toolchain[:12]))
    return ("Allowed shell commands: %s. Never push, merge, create or edit PRs/Issues, comment, "
            "rebase, reset --hard, print the environment, or start sub-agents — the engine does "
            "those. A command outside this list is refused without a prompt; if you need one, "
            "return BLOCKED: permission — <command>." % "; ".join(parts))


def normalized_prefix(command, words=2):
    """The first `words` words of a denied command — the unit `dev denials` counts (§5.1 4)."""
    ws = (command or "").split()
    while ws and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", ws[0]):
        ws = ws[1:]
    return " ".join(ws[:words])


def suggest_role_allow(denials, min_issues=2, min_count=3):
    """§5.1 거부 4 (학습): `denials` = [{issue, role, command, cls}] from the journals. A normalized
    prefix outside the forbidden class denied ≥3 times across ≥2 Issues becomes a
    `config.engine.role_allow.<role>` SUGGESTION (a human approves; never applied here)."""
    agg = {}
    for d in denials:
        if d.get("cls") == "forbidden":
            continue
        key = (d.get("role"), normalized_prefix(d.get("command")))
        n, issues = agg.get(key, (0, set()))
        issues.add(d.get("issue"))
        agg[key] = (n + 1, issues)
    out = []
    for (role, pfx), (n, issues) in sorted(agg.items()):
        if pfx and n >= min_count and len(issues) >= min_issues:
            out.append({"role": role, "pattern": "Bash(%s:*)" % pfx, "count": n, "issues": len(issues)})
    return out
