#!/usr/bin/env python3
"""replay.smoke — the K1 local CLI smoke (§10.2-3b), run by the K1 executor ITSELF.

    smoke.py --work DIR --repo SRC --out EVIDENCE_DIR [--items 1,1b,3,4,5,6,7,8] [--model-items]

Every item runs `claude -p` (CLI 2.1.311) through `guildcore.roles.runner` /
`guildcore.judges.runner` / `guildcore.adapters.claude` with the SAME rendered settings and source
arguments as production, against a loopback endpoint only:
  * scripted endpoint (`replay.proxy` script mode) — deterministic tool calls, seconds per call;
  * the local Ollama model (`--model-items`, proxy forward mode) — the model-driven checks
    (1-qwen, 6(i), 7-qwen). `--allow-local-endpoint` semantics: the runner is built with
    `allow_local=True`; without it the endpoint guard halts (asserted in 1b-iii).
No item can reach a real Anthropic endpoint: the child env is `env -i`-built with HTTPS_PROXY to a
dead port, the base URL is the loopback proxy, and the config dir is an isolated scratch dir.
Evidence per item: `<out>/<item>/` — argv, stream-json (also parser fixtures), proxy request log,
`result.json` with the assertions and their outcome.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from guildcore import emit                                   # noqa: E402
from guildcore import ratelimit as RL                        # noqa: E402
from guildcore.adapters import claude as C                   # noqa: E402
from guildcore.judges import runner as JR                    # noqa: E402
from guildcore.roles import runner as RR                     # noqa: E402
from guildcore.roles import settings as S                    # noqa: E402
from workflows.dev.replay import calibrate as CA             # noqa: E402
from workflows.dev.replay import proxy as PX                 # noqa: E402

OLLAMA = "http://127.0.0.1:11434"
QWEN = "qwen3.8:27b"
SCRIPT_MODEL = "claude-sonnet-4-5"


class Ctx(object):
    def __init__(self, work, repo, out):
        self.env_dirs = CA.prepare(work, repo)
        self.clone = self.env_dirs["clone"]
        self.out = out
        self.work = work
        os.makedirs(out, exist_ok=True)
        self.user_settings = os.path.join(self.env_dirs["cfg"], "settings.json")

    def parent_env(self, endpoint, shims=False, extra=None):
        e = CA.base_env(self.env_dirs, endpoint)
        if not shims:
            e["PATH"] = os.pathsep.join(["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/opt/homebrew/bin"])
        e.update(extra or {})
        return e


def _dir(ctx, item):
    d = os.path.join(ctx.out, item)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    return d


def _save(d, name, obj):
    with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
        if isinstance(obj, str):
            fh.write(obj)
        else:
            json.dump(obj, fh, ensure_ascii=False, indent=1, default=str)


def _rr(ctx, d, name):
    """Run roots live in the scratch work dir; `_collect` copies the evidence out afterwards."""
    return os.path.join(ctx.work, "smoke-runs", os.path.relpath(d, ctx.out), name)


def _collect(ctx, item_dir):
    """Copy streams, rendered settings, task.md and result.json of an item's runs (never the
    exported gate scripts) into the evidence dir."""
    src = os.path.join(ctx.work, "smoke-runs", item_dir)
    dst = os.path.join(ctx.out, item_dir, "runs")
    n = 0
    for base, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x != "gates"]
        for f in files:
            if f.endswith((".jsonl", ".stderr", "settings.json", "task.md", "result.json", "evidence.md")):
                rel = os.path.relpath(os.path.join(base, f), src)
                os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
                shutil.copyfile(os.path.join(base, f), os.path.join(dst, rel))
                n += 1
    return n


def _collect_streams(run_root, d):
    """Copy every session stream under a run root into the evidence dir (parser fixtures)."""
    n = 0
    for base, _dirs, files in os.walk(run_root):
        for f in files:
            if f.endswith(".stream.jsonl") or f.endswith(".json") and "/out/" in base + "/":
                src = os.path.join(base, f)
                rel = os.path.relpath(src, run_root).replace(os.sep, "__")
                shutil.copyfile(src, os.path.join(d, "stream__" + rel))
                n += 1
    return n


def _runner(ctx, endpoint_url, run_root, allow_local=True, shims=False, journal=None,
            extra_env=None, user_settings=None):
    return RR.Runner(journal=journal, common_dir=None,
                     parent_env=ctx.parent_env(endpoint_url, shims, extra_env),
                     allow_local=allow_local, user_settings=user_settings or ctx.user_settings,
                     run_root_dir=run_root)


def _spec(ctx, role, task, template, model=SCRIPT_MODEL, **kw):
    kw.setdefault("issue", 1)
    kw.setdefault("stage", "smoke")
    kw.setdefault("step", "K1")
    return RR.RoleSpec(role, task, template, worktree=ctx.clone, model=model,
                       base=kw.pop("base", "HEAD"), **kw)


def _script_proxy(d, turns, **kw):
    return PX.serve_background(logdir=os.path.join(d, "proxy"), mode="script",
                               script={"turns": turns, "usage": kw.pop("usage", None)}, **kw)


def _requests(d):
    p = os.path.join(d, "proxy", "requests.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def _result_dict(rr):
    return {"status": rr.status, "line": rr.line, "extras": rr.extras, "notes": rr.notes,
            "denials": rr.denials, "violations": rr.violations, "session_id": rr.session_id,
            "cost": rr.cost, "rl": rr.rl.status if rr.rl else None}


# ---- item 1: executor plumbing --------------------------------------------------------------------

def item1(ctx):
    d = _dir(ctx, "1-plumbing")
    res = {}
    CA.reset_clone(ctx.clone)
    # 1a — result-file contract through --add-dir + Read/Write(//abs) rules
    root = _rr(ctx, d, "runs-1a")
    run = os.path.join(root, "001-smoke-explorer")
    turns = [{"tool_use": {"name": "Read", "input": {"file_path": run + "/in/brief.md"}}},
             {"tool_use": {"name": "Write", "input": {"file_path": run + "/out/evidence.md",
                                                       "content": "# evidence\n- pubspec.yaml:1\n"}}},
             {"tool_use": {"name": "Write", "input": {"file_path": run + "/out/result.json",
                                                       "content": json.dumps({"evidence_path": run + "/out/evidence.md"})}}},
             {"text": "done\n>>> RESULT <<<\nDONE: evidence at out/evidence.md"}]
    srv, url = _script_proxy(d, turns)
    try:
        sid = None
        rr = _runner(ctx, url, root).run_role(_spec(
            ctx, "explorer", None, "Read in/brief.md and write evidence.", who="explorer",
            inputs={"brief.md": {"text": "find the app name"}},
            result_schema=RR.R.RESULT_SCHEMAS["explorer"], scope_check=True))
    finally:
        srv.shutdown()
    st = C.read_stream(os.path.join(run, "s1.stream.jsonl"))
    reqs = _requests(d)
    res["1a_result_file"] = {
        "status": rr.status, "extras": rr.extras,
        "decisions": st.decisions,
        "pass": rr.status == "DONE" and rr.extras.get("evidence_path", "").endswith("evidence.md")
        and all(v.get("decision") == "accept" for v in st.decisions.values()),
        "session_header_matches": bool(reqs) and reqs[0]["headers"].get("x-claude-code-session-id") == rr.session_id}
    # 1b — fence fallback (no result.json file)
    root = _rr(ctx, d, "runs-1b")
    turns = [{"text": "```guild-result\n{\"evidence_path\": \"pubspec.yaml\"}\n```\n>>> RESULT <<<\nDONE: inline"}]
    srv, url = _script_proxy(os.path.join(d, "fence"), turns)
    try:
        rr = _runner(ctx, url, root).run_role(_spec(
            ctx, "explorer", None, "x", who="explorer", result_schema=RR.R.RESULT_SCHEMAS["explorer"]))
    finally:
        srv.shutdown()
    res["1b_fence_fallback"] = {"status": rr.status, "extras": rr.extras,
                                "pass": rr.status == "DONE" and rr.extras == {"evidence_path": "pubspec.yaml"}}
    # 1c — --resume repair of a missing RESULT line (same session)
    root = _rr(ctx, d, "runs-1c")
    turns = [{"text": "I finished the review."}, {"text": ">>> RESULT <<<\nDONE: reviewed"}]
    srv, url = _script_proxy(os.path.join(d, "repair"), turns)
    try:
        rr = _runner(ctx, url, root).run_role(_spec(ctx, "reviewer", None, "review", who="reviewer"))
    finally:
        srv.shutdown()
    reqs = _requests(os.path.join(d, "repair"))
    sids = [r["headers"].get("x-claude-code-session-id") for r in reqs if not r.get("side")]
    res["1c_resume_repair"] = {"status": rr.status, "notes": rr.notes, "session_ids_seen": sids,
                               "pass": rr.status == "DONE" and "repair-resume" in rr.notes
                               and len(set(sids)) == 1}
    # 1d — permission denial → one --resume with the brief → DONE
    root = _rr(ctx, d, "runs-1d")
    turns = [{"tool_use": {"name": "Bash", "input": {"command": "git push origin HEAD", "description": "push"}}},
             {"text": ">>> RESULT <<<\nBLOCKED: permission — git push origin HEAD"},
             {"text": ">>> RESULT <<<\nDONE: left the push to the engine"}]
    srv, url = _script_proxy(os.path.join(d, "permission"), turns)
    try:
        rr = _runner(ctx, url, root).run_role(_spec(ctx, "developer", "implement", "x", scope_check=False))
    finally:
        srv.shutdown()
    reqs = _requests(os.path.join(d, "permission"))
    brief_seen = any("refused by the permission rules" in json.dumps(r.get("body")) for r in reqs)
    res["1d_permission_resume"] = {"status": rr.status, "denials": rr.denials, "notes": rr.notes,
                                   "brief_sent": brief_seen,
                                   "pass": rr.status == "DONE" and rr.denials and
                                   rr.denials[0]["class"] == "forbidden" and brief_seen}
    # 1e — timeout → process-group kill
    root = _rr(ctx, d, "runs-1e")
    turns = [{"tool_use": {"name": "Bash", "input": {"command": "sleep 300", "description": "long",
                                                     "timeout": 400000}}},
             {"text": ">>> RESULT <<<\nDONE: slept"}]
    srv, url = _script_proxy(os.path.join(d, "timeout"), turns)
    pids = []

    class J(object):
        def record_pid(self, who, pid, pgid, st, session_id=None):
            pids.append((pid, pgid, st))

        def record_denial(self, *a, **k):
            pass
    try:
        r = _runner(ctx, url, root, journal=J())
        t0 = time.time()
        rr = r.run_role(_spec(ctx, "developer", "implement", "x", timeout_s=20, scope_check=False))
        took = time.time() - t0
    finally:
        srv.shutdown()
    alive = []
    for _pid, pgid, _st in pids:
        try:
            os.killpg(pgid, 0)
            alive.append(pgid)
        except OSError:
            pass
    leftover = subprocess.run(["pgrep", "-f", "sleep 300"], stdout=subprocess.PIPE).stdout.decode().split()
    res["1e_timeout_pgid_kill"] = {"status": rr.status, "secs": round(took, 1), "pgids": [p[1] for p in pids],
                                   "groups_alive_after": alive, "sleep_300_left": leftover,
                                   "pass": rr.status == "TIMEOUT" and not alive and not leftover}
    # 1f — --agent <name> under --setting-sources "" (FR-F9 evaluation)
    agents = os.path.join(ctx.clone, ".claude", "agents")
    os.makedirs(agents, exist_ok=True)
    with open(os.path.join(agents, "k1probe.md"), "w") as fh:
        fh.write("---\nname: k1probe\ndescription: K1 smoke probe agent\n---\nK1-AGENT-MARKER-7731\n")
    root = _rr(ctx, d, "runs-1f")
    srv, url = _script_proxy(os.path.join(d, "agent"), [{"text": ">>> RESULT <<<\nDONE: agent"}])
    try:
        rr = _runner(ctx, url, root).run_role(_spec(ctx, "reviewer", None, "x", who="reviewer",
                                                    agent="k1probe", scope_check=False))
    finally:
        srv.shutdown()
    reqs = _requests(os.path.join(d, "agent"))
    seen = any("K1-AGENT-MARKER-7731" in json.dumps(r.get("body")) for r in reqs)
    errs = open(os.path.join(rr.run_dir, "s1.stream.jsonl.stderr"), errors="replace").read()[:500] if rr.run_dir else ""
    res["1f_agent_flag"] = {"status": rr.status, "agent_body_in_request": seen, "stderr": errs,
                            "pass": None, "note": "evaluation only (FR-F9): records whether a project "
                            "agent loads with --setting-sources \"\""}
    CA.reset_clone(ctx.clone)
    # exit codes seen
    res["exit_codes"] = "every session rc recorded in the stream stderr files; runner maps rc/timeout/halt"
    _save(d, "result.json", res)
    return res


# ---- item 1b: settings sources -------------------------------------------------------------------

def item1b(ctx):
    d = _dir(ctx, "1b-settings-sources")
    res = {}
    CA.reset_clone(ctx.clone)
    home = ctx.env_dirs["home"]
    os.makedirs(os.path.join(home, ".ssh"), exist_ok=True)
    with open(os.path.join(home, ".ssh", "id_rsa"), "w") as fh:
        fh.write("not a key\n")
    turns = [{"tool_use": {"name": "Bash", "input": {"command": "cat ~/.ssh/id_rsa", "description": "i"}}},
             {"tool_use": {"name": "Bash", "input": {"command": "curl --version", "description": "i-allow-not-carried"}}},
             {"tool_use": {"name": "Bash", "input": {"command": "python3 -c \"import os; print('t=%s e=%s' % (os.environ.get('DISABLE_TELEMETRY'), os.environ.get('CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC')))\"",
                                                     "description": "ii"}}},
             {"text": ">>> RESULT <<<\nDONE: x"}]
    srv, url = _script_proxy(d, turns)
    root = _rr(ctx, d, "runs")
    try:
        rr = _runner(ctx, url, root).run_role(_spec(ctx, "developer", "implement", "x", scope_check=False))
    finally:
        srv.shutdown()
    st = C.read_stream(os.path.join(rr.run_dir, "s1.stream.jsonl"))
    by_desc = {}
    for t in st.tool_uses:
        by_desc[(t["input"] or {}).get("description")] = t
    dec = lambda k: (st.decisions.get(by_desc[k]["id"]) or {}).get("decision") if k in by_desc else None
    out_ii = json.dumps((st.tool_results.get(by_desc.get("ii", {}).get("id")) or {}).get("content"))
    res["i_user_deny_carried"] = {"decision": dec("i"), "denials": rr.denials,
                                  "pass": any(x["command"] == "cat ~/.ssh/id_rsa" for x in rr.denials)}
    res["i_user_allow_not_carried"] = {"note": "user settings allow Bash(*) — must NOT apply",
                                       "pass": any(x["command"] == "curl --version" for x in rr.denials)}
    res["ii_settings_env_in_child"] = {"output": out_ii, "pass": "t=1" in out_ii and "e=1" in out_ii}
    # iii — routing key in settings env → endpoint guard
    bad = os.path.join(d, "user-settings-routing.json")
    us = json.load(open(ctx.user_settings))
    us = dict(us, env=dict(us.get("env") or {}, ANTHROPIC_BASE_URL="http://10.0.0.1:9999"))
    _save(d, "user-settings-routing.json", us)
    try:
        _runner(ctx, "https://api.anthropic.com", _rr(ctx, d, "runs-iii"), allow_local=False,
                user_settings=bad).run_role(_spec(ctx, "reviewer", None, "x", scope_check=False))
        halted = None
    except C.EnvHalt as e:
        halted = str(e)
    res["iii_routing_in_settings_env_halts"] = {"halt": halted, "pass": bool(halted) and "endpoint" in halted}
    # iv — sandbox block carried: enabled + allowWrite → write succeeds; without → fails
    # outside $TMPDIR (the sandbox lets every process write there): the evidence dir itself
    pc = os.path.join(d, "pubcache")
    os.makedirs(pc, exist_ok=True)
    outcome = {}
    for name, sb in (("with_allowWrite", {"enabled": True, "filesystem": {"allowWrite": [pc + "/**"]}}),
                     ("without_allowWrite", {"enabled": True})):
        target = os.path.join(pc, "w-%s.txt" % name)
        if os.path.exists(target):
            os.unlink(target)
        usp = os.path.join(d, "user-settings-%s.json" % name)
        u2 = json.load(open(ctx.user_settings))
        u2["sandbox"] = sb
        _save(d, "user-settings-%s.json" % name, u2)
        turns = [{"tool_use": {"name": "Bash", "input": {
            "command": "python3 -c \"open('%s','w').write('1')\"" % target, "description": "w"}}},
            {"text": ">>> RESULT <<<\nDONE: x"}]
        srv, url = _script_proxy(os.path.join(d, "sandbox-" + name), turns)
        try:
            rr = _runner(ctx, url, _rr(ctx, d, "runs-iv-" + name), user_settings=usp).run_role(
                _spec(ctx, "developer", "implement", "x", scope_check=False))
        finally:
            srv.shutdown()
        rendered = json.load(open(os.path.join(rr.run_dir, "in", "settings.json")))
        st = C.read_stream(os.path.join(rr.run_dir, "s1.stream.jsonl"))
        outcome[name] = {"written": os.path.exists(target), "rendered_sandbox": rendered.get("sandbox"),
                         "tool_result": json.dumps(list(st.tool_results.values()))[:400],
                         "decisions": st.decisions}
    res["iv_sandbox_carried"] = dict(outcome, pass_=outcome["with_allowWrite"]["written"]
                                     and not outcome["without_allowWrite"]["written"])
    # v — hooks from the base snapshot; a branch-changed hook does not fire; user hooks not loaded
    CA.reset_clone(ctx.clone)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ctx.clone, stdout=subprocess.PIPE).stdout.decode().strip()
    marker = os.path.join(d, "branch-hook-fired.txt")
    sp = os.path.join(ctx.clone, ".claude", "settings.json")
    cur = json.load(open(sp))
    cur.setdefault("hooks", {}).setdefault("PreToolUse", []).append(
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo fired >> %s" % marker}]})
    json.dump(cur, open(sp, "w"), indent=2)
    subprocess.run(["git", "commit", "-qam", "k1: branch hook"], cwd=ctx.clone, check=True)
    user_hook = os.path.join(ctx.work, "user-hook-fired.txt")
    if os.path.exists(user_hook):
        os.unlink(user_hook)
    turns = [{"tool_use": {"name": "Bash", "input": {"command": "git status --short", "description": "v"}}},
             {"text": ">>> RESULT <<<\nDONE: x"}]
    srv, url = _script_proxy(os.path.join(d, "hooks"), turns)
    try:
        rr = _runner(ctx, url, _rr(ctx, d, "runs-v")).run_role(
            _spec(ctx, "developer", "implement", "x", base=base, scope_check=False))
    finally:
        srv.shutdown()
    rendered = json.load(open(os.path.join(rr.run_dir, "in", "settings.json")))
    hooks_txt = json.dumps(rendered.get("hooks"))
    res["v_hooks_from_base"] = {
        "branch_hook_fired": os.path.exists(marker), "user_stop_hook_fired": os.path.exists(user_hook),
        "rendered_hook_commands": hooks_txt[:600],
        "gates_exported": os.path.isdir(os.path.join(rr.run_dir, "in", "gates", "scripts")),
        "pass": not os.path.exists(marker) and not os.path.exists(user_hook)
        and os.path.join(rr.run_dir, "in", "gates") in hooks_txt and "CLAUDE_PROJECT_DIR}/.claude/guild/gates" not in hooks_txt}
    subprocess.run(["git", "reset", "-q", "--hard", base], cwd=ctx.clone)
    CA.reset_clone(ctx.clone)
    _save(d, "result.json", res)
    return res


# ---- item 3: gate hooks through the rendered settings ---------------------------------------------

def item3(ctx):
    d = _dir(ctx, "3-gate-hooks")
    CA.reset_clone(ctx.clone)
    tests = subprocess.run(["git", "ls-files", "test/*_test.dart", "test/**/*_test.dart"], cwd=ctx.clone,
                           stdout=subprocess.PIPE).stdout.decode().split()
    victim = tests[0]
    turns = [{"tool_use": {"name": "Bash", "input": {"command": "git rm -q %s" % victim, "description": "rm"}}},
             {"tool_use": {"name": "Bash", "input": {"command": "git commit -m 'drop a test'", "description": "commit"}}},
             {"tool_use": {"name": "Read", "input": {"file_path": os.path.join(ctx.clone, ".claude", "settings.json")}}},
             {"tool_use": {"name": "Edit", "input": {"file_path": os.path.join(ctx.clone, ".claude", "settings.json"),
                                                     "old_string": "\"timeout\": 30", "new_string": "\"timeout\": 31"}}},
             {"text": ">>> RESULT <<<\nDONE: x"}]
    srv, url = _script_proxy(d, turns)
    head0 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ctx.clone, stdout=subprocess.PIPE).stdout.decode().strip()
    try:
        rr = _runner(ctx, url, _rr(ctx, d, "runs")).run_role(
            _spec(ctx, "developer", "implement", "x", scope_check=False))
    finally:
        srv.shutdown()
    head1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ctx.clone, stdout=subprocess.PIPE).stdout.decode().strip()
    st = C.read_stream(os.path.join(rr.run_dir, "s1.stream.jsonl"))
    rows = []
    for t in st.tool_uses:
        r = st.tool_results.get(t["id"]) or {}
        rows.append({"tool": t["name"], "input": t["input"], "decision": st.decisions.get(t["id"]),
                     "is_error": r.get("is_error"), "result": json.dumps(r.get("content"), ensure_ascii=False)[:500]})
    commit = [r for r in rows if r["tool"] == "Bash" and "commit" in r["input"].get("command", "")]
    edit = [r for r in rows if r["tool"] == "Edit"]
    res = {"rows": rows, "head_unchanged": head0 == head1,
           "inv2_blocked_by_base_gate": bool(commit) and commit[0]["is_error"] and "INV2" in commit[0]["result"],
           "guard_config_on_settings_edit": edit[0] if edit else None,
           "gate_reads_config_from": "worktree (repo_root()/CLAUDE_PROJECT_DIR — gates_enabled, rules), not the "
                                     "exported script's own directory (static read of gate_precommit.py)"}
    res["pass"] = res["inv2_blocked_by_base_gate"] and res["head_unchanged"]
    CA.reset_clone(ctx.clone)
    _save(d, "result.json", res)
    return res


# ---- item 4: TTL request assertion ------------------------------------------------------------------

def _raw_session(ctx, d, tag, turns, env_extra, cache=None, model=SCRIPT_MODEL, judge=False):
    sub = os.path.join(d, tag)
    os.makedirs(sub, exist_ok=True)
    srv, url = PX.serve_background(logdir=os.path.join(sub, "proxy"), mode="script",
                                   script={"turns": turns})
    rendered = S.render("reviewer", None, worktree=ctx.clone, base="HEAD", run_dir=_rr(ctx, sub, "run"),
                        user_settings=ctx.user_settings, hooks=False,
                        env={"CLAUDE_CONFIG_DIR": ctx.env_dirs["cfg"]})
    parent = ctx.parent_env(url)
    env = C.child_env(parent, rendered.env, cache=cache, judge=judge, extra=env_extra)
    argv = C.role_argv(model, None, rendered.settings["permissions"]["allow"],
                       rendered.settings["permissions"]["deny"], _rr(ctx, sub, "run"), rendered.path,
                       session_id=str(uuid.uuid4()), claude=shutil.which("claude"))
    try:
        p = C.run_process(argv, env, ctx.clone, "hello", os.path.join(sub, "stream.jsonl"),
                          os.path.join(sub, "stream.jsonl.stderr"), 300)
    finally:
        srv.shutdown()
    return p, sub, _requests(sub)


def _cache_controls(reqs):
    out = []
    for r in reqs:
        if r.get("side"):
            continue
        s = json.dumps(r.get("body"))
        import re
        out += re.findall(r'"cache_control": (\{[^}]*\})', s)
    return out


def item4(ctx):
    d = _dir(ctx, "4-ttl")
    turns = [{"text": ">>> RESULT <<<\nDONE: x"}]
    res = {}
    for tag, extra, cache in (("control-1h", {"ENABLE_PROMPT_CACHING_1H": "1"}, None),
                              ("1h-plus-force5m", {"ENABLE_PROMPT_CACHING_1H": "1"}, "5m"),
                              ("engine-role-5m", {}, "5m"),
                              ("disable", {}, "off")):
        p, sub, reqs = _raw_session(ctx, d, tag, turns, extra, cache=cache)
        ccs = _cache_controls(reqs)
        res[tag] = {"rc": p.rc, "cache_control": sorted(set(ccs)), "n": len(ccs)}
    res["pass"] = (any('"1h"' in c for c in res["control-1h"]["cache_control"])
                   and not any('"1h"' in c for c in res["1h-plus-force5m"]["cache_control"])
                   and res["disable"]["n"] == 0)
    _save(d, "result.json", res)
    return res


# ---- item 5: rate limit -----------------------------------------------------------------------------

def item5(ctx):
    d = _dir(ctx, "5-ratelimit")
    res = {}
    reset = int(time.time()) + 3600
    for tag, kw in (("headers-rejected", {"ratelimit": ("rejected", reset)}),
                    ("http-429-once", {"ratelimit": ("rejected", reset), "status429": 1}),
                    ("http-429-always", {"ratelimit": ("rejected", reset), "status429": -1})):
        sub = os.path.join(d, tag)
        srv, url = PX.serve_background(logdir=os.path.join(sub, "proxy"), mode="script",
                                       script={"turns": [{"text": ">>> RESULT <<<\nDONE: x"}]}, **kw)
        try:
            rr = _runner(ctx, url, _rr(ctx, sub, "runs")).run_role(
                _spec(ctx, "reviewer", None, "x", scope_check=False, timeout_s=240))
        finally:
            srv.shutdown()
        st = C.read_stream(os.path.join(rr.run_dir, "s1.stream.jsonl"))
        obs = RL.observe(st)
        v = RL.verdict([obs])
        import io
        buf = io.StringIO()
        RL.final_event(v, out=buf)
        res[tag] = {"cli_rate_limit_events": st.rate_limit_events, "result_is_error": (st.result or {}).get("is_error"),
                    "api_error_status": (st.result or {}).get("api_error_status"),
                    "session": obs.as_dict(), "verdict": v.status, "resetsAt": v.resets_at,
                    "engine_final_event": buf.getvalue().strip(), "runner_status": rr.status,
                    "engine_exit": RL.EXIT_RATE_LIMIT if v.rejected() else 0}
    res["note"] = ("CLI reads anthropic-ratelimit-unified-* only on some auth paths; whatever it "
                   "emitted is recorded verbatim; the engine path (observe→verdict→final event→75) "
                   "is exercised on it and pinned by unit fixtures")
    res["pass"] = res["http-429-always"]["verdict"] == "rejected" and res["http-429-always"]["engine_exit"] == 75
    _save(d, "result.json", res)
    return res


# ---- item 6: env guards (scripted control parts) ---------------------------------------------------

def item6_scripted(ctx, which):
    d = _dir(ctx, "6-env-guards-" + which)
    cmd = {"command": "sleep 700 && echo done", "description": "long"}
    if which == "no-timeout":
        turns = [{"tool_use": {"name": "Bash", "input": cmd}}, {"text": ">>> RESULT <<<\nDONE: x"}]
        extra, drop = {}, ()
    else:   # unguarded control: explicit timeout but no PRINT_BG_WAIT_CEILING guard
        turns = [{"tool_use": {"name": "Bash", "input": dict(cmd, timeout=800000)}},
                 {"text": ">>> RESULT <<<\nDONE: x"}]
        extra, drop = {}, ("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS",)
    srv, url = PX.serve_background(logdir=os.path.join(d, "proxy"), mode="script", script={"turns": turns})
    rendered = S.render("developer", "implement", worktree=ctx.clone, base="HEAD", run_dir=_rr(ctx, d, "run"),
                        user_settings=ctx.user_settings, hooks=False,
                        env={"CLAUDE_CONFIG_DIR": ctx.env_dirs["cfg"]})
    env = C.child_env(ctx.parent_env(url), rendered.env, cache="5m", extra=extra)
    for k in drop:
        env.pop(k, None)
    argv = C.role_argv(SCRIPT_MODEL, None, rendered.settings["permissions"]["allow"],
                       rendered.settings["permissions"]["deny"], _rr(ctx, d, "run"), rendered.path,
                       session_id=str(uuid.uuid4()), claude=shutil.which("claude"))
    t0 = time.time()
    try:
        p = C.run_process(argv, env, ctx.clone, "go", os.path.join(d, "stream.jsonl"),
                          os.path.join(d, "stream.jsonl.stderr"), 1500)
    finally:
        srv.shutdown()
    st = C.read_stream(os.path.join(d, "stream.jsonl"))
    r = list(st.tool_results.values())
    res = {"which": which, "rc": p.rc, "secs": round(time.time() - t0, 1),
           "tool_result": json.dumps(r, ensure_ascii=False)[:600], "final_text": st.last_text[:200],
           "result_subtype": (st.result or {}).get("subtype"),
           "env_guard_keys": {k: env.get(k) for k in ("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS",
                                                      "BASH_DEFAULT_TIMEOUT_MS", "BASH_MAX_TIMEOUT_MS",
                                                      "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS")}}
    _save(d, "result.json", res)
    return res


# ---- item 7: tools + schema --------------------------------------------------------------------------

JUDGE_SCHEMA = {"type": "object", "required": ["verdict", "evidence"], "additionalProperties": False,
                "properties": {"verdict": {"type": "string", "enum": ["effective", "vacuous", "unsure"]},
                               "evidence": {"type": "array", "items": {"type": "object",
                                            "required": ["path", "line", "quote"],
                                            "properties": {"path": {"type": "string"},
                                                           "line": {"type": "integer"},
                                                           "quote": {"type": "string"}}}}}}


def item7(ctx, model_driven=False):
    d = _dir(ctx, "7-tools-schema" + ("-qwen" if model_driven else ""))
    if model_driven:
        srv, url = PX.serve_background(logdir=os.path.join(d, "proxy"), mode="forward", upstream=OLLAMA)
        model = QWEN
    else:
        turns = [{"tool_use": {"name": "Read", "input": {"file_path": os.path.join(ctx.clone, "pubspec.yaml")}}},
                 {"tool_use": {"name": "StructuredOutput", "input": {
                     "verdict": "effective", "evidence": [{"path": "pubspec.yaml", "line": 1, "quote": "name"}]}}},
                 {"text": "ok"}]
        srv, url = PX.serve_background(logdir=os.path.join(d, "proxy"), mode="script", script={"turns": turns})
        model = SCRIPT_MODEL
    jr = JR.JudgeRunner(parent_env=ctx.parent_env(url), allow_local=True, run_root_dir=_rr(ctx, d, "runs"),
                        user_settings=ctx.user_settings, claude=shutil.which("claude"))
    spec = JR.JudgeSpec("TEST", model, JUDGE_SCHEMA,
                        ["You judge whether a file exists and is a Flutter pubspec. Use Read on "
                         "pubspec.yaml in the current directory, then answer with the schema."],
                        [("brief", "Read pubspec.yaml (first line) and return verdict=effective with one "
                                   "evidence item {path:'pubspec.yaml', line:1, quote:<a word from line 1>}.")],
                        tools="Read,Grep", cwd=ctx.clone, choice_key="verdict", unsure_default="vacuous",
                        budget_usd=50.0)
    t0 = time.time()
    try:
        dec = jr.judge(spec)
        err = None
    except Exception as e:
        dec, err = None, "%s: %s" % (type(e).__name__, e)
    finally:
        srv.shutdown()
    reqs = _requests(d)
    tools_offered = sorted(set(t.get("name") for r in reqs for t in (r.get("body") or {}).get("tools") or []))
    res = {"model": model, "secs": round(time.time() - t0, 1), "decision": dec.as_dict() if dec else None,
           "error": err, "tools_offered": tools_offered,
           "pass": dec is not None and dec.choice in ("effective", "vacuous") and "Read" in tools_offered}
    _save(d, "result.json", res)
    return res


# ---- item 8: cost / budget -----------------------------------------------------------------------------

def item8(ctx):
    d = _dir(ctx, "8-cost-budget")
    big = {"input_tokens": 400000, "output_tokens": 20000, "cache_creation_input_tokens": 0,
           "cache_read_input_tokens": 0}
    turns = [{"tool_use": {"name": "Bash", "input": {"command": "ls", "description": "1"}}},
             {"tool_use": {"name": "Bash", "input": {"command": "ls", "description": "2"}}},
             {"tool_use": {"name": "Bash", "input": {"command": "ls", "description": "3"}}},
             {"text": ">>> RESULT <<<\nDONE: x"}]
    res = {}
    for tag, budget in (("no-cap", 100.0), ("cap-1usd", 1.0)):
        sub = os.path.join(d, tag)
        srv, url = PX.serve_background(logdir=os.path.join(sub, "proxy"), mode="script",
                                       script={"turns": turns, "usage": big})
        try:
            rr = _runner(ctx, url, _rr(ctx, sub, "runs")).run_role(
                _spec(ctx, "developer", "implement", "x", budget_usd=budget, scope_check=False))
        finally:
            srv.shutdown()
        st = C.read_stream(os.path.join(rr.run_dir, "s1.stream.jsonl"))
        res[tag] = {"total_cost_usd": (st.result or {}).get("total_cost_usd"),
                    "subtype": (st.result or {}).get("subtype"), "num_turns": (st.result or {}).get("num_turns"),
                    "model_usage": (st.result or {}).get("modelUsage"), "runner_status": rr.status,
                    "runner_cost": rr.cost}
    res["pass"] = bool(res["no-cap"]["total_cost_usd"]) and (
        res["cap-1usd"]["num_turns"] or 99) < (res["no-cap"]["num_turns"] or 0)
    _save(d, "result.json", res)
    return res


# ---- model-driven items (local Ollama) ----------------------------------------------------------------

def item1_qwen(ctx):
    d = _dir(ctx, "1-plumbing-qwen")
    CA.reset_clone(ctx.clone)
    srv, url = PX.serve_background(logdir=os.path.join(d, "proxy"), mode="forward", upstream=OLLAMA)
    root = _rr(ctx, d, "runs")
    t0 = time.time()
    try:
        rr = _runner(ctx, url, root).run_role(_spec(
            ctx, "explorer", None,
            "Task: read the brief file given below, then look at pubspec.yaml in the current "
            "directory with the Read tool. Write a short markdown note to out/evidence.md under your "
            "run directory saying what the app's `name:` is, then write out/result.json there as "
            "{\"evidence_path\": \"<absolute path of evidence.md>\"}.",
            model=QWEN, who="explorer", inputs={"brief.md": {"text": "Find the Flutter app name."}},
            result_schema=RR.R.RESULT_SCHEMAS["explorer"], timeout_s=1500, budget_usd=100.0))
    finally:
        srv.shutdown()
    res = dict(_result_dict(rr), secs=round(time.time() - t0, 1),
               pass_=rr.status in ("DONE", "DONE_WITH_CONCERNS"))
    _save(d, "result.json", res)
    return res


def item6_qwen(ctx):
    d = _dir(ctx, "6-env-guards-qwen")
    CA.reset_clone(ctx.clone)
    srv, url = PX.serve_background(logdir=os.path.join(d, "proxy"), mode="forward", upstream=OLLAMA)
    root = _rr(ctx, d, "runs")
    t0 = time.time()
    try:
        rr = _runner(ctx, url, root).run_role(_spec(
            ctx, "developer", "implement",
            "Run exactly this one shell command with the Bash tool and set the Bash tool's `timeout` "
            "parameter to 800000 (milliseconds): `sleep 700 && echo done`. Wait for it to finish. Do "
            "not run it in the background. Then report whether it printed done.",
            model=QWEN, timeout_s=2400, budget_usd=100.0, scope_check=False))
    finally:
        srv.shutdown()
    st = C.read_stream(os.path.join(rr.run_dir, "s1.stream.jsonl"))
    bash = [t for t in st.tool_uses if t["name"] == "Bash"]
    outs = [json.dumps(st.tool_results.get(t["id"]), ensure_ascii=False)[:300] for t in bash]
    res = dict(_result_dict(rr), secs=round(time.time() - t0, 1),
               bash_inputs=[t["input"] for t in bash], bash_results=outs,
               timeout_asserted=any((t["input"] or {}).get("timeout") == 800000 for t in bash),
               printed_done=any("done" in o for o in outs))
    res["pass"] = res["timeout_asserted"] and res["printed_done"] and rr.status.startswith("DONE")
    _save(d, "result.json", res)
    return res


ITEMS = {"1": item1, "1b": item1b, "3": item3, "4": item4, "5": item5, "8": item8,
         "7": lambda c: item7(c, False),
         "6-no-timeout": lambda c: item6_scripted(c, "no-timeout"),
         "6-unguarded": lambda c: item6_scripted(c, "unguarded"),
         "1-qwen": item1_qwen, "6-qwen": item6_qwen, "7-qwen": lambda c: item7(c, True)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--items", default="1,1b,3,4,5,7,8")
    a = ap.parse_args(argv)
    ctx = Ctx(a.work, a.repo, a.out)
    summary = {}
    for it in a.items.split(","):
        t0 = time.time()
        try:
            r = ITEMS[it](ctx)
            summary[it] = {"pass": r.get("pass", r.get("pass_")), "secs": round(time.time() - t0, 1)}
        except Exception as e:
            import traceback
            summary[it] = {"error": "%s: %s" % (type(e).__name__, e), "trace": traceback.format_exc()[-1500:]}
        for item_dir in os.listdir(os.path.join(a.work, "smoke-runs")) if os.path.isdir(os.path.join(a.work, "smoke-runs")) else []:
            _collect(ctx, item_dir)
        sys.stdout.write("%s %s\n" % (it, json.dumps(summary[it], default=str)[:600]))
        sys.stdout.flush()
    p = os.path.join(a.out, "summary-%s.json" % a.items.replace(",", "_"))
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
