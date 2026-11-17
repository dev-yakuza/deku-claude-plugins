"""workflows.dev.variants — the three execute variants' SLOTS (spine S:14–26): DESIGN INPUT, BRANCH
prefix, DEVELOPER TASK, EVIDENCE RULE, CONFORMANCE, SIGNAL AREA, PR SUMMARY. The refactor Safety net
(which breaks the slot abstraction) lives in `refactor_net`.
"""

import re

VARIANTS = ("implement", "debug", "refactor")
PREFIX = {"implement": "feature/", "debug": "fix/", "refactor": "refactor/"}
NEEDS_CONTEXT = {"implement": "design/skeleton not found for #%d",
                 "debug": "analyze/design not found for #%d",
                 "refactor": "design/target-structure not found for #%d"}
SUMMARY_HEAD = {"implement": "## 무엇을 구현했나", "debug": "## 무엇을 고쳤나", "refactor": "## 무엇을 정리했나"}
CAPTURE_AREA = {"implement": "implement", "debug": "debug", "refactor": "refactor"}


def design_input(p, variant, comments):
    """P0.2: the design input exists → None, else the NEEDS_CONTEXT line."""
    from guildcore.records import outputs as OUT
    n = p.issue
    if variant == "implement":
        ok = OUT.find(comments, "design:output") is not None and p.exists("docs/specs/%d/skeleton.md" % n)
    elif variant == "debug":
        ok = OUT.find(comments, "design:output") is not None or OUT.find(comments, "analyze:output") is not None
    else:
        ok = p.exists("docs/specs/%d/skeleton.md" % n)
    return None if ok else NEEDS_CONTEXT[variant] % n


SLUG_RE = re.compile(r"[^a-z0-9]+")


def branch_name(variant, issue, title, template=None):
    """J-B4 as code (`config.engine.branch_template`, default `<prefix>#<N>-<slug>`): the name always
    carries <N> as a whole token so J-B1 finds it again."""
    slug = SLUG_RE.sub("-", (title or "").lower()).strip("-")[:40].strip("-") or "work"
    tpl = template or "{prefix}#{n}-{slug}"
    name = tpl.format(prefix=PREFIX[variant], n=int(issue), slug=slug)
    if not re.search(r"(?<![0-9.])%d(?![0-9])" % int(issue), name):
        name = "%s#%d-%s" % (PREFIX[variant], int(issue), slug)
    return name


def evidence_rule(variant, green, extras, ledger_rows, red_runs=None):
    """The variant's extra condition on raw evidence (Step 2.7). Returns (met, reason, concern):
    implement — raw green; debug — a red run before the fix and the green run now naming the same
    test, or the visual-only carve-out (DWC); refactor — raw green and a ledger without
    C/M/D/P/replacing-A and without an A lacking a case."""
    if not green:
        return False, None, None
    if variant == "debug":
        dwc = (extras or {}).get("dwc") or ""
        if "visual-only bug, unprovable here" in dwc:
            return True, None, dwc
        red = (extras or {}).get("red") or []
        if not red:
            return False, "debug: no red run before the fix (regression test not shown failing)", None
        return True, None, None
    if variant == "refactor":
        for r in ledger_rows or []:
            code, rest = r[0], r[1:]
            if code in ("C", "M", "D", "P") or (code == "A" and "replaces" in rest) or \
                    (code == "A" and "case:" not in rest):
                return False, "refactor changed a visual baseline: %s" % r, None
    return True, None, None
