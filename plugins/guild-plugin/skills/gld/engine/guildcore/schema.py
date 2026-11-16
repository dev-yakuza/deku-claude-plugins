"""guildcore.schema — the small closed-JSON-schema validator the engine re-checks every model output with.

The CLI's `--json-schema` constrains a judge's `structured_output`, but the engine never trusts
it (§3.1 "엔진이 스키마 재검증"); role `result.json` files (§5.2) have no CLI-side check at all.
Supported keywords — the subset the engine's own schemas use: `type` (object, array, string,
integer, number, boolean, null, or a list), `enum`, `const`, `required`, `properties`,
`additionalProperties` (bool), `items`, `minItems`, `maxItems`, `minLength`, `maxLength`,
`pattern`, `anyOf`, `oneOf`. Unknown keywords are an error in the SCHEMA (the engine's schemas
must stay inside this subset), never silently ignored.
"""

import re

KNOWN = {"type", "enum", "const", "required", "properties", "additionalProperties", "items",
         "minItems", "maxItems", "minLength", "maxLength", "pattern", "anyOf", "oneOf",
         "description", "title", "$schema", "default"}
_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class SchemaError(Exception):
    pass


def check_schema(schema, path="$"):
    if not isinstance(schema, dict):
        raise SchemaError("%s: schema must be an object" % path)
    bad = set(schema) - KNOWN
    if bad:
        raise SchemaError("%s: unsupported keywords %s" % (path, sorted(bad)))
    for k, sub in (schema.get("properties") or {}).items():
        check_schema(sub, "%s.%s" % (path, k))
    if isinstance(schema.get("items"), dict):
        check_schema(schema["items"], path + "[]")
    for k in ("anyOf", "oneOf"):
        for i, sub in enumerate(schema.get(k) or []):
            check_schema(sub, "%s.%s[%d]" % (path, k, i))


def errors(value, schema, path="$"):
    """[message] — empty when `value` satisfies `schema`."""
    out = []
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPES[x](value) for x in types):
            return ["%s: expected %s" % (path, "|".join(types))]
    if "const" in schema and value != schema["const"]:
        out.append("%s: must be %r" % (path, schema["const"]))
    if "enum" in schema and value not in schema["enum"]:
        out.append("%s: %r not in %s" % (path, value, schema["enum"]))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append("%s: shorter than %d" % (path, schema["minLength"]))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append("%s: longer than %d" % (path, schema["maxLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append("%s: does not match %s" % (path, schema["pattern"]))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append("%s: fewer than %d items" % (path, schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append("%s: more than %d items" % (path, schema["maxItems"]))
        if isinstance(schema.get("items"), dict):
            for i, v in enumerate(value):
                out += errors(v, schema["items"], "%s[%d]" % (path, i))
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for k in schema.get("required") or []:
            if k not in value:
                out.append("%s: missing %s" % (path, k))
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    out.append("%s: unexpected key %s" % (path, k))
        for k, sub in props.items():
            if k in value:
                out += errors(value[k], sub, "%s.%s" % (path, k))
    if "anyOf" in schema and not any(not errors(value, s, path) for s in schema["anyOf"]):
        out.append("%s: matches none of anyOf" % path)
    if "oneOf" in schema and sum(1 for s in schema["oneOf"] if not errors(value, s, path)) != 1:
        out.append("%s: must match exactly one of oneOf" % path)
    return out


def valid(value, schema):
    return not errors(value, schema)
