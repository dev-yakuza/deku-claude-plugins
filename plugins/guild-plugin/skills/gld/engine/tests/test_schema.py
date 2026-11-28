"""The small JSON Schema validator (gxengine/schema.py): every supported keyword, and refusal of the rest."""

import unittest

from gxengine import schema as S


def ok(inst, sch):
    return not S.errors(inst, sch)


class TypeTests(unittest.TestCase):
    def test_types(self):
        self.assertTrue(ok({}, {"type": "object"}))
        self.assertTrue(ok([], {"type": "array"}))
        self.assertTrue(ok("x", {"type": "string"}))
        self.assertTrue(ok(None, {"type": "null"}))
        self.assertTrue(ok(True, {"type": "boolean"}))
        self.assertTrue(ok(3, {"type": "integer"}))
        self.assertTrue(ok(3.0, {"type": "integer"}), "1.0-style floats are integers in JSON Schema")
        self.assertFalse(ok(3.5, {"type": "integer"}))
        self.assertTrue(ok(3.5, {"type": "number"}))

    def test_booleans_are_not_numbers(self):
        self.assertFalse(ok(True, {"type": "integer"}))
        self.assertFalse(ok(False, {"type": "number"}))
        self.assertFalse(ok(1, {"type": "boolean"}))

    def test_type_list(self):
        sch = {"type": ["string", "null"]}
        self.assertTrue(ok(None, sch))
        self.assertTrue(ok("a", sch))
        self.assertFalse(ok(1, sch))


class ValueTests(unittest.TestCase):
    def test_enum_const_json_equality(self):
        self.assertTrue(ok("a", {"enum": ["a", "b"]}))
        self.assertFalse(ok("c", {"enum": ["a", "b"]}))
        self.assertFalse(ok(True, {"enum": [1]}), "True != 1 in JSON")
        self.assertFalse(ok(1, {"const": True}))
        self.assertTrue(ok(1.0, {"const": 1}))
        self.assertTrue(ok(None, {"enum": ["work", None]}))
        self.assertTrue(ok({"a": [1, 2]}, {"const": {"a": [1, 2]}}))

    def test_string_keywords(self):
        self.assertFalse(ok("", {"minLength": 1}))
        self.assertFalse(ok("abc", {"maxLength": 2}))
        self.assertTrue(ok("design", {"pattern": "^[a-z]+$"}))
        self.assertFalse(ok("pnpm test", {"pattern": "^[a-z]+$"}))
        self.assertTrue(ok(5, {"pattern": "^x$"}), "string keywords ignore non-strings")

    def test_number_keywords(self):
        self.assertFalse(ok(0, {"minimum": 1}))
        self.assertFalse(ok(11, {"maximum": 10}))
        self.assertTrue(ok(10, {"minimum": 1, "maximum": 10}))


class ContainerTests(unittest.TestCase):
    def test_object_keywords(self):
        sch = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}},
               "additionalProperties": False}
        self.assertTrue(ok({"a": 1}, sch))
        self.assertFalse(ok({}, sch))
        self.assertFalse(ok({"a": 1, "when": "x"}, sch))
        self.assertFalse(ok({"a": "1"}, sch))

    def test_additional_properties_schema_and_property_names(self):
        sch = {"type": "object", "propertyNames": {"pattern": "^[a-z]+$"},
               "additionalProperties": {"type": "string"}, "minProperties": 1}
        self.assertTrue(ok({"test": "x"}, sch))
        self.assertFalse(ok({"Test": "x"}, sch))
        self.assertFalse(ok({"test": 1}, sch))
        self.assertFalse(ok({}, sch))

    def test_array_keywords(self):
        sch = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2, "uniqueItems": True}
        self.assertTrue(ok(["a"], sch))
        self.assertFalse(ok([], sch))
        self.assertFalse(ok(["a", "b", "c"], sch))
        self.assertFalse(ok(["a", "a"], sch))
        self.assertFalse(ok([1], sch))
        self.assertTrue(ok([1, True], {"uniqueItems": True}), "1 and True are different JSON values")


class CombinatorTests(unittest.TestCase):
    def test_one_any_all_not(self):
        one = {"oneOf": [{"type": "string"}, {"pattern": "^a"}]}
        self.assertTrue(ok("b", one))
        self.assertFalse(ok("abc", one), "matches both branches")
        self.assertFalse(ok(1, {"oneOf": [{"type": "string"}, {"type": "null"}]}))
        self.assertTrue(ok("abc", {"anyOf": [{"type": "string"}, {"pattern": "^a"}]}))
        self.assertFalse(ok(1, {"anyOf": [{"type": "string"}, {"type": "null"}]}))
        self.assertFalse(ok("ab", {"allOf": [{"minLength": 1}, {"maxLength": 1}]}))
        self.assertFalse(ok("x", {"not": {"type": "string"}}))
        self.assertTrue(ok(1, {"not": {"type": "string"}}))

    def test_local_ref(self):
        sch = {"$defs": {"name": {"type": "string", "pattern": "^[a-z]+$"}},
               "type": "array", "items": {"$ref": "#/$defs/name"}}
        self.assertTrue(ok(["ab"], sch))
        self.assertFalse(ok(["AB"], sch))

    def test_bool_schemas(self):
        self.assertTrue(ok({"x": 1}, {"properties": {"x": True}}))
        self.assertFalse(ok({"x": 1}, {"properties": {"x": False}}))


class RefusalTests(unittest.TestCase):
    def test_unsupported_keyword_refused(self):
        for kw in ("if", "then", "patternProperties", "format", "prefixItems", "unevaluatedProperties", "dependentRequired"):
            with self.subTest(kw=kw), self.assertRaises(S.SchemaError):
                S.errors({}, {kw: {}})

    def test_nested_unsupported_keyword_refused(self):
        with self.assertRaises(S.SchemaError):
            S.check_schema({"properties": {"a": {"format": "date-time"}}})
        with self.assertRaises(S.SchemaError):
            S.check_schema({"oneOf": [{"type": "string"}, {"if": {}}]})

    def test_malformed_values_refused(self):
        for bad in ({"type": "text"}, {"required": "a"}, {"enum": []}, {"pattern": "("},
                    {"$ref": "other.json#/x"}, {"minItems": -1}, {"oneOf": []}):
            with self.subTest(bad=bad), self.assertRaises(S.SchemaError):
                S.check_schema(bad)

    def test_unresolvable_ref(self):
        with self.assertRaises(S.SchemaError):
            S.errors(1, {"$ref": "#/$defs/missing"})


class ApiTests(unittest.TestCase):
    def test_validate_raises_with_paths(self):
        sch = {"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "string"}}}}
        with self.assertRaises(S.ValidationError) as cm:
            S.validate({"steps": ["a", 2]}, sch)
        self.assertTrue(any(e.startswith("$/steps/1") for e in cm.exception.errors), cm.exception.errors)

    def test_named_schema(self):
        self.assertIn("state", S.schema_names())
        self.assertFalse(S.is_valid({}, "state"))


class FillEnumsTests(unittest.TestCase):
    """schema.fill_enums — the enum templates of the stage-2 leader answers (V1)."""

    T = {"type": "object", "additionalProperties": False, "required": ["a", "s", "ids"],
         "properties": {"a": {"enum": ["{answers}"]},
                        "s": {"type": ["string", "null"], "enum": ["{steps}", None]},
                        "ids": {"type": "array", "items": {"type": "object", "required": ["id"],
                                                           "properties": {"id": {"type": "integer", "enum": ["{ids}"]}}}}}}

    def test_fills_in_place_and_keeps_other_members(self):
        out = S.fill_enums(self.T, {"{answers}": ["plan", "escalate"], "{steps}": ["analyze"], "{ids}": [1, 2]})
        self.assertEqual(out["properties"]["a"]["enum"], ["plan", "escalate"])
        self.assertEqual(out["properties"]["s"]["enum"], ["analyze", None])
        self.assertEqual(out["properties"]["ids"]["items"]["properties"]["id"]["enum"], [1, 2])
        self.assertTrue(S.is_valid({"a": "plan", "s": None, "ids": [{"id": 2}]}, out))
        self.assertFalse(S.is_valid({"a": "rerun", "s": None, "ids": []}, out))
        self.assertFalse(S.is_valid({"a": "plan", "s": "x", "ids": []}, out))
        self.assertEqual(self.T["properties"]["a"]["enum"], ["{answers}"], "the template is not changed")

    def test_empty_list_drops_its_property_and_null_survives(self):
        out = S.fill_enums(self.T, {"{answers}": ["escalate"], "{steps}": [], "{ids}": []})
        self.assertNotIn("ids", out["properties"])
        self.assertEqual(out["required"], ["a", "s"])
        self.assertEqual(out["properties"]["s"]["enum"], [None])
        with self.assertRaises(S.SchemaError):
            S.fill_enums({"enum": ["{answers}"]}, {"{answers}": []})
        with self.assertRaises(S.SchemaError):     # a scalar property cannot be dropped: impossible answer
            S.fill_enums(self.T, {"{answers}": [], "{steps}": [], "{ids}": [1]})

    def test_fail_closed(self):
        ok = {"{answers}": ["plan"], "{steps}": [], "{ids}": [1]}
        for bad in ({"{answers}": ["plan"], "{steps}": []},                    # missing token
                    dict(ok, **{"{extra}": ["x"]}),                            # unknown token
                    dict(ok, **{"{ids}": [{"x": 1}]}),                         # non-scalar
                    dict(ok, **{"{ids}": [1.5]}),                              # float
                    dict(ok, **{"{answers}": "plan"})):                        # not a list
            with self.subTest(bad=bad), self.assertRaises(S.SchemaError):
                S.fill_enums(self.T, bad)

    def test_duplicates_removed_and_tokens_listed(self):
        out = S.fill_enums(self.T, {"{answers}": ["plan", "plan"], "{steps}": [None], "{ids}": [1, 1]})
        self.assertEqual(out["properties"]["a"]["enum"], ["plan"])
        self.assertEqual(out["properties"]["s"]["enum"], [None])
        self.assertEqual(S.schema_tokens(self.T), {"{answers}", "{steps}", "{ids}"})
        self.assertTrue(S.is_token("{answers}"))
        self.assertFalse(S.is_token("answers"))

    def test_empty_list_drops_a_nullable_property(self):
        """Stage 3: an object-or-null / array-or-null property goes when an enum inside comes out empty."""
        t = {"type": "object", "additionalProperties": False, "required": ["a", "plan", "defer"],
             "properties": {"a": {"enum": ["{answers}"]},
                            "plan": {"type": ["object", "null"], "required": ["t", "adj"],
                                     "properties": {"t": {"enum": ["{templates}"]},
                                                    "adj": {"type": "array", "items": {"enum": ["{steps}"]}}}},
                            "defer": {"type": ["array", "null"], "items": {"enum": ["{rows}"]}}}}
        out = S.fill_enums(t, {"{answers}": ["x"], "{templates}": [], "{steps}": ["s"], "{rows}": ["R1"]})
        self.assertEqual((list(out["properties"]), out["required"]), (["a", "defer"], ["a", "defer"]))
        out = S.fill_enums(t, {"{answers}": ["x"], "{templates}": ["f"], "{steps}": [], "{rows}": []})
        self.assertEqual(out["required"], ["a", "plan"])
        self.assertEqual(out["properties"]["plan"]["required"], ["t"], "the nearest droppable property goes, not the outer one")
        with self.assertRaises(S.SchemaError):
            S.fill_enums(t, {"{answers}": [], "{templates}": ["f"], "{steps}": ["s"], "{rows}": []})


class SurrogateTests(unittest.TestCase):
    """schema.surrogate_errors (stage 3, review-q0 D9)."""

    def test_found_anywhere(self):
        self.assertEqual(S.surrogate_errors({"a": ["ok", {"b": "\ud800x"}]}), ["$/a/1/b: a lone surrogate (not valid Unicode text)"])
        self.assertEqual(len(S.surrogate_errors({"\udfff": "\udc00"})), 2)
        for bad in (S.surrogate_errors("\udabc"), S.surrogate_errors({"\ud800": 1})):
            for line in bad:
                line.encode("utf-8")       # the messages themselves can be written

    def test_fine(self):
        import json
        for ok in (None, 1, "한글 😀", {"a": [True, 1.5, "x"]}, json.loads('"\\ud83d\\ude00"')):
            self.assertEqual(S.surrogate_errors(ok), [])


if __name__ == "__main__":
    unittest.main()
