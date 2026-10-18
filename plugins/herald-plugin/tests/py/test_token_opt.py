"""Token optimization, phase A (design/herald/04-token-optimization.md): measure.py's config
directory, sub-agent labels and context attribution (synthetic transcripts only — real ones hold
private data), and the trimmed HRD outputs."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import SCRIPTS, RepoCase, sh
from test_social import SocialCase, guide_head, guide_text  # noqa: F401

from hrdlib import measure, store
from hrdlib.hashing import bundle_hash

USAGE = lambda prefix, out=10: {"input_tokens": 0, "cache_read_input_tokens": prefix, "cache_creation_input_tokens": 0,  # noqa: E731
                                "output_tokens": out}


def asst(mid, prefix, tools=(), out=10):
    content = [{"type": "tool_use", "id": tid, "name": name, "input": inp} for tid, name, inp in tools]
    return {"type": "assistant", "cwd": "/repo", "message": {"id": mid, "model": "claude-sonnet-5-5",
                                                             "usage": USAGE(prefix, out), "content": content}}


def result(tid, text):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]},
            "toolUseResult": {"file": text}}


class ConfigDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp, "cfg")  # never the real one
        self.root = "/tmp/hrd-token-repo"
        self.base = os.path.join(self.tmp, "cfg", "projects", measure.project_key(self.root))
        os.makedirs(os.path.join(self.base, "s1", "subagents", "workflows", "w1"))

    def tearDown(self):
        if self.old is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old

    def jsonl(self, path, rows):
        with open(path, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def agent(self, rel, meta, prompt="do it"):
        p = os.path.join(self.base, "s1", "subagents", rel)
        self.jsonl(p, [{"type": "user", "message": {"content": prompt}}, asst("a-" + rel, 1000)])
        with open(p[:-len(".jsonl")] + ".meta.json", "w") as f:
            json.dump(meta, f)

    def test_config_dir_nested_agents_and_labels(self):
        notif = "<task-notification><tool-use-id>tu-1</tool-use-id><result>draft done</result></task-notification>"
        self.jsonl(os.path.join(self.base, "s1.jsonl"), [
            {"type": "user", "isMeta": True, "message": {"content": "Base directory for this skill: /x/skills/hrd\n\n# Herald"}},
            asst("m1", 20000, [("r1", "Bash", {"command": "cat /cache/herald/skills/hrd/commands/atoms/_contract.md"})]),
            result("r1", "x" * 4000),
            asst("m2", 21100, [("r2", "Bash", {"command": "python3 .claude/herald/scripts/hrd.py social prepare --sns x"})]),
            result("r2", "y" * 800),
            asst("m2", 21100),  # a streamed duplicate: counted once
            asst("m3", 21400, [("r3", "Read", {"file_path": "/repo/docs/editorial/persona.md"}),
                               ("tu-1", "Agent", {"description": "Herald: distributor — promo"})]),
            result("r3", "z" * 2000), result("tu-1", "Async agent launched"),
            {"type": "attachment", "attachment": {"type": "prompt_snapshot", "systemPrompt": "s" * 5000}},
            {"type": "attachment", "attachment": {"type": "queued_command", "prompt": notif}},
            {"type": "attachment", "attachment": {"type": "hook_success", "content": "", "hookEvent": "PreToolUse"}},
            asst("m4", 22300, [("r4", "Bash", {"command": "python3 .claude/herald/scripts/measure.py --session s1"})]),
            result("r4", "{}"),
            {"type": "system", "subtype": "compact_boundary"},
            asst("m5", 5000),
        ])
        self.agent("agent-a1.jsonl", {"agentType": "distributor", "description": "Herald: distributor — promo",
                                      "toolUseId": "tu-1"})
        self.agent("agent-a2.jsonl", {"agentType": "Explore", "description": "review it"},
                   prompt="You are an external auditor. Read the article.")
        self.agent("workflows/w1/agent-a3.jsonl", {"agentType": "workflow-subagent", "description": "x"},
                   prompt="the writer persona")
        out = measure.measure(self.root, {"sonnet": 3.0}, detail=True)
        self.assertTrue(out["found"])
        self.assertEqual(set(out["roles"]), {"distributor", "auditor", "writer"})
        self.assertEqual(out["detail"]["tasks"]["distributor — promo"]["spawns"], 1)
        m = out["detail"]["main"]
        self.assertEqual(m["turns"], 5)
        self.assertEqual(m["compactions"], 1)
        self.assertIn("skill commands/atoms/_contract.md", m["sources"])
        self.assertIn("hrd social prepare", m["sources"])
        self.assertIn("read docs/editorial/persona.md", m["sources"])
        self.assertIn("agent distributor — promo", m["sources"])
        self.assertEqual(m["measure_calls"], 1)
        self.assertIn("prompt_snapshot", m["excluded_bytes"])
        self.assertIn("hook_success", m["excluded_bytes"])  # the guard's answer is never visible
        self.assertEqual(m["skill_dirs"], ["/x/skills/hrd"])
        self.assertEqual(m["sources"]["read docs/editorial/persona.md"]["bytes"], 2000)  # toolUseResult not counted twice

    def test_cli_outside_a_repo_with_prices(self):
        self.jsonl(os.path.join(self.base, "s1.jsonl"), [asst("m1", 1000000, out=0)])
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "measure.py"), "--transcript-dir", self.base,
                            "--session", "s1", "--detail", "--prices", '{"sonnet": 3}'],
                           capture_output=True, text=True, cwd=self.tmp)
        out = json.loads(p.stdout)
        self.assertEqual((out["total_usd"], out["detail"]["prices"]), (0.3, {"sonnet": 3}))
        self.assertNotIn("\n", p.stdout.strip())  # compact JSON


class OutputCase(SocialCase):
    def test_integrity_counts_quiet_rows_and_keeps_the_deploy_set(self):
        led = os.path.join(self.root, ".claude/herald/ledger/verified.jsonl")
        os.makedirs(os.path.dirname(led), exist_ok=True)
        with open(led, "w") as f:
            f.write(json.dumps({"topic_id": "t0001", "verified_hash": bundle_hash(self.root, self.cfg, "old-post")}) + "\n")
        out = self.hrd("integrity", "--report")[0]
        self.assertEqual((out["ok_count"], out["articles"]), (1, []))
        self.set_prs([{"number": 7, "state": "MERGED", "headRefName": "herald/t0009--old-post",
                       "mergedAt": "2026-10-01T00:00:00Z", "labels": ["herald"], "baseRefName": "main", "title": "t"}])
        out = self.hrd("integrity", "--report", check=False)[0]
        self.assertTrue(any(r["slug"] == "old-post" for r in out["articles"]))  # merged_unrecorded stays listed
        out = self.hrd("integrity", "--predeploy", "--report", check=False)[0]
        self.assertNotIn("ok_count", out)

    def test_social_check_output_and_merge(self):
        rel = self.daily("Rainy day.")
        out = self.hrd("social", "check", "--file", rel)[0]
        self.assertNotIn("sha256", out[0])
        p = os.path.join(self.root, ".claude/herald/memory/social/pending/channels/x.md")
        self.write(".claude/herald/memory/social/pending/channels/x.md", guide_text(guide_head(researched_at="2099-01-01")))
        out = self.hrd("social", "merge", "--sns", "x", "--researched", p)[0]
        self.assertNotIn("house_untouched", out)
        self.assertIn("diff", out)

    def test_gsc_show_slug(self):
        mem = os.path.join(self.root, ".claude/herald/memory")
        os.makedirs(mem, exist_ok=True)
        with open(os.path.join(mem, "metrics.json"), "w") as f:
            json.dump({"at": "x", "window_days": 28, "articles": [{"slug": "a", "lang": "en"}, {"slug": "a", "lang": "ja"},
                                                                  {"slug": "b"}]}, f)
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "gsc.py"), "show", "--slug", "a"],
                           capture_output=True, text=True, cwd=self.root)
        out = json.loads(p.stdout)
        self.assertEqual((len(out["articles"]), out["at"], out["window_days"]), (2, "x", 28))


if __name__ == "__main__":
    unittest.main()
