"""`setup.py init plan|apply` (m1-plan §5.1 · §5.2, D-M1-3).

`init apply` takes no evidence: in a repository without a harness or marker the guard judges nothing, and the person's
confirmation is the first harness commit (`커밋 <tree12>` with the value block). Until that commit `begin` refuses
(the harness is not committed). `init apply` refuses (3) when a harness exists anywhere (work tree, index, HEAD) or
when only a marker is left from an earlier install — so it is never a way around the evidence that `config`/`update`
need. The empty overlay and its sha are made here only, on the first install."""

import hashlib
import json
import os
import re
import shutil

from .. import ignore, machine, narrator, paths
from . import analyze, render
from .common import FAIL, REFUSED, USAGE, SetupError, git, write_text

PLAN_SCHEMA = 1
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
ROOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
LANGS = narrator.LANGS
TEXT_MAX = 300


def plan_path(top):
    return os.path.join(paths.common_dir(top), "studio", "init-plan.json")


def _text(v, name, empty_ok=False, maximum=TEXT_MAX):
    if not isinstance(v, str) or (not v.strip() and not empty_ok) or len(v) > maximum or "\n" in v:
        raise SetupError(USAGE, "%s must be one line of text (at most %d characters)" % (name, maximum))
    return v.strip()


def _rel(top, v, name, folder=False):
    """A repository-relative path or glob without `..`, absolute parts or links out of the repository."""
    if not isinstance(v, str) or not v or v.startswith("/") or "\\" in v or ".." in v.split("/") or "\n" in v:
        raise SetupError(USAGE, "%s must be a path inside the repository: %r" % (name, v))
    if folder:
        real = os.path.realpath(os.path.join(top, v))
        if not (real == os.path.realpath(top) or real.startswith(os.path.realpath(top) + os.sep)):
            raise SetupError(USAGE, "%s leaves the repository: %r" % (name, v))
    return v


def normalize(top, answers):
    """The validated answers (m1-plan §5.2 step 3) with defaults filled in."""
    if not isinstance(answers, dict):
        raise SetupError(USAGE, "the answers are a JSON object")
    known = {"language", "studio_root", "project_name", "purpose", "priorities", "brand", "public_domains",
             "web_roots", "visibility_public", "narrator", "husky", "s2v_path"}
    extra = sorted(set(answers) - known)
    if extra:
        raise SetupError(USAGE, "unknown answers: %s" % ", ".join(extra))
    lang = answers.get("language")
    if lang not in LANGS:
        raise SetupError(USAGE, "language must be one of %s" % ", ".join(LANGS))
    root = answers.get("studio_root") or "studio"
    if not ROOT.match(root) or root in (".claude", ".git", "node_modules"):
        raise SetupError(USAGE, "studio_root must be a plain folder name: %r" % root)
    brand = answers.get("brand") or {}
    if not isinstance(brand, dict) or set(brand) - {"name", "accent_color", "logo"}:
        raise SetupError(USAGE, "brand is {\"name\", \"accent_color\", \"logo\"}")
    color = brand.get("accent_color") or "#2563EB"
    if not COLOR.match(color):
        raise SetupError(USAGE, "brand.accent_color must be #RRGGBB")
    logo = brand.get("logo")
    if logo is not None:
        _rel(top, logo, "brand.logo", folder=True)
        if not os.path.isfile(os.path.join(top, logo)):
            raise SetupError(USAGE, "brand.logo is not a file in the repository: %s" % logo)
    project = _text(answers.get("project_name"), "project_name")
    doms = answers.get("public_domains") or []
    if not isinstance(doms, list) or not all(isinstance(d, str) and re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", d)
                                             for d in doms):
        raise SetupError(USAGE, "public_domains is a list of host names (example.com)")
    wr = answers.get("web_roots") or {}
    if not isinstance(wr, dict) or not all(isinstance(k, str) and k.startswith("/") for k in wr):
        raise SetupError(USAGE, "web_roots maps a site path (starting with /) to a folder of the repository")
    for k, v in wr.items():
        _rel(top, v, "web_roots[%s]" % k, folder=True)
        if not os.path.isdir(os.path.join(top, v)):
            raise SetupError(USAGE, "web_roots[%s] is not a folder of the repository: %s" % (k, v))
    vis = answers.get("visibility_public") or []
    if not isinstance(vis, list) or not all(isinstance(g, str) for g in vis):
        raise SetupError(USAGE, "visibility_public is a list of globs")
    for g in vis:
        _rel(top, g, "visibility_public")
        if g in ("**", "*", "**/*"):
            raise SetupError(USAGE, "visibility_public %r marks the whole repository public — name the folders" % g)
    nar = answers.get("narrator") or {}
    if not isinstance(nar, dict) or set(nar) - {"id", "engine", "style"}:
        raise SetupError(USAGE, "narrator is {\"id\", \"engine\", \"style\"}")
    nid = nar.get("id") or "narrator"
    if not narrator.ID.match(nid):
        raise SetupError(USAGE, "narrator.id is lowercase letters, digits and -")
    engine = nar.get("engine") or narrator.SUGGESTED[lang]
    if not narrator.engine_ok(engine):
        raise SetupError(USAGE, "narrator.engine must be qwen:<built-in speaker> (%s)"
                         % ", ".join(sorted(narrator.QWEN_SPEAKERS)))
    style = _text(nar.get("style", ""), "narrator.style", empty_ok=True, maximum=narrator.STYLE_MAX)
    s2v = answers.get("s2v_path")
    if not isinstance(s2v, str) or not os.path.isabs(s2v):
        raise SetupError(USAGE, "s2v_path must be the absolute path of this machine's script2video checkout")
    return {"language": lang, "studio_root": root, "project_name": project,
            "purpose": _text(answers.get("purpose") or "Videos made from this repository's writing.", "purpose"),
            "priorities": _text(answers.get("priorities") or "youtube: accuracy to the source first, then clarity",
                                "priorities"),
            "brand": {"name": _text(brand.get("name") or project, "brand.name"), "accent_color": color, "logo": logo},
            "public_domains": sorted(set(doms)), "web_roots": dict(sorted(wr.items())), "visibility_public": list(vis),
            "narrator": {"id": nid, "engine": engine, "style": style}, "husky": bool(answers.get("husky")),
            "s2v_path": os.path.normpath(s2v)}


def existing(top):
    """Why a first install is refused (3), or None."""
    rel = ".claude/studio/config.json"
    if os.path.lexists(os.path.join(top, rel)):
        return "a Studio harness is already here (%s) — use /std config or /std update" % rel
    if git(top, "ls-files", "--error-unmatch", "--", rel, check=False).returncode == 0:
        return "a Studio harness is staged in the index (%s) — use /std config or /std update" % rel
    if git(top, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0 and \
            git(top, "cat-file", "-e", "HEAD:%s" % rel, check=False).returncode == 0:
        return "HEAD has a Studio harness (%s) — check it out, or use /std config or /std update" % rel
    try:
        m = paths.marker_path(top)
        with open(m, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, RuntimeError):
        data = None
    if data is not None:
        root = data.get("studio_root") if isinstance(data, dict) else None
        return ("traces of an earlier Studio install remain (marker for studio_root %r) — ask the person whether to "
                "restore that harness from git or to remove the traces by hand" % root)
    return None


def _check_s2v(path, version):
    try:
        info = version(path)
    except Exception as e:  # noqa: BLE001 — collect.CollectError and friends
        raise SetupError(USAGE, "cannot read s2v --version --json at %s (%s)" % (path, e))
    if not isinstance(info, dict) or not info.get("id"):
        raise SetupError(USAGE, "s2v at %s reports no id" % path)
    if info.get("stale_build") is not False:
        raise SetupError(USAGE, "s2v's build at %s is stale (or unknown): run yarn build there first" % path)
    from ..state.flow import _semver
    have, want = _semver(info.get("version")), (0, 12, 1)
    if have is None or have < want:
        raise SetupError(USAGE, "s2v %s is older than 0.12.1" % info.get("version"))
    return info


def plan(top, answers, version=None, check_s2v=True):
    """The plan: the normalized answers, every file init writes with its sha, the s2v it found. Deterministic."""
    why = existing(top)
    if why:
        raise SetupError(REFUSED, why)
    a = normalize(top, answers)
    busy = analyze.studio_root_free(top, a["studio_root"])
    if busy:
        raise SetupError(REFUSED, busy)
    s2v = {"path": a["s2v_path"]}
    if check_s2v:
        if version is None:
            from ..state.collect import run_version as version
        info = _check_s2v(a["s2v_path"], version)
        s2v.update(id=info.get("id"), version=info.get("version"))
    files = render.harness_files(a)
    vals = render.values_of(a)
    plan_ = {"schema": PLAN_SCHEMA, "answers": a, "s2v": s2v,
             "files": {rel: render.sha(text) for rel, text in files.items()},
             "installed": render.installed(vals), "scripts": render.script_files(),
             "local": [machine.REL.replace(os.sep, "/"), ".claude/studio/local/config.internal.json"],
             "gitignore": "Studio's block in .gitignore and in info/exclude", "hooks": "hooks.py install%s"
             % (" --husky-apply" if a["husky"] else "")}
    # a partial earlier install: files that exist are replaced (M1c review P5); shown, and part of the sha
    plan_["replaces"] = sorted(rel for rel in list(files) + [render.INSTALLED, ".claude/studio/scripts"]
                               if os.path.lexists(os.path.join(top, rel)))
    plan_["sha"] = hashlib.sha256(json.dumps(plan_, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return plan_


def apply(top, plan_, env=None, version=None, check_s2v=True):
    """Write the harness. The plan is recomputed from its answers and must be the same (the templates or the
    repository did not change since it was shown)."""
    if not isinstance(plan_, dict) or plan_.get("schema") != PLAN_SCHEMA:
        raise SetupError(USAGE, "not an init plan (run init plan first)")
    again = plan(top, plan_.get("answers"), version=version, check_s2v=check_s2v)
    if again["sha"] != plan_.get("sha"):
        raise SetupError(FAIL, "the plan no longer matches (the repository, the templates or s2v changed since it "
                               "was shown) — run init plan again and show it to the person")
    a = again["answers"]
    files = render.harness_files(a)
    for rel, text in files.items():
        write_text(top, rel, text)
    write_text(top, render.INSTALLED, render.dump_json(again["installed"]))
    copy_scripts(top)
    gi = os.path.join(top, ".gitignore")
    try:
        with open(gi, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    write_text(top, ".gitignore", ignore.ensure(text, ignore.render(a["studio_root"])))
    os.makedirs(os.path.join(top, ".claude", "studio", "local"), exist_ok=True)
    paths.check_local(top, a["studio_root"])
    machine.write(top, a["s2v_path"])
    raw = json.dumps({"internal": {}}, ensure_ascii=False).encode("utf-8")
    write_text(top, ".claude/studio/local/config.internal.json", raw.decode("utf-8"))
    d = os.path.join(paths.backup_root(env), paths.repo_key(top))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "overlay.sha"), "w", encoding="utf-8") as f:
        f.write(hashlib.sha256(raw).hexdigest() + "\n")
    m = paths.marker_path(top, env)
    os.makedirs(os.path.dirname(m), exist_ok=True)
    with open(m, "w", encoding="utf-8") as f:
        json.dump({"studio_root": a["studio_root"]}, f)
    os.makedirs(os.path.join(top, a["studio_root"], "voices"), exist_ok=True)
    hooks = install_hooks(top, env, a["husky"])
    return {"wrote": sorted(list(files) + [render.INSTALLED, ".gitignore"]), "scripts": len(again["scripts"]),
            "hooks": hooks, "studio_root": a["studio_root"]}


def copy_scripts(top):
    """The plugin's scripts, exactly the manifest's files (the guard and setup.py stay in the plugin)."""
    dst = os.path.join(top, ".claude", "studio", "scripts")
    if os.path.islink(dst):
        raise SetupError(FAIL, ".claude/studio/scripts is a symbolic link")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    for rel in render.script_files():
        src = os.path.join(render.SCRIPTS, rel)
        p = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        shutil.copy2(src, p)
    return dst


def install_hooks(top, env, husky):
    from ..commit.gitx import Git
    from ..hooks import install as I
    g = Git(top, paths.git_env(env))
    g.cwd = g.toplevel()
    res = I.install(g, top, dict(env or os.environ), husky_apply=husky)
    return {"code": res.code, "manager": res.manager, "wrote": list(res.wrote), "problems": list(res.problems)}
