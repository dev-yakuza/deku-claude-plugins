"""Guard hook (plan §3.4), content gate (§3.5), measurement (§3.7)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import SCRIPTS, RepoCase, sh

from hrdlib import hashing, measure, store
from hrdlib.prose import prose_report
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

    def test_round9_env_wrappers_and_paths(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cur = json.load(open(cfgp)); cur["autonomy"]["publish"] = "auto"
        with open(cfgp, "w") as f:
            json.dump(cur, f)
        un = {"HRD_UNATTENDED": "1"}
        for cmd in ("HUSKY=0 git push origin main", "GH_PROMPT_DISABLED=1 gh pr merge 5 --squash",
                    "GH_REPO=o/r gh pr merge 5 --admin", "GIT_EDITOR=true git rebase main", "/usr/bin/git push origin main",
                    "HUSKY=0 git commit -m x", "env -i A=1 git push origin main", "timeout 60 git push origin main",
                    "git status & git push origin main", "git checkout -B main origin/main", "git clean -fdX",
                    "git clean -fd -- .claude/herald/ledger", "git reset HEAD~0 --"):
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny", cmd)
        for cmd in ("git remote -v", "git ls-remote origin", "git stash list", "git config --get user.name",
                    "git worktree list", "grep -rn hugo docs/"):
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "allow", cmd)

    def test_round10_runner_forms_wrappers_config(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        un = {"HRD_UNATTENDED": "1"}
        for deploy, cmds in (("vercel --prod", ("npx vercel --prod", "bunx vercel --prod", "pnpm dlx vercel --prod")),
                             ("npx wrangler pages deploy dist", ("wrangler pages deploy dist",)),
                             ("npm run deploy", ("npm run-script deploy", "pnpm run deploy", "yarn deploy",
                                                 "npm --silent run deploy"))):
            cur = json.load(open(cfgp)); cur["commands"]["deploy"] = deploy
            with open(cfgp, "w") as f:
                json.dump(cur, f)
            for cmd in cmds:
                self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny", cmd)
        self.assertEqual(self.guard("Bash", {"command": "npm install"}, un), "allow")
        for cmd in ("timeout -s KILL 60 git push origin main", "sudo -u me git push origin main",
                    "env -u X git push origin main", "git config --unset core.hooksPath",
                    "git config --remove-section remote.origin", "git symbolic-ref HEAD refs/heads/main",
                    "nohup cp x .claude/settings.json"):
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny", cmd)
        self.assertEqual(self.guard("Bash", {"command": "git reset HEAD"}, un), "allow")

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


class ProseCase(RepoCase):
    def test_hints_never_fail_the_gate_and_carry_file_lines(self):
        self.write("docs/editorial/gate-rules.json", json.dumps({}))
        long_ = "This sentence " + "keeps going and going " * 12 + "until it ends."
        self.write("src/content/blog/p5.md", "---\ntitle: a\ndescription: d\nslug: p5\ndate: x\n---\n"
                   "Intro line.\n\n" + long_ + "\n\nIn conclusion, delve in.\n")
        rep = validate(self.root, self.cfg, "src/content/blog/p5.md")
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["warnings"], [])
        hints = " | ".join(rep["prose"]["warnings"])
        self.assertIn("over 35 words", hints)
        self.assertIn("line 9 ", hints)
        self.assertIn("'in conclusion'", hints)
        self.assertIn("'delve'", hints)
        self.write("docs/editorial/gate-rules.json", json.dumps({"prose": {"check": False}}))
        self.assertEqual(validate(self.root, self.cfg, "src/content/blog/p5.md")["prose"]["warnings"], [])

    def test_custom_validator_still_gets_hints(self):
        self.write("docs/editorial/gate-rules.json", json.dumps({}))
        self.write("src/content/blog/p6.md", "---\ntitle: a\nslug: p6\n---\nIn conclusion, it ends.\n")
        self.cfg.data["commands"]["validate"] = "true"
        rep = store.run_gate(self.root, self.cfg, "p6")
        self.assertTrue(rep["ok"])
        self.assertTrue(any("in conclusion" in w for w in rep["prose"]["warnings"]), rep)

    def test_korean_labels_numbers_and_asides(self):
        body = ("공부 시간은 하루 1.5시간입니다(가정). 주말에는 3시간입니다(가정).\n\n"
                "8주 합계는 105시간입니다(가정).\n\n"
                "| 표 | 1 | 2 | 3 | 4 | 5 |\n|---|---|---|---|---|---|\n\n"
                "```\n(가정) (가정) 1 2 3 4 5 6\n```\n\n"
                "기준점(N3는 19점, 약 32%)과 합격점(N3는 95점, 약 53%)을 1, 2주에 확인합니다.\n\n"
                "空港(くうこう)과 搭乗券(탑승권), 「はい」(네)는 설명입니다.\n")
        rep = prose_report(body, "ko")
        hints = " | ".join(rep["warnings"])
        self.assertIn("(가정) appears 3 times", hints)
        self.assertIn("1 sentence(s) with 2+ parenthetical asides", hints)
        self.assertIn("1 sentence(s) with 5+ numbers", hints)
        self.assertEqual(rep["stats"]["sentences"], 5)
        tuned = prose_report(body, "ko", {"repeat_label": 4, "max_numbers": 9, "stock_phrases": ["설명입니다"]})
        hints = " | ".join(tuned["warnings"])
        self.assertNotIn("appears", hints)
        self.assertNotIn("numbers", hints)
        self.assertIn("'설명입니다' ×1", hints)
        self.assertEqual(prose_report("짧은 문장입니다. " * 3 + "가" * 91 + "다.", "ko")["stats"]["long"], 1)


class ProseEdgeCase(RepoCase):
    def test_bad_rule_values_fall_back_and_never_crash(self):
        body = "One sentence here. In conclusion, two."
        for rules in (None, [], "x", {"max_asides": None, "repeat_label": "3", "max_numbers": 0,
                                       "stock_phrases": [{"phrase": "x"}, "", 3]},
                      {"stock_phrases": "abc"}, {"max_sentence": True}):
            rep = prose_report(body, "en", rules)
            self.assertEqual(rep["stats"]["sentences"], 2, rules)
            self.assertFalse(any("numbers" in w for w in rep["warnings"]), rules)
            self.assertFalse(any("'a'" in w or "''" in w for w in rep["warnings"]), rules)
        for lang in (None, 5, "", "ja_JP"):
            prose_report(body, lang)
        self.assertEqual(prose_report("", "ko")["stats"]["sentences"], 0)
        self.write("docs/editorial/gate-rules.json", json.dumps({"prose": None, "links": None}))
        self.article("p7")
        rep = validate(self.root, self.cfg, "src/content/blog/p7.md")
        self.assertIn("prose", rep)

    def test_custom_validator_with_broken_rules_keeps_its_own_verdict(self):
        self.write("src/content/blog/p8.md", "---\ntitle: a\nslug: p8\n---\nIn conclusion, it ends.\n")
        self.write("docs/editorial/gate-rules.json", "{not json")
        self.cfg.data["commands"]["validate"] = "true"
        rep = store.run_gate(self.root, self.cfg, "p8")
        self.assertTrue(rep["ok"], rep)
        self.assertIn("hints unavailable", rep["prose"]["warnings"][0])
        self.cfg.data["commands"]["validate"] = "false"
        self.write("docs/editorial/gate-rules.json", json.dumps({}))
        rep = store.run_gate(self.root, self.cfg, "p8")
        self.assertFalse(rep["ok"])
        self.assertTrue(any("in conclusion" in w for w in rep["prose"]["warnings"]), rep)

    def test_japanese_and_chinese_split_without_spaces(self):
        zh = "考试在七月举行。考试在十二月举行。报名三月开始。" * 3
        rep = prose_report(zh, "zh")
        self.assertEqual(rep["stats"]["sentences"], 9)
        self.assertEqual(rep["stats"]["long"], 0)
        ja = ("受験料は5,500円です（税込）。試験は年2回です（仮定）。会場は東京です（仮定）。"
              "時間は2時間です（仮定）。空港（くうこう）に行きます。")
        rep = prose_report(ja, "ja_JP")
        hints = " | ".join(rep["warnings"])
        self.assertIn("(仮定) appears 3 times", hints)
        self.assertNotIn("くうこう", hints)
        self.assertEqual(rep["stats"]["sentences"], 5)
        self.assertEqual(rep["stats"]["limit"], 80)

    def test_line_numbers_comments_scripts_tables_abbreviations(self):
        body = ("First line of a paragraph.\nSecond line, " + "very " * 40 + "long.\n\n"
                "<!-- a comment\nIn conclusion, hidden.\n-->\n"
                "<script>\ndelve();\n</script>\n"
                "a | b | c\n1 | 2 | 3\n\n"
                "See e.g. the guide by Dr. Kim. It was 2024-01-15 at 10:30 with v1.2.3.\n")
        rep = prose_report(body, "en", offset=10)
        hints = " | ".join(rep["warnings"])
        self.assertIn("line 12 ", hints)
        self.assertNotIn("conclusion", hints)
        self.assertNotIn("delve", hints)
        self.assertNotIn("numbers", hints)
        self.assertEqual(rep["stats"]["sentences"], 4)
        self.assertNotIn("asides", " | ".join(prose_report("한국어(韓國語)와 일본어(日本語), 영어(英語)를 씁니다.", "ko")["warnings"]))

    def test_breaks_two_column_tables_emphasis_and_list_before_break(self):
        from hrdlib.prose import _paragraphs
        self.assertEqual([t for para in _paragraphs("Para one.\n\n---\n\nPara two.\n\n* * *\n\nMore.\n***\n")
                          for _, t in para], ["Para one.", "Para two.", "More."])
        self.assertEqual(_paragraphs("a | b\n--- | ---\n1 | in conclusion\n\nAfter."), [[(5, "After.")]])
        self.assertEqual(prose_report("**Bold.** Next one.", "en")["stats"]["sentences"], 2)
        self.assertIn("'delve'", " ".join(prose_report("- item delve here.\n---\n", "en")["warnings"]))
        self.assertEqual(_paragraphs("Title\n---\nbody"), [[(3, "body")]])

    def test_custom_validator_json_errors_are_kept(self):
        self.write("src/content/blog/q1.md", "---\ntitle: a\nslug: q1\n---\nText.\n")
        self.write("check.py", "import json; print(json.dumps({'ok': False, 'errors': ['real error'], "
                               "'prose': {'warnings': ['x' * 900]}})); raise SystemExit(1)\n")
        self.cfg.data["commands"]["validate"] = "python3 check.py"
        rep = store.run_gate(self.root, self.cfg, "q1")
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["errors"], ["real error"])
        self.write("check.py", "import json; print('> blog@1.0.0 validate'); print(json.dumps({'ok': False, "
                               "'errors': ['after banner'], 'prose': {'warnings': ['x' * 900]}}, indent=2)); "
                               "raise SystemExit(1)\n")
        self.assertEqual(store.run_gate(self.root, self.cfg, "q1")["errors"], ["after banner"])
        self.write("check.py", "print('all good')\n")
        self.assertEqual(store.run_gate(self.root, self.cfg, "q1")["errors"], [])
        from hrdlib.prose import _paragraphs
        self.assertEqual(_paragraphs("Header\n| --- |\n| x |\n\nText."), [[(5, "Text.")]])

    def test_quotes_weekdays_glosses_mdx_toml(self):
        from hrdlib.prose import _sentences
        self.assertEqual([t for _, t in _sentences('「はい。」と言った。He said "Hi." Then e.g. this ends.')],
                         ["「はい。」と言った。", 'He said "Hi."', "Then e.g. this ends."])
        self.assertEqual(prose_report("12월 6일(일), 13일(일), 20일(일). 음독(音読み)과 시험(日本語能力試験, にほんご)이다.",
                                      "ko")["warnings"], [])
        self.assertEqual(prose_report('import X from "y"\n\n:::note\n\nOne.\n', "en")["stats"]["sentences"], 1)
        self.assertEqual(prose_report("長い" * 60 + "。", "jp")["stats"]["long"], 1)
        self.write("src/content/blog/q2.md", '+++\ntitle = "Delve into 2024 1 2 3 4"\n+++\nShort text.\n')
        from hrdlib.validate import prose_for
        self.assertEqual(prose_for(self.root, self.cfg, "src/content/blog/q2.md")["warnings"], [])

    def test_dialogue_dates_and_hard_wrapped_import(self):
        from hrdlib.prose import _sentences
        self.assertEqual([t for _, t in _sentences("「ばかな！ このオレが…だと！？」と叫んだ。See Fig. 2 now.")],
                         ["「ばかな！ このオレが…だと！？」と叫んだ。", "See Fig. 2 now."])
        self.assertEqual(prose_report("2026년 JLPT는 7월 5일과 12월 6일 두 번 있고 3시 30분에 시작합니다.", "ko")["warnings"], [])
        self.assertEqual(len(list(_sentences("Japan must\nimport most wheat, raising\nexport prices."))), 1)
        self.assertEqual(len(list(_sentences("今日は晴れです。\n明日は雨です。 次です。"))), 3)
        self.assertEqual(len(list(_sentences("Meet at 3 p.m. Tomorrow we go."))), 2)
        self.assertEqual(prose_report("GitHub Security LabはCommunity CodeQL Bountyを開始しました。", "ja")["stats"]["long"], 0)

    def test_gate_command_writes_prose_file_for_the_editor(self):
        self.write("docs/editorial/gate-rules.json", json.dumps({}))
        self.article("p9", "In conclusion, done.")
        self.write(".claude/herald/work/t0001/state.json", json.dumps({"slug": "p9"}))
        out, _ = self.hrd("gate", "--topic", "t0001")
        self.assertEqual(out["prose_file"], ".claude/herald/memory/prose/t0001.json")
        with open(os.path.join(self.root, out["prose_file"])) as f:
            saved = json.load(f)
        self.assertEqual(saved["warnings"], out["prose"]["warnings"])
        self.assertEqual(saved["body_hash"], hashing.worktree_hash(self.root, self.cfg, "p9"))
        sh(self.root, "git", "add", "-A")
        self.assertEqual(sh(self.root, "git", "status", "--porcelain", "--", ".claude/herald/memory").strip(), "")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude/herald/work/t0001/prose.json")))

    def test_language_names_blockquotes_fences_setext(self):
        self.assertIn("over 80 chars", " ".join(prose_report("長い" * 60 + "。", "日本語")["warnings"]))
        self.assertIn("over 80 chars", " ".join(prose_report("長い" * 60 + "。", "Japanese")["warnings"]))
        body = ("````\n```\ndelve\n```\n````\nUse `in conclusion` here.\n\nTitle delve\n=====\n\n"
                "> In conclusion, quoted.\n\n- item one.\n\n    second para of item, embark on it.\n\n"
                "Take vitamin C. It helps.\n")
        rep = prose_report(body, "en")
        self.assertEqual(rep["warnings"], ["prose: stock phrase 'embark on' ×1"])
        self.assertEqual(rep["stats"]["sentences"], 5)
        self.assertIn("1 sentence(s) with 1+ numbers", " ".join(prose_report("It costs 5 dollars.", "en", {"max_numbers": 1})["warnings"]))


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

    def test_reports_the_session_it_read_so_later_readings_can_pin_it(self):
        home = tempfile.mkdtemp()
        root = "/tmp/hrd-measure-repo"
        base = os.path.join(home, ".claude", "projects", measure.project_key(root))
        os.makedirs(base)
        for sid in ("older", "newer"):
            with open(os.path.join(base, sid + ".jsonl"), "w") as f:
                f.write("{}\n")
            os.utime(os.path.join(base, sid + ".jsonl"), (1, 1) if sid == "older" else None)
        old = os.environ.get("HOME")
        os.environ["HOME"] = home
        try:
            self.assertEqual(measure.measure(root, {})["session"], "newer")
            self.assertEqual(measure.measure(root, {}, session="older")["session"], "older")
            self.assertIsNone(measure.measure(root, {}, files=[os.path.join(base, "older.jsonl")])["session"])
            missing = measure.measure(root, {}, session="gone")
            self.assertEqual((missing["found"], missing["total_usd"]), (False, 0.0))  # never a silent 0 spent
            self.assertTrue(measure.measure(root, {})["found"])
        finally:
            os.environ["HOME"] = old


if __name__ == "__main__":
    unittest.main()
