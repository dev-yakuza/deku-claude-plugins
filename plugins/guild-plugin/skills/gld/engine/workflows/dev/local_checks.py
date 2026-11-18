"""workflows.dev.local_checks — the checks the engine runs itself before a 1L (local-model) commit
(user decision K3r1 Q2, K3r2-M2): the SAME set the repo's pre-commit hook runs for a Claude developer
commit, read from <base>'s `lefthook.yml` (never the branch's), minus

* the commit gate (the engine runs <base>'s gate itself, `--git-hook`), and
* commands that run the test suite (the engine's own suite runs right after the commit).

`config.engine.local_checks` overrides: a list of commands (replaces the derived set) or
`{"skip": [names], "extra": [commands]}`. No lefthook and no override → `commands.lint` +
`commands.typecheck`.

A command is a `&&`/`;` chain: the steps that RUN THE TESTS and later steps that read what such a step
wrote (`--file-reporter json:<f>` → a step naming `<f>`) are dropped, the rest stays (word_app's
`flutter analyze && … flutter test … && verify_test_coverage.sh <report>` keeps `flutter analyze`,
K3r3-M1).

Each check runs OFFLINE in the 1L sandbox with `{staged_files}` substituted by the staged files that
match its `glob` (lefthook semantics incl. braces; a pattern this reader cannot expand → ALL staged
files, never a silent skip) and not its `exclude`; no matching file → not run (lefthook's own rule).

K3r3-M2 — env is decided ONLY from preconditions the ENGINE observes before the run (`prepare`):
a script the check runs exists at <base> (and the BASE copy is what runs), an `npx` tool resolves in
the engine-prepared node_modules (deps step), any other program resolves on PATH. A failed precondition
→ `skipped(env: <which>)`; once they hold, ANY non-zero exit refuses the commit. Output text is never
read to decide env.
"""

import fnmatch
import os
import re
import shlex

BRACE_RE = re.compile(r"\{([^{}]*)\}")
UNKNOWN_GLOB_RE = re.compile(r"[!@+]\(|\[\[:|\\")
REPORT_RE = re.compile(r"--file-reporter[ =]json:(\S+)|--json(?:-output)?[ =](\S+)|--outputFile[ =](\S+)")
TEST_RUN_RE = re.compile(r"\b(flutter test|dart test|npm (run )?test|yarn test|pnpm test|pytest|go test|jest|vitest|"
                         r"cargo test|python3? -m (unittest|pytest))\b")
GATE_RE = re.compile(r"gate_precommit\.py")

# ---- a minimal YAML reader for lefthook's shape (no PyYAML on the host) ----------------------------

def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def parse_yaml(text):
    """Mappings, `- item` lists and `>`/`|` block scalars by indentation; comments dropped. Enough for
    lefthook.yml; anything else is read best-effort (unknown shapes are ignored by the caller)."""
    lines = []
    for raw in (text or "").split("\n"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            lines.append((None, raw))
            continue
        lines.append((len(raw) - len(raw.lstrip(" ")), raw))

    def block(i, indent):
        out, kind = None, None
        while i < len(lines):
            ind, raw = lines[i]
            if ind is None:
                i += 1
                continue
            if ind < indent:
                break
            st = raw.strip()
            if st.startswith("- "):
                if kind is None:
                    out, kind = [], "list"
                if kind != "list":
                    break
                out.append(_scalar(st[2:]))
                i += 1
                continue
            m = re.match(r"^([^:#]+?):(\s+(.*))?$", st)
            if not m:
                i += 1
                continue
            if kind is None:
                out, kind = {}, "map"
            if kind != "map":
                break
            key, val = m.group(1).strip().strip("'\""), (m.group(3) or "").strip()
            val = re.sub(r"\s+#.*$", "", val) if not val.startswith(("'", '"')) else val
            if val in (">", ">-", "|", "|-", ">+", "|+"):
                j, buf = i + 1, []
                while j < len(lines) and (lines[j][0] is None or lines[j][0] > ind):
                    buf.append(lines[j][1].strip())
                    j += 1
                sep = " " if val.startswith(">") else "\n"
                out[key] = sep.join(x for x in buf if x).strip()
                i = j
            elif val == "":
                sub, i = block(i + 1, ind + 1)
                out[key] = sub
            else:
                out[key] = _scalar(val)
                i += 1
        return out, i
    v, _ = block(0, 0)
    return v or {}


# ---- the check list ---------------------------------------------------------------------------------

def expand_braces(pat):
    m = BRACE_RE.search(pat)
    if not m:
        return [pat]
    out = []
    for alt in m.group(1).split(","):
        out += expand_braces(pat[:m.start()] + alt + pat[m.end():])
    return out


def glob_match(path, pattern):
    """lefthook-style: braces expanded, `*`/`**` across directories, matched on the path or the base
    name. Returns None when the pattern uses syntax this reader does not implement."""
    if UNKNOWN_GLOB_RE.search(pattern or ""):
        return None
    for p in expand_braces(pattern):
        p2 = p.replace("**/", "*").replace("**", "*")
        if fnmatch.fnmatch(path, p2) or fnmatch.fnmatch(path.rsplit("/", 1)[-1], p2):
            return True
    return False


def split_chain(run):
    """`a && b; c` → [a, b, c] (operators outside quotes)."""
    steps, cur, q, i = [], "", None, 0
    while i < len(run):
        ch = run[i]
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in "'\"":
            q, cur = ch, cur + ch
        elif run.startswith("&&", i) or ch == ";":
            steps.append(cur.strip())
            cur = ""
            i += 2 if ch == "&" else 1
            continue
        else:
            cur += ch
        i += 1
    if cur.strip():
        steps.append(cur.strip())
    return [s for s in steps if s]


def split_pipes(step):
    """One `&&`/`;` step → its commands across `|` and `||` (outside quotes) — K3r4-m4: every command
    is checked and rewritten, not only the first."""
    parts, cur, q, i = [], "", None, 0
    while i < len(step):
        ch = step[i]
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in "'\"":
            q, cur = ch, cur + ch
        elif ch == "|":
            parts.append(cur.strip())
            cur = ""
            i += 2 if step.startswith("||", i) else 1
            continue
        else:
            cur += ch
        i += 1
    if cur.strip():
        parts.append(cur.strip())
    return [x for x in parts if x]


def strip_test_steps(run):
    """(kept command or None, dropped steps)."""
    kept, dropped, outputs = [], [], []
    for st in split_chain(run):
        if TEST_RUN_RE.search(st):
            dropped.append(st)
            for m in REPORT_RE.finditer(st):
                outputs.append(next(g for g in m.groups() if g))
            continue
        if any(o and o in st for o in outputs):
            dropped.append(st)
            continue
        kept.append(st)
    return (" && ".join(kept) if kept else None), dropped


class Check(object):
    def __init__(self, name, run, glob=None, exclude=(), source="lefthook"):
        self.name, self.run, self.glob, self.exclude, self.source = name, run, glob, list(exclude or []), source

    def files(self, staged):
        out = []
        for f in staged:
            if self.glob and glob_match(f, self.glob) is False:     # None (unknown syntax) → keep the file
                continue
            if any(glob_match(f, x) for x in self.exclude):
                continue
            out.append(f)
        return out

    def command(self, staged):
        """The shell command for these staged files, or None (lefthook skips a command whose glob
        matches nothing)."""
        if self.glob or "{staged_files}" in self.run:
            fs = self.files(staged)
            if not fs:
                return None
            return self.run.replace("{staged_files}", " ".join(shlex.quote(f) for f in fs))
        return self.run


def load_config(name, text):
    """K4r2-m9: a base lefthook config of any name lefthook reads → a mapping (yml/yaml by the
    minimal reader, json by `json`, toml by `tomllib` when the host has it) — None when unreadable."""
    import json
    low = name.lower()
    try:
        if low.endswith(".json"):
            doc = json.loads(text)
        elif low.endswith(".toml"):
            import tomllib
            doc = tomllib.loads(text)
        else:
            doc = parse_yaml(text)
    except (ValueError, ImportError):
        return None
    return doc if isinstance(doc, dict) else None


def derive(lefthook_text, raw_config, skipped=None):
    """[Check] for a 1L commit; `skipped` collects (name, why) for the dropped hook commands.
    `lefthook_text` is the config text (YAML) or an already-loaded mapping (`load_config`)."""
    skipped = skipped if skipped is not None else []
    eng = (raw_config or {}).get("engine") or {}
    over = eng.get("local_checks")
    if isinstance(over, list):
        return [Check("config:%d" % i, c, source="config") for i, c in enumerate(over)]
    skip_names = set((over or {}).get("skip") or []) if isinstance(over, dict) else set()
    out = []
    if lefthook_text or isinstance(lefthook_text, dict):
        doc = lefthook_text if isinstance(lefthook_text, dict) else parse_yaml(lefthook_text)
        cmds = ((doc.get("pre-commit") or {}).get("commands") or {}) if isinstance(doc, dict) else {}
        for name, c in (cmds.items() if isinstance(cmds, dict) else []):
            run = (c or {}).get("run") if isinstance(c, dict) else None
            if not run:
                continue
            if name in skip_names:
                skipped.append((name, "config skip"))
            elif GATE_RE.search(run):
                skipped.append((name, "the engine runs <base>'s gate itself"))
            else:
                kept, dropped = strip_test_steps(run)
                if dropped:
                    skipped.append((name, "test-run steps dropped (the engine's suite covers them): %s"
                                    % " && ".join(dropped)))
                if kept is None:
                    continue
                ex = c.get("exclude")
                out.append(Check(name, kept, c.get("glob"), ex if isinstance(ex, list) else ([ex] if ex else [])))
    else:
        for key in ("lint", "typecheck"):
            v = ((raw_config or {}).get("commands") or {}).get(key)
            for i, c in enumerate([v] if isinstance(v, str) else list(v or [])):
                out.append(Check("commands.%s%s" % (key, ("[%d]" % i) if i else ""), c, source="commands"))
    for i, c in enumerate(((over or {}).get("extra") or []) if isinstance(over, dict) else []):
        out.append(Check("extra:%d" % i, c, source="config"))
    return out


def classify(result):
    """pass | fail. Env is NEVER read from the output (K3r3-M2) — see `prepare`."""
    return "pass" if result.passed else "fail"


SCRIPT_RUNNERS = ("bash", "sh", "zsh", "python3", "python", "node", "perl", "ruby")
BUILTINS = ("exit", "true", "false", "test", "[", "cd", "echo", "printf", "export", "set", ":", "if", "then",
            "fi", "for", "do", "done", "while", "case", "esac", "!", "{", "(")
STEP_RE = re.compile(r"^(\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*)(\S+)(\s+)?(\S+)?(.*)$", re.S)


def prepare(command, base_has, base_export, node_bin, which):
    """Engine-observed preconditions for one check command. Returns (command to run, None) or
    (None, "<precondition> failed: …"). Only the head of each `&&`/`;` step is rewritten (pipes,
    `||`, quoting stay as written).
    base_has(path) → bool: the path is a file at <base>;  base_export(path) → abs path of the BASE copy;
    node_bin: the engine-prepared `node_modules/.bin` (or None);  which(name) → path or None."""
    out = command
    if re.search(r"\$\(|`", command):
        return None, "precondition unverifiable: command substitution in `%s`" % command[:60]
    for st in [c for step in split_chain(command) for c in split_pipes(step)]:
        m = STEP_RE.match(st)
        if not m:
            continue
        env_pre, head, sp, arg, rest = m.group(1), m.group(2), m.group(3) or "", m.group(4) or "", m.group(5) or ""
        new = None
        if head == "npx":
            words = (arg + rest).split()
            while words and words[0] in ("--yes", "-y", "--no-install", "--offline"):
                words.pop(0)
            tool = words[0] if words else ""
            exe = os.path.join(node_bin, tool) if node_bin and tool else None
            if not exe or not os.path.exists(exe):
                return None, "npx tool `%s` not prepared by the deps step" % tool
            new = "%s%s %s" % (env_pre, shlex.quote(exe), (arg + rest).split(tool, 1)[1].lstrip())
        elif head in SCRIPT_RUNNERS and arg and not arg.startswith("-"):
            if not which(head):
                return None, "`%s` not on PATH" % head
            if not base_has(arg):
                return None, "script %s is not at <base>" % arg
            new = "%s%s%s%s%s" % (env_pre, head, sp, shlex.quote(base_export(arg)), rest)
        elif "/" in head and not head.startswith("/"):
            if not base_has(head.lstrip("./")):
                return None, "script %s is not at <base>" % head
            new = "%s%s%s%s%s" % (env_pre, shlex.quote(base_export(head.lstrip("./"))), sp, arg, rest)
        elif head not in BUILTINS and not which(head):
            return None, "`%s` not on PATH" % head
        if head in ("flutter", "fvm") and re.search(r"\b(analyze|test)\b", st) and "--no-pub" not in st:
            # the checks run OFFLINE; flutter's implicit `pub get` would fail on pub.dev (measured, K3r3) —
            # dependencies come from the deps step
            new = re.sub(r"\b(flutter\s+(?:analyze|test))\b", r"\1 --no-pub", new if new is not None else st, count=1)
        if new is not None:
            out = out.replace(st, new, 1)
    return out, None


def npx_tools(checks):
    """Tools the checks fetch through `npx <tool>` — prefetched by the deps step under the proxy."""
    out = []
    for c in checks:
        for m in re.finditer(r"\bnpx\s+(?:--yes\s+|-y\s+)?([@\w./-]+)", c.run):
            if m.group(1) not in out:
                out.append(m.group(1))
    return out
