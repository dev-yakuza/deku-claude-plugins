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
