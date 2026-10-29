"""M1b: a video's flow commands (m1-plan §4.1) — begin, record-source, hold, release-lock, record-render, done (no
evidence: they enter a held state or record what a Studio script or git did), abandon and overlay (a person's
decision: the guard's evidence, consumed once).

Exit codes as state.py's (commands.py): 0 ok · 1 failed · 2 usage/setup · 3 refused · 4 waiting for a person ·
5 busy · 6 no evidence."""

import json
import os
import re
import shutil
import stat
import subprocess
import sys

from .. import locks, machine, paths
from ..commit import okfile
from . import commands, evidence, harnessgate, hashes, labels, schema, stagechecks, store
from .collect import CollectError, frozen_copy_path

C = commands
VIDEO_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
KINDS = ("youtube",)  # M1: one video kind (U-M1-4)
REASON_MAX = 500
OVERLAY_MAX = 64 * 1024
OVERLAY_KEYS = ("hosts", "sources", "terms", "videos", "actors")
MIN_TERM = 4


class Usage(Exception):
    pass


def _out(line):
    sys.stdout.write(line + "\n")


def _warn(line):
    sys.stderr.write("warning: %s\n" % line)


def _refuse(msg, code):
    raise store.Refused(msg, code)


def harness_refusal(repo, providers, ctx_of, env=None):
    """None, or the refusal text when the harness has uncommitted changes (exit 3)."""
    res = harnessgate.check(repo, env=env, providers=providers, ctx_of=ctx_of)
    return res.message() if res.blocking else None


# ---------- begin ----------

def _semver(text):
    core = str(text or "").split("+", 1)[0].split("-", 1)[0].split(".")
    if len(core) != 3 or not all(p.isdigit() for p in core):
        return None
    return tuple(int(p) for p in core)


def begin(repo, cfg, root, o, providers, ctx_of, env=None):
    """`begin <video> --source <path> --kind youtube [--lang l]`."""
    if len(o["_"]) != 1:
        raise Usage("begin needs one video id: begin <video> --source <path> --kind youtube [--lang l]")
    video = o["_"][0]
    if not VIDEO_ID.match(video):
        raise Usage("a video id is lowercase letters, digits and -, at most 64 characters: %r" % video)
    kind = o.get("--kind")
    if kind not in KINDS:
        raise Usage("--kind must be one of %s in this version (got %r)" % (", ".join(KINDS), kind))
    src = o.get("--source")
    if not src:
        raise Usage("begin needs --source <the Markdown file in this repository>")
    lang = o.get("--lang") or cfg.get("language")
    if not isinstance(lang, str) or not re.match(r"^[a-z]{2,3}(-[A-Za-z0-9]+)?$", lang):
        raise Usage("cannot tell the video's language (--lang, or language in config.json): %r" % (lang,))
    why = harness_refusal(repo, providers, ctx_of, env)
    if why:
        raise store.Refused(why, C.REFUSED)
    for d in (os.path.join(repo, root, "videos", video), os.path.join(repo, root, "local", "videos", video)):
        if os.path.lexists(d):
            raise store.Refused("a video %s exists already (%s)" % (video, os.path.relpath(d, repo)), C.REFUSED)
    real_repo = os.path.realpath(repo)
    absrc = os.path.realpath(src if os.path.isabs(src) else os.path.join(repo, src))
    if not absrc.startswith(real_repo + os.sep):
        raise Usage("the source must be a file in this repository: %s" % src)
    rel = os.path.relpath(absrc, real_repo)
    if rel.split(os.sep)[0] in (".git", ".claude") or rel.startswith(root.strip("/") + os.sep):
        raise Usage("the source must be the repository's own writing, not Studio's or git's files: %s" % rel)
    if not os.path.isfile(absrc) or not rel.lower().endswith((".md", ".mdx", ".markdown")):
        raise Usage("the source must be a Markdown file (.md): %s" % rel)
    s2v_path = machine.s2v_path(repo)
    if s2v_path is None:
        raise Usage(machine.HINT)
    try:
        ver = providers.version({"s2v_path": s2v_path, "repo": repo})
    except CollectError as e:
        raise Usage(str(e))
    if not isinstance(ver, dict) or not ver.get("id"):
        raise Usage("s2v --version --json gave no id")
    if ver.get("stale_build") is not False:
        raise Usage("s2v's build is stale (or unknown): run yarn build in the s2v repository first")
    want = _semver(((cfg.get("s2v") or {}) if isinstance(cfg.get("s2v"), dict) else {}).get("min_version"))
    have = _semver(ver.get("version"))
    if want and (have is None or have < want):
        raise Usage("s2v %s is older than this repository's s2v.min_version %s" % (
            ver.get("version"), ".".join(map(str, want))))
    if ver.get("commit") is None:
        _warn("s2v has no git commit (a copy): going back to this exact version later is not possible")
    elif ver.get("dirty"):
        _warn("s2v has uncommitted changes: going back to this exact version later is not possible")
    s2v = {k: ver.get(k) for k in ("id", "version", "commit", "dirty")}
    st = schema.create_state(video, "public", kind, "public", lang, s2v,
                             {"kind": "repo-md", "path": rel.replace(os.sep, "/"), "images": [], "frozen_hash": None,
                              # the source's last commit at begin: later commits to it are shown at ① (S5)
                              "begin_commit": last_commit(repo, [rel.replace(os.sep, "/")])})
    vdir = os.path.join(repo, root, "videos", video)
    voices = os.path.join(repo, root, "voices")
    if not os.path.isdir(voices):
        os.makedirs(voices, exist_ok=True)  # S7: the first tts must not make voices/ at the repository root
    store.create(vdir, st)
    _out("begun %s (%s, %s) from %s" % (video, kind, lang, st["source"]["path"]))
    return C.OK


# ---------- record-source ----------

def _checked_assets(vdir, copy_sha, fp):
    """(images, assets.json sha, note): the usable images of assets.json when check_scope passed for this very copy of
    the source (m1-plan §6, M1d); else no images and a note saying what to run."""
    p = os.path.join(vdir, "work", "assets.json")
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        return [], None, "no work/assets.json yet: run resolve_assets.py, the source analyst and check_scope.py, " \
                         "then record-source again"
    except ValueError:
        return [], None, "work/assets.json is not JSON: run resolve_assets.py again"
    sc = data.get("scope_check") if isinstance(data, dict) else None
    if not isinstance(sc, dict) or sc.get("result") != "pass" or sc.get("source_copy_sha") != copy_sha or \
            data.get("source_copy_sha") != copy_sha:
        return [], None, "work/assets.json is not checked for this copy of the source: run resolve_assets.py and " \
                         "check_scope.py, then record-source again"
    changed = [k for k in sorted(fp) if k not in sc or sc[k] != fp[k]]
    if changed:
        return [], None, "%s changed since check_scope.py: run check_scope.py again, then record-source again" \
            % ", ".join(changed)
    images = sorted(set(i["resolved"] for i in data.get("images") or []
                        if isinstance(i, dict) and i.get("status") == "ok" and isinstance(i.get("resolved"), str)))
    return images, hashes.file_sha(p), None


def uncommitted(repo, rels):
    """[(path, why)] of the repository files among `rels` that are not exactly as in HEAD (M1d re-review R1, M1e
    review S4): untracked, marked assume-unchanged or skip-worktree (git would hide their changes), staged, or with
    work-tree bytes whose blob is not HEAD's."""
    rels = sorted(set(rels))
    if not rels:
        return []
    if _git(repo, "rev-parse", "-q", "--verify", "HEAD^{commit}") is None:
        return [(r, "no commit yet") for r in rels]
    spec = [":(literal)" + r for r in rels]
    flags = {}
    for line in (_git(repo, "ls-files", "-v", "-z", "--", *spec) or "").split("\0"):
        if len(line) > 2 and line[1] == " ":
            flags[line[2:]] = line[0]
    changed = _git(repo, "diff", "--name-only", "-z", "HEAD", "--", *spec)
    changed = set((changed or "").split("\0")) - {""} if changed is not None else set(rels)
    out = []
    for r in rels:
        tag = flags.get(r)
        if tag is None:
            out.append((r, "not committed (untracked)"))
        elif tag in ("S", "s") or tag.islower():
            out.append((r, "marked skip-worktree or assume-unchanged (git hides its changes) — the person clears it"))
        elif r in changed:
            out.append((r, "changed since the last commit"))
        else:
            head = (_git(repo, "rev-parse", "-q", "--verify", "HEAD:" + r) or "").strip()
            work = (_git(repo, "hash-object", "--path=" + r, "--", r) or "").strip()
            if not head or head != work:
                out.append((r, "changed since the last commit"))
    return out


def last_commit(repo, rels):
    """The newest commit that touched `rels` (None without one)."""
    out = _git(repo, "log", "-1", "--format=%H", "--", *[":(literal)" + r for r in rels])
    return (out or "").strip() or None


def commits_since(repo, base, rels):
    """[{"sha", "subject"}] of the commits that touched `rels` after `base` (all of them when base is None)."""
    if not rels:
        return []
    rng = "%s..HEAD" % base if base else "HEAD"
    spec = [":(literal)" + r for r in sorted(set(rels))]
    # commits that changed the paths, and merges that changed them against their first parent (U2: plain path
    # limiting drops a merge whose result equals one of its parents)
    touched = set((_git(repo, "log", "--no-merges", "--format=%H", rng, "--", *spec) or "").split())
    touched |= set((_git(repo, "log", "--first-parent", "--merges", "--format=%H", rng, "--", *spec) or "").split())
    out = _git(repo, "log", "--format=%H%x09%s", rng)
    res = []
    for line in (out or "").splitlines():
        sha, _, subject = line.partition("\t")
        if sha and sha in touched:
            merge = len((_git(repo, "rev-list", "--parents", "-n", "1", sha) or "").split()) > 2
            c = {"sha": sha, "subject": subject, "stat": _diffstat(repo, sha, rels, merge)}
            if merge:
                c["merge"] = True
            res.append(c)
    return res


def _diffstat(repo, sha, rels, merge=False):
    """`+A -D path, …` of one commit, limited to `rels` (M1e review T3: what the commit changed in the source). A merge
    is diffed against its first parent (U2: `git show --numstat` prints nothing for one)."""
    spec = [":(literal)" + r for r in sorted(set(rels))]
    if merge:
        out = _git(repo, "diff", "--numstat", sha + "^1", sha, "--", *spec)
    else:
        out = _git(repo, "show", "--numstat", "--format=", sha, "--", *spec)
    parts = []
    for line in (out or "").splitlines():
        bits = line.split("\t")
        if len(bits) == 3:
            parts.append("%s %s" % (path_stat(bits[0], bits[1]), bits[2]))
    return ", ".join(parts)


def path_stat(added, deleted):
    return "binary" if added == "-" else "+%s -%s" % (added, deleted)


def source_commit_lines(state):
    """The lines the ① question must show (S5): one per commit to the source after begin."""
    return labels.source_commit_lines(state)


def _dirty_refusal(found):
    return store.Refused("Studio freezes only committed writing — %s. Ask the person to commit (or undo) these "
                         "changes; never change or commit the person's writing yourself. Then record-source again."
                         % "; ".join("%s: %s" % x for x in found), C.REFUSED)


def record_source(repo, vdir, state, cfg, hooks=None, env=None):
    src = state["source"]
    if src.get("kind") != "repo-md":
        raise store.Refused("source kind %r is not supported yet" % src.get("kind"), C.USAGE)
    absrc = os.path.join(repo, src["path"])
    before = hashes.file_sha(absrc)
    if before is None:
        raise store.Refused("the source is missing: %s" % src["path"], C.FAIL)
    found = uncommitted(repo, [src["path"]])
    if found:  # an agent could otherwise edit the person's writing before it is frozen
        raise _dirty_refusal(found)
    dst = frozen_copy_path(vdir, src)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = "%s.tmp.%d" % (dst, os.getpid())
    shutil.copyfile(absrc, tmp)
    copied = hashes.file_sha(tmp)
    if hashes.file_sha(absrc) != before or copied != before:
        os.remove(tmp)
        raise store.Refused("the source changed while it was copied: run record-source again", C.FAIL)
    # the images the source refers to are part of its hash once assets.json is checked for this copy (M1d)
    from ..source.scope import fingerprint
    fp = fingerprint(repo, cfg, dict(os.environ if env is None else env))
    images, assets_sha, note = _checked_assets(vdir, copied, fp)
    found = uncommitted(repo, images)
    if found:
        os.remove(tmp)
        raise _dirty_refusal(found)
    before_live = hashes.source_hash_repo_md(repo, src["path"], images)
    os.replace(tmp, dst)
    after_live = hashes.source_hash_repo_md(repo, src["path"], images)
    if after_live != before_live or hashes.file_sha(absrc) != before:
        raise store.Refused("the source or its images changed while they were recorded: run record-source again",
                            C.FAIL)
    rec = {"frozen_hash": after_live, "copy_sha": copied, "assets_sha": assets_sha, "images": images,
           "frozen_at": schema.now(),
           "commits_since_begin": commits_since(repo, src.get("begin_commit"), [src["path"]] + list(images))}

    def check(s):
        if all(L["status"] in ("done", "aborted") for L in s["langs"].values()):
            raise store.Refused("every language of %s is finished" % s["video"], C.USAGE)

    def change(s):
        s["source"].update(rec)

    store.write(vdir, dict({"event": "record-source"}, **rec), change, hooks=hooks, check=check)
    _out("source frozen %s (%d image(s))" % (after_live[:12], len(images)))
    for line in source_commit_lines(dict(state, source=dict(src, **rec))):
        _out("%s — put this line in the ① question" % line)
    if note:
        _out("note: %s" % note)
    return C.OK


# ---------- hold / release-lock ----------

def hold(vdir, lang, o, hooks=None):
    if len(o["_"]) < 2 or o["_"][1] != "lock":
        raise Usage("hold takes only: hold <video> lock --reason <the busy line> (other held states are entered "
                    "by the stages themselves)")
    reason = o.get("--reason")
    if not reason:
        raise Usage("hold needs --reason <the busy line s2v printed>")
    reason = reason[:REASON_MAX]
    box = {}

    def check(s):
        L = s["langs"][lang]
        if L["status"] in ("done", "aborted"):
            raise store.Refused("%s is %s" % (lang, L["status"]), C.USAGE)
        h = L.get("held")
        if h and h.get("state") != "lock":
            raise store.Refused("%s is held already (%s): resolve it first" % (lang, h.get("state")), C.WAIT)
        box["again"] = bool(h)

    def change(s):
        L = s["langs"][lang]
        if not box["again"]:
            L["held"] = {"state": "lock", "detail": {"reason": reason}, "since": schema.now()}
        else:
            L["held"]["detail"] = {"reason": reason}

    store.write(vdir, {"event": "hold", "lang": lang, "held": "lock", "reason": reason}, change, hooks=hooks,
                check=check)
    _out("%s: held (lock)" % lang)
    return C.OK


def release_lock(vdir, state, lang, ctx, providers, hooks=None, env=None):
    """Leave `held:lock` only: s2v says the machine lock is free (busy.tts null) in the same state folder lock.py
    uses (m1-plan §4.1, M4). Other held states belong to unlock (evidence) and the gates."""
    h = state["langs"][lang].get("held")
    if not h or h.get("state") != "lock":
        raise store.Refused("%s is not held by the machine lock (%s) — release-lock leaves held:lock only; other held "
                            "states need the person (unlock) or their gate" % (lang, (h or {}).get("state") or
                                                                                "not held"), C.REFUSED)
    try:
        st = providers.services(ctx)
    except CollectError as e:
        raise store.Refused("cannot ask s2v about the machine lock: %s" % e, C.WAIT)
    try:
        mine = os.path.realpath(locks.state_dir(env))
    except locks.UsageError as e:
        raise Usage(str(e))
    theirs = st.get("state_dir") if isinstance(st, dict) else None
    if not isinstance(theirs, str) or os.path.realpath(theirs) != mine:
        raise store.Refused("s2v's state folder (%s) is not lock.py's (%s): the shell's S2V_STATE_DIR differs — "
                            "ask the person" % (theirs, mine), C.WAIT)
    busy = (st.get("busy") or {}) if isinstance(st.get("busy"), dict) else None
    if busy is None or "tts" not in busy:
        raise store.Refused("s2v services status has no busy.tts", C.WAIT)
    if busy["tts"] is not None:
        raise store.Refused("the machine lock is still busy (%s): wait, then try again" % json.dumps(
            busy["tts"], ensure_ascii=False), C.WAIT)

    def check(s):
        hh = s["langs"][lang].get("held")
        if not hh or hh.get("state") != "lock":
            raise store.Refused("%s is not held by the machine lock any more" % lang, C.REFUSED)

    def change(s):
        s["langs"][lang]["held"] = None

    store.write(vdir, {"event": "release-lock", "lang": lang, "services": {"state_dir": theirs, "busy": busy}},
                change, hooks=hooks, check=check)
    _out("%s: released (the machine lock is free)" % lang)
    return C.OK


# ---------- record-render ----------

def record_render(repo, vdir, state, lang, o, hooks=None):
    """Record run_s2v.py's render result from its check file (never from flags, M3)."""
    out = o.get("--output")
    if not out:
        raise Usage("record-render needs --output <output>")
    if out not in schema.current_outputs(state, lang):
        raise Usage("output %s is not in the brief" % out)
    data = stagechecks.read(vdir, lang, "render", out)
    rel = os.path.relpath(stagechecks.path(vdir, lang, "render", out), repo)
    if data is None:
        raise store.Refused("no render result (%s): render with run_s2v.py render first" % rel, C.FAIL)
    det = data.get("details") if isinstance(data.get("details"), dict) else None
    if data.get("_unreadable") or data.get("schema") != stagechecks.SCHEMA or data.get("stage") != "render" or \
            data.get("scope") != out or det is None or data.get("script") != "run_s2v.py":
        raise store.Refused("%s is not a render result of run_s2v.py" % rel, C.FAIL)
    mp4 = det.get("mp4")
    if not isinstance(mp4, str) or os.path.isabs(mp4) or ".." in mp4.split("/"):
        raise store.Refused("%s names no result file" % rel, C.FAIL)
    now = hashes.file_sha(os.path.join(repo, mp4))
    if now != det.get("mp4_sha"):
        raise store.Refused("the result %s is not the file run_s2v.py made (its sha changed) — render again" % mp4,
                            C.FAIL)
    good = data.get("result") == "pass" and det.get("exit") == 0 and bool(det.get("ok_line")) and \
        not det.get("check_failed_line") and now is not None
    rec = {"exit": det.get("exit"), "ok": bool(det.get("ok_line")), "check_failed": bool(det.get("check_failed_line")),
           "sha": now, "file": mp4, "proxy": bool(det.get("watermark")), "result": "pass" if good else "fail",
           "check_sha": hashes.file_sha(stagechecks.path(vdir, lang, "render", out)), "at": schema.now()}

    def check(s):
        L = s["langs"][lang]
        if L["status"] in ("done", "aborted"):
            raise store.Refused("%s is %s" % (lang, L["status"]), C.USAGE)
        if L.get("held"):
            raise store.Refused("%s is held (%s): resolve it first" % (lang, L["held"].get("state")), C.WAIT)

    def change(s):
        L = s["langs"][lang]
        L["renders"][out] = dict(rec)
        if not good:
            L["held"] = {"state": "render", "detail": {"output": out, "exit": rec["exit"],
                                                       "check_failed": rec["check_failed"]}, "since": schema.now()}

    store.write(vdir, {"event": "record-render", "lang": lang, "output": out, "render": rec}, change, hooks=hooks,
                check=check)
    if not good:
        _out("%s %s: the render failed (exit %s%s) — held:render; ask the person" % (
            lang, out, rec["exit"], ", CHECK FAILED" if rec["check_failed"] else ""))
        return C.WAIT
    _out("%s %s: render recorded%s" % (lang, out, " (proxy watermark)" if rec["proxy"] else ""))
    return C.OK


def render_problem(state, lang, out, repo):
    """Why `stage-done render --output o` cannot be recorded from the state's render record (v3 N2), or None."""
    r = state["langs"][lang]["renders"].get(out)
    if not isinstance(r, dict) or r.get("result") != "pass" or r.get("exit") != 0 or not r.get("ok"):
        return "render %s has no successful record-render — render with run_s2v.py, then record-render" % out
    if not r.get("file") or hashes.file_sha(os.path.join(repo, r["file"])) != r.get("sha"):
        return "the render of %s changed after record-render — render again" % out
    return None


# ---------- done ----------

def _git(repo, *args):
    out = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, env=paths.git_env())
    return out.stdout if out.returncode == 0 else None


def _commit_of_tree(repo, tree):
    """The newest commit in HEAD's history whose tree is `tree`, or None."""
    log = _git(repo, "log", "--format=%H %T", "HEAD")
    for line in (log or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == tree:
            return parts[0]
    return None


def done(repo, vdir, state, lang, hooks=None, root="studio"):
    """After the video commit: its commit record must say kind video, this video, a person's answer and this state's
    seq, and that commit must be in HEAD's history with the video's committed paths unchanged since (m1-plan §4.1, M2;
    M1b review Y3: the record the hook kept in the video's folder, so later commits do not block done)."""
    video = state["video"]
    ok = okfile.read_video_record(repo, root, video)
    if ok is None:
        ok, why = okfile.read(repo)
        if ok is None:
            raise store.Refused("no commit record of %s (commit-ok.json is %s) — commit the video first "
                                "(check_commit.py --stage video)" % (video, why), C.FAIL)
    probs = []
    if ok.get("kind") != "video":
        probs.append("the last staged commit is a %s commit, not a video commit" % ok.get("kind"))
    if ok.get("target") != video:
        probs.append("the last staged commit is for %r, not %s" % (ok.get("target"), video))
    ap = ok.get("approval")
    if not isinstance(ap, dict) or ap.get("mode") != "human":
        probs.append("the commit has no person's answer recorded")
    seq = ((ok.get("states") or {}).get(video) or {}).get("last_seq") if isinstance(ok.get("states"), dict) else None
    if seq != state.get("last_seq"):
        probs.append("the video's state changed after it was staged (seq %s, now %s)" % (seq, state.get("last_seq")))
    tree = ok.get("tree") if isinstance(ok.get("tree"), str) else ""
    commit = _commit_of_tree(repo, tree) if tree else None
    if commit is None:
        probs.append("HEAD's history has no commit with the staged tree %s (was the commit made?)" % (tree[:12] or "-"))
    else:
        # only the video's own files: another video's commit may change shared ones (pronounce.json, voices/) — M1b
        # re-review Z2
        mine = "%s/videos/%s/" % (root.strip("/"), video)
        vpaths = [p for p in (ok.get("paths") or []) if isinstance(p, str) and p.startswith(mine)]
        changed = _git(repo, "diff", "--name-only", commit, "HEAD", "--", *[":(literal)" + p for p in vpaths]) \
            if vpaths else ""
        if changed is None or changed.strip():
            probs.append("the video's committed files changed after its commit (%s) — commit the video again"
                         % ", ".join((changed or "?").split()[:5]))
    if probs:
        raise store.Refused("not done: " + "; ".join(probs), C.FAIL)

    def check(s):
        L = s["langs"][lang]
        if L["status"] != "active":
            raise store.Refused("%s is %s already" % (lang, L["status"]), C.USAGE)
        if s.get("last_seq") != seq:
            raise store.Refused("the video's state changed meanwhile", C.FAIL)

    def change(s):
        L = s["langs"][lang]
        L["status"] = "done"
        L["stage"] = "commit"

    store.write(vdir, {"event": "done", "lang": lang, "tree": tree, "commit": commit,
                       "commit_ok": {"kind": ok.get("kind"), "target": ok.get("target")}},
                change, hooks=hooks, check=check)
    _out("%s: done" % lang)
    return C.OK


# ---------- abandon (evidence) ----------

def abandon(repo, vdir, state, lang, o, hooks, argv):
    from .gates import _with_evidence  # one lock order for every evidence command

    def check_state(s):
        L = s["langs"][lang]
        if L["status"] != "active":
            raise store.Refused("%s is %s already" % (lang, L["status"]), C.USAGE)

    def events(s, ev):
        return [{"event": "abandon", "lang": lang, "answer": evidence.answer_of(ev)}]

    def change(s, ev):
        s["langs"][lang]["status"] = "aborted"

    _with_evidence(repo, vdir, state["video"], argv, "abandon", lambda s: labels.abandon(s["video"], lang),
                   check_state, change, events, bool(o.get("--proxy")), hooks)
    _out("%s: abandoned (the committed script stays)" % lang)
    return C.OK


# ---------- overlay (evidence) ----------

def _overlay_source(repo, src):
    """The --from file's bytes: a regular file (not a link), at most 64 KB, outside the repository's tracked area —
    outside the repository or under .claude/studio/local/ (a tracked file as the source would carry internal terms
    into the commit paths)."""
    if not src or not os.path.isabs(src):
        raise Usage("overlay --from needs an absolute path")
    try:
        st = os.lstat(src)
    except OSError as e:
        raise Usage("cannot read %s: %s" % (src, e.strerror))
    if stat.S_ISLNK(st.st_mode):
        raise store.Refused("%s is a symbolic link — give the file itself" % src, C.FAIL)
    if not stat.S_ISREG(st.st_mode):
        raise store.Refused("%s is not a regular file" % src, C.FAIL)
    if st.st_size > OVERLAY_MAX:
        raise store.Refused("%s is larger than 64 KB" % src, C.FAIL)
    real = os.path.realpath(src)
    top = os.path.realpath(repo)
    local = os.path.realpath(os.path.join(repo, ".claude", "studio", "local"))
    if real == top or real.startswith(top + os.sep):
        if not real.startswith(local + os.sep):
            raise store.Refused("%s is inside the repository — the overlay's source must be outside it (or under "
                                ".claude/studio/local/)" % src, C.FAIL)
    with open(src, "rb") as f:
        raw = f.read(OVERLAY_MAX + 1)
    if len(raw) > OVERLAY_MAX:
        raise store.Refused("%s is larger than 64 KB" % src, C.FAIL)
    return raw


def overlay_problems(raw):
    """Problems of the overlay's content (the keys of m0d2-plan §9.2 only)."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return ["not JSON: %s" % e]
    if not isinstance(data, dict) or set(data) != {"internal"} or not isinstance(data["internal"], dict):
        return ["the overlay is {\"internal\": {…}} and nothing else"]
    inner = data["internal"]
    out = []
    extra = sorted(set(inner) - set(OVERLAY_KEYS))
    if extra:
        out.append("unknown keys: %s (allowed: %s)" % (", ".join(extra), ", ".join(OVERLAY_KEYS)))
    for k in ("hosts", "terms", "videos", "actors"):
        v = inner.get(k, [])
        if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
            out.append("%s must be a list of texts" % k)
    if any(isinstance(t, str) and len(t.strip()) < MIN_TERM for t in inner.get("terms", []) or []):
        out.append("every term has at least %d characters" % MIN_TERM)
    srcs = inner.get("sources", [])
    if not isinstance(srcs, list) or not all(isinstance(x, dict) and isinstance(x.get("url"), str) for x in srcs):
        out.append("sources must be a list of {\"url\": …}")
    return out


def overlay_lines(raw):
    """The lines the overlay question shows: every key with its number of entries (M1b review Y10 / J29)."""
    inner = json.loads(raw.decode("utf-8"))["internal"]
    return ["internal.%s: %d개" % (k, len(inner.get(k) or [])) for k in OVERLAY_KEYS]


def overlay_lines_missing(raw, question):
    from ..commit.summary import norm
    q = norm(question or "")
    return [l for l in overlay_lines(raw) if norm(l) not in q]


def overlay(repo, o, hooks, argv):
    if o["_"]:
        raise Usage("overlay takes no video id: overlay --from <json> --expect <sha12>")
    if o.get("--proxy"):
        raise Usage("overlay records the person's own settings: the proxy mode cannot")
    expect = o.get("--expect")
    if not expect or not labels.HASH12.match(expect):
        raise Usage("overlay needs --expect <the 12 hex characters shown in the question>")
    raw = _overlay_source(repo, o.get("--from"))
    sha = hashes.sha(raw)
    if sha[:12] != expect:
        raise store.Refused("--expect %s is not the sha of %s (%s): show the file again" % (
            expect, o.get("--from"), sha[:12]), C.FAIL)
    probs = overlay_problems(raw)
    if probs:
        raise store.Refused("the overlay is refused: %s" % "; ".join(probs), C.FAIL)
    why = paths.local_problem(repo)
    if why:
        raise Usage(why)
    with evidence.ConsumptionLock(repo):
        try:
            ev = evidence.check(repo, argv, labels.overlay(expect), False)
        except evidence.Missing as e:
            raise store.Refused(str(e), C.NO_EVIDENCE)
        missing = overlay_lines_missing(raw, ev.get("question"))
        if missing:
            raise store.Refused("the person's question did not show what the overlay holds (%s) — ask again with "
                                "each key and its number of entries (m1-plan §23.2 J29)" % "; ".join(missing),
                                C.NO_EVIDENCE)
        evidence.consume(repo, ev, None, "overlay")
        p = os.path.join(repo, ".claude", "studio", "local", "config.internal.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = "%s.tmp.%d" % (p, os.getpid())
        with open(tmp, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        paths.check_local(repo)
        d = os.path.join(paths.backup_root(), paths.repo_key(repo))
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, "overlay.sha.tmp.%d" % os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(sha + "\n")
        os.replace(tmp, os.path.join(d, "overlay.sha"))
        evidence.remove_pending(repo)
    _out("overlay set %s" % sha[:12])
    return C.OK

