"""`check_claims.py <video> --narration [--lang l]` (the script stage) · `check_claims.py <video> [--lang l]` (verify)
(m1-plan §7.3 · §7.4). Each writes its stage's check result (`checks/script.json` · `checks/verify-claims.json`);
verify also writes `verify.json` and `verify.md` when it passes (and removes them when it does not).

`check_claims.py <video> --source [--fill]` (the source stage, 0.0.25 P9): the claim ids of `work/source.md`, one line
per claim (`line N  C-…  ok | placeholder | was C-…`); `--fill` writes the right ids into the file (the analyst writes
the placeholder C-00000000). Needs no script and no s2v.
`check_claims.py <video> --skeleton [--lang l]` (verify, 0.0.25 P13): (re)writes `work/<lang>/verify.draft.json` with
one entry per narration sentence, on-screen text and scene title the check judges; an entry whose text is still there
keeps what the fact-checker wrote. `--source`, `--skeleton` and `--narration` exclude each other.

Exit: 0 pass · 1 fail (the result lists why; for verify: `state.py loop <video> verify`, then the fact-checker again)
· 2 usage or setup (no harness, no such video, no script, no s2v)."""

import json
import os
import re
import sys

from .. import machine, paths, s2vlint, writes
from ..source import assets as assets_mod
from ..state import cli as scli, commands as C, schema, stagechecks, store
from ..state.collect import CollectError, Providers
from ..text.normalize import normalize
from . import check, linkrule, sourcemd

USAGE = "check_claims.py <video> [--narration | --skeleton | --source [--fill]] [--lang l]"
MODES = ("--narration", "--skeleton", "--source")
PLACEHOLDER = "C-00000000"
LOOSE_CLAIM = re.compile(r"^\s*[-*]\s+C-")  # a line meant as a claim (sourcemd.CLAIM is the well-formed one)


class Usage(Exception):
    pass


def _err(msg):
    sys.stderr.write("std check_claims: %s\n" % msg)


def _opts(argv):
    o = {"_": []}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in MODES or a == "--fill":
            o[a] = True
        elif a == "--lang" and i + 1 < len(argv):
            o[a] = argv[i + 1]
            i += 1
        elif a.startswith("--lang="):
            o["--lang"] = a.split("=", 1)[1]
        elif a.startswith("-"):
            raise Usage("unknown option: %s" % a)
        else:
            o["_"].append(a)
        i += 1
    if len(o["_"]) != 1:
        raise Usage(USAGE)
    if sum(1 for m in MODES if o.get(m)) > 1:
        raise Usage("--source, --skeleton and --narration exclude each other: " + USAGE)
    if o.get("--fill") and not o.get("--source"):
        raise Usage("--fill goes with --source: " + USAGE)
    return o


def _setup(argv, cwd):
    o = _opts(argv)
    try:
        repo, cfg = scli._repo(cwd)
    except scli.Usage as e:
        raise Usage(str(e))
    root = cfg.get("studio_root") or "studio"
    unsafe = paths.local_problem(repo, root)
    if unsafe:
        raise Usage(unsafe)
    vdir = store.video_dir(repo, root, o["_"][0])
    state = store.read_state(vdir)
    lang = o.get("--lang") or state["source_lang"]
    if lang not in state["langs"]:
        raise Usage("no language %s in %s" % (lang, state["video"]))
    ctx = scli._ctx(repo, cfg, vdir, lang)
    if o.get("--source"):  # the claim ids of work/source.md: no script and no s2v yet
        return o, repo, vdir, state, lang, ctx
    if not os.path.isfile(ctx["script"]):
        raise Usage("no script yet: %s" % os.path.relpath(ctx["script"], repo))
    if ctx["s2v_path"] is None:
        raise Usage(machine.HINT)
    return o, repo, vdir, state, lang, ctx


def _report(stage, result, problems, rel):
    if result == "pass":
        sys.stdout.write("%s: pass → %s\n" % (stage, rel))
    else:
        sys.stdout.write("%s: FAIL (%d problem(s)) → %s\n" % (stage, len(problems), rel))
        for p in problems:
            sys.stdout.write("  - %s\n" % p)


def script_check(repo, vdir, state, lang, ctx, providers, env, runner):
    problems = []
    from ..claims.brief import assets_problem
    why = assets_problem(vdir, state)
    if why:
        problems.append(why)
    fail_unread = schema.STAGE_CHECKS["script"]["fail_unread"]
    lint = s2vlint.run(ctx["s2v_path"], ctx["script"], "lint", env=env, runner=runner, lang=lang,
                       fail_unread=fail_unread)
    problems += lint.problems()
    copy = check.copy_text(vdir, state)
    cm, cm_problems = check.claims_map(vdir, lang, state, copy)
    problems += cm_problems
    ins = providers.inspect(ctx)
    cur = providers.collect(ctx, state, lang, ins=ins)
    sentences = providers.sentences(ctx)
    problems += check.narration_problems(sentences, lang)
    from .. import criteria, look
    with open(ctx["script"], encoding="utf-8") as f:
        text = f.read()
    try:
        crit = criteria.read(repo, state.get("kind"))
        problems += check.length_problems(text, schema.current_outputs(state, lang), crit, sentences, lang)
    except criteria.Missing as e:
        problems.append("the format's criteria cannot be read (%s)" % e)
    assets_data = assets_mod.read(vdir)
    problems += check.picture_problems(ins, assets_data)
    # 0.0.26 (pilot-2 P16 · P17): the post's images, the title scene, no presenter layout without character art
    problems += check.unused_problems(ins, assets_data, cm)
    problems += check.title_scene_problems(text)
    outs = look.outputs_of(text)
    for o in schema.current_outputs(state, lang):
        cast, art = look.cast_art(ins, o)
        attrs = outs.get(o) or {}
        lp = look.layout_problem(attrs.get("layout"), cast, art, "script", attrs.get("aspect"), o)
        if lp:
            problems.append(lp)
    details = {"lint": lint.details(), "fail_unread": fail_unread, "problems": problems,
               "screen_text": len(ins.get("screen_text") or []), "sentences": len(sentences or [])}
    result = "fail" if problems else "pass"
    inp = stagechecks.Inputs(ctx, state, lang, None, cur, providers)
    p = stagechecks.write(vdir, lang, "script", None, result, details,
                          stagechecks.input_sha("script", inp, cur.get("s2v_version")))
    _report("script", result, problems, os.path.relpath(p, repo))
    return C.OK if result == "pass" else C.FAIL


def verify_check(repo, vdir, state, lang, ctx, providers):
    w = os.path.join(vdir, "work", lang)
    draft, why = check._read_json(os.path.join(w, "verify.draft.json"), "work/%s/verify.draft.json" % lang)
    copy = check.copy_text(vdir, state)
    cm, problems = check.claims_map(vdir, lang, state, copy)
    if why:
        problems.append(why)
    else:
        ins = providers.inspect(ctx)
        problems += check.draft_problems(draft, cm, copy, providers.sentences(ctx), ins.get("screen_text"),
                                         [x.get("title") for x in ins.get("scenes") or [] if isinstance(x, dict)])
    for name in ("verify.json", "verify.md"):  # a failed or repeated check never leaves the last ones behind
        try:
            os.remove(os.path.join(w, name))
        except OSError:
            pass
    result = "fail" if problems else "pass"
    if result == "pass":
        v = check.verify_json(state, lang, draft, check.file_shas(ctx, vdir, lang, state))
        _atomic(os.path.join(w, "verify.json"), json.dumps(v, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        _atomic(os.path.join(w, "verify.md"), check.verify_md(v))
    inp = stagechecks.Inputs(ctx, state, lang, None)
    p = stagechecks.write(vdir, lang, "verify", None, result, {"problems": problems},
                          stagechecks.input_sha("verify", inp))
    _report("verify", result, problems, os.path.relpath(p, repo))
    if result != "pass":
        sys.stdout.write("next: python3 .claude/studio/scripts/state.py loop %s verify%s, then the fact-checker "
                         "again\n" % (state["video"], "" if lang == state["source_lang"] else " --lang " + lang))
    return C.OK if result == "pass" else C.FAIL


# ---------- --source (0.0.25 P9) ----------

def source_ids(text):
    """[(line, written id, right id or None, excerpt)] of the claims of a source.md text (sourcemd's format)."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    i = 0
    while i < len(lines):
        m = sourcemd.CLAIM.match(lines[i])
        if not m:
            i += 1
            continue
        line, written, quote = i + 1, m.group(1), []
        i += 1
        while i < len(lines) and sourcemd.QUOTE.match(lines[i]) and not sourcemd.CLAIM.match(lines[i]):
            quote.append(sourcemd.QUOTE.match(lines[i]).group(1))
            i += 1
        excerpt = "\n".join(quote)
        out.append((line, written, sourcemd.claim_id(excerpt) if excerpt.strip() else None, excerpt))
    return out


def claims_section(text):
    """[(line number, line)] of the Claims section: from a `# … Claims` heading to the next heading (the whole text
    when there is no such heading). Other sections (ruby pairs, notes) may hold `- C-…` lines that are not claims."""
    lines = list(enumerate((text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1))
    start = next((i for i, (_n, l) in enumerate(lines) if re.match(r"^#+\s*Claims\s*$", l, re.I)), None)
    if start is None:
        return lines
    out = []
    for n, l in lines[start + 1:]:
        if l.startswith("#"):
            break
        out.append((n, l))
    return out


def source_check(repo, vdir, fill):
    p = sourcemd.path(vdir)
    rel = os.path.relpath(p, repo)
    try:
        with open(p, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        sys.stdout.write("source: FAIL — %s is missing: the source analyst writes it\n" % rel)
        return C.FAIL
    claims = source_ids(text)
    problems, out, seen, fixes = 0, [], {}, {}
    for n, l in claims_section(text):
        if LOOSE_CLAIM.match(l) and not sourcemd.CLAIM.match(l):  # a mistyped id is never skipped silently
            problems += 1
            out.append("line %d  not a claim line (`- C-<8 hex digits>: <claim>`, e.g. `- C-00000000: …`): %s"
                       % (n, l.strip()[:80]))
    for line, written, right, _excerpt in claims:
        if right is None:
            problems += 1
            out.append("line %d  %s  no excerpt (`  > …` on the next line)" % (line, written))
            continue
        if written == right:
            st = "ok"
        else:
            st = "placeholder" if written == PLACEHOLDER else "was %s" % written
            fixes[line] = (written, right)
            if not fill:
                problems += 1
        if right in seen:  # identical excerpts give identical ids
            problems += 1
            st += " — listed twice (line %d) — make the excerpts differ" % seen[right]
        else:
            seen[right] = line
        out.append("line %d  %s  %s" % (line, right, st))
    if not claims:
        problems += 1
        out.append("no claims (`- C-00000000: <claim>` with `  > <excerpt>` on the next line)")
    if fill and fixes:
        lines = text.split("\n")
        for line, (written, right) in fixes.items():
            lines[line - 1] = lines[line - 1].replace(written, right, 1)
        _atomic(p, "\n".join(lines), check_writes=False)  # work/source.md is the analyst's file, not a record
    out.sort(key=lambda l: int(l.split()[1]) if l.startswith("line ") else 0)  # in the file's order
    for l in out:
        sys.stdout.write(l + "\n")
    if problems:
        sys.stdout.write("source: FAIL (%d problem(s)) → %s%s\n" % (
            problems, rel, "" if fill else " (`--source --fill` writes the right ids)" if fixes else ""))
        return C.FAIL
    sys.stdout.write("source: %s → %s\n" % ("filled %d id(s)" % len(fixes) if fixes else "pass", rel))
    return C.OK


# ---------- --skeleton (0.0.25 P13) ----------

def skeleton_texts(ins, sentences, cm):
    """The texts the verify check judges, in order: every narration sentence and on-screen text, and a scene title
    only when it states something (draft_problems' title rule); one per normalized text."""
    claims = (cm or {}).get("claims") if isinstance(cm, dict) else None
    claims = claims if isinstance(claims, dict) else {}
    listed = {}
    for cid, c in sorted(claims.items()):
        for t in (c.get("sentences") if isinstance(c, dict) and isinstance(c.get("sentences"), list) else []):
            if isinstance(t, str):
                ids = listed.setdefault(normalize(t), [])
                if cid not in ids:  # a claim listing a sentence twice cites it once
                    ids.append(cid)
    excerpts = (cm or {}).get("excerpts") if isinstance(cm, dict) else None
    ts = linkrule.terms(excerpts if isinstance(excerpts, list) else [])
    out, seen = [], set()

    def add(t):
        if isinstance(t, str) and t.strip() and normalize(t) not in seen:
            seen.add(normalize(t))
            out.append(t)
    for x in list(sentences or []) + list(ins.get("screen_text") or []):
        add(x.get("text") if isinstance(x, dict) else None)
    for x in ins.get("scenes") or []:
        t = x.get("title") if isinstance(x, dict) else None
        if isinstance(t, str) and (linkrule.has_number(t) or linkrule.term_in(t, ts) or normalize(t) in listed):
            add(t)
    return out, listed, claims


def skeleton(repo, vdir, lang, ctx, providers):
    w = os.path.join(vdir, "work", lang)
    p = os.path.join(w, "verify.draft.json")
    cm, _why = check._read_json(os.path.join(w, "claims-map.json"), "claims-map.json")
    ins = providers.inspect(ctx)
    texts, listed, claims = skeleton_texts(ins, providers.sentences(ctx), cm)
    old, why = check._read_json(p, "work/%s/verify.draft.json" % lang)
    have, dupes = {}, []
    if old is not None:
        for s in old.get("sentences") if isinstance(old, dict) and isinstance(old.get("sentences"), list) else []:
            if isinstance(s, dict) and isinstance(s.get("text"), str):
                if normalize(s["text"]) in have:
                    dupes.append(s["text"])  # a second entry of the same text: dropped, and said so
                else:
                    have[normalize(s["text"])] = s
    elif why and "is not JSON" in why:
        sys.stdout.write("the old draft was not JSON: written anew\n")
    entries, kept, added = [], 0, 0
    for t in texts:
        k = normalize(t)
        if k in have:
            entries.append(have.pop(k))
            kept += 1
            continue
        cids = listed.get(k, [])
        entries.append({"text": t, "kind": "fact", "claims": list(cids),
                        "excerpts": [claims[c].get("excerpt") for c in cids
                                     if isinstance(claims[c], dict) and isinstance(claims[c].get("excerpt"), str)],
                        "verdict": "", "note": ""})
        added += 1
    dropped = [s["text"] for s in have.values()] + dupes
    os.makedirs(w, exist_ok=True)
    _atomic(p, json.dumps({"sentences": entries}, ensure_ascii=False, indent=2) + "\n", check_writes=False)
    sys.stdout.write("skeleton: kept %d · added %d · dropped %d → %s\n" % (kept, added, len(dropped),
                                                                          os.path.relpath(p, repo)))
    for t in dropped:
        sys.stdout.write("  - dropped (no longer in the script): %s\n" % t[:80])
    return C.OK


def _atomic(p, text, check_writes=True):
    if check_writes:
        writes.check(os.path.basename(p))
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def main(argv, providers=None, env=None, cwd=None, runner=None):
    providers = providers or Providers()
    env = dict(os.environ if env is None else env)
    try:
        o, repo, vdir, state, lang, ctx = _setup(argv, cwd or os.getcwd())
        if o.get("--source"):
            return source_check(repo, vdir, o.get("--fill"))
        if o.get("--skeleton"):
            return skeleton(repo, vdir, lang, ctx, providers)
        if o.get("--narration"):
            return script_check(repo, vdir, state, lang, ctx, providers, env, runner)
        return verify_check(repo, vdir, state, lang, ctx, providers)
    except Usage as e:
        _err(e)
        return C.USAGE
    except schema.SchemaError as e:
        _err(e)
        return e.code or C.USAGE
    except CollectError as e:
        _err(e)
        return e.code
    except paths.UnsafeLocal as e:
        _err(e)
        return C.USAGE


def entry():
    writes.enable()  # the check results, verify.json and verify.md (P-STATE) are written from this entry
    return main(sys.argv[1:])
