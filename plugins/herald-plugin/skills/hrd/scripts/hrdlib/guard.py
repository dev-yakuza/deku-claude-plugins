"""PreToolUse guard (plan §3.4). Installed by `init` into `.claude/settings.json` as
`python3 "${CLAUDE_PROJECT_DIR}/.claude/herald/scripts/guard.py"` for Bash and Edit/Write.

Decision table (attended → `ask`, unattended `HRD_UNATTENDED=1` → `deny`):
- criteria files, critique/verify personas, protected config keys, guard wiring, the ledger
- `gh pr merge` (unattended: allowed only for auto + --match-head-commit + PR in HRD_AUTO_PRS)
- the deploy command
- base-branch commits that touch Herald paths outside the allowed set (unattended: any
  base commit or push) and herald/* commits outside the PR file scope.

It is a string-pattern tripwire, not a boundary (plan §3.4 "한계"); `audit` checks after the fact.
"""

import json
import os
import re
import shlex
import sys

from . import commits
from .config import Config
from .store import load_published, load_topics, parse_branch
from .util import git, read_json

CRITERIA = [
    "docs/editorial/charter.md", "docs/editorial/exemplars.md", "docs/editorial/sources.md",
    "docs/editorial/style-guide.md", "docs/editorial/promotion.md",
    "docs/editorial/search-checklist.md", "docs/editorial/gate-rules.json",
    "docs/editorial/categories/*",
]
PERSONAS = [".claude/agents/editor.md", ".claude/agents/fact-checker.md", ".claude/agents/subject-expert.md"]
WIRING = [".claude/settings.json", ".claude/settings.local.json", ".claude/herald/scripts/*",
          ".claude/herald/scripts/**"]
LEDGER = [".claude/herald/ledger/*", ".claude/herald/ledger/**"]
CONFIG = ".claude/herald/config.json"
PROTECTED_CONFIG_KEYS = ("autonomy", "budget", "commands", "paths", "base_branch", "roles", "models")
HERALD_PERSONAS = [
    ".claude/agents/editor-in-chief.md", ".claude/agents/content-strategist.md",
    ".claude/agents/researcher.md", ".claude/agents/writer.md", ".claude/agents/fact-checker.md",
    ".claude/agents/editor.md", ".claude/agents/subject-expert.md",
    ".claude/agents/search-discovery.md", ".claude/agents/illustrator.md",
    ".claude/agents/translator.md", ".claude/agents/distributor.md",
]


def unattended():
    return os.environ.get("HRD_UNATTENDED") == "1"


def decide(kind, reason):
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": kind,
                                  "permissionDecisionReason": "Herald guard: " + reason}}
    print(json.dumps(out, ensure_ascii=False))
    if kind == "deny":
        sys.stderr.write("Herald guard blocked: %s\n" % reason)
    sys.exit(0)


def protect(reason):
    decide("deny" if unattended() else "ask", reason)


def rel(root, path):
    if not path:
        return ""
    p = os.path.join(root, path) if not os.path.isabs(path) else path
    p = os.path.realpath(p)
    try:
        r = os.path.relpath(p, os.path.realpath(root))
    except ValueError:
        return path
    return r.replace(os.sep, "/")


def _covers(r, globs):
    """r matches a glob, or r is a directory that contains protected paths (`cp -r x .claude/herald/scripts`)."""
    if commits._match(r, globs):
        return True
    r = r.rstrip("/")
    return bool(r) and any(g.startswith(r + "/") for g in globs)


def classify_path(r):
    if commits._match(r, CRITERIA):
        return "criteria file %s" % r
    if r in PERSONAS:
        return "critique/verify persona %s" % r
    if _covers(r, WIRING):
        return "guard wiring %s" % r
    if _covers(r, LEDGER):
        return "verification ledger %s" % r
    return None


def config_change_protected(root, ti, tool):
    path = os.path.join(root, CONFIG)
    try:
        cur_text = open(path, encoding="utf-8").read()
    except OSError:
        cur_text = "{}"
    try:
        cur = json.loads(cur_text)
    except ValueError:
        return True
    if tool == "Write":
        new_text = ti.get("content", "")
    elif tool in ("Edit", "MultiEdit"):
        new_text = cur_text
        edits = ti.get("edits") or [{"old_string": ti.get("old_string", ""), "new_string": ti.get("new_string", ""),
                                     "replace_all": ti.get("replace_all", False)}]
        for e in edits:
            if e.get("replace_all"):
                new_text = new_text.replace(e.get("old_string", ""), e.get("new_string", ""))
            else:
                new_text = new_text.replace(e.get("old_string", ""), e.get("new_string", ""), 1)
    else:
        return True
    try:
        new = json.loads(new_text)
    except ValueError:
        return True
    return any(cur.get(k) != new.get(k) for k in PROTECTED_CONFIG_KEYS)


def herald_article_paths(root, cfg):
    slugs = set()
    try:
        for a in load_published(root)["articles"]:
            if a.get("origin") == "herald":
                slugs.add(a["slug"])
        for t in load_topics(root)["topics"]:
            if t.get("slug"):
                slugs.add(t["slug"])
    except Exception:
        pass
    globs = []
    for s in slugs:
        globs += [cfg.body_path(s), cfg.image_dir(s) + "/*", cfg.image_dir(s) + "/**"]
    return globs


def jurisdiction(root, cfg):
    return herald_article_paths(root, cfg) + [".claude/herald/*", ".claude/herald/**",
                                              "docs/editorial/*", "docs/editorial/**"] + HERALD_PERSONAS


def current_branch(root):
    return git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()


def staged_after(root, argv, pending=()):
    """What this commit will contain: the index now, paths earlier segments of the same command
    stage (`git add x && git commit`), the commit's own pathspecs, and `-a`."""
    staged = set(commits.staged_paths(root)) | set(pending)
    rest = argv[2:]
    if "--" in rest:
        specs = rest[rest.index("--") + 1:]
    else:
        specs, skip = [], False
        for x in rest:
            if skip:
                skip = False
                continue
            if x in ("-m", "--message", "-F", "--file", "-C", "-c", "--author", "--date", "--trailer",
                     "--fixup", "--squash", "--cleanup", "-t", "--template"):
                skip = True
                continue
            if re.match(r"^-[a-zA-Z]+$", x) and x[-1] in "mFCct":  # combined short options: `-am msg`
                skip = True
                continue
            if not x.startswith("-"):
                specs.append(x)
    if specs:
        staged |= set(git_pathspec_paths(root, specs))
    if any(a in ("-a", "--all") or (a.startswith("-") and not a.startswith("--") and "a" in a[1:]) for a in argv):
        staged |= {p for p in git(root, "diff", "--name-only", "-z").split("\0") if p}
    return sorted(staged)


def check_edit(root, cfg, tool, ti):
    r = rel(root, ti.get("file_path") or ti.get("notebook_path") or "")
    what = classify_path(r)
    if what:
        protect("editing the %s changes Herald's verification baseline or enforcement." % what)
    if r == CONFIG and config_change_protected(root, ti, tool):
        protect("changing protected config keys (%s)." % ", ".join(PROTECTED_CONFIG_KEYS))


def segments(cmd):
    return [s.strip() for s in re.split(r"&&|\|\||;|\n|\|", cmd) if s.strip()]


GIT_GLOBAL_WITH_VALUE = ("-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                         "--super-prefix", "--attr-source")
PUSH_OPTS_WITH_VALUE = ("-o", "--push-option", "--repo", "--receive-pack", "--exec")


def normalize(seg, split=True):
    """argv with git's global options removed (before splitting `=`, so a value never becomes
    the subcommand), then — unless split=False — `--opt=value` split into two tokens."""
    try:
        argv = shlex.split(seg)
    except ValueError:
        argv = seg.split()
    if argv and argv[0] == "git":
        i = 1
        while i < len(argv) and argv[i].startswith("-"):
            opt = argv[i]
            i += 2 if opt in GIT_GLOBAL_WITH_VALUE else 1  # `--opt=value` is one token here
        argv = ["git"] + argv[i:]
    if not split:
        return argv
    return [x for a in argv for x in (a.split("=", 1) if a.startswith("--") and "=" in a else [a])]


def contains(hay, needle):
    n = len(needle)
    return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


TRIVIAL = {"echo", "tee", "true", ":", "printf", "cat", "sleep", "cd"}


def deploy_signatures(deploy):
    """Publishing steps of the configured deploy string: split on `&&`/`;`/pipes, drop env
    assignments, redirections, trivial commands (echo, tee, …) and build/test/lint steps —
    normalized like the commands we inspect."""
    sigs = []
    for part in re.split(r"&&|\|\||;|\n", deploy or ""):
        for member in part.split("|"):  # `echo y | vercel --prod`: the publisher is after the pipe
            argv = strip_noise(normalize(member.strip()))
            if argv and argv[0] not in TRIVIAL and not (set(argv) & BUILD_WORDS):
                sigs.append(argv)
    if not sigs and (deploy or "").strip():
        last = [x for x in segments(deploy) if x]
        sigs = [strip_noise(normalize(last[-1]))] if last else []
    # every publishing step (build/test/lint steps excluded) — a later notify step must not hide
    # the real deploy step
    return [x for x in sigs if x]


def git_pathspec_paths(root, specs, everything=False):
    """Changed (tracked or untracked-not-ignored) paths a `git add/rm/commit <specs>` would take."""
    if everything:  # name-only lists (no rename records to mis-parse)
        changed = git(root, "diff", "--name-only", "-z", "HEAD", check=False).split("\0")
        untracked = git(root, "ls-files", "-z", "--others", "--exclude-standard", check=False).split("\0")
        return sorted({p for p in changed + untracked if p})
    if not specs:
        return []
    tracked = git(root, "diff", "--name-only", "-z", "HEAD", "--", *specs, check=False).split("\0")
    untracked = git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", *specs, check=False).split("\0")
    return sorted({p for p in tracked + untracked if p})


def other_git_dir(root, seg):
    """True when `git -C <dir>` / `--git-dir` points at another repository."""
    try:
        raw = shlex.split(seg)
    except ValueError:
        raw = seg.split()
    for i, a in enumerate(raw[1:], 1):
        if not a.startswith("-"):
            break
        val = None
        if a in ("-C", "--git-dir") and i + 1 < len(raw):
            val = raw[i + 1]
        elif a.startswith("--git-dir="):
            val = a.split("=", 1)[1]
        if val:
            d = os.path.join(root, val)
            d = d if os.path.isdir(d) else os.path.dirname(d)
            top = git(d, "rev-parse", "--show-toplevel", check=False).strip() if os.path.isdir(d) else ""
            # unknown → same repository (fail closed)
            if top and os.path.realpath(top) != os.path.realpath(root):
                return True
    return False


def resets_history(args):
    """`git reset -- <paths>` only unstages; --hard/--soft/--mixed/--merge/--keep or a commit moves HEAD."""
    if any(a in ("--hard", "--soft", "--mixed", "--merge", "--keep") for a in args):
        return True
    before = args[:args.index("--")] if "--" in args else args
    return any(not a.startswith("-") for a in before)


REDIR_RE = re.compile(r"^(\d*|&)(>>?|<)(.*)$")
BUILD_WORDS = {"build", "test", "lint", "typecheck", "check", "install", "ci", "format", "prebuild"}


def strip_noise(argv):
    """Drop leading VAR=value assignments and redirections (operator + target, attached or not)."""
    out, i = [], 0
    while i < len(argv) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[i]) and not out:
        i += 1
    while i < len(argv):
        m = REDIR_RE.match(argv[i])
        if m:
            i += 1 if m.group(3) else 2
            continue
        out.append(argv[i])
        i += 1
    return out


def write_targets(seg):
    """Paths a shell segment writes: redirection targets and the target arguments of common
    file-writing commands. Executing a protected script (`python3 .claude/herald/scripts/hrd.py
    ... 2>&1`) is not a write to it."""
    try:
        raw = shlex.split(seg)
    except ValueError:
        raw = seg.split()
    out = []
    for i, a in enumerate(raw):
        m = REDIR_RE.match(a)
        if m and m.group(2) in (">", ">>"):
            tgt = m.group(3) or (raw[i + 1] if i + 1 < len(raw) else "")
            if tgt and not tgt.startswith("&") and tgt != "/dev/null":
                out.append(tgt)
    argv = strip_noise(raw)
    if not argv:
        return out
    cmd, args = os.path.basename(argv[0]), [x for x in argv[1:] if not x.startswith("-")]
    if cmd in ("tee", "rm", "mv", "truncate", "shred", "unlink", "rmdir", "touch"):
        out += args
    elif cmd in ("cp", "ln", "install", "rsync") and args:
        out.append(args[-1])
    elif cmd in ("sed", "perl") and any(x.startswith("-i") or x.startswith("-pi") for x in argv[1:]):
        out += args[1:] if cmd == "sed" else args
    elif cmd == "chmod" and len(args) > 1:
        out += args[1:]
    elif cmd == "dd":
        out += [x[3:] for x in argv[1:] if x.startswith("of=")]
    elif cmd.startswith("python") and "-c" in argv and re.search(r"open\([^)]*['\"][wa]|write_text", seg):
        out += [x for x in raw if "/" in x or "." in x]
    return out


def switch_target(root, argv):
    """Branch a `git switch|checkout` segment moves to, or None (path checkouts move nowhere)."""
    rest = argv[2:]
    for i, a in enumerate(rest):
        if a in ("-c", "-C", "-b", "-B", "--orphan") and i + 1 < len(rest):
            return rest[i + 1]
    if "--" in rest:
        return None
    names = [a for a in rest if not a.startswith("-")]
    if not names:
        return None
    ref = names[0]
    if argv[1] == "switch" or git(root, "rev-parse", "--verify", "-q", "refs/heads/" + ref, check=False).strip() \
            or git(root, "rev-parse", "--verify", "-q", "refs/remotes/origin/" + ref, check=False).strip():
        return ref
    return None


def push_targets(argv):
    """(remote, refspecs) of a `git push ...` argv NOT split on `=` (a `--opt=value` stays one
    token and is skipped; only the separated forms of value options consume a value)."""
    pos, i = [], 2
    while i < len(argv):
        a = argv[i]
        if a in PUSH_OPTS_WITH_VALUE:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        pos.append(a)
        i += 1
    return (pos[0] if pos else None), pos[1:]


def check_bash(root, cfg, cmd):
    base = cfg.base
    sigs = deploy_signatures((cfg.get("commands", "deploy") or "").strip())
    pending = set()  # paths earlier `git add/rm/mv` segments of this same command will stage
    branch = current_branch(root)  # updated by switch/checkout segments
    for seg in segments(cmd):
        argv = normalize(seg)
        if not argv:
            continue
        joined = " ".join(argv)
        if argv[:2] == ["gh", "api"] and re.search(r"/pulls/\d+/merge\b", joined):
            argv = ["gh", "pr", "merge"] + re.findall(r"/pulls/(\d+)/merge", joined)  # same rules as a merge
        # 1. merges
        if argv[:3] == ["gh", "pr", "merge"]:
            if not unattended():
                decide("ask", "merging a PR publishes content — confirm this is the approved `ship` step.")
            if cfg.get("autonomy", "publish") != "auto":
                decide("deny", "unattended runs may not merge while autonomy.publish=approve.")
            allowed = set((os.environ.get("HRD_AUTO_PRS") or "").replace(",", " ").split())
            nums = [a for a in argv[3:] if a.isdigit()]
            if "--match-head-commit" not in joined or not nums or not set(nums) <= allowed:
                decide("deny", "auto merge needs --match-head-commit and a PR listed in HRD_AUTO_PRS.")
        # 1b. trust records bypass verification for one article — a human decision only
        if "--kind" in argv and "trust" in argv and ("ledger" in argv or any(x.endswith("integrity.py") for x in argv)):
            protect("recording `trust` in the verification ledger skips re-verification for that article.")
        # 2. deploy
        if any(contains(strip_noise(argv), s) for s in sigs):
            if unattended():
                decide("deny", "unattended sessions may not deploy (the batch runner does).")
            decide("ask", "running the deploy command publishes the whole base branch — confirm this is `ship` step 7.")
        # 3. writes to protected paths through the shell (actual write targets only)
        for token in write_targets(seg):
            what = classify_path(rel(root, token))
            if what:
                protect("shell write to the %s." % what)
            if rel(root, token) == CONFIG:
                protect("shell write to %s (protected keys must change through `ask`)." % CONFIG)
        # 4. git: the effective branch follows switch/checkout segments of this same command
        if argv[0] == "git" and len(argv) > 1:
            sub = argv[1]
            other_repo = other_git_dir(root, seg)
            if other_repo:
                continue
            if sub in ("switch", "checkout"):
                tgt = switch_target(root, argv)
                if tgt:
                    branch = tgt
                continue
            if sub in ("add", "rm", "mv"):
                specs = [x for x in argv[2:] if not x.startswith("-")]
                if sub == "add":
                    everything = not specs and any(x in ("-A", "--all", "-u", "--update") for x in argv[2:]) \
                        or specs == ["."]
                    pending |= set(git_pathspec_paths(root, [] if everything else specs, everything))
                elif specs:  # rm/mv touch tracked files that show no diff before running
                    srcs = specs if sub == "rm" else specs[:-1]
                    pending |= {p for p in git(root, "ls-files", "-z", "--", *srcs, check=False).split("\0") if p}
                    if sub == "mv":
                        dest = specs[-1]
                        if os.path.isdir(os.path.join(root, dest)) and len(srcs) >= 1:
                            pending |= {"%s/%s" % (dest.rstrip("/"), os.path.basename(x)) for x in srcs}
                        else:
                            pending.add(dest)
            rewrites = sub in ("merge", "cherry-pick", "revert", "am", "rebase", "pull") or (
                sub == "reset" and resets_history(argv[2:]))
            if rewrites:
                if unattended():  # unattended children never need history-changing git commands
                    decide("deny", "unattended sessions may not run `git %s`." % sub)
                if branch == base:
                    decide("ask", "`git %s` changes the base branch without Herald's commit checks — confirm." % sub)
            if sub == "push":
                _, refspecs = push_targets(normalize(seg, split=False))
                targets = [t.lstrip("+") for t in refspecs]
                targets = ["HEAD" if t == "@" else t.replace("@:", "HEAD:", 1) for t in targets]
                dests = [t.split(":", 1)[1] if ":" in t else (branch if t == "HEAD" else t) for t in targets]
                dests = [d[len("refs/heads/"):] if d.startswith("refs/heads/") else d for d in dests]
                if unattended():
                    # allow-list: an explicit destination that is a herald/* branch, nothing else
                    if any(x in ("--all", "--mirror", "--tags") for x in argv[2:]) or not dests \
                            or not all(d.startswith("herald/") for d in dests):
                        decide("deny", "unattended sessions may push only explicit herald/* branches.")
            if sub == "commit":
                if unattended() and not (branch.startswith("herald/") or branch.startswith("herald-revert/")):
                    decide("deny", "unattended sessions may commit only on herald/* branches (branch: %s)." % branch)
                if branch == base:
                    staged = staged_after(root, argv, pending)
                    juris = jurisdiction(root, cfg)
                    allowed = commits.all_base_globs(cfg)
                    bad = [p for p in staged if commits._match(p, juris) and not commits._match(p, allowed)]
                    if bad:
                        decide("deny", "base commits may not touch Herald paths outside the allowed record/harness set: %s"
                               % ", ".join(bad[:5]))
                parsed = parse_branch(branch)
                if parsed or branch.startswith("herald-revert/"):
                    staged = staged_after(root, argv, pending)
                    if parsed:
                        globs = commits.pr_scope_globs(cfg, *parsed)
                    else:
                        tid = branch[len("herald-revert/"):]
                        globs = [".claude/herald/work/%s/*" % tid] + herald_article_paths(root, cfg)
                    bad = [p for p in staged if not commits._match(p, globs)]
                    if bad:
                        protect("commit on %s touches files outside the PR file scope: %s" % (branch, ", ".join(bad[:5])))


def main():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    try:
        from .util import repo_root
        root = repo_root(payload.get("cwd"))
        if read_json(os.path.join(root, CONFIG)) is None:
            sys.exit(0)
        cfg = Config.load(root)
        tool = payload.get("tool_name", "")
        ti = payload.get("tool_input") or {}
        if tool == "Bash":
            check_bash(root, cfg, ti.get("command", ""))
        elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            check_edit(root, cfg, tool, ti)
    except SystemExit:
        raise
    except Exception as e:  # a crashing guard must not silently disable itself unattended
        if unattended():
            decide("deny", "guard error (%s) — refusing while unattended" % e)
        sys.stderr.write("Herald guard warning: %s\n" % e)
    sys.exit(0)
