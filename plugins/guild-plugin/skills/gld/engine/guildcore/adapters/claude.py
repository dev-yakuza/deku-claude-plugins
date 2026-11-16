"""guildcore.adapters.claude — every `claude -p` the engine spawns: argv, env contract, process, stream.

Only documented flags (§1.4, FR-F9): no `--system-prompt-file`, `--append-system-prompt-file`,
`--max-turns`, `--bare` or `--dangerously-skip-permissions`. Every session gets `--model`,
`--setting-sources ""` + `--settings <rendered>` (§5.1) and `--strict-mcp-config`.

Env contract (§5.1, R4C-M1) — laid over the parent env AND the merged settings env, always:
    CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1, CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0,
    BASH_DEFAULT_TIMEOUT_MS=600000, BASH_MAX_TIMEOUT_MS=<suite ceiling, 3600000>,
    + cache: FORCE_PROMPT_CACHING_5M=1 (roles, multi-turn judges) | DISABLE_PROMPT_CACHING=1
      (single-shot judges); judges also CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 and
      CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 (§3.1).

Endpoint guard (§5.1, R5C-M1): a non-default `ANTHROPIC_BASE_URL` (or any routing key) in the
parent env OR the merged settings env halts the engine (`EnvHalt("endpoint")` → exit 6
`halted: env endpoint`) unless `--allow-local-endpoint` or `config.engine.allowed_endpoints`
names it. The effective endpoint and model id go into every cost row.

Processes run in their own session/process group (`start_new_session`), are journaled as
{pid, pgid, start_time, session_id}, and are killed as a GROUP: SIGTERM → 10 s → SIGKILL —
and only after re-checking that pid's start time and that its cmdline carries the session id
(§2.7, R2C-n2), so an unrelated process that reused the pid is never touched.
"""

import json
import re
import os
import signal
import shutil
import subprocess
import time

from guildcore.roles.settings import ROUTING_KEYS

DEFAULT_ENDPOINT = "https://api.anthropic.com"
SUITE_CEILING_MS = 3600000
KILL_GRACE_S = 10
ENV_CONTRACT = {
    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
    "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0",
    "BASH_DEFAULT_TIMEOUT_MS": "600000",
    "BASH_MAX_TIMEOUT_MS": str(SUITE_CEILING_MS),
}
JUDGE_ENV = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
CACHE_ENV = {"5m": {"FORCE_PROMPT_CACHING_5M": "1"}, "off": {"DISABLE_PROMPT_CACHING": "1"},
             None: {}}
# keys the engine strips so a parent's choice cannot defeat the contract's cache mode
_CACHE_KEYS = ("FORCE_PROMPT_CACHING_5M", "DISABLE_PROMPT_CACHING", "ENABLE_PROMPT_CACHING_1H",
               "CLAUDE_CODE_PROMPT_CACHE_TTL")
FORBIDDEN_FLAGS = ("--system-prompt-file", "--append-system-prompt-file", "--max-turns", "--bare",
                   "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions")


class EnvHalt(Exception):
    """Environment-level prevalidate (§2.2): exit 6 + `halted: env <reason>`."""

    def __init__(self, reason, detail=""):
        Exception.__init__(self, "halted: env %s%s" % (reason, (" — " + detail) if detail else ""))
        self.reason = reason
        self.detail = detail


def _norm_url(u):
    return (u or "").strip().rstrip("/")


# model-id keys are not routing (every session passes --model); they are stripped from the child
# env instead of halting the engine (K1-m1)
MODEL_KEYS = tuple(k for k in ROUTING_KEYS if k.endswith("_MODEL"))
# Q23 defence in depth: a role's env carries no GitHub credential and no agent socket
_SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|CREDENTIAL|PRIVATE_KEY", re.I)
CLI_AUTH_KEYS = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
CREDENTIAL_KEYS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
                   "SSH_AUTH_SOCK", "GIT_ASKPASS", "SSH_ASKPASS")


def endpoint_guard(parent_env, settings_env=None, allow_local=False, allowed_endpoints=()):
    """The effective endpoint; raises EnvHalt('endpoint') for an unapproved routing override.
    A key whose value is the default endpoint, and the `*_MODEL` keys, are not overrides."""
    found = {}
    for src, env in (("env", parent_env or {}), ("settings", settings_env or {})):
        for k in ROUTING_KEYS:
            v = env.get(k)
            if v in (None, "") or k in MODEL_KEYS:
                continue
            if k == "ANTHROPIC_BASE_URL" and _norm_url(v) == DEFAULT_ENDPOINT:
                continue
            found["%s:%s" % (src, k)] = v
    base = _norm_url((settings_env or {}).get("ANTHROPIC_BASE_URL") or
                     (parent_env or {}).get("ANTHROPIC_BASE_URL")) or DEFAULT_ENDPOINT
    if not found:
        return DEFAULT_ENDPOINT
    allowed = set(_norm_url(x) for x in allowed_endpoints or ())
    if allow_local:
        return base
    only_base = all(k.endswith(":ANTHROPIC_BASE_URL") for k in found)
    if only_base and base in allowed:
        return base
    raise EnvHalt("endpoint", "non-default model routing (%s) needs --allow-local-endpoint or "
                  "config.engine.allowed_endpoints" % ", ".join(sorted(found)))


def child_env(parent_env, settings_env=None, cache="5m", judge=False, suite_ceiling_ms=None,
              extra=None, role_dir=None):
    """`role_dir` (a role's run dir) → GitHub credentials removed and `GH_CONFIG_DIR` pointed at
    an empty dir inside it (Q23 defence in depth; the sandbox's network list is the guard)."""
    env = dict(parent_env or {})
    env.update(settings_env or {})
    for k in _CACHE_KEYS + MODEL_KEYS:
        env.pop(k, None)
    if role_dir:
        for k in list(env):
            if k in CREDENTIAL_KEYS or k.startswith("GH_") or (
                    _SECRET_NAME.search(k) and k not in CLI_AUTH_KEYS):
                env.pop(k, None)
        # the CLI keeps its own auth, its Bash subprocesses get a scrubbed env (K1r2-M1)
        env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] = "1"
        tmp = os.path.join(role_dir, "tmp")
        os.makedirs(tmp, exist_ok=True)
        env["TMPDIR"] = tmp                  # a private TMPDIR, not /tmp/claude-<uid> (K1r2-M2)
        ghd = os.path.join(role_dir, "in", "gh-config-empty")
        os.makedirs(ghd, exist_ok=True)
        env["GH_CONFIG_DIR"] = ghd
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_CONFIG_NOSYSTEM"] = "1"
    env.update(ENV_CONTRACT)
    if suite_ceiling_ms:
        env["BASH_MAX_TIMEOUT_MS"] = str(int(suite_ceiling_ms))
    env.update(CACHE_ENV[cache])
    if judge:
        env.update(JUDGE_ENV)
    env.update(extra or {})
    return env


def role_argv(model, persona, allow, deny, run_dir, settings_path, session_id=None, resume=None,
              mcp_config=None, effort=None, agent=None, budget_usd=None, claude="claude"):
    """§5.1 role invocation. Persona goes in `--append-system-prompt` (argv)."""
    argv = [claude, "-p", "--model", model, "--output-format", "stream-json", "--verbose",
            "--permission-mode", "dontAsk",
            "--allowedTools", ",".join(allow),
            "--disallowedTools", ",".join(deny),
            "--setting-sources", "", "--settings", settings_path,
            "--strict-mcp-config", "--mcp-config", mcp_config or '{"mcpServers":{}}']
    if run_dir:
        argv += ["--add-dir", os.path.abspath(run_dir)]
    if persona:
        argv += ["--append-system-prompt", persona]
    if agent:
        argv += ["--agent", agent]
    if effort:
        argv += ["--effort", effort]
    if budget_usd is not None:
        argv += ["--max-budget-usd", "%g" % budget_usd]
    if resume:
        argv += ["--resume", resume]
    elif session_id:
        argv += ["--session-id", session_id]
    check_argv(argv)
    return argv


def judge_argv(model, system, schema, settings_path, tools="", budget_usd=None, effort=None,
               claude="claude"):
    """§3.1 judge invocation: json output, inline schema, replaced system prompt, no persistence."""
    argv = [claude, "-p", "--model", model, "--output-format", "json",
            "--json-schema", json.dumps(schema, separators=(",", ":"), ensure_ascii=False),
            "--system-prompt", system, "--tools", tools, "--strict-mcp-config",
            "--disable-slash-commands", "--setting-sources", "", "--settings", settings_path,
            "--no-session-persistence"]
    if tools:
        argv += ["--permission-mode", "dontAsk"]
    if effort:
        argv += ["--effort", effort]
    if budget_usd is not None:
        argv += ["--max-budget-usd", "%g" % budget_usd]
    check_argv(argv)
    return argv


def check_argv(argv):
    for f in FORBIDDEN_FLAGS:
        if f in argv:
            raise ValueError("forbidden flag %s (FR-F9)" % f)
    if "--setting-sources" not in argv or "--settings" not in argv:
        raise ValueError("every engine session fixes its settings sources (§1.4)")
    if "--model" not in argv:
        raise ValueError("always pass --model (§1.4)")


def claude_binary(env=None):
    env = os.environ if env is None else env
    return env.get("GLD_ENGINE_CLAUDE") or shutil.which("claude", path=env.get("PATH")) or "claude"


# ---- processes --------------------------------------------------------------------------------

def process_start(pid):
    """The kernel's start time of `pid` as `ps -o lstart=` prints it, or None."""
    try:
        p = subprocess.run(["ps", "-o", "lstart=", "-p", str(int(pid))], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    s = p.stdout.decode("utf-8", "replace").strip()
    return s or None


def process_cmdline(pid):
    try:
        p = subprocess.run(["ps", "-o", "command=", "-p", str(int(pid))], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    return p.stdout.decode("utf-8", "replace").strip()


def safe_kill_group(rec, grace_s=KILL_GRACE_S, sleep=time.sleep):
    """Kill a journaled group {pid, pgid, start_time, session_id?} only if pid is alive, its start
    time equals the journaled one and (when a session id was journaled) its cmdline carries it.
    Returns 'killed' | 'gone' | 'mismatch'."""
    pid, pgid = rec.get("pid"), rec.get("pgid")
    if not pid or not pgid:
        return "gone"
    st = process_start(pid)
    if st is None:
        # the leader is gone but members may live on (K1-B5): a pgid cannot be reused while any
        # member is alive, so a live group with this id is still ours
        try:
            os.killpg(int(pgid), 0)
        except OSError:
            return "gone"
        return _kill_group(int(pgid), grace_s, sleep)
    if rec.get("start_time") and st != rec["start_time"]:
        return "mismatch"
    sid = rec.get("session_id")
    if sid and sid not in process_cmdline(pid):
        return "mismatch"
    return _kill_group(int(pgid), grace_s, sleep)


def _kill_group(pgid, grace_s=KILL_GRACE_S, sleep=time.sleep):
    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        return "gone"
    deadline = time.time() + grace_s
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except OSError:
            return "killed"
        sleep(0.2)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass
    for _ in range(50):                      # wait until the group is really gone
        try:
            os.killpg(pgid, 0)
        except OSError:
            break
        sleep(0.1)
    return "killed"


def reap_group(pgid, grace_s=2, sleep=time.sleep):
    """After a session ends: kill whatever is left in its process group (backgrounded children,
    `&` jobs) and wait — the post-role checks run only after this (K1-B5)."""
    try:
        os.killpg(int(pgid), 0)
    except OSError:
        return "gone"
    return _kill_group(int(pgid), grace_s, sleep)


class ProcResult(object):
    def __init__(self, rc, timed_out, pid, pgid, start_time, duration_s, killed_by=None):
        self.rc = rc
        self.timed_out = timed_out
        self.pid = pid
        self.pgid = pgid
        self.start_time = start_time
        self.duration_s = duration_s
        self.killed_by = killed_by


def run_process(argv, env, cwd, stdin_text, stdout_path, stderr_path, timeout_s, on_start=None,
                halt_check=None, poll_s=0.5):
    """Run one child in its own process group; stdout → stdout_path (stream-json), stderr → side
    file. `on_start({pid,pgid,start_time})` journals the group before we wait (§2.7). On
    timeout or `halt_check()` truthy the group is killed (TERM → 10 s → KILL)."""
    t0 = time.time()
    with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
        p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=out, stderr=err,
                             start_new_session=True)
        pgid = os.getpgid(p.pid)
        st = process_start(p.pid)
        if on_start:
            on_start({"pid": p.pid, "pgid": pgid, "start_time": st})
        try:
            p.stdin.write((stdin_text or "").encode("utf-8"))
            p.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        timed_out, killed_by = False, None
        while True:
            try:
                rc = p.wait(timeout=poll_s)
                break
            except subprocess.TimeoutExpired:
                pass
            if timeout_s and time.time() - t0 > timeout_s:
                timed_out, killed_by = True, "timeout"
            elif halt_check and halt_check():
                killed_by = "halt"
            if killed_by:
                safe_kill_group({"pid": p.pid, "pgid": pgid, "start_time": st})
                rc = p.wait()
                break
    reaped = reap_group(pgid)
    res = ProcResult(rc, timed_out, p.pid, pgid, st, time.time() - t0, killed_by)
    res.reaped = reaped
    return res


# ---- stream-json --------------------------------------------------------------------------------

class Stream(object):
    """What the engine reads from one session's stream-json (or json) output."""

    def __init__(self):
        self.init = None
        self.session_id = None
        self.assistant_texts = []         # every assistant text block, in order
        self.tool_uses = []               # [{id, name, input}]
        self.tool_results = {}            # id → {is_error, content}
        self.denials = []                 # system/permission_denied events
        self.decisions = {}               # tool_use_id → tool_result_meta.permission_decision
        self.usages = []                  # per assistant message usage (cost of a dead session)
        self.rate_limit_events = []       # [{status, resetsAt, …}]
        self.result = None                # the final `result` event
        self.torn = 0
        self.events = 0

    @property
    def last_text(self):
        if self.result and isinstance(self.result.get("result"), str):
            return self.result["result"]
        return self.assistant_texts[-1] if self.assistant_texts else ""

    @property
    def structured(self):
        return (self.result or {}).get("structured_output")

    def denial_records(self):
        """[{tool_use_id, tool, command, reason_type, message}] — the stream event when present,
        else the result's `permission_denials` list."""
        out, seen = [], set()
        by_id = dict((t["id"], t) for t in self.tool_uses)
        for d in self.denials:
            tu = by_id.get(d.get("tool_use_id")) or {}
            out.append({"tool_use_id": d.get("tool_use_id"), "tool": d.get("tool_name"),
                        "command": (tu.get("input") or {}).get("command"),
                        "reason_type": d.get("decision_reason_type"), "message": d.get("message")})
            seen.add(d.get("tool_use_id"))
        for d in (self.result or {}).get("permission_denials") or []:
            if d.get("tool_use_id") in seen:
                continue
            out.append({"tool_use_id": d.get("tool_use_id"), "tool": d.get("tool_name"),
                        "command": (d.get("tool_input") or {}).get("command"),
                        "reason_type": None, "message": None})
        return out


def parse_stream(text):
    s = Stream()
    seen_msgs, out_chars = {}, {}
    for ln in (text or "").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            s.torn += 1
            continue
        if not isinstance(e, dict):
            continue
        s.events += 1
        t = e.get("type")
        if e.get("session_id") and not s.session_id:
            s.session_id = e["session_id"]
        if t == "system" and e.get("subtype") == "init":
            s.init = e
        elif t == "system" and e.get("subtype") == "permission_denied":
            s.denials.append(e)
        elif t == "assistant":
            u = (e.get("message") or {}).get("usage")
            mid = (e.get("message") or {}).get("id")
            if isinstance(u, dict):
                # stream-json re-sends a message per content block with the message_start usage
                # (output ≈ 0 — the final count is in a message_delta stream-json never shows,
                # verified on a real stream, K1r2-M6): keep the LAST usage per id and estimate
                # output from the content actually produced (≈ 3.5 chars/token)
                key = mid if mid is not None else "_%d" % len(seen_msgs)
                chars = out_chars.get(key, 0) + sum(
                    len(c.get("text") or "") + (len(json.dumps(c.get("input") or {}))
                                                if c.get("type") == "tool_use" else 0)
                    for c in (e.get("message") or {}).get("content") or [])
                out_chars[key] = chars
                u2 = dict(u)
                u2["output_tokens"] = max(int(u.get("output_tokens") or 0), int(chars / 3.5))
                seen_msgs[key] = u2
                s.usages = list(seen_msgs.values())
            for c in (e.get("message") or {}).get("content") or []:
                if c.get("type") == "text":
                    s.assistant_texts.append(c.get("text") or "")
                elif c.get("type") == "tool_use":
                    s.tool_uses.append({"id": c.get("id"), "name": c.get("name"),
                                        "input": c.get("input") or {}})
        elif t == "user":
            content = (e.get("message") or {}).get("content")
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    s.tool_results[c.get("tool_use_id")] = {"is_error": bool(c.get("is_error")),
                                                            "content": c.get("content")}
            for m in e.get("tool_result_meta") or []:
                if isinstance(m, dict) and m.get("permission_decision"):
                    s.decisions[m.get("id")] = m["permission_decision"]
        elif t == "rate_limit_event":
            s.rate_limit_events.append(e.get("rate_limit_info") or {})
        elif t == "result":
            s.result = e
            if e.get("session_id"):
                s.session_id = e["session_id"]
    return s


def read_stream(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return parse_stream(fh.read())
    except (IOError, OSError):
        return parse_stream("")


def _etime_s(text):
    """`ps -o etime=` ([[dd-]hh:]mm:ss) → seconds."""
    t = (text or "").strip()
    days = 0
    if "-" in t:
        d, t = t.split("-", 1)
        days = int(d)
    parts = [int(x) for x in t.split(":") if x.isdigit()]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3:]
    return days * 86400 + h * 3600 + m * 60 + s


def stray_pids(roots, since_s, exclude=()):
    """Processes of this user whose cwd is inside `roots` and that started within the last
    `since_s` seconds — a role's backgrounded children after the CLI's Bash tool detached them
    from our process group (real CLI: `(sleep 8; echo late > f) &` survived the group kill).
    The Bash tool runs commands from the worktree, so their cwd gives them away."""
    try:
        p = subprocess.run(["lsof", "-nP", "-a", "-d", "cwd", "-u", str(os.getuid()), "-Fpn"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    roots = [os.path.realpath(r).rstrip("/") + "/" for r in roots if r]
    out, pid = [], None
    for ln in p.stdout.decode("utf-8", "replace").splitlines():
        if ln.startswith("p"):
            pid = int(ln[1:])
        elif ln.startswith("n") and pid:
            cwd = os.path.realpath(ln[1:]).rstrip("/") + "/"
            if pid not in exclude and pid != os.getpid() and any(cwd.startswith(r) for r in roots):
                out.append(pid)
    young = []
    for pid in out:
        try:
            e = subprocess.run(["ps", "-o", "ppid=,etime=", "-p", str(pid)], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=10).stdout.decode().split()
        except (OSError, subprocess.SubprocessError):
            continue
        # only ORPHANS (reparented to launchd/init): a live peer role's children in a parallel
        # group still have their shell as parent and are never touched
        if len(e) == 2 and e[0] == "1" and _etime_s(e[1]) <= since_s + 2:
            young.append(pid)
    return young


def reap_strays(roots, since_s, sleep=time.sleep, rounds=6):
    """Kill the stray processes (TERM, then KILL), then LOOK AGAIN until a pass finds none —
    killing an outer subshell orphans its inner job, which only then has ppid 1 (K1r2-B3).
    Returns every pid killed. Strays that left the roots (`cd /`) are not found here; the
    between-roles drift check catches what they write."""
    found = []
    for _ in range(rounds):
        pids = [p for p in stray_pids(roots, since_s + 5 * len(found), exclude=(os.getppid(),))
                if p not in found]
        if not pids:
            break
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid in pids:
                try:
                    os.kill(pid, sig)
                except OSError:
                    pass
            if sig == signal.SIGTERM:
                sleep(0.5)
        found += pids
        sleep(0.3)
    return found
