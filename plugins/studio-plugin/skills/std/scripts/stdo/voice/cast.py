"""`check_assets.py <video> --actors` — the cast stage's check (m1-plan §8): s2v lint run by Studio (`unread-word`
fails from cast on, J32 — `STAGE_CHECKS["cast"]["fail_unread"]`), content unchanged since ①, every speaker of the
narration cast in the frontmatter with the voice and style of an actor in the roster (`<sr>/cast/*/status.json`, a
valid builtin record), and `work/<l>/pronounce-changes.json` exactly what the script's `pronounce` adds or changes
against HEAD's pronounce.json. Conflicts with HEAD and with other videos in progress are listed, never failed."""

import glob
import os

from .. import narrator, s2vlint
from ..state import schema
from . import frontmatter, pronounce


def roster(repo, root):
    """{actor id: status} of the valid builtin actors."""
    out = {}
    for p in sorted(glob.glob(os.path.join(repo, glob.escape(root), "cast", "*", "status.json"))):
        nid = os.path.basename(os.path.dirname(p))
        try:
            with open(p, "rb") as f:
                st = narrator.parse(f.read())
        except OSError:
            continue
        if st is not None and not narrator.problems(st, nid):
            out[nid] = st
    return out


def actor_problems(text, lang, sentences, actors):
    """([problems], {role: actor id})."""
    cast = frontmatter.block(text, "cast")
    if not isinstance(cast, dict) or not cast:
        return ["the script has no cast (write the default narrator into cast.<role>)"], {}
    used = sorted(set(s.get("cast") for s in sentences or [] if isinstance(s, dict) and s.get("cast")))
    out, chosen = [], {}
    for role in used:
        if role not in cast:
            out.append("the narration's speaker %s is not in the script's cast" % role)
    for role, spec in sorted(cast.items()):
        if not isinstance(spec, dict) or not spec.get("voice"):
            out.append("cast.%s has no voice" % role)
            continue
        want = (spec.get("voice"), spec.get("style") or None)
        hit = [nid for nid, st in sorted(actors.items())
               if ((st.get("voice") or {}).get(lang) or {}).get("engine") == want[0]
               and ((st.get("voice") or {}).get(lang) or {}).get("style") == want[1]]
        if not hit:
            out.append("cast.%s (%s, %s) is no actor of the roster for %s — use an actor's voice and style exactly"
                       % (role, want[0], want[1], lang))
        else:
            chosen[role] = hit[0]
    return out, chosen


def pronounce_problems(repo, vdir, lang, text):
    """([problems], the expected changes or None)."""
    smap = pronounce.of_script(text)
    if smap is None:
        return ["the script's pronounce is not a flat list of written form: reading"], None
    shared = pronounce.head_shared(repo)
    if shared is None:
        return ["HEAD's .claude/studio/pronounce.json is not a flat object"], None
    want = pronounce.changes(smap, shared)
    have, why = pronounce.read(pronounce.path_changes(vdir, lang))
    if have is None:
        return ["work/%s/pronounce-changes.json is %s (write {} when the script adds nothing)" % (lang, why)], want
    if have != want:
        return ["work/%s/pronounce-changes.json is not what the script's pronounce adds or changes against HEAD's "
                "pronounce.json (it should be %s)" % (lang, want)], want
    return [], want


def check(repo, root, vdir, state, lang, ctx, providers, env, runner, ctx_of=None):
    """(result, details) — the caller writes the check file."""
    problems = []
    fail_unread = schema.STAGE_CHECKS["cast"]["fail_unread"]
    lint = s2vlint.run(ctx["s2v_path"], ctx["script"], "lint", env=env, runner=runner, lang=lang,
                       fail_unread=fail_unread)
    if not lint.passed:
        problems.append("s2v lint: %s" % (", ".join(sorted(set(d["code"] for d in lint.failures)))
                                          or "exit %d" % lint.code))
    ins = providers.inspect(ctx)
    cur = providers.collect(ctx, state, lang, ins=ins)
    rec1 = state["langs"][lang]["approved"].get("1")
    if not isinstance(rec1, dict):
        problems.append("① is not approved yet")
    elif rec1["tuple"].get("content") != cur.get("content"):
        problems.append("the script's content changed since ① (cast changes only cast and pronounce) — undo it, or "
                        "go back to the script stage")
    with open(ctx["script"], encoding="utf-8") as f:
        text = f.read()
    sentences = providers.sentences(ctx)
    ap, chosen = actor_problems(text, lang, sentences, roster(repo, root))
    problems += ap
    pp, want = pronounce_problems(repo, vdir, lang, text)
    problems += pp
    shared = pronounce.head_shared(repo) or {}
    found = pronounce.conflicts(repo, root, state["video"], want or {}, shared, providers, ctx_of)
    details = {"lint": lint.details(), "fail_unread": fail_unread, "actors": chosen, "problems": problems,
               "pronounce_changes": want, "conflicts": found}
    return ("fail" if problems else "pass"), details, cur
