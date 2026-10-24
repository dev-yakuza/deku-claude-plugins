"""Rendering the harness from the plugin's templates (m1-plan §5.2 step 5; moved from tests' make_harness.py).

Everything here is a pure function of the answers (and the templates): `init plan` lists what `init apply` writes, and
`update` renders the same templates again with the values kept in installed.json to find what a new plugin changes."""

import collections
import hashlib
import json
import os
import re

from .. import SCRIPTS_VERSION, manifest, narrator

SCRIPTS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SKILL = os.path.dirname(SCRIPTS)
TEMPLATES = os.path.join(SKILL, "templates")
PLUGIN = os.path.dirname(os.path.dirname(SKILL))

# the agents init installs: the six spine roles and the external auditor (the conditional ones come with M3)
AGENTS = ("std-source-analyst", "std-strategist", "std-writer", "std-fact-checker", "std-visual-director",
          "std-distributor", "std-auditor")
PROTECTED_PERSONAS = (".claude/agents/std-fact-checker.md", ".claude/agents/std-source-analyst.md")  # P-PERS
PERSONA_START = "<!-- studio:persona:start -->"
PERSONA_END = "<!-- studio:persona:end -->"
INSTALLED = ".claude/studio/installed.json"
CONFIG = ".claude/studio/config.json"
PRONOUNCE = ".claude/studio/pronounce.json"

# repository file -> template file, for the files `update` compares three ways (m1-plan §5.4)
TEMPLATED = collections.OrderedDict([
    (".claude/studio/charter.md", "studio/charter.md.tmpl"),
    (".claude/studio/formats/youtube.md", "formats/youtube.md"),
    (".claude/studio/platforms/youtube.md", "platforms/youtube.md"),
    (".claude/studio/guides/script.md", "guides/script.md"),
    (".claude/studio/guides/board.md", "guides/board.md"),
    (".claude/studio/guides/copy.md", "guides/copy.md"),
] + [(".claude/agents/%s.md" % a, "agents/%s.md" % a) for a in AGENTS])


class RenderError(Exception):
    pass


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plugin_version():
    try:
        with open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            return json.load(f).get("version")
    except (OSError, ValueError):
        return None


def fill(text, values):
    for k, v in values.items():
        text = text.replace("{{%s}}" % k, v)
    m = re.search(r"\{\{[A-Z_]+\}\}", text)
    if m:
        raise RenderError("unfilled placeholder %s" % m.group(0))
    return text


def template(rel, values):
    with open(os.path.join(TEMPLATES, rel), encoding="utf-8") as f:
        return fill(f.read(), values)


def values_of(answers):
    """The placeholder values of the text templates (kept in installed.json for update)."""
    return {"LANGUAGE": answers["language"], "STUDIO_ROOT": answers["studio_root"],
            "PROJECT_NAME": answers["project_name"], "PURPOSE": answers["purpose"],
            "PRIORITIES_BY_KIND": answers["priorities"], "CHECKED_DATE": ""}


def config_of(answers):
    cfg = json.loads(template("studio/config.json.tmpl", {"LANGUAGE": answers["language"],
                                                          "STUDIO_ROOT": answers["studio_root"]}))
    cfg["visibility"]["public"] = list(answers["visibility_public"])
    cfg["public_domains"] = list(answers["public_domains"])
    cfg["web_roots"] = dict(answers["web_roots"])
    return cfg


def dump_json(v):
    return json.dumps(v, ensure_ascii=False, indent=2) + "\n"


def persona_block(text):
    """The persona region of an agent file (markers included), or None."""
    i = text.find(PERSONA_START)
    j = text.find(PERSONA_END)
    if i < 0 or j < i or text.count(PERSONA_START) != 1 or text.count(PERSONA_END) != 1:
        return None
    return text[i:j + len(PERSONA_END)]


def replace_persona(text, block):
    old = persona_block(text)
    if old is None:
        raise RenderError("no single persona region")
    return text.replace(old, block, 1)


def templated(values):
    """{repository path: rendered text} of the three-way files."""
    return collections.OrderedDict((rel, template(src, values)) for rel, src in TEMPLATED.items())


def harness_files(answers):
    """{repository path: text} of every committed harness file init writes, the scripts copy aside."""
    vals = values_of(answers)
    out = collections.OrderedDict()
    out[CONFIG] = dump_json(config_of(answers))
    brand = answers["brand"]
    out[".claude/studio/brand.json"] = template("studio/brand.json.tmpl", {
        "BRAND_NAME": json.dumps(brand["name"], ensure_ascii=False)[1:-1],
        "ACCENT_COLOR": brand["accent_color"],
        "LOGO": json.dumps(brand.get("logo") or "", ensure_ascii=False)[1:-1]})  # "" = no logo
    json.loads(out[".claude/studio/brand.json"])  # a template slip must not reach a repository
    out.update(templated(vals))
    out[PRONOUNCE] = "{}\n"  # the shared pronunciation dictionary: a flat object, reading by written form
    nar = answers["narrator"]
    base = "%s/cast/%s/" % (answers["studio_root"], nar["id"])
    out[base + "profile.md"] = template("cast/profile.md.tmpl", {"NARRATOR_ID": nar["id"]})
    out[base + "status.json"] = narrator.dumps(narrator.record(nar["id"], {answers["language"]: (nar["engine"],
                                                                                                 nar["style"])}))
    return out


def installed(values, texts=None):
    """installed.json: each three-way file's base (its rendered text's sha; for an agent its persona block's sha)."""
    texts = texts if texts is not None else templated(values)
    tpl = collections.OrderedDict()
    for rel, text in texts.items():
        ent = {"sha": sha(text)}
        if rel.startswith(".claude/agents/"):
            blk = persona_block(text)
            ent["persona"] = sha(blk) if blk is not None else None
        tpl[rel] = ent
    return {"schema": 1, "plugin_version": plugin_version(), "scripts_version": SCRIPTS_VERSION,
            "values": dict(values), "templates": tpl}


def script_files():
    """The plugin's scripts a repository copy carries (MANIFEST.sha256 included)."""
    return manifest.files(SCRIPTS) + [manifest.NAME]
