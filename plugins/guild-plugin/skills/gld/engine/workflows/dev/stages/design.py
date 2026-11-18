"""workflows.dev.stages.design — the `design` stage as code (catalog A §2.8; design §3.2 G-SPLIT, §3.3
DE-ARB, §3.6 design→execute).

    E0  enter (C-F-1, entry label) → analyze:output (absent / no AC → NEEDS_CONTEXT, J-DEV-05 maps it
        to analyze) → IS_LEAF (`guild:child`) → discovery of existing children (always, never the label)
    E1  VISUAL (code: VISUAL_AVAILABLE ∧ KICKOFF `ui_surface` inside `visual.packages`, or the
        safety-net override) · specialists = KICKOFF cast ∩ design specialists ∩ installed roster
    E2  roles, in this order: tester (cases — given ONLY the AC; it runs before the tech-lead, so on a
        fresh design no skeleton exists anywhere it could read) → tech-lead (skeleton + split.json) →
        specialists. Every artifact is written to the role's own `out/` and read back by the engine
        (`roleout`, P1); BLOCKED/NEEDS_CONTEXT → DE-ARB (one re-invocation per role); FAIL → FAIL.
        Each artifact's contract (design→execute, §3.6) is checked; a failure → that role repairs
        ONCE → still failing → SJ-HANDOFF (ok / ok_with_assumption → on; upstream_gap → a person)
    E3  split (split.json `split: true`) → L0-SPLIT (unsure → a person; leaf → `ask leaf-split`; every
        parent AC must be in a slice) → children created in order with a hidden slice key (A-F23 —
        existing keys are never created again) → design:output (with the split) → `guild:children` →
        roster `<!-- guild:children:output -->` (once) → `OK SPLIT: N children` (A-F38 order)
    E4  single PR: specs kept in the engine's spec store → design:output → `guild:design → guild:execute`
"""

import json
import re

from guildcore import ask as ASK
from guildcore.checks import visual as V
from guildcore.adapters.gh import GhWriteError
from guildcore.decisions import DecisionLog
from guildcore.records import markers
from guildcore.records import outputs as OUT
from workflows.dev import analysis as AN
from workflows.dev import arbitration as ARB
from workflows.dev import handoff as HO
from workflows.dev import judging as JG
from workflows.dev import roleout as RO
from workflows.dev.stages import analyze as A
from workflows.dev.stages import base as B

STAGE = "design"
CHILD_PREFIX = "[Guild子] "
SLICE_KEY_RE = re.compile(r"<!-- guild:slice-key (\S+) -->")
TL_STATUSES = ("DONE", "BLOCKED", "NEEDS_CONTEXT", "FAIL")
SPECIALIST_SCHEMA = {"type": "object", "properties": {"file": {"type": "string"},
                                                       "none_applicable": {"type": "boolean"}}}


def kickoff_block(comments):
    blk = None
    for b in DecisionLog.load(comments).blocks:
        if b.get("point") == "KICKOFF" and b.get("stage") == "analyze":
            blk = b
    return blk


def visual_decision(cfg, kick, ac):
    """(VISUAL, why) — L.1 as code; the UI-surface half is KICKOFF's (J-DE-01 merged into it)."""
    avail = V.visual_available(cfg)
    if not avail:
        return False, "VISUAL_AVAILABLE=false"
    net_visual = kick is not None and kick.get("safety_net_visual") == "true"
    if net_visual:
        return True, "safety-net visual case (override)"
    if kick is None:
        return False, "ui surface unknown (analyze ran before the engine) — no visual cases"
    if kick.get("ui_surface") != "true":
        return False, "no UI surface"
    pk = (cfg.get("visual") or {}).get("packages") or []
    if pk:
        areas = [x for x in (kick.get("areas") or "").split(",") if x]
        if not any(a == q or a.startswith(q.rstrip("/") + "/") or q.startswith(a.rstrip("/") + "/")
                   for a in areas for q in pk):
            return False, "UI surface outside visual.packages"
    return True, "UI surface ∧ VISUAL_AVAILABLE"


def visual_count(test_cases):
    if not test_cases or "<!-- guild:visual-cases -->" not in test_cases:
        return 0
    tail = test_cases.split("<!-- guild:visual-cases -->", 1)[1]
    n = 0
    for ln in tail.split("\n"):
        s = ln.strip()
        if s.startswith("#"):
            break
        if s.startswith("|") and not re.match(r"^\|[\s:|-]+\|?$", s) and "AC" in s:
            n += 1
        elif s.startswith(("- ", "* ")):
            n += 1
    return n


def specialist_file(role):
    return "ux.md" if role == "designer" else "%s.md" % role


def child_key(c):
    """K4r4-m4: a child's slice key is its JOURNAL key (`own_children` rows carry it) — a body comment a
    person edited away must not hide a child from the duplicate check. The body tag only for rows that are
    not the engine's own (none reach the stages since r3)."""
    if c.get("key"):
        return c["key"]
    m = SLICE_KEY_RE.search(c.get("body") or "")
    return m.group(1) if m else None


def duplicate_keys(children):
    seen = {}
    for c in children:
        k = child_key(c)
        if k:
            seen.setdefault(k, []).append(c["number"])
    return dict((k, sorted(v)) for k, v in seen.items() if len(v) > 1)


def existing_keys(children):
    out = {}
    for c in children:
        k = child_key(c)
        if k:
            out[k] = c["number"]
    return out


# ---- the stage ----------------------------------------------------------------------------------

def run(p, only=None, config_present=True):
    e = B.enter(p, STAGE, config_present)
    if isinstance(e, B.StageResult):
        return e
    B.note_untrusted(p, STAGE)
    B.register_exact(p)
    comments = B.records(p)
    so = OUT.find(comments, "analyze:output")
    if so is None:
        return B.StageResult(B.StageResult.FAIL, line="analyze output not found for #%d" % p.issue,
                             fail_class="needs_context")
    rec = AN.parse_output(so.body)
    if not rec.ac:
        return B.StageResult(B.StageResult.FAIL, line="analyze output not found for #%d (no acceptance criteria)" % p.issue,
                             fail_class="needs_context")
    is_leaf = "guild:child" in e.labels
    kick = kickoff_block(comments)
    cfg = getattr(p.config, "raw", None) or (p.config if isinstance(p.config, dict) else {})
    issue = p.gh.issue(p.issue)
    try:
        trust, _assoc = A.trusted_body(p, issue)
    except A.TrustUnknown as ex:
        return A.unknown_trust_result(p, STAGE, ex)
    body = issue.get("body") or ""
    if not trust:
        body = A.OUTSIDER_PREFACE + body                 # K4r1-m10: DE-ARB / STAKES briefs mark it untrusted
    slot = ""
    if trust:
        for m in ("<!-- guild:refactor-slot -->", "<!-- guild:safety-net -->", "<!-- guild:safety-net-only -->"):
            if m in body:
                slot += m.replace("<!-- guild:", "").replace(" -->", "") + "\n"
    # K4r3-B1: the engine's own children by its journal (numbers read by number — never a listing);
    # K4r2-m4: a child a person closed as not planned is withdrawn (the documented re-split path)
    children, stop = B.own_children_or_stop(p, STAGE)
    if stop is not None:
        return stop
    answers = {}
    for kind in ("design-block", "leaf-split", "escalation"):
        q, res = B.pending_answer(p, STAGE, kind, comments)
        if res is not None:
            if res.get("choice") == "stop":
                return B.StageResult(B.StageResult.PAUSE, cause="stopped by the human answer %s" % res.id)
            answers[kind] = (q, res)
    # K4r1-M2: a design that already decided a split (a recorded SPLIT block) or already has children
    # NEVER re-judges — it resumes from the recorded plan and creates only the missing keys
    plan_blk = split_block(comments)
    if children or plan_blk is not None:
        return resume_split(p, e, rec, children, plan_blk, is_leaf, answers, trust)
    RO.clear(p)                                        # K4r1-m8: a fresh design starts with an empty spec store
    visual, vwhy = visual_decision(cfg, kick, rec.ac)
    ros = A.roster(p)
    cast = [x for x in ((kick.get("cast") or "").split(",") if kick else (rec.cast or [])) if x]
    specialists = sorted(set(r for r in cast if r in AN.DESIGN_SPECIALISTS and r in ros))
    if visual and "designer" in ros and "designer" not in specialists:
        specialists.append("designer")                 # the UI surface IS the designer trigger (one decision)
    trace = ["visual: %s (%s)" % ("yes" if visual else "no", vwhy), "leaf: %s" % is_leaf,
             "existing children: %s" % (", ".join("#%d" % c["number"] for c in children) or "none"),
             "specialists: %s" % (", ".join(specialists) or "none")]
    ac_ids = [a["n"] for a in rec.ac]
    ac_md = "\n".join("- %s%s: %s" % (a["id"], " (safety net)" if a["net"] else "", a["text"]) for a in rec.ac)
    analyze_md = so.body
    std = "\n\n".join("## %s\n%s" % s for s in A.standards(p))
    irr = AN.irreversible((kick.get("areas") or "").split(",") if kick else [], p.engine_cfg("irreversible_globs"))
    reinvoked, assumptions, concerns, rows = set(), [], [], []
    ctx = [("analyze", analyze_md[:12000])]

    # E2.1 — tester (cases) first: given only the AC
    vis_txt = "VISUAL = %s" % ("yes" if visual else "no")
    tester_in = {"ac.md": {"text": ac_md}, "visual.txt": {"text": vis_txt}}

    def tester(addendum=None):
        # K4r1-m4: `spec-cases` = read-only on the main checkout (its artifact is out/test-cases.md)
        return p.run_role(B.RoleCall("tester", "spec-cases", STAGE, "E1.1", inputs=tester_in, addendum=addendum))

    def check_cases(text):
        return HO.cases_bad(text, ac_ids, visual)
    got = artifact(p, "tester", tester, "out/test-cases.md", check_cases, reinvoked, ctx, body, irr, ac_md)
    if isinstance(got, B.StageResult):
        return got
    tc_text, tres, tnote = got
    rows.append(("tester", "스파인", tres.status, tres.line))
    assumptions += tnote

    # E2.2 — tech-lead (skeleton + split)
    ex_md = "\n\n".join("#%d %s\n%s" % (c["number"], c["title"], c.get("body") or "") for c in children)
    tl_in = {"analyze-output.md": {"text": analyze_md}, "standards.md": {"text": std},
             "existing-children.md": {"text": ex_md}, "slot.txt": {"text": slot}}

    def techlead(addendum=None):
        return p.run_role(B.RoleCall("tech-lead", "design", STAGE, "E1.1", inputs=tl_in, addendum=addendum,
                                     allowed_status=TL_STATUSES))
    split_holder = {}

    got = artifact(p, "tech-lead", techlead, "out/skeleton.md", HO.skeleton_bad, reinvoked, ctx, body, irr, ac_md,
                   extra=lambda res: split_holder.update(split=RO.json_out(p, STAGE, res, (res.extras or {}).get("split_path")
                                                                           or "out/split.json")))
    if isinstance(got, B.StageResult):
        return got
    sk_text, tlres, tlnote = got
    rows.append(("tech-lead", "스파인", tlres.status, tlres.line))
    assumptions += tlnote
    split = split_holder.get("split") or {"split": False}
    if not isinstance(split.get("split"), bool):
        B.record_code(p, STAGE, "split-json-invalid", "single", reason="split.json without a boolean `split` → single")
        split = {"split": False}

    # E2.3 — specialists
    spec_files = {}
    for role in specialists:
        fname = specialist_file(role)
        sp_in = {"analyze-output.md": {"text": analyze_md}, "standards.md": {"text": std}, "visual.txt": {"text": vis_txt}}

        def sp(addendum=None, role=role, sp_in=sp_in):
            return p.run_role(B.RoleCall(role, "design", STAGE, "E1.5", inputs=sp_in, addendum=addendum,
                                         schema=SPECIALIST_SCHEMA))
        res = sp()
        while res.status in ("BLOCKED", "NEEDS_CONTEXT"):
            if res.status == "BLOCKED" and (res.extras or {}).get("evidence"):
                # J-DE-09: a specialist BLOCKED carrying an objective finding (A-F27 `evidence`) reverses an approach
                p.capture("correction", STAGE, role, "%s BLOCKED at design" % role,
                          B.one_line(str(res.extras.get("evidence")), 160), "#%d" % p.issue, True)
            out = ARB.blocked(p, STAGE, role, res, ctx, reinvoked, lambda add, f=sp: f(add), body, [], irr, "E2.1")
            if isinstance(out, B.StageResult):
                return out
            if out[0] == "decided":
                assumptions.append("%s %s — %s" % (role, res.status, out[1]))
                res = None
                break
            res = out[1]
        if res is None:
            rows.append((role, "참여", "BLOCKED→판단", ""))
            continue
        r = B.role_outcome(p, STAGE, role, res)
        if r is not None:
            return r
        if res.status == "FAIL":
            return B.fail(p, STAGE, "%s FAIL — %s" % (role, B.one_line(res.line or "", 160)))
        if res.status == "DONE_WITH_CONCERNS":
            concerns.append("%s: %s" % (role, B.one_line(res.line or "", 200)))
        if not (res.extras or {}).get("none_applicable"):
            text = RO.read(p, STAGE, res, (res.extras or {}).get("file") or "out/" + fname)
            if text is None:
                return B.fail(p, STAGE, "%s reported %s without its file" % (role, res.status))
            spec_files[fname] = text
        rows.append((role, "게이트" if role in AN.GATE_ROLES else "참여", res.status, res.line))

    # keep the specs (engine store — installed into the execute worktree later)
    RO.put(p, "test-cases.md", tc_text)
    RO.put(p, "skeleton.md", sk_text)
    for fname, text in spec_files.items():
        RO.put(p, fname, text)
    RO.put(p, "split.json", json.dumps(split, ensure_ascii=False))
    if p.engine_cfg("handoff_judge", "default") == "always":
        hd = HO.judge(p, STAGE, "design→execute", [], [("skeleton", sk_text[:6000]), ("test_cases", tc_text[:6000])],
                      ac_md, issue.get("title") or "", "E4")
        if hd.choice == "upstream_gap":
            return _gap(p, "design 산출물 간극(HANDOFF) — %s" % B.one_line(hd.fields.get("reason") or "", 200))
        if hd.choice == "ok_with_assumption":
            assumptions.append(hd.fields.get("line") or "")

    if split.get("split"):
        return do_split(p, e, rec, split, sk_text, children, is_leaf, answers, rows, assumptions, concerns,
                        visual, tc_text, trace, specialists, spec_files, trust)
    out = render_output(p.issue, rows, visual, tc_text, spec_files, specialists, cast, None, assumptions,
                        concerns, trace)
    p.writer.upsert_comment(p.issue, "design:output", out)
    for kind, (q, res) in answers.items():
        B.mark_applied(p, STAGE, res)
    B.transition(p, e, "execute")
    return B.StageResult(B.StageResult.ADVANCE, nxt="execute")


def _gap(p, line):
    q = ASK.Question("design-block", line, [{"token": "stop", "label": "stop"}])
    return B.ask(p, STAGE, q, line, {"cause_kind": "ambiguity", "line": line, "token_cause": "ambiguity: %s" % line})


def artifact(p, role, call, rel, check, reinvoked, ctx, body, irr, ac_md, extra=None):
    """Run a design role → its artifact (text, result, assumptions) or a StageResult. BLOCKED /
    NEEDS_CONTEXT → DE-ARB; the contract check failing → one repair → SJ-HANDOFF."""
    res = call()
    notes = []
    while res.status in ("BLOCKED", "NEEDS_CONTEXT"):
        out = ARB.blocked(p, STAGE, role, res, ctx, reinvoked, lambda add: call(add), body, [], irr, "E2.1")
        if isinstance(out, B.StageResult):
            return out
        if out[0] == "decided":
            # a design artifact cannot be assumed into existence — the decision becomes the retry's context
            notes.append("%s %s — %s" % (role, res.status, out[1]))
            if role in reinvoked:
                return _gap(p, "%s %s — 판단(%s)으로도 산출물이 없음" % (role, res.status, B.one_line(out[1], 120)))
            reinvoked.add(role)
            res = call("Decision for your blocker (proceed on it): %s" % out[1])
            continue
        res = out[1]
    r = B.role_outcome(p, STAGE, role, res)
    if r is not None:
        return r
    if res.status == "FAIL":
        return B.fail(p, STAGE, "%s FAIL — %s" % (role, B.one_line(res.line or "", 160)))
    repaired = False
    while True:
        if extra is not None:
            extra(res)
        text = RO.read(p, STAGE, res, rel) or ""
        bad = check(text)
        if not bad:
            return text, res, notes
        if not repaired:
            repaired = True
            res = call("Your artifact failed the hand-over check: %s. Fix exactly that and return again." % "; ".join(bad))
            r = B.role_outcome(p, STAGE, role, res)
            if r is not None:
                return r
            if res.status not in ("DONE", "DONE_WITH_CONCERNS"):
                return _gap(p, "%s repair returned %s — %s" % (role, res.status, B.one_line(res.line or "", 160)))
            continue
        d = HO.judge(p, STAGE, "design→execute", bad, [(role, text[:8000])], ac_md, "#%d" % p.issue, "E2.1")
        if d.choice == "ok":
            return text, res, notes
        if d.choice == "ok_with_assumption":
            return text, res, notes + [d.fields.get("line") or ""]
        return _gap(p, "design 산출물 간극(%s) — %s" % (role, "; ".join(bad)[:200]))


def render_output(issue, rows, visual, tc_text, spec_files, specialists, cast, split_line, assumptions, concerns, trace):
    v = markers.value
    n = int(issue)
    out = [markers.open_tag("design:output"), "## Guild design — #%d" % n, "",
           split_line or "분할: 없음 — 단일 PR",
           "skeleton: docs/specs/%d/skeleton.md" % n,
           "test-cases: docs/specs/%d/test-cases.md" % n,
           "visual: %s" % ("yes" if visual else "no")]
    if visual:
        out.append("시각 케이스 %d건" % visual_count(tc_text))
    for fname in sorted(spec_files):
        out.append("spec: docs/specs/%d/%s" % (n, fname))
    out += ["", "### 참여 역할"]
    for role, why, st, line in rows:
        out.append("- %s (%s): %s%s" % (role, why, st, (" — " + v(B.one_line(line, 160))) if line else ""))
    skipped = [r for r in cast if r in AN.DESIGN_SPECIALISTS and r not in specialists]
    if skipped:
        out += ["", "### 소집하지 않은 역할"] + ["- %s: 설치되지 않음" % r for r in skipped]
    if concerns:
        out += ["", "### 우려"] + ["- %s" % v(c) for c in concerns]
    if assumptions:
        out += ["", "### 가정"] + ["- 가정: %s" % v(a) for a in assumptions if a]
    out += ["", "<details><summary>preflight trace</summary>", ""] + ["- %s" % v(t) for t in trace] + \
        ["", "</details>", markers.close_tag("design:output")]
    return markers.assert_own_markers("\n".join(out), "design:output")


SLICE_KEY_OK = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
PLAN_FILE = "split-plan.json"


def child_body(parent, sl, ac_by_id, trusted=True):
    lines = [markers.value(sl.get("scope") or "", one_line=False), "", "## 수용 기준"]
    for aid in sl.get("ac_ids") or []:
        a = ac_by_id.get(aid)
        if a is not None:
            lines.append("- %s: %s" % (aid, markers.value(a["text"])))
    # K4r1-m3: no second discovery line ANYWHERE in the body (scope, AC text) — only the engine's last line
    body = re.sub(r"Parent Issue:\s*#", "Parent Issue #", "\n".join(lines))
    if not trusted:
        body += "\n\n" + A.UNTRUSTED_ORIGIN               # K4r1-m11: the child inherits the parent's untrust
    return body + "\n\nParent Issue: #%d" % int(parent)


def split_block(comments):
    """The recorded SPLIT decision that chose `split` (the last one not resolved by a later block —
    a person's `superseded`, K4r2-m4), or None."""
    log = DecisionLog.load(comments)
    gone = log.resolved_ids()
    blk = None
    for b in log.blocks:
        if b.get("point") == "SPLIT" and b.get("stage") == STAGE and b.id not in gone:
            blk = b
    return blk if blk is not None and blk.get("choice") == "split" else None


def _plan_sha(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def ac_sha(ac):
    """K4r2-m4: the analysis the plan was made from — every AC id and text, in order."""
    return _plan_sha("\n".join("%s: %s" % (a["id"], a["text"]) for a in ac))


PLAN_RECORD = "split-plan"


def _neutral(obj):
    """Every string of the plan through `markers.value` (redact + neutralise; idempotent)."""
    if isinstance(obj, str):
        return markers.value(obj, one_line=False)
    if isinstance(obj, list):
        return [_neutral(x) for x in obj]
    if isinstance(obj, dict):
        return dict((k, _neutral(v)) for k, v in obj.items())
    return obj


def render_plan_record(text, children):
    """The engine's split record on the parent (K5, K4r2-m5 / K4r4 carry-over 8): the exact plan text (its sha is
    in the SPLIT block) and the child numbers by slice key — what another host or a fresh clone resumes from."""
    return "\n".join([markers.open_tag(PLAN_RECORD),
                      "<details><summary>Guild split plan — engine record, do not edit</summary>", "",
                      "plan_sha: %s" % _plan_sha(text),
                      "children: %s" % json.dumps(dict(sorted(children.items())), sort_keys=True),
                      "plan: %s" % text, "", "</details>", markers.close_tag(PLAN_RECORD)])


def read_plan_record(comments):
    """(plan_text, {key: number}) from the parent's trusted split record, or (None, {})."""
    c = markers.find(comments, PLAN_RECORD)
    if c is None:
        return None, {}
    text, kids = None, {}
    for ln in markers.body_of(c).split("\n"):
        if ln.startswith("plan: "):
            text = ln[len("plan: "):]
        elif ln.startswith("children: "):
            try:
                kids = dict((str(k), int(v)) for k, v in json.loads(ln[len("children: "):]).items())
            except (ValueError, TypeError, AttributeError):
                kids = {}
    return text, kids


def publish_plan(p, text, children):
    _old, kids = read_plan_record(B.records(p))
    kids = dict(kids, **children)
    p.writer.upsert_comment(p.issue, PLAN_RECORD, render_plan_record(text, kids))


def load_plan(p, blk):
    """(plan, None) from the engine spec store — or, on another host / a fresh clone, from the parent's split
    record on GitHub (K5) — verified against the recorded SPLIT block; or (None, why)."""
    text = RO.get(p, PLAN_FILE)
    if text is None:
        rtext, _kids = read_plan_record(B.records(p))
        if rtext is not None and blk.get("plan_sha") and blk.get("plan_sha") == _plan_sha(rtext):
            RO.put(p, PLAN_FILE, rtext)
            text = rtext
    if text is None:
        return None, "no stored split plan"
    if not blk.get("plan_sha") or blk.get("plan_sha") != _plan_sha(text):
        return None, "stored split plan does not match the recorded SPLIT block %s" % blk.id
    try:
        plan = json.loads(text)
    except ValueError:
        return None, "stored split plan unreadable"
    slices = plan.get("slices") if isinstance(plan, dict) else None
    if not slices or not all(isinstance(x, dict) and SLICE_KEY_OK.match(str(x.get("key") or "")) for x in slices):
        return None, "stored split plan has no valid slices"
    return plan, None


def do_split(p, e, rec, split, sk_text, children, is_leaf, answers, rows, assumptions, concerns, visual, tc_text,
             trace, specialists, spec_files, trusted=True):
    keys = existing_keys(children)
    brief = [("split", json.dumps(split, ensure_ascii=False)[:12000]),
             ("parent_ac", "\n".join("%s: %s" % (a["id"], a["text"]) for a in rec.ac)),
             ("existing_children", "\n".join("#%d %s (key %s)" % (c["number"], c["title"],
                                             next((k for k, v in keys.items() if v == c["number"]), "-")) for c in children) or "none"),
             ("skeleton", sk_text[:8000])]
    d = p.judge(JG.spec(p, "SPLIT", brief, STAGE, "E2.2"))
    slices = sorted([s for s in d.fields.get("slices") or [] if isinstance(s, dict)], key=lambda s: s.get("order") or 0)
    choice = d.choice
    covered = set()
    for s in slices:
        covered.update(s.get("ac_ids") or [])
    missing = [a["id"] for a in rec.ac if a["id"] not in covered]
    seen = set()
    dup = [s.get("key") for s in slices if s.get("key") in seen or seen.add(s.get("key"))]
    badkey = [s.get("key") for s in slices if not SLICE_KEY_OK.match(str(s.get("key") or ""))]
    if choice == "split" and (missing or dup or badkey or not slices):
        choice = "unsure"
    extra = {"slices": [s.get("key") for s in slices] or None}
    if choice == "split" and not is_leaf:
        # K4r1-M2: the plan is stored BEFORE the decision is recorded and before any child exists —
        # every later run resumes from exactly this plan (sha in the block), never from a new judgment
        plan = {"ac_sha": ac_sha(rec.ac), "slices": [{"key": s["key"], "name": str(s.get("name") or s["key"])[:200],
                            "scope": str(s.get("scope") or "")[:4000], "order": s.get("order") or 0,
                            "ac_ids": [x for x in s.get("ac_ids") or [] if isinstance(x, str)]} for s in slices],
                "render": {"rows": [list(r) for r in rows], "visual": bool(visual), "specialists": list(specialists),
                           "spec_files": sorted(spec_files), "assumptions": list(assumptions),
                           "concerns": list(concerns), "trace": list(trace)}}
        plan = _neutral(plan)                       # K5 (P1): the plan is posted on GitHub — redacted before its sha
        text = json.dumps(plan, ensure_ascii=False, sort_keys=True)
        RO.put(p, PLAN_FILE, text)
        extra["plan_sha"] = _plan_sha(text)
        publish_plan(p, text, {})                   # K5 (K4r2-m5): host portability — the plan lives on GitHub too
    B.record_judgment(p, STAGE, "SPLIT", "J-DE-05", d, choice=choice,
                      reason=("AC not in any slice: %s" % ", ".join(missing)) if missing else (d.fields.get("reason") or "")[:300],
                      extra=extra)
    if choice == "single":
        out = render_output(p.issue, rows, visual, tc_text, spec_files, specialists, [], "분할: 없음 — 단일 PR (L0-SPLIT)",
                            assumptions, concerns, trace)
        p.writer.upsert_comment(p.issue, "design:output", out)
        B.transition(p, e, "execute")
        return B.StageResult(B.StageResult.ADVANCE, nxt="execute")
    if choice != "split":
        return _gap(p, "분할 판단 불확실 — 분할은 되돌리기 어려움 (%s)" % B.one_line(d.fields.get("reason") or "", 160))
    if is_leaf:
        return _leaf(p)
    return make_children(p, e, rec, plan, children, answers, trusted)


def _leaf(p):
    line = "child #%d cannot be re-split — re-scope the parent" % p.issue
    q = ASK.Question("leaf-split", line, [{"token": "stop", "label": "stop"}])
    return B.ask(p, STAGE, q, line, {"cause_kind": "ambiguity", "line": line, "token_cause": "ambiguity: %s" % line})


def resume_split(p, e, rec, children, blk, is_leaf, answers, trusted):
    """K4r1-M2: children exist or a split was recorded — no tester, tech-lead or L0-SPLIT again. The
    recorded plan (store + sha in the SPLIT block) is the only source of slices; a child outside it,
    or no verifiable plan, is a person's."""
    if is_leaf:
        return _leaf(p)
    nums = ", ".join("#%d" % c["number"] for c in children) or "none"
    if blk is None:
        return B.fail(p, STAGE, "split resume — children exist (%s) but no SPLIT decision chose a split; "
                      "a person decides (close the children or move the parent to guild:children)" % nums)
    plan, why = load_plan(p, blk)
    if plan is None:
        return B.fail(p, STAGE, "split resume — %s; existing children: %s — a person decides" % (why, nums))
    if plan.get("ac_sha") != ac_sha(rec.ac):
        # K4r2-m4: rollback → analyze re-ran → the AC changed; the old plan would leave new AC in no child
        return B.fail(p, STAGE, "split resume — the acceptance criteria changed since the recorded split plan %s; "
                      "a person decides (close the children as not planned and supersede the SPLIT block to "
                      "re-split, or restore the analysis)" % blk.id)
    want = set("%d-%s" % (p.issue, s["key"]) for s in plan["slices"])
    stray = []
    for c in children:
        m = SLICE_KEY_RE.search(c.get("body") or "")
        if not m or m.group(1) not in want:
            stray.append("#%d" % c["number"])
    if stray:
        return B.fail(p, STAGE, "split resume — children outside the recorded split plan %s: %s — a person decides"
                      % (blk.id, ", ".join(stray)))
    B.record_code(p, STAGE, "split-resume", "resumed", refs=blk.id,
                  reason="split resumed from the recorded plan — existing: %s" % nums)
    return make_children(p, e, rec, plan, children, answers, trusted)


def make_children(p, e, rec, plan, children, answers, trusted):
    """Create the plan's missing children in order — idempotent by slice key, journal first (K4r3-B1:
    the writer journals intent + token before each POST and the number right after; a lost reply is
    resolved by the token through the REST list, never a search-backed read; still unknown → a
    person, nothing re-sent) — then the children read back BY NUMBER (two live children with one key
    → a person) → design:output → `guild:children` → roster (A-F38). A failure goes through `B.fail`
    (needs-human unattended)."""
    slices = sorted(plan["slices"], key=lambda s: s.get("order") or 0)
    ac_by_id = dict((a["id"], a) for a in rec.ac)
    have = existing_keys(children)
    for i, s in enumerate(slices):
        full = "%d-%s" % (p.issue, s["key"])
        if full in have:
            continue
        title = CHILD_PREFIX + markers.value(s.get("name") or s["key"])[:90]
        try:
            n, _created = p.writer.issue_create(title, child_body(p.issue, s, ac_by_id, trusted),
                                                labels=["guild:child", "guild:analyze"], key=full)
        except GhWriteError as ex:
            if ex.kind in ("auth", "ratelimit"):
                raise                                   # the FSM's exit 3 / 75
            # a lost reply was already looked up by its token (REST list, backoff) inside the writer;
            # "ambiguous" = still unknown → a person, and nothing is sent again
            # K4r4-m3: 1-based slice counter; the message names when a resume can settle an unknown create
            return B.fail(p, STAGE, "child creation failed at slice %s (%d/%d) — %s" % (
                s["key"], i + 1, len(slices), B.one_line(str(ex), 320)),
                "transient" if ex.kind in ("transient", "ambiguous") else "defect")
        have[full] = n
        publish_plan(p, json.dumps(plan, ensure_ascii=False, sort_keys=True), {full: int(n)})   # K5: numbers on GitHub
    now, stop = B.own_children_or_stop(p, STAGE)
    if stop is not None:
        return stop
    dups = duplicate_keys(now)
    if dups:
        # K4r2-M1: two live children with one slice key would run the same AC twice — a person's
        return B.fail(p, STAGE, "duplicate child Issues for one slice key: %s — close the extra one as not planned (or duplicate), "
                      "then /gld resume %d" % ("; ".join("%s → %s" % (k, ", ".join("#%d" % n for n in v))
                                                          for k, v in sorted(dups.items())), p.issue))
    got = existing_keys(now)
    lost = [s["key"] for s in slices if "%d-%s" % (p.issue, s["key"]) not in got]
    if lost:
        return B.fail(p, STAGE, "created children not listed yet (%s) — resume picks them up" % ", ".join(lost), "transient")
    nums = [c["number"] for c in now]
    split_line = "분할: %d개 자식 — %s" % (len(nums), ", ".join("#%d" % x for x in nums))
    r = plan.get("render") or {}
    tc_text = RO.get(p, "test-cases.md") or ""
    spec_files = dict((f, "") for f in r.get("spec_files") or [])
    out = render_output(p.issue, [tuple(x) for x in r.get("rows") or []], bool(r.get("visual")), tc_text, spec_files,
                        r.get("specialists") or [], [], split_line, r.get("assumptions") or [], r.get("concerns") or [],
                        r.get("trace") or [])
    p.writer.upsert_comment(p.issue, "design:output", out)
    B.transition(p, e, "children")
    if markers.find(B.records(p), "children:output") is None:
        by_key = dict((v, k) for k, v in got.items())
        lines = [markers.open_tag("children:output"), "## 자식 Issue (#%d)" % p.issue, ""]
        for c in now:
            key = by_key.get(c["number"], "")
            sl = next((s for s in slices if "%d-%s" % (p.issue, s["key"]) == key), None)
            lines.append("- #%d · %s · %s" % (c["number"], markers.value(c.get("title") or "")[:100],
                                               markers.value(B.one_line((sl or {}).get("scope") or "", 140))))
        lines.append(markers.close_tag("children:output"))
        p.writer.create_comment(p.issue, markers.assert_own_markers("\n".join(lines), "children:output"))
    for kind, (q, res) in answers.items():
        B.mark_applied(p, STAGE, res)
    return B.StageResult(B.StageResult.SPLIT, nxt=len(nums))
