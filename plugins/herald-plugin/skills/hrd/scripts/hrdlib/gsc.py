"""Search Console connector (plan M5). Read-only; credentials stay in .claude/herald/secrets/.

Optional dependency: `google-auth` (pip install google-auth requests). Without it the
connector explains how to install it instead of failing obscurely.
"""

import datetime
import os
import urllib.parse

from .store import load_published, paths
from .util import HeraldError, now_iso, read_json, write_json

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
API = "https://searchconsole.googleapis.com/webmasters/v3/sites/%s/searchAnalytics/query"


def session(root):
    key = os.path.join(paths(root)["dir"], "secrets", "gsc.json")
    if not os.path.exists(key):
        raise HeraldError("no Search Console key at .claude/herald/secrets/gsc.json — run /hrd monitoring --connect-gsc")
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except ImportError:
        raise HeraldError("the Search Console connector needs `pip install google-auth requests`")
    creds = service_account.Credentials.from_service_account_file(key, scopes=[SCOPE])
    return AuthorizedSession(creds)


def query(sess, prop, start, end, page=None, dimensions=("page",), row_limit=1000):
    body = {"startDate": start, "endDate": end, "dimensions": list(dimensions), "rowLimit": row_limit}
    if page:
        body["dimensionFilterGroups"] = [{"filters": [{"dimension": "page", "operator": "equals", "expression": page}]}]
    r = sess.post(API % urllib.parse.quote(prop, safe=""), json=body, timeout=60)
    if r.status_code != 200:
        raise HeraldError("Search Console API %d: %s" % (r.status_code, r.text[:300]))
    return r.json().get("rows", [])


def collect(root, cfg, days=28):
    prop = cfg.get("site", "gsc_property")
    if not prop:
        raise HeraldError("config.site.gsc_property is not set")
    sess = session(root)
    end = datetime.date.today() - datetime.timedelta(days=3)  # GSC data lags
    cur_start = end - datetime.timedelta(days=days - 1)
    prev_end = cur_start - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=days - 1)
    pages = {}
    for label, s, e in (("current", cur_start, end), ("previous", prev_start, prev_end)):
        for row in query(sess, prop, s.isoformat(), e.isoformat()):
            pages.setdefault(row["keys"][0], {})[label] = {k: row.get(k) for k in ("clicks", "impressions", "ctr", "position")}
    out = {"at": now_iso(), "property": prop, "window_days": days, "articles": []}
    for a in load_published(root)["articles"]:
        url = a.get("url") or cfg.article_url(a["slug"])
        m = pages.get(url, {})
        cur, prev = m.get("current") or {}, m.get("previous") or {}
        queries = [r["keys"][0] for r in query(sess, prop, cur_start.isoformat(), end.isoformat(), page=url,
                                               dimensions=("query",), row_limit=10)] if cur else []
        drop = None
        if prev.get("clicks"):
            drop = round((cur.get("clicks", 0) - prev["clicks"]) / prev["clicks"], 3)
        out["articles"].append({"slug": a["slug"], "url": url, "origin": a.get("origin"), "current": cur,
                                "previous": prev, "click_change": drop, "top_queries": queries,
                                "refresh_candidate": drop is not None and drop <= -0.3})
    write_json(os.path.join(paths(root)["memory"], "metrics.json"), out)
    return out


def cached(root):
    return read_json(os.path.join(paths(root)["memory"], "metrics.json"))
