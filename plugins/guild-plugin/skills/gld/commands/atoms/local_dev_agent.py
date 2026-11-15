"""
local_dev_agent.py — the agent mode of `local_dev.py` (`local_developer.mode` "agent" / "auto").

The one-shot mode sends the whole implementation file and takes SEARCH/REPLACE blocks back in one
answer. Here the model works in turns through tools instead — `read_file`, `outline`, `search`,
`edit_file`, `run_tests` — so a large file never has to fit the prompt and an edit is written
against text the model has just read. Everything the leader sees is unchanged: the same job,
states and reasons (`local_dev.py` docstring); only the worker's inside differs.

What still holds, and how:
  • only `--files` are written by a tool; reads are limited to files git tracks and does not
    ignore (no secrets, no other job's records under the memory dir, nothing outside the repo —
    the path is resolved before it is checked, case-folded)
  • the pass is the tool's own check (lint when green at start + test_cmd), never the model's word
  • `run_tests` runs model-written code with the user's rights, like any test run: what a check
    leaves outside `--files` and the tests is caught after the fact (`Scope`): a new untracked file
    is moved into the job folder, a changed tracked file is put back and the job falls back with
    `out_of_scope_write`
  • no request is sent past `num_ctx` (Ollama would silently drop the oldest messages — the task)
  • a bad tool argument is an error string back to the model, never a crashed worker
  • the queue: an attended job holds the model throughout (as before); an unattended one holds it
    across consecutive model turns — the conversation is re-sent every turn and only an unbroken
    run keeps Ollama's prefix cache — and lets go while its checks run, and after HOLD_S

Design and review record: design/guild/local-dev-agent-mode.md (sdd-plugin, not shipped).
"""
import difflib
import fcntl
import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import subprocess
import time

TOOL_CHARS = 10000           # one tool result
READ_LINES = 300             # lines per read_file call
LINE_CAP = 2000              # a longer line is cut inside read_file
INLINE_CHARS = 8000          # --files this small (together) go into the first message whole
OUTLINE_CAP = 6000           # per large file, in the first message
MSG_OVERHEAD = 12            # chat-template tokens per message
FIT_MARGIN_AGENT = 2000
KEEP_RECENT = 2              # tool results never elided
LOW_WATER = 0.6              # elide down to this share of the limit in one go
STUCK_TURNS = 6
EDIT_MISS_LIMIT = 8           # per file, per segment (a restart resets it)
MIN_SUFFIX = 2000            # a restart that cannot carry this much of where it stands is blind
PRIOR_CHARS = 4000           # a failed one-shot attempt's diff, carried into an escalated job
EDITS_BEFORE_CHECK = 3
CALLS_PER_TURN = 8           # tool calls run from one reply; the rest are refused
HOLD_S = 900                 # an unattended job yields the model after this long
KEEP_ALIVE = "30m"
SEARCH_TIMEOUT = 20
SEARCH_LINES = 200
NEAR_MARGIN = 10
CONTEXT_LINES = 8            # around an applied edit
ELIDED = "[elided to save context — call the tool again if you need it]"

AGENT_SYSTEM = """You are the developer of a spec-driven workflow. The design skeleton is fixed and \
the failing tests are already written. Change the implementation so those tests pass, following \
the skeleton.

Rules:
- You can edit ONLY the implementation files listed in the task. Never edit tests.
- Keep the change minimal; do not refactor unrelated code.
- Work with the tools: find the place with `outline` or `search`, read only the lines you need \
with `read_file`, change them with `edit_file` (its `search` text must be copied from what you \
just read — exactly, once in the file), then call `run_tests`. When the tests pass you are done.
- After an edit, line numbers below it move: rely on what `edit_file` returned, or read again.
- If the tests cannot pass because of something outside the editable files, say so with
`report_blocker` (it is refused unless the checks show it).
- Answer with tool calls. Keep any prose short."""


def _fn(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": required}}}


TOOLS = [
    _fn("read_file", f"Read a tracked file with line numbers, at most {READ_LINES} lines per call.",
        {"path": {"type": "string"}, "start_line": {"type": "integer"},
         "end_line": {"type": "integer"}}, ["path"]),
    _fn("outline", "List the class, function and method declarations of a file with line numbers.",
        {"path": {"type": "string"}}, ["path"]),
    _fn("search", "Search tracked files (git grep). Fixed string unless regex is true.",
        {"pattern": {"type": "string"}, "path": {"type": "string"},
         "regex": {"type": "boolean"}, "context": {"type": "integer"}}, ["pattern"]),
    _fn("edit_file", "Replace `search` (exact text, must occur once) with `replace` in an "
        "implementation file. With several matches, near_line picks the one nearest that line.",
        {"path": {"type": "string"}, "search": {"type": "string"}, "replace": {"type": "string"},
         "near_line": {"type": "integer"}}, ["path", "search", "replace"]),
    _fn("run_tests", "Run the lint and the new tests against the current files.", {}, []),
    _fn("report_blocker", "Only when the tests cannot pass because of something outside the files "
        "you may edit (the test setup, a runner or config error that was there before your "
        "edits). Ends your work with your diagnosis. Refused unless the checks show it.",
        {"reason": {"type": "string"}, "evidence": {"type": "string"}}, ["reason", "evidence"]),
]
SCHEMA = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}
DENY = (".git", os.path.join(".claude", "guild", "memory"))


class BadArg(Exception):
    pass


def coerce(name, props, args):
    """The model's arguments as the schema types — "12" and 12.0 are 12, "false" is False —
    or BadArg with what to fix. Unknown keys are dropped."""
    out = {}
    for k, v in args.items():
        if k not in props:
            continue
        t = props[k]["type"]
        if v is None:
            continue
        if t == "string":
            if not isinstance(v, str):
                raise BadArg(f"{k} must be a string")
            try:
                v.encode("utf-8")
            except UnicodeError:
                raise BadArg(f"{k} is not valid text")
        elif t == "integer":
            try:
                if isinstance(v, bool):
                    raise ValueError
                f = float(v)
                if f != int(f):
                    raise ValueError
                v = int(f)
            except (TypeError, ValueError, OverflowError):
                raise BadArg(f"{k} must be an integer")
        elif t == "boolean":
            if isinstance(v, str) and v.strip().lower() in ("true", "false"):
                v = v.strip().lower() == "true"
            elif not isinstance(v, bool):
                raise BadArg(f"{k} must be true or false")
        out[k] = v
    missing = [k for k in SCHEMA[name]["required"] if k not in out]
    if missing:
        raise BadArg(f"missing argument(s): {', '.join(missing)}")
    return out


# --------------------------------------------------------------------------- paths

def run_git(repo, args, timeout=None):
    env = dict(os.environ, GIT_LITERAL_PATHSPECS="1")
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, env=env,
                          timeout=timeout)


def tracked(repo, rel, as_dir=False):
    p = run_git(repo, ["ls-files", "-z", "--", rel])
    names = [n for n in p.stdout.decode("utf-8", "replace").split("\0") if n]
    return bool(names) if as_dir else rel in names


def denied(rel):
    low = rel.casefold()
    return any(low == d.casefold() or low.startswith(d.casefold() + os.sep) for d in DENY)


def resolve(ld, repo, path, allow_dir=False, own=()):
    """(repo-relative path, None) or (None, why). The path is resolved first, then checked."""
    if not isinstance(path, str) or not path.strip() or "\0" in path:
        return None, "path must be a non-empty string"
    path = path.strip()
    if allow_dir and path in (".", "./"):
        return "", None
    norm, _ = ld.normalize(repo, [path])
    if norm is None:
        return None, f"{path!r} is outside the repository"
    rel = norm[0]
    if denied(rel):
        return None, f"{rel} cannot be read"
    full = os.path.join(repo, rel)
    if os.path.isdir(full):
        if allow_dir and tracked(repo, rel, as_dir=True):
            return rel, None
        return None, f"{rel} is a directory"
    if not os.path.isfile(full):
        return None, f"{rel} does not exist"
    if not tracked(repo, rel):
        return None, f"{rel} is not a tracked file (only files in git can be read)"
    if rel not in own and \
            run_git(repo, ["check-ignore", "-q", "--no-index", "--", rel]).returncode == 0:
        return None, f"{rel} is ignored by git and cannot be read"
    return rel, None


# --------------------------------------------------------------------------- outline

DECL_RE = re.compile(r"^\s*(?:(?:export|public|private|protected|static|abstract|final|async|"
                     r"override|external|factory|sealed|base|interface|pub|default)\s+)*"
                     r"(?:class|enum|mixin|extension|typedef|struct|trait|impl|interface|def|"
                     r"fn|func|function|module|object|record|type)\b")
ARROW_RE = re.compile(r"^\s{0,4}(?:export\s+)?(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*"
                      r"(?::[^=]+)?=\s*(?:async\s+)?(?:function\b|(?:\([^()]*\)|[\w$]+)\s*"
                      r"(?::[^=]+)?=>)")
CALL_RE = re.compile(r"^(\s*)((?:[\w<>\[\]?,.]+\s+)*)(?:get\s+|set\s+)?([A-Za-z_$][\w$]*)\s*"
                     r"(?:<[^>()]*>)?\s*\(")
GETTER_RE = re.compile(r"^(\s*)(?:[\w<>\[\]?,.]+\s+)*(?:get|set)\s+[A-Za-z_$][\w$]*\s*(=>|\{)")
CONTROL = {"if", "for", "while", "switch", "catch", "return", "else", "do", "try", "await",
           "throw", "assert", "super", "this", "new", "print", "yield", "case", "when", "in",
           "is", "as", "var", "final", "late", "with", "on"}


def outline_lines(text):
    out = []
    lines = text.split("\n")
    for i, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith(("//", "#", "*", "/*")):
            continue
        if DECL_RE.match(line) or ARROW_RE.match(line):
            out.append((i, line))
            continue
        g = GETTER_RE.match(line)
        if g and len(g.group(1)) <= 4:
            out.append((i, line))
            continue
        m = CALL_RE.match(line)
        if not m or len(m.group(1)) > 4 or m.group(3) in CONTROL:
            continue
        words = m.group(2).split()
        if words == ["const"] and m.group(3)[:1].isupper():
            out.append((i, line))          # a Dart const constructor
            continue
        if any(w in CONTROL or w == "const" for w in words):
            continue
        s = line.rstrip()
        if not words:                      # untyped: a method (`render() {`) or a call
            rest = line[m.end():].lstrip()
            nxt0 = next((l for l in lines[i:i + 2] if l.strip()), "")
            multi = s.endswith("(") and len(m.group(1)) <= 2 \
                and len(nxt0) - len(nxt0.lstrip()) > len(m.group(1))
            if rest[:1] in ("'", '"', "`", "(") or not (
                    multi or re.search(r"\)\s*(async\s*)?(:\s*[^=;(]+)?\{\s*\}?$", s)):
                continue                   # `it('…', () {`, `setState(() {`, `showX(`
        if s.endswith(";") and "=>" not in s:
            continue                       # a call statement, not a declaration
        nxt = next((l.strip() for l in lines[i:i + 3] if l.strip()), "")
        if "{" in s or "=>" in s or s.endswith(("(", ",")) or nxt.startswith(("{", "=>")) \
                or re.search(r"\)\s*(async\s*)?$", s):
            out.append((i, line))
    return out


def outline_text(text, cap):
    rows, size = [], 0
    for i, line in outline_lines(text):
        row = f"{i:>6}: {line.strip()[:160]}"
        if size + len(row) + 1 > cap:
            rows.append("… [outline cut — use outline/search for the rest]")
            break
        rows.append(row)
        size += len(row) + 1
    return "\n".join(rows) or "(no declarations found)"


# --------------------------------------------------------------------------- the first message

def read_text(repo, rel):
    with open(os.path.join(repo, rel), encoding="utf-8", newline="") as fh:
        return fh.read()


def initial_user(ld, repo, job, persona=None, bodies=None, label=None):
    """The task message. `bodies` — the --files as they were at start — is passed once the job
    runs, so a rebuild (the persona dropped) still shows what its label says."""
    parts = [f"## Task\nIssue #{job['issue']} — implement against the skeleton so the new tests "
             f"pass. Editable files: {', '.join(job['files'])}."]
    if job.get("note"):
        parts.append("## Note from the test author\n" + job["note"])
    if persona:
        parts.append("## This repository's developer conventions and lessons\n"
                     "Some of these describe steps of a wider workflow that are not yours "
                     "here. Apply what bears on the code you write; the rules above come "
                     "first.\n\n" + persona)
    with open(job["skeleton_path"], encoding="utf-8") as fh:
        parts.append("## Design skeleton\n" + fh.read())
    parts.append("## New/changed tests (diff vs base)\n```diff\n"
                 + ld.git(repo, "diff", job["mb"], "--", *job["tests"]) + "\n```")
    bodies = bodies or {f: read_text(repo, f) for f in job["files"]}
    total = sum(len(b) for b in bodies.values())
    for f, body in bodies.items():
        n = body.count("\n") + (0 if body.endswith("\n") or not body else 1)
        if total <= INLINE_CHARS:
            parts.append(f"## {f} ({n} lines) — content {label or 'at the start'}; after an edit "
                         f"use read_file for the current text\n```\n{body}\n```")
        else:
            parts.append(f"## {f} ({n} lines {label or 'at the start'}) — outline (read_file the "
                         f"parts you need)\n" + outline_text(body, OUTLINE_CAP))
    return "\n\n".join(parts)


def est_tokens(ld, messages):
    n = ld.estimate_tokens(json.dumps(TOOLS))
    for m in messages:
        n += MSG_OVERHEAD + ld.estimate_tokens(m.get("content") or "")
        if m.get("tool_calls"):
            n += ld.estimate_tokens(json.dumps(m["tool_calls"], ensure_ascii=False))
    return n


def reserve(ld):
    return 2 * TOOL_CHARS + ld.FEEDBACK_CHARS + FIT_MARGIN_AGENT


def fits(ld, cfg, first_user):
    """Eligibility: the fixed part of every request plus room to work in fits num_ctx."""
    need = est_tokens(ld, [{"role": "system", "content": AGENT_SYSTEM},
                           {"role": "user", "content": first_user}])
    return need + cfg["max_output_tokens"] + reserve(ld) <= cfg["num_ctx"]


# --------------------------------------------------------------------------- text-embedded calls

TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def valid_call(name, args):
    if not isinstance(name, str) or name not in SCHEMA or not isinstance(args, dict):
        return False
    try:
        coerce(name, SCHEMA[name]["properties"], args)
    except BadArg:
        return False
    return not any(k not in SCHEMA[name]["properties"] for k in args)


def parse_text_calls(content):
    """Calls a model wrote as text instead of through the API — only after its reasoning, only a
    `<tool_call>` block or a reply that is nothing but one call object, only valid calls."""
    text = (content or "").split("</think>")[-1]
    found = []
    blobs = TOOL_CALL_RE.findall(text)
    if not blobs and text.strip().startswith("{") and text.strip().endswith("}"):
        blobs = [text.strip()]
    for b in blobs:
        try:
            obj = json.loads(b)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        name, args = obj.get("name"), obj.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                continue
        if valid_call(name, args):
            found.append({"function": {"name": name, "arguments": args}})
    return found


# --------------------------------------------------------------------------- out-of-scope writes

def status_paths(repo):
    """{path: kind} — '??' untracked, else tracked-and-changed — from git status."""
    p = run_git(repo, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    out, parts, i = {}, p.stdout.decode("utf-8", "surrogateescape").split("\0"), 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        xy, path = e[:2], e[3:]
        if "R" in xy or "C" in xy:
            i += 1                         # the rename's source follows (index or worktree)
        if os.path.isabs(path) or path.split("/")[0] == ".." or "/../" in path:
            continue
        out[path] = "??" if xy == "??" else "M"
    return out


def content_hash(path):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "<missing>"
    if stat.S_ISLNK(st.st_mode):
        return "<link>" + os.readlink(path)
    if not stat.S_ISREG(st.st_mode):
        return "<other>"
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parent_ok(repo, rel):
    """The directories leading to `rel` are the real ones — no symlink anywhere on the way."""
    real = os.path.realpath(repo)
    return os.path.realpath(os.path.dirname(os.path.join(repo, rel))) == os.path.normpath(
        os.path.join(real, os.path.dirname(rel)))


def head_mode(repo, rel):
    """The mode HEAD records for `rel` ('100644', '120000', '160000' gitlink…), or None."""
    p = run_git(repo, ["ls-tree", "HEAD", "--", rel])
    line = p.stdout.decode("utf-8", "replace").split("\n")[0]
    return line.split(" ", 1)[0] if line else None


def remove_path(full):
    if os.path.isdir(full) and not os.path.islink(full):
        shutil.rmtree(full)
    elif os.path.lexists(full):
        os.unlink(full)


class Scope:
    """I8: what a check run leaves outside `--files` and the tests.

    S0 is taken before the baseline check, S1 after it. The reference is S1 — whatever the
    baseline run changed (a lock file, a report) is the runner's doing, not the model's. S0 only
    tells which untracked paths the baseline run created: those are the runner's artifacts (a
    failing golden test's images) and may change or vanish on every red run. The state is kept
    in the job folder, so `settle_dead` can finish the job's scope after a dead worker."""

    def __init__(self, ld, repo, jd, job):
        self.repo, self.jd = repo, jd
        self.skip = set(job["files"]) | set(job["tests"])
        self.state = os.path.relpath(ld.state_dir(repo), repo) + os.sep
        self.s0 = {}
        self.s1 = {}
        self.artifacts = set()
        self.s1_taken = False
        self.moved, self.out_of_scope, self.unrestored = [], [], []

    def _paths(self):
        return {p: k for p, k in status_paths(self.repo).items()
                if p not in self.skip and not (p + os.sep).startswith(self.state)}

    def save(self):
        with open(os.path.join(self.jd, "scope.json"), "w", encoding="utf-8") as fh:
            json.dump({"s0": self.s0, "s1": self.s1, "s1_taken": self.s1_taken,
                       "artifacts": sorted(self.artifacts), "moved": self.moved,
                       "out_of_scope": self.out_of_scope, "unrestored": self.unrestored}, fh)

    @classmethod
    def load(cls, ld, repo, jd, job):
        path = os.path.join(jd, "scope.json")
        if not os.path.isfile(path):
            return None
        sc = cls(ld, repo, jd, job)
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        sc.s0 = d.get("s0") or {}
        sc.s1 = {k: tuple(v) for k, v in d["s1"].items()}
        sc.s1_taken = bool(d.get("s1_taken"))
        sc.artifacts = set(d["artifacts"])
        sc.moved, sc.out_of_scope = d["moved"], d["out_of_scope"]
        sc.unrestored = d.get("unrestored", [])
        return sc

    def before_baseline(self):
        self.s0 = self._paths()
        self.save()                        # an auto job takes S0 before its one-shot part

    def after_baseline(self):
        for p, k in self._paths().items():
            if k == "??" and p not in self.s0:
                self.artifacts.add(p)
                continue
            full = os.path.join(self.repo, p)
            self.s1[p] = (k, content_hash(full))
            if os.path.isfile(full) and not os.path.islink(full):
                dst = os.path.join(self.jd, "s1", p)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(full, dst)
        self.s1_taken = True
        self.save()

    def _move(self, p):
        src = os.path.join(self.repo, p)
        dst = os.path.join(self.jd, "stray", p)
        if not parent_ok(self.repo, p):    # never move through a symlinked directory
            if p not in self.unrestored:
                self.unrestored.append(p)
            return
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
        except OSError:
            return
        self.moved.append(p)

    def _put_back(self, p):
        """True when `p` is as it was at S1 again."""
        full = os.path.join(self.repo, p)
        if not parent_ok(self.repo, p):
            return False
        mode = head_mode(self.repo, p)
        if mode == "160000" or os.path.lexists(os.path.join(full, ".git")):
            return False                   # a submodule: never removed or rewritten here
        try:
            if p not in self.s1:           # was clean at S1: HEAD has it, for index and tree
                if os.path.isdir(full) and not os.path.islink(full):
                    if mode is None:
                        return False       # a directory HEAD does not know — not ours to remove
                    shutil.rmtree(full)    # a check put a directory where HEAD has a file
                r = run_git(self.repo, ["checkout", "-q", "HEAD", "--", p])
                if r.returncode != 0:      # not in HEAD: it did not exist — remove it
                    run_git(self.repo, ["rm", "-q", "--cached", "--ignore-unmatch", "--", p])
                    remove_path(full)
            else:
                want = self.s1[p][1]
                copy = os.path.join(self.jd, "s1", p)
                remove_path(full)
                if want.startswith("<link>"):
                    os.symlink(want[len("<link>"):], full)
                elif os.path.isfile(copy):
                    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
                    shutil.copy2(copy, full)
                # "<missing>" (deleted at S1): removing it was the put-back
        except OSError:
            return False
        if p in self.s1:
            return content_hash(full) == self.s1[p][1]
        return p not in status_paths(self.repo)

    def check(self, act=True):
        """(new out-of-scope paths, newly moved paths) after a check run. `act=False` only
        records: a dead worker is settled later, maybe after a human edited the checkout —
        what differs then is listed for a human, never put back or moved."""
        now = self._paths()
        bad, moved_before = [], len(self.moved)
        for p, k in now.items():
            if p in self.artifacts:
                continue
            if p not in self.s1:
                if k == "??" and act:
                    self._move(p)
                elif k == "??":
                    bad.append(p)
                else:
                    bad.append(p)          # a tracked file clean at S1 changed
            elif content_hash(os.path.join(self.repo, p)) != self.s1[p][1]:
                bad.append(p)
        for p in self.s1:
            if p not in now:               # back to clean / deleted since S1
                bad.append(p)
        for p in bad:
            if (not act or not self._put_back(p)) and p not in self.unrestored:
                self.unrestored.append(p)
        self.out_of_scope += [p for p in bad if p not in self.out_of_scope]
        self.save()
        return bad, self.moved[moved_before:]

    def finish(self):
        for p in sorted(self.artifacts):
            if os.path.lexists(os.path.join(self.repo, p)):
                self._move(p)
        self.save()


def settle_scope(ld, repo, jd, job):
    """For `settle_dead`: the dead agent worker's last check may have left writes behind."""
    sc = Scope.load(ld, repo, jd, job)
    if sc is None or not sc.s1_taken:      # died before its reference existed: nothing to compare
        return
    sc.check(act=False)                    # listed for a human (restore_failed), never acted on
    record(job, sc)


def record(job, sc):
    for k, v in (("out_of_scope", sc.out_of_scope), ("stray", sc.moved)):
        if v:
            job[k] = list(v)
    if sc.unrestored:
        job["restore_failed"] = sorted(set(job.get("restore_failed") or []) | set(sc.unrestored))


# --------------------------------------------------------------------------- tools

def numbered(lines, start):
    out = []
    for i, line in enumerate(lines, start):
        cut = line[:LINE_CAP] + ("…[line cut]" if len(line) > LINE_CAP else "")
        out.append(f"{i:>6}| {cut}")
    return "\n".join(out)


def capped(text):
    return text if len(text) <= TOOL_CHARS else text[:TOOL_CHARS] + "\n… [cut]"


def file_lines(text):
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [l.rstrip("\r") for l in lines]


class Tools:
    def __init__(self, ld, worker, run):
        self.ld, self.w, self.run = ld, worker, run
        self.repo = worker.repo
        self.reads = {}           # (path, start, end, digest) -> (message index, turn)
        self.ranges = set()
        self.edits_since_check = 0
        self.edit_misses = {}

    def call(self, name, args):
        """(result text, progress, read key or None) — never raises."""
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                return "error: arguments are not JSON", False, None
        if not isinstance(args, dict):
            return "error: arguments must be an object", False, None
        if not isinstance(name, str) or name not in SCHEMA:
            return f"error: unknown tool {name!r} — use one of {', '.join(SCHEMA)}", False, None
        if name == "run_tests":            # the tool's own check: a failure there is the
            return self.t_run_tests()      # worker's (worker_error), not the model's
        if name == "report_blocker":
            try:
                kw = coerce(name, SCHEMA[name]["properties"], args)
            except BadArg as exc:
                return f"error: {name}: {exc}", False, None
            return self.t_report_blocker(**kw)
        try:
            kw = coerce(name, SCHEMA[name]["properties"], args)
            return getattr(self, "t_" + name)(**kw)
        except BadArg as exc:
            return f"error: {name}: {exc}", False, None
        except Exception as exc:  # noqa: BLE001 — a model's call never kills the job
            return f"error: {name} failed: {type(exc).__name__}: {str(exc)[:300]}", False, None

    def t_read_file(self, path, start_line=None, end_line=None):
        rel, err = resolve(self.ld, self.repo, path,
                           own=self.w.job["files"] + self.w.job["tests"])
        if err:
            return "error: " + err, False, None
        try:
            text = read_text(self.repo, rel)
        except UnicodeDecodeError:
            return f"error: {rel} is not UTF-8 text", False, None
        lines = file_lines(text)
        n = len(lines)
        if n == 0:
            progress = (rel, "empty") not in self.ranges
            self.ranges.add((rel, "empty"))
            return f"{rel} is empty (0 lines)", progress, None
        s = max(1, start_line or 1)
        if s > n:
            return f"error: {rel} has {n} lines", False, None
        e = min(n, end_line if end_line else s + READ_LINES - 1, s + READ_LINES - 1)
        e = max(e, s)
        digest = hashlib.sha256(text.encode()).hexdigest()
        key = (rel, s, e, digest)
        seen = self.reads.get(key)
        if seen is not None and not self.run.messages[seen[0]].get("_elided"):
            return (f"{rel} lines {s}-{e}: unchanged — same as your read_file result at turn "
                    f"{seen[1]}", False, None)
        rows, size, last = [], 0, s - 1
        for i in range(s, e + 1):
            row = numbered([lines[i - 1]], i)
            if rows and size + len(row) + 1 > TOOL_CHARS:
                break
            rows.append(row)
            size += len(row) + 1
            last = i
        want = min(n, end_line) if end_line else n
        more = f"\n[more: read_file start_line={last + 1}]" if last < want else ""
        progress = (rel, s, last) not in self.ranges
        self.ranges.add((rel, s, last))
        return f"{rel} lines {s}-{last} of {n}\n" + "\n".join(rows) + more, progress, key

    def t_outline(self, path):
        rel, err = resolve(self.ld, self.repo, path)
        if err:
            return "error: " + err, False, None
        try:
            text = read_text(self.repo, rel)
        except UnicodeDecodeError:
            return f"error: {rel} is not UTF-8 text", False, None
        progress = (rel, "outline") not in self.ranges
        self.ranges.add((rel, "outline"))
        return f"{rel} — declarations\n" + outline_text(text, TOOL_CHARS), progress, None

    def t_search(self, pattern, path=None, regex=False, context=0):
        if not pattern:
            return "error: pattern must be a non-empty string", False, None
        rel = ""
        if path:
            rel, err = resolve(self.ld, self.repo, path, allow_dir=True)
            if err:
                return "error: " + err, False, None
        ctx = max(0, min(3, context or 0))

        def grep(flag):
            args = ["grep", "-n", "-I", "--no-color", flag]
            if ctx:
                args += ["-C", str(ctx)]
            args += ["-e", pattern, "--"] + ([rel] if rel else [])
            return run_git(self.repo, args, timeout=SEARCH_TIMEOUT)
        try:
            p = grep("-E" if regex else "-F")
            if regex and p.returncode not in (0, 1):
                p = grep("-F")
        except subprocess.TimeoutExpired:
            return "error: search timed out — narrow the pattern or the path", False, None
        if p.returncode == 1:
            return f"no match for {pattern!r}", False, None
        if p.returncode != 0:
            return "error: " + p.stderr.decode("utf-8", "replace")[:500], False, None
        lines = [l for l in p.stdout.decode("utf-8", "replace").splitlines()
                 if not denied(re.split(r"[:\-]\d+[:\-]", l, maxsplit=1)[0])]
        out, size = [], 0
        for l in lines[:SEARCH_LINES]:
            l = l[:LINE_CAP]
            if size + len(l) + 1 > TOOL_CHARS:
                break
            out.append(l)
            size += len(l) + 1
        if not out:
            return f"no match for {pattern!r}", False, None
        tail = f"\n[{len(lines) - len(out)} more lines — narrow the search]" if len(out) < len(lines) else ""
        key = ("search", pattern, rel, bool(regex), ctx)
        progress = key not in self.ranges
        self.ranges.add(key)
        return "\n".join(out) + tail, progress, None

    def _miss(self, rel, msg):
        self.edit_misses[rel] = self.edit_misses.get(rel, 0) + 1
        self.w.job["edit_misses"] = self.w.job.get("edit_misses", 0) + 1
        return capped(msg), False, None

    def t_edit_file(self, path, search, replace, near_line=None):
        rel, err = resolve(self.ld, self.repo, path, own=self.w.job["files"])
        if err:
            return "error: " + err, False, None
        if rel not in self.w.job["files"]:
            return (f"error: {rel} is not editable — the only editable files are "
                    f"{', '.join(self.w.job['files'])}"), False, None
        full = os.path.join(self.repo, rel)
        st = os.lstat(full)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
            return f"error: {rel} is not a plain file (link) — not written", False, None
        search, replace = search.replace("\r\n", "\n"), replace.replace("\r\n", "\n")
        try:
            cur = read_text(self.repo, rel)
        except UnicodeDecodeError:
            return f"error: {rel} is not UTF-8 text — not written", False, None
        nl = "\r\n" if "\r\n" in cur else "\n"
        s2, r2 = search.replace("\n", nl), replace.replace("\n", nl)
        if s2 == "":
            if cur.strip():
                return self._miss(rel, "error: an empty search is allowed only for an empty file")
            starts = [0]
        else:
            starts, i = [], cur.find(s2)
            while i != -1:
                starts.append(i)
                i = cur.find(s2, i + 1)
        if not starts:
            return self._miss(rel, self._nearest(rel, cur, search))
        if len(starts) > 1:
            lines_at = [cur.count("\n", 0, i) + 1 for i in starts]
            pick = None
            if near_line is not None:
                d = sorted((abs(l - near_line), j) for j, l in enumerate(lines_at))
                if d[1][0] - d[0][0] >= NEAR_MARGIN:
                    pick = d[0][1]
            if pick is None:
                return self._miss(rel, f"error: search matches {len(starts)} times in {rel}, "
                                       f"starting at lines {lines_at[:20]} — add surrounding "
                                       f"lines to make it unique, or pass near_line")
            starts = [starts[pick]]
        at = starts[0]
        new = cur[:at] + r2 + cur[at + len(s2):]
        if new == cur:
            return "no change: search and replace are the same text", False, None
        data = new.encode("utf-8")         # encode first: a failure must not truncate the file
        fd = os.open(full, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        self.edits_since_check += 1
        first = cur.count("\n", 0, at) + 1
        lines = file_lines(new)
        span = r2.count("\n") + 1
        lo, hi = max(1, first - CONTEXT_LINES), min(len(lines), first + span + CONTEXT_LINES - 1)
        if hi - lo > 2 * CONTEXT_LINES + 40:   # a long replacement: show its ends only
            shown = numbered(lines[lo - 1:lo + CONTEXT_LINES + 10], lo) + "\n   …\n" + \
                numbered(lines[hi - CONTEXT_LINES - 10:hi], hi - CONTEXT_LINES - 9)
        else:
            shown = numbered(lines[lo - 1:hi], lo)
        if not lines:
            return f"edited {rel}: it is now empty", True, None
        delta = r2.count("\n") - s2.count("\n")
        return capped(f"edited {rel}. Lines {lo}-{hi} now:\n" + shown
                      + (f"\nEarlier reads of {rel} are stale: lines after {first} moved by "
                         f"{delta:+d}." if delta else "")), True, None

    @staticmethod
    def _nearest(rel, cur, search):
        cand = sorted((l.strip() for l in search.split("\n") if l.strip()), key=len, reverse=True)
        lines = file_lines(cur)
        squash = [re.sub(r"\s+", "", l) for l in lines]
        for c in cand[:3]:
            key = re.sub(r"\s+", "", c)
            hits = [i for i, l in enumerate(squash) if key and key in l]
            if hits:
                i = hits[0]
                lo, hi = max(0, i - 6), min(len(lines), i + 7)
                return (f"error: search not found in {rel}. The closest place (line {i + 1}) "
                        f"currently reads:\n" + numbered(lines[lo:hi], lo + 1)
                        + "\nCopy the search text exactly from this.")
        return f"error: search not found in {rel}, and none of its lines occur — read the place again"

    def t_run_tests(self):
        return self.run.check(intermediate=True)

    def t_report_blocker(self, reason, evidence):
        return self.run.blocker(reason, evidence)


# --------------------------------------------------------------------------- the loop

TIME_RE = re.compile(r"\d+")
REPORTER_PREFIX = re.compile(r"^\s*\d+:\d+\s+\+\d+(?:\s+~\d+)?(?:\s+-\d+)?:\s*")
TIMING = re.compile(r"\s*\(\d+(?:\.\d+)?\s*m?s\)")
FAIL_RE = re.compile(r"\[E\]|FAILED|✕|✗|^not ok\b|^\s*FAIL\b")


def check_signature(outcome, out):
    names = set()
    for line in out.splitlines():
        if FAIL_RE.search(line):
            names.add(TIMING.sub("", REPORTER_PREFIX.sub("", line)).strip())
    if names:
        return outcome, tuple(sorted(names))
    tail = "\n".join(out.splitlines()[-30:])
    return outcome, hashlib.sha256(TIME_RE.sub("", tail).encode()).hexdigest()


LOAD_RE = re.compile(r"Failed to load|failed to compile|Compilation failed|No tests (?:ran|found|were "
                     r"found)|\b0 tests?\b|Tests:\s+0 total|Test suite failed to run|Cannot find "
                     r"module|ImportError|ModuleNotFoundError|SyntaxError|Error: Could not", re.I)
LOC_RE = re.compile(r"((?:file://)?(?:[\w.@~+-]*/)*[\w.@+-]+\.\w{1,8}):\d+(?::\d+)?[:\s]+(.*)")
# a located line counts as an error only with an error marker of its own — never a stack or
# traceback frame (`at f (<file>:<line>:<col>)`, `<file>:<line>: in <module>`, `#3  main (…)`)
ERR_MARK = re.compile(r"\b(?:error|Error|ERROR)\b|error TS\d+|^E\s")
FRAME = re.compile(r"^\s*(?:at\s|#\d+\s)|:\s*in\s<|\(\S+:\d+:\d+\)\s*$")


def cut_middle(text, n):
    """`text` within n chars, keeping its head and its tail."""
    if len(text) <= n:
        return text
    h = max(0, n // 2 - 20)
    return text[:h] + "\n… [cut] …\n" + text[len(text) - (n - h - 12):] if n > 40 else text[:n]


class Run:
    def __init__(self, ld, worker, prior=None):
        self.ld, self.w = ld, worker
        self.cfg, self.job, self.repo, self.jd = worker.cfg, worker.job, worker.repo, worker.jd
        self.messages = []
        self.tools = Tools(ld, worker, self)
        self.scope = Scope(ld, self.repo, self.jd, self.job)
        self.ticket = worker.fixed_ticket
        self.held_since = None
        self.think = bool(self.cfg.get("agent_think"))
        self.persona = None
        if self.job.get("persona_path"):
            with open(os.path.join(self.repo, self.job["persona_path"]), encoding="utf-8") as fh:
                self.persona = fh.read()
        self.prior = ("## A previous one-shot attempt (failed) — for reference only\n```diff\n"
                      + cut_middle(prior, PRIOR_CHARS) + "\n```") if prior else ""
        self.bodies = None
        self.label = None
        self.suffix = ""
        self.seg = 1
        self.restarts = 0
        self.no_restart = False
        self.history = []                  # every agent check: {seg, sig, digest, out}
        self.refusals = 0
        self.last_sig = None
        self.checked_digest = None
        self.n_check = 0
        self.turn = 0
        self.ended = None                  # (state, reason) once a check or a blocker decides

    # ---- messages
    def add(self, msg):
        self.messages.append(msg)
        with open(os.path.join(self.jd, "transcript.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({k: v for k, v in msg.items() if not k.startswith("_")},
                                ensure_ascii=False) + "\n")
        return len(self.messages) - 1

    def feedback(self, text):
        """A user message the tool wrote (check output, a nudge) — elidable like a tool result."""
        return self.add({"role": "user", "content": text, "_feedback": True})

    def wire(self):
        return [{k: v for k, v in m.items() if not k.startswith("_")} for m in self.messages]

    def first_message(self, suffix=None):
        parts = [initial_user(self.ld, self.repo, self.job, self.persona, self.bodies, self.label)]
        if self.prior:
            parts.append(self.prior)
        suffix = self.suffix if suffix is None else suffix
        if suffix:
            parts.append(suffix)
        return "\n\n".join(parts)

    def start_segment(self):
        self.messages = []
        self.add({"role": "system", "content": AGENT_SYSTEM})
        self.add({"role": "user", "content": self.first_message()})

    def fit(self):
        high = self.cfg["num_ctx"] - self.cfg["max_output_tokens"] - FIT_MARGIN_AGENT
        if est_tokens(self.ld, self.messages) <= high:
            return True, 0
        low = int(high * LOW_WATER)
        elided = 0
        idx = [i for i, m in enumerate(self.messages)
               if (m["role"] == "tool" or m.get("_feedback")) and not m.get("_elided")]
        for i in idx[:-KEEP_RECENT] if len(idx) > KEEP_RECENT else []:
            if est_tokens(self.ld, self.messages) <= low:
                break
            self.messages[i]["content"] = ELIDED
            self.messages[i]["_elided"] = True
            elided += 1
        for m in self.messages[:-1]:
            if est_tokens(self.ld, self.messages) <= low:
                break
            if m["role"] != "assistant" or m.get("_args_elided"):
                continue
            m["_args_elided"] = True
            for c in m.get("tool_calls") or []:
                f = c.get("function", {})
                a = f.get("arguments")
                if f.get("name") == "edit_file" and isinstance(a, dict) and "elided" not in a:
                    f["arguments"] = {"path": a.get("path"), "elided":
                                      f"-{str(a.get('search', '')).count(chr(10)) + 1}/"
                                      f"+{str(a.get('replace', '')).count(chr(10)) + 1} lines"}
                    elided += 1
        if est_tokens(self.ld, self.messages) > low and self.persona:
            self.persona = None            # the restart suffix and the prior stay: first_message()
            self.job["persona"] = "dropped"
            self.messages[1]["content"] = self.first_message()
            elided += 1
        return est_tokens(self.ld, self.messages) <= high, elided

    # ---- queue
    def hold(self):
        if self.ticket is None:
            self.ticket = self.w.queue.take(f"{self.repo}#{self.job['issue']} (agent)")
            self.w.wait_turn(self.ticket)
            self.held_since = time.monotonic()

    def release(self):
        if self.ticket is not None and self.ticket != self.w.fixed_ticket:
            self.w.queue.leave(self.ticket)
            self.ticket = None

    def call_model(self):
        if self.ticket is not None and self.ticket != self.w.fixed_ticket \
                and time.monotonic() - self.held_since > HOLD_S:
            self.release()                 # let the queue move, then line up again
        self.hold()
        timeout = min(self.cfg["attempt_timeout_min"] * 60, self.w.budget())
        if timeout <= 0:
            return None, "total_timeout", 0.0
        body = {"model": self.cfg["model"], "stream": False, "messages": self.wire(),
                "tools": TOOLS, "keep_alive": KEEP_ALIVE, "think": self.think,
                "options": {"num_ctx": self.cfg["num_ctx"],
                            "num_predict": self.cfg["max_output_tokens"], "temperature": 0.2}}
        with open(self.w.queue.lock_path, "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            t0 = time.monotonic()
            try:
                return self.ld.post_json(self.cfg, "/api/chat", body, timeout), None, \
                    time.monotonic() - t0
            except (TimeoutError, OSError) as exc:
                secs = time.monotonic() - t0
                if isinstance(exc, TimeoutError) or "timed out" in str(exc):
                    cap = self.cfg["attempt_timeout_min"] * 60
                    return None, ("attempt_timeout" if timeout >= cap else "total_timeout"), secs
                return None, f"model_error:{type(exc).__name__}", secs
            except (ValueError, http.client.HTTPException) as exc:
                return None, f"model_error:{type(exc).__name__}", time.monotonic() - t0

    # ---- checks
    def check(self, intermediate):
        """(result text, progress, None); sets self.ended when the check decides the job."""
        self.release()                     # nobody needs the model while tests run
        self.tools.edits_since_check = 0
        outcome, out, moved = self._check_once()
        if outcome == "pass" and moved:    # a pass must not lean on a file it just lost: the
            outcome, out, more = self._check_once()   # same check again, without those files
            moved = moved + more
            self.job["rechecked"] = self.job.get("rechecked", 0) + 1
        self.n_check += 1
        with open(os.path.join(self.jd, f"checks{self.n_check}.txt"), "w", encoding="utf-8") as fh:
            fh.write(out)
        rec = {"n": self.n_check, "outcome": outcome, "intermediate": intermediate,
               "seg": self.seg, "started": self.ld.now_iso()}
        if outcome != "pass":
            rec["error"] = out[-self.ld.EXCERPT_CHARS:]
        self.job["attempts"].append(rec)
        self.checked_digest = self.ld.files_digest(self.repo, self.job["files"])
        if outcome == "pass":
            with open(os.path.join(self.jd, "test-output.txt"), "w", encoding="utf-8") as fh:
                fh.write(out)
            self.job["evidence"] = os.path.relpath(os.path.join(self.jd, "test-output.txt"),
                                                   self.repo)
            self.ended = ("local_pass", None)
        elif outcome in ("tests_modified", "out_of_scope_write", "total_timeout"):
            self.ended = ("fallback", outcome)
        if self.scope.unrestored:
            self.ended = ("fallback", "restore_failed")
        sig = check_signature(outcome, out)
        # (L)'s evidence is parsed now, from the whole output — the stored text is only a tail
        self.history.append({"seg": self.seg, "sig": sig, "digest": self.checked_digest,
                             "out": out[-20000:], "pairs": self.load_pairs(out)})
        progress = sig != self.last_sig
        self.last_sig = sig
        note = (f"\n[files created outside the editable set were moved away: {', '.join(moved)}]"
                if moved else "")
        return (f"{outcome}\n" + out[-self.ld.FEEDBACK_CHARS:] + note), progress, None

    def _check_once(self):
        outcome, out = self.w.checks()
        tests_changed = self.ld.restore_changed_tests(self.repo, self.jd, self.job["tests"])
        bad, moved = self.scope.check()    # always — a test change does not excuse the rest
        record(self.job, self.scope)
        if tests_changed:
            return "tests_modified", out, moved
        if bad:
            return "out_of_scope_write", out + f"\n[changed outside the editable set: {bad}]", moved
        return outcome, out, moved

    # ---- report_blocker
    def load_pairs(self, out):
        """(normalised message, repo path) of each located error line — only paths that are
        tracked files of this repo outside --files and every --tests entry."""
        real = os.path.realpath(self.repo)
        own = set(self.job["files"]) | set(self.job["tests"])
        pairs = set()
        lines = out.splitlines()
        for i, line in enumerate(lines):
            m = LOC_RE.search(line)
            if not m or FRAME.search(line) or not ERR_MARK.search(line):
                continue
            # the load failure must be this error's own: on its line or the three before it
            if not any(LOAD_RE.search(l) for l in lines[max(0, i - 3):i + 1]):
                continue
            path = m.group(1)
            if path.startswith("file://"):
                path = path[len("file://"):]
            if os.path.isabs(path):
                rp = os.path.realpath(path)
                if not rp.startswith(real + os.sep):
                    continue
                path = os.path.relpath(rp, real)
            path = os.path.normpath(path)
            if path in own or path.startswith("..") or not tracked(self.repo, path):
                continue
            msg = re.sub(r"\d+", "N", m.group(2).strip())[:200]
            if msg:
                pairs.add((msg, path))
        return pairs

    def blocker_holds(self):
        """'L' / 'P' when the record shows a wall the model cannot move, else None."""
        if not self.history:
            return None
        last = self.history[-1]
        if last["pairs"]:                  # (L) a wall that was there before any edit
            try:
                with open(os.path.join(self.jd, "baseline.checks.txt"), encoding="utf-8") as fh:
                    base = self.load_pairs(fh.read())
            except OSError:
                base = set()
            for pair in last["pairs"] & base:
                if any(h["digest"] != last["digest"] and pair in h["pairs"]
                       for h in self.history[:-1]):
                    return "L"
        if self.seg > 1:                   # (P) the same failure however the files change
            cur = [h for h in self.history if h["seg"] == self.seg][-3:]
            if len(cur) == 3 and len({h["sig"] for h in cur}) == 1 \
                    and len({h["digest"] for h in cur}) >= 2:
                return "P"
        return None

    def blocker(self, reason, evidence):
        checked = ""
        if self.ld.files_digest(self.repo, self.job["files"]) != self.checked_digest:
            text, _, _ = self.check(intermediate=True)    # judge on the files as they are
            if self.ended:
                return text, True, None
            checked = "\n\nThe check just run on your current files:\n" + text
        kind = self.blocker_holds()
        if kind is None:
            self.refusals += 1
            if self.refusals == 1:
                return ("refused: report_blocker is accepted only when (a) a load/compile error "
                        "at a path outside the editable files and the tests was already in the "
                        "baseline run and survived your edits, or (b) after a restart, the last "
                        "three checks fail the same way although the files changed. Keep "
                        "working on the editable files." + checked), False, None
            return "refused — keep working on the editable files." + checked, False, None
        self.job["blocker"] = {"reason": reason[:2000], "evidence": evidence[:2000],
                               "signature": str(self.history[-1]["sig"])[:300], "kind": kind}
        self.ended = ("fallback", "blocked")
        return "accepted — your diagnosis is handed on.", True, None

    # ---- restart
    def where_you_are(self, budget_tokens):
        diffs = []
        for f in self.job["files"]:
            try:
                with open(os.path.join(self.jd, "originals", f), encoding="utf-8") as fh:
                    a = fh.read().splitlines(keepends=True)
            except (OSError, UnicodeDecodeError):
                a = []
            b = read_text(self.repo, f).splitlines(keepends=True)
            diffs.append("".join(difflib.unified_diff(a, b, "a/" + f, "b/" + f)))
        diff = "".join(diffs) or "(no change yet)"
        tail = self.history[-1]["out"][-self.ld.FEEDBACK_CHARS:] if self.history else "(no check yet)"
        k = self.restarts + 1
        head = (f"## Where you are (restart {k} of {self.cfg['max_restarts']})\n"
                "The files above are as they are now. Your edits so far, against the files before "
                "you started:\n```diff\n")
        mid, tail_head = "\n```\n\nThe last check said:\n```\n", "\n```"
        dn, tn = len(diff), len(tail)
        while True:
            text = head + cut_middle(diff, dn) + mid + cut_middle(tail, tn) + tail_head
            cut = dn < len(diff) or tn < len(tail)
            if self.ld.estimate_tokens(text) <= budget_tokens:
                # cut down below MIN_SUFFIX, it no longer says where the work stands
                return "" if cut and len(text) < MIN_SUFFIX else text
            if dn < 200 and tn < 200:
                return ""
            if dn >= 200:                  # the diff gives way first, then the check's tail
                dn = dn * 2 // 3
            else:
                tn = tn * 2 // 3

    def restart(self):
        """A fresh conversation on the same job: same scope, same files, same attempts."""
        if self.restarts >= self.cfg["max_restarts"] or \
                self.w.budget() < 0.25 * self.cfg["total_timeout_min"] * 60:
            return False
        bodies, label = self.bodies, self.label
        self.bodies = {f: read_text(self.repo, f) for f in self.job["files"]}
        self.label = f"now (restart {self.restarts + 1})"
        base = est_tokens(self.ld, [{"role": "system", "content": AGENT_SYSTEM},
                                    {"role": "user", "content": self.first_message(suffix="")}])
        slack = self.cfg["num_ctx"] - base - self.cfg["max_output_tokens"] - reserve(self.ld)
        suffix = self.where_you_are(slack) if slack > 0 else ""
        if not suffix:
            self.bodies, self.label = bodies, label
            return False
        self.suffix = suffix
        self.restarts += 1
        self.seg += 1
        self.job["restarts"] = self.restarts
        self.tools.reads, self.tools.ranges = {}, set()
        self.tools.edit_misses, self.tools.edits_since_check = {}, 0
        self.last_sig, self.ended, self.refusals = None, None, 0
        self.start_segment()
        return True

    # ---- main
    def final_check(self, state, reason):
        """The last edit was never checked — it may pass."""
        if state == "fallback" and reason in ("max_turns", "stuck", "context_overflow") \
                and not self.ended \
                and self.ld.files_digest(self.repo, self.job["files"]) != self.checked_digest:
            self.check(intermediate=False)
            if self.ended:
                return self.ended
        return state, reason

    def end(self, state, reason=None):
        self.release()
        if self.job["attempts"]:
            self.job["attempts"][-1]["intermediate"] = False
        self.scope.finish()
        record(self.job, self.scope)
        return self.w.finish(state, reason)

    def run(self):
        w = self.w
        self.job["state"] = "running"
        w.save()
        if self.job.get("escalated_from"):  # S0 was taken before the one-shot part
            saved = Scope.load(self.ld, self.repo, self.jd, self.job)
            self.scope.s0 = saved.s0 if saved else {}
        else:
            self.scope.before_baseline()
        reason = w.baseline()
        if reason:
            return self.end("fallback", reason)
        if self.ld.restore_changed_tests(self.repo, self.jd, self.job["tests"]):
            return self.end("fallback", "tests_modified")
        self.scope.after_baseline()
        if self.job.get("escalated_from"):  # only now is it an agent job a settler can scope
            self.job["mode"] = "agent"
            w.save()
        self.checked_digest = self.ld.files_digest(self.repo, self.job["files"])
        self.bodies = {f: read_text(self.repo, f) for f in self.job["files"]}
        self.job.setdefault("turns", [])
        self.start_segment()
        while True:
            state, reason = self.segment()
            state, reason = self.final_check(state, reason)
            if state == "fallback" and reason in ("max_turns", "stuck", "context_overflow") \
                    and not self.no_restart and self.restart():
                continue
            return self.end(state, reason)

    def segment(self):
        """One conversation: (state, reason) when it ends."""
        w = self.w
        idle, timeouts = 0, 0
        for n in range(1, self.cfg["max_turns"] + 1):
            self.turn = n
            ok, elided = self.fit()
            if not ok:
                self.job["turns"].append({"n": n, "seg": self.seg, "outcome": "context_overflow",
                                          "elided": elided})
                return "fallback", "context_overflow"
            d, err, secs = self.call_model()
            w.active += secs
            turn = {"n": n, "seg": self.seg, "gen_s": round(secs, 1), "think": self.think,
                    "elided": elided}
            self.job["turns"].append(turn)
            if err == "total_timeout":
                turn["outcome"] = err
                return "fallback", err
            if d is None:
                turn["outcome"] = err.split(":")[0]
                timeouts += 1
                if timeouts >= 2:
                    return "fallback", ("attempt_timeout" if err == "attempt_timeout"
                                        else "model_error")
                self.think = False
                self.feedback(f"The previous call failed ({err}). Answer more briefly — one "
                              "tool call.")
                continue                   # two failures in a row end the job above
            timeouts = 0                   # the model answers: scattered call failures reset
            msg = d.get("message") or {}
            content = msg.get("content") if isinstance(msg.get("content"), str) else ""
            thinking = msg.get("thinking") if isinstance(msg.get("thinking"), str) else ""
            calls = msg.get("tool_calls") if isinstance(msg.get("tool_calls"), list) else []
            calls = [c for c in calls if isinstance(c, dict)]
            turn.update(prompt_tokens=d.get("prompt_eval_count"), output_tokens=d.get("eval_count"),
                        prompt_s=round((d.get("prompt_eval_duration") or 0) / 1e9, 1),
                        done_reason=d.get("done_reason"))
            if not calls:
                calls = parse_text_calls(content)
                if calls:
                    turn["text_calls"] = len(calls)
                    content = ""
            progress = False
            if d.get("done_reason") == "length" and not calls:
                turn["outcome"] = "output_cap"
                if content.strip():
                    self.add({"role": "assistant", "content": content})
                if not content.strip() and thinking.strip() and self.think:
                    self.think = False
                    self.feedback("Your reasoning so far was cut at the output limit. Its last "
                                  "part:\n" + thinking[-self.ld.CARRY_CHARS:]
                                  + "\n\nDo not reason again. Call the tools now.")
                else:
                    self.feedback("Your reply hit the output limit. Be brief: answer with one "
                                  "tool call.")
            elif calls:
                self.add({"role": "assistant", "content": content, "tool_calls": calls})
                turn["tools"] = []
                for j, c in enumerate(calls):
                    f = c.get("function") if isinstance(c.get("function"), dict) else {}
                    name = f.get("name")
                    turn["tools"].append(name if isinstance(name, str) else repr(name))
                    if j >= CALLS_PER_TURN:
                        text, prog, key = (f"error: at most {CALLS_PER_TURN} tool calls per "
                                           "reply — this one was not run"), False, None
                    else:
                        t0 = time.monotonic()
                        text, prog, key = self.tools.call(name, f.get("arguments") or {})
                        if name not in ("run_tests", "report_blocker"):   # checks count their own
                            w.active += time.monotonic() - t0
                    i = self.add({"role": "tool", "content": text,
                                  "tool_name": name if isinstance(name, str) else "?"})
                    if key:
                        self.tools.reads[key] = (i, n)
                    progress = progress or prog
                    if self.ended:
                        return self.ended
                if self.tools.edits_since_check >= EDITS_BEFORE_CHECK:
                    text, prog, _ = self.check(intermediate=True)
                    self.feedback("(checks run automatically after several edits)\n" + text)
                    progress = progress or prog
                    if self.ended:
                        return self.ended
            else:
                if content.strip():
                    self.add({"role": "assistant", "content": content})
                if self.ld.files_digest(self.repo, self.job["files"]) != self.checked_digest:
                    text, prog, _ = self.check(intermediate=False)
                    if self.ended:
                        return self.ended
                    self.feedback("The checks are still red:\n" + text
                                  + "\n\nContinue with the tools.")
                    progress = prog
                else:
                    self.feedback("Nothing changed since the last check. Use the tools: "
                                  "outline/search/read_file, edit_file, run_tests.")
            idle = 0 if progress else idle + 1
            w.save()
            if idle >= STUCK_TURNS or any(v >= EDIT_MISS_LIMIT
                                          for v in self.tools.edit_misses.values()):
                return "fallback", "stuck"
            if w.budget() <= 0:
                return "fallback", "total_timeout"
        return "fallback", "max_turns"


def run(worker, ld, prior=None):
    r = Run(ld, worker, prior)
    try:
        return r.run()
    except Exception:
        try:                               # what the crashed turn's checks left behind
            if r.scope.s1_taken:
                r.scope.check()
                r.scope.finish()
                record(r.job, r.scope)
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        r.release()
