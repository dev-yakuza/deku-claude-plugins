"""guildcore.config — `.claude/guild/config.json` and role personas.

`load()` never rejects a config for keys it does not know: 0.101.x ignores `config.engine.*`, and
this engine must ignore keys a LATER engine adds (forward-compatible schema, §10.5). Type errors in
a known `engine.*` key fall back to the default and are reported in `warnings` — a bad dial must
not stop status/resume.

`persona(role)` reads `.claude/agents/<role>.md`: frontmatter `model:` (default `sonnet` —
`_model_tiering.md` Section 0), the body, and the habit lines under `<!-- guild:persona:habits -->`.
`habits(tag)` filters by the `[J:<group>]` prefix tag (§8.1); before tagging is approved an
untagged habit loads only for KICKOFF and ESCALATE (§10.2-6, R3J-m5).
"""

import copy
import json
import os
import re

CONFIG_REL = os.path.join(".claude", "guild", "config.json")
AGENTS_REL = os.path.join(".claude", "agents")
DEFAULT_MODEL = "sonnet"
HABITS_MARKER = "<!-- guild:persona:habits -->"
UNTAGGED_GROUPS = ("KICKOFF", "ESCALATE")
TAG_RE = re.compile(r"\[J:([A-Z0-9_-]+)\]")

# §2.5 · §2.6 · §4.2 · §5.1 · §3.2 · §10.4 — every key the design names under `config.engine`.
ENGINE_DEFAULTS = {
    "answer_associations": ["OWNER", "MEMBER", "COLLABORATOR"],
    "attended_confirm_interpretation": False,
    "first_sprint_mode": "auto",                  # auto | on | off
    "budget_usd_per_issue": 35.0,
    "handoff_judge": "default",                   # default | always
    "max_parallel_roles": 3,
    "allowed_endpoints": [],
    "irreversible_globs": None,                   # None = ecosystem defaults (K4)
    "gate_triggers": [],
    "branch_template": None,
    "role_allow": {},
    "roles": {},
    "judges": {},
    "grading": {},                                # §9.5 grader: {"grader_model": "opus"} (K5r4)
    # §9.4-7 dual judgment (K6 item 11; user decision 4, 2026-11-19: ON from the first sprint — first-sprint mode
    # never turns it off): the deterministic share of §9.5 decisions judged again by another tier (monitoring)
    "dual_judge_rate": 0.10,
    # K2 r3 (user decision): git-ignored paths an OFFLINE TEST `effective` re-run may copy into its
    # temp tree — explicit relative paths (no globs), realpath-contained, never present during a
    # networked step; default empty = `unverified(secret-required)` when a test needs them.
    #   "effective": {"copy_ignored": ["assets/data.db", "lib/env/env.dart"]}
    "effective": {"copy_ignored": []},
}
ENUMS = {"first_sprint_mode": ("auto", "on", "off"), "handoff_judge": ("default", "always")}
_TYPES = {bool: (bool,), float: (int, float), int: (int,), list: (list,), dict: (dict,),
          str: (str,)}


class ConfigError(Exception):
    pass


def command_list(v):
    """0.102.16 (japanlifeinfo #227): a `commands.*` value is a string OR a list of strings (`"e2e": ["pnpm build:e2e",
    "pnpm --filter visa-home test:e2e"]`) — [] / [str, …]. The one reader for every place that runs or compares one."""
    if v is None or v == "" or v is False:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x is not None and str(x).strip()]
    return [str(v)]


def command_text(v):
    """A `commands.*` value as ONE line for a person / a role input (a list → `a && b`), or None when unset."""
    xs = command_list(v)
    return " && ".join(xs) if xs else None


class Config(object):
    def __init__(self, raw, root, warnings):
        self.raw = raw
        self.root = root
        self.warnings = warnings
        self.language = raw.get("language") or "en"
        self.version = raw.get("version")
        self.roles = list(raw.get("roles") or [])
        self.commands = raw.get("commands") or {}
        self.engine, self.engine_unknown = _engine(raw.get("engine"), warnings)

    def get(self, dotted, default=None):
        cur = self.raw
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def persona(self, role):
        return persona(self.root, role)


def _engine(section, warnings):
    eng = copy.deepcopy(ENGINE_DEFAULTS)
    unknown = []
    if section is None:
        return eng, unknown
    if not isinstance(section, dict):
        warnings.append("config.engine is not an object — defaults used")
        return eng, unknown
    for k, v in section.items():
        if k not in ENGINE_DEFAULTS:
            unknown.append(k)              # a later engine's key: keep, never fail
            eng[k] = v
            continue
        d = ENGINE_DEFAULTS[k]
        if d is None:
            if v is None or isinstance(v, (str, list)):
                eng[k] = v
            else:
                warnings.append("config.engine.%s has the wrong type — default used" % k)
            continue
        ok = isinstance(v, _TYPES[type(d)]) and not (type(d) is not bool and isinstance(v, bool))
        if ok and k in ENUMS and v not in ENUMS[k]:
            ok = False
        if ok:
            eng[k] = float(v) if isinstance(d, float) else v
        else:
            warnings.append("config.engine.%s has the wrong type or value — default used" % k)
    return eng, unknown


def config_path(root):
    return os.path.join(root, CONFIG_REL)


def exists(root):
    return os.path.isfile(config_path(root))


def load(root="."):
    p = config_path(root)
    try:
        with open(p, encoding="utf-8") as fh:
            raw = json.load(fh)
    except IOError:
        raise ConfigError("Guild not initialized (run `/gld init`).")
    except ValueError as e:
        raise ConfigError("config.json is not valid JSON: %s" % e)
    if not isinstance(raw, dict):
        raise ConfigError("config.json is not a JSON object")
    return Config(raw, root, [])


class Persona(object):
    def __init__(self, role, model, body, habit_lines):
        self.role = role
        self.model = model
        self.body = body
        self.habit_lines = habit_lines

    def habits(self, tag=None):
        if tag is None:
            return list(self.habit_lines)
        out = []
        for h in self.habit_lines:
            tags = TAG_RE.findall(h)
            if tag in tags or (not tags and tag in UNTAGGED_GROUPS):
                out.append(h)
        return out


def _frontmatter(text):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    fm = {}
    for ln in text[4:end].split("\n"):
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", ln)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"')
    rest = text[end + 4:]
    return fm, rest[1:] if rest.startswith("\n") else rest


def persona(root, role):
    p = os.path.join(root, AGENTS_REL, role + ".md")
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    fm, body = _frontmatter(text)
    habits = []
    i = body.find(HABITS_MARKER)
    if i >= 0:
        for ln in body[i + len(HABITS_MARKER):].split("\n"):
            if ln.startswith("## ") or ln.startswith("<!-- guild:persona:"):
                break
            if ln.startswith("- ") and "(아직 없음" not in ln:
                habits.append(ln)
    return Persona(role, fm.get("model") or DEFAULT_MODEL, body, habits)
