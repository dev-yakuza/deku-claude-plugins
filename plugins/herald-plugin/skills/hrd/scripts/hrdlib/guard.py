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
WRITE_HINT = re.compile(r"(>>?|\btee\b|\bsed\s+-i|\bmv\b|\bcp\b|\brm\b|\btruncate\b|\bdd\b|"
                        r"open\([^)]*['\"][wa]|write_text|\bperl\s+-p?i|\bln\b|\bchmod\b)")


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


def staged_after(root, argv):
    staged = set(commits.staged_paths(root))
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


def check_bash(root, cfg, cmd):
    base = cfg.base
    deploy = (cfg.get("commands", "deploy") or "").strip()
    for seg in segments(cmd):
        try:
            argv = shlex.split(seg)
        except ValueError:
            argv = seg.split()
        if not argv:
            continue
        joined = " ".join(argv)
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
        if deploy and deploy in joined:
            if unattended():
                decide("deny", "unattended sessions may not deploy (the batch runner does).")
            decide("ask", "running the deploy command publishes the whole base branch — confirm this is `ship` step 7.")
        # 3. writes to protected paths through the shell
        if WRITE_HINT.search(seg):
            for token in argv:
                what = classify_path(rel(root, token))
                if what:
                    protect("shell write to the %s." % what)
                if rel(root, token) == CONFIG:
                    protect("shell write to %s (protected keys must change through `ask`)." % CONFIG)
        # 4. git commit / push on base or herald branches
        if argv[0] == "git" and len(argv) > 1:
            sub = argv[1]
            branch = current_branch(root)
            if sub == "push":
                if unattended() and any(t in ("--all", "--mirror") for t in argv[2:]):
                    decide("deny", "unattended sessions may not push --all/--mirror.")
                targets = [t.lstrip("+") for t in argv[2:] if not t.startswith("-")]
                to_base = (branch == base and not any(":" in t for t in targets)) or \
                          any(t in (base, "HEAD:%s" % base, "refs/heads/%s" % base) or t.endswith(":" + base) for t in targets)
                if to_base and unattended():
                    decide("deny", "unattended sessions may not push the base branch.")
            if sub == "commit":
                if branch == base:
                    if unattended():
                        decide("deny", "unattended sessions may not commit on the base branch.")
                    staged = staged_after(root, argv)
                    juris = jurisdiction(root, cfg)
                    allowed = commits.all_base_globs(cfg)
                    bad = [p for p in staged if commits._match(p, juris) and not commits._match(p, allowed)]
                    if bad:
                        decide("deny", "base commits may not touch Herald paths outside the allowed record/harness set: %s"
                               % ", ".join(bad[:5]))
                parsed = parse_branch(branch)
                if parsed or branch.startswith("herald-revert/"):
                    staged = staged_after(root, argv)
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
