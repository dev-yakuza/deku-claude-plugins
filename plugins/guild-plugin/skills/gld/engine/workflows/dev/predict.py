"""workflows.dev.predict — when a human question is predict-first (design §2.6 `predict_first`, R5J-M4, §9.5, §10.4).

A question is predict-first — the person answers BEFORE seeing the engine's recommendation — when any of these holds
(`forced(p, q)` returns the first reason, or None):

    high-risk      the question comes from a §9.5 high-risk group (KICKOFF · STAKES · EX-ARB:dismiss · ESCALATE ·
                   SPLIT · INTEGRATE) — always
    conservative   `group.<g>.conservative` is in force (a valve — the §9.5 count rule or a person)
    watch          the group is on the §9.5 watch list (`grade-state.json`)
    option         `config.learning.predict_first: true` and the kind is readiness · disputed-blocker · loopback
    first-sprint   first-sprint mode (§10.4): `config.engine.first_sprint_mode` on, or auto with no recorded go

Only these answers count as a human judgment in §9.5 (G1, graduation, release). What it changes:
  attended    the `ask` event carries no recommendation; the pending block carries `recommended_sha` only; the
              answer's resolution block reveals `recommended` + `nonce` (`dev answer` prints the reveal)
  unattended  the pause comment shows evidence, question, options and the reasons — never the token; the pending
              block carries `recommended_sha`; the nonce is journaled BEFORE the commitment is written (crash-safe)
  wording     (K5r3-M1) the question is rendered from its neutral wording (`Question.neutral`), options in the
              canonical order (label, token; `stop` last); `apply` — the one enforcement point — REFUSES a blind
              answer (`predict_first_refused`, recommendation shown openly, never a §9.5 human judgment) when the
              question, its options, the text going out with it or this stage's decision-log free text names the
              recommendation, or when the kind states it by being asked (close-decided)
  names       (K5r4-M1/m6) an option goes by its engine token, the judge's own id (`Question.aliases` — KICKOFF's
              `I2` / `B` / `broad`, which `analysis.to_tokens` also rewrites to the token in the judge's text) and
              its full summary; whole words, case-insensitive. A text naming every option equally often, with no
              preference word, is neutral; an unreadable decision log refuses (K5r4-m2 — fail closed)
  KICKOFF     its decision block carries `chosen_sha` instead of `chosen` (the chosen interpretation IS the readiness
              question's recommendation); analyze:output names it once the stage goes on

First-sprint "auto" ends only on a recorded go (§10.4, R4C-m9): a trusted `<!-- guild:note -->` comment
`first-sprint go/no-go` with `result: go` on a sprint tracker. Trackers are found by a REST list (`issue_rows`,
label `guild:sprint` — never the search API); a found go is cached locally (`first-sprint-go.json`, a cache only —
the source stays GitHub); a read that fails keeps the mode ON (the conservative side).
"""

import json
import os
import re

HIGH_RISK = ("KICKOFF", "STAKES", "EX-ARB:dismiss", "ESCALATE", "SPLIT", "INTEGRATE")
OPTION_KINDS = ("readiness", "disputed-blocker", "loopback")
# the §9.5 group a question's recommendation comes from, by its §2.6 kind (a Question may name `group` itself)
KIND_GROUP = {"readiness": "KICKOFF", "premise": "KICKOFF", "close-decided": "KICKOFF",
              "interpretation-surface": "KICKOFF", "disputed-blocker": "EX-ARB:dismiss",
              "dismiss-blocker": "EX-ARB:dismiss", "leaf-split": "SPLIT", "integration-gap": "INTEGRATE",
              "integration-fix-child": "INTEGRATE", "escalation": "ESCALATE", "design-block": "DE-ARB"}
GO_CACHE = "first-sprint-go.json"


def group_of(q, stage=None):
    g = getattr(q, "group", None) or KIND_GROUP.get(q.kind)
    if g is None and q.kind == "loopback":
        g = "QA" if (stage == "qa" or (q.point or "").endswith(":qa")) else "TEST"
    return g


def _truthy(v):
    return v is True or str(v).strip().lower() in ("1", "true", "on", "yes")


def _common(p):
    return getattr(p, "git_dir", None)


def watch_groups(p):
    c = _common(p)
    if not c:
        return set()
    from workflows.dev import grade as GR
    return set((GR.load_state(c).get("watch") or {}).keys())


def conservative(p, group):
    key = "group.%s.conservative" % group.replace(":", "-")
    return _truthy((getattr(p, "valves", None) or {}).get(key))


def _go_cache(p):
    from guildcore import journal as J
    c = _common(p)
    return os.path.join(J.engine_dir(c), GO_CACHE) if c else None


GO_LINE = re.compile(r"^[ \t]*result:[ \t]*go[ \t]*\r?$", re.M)


def is_go_note(body):
    """K5r3-m7: THE go predicate (predict + grade) — a `<!-- guild:note -->` `first-sprint go/no-go` note whose own
    line reads `result: go` (anchored: `result: go-later` / `result: no-go` / a quote mid-line is not a go)."""
    b = str(body or "")
    return b.startswith("<!-- guild:note -->") and "first-sprint go/no-go" in b and bool(GO_LINE.search(b))


def go_recorded(p):
    """True only when a trusted `first-sprint go/no-go` note with `result: go` exists on a sprint tracker."""
    path = _go_cache(p)
    if path and os.path.exists(path):
        return True
    from guildcore.records import markers
    try:
        rows = p.gh.issue_rows(label="guild:sprint", state="all")
        for r in rows:
            for c in markers.trusted(p.gh.comments(int(r["number"])), ()):
                b = markers.body_of(c)
                if is_go_note(b):
                    if path:
                        from guildcore import journal as J
                        os.makedirs(os.path.dirname(path), exist_ok=True)  # fs-ok: engine cache under <git-common-dir>/guild/engine
                        J.atomic_write(path, json.dumps({"tracker": int(r["number"]), "comment": c.get("id")}))
                    return True
    except Exception:                                            # noqa: BLE001 — unknown = the mode stays on
        return False
    return False


def first_sprint(p):
    """§10.4 first-sprint mode, decided once per Ports (one REST list + tracker reads at most)."""
    cached = getattr(p, "_first_sprint", None)
    if cached is not None:
        return cached
    mode = str(p.engine_cfg("first_sprint_mode", "auto") or "auto").lower()
    on = True if mode == "on" else False if mode == "off" else not go_recorded(p)
    try:
        p._first_sprint = on
    except AttributeError:
        pass
    return on


def forced(p, q, stage=None):
    """The reason this question must be predict-first, or None."""
    g = group_of(q, stage)
    if g in HIGH_RISK:
        return "high-risk"
    if g and conservative(p, g):
        return "conservative"
    if g and g in watch_groups(p):
        return "watch"
    if q.kind in OPTION_KINDS and _truthy(p.cfg("learning.predict_first", False)):
        return "option"
    if first_sprint(p):
        return "first-sprint"
    return None


# K5r3-M1: kinds whose question exists only because the engine proposes one answer — asking it states the
# recommendation (close-decided is asked only when the judge proposes closing), so it is never a blind judgment
INHERENT = {"close-decided": "the question is asked only when the judge proposes closing"}
# words that mark an option as the recommended one
MARKERS = re.compile(r"권장|추천|recommend|\(rec\)|\bchosen\b", re.I)
LABEL_MIN = 6                    # a label shorter than this is too generic to search for (e.g. "go")
LOG_FIELDS = ("reason", "question", "line", "about_to_take")


def canonical(options):
    """K5r3-M1 / r3-m3: a stable order that never depends on the recommendation or on the judge's ranking —
    by label, then token; `stop` last."""
    rest = [o for o in options if o["token"] != "stop"]
    stop = [o for o in options if o["token"] == "stop"]
    return sorted(rest, key=lambda o: (str(o.get("label") or "").casefold(), o["token"])) + stop


def _token_re(tok):
    """K5r4-M1: an option name as a whole word, any case (`I2` names `i2` to a reader; a one-letter id only in
    its own case — `analysis.id_regex`)."""
    from workflows.dev.analysis import id_regex
    return id_regex(tok)


def _strip_enumeration(text, options):
    """An enumeration of EVERY option (`i1 = A | i2 = B`) names the recommendation no more than the others."""
    for o in options:
        text = text.replace("%s = %s" % (o["token"], o.get("label") or ""), " ")
    return text


# K5r4-m6: a text that names every option equally often names none of them — unless it also states a preference
PREFERENCE = re.compile(r"맞아\s*보|맞는\s*것|적절|타당|바람직|나아\s*보|낫|좋아\s*보|유력|아마|것\s*같|가능성이\s*높|"
                        r"\bprefer|\blikely\b|\bbetter\b|\bbest\b|\bshould\b|\bseems?\b|\bappropriate\b|"
                        r"\bcorrect\b|\bsuggest|\bprobably\b|\bpick\b|\bgo with\b", re.I)


class _Names(object):
    """Every name an option goes by — the engine token, the judge's own id (`Question.aliases`), the label (its
    `…`-truncated head too) and the untruncated summary. Short names match as whole words, case-insensitive;
    long ones (≥ LABEL_MIN) as case-insensitive substrings."""

    def __init__(self, q):
        self.q = q
        self.words, self.phrases = {}, {}
        for o in q.options:
            t = o["token"]
            if t == "stop":
                continue
            names = [t] + [str(x) for x in (q.aliases or {}).get(t, []) if x]
            lb = str(o.get("label") or "")
            names.append(lb[:-1].rstrip() if lb.endswith("…") else lb)
            ws, ps = [], []
            for nm in names:
                nm = " ".join(nm.split())
                if not nm or nm == "stop":
                    continue
                if len(nm) >= LABEL_MIN and (" " in nm or len(nm) > 40 or not re.match(r"^[\w.:-]+$", nm)):
                    ps.append(nm.casefold())
                elif re.match(r"^[\w.:-]+$", nm):
                    ws.append(_token_re(nm))
            self.words[t], self.phrases[t] = ws, ps

    def count(self, text, tok):
        t = " ".join(str(text or "").split())
        tf = t.casefold()
        return sum(len(rx.findall(t)) for rx in self.words.get(tok, [])) + \
            sum(tf.count(ph) for ph in self.phrases.get(tok, []))

    def names_rec(self, text, markers=True):
        """True when `text` points at the recommendation: names it more often than some other option, or names
        every option equally but with a preference word, or (`markers`) carries a recommendation marker."""
        rec = self.q.recommended
        t = _strip_enumeration(str(text or ""), self.q.options)
        if markers and MARKERS.search(t):
            return True
        n = self.count(t, rec)
        if not n:
            return False
        others = [self.count(t, o) for o in self.words if o != rec]
        if others and all(c == n for c in others) and not PREFERENCE.search(t):
            return False                                      # a symmetric mention: "범위: i1 vs i2"
        return True


def leak(p, q, stage=None, texts=()):
    """Where the rendered question would show its recommendation, or None. Looks at the question text, the
    context lines, every other text that goes out with it (`texts`: the needs-human line, the pause prose, the
    cause …), the option labels, and the free-text fields this Issue's decision log already shows for the stage
    (a STAKES / KICKOFF `reason` that names the chosen interpretation — r3-m1/m2). K5r4-M1: by every name the
    recommendation goes by (`_Names`); K5r4-m2: a decision log that cannot be read is NOT "nothing shown yet" —
    the log is on GitHub for the person to see, so the blind answer is refused."""
    rec = q.recommended
    if rec is None:
        return None
    nm = _Names(q)
    if nm.names_rec(q.text):
        return "question"
    for t in list(q.context_lines) + [x for x in texts if x]:
        if nm.names_rec(t):
            return "text"
    for o in q.options:
        lb = str(o.get("label") or "")
        if MARKERS.search(lb) or (o["token"] != rec and nm.count(lb, rec)):
            return "options"
    try:
        log = p.decisions._log()
    except Exception:                                            # noqa: BLE001 — K5r4-m2: fail closed
        return "decision-log unreadable"
    for b in log.blocks:
        if stage is not None and b.get("stage") != stage:
            continue
        if b.get("chosen") == rec or (b.get("recommended") == rec and b.get("kind") == q.kind):
            return "decision-log %s" % b.id
        for f in LOG_FIELDS:
            v = b.get(f)
            if v and nm.names_rec(str(v), markers=False):
                if f == "question" and b.get("status") == "pending-human" and b.get("recommended_sha"):
                    continue                                     # an earlier blind question passed this same check
                return "decision-log %s" % b.id
    return None


def swap(q, s):
    """A text that repeated the question's own (non-neutral) wording, with the neutral wording in its place."""
    orig = getattr(q, "original", None)
    if not getattr(q, "neutralized", False) or not orig or not s:
        return s
    return q.text if s == orig else str(s).replace(orig, q.text)


def apply(p, q, stage=None, texts=()):
    """THE predict-first enforcement point (`B.ask` and `B.pause` only). Turns `q.predict_first` on when it is
    forced (records why: `pf_why`); a predict-first question is then rendered from its neutral wording
    (`q.neutral`) with its options in the canonical order, and refused — `blind_refused`, the block carries
    `recommended` openly plus `predict_first_refused` — when the question, its options or any text going out
    with it (`texts`) still shows the recommendation, or when its kind states it by being asked (INHERENT). A
    refused question is never counted as a blind human judgment (§9.5). Returns q."""
    if not q.predict_first and q.recommended is not None:     # nothing to withhold → the answer is blind anyway
        why = forced(p, q, stage)
        if why:
            q.predict_first = True
            q.pf_why = why
    if not q.predict_first or q.recommended is None:
        return q
    if q.neutral and q.text != q.neutral:
        q.original, q.text, q.neutralized = q.text, q.neutral, True
    q.options = canonical(q.options)
    texts = [swap(q, t) for t in texts]
    where = ("inherent: %s" % INHERENT[q.kind]) if q.kind in INHERENT else leak(p, q, stage, texts)
    if where:
        q.predict_first, q.blind_refused = False, "%s (%s)" % (where, q.pf_why or "requested")
        q.pf_why = None
    return q


def sealed(p, value, what):
    """(sha, None) — `value` withheld from a decision block: sha256(value + nonce), the nonce and the value journaled
    first (`predict-first-seal`) so the record can be checked later and never forged after the fact."""
    import hashlib
    if value is None:
        return None
    nonce = os.urandom(8).hex()
    if getattr(p, "journal", None) is not None:
        p.journal.append("event", what="predict-first-seal", field=what, value=value, nonce=nonce)
    return hashlib.sha256((str(value) + nonce).encode("utf-8")).hexdigest()


def kickoff_chosen_fields(p, chosen):
    """KICKOFF is a high-risk group, so any readiness / interpretation question after it is predict-first — and
    its chosen interpretation IS that question's recommendation: the block carries `chosen_sha` (sealed), never
    `chosen`; analyze:output names it once the stage goes on."""
    return {"chosen_sha": sealed(p, chosen, "KICKOFF.chosen")} if chosen is not None else {}
