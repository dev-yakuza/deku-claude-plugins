"""`check_assets.py <video> --output <o>` — the board stage's check (m1-plan §9, J73 · J81): s2v check run by Studio
(`unread-word` fails, STAGE_CHECKS board), content and voice unchanged since ②, the checked assets still the recorded
ones, and every picture the script shows (inspect's files of kind image · video · thumbnail):
- every file kind but recording · voice · font · bgm counts as a picture, the frontmatter logo too, and a kind Studio
  does not know as well (closed side, X1); fonts and music are listed in the details as information;
- a usable assets.json entry by its `script_src` (J73), inside the repository, PNG or JPEG by its bytes, and the same
  sha256 assets.json recorded;
- a CREDITS.yaml entry whose sha256 is the file's and whose hash is the one the person approved (`state.py credit`) —
  by the person: a proxy-mode credit counts only inside the proxy session (X2);
  entries with consent · originality_checked · ai_generated: true are not supported in M1;
- an image whose scope is third-party or unknown needs `public_ok: true` and a license (`TODO` · `see README` only
  with `license_checked: true`)."""

import os

from . import credits, s2vlint, sandbox
from .claims.brief import assets_problem
from .source import assets as assets_mod, imgformat
from .state import schema
from .state.hashes import file_sha

# every kind s2v inspect lists is a picture except these (s2v inspect.ts files.sha(…, kind)); a kind Studio does not
# know is a picture too — closed side (M1g review X1: the frontmatter logo is kind `logo`)
NOT_PICTURES = ("recording", "voice", "font", "bgm")


def is_picture(kind):
    kinds = [k for k in str(kind or "").split(",") if k]
    return not kinds or any(k not in NOT_PICTURES for k in kinds)


def picture_problems(repo, vdir, state, ins, proxy=False):
    """Problems of every picture the script shows. `proxy`: this is the sandbox proxy session (a credit approved by
    proxy counts only there — M1g review X2)."""
    out = []
    usable = credits.assets_by_src(assets_mod.read(vdir))
    cred, why = credits.read(os.path.join(vdir, credits.FILE))
    if why:
        out.append(why)
        cred = {}
    approved = state.get("credits") or {}
    real_top = os.path.realpath(repo)
    for f in ins.get("files") or []:
        if not isinstance(f, dict) or not is_picture(f.get("kind")):
            continue
        p = f.get("path")
        a = usable.get(p)
        if a is None:
            out.append("%s is not a usable image of work/assets.json (use its script_src)" % p)
            continue
        full = os.path.normpath(os.path.join(vdir, p))
        real = os.path.realpath(full)
        if not real.startswith(real_top.rstrip(os.sep) + os.sep):
            out.append("%s is outside the repository" % p)
            continue
        try:
            with open(real, "rb") as fh:
                data = fh.read()
        except OSError:
            out.append("%s cannot be read" % p)
            continue
        if imgformat.detect(data)[0] not in imgformat.USABLE:
            out.append("%s is not PNG or JPEG by its bytes" % p)
        sha = file_sha(real)
        if sha != a.get("sha256"):
            out.append("%s changed since resolve_assets (its sha is not assets.json's) — run the source stage again"
                       % p)
        e = cred.get(p)
        if e is None:
            out.append("%s has no CREDITS entry (every picture of a public video needs one, your own too)" % p)
            continue
        rec = approved.get(p)
        if not isinstance(rec, dict) or rec.get("hash") != credits.entry_hash(e):
            out.append("%s: its CREDITS entry is not the one the person approved — credit-preview, ask, credit" % p)
        elif rec.get("approved_by") != "human" and not proxy:
            out.append("%s: its credit was approved in the proxy mode — the person runs `state.py credit` for it "
                       "again (credit-preview, ask, credit)" % p)
        if e.get("sha256") != sha:
            out.append("%s: the file is not the one its CREDITS entry was approved for" % p)
        u = credits.unsupported(e)
        if u:
            out.append("%s: %s" % (p, u))
        scope = a.get("scope") or a.get("floor") or "unknown"
        if scope in ("third-party", "unknown"):
            if e.get("public_ok") is not True:
                out.append("%s is %s: a public video needs public_ok: true in its CREDITS entry" % (p, scope))
            lic = e.get("license")
            if not isinstance(lic, str) or not lic.strip():
                out.append("%s is %s: it needs a license" % (p, scope))
            elif lic in credits.LICENSE_UNCHECKED and e.get("license_checked") is not True:
                out.append("%s: license %r needs license_checked: true" % (p, lic))
    return out


def check(repo, vdir, state, lang, ctx, output, providers, env, runner):
    """(result, details, cur)."""
    problems = []
    fail_unread = schema.STAGE_CHECKS["board"]["fail_unread"]
    res = s2vlint.run(ctx["s2v_path"], ctx["script"], "check", env=env, runner=runner, lang=lang,
                      fail_unread=fail_unread)
    if not res.passed:
        problems.append("s2v check: %s" % (", ".join(sorted(set(d["code"] for d in res.failures)))
                                           or "exit %d" % res.code))
    ins = providers.inspect(ctx)
    cur = providers.collect(ctx, state, lang, ins=ins)
    rec2 = state["langs"][lang]["approved"].get("2")
    if not isinstance(rec2, dict):
        problems.append("② is not approved yet")
    else:
        for k in ("content", "voice"):
            if rec2["tuple"].get(k) != cur.get(k):
                problems.append("the script's %s changed since ② (board changes only how it looks)" % k)
    why = assets_problem(vdir, state)
    if why:
        problems.append(why)
    problems += picture_problems(repo, vdir, state, ins, proxy=sandbox.active(env or {}, repo))
    other = [{"path": f.get("path"), "kind": f.get("kind")} for f in ins.get("files") or []
             if isinstance(f, dict) and not is_picture(f.get("kind"))]
    details = {"check": res.details(), "fail_unread": fail_unread, "output": output, "problems": problems,
               "not_pictures": other}  # fonts, music, voices: information (they need no CREDITS entry here)
    return ("fail" if problems else "pass"), details, cur
