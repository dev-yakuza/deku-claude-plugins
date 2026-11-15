"""`setup.py platform list|preview|apply|remove` — a repository's platform rules
(`.claude/studio/platforms/<name>.md`, P-CRIT). Plugin-only, like config.

    platform list                               every platform file: audience, outputs, checked and its age, rules
                                                version, the videos in progress that name it (read-only)
    platform preview <name>                     the draft's lines, h12 and the label (read-only)
    platform remove-preview <name>              the removal's line, h12 and the label (read-only)
    platform apply <name> --expect <h12>        플랫폼 <h12>: the draft becomes the platform file, `checked` = today
    platform remove <name> --expect <h12>       플랫폼 <h12>: the file goes (refused while a video in progress names it)

The agent drafts (`/std platform add|refresh`: `.claude/studio/local/drafts/platforms/<name>.md`); a script writes
after the person's answer. The question must show every preview line — the guard compares them (`preview_lines` is
pure and shared with it), and apply checks them again before the answer is used up. `--proxy` is refused."""

import datetime
import hashlib
import json
import os
import re

from ..distribute import rules as rules_mod
from ..state.hashes import hash_of
from ..state.schema import NAME, KINDS
from . import labels as L
from .common import FAIL, NO_EVIDENCE, REFUSED, USAGE, SetupError, read_config, with_evidence, write_text

DRAFTS = ".claude/studio/local/drafts/platforms"
ASPECTS = ("16:9", "9:16", "1:1")  # s2v packages/core/src/schema.ts ASPECTS
LAYOUTS = ("presenter", "dialogue", "fullscreen", "shorts")  # s2v LAYOUTS
OUTPUT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
HOME = re.compile(r"/Users/[^/\s]+|/home/[^/\s]+|(?<![\w.])~/|[A-Za-z]:\\Users\\")
URL = re.compile(r"^https://[A-Za-z0-9.-]+(?::[0-9]+)?(/[^\s]*)?$")
SHORT = 160  # a preview line's value is shown whole; longer values are refused (a person cannot compare them)
CHECKED_DAYS = 180
MAX_CHARS = 64 * 1024  # a platform file or draft longer than this (characters) is refused (the guard reads it)


class PlatformProblem(Exception):
    pass


def draft_rel(name):
    return "%s/%s.md" % (DRAFTS, name)


def file_rel(name):
    return ".claude/studio/platforms/%s.md" % name


def _name(name):
    if not isinstance(name, str) or not NAME.match(name):
        raise SetupError(USAGE, "a platform name is letters, digits, _ and - (at most 64): %r" % (name,))
    return name


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _v(x):
    return "null" if x is None else json.dumps(x, ensure_ascii=False) if not isinstance(x, (int, str)) else str(x)


def body_of(text):
    """Everything after the frontmatter (the rules block and the copy notes, as the distributor reads them)."""
    end = text.find("\n---", 3)
    return text[end + 4:].lstrip("\n") if text.startswith("---") and end >= 0 else text


def preview_lines(name, text):
    """The lines a question must show for this draft (one per parsed key), or PlatformProblem. Pure: the guard calls
    it on the same draft."""
    if len(text) > MAX_CHARS:
        raise PlatformProblem("longer than %d characters" % MAX_CHARS)
    try:
        fm = rules_mod.frontmatter(text)
        rules, _checked = rules_mod.parse(text)
    except rules_mod.RulesProblem as e:
        raise PlatformProblem(str(e))
    unknown = sorted(set(fm) - {"platform", "audience", "checked", "outputs", "sources"})
    if unknown:
        raise PlatformProblem("unknown frontmatter keys: %s" % ", ".join(unknown))
    if fm.get("platform") != name:
        raise PlatformProblem("platform: must be %s (the file's name)" % name)
    if fm.get("audience") not in rules_mod.AUDIENCES:
        raise PlatformProblem("audience: must be public or internal")
    outs = fm.get("outputs")
    if not isinstance(outs, list) or not outs:
        raise PlatformProblem("outputs: lists at least one output (name, aspect, max_duration)")
    lines = ["플랫폼 %s — audience %s" % (name, fm["audience"])]
    seen = set()
    for o in outs:
        extra = sorted(set(o) - {"name", "aspect", "max_duration", "layout", "shot"})
        if extra:
            raise PlatformProblem("output keys %s are not read" % ", ".join(extra))
        n = o.get("name")
        if not isinstance(n, str) or not OUTPUT.match(n) or n in seen:
            raise PlatformProblem("an output needs a unique name (letters, digits, _ and -): %r" % (n,))
        seen.add(n)
        if o.get("aspect") not in ASPECTS:
            raise PlatformProblem("output %s: aspect must be one of %s" % (n, ", ".join(ASPECTS)))
        md = o.get("max_duration")
        if md is not None and not (isinstance(md, int) and not isinstance(md, bool) and md > 0):
            raise PlatformProblem("output %s: max_duration must be seconds (a whole number) or null" % n)
        if o.get("layout") is not None and o.get("layout") not in LAYOUTS:
            raise PlatformProblem("output %s: layout must be one of %s" % (n, ", ".join(LAYOUTS)))
        shot = o.get("shot")
        if shot is not None and (not isinstance(shot, str) or not OUTPUT.match(shot)):
            raise PlatformProblem("output %s: shot must be a word" % n)
        lines.append("플랫폼 %s — output %s: %s, max %s, layout %s%s" % (
            name, n, o["aspect"], "none" if md is None else "%d s" % md, o.get("layout") or "-",
            ", shot %s" % shot if shot else ""))
    for k in rules_mod.RULE_KEYS:
        if k in rules and k != "required":
            lines.append("플랫폼 %s — %s: %s" % (name, k, _v(rules[k])))
    for r in rules["required"]:
        lines.append("플랫폼 %s — required: %s" % (name, r))
    srcs = fm.get("sources") or []
    if not isinstance(srcs, list):
        raise PlatformProblem("sources: is a list of https addresses")
    for s in srcs:
        if not isinstance(s, str) or not URL.match(s):
            raise PlatformProblem("sources: %r is not an https address" % (s,))
        lines.append("플랫폼 %s — source: %s" % (name, s))
    if fm["audience"] == "public" and not srcs:
        raise PlatformProblem("sources: a public platform's rules name the help pages they were checked against")
    body = body_of(text)  # the prose the distributor reads as instructions: the person approves it too
    lines.append("플랫폼 %s — 본문 sha %s (%d줄)" % (name, _sha(body)[:12], len(body.splitlines())))
    long_ = [l for l in lines if len(l) > SHORT + len(name) + 12]
    if long_:
        raise PlatformProblem("a line is too long to show in a question: %s…" % long_[0][:60])
    return lines


def _check(top, name, text, env):
    """preview_lines plus what needs the repository: no home paths, no in-house terms (closed without the overlay)."""
    lines = preview_lines(name, text)
    hit = HOME.search(text)
    if hit:
        raise PlatformProblem("the draft shows a home path (%s)" % hit.group(0))
    from ..commit.harness import overlay_terms, term_hit
    cfg = read_config(top)
    st, terms = overlay_terms(top, cfg, env)
    if st == "missing":
        raise PlatformProblem("the internal overlay is missing or changed — the person recreates it (/std config)")
    t = term_hit(text, terms) if terms else None
    if t:
        raise PlatformProblem("the draft uses an in-house term (%s)" % t)
    return lines


def _read(top, rel, what):
    try:
        with open(os.path.join(top, rel), encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        raise SetupError(FAIL, "%s: %s is missing or unreadable" % (what, rel))


def apply_hash(name, text):
    return hash_of({"action": "platform-apply", "name": name, "draft": _sha(text)})[:12]


def remove_hash(name, text):
    return hash_of({"action": "platform-remove", "name": name, "file": _sha(text)})[:12]


def remove_lines(name, text):
    return ["플랫폼 %s — remove (file sha %s)" % (name, _sha(text)[:12])]


def preview(top, name, remove=False, env=None):
    _name(name)
    read_config(top)
    env = dict(os.environ if env is None else env)
    if remove:
        text = _read(top, file_rel(name), "remove")
        h, lines = remove_hash(name, text), remove_lines(name, text)
        busy = users(top, name)
        out = {"name": name, "action": "remove", "lines": lines, "h12": h, "label": L.platform_label(h)}
        if busy:
            out["refused"] = remove_refusal(top, name, busy)
        return out
    text = _read(top, draft_rel(name), "the draft")
    try:
        lines = _check(top, name, text, env)
    except PlatformProblem as e:
        raise SetupError(FAIL, "the draft %s: %s" % (draft_rel(name), e))
    h = apply_hash(name, text)
    exists = os.path.isfile(os.path.join(top, file_rel(name)))
    return {"name": name, "action": "refresh" if exists else "add", "lines": lines, "h12": h,
            "label": L.platform_label(h), "draft": draft_rel(name)}


def set_checked(text, day):
    """The text with the frontmatter's `checked` set to `day` (added after `audience:` when absent)."""
    end = text.find("\n---", 3)
    head, rest = text[:end], text[end:]
    if re.search(r"^checked:.*$", head, re.M):
        head = re.sub(r"^checked:.*$", 'checked: "%s"' % day, head, count=1, flags=re.M)
    else:
        m = re.search(r"^audience:[^\n]*$", head, re.M)
        at = m.end() if m else head.find("\n")
        head = head[:at] + '\nchecked: "%s"' % day + head[at:]
    return head + rest


def _shown(lines):
    def check(ev):  # before the answer is used up: the question showed every line
        from ..commit.summary import first_missing, missing_text
        q = ev.get("question")
        miss = first_missing(lines, q if isinstance(q, str) else "")
        if miss:
            raise SetupError(NO_EVIDENCE, "values-not-shown: %s" % missing_text(miss, "the preview"))
    return check


def _expect(p, expect):
    if not expect:
        raise SetupError(USAGE, "this needs the person's answer: show every line of `setup.py platform preview`, ask "
                                "for the option \"%s\", then run this again with --expect %s" % (p["label"], p["h12"]))
    if expect != p["h12"]:
        raise SetupError(FAIL, "--expect %s is not this change (%s) — preview again and show it to the person"
                         % (expect, p["h12"]))


def apply(top, name, expect, argv, proxy=False, env=None, today=None):
    if proxy:
        raise SetupError(USAGE, "platform rules are the person's: the proxy mode cannot (--proxy refused)")
    p = preview(top, name, env=env)
    _expect(p, expect)
    day = today or datetime.date.today().isoformat()

    def write():
        text = _read(top, draft_rel(name), "the draft")
        if apply_hash(name, text) != p["h12"]:
            raise SetupError(FAIL, "the draft changed — preview again")
        write_text(top, file_rel(name), set_checked(text, day))
        os.remove(os.path.join(top, draft_rel(name)))
        return [file_rel(name)]
    wrote = with_evidence(top, argv, p["label"], False, write, "platform apply", ev_check=_shown(p["lines"]))
    return dict(p, wrote=wrote, checked=day, next="commit the harness (/std init step 6: the harness commit)")


def users(top, name):
    """{video: [outputs of this platform]} of the videos in progress whose brief names the platform."""
    root = read_config(top).get("studio_root") or "studio"
    out = {}
    for base in (os.path.join(top, root, "videos"), os.path.join(top, root, "local", "videos")):
        for v in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            try:
                with open(os.path.join(base, v, "work", "state.json"), encoding="utf-8") as f:
                    st = json.load(f)
            except (OSError, ValueError):
                continue
            active = any(isinstance(lg, dict) and lg.get("status") == "active"
                         for lg in (st.get("langs") or {}).values())
            plats = ((st.get("brief") or {}).get("platforms") or {}) if isinstance(st.get("brief"), dict) else {}
            if active and isinstance(plats, dict) and name in plats:
                out[v] = {"outputs": list(plats[name] or []), "shared": sorted(
                    p for p, outs in plats.items() if p != name and set(outs or []) & set(plats[name] or []))}
    return out


def remove_refusal(top, name, busy):
    parts = []
    for v, u in sorted(busy.items()):
        if len(u["outputs"]) == 1 and not u["shared"]:
            parts.append("%s (abandon it, or state.py exclude-output %s %s — the platform goes with that output)"
                         % (v, v, u["outputs"][0]))
        else:
            parts.append("%s (abandon it: the platform shares its output with %s, and a platform alone cannot be "
                         "excluded)" % (v, ", ".join(u["shared"]) or "other outputs"))
    return "videos in progress name platform %s: %s" % (name, "; ".join(parts))


def remove(top, name, expect, argv, proxy=False, env=None):
    if proxy:
        raise SetupError(USAGE, "platform rules are the person's: the proxy mode cannot (--proxy refused)")
    p = preview(top, name, remove=True, env=env)
    if p.get("refused"):
        raise SetupError(REFUSED, p["refused"])
    _expect(p, expect)

    def write():
        os.remove(os.path.join(top, file_rel(name)))
        return [file_rel(name)]
    wrote = with_evidence(top, argv, p["label"], False, write, "platform remove", ev_check=_shown(p["lines"]))
    return dict(p, wrote=wrote, next="commit the harness (/std init step 6: the harness commit)")


def list_(top, today=None):
    read_config(top)
    d = os.path.join(top, ".claude", "studio", "platforms")
    day = today or datetime.date.today()
    out = []
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        name = fn[:-3]
        if not fn.endswith(".md") or not NAME.match(name):
            continue
        text = _read(top, file_rel(name), "list")
        ent = {"name": name}
        try:
            fm = rules_mod.frontmatter(text)
            ent.update(audience=fm.get("audience"), outputs=[
                "%s %s" % (o.get("name"), o.get("aspect")) for o in fm.get("outputs") or [] if isinstance(o, dict)])
        except rules_mod.RulesProblem as e:
            ent["problem"] = str(e)
        try:
            rules, checked = rules_mod.parse(text)
            raw = rules_mod.BLOCK.search(text).group(1)
            ent["rules"] = "v2" if any(k in json.loads(raw) for k in ("chapters", "link", "description_max_chars")) \
                or rules["title_max"] is None else "v1"
        except (rules_mod.RulesProblem, ValueError) as e:
            ent.setdefault("problem", str(e))
            checked = ""
        ent["checked"] = checked or None
        try:
            age = (day - datetime.date.fromisoformat(checked)).days if checked else None
        except ValueError:
            age = None
        ent["checked_days"] = age
        if checked and (age is None or age > CHECKED_DAYS):
            ent["warning"] = "checked more than %d days ago: /std platform refresh %s" % (CHECKED_DAYS, name)
        if not checked:
            ent["warning"] = "not checked yet: /std platform refresh %s" % name
        ent["videos"] = sorted(users(top, name))
        ent["kinds"] = sorted(k for k, sc in KINDS.items() if sc == ent.get("audience"))
        out.append(ent)
    return {"platforms": out, "drafts": sorted(f[:-3] for f in os.listdir(os.path.join(top, DRAFTS))
                                               if f.endswith(".md")) if os.path.isdir(os.path.join(top, DRAFTS))
            else []}
