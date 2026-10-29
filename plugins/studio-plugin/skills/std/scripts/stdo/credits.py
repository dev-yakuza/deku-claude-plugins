"""CREDITS (m1-plan §9, D-M1-13): every picture a public video shows has an approved entry in
`<sr>/videos/<id>/CREDITS.yaml` — the JSON-compatible subset of YAML (a file that is not JSON is refused: block YAML
is never read). The agent writes only `CREDITS.draft.yaml`; `state.py credit` moves an entry from the draft into
CREDITS.yaml after the person approved it (`출처 <video> <h12>`).

An entry, normalized: the eight fields the question shows as `key=value` lines (values in canonical JSON scalar
notation, at most LINE_MAX characters a line) — path (the script_src) · license · credit_line · floor (the image's
deterministic floor from assets.json, `<level>/<reason>`) · license_checked · public_ok · redistribute · commercial —
plus `sha256` of the file. Its hash (h12 = the first 12 hex) covers all of them, so changing any field, or the file,
needs the person again. `consent`, `originality_checked` and `ai_generated: true` are not supported in M1."""

import json
import os

from .state.hashes import canonical, file_sha, hash_of

FIELDS = ("path", "license", "credit_line", "floor", "license_checked", "public_ok", "redistribute", "commercial")
BOOLS = ("license_checked", "public_ok", "redistribute", "commercial")
UNSUPPORTED = ("consent", "originality_checked")
LICENSE_UNCHECKED = ("TODO", "see README")
LINE_MAX = 200
FILE, DRAFT = "CREDITS.yaml", "CREDITS.draft.yaml"


class CreditError(Exception):
    pass


def read(path):
    """({path: entry}, why or None) of a CREDITS file ({} and None when it does not exist)."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}, None
    try:
        data = json.loads(text)
    except ValueError:
        return None, "%s is not the JSON form Studio reads (block YAML is not read): write it as JSON" % (
            os.path.basename(path))
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not all(isinstance(i, dict) and isinstance(i.get("path"), str) for i in items):
        return None, "%s needs {\"schema\": 1, \"items\": [{\"path\": …}, …]}" % os.path.basename(path)
    return {i["path"]: i for i in items}, None


def dumps(entries):
    return json.dumps({"schema": 1, "items": [entries[k] for k in sorted(entries)]}, ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"


def floor_of(asset):
    return "%s/%s" % (asset.get("floor") or "unknown", asset.get("floor_reason") or "-")


def normalize(item, file_path, asset):
    """The normalized entry (raises CreditError). `asset`: the assets.json image whose script_src is item.path."""
    if asset is None:
        raise CreditError("%s is not a usable image of work/assets.json (its script_src)" % item.get("path"))
    out = {}
    for k in ("path", "license", "credit_line", "floor"):
        v = item.get(k)
        if not isinstance(v, str) or not v.strip():
            raise CreditError("%s needs %s (text)" % (item.get("path"), k))
        out[k] = v
    for k in BOOLS:
        if not isinstance(item.get(k), bool):
            raise CreditError("%s needs %s (true or false)" % (item.get("path"), k))
        out[k] = item[k]
    want = floor_of(asset)
    if out["floor"] != want:
        raise CreditError("%s: floor must be the image's floor %s" % (item.get("path"), want))
    sha = file_sha(file_path)
    if sha is None:
        raise CreditError("%s: the file cannot be read" % item.get("path"))
    out["sha256"] = sha
    for k in UNSUPPORTED + ("ai_generated",):
        if k in item:
            out[k] = item[k]
    for l in lines(out):
        if len(l) > LINE_MAX:
            raise CreditError("a line is longer than %d characters — shorten the draft: %s…" % (LINE_MAX, l[:60]))
    return out


def lines(entry):
    """The `key=value` lines the question shows (canonical JSON scalars)."""
    return ["%s=%s" % (k, canonical(entry.get(k)).decode("utf-8")) for k in FIELDS]


def entry_hash(entry):
    return hash_of(entry)


def h12(entry):
    return entry_hash(entry)[:12]


def unsupported(entry):
    """Why an entry is not supported in M1, or None."""
    for k in UNSUPPORTED:
        if k in entry:
            return "%s is not supported in M1 (no consent or originality records yet)" % k
    if entry.get("ai_generated") is True:
        return "ai_generated images are not supported in M1"
    return None


def assets_by_src(assets_data):
    return {i.get("script_src"): i for i in (assets_data or {}).get("images") or []
            if isinstance(i, dict) and i.get("status") == "ok" and i.get("script_src")}
