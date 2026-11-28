"""Sprint graph and table — pure functions (stage-4 scope §2.2–§2.4, VA1) — owner: branch A.

Nothing here reads GitHub, files or the clock; the supervisor (sprint.py) and the tracker
(sprinttracker.py) bring the facts.

0.98.7 parity: `order` and `plan_hash` give the same answer as `commands/atoms/sprint_dag.py --mode order`
/ `--mode hash` for the same input (TD2); `Depends on:` is never read — the member table is the only edge
source (§2.3).
"""

import hashlib
import re

from . import codes, defaults

TABLE_COLUMNS = ("#", "이슈", "base 의존", "원래 의존", "비고", "구분")
"""The member table `sprint plan` writes (sprint/plan.md Phase 6). A table from before the last column has the first five."""
ISSUE, DEP, KIND = TABLE_COLUMNS[1], TABLE_COLUMNS[2], TABLE_COLUMNS[5]
NO_DEP = ("—", "–", "-")
_ISSUE_CELL = re.compile(r"\A#([1-9][0-9]*)\Z")
_SEPARATOR = re.compile(r"\A:?-+:?\Z")
_HASH_VALUE = re.compile(r"\A[0-9a-f]+\Z")
_REASON_LINE = re.compile(r"\A[-*]?\s*상한 근거:\s*[\"'`]?([a-z-]+)[\"'`]?\s*\Z")
_WINDOW = re.compile(r"\A([01][0-9]|2[0-3]):[0-5][0-9]-([01][0-9]|2[0-3]):[0-5][0-9]\Z")


class SprintTableError(ValueError):
    """The tracker body's member table (or its plan block) is not what the engine reads → the sprint is
    refused before anything starts (§2.3, TD1, TD6)."""


class Member:
    """One row of the member table. issue (int), base_dep (int or None), kind (codes.MemberKind value, or
    None when the table has no kind column)."""

    __slots__ = ("issue", "base_dep", "kind")

    def __init__(self, issue, base_dep=None, kind=None):
        for n in (issue,) + ((base_dep,) if base_dep is not None else ()):
            if isinstance(n, bool) or not isinstance(n, int) or n < 1:
                raise SprintTableError(f"not an Issue number: {n!r}")
        if kind is not None and kind not in codes.MemberKind.values():
            raise SprintTableError(f"unknown member kind {kind!r}")
        self.issue, self.base_dep, self.kind = issue, base_dep, kind

    def __eq__(self, other):
        return isinstance(other, Member) and all(getattr(self, k) == getattr(other, k) for k in self.__slots__)

    __hash__ = None

    def __repr__(self):
        return f"Member({self.issue}, base_dep={self.base_dep}, kind={self.kind!r})"


class DepFacts:
    """The facts of one dependency D (sprinttracker.dep_facts). Unknown facts are never guessed: what could
    not be read is a raised error there (→ base-unresolved), never a default here.

    issue          D's number.
    issue_state    "OPEN" | "CLOSED".
    state_reason   "COMPLETED" | "NOT_PLANNED" | None (open, or GitHub gave none).
    prs            [{"number", "state": "OPEN" | "CLOSED" | "MERGED", "head_sha", "base"}] of head `gld/<D>` (the
                   one named by state.github.pr_number alone when that is set).
    local          None (no state.json on this machine), or {"finished": bool, "stopped": bool, "pr_number": int|None}.
    outcome        D's codes.MemberOutcome value in THIS supervisor run, or None (not looked at / not a member)."""

    FIELDS = ("issue", "issue_state", "state_reason", "prs", "local", "outcome")

    def __init__(self, **fields):
        if set(fields) != set(self.FIELDS):
            raise TypeError(f"DepFacts needs exactly {self.FIELDS}")
        for k, v in fields.items():
            setattr(self, k, v)


class DepVerdict:
    """member_state: base (codes.DepBase value), block (codes.MemberBlock value, only with BLOCKED), pr (the
    open PR dict to stack on, only with STACK)."""

    def __init__(self, base, block=None, pr=None):
        if base not in codes.DepBase.values():
            raise ValueError(f"bad base {base!r}")
        if (base == codes.DepBase.BLOCKED.value) != (block is not None):
            raise ValueError("a block goes with base blocked exactly")
        if block is not None and block not in codes.MemberBlock.values():
            raise ValueError(f"unknown block {block!r}")
        if (base == codes.DepBase.STACK.value) != (pr is not None):
            raise ValueError("a pull request goes with base stack exactly")
        self.base, self.block, self.pr = str(base), block, pr

    def __repr__(self):
        return f"DepVerdict({self.base!r}, block={self.block!r})"


class BaseChoice:
    """base_for: where the member starts. branch (PR base), stacked_on (D or None), draft (bool, U1)."""

    def __init__(self, branch, stacked_on=None, draft=False):
        self.branch, self.stacked_on, self.draft = branch, stacked_on, bool(draft)


# --- the plan block of the tracker body ----------------------------------------------------------------

def _block(body):
    """The text between the plan markers. Exactly one block — SprintTableError otherwise."""
    text = body if isinstance(body, str) else ""
    start, end = defaults.SPRINT_PLAN_MARKER, defaults.SPRINT_PLAN_MARKER_END
    if text.count(start) != 1 or text.count(end) != 1 or text.index(end) < text.index(start):
        raise SprintTableError(f"the tracker body needs exactly one {start} … {end} block")
    return text.split(start, 1)[1].split(end, 1)[0]


def _cells(line):
    """The cells of one table line (a backslash-escaped bar is text), or None when the line is no table line."""
    t = line.strip()
    if not t.startswith("|"):
        return None
    if len(t) < 2 or not t.endswith("|"):
        raise SprintTableError(f"not a closed table row: {t[:80]!r}")
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", t[1:-1])]


def parse_table(body):
    """[Member] of the plan block (defaults.SPRINT_PLAN_MARKER …) in table order. Reads the columns `이슈`,
    `base 의존` (`—` or one `#N`) and `구분` only; a table without `구분` gives kind None for every row. The block or
    a column missing / twice, another column order, two dependencies, an unknown kind, a duplicate member, a member
    on itself → SprintTableError. A dependency outside the table stays in base_dep (order drops it with a warning)."""
    lines = [_cells(x) for x in _block(body).split("\n")]
    heads = [i for i, c in enumerate(lines) if c is not None and (ISSUE in c or DEP in c)]
    if len(heads) != 1:
        raise SprintTableError(f"the plan block needs exactly one member table, found {len(heads)}")
    columns = tuple(lines[heads[0]])
    if columns not in (TABLE_COLUMNS, TABLE_COLUMNS[:-1]):
        raise SprintTableError(f"the member table's columns must be {' | '.join(TABLE_COLUMNS)} (the last one may be "
                               f"missing), got {' | '.join(columns)}")
    rest = lines[heads[0] + 1:]
    if not rest or rest[0] is None or len(rest[0]) != len(columns) or not all(_SEPARATOR.match(c) for c in rest[0]):
        raise SprintTableError("the member table has no separator row")
    rows = rest[1:]
    stop = next((i for i, r in enumerate(rows) if r is None), len(rows))
    if any(r is not None for r in rows[stop:]):
        raise SprintTableError("the member table is interrupted")
    out, seen = [], set()
    for row in rows[:stop]:
        m = _member(columns, row)
        if m.issue in seen:
            raise SprintTableError(f"duplicate member #{m.issue}")
        seen.add(m.issue)
        out.append(m)
    if not out:
        raise SprintTableError("the member table has no rows")
    return out


def _member(columns, row):
    if len(row) != len(columns):
        raise SprintTableError(f"a member row has {len(row)} cells, not {len(columns)}: {' | '.join(row)[:80]}")
    cell = dict(zip(columns, row))
    issue = _ISSUE_CELL.match(cell[ISSUE])
    if not issue:
        raise SprintTableError(f"not an Issue cell: {cell[ISSUE]!r}")
    n, dep = int(issue.group(1)), None
    if cell[DEP] not in NO_DEP:
        got = _ISSUE_CELL.match(cell[DEP])
        if not got:
            raise SprintTableError(f"#{n}: `{DEP}` must be — or one #N, got {cell[DEP]!r}")
        dep = int(got.group(1))
    if dep == n:
        raise SprintTableError(f"#{n} depends on itself")
    return Member(n, dep, cell.get(KIND))


def stored_plan_hash(body):
    """The `plan-hash:` value written in the plan block, or None. SprintTableError when malformed."""
    found = [x.strip()[len("plan-hash:"):].strip() for x in _block(body).split("\n")
             if x.lstrip().startswith("plan-hash:")]
    if not found:
        return None
    if len(found) > 1 or len(found[0]) != defaults.SPRINT_PLAN_HASH_LEN or not _HASH_VALUE.match(found[0]):
        raise SprintTableError(f"malformed plan-hash line: {found!r}"[:200])
    return found[0]


def stack_reason_token(body):
    """The tracker's stack-cap reason token (codes.StackReason value), or None when there is none / unknown."""
    found = [m.group(1) for m in (_REASON_LINE.match(x.strip()) for x in _block(body).split("\n")) if m]
    return found[0] if len(found) == 1 and found[0] in codes.StackReason.values() else None


def plan_hash(body):
    """The 12-character hash of the plan block (0.98.7 `--mode hash`, exactly). SprintTableError without one block."""
    lines = _block(body).split("\n")
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    kept = [x.replace("\r", "").rstrip() for x in lines if not x.lstrip().startswith("plan-hash:")]
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()[:defaults.SPRINT_PLAN_HASH_LEN]


# --- order ----------------------------------------------------------------------------------------------

def effective_deps(members):
    """({issue: the dependency that counts, or None}, [warning text]): a dependency outside the table (or on
    itself) is dropped with a warning (0.98.7 — one cannot wait for an Issue that is not in the sprint)."""
    inside, deps, warnings = {m.issue for m in members}, {}, []
    for m in members:
        if m.issue in deps:
            raise SprintTableError(f"duplicate member #{m.issue}")
        dep = m.base_dep
        if dep is not None and dep not in inside:
            warnings.append(f"#{m.issue}: the dependency #{dep} is outside the sprint — ignored")
            dep = None
        elif dep == m.issue:
            warnings.append(f"#{m.issue} depends on itself — ignored")
            dep = None
        deps[m.issue] = dep
    return deps, warnings


def order(members):
    """([issue], [warning text]): topological by base_dep, codes.MEMBER_KIND_RANK first, then the number
    (0.98.7 `--mode order`); a dependency outside the members is dropped with a warning. A cycle →
    SprintTableError."""
    if not members:
        raise SprintTableError("a sprint needs a member")
    deps, warnings = effective_deps(members)
    rank = {m.issue: 0 if m.kind is None else codes.MEMBER_KIND_RANK[m.kind] for m in members}
    left, out = dict(deps), []
    while left:
        ready = [n for n, d in left.items() if d is None or d not in left]
        if not ready:
            raise SprintTableError(f"the base dependencies contain a cycle: {sorted(left)}")
        out.append(min(ready, key=lambda n: (rank[n], n)))
        del left[out[-1]]
    return out, warnings


# --- dependency → base ----------------------------------------------------------------------------------

def _blocked(block):
    return DepVerdict(codes.DepBase.BLOCKED.value, block=block.value)


def member_state(facts):
    """DepVerdict of one dependency (DepFacts) — review-q0 D4, first rule that fits:
      1. facts.outcome blocked → upstream
      2. a MERGED PR and the Issue CLOSED / COMPLETED, or no PR and CLOSED / COMPLETED → default
         (this beats this run's outcome)
      3. facts.outcome through codes.BLOCK_BY_DEP_OUTCOME → dep-stopped / dep-failed
      4. local stopped → dep-stopped
      5. the rest of the §2.3 table: CLOSED / NOT_PLANNED → dep-not-planned; two open PRs → dep-pr-ambiguous;
         MERGED → default; open PR and local finished → stack; closed unmerged PR → dep-pr-closed; anything
         else → dep-not-done."""
    B = codes.MemberBlock
    states = [p["state"] for p in facts.prs]
    closed_as = facts.state_reason if facts.issue_state == "CLOSED" else None
    local = facts.local
    if facts.outcome == codes.MemberOutcome.BLOCKED.value:
        return _blocked(B.UPSTREAM)
    if closed_as == "COMPLETED" and ("MERGED" in states or not states):
        return DepVerdict(codes.DepBase.DEFAULT.value)
    if facts.outcome in codes.BLOCK_BY_DEP_OUTCOME:
        return DepVerdict(codes.DepBase.BLOCKED.value, block=codes.BLOCK_BY_DEP_OUTCOME[facts.outcome])
    if local is not None and local["stopped"]:
        return _blocked(B.DEP_STOPPED)
    if closed_as == "NOT_PLANNED":
        return _blocked(B.DEP_NOT_PLANNED)
    open_prs = [p for p in facts.prs if p["state"] == "OPEN"]
    if len(open_prs) > 1:
        return _blocked(B.DEP_PR_AMBIGUOUS)
    if "MERGED" in states:
        return DepVerdict(codes.DepBase.DEFAULT.value)
    if open_prs:
        if local is not None and local["finished"]:
            return DepVerdict(codes.DepBase.STACK.value, pr=open_prs[0])
        return _blocked(B.DEP_NOT_DONE)
    return _blocked(B.DEP_PR_CLOSED if states else B.DEP_NOT_DONE)


def base_for(verdict, default_branch, dep_issue, stack_reason):
    """BaseChoice, or a codes.MemberBlock value (str). verdict: DepVerdict, or None (no dependency → the default
    branch). STACK: stack_reason config → gld/<D>; in codes.DRAFT_STACK_REASONS → gld/<D>, draft (U1);
    merge-commit-forbidden or None → dep-unmerged (§2.4)."""
    if verdict is None or verdict.base == codes.DepBase.DEFAULT.value:
        return BaseChoice(default_branch)
    if verdict.base == codes.DepBase.BLOCKED.value:
        return verdict.block
    draft = stack_reason in codes.DRAFT_STACK_REASONS
    if not draft and stack_reason != codes.StackReason.CONFIG.value:
        return codes.MemberBlock.DEP_UNMERGED.value
    return BaseChoice(f"gld/{dep_issue}", stacked_on=dep_issue, draft=draft)


def effective_stack_reason(token, merge_settings):
    """How this run may stack: codes.StackReason value or None (→ dep-unmerged). `token` = stack_reason_token;
    `merge_settings` = sprinttracker.merge_settings ({"merge", "squash", "rebase"} bools) or None (not readable →
    None). merge commits allowed → config; forbidden → the token when it is squash-sync / human-override, None
    when it is config or missing (the plan is older than the settings); merge-commit-forbidden always stays."""
    if token == codes.StackReason.MERGE_COMMIT_FORBIDDEN.value:
        return token
    if merge_settings is None:
        return None
    if merge_settings["merge"]:
        return codes.StackReason.CONFIG.value
    return token if token in codes.DRAFT_STACK_REASONS else None


# --- the run window -------------------------------------------------------------------------------------

def parse_window(text):
    """"HH:MM-HH:MM" (24h, zero-padded; `~` read as `-`), or None for "none". ValueError otherwise, and when start
    equals end (§2.6, TW1)."""
    if text == "none":
        return None
    got = text.replace("~", "-") if isinstance(text, str) else ""
    if not _WINDOW.match(got):
        raise ValueError(f"--window must be HH:MM-HH:MM (24h, zero-padded) or none, got {text!r}")
    if got[:5] == got[6:]:
        raise ValueError(f"the window's start equals its end ({got}) — omit the window instead")
    return got


def in_window(window, hhmm):
    """True when "HH:MM" `hhmm` is inside `window` (end exclusive, may cross midnight). None = always (TW2).
    Zero-padded HH:MM compares as text: no number is parsed, so 08 and 09 are no special case."""
    if window is None:
        return True
    start, end = window[:5], window[6:]
    if start < end:
        return start <= hhmm < end
    return hhmm >= start or hhmm < end
