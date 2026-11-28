"""A small JSON Schema (draft 2020-12) validator — only the keywords our schemas use.

Standard library only. A schema that uses a keyword outside SUPPORTED is refused with
SchemaError (fail-closed): adding a keyword to a schema means adding it here, with a
test. The schema files live in `../schemas/<name>.schema.json`.

Supported:
  annotations (ignored): $schema $id $comment title description default examples
  structure: $defs, $ref (local "#" / "#/$defs/<name>" pointers only)
  any type:  type (string or list), enum, const, oneOf, anyOf, allOf, not
  object:    properties, required, additionalProperties (bool or schema), propertyNames,
             minProperties
  array:     items (single schema), minItems, maxItems, uniqueItems
  string:    minLength, maxLength, pattern (Python `re.search`)
  number:    minimum, maximum

JSON semantics: booleans are not integers or numbers; 1.0 counts as an integer;
`const`/`enum`/`uniqueItems` compare with JSON equality (True != 1).
"""

import json
import os
import re

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas")

ANNOTATIONS = frozenset({"$schema", "$id", "$comment", "title", "description", "default", "examples"})
SUPPORTED = ANNOTATIONS | frozenset({
    "$defs", "$ref", "type", "enum", "const", "oneOf", "anyOf", "allOf", "not",
    "properties", "required", "additionalProperties", "propertyNames", "minProperties",
    "items", "minItems", "maxItems", "uniqueItems",
    "minLength", "maxLength", "pattern", "minimum", "maximum",
})
TYPES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})


class SchemaError(Exception):
    """The schema itself is malformed or uses an unsupported keyword."""


class ValidationError(Exception):
    """An instance does not satisfy a schema. `.errors` is a list of "path: message"."""

    def __init__(self, errors, schema_name=None):
        self.errors = list(errors)
        self.schema_name = schema_name
        head = f"{schema_name}: " if schema_name else ""
        super().__init__(head + "; ".join(self.errors[:5]) + (" …" if len(self.errors) > 5 else ""))


# --- schema loading ------------------------------------------------------------------

_CACHE = {}


def schema_path(name):
    """Path of the schema file `<name>.schema.json`."""
    return os.path.join(SCHEMA_DIR, f"{name}.schema.json")


def load_schema(name):
    """Load, keyword-check and cache the named schema (e.g. "state", "result-review")."""
    if name not in _CACHE:
        with open(schema_path(name), encoding="utf-8") as f:
            schema = json.load(f)
        check_schema(schema)
        _CACHE[name] = schema
    return _CACHE[name]


def schema_names():
    """Names of every schema file shipped with the engine."""
    return sorted(f[: -len(".schema.json")] for f in os.listdir(SCHEMA_DIR) if f.endswith(".schema.json"))


def check_schema(schema, _path="#"):
    """Raise SchemaError if `schema` uses an unsupported keyword or a malformed value."""
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise SchemaError(f"{_path}: a schema must be an object or a boolean")
    for key, val in schema.items():
        if key not in SUPPORTED:
            raise SchemaError(f"{_path}: unsupported keyword {key!r}")
        sub = f"{_path}/{key}"
        if key in ("properties", "$defs"):
            if not isinstance(val, dict):
                raise SchemaError(f"{sub}: must be an object")
            for k, v in val.items():
                check_schema(v, f"{sub}/{k}")
        elif key in ("additionalProperties", "propertyNames", "items", "not"):
            check_schema(val, sub)
        elif key in ("oneOf", "anyOf", "allOf"):
            if not isinstance(val, list) or not val:
                raise SchemaError(f"{sub}: must be a non-empty array")
            for i, v in enumerate(val):
                check_schema(v, f"{sub}/{i}")
        elif key == "type":
            names = val if isinstance(val, list) else [val]
            if not names or any(n not in TYPES for n in names):
                raise SchemaError(f"{sub}: unknown type {val!r}")
        elif key == "required":
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                raise SchemaError(f"{sub}: must be an array of strings")
        elif key == "enum":
            if not isinstance(val, list) or not val:
                raise SchemaError(f"{sub}: must be a non-empty array")
        elif key == "pattern":
            try:
                re.compile(val)
            except (re.error, TypeError) as e:
                raise SchemaError(f"{sub}: bad pattern ({e})") from None
        elif key == "$ref":
            if not isinstance(val, str) or not (val == "#" or val.startswith("#/$defs/")):
                raise SchemaError(f"{sub}: only local '#/$defs/<name>' refs are supported")
        elif key in ("minItems", "maxItems", "minLength", "maxLength", "minProperties"):
            if not _is_int(val) or val < 0:
                raise SchemaError(f"{sub}: must be a non-negative integer")


# --- validation ------------------------------------------------------------------------

def _is_int(x):
    return (isinstance(x, int) and not isinstance(x, bool)) or (isinstance(x, float) and x.is_integer())


def _type_ok(inst, name):
    if name == "object":
        return isinstance(inst, dict)
    if name == "array":
        return isinstance(inst, list)
    if name == "string":
        return isinstance(inst, str)
    if name == "integer":
        return _is_int(inst)
    if name == "number":
        return isinstance(inst, (int, float)) and not isinstance(inst, bool)
    if name == "boolean":
        return isinstance(inst, bool)
    if name == "null":
        return inst is None
    return False


def _canon(x):
    """A hashable JSON-equality key (True and 1 stay different; 1 and 1.0 are equal)."""
    if isinstance(x, bool):
        return ("b", x)
    if isinstance(x, (int, float)):
        return ("n", float(x))
    if isinstance(x, str):
        return ("s", x)
    if x is None:
        return ("z",)
    if isinstance(x, list):
        return ("a", tuple(_canon(v) for v in x))
    if isinstance(x, dict):
        return ("o", tuple(sorted((k, _canon(v)) for k, v in x.items())))
    return ("?", repr(x))


def _resolve(root, ref):
    if ref == "#":
        return root
    name = ref[len("#/$defs/"):]
    try:
        return root["$defs"][name]
    except (KeyError, TypeError):
        raise SchemaError(f"unresolvable $ref {ref!r}") from None


def _validate(inst, schema, root, path, errs):
    if schema is True:
        return
    if schema is False:
        errs.append(f"{path}: not allowed")
        return
    if "$ref" in schema:
        _validate(inst, _resolve(root, schema["$ref"]), root, path, errs)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(inst, n) for n in names):
            errs.append(f"{path}: expected {'/'.join(names)}, got {type(inst).__name__}")
            return
    if "const" in schema and _canon(inst) != _canon(schema["const"]):
        errs.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and _canon(inst) not in {_canon(v) for v in schema["enum"]}:
        errs.append(f"{path}: {inst!r} is not one of {schema['enum']!r}")
    for key in ("allOf",):
        for sub in schema.get(key, ()):
            _validate(inst, sub, root, path, errs)
    if "anyOf" in schema:
        if not any(not _errors(inst, sub, root, path) for sub in schema["anyOf"]):
            errs.append(f"{path}: matches none of anyOf")
    if "oneOf" in schema:
        results = [_errors(inst, sub, root, path) for sub in schema["oneOf"]]
        n = sum(1 for r in results if not r)
        if n != 1:
            if n == 0:
                best = min(results, key=len)
                errs.append(f"{path}: matches none of oneOf (closest: {'; '.join(best[:3])})")
            else:
                errs.append(f"{path}: matches {n} branches of oneOf, expected exactly 1")
    if "not" in schema and not _errors(inst, schema["not"], root, path):
        errs.append(f"{path}: must not match the 'not' schema")

    if isinstance(inst, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", ()):
            if req not in inst:
                errs.append(f"{path}: missing required property {req!r}")
        if "minProperties" in schema and len(inst) < schema["minProperties"]:
            errs.append(f"{path}: needs at least {schema['minProperties']} properties")
        addl = schema.get("additionalProperties", True)
        for k, v in inst.items():
            sub = f"{path}/{k}"
            if "propertyNames" in schema:
                for e in _errors(k, schema["propertyNames"], root, f"{path}/<name {k!r}>"):
                    errs.append(e)
            if k in props:
                _validate(v, props[k], root, sub, errs)
            elif addl is False:
                errs.append(f"{path}: unexpected property {k!r}")
            elif isinstance(addl, dict):
                _validate(v, addl, root, sub, errs)
    elif isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            errs.append(f"{path}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(inst) > schema["maxItems"]:
            errs.append(f"{path}: at most {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = set()
            for i, v in enumerate(inst):
                c = _canon(v)
                if c in seen:
                    errs.append(f"{path}/{i}: duplicate item")
                seen.add(c)
        if "items" in schema:
            for i, v in enumerate(inst):
                _validate(v, schema["items"], root, f"{path}/{i}", errs)
    elif isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            errs.append(f"{path}: {inst!r} does not match {schema['pattern']!r}")
    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in schema and inst < schema["minimum"]:
            errs.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and inst > schema["maximum"]:
            errs.append(f"{path}: above maximum {schema['maximum']}")


def _errors(inst, schema, root, path):
    out = []
    _validate(inst, schema, root, path, out)
    return out


def errors(instance, schema):
    """Return the list of "path: message" errors of `instance` against `schema` (a dict)."""
    check_schema(schema)
    return _errors(instance, schema, schema, "$")


def validate(instance, schema_or_name):
    """Raise ValidationError unless `instance` satisfies the schema (a dict or a name)."""
    if isinstance(schema_or_name, str):
        schema, name = load_schema(schema_or_name), schema_or_name
    else:
        schema, name = schema_or_name, None
    errs = errors(instance, schema)
    if errs:
        raise ValidationError(errs, name)
    return instance


def is_valid(instance, schema_or_name):
    """True when `instance` satisfies the schema."""
    try:
        validate(instance, schema_or_name)
    except ValidationError:
        return False
    return True


# --- lone surrogates (stage 3, review-q0 D9) ---------------------------------------------------

def surrogate_errors(instance):
    """["path: message"] for every string (object keys included) holding a lone surrogate.

    Such a string cannot be written as UTF-8. The result / answer check refuses it by name —
    a role result is output-format / result-schema, a leader answer is answer-schema — and the
    raw object is recorded with ASCII escapes; nothing is replaced. [] when fine."""
    out = []

    def bad(s):
        return any("\ud800" <= c <= "\udfff" for c in s)

    def walk(x, path):
        if isinstance(x, str):
            if bad(x):
                out.append(f"{path}: a lone surrogate (not valid Unicode text)")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}/{i}")
        elif isinstance(x, dict):
            for k, v in x.items():
                key = k if isinstance(k, str) and not bad(k) else ascii(k)
                if isinstance(k, str) and bad(k):
                    out.append(f"{path}: a property name holds a lone surrogate ({key})")
                walk(v, f"{path}/{key}")
    walk(instance, "$")
    return out


# --- enum templates (stage 2 leader answers, scope §2.0) ---------------------------------

TOKEN_RE = re.compile(r"^\{[a-z][a-z0-9_]*\}$")


def is_token(value):
    """True for an enum placeholder string like "{answers}"."""
    return isinstance(value, str) and bool(TOKEN_RE.match(value))


def schema_tokens(schema):
    """The set of enum placeholder tokens used anywhere in `schema`."""
    out = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "enum" and isinstance(v, list):
                    out.update(x for x in v if is_token(x))
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(schema)
    return out


def fill_enums(template, values):
    """Return a copy of an enum TEMPLATE schema with every placeholder token replaced.

    `values` maps each token (e.g. "{answers}") to a list of JSON scalars. In an `enum`
    list, each token member is replaced by its values in place (other members such as
    `null` stay). Fail-closed:
      * a token used in the template but missing from `values`, or a key of `values` the
        template does not use → SchemaError;
      * a value that is not a JSON scalar (str / int / bool / null) → SchemaError;
      * an enum that comes out EMPTY makes its schema impossible; that propagates up through
        `items` and object properties to the nearest property that can go without a value — an
        ARRAY one (`type` is or has "array") or a NULLABLE one (`type` has "null", stage 3) —
        which is removed from `properties` and `required` of its object (the engine reads a
        dropped array as [] and a dropped nullable as null). Reaching the root → SchemaError.
    The result passes check_schema; duplicate values are removed (first kept).
    """
    used = schema_tokens(template)
    if set(values) != used:
        missing, extra = sorted(used - set(values)), sorted(set(values) - used)
        raise SchemaError(f"fill_enums: missing tokens {missing}, unknown tokens {extra}")
    for tok, vals in values.items():
        if not isinstance(vals, (list, tuple)):
            raise SchemaError(f"fill_enums: {tok} must map to a list")
        for v in vals:
            if not (v is None or isinstance(v, (str, bool, int)) and not isinstance(v, float)):
                raise SchemaError(f"fill_enums: {tok} has a non-scalar value {v!r}")

    class _Empty(Exception):
        pass

    def fill(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "enum" and isinstance(v, list):
                    new, seen = [], set()
                    for x in v:
                        for y in (values[x] if is_token(x) else [x]):
                            c = _canon(y)
                            if c not in seen:
                                seen.add(c)
                                new.append(y)
                    if not new:
                        raise _Empty()
                    out[k] = new
                elif k == "properties" and isinstance(v, dict):
                    props, dropped = {}, []
                    for pk, pv in v.items():
                        try:
                            props[pk] = fill(pv)
                        except _Empty:
                            types = pv.get("type") if isinstance(pv, dict) else None
                            types = types if isinstance(types, list) else [types]
                            if not {"array", "null"} & {x for x in types if isinstance(x, str)}:
                                raise
                            dropped.append(pk)
                    out[k] = props
                    if dropped:
                        out["_dropped"] = dropped
                else:
                    out[k] = fill(v)
            if "_dropped" in out:
                dropped = out.pop("_dropped")
                if "required" in out:
                    out["required"] = [r for r in out["required"] if r not in dropped]
            return out
        if isinstance(node, list):
            return [fill(v) for v in node]
        return node

    try:
        result = fill(template)
    except _Empty:
        raise SchemaError("fill_enums: an enum outside any property came out empty") from None
    check_schema(result)
    return result
