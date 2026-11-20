"""workflows.dev.predict — when a human question is predict-first (design §2.6 `predict_first`, R5J-M4, §9.5, §10.4).

A question is predict-first — the person answers BEFORE seeing the engine's recommendation — when any of these holds
(`forced(p, q)` returns the first reason, or None):

    high-risk      the question comes from a §9.5 high-risk group (EX-ARB:dismiss · ESCALATE · SPLIT · INTEGRATE) —
                   always
    conservative   `group.<g>.conservative` is in force (a valve — the §9.5 count rule or a person)
    watch          the group is on the §9.5 watch list (`grade-state.json`)
    option         `config.learning.predict_first: true` and the kind is readiness · disputed-blocker · loopback
    first-sprint   first-sprint mode (§10.4): `config.engine.first_sprint_mode` on, or auto with no recorded go

Only these answers count as a human judgment in §9.5 (G1, graduation, release). What it changes:
  attended    the `ask` event carries no recommendation; the pending block carries `recommended_sha` only; the
              answer's resolution block reveals `recommended` + `nonce` (`dev answer` prints the reveal)
  unattended  the pause comment shows evidence, question, options and the reasons — never the token; the pending
              block carries `recommended_sha`; the nonce is journaled BEFORE the commitment is written (crash-safe)
  open        (user decision 2026-11-20, K6 r4 — scope reduction) KICKOFF and STAKES (`OPEN_GROUPS`) are never
              predict-first: their questions are asked with the recommendation shown, marked
              `predict_first_counted: false — open: …`, and the groups are released by the person's grading-sheet
              verdicts on those decisions (`unverified.SHEET_RELEASED`, `grade.inherent_row`) like the INHERENT gates
  wording     (K5r3-M1) the question is rendered from its neutral wording (`Question.neutral`), options in the
              canonical order (label, token; `stop` last); `apply` — the one enforcement point — REFUSES a blind
              answer (`predict_first_refused`, recommendation shown openly, never a §9.5 human judgment) when the
              question, its options, the text going out with it or this stage's decision-log free text names the
              recommendation, or when the kind states it by being asked (close-decided)
  names       (K5r4-M1/m6) an option goes by its engine token, the judge's own id (`Question.aliases` — KICKOFF's
              `I2` / `B` / `broad`, which `analysis.to_tokens` also rewrites to the token in the judge's text) and
              its full summary; whole words, case-insensitive. A text naming every option equally often, with no
              preference word, is neutral; an unreadable decision log refuses (K5r4-m2 — fail closed)
  withheld    (K5r5-M1, structural) a blind question does not evaluate options at all: everything a person sees
              BEFORE the answer is engine-generated — the neutral template (`Question.neutral`, else
              `default_neutral`) and each option's own summary; the judge's free text (the question it wrote,
              `choice_needed`, context lines, the pause line / prose / cause built from them) is WITHHELD —
              journaled with the nonce and revealed with the recommendation in the answer's resolution block
              (`revealed_question`). (K6, r12 m2 — corrected) On the operating path `apply` empties the context
              and swaps every outgoing text for the template, so the question / text checks of `leak` see the
              template only — and a REGISTERED template (`NEUTRAL_FORMS`, K6 item 44) is never counted. What still
              defends in depth: the option LABELS (judge summaries — evaluative clauses cut, a label naming another
              option or still rating refuses), this stage's decision-log free text on GitHub (`LOG_FIELDS`), and a
              `neutral` that is not a registered wording (counted like any text — the slot check of
              `neutral_text` keeps judge phrases out of the template itself).

First-sprint "auto" ends only on a recorded go (§10.4, R4C-m9): a trusted `<!-- guild:note -->` comment
`first-sprint go/no-go` with `result: go` on a sprint tracker. Trackers are found by a REST list (`issue_rows`,
label `guild:sprint` — never the search API); a found go is cached locally (`first-sprint-go.json`, a cache only —
the source stays GitHub); a read that fails keeps the mode ON (the conservative side).
"""

import json
import os
import re

HIGH_RISK = ("EX-ARB:dismiss", "ESCALATE", "SPLIT", "INTEGRATE")
# user decision 2026-11-20 (K6 r4 — scope reduction): these groups leave predict-first blind counting — asked openly,
# never a counted blind answer, released by the person's grading-sheet verdicts on their decisions
OPEN_GROUPS = {
    "KICKOFF": "the interpretation question is asked openly (user decision 2026-11-20) — released by grading-sheet "
               "verdicts on the engine's readings",
    "STAKES": "the stakes question is asked openly (user decision 2026-11-20) — released by grading-sheet verdicts on "
              "the engine's levels",
}
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
    """`group.<g>.conservative` in force (a valve), or — K6 item 4 — `g` is a §10.2-6 unverified group not yet
    released (`p.unverified`, read once per run by the live Ports — `workflows.dev.unverified`)."""
    key = "group.%s.conservative" % group.replace(":", "-")
    if _truthy((getattr(p, "valves", None) or {}).get(key)):
        return True
    return group.replace(":", "-") in (getattr(p, "unverified", None) or ())


def conservative_source(p, group):
    """K6 r1 M6: why `group` is on the conservative path — "valve" (`group.<g>.conservative` in force: a person or the
    §9.5 count rule set it), "unverified" (§10.2-6, not released yet — no valve exists to clear), or None."""
    key = "group.%s.conservative" % group.replace(":", "-")
    if _truthy((getattr(p, "valves", None) or {}).get(key)):
        return "valve"
    if group.replace(":", "-") in (getattr(p, "unverified", None) or ()):
        return "unverified"
    return None


def conservative_label(p, group):
    """The engine's words for that source — what a person can act on (K6 r1 M6: never a valve name that is not set)."""
    g = group.replace(":", "-")
    src = conservative_source(p, group)
    if src == "unverified":
        from workflows.dev import unverified as UV
        if g in UV.SHEET_RELEASED:
            # K6 r2 M1: released by the person's grading-sheet verdicts (`dev grade`), never by the blind answers
            return ("unverified %s (§10.2-6: released after the person's grading-sheet verdicts on its decisions — "
                    "`dev grade`; `dev health` shows the count)" % g)
        return "unverified %s (§10.2-6: released after its human verdicts — `dev health` shows the count)" % g
    return "group.%s.conservative" % g


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
    """The reason this question must be predict-first, or None (never for an OPEN_GROUPS question)."""
    g = group_of(q, stage)
    if g in OPEN_GROUPS:
        return None
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
LIKELIHOOD = re.compile(r"가능성|가장|제일|최선|최적|잘\s*맞|자연스러|자연스럽|분명|명백|당연|확실|의도된|의도한|"
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
# K5r9-m1: an as-is reading of the SOURCE is fit language as a phrase — source + 그대로/通り + reading / scope / build
# ("제목 그대로 해석", "요청 그대로의 범위", "タイトル通りに解釈") — never `그대로 표시` / `通りに表示` (a display, r8 m3)
_AS_IS_KO = r"그대로\s*(?:의\s*)?(?:해석|읽|이해|받아들|범위|구현|반영)"
_AS_IS_JA = r"(?:の\s*)?(?:解釈|読|理解|受け取|範囲|実装)"
_EN_NOUN = r"(?!\s+(?:case|style|format|font|layout|bar|colou?r|size|field|page|screen|row|column)s?\b)"
_EVAL_KO = r"\s*(?:이|가|은|는)?\s*(?:없|부족|약하|약함|약해|희박|박약|충분|있음|있다|있는|분명|명확|빈약|약한)"
_EVAL_JA = r"\s*(?:が|は)?\s*(?:薄|弱|乏し|な[いし]|無[いし]|十分|ある|あり|明確|不十分)"
FIT = re.compile(_SRC_KO + r"\s*(?:과|와|에|이|의|에서)?\s*(?:일치|불일치|어울리|부합|들어맞|맞|그대로(?=\s*(?:$|[)）\],、，;；.]))|"
                 + _AS_IS_KO + r")|"
                 r"근거" + _EVAL_KO + r"|근거\s*[:：]|" + _SRC_KO + r"\s*(?:에|을|를)?\s*근거|억지|무난|합리|"
                 + _SRC_JA + r"\s*(?:と|に|の)?\s*(?:(?:通り|どおり)(?!に)|(?:通り|どおり)に?\s*" + _AS_IS_JA + r"|合う|合わ|沿う|沿った|沿わ|一致)|"
                 r"根拠" + _EVAL_JA + r"|根拠\s*[:：]|" + _SRC_JA + r"\s*(?:を|に)?\s*根拠|素直(?:な|に)?\s*(?:解釈|読|受け取)|無理|"
                 r"(?:\bmatch(?:es|ing)?|\bfits?|\bconsistent with|\binconsistent with|\bin line with|\bsupported by|"
                 r"\bfollows)\s+" + _SRC_EN + r"\b" + _EN_NOUN + r"|\bstretch\b|\bas asked\b|\basked for\b|"
                 # K6 item 29: `mismatch` only against a source (a bare `mismatch` is a domain word — account
                 # mismatch — in 3 of 377 real AC lines); the r10 m5 paraphrases (faithful / beyond / departs …)
                 r"\bmismatch(?:es|ed)?\s+(?:with|to)\s+" + _SRC_EN + r"\b|" + _SRC_EN + r"\s+mismatch|"
                 r"\baligns?\s+with\s+" + _SRC_EN + r"\b|\bfaithful\b|\bgoes\s+beyond\b|\bbeyond\s+" + _SRC_EN +
                 r"\b|\bstrict\s+reading\b|\bliteral\s+take\b|\bdepart(?:s|ed|ing)?\s+from\s+" + _SRC_EN + r"\b|"
                 r"충실|벗어(?:난|나)|(?:확대|축소|과대|과소)\s*해석|상통|취지(?:에|와|를)?\s*(?:부합|맞|어긋|벗어|충실)|"
                 r"文字通り|忠実|(?:から|を)\s*(?:は)?\s*外れ|食い違|"
                 r"\b(?:typical(?:ly)?|literal(?:ly)?)\s+(?:reading|interpretation|meaning|intent|choice|read|sense|scope|case)\b|"
                 r"\b(?:read(?:ing)?|tak(?:en|e|es|ing)|took|interpret(?:ed|ing)?)\s+(?:" + _SRC_EN + r"\s+)?(?:literally|typically)\b|"
                 r"\b(?:does|do|did)\s*(?:not|n't)\s+(?:mention|say|support|ask)", re.I)


def evaluative(text):
    return bool(PREFERENCE.search(text) or NEGATIVE.search(text) or LIKELIHOOD.search(text) or FIT.search(text))


# K6 r3 m1: a number / symbol that RATES — a percentage, a score `9/10`, stars, check / cross marks, a letter grade
# with a sign (`A+`, `B-`), a rank (`#1` alone, `1st`, `1위`, `1位`) — never a scope, whatever the word lists say
NUM_RATING = re.compile(r"\d+(?:[.,]\d+)?\s*[%％]|(?<![\w./])\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?(?![\w./])|"
                        r"[★☆⭐✓✔✗✘○◎△◯●❌✅👍👎]|(?<![A-Za-z0-9_])[A-F][+\-]{1,2}(?![A-Za-z0-9_])|"
                        r"(?<![\w#])\d+(?:st|nd|rd|th)\b|\d+\s*(?:위|등|位|番目)|"
                        r"(?:^|\s)#\d{1,2}(?:\s|$)|\b(?:rank|top|tier)\s*-?\s*\d+\b|\bP[0-4]\b", re.I)


_PROB = re.compile(r"\b(?:p|prob(?:ability)?|score|conf(?:idence)?|likelihood|rank|rating)\s*[=:]\s*\d", re.I)


def num_rating(text):
    """K6 r3 m1: does `text` (outside its code spans) carry a numeric / symbolic rating (`NUM_RATING`)?"""
    return bool(NUM_RATING.search(_CODE_SPAN.sub(" ", str(text or ""))))


def rates(label):
    """K5r6-M2: does an option label rate its option (how likely / good / fitting)? — preference, likelihood and
    rating words; a plain negation that describes the option ("설정 화면은 바꾸지 않는다") is not a rating. K6 r3 m1:
    a numeric / symbolic rating (`num_rating`: `90%`, `9/10`, `★★★`, `✓`, `A+`, `#1`) rates too."""
    t = str(label or "")
    return bool(PREFERENCE.search(t) or LIKELIHOOD.search(t) or NEG_RATING.search(t) or FIT.search(t)
                or num_rating(t))


_CLAUSE = re.compile(r"\s*[(（\[][^)）\]]*[)）\]]|\s*(?:—|–|--| - |;|；|:|：|,|、|，)[^—–;；:：,、，(（]*")


# K6 r1 M4 (structural — three review rounds found new evaluative paraphrases the word lists missed): an ASIDE is
# never shown blind as written — every parenthesis / bracket (an unclosed one, cut by the one-line cap, to the end)
# and every spaced-dash tail.
# K6 r2 M3: but an aside is also where a summary states its SCOPE ("(설정 화면 제외)", "— iOS 만", "(soft delete, keep
# audit log)", "（パスワード再設定は対象外）") — cut, the label shows a scope the token does not run (the person's
# token runs the full interpretation: `apply_choice` parity holds for the token, not for the meaning). Each clause of
# an aside (and of a tail `blind_labels` would drop) is now one of:
#   REMARK  rates (`rates`) or speaks of the source / the reading (`_REMARK_REF`: title, request, intent, reading,
#           evidence …) — cut, as r1 (no execution meaning; where the paraphrases live);
#   SCOPE   a limitation / exclusion / inclusion / negation (`_SCOPE`) that does not rate — KEPT (shown blind);
#           a scope clause that also rates cannot be shown or dropped → the blind answer is refused;
#   OTHER   anything else ("(admin)", "(web)", "(narrow but safe)", "(최소 범위)") — whether it changes what runs
#           is unknown to the engine: never dropped silently, never shown → the blind answer is refused (shown
#           openly, never counted — `aside_split` → None).
# The shown label therefore names everything the token runs that the summary said, or the question is not blind.
_ASIDE = re.compile(r"\s*[(（\[【][^)）\]】]*(?:[)）\]】]|$)|\s+(?:—|–|--|-)\s+.*$|\s*—.*$")
_SCOPE = re.compile(r"제외|빼고|말고|(?:\S)만(?=$|\s|[)）\]】,.、])|(?:^|\s)만(?=$|\s)|뿐|한정|이외|외에는|전용|없이|유지|남기|남김|"
                    r"금지|않|미포함|불포함|포함|까지|부터|단독|전체|모든|일부|"
                    r"対象外|除く|除き|除外|のみ|だけ|限定|以外|しない|せず|含む|含め|含まない|維持|残す|保持|全体|全て|すべて|一部|まで|"
                    r"\bonly\b|\bexcept|\bexclud|\bwithout\b|\bnever\b|\bnot\b|n't\b|\bno\b|\bkeep|\bkept\b|\bretain|"
                    r"\bpreserv|\binclud|\bincl\.|\ball\b|\bwhole\b|\bentire|\bevery\b|\bpartial|\bsoft\b|\bhard\b|"
                    r"\bread-only\b|\blimited\b|\bsolely\b", re.I)
# K6 r3 M3: a REMARK speaks of the Issue / the reading. Two strengths:
#   READING  the reading itself (intent · interpretation · "asks" · "says" · wording · literal …) — a remark even inside
#            a scope clause ("only what the request asks" → neither shown nor dropped: refused);
#   SOURCE   a reference TO the Issue's text ("the request", "the title", "requested", "제목이 말하는", "요청대로",
#            "タイトル通り") — a remark only when the clause states no scope: a scope word wins over it.
# The bare product nouns the source is made of (제목 · 본문 · 설명 · 이슈 · 요청 · title · body · description · issue ·
# request · タイトル · 本文 · 依頼 …) are an app's everyday domain nouns too (a post's 본문, an issue tracker's issue, API
# requests) and are no remark by themselves: "(본문 편집기 제외)", "(write requests only)", "（依頼通知のみ）" are scope
# clauses and shown; "(셸 주석에 이슈번호가 있으면 게이트가 차단)" is neither → refused, never cut.
_REMARK_REF = re.compile(r"의도|취지|해석|근거|문구|뜻하|말하는|원한|원하는|읽(?!기\s*전용)|"
                         r"趣旨|意図|解釈|読み(?!取り専用|込み)|読む|根拠|文言|"
                         r"\bintent|\bmeant\b|\breading\b|\breads\b|\binterpret|\bevidence\b|\bbasis\b|"
                         r"\bask(?:ed|s)?\b|\bsays?\b|\bsaid\b|\bmention|\bwritten\b|\bwording\b|\bliteral", re.I)
_SOURCE_REF = re.compile(r"(?:제목|본문|요청|이슈|설명|보고)\s*(?:이|가|은|는|에서|에|과|와|의)?\s*"
                         r"(?:말하|요구|원하|적힌|적은|쓰인|명시|언급|범위|그대로|대로|기준|따르|따른|맞)|"
                         r"요청(?:한|된|받은|하는)|요청자|작성자|보고자|"
                         r"(?:제목|본문|요청|이슈|설명)\s*(?:과|와)\s*(?:거리|다르|다름|어긋|일치|들어|가깝|멀)|"
                         r"依頼者|要望者|報告者|起票者|"
                         r"(?:タイトル|本文|依頼|要望|説明|イシュー)\s*(?:が|の)?\s*(?:示|求め)|"
                         r"(?:タイトル|本文|依頼|要望|説明|イシュー)\s*と\s*(?:ずれ|違|異な|一致|合)|"
                         r"(?:タイトル|本文|依頼|要望|要求|説明|イシュー|報告)\s*(?:の|に|が|で)?\s*"
                         r"(?:範囲|通り|どおり|沿|記載|書|言)|"
                         # K6 r4 M3: "the issue" before a product noun ("the issue body", "the request body") is that
                         # noun, not a reference to the Issue's text
                         r"\bthe\s+(?:title|issue|ticket|request|body|description|report|reporter|author)\b"
                         r"(?!\s+(?:body|title|field|list|number|tracker|page|screen|editor|comment|label|header)s?\b)|"
                         # K6 r4 M3: a scope set BY the source — "title scope", "제목에 있는 것", "제목에 없는 화면"
                         r"\b(?:title|issue|ticket|request|description)['’]?s?\s+(?:scope|wording|text)\b|"
                         r"(?:제목|요청|이슈|설명)\s*에\s*(?:있는|없는|나온|적힌|들어간)\s*(?:것|부분|범위|화면|내용|기능)|"
                         r"\b(?:requested|described|reported|titled)\b|"
                         r"\bper\s+(?:the\s+)?(?:title|issue|ticket|request|body|description)\b", re.I)
_NEGATION = re.compile(r"않|없이|아니|n't|not|no|never|しない|せず", re.I)   # a scope match that only negates
_CLAUSES = re.compile(r"\s*[,、，;；]\s*")
_CLOSE = {"(": ")", "（": "）", "[": "]", "【": "】"}


_CODE_SPAN = re.compile(r"`[^`]*(?:`|$)")
# K6 r3 m5: a code span is never cut into — its brackets, commas, colons and dashes (`Get.back()`, `jq '.[]'`,
# `foo(a, b)`) are masked to private-use characters while the asides / clauses are found, and restored after
_MASK_SRC = "()（）[]【】,、，;；:：—–-"
_MASK = dict((c, chr(0xE000 + n)) for n, c in enumerate(_MASK_SRC))
_UNMASK = dict((v, k) for k, v in _MASK.items())


def _mask(s):
    return _CODE_SPAN.sub(lambda m: "".join(_MASK.get(c, c) for c in m.group(0)), str(s or ""))


def _unmask(s):
    return s if not s else "".join(_UNMASK.get(c, c) for c in s)


_LIT_TOKEN = re.compile(r"[A-Za-z0-9_./#:+\-~%$<>=!*·↔→&|@]+")


def _literal(t):
    """K6 r2 M3: a clause made only of code spans, paths, identifiers, versions (`_runAutoSync`, `v2.0`, `CSV`,
    `iOS/Android`, `status: 401`) — no natural-language word that could rate: shown as it is. K6 r3 m1: at least one
    code span or LETTER-bearing identifier; numbers, `%`, stars, checks, grades and ranks alone (`(90%)`, `(#1)`,
    `(★★★)`, `(✓)`, `(9/10)`, `(A+)`, `(C)`) are no literal (and `num_rating` refuses them first)."""
    ident = bool(_CODE_SPAN.search(t))
    rest = _CODE_SPAN.sub(" ", t)
    for w in rest.split():
        w = w.strip("'\"“”‘’()[]{}.,;")
        if not w or re.match(r"^[-–—/·,;:.|&+]+$", w):
            continue
        if re.match(r"^[0-9.,:]+$", w):
            continue                                     # a bare number next to an identifier (`status: 401`)
        if _LIT_TOKEN.fullmatch(w) and re.search(r"[A-Za-z]", w) and \
                (re.search(r"[0-9_./#:+$<>=*·↔→&|@]", w) or re.search(r"[a-z][A-Z]", w) or re.match(r"^[A-Z]{2,}s?$", w)):
            ident = True
            continue
        return False
    return ident


def clause_kind(text):
    """K6 r2 M3: "remark" | "scope" | "scope-rating" | "other" for one clause of an aside / a dropped tail.
    K6 r3: the order is (1) a numeric / symbolic rating (`num_rating`) → refused ("scope-rating" with a scope word,
    else "other" — never cut silently, never shown); (2) a rating word (`rates`) → "scope-rating" with a scope word,
    else "remark" (cut); (3) a literal (`_literal`) → "scope" (shown); (4) a SCOPE word wins over a product noun —
    "scope", unless it also speaks of the reading (`_REMARK_REF`: "only what the request asks") → "other"; (5) a
    reading remark or a reference to the source (`_SOURCE_REF`) → "remark"; (6) anything else → "other"."""
    t = _unmask(str(text or "")).strip()
    if not t:
        return "remark"
    bare = _CODE_SPAN.sub(" ", t)
    sc = bool(_SCOPE.search(bare))
    spans = _CODE_SPAN.findall(t)
    if spans and not bare.strip(" ()（）[]【】"):
        # K6 r4 m4: a clause made of code spans only — a number inside one still rates (`(`90%`)`, `(`p=0.9`)`), and a
        # bare number (`(`0.9`)`, `(`2`)`) is no identifier: refused, never shown as a literal (a line reference
        # `(`:3180-3218`)` stays a literal)
        inner = [x.strip("`").strip() for x in spans]
        if any(NUM_RATING.search(x) or _PROB.search(x) or re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", x) for x in inner):
            return "other"
    if num_rating(t):
        return "scope-rating" if sc else "other"
    if FIT.search(bare) and all(_NEGATION.fullmatch(m.group(0).strip()) for m in _SCOPE.finditer(bare)):
        return "remark"          # "(제목과 어울리지 않음)", "(the title does not mention login)": a fit remark, negated
    if rates(bare):
        return "scope-rating" if sc else "remark"
    if _literal(t):
        return "scope"
    ref = bool(_REMARK_REF.search(bare))
    src = bool(_SOURCE_REF.search(bare))
    if sc:
        # K6 r4 M3: a scope set BY the source ("(제목 범위만)", "(per the title only)", "(only what the title names)",
        # "(requested screen only)") is a faithfulness remark AND a scope — neither shown nor dropped: refused
        return "other" if ref or src else "scope"
    return "remark" if ref or src else "other"


def _kept_clauses(inner):
    """(kept clauses, refuse?) of one aside's / tail's text."""
    kept, refuse = [], False
    for c in _CLAUSES.split(inner):
        k = clause_kind(c)
        if k == "scope":
            kept.append(c.strip())
        elif k != "remark":
            refuse = True
    return kept, refuse


def aside_split(label):
    """K6 r2 M3: (the label with each aside reduced to its SCOPE clauses — remarks cut — , refuse?) — refuse when an
    aside holds a clause that can be neither shown nor dropped (`clause_kind` other / scope-rating)."""
    lb = _mask(label)
    refuse = [False]

    def one(m):
        seg = m.group(0)
        st = seg.lstrip()
        lead = seg[:len(seg) - len(st)]
        if st[:1] in _CLOSE:
            close = st[-1] if st[-1:] in _CLOSE.values() else ""
            inner = st[1:len(st) - len(close)] if close else st[1:]
            kept, bad = _kept_clauses(inner)
            refuse[0] = refuse[0] or bad
            return ("%s%s%s%s" % (lead, st[0], ", ".join(kept), close or _CLOSE[st[0]])) if kept else ""
        dm = re.match(r"(—|–|--|-)\s*(.*)$", st, re.S)
        dash, inner = (dm.group(1), dm.group(2)) if dm else ("—", st)
        kept, bad = _kept_clauses(inner)
        refuse[0] = refuse[0] or bad
        return (" %s %s" % (dash, ", ".join(kept))) if kept else ""
    out = _ASIDE.sub(one, lb).strip(" —–-;:,、")
    return _unmask(out), refuse[0]


def aside_cut(label):
    """The label with its asides reduced (remarks cut, scope clauses kept — K6 r2 M3); see `aside_split`."""
    return aside_split(label)[0]


_HEAD_SPLIT = re.compile(r"\s*(?:[,、，;；]|[:：](?=\s|$))\s*")


def blind_labels(labels):
    """K6 r1 M4: the labels of one blind question, as shown — each `neutral_label`; then, when the HEADS (each label up
    to its first comma / colon / semicolon) still tell every option apart and none rates, only the heads: the least
    that distinguishes the options is all a blind question needs, and a tail is where a summary drifts into a remark
    the word lists do not know. K6 r2 M3: a tail is dropped only when every clause of it is a remark; a scope clause
    stays with its head ("Retry failed uploads, but never on 4xx"), and a tail clause that can be neither shown nor
    dropped refuses that label. Returns [label or None (refused)]."""
    # a recommendation MARKER (권장 · recommend · (rec) …) is the judge naming its pick — never cut away silently:
    # the label stays as written so the leak check refuses the blind answer (K5r3-M1)
    nl = [(str(x or "") if MARKERS.search(str(x or "")) else neutral_label(x)) for x in labels]
    if any(MARKERS.search(str(x or "")) for x in labels):
        return nl
    if any(x is None for x in nl):
        return nl
    parts = [_HEAD_SPLIT.split(_mask(x), 1) for x in nl]
    heads = [pp[0].strip() for pp in parts]
    keys = [re.sub(r"\s+", " ", h).strip().lower() for h in heads]
    if all(keys) and len(set(keys)) == len(keys) and not any(rates(h) for h in heads):
        out = []
        for h, pp in zip(heads, parts):
            if len(pp) < 2:
                out.append(h)
                continue
            kept, bad = _kept_clauses(re.sub(r"\s*[:：]\s*", ", ", pp[1]))
            out.append(None if bad else _unmask(h + (", " + ", ".join(kept) if kept else "")))
        return [_unmask(x) if x is not None else None for x in out]
    return nl


def neutral_label(label):
    """K5r6-M2 / K6 r1 M4 / K6 r2 M3: an option label as the engine shows it blind — the judge's summary with its asides
    reduced to their scope clauses (`aside_split`) and without a comma / colon tail that rates the option. None when
    what is left still evaluates, nothing is left, or an aside holds a clause that can be neither shown nor dropped:
    the blind answer is then refused."""
    lb, refuse = aside_split(label)
    if refuse:
        return None
    if not rates(lb):
        return lb or None
    cut = []
    out = _CLAUSE.sub(lambda m: _cut(m, cut), _mask(lb)).strip(" —–-;:,、")
    # K6 r3 m1: a cut clause must be a REMARK — a numeric rating (`other`) or a rated scope is refused, never dropped
    if not out or rates(out) or any(clause_kind(c.strip(" —–-;；:：,、，()（）[]")) not in ("remark",) for c in cut):
        return None
    return _unmask(out)


_PAREN = re.compile(r"^(\s*)([(（\[])([^)）\]]*)([)）\]])$")
_COMMA = re.compile(r"\s*[,、，;；]\s*")


def _cut(m, cut=None):
    """One clause of a label: kept when it does not rate. K5r7-m2(b): a parenthesis is cut by its comma clauses —
    `(앱 전체, 가능성 높음)` keeps `(앱 전체)` (cutting it whole made two labels the same). `cut` collects what was
    removed (K6 r2 M3: `neutral_label` refuses when a removed clause was not a remark)."""
    c = m.group(0)
    if not rates(c):
        return c
    pm = _PAREN.match(c)
    if not pm:
        if cut is not None:
            cut.append(c)
        return ""
    keep = [x for x in _COMMA.split(pm.group(3)) if x.strip() and not rates(x)]
    if cut is not None:
        cut += [x for x in _COMMA.split(pm.group(3)) if x.strip() and rates(x)]
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
    # K5r11-M1 (structural): the blind question's own wording is the engine's template (`Question.neutral` /
    # `default_neutral`) — an option token in it (a group name `SPLIT`, a step) is no judgment of the options, so
    # mentions are counted only in the text that is NOT the template
    tmpl = q.text if getattr(q, "neutralized", False) else None
    if nm.names_rec(_strip_template(q.text, tmpl)):
        return "question"
    for t in list(q.context_lines) + [x for x in texts if x]:
        if nm.names_rec(_strip_template(t, tmpl)):
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


def _strip_template(text, tmpl):
    """K5r11-M1: `text` without the engine-generated neutral template (every occurrence) — what is left is the only
    text whose option mentions can say anything about the recommendation. K6 (r12 m1, item 44): only a template the
    engine REGISTERED (`NEUTRAL_FORMS`, every variable slot within its own closed pattern) is stripped — a `neutral`
    that is not one of them (a judge phrase that reached a caller) is counted like any other text."""
    text = str(text or "")
    if tmpl and is_template(tmpl):
        text = text.replace(str(tmpl), " ")
    return text


# K6 (r12 m1, item 44): THE registry of blind-question wordings. A caller never formats its own `neutral=` — it calls
# `neutral_text(form, *values)`, which checks every value against its slot's closed pattern (an issue number, a step
# id, an ask kind) and refuses anything else; `is_template` accepts only text that one of
# these forms produces. A static test (test_k6_neutral) fails on any `neutral=` that does not come from here.
_ISSUE = r"[0-9]{1,7}"
_STEP = r"(?:-|[A-Za-z0-9][A-Za-z0-9._:→-]{0,39})"   # E2.1 · HO · Q2.5 · X→T · TEST:repair · `-` — no spaces, no prose
# K6 r4: the KICKOFF wordings (readiness-unclear · interpretation · readiness-high · kickoff-conservative) are gone with
# the scope reduction — a KICKOFF question is never blind (`OPEN_GROUPS`)
NEUTRAL_FORMS = {
    "conservative": ("#%d: 보수 경로 확인(%s) — 어느 쪽으로 정할까요?", ("issue", "step")),
    "default": ("#%d: %s — 어느 선택지로 진행할까요?", ("issue", "kind")),
}


def _slot(name):
    if name == "issue":
        return _ISSUE
    if name == "step":
        return _STEP
    if name == "kind":
        from guildcore.records.decisions import ASK_KINDS
        return "(?:%s)" % "|".join(re.escape(k) for k in sorted(ASK_KINDS, key=len, reverse=True))
    raise KeyError(name)


def _form_re(form):
    fmt, slots = NEUTRAL_FORMS[form]
    parts, i = re.split(r"(%[ds])", fmt), 0
    out = []
    for x in parts:
        if x in ("%d", "%s"):
            out.append(_slot(slots[i]))
            i += 1
        else:
            out.append(re.escape(x))
    return re.compile("^%s$" % "".join(out))


def is_template(text):
    """True when `text` is exactly one registered blind wording (every slot inside its closed pattern)."""
    t = str(text or "")
    return any(_form_re(f).match(t) for f in NEUTRAL_FORMS)


def neutral_text(form, *values):
    """The blind wording `form` with `values` — ValueError when a value is outside its slot (never formatted in)."""
    fmt, slots = NEUTRAL_FORMS[form]
    if len(values) != len(slots):
        raise ValueError("neutral form %s takes %d values" % (form, len(slots)))
    for name, v in zip(slots, values):
        if not re.match("^%s$" % _slot(name), str(v)):
            raise ValueError("neutral form %s: %r is not a %s" % (form, v, name))
    vals = tuple(int(v) if name == "issue" else v for name, v in zip(slots, values))
    return fmt % vals


def default_neutral(p, q):
    """K5r5-M1: the engine's own wording of a blind question — the Issue and the kind, nothing the judge wrote."""
    return neutral_text("default", int(getattr(p, "issue", 0) or 0), q.kind)


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
    g = group_of(q, stage)
    if g in OPEN_GROUPS:
        # user decision 2026-11-20 (K6 r4): asked openly — the recommendation is shown, the answer never counted
        q.predict_first, q.pf_why = False, None
        q.open_group = "%s: %s" % (g, OPEN_GROUPS[g])
        return q
    if not q.predict_first and q.recommended is not None:     # nothing to withhold → the answer is blind anyway
        why = forced(p, q, stage)
        if why:
            q.predict_first = True
            q.pf_why = why
    if not q.predict_first or q.recommended is None:
        return q
    # K5r5-M1 (structural): the person sees only engine-generated text before answering — the neutral template and
    # the options' own summaries; the judge's text is withheld (journaled, revealed after the answer)
    q.withheld = {"question": q.text, "context": list(q.context_lines), "texts": [t for t in texts if t]}
    q.original, q.text, q.neutralized = q.text, (q.neutral or default_neutral(p, q)), True
    q.context_lines = []
    # K5r6-M2: the labels are the judge's summaries — blind, the engine shows them without their evaluative clauses
    # (`neutral_label`); a label that still evaluates refuses the blind answer
    q.withheld["labels"] = [dict(o) for o in q.options]
    where = None
    opts = []
    real = [o for o in q.options if o["token"] != "stop"]
    shown = dict(zip([o["token"] for o in real], blind_labels([o.get("label") for o in real])))
    for o in q.options:
        if o["token"] == "stop":
            opts.append(o)
            continue
        nl = shown.get(o["token"])
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
