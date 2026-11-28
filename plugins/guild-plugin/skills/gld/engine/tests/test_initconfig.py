"""VB3 init (stage-4 scope §2.9): TI5–TI11 — the real draft tool on temporary repositories, doubles for the base check
and the (paid) canaries. No LLM, no network; nothing outside the temporary folders is written.
"""

import argparse
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from gxengine import (basecheck, channel, cli, codes, defaults, initconfig as I, paths as pathsmod, procedure,
                      repoconfig, schema, store)
from tests.helpers.gitrepo import GitRepo

# the stable channel's settings folder is the one Guild 0.98.x used (R4-1 S1) — the first promotion's collision
OWN_IS_0987 = channel.CONFIG_DIR[channel.SELF] == ".claude/guild"  # promote: literal

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(ENGINE)))
REPO = "acme/app"
CI = "on: [push]\njobs:\n  t:\n    steps:\n      - run: python -m pytest -q\n      - run: ruff check .\n"
FILES = {"pyproject.toml": "[project]\nname='a'\n", "src/a.py": "x = 1\n", "src/auth/login.py": "x = 1\n",
         "tests/test_a.py": "def test_a(): pass\n", ".github/workflows/ci.yml": CI, "README.md": "x\n"}
Q = codes.InitQuestion


class Canary:
    def __init__(self, ok=True, note="", cost=0.5):
        self.ok, self.note, self.key, self.ran = ok, note, "key", {"cost_usd": cost}


class World(unittest.TestCase):
    FILES = FILES

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="gx-init-t-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.repo = GitRepo.create(self.root, files=dict(self.FILES))
        self.repo.git("remote", "set-url", "origin", "git@github.com:Acme/app.git")
        self.env = dict(self.repo.env, HOME=self.root + "/home", GLD_ENGINE_HOME=self.root + "/eng", PATH=os.environ["PATH"])
        os.makedirs(self.env["HOME"])
        self.home = pathsmod.engine_home(self.env)
        self.srt = self.root + "/srt"
        with open(self.srt, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(self.srt, 0o755)
        self.calls = []
        self.base = [basecheck.BaseCheckResult(True, record="/r")]
        self.green = lambda cfg, names: []
        self.canary = {"work": Canary(), "judge": Canary()}
        self.srt_ok = True

    def units(self):
        def base_check(request):
            self.calls.append(("base", request))
            return self.base[min(len([c for c in self.calls if c[0] == "base"]), len(self.base)) - 1]

        def measure(request, names):
            cfg = json.loads(request.config_text)
            self.calls.append(("measure", cfg.get("sandbox_exceptions")))
            return self.green(cfg, names)

        def role(cls, *a, **kw):
            self.calls.append(("role", cls, kw))
            return self.canary[cls]
        return I.Units(base_check=base_check, measure=measure, role_canary=role, cli_version=lambda *a: "2.1.323",
                       srt_canary=lambda *a, **kw: (self.srt_ok, "srt-key"))

    def init(self, action, *rest, want=0, json_out=True, units=None):
        argv = ["init", action, "--repo", REPO, "--checkout", self.repo.path, *rest] + (["--json"] if json_out else [])
        args = cli.build_parser().parse_args(argv)
        out = io.StringIO()
        rc = I.run(action, args, self.env, out, plugin_root=PLUGIN_ROOT, srt=self.srt, user_tmp="/private/var/x",
                   units=units or self.units())
        self.assertEqual(rc, want, out.getvalue())
        text = out.getvalue()
        return json.loads(text) if json_out and not text.startswith("refused") else text

    def answer(self, question, answer, item=None, note="JK, 2026-11-25", want=0):
        return self.init("answer", "--question", question, *(["--item", item] if item else []), "--answer", answer, "--note", note,
                         want=want)

    def propose(self, units=None):
        """`init propose`, then the answer a validation repository gives (A4 — opted into, never asked since Q11):
        follow-ups only recorded."""
        d = self.init("propose", units=units)
        self.answer("followups-dry-run", "dry-run")
        return d

    def settle(self, d=None):
        """Answer every open required question with its first choice."""
        d = d or self.init("propose")
        for q in d["questions"]:
            if q["required"] and not q["answered"]:
                self.answer(q["question"], list(q["choices"])[0], q["item"])
        return d

    def record(self, name):
        with open(os.path.join(pathsmod.init_dir(self.home, REPO), name), encoding="utf-8") as f:
            return json.load(f)

    def assertCheckoutUntouched(self):
        self.assertEqual(self.repo.git("status", "--porcelain", "--untracked-files=all"), "")


class Doctor(World):
    def test_ready(self):
        d = self.init("doctor")
        self.assertEqual([c["check"] for c in d["checks"] if not c["ok"]], [])
        self.assertIn("does not exist yet", next(c for c in d["checks"] if c["check"] == "no-settings")["text"])
        self.assertCheckoutUntouched()

    def test_each_failure(self):
        self.repo.git("remote", "set-url", "origin", "git@github.com:other/app.git")
        self.assertEqual([c["check"] for c in self.init("doctor", want=4)["checks"] if not c["ok"]], ["github"])
        self.repo.git("remote", "set-url", "origin", "https://github.com-work/acme/app")
        self.init("doctor")
        self.repo.git("remote", "set-url", "origin", "git@personal:Acme/app.git")       # a bare SSH host alias (VW1)
        self.init("doctor")
        for url in ("git@personal:other/app.git", "https://gitlab.com/acme/app.git", "git@gitlab.example:acme/app"):
            self.repo.git("remote", "set-url", "origin", url)
            self.assertEqual([c["check"] for c in self.init("doctor", want=4)["checks"] if not c["ok"]], ["github"], url)
        self.repo.git("remote", "set-url", "origin", "ssh://git@github.com:22/acme/app.git")
        self.init("doctor")
        self.srt = None
        self.assertEqual([c["check"] for c in self.init("doctor", want=4)["checks"] if not c["ok"]], ["srt"])

    def test_existing_settings(self):
        self.repo.write(defaults.ENGINE_SETTINGS, "{}")
        d = self.init("doctor", want=4)
        self.assertEqual([c["check"] for c in d["checks"] if not c["ok"]], ["no-settings"])


class Propose(World):
    def test_the_draft_is_kept_outside_the_checkout(self):
        d = self.init("propose")
        self.assertCheckoutUntouched()
        self.assertEqual(d["config"]["commands"]["test"]["cmd"], "python -m pytest -q")
        rec = self.record(I.DRAFT)
        self.assertEqual(rec["sha"], self.repo.head())
        repoconfig.RepoConfig.from_text(rec["config_text"])
        self.assertTrue(os.path.isfile(d["report"]))
        with open(d["report"], encoding="utf-8") as f:
            report = f.read()
        self.assertIn("`init check`", report)            # VW1: init's own steps, not the conversion's
        for stale in ("commit/.claude", "tools/base_check.py", "stage-3 merge"):
            self.assertNotIn(stale, report)

    def test_ti6_the_questions(self):
        d = self.init("propose")
        self.assertEqual([(q["question"], q["item"], q["required"]) for q in d["questions"]],
                         [("risk-rules", "risk:security:src/auth/**", False),
                          ("narrow-glob", "test-code:**/test_*.py", False), ("narrow-glob", "test-code:tests/**/*.py", False),
                          ("narrow-glob", "safety-net:**/test_safety_net_*.py", False),
                          ("risk-add", None, False), ("followups-dry-run", None, False)])
        self.assertEqual(d["open"], 0, "Q11: follow-ups are really created unless a human asks for a dry run")
        self.assertNotIn("followups_dry_run", d["config"])
        self.assertEqual(self.answer("followups-dry-run", "create")["open"], 0)

    def test_ti11_missing_roles_are_told_and_nothing_is_made(self):
        d = self.init("propose")
        self.assertIn("developer", d["roles_missing"])
        text = self.init("propose", json_out=False)
        self.assertIn("role files missing (only a channel that writes role files makes them — `init roles` says "
                      "whether this one does): ", text)                   # readiness T2: no stable command name
        self.assertFalse(os.path.exists(os.path.join(self.repo.path, ".claude")))

    def test_settings_that_exist_are_never_proposed_over(self):
        self.repo.write(defaults.ENGINE_SETTINGS, "{}")
        self.assertIn("exists", self.init("propose", want=4))
        self.repo.commit("settings")
        self.assertIn("exists", self.init("propose", want=4))

    def test_a_tool_refusal_is_a_refusal(self):
        self.repo.write(".claude/guild/config.json", "{")  # promote: literal; rename-exception: the 0.98.x settings file
        self.repo.commit("broken stable settings")
        # the stable channel keeps its settings where 0.98.x kept them (R4-1 S1): there the existing-settings refusal
        # answers first and `init migrate` is the way (T2); in the development channel the converter refuses the file
        self.assertIn("exists" if OWN_IS_0987 else "not valid JSON", self.init("propose", want=4))
        self.assertFalse(os.path.exists(pathsmod.init_dir(self.home, REPO)))

    def test_text_output_has_every_question_and_source(self):
        text = self.init("propose", json_out=False)
        for part in ("ci: .github/workflows/ci.yml:5", "[optional] risk-rules", "drop: drop the rule line", "[optional] risk-add",
                     "[optional] followups-dry-run", "open questions: 0"):
            self.assertIn(part, text)


class Answers(World):
    FILES = {"README.md": "x\n", "src/auth/login.py": "x = 1\n", "package.json": json.dumps({"scripts": {"lint": "eslint ."}}),
             "pnpm-lock.yaml": "  resolution: {tarball: https://npm.corp.example/a.tgz}\n",
             ".github/workflows/ci.yml": "on: [push]\njobs:\n  d:\n    steps:\n      - run: ./x.sh ${{ secrets.T }}\n"}

    def test_a_human_test_command(self):
        d = self.init("propose")
        self.assertEqual([(q["question"], q["item"]) for q in d["questions"] if q["required"]],
                         [("test-command", None), ("not-local", "ci/d"), ("registry-host", "npm.corp.example")])
        got = self.answer("test-command", "make unit")
        self.assertEqual(got["open"], 2)
        rec = self.record(I.DRAFT)
        self.assertEqual(rec["config"]["commands"]["test"], {"cmd": "make unit", "description": "human: JK, 2026-11-25"})
        dec = self.record(I.DECISIONS)
        schema.validate(dec, "init-decisions")
        self.assertEqual(dec["answers"][0]["answer"], "make unit")
        self.assertCheckoutUntouched()

    def test_the_same_question_again_replaces_the_answer(self):
        self.init("propose")
        self.answer("test-command", "make unit")
        self.answer("test-command", "make all", note="changed my mind")
        self.assertEqual([a["answer"] for a in self.record(I.DECISIONS)["answers"]], ["make all"])

    def test_fix_repository_never_settles(self):
        self.init("propose")
        self.assertEqual(self.answer("not-local", "fix-repository", "ci/d")["open"], 3)      # Q11: followups-dry-run not among them
        self.assertEqual(self.answer("not-local", "not-checked-locally", "ci/d")["open"], 2)

    def test_hosts(self):
        self.init("propose")
        self.answer("registry-host", "reject", "npm.corp.example")
        self.assertNotIn("npm.corp.example", self.record(I.DRAFT)["config"].get("registry_hosts", []))
        self.answer("registry-host", "approve", "npm.corp.example")
        self.assertIn("npm.corp.example", self.record(I.DRAFT)["config"]["registry_hosts"])

    def test_a_risk_line(self):
        self.init("propose")
        self.answer("risk-rules", "drop", "risk:security:src/auth/**")
        self.assertFalse([r for r in self.record(I.DRAFT)["config"].get("path_rules", []) if r["kind"] == "risk"])
        self.answer("risk-rules", "keep", "risk:security:src/auth/**")
        self.assertTrue([r for r in self.record(I.DRAFT)["config"]["path_rules"] if r["kind"] == "risk"])

    def test_ti7_refused_answers_change_nothing(self):
        self.init("propose")
        self.answer("test-command", "make unit")
        before = self.record(I.DECISIONS), self.record(I.DRAFT)
        for q, a, item in (("test-command", " ", None), ("test-command", "a\nb", None), ("registry-host", "yes", "npm.corp.example"),
                           ("registry-host", "approve", "evil.example"), ("not-local", "keep", "ci/d"), ("not-local", "fix-repository", "ci/x"),
                           ("toolchain", "none", "flutter-sdk"), ("command-conflict", "c-12345678", "test"),
                           ("sandbox-exception", "approve", "local-binding"), ("quarantine", "x tests/a.py", "test:tests/a.py"),
                           ("risk-rules", "maybe", "risk:security:src/auth/**"), ("risk-rules", "drop", "risk:security:src/**"),
                           ("test-command", "make unit", "test")):
            with self.subTest(q=q, a=a, item=item):
                self.answer(q, a, item, want=4)
        self.answer("test-command", "make x", note=" ", want=4)
        self.assertEqual((self.record(I.DECISIONS), self.record(I.DRAFT)), before)

    def test_an_answer_file(self):
        self.init("propose")
        path = os.path.join(self.root, "a.txt")
        with open(path, "w") as f:
            f.write("make 'unit tests'\n")
        self.init("answer", "--question", "test-command", "--answer-file", path, "--note", "JK")
        self.assertEqual(self.record(I.DRAFT)["config"]["commands"]["test"]["cmd"], "make 'unit tests'")
        self.init("answer", "--question", "test-command", "--answer-file", path + "x", "--note", "JK", want=4)

    def test_without_a_draft_or_with_a_moved_head(self):
        self.answer("test-command", "make unit", want=4)
        self.init("propose")
        self.repo.write("README.md", "y\n")
        self.repo.commit("moved")
        self.assertIn("HEAD moved", self.answer("test-command", "make unit", want=4))

    def test_the_settings_text_is_the_same_for_the_same_answers(self):
        self.init("propose")
        self.answer("test-command", "make unit")
        one = self.record(I.DRAFT)["config_text"]
        self.init("propose")
        self.assertEqual(self.record(I.DRAFT)["config_text"], one)


class HumanJudgment(World):
    """§2.9 the answers of A15 (2026-11-26): risk-add, narrow-glob, followups-dry-run — each taken and each refused; a
    refused answer changes nothing."""

    FILES = dict(FILES, **{"src/pay/charge.py": "x = 1\n", "bin/release.sh": "true\n", "tests/unit/test_b.py": "def test_b(): pass\n"})

    def rules(self, kind):
        return {r.get("area") or r.get("category"): r for r in self.record(I.DRAFT)["config"].get("path_rules", [])
                if r["kind"] == kind}

    def globs(self, kind, label=None):
        r = self.rules(kind).get(label)
        return sorted(r["globs"]) if r else []

    def refused(self, cases):
        before = self.record(I.DECISIONS), self.record(I.DRAFT)
        for q, a, item in cases:
            with self.subTest(q=q, a=a, item=item):
                self.answer(q, a, item, want=4)
        self.assertEqual((self.record(I.DECISIONS), self.record(I.DRAFT)), before)

    def test_a_human_adds_a_rule_line(self):
        self.propose()
        self.answer("risk-add", "add", "risk:security:src/pay/**", note="JK: card charges")
        self.assertEqual(self.globs("risk", "security"), ["src/auth/**", "src/pay/**"])
        self.answer("risk-add", "add", "risk:data-migration:src/a.py", note="JK: the schema lives here")
        self.assertEqual((self.globs("risk", "data-migration"), self.rules("risk")["data-migration"]["gate"]), (["src/a.py"], "data-review"))
        self.answer("risk-add", "add", "irreversible:human-executed:bin/release.sh", note="JK: a human runs the release")
        self.assertEqual(self.globs("irreversible", "human-executed"), ["bin/release.sh"])
        dec = I.to_decisions(self.record(I.DECISIONS)["answers"], self.record(I.DRAFT), "2026-11-26")
        self.assertIn({"kind": "risk", "area": "security", "glob": "src/pay/**", "why": "JK: card charges"},
                      dec["stage3"]["review"]["include"], "the note is the rule line's reason")
        self.answer("risk-add", "withdraw", "risk:security:src/pay/**", note="JK: not needed after all")
        self.assertEqual(self.globs("risk", "security"), ["src/auth/**"])
        self.assertEqual(self.init("propose")["open"], 0)

    def test_a_rule_line_that_is_not_one_is_refused(self):
        self.propose()
        self.refused([("risk-add", "add", "verification:test:src/a.py"), ("risk-add", "add", "risk:payment:src/a.py"),
                      ("risk-add", "add", "irreversible:deploy:bin/release.sh"), ("risk-add", "add", "risk:security:/src/a.py"),
                      ("risk-add", "add", "risk:security:src/a b.py"), ("risk-add", "add", "risk:security:src/../a.py"),
                      ("risk-add", "add", "risk:security:src/{a,b}.py"), ("risk-add", "add", "risk:security:src//a.py"),
                      ("risk-add", "add", "risk:security:src/none/**"),          # matches no tracked file (the draft tool)
                      ("risk-add", "add", "risk:security:src/auth/**"),          # a candidate already: risk-rules keep
                      ("risk-add", "yes", "risk:security:src/a.py"), ("risk-add", "add", "risk:security"),
                      ("risk-add", "add", None)])
        self.answer("risk-add", "add", "risk:security:src/a.py", note=" ", want=4)

    def test_a_human_narrows_a_test_glob(self):
        self.propose()
        self.assertEqual(self.globs("test-code"), ["**/test_*.py", "tests/**/*.py"])
        self.answer("narrow-glob", "tests/unit/**/test_*.py", "test-code:**/test_*.py", note="JK: only the unit tests")
        self.assertEqual(self.globs("test-code"), ["tests/**/*.py", "tests/unit/**/test_*.py"])
        self.answer("narrow-glob", "tests/unit/*.py tests/test_*.py", "test-code:tests/**/*.py", note="JK: two folders")
        self.assertEqual(self.globs("test-code"), ["tests/test_*.py", "tests/unit/**/test_*.py", "tests/unit/*.py"])
        self.answer("narrow-glob", "drop", "safety-net:**/test_safety_net_*.py", note="JK: no Python nets")
        self.assertEqual(self.globs("safety-net"), [])
        self.assertIn("safety-net", self.record(I.DRAFT)["unusable"], "what a dropped glob costs is shown")
        self.answer("narrow-glob", "keep", "safety-net:**/test_safety_net_*.py", note="JK: back")
        self.assertEqual(self.globs("safety-net"), ["**/test_safety_net_*.py"])

    def test_a_wider_or_unproved_glob_is_refused(self):
        self.propose()
        item = "test-code:tests/**/*.py"
        self.refused([("narrow-glob", "**/*.py", item),                     # wider
                      ("narrow-glob", "tests/**/*.py", item), ("narrow-glob", "tests/**/**/*.py", item),     # the same paths
                      ("narrow-glob", "tests/*", item),                     # cannot be proved narrower
                      ("narrow-glob", "src/**/*.py", item),                 # no narrowing of this line
                      ("narrow-glob", "tests/none/**/*.py", item),          # narrower, but matches no tracked file
                      ("narrow-glob", "tests/{a,b}.py", item), ("narrow-glob", "tests/test_a.py tests/test_a.py", item),
                      ("narrow-glob", "/tests/a.py", item),
                      ("narrow-glob", "tests/unit/*.py", "test-code:src/**"),         # not a candidate
                      ("narrow-glob", "src/auth/login.py", "risk:src/auth/**"),        # a risk glob guards by covering
                      ("narrow-glob", "tests/unit/*.py", None)])

    def test_follow_ups_are_really_created_unless_a_human_asks(self):
        """Q11 (user decision 2026-11-28): not asked — no answer = really create; `dry-run` stays a human's choice."""
        self.init("propose")
        self.assertNotIn("followups_dry_run", self.record(I.DRAFT)["config"])
        self.assertIs(repoconfig.RepoConfig.from_text(self.record(I.DRAFT)["config_text"]).followups_dry_run(), False,
                      "the engine reads the written settings as: really create")
        self.init("check")
        self.answer("followups-dry-run", "dry-run", note="JK: a validation repository (A4)")
        self.assertIs(self.record(I.DRAFT)["config"]["followups_dry_run"], True)
        self.refused([("followups-dry-run", "yes", None), ("followups-dry-run", "true", None), ("followups-dry-run", "create", "x")])
        self.answer("followups-dry-run", "create", note="JK: a real repository")
        self.assertNotIn("followups_dry_run", self.record(I.DRAFT)["config"])
        self.init("check")


class Vw1WordApp(unittest.TestCase):
    """A15's reason, kept as a fixture: VW1's init draft of app_a was looser than the committed hand settings
    (vw1/report.md §3.2: ten rule lines, the wider test-code / safety-net globs, follow-ups really created) and the
    eight questions could not put the stage-3 Q5 review back. The answers of tests/fixtures/init/app_a_vw1.json —
    the human's own words of that review — leave no difference in the stage-3 rules and follow-ups."""

    KINDS = ("test-code", "safety-net", "risk", "irreversible")

    @classmethod
    def setUpClass(cls):
        from tests.test_convert_config import cc, init_draft
        with open(os.path.join(ENGINE, "tests", "fixtures", "init", "app_a_vw1.json"), encoding="utf-8") as f:
            cls.fx = json.load(f)
        cls.files = dict({p: "" for p in cls.fx["paths"]}, **cls.fx["texts"])
        cls.cc, cls.init_draft = cc, staticmethod(init_draft)
        cls.plain = init_draft(cls.files)

    def differences(self, draft):
        """The compare rows of the stage-3 rules and follow-ups (the rest of the fixture is not the repository's)."""
        rows = I.compare(self.fx["hand"], {"path_rules": [r for r in draft["config"].get("path_rules", []) if r["kind"] in self.KINDS],
                                           "followups_dry_run": draft["config"].get("followups_dry_run")})
        return {(r["area"].split(" ", 1)[1] if r["area"].startswith("path_rules ") else r["area"], r["item"]): r["loosened"] for r in rows}

    def test_the_fixture_asks_what_vw1_was_asked(self):
        asked = {q: [x["item"] for x in self.plain["questions"] if x["question"] == q] for q in ("risk-rules", "narrow-glob")}
        self.assertEqual(sorted(asked["risk-rules"]), sorted(
            [f"risk:security:{p}" for p in ("lib/controller/iap_controller.dart", "lib/controller/store/iap_store.dart",
                                            "lib/features/kanji_detail_modal/widgets/subscription_panel.dart",
                                            "lib/helpers/google_api_helpers/google_auth_client.dart",
                                            "lib/services/sync/google_sign_in_failure.dart", "lib/services/sync/google_sign_in_timeout.dart",
                                            "lib/widgets/google_sign_in_button.dart")]
            + [f"irreversible:external-side-effect:.github/workflows/{w}.yml" for w in
               ("publish_release_notes", "release_android", "release_ios", "update_release_notes_draft")]), "vw1/runs/01-propose.txt")
        self.assertEqual(sorted(asked["narrow-glob"]), sorted(
            ["test-code:**/*_test.dart", "test-code:**/test_*.py", "test-code:**/tests/**/*.py", "test-code:integration_test/**/*.dart",
             "safety-net:**/*_safety_net_test.dart", "safety-net:**/test_safety_net_*.py"]))

    def test_without_the_new_answers_it_is_looser_as_in_vw1(self):
        got = self.differences(self.plain)
        loose = sorted(k for k, v in got.items() if v)
        self.assertEqual(loose, sorted(
            [("irreversible/external-side-effect", "android/fastlane/**"), ("irreversible/external-side-effect", "ios/fastlane/**"),
             ("irreversible/hard-to-revert", "lib/helpers/db_helper.dart"), ("irreversible/human-executed", "bin/release_app.dart"),
             ("risk/data-migration", "lib/helpers/db_helper.dart"), ("risk/security", "env/*/src/env/**"), ("risk/security", "lib/env/**"),
             ("risk/security", "lib/controller/sync_data_controller.dart"),
             ("risk/security", "lib/helpers/google_api_helpers/google_drive_helper.dart"),
             ("risk/security", "lib/services/api_service/api_service.dart"),
             ("test-code", "**/*_test.dart"), ("test-code", "**/test_*.py"),
             ("safety-net", "**/*_safety_net_test.dart"), ("safety-net", "**/test_safety_net_*.py")]), "vw1/report.md §3.2 rows 1-13")
        self.assertIn(("followups_dry_run", "followups_dry_run"), got, "row (+): follow-ups really created")

    def test_the_answers_leave_no_difference(self):
        asked = self.plain["questions"]
        for a in self.fx["answers"]:
            with self.subTest(question=a["question"], item=a["item"]):
                q = I.find_question(asked, a["question"], a["item"])
                self.assertIsNotNone(q)
                self.assertIsNone(I.answer_problem(q, a["item"], a["answer"], asked))
        answers = [dict(a, at="2026-11-26T00:00:00Z") for a in self.fx["answers"]]
        self.assertEqual([q["question"] for q in I.open_questions(asked, answers)], ["toolchain"],
                         "the fixture has no .fvmrc and the test says every SDK folder exists — VW1 had no such question")
        dec = I.to_decisions(answers, self.plain, "2026-11-26")
        self.cc.load_decisions(json.dumps(dec), init=True)
        draft = self.init_draft(self.files, dec)
        self.assertEqual(self.differences(draft), {}, "not one loosened line — and nothing stricter either")
        self.assertEqual([w for w in draft["warnings"] if "not judged by the human review" in w], [], "every candidate answered")
        self.assertIs(draft["config"]["followups_dry_run"], True)
        rows = {(r["kind"], r.get("area") or r.get("category")): r for r in draft["config"]["path_rules"]}
        self.assertEqual(rows[("risk", "data-migration")]["gate"], "data-review")
        self.assertEqual(sorted(self.fx["hand"]["path_rules"][0]["globs"]), sorted(rows[("test-code", None)]["globs"]))

    def test_one_answer_less_is_one_line_looser(self):
        answers = [dict(a, at="2026-11-26T00:00:00Z") for a in self.fx["answers"] if a["item"] != "irreversible:external-side-effect:ios/fastlane/**"]
        draft = self.init_draft(self.files, I.to_decisions(answers, self.plain, "2026-11-26"))
        self.assertEqual(self.differences(draft), {("irreversible/external-side-effect", "ios/fastlane/**"): True})


class Conflict(World):
    FILES = dict(FILES, **{"Makefile": "x:\n\ttrue\n", "lefthook.yml": "pre-push:\n  commands:\n    unit:\n      run: python -m pytest -x tests\n"})

    def test_a_choice_is_named_by_its_id(self):
        d = self.init("propose")
        q = [x for x in d["questions"] if x["question"] == "command-conflict"][0]
        self.assertEqual((q["item"], q["required"]), ("test", True))
        self.answer("command-conflict", "python -m pytest -x tests", "test", want=4)      # a text is no answer
        cid = next(i for i, t in q["choices"].items() if "-x tests" in t)
        self.assertEqual(self.answer("command-conflict", cid, "test")["open"], 0)        # Q11: followups-dry-run is not asked
        got = self.record(I.DRAFT)["config"]["commands"]["test"]
        self.assertEqual(got["cmd"], "python -m pytest -x tests")
        self.assertTrue(got["description"].startswith("lefthook: lefthook.yml:4"), got)


class Check(World):
    def test_green_base_and_canaries(self):
        self.propose()
        c = self.init("check")
        self.assertEqual((c["ok"], [x["canary"] for x in c["canaries"]]), (True, ["work", "judge", "srt"]))
        self.assertEqual([x[:2] for x in self.calls if x[0] == "role"], [("role", "work"), ("role", "judge")])
        self.assertEqual([x[2]["spent_before"] for x in self.calls if x[0] == "role"], [0.0, 0.5], "one cost cap for both")
        req = self.calls[0][1]
        self.assertEqual((req.config_text, req.sha, req.force), (self.record(I.DRAFT)["config_text"], self.repo.head(), False))
        self.assertCheckoutUntouched()

    def test_ti8_red_base_no_canary_no_write(self):
        self.base = [basecheck.BaseCheckResult(False, red=["test"], record="/r")]
        self.propose()
        c = self.init("check", want=4)
        self.assertEqual([x for x in self.calls if x[0] == "role"], [], "no paid call after a red base")
        self.assertEqual([(q["question"], q["item"]) for q in c["questions"]], [("quarantine", "test"), ("not-local", "test")])
        self.assertIn("did not pass", self.init("write", want=4))
        self.assertCheckoutUntouched()

    def test_ti8_a_failing_canary_refuses_write(self):
        for which in ("work", "judge"):
            self.canary = {"work": Canary(), "judge": Canary(), which: Canary(False, "init tools differ")}
            self.propose()
            c = self.init("check", want=4)
            self.assertEqual([x["ok"] for x in c["canaries"]][-1], False)
            self.assertIn("did not pass", self.init("write", want=4))
        self.canary, self.srt_ok = {"work": Canary(), "judge": Canary()}, False
        self.init("check", want=4)
        self.init("write", want=4)

    def test_open_questions_come_first(self):
        self.repo.write(".github/workflows/d.yml", "on: [push]\njobs:\n  d:\n    steps:\n      - run: ./x.sh ${{ secrets.T }}\n")
        self.repo.commit("ci")
        self.propose()
        self.assertIn("not-local d/d", self.init("check", want=4))
        self.assertEqual(self.calls, [])
        self.settle()
        self.init("check")

    def test_changed_answers_need_a_new_check(self):
        self.propose()
        self.init("check")
        self.answer("risk-rules", "drop", "risk:security:src/auth/**")
        self.assertIn("not checked", self.init("write", want=4))
        self.init("check")
        self.init("write")

    def test_a_problem_that_is_no_sandbox_matter_asks_nothing(self):
        self.base = [basecheck.BaseCheckResult(False, problem="worktree", record="/r")]
        self.propose()
        self.assertEqual(self.init("check", want=4)["questions"], [])
        self.assertEqual([x for x in self.calls if x[0] == "measure"], [])


class AfterRed(World):
    """§2.9 sandbox-exception: measured, then asked; TI10."""

    def setUp(self):
        super().setUp()
        self.base = [basecheck.BaseCheckResult(False, red=["test"], record="/r"), basecheck.BaseCheckResult(True, record="/r")]
        self.need = {"allow_local_binding", "allow_write"}
        self.green = lambda cfg, names: names if self.need <= set(cfg["sandbox_exceptions"]) else []

    def test_only_the_exceptions_that_matter_are_asked(self):
        self.propose()
        c = self.init("check", want=4)
        self.assertEqual([q["item"] for q in c["questions"] if q["question"] == "sandbox-exception"], ["local-binding", "user-tmp"])
        self.assertEqual(c["measured"], [{"exceptions": ["local-binding", "user-tmp"], "green": ["test"]}])
        self.assertTrue(all(m[1]["note"] == I.WHAT_IF_NOTE for m in self.calls if m[0] == "measure"))
        self.assertNotIn("sandbox_exceptions", self.record(I.DRAFT)["config"], "TI10: nothing is added by itself")

    def test_approved_ones_are_in_the_settings_with_the_humans_words(self):
        self.propose()
        self.init("check", want=4)
        self.answer("sandbox-exception", "approve", "weaker-network", want=4)      # not measured: not asked
        self.answer("sandbox-exception", "approve", "local-binding", note="JK: the test server")
        self.answer("sandbox-exception", "approve", "user-tmp", note="JK: mktemp")
        exc = self.record(I.DRAFT)["config"]["sandbox_exceptions"]
        self.assertEqual(exc, {"allow_local_binding": True, "allow_write": ["{user_tmp}"],
                               "note": "local-binding: JK: the test server; user-tmp: JK: mktemp"})
        self.init("check")
        self.assertEqual([x[2]["user_tmp"] for x in self.calls if x[0] == "role"], ["/private/var/x", None])
        self.init("write")

    def test_a_rejected_one_stays_out(self):
        self.propose()
        self.init("check", want=4)
        self.answer("sandbox-exception", "reject", "local-binding")
        self.assertNotIn("sandbox_exceptions", self.record(I.DRAFT)["config"])

    def test_nothing_measured_nothing_asked(self):
        self.green = lambda cfg, names: []
        self.propose()
        c = self.init("check", want=4)
        self.assertEqual([q["question"] for q in c["questions"]], ["quarantine", "not-local"])
        self.assertEqual(len([x for x in self.calls if x[0] == "measure"]), 1)

    def test_a_failed_prepare_is_measured_too(self):
        self.base = [basecheck.BaseCheckResult(False, problem="prepare", record="/r")]
        self.need = {"weaker_network_isolation"}
        self.propose()
        c = self.init("check", want=4)
        self.assertEqual([q["item"] for q in c["questions"]], ["weaker-network"])

    def test_quarantine_is_a_command_text_a_human_wrote(self):
        self.propose()
        self.init("check", want=4)
        self.answer("quarantine", "python -m pytest -q --deselect x", "test:tests/test_a.py", want=4)    # does not name the test
        self.answer("quarantine", "python -m pytest -q --ignore=tests/none.py", "test:tests/none.py", want=4)   # no tracked file
        self.answer("quarantine", "x tests/test_a.py", "lint:tests/test_a.py", want=4)                    # not red
        self.answer("quarantine", "x ../a", "test:../a", want=4)
        got = self.answer("quarantine", "python -m pytest -q --ignore=tests/test_a.py", "test:tests/test_a.py", note="pgrep in srt")
        self.assertEqual(got["open"], 0)
        cfg = self.record(I.DRAFT)["config"]
        self.assertEqual(cfg["commands"]["test"]["cmd"], "python -m pytest -q --ignore=tests/test_a.py")
        self.assertEqual([(q["test"], q["note"]) for q in cfg["quarantine"]], [("tests/test_a.py", "pgrep in srt")])
        self.assertTrue(cfg["commands"]["test"]["description"].startswith("human: quarantine of tests/test_a.py"))

    def test_a_red_command_that_cannot_run_here(self):
        self.base = [basecheck.BaseCheckResult(False, red=["lint"], record="/r")]
        self.green = lambda cfg, names: []
        self.propose()
        self.init("check", want=4)
        self.answer("not-local", "not-checked-locally", "lint", note="needs the CI image")
        cfg = self.record(I.DRAFT)["config"]
        self.assertNotIn("lint", cfg["commands"])
        self.assertIn("lint", [e["name"] for e in cfg["not_checked_locally"]])


class Write(World):
    def ready(self):
        self.settle()
        self.init("check")

    def test_the_settings_the_check_passed(self):
        self.ready()
        d = self.init("write")
        with open(os.path.join(self.repo.path, defaults.ENGINE_SETTINGS), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text, self.record(I.DRAFT)["config_text"])
        repoconfig.RepoConfig.from_text(text)
        self.assertEqual(sorted(d["written"]), sorted(
            [defaults.ENGINE_SETTINGS, ".claude/guild/roles/leader.md"]
            + [f".claude/guild/procedures/{n}.yaml" for n in self.record(I.DRAFT)["templates"]]))
        for n in self.record(I.DRAFT)["templates"]:
            with open(os.path.join(self.repo.path, repoconfig.TEMPLATES_DIR, n + ".yaml"), encoding="utf-8") as f:
                procedure.parse_template(f.read(), stage=3)
        self.assertEqual({p.split("/")[1] for p in d["written"]}, {channel.CONFIG_DIR[channel.SELF].split("/")[1]},
                         "TI11: .claude/agents is never written")
        self.assertFalse(os.path.exists(os.path.join(self.repo.path, defaults.HARNESS_SETTINGS)), "H13: another command's file")

    def test_ti9_existing_settings_are_never_touched(self):
        self.ready()
        for rel in (defaults.ENGINE_SETTINGS, ".claude/guild/procedures/bug.yaml", ".claude/guild/roles/leader.md"):
            with self.subTest(rel=rel):
                self.repo.write(rel, "mine\n")
                self.assertIn("xists", self.init("write", want=4))
                with open(os.path.join(self.repo.path, rel)) as f:
                    self.assertEqual(f.read(), "mine\n")
                self.assertEqual(self.repo.git("status", "--porcelain", "--untracked-files=all"), f"?? {rel}")
                shutil.rmtree(os.path.join(self.repo.path, ".claude"))

    def test_without_a_check_or_after_a_move(self):
        self.propose()
        self.assertIn("not checked", self.init("write", want=4))
        self.init("check")
        self.repo.write("README.md", "y\n")
        self.repo.commit("moved")
        self.assertIn("HEAD moved", self.init("write", want=4))

    def test_a_link_in_the_way_is_refused_and_nothing_is_left(self):
        self.ready()
        os.makedirs(self.root + "/elsewhere")
        os.symlink(self.root + "/elsewhere", os.path.join(self.repo.path, ".claude"))
        self.init("write", want=4)
        self.assertEqual(os.listdir(self.root + "/elsewhere"), [])

    def test_a_failure_half_way_leaves_nothing(self):
        self.ready()
        real, n = I.fsafe.write_text, []

        def fail(path, text, **kw):
            if path.startswith(self.repo.path):
                n.append(path)
                if len(n) == 3:
                    raise OSError("disk full")
            return real(path, text, **kw)
        with mock.patch.object(I.fsafe, "write_text", fail):
            self.assertIn("disk full", self.init("write", want=4))
        self.assertEqual(self.repo.git("status", "--porcelain", "--untracked-files=all"), "")


class Compare(World):
    def committed(self, change=None):
        d = self.init("propose")
        cfg = d["config"]
        if change:
            change(cfg)
        shutil.rmtree(pathsmod.init_dir(self.home, REPO))
        self.repo.write(defaults.ENGINE_SETTINGS, json.dumps(cfg))
        self.repo.commit("settings")
        return self.init("propose", "--compare")

    def test_ti5_nothing_is_written(self):
        d = self.committed()
        self.assertEqual((d["differences"], d["loosened"]), ([], 0))
        self.assertFalse(os.path.exists(pathsmod.init_dir(self.home, REPO)))
        self.assertCheckoutUntouched()

    def test_what_the_draft_checks_less_is_loosened(self):
        def more(cfg):
            cfg["commands"]["e2e"] = {"cmd": "make e2e"}
            cfg["commands"]["lint"]["cmd"] = "ruff check . --strict"
            cfg["path_rules"].append({"kind": "risk", "area": "payment", "gate": "security-review", "globs": ["src/pay/**"]})
            cfg["secret_paths"].append("**/*.corp")
            cfg["sandbox_exceptions"] = {"allow_local_binding": True, "note": "x"}
        d = self.committed(more)
        got = {(r["area"], r["item"]): r["loosened"] for r in d["differences"]}
        self.assertEqual(got, {("commands", "e2e"): True, ("commands", "lint"): None, ("path_rules risk/payment", "src/pay/**"): True,
                               ("secret_paths", "**/*.corp"): True, ("sandbox_exceptions", "allow_local_binding"): False})
        self.assertEqual(d["loosened"], 3)
        self.assertIn("[LOOSENED] commands e2e", self.init("propose", "--compare", json_out=False))

    def test_what_it_opens_is_loosened(self):
        a = {"commands": {"test": {"cmd": "t"}}, "registry_hosts": ["a.b"], "irreversible_levels": {"external-side-effect": "human-decision"}}
        b = {"commands": {"test": {"cmd": "t"}, "lint": {"cmd": "l"}}, "registry_hosts": ["a.b", "c.d"], "quarantine": [{"test": "x"}],
             "not_checked_locally": [{"name": "n"}], "sandbox_exceptions": {"allow_write": ["{user_tmp}"], "weaker_network_isolation": True},
             "irreversible_levels": {"external-side-effect": "notify"}, "run_timeout_min": 90}
        got = {(r["area"], r["item"]): r["loosened"] for r in I.compare(a, b)}
        self.assertEqual(got, {("commands", "lint"): False, ("registry_hosts", "c.d"): True, ("quarantine", "x"): True,
                               ("not_checked_locally", "n"): True, ("sandbox_exceptions", "allow_write"): True,
                               ("sandbox_exceptions", "weaker_network_isolation"): True,
                               ("irreversible_levels", "external-side-effect"): True, ("run_timeout_min", "run_timeout_min"): None})

    def test_a_wider_test_glob_is_loosened(self):
        """A15 (VW1 rows 11-13): for test-code / safety-net a narrower glob protects more."""
        def rule(kind, *g):
            return {"kind": kind, "globs": list(g), "note": "x"}
        a = {"path_rules": [rule("test-code", "test/**/*_test.dart", "**/tests/**/*.py"), rule("safety-net", "test/**/*_safety_net_test.dart")]}
        b = {"path_rules": [rule("test-code", "**/*_test.dart", "**/tests/**/*.py", "**/test_*.py", "**/tests/unit/*.py"),
                            rule("safety-net", "test/unit/*_safety_net_test.dart")]}
        got = {(r["area"], r["item"]): r["loosened"] for r in I.compare(a, b)}
        self.assertEqual(got, {("path_rules test-code", "**/*_test.dart"): True,           # covers what the committed rule does not
                               ("path_rules test-code", "test/**/*_test.dart"): None,      # a wider glob took its place
                               ("path_rules test-code", "**/test_*.py"): True,             # not inside the committed rule
                               ("path_rules test-code", "**/tests/unit/*.py"): False,      # inside **/tests/**/*.py
                               ("path_rules safety-net", "test/**/*_safety_net_test.dart"): False,
                               ("path_rules safety-net", "test/unit/*_safety_net_test.dart"): False})
        odd = {"path_rules": [rule("test-code", "/abs/**")]}           # outside the dialect: proves nothing, no crash
        self.assertEqual({r["item"]: r["loosened"] for r in I.compare(odd, b)}["**/tests/**/*.py"], True)

    def test_compare_wants_committed_settings(self):
        self.assertIn("not committed", self.init("propose", "--compare", want=4))


class Contract(World):
    def test_the_command_line_reaches_it(self):
        out = io.StringIO()
        rc = cli.main(["init", "propose", "--repo", REPO, "--checkout", self.repo.path, "--json"], environ=self.env, out=out, stage=4)
        self.assertEqual(rc, 0, out.getvalue())
        self.assertEqual(json.loads(out.getvalue())["sha"], self.repo.head())

    def test_exit_codes_and_actions_are_the_clis(self):
        self.assertEqual((I.EXIT_OK, I.EXIT_REFUSED), (cli.EXIT_OK, cli.EXIT_REFUSED))
        for a in I.ACTIONS:
            self.assertTrue(callable(getattr(I._Run, a)))
        with self.assertRaises(ValueError):
            I.run("delete", argparse.Namespace(), {}, None, plugin_root="/", srt=None, user_tmp=None)

    def test_corrupt_records_are_refused(self):
        self.init("propose")
        for name in (I.DRAFT, I.DECISIONS):
            path = os.path.join(pathsmod.init_dir(self.home, REPO), name)
            with open(path, "w") as f:
                f.write('{"a": 1, "a": 2}')
            self.init("check", want=4)
            os.unlink(path)
            self.init("propose")

    def test_only_the_eleven_questions_exist(self):
        self.assertEqual(len(Q.values()), 11, "§2.9: eight, and three more by A15 (2026-11-26)")
        from tests.test_convert_config import cc
        self.assertEqual(set(I.RISK_ADD_LABELS["risk"]), set(cc.RISK_AREAS), "risk-add takes the draft tool's own areas")
        self.assertEqual(set(I.NARROWABLE), {"test-code", "safety-net"}, "only where narrower protects more")
        self.assertEqual(set(I.EXCEPTIONS), {"local-binding", "weaker-network", "user-tmp"})


class EndToEnd(World):
    """The real base check under the real srt (the free canary replaced), doubles only for the paid canaries."""

    FILES = {"README.md": "x\n", "src/a.sh": "true\n", "tests/a_test.sh": "grep -q x README.md\n", "Makefile":
             "test:\n\tsh tests/a_test.sh\nlint:\n\tsh -n src/a.sh\n"}

    def test_propose_check_write(self):
        from tests.test_render import find_srt
        self.srt = find_srt()
        if self.srt is None:
            self.fail("srt not found")
        u = self.units()
        u.base_check = basecheck.check
        with mock.patch.object(basecheck, "_srt_canary"):
            self.propose(units=u)
            c = self.init("check", units=u)
        self.assertEqual(c["base"]["red"], [])
        rec = store.read_record(pathsmod.EnginePaths(self.home, REPO, 1), c["base"]["record"], "base-green")
        self.assertEqual([x["name"] for x in rec["commands"]], ["test", "lint"])
        self.init("write", units=u)
        self.assertIn(defaults.ENGINE_SETTINGS.split("/")[0], self.repo.git("status", "--porcelain"))


if __name__ == "__main__":
    unittest.main()
