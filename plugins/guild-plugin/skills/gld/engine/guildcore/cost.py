"""guildcore.cost — the durable cost sink `<git-common-dir>/guild/engine/cost.jsonl` (§5.6, §9.6, FR-F10).

One row per engine-spawned session, from its `result` event: `total_cost_usd`, `modelUsage`,
`usage.cache_creation.ephemeral_{5m,1h}_input_tokens` (kept SEPARATE so the 5m TTL forcing can be
watched, §5.6), `num_turns`, `duration_ms` — plus the attribution fields of Q21/R6F-M1:
`{issue, stage, step, who (<role>-<task> | J:<group> | G:<group>), model, tier, local, attempt,
arm, experiment_id, kind (score|monitoring|validation), persona_chars, brief_chars, endpoint}`.
`summary(by=…)` is what `dev cost --by role|model|tier|local|arm|kind` prints; `budget_guard`
is the per-Issue cap of §4.2 (80% warn, 100% → ask/pause `budget`).
"""

import json
import os

from guildcore import journal as J

KINDS = ("score", "monitoring", "validation")
BY_KEYS = ("role", "who", "model", "tier", "local", "arm", "kind", "stage", "endpoint")
ATTRIBUTION = ("issue", "stage", "step", "who", "model", "tier", "local", "attempt", "arm",
               "experiment_id", "kind", "persona_chars", "brief_chars", "endpoint")


def path(common_dir):
    return os.path.join(J.engine_dir(common_dir), "cost.jsonl")


def from_result(result, **attrib):
    """A cost row from one session's `result` event + attribution."""
    result = result or {}
    usage = result.get("usage") or {}
    cc = usage.get("cache_creation") or {}
    row = {k: attrib.get(k) for k in ATTRIBUTION}
    if row["kind"] is None:
        row["kind"] = "score"
    if row["kind"] not in KINDS:
        raise ValueError("cost kind must be score|monitoring|validation")
    row["local"] = bool(row["local"])
    row.update({
        "total_cost_usd": float(result.get("total_cost_usd") or 0.0),
        "model_usage": result.get("modelUsage") or {},
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
        "cache_5m_tokens": cc.get("ephemeral_5m_input_tokens"),
        "cache_1h_tokens": cc.get("ephemeral_1h_input_tokens"),
        "num_turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
        "session_id": result.get("session_id"),
        "is_error": bool(result.get("is_error")),
    })
    for k in ("version", "t", "active_s"):
        if attrib.get(k) is not None:
            row[k] = attrib[k]
    return row


def local_row(active_s, **attrib):
    """A local developer job: $0 and its active seconds (§5.6)."""
    row = from_result({}, **dict(attrib, local=True))
    row["active_s"] = active_s
    return row


def record(common_dir, row):
    J.fsync_append(path(common_dir), json.dumps(row, ensure_ascii=False, sort_keys=True))
    return row


def rows(common_dir, issue=None):
    out = []
    try:
        with open(path(common_dir), encoding="utf-8") as fh:
            for ln in fh:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if issue is None or r.get("issue") == issue:
                    out.append(r)
    except IOError:
        pass
    return out


def _key(r, by):
    if by == "role":
        w = r.get("who") or "?"
        return w.split("-", 1)[0] if not w.startswith(("J:", "G:")) else w.split(":", 1)[0] + ":*"
    return r.get(by)


def summary(common_dir, by="who", issue=None):
    """[(key, n, usd)] sorted by $ desc."""
    if by not in BY_KEYS:
        raise ValueError("--by must be one of %s" % (BY_KEYS,))
    agg = {}
    for r in rows(common_dir, issue):
        k = _key(r, by)
        n, usd = agg.get(k, (0, 0.0))
        agg[k] = (n + 1, usd + float(r.get("total_cost_usd") or 0.0))
    return sorted(((k, n, round(u, 6)) for k, (n, u) in agg.items()), key=lambda x: -x[2])


def spent(common_dir, issue, kind="score"):
    """$ spent on one Issue (score rows by default — monitoring is booked apart, §1.3)."""
    return sum(float(r.get("total_cost_usd") or 0.0) for r in rows(common_dir, issue)
               if kind is None or r.get("kind") == kind)


def budget_guard(common_dir, issue, limit):
    """(state, spent): state ok | warn (≥80%) | over (≥100%) — §4.2 이슈 예산."""
    s = spent(common_dir, issue, kind=None)
    if limit and s >= limit:
        return "over", s
    if limit and s >= 0.8 * limit:
        return "warn", s
    return "ok", s
