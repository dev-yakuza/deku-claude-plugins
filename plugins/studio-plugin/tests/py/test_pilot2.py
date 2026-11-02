"""Pilot 2 fixes (0.0.25), the parts outside the guard: P9 — `check_claims.py <video> --source [--fill]` prints and
fills the claim ids of work/source.md; P13 — `--skeleton` (re)writes the verify draft and keeps what the fact-checker
filled; P10 — `setup.py doc s2v-syntax` prints s2v's script syntax behind a fence; P12 · P19 · P21 · N1 · N6 · N12 and
the wording of P14/P15 (the next tool call, the Read/Write line, the "This is not a stop" exception).
The guard's own 0.0.25 changes are tested in test_pilot2_guard.py. No s2v process starts here: Providers are stubs."""

import contextlib
import copy
import glob
import io
import json
import os
import re
import stat
from unittest import mock

import helpers
import state_fixtures as F
from approve_base import ApproveCase
from helpers import StudioTestCase
from stdo import machine
from stdo.claims import check as ccheck, cli as ccli, linkrule, sourcemd
from stdo.setup import doc
from stdo.state import gates
from stdo.state.collect import Providers
import test_pilot1b

SETUP = test_pilot1b.SETUP

SKILL = helpers.SKILL
COMMANDS = os.path.join(SKILL, "commands")
AGENTS = os.path.join(SKILL, "templates", "agents")


def flat(text):
    return " ".join(text.split())


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


class ClaimsCase(StudioTestCase):
    """A harness repository with a video past the brief (state_fixtures), no s2v process."""

    def setUp(self):
        super().setUp()
        from stdo.state import store
        store.enable_writes()
        self.repo = helpers.make_repo(self.tmp)
        self.vdir = os.path.join(self.repo, "studio", "videos", "v1")
        os.makedirs(self.vdir)
        store.create(self.vdir, F.state(outputs=("youtube",), platforms={"youtube": ["youtube"]}))
        F.brief_ready(self.repo, self.vdir)
        self.src = sourcemd.path(self.vdir)

    def run_cli(self, *argv, providers=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ccli.main(list(argv), providers=providers, cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code


# ---------------------------------------------------------------- P9: --source [--fill]

E1, E2, E3 = F.EXCERPTS[0], F.EXCERPTS[1], "Dogs bark at night."


class SourceIds(ClaimsCase):
    def write_source(self, body):
        with open(self.src, "w", encoding="utf-8") as f:
            f.write("# Source\n\n## Claims\n" + body + "\n## Ruby pairs\n")

    def three(self):
        self.write_source("- C-00000000: the cat\n  > %s\n- C-1234abcd: warm\n  > %s\n- %s: dogs\n  > %s\n"
                          % (E1, E2, F.claim_id(E3), E3))

    def snapshot(self):
        st = os.stat(self.src)
        return read(self.src), st.st_mtime_ns, st.st_ino

    def test_states_and_exit_1(self):
        self.three()
        before = self.snapshot()
        self.assertEqual(self.run_cli("v1", "--source"), 1, self.out + self.err)
        lines = self.out.splitlines()
        self.assertIn("line 4  %s  placeholder" % F.claim_id(E1), lines)
        self.assertIn("line 6  %s  was C-1234abcd" % F.claim_id(E2), lines)
        self.assertIn("line 8  %s  ok" % F.claim_id(E3), lines)
        self.assertIn("--source --fill", self.out)
        self.assertEqual(self.snapshot(), before)  # without --fill nothing is written

    def test_fill_then_pass(self):
        self.three()
        self.assertEqual(self.run_cli("v1", "--source", "--fill"), 0, self.out + self.err)
        self.assertIn("line 4  %s  placeholder" % F.claim_id(E1), self.out)  # the same lines
        claims, problems = sourcemd.parse(read(self.src))
        self.assertEqual(problems, [])
        self.assertEqual(sorted(claims), sorted(F.claim_id(e) for e in (E1, E2, E3)))
        self.assertIn("## Ruby pairs", read(self.src))  # the rest of the file is kept
        self.assertEqual(self.run_cli("v1", "--source"), 0, self.out)
        self.assertEqual(self.out.count("  ok"), 3)

    def test_missing_excerpt_and_duplicates(self):
        self.write_source("- C-00000000: no quote\n\n- %s: one\n  > %s\n- %s: two\n  > %s\n"
                          % (F.claim_id(E1), E1, F.claim_id(E1), E1))
        self.assertEqual(self.run_cli("v1", "--source", "--fill"), 1)
        self.assertIn("line 4  C-00000000  no excerpt", self.out)
        self.assertIn("listed twice", self.out)
        self.assertIn("make the excerpts differ", self.out)

    def test_placeholders_are_not_duplicates(self):
        self.write_source("- C-00000000: one\n  > %s\n- C-00000000: two\n  > %s\n" % (E1, E2))
        self.assertEqual(self.run_cli("v1", "--source"), 1)  # placeholders are problems, not duplicates
        self.assertNotIn("listed twice", self.out)
        self.assertEqual(self.run_cli("v1", "--source", "--fill"), 0, self.out)
        # identical excerpts behind two placeholders give one id twice
        self.write_source("- C-00000000: one\n  > %s\n- C-00000000: two\n  > %s\n" % (E1, E1))
        self.assertEqual(self.run_cli("v1", "--source", "--fill"), 1)
        self.assertIn("listed twice", self.out)

    def test_mistyped_ids_are_reported(self):
        for bad in ("C-0000000", "C-0000000X", "C-ABCDEF12", "C-123456789", "C-"):
            self.write_source("- %s: the cat\n  > %s\n- %s: warm\n  > %s\n" % (bad, E1, F.claim_id(E2), E2))
            for fill in ((), ("--fill",)):
                before = self.snapshot()
                self.assertEqual(self.run_cli("v1", "--source", *fill), 1, (bad, fill, self.out))
                self.assertIn("line 4  not a claim line", self.out, bad)
                self.assertIn("line 6  %s  ok" % F.claim_id(E2), self.out)
                self.assertEqual(self.snapshot()[0], before[0])  # nothing to fix: the file stays as it is
        self.write_source("* C-00000000 the cat\n  > %s\n" % E1)  # no colon
        self.assertEqual(self.run_cli("v1", "--source", "--fill"), 1)
        self.assertIn("not a claim line", self.out)

    def test_only_the_claims_section_is_checked(self):
        with open(self.src, "w", encoding="utf-8") as f:
            f.write("# Source\n\n## Claims\n- %s: warm\n  > %s\n\n## Ruby pairs\n- C-언어 → 씨 언어\n\n## Notes\n"
                    "- C-0000000X is not a claim here\n" % (F.claim_id(E2), E2))
        self.assertEqual(self.run_cli("v1", "--source"), 0, self.out)
        self.assertNotIn("not a claim line", self.out)
        with open(self.src, "w", encoding="utf-8") as f:
            f.write("# Source\n\n## Claims\n- C-0000000X: cat\n  > %s\n- %s: warm\n  > %s\n\n## Ruby pairs\n"
                    "- C-언어 → 씨 언어\n" % (E1, F.claim_id(E2), E2))
        self.assertEqual(self.run_cli("v1", "--source", "--fill"), 1)
        self.assertIn("line 4  not a claim line", self.out)
        self.assertEqual(self.out.count("not a claim line"), 1)

    def test_needs_no_script_and_no_s2v(self):
        os.remove(machine.path(self.repo))
        self.assertFalse(os.path.exists(os.path.join(self.vdir, "script.ko.md")))
        self.three()
        self.assertEqual(self.run_cli("v1", "--source", "--fill"), 0, self.out + self.err)
        # the other modes still need them
        self.assertEqual(self.run_cli("v1", "--skeleton"), 2)

    def test_flags_exclude_each_other(self):
        self.three()
        before = self.snapshot()
        for argv in (("--source", "--skeleton"), ("--source", "--narration"), ("--skeleton", "--narration"),
                     ("--fill",), ("--skeleton", "--fill"), ("--narration", "--fill")):
            self.assertEqual(self.run_cli("v1", *argv), 2, argv)
            self.assertIn("check_claims.py <video>", self.err)
        self.assertEqual(self.snapshot(), before)

    def test_usage_text(self):
        self.assertIn("--source [--fill]", ccli.USAGE)
        self.assertIn("--skeleton", ccli.__doc__)
        self.assertIn("--source [--fill]", ccli.__doc__)


# ---------------------------------------------------------------- P13: --skeleton

S1, S2, S3 = "The cat sat on the mat.", "It was warm.", "Then it slept."


class Skeleton(ClaimsCase):
    def setUp(self):
        super().setUp()
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write("# a script exists\n")
        self.w = os.path.join(self.vdir, "work", "ko")
        os.makedirs(self.w, exist_ok=True)
        self.cm = {"claims": {F.C1: {"excerpt": E1, "sentences": [S1, "Cat"]}},
                   "excerpts": [E1, E2], "copy_excerpts": {}}
        with open(os.path.join(self.w, "claims-map.json"), "w") as f:
            json.dump(self.cm, f)
        self.sentences = [{"id": "s:0:0", "text": S1}, {"id": "s:0:1", "text": S2}]
        self.screen = [{"text": "Cat"}, {"text": S1 + " "}]  # the second is the first sentence again
        # titles: a plain heading (not judged), a number, a term of the excerpts, a title equal to a sentence
        self.titles = ["Intro", "3 steps", "Warm days", S2]
        self.calls = []

        def inspect(ctx):
            self.calls.append("inspect")
            return {"screen_text": copy.deepcopy(self.screen), "scenes": [{"title": t} for t in self.titles]}

        def sentences(ctx):
            self.calls.append("sentences")
            return copy.deepcopy(self.sentences)

        def no_process(*a, **kw):
            raise AssertionError("an s2v process would start")
        self.providers = Providers(inspect=inspect, sentences=sentences, source=no_process, inspect_at=no_process,
                                   version=no_process, services=no_process)
        self.draft_path = os.path.join(self.w, "verify.draft.json")

    def skeleton(self):
        code = self.run_cli("v1", "--skeleton", providers=self.providers)
        self.assertEqual(code, 0, self.out + self.err)
        with open(self.draft_path, encoding="utf-8") as f:
            raw = f.read()
        return json.loads(raw), raw

    def problems(self, draft):
        return ccheck.draft_problems(draft, self.cm, None, self.sentences, self.screen, self.titles)

    def test_first_run(self):
        draft, raw = self.skeleton()
        texts = [s["text"] for s in draft["sentences"]]
        self.assertEqual(texts, [S1, S2, "Cat", "3 steps", "Warm days"])  # no duplicates, no title-only filler
        self.assertNotIn("Intro", texts)
        probs = self.problems(draft)
        self.assertTrue(probs)
        self.assertEqual([p for p in probs if "has no verdict" not in p], [])
        first = draft["sentences"][0]
        self.assertEqual(list(first), ["text", "kind", "claims", "excerpts", "verdict", "note"])  # text first, no sort
        self.assertEqual((first["kind"], first["claims"], first["excerpts"], first["verdict"], first["note"]),
                         ("fact", [F.C1], [E1], "", ""))
        self.assertEqual(draft["sentences"][1]["claims"], [])
        self.assertTrue(raw.lstrip().startswith('{\n  "sentences": [\n    {\n      "text"'), raw[:80])
        self.assertIn("kept 0 · added 5 · dropped 0", self.out)
        self.assertEqual(sorted(set(self.calls)), ["inspect", "sentences"])

    def test_merge_keeps_filled_entries(self):
        draft, _ = self.skeleton()
        filled = dict(draft["sentences"][0], verdict="supported", note="checked")
        link = dict(draft["sentences"][1], kind="link", claims=[], excerpts=[], note="a transition")
        draft["sentences"][0], draft["sentences"][1] = filled, link
        draft["sentences"].append({"text": "a hand-added stale line", "kind": "fact", "verdict": "supported"})
        with open(self.draft_path, "w", encoding="utf-8") as f:
            json.dump(draft, f)
        # the script changes: S2 goes, S3 comes
        self.sentences = [{"id": "s:0:0", "text": S1}, {"id": "s:0:1", "text": S3}]
        self.titles = ["Intro"]
        again, _ = self.skeleton()
        by = {s["text"]: s for s in again["sentences"]}
        self.assertEqual(by[S1], filled)  # unchanged
        self.assertEqual(by[S3]["verdict"], "")
        self.assertNotIn(S2, by)
        self.assertNotIn("a hand-added stale line", by)
        self.assertEqual([s["text"] for s in again["sentences"]], [S1, S3, "Cat"])
        self.assertIn("kept 2 · added 1 · dropped 4", self.out)
        self.assertIn("dropped (no longer in the script): a hand-added stale line", self.out)
        self.assertIn("dropped (no longer in the script): %s" % S2, self.out)

    def test_duplicates_in_the_old_draft_are_listed(self):
        draft, _ = self.skeleton()
        first = dict(draft["sentences"][0], verdict="supported")
        draft["sentences"] = [first, dict(first, note="the second copy"), dict(first, text=S1 + "  ")] + \
            draft["sentences"][1:]
        with open(self.draft_path, "w", encoding="utf-8") as f:
            json.dump(draft, f)
        again, _ = self.skeleton()
        self.assertEqual([s["text"] for s in again["sentences"]].count(S1), 1)
        self.assertEqual(again["sentences"][0], first)  # the first entry is kept
        self.assertIn("kept 5 · added 0 · dropped 2", self.out)
        self.assertEqual(self.out.count("dropped (no longer in the script): %s" % S1), 2)

    def test_claim_ids_once(self):
        self.cm["claims"][F.C1]["sentences"] = [S1, S1, "Cat"]
        self.cm["claims"][F.C2] = {"excerpt": E2, "sentences": [S1]}
        with open(os.path.join(self.w, "claims-map.json"), "w") as f:
            json.dump(self.cm, f)
        draft, _ = self.skeleton()
        ids = sorted([F.C1, F.C2])  # claims in id order, each once
        self.assertEqual(draft["sentences"][0]["claims"], ids)
        self.assertEqual(draft["sentences"][0]["excerpts"], [{F.C1: E1, F.C2: E2}[c] for c in ids])

    def test_needs_the_script_and_s2v(self):
        os.remove(machine.path(self.repo))
        self.assertEqual(self.run_cli("v1", "--skeleton", providers=self.providers), 2)
        self.assertFalse(os.path.exists(self.draft_path))
        self.assertEqual(self.calls, [])


# ---------------------------------------------------------------- P10: doc s2v-syntax

REF = "# write-script reference\n\n::title[...] and :::quote blocks.\n"


class S2vSyntax(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.tmp, "site")
        os.makedirs(os.path.join(self.repo, ".git"))
        os.makedirs(os.path.join(self.repo, "docs", "deep"))
        self.s2v = os.path.join(self.tmp, "s2v")
        self.ref_dir = os.path.join(self.s2v, ".claude", "skills", "write-script")
        os.makedirs(self.ref_dir)
        self.ref = os.path.join(self.ref_dir, "reference.md")
        with open(self.ref, "w", encoding="utf-8") as f:
            f.write(REF)
        machine.write(self.repo, self.s2v)

    def run_doc(self, cwd=None):
        out, err = io.StringIO(), io.StringIO()
        code = doc.main(["s2v-syntax"], script=SETUP, out=out, err=err, cwd=cwd or os.path.join(self.repo, "docs",
                                                                                                    "deep"))
        return code, out.getvalue(), err.getvalue()

    def assertRefused(self):
        code, out, _err = self.run_doc()
        self.assertEqual((code, out), (2, ""))

    def test_prints_the_file(self):
        code, out, err = self.run_doc()
        self.assertEqual(code, 0, err)
        self.assertTrue(out.endswith(REF))
        self.assertTrue(out.startswith("# s2v script syntax"))
        self.assertNotIn(self.s2v, out.splitlines()[0])

    def test_git_file_marks_a_worktree(self):
        wt = os.path.join(self.tmp, "wt")
        os.makedirs(wt)
        with open(os.path.join(wt, ".git"), "w") as f:
            f.write("gitdir: /elsewhere\n")
        machine.write(wt, self.s2v)
        self.assertEqual(self.run_doc(cwd=wt)[0], 0)

    def test_link_at_the_reference(self):
        real = os.path.join(self.ref_dir, "real.md")
        os.rename(self.ref, real)
        os.symlink(real, self.ref)  # even a link inside s2v
        self.assertRefused()

    def test_fifo(self):
        os.remove(self.ref)
        os.mkfifo(self.ref)
        self.assertRefused()

    def test_too_long(self):
        with open(self.ref, "w", encoding="utf-8") as f:
            f.write("가" * (doc.MAX_CHARS + 1))
        self.assertRefused()
        with open(self.ref, "w", encoding="utf-8") as f:
            f.write("가" * doc.MAX_CHARS)
        self.assertEqual(self.run_doc()[0], 0)

    def test_outside_the_s2v_folder(self):
        outside = os.path.join(self.tmp, "outside", "write-script")
        os.makedirs(outside)
        with open(os.path.join(outside, "reference.md"), "w") as f:
            f.write(REF)
        os.remove(self.ref)
        os.rmdir(self.ref_dir)
        os.symlink(outside, self.ref_dir)  # a folder of the path leads out of s2v
        self.assertRefused()

    def test_no_machine_json(self):
        os.remove(machine.path(self.repo))
        code, out, err = self.run_doc()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no s2v path: run /std init or /std config", err)
        nogit = os.path.join(self.tmp, "nogit")
        os.makedirs(nogit)
        code, out, err = self.run_doc(cwd=nogit)
        self.assertEqual((code, out), (2, ""))

    def test_name_is_listed_and_known(self):
        self.assertIn("s2v-syntax", doc.NAMES)
        self.assertNotIn("s2v-syntax", doc.names())
        out = io.StringIO()
        self.assertEqual(doc.main([], script=SETUP, out=out), 0)
        self.assertIn("- s2v-syntax — s2v script syntax", out.getvalue())

    def test_no_process_and_lazy_machine(self):
        src = read(doc.__file__)
        self.assertNotIn("subprocess", src)
        head = src.split("def s2v_syntax", 1)[0]
        self.assertNotIn("machine", re.sub(r'""".*?"""', "", head, flags=re.S).replace("this machine", ""))


class S2vSyntaxGuard(test_pilot1b.DocsGuard):
    def test_allowed_with_and_without_a_harness(self):
        for cwd in self.folders:
            for cmd in ("python3 %s doc s2v-syntax" % SETUP, 'python3 "%s" doc s2v-syntax' % SETUP):
                self.assertDocAllow(cmd, cwd)
        self.assertFalse(self.pending())


for _name in [n for n in dir(test_pilot1b.DocsGuard) if n.startswith("test_")]:  # run only this class's own test (P6 is pilot1b's)
    if _name not in S2vSyntaxGuard.__dict__:
        setattr(S2vSyntaxGuard, _name, None)


class S2vSyntaxText(StudioTestCase):
    def test_templates_name_the_doc_command_only(self):
        for n in ("std-writer.md", "std-visual-director.md"):
            t = flat(read(AGENTS, n))
            self.assertIn("run `<the doc command the producer gives you>` for the s2v syntax; if none was given, "
                          "stop and say so", t, n)
            self.assertNotIn("reference.md", t, n)
            self.assertNotIn("write-script", t, n)
            self.assertNotIn("config get", t, n)
        for d in ("script", "board"):
            t = flat(read(COMMANDS, d + ".md"))
            step2 = t.split("2. ", 1)[1].split(" 3. ", 1)[0]
            self.assertIn('`python3 "<<SKILL_DIR>>/scripts/setup.py" doc s2v-syntax`', step2, d)
            self.assertIn("spawn prompt", step2, d)


# ---------------------------------------------------------------- P9 · P13 · P12 · P19 text

class ClaimsText(StudioTestCase):
    def test_p9_analyst_writes_the_placeholder(self):
        t = flat(read(AGENTS, "std-source-analyst.md"))
        self.assertIn("`- C-00000000: <claim in one sentence>`", t)
        self.assertNotIn("first 8 hex", t)
        src = flat(read(COMMANDS, "source.md"))
        self.assertIn("3b. `python3 .claude/studio/scripts/check_claims.py <video> --source --fill`", src)

    def test_p13_skeleton_then_fact_checker(self):
        v = flat(read(COMMANDS, "verify.md"))
        step2 = v.split(" 2. ", 1)[1].split(" 3. ", 1)[0]
        self.assertLess(step2.find("--skeleton"), step2.find("spawn the fact-checker"))
        self.assertIn("fills the draft with Edit", step2)
        self.assertIn("go back to step 2 (`--skeleton`, then the fact-checker)", v)
        fc = flat(read(AGENTS, "std-fact-checker.md"))
        self.assertIn("check_claims.py <video> --skeleton", fc)
        self.assertIn("Fill it in with Edit", fc)

    def test_p12_numbers_are_linkrule(self):
        self.assertEqual((linkrule.LINK_MAX, linkrule.LINK_SHARE), (2, 0.25))
        rule = "at most %d link sentences, or a quarter of the judged entries (rounded down) when that is more" \
            % linkrule.LINK_MAX
        self.assertIn(rule, flat(read(AGENTS, "std-fact-checker.md")))
        self.assertIn(rule, flat(read(COMMANDS, "verify.md")))
        # the code: max(LINK_MAX, floor(judged × LINK_SHARE))
        self.assertEqual(max(linkrule.LINK_MAX, int(13 * linkrule.LINK_SHARE)), 3)

    def test_p19_list_items_and_dropped_conditions(self):
        fc = flat(read(AGENTS, "std-fact-checker.md"))
        rule = ("Judge a list item together with its heading; a sentence that drops a condition or limit stated in its "
                "excerpt is `unsupported`.")
        self.assertEqual(fc.count(rule), 2)  # script verify and copy verify
        self.assertLess(fc.find(rule), fc.find("## The copy"))
        self.assertGreater(fc.rfind(rule), fc.find("## The copy"))


# ---------------------------------------------------------------- P21: the `read:` line of shown ②

class AuditionRead(ApproveCase):
    def to_two(self):
        self.pass_gate("1")
        md = os.path.join(self.repo, "studio", "out", "v1", "ko", "audition", "audition.md")
        os.makedirs(os.path.dirname(md))
        with open(md, "w") as f:
            f.write("# audition\n")
        for st in ("cast", "tts", "audition"):
            self.assertEqual(self.cli("stage-done", "v1", st), 0, self.last_err)
        return md

    def test_read_line_after_hash12(self):
        md = self.to_two()
        real = os.path.isfile
        with mock.patch.object(gates.os.path, "isfile", lambda p: False if p == md else real(p)):
            self.assertEqual(self.cli("shown", "v1", "2"), 0, self.last_err)
        without = self.last_out
        self.assertNotIn("read: ", without)
        self.assertEqual(self.cli("shown", "v1", "2"), 0, self.last_err)
        lines = self.last_out.splitlines()
        i = [n for n, l in enumerate(lines) if l.startswith("hash12 ")][0]
        self.assertEqual(lines[i + 1], "read: studio/out/v1/ko/audition/audition.md")
        self.assertEqual("\n".join(lines[:i + 1] + lines[i + 2:]) + "\n", without)  # block and hash unchanged

    def test_no_line_without_the_file(self):
        md = self.to_two()
        os.remove(md)
        self.assertEqual(self.cli("shown", "v1", "2"), 0, self.last_err)
        self.assertNotIn("read: ", self.last_out)

    def test_make_names_the_path(self):
        mk = flat(read(COMMANDS, "make.md"))
        gate2 = mk.split("## Gate ②", 1)[1].split("## ", 1)[0]
        self.assertIn("`studio/out/<video>/<lang>/audition/audition.md`", gate2)


# ---------------------------------------------------------------- N1 · N6 · N12 · P14 · P15 wording

NEXT_CALL = ("next tool call, in the same turn", "never in the same assistant message")
NOT_A_STOP = ("Exception: when the refusal itself says 'This is not a stop', do what it says — that is not reaching the "
              "same effect another way.")
READ_WRITE = ("Read files with Read and write your outputs (if any) with Write or Edit. Never use `python -c`, heredocs "
              "or generator scripts for file work: the guard refuses them. For ids, lists and skeletons use the Studio "
              "commands your stage names.")
# the misspellings the pilot showed (escaped so this file never carries them as text)
TYPOS = ("하니스", "발추", "챙터", "크레딘")
P15_PLACES = ("abandon", "verify", "make", "render", "copy", "board", "config", "update", "init", "resume")


class Wording(StudioTestCase):
    def mds(self):
        return [p for p in glob.glob(os.path.join(helpers.PLUGIN, "**", "*.md"), recursive=True)]

    def test_p15_next_tool_call(self):
        for d in P15_PLACES:
            t = flat(read(COMMANDS, d + ".md"))
            for s in NEXT_CALL:
                self.assertIn(s, t, d)
        st = flat(read(COMMANDS, "atoms", "_stages.md"))
        for s in NEXT_CALL:
            self.assertIn(s, st)
        self.assertEqual(flat(read(COMMANDS, "config.md")).count("next tool call, in the same turn"), 4)
        self.assertEqual(flat(read(COMMANDS, "make.md")).count("next tool call, in the same turn"), 3)
        for p in glob.glob(os.path.join(COMMANDS, "**", "*.md"), recursive=True):
            self.assertNotIn("in a later message", flat(read(p)), p)
            self.assertNotIn("later message", flat(read(p)), p)

    def test_p14_exception_everywhere(self):
        blocks = []
        for p in glob.glob(os.path.join(SKILL, "**", "*.md"), recursive=True):
            blocks += re.findall(r"<!-- studio:guard-refusal -->\n(.*?)\n<!-- /studio:guard-refusal -->", read(p), re.S)
        self.assertEqual(len(blocks), 16)
        self.assertEqual(len(set(blocks)), 1)
        self.assertIn(NOT_A_STOP, flat(blocks[0].replace(">", " ")))
        self.assertIn(NOT_A_STOP, flat(read(COMMANDS, "atoms", "_contract.md").replace("\n>", "\n")))
        self.assertIn(NOT_A_STOP, flat(read(COMMANDS, "atoms", "_invariants.md")))
        for p in glob.glob(os.path.join(AGENTS, "std-*.md")):
            t = flat(read(p))
            if p.endswith("std-auditor.md"):
                self.assertNotIn(READ_WRITE, t)  # the read-only auditor keeps its own rule
                continue
            self.assertIn(NOT_A_STOP, t, p)
            self.assertIn(READ_WRITE, t, p)

    def test_p14_read_write_in_contract_a(self):
        t = read(COMMANDS, "atoms", "_contract.md")
        a = flat(t.split("## A.", 1)[1].split("## B.", 1)[0])
        self.assertIn(READ_WRITE, a)

    def test_n1_one_free_text_line(self):
        t = flat(read(COMMANDS, "init.md"))
        self.assertIn('Never add an option that means "I\'ll type it"', t)
        self.assertIn("Only the first question says so", t)
        self.assertIn("the other questions do not repeat it", t)
        self.assertNotIn("Instead, the question text ends with one line", t)

    def test_n6_glossary_and_no_misspelling(self):
        t = flat(read(COMMANDS, "atoms", "_contract.md"))
        self.assertIn("하네스 (harness), 발췌 (excerpt), 챕터 (chapter), 크레딧 (credit)", t)
        bad = ["%s: %s" % (os.path.relpath(p, helpers.PLUGIN), w) for p in self.mds() for w in TYPOS if w in read(p)]
        self.assertEqual(bad, [])

    def test_n12_commit_names_both_folders(self):
        mk = read(COMMANDS, "make.md")
        sec = flat(mk.split("## The video's commit", 1)[1])
        self.assertIn("`studio/out/<video>/…`", sec)
        self.assertIn("`studio/copy/<video>/…`", sec)
        self.assertIn("never committed", sec)
        gi = read(SKILL, "templates", "studio", "gitignore.tmpl")
        self.assertIn("/{{STUDIO_ROOT}}/out/", gi)
        self.assertIn("/{{STUDIO_ROOT}}/copy/", gi)

    def test_versions(self):
        from stdo import SCRIPTS_VERSION
        self.assertGreaterEqual(int(SCRIPTS_VERSION), 23)  # 0.0.25's bump; test_pilot2b pins the current one
        with open(os.path.join(helpers.PLUGIN, ".claude-plugin", "plugin.json")) as f:
            v = json.load(f)["version"]
        self.assertGreaterEqual(tuple(int(x) for x in v.split(".")), (0, 0, 25))
        for n in ("README.md", "README.ko.md", "README.ja.md"):
            self.assertIn("0.0.25", read(helpers.PLUGIN, n), n)
        self.assertIn("0.0.25", read(helpers.PLUGIN, "tests", "README.md"))


if __name__ == "__main__":
    import unittest
    unittest.main()
