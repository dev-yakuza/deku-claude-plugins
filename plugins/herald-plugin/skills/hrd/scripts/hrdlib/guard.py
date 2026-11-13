"""PreToolUse guard (plan §3.4). Installed by `init` into `.claude/settings.json` as
`python3 "${CLAUDE_PROJECT_DIR}/.claude/herald/scripts/guard.py"` for Bash and Edit/Write.

Decision table (attended → `ask`, unattended `HRD_UNATTENDED=1` → `deny`):
- criteria files (SNS guides and persona included), protected personas (critique/verify, distributor),
  protected config keys, guard wiring, the ledger
- `gh pr merge` (unattended: allowed only for auto + --match-head-commit + PR in HRD_AUTO_PRS)
- the deploy command
- base-branch commits that touch Herald paths outside the allowed set (unattended: any
  base commit or push) and herald/* commits outside the PR file scope.

0.20.0 (design/herald/11-ship-consent.md §2.5, §9–§11): a `--ship` run marks its checkout lock
(`.claude/herald/memory/lock`, protected here with `lock.pass`). With that mark for the command's
topic (and not `--attended`), `image confirm|reject --agent` and `shot confirm --agent` pass rule
1c/1d; with a valid `lock.pass`, the one merge command `ship` runs (checked on the raw text) and
the configured deploy command (byte for byte) get `allow` — only after every other rule decided
nothing; the merge only before `ship-pass --merged`, the deploy only after. Unattended runs are
unchanged. A crashing guard still asks for a merge or the deploy; one that cannot even import
falls back to the same asks in `scripts/guard.py`. Known limit: a hook killed by its timeout
decides nothing — Claude Code then applies the settings alone, which no longer ask before a merge.

It is a string-pattern tripwire, not a boundary (plan §3.4 "한계"); `audit` checks after the fact.
"""

import json
import os
import re
import shlex
import sys

from . import commits, lock as lockmod
from .config import Config
from .store import load_published, load_topics, parse_branch
from .util import git, read_json

CRITERIA = [
    "docs/editorial/charter.md", "docs/editorial/exemplars.md", "docs/editorial/sources.md",
    "docs/editorial/style-guide.md", "docs/editorial/promotion.md",
    "docs/editorial/search-checklist.md", "docs/editorial/gate-rules.json",
    "docs/editorial/refresh-policy.md",  # the refresh decision's rules (02-refresh-decision.md R4)
    "docs/editorial/categories/*",
    # SNS (03-social.md S14): channel guides, the persona and its empathy notes hold the floor
    "docs/editorial/channels/*", "docs/editorial/persona.md", "docs/editorial/persona-notes.md",
]
PERSONAS = [".claude/agents/editor.md", ".claude/agents/fact-checker.md", ".claude/agents/subject-expert.md",
            ".claude/agents/distributor.md"]
WIRING = [".claude/settings.json", ".claude/settings.local.json", ".claude/herald/scripts/*",
          ".claude/herald/scripts/**"]
LEDGER = [".claude/herald/ledger/*", ".claude/herald/ledger/**"]
# a diagram's evidence: only `HRD image render` writes it (design/herald/08-images.md §2.7.2). Matched
# by file path only, so `git clean -fd -- <w>` / `git checkout HEAD -- <w>` and commits stay free
RENDERS = [".claude/herald/work/*/diagram-renders.jsonl"]
# the checkout lock carries a `--ship` run's mark, `lock.pass` the merge/deploy pass (11 §2.5 1, §9 m2)
LOCKS = [".claude/herald/memory/lock", ".claude/herald/memory/lock.pass"]
# evolve's local ledgers and the signals they count (0.22.0, 13 §R1-M3): only HRD writes them — a
# direct edit could retire or consume growth evidence with nobody asked
MEMORY_LEDGERS = [".claude/herald/memory/evolve-state.json", ".claude/herald/memory/evolve-scan.json",
                  ".claude/herald/signals.jsonl"]
CONFIG = ".claude/herald/config.json"
# `screenshots` holds the capture command Herald runs (design/herald/07-auto-capture.md §2.7);
# `limner` and `images` the image engine's argv, the OG generator and the attribution templates (08 §2.15)
PROTECTED_CONFIG_KEYS = ("autonomy", "budget", "commands", "paths", "base_branch", "roles", "models",
                         "translations", "screenshots", "limner", "images")
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


def limner_state_globs(cfg):
    """limner's whole state dir (design/herald/09-scenes.md §2.13, R2-3): its records vouch for a
    generated scene, and `tmp/` holds records limner adopts into `records/`; Herald's own job and
    output folders live there too. Matched by path only; the default `.limner` without config."""
    sd = ".limner"
    try:
        blk = cfg.get("limner") if cfg is not None else None
        v = blk.get("state_dir") if isinstance(blk, dict) else None
    except Exception:  # noqa: BLE001 — no readable config: the default
        v = None
    if isinstance(v, str) and v.strip("/ ") and not os.path.isabs(v) and ".." not in v.split("/"):
        sd = v.strip("/")
    return [sd, sd + "/*", sd + "/**"]


def classify_path(r, cfg=None):
    if _covers(r, CRITERIA):  # a directory holding criteria too (`rm -r docs/editorial/channels`)
        return "criteria file %s" % r
    if r in PERSONAS:
        return "protected persona %s" % r
    if _covers(r, WIRING):
        return "guard wiring %s" % r
    if _covers(r, LEDGER):
        return "verification ledger %s" % r
    if commits._match(r, RENDERS):
        return "diagram render record %s" % r
    if _covers(r, LOCKS):
        return "checkout lock %s" % r
    if _covers(r, MEMORY_LEDGERS):
        return "evolve ledger %s" % r
    if r and _covers(r, limner_state_globs(cfg)):
        return "limner state %s" % r
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
        # the bundle: every configured translation path too, so an unverified translation
        # cannot be committed to base directly (01-multilingual.md §5)
        globs += [cfg.body_path(s), cfg.image_dir(s) + "/*", cfg.image_dir(s) + "/**"]
        globs += list(cfg.translation_paths(s).values())
        if cfg.og_outside(s):  # a repo OG generator's path (08-images.md §2.15)
            globs.append(cfg.og_outside(s))
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
    what = classify_path(r, cfg)
    if what:
        protect("editing the %s changes Herald's verification baseline or enforcement." % what)
    if r == CONFIG and config_change_protected(root, ti, tool):
        protect("changing protected config keys (%s)." % ", ".join(PROTECTED_CONFIG_KEYS))


SHELLS = "bash|sh|zsh|dash|ksh"
_TO_SHELL = re.compile(r"\|\s*(?:%s)\b" % SHELLS)  # a pipe into a shell: everything may run
_SHELL_ARG = re.compile(r"(?:^|[\s;&|(`])(?:%s)\s[^;&|\n]*-[A-Za-z]*c[A-Za-z]*\s+(?:--\s+)?$|(?:^|[\s;&|(`])eval\s+$"
                        % SHELLS)
_SHELL_STDIN = re.compile(r"(?:^|[\s;&|(`])(?:%s)\b[^;&|\n]*$" % SHELLS)
_QHEREDOC = re.compile(r"<<-?\s*(['\"])([A-Za-z0-9_.-]+)\1")
_GENERIC = {"uv", "uvx", "pipx", "run", "env", "python", "python3"}


def _limner_words(cfg):
    """The words that name limner's executable: `lmn` and the configured command's own name (its
    first word, or its last when the first is a runner such as `uv run … lmn`)."""
    out = {"lmn"}
    try:
        from . import limner
        cmd = limner.settings(cfg)["command"] if cfg is not None else None
    except Exception:  # noqa: BLE001 — no readable config: `lmn` alone
        cmd = None
    if isinstance(cmd, list) and cmd and all(isinstance(x, str) for x in cmd):
        for x in (cmd[0], cmd[-1]):
            b = os.path.basename(x)
            if b and not b.startswith("-") and b not in _GENERIC and not re.match(r"^python[0-9.]*$", b):
                out.add(b)
                break
    return out


def _strip_quoted(cmd):
    """The command with what the shell never runs taken out (review 22 R3-2/R3-3): the bodies of
    quoted heredocs (`<<'X'`, `<<"X"`) and single-quoted strings — unless they are fed to a shell
    (`bash -c '…'`, `eval '…'`, `bash <<'X'`, `… | sh`). Double-quoted text stays (a mention there
    is asked about, never let through)."""
    to_shell = bool(_TO_SHELL.search(cmd))
    out, i = [], 0
    for m in list(_QHEREDOC.finditer(cmd)):
        if m.start() < i:
            continue
        nl = cmd.find("\n", m.end())
        if nl < 0:
            break
        k, end = nl + 1, len(cmd)
        while k < len(cmd):
            e = cmd.find("\n", k)
            e = len(cmd) if e < 0 else e
            if cmd[k:e].strip() == m.group(2):
                end = e
                break
            k = e + 1
        keep = to_shell or _SHELL_STDIN.search(cmd[:m.start()].split("\n")[-1])
        out.append(cmd[i:m.start()] + "<<" + m.group(2) + cmd[m.end():nl + 1])
        out.append(cmd[nl + 1:end] if keep else "")
        i = end
    text = "".join(out) + cmd[i:]
    res, dq, k = [], False, 0
    while k < len(text):
        c = text[k]
        if c == "\\" and k + 1 < len(text):
            res.append(text[k:k + 2])
            k += 2
            continue
        if c == '"':
            dq = not dq
        elif c == "'" and not dq:
            e = text.find("'", k + 1)
            e = len(text) if e < 0 else e
            if to_shell or _SHELL_ARG.search("".join(res)):
                res.append(" " + text[k + 1:e] + " ")
            else:
                res.append(" ")
            k = e + 1
            continue
        res.append(c)
        k += 1
    return "".join(res)


def _lookup(words):
    """A simple command that only finds or installs limner, never runs it (review 22 R3-5), or
    Herald's own CLI (it calls limner itself)."""
    w = words
    return (w[:1] in (["which"], ["type"], ["hash"]) or w[:2] in (["command", "-v"], ["command", "-V"])
            or w[:3] in (["uv", "tool", "install"], ["uv", "tool", "upgrade"], ["uv", "tool", "uninstall"],
                         ["uv", "pip", "install"])
            or w[:2] in (["pipx", "install"], ["pipx", "upgrade"], ["pipx", "uninstall"], ["pipx", "reinstall"])
            or w[:1] == ["HRD"] or any(os.path.basename(x) == "hrd.py" for x in w))


def limner_in(cmd, cfg):
    """A shell line that may run limner (10-social-media.md §10 R3-1, review 22 R3-2/R3-3): after
    the never-run text is taken out (`_strip_quoted`), any word naming limner's executable (`lmn`,
    the configured command's name, a path ending in one), `-m limner` after a python word, or
    `limner` after `uvx`/`pipx run` — wherever it stands (a loop body, after a redirection, in
    `$( )` at any depth). Lookups and installs (`command -v`, `which`, `uv tool install`, …) and
    Herald's own CLI are not calls. Token-based on purpose: shell grammar is never chased."""
    names = _limner_words(cfg)
    text = _strip_quoted(cmd or "")
    for piece in re.split(r"[;&|\n()`{}]|\$\(", text):
        words = [w for w in re.split(r"[\s\"<>]+", piece) if w]
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
        if not words or _lookup(words):
            continue
        if any(os.path.basename(w) in names for w in words):
            return True
        if any(re.match(r"^python[0-9.]*$", os.path.basename(w)) for w in words) and (
                "-mlimner" in words or any(a == "-m" and b in ("limner", "limner.cli")
                                          for a, b in zip(words, words[1:]))):
            return True
        if any((a == "uvx" and b == "limner") or (a, b) == ("run", "limner") and "pipx" in words
               for a, b in zip(words, words[1:])):
            return True
    return False


def segments(cmd):
    # `&&`, `||`, `;`, newlines, pipes and a lone `&` (background) all start a new command
    return [s.strip() for s in re.split(r"&&|\|\||;|\n|\||(?<![>&])&(?![>&])", cmd) if s.strip()]


WRAPPERS = {"env", "command", "exec", "nohup", "time", "nice", "xargs", "sudo", "stdbuf", "timeout"}
WRAPPER_VALUE_OPTS = {"timeout": ("-s", "--signal", "-k", "--kill-after"), "sudo": ("-u", "-g", "-C", "-h", "-p"),
                      "env": ("-u", "--unset", "-C", "--chdir", "-S"), "nice": ("-n",),
                      "stdbuf": ("-i", "-o", "-e"), "xargs": ("-I", "-n", "-P", "-L", "-d", "-a", "-E", "-s")}
PKG_RUNNERS = {"npm", "pnpm", "yarn", "bun"}


def canon(argv):
    """Package-runner forms reduced to one shape so a configured deploy matches however it is
    invoked: `npx|bunx|pnpm dlx|yarn dlx|npm exec X` → `X`; `npm [opts] run|run-script T`,
    `pnpm [run] T`, `yarn [run] T`, `bun run T` → `run T`; `bash|sh script` → script basename."""
    if not argv:
        return argv
    a0, rest = argv[0], argv[1:]
    if a0 in ("npx", "bunx"):
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in ("-p", "--package") else rest[1:]
        return canon(rest)
    if a0 in PKG_RUNNERS:
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in ("--prefix", "-C", "--cwd", "--dir") else rest[1:]
        if rest and rest[0] in ("dlx", "exec", "x"):
            return canon([x for x in rest[1:] if x != "--"])
        if rest and rest[0] in ("run", "run-script"):
            return ["run"] + rest[1:]
        if a0 in ("pnpm", "yarn") and rest and rest[0] not in ("install", "add", "remove", "i", "up", "update"):
            return ["run"] + rest  # `pnpm deploy`, `yarn deploy` run the script
        return [a0] + rest
    if a0 in ("bash", "sh", "zsh") and rest and not rest[0].startswith("-"):
        return [os.path.basename(rest[0])] + rest[1:]
    return argv


def unwrap(argv):
    """Drop leading VAR=value assignments and wrapper commands (`env -i A=1`, `nohup`, `time`,
    `timeout 60`, ...), and reduce argv[0] to its basename (`/usr/bin/git` → `git`)."""
    i = 0
    while i < len(argv):
        a = argv[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", a):
            i += 1
            continue
        base = os.path.basename(a)
        if base in WRAPPERS:
            i += 1
            takes_value = WRAPPER_VALUE_OPTS.get(base, ())
            while i < len(argv):
                x = argv[i]
                if x in takes_value:
                    i += 2
                elif x.startswith("-") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", x) \
                        or (base == "timeout" and re.match(r"^\d+(\.\d+)?[smhd]?$", x)) \
                        or (base == "nice" and re.match(r"^-?\d+$", x)):
                    i += 1
                else:
                    break
            continue
        break
    out = argv[i:]
    if out:
        out = [os.path.basename(out[0])] + out[1:]
    return out


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
    argv = unwrap(argv)
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
    """Signature match anchored at the command start (after env/wrappers): `grep hugo` is not
    `hugo`."""
    n = len(needle)
    return n > 0 and hay[:n] == needle


TRIVIAL = {"echo", "tee", "true", ":", "printf", "cat", "sleep", "cd"}


def deploy_signatures(deploy):
    """Publishing steps of the configured deploy string: split on `&&`/`;`/pipes, drop env
    assignments, redirections, trivial commands (echo, tee, …) and build/test/lint steps —
    normalized like the commands we inspect."""
    sigs = []
    for part in re.split(r"&&|\|\||;|\n", deploy or ""):
        for member in part.split("|"):  # `echo y | vercel --prod`: the publisher is after the pipe
            argv = strip_noise(normalize(member.strip()))
            if argv and argv[0] not in TRIVIAL and not is_build_step(argv):
                sigs.append(canon(argv))
    if not sigs and (deploy or "").strip():
        rest = [strip_noise(normalize(x)) for x in segments(deploy)]
        rest = [x for x in rest if x and x[0] not in TRIVIAL]
        sigs = [canon(x) for x in rest[-1:]]
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
            common = git(d, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False).strip() \
                if os.path.isdir(d) else ""
            mine = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False).strip()
            # unknown → same repository (fail closed); worktrees share the common dir
            if common and os.path.realpath(common) != os.path.realpath(mine):
                return True
    return False


def resets_history(args, root=None):
    """Does this `git reset` move HEAD? --hard/--soft/--merge/--keep or a single commit argument
    do; `reset`, `reset -- <paths>`, `reset HEAD <path>`, `reset <path>` only unstage."""
    if any(a in ("--hard", "--soft", "--merge", "--keep") for a in args):
        return True
    if "--" in args:
        after = args[args.index("--") + 1:]
        if after:
            return False  # `reset [rev] -- <paths>` only unstages
        args = args[:args.index("--")]
    names = [a for a in args if not a.startswith("-")]
    if len(names) != 1:
        return False
    name = names[0]
    if name in ("HEAD", "@"):
        return False  # `reset HEAD` unstages; HEAD stays
    if root and os.path.exists(os.path.join(root, name)):
        return False
    if root is None:
        return True
    return bool(git(root, "rev-parse", "--verify", "-q", name + "^{commit}", check=False).strip())


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


def is_build_step(argv):
    """Build/test/lint steps judged by command position (`npm run build`, `make test`,
    `pnpm lint`), never by arguments (`gh-pages -d build` is a deploy)."""
    cmd = os.path.basename(argv[0])
    if cmd in ("npm", "yarn", "pnpm", "bun", "npx") and len(argv) > 1:
        task = argv[2] if argv[1] in ("run", "run-script") and len(argv) > 2 else argv[1]
        return task.split(":", 1)[0] in BUILD_WORDS
    if cmd == "make" and len(argv) > 1:
        return argv[1] in BUILD_WORDS
    return len(argv) > 1 and argv[1] in BUILD_WORDS


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
    argv = strip_noise(unwrap(raw))
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
    if ref == "-":
        prev = git(root, "rev-parse", "--abbrev-ref", "@{-1}", check=False).strip()
        return prev or None
    if argv[1] == "switch" or git(root, "rev-parse", "--verify", "-q", "refs/heads/" + ref, check=False).strip() \
            or git(root, "rev-parse", "--verify", "-q", "refs/remotes/origin/" + ref, check=False).strip():
        return ref
    return None


UNATTENDED_GIT = {"status", "diff", "log", "show", "rev-parse", "ls-files", "ls-tree", "cat-file",
                  "hash-object", "merge-base", "for-each-ref", "check-ignore", "blame", "grep", "describe",
                  "rev-list", "shortlog", "switch", "checkout", "restore", "add", "rm", "mv", "commit", "push",
                  "clean", "branch", "fetch", "reset", "show-ref", "symbolic-ref", "name-rev", "config",
                  "remote", "ls-remote", "reflog", "diff-tree", "diff-index", "version", "tag", "stash",
                  "worktree", "help"}


def unattended_git_allowed(root, base, argv):
    """Allow-list for unattended sessions: read commands, the write-path commands the flow needs,
    and nothing that moves a ref behind the guard's back (update-ref, branch -f, worktree, merge,
    rebase, cherry-pick, fetch into a local branch, ...)."""
    sub, args = argv[1], argv[2:]
    if sub not in UNATTENDED_GIT:
        decide("deny", "unattended sessions may not run `git %s`." % sub)
    if sub == "branch" and any(a in ("-f", "--force", "-m", "-M", "-c", "-C", "--move", "--copy",
                                     "-u", "--set-upstream-to") for a in args):
        decide("deny", "unattended sessions may not move, copy or force branches.")
    if sub == "branch" and any(a in ("-D", "-d", "--delete") for a in args):
        if not all(a.startswith(("herald/", "herald-revert/")) for a in args if not a.startswith("-")):
            decide("deny", "unattended sessions may delete only herald/* branches.")
    if sub == "fetch":
        for a in args:
            if ":" in a and not a.startswith("-"):
                dst = a.split(":", 1)[1].lstrip("+")
                if not dst.startswith("refs/remotes/"):
                    decide("deny", "unattended sessions may fetch only into remote-tracking refs.")
    if sub == "config":
        writes = any(a.startswith(("--unset", "--add", "--replace-all", "--remove-section", "--rename-section"))
                     or a in ("-e", "--edit") for a in args)
        reads = any(a.startswith("--get") or a in ("-l", "--list", "--show-origin") for a in args)
        readonly = not writes and (reads or len([a for a in args if not a.startswith("-")]) <= 1)
        if not readonly:
            decide("deny", "unattended sessions may not change git config.")
    if sub == "remote" and [a for a in args if not a.startswith("-")][:1] not in ([], ["show"], ["get-url"]):
        decide("deny", "unattended sessions may only read remotes.")
    if sub == "tag" and [a for a in args if not a.startswith("-")] and "-l" not in args and "--list" not in args:
        decide("deny", "unattended sessions may only list tags.")
    if sub == "stash" and [a for a in args if not a.startswith("-")][:1] not in (["list"], ["show"]):
        decide("deny", "unattended sessions may only list stashes.")
    if sub == "worktree" and [a for a in args if not a.startswith("-")][:1] != ["list"]:
        decide("deny", "unattended sessions may not add or move worktrees.")
    if sub == "reflog" and [a for a in args if not a.startswith("-")][:1] not in ([], ["show"]):
        decide("deny", "unattended sessions may only read the reflog.")
    if sub in ("switch", "checkout"):
        for i, a in enumerate(args):
            if a in ("-C", "-B", "--force-create", "--orphan"):
                tgt = args[i + 1] if i + 1 < len(args) else ""
                if not tgt.startswith(("herald/", "herald-revert/")):
                    decide("deny", "unattended sessions may not force-create or reset branch %s." % tgt)
    if sub == "clean":
        paths_ = args[args.index("--") + 1:] if "--" in args else []
        if not paths_ or any(a.startswith("-") and ("x" in a or "X" in a) and not a.startswith("--") for a in args):
            decide("deny", "unattended `git clean` needs explicit paths after `--` and no -x/-X.")
        for p_ in paths_:
            rp = os.path.relpath(os.path.realpath(os.path.join(root, p_)), os.path.realpath(root)).replace(os.sep, "/")
            if rp in (".", "", ".claude", ".claude/herald") or rp.startswith((".claude/herald/ledger", ".claude/herald/memory")):
                decide("deny", "unattended `git clean` may not touch the ledger or memory (%s)." % p_)
    if sub == "symbolic-ref" and len([a for a in args if not a.startswith("-")]) >= 2:
        decide("deny", "unattended sessions may not repoint HEAD.")
    if sub == "reset" and resets_history(args, root):
        decide("deny", "unattended sessions may not run `git reset` that moves HEAD.")


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


# options of `HRD image` / `HRD shot` that take a value: a token right after one is that value
# (`--note=--agent` sets a note — never the flag)
VALUE_OPTS = ("--topic", "--id", "--source", "--pr", "--reason", "--wait", "--note", "--rev", "--command",
              "--retake-kind", "--slug", "--path", "--problem", "--stage", "--place", "--url")


def _prefix_of(x, name, least=3):
    """argparse takes any unambiguous prefix (`--ag`), with or without `=value` (`--retire=<id>`,
    `--ret=<id>` — review 28 B1): does token `x` name `name`?"""
    h = x.split("=", 1)[0]
    return h.startswith("--") and len(h) >= least and name.startswith(h)


def _agent_pass(root, seg):
    """1c/1d's `--agent` way (11 §2.5 2, §11 m3): the segment carries the flag `--agent` itself (not
    as some option's value) and the lock carries a ship mark for its `--topic`, not attended.
    Read failures are "no mark"."""
    if unattended():  # unattended runs never pass (11 §1): 0.19.0's deny
        return False
    raw = normalize(seg, split=False)
    agent, topic, i = False, None, 0
    while i < len(raw):
        x = raw[i]
        if x.startswith("--topic=") or (x.startswith("--to") and "=" in x and "--topic".startswith(x.split("=")[0])):
            topic = x.split("=", 1)[1]
        elif "=" not in x and _prefix_of(x, "--topic") and i + 1 < len(raw):
            topic = raw[i + 1]
            i += 1
        elif _prefix_of(x, "--agent"):
            agent = True
        elif "=" not in x and any(_prefix_of(x, o) for o in VALUE_OPTS):
            i += 1  # its value, whatever it looks like
        i += 1
    if not agent or not topic:
        return False
    try:
        return lockmod.agent_ok(root, topic)
    except Exception:  # noqa: BLE001
        return False


def _opt_values(seg, name):
    """The values the segment gives option `name` (`--cmd evolve`, `--cmd=evolve`, `--cm evolve`)."""
    raw = normalize(seg, split=False)
    out, i = [], 0
    while i < len(raw):
        x = raw[i]
        if _prefix_of(x, name):
            if "=" in x:
                out.append(x.split("=", 1)[1])
            elif i + 1 < len(raw):
                out.append(raw[i + 1])
                i += 1
        elif "=" not in x and any(_prefix_of(x, o) for o in VALUE_OPTS):
            i += 1
        i += 1
    return out


def _has_flag(seg, name):
    """The segment carries the flag `name` itself — any prefix argparse takes (3+ characters), never
    some option's value (`--note=--rerun`, `--note --rerun`) — 12 §R3-m1, §R4-m2."""
    raw = normalize(seg, split=False)
    i = 0
    while i < len(raw):
        x = raw[i]
        if _prefix_of(x, name):
            return True
        if "=" not in x and any(_prefix_of(x, o) for o in VALUE_OPTS):
            i += 1  # its value, whatever it looks like
        i += 1
    return False


MERGE_META = re.compile(r"[;&|<>$`()\n]")
MERGE_METHODS = ("--squash", "--merge", "--rebase")


def ship_merge_ok(root, cmd):
    """R2-1: the raw command is exactly `gh pr merge <n> [--squash|--merge|--rebase]
    [--delete-branch] --match-head-commit <sha>` — no shell syntax, no env prefix, nothing else —
    and <n>, <sha> are the valid `lock.pass`'s. Never unattended."""
    if unattended() or not cmd or MERGE_META.search(cmd):
        return False
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return False
    if argv[:3] != ["gh", "pr", "merge"] or len(argv) < 4 or not argv[3].isdigit():
        return False
    method = delete = 0
    sha, i = [], 4
    while i < len(argv):
        x = argv[i]
        if x in MERGE_METHODS:
            method += 1
        elif x == "--delete-branch":
            delete += 1
        elif x == "--match-head-commit" and i + 1 < len(argv):
            sha.append(argv[i + 1])
            i += 1
        elif x.startswith("--match-head-commit="):
            sha.append(x.split("=", 1)[1])
        else:
            return False
        i += 1
    if method > 1 or delete > 1 or len(sha) != 1:
        return False
    p = lockmod.valid_pass(root)
    return bool(p) and p.get("merged") is False and str(p.get("pr")) == str(int(argv[3])) and \
        sha[0].strip().lower() == str(p.get("sha")).lower()  # only before the merge (review 24 MINOR-4)


def ship_deploy_ok(root, cfg, cmd):
    """R2-2: the raw command is the configured deploy, byte for byte (no normalizing), a valid
    `lock.pass` exists and the checkout is on the base branch (11 §10 m2). Never unattended."""
    deploy = cfg.get("commands", "deploy") or ""
    if unattended() or not deploy.strip() or (cmd or "").strip() != deploy.strip():
        return False
    p = lockmod.valid_pass(root)
    # only after `ship-pass --merged` saw the PR merged into this base (review 24 MINOR-4), and only
    # while the base is still the commit it saw (R2-MINOR-1)
    if not p or p.get("merged") is not True or not p.get("base_head") or current_branch(root) != cfg.base:
        return False
    return git(root, "rev-parse", "HEAD", check=False).strip() == p["base_head"]


def check_bash(root, cfg, cmd):
    base = cfg.base
    sigs = deploy_signatures((cfg.get("commands", "deploy") or "").strip())
    # a `--ship` run's merge or deploy: only rules 1 and 2 stand aside; `allow` comes at the very
    # end, after every other rule decided nothing (11 §11 m2)
    try:
        ship_merge = ship_merge_ok(root, cmd)
        ship_deploy = not ship_merge and ship_deploy_ok(root, cfg, cmd)
    except Exception:  # noqa: BLE001 — a pass that cannot be read is no pass
        ship_merge = ship_deploy = False
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
        if argv[:3] == ["gh", "pr", "merge"] and not ship_merge:
            if not unattended():
                decide("ask", "merging a PR publishes content — confirm this is the approved `ship` step.")
            if cfg.get("autonomy", "publish") != "auto":
                decide("deny", "unattended runs may not merge while autonomy.publish=approve.")
            allowed = set((os.environ.get("HRD_AUTO_PRS") or "").replace(",", " ").split())
            nums = [a for a in argv[3:] if a.isdigit()]
            if "--match-head-commit" not in joined or not nums or not set(nums) <= allowed:
                decide("deny", "auto merge needs --match-head-commit and a PR listed in HRD_AUTO_PRS.")
        # 1b. trust records bypass verification for one article — a human decision only
        # argparse accepts any unambiguous prefix (`--kin trust`): match those too (R5 MN-6)
        has_kind = any(len(x) >= 3 and "--kind".startswith(x.split("=", 1)[0]) and x.startswith("--k") for x in argv)
        if has_kind and "trust" in argv and ("ledger" in argv or any(x.endswith("integrity.py") for x in argv)):
            protect("recording `trust` in the verification ledger skips re-verification for that article.")
        if has_kind and "withdraw-lang" in argv and ("ledger" in argv or any(x.endswith("integrity.py") for x in argv)):
            protect("recording `withdraw-lang` in the verification ledger takes a translation down without re-verification.")
        # 1c. a captured screenshot passes to the remote only on a human's look (07-auto-capture.md
        # §2.5): `shot confirm` / `shot demote` (argparse takes positional choices whole, never a prefix)
        # 0.20.0: `shot confirm --agent` in a `--ship` run of that topic passes this segment (never demote)
        if "shot" in argv and ("confirm" in argv or "demote" in argv) and not (
                "demote" not in argv and _agent_pass(root, seg)):
            protect("`HRD shot %s` records that a human looked at an automatic screenshot — only the human decides."
                    % ("confirm" if "confirm" in argv else "demote"))
        # 1d. the same for an external image (08-images.md §2.15); `--agent` as for 1c
        if "image" in argv and ("confirm" in argv or "reject" in argv) and not _agent_pass(root, seg):
            protect("`HRD image %s` records a human's decision about an external image — only the human decides."
                    % ("confirm" if "confirm" in argv else "reject"))
        # 1e. 0.21.0 (12 §R3-m1, §R2-m4, §R1-m4): a human reruns brief/research, judges a place's subject,
        # or lifts a "go without" — unattended and `--ship` refusals are the commands' own (§R4-m2)
        if "stage" in argv and "pass" in argv and _has_flag(seg, "--rerun"):
            protect("brief/research를 다시 통과시킵니다. 옛 이미지 자리 기록(사람의 ‘없이 감’·대상 거부)이 새 brief에 없으면 "
                    "이 글감 전체에서 AI 대체 그림이 꺼집니다. (Re-passing brief/research: if a human's old image-place "
                    "record has no line in the new brief, AI stand-ins turn off for this whole topic.)")
        if "image" in argv and "review" in argv and _has_flag(seg, "--human"):
            protect("`HRD image review --problem subject --human` records a human's judgement that a place is a work, "
                    "a person, a logo or text — only the human decides.")
        if "image" in argv and "stand-in" in argv and _has_flag(seg, "--allow"):
            protect("`HRD image stand-in --allow` lifts a human's \"go without\" (or a review's refusal) for that "
                    "place — only the human decides. Check its brief line and the refusal note in `HRD image status`.")
        # 1f. 0.22.0 (13 §3.2, §R1-M3): retiring signals takes growth evidence out of the count without a
        # proposal — the human confirms here (the command itself checks the evolve lock)
        # the evolve lock is what `--retire` checks: a human starts every evolve run, so taking it is asked too
        # — otherwise an agent could take it and retire alone (review 28 B1)
        if "lock" in argv and "acquire" in argv and "evolve" in _opt_values(seg, "--cmd"):
            protect("`/hrd evolve`를 시작합니다 — evolve는 언제나 사람이 시작합니다. (Starting `/hrd evolve` — evolve is "
                    "always started by a human; its lock lets the run retire growth signals.)")
        if "evolve-mark" in argv and (_has_flag(seg, "--retire") or _has_flag(seg, "--unretire")):
            protect("퇴역은 성장 증거를 제안 없이 지웁니다 — 사람의 결정인지 확인하세요. (Retiring removes growth evidence "
                    "without a proposal — confirm this is the human's decision.)")
        # 2. deploy
        if not ship_deploy and any(contains(canon(strip_noise(argv)), s) for s in sigs):
            if unattended():
                decide("deny", "unattended sessions may not deploy (the batch runner does).")
            decide("ask", "running the deploy command publishes the whole base branch — confirm this is `ship` step 7.")
        # 3. writes to protected paths through the shell (actual write targets only)
        for token in write_targets(seg):
            what = classify_path(rel(root, token), cfg)
            if what:
                protect("shell write to the %s." % what)
            if rel(root, token) == CONFIG:
                protect("shell write to %s (protected keys must change through `ask`)." % CONFIG)
        # 4. git: the effective branch follows switch/checkout segments of this same command
        if argv[0] == "git" and len(argv) > 1:
            argv = strip_noise(argv)  # `2>&1` is not a pathspec or a refspec
            sub = argv[1]
            other_repo = other_git_dir(root, seg)
            if other_repo:
                continue
            if unattended():
                unattended_git_allowed(root, base, argv)
            if sub in ("switch", "checkout"):
                tgt = switch_target(root, argv)
                if tgt:
                    branch = tgt
                continue
            if sub in ("add", "rm", "mv"):
                specs = [x for x in argv[2:] if not x.startswith("-")]
                if sub == "add":
                    update_only = any(x in ("-u", "--update") for x in argv[2:])
                    everything = not specs and any(x in ("-A", "--all", "-u", "--update") for x in argv[2:]) \
                        or specs == ["."]
                    paths_ = git_pathspec_paths(root, [] if everything else specs, everything)
                    if update_only:  # -u stages tracked files only
                        tracked = set(git(root, "ls-files", "-z", check=False).split("\0"))
                        paths_ = [x for x in paths_ if x in tracked]
                    pending |= set(paths_)
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
                sub == "reset" and resets_history(argv[2:], root))
            if rewrites:
                if branch == base:
                    decide("ask", "`git %s` changes the base branch without Herald's commit checks — confirm." % sub)
            if sub == "push":
                _, refspecs = push_targets(strip_noise(normalize(seg, split=False)))
                targets = [t.lstrip("+") for t in refspecs]
                targets = ["HEAD" if t == "@" else t.replace("@:", "HEAD:", 1) for t in targets]
                dests = [t.split(":", 1)[1] if ":" in t else (branch if t == "HEAD" else t) for t in targets]
                dests = [d[len("refs/heads/"):] if d.startswith("refs/heads/") else d for d in dests]
                if unattended():
                    if not dests:  # bare push: allowed only to a herald/* upstream
                        up = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False).strip()
                        if branch == current_branch(root) and up.startswith("origin/herald/"):
                            dests = [up[len("origin/"):]]
                    # allow-list: an explicit destination that is a herald/* branch, nothing else
                    if any(x in ("--all", "--mirror", "--tags") for x in argv[2:]) or not dests \
                            or not all(d.startswith("herald/") for d in dests):
                        decide("deny", "unattended sessions may push only explicit herald/* branches.")
            if sub == "commit":
                if unattended() and not (branch.startswith("herald/") or branch.startswith("herald-revert/")):
                    decide("deny", "unattended sessions may commit only on herald/* branches (branch: %s)." % branch)
                if branch == base:
                    staged = staged_after(root, argv, pending)
                    social_files = [p for p in staged if p.startswith("docs/editorial/channels/")
                                    or p in ("docs/editorial/persona.md", "docs/editorial/persona-notes.md")]
                    if social_files:  # HRD commit checks their floor; a raw commit does not
                        protect("committing %s without `HRD commit` skips the social floor check (03-social.md S14) — "
                                "use `HRD commit --cmd harness --kind social …`" % ", ".join(social_files[:3]))
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
                        globs = commits.pr_scope_globs(cfg, *parsed, langs=commits.topic_langs(root, parsed[0]))
                    else:
                        tid = branch[len("herald-revert/"):]
                        globs = [".claude/herald/work/%s/*" % tid] + herald_article_paths(root, cfg)
                    bad = [p for p in staged if not commits._match(p, globs)]
                    if bad:
                        protect("commit on %s touches files outside the PR file scope: %s" % (branch, ", ".join(bad[:5])))
    # 1e, after every other rule (their deny stands — review 22 R3-4): limner itself. Herald's
    # pictures and the records that vouch for them are written only through Herald
    # (10-social-media.md §10 R3-1 — a direct `lmn compose` could redraw them)
    if limner_in(cmd, cfg):
        protect("running limner directly — Herald calls it (`HRD image …`, `HRD social media`); a direct call "
                "can redraw a picture and the record Herald checks it against.")
    if ship_merge or ship_deploy:  # nothing above decided: the verified merge / the deploy of a `--ship` run
        decide("allow", "the %s of a `--ship` run, checked against its pass (lock.pass)."
               % ("merge" if ship_merge else "deploy"))


def closed_rule(root, cfg, tool, ti):
    """A malformed `translations` block: the bundle paths cannot be trusted, so the guard does
    not compute them — every git write and every edit except config.json itself needs a human
    (unattended: denied) until config is fixed (01-multilingual.md §2)."""
    try:
        errors, _ = cfg.validate()
    except Exception as e:  # noqa: BLE001 — a validator crash is an invalid config, closed
        errors = ["validation failed: %s" % e]
    if not errors:
        return False
    why = "config.json translations is invalid (%s) — fix it first" % "; ".join(errors)[:300]
    if tool == "Bash":
        # no allow-list: every shell command needs a human while config is broken (rare, and an
        # allow-list of "reads" kept leaking through substitutions, wrappers and git options)
        protect(why)
    elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        if rel(root, ti.get("file_path") or ti.get("notebook_path") or "") != CONFIG:
            protect(why)
        elif config_change_protected(root, ti, tool):
            # fixing config never skips the protected-key rule (INV1): the same ask as ever
            protect("changing protected config keys (%s)." % ", ".join(PROTECTED_CONFIG_KEYS))
    return True


MERGE_TEXT = re.compile(r"\bgh\b[\s\S]*\bmerge\b")


def _ask_publish_on_failure(payload, root=None):
    """R2-3 (11 §9, §10 m4): the settings no longer ask before `gh pr merge`, so a guard that
    fails (or finds no config) still asks for a merge — and for the deploy when config is
    readable — before falling open as in 0.19.0. Attended only."""
    if unattended() or payload.get("tool_name") != "Bash":
        return
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if not isinstance(cmd, str):
        return
    if MERGE_TEXT.search(cmd):
        decide("ask", "merging a PR publishes content — the guard could not check this command, confirm it.")
    try:
        deploy = (read_json(os.path.join(root, CONFIG)) or {}).get("commands", {}).get("deploy") if root else None
    except Exception:  # noqa: BLE001 — no readable config: the merge pattern only
        deploy = None
    if isinstance(deploy, str) and deploy.strip() and deploy.strip() in cmd:
        decide("ask", "running the deploy command publishes the whole base branch — the guard could not check "
                      "this command, confirm it.")


def main():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    root = None
    try:
        from .util import repo_root
        root = repo_root(payload.get("cwd"))
        if read_json(os.path.join(root, CONFIG)) is None:
            _ask_publish_on_failure(payload)
            sys.exit(0)
        cfg = Config.load(root)
        tool = payload.get("tool_name", "")
        ti = payload.get("tool_input") or {}
        if closed_rule(root, cfg, tool, ti):
            sys.exit(0)  # never compute bundle paths from a config that failed validation
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
        try:
            _ask_publish_on_failure(payload, root)
        except SystemExit:
            raise
        except Exception:  # noqa: BLE001
            pass
    sys.exit(0)
