#!/usr/bin/env python3
"""replay.procedure — the procedure replay for test/qa (§10.2-2): legacy sprint logs → fake GitHub →
the ENGINE's stage code with canned role/judge/suite results → compare what it writes with what the
legacy session wrote.

1. **Episodes**: each `/gld dev` sprint log (stream-json) is cut where the session read a stage
   wrapper (`commands/test.md`, `commands/qa.md`); an episode ends at its first label edit that
   leaves the stage (or a needs-human add), or at the next wrapper read. Logs of one Issue are
   chained in time order so the GitHub state at an episode's start (labels from the episode's own
   label read; comments = every marker body posted earlier — test evidence, loop-back record,
   follow-ups …) is reconstructed from the logs themselves.
2. **Canned inputs** (frozen per episode): the suite summary line (from the legacy test:output, or
   synthesised from the outcome), the tester/qa/designer RESULT lines, the E2E string, the AC ids,
   the check-runs JSON the legacy session read, the legacy manual-qa items and follow-up titles.
   **Injected** (design §10.2-2 — legacy values, so differences unrelated to engine correctness
   vanish): loop-back `reason`/`signature`/`at`/`branch`, every judgment (TEST, QA, PRMATCH,
   FOLLOWUP, VIS-ENV), the Q-UI-CONVENE diff, the PR the legacy session used.
3. **Comparison** per episode:
   * structural layer — a byte projection of the label-edit sequence and, per written marker, its
     machine skeleton (markers, headings, keys, ASCII tokens, verbatim ledger blocks, the PR body
     outside the manual-qa block); elements governed by a prose rule the log's own wrapper text did
     not carry yet (older plugin versions) are excluded as prose-version drift and counted;
   * prose marker fields — the values of machine keys (loop-back reason/signature/branch/from, the
     cause line, the E2E line, `PR CI:` value, follow-up titles, checklist items) compared after
     whitespace normalisation.
   Every differing element is classified against the design's lists (§6.2 C1–C14, §7 rows) or as a
   defect.

    procedure.py --logs '<glob>' --config <repo config.json> --out <dir> [--limit N]
"""

import argparse
import difflib
import glob
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from guildcore.adapters.gh import FakeGh, FakeGhWrite          # noqa: E402
from guildcore.checks import CheckResult                       # noqa: E402
from guildcore.decisions import DecisionWriter                 # noqa: E402
from guildcore.judges.runner import Decision                   # noqa: E402
from guildcore.records import followups as FU                  # noqa: E402
from guildcore.records import loopback as LB                   # noqa: E402
from guildcore.records import manual_qa as MQ                  # noqa: E402
from guildcore.records import markers                          # noqa: E402
from guildcore.records import needs_human as NH                # noqa: E402
from guildcore.records.write import GhWriter                   # noqa: E402
from guildcore.roles.runner import RoleResult                  # noqa: E402
from workflows.dev.stages import base as B                     # noqa: E402

WRAP_RE = re.compile(r"skills/gld/commands/(test|qa|implement|debug|refactor|analyze|design)\.md")
MARK_RE = re.compile(r"^<!-- guild:([a-z0-9:-]+) -->")
LABEL_RE = re.compile(r"--(add|remove)-label[ =]\"?(guild:[a-z-]+|[^\s\"]+)\"?")
SUMMARY_RE = re.compile(r"\d\d:\d\d \+\d+(?: ~\d+)?(?: -\d+)?: (?:All tests passed!|Some tests failed\.)")
CASE_RE = re.compile(r"\b(AC ?#\d+|C\d{1,3})\b")
RESULT_RE = re.compile(r">>> RESULT <<<\s*\n\s*(DONE_WITH_CONCERNS|DONE|BLOCKED|NEEDS_CONTEXT|FAIL)(?::\s*([^\n]*))?")
E2E_RE = re.compile(r"(E2E 불요:[^\n]*|E2E 회귀 실행 필요:[^\n]*)")
E2E_LOOSE = re.compile(r"E2E (불요|회귀 실행 필요)\**\s*[:：—–-]?\s*\**\s*([^\n]*)")


def e2e_of(text):
    """The legacy E2E judgment, normalised to the literal form (`E2E 불요: …`)."""
    ms = list(E2E_LOOSE.finditer(text or ""))
    if not ms:
        return ""
    m = ms[-1]
    rest = m.group(2).strip().strip("*").strip()
    return "E2E %s: %s" % (m.group(1), rest or "-")
CI_LINE_RE = re.compile(r"^PR CI: ?(.*)$", re.M)
HOST = "macOS arm64"


# ---- log parsing ----------------------------------------------------------------------------------

def _text(cont):
    if isinstance(cont, str):
        return cont
    return "\n".join(x.get("text", "") for x in cont or [] if isinstance(x, dict))


def steps_of(path):
    """Top-level tool steps in order: dicts {id, name, input, result}."""
    out, by = [], {}
    with open(path, errors="replace") as fh:
        for ln in fh:
            if not ln.startswith("{"):
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if e.get("parent_tool_use_id"):
                continue
            msg = e.get("message") or {}
            for c in msg.get("content") if isinstance(msg.get("content"), list) else []:
                if c.get("type") == "tool_use":
                    st = {"id": c["id"], "name": c.get("name"), "input": c.get("input") or {}, "result": None}
                    by[c["id"]] = st
                    out.append(st)
                elif c.get("type") == "tool_result" and c.get("tool_use_id") in by:
                    by[c["tool_use_id"]]["result"] = _text(c.get("content"))
    return out


def wrapper_of(st):
    s = st["input"].get("command") or st["input"].get("file_path") or ""
    m = WRAP_RE.search(s)
    if not m:
        return None
    if st["name"] == "Read" or re.match(r"\s*(cat|sed|head)\b", s):
        return m.group(1)
    return None


def label_edit(st, n):
    c = st["input"].get("command") or ""
    if st["name"] != "Bash" or not re.search(r"gh issue edit %d\b" % n, c):
        return None
    adds = [m.group(2) for m in LABEL_RE.finditer(c) if m.group(1) == "add" and m.group(2).startswith("guild:")]
    rems = [m.group(2) for m in LABEL_RE.finditer(c) if m.group(1) == "remove" and m.group(2).startswith("guild:")]
    return (adds, rems) if adds or rems else None


def _json_after_banner(text):
    for ln in (text or "").split("\n"):
        ln = ln.strip()
        if ln.startswith("[") or ln.startswith("{"):
            try:
                return json.loads(ln)
            except ValueError:
                continue
    return None


class Episode(object):
    def __init__(self, log, issue, stage, prose):
        self.log, self.issue, self.stage, self.prose = log, issue, stage, prose
        self.steps = []
        self.start_labels = None
        self.state = None              # reconstructed comments/prs at start
        self.version = None

    @property
    def key(self):
        return "%s#%s:%s" % (os.path.basename(self.log), self.issue, self.stage)


def issue_of(path):
    m = re.search(r"issue-(\d+)-", os.path.basename(path))
    return int(m.group(1)) if m else None


def plugin_version(path):
    """guild-plugin's version from the log's system/init plugin list (None when absent — a
    session run from a source checkout lists no guild-plugin)."""
    with open(path, errors="replace") as fh:
        for ln in fh:
            if '"subtype":"init"' not in ln.replace(" ", ""):
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                return None
            for pl in e.get("plugins") or []:
                if isinstance(pl, dict) and pl.get("name") == "guild-plugin":
                    return pl.get("version")
            return None
    return None


class State(object):
    """GitHub as the logs show it: marker bodies posted so far (issue + PR), PR bodies."""

    def __init__(self):
        self.issue = {}           # marker → latest body (needs-human: list)
        self.pauses = []
        self.pr_comments = {}     # (pr, marker) → body
        self.pr_bodies = {}
        self.labels = None        # guild:* labels as last read/edited
        self.evidence_untracked = False

    def apply_write(self, body, target_pr=None):
        m = MARK_RE.match(body or "")
        if not m:
            return
        name = m.group(1)
        if name.startswith("followups:pr:") and target_pr:
            self.pr_comments[(target_pr, name)] = body
        elif name == "needs-human":
            self.pauses.append(body)
        else:
            self.issue[name] = body

    def comments(self):
        out, cid = [], 100
        for name, body in sorted(self.issue.items()):
            cid += 1
            out.append({"id": cid, "body": body, "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z", "author_association": "OWNER",
                        "user": {"login": "guild"}})
        for body in self.pauses:
            cid += 1
            out.append({"id": cid, "body": body, "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z", "author_association": "OWNER",
                        "user": {"login": "guild"}})
        return out


BODY_FILE_RE = re.compile(r"(?:--body-file|body=@)\s*['\"]?([^\s'\"]+)")


HEREDOC_RE = re.compile(r"cat\s+(?:>\s*(?P<p1>\S+)\s+<<-?\s*['\"]?(?P<t1>\w+)['\"]?|<<-?\s*['\"]?(?P<t2>\w+)['\"]?\s*>\s*(?P<p2>\S+))\n"
                        r"(?P<body>.*?)\n(?P=t1)?(?P=t2)?\s*$", re.S)


SED_RE = re.compile(r"sed -i (?:''\s+)?'s/(?P<pat>(?:[^/\\]|\\.)*)/(?P<rep>(?:[^/\\]|\\.)*)/(?P<g>g?)'\s+(?P<path>\S+)")


class Files(object):
    """The session's temp files: Write sets, Edit patches — what a later `--body-file` posts."""

    def __init__(self):
        self.files = {}

    def step(self, st):
        inp = st["input"]
        if st["name"] == "Write" and inp.get("file_path"):
            self.files[inp["file_path"]] = inp.get("content") or ""
        elif st["name"] == "Bash":
            sm = SED_RE.search(inp.get("command") or "")
            if sm and sm.group("path") in self.files:
                flags = re.M if not sm.group("g") else re.M
                try:
                    self.files[sm.group("path")] = re.sub(sm.group("pat"), sm.group("rep").replace("\\/", "/"),
                                                          self.files[sm.group("path")], 0 if sm.group("g") else 1, flags)
                except re.error:
                    pass
            m = HEREDOC_RE.search(inp.get("command") or "")
            if m:
                self.files[m.group("p1") or m.group("p2")] = m.group("body") + "\n"
        elif st["name"] == "Edit" and inp.get("file_path") in self.files:
            cur = self.files[inp["file_path"]]
            old, new = inp.get("old_string") or "", inp.get("new_string") or ""
            if old and old in cur:
                self.files[inp["file_path"]] = cur.replace(old, new) if inp.get("replace_all") else cur.replace(old, new, 1)


def post_of(st, files, issue):
    """A Bash step that posts a body: (kind, number, body) — kind issue | pr-comment | pr-body."""
    if st["name"] != "Bash":
        return None
    c = st["input"].get("command") or ""
    m = BODY_FILE_RE.search(c)
    if not m:
        return None
    path = m.group(1)
    if path not in files.files:
        rel = path[2:] if path.startswith("./") else path
        hits = [k for k in files.files if k.endswith("/" + rel)]
        if not hits:
            return None
        path = hits[-1]
    body = files.files[path]
    r = re.search(r"gh pr edit (\d+)", c)
    if r:
        return ("pr-body", int(r.group(1)), body)
    r = re.search(r"gh pr comment (\d+)", c)
    if r:
        return ("pr-comment", int(r.group(1)), body)
    r = re.search(r"gh issue comment (\d+)", c) or re.search(r"issues/(\d+)/comments", c)
    if r:
        n = int(r.group(1))
        return ("issue" if n == issue else "pr-comment", n, body)
    if re.search(r"issues/comments/\d+", c):
        mm = MARK_RE.match(body or "")
        if mm and mm.group(1).startswith("followups:pr:"):
            return ("pr-comment", None, body)
        return ("issue", issue, body)
    return None


def episodes(paths):
    by_issue = {}
    for p in sorted(paths):
        n = issue_of(p)
        if n:
            by_issue.setdefault(n, []).append(p)
    out = []
    for n, logs in sorted(by_issue.items()):
        state = State()
        for log in sorted(logs, key=lambda x: (re.sub(r"-attempt\d+", "", os.path.basename(x)), x)):
            steps = steps_of(log)
            files = Files()
            ver = plugin_version(log)
            cur = None
            for i, st in enumerate(steps):
                w = wrapper_of(st)
                if w:
                    if cur is not None and cur.stage == w:
                        continue
                    prose = st["result"] or ""
                    if "<persisted-output>" in prose:     # a long wrapper is read back from tool-results
                        pm = re.search(r"saved to: (\S+)", prose)
                        for nx in steps[i + 1:i + 6]:
                            if pm and nx["name"] == "Read" and nx["input"].get("file_path") == pm.group(1):
                                prose = (nx["result"] or "") + prose
                                break
                    cur = Episode(log, n, w, prose) if w in ("test", "qa") else None
                    if cur is not None:
                        cur.version = ver
                        cur.prior_labels = list(state.labels) if state.labels is not None else None
                        cur.state = json.loads(json.dumps({"issue": state.issue, "pauses": state.pauses,
                                                           "evidence_untracked": state.evidence_untracked,
                                                           "pr_comments": {"%d|%s" % k: v for k, v in state.pr_comments.items()},
                                                           "pr_bodies": {str(k): v for k, v in state.pr_bodies.items()}}))
                        out.append(cur)
                    continue
                files.step(st)
                cmd0 = st["input"].get("command") or ""
                if st["name"] == "Bash" and re.search(r"python|perl", cmd0) and (
                        "test-evidence" in cmd0 or any(k in cmd0 for k, v in files.files.items()
                                                       if v.startswith("<!-- guild:test-evidence"))):
                    state.evidence_untracked = True        # a script edit the replay cannot follow
                if st["name"] == "Bash" and re.search(r"gh issue view %d\b.*labels" % n, st["input"].get("command") or ""):
                    j = _json_after_banner(st["result"])
                    j = j.get("labels") if isinstance(j, dict) else j
                    if isinstance(j, list):
                        state.labels = [x if isinstance(x, str) else (x or {}).get("name") for x in j]
                        state.labels = [x for x in state.labels if x and x.startswith("guild:")]
                le0 = label_edit(st, n)
                if le0 and state.labels is not None:
                    state.labels = [x for x in state.labels if x not in le0[1]] + [a for a in le0[0] if a not in state.labels]
                po = post_of(st, files, n)
                if po:
                    if po[0] == "pr-body":
                        state.pr_bodies[po[1]] = po[2]
                    else:
                        state.apply_write(po[2], po[1] if po[0] == "pr-comment" else None)
                if cur is not None and not getattr(cur, "closed", False):
                    cur.steps.append((i, st, dict(files.files)))
                    if cur.start_labels is None and st["name"] == "Bash" and re.search(
                            r"gh issue view %d\b.*--json [a-z,]*labels" % n, st["input"].get("command") or ""):
                        j = _json_after_banner(st["result"])
                        if isinstance(j, list):
                            cur.start_labels = [x for x in j if isinstance(x, str)]
                    le = label_edit(st, n)
                    if le and (any(a in ("guild:execute", "guild:qa", "guild:done", "guild:needs-human") for a in le[0])):
                        cur.closed = True
    return out


# ---- legacy view of one episode -------------------------------------------------------------------

class Legacy(object):
    def __init__(self, ep):
        self.labels = []
        self.writes = {}          # marker → body (latest in the episode)
        self.pauses = []
        self.pr_body = None
        self.pr = None
        self.pr_comment = {}
        self.roles = {}           # description prefix → (status, line)
        self.check_runs = None
        self.annotations = {}
        self.designer = False
        self.spawns = {}
        self.head = None
        for i, st, steps in ep.steps:
            le = label_edit(st, ep.issue)
            if le:
                self.labels.append(le)
            c = st["input"].get("command") or ""
            m = re.search(r"gh pr (?:view|edit|comment) (\d+)", c)
            if m and int(m.group(1)) != ep.issue:
                self.pr = self.pr or int(m.group(1))
            if "headRefOid" in c and st["result"]:
                hm = re.search(r"\b([0-9a-f]{40})\b", st["result"])
                if hm:
                    self.head = hm.group(1)            # the LATEST head (qa may have pushed)
            if "check-runs" in c and "/annotations" not in c and st["result"] and \
                    (self.check_runs is None or not self.head or self.head in c):
                rows = []
                for ln in st["result"].split("\n"):
                    ln = ln.strip()
                    if ln.startswith("{"):
                        try:
                            rows.append(json.loads(ln))
                        except ValueError:
                            pass
                self.check_runs = rows
            m = re.search(r"check-runs/(\d+)/annotations", c)
            if m:
                self.annotations[m.group(1)] = [x for x in (st["result"] or "").split("\n")[1:] if x.strip()]
            if st["name"] in ("Agent", "Task"):
                d = st["input"].get("description") or ""
                rm = RESULT_RE.search(st["result"] or "")
                key = "designer" if "designer" in d else ("tester" if "tester" in d else ("qa" if d.startswith("qa") else d))
                if key == "designer":
                    self.designer = True
                self.spawns[key] = self.spawns.get(key, 0) + 1
                self.roles[key] = (rm.group(1), (rm.group(2) or "").strip()) if rm else ("DONE", "")
            fl = Files()
            fl.files = steps
            po = post_of(st, fl, ep.issue)
            if not po:
                continue
            kind, num, body = po
            if kind == "pr-body":
                self.pr_body, self.pr = body, num
                continue
            mm = MARK_RE.match(body)
            if not mm:
                continue
            name = mm.group(1)
            if name == "needs-human":
                self.pauses.append(body)
            elif name.startswith("followups:pr:"):
                self.pr_comment[name] = body
                if num:
                    self.pr = self.pr or num
            elif kind == "issue":
                self.writes[name] = body

    def outcome(self):
        adds = [a for a, _r in self.labels for a in a]
        if "guild:execute" in adds and "guild:needs-human" in adds:
            return "PAUSE:pending"
        if "guild:execute" in adds:
            return "LOOPBACK"
        if "guild:needs-human" in adds or self.pauses:
            return "PAUSE"
        if "guild:qa" in adds:
            return "ADVANCE"
        if "guild:done" in adds:
            return "DONE"
        return None


# ---- engine run -----------------------------------------------------------------------------------

class ReplayGh(FakeGh):
    def __init__(self, fx, prs):
        FakeGh.__init__(self, fx)
        self._prs = prs

    def pr_search(self, n):
        self.calls.append(("pr_search", n))
        return [dict(p) for p in self.fx.get("prs", [])]


class Clock(object):
    def __init__(self, at=None):
        self.at, self.n = at, 0

    def now(self):
        self.n += 1
        return self.at or "2026-11-16T00:%02d:%02dZ" % (self.n // 60, self.n % 60)


def _dec(choice, fields):
    return Decision(choice, fields, "judge:replay", "r" * 12, False, False, None, None)


def _ac_ids(text):
    ids = []
    for m in CASE_RE.finditer(text or ""):
        k = m.group(1).replace(" ", " ")
        if k not in ids:
            ids.append(k)
    return ids or ["C1"]


def _items(block):
    return [markers.clean(l)[6:] for l in (block or "").split("\n") if markers.clean(l).startswith("- [ ] ")]


RANGE_RE = re.compile(r"\b([A-Z]{1,3}-?)(\d+)\s*[–~-]\s*(?:\1)?(\d+)\b")
GAP_WORDS = re.compile(r"미커버|uncovered|커버 ?안 ?됨|커버되지 않|\bAC gap\b|누락된|미충족|not covered|공허 테스트로|vacuous", re.I)
ALL_WORDS = re.compile(r"모두|전부|전수|전 ID|전 항목|전 케이스|\ball\b|\bPASS\b|직접 커버|커버됨|covered|green", re.I)
LETTER_RANGE = re.compile(r"\b([A-Z])\s*[~–-]\s*([A-Z])\b")


def coverage_section(tout):
    lines = (tout or "").split("\n")
    out, on = [], False
    for ln in lines:
        if re.match(r"^#{2,4} ", ln):
            on = bool(re.search(r"커버|[Cc]overage|AC", ln)) and "검증 범위" not in ln
            continue
        if on:
            out.append(ln)
    return "\n".join(out)


def prose_verdicts(ids, tout):
    """K2-M7 (d): per case id, the legacy LEADER'S coverage statement (not the label outcome):
    a mention on a gap line → not_covering; a mention, or a section-wide "all covered" → effective;
    neither → unsure. Ranges `C1–C12` expand."""
    sec = coverage_section(tout)
    exp = sec
    for m in RANGE_RE.finditer(sec):
        a, b = int(m.group(2)), int(m.group(3))
        if 0 < b - a < 80:
            exp += "\n" + " ".join("%s%d" % (m.group(1), k) for k in range(a, b + 1)) + \
                (" gap" if GAP_WORDS.search(sec[max(0, m.start() - 80):m.end() + 80].split("\n")[0]) else "")
    for m in LETTER_RANGE.finditer(sec):                 # `A~H 전 ID` → every id with those prefixes
        if not GAP_WORDS.search(sec[max(0, m.start() - 80):m.end() + 80]):
            exp += "\n" + " ".join(i for i in ids if i[:1].isalpha() and m.group(1) <= i[:1] <= m.group(2)
                                   and not i.startswith("AC"))
    blanket = bool(ALL_WORDS.search(sec)) and not GAP_WORDS.search(sec)
    out = {}
    for i in ids:
        rx = re.compile(r"(?<![A-Za-z0-9])%s(?![0-9])" % re.escape(i.lstrip("#")))
        hits = [ln for ln in exp.split("\n") if rx.search(ln)]
        if hits:
            out[i] = "not_covering" if any(GAP_WORDS.search(h) for h in hits) else "effective"
        else:
            out[i] = "effective" if blanket else "unsure"
    return out


def build(ep, leg, cfg, work, real_tc=None):
    """Fake GitHub + ports for one episode. Returns (ports, gh, writer_calls, injected)."""
    n = ep.issue
    labels = list(ep.start_labels or getattr(ep, "prior_labels", None) or ["guild:%s" % ep.stage])
    if "guild:%s" % ep.stage not in labels and not any(l in labels for l in ("guild:children", "guild:sprint")):
        labels = [l for l in labels if l in ("guild:child", "guild:needs-human", "guild:harness")] + ["guild:%s" % ep.stage]
    comments = State()
    comments.issue = dict(ep.state["issue"])
    comments.pauses = list(ep.state["pauses"])
    fx = {"repo": "o/r", "issues": {str(n): {"number": n, "title": "t", "body": "Issue #%d" % n, "state": "OPEN",
                                             "url": "https://github.com/o/r/issues/%d" % n,
                                             "labels": [{"name": l} for l in labels],
                                             "comments": comments.comments(), "timeline": []}},
          "prs": [], "check_runs": {}, "annotations": {}}
    inj = {}
    pr_n = leg.pr
    if ep.stage == "qa" and pr_n:
        body_after = leg.pr_body
        if body_after is not None:
            sp = markers.marker_span(body_after, MQ.NAME)
            before = body_after[:sp[0]].rstrip("\n") + "\n" + body_after[sp[1]:].lstrip("\n") if sp else body_after
            if sp and not body_after[sp[1]:].strip():
                before = body_after[:sp[0]].rstrip("\n") + "\n"
        else:
            before = ep.state["pr_bodies"].get(str(pr_n)) or "Closes #%d\n" % n
        fx["prs"] = [{"number": pr_n, "url": "https://github.com/o/r/pull/%d" % pr_n, "state": "OPEN",
                      "title": "pr", "body": before, "headRefOid": "f" * 40}]
        fx["issues"][str(pr_n)] = {"number": pr_n, "labels": [], "url": "https://github.com/o/r/pull/%d" % pr_n,
                                   "comments": [{"id": 900 + i, "body": b, "created_at": "2026-01-01T00:00:00Z",
                                                 "updated_at": "2026-01-01T00:00:00Z"}
                                                for i, (k, b) in enumerate(sorted(ep.state["pr_comments"].items()))
                                                if k.startswith("%d|" % pr_n)]}
        fx["check_runs"]["f" * 40] = leg.check_runs or []
        fx["annotations"] = leg.annotations
        inj["pr"] = pr_n
    gh = ReplayGh(fx, fx["prs"])
    lb_body = leg.writes.get("loopback")
    lb_blk = LB.LoopbackRecord.parse(lb_body).latest_active() if lb_body else None
    clock = Clock(lb_blk.get("at") if lb_blk else None)
    w = FakeGhWrite(gh, clock)
    writer = GhWriter(gh, w, sleep=lambda s: None)
    decisions = DecisionWriter(writer, n, clock)
    root = tempfile.mkdtemp(prefix="ep-", dir=work)
    out = leg.outcome()
    tout = leg.writes.get("test:output") or ep.state["issue"].get("test:output") or ""
    acs = _ac_ids(tout)
    _write(root, "docs/specs/%d/test-cases.md" % n, "\n".join("| %s | case |" % a for a in acs) + "\n")
    _write(root, "test/replay_test.dart", "void main() { test('t', () { expect(subject(), 1); }); }\n")
    if "followups" in leg.writes or ep.state["issue"].get("followups"):
        _write(root, "docs/specs/%d/skeleton.md" % n, "# skeleton\n")
    sig = markers.unescape(lb_blk.get("signature") or "") if lb_blk else None
    reason = markers.unescape(lb_blk.get("reason") or "") if lb_blk else None
    if lb_blk is not None:
        inj["loopback"] = {"reason": reason, "signature": sig, "at": lb_blk.get("at"), "branch": lb_blk.get("branch")}

    roles, judges, suites = [], {}, []
    derived = ep.stage == "test" and bool(real_tc) and bool(SUMMARY_RE.search(tout))
    inj["derived"] = derived
    if derived:
        from workflows.dev import cases as CSM
        _write(root, "docs/specs/%d/test-cases.md" % n, real_tc)
        ids = CSM.case_ids(real_tc)
        m = SUMMARY_RE.findall(tout)
        green = any("All tests passed" in x for x in m)
        line = [x for x in m if ("All tests passed" in x) == green][-1]
        suites.append(CheckResult(green, 0 if green else 1, False, line + "\n", [{"cmd": "replay", "rc": 0 if green else 1,
                                                                                  "timed_out": False}], 3600))
        st, ln = leg.roles.get("tester", ("DONE", ""))
        covers = [{"test": "test/replay_test.dart::t", "ac": a, "kind": "guard"} for a in ids]
        roles.append(RoleResult(st, ln, {"covers": covers, "e2e": e2e_of(tout)}))
        verdicts = prose_verdicts(ids, tout)
        inj["verdicts"] = {k: sum(1 for x in verdicts.values() if x == k) for k in ("effective", "not_covering", "unsure")}
        f = {"ac": [{"id": a, "covered_by": ["test/replay_test.dart::t"], "verdict": v, "why": "legacy prose"}
                    for a, v in verdicts.items()], "visual_rows": [],
             "overall": "all_effective" if all(v == "effective" for v in verdicts.values()) else "gap"}
        judges["TEST"] = [_dec(f["overall"], f), _dec(f["overall"], json.loads(json.dumps(f)))]
        roles.append(RoleResult("DONE", "", {"covers": covers}))
        judges["DWC"] = [_dec("other", {"verdict": "other"})]
        judges["VIS-ENV"] = [_dec("regression", {"verdict": "regression"})]
        judges["RUNNER"] = [_dec("green" if green else "red", {"verdict": "green" if green else "red"})]
    elif ep.stage == "test":
        m = SUMMARY_RE.findall(tout)
        green = out in ("ADVANCE",) or (out == "LOOPBACK" and m and "All tests passed" in m[-1])
        if green:
            m = [x for x in m if "All tests passed" in x]
        line = m[-1] if m else ("00:00 +1: All tests passed!" if green else "00:00 +0 -1: Some tests failed.")
        raw = line + "\n"
        if not green:
            names = [s for s in LB.signature_set(sig or "") if not CASE_RE.fullmatch(s)] if sig else []
            raw = "".join("00:00 +0 -1: %s [E]\n" % x for x in names) + (line if "failed" in line else
                                                                          "00:00 +0 -1: Some tests failed.") + "\n"
        suites.append(CheckResult(green, 0 if green else 1, False, raw, [{"cmd": "replay", "rc": 0 if green else 1,
                                                                           "timed_out": False}], 3600))
        st, ln = leg.roles.get("tester", ("DONE", ""))
        covers = [{"test": "test/replay_test.dart::t", "ac": a, "kind": "guard"} for a in acs]
        roles.append(RoleResult(st, ln, {"covers": covers, "e2e": e2e_of(tout)}))
        if green:
            gap = [a for a in LB.signature_set(sig or "") if CASE_RE.fullmatch(a)] if (out == "LOOPBACK" and sig) else []
            if out == "LOOPBACK" and not gap:
                gap = [acs[0]]
            f = {"ac": [{"id": a, "covered_by": ["test/replay_test.dart::t"],
                         "verdict": "not_covering" if a in gap else "effective", "why": "replay"} for a in acs],
                 "visual_rows": [], "overall": "gap" if gap else "all_effective"}
            judges["TEST"] = [_dec(f["overall"], f), _dec(f["overall"], json.loads(json.dumps(f)))]
            if gap:
                roles.append(RoleResult("DONE", "", {"covers": covers}))
        dwc = "partial_read" if leg.spawns.get("tester", 0) >= 2 else "other"
        judges["DWC"] = [_dec(dwc, {"verdict": dwc})]
        judges["VIS-ENV"] = [_dec("regression", {"verdict": "regression"})]
        judges["RUNNER"] = [_dec("green" if green else "red", {"verdict": "green" if green else "red"})]
    else:
        qst, qln = leg.roles.get("qa", ("DONE", ""))
        items = _items(MQ.from_pr_body(leg.pr_body).render() if leg.pr_body and MQ.from_pr_body(leg.pr_body) else "")
        if not items:
            qo = leg.writes.get("qa:output") or ""
            items = _items(qo)
        fu = FU.FollowupsRecord(leg.writes.get("followups") or "")
        prev = FU.FollowupsRecord(ep.state["issue"].get("followups") or "")
        prev_titles = set(i.title for i in prev.items if i.status in ("declined", "filed"))
        fitems = [{"title": i.title, "rationale": i.rationale, "keywords": i.title}
                  for i in fu.items if i.status == "unfiled" and i.title not in prev_titles]
        roles.append(RoleResult(qst, qln, {"plan": None, "human_items": items, "followups": fitems}))
        dst, dln = leg.roles.get("designer", ("DONE", "replay: designer not convened by legacy"))
        roles.append(RoleResult(dst, dln, {}))
        defects = []
        if out == "LOOPBACK":
            defects = [{"id": x, "blocking": True, "fixable_in_code": "yes", "line": reason or x}
                       for x in sorted(LB.signature_set(sig or "QA-1"))]
        elif out == "PAUSE":
            cause = (NH.Pause(leg.pauses[-1]).cause_line if leg.pauses else "") or ""
            defects = [{"id": "QA-1", "blocking": True, "fixable_in_code": "no",
                        "line": re.sub(r"^defect: (QA defect: )?", "", cause)}]
        verdict = "block" if defects else "pass"
        judges["QA"] = [_dec(verdict, {"defects": defects, "checklist": items, "quality_bar_met": "yes" if not defects else "no",
                                       "verdict": verdict})]
        judges["PRMATCH"] = [_dec("match" if pr_n else "none", {"verdict": "match" if pr_n else "none", "pr": pr_n})]
        judges["FOLLOWUP"] = lambda: _dec("needs_filing", {"verdict": "needs_filing"})
        inj["diff"] = ["lib/widgets/replay.dart"] if leg.designer else []
    calls = {"roles": [], "judges": [], "captures": []}

    def run_role(call):
        calls["roles"].append("%s-%s" % (call.role, call.task))
        return roles.pop(0) if roles else RoleResult("DONE", "replay: extra role call", {})

    def judge(spec):
        calls["judges"].append(spec.group)
        q = judges.get(spec.group)
        if callable(q):
            return q()
        if q:
            return q.pop(0) if len(q) > 1 else q[0]
        return _dec("unsure", {"verdict": "unsure"})

    def suite(cmds, owner, t):
        return suites.pop(0) if suites else CheckResult(True, 0, False, "00:00 +1: All tests passed!\n", [], t)

    def check(cmd, cwd, owner, t, wd):
        return CheckResult(False, 1, False, "00:00 +0 -1: t [E]\n  Expected: 1\n  Actual: 0\n00:00 +0 -1: Some tests failed.\n", [], t)

    p = B.Ports(n, gh, writer, decisions, clock, cfg, root, unattended=True, run_role=run_role, judge=judge,
                suite=suite, check=check, capture=lambda *a: calls["captures"].append(a[0]), host=HOST,
                branch=(lb_blk.get("branch") if lb_blk else "feature/#%d" % n), base=None)
    p.inject = inj
    return p, gh, w, calls, inj


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def real_test_cases(repo, n):
    """`docs/specs/<n>/test-cases.md` as the repository has it — the Issue's squash commit when
    one says `(#n)`, else the default branch tip (read-only `git show`)."""
    if not repo:
        return None
    import subprocess
    sha = subprocess.run(["git", "-C", repo, "log", "--format=%H", "-1", "--grep", "(#%d)" % n, "HEAD"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode().strip()
    r = subprocess.run(["git", "-C", repo, "show", "%s:docs/specs/%d/test-cases.md" % (sha or "HEAD", n)],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def run_engine(ep, leg, cfg, work, repo=None):
    from workflows.dev.stages import qa as Q
    from workflows.dev.stages import test as T
    p, gh, w, calls, inj = build(ep, leg, cfg, work, real_test_cases(repo, ep.issue) if ep.stage == "test" else None)
    try:
        if ep.stage == "test":
            r = T.run(p)
        else:
            r = Q.run(p, diff_paths=inj.get("diff"))
        err = None
    except Exception as e:                                     # an engine crash IS a defect finding
        r, err = None, "%s: %s" % (type(e).__name__, e)
    eng = {"labels": [(list(c[2]), list(c[3])) for c in w.calls if c[0] == "edit_labels"],
           "token": r.token() if r else "CRASH",
           "comments": {}, "pauses": [], "pr_body": None, "pr_comment": {}, "error": err, "calls": calls,
           "derived": inj.get("derived", False), "kind": r.kind if r else None, "verdicts": inj.get("verdicts")}
    touched = set(c[1] for c in w.calls if c[0] == "patch_comment")
    for c in gh.fx["issues"][str(ep.issue)].get("comments", []):
        m = MARK_RE.match(c.get("body") or "")
        if not m or (c["id"] < 9000 and c["id"] not in touched):
            continue
        if m.group(1) == "needs-human":
            eng["pauses"].append(c["body"])
        else:
            eng["comments"][m.group(1)] = c["body"]
    if inj.get("pr"):
        eng["pr_body"] = gh.fx["prs"][0]["body"]
        for c in gh.fx["issues"][str(inj["pr"])].get("comments", []):
            m = MARK_RE.match(c.get("body") or "")
            if m and (c["id"] >= 9000 or c["id"] in touched):
                eng["pr_comment"][m.group(1)] = c["body"]
    return eng


# ---- projections ----------------------------------------------------------------------------------

def _norm(s):
    return " ".join(markers.unescape(s or "").split())


def skeleton(stage, labels, comments, pauses, pr_body, pr_comment, token, prose_has):
    """[(element, text)] — the structural layer of one side."""
    out = []
    for adds, rems in labels:
        out.append(("labels", "labels +%s -%s" % (",".join(sorted(adds)), ",".join(sorted(rems)))))
    out.append(("token", "token %s" % re.sub(r"(OK PAUSE: needs-human) — .*", r"\1", token or "")))
    t = comments.get("test:output")
    if t is not None:
        lines = [markers.clean(x) for x in t.rstrip("\n").split("\n")]
        out.append(("test:output", "test:output %s|%s" % (lines[0], lines[-1])))
        out.append(("test:output/검증범위", "검증 범위 %s" % ("### 검증 범위" in lines or any("검증 범위" in l for l in lines))))
        d = e2e_of(t)
        out.append(("test:output/e2e", "e2e %s" % ("skip" if d.startswith("E2E 불요") else ("run" if d else "none"))))
        if prose_has("visual-baselines"):
            from guildcore.checks import visual as V
            out.append(("test:output/ledger", "ledger %s" % (V.block_text(t) or "none")))
        if prose_has("safety-net-evidence"):
            from guildcore.checks import visual as V
            out.append(("test:output/safety", "safety %s" % (V.block_text(t, V.SAFETY_NET) or "none")))
        out.append(("test:output/loopback-lines", "lb-lines %s" % any(l.startswith("loopback-signature:") for l in lines)))
    q = comments.get("qa:output")
    if q is not None:
        lines = [markers.clean(x) for x in q.rstrip("\n").split("\n")]
        out.append(("qa:output", "qa:output %s|%s" % (lines[0], lines[-1])))
        if prose_has("PR CI"):
            out.append(("qa:output/pr-ci", "### PR CI %s" % ("### PR CI" in lines)))
            ci = CI_LINE_RE.search(q)
            cls = "absent"
            if ci:
                v = ci.group(1)
                cls = next((k for k in ("없음(check-run", "없음", "green", "진행 중", "시작되지 않음", "red") if v.startswith(k)), "other")
            out.append(("qa:output/pr-ci-class", "PR CI class %s" % cls))
        out.append(("qa:output/ran-at", "ran-at %s" % any(l.startswith("ran-at: ") for l in lines)))
        out.append(("qa:output/loopback-lines", "lb-lines %s" % any(l.startswith("loopback-signature:") for l in lines)))
    lb = comments.get("loopback")
    if lb is not None:
        rec = LB.LoopbackRecord.parse(lb)
        for b in rec.blocks:
            keys = [markers.clean(x).split(":", 1)[0] for x in b.lines if re.match(r"^[a-z]+:", markers.clean(x))]
            out.append(("loopback", "%s %s from=%s" % (markers.clean(b.heading), ",".join(keys), b.get("from"))))
    for pz in pauses:
        p = NH.Pause(pz)
        out.append(("needs-human", "needs-human ok=%s cause=%s" % (p.cause_check_ok(), (p.cause_kind or "") + ":" + (p.env_key or ""))))
    if prose_has("guild:followups"):
        f = comments.get("followups")
        if f is not None:
            rec = FU.FollowupsRecord(f)
            out.append(("followups", "followups %s" % ",".join(sorted(i.status for i in rec.items))))
        for name, body in sorted(pr_comment.items()):
            pn = FU.PrNotice(body)
            out.append(("followups:pr", "%s settled=%s n=%d" % (name.split(":")[0] + ":pr", pn.settled, len(pn.titles))))
    if pr_body is not None:
        sp = markers.marker_span(pr_body, MQ.NAME)
        if sp:
            blk = pr_body[sp[0]:sp[1]]
            ls = [markers.clean(x) for x in blk.split("\n")]
            out.append(("manual-qa", "manual-qa %s|%s|%s n=%d" % (ls[0], ls[1] if len(ls) > 1 else "", ls[-1], len(_items(blk)))))
    return out


def prose_fields(stage, labels, comments, pauses, pr_body, pr_comment):
    f = {}
    lb = comments.get("loopback")
    if lb is not None:
        b = LB.LoopbackRecord.parse(lb).latest_active()
        if b is not None:
            for k in ("from", "branch", "reason", "signature"):
                f["loopback." + k] = _norm(b.get(k))
    for i, pz in enumerate(pauses[-1:]):
        f["needs-human.cause"] = _norm(NH.Pause(pz).cause_line or "")
    t = comments.get("test:output")
    if t is not None:
        f["test.e2e"] = _norm(e2e_of(t))
    q = comments.get("qa:output")
    if q is not None:
        m = CI_LINE_RE.search(q)
        if m:
            f["qa.pr_ci"] = _norm(m.group(0))
    fo = comments.get("followups")
    if fo is not None:
        f["followups.titles"] = "|".join(sorted(_norm(i.title) for i in FU.FollowupsRecord(fo).items))
    for name, body in pr_comment.items():
        f["pr_notice.titles"] = "|".join(sorted(_norm(x) for x in FU.PrNotice(body).titles))
    if pr_body is not None and MQ.from_pr_body(pr_body):
        f["manual_qa.items"] = "|".join(_norm(x) for x in _items(MQ.from_pr_body(pr_body).render()))
    return f


# ---- classification -------------------------------------------------------------------------------

def _ver(v):
    try:
        return tuple(int(x) for x in (v or "0").split("."))
    except ValueError:
        return (0,)


def classify(elem, leg_text, eng_text, ep):
    """(category, reason): category ∈ intentional:<id> | defect."""
    if elem == "labels" and leg_text.replace(",guild:needs-human", "").replace("-guild:needs-human,", "-") == eng_text \
            and "guild:needs-human" not in (getattr(ep, "prior_labels", None) or ["guild:needs-human"]):
        return "intentional:§7 B-F-18", "legacy removed guild:needs-human that the labels show absent (engine: set difference)"
    if elem == "loopback" and leg_text == "(absent)" and _ver(ep.version) < (0, 96, 0):
        return "drift", "the loop-back record exists since 0.96.0 (cf39b09); this log ran %s" % ep.version
    if elem == "loopback" and leg_text == "(absent)":
        return "intentional:§7 C-F-15", "legacy moved the label without writing the loop-back block (block always written)"
    if elem == "test:output/ledger":
        from guildcore.checks import visual as V
        ev = V.block_text(ep.state["issue"].get("test-evidence:step-1") or "")
        if ev is not None and ("ledger " + ev) == eng_text:
            return "intentional:§7 B-F-18", "engine copies the execute evidence ledger verbatim; legacy's copy differed"
        if ev is None and eng_text.endswith("none"):
            return "replay-gap", "the execute evidence is not in the logs (earlier session)"
    if elem == "qa:output/ran-at":
        return "intentional:C5", "qa:output `ran-at:` (C-F-17)"
    if elem == "test:output/e2e" and leg_text.endswith("none"):
        return "intentional:§7 C-F-14", "legacy output had no E2E literal; engine validates the string"
    if elem in ("qa:output/pr-ci", "qa:output/pr-ci-class") and "absent" in leg_text + " " + ("False" if "False" in leg_text else ""):
        return "intentional:§7 C-F-4", "PR CI record is mandatory and ordered after the lookup"
    if elem == "qa:output/pr-ci-class" and "other" in leg_text:
        return "intentional:§7 B-F-18", "legacy LLM wrote a PR CI value outside the closed table"
    if elem == "followups:pr" and leg_text != eng_text:
        return "intentional:§7 B-F-18", "PR notice rendered from the fixed template (legacy paraphrased)"
    if elem in ("test:output/safety", "test:output/ledger") and ep.state.get("evidence_untracked"):
        return "replay-gap", "the execute evidence was edited by a script the replay cannot follow"
    if elem in ("test:output/loopback-lines", "qa:output/loopback-lines") and "True" in leg_text:
        return "intentional:§7 B-F-18", "loopback-* lines only on the attended path (prose); legacy wrote them unattended"
    if elem == "manual-qa" and leg_text == "(absent)":
        return "replay-gap", "the legacy PR body write is not readable from the log"
    if elem == "manual-qa" and leg_text != eng_text:
        if "|<!-- /guild:manual-qa -->" not in leg_text or "사람 QA 체크리스트" not in leg_text:
            return "intentional:§7 B-F-18", "legacy block heading/intro drifted from the prose format"
    if elem == "needs-human" and "ok=False" in leg_text:
        return "intentional:§7 B-F-18", "legacy pause failed the cause-line check"
    return "defect", "unexplained"


def compare(ep, leg, eng):
    def has(word):
        return word in (ep.prose or "")
    L = skeleton(ep.stage, leg.labels, leg.writes, leg.pauses, leg.pr_body, leg.pr_comment,
                 _legacy_token(leg), has)
    E = skeleton(ep.stage, eng["labels"], eng["comments"], eng["pauses"], eng["pr_body"], eng["pr_comment"],
                 eng["token"], has)
    lt = "\n".join("%s\t%s" % x for x in L)
    et = "\n".join("%s\t%s" % x for x in E)
    sm = difflib.SequenceMatcher(None, lt, et, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    diffs = []
    le, ee = {}, {}
    for k, v in L:
        le.setdefault(k, []).append(v)
    for k, v in E:
        ee.setdefault(k, []).append(v)
    for k in sorted(set(le) | set(ee)):
        if le.get(k) != ee.get(k):
            cat, why = classify(k, " ".join(le.get(k, ["(absent)"])), " ".join(ee.get(k, ["(absent)"])), ep)
            diffs.append({"element": k, "legacy": le.get(k), "engine": ee.get(k), "class": cat, "why": why})
    lf = prose_fields(ep.stage, leg.labels, leg.writes, leg.pauses, leg.pr_body, leg.pr_comment)
    ef = prose_fields(ep.stage, eng["labels"], eng["comments"], eng["pauses"], eng["pr_body"], eng["pr_comment"])
    fields = {}
    for k in sorted(lf):
        ok = lf[k] == ef.get(k)
        fields[k] = (ok, lf[k], ef.get(k), None if ok else classify_field(k, lf[k], ef.get(k), leg))
    gated = [w for w in (("visual-baselines", "safety-net-evidence") if ep.stage == "test" else
                         ("PR CI", "guild:followups")) if not has(w)]
    return {"matched": matched, "total": max(len(lt), len(et)), "legacy_bytes": len(lt), "exact": lt == et,
            "gated": gated,
            "diffs": diffs, "fields": fields}


def classify_field(k, lv, ev, leg):
    from workflows.dev import judging as JG
    if k == "loopback.signature" and ev and LB.signature_set(lv) == LB.signature_set(ev):
        return "intentional:§7 B-F-18"          # same set; engine renders `a,b` (H§B), legacy `a, b`
    if k == "qa.pr_ci" and ev and lv.startswith(ev):
        return "intentional:§7 B-F-18"          # same class; legacy embellished the closed value
    if k == "qa.pr_ci" and not re.match(r"PR CI: (없음|green|진행 중|시작되지 않음|red)", lv):
        return "intentional:§7 B-F-18"          # legacy value outside the closed table
    if k == "qa.pr_ci" and leg.check_runs is None:
        return "replay-gap"                     # the log holds no check-run read to replay
    if k == "manual_qa.items" and ev == "|".join(_norm(JG.strip_hedges(x)) for x in lv.split("|")):
        return "intentional:§7 B-F-18"          # hedge words are banned inside entries (qa.md 2.5)
    if k == "pr_notice.titles":
        rec = FU.FollowupsRecord(leg.writes.get("followups") or "")
        if ev == "|".join(sorted(_norm(i.title) for i in rec.items if i.status == "unfiled")):
            return "intentional:§7 B-F-18"      # notice kept in step with the record (qa.md 2.6)
    if k == "test.e2e" and ev and lv and ev.split(":")[0] == lv.split(":")[0]:
        return "intentional:§7 C-F-14"
    return "defect"


def _legacy_token(leg):
    return {"ADVANCE": "OK ADVANCE: qa", "DONE": "OK DONE", "LOOPBACK": "OK LOOPBACK: execute",
            "PAUSE": "OK PAUSE: needs-human — x", "PAUSE:pending": "OK PAUSE: needs-human — pending regeneration"}.get(
        leg.outcome(), "none")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--repo", help="the logs' repository (read-only `git show` of real test-cases.md)")
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as fh:
        cfg = json.load(fh)
    os.makedirs(a.out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="replay-", dir=a.out)
    eps = episodes(glob.glob(a.logs))
    rows, skipped = [], {}
    for ep in eps:
        leg = Legacy(ep)
        if leg.outcome() is None:
            skipped["no legacy outcome (session cut mid-stage)"] = skipped.get("no legacy outcome (session cut mid-stage)", 0) + 1
            continue
        if a.limit and len(rows) >= a.limit:
            break
        eng = run_engine(ep, leg, cfg, work)                  # by construction: the render layer
        cmp_ = compare(ep, leg, eng)
        row = {"episode": ep.key, "stage": ep.stage, "version": ep.version, "legacy_outcome": leg.outcome(),
               "engine_token": eng["token"], "error": eng["error"], "engine_kind": eng["kind"], **cmp_}
        if a.repo and ep.stage == "test":                    # independently derived: the judgment path
            d2 = run_engine(ep, leg, cfg, work, a.repo)
            if d2["derived"]:
                row["derived_run"] = {"kind": d2["kind"], "token": d2["token"], "error": d2["error"],
                                      "verdicts": d2["verdicts"]}
        rows.append(row)
    shutil.rmtree(work, True)
    rep = report(rows, skipped)
    with open(os.path.join(a.out, "rows.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


def _agreement(rs):
    """Stage-outcome agreement (ADVANCE/DONE vs LOOPBACK/PAUSE) with the legacy session:
    `by_construction` — the judgments were inverted from the legacy outcome, so agreement is true
    by construction (it checks the render/transition layer only); `derived` — real test-cases.md
    (repository), the legacy LEADER's coverage sentences, the real runner summary line; the engine
    computes the outcome (K2-M7). Derived misses are split by cause: ids the prose never mentions
    (`unsure` → repair → uncovered — an extraction limit) vs ids the prose calls not covered."""
    out = {"by_construction": {"n": 0, "agree": 0}, "derived": {"n": 0, "agree": 0, "miss_extraction": 0,
                                                                  "miss_not_covering": 0, "miss_other": 0,
                                                                  "disagree": []}}
    for r in rs:
        b = out["by_construction"]
        b["n"] += 1
        b["agree"] += _kind_of(r["legacy_outcome"]) == (r.get("engine_kind") or "")
        d = r.get("derived_run")
        if not d:
            continue
        o = out["derived"]
        o["n"] += 1
        if _kind_of(r["legacy_outcome"]) == (d.get("kind") or ""):
            o["agree"] += 1
            continue
        v = d.get("verdicts") or {}
        cause = ("miss_extraction" if v.get("unsure") and not v.get("not_covering") else
                 "miss_not_covering" if v.get("not_covering") else "miss_other")
        o[cause] += 1
        if len(o["disagree"]) < 40:
            o["disagree"].append({"episode": r["episode"], "legacy": r["legacy_outcome"], "engine": d.get("token", "")[:60],
                                  "verdicts": v, "cause": cause})
    for k in out.values():
        k["pct"] = round(100.0 * k["agree"] / k["n"], 1) if k["n"] else None
    return out


def _kind_of(outcome):
    return {"ADVANCE": "ADVANCE", "DONE": "DONE", "LOOPBACK": "LOOPBACK", "PAUSE": "PAUSE",
            "PAUSE:pending": "PAUSE"}.get(outcome, outcome)


def report(rows, skipped):
    out = {"episodes": {}, "skipped": skipped}
    for stage in ("test", "qa"):
        rs = [r for r in rows if r["stage"] == stage]
        if not rs:
            continue
        lb = sum(r["legacy_bytes"] for r in rs)
        tot = sum(r["total"] for r in rs)
        m = sum(r["matched"] for r in rs)
        # after_intentional = 1 − defect bytes / (legacy bytes − bytes of intentional, replay-gap and
        # drift elements): those elements leave the numerator AND the denominator (§10.2-2 gates
        # on unexplained differences) — K2-M7 fixed the formula to match this comment
        f_all = [f for r in rs for f in r["fields"].values()]
        f_def = [f for f in f_all if not f[0] and f[3] == "defect"]
        f_gap = [f for f in f_all if not f[0] and f[3] == "replay-gap"]
        f_cls = {}
        for f in f_all:
            if not f[0]:
                f_cls[f[3]] = f_cls.get(f[3], 0) + 1
        bad = gap = 0
        cls = {}
        for r in rs:
            for d in r["diffs"]:
                cls[d["class"]] = cls.get(d["class"], 0) + 1
                size = len("\n".join(d["legacy"] or d["engine"] or []))
                if d["class"] == "defect":
                    bad += size
                else:
                    gap += size
        clean = sum(1 for r in rs if not any(d["class"] in ("defect", "replay-gap", "drift") for d in r["diffs"]))
        out["episodes"][stage] = {
            "n": len(rs), "exact_structural": sum(1 for r in rs if r["exact"]),
            "structural_byte_match_raw": round(100.0 * m / tot, 2) if tot else None,
            "structural_byte_match_after_intentional": round(100.0 * (1 - float(bad) / (lb - gap)), 2) if lb else None,
            "structural_excluded_bytes(intentional+replay-gap+drift)": gap, "structural_defect_bytes": bad,
            "episodes_without_unexplained_diff": clean,
            "prose_fields": len(f_all), "prose_field_match_raw": round(100.0 * sum(1 for f in f_all if f[0]) / len(f_all), 2) if f_all else None,
            "prose_field_match_after_intentional": round(100.0 * (len(f_all) - len(f_def) - len(f_gap)) / (len(f_all) - len(f_gap)), 2) if f_all else None,
            "prose_diff_classes": f_cls, "prose_replay_gaps": len(f_gap),
            "diff_classes": cls, "crashes": sum(1 for r in rs if r["error"]),
            "legacy_bytes": lb,
            "outcome_agreement": _agreement(rs),
            "prose_version_gated": {w: sum(1 for r in rs if w in r.get("gated", [])) for w in
                                    sorted(set(x for r in rs for x in r.get("gated", [])))}}
    return out


if __name__ == "__main__":
    sys.exit(main())
