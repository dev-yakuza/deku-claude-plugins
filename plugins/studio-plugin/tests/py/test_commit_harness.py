"""M0f §2, §5: the harness commit kind — allow-list, the summary line, H2–H14 on the index, the husky block,
the runner's closed side and `hooks.py status` warnings. Real git in temporary repositories only."""

import json
import os
import subprocess

from harness_base import SID, HarnessCase
from stdo.commit import okfile, summary
from stdo.hooks import templates as T


class Stage(HarnessCase):
    def test_guide_change_end_to_end_outside_a_session(self):
        self.write(".claude/studio/guides/script.md", "# Script guide\n\n- Keep it short.\n")
        out = self.stage()
        self.assertEqual(out.returncode, 0, out.stderr + out.stdout)
        ok, _ = okfile.read(self.repo)
        self.assertEqual(ok["kind"], "harness")
        self.assertEqual(ok["paths"], [".claude/studio/guides/script.md"])
        self.assertEqual(ok["summary"], "커밋 %s | 변경 1 | 삭제 0 | 보호 키: 없음" % ok["tree"][:12])
        self.assertIn(ok["summary"], out.stdout)
        self.assertEqual(ok["protected_changes"], [])
        # a person outside any session: no guard record needed
        self.assertEqual(self.commit().returncode, 0)

    def test_claude_session_needs_the_guards_record_with_the_summary(self):
        self.guard_ran()
        self.write(".claude/studio/charter.md", self.read(".claude/studio/charter.md") + "\n추가.\n")
        self.assertEqual(self.stage(env=self.claude_env()).returncode, 0)
        out = self.commit(env=self.claude_env())
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("did not see this commit", out.stderr)
        self.approve_as_guard()
        ok, _ = okfile.read(self.repo)
        ap = dict(ok["approval"])
        ap["summary"] = ok["summary"].replace("변경 1", "변경 2")
        okfile.set_approval(self.repo, ap)
        out = self.commit(env=self.claude_env())
        self.assertIn("summary line", out.stderr)
        self.approve_as_guard()
        self.assertEqual(self.commit(env=self.claude_env()).returncode, 0, self.commit(env=self.claude_env()).stderr)

    def test_protected_keys_in_summary_and_proxy(self):
        self.guard_ran()
        self.config(public_domains=["example.com"], language="en")
        self.assertEqual(self.stage(env=self.claude_env()).returncode, 0)
        ok, _ = okfile.read(self.repo)
        self.assertEqual([c["key"] for c in ok["protected_changes"]], ["public_domains"])
        self.assertIn("보호 키: public_domains", ok["summary"])
        self.approve_as_guard(mode="proxy")
        out = self.commit(env=self.claude_env())
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("protected settings", out.stderr)
        self.approve_as_guard()
        self.assertEqual(self.commit(env=self.claude_env()).returncode, 0)

    def test_proxy_harness_commit_without_protected_keys(self):
        self.guard_ran()
        self.write(".claude/studio/guides/script.md", "# g\n")
        self.assertEqual(self.stage(env=self.claude_env()).returncode, 0)
        self.approve_as_guard(mode="proxy")
        self.assertEqual(self.commit(env=self.claude_env()).returncode, 0)

    def test_deleted_agent_in_summary(self):
        self.git("rm", "-q", "--cached", ".claude/agents/std-distributor.md")
        os.remove(os.path.join(self.repo, ".claude", "agents", "std-distributor.md"))
        out = self.stage()
        self.assertEqual(out.returncode, 0, out.stderr)
        ok, _ = okfile.read(self.repo)
        self.assertTrue(ok["summary"].endswith("| 삭제 1 | 보호 키: 없음 | 삭제된 에이전트: std-distributor"),
                        ok["summary"])

    def test_outside_the_allow_list_and_other_staging(self):
        self.write("src/a.ts", "a\n")
        self.git("add", "src/a.ts")
        out = self.stage()
        self.assertEqual(out.returncode, 1)
        self.assertIn("other changes are already staged", out.stderr)
        self.git("reset", "-q")
        self.write("studio/videos/v1/script.ko.md", "# s\n")
        self.write(".claude/studio/guides/script.md", "# g2\n")
        out = self.stage()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("studio/videos/v1/script.ko.md", okfile.read(self.repo)[0]["paths"])


class Checks(HarnessCase):
    def assertStage(self, code, *words):
        out = self.stage()
        self.assertEqual(out.returncode, code, out.stderr + out.stdout)
        for w in words:
            self.assertIn(w, out.stderr)
        if code:
            self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")
        return out

    def test_h2_home_paths(self):
        for text in ("cd /" + "Users/alice/work\n", "path: /" + "home/bob/x\n", "see ~/notes\n"):
            self.write(".claude/studio/guides/script.md", text)
            self.assertStage(1, "home-folder path")
        self.write(".claude/studio/guides/script.md", "an example: /" + "home/user/repo\n")
        self.assertStage(0)
        # every text file of the allow-list, not only content files (review MINOR-1)
        self.git("reset", "-q")
        self.write(".claude/agents/std-writer.md", self.read(".claude/agents/std-writer.md") + "\nsee /" + "Users/alice\n")
        self.assertStage(1, "home-folder path")

    def test_h2_skips_the_scripts_copy(self):
        # the copy's docstrings mention ~/.claude; an unchanged copy passes H2 and a harness commit goes through
        self.write(".claude/studio/guides/script.md", "# g\n")
        self.assertStage(0)

    def test_h3_terms(self):
        make = __import__("make_harness")
        make.write_overlay(self.repo, {"internal": {"terms": ["Project Kestrel", "abc"], "videos": ["onboard-x"]}},
                           self.env)
        self.write(".claude/studio/guides/script.md", "talk about project kestrel\n")
        self.assertStage(1, "internal term")
        self.write(".claude/studio/guides/script.md", "abc is short\n")
        self.assertStage(0)
        # overlay missing: content files -> 4, wiring only -> passes
        os.remove(os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json"))
        self.git("reset", "-q", "--soft", "HEAD")
        self.git("reset", "-q")
        self.write(".claude/studio/guides/script.md", "anything\n")
        self.assertStage(4, "internal overlay")

    def test_h4_internal_guide_items(self):
        self.write(".claude/studio/guides/script.md", "- item\n  scope: internal\n")
        self.assertStage(1, "scope: internal")
        self.write(".claude/studio/guides/script.md", "<!-- scope: internal -->\n")
        self.assertStage(1, "scope: internal")

    def test_h6_studio_root_change(self):
        self.config(studio_root="media")
        out = self.stage()
        self.assertNotEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")

    def test_h10_scripts_copy(self):
        p = os.path.join(self.repo, ".claude", "studio", "scripts", "stdo", "paths.py")
        with open(p, "a") as f:
            f.write("# edited\n")
        self.assertStage(1, "differ from their manifest")
        with open(p) as f:
            text = f.read()
        with open(p, "w") as f:
            f.write(text.replace("# edited\n", ""))
        self.write(".claude/studio/scripts/stdo/extra.py", "x = 1\n")
        self.assertStage(1, "does not list")
        os.remove(os.path.join(self.repo, ".claude", "studio", "scripts", "stdo", "extra.py"))
        self.assertStage(1, "nothing to stage")  # back to HEAD

    def test_h14_deletions(self):
        for rel in (".claude/studio/scripts/lock.py", ".claude/studio/config.json",
                    ".claude/studio/scripts/MANIFEST.sha256", ".claude/agents/std-fact-checker.md",
                    ".claude/studio/charter.md"):
            self.git("rm", "-q", rel)
            self.git("reset", "-q")
            out = self.stage()
            self.assertNotEqual(out.returncode, 0, rel)
            if rel != ".claude/studio/config.json":  # without config.json --stage says there is no harness
                self.assertIn("removal procedure", out.stderr, rel)
            self.git("checkout", "-q", "--", rel)
        # the hook: a commit removing config.json from a harness HEAD
        self.git("rm", "-q", ".claude/studio/config.json")
        out = self.commit()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("removal procedure", out.stderr)
        self.git("reset", "-q")
        self.git("checkout", "-q", "--", ".claude/studio/config.json")
        # another std-* agent may go (a role turned off)
        self.git("rm", "-q", ".claude/agents/std-distributor.md")
        self.git("reset", "-q")
        self.assertEqual(self.stage().returncode, 0)

    def test_h11_links(self):
        os.symlink("/etc/hosts", os.path.join(self.repo, ".claude", "studio", "guides", "link.md"))
        self.assertStage(1, "symbolic link")

    def test_h13_gitignore_block(self):
        text = self.read(".gitignore")
        self.write(".gitignore", text.replace("# <<< studio <<<", "!/studio/local/keep\n# <<< studio <<<"))
        self.assertStage(1, "re-includes")
        self.write(".gitignore", text.replace("/.claude/studio/local/\n", ""))
        out = self.stage()
        self.assertNotEqual(out.returncode, 0)
        self.write(".gitignore", text.replace("# <<< studio <<<", "/studio/tmp/\n# <<< studio <<<"))
        self.assertStage(0)  # adding a line to the block is fine


class Husky(HarnessCase):
    husky = True

    def test_block_only_and_template(self):
        text = self.read(".husky/pre-commit")
        self.assertIn(T.husky_block(), text)
        # changing the block to something else is not a harness commit
        self.write(".husky/pre-commit", text.replace("|| exit $?", "|| true"))
        out = self.stage()
        self.assertEqual(out.returncode, 1, out.stderr + out.stdout)
        self.assertIn("not this version", out.stderr)
        # changes outside the block are the team's, not Studio's
        self.write(".husky/pre-commit", "npm run lint\n" + text)
        out = self.stage()
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("nothing to stage", out.stderr)
        self.write(".husky/pre-commit", "npm run lint\n" + text.replace("|| exit $?", "|| true"))
        out = self.stage()
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("outside Studio's block", out.stderr)

    def test_exit_before_the_block(self):
        """M0f review MINOR-2: a standalone exit before the block makes the file broken; the guard denies the edit."""
        text = self.read(".husky/pre-commit")
        new = "exit 0\n" + text
        self.write(".husky/pre-commit", new)
        out = self.stage()
        self.assertEqual(out.returncode, 1, out.stderr + out.stdout)
        self.assertIn(".husky/pre-commit", out.stderr)
        self.write(".husky/pre-commit", text)
        from stdo.guard import judge
        hook = {"tool_name": "Edit", "cwd": self.repo, "session_id": SID, "tool_use_id": "t",
                "tool_input": {"file_path": os.path.join(self.repo, ".husky", "pre-commit"),
                               "old_string": "npm test\n", "new_string": "npm test\nexit 0\n"}}
        deny, _ = judge.decide(hook, self.env, snapshot_loader=lambda e: (None, ["snapshot-none"]))
        self.assertIsNotNone(deny)
        self.assertEqual(deny.rule, "G-PROT")

    def test_indented_exit_inside_if_is_fine(self):
        """M0f review 2 MINOR-3: only column-0 exit/exec/return lines stop the hook before the block."""
        text = self.read(".husky/pre-commit")
        self.git("rm", "-q", "--cached", ".husky/pre-commit")
        self.write(".husky/pre-commit", text.replace(T.husky_block(), ""))
        self.git("add", ".husky/pre-commit")
        self.git("commit", "-q", "--no-verify", "-m", "husky without the block")
        self.write(".husky/pre-commit", 'if [ -n "$CI" ]; then\n  exit 0\nfi\n' + text.replace(T.husky_block(), "") +
                   T.husky_block())
        self.git("add", ".husky/pre-commit")
        self.git("commit", "-q", "--no-verify", "-m", "team: skip on CI")
        self.write(".husky/pre-commit", self.read(".husky/pre-commit").replace(T.husky_block(), ""))
        self.git("add", ".husky/pre-commit")
        self.git("commit", "-q", "--no-verify", "-m", "a person removed the block")
        self.write(".husky/pre-commit", self.read(".husky/pre-commit") + T.husky_block())
        out = self.stage()
        self.assertEqual(out.returncode, 0, out.stderr + out.stdout)
        self.assertEqual(T.stops_before_block("exit 0\n" + T.husky_block()), 1)
        self.assertEqual(T.stops_before_block("if x; then\n  exit 0\nfi\n" + T.husky_block()), 0)

    def test_block_restored_is_a_harness_commit(self):
        text = self.read(".husky/pre-commit")
        without = text.replace(T.husky_block(), "")
        self.write(".husky/pre-commit", without)
        self.git("add", ".husky/pre-commit")
        self.git("commit", "-q", "--no-verify", "-m", "a person removed the block")
        self.write(".husky/pre-commit", text)
        out = self.stage()
        self.assertEqual(out.returncode, 0, out.stderr + out.stdout)
        self.assertIn(".husky/pre-commit", okfile.read(self.repo)[0]["paths"])


class Runner(HarnessCase):
    def test_closed_when_head_has_the_check_script(self):
        self.git("rm", "-q", "-r", ".claude/studio/scripts")
        out = self.commit()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("is in HEAD but not in the work tree", out.stderr)
        self.git("config", "core.sparseCheckout", "true")
        out = self.commit()
        self.assertIn("sparse-checkout", out.stderr)

    def test_open_on_a_branch_without_the_harness(self):
        self.git("checkout", "-q", "--orphan", "plain")
        self.git("rm", "-q", "-r", "--cached", ".")
        for n in os.listdir(self.repo):
            if n not in (".git",):
                p = os.path.join(self.repo, n)
                if os.path.isdir(p):
                    import shutil
                    shutil.rmtree(p)
                else:
                    os.remove(p)
        self.write(".claude/studio/notes.md", "x\n")  # a Studio path, no harness ever on this branch
        self.git("add", ".claude/studio/notes.md")
        self.assertEqual(self.commit().returncode, 0)

    def test_old_runner_is_invalid_after_the_upgrade(self):
        """E22 (m0f-plan v4 NIT-3): a runner written by 0.0.8 (v1) is reported invalid by status."""
        common = self.git("rev-parse", "--git-common-dir").stdout.strip()
        rp = os.path.join(self.repo, common, T.RUNNER_REL) if not os.path.isabs(common) else os.path.join(common, T.RUNNER_REL)
        with open(rp) as f:
            cur = f.read()
        self.assertIn("v%d" % T.RUNNER_VERSION, cur.splitlines()[1])
        with open(rp, "w") as f:
            f.write(cur.replace("v%d —" % T.RUNNER_VERSION, "v1 —").replace(
                "  git cat-file -e \"HEAD:$cc\" 2>/dev/null || exit 0\n", ""))
        out = self.script("hooks.py", "status")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("runner differs", out.stdout)

    def test_status_warns_on_reincluded_local(self):
        self.write(".gitignore", self.read(".gitignore") + "!/studio/local/videos/\n")
        out = self.script("hooks.py", "status")
        self.assertIn("warning: .gitignore re-includes", out.stdout)


class SummaryUnit(HarnessCase):
    def test_norm_and_shown(self):
        line = "커밋 3f2a9c0d1e4b | 변경 3 | 삭제 1 | 보호 키: s2v, visibility"
        self.assertTrue(summary.shown_in(line, "커밋할까요?\n" + line.replace(" | ", "  |   ") + "\n목록"))
        self.assertFalse(summary.shown_in(line, line.replace("변경 3", "변경 30")))
        self.assertFalse(summary.shown_in(line, line.replace("s2v, ", "")))
        import unicodedata
        self.assertTrue(summary.shown_in(line, unicodedata.normalize("NFD", line)))

    def test_protected_changes(self):
        ch = summary.protected_changes({"s2v": {"path": "a"}, "language": "ko"},
                                       {"s2v": {"path": "b"}, "language": "en", "protected_keys": ["brand"],
                                        "brand": 1})
        self.assertEqual([c["key"] for c in ch], ["brand", "protected_keys", "s2v"])


class AllowList(HarnessCase):
    def test_allowed_paths(self):
        from stdo.commit import checks, kinds
        from stdo.commit.gitx import Git
        ctx = checks.Ctx(Git(self.repo, self.env), self.env, kinds.registry({}))
        k = kinds.registry({})["harness"]
        for p in (".claude/studio/charter.md", ".claude/studio/scripts/state.py", ".claude/agents/std-writer.md",
                  ".gitignore", ".husky/pre-commit"):
            self.assertTrue(k.allowed(ctx, p), p)
        for p in (".claude/studio/local/config.internal.json", ".claude/agents/other.md", ".claude/agents/std-x.txt",
                  "studio/videos/v1/script.ko.md", "studio/voices/a.yaml", "src/a.ts", ".husky/pre-push"):
            self.assertFalse(k.allowed(ctx, p), p)
