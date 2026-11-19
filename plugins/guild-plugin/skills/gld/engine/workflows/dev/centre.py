"""workflows.dev.centre — the §9.4-6 / §10.4 tripwire centres, recomputed from replay output (K6 item 18).

Input: the decisions the §10.2-6 held-out replay recorded, `{issue: [decision block dicts]}` (the engine's own
output on held-out Issues — a paid run), and optionally the LEGACY rates of the same Issues.

* `normal` centre = `health.metrics` over the replay's decisions (the engine's own distribution, the designed shifts
  included); per §9.4-6 (R4J-M2), on a LENIENT metric (EX-ARB dismiss, KICKOFF clear, STAKES low) where the engine
  is more lenient than legacy, the centre is legacy's value;
* `first_sprint` centre (R4J-M4) = the SAME recorded decisions passed through the first-sprint forcing in code — no
  new call: an unattended EX-ARB BLOCKER/MAJOR dismiss → accept (`coerced_by: first-sprint`, excluded from the
  coercion rate); an analyze/design HANDOFF `ok_with_assumption` → an `ambiguity:` pause (the Issue counts as
  paused); every decision of an unverified group (`unverified.pending` at the replay's time) → the conservative
  question (a pause on an unattended Issue) — the "first-sprint path" G4 explains away, recorded separately as
  `explained_pause_issues`;
* written to `<engine>/health-center.json` as {"normal": …, "first_sprint": …, "source": …, "n": …}; `dev health`
  compares against `first_sprint` with `--first-sprint`, else `normal` (a flat legacy file = `normal`).
"""

import copy
import json
import os

LENIENT = ("exarb_dismiss", "kickoff_clear", "stakes_low")


def _set(b, **kv):
    out = dict(b)
    out.update(kv)
    return out


def first_sprint_view(blocks_by_issue, unattended=True, unverified=()):
    """(blocks_by_issue as first-sprint mode would have recorded them, {issue: True} explained by that path)."""
    uv = set(str(g).replace(":", "-") for g in unverified)
    out, explained = {}, {}
    for n, blocks in blocks_by_issue.items():
        nb = []
        for b in blocks:
            b = dict(b)
            pt = str(b.get("point") or "")
            ch = str(b.get("choice") or "")
            judged = str(b.get("by") or "").startswith(("judge:", "leader:"))
            if judged and unattended and pt.startswith("EX-ARB") and "dismiss" in ch and \
                    str(b.get("severity") or "BLOCKER/MAJOR").upper() not in ("MINOR", "NIT"):
                b = _set(b, raw_choice=ch.replace("dismiss", "would-dismiss"), choice=ch.replace("dismiss", "accept"),
                         coerced="true", coerced_by="first-sprint")
            if judged and pt == "HANDOFF" and ch == "ok_with_assumption" and \
                    str(b.get("stage") or "") in ("analyze", "design", "execute"):
                nb.append(b)
                nb.append({"point": "ask:ambiguity", "status": "pending-human", "by": "code",
                           "cause": "ambiguity: first-sprint HANDOFF assumption"})
                explained[n] = True
                continue
            g = pt.split(":")[0]
            if judged and unattended and (g in uv or g.replace(":", "-") in uv):
                nb.append(b)
                nb.append({"point": "conservative:%s" % g, "status": "pending-human", "by": "code"})
                explained[n] = True
                continue
            nb.append(b)
        out[n] = nb
    return out, explained


def compute(blocks_by_issue, legacy=None, unverified=(), source=""):
    from workflows.dev import health as HE
    normal = HE.metrics(blocks_by_issue)
    legacy = legacy or {}
    for k in LENIENT:
        if normal.get(k) is not None and legacy.get(k) is not None and normal[k] > legacy[k]:
            normal[k] = legacy[k]                        # R4J-M2: never centre a tripwire on a more lenient engine
            normal.setdefault("_legacy_centre", []).append(k)
    fs_blocks, explained = first_sprint_view(copy.deepcopy(blocks_by_issue), True, unverified)
    fs = HE.metrics(fs_blocks)
    for k in LENIENT:
        if fs.get(k) is not None and legacy.get(k) is not None and fs[k] > legacy[k]:
            fs[k] = legacy[k]
    fs["explained_pause_issues"] = (float(len(explained)) / len(blocks_by_issue)) if blocks_by_issue else None
    return {"normal": normal, "first_sprint": fs, "n": len(blocks_by_issue), "source": source,
            "legacy": legacy or None}


def write(common, centre):
    from guildcore import journal as J
    path = os.path.join(J.engine_dir(common), "health-center.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)  # fs-ok: the engine dir under <git-common-dir>/guild/engine
    J.atomic_write(path, json.dumps(centre, sort_keys=True, indent=1))
    return path


def pick(centre, first_sprint):
    """The centre `dev health` compares against: `first_sprint` / `normal`, or a flat (older) file as is."""
    if not isinstance(centre, dict):
        return None
    if "normal" in centre or "first_sprint" in centre:
        return centre.get("first_sprint" if first_sprint else "normal")
    return centre
