"""The guard's shell scanner and normalization layer (M0d-1a, m0d1a-plan v7).

    scan(command, cwd, env, ...) -> Scan
    resolve_path(text, cwd, env) -> Resolved
    classify_s2v(cmd, s2v_path, ...) -> S2vForm | None
    load_snapshot(env) -> (Snapshot | None, notes)

No allow/deny decisions here (M0d-1b). The scanner never raises: a failure becomes
status "unparsable" or "error" with the whole command as one opaque part.
"""

from . import limits, recog, snapshot as snapshot_mod, terms as terms_mod
from .lex import ParseError
from .model import NOT_ALIAS, Opaque, Scan
from .parse import Parser
from .scanctx import Oracle, ScanCtx
from .walk import Walker, cwd_list, union
from .where import FS, Where

__all__ = ["scan", "resolve_path", "classify_s2v", "load_snapshot", "FS", "NOT_ALIAS"]


def load_snapshot(env, now=None):
    return snapshot_mod.load(env, now=now)


def resolve_path(text, cwd, env, fs=None):
    return Where(fs or FS(), env).resolve(text, cwd)


def classify_s2v(cmd, s2v_path, env, fs=None, paths=None):
    run = cmd.run_cwds[0] if len(cmd.run_cwds) == 1 else None
    return recog.classify_s2v(cmd.words, run, s2v_path, paths or [env.get("PATH", "")], fs or FS())


def _dedup(cmds, opaques):
    seen = {}
    remap = {}
    out = []
    for c in cmds:
        k = (c.span, tuple(c.argv), tuple(c.cwds), tuple(c.ctx), tuple(sorted(c.flags)),
             tuple(r.mode for r in c.redirs), c.parent and remap.get(c.parent, c.parent))
        if k in seen:
            remap[c.id] = seen[k]
            continue
        seen[k] = c.id
        out.append(c)
    for c in out:
        if c.parent in remap:
            c.parent = remap[c.parent]
    oseen = set()
    oout = []
    for o in opaques:
        if o.cmd in remap:
            o.cmd = remap[o.cmd]
        k = (o.kind, o.payload, o.cmd, o.origin, o.path)
        if k in oseen:
            continue
        oseen.add(k)
        oout.append(o)
    return out, oout


def scan(command, cwd, env, snapshot=None, snapshot_notes=(), terms=None, fs=None, budget=None, s2v_path=None):
    """Scan one Bash command string. `cwd` is the hook input's cwd (start of the call)."""
    result = Scan(command)
    fs = fs or FS()
    budget = budget or limits.Budget()
    ctx = None
    try:
        ctx = ScanCtx(env, fs, snapshot=snapshot, snapshot_notes=snapshot_notes, terms=terms, budget=budget,
                      s2v_path=s2v_path)
        if terms:
            result.raw_hits = terms.find(command)
        if "\x00" in command:
            raise ParseError("nul-byte", command.index("\x00"))
        if len(command) > limits.MAX_INPUT:
            raise limits.LimitExceeded("size")
        queue = [[]]
        state = {"total": 1}

        def schedule(taken, n):
            if state["total"] + (n - 1) > limits.ALT_TOTAL:
                return False
            for i in range(1, n):
                queue.append(list(taken) + [i])
            state["total"] += n - 1
            return True

        cmds, opq = [], []
        final = ()
        while queue:
            prefix = queue.pop(0)
            ctx.oracle = Oracle(prefix, schedule)
            ctx.tokens = 0
            ctx.depth = 0
            ast = Parser(command, ctx).parse_program()
            w = Walker(ctx, result)
            out = w.walk_list(ast, (cwd,) if cwd else None, _initial_state(w))
            final = union(final, union(out[0], out[1])) if final is not None else None
            cmds.extend(w.cmds)
            opq.extend(w.opaque)
        cmds, opq = _dedup(cmds, opq)
        for o in opq:
            if terms is not None:
                o.hits = terms.find(o.payload)
            o.hits_unknown = o.payload is None
            o.literals = (o.literals or []) + terms_mod.literals(o.payload)
        result.commands, result.opaque = cmds, opq
        result.stats["final_cwds"] = cwd_list(final)
    except ParseError as e:
        _fail(result, "unparsable", "%s@%d" % (e.code, e.pos), terms)
    except limits.LimitExceeded as e:
        _fail(result, "unparsable", "limit:%s" % e.kind, terms)
    except RecursionError:
        _fail(result, "unparsable", "limit:depth", terms)
    except Exception as e:  # noqa: BLE001 — never raise out of the scanner
        _fail(result, "error", "internal:%s" % type(e).__name__, terms)
    if ctx is not None:
        for n in list(snapshot_notes) + ctx.notes:
            result.note(n)
        if snapshot is None:
            result.note("snapshot-unavailable")
    result.stats.update({"tokens": ctx.tokens if ctx else 0, "commands": len(result.commands),
                         "fs_calls": fs.calls, "elapsed_ms": budget.elapsed_ms()})
    return result


def _initial_state(w):
    from .walk import State
    return State(w.ctx)


def _fail(result, status, reason, terms):
    result.status = status
    result.reason = reason
    result.commands = []
    op = Opaque("unparsable", payload=result.raw, origin="literal")
    op.hits = list(result.raw_hits)
    op.hits_unknown = False
    result.opaque = [op]
