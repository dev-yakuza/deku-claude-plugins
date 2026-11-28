"""Readiness T2 — parity P4 / R4-13 H1: a repository the 0.98.x Guild set up moves to this channel without failing and
without anything being written over (design/guild/24-redesign/readiness/promote/t2-init.md).

The fixture is a 0.98.7 install as it lies in app_a (`config.json` in the 0.102.x form with gates, visual, engine,
local_developer and a 10-entry sprint history; knowledge, evolve ledger, memory, overlay, gate rules; 16 role files,
CLAUDE.md, standards; the 0.98.7 pre-commit shim) — placed in THIS channel's settings folder, where the stable channel
meets it at the first promotion. GitHub is the fake `gh` (labels); real git."""

import argparse
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from gxengine import channel, cli, defaults, initconfig, initharness, paths as pathsmod, sprintdag
from tests.helpers import fakes
from tests.helpers.gitrepo import GitRepo
from tests.test_initconfig import World

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.realpath(os.path.join(ENGINE, "..", "..", ".."))
REPO = "acme/app"
D = channel.CONFIG_DIR[channel.SELF]
P = defaults.LABEL_PREFIX


def history():
    """The 0.98.7 retro's capacity history (retro.md Phase 4): 10 entries, the shapes of several versions."""
    out = [{"sprint": 1581 + 30 * i, "planned": 9 + i % 4, "merged": 9 + i % 3, "carryover": i % 2, "needs_human": 0,
            "refactor": {"issue": 1500 + i, "outcome": "merged", "kind": "refactor", "paths": [f"lib/a{i}.dart"],
                         "merged_at": "2026-10-0%dT04:12:00Z" % (i % 9 + 1), "closed_at": None}} for i in range(8)]
    out.append({"sprint": 1839, "planned": 13, "merged": 12, "carryover": 1, "needs_human": 1, "capacity": 13,
                "shortfall": "none", "refactor": {"issue": 1836, "outcome": "merged", "kind": "refactor",
                                                  "paths": ["lib/controller/sync_data_controller.dart"],
                                                  "merged_at": "2026-11-07T07:31:24Z", "closed_at": None}})
    out.append({"sprint": 1889, "planned": 13, "merged": 13, "carryover": 0, "needs_human": 1, "capacity": 13,
                "shortfall": "none", "adhoc": True, "note": "an older shape — kept as it is"})
    return out


def legacy_config(gates_on=False):
    return {
        "version": "0.102.3", "language": "ko", "roles": list(initharness.ROSTER),
        "commands": {"test": ["flutter test --fail-fast --concurrency=12", "scripts/verify_test_coverage.sh"],
                     "lint": ["flutter analyze", "npx remark . --quiet --frail"], "typecheck": None,
                     "build": "flutter build apk", "e2e": "flutter test integration_test/app_test.dart", "vrt": None},
        "visual": {"baselines": ["test/**/goldens/**"], "tests": [], "matchers": [], "packages": [], "run_file": None,
                   "config_files": ["dart_test.yaml"], "runnable": True, "env": "macOS arm64", "create": None},
        "automation": {"evolve_nudge": True},
        "gates": {"enabled": gates_on},
        "sprint": {"capacity": 14, "max_stack_depth": 3, "refactor_slot": True, "history": history(),
                   "board": {"owner": "acme", "owner_type": "org", "number": 2, "column_field": "Guild board"},
                   "window": None, "stage_groups": False},
        "local_developer": {"enabled": True, "model": "qwen3.8:27b"},
        "engine": {"budget_usd_per_issue": 35.0, "effective": {"copy_ignored": ["lib/env/env.dart"]}},
    }


def role_text(role):
    return initharness.template_text(PLUGIN_ROOT, role).replace("{{", "<").replace("}}", ">")


OLD_GATE = "#!/usr/bin/env python3\n# the 0.98.7 commit gate (a copy init made long ago)\n"
OLD_SHIM = ("#!/bin/sh\n# Guild commit gate — installed by init\nGATE=\"$ROOT/" + D +
            "/gates/scripts/gate_precommit.py\"\nexec python3 \"$GATE\" --git-hook\n")


def install_0987(repo, gates_on=False, gitignore="memory/\ngates/scripts/local/__pycache__/\n"):
    """Lay a 0.98.7 install into the checkout (this channel's settings folder) and commit it."""
    w = repo.write
    w(f"{D}/config.json", json.dumps(legacy_config(gates_on), ensure_ascii=False, indent=2) + "\n")
    w(f"{D}/.gitignore", gitignore)
    w(f"{D}/evolution-log.md", "# Evolution log\n\n## evolve #12\n- applied: habit\n")
    w(f"{D}/evolution-log.archive.md", "# archive\n")
    w(f"{D}/overlay/.gitkeep", "")
    w(f"{D}/readiness-report.md", "# readiness\n")
    w(f"{D}/gates/scripts/gate_precommit.py", OLD_GATE)
    w(f"{D}/gates/rules/secrets.md", "status: confirmed\n- no keys\n")
    w(f"{D}/gates/rules/verification.md", "status: confirmed\n- no skipped tests\n")
    w(f"{D}/gates/dismissed.md", "> format: `path` — reason\n- `assets/demo.pem` — a public demo key\n")
    w(f"{D}/gates/findings.json", '{ "open": [] }\n')
    w(f"{D}/gates/scripts/local/extra.py", "def check(ctx):\n    return []\n")
    w(f"{defaults.KNOWLEDGE_DIR}/index.md", "# Knowledge Index\n- `lib/db/**` → [db.md](facts/db.md)\n")
    w(f"{defaults.KNOWLEDGE_DIR}/facts/db.md", "# Facts: db\n- **Fact**: x\n")
    w(f"{defaults.KNOWLEDGE_DIR}/facts/ui.md", "# Facts: ui\n- **Fact**: y\n")
    for r in initharness.ROSTER:
        w(f"{initharness.AGENTS_DIR}/{r}.md", role_text(r))
    w("CLAUDE.md", "# app\n\n" + defaults.MARKER_PREFIX + "start -->\nGuild block of 0.98.7\n"
      + defaults.MARKER_PREFIX + "end -->\n")
    for s in ("charter", "architecture", "conventions", "quality-bar", "verification"):
        w(f"docs/standards/{s}.md", f"---\nstatus: confirmed\n---\n# {s}\n")
    w(".claude/settings.json", '{"permissions": {"allow": ["Bash(gh:*)"]}}\n')
    repo.commit("guild 0.98.7")
    # files 0.98.7 runs leave behind (gitignored or not, never read by the engine)
    w(f"{D}/memory/2026-11-01-run.md", "episode\n")
    w(f"{D}/.sprint-logs/1923/failures.jsonl", "{}\n")


def labels_fixture(folder, names):
    path = os.path.join(folder, "gh.json")
    rules = [{"args": ["api", f"repos/{REPO}/labels?per_page=100", "--paginate"],
              "json": [{"name": n} for n in names] + [{"name": "bug"}]}]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"rules": rules}, f)
    return path


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def snapshot(top, hook):
    """{path: bytes} of every file under the checkout (no .git) plus the hook."""
    out = {}
    for dirpath, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            p = os.path.join(dirpath, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, top)] = fh.read()
    if os.path.exists(hook):
        with open(hook, "rb") as fh:
            out["<hook>"] = fh.read()
    return out


class Base(unittest.TestCase):
    gates_on = False

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = os.path.realpath(self._tmp.name)
        self.repo = GitRepo.create(self.tmp, name="app", files={"README.md": "app\n"})
        self.top = self.repo.path
        cfg = os.path.join(self.tmp, "gitconfig-hooks")           # the test config without core.hooksPath=/dev/null
        with open(os.path.join(self.tmp, "gitconfig"), encoding="utf-8") as f:
            text = f.read().replace("\thooksPath = /dev/null\n", "")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write(text)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.ghlog = os.path.join(self.tmp, "ghlog")
        self.environ = fakes.fake_env(dict(self.repo.env, HOME=self.home, GIT_CONFIG_GLOBAL=cfg,
                                           GLD_ENGINE_HOME=os.path.join(self.tmp, "gld"),
                                           GX_ENGINE_HOME=os.path.join(self.tmp, "gldx")),  # promote: other
                                      gh_fixtures=labels_fixture(self.tmp, [P + n for n in initharness.LABELS if n != "harness"]),
                                      gh_log=self.ghlog)
        self.engine_home = pathsmod.engine_home(self.environ)
        install_0987(self.repo, gates_on=self.gates_on)
        self.hook = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-path", "hooks/pre-commit"],
                                   cwd=self.top, capture_output=True, text=True, check=True, env=self.environ).stdout.strip()
        os.makedirs(os.path.dirname(self.hook), exist_ok=True)
        with open(self.hook, "w", encoding="utf-8") as f:
            f.write(OLD_SHIM)
        os.chmod(self.hook, 0o755)

    def cli(self, *argv):
        out = io.StringIO()
        rc = cli.main(list(argv), environ=self.environ, out=out)
        return rc, out.getvalue()

    def migrate(self, *extra, want=0):
        rc, text = self.cli("init", "migrate", "--repo", REPO, "--checkout", self.top, "--json", *extra)
        self.assertEqual(rc, want, text)
        return json.loads(text) if rc == 0 else text

    def read(self, rel):
        with open(os.path.join(self.top, rel), encoding="utf-8") as f:
            return f.read()

    def readj(self, rel):
        return json.loads(self.read(rel))


class DryRun(Base):
    def test_nothing_is_written_and_everything_is_named(self):
        before = snapshot(self.top, self.hook)
        rep = self.migrate()
        self.assertEqual(snapshot(self.top, self.hook), before, "a dry run writes nothing")
        self.assertFalse(os.path.exists(initharness.record_path(self.engine_home, REPO)))
        self.assertFalse(os.path.exists(rep["backup"]), "no backup folder on a dry run")
        self.assertEqual((rep["state"], rep["done"]), ("legacy", False))
        acts = {c["path"]: c["action"] for c in rep["changes"]}
        self.assertEqual(acts[defaults.HARNESS_SETTINGS], "write")
        self.assertEqual(acts[defaults.ENGINE_SETTINGS], "change")
        self.assertEqual(acts[initharness.GATE_REL], "update")
        self.assertEqual(acts[self.hook], "hook")
        self.assertEqual(acts[initharness.GITIGNORE_REL], "add")
        self.assertEqual(rep["hook"]["kind"], "guild")
        self.assertEqual({k["key"] for k in rep["not_carried"]},
                         {"visual", "engine", "local_developer", "version", "sprint.stage_groups"})
        self.assertEqual([r["key"] for r in rep["removed"]], ["gates"])
        kept = {k["path"]: k["line"] for k in rep["kept"]}
        self.assertEqual(kept[".claude/agents/"], "16 role file(s) — never written over")
        self.assertEqual(kept["CLAUDE.md"], "kept as it is (its Guild block is not replaced)")
        self.assertEqual(kept["docs/standards/"], "5 file(s)")
        self.assertEqual(kept[defaults.KNOWLEDGE_DIR + "/"], "index.md + 2 fact file(s) (shared by both channels)")
        self.assertEqual(rep["labels"]["missing"], [P + "harness"])
        self.assertEqual(len(rep["labels"]["exist"]), 10)

    def test_the_text_a_human_reads(self):
        rc, text = self.cli("init", "migrate", "--repo", REPO, "--checkout", self.top)
        self.assertEqual(rc, 0, text)
        self.assertTrue(text.startswith(f"0.98.x Guild settings found in {D}/ (config.json version 0.102.3, no "
                                        "harness.json) — the migration would:\n"), text)
        for line in (f"  write   {defaults.HARNESS_SETTINGS} — language ko, 16 role(s), commands test · lint · build · e2e, "
                     "sprint capacity 14, history 10 entries copied as they are (the newest #1889)",
                     f"  change  {defaults.ENGINE_SETTINGS} — `gates` taken out (gates.enabled was false: the commit gate "
                     "was OFF and is ON from now — it has no off-switch any more)",
                     f"  update  {initharness.GATE_REL} — this plugin's commit gate (the old copy is backed up)",
                     f"  add     {initharness.GITIGNORE_REL} — .gld-sprint-*.window, .gld-sprint-*.board",
                     f"  keep    .claude/agents/ — 16 role file(s) — never written over",
                     f"  labels  10 {P} label(s) exist — kept; init step 7 creates {P}harness and refreshes their color "
                     "and description (--force)",
                     "nothing was changed (dry run) — `init migrate --apply` makes the migration"):
            self.assertIn(line + "\n", text)
        self.assertIn("  backup  " + os.path.join(pathsmod.init_dir(self.engine_home, REPO), "migrate-"), text)
        self.assertIn(f"stays the 0.98.x file until P2.9 `init write` replaces it", text)


class GatesOn(Base):
    gates_on = True

    def test_an_on_gate_key_is_taken_out_too(self):
        rep = self.migrate()
        line = next(c["line"] for c in rep["changes"] if c["path"] == defaults.ENGINE_SETTINGS)
        self.assertIn("`gates` taken out (removed on purpose — the commit gate has no off-switch any more", line)


class Apply(Base):
    def test_the_migration(self):
        legacy = legacy_config()
        keep = {rel: data for rel, data in snapshot(self.top, self.hook).items()
                if rel.startswith((initharness.AGENTS_DIR, "docs/", defaults.KNOWLEDGE_DIR, "CLAUDE.md", ".claude/settings",
                                   f"{D}/evolution-log", f"{D}/memory", f"{D}/overlay", f"{D}/gates/rules",
                                   f"{D}/gates/dismissed", f"{D}/gates/findings", f"{D}/gates/scripts/local",
                                   f"{D}/.sprint-logs", f"{D}/readiness"))}
        rep = self.migrate("--apply")
        self.assertTrue(rep["done"])
        # harness.json: the 0.98.x settings, the history byte for byte (H1)
        h = self.readj(defaults.HARNESS_SETTINGS)
        self.assertEqual(list(h), ["version", "language", "roles", "commands", "automation", "sprint"])
        self.assertEqual(h["version"], initharness.plugin_version(PLUGIN_ROOT))
        self.assertEqual((h["language"], h["roles"], h["commands"], h["automation"]),
                         ("ko", list(initharness.ROSTER), legacy["commands"], legacy["automation"]))
        self.assertEqual(h["sprint"]["history"], legacy["sprint"]["history"])
        self.assertEqual(json.dumps(h["sprint"]["history"]), json.dumps(legacy["sprint"]["history"]), "key order kept")
        self.assertEqual({k: v for k, v in h["sprint"].items() if k != "history"},
                         {"capacity": 14, "max_stack_depth": 3, "refactor_slot": True, "board": legacy["sprint"]["board"],
                          "window": None})
        self.assertNotIn("gates", json.dumps(h))
        # the 0.98.x config.json: gates taken out, the rest stays for P2.9
        cfg = self.readj(defaults.ENGINE_SETTINGS)
        self.assertEqual(cfg, {k: v for k, v in legacy.items() if k != "gates"})
        self.assertTrue(initconfig.legacy_settings(self.read(defaults.ENGINE_SETTINGS)))
        self.assertEqual(self.read(defaults.ENGINE_SETTINGS),
                         json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", "only `gates` left the indent-2 file")
        # the commit gate and its hook
        with open(os.path.join(PLUGIN_ROOT, initharness.PLUGIN_GATE), encoding="utf-8") as f:
            self.assertEqual(self.read(initharness.GATE_REL), f.read())
        with open(self.hook, encoding="utf-8") as f:
            self.assertEqual(f.read(), channel.shim_text(PLUGIN_ROOT, channel.SELF))
        self.assertTrue(os.access(self.hook, os.X_OK))
        self.assertEqual(self.read(initharness.GITIGNORE_REL),
                         "memory/\ngates/scripts/local/__pycache__/\n.gld-sprint-*.window\n.gld-sprint-*.board\n")
        # everything else as it was
        after = snapshot(self.top, self.hook)
        for rel, data in keep.items():
            self.assertEqual(after.get(rel), data, rel)
        # the backup holds what was changed, as it was
        man = load(os.path.join(rep["backup"], "manifest.json"))
        files = {e["path"]: e for e in man["files"]}
        self.assertEqual(set(files), {defaults.ENGINE_SETTINGS, defaults.HARNESS_SETTINGS, initharness.GATE_REL,
                                      self.hook, initharness.GITIGNORE_REL})
        self.assertFalse(files[defaults.HARNESS_SETTINGS]["existed"])
        with open(os.path.join(rep["backup"], files[defaults.ENGINE_SETTINGS]["backup"]), encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read()), legacy)
        with open(os.path.join(rep["backup"], files[self.hook]["backup"]), encoding="utf-8") as f:
            self.assertEqual(f.read(), OLD_SHIM)
        rec = initharness.read_record(self.engine_home, REPO)
        self.assertEqual((rec["repo"], rec["backup"]), (REPO, rep["backup"]))

    def test_once_only(self):
        self.migrate("--apply")
        before = snapshot(self.top, self.hook)
        rep = self.migrate("--apply")
        self.assertEqual((rep["state"], rep["done"]), ("migrated", False))
        self.assertEqual(snapshot(self.top, self.hook), before)
        rc, text = self.cli("init", "migrate", "--repo", REPO, "--checkout", self.top)
        self.assertTrue(text.startswith("migrated already\n"), text)

    def test_the_backup_puts_everything_back(self):
        before = snapshot(self.top, self.hook)
        rep = self.migrate("--apply")
        man = load(os.path.join(rep["backup"], "manifest.json"))
        initharness._restore({"top": self.top, "backup": rep["backup"]}, man["files"])
        self.assertEqual(snapshot(self.top, self.hook), before)

    def test_a_failed_write_is_put_back(self):
        before = snapshot(self.top, self.hook)
        os.chmod(os.path.dirname(self.hook), 0o500)               # the hook folder cannot be written
        self.addCleanup(os.chmod, os.path.dirname(self.hook), 0o755)
        text = self.migrate("--apply", want=4)
        self.assertIn("what was written is put back from", text)
        os.chmod(os.path.dirname(self.hook), 0o755)
        self.assertEqual(snapshot(self.top, self.hook), before)
        self.assertIsNone(initharness.read_record(self.engine_home, REPO))


class Refusals(Base):
    def test_nothing_to_migrate(self):
        shutil.rmtree(os.path.join(self.top, D))
        rep = self.migrate()
        self.assertEqual((rep["state"], rep["changes"]), ("none", []))
        self.repo.write(defaults.HARNESS_SETTINGS, "{}\n")
        self.assertEqual(self.migrate()["state"], "initialized")
        rc, text = self.cli("init", "migrate", "--repo", REPO, "--checkout", self.top)
        self.assertEqual(text, f"no 0.98.x settings in {D}/ — nothing to migrate (this channel's harness is there)\n")

    def test_engine_settings_are_no_0987_install(self):
        self.repo.write(defaults.ENGINE_SETTINGS, json.dumps({"format": 1, "commands": {}}) + "\n")
        self.assertEqual(self.migrate("--apply")["state"], "initialized")
        self.assertFalse(os.path.exists(os.path.join(self.top, defaults.HARNESS_SETTINGS)))

    def test_harness_without_a_record_is_refused(self):
        self.repo.write(defaults.HARNESS_SETTINGS, "{}\n")
        before = snapshot(self.top, self.hook)
        text = self.migrate("--apply", want=4)
        self.assertIn("this machine has no record of a migration — nothing is migrated", text)
        self.assertEqual(snapshot(self.top, self.hook), before)

    def test_unreadable_settings_are_refused(self):
        self.repo.write(defaults.ENGINE_SETTINGS, "[1, 2]\n")
        self.assertIn("is not a JSON object — nothing is migrated", self.migrate("--apply", want=4))

    def test_a_broken_history_is_refused(self):
        cfg = legacy_config()
        cfg["sprint"]["history"] = {"1923": "x"}
        self.repo.write(defaults.ENGINE_SETTINGS, json.dumps(cfg) + "\n")
        before = snapshot(self.top, self.hook)
        self.assertIn("sprint.history is not a list", self.migrate("--apply", want=4))
        self.assertEqual(snapshot(self.top, self.hook), before)

    def test_refused_by_the_other_channel(self):
        self.repo.write(channel.CHANNEL_FILE, channel.OTHER + "\n")
        rc, text = self.cli("init", "migrate", "--repo", REPO, "--checkout", self.top, "--apply")
        self.assertEqual(rc, 4)
        self.assertIn("active channel is", text)
        self.assertFalse(os.path.exists(os.path.join(self.top, defaults.HARNESS_SETTINGS)))

    def test_github_silent_only_loses_the_labels_line(self):
        silent = os.path.join(self.tmp, "gh-silent.json")         # no rule: every gh call fails (fail-closed fake)
        with open(silent, "w", encoding="utf-8") as f:
            json.dump({"rules": []}, f)
        env = dict(self.environ, GLD_FAKE_GH_FIXTURES=silent)
        out = io.StringIO()
        rc = cli.main(["init", "migrate", "--repo", REPO, "--checkout", self.top], environ=env, out=out)
        self.assertEqual(rc, 0, out.getvalue())
        self.assertIn("  labels  not read (", out.getvalue())

    def test_a_lefthook_repository_keeps_its_hook(self):
        yml = f"pre-commit:\n  commands:\n    guild-gate:\n      run: python3 {channel.gate_path(channel.SELF)} --git-hook\n"
        self.repo.write("lefthook.yml", yml)
        with open(self.hook, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n# lefthook generated\nlefthook run pre-commit\n")
        rep = self.migrate("--apply")
        self.assertEqual(rep["hook"]["kind"], "lefthook")
        self.assertIn("lefthook.yml: already runs the", " ".join(rep["notes"]))
        self.assertEqual(self.read("lefthook.yml"), yml)
        with open(self.hook, encoding="utf-8") as f:
            self.assertIn("lefthook run", f.read())


class LefthookNotInstalled(Base):
    """FC M3: a clone of a lefthook repo where `lefthook install` never ran — lefthook.yml is committed (it runs
    the 0.98.x gate), .git/hooks/pre-commit does not exist. The migration registers the gate in lefthook.yml,
    writes no Guild hook, and says lefthook is not installed here."""

    def setUp(self):
        super().setUp()
        os.unlink(self.hook)
        self.repo.write("lefthook.yml", "pre-commit:\n  commands:\n    guild-gate:\n      run: python3 "
                        ".claude/guild-exp/gates/scripts/gate_precommit.py --git-hook\n")  # promote: other
        self.repo.commit("lefthook")

    def test_the_gate_goes_into_lefthook_yml_not_into_a_hook(self):
        rep = self.migrate("--apply")
        self.assertEqual(rep["hook"]["kind"], "lefthook")
        self.assertFalse(os.path.lexists(self.hook), "no Guild hook the next `lefthook install` would replace")
        self.assertIn(channel.gate_path(channel.SELF), self.read("lefthook.yml"))
        self.assertTrue(any("not installed here" in n and "lefthook install" in n for n in rep["notes"]), rep["notes"])


class NumberTexts(unittest.TestCase):
    """FC M1: taking `gates` out rewrites config.json — every number keeps its text (app_a: `0.10` became `0.1`)."""

    def test_numbers_keep_their_text(self):
        raw = ('{\n  "version": "0.102.3",\n  "dual_judge_rate": 0.10,\n  "x": [1.50, -2E3, 3, 1e-7],\n'
               '  "gates": {"enabled": true},\n  "s": "0.10"\n}\n').encode()
        out = initharness._without_keys(raw, initharness.REMOVED).decode()
        self.assertEqual(out, '{\n  "version": "0.102.3",\n  "dual_judge_rate": 0.10,\n  "x": [\n    1.50,\n    -2E3,\n'
                              '    3,\n    1e-7\n  ],\n  "s": "0.10"\n}\n')
        self.assertEqual(json.loads(out), {k: v for k, v in json.loads(raw).items() if k != "gates"})

    def test_a_nul_escape_falls_back_to_plain_numbers(self):
        raw = b'{"a": "x\\u0000y", "n": 0.10, "gates": {}}'
        self.assertEqual(json.loads(initharness._without_keys(raw, initharness.REMOVED)), {"a": "x\x00y", "n": 0.1})


class History(unittest.TestCase):
    """H1 against R4-11: a 0.98.7 tracker such as app_a #1923 (14 members, the plan hash the 0.98.7 `sprint_dag.py
    --mode hash` stored) is read by the engine's sprintdag as it is; the history the migration carries lives in
    harness.json, which the engine never reads (H13) — so the migration cannot change what `sprint run` reads."""

    MEMBERS = (1056, 1823, 1874, 1875, 1878, 1898, 1903, 1908, 1915, 1916, 1918, 1919, 999, 1912)

    def tracker(self, stored):
        from tests.test_sprintdag import body
        rows = [f"| {i + 1} | #{n} | — | — | x | goal |" for i, n in enumerate(self.MEMBERS)]
        return body(rows, meta=f"plan-hash: {stored}\n- 목표: x\n- 상한 근거: squash-sync\n")

    def test_the_tracker_reads_as_before(self):
        from tests.test_sprintdag import STABLE_DAG
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "in.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"text": self.tracker("0123456789ab")}, f, ensure_ascii=False)
            p = subprocess.run([sys.executable, "-I", STABLE_DAG, "--input", path, "--mode", "hash"],
                               capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        stored = p.stdout.split()[0]
        body = self.tracker(stored)
        self.assertEqual(sprintdag.stored_plan_hash(body), stored)
        self.assertEqual(sprintdag.plan_hash(body), stored, "the engine's hash is the 0.98.7 tool's")
        self.assertEqual([m.issue for m in sprintdag.parse_table(body)], list(self.MEMBERS))

    def test_the_engine_never_reads_the_harness(self):
        """H13: no engine module but init's own names harness.json — the carried history cannot change a sprint run."""
        pkg = os.path.join(ENGINE, "gxengine")
        for f in sorted(os.listdir(pkg)):
            if f.endswith(".py") and f not in ("initharness.py", "channel.py", "defaults.py"):
                with open(os.path.join(pkg, f), encoding="utf-8") as fh:
                    self.assertNotIn("HARNESS_SETTINGS", fh.read(), f)


class SettingsAfterMigration(World):
    """P2.9 after the migration: the 0.98.x config.json counts as no engine settings; `init write` replaces it (one more
    copy into the backup first); before the migration init refuses to take it."""

    def setUp(self):
        super().setUp()
        cfg = os.path.join(self.root, "gitconfig-hooks")
        with open(os.path.join(self.root, "gitconfig"), encoding="utf-8") as f:
            text = f.read().replace("\thooksPath = /dev/null\n", "")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write(text)
        self.env["GIT_CONFIG_GLOBAL"] = cfg
        self.repo.env["GIT_CONFIG_GLOBAL"] = cfg
        self.repo.write(f"{D}/config.json", json.dumps(legacy_config(), indent=2) + "\n")
        for r in initharness.ROSTER:
            self.repo.write(f"{initharness.AGENTS_DIR}/{r}.md", role_text(r))
        self.repo.commit("guild 0.98.7")

    def migrate(self):
        return initharness.migrate(self.repo.path, REPO, PLUGIN_ROOT, self.home, self.env, apply=True)

    def test_before_the_migration_init_refuses(self):
        d = self.init("doctor", want=4)
        row = next(c for c in d["checks"] if c["check"] == "no-settings")
        self.assertFalse(row["ok"])
        self.assertIn("holds 0.98.x Guild settings — run `init migrate` first", row["text"])
        self.assertTrue(self.init("propose", want=4, json_out=False).startswith("refused: "))

    def test_after_the_migration_p29_runs_and_write_replaces_it(self):
        rep = self.migrate()
        self.repo.commit("migrate")                               # harness.json + the changed files, committed
        d = self.init("doctor")
        self.assertEqual([c["check"] for c in d["checks"] if not c["ok"]], [])
        row = next(c for c in d["checks"] if c["check"] == "no-settings")           # FC M2: says what is there
        self.assertIn("still holds the 0.98.x settings (migrated ", row["text"])
        self.assertNotIn("does not exist yet", row["text"])
        self.settle(self.propose())
        self.assertTrue(self.init("check")["ok"])
        with open(os.path.join(self.repo.path, defaults.ENGINE_SETTINGS), encoding="utf-8") as f:
            legacy_text = f.read()
        w = self.init("write")
        self.assertIn(defaults.ENGINE_SETTINGS, w["written"])
        new = load(os.path.join(self.repo.path, defaults.ENGINE_SETTINGS))
        self.assertEqual(new["format"], 1)
        with open(os.path.join(rep["backup"], "config.json.replaced-by-init-write"), encoding="utf-8") as f:
            self.assertEqual(f.read(), legacy_text)
        self.assertTrue(os.path.isfile(os.path.join(self.repo.path, defaults.HARNESS_SETTINGS)), "harness.json stays")

    def test_engine_settings_where_the_draft_tool_looks_for_0987_ones(self):
        """The draft tool reads 0.98.x settings at one fixed path — the stable channel's settings folder. Once that
        channel has engine settings there (the promoted tree after a migration and `init write`), they are not read as
        0.98.x settings: a warning, and the draft is made from CI / lefthook / manifests (H14)."""
        other = channel.CONFIG_DIR[channel.OTHER] + "/config.json"
        if channel.OTHER != "gld":  # promote: literal
            self.skipTest("the promoted tree: the tool's fixed path is this channel's own, tested above")
        self.migrate()
        self.repo.write(other, json.dumps({"format": 1, "commands": {"test": {"cmd": "python -m pytest -q"}}}) + "\n")
        self.repo.commit("the migration; the stable channel's engine settings")
        d = self.propose()
        self.assertTrue(any(w.endswith("not 0.98.x settings — not read as such") for w in d["warnings"]), d["warnings"])
        self.assertIn("test", d["config"]["commands"])
        p = subprocess.run([sys.executable, "-I", "-B", os.path.join(ENGINE, "tools", "convert_config.py"),
                            "--repo-root", self.repo.path, "--dry-run"], capture_output=True, text=True, env=self.env)
        self.assertNotEqual(p.returncode, 0, "the stage conversion has nothing to convert")
        self.assertIn("holds engine settings (format 1), not 0.98.x settings — nothing to convert", p.stderr)

    def test_write_still_never_overwrites_the_rest(self):
        self.migrate()
        self.repo.commit("migrate")
        self.settle(self.propose())
        self.init("check")
        self.repo.write(f"{D}/roles/leader.md", "mine\n")
        self.assertIn("exists already, never overwritten", self.init("write", want=4, json_out=False))


if __name__ == "__main__":
    unittest.main()
