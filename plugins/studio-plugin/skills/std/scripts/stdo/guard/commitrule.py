"""Commits in Studio repositories (m0d2-plan §5): hook-disabling environment and settings, the commit forms
that bypass `check_commit.py --stage`, plumbing and GitHub API writes, and the evidence for a Studio commit
(commit-ok.json + the person's answer "커밋 <tree12>"). The Studio paths of a commit are computed with the
pre-commit hook's own functions (stdo/commit/checks.Staged) through the guard's budgeted git."""

import os
import re

HOOKOFF_VARS = ("HUSKY", "HUSKY_SKIP_HOOKS", "LEFTHOOK", "LEFTHOOK_EXCLUDE", "SKIP", "SKIP_SIMPLE_GIT_HOOKS")
GIT_ENV = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY", "GIT_EXEC_PATH", "GIT_CONFIG",
           "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT")
CONTINUE_SUBS = ("merge", "cherry-pick", "revert", "rebase", "am")
HOOKOFF_TAIL = "do not turn Studio's pre-commit check off to retry."

# git commit options that take a value (short: next word or the rest of the cluster)
SHORT_VALUE = set("mFCct")
SHORT_OPTIONAL = set("Su")  # -S[keyid], -u[mode]: the rest of the cluster only
LONG_VALUE = {"--message", "--file", "--reuse-message", "--reedit-message", "--template", "--author", "--date",
              "--cleanup", "--fixup", "--squash", "--trailer", "--pathspec-from-file"}


def hookoff_env(cmd):
    """Names of hook-disabling or git-redirecting variables the command sets or unsets."""
    v = cmd.env
    names = set(v.set) | set(v.unset)
    out = sorted(n for n in names if n in HOOKOFF_VARS or n in GIT_ENV or n.startswith(("GIT_CONFIG_KEY_",
                                                                                          "GIT_CONFIG_VALUE_")))
    if v.cleared:
        out.append("env -i")
    return out


def hook_config(cmd):
    """A `-c` / `--config-env` / `--exec-path` of the git call that changes hooks or aliases."""
    for k, _v in cmd.git.configs:
        if _hook_key(k) or (k or "").lower() == "core.fsmonitor":
            return "-c %s" % k
    # git's own options come before the subcommand (a commit message may say anything)
    for w in cmd.words[1:]:
        if w.value is not None and w.value == cmd.git.sub:
            break
        if w.value is not None and w.value.startswith("--config-env"):
            return w.value.split("=", 1)[0]
        if w.value is not None and w.value.startswith("--exec-path="):
            return "--exec-path=…"  # sets git's helper folder; the bare --exec-path only prints it
        if w.value is None and w.raw.startswith(("--config-env", "--exec-path=", "-c")):
            return w.raw
    return None


def parse_commit(args):
    """Options of `git commit` -> dict; `paths` holds pathspecs (None for a dynamic word)."""
    o = {"all": False, "include": False, "only": False, "amend": False, "no_verify": False, "fixup_amend": False,
         "interactive": False, "pathspec_file": False, "dry_run": False, "paths": [], "unknown": False}
    vals = [w.value for w in args]
    i = 0
    end = False
    while i < len(vals):
        a = vals[i]
        if end:
            o["paths"].append(a)
            i += 1
            continue
        if a is None:
            raw = args[i].raw
            if raw.startswith(("-m", "--message=")) and not end:
                i += 1  # `-m"$(…)"` / `--message="$(…)"`: a message, not a pathspec
                continue
            o["paths"].append(None)  # a dynamic word outside an option value: may be a pathspec
            i += 1
            continue
        if a == "--":
            end = True
        elif a.startswith("--"):
            name, eq, val = a.partition("=")
            if name in LONG_VALUE and not eq:
                val = vals[i + 1] if i + 1 < len(vals) else None
                i += 1
            if name == "--all":
                o["all"] = True
            elif name == "--include":
                o["include"] = True
            elif name == "--only":
                o["only"] = True
            elif name == "--amend":
                o["amend"] = True
            elif name in ("--no-verify",):
                o["no_verify"] = True
            elif name in ("--interactive", "--patch"):
                o["interactive"] = True
            elif name == "--pathspec-from-file":
                o["pathspec_file"] = True
            elif name == "--dry-run":
                o["dry_run"] = True
            elif name == "--fixup" and (val is None or str(val).startswith(("amend:", "reword:"))):
                o["fixup_amend"] = True
        elif a.startswith("-") and len(a) > 1:
            j = 1
            while j < len(a):
                ch = a[j]
                if ch in SHORT_VALUE:
                    if j == len(a) - 1:
                        i += 1
                    break
                if ch in SHORT_OPTIONAL:
                    break
                if ch == "a":
                    o["all"] = True
                elif ch == "i":
                    o["include"] = True
                elif ch == "o":
                    o["only"] = True
                elif ch == "n":
                    o["no_verify"] = True
                elif ch == "p":
                    o["interactive"] = True
                j += 1
        else:
            o["paths"].append(a)
        i += 1
    return o


def forms(o):
    out = [n for n, k in (("-a", "all"), ("--include", "include"), ("--only", "only"), ("--amend", "amend"),
                          ("--no-verify", "no_verify"), ("--fixup=amend", "fixup_amend"), ("--patch", "interactive"),
                          ("--pathspec-from-file", "pathspec_file")) if o[k]]
    if o["paths"]:
        out.append("a pathspec")
    return out


# ---- git config ----

CONFIG_READ = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l", "--show-origin",
               "--show-scope", "--name-only", "--null", "-z", "--type", "--bool", "--int", "--path",
               "--default", "--includes", "--no-includes"}
CONFIG_SCOPE = {"--local", "--global", "--system", "--worktree", "--file", "-f", "--blob"}
CONFIG_SUBS_WRITE = {"set", "unset", "edit", "rename-section", "remove-section"}
CONFIG_SUBS_READ = {"get", "list"}


def _include_key(k):
    kl = (k or "").lower()
    return kl == "include.path" or kl.startswith("includeif.")


def _hook_key(k):
    """Keys that change which hooks run or which commands git runs: hooks, aliases, and included config files
    (include.path / includeIf.<cond>.path can bring in any of them)."""
    kl = (k or "").lower()
    return kl == "core.hookspath" or kl.startswith(("alias.", "hook.", "includeif.")) or kl == "include.path"


def config_write(args):
    """The hook/alias key a `git config` call writes ("*" when it may write anything), or None."""
    vals = [w.value for w in args]
    if any(v is None for v in vals):
        return "*" if any(v is None or _hook_key(v) for v in vals) else None
    if vals and vals[0] in CONFIG_SUBS_READ:
        return None
    if vals and vals[0] in CONFIG_SUBS_WRITE:
        if vals[0] == "edit":
            return "*"
        keys = [v for v in vals[1:] if not v.startswith("-")]
        if keys and vals[0] == "unset" and _include_key(keys[0]):
            return None  # removing an include brings nothing in
        return keys[0] if keys and _hook_key(keys[0]) else None
    pos, read, write_flag, unset = [], False, False, False
    i = 0
    while i < len(vals):
        a = vals[i]
        if a in ("--file", "-f", "--blob", "--type", "--default"):
            i += 2
            continue
        if a in ("--edit", "-e"):
            return "*"
        if a.startswith("--unset") or a in ("--replace-all", "--add", "--rename-section", "--remove-section"):
            write_flag = True
            unset = unset or a.startswith("--unset")
        elif a in CONFIG_READ or a.startswith(("--get", "--type=", "--default=", "--file=")):
            read = True
        elif a in CONFIG_SCOPE:
            pass
        elif not a.startswith("-"):
            pos.append(a)
        i += 1
    if not pos:
        return None
    key = pos[0]
    if not _hook_key(key):
        return None
    if unset and _include_key(key):
        return None  # removing an include brings nothing in (hooks and aliases stay protected both ways)
    if write_flag or (not read and len(pos) >= 2):
        return key
    return None


# ---- plumbing ----

def plumbing(sub, args):
    """A sentence when a plumbing command may write refs or the index in ways the guard cannot check."""
    vals = [w.value for w in args]
    if sub in ("commit-tree", "update-ref", "replace", "fast-import", "filter-branch", "filter-repo"):
        return "git %s writes commits or refs directly" % sub
    if sub == "symbolic-ref":
        pos = [v for v in vals if v is None or not v.startswith("-")]
        if len(pos) >= 2 or "-d" in vals or "--delete" in vals:
            return "git symbolic-ref changes a ref"
    if sub == "read-tree":
        if any(v is None or not v.startswith("-") or v in ("-m", "--reset", "-u") for v in vals):
            return "git read-tree replaces the index"
    if sub == "update-index":
        if any(v not in ("--refresh", "--really-refresh", "-q", "--ignore-missing") for v in vals):
            return "git update-index stages content without check_commit.py --stage"
    if sub == "apply" and any(v in ("--cached", "--index") for v in vals):
        return "git apply --cached stages a patch without check_commit.py --stage"
    if sub == "checkout-index" and any(v in ("-a", "--all") for v in vals):
        return "git checkout-index --all overwrites the work tree from the index"
    return None


# ---- gh api ----

WRITE_METHODS = ("PUT", "POST", "PATCH", "DELETE")
FIELD_OPTS = ("-f", "-F", "--field", "--raw-field", "--input")


def gh_api(argv, studio_paths):
    """A sentence when `gh api …` may write Studio files through the GitHub API (argv without `gh`)."""
    if len(argv) < 2 or argv[0] != "api":
        return None
    method, endpoint, fields, query_from_file = None, None, False, False
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("-X", "--method"):
            method = argv[i + 1] if i + 1 < len(argv) else None
            i += 2
            continue
        if a is not None and a.startswith("--method="):
            method = a.split("=", 1)[1]
        elif a is not None and a.startswith("-X") and len(a) > 2:
            method = a[2:]
        elif a in FIELD_OPTS or (a is not None and a.startswith(tuple(f + "=" for f in FIELD_OPTS if f.startswith("--")))):
            fields = True
            val = argv[i + 1] if a in FIELD_OPTS and i + 1 < len(argv) else (a.split("=", 1)[1] if a and "=" in a else None)
            if val is None or (isinstance(val, str) and "=@" in val and val.split("=", 1)[0] == "query"):
                query_from_file = True
            if a in FIELD_OPTS:
                i += 2
                continue
        elif a in ("-H", "--header", "-p", "--preview", "--jq", "-q", "-t", "--template", "--hostname", "--cache"):
            i += 2
            continue
        elif endpoint is None and (a is None or not a.startswith("-")):
            endpoint = a
        i += 1
    if endpoint is None:
        return "gh api with an endpoint the guard cannot read"
    m = (method or ("POST" if fields else "GET"))
    if m is None or (isinstance(m, str) and m.upper() not in ("GET", "HEAD") + WRITE_METHODS):
        return "gh api with a method the guard cannot read"
    import urllib.parse
    ep = urllib.parse.unquote(endpoint).lstrip("/")
    if ep == "graphql":
        if query_from_file:
            return "gh api graphql reads its query from a file the guard cannot check"
        text = " ".join(x for x in argv if x)
        if "createCommitOnBranch" in text or any(x is None for x in argv):
            return "gh api graphql may create a commit"
        return None
    if m.upper() not in WRITE_METHODS:
        return None
    mm = re.match(r"^repos/[^/]+/[^/]+/(.*)$", ep)
    if not mm:
        return None
    rest = mm.group(1)
    if re.match(r"^git/(blobs|trees|commits|refs)(/|$)", rest):
        return "gh api %s writes git objects or refs on GitHub" % rest.split("?")[0]
    if rest.startswith("contents/"):
        p = rest[len("contents/"):].split("?")[0].strip("/")
        for sp in studio_paths:
            if p == sp or p.startswith(sp.rstrip("/") + "/") or (sp.endswith("std-") and p.startswith(sp)):
                return "gh api writes %s on GitHub without Studio's commit checks" % p
    return None


# ---- a commit's Studio paths and evidence (needs git) ----

class Outcome(object):
    def __init__(self):
        self.deny = None  # (rule, text)
        self.studio = []  # Studio paths the commit would record
        self.ok = None  # commit-ok.json
        self.tree = None
        self.head = None
        self.top = None


def _studio_names(cctx, names, git):
    out = []
    for p in names:
        if p == ".gitignore":
            from ..commit import spaths
            old = git.show("%s:.gitignore" % cctx.head) if cctx.head else None
            try:
                with open(os.path.join(cctx.top, ".gitignore"), "rb") as f:
                    new = f.read()
            except OSError:
                new = None
            if spaths.gitignore_kind(old, new) in ("studio", "mixed", "broken"):
                out.append(p)
        elif cctx.cls.is_studio(p) or cctx.cls.is_local(p):
            out.append(p)
    return out


def _names(raw):
    return [p for p in raw.split("\0") if p]


SCRIPTS_REL = ".claude/studio/scripts/"


def scripts_vs_plugin(git, plugin_scripts):
    """H10 on the guard's side (m0f-plan §2.3): the committed copy of Studio's scripts is byte-identical to the plugin's
    own files and complete — catches a copy edited together with its manifest."""
    from .. import manifest
    want = manifest.files(plugin_scripts) + [manifest.NAME]
    raw = git.text("ls-files", "-s", "-z", "--", ":(literal)" + SCRIPTS_REL.rstrip("/"))
    have = set()
    for rec in raw.split("\0"):
        if rec:
            have.add(rec.split("\t", 1)[1][len(SCRIPTS_REL):])
    out = []
    if have != set(want):
        diff = sorted(have ^ set(want))
        out.append("the committed copy of Studio's scripts is not the plugin's file set (%s)" % ", ".join(diff[:3]))
        return out
    git.prefetch([":" + SCRIPTS_REL + r for r in want])
    bad = []
    for r in want:
        try:
            with open(os.path.join(plugin_scripts, r), "rb") as f:
                mine = f.read()
        except OSError:
            mine = None
        if git.show(":" + SCRIPTS_REL + r) != mine:
            bad.append(r)
    if bad:
        out.append("the committed copy of Studio's scripts differs from the plugin's (%s)" % ", ".join(bad[:3]))
    return out


def evaluate(worktree, env, extra_env, opts, budget=8.0, plugin_scripts=None):
    """Outcome of `git commit` with options `opts` in `worktree` (a harness repository)."""
    from ..commit import checks, gitx, kinds, okfile
    from . import gitprobe
    out = Outcome()
    try:
        git = gitprobe.budget_git(worktree, env, budget=budget, extra_env=extra_env)
        cctx = checks.Ctx(git, env, kinds.registry({}))
        st = checks.Staged(cctx)
        out.top, out.head = cctx.top, cctx.head
        touched = set(st.studio)
        if opts["all"]:
            touched |= set(_studio_names(cctx, _names(git.text("diff", "--name-only", "-z", "--no-renames",
                                                                  "--no-ext-diff", "--no-textconv", "--")), git))
        if opts["paths"] or opts["pathspec_file"]:
            literal = [p for p in opts["paths"] if p is not None]
            if len(literal) != len(opts["paths"]) or opts["pathspec_file"]:
                # a pathspec the guard cannot read: any uncommitted Studio change counts
                base = cctx.head or git.empty_tree()
                changed = _names(git.text("diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", base, "--"))
            elif cctx.head:
                changed = _names(git.text("diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", cctx.head,
                                          "--", *literal))
            else:
                changed = _names(git.text("ls-files", "-z", "--", *literal))
            touched |= set(_studio_names(cctx, changed, git))
        if (opts["amend"] or opts["fixup_amend"]) and cctx.head:
            touched |= set(_studio_names(cctx, _names(git.text("diff-tree", "--no-commit-id", "-r", "--name-only",
                                                                  "-z", "--no-renames", "--root", cctx.head)), git))
        fs = forms(opts)
        if fs and touched:
            out.deny = ("G-COMMITFORM", "git commit %s would record Studio files (%s) without Studio's commit "
                                        "checks. Studio changes are committed only as: python3 "
                                        ".claude/studio/scripts/check_commit.py --stage … → ask the person \"커밋 "
                                        "<tree12>\" → git commit -m …" % (", ".join(fs), ", ".join(sorted(touched)[:3])))
            return out
        out.studio = sorted(st.studio)
        if not out.studio:
            return out
        ok, why = okfile.read(cctx.top)
        if ok is None:
            out.deny = ("G-COMMIT", "Studio files are staged but Studio did not prepare this commit (commit-ok.json "
                                    "%s) — run \"python3 .claude/studio/scripts/check_commit.py --stage …\" and ask the "
                                    "person." % why)
            return out
        tree = git.write_tree()
        out.ok, out.tree = ok, tree
        problems = []
        if ok.get("tree") != tree:
            problems.append("the staged tree %s is not the one Studio prepared (%s)" % (tree[:12],
                                                                                    str(ok.get("tree"))[:12]))
        if ok.get("head") != cctx.head:
            problems.append("HEAD moved since Studio prepared this commit")
        if ok.get("studio_root") != cctx.roots[0]:
            problems.append("studio_root changed since Studio prepared this commit")
        if sorted(ok.get("paths") or []) != out.studio:
            problems.append("the staged Studio paths are not the ones Studio prepared")
        if (ok.get("in_progress") or None) != (st.progress or None):
            problems.append("commit-ok.json was prepared for a different situation")
        if ok.get("label") != okfile.LABEL % tree[:12]:
            problems.append("commit-ok.json's label is not \"%s\"" % (okfile.LABEL % tree[:12]))
        if not problems and any(p.startswith(SCRIPTS_REL) for p in out.studio):
            problems += scripts_vs_plugin(git, plugin_scripts)
        if problems:
            out.deny = ("G-COMMIT", "%s — stage again (check_commit.py --stage) and ask the person again." %
                        "; ".join(problems))
        return out
    except gitx.GitError as e:
        out.deny = ("G-COMMIT", "could not check this commit's Studio files (%s)." % e)
        return out
