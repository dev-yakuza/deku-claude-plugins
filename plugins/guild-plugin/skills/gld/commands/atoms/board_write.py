#!/usr/bin/env python3
"""Board writer for `/gld sprint` (design: design/guild/03-sprint-board.md §7.1a).

Why this is code and not a series of Bash calls: `_bash_rules.md` forbids loops, `&&`, `;`
and pipes in Bash *tool* calls, so `plan`'s board writes would become one tool call per
`gh` invocation — 2M+1 for M non-members plus 6N for N members, i.e. ~123 calls for a
40-issue backlog and ~443 for a 200-issue one. The deployed precedent in `plan.md`
(Phase 6 step 3, "One member per Bash call") sits at N≈7. The `run` supervisor's own
~177 calls are exempt because a generated script's contents are outside those rules
(`_bash_rules.md:85`); `plan` is an LLM command and is not.

This is NOT a derivation. D6 was retired precisely because deriving columns in a shared
pure function made several callers assemble the same input from different sources. The
column decision is still the leader's; this script only batches the I/O and holds the
one guard that keeps `plan` from clobbering supervisor-owned cards.

⚠ INTERFACE IS FILE-BASED, NOT STDIN — same reason as `sprint_dag.py`: the sanctioned
python exception in `_bash_rules.md` is the flag form.

    python3 board_write.py --input <path>

Input (JSON):

    ⚠ ALL SIX OF `number` `owner` `repo` `field` `columns` `writes` ARE REQUIRED — a missing
    one is exit 64. `repo` is the one that is easy to forget and it is load-bearing twice: it
    builds the issue URL and it filters other repos' issues out of `item-list`.

    {
      "number": 7,                        # project number            (required)
      "owner": "acme",                    # project owner. ⚠ NEVER `@me`: measured, a user
                                          #   project cannot be linked to an org repo and
                                          #   `item-edit --url` then fails on issues that
                                          #   `item-list` happily shows (D10)
      "repo": "owner/name",               # to filter foreign issues out of item-list
      "field": "Guild board",             # column field display name
      "columns": {"backlog": "Backlog", "ready": "Ready", ...},   # token -> display name
      "owned": ["Guild board","Order",…],  # optional; when present, every field name written
                                          #   must be on it (D1 as a rule, not an intention)
      "guard": true,                      # default for writes that omit it — DEFAULTS TO TRUE
      "read": true,                       # read item-list once; defaults to `guard`
      "limit": 500,                       # item-list page size; defaults to 500
      "writes": [
        {"issue": 120, "column": "backlog"},
        {"issue": 121, "column": null},                     # clear -> null bucket = Issues
        {"issue": 101, "column": "ready", "guard": false,
         "fields": {"Order": "1", "Depends on": "#100", "Sprint": "99"},
         "clear": ["Needs human"]}
      ]
    }

Output — one line on stdout:

    wrote=<n> skipped=<n> unknown=<n> col_failed=<n> failed=<n> truncated=<0|1>

`skipped` counts writes the guard refused because the supervisor owns the card.
`unknown` counts cards whose current value is not in `columns` at all — almost always a
column renamed in the UI without updating config — plus malformed no-op entries. It is
reported apart from `skipped` because it needs a different sentence to the human.
`col_failed` counts entries whose COLUMN write failed — the only field that changes what
the board says, so it is reported apart from `failed` (which counts every `gh` call, including
`Order`/`Sprint` writes). The affected issue numbers go to stderr.
`failed` counts `gh` calls that did not
succeed; they are absorbed (D9) and never change the exit code — but they ARE counted,
because absorbing the fact of absorption is what D9 forbids.

Exit codes:

    0   ran (even with failures — D9)
    64  refused before writing anything. Four causes, and they are not all "input errors":
          - usage: missing file, bad JSON, a missing required key, an unknown column token,
            a non-numeric `issue`, two tokens sharing a display name, a field outside `owned`
          - the ownership lists overlap (`_check_ownership_lists`)
          - GitHub could not be reached for the node-id resolution (`project view` /
            `field-list` failed). ⚠ This one is TRANSIENT — a rate-limited `project view`
            produces no summary line, which `plan.md` promises unconditionally. Sanctioned by
            the design (§0.4) because writing 104-point name-addressed calls instead would
            reintroduce the cost the node-ID form removes
          - a column option this call WRITES is absent from the board
"""

import sys

# Do not leave a __pycache__ behind — this module is imported by tests/board_write_test.sh
# and a stale .pyc beside a plugin file that gets updated in place is a confusing thing to
# find. Same reasoning as `sprint_dag.py`.
sys.dont_write_bytecode = True

import argparse
import json
import subprocess

EXIT_OK = 0
EXIT_USAGE = 64

_MISS = object()   # distinguishes "no `column` key" from `"column": null` (= clear it)

# A card value we could not reverse-map. Distinct from `None` (= no value at all), because
# conflating the two is what made the guard fail open. Any string works; this one cannot
# collide with a real display name.
_UNMAPPED = "\x00unmapped"

# The four values only the `run` supervisor writes (§5.2). A card sitting on any of them is
# supervisor-owned and `plan` must not touch it — that is the whole point of the guard.
# Kept as tokens; the comparison happens after reverse-mapping the display name.
# ⚠ `ready` is NOT here, and that is deliberate. It has two writers — `plan`'s member seeding
# and the supervisor's dependency-wait repair — so classifying it supervisor-owned made every
# `Ready` card unrepairable by either: a member the human DROPS from the next sprint sits in
# `Ready` with last sprint's `Order` and `Sprint` forever, telling the human "queued, nothing to
# do" about work in no queue. `plan` refuses to run while a supervisor is live (its Phase 0
# step 4), so re-triaging a stale `Ready` into `Backlog` after a run has ended is both safe and
# the only thing that ever cleans that column. §5.4's freeze list covered cards the SUPERVISOR
# touched; this one was touched by `plan` and was stuck all the same.
SUPERVISOR_OWNED = ("in_progress", "blocked", "in_review", "done")

# What `plan` may overwrite. `issues` is not a value at all — it is the null bucket (D16), so
# "no key in the item JSON" is what it looks like; the condition is "absent, `backlog` or
# `ready`", never "absent or `issues` or …". `ready` is here for the reason above: it is the one
# column both writers touch and the only one that would otherwise accumulate cards belonging to
# no sprint.
PLAN_OWNED = ("backlog", "ready")


def _check_ownership_lists():
    """The two ownership lists must be disjoint, and together must cover every column token.

    Overlap would make the outcome depend on evaluation order in the guard — the failure mode
    that made a *display-name* collision dangerous (two tokens sharing one name let the reverse
    map pick a winner by dict order, measured). A token in NEITHER list is fine and fails closed
    (`writable` stays False), which is the safe default for a column added later.
    """
    both = set(PLAN_OWNED) & set(SUPERVISOR_OWNED)
    if both:
        die("PLAN_OWNED and SUPERVISOR_OWNED overlap on %s — the guard's outcome would depend "
            "on evaluation order" % ", ".join(sorted(both)))


def die(msg):
    sys.stderr.write("board_write: %s\n" % msg)
    raise SystemExit(EXIT_USAGE)


def req(d, key, where):
    if key not in d:
        die("missing key `%s` in %s" % (key, where))
    return d[key]


def gh(args):
    """Run one `gh` call. Returns (ok, stdout). Never raises — D9 absorbs failures.

    stderr is dropped on purpose: the caller gets a count, not a transcript. A failure
    here is almost always the same three causes (missing `project` scope, rate limit, a
    stale project number) and the count plus `sprint board` is how the human sees it.
    """
    try:
        p = subprocess.run(["gh"] + args, capture_output=True, text=True)
    except OSError as e:
        return False, str(e)
    return p.returncode == 0, p.stdout


def resolve_ids(cfg):
    """One `project view` + one `field-list`. Returns (project_id, fields, options).

    ⚠ WHY THIS EXISTS — the measured cost of a name-addressed write. `gh project item-edit
    <n> --owner … --url … --field <name> --value <name>` costs **104 GraphQL points**; the
    node-ID form (`--id --project-id --field-id --single-select-option-id`) costs **1**. Both
    measured four times on a live project. The hourly budget is 5000 points, so the name form
    allows ~48 writes an hour, and one 41-card projection with three data fields would need
    ~12,800 — two and a half times the whole budget. §7.5's "one field per call" accounting
    counted gh invocations and never points.

    The preparation is paid once: `project view` = 2 points, `field-list --limit 100` = ~101
    (cost is 1 + limit, measured linear). `field-list` returns field ids AND, for a
    single-select, its option ids — so nothing else has to be looked up.

    ⚠ Item ids come from the `item-list` read **when there is one**. A caller that passes
    `"read": false` has no ids and pays one `item-add` per entry instead — which is why
    `--reset` passes `"read": true` even though its guards are off.

    `fields`  maps display name -> {"id": …, "type": …}
    `options` maps the column field's option display name -> option id
    """
    # ⚠ Each failure returns EARLY with empty maps, so `main`'s two `die()`s cannot tell them
    # apart by their message — and a test asserting only "exit 64" cannot tell whether the
    # project id or the field list was the cause. `die()` here instead, with the real reason.
    ok, out = gh(["project", "view", str(cfg["number"]), "--owner", cfg["owner"],
                  "--format", "json"])
    if not ok:
        die("cannot read project %s (owner %s) — refusing to write"
            % (cfg["number"], cfg["owner"]))
    try:
        project_id = (json.loads(out or "{}") or {}).get("id")
    except ValueError:
        die("project %s returned unparseable JSON — refusing to write" % cfg["number"])
    if not project_id:
        die("project %s returned no node id — refusing to write" % cfg["number"])

    # ⚠ 100, and it must MATCH the supervisor's. `--limit` costs 1 point per requested node
    # (measured linear at 1/5/10/30/100/200), so tight is cheaper — but a board already carries
    # GitHub's ~13 built-in fields plus Guild's 5, and a short read is FATAL (the `totalCount`
    # check below refuses rather than building a partial map). Two readers with two limits meant
    # one of them died on a board the other called healthy; the diagnostic reading further than
    # the writer is the worst arrangement of the two.
    ok, out = gh(["project", "field-list", str(cfg["number"]), "--owner", cfg["owner"],
                  "--limit", "100", "--format", "json"])
    if not ok:
        die("cannot read the fields of project %s — refusing to write" % cfg["number"])
    try:
        data = json.loads(out or "{}") or {}
    except ValueError:
        die("field-list for project %s returned unparseable JSON — refusing to write"
            % cfg["number"])

    fields, options = {}, {}
    flist = data.get("fields") or []
    total = data.get("totalCount")
    if total is not None and len(flist) != total:
        # A short field list means a field we need may be missing from it, and "missing" is
        # indistinguishable from "renamed" downstream. Refuse rather than write to whatever
        # subset came back. ⚠ `die()` with the reason, not an empty map — an empty map made the
        # NEXT check ("column field does not exist") fire, so a test could not tell a truncated
        # read from a renamed field, and deleting this check left the suite green.
        die("field-list for project %s returned %d of %d fields — refusing to write to a "
            "partial field map" % (cfg["number"], len(flist), total))
    for f in flist:
        name = f.get("name")
        if not name:
            continue
        if not f.get("id"):
            # A field with no id cannot be addressed. Letting it through reached
            # `subprocess.run` with `None` in the argv and raised an uncaught TypeError —
            # exit 1, which is not in the documented set {0, 64}.
            continue
        fields[name] = {"id": f.get("id"), "type": f.get("type")}
        if name == cfg["field"]:
            for opt in f.get("options") or []:
                if opt.get("name"):
                    options[opt["name"]] = opt.get("id")
    return project_id, fields, options


def read_cards(cfg):
    """Read `item-list`, escalating the limit until it is not truncated.

    Returns (by_issue, truncated, read_failed).

    by_issue maps issue number -> (raw display-name string for the column field or None when
    the field has no value on that card, project item node id).

    Four measured facts about the output shape drive this function (§7.1a):
      1. The JSON key is the field name with only its first letter lowercased and spaces
         kept — `"Guild board"` comes back as `"guild board"`. Same for `"needs human"`.
      2. Values are DISPLAY NAMES (`"In review"`), not tokens.
      3. A card with no value for the field has NO KEY at all in RAW `--format json` output —
         that absence is the null bucket, i.e. the `Issues` column. ⚠ After the `--jq`
         projection below, jq **materialises it as `null`** instead (measured), so post-jq the
         key is present with a null value. `it.get(key)` collapses both to `None`, so the guard
         is right either way — but do not "simplify" it to a `key in it` test.
      4. Items must be matched by `.content.number` AND `.content.repository`: a real
         board carries issues from other repos, and draft items have no `number`.
    """
    # ⚠ ESCALATE, do not just give up. `truncated` disables every guarded write, and Guild
    # never archives cards (§10: "보드가 누적된다"), so a long-lived board WILL cross any
    # fixed limit — and from that day on the whole intake half of the board stops updating
    # on every `plan`, forever, reported through the same word as a benign guard refusal.
    # `totalCount` comes back in the same response, so one re-read at the real size fixes it.
    limit = int(cfg.get("limit") or 500)
    items, total, read_failed = [], None, False
    for attempt in (0, 1):
        ok, out = gh([
            "project", "item-list", str(cfg["number"]),
            "--owner", cfg["owner"], "--format", "json", "--limit", str(limit),
            # Project away `content.body`: raw output carries every item's full issue body,
            # which at limit 500+ is hundreds of KB through a pipe for four fields we need.
            # ⚠ Measured: `--jq` applies AFTER gh builds the `{items:…, totalCount:…}` envelope,
            # so the expression sees `.items` and `.totalCount` — and `--format json` is
            # mandatory alongside it (`cannot use --jq without specifying --format json`).
            # ⚠ `json.dumps` for BOTH slots. A `"` in the field name produced a malformed jq
            # program, `gh` failed, and that surfaced as `read_failed`/`truncated` — the guard
            # silently disabling while unguarded member seeding kept writing.
            "--jq", "{items: [.items[] | {id: .id, content: {number: .content.number, "
                    "repository: .content.repository}, %s: .[%s]}], "
                    "totalCount: .totalCount}" % (json.dumps(_json_key(cfg["field"])),
                                                  json.dumps(_json_key(cfg["field"]))),
        ])
        if not ok:
            # Could not read -> could not guard. Writing anyway is the damage the guard
            # exists to prevent, so this is treated exactly like truncation — but it is ALSO
            # a failed `gh` call, and D9 requires those be counted, not folded into
            # "the board is too big".
            return {}, True, True
        try:
            data = json.loads(out or "{}")
        except ValueError:
            return {}, True, True

        items = data.get("items") or []
        total = data.get("totalCount")
        # `total is None` is fail-CLOSED on purpose: without it we cannot prove completeness,
        # and a payload shape that drops the key would silently disable the whole guard.
        if total is None:
            return {}, True, False
        if len(items) == total:
            break
        if attempt == 0:
            limit = total + 50          # read the real size, once
    truncated = len(items) != total

    key = _json_key(cfg["field"])
    by_issue = {}
    for it in items:
        content = it.get("content") or {}
        num = content.get("number")
        if num is None:                                   # draft item — no issue behind it
            continue
        if content.get("repository") != cfg["repo"]:
            continue                                      # another repo's issue, or no repo

        # (display value, project item node id) — the id is what makes a 1-point write
        # possible instead of a 104-point one, and it comes free with this read.
        by_issue[int(num)] = (it.get(key), it.get("id"))

    # ⚠ KNOWN LIMITATION, deliberately not "fixed". If `cfg["repo"]` never matches any item's
    # `.content.repository` — a rename, a non-canonical `owner/repo` — every card reads as
    # absent, absent means writable, and the guard waves everything through. Failing closed on
    # "items exist but none are ours" was tried and is WRONG: a first `plan --create` sees
    # exactly that on a freshly created board, and on any board that already carries another
    # repo's issues. Refusing there would make the primary path write nothing. The repo
    # string comes from `_handoff.md` Section F's single resolution, not from config, so the
    # realistic failure is a rename between resolution and this call — narrow enough to accept
    # rather than pay for with a broken first run.
    return by_issue, truncated, read_failed


def _value_flag(ftype, val):
    """Node-ID writes need the flag that matches the field's data type.

    `--value` exists only alongside `--field` (the name form), so it is unavailable here.
    Measured: `--text` on a TEXT field costs 1 point and works; the same call against the
    built-in `Title` is rejected. `board.md` specifies all four of Guild's data fields as TEXT,
    which is why TEXT is the only shape written. A field whose type was changed to NUMBER or
    DATE in the GitHub UI will reject `--text` — that call fails, is counted in `failed`, and the
    mismatch is what `sprint board` Phase S step 3 reports. Guessing the type from the value
    would write a number into a text field and a text into a number field with equal
    confidence; refusing loudly is better than being right half the time.
    """
    return ["--text", str(val)]


def _json_key(field_name):
    """`"Guild board"` -> `"guild board"` (measured: first letter lowercased, spaces kept)."""
    return field_name[:1].lower() + field_name[1:]


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--input", required=True)
    ns = ap.parse_args(argv)

    try:
        with open(ns.input) as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as e:
        die("cannot read --input: %s" % e)

    _check_ownership_lists()

    for k in ("number", "owner", "repo", "field", "columns", "writes"):
        req(cfg, k, "input")

    # `owned` is optional but load-bearing when present: §4.3 calls it "the only thing that
    # makes D1 a rule rather than an intention". Without enforcement it was a dead key — a
    # hand-edited `config.sprint.board.fields.needs_human` pointing at `Assignees` would have
    # Guild writing the human's own field with nothing refusing. Enforced here because this is
    # the one place every `plan`/`--reset` field name passes through.
    owned = cfg.get("owned")
    if owned is not None:
        if not isinstance(owned, list):
            die("`owned` must be a list of field names")
        owned_set = set(owned)
        if cfg["field"] not in owned_set:
            die("column field `%s` is not in `owned`" % cfg["field"])
        for w in cfg["writes"] if isinstance(cfg["writes"], list) else []:
            if not isinstance(w, dict):
                continue
            for fname in list((w.get("fields") or {}).keys()) + list(w.get("clear") or []):
                if fname not in owned_set:
                    die("field `%s` is not in `owned` — refusing to write a field Guild "
                        "does not own (D1)" % fname)
    columns = cfg["columns"]
    writes = cfg["writes"]
    if not isinstance(columns, dict):
        # Same class as the `issue: "#101"` slip: an uncaught AttributeError exits 1, which is
        # not in the documented exit set {0, 64}, and prints no summary line.
        die("`columns` must be an object, got %s" % type(columns).__name__)
    if not isinstance(writes, list):
        die("`writes` must be a list")

    # token -> display name, and the reverse. The reverse map is what makes the guard
    # survive a human renaming a column in the UI (D7): we compare tokens, never the
    # literal display string.
    display_of = {}
    token_of = {}
    for tok, disp in columns.items():
        display_of[tok] = disp
        # Two tokens mapping to one display name makes the reverse map pick a winner by dict
        # order, and the loser's cards become writable — measured: with
        # {"ready":"Backlog","backlog":"Backlog"} a supervisor `Ready` card was overwritten,
        # and swapping the two keys flipped the outcome. Refuse before anything is written.
        if disp in token_of:
            die("two column tokens share the display name `%s` (`%s` and `%s`)"
                % (disp, token_of[disp], tok))
        token_of[disp] = tok

    # ⚠ DEFAULT IS ON — fail closed. An earlier version defaulted to False, which meant a
    # caller that simply omitted the key got NO guard and no `item-list` read at all: every
    # write went through and a supervisor-written `Blocked` became `Backlog`, unrecoverably
    # (`sprint board --reset` deliberately never clears the column field). The prompt did
    # not spell the key out, and every test supplied it — so the tests were green over a
    # live hole. Member seeding is the only caller that wants the guard off and it says so
    # per entry (`"guard": false`), which is the right place for an explicit exception.
    # ⚠ VALIDATE EVERY ENTRY BEFORE THE FIRST `gh` CALL. `die()` used to fire from inside the
    # write loop, so a single stale column token meant: earlier entries already written, the
    # rest silently dropped, exit 64, and NO summary line on stdout — breaking the one-line
    # contract this script documents and leaving `plan` with nothing to report. Once writing
    # has begun we never die; we count.
    for w in writes:
        if not isinstance(w, dict):
            die("each `writes` entry must be an object")
        if "issue" not in w:
            die("missing key `issue` in writes[]")
        try:
            int(w["issue"])
        except (TypeError, ValueError):
            # `#101` is the convention in the SAME input document (`"Depends on": "#100"`),
            # so this is a plausible slip in a hand-written file — and it used to be an
            # uncaught ValueError: exit 1, which is not even in the documented exit set.
            die("`issue` must be a number, got %r" % (w["issue"],))
        col = w.get("column", _MISS)
        if col is not _MISS and col is not None and col not in display_of:
            die("unknown column token `%s`" % col)

    default_guard = bool(cfg.get("guard", True))
    need_read = bool(cfg.get("read", default_guard)) or any(
        bool(w.get("guard", default_guard)) for w in writes if isinstance(w, dict)
    )

    # ⚠ RESOLVE FIRST. `read_cards` is ~501 points at the default limit and `resolve_ids` is
    # ~103; every `die()` below throws the expensive one away. Order costs nothing and saves
    # ~500 points on every refusal.
    project_id, fields, options = resolve_ids(cfg)
    if not project_id or not fields:
        die("cannot resolve project/field node ids for project %s (owner %s) — "
            "refusing to write" % (cfg["number"], cfg["owner"]))
    if cfg["field"] not in fields:
        die("column field `%s` does not exist on the board" % cfg["field"])

    cards, truncated, read_failed = ({}, False, False)
    if need_read:
        cards, truncated, read_failed = read_cards(cfg)
    # ⚠ ONLY the tokens this call actually writes. Validating all six killed `plan`'s whole
    # board step — member seeding included — when a human renamed a column `plan` never touches
    # (`in_progress`/`blocked`/`in_review`/`done` are supervisor-owned), and killed `--reset`
    # outright even though it never addresses the column field at all. Both then exited 64 with
    # NO summary line, in exactly the scenario `plan.md` promises `unknown=<n>` plus a
    # one-line-config-edit remedy, and D9 promises a summary and exit 0. A mismatch on a token
    # we do not write is not our problem at write time; it becomes `unknown` if a card is
    # sitting on it, which is the documented behaviour.
    needed = set()
    for w in writes:
        if isinstance(w, dict):
            c = w.get("column", _MISS)
            if c is not _MISS and c is not None:
                needed.add(c)
    for tok in sorted(needed):
        disp = display_of.get(tok)
        if disp not in options:
            die("column option `%s` (token `%s`) does not exist on field `%s` — "
                "the board and `config.sprint.board.columns` disagree"
                % (disp, tok, cfg["field"]))
    # The rest are reported, not fatal: the human still wants to know config drifted.
    for tok, disp in sorted(columns.items()):
        if tok not in needed and disp not in options:
            sys.stderr.write("board_write: note — column option `%s` (token `%s`) is not on the "
                             "board; this call does not write it\n" % (disp, tok))

    wrote = skipped = failed = unknown = col_failed = 0
    col_failed_issues = []
    if read_failed:
        failed += 1        # a gh call DID fail; D9 counts it (§5.2)

    # Read-but-truncated means the guard cannot prove anything. Writing anyway is how a
    # supervisor-written `blocked` card gets overwritten with `Backlog` — the exact damage
    # the guard exists to prevent. So: skip every guarded write, report truncated=1, and
    # let the caller surface it. Unguarded writes (member seeding) still go through.
    for w in writes:
        # ⚠ int(), not the raw value. The pre-pass proves `int()` succeeds; using the raw value
        # in the URL let `120.9` and `" 120 "` through to `.../issues/120.9` — reported as
        # `wrote=1` against an issue that does not exist.
        issue = int(w["issue"])
        guarded = bool(w.get("guard", default_guard))
        col = w.get("column", _MISS)

        if guarded:
            if truncated:
                skipped += 1
                continue
            entry_g = cards.get(issue)
            current_disp = entry_g[0] if isinstance(entry_g, tuple) else None
            if not isinstance(current_disp, str):
                # gh exports some field types as objects (an iteration field is
                # `{"title": …}`). Only a single-select's string value is meaningful here,
                # and an object used to crash on `token_of.get(dict)` with a TypeError.
                current_disp = None if current_disp is None else _UNMAPPED
            present = current_disp is not None
            current_tok = token_of.get(current_disp)

            # ⚠ THREE STATES, NOT TWO. `current_tok is None` used to mean both "the card has
            # no value at all" (the null bucket = `Issues`, writable) and "the card has a
            # value we cannot reverse-map" — and the second was treated as writable, so the
            # guard failed OPEN in exactly the situation D7 was written for: a human renames
            # `In progress` to `Doing` in the UI without updating config, and the next `plan`
            # moves a live in-progress card to `Backlog` and reports it as `wrote=1`.
            # Measured. An unmappable value is now refused AND counted apart, because
            # "3건 생략(감독자 소유)" and "40건 생략(컬럼 이름이 config와 다릅니다)" are
            # different sentences to the human.
            if present and current_tok is None:
                unknown += 1
                continue
            # ⚠ `PLAN_OWNED` is the sole authority, and the check below is a BACKSTOP that is
            # unreachable while the two lists stay disjoint — which `_check_ownership_lists()`
            # now enforces at startup. No test can reach it, and a review round confirmed that
            # deleting it changes no observable behaviour. It stays because the day someone adds
            # a token to both lists it becomes the only thing that refuses, and the startup check
            # is what makes that day loud instead of silent.
            writable = (not present) or current_tok in PLAN_OWNED
            if current_tok in SUPERVISOR_OWNED:
                writable = False
            if not writable:
                skipped += 1
                continue

        url = "https://github.com/%s/issues/%s" % (cfg["repo"], issue)

        # The item node id comes from the guard's read. A card that is not on the board yet has
        # none — `item-add --format json` returns it, and `item-add` is idempotent (measured:
        # same item id, exit 0), so this doubles as the self-heal path `--setup`-run-mid-sprint
        # needs. One add per missing card, never per write.
        entry = cards.get(issue)
        item_id = entry[1] if isinstance(entry, tuple) else None
        if not item_id:
            ok, out = gh(["project", "item-add", str(cfg["number"]),
                          "--owner", cfg["owner"], "--url", url, "--format", "json"])
            if ok:
                try:
                    item_id = (json.loads(out or "{}") or {}).get("id")
                except ValueError:
                    item_id = None
            if item_id:
                cards[issue] = (entry[0] if isinstance(entry, tuple) else None, item_id)
        if not item_id:
            # No id, no node-ID write. Falling back to the 104-point name form here would
            # reintroduce the cost the whole change removes, and it would do so exactly on the
            # cards that are hardest to reach anyway.
            failed += 1
            if col is not _MISS:
                col_failed += 1
                col_failed_issues.append(str(issue))
            continue

        base = ["project", "item-edit", "--id", item_id, "--project-id", project_id]

        did_any = False
        if col is not _MISS:
            fid = fields[cfg["field"]]["id"]
            if col is None:
                ok, _ = gh(base + ["--field-id", fid, "--clear"])
            else:
                ok, _ = gh(base + ["--field-id", fid,
                                   "--single-select-option-id", options[display_of[col]]])
            if ok:
                did_any = True
            else:
                failed += 1
                # ⚠ The COLUMN is the only field that changes what the board says. Folding its
                # failure into the same `failed` count as an `Order` write meant an entry could
                # be reported in BOTH `wrote` and `failed`, and the caller could not learn that
                # up to N of the "41 recorded" cards are in the wrong column. Counted apart, and
                # the issue numbers go to stderr so the human can fix them by hand or re-run.
                col_failed += 1
                col_failed_issues.append(str(issue))

        for fname, fval in (w.get("fields") or {}).items():
            meta = fields.get(fname)
            if not meta:
                # The field was renamed or deleted in the UI. Refusing is right — the
                # alternative is writing a value nowhere the human will find it.
                failed += 1
                continue
            ok, _ = gh(base + ["--field-id", meta["id"]] + _value_flag(meta["type"], fval))
            if ok:
                did_any = True
            else:
                failed += 1

        for fname in (w.get("clear") or []):
            meta = fields.get(fname)
            if not meta:
                failed += 1
                continue
            ok, _ = gh(base + ["--field-id", meta["id"], "--clear"])
            if ok:
                did_any = True
            else:
                failed += 1

        if did_any:
            wrote += 1
        elif col is _MISS and not w.get("fields") and not w.get("clear"):
            # No column, no fields, nothing to clear: zero gh calls, so it belonged in
            # neither `wrote` nor `failed` and the counts stopped summing to len(writes).
            # A malformed entry the caller cannot see is a malformed entry that repeats.
            unknown += 1

    if col_failed_issues:
        sys.stderr.write("board_write: column write failed for: %s\n"
                         % " ".join("#" + n for n in col_failed_issues))
    sys.stdout.write("wrote=%d skipped=%d unknown=%d col_failed=%d failed=%d truncated=%d\n"
                     % (wrote, skipped, unknown, col_failed, failed,
                        1 if truncated else 0))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
