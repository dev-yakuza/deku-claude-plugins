"""Readiness R1: a reproduction test of a fixed engine defect declares it.

    @fixes_defect("E1", "escalate:env-problem @ done-gate")
    def test_…(self): …

tests/test_fixed_defects.py collects every declaration and fails when a declared (id, signature) is not in
engine/data/fixed-defects.json, or an entry of that list has no declaring test.
"""

ATTR = "__gx_fixes_defect__"


def fixes_defect(defect_id, signature):
    """Mark a test method as the reproduction test of fixed-defects entry `defect_id` with `signature`."""
    def mark(fn):
        setattr(fn, ATTR, tuple(getattr(fn, ATTR, ())) + ((defect_id, signature),))
        return fn
    return mark
