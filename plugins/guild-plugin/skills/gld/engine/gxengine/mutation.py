"""Mutation evidence: the engine runs what a role declared (VB9, coordinator decision on #1938) — owner: branch B.

Why: an acceptance criterion like "with the flag removed the test fails" is proven by RUNNING the tests on
the changed code. Until stage 4 no fact of such a run reached the done-gate. A role may not report it as a
claim (§7.2: the engine judges by what it saw itself), so the role only DECLARES the mutations — data, never
a command — and the engine runs them.

  1. A developer step writes and commits docs/specs/<N>/mutations.json (schemas/mutations): which AC, which
     tracked production file, the literal text to replace and its replacement. At most
     defaults.MUTATIONS_MAX. Optional: no file = nothing to prove = no cost.
  2. Right before the done-gate opens (driver, stage >= 4, once per HEAD) the engine calls `prove`: a fresh
     worktree of HEAD, `setup` when the repository has one, the named `test` command WITHOUT a mutation
     (control), then once per mutation, all under the run boundary (srt) and the heavy-run lock. Every row
     is a fact of mutation-record.
  3. `load` gives the record to the done-gate leader (leader-input done_gate.mutations) and to the PR body.

A row never turns a step green or red. The engine adds no stop: the leader judges the AC with the fact
(survived / refused / timed-out / not-run is no proof).

The control and a flaky test (VW2 E1, #1938 — one performance assertion turned a whole proof into not-run):
  * the control follows the base check's rule (K8-2): red on a clean tree → once more on the same tree;
    red twice → every row is not-run; red, then green → `control.flaky` (both runs are in the record). A tree
    left dirty is never run again.
  * after a flaky control a red mutation is NOT taken at its word — a test that just failed without any
    change may fail again under the mutation, which would look like a kill. Such a red counts only when
      - its log shows a failure line that neither control run showed (lines compared after the digits are
        blanked and colour codes removed, so times and counters never make a line "new"), and
      - the same mutated tree is red AGAIN (exit > 0) with such a line too.
    Anything else is not-run, its reason in log_tail. The engine knows no test framework, so "a line the
    control did not show" is the strictest mechanical sign it has that the red is not the flaky failure; it
    can only turn a red into no proof, never a green into one. The leader still checks in log_tail that the
    red is the criterion's test (done-gate.md). After a green control nothing changes: one run per mutation.
  * `supersede` (driver: a human's `resume --answer rerun`, stage 4) moves a record without any run fact
    (no killed / survived / timed-out row, at least one not-run) aside, so the next done-gate proves the same
    HEAD again. A record with a run fact is never replaced: running again until a red shows would be
    shopping for evidence. The leader cannot do it — two reds of the control in a row are no thing a role
    can repair, and an automatic retry would spend a full `test` on every return to the done-gate.

What the leader reads of a red run (VW3 E2, #1938 — the last 40 lines of a `--fail-fast` run were the clean-up
of the tests it closed; the one failing assertion was 70 lines above them): `log_tail` is the END of the log,
`log_excerpt` (`_excerpt`) the first failure block with the lines around it. The block is found mechanically,
knowing no framework:
  * a failure line = a line with a failure mark (FAIL_MARK: words like fail / error / exception / assert /
    expected / panic / traceback, a CamelCase …Error / …Exception / …Failure, `[E]`, `not ok`, ✗ ✕ ✘) that the
    GREEN control run did not print (lines compared as in the flaky check above: colour removed, digits
    blanked). A line the unchanged tests print too is no failure of the mutation. Without a readable green
    control every marked line counts.
  * failure lines at most EXCERPT_GAP lines apart are one block; the first block of two or more lines is THE
    first failure block (one marked line alone is often a test NAME with such a word in a progress line);
    no such block → the first failure line. After a flaky control the first such block with a line its RED
    run did not print either comes first (a block that run printed whole is its flaky failure again). No
    failure line at all → the first line the green control did not print. Nothing → only a header saying so.
  * why not "the first line the control did not print" alone: in VW3 616 of the 4010 lines were new that way —
    a progress line names whichever test is running, and that differs between two runs of the same tests.
  * the excerpt is EXCERPT_BEFORE lines before the block, the block, EXCERPT_AFTER lines after; each line cut
    at EXCERPT_LINE_MAX, the temporary tree's path written `<tree>`, the whole at most
    defaults.MUTATION_EXCERPT_MAX characters. A header line says which rule found it and where; what does not
    fit ends with the engine's truncation mark; the line numbers of the other failure lines close it.
It is a reading aid, never a verdict: no status depends on it.

Decisions (fail-closed): one temporary tree for the control and every mutation, put back to HEAD in between
(the file time stamps always move on, so a tool that compares time and size never reuses the other build);
a run that leaves anything but the mutated file changed is not-run; an exit by a signal is not-run; a
repository without any verification / test-code rule refuses every mutation (the engine cannot tell a test
from production code); a not-run row says why in log_tail (it is no file's output).
"""

import os
import re
import time

from . import codes, defaults, fsafe, gitops, globs, paths as pathsmod, schema, store
from . import runner         # every command runs through runner.run_named (the run boundary)


def declaration_path(issue):
    """docs/specs/<N>/mutations.json (worktree-relative)."""
    return pathsmod.specs_dir(issue) + "/" + defaults.MUTATIONS_NAME


class ProveRequest:
    """Everything `prove` needs (the driver builds it).

    engine_paths  paths.EnginePaths of the Issue (the record goes to engine_paths.mutation_record(head))
    ctx           gitops.GitContext of the Issue worktree
    config        RepoConfig read at the recorded base
    issue, head   Issue number, the HEAD sha the mutations apply to
    blob          blob sha of the declaration at head
    acs           the AC numbers of the committed analysis
    render_paths  run render paths (driver._run_paths shape)
    base_env, srt the engine environment, the srt executable
    prepare_tree  callable(path) — the worktree_prepare copies into a temporary tree
    heavy_lock    paths.heavy_run_lock (H22)"""

    FIELDS = ("engine_paths", "ctx", "config", "issue", "head", "blob", "acs", "render_paths", "base_env", "srt",
              "prepare_tree", "heavy_lock")

    def __init__(self, **fields):
        if set(fields) != set(self.FIELDS):
            raise TypeError(f"ProveRequest needs exactly {self.FIELDS}")
        for k, v in fields.items():
            setattr(self, k, v)


STEP = "mutation-proof"
TREE = "mutation-tree"
TMP = "mutation-tmp"
TEST_COMMAND = "test"
TAIL_BYTES = 8000
GUARDED = (codes.PathRuleKind.VERIFICATION.value, codes.PathRuleKind.TEST_CODE.value, codes.PathRuleKind.SAFETY_NET.value)
"""The path rules no mutation may touch: breaking a test would turn it red without proving anything."""

RERUN = ".rerun"                                 # label / log suffix of a second run (no command name has a dot)
SUPERSEDED = "superseded-{n}.json"
"""A record a human rerun moved aside (mutations/<head>/), kept as it was."""
SIGNATURE_MAX_BYTES = 64 * 1024 * 1024
"""A log larger than this is not compared (no proof): reading it whole would cost more than the run told."""

M = codes.MutationRefusal
ST = codes.MutationStatus
RUN_FACTS = (ST.KILLED.value, ST.SURVIVED.value, ST.TIMED_OUT.value)
"""Row statuses that are what a run showed — a record with one of them is never replaced (`supersede`)."""


class _NotRun(Exception):
    """The engine cannot run (the rest of) the mutations — the rows stay not-run."""


def _declared(request):
    """The parsed declaration, or None (bad-file: not a regular file, not the announced blob, not JSON, not the schema)."""
    got = gitops.blob(request.ctx, request.head, declaration_path(request.issue))
    if got is None or got[2] is None or not gitops.is_regular_mode(got[0]) or got[1] != request.blob:
        return None
    try:
        obj = store.loads_strict(got[2].decode("utf-8"), "mutations.json")
    except ValueError:
        return None
    if schema.surrogate_errors(obj):
        return None
    try:
        schema.validate(obj, "mutations")
    except schema.ValidationError:
        return None
    return obj["mutations"]


def _once(data, find):
    i = data.find(find)
    return i if i >= 0 and data.find(find, i + 1) < 0 else None


def _usable(request, cfg, entry):
    """(MutationRefusal value or None, mode, the mutated bytes, the HEAD bytes) of one declared mutation."""
    if not set(entry["acs"]) <= set(request.acs):
        return M.UNKNOWN_AC.value, None, None, None
    path = entry["path"]
    bad = (M.BAD_PATH.value, None, None, None)
    try:
        gitops._need_relpath(path)
        if globs.is_control_file(path, request.issue) or path.lower().startswith(_SPECS_ROOT):
            return bad
    except (ValueError, gitops.UnsafePath):      # a name the dialect / git cannot express, not a link found on disk
        return bad
    got = gitops.blob(request.ctx, request.head, path)
    if got is None or got[2] is None or not gitops.is_regular_mode(got[0]):
        return bad
    guarded = [g for kind in GUARDED for g in cfg.path_globs(kind)]
    if not guarded or globs.match_any(guarded, path, fold=True) is not None:
        return M.VERIFICATION_PATH.value, None, None, None       # without any rule the engine cannot tell a test from code
    find, replace = entry["find"].encode("utf-8"), entry["replace"].encode("utf-8")
    at = _once(got[2], find)
    if at is None:
        return M.NOT_UNIQUE.value, None, None, None
    if find == replace:
        return M.NO_CHANGE.value, None, None, None
    return None, got[0], got[2][:at] + replace + got[2][at + len(find):], got[2]


_SPECS_ROOT = defaults.SPECS_DIR.split("{issue}")[0].lower()


def _tail(path):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TAIL_BYTES))
            data = f.read()
    except OSError:
        return ""
    return "\n".join(data.decode("utf-8", "replace").splitlines()[-defaults.MUTATION_LOG_LINES:])


class _Proof:
    """One temporary tree of HEAD: setup, the control run, then one run per usable mutation."""

    def __init__(self, request, cfg, out_dir):
        self.r, self.cfg, self.out_dir = request, cfg, out_dir
        self.home = os.path.dirname(request.render_paths["engine_records"])
        self.tctx = self.tpaths = None
        self.mtime = int(time.time())
        self.green_log = None                    # the green control run's log (_control)
        self.baseline = None                     # (its _signature,) once read
        self.red = None                          # a flaky control: its red run's _signature

    def excerpt(self, res):
        """The log_excerpt of a run: "" for a green one (nothing failed), else _excerpt against the green control."""
        if res.green:
            return ""
        if self.baseline is None:
            self.baseline = (_signature(self.green_log) if self.green_log else None,)
        return _excerpt(res.log_file, self.baseline[0], tree=self.tctx.work_tree, red=self.red)

    def __enter__(self):
        r = self.r
        path = os.path.join(r.render_paths["run_tmp"], TREE)
        fsafe.make_dirs(r.render_paths["run_tmp"], root=self.home)
        fsafe.check_parents(path, root=self.home)
        if os.path.lexists(path):                # left by an engine that died here
            gitops.git(r.ctx, "worktree", "remove", "--force", "--force", path, check=False)
            if os.path.lexists(path):
                raise _NotRun("the old temporary tree could not be removed")
        gitops.git(r.ctx, "worktree", "prune")
        self.tctx = gitops.detached_worktree(r.ctx, path, r.head)
        try:
            if r.prepare_tree is not None:
                r.prepare_tree(self.tctx.work_tree)
            tmp = os.path.join(r.render_paths["run_tmp"], TMP)
            fsafe.make_dirs(tmp, root=self.home)
            self.tpaths = runner._with_dirs(runner._temp_paths(r.render_paths, self.tctx, r.ctx.work_tree, tmp), self.tctx)
        except BaseException:
            self._remove()
            raise
        return self

    def __exit__(self, *exc):
        self._remove()
        return False

    def _remove(self):
        try:
            gitops.remove_worktree(self.r.ctx, self.tctx.work_tree)
        except gitops.UnsafePath:
            raise
        except gitops.GitError:
            pass                                 # the next proof removes it; the rows stand

    def run(self, command, log, label):
        return runner._tree_command(self.cfg, self.cfg.raw, STEP, 1, self.r.issue, self.tpaths, command, self.out_dir,
                                    self.r.base_env, self.r.srt, log_name=log, srt_name=f"srt-{label}.json", label=label,
                                    heavy=self.r.heavy_lock)

    def dirty(self):
        """The changed / new paths of the tree against HEAD (a moved HEAD counts as everything)."""
        if gitops.head(self.tctx) != self.r.head:
            return None
        return sorted(gitops.tree_state(self.tctx)["dirty_files"])

    def write(self, path, mode, data):
        """Put bytes into the tree with a time stamp no earlier write had (a tool that compares time and size
        never reuses what it built from the other text)."""
        target = os.path.join(self.tctx.work_tree, path)
        fsafe.write_bytes(target, data, root=self.tctx.work_tree, mode=0o755 if mode == "100755" else 0o644)
        self.mtime = max(self.mtime + 2, int(time.time()))
        os.utime(target, (self.mtime, self.mtime), follow_symlinks=False)

    def restore(self, path, mode, data):
        """The tree back at HEAD; _NotRun when it is not."""
        if gitops.head(self.tctx) != self.r.head:
            raise _NotRun("a mutated run moved HEAD")
        gitops.git(self.tctx, "reset", "-q", "--hard", self.r.head)
        gitops.git(self.tctx, "clean", "-fdq")
        self.write(path, mode, data)
        if self.dirty() != []:
            raise _NotRun("the temporary tree could not be restored")


def _why(text):
    return f"\n[gld engine] not run: {text}"


def _facts(result, out_dir):
    """The run facts with the log file relative to the record's folder (try-<n>/…)."""
    return dict(result.to_facts(), log_file=os.path.basename(out_dir) + "/" + os.path.basename(result.log_file))


_COLOUR = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")
_DIGITS = re.compile(rb"[0-9]+")


def _signature(path):
    """The lines of a run log, colour codes removed, digit runs blanked, blank lines dropped (a set), or None
    when the log cannot be read whole (no comparison = no proof)."""
    try:
        if os.path.getsize(path) > SIGNATURE_MAX_BYTES:
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    out = set()
    for line in data.splitlines():
        line = _DIGITS.sub(b"#", _COLOUR.sub(b"", line)).strip()
        if line:
            out.add(line)
    return out


FAIL_MARK = re.compile(
    rb"(?i:\b(?:fail(?:s|ed|ure|ures|ing)?|errors?|exceptions?|assert\w*|expected|panic(?:s|ked)?|traceback|fatal)\b"
    rb"|\[E\]|\bnot ok\b)"
    rb"|[a-z](?:Error|Exception|Failure)\b"
    + "|\u2717|\u2715|\u2718".encode("utf-8"))
"""A failure mark (module doc) — words, not a framework: it only chooses where the excerpt starts."""
EXCERPT_GAP = 3
EXCERPT_BEFORE = 6
EXCERPT_AFTER = 20
EXCERPT_LINE_MAX = 300
EXCERPT_OTHERS_MAX = 300
TREE_NAME = "<tree>"
_HEAD = "[gld engine] "
R_BLOCK = "the first block of 2+ failure-mark lines the green control run did not print"
R_LINE = "the first failure-mark line the green control run did not print (no block of 2+ such lines)"
R_NEW = "no failure-mark line the green control did not print — the first line it did not print"
R_NONE = "no failure-mark line and no line the green control did not print — read log_tail"
NO_BASE = " (the green control log could not be compared: every failure-mark line counts)"
OTHERS = _HEAD + "other failure-mark lines: "
R_FRESH = " — after a flaky control: the first with a line its red run did not print either"
R_STALE = " (flaky control: the red control run printed every such block too — it may be its failure)"


def _norm(line):
    """A colour-free line as _signature compares it."""
    return _DIGITS.sub(b"#", line).strip()


def _blocks(idx, gap):
    """Sorted indexes grouped where neighbours are at most `gap` apart."""
    out = []
    for i in idx:
        if out and i - out[-1][-1] <= gap:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def _ranges(idx):
    """1-based "3963-3970, 4001" of sorted 0-based indexes."""
    return ", ".join(f"{b[0] + 1}" if len(b) == 1 else f"{b[0] + 1}-{b[-1] + 1}" for b in _blocks(idx, 1))


def _excerpt(path, baseline, tree=None, red=None):
    """The `log_excerpt` of a red run's log (module doc). `baseline`: _signature of the green control log, or
    None. `red`: after a flaky control, _signature of its RED run — a block all of whose lines that run printed
    too is its flaky failure again, so the first block with a line it did not print comes first. `tree`: the
    temporary tree, written TREE_NAME in what is shown (not in what is compared: the control ran in the same
    tree). Never raises for the log: an unreadable one gives ""."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            data = f.read(SIGNATURE_MAX_BYTES)
    except OSError:
        return ""
    lines = [_COLOUR.sub(b"", line) for line in data.splitlines()]
    known = (lambda line: _norm(line) in baseline) if baseline is not None else (lambda line: False)
    hits = [i for i, line in enumerate(lines) if FAIL_MARK.search(line) and not known(line)]
    if hits:
        blocks = _blocks(hits, EXCERPT_GAP)
        two = [b for b in blocks if len(b) >= 2]
        rule = R_BLOCK if two else R_LINE
        pool = two or blocks
        first = pool[0]
        if red is not None:
            fresh = [b for b in pool if any(_norm(lines[i]) not in red for i in b)]
            first = (fresh or pool)[0]
            rule += R_FRESH if fresh else R_STALE
        rule += NO_BASE if baseline is None else ""
    else:
        new = [i for i, line in enumerate(lines) if _norm(line) and not known(line)] if baseline is not None else []
        first, rule = new[:1], R_NEW
    name = os.path.basename(path)
    total = f"{len(lines)}" + (f" (only the first {SIGNATURE_MAX_BYTES} bytes read)" if size > SIGNATURE_MAX_BYTES else "")
    if not first:
        return f"{_HEAD}{name}, {total} lines: {R_NONE}" + (NO_BASE if baseline is None else "")
    lo, hi = max(0, first[0] - EXCERPT_BEFORE), min(len(lines), first[-1] + 1 + EXCERPT_AFTER)
    # the closing line names the failure lines NOT shown; room for it is kept first (what may stay unshown is
    # at most every hit outside [lo, first line of the block])
    could = [i for i in hits if not lo <= i <= first[0]]
    reserve = min(EXCERPT_OTHERS_MAX, len(OTHERS) + len(_ranges(could))) + 1 if could else 0
    budget = defaults.MUTATION_EXCERPT_MAX - reserve
    head = f"{_HEAD}{name}, lines {lo + 1}-{hi} of {total}: {rule}"
    trees = sorted({os.fsencode(t.rstrip("/")) for t in (tree, tree and os.path.realpath(tree)) if t}, key=len,
                   reverse=True)
    out, used, shown = [head], len(head), lo
    for i in range(lo, hi):
        raw = lines[i]
        for t in trees:
            raw = raw.replace(t, TREE_NAME.encode())
        text = raw.decode("utf-8", "replace").rstrip()
        text = f"{i + 1}| " + (text[:EXCERPT_LINE_MAX] + "…" if len(text) > EXCERPT_LINE_MAX else text)
        mark = f"{defaults.LEADER_INPUT_TRUNCATION_MARK} lines {i + 1}-{hi} not shown"
        if used + 1 + len(text) + 1 + len(mark) > budget:
            out.append(mark)
            break
        out.append(text)
        used += 1 + len(text)
        shown = i + 1
    unshown = [i for i in hits if not lo <= i < shown]
    if unshown and reserve:
        out.append((OTHERS + _ranges(unshown))[:reserve - 1])
    return "\n".join(out)


def _new_failure(log, control_sigs):
    """True when the log has a line no control run showed (see the module doc). Unreadable = False."""
    if any(s is None for s in control_sigs):
        return False
    sig = _signature(log)
    return sig is not None and not sig <= set().union(*control_sigs)


def _left(p, row):
    """None when the tree is HEAD + the mutation only, else the not-run reason."""
    left = p.dirty()
    if left == [row["path"]]:
        return None
    return "the run left other changes in the tree: " + ", ".join(left[:10] if left is not None else ["HEAD moved"])


def _status(res):
    """The row status a run alone shows (not-run for an exit by a signal)."""
    if res.timed_out:
        return ST.TIMED_OUT.value
    if res.exit_code == 0:
        return ST.SURVIVED.value
    if res.exit_code is not None and res.exit_code > 0:
        return ST.KILLED.value
    return ST.NOT_RUN.value


SAME_RED = "the red shows no failure line that the flaky control runs did not show — it may be their failure"


def _after_flaky_control(p, row, first, control_sigs, out_dir):
    """A red mutation run after a flaky control → (status, not-run reason or None). Runs the mutated tree once
    more; KILLED only when both reds show a failure line no control run showed (module doc)."""
    if not _new_failure(first.log_file, control_sigs):
        return ST.NOT_RUN.value, SAME_RED
    rid = row["id"].lower()
    again = p.run(TEST_COMMAND, f"{rid}{RERUN}.log", rid + RERUN)
    row["again"] = _facts(again, out_dir)
    row["log_tail"] = _tail(again.log_file)
    row["log_excerpt"] = p.excerpt(again)       # the same run as log_tail
    why = _left(p, row)
    if why is not None:
        return ST.NOT_RUN.value, why
    status = _status(again)
    if status == ST.SURVIVED.value:
        return ST.NOT_RUN.value, "red, then green with the same mutation after a flaky control — the red proves nothing"
    if status == ST.KILLED.value and not _new_failure(again.log_file, control_sigs):
        return ST.NOT_RUN.value, "second run: " + SAME_RED
    return status, None


def _control(p, rec, out_dir):
    """The control run(s) (K8-2: red on a clean tree → once more) → the signatures of the control logs when it
    was flaky (red, then green), [] when green the first time. _NotRun otherwise."""
    first = p.run(TEST_COMMAND, "control.log", "control")
    rec["control"] = dict(_facts(first, out_dir), again=None, flaky=False)
    clean = p.dirty() == []
    if first.green and clean:
        p.green_log = first.log_file
        return []
    if not clean:
        raise _NotRun("the control run left the tree changed — not run again")
    again = p.run(TEST_COMMAND, f"control{RERUN}.log", "control" + RERUN)
    rec["control"]["again"] = _facts(again, out_dir)
    if not again.green or p.dirty() != []:
        raise _NotRun("the control run was not green on a clean tree, twice")
    rec["control"]["flaky"] = True
    sigs = [_signature(first.log_file), _signature(again.log_file)]
    p.green_log, p.baseline, p.red = again.log_file, (sigs[1],), sigs[0]
    return sigs


def _run_rows(request, cfg, rows, usable, rec, out_dir):
    """Fill control and the rows of `usable` ({row index: (mode, mutated, original)})."""
    names = cfg.command_names()
    if TEST_COMMAND not in names or not cfg.command(TEST_COMMAND)["cmd"]:
        raise _NotRun("no `test` command")
    with _Proof(request, cfg, out_dir) as p:
        if runner.SETUP_COMMAND in names and cfg.command(runner.SETUP_COMMAND)["cmd"]:
            if not p.run(runner.SETUP_COMMAND, "setup.log", "setup").green:
                raise _NotRun("setup was red on the temporary tree")
        control_sigs = _control(p, rec, out_dir)
        for i in sorted(usable):
            mode, mutated, original = usable[i]
            row, log = rows[i], f"{rows[i]['id'].lower()}.log"
            p.write(row["path"], mode, mutated)
            if p.dirty() != [row["path"]]:
                raise _NotRun("the mutated file is not the only change")
            res = p.run(TEST_COMMAND, log, rows[i]["id"].lower())
            row["run"] = _facts(res, out_dir)
            row["log_tail"] = _tail(res.log_file)
            row["log_excerpt"] = p.excerpt(res)
            why = _left(p, row)                 # not-run: what it judged is not HEAD + the mutation any more
            status = ST.NOT_RUN.value if why is not None else _status(res)
            if status == ST.KILLED.value and control_sigs:
                status, why = _after_flaky_control(p, row, res, control_sigs, out_dir)
            elif status == ST.NOT_RUN.value and why is None:
                why = "the run ended without an exit code (a signal)"
            row["status"] = status
            if why is not None:
                row["log_tail"] += _why(why)
            p.restore(row["path"], mode, original)


def prove(request):
    """Run the declared mutations (the control twice when red, a red mutation twice after a flaky control — module
    doc) and write the mutation-record; return it (the dict).

    Never a pass by default: a declaration that cannot be read → problem bad-file, no row; a row that cannot
    be used → refused + detail; a tree / control / setup problem → not-run. Raises gitops.UnsafePath /
    fsafe.UnsafePath (→ unsafe-path stop) and nothing else on purpose."""
    ep = request.engine_paths
    cfg = request.config
    rec = {"format": 1, "issue": request.issue, "head": request.head, "blob": request.blob, "problem": None, "control": None,
           "rows": []}
    entries = _declared(request)
    if entries is None:
        rec["problem"] = M.BAD_FILE.value
    usable = {}
    for i, e in enumerate(entries or ()):
        detail, mode, mutated, original = _usable(request, cfg, e)
        rec["rows"].append({"id": f"M{i + 1}", "acs": list(e["acs"]), "path": e["path"], "find": e["find"],
                            "replace": e["replace"], "note": e["note"],
                            "status": ST.REFUSED.value if detail else ST.NOT_RUN.value, "detail": detail, "run": None,
                            "again": None, "log_tail": "", "log_excerpt": ""})
        if detail is None:
            usable[i] = (mode, mutated, original)
    if usable:
        base = ep.mutations_dir(request.head)
        root = os.path.dirname(request.render_paths["engine_records"])
        try:
            n = 1                                # an engine that died left its logs: never reuse a folder
            while os.path.lexists(os.path.join(base, f"try-{n}")):
                n += 1
            out_dir = os.path.join(base, f"try-{n}")
            fsafe.make_dirs(out_dir, root=root)
            _run_rows(request, cfg, rec["rows"], usable, rec, out_dir)
        except (gitops.UnsafePath, fsafe.UnsafePath):
            raise
        except (_NotRun, runner.RunnerError, gitops.GitError, OSError) as e:
            for i in usable:
                if rec["rows"][i]["run"] is None:
                    rec["rows"][i]["log_tail"] = _why(str(e)[:500]).lstrip("\n")
    rec["at"] = store.now_ts()
    store.write_record(ep, ep.mutation_record(request.head), rec, "mutation-record")
    return rec


def load(engine_paths, head):
    """The mutation-record of `head`, or None (nothing was declared there, or it has not been run)."""
    return store.read_record(engine_paths, engine_paths.mutation_record(head), "mutation-record")


def retryable(rec):
    """True for a record a human rerun may replace: at least one not-run row and no row a run decided
    (killed / survived / timed-out). Refused rows alone are the declaration's problem (a new HEAD fixes it)."""
    rows = rec.get("rows") or ()
    return (any(r["status"] == ST.NOT_RUN.value for r in rows)
            and not any(r["status"] in RUN_FACTS for r in rows))


def supersede(engine_paths, head):
    """A human `rerun` (driver, stage 4): move the retryable record of `head` to superseded-<n>.json in its folder
    (kept as it was; the next proof writes try-<n+1>/) → that file name, or None when there is no record or it
    holds a run fact. CorruptFile / FormatMismatch of an unreadable record propagate (the engine stops)."""
    rec = load(engine_paths, head)
    if rec is None or not retryable(rec):
        return None
    folder = engine_paths.mutations_dir(head)
    root = store._root(engine_paths)
    n = 1
    while os.path.lexists(os.path.join(folder, SUPERSEDED.format(n=n))):
        n += 1
    name = SUPERSEDED.format(n=n)
    fsafe.check_parents(os.path.join(folder, name), root=root)
    os.rename(engine_paths.mutation_record(head), os.path.join(folder, name))
    return name
