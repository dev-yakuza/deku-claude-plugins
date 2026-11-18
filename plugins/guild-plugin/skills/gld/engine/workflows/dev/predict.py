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
  KICKOFF     its decision block carries `chosen_sha` instead of `chosen` (the chosen interpretation IS the readiness
              question's recommendation); analyze:output names it once the stage goes on

First-sprint "auto" ends only on a recorded go (§10.4, R4C-m9): a trusted `<!-- guild:note -->` comment
`first-sprint go/no-go` with `result: go` on a sprint tracker. Trackers are found by a REST list (`issue_rows`,
label `guild:sprint` — never the search API); a found go is cached locally (`first-sprint-go.json`, a cache only —
the source stays GitHub); a read that fails keeps the mode ON (the conservative side).
"""

import json
import os

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
                if b.startswith("<!-- guild:note -->") and "first-sprint go/no-go" in b and "result: go" in b:
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


def apply(p, q, stage=None):
    """Turn `q.predict_first` on when it is forced; records why on the question (`pf_why`). Returns q."""
    if not q.predict_first and q.recommended is not None:     # nothing to withhold → the answer is blind anyway
        why = forced(p, q, stage)
        if why:
            q.predict_first = True
            q.pf_why = why
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
