"""K3 — the auditor tripwire (D-M1–D-M7, D-A1) and the refactor Safety net (D-R1–D-R9, P0.R2, the §5.1
refactor-net scope fixture R7C-M1) on real temp git repos."""

import json
import os
import unittest

import _util  # noqa: F401
from _k1 import FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir

from guildcore.roles import runner as RR

DONE = ">>> RESULT <<<\nDONE: ok"
from workflows.dev import tripwire as TW
from workflows.dev.variants import refactor_net as RN


def w(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(text)


class Tripwire(unittest.TestCase):
    def setUp(self):
        self.r = repo(self, {"lib/a.dart": "int a() => 1;\n"})
        git(self.r, "switch", "-q", "-c", "feat")
        w(self.r, "lib/a.dart", "int a() => 2;\n")
        w(self.r, "lib/new.dart", "int n() => 0;\n")
        self.mb = git(self.r, "merge-base", "main", "HEAD")

    def before(self):
        return TW.readings(self.r, self.mb)

    def test_clean(self):
        b = self.before()
        self.assertEqual(TW.compare(b, TW.readings(self.r, self.mb))["verdict"], "clean")

    def test_staged_untracked_is_benign_dm3(self):
        b = self.before()
        git(self.r, "add", "lib/new.dart")
        self.assertEqual(TW.compare(b, TW.readings(self.r, self.mb))["verdict"], "benign")

    def test_deleted_untracked_is_mutation_dm4(self):
        b = self.before()
        os.remove(os.path.join(self.r, "lib/new.dart"))
        c = TW.compare(b, TW.readings(self.r, self.mb))
        self.assertEqual((c["verdict"], c["paths"]), ("mutation", ["lib/new.dart"]))

    def test_content_change_needs_attribution_dm5(self):
        b = self.before()
        w(self.r, "lib/a.dart", "int a() => 3; // auditor\n")
        self.assertEqual(TW.compare(b, TW.readings(self.r, self.mb))["verdict"], "attribute")

    def test_whitespace_only_is_formatter(self):
        b = self.before()
        w(self.r, "lib/a.dart", "int a()  =>  2;\n\n")
        c = TW.compare(b, TW.readings(self.r, self.mb))
        self.assertEqual((c["verdict"], c["formatter"]), ("formatter", ["lib/a.dart"]))

    def test_cache_artifact(self):
        b = self.before()
        w(self.r, "__pycache__/x.pyc", "x")
        self.assertEqual(TW.compare(b, TW.readings(self.r, self.mb))["verdict"], "artifact")

    def test_missing_before_file_is_mutation_dm7(self):
        p = os.path.join(tmpdir(self), "mutation-before.json")
        self.assertIsNone(TW.load(p))
        self.assertEqual(TW.compare(TW.load(p), TW.readings(self.r, self.mb))["verdict"], "mutation")

    def test_saved_before_roundtrip_and_gate_findings_ignored(self):
        p = os.path.join(tmpdir(self), "b.json")
        TW.save(p, self.before())
        w(self.r, ".claude/guild/gates/findings.json", "{}")
        self.assertEqual(TW.compare(TW.load(p), TW.readings(self.r, self.mb))["verdict"], "clean")

    def test_remainder_discounts_other_specs(self):
        w(self.r, "docs/specs/9/notes.md", "x")
        w(self.r, "docs/specs/7/extra.md", "x")
        keep, disc, unclear = TW.audited_remainder(self.before(), 7)
        self.assertIn("docs/specs/9/notes.md", disc)
        self.assertIn("docs/specs/7/extra.md", keep)
        self.assertEqual(unclear, ["docs/specs/7/extra.md"])

    def test_violation_note_is_not_self_resolving(self):
        from guildcore.records import audit as AU
        b = self.before()
        os.remove(os.path.join(self.r, "lib/new.dart"))
        a = TW.readings(self.r, self.mb)
        body = TW.violation_note(7, b, a, TW.compare(b, a), b["head"])
        self.assertFalse(AU.Violation(body).resolved)
        self.assertTrue(AU.Violation(body + "\n" + AU.RESOLVED_LINE).resolved)


class ModuleOnly(unittest.TestCase):
    def test_import_path_only(self):
        d = "@@ -1 +1 @@\n-import { x } from '../old/x';\n+import { x } from '../new/x';\n"
        self.assertTrue(RN.module_only(d))
        self.assertTrue(RN.module_only("@@ -1 +1 @@\n-import 'package:app/a.dart';\n+import 'package:app/b/a.dart';\n"))
        self.assertTrue(RN.module_only("@@ -3 +3 @@\n-} from './a';\n+} from './b/a';\n"))
        self.assertTrue(RN.module_only("@@ -1 +1 @@\n-jest.mock('./a');\n+jest.mock('./b/a');\n"))

    def test_assertion_change_is_not(self):
        self.assertFalse(RN.module_only("@@ -5 +5 @@\n-expect(x).toBe(1);\n+expect(x).toBe(2);\n"))
        self.assertFalse(RN.module_only("@@ -1 +1,2 @@\n-import a from './a';\n+import a from './b';\n+import c from './c';\n"))

    def test_mode(self):
        self.assertEqual(RN.mode("x <!-- guild:safety-net-only --> y"), "only")
        self.assertEqual(RN.mode("<!-- guild:safety-net -->"), "with-refactor")
        self.assertEqual(RN.mode("plain"), "none")


class Net(unittest.TestCase):
    """main: lib/a.js; branch refactor: net commit (test/a.net.test.js) → transform commit."""

    def setUp(self):
        self.r = repo(self, {"lib/a.js": "module.exports = () => 1;\n"})
        git(self.r, "switch", "-q", "-c", "refactor/#7-x")
        w(self.r, "test/a.net.test.js", "const a = require('../lib/a');\ntest('a', () => expect(a()).toBe(1));\n")
        git(self.r, "add", "-A")
        git(self.r, "commit", "-qm", "net")
        self.sha = git(self.r, "rev-parse", "HEAD")
        w(self.r, "lib/a.js", "const one = 1;\nmodule.exports = () => one;\n")
        git(self.r, "commit", "-qam", "transform")
        self.block = {"verified": "no", "sha": self.sha, "run": ["PASS test/a.net.test.js"],
                      "net": ["test/a.net.test.js"], "deferred": [], "post-transform-net": [], "leftover": []}

    def test_holds(self):
        self.assertEqual(RN.checks(self.r, "main", "refactor/#7-x", self.block), [])

    def test_render_parse_roundtrip(self):
        txt = RN.render_block(self.block)
        self.assertEqual(RN.parse_block(txt)["net"], ["test/a.net.test.js"])
        self.assertEqual(RN.parse_block(txt)["sha"], self.sha)

    def test_dr1_run_must_name_every_net_file(self):
        b = dict(self.block, run=["PASS something else"])
        self.assertTrue(any("does not show net file" in x for x in RN.checks(self.r, "main", "refactor/#7-x", b)))

    def test_dr2_production_change_in_proof(self):
        git(self.r, "switch", "-q", "--detach", "main")
        w(self.r, "lib/a.js", "module.exports = () => 2;\n")
        w(self.r, "test/a.net.test.js", "x")
        git(self.r, "add", "-A")
        tree = git(self.r, "write-tree")
        git(self.r, "reset", "-q", "--hard")
        git(self.r, "switch", "-q", "refactor/#7-x")
        b = dict(self.block, sha=tree)
        self.assertTrue(any("production change: lib/a.js" in x for x in RN.checks(self.r, "main", "refactor/#7-x", b)))

    def test_dr3_net_assertion_edit_unpins(self):
        w(self.r, "test/a.net.test.js", "const a = require('../lib/a');\ntest('a', () => expect(a()).toBe(2));\n")
        git(self.r, "commit", "-qam", "edit net")
        self.assertTrue(any("beyond module paths" in x for x in RN.checks(self.r, "main", "refactor/#7-x", self.block)))

    def test_dr3_module_path_edit_is_fine(self):
        os.makedirs(os.path.join(self.r, "lib/core"))
        git(self.r, "mv", "lib/a.js", "lib/core/a.js")
        w(self.r, "test/a.net.test.js", "const a = require('../lib/core/a');\ntest('a', () => expect(a()).toBe(1));\n")
        git(self.r, "commit", "-qam", "move")
        self.assertEqual(RN.checks(self.r, "main", "refactor/#7-x", self.block), [])

    def test_dr3_net_deleted(self):
        git(self.r, "rm", "-q", "test/a.net.test.js")
        git(self.r, "commit", "-qm", "rm net")
        self.assertIn("net file deleted: test/a.net.test.js", RN.checks(self.r, "main", "refactor/#7-x", self.block))

    def test_dr6_gone_tree(self):
        b = dict(self.block, sha="1" * 40)
        self.assertTrue(RN.checks(self.r, "main", "refactor/#7-x", b)[0].startswith("proof tree"))

    def test_dr7_only_mode_production_file(self):
        self.assertTrue(any("safety-net-only" in x for x in RN.checks(self.r, "main", "refactor/#7-x", self.block,
                                                                         net_mode="only")))

    # ---- P0.R2 (D-R9) ----
    def test_residue_on_branch_staged(self):
        w(self.r, "test/b.net.test.js", "x")
        git(self.r, "add", "test/b.net.test.js")
        self.assertEqual(RN.residue(self.r, "refactor/#7-x", "main").state, "staged-on-branch")

    def test_residue_other_branch(self):
        git(self.r, "switch", "-q", "main")
        r = RN.residue(self.r, "refactor/#7-x", "main")
        self.assertEqual((r.state, r.detail), ("other-branch", "main"))

    def proof(self):
        git(self.r, "switch", "-q", "--detach", "main")
        git(self.r, "checkout", "refactor/#7-x", "--", "test/a.net.test.js")

    def test_residue_proof_copies_cleanup(self):
        self.proof()
        r = RN.residue(self.r, "refactor/#7-x", "main")
        self.assertEqual((r.state, r.copies), ("proof-copies", [("A", "test/a.net.test.js")]))
        self.assertIsNone(RN.cleanup(self.r, "refactor/#7-x", r))
        self.assertEqual(git(self.r, "symbolic-ref", "HEAD"), "refs/heads/refactor/#7-x")
        self.assertEqual(git(self.r, "status", "--porcelain"), "")

    def test_residue_not_proof(self):
        self.proof()
        w(self.r, "lib/a.js", "module.exports = () => 99;\n")
        git(self.r, "add", "lib/a.js")
        self.assertEqual(RN.residue(self.r, "refactor/#7-x", "main").state, "not-proof")

    def test_residue_detached_not_ancestor(self):
        git(self.r, "switch", "-q", "--detach", "HEAD")
        w(self.r, "lib/x.js", "x")
        git(self.r, "add", "lib/x.js")
        r = RN.residue(self.r, "refactor/#7-x", "main")
        self.assertEqual(r.state, "not-proof")


class NetScopeFixture(unittest.TestCase):
    """§5.1 R7C-M1: developer → P0.R2 cleanup FIRST, then the scope check. Detached + proof copies →
    no violation; detached + non-proof staged → BRANCH (P0.R2 needs-human), not a scope defect."""

    def setUp(self):
        self.wt = repo(self, {"lib/a.js": "module.exports = () => 1;\n"})
        git(self.wt, "switch", "-q", "-c", "refactor/#7-x")
        w(self.wt, "test/a.net.test.js", "test('a', () => {});\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-qm", "net")
        self.root = os.path.join(tmpdir(self), "runs")
        self.cd = tmpdir(self)
        self.user = os.path.join(tmpdir(self), "settings.json")
        with open(self.user, "w") as fh:
            json.dump({}, fh)

    def run_dev(self, act):
        spawn = FakeSpawn([{"stream": stream_lines(texts=[DONE]), "check": act}])
        r = RR.Runner(journal=RecJournal(), common_dir=self.cd, parent_env={"PATH": os.environ["PATH"], "TMPDIR": "/tmp"},
                      spawn=spawn, user_settings=self.user, run_root_dir=self.root, claude="claude")
        spec = RR.RoleSpec("developer", "refactor", "Do it.", 7, "execute", "X1", self.wt, "sonnet", base="main",
                           branch="refactor/#7-x", remote_check=False,
                           pre_check=lambda wt: _post(wt))
        return r.run_role(spec)

    def test_proof_copies_cleaned_then_no_violation(self):
        def act(argv, env, cwd, stdin):
            git(cwd, "switch", "-q", "--detach", "main")
            git(cwd, "checkout", "refactor/#7-x", "--", "test/a.net.test.js")
        res = self.run_dev(act)
        self.assertEqual(res.status, "DONE")
        self.assertEqual(git(self.wt, "symbolic-ref", "HEAD"), "refs/heads/refactor/#7-x")

    def test_non_proof_staged_is_branch_not_scope(self):
        def act(argv, env, cwd, stdin):
            git(cwd, "switch", "-q", "--detach", "main")
            w(cwd, "lib/a.js", "module.exports = () => 5;\n")
            git(cwd, "add", "lib/a.js")
        res = self.run_dev(act)
        self.assertEqual(res.status, "BRANCH")
        self.assertIn("not proof copies", res.line)
        self.assertEqual(res.violations, [])


def _post(wt):
    r = RN.residue(wt, "refactor/#7-x", "main")
    if r.state == "not-proof":
        return "left on a detached checkout with staged changes that are not proof copies"
    if r.state in ("proof-copies", "detached-clean"):
        return RN.cleanup(wt, "refactor/#7-x", r)
    return None


if __name__ == "__main__":
    unittest.main()
