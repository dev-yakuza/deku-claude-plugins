"""workflows.dev.local_checks — the checks the engine runs itself before a 1L (local-model) commit
(user decision K3r1 Q2, K3r2-M2): the SAME set the repo's pre-commit hook runs for a Claude developer
commit, read from <base>'s `lefthook.yml` (never the branch's), minus

* the commit gate (the engine runs <base>'s gate itself, `--git-hook`), and
* commands that run the test suite (the engine's own suite runs right after the commit).

`config.engine.local_checks` overrides: a list of commands (replaces the derived set) or
`{"skip": [names], "extra": [commands]}`. No lefthook and no override → `commands.lint` +
`commands.typecheck`.

Each check runs OFFLINE in the 1L sandbox with `{staged_files}` substituted by the staged files that
match its `glob` (and not its `exclude`); no matching file → not run (lefthook's own rule). A check that
fails for an ENVIRONMENT reason (tool missing, a fetch with no network) is `skipped(env: …)` — recorded,
never a refusal; any other non-zero exit refuses the commit.
"""

import fnmatch
import re
import shlex

TEST_RUN_RE = re.compile(r"\b(flutter test|dart test|npm (run )?test|yarn test|pnpm test|pytest|go test|jest|vitest|"
                         r"cargo test|python3? -m (unittest|pytest))\b")
GATE_RE = re.compile(r"gate_precommit\.py")
ENV_FAIL_RE = re.compile(r"command not found|not found: |No such file or directory.*(npx|dart|node|flutter)|"
                         r"ENOTFOUND|EAI_AGAIN|ECONNREFUSED|ETIMEDOUT|network request|npm ERR! code E(NOTFOUND|AI_AGAIN|"
                         r"CONNREFUSED|TIMEDOUT)|getaddrinfo|Could not resolve host|Failed host lookup|"
                         r"npm error (code )?E(NOTFOUND|AI_AGAIN|CONNREFUSED)|request to https?://\S+ failed", re.I)


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

class Check(object):
    def __init__(self, name, run, glob=None, exclude=(), source="lefthook"):
        self.name, self.run, self.glob, self.exclude, self.source = name, run, glob, list(exclude or []), source

    def files(self, staged):
        out = []
        for f in staged:
            if self.glob and not (fnmatch.fnmatch(f, self.glob) or fnmatch.fnmatch(f.rsplit("/", 1)[-1], self.glob)):
                continue
            if any(fnmatch.fnmatch(f, x) for x in self.exclude):
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


def derive(lefthook_text, raw_config, skipped=None):
    """[Check] for a 1L commit; `skipped` collects (name, why) for the dropped hook commands."""
    skipped = skipped if skipped is not None else []
    eng = (raw_config or {}).get("engine") or {}
    over = eng.get("local_checks")
    if isinstance(over, list):
        return [Check("config:%d" % i, c, source="config") for i, c in enumerate(over)]
    skip_names = set((over or {}).get("skip") or []) if isinstance(over, dict) else set()
    out = []
    if lefthook_text:
        doc = parse_yaml(lefthook_text)
        cmds = ((doc.get("pre-commit") or {}).get("commands") or {}) if isinstance(doc, dict) else {}
        for name, c in (cmds.items() if isinstance(cmds, dict) else []):
            run = (c or {}).get("run") if isinstance(c, dict) else None
            if not run:
                continue
            if name in skip_names:
                skipped.append((name, "config skip"))
            elif GATE_RE.search(run):
                skipped.append((name, "the engine runs <base>'s gate itself"))
            elif TEST_RUN_RE.search(run):
                skipped.append((name, "runs the test suite — the engine's suite covers it"))
            else:
                ex = c.get("exclude")
                out.append(Check(name, run, c.get("glob"), ex if isinstance(ex, list) else ([ex] if ex else [])))
    else:
        for key in ("lint", "typecheck"):
            v = ((raw_config or {}).get("commands") or {}).get(key)
            for i, c in enumerate([v] if isinstance(v, str) else list(v or [])):
                out.append(Check("commands.%s%s" % (key, ("[%d]" % i) if i else ""), c, source="commands"))
    for i, c in enumerate(((over or {}).get("extra") or []) if isinstance(over, dict) else []):
        out.append(Check("extra:%d" % i, c, source="config"))
    return out


def classify(result):
    """pass | fail | env:<reason> for one check's CheckResult."""
    if result.passed:
        return "pass"
    raw = result.raw or ""
    if result.rc == 127 or ENV_FAIL_RE.search(raw):
        m = ENV_FAIL_RE.search(raw)
        return "env:%s" % ((m.group(0) if m else "tool missing (rc 127)")[:80])
    return "fail"


def npx_tools(checks):
    """Tools the checks fetch through `npx <tool>` — prefetched by the deps step under the proxy."""
    out = []
    for c in checks:
        for m in re.finditer(r"\bnpx\s+(?:--yes\s+|-y\s+)?([@\w./-]+)", c.run):
            if m.group(1) not in out:
                out.append(m.group(1))
    return out
