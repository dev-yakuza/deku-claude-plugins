"""Guard hook (plan §3.4), content gate (§3.5), measurement (§3.7)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import SCRIPTS, RepoCase, sh

from hrdlib import measure, store
from hrdlib.validate import validate


class GuardCase(RepoCase):
    def guard(self, tool, tool_input, env=None):
        e = dict(os.environ)
        e.update(env or {})
        payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": self.root})
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard.py")], input=payload,
                           capture_output=True, text=True, env=e, cwd=self.root, timeout=60)
        if not p.stdout.strip():
            return "allow"
        return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_criteria_and_persona_edits(self):
        path = os.path.join(self.root, "docs/editorial/charter.md")
        self.assertEqual(self.guard("Edit", {"file_path": path}), "ask")
        self.assertEqual(self.guard("Edit", {"file_path": path}, {"HRD_UNATTENDED": "1"}), "deny")
        self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, ".claude/agents/editor.md")}), "ask")
        self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, ".claude/agents/writer.md")}), "allow")
        self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, ".claude/herald/ledger/verified.jsonl")}), "ask")

    def test_config_protected_keys_only(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cur = json.load(open(cfgp))
        same = dict(cur, language="ko")
        self.assertEqual(self.guard("Write", {"file_path": cfgp, "content": json.dumps(same)}), "allow")
        risky = dict(cur, autonomy={"publish": "auto"})
        self.assertEqual(self.guard("Write", {"file_path": cfgp, "content": json.dumps(risky)}), "ask")

    def test_merge_rules(self):
        self.assertEqual(self.guard("Bash", {"command": "gh pr merge 3 --squash"}), "ask")
        un = {"HRD_UNATTENDED": "1"}
        self.assertEqual(self.guard("Bash", {"command": "gh pr merge 3 --squash"}, un), "deny")
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cur = json.load(open(cfgp)); cur["autonomy"]["publish"] = "auto"
        with open(cfgp, "w") as f:
            json.dump(cur, f)
        env = dict(un, HRD_AUTO_PRS="3 4")
        self.assertEqual(self.guard("Bash", {"command": "gh pr merge 3 --squash"}, env), "deny")
        self.assertEqual(self.guard("Bash", {"command": "gh pr merge 3 --squash --match-head-commit abc"}, env), "allow")
        self.assertEqual(self.guard("Bash", {"command": "gh pr merge 5 --squash --match-head-commit abc"}, env), "deny")

    def test_deploy_command_forms(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cur = json.load(open(cfgp)); cur["commands"]["deploy"] = 'npm run build && wrangler pages deploy dist --project-name="blog"'
        with open(cfgp, "w") as f:
            json.dump(cur, f)
        un = {"HRD_UNATTENDED": "1"}
        for cmd in ("wrangler pages deploy dist --project-name=blog", "wrangler pages deploy dist --project-name blog",
                    "npm run build && wrangler pages deploy dist --project-name='blog'"):
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny", cmd)
        self.assertEqual(self.guard("Bash", {"command": "npm run build"}, un), "allow")

    def test_push_parsing_bypasses(self):
        un = {"HRD_UNATTENDED": "1"}
        for cmd in ("git --exec-path=/usr/lib/git-core push origin main", "git --config-env=a=B push origin main",
                    "git push -o ci.skip origin", "git push --push-option=ci.skip origin"):
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny", cmd)

    def test_deploy_and_shell_writes(self):
        self.assertEqual(self.guard("Bash", {"command": "npm run deploy"}), "ask")
        self.assertEqual(self.guard("Bash", {"command": "npm run deploy"}, {"HRD_UNATTENDED": "1"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "echo x > docs/editorial/sources.md"}), "ask")
        self.assertEqual(self.guard("Bash", {"command": "cat docs/editorial/sources.md"}), "allow")

    def test_base_commit_jurisdiction(self):
        # unrelated human work on main is not blocked
        self.write("README.md", "hello")
        sh(self.root, "git", "add", "README.md")
        self.assertEqual(self.guard("Bash", {"command": "git commit -m readme"}), "allow")
        sh(self.root, "git", "reset", "-q")
        # a Herald article body committed straight to main is
        data = store.load_topics(self.root)
        data["topics"].append({"id": "t0001", "title": "x", "state": "published", "slug": "mine", "history": []})
        store.save_topics(self.root, data)
        self.article("mine")
        sh(self.root, "git", "add", "src/content/blog/mine.md")
        self.assertEqual(self.guard("Bash", {"command": "git commit -m sneak"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "git commit -m x"}, {"HRD_UNATTENDED": "1"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "git push origin main"}, {"HRD_UNATTENDED": "1"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "git push origin +main"}, {"HRD_UNATTENDED": "1"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "git push --all origin"}, {"HRD_UNATTENDED": "1"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "git push origin HEAD:refs/heads/main"}, {"HRD_UNATTENDED": "1"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "git -c a=b push origin main"}, {"HRD_UNATTENDED": "1"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "git push origin herald/t0001--x"}, {"HRD_UNATTENDED": "1"}), "allow")

    def test_add_and_commit_in_one_command(self):
        data = store.load_topics(self.root)
        data["topics"].append({"id": "t0001", "title": "x", "state": "published", "slug": "mine", "history": []})
        store.save_topics(self.root, data)
        self.article("mine")
        self.assertEqual(self.guard("Bash", {"command": "git add src/content/blog/mine.md && git commit -m x"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "git commit -m x src/content/blog/mine.md"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "git add -A && git commit -m x"}), "deny")
        self.write("README.md", "human")
        self.assertEqual(self.guard("Bash", {"command": "git add README.md && git commit -m readme"}), "allow")

    def test_push_value_options_and_base_rewrites(self):
        un = {"HRD_UNATTENDED": "1"}
        for cmd in ("git push --force-with-lease=main origin", "git push --recurse-submodules=check origin",
                    "git push origin @", "git merge herald/t0001--x", "git cherry-pick abc", "git reset --hard HEAD~1"):
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny", cmd)
        self.assertEqual(self.guard("Bash", {"command": "git merge herald/t0001--x"}), "ask")
        self.assertEqual(self.guard("Bash", {"command": "gh api repos/o/r/pulls/3/merge -X PUT"}, un), "deny")

    def test_deploy_with_pipe(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cur = json.load(open(cfgp)); cur["commands"]["deploy"] = "npm run deploy 2>&1 | tee deploy.log; echo done"
        with open(cfgp, "w") as f:
            json.dump(cur, f)
        un = {"HRD_UNATTENDED": "1"}
        self.assertEqual(self.guard("Bash", {"command": "npm run deploy"}, un), "deny")
        self.assertEqual(self.guard("Bash", {"command": "tee deploy.log"}, un), "allow")

    def test_round6_guard_regressions(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        un = {"HRD_UNATTENDED": "1"}
        for deploy, cmd in (("cat site.tar | ssh host deploy-site", "cat site.tar | ssh host deploy-site"),
                            ("echo y | npx vercel --prod", "echo y | npx vercel --prod")):
            cur = json.load(open(cfgp)); cur["commands"]["deploy"] = deploy
            with open(cfgp, "w") as f:
                json.dump(cur, f)
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny", cmd)
        # rm/mv of a Herald article followed by a commit on base
        data = store.load_topics(self.root)
        data["topics"].append({"id": "t0001", "title": "x", "state": "published", "slug": "old-post", "history": []})
        store.save_topics(self.root, data)
        self.assertEqual(self.guard("Bash", {"command": "git rm src/content/blog/old-post.md && git commit -m x"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "git mv src/content/blog/old-post.md src/content/blog/x.md && git commit -m x"}), "deny")
        # unstaging and other repositories are not base rewrites
        self.assertEqual(self.guard("Bash", {"command": "git reset -q -- README.md"}, un), "allow")
        other = os.path.join(self.tmp, "otherrepo")
        sh(self.tmp, "git", "init", "-q", other)
        self.assertEqual(self.guard("Bash", {"command": "git -C %s merge foo" % other}, un), "allow")
        self.assertEqual(self.guard("Bash", {"command": "git -C src merge foo"}, un), "deny")
        self.assertEqual(self.guard("Bash", {"command": 'git commit -am "src/content/blog/old-post.md"'}), "allow")

    def test_round7_effective_branch_and_write_targets(self):
        un = {"HRD_UNATTENDED": "1"}
        sh(self.root, "git", "switch", "-q", "-c", store.branch_name("t0001", "mine"))
        self.article("mine")
        for cmd in ("git switch main && git add src/content/blog/mine.md && git commit -m publish && git push",
                    "git switch main && git merge herald/t0001--mine && git push",
                    "git push"):
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny", cmd)
        ok = ("python3 .claude/herald/scripts/hrd.py stage pass --topic t0001 --stage draft 2>&1",
              "python3 .claude/herald/scripts/hrd.py hash --slug mine 2>/dev/null | tail -5",
              "git add -A -- src/content/blog/mine.md .claude/herald/work/t0001 && git commit -m draft",
              "git push -u origin herald/t0001--mine")
        self.write("notes.txt", "unrelated untracked file")
        for cmd in ok:
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "allow", cmd)

    def test_deploy_with_spaced_redirect_and_env(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cur = json.load(open(cfgp)); cur["commands"]["deploy"] = "NODE_ENV=production vercel --prod > deploy.log && curl -X POST https://hooks.example/x"
        with open(cfgp, "w") as f:
            json.dump(cur, f)
        un = {"HRD_UNATTENDED": "1"}
        for cmd in ("NODE_ENV=production vercel --prod > deploy.log", "vercel --prod"):
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny", cmd)

    def test_round8_guard(self):
        un = {"HRD_UNATTENDED": "1"}
        sh(self.root, "git", "switch", "-q", "-c", store.branch_name("t0001", "x"))
        self.assertEqual(self.guard("Bash", {"command": "git push origin herald/t0001--x 2>&1"}, un), "allow")
        self.assertEqual(self.guard("Bash", {"command": "git push -u origin herald/t0001--x 2>/dev/null"}, un), "allow")
        for cmd in ("git branch -f main HEAD", "git update-ref refs/heads/main HEAD", "git fetch origin main:main",
                    "git worktree add ../wt main", "git merge-file a b c", "git reset --hard HEAD~1"):
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny", cmd)
        for cmd in ("git reset HEAD src/x.md", "git reset -q", "git fetch origin", "git branch -D herald/t0002--y",
                    "git status --porcelain"):
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "allow", cmd)

    def test_round8_deploy_build_words(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        un = {"HRD_UNATTENDED": "1"}
        for deploy, cmd, free in (("npm run build && npx gh-pages -d build && echo done", "npx gh-pages -d build", "echo done"),
                                  ("netlify deploy --prod --dir=build && curl -X POST https://hooks.example/x",
                                   "netlify deploy --prod --dir=build", "npm run build")):
            cur = json.load(open(cfgp)); cur["commands"]["deploy"] = deploy
            with open(cfgp, "w") as f:
                json.dump(cur, f)
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny", cmd)
            self.assertEqual(self.guard("Bash", {"command": free}, un), "allow", free)

    def test_pr_branch_scope(self):
        sh(self.root, "git", "switch", "-q", "-c", store.branch_name("t0001", "mine"))
        self.article("mine")
        sh(self.root, "git", "add", "-A")
        self.assertEqual(self.guard("Bash", {"command": "git commit -m ok"}), "allow")
        self.write("src/content/blog/old-post.md", "other article")
        sh(self.root, "git", "add", "-A")
        self.assertEqual(self.guard("Bash", {"command": "git commit -m bad"}), "ask")
        self.assertEqual(self.guard("Bash", {"command": "git commit -m bad"}, {"HRD_UNATTENDED": "1"}), "deny")

    def test_trust_records_and_directory_writes(self):
        cmd = "python3 .claude/herald/scripts/hrd.py ledger record --topic t0001 --kind trust"
        self.assertEqual(self.guard("Bash", {"command": cmd}), "ask")
        self.assertEqual(self.guard("Bash", {"command": cmd}, {"HRD_UNATTENDED": "1"}), "deny")
        self.assertEqual(self.guard("Bash", {"command": "cp -r /tmp/x .claude/herald/scripts"}), "ask")

    def test_uninitialized_repo_is_ignored(self):
        os.remove(os.path.join(self.root, ".claude/herald/config.json"))
        self.assertEqual(self.guard("Bash", {"command": "gh pr merge 1"}), "allow")


class GateCase(RepoCase):
    def rules(self, obj):
        self.write("docs/editorial/gate-rules.json", json.dumps(obj))

    def test_frontmatter_length_forbidden_images(self):
        self.rules({"frontmatter": {"required": ["title", "slug", "category"]},
                    "length": {"min_chars": 5, "max_chars": 60},
                    "forbidden": [{"pattern": "Wikipedia", "status": "confirmed"},
                                  {"pattern": "Body", "status": "draft"}]})
        self.article("p1")
        rep = validate(self.root, self.cfg, "src/content/blog/p1.md")
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(len(rep["warnings"]), 1)
        self.write("src/content/blog/p1.md", open(os.path.join(self.root, "src/content/blog/p1.md")).read() + " Wikipedia")
        self.assertFalse(validate(self.root, self.cfg, "src/content/blog/p1.md")["ok"])

    def test_ignored_or_missing_image_fails(self):
        self.rules({})
        self.write("src/content/blog/p2.md", "---\ntitle: a\ndescription: d\nslug: p2\ndate: x\n---\n![a](/blog-images/p2/01.webp)\n")
        self.write("public/blog-images/p2/01.webp", b"x", binary=True)
        rep = validate(self.root, self.cfg, "src/content/blog/p2.md")
        self.assertTrue(any("gitignored" in e for e in rep["errors"]), rep)
        self.write("src/content/blog/p3.md", "---\ntitle: a\ndescription: d\nslug: p3\ndate: x\n---\n![a](/blog-images/p3/none.png)\n")
        self.assertTrue(any("does not exist" in e for e in validate(self.root, self.cfg, "src/content/blog/p3.md")["errors"]))

    def test_image_ref_variants(self):
        self.rules({})
        self.write("public/img/a.png", b"x", binary=True)
        self.write("src/content/blog/p4.md", "---\ntitle: a\ndescription: d\nslug: p4\ndate: x\n---\n"
                   "![a](//cdn.example.com/x.png) ![b](/img/a.png?v=2) ![c](/img/none.png \"title\")\n")
        errs = validate(self.root, self.cfg, "src/content/blog/p4.md")["errors"]
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("/img/none.png", errs[0])

    def test_double_hyphen_slug_rejected(self):
        self.rules({})
        self.write("src/content/blog/a--b.md", "---\ntitle: a\ndescription: d\nslug: a--b\ndate: x\n---\nbody\n")
        self.assertFalse(validate(self.root, self.cfg, "src/content/blog/a--b.md")["ok"])


class MeasureCase(unittest.TestCase):
    def test_dedupe_by_message_id_and_dollars(self):
        usage = {"input_tokens": 1000, "cache_read_input_tokens": 10000, "cache_creation_input_tokens": 2000,
                 "cache_creation": {"ephemeral_5m_input_tokens": 2000, "ephemeral_1h_input_tokens": 0},
                 "output_tokens": 500}
        ev = {"type": "assistant", "message": {"id": "m1", "model": "claude-sonnet-5-5", "usage": usage}}
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            for _ in range(3):  # streamed duplicates
                f.write(json.dumps(ev) + "\n")
            path = f.name
        s = measure.summarize_file(path, {"sonnet": 3.0})
        self.assertEqual(s["turns"], 1)
        expected = 3.0 / 1e6 * (1000 + 10000 * 0.1 + 2000 * 1.25 + 500 * 5)
        self.assertAlmostEqual(s["usd"], round(expected, 4))
        self.assertAlmostEqual(measure.stream_json_usd(path, {"sonnet": 3.0}), round(expected, 4))
        os.remove(path)


if __name__ == "__main__":
    unittest.main()
