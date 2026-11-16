"""replay.permissions_check — offline reclassification of role Bash calls (§5.1, §10.2-3).

The port of `design/guild/measure/allow3.py`: read a sprint log's role Bash calls, split each
command quote-aware into its sub-commands, and decide per role whether the §5.1 rules would allow
it. Unlike allow3 (which had its own class regexes), the prediction is made from the SAME rule
lists `guildcore.roles.permissions` renders for the CLI — the K1 matcher calibration measures how
often the CLI's real decision equals this prediction (§10.2-3b item 2, gate ≥98%).

`predict_v0` is the pre-calibration model (prefix rules per sub-command, redirect = C3) — kept
for the record. `predict` (v1) adds what K1's micro-probes of CLI 2.1.311 in dontAsk showed
(`design/guild/measure/k1-local-smoke/calibration/probes/`), learned from probe commands, not from
the calibration sample:
  P1 a `$` expansion needs approval → denied: unquoted (`$X`, `$?`; bare `$HOME` excepted),
     `${…}`, `$(…)`, backticks, or a double-quoted word that is ONLY the expansion (`"$X"`,
     `x"$?"`); a simple `$X`/`$?` inside a longer double-quoted string (`"rc=$?"`) is fine; the
     commit-message idiom `"$(cat <<'EOF' … EOF )"` is fine;
  P2 a leading `VAR=value` assignment → denied;
  P3 `{ …; }` groups, `( … )` subshells and function definitions → denied;
  P4 an UNQUOTED heredoc (`<<EOF`) → denied; a quoted one (`<<'EOF'`) is fine;
  P5 `cd <cwd>` is neutral (the CLI strips it) unless the command also pipes (`cd …; a | b` is
     denied); `cd <elsewhere>` alone is allowed only inside the working directories, combined
     with any other sub-command it is denied; a `for`/`while` loop whose body pipes, and any
     `case`, are denied;
  P6 a path argument (absolute, `~…`, `../…`, quoted or not) outside the working directories
     (cwd + `--add-dir`) → denied — only for commands that take paths (cat, head, ls, grep's
     files, sed's files, cp, mkdir, find, git, …); a pattern/script argument (grep/rg/sed/awk/jq
     first operand, `python3 -c`) and path-string commands (basename, dirname, realpath,
     readlink, xxd, echo) are not paths;
  P7 an output redirection to a file (not /dev/null, not an fd) needs a path-scoped
     `Write(//…)`/`Edit(//…)` rule covering the target (a bare `Write` does not count);
  P8 then every sub-command must match an allow prefix rule and none may match a deny rule.
"""

import fnmatch
import glob
import json
import os
import re

ROLE_RE = re.compile(r"\b(developer|tester|qa|tech-lead|security|i18n|designer|tech-writer|"
                     r"performance|dba|analytics|infra|product-owner|explorer)\b", re.I)
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _strip_heredoc_bodies(cmd):
    out, pos = [], 0
    for m in re.finditer(r"<<-?\s*(['\"]?)(\w+)\1", cmd):
        if m.start() < pos:
            continue
        nl = cmd.find("\n", m.end())
        if nl < 0:
            break
        end = re.search(r"\n\s*%s\s*(?=\n|$)" % re.escape(m.group(2)), cmd[nl:])
        out.append(cmd[pos:nl])
        pos = nl + (end.end() if end else len(cmd) - nl)
    out.append(cmd[pos:])
    return "".join(out)


def tokens(cmd):
    """Quote-aware shell words and operators of `cmd` (heredoc bodies dropped). Words keep
    their quoting as written; operators are `&& || ; | |& & ( ) newline` and redirections
    (`>`, `>>`, `<`, `<<`, `2>&1` …) are returned as ("redir", text)."""
    s = _strip_heredoc_bodies(cmd)
    out, cur, i, n = [], [], 0, len(s)
    depth = 0

    def flush():
        if cur:
            out.append(("word", "".join(cur)))
            del cur[:]
    while i < n:
        ch = s[i]
        if ch in "'\"`":
            j = i + 1
            while j < n and s[j] != ch:
                j += 2 if (s[j] == "\\" and ch != "'") else 1
            cur.append(s[i:j + 1])
            i = j + 1
            continue
        if ch == "\\" and i + 1 < n:
            cur.append(s[i:i + 2])
            i += 2
            continue
        if s.startswith("$(", i):
            j, d = i + 2, 1
            while j < n and d:
                d += {"(": 1, ")": -1}.get(s[j], 0)
                j += 1
            cur.append(s[i:j])
            i = j
            continue
        m = re.match(r"(\d?>>?&\d|&>>?|\d?>>?|\d?<<?<?|>\|)", s[i:])
        if m and (not cur or re.match(r"^\d$", "".join(cur)) or ch in "<>&"):
            if cur and re.match(r"^\d$", "".join(cur)):
                del cur[:]
            flush()
            op = m.group(1)
            i += len(op)
            if op.startswith("&") or ">" in op and not op.endswith(("&1", "&2")) or "<" in op:
                while i < n and s[i] in " \t":
                    i += 1
                j = i
                while j < n and s[j] not in " \t\n;&|)":
                    j += 1
                out.append(("redir", op + s[i:j]))
                i = j
            else:
                out.append(("redir", op))
            continue
        for op in ("&&", "||", "|&", ";;", ";", "|", "&", "\n", "(", ")", "{", "}"):
            if s.startswith(op, i) and (op not in ("{", "}") or not cur):
                flush()
                out.append(("op", op))
                i += len(op)
                break
        else:
            if ch in " \t":
                flush()
            else:
                cur.append(ch)
            i += 1
    flush()
    return out


_KEYWORDS = ("then", "else", "do", "!", "time", "elif")
_SKIP_FIRST = ("for", "while", "if", "case", "done", "fi", "esac", "in", "until", "function")


def parse_commands(cmd):
    """[(text, writes)] — each sub-command's words joined by single spaces, and whether it has
    an output redirection to something other than /dev/null or an fd."""
    res, cur, writes = [], [], False
    toks = tokens(cmd) + [("op", ";")]
    for kind, t in toks:
        if kind == "word":
            cur.append(t)
        elif kind == "redir":
            tgt = re.sub(r"^\d?(>>?|&>>?|>\|)", "", t)
            if (">" in t or t.startswith("&")) and not re.match(r"^\d?>>?&\d$", t) \
                    and tgt.strip() not in ("/dev/null", "/dev/stderr", "/dev/stdout"):
                writes = True
        else:
            words = list(cur)
            while words and (_ASSIGN.match(words[0]) or words[0] in _KEYWORDS):
                words = words[1:]
            if words and words[0] not in _SKIP_FIRST and not re.match(r"^\w+\s*\(\)$", words[0]):
                if not (len(words) >= 2 and words[1] == "()"):
                    res.append((" ".join(words), writes))
            cur, writes = [], False
    return res


def split_commands(cmd):
    return [t for t, _ in parse_commands(cmd)]


def _rule_body(rule):
    m = re.match(r"^Bash\((.*)\)$", rule)
    return m.group(1) if m else None


def rule_matches(rule, sub):
    body = _rule_body(rule)
    if body is None:
        return False
    if body.endswith(":*"):
        p = body[:-2]
        return sub == p or sub.startswith(p + " ")
    if "*" in body:
        return fnmatch.fnmatchcase(sub, body)
    return sub == body


def predict_v0(command, allow, deny, has_c3=None, **_kw):
    """('allow'|'deny', reason). `has_c3` defaults to "the allow list carries a C3 prefix"."""
    if has_c3 is None:
        has_c3 = "Bash(mkdir:*)" in allow
    subs = parse_commands(command)
    if not subs:
        return "allow", "empty"
    for s, _w in subs:
        s2 = re.sub(r"^git -C \S+ ", "git ", s)
        for r in deny:
            if rule_matches(r, s) or rule_matches(r, s2):
                return "deny", "deny-rule %s" % r
    for s, w in subs:
        if w and not has_c3:
            return "deny", "redirect-write %s" % s[:60]
        if not any(rule_matches(r, s) for r in allow):
            return "deny", "no-allow %s" % s[:60]
    return "allow", "all-allowed"


_COMMIT_IDIOM = re.compile(r"\"\$\(cat <<'?(\w+)'?\n.*?\n\1\n?\)\"", re.S)
_PATH_RULE = re.compile(r"^(Write|Edit)\(//(.*)\)$")


def _unquoted(text):
    """`text` with single-quoted spans blanked (expansions there are literal)."""
    return re.sub(r"'[^']*'", "''", text)


def _inside(path, roots):
    p = os.path.normpath(path)
    return any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots)


def _resolve(arg, cwd, home):
    a = arg.strip("'\"")
    if a.startswith("~"):
        a = (home or "/nonexistent-home") + a[1:]
    if not os.path.isabs(a):
        a = os.path.join(cwd or "/", a)
    return os.path.normpath(a)


def _write_rule_covers(allow, target):
    for r in allow:
        m = _PATH_RULE.match(r)
        if not m:
            continue
        pat = "/" + m.group(2)
        if pat.endswith("/**"):
            if _inside(target, [pat[:-3]]):
                return True
        elif fnmatch.fnmatchcase(target, pat):
            return True
    return False


PATH_CMDS = ("cat", "head", "tail", "ls", "cd", "cp", "mv", "rm", "touch", "mkdir", "rmdir",
             "chmod", "diff", "cmp", "find", "stat", "wc", "file", "sort", "uniq", "cut", "tr",
             "strings", "od", "grep", "rg", "sed", "awk", "jq", "git", "tee", "ln", "less", "more")
PATTERN_FIRST = ("grep", "rg", "sed", "awk", "jq")


def _words(sub):
    out = []
    for k, t in tokens(sub):
        if k == "word":
            out.append(t)
    return out


def path_args(sub):
    """Operands of a path-taking command, quotes removed, the pattern/script operand skipped."""
    ws = _words(sub)
    if not ws or ws[0] not in PATH_CMDS:
        return []
    ops, skip_first = [], ws[0] in PATTERN_FIRST
    has_e = any(w in ("-e", "-f", "--regexp", "--expression", "--file") for w in ws[1:])
    for w in ws[1:]:
        w2 = w.strip("'\"")
        if w.startswith("-") and not w2.startswith("/"):
            continue
        ops.append(w2)
    if skip_first and ops and not has_e:
        ops = ops[1:]
    return ops


def _expansion(uq):
    """The P1 reason, or None. `uq` has single-quoted spans blanked."""
    if "`" in uq:
        return "backtick"
    if re.search(r"\$\(|\$\{", uq):
        return "command/brace expansion"
    dq = re.compile(r'"(?:[^"\\]|\\.)*"')
    for m in dq.finditer(uq):
        body = m.group(0)[1:-1]
        if re.fullmatch(r"\$[A-Za-z_?][A-Za-z0-9_]*", body):
            return "quoted lone expansion"
        start, end = m.start(), m.end()
        if "$" in body and ((start > 0 and not uq[start - 1].isspace() and uq[start - 1] not in "=;&|(")
                            or (end < len(uq) and not uq[end].isspace() and uq[end] not in ";&|)")):
            return "glued quoted expansion"
    bare = dq.sub('""', uq)
    for m in re.finditer(r"\$([A-Za-z_?][A-Za-z0-9_]*|[0-9#@*!-])", bare):
        if m.group(1) == "HOME" and (m.end() == len(bare) or bare[m.end()] in " \t\n;&|"):
            continue
        return "unquoted $%s" % m.group(1)
    return None


def predict_v2(command, allow, deny, has_c3=None, cwd=None, dirs=(), home=None):
    """v1 — ('allow'|'deny', reason) under the rules a session runs with; `cwd` and `dirs`
    (`--add-dir`) are the working directories."""
    roots = [os.path.normpath(d) for d in ([cwd] if cwd else []) + list(dirs or ())]
    cmd = _COMMIT_IDIOM.sub('"msg"', command)
    uq = _unquoted(_strip_heredoc_bodies(cmd))
    why = _expansion(uq)
    if why:
        return "deny", "P1 " + why
    if re.search(r"(^|[;&|\s])case\s", uq):
        return "deny", "P5 case"
    if "|" in re.sub(r"\|\||'[^']*'|\"[^\"]*\"", "", uq):
        if re.search(r"(^|[;&|(\s])cd(\s|$)", uq):
            return "deny", "P5 cd + pipe"
        if re.search(r"(^|[;&\s])(for|while|until)\s", uq):
            return "deny", "P5 loop + pipe"
    if re.search(r"<<-?\s*[A-Za-z_]", uq):
        return "deny", "P4 unquoted heredoc"
    toks = tokens(cmd)
    if any(k == "op" and t in ("(", ")", "{", "}") for k, t in toks):
        return "deny", "P3 group/subshell/function"
    subs = parse_commands(cmd)
    if not subs:
        return "allow", "empty"
    # P2: assignment prefixes are dropped by parse_commands — look at the raw words
    cur = []
    for k, t in toks + [("op", ";")]:
        if k == "word":
            cur.append(t)
            continue
        if cur and _ASSIGN.match(cur[0]):
            return "deny", "P2 assignment prefix"
        cur = []
    kept = []
    for s_, w in subs:
        if s_ == "cd" or s_.startswith("cd "):
            target = _resolve(s_[3:].strip() or "~", cwd, home)
            if cwd and target == os.path.normpath(cwd):
                continue
            if len(subs) > 1:
                return "deny", "P5 cd + other"
            if not _inside(target, roots):
                return "deny", "P5 cd outside"
        kept.append((s_, w))
    for s_, _w in kept:
        s2 = re.sub(r"^git -C \S+ ", "git ", s_)
        for r in deny:
            if rule_matches(r, s_) or rule_matches(r, s2):
                return "deny", "deny-rule %s" % r
    for s_, _w in kept:
        for a2 in path_args(s_):
            if a2.startswith(("/", "~", "../")) or a2 == "..":
                if a2.startswith("/dev/"):
                    continue
                if not _inside(_resolve(a2, cwd, home), roots):
                    return "deny", "P6 path outside %s" % a2[:50]
    for k, t in toks:
        if k == "redir" and (">" in t or t.startswith("&")) and not re.match(r"^\d?>>?&\d$", t):
            tgt = re.sub(r"^\d?(>>?|&>>?|>\|)", "", t).strip()
            if tgt in ("/dev/null", "/dev/stderr", "/dev/stdout") or not tgt:
                continue
            path = _resolve(tgt, cwd, home)
            if not _inside(path, roots) or not _write_rule_covers(allow, path):
                return "deny", "P7 redirect %s" % tgt[:50]
    for s_, _w in kept:
        if not any(rule_matches(r, s_) for r in allow):
            return "deny", "no-allow %s" % s_[:60]
    return "allow", "all-allowed"


_WRAPPERS = ("env", "command", "builtin", "exec", "time", "nohup", "nice", "timeout", "xargs")


def _inner_commands(text):
    """Commands inside `$(…)` and backticks (one level per call, applied recursively)."""
    out = []
    i = 0
    while i < len(text):
        if text.startswith("$(", i):
            d, j = 1, i + 2
            while j < len(text) and d:
                d += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            out.append(text[i + 2:j - 1])
            i = j
        elif text[i] == "`":
            j = text.find("`", i + 1)
            if j < 0:
                break
            out.append(text[i + 1:j])
            i = j + 1
        else:
            i += 1
    return out


def _normalize(sub):
    """Strip wrappers the CLI looks through (env [-u X] [VAR=…], command, exec, time, nohup,
    timeout N, a leading backslash, an absolute path, double quotes on the command name)."""
    ws = sub.split()
    changed = True
    while ws and changed:
        changed = False
        w0 = ws[0].lstrip("\\")
        if w0.startswith('"') and w0.endswith('"') and len(w0) > 1:
            w0 = w0[1:-1]
        if "/" in w0 and not w0.startswith("./"):
            w0 = w0.rsplit("/", 1)[1]
        if w0 != ws[0]:
            ws[0], changed = w0, True
        if ws and _ASSIGN.match(ws[0]):
            ws, changed = ws[1:], True
        elif ws and ws[0] in ("env", "command", "builtin", "exec", "time", "nohup", "nice") and len(ws) > 1:
            ws = ws[1:]
            while ws and (ws[0].startswith("-") or _ASSIGN.match(ws[0])):
                ws = ws[2:] if ws[0] == "-u" else ws[1:]
            changed = True
        elif ws and ws[0] == "timeout" and len(ws) > 2:
            ws, changed = ws[2:], True
    return " ".join(ws)


def predict_q22(command, allow, deny, **_kw):
    """Q22 model (bare `Bash` + deny lists): allowed unless a sub-command — including those inside
    `$(…)`/backticks and after the wrappers above — matches a deny rule; `env` alone, `{ }`, `( )`
    groups are looked through. Path, expansion and redirect rules no longer apply (calibrated)."""
    todo, subs = [command], []
    while todo:
        c = todo.pop()
        todo += _inner_commands(c)
        subs += [s_ for s_, _w in parse_commands(c)]
    for s_ in subs:
        for cand in (s_, _normalize(s_), re.sub(r"^git -C \S+ ", "git ", _normalize(s_))):
            for r in deny:
                if rule_matches(r, cand):
                    return "deny", "deny-rule %s" % r
    # calibrated: a mid-wildcard rule is also matched against a whole pipeline
    # (`gh api x | grep -f y` hits `gh api * -f*`)
    mids = [r for r in deny if " * " in (_rule_body(r) or "")]
    for pipe in re.split(r"&&|\|\||;|\n", command):
        p_ = " ".join(pipe.split())
        if "|" in p_:
            for r in mids:
                if rule_matches(r, p_):
                    return "deny", "pipeline %s" % r
    return "allow", "q22"


def predict(command, allow, deny, has_c3=None, cwd=None, dirs=(), home=None):
    """Dispatch: bare `Bash` in the allow list → the Q22 model, else the allow-list model (v2)."""
    if "Bash" in allow:
        return predict_q22(command, allow, deny)
    return predict_v2(command, allow, deny, has_c3, cwd, dirs, home)


# ---- log extraction (allow3's reader) -----------------------------------------------------------

def role_of(description):
    m = ROLE_RE.search(description or "")
    return m.group(1).lower() if m else "other"


def calls_from_log(path):
    """[(role, command, log_path)] for every Bash call a spawned role made in one sprint log."""
    spawn, out = {}, []
    with open(path, errors="replace") as fh:
        for ln in fh:
            if not ln.startswith("{"):
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if e.get("type") != "assistant":
                continue
            par = e.get("parent_tool_use_id")
            for c in (e.get("message") or {}).get("content") or []:
                if c.get("type") != "tool_use":
                    continue
                if not par and c.get("name") in ("Agent", "Task"):
                    spawn[c.get("id")] = role_of((c.get("input") or {}).get("description"))
                elif par and c.get("name") == "Bash":
                    cmd = (c.get("input") or {}).get("command") or ""
                    out.append((spawn.get(par, "other"), cmd, path))
    return out


def calls_from_logs(log_glob):
    out = []
    for p in sorted(glob.glob(log_glob)):
        out.extend(calls_from_log(p))
    return out


def engine_role(log_role):
    """A logged spawn's role → the engine's (role, task) used for its rules."""
    return {"developer": ("developer", "implement"), "tester": ("tester", "verify"),
            "qa": ("qa", None), "tech-lead": ("tech-lead", "design")}.get(
        log_role, ("reviewer", None))


def reclassify(calls, rules_for):
    """{role: {"calls": n, "deny": k}} with `rules_for(role) -> (allow, deny)`."""
    out = {}
    for role, cmd, _ in calls:
        allow, deny = rules_for(role)
        v, _why = predict(cmd, allow, deny)
        r = out.setdefault(role, {"calls": 0, "deny": 0})
        r["calls"] += 1
        r["deny"] += v == "deny"
    return out


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from guildcore.roles import permissions as P
    tool = P.toolchain_prefixes(None, tracked_files=())
    tool += ["flutter", "dart", "fvm"]
    rules = {}

    def rules_for(role):
        if role not in rules:
            r, t = engine_role(role)
            rules[role] = P.role_rules(r, t, toolchain=tool)
        return rules[role]
    res = reclassify(calls_from_logs(sys.argv[1]), rules_for)
    for role, r in sorted(res.items()):
        print("%-12s %6d calls  deny %5.1f%%" % (role, r["calls"], 100.0 * r["deny"] / max(1, r["calls"])))
