"""The translation stage (design/herald/01-multilingual.md §2, §4).

critique → translation → verify. The translator carries the critique-passed source into each
of the topic's languages; code checks what a person would otherwise have to trust:

- the source did not change while translating (it is what critique evaluated);
- every language in `pending` exists, passes its own gate and maps the same claims as the
  source (claim correspondence — catches omitted or added facts, not distortions);
- languages outside `pending` are byte-for-byte what last passed.

State lives in state.json `translation` (schema in the design §2).
"""

import hashlib
import os
import re

from .hashing import file_hash, worktree_hash
from .util import HeraldError, now_iso, read_json

EMPTY = "sha256:" + hashlib.sha256(b"").hexdigest()  # @translations of a topic with no languages


def work_rel(tid, name):
    return os.path.join(".claude", "herald", "work", tid, name)


def map_name(lang=None):
    return "claims-map.%s.json" % lang if lang else "claims-map.json"


# --- topic languages (§2 table) ---------------------------------------------------------------

def existing_langs(root, cfg, slug):
    """Translation languages whose file exists for slug (refresh carries all of them, L13)."""
    return [lang for lang, p in cfg.translation_paths(slug).items() if os.path.isfile(os.path.join(root, p))]


def init_state(root, cfg, topic, slug=None):
    """`translation` for a new state.json, or None when the repo does not translate (then the
    topic behaves as in 0.8.0)."""
    if not cfg.translations():
        return None
    targets = cfg.target_langs()
    asked = topic.get("languages") if isinstance(topic.get("languages"), list) else None
    if topic.get("refresh_of") and slug:
        langs = sorted(set(existing_langs(root, cfg, slug)) | set(asked or []))
        why = "refresh-existing"
    else:
        langs = list(asked) if asked is not None else list(targets)
        why = "begin"
    bad = [l for l in langs if l not in targets]
    if bad:
        raise HeraldError("topic languages %s are not translation targets in config.json" % ", ".join(bad))
    at = now_iso()
    return {"langs": langs, "log": [{"at": at, "lang": l, "why": why} for l in langs],
            "pending": list(langs), "passed": {}, "hashes": {}, "source_hash": None, "round": 0,
            "last_refusal": None, "enabled_at_begin": True}


def langs_of(st):
    return list((st.get("translation") or {}).get("langs") or [])


# --- hashes -----------------------------------------------------------------------------------

def lang_record(root, cfg, tid, slug, lang):
    return {"file": file_hash(root, cfg.body_path(slug, lang)), "map": file_hash(root, work_rel(tid, map_name(lang)))}


def translations_hash(root, cfg, st):
    """`@translations`: every topic language's file + claims map (EMPTY without languages)."""
    langs = langs_of(st)
    if not langs:
        return EMPTY
    h = hashlib.sha256()
    for lang in sorted(langs):
        r = lang_record(root, cfg, st["topic_id"], st["slug"], lang)
        if r["file"] is None or r["map"] is None:
            return None
        h.update(("%s\0%s\0%s\n" % (lang, r["file"], r["map"])).encode())
    return "sha256:" + h.hexdigest()


# --- claim correspondence (§4) ---------------------------------------------------------------

_FM_RE = re.compile(r"\A(?:---|\+\+\+)\r?\n.*?\r?\n(?:---|\+\+\+)\r?\n?", re.S)


def normalize(text):
    """Markdown-insensitive comparison text: links and images to their label, no emphasis or
    code marks, no tags, single spaces."""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[*_`~]+", "", t)
    t = re.sub(r"^[ \t]*(?:[-+>]|#{1,6}|\d+[.)])[ \t]+", "", t, flags=re.M)
    return re.sub(r"\s+", " ", t).strip()


def body_norm(root, path):
    try:
        with open(os.path.join(root, path), encoding="utf-8") as f:
            text = f.read().replace("\r\n", "\n")
    except OSError:
        return None
    return normalize(_FM_RE.sub("", text, count=1))


def entries(root, tid, lang=None):
    """Sentences of a claims map; a missing or malformed file → None."""
    data = read_json(os.path.join(root, work_rel(tid, map_name(lang))))
    sents = (data or {}).get("sentences") if isinstance(data, dict) else None
    if not isinstance(sents, list):
        return None
    return [s for s in sents if isinstance(s, dict) and isinstance(s.get("text"), str)
            and isinstance(s.get("claims"), list)]


def present_ids(sents, body):
    ids = set()
    for s in sents:
        t = normalize(s["text"])
        if t and t in body:
            ids.update(str(c).strip() for c in s["claims"])
    return ids


def missing_texts(sents, body):
    return [s["text"] for s in sents if normalize(s["text"]) and normalize(s["text"]) not in body]


def correspondence(root, cfg, tid, slug, lang):
    """None when the translation maps exactly the claims the source does, else a reason. Both
    sides count only sentences that are really in their body: a human who deletes a qualifier
    from a translation and leaves its map alone still shows up (§4)."""
    src_body = body_norm(root, cfg.body_path(slug))
    tr_body = body_norm(root, cfg.body_path(slug, lang))
    src, tr = entries(root, tid), entries(root, tid, lang)
    if src is None or src_body is None:
        return "the source claims map or article cannot be read"
    if tr is None:
        return "%s is missing or malformed ({\"sentences\": [{\"text\", \"claims\"}]})" % map_name(lang)
    if tr_body is None:
        return "the %s translation cannot be read" % lang
    want, have = present_ids(src, src_body), present_ids(tr, tr_body)
    if want == have:
        return None
    parts = []
    if want - have:
        parts.append("claims missing in %s: %s" % (lang, ", ".join(sorted(want - have))))
    if have - want:
        parts.append("claims in %s the source does not state: %s" % (lang, ", ".join(sorted(have - want))))
    return "; ".join(parts)


def draft_text_problems(root, cfg, tid, slug):
    """Every source map `text` must be in the body (translation repos only — the correspondence
    filter would otherwise drop real mappings, §4)."""
    sents = entries(root, tid)
    body = body_norm(root, cfg.body_path(slug))
    if sents is None or body is None:
        return ["claims-map.json is missing or malformed ({\"sentences\": [{\"text\", \"claims\"}]})"]
    gone = missing_texts(sents, body)
    return ["claims-map.json text not found in the article (copy each sentence verbatim): %s"
            % "; ".join(t[:80] for t in gone[:3])] if gone else []


# --- stage hooks --------------------------------------------------------------------------------

def on_critique_pass(st, critique_hash):
    """The source was (re)critiqued: every translation is made again from it. Old-round records
    must not feed the out-of-pending comparison or the pending formula (§2). Returns the next
    stage."""
    tr = st.get("translation")
    if not tr:
        return "verify"
    tr.update({"pending": list(tr.get("langs") or []), "passed": {}, "hashes": {}, "last_refusal": None,
               "round": 0})
    if not tr.get("langs"):
        tr["source_hash"] = critique_hash
        st["stages"]["translation"] = {"outputs": {"@translations": EMPTY}, "at": now_iso()}
        return "verify"
    tr["source_hash"] = None
    return "translation"


def verify_entry_problems(st):
    tr = st.get("translation") or {}
    if not tr.get("langs"):
        return []  # 0.8.0 topics, untranslated repos, no-language topics: as before (trim, L15)
    problems = []
    if tr.get("source_hash") != (st["stages"].get("critique") or {}).get("body_hash"):
        problems.append("the translations were not made from the critiqued source — run the translation stage")
    if tr.get("pending"):
        problems.append("translation pending for %s — run the translation stage" % ", ".join(tr["pending"]))
    return problems


class TranslationRefused(HeraldError):
    pass


def stage_pass(root, cfg, tid, st, run_gate, save_state, record_gate_failure):
    """`HRD stage pass --stage translation`. Order matters (§4): the source check comes first so
    a translator that edited the source reaches its own refusal (needs-human), not a stale-
    artifact message."""
    tr = st.get("translation")
    if not tr or not tr.get("langs"):
        raise HeraldError("this topic has no translation languages — verify follows critique")
    if tid.startswith("tr-") and not tr.get("remapped"):
        raise HeraldError("`HRD remap --topic %s` first (the inherited claims map must match the source)" % tid)
    slug = st["slug"]
    crit = (st["stages"].get("critique") or {}).get("body_hash")
    if not crit:
        raise HeraldError("critique has not passed")
    if worktree_hash(root, cfg, slug) != crit:
        raise HeraldError("the source changed during translation (translator modified the source) — "
                          "hold needs-human; translation cannot repair it")
    tr["round"] = int(tr.get("round") or 0) + 1
    refused, reasons = [], []
    pending = list(tr.get("pending") or [])
    for lang in pending:
        path = cfg.body_path(slug, lang)
        why = None
        if not os.path.isfile(os.path.join(root, path)):
            why = "%s missing (%s)" % (lang, path)
        elif not os.path.isfile(os.path.join(root, work_rel(tid, map_name(lang)))):
            why = "%s missing" % map_name(lang)
        else:
            gate = run_gate(root, cfg, slug, lang=lang)
            if not gate["ok"]:
                record_gate_failure(root, st, tid, "translation", gate, lang=lang)
                why = "%s gate: %s" % (lang, "; ".join(gate["errors"][:3]))
            else:
                why = correspondence(root, cfg, tid, slug, lang)
        if why:
            refused.append(lang)
            reasons.append(why)
        else:
            tr.setdefault("passed", {})[lang] = lang_record(root, cfg, tid, slug, lang)
    for lang in tr["langs"]:
        if lang in pending:
            continue
        expect = (tr.get("passed") or {}).get(lang) or (tr.get("hashes") or {}).get(lang)
        if expect is None:
            refused.append(lang)
            reasons.append("%s has no passing record and is not pending" % lang)
        elif lang_record(root, cfg, tid, slug, lang) != expect:
            refused.append(lang)
            reasons.append("%s changed although it was not being translated" % lang)
    if refused:
        tr["last_refusal"] = {"at": now_iso(), "round": tr["round"], "langs": sorted(set(refused)),
                              "reason": "; ".join(reasons)[:1000], "consumed": False}
        save_state(st)
        raise TranslationRefused("translation refused: %s — `HRD loopback --topic %s --cause translation`"
                                 % ("; ".join(reasons[:4]), tid))
    tr["hashes"] = {lang: lang_record(root, cfg, tid, slug, lang) for lang in tr["langs"]}
    tr.update({"source_hash": crit, "pending": [], "passed": {}, "last_refusal": None})
    st["stages"]["translation"] = {"outputs": {"@translations": translations_hash(root, cfg, st)}, "at": now_iso()}
    st["stage"] = "verify"
    save_state(st)
    return st


def loopback(root, cfg, st, langs, ver, human=False):
    """`HRD loopback --cause translation [--lang …]` / `--human --lang …`: back to the translation
    stage for some languages. The basis is checked here (§4): a fresh translation refusal, or a
    verify result whose source part is clean and that names a gap in these languages."""
    tr = st.get("translation") or {}
    all_langs = tr.get("langs") or []
    if not all_langs:
        raise HeraldError("this topic has no translation languages")
    if st.get("topic_id", "").startswith("tr-") and not human:
        # a tr- verify covers every language of the bundle: a defect in an existing translation
        # outside the request joins the topic (and its PR scope) — §7 step 5
        for l in langs:
            if l not in all_langs and l in cfg.target_langs() and \
                    os.path.isfile(os.path.join(root, cfg.body_path(st["slug"], l))):
                all_langs.append(l)
                tr.setdefault("log", []).append({"at": now_iso(), "lang": l, "why": "tr-existing-defect"})
        tr["langs"] = all_langs
    bad = [l for l in langs if l not in all_langs]
    if bad:
        raise HeraldError("%s not among this topic's languages (%s)" % (", ".join(bad), ", ".join(all_langs)))
    ref = tr.get("last_refusal") or {}
    if human:
        if not langs:
            raise HeraldError("--human --lang names the languages to redo")
        new = set(langs)
    elif ref and not ref.get("consumed"):
        ref["consumed"] = True
        # what is still owed: refused languages, and any language with no passing record —
        # never one that passed this round (01-multilingual.md §4)
        done = set(tr.get("passed") or {}) | set(tr.get("hashes") or {})
        new = (set(tr.get("pending") or []) - done) | set(ref.get("langs") or []) | (set(all_langs) - done) | set(langs)
    else:
        by = (ver or {}).get("by_lang")
        if not isinstance(by, dict):
            raise HeraldError("no basis for a translation loopback: no unconsumed translation refusal and no "
                              "current verify.json with by_lang")
        src = by.get(cfg.source_lang()) or {}
        if _gap(src):
            raise HeraldError("the source has unsupported or contradicted sentences — `--cause verify` (back to draft)")
        gaps = [l for l in all_langs if _gap(by.get(l) or {})]
        if not langs:
            langs = gaps
        if not langs or any(l not in gaps for l in langs):
            raise HeraldError("verify.json shows no gap in %s (gaps: %s)" % (", ".join(langs) or "-", ", ".join(gaps) or "none"))
        new = set(langs)
    prev = tr.get("last_loopback_langs") or []
    tr["pending"] = sorted(new)
    stagnant = (not human) and bool(set(prev) & set(new)) and tr.get("last_loopback_stage") == "translation"
    tr["last_loopback_langs"] = sorted(new)
    tr["last_loopback_stage"] = "translation"
    st["stage"] = "translation"
    return sorted(new), stagnant


def _gap(rec):
    c = rec.get("counts") if isinstance(rec, dict) else None
    if not isinstance(c, dict):
        return False
    try:
        return int(c.get("unsupported", 0)) > 0 or int(c.get("contradicted", 0)) > 0
    except (TypeError, ValueError):
        return True


# --- verify (§4) -------------------------------------------------------------------------------

def verify_problems(root, cfg, st, ver):
    """by_lang bookkeeping in a translation repo: one entry per existing language, each made
    for the file as it is now, and top-level counts equal to their sum."""
    from .hashing import lang_hash

    if not cfg.translations():
        return []
    slug = st["slug"]
    present = [cfg.source_lang()] + [l for l in cfg.target_langs()
                                     if os.path.isfile(os.path.join(root, cfg.body_path(slug, l)))]
    if present == [cfg.source_lang()] and not isinstance((ver or {}).get("by_lang"), dict):
        return []  # nothing translated: verify.json as in 0.8.0
    by = (ver or {}).get("by_lang")
    if not isinstance(by, dict):
        return ["verify.json needs by_lang (one entry per language: hash, counts, unsupported_sentences)"]
    problems = []
    for lang in present:
        rec = by.get(lang)
        if not isinstance(rec, dict):
            problems.append("verify.json by_lang has no %s entry" % lang)
            continue
        if rec.get("hash") != lang_hash(root, cfg, slug, lang):
            problems.append("verify.json by_lang.%s.hash is not the current %s file — take `HRD hash --lang` "
                            "before spawning the fact-checker" % (lang, lang))
    total = {"supported": 0, "unsupported": 0, "contradicted": 0}
    try:
        for lang in present:
            c = (by.get(lang) or {}).get("counts") or {}
            for k in total:
                total[k] += int(c.get(k, 0))
        top = ver.get("counts") or {}
        if any(int(top.get(k, 0)) != total[k] for k in total):
            problems.append("verify.json counts are not the sum of by_lang counts")
    except (TypeError, ValueError):
        problems.append("verify.json by_lang counts are malformed")
    return problems


def amend_problems(root, cfg, tid, st, run_gate):
    """`verify --amend` (a human's push re-verified): gate and correspondence for every
    translation whose file or map changed since the translation stage passed (§4 table)."""
    tr = st.get("translation") or {}
    problems = []
    for lang in tr.get("langs") or []:
        if lang_record(root, cfg, tid, st["slug"], lang) == (tr.get("hashes") or {}).get(lang):
            continue
        gate = run_gate(root, cfg, st["slug"], lang=lang)
        if not gate["ok"]:
            problems.append("%s gate: %s" % (lang, "; ".join(gate["errors"][:3])))
            continue
        why = correspondence(root, cfg, tid, st["slug"], lang)
        if why:
            problems.append(why)
    return problems


# --- ship: before merging a PR that carries translations (01-multilingual.md §5) --------------

def premerge_problems(root, cfg, tid, rev):
    """Checks ship runs on a PR head before merging (attended, session-auto and --auto alike).
    Without translations in config: none (0.8.0)."""
    from .commits import changed_files, topic_langs
    from .hashing import tree_hash
    from .store import find_article, load_published, read_json_at

    if not cfg.translations():
        return []
    st = read_json_at(root, rev, work_rel(tid, "state.json")) or {}
    slug = st.get("slug")
    if not slug:
        return ["no state.json with a slug at the PR head"]
    langs = topic_langs(root, tid, rev=rev)
    base = "origin/%s" % cfg.base
    problems = []
    tr_paths = cfg.translation_paths(slug)
    in_pr = changed_files(root, "%s...%s" % (base, rev))
    # 1. the source on base must be what this PR's translations were made from
    if tid.startswith("tr-"):
        if tree_hash(root, cfg, base, slug) != ((st.get("stages") or {}).get("critique") or {}).get("body_hash"):
            problems.append("base-source-changed: the source on base is not the one this translation was made from "
                            "— decline and start again (`/hrd translate`)")
    elif langs or tid.startswith("r-"):
        mb = __import__("subprocess").run(["git", "merge-base", base, rev], cwd=root, capture_output=True, text=True)
        if mb.returncode == 0:
            moved = changed_files(root, "%s..%s" % (mb.stdout.strip(), base))
            bundle = set(cfg.bundle_paths(slug))
            img = cfg.image_dir(slug).rstrip("/") + "/"
            if any(p in bundle or p.startswith(img) for p in moved):
                problems.append("base-bundle-changed: the article's files changed on base after this PR forked — "
                                "decline and refresh")
    # 2. a PR never deletes a translation, nor adds one outside its languages
    status = __import__("subprocess").run(["git", "diff", "--name-status", "-z", "%s...%s" % (base, rev)],
                                          cwd=root, capture_output=True, text=True).stdout.split("\0")
    deleted = {status[i + 1] for i in range(0, len(status) - 1, 2) if status[i].startswith("D")}
    for lang, p in tr_paths.items():
        if p in deleted:
            problems.append("translation-deleted:%s — a PR does not take a language down (use `status --withdraw-lang` "
                            "after publishing)" % lang)
        elif p in in_pr and lang not in langs:
            problems.append("translation-added:%s — not one of this topic's languages" % lang)
    # 3. a language taken down while this PR was open must not come back unasked
    art = find_article(load_published(root), slug) or {}
    revived = {e.get("lang") for e in (st.get("translation") or {}).get("log") or [] if e.get("why") == "revive"}
    back = sorted(set(langs) & set(art.get("withdrawn_langs") or []) - revived)
    if back:
        problems.append("withdrawn-lang:%s — taken down after this PR opened; decline it" % ",".join(back))
    return problems


# --- later translation: /hrd translate (01-multilingual.md §7) --------------------------------

def translate_check(root, cfg, slug, langs=None, adopt=False, exclude=None):
    """Preconditions of a tr- topic (step 2, and again at begin): a Herald article whose bundle
    is verified (or, adopting, whose only difference is the human translations being adopted),
    whose reference topic left research.md and claims-map.json on base, with no other topic in
    flight. Returns {"ref", "langs"}; raises with every reason otherwise."""
    from . import ghstate, integrity
    from .store import find_article, load_published

    if not cfg.translations():
        raise HeraldError("this repo has no `translations` in config — `/hrd config` first")
    pub = load_published(root)
    art = find_article(pub, slug)
    if not art or art.get("origin") != "herald" or art.get("withdrawn"):
        raise HeraldError("%s is not a published Herald article — an external article has no research to verify a "
                          "translation against: `/hrd refresh %s` first" % (slug, slug))
    prs = ghstate.herald_prs(root, cfg)
    ref = (ghstate.herald_set(root, cfg, prs=prs, pub=pub).get(slug) or {}).get("ref_topic")
    problems = []
    if not ref:
        problems.append("no reference topic for %s" % slug)
    else:
        for name in ("research.md", "claims-map.json"):
            if not os.path.isfile(os.path.join(root, work_rel(ref, name))):
                problems.append("%s of the reference topic %s is not on base" % (name, ref))
    existing = set(existing_langs(root, cfg, slug))
    withdrawn = set(art.get("withdrawn_langs") or [])
    if langs:
        bad = [l for l in langs if l not in cfg.target_langs()]
        if bad:
            problems.append("%s not translation targets" % ", ".join(bad))
    elif adopt:
        problems.append("--adopt names the languages to adopt")
    else:
        langs = [l for l in cfg.target_langs() if l not in existing and l not in withdrawn]
        if not langs:
            problems.append("%s already has every target language (taken-down ones need --lang)" % slug)
    langs = list(langs or [])
    if adopt:
        missing = [l for l in langs if l not in existing]
        if missing:
            problems.append("nothing to adopt for %s (no file)" % ", ".join(missing))
    else:
        there = [l for l in langs if l in existing]
        if there:
            problems.append("%s already exist — --adopt to take over a human translation" % ", ".join(there))
    busy = ghstate.slug_busy(root, cfg, slug, exclude=exclude, prs=prs)
    if busy:
        problems.append("another topic is in progress on %s (%s)" % (slug, ", ".join(busy)))
    row = next((r for r in integrity.check(root, cfg, prs=prs)["articles"] if r["slug"] == slug), None)
    if row is None:
        problems.append("%s is not in the Herald article set" % slug)
    elif row["status"] != "ok":
        causes = row.get("causes") or []
        added = {c.split(":", 1)[1] for c in causes if c.startswith("translation_added:")}
        if not (adopt and causes and len(added) == len(causes) and added == set(langs)):
            problems.append("%s does not match its verified record (%s: %s) — `/hrd ship` handles that first"
                            % (slug, row["status"], ", ".join(causes) or "-"))
    if problems:
        raise HeraldError("; ".join(problems))
    return {"ref": ref, "langs": langs, "withdrawn": sorted(withdrawn & set(langs))}


def inherit_state(root, cfg, st, topic):
    """`HRD begin` for a tr- topic: brief..critique ran in the reference topic. Copy its research
    and claims maps, anchor each inherited output to the files as they are now (the check above
    proved they are the verified ones), and start at the claims-map remap (§7 step 4)."""
    import shutil

    slug = topic["translate_of"]
    chk = translate_check(root, cfg, slug, topic.get("languages"), adopt=bool(topic.get("adopt")), exclude=topic["id"])
    ref, tid = chk["ref"], topic["id"]
    os.makedirs(os.path.join(root, work_rel(tid, "")), exist_ok=True)
    for name in os.listdir(os.path.join(root, work_rel(ref, ""))):
        if name in ("research.md", "claims-map.json") or (name.startswith("claims-map.") and name.endswith(".json")):
            shutil.copy2(os.path.join(root, work_rel(ref, name)), os.path.join(root, work_rel(tid, name)))
    src = worktree_hash(root, cfg, slug)
    at = now_iso()
    st["slug"] = slug
    st["inherited_from"] = ref
    st["stages"] = {
        "brief": {"inherited": ref, "outputs": {}, "at": at},
        "research": {"inherited": ref, "outputs": {"research.md": file_hash(root, work_rel(tid, "research.md"))}, "at": at},
        "draft": {"inherited": ref, "outputs": {"@article": src, "claims-map.json": file_hash(root, work_rel(tid, "claims-map.json"))},
                  "at": at},
        "critique": {"inherited": ref, "outputs": {}, "body_hash": src, "at": at},
    }
    langs = chk["langs"]
    st["translation"] = {"langs": langs,
                         "log": [{"at": at, "lang": l, "why": "revive" if l in chk["withdrawn"] else "begin"} for l in langs],
                         "pending": list(langs), "passed": {}, "hashes": {}, "source_hash": None, "round": 0,
                         "last_refusal": None, "enabled_at_begin": True, "remapped": False}
    st["stage"] = "translation"
    return st


def remap(root, cfg, tid, st):
    """`HRD remap`: the fact-checker re-mapped the inherited claims-map.json to the source as it
    stands, with existing claim ids only. Code checks that and re-anchors the map (§7 step 4)."""
    from .store import research_claim_ids

    if not tid.startswith("tr-") or not st.get("inherited_from"):
        raise HeraldError("remap is the first step of a tr- topic only")
    tr = st.get("translation") or {}
    if file_hash(root, work_rel(tid, "research.md")) != st["stages"]["research"]["outputs"].get("research.md"):
        raise HeraldError("research.md changed — a later translation never edits the research")
    sents = entries(root, tid)
    if sents is None:
        raise HeraldError("claims-map.json is missing or malformed")
    known = set(research_claim_ids(root, tid))
    new_ids = sorted({str(c).strip() for s in sents for c in s["claims"]} - known)
    if new_ids:
        raise HeraldError("claims-map.json uses ids research.md does not have: %s — remap to existing claims only; "
                          "a sentence no claim supports is a source defect" % ", ".join(new_ids))
    gone = draft_text_problems(root, cfg, tid, st["slug"])
    if gone:
        raise HeraldError("; ".join(gone))
    st["stages"]["draft"]["outputs"]["claims-map.json"] = file_hash(root, work_rel(tid, "claims-map.json"))
    tr["remapped"] = True
    return st


def missing(root, cfg, langs=None):
    """`/hrd translate --missing`: Herald articles lacking target languages, minus taken-down
    languages, slugs with a topic in flight, and slugs whose last tr- ended in a source defect
    with no refresh published since."""
    from . import ghstate
    from .store import load_published, load_topics

    pub = load_published(root)
    topics = load_topics(root)["topics"]
    prs = ghstate.herald_prs(root, cfg)
    busy = {t["slug"] for t in ghstate.in_progress_topics(root, cfg, prs=prs) if t["slug"]}
    out = []
    for a in pub["articles"]:
        if a.get("origin") != "herald" or a.get("withdrawn") or a["slug"] in busy:
            continue
        defect = max((h.get("at", "") for t in topics if t.get("translate_of") == a["slug"]
                      for h in t.get("history") or [] if h.get("reason") == "source-defect"), default="")
        if defect and defect > str(a.get("published_at", "")):
            continue
        have = set(existing_langs(root, cfg, a["slug"])) | set(a.get("withdrawn_langs") or [])
        want = [l for l in (langs or cfg.target_langs()) if l not in have]
        if want:
            out.append({"slug": a["slug"], "langs": want})
    return out
