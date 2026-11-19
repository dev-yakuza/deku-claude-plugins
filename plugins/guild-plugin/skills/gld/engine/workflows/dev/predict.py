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
  withheld    (K5r5-M1, structural) a blind question does not evaluate options at all: everything a person sees
              BEFORE the answer is engine-generated — the neutral template (`Question.neutral`, else
              `default_neutral`) and each option's own summary; the judge's free text (the question it wrote,
              `choice_needed`, context lines, the pause line / prose / cause built from them) is WITHHELD —
              journaled with the nonce and revealed with the recommendation in the answer's resolution block
              (`revealed_question`). The leak check stays as defence in depth: any text still going out that
              mentions the options unevenly (the recommendation 0 times included) or evaluates them (a
              preference OR a negative word) refuses the blind answer.

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
                    inherit_no_dismiss(p, int(r["number"]))
                    return True
    except Exception:                                            # noqa: BLE001 — unknown = the mode stays on
        return False
    return False


def inherit_no_dismiss(p, tracker):
    """§10.4: the go turns first-sprint mode off but `exarb.no_unattended_dismiss` stays — carried by the valve in
    the `auto` area (a person-released valve is not re-applied — `valves.auto_set`). Best effort: a failed write
    leaves the valve unset and is journaled (the first-sprint coercion is then gone — `dev health` shows valves)."""
    c = _common(p)
    if not c:
        return
    from guildcore import valves as VALVES
    try:
        if VALVES.auto_set(c, "exarb.no_unattended_dismiss", True, "first-sprint go on #%d — inherited (§10.4)" % tracker):
            v = getattr(p, "valves", None)
            if isinstance(v, dict):
                v.setdefault("exarb.no_unattended_dismiss", True)
    except Exception as e:                                       # noqa: BLE001
        if getattr(p, "journal", None) is not None:
            p.journal.append("event", what="no-dismiss-inherit-failed", why=str(e)[:200])


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
# (or, K5r5-M1, a negative judgment: "i1 은 맞지 않음" eliminates i1, which recommends the rest)
PREFERENCE = re.compile(r"맞아\s*보|맞는\s*것|적절|타당|바람직|나아\s*보|낫|좋아\s*보|유력|아마|것\s*같|가능성이\s*높|"
                        r"\bprefer|\blikely\b|\bbetter\b|\bbest\b|\bshould\b|\bseems?\b|\bappropriate\b|"
                        r"\bcorrect\b|\bsuggest|\bprobably\b|\bpick\b|\bgo with\b", re.I)
NEGATIVE = re.compile(r"아니|않|못\s*하|약하|약함|부족|틀리|틀림|어긋|맞지|무리|부적절|과도|너무|어렵|의심|배제|제외|"
                      r"\bnot\b|n't\b|\bunlikely\b|\bless\b|\bweak|\bwrong\b|\bpoor|\btoo\b|\bworse\b|"
                      r"\bbad\b|\brule[sd]? out\b|\bexclude", re.I)


# K5r6-M2: likelihood / ranking language (an option label that says how likely or how good it is) — ko / ja / en
LIKELIHOOD = re.compile(r"가능성|가장|제일|최선|최적|잘\s*맞|자연스럽|분명|명백|당연|확실|의도된|의도한|"
                        r"可能性|おすすめ|オススメ|推奨|最適|最善|最も|一番|妥当|適切|望ましい|ベスト|らしい|と思われ|"
                        r"ではない|じゃない|自然|明らか|"
                        r"\bmost\b|\bleast\b|\bbest\b|\bobvious|\bclearly\b|\bplausib|\bimplausib|\bdoubt|"
                        r"\bideal\b|\boptimal\b|\breasonabl|\bsensibl|\bnatural(?:ly)?\b|\bsafe(?:r|st)\b|"
                        r"\bintended\b|\bpreferred\b|\brecommend", re.I)


# the NEGATIVE words that rate (not the plain negation a summary may describe with: 않 / not / 제외 …)
NEG_RATING = re.compile(r"약하|약함|부족|틀리|틀림|어긋|맞지|무리|부적절|과도|너무|의심|"
                        r"\bunlikely\b|\bweak|\bwrong\b|\bpoor|\btoo\b|\bworse\b|\bbad\b", re.I)


# K5r7-m2: fit / match language — a label that says how well its option agrees with the Issue ("matches the title",
# "제목과 어울리지 않음", "タイトル通り", "a stretch", "근거 없음") rates it as surely as a likelihood word does
_SRC_KO = r"(?:제목|본문|요청|이슈|설명|보고)"
_SRC_JA = r"(?:タイトル|本文|要望|依頼|説明|イシュー|報告)"
_SRC_EN = r"(?:the\s+)?(?:title|issue|request|body|description|report|ask|reporter)"
# K5r8-m3: a source word or a lone `근거` / `根拠` / `素直` / `typical` / `literal` is not a rating by itself
# ("근거 자료 링크 추가", "본문 그대로 표시", "タイトル通りに表示", "Literal string search", "Match title case") — only
# with an evaluative tail (근거 없음 · 根拠が薄い) or as a reading of the Issue ("typical reading", "제목과 일치")
_EN_NOUN = r"(?!\s+(?:case|style|format|font|layout|bar|text|colou?r|size|field|page|screen|row|column)s?\b)"
_EVAL_KO = r"\s*(?:이|가|은|는)?\s*(?:없|부족|약하|약함|희박|박약|충분|있음|있다|있는|분명|명확|빈약|약한)"
_EVAL_JA = r"\s*(?:が|は)?\s*(?:薄|弱|乏し|な[いし]|無[いし]|十分|ある|あり|明確|不十分)"
FIT = re.compile(_SRC_KO + r"\s*(?:과|와|에|이|의|에서)?\s*(?:일치|불일치|어울리|부합|들어맞|맞|그대로(?=\s*(?:$|[)）\],、，;；.])))|"
                 r"근거" + _EVAL_KO + r"|" + _SRC_KO + r"\s*(?:에|을|를)?\s*근거|억지|무난|합리|"
                 + _SRC_JA + r"\s*(?:と|に|の)?\s*(?:(?:通り|どおり)(?!に)|合う|合わ|沿う|沿った|沿わ|一致)|"
                 r"根拠" + _EVAL_JA + r"|" + _SRC_JA + r"\s*(?:を|に)?\s*根拠|素直(?:な|に)?\s*(?:解釈|読|受け取)|無理|"
                 r"(?:\bmatch(?:es|ing)?|\bfits?|\bconsistent with|\binconsistent with|\bin line with|\bsupported by|"
                 r"\bfollows)\s+" + _SRC_EN + r"\b" + _EN_NOUN + r"|\bmismatch|\bstretch\b|\bas asked\b|\basked for\b|"
                 r"\b(?:typical(?:ly)?|literal(?:ly)?)\s+(?:reading|interpretation|meaning|intent|choice|read)\b|"
                 r"\b(?:read|taken|interpreted)\s+(?:literally|typically)\b|"
                 r"\b(?:does|do|did)\s*(?:not|n't)\s+(?:mention|say|support|ask)", re.I)


def evaluative(text):
    return bool(PREFERENCE.search(text) or NEGATIVE.search(text) or LIKELIHOOD.search(text) or FIT.search(text))


def rates(label):
    """K5r6-M2: does an option label rate its option (how likely / good / fitting)? — preference, likelihood and
    rating words; a plain negation that describes the option ("설정 화면은 바꾸지 않는다") is not a rating."""
    t = str(label or "")
    return bool(PREFERENCE.search(t) or LIKELIHOOD.search(t) or NEG_RATING.search(t) or FIT.search(t))


_CLAUSE = re.compile(r"\s*[(（\[][^)）\]]*[)）\]]|\s*(?:—|–|--| - |;|；|:|：|,|、|，)[^—–;；:：,、，(（]*")


def neutral_label(label):
    """K5r6-M2: an option label as the engine shows it blind — the judge's summary with every evaluative clause (a
    parenthesis, a dash / colon / comma tail that rates the option) cut. None when what is left still evaluates
    (or nothing is left): the blind answer is then refused."""
    lb = str(label or "")
    if not rates(lb):
        return lb
    out = _CLAUSE.sub(_cut, lb).strip(" —–-;:,、")
    if not out or rates(out):
        return None
    return out


_PAREN = re.compile(r"^(\s*)([(（\[])([^)）\]]*)([)）\]])$")
_COMMA = re.compile(r"\s*[,、，;；]\s*")


def _cut(m):
    """One clause of a label: kept when it does not rate. K5r7-m2(b): a parenthesis is cut by its comma clauses —
    `(앱 전체, 가능성 높음)` keeps `(앱 전체)` (cutting it whole made two labels the same)."""
    c = m.group(0)
    if not rates(c):
        return c
    pm = _PAREN.match(c)
    if not pm:
        return ""
    keep = [x for x in _COMMA.split(pm.group(3)) if x.strip() and not rates(x)]
    return "%s%s%s%s" % (pm.group(1), pm.group(2), ", ".join(keep), pm.group(4)) if keep else ""


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
        """True when `text` evaluates the options — K5r5-M1: ANY uneven mention (some option named more often than
        another — the recommendation named 0 times included: "i1 은 맞지 않음" eliminates i1), or an even mention with
        a preference or negative word, or (`markers`) a recommendation marker. An even, plain enumeration
        ("범위: i1 vs i2") is neutral."""
        t = _strip_enumeration(str(text or ""), self.q.options)
        if markers and MARKERS.search(t):
            return True
        counts = [self.count(t, o) for o in self.words]
        if not any(counts):
            return False
        if len(set(counts)) > 1:
            return True                                       # uneven: one option singled out (for or against)
        return evaluative(t)


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
        # K5r5-M1: a label is the option's own summary — naming ANOTHER option is a comparison
        if MARKERS.search(lb) or any(nm.count(lb, t) for t in nm.words if t != o["token"]):
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


def default_neutral(p, q):
    """K5r5-M1: the engine's own wording of a blind question — the Issue and the kind, nothing the judge wrote."""
    return "#%d: %s — 어느 선택지로 진행할까요?" % (int(getattr(p, "issue", 0) or 0), q.kind)


def enumeration(q):
    """The engine's option list (canonical order) — the only prose a blind pause shows."""
    return "선택지: " + " | ".join("%s = %s" % (o["token"], o.get("label") or o["token"])
                                   for o in q.options if o["token"] != "stop")


def swap(q, s):
    """K5r5-M1: once a question is blind (`withheld`), any text that goes out with it is the neutral wording —
    never the judge's free text (revealed after the answer)."""
    if not getattr(q, "neutralized", False) or not s:
        return s
    return q.text


def withheld_text(q):
    from guildcore import ask as ASK
    return ASK.withheld_text(q)


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
    # K5r5-M1 (structural): the person sees only engine-generated text before answering — the neutral template and
    # the options' own summaries; the judge's text is withheld (journaled, revealed after the answer)
    extra = list(getattr(p, "__dict__", {}).pop("_withheld_next", None) or [])     # K5r6-m7: STAKES reasons
    q.withheld = {"question": q.text, "context": list(q.context_lines), "texts": [t for t in texts if t] + extra}
    q.original, q.text, q.neutralized = q.text, (q.neutral or default_neutral(p, q)), True
    q.context_lines = []
    # K5r6-M2: the labels are the judge's summaries — blind, the engine shows them without their evaluative clauses
    # (`neutral_label`); a label that still evaluates refuses the blind answer
    q.withheld["labels"] = [dict(o) for o in q.options]
    where = None
    opts = []
    for o in q.options:
        if o["token"] == "stop":
            opts.append(o)
            continue
        nl = neutral_label(o.get("label"))
        if nl is None:
            where = "label-evaluative %s" % o["token"]
            nl = o.get("label")
        opts.append(dict(o, label=nl))
    q.options = canonical(opts)
    # K5r7-m2(b): blind labels must still tell the options apart — two the same (or empty) after the cut refuse
    if where is None:
        seen = set()
        for o in q.options:
            if o["token"] == "stop":
                continue
            k = re.sub(r"\s+", " ", str(o.get("label") or "")).strip().lower()
            if not k or k in seen:
                where = "label-indistinct %s" % o["token"]
                break
            seen.add(k)
    # K5r6-M2(a): with one real option (`i1 | stop`) the answer is no judgment between interpretations — it stays
    # blind but is never counted as one (§9.5 / §10.2-6 releases read only counted answers)
    if len([o for o in q.options if o["token"] != "stop"]) < 2:
        q.uncounted = "one real option"
    texts = [swap(q, t) for t in texts]
    if q.kind in INHERENT:
        where = "inherent: %s" % INHERENT[q.kind]
    elif where is None:
        where = leak(p, q, stage, texts)
    if where:
        q.predict_first, q.blind_refused = False, "%s (%s)" % (where, q.pf_why or "requested")
        q.pf_why = None
        # not blind → nothing is withheld: the judge's own wording goes out with the recommendation shown openly
        q.text, q.context_lines, q.neutralized = q.original, list(q.withheld["context"]), False
        q.options = canonical(q.withheld["labels"])
        q.withheld = None
        q.uncounted = None
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
