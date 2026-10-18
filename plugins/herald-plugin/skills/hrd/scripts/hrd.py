#!/usr/bin/env python3
"""Herald deterministic CLI. Commands (`/hrd ...`) call this for every state change so the
rules in design/herald/00-plan.md are enforced by code, not by prompt text.

Usage: python3 .claude/herald/scripts/hrd.py <group> <action> [...]
Every subcommand prints JSON on success and exits non-zero with a human-readable message on a
failed precondition.
"""

import argparse
import json
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo's .claude/herald/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hrdlib import commits, ghstate, integrity, lock, store  # noqa: E402
from hrdlib.config import Config  # noqa: E402
from hrdlib.hashing import bundle_hash, lang_hash, tree_hash, worktree_hash  # noqa: E402
from hrdlib.util import HeraldError, emit, git, git_ok, now_iso, read_json, repo_root, write_json  # noqa: E402


SCRIPTS_VERSION = "0.13.0"  # == plugin.json version (structure test); SKILL.md compares repo vs plugin


def _vtuple(v):
    """Malformed versions raise — callers must stop and report, not treat them as "older"."""
    from hrdlib.util import version_tuple
    return version_tuple(v)


def cmd_version(a):
    """`--against <plugin version>` compares as dot-separated integers (0.10.0 > 0.9.0):
    `relation` is this repo's scripts relative to the plugin — older | equal | newer."""
    out = {"version": SCRIPTS_VERSION}
    if a.against:
        mine, theirs = _vtuple(SCRIPTS_VERSION), _vtuple(a.against)
        out["relation"] = "equal" if mine == theirs else ("older" if mine < theirs else "newer")
    emit(out)


def ctx(check=True):
    """Repo root and config. `check` refuses a malformed `translations` block (Config.validate);
    the commands needed to repair config — sync, status, the harness commit — pass False
    (design/herald/01-multilingual.md §2)."""
    root = repo_root()
    cfg = Config.load(root)
    if check:
        errors, _ = cfg.validate()
        if errors:
            raise HeraldError("config.json translations is invalid: %s — fix it with /hrd config" % "; ".join(errors))
    return root, cfg


def attended_only(what):
    """Base-branch writers: unattended children never write base (plan §3.2.1) — the batch
    runner does. The guard only sees `git commit`; this covers writes made inside hrd.py."""
    if os.environ.get("HRD_UNATTENDED") == "1":
        raise HeraldError("%s writes the base branch — not allowed in unattended sessions (the batch runner records)" % what)


# --- lock -------------------------------------------------------------------------------------

def cmd_lock(a):
    root = repo_root()
    if a.action == "acquire":
        emit({"token": lock.acquire(root, a.cmd, token=a.token)})
    elif a.action == "release":
        emit({"released": lock.release(root, a.token, command=a.cmd if a.cmd != "cli" else None)})
    elif a.action == "status":
        emit({"lock": lock.status(root)})
    elif a.action == "unlock":
        emit({"removed": lock.force_unlock(root)})


# --- topics -----------------------------------------------------------------------------------

def cmd_topics(a):
    root, cfg = ctx()
    data = store.load_topics(root)
    if a.action == "add":
        incoming = json.load(sys.stdin if a.file in (None, "-") else open(a.file, encoding="utf-8"))
        added = []
        for item in incoming if isinstance(incoming, list) else [incoming]:
            if not item.get("title"):
                raise HeraldError("topic needs a title")
            tid = item.get("id") or store.next_topic_id(data)
            store.check_topic_id(tid)
            if any(t["id"] == tid for t in data["topics"]):
                raise HeraldError("topic %s exists" % tid)
            busy = ghstate.slug_busy(root, cfg, item.get("slug") or item.get("refresh_of") or item.get("translate_of"))
            if busy:  # L16
                raise HeraldError("another topic is in progress on %s (%s) — finish or close it first"
                                  % (item.get("slug") or item.get("refresh_of") or item.get("translate_of"), ", ".join(busy)))
            t = {"id": tid, "title": item["title"], "category": item.get("category"),
                 "keywords": item.get("keywords", []), "angle": item.get("angle", ""),
                 "refresh_of": item.get("refresh_of"), "slug": item.get("slug"),
                 "state": "queued", "reason": None, "reverted_by": [], "history": []}
            if isinstance(item.get("languages"), list):  # a subset of the translation targets (§2)
                t["languages"] = [str(x) for x in item["languages"]]
            if item.get("direction"):  # a saved human change to carry (refresh --direction)
                t["direction"] = str(item["direction"])
            for k in ("translate_of", "adopt", "follows", "refresh_decision"):  # tr- topics, refresh decisions
                if item.get(k):
                    t[k] = item[k]
            store.set_topic_state(t, "queued", note="added")
            data["topics"].append(t)
            added.append(tid)
        store.save_topics(root, data)
        emit({"added": added})
    elif a.action == "list":
        emit([{k: t.get(k) for k in ("id", "title", "category", "state", "reason", "slug")}
              for t in data["topics"] if not a.state or t.get("state") == a.state])
    elif a.action == "show":
        emit(store.get_topic(data, a.topic))


def derived_status(root, cfg):
    data = store.load_topics(root)
    prs = ghstate.herald_prs(root, cfg)
    local = ghstate.local_branches(root)
    out = []
    for t in data["topics"]:
        tid = t["id"]
        mine = [p for p in prs if p["topic_id"] == tid]
        merged = [p for p in mine if p.get("mergedAt") and not (p["label_set"] & {ghstate.REVERTED, ghstate.WITHDRAWN})]
        open_ = [p for p in mine if p["state"] == "OPEN"]
        branches = [b for b in local if b.startswith("herald/%s--" % tid)]
        stored = t.get("state")
        if stored == "withdrawn":
            d = "withdrawn"
        elif stored == "published":
            d = "published"
        elif merged and stored != "published":
            d = "merged-unrecorded"
        elif stored == "unwithdrawn":
            d = "merged-unrecorded"
        elif stored in ("declined", "held"):
            d = "%s:%s" % (stored, t.get("reason"))
        elif open_:
            d = "pr-pending"
        elif branches:
            d = "in-progress"
        else:
            d = stored
        note = ((t.get("history") or [{}])[-1] or {}).get("note")
        out.append({"id": tid, "title": t.get("title"), "stored": stored, "reason": t.get("reason"), "note": note,
                    "derived": d, "open_prs": [p["number"] for p in open_],
                    "merged_prs": [p["number"] for p in merged], "branches": branches})
    return out


def cmd_select(a):
    root, cfg = ctx()
    picked = ghstate.selectable(root, cfg)
    if a.topic:
        if a.topic not in picked:
            raise HeraldError("topic %s is not selectable (needs queued with no open/merged PR or local branch)" % a.topic)
        picked = [a.topic]
    emit(picked[: a.n] if a.n else picked)


def cmd_status(a):
    root, cfg = ctx(check=False)
    try:
        evolve = store.evolve_readiness(root, cfg)
    except Exception as e:  # advisory only — never let a bad signals file break status
        evolve = {"tier": "none", "error": str(e)}
    from hrdlib import refresh
    try:  # old articles whose new article has no link from them yet (02-refresh-decision.md R9)
        pending = refresh.supersede_pending(root, cfg, store.load_published(root))
    except Exception as e:  # noqa: BLE001 — advisory
        pending = [{"error": str(e)}]
    try:  # stale or invalid channel guides (03-social.md S3); absent before social is set up
        from hrdlib import social
        soc = social.status_summary(root, cfg)
    except Exception as e:  # noqa: BLE001 — advisory
        soc = {"error": str(e)}
    out = {"topics": derived_status(root, cfg), "lock": lock.status(root), "evolve": evolve,
           "supersede_pending": pending}
    if soc is not None:
        out["social"] = soc
    emit(out)


# --- work lifecycle -----------------------------------------------------------------------------

def cmd_begin(a):
    """Create work/<id>/state.json on base (untracked; carried onto the branch by `branch`)."""
    root, cfg = ctx()
    store.check_topic_id(a.topic)
    from hrdlib import translation
    try:
        topic = store.get_topic(store.load_topics(root), a.topic)
    except HeraldError:
        topic = {}
    branch = next((b for b in ghstate.local_branches(root) if b.startswith("herald/%s--" % a.topic)), None)
    if branch and not os.path.exists(store.state_path(root, a.topic)) and not a.force:
        # the work lives on its branch (a preserved hold, a batch retry): switch to it, never start over
        emit({"resumed": True, "branch": branch, "note": "state.json is on the branch — `git switch %s`" % branch})
        return
    if os.path.exists(store.state_path(root, a.topic)) and not a.force:
        st = store.load_state(root, a.topic)
        if topic.get("translate_of") and st.get("stage") == "translation":
            # a retry or resume: the source on base may have moved since begin. Compare the committed
            # source only — the working tree may hold this topic's own translations (R2 M-4)
            if tree_hash(root, cfg, "origin/%s" % cfg.base, st["slug"]) != \
                    (st["stages"].get("critique") or {}).get("body_hash"):
                raise HeraldError("base-source-changed: the source on base is not the one this topic translates")
            busy = ghstate.slug_busy(root, cfg, st["slug"], exclude=a.topic)
            if busy:
                raise HeraldError("slug in progress: %s — another topic is working on %s" % (busy[0], st["slug"]))
        emit({"resumed": True, "state": st})
        return
    known = topic.get("refresh_of") or topic.get("slug")
    busy = ghstate.slug_busy(root, cfg, known, exclude=a.topic) if known and not topic.get("translate_of") else []
    if busy:  # L16 again at begin: the queue entry may be older than the other topic
        raise HeraldError("slug in progress: %s — another topic is working on %s" % (busy[0], known))
    st = store.new_state(a.topic, None)
    if topic.get("translate_of"):
        st = translation.inherit_state(root, cfg, st, topic)
    else:
        tr = translation.init_state(root, cfg, topic, slug=topic.get("refresh_of") or topic.get("slug"))
        if tr is not None:  # without translations state.json stays as in 0.8.0
            st["translation"] = tr
    store.save_state(root, a.topic, st)
    try:  # hints of an earlier attempt describe another body
        os.remove(os.path.join(root, store.prose_rel(a.topic)))
    except OSError:
        pass
    emit({"created": store.work_rel(a.topic)})


def cmd_branch(a):
    """After brief: fix the slug and branch from origin/<base> (plan §3.2 branch origin)."""
    root, cfg = ctx()
    try:
        store.check_slug(a.slug)
    except HeraldError as e:
        raise HeraldError("%s — Herald 1.0 supports only lowercase ASCII slugs with single hyphens; "
                          "articles with other slugs cannot be refreshed" % e)
    if "--" in a.slug:
        raise HeraldError("slug must not contain `--`")
    try:
        topic = store.get_topic(store.load_topics(root), a.topic)
    except HeraldError:
        topic = {}
    # slug rules (02-refresh-decision.md R11): a refresh keeps its article's slug, a later
    # translation its source's — on every path, resume included
    fixed = topic.get("refresh_of") or topic.get("translate_of")
    if fixed and a.slug != fixed:
        raise HeraldError("slug mismatch: %s works on %s — call HRD branch with --slug %s" % (a.topic, fixed, fixed))
    name = store.branch_name(a.topic, a.slug)
    if not os.path.exists(store.state_path(root, a.topic)) and git_ok(root, "rev-parse", "--verify", "-q", "refs/heads/" + name):
        # the work (and its state.json) lives on the branch: a preserved hold, a retry (R4 MJ-1)
        git(root, "switch", "-q", name)
        busy = ghstate.slug_busy(root, cfg, a.slug, exclude=a.topic)
        if busy:  # L16 on the main resume path too (R5 MN-1)
            raise HeraldError("slug in progress: %s — another topic is working on %s" % (busy[0], a.slug))
        emit({"branch": name, "resumed": True})
        return
    busy = ghstate.slug_busy(root, cfg, a.slug, exclude=a.topic)
    if busy:  # L16: one topic in flight per slug in a translation repo
        raise HeraldError("slug in progress: %s — another topic is working on %s; hold this one cannibalization "
                          "with the note `tooling: slug in progress: %s`" % (busy[0], a.slug, busy[0]))
    if not fixed and not git_ok(root, "rev-parse", "--verify", "-q", "refs/heads/" + name):
        git(root, "fetch", "-q", "origin", cfg.base)  # judge against base as it is now, not at preflight
        used = _slug_in_use(root, cfg, a.slug)
        if used:  # a new article never takes a slug something lives at (R11)
            raise HeraldError("slug used: %s (%s) — ask the strategist for another slug" % (a.slug, used))
    st = store.load_state(root, a.topic)
    st["slug"] = a.slug
    store.save_state(root, a.topic, st)
    name = store.branch_name(a.topic, a.slug)
    git(root, "fetch", "-q", "origin", cfg.base)
    if git_ok(root, "rev-parse", "--verify", "-q", "refs/heads/" + name):
        git(root, "switch", "-q", name)
    else:
        git(root, "switch", "-q", "-c", name, "origin/%s" % cfg.base)
    emit({"branch": name})


def _slug_in_use(root, cfg, slug):
    """Why a new article may not take `slug`, or None: a current Herald article (published or
    merged-unrecorded), an external article not withdrawn, or any file of that slug's bundle on
    origin/<base>. A withdrawn slug and a moved-away old slug stay reusable (00-plan §3.2.1)."""
    try:
        if slug in ghstate.herald_set(root, cfg):
            return "a Herald article"
    except Exception as e:  # noqa: BLE001 — gh down: refuse rather than guess
        raise HeraldError("gh unavailable (%s) — hold cannibalization with `tooling: gh unavailable`" % e)
    art = store.find_article(store.load_published(root), slug)
    if art and art.get("origin") != "herald" and not art.get("withdrawn"):
        return "an external article"
    for p in [cfg.body_path(slug)] + list(cfg.translation_paths(slug).values()):
        if git_ok(root, "cat-file", "-e", "origin/%s:%s" % (cfg.base, p)):
            return "a file on %s: %s" % (cfg.base, p)
    return None


def cmd_refresh_decision(a):
    """02-refresh-decision.md §2: precheck / check / decide / signal."""
    from hrdlib import refresh

    root, cfg = ctx()
    if a.precheck:
        out = refresh.precheck(root, cfg, a.slug, for_translation=a.for_translation)
        emit(out)
        if not out["choices"]:
            sys.exit(1)
    elif a.check:
        pc = refresh.precheck(root, cfg, a.slug, for_translation=a.for_translation, clear=False)
        rec, problems = refresh.check(root, cfg, a.slug, pc["choices"])
        emit({"ok": not problems, "problems": problems, "recommendation": (rec or {}).get("recommendation"),
              "choices": pc["choices"]})
        if problems:
            sys.exit(1)
    elif a.decide:
        attended_only("`refresh-decision --decide`")
        emit(refresh.decide(root, cfg, a.slug, a.decide, source=a.source, direction=a.direction,
                            for_translation=a.for_translation, override_reason=a.override_reason,
                            topic=refresh.load_topic_file(a.topic_file)))
    elif a.signal:
        emit(refresh.signal(root, cfg, a.slug))
    else:
        raise HeraldError("one of --precheck, --check, --decide, --signal")


def cmd_stage(a):
    root, cfg = ctx()
    st = store.load_state(root, a.topic)
    if a.action == "check":
        problems = store.entry_check(root, cfg, st, a.stage)
        emit({"ok": not problems, "problems": problems})
        if problems:
            sys.exit(1)
    elif a.action == "pass":
        st = store.stage_pass(root, cfg, a.topic, a.stage, amend=a.amend)
        emit({"stage": st["stage"], "verified_hash": st.get("verified_hash")})


def cmd_loopback(a):
    """Back to draft. A counted loopback names its cause and records the signal itself, so
    growth evidence never depends on a separate call being remembered."""
    root, cfg = ctx()
    if a.human == bool(a.cause):
        raise HeraldError("give exactly one of --cause %s or --human" % "|".join(store.LOOPBACK_CAUSES))
    if a.cause in ("revise", "audit") and a.theme not in store.THEMES:
        raise HeraldError("--cause %s needs --theme, one of: %s" % (a.cause, ", ".join(store.THEMES)))
    if a.theme and a.cause not in ("revise", "audit"):
        raise HeraldError("--theme applies only to --cause revise|audit")
    if a.claims and a.cause != "research":
        raise HeraldError("--claims applies only to --cause research")
    st = store.load_state(root, a.topic)
    if store.open_research_fix(st):
        raise HeraldError("a research fix is open (%s) — the researcher runs first (`atoms/_stages.md` § research); "
                          "a human's direction goes to the researcher with it"
                          % ", ".join(store.open_research_fix(st).get("claims") or []))
    ver = store.current_verify(root, cfg, a.topic, st)
    if a.cause == "verify" and store.research_suspects(ver):
        raise HeraldError("verify.json lists research_suspects (%s) — the researcher rechecks them first: "
                          "`HRD loopback --cause research --claims %s`"
                          % (", ".join(store.research_suspects(ver)), ",".join(store.research_suspects(ver))))
    fix = None
    if a.cause == "research":
        claims, ids = store.research_fix_claims(root, cfg, a.topic, st, a.claims)
        fix = {"claims": claims, "ids_before": ids, "status": "open", "at": now_iso(),
               "verify_blob": store._verify_blob(root, a.topic),
               "research_before": store.artifact_hash(root, cfg, st, "research.md"),
               "suspects": [dict(s, claim=s["claim"].strip()) for s in ver["research_suspects"]][:20]}
    reader = a.cause == "revise" and bool(store.reader_blockers(root, cfg, a.topic, st))
    if reader and store.reader_round_used(st):
        raise HeraldError("reader.json lists blocking reader-pass problems, but readability can no longer send this "
                          "article back (its one send-back is used, or the loopback budget is spent) — move them "
                          "to `notes` in reader.json (the editor's verdict stands), then go on")
    if (st.get("trim") or {}).get("status") == "open":
        raise HeraldError("a trim is open — `HRD trim --topic %s --abort` first (it restores the article)" % a.topic)
    if a.cause == "audit" and store._int(st.get("audit_rounds")) >= store.AUDIT_ROUND_CAP:
        raise HeraldError("no audit loopback on the last audit round: a MAJOR is deferred, a BLOCKER is held "
                          "needs-human (a human-directed fix uses --human)")
    langs = [x.strip() for x in (a.lang or "").split(",") if x.strip()]
    if a.topic.startswith("tr-") and not (a.cause == "translation" or (a.human and langs)):
        raise HeraldError("a tr- topic has no draft: only `--cause translation` or `--human --lang` — a defect in the "
                          "source holds source-defect (then `/hrd refresh`)")
    if langs and not (a.cause == "translation" or a.human):
        raise HeraldError("--lang applies only to --cause translation or --human")
    if a.cause == "translation" or (a.human and langs):
        return _translation_loopback(root, cfg, a, st, ver, langs)
    if st.get("translation"):  # another cause breaks a run of translation loopbacks
        st["translation"].pop("last_loopback_langs", None)
        st["translation"].pop("last_loopback_stage", None)
    # the accuracy reserve: past the shared cap, one more loopback for a fact the article got wrong
    reserve = (not a.human and store._int(st.get("loopbacks")) >= store.LOOP_CAP and not st.get("accuracy_reserve")
               and a.cause in ("verify", "research") and store.accuracy_gap(ver))
    if not a.human:
        st["loopbacks"] = int(st.get("loopbacks", 0)) + 1
    st["last_loopback"] = "human" if a.human else a.cause
    if reader:
        st["reader_revise"] = True
    if reserve:
        st["accuracy_reserve"] = True
    st["stage"] = "draft"
    if fix:  # the researcher corrects the claims first; draft, critique and verify follow
        st.setdefault("research_fixes", []).append(fix)
        st["stage"] = "research"
        st["verified_hash"] = None  # what verify vouched for rested on the claims being corrected
    store.save_state(root, a.topic, st)
    n = st["loopbacks"]
    # signals below are best-effort: the loopback is already counted and must not be retried
    kind = store.LOOPBACK_CAUSES.get(a.cause)
    if a.cause == "verify":  # a trim that was tried on this very verify result already recorded the gap
        ver = store.safe_machine(root, a.topic, "verify.json")
        if ver.get("body_hash") and (st.get("trim") or {}).get("base_hash") == ver.get("body_hash"):
            kind = None
    if kind:  # gate failures are recorded by `stage pass` where they happen
        data = {"note": (a.note or "")[:500], "loopback": n}
        if a.theme:
            data["theme"] = a.theme
        if fix:
            data["claims"] = fix["claims"]
        if reserve:
            data["accuracy_reserve"] = True
        if reader:
            data["reader"] = True
        if a.cause == "verify":  # counts only from a verify.json about this very article
            ver = store.safe_machine(root, a.topic, "verify.json")
            counts = ver.get("counts")
            try:
                current = st.get("slug") and ver.get("body_hash") == bundle_hash(root, cfg, st["slug"])
                gap = isinstance(counts, dict) and not store.verify_passed(ver)
            except Exception:  # noqa: BLE001 — malformed counts: leave them out
                current = gap = False
            if current and gap:
                data["counts"] = counts
        store.safe_signal(root, kind, a.topic, data)
    if a.cause == "audit":
        store.record_dismissals(root, a.topic, store.safe_machine(root, a.topic, "critique.json"))
    # the retry tier bump (contract §E); past the cap only for the accuracy reserve
    escalate = not a.human and (2 <= n <= store.LOOP_CAP or reserve)
    if escalate:
        store.safe_signal(root, "escalation", a.topic, {"loopback": n, "cause": a.cause})
    emit({"loopbacks": n, "cap": store.LOOP_CAP, "exhausted": n > store.LOOP_CAP and not reserve,
          "accuracy_reserve": bool(reserve), "escalate_tier": escalate, "stage": st["stage"]})


def _translation_loopback(root, cfg, a, st, ver, langs):
    """Back to the translation stage for some languages (01-multilingual.md §4, L9): counted like
    any loopback unless --human, shares the cap and the accuracy reserve; the same language twice
    in a row reports `stagnation` (the caller holds)."""
    from hrdlib import translation

    if a.cause == "translation" and store.research_suspects(ver):
        raise HeraldError("verify.json lists research_suspects — `HRD loopback --cause research` first")
    if a.human:
        attended_only("`loopback --human --lang`")  # uncounted: only a human may ask for it
    reserve = (not a.human and store._int(st.get("loopbacks")) >= store.LOOP_CAP and not st.get("accuracy_reserve")
               and store.accuracy_gap(ver))
    new, stagnant = translation.loopback(root, cfg, st, langs, ver, human=a.human)
    if not a.human:
        st["loopbacks"] = int(st.get("loopbacks", 0)) + 1
    st["last_loopback"] = "human" if a.human else "translation"
    if reserve:
        st["accuracy_reserve"] = True
    store.save_state(root, a.topic, st)
    n = st["loopbacks"]
    if not a.human:
        store.safe_signal(root, "verify-gap", a.topic, {"note": (a.note or "")[:500], "loopback": n,
                                                        "cause": "translation", "langs": new})
    escalate = not a.human and (2 <= n <= store.LOOP_CAP or reserve)
    if escalate:
        store.safe_signal(root, "escalation", a.topic, {"loopback": n, "cause": "translation"})
    emit({"loopbacks": n, "cap": store.LOOP_CAP, "exhausted": n > store.LOOP_CAP and not reserve,
          "accuracy_reserve": bool(reserve), "escalate_tier": escalate, "stage": "translation",
          "langs": new, "stagnation": stagnant})


def cmd_remap(a):
    from hrdlib import translation

    root, cfg = ctx()
    st = store.load_state(root, a.topic)
    st = translation.remap(root, cfg, a.topic, st)
    store.save_state(root, a.topic, st)
    emit({"remapped": True, "stage": st["stage"]})


def cmd_translate(a):
    """`/hrd translate` helpers: `check` (preconditions of one tr- topic) and `missing`."""
    from hrdlib import translation

    root, cfg = ctx()
    langs = [x.strip() for x in (a.lang or "").split(",") if x.strip()] or None
    if a.action == "check":
        if not a.slug:
            raise HeraldError("check needs --slug")
        emit(translation.translate_check(root, cfg, a.slug, langs, adopt=a.adopt))
    else:
        emit({"articles": translation.missing(root, cfg, langs)})


def cmd_config_check(a):
    """Config.validate's errors and warnings (`/hrd config` runs it after an edit)."""
    root, cfg = ctx(check=False)
    errors, warnings = cfg.validate()
    emit({"ok": not errors, "errors": errors, "warnings": warnings})
    if errors:
        sys.exit(1)


def cmd_audit_round(a):
    root, cfg = ctx()
    emit(store.audit_round(root, cfg, a.topic))


def cmd_finalize(a):
    """publish entry: lock agent_final_hash once (never rewritten)."""
    root, cfg = ctx()
    st = store.load_state(root, a.topic)
    problems = store.entry_check(root, cfg, st, "publish")
    if problems:
        raise HeraldError("; ".join(problems))
    if not st.get("agent_final_hash"):
        st["agent_final_hash"] = st["verified_hash"]
    st["stage"] = "publish"
    store.save_state(root, a.topic, st)
    emit({"agent_final_hash": st["agent_final_hash"]})


RESULT_STATUSES = {"pr-open", "merged"} | {"held:%s" % r for r in
                                          ("cannibalization", "research", "rejected", "needs-human", "stagnation", "budget",
                                           "source-defect")}


def cmd_result(a):
    """Batch child result file (memory/batch/<id>.json) — children never write base."""
    root = repo_root()
    if a.status not in RESULT_STATUSES:
        raise HeraldError("unknown result status %r (one of: %s)" % (a.status, ", ".join(sorted(RESULT_STATUSES))))
    path = os.path.join(store.paths(root)["memory"], "batch", a.topic + ".json")
    write_json(path, {"status": a.status, "pr": a.pr, "note": a.note, "merged": a.merged or [], "at": now_iso()})
    emit({"written": path})


# --- hashes / ledger / scope ----------------------------------------------------------------------

def cmd_hash(a):
    """Default: the bundle (source + translations) — what verify, the ledger and ship compare.
    `--source`: body + images (critique, the editor's reader pass). `--lang`: one language's
    file (`verify.json` by_lang). Design: 01-multilingual.md §3."""
    root, cfg = ctx()
    if a.lang:
        h = lang_hash(root, cfg, a.slug, a.lang, rev=a.rev)
    elif a.source:
        h = tree_hash(root, cfg, a.rev, a.slug) if a.rev else worktree_hash(root, cfg, a.slug)
    else:
        h = bundle_hash(root, cfg, a.slug, rev=a.rev)
    emit({"hash": h})


def cmd_ledger(a):
    root, cfg = ctx()
    if a.action == "record":
        emit(store.ledger_record(root, cfg, a.topic, sha=a.sha, kind=a.kind, rev=a.rev))
    else:
        emit(store.ledger_latest(root, a.topic))


def cmd_scope(a):
    root, cfg = ctx()
    st = store.read_json_at(root, a.rev, store.work_rel(a.topic, "state.json")) if a.rev != "HEAD" else store.load_state(root, a.topic)
    slug = a.slug or (st or {}).get("slug")
    if not slug:
        raise HeraldError("slug unknown for %s" % a.topic)
    led = store.ledger_latest(root, a.topic) or {}
    res = commits.scope_check(root, cfg, a.topic, slug, rev=a.rev, herald_sha=led.get("sha"))
    emit(res)
    if not res["ok"]:
        sys.exit(1)


def cmd_premerge(a):
    """ship §3/§5: checks on a PR head before merging when the repo translates
    (01-multilingual.md §5). Exit 1 with `problems` → do not merge this PR."""
    from hrdlib import translation

    root, cfg = ctx()
    problems = translation.premerge_problems(root, cfg, a.topic, a.rev)
    emit({"ok": not problems, "problems": problems})
    if problems:
        sys.exit(1)


def cmd_ahead(a):
    root, cfg = ctx()
    rows = commits.classify_ahead(root, cfg, cfg.base)
    emit({"commits": rows, "needs_human": [r for r in rows if not r["ok"]]})


def cmd_sync(a):
    root, cfg = ctx(check=False)
    emit({"sync": commits.sync_base(root, cfg, allow_merge=os.environ.get("HRD_UNATTENDED") != "1")})


def cmd_fetch_pr(a):
    """Bring a PR head (possibly pushed by a human) into refs/remotes/origin/pr-<n>."""
    root, cfg = ctx()
    ref = "refs/remotes/origin/pr-%d" % a.pr
    git(root, "fetch", "-q", "origin", "+pull/%d/head:%s" % (a.pr, ref))
    emit({"ref": ref, "sha": git(root, "rev-parse", ref).strip()})


def cmd_commit(a):
    root, cfg = ctx(check=a.cmd != "harness")
    attended_only("`commit`")
    sha = commits.commit_state(root, cfg, a.cmd, a.message, a.kind, a.paths, extra_trailers=a.trailer or ())
    emit({"commit": sha})


def cmd_integrity(a):
    root, cfg = ctx()
    rep = integrity.predeploy(root, cfg) if a.predeploy else integrity.check(root, cfg, rev=a.rev)
    if not a.predeploy:
        # rows that need nothing (ok and recorded) are counted, not listed: the list grows with the
        # site and enters the session's context; ok + merged_unrecorded rows stay (ship's deploy set)
        keep = [r for r in rep["articles"] if r["status"] != "ok" or r.get("merged_unrecorded")]
        rep["ok_count"] = len(rep["articles"]) - len(keep)
        rep["articles"] = keep
    emit(rep)
    if not rep["ok"] and not a.report:
        sys.exit(1)


def cmd_residue(a):
    root, cfg = ctx()
    dirs = integrity.ignored_residue(root, cfg)
    if a.clean:
        for d in dirs:
            git(root, "clean", "-q", "-fdX", "--", d)
    emit({"residue": dirs, "cleaned": bool(a.clean)})


def cmd_herald_set(a):
    root, cfg = ctx()
    emit(ghstate.herald_set(root, cfg))


def cmd_reverts(a):
    root, cfg = ctx()
    topics = store.load_topics(root)
    pending = ghstate.pending_removal_reverts(root, cfg, topics)
    if a.action == "apply":
        attended_only("`reverts apply`")
        prs = ghstate.herald_prs(root, cfg)
        for rv in pending:
            for p in prs:
                if p["topic_id"] == rv["topic_id"] and p.get("mergedAt"):
                    ghstate.add_label(root, p["number"], ghstate.REVERTED)
            t = store.get_topic(topics, rv["topic_id"])
            store.set_topic_state(t, "held", "reverted", "revert PR #%d" % rv["number"])
            t.setdefault("reverted_by", []).append(rv["number"])
        store.save_topics(root, topics)
    emit({"pending": [{"topic_id": p["topic_id"], "pr": p["number"]} for p in pending],
          "applied": a.action == "apply"})


# --- stored-state transitions ----------------------------------------------------------------------

def cmd_state(a):
    root, cfg = ctx()
    attended_only("`state`")
    data = store.load_topics(root)
    t = store.get_topic(data, a.topic)
    if t.get("state") == "published" and a.state in ("queued", "held"):
        raise HeraldError("%s is already published — a removal revert (ship step 2, held:reverted) or `withdraw` changes that, not `state`" % a.topic)
    store.set_topic_state(t, a.state, a.reason, a.note)
    store.save_topics(root, data)
    # holds and ship declines are growth signals; record them where the state changes
    # (the batch runner records its own holds)
    # (not for holds caused by a human's change — a failed re-verify after their push, a revert)
    # (nor tooling stops or a human's own choice: note "tooling: …" / "human: …")
    if a.state == "held" and a.reason not in ("verify-after-human-edit", "reverted") \
            and not str(a.note or "").startswith(store.NON_SIGNAL_HOLD_NOTES):
        store.safe_signal(root, "hold", t["id"], {"reason": a.reason, "note": a.note, "by": "session"})
    elif a.state == "declined":
        store.safe_signal(root, "ship-decline", t["id"], {"reason": a.reason, "note": a.note})
    emit({"id": t["id"], "state": t["state"], "reason": t["reason"]})


def _article_present(root, cfg, slug):
    """Any part of the bundle still on base: the body, tracked images, or a translation."""
    return os.path.exists(os.path.join(root, cfg.body_path(slug))) or \
        any(os.path.exists(os.path.join(root, p)) for p in cfg.translation_paths(slug).values()) or \
        os.path.isdir(os.path.join(root, cfg.image_dir(slug))) and bool(
            git(root, "ls-files", "--", cfg.image_dir(slug)).strip())


def cmd_requeue(a):
    root, cfg = ctx()
    attended_only("`requeue`")
    data = store.load_topics(root)
    t = store.get_topic(data, a.topic)
    if t["state"] not in ("held", "declined"):
        raise HeraldError("only held/declined topics can be requeued (state: %s)" % t["state"])
    busy = ghstate.slug_busy(root, cfg, t.get("slug") or t.get("refresh_of") or t.get("translate_of"), exclude=a.topic)
    if busy:
        raise HeraldError("another topic is in progress on this slug (%s) — finish or close it first" % ", ".join(busy))
    for b in ghstate.local_branches(root):
        if b.startswith("herald/%s--" % a.topic):
            git(root, "branch", "-q", "-D", b)
    t.pop("auto_merged_pr", None)  # a new PR will be judged on its own
    t.pop("auto_merged_at", None)
    if a.direction:  # a human's change saved at decline (01-multilingual.md §5): brief/draft read it
        rel = os.path.join(".claude", "herald", "memory", "directions", "%s.diff" % a.topic)
        if not os.path.isfile(os.path.join(root, rel)):
            raise HeraldError("no saved direction %s" % rel)
        t["direction"] = rel
    store.set_topic_state(t, "queued", note="requeued (reverted_by kept)")
    store.save_topics(root, data)
    emit({"id": a.topic, "state": "queued", "reverted_by": t.get("reverted_by", [])})


def cmd_drop(a):
    root, cfg = ctx()
    attended_only("`drop`")
    data = store.load_topics(root)
    t = store.get_topic(data, a.topic)
    t["dropped"] = True
    store.set_topic_state(t, "declined", "dropped", a.note)
    store.save_topics(root, data)
    emit({"id": a.topic, "state": "declined:dropped"})


def _topic_articles(pub, prs, slug):
    """All topic ids merged under this article (aliases included)."""
    art = store.find_article(pub, slug)
    tids = set()
    if art:
        tids.add(art.get("current_topic_id"))
        for m in art.get("moved_from") or []:
            tids.update(m.get("topic_ids") or [])
    tids |= {p["topic_id"] for p in prs if p.get("mergedAt") and p["slug"] == slug}
    tids.discard(None)
    return art, tids


def cmd_withdraw(a):
    root, cfg = ctx()
    attended_only("`withdraw`")
    pub = store.load_published(root)
    slug = a.slug_or_topic
    art = store.find_article(pub, slug) or store.find_article_by_topic(pub, slug)
    if not art:
        raise HeraldError("no published article %s" % slug)
    slug = art["slug"]
    if _article_present(root, cfg, slug):
        raise HeraldError("the body, tracked images or a translation of %s still exist on base — withdraw only after the human removed them "
                          "(to change the slug use `status --move`; to fix content use exit ①/②)" % slug)
    # Without a pathspec git can pair the rename (with one, the other side is out of scope and
    # it reports a delete) — look for any rename whose source is this body or image dir.
    since = ["--since=%s" % art["published_at"]] if art.get("published_at") else []
    renames = git(root, "log", "-M", "--diff-filter=R", "--name-status", "--format=", *since).splitlines()
    img = cfg.image_dir(slug) + "/"
    renamed = [l for l in renames if l.startswith("R") and len(l.split("\t")) == 3
               and (l.split("\t")[1] == cfg.body_path(slug) or l.split("\t")[1].startswith(img))]
    if renamed:
        raise HeraldError("git shows %s was renamed — use `status --move`, not withdraw" % slug)
    prs = ghstate.herald_prs(root, cfg)
    _, tids = _topic_articles(pub, prs, slug)
    for p in prs:
        if p.get("mergedAt") and p["topic_id"] in tids:
            ghstate.add_label(root, p["number"], ghstate.WITHDRAWN)
    art.update({"withdrawn": True, "withdrawn_at": now_iso(), "withdrawn_topics": sorted(tids)})
    for x in pub["articles"]:  # an old article no longer points at a withdrawn new one (R9)
        if (x.get("superseded") or {}).get("by") == slug:
            x.pop("superseded", None)
    # (the withdrawn entry keeps its own refresh history for unwithdraw; record_published clears
    # it when another topic reuses the slug)
    data = store.load_topics(root)
    for t in data["topics"]:
        if t["id"] in tids:
            store.set_topic_state(t, "withdrawn", note=a.note)
    store.save_published(root, pub)
    store.save_topics(root, data)
    emit({"withdrawn": slug, "topics": sorted(tids)})


def cmd_unwithdraw(a):
    root, cfg = ctx()
    attended_only("`unwithdraw`")
    pub = store.load_published(root)
    art = store.find_article(pub, a.slug_or_topic) or store.find_article_by_topic(pub, a.slug_or_topic)
    if not art or not art.get("withdrawn"):
        raise HeraldError("no withdrawn article %s" % a.slug_or_topic)
    if not os.path.exists(os.path.join(root, cfg.body_path(art["slug"]))):
        raise HeraldError("restore the body on base first")
    tids = set(art.get("withdrawn_topics") or [])
    for p in ghstate.herald_prs(root, cfg):
        if p["topic_id"] in tids and ghstate.WITHDRAWN in p["label_set"]:
            ghstate.remove_label(root, p["number"], ghstate.WITHDRAWN)
    art["withdrawn"] = False
    data = store.load_topics(root)
    from hrdlib import refresh
    for t in data["topics"]:  # any topic of this article that followed an old one (R9)
        if t["id"] in tids and t.get("follows"):
            refresh.link_superseded(pub, t["follows"], art["slug"])
    for t in data["topics"]:
        if t["id"] in tids:
            store.set_topic_state(t, "unwithdrawn", note="restored; next ship re-checks and deploys")
    store.save_published(root, pub)
    store.save_topics(root, data)
    emit({"unwithdrawn": art["slug"]})


def cmd_move(a):
    root, cfg = ctx()
    attended_only("`move`")
    store.check_slug(a.new_slug)
    pub = store.load_published(root)
    art = store.find_article_by_topic(pub, a.topic) or store.find_article(pub, a.topic)
    if not art:
        raise HeraldError("`move` needs a published article (merged-unrecorded: move the files back and run ship)")
    old = art["slug"]
    if art.get("translations") or any(os.path.exists(os.path.join(root, p)) for p in
                                      list(cfg.translation_paths(old).values()) + list(cfg.translation_paths(a.new_slug).values())):
        raise HeraldError("moving an article with translations is not supported (01-multilingual.md §5) — "
                          "`status --withdraw-lang` each language, move, then `/hrd translate`")
    if os.path.exists(os.path.join(root, cfg.body_path(old))):
        raise HeraldError("old path %s still exists" % cfg.body_path(old))
    if not os.path.exists(os.path.join(root, cfg.body_path(a.new_slug))):
        raise HeraldError("new path %s does not exist" % cfg.body_path(a.new_slug))
    if os.path.isdir(os.path.join(root, cfg.image_dir(old))) and git(root, "ls-files", "--", cfg.image_dir(old)).strip():
        raise HeraldError("tracked images still under %s — move them too" % cfg.image_dir(old))
    prs = ghstate.herald_prs(root, cfg)
    _, tids = _topic_articles(pub, prs, old)
    art.setdefault("moved_from", []).append({"slug": old, "moved_at": now_iso(),
                                             "moved_at_commit": git(root, "rev-parse", "HEAD").strip(),
                                             "topic_ids": sorted(tids)})
    for x in pub["articles"]:  # an old article's link follows the new article's move (R9)
        if (x.get("superseded") or {}).get("by") == old:
            x["superseded"]["by"] = a.new_slug
    art["slug"] = a.new_slug
    art["path"] = cfg.body_path(a.new_slug)
    art["url"] = cfg.article_url(a.new_slug)
    store.save_published(root, pub)
    # re-verification on base reads work/<tid>/state.json's slug — point it at the new path
    updated = []
    for tid in sorted(tids):
        sp = store.state_path(root, tid)
        st = read_json(sp)
        if st and st.get("slug") == old:
            st["slug"] = a.new_slug
            write_json(sp, st)
            updated.append(store.work_rel(tid, "state.json"))
    emit({"moved": old, "to": a.new_slug, "topic_ids": sorted(tids), "state_files": updated,
          "note": "commit published.json and the state files; next ship re-verifies (path is part of the hash)"})


def cmd_withdraw_lang(a):
    """Take one translation down (01-multilingual.md §5): the file is already gone from base;
    the rest of the bundle must be exactly what was verified, file by file, so nothing else can
    ride along. Updates the reference topic's committed state (verified_hash, verified_files,
    withdrawn_langs) and published.json; the caller commits them, then records the ledger line
    with `integrity.py --record --kind withdraw-lang`."""
    from hrdlib.hashing import bundle_files, bundle_hash, digest_files

    root, cfg = ctx()
    attended_only("`withdraw-lang`")
    lang = a.lang
    if lang not in cfg.target_langs():
        raise HeraldError("%s is not a translation target" % lang)
    pub = store.load_published(root)
    art = store.find_article(pub, a.slug)
    if not art or art.get("origin") != "herald":
        raise HeraldError("no Herald article %s" % a.slug)
    slug = art["slug"]
    if os.path.exists(os.path.join(root, cfg.body_path(slug, lang))):
        raise HeraldError("remove %s from base first" % cfg.body_path(slug, lang))
    prs = ghstate.herald_prs(root, cfg)
    busy = [t for t in ghstate.in_progress_topics(root, cfg, prs=prs) if t["slug"] == slug]
    if busy:
        raise HeraldError("%s has a topic in progress (%s) — finish or close it first: its verify covers the bundle "
                          "with this language" % (slug, ", ".join(t["id"] for t in busy)))
    ref = ghstate.herald_set(root, cfg, prs=prs, pub=pub).get(slug, {}).get("ref_topic")
    if not ref:
        raise HeraldError("no reference topic for %s" % slug)
    st = store.load_state(root, ref)
    path = cfg.body_path(slug, lang)
    # the committed tree decides: a deletion that is not committed is not a withdrawal (R2 M-5')
    if git(root, "ls-tree", "--name-only", "HEAD", "--", path).strip():
        raise HeraldError("%s is still in HEAD — commit its removal first" % path)
    cur = bundle_files(root, cfg, slug, rev="HEAD")
    already = lang in (st.get("withdrawn_langs") or []) and \
        {p: v["blob"] for p, v in (st.get("verified_files") or {}).items()} == {p: v["blob"] for p, v in cur.items()}
    if not already:
        trial = dict(st, withdrawn_langs=sorted(set(st.get("withdrawn_langs") or []) | {lang}))
        problem = store.withdraw_lang_proof(root, cfg, ref, trial, "HEAD") if store.ledger_latest(root, ref) else None
        if problem is None and not store.ledger_latest(root, ref):
            # no ledger line here: the committed record only (R4 MN-1)
            head_st = store.read_json_at(root, "HEAD", store.work_rel(ref, "state.json")) or {}
            if head_st != st:
                raise HeraldError("work/%s/state.json differs from HEAD — commit or discard that edit first" % ref)
            basis = head_st.get("verified_files") or {}
            if path not in basis:
                problem = "%s was not part of the verified bundle" % path
            elif {p: v["blob"] for p, v in basis.items() if p != path} != {p: v["blob"] for p, v in cur.items()}:
                problem = "the bundle differs from what was verified beyond removing %s — re-verify or restore" % lang
        if problem:
            raise HeraldError(problem)
        st["verified_hash"] = bundle_hash(root, cfg, slug, rev="HEAD")
        st["verified_files"] = cur
        st["withdrawn_langs"] = trial["withdrawn_langs"]
        if st.get("stages", {}).get("verify"):
            st["stages"]["verify"]["body_hash"] = st["verified_hash"]
        tr = st.get("translation")
        if tr and lang in (tr.get("langs") or []):
            # the topic no longer carries that language: a later re-verify must not look for it (R2 M-2)
            tr["langs"] = [l for l in tr["langs"] if l != lang]
            (tr.get("hashes") or {}).pop(lang, None)
            tr.setdefault("log", []).append({"at": now_iso(), "lang": lang, "why": "withdraw"})
            st.setdefault("stages", {}).setdefault("translation", {}).setdefault("outputs", {})["@translations"] = \
                store.artifact_hash(root, cfg, st, "@translations")
        store.save_state(root, ref, st)
        (art.get("translations") or {}).pop(lang, None)
        art["withdrawn_langs"] = sorted(set(art.get("withdrawn_langs") or []) | {lang})
        store.save_published(root, pub)
    emit({"withdrawn_lang": lang, "slug": slug, "ref_topic": ref, "already_applied": already,
          "verified_hash": st.get("verified_hash"),
          "commit": [] if already else [store.work_rel(ref, "state.json"), ".claude/herald/published.json"],
          "next": "commit these (HRD commit --cmd status) unless already_applied, then integrity.py --record --topic %s "
                  "--kind withdraw-lang (no --sha: the record names HEAD)" % ref})


def cmd_release_slug(a):
    root, cfg = ctx()
    attended_only("`release-slug`")
    pub = store.load_published(root)
    slug = a.slug
    if slug in ghstate.herald_set(root, cfg, pub=pub):
        raise HeraldError("%s is a current Herald article — release applies only to withdrawn or moved-away slugs" % slug)
    known = any(x.get("withdrawn") and x["slug"] == slug for x in pub["articles"]) or \
        any(m["slug"] == slug for x in pub["articles"] for m in x.get("moved_from") or [])
    if not known:
        raise HeraldError("%s is neither withdrawn nor a moved-away slug" % slug)
    rel = {"slug": slug, "at": now_iso(), "content_hash": bundle_hash(root, cfg, slug)}
    pub["releases"] = [r for r in pub.get("releases", []) if r["slug"] != slug] + [rel]
    if not store.find_article(pub, slug):
        pub["articles"].append({"slug": slug, "path": cfg.body_path(slug), "origin": "external",
                                "url": cfg.article_url(slug), "published_at": now_iso()})
    store.save_published(root, pub)
    emit(rel)


def cmd_mark_published(a):
    """External publish record (`status --mark-published`, `ship --deploy-only`): URL checked by caller."""
    root, cfg = ctx()
    attended_only("`mark-published`")
    prs = ghstate.herald_prs(root, cfg)
    if any(p["topic_id"] == a.topic and p.get("mergedAt") for p in prs):
        raise HeraldError("%s has a merged Herald PR — use `ship`, not an external record" % a.topic)
    store.record_published(root, cfg, a.topic, a.slug, origin="external")
    emit({"published": a.slug, "origin": "external"})


def cmd_record_published(a):
    """ship step 9 for one Herald article (URL already confirmed)."""
    root, cfg = ctx()
    attended_only("`record-published`")
    art = store.record_published(root, cfg, a.topic, a.slug, pr=a.pr, auto=a.auto)
    out = {"published": a.slug, "human_reviewed": art.get("human_reviewed")}
    if cfg.translations():
        # per published entry: ship §9 records human-edit signals with each one's own value
        out["entries"] = {}
        if not a.topic.startswith("tr-"):
            out["entries"][cfg.source_lang()] = art.get("human_reviewed")
        for lang in store._published_langs(root, cfg, a.topic, store.get_topic(store.load_topics(root), a.topic)):
            out["entries"][lang] = (art.get("translations") or {}).get(lang, {}).get("human_reviewed")
        out["urls"] = store.bundle_urls(root, cfg, a.slug)
    emit(out)


def cmd_auto_merged(a):
    root, _ = ctx()
    attended_only("`auto-merged`")
    if a.clear == (a.pr is not None):
        raise HeraldError("give exactly one of --pr <n> or --clear")
    if (a.rev or a.consent or a.sha) and a.clear:
        raise HeraldError("--rev/--consent/--sha go with --pr")
    accepted = []
    if a.pr is not None:  # recomputed here at the PR head, never taken from the caller
        if not a.rev or not a.sha:
            raise HeraldError("--pr needs --rev <the PR head ref> and --sha <the verified head it must be>")
        if git(root, "rev-parse", a.rev).strip() != a.sha.strip():
            raise HeraldError("%s is not the verified head %s — fetch the PR again" % (a.rev, a.sha))
        cfg = Config.load(root)
        reasons = store.exclusion_reasons(root, cfg, a.topic, a.rev)
        blocking = store.blocking_exclusions(reasons, consent=a.consent)
        if blocking:
            raise HeraldError("refusing to stamp an auto merge: excluded (%s)" % ", ".join(blocking))
        accepted = reasons
    emit(store.mark_auto_merged(root, a.topic, a.pr, clear=a.clear, accepted=accepted))


def cmd_throttle(a):
    """Today's auto publishes against `autonomy.throttle.max_per_day` (UTC day), counting auto
    merges not yet recorded as published."""
    from hrdlib.batch import auto_published_today
    root, cfg = ctx()
    used = auto_published_today(store.load_published(root), store.load_topics(root))
    cap = int(cfg.get("autonomy", "throttle", "max_per_day") or 0)
    emit({"used": used, "max": cap, "room": max(cap - used, 0)})


def cmd_gate(a):
    """Deterministic gate on a topic's article (config.commands.validate or built-in). Also
    writes the readability hints, with the body hash they describe, to
    memory/prose/<id>.json — the editor's input for its reader pass (gitignored)."""
    root, cfg = ctx()
    slug = a.slug or store.load_state(root, a.topic)["slug"]
    rep = store.run_gate(root, cfg, slug, lang=a.lang)
    if a.lang:  # a translation's hints describe that file, not the source the editor reads
        rep["prose_file"] = None
    else:
        rep["prose_file"] = store.write_prose(root, cfg, a.topic, slug, rep)
    if a.record and not rep["ok"]:  # the pre-editor check: a gate failure the flow acts on
        store.record_gate_failure(root, store.load_state(root, a.topic), a.topic, "critique", rep)
    emit(rep)
    if not rep["ok"]:
        sys.exit(1)


def cmd_social(a):
    """SNS drafts (design/herald/03-social.md): prepare / check / close / list / lint."""
    from hrdlib import social

    root, cfg = ctx()
    if a.action in ("prepare", "check", "close", "merge", "final") and os.environ.get("HRD_UNATTENDED") == "1":
        raise HeraldError("/hrd social is interactive only (a human picks every post)")
    if a.action == "prepare":
        if not a.sns:
            raise HeraldError("prepare needs --sns")
        emit(social.prepare(root, cfg, a.sns, slug=a.slug, n=a.n))
    elif a.action == "check":
        if not a.file:
            raise HeraldError("check needs --file <draft> …")
        social.on_base(root, cfg)  # once for the run, not as a per-draft failure
        out = []
        for f in a.file:  # one missing draft must not hide the others' results
            try:
                res = social.check_draft(root, cfg, f, record_signal=a.record)
                res.pop("sha256", None)  # kept in the log; no prompt reads it
                out.append(res)
            except HeraldError as e:  # not a writing problem: nothing for the distributor to fix
                out.append({"draft": f, "ok": False, "profile": None, "settings_to_confirm": [], "warnings": [],
                            "failed": [{"id": "check-error", "overridable": False, "detail": str(e)}]})
        emit(out)
        if not all(r["ok"] for r in out):
            sys.exit(1)
    elif a.action == "close":
        if not a.run:
            raise HeraldError("close needs --run")
        emit(social.close(root, cfg, a.run, approved=a.approved, reject_all=a.reject_all, override=a.override,
                          settings_confirmed=a.setting_confirmed or ()))
    elif a.action == "list":
        emit(social.listing(root, cfg))
    elif a.action == "merge":
        if not (a.sns and a.researched):
            raise HeraldError("merge needs --sns and --researched <pending draft>")
        emit(social.merge(root, cfg, a.sns, a.researched, accept=a.accept, accept_floor=a.accept_floor or ()))
    elif a.action == "final":
        if not (a.draft and a.final_file):
            raise HeraldError("final needs --draft <approved draft> and --final-file <memory/social/final/<sns>/…>")
        emit(social.final(root, cfg, a.draft, a.final_file))
    elif a.action == "lint":
        if a.mode == "rollback" and a.target and not a.file:
            a.file = [a.target]  # the working tree after `git revert --no-commit`
        if not (a.mode and a.file and a.target):
            raise HeraldError("lint needs --mode, --file <pending> and --target <repo path>")
        if len(a.file) != 1:
            raise HeraldError("lint takes one --file")
        out = social.lint(root, cfg, a.mode, a.file[0], a.target, allow_floor=a.allow_floor or (),
                          strengthen=a.strengthen or ())
        emit(out)
        if not out["ok"]:
            sys.exit(1)


MANUAL_SIGNAL_KINDS = ("session-edit-request", "human-edit", "review-finding", "social-edit-request")


def cmd_signal(a):
    """Only the signals that need the session's judgment or diff; the rest are recorded by the
    command where the event happens (contract §G), so a manual call would double-record."""
    if a.kind not in MANUAL_SIGNAL_KINDS:
        raise HeraldError("`%s` is recorded by HRD itself; `signal` takes only: %s"
                          % (a.kind, ", ".join(MANUAL_SIGNAL_KINDS)))
    root = repo_root()
    data = json.loads(a.data) if a.data else {}
    if a.kind == "social-edit-request":  # one axis per theme and day (03-social.md S13)
        import re
        if not isinstance(data, dict) or data.get("theme") not in store.SOCIAL_THEMES:
            raise HeraldError("social-edit-request needs data.theme, one of: %s" % ", ".join(store.SOCIAL_THEMES))
        if not re.match(r"^social:[a-z0-9-]+:\d{8}$", a.topic or ""):
            raise HeraldError("social-edit-request needs --topic social:<sns>:<YYYYMMDD> (prepare's signal_topic)")
        bad = [k for k in ("request", "run", "draft") if not isinstance(data.get(k), str) or not data[k]]
        if bad:
            raise HeraldError("social-edit-request data needs %s" % ", ".join(bad))
    emit(store.signal(root, a.kind, a.topic, data,
                      human_reviewed=None if a.human_reviewed is None else a.human_reviewed == "true"))


def cmd_evolve_readiness(a):
    root, cfg = ctx()
    out = store.evolve_readiness(root, cfg, listing=a.list or a.snapshot)
    if a.snapshot:
        if os.environ.get("HRD_UNATTENDED") == "1":
            raise HeraldError("evolve bookkeeping is attended only (evolve is always started by a human)")
        if not a.token:
            raise HeraldError("--snapshot needs --token <the evolve lock token> (ties it to this run)")
        store.evolve_snapshot(root, out["list"], token=a.token)
    emit(out)


def cmd_evolve_mark(a):
    root = repo_root()
    if os.environ.get("HRD_UNATTENDED") == "1":
        raise HeraldError("evolve bookkeeping is attended only (evolve is always started by a human)")
    if not a.scan and not a.consume:
        raise HeraldError("give --scan and/or --consume <id …>")
    emit(store.evolve_mark(root, scan=a.scan, consume=a.consume or (), token=a.token))


def cmd_auto_exclusion(a):
    root, cfg = ctx()
    reasons = store.exclusion_reasons(root, cfg, a.topic, a.rev)
    blocking = store.blocking_exclusions(reasons, consent=a.consent)
    emit({"reasons": reasons, "blocking": blocking,
          "accepted": [r for r in reasons if r not in blocking]})


def cmd_trim(a):
    root, cfg = ctx()
    if a.force and not a.abort:
        raise HeraldError("--force goes with --abort")
    if a.abort:
        emit(store.trim_abort(root, cfg, a.topic, force=a.force))
    else:
        emit((store.trim_begin if a.begin else store.trim_finish)(root, cfg, a.topic))


def build():
    ap = argparse.ArgumentParser(allow_abbrev=False, prog="hrd.py")
    sp = ap.add_subparsers(dest="group", required=True)

    p = sp.add_parser("lock"); p.add_argument("action", choices=["acquire", "release", "status", "unlock"])
    p.add_argument("--cmd", default="cli"); p.add_argument("--token"); p.set_defaults(fn=cmd_lock)

    p = sp.add_parser("topics"); p.add_argument("action", choices=["add", "list", "show"])
    p.add_argument("--file"); p.add_argument("--state"); p.add_argument("--topic"); p.set_defaults(fn=cmd_topics)

    p = sp.add_parser("select"); p.add_argument("--n", type=int, default=0); p.add_argument("--topic")
    p.set_defaults(fn=cmd_select)
    p = sp.add_parser("status"); p.set_defaults(fn=cmd_status)
    p = sp.add_parser("version"); p.add_argument("--against"); p.set_defaults(fn=cmd_version)
    p = sp.add_parser("evolve-readiness"); p.add_argument("--list", action="store_true")
    p.add_argument("--snapshot", action="store_true"); p.add_argument("--token")
    p.set_defaults(fn=cmd_evolve_readiness)
    p = sp.add_parser("evolve-mark"); p.add_argument("--scan", action="store_true"); p.add_argument("--consume", nargs="+")
    p.add_argument("--token")
    p.set_defaults(fn=cmd_evolve_mark)

    p = sp.add_parser("begin"); p.add_argument("--topic", required=True); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_begin)
    p = sp.add_parser("branch"); p.add_argument("--topic", required=True); p.add_argument("--slug", required=True)
    p.set_defaults(fn=cmd_branch)
    p = sp.add_parser("stage"); p.add_argument("action", choices=["check", "pass"])
    p.add_argument("--topic", required=True); p.add_argument("--stage", required=True)
    p.add_argument("--amend", action="store_true"); p.set_defaults(fn=cmd_stage)
    p = sp.add_parser("loopback"); p.add_argument("--topic", required=True)
    p.add_argument("--human", action="store_true", help="human-requested revision: not counted")
    p.add_argument("--cause", choices=sorted(store.LOOPBACK_CAUSES)); p.add_argument("--theme")
    p.add_argument("--note"); p.add_argument("--claims", help="research: the suspect claim ids, comma-separated")
    p.add_argument("--lang", help="translation / --human: the languages to translate again, comma-separated")
    p.set_defaults(fn=cmd_loopback)
    p = sp.add_parser("audit-round"); p.add_argument("--topic", required=True); p.set_defaults(fn=cmd_audit_round)
    p = sp.add_parser("remap"); p.add_argument("--topic", required=True); p.set_defaults(fn=cmd_remap)
    p = sp.add_parser("refresh-decision"); p.add_argument("--slug", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--precheck", action="store_true"); g.add_argument("--check", action="store_true")
    g.add_argument("--decide", choices=["update", "new", "none"]); g.add_argument("--signal", action="store_true")
    p.add_argument("--source", default="recommended", choices=["recommended", "forced", "direction"])
    p.add_argument("--direction"); p.add_argument("--for-translation", action="store_true")
    p.add_argument("--override-reason"); p.add_argument("--topic-file")
    p.set_defaults(fn=cmd_refresh_decision)
    p = sp.add_parser("config-check"); p.set_defaults(fn=cmd_config_check)
    p = sp.add_parser("translate"); p.add_argument("action", choices=["check", "missing"])
    p.add_argument("--slug"); p.add_argument("--lang"); p.add_argument("--adopt", action="store_true")
    p.set_defaults(fn=cmd_translate)
    p = sp.add_parser("finalize"); p.add_argument("--topic", required=True); p.set_defaults(fn=cmd_finalize)
    p = sp.add_parser("result"); p.add_argument("--topic", required=True); p.add_argument("--status", required=True)
    p.add_argument("--pr", type=int); p.add_argument("--note"); p.add_argument("--merged", type=int, nargs="*")
    p.set_defaults(fn=cmd_result)

    p = sp.add_parser("hash"); p.add_argument("--slug", required=True); p.add_argument("--rev")
    g = p.add_mutually_exclusive_group(); g.add_argument("--source", action="store_true"); g.add_argument("--lang")
    p.set_defaults(fn=cmd_hash)
    p = sp.add_parser("ledger"); p.add_argument("action", choices=["record", "show"])
    p.add_argument("--topic", required=True); p.add_argument("--sha"); p.add_argument("--rev")
    p.add_argument("--kind", default="verify", choices=["verify", "push", "base-commit", "trust", "withdraw-lang"])
    p.set_defaults(fn=cmd_ledger)
    p = sp.add_parser("scope"); p.add_argument("--topic", required=True); p.add_argument("--slug")
    p.add_argument("--rev", default="HEAD"); p.set_defaults(fn=cmd_scope)
    p = sp.add_parser("premerge"); p.add_argument("--topic", required=True); p.add_argument("--rev", required=True)
    p.set_defaults(fn=cmd_premerge)
    p = sp.add_parser("ahead"); p.set_defaults(fn=cmd_ahead)
    p = sp.add_parser("sync"); p.set_defaults(fn=cmd_sync)
    p = sp.add_parser("fetch-pr"); p.add_argument("--pr", type=int, required=True); p.set_defaults(fn=cmd_fetch_pr)
    p = sp.add_parser("commit"); p.add_argument("--cmd", required=True); p.add_argument("--kind", required=True)
    p.add_argument("-m", "--message", required=True)
    p.add_argument("--trailer", action="append", help="Herald-Floor: <token> … / Herald-Strengthen: <token> … (repeatable)")
    p.add_argument("paths", nargs="+"); p.set_defaults(fn=cmd_commit)
    p = sp.add_parser("integrity"); p.add_argument("--predeploy", action="store_true"); p.add_argument("--rev")
    p.add_argument("--report", action="store_true", help="always exit 0; read `ok` and the rows")
    p.set_defaults(fn=cmd_integrity)
    p = sp.add_parser("residue"); p.add_argument("--clean", action="store_true"); p.set_defaults(fn=cmd_residue)
    p = sp.add_parser("herald-set"); p.set_defaults(fn=cmd_herald_set)
    p = sp.add_parser("reverts"); p.add_argument("action", choices=["list", "apply"]); p.set_defaults(fn=cmd_reverts)

    p = sp.add_parser("state"); p.add_argument("--topic", required=True); p.add_argument("--state", required=True)
    p.add_argument("--reason"); p.add_argument("--note"); p.set_defaults(fn=cmd_state)
    p = sp.add_parser("requeue"); p.add_argument("--topic", required=True)
    p.add_argument("--direction", action="store_true", help="attach memory/directions/<id>.diff as the topic's direction")
    p.set_defaults(fn=cmd_requeue)
    p = sp.add_parser("drop"); p.add_argument("--topic", required=True); p.add_argument("--note")
    p.set_defaults(fn=cmd_drop)
    p = sp.add_parser("withdraw-lang"); p.add_argument("slug"); p.add_argument("--lang", required=True)
    p.set_defaults(fn=cmd_withdraw_lang)
    p = sp.add_parser("withdraw"); p.add_argument("slug_or_topic"); p.add_argument("--note")
    p.set_defaults(fn=cmd_withdraw)
    p = sp.add_parser("unwithdraw"); p.add_argument("slug_or_topic"); p.set_defaults(fn=cmd_unwithdraw)
    p = sp.add_parser("move"); p.add_argument("--topic", required=True); p.add_argument("--new-slug", required=True)
    p.set_defaults(fn=cmd_move)
    p = sp.add_parser("release-slug"); p.add_argument("slug"); p.set_defaults(fn=cmd_release_slug)
    p = sp.add_parser("mark-published"); p.add_argument("--topic", required=True); p.add_argument("--slug", required=True)
    p.set_defaults(fn=cmd_mark_published)
    p = sp.add_parser("record-published"); p.add_argument("--topic", required=True); p.add_argument("--slug", required=True)
    p.add_argument("--pr", type=int); p.add_argument("--auto", action="store_true"); p.set_defaults(fn=cmd_record_published)
    p = sp.add_parser("auto-merged"); p.add_argument("--topic", required=True); p.add_argument("--pr", type=int)
    p.add_argument("--clear", action="store_true"); p.add_argument("--rev")
    p.add_argument("--consent", action="store_true"); p.add_argument("--sha"); p.set_defaults(fn=cmd_auto_merged)
    p = sp.add_parser("throttle"); p.set_defaults(fn=cmd_throttle)
    p = sp.add_parser("gate"); p.add_argument("--topic", required=True); p.add_argument("--slug")
    p.add_argument("--lang", help="gate one translation (the translator's own check)")
    p.add_argument("--record", action="store_true", help="record a failure as a gate-failure signal (pre-editor check)")
    p.set_defaults(fn=cmd_gate)
    p = sp.add_parser("social")
    p.add_argument("action", choices=["prepare", "check", "close", "list", "lint", "merge", "final"])
    p.add_argument("--record", action="store_true", help="check: record failures as social-gate-failure signals")
    p.add_argument("--researched"); p.add_argument("--accept", nargs="*"); p.add_argument("--accept-floor", action="append")
    p.add_argument("--draft"); p.add_argument("--final-file")
    p.add_argument("--sns"); p.add_argument("--slug"); p.add_argument("--n", type=int, default=3)
    p.add_argument("--file", nargs="+"); p.add_argument("--run"); p.add_argument("--approved")
    p.add_argument("--reject-all", action="store_true"); p.add_argument("--override")
    p.add_argument("--setting-confirmed", action="append")
    p.add_argument("--mode"); p.add_argument("--target")
    p.add_argument("--allow-floor", action="append"); p.add_argument("--strengthen", action="append")
    p.set_defaults(fn=cmd_social)
    p = sp.add_parser("signal"); p.add_argument("--kind", required=True); p.add_argument("--topic")
    p.add_argument("--data"); p.add_argument("--human-reviewed", choices=["true", "false"]); p.set_defaults(fn=cmd_signal)
    p = sp.add_parser("auto-exclusion"); p.add_argument("--topic", required=True); p.add_argument("--rev")
    p.add_argument("--consent", action="store_true"); p.set_defaults(fn=cmd_auto_exclusion)
    p = sp.add_parser("trim"); p.add_argument("--topic", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    for flag in ("--begin", "--finish", "--abort"):
        g.add_argument(flag, action="store_true")
    p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_trim)
    return ap


def main(argv=None):
    a = build().parse_args(argv)
    try:
        a.fn(a)
    except HeraldError as e:
        sys.stderr.write("hrd: %s\n" % e)
        sys.exit(1)


if __name__ == "__main__":
    main()
