"""init: make the engine settings with the human (stage-4 scope §2.9 S4-init, A10, VB3).

A command text is taken from a file of the repository or written by a human (codes.CommandSource) — never
made up by the engine or an LLM (§7.10). The drafts are made by tools/convert_config.py (`--init`), run as a
`python3 -I` child and read as JSON (a tool is outside the package). Everything before `write` lives under
paths.init_dir — `write` is the only action that touches the checkout, and it never overwrites.

  doctor   the pre-checks                                   propose  draft.json + report.md + the questions
  answer   one human answer → decisions.json, new draft     check    base check, then the canaries → check.json
  write    .claude/guild/ of the checkout

What the LLM command does: shows a question and passes the human's words on. An answer is checked against the
question as the draft (or the last check) asked it; a choice is named by its id, so an answer holds a command
text only where a human writes one (test-command, quarantine). Questions with `required` must be settled
before `check`; `fix-repository` never settles one. The same commit and answers give the same settings text,
so `write` takes exactly the text `check` passed (sha256).

After a red base check (interpretation, fail-closed): the engine MEASURES which sandbox exceptions would turn
the red commands green — all candidates together, then each one dropped when nothing is lost — and asks for
those only (`sandbox-exception`, item = the candidate). Every red command is also asked as `quarantine` (item
`<command>`; the answer's item is `<command>:<test file>` and its text the command a human rewrote to leave that
test out) and as `not-local` (item = the command). Nothing is added by itself.

What a human judged and no file shows (A15, 2026-11-26 — VW1's loosened lines): `risk-add` adds a risk /
irreversible rule line (decisions `stage3.review.include`, the note is its reason; the draft tool refuses a glob that
matches no tracked file); `narrow-glob` narrows a test-code / safety-net candidate (`review.exclude` of the candidate +
`include` of the narrower globs) and takes only globs globs.covers PROVES narrower — wider, unproved, the same set:
refused; `followups-dry-run` sets `followups_dry_run`. Q11 (user decision 2026-11-28): every recommended follow-up is
filed, so that question is optional and never asked — no answer = really create (defaults.FOLLOWUPS_DRY_RUN_DEFAULT);
`dry-run` is recorded only when a human asks for it (a validation repository).
"""

import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

from . import basecheck, canaryrun, codes, defaults, fsafe, gitops, globs, instructions, paths as pathsmod, repoconfig, session, store

ACTIONS = ("doctor", "propose", "answer", "check", "write")
EXIT_OK = 0
EXIT_REFUSED = 4

DRAFT, DECISIONS, CHECK, REPORT = "draft.json", "decisions.json", "check.json", "report.md"
MIGRATED = "migrated.json"
"""Readiness T2 (parity P4): the record `init migrate --apply` leaves when it moved a 0.98.x install of this channel's
settings folder (initharness). With it, the 0.98.x config.json counts as "no engine settings yet" and `write` replaces
it (after one more copy into the migration's backup folder)."""
LEGACY_KEYS = ("version", "language", "roles", "commands", "visual", "gates", "sprint", "automation")


def legacy_settings(text):
    """Is `text` a 0.98.x Guild config.json (a JSON object without `format` that has a 0.98.x key)? True / False; None
    when it is no JSON object at all."""
    try:
        d = json.loads(text)
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    return "format" not in d and any(k in d for k in LEGACY_KEYS)
CONVERT_TIMEOUT_S = 600
FIX = "fix-repository"
NOT_LOCAL_ANSWER = "not-checked-locally"
APPROVE, REJECT, KEEP, DROP, NONE = "approve", "reject", "keep", "drop", "none"
EXCEPTIONS = {"local-binding": {"allow_local_binding": True}, "weaker-network": {"weaker_network_isolation": True},
              "user-tmp": {"allow_write": [defaults.USER_TMP_TOKEN]}}
"""The sandbox exceptions init may propose (§7.10: measured, then approved by a human)."""
WHAT_IF_NOTE = "measurement only (init check) — not approved"
ADD, WITHDRAW, DRY_RUN, CREATE = "add", "withdraw", "dry-run", "create"
RISK_ADD_LABELS = {codes.PathRuleKind.RISK.value: ("security", "data-migration"),
                   codes.PathRuleKind.IRREVERSIBLE.value: tuple(codes.IrreversibleCategory.values())}
"""risk-add (A15): the kinds and the area / category of each — the draft tool's own (convert_config.RISK_AREAS)."""
NARROWABLE = codes.TEMPLATE_PATH_KINDS
"""narrow-glob (A15): the kinds where a narrower glob protects more, never less — test-code ({path:test-code}: what
the reproduce step may write, repro-scope) and safety-net (net-scope, no-production-change). A verification, risk or
irreversible glob guards by covering: narrowing one loosens it, so they are never narrowed."""

Q = codes.InitQuestion


class Refused(Exception):
    """The action is refused; nothing was written."""


class Units:
    """The outside of init — tests replace them."""

    def __init__(self, **over):
        self.convert = convert
        self.base_check = basecheck.check
        self.measure = basecheck.measure
        self.role_canary = canaryrun.ensure_role_canary
        self.srt_canary = canaryrun.ensure_srt_canary
        self.cli_version = session.cli_version
        for k, v in over.items():
            if not hasattr(self, k):
                raise TypeError(f"no unit {k!r}")
            setattr(self, k, v)


def convert(checkout, sha, decisions, environ):
    """The draft of a commit (tools/convert_config.py --init as a child). Refused with the tool's own message."""
    engine = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    argv = [sys.executable, "-I", "-B", os.path.join(engine, "tools", "convert_config.py"), "--repo-root", checkout,
            "--rev", sha, "--init"]
    with tempfile.TemporaryDirectory(prefix="gx-init-") as folder:
        if decisions is not None:
            path = os.path.join(folder, DECISIONS)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(decisions, f, ensure_ascii=False)
            argv += ["--decisions", path]
        try:
            p = subprocess.run(argv, env=dict(environ), stdin=subprocess.DEVNULL, capture_output=True, timeout=CONVERT_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise Refused(f"the draft tool could not be run: {e}") from e
    if p.returncode != 0:
        raise Refused((p.stderr.decode("utf-8", "replace").strip().splitlines() or ["the draft tool failed"])[-1])
    try:
        return json.loads(p.stdout.decode("utf-8"))
    except ValueError as e:
        raise Refused(f"the draft tool gave no JSON: {e}") from e


# --- the pure parts -------------------------------------------------------------------------------

def _digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


_ORIGIN = re.compile(r"^(?:(?:ssh|https?|git)://)?(?:[^@/\s]+@)?([^:/\s]+)(?::\d+)?[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$")


def origin_repo(url):
    """`owner/name` of a GitHub origin URL, or None. The host is GitHub's, a `github…` SSH alias, or a bare SSH host
    alias without a dot (`git@personal:owner/name.git` — its real host is in the user's SSH config, which init does
    not read); any other host (a dotted name that is not GitHub's) is not GitHub."""
    m = _ORIGIN.match(url or "")
    if not m:
        return None
    host = m.group(1).lower()
    return m.group(2) if "github" in host or "." not in host else None


def find_question(questions, question, item):
    """The question an answer is about, or None. A quarantine answer's item is `<command>:<test file>`; a risk-add
    answer's item is the line `<kind>:<area|category>:<glob>` (the question itself has none)."""
    for q in questions:
        if q["question"] != question:
            continue
        if question == Q.QUARANTINE.value:
            if item and ":" in item and item.split(":", 1)[0] == q["item"]:
                return q
        elif question == Q.RISK_ADD.value:
            if q["item"] is None and item and item.count(":") >= 2:
                return q
        elif q["item"] == item:
            return q
    return None


def _glob_problem(g):
    """Why `g` is no glob of a path rule, or None."""
    if any(c.isspace() for c in g) or "{" in g or "}" in g:
        return f"`{g}` is no glob (no spaces, no braces)"
    try:
        globs._compile(g)
    except ValueError as e:
        return f"`{g}`: {e}"
    return None


def narrowed(candidate, answer):
    """The globs a narrow-glob answer names (`keep` → None: unchanged, `drop` → []), or the reason it is refused.
    → (globs | None, problem | None). Each glob must be PROVED narrower than the candidate (globs.covers) — a wider
    one, one the engine cannot prove, the same set, or one that shares no path with the candidate is refused."""
    if answer == KEEP:
        return None, None
    if answer == DROP:
        return [], None
    out = answer.split()
    if len(set(out)) != len(out):
        return None, "a glob is named twice"
    for g in out:
        problem = _glob_problem(g)
        if problem:
            return None, problem
        inside, around = globs.covers(candidate, g) is True, g == candidate or globs.covers(g, candidate) is True
        if inside and around:
            return None, f"`{g}` is not narrower than `{candidate}` (the same paths) — answer `keep`"
        if around:
            return None, f"`{g}` is wider than `{candidate}` — a glob may only be narrowed"
        if not inside:
            if not globs.may_overlap(candidate, g):
                return None, f"`{g}` shares no path with `{candidate}` — that is no narrowing of it"
            return None, (f"the engine cannot prove that `{g}` is narrower than `{candidate}` (every path it matches must "
                          "match the candidate) — write it so that it is, or answer `keep`")
    return out, None


def answer_problem(q, item, answer, questions=()):
    """Why `answer` is no answer to the question, or None (TI7). `questions` = every question asked now."""
    if not isinstance(answer, str) or not answer.strip():
        return "an empty answer"
    if any(ord(c) < 32 or ord(c) == 127 for c in answer):
        return "an answer is one line without control characters"
    if q["question"] == Q.RISK_ADD.value:
        kind, label, glob = item.split(":", 2)
        if kind not in RISK_ADD_LABELS:
            return f"the item is `<{'|'.join(RISK_ADD_LABELS)}>:<area or category>:<glob>`, got kind {kind!r}"
        if label not in RISK_ADD_LABELS[kind]:
            return f"the {kind} lines are {', '.join(RISK_ADD_LABELS[kind])}, got {label!r}"
        problem = _glob_problem(glob)
        if problem:
            return problem
        if answer == ADD and find_question(questions, Q.RISK_RULES.value, item):
            return f"`{glob}` is a {kind} candidate already — answer risk-rules {item} keep"
    elif q["question"] == Q.NARROW_GLOB.value:
        return narrowed(item.split(":", 1)[1], answer)[1]
    if q["question"] == Q.QUARANTINE.value:
        test = item.split(":", 1)[1]
        if answer == FIX:
            return None
        if not test or test.startswith("/") or any(s in ("", ".", "..") for s in test.split("/")):
            return f"the item must be `<command>:<test file>`, got {item!r}"
        return None if test in answer else f"the command must name the test it leaves out ({test})"
    if q["choices"] is None:
        return None
    return None if answer in q["choices"] else f"choose one of {', '.join(q['choices'])}"


def settled(q, answers):
    """True when the human answered this question in a way that lets init go on."""
    return any(a["question"] == q["question"] and a["answer"] != FIX and find_question([q], a["question"], a["item"])
               for a in answers)


def open_questions(questions, answers):
    return [q for q in questions if q["required"] and not settled(q, answers)]


def to_decisions(answers, draft, today):
    """The decisions object of convert_config.load_decisions(init=True) from the recorded answers."""
    d, review, s3 = {"note": "init answers"}, {"exclude": [], "kept": [], "include": []}, {}
    exc = {}
    by = sorted(answers, key=lambda a: a["question"] == Q.QUARANTINE.value)      # a quarantine text wins over a conflict choice
    toolchain = {q["item"]: q["choices"] for q in draft["questions"] if q["question"] == Q.TOOLCHAIN.value}
    for a in by:
        kind, item, answer, note = a["question"], a["item"], a["answer"], a["note"]
        if kind == Q.TEST_COMMAND.value:
            d.setdefault("add_commands", {})["test"] = {"cmd": answer, "why": note}
        elif kind == Q.COMMAND_CONFLICT.value:
            text = (draft["choices"].get(item) or {}).get(answer)
            if text is None:
                raise Refused(f"the recorded answer to command-conflict {item!r} names no candidate of this draft — answer it again")
            d.setdefault("commands", {})[item] = {"cmd": text, "why": note}
        elif kind == Q.NOT_LOCAL.value:
            if answer == NOT_LOCAL_ANSWER and item in draft["commands"]:
                d.setdefault("not_checked_locally", {})[item] = note
        elif kind == Q.SANDBOX_EXCEPTION.value:
            if answer == APPROVE:
                for k, v in EXCEPTIONS[item].items():
                    exc[k] = exc.get(k, []) + v if isinstance(v, list) else v
                exc["note"] = "; ".join(x for x in (exc.get("note"), f"{item}: {note}") if x)
        elif kind == Q.QUARANTINE.value:
            if answer != FIX:
                command, test = item.split(":", 1)
                d.setdefault("commands", {})[command] = {"cmd": answer, "why": f"quarantine of {test}: {note}"}
                d.setdefault("quarantine", []).append({"test": test, "note": note, "added": a["at"][:10] or today})
        elif kind == Q.RISK_RULES.value:
            rule, label, glob = item.split(":", 2)
            review["exclude" if answer == DROP else "kept"].append(
                {"kind": rule, "glob": glob, "why": note, "area" if rule == "risk" else "category": label})
        elif kind == Q.REGISTRY_HOST.value:
            if answer == APPROVE:
                d.setdefault("registry_hosts", {})[item] = note
        elif kind == Q.TOOLCHAIN.value:
            choice = (toolchain.get(item) or {}).get(answer)
            if choice is None:
                raise Refused(f"the recorded answer to toolchain {item!r} names no candidate of this draft — answer it again")
            d.setdefault("toolchain", {})[item] = {"from": None if answer == NONE else choice, "why": note}
        elif kind == Q.RISK_ADD.value:                # A15: the tool checks the glob matches a tracked file
            if answer == ADD:
                rule, label, glob = item.split(":", 2)
                review["include"].append({"kind": rule, "glob": glob, "why": note, "area" if rule == "risk" else "category": label})
        elif kind == Q.NARROW_GLOB.value:             # A15: the candidate leaves, the narrower globs come in
            rule, candidate = item.split(":", 1)
            got, problem = narrowed(candidate, answer)
            if problem:
                raise Refused(f"the recorded answer to narrow-glob {item!r} is refused now ({problem}) — answer it again")
            if got is None:                           # keep: the record that a human checked the line
                review["kept"].append({"kind": rule, "glob": candidate, "why": note})
            else:
                review["exclude"].append({"kind": rule, "glob": candidate, "why": f"narrowed by a human: {note}"})
                review["include"] += [{"kind": rule, "glob": g, "why": f"narrowed from {candidate}: {note}"} for g in got]
        elif kind == Q.FOLLOWUPS_DRY_RUN.value:
            if answer not in (DRY_RUN, CREATE):
                raise Refused(f"the recorded answer to followups-dry-run is {answer!r} — answer it again")
            s3.update(followups_dry_run=answer == DRY_RUN, note=f"followups-dry-run = {answer}: {note}")
    if exc:
        d["sandbox_exceptions"] = exc
    if review["exclude"] or review["kept"] or review["include"]:
        s3["review"] = dict(review, note="init answers, line by line")
    if s3:
        d["stage3"] = dict(s3, note=s3.get("note") or "init answers")
    return d


def _rules(config):
    """{(kind, area / category): (globs, the rule's other fields)} of the path rules."""
    out = {}
    for r in config.get("path_rules") or []:
        key = (r["kind"], r.get("area") or r.get("category") or "")
        globs_, extra = out.get(key, (set(), []))
        out[key] = (globs_ | set(r["globs"]), extra + [(r.get("gate"), r.get("level"))])
    return out


def _proved(outer, inner):
    """globs.covers proved it; a glob outside the engine's dialect proves nothing (compare reads any settings)."""
    try:
        return globs.covers(outer, inner) is True
    except ValueError:
        return False


STRICT_KINDS = ("verification", "risk", "irreversible")
LEVELS = defaults.IRREVERSIBLE_LEVEL_ORDER


def compare(committed, draft):
    """The differences of a draft to the committed settings → [{area, item, committed, draft, loosened}]. `loosened` =
    the draft checks or protects less there (§5.0: a missing check, a wider exception, a missing rule) — True, False,
    or None when the engine cannot say (a changed text): a human reads it. A test-code / safety-net glob (where narrower
    is stricter, A15): one only the draft has is loosened unless a committed glob of the rule covers it (globs.covers —
    VW1's `**/*_test.dart` for `test/**/*_test.dart`); one only the committed rule has is stricter, or None when a
    wider draft glob took its place."""
    rows = []

    def row(area, item, a, b, loosened):
        rows.append({"area": area, "item": item, "committed": a, "draft": b, "loosened": loosened})

    ca, cb = committed.get("commands", {}), draft.get("commands", {})
    for n in sorted(set(ca) | set(cb)):
        a, b = ca.get(n), cb.get(n)
        ta, tb = [x and (x.get("cmd") or "plugin " + x["plugin"]) for x in (a, b)]
        if ta != tb:
            row("commands", n, ta, tb, True if b is None else (False if a is None else None))
    ra, rb = _rules(committed), _rules(draft)
    for key in sorted(set(ra) | set(rb)):
        (ga, ea), (gb, eb) = ra.get(key, (set(), [])), rb.get(key, (set(), []))
        area = "path_rules " + "/".join(x for x in key if x)
        if key[0] in NARROWABLE:         # narrower protects more (A15): a glob the committed rule does not cover may widen
            wider = {g for g in gb - ga if not any(_proved(c, g) for c in ga)}
            for g in sorted(ga - gb):
                row(area, g, "rule", None, None if any(_proved(w, g) for w in wider) else False)
            for g in sorted(gb - ga):
                row(area, g, None, "rule", g in wider)
        else:
            for g in sorted(ga - gb):
                row(area, g, "rule", None, True if key[0] in STRICT_KINDS else None)
            for g in sorted(gb - ga):
                row(area, g, None, "rule", False if key[0] in STRICT_KINDS else None)
        if ga and gb and sorted(map(str, set(ea))) != sorted(map(str, set(eb))):
            row(area, "gate / level", sorted(map(str, set(ea))), sorted(map(str, set(eb))), None)
    for key, wider_is_loose in (("secret_paths", False), ("registry_hosts", True)):
        a, b = set(committed.get(key) or []), set(draft.get(key) or [])
        for x in sorted(a - b):
            row(key, x, x, None, not wider_is_loose)
        for x in sorted(b - a):
            row(key, x, None, x, wider_is_loose)
    for key, field in (("quarantine", "test"), ("not_checked_locally", "name")):
        a, b = {e[field] for e in committed.get(key) or []}, {e[field] for e in draft.get(key) or []}
        for x in sorted(a - b):
            row(key, x, x, None, False)
        for x in sorted(b - a):
            row(key, x, None, x, True)
    ea, eb = committed.get("sandbox_exceptions") or {}, draft.get("sandbox_exceptions") or {}
    for k in sorted((set(ea) | set(eb)) - {"note"}):
        if ea.get(k) != eb.get(k):
            va, vb = ea.get(k), eb.get(k)
            wider = bool(set(vb or []) - set(va or [])) if isinstance(va or vb, list) else bool(vb) and not va
            row("sandbox_exceptions", k, va, vb, wider)
    la, lb = committed.get("irreversible_levels") or {}, draft.get("irreversible_levels") or {}
    for k in sorted(set(la) | set(lb)):
        a = la.get(k) or defaults.IRREVERSIBLE_DEFAULT_LEVEL.get(k)
        b = lb.get(k) or defaults.IRREVERSIBLE_DEFAULT_LEVEL.get(k)
        if a != b:
            row("irreversible_levels", k, a, b, LEVELS.index(b) < LEVELS.index(a))
    seen = {"commands", "path_rules", "secret_paths", "registry_hosts", "quarantine", "not_checked_locally", "sandbox_exceptions",
            "irreversible_levels", "source", "format"}
    for k in sorted((set(committed) | set(draft)) - seen):
        if committed.get(k) != draft.get(k):
            row(k, k, committed.get(k), draft.get(k), None)
    return rows


# --- the actions -------------------------------------------------------------------------------------

class _Run:
    def __init__(self, args, environ, out, plugin_root, srt, user_tmp, units):
        self.args, self.environ, self.out, self.plugin_root = args, environ, out, plugin_root
        self.srt, self.user_tmp, self.units = srt, user_tmp, units or Units()
        self.repo = args.repo
        self.checkout = os.path.realpath(args.checkout or os.getcwd())
        self.home = pathsmod.engine_home(environ)
        self.ep = pathsmod.EnginePaths(self.home, self.repo, 1)
        self.dir = pathsmod.init_dir(self.home, self.repo)

    # --- small helpers

    def emit(self, obj, text):
        self.out.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n" if self.args.json else text.rstrip("\n") + "\n")

    def progress(self):
        return None if self.args.json else self.out

    def path(self, name):
        return os.path.join(self.dir, name)

    def read(self, name):
        try:
            return store.loads_strict(fsafe.read_bytes(self.path(name), root=store._root(self.ep)).decode("utf-8"), name)
        except FileNotFoundError:
            return None
        except UnicodeDecodeError as e:
            raise Refused(f"{name}: {e}") from e

    def save(self, name, obj):
        root = store._root(self.ep)
        fsafe.make_dirs(self.dir, root=root)
        if isinstance(obj, str):
            fsafe.write_text(self.path(name), obj, root=root)
        else:
            fsafe.write_json(self.path(name), obj, root=root)

    def answers(self):
        rec = store.read_record(self.ep, self.path(DECISIONS), "init-decisions")
        if rec is not None and rec["repo"] != self.ep.repo:
            raise Refused(f"{DECISIONS} is of {rec['repo']}")
        return rec["answers"] if rec else []

    def head(self):
        try:
            return basecheck.head_sha(self.checkout, self.environ)
        except gitops.GitError as e:
            raise Refused(f"{self.checkout}: {e}") from e

    def settings_text(self):
        """The engine settings of the checkout: committed at HEAD, else on disk, else None. A 0.98.x config.json this
        machine migrated (`init migrate`, readiness T2) is no engine settings: None while HEAD and the disk both hold
        the 0.98.x form (or nothing)."""
        try:
            text = basecheck.committed_config(self.checkout, self.head(), self.environ)
        except (gitops.GitError, UnicodeDecodeError) as e:
            raise Refused(f"{defaults.ENGINE_SETTINGS} could not be read: {e}") from e
        disk = self.disk_settings()
        if self.migrated() is not None and all(t is None or legacy_settings(t) for t in (text, disk)):
            return None
        if text is None and disk is not None:
            return ""
        return text

    def disk_settings(self):
        """The text of the engine settings file on disk, or None."""
        try:
            return fsafe.read_bytes(os.path.join(self.checkout, defaults.ENGINE_SETTINGS), root=self.checkout,
                                    max_bytes=4 * 1024 * 1024).decode("utf-8", "replace")
        except FileNotFoundError:
            return None

    def migrated(self):
        """The migration record of this repository (readiness T2), or None."""
        rec = self.read(MIGRATED)
        return rec if rec is not None and rec.get("repo") == self.ep.repo else None

    def legacy_problem(self):
        """Why the settings file is 0.98.x settings init must not take as engine settings, or None."""
        disk = self.disk_settings()
        if disk is not None and legacy_settings(disk) and self.migrated() is None:
            return (f"{defaults.ENGINE_SETTINGS} holds 0.98.x Guild settings — run `init migrate` first (it moves them "
                    "into the commands' settings and keeps a backup); nothing is overwritten")
        return None

    def make_draft(self, answers):
        """The draft of HEAD with these answers (Refused when the tool refuses it)."""
        sha = self.head()
        d = plain = self.units.convert(self.checkout, sha, None, self.environ)
        if answers:
            today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
            d = self.units.convert(self.checkout, sha, to_decisions(answers, plain, today), self.environ)
        return dict(d, answers_sha256=_digest(answers))

    def draft(self):
        """The current draft: of HEAD and of the recorded answers."""
        d = self.read(DRAFT)
        if d is None:
            raise Refused("no draft yet — run `init propose`")
        if d["sha"] != self.head():
            raise Refused(f"the draft is of {d['sha'][:12]}, HEAD moved — run `init propose` again")
        if d["answers_sha256"] != _digest(self.answers()):
            raise Refused("the answers changed after the draft — run `init propose` again")
        return d

    def last_check(self, d):
        c = self.read(CHECK)
        return c if c is not None and c["sha"] == d["sha"] else None

    def questions(self, d):
        """Every question that can be answered now: the draft's, then the last check's."""
        c = self.last_check(d)
        return d["questions"] + (c["questions"] if c else [])

    def question_lines(self, questions, answers):
        out = []
        for q in questions:
            state = "answered" if settled(q, answers) else ("OPEN" if q["required"] else "optional")
            out.append(f"[{state}] {q['question']}" + (f" --item {q['item']!r}" if q["item"] else "") + f": {q['text']}")
            out += [f"    {i}: {t}" for i, t in (q["choices"] or {}).items()]
        return out

    # --- doctor

    def doctor(self):
        rows = []

        def check(name, ok, text):
            rows.append({"check": name, "ok": bool(ok), "text": text})
            return ok
        git_ok = check("git", os.path.isdir(os.path.join(self.checkout, ".git")) and not os.path.islink(
            os.path.join(self.checkout, ".git")), f"{self.checkout} is a main checkout")
        if git_ok:
            try:
                url = gitops._plain_git(self.checkout, ["remote", "get-url", "origin"], self.environ)
            except gitops.GitError:
                url = ""
            got = origin_repo(url)
            check("github", bool(got) and got.lower() == self.ep.repo.lower(),
                  f"origin is {self.ep.repo} on GitHub (it is {url or 'missing'})")
        check("srt", bool(self.srt) and os.access(self.srt or "", os.X_OK), "srt is installed (GLD_SRT_BIN, <engine home>/srt or PATH)")
        check("python3", sys.version_info >= (3, 9), f"python3 is 3.9 or newer ({sys.version.split()[0]})")
        if git_ok:
            legacy = self.legacy_problem()
            none_yet = self.settings_text() is None and legacy is None
            disk, rec = self.disk_settings(), self.migrated()
            if none_yet and rec is not None and disk is not None and legacy_settings(disk):
                # FC M2: after `init migrate` the 0.98.x file is still there — "does not exist yet" read wrong
                text = (f"{defaults.ENGINE_SETTINGS} still holds the 0.98.x settings (migrated {rec.get('at')}) — no "
                        "engine settings yet; `init write` replaces that file at the end of P2.9")
            else:
                text = legacy or f"{defaults.ENGINE_SETTINGS} does not exist yet (when it does: only `init propose --compare`)"
            check("no-settings", none_yet, text)
        ok = all(r["ok"] for r in rows)
        self.emit({"ok": ok, "checks": rows}, "\n".join(f"{'ok ' if r['ok'] else 'NO '} {r['check']}: {r['text']}" for r in rows))
        return EXIT_OK if ok else EXIT_REFUSED

    # --- propose

    def propose(self):
        if self.legacy_problem():
            raise Refused(self.legacy_problem())
        existing = self.settings_text()
        if self.args.compare:
            return self.compare(existing)
        if existing is not None:
            raise Refused(f"{defaults.ENGINE_SETTINGS} exists — `init propose --compare` shows the differences; nothing is overwritten")
        answers = self.answers()
        d = self.make_draft(answers)
        self.save(DRAFT, d)
        self.save(REPORT, d["report"] + "\n")
        self.show(d, answers)
        return EXIT_OK

    def show(self, d, answers):
        qs = self.questions(d)
        todo = open_questions(qs, answers)
        lines = [f"draft of {d['sha'][:12]}: {sum(1 for e in d['config']['commands'].values() if 'cmd' in e)} repository commands, "
                 f"templates {', '.join(sorted(d['templates'])) or 'none'}"]
        lines += [f"  {n}: {e['cmd']}\n      {e.get('description', '')}" for n, e in d["config"]["commands"].items() if "cmd" in e]
        lines += [f"warning: {w}" for w in d["warnings"]]
        lines += [f"template {n} is unusable here: {'; '.join(w)}" for n, w in sorted(d["unusable"].items())]
        lines += [self.roles_line(d)] if d["roles_missing"] else []
        lines += self.question_lines(qs, answers)
        lines.append(f"open questions: {len(todo)} — report: {self.path(REPORT)}")
        self.emit({"sha": d["sha"], "config": d["config"], "templates": sorted(d["templates"]), "unusable": d["unusable"],
                   "warnings": d["warnings"], "roles_missing": d["roles_missing"], "report": self.path(REPORT),
                   "questions": [dict(q, answered=settled(q, answers)) for q in qs], "open": len(todo)}, "\n".join(lines))

    @staticmethod
    def roles_line(d):
        return ("role files missing (only a channel that writes role files makes them — `init roles` says whether this "
                "one does): " + ", ".join(d["roles_missing"]))

    def compare(self, text):
        if not text:
            raise Refused(f"{defaults.ENGINE_SETTINGS} is not committed at HEAD — there is nothing to compare with")
        try:
            committed = repoconfig.RepoConfig.from_text(text).raw
        except repoconfig.ConfigError as e:
            raise Refused(str(e)) from e
        d = self.make_draft(self.answers())
        rows = compare(committed, d["config"])
        loose = [r for r in rows if r["loosened"]]
        lines = [f"{len(rows)} difference(s) of the draft of {d['sha'][:12]} to the committed settings, {len(loose)} loosened"]
        mark = {True: "LOOSENED", False: "stricter", None: "changed"}
        lines += [f"[{mark[r['loosened']]}] {r['area']} {r['item']}: {json.dumps(r['committed'], ensure_ascii=False)} → "
                  f"{json.dumps(r['draft'], ensure_ascii=False)}" for r in rows]
        self.emit({"sha": d["sha"], "differences": rows, "loosened": len(loose), "unusable": d["unusable"]}, "\n".join(lines))
        return EXIT_OK

    # --- answer

    def answer(self):
        a = self.args
        text = a.answer
        if a.answer_file:
            try:
                with open(a.answer_file, "rb") as f:
                    text = f.read().decode("utf-8").strip("\r\n")
            except (OSError, UnicodeDecodeError) as e:
                raise Refused(f"cannot read the answer file: {e}") from e
        if not (a.note or "").strip():
            raise Refused("an answer needs --note: who answered and why")
        d = self.draft()
        asked = self.questions(d)
        q = find_question(asked, a.question, a.item)
        if q is None:
            raise Refused(f"init does not ask {a.question}" + (f" about {a.item!r}" if a.item else "") + " — see `init propose`")
        problem = answer_problem(q, a.item, text, asked)
        if problem:
            raise Refused(f"{a.question}" + (f" {a.item}" if a.item else "") + f": {problem}")
        answers = [x for x in self.answers() if (x["question"], x["item"]) != (a.question, a.item)]
        answers.append({"question": a.question, "item": a.item, "answer": text, "note": a.note.strip(), "at": store.now_ts()})
        new = self.make_draft(answers)           # the tool checks every decision (load_decisions, the engine's loader)
        root = store._root(self.ep)
        fsafe.make_dirs(self.dir, root=root)
        store.write_record(self.ep, self.path(DECISIONS), {"format": 1, "repo": self.ep.repo, "answers": answers}, "init-decisions")
        self.save(DRAFT, new)
        self.save(REPORT, new["report"] + "\n")
        todo = open_questions(self.questions(new), answers)
        self.emit({"recorded": answers[-1], "open": len(todo), "questions": [dict(x, answered=settled(x, answers)) for x in self.questions(new)]},
                  f"recorded: {a.question}" + (f" {a.item}" if a.item else "") + f" = {text}\nopen questions: {len(todo)}")
        return EXIT_OK

    # --- check

    def request(self, d, text=None):
        return basecheck.BaseCheckRequest(
            repo=self.repo, checkout=self.checkout, sha=d["sha"], config_text=text if text is not None else d["config_text"],
            engine_home=self.home, plugin_root=self.plugin_root, environ=self.environ, srt=self.srt, user_tmp=self.user_tmp,
            force=False, out=self.progress())

    def check(self):
        if self.settings_text() is not None:
            raise Refused(f"{defaults.ENGINE_SETTINGS} exists — init does not check or write over it")
        d, answers = self.draft(), self.answers()
        todo = open_questions(d["questions"], answers)
        if todo:
            raise Refused("questions are open: " + ", ".join(q["question"] + (f" {q['item']}" if q["item"] else "") for q in todo))
        digest = basecheck.config_sha256(d["config_text"])
        res = self.units.base_check(self.request(d))
        rec = {"format": 1, "sha": d["sha"], "config_sha256": digest, "ok": False, "at": store.now_ts(), "questions": [],
               "base": {"ok": res.ok, "red": res.red, "flaky": res.flaky, "problem": res.problem, "record": res.record},
               "measured": [], "canaries": []}
        if res.ok:
            rec["canaries"] = self.canaries(d["config"])
            rec["ok"] = all(c["ok"] for c in rec["canaries"])
        else:
            rec["questions"], rec["measured"] = self.after_red(d, res)
        self.save(CHECK, rec)
        lines = ["base check: " + ("green" if res.ok else (f"refused ({res.problem})" if res.problem else "RED: " + ", ".join(res.red)))
                 + (f" — flaky: {', '.join(res.flaky)}" if res.flaky else "")]
        lines += [f"{c['canary']} canary: {'PASS' if c['ok'] else 'FAIL — ' + c['note']}" for c in rec["canaries"]]
        lines += self.question_lines(rec["questions"], answers)
        lines += [f"template {n} is unusable here: {'; '.join(w)}" for n, w in sorted(d["unusable"].items())]
        lines.append("check passed — `init write`" if rec["ok"] else "check did NOT pass")
        self.emit(dict(rec, unusable=d["unusable"], questions=[dict(q, answered=settled(q, answers)) for q in rec["questions"]]),
                  "\n".join(lines))
        return EXIT_OK if rec["ok"] else EXIT_REFUSED

    def canaries(self, config):
        """The role canaries (paid, the same code as the engine's own) and the srt canary of these settings."""
        out, spent = [], 0.0
        try:
            version = self.units.cli_version("claude", self.environ)
        except session.SessionError as e:
            return [{"canary": "role", "ok": False, "note": str(e), "key": None, "cost_usd": None}]
        tmp = self.user_tmp if defaults.USER_TMP_TOKEN in ((config.get("sandbox_exceptions") or {}).get("allow_write") or []) else None
        for cls in (codes.RoleClass.WORK.value, codes.RoleClass.JUDGE.value):
            got = self.units.role_canary(cls, self.environ, self.plugin_root, self.home, config, version, spent_before=spent,
                                         user_tmp=tmp if cls == codes.RoleClass.WORK.value else None, out=self.progress())
            cost = float((got.ran or {}).get("cost_usd") or 0.0)
            spent += cost
            out.append({"canary": cls, "ok": got.ok, "note": got.note, "key": got.key, "cost_usd": cost})
            if not got.ok:
                return out
        ok, key = self.units.srt_canary(self.srt, self.home, config, user_tmp=tmp, base_env=self.environ)
        out.append({"canary": "srt", "ok": ok, "note": "" if ok else f"failed or missing for {key}", "key": key, "cost_usd": 0.0})
        return out

    def after_red(self, d, res):
        """(questions, measured exceptions) of a base that is not green. Only a red command or a failed prepare can be the
        sandbox's doing — anything else (worktree, settings, srt canary, engine) is no question: it is repaired."""
        if res.problem not in (None, "prepare"):
            return [], []
        names = list(res.red) or sorted(n for n, e in d["config"]["commands"].items() if "cmd" in e)
        have = d["config"].get("sandbox_exceptions") or {}
        missing = [k for k, v in EXCEPTIONS.items() if any(not have.get(x) or (isinstance(y, list) and set(y) - set(have[x]))
                                                           for x, y in v.items())]
        best = self.green_with(d, missing, names) if missing else []
        if best:
            for k in list(missing):              # drop what is not needed for what it made green
                rest = [x for x in missing if x != k]
                if rest and set(self.green_with(d, rest, names)) >= set(best):
                    missing = rest
        qs = []
        if best:
            for k in missing:
                qs.append({"question": Q.SANDBOX_EXCEPTION.value, "item": k, "required": False,
                           "text": f"measured: with {' + '.join(missing)} the sandbox lets {', '.join(best)} be green",
                           "choices": {APPROVE: "the run sandbox gets this exception", REJECT: "it stays closed"}})
        for n in res.red:
            if n == "setup":
                continue
            qs.append({"question": Q.QUARANTINE.value, "item": n, "required": False, "choices": None,
                       "text": f"`{n}` is red on the base. If one test is the cause: item `{n}:<test file>`, answer = the command text "
                               f"that leaves it out (written by the human); or `{FIX}`"})
            qs.append({"question": Q.NOT_LOCAL.value, "item": n, "required": False,
                       "text": f"`{n}` is red on the base — can it not run on this machine?",
                       "choices": {NOT_LOCAL_ANSWER: "it leaves the commands and is listed in every PR", FIX: "the repository will be changed"}})
        return qs, [{"exceptions": missing, "green": best}] if best else []

    def green_with(self, d, keys, names):
        config = json.loads(json.dumps(d["config"]))
        exc = config.setdefault("sandbox_exceptions", {})
        for k in keys:
            for x, y in EXCEPTIONS[k].items():
                exc[x] = sorted(set(exc.get(x) or []) | set(y)) if isinstance(y, list) else y
        exc.setdefault("note", WHAT_IF_NOTE)
        return self.units.measure(self.request(d, json.dumps(config, ensure_ascii=False)), names)

    # --- write

    def keep_legacy(self):
        """Copy the 0.98.x settings `write` replaces into the migration's backup folder (readiness T2)."""
        rec = self.migrated()
        folder = rec.get("backup") or self.dir
        root = store._root(self.ep)
        fsafe.make_dirs(folder, root=root)
        fsafe.write_text(os.path.join(folder, "config.json.replaced-by-init-write"), self.disk_settings(), root=root)

    def write(self):
        if self.settings_text() is not None:
            raise Refused(f"{defaults.ENGINE_SETTINGS} exists — never overwritten")
        d = self.draft()
        c = self.read(CHECK)
        if c is None or c["sha"] != d["sha"] or c["config_sha256"] != basecheck.config_sha256(d["config_text"]):
            raise Refused("this draft was not checked — run `init check`")
        if c["ok"] is not True or c["base"]["ok"] is not True:
            raise Refused("the check of this draft did not pass")
        files = {f"{repoconfig.TEMPLATES_DIR}/{n}.yaml": json.dumps(t, indent=2, ensure_ascii=False) + "\n"
                 for n, t in sorted(d["templates"].items())}
        files[os.path.dirname(defaults.ENGINE_SETTINGS) + "/roles/leader.md"] = instructions.default_role_file("leader")
        files[defaults.ENGINE_SETTINGS] = d["config_text"]          # last: the settings are there only when the rest is
        legacy = self.migrated() is not None and legacy_settings(self.disk_settings() or "") is True
        there = [p for p in files if os.path.lexists(os.path.join(self.checkout, p))
                 and not (legacy and p == defaults.ENGINE_SETTINGS)]
        if there:
            raise Refused("exists already, never overwritten: " + ", ".join(there))
        if legacy:                                   # readiness T2: the migrated 0.98.x settings — one more copy first
            self.keep_legacy()
        done = []
        try:
            for rel, text in files.items():
                full = os.path.join(self.checkout, rel)
                fsafe.make_dirs(os.path.dirname(full), root=self.checkout, mode=0o755)
                fsafe.write_text(full, text, root=self.checkout)
                done.append(full)
        except (OSError, fsafe.UnsafePath) as e:
            for full in done:
                if not (legacy and full == os.path.join(self.checkout, defaults.ENGINE_SETTINGS)):
                    os.unlink(full)
            raise Refused(f"{e} — what was written is removed again") from e
        lines = ["wrote (a human reads, changes nothing by hand without a new check, and commits):"] + [f"  {p}" for p in files]
        if d["roles_missing"]:
            lines.append(self.roles_line(d))
        self.emit({"written": list(files), "roles_missing": d["roles_missing"], "unusable": d["unusable"]}, "\n".join(lines))
        return EXIT_OK


def run(action, args, environ, out, *, plugin_root, srt, user_tmp, units=None):
    """`engine.py init <action>` (cli.py parses; `args` = the argparse namespace: repo, checkout, json, compare / question,
    item, answer, answer_file, note). Exit 0 ok, 4 refused. `units` = Units (tests).

    doctor   pre-checks: git repository, GitHub origin, srt, python3, no committed engine settings
    propose  the draft from the 0.98.x settings → CI → lefthook → manifests; `--compare`: only the differences to
             the committed settings, nothing written (TI5)
    answer   record one answer (schemas/init-decisions); question = codes.InitQuestion value (§2.9 table)
    check    base check of the draft (basecheck.check), then the role and srt canaries (canaryrun)
    write    .claude/guild/ of the checkout — refused when settings exist (TI9) or check did not pass (TI8)"""
    if action not in ACTIONS:
        raise ValueError(f"unknown init action {action!r}")
    r = _Run(args, environ, out, plugin_root, srt, user_tmp, units)
    try:
        return getattr(r, action)()
    except (Refused, store.CorruptFile, store.FormatMismatch, fsafe.UnsafePath) as e:
        out.write(f"refused: {e}\n")
        return EXIT_REFUSED
