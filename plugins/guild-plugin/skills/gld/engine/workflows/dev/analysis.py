"""workflows.dev.analysis — the CODE half of analyze (catalog A §2.7, design §3.2): the parts the
legacy leader did in prose that need no model.

* `plan_decisions(body)` — the Issue body's `<!-- guild:plan-decision -->` lines
  (`- <Goal|Constraint|Success>: <q> → <answer> (<date>, sprint plan)`), each with its tagged
  premises `(전제: #d)` (A1.0, J-AN-02 tagged half);
* `premise_met(issue, comments)` — met = CLOSED+COMPLETED, or `guild:done` ∧ not a split parent ∧
  not CLOSED/NOT_PLANNED (catalog A1.0 rule, one read per premise);
* `safety_net_lines(body)` — each line under `<!-- guild:safety-net -->` becomes its own AC verbatim
  (A-F17 — the judgment may phrase alongside, never replace);
* `verify_anchor(anchor, root, sources)` — KICKOFF's `path:line`+quote anchors checked against the
  REAL file (tracked, contained, no symlink; quote within ±3 lines) or a quote of the Issue / charter /
  plan text (JR-B1, R2J-N1);
* `coerce_kickoff(...)` — §3.2 G-KICK coercions as code (partial + invalid anchor → unclear,
  premise unmet / requires_reinterpretation / unsure → unclear + stakes high, safety-net AC restored,
  areas = existing directories only, AC ids renumbered `AC #n`, close only from a plan line);
* `harness_hit(paths)` — R7C-m1: `.claude/settings*.json` / `.claude/guild/gates/**` → a person;
* `irreversible(paths, globs)` — §3.2: the ecosystem globs (or `engine.irreversible_globs`);
* `render_output(...)` / `parse_output(body)` — the analyze:output record: free prose stays prose,
  the machine lines are `Readiness: Goal=<t> · Constraint=<t> · Success=<t> (…)` (RD §D),
  `work-type: <feature|bug|refactor>`, `cast: <roles>` (catalog D2.G4) and one `- AC #n …` line per
  acceptance criterion. The parser is tolerant of the legacy prose forms (bold, `AC-1`, tables) so
  a legacy-started Issue's analyze:output feeds design.

P2: every input here except the repo files is untrusted text. Nothing parsed from the Issue body is
honoured unless `trusted_body` (the Issue author is a member — `stage.analyze` decides that);
judgment output only ever narrows (coercions move toward `unclear`/`high`, never away).
"""

import fnmatch
import os
import re
import stat

from guildcore.records import markers

DIMS = ("goal", "constraint", "success")
DIM_KEY = {"goal": "Goal", "constraint": "Constraint", "success": "Success"}
RATINGS = ("clear", "partial", "unclear")
WORK_TYPES = ("feature", "bug", "refactor")
SPINE = ("leader", "tech-lead", "developer", "tester", "qa")
GATE_ROLES = ("designer", "security", "infra")
PARTICIPATION = ("product-owner", "i18n", "dba", "analytics", "performance", "tech-writer")
DESIGN_SPECIALISTS = ("designer", "i18n", "dba", "analytics", "performance", "tech-writer", "security")

PLAN_OPEN, PLAN_CLOSE = "<!-- guild:plan-decision -->", "<!-- /guild:plan-decision -->"
PLAN_LINE_RE = re.compile(r"^\s*[-*]\s*(Goal|Constraint|Success)\s*:\s*(.+?)\s*→\s*(.+?)\s*$")
PREMISE_RE = re.compile(r"\(전제:\s*#(\d+)\)")
SAFETY_NET = "<!-- guild:safety-net -->"
HARNESS_GLOBS = (".claude/settings.json", ".claude/settings.local.json", ".claude/settings*.json",
                 ".claude/guild/gates/*", ".claude/guild/gates/**")
# §3.2: the ecosystem defaults — migrations, schema files, public API manifests / OpenAPI / proto,
# persisted data-model paths (`engine.irreversible_globs` replaces them)
IRREVERSIBLE_DEFAULT = ("**/migrations/**", "**/migration/**", "**/*.sql", "**/schema*.*", "**/*.proto",
                        "**/openapi*.*", "**/swagger*.*", "**/drift_schemas/**", "**/*.prisma",
                        "**/db/**", "**/models/**/*.g.dart")
TYPE_LABEL = {"feature": "type:feature", "bug": "type:bug", "refactor": "type:refactor"}
ANCHOR_RE = re.compile(r"^([^:\s][^:]*):(\d+)(?:-(\d+))?$")
MAX_ANCHOR_FILE = 2 * 1024 * 1024


# ---- the Issue body (trusted only from a member — the caller decides) ---------------------------

class PlanLine(object):
    def __init__(self, raw, dim, question, answer):
        self.raw, self.dim, self.question, self.answer = raw, dim.lower(), question, answer
        self.premises = [int(x) for x in PREMISE_RE.findall(answer)]


def _block(body, open_tag, close_tag=None):
    text = body or ""
    i = text.find(open_tag)
    if i < 0:
        return None
    rest = text[i + len(open_tag):]
    if close_tag and close_tag in rest:
        return rest[:rest.index(close_tag)]
    return rest


def unquoted(body):
    """K4r3-m6: the body with code fences (``` / ~~~) and `>` quote lines blanked — a member quoting the
    close grammar as an example, or pasting someone else's text, does not write a sprint decision.
    K4r4-m6: a block is ignored only when its OPENING line sits inside a fence. A fence that never closes
    (a pasted log cut short) ends at the next line that opens a plan-decision block — sprint plan appends
    its block at the end of the body, after whatever the member pasted — or at EOF. K4r5-m3: not at a block
    that opens right after the fence line (nothing between) — that block is the fenced example."""
    lines = (body or "").split("\n")
    out, i = [], 0
    while i < len(lines):
        st = lines[i].lstrip()
        if st.startswith("```") or st.startswith("~~~"):
            fence = st[:3]
            close = next((j for j in range(i + 1, len(lines)) if lines[j].lstrip().startswith(fence)), None)
            if close is None:
                # K4r5-m3: the fence ends right before a block-opening line only when something non-blank stands
                # between the fence and that line (a pasted log, then sprint plan's appended block); a block that
                # opens RIGHT after the fence is the fenced example itself and stays blanked
                close = next((j - 1 for j in range(i + 1, len(lines)) if lines[j].lstrip().startswith(PLAN_OPEN)
                              and any(lines[k].strip() for k in range(i + 1, j))), len(lines) - 1)
            out.extend([""] * (close - i + 1))
            i = close + 1
            continue
        out.append("" if st.startswith(">") else lines[i])
        i += 1
    return "\n".join(out)


def plan_decisions(body):
    blk = _block(unquoted(body), PLAN_OPEN, PLAN_CLOSE)
    if blk is None:
        return []
    out = []
    for ln in blk.split("\n"):
        if ln.strip().startswith("<!--"):
            break
        m = PLAN_LINE_RE.match(ln)
        if m:
            out.append(PlanLine(ln.strip(), m.group(1), m.group(2), m.group(3)))
    return out


def safety_net_lines(body):
    blk = _block(body, SAFETY_NET)
    if blk is None:
        return []
    out = []
    for ln in blk.split("\n"):
        s = ln.strip()
        if s.startswith("#") or s.startswith("<!--"):
            if out:
                break
            continue
        if s.startswith(("- ", "* ")):
            out.append(s[2:].strip())
    return out


def premise_met(issue, comments):
    """catalog A1.0: met = CLOSED+COMPLETED, or guild:done ∧ no children:output ∧ not CLOSED/NOT_PLANNED."""
    from guildcore.state import label_names
    st = (issue.get("state") or "").upper()
    reason = (issue.get("stateReason") or "").upper()
    if st == "CLOSED" and reason == "COMPLETED":
        return True
    split = any(markers.open_tag("children:output") in markers.body_of(c) for c in comments or [])
    return "guild:done" in label_names(issue.get("labels")) and not split and \
        not (st == "CLOSED" and reason == "NOT_PLANNED")


# ---- anchors (JR-B1) ---------------------------------------------------------------------------

def _safe_repo_file(root, rel):
    """A repo-relative, contained, symlink-free regular file — else None (P1/P2: an anchor path
    comes from a judgment that read untrusted text)."""
    if not root or not rel or os.path.isabs(rel) or "\0" in rel:
        return None
    norm = os.path.normpath(rel)
    if norm.startswith("..") or norm == "." or norm.split(os.sep)[0] == ".git":
        return None
    cur = root
    for part in norm.split(os.sep):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except OSError:
            return None
        if stat.S_ISLNK(st.st_mode):
            return None
    real_root = os.path.realpath(root)
    if not os.path.realpath(cur).startswith(real_root + os.sep):
        return None
    st = os.lstat(cur)
    if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_ANCHOR_FILE:
        return None
    return cur


def _norm(s):
    return " ".join((s or "").split())


# K4r2-M3: "close as decided" is a STRUCTURED decision of the plan-decision grammar, never words found
# in an ordinary answer (`… 동기화하지 않음`, `닫기 버튼 재사용`, `completed 상태에서 …`, `취소 버튼 추가`
# are requirements, not closes). A member plan line closes the Issue only when
#   * its dimension is `Goal`, and
#   * its ANSWER STARTS with the close form  `close: completed` | `close: not_planned`
#     (`not planned` / `not-planned` accepted; Korean `닫음: 이미 충족` = completed, `닫음: 하지 않기로` =
#     not_planned), optionally followed by ` — <why>` / ` - <why>` / ` (<why>)` and the plan's own tail;
#   * the judgment's quote equals that whole line (bullet optional) and its reason agrees.
# Everything else is an ordinary answer: attended `ask close-decided`, unattended `ambiguity:`.
CLOSE_FORM_RE = re.compile(r"^(?:close|닫음)\s*:\s*(completed|not[ _-]planned|이미 충족|하지 않기로)(?=\s*(?:$|[—(-]))",
                           re.I)
CLOSE_FORM_REASON = {"completed": "completed", "이미 충족": "completed", "하지 않기로": "not_planned"}


def close_form(answer):
    """`completed` | `not_planned` when `answer` IS a structured close decision, else None."""
    m = CLOSE_FORM_RE.match((answer or "").strip())
    if not m:
        return None
    tok = m.group(1).lower()
    return CLOSE_FORM_REASON.get(tok) or ("not_planned" if tok.startswith("not") else None)


def close_plan_line(quote, plan_lines, decide):
    """The member Goal plan line `quote` names EXACTLY whose answer is the structured close form
    for `decide` (completed | not_planned) — else None."""
    q = _norm(quote)
    if not q:
        return None
    for pl in plan_lines or []:
        raw = _norm(pl.raw)
        if q not in (raw, _norm(re.sub(r"^\s*[-*]\s*", "", pl.raw))):
            continue
        if pl.dim != "goal":
            return None
        form = close_form(pl.answer)
        return pl if form is not None and form == decide else None
    return None


def verify_anchor(anchor, root, sources, tracked=None):
    """True when `anchor` = {cite: "path:line[-line]", quote} matches the file (quote within ±3
    lines of the range, whitespace-folded) or `{source: issue|charter|plan, quote}` is a substring of
    that source. `tracked(rel)` (optional) — the path must be a tracked file (never an ignored one)."""
    if not isinstance(anchor, dict):
        return False
    quote = _norm(anchor.get("quote"))
    if len(quote) < 4:
        return False
    cite = (anchor.get("cite") or "").strip()
    m = ANCHOR_RE.match(cite)
    if m:
        rel = m.group(1)
        if tracked is not None and not tracked(rel):
            return False
        path = _safe_repo_file(root, rel)
        if path is None:
            return False
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(fd, "rb") as fh:
                lines = fh.read().decode("utf-8", "replace").split("\n")
        except OSError:
            return False
        a, b = int(m.group(2)), int(m.group(3) or m.group(2))
        if a < 1 or b < a or a > len(lines):
            return False
        lo, hi = max(0, a - 1 - 3), min(len(lines), b + 3)
        return quote in _norm("\n".join(lines[lo:hi]))
    src = (anchor.get("source") or cite or "").strip().lower()
    for name in ("issue", "charter", "plan"):
        if src.startswith(name):
            return quote in _norm(sources.get(name) or "")
    return False


# ---- paths -------------------------------------------------------------------------------------

def _glob_match(path, globs):
    # K6 r3 (found with M4): `lstrip("./")` stripped the leading DOT of `.claude/…` too — the harness globs
    # (`.claude/settings*.json`, `.claude/guild/gates/**`) never matched a path; only a `./` prefix is dropped now
    p = str(path or "")
    while p.startswith("./"):
        p = p[2:]
    for g in globs:
        if fnmatch.fnmatch(p, g) or (g.startswith("**/") and fnmatch.fnmatch(p, g[3:])):
            return True
    return False


# K6 r3 M4: an AREA is a directory (KICKOFF `areas`, the explorer's dirs — `real_dirs` strips the trailing `/`). A
# directory glob (`**/migrations/**`, `**/db/**`, `.claude/guild/gates/**`) needs a path component AFTER the directory,
# so the directory itself — `supabase/migrations`, `lib/db`, `migrations` — never matched: §3.2 "irreversible path →
# never low" and the §9.5 irreversible class were dead for directory inputs. An area matches when the area itself, or
# anything directly inside it, matches (`<area>/<probe>`); the probe holds no `.` so a file glob (`**/*.sql`,
# `**/schema*.*`) does not match a plain directory by it.
_DIR_PROBE = "_guild_area_probe_"


def _area_match(path, globs):
    p = str(path or "").strip().rstrip("/")
    return bool(p) and (_glob_match(p, globs) or _glob_match(p + "/" + _DIR_PROBE, globs))


def harness_hit(paths):
    return sorted(set(p for p in paths if p and _area_match(p, HARNESS_GLOBS)))


def harness_text_hit(texts):
    """A harness path named in free text (AC / areas) — `.claude/settings*.json`, gates."""
    rx = re.compile(r"\.claude/(?:settings[A-Za-z0-9_.-]*\.json|guild/gates(?:/[\w./-]*)?)")
    out = set()
    for t in texts:
        out.update(rx.findall(t or ""))
    return sorted(out)


def irreversible(paths, globs=None):
    """§3.2 — the paths (files or directory AREAS — K6 r3 M4) that touch an irreversible glob."""
    gl = tuple(globs) if globs else IRREVERSIBLE_DEFAULT
    return sorted(set(p for p in paths if p and _area_match(p, gl)))


def real_dirs(root, paths):
    """`areas` = only directories that exist in the repo (contained, no symlink)."""
    out = []
    for rel in paths or []:
        if not isinstance(rel, str):
            continue
        rel = rel.strip().rstrip("/")
        if not rel or os.path.isabs(rel) or os.path.normpath(rel).startswith(".."):
            continue
        cur, ok = root, bool(root)
        for part in os.path.normpath(rel).split(os.sep):
            cur = os.path.join(cur, part)
            if not os.path.lexists(cur) or os.path.islink(cur):
                ok = False
                break
        if ok and os.path.isdir(cur) and os.path.realpath(cur).startswith(os.path.realpath(root) + os.sep):
            out.append(os.path.normpath(rel))
    return sorted(set(out))


# ---- KICKOFF coercions -------------------------------------------------------------------------

class Kickoff(object):
    """The code-checked KICKOFF result the stage acts on."""

    def __init__(self):
        self.readiness = {}           # dim → rating
        self.anchors = {}             # dim → anchor (verified) | None
        self.choice_needed = {}       # dim → text
        self.high = set()             # dims whose stakes are fixed high (premise / reinterpretation)
        self.coerced = []             # human-readable coercion notes (decision log `coerced_by: rule`)
        self.ac = []                  # [{id, text, priority, tag}]
        self.interpretations = []     # [{id, summary, orig}] — id = engine token, canonical order (K5r4-m1)
        self.token_map = []           # [{token, orig}] — journaled by the stage (K5r4-m1)
        self.aliases = {}             # token → [judge id, full summary] — predict.leak (K5r4-M1)
        self.chosen = None
        self.assumptions = []
        self.features = []
        self.work_type = "feature"
        self.split_hint = False
        self.cast = {"participation": [], "gates": [], "skipped": []}
        self.po = {"convene": False, "reason": ""}
        self.ui_surface = False
        self.safety_net_visual = False
        self.areas = []
        self.close = {"decide": "none"}
        self.surface = {"ask": False}
        self.own_footprints = {}      # token → the judge's raw interpretation entry (its own footprint — K6 r3 M1)
        self.safety_net_visual_possible = False   # the body has safety-net lines (K6 r4 m2 — the visual case)


def coerce_kickoff(fields, root, sources, net_lines, plan_lines, premise_unmet_dims, roster,
                   tracked=None, attended=False):
    k = Kickoff()
    f = fields or {}
    interp = [i for i in (f.get("interpretations") or []) if isinstance(i, dict) and i.get("id")][:5]
    # ids become answer tokens `i1`…`i5` (the judge's own ids are free text — §2.5 token grammar).
    # K5r4-m1: the NUMBERS follow a canonical, content-based order (normalized summary, then a hash of the judge's
    # id) — never the judge's listing order, which tends to put its pick first; the mapping is journaled by the stage
    order = sorted(range(len(interp)), key=lambda n: canon_key(interp[n]))
    k.interpretations = [{"id": "i%d" % (r + 1), "summary": str(interp[n].get("summary") or ""),
                          "orig": str(interp[n]["id"])[:40]} for r, n in enumerate(order)]
    k.own_footprints = dict((k.interpretations[r]["id"], interp[n]) for r, n in enumerate(order))
    k.token_map = [{"token": i["id"], "orig": i["orig"]} for i in k.interpretations]
    # K5r4-M1: the judge's own ids are aliases of the engine tokens — case-insensitive (`I2` = `i2` to a reader)
    by_orig = dict((i["orig"].strip().casefold(), i["id"]) for i in k.interpretations)
    k.aliases = dict((i["id"], [i["orig"], i["summary"]]) for i in k.interpretations)
    first = k.interpretations[order.index(0)]["id"] if interp else None     # the judge's first listed one
    k.chosen = by_orig.get(str(f.get("chosen")).strip().casefold()) or first
    if str(f.get("chosen")).strip().casefold() not in by_orig and first:
        k.coerced.append("chosen not among interpretations → %s" % k.chosen)
    rd = f.get("readiness") or {}
    for dim in DIMS:
        r = rd.get(dim) or {}
        rating = r.get("rating") if r.get("rating") in RATINGS + ("unsure",) else "unsure"
        anchor = r.get("anchor")
        if rating == "unsure":
            k.coerced.append("%s unsure → unclear" % dim)
            rating = "unclear"
            k.high.add(dim)
        if rating == "partial":
            if not verify_anchor(anchor, root, sources, tracked):
                k.coerced.append("%s partial with an unverified anchor → unclear (A-F13)" % dim)
                rating = "unclear"
            else:
                k.anchors[dim] = anchor
        elif rating == "clear" and anchor and verify_anchor(anchor, root, sources, tracked):
            k.anchors[dim] = anchor
        k.readiness[dim] = rating
        k.choice_needed[dim] = to_tokens(str(r.get("choice_needed") or ""), k.token_map)
    plan_dims = {}
    for pl in plan_lines:
        plan_dims.setdefault(pl.dim, []).append(pl)
    for pd in f.get("plan_decisions") or []:
        if not isinstance(pd, dict):
            continue
        fit = pd.get("fit")
        hit = [pl for pl in plan_lines if _norm(pl.raw) == _norm(pd.get("line")) or _norm(pd.get("line")) in _norm(pl.raw)]
        if not hit:
            continue
        dim = hit[0].dim
        if fit in ("requires_reinterpretation", "unsure"):
            k.readiness[dim] = "unclear"
            k.high.add(dim)
            k.coerced.append("plan line %s → unclear + stakes high (an:51)" % fit)
    for dim in premise_unmet_dims:
        k.readiness[dim] = "unclear"
        k.high.add(dim)
    # AC — renumbered, safety-net lines restored verbatim (A-F17)
    acs = []
    for a in f.get("ac") or []:
        if isinstance(a, dict) and (a.get("text") or "").strip():
            acs.append({"text": str(a["text"]).strip(), "priority": str(a.get("priority") or ""),
                        "tag": "safety net" if (a.get("tag") or "").strip().lower() == "safety net" else ""})
    have = [_norm(a["text"]) for a in acs if a["tag"] == "safety net"]
    for line in net_lines:
        if _norm(line) not in have:
            acs.append({"text": line, "priority": "must", "tag": "safety net"})
            k.coerced.append("safety-net line restored as AC: %s" % line[:60])
    for a in acs:
        if a["tag"] == "safety net" and _norm(a["text"]) not in [_norm(x) for x in net_lines]:
            a["tag"] = ""                       # a tag the body does not back is not a net
    k.ac = [dict(a, id="AC #%d" % (i + 1)) for i, a in enumerate(acs)]
    k.assumptions = [str(x.get("text") if isinstance(x, dict) else x) for x in (f.get("assumptions") or [])][:12]
    k.features = [str(x) for x in (f.get("features") or [])][:20]
    wt = f.get("work_type")
    k.work_type = wt if wt in WORK_TYPES else "feature"
    k.split_hint = bool(f.get("split_hint"))
    installed = set(roster or ())
    cast = f.get("cast") or {}
    part = [r for r in cast.get("participation") or [] if r in installed and r not in SPINE]
    gates = [r for r in cast.get("gates") or [] if r in installed and r in GATE_ROLES]
    unresolved_gates = [r for r in cast.get("unresolved_gates") or [] if r in installed and r in GATE_ROLES]
    for r in unresolved_gates:                  # H§G:503 — an unresolved gate trigger convenes
        if r not in gates:
            gates.append(r)
            k.coerced.append("gate %s unresolved → convened" % r)
    k.cast = {"participation": sorted(set(part) - set(gates)), "gates": sorted(set(gates)),   # K4 smoke: no `designer, designer`
              "skipped": [str(s)[:120] for s in cast.get("skipped") or []][:10]}
    po = f.get("po") or {}
    k.po = {"convene": bool(po.get("convene")) and "product-owner" in installed, "reason": str(po.get("reason") or "")}
    k.ui_surface = bool(f.get("ui_surface"))
    k.safety_net_visual = bool(f.get("safety_net_visual")) and bool(net_lines)
    k.safety_net_visual_possible = bool(net_lines)
    k.areas = real_dirs(root, f.get("areas") or [])
    dropped = [a for a in f.get("areas") or [] if isinstance(a, str) and os.path.normpath(a.strip().rstrip("/")) not in k.areas]
    if dropped:
        k.coerced.append("areas dropped (not a repo directory): %s" % ", ".join(str(x) for x in dropped[:5]))
    cl = f.get("close") or {}
    dec = cl.get("decide") if cl.get("decide") in ("none", "completed", "not_planned") else "none"
    k.close = {"decide": dec, "source": cl.get("source"), "line": to_tokens(str(cl.get("line") or ""), k.token_map)}
    if dec != "none":
        pl = close_plan_line(cl.get("line"), plan_lines, dec) if cl.get("source") == "plan_line" else None
        from_plan = pl is not None
        k.close["from_plan"] = from_plan
        if from_plan:
            k.close["line"] = pl.raw                  # the engine's own copy of the member's line
        if not from_plan and not attended:
            k.coerced.append("close without a plan-decision line → high ambiguity (unattended)")
    st = f.get("surface_to_human") or {}
    k.surface = {"ask": bool(st.get("ask")), "question": to_tokens(str(st.get("question") or ""), k.token_map)}
    return k


# ---- K6 r3 M1 / K6 r4: the person's reading, carried as the reading itself -----------------------------------------
# A KICKOFF answer is a TOKEN (`i2`) of the canonical order of THAT run's summaries; the next run's judge writes new
# summaries (the order — and so the token — can flip) and its own footprint (`areas` · `ui_surface` · `cast` ·
# `work_type` · `safety_net_visual` · `po`) is for the reading IT chose. So the question captures, at question time,
# every reading the person chooses between — token, the judge's id, the summary and that reading's footprint — as
# CONTENT on its pending block (`reading_<token>`, one JSON value each — K6 r4: KICKOFF is asked openly, so nothing is
# sealed; any clone reads it). The run after the answer takes the readings, `chosen` and the footprint from that
# capture (never from the new judge's token order), tells the judge which reading the person chose, and pauses when the
# judge does not take it (user decision 2026-11-20: its AC would be another reading's).
# A reading's footprint: the judge's top-level fields for the reading it chose; for another reading its own fields
# (`interpretations[].areas` / `ui_surface` / `cast` / `work_type` / `safety_net_visual` / `po`) when given, else the
# conservative SUPERSET (K6 r4 m2): every known area (the explorer's directories too — an empty / non-existent own
# `areas` is no footprint), every known participation role and EVERY installed gate role, a UI surface (the visual
# safety net then follows `VISUAL_AVAILABLE` — design's L.1), the safety-net visual case when the body has a net, the
# product-owner when installed, nothing skipped — never narrower than any reading.
READING_FIELD = "reading_"         # pending block keys `reading_i1` … `reading_i5`
READING_CAP = 1900                 # one JSON value under the decision log's VALUE_CAP (2000)


def order_areas(areas, globs=None):
    """K6 r4 m2: areas with the irreversible and harness ones FIRST (then the rest, sorted) — whatever a value cap
    drops is never one §3.2 / A4 must see."""
    a = sorted(set(x for x in areas or () if x))
    hot = set(irreversible(a, globs)) | set(harness_hit(a))
    return [x for x in a if x in hot] + [x for x in a if x not in hot]


def _own_cast(raw, roster):
    installed = set(roster or ())
    c = raw.get("cast") if isinstance(raw.get("cast"), dict) else None
    if c is None:
        return None
    part = [r for r in c.get("participation") or [] if r in installed and r not in SPINE]
    gates = [r for r in (list(c.get("gates") or []) + list(c.get("unresolved_gates") or []))
             if r in installed and r in GATE_ROLES]
    return sorted(set(part) - set(gates)), sorted(set(gates))


def reading_capture(k, root, roster, extra_areas=(), net=False, globs=None):
    """[{token, orig, summary, areas, ui_surface, safety_net_visual, participation, gates, skipped, po_convene,
    work_type}] — every reading of this KICKOFF with its footprint (see above). `extra_areas` (the explorer's real
    directories) widen the superset; `net` = the body has safety-net lines (the superset's visual case)."""
    if not k.interpretations:
        return []
    installed = set(roster or ())
    owns = getattr(k, "own_footprints", {}) or {}
    union_a = set(k.areas) | set(extra_areas or ())
    union_p, union_g = set(k.cast["participation"]), set(k.cast["gates"])
    per = {}
    for i in k.interpretations:
        raw = owns.get(i["id"]) or {}
        a = real_dirs(root, raw.get("areas")) if isinstance(raw.get("areas"), list) else None
        a = a or None                         # m2(b): an empty / non-existent own area list is no footprint
        c = _own_cast(raw, roster)
        u = raw.get("ui_surface") if isinstance(raw.get("ui_surface"), bool) else None
        v = raw.get("safety_net_visual") if isinstance(raw.get("safety_net_visual"), bool) else None
        po = raw.get("po") if isinstance(raw.get("po"), dict) and isinstance(raw["po"].get("convene"), bool) else None
        w = raw.get("work_type") if raw.get("work_type") in WORK_TYPES else None
        sk = [str(x)[:80] for x in raw.get("skipped") or []][:5] if isinstance(raw.get("skipped"), list) else None
        per[i["id"]] = (a, c, u, v, po, w, sk)
        union_a |= set(a or ())
        if c:
            union_p |= set(c[0])
            union_g |= set(c[1])
    # m2(c): a reading whose roles are unknown may need any gate — every INSTALLED gate role convenes
    sup_g = union_g | (installed & set(GATE_ROLES))
    out = []
    for i in k.interpretations:
        a, c, u, v, po, w, sk = per[i["id"]]
        if i["id"] == k.chosen:
            fp = {"areas": order_areas(k.areas, globs), "ui_surface": bool(k.ui_surface),
                  "safety_net_visual": bool(k.safety_net_visual),
                  "participation": list(k.cast["participation"]), "gates": list(k.cast["gates"]),
                  "skipped": [str(x)[:80] for x in k.cast.get("skipped") or []][:5],
                  "po_convene": bool(k.po.get("convene")), "work_type": k.work_type}
        else:
            fp = {"areas": order_areas(a if a is not None else union_a, globs),
                  "ui_surface": u if u is not None else True,      # unknown → a UI surface (L.1 decides the visual)
                  "safety_net_visual": (v and bool(net)) if v is not None else bool(net),
                  "participation": sorted(c[0] if c is not None else union_p - sup_g),
                  "gates": sorted(c[1] if c is not None else sup_g),
                  "skipped": sk if (sk is not None and c is not None) else [],
                  "po_convene": po["convene"] if po is not None else ("product-owner" in installed),
                  "work_type": w or k.work_type}
        out.append(dict(fp, token=i["id"], orig=i["orig"][:40], summary=i["summary"][:300]))
    return out


READING_MORE = "reading-areas-"    # K6 r5 m3: continuation values `reading-areas-<token>-<n>` (the rest of the areas)
MORE_PLACEHOLDER = 999
# K6 r6 m2: the continuation values of ONE pending block together — well under the decision log's rollover (60,000;
# a single block is never split, and GitHub refuses a comment over 65,536). With ≤ 5 readings of ≤ READING_CAP each
# and the question's own fields, a block stays ≈ 45k at most. A reading whose rest would pass it keeps its head only
# (`more: true` — the conservative superset at `apply_reading`; nothing narrows).
CONTINUATION_BUDGET = 30000


def _dump(e):
    import json
    return json.dumps(e, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def capture_fields(capture):
    """The pending-block fields carrying `capture` as content — one compact JSON value per reading. K6 r5 m3: nothing
    is lost to the value cap — a reading whose JSON is over it keeps the head of its areas (ordered: irreversible /
    harness first — `order_areas`) and carries the rest in continuation values `reading-areas-<token>-<n>` (each a
    JSON list under the cap), `more: <n>` naming how many; `captured` puts them back together.
    K6 r6 m2: the continuation values of the whole block stay within `CONTINUATION_BUDGET`; a reading whose rest would
    pass it is carried as its head with `more: true` (read back as a head only → the conservative superset)."""
    out = {}
    spent = 0
    for e in capture or ():
        e = dict(e)
        txt = _dump(e)
        rest = []
        if len(txt) > READING_CAP and e.get("areas"):
            areas = list(e["areas"])
            e["areas"] = list(areas)              # never the caller's list (the capture stays whole)
            e["more"] = MORE_PLACEHOLDER
            while len(_dump(e)) > READING_CAP and e["areas"]:
                rest.insert(0, e["areas"].pop())
            chunks, cur = [], []
            for x in rest:
                if cur and len(_dump(cur + [x])) > READING_CAP:
                    chunks.append(cur)
                    cur = []
                cur.append(x)
            if cur:
                chunks.append(cur)
            e["more"] = len(chunks)
            assert sum(len(c) for c in chunks) + len(e["areas"]) == len(areas)
            cost = sum(len(_dump(c)) + len(READING_MORE) + len(str(e["token"])) + 8 for c in chunks)
            if not chunks:
                e.pop("more")
            elif spent + cost > CONTINUATION_BUDGET:
                e["more"] = True               # K6 r6 m2: over the block budget — a head only (the superset fallback)
                chunks = []
            spent += sum(len(_dump(c)) + len(READING_MORE) + len(str(e["token"])) + 8 for c in chunks)
            for n, c in enumerate(chunks, 1):
                out["%s%s-%d" % (READING_MORE, e["token"], n)] = _dump(c)
            txt = _dump(e)
        if len(txt) > READING_CAP:
            e["skipped"], e["summary"] = [], e["summary"][:120]
            txt = _dump(e)
        out[READING_FIELD + e["token"]] = txt
    return out


def captured(block):
    """(capture | None, why) of a pending KICKOFF question block: `why` = "legacy" (no capture — a question asked before
    r3), "unreadable" (a field that does not parse), or None. K6 r5 m3: the continuation values are joined back; an
    entry whose rest cannot be read (missing / broken, or an r4 capture's bare `more: true`) keeps `more: true` — its
    areas are a HEAD only, and `apply_reading` then widens to the conservative superset."""
    import json
    fields = getattr(block, "fields", None)
    items = list(fields) if isinstance(fields, list) else list((block or {}).items()) if isinstance(block, dict) else []
    vals = [(k, v) for k, v in items if str(k).startswith(READING_FIELD)]
    if not vals:
        return None, "legacy"
    cont = dict((str(k), v) for k, v in items if str(k).startswith(READING_MORE))
    out = []
    for k, v in vals:
        try:
            e = json.loads(markers.unescape(v))
        except (TypeError, ValueError):
            return None, "unreadable"
        if not isinstance(e, dict) or e.get("token") != k[len(READING_FIELD):]:
            return None, "unreadable"
        m = e.get("more")
        if isinstance(m, int) and not isinstance(m, bool) and m > 0:
            extra = []
            for n in range(1, m + 1):
                try:
                    c = json.loads(markers.unescape(cont.get("%s%s-%d" % (READING_MORE, e["token"], n))))
                except (TypeError, ValueError):
                    c = None
                if not isinstance(c, list) or not all(isinstance(x, str) for x in c):
                    extra = None
                    break
                extra += c
            if extra is None:
                e["more"] = True               # the rest is lost — a head only
            else:
                e["areas"] = list(e.get("areas") or []) + extra
                e.pop("more")
        elif m:
            e["more"] = True
        out.append(e)
    return sorted(out, key=lambda e: e["token"]), None


def _raw_of(e):
    """A captured entry in the judge's per-reading shape (`own_footprints`) — K6 r4 m1."""
    return {"areas": list(e.get("areas") or []), "ui_surface": bool(e.get("ui_surface")),
            "safety_net_visual": bool(e.get("safety_net_visual")),
            "cast": {"participation": list(e.get("participation") or []), "gates": list(e.get("gates") or [])},
            "skipped": list(e.get("skipped") or []), "po": {"convene": bool(e.get("po_convene"))},
            "work_type": e.get("work_type")}


def apply_reading(k, capture, token, root, widen=()):
    """The person's reading (`token` of the question-time `capture`) as THIS run's KICKOFF result: the readings,
    tokens and aliases of that question, `chosen` = the person's, and its footprint (areas re-checked to exist).
    K6 r4 m1: every reading's own footprint is the captured one from now on (`own_footprints` re-keyed to the captured
    tokens — a later capture in this run never pairs a token with another reading's footprint).
    K6 r5 m3: an entry whose areas are a head only (`more: true` — its rest was lost) is never taken as the whole
    footprint: its areas widen to the conservative superset (every captured reading's areas, this run's judge areas
    and `widen` — the explorer's directories).
    Returns the captured entry, or None (the token is not one of the captured readings)."""
    ent = next((e for e in capture or () if e.get("token") == token), None)
    if ent is None:
        return None
    judge_areas = list(k.areas or ())
    k.interpretations = [{"id": e["token"], "summary": e.get("summary") or "", "orig": e.get("orig") or ""}
                         for e in capture]
    k.token_map = [{"token": i["id"], "orig": i["orig"]} for i in k.interpretations]
    k.aliases = dict((i["id"], [i["orig"], i["summary"]]) for i in k.interpretations)
    k.own_footprints = dict((e["token"], _raw_of(e)) for e in capture)
    k.chosen = token
    areas = list(ent.get("areas") or [])
    if ent.get("more"):
        sup = set(areas) | set(judge_areas) | set(widen or ())
        for e in capture:
            sup |= set(e.get("areas") or ())
        areas = sorted(sup)
        k.coerced.append("reading %s: its captured areas were cut — the conservative superset (%d areas)"
                         % (token, len(areas)))
    k.areas = real_dirs(root, areas)
    k.ui_surface = bool(ent.get("ui_surface"))
    k.safety_net_visual = bool(ent.get("safety_net_visual")) and k.safety_net_visual_possible
    k.cast = {"participation": list(ent.get("participation") or []), "gates": list(ent.get("gates") or []),
              "skipped": list(ent.get("skipped") or [])}
    k.po = dict(k.po, convene=bool(ent.get("po_convene")))
    if ent.get("work_type") in WORK_TYPES:
        k.work_type = ent["work_type"]
    return ent


def footprint_of(k):
    """K6 r5 m6: this run's judge's top-level footprint (before `apply_reading` replaces it)."""
    return {"areas": list(k.areas or ()), "ui_surface": bool(k.ui_surface),
            "safety_net_visual": bool(k.safety_net_visual),
            "participation": list(k.cast.get("participation") or ()), "gates": list(k.cast.get("gates") or ()),
            "po_convene": bool(k.po.get("convene"))}


def widen_reading(k, fp):
    """K6 r5 m6: a judge that TOOK the person's reading wrote its top-level footprint for that reading — the result is
    the UNION of it and the question-time capture (areas · roles), `ui_surface` / `safety_net_visual` / PO OR-ed:
    the conservative side (a capture is often a rough estimate of a reading the judge did not choose then)."""
    k.areas = sorted(set(k.areas or ()) | set(fp.get("areas") or ()))
    k.ui_surface = bool(k.ui_surface or fp.get("ui_surface"))
    k.safety_net_visual = bool((k.safety_net_visual or fp.get("safety_net_visual")) and k.safety_net_visual_possible)
    gates = set(k.cast.get("gates") or ()) | set(fp.get("gates") or ())
    part = (set(k.cast.get("participation") or ()) | set(fp.get("participation") or ())) - gates
    k.cast = {"participation": sorted(part), "gates": sorted(gates),
              "skipped": [x for x in k.cast.get("skipped") or () if not any(
                  str(x).startswith(r) for r in part | gates)]}
    k.po = dict(k.po, convene=bool(k.po.get("convene") or fp.get("po_convene")))


# K6 r5 M1 / m1: the person's reading is handed to the judge under this FIXED engine id (never the judge's earlier id —
# a judge re-letters freely and may list its own reading under that letter) with the reading's exact text. Taking it
# is STRUCTURAL: `chosen` is this id. The engine then runs the STORED reading (the capture's summary and footprint —
# `apply_reading`), whatever words the judge gives it, so a re-wording costs nothing (m1). Text closeness is never
# evidence of taking ("로그인 화면만" ← "로그인 화면 제외" — closeness cannot see a negation).
# K6 r6 M1: but exact (normalised) EQUALITY is decidable and is evidence against: the judge's text under the fixed id
# that IS another captured reading's text, or the person's reading's text under another id, is the judge putting
# another reading under the person's name — not taken. What stays unchecked is the judge's AC / readiness under a
# taken id (they are the judge's words for "this reading"): their fidelity to the person's reading is checked only
# post hoc (the KICKOFF grading-sheet row, the design stage) — k6-notes r6.
PERSON_READING_ID = "person-reading"


def _same_text(judge_text, cap_text):
    """K6 r6 M1: equal after normalisation (NFKC, whitespace, case, a trailing full stop) — never closeness. A captured
    summary is stored cut (300 / 120 characters): a judge's longer text that starts with such a cut summary is the
    same text."""
    import unicodedata

    def n(x):
        x = " ".join(unicodedata.normalize("NFKC", str(x or "")).split()).casefold()
        return x.rstrip(" .。")
    j, c = n(judge_text), n(cap_text)
    if not c or not j:
        return False
    return j == c or (len(str(cap_text or "")) >= 120 and j.startswith(c))


def judge_took(fields, ent=None, capture=()):
    """Did this run's KICKOFF judge take the person's reading? K6 r5 M1: by STRUCTURE — its `chosen` is the fixed
    engine id `PERSON_READING_ID` and exactly one of its `interpretations` carries that id. Any other id (the judge's
    earlier letter included), the id absent or listed twice → not taken (user decision 2026-11-20: pause).
    K6 r6 M1: two exact-equality refutations (`_same_text`, no closeness): (a) the summary under the fixed id equals
    another captured reading's summary (`capture` other than `ent` — one whose text is not the person's own); (b) the
    person's reading's summary (`ent`) appears under any other id of the judge's list."""
    f = fields or {}
    norm = lambda x: " ".join(str(x or "").split()).casefold()              # noqa: E731
    pid = PERSON_READING_ID.casefold()
    if norm(f.get("chosen")) != pid:
        return False
    items = [i for i in (f.get("interpretations") or []) if isinstance(i, dict)]
    mine = [i for i in items if norm(i.get("id")) == pid]
    if len(mine) != 1:
        return False
    own = (ent or {}).get("summary") or ""
    others = [e.get("summary") for e in capture or () if isinstance(e, dict) and e is not ent
              and e.get("token") != (ent or {}).get("token") and not _same_text(e.get("summary"), own)]
    if any(_same_text(mine[0].get("summary"), o) for o in others):
        return False                       # (a) another offered reading's text under the person's id
    if own and any(_same_text(i.get("summary"), own) for i in items if norm(i.get("id")) != pid):
        return False                       # (b) the person's reading's text under another id
    return True


def canon_key(interp):
    """K5r4-m1: the content-based sort key of an interpretation — its whitespace-normalized, case-folded summary,
    then a hash of the judge's id (a tie between equal summaries never falls back to the judge's I1 < I2)."""
    import hashlib
    s = " ".join(str(interp.get("summary") or "").split()).casefold()
    return (s, hashlib.sha256(str(interp.get("id")).encode("utf-8")).hexdigest())


ID_EDGE = "A-Za-z0-9_-"            # `A-F13` is not the id `A`


HANGUL = "가-힣"


def id_regex(name):
    """A judge id / engine token as a whole word: case-insensitive (`I2` = `i2` to a reader), except a one-letter id,
    which matches its own case only (`A` is an id, `a` is an article) — K5r5-m5: or any case when a Hangul syllable
    follows it (`b안`, `b가`: no article reads that way)."""
    if len(name) == 1:
        e = re.escape(name)
        return re.compile(r"(?<![%s])(?:%s(?![%s])|(?i:%s)(?=[%s]))" % (ID_EDGE, e, ID_EDGE, e, HANGUL))
    return re.compile(r"(?<![%s])%s(?![%s])" % (ID_EDGE, re.escape(name), ID_EDGE), re.I)


def to_tokens(text, token_map):
    """K5r4-M1: the judge's text with its own interpretation ids (`I2`, `B`, `broad` — any case) replaced by the
    engine tokens the person sees (`i2`) — one simultaneous substitution (a judge id that spells another token,
    e.g. its `i1` that became `i2`, never chains). A purely numeric id is left alone (it would rewrite counts and
    AC numbers); the leak check still treats it as an alias (`predict.leak` — refused, the safe side)."""
    if not text or not token_map:
        return text
    ids = [(t["orig"].strip(), t["token"]) for t in token_map
           if t.get("orig") and t["orig"].strip() and not t["orig"].strip().isdigit()]
    if not ids:
        return text
    ids.sort(key=lambda x: len(x[0]), reverse=True)
    # a one-letter id: its own case at a word end, any case before a Hangul syllable (K5r5-m5: `b안` = `B안`)
    alt = "|".join(("(?:(?-i:%s)(?![%s])|%s(?=[%s]))" % (re.escape(o), ID_EDGE, re.escape(o), HANGUL)
                    if len(o) == 1 else "%s(?![%s])" % (re.escape(o), ID_EDGE)) for o, _t in ids)
    rx = re.compile(r"(?<![%s])(?:%s)" % (ID_EDGE, alt), re.I)
    exact = dict((o, t) for o, t in ids if len(o) == 1)
    one = dict((o.casefold(), t) for o, t in ids if len(o) == 1)
    folded = dict((o.casefold(), t) for o, t in ids if len(o) > 1)
    return rx.sub(lambda mo: exact.get(mo.group(0)) or one.get(mo.group(0).casefold()) or
                  folded[mo.group(0).casefold()], text)


def readiness_assumptions(k):
    """RD §C: every partial dimension is an explicit assumption (with what pointed at it)."""
    out = []
    for dim in DIMS:
        if k.readiness.get(dim) == "partial":
            a = k.anchors.get(dim) or {}
            out.append("%s: %s (근거: %s)" % (DIM_KEY[dim], k.choice_needed.get(dim) or "-",
                                             a.get("cite") or a.get("source") or "-"))
    return out


# ---- the record --------------------------------------------------------------------------------

def readiness_line(readiness, note=""):
    toks = " · ".join("%s=%s" % (DIM_KEY[d], readiness.get(d, "unclear")) for d in DIMS)
    return "Readiness: %s%s" % (toks, (" (%s)" % note) if note else "")


def render_output(issue, k, chosen_summary, note, trace, assumptions, po_line=None, extra=()):
    """analyze:output (A4). Machine lines ASCII; every free value through markers.value."""
    v = markers.value
    out = [markers.open_tag("analyze:output"), "## Guild analyze — #%d" % int(issue), "",
           readiness_line(k.readiness, v(note)),
           "work-type: %s" % k.work_type,
           "cast: %s" % (", ".join(k.cast["participation"] + k.cast["gates"]) or "none"), ""]
    out.append("### 해석")
    for i in k.interpretations:
        out.append("- %s%s: %s" % ("(선택) " if i["id"] == k.chosen else "", v(i["id"]), v(i["summary"])))
    if not k.interpretations:
        out.append("- %s" % v(chosen_summary or "-"))
    out += ["", "### 가정"]
    # `- 가정: …` — the C14 unattended log reads assumption lines in this form (unattended_log.ASSUMPTION_RE)
    out += ["- 가정: %s" % v(a) for a in assumptions] or ["- 없음 (readiness 가 간극을 찾지 못함)"]
    if k.features:
        out += ["", "### 기능"] + ["- %s" % v(x) for x in k.features]
    out += ["", "### 수용 기준"]
    for a in k.ac:
        tag = " (safety net)" if a["tag"] == "safety net" else ""
        pr = (" [%s]" % v(a["priority"])) if a["priority"] else ""
        out.append("- %s%s: %s%s" % (a["id"], tag, v(a["text"]), pr))
    if k.split_hint:
        out += ["", "분할 힌트: design 에서 분할 여부를 판단"]
    if po_line:
        out += ["", v(po_line)]
    for x in extra:
        out += ["", v(x)]
    if k.cast["skipped"]:
        out += ["", "### 소집하지 않은 역할"] + ["- %s" % v(s) for s in k.cast["skipped"]]
    out += ["", "<details><summary>preflight trace</summary>", ""]
    out += ["- %s" % v(t) for t in trace]
    out += ["", "</details>", markers.close_tag("analyze:output")]
    body = "\n".join(out)
    return markers.assert_own_markers(body, "analyze:output")


READINESS_RE = re.compile(r"Readiness\**\s*:\s*\**\s*Goal\s*=\s*\**(\w+)\**\s*·\s*Constraint\s*=\s*\**(\w+)\**"
                          r"(?:[^·\n]*?)·\s*Success\s*=\s*\**(\w+)")
AC_LINE_RE = re.compile(r"^\s*(?:[-*]|\|)?\s*\**\s*(AC\s*#?\s*-?\s*(\d+))\b\s*\**\s*(\(safety net\))?\s*[:：|.)\-—]*\s*(.*)$")
CAST_RE = re.compile(r"^cast:\s*(.*)$", re.M)
WT_RE = re.compile(r"^work-type:\s*(feature|bug|refactor)\s*$", re.M)
WT_LEGACY_RE = re.compile(r"type:(feature|bug|refactor)")


DIM_TOKEN_RE = dict((d, re.compile(r"%s\**\s*[=:]\s*\**\s*`?(clear|partial|unclear)\b" % DIM_KEY[d], re.I)) for d in DIMS)


def readiness_of(body):
    """The engine line (READINESS_RE) or, tolerant of the legacy forms (bold, parentheticals holding `·`,
    backticks), the three tokens on the first line naming `Readiness`. None when not all three are there."""
    m = READINESS_RE.search(body or "")
    if m:
        return dict(zip(DIMS, (m.group(1), m.group(2), m.group(3))))
    for ln in (body or "").split("\n"):
        if "readiness" not in ln.lower():
            continue
        got = {}
        for d in DIMS:
            mm = DIM_TOKEN_RE[d].search(ln)
            if mm:
                got[d] = mm.group(1).lower()
        if len(got) == 3:
            return got
    return None


class AnalyzeRecord(object):
    def __init__(self, body):
        self.body = body or ""
        self.readiness = readiness_of(self.body)
        seen, acs = set(), []
        for ln in self.body.split("\n"):
            mm = AC_LINE_RE.match(markers.clean(ln))
            if mm:
                n = int(mm.group(2))
                if n in seen:
                    continue
                seen.add(n)
                acs.append({"id": "AC #%d" % n, "n": n, "net": bool(mm.group(3)), "text": mm.group(4).strip()})
        self.ac = acs
        c = CAST_RE.search(self.body)
        self.cast = [x.strip() for x in c.group(1).split(",") if x.strip() and x.strip() != "none"] if c else None
        w = WT_RE.search(self.body) or WT_LEGACY_RE.search(self.body)
        self.work_type = w.group(1) if w else None
        self.engine = "\nwork-type: " in self.body


def parse_output(body):
    return AnalyzeRecord(body)


def ac_ids_in(text):
    """AC ids a document mentions (`AC #3`, `AC-3`, `AC3`, `AC 3`) → {3, …}."""
    return set(int(x) for x in re.findall(r"\bAC\s*[#-]?\s*(\d+)\b", text or ""))
