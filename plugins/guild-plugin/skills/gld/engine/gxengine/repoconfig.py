"""Repository settings `.claude/guild/config.json` — load and query (design §7.10, §7.4, §7.11, §7.12 S8) — U16.

The engine reads the settings ONLY from the recorded base SHA blob (gitops.blob, §7.12
S3) and validates them against `schemas/repo-config`. It interprets nothing about the
repository: it looks commands up by name, passes cache env through, matches paths
against rule globs. No role or leader can add a command string (§7.10).

Loading is fail-closed: anything the schema or the checks below do not accept raises
`ConfigError` (→ `needs_human` at Issue start); nothing is repaired or defaulted away
except what the design names as a default (secret paths, run timeout, §7.8 allow-lists).

The conversion script that builds this file from 0.98.7 `.claude/<stable>/config.json`
(§9.2 stage 0, I11) is `engine/tools/convert_config.py` (U16).
"""

import copy
import fnmatch
import json
import os
import re

from . import codes, defaults, globs, schema

CONFIG_PATH = ".claude/guild/config.json"
TEMPLATES_DIR = ".claude/guild/procedures"

CACHE_PLACEHOLDER = "{cache}"

# §7.12 S8 — user-home toolchain / cache locations a sandbox exception may never open
# for writing (home-relative prefixes). The list is deliberately broad: a human who
# really needs one of these changes the design, not the settings.
HOME_TOOLCHAIN_PREFIXES = (
    ".cache", ".pub-cache", ".gradle", ".npm", ".nvm", ".pnpm-store", ".yarn", ".cargo",
    ".rustup", ".m2", ".dart-tool", ".dartServer", ".flutter", ".fvm", "fvm", ".pyenv",
    ".rbenv", ".bun", ".deno", ".volta", ".local", ".config", ".ssh", ".aws", ".gnupg",
    "Library", ".claude",
)

_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


class ConfigError(Exception):
    """The settings are missing or invalid (→ needs_human at Issue start)."""


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ConfigError(f"duplicate key in config.json: {key!r}")
        out[key] = value
    return out


def _bad_allow_write(path, home):
    """Why `path` may not be a sandbox write exception, or None (§7.12 S8)."""
    if not isinstance(path, str) or not path.strip():
        return "empty path"
    if path == defaults.USER_TMP_TOKEN:
        return None     # resolved by the engine (getconf DARWIN_USER_TEMP_DIR); unresolvable → refused there
    if ".." in path.replace("\\", "/").split("/"):
        return "contains .."
    if path.startswith(("~", "$")):
        return "starts with ~ or $ (home-relative or variable path)"
    norm = os.path.normpath(path)
    if norm == "/" or norm == home:
        return "the root or home folder"
    if os.path.isabs(norm):
        # P3-0: an ancestor of home would open home (and its secrets) for writing
        if home.startswith(norm.rstrip(os.sep) + os.sep):
            return "an ancestor of the home folder"
        rel = os.path.relpath(norm, home) if (norm == home or norm.startswith(home + os.sep)) else None
        if rel is not None and rel.split(os.sep)[0] in HOME_TOOLCHAIN_PREFIXES:
            return "a user home toolchain/cache location"
        # P3-0: never inside (or at) a home secret (defaults.HOME_SECRETS, case-insensitive — APFS)
        if rel is not None:
            low = rel.lower()
            for s in defaults.HOME_SECRETS:
                s = s.lower()
                if low == s or low.startswith(s + os.sep):
                    return f"inside the home secret {s!r}"
        if norm.startswith("/tmp/claude-") or norm.startswith("/private/tmp/claude-"):
            return "the Claude sandbox temp area (engine records never live there)"
    return None


HOME_TOKEN = "{home}"
TEMP_AREAS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders", "/var/tmp", "/private/var/tmp")
"""Folders any process (a run, a role's Bash) may write: never a toolchain sync source."""


def resolve_home(src, home):
    """A sync source with `{home}` filled (the user's real home)."""
    if src == HOME_TOKEN:
        return home
    if src.startswith(HOME_TOKEN + "/"):
        return home.rstrip("/") + src[len(HOME_TOKEN):]
    return src


def _bad_sync_source(path):
    """Why `path` may not be a toolchain sync source (static part), or None. The runner also
    refuses a source inside the engine home or any worktree (it knows those paths)."""
    norm = os.path.normpath(path)
    if not os.path.isabs(norm) or norm != path.rstrip("/") or norm == "/":
        return "not a canonical absolute folder"
    for t in TEMP_AREAS:
        if norm == t or norm.startswith(t + "/"):
            return "a temp area (writable by runs)"
    return None


class RepoConfig:
    """Validated repository settings. `catalog` (stage ≥ 3: {id: catalog.Entry}): also refuse a risk
    rule whose `gate` is no diff-review catalog entry (`gate_problems`, E25)."""

    def __init__(self, raw, home=None, catalog=None):
        if not isinstance(raw, dict):
            raise ConfigError("config.json must be a JSON object")
        try:
            schema.validate(raw, "repo-config")
        except schema.ValidationError as e:
            raise ConfigError(f"config.json does not match schemas/repo-config: {e}") from e
        self.raw = raw
        home = os.path.realpath(home or os.path.expanduser("~"))
        self._check_semantics(home)
        problems = [] if catalog is None else self.gate_problems(catalog)
        if problems:
            raise ConfigError("; ".join(problems))

    @classmethod
    def from_text(cls, text, home=None, catalog=None):
        try:
            raw = json.loads(text, object_pairs_hook=_no_duplicate_keys)
        except ValueError as e:
            raise ConfigError(f"config.json is not valid JSON: {e}") from e
        return cls(raw, home=home, catalog=catalog)

    # --- checks beyond the schema ------------------------------------------------------

    def _check_semantics(self, home):
        raw = self.raw
        for env_name, value in (raw.get("cache_env") or {}).items():
            stray = [p for p in _PLACEHOLDER.findall(value) if p != CACHE_PLACEHOLDER]
            if stray:
                raise ConfigError(f"cache_env.{env_name}: only {CACHE_PLACEHOLDER} may be used as a placeholder, got {stray[0]}")
        for path in (raw.get("sandbox_exceptions") or {}).get("allow_write", []):
            why = _bad_allow_write(path, home)
            if why:
                raise ConfigError(f"sandbox_exceptions.allow_write {path!r} refused: {why} (§7.12 S8)")
        for kind in ("allowed_models", "allowed_efforts"):
            if kind in raw and not raw[kind]:
                raise ConfigError(f"{kind} must not be empty when present")
        both = sorted(set(raw.get("run_env") or {}) & set(raw.get("cache_env") or {}))
        if both:
            raise ConfigError(f"run_env and cache_env both name {both[0]!r} — one variable, one slot (P3-0)")
        for env_name in raw.get("run_env") or {}:
            if any(fnmatch.fnmatchcase(env_name, p) for p in defaults.ENV_SCRUB_PATTERNS):
                raise ConfigError(f"run_env.{env_name}: the engine scrubs this name (§6.2)")
        names, dests = set(), []
        for e in raw.get("toolchain_prepare") or []:
            if e["name"] in names:
                raise ConfigError(f"toolchain_prepare: the name {e['name']!r} is used twice")
            names.add(e["name"])
            if "sync" not in e:
                continue
            for src in e["sync"]["from"]:
                why = _bad_sync_source(resolve_home(src, home))
                if why:
                    raise ConfigError(f"toolchain_prepare.{e['name']}.sync.from {src!r} refused: {why} (§7.12 S8)")
            to = e["sync"]["to"]
            for d in dests:
                if to == d or to.startswith(d + "/") or d.startswith(to + "/"):
                    raise ConfigError(f"toolchain_prepare.{e['name']}.sync.to {to!r} overlaps another sync destination")
            dests.append(to)

    # --- queries ------------------------------------------------------------------------

    def command_names(self):
        """Every named command (repo commands and plugin entries), in file order."""
        return list(self.raw["commands"])

    def command(self, name):
        """{"cmd": str | None, "plugin": str | None, "timeout_s": int}. KeyError if unknown."""
        entry = self.raw["commands"][name]
        minutes = entry.get("timeout_min") or self.raw.get("run_timeout_min") or defaults.RUN_TIMEOUT_MIN
        return {"cmd": entry.get("cmd"), "plugin": entry.get("plugin"), "timeout_s": int(minutes) * 60}

    def path_rules(self, kind):
        """The rules of one codes.PathRuleKind value."""
        kinds = {k.value for k in codes.PathRuleKind}
        value = getattr(kind, "value", kind)
        if value not in kinds:
            raise ValueError(f"unknown path rule kind {kind!r}")
        return [copy.deepcopy(r) for r in self.raw.get("path_rules", []) if r["kind"] == value]

    def matches(self, kind, path):
        """The rules of `kind` whose globs match a worktree-relative path (globs.match)."""
        return [r for r in self.path_rules(kind) if globs.match_any(r["globs"], path) is not None]

    def verification_category(self, path):
        """Stage 3 (E33): the codes.VerificationCategory value of a path, or None (no matching rule
        has one). golden / comparison-config win over the others whatever the rule order — a
        broader `test/**` rule must not hide a baseline image; else the first matching rule's."""
        C = codes.VerificationCategory
        found = [r["category"] for r in self.matches(codes.PathRuleKind.VERIFICATION.value, path) if r.get("category")]
        for value in (C.GOLDEN.value, C.COMPARISON_CONFIG.value):
            if value in found:
                return value
        return found[0] if found else None

    def irreversible_level(self, category, rule=None):
        """Stage 3 (E22, E24): (level, default level, lowered) of an irreversible category.

        level = the path rule's own `level`, else `irreversible_levels`, else the plugin default;
        a role code has no rule. lowered = weaker than the plugin default (shown in every PR)."""
        value = getattr(category, "value", category)
        if value not in defaults.IRREVERSIBLE_DEFAULT_LEVEL:
            raise ValueError(f"unknown irreversible category {category!r}")
        if rule is not None and (rule.get("kind") != codes.PathRuleKind.IRREVERSIBLE.value or rule.get("category") != value):
            raise ValueError(f"not an irreversible path rule of category {value!r}: {rule!r}")
        default = defaults.IRREVERSIBLE_DEFAULT_LEVEL[value]
        level = (rule or {}).get("level") or (self.raw.get("irreversible_levels") or {}).get(value) or default
        order = defaults.IRREVERSIBLE_LEVEL_ORDER
        return level, default, order.index(level) < order.index(default)

    def followups_dry_run(self):
        """Stage 3 (A4): True = create-followups only records what it would write."""
        return self.raw.get("followups_dry_run", defaults.FOLLOWUPS_DRY_RUN_DEFAULT)

    def gate_problems(self, catalog):
        """Stage 3 (E25): why a risk rule's `gate` is no gate — it must be a `diff-review` entry of
        the step catalog ({id: entry with .cls}). [] = fine. Whether the role can run is not
        asked here (rules.evaluate → rule-unfillable)."""
        out = []
        for rule in self.path_rules(codes.PathRuleKind.RISK.value):
            entry = catalog.get(rule["gate"])
            if entry is None or entry.cls != codes.CatalogClass.DIFF_REVIEW.value:
                out.append(f"path_rules: the risk area {rule['area']!r} names gate {rule['gate']!r}, which is not a "
                           f"{codes.CatalogClass.DIFF_REVIEW.value} step of the plugin catalog")
        return out

    def path_globs(self, kind):
        """Stage 3 (E4): the globs of every rule of `kind`, file order, no repeats ([] = no rule) —
        what `{path:<kind>}` of a template becomes (procedure.expand_paths)."""
        out = []
        for rule in self.path_rules(kind):
            out += [g for g in rule["globs"] if g not in out]
        return out

    def cache_env(self, cache_dir):
        """cache_env with {cache} filled."""
        return {k: v.replace(CACHE_PLACEHOLDER, cache_dir) for k, v in (self.raw.get("cache_env") or {}).items()}

    def run_env(self):
        """run_env (literal, non-path values for runs and toolchain prepare, P3-0)."""
        return dict(self.raw.get("run_env") or {})

    def secret_paths(self):
        """Repo secret globs (defaults.REPO_SECRET_DEFAULTS when absent or empty — fail-closed)."""
        listed = self.raw.get("secret_paths")
        return list(listed) if listed else list(defaults.REPO_SECRET_DEFAULTS)

    def registry_hosts(self):
        return list(self.raw.get("registry_hosts", []))

    def toolchain_prepare(self):
        """[{"name", "cmd", "sync", "timeout_s"}] in file order (§7.12 S8, P3-Z decision 4).

        `sync` = {"from": [...], "to": ...} (a file copy outside the sandbox, `cmd` None) or
        None (`cmd` runs INSIDE srt with the run boundary)."""
        default = self.raw.get("run_timeout_min") or defaults.RUN_TIMEOUT_MIN
        out = []
        for e in self.raw.get("toolchain_prepare", []):
            sync = e.get("sync")
            out.append({"name": e["name"], "cmd": e.get("cmd"),
                        "sync": {"from": list(sync["from"]), "to": sync["to"]} if sync else None,
                        "timeout_s": int(e.get("timeout_min") or default) * 60})
        return out

    def worktree_prepare(self):
        """[{"copy": glob, "note": str | None}] — files copied main checkout → Issue worktree."""
        return [{"copy": e["copy"], "note": e.get("note")} for e in self.raw.get("worktree_prepare", [])]

    def sandbox_exceptions(self):
        """The approved exceptions ({} when none): allow_write, allow_hosts, allow_local_binding, weaker_network_isolation."""
        return copy.deepcopy(self.raw.get("sandbox_exceptions") or {})

    def not_checked_locally(self):
        """[{"name", "note"}] — CI checks that cannot run locally (PR body, §7.2-2)."""
        return [dict(e) for e in self.raw.get("not_checked_locally", [])]

    def quarantine(self):
        return [dict(e) for e in self.raw.get("quarantine", [])]

    def allowed_models(self):
        return list(self.raw.get("allowed_models") or defaults.ALLOWED_MODELS)

    def allowed_efforts(self):
        return list(self.raw.get("allowed_efforts") or defaults.ALLOWED_EFFORTS)
