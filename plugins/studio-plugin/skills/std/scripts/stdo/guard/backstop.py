"""fix20: the 0.0.26 guard as a backstop. Every call is judged by this guard (G1) and by the 0.0.26 guard, kept
frozen in guard/legacy (d2028cc; tests/structure_test.sh checks the copy). Anything either refuses is refused.

    G1 judges first, without its effects. When it refuses, its answer stands (the 0.0.26 guard is not imported).
    Otherwise the 0.0.26 guard judges, without its effects. When it refuses, its own message is the answer.
    Otherwise exactly one finish runs (evidence writes, then allow): G1's, or the 0.0.26 guard's when G1 stopped at a
    `source` / `.` (what follows it was judged by the 0.0.26 rules only) or stopped early on a limit.

`judge.decide` is `decide` (an alias): the 0.0.26 code runs at the stack depth it had in 0.0.26 (P20-3). Nothing here
changes a module of the frozen copy except three functions, each wrapped once: its push and commit checks, so that the
two guards share one run of each within a decision (P20-4: G1 calls the frozen checks themselves, through
`shared_push` and `shared_commit`), and its snapshot `split_line`, so that a shell line repeated across the snapshot
files is split once per decision (fix-0029 §1.3; the frozen function still computes every first answer, with its own
lexer — the two guards never share a parse)."""

import time
import types

# P20-8: when G1 alone took this long, the 0.0.26 guard is not started and the call is refused (G-LIMIT) — the hook
# times out at 20 s (hooks.json), and both guards together could pass it; a hook that times out blocks the call
# (onFailure "block", m0-measure X6), but without a message
DEADLINE = 9.0
_MEMO = {}
# fix-0029 §1.3: the frozen snapshot.split_line's answers (line → words), only while `decide` runs (`_SPLIT_ON`)
_SPLIT = {}
_SPLIT_ON = []
SPLIT_MAX = 4096
_LEGACY = []  # [legacy package, legacy judge, _decide without finish]: imported on first use, after G1 judged


def _legacy():
    if not _LEGACY:
        from .legacy import commitrule as lc, judge as lj, push as lp, snapshot as ls
        _install(lp, lc)
        _install_split(ls)
        # HEAD's own _decide, its code object unchanged: only the name `finish` it looks up is a no-op here (no
        # module of the frozen copy changes; test_guard_backstop checks the code and the lines after the finish)
        g = dict(vars(lj))
        g["finish"] = _no_finish
        dec = types.FunctionType(lj._decide.__code__, g, "_decide", lj._decide.__defaults__, lj._decide.__closure__)
        _LEGACY[:] = [lj, dec]
    return _LEGACY


def _no_finish(ctx):
    return None


def decide(hook, env, fs=None, probe=None, snapshot_loader=None, legacy_snapshot_loader=None, legacy_probe=None):
    """(Deny | None, Context). `fs` / `probe` / `snapshot_loader` are G1's (tests); the 0.0.26 guard gets its own file
    system budget and git probe (`legacy_probe` in tests) and loads the snapshot itself (`legacy_snapshot_loader`, or
    the `legacy_view` an injected G1 snapshot carries)."""
    from . import judge
    t0 = time.monotonic()
    _MEMO.clear()
    _SPLIT.clear()
    _SPLIT_ON[:] = [True]
    try:
        g_deny, g, complete = judge.decide_g1(hook, env, fs=fs, probe=probe, snapshot_loader=snapshot_loader,
                                              run_finish=False)
        if g_deny is not None:
            return g_deny, g
        _release(g)
        if time.monotonic() - t0 > DEADLINE:
            g.denies.insert(0, judge.Deny("G-LIMIT", "the command needs more checks than the guard's time allows — "
                                                     "split it into simpler commands, one step per call."))
            return g.denies[0], g
        lj, legacy_decide = _legacy()
        lctx = lj.Context(hook, env, probe=legacy_probe,
                          snapshot_loader=_legacy_loader(snapshot_loader, legacy_snapshot_loader))
        try:
            l_deny = legacy_decide(lctx, hook)[0]
        except Exception as e:  # noqa: BLE001 — HEAD's own handler (judge.decide at d2028cc), HEAD's text (Q4)
            lctx.denies.insert(0, lj.Deny("G-ERR", "internal guard error (%s) — tell the user; this is a bug in the "
                                                   "guard." % type(e).__name__))
            l_deny = lctx.denies[0]
    finally:
        _MEMO.clear()
        _SPLIT.clear()
        del _SPLIT_ON[:]
    _merge(g, lctx)
    if l_deny is not None:
        g.denies = list(lctx.denies)
        return l_deny, g
    if g.sourced or not complete:
        # what follows a source (or what G1 did not reach) was judged by the 0.0.26 rules alone: their effects
        # and allow, exactly as in 0.0.26; G1's effects and candidates are dropped
        _legacy_finish(lj, lctx)
        g.allow = lctx.allow
        g.denies = list(lctx.denies)
        return (g.denies[0] if g.denies else None), g
    return judge.finish_g1(g, hook), g


def _legacy_finish(lj, lctx):
    try:
        lj.finish(lctx)
    except Exception as e:  # noqa: BLE001 — as HEAD's decide (P20-7)
        lctx.denies.insert(0, lj.Deny("G-ERR", "internal guard error (%s) — tell the user; this is a bug in the "
                                               "guard." % type(e).__name__))


def _release(g):
    """P20-3: what only G1's checks used, dropped before the 0.0.26 guard runs (its finish keeps what it needs)."""
    g.nested_memo = {}
    g.commit_memo = {}
    memo = getattr(g.probe, "memo", None)
    if isinstance(memo, dict):
        memo.clear()


def _merge(g, lctx):
    """The touched repositories (guard-ran record) and the warnings of both, G1's first."""
    seen = {getattr(ri, "worktree", None) for ri in g.touched}
    for ri in lctx.touched:
        if getattr(ri, "worktree", None) not in seen:
            g.touched.append(ri)
            seen.add(getattr(ri, "worktree", None))
    for w in lctx.warnings:
        if w not in g.warnings:
            g.warnings.append(w)


def _legacy_loader(snapshot_loader, legacy_snapshot_loader):
    if legacy_snapshot_loader is not None or snapshot_loader is None:
        return legacy_snapshot_loader  # None: the 0.0.26 snapshot.load (production)

    def load(env):
        snap, notes = snapshot_loader(env)
        if snap is None:
            return None, list(notes)
        view = getattr(snap, "legacy_view", None)
        if view is None:
            raise ValueError("an injected snapshot without its 0.0.26 reading (legacy_snapshot_loader)")
        return view
    return load


# ---- the push and commit checks, shared within one decision (P20-4) ----

def _env_key(env):
    return tuple(sorted((k, v) for k, v in (env or {}).items()))


def _install(lp, lc):
    """Wrap the frozen push.check and commitrule.evaluate once: the two guards ask the same question with the same
    inputs (the code is the frozen one for both), and the repository does not change in between (the guards run
    nothing). Keys are every input of the checks; push reads only the words' values (push.parse)."""
    if getattr(lp.check, "_shared", False):
        return
    push_check, commit_eval = lp.check, lc.evaluate

    def check(worktree, env, args, internal_ids, budget=3.0):
        key = ("push", worktree, _env_key(env), tuple(w.value for w in args), frozenset(internal_ids or ()), budget)
        if key not in _MEMO:
            d, w = check.__wrapped__(worktree, env, args, internal_ids, budget)
            _MEMO[key] = (d, list(w))
        d, w = _MEMO[key]
        return d, list(w)

    def evaluate(worktree, env, extra_env, opts, budget=8.0, plugin_scripts=None):
        key = ("commit", worktree, _env_key(env), _env_key(extra_env), repr(sorted(opts.items())), budget,
               plugin_scripts)
        if key not in _MEMO:
            _MEMO[key] = evaluate.__wrapped__(worktree, env, extra_env, opts, budget=budget,
                                              plugin_scripts=plugin_scripts)
        return _MEMO[key]

    check._shared = evaluate._shared = True
    check.__wrapped__, evaluate.__wrapped__ = push_check, commit_eval
    lp.check, lc.evaluate = check, evaluate


def _install_split(ls):
    """Wrap the frozen snapshot.split_line once (fix-0029 §1.3). The frozen parse_snapshot looks the name up as a
    module global at each call (alias, `unalias` and PATH lines), so it calls this wrapper. Inside `decide` a line's
    words are kept (at most SPLIT_MAX lines; a new list is returned each time); an exception is never kept. Outside
    `decide` (tests loading snapshots) it passes every call through. `__wrapped__` is looked up at each call."""
    if getattr(ls.split_line, "_shared", False):
        return

    def split_line(line):
        if not _SPLIT_ON:
            return split_line.__wrapped__(line)
        words = _SPLIT.get(line)
        if words is None:
            words = split_line.__wrapped__(line)
            if len(_SPLIT) < SPLIT_MAX:
                _SPLIT[line] = words
        return list(words)

    split_line._shared = True
    split_line.__wrapped__ = ls.split_line
    ls.split_line = split_line


def _frozen_checks():
    from .legacy import commitrule as lc, push as lp
    _install(lp, lc)
    return lp, lc


def shared_push(worktree, env, args, internal_ids):
    """G1's push check: the frozen 0.0.26 one (shared with the 0.0.26 guard within this decision)."""
    return _frozen_checks()[0].check(worktree, env, args, internal_ids)


def shared_commit(worktree, env, extra_env, opts, plugin_scripts=None):
    """G1's commit check: the frozen 0.0.26 one (shared with the 0.0.26 guard within this decision)."""
    return _frozen_checks()[1].evaluate(worktree, env, extra_env, opts, plugin_scripts=plugin_scripts)
