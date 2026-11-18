"""K4 — platform additions and the K3 carry-overs: gh read/write forms (author association, closed-by
PRs, PR state, issue close), the pause `cause:` field, role-output reading (P1), the spec store and its
install through fsafe, base config (carry-over 1), the H§M line on execute env stops (3), legacy
unreadable pending lines (6), sub-directory / alternative check configs (7), the AST raw-write lint and
O_NOFOLLOW reads (11), judge specs/schemas/coercions for the K4 groups."""

import ast
import json
import os
import unittest

import _util  # noqa: F401
from _k1 import Clock, git, repo, tmpdir
from _k4 import K4, comment, decision, out_role

from guildcore import fsafe as FS
from guildcore import schema as SCH
from guildcore.adapters import gh as GH
from guildcore.records import audit as AU
from workflows.dev import judging as JG
from workflows.dev import ports as PO
from workflows.dev import roleout as RO

ENGINE = _util.ENGINE


class GhForms(unittest.TestCase):
    def test_new_read_forms_are_reads(self):
        GH.assert_read_only(["gh", "api", "repos/o/r/issues/7", "--jq", ".author_association"])
        GH.assert_read_only(["gh", "issue", "view", "7", "--json", "closedByPullRequestsReferences"])
        GH.assert_read_only(["gh", "pr", "view", "3", "--json", "number,state,mergedAt,url"])
        with self.assertRaises(GH.GhError):
            GH.assert_read_only(["gh", "api", "repos/o/r/issues/7", "-X", "PATCH"])

    def test_close_write_form_and_reason_guard(self):
        GH.assert_write_form(["gh", "api", "repos/o/r/issues/7", "-X", "PATCH", "--input", "-"])
        seen = []
        w = GH.GhWriteCli("o/r", runner=lambda argv, stdin: seen.append((argv, stdin)) or "{}")
        w.close_issue(7, "not_planned")
        self.assertEqual(json.loads(seen[0][1]), {"state": "closed", "state_reason": "not_planned"})
        with self.assertRaises(GH.GhError):
            w.close_issue(7, "spam")

    def test_cli_reads_parse(self):
        def run(argv):
            if "closedByPullRequestsReferences" in argv:
                return json.dumps({"closedByPullRequestsReferences": [
                    {"number": 4, "repository": {"name": "r", "owner": {"login": "o"}}}]})
            return "MEMBER\n"
        g = GH.GhCli("o/r", runner=run)
        self.assertEqual(g.closed_by_prs(7), [{"number": 4, "repo": "o/r"}])
        self.assertEqual(g.issue_author_association(7), "MEMBER")

    def test_issue_close_verified_and_idempotent(self):
        h = K4(self)
        self.assertTrue(h.writer.issue_close(7, "completed"))
        self.assertEqual(h.issue()["state"], "CLOSED")
        self.assertFalse(h.writer.issue_close(7, "completed"))
        h2 = K4(self)
        h2.w.lose_next(5)
        with self.assertRaises(GH.GhWriteError):
            h2.writer.issue_close(7, "completed")


class PauseCause(unittest.TestCase):
    def test_pending_block_carries_the_cause_line(self):
        from guildcore import ask as ASK
        from workflows.dev.stages import base as B
        h = K4(self)
        q = ASK.Question("readiness", "Goal unclear — x", [{"token": "i1", "label": "a"}, {"token": "stop", "label": "s"}])
        r = B.pause(h.p, "analyze", "ambiguity", "Goal unclear — x", "ambiguity: Goal unclear — x", question=q)
        blk = h.decisions_of("ask:readiness")[0]
        self.assertEqual(blk.get("cause"), "ambiguity: Goal unclear — x")
        self.assertEqual(r.qid, blk.id)


class RoleOut(unittest.TestCase):
    def test_reads_only_regular_files_inside_out(self):
        h = K4(self)
        outside = os.path.join(tmpdir(self), "x.txt")
        with open(outside, "w") as fh:
            fh.write("SECRET")
        res = out_role(self, files={"a.md": "ok", "sub/b.md": "deep"}, links={"l.md": outside})
        self.assertEqual(RO.read(h.p, "design", res, "out/a.md"), "ok")
        self.assertEqual(RO.read(h.p, "design", res, "sub/b.md"), "deep")
        for bad in ("out/l.md", "../x.txt", outside, "out/missing.md", "out/../../x.txt", ""):
            self.assertIsNone(RO.read(h.p, "design", res, bad), bad)
        os.mkfifo(os.path.join(res.run_dir, "out", "fifo"))
        self.assertIsNone(RO.read(h.p, "design", res, "out/fifo"))
        big = out_role(self, files={"big.md": "x" * 100})
        self.assertIsNone(RO.read(h.p, "design", big, "out/big.md", cap=10))
        self.assertGreaterEqual(len(h.decisions_of("role-path-refused")), 6)

    def test_json_out_must_be_an_object(self):
        h = K4(self)
        self.assertIsNone(RO.json_out(h.p, "design", out_role(self, files={"s.json": "[1]"}), "out/s.json"))
        self.assertEqual(RO.json_out(h.p, "design", out_role(self, files={"s.json": {"split": False}}), "out/s.json"),
                         {"split": False})


class SpecStore(unittest.TestCase):
    def test_install_into_worktree_through_fsafe(self):
        store = tmpdir(self)
        with open(os.path.join(store, "skeleton.md"), "w") as fh:
            fh.write("# S\n")
        with open(os.path.join(store, "split.json"), "w") as fh:
            fh.write("{}")
        wt = tmpdir(self)
        inst, kept = RO.install(store, wt, 7)
        self.assertEqual(inst, ["docs/specs/7/skeleton.md"])
        self.assertFalse(os.path.exists(os.path.join(wt, "docs/specs/7/split.json")))
        inst2, kept2 = RO.install(store, wt, 7)
        self.assertEqual((inst2, kept2), ([], ["docs/specs/7/skeleton.md"]))

    def test_install_refuses_a_planted_link(self):
        store = tmpdir(self)
        with open(os.path.join(store, "skeleton.md"), "w") as fh:
            fh.write("# S\n")
        wt, outside = tmpdir(self), tmpdir(self)
        os.makedirs(os.path.join(wt, "docs"))
        os.symlink(outside, os.path.join(wt, "docs", "specs"))
        with self.assertRaises(FS.UnsafePath):
            RO.install(store, wt, 7)
        self.assertEqual(os.listdir(outside), [])

    def test_spec_names_guarded(self):
        h = K4(self)
        for bad in ("../x.md", "a/b.md", ".hidden.md", "x.sh"):
            with self.assertRaises(ValueError):
                RO.put(h.p, bad, "x")


class BaseConfig(unittest.TestCase):
    def test_commands_engine_visual_from_base(self):
        from guildcore import config as CF
        cfg_base = {"version": "1", "language": "ko", "commands": {"test": "flutter test"},
                    "engine": {"effective": {"copy_ignored": []}}}
        d = repo(self, {".claude/guild/config.json": json.dumps(cfg_base)})
        git(d, "switch", "-q", "-c", "feature/x")
        cfg_branch = dict(cfg_base, commands={"test": "true"}, engine={"effective": {"copy_ignored": ["secret.env"]}},
                          language="en")
        with open(os.path.join(d, ".claude/guild/config.json"), "w") as fh:
            json.dump(cfg_branch, fh)
        loaded = CF.load(d)
        self.assertEqual(loaded.commands["test"], "true")
        c, note = PO.config_at_base(d, "main", loaded)
        self.assertEqual(c.commands["test"], "flutter test")
        self.assertEqual(c.engine["effective"]["copy_ignored"], [])
        self.assertEqual(c.language, "en")                         # non-execution keys stay the checkout's
        self.assertIn("from main", note)
        c2, note2 = PO.config_at_base(d, "nope", loaded)
        self.assertIs(c2, loaded)
        self.assertIn("unreadable", note2)


class ExecuteCarry(unittest.TestCase):
    def test_env_pause_carries_directive_none_line(self):
        from workflows.dev.stages import execute as X
        h = K4(self, labels=("guild:execute",))
        r = X.env_pause(h.p, "PR body unreadable", "PR body unreadable", "X5.11")
        self.assertEqual(r.kind, "PAUSE")
        nh = h.body_with("needs-human").split("\n")
        self.assertEqual(nh[1], "env: other — PR body unreadable")
        self.assertTrue(nh[2].startswith("사람 지시 확인: 없음 — 읽음: #7"))

    def test_env_pause_with_a_human_comment_asks_directive(self):
        from workflows.dev.stages import execute as X
        dj = decision("none", {"verdict": "none", "applies": [], "out_of_scope": []})
        h = K4(self, labels=("guild:execute",), comments=[comment("please retry tomorrow", 70)], judges={"DIRECTIVE": dj})
        X.env_pause(h.p, "PR body unreadable", "PR body unreadable", "X5.11")
        self.assertEqual([s.group for s in h.calls["judges"]], ["DIRECTIVE"])
        self.assertEqual(h.decisions_of("DIRECTIVE")[0].get("choice"), "none")

    def test_legacy_free_form_pending_is_recorded_not_guessed(self):
        from workflows.dev.stages import execute as X
        body = ("<!-- guild:auditor:execute -->\n### audit-record 1\ninvocation: 2026\nhead: %s\n"
                "| F1 | MAJOR | looped-back | null check |\n- looped-back · MAJOR · auditor · lib/a.dart:1 · x\n"
                "<!-- /guild:auditor:execute -->") % ("a" * 40)
        rec = AU.AuditRecord.parse(body)
        self.assertEqual(len(rec.blocks[0].findings), 1)
        self.assertEqual(rec.blocks[0].unreadable_pending, ["| F1 | MAJOR | looped-back | null check |"])
        h = K4(self, labels=("guild:execute",), comments=[comment(body, 60)])
        from workflows.dev.stages import base as B
        X.legacy_unreadable(h.p, B.records(h.p))
        X.legacy_unreadable(h.p, B.records(h.p))                   # once per block
        self.assertEqual(len(h.decisions_of("legacy-pending-unreadable")), 1)
        from workflows.dev import unattended_log as UL
        self.assertTrue(any("legacy-pending-unreadable" in x for x in UL.entries(h.gh.comments(7))))


class CheckConfigs(unittest.TestCase):
    def test_subdirectory_and_alt_formats_are_swapped_to_base(self):
        d = repo(self, {"analysis_options.yaml": "linter: {}\n", "lib/analysis_options.yaml": "analyzer: {}\n",
                        "README.md": "x\n"})
        base = git(d, "rev-parse", "HEAD")
        git(d, "switch", "-q", "-c", "feature/x")
        with open(os.path.join(d, "lib/analysis_options.yaml"), "w") as fh:
            fh.write('analyzer:\n  exclude: ["**"]\n')
        with open(os.path.join(d, "cspell.config.js"), "w") as fh:
            fh.write("module.exports = {ignorePaths: ['**']}\n")
        with open(os.path.join(d, "package.json"), "w") as fh:
            fh.write('{"cspell": {"ignorePaths": ["**"]}}')
        cands = PO.config_candidates(d, base)
        self.assertIn("lib/analysis_options.yaml", cands)
        self.assertIn("cspell.config.js", cands)
        h = K4(self, labels=("guild:execute",))
        restore = PO.base_check_configs(d, base, p=h.p)
        with open(os.path.join(d, "lib/analysis_options.yaml")) as fh:
            self.assertEqual(fh.read(), "analyzer: {}\n")
        self.assertFalse(os.path.exists(os.path.join(d, "cspell.config.js")))     # added by the branch → removed
        notes = [b.get("refs") for b in h.decisions_of("check-config-changed")]
        self.assertIn("lib/analysis_options.yaml", notes)
        self.assertTrue(h.decisions_of("check-config-in-manifest"))
        restore()
        with open(os.path.join(d, "lib/analysis_options.yaml")) as fh:
            self.assertIn("exclude", fh.read())
        self.assertTrue(os.path.exists(os.path.join(d, "cspell.config.js")))


# ---- carry-over 11: the AST raw-write lint ----------------------------------------------------------

OS_W = {"remove", "unlink", "rmdir", "removedirs", "makedirs", "mkdir", "chmod", "link", "symlink", "replace",
        "rename", "truncate", "utime"}
SH_W = {"copy", "copy2", "copyfile", "copytree", "rmtree", "move", "copymode", "copystat"}
SUB_W = {"tar", "cp", "ln", "mv", "rsync", "install"}


def _mode_writes(node):
    for a in node.args[1:2]:
        if isinstance(a, ast.Constant) and isinstance(a.value, str) and any(c in a.value for c in "wax+"):
            return True
    for k in node.keywords:
        if k.arg == "mode" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str) \
                and any(c in k.value.value for c in "wax+"):
            return True
    return False


def raw_writes(src):
    """(line, kind) of every write-capable call: open/os.open/io.open in a write mode, os.* file
    mutators, shutil.*, tarfile extract, Path.write_*, subprocess argv starting with tar/cp/ln/mv/…"""
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        f, why = node.func, None
        if isinstance(f, ast.Name) and f.id == "open" and _mode_writes(node):
            why = "open"
        elif isinstance(f, ast.Attribute):
            base = f.value.id if isinstance(f.value, ast.Name) else ""
            if base == "os" and f.attr in OS_W:
                why = "os." + f.attr
            elif base == "os" and f.attr == "open" and len(node.args) > 1 and any(
                    x in ast.dump(node.args[1]) for x in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC")):
                why = "os.open"
            elif base in ("io", "codecs") and f.attr == "open" and _mode_writes(node):
                why = base + ".open"
            elif base in ("shutil", "_sh") and f.attr in SH_W:
                why = "shutil." + f.attr
            elif f.attr in ("extractall", "extract"):
                why = f.attr
            elif f.attr in ("write_text", "write_bytes") and base not in ("FS", "fsafe"):
                why = f.attr
            elif base == "subprocess" and f.attr in ("run", "Popen", "call", "check_call", "check_output") and node.args:
                a = node.args[0]
                if isinstance(a, (ast.List, ast.Tuple)) and a.elts and isinstance(a.elts[0], ast.Constant) \
                        and a.elts[0].value in SUB_W:
                    why = "subprocess " + a.elts[0].value
        if why:
            out.append((node.lineno, getattr(node, "end_lineno", node.lineno), why))
    return out


class AstLint(unittest.TestCase):
    def test_every_write_capable_call_is_fsafe_or_justified(self):
        bad = []
        for base, _dirs, files in os.walk(ENGINE):
            if "/replay" in base or "__pycache__" in base:
                continue
            for f in files:
                if not f.endswith(".py") or f == "fsafe.py":
                    continue
                p = os.path.join(base, f)
                with open(p, encoding="utf-8") as fh:
                    src = fh.read()
                lines = src.split("\n")
                for a, b, why in raw_writes(src):
                    span = "\n".join(lines[a - 1:b])
                    m = __import__("re").search(r"# fs-ok: (\S.{4,})", span)
                    if not m:
                        bad.append("%s:%d %s" % (os.path.relpath(p, ENGINE), a, why))
        self.assertEqual(bad, [], "write-capable calls without fsafe or a `# fs-ok: <reason>`")

    def test_lint_sees_what_the_regex_missed(self):
        src = ("import os, shutil, subprocess, tarfile\n"
               "open(os.path.join(a, b), 'w')\n"            # the K3r7 (b) regex miss
               "os.remove(x)\nshutil.rmtree(y)\nos.makedirs(z)\nos.chmod(z, 0)\nos.link(a, b)\n"
               "tarfile.open(t).extractall(d)\nsubprocess.run(['tar', '-x'])\nopen(p).read()\n")
        kinds = [w for _a, _b, w in raw_writes(src)]
        self.assertEqual(kinds, ["open", "os.remove", "shutil.rmtree", "os.makedirs", "os.chmod", "os.link",
                                 "extractall", "subprocess tar"])

    def test_read_nofollow(self):
        d = tmpdir(self)
        with open(os.path.join(d, "f"), "w") as fh:
            fh.write("x")
        os.symlink(os.path.join(d, "f"), os.path.join(d, "l"))
        self.assertEqual(FS.read_nofollow(os.path.join(d, "f"))[0], b"x")
        with self.assertRaises(FS.UnsafePath):
            FS.read_nofollow(os.path.join(d, "l"))
        with self.assertRaises(FS.UnsafePath):
            FS.read_nofollow(os.path.join(d, "f"), max_bytes=0)


class JudgeSpecs(unittest.TestCase):
    def test_k4_schemas_valid_and_specs_built(self):
        for g in ("KICKOFF", "STAKES", "AN-PO", "DE-ARB", "SPLIT", "INTEGRATE", "HANDOFF"):
            SCH.check_schema(JG.schema(g))
            sp = JG.spec(None, g, [("x", "y")], "analyze", "A1", cwd="/tmp" if g == "INTEGRATE" else None)
            self.assertTrue(sp.system_parts[-1].startswith("# "))
        k = JG.spec(None, "KICKOFF", [("issue", "x")], "analyze", "A3")
        self.assertEqual((k.model, k.budget_usd, k.cap_chars, k.effort, k.tools), ("opus", 2.0, 40000, "high", ""))
        self.assertEqual(k.no_elide, {"issue", "comments"})
        self.assertEqual(JG.spec(None, "INTEGRATE", [], "children", "2c", cwd="/r").tools, "Read,Grep,Glob")

    def test_coercions(self):
        self.assertEqual(JG.coerce_stakes({"level": "low"})[0]["level"], "high")
        self.assertEqual(JG.coerce_stakes({"level": "medium", "local_reversible_reason": "x"})[1], None)
        self.assertEqual(JG.coerce_de_arb({"action": "reinvoke", "role": "tech-lead"})[0]["action"], "pause")
        self.assertEqual(JG.coerce_de_arb({"action": "escalate", "reason": "other"})[0]["action"], "pause")
        self.assertEqual(JG.coerce_split({"decision": "split", "slices": [{}]})[0]["decision"], "unsure")
        self.assertEqual(JG.coerce_handoff({"verdict": "ok_with_assumption"})[0]["verdict"], "upstream_gap")
        self.assertFalse(JG.coerce_handoff({"verdict": "upstream_gap", "fixable_by_execute": True})[0]["fixable_by_execute"])
        self.assertEqual(JG.coerce_an_po({"action": "rerate_success", "rating": "partial"})[0]["rating"], "unclear")
        self.assertTrue(JG.coerce_integrate({"verdict": "gap", "gaps": []})[0]["gaps"][0]["needs_decision"])

    def test_prompt_templates_exist_and_specialists_share_one(self):
        from workflows.dev.stages.base import RoleCall
        for role, task in (("explorer", "kickoff"), ("product-owner", "analyze"), ("tech-lead", "design"),
                           ("tester", "cases"), ("tech-lead", "integration")):
            self.assertIn("#7", PO.prompt(RoleCall(role, task, "s", "x"), 7))
        t = PO.prompt(RoleCall("designer", "design", "design", "E1.5"), 7)
        self.assertIn("out/ux.md", t)
        self.assertIn("out/i18n.md", PO.prompt(RoleCall("i18n", "design", "design", "E1.5"), 7))


if __name__ == "__main__":
    unittest.main()
