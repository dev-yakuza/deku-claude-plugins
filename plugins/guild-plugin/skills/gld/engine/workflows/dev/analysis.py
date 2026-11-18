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


def plan_decisions(body):
    blk = _block(body, PLAN_OPEN, PLAN_CLOSE)
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
    p = path.lstrip("./")
    for g in globs:
        if fnmatch.fnmatch(p, g) or (g.startswith("**/") and fnmatch.fnmatch(p, g[3:])):
            return True
    return False


def harness_hit(paths):
    return sorted(set(p for p in paths if p and _glob_match(p, HARNESS_GLOBS)))


def harness_text_hit(texts):
    """A harness path named in free text (AC / areas) — `.claude/settings*.json`, gates."""
    rx = re.compile(r"\.claude/(?:settings[A-Za-z0-9_.-]*\.json|guild/gates(?:/[\w./-]*)?)")
    out = set()
    for t in texts:
        out.update(rx.findall(t or ""))
    return sorted(out)


def irreversible(paths, globs=None):
    gl = tuple(globs) if globs else IRREVERSIBLE_DEFAULT
    return sorted(set(p for p in paths if p and _glob_match(p, gl)))


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
        self.interpretations = []     # [{id, summary}]
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


def coerce_kickoff(fields, root, sources, net_lines, plan_lines, premise_unmet_dims, roster,
                   tracked=None, attended=False):
    k = Kickoff()
    f = fields or {}
    interp = [i for i in (f.get("interpretations") or []) if isinstance(i, dict) and i.get("id")][:5]
    # ids become answer tokens `i1`…`i5` (the judge's own ids are free text — §2.5 token grammar)
    k.interpretations = [{"id": "i%d" % (n + 1), "summary": str(i.get("summary") or ""),
                          "orig": str(i["id"])[:40]} for n, i in enumerate(interp)]
    by_orig = dict((i["orig"], i["id"]) for i in k.interpretations)
    ids = [i["id"] for i in k.interpretations]
    k.chosen = by_orig.get(str(f.get("chosen"))) or (ids[0] if ids else None)
    if str(f.get("chosen")) not in by_orig and ids:
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
        k.choice_needed[dim] = str(r.get("choice_needed") or "")
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
    k.areas = real_dirs(root, f.get("areas") or [])
    dropped = [a for a in f.get("areas") or [] if isinstance(a, str) and os.path.normpath(a.strip().rstrip("/")) not in k.areas]
    if dropped:
        k.coerced.append("areas dropped (not a repo directory): %s" % ", ".join(str(x) for x in dropped[:5]))
    cl = f.get("close") or {}
    dec = cl.get("decide") if cl.get("decide") in ("none", "completed", "not_planned") else "none"
    k.close = {"decide": dec, "source": cl.get("source"), "line": cl.get("line") or ""}
    if dec != "none":
        from_plan = cl.get("source") == "plan_line" and any(
            _norm(cl.get("line")) and (_norm(cl.get("line")) == _norm(pl.raw) or _norm(cl.get("line")) in _norm(pl.raw))
            for pl in plan_lines)
        k.close["from_plan"] = from_plan
        if not from_plan and not attended:
            k.coerced.append("close without a plan-decision line → high ambiguity (unattended)")
    st = f.get("surface_to_human") or {}
    k.surface = {"ask": bool(st.get("ask")), "question": str(st.get("question") or "")}
    return k


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
