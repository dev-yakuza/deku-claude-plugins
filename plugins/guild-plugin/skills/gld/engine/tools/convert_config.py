#!/usr/bin/env -S python3 -I
"""Conversion script: 0.98.7 settings → `.claude/guild/` (design §9.2 stage 0, §7.10, §7.2-2, I11) — U16.

    python3 -I convert_config.py --repo-root <main checkout> [--rev <ref>] [--out <dir>] [--dry-run]
                                 [--template <feature.json>] [--host-os darwin|linux]
                                 [--not-checked-locally NAME=note …] [--candidate-exception KEY …]
                                 [--decisions tools/decisions/<repo>.json]

Reads the stable edition's config.json (read only — never writes the stable folder or
anything inside the repository) and `.github/workflows`, `lefthook.yml`, and proposes for
human review (default `--out` = `tools/out/<repo>/`):
  - config.json (schemas/repo-config): named commands setup · test · e2e · vrt · pre-push
    checks · CI-derived lint/typecheck/build, plugin entries ac-format · ac-coverage ·
    verify-gate, path rules (verification from visual.tests / visual.baselines /
    visual.config_files / commands + I11 b command definition files), registry hosts
    (incl. package-manager distribution hosts, F3), cache env → {cache} (paths only), run_env
    (literal non-path values, P3-0), secret paths, worktree prepare list, toolchain prepare
    (`flutter precache` for Flutter repos), not_checked_locally (CI steps that cannot run
    locally, plus `--not-checked-locally` commands a human moved there after the base-green check);
  - procedures/feature.yaml (JSON text) from the plugin default template `data/templates/feature.json`
    (U15): `run` steps the repository has no command for are removed, one `run` step is added
    for every verification command the template lacks; the result must pass the engine's
    template checker;
  - config.with-candidate-exceptions.json (with `--candidate-exception`): measured, NOT approved
    sandbox exceptions — the user temp folder as the token `{user_tmp}`, never a machine path;
  - report.md: everything a human has to decide, including I11 a (stable role bodies' write
    paths as `outputs` candidates — report only);
  - commit/.claude/guild/{config.json, procedures/feature.yaml, roles/leader.md}: the same files as the tree
    a human copies into the repository unchanged (`cp -R commit/.claude <repo>/`).
With `--decisions` (CFG): the human decisions of the base-green check — approved sandbox
exceptions, commands moved to `not_checked_locally`, command texts a human wrote (a quarantine
exclusion), the quarantine list — are applied, checked fail-closed (`load_decisions`).
A human reviews and commits; then the base-green check in the sandbox (§7.10, tools/base_check.py).

`--stage 3` (stage-3 scope V19) writes the stage-3 proposal into tools/out/<repo>/stage3/ instead: the
plugin commands repro-red · safety-net-proof · verification-frozen · no-production-change, verification
`category` (E33), `test-code` and `safety-net` path rules (E4), risk-gate and irreversible-change rule
CANDIDATES with their evidence (E25, E22), `followups_dry_run` (decisions `stage3`, user decision A4), a
repository copy of every stage-3 template (codes.STAGE3_TEMPLATES, run steps the repository lacks removed),
and the catalog roles check. A stage-2 engine refuses these settings: they are committed with the stage-3
merge (scope Q6), and the base-green check runs again then (§7.10).

`--init` (stage 4, S4-init VB2; called by gxengine/initconfig as a child) prints the init draft as JSON and
writes nothing: the stage-3 proposal of the revision, also for a repository without 0.98.x settings (H14:
CI → lefthook → manifest name table, tools/init_tables.json), every command with its source (codes.CommandSource
+ file:line) in `description`, and the questions (codes.InitQuestion) a human must answer. The answers come
back as `--decisions` (load_decisions(init=True)): the same commit and answers give the same text.

Principles (fail-closed, §1): only literal commands from the stable config / lefthook /
workflow `run:` steps are carried — never generated; a CI step that needs secrets, PR
context, `sudo`, shell logic, or rewrites the tree is NOT carried but listed in
`not_checked_locally`; anything unparsable is reported, never guessed.
"""

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ENGINE_ROOT)

from gxengine import codes, defaults, instructions, repoconfig  # noqa: E402

TOOL_VERSION = 1
STABLE_CONFIG = ".claude/guild/config.json"  # promote: literal; rename-exception: the 0.98.x settings file
STABLE_DIR = ".claude/guild/"  # promote: literal; rename-exception: the 0.98.x settings folder
PLUGIN_COMMANDS = ("ac-format", "ac-coverage", "verify-gate")
STAGE3_PLUGIN_COMMANDS = ("repro-red", "safety-net-proof", "verification-frozen", "no-production-change")
STABLE_COMMAND_KEYS = ("test", "lint", "typecheck", "build", "e2e", "vrt")
RESERVED_NAMES = {"setup", *PLUGIN_COMMANDS, *STAGE3_PLUGIN_COMMANDS, *STABLE_COMMAND_KEYS}
MAX_NAME = 64
SKIP_DIRS = ("node_modules/", "build/", ".dart_tool/", ".git/", "Pods/", ".gradle/", ".idea/")   # never scanned for credentials


# ======================================================================================
# A. A small YAML reader (the subset GitHub workflows and lefthook.yml use)
# ======================================================================================

class YamlError(ValueError):
    """The text is outside the supported YAML subset."""


_KEY = re.compile(r"""^(?P<k>"(?:[^"\\]|\\.)*"|'[^']*'|[^\s#"'\[\]{},&*!|>%@`-][^:]*?|-[^\s:][^:]*?)\s*:(?:\s+(?P<v>.*)|)$""")


def _strip_comment(s):
    out, quote = [], None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'" and (i == 0 or s[i - 1] in " \t[{,:"):
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        try:
            return json.loads(s)
        except ValueError:
            return s[1:-1]
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


def _scalar(s):
    s = s.strip()
    if s in ("", "~", "null", "Null", "NULL"):
        return None
    return _unquote(s)


def _split_flow(s):
    """Split the inside of a flow collection on top-level commas."""
    parts, depth, quote, cur = [], 0, None, []
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "[{":
            depth += 1
            cur.append(ch)
        elif ch in "]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def _flow(s):
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        return [_flow(p) for p in _split_flow(s[1:-1])]
    if s.startswith("{") and s.endswith("}"):
        out = {}
        for p in _split_flow(s[1:-1]):
            m = _KEY.match(p.strip())
            if not m:
                raise YamlError(f"bad flow mapping entry: {p!r}")
            out[_unquote(m.group("k"))] = _flow(m.group("v") or "")
        return out
    return _scalar(s)


def _balanced(s):
    depth, quote = 0, None
    for ch in s:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
    return depth <= 0 and quote is None


class _Yaml:
    def __init__(self, text):
        self.lines = text.replace("\t", "    ").splitlines()
        self.i = 0

    def peek(self):
        while self.i < len(self.lines):
            raw = self.lines[self.i]
            st = raw.strip()
            if not st or st.startswith("#") or st in ("---", "..."):
                self.i += 1
                continue
            return len(raw) - len(raw.lstrip(" ")), st
        return None

    def node(self, min_indent):
        p = self.peek()
        if p is None or p[0] < min_indent:
            return None
        ind, st = p
        if st == "-" or st.startswith("- "):
            return self.seq(ind)
        if _KEY.match(_strip_comment(st)):
            return self.mapping(ind)
        return self.plain(ind - 1)

    def seq(self, ind):
        items = []
        while True:
            p = self.peek()
            if p is None or p[0] != ind or not (p[1] == "-" or p[1].startswith("- ")):
                return items
            rest = p[1][1:].lstrip(" ")
            if not rest or rest.startswith("#"):
                self.i += 1
                items.append(self.node(ind + 1))
                continue
            child = ind + (len(p[1]) - len(rest))
            self.lines[self.i] = " " * child + rest
            items.append(self.node(child))

    def mapping(self, ind):
        out = {}
        while True:
            p = self.peek()
            if p is None or p[0] != ind:
                return out
            m = _KEY.match(_strip_comment(p[1]))
            if not m or p[1].startswith("- "):
                return out
            key = _unquote(m.group("k"))
            val = (m.group("v") or "").strip()
            self.i += 1
            if val == "":
                nxt = self.peek()
                if nxt and nxt[0] > ind:
                    out[key] = self.node(ind + 1)
                elif nxt and nxt[0] == ind and (nxt[1] == "-" or nxt[1].startswith("- ")):
                    out[key] = self.seq(ind)
                else:
                    out[key] = None
            elif val[0] in "|>":
                out[key] = self.block(ind, val)
            elif val[0] in "[{":
                text = val
                while not _balanced(text) and self.i < len(self.lines):
                    text += " " + _strip_comment(self.lines[self.i].strip())
                    self.i += 1
                if not _balanced(text):
                    raise YamlError(f"unterminated flow collection at key {key!r}")
                out[key] = _flow(text)
            elif val[0] in "\"'":
                text = val
                while not self._closed(text) and self.i < len(self.lines):
                    text += " " + self.lines[self.i].strip()
                    self.i += 1
                out[key] = _scalar(_strip_comment(text) if self._closed(text) else text)
            else:
                text = _strip_comment(val)
                while self.i < len(self.lines):
                    raw = self.lines[self.i]
                    st = raw.strip()
                    if not st or st.startswith("#"):
                        break
                    if len(raw) - len(raw.lstrip(" ")) <= ind:
                        break
                    text += " " + _strip_comment(st)
                    self.i += 1
                out[key] = _scalar(text)

    @staticmethod
    def _closed(text):
        q = text[0]
        return len(text) >= 2 and text.endswith(q) and not (q == '"' and text.endswith('\\"') and not text.endswith('\\\\"'))

    def plain(self, parent):
        raw = self.lines[self.i]
        text = _strip_comment(raw.strip())
        self.i += 1
        while self.i < len(self.lines):
            nxt = self.lines[self.i]
            st = nxt.strip()
            if not st or st.startswith("#") or len(nxt) - len(nxt.lstrip(" ")) <= parent:
                break
            text += " " + _strip_comment(st)
            self.i += 1
        return _scalar(text)

    def block(self, ind, header):
        style, chomp = header[0], ""
        for ch in header[1:]:
            if ch in "+-":
                chomp = ch
        body, block_indent = [], None
        while self.i < len(self.lines):
            raw = self.lines[self.i]
            if raw.strip() == "":
                body.append("")
                self.i += 1
                continue
            cur = len(raw) - len(raw.lstrip(" "))
            if cur <= ind:
                break
            if block_indent is None:
                block_indent = cur
            body.append(raw[block_indent:] if cur >= block_indent else raw.lstrip(" "))
            self.i += 1
        while body and body[-1] == "" and chomp != "+":
            body.pop()
        if style == "|":
            text = "\n".join(body)
        else:
            text, prev_blank = "", False
            for line in body:
                if line == "":
                    text += "\n"
                    prev_blank = True
                else:
                    text += ("" if (prev_blank or not text) else " ") + line
                    prev_blank = False
        return text if chomp == "-" else text + "\n"


def parse_yaml(text):
    """Parse the supported YAML subset into dict / list / str / None. Raises YamlError."""
    y = _Yaml(text)
    value = y.node(0)
    if y.peek() is not None:
        raise YamlError(f"unparsed content at line {y.i + 1}: {y.lines[y.i].strip()[:60]!r}")
    return value


# ======================================================================================
# B. Sources (read only)
# ======================================================================================

class FsSource:
    """The repository as files on disk."""

    def __init__(self, root):
        self.root = root
        self.label = f"{root} (working tree)"

    def files(self):
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "build", ".dart_tool")]
            for f in filenames:
                out.append(os.path.relpath(os.path.join(dirpath, f), self.root).replace(os.sep, "/"))
        return sorted(out)

    def read(self, path):
        try:
            with open(os.path.join(self.root, path), encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def untracked(self):
        return []

    def has_dir(self, rel):
        return os.path.isdir(os.path.join(self.root, rel))


class GitSource:
    """The repository at a fixed revision (blobs only), plus the untracked/ignored listing of the checkout."""

    def __init__(self, root, rev):
        self.root, self.rev = root, rev
        self._files = None
        sha = self._git("rev-parse", "--verify", rev + "^{commit}").strip()
        self.sha = sha
        self.label = f"{root} @ {rev} ({sha[:12]})"

    def _git(self, *args, check=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
        p = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", self.root, *args],
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        if check and p.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
        return p.stdout if p.returncode == 0 else None

    def files(self):
        if self._files is None:
            self._files = sorted(p for p in self._git("ls-tree", "-r", "--name-only", "-z", self.sha).split("\0") if p)
        return self._files

    def read(self, path):
        return self._git("show", f"{self.sha}:{path}", check=False)

    def has_dir(self, rel):
        """Does the main checkout (working tree, not the revision) have this folder? — for ignored generated files."""
        return os.path.isdir(os.path.join(self.root, rel))

    def untracked(self):
        skip = [f"--exclude={d.rstrip('/')}" for d in SKIP_DIRS if d != ".git/"]
        out = self._git("ls-files", "-o", "-z", *skip, check=False) or ""
        return sorted(p for p in out.split("\0") if p)


# ======================================================================================
# C. Command text helpers
# ======================================================================================

_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
TRANSPARENT_WRAPPERS = ("with_clean_git_env.sh",)   # repo wrappers that only clean the environment
PM_PROGRAMS = ("pnpm", "npm", "yarn")
SIMPLE_SUBCOMMAND_PROGRAMS = ("flutter", "pnpm", "npm", "yarn", "turbo", "make", "cargo", "go")
SCRIPT_RUNNERS = ("bash", "sh", "zsh", "python3", "python", "node", "ruby", "perl")
SCRIPT_EXT = (".sh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb")
DIAGNOSTIC = ("echo", "printf", "df", "free", "nproc", "ls", "cat", "pwd", "env", "true", "set", "export", "cd", "mkdir", "sleep", "date", "uname", "which")
INSTALL_RE = re.compile(
    r"^(?:(?:npm|pnpm|yarn)\s+(?:ci|install|i|add)\b|npm\s+install\b|(?:flutter|dart)\s+pub\s+(?:get|upgrade)\b|"
    r"pip3?\s+install\b|corepack\b|bundle\s+install\b|gem\s+install\b|brew\s+install\b)")
MUTATING_RE = re.compile(r"(--update-goldens|--fix\b|--write\b|\s-w\b|--update-snapshots?|\s-u\b|--autofix|--apply\b)")
# Anything that needs the CI machine, the PR, secrets or the network beyond the registry.
NOT_LOCAL_RE = [
    (re.compile(r"\$\{\{\s*secrets\."), "needs secrets"),
    (re.compile(r"\$\{\{\s*(?:github|runner|matrix|needs|steps|inputs|env)\b"), "uses a workflow expression (PR context / CI runner values)"),
    (re.compile(r"\$\{\{"), "uses a workflow expression"),
    (re.compile(r"\$GITHUB_|\$RUNNER_|\$\{GITHUB_"), "uses GitHub runner variables"),
    (re.compile(r"(^|[\s;&|])sudo\s"), "needs sudo (CI machine setup)"),
    (re.compile(r"\bapt(?:-get)?\s+install\b|\bbrew\s+install\b"), "installs system packages"),
    (re.compile(r"(^|[\s;&|])gh\s"), "calls the GitHub CLI"),
    (re.compile(r"\bgit\s+(?:push|checkout|fetch|switch|reset|rebase|merge|tag)\b"), "rewrites git state"),
    (re.compile(r"\bdocker\b|\bkubectl\b|\bterraform\b|\bfastlane\b|\bgcloud\b|\bfirebase\s+deploy\b|\bgh-pages\b|\bvercel\b|\bnetlify\b|\bwrangler\b"), "deploy / infrastructure tool"),
    (re.compile(r"\b(?:npm|pnpm|yarn)\s+publish\b|\bdeploy\b|\bpublish\b"), "deploy / publish step"),
    (re.compile(r"\badb\b|\bemulator\b|\bsdkmanager\b|\budevadm\b"), "needs an Android emulator / SDK manager"),
]
SHELL_LOGIC_RE = re.compile(r"^(?:if|for|while|case|until|function)\b|^\w+\(\)\s*\{|<<-?\s*['\"]?\w+")
HOST_FOREIGN_TARGETS = {"darwin": ("windows", "linux"), "linux": ("windows", "macos", "ios"), "win32": ("macos", "ios", "linux")}


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not s:
        return ""
    if not s[0].isalpha():
        s = "c-" + s
    return s[:MAX_NAME].strip("-")


def split_segments(cmd):
    """Split a shell line on top-level && / ; (not inside quotes)."""
    segs, cur, quote, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif cmd.startswith("&&", i):
            segs.append("".join(cur))
            cur, i = [], i + 1
        elif ch == ";":
            segs.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    segs.append("".join(cur))
    return [s.strip() for s in segs if s.strip()]


def _tokens(seg):
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.split()


def seg_key(seg):
    """A coarse identity of one shell segment: what it runs, not with which options."""
    toks = _tokens(seg)
    while toks and _ENV_ASSIGN.match(toks[0]):
        toks.pop(0)
    changed = True
    while changed and toks:
        changed = False
        if toks[0] in ("npx", "time", "fvm", "exec"):
            toks.pop(0)
            changed = True
        elif toks[0] in SCRIPT_RUNNERS and len(toks) > 1 and os.path.basename(toks[1]) in TRANSPARENT_WRAPPERS:
            toks = toks[2:]
            changed = True
        elif toks[0] == "pnpm" and len(toks) > 1 and toks[1] == "exec":
            toks = toks[2:]
            changed = True
    if not toks:
        return None
    first = toks[0]
    if first in SCRIPT_RUNNERS and len(toks) > 1:
        return ("script", toks[1])
    if first.endswith(SCRIPT_EXT):
        return ("script", first)
    if first in PM_PROGRAMS and len(toks) > 1:
        sub = toks[1]
        if sub in ("run", "run-script", "exec", "dlx") and len(toks) > 2:
            sub = toks[2]
        return ("pm", sub)
    if len(toks) > 1 and re.match(r"^[a-z][a-z0-9-]*$", toks[1]):
        return (first, toks[1])
    return (first, "")


def cmd_keys(cmd):
    return {k for k in (seg_key(s) for s in split_segments(cmd)) if k}


def name_for(key, hint=None):
    if hint and slug(hint):
        return slug(hint)
    kind, sub = key
    if kind == "script":
        stem = os.path.splitext(os.path.basename(sub))[0]
        return slug(stem) or "check"
    if kind == "pm":
        return slug(sub) or "check"
    if kind in SIMPLE_SUBCOMMAND_PROGRAMS and sub:
        return slug(sub)
    return slug(f"{kind}-{sub}" if sub else kind) or "check"


def unwrap_hook_command(run):
    """`bash x/pre_push_scope.sh <name> -- <inner>` → inner (the scope wrapper is a push-time optimisation)."""
    m = re.match(r"^\s*(?:bash|sh)\s+\S*scope\S*\.sh\s+\S+\s+--\s+(.*)$", run, re.S)
    return m.group(1).strip() if m else run.strip()


def host_filter(cmd, host_os):
    """Drop `&&`-chained parts that target a platform this host cannot run. → (kept_cmd | None, [dropped])."""
    foreign = HOST_FOREIGN_TARGETS.get(host_os, ())
    parts = [p.strip() for p in cmd.split("&&")] if "&&" in cmd else [cmd.strip()]
    kept, dropped = [], []
    for p in parts:
        if any(re.search(rf"\b{t}\b", p) for t in foreign):
            dropped.append(p)
        else:
            kept.append(p)
    return (" && ".join(kept) if kept else None), dropped


def valid_glob(g):
    return bool(g) and not g.startswith("/") and not re.search(r"\s", g) and ".." not in g.split("/")


def glob_to_re(g):
    """A converter-local glob → regex, used only to test whether a candidate rule matches any tracked file."""
    out, i = [], 0
    while i < len(g):
        if g.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif g.startswith("**", i):
            out.append(".*")
            i += 2
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        elif g[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


# ======================================================================================
# D. CI (GitHub workflows, composite actions, lefthook) → candidate commands
# ======================================================================================

class Candidate:
    def __init__(self, cmd, origin, hint=None, timeout=None, env=None, source=None, path=None):
        self.cmd, self.origin, self.hint, self.timeout, self.env = cmd, origin, hint, timeout, env or {}
        self.source, self.path = source, path


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _triggers(doc):
    on = doc.get("on") if isinstance(doc, dict) else None
    if on is None and isinstance(doc, dict):
        on = doc.get("true")
    if isinstance(on, dict):
        return set(on)
    return {str(x) for x in _as_list(on)}


def _is_check_workflow(doc):
    """A pull-request check, or a branch push that is not a tag release."""
    on = doc.get("on")
    if on is None:
        on = doc.get("true")
    if isinstance(on, dict):
        if "pull_request" in on or "pull_request_target" in on:
            return True
        push = on.get("push")
        return "push" in on and not (isinstance(push, dict) and ("tags" in push))
    names = {str(x) for x in _as_list(on)}
    return bool(names & {"pull_request", "pull_request_target", "push"})


def _literal_env(env):
    return {k: str(v) for k, v in (env or {}).items() if v is not None and "${{" not in str(v)}


def _env_is_secretish(env):
    return any("${{" in str(v) for v in (env or {}).values())


def script_commands(script):
    """Logical command lines of a `run:` script, or (None, reason) when it contains shell logic."""
    lines, cur = [], ""
    for raw in script.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.endswith("\\"):
            cur += s[:-1].rstrip() + " "
            continue
        lines.append((cur + s).strip())
        cur = ""
    if cur:
        lines.append(cur.strip())
    for ln in lines:
        if SHELL_LOGIC_RE.match(ln):
            return None, "shell logic (if / loops / heredoc)"
    return lines, None


def classify_command(cmd):
    """→ ("skip", why) | ("install", None) | ("not-local", why) | ("check", None)."""
    c = cmd.strip()
    for rx, why in NOT_LOCAL_RE:
        if rx.search(c):
            return "not-local", why
    first = _tokens(c)[0] if _tokens(c) else ""
    if first in DIAGNOSTIC and not re.search(r"&&", c):
        return "skip", "diagnostic / housekeeping"
    if INSTALL_RE.match(c):
        return "install", None
    if MUTATING_RE.search(c):
        return "not-local", "rewrites tracked files (golden / fix / write mode)"
    return "check", None


class CiScan:
    """Everything learned from the CI configuration."""

    def __init__(self):
        self.candidates = []       # [Candidate]
        self.install_env = {}      # literal env of install steps
        self.job_env = {}          # literal job/workflow env of jobs that contributed a candidate
        self.not_local = []        # [{"name", "note"}]
        self.notes = []            # free text for the report
        self.ignored_workflows = []
        self.unparsed = []
        self.prep_steps = []       # composite-action steps not adopted
        self.path = None           # the workflow file being read


def scan_workflows(src):
    scan = CiScan()
    files = src.files()
    actions = {}
    for path in files:
        if re.match(r"^\.github/actions/[^/]+/action\.ya?ml$", path):
            try:
                actions[path.split("/")[2]] = parse_yaml(src.read(path) or "")
            except YamlError as e:
                scan.unparsed.append(f"{path}: {e}")
    for path in files:
        if not re.match(r"^\.github/workflows/[^/]+\.ya?ml$", path):
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        scan.path = path
        try:
            doc = parse_yaml(src.read(path) or "")
        except YamlError as e:
            scan.unparsed.append(f"{path}: {e}")
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
            scan.unparsed.append(f"{path}: no jobs mapping")
            continue
        trig = _triggers(doc)
        if not _is_check_workflow(doc):
            scan.ignored_workflows.append(f"{path} (trigger: {', '.join(sorted(trig)) or 'none'} — not a PR / branch check)")
            continue
        wf_env = _literal_env(doc.get("env"))
        for jid, job in doc["jobs"].items():
            if not isinstance(job, dict):
                continue
            where = f"{stem}/{jid}"
            job_env = dict(wf_env)
            job_env.update(_literal_env(job.get("env")))
            timeout = job.get("timeout-minutes")
            reasons, cands = [], []
            steps = _expand_steps(job.get("steps"), actions, scan, where)
            for step, from_action in steps:
                _scan_step(step, from_action, where, timeout, scan, reasons, cands)
            if any(r in ENVIRONMENT_BOUND for r in reasons) and cands:
                reasons.append("whole job is bound to the CI machine — its other commands were not carried")
                cands = []
            if cands:
                scan.candidates += cands
                scan.job_env.update(job_env)
            if reasons:
                scan.not_local.append({"name": where, "note": "; ".join(sorted(set(reasons)))})
    return scan


def _expand_steps(steps, actions, scan, where):
    out = []
    for step in _as_list(steps):
        if not isinstance(step, dict):
            continue
        uses = str(step.get("uses") or "")
        if uses.startswith("./.github/actions/"):
            name = uses.split("/")[3]
            comp = actions.get(name) or {}
            for sub in _as_list((comp.get("runs") or {}).get("steps")):
                if isinstance(sub, dict):
                    out.append((sub, name))
            continue
        out.append((step, None))
    return out


QUIET_USES = ("actions/checkout", "actions/setup-", "actions/cache", "subosito/flutter-action", "pnpm/action-setup",
              "actions/upload-artifact", "actions/download-artifact", "actions/upload-pages-artifact", "gradle/")


ENVIRONMENT_BOUND = ("needs an Android emulator / SDK manager", "uses reactivecircus/android-emulator-runner")


def _scan_step(step, from_action, where, timeout, scan, reasons, cands):
    uses = str(step.get("uses") or "")
    run = step.get("run")
    label = step.get("name") or (uses or "run")
    env = step.get("env") if isinstance(step.get("env"), dict) else {}
    if uses and not run:
        if not any(uses.startswith(q) for q in QUIET_USES):
            reasons.append(f"uses {uses.split('@')[0]}")
        return
    if not isinstance(run, str):
        return
    if _env_is_secretish(env):
        reasons.append("a step env uses a workflow expression (secrets / PR context)")
        return
    lines, why = script_commands(run)
    if lines is None:
        reasons.append(f"step '{label}': {why}")
        return
    step_env = _literal_env(env)
    for ln in lines:
        kind, why = classify_command(ln)
        if kind == "skip":
            continue
        if kind == "install":
            scan.install_env.update(step_env)
            continue
        if kind == "not-local":
            reasons.append(why)
            continue
        if from_action:
            entry = f"{where} (composite action {from_action}): {ln}"
            if entry not in scan.prep_steps:
                scan.prep_steps.append(entry)
            continue
        cands.append(Candidate(ln, f"CI {where} › {label}", timeout=timeout, env=step_env,
                               source=codes.CommandSource.CI.value, path=scan.path))


def scan_lefthook(src):
    """pre-push commands of lefthook.yml → [Candidate]; (candidates, notes)."""
    out, notes = [], []
    for path in ("lefthook.yml", "lefthook.yaml", ".lefthook.yml"):
        text = src.read(path)
        if text is None:
            continue
        try:
            doc = parse_yaml(text)
        except YamlError as e:
            return [], [f"{path}: not parsed ({e}) — pre-push checks must be moved by hand"]
        block = (doc or {}).get("pre-push") or {}
        for name, spec in (block.get("commands") or {}).items():
            run = (spec or {}).get("run")
            if not isinstance(run, str):
                continue
            lines, why = script_commands(run)
            if lines is None or len(lines) != 1:
                notes.append(f"{path} pre-push '{name}': {why or 'several lines'} — move by hand")
                continue
            kind, why = classify_command(unwrap_hook_command(lines[0]))
            if kind not in ("check",):
                notes.append(f"{path} pre-push '{name}': not carried ({why or kind})")
                continue
            out.append(Candidate(unwrap_hook_command(lines[0]), f"{path} pre-push '{name}'", hint=name,
                                 source=codes.CommandSource.LEFTHOOK.value, path=path))
        return out, notes
    return [], notes


# ======================================================================================
# E. Stack detection and rule building
# ======================================================================================

class Stack:
    def __init__(self, files, src):
        fs = set(files)
        self.files = fs
        self.pnpm = "pnpm-lock.yaml" in fs
        self.npm = "package-lock.json" in fs
        self.yarn = "yarn.lock" in fs
        self.node = self.pnpm or self.npm or self.yarn or "package.json" in fs
        pub = src.read("pubspec.yaml") if "pubspec.yaml" in fs else None
        self.flutter = bool(pub and re.search(r"^\s*sdk:\s*flutter\b", pub, re.M))
        self.dart = pub is not None
        self.pubspec_lock = "pubspec.lock" in fs
        self.fvm = ".fvmrc" in fs
        self.fvm_version = None
        if self.fvm:
            try:
                self.fvm_version = str((json.loads(src.read(".fvmrc") or "{}") or {}).get("flutter") or "") or None
            except ValueError:
                self.fvm_version = None
        self.gradle = any(f.endswith(("build.gradle", "build.gradle.kts", "gradlew")) for f in fs)
        self.pods = any(os.path.basename(f) == "Podfile" for f in fs)
        self.turbo = "turbo.json" in fs
        self.python = bool({"requirements.txt", "pyproject.toml", "setup.py"} & fs)
        self.yarn_berry = ".yarnrc.yml" in fs


SQLITE_HOOK_CACHE = ".dart_tool/hooks_runner/shared/sqlite3"
FLUTTER_PATH_PREFIX = (
    'export PATH="$GLD_FLUTTER_ROOT/bin:$PATH"; '
    # The Dart tools write telemetry state under ~/.dart-tool before compiling a build hook and crash when they cannot
    # (measured, base_check). HOME moves into the Guild cache; git keeps reading the real user config.
    'export GIT_CONFIG_GLOBAL="${GIT_CONFIG_GLOBAL:-$HOME/.gitconfig}"; '
    'export HOME="$GLD_HOME"; mkdir -p "$HOME"; ')


TABLES_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "init_tables.json")


def load_tables(path=TABLES_FILE):
    """tools/init_tables.json (D10): names, programs, toolchains and lockfile host patterns by ecosystem."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


TABLES = load_tables()
FLUTTER_TOOLCHAIN = next(t for t in TABLES["toolchains"] if t["ecosystem"] == "flutter")
FLUTTER_UNPINNED_SOURCES = tuple(FLUTTER_TOOLCHAIN["sources"])


def flutter_sdk_sources(version):
    """`sync.from` of the Flutter SDK copy (P3-Z decision 4: outside the sandbox the engine
    only copies files, never runs one). A `.fvmrc` pin names exactly the fvm cache folder
    of that version (default FVM_CACHE_PATH = ~/fvm) — no silent fallback to another SDK;
    without a pin, the usual install folders in order (the report warns)."""
    if version:
        return [p.replace("{version}", version) for p in FLUTTER_TOOLCHAIN["pinned"]]
    return list(FLUTTER_UNPINNED_SOURCES)


def derive_setup(stack, env_prefix):
    parts = []
    if stack.pnpm:
        parts.append("pnpm install --frozen-lockfile")
    elif stack.npm:
        parts.append("npm ci")
    elif stack.yarn:
        parts.append("yarn install --frozen-lockfile")
    if stack.dart and stack.pubspec_lock:
        parts.append(("flutter" if stack.flutter else "dart") + " pub get --enforce-lockfile")
    if not parts:
        return None
    return env_prefix + " && ".join(parts)


def env_prefix(env):
    return "".join(f"export {k}={shlex.quote(v)}; " for k, v in sorted(env.items()))


def stack_cache_env(stack):
    env = {}
    if stack.node:
        env["npm_config_cache"] = "{cache}/npm"
        env["COREPACK_HOME"] = "{cache}/corepack"
    if stack.pnpm:
        env["npm_config_store_dir"] = "{cache}/pnpm-store"
        env["PNPM_HOME"] = "{cache}/pnpm"
    if stack.dart:
        env["PUB_CACHE"] = "{cache}/pub"
    if stack.flutter:
        env["GLD_FLUTTER_ROOT"] = "{cache}/flutter-sdk"
        env["GLD_HOME"] = "{cache}/home"
    if stack.gradle:
        env["GRADLE_USER_HOME"] = "{cache}/gradle"
    if stack.pods:
        env["CP_HOME_DIR"] = "{cache}/cocoapods"
    if stack.python:
        env["PIP_CACHE_DIR"] = "{cache}/pip"
    return env


def stack_run_env(stack):
    """Literal, non-path env for runs (repo-config `run_env`, P3-0) — never a `{cache}` path."""
    env = {}
    if stack.turbo:
        env["TURBO_TELEMETRY_DISABLED"] = "1"
    return env


def run_env_refusal(name, value):
    """Why `name=value` cannot go into `run_env` (the schema's rules + the engine's scrub), or None."""
    if not re.fullmatch(defaults.RUN_ENV_NAME, name):
        return "the name is not [A-Z_][A-Z0-9_]*"
    if any(w in name for w in defaults.RUN_ENV_SECRET_WORDS):
        return "the name looks like a secret"
    if name in defaults.RUN_ENV_RESERVED or name.startswith(defaults.RUN_ENV_RESERVED_PREFIXES):
        return "the engine sets or scrubs this name"
    if any(fnmatch.fnmatchcase(name, p) for p in defaults.ENV_SCRUB_PATTERNS):
        return "the engine scrubs this name"
    if re.search(r"[{}\x00-\x1f\x7f]", value):
        return "the value has braces or control characters"
    if value.startswith(("/", "~")) or "$" in value:
        return "the value is a path or an expansion (cache paths go to cache_env as {cache}/…)"
    return None


def stack_registry_hosts(stack, cmds_text):
    hosts = []
    if stack.node:
        hosts.append("registry.npmjs.org")
        if stack.yarn_berry or stack.yarn:
            hosts.append("repo.yarnpkg.com")
    if stack.dart:
        hosts += ["pub.dev", "storage.googleapis.com"]
    if stack.gradle and re.search(r"\b(apk|appbundle|aar|gradle)\b", cmds_text):
        hosts += ["dl.google.com", "maven.google.com", "repo.maven.apache.org", "repo1.maven.org", "plugins.gradle.org",
                  "services.gradle.org", "downloads.gradle.org"]
    if stack.pods and re.search(r"\b(ios|macos|ipa)\b", cmds_text):
        hosts += ["cdn.cocoapods.org"]
    return list(dict.fromkeys(hosts))


RENDERABLE_GLOB = re.compile(r"(?!/)[A-Za-z0-9._@+*?/-]+")   # render._SAFE_GLOB
# The engine's glob dialect has no character classes (globs.py: `[`/`]` are literal) and the
# render refuses them, so a secret name is written with `*` only — wider, never narrower.
SECRET_NAME_GLOBS = ("*.keystore", "*.jks", "*.p8", "*.p12", "*.pem", "*.key", "*.pfx", "key.properties", "id_rsa", "id_ed25519",
                     ".env", ".env.*", "service-account*.json", "*-service-account*.json", "api-*-*.json")


def detect_secrets(files, untracked):
    """→ (globs, found) — default secret paths (root and `**/` forms) + `**/` forms of the well-known credential names that exist."""
    globs = list(defaults.REPO_SECRET_DEFAULTS)
    found = {}
    for path in list(files) + list(untracked):
        if path.endswith("/") or any(("/" + path).find("/" + d) != -1 for d in SKIP_DIRS):
            continue
        base = os.path.basename(path)
        for pat in SECRET_NAME_GLOBS:
            if fnmatch.fnmatchcase(base, pat):
                found.setdefault(pat, []).append(path)
    for pat, paths in sorted(found.items()):
        deep = "**/" + pat
        if deep not in globs:
            globs.append(deep)
    return globs, found


VISUAL_CATEGORIES = (("tests", "test"), ("baselines", "golden"), ("config_files", "comparison-config"))
"""Stage 3 (E33): 0.98.7 `visual.<key>` → the verification rule `category`."""


def verification_rules(cfg, files, texts, src, categorized=False):
    """I11 as repo-config rules. Stage 2: verification_globs as is. Stage 3 (`categorized`, E33): every
    rule carries a `category` — the 0.98.7 visual keys become separate test / golden / comparison-config
    rules (the baseline-image ledger reads golden and comparison-config), test folders `test`, CI `ci`,
    command definition files `runner`."""
    if not categorized:
        return [{"kind": "verification", "globs": g, "note": n} for n, g in verification_globs(cfg, files, texts, src)]
    rules, seen = [], set()
    visual = cfg.get("visual") or {}
    for key, category in VISUAL_CATEGORIES:
        globs_ = [g for g in dict.fromkeys(_as_list(visual.get(key))) if isinstance(g, str) and valid_glob(g) and g not in seen]
        seen.update(globs_)
        if globs_:
            rules.append({"kind": "verification", "category": category, "globs": globs_, "note": f"0.98.7 visual.{key}"})
    by_note = {"test directories": "test", "CI configuration": "ci", "command definition files": "runner"}
    for note, globs_ in verification_globs(cfg, files, texts, src):
        if note.startswith("0.98.7 visual"):
            continue                                    # split by key above
        category = next(c for prefix, c in by_note.items() if note.startswith(prefix))
        rules.append({"kind": "verification", "category": category, "globs": globs_, "note": note})
    return rules


def verification_globs(cfg, files, texts, src):
    """I11: the verification path rules, each with a note. → [(note, [globs])]"""
    rules = []
    visual = cfg.get("visual") or {}
    stable = []
    for key in ("tests", "baselines", "config_files"):
        stable += [g for g in _as_list(visual.get(key)) if isinstance(g, str)]
    stable = [g for g in dict.fromkeys(stable) if valid_glob(g)]
    if stable:
        rules.append(("0.98.7 visual.tests / visual.baselines / visual.config_files", stable))
    candidates = []
    if "pubspec.yaml" in files:
        candidates += ["test/**", "integration_test/**", "**/*_test.dart", "test_driver/**"]
    if "package.json" in files:
        candidates += ["**/__tests__/**", "**/*.test.*", "**/*.spec.*", "**/e2e/**", "**/tests/**"]
    if any(f.endswith(".py") for f in files):
        candidates += ["tests/**", "**/test_*.py", "**/*_test.py"]
    tests = [g for g in candidates if any(glob_to_re(g).match(f) for f in files if not f.startswith(("node_modules/", "build/")))]
    if tests:
        rules.append(("test directories and files (by stack, only patterns that match tracked files)", list(dict.fromkeys(tests))))
    if any(f.startswith(".github/workflows/") for f in files):
        rules.append(("CI configuration", [".github/workflows/**"] + (
            [".github/actions/**"] if any(f.startswith(".github/actions/") for f in files) else [])))
    defs = command_definition_files(files, texts, src)
    if defs:
        rules.append(("command definition files and the wrappers / scripts the named commands run (I11 b)", defs))
    return rules


DEFINITION_CANDIDATES = (
    "package.json", "**/package.json", "pnpm-workspace.yaml", "turbo.json", "Makefile", "makefile", "justfile", "melos.yaml",
    "pubspec.yaml", "analysis_options.yaml", "dart_test.yaml", "lefthook.yml", "lefthook.yaml", ".cspell.json", "cspell.json",
    ".remarkrc.json", ".remarkrc", ".remarkignore", "eslint.config.js", "eslint.config.mjs", ".eslintrc.json", ".eslintrc.js",
    "tsconfig.json", "tsconfig.base.json", "vitest.config.*", "jest.config.*", "playwright.config.*", "pytest.ini", "pyproject.toml",
    ".fvmrc", ".nvmrc",
)
SCRIPT_REF = re.compile(r"[A-Za-z0-9_./\-]+\.(?:sh|py|js|mjs|cjs|ts|rb)\b")


def command_definition_files(files, texts, src):
    fs = set(files)
    found, queue, depth = [], [(t, 0) for t in texts], 0
    seen_text = set()
    while queue:
        text, depth = queue.pop(0)
        if text in seen_text or depth > 3:
            continue
        seen_text.add(text)
        for ref in SCRIPT_REF.findall(text):
            ref = os.path.normpath(ref.lstrip("./")) if ref.startswith("./") else ref
            if ref in fs and ref not in found:
                found.append(ref)
                body = src.read(ref)
                if body:
                    # scripts call helpers next to themselves (`${script_dir}/judge_test_report.py`)
                    sibling = [f for f in fs if os.path.dirname(f) == os.path.dirname(ref) and os.path.basename(f) in body]
                    for s in sibling:
                        if s not in found:
                            found.append(s)
                    queue.append((body, depth + 1))
    for pat in DEFINITION_CANDIDATES:
        rx = glob_to_re(pat)
        hits = [f for f in files if rx.match(f) and not f.startswith(("node_modules/", "build/")) and "/node_modules/" not in f]
        if hits:
            found.append(pat if ("*" in pat) else hits[0])
    return [g for g in dict.fromkeys(found) if valid_glob(g) and not g.startswith(".claude/")]


ROLE_PATH = re.compile(r"`((?:docs|release_notes|test|lib|scripts|design)[A-Za-z0-9_./<>{}*\-]*/[A-Za-z0-9_./<>{}*\-]+|[A-Za-z0-9_\-]+/[A-Za-z0-9_.<>{}*\-]+\.(?:md|txt|json|yaml|yml))`")
WRITE_WORDS = re.compile(r"(쓴다|쓰고|쓰며|쓸|작성|저장|기록|남긴|산출물|파일로|write|Write|produce|output)")


def role_output_candidates(files, src):
    """I11 a: path tokens in stable role bodies that sit on a 'writes' line — report only."""
    out = {}
    for path in files:
        if not re.match(r"^\.claude/agents/[^/]+\.md$", path):
            continue
        body = src.read(path) or ""
        paths = []
        for line in body.splitlines():
            if not WRITE_WORDS.search(line):
                continue
            for m in ROLE_PATH.finditer(line):
                p = re.sub(r"<[^>/]*(?:issue|N|이슈)[^>/]*>", "{issue}", m.group(1))
                if "{issue}" in p or "*" in p or p.startswith(("docs/", "release_notes/")):
                    paths.append(p)
        if paths:
            out[os.path.basename(path)[:-3]] = list(dict.fromkeys(paths))
    return out


# ======================================================================================
# E2. Stage 3 (V19): test-code / safety-net rules, risk and irreversible candidates
# ======================================================================================

CODE_EXT = ("dart", "ts", "tsx", "js", "jsx", "mjs", "cjs", "py", "rb", "go", "kt", "swift")
TEST_DIR_NAMES = ("test", "tests", "integration_test", "test_driver", "e2e", "__tests__")
NOT_SCANNED = ("docs/", ".claude/", ".github/", "node_modules/", "build/", ".dart_tool/")


def _ext(path):
    base = path.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1] if "." in base else ""


def _scanned(files):
    return [f for f in files if not f.startswith(NOT_SCANNED) and "/node_modules/" not in f]


def test_code_globs(files):
    """E4 `test-code`: test SOURCE files only — the suffix forms (`*_test.dart`, `*.test.<ext>`,
    `*.spec.<ext>`, `test_*.py`, `*_test.py`) at any depth, and code files inside test folders. Never a
    golden, snapshot, fixture or configuration (only code extensions). Only patterns that match a
    tracked file. → [(glob, number of tracked files)]"""
    count = {}
    for f in _scanned(files):
        ext = _ext(f)
        if ext not in CODE_EXT:
            continue
        base = f.rsplit("/", 1)[-1]
        found = []
        if base.endswith("_test.dart"):
            found.append("**/*_test.dart")
        for mid in (".test.", ".spec."):
            if mid in base:
                found.append(f"**/*{mid}{ext}")
        if ext == "py" and (base.startswith("test_") or base.endswith("_test.py")):
            found.append("**/test_*.py" if base.startswith("test_") else "**/*_test.py")
        segs = f.split("/")[:-1]
        for i, seg in enumerate(segs):
            if seg in TEST_DIR_NAMES:
                found.append(f"{seg}/**/*.{ext}" if i == 0 else f"**/{seg}/**/*.{ext}")
                break
        for g in found:
            count[g] = count.get(g, 0) + 1
    return sorted(count.items())


def safety_net_globs(files, test_globs):
    """E4 `safety-net`: the naming rule of new safety-net test files (0.98.7 refactor step 1:
    `foo_safety_net_test.dart`, `index.safety-net.test.tsx`) — one per test suffix form the repository
    uses. Files the `test` command picks up, so a net file is test code too."""
    out = []
    for g, _ in test_globs:
        if g == "**/*_test.dart":
            out.append("**/*_safety_net_test.dart")
        elif g.startswith("**/*.test."):
            out.append("**/*.safety-net.test." + g.rsplit(".", 1)[-1])
        elif g == "**/test_*.py":
            out.append("**/test_safety_net_*.py")
    return list(dict.fromkeys(out))


SECURITY_TOKENS = ("auth", "authentication", "oauth", "login", "logout", "signin", "signout", "credential",
                   "credentials", "password", "secret", "secrets", "keychain", "crypto", "cryptography", "cipher",
                   "iap", "payment", "payments", "billing", "purchase", "purchases", "subscription")
"""0.98.7 Section G security trigger (authentication, external exposure, secrets, sensitive data),
plus payments — matched as whole name tokens of a path (`google_auth_client.dart`, `auth/`)."""
DATA_TOKENS = ("migration", "migrations", "schema", "schemas")
"""0.98.7 Section G dba trigger (schema, migration) → the data-review gate (area data-migration)."""
RELEASE_WORKFLOW = re.compile(r"(^|[_.-])(release|deploy|publish)([_.-]|$)")
RISK_AREAS = {"security": "security-review", "data-migration": "data-review"}
"""The risk areas the tool proposes and the catalog diff-review gate of each (E25)."""

REVIEW_KINDS = ("test-code", "safety-net", "risk", "irreversible", "verification")
"""The path rule kinds a human review (decisions `stage3.review`, V19) may change."""
REVIEW_EXCLUDABLE = ("test-code", "safety-net", "risk", "irreversible")
"""Kinds whose tool CANDIDATES a review may drop — verification rules come from stage 2 and only grow."""


def review_verification_rules(files, review, report):
    """V19 human review: the `include` entries of kind `verification` → one rule per category (each glob
    must match a tracked file). They come before the stage-3 rules, so test-code never covers them when
    they are golden / comparison-config (E4) and risk candidates skip them."""
    by_cat = {}
    for e in (review or {}).get("include", []):
        if e["kind"] != "verification":
            continue
        _review_hits(files, e)
        by_cat.setdefault(e["category"], []).append(e)
    out = []
    for cat, entries in by_cat.items():
        out.append({"kind": "verification", "category": cat, "globs": [e["glob"] for e in entries],
                    "note": "added by the human review (V19 — every line judged in report.md)"})
        for e in entries:
            report["decisions"].append(f"verification ({cat}): `{e['glob']}` added by the human review — {e['why']}")
            report.setdefault("review_verification", []).append({"label": cat, "glob": e["glob"], "why": e["why"]})
    return out


def _review_hits(files, entry):
    """The tracked files an `include` glob matches — none is refused (a stale or mistyped decision)."""
    from gxengine import globs as G
    hits = [f for f in files if G.match(entry["glob"], f)]
    if not hits:
        raise SystemExit(f"error: decisions: stage3.review include {entry['kind']} `{entry['glob']}` matches no tracked file")
    return hits


def _name_tokens(seg):
    """Name tokens of a path segment, plus each adjacent pair joined (`sign_in` → sign, in, signin)."""
    words = [t for t in re.split(r"[^a-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", seg).lower()) if t]
    return words + [a + b for a, b in zip(words, words[1:])]


def _token_globs(files, tokens, exts, covered):
    """→ ({glob: [matching files]}): a folder whose name is a token → `<folder>/**`, else the file itself."""
    out = {}
    for f in _scanned(files):
        if _ext(f) not in exts or covered(f):
            continue
        segs = f.split("/")
        hit = None
        for i, seg in enumerate(segs[:-1]):
            if any(t in tokens for t in _name_tokens(seg)):
                hit = "/".join(segs[:i + 1]) + "/**"
                break
        if hit is None and any(t in tokens for t in _name_tokens(segs[-1].rsplit(".", 1)[0])):
            hit = f
        if hit:
            out.setdefault(hit, []).append(f)
    return dict(sorted(out.items()))


def stage3_path_rules(files, rules, report, s3):
    """The stage-3 path rules (E4, E25, E22) — proposals a human reviews (report §Stage 3):
      test-code    test_code_globs; none found → no rule (bug becomes template-unusable, reported);
      safety-net   safety_net_globs + decisions `stage3.safety_net_globs` (review-q0 D3);
      risk         security-review / data-review candidates from path tokens (code files only, never
                   test or verification paths);
      irreversible release / deploy / publish workflows → external-side-effect; schema / migration code
                   → hard-to-revert; SQL files in a migrations folder → human-executed.
    With decisions `stage3.review` (V19, a human checked every line): `exclude` drops a tool candidate,
    `include` adds a glob the path names missed, `kept` records a candidate checked and kept — see
    `Review`. A candidate the review never judged stays in (fail-closed) and is reported."""
    from gxengine import globs as G
    verification = [g for r in rules if r["kind"] == "verification" for g in r["globs"]]

    def is_verification(f):
        return any(G.match(g, f) for g in verification if valid_glob(g) and not g.endswith("/"))

    out, s3rep = [], {"test_code": [], "safety_net": [], "risk": [], "irreversible": []}
    frozen = [g for r in rules if r["kind"] == "verification" and r.get("category") in ("golden", "comparison-config")
              for g in r["globs"] if valid_glob(g) and not g.endswith("/")]

    def frozen_hit(g):
        return next((f for f in files if G.match(g, f) and any(G.match(x, f) for x in frozen)), None)

    review = s3.get("review")
    rv = Review(review, files, frozen_hit)
    tests, dropped = [], []
    for g, n in test_code_globs(files):
        hit = frozen_hit(g)
        if hit:
            dropped.append((g, hit))     # E4: test-code is test code only — never a golden or a comparison setting
        else:
            tests.append((g, n))
    for g, hit in dropped:
        report["decisions"].append(f"test-code: `{g}` left out — it covers `{hit}`, a golden / comparison-config path (E4)")
    derived = list(tests)                 # the safety-net names follow the tool's own test forms
    tests = [(g, n) for g, n in tests if rv.keep("test-code", None, g)]
    tests += [(g, len(hits)) for g, hits in rv.added("test-code", None, [g for g, _ in tests])]
    s3rep["test_code"] = tests
    if tests:
        out.append({"kind": "test-code", "globs": [g for g, _ in tests],
                    "note": "test source files of the repository (stage 3 E4 — never goldens, snapshots or config)"
                            + rv.note_suffix("test-code")})
    else:
        report["warnings"].append("no test source files found: no `test-code` rule — the bug template is unusable here")
    net = [g for g in safety_net_globs(files, derived) if rv.keep("safety-net", None, g)]
    extra = [g for g in (s3.get("safety_net_globs") or []) if g not in net]
    reviewed_net = [g for g, _ in rv.added("safety-net", None, net + extra)]
    if net or extra or reviewed_net:
        out.append({"kind": "safety-net", "globs": net + extra + reviewed_net,
                    "note": "safety-net file names (0.98.7 refactor: new files with a safety-net name)"
                            + (f"; plus {', '.join(extra)} — decision: {s3.get('note')}" if extra else "")
                            + rv.note_suffix("safety-net")})
        s3rep["safety_net"] = net + extra + reviewed_net
    else:
        report["warnings"].append("no safety-net naming rule could be derived: refactor-net and safety-net are unusable here")

    def covered(f):
        return is_verification(f) or any(G.match(g, f) for g, _ in tests)

    for area, tokens, exts in (("security", SECURITY_TOKENS, CODE_EXT),
                               ("data-migration", DATA_TOKENS, CODE_EXT + ("sql", "prisma"))):
        gate = RISK_AREAS[area]
        found = {g: fs for g, fs in _token_globs(files, tokens, exts, covered).items() if rv.keep("risk", area, g)}
        found.update(rv.added("risk", area, list(found)))
        if found:
            out.append({"kind": "risk", "area": area, "gate": gate, "globs": list(found),
                        "note": rv.rule_note(f"CANDIDATE (V19, 0.98.7 Section G {area} trigger by path names) — "
                                             "a human checks the list",
                                             f"0.98.7 Section G {area} trigger: path-name candidates and human additions")})
            s3rep["risk"].append({"area": area, "gate": gate, "evidence": found})
    release = [f for f in files if f.startswith(".github/workflows/") and RELEASE_WORKFLOW.search(f.rsplit("/", 1)[-1].lower())]
    migrations = _token_globs(files, ("migration", "migrations"), CODE_EXT + ("sql",), covered)
    sql = {g: fs for g, fs in migrations.items() if all(_ext(f) == "sql" for f in fs)}
    code = {g: fs for g, fs in _token_globs(files, DATA_TOKENS, CODE_EXT, covered).items() if g not in sql}
    for category, found, why in (("external-side-effect", {g: [g] for g in release},
                                  "release / deploy / publish workflows — a merged change acts outside the repository"),
                                 ("human-executed", sql, "SQL migrations a human runs"),
                                 ("hard-to-revert", code, "schema / migration code (a bad migration is hard to revert once it ran)")):
        found = {g: fs for g, fs in found.items() if rv.keep("irreversible", category, g)}
        found.update(rv.added("irreversible", category, list(found)))
        if found:
            out.append({"kind": "irreversible", "category": category, "globs": list(found),
                        "note": rv.rule_note(f"CANDIDATE (V19): {why}", f"tool candidates ({why}) and human additions")})
            s3rep["irreversible"].append({"category": category, "evidence": found})
    s3rep["review"] = rv.finish(report)
    report["stage3"] = s3rep
    return out


class Review:
    """decisions `stage3.review` applied to the tool's candidates (V19 — a human checked every line).

      exclude  [{kind, glob, why}]                a tool candidate dropped (kinds REVIEW_EXCLUDABLE)
      include  [{kind, glob, why, area|category}] a glob added (risk: area; irreversible / verification:
                                                  category); it must match a tracked file (safety-net: a
                                                  name rule for NEW files — no match needed), must not be
                                                  a candidate already, and a test-code glob must not cover
                                                  a golden / comparison-config path (E4)
      kept     [{kind, glob, why, area|category}] a candidate checked and kept (the record of the check)
    Fail-closed: an `exclude` / `kept` entry that names no candidate is refused (a stale decision); a
    candidate the review never judged stays in and is listed as unreviewed (report + warning)."""

    def __init__(self, review, files, frozen_hit):
        self.review, self.files, self.frozen_hit = review, files, frozen_hit
        self.used, self.rows, self.unreviewed = set(), [], []

    def _entries(self, field, kind, label):
        for i, e in enumerate((self.review or {}).get(field, [])):
            if e["kind"] == kind and (label is None or e.get("area", e.get("category")) == label):
                yield i, e

    def keep(self, kind, label, glob):
        """False = the review excludes this candidate. Records the judgment of every candidate."""
        if self.review is None:
            return True
        for field, verdict in (("exclude", "excluded"), ("kept", "kept")):
            for i, e in self._entries(field, kind, label):
                if e["glob"] == glob:
                    self.used.add((field, i))
                    self.rows.append({"kind": kind, "label": label, "glob": glob, "verdict": verdict, "why": e["why"]})
                    return verdict == "kept"
        self.unreviewed.append({"kind": kind, "label": label, "glob": glob})
        return True

    def added(self, kind, label, present):
        """[(glob, tracked files it matches)] of the `include` entries of kind / label."""
        out = []
        for i, e in self._entries("include", kind, label):
            if e["glob"] in present or e["glob"] in [g for g, _ in out]:
                raise SystemExit(f"error: decisions: stage3.review include {kind} `{e['glob']}` is already in the rule")
            if kind == "test-code" and self.frozen_hit(e["glob"]):
                raise SystemExit(f"error: decisions: stage3.review include test-code `{e['glob']}` covers "
                                 f"`{self.frozen_hit(e['glob'])}`, a golden / comparison-config path (E4)")
            hits = [] if kind == "safety-net" else _review_hits(self.files, e)
            self.used.add(("include", i))
            self.rows.append({"kind": kind, "label": label, "glob": e["glob"], "verdict": "included", "why": e["why"]})
            out.append((e["glob"], hits or [e["glob"]]))
        return out

    def note_suffix(self, kind):
        if self.review is None:
            return ""
        return "; reviewed by a human (V19 — every line judged in report.md)"

    def rule_note(self, candidate, desc):
        """The rule note: the tool's CANDIDATE note, or REVIEWED once a human judged the lines."""
        if self.review is None:
            return candidate
        return f"REVIEWED (V19 human review — every line judged in report.md): {desc}"

    def finish(self, report):
        """Refuse entries that named no candidate; report unreviewed candidates. → the report rows."""
        if self.review is None:
            return None
        for field in ("exclude", "kept", "include"):
            for i, e in enumerate(self.review.get(field, [])):
                if e["kind"] == "verification" and field == "include":
                    continue                      # applied by review_verification_rules
                if (field, i) not in self.used:
                    raise SystemExit(f"error: decisions: stage3.review {field} {e['kind']} `{e['glob']}` names no "
                                     f"candidate of this proposal (a stale or mistyped decision)")
        for u in self.unreviewed:
            report["warnings"].append(f"stage-3 {u['kind']} candidate `{u['glob']}` was not judged by the human review — "
                                      "it stays in (fail-closed); review it and add it to decisions `stage3.review`")
        return {"note": self.review["note"], "rows": self.rows, "unreviewed": self.unreviewed}


def catalog_roles(files):
    """{catalog role: its stable role file exists} — the judge roles of data/catalog.json (E17)."""
    roles = []
    for e in instructions.load_catalog_data()["entries"]:
        if e["role"] != "developer" and e["role"] not in roles:
            roles.append(e["role"])
    fs = set(files)
    return {r: f".claude/agents/{r}.md" in fs for r in roles}


# ======================================================================================
# E3. Init (stage 4, VB2): sources, manifests, questions
# ======================================================================================

SOURCE = codes.CommandSource


def line_of(text, cmd):
    """The 1-based line of `text` that holds the command — its whole text (the first such line), else its first three
    or two words when exactly one line has them (a folded scalar) — or None: never a guessed line."""
    lines = (text or "").splitlines()
    whole = [n for n, line in enumerate(lines, 1) if cmd.strip() and cmd.strip() in line]
    if whole:
        return whole[0]
    for k in (3, 2):
        probe = " ".join(cmd.split()[:k])
        hits = [n for n, line in enumerate(lines, 1) if len(cmd.split()) >= k and probe in line]
        if len(hits) == 1:
            return hits[0]
    return None


def _program_tokens(seg):
    """The words of a segment with and without env assignments and transparent wrappers."""
    raw = _tokens(seg)
    while raw and _ENV_ASSIGN.match(raw[0]):
        raw = raw[1:]
    bare = list(raw)
    while len(bare) > 1:
        if bare[0] in ("npx", "fvm", "exec", "time"):
            bare = bare[1:]
        elif (bare[0] in SCRIPT_RUNNERS and os.path.basename(bare[1]) in TRANSPARENT_WRAPPERS) \
                or (bare[0] in PM_PROGRAMS and bare[1] == "exec"):
            bare = bare[2:]
        else:
            break
    return raw, bare


def program_name(cmd):
    """The catalog name (`test`, `lint`, …) of a command whose program the table knows, or None. The text stays the file's."""
    segs = split_segments(cmd)
    for name in TABLES["manifest_names"]:
        for words in TABLES["program_names"].get(name, []):
            if any(t[:len(words)] == words for s_ in segs for t in _program_tokens(s_)):
                return name
    return None


def normal_segments(cmd):
    """A command's segments for "is this the same command": wrappers and `run` of a package manager dropped."""
    out = set()
    for seg in split_segments(cmd):
        _, t = _program_tokens(seg)
        if len(t) > 2 and t[0] in PM_PROGRAMS and t[1] in ("run", "run-script", "exec"):
            t = [t[0]] + t[2:]
        out.add(" ".join(t))
    return out


def manifest_candidates(src, stack):
    """→ ([Candidate], [note]): the scripts of the name table the repository's own manifests define (H14) — nothing else."""
    out, notes = [], []
    files = set(src.files())
    for m in TABLES["manifests"]:
        if m["file"] not in files:
            continue
        text = src.read(m["file"]) or ""
        runner = next((r for r in m["runners"] if r["lock"] is None or r["lock"] in files), None)
        if m["kind"] == "json-scripts":
            try:
                doc = json.loads(text)
                scripts = (doc.get(m["key"]) if isinstance(doc, dict) else None) or {}
            except ValueError as e:
                notes.append(f"{m['file']}: not valid JSON ({e}) — its scripts were not read")
                continue
            bodies = {k: v for k, v in scripts.items() if isinstance(v, str)} if isinstance(scripts, dict) else {}
        else:
            bodies = {t: "" for t in re.findall(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", text, re.M)}
        for name in TABLES["manifest_names"]:
            if name not in bodies:
                continue
            body = bodies[name]
            if any(x in body for x in m["not_a_command"]):
                continue
            kind, why = classify_command(body) if body else ("check", None)
            if kind != "check":
                notes.append(f"{m['file']} `{name}`: not carried ({why or kind})")
                continue
            if runner is None:
                notes.append(f"{m['file']} `{name}`: no lockfile names the package manager — not carried")
                continue
            probe = f'"{name}"' if m["kind"] == "json-scripts" else f"{name}:"
            line = line_of(text, probe)
            c = Candidate(runner["cmd"].replace("{name}", name), f"{m['id']} `{name}`", hint=name,
                          source=SOURCE.MANIFEST.value, path=m["file"])
            c.line = line
            out.append(c)
    return out, notes


def lock_hosts(src):
    """{host: [file]} of the package sources the lockfiles and registry settings of the repository name."""
    files, out = set(src.files()), {}
    for h in TABLES["host_patterns"]:
        if h["file"] in files:
            for host in re.findall(h["pattern"], src.read(h["file"]) or "", re.M):
                out.setdefault(host.lower(), [])
                if h["file"] not in out[host.lower()]:
                    out[host.lower()].append(h["file"])
    return out


def choice_id(text):
    """A stable id of a candidate: the answer names it, so an answer never holds a command text of a file."""
    return "c-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


class Init:
    """What the init draft adds to `build` (stage 4, VB2).

    exists(path)   is this toolchain source a folder of this machine (`{home}` resolved by the caller)
    Filled by build: `sources` {command: "source: file:line (origin)"}, `choices` {command: {choice id:
    (cmd, described)}}, `toolchain` (question or None), `hosts` {host outside the draft: [file]}."""

    def __init__(self, exists=None):
        self.exists = exists or (lambda path: True)
        self.sources, self.choices, self.toolchain, self.hosts = {}, {}, None, {}

    def describe(self, src, source, path, cmd, origin, line=None):
        line = line or (line_of(src.read(path), cmd) if path else None)
        where = f"{path}:{line}" if line else path
        return f"{source}: {where} ({origin})" if where else f"{source}: {origin}"

    def choose(self, name, cmd, described):
        self.choices.setdefault(name, {}).setdefault(choice_id(cmd), (cmd, described))

    def conflicts(self):
        """{command: choices} of the commands whose sources really differ."""
        return {n: c for n, c in self.choices.items() if len(c) > 1}

    def flutter_sources(self, version, decision):
        """(sync sources or None, question or None) of the Flutter SDK copy (H15)."""
        declared = flutter_sdk_sources(version)
        here = [p for p in declared if self.exists(p)]
        question = None
        if len(here) != 1:
            question = {"question": codes.InitQuestion.TOOLCHAIN.value, "item": FLUTTER_TOOLCHAIN["id"], "required": True,
                        "text": ("several SDK folders exist on this machine" if here else
                                 "no SDK folder of the table exists on this machine")
                                + (f" (.fvmrc pins {version})" if version else ""),
                        "choices": {**{choice_id(p): p for p in here}, "none": "no SDK copy (the commands use the SDK of the machine)"}}
        if decision is not None:
            return ([decision["from"]] if decision["from"] else None), question
        return (here if len(here) == 1 else None), question


def questions_of(cfg, report, init):
    """The init questions of a draft made WITHOUT answers (§2.9 table; the check adds sandbox-exception,
    quarantine and a red command's not-local). Every question: {question, item, required, text, choices}."""
    Q, out = codes.InitQuestion, []
    if "test" not in cfg["commands"]:
        out.append({"question": Q.TEST_COMMAND.value, "item": None, "required": True, "choices": None,
                    "text": "no test command was found in the 0.98.x settings, CI, lefthook or a manifest — write the command"})
    for name, choices in sorted(init.conflicts().items()):
        out.append({"question": Q.COMMAND_CONFLICT.value, "item": name, "required": True,
                    "text": f"the sources give different commands for `{name}`",
                    "choices": {i: f"{cmd} — {described}" for i, (cmd, described) in choices.items()}})
    for e in cfg.get("not_checked_locally", []):
        out.append({"question": Q.NOT_LOCAL.value, "item": e["name"], "required": True, "text": e["note"],
                    "choices": {"not-checked-locally": "list it in every PR as not checked locally",
                                "fix-repository": "the repository will be changed so that it can run here"}})
    s3 = report.get("stage3") or {}
    for kind, rows in (("risk", s3.get("risk", [])), ("irreversible", s3.get("irreversible", []))):
        for r in rows:
            label = r.get("area") or r.get("category")
            for g, files in r["evidence"].items():
                out.append({"question": Q.RISK_RULES.value, "item": f"{kind}:{label}:{g}", "required": False,
                            "text": f"{kind} rule candidate ({label}): {g}" + (f" — e.g. {', '.join(files[:3])}" if files != [g] else ""),
                            "choices": {"keep": "keep the rule line (also what happens without an answer)", "drop": "drop the rule line"}})
    # A15 (2026-11-26, VW1): what a human judged and no repository file shows — narrower test globs, added rule lines
    for kind, globs_ in (("test-code", [g for g, _ in s3.get("test_code", [])]), ("safety-net", list(s3.get("safety_net", [])))):
        for g in globs_:
            out.append({"question": Q.NARROW_GLOB.value, "item": f"{kind}:{g}", "required": False, "choices": None,
                        "text": f"{kind} glob candidate {g} — to narrow it, answer one or more narrower globs (space-separated) "
                                "or `drop`; `keep` (also what happens without an answer) leaves it. A glob that is wider, "
                                "or that the engine cannot prove narrower, is refused"})
    out.append({"question": Q.RISK_ADD.value, "item": None, "required": False,
                "text": "a risk or irreversible rule line the path names missed — item `risk:<security|data-migration>:<glob>` "
                        "or `irreversible:<external-side-effect|hard-to-revert|human-executed>:<glob>`; the glob must match a "
                        "tracked file; --note says why (it becomes the rule's reason)",
                "choices": {"add": "add the rule line", "withdraw": "take back a line added before"}})
    for host, files in sorted(init.hosts.items()):
        out.append({"question": Q.REGISTRY_HOST.value, "item": host, "required": True,
                    "text": f"packages come from {host} ({', '.join(files)}), outside the default table",
                    "choices": {"approve": "the sandbox may reach this host", "reject": "it stays closed"}})
    if init.toolchain:
        out.append(init.toolchain)
    # Q11 (user decision 2026-11-28): every recommended follow-up is filed — optional, never asked, no answer = create
    out.append({"question": Q.FOLLOWUPS_DRY_RUN.value, "item": None, "required": False,
                "text": "follow-up Issues of create-followups are really created on GitHub (also what happens without an "
                        "answer). Not asked: answer `dry-run` only when a human asks for it (a validation repository — "
                        "the engine-local record and a line in the PR, no Issue, comment or label is written)",
                "choices": {"dry-run": "record only (followups_dry_run: true)", "create": "really create (followups_dry_run absent)"}})
    return out


# ======================================================================================
# F. Assembling the settings
# ======================================================================================

def _normalise_stable_value(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [v.strip() for v in value if isinstance(v, str) and v.strip()]
    return []


def build(src, host_os=None, now=None, template_text=None, repo_name=None, moved_not_local=None, start_text=None,
          decisions=None, stage=2, init=None):
    """Pure conversion: a Source → (config dict, report dict, adapted template dict | None).

    `stage` 3 (V19): the stage-3 proposal — the plugin commands of the evidence and git-fact runs,
    verification categories, `test-code` / `safety-net` rules, risk and irreversible candidates,
    the follow-up dry-run switch (decisions `stage3`) and the catalog roles check in the report.
    The templates of stage 3 are adapted by `stage3_templates` (one per STAGE3 template).

    `init` (an Init, stage 4): the init draft — a repository without 0.98.x settings is read too, every command
    carries its source, what is ambiguous becomes a question. Without it nothing of that happens.

    `moved_not_local` {command name: note}: commands a human moved to `not_checked_locally`
    after the base-green check (removed from `commands` and from the template).
    `start_text`: the plugin start procedure used to validate the adapted template
    (default data/start.json).
    `decisions`: the checked human decisions (`load_decisions`) — command texts, approved sandbox
    exceptions, quarantine; their `not_checked_locally` moves arrive merged into `moved_not_local`."""
    host_os = host_os or {"darwin": "darwin", "linux": "linux"}.get(sys.platform, sys.platform)
    files = src.files()
    report = {"warnings": [], "decisions": [], "origin": {}, "dropped": [], "prep_steps": [], "ignored_workflows": [],
              "role_outputs": {}, "secrets_found": {}, "stable": None}
    stable_text = src.read(STABLE_CONFIG)
    if stable_text is None:
        if init is None:
            raise SystemExit(f"error: {STABLE_CONFIG} not found in {src.label} — nothing to convert")
        cfg = {}
    else:
        try:
            cfg = json.loads(stable_text)
        except ValueError as e:
            raise SystemExit(f"error: {STABLE_CONFIG} is not valid JSON: {e}")
        if not isinstance(cfg, dict):
            raise SystemExit(f"error: {STABLE_CONFIG} is not a JSON object")
        if "format" in cfg:
            # Readiness T2: the engine settings, not 0.98.x settings — in the promoted (stable) channel both live at
            # this path (after a migration and `init write`), and a Guild that moved on keeps them here as well.
            if init is None:
                raise SystemExit(f"error: {STABLE_CONFIG} holds engine settings (format {cfg['format']!r}), not 0.98.x "
                                 "settings — nothing to convert")
            report["warnings"].append(f"{STABLE_CONFIG} holds engine settings (format {cfg['format']!r}), not 0.98.x "
                                      "settings — not read as such")
            stable_text, cfg = None, {}
        else:
            report["stable"] = {"version": cfg.get("version"), "path": STABLE_CONFIG}
    stack = Stack(files, src)
    commands, origin, not_local = {}, {}, []
    keys_seen = {}            # key -> command name

    def register(name, entry, why):
        commands[name] = entry
        origin[name] = why

    # 1. stable named commands (human-approved before)
    for key in STABLE_COMMAND_KEYS:
        parts = _normalise_stable_value((cfg.get("commands") or {}).get(key))
        if not parts:
            continue
        kept = []
        for part in parts:
            k, dropped = host_filter(part, host_os)
            if dropped:
                for d in dropped:
                    not_local.append({"name": f"{key}: {d[:70]}", "note": f"targets a platform this {host_os} host cannot run"})
                    report["dropped"].append(f"{key}: `{d}` (other-platform target)")
            if k:
                kept.append(k)
        if not kept:
            continue
        cmd = " && ".join(kept)
        entry = {"cmd": cmd, "description": f"0.98.7 commands.{key}"}
        register(key, entry, f"0.98.7 commands.{key}")
        if init is not None:
            init.sources[key] = init.describe(src, SOURCE.STABLE_CONFIG.value, STABLE_CONFIG, kept[0], f"commands.{key}")
            init.choose(key, cmd, init.sources[key])
        for kk in cmd_keys(cmd):
            keys_seen.setdefault(kk, key)

    # 2. lefthook pre-push, then CI
    hook_cands, hook_notes = scan_lefthook(src)
    scan = scan_workflows(src)
    report["warnings"] += hook_notes + [f"workflow not parsed: {u}" for u in scan.unparsed]
    report["ignored_workflows"] = scan.ignored_workflows
    report["prep_steps"] = scan.prep_steps
    verify_order = [k for k in STABLE_COMMAND_KEYS if k in commands]
    cands = hook_cands + scan.candidates
    if init is not None and stable_text is None:
        # H14: CI → lefthook → manifests. With 0.98.x settings the conversion stays as it is (TI1): a human already
        # decided which commands there are
        manifest, notes = manifest_candidates(src, stack)
        report["warnings"] += notes
        cands = scan.candidates + hook_cands + manifest
    for cand in cands:
        k, dropped = host_filter(cand.cmd, host_os)
        if dropped and not k:
            not_local.append({"name": cand.cmd[:70], "note": f"targets a platform this {host_os} host cannot run ({cand.origin})"})
            continue
        cmd = k
        keys = cmd_keys(cmd)
        known = program_name(cmd) if init is not None and stable_text is None else None
        if cand.source == SOURCE.MANIFEST.value:
            known = cand.hint                    # the script's own name is the command's name
            if known in commands:                # another source has it: a candidate only when it runs something else
                if not normal_segments(cmd) <= normal_segments(commands[known]["cmd"]):
                    init.choose(known, cmd, init.describe(src, cand.source, cand.path, cand.cmd, cand.origin,
                                                          getattr(cand, "line", None)))
                continue
        extra = False
        if init is not None and keys and all(kk in keys_seen for kk in keys):
            at = keys_seen[sorted(keys)[0]]
            if at in init.sources and not any(normal_segments(cmd) <= normal_segments(e["cmd"]) for e in commands.values()):
                init.choose(at, (env_prefix(cand.env) if cand.env else "") + cmd,
                            init.describe(src, cand.source, cand.path, cand.cmd, cand.origin))
                # two steps of ONE source are two checks: the second stays a command of its own (no 0.98.x settings)
                extra = stable_text is None and init.sources[at].startswith(cand.source + ":")
        if not keys or (not extra and all(kk in keys_seen for kk in keys)):
            line = (f"covered: `{cmd[:80]}` ({cand.origin}) ≙ command `{keys_seen.get(next(iter(keys)))}`" if keys else
                    f"skipped: `{cmd[:80]}` ({cand.origin}) — no recognisable program")
            if line not in report["decisions"]:
                report["decisions"].append(line)
            continue
        base = name_for(sorted(keys)[0], cand.hint)
        name, n = base, 2
        if known is not None and known not in commands:
            name = base = known                  # no 0.98.x settings: the engine's own names are free
        while name in commands or (name in RESERVED_NAMES and name != known):
            name = f"{base}-{n}" if n > 2 or base not in RESERVED_NAMES else f"{base}-ci"
            n += 1
        full = (env_prefix(cand.env) if cand.env else "") + cmd
        entry = {"cmd": full, "description": cand.origin}
        if cand.timeout and int(cand.timeout) > 30:
            entry["timeout_min"] = min(600, int(cand.timeout))
        register(name, entry, cand.origin)
        if init is not None:
            init.sources[name] = init.describe(src, cand.source, cand.path, cand.cmd, cand.origin, getattr(cand, "line", None))
            init.choose(name, full, init.sources[name])
        for kk in keys:
            keys_seen.setdefault(kk, name)
        verify_order.append(name)
    not_local += scan.not_local

    # 3. setup (lockfile pinned, §7.12 S8) + plugin entries
    setup = derive_setup(stack, env_prefix(scan.install_env))
    ordered = {}
    if setup:
        ordered["setup"] = {"cmd": setup, "description": "lockfile-pinned install (§7.12 S8)" + (" with the CI install step's env" if scan.install_env else "")}
        origin["setup"] = "lockfiles"
    else:
        report["warnings"].append("no lockfile found at the repository root: no `setup` command was generated — add one by hand if the template needs it")
    for name in verify_order:
        ordered[name] = commands[name]
    for p in PLUGIN_COMMANDS + (STAGE3_PLUGIN_COMMANDS if stage >= 3 else ()):
        ordered[p] = {"plugin": p}
    # 3b. commands a human moved to "not checked locally" after the base-green check (P3-B):
    # they leave `commands` (and the template), their note goes to the PR body list (§7.2-2).
    removed_texts = []
    for name, note in (moved_not_local or {}).items():
        if name not in ordered or "cmd" not in ordered[name] or name == "setup":
            raise SystemExit(f"error: --not-checked-locally {name!r}: not a repository verification command of this conversion")
        removed_texts.append(ordered.pop(name)["cmd"])
        if name in verify_order:
            verify_order.remove(name)
        not_local.append({"name": name, "note": f"{note} (base-green check: cannot run inside the sandbox — human decision)"})
        report["decisions"].append(f"command `{name}` moved to not_checked_locally: {note}")
    # 3c. human decisions after the base-green check (CFG): a command text a human wrote, approved
    # sandbox exceptions, the quarantine list. Literal text from the decisions file only — never generated.
    dec = decisions or {}
    for name, entry in (dec.get("add_commands") or {}).items():
        if name in ordered:
            raise SystemExit(f"error: decisions: add_commands {name!r}: the draft has that command already")
        at = {n: e for n, e in ordered.items() if "cmd" in e}
        plugins = {n: e for n, e in ordered.items() if "cmd" not in e}
        ordered = dict(at, **{name: {"cmd": entry["cmd"], "description": f"{SOURCE.HUMAN.value}: {entry['why']}"}}, **plugins)
        origin[name] = "human"
        verify_order.append(name)
        if init is not None:
            init.sources[name] = ordered[name]["description"]
    for name, entry in (dec.get("commands") or {}).items():
        if name not in ordered or "cmd" not in ordered[name]:
            raise SystemExit(f"error: decisions: command {name!r} is not a repository command of this conversion")
        ordered[name] = {"cmd": entry["cmd"], "description": f"{ordered[name].get('description', name)}; "
                                                             f"human decision: {entry['why']}"}
        origin[name] = f"{origin.get(name, name)} + human decision"
        if init is not None:
            mine = (init.choices.get(name) or {}).get(choice_id(entry["cmd"]))
            twin = next((n for n, e in ordered.items() if n != name and e.get("cmd") == entry["cmd"]), None)
            if mine and twin:                    # the chosen text was a command of its own: the two change places
                old = commands[name]["cmd"]
                ordered[twin] = dict(ordered[twin], cmd=old)
                init.sources[twin] = init.choices[name][choice_id(old)][1]
            init.sources[name] = mine[1] + f"; chosen by a human: {entry['why']}" if mine and mine[0] == entry["cmd"] \
                else f"{SOURCE.HUMAN.value}: {entry['why']}"
        report["decisions"].append(f"command `{name}` replaced by the human decision: {entry['why']}")
    if not [n for n in ordered if n not in PLUGIN_COMMANDS and n != "setup"]:
        report["warnings"].append("no verification command could be derived")

    if init is not None:
        if setup:
            init.sources["setup"] = init.sources.get("setup") or f"{SOURCE.MANIFEST.value}: " + ", ".join(
                f for f in ("pnpm-lock.yaml", "package-lock.json", "yarn.lock", "pubspec.lock") if f in stack.files) \
                + " (lockfile-pinned install)"
        for name, e in ordered.items():
            if "cmd" in e:
                e["description"] = init.sources[name]
    out = {"format": 1, "commands": ordered, "run_timeout_min": defaults.RUN_TIMEOUT_MIN}

    # 4. toolchain prepare (outside the sandbox, §7.12 S8)
    sdk_from = flutter_sdk_sources(stack.fvm_version)
    if init is not None and stack.flutter:
        sdk_from, init.toolchain = init.flutter_sources(stack.fvm_version, (dec.get("toolchain") or {}).get(FLUTTER_TOOLCHAIN["id"]))
    if stack.flutter and sdk_from is not None:
        # Measured (F3 d, re-measured by tools/base_check.py): after `flutter precache` the SDK still writes
        # bin/cache/engine.stamp on EVERY `flutter` call, so a read-only user SDK cannot run anything inside srt.
        # The design's fallback is used from the start: a per-repository SDK copy in the Guild cache.
        out["toolchain_prepare"] = [
            {"name": "flutter-sdk", "sync": {"from": sdk_from, "to": FLUTTER_TOOLCHAIN["to"]},
             "description": "per-repository Flutter SDK copy in the Guild cache: a file copy outside the sandbox, "
                            "re-made at every engine start (§7.12 S8: the user's SDK is only read; P3-Z decision 4)"},
            {"name": "flutter-precache", "cmd": FLUTTER_PATH_PREFIX + "flutter precache",
             "description": "artifacts of the private SDK copy, inside srt (needs storage.googleapis.com in registry_hosts)"},
        ]
        for entry in ordered.values():
            if "cmd" in entry:
                entry["cmd"] = FLUTTER_PATH_PREFIX + entry["cmd"]
        report["decisions"].append("Flutter repository: every command runs with the private SDK copy first on PATH "
                                   "(GLD_FLUTTER_ROOT = {cache}/flutter-sdk) and HOME = {cache}/home (the Dart tools crash when they cannot "
                                   "write ~/.dart-tool; GIT_CONFIG_GLOBAL keeps git on the real user config; XDG_CONFIG_HOME is NOT kept, flutter writes tool_state there). "
                                   "Alternative without HOME change: the user runs `dart --disable-analytics` once.")
        if stack.fvm_version:
            report["decisions"].append(f".fvmrc pins Flutter {stack.fvm_version}: the copy is made from that version")
        elif init is None:
            report["warnings"].append("no pinned Flutter version (.fvmrc): the SDK copy is made from the first existing "
                                      "folder of " + ", ".join(FLUTTER_UNPINNED_SOURCES) + " — check toolchain_prepare.sync.from")
    elif stack.flutter:
        report["warnings"].append("no Flutter SDK copy: the commands run with the machine's own SDK, which a run cannot write "
                                  "(question `toolchain`)")

    # 5. path rules
    texts = [c.get("cmd", "") for c in ordered.values()] + [(src.read("lefthook.yml") or "")]
    rule_texts = texts + removed_texts      # a moved command's definition files stay verification paths
    rules = verification_rules(cfg, files, rule_texts, src, categorized=stage >= 3)
    irr = [g for g in _as_list((cfg.get("engine") or {}).get("irreversible_globs")) if isinstance(g, str) and valid_glob(g)]
    if irr:
        rules.append({"kind": "irreversible", "category": "hard-to-revert", "globs": irr, "note": "0.98.7 engine.irreversible_globs"})
    if stage >= 3:
        rules += review_verification_rules(files, (dec.get("stage3") or {}).get("review"), report)
        rules += stage3_path_rules(files, rules, report, dec.get("stage3") or {})
    if rules:
        out["path_rules"] = rules
    if stage < 3:
        report["decisions"].append("risk areas / irreversible kinds beyond 0.98.7 engine.irreversible_globs are not detected here (init §7.4 — stage 3)")

    # 6. network, cache env, secrets, worktree prepare
    all_cmd_text = " ".join(texts)
    hosts = stack_registry_hosts(stack, all_cmd_text)
    if init is not None:
        init.hosts = {h: f for h, f in lock_hosts(src).items() if h not in hosts}
        hosts += [h for h in (dec.get("registry_hosts") or {}) if h not in hosts]
        for h, why in (dec.get("registry_hosts") or {}).items():
            report["decisions"].append(f"registry host `{h}` approved (human decision): {why}")
    if hosts:
        out["registry_hosts"] = hosts
    cache_env = stack_cache_env(stack)
    if stack.flutter and sdk_from is None:
        cache_env = {k: v for k, v in cache_env.items() if k not in ("GLD_FLUTTER_ROOT", "GLD_HOME")}
    run_env = stack_run_env(stack)
    for k, v in sorted(scan.job_env.items()):
        if k in cache_env or k in run_env:
            continue
        why = run_env_refusal(k, v)
        if why:
            report["warnings"].append(f"CI job env {k}={v} not carried: {why}")
            continue
        run_env[k] = v
        report["decisions"].append(f"CI job env {k}={v} carried into run_env (a literal, non-path value)")
    if cache_env:
        out["cache_env"] = cache_env
    if run_env:
        out["run_env"] = run_env
    secrets, found = detect_secrets(files, src.untracked())
    bad = [g for g in secrets if not RENDERABLE_GLOB.fullmatch(g)]
    if bad:
        raise SystemExit(f"error: secret globs the engine render would refuse: {bad}")
    out["secret_paths"] = secrets
    report["secrets_found"] = {k: v[:5] for k, v in found.items()}
    prep = []
    for g in _as_list(((cfg.get("engine") or {}).get("effective") or {}).get("copy_ignored")):
        if not isinstance(g, str) or not valid_glob(g):
            report["warnings"].append(f"copy_ignored entry refused (not a relative glob): {g!r}")
            continue
        if any(glob_to_re(c).match(g) or glob_to_re(c).match(g.rstrip("/") + "/x") for c in (".claude/**", "**/CLAUDE.md", "**/CLAUDE.local.md", "**/AGENTS.md")):
            report["warnings"].append(f"copy_ignored entry {g!r} is a control-file pattern — never copied (§7.12 S2); dropped")
            continue
        if any(fnmatch.fnmatchcase(os.path.basename(g), s) for s in SECRET_NAME_GLOBS):
            report["warnings"].append(f"copy_ignored entry {g!r} looks like a secret — copied files are read-denied in the worktree; check")
        prep.append({"copy": g, "note": "0.98.7 engine.effective.copy_ignored"})
    if stack.dart and re.search(r"^  sqlite3:\s*$", src.read("pubspec.lock") or "", re.M) and src.has_dir(SQLITE_HOOK_CACHE):
        # package:sqlite3's build hook downloads a prebuilt library from github.com — not a registry host. The copy-only
        # prepare list carries the already downloaded file instead of opening github.com (measured, base_check).
        prep.append({"copy": SQLITE_HOOK_CACHE + "/**", "note": "sqlite3 build-hook download cache (ignored generated files) — avoids opening github.com"})
    if prep:
        out["worktree_prepare"] = prep
    if dec.get("sandbox_exceptions"):
        out["sandbox_exceptions"] = json.loads(json.dumps(dec["sandbox_exceptions"]))
        report["decisions"].append("approved sandbox exceptions (human decision): " + ", ".join(
            k for k in dec["sandbox_exceptions"] if k != "note"))
    if dec.get("quarantine"):
        cmd_text = "\n".join(e.get("cmd", "") for e in ordered.values())
        for q in dec["quarantine"]:
            # §7.10: the commands themselves exclude a quarantined test — an entry no command names is refused
            if q["test"] not in files:
                raise SystemExit(f"error: decisions: quarantined test {q['test']!r} is not a tracked file of {src.label}")
            if q["test"] not in cmd_text:
                raise SystemExit(f"error: decisions: quarantined test {q['test']!r} is not excluded by any command text")
        out["quarantine"] = [dict(q) for q in dec["quarantine"]]
        report["decisions"].append("quarantine (human decision): " + ", ".join(f"`{q['test']}`" for q in dec["quarantine"]))
    if not_local:
        merged, seen = [], set()
        for e in not_local:
            if e["name"] not in seen:
                seen.add(e["name"])
                merged.append(e)
        out["not_checked_locally"] = merged
    out["source"] = {
        "converted_from": f"{STABLE_CONFIG} v{cfg.get('version')} @ {src.label}" if stable_text is not None else f"CI, lefthook, manifests @ {src.label}",
        "at": (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "by": f"tools/convert_config.py v{TOOL_VERSION}",
    }
    for a, b in (("local_developer", "0.98.7 local_developer (ollama) is not carried — no counterpart in stage 1"),):
        if a in cfg:
            report["decisions"].append(b)
    report["origin"] = origin
    report["role_outputs"] = role_output_candidates(files, src)
    if stage >= 3:
        s3 = dec.get("stage3") or {}
        if s3.get("followups_dry_run"):
            out["followups_dry_run"] = True
            report["decisions"].append("followups_dry_run: true (decision: " + s3["note"] + ")")
        report["catalog_roles"] = catalog_roles(files)
        for role, ok in report["catalog_roles"].items():
            if not ok:
                report["warnings"].append(f"catalog role `{role}` has no `.claude/agents/{role}.md`: its catalog steps are "
                                          "declined (role-unavailable) and a risk gate it reviews stops as rule-unfillable")

    # 7. schema + semantic validation (the engine's own loader)
    repoconfig.RepoConfig(json.loads(json.dumps(out)))

    report["verify_order"] = list(verify_order)
    template = None
    if template_text:
        template = adapt_template(template_text, out, verify_order, report, moved=set(moved_not_local or ()),
                                  start_text=start_text)
    return out, report, template


DEFAULT_ON_FAIL_MAX = 2


TEMPLATE_STAGE = 2        # the plugin feature template ends with the leader's done-gate (scope D19)


def adapt_template(text, config, verify_order, report, moved=(), start_text=None, stage=TEMPLATE_STAGE):
    """The repository's copy of the plugin feature template (P3-B).

    - a `run` step whose command the repository does not have is REMOVED (moved to
      not_checked_locally or simply absent — the report says which);
    - a verification command the template lacks gets a `run` step after the developer's
      verification runs, with the on_fail of the first of those runs (else back to the
      developer, max 2);
    - the result must pass the engine's template checker and build into a stage-2
      procedure with the start procedure (procedure.parse_template / procedure.build,
      TEMPLATE_STAGE: the template carries the leader's done-gate) —
      otherwise the template is not proposed (a warning says why).
    Stage 3 (V19, `stage` 3): the developer step is the E5 one (the last work-role step before the
    first review step — `fix` in bug, `transform` in refactor), and the check is check_stage3_template.
    """
    from gxengine import procedure as _procedure
    try:
        tpl = json.loads(text)
    except ValueError as e:
        report["warnings"].append(f"default template is not JSON text: {e}")
        return None
    names = set(config["commands"])
    label = "template" if stage < 3 else f"template `{tpl.get('template')}`"
    steps = []
    for s in tpl.get("steps") or []:
        if isinstance(s, dict) and "run" in s and s["run"] not in names:
            why = ("moved to not_checked_locally (base-green check)" if s["run"] in moved
                   else "the repository has no such command")
            report["decisions"].append(f"{label}: step `{s.get('id')}` (run `{s['run']}`) removed — {why}")
            continue
        steps.append(s)
    referenced = [s["run"] for s in steps if isinstance(s, dict) and "run" in s]
    todo = [n for n in verify_order if n not in referenced]
    dev = (developer_index(steps) if stage >= 3 else
           next((i for i, s in enumerate(steps) if isinstance(s, dict) and s.get("role") == "developer"), None))
    if todo and dev is None:
        report["warnings"].append(f"{label} has no developer step: verification `run` steps were not inserted")
    elif todo:
        at = dev + 1
        while at < len(steps) and "run" in steps[at]:
            at += 1
        first_run = steps[dev + 1] if dev + 1 < at else None
        on_fail = dict(first_run["on_fail"]) if first_run and first_run.get("on_fail") else \
            {"back_to": steps[dev]["id"], "max": DEFAULT_ON_FAIL_MAX}
        ids = {s.get("id") for s in steps if isinstance(s, dict)}
        new = []
        for n in todo:
            sid = n if n not in ids else f"{n}-run"
            new.append({"id": sid, "run": n, "on_fail": dict(on_fail)})
        steps[at:at] = new
        report["decisions"].append(f"{label}: inserted `run` steps after the developer's verification runs: {', '.join(todo)}")
    tpl["steps"] = steps
    if start_text is None:
        # the start procedure as an engine of that stage reads it (the data file carries stage-3 additions)
        start_text = json.dumps(instructions.load_start_procedure(stage=stage))
    if stage >= 3:
        problems = check_stage3_template(tpl, start_text, config)
        if problems:
            report["warnings"].append(f"adapted template {tpl.get('template')!r} refused by the engine's checker — "
                                      "not proposed: " + "; ".join(problems))
            return None
        return tpl
    try:
        # dicts, not text: procedure.build parses TEXT at stage 1 (its `_as_template`), which refuses done-gate
        tpl_raw = _procedure.parse_template(json.dumps(tpl), stage=TEMPLATE_STAGE)
        start_raw = _procedure.parse_template(start_text, stage=TEMPLATE_STAGE)
        _procedure.build(start_raw, tpl_raw, 1, sorted(names), stage=TEMPLATE_STAGE)
    except (_procedure.ProcedureError, ValueError) as e:
        report["warnings"].append(f"adapted template refused by the engine's checker — not proposed: {e}")
        return None
    return tpl


def developer_index(steps):
    """E5 (+ D4: a template has no catalog step): index of the last work-role step before the first
    review step (a role step with checks); without a review step, the last work-role step. None if none."""
    first_review = next((i for i, s in enumerate(steps) if isinstance(s, dict) and s.get("role") and s.get("checks")),
                        len(steps))
    work = [i for i, s in enumerate(steps[:first_review])
            if isinstance(s, dict) and s.get("role") and codes.role_class(s["role"]) == codes.RoleClass.WORK.value]
    return work[-1] if work else None


def _path_globs(config):
    out = {}
    for r in config.get("path_rules") or []:
        if r["kind"] in codes.TEMPLATE_PATH_KINDS:
            out.setdefault(r["kind"], []).extend(r["globs"])
    return out


def expand_path_tokens(tpl, path_globs):
    """A copy of `tpl` with every `{path:<kind>}` item replaced by that kind's globs (E4). A kind
    the settings lack → ValueError (the template is unusable in this repository)."""
    doc = json.loads(json.dumps(tpl))
    for s in doc["steps"]:
        for key in ("inputs", "outputs"):
            items = []
            for item in s.get(key) or []:
                kind = next((k for k in codes.TEMPLATE_PATH_KINDS if item == codes.path_token(k)), None)
                if kind is None:
                    items.append(item)
                elif not path_globs.get(kind):
                    raise ValueError(f"step {s['id']!r} needs a `{kind}` path rule (E4)")
                else:
                    items += [g for g in path_globs[kind] if g not in items]
            if key in s:
                s[key] = items
    return doc


def check_stage3_template(tpl, start_text, config):
    """[problem] of a stage-3 repository copy ([] = usable): the engine's own judgment,
    procedure.template_problems (session B1 — the `{path:…}` items expanded from the settings, the
    stage-3 grammar and the work-output control-file rule; coordinator decision Z4 replaced the interim check)."""
    from gxengine import procedure as _procedure
    names = sorted(config["commands"])
    return list(_procedure.template_problems(json.loads(start_text), tpl, 1, names, _path_globs(config), stage=3))


def stage3_templates(config, report, moved=()):
    """{name: adapted repository copy} of every plugin template of stage 3 (codes.STAGE3_TEMPLATES) —
    a refused template is left out, with the reasons in report["templates_unusable"] (E2)."""
    out, unusable = {}, {}
    for name in codes.STAGE3_TEMPLATES:
        text = json.dumps(instructions.load_default_template(name, stage=3))
        before = len(report["warnings"])
        tpl = adapt_template(text, config, report.get("verify_order") or [], report, moved=moved, stage=3)
        if tpl is None:
            unusable[name] = report["warnings"][before:]
        else:
            out[name] = tpl
    report["templates_unusable"] = unusable
    return out


# ======================================================================================
# G. Report and output
# ======================================================================================

def render_report(repo, cfg, rep, src_label, template_note):
    L = [f"# guild-plugin settings proposal — {repo}", "",
         f"- source: {src_label}", f"- converted from: {cfg['source']['converted_from']}", f"- at: {cfg['source']['at']}", "",
         "A human reviews this and copies `commit/.claude/` into the repository root (`cp -R commit/.claude <repo>/`: "
         "`config.json` + `procedures/feature.yaml` + `roles/leader.md` as `.claude/guild/`), commits it, then the base-green check (tools/base_check.py).", ""]
    L += ["## Named commands", "", "| name | origin | command |", "|---|---|---|"]
    for name, e in cfg["commands"].items():
        body = e.get("cmd") or f"(plugin: {e['plugin']})"
        L.append(f"| `{name}` | {rep['origin'].get(name, 'plugin entry')} | `{body[:160]}` |")
    L += ["", f"run_timeout_min: {cfg['run_timeout_min']}", ""]
    if rep["decisions"]:
        L += ["## Decisions made by the script", ""] + [f"- {d}" for d in rep["decisions"]] + [""]
    if rep["warnings"]:
        L += ["## Needs a human", ""] + [f"- {w}" for w in rep["warnings"]] + [""]
    nl = cfg.get("not_checked_locally", [])
    L += ["## Not checked locally (PR body, §7.2-2)", ""] + ([f"- **{e['name']}** — {e['note']}" for e in nl] or ["- (none)"]) + [""]
    if rep["prep_steps"]:
        L += ["## CI preparation steps not adopted (composite actions — review, may mutate the tree)", ""] + [f"- {p}" for p in rep["prep_steps"]] + [""]
    if rep["ignored_workflows"]:
        L += ["## Workflows ignored (not checks)", ""] + [f"- {w}" for w in rep["ignored_workflows"]] + [""]
    exc = cfg.get("sandbox_exceptions")
    L += ["## Approved sandbox exceptions (human decision)", ""]
    L += ([f"- `{k}`: {json.dumps(v, ensure_ascii=False)}" for k, v in exc.items() if k != "note"] + [f"- note: {exc.get('note', '')}"]
          if exc else ["- (none)"]) + [""]
    L += ["## Quarantine (human decision — the commands exclude these tests)", ""]
    L += [f"- `{q['test']}` (added {q.get('added', '?')}) — {q['note']}" for q in cfg.get("quarantine", [])] or ["- (none)"]
    L += [""]
    L += ["## Secret paths", "", "- " + ", ".join(f"`{g}`" for g in cfg["secret_paths"]), ""]
    if rep["secrets_found"]:
        L += ["Credential-looking files present in the checkout (first matches):", ""]
        L += [f"- `{p}` → e.g. {', '.join('`' + x + '`' for x in xs[:3])}" for p, xs in sorted(rep["secrets_found"].items())] + [""]
    L += ["## Worktree prepare / toolchain / network", ""]
    L += [f"- copy `{e['copy']}`" for e in cfg.get("worktree_prepare", [])] or ["- worktree_prepare: (none)"]
    L += [(f"- toolchain_prepare `{e['name']}`: copy {' | '.join(e['sync']['from'])} → {{cache}}/{e['sync']['to']} "
           "(outside the sandbox, files only)") if "sync" in e else
          f"- toolchain_prepare `{e['name']}`: `{e['cmd']}` (inside srt)" for e in cfg.get("toolchain_prepare", [])]
    L += [f"- registry_hosts: {', '.join(cfg.get('registry_hosts', [])) or '(none)'}",
          f"- cache_env: {', '.join(f'{k}={v}' for k, v in cfg.get('cache_env', {}).items()) or '(none)'}",
          f"- run_env: {', '.join(f'{k}={v}' for k, v in cfg.get('run_env', {}).items()) or '(none)'}", ""]
    L += ["## I11 a — write paths found in stable role bodies (candidates for step `outputs`; report only)", ""]
    L += [f"- **{r}**: " + ", ".join(f"`{p}`" for p in ps) for r, ps in sorted(rep["role_outputs"].items())] or ["- (none found)"]
    L += ["", "## Procedure template", "", template_note, ""]
    return "\n".join(L)


def render_report_stage3(repo, cfg, rep, src_label, templates):
    """report.md of the stage-3 proposal: the stage-2 report plus what V19 adds (evidence per rule)."""
    base = render_report(repo, cfg, rep, src_label, "see “Stage 3 templates” below").replace(
        "copies `commit/.claude/` into the repository root (`cp -R commit/.claude <repo>/`: "
        "`config.json` + `procedures/feature.yaml` + `roles/leader.md` as `.claude/guild/`), commits it",
        "copies `commit/.claude/` into the repository root (`cp -R commit/.claude <repo>/`: `config.json`, "
        "`procedures/<template>.yaml` for every stage-3 template and `roles/leader.md` as `.claude/guild/`) "
        "— only together with the stage-3 merge (a stage-2 engine refuses these settings) — commits it")
    s3 = rep.get("stage3") or {}
    L = [base, "## Stage 3 (V19) — what this proposal adds", "",
         "This is the stage-3 proposal. A stage-2 engine refuses it (new rule kinds, commands and ops): commit and push "
         "it only with the stage-3 merge (scope Q6), then run the base-green check again (the settings changed, §7.10).", ""]
    L += ["### `test-code` (E4 — fills `{path:test-code}`: the bug template's reproduce step)", ""]
    L += [f"- `{g}` — {n} tracked file(s)" for g, n in s3.get("test_code", [])] or ["- (none — the bug template is unusable)"]
    L += ["", "### `safety-net` (E4 — names of new safety-net files: refactor-net, safety-net)", ""]
    L += [f"- `{g}`" for g in s3.get("safety_net", [])] or ["- (none)"]
    L += ["", "### Verification categories (E33 — golden / comparison-config feed the baseline-image ledger)", ""]
    L += [f"- {r.get('category', '?')}: " + ", ".join(f"`{g}`" for g in r["globs"][:12]) + (" …" if len(r["globs"]) > 12 else "")
          for r in cfg.get("path_rules", []) if r["kind"] == "verification"]
    L += ["", "### Risk-area gate candidates (E25 — a change under these paths adds the gate; check every line)", ""]
    for r in s3.get("risk", []):
        L.append(f"- **{r['area']}** → `{r['gate']}`:")
        L += [f"  - `{g}`" + (" — e.g. " + ", ".join(f"`{f}`" for f in fs[:3]) if fs != [g] else "")
              for g, fs in r["evidence"].items()]
    if not s3.get("risk"):
        L.append("- (no path matched the security or data-migration names)")
    L += ["", "### Irreversible-change candidates (E22, E23 — external-side-effect stops for a human, the others notify)", ""]
    for r in s3.get("irreversible", []):
        L.append(f"- **{r['category']}**:")
        L += [f"  - `{g}`" + (" — e.g. " + ", ".join(f"`{f}`" for f in fs[:3]) if fs != [g] else "") for g, fs in r["evidence"].items()]
    if not s3.get("irreversible"):
        L.append("- (none found)")
    rv = s3.get("review")
    if rv:
        L += ["", f"### Human review of the stage-3 rules (decisions `stage3.review`: {rv['note']})", "",
              "| kind | area / category | glob | judgment | why |", "|---|---|---|---|---|"]
        L += [f"| {r['kind']} | {r['label'] or '—'} | `{r['glob']}` | {r['verdict']} | {r['why']} |" for r in rv["rows"]]
        L += [f"| verification | {r['label']} | `{r['glob']}` | included | {r['why']} |" for r in rep.get("review_verification", [])]
        if rv["unreviewed"]:
            L += ["", "Candidates the review did not judge (they stay in — fail-closed):", ""]
            L += [f"- {u['kind']} {u['label'] or ''} `{u['glob']}`" for u in rv["unreviewed"]]
    L += ["", "### Catalog roles (E17 — `.claude/agents/<role>.md` at this revision)", ""]
    L += [f"- `{r}`: {'present' if ok else 'MISSING — its catalog steps are declined'}" for r, ok in (rep.get("catalog_roles") or {}).items()]
    L += ["", f"### Follow-up Issues: `followups_dry_run` = {str(bool(cfg.get('followups_dry_run'))).lower()} "
          "(user decision A4: on for the validation repositories)", ""]
    L += ["### Stage 3 templates", ""]
    for name in codes.STAGE3_TEMPLATES:
        if name in templates:
            L.append(f"- `{name}`: `procedures/{name}.yaml` — " + " → ".join(s["id"] for s in templates[name]["steps"]))
        else:
            L.append(f"- `{name}`: NOT PROPOSED — " + "; ".join((rep.get("templates_unusable") or {}).get(name) or ["refused"]))
    return "\n".join(L)


def repo_name(repo_root):
    """The output / decisions name: the folder name, `<parent>-service` for a `service` folder."""
    root = os.path.normpath(repo_root)
    base = os.path.basename(root)
    return base if base != "service" else os.path.basename(os.path.dirname(root)) + "-service"


def default_out(repo_root):
    return os.path.join(ENGINE_ROOT, "tools", "out", repo_name(repo_root))


def refuse_unsafe_out(repo_root, out):
    real_out, real_root = os.path.realpath(out), os.path.realpath(repo_root)
    for forbidden in (os.path.join(real_root, ".git"), os.path.join(real_root, ".claude", "guild")):  # promote: literal; rename-exception: the 0.98.x settings folder
        if real_out == forbidden or real_out.startswith(forbidden + os.sep):
            raise SystemExit(f"error: refusing to write into {forbidden} (the repository's git data / the stable Guild folder)")


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


DEFAULT_TEMPLATE = os.path.join(ENGINE_ROOT, "data", "templates", "feature.json")
LEADER_ROLE_OUT = os.path.join("roles", "leader.md")             # the plugin default leader role file (stage 2, D11)
PROCEDURE_OUT = os.path.join("procedures", "feature.yaml")   # repo-config TEMPLATES_DIR/<type>.yaml (JSON text, interfaces §4-1)
CANDIDATE_OUT = "config.with-candidate-exceptions.json"
CANDIDATE_KEYS = {"local-binding": "allow_local_binding", "weaker-network": "weaker_network_isolation"}


def candidate_config(cfg, keys):
    """A copy of the proposal with measured, NOT approved sandbox exceptions (§7.10 shows candidates
    only): local-binding · weaker-network · user-tmp (the token {user_tmp}, never a machine path) ·
    host:<name>. Validated by the engine's loader."""
    out = json.loads(json.dumps(cfg))
    exc = {}
    for k in keys:
        if k in CANDIDATE_KEYS:
            exc[CANDIDATE_KEYS[k]] = True
        elif k == "user-tmp":
            exc.setdefault("allow_write", []).append(defaults.USER_TMP_TOKEN)
        elif k.startswith("host:") and k[5:]:
            exc.setdefault("allow_hosts", []).append(k[5:])
        else:
            raise SystemExit(f"error: --candidate-exception {k!r} (local-binding | weaker-network | user-tmp | host:<name>)")
    exc["note"] = "WHAT-IF (not approved): measured candidates (tools/out/BASE_GREEN.md) — copy only what a human approves into config.json"
    out["sandbox_exceptions"] = exc
    repoconfig.RepoConfig(json.loads(json.dumps(out)))
    return out


DECISION_KEYS = {"repo", "note", "sandbox_exceptions", "not_checked_locally", "commands", "quarantine", "stage3"}
INIT_DECISION_KEYS = {"add_commands", "registry_hosts", "toolchain"}      # stage 4 (--init) only
STAGE3_DECISION_KEYS = {"note", "followups_dry_run", "safety_net_globs", "review"}
REVIEW_FIELDS = ("exclude", "include", "kept")


def _check_review(r, label):
    """decisions `stage3.review` (Review): {note, exclude, include, kept} — every entry {kind, glob, why}
    plus `area` (risk: a RISK_AREAS key) or `category` (irreversible / verification: the schema enum)."""
    if not isinstance(r, dict) or set(r) - {"note", *REVIEW_FIELDS} or not str(r.get("note", "")).strip():
        raise SystemExit(f"error: {label}: stage3.review wants {{note, exclude, include, kept}} with a note")
    labels = {"risk": ("area", set(RISK_AREAS)),
              "irreversible": ("category", {c.value for c in codes.IrreversibleCategory}),
              "verification": ("category", {c.value for c in codes.VerificationCategory})}
    for field in REVIEW_FIELDS:
        entries = r.get(field, [])
        if not isinstance(entries, list):
            raise SystemExit(f"error: {label}: stage3.review.{field} must be a list")
        for e in entries:
            kinds = REVIEW_KINDS if field == "include" else REVIEW_EXCLUDABLE
            key, allowed = labels.get(e.get("kind") if isinstance(e, dict) else None, (None, None))
            want = {"kind", "glob", "why"} | ({key} if key else set())
            if (not isinstance(e, dict) or e.get("kind") not in kinds or set(e) != want
                    or not all(isinstance(e[k], str) and e[k].strip() for k in want)
                    or not valid_glob(e["glob"]) or (key and e[key] not in allowed)):
                raise SystemExit(f"error: {label}: stage3.review.{field} entry wants {sorted(want)} "
                                 f"(kind one of {list(kinds)}{f', {key} one of {sorted(allowed)}' if key else ''}): {e!r}")
    seen = {}
    for field in REVIEW_FIELDS:
        for e in r.get(field, []):
            k = (e["kind"], e.get("area", e.get("category")), e["glob"])
            if k in seen:
                raise SystemExit(f"error: {label}: stage3.review names {e['kind']} `{e['glob']}` twice ({seen[k]}, {field})")
            seen[k] = field
COMMIT_DIR = os.path.join("commit", ".claude", "guild")       # copied as-is into the repository


def _check_init_decisions(d, label):
    """The decisions only the init draft knows (stage 4, VB2)."""
    for k, v in (d.get("add_commands") or {}).items():
        if k != "test" or not isinstance(v, dict) or set(v) != {"cmd", "why"} or not all(isinstance(x, str) and x.strip() for x in v.values()):
            raise SystemExit(f"error: {label}: add_commands wants exactly test: {{cmd, why}}, got {k!r}")
        if "\0" in v["cmd"] or "\n" in v["cmd"].strip():
            raise SystemExit(f"error: {label}: add_commands {k!r}: one line of text")
    for k, v in (d.get("registry_hosts") or {}).items():
        if not re.fullmatch(r"(?:[A-Za-z0-9-]+\.)+[A-Za-z0-9-]+", k) or not isinstance(v, str) or not v.strip():
            raise SystemExit(f"error: {label}: registry_hosts wants {{host: why}}, got {k!r}")
    ids = {t["id"] for t in TABLES["toolchains"]}
    for k, v in (d.get("toolchain") or {}).items():
        if k not in ids or not isinstance(v, dict) or set(v) != {"from", "why"} or not str(v["why"] or "").strip() \
                or not (v["from"] is None or (isinstance(v["from"], str) and v["from"].startswith(("{home}/", "/")))):
            raise SystemExit(f"error: {label}: toolchain wants {{{'|'.join(sorted(ids))}: {{from, why}}}}, got {k!r}")


def load_decisions(text, label="decisions", init=False):
    """The human decisions of the base-green check (tools/decisions/<repo>.json), checked fail-closed:
      repo                 the output folder name (must match)
      sandbox_exceptions   APPROVED exceptions, copied verbatim (needs a `note` saying who/when/why)
      not_checked_locally  {command: note} moved out of `commands` and the template
      commands             {command: {cmd, why}} a command text a human wrote (e.g. a quarantine exclusion)
      quarantine           [{test, note, added}] — every test must be named by a command text
      stage3               decisions of the stage-3 proposal only (`--stage 3`, V19): {note (who / when /
                           why), followups_dry_run (A4), safety_net_globs (extra safety-net names, D3),
                           review (the human review of the stage-3 candidates — Review, _check_review)}
      add_commands · registry_hosts · toolchain   the init draft only (`init`, stage 4): a test command a human
                           wrote, hosts a human approved {host: why}, the SDK copy's source {id: {from, why}}
    Unknown keys, a missing note/why/added, or a machine-specific temp path are refused."""
    try:
        d = json.loads(text)
    except ValueError as e:
        raise SystemExit(f"error: {label}: not JSON: {e}")
    known = DECISION_KEYS | (INIT_DECISION_KEYS if init else set())
    if not isinstance(d, dict) or set(d) - known:
        raise SystemExit(f"error: {label}: unknown keys {sorted(set(d) - known) if isinstance(d, dict) else d!r}")
    if init:
        for key in sorted(INIT_DECISION_KEYS & set(d)):
            if not isinstance(d[key], dict):
                raise SystemExit(f"error: {label}: {key} must be an object")
        _check_init_decisions(d, label)
    exc = d.get("sandbox_exceptions")
    if exc is not None and (not isinstance(exc, dict) or not str(exc.get("note", "")).strip()):
        raise SystemExit(f"error: {label}: sandbox_exceptions needs a note (who approved, when, why)")
    for k, v in (d.get("not_checked_locally") or {}).items():
        if not isinstance(v, str) or not v.strip():
            raise SystemExit(f"error: {label}: not_checked_locally {k!r} needs a note")
    for k, v in (d.get("commands") or {}).items():
        if not isinstance(v, dict) or set(v) != {"cmd", "why"} or not all(isinstance(x, str) and x.strip() for x in v.values()):
            raise SystemExit(f"error: {label}: commands {k!r} wants exactly {{cmd, why}}")
    for q in d.get("quarantine") or []:
        if not isinstance(q, dict) or set(q) != {"test", "note", "added"} or not all(isinstance(x, str) and x.strip() for x in q.values()):
            raise SystemExit(f"error: {label}: a quarantine entry wants exactly {{test, note, added}}: {q!r}")
    s3 = d.get("stage3")
    if s3 is not None:
        if not isinstance(s3, dict) or set(s3) - STAGE3_DECISION_KEYS or not str(s3.get("note", "")).strip():
            raise SystemExit(f"error: {label}: stage3 wants {{note, followups_dry_run, safety_net_globs, review}} with a note")
        if "followups_dry_run" in s3 and not isinstance(s3["followups_dry_run"], bool):
            raise SystemExit(f"error: {label}: stage3.followups_dry_run must be true or false")
        nets = s3.get("safety_net_globs", [])
        if not isinstance(nets, list) or not all(isinstance(g, str) and valid_glob(g) for g in nets):
            raise SystemExit(f"error: {label}: stage3.safety_net_globs must be relative globs")
        if "review" in s3:
            _check_review(s3["review"], label)
    if "/var/folders" in text or "/private/var" in text:
        raise SystemExit(f"error: {label}: a machine temp path — use the token {defaults.USER_TMP_TOKEN}")
    return d


def _pairs(values, flag):
    out = {}
    for v in values or []:
        name, sep, note = v.partition("=")
        if not sep or not name or not note.strip():
            raise SystemExit(f"error: {flag} wants NAME=note, got {v!r}")
        out[name] = note.strip()
    return out


def main(argv):
    ap = argparse.ArgumentParser(prog="convert_config.py", description=__doc__.split("\n")[0])
    ap.add_argument("--repo-root", required=True, help="main checkout of the repository (read only)")
    ap.add_argument("--rev", help="read files from this git revision instead of the working tree")
    ap.add_argument("--out", help="output folder (default tools/out/<repo>/)")
    ap.add_argument("--dry-run", action="store_true", help="print the settings and the report, write nothing")
    ap.add_argument("--template", help="default feature template (default data/templates/feature.json)")
    ap.add_argument("--host-os", default=None, help="platform commands must run on (default: this machine)")
    ap.add_argument("--not-checked-locally", action="append", metavar="NAME=note",
                    help="a command the base-green check showed cannot run in the sandbox (human decision): "
                         "removed from commands and the template, listed in not_checked_locally")
    ap.add_argument("--candidate-exception", action="append", metavar="KEY",
                    help=f"also write {CANDIDATE_OUT} with this measured, unapproved exception "
                         "(local-binding | weaker-network | user-tmp | host:<name>)")
    ap.add_argument("--decisions", metavar="FILE",
                    help="the human decisions of the base-green check (tools/decisions/<repo>.json): approved "
                         "sandbox exceptions, commands moved to not_checked_locally, command texts, quarantine")
    ap.add_argument("--stage", type=int, choices=(2, 3), default=2,
                    help="2 (default): the stage-2 proposal; 3: the stage-3 proposal (V19) into tools/out/<repo>/stage3/ "
                         "— every stage-3 template, the new rules and commands; committed only with the stage-3 merge")
    ap.add_argument("--init", action="store_true",
                    help="stage 4: print the init draft (settings, templates, questions) as JSON; needs --rev; writes nothing")
    args = ap.parse_args(argv)
    if args.init:
        return main_init(args)
    if args.stage == 3:
        return main_stage3(args)
    root = os.path.abspath(args.repo_root)
    if not os.path.isdir(root):
        raise SystemExit(f"error: {root} is not a directory")
    src = GitSource(root, args.rev) if args.rev else FsSource(root)
    tpl_path = args.template or DEFAULT_TEMPLATE
    tpl_text = None
    if not args.template:
        # the plugin feature template as a stage-2 engine reads it: the data file is also the stage-3
        # source (create-followups, stage-3 inputs — instructions.load_default_template drops them)
        tpl_text = json.dumps(instructions.load_default_template("feature", stage=TEMPLATE_STAGE), indent=2, ensure_ascii=False)
    elif os.path.isfile(tpl_path):
        with open(tpl_path, encoding="utf-8") as f:
            tpl_text = f.read()
    decisions = None
    if args.decisions:
        with open(args.decisions, encoding="utf-8") as f:
            decisions = load_decisions(f.read(), args.decisions)
    moved = dict((decisions or {}).get("not_checked_locally") or {})
    moved.update(_pairs(args.not_checked_locally, "--not-checked-locally"))
    cfg, rep, tpl = build(src, host_os=args.host_os, template_text=tpl_text, moved_not_local=moved, decisions=decisions)
    rel_tpl = os.path.relpath(tpl_path, ENGINE_ROOT) if tpl_path.startswith(ENGINE_ROOT) else tpl_path
    if tpl:
        note = (f"`{PROCEDURE_OUT}` adapted from the plugin default `{rel_tpl}` (version {tpl.get('version')}) — "
                "commit it as `.claude/guild/procedures/feature.yaml` after review")
    elif tpl_text:
        note = f"the adapted template was refused (see Needs a human) — no {PROCEDURE_OUT}"
    else:
        note = f"no default template at {rel_tpl} — no {PROCEDURE_OUT}"
    repo = repo_name(root)
    if decisions and decisions.get("repo") not in (None, repo):
        raise SystemExit(f"error: --decisions is for {decisions['repo']!r}, not {repo!r}")
    report = render_report(repo, cfg, rep, src.label, note)
    cfg_text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    cand = candidate_config(cfg, args.candidate_exception) if args.candidate_exception else None
    if args.dry_run:
        sys.stdout.write(cfg_text + "\n" + report + "\n")
        return 0
    out = os.path.abspath(args.out or default_out(root))
    refuse_unsafe_out(root, out)
    write_text(os.path.join(out, "config.json"), cfg_text)
    write_text(os.path.join(out, "report.md"), report + "\n")
    wrote = ["config.json", "report.md"]
    tpl_text_out = json.dumps(tpl, indent=2, ensure_ascii=False) + "\n" if tpl else None
    if tpl:
        write_text(os.path.join(out, PROCEDURE_OUT), tpl_text_out)
        wrote.append(PROCEDURE_OUT)
    # the tree a human copies into the repository unchanged: config.json + procedures/feature.yaml
    # + roles/leader.md (the plugin default, so the repository's copy is the one the evolve stage grows)
    commit = os.path.join(out, COMMIT_DIR)
    if os.path.isdir(os.path.join(out, "commit")):
        shutil.rmtree(os.path.join(out, "commit"))      # one tree per conversion — nothing stale left behind
    write_text(os.path.join(commit, "config.json"), cfg_text)
    if tpl:
        write_text(os.path.join(commit, PROCEDURE_OUT), tpl_text_out)
    write_text(os.path.join(commit, LEADER_ROLE_OUT), instructions.default_role_file("leader"))
    wrote.append(COMMIT_DIR + "/")
    if cand:
        write_text(os.path.join(out, CANDIDATE_OUT), json.dumps(cand, indent=2, ensure_ascii=False) + "\n")
        wrote.append(CANDIDATE_OUT)
    elif os.path.exists(os.path.join(out, CANDIDATE_OUT)):
        os.unlink(os.path.join(out, CANDIDATE_OUT))       # a stale what-if copy of an earlier conversion
    print(f"wrote {out}/: " + ", ".join(wrote))
    return 0


def roles_missing(files, templates):
    """The role files the templates and the catalog name, the repository does not have and the plugin does not ship
    (U2 — init writes none of them)."""
    need = set(catalog_roles(files)) | {"developer"}
    for tpl in templates.values():
        need |= {s["role"] for s in tpl["steps"] if isinstance(s, dict) and s.get("role")}
    have = set(files)
    return sorted(r for r in need if f".claude/agents/{r}.md" not in have and r not in instructions.PLUGIN_ROLES)


def propose(src, decisions=None, host_os=None, now=None, exists=None):
    """The init draft (VB2) → {"config", "templates", "unusable", "questions", "report", "warnings", "decisions",
    "roles_missing", "conflicts"}. Two builds: the questions come from the one WITHOUT answers, so they never move
    with an answer; the settings from the one with them."""
    asked = Init(exists)
    plain, plain_rep, _ = build(src, host_os=host_os, now=now, stage=3, init=asked)
    moved = dict((decisions or {}).get("not_checked_locally") or {})
    init = Init(exists)
    cfg, rep, _ = build(src, host_os=host_os, now=now, moved_not_local=moved, decisions=decisions, stage=3, init=init)
    templates = stage3_templates(cfg, rep, moved=set(moved))
    cfg["source"]["by"] = f"tools/convert_config.py v{TOOL_VERSION} --init"
    return {"config": cfg, "templates": templates, "unusable": rep.get("templates_unusable") or {},
            "questions": questions_of(plain, plain_rep, asked), "warnings": rep["warnings"], "decisions": rep["decisions"],
            "roles_missing": roles_missing(src.files(), templates),
            "choices": {n: {i: cmd for i, (cmd, _) in c.items()} for n, c in sorted(asked.conflicts().items())},
            "commands": sorted(n for n, e in plain["commands"].items() if "cmd" in e),
            "report": init_report(render_report_stage3("init", cfg, rep, src.label, templates))}


INIT_HOWTO = ("This is an `init` draft: nothing is copied by hand. `engine.py init answer` records the human's answers, "
              "`init check` runs the base-green check and the canaries on this draft, `init write` writes exactly the checked "
              "settings into `.claude/guild/` (never over existing files), and a human reads and commits them.")


def init_report(text):
    """The stage-3 report with the steps of `init` instead of the conversion's copy / merge instructions (VW1)."""
    text = re.sub(r"^A human reviews this and copies `commit/\.claude/`.*$", INIT_HOWTO, text, count=1, flags=re.M)
    return re.sub(r"^This is the stage-3 proposal\. A stage-2 engine refuses it.*$",
                  "The settings changed by any answer are checked again by `init check` (§7.10).", text, count=1, flags=re.M)


class InitSource(GitSource):
    """A fixed revision; the settings name the commit, never a path of this machine."""

    def __init__(self, root, rev):
        super().__init__(root, rev)
        self.label = self.sha[:12]

    def at(self):
        """The commit's own time: the same commit and answers give the same settings text."""
        t = self._git("show", "-s", "--format=%ct", self.sha).strip()
        return datetime.datetime.fromtimestamp(int(t), datetime.timezone.utc)


def main_init(args):
    """`--init` (stage 4, VB2): the draft of one revision as JSON on stdout; nothing is written."""
    if not args.rev or args.template or args.candidate_exception or args.not_checked_locally or args.out:
        raise SystemExit("error: --init wants --repo-root, --rev and optionally --decisions / --host-os")
    src = InitSource(os.path.abspath(args.repo_root), args.rev)
    decisions = None
    if args.decisions:
        with open(args.decisions, encoding="utf-8") as f:
            decisions = load_decisions(f.read(), "decisions", init=True)
    home = os.path.realpath(os.path.expanduser("~"))
    draft = propose(src, decisions, host_os=args.host_os, now=src.at(),
                    exists=lambda p: os.path.isdir(repoconfig.resolve_home(p, home)))
    draft.update(format=1, sha=src.sha, config_text=json.dumps(draft["config"], indent=2, ensure_ascii=False) + "\n")
    sys.stdout.write(json.dumps(draft, ensure_ascii=False, indent=1) + "\n")
    return 0


STAGE3_OUT = "stage3"


def main_stage3(args):
    """`--stage 3` (V19): the stage-3 proposal. Same reading and checks as stage 2; the output is a separate
    tree tools/out/<repo>/stage3/ (config.json, report.md, procedures/<template>.yaml for every usable
    stage-3 template, commit/.claude/guild/), so the committed stage-2 proposal and its base-green
    records stay as they are until the stage-3 merge."""
    if args.template or args.candidate_exception:
        raise SystemExit("error: --stage 3 adapts every plugin template itself (no --template) and takes no --candidate-exception")
    root = os.path.abspath(args.repo_root)
    if not os.path.isdir(root):
        raise SystemExit(f"error: {root} is not a directory")
    src = GitSource(root, args.rev) if args.rev else FsSource(root)
    decisions = None
    if args.decisions:
        with open(args.decisions, encoding="utf-8") as f:
            decisions = load_decisions(f.read(), args.decisions)
    repo = repo_name(root)
    if decisions and decisions.get("repo") not in (None, repo):
        raise SystemExit(f"error: --decisions is for {decisions['repo']!r}, not {repo!r}")
    moved = dict((decisions or {}).get("not_checked_locally") or {})
    moved.update(_pairs(args.not_checked_locally, "--not-checked-locally"))
    cfg, rep, _ = build(src, host_os=args.host_os, moved_not_local=moved, decisions=decisions, stage=3)
    templates = stage3_templates(cfg, rep, moved=set(moved))
    report = render_report_stage3(repo, cfg, rep, src.label, templates)
    cfg_text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    if args.dry_run:
        sys.stdout.write(cfg_text + "\n" + report + "\n")
        return 0
    out = os.path.abspath(args.out or os.path.join(default_out(root), STAGE3_OUT))
    refuse_unsafe_out(root, out)
    for stale in ("procedures", "commit"):
        if os.path.isdir(os.path.join(out, stale)):
            shutil.rmtree(os.path.join(out, stale))      # one tree per conversion — nothing stale left behind
    commit = os.path.join(out, COMMIT_DIR)
    for base in (out, commit):
        write_text(os.path.join(base, "config.json"), cfg_text)
        for name, tpl in templates.items():
            write_text(os.path.join(base, "procedures", name + ".yaml"), json.dumps(tpl, indent=2, ensure_ascii=False) + "\n")
    write_text(os.path.join(out, "report.md"), report + "\n")
    write_text(os.path.join(commit, LEADER_ROLE_OUT), instructions.default_role_file("leader"))
    print(f"wrote {out}/: config.json, report.md, procedures/ ({', '.join(templates)}), {COMMIT_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
