"""Auditor refresh scope, research-grounded dismissals and retiring stale signals
(design/herald/13-auditor-scope-and-signal-retire.md, 0.22.0): `refresh-scope`, the out-of-scope
quote check (whole sentence, unchanged paragraph, merge-base, one normalisation for quote and body,
both ruby readings), the counts and auto-publish reasons, the `out-of-scope-finding` context signal,
`refresh_candidates` (merge, adopt, prune), `grounds` and the `dismissal:grounded-unseen` axis,
`withdrawn:` blocks, `evolve-mark --retire/--unretire` and its lock binding, the guard, `v`/`legacy`.
A critique.json and signals without the new fields behave as in 0.21.0 (test_core runs on them)."""

import json
import os
import unittest

from helpers import ARTICLE, RepoCase, sh
from test_core import CRIT_PASS, write_machine
from test_ship_consent import guard_decision

from hrdlib import lock, scope, store

TID = "r-old-post-20261101"
SLUG = "old-post"
BODY = "src/content/blog/old-post.md"

RUBY = ("Visitors can read <ruby>空港<rt>くうこう</rt></ruby> signs at the [main gate](https://example.test/gate) "
        "without trouble. Entry is **free** for children under six.")
BASE = ARTICLE.format(slug=SLUG) + """
## Opening hours

The ticket office opens at nine in the morning on weekdays. Late entry ends at five.

%s

The fee was 1,000 yen in 2025. It covers the museum and the garden.

Parking is free for every visitor today. Shuttle buses run hourly from the station.

Parking is free for every visitor today. The lot fills early.

| Day | Hours |
|---|---|
| Mon | closed all day long |
""" % RUBY
CUR = BASE.replace("The fee was 1,000 yen in 2025.", "The fee is 1,200 yen in 2026.") \
          .replace("The lot fills early.", "The lot fills early in summer.")

RUBY_SENTENCE = "Visitors can read 空港くうこう signs at the main gate without trouble."


def out_entry(i="R1-1", quote=RUBY_SENTENCE, sev="MAJOR", rnd=1, **kw):
    e = {"round": rnd, "id": i, "severity": sev, "summary": "the gate sign reads oddly", "outcome": "out-of-scope",
         "scope": "out", "quote": quote}
    e.update(kw)
    return e


# --- the quote check (§R2-1, §R3-1, §R3-2) ---------------------------------------------------------

class QuoteTests(unittest.TestCase):
    def ok(self, quote, base=BASE, cur=CUR):
        return scope.quote_problem(base, cur, quote, "R1-1")

    def test_ruby_link_and_emphasis_sentences_pass(self):
        for q in (RUBY_SENTENCE,  # the reading as the body flattens it
                  "Visitors can read 空港 signs at the main gate without trouble.",  # as a reader sees the base
                  "Visitors can read <ruby>空港<rt>くうこう</rt></ruby> signs at the [main gate](https://x.test) "
                  "without trouble.",  # with markup: the same pipeline drops it
                  "Entry is free for children under six.", "Entry is **free** for children under six.",
                  "  The ticket office opens at nine in the morning\non weekdays.  "):
            self.assertIsNone(self.ok(q), q)

    def test_fragments_prefixes_and_changed_sentences_are_refused(self):
        self.assertIn("text this refresh wrote", self.ok("The ticket office opens at nine"))  # a fragment
        self.assertIn("text this refresh wrote", self.ok("The fee is 1,200 yen in 2026."))  # new text
        self.assertIn("changed after", self.ok("The fee was 1,000 yen in 2025."))  # gone from the body now
        base = "Shuttle buses run hourly from the station.\n"
        cur = "Since 2026, shuttle buses run hourly from the station.\n"
        self.assertIn("changed after", self.ok("Shuttle buses run hourly from the station.", base, cur))
        self.assertIn("text this refresh wrote", self.ok("Since 2026, shuttle buses run hourly from the station.",
                                                         base, cur))

    def test_a_paragraph_the_refresh_changed_refuses_its_other_sentences(self):
        self.assertIn("paragraph changed", self.ok("It covers the museum and the garden."))

    def test_a_repeated_sentence_needs_every_paragraph_unchanged(self):
        self.assertIn("paragraph changed", self.ok("Parking is free for every visitor today."))
        self.assertIsNone(self.ok("Parking is free for every visitor today.", BASE, BASE))

    def test_short_long_missing_and_unreadable(self):
        self.assertIn("too short", self.ok("Late entry."))
        self.assertIn("over 500", self.ok("x" * 501))
        self.assertIn("no quote", self.ok(""))
        self.assertIn("no quote", self.ok(None))
        self.assertIn("no merge-base", self.ok(RUBY_SENTENCE, base=None))
        self.assertIn("text this refresh wrote", self.ok("closed all day long"))  # a table cell is no sentence
        self.assertIn("text this refresh wrote", self.ok("Opening hours are listed"))

    def test_what_a_reader_sees_passes(self):
        """review 28 M1, m1, m2: inline code read as text, footnotes, reference links, entities,
        escapes, a missing final stop, and the three ruby readings — the same on both sides."""
        cases = [
            ("Run `npm install` before building the project today. Then go.\n",
             ["Run npm install before building the project today.", "Run `npm install` before building the project today."]),
            ("The station opened in 1998 after many years.[^1] Next one.\n\n[^1]: source\n",
             ["The station opened in 1998 after many years."]),
            ("See the [official guide][g] for the full timetable today. Next.\n\n[g]: https://x.test\n",
             ["See the official guide for the full timetable today."]),
            ("Tom &amp; Jerry visit the museum every summer holiday. Next.\n",
             ["Tom & Jerry visit the museum every summer holiday."]),
            ("Prices are 5\\* cheaper than last year in total. Next.\n", ["Prices are 5* cheaper than last year in total."]),
            ("이 글은 **서울**의 [지하철](https://x.test \"t\") 요금을 정리합니다. 다음.\n",
             ["이 글은 서울의 지하철 요금을 정리합니다", "이 글은 서울의 지하철 요금을 정리합니다."]),
            ("<ruby>空港<rp>（</rp><rt>くうこう</rt><rp>）</rp></ruby>までは**電車**で[30分](https://x.test)ほどかかります。次。\n",
             ["空港までは電車で30分ほどかかります。", "空港（くうこう）までは電車で30分ほどかかります。",
              "空港くうこうまでは電車で30分ほどかかります。"]),
        ]
        for body, quotes in cases:
            for q in quotes:
                self.assertIsNone(self.ok(q, body, body), q)

    def test_a_changed_reading_is_a_change(self):
        base = "<ruby>生<rt>なま</rt></ruby>ビールの値段は五百円でした、今年もそうです。\n"
        self.assertIn("paragraph changed", self.ok("生ビールの値段は五百円でした、今年もそうです。", base,
                                                   base.replace("なま", "せい")))
        code = "Run `npm install` before building the project today.\n"
        self.assertIn("changed after", self.ok("Run npm install before building the project today.", code,
                                               code.replace("npm install", "npm ci")))

    def test_hash_is_the_normalised_quote(self):
        self.assertEqual(scope.quote_hash("Entry is **free** for children under six."),
                         scope.quote_hash("Entry is free for  children under six."))
        self.assertEqual(len(scope.quote_hash("x")), 16)


# --- a refresh topic through critique (§1.3, §1.4, §R1-m1–m3, §R2-1) ---------------------------------

class RefreshCase(RepoCase):
    topic = {"id": TID, "title": "Old post", "state": "queued", "refresh_of": SLUG, "slug": SLUG,
             "angle": "refresh: update the fee", "history": [], "reverted_by": [],
             "refresh_decision": {"recommendation": "update", "decision": "update", "source": "recommended",
                                  "stale": ["the 2025 fee"]}}

    def setUp(self):
        super().setUp()
        self.write(BODY, BASE)
        self.write("public/blog-images/%s/01.png" % SLUG, b"\x89PNG fake", binary=True)
        store.save_topics(self.root, {"version": 1, "topics": [
            {"id": "t0001", "title": "Old", "state": "published", "slug": SLUG, "history": [], "reverted_by": []},
            json.loads(json.dumps(self.topic))]})
        store.save_published(self.root, {"version": 1, "releases": [], "articles": [
            {"slug": SLUG, "origin": "herald", "current_topic_id": "t0001", "published_at": "2026-01-01T00:00:00+00:00",
             "path": BODY, "url": "https://example.test/blog/old-post/"}]})
        self.commit("base")
        sh(self.root, "git", "push", "-q", "origin", "main")

    def to_critique(self, body=CUR):
        self.hrd("begin", "--topic", TID)
        self.write(".claude/herald/work/%s/brief.md" % TID, "brief")
        self.hrd("branch", "--topic", TID, "--slug", SLUG)
        self.hrd("stage", "pass", "--topic", TID, "--stage", "brief")
        self.write(".claude/herald/work/%s/research.md" % TID, "C1. source\n")
        self.hrd("stage", "pass", "--topic", TID, "--stage", "research")
        self.write(BODY, body)
        self.write(".claude/herald/work/%s/claims-map.json" % TID, "{}")
        self.hrd("stage", "pass", "--topic", TID, "--stage", "draft")
        self.write(".claude/herald/work/%s/critique.md" % TID, "ok")

    def crit(self, log, scope_hash=True, **fr):
        c = json.loads(json.dumps(CRIT_PASS))
        c["final_round"].update(fr)
        if scope_hash:
            c["final_round"]["scope_hash"] = self.hrd("refresh-scope", "--topic", TID)[0]["scope_hash"]
        c["audit_log"] = log
        write_machine(self, TID, "critique.json", c, SLUG)
        return self.hrd("stage", "pass", "--topic", TID, "--stage", "critique", check=False)[1]

    def signals(self):
        p = os.path.join(self.root, ".claude/herald/signals.jsonl")
        return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


class CritiqueTests(RefreshCase):
    def test_a_legit_out_of_scope_major_passes_round_one_and_is_context_only(self):
        self.to_critique()
        log = [out_entry(), out_entry("R1-2", "Entry is free for children under six.", sev="MINOR")]
        p = self.crit(log, audit={"major": 1, "minor": 1}, out_of_scope={"major": 1})
        self.assertEqual(p.returncode, 0, p.stderr)
        recs = [r for r in self.signals() if r["kind"] == "out-of-scope-finding"]
        self.assertEqual([r["data"]["id"] for r in recs], ["R1-1"])  # MAJOR only
        self.assertEqual(recs[0]["data"]["quote_hash"], scope.quote_hash(RUBY_SENTENCE))
        self.assertEqual(recs[0]["v"], json.load(open(os.path.join(
            os.path.dirname(__file__), "..", "..", ".claude-plugin", "plugin.json")))["version"])
        r = store.evolve_readiness(self.root, self.cfg)
        self.assertEqual((r["tier"], r["signals"], r["kinds"]), ("none", 0, {"out-of-scope-finding": 1}))
        store.record_out_of_scope(self.root, TID, store.load_machine(self.root, TID, "critique.json"))
        self.assertEqual(sum(r["kind"] == "out-of-scope-finding" for r in self.signals()), 1)  # once

    def test_refusals(self):
        self.to_critique()
        cases = [
            ([out_entry(sev="BLOCKER")], {"audit": {"blocker": 1}, "dismissed": {"blocker": 1}}, "never out of scope"),
            ([out_entry()], {"audit": {"major": 1}, "out_of_scope": {"major": 1}, "scope_hash": False}, "scope_hash"),
            ([], {"audit": {"major": 1}, "out_of_scope": {"major": 1}}, "lists 0 out-of-scope"),
            ([out_entry(tag="regression")], {"audit": {"major": 1}, "out_of_scope": {"major": 1}}, "regression"),
            ([out_entry(scope=None)], {"audit": {"major": 1}, "out_of_scope": {"major": 1}}, "goes with"),
            ([out_entry(quote="The fee is 1,200 yen in 2026.")], {"audit": {"major": 1}, "out_of_scope": {"major": 1}},
             "text this refresh wrote"),
            ([out_entry(quote="It covers the museum and the garden.")],
             {"audit": {"major": 1}, "out_of_scope": {"major": 1}}, "paragraph changed"),
            ([out_entry()], {"audit": {"major": 1}, "out_of_scope": {"major": True}}, "non-negative integer"),
        ]
        for log, fr, msg in cases:
            sh_ = fr.pop("scope_hash", True)
            p = self.crit(log, scope_hash=sh_, **fr)
            self.assertNotEqual(p.returncode, 0, msg)
            self.assertIn(msg, p.stderr)
        p = self.crit([out_entry(), out_entry("R1-2")], audit={"major": 2}, out_of_scope={"major": 2})
        self.assertIn("quote the same sentence", p.stderr)
        c = json.loads(json.dumps(CRIT_PASS))  # a made-up hash: not the scope audit-round recorded
        c["final_round"].update(audit={"major": 1}, out_of_scope={"major": 1}, scope_hash="sha256:" + "ab" * 32)
        c["audit_log"] = [out_entry()]
        write_machine(self, TID, "critique.json", c, SLUG)
        p = self.hrd("stage", "pass", "--topic", TID, "--stage", "critique", check=False)[1]
        self.assertIn("not the scope `HRD audit-round` recorded", p.stderr)
        p = self.crit([out_entry()], audit={"major": 1})  # not counted out: still an open MAJOR
        self.assertIn("does not record a PASS", p.stderr)

    def test_a_sentence_changed_between_rounds_is_caught_at_the_next_pass(self):
        self.to_critique()
        p = self.crit([out_entry()], audit={"major": 1}, out_of_scope={"major": 1})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.hrd("loopback", "--topic", TID, "--human")
        self.write(BODY, CUR.replace("without trouble.", "without any trouble."))
        self.hrd("stage", "pass", "--topic", TID, "--stage", "draft")
        p = self.crit([out_entry()], audit={})  # round 2: the earlier entry is checked again
        self.assertIn("changed after", p.stderr)

    def test_the_old_shape_still_passes_and_unknown_scope_refuses(self):
        self.to_critique()
        p = self.crit([], scope_hash=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        t = store.load_topics(self.root)
        for x in t["topics"]:
            x.pop("refresh_decision", None)
            x["angle"] = ""
        store.save_topics(self.root, t)
        self.assertEqual(self.hrd("refresh-scope", "--topic", TID)[0]["scope_hash"], None)

    def test_auto_exclusion_reasons_and_consent(self):
        crit = {"final_round": {"verdict": "PASS", "audit": {"major": 1}, "out_of_scope": {"major": 1}},
                "audit_log": [out_entry()]}
        self.assertEqual(store.auto_exclusion(crit), ["audit-dismissed", "audit-log:out-of-scope"])
        self.assertEqual(store.blocking_exclusions(store.auto_exclusion(crit), consent=True), [])
        self.assertTrue(store.critique_passed(crit))
        crit["audit_log"] = [out_entry(sev="BLOCKER")]
        self.assertIn("audit-log:out-of-scope-blocker",
                      store.blocking_exclusions(store.auto_exclusion(crit), consent=True, strong=True))

    def test_past_the_cap_out_of_scope_is_empty(self):
        crit = {"final_round": {"audit": {}, "out_of_scope": {"major": 1}}, "audit_log": []}
        self.assertTrue(any("final_round.out_of_scope must be empty" in x for x in store.audit_log_problems(crit, 4)))

    def test_a_topic_that_is_no_refresh_cannot_rule_out_of_scope(self):
        t = store.load_topics(self.root)
        for x in t["topics"]:
            if x["id"] == TID:
                x.pop("refresh_of")
        store.save_topics(self.root, t)
        problems = store.audit_log_problems({"final_round": {}, "audit_log": [out_entry()]}, 1,
                                            self.root, self.cfg, TID)
        self.assertTrue(any("only for a refresh" in x for x in problems), problems)
        self.assertEqual(self.hrd("refresh-scope", "--topic", "t0001")[0], {"refresh_of": None})


# --- refresh-scope (§1.1) ----------------------------------------------------------------------------

class ScopeTests(RefreshCase):
    def set_topic(self, **kw):
        t = store.load_topics(self.root)
        for x in t["topics"]:
            if x["id"] == TID:
                for k, v in kw.items():
                    if v is None:
                        x.pop(k, None)
                    else:
                        x[k] = v
        store.save_topics(self.root, t)
        return self.hrd("refresh-scope", "--topic", TID)

    def test_stale_angle_direction_and_none(self):
        out, _ = self.set_topic(angle="")
        self.assertEqual((out["scope"], out["angle"]), (["the 2025 fee"], None))
        self.assertIn("- the 2025 fee", out["quoted"])
        self.assertTrue(out["scope_hash"].startswith("sha256:"))
        out, _ = self.set_topic(refresh_decision=None, angle="refresh: only the fee table")
        self.assertEqual((out["scope"], out["angle"]), ([], "only the fee table"))
        out, _ = self.set_topic(angle="a plan-made refresh")  # no `refresh:` prefix: the whole text
        self.assertEqual(out["angle"], "a plan-made refresh")
        self.write(".claude/herald/memory/directions/d1.diff", "-old fee\n+new fee\n")
        out, _ = self.set_topic(angle="", direction=".claude/herald/memory/directions/d1.diff")
        self.assertIn("+new fee", out["quoted"])
        out, p = self.set_topic(direction=".claude/herald/memory/directions/gone.diff")
        self.assertEqual((out["direction"], out["quoted"], out["scope_hash"]), (None, "", None))
        self.assertIn("not on this machine", p.stderr)

    def test_adopted_candidates_join_the_scope(self):
        pub = store.load_published(self.root)
        store.find_article(pub, SLUG)["refresh_candidates"] = [
            {"from": "r-old-post-20260501", "id": "R1-3", "severity": "MAJOR", "summary": "parking line is stale",
             "quote": "Parking is free for every visitor today.", "quote_hash": "x"},
            {"from": "r-old-post-20260501", "id": "R1-4", "severity": "MINOR", "summary": "fee sentence",
             "quote": "The fee was 1,000 yen in 2025.", "quote_hash": "y"}]
        store.save_published(self.root, pub)
        self.write(".claude/herald/work/%s/brief.md" % TID,
                   "## Refresh candidates\nadopted: r-old-post-20260501/R1-3 — the parking line\n"
                   "- adopted: `r-old-post-20260501/R1-4`\nadopted: the fee one\n")
        self.write(BODY, CUR)
        out, p = self.hrd("refresh-scope", "--topic", TID)
        self.assertIn("names no candidate", p.stderr)  # `adopted: the fee one`
        self.assertIn("- parking line is stale", out["quoted"])
        self.assertEqual([(a["id"], a["status"]) for a in out["adopted"]], [("R1-3", "unchanged"), ("R1-4", "resolved")])
        pc = self.hrd("refresh-decision", "--slug", SLUG, "--precheck")[0]
        self.assertEqual([c["id"] for c in pc["refresh_candidates"]], ["R1-3", "R1-4"])
        self.assertEqual(self.hrd("status")[0]["refresh_candidates"], 1)


# --- refresh_candidates (§1.5, §R1-M5, §R2-4, §R2-5) -------------------------------------------------

class CandidateTests(RefreshCase):
    def publish(self, tid=TID, log=(), brief="brief", body=CUR, origin="herald", pr=2):
        self.write(BODY, body)
        self.write(".claude/herald/work/%s/brief.md" % tid, brief)
        self.write(".claude/herald/work/%s/critique.json" % tid, json.dumps({"final_round": {}, "audit_log": list(log)}))
        store.record_published(self.root, self.cfg, tid, SLUG, pr=pr, origin=origin)
        return store.find_article(store.load_published(self.root), SLUG).get("refresh_candidates")

    def seed(self, cands):
        pub = store.load_published(self.root)
        store.find_article(pub, SLUG)["refresh_candidates"] = cands
        store.save_published(self.root, pub)

    def test_merge_adopt_prune_and_cap(self):
        old = "r-old-post-20260501"
        self.seed([
            {"from": old, "id": "R1-1", "severity": "MAJOR", "summary": "kept", "quote": "Late entry ends at five today."},
            {"from": old, "id": "R1-2", "severity": "MAJOR", "summary": "gone",
             "quote": "The fee was 1,000 yen in 2025."},
            {"from": old, "id": "R1-3", "severity": "MINOR", "summary": "adopted, unchanged",
             "quote": "Parking is free for every visitor today."},
            {"from": old, "id": "R1-4", "severity": "MAJOR", "summary": "raised again",
             "quote": "Entry is free for children under six.", "quote_hash": scope.quote_hash(
                 "Entry is free for children under six.")}])
        body = CUR.replace("Late entry ends at five.", "Late entry ends at five today.")
        log = [out_entry("R2-1", "Entry is **free** for children under six.", rnd=2),
               out_entry("R1-5", RUBY_SENTENCE, sev="MINOR", summary="s" * 300),
               dict(out_entry("R1-6"), outcome="fixed", scope=None),
               out_entry("R1-7", "The fee was 1,000 yen in 2025.")]  # changed after critique: no candidate
        out = self.publish(log=log, brief="adopted: %s/R1-3\n" % old, body=body)
        self.assertEqual([(c["from"], c["id"]) for c in out],
                         [(old, "R1-1"), (old, "R1-3"), (TID, "R2-1"), (TID, "R1-5")])
        self.assertEqual(out[1]["adopted_by"], TID)
        self.assertEqual((out[3]["severity"], len(out[3]["summary"])), ("MINOR", 200))
        self.seed([{"from": old, "id": "R%d" % i, "summary": "x", "quote": RUBY_SENTENCE + " " * i} for i in range(25)])
        self.assertEqual(len(self.publish(log=[out_entry("R9-9", "Entry is free for children under six.")])), 20)

    def test_a_reused_withdrawn_slug_drops_them(self):
        self.seed([{"from": "r-x", "id": "R1-1", "summary": "old", "quote": RUBY_SENTENCE}])
        pub = store.load_published(self.root)
        store.find_article(pub, SLUG)["withdrawn"] = True
        store.save_published(self.root, pub)
        data = store.load_topics(self.root)
        data["topics"].append({"id": "t0003", "title": "x", "state": "pr-open", "history": [], "reverted_by": []})
        store.save_topics(self.root, data)
        self.assertIsNone(self.publish(tid="t0003"))

    def test_other_publishes_leave_them(self):
        self.seed([{"from": "r-x", "id": "R1-1", "summary": "kept", "quote": "The fee was 1,000 yen in 2025."}])
        data = store.load_topics(self.root)
        data["topics"] += [{"id": "t0002", "title": "x", "state": "pr-open", "history": [], "reverted_by": []},
                           {"id": "tr-old-post-ja", "title": "x", "state": "pr-open", "translate_of": SLUG,
                            "refresh_of": SLUG, "history": [], "reverted_by": []}]
        store.save_topics(self.root, data)
        for tid, origin in (("t0002", "herald"), ("tr-old-post-ja", "herald"), (TID, "external")):
            self.assertEqual(len(self.publish(tid=tid, origin=origin, log=[out_entry()])), 1, tid)
        self.assertIsNone(self.publish(log=[]))  # a refresh's publish: the sentence is gone, nothing left


# --- grounds (§2, §R1-M2, §R1-m10, §R2-3, §R2-7, §R3-3) ------------------------------------------------

RESEARCH = """# Research

**C1.** Fees are 1,200 yen. — https://a.test
- withdrawn: 2026-11-01 — the page is gone
C2: Opening at nine. — https://b.test
  - **withdrawn:** moved
| C3 | Parking is free | https://c.test |
C4 — Shuttle hourly.
*withdrawn*: not true any more
C5. Garden open.
Note: C5 was rechecked; it was not withdrawn: fine.
C6. Fees in 2024 were lower — withdrawn: superseded by C1
| C7 | Museum hours | withdrawn: page gone |
| C8 | Garden hours | https://d.test |
"""


class GroundsTests(RepoCase):
    def sigs(self):
        p = os.path.join(self.root, ".claude/herald/signals.jsonl")
        return [json.loads(l) for l in open(p)] if os.path.exists(p) else []

    def test_withdrawn_blocks_and_emphasis(self):
        self.write(".claude/herald/work/t0001/research.md", RESEARCH)
        self.assertEqual(store.research_claim_ids(self.root, "t0001"), ["C%d" % i for i in range(1, 9)])
        self.assertEqual(store.research_withdrawn_ids(self.root, "t0001"), ["C1", "C2", "C4", "C6", "C7"])

    def test_grounds_normalised_filtered_and_counted_twice(self):
        for t in ("t0001", "t0002", "t0003"):
            self.write(".claude/herald/work/%s/research.md" % t, RESEARCH)
        log = {"decision_log": [
            {"kind": "dismissal", "note": "R1-1: fee is research C5", "grounds": ["C5", " C5", "C9", "C2", "x", 3]},
            {"kind": "dismissal", "note": "R1-2: only withdrawn claims", "grounds": ["C1"]},
            {"kind": "dismissal", "note": "R1-3: style call"}]}
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            store.record_dismissals(self.root, "t0001", log)
        self.assertIn("C9, C2 are not live claims", err.getvalue())
        self.assertIn("C1 are not live claims", err.getvalue())
        recs = self.sigs()
        self.assertEqual([r["data"].get("grounds") for r in recs], [["C5"], None, None])
        store.record_dismissals(self.root, "t0001", dict(log, decision_log=[dict(log["decision_log"][0], grounds=["C3"])]))
        self.assertEqual(len(self.sigs()), 3)  # same note: not a new dismissal
        store.record_dismissals(self.root, "t0002", {"decision_log": [{"kind": "dismissal", "note": "a", "grounds": ["C3"]}]})
        store.record_dismissals(self.root, "t0003", {"decision_log": [{"kind": "dismissal", "note": "b", "grounds": ["C5"]}]})
        r = store.evolve_readiness(self.root, None)
        self.assertEqual((r["signals"], r["themes"]["dismissal"]["count"]), (5, 5))  # the abuse watch keeps them
        self.assertEqual(r["secondary"], {"dismissal:grounded-unseen": {"count": 3, "topics": 3, "new": 3}})
        self.assertIn("dismissal:grounded-unseen", r["ready_themes"])
        self.assertEqual(r["topics"], 3)

    def test_grounds_list_cap(self):
        self.assertEqual(len(store._grounds(["C%d" % i for i in range(30)])), 20)
        self.assertEqual(store._grounds("C1"), [])


# --- retiring signals (§3, §R1-M3, §R1-M4, §R1-m9, §R2-6) -------------------------------------------

class RetireTests(RepoCase):
    def sig(self, kind, tid, data, v=None, at="2026-10-10T00:00:00+00:00"):
        rec = {"at": at, "kind": kind, "topic_id": tid, "data": data}
        if v:
            rec["v"] = v
        with open(os.path.join(self.root, ".claude/herald/signals.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
        return store.signal_id(rec)

    def listing(self):
        return self.hrd("evolve-readiness", "--list")[0]

    def evolve_lock(self):
        return self.hrd("lock", "acquire", "--cmd", "evolve")[0]["token"]

    def retire(self, *ids, token=None, reason="0.4.0 capped audit rounds; these are its repeats", check=False, env=None):
        args = ["evolve-mark", "--retire", *ids]
        if reason is not None:
            args += ["--reason", reason]
        if token:
            args += ["--token", token]
        return self.hrd(*args, check=check, env=env)

    def test_refusals_bind_it_to_an_attended_evolve_run(self):
        a = self.sig("dismissal", "t0001", {"note": "repeat of B2"})
        _, p = self.retire(a, token="nope")
        self.assertIn("not this evolve run", p.stderr)  # no lock at all
        tok = self.hrd("lock", "acquire", "--cmd", "write", "--ship", "--topic", "t0001")[0]["token"]
        _, p = self.retire(a, token=tok)
        self.assertIn("not this evolve run", p.stderr)  # another command's token
        self.hrd("lock", "release", "--cmd", "write", "--token", tok)
        tok = self.hrd("lock", "acquire", "--cmd", "evolve", "--ship", "--topic", "t0001")[0]["token"]
        _, p = self.retire(a, token=tok)
        self.assertIn("--ship", p.stderr)
        self.hrd("lock", "release", "--cmd", "evolve", "--token", tok)
        tok = self.evolve_lock()
        _, p = self.retire(a, token=tok, env={"HRD_UNATTENDED": "1"})
        self.assertIn("attended only", p.stderr)
        _, p = self.retire(a, token=tok, reason=None)
        self.assertIn("--reason", p.stderr)
        _, p = self.retire(a, token=tok, reason="too short")
        self.assertIn("10+ characters", p.stderr)
        _, p = self.retire(a)
        self.assertIn("--token", p.stderr)
        _, p = self.hrd("evolve-mark", "--retire", a, "--unretire", a, "--token", tok, check=False)
        self.assertIn("one per call", p.stderr)
        _, p = self.hrd("evolve-mark", "--consume", a, "--reason", "x" * 20, check=False)
        self.assertIn("go with --retire", p.stderr)
        self.assertEqual(store.load_evolve_state(self.root)["retired"], [])

    def test_retire_groups_unretire_and_prune(self):
        a1 = self.sig("dismissal", "t0001", {"note": "repeat of B2"})
        a2 = self.sig("dismissal", "t0001", {"note": "repeat of B2"}, at="2026-10-11T00:00:00+00:00")  # same group
        b = self.sig("dismissal", "t0002", {"note": "research C9"})
        c = self.sig("dismissal", "t0003", {"note": "policy"}, v="0.22.0")
        base = self.sig("review-finding", "t0004", {"blocker": 0, "major": 0, "minor": 0})
        lst = self.listing()
        groups = {g["id"]: g for g in lst["list"]}
        self.assertEqual(groups[a1]["ids"], [a1, a2])
        self.assertTrue(groups[a1]["legacy"])
        self.assertNotIn("legacy", groups[c])
        self.assertEqual(lst["retired"], {"groups": 0, "ids": 0, "entries": []})
        tok = self.evolve_lock()
        out, _ = self.retire(a2, base, "bogus", a1, token=tok, check=True)
        self.assertEqual((sorted(out["retired"]), out["baseline_cited"], out["unknown"]), (sorted([a1, a2]), [base], ["bogus"]))
        st = store.load_evolve_state(self.root)
        e = st["retired"][0]
        self.assertEqual((e["ids"], e["by"], e["version"], e["run"]), ([a1, a2], "t", store_version(), None))
        lst = self.listing()
        self.assertEqual(sorted(g["id"] for g in lst["list"]), sorted([b, c]))
        self.assertEqual((lst["retired"]["groups"], lst["retired"]["ids"]), (1, 2))
        out, _ = self.retire(a1, token=tok, check=True)
        self.assertEqual(out["already_retired"], [a1])
        out, _ = self.hrd("evolve-mark", "--consume", a2)
        self.assertEqual(out["already_retired"], [a2])
        out, _ = self.hrd("evolve-mark", "--retire", b, "--reason", "r" * 12, "--run", "4", "--token", tok)
        self.assertEqual(store.load_evolve_state(self.root)["retired"][1]["run"], 4)
        out, _ = self.hrd("evolve-mark", "--unretire", a2, "--token", tok)
        self.assertEqual(sorted(out["unretired"]), sorted([a1, a2]))
        st = store.load_evolve_state(self.root)
        self.assertEqual(([x["ids"] for x in st["retired"]], st["unretired"][0]["ids"]), ([[b]], [a1, a2]))
        self.assertIn(a1, [g["id"] for g in self.listing()["list"]])
        with open(os.path.join(self.root, ".claude/herald/signals.jsonl")) as f:  # b's record goes away
            keep = [l for l in f if '"research C9"' not in l]
        with open(os.path.join(self.root, ".claude/herald/signals.jsonl"), "w") as f:
            f.writelines(keep)
        self.hrd("evolve-mark", "--scan")
        self.assertEqual(store.load_evolve_state(self.root)["retired"][0]["ids"], [])  # the decision stays

    def test_observed_repo_shape_before_and_after(self):
        """REVIEW-27 R1: t0001 27 + three r- topics 6 + six other topics 9; retiring t0001 alone leaves
        `dismissal` ready (15 over 8 topics), retiring the rest too silences it."""
        ids = {"t0001": [], "rest": []}
        for i in range(27):
            ids["t0001"].append(self.sig("dismissal", "t0001", {"note": "repeat of B%d" % i}))
        for i in range(6):
            ids["rest"].append(self.sig("dismissal", "r-a-2026010%d" % (i % 3), {"note": "out of refresh scope %d" % i}))
        for i in range(9):
            ids["rest"].append(self.sig("dismissal", "t01%02d" % (i % 6), {"note": "research C%d grounds" % i}))
        self.assertEqual(store.evolve_readiness(self.root, None)["tier"], "sufficient")
        tok = self.evolve_lock()
        self.retire(*ids["t0001"], token=tok, check=True)
        r = store.evolve_readiness(self.root, None)
        self.assertEqual((r["tier"], r["signals"], r["topics"]), ("sufficient", 15, 9))
        self.retire(*ids["rest"], token=tok, check=True)
        self.assertEqual(store.evolve_readiness(self.root, None)["tier"], "none")

    def test_signal_records_its_version(self):
        was = store.PLUGIN_VERSION  # another suite in this process may have set it
        try:
            store.PLUGIN_VERSION = None
            self.assertNotIn("v", store.signal(self.root, "verify-gap", "t0001", {}))  # no version known: no `v`
            store.PLUGIN_VERSION = "9.9.9"
            self.assertEqual(store.signal(self.root, "verify-gap", "t0002", {})["v"], "9.9.9")
        finally:
            store.PLUGIN_VERSION = was
        out, _ = self.hrd("signal", "--kind", "review-finding", "--topic", "t0001", "--data", '{"major": 1}')
        self.assertEqual(out["v"], store_version())


def store_version():
    from helpers import SCRIPTS
    return json.load(open(os.path.join(SCRIPTS, "..", "..", "..", ".claude-plugin", "plugin.json")))["version"]


class RetireDocTests(unittest.TestCase):
    """§R1-M4: Phase 1b only decides; the ledger changes after the commit, with `--consume`."""

    def test_evolve_md_retires_at_the_commit_point(self):
        from helpers import SCRIPTS
        text = open(os.path.join(SCRIPTS, "..", "commands", "evolve.md"), encoding="utf-8").read()
        p1b = text[text.index("## Phase 1b"):text.index("## Phase 2")]
        p6 = text[text.index("## Phase 6"):text.index("## Phase 7")]
        self.assertNotIn("evolve-mark --retire", p1b)
        self.assertIn("evolve-mark --retire", p6)
        self.assertIn("--unretire", p6)
        self.assertLess(p6.index("HRD commit"), p6.index("evolve-mark --retire"))


# --- the guard (§3.2, §R1-M3) -------------------------------------------------------------------------

class GuardTests(RepoCase):
    def test_retire_asks_and_ledgers_are_protected(self):
        hrd = "python3 .claude/herald/scripts/hrd.py "
        g = lambda c, env=None: guard_decision(self.root, "Bash", {"command": c}, env)  # noqa: E731
        for c in ("evolve-mark --retire abc --reason 'x y z w v u' --token t", "evolve-mark --ret abc --token t",
                  "evolve-mark --unretire abc --token t", "evolve-mark --unr abc --token t",
                  "evolve-mark --reason because --retire abc --token t",
                  # review 28 B1: `=` forms, which argparse takes for these list options
                  "evolve-mark --retire=abc --reason 'x y z w v u k' --token t", "evolve-mark --unretire=abc --token t",
                  "evolve-mark --ret=abc --reason 'xxxxxxxxxxxx' --token t", "evolve-mark --u=abc --token t",
                  "lock acquire --cmd evolve", "lock acquire --cmd=evolve", "lock acquire --cm evolve"):
            self.assertEqual(g(hrd + c), "ask", c)
            self.assertEqual(g(hrd + c, {"HRD_UNATTENDED": "1"}), "deny", c)
        for c in ("evolve-mark --consume abc", "evolve-mark --scan --token t", "evolve-readiness --list",
                  "lock acquire --cmd write", "lock release --cmd evolve --token t", "lock status",
                  "evolve-mark --consume abc --token=evolve"):
            self.assertEqual(g(hrd + c), "none", c)
        for rel in (".claude/herald/memory/evolve-state.json", ".claude/herald/memory/evolve-scan.json",
                    ".claude/herald/signals.jsonl"):
            path = os.path.join(self.root, rel)
            self.assertEqual(guard_decision(self.root, "Write", {"file_path": path, "content": "{}"}), "ask", rel)
            self.assertEqual(guard_decision(self.root, "Edit", {"file_path": path}, {"HRD_UNATTENDED": "1"}), "deny")
            self.assertEqual(g("echo '{}' > %s" % rel), "ask", rel)
        self.assertEqual(g("cat .claude/herald/signals.jsonl"), "none")

    def test_reviewer_reproduction_needs_two_human_prompts(self):
        """review 28 B1 end to end: an agent taking the evolve lock and retiring with `--retire=<id>` —
        both commands now ask the human (and are denied unattended); the `=` form really retires."""
        rec = {"at": "2026-10-10T00:00:00+00:00", "kind": "dismissal", "topic_id": "t0001", "data": {"note": "real"}}
        with open(os.path.join(self.root, ".claude/herald/signals.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
        sid = store.signal_id(rec)
        hrd = "python3 .claude/herald/scripts/hrd.py "
        take, retire = "lock acquire --cmd evolve", "evolve-mark --retire=%s --reason 'agent wants quiet' --token %s"
        self.assertEqual(guard_decision(self.root, "Bash", {"command": hrd + take}), "ask")
        self.assertEqual(guard_decision(self.root, "Bash", {"command": hrd + take}, {"HRD_UNATTENDED": "1"}), "deny")
        tok = self.hrd(*take.split())[0]["token"]
        cmd = hrd + retire % (sid, tok)
        self.assertEqual(guard_decision(self.root, "Bash", {"command": cmd}), "ask")
        self.assertEqual(guard_decision(self.root, "Bash", {"command": cmd}, {"HRD_UNATTENDED": "1"}), "deny")
        out, _ = self.hrd("evolve-mark", "--retire=%s" % sid, "--reason", "agent wants quiet", "--token", tok)
        self.assertEqual(out["retired"], [sid])  # the form the guard must see is a real one


if __name__ == "__main__":
    unittest.main()
