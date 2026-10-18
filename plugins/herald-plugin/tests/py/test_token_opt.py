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
        self.assertEqual(m["measure"]["calls"], 1)
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
        self.assertEqual((out["total_usd"], out["detail"]["prices"]), (0.3, {"opus": 5.0, "sonnet": 3, "haiku": 1.0}))
        self.assertNotIn("\n", p.stdout.strip())  # compact JSON


class DetailRound1Case(ConfigDirCase):
    test_config_dir_nested_agents_and_labels = None  # inherited fixtures only
    test_cli_outside_a_repo_with_prices = None

    def run_detail(self, rows, labels=None):
        p = os.path.join(self.base, "s2.jsonl")
        self.jsonl(p, rows)
        return measure.main_detail(p, labels or {})

    def test_sync_agent_results_synthetic_turns_and_compaction(self):
        rows = [
            asst("m1", 10000),
            {"type": "user", "message": {"content": [{"type": "text", "text": "go"}]}},
            asst("m2", 10100, [("a1", "Agent", {"description": "Herald: writer — draft"})]),
            result("a1", "the full writer report " * 200),  # a foreground (sync) spawn returns its report
            {"type": "assistant", "message": {"id": "e1", "model": "<synthetic>", "usage": {"input_tokens": 0,
                                                                                           "output_tokens": 0}}},
            asst("m3", 11400, [("r1", "Read", {"file_path": "/repo/big.md"})]),
            result("r1", "q" * 40000),
            asst("m4", 21500),
            {"type": "system", "subtype": "compact_boundary"},
            asst("m5", 3000),
            asst("m6", 3100),
        ]
        m = self.run_detail(rows)
        self.assertEqual(m["turns"], 6)  # the synthetic error turn is not a turn
        self.assertIn("agent writer — draft", m["sources"])
        self.assertNotIn("agent launch", " ".join(m["sources"]))
        self.assertEqual(m["compactions"], 1)
        big = m["sources"]["read big.md"]
        self.assertEqual(big["integral"], big["est_tokens"] * 1)  # m4 only: it left at the compaction (m5)

    def test_task_id_only_notifications_and_background_bash(self):
        rows = [
            asst("m1", 1000, [("b1", "Bash", {"command": "python3 .claude/herald/scripts/hrd.py begin t0001", "run_in_background": True})]),
            result("b1", "started"),
            asst("m2", 1100),
            {"type": "user", "message": {"content": "<task-notification><task-id>abc</task-id>done</task-notification>"}},
            {"type": "attachment", "attachment": {"type": "queued_command",
                                                  "prompt": "<task-notification><tool-use-id>b1</tool-use-id>exit 0</task-notification>"}},
            asst("m3", 1300),
        ]
        m = self.run_detail(rows, {"abc": "researcher"})
        self.assertIn("agent researcher", m["sources"])
        self.assertIn("hrd begin", m["sources"])  # a slug or topic id is never part of the source name
        self.assertNotIn("hrd begin t", m["sources"])

    def test_default_prices_outside_a_repo_and_journal_files(self):
        u = {"input_tokens": 1000000, "output_tokens": 0}
        self.jsonl(os.path.join(self.base, "s1.jsonl"), [{"type": "assistant", "message": {"id": "o1", "model": "claude-opus-5-5", "usage": u}}])
        self.jsonl(os.path.join(self.base, "s1", "subagents", "workflows", "w1", "journal.jsonl"), [{"type": "started"}])
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "measure.py"), "--transcript-dir", self.base, "--session", "s1"],
                           capture_output=True, text=True, cwd=self.tmp)
        out = json.loads(p.stdout)
        self.assertEqual((out["total_usd"], out["roles"]), (5.0, {}))  # opus at its default price; no journal "agent"


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
        os.remove(os.path.join(self.root, "src/content/blog/old-post.md"))
        self.set_prs([])
        out = self.hrd("integrity", "--report", check=False)[0]
        self.assertEqual([r["status"] for r in out["articles"]], ["missing"])

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
        os.remove(os.path.join(mem, "metrics.json"))
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "gsc.py"), "show", "--slug", "a"],
                           capture_output=True, text=True, cwd=self.root)
        self.assertEqual(json.loads(p.stdout), None)


class DetailRound2Case(ConfigDirCase):
    test_config_dir_nested_agents_and_labels = None
    test_cli_outside_a_repo_with_prices = None

    def detail(self, rows, labels=None):
        p = os.path.join(self.base, "s3.jsonl")
        self.jsonl(p, rows)
        return measure.main_detail(p, labels or {})

    def test_compaction_without_boundary_and_summary_flag(self):
        m = self.detail([asst("m1", 50000), asst("m2", 51000), asst("m3", 9000), asst("m4", 9100)])
        self.assertEqual(m["compactions"], 1)  # a prefix drop alone
        m = self.detail([asst("m1", 50000), {"type": "user", "isCompactSummary": True, "message": {"content": "summary"}},
                         asst("m2", 48000)])
        self.assertEqual(m["compactions"], 1)

    def test_launch_stub_hooks_and_synthetic_carry_over(self):
        stub = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a1", "content": "launched"}]},
                "toolUseResult": {"status": "async_launched"}}
        syn = {"type": "assistant", "message": {"id": "e%d", "model": "<synthetic>", "usage": {"input_tokens": 0}}}
        rows = [asst("m1", 1000, [("a1", "Agent", {"description": "Herald: researcher—channel"})]), stub,
                {"type": "attachment", "attachment": {"type": "hook_success", "hookEvent": "SessionStart", "content": "ctx " * 50}},
                {"type": "attachment", "attachment": {"type": "hook_success", "hookEvent": "Stop", "content": "log " * 50}},
                dict(syn, message=dict(syn["message"], id="e1")), dict(syn, message=dict(syn["message"], id="e2")),
                asst("m2", 1500)]
        m = self.detail(rows)
        self.assertIn("agent researcher — channel (launch)", m["sources"])  # a dash without spaces still parses
        self.assertIn("attachment hook_success", m["sources"])
        self.assertIn("hook_success", m["excluded_bytes"])  # the Stop hook's output
        self.assertEqual(m["turns"], 2)

    def test_measure_inside_a_compound_command_and_bad_prices(self):
        m = self.detail([asst("m1", 1000, [("b1", "Bash", {"command": "python3 x/measure.py --session s && python3 x/hrd.py status"})]),
                         result("b1", "{}"), asst("m2", 1100)])
        self.assertEqual(m["measure"]["calls"], 1)
        self.jsonl(os.path.join(self.base, "s1.jsonl"), [asst("m1", 1000)])
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "measure.py"), "--transcript-dir", self.base,
                            "--session", "s1", "--prices", "[1]"], capture_output=True, text=True, cwd=self.tmp)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("JSON object", p.stderr)

    def test_bash_source_names(self):
        self.assertEqual(measure._bash_source("python3 .claude/herald/scripts/hrd.py trim --topic t1 --begin"), "hrd trim")
        self.assertEqual(measure._bash_source("python3 .claude/herald/scripts/hrd.py lock acquire --cmd x"), "hrd lock acquire")

    def test_bash_source_shell_shorthands(self):
        src = measure._bash_source
        hrd = "python3 .claude/herald/scripts/hrd.py"
        # a variable or a function standing for HRD, `eval`, a leading command before the definition
        self.assertEqual(src('H="%s"; $H version --against 1.0 && $H lock acquire --cmd x' % hrd), "hrd version")
        self.assertEqual(src('HRD="%s"; ${HRD} social check --file a.md' % hrd), "hrd social check")
        self.assertEqual(src('H="%s"; eval "$H sync" && eval "$H lock release --cmd x"' % hrd), "hrd sync")
        self.assertEqual(src('H() { %s "$@"; }; H social prepare --sns x --n 2' % hrd), "hrd social prepare")
        self.assertEqual(src('echo "U=$HRD_UNATTENDED"; H="%s"; $H lock acquire --cmd x' % hrd), "hrd lock acquire")
        self.assertEqual(src('eval "%s lock release"' % hrd), "hrd lock release")
        self.assertEqual(src("%s --help 2>&1 | head -60" % hrd), "hrd")
        # a definition alone runs nothing
        self.assertEqual(src('H="%s"; git status' % hrd), "bash git")
        # prompt files through a path variable, or relative after `cd <plugin>`
        self.assertEqual(src("S=/p/skills/hrd/commands; sed -n 1,80p $S/write.md; ls $S/atoms"), "skill commands/write.md")
        self.assertEqual(src("cd /p/herald-plugin; cat skills/hrd/commands/translate.md; cd -"), "skill commands/translate.md")
        self.assertEqual(src("cat /p/skills/hrd/commands/a.md /p/skills/hrd/SKILL.md"), "skill commands/a.md +1")
        # the first statement that runs something
        self.assertEqual(src("SD=/p/skills/hrd; grep -n x .claude/agents/a.md"), "bash grep")
        self.assertEqual(src("T=tr-a-20261018; git log -1"), "bash git")
        self.assertEqual(src("cd repo && ls"), "bash ls")
        self.assertEqual(src("X=1"), "bash ?")
        self.assertEqual(src("cd /repo"), "bash cd")
        # a command that only reads or names hrd.py is not an HRD call
        for c in ("sed -n 1,40p .claude/herald/scripts/hrd.py", "grep -n x .claude/herald/scripts/hrd.py",
                  "git diff -- .claude/herald/scripts/hrd.py", "cat .claude/herald/scripts/hrd.py | head"):
            self.assertEqual(src(c), "bash " + c.split()[0], c)
        # other definition forms; a value with `$`; a reference takes the last definition before it
        self.assertEqual(src('export H="%s"; git status' % hrd), "bash git")
        self.assertEqual(src('declare -r H="%s"; $H sync' % hrd), "hrd sync")
        self.assertEqual(src('H="python3 $(git rev-parse --show-toplevel)/.claude/herald/scripts/hrd.py"; $H sync'), "hrd sync")
        self.assertEqual(src('H="python3 $R/.claude/herald/scripts/hrd.py"; git status'), "bash git")
        self.assertEqual(src('H() { %s "$@" 2>&1; }; H sync' % hrd), "hrd sync")
        self.assertEqual(src('function H { %s $@; }; H sync' % hrd), "hrd sync")
        self.assertEqual(src('H() {\n  %s "$@"\n}\nH lock acquire --cmd x' % hrd), "hrd lock acquire")
        self.assertEqual(src('H=git; $H status'), "bash git")
        self.assertEqual(src('H="%s"; $H "sync"' % hrd), "hrd sync")
        # env prefixes
        self.assertEqual(src("GIT_PAGER=cat git log -3"), "bash git")
        self.assertEqual(src("HRD_UNATTENDED=1 %s lock acquire --cmd x" % hrd), "hrd lock acquire")
        self.assertEqual(src('VAR="a b" git status'), "bash git")
        # whatever runs the script: wrappers, flags with values, quoted "$(…)" paths, ./hrd.py, eval
        script = ".claude/herald/scripts/hrd.py"
        for c in ('python3 "$(git rev-parse --show-toplevel)"/%s sync' % script,
                  'python3 "$(git rev-parse --show-toplevel)/%s" sync' % script,
                  'R="$(git rev-parse --show-toplevel)"; python3 "$R/%s" sync' % script,
                  "python3 -X utf8 %s sync" % script, "timeout 120 ./%s sync" % script,
                  "$PYTHON %s sync" % script, 'eval "./%s sync"' % script,
                  "python3 %s \\\n  sync" % script):
            self.assertEqual(src(c), "hrd sync", c)
        self.assertEqual(src("if ./%s lock acquire --cmd x; then :; fi" % script), "hrd lock acquire")
        # a definition or a comment on its own line is not a call; braces and nesting in functions
        self.assertEqual(src('# H="%s"\ngit status' % hrd), "bash git")
        self.assertEqual(src('H() { python3 "${ROOT}/%s" "$@"; }; H sync' % script), "hrd sync")
        self.assertEqual(src('H() { %s "$@"; }; G() { H "$@"; }; G sync' % hrd), "hrd sync")
        # the file the reading statement reads
        self.assertEqual(src("grep -l x /p/skills/hrd/commands/a.md; cat /p/skills/hrd/commands/b.md"), "skill commands/b.md")
        self.assertEqual(src("(cd sub && make)"), "bash make")
        # backticks and redirections after the subcommand; keywords before a function call
        self.assertEqual(src("echo `%s sync`" % hrd), "hrd sync")
        self.assertEqual(src("%s sync>/tmp/o" % hrd), "hrd sync")
        self.assertEqual(src('H() { %s "$@"; }; if ! H lock acquire --cmd x; then exit 1; fi' % hrd), "hrd lock acquire")
        self.assertEqual(src('H="%s" # the cli\n$H sync' % hrd), "hrd sync")
        self.assertEqual(src('  H="%s"\n  $H sync' % hrd), "hrd sync")
        # a command substitution in an assignment is what runs
        self.assertEqual(src("SHA=$(git rev-parse HEAD)\ngit show $SHA"), "bash git")
        # every prompt file the reading statements read, after an env prefix or a brace too
        self.assertEqual(src("LC_ALL=C cat /p/skills/hrd/commands/write.md"), "skill commands/write.md")
        self.assertEqual(src("cat /p/skills/hrd/commands/w.md; echo ---; cat /p/skills/hrd/commands/s.md"), "skill commands/w.md +1")
        self.assertEqual(src("{ cat /p/skills/hrd/commands/x.md; }"), "skill commands/x.md")
        # quotes and comments are honoured when splitting statements
        self.assertEqual(src("sed -n '1,40p;120,160p' /p/skills/hrd/commands/write.md"), "skill commands/write.md")
        self.assertEqual(src('P="/p/skills/hrd"; cat "$P"/commands/write.md'), "skill commands/write.md")
        self.assertEqual(src("# build & test; then ship\nnpm test"), "bash npm")
        # an assignment from a substitution, quoted or not, runs that command
        for c, want in (('SHA="$(git rev-parse HEAD)"', "bash git"), ("ROOT=$(pwd)", "bash pwd"),
                        ('OUT="$(gh pr view 1)"; echo "$OUT"', "bash gh"), ("BR=`git branch`; echo $BR", "bash git")):
            self.assertEqual(src(c), want, c)
        # a later redefinition does not change an earlier reference; $* bodies; hyphenated names
        self.assertEqual(src('H=git; $H status; H="%s"' % hrd), "bash git")
        self.assertEqual(src("H() { %s $*; }; H sync" % hrd), "hrd sync")
        self.assertEqual(src('hrd-cli() { %s "$@"; }; hrd-cli sync' % hrd), "hrd sync")
        # substitutions: an HRD call or a read inside one, pipes and nested quotes inside one
        self.assertEqual(src('H="%s"; OUT="$($H status --json)"; echo done' % hrd), "hrd status")
        self.assertEqual(src('X="$(cat "/p/skills/hrd/commands/write.md")"'), "skill commands/write.md")
        self.assertEqual(src("COUNT=$(ls posts | wc -l); echo $COUNT"), "bash ls")
        self.assertEqual(src('MSG="$(git log -1 --format="%s")"; echo "$MSG"'), "bash git")
        # a heredoc body is data: an apostrophe in it does not swallow later statements
        self.assertEqual(src("cat <<'EOF' > /tmp/x.md\nit's done\nEOF\ncat /p/skills/hrd/commands/a.md"),
                         "skill commands/a.md")
        self.assertEqual(src("N=$(( N + 1 )); git push"), "bash git")  # arithmetic is not a command
        # an env prefix holding a substitution; a substitution's own cd and env prefixes
        self.assertEqual(src("PYTHONPATH=$(pwd) python3 -m unittest"), "bash python3")
        self.assertEqual(src("D=$(pwd) cat /p/skills/hrd/commands/a.md"), "skill commands/a.md")
        self.assertEqual(src("SHA=$(cd /repo && git rev-parse HEAD)"), "bash git")
        # redirections with & are not separators; a here-string is not a heredoc
        self.assertEqual(src("cd /repo >/dev/null 2>&1; npm test"), "bash npm")
        self.assertEqual(src("read -r a <<< foo\ncat /p/skills/hrd/commands/a.md"), "skill commands/a.md")

    def test_bash_source_long_inputs_stay_fast(self):
        import time
        doubling = "".join('A%d="$A%d$A%d"; ' % (i + 1, i, i) for i in range(30))
        for cmd in ('"; f() { ' * 6000, "f() { a" + " " * 40000 + 'x"$@"', "A=1\n" * 25000, "\n" * 50000,
                    " " * 50000, "(x)" * 16000, "(" * 50000, doubling,
                    "f() { " + "a " * 10000 + ' "$@"; }\n' + "f;" * 15000,  # a long body called often
                    'H="' + "a" * 4000 + '"\n' + "$H;" * 15000,  # a long value referenced often
                    "function f" + " " * 50000, "cat " + "/skills/hrd" * 4540, "$(" * 25000, "<<A\n" * 10000,
                    'B="' + "x" * 4000 + '"; A=$(' + "$B" * 11000 + ")",  # a long value inside a substitution
                    "S=" + "/skills/hrd" * 372 + "; cat " + "/skills/hrd" * 4000 + "$S" * 37):
            t = time.time()
            self.assertIsInstance(measure._bash_source(cmd), str)
            self.assertLess(time.time() - t, 1.0)


class PricesInRepoCase(RepoCase):
    def test_partial_config_prices_merge_defaults(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp))
        cfg["models"] = {"prices": {"sonnet": 4.0}}
        self.write(".claude/herald/config.json", json.dumps(cfg))
        from hrdlib.config import Config
        self.assertEqual(Config.load(self.root).get("models", "prices")["opus"], 5.0)


if __name__ == "__main__":
    unittest.main()
