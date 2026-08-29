#!/usr/bin/env python3
"""Draw the central/local boundary in an existing persona file.

`update` refreshes the region between `<!-- guild:persona:start -->` and
`<!-- guild:persona:end -->` from the role's template. A repo initialized before those
markers shipped has none, so `update` skips its personas. This script is what
`/gld update --migrate-personas` runs to insert them.

Three modes, one Bash tool call each (`_bash_rules.md` sanctioned exception 1 — a single
bundled Python invocation):

    --mode classify --init <sha>              which roles are mechanical, which need a human
    --mode insert   --file <f>                insert the three markers, nothing else
    --mode check    --file <f> [<f>...]       structural verification (any number of files)
                    [--base <sha>]            ...plus a loss check against that commit
                    [--scope below-end]       ...covering only what update promises not to touch

⚠ THE ANCHOR IS A PARAMETER, NOT A LITERAL. The heading that closes the central region is
`## 프로젝트 특화` only in a `ko` repo — `init` renders it in `config.language`. `--anchor`
defaults to the ko form because that is every repo this migration currently targets, but a
non-ko repo must pass its own, and `init`'s post-write check always passes the heading it
just rendered. Hard-coding it would leave a non-ko repo with no migration path at all and no
error message saying so: every persona would report `HITL(anchor=0)` and look corrupt.
`--habits-heading` is the same story for the local section `insert` appends.

`--base` is optional because two callers need the structure check without it: `init` verifies
files it just wrote (there is no "before"), and `update` step 4 verifies files it just rewrote.
Only migration has a meaningful base to compare against.

WHY A SCRIPT AND NOT PROSE. Classification compares diff hunk ranges against two line
positions; insertion computes three offsets. Both are calculations, and a calculation
written as prose gets a different answer on different runs. The same reasoning that put
`sprint_dag.py` and `board_write.py` on disk applies here.

EXIT CODES — distinct on purpose, so a caller can branch without parsing stderr:
    0   done (classify: always 0 — the verdicts are on stdout)
    2   guard failed: this file cannot be migrated mechanically (insert/check)
    3   check found a real problem (loss, or markers mis-placed)
    64  usage error — bad flags, missing file, unreadable input

The 64 matters: without it a typo in --file reports as "guard failed" and a human goes
looking for a malformed persona that is fine.
"""

import argparse
from collections import Counter
import glob
import os
import re
import subprocess
import sys

# The script is invoked as `python3 persona_migrate.py …`, and CPython never caches the
# __main__ script — so this line buys nothing on the shipped path. It is kept for the case
# that costs something: `import persona_migrate` from a test or a REPL, which WOULD write a
# .pyc next to the script. (Even then the flag is too late to stop that first write; it stops
# the ones after.) The concern is real — in a user's repo an untracked __pycache__ would show
# up in the dirty-tree snapshot update step 2 takes.
sys.dont_write_bytecode = True

START = "<!-- guild:persona:start -->"
END = "<!-- guild:persona:end -->"
HABITS = "<!-- guild:persona:habits -->"
ANCHOR_KO = "## 프로젝트 특화"
HABITS_HEADING_KO = "## 역할 습관 (로컬 — evolve가 기른다)"
# ⚠ Localized by `init`, so migration must be able to write the localized form too. Writing the
# Korean line into a Japanese file produces a state `init.md` and `evolve.md` both say cannot
# exist — and `audit`/`monitoring` key on it to tell "no habit yet" from "day-1 boilerplate".
HABITS_PLACEHOLDER_KO = "- (아직 없음 — `/gld evolve`가 이 역할의 습관을 여기에 쌓는다.)"

USAGE, GUARD, PROBLEM = 64, 2, 3


def die(msg, code=USAGE):
    print(msg, file=sys.stderr)
    sys.exit(code)


def read(path):
    try:
        return open(path, encoding="utf-8").read()
    except OSError as e:
        die(f"cannot read {path}: {e}")


def read_raw(path):
    """The file with its line terminators intact.

    `insert` must not touch a line it did not add. Universal-newline reading plus a default
    write converts a CRLF persona to LF — every line rewritten, `13 deletions` in a diff that
    should read `6 insertions, 0 deletions`, and the loss check cannot see it because `\r` is
    stripped on both sides. The reviewable migration diff §7.4 step 5 depends on is destroyed.

    Reading with `newline=""` keeps each line's own `\r`, so splitting on `\n` and rejoining
    reproduces the file byte for byte — including a file whose terminators are MIXED, which a
    single "is this a CRLF file?" answer necessarily corrupts one way or the other.
    """
    try:
        return open(path, encoding="utf-8", newline="").read()
    except OSError as e:
        die(f"cannot read {path}: {e}")


def eol_of(lines):
    """The terminator to give lines this run ADDS: whatever the file mostly uses.

    ⚠ Cosmetic, and the suite does not pin it. What actually prevents the CRLF damage is
    `read_raw` + `newline=""` on the write — those reproduce every existing line byte for
    byte, and mutating either one is caught. This function only decides whether the six
    lines being inserted match their neighbours; getting it wrong introduces mixed
    terminators but deletes nothing, so no check can distinguish it from correct output.
    """
    cr = sum(1 for l in lines if l.endswith("\r"))
    return "\r" if cr * 2 > len(lines) else ""


def git(*args):
    """Run git. Returns (ok, stdout).

    ⚠ The caller MUST look at `ok`. An earlier version returned '' on failure and called that
    "no history to go on, which is the safe reading" — it is not. In `classify`, an empty diff
    means *nothing changed*, which is the T1 verdict, which is the dangerous direction. So a
    git that fails, or that a repo has configured to emit something other than a unified diff,
    silently turned real local growth into "safe to migrate mechanically".
    """
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    # On failure the caller gets git's own message, not an empty string. `HITL(git-log-failed)`
    # on all sixteen roles with nothing else to go on is not an actionable verdict — the cause
    # (`fatal: bad boolean config value 'bogusvalue' for 'log.follow'`) was in stderr and got
    # dropped, and re-classifying returns the identical verdict forever.
    return (True, r.stdout) if r.returncode == 0 else (False, r.stderr.strip())


def git_out(*args):
    """stdout on success, empty string on failure.

    ⚠ Must discard the failure payload explicitly. Since `git()` began returning stderr on
    failure, "just take element 2" would hand the caller an error message where it expects a
    path — `rel_to_repo`'s `if not root` fallback stopped being reachable and it computed a
    relpath against `fatal: not a git repository…`.

    ⚠ NOT COVERED BY THE SUITE, and deliberately. The only caller is `rel_to_repo`, reached from
    `check_one` when `--base` is set — and outside a repo `git show` fails either way, so the
    printed output is identical with the bug and without it. The only way to observe the
    difference is to import this module, which writes a `.pyc` beside it and trips the check that
    exists to keep the user's tree clean. A latent defect fixed on inspection; do not read its
    absence from the suite as coverage.
    """
    ok, out = git(*args)
    return out if ok else ""


def rel_to_repo(path):
    """`path` as git sees it: relative to the repo root, forward slashes."""
    root = git_out("rev-parse", "--show-toplevel").strip()
    if not root:
        return path
    # realpath on BOTH sides: git reports the physical path, and on macOS /tmp, /var and
    # $TMPDIR are all symlinks — so an absolute --file under any of them would otherwise
    # compute a relpath git cannot resolve, and a sound file would fail the lossless check.
    try:
        return os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    except ValueError:
        return path


def hunk_lines(diff):
    """Line numbers (in the NEW file) that a unified diff touches.

    A pure deletion (`@@ -n +m,0 @@`) touches no new line, so it is recorded as the two
    lines that straddle the removal — otherwise deleting the last line of the central
    region would look like it happened outside the region.
    """
    out = []
    for m in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start = int(m.group(1))
        count = 1 if m.group(2) is None else int(m.group(2))
        out += [start, start + 1] if count == 0 else list(range(start, start + count))
    return out


def marker_counts(lines):
    """(start, end) counts, by line equality — the way every other check judges it.

    ⚠ ONE DEFINITION, because four consumers had two. `classify` and `insert` used a whole-file
    substring test while `check` and `update`'s rule 2 used line equality — so a persona that
    merely *mentions* `<!-- guild:persona:start -->` in its own prose (a tech-writer
    documenting the convention is the obvious case) read as `done` to migration and as "no
    markers" to everything else.
    """
    return (sum(1 for l in lines if l.strip() == START),
            sum(1 for l in lines if l.strip() == END))


def pair_state(lines):
    """`none` · `both` · `broken` — and the three are not interchangeable.

    ⚠ AND, NOT OR. An earlier version answered one question ("any marker present?") for two
    callers that need different ones. `classify` asks *is this role finished* — only `both`
    means yes. `insert` asks *may I write markers here* — anything but `none` means no.
    Collapsing them made a file with a destroyed `persona:start` report `done` to the
    classifier AND get refused by insert, while rule 2 kept sending it to migration: the role
    could never be repaired and never received another central update.
    """
    s, e = marker_counts(lines)
    if s == 0 and e == 0:
        return "none"
    if s == 1 and e == 1:
        return "both"
    return "broken"


def landmarks(lines, anchor_text):
    """(h1, anchor) as 1-based line numbers, or a reason string if the file cannot be
    migrated mechanically. Both must be unique and in order: the H1 opens the central
    region and the anchor closes it, so an ambiguous either end means an ambiguous split.
    """
    h1 = [i for i, l in enumerate(lines, 1) if l.startswith("# ")]
    anchor = [i for i, l in enumerate(lines, 1) if l.startswith(anchor_text)]
    if len(h1) != 1 or len(anchor) != 1:
        return f"h1={len(h1)} anchor={len(anchor)} (each must be exactly 1)"
    if h1[0] > anchor[0]:
        return "h1 sits below the anchor"
    return h1[0], anchor[0]


# ── classify ────────────────────────────────────────────────────────────────────────

def region_headings(lines, h1, anchor):
    """`## ` headings that would fall INSIDE the central region (between H1 and the anchor)."""
    return [l.rstrip() for l in lines[h1:anchor - 1] if l.startswith("## ")]


def template_headings(tpl_path):
    """Headings inside the template's marker region.

    ⚠ DIES rather than returning "none found". An earlier version returned None for an absent
    or malformed template and the caller mapped that to an empty list — indistinguishable from
    "this file has no foreign headings", which is the T1 verdict, which is the dangerous
    direction. That is the same fallacy the `git()` wrapper was rewritten to remove: a lookup
    that failed must never read as evidence of absence. `--templates` is a path the caller
    resolves from `<<SKILL_DIR>>`, and a marketplace install and a local checkout put it in
    different places, so getting it wrong is an ordinary mistake, not an exotic one.
    """
    tl = read(tpl_path).split("\n")
    a = [i for i, l in enumerate(tl) if l.strip() == START]
    b = [i for i, l in enumerate(tl) if l.strip() == END]
    if len(a) != 1 or len(b) != 1:
        # Per-role, so one malformed template does not abort the run. `templates_ok()` already
        # rejected a wrong --templates path; this is a defect in one template, and killing the
        # other fifteen verdicts to report it helps nobody. The caller turns it into a verdict.
        return None
    return [l.rstrip() for l in tl[a[0] + 1:b[0]] if l.startswith("## ")]


def templates_ok(templates_dir):
    """Fail loudly if `--templates` does not point at a template directory.

    Checked ONCE, for the directory — not per role. Those are different failures and only one
    of them is fatal: a wrong `--templates` path disables the foreign-heading guard for every
    role at once, while a role with no template of its own is `local-only`, which rule 1
    already puts outside migration scope. Conflating them made one retired role abort the whole
    classify run at exit 64, and every file sorted after it went unclassified.
    """
    # Two guards, one observable: deleting the isdir test still exits 64 via the glob below
    # (a nonexistent directory globs to nothing). Kept anyway because it names the actual
    # problem — "does not name a directory" beats "no *.md templates under nope".
    if not templates_dir or not os.path.isdir(templates_dir):
        die(f"--templates does not name a directory: {templates_dir or '(missing)'}. Without "
            f"it the foreign-heading guard cannot run and a false T1 would go undetected")
    md = glob.glob(os.path.join(templates_dir, "*.md"))
    if not md:
        die(f"no *.md templates under {templates_dir} — is this the right directory?")
    # And they must be PERSONA templates. `*.md` alone accepts the sibling `templates/standards/`
    # directory, and then every role reports `local-only` — which reads as "nothing to migrate",
    # a steady state needing no action. A wrong path has to look like an error, not like success.
    if not any(START in read(f) for f in md):
        die(f"{templates_dir} has no persona templates (none contains {START}) — this looks like "
            f"a different templates directory")


def foreign_headings(path, lines, h1, anchor, templates_dir, localized=False):
    """Headings inside the prospective region that the central template does not have.

    THIS IS THE ONLY MECHANICAL DETECTOR OF THE FALSE-T1 CASE. The git oracle compares the
    file against its own init commit, so a local section that went in WITH that commit — day-1
    customization, or a section `/gld audit` routed there — produces an empty delta and reads
    as T1. Insertion then closes the region below it and the next `update` deletes it, with
    every loss and structural check green: the section is above the end marker, so nothing
    downstream is looking at it.

    ⚠ IT CATCHES TWO THINGS AND CANNOT TELL THEM APART, BY DESIGN. A heading absent from the
    current template is either (a) a locally-grown section, or (b) central text whose heading
    was renamed centrally since this repo was initialized. Measured, both occur: `word_app`'s
    `leader.md` carries `## 코드상태 사실확인 (analyze 필수)`, which has never existed in the
    template — case (a), and exactly the loss this guard exists to prevent. Both repos' 
    `product-owner.md` carries `## 책임 (참여 스테이지)` where the template now reads
    `## 책임 (참여 스테이지 — 조건부)` — case (b), a false positive.

    Separating them would need the template as of the init commit, and §12 rejected bundling
    historical templates. So both go to a human, and the message must not claim which one it
    found. A false T2 costs review time; a false T1 costs local knowledge silently.
    """
    tpl_path = os.path.join(templates_dir, os.path.basename(path))
    if not os.path.exists(tpl_path):
        return "local-only"
    # ⚠ In a repo whose personas were rendered in another language, the comparison below is
    # between translated headings and the template's Korean ones — it can never match, so every
    # role would report T2 with an explanation that is false ("a locally-grown section, or a
    # central rename"). It is neither, and a human following the first branch cuts the central
    # sections out of the region with every check still green. The caller sets `localized` from
    # `config.language`; there the diff alone decides T1/T2 and this guard simply does not run.
    if localized:
        return []
    tpl = template_headings(tpl_path)
    if tpl is None:
        return "bad-template"
    return [h for h in region_headings(lines, h1, anchor) if h not in tpl]


def central_diff(path, init_sha):
    """(ok, diff) for `<init>..HEAD` on one file, with every renderer defeated.

    ⚠ ONE FUNCTION, TWO CALLERS, on purpose. `classify` and `insert --init` ask the same
    question and must not answer it differently. They did: the guard added to `insert` was a
    second copy of the diff invocation, without `--text` and without the hunkless-output
    backstop — so a repo with `*.md -diff` got `T2` from the classifier and a silent, green
    migration from the guard that exists to stop exactly that.
    """
    ok, diff = git("-c", "diff.external=", "diff", "--no-ext-diff", "--no-textconv",
                   "--text", "-U0", f"{init_sha}..HEAD", "--", path)
    if not ok:
        return False, "git-diff-failed"
    if diff.strip() and "@@" not in diff:
        return False, "diff-without-hunks — check .gitattributes for `-diff`"
    return True, diff


def classify(init_sha, agents_dir, anchor_text, templates_dir, localized=False):
    """Print `<file> <verdict>` per persona.

    The question is narrow: did anything grow inside what will become the central region?
    Everything else about the file is local either way, so it does not bear on whether the
    markers can be inserted mechanically.

    The premise is that `update` has never written to `.claude/agents/*` — true until this
    feature ships — so any change after the `init` commit is local. `HITL(not-from-init)`
    is where that premise does not hold for a given file.
    """
    files = sorted(glob.glob(os.path.join(agents_dir, "*.md")))
    if not files:
        die(f"no persona files under {agents_dir}")
    for path in files:
        # ⚠ ALREADY MIGRATED IS ITS OWN VERDICT, and it has to come first. The markers this
        # tool inserts land inside the central region, so once they exist the diff against
        # init shows "growth in the region" and every done role re-classifies as T2 — which
        # routes nine finished files back to the human path. Leaving them uncommitted does
        # not help either: the dirty guard below then reports them all as HITL. The deferred
        # -T2 workflow (§0.2) depends on a second run being able to say "that one is done".
        state = pair_state(read(path).split("\n"))
        if state == "both":
            print(f"{path} done(markers already present)")
            continue
        if state == "broken":
            s_n, e_n = marker_counts(read(path).split("\n"))
            print(f"{path} HITL(marker anomaly: start x{s_n}, end x{e_n} — a human repairs the "
                  f"pair; this mode will not, because it only creates markers where there are none)")
            continue
        ok, log = git("log", "--format=%H", "--diff-filter=A", "--", path)
        if not ok:
            print(f"{path} HITL(git-log-failed: {log[:70]})")
            continue
        adds = log.split()
        if not adds:
            # Zero add-commits means git has never seen this file — it is untracked, which is a
            # different problem from "added more than once" and has a different fix. `evolve
            # --hire` produces exactly this, so it is an ordinary state, not an exotic one.
            print(f"{path} HITL(untracked — commit it, then re-classify)")
            continue
        if len(adds) > 1:
            print(f"{path} HITL(add-commits={len(adds)})")
            continue
        if adds[0] != init_sha:
            print(f"{path} HITL(not-from-init)")
            continue

        # ⚠ The diff below compares COMMITTED trees while the landmarks come from the working
        # tree. If the file is dirty, uncommitted central growth is invisible to the diff and
        # an unrelated uncommitted edit above the H1 shifts the landmarks out from under the
        # HEAD-numbered hunks — both flip a real T2 to T1. §7.3 expects personas to sit
        # uncommitted for days, so this is the normal state, not an edge case.
        ok, st = git("status", "--porcelain", "--", path)
        if not ok:
            print(f"{path} HITL(git-status-failed: {st[:70]})")
            continue
        if st.strip():
            print(f"{path} HITL(dirty — commit or stash it, then re-classify)")
            continue

        # --no-ext-diff/--no-textconv and an emptied diff.external: a repo or an inherited
        # environment that renders diffs some other way (difftastic, a textconv driver,
        # `*.md -diff`) otherwise emits no `@@` at all, which reads as "nothing changed" = T1.
        ok, diff = central_diff(path, adds[0])
        if not ok:
            print(f"{path} HITL({diff})")
            continue

        lines = read(path).split("\n")
        marks = landmarks(lines, anchor_text)
        if isinstance(marks, str):
            print(f"{path} HITL({marks})")
            continue
        h1, anchor = marks

        foreign = foreign_headings(path, lines, h1, anchor, templates_dir, localized)
        if foreign == "local-only":
            print(f"{path} local-only(no central template)")
            continue
        if foreign == "bad-template":
            # A verdict, not an exit code. `classify`'s contract is "verdicts on stdout,
            # always 0", and a Bash call returning non-zero reads as a failed command — which
            # would abort the run for the reader and throw away the fifteen verdicts that
            # printed fine, the very thing per-role handling was introduced to stop.
            print(f"{path} HITL(central template is malformed — its marker pair is not 1/1; "
                  f"this is a plugin defect, not a repo one)")
            continue
        if foreign:
            print(f"{path} T2(heading-not-in-template: {foreign[0][:40]})")
            continue
        if not diff.strip():
            print(f"{path} T1")
            continue
        touched_central = any(h1 < n < anchor for n in hunk_lines(diff))
        print(f"{path} {'T2' if touched_central else 'T1'}")


# ── insert ──────────────────────────────────────────────────────────────────────────

def insert(path, anchor_text, habits_heading, init_sha=None, templates_dir=None,
           localized=False, habits_placeholder=HABITS_PLACEHOLDER_KO):
    """Insert the three markers. Inserts only — never moves or deletes a line.

    That is the safety property of the whole migration: this run cannot lose anything.
    Loss can only happen later, when `update` replaces the central region, and only if a
    marker landed in the wrong place. Hence the guard here and `--mode check` after.
    """
    text = read_raw(path)
    lines = text.split("\n")

    state = pair_state(lines)
    if state == "both":
        die(f"{path}: already has a start/end marker pair — nothing to do", GUARD)
    if state == "broken":
        s_n, e_n = marker_counts(lines)
        die(f"{path}: broken marker pair (start x{s_n}, end x{e_n}) — a human repairs it "
            f"first; this mode only creates markers where there are none", GUARD)
    # A DUPLICATE habits marker is refused, not reused. Reusing one would migrate a file that
    # every later `update` then skips as a marker anomaly — the migration would report success
    # and change nothing that sticks. `update`'s rule 3b tells the human this mode refuses a
    # file with duplicate markers; that has to be true of all three, not just start/end.
    n_habits = sum(1 for l in lines if l.strip() == HABITS)
    if n_habits > 1:
        die(f"{path}: {n_habits} habits markers — a human must remove the duplicates first", GUARD)
    marks = landmarks(lines, anchor_text)
    if isinstance(marks, str):
        die(f"{path}: {marks}", GUARD)
    h1, anchor = marks

    # The blank line after the H1 belongs to neither side; the start marker goes below it
    # so the central region begins at the first line of prose.
    if h1 < len(lines) and lines[h1].strip() == "":
        open_at = h1 + 1
    else:
        open_at = h1

    # An existing habits block ABOVE the anchor would be swallowed by the region. `check`
    # catches it afterwards (marker order), but insert reporting success on a file it just
    # broke is the wrong signal to give the caller mid-migration.
    at_habits = [i for i, l in enumerate(lines, 1) if l.strip() == HABITS]
    if at_habits and at_habits[0] < anchor:
        die(f"{path}: habits marker sits above the anchor — a human must move it below", GUARD)

    # T1/T2 ROUTING IS A GUARD, NOT A CONVENTION. The whole point of putting classification in
    # a script was that a calculation written as prose gets a different answer on different
    # runs — and then the routing between the two paths was left as prose. Pass --init on the
    # T1 path and this refuses a file its own classifier calls T2. The T2 path deliberately
    # omits --init: there, a human has already moved the local content down and the diff
    # against init still says T2.
    # Scope, and it runs on BOTH paths. §7.4 step 1: a persona with no central template has no
    # central region, and wrapping one in markers tells the next update to overwrite local
    # prose. The T2 path omits `--init` on purpose, so this check cannot live inside it —
    # an earlier version put it there and the T2 path happily wrapped a local-only persona.
    if templates_dir:
        scope = foreign_headings(path, lines, h1, anchor, templates_dir, localized)
        if scope == "local-only":
            die(f"{path}: no central template for this role — it is local-only, and migration "
                f"does not apply (marking a central region in it would tell the next update to "
                f"overwrite local prose)", GUARD)
        if scope == "bad-template":
            die(f"{path}: this role's central template is malformed (marker pair not 1/1) — "
                f"a plugin defect; report it rather than migrating around it", GUARD)

    if init_sha:
        foreign = foreign_headings(path, lines, h1, anchor, templates_dir, localized)
        if foreign:
            die(f"{path}: T2 — a heading inside the region is not in the current template "
                f"({foreign[0][:40]}). Either it is local and must move below the anchor, or "
                f"it is central text renamed since init and can stay. A human decides.", GUARD)
        ok, st = git("status", "--porcelain", "--", path)
        if not ok:
            # Reporting a git failure as "unclean tree" sends the human to `git status` on a
            # file that is fine. Its twin in classify surfaces the message; so does this.
            die(f"{path}: cannot check whether the tree is clean ({st[:70]})", GUARD)
        if st.strip():
            die(f"{path}: working tree not clean for this file — commit or stash it first", GUARD)
        ok, diff = central_diff(path, init_sha)
        if not ok:
            die(f"{path}: cannot confirm this file is T1 ({diff})", GUARD)
        if any(h1 < n < anchor for n in hunk_lines(diff)):
            die(f"{path}: T2 — local growth inside the central region; run the T2 path", GUARD)

    cr = eol_of(lines)
    out = (lines[:open_at] + [START + cr] + lines[open_at:anchor - 1]
           + [END + cr, cr] + lines[anchor - 1:])

    # An existing habits marker is reused, never duplicated. `evolve` may have created one
    # already; a second would make every later `update` skip the file as a marker anomaly.
    #
    # The block goes after the last NON-BLANK line rather than at the literal end of file, so
    # trailing blank lines survive. `rstrip("\n")` here used to delete them — invisible to the
    # loss check (blanks are normalized away) but a real contradiction of "inserts only".
    if not any(l.strip() == HABITS for l in lines):
        last = max((i for i, l in enumerate(out) if l.strip()), default=len(out) - 1)
        out[last + 1:last + 1] = [cr, habits_heading + cr, HABITS + cr, habits_placeholder + cr]

    open(path, "w", encoding="utf-8", newline="").write("\n".join(out))
    print(f"{path} inserted"
          + ("" if HABITS not in text else " (reused existing habits marker)"))


# ── check ───────────────────────────────────────────────────────────────────────────

# Which checks each caller needs. This is a table and not prose on purpose: the caller's real
# question is "may I roll this write back?", and the answer depends on whether the failure is
# something this run could have caused. Leaving that to a human reading a list of FAIL strings
# is how a pre-existing marker anomaly gets attributed to the current run and a correct refresh
# gets discarded — the design settles it (§6.3) and an earlier draft of update.md got it wrong.
#
#   migrate     — right after --mode insert. Everything: the file was just rebuilt.
#   pre-write   — update rule 3b, BEFORE replacing the region. Structure only; a loss check has
#                 no meaning yet. These are states `update` cannot create, so a failure here
#                 means SKIP the file, never write-then-roll-back.
#   post-write  — update step 4, AFTER replacing. Only what the replacement itself can break:
#                 the anchor moved, prose stranded above it, or something below the end marker
#                 changed when nothing there should have. A failure here DOES indict this run.
PHASES = {
    "migrate":    {"loss", "count-pair", "count-habits", "order", "anchor", "stranded",
                   "unique", "start"},
    "pre-write":  {"count-pair", "count-habits", "order", "anchor", "stranded", "unique",
                   "start"},
    # ⚠ THE MARKER COUNT SPLITS, and the seam is what the replacement can reach. `update`
    # rewrites the span BETWEEN start and end, so it can swallow one of those two — and if
    # step 4 does not look, it reports success, the version bumps, and afterwards rule 2 says
    # "migration pending" while migration says "broken pair, a human repairs it": both
    # recovery routes dead-end. So `count-pair` belongs in post-write.
    #
    # `count-habits` does not. That marker lives below the end marker, outside anything the
    # replacement writes, so an anomaly there was a human editing the file mid-run — and the
    # design's objection applies exactly: rolling back cannot fix a defect this run did not
    # cause, and would discard a correct refresh every time. Report it, do not roll back.
    #
    # This is the design's rule (§6.3) with the seam drawn one level finer, not a reversal of
    # it: "states `update` cannot create" is true of the habits marker and false of the pair.
    "post-write": {"loss", "count-pair", "anchor", "stranded"},
}


def check_one(path, base_sha, anchor_text, scope="whole", phase="migrate"):
    """Structural verification of one file, plus a lossless check when a base is given.

    The lossless check passes trivially after `--mode insert`, which is exactly why the
    structural ones exist: a mis-placed `end` marker loses nothing today and makes the
    next `update` delete the project-specialization section.
    """
    text = read(path)
    lines = text.split("\n")
    problems = []
    wanted = PHASES[phase]

    def add(tag, line):
        if tag in wanted:
            problems.append(line)

    if base_sha:
        # `git show <sha>:<path>` only understands a repo-relative path. A caller that passes
        # an absolute one would otherwise get `FAIL: cannot read` — safe (it blocks) but the
        # diagnostic names the wrong problem, and a human goes looking for a corrupt file.
        ok_show, before = git("show", f"{base_sha}:{rel_to_repo(path)}")
        if not ok_show or not before:
            add("loss", f"FAIL: cannot read {path} at {base_sha}")
        else:
            def tail(s):
                """Lines from the end marker down, or None when there is no end marker."""
                ls = s.split("\n")
                at = [i for i, l in enumerate(ls) if l.strip() == END]
                return ls[at[0]:] if at else None

            def norm(ls):
                return [l.rstrip() for l in ls if l.strip()]

            b_tail = None
            gained = []
            if scope == "below-end":
                # Everything from the end marker down — the part `update` promises not to
                # touch. Comparing the WHOLE file after a marker-region replacement flags
                # every legitimately-retired central line as a loss, which is why step 4 used
                # to pass no `--base` at all and check nothing.
                #
                # ⚠ A missing end marker on EITHER side is "not comparable", not "nothing
                # lost". An earlier version emptied only the side that lacked it, and
                # `Counter([]) - Counter(anything)` is always empty — so a base with no
                # markers, whose local bullets were then deleted, reported `ok`.
                b_tail, t_tail = tail(before), tail(text)
                if b_tail is None or t_tail is None:
                    side = "base" if b_tail is None else "current file"
                    add("loss", f"FAIL: no end marker in the {side} — below-end comparison "
                                f"cannot run. If the current file is the one missing it, this "
                                f"run destroyed the marker: restore the whole file from the "
                                f"base commit, because there is no region left to restore.")
                    b_tail = t_tail = None
                # SYMMETRIC. step 4 promises "nothing below the end marker changed", and a
                # one-directional loss check cannot say that: a section ADDED below the marker
                # by a botched replacement passes, and the next run's rule 3b then skips the
                # file forever as a marker anomaly while step 4 reported success.
                lost = [] if b_tail is None else list(
                    (Counter(norm(b_tail)) - Counter(norm(t_tail))).elements())
                gained = [] if b_tail is None else list(
                    (Counter(norm(t_tail)) - Counter(norm(b_tail))).elements())
            else:
                lost = list((Counter(norm(before.split("\n")))
                             - Counter(norm(text.split("\n")))).elements())
            # MULTISET, not set membership. The design specifies `comm -23` over two sorted
            # lists, which is a multiset difference: deleting one of two identical lines is a
            # loss. Set membership cannot see that, and the shipped template shape repeats
            # `- (아직 없음 …)`, so the blind spot covered a line this feature itself ships.
            #
            # ⚠ STATED BLIND SPOTS, inherited deliberately from the design's `comm -23`
            # formulation (§10.2 pipes both sides through
            # `sed '/^[[:space:]]*$/d;s/[[:space:]]*$//'`):
            #   · blank lines are dropped, so losing a paragraph break is invisible;
            #   · trailing whitespace is stripped, so losing a markdown hard line-break
            #     (two trailing spaces) is invisible — a rendering change, not a text one.
            # Neither can be tightened without making the check fire on every migration:
            # insertion adds a blank line by construction. The structural checks are what
            # cover the damage that matters; this one covers whole lines.
            label = "lossless" if scope == "whole" else "nothing changed below the end marker"
            if lost:
                add("loss", f"FAIL: {len(lost)} line(s) lost, first: {lost[0][:60]}")
            elif gained:
                add("loss", f"FAIL: {len(gained)} line(s) appeared below the end marker, "
                            f"first: {gained[0][:60]}")
            elif b_tail is not None or scope == "whole":
                # Silent when the comparison could not run — an `ok:` beside the FAIL that
                # says it could not run is a contradiction, and the reader believes the ok.
                add("loss", f"ok: {label}")

    for marker, name in ((START, "start"), (END, "end"), (HABITS, "habits")):
        n = sum(1 for l in lines if l.strip() == marker)
        if n != 1:
            add("count-habits" if name == "habits" else "count-pair",
                f"FAIL: {name} marker appears {n} time(s), expected 1")
    positions = {}
    for marker, name in ((START, "start"), (END, "end"), (HABITS, "habits")):
        at = [i for i, l in enumerate(lines, 1) if l.strip() == marker]
        if len(at) == 1:
            positions[name] = at[0]
    if len(positions) == 3:
        if positions["start"] < positions["end"] < positions["habits"]:
            add("order", "ok: markers in order")
        else:
            add("order", f"FAIL: marker order {positions}")

    # The first `## ` below the end marker must be the anchor. This is the check that
    # catches a mis-placed end marker, and the only one that does.
    if "end" in positions:
        tail = lines[positions["end"]:]
        below = [l for l in tail if l.startswith("## ")]
        # "Directly below" has to mean it, not "somewhere below". Anything non-blank between
        # the end marker and that heading is central prose that fell OUT of the region: it
        # stops being refreshed, and the next update writes the template's own copy of it
        # above — two copies, diverging. An `## `-only test cannot see that, because no
        # heading was crossed.
        stray = [l for l in tail[:tail.index(below[0])] if l.strip()] if below else []
        if below and below[0].startswith(anchor_text) and not stray:
            add("anchor", "ok: anchor directly below end marker")
            add("stranded", "ok: nothing stranded between end marker and anchor")
        elif below and below[0].startswith(anchor_text):
            add("stranded", f"FAIL: {len(stray)} line(s) stranded between end marker and "
                            f"anchor, first: {stray[0][:50]}")
        else:
            add("anchor", f"FAIL: first heading below end is {below[0][:40] if below else '(none)'}, expected {anchor_text}")

    # The anchor and the H1 each exactly once, H1 above. This is the symmetric guard from
    # insertion, re-asserted after the fact: both ends of the central region must stay
    # unambiguous, or a later run has two candidate boundaries and no way to choose.
    #
    # ⚠ NOT a count of `## ` headings below the end marker. A migrated T2 persona carries a
    # local section that was moved down out of the central region, so it has THREE headings
    # there (specialization, the moved section, habits) where a freshly-rendered file has two.
    # Counting would hard-fail every such file forever — and it would not even buy anything:
    # an end marker placed one heading too low leaves exactly two behind and passes. Identity
    # is what catches that, which is the check directly above.
    anchors = [i for i, l in enumerate(lines, 1) if l.startswith(anchor_text)]
    h1s_all = [i for i, l in enumerate(lines, 1) if l.startswith("# ")]
    if len(anchors) == 1 and len(h1s_all) == 1 and h1s_all[0] < anchors[0]:
        add("unique", "ok: anchor and H1 each once, in order")
    else:
        add("unique", f"FAIL: anchor x{len(anchors)}, h1 x{len(h1s_all)}"
                        + ("" if not (anchors and h1s_all) or h1s_all[0] < anchors[0]
                           else ", h1 below anchor"))

    # The start marker must sit below the closing frontmatter fence and the H1. Otherwise
    # `update` replaces the YAML frontmatter with body text and the sub-agent stops
    # registering at all.
    if "start" in positions:
        fences = [i for i, l in enumerate(lines, 1) if l.rstrip() == "---"]
        h1s = [i for i, l in enumerate(lines, 1) if l.startswith("# ")]
        if len(fences) >= 2 and h1s and positions["start"] > fences[1] and positions["start"] > h1s[0]:
            add("start", "ok: start below frontmatter and H1")
        else:
            add("start", f"FAIL: start at {positions['start']}, fence2={fences[1] if len(fences) > 1 else '-'}, h1={h1s[0] if h1s else '-'}")

    # ⚠ NO HEADING-SET COMPARISON HERE. It belongs to `classify`, which routes a role to a
    # human, and never to `check`, which decides whether to roll a write back. The design
    # settles this and names the case: `product-owner`'s template heading was renamed
    # centrally (`## 책임 (참여 스테이지)` → `… — 조건부`) while both measured repos still
    # carry the old one. As a verification it therefore FAILs on a correct file, and the
    # prescribed response to a FAIL is `git checkout -- <f>` — so the role could never
    # complete migration, and every later update would skip it. The mismatch is transient
    # by construction: the replacement itself is what makes the heading match.
    return problems


def check(paths, base_sha, anchor_text, scope="whole", phase="migrate"):
    """Run check_one over every path. One `<file>: <result>` line per check, and a single
    exit code for the batch — a caller that verifies 16 files wants one answer, not 16."""
    bad = False
    for path in paths:
        if not os.path.exists(path):
            print(f"{path}: FAIL: no such file")
            bad = True
            continue
        for line in check_one(path, base_sha, anchor_text, scope, phase):
            print(f"{path}: {line}")
            bad = bad or line.startswith("FAIL")
    sys.exit(PROBLEM if bad else 0)


class Parser(argparse.ArgumentParser):
    """argparse exits 2 on a bad flag, and 2 is this script's "guard failed" — the exact
    collision the distinct 64 was introduced to prevent. A typo in a flag name would send a
    human looking for a malformed persona that is fine."""

    def error(self, message):
        die(f"usage: {message}")


def main():
    p = Parser(add_help=True)
    p.add_argument("--mode", required=True, choices=("classify", "insert", "check"))
    p.add_argument("--init", help="the repo's init commit SHA — required by classify; on "
                                  "insert it turns T1/T2 routing into a guard")
    p.add_argument("--agents", default=".claude/agents", help="persona directory (classify)")
    p.add_argument("--file", nargs="+", help="persona file(s) — one for insert, any number for check")
    p.add_argument("--base", help="commit to compare against — optional, adds a lossless check")
    p.add_argument("--anchor", default=ANCHOR_KO,
                   help="heading that closes the central region — pass the localized one in a non-ko repo")
    p.add_argument("--localized", action="store_true",
                   help="this repo's personas were rendered in a language other than ko. Skips "
                        "the heading comparison, which would otherwise compare translated "
                        "headings against the template's Korean ones and call every role T2")
    p.add_argument("--habits-placeholder", default=HABITS_PLACEHOLDER_KO,
                   help="the '(none yet)' bullet under the habits marker, in this repo's language")
    p.add_argument("--habits-heading", default=HABITS_HEADING_KO,
                   help="heading for the local habits section insert appends (non-ko repos)")
    p.add_argument("--phase", choices=tuple(PHASES), default="migrate",
                   help="which checks this caller needs — see the PHASES table in this file. "
                        "post-write reports only what the replacement itself can break, so a "
                        "FAIL there is safe to roll back and a FAIL elsewhere is not")
    p.add_argument("--scope", choices=("whole", "below-end"), default="whole",
                   help="what the --base comparison covers: the whole file (migration, which "
                        "is insert-only) or only from the end marker down (update step 4, "
                        "where central lines are legitimately replaced)")
    p.add_argument("--templates",
                   help="central template dir. Used by classify (and by insert's --init guard) "
                        "to spot a heading inside the region that the template lacks — the only "
                        "detector of local content that predates the init commit. ⚠ Never used "
                        "by check: as a verification it fails on a correctly-migrated role whose "
                        "central heading was renamed since, and the response to a check failure "
                        "is a rollback")
    a = p.parse_args()

    if a.mode == "classify":
        if not a.init:
            die("--mode classify needs --init <sha>")
        if not a.templates:
            die("--mode classify needs --templates <dir> — the foreign-heading guard is the "
                "only mechanical detector of local content that predates the init commit, and "
                "without it a file that would lose that content classifies as T1")
        ok, sha = git("rev-parse", "--verify", f"{a.init}^{{commit}}")
        if not ok:
            die(f"--init is not a commit in this repo: {a.init}")
        templates_ok(a.templates)
        classify(sha.strip(), a.agents, a.anchor, a.templates, a.localized)
    elif a.mode == "insert":
        if not a.file:
            die("--mode insert needs --file <path>")
        if len(a.file) != 1:
            die("--mode insert takes exactly one --file")
        if not os.path.exists(a.file[0]):
            # Redundant with read()'s own 64, deliberately: this one names the actual problem
            # ("no such file") instead of surfacing an OSError string.
            die(f"no such file: {a.file[0]}")
        init_sha = None
        if not a.templates:
            die("--mode insert needs --templates <dir>. It is not only the T1 guard: the Scope "
                "check — refusing a role with no central template — runs on BOTH paths, because "
                "wrapping a local-only persona in a central region tells the next update to "
                "overwrite local prose. Dropping the flag turns that guard off silently.")
        templates_ok(a.templates)
        if a.init:
            ok, sha = git("rev-parse", "--verify", f"{a.init}^{{commit}}")
            if not ok:
                die(f"--init is not a commit in this repo: {a.init}")
            init_sha = sha.strip()
        insert(a.file[0], a.anchor, a.habits_heading, init_sha, a.templates,
               a.localized, a.habits_placeholder)
    else:
        if not a.file:
            die("--mode check needs --file <path> [<path>...]")
        check(a.file, a.base, a.anchor, a.scope, a.phase)


if __name__ == "__main__":
    main()
