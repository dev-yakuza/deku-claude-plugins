"""init: the parts of the harness the engine decides (readiness T2 — design/guild/24-redesign/readiness/promote/t2-init.md).

  roles    (R4-3, parity P6) which role files init §2 writes and how the existing ones differ from this plugin's
           templates. Only a channel whose value `writes_role_files` is on (channel.VALUES — the stable channel) writes
           role files, and then only the MISSING ones: an existing `.claude/agents/<role>.md` is never written over —
           its differences are reported. The LLM command fills the templates (P1 scans, P1.5 interview) and writes the
           files `write` names; the engine writes no role file itself. Read only.
  migrate  (parity P4, R4-13 H1) a repository the 0.98.x Guild set up in THIS channel's settings folder — a `config.json`
           in the 0.98.x form (no `format`) and no `harness.json`. That happens in the stable channel, whose folder is
           the 0.98.x one: the first promotion. Dry run by default (what would change, what is kept); `--apply` first
           copies every file it changes into a backup folder of the engine home (manifest.json), then
             - writes `harness.json` from the 0.98.x settings: language, roles (the role files that exist), commands,
               automation, sprint — `sprint.history` copied as it is (H1: the next retro replaces-or-appends by sprint,
               the engine never reads it, so a 0.98.x tracker such as word_app #1923 runs on unchanged);
             - takes `gates` out of the 0.98.x config.json (F13: removed on purpose — the commit gate reads
               `gates.enabled` and has no off-switch any more); everything else stays in that file for P2.9, whose draft
               tool reads the 0.98.x commands, visual and engine keys from it; P2.9 `init write` replaces it;
             - puts this plugin's commit gate script in place and points the pre-commit hook at it (channel.plan_hook —
               the switch's hook code, T1);
             - adds the missing lines of the folder's `.gitignore`.
           Role files, CLAUDE.md, docs/standards, the knowledge, the evolve ledger, memory, overlay, the gate's rules and
           every other file are kept as they are. The record `migrated.json` (engine home, init folder) lets P2.9 treat
           the 0.98.x config.json as "no engine settings yet" and `init write` replace it.
"""

import datetime
import difflib
import hashlib
import json
import os
import re
import shutil

from . import channel, defaults, fsafe, github, initconfig, paths as pathsmod, store

AGENTS_DIR = ".claude/agents"                     # promote: literal — the role files are the same in both channels
TEMPLATES = os.path.join("skills", "gld", "templates", "agents")    # promote: self — this plugin's role templates
ROSTER = ("leader", "tech-lead", "developer", "tester", "product-owner", "qa", "designer", "infra", "dba", "security",
          "performance", "i18n", "analytics", "tech-writer", "release-manager", "support-triage")
"""The full roster init §2 installs (0.98.7 init §2, `harness.json` `roles` order)."""
CENTRAL_KEYS = ("name", "model")
"""Frontmatter keys this plugin owns (0.98.7 init §2: `update` refreshes them, the rest of the frontmatter is local)."""
PERSONA_START = defaults.MARKER_PREFIX + "persona:start -->"
PERSONA_END = defaults.MARKER_PREFIX + "persona:end -->"
PERSONA_HABITS = defaults.MARKER_PREFIX + "persona:habits -->"
MAX_ROLE_BYTES = 256 * 1024

EXIT_OK = 0
EXIT_REFUSED = 4


class Refused(Exception):
    """The action is refused; nothing was written."""


def _read(path, root):
    try:
        return fsafe.read_bytes(path, root=root, max_bytes=MAX_ROLE_BYTES).decode("utf-8", "replace")
    except FileNotFoundError:
        return None


def _frontmatter(text):
    """{key: value} of the leading `---` block (one-line values), {} without one."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"')
    return {}


def _region(text):
    """The text between the persona markers (stripped lines), or None without exactly one pair in order."""
    lines = [x.rstrip() for x in text.replace("\r\n", "\n").split("\n")]
    if lines.count(PERSONA_START) != 1 or lines.count(PERSONA_END) != 1:
        return None
    a, b = lines.index(PERSONA_START), lines.index(PERSONA_END)
    return lines[a + 1:b] if a < b else None


def differences(text, template):
    """What a role file that exists differs in from this plugin's template — [one line each], [] = nothing the engine
    can compare differs. Compared: the central frontmatter keys, the three persona markers (exactly once each), the
    region between the start / end markers (a translated region always differs: `update` refreshes it), and a
    placeholder left in the file."""
    out = []
    mine, theirs = _frontmatter(text), _frontmatter(template)
    if not mine:
        out.append("no frontmatter (`---` block) at the top")
    for k in CENTRAL_KEYS:
        if mine and mine.get(k) != theirs.get(k):
            out.append(f"frontmatter {k}: {mine.get(k)!r} (template {theirs.get(k)!r})")
    lines = [x.rstrip() for x in text.replace("\r\n", "\n").split("\n")]
    for marker in (PERSONA_START, PERSONA_END, PERSONA_HABITS):
        n = lines.count(marker)
        if n != 1:
            out.append(f"{marker} appears {n} time(s), not once — `update` cannot refresh the persona region")
    a, b = _region(text), _region(template)
    if a is not None and b is not None and a != b:
        changed = sum(1 for d in difflib.ndiff(b, a) if d[:1] in "+-")
        out.append(f"the persona region differs from this plugin's template ({changed} line(s) added or removed) — "
                   f"a translated region always differs; `/{channel.SELF} update` refreshes it")
    if "{{" in text:
        out.append("a `{{…}}` placeholder is left in the file")
    return out


def template_text(plugin_root, role):
    with open(os.path.join(plugin_root, TEMPLATES, role + ".md"), encoding="utf-8") as f:
        return f.read()


def roles(top, plugin_root):
    """{writes_role_files, channel, dir, roster, write, missing, existing: [{role, path, differences}], others, roles}.
    `write` = the roles init §2 writes now (missing ones, only when this channel writes role files); `roles` = the
    names `harness.json` lists once `write` is written (roster order, then the others)."""
    writes = channel.value("writes_role_files")
    folder = os.path.join(top, AGENTS_DIR)
    if os.path.islink(folder) or (os.path.lexists(folder) and not os.path.isdir(folder)):
        raise Refused(f"{AGENTS_DIR} is not a plain folder")
    present = set()
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            p = os.path.join(folder, f)
            if f.endswith(".md") and os.path.isfile(p) and not os.path.islink(p):
                present.add(f[:-3])
    missing = [r for r in ROSTER if r not in present]
    existing = []
    for r in ROSTER:
        if r not in present:
            continue
        path = f"{AGENTS_DIR}/{r}.md"
        diff = differences(_read(os.path.join(top, path), top) or "", template_text(plugin_root, r)) if writes else []
        existing.append({"role": r, "path": path, "differences": diff})
    others = sorted(present - set(ROSTER))
    write = list(missing) if writes else []
    listed = [r for r in ROSTER if r in present or r in write] + others
    return {"channel": channel.SELF, "writes_role_files": writes, "dir": AGENTS_DIR, "roster": list(ROSTER),
            "write": write, "missing": missing, "existing": existing, "others": others, "roles": listed}


def format_roles(rep):
    have = len(rep["roster"]) - len(rep["missing"])
    lines = [f"role files ({rep['dir']}/): {have} of {len(rep['roster'])} exist"
             + (f" — this channel ({rep['channel']}) writes the missing ones" if rep["writes_role_files"] else
                f" — this channel ({rep['channel']}) writes no role file: the stable channel's init writes them")]
    if rep["write"]:
        lines.append("write (missing): " + ", ".join(rep["write"]))
    elif rep["missing"]:
        lines.append("missing: " + ", ".join(rep["missing"]))
    if rep["writes_role_files"] and rep["existing"]:
        lines.append("kept as they are (init never writes over a role file):")
        for e in rep["existing"]:
            lines += [f"  {e['role']}: {d}" for d in e["differences"]] or [f"  {e['role']}: as the template"]
    if rep["others"]:
        lines.append("other role files (not in the roster, kept): " + ", ".join(rep["others"]))
    lines.append("harness.json roles: " + (", ".join(rep["roles"]) or "(none)"))
    return "\n".join(lines) + "\n"


# --- migrate: a 0.98.x install in this channel's settings folder (parity P4, R4-13 H1) --------------------------------

SELF_DIR = channel.CONFIG_DIR[channel.SELF]
GATE_REL = f"{SELF_DIR}/{channel.GATE_SCRIPT}"
PLUGIN_GATE = channel.DETECTOR                    # the plugin's gate_precommit.py — init §1 copies it verbatim
GITIGNORE_REL = f"{SELF_DIR}/.gitignore"
GITIGNORE_LINES = ("memory/", ".gld-sprint-*.window", ".gld-sprint-*.board",      # promote: self — init §1's lines
                   "gates/scripts/local/__pycache__/")
LABELS = ("analyze", "design", "execute", "test", "qa", "done", "child", "children", "harness", "needs-human", "sprint")
"""init §7's labels (without the prefix)."""
SPRINT_KEYS = ("capacity", "max_stack_depth", "refactor_slot", "history", "board", "window")
SPRINT_DEFAULTS = {"capacity": None, "max_stack_depth": 3, "refactor_slot": True, "history": [], "board": None,
                   "window": None}
REMOVED = {"gates": "removed on purpose — the commit gate has no off-switch any more (parity F13)"}
NOT_CARRIED = {"visual": "P2.9's draft tool makes the engine's verification rules from it",
               "engine": "P2.9's draft tool reads its irreversible globs and copy list",
               "local_developer": "no counterpart in this Guild",
               "version": "harness.json gets this plugin's version"}
CARRIED = ("language", "roles", "commands", "automation", "sprint")
KEPT_IN_DIR = ("knowledge", "evolution-log.md", "evolution-log.archive.md", "memory", "overlay", "readiness-report.md",
               "gates/rules", "gates/dismissed.md", "gates/findings.json", "gates/scripts/local")
"""What the 0.98.x folder holds that the migration names as kept (anything else in it is kept too, unnamed)."""
MAX_SETTINGS_BYTES = 4 * 1024 * 1024
BACKUP_PREFIX = "migrate-"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read_bytes(top, rel):
    try:
        return fsafe.read_bytes(os.path.join(top, rel), root=top, max_bytes=MAX_SETTINGS_BYTES)
    except FileNotFoundError:
        return None


def plugin_version(plugin_root):
    with open(os.path.join(plugin_root, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
        return json.load(f)["version"]


def harness_from(cfg, role_names, version):
    """harness.json (init §1's M1 subset, H13) from the 0.98.x settings → (harness, dropped sprint keys). Values are
    carried as they are; `sprint.history` keeps every entry byte for byte (H1)."""
    sprint_in = cfg.get("sprint") if isinstance(cfg.get("sprint"), dict) else {}
    history = sprint_in.get("history", [])
    if not isinstance(history, list):
        raise Refused("the 0.98.x sprint.history is not a list — nothing is migrated; a human looks at config.json")
    sprint = {k: sprint_in.get(k, SPRINT_DEFAULTS[k]) for k in SPRINT_KEYS}
    automation = cfg.get("automation") if isinstance(cfg.get("automation"), dict) else {"evolve_nudge": True}
    harness = {"version": version, "language": cfg.get("language") or "en", "roles": list(role_names),
               "commands": cfg.get("commands") if isinstance(cfg.get("commands"), dict) else {},
               "automation": automation, "sprint": sprint}
    return harness, sorted(set(sprint_in) - set(SPRINT_KEYS))


def _list_dir(top, rel):
    p = os.path.join(top, rel)
    try:
        return sorted(os.listdir(p)) if os.path.isdir(p) and not os.path.islink(p) else None
    except OSError:
        return None


def _kept(top, cfg_dir):
    """[(where, what)] the migration names as kept."""
    out = []
    agents = _list_dir(top, AGENTS_DIR)
    if agents is not None:
        out.append((f"{AGENTS_DIR}/", f"{sum(1 for a in agents if a.endswith('.md'))} role file(s) — never written over"))
    if os.path.isfile(os.path.join(top, "CLAUDE.md")):
        block = defaults.MARKER_PREFIX + "start -->"
        has = block in (_read_bytes(top, "CLAUDE.md") or b"").decode("utf-8", "replace")
        out.append(("CLAUDE.md", "kept as it is" + (" (its Guild block is not replaced)" if has else "")))
    std = _list_dir(top, "docs/standards")
    if std is not None:
        out.append(("docs/standards/", f"{sum(1 for s in std if s.endswith('.md'))} file(s)"))
    facts = _list_dir(top, defaults.KNOWLEDGE_DIR + "/facts")
    if _list_dir(top, defaults.KNOWLEDGE_DIR) is not None:
        idx = "index.md + " if os.path.isfile(os.path.join(top, defaults.KNOWLEDGE_DIR, "index.md")) else ""
        out.append((f"{defaults.KNOWLEDGE_DIR}/", f"{idx}{len(facts or [])} fact file(s) (shared by both channels)"))
    if os.path.isfile(os.path.join(top, ".claude", "settings.json")):
        out.append((".claude/settings.json", "init step 5 adds only what is missing"))
    named = [k for k in KEPT_IN_DIR if os.path.lexists(os.path.join(top, cfg_dir, k))
             and f"{cfg_dir}/{k}" != defaults.KNOWLEDGE_DIR]
    if named:
        out.append((f"{cfg_dir}/", ", ".join(k + ("/" if os.path.isdir(os.path.join(top, cfg_dir, k)) else "")
                                              for k in named)))
    known = {"config.json", "harness.json", ".gitignore", "gates", "procedures", "roles"} | {k.split("/")[0] for k in KEPT_IN_DIR}
    rest = [e for e in (_list_dir(top, cfg_dir) or []) if e not in known]
    if rest:
        out.append((f"{cfg_dir}/", "not read by the engine, kept: " + ", ".join(rest[:8]) + (" …" if len(rest) > 8 else "")))
    return out


def _labels(gh):
    """(names of this channel's labels that exist, problem) — read once; None names when GitHub did not answer."""
    if gh is None:
        return None, "no GitHub repository"
    try:
        got = gh.api("GET", gh.path("labels") + "?per_page=100", paginate=True) or []
    except (github.GhError, ValueError) as e:
        return None, str(e)
    names = {(x.get("name") or "") for x in got if isinstance(x, dict)}
    return sorted(n for n in names if n.startswith(defaults.LABEL_PREFIX)), None


def record_path(home, repo):
    return os.path.join(pathsmod.init_dir(home, repo), initconfig.MIGRATED)


def read_record(home, repo):
    ep = pathsmod.EnginePaths(home, repo, 1)
    try:
        raw = fsafe.read_bytes(record_path(home, repo), root=store._root(ep), max_bytes=1024 * 1024)
    except FileNotFoundError:
        return None
    return store.loads_strict(raw.decode("utf-8"), initconfig.MIGRATED)


def state_of(top, home, repo):
    """(state, config, text): none · initialized · legacy · migrated · conflict · unreadable — and the 0.98.x settings
    (dict) with their bytes when there are any."""
    raw = _read_bytes(top, defaults.ENGINE_SETTINGS)
    has_harness = os.path.lexists(os.path.join(top, defaults.HARNESS_SETTINGS))
    if raw is None:
        return ("initialized" if has_harness else "none"), None, None
    legacy = initconfig.legacy_settings(raw.decode("utf-8", "replace"))
    if legacy is None:
        return "unreadable", None, raw
    if not legacy:
        return "initialized", None, raw
    cfg = json.loads(raw.decode("utf-8"))
    if not has_harness:
        return "legacy", cfg, raw
    return ("migrated" if read_record(home, repo) is not None else "conflict"), cfg, raw


_NUM = "\x00gx-number:"


def _without_keys(raw, keys):
    """The 0.98.x config.json bytes without the top-level `keys`, written back as indent-2 JSON — every number
    keeps the text it had (FC M1: `0.10` stays `0.10`, not `0.1`). A file that already holds a NUL escape
    falls back to plain JSON numbers (values are the same either way)."""
    text = raw.decode("utf-8")
    keep = "\\u0000" not in text
    obj = json.loads(text, parse_float=(lambda s: _NUM + s + "\x00") if keep else None)
    out = json.dumps({k: v for k, v in obj.items() if k not in keys}, ensure_ascii=False, indent=2) + "\n"
    if keep:
        out = re.sub(r'"\\u0000gx-number:([-+.0-9eE]+)\\u0000"', r"\1", out)
    return out.encode("utf-8")


def plan_migration(top, repo, plugin_root, home, environ, gh=None, now=None):
    """What `init migrate` does — decided before anything is written (the dry run shows exactly this)."""
    state, cfg, raw = state_of(top, home, repo)
    rep = {"state": state, "repo": repo, "top": top, "dir": SELF_DIR, "settings": defaults.ENGINE_SETTINGS,
           "harness": defaults.HARNESS_SETTINGS, "done": False, "changes": [], "kept": [], "not_carried": [],
           "removed": [], "labels": None, "notes": [], "backup": None, "record": None}
    if state == "unreadable":
        raise Refused(f"{defaults.ENGINE_SETTINGS} is not a JSON object — nothing is migrated; a human looks at it")
    if state == "conflict":
        raise Refused(f"{defaults.ENGINE_SETTINGS} is in the 0.98.x form and {defaults.HARNESS_SETTINGS} exists, but "
                      "this machine has no record of a migration — nothing is migrated: move one of them away (both "
                      "are in git) and run init migrate again")
    if state == "migrated":
        rec = read_record(home, repo)
        rep["backup"], rep["record"] = rec.get("backup"), rec
        rep["notes"].append(f"moved on {rec.get('at')} (backup {rec.get('backup')}) — next: P2.9 makes the "
                            f"engine settings; `init write` replaces the 0.98.x {defaults.ENGINE_SETTINGS}")
        return rep, None
    if state != "legacy":
        return rep, None
    rep["version_0987"] = cfg.get("version")
    rl = roles(top, plugin_root)
    have = rl["roles"] if not rl["write"] else [r for r in rl["roles"] if r not in rl["write"]]
    harness, dropped_sprint = harness_from(cfg, have, plugin_version(plugin_root))
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    rep["backup"] = os.path.join(pathsmod.init_dir(home, repo), BACKUP_PREFIX + stamp)
    writes = []                                                    # (rel or abs path, bytes, mode, root, action)

    def change(path, data, mode, root, action, line):
        writes.append((path, data, mode, root, action))
        rep["changes"].append({"path": path, "action": action, "line": line})

    hist = harness["sprint"]["history"]
    newest = max((h.get("sprint") for h in hist if isinstance(h, dict) and isinstance(h.get("sprint"), int)), default=None)
    cmds = " · ".join(k for k, v in harness["commands"].items() if v) or "none"
    change(defaults.HARNESS_SETTINGS, (json.dumps(harness, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), 0o644,
           top, "write", f"language {harness['language']}, {len(harness['roles'])} role(s), commands {cmds}, sprint "
           f"capacity {harness['sprint']['capacity']}, history {len(hist)} entr{'y' if len(hist) == 1 else 'ies'} "
           f"copied as they are" + (f" (the newest #{newest})" if newest is not None else ""))
    legacy_roles = [r for r in cfg.get("roles") or () if isinstance(r, str) and r not in have]
    if legacy_roles:
        rep["notes"].append("0.98.x roles without a role file (not listed in harness.json): " + ", ".join(legacy_roles))
    if not have:
        rep["notes"].append("no role file exists — `init roles` says whether this channel writes them")
    for k in REMOVED:
        if k in cfg:
            off = isinstance(cfg[k], dict) and cfg[k].get("enabled") is False
            rep["removed"].append({"key": k, "value": cfg[k], "why": REMOVED[k]})
            why = ("gates.enabled was false: the commit gate was OFF and is ON from now — it has no off-switch any more"
                   if off else f"{REMOVED[k]}")
            change(defaults.ENGINE_SETTINGS, _without_keys(raw, REMOVED), None, top, "change", f"`{k}` taken out ({why})")
    for k, why in NOT_CARRIED.items():
        if k in cfg:
            rep["not_carried"].append({"key": k, "why": why})
    for k in sorted(set(cfg) - set(CARRIED) - set(NOT_CARRIED) - set(REMOVED)):
        rep["not_carried"].append({"key": k, "why": "no counterpart in harness.json — it stays in the 0.98.x "
                                                    "config.json until P2.9 replaces that file"})
    for k in dropped_sprint:
        rep["not_carried"].append({"key": f"sprint.{k}", "why": "no counterpart in harness.json"})
    with open(os.path.join(plugin_root, PLUGIN_GATE), "rb") as f:
        gate = f.read()
    old_gate = _read_bytes(top, GATE_REL)
    if old_gate != gate:
        change(GATE_REL, gate, None if old_gate is not None else 0o644, top, "update" if old_gate is not None else "write",
               "this plugin's commit gate" + (" (the old copy is backed up)" if old_gate is not None else ""))
    hook = channel.plan_hook(top, plugin_root, channel.SELF, environ)
    for path, text, mode, root in hook["write"]:
        change(path, text.encode("utf-8"), mode, root, "hook", "pre-commit hook / hook manager: the gate of this "
               f"channel ({channel.gate_path(channel.SELF)})")
    if hook["move"]:
        rep["changes"].append({"path": hook["move"][0], "action": "move", "line": f"→ {hook['move'][1]} (still runs first)"})
    rep["hook"] = {"kind": hook["kind"], "manual": hook["manual"], "move": hook["move"]}
    rep["notes"] += [n for n in hook["notes"] if hook["manual"] or "already runs" in n or "not installed here" in n]
    ign = (_read_bytes(top, GITIGNORE_REL) or b"").decode("utf-8", "replace")
    have_lines = {x.strip() for x in ign.splitlines()}
    add = [x for x in GITIGNORE_LINES if x not in have_lines]
    if add:
        text = ign + ("" if not ign or ign.endswith("\n") else "\n") + "\n".join(add) + "\n"
        change(GITIGNORE_REL, text.encode("utf-8"), None if ign else 0o644, top, "add", ", ".join(add))
    rep["kept"] = [{"path": p, "line": t} for p, t in _kept(top, SELF_DIR)]
    names, problem = _labels(gh)
    want = [defaults.LABEL_PREFIX + n for n in LABELS]
    rep["labels"] = {"exist": names, "missing": None if names is None else [n for n in want if n not in names],
                     "problem": problem}
    rep["notes"].append(f"{defaults.ENGINE_SETTINGS} stays the 0.98.x file until P2.9 `init write` replaces it with the "
                        "engine settings — the engine refuses to run an Issue until then")
    rep["settings_sha256"] = _sha(raw)
    return rep, {"writes": writes, "hook": hook, "raw": raw}


def _backup(rep, plan, home):
    """Copy every file the migration changes (and the 0.98.x settings as they were) into the backup folder."""
    folder = rep["backup"]
    root = store._root(pathsmod.EnginePaths(home, rep["repo"], 1))
    fsafe.make_dirs(os.path.join(folder, "files"), root=root)
    entries = []
    paths = [defaults.ENGINE_SETTINGS] + [w[0] for w in plan["writes"]] + ([plan["hook"]["move"][0]] if plan["hook"]["move"] else [])
    for i, path in enumerate(dict.fromkeys(paths)):
        full = path if os.path.isabs(path) else os.path.join(rep["top"], path)
        try:
            with open(full, "rb") as f:
                data = f.read()
            mode = os.stat(full).st_mode & 0o777
        except FileNotFoundError:
            entries.append({"path": path, "existed": False, "backup": None, "sha256": None, "mode": None})
            continue
        name = f"{i:02d}-" + re.sub(r"[^\w.-]", "_", path.strip("/"))[-120:]
        fsafe.write_bytes(os.path.join(folder, "files", name), data, root=root, mode=0o600)
        entries.append({"path": path, "existed": True, "backup": f"files/{name}", "sha256": _sha(data), "mode": mode})
    manifest = {"format": 1, "repo": rep["repo"], "top": rep["top"], "at": store.now_ts(), "files": entries,
                "undo": "copy each file back from files/ (mode as listed), delete the ones with existed: false; the "
                        "committed state is also in git"}
    fsafe.write_json(os.path.join(folder, "manifest.json"), manifest, root=root)
    return entries


def _restore(rep, entries):
    for e in entries:
        full = e["path"] if os.path.isabs(e["path"]) else os.path.join(rep["top"], e["path"])
        if e["existed"]:
            with open(os.path.join(rep["backup"], e["backup"]), "rb") as f:
                data = f.read()
            with open(full, "wb") as f:
                f.write(data)
            os.chmod(full, e["mode"])
        elif os.path.lexists(full):
            os.unlink(full)


def apply_migration(rep, plan, home):
    if os.path.lexists(os.path.join(rep["top"], defaults.HARNESS_SETTINGS)):
        raise Refused(f"{defaults.HARNESS_SETTINGS} appeared meanwhile — nothing is migrated")
    entries = _backup(rep, plan, home)
    try:
        if plan["hook"]["move"]:
            os.rename(*plan["hook"]["move"])
        for path, data, mode, root, _ in plan["writes"]:
            full = path if os.path.isabs(path) else os.path.join(rep["top"], path)
            if mode is None:
                mode = os.stat(full).st_mode & 0o777
            fsafe.make_dirs(os.path.dirname(full), root=root, mode=0o755)
            fsafe.write_bytes(full, data, root=root, mode=mode)
    except (OSError, fsafe.UnsafePath) as e:
        if plan["hook"]["move"] and os.path.lexists(plan["hook"]["move"][1]) and not os.path.lexists(plan["hook"]["move"][0]):
            os.rename(plan["hook"]["move"][1], plan["hook"]["move"][0])
        _restore(rep, entries)
        raise Refused(f"{e} — what was written is put back from {rep['backup']}") from e
    after = _read_bytes(rep["top"], defaults.ENGINE_SETTINGS)
    rec = {"format": 1, "repo": rep["repo"], "top": rep["top"], "at": store.now_ts(), "backup": rep["backup"],
           "settings_sha256_before": rep["settings_sha256"], "settings_sha256": _sha(after or b"")}
    ep = pathsmod.EnginePaths(home, rep["repo"], 1)
    fsafe.write_json(record_path(home, rep["repo"]), rec, root=store._root(ep))
    rep["done"], rep["record"] = True, rec
    return rep


def migrate(top, repo, plugin_root, home, environ, gh=None, apply=False, now=None):
    """`engine.py init migrate`: the report (a dry run unless `apply`). Refused (nothing written) when it cannot."""
    pathsmod.split_repo(repo)
    rep, plan = plan_migration(top, repo, plugin_root, home, environ, gh=gh, now=now)
    if apply and plan is not None:
        apply_migration(rep, plan, home)
    return rep


def format_migrate(rep):
    s = rep["state"]
    if s in ("none", "initialized"):
        return (f"no 0.98.x settings in {rep['dir']}/ — nothing to migrate"
                + (" (this channel's harness is there)" if s == "initialized" else "") + "\n")
    if s == "migrated":
        return "\n".join(["migrated already"] + [f"  {n}" for n in rep["notes"]]) + "\n"
    head = "migrated" if rep["done"] else "the migration would"
    lines = [f"0.98.x Guild settings found in {rep['dir']}/ (config.json version {rep.get('version_0987')}, no "
             f"harness.json) — {head}:"]
    lines += [f"  {c['action']:<7} {c['path']} — {c['line']}" for c in rep["changes"]]
    lines += [f"  keep    {k['path']} — {k['line']}" for k in rep["kept"]]
    lab = rep["labels"]
    if lab["exist"] is None:
        lines.append(f"  labels  not read ({lab['problem']}) — init step 7 makes them either way")
    else:
        lines.append(f"  labels  {len(lab['exist'])} {defaults.LABEL_PREFIX} label(s) exist — kept; init step 7 "
                     + (f"creates {', '.join(lab['missing'])} and " if lab["missing"] else "")
                     + "refreshes their color and description (--force)")
    if rep["not_carried"]:
        lines.append("  not carried into harness.json: " + "; ".join(f"{n['key']} ({n['why']})" for n in rep["not_carried"]))
    lines += [f"  note    {n}" for n in rep["notes"]]
    lines.append(f"  backup  {rep['backup']}/ — every file above is copied there first (manifest.json); undo: copy them "
                 f"back and delete {rep['harness']}")
    lines.append("next: commit the changed files, then P2.9 (init doctor → propose → answer → check → write)" if rep["done"]
                 else "nothing was changed (dry run) — `init migrate --apply` makes the migration")
    return "\n".join(lines) + "\n"


# --- CLI -------------------------------------------------------------------------------------------------------------

ACTIONS = ("roles", "migrate")


def run(action, args, environ, out, *, plugin_root, gh=None):
    """`engine.py init roles|migrate` (cli.py parses: repo, checkout, json; migrate: apply). Exit 0, 4 refused.
    `gh` = a github.Gh of the repository (labels are read once by migrate) or None."""
    if action not in ACTIONS:
        raise ValueError(f"unknown init action {action!r}")
    top = channel.top_of(os.path.realpath(args.checkout or os.getcwd()), environ)
    try:
        if top is None:
            raise Refused(f"{args.checkout or os.getcwd()} is not a git checkout")
        if action == "roles":
            rep, text = roles(top, plugin_root), format_roles
        else:
            home = pathsmod.engine_home(environ)
            rep, text = migrate(top, args.repo, plugin_root, home, environ, gh=gh, apply=args.apply), format_migrate
    except (Refused, channel.ChannelError, store.CorruptFile, store.FormatMismatch, fsafe.UnsafePath, OSError,
            ValueError) as e:
        out.write(f"refused: {e}\n")
        return EXIT_REFUSED
    out.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n" if args.json else text(rep))
    return EXIT_OK
