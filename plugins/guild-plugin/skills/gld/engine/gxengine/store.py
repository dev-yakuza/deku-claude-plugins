"""state.json, log.jsonl and attempt files — read, validate, write (design §4.3, §7.2-3) — U2.

Every write is atomic through fsafe and validated against its schema first
(`schemas/state`, `log-line`, `brief`, `facts`). `result.json` is the role's claim:
it is stored as received (the session runner extracts it from the stream) and
validated by results.py, not here.

`format` (§4.3): every file carries `format`. Reading a file whose format this engine
cannot convert raises FormatMismatch → needs_human (StopReason.FORMAT_MISMATCH). A
version that changes a CORE field of state.json ships a converter here (`CONVERTERS`).

All reads and writes stay below `paths.engine_home` (the fsafe root): a link or a
non-regular file anywhere under it raises fsafe.UnsafePath (StopReason.UNSAFE_PATH).
A file that is not JSON, or a JSON object that fails its schema, raises CorruptFile
(the driver stops with engine-error — the engine never guesses a broken record).
"""

import json
import os
import stat
import time

from . import codes, defaults, fsafe, schema

STATE_CORE_FIELDS = ("format", "issue", "revision", "steps", "last_head")
STATE_STEP_CORE_FIELDS = ("id", "status", "latest_attempt")

CONVERTERS = {}
"""(file kind, from format) → function(obj) -> obj of the next format. Empty in format 1."""

MAX_RECORD_BYTES = 64 * 1024 * 1024
"""Refuse to read an engine record larger than this (a role cannot write records; a
huge file means something is badly wrong)."""


class FormatMismatch(Exception):
    """A file's `format` is not ours and no converter exists (§4.3)."""


class CorruptFile(ValueError):
    """An engine file is not valid JSON or does not satisfy its schema."""


# --- helpers ----------------------------------------------------------------------

def now_ts(t=None):
    """UTC timestamp string in the schemas' `ts` form (2026-11-23T01:02:03Z)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if t is None else t))


def _plain(obj):
    """JSON round trip: str enums become plain strings, tuples lists; refuses NaN."""
    return json.loads(json.dumps(obj, allow_nan=False))


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate key {k!r}")
        out[k] = v
    return out


def _bad_constant(name):
    raise ValueError(f"not JSON: {name}")


def loads_strict(text, what="file"):
    """json.loads that refuses duplicate keys and NaN/Infinity (CorruptFile)."""
    try:
        return json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_bad_constant)
    except (ValueError, RecursionError) as e:
        raise CorruptFile(f"{what}: not valid JSON ({e})") from None


def _validate(obj, name, what):
    try:
        schema.validate(obj, name)
    except schema.ValidationError as e:
        raise CorruptFile(f"{what}: {e}") from None


def convert(kind, obj, what="file"):
    """Bring `obj` to defaults.FORMAT through CONVERTERS, or raise FormatMismatch."""
    if not isinstance(obj, dict):
        raise CorruptFile(f"{what}: not a JSON object")
    seen = set()
    while True:
        fmt = obj.get("format")
        if isinstance(fmt, bool) or not isinstance(fmt, int):
            raise FormatMismatch(f"{what}: no integer `format` field")
        if fmt == defaults.FORMAT:
            return obj
        conv = CONVERTERS.get((kind, fmt))
        if conv is None or fmt in seen:
            raise FormatMismatch(
                f"{what}: format {fmt}, this engine writes {defaults.FORMAT} and has no converter")
        seen.add(fmt)
        obj = conv(obj)


def _root(paths):
    """The fsafe root (engine home): created if missing, must be a real directory."""
    home = paths.engine_home
    if not os.path.lexists(home):
        os.makedirs(home, mode=0o700, exist_ok=True)
    st = os.lstat(home)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise fsafe.UnsafePath(home, "the engine home is not a plain directory")
    return home


def _read(paths, path):
    return fsafe.read_bytes(path, root=_root(paths), max_bytes=MAX_RECORD_BYTES)


def _read_json(paths, path, kind, schema_name):
    what = os.path.relpath(path, paths.engine_home)
    try:
        text = _read(paths, path).decode("utf-8")
    except UnicodeDecodeError:
        raise CorruptFile(f"{what}: not UTF-8") from None
    obj = convert(kind, loads_strict(text, what), what)
    _validate(obj, schema_name, what)
    return obj


def _write_json(paths, path, obj):
    root = _root(paths)
    fsafe.make_dirs(os.path.dirname(path), root=root)
    return fsafe.write_json(path, obj, root=root)


def _check_ids(paths, step, attempt, obj, what):
    for key, want in (("issue", paths.issue), ("step", step), ("attempt", attempt)):
        if obj.get(key) != want:
            raise ValueError(f"{what}: `{key}` is {obj.get(key)!r}, expected {want!r}")


# --- state.json -------------------------------------------------------------------

def new_state(issue, revision, step_ids, head, **free):
    """Build a fresh state dict: every step pending, latest_attempt null, plus free fields."""
    clash = set(free) & set(STATE_CORE_FIELDS)
    if clash:
        raise ValueError(f"core fields passed as free fields: {sorted(clash)}")
    ids = list(step_ids)
    if not ids:
        raise ValueError("a state needs at least one step")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate step ids")
    state = {
        "format": defaults.FORMAT,
        "issue": issue,
        "revision": revision,
        "steps": [{"id": s, "status": codes.StepStatus.PENDING.value, "latest_attempt": None}
                  for s in ids],
        "last_head": head,
    }
    state.update(free)
    state = _plain(state)
    _validate(state, "state", "new state")
    return state


def load_state(paths):
    """Read and validate state.json (converting older formats). None when it does not exist."""
    try:
        state = _read_json(paths, paths.state, "state", "state")
    except FileNotFoundError:
        return None
    if state["issue"] != paths.issue:
        raise CorruptFile(f"state.json: issue {state['issue']} in the folder of issue {paths.issue}")
    return state


def save_state(paths, state):
    """Validate against schemas/state and write atomically (fsafe)."""
    obj = _plain(state)
    _validate(obj, "state", "state.json")
    if obj["issue"] != paths.issue:
        raise ValueError(f"state of issue {obj['issue']} saved under issue {paths.issue}")
    ids = [s["id"] for s in obj["steps"]]
    if len(set(ids)) != len(ids):
        raise ValueError("state.json: duplicate step ids")
    return _write_json(paths, paths.state, obj)


# --- log.jsonl --------------------------------------------------------------------

def make_log_line(issue, event, who="engine", **fields):
    """The validated log.jsonl object (fields with value None are left out)."""
    line = {"format": defaults.FORMAT, "ts": fields.pop("ts", None) or now_ts(),
            "issue": issue, "who": who, "event": event}
    for k, v in fields.items():
        if k in line:
            raise ValueError(f"log field {k!r} is set by the engine")
        if v is not None:
            line[k] = v
    line = _plain(line)
    _validate(line, "log-line", "log line")
    return line


def append_log(paths, event, who="engine", **fields):
    """Append one validated log.jsonl line {format, ts, issue, who, event, …fields}."""
    line = make_log_line(paths.issue, event, who=who, **fields)
    root = _root(paths)
    fsafe.make_dirs(paths.issue_dir, root=root)
    fsafe.append_line(paths.log, json.dumps(line, ensure_ascii=False, separators=(",", ":")), root=root)
    return line


def read_log(paths):
    """Yield every log line as a dict (for status and U19)."""
    try:
        data = _read(paths, paths.log)
    except FileNotFoundError:
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise CorruptFile("log.jsonl: not UTF-8") from None
    if text and not text.endswith("\n"):
        raise CorruptFile("log.jsonl: the last line is incomplete")
    for n, raw in enumerate(text.split("\n")[:-1], 1):
        what = f"log.jsonl line {n}"
        obj = convert("log-line", loads_strict(raw, what), what)
        _validate(obj, "log-line", what)
        yield obj


# --- attempt files ----------------------------------------------------------------

def _state_step(state, step_id):
    for s in state["steps"]:
        if s["id"] == step_id:
            return s
    raise KeyError(f"step {step_id!r} is not in state.json")


def new_attempt(paths, state, step_id):
    """Create runs/<step>/<n>/ and in/ for the next attempt; return n (1-based).

    Updates state's latest_attempt in memory only — the caller saves state.
    n = latest_attempt + 1; a folder left behind by a crash before the state was
    saved is never reused or overwritten — n moves past it.
    """
    s = _state_step(state, step_id)
    root = _root(paths)
    fsafe.make_dirs(paths.step_dir(step_id), root=root)
    n = (s.get("latest_attempt") or 0) + 1
    while True:
        d = paths.attempt_dir(step_id, n)
        try:
            os.mkdir(d, 0o700)
            break
        except FileExistsError:
            n += 1
    fsafe.make_dirs(paths.in_dir(step_id, n), root=root)
    s["latest_attempt"] = n
    return n


def write_brief(paths, step, attempt, brief):
    """Validate against schemas/brief and write runs/<step>/<attempt>/brief.json."""
    obj = _plain(brief)
    _validate(obj, "brief", "brief.json")
    _check_ids(paths, step, attempt, obj, "brief.json")
    return _write_json(paths, paths.attempt_file(step, attempt, "brief.json"), obj)


def read_brief_or_none(paths, step, attempt):
    """A brief.json (validated), or None when it is missing, unreadable or not this attempt's."""
    try:
        obj = _read_json(paths, paths.attempt_file(step, attempt, "brief.json"), "brief", "brief")
        _check_ids(paths, step, attempt, obj, "brief.json")
    except (FileNotFoundError, ValueError, FormatMismatch):
        return None
    return obj


def attempt_numbers(paths, step):
    """Sorted n of every runs/<step>/<n>/ folder on disk ([] when the step never ran)."""
    try:
        names = os.listdir(paths.step_dir(step))
    except FileNotFoundError:
        return []
    return sorted(int(n) for n in names if n.isdigit() and n == str(int(n)) and int(n) >= 1)


def write_facts(paths, step, attempt, facts):
    """Validate against schemas/facts and write runs/<step>/<attempt>/facts.json."""
    obj = _plain(facts)
    _validate(obj, "facts", "facts.json")
    _check_ids(paths, step, attempt, obj, "facts.json")
    return _write_json(paths, paths.attempt_file(step, attempt, "facts.json"), obj)


def read_facts(paths, step, attempt):
    """Read a facts.json (validated)."""
    obj = _read_json(paths, paths.attempt_file(step, attempt, "facts.json"), "facts", "facts")
    try:
        _check_ids(paths, step, attempt, obj, "facts.json")
    except ValueError as e:
        raise CorruptFile(str(e)) from None
    return obj


def _write_received(paths, path, result):
    """Write a structured output as received (result.json of a role or a leader).

    review-q0 D9 (Q8 ③): a string holding a lone surrogate cannot be written as UTF-8. It is
    recorded with ASCII escapes (`\\ud83d`) — nothing is replaced, json.loads gives the same
    object back — and the judgment refuses it by name (schema.surrogate_errors)."""
    root = _root(paths)
    fsafe.make_dirs(os.path.dirname(path), root=root)
    if isinstance(result, (bytes, bytearray)):
        return fsafe.write_bytes(path, bytes(result), root=root)
    if isinstance(result, str):
        return fsafe.write_bytes(path, result.encode("utf-8", "backslashreplace"), root=root)
    if schema.surrogate_errors(result):
        text = json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        return fsafe.write_text(path, text, root=root)
    return fsafe.write_json(path, result, root=root)


def write_result(paths, step, attempt, result):
    """Write the role's structured output as received to result.json (not validated here).

    `result` is the parsed structured output (written as engine JSON; with a lone surrogate:
    ASCII-escaped) or the raw text / bytes as received (written byte for byte).
    """
    return _write_received(paths, paths.attempt_file(step, attempt, "result.json"), result)


def write_in_file(paths, step, attempt, name, text):
    """Write an engine-made input (codes.InFile value) into the attempt's in/ folder."""
    if name not in codes.InFile.values():
        raise ValueError(f"not an engine input file name: {name!r}")
    d = paths.in_dir(step, attempt)
    root = _root(paths)
    fsafe.make_dirs(d, root=root)
    # review.diff is `git diff -a` output decoded with surrogateescape: a non-UTF-8 byte (P5
    # real run, #1797) must round-trip to the same byte, not crash the engine.
    return fsafe.write_bytes(os.path.join(d, str(name)), text.encode("utf-8", "surrogateescape"),
                             root=root)


# --- stage 2: needs_leader call folders leader/<k>/ (D13) ---------------------------
# Same files as an attempt folder. brief / facts carry `kind: leader`, `step` = the step the
# situation is attached to and `attempt` = k, so _check_ids works unchanged.

def leader_call_numbers(paths):
    """Sorted k of every leader/<k>/ folder on disk (budget.issue_cost reads their facts)."""
    try:
        names = os.listdir(paths.leader_root)
    except FileNotFoundError:
        return []
    return sorted(int(n) for n in names if n.isdigit() and n == str(int(n)) and int(n) >= 1)


def new_leader_call(paths):
    """Create leader/<k>/ and its in/ for the next needs_leader session; return k (1-based).

    k = 1 + the highest existing folder number — never reused, so a re-call after an engine
    crash lands in the next folder (L21). Nothing in state changes (the caller records
    state.leader_calls)."""
    root = _root(paths)
    fsafe.make_dirs(paths.leader_root, root=root)
    nums = leader_call_numbers(paths)
    k = (nums[-1] if nums else 0) + 1
    while True:
        try:
            os.mkdir(paths.leader_dir(k), 0o700)
            break
        except FileExistsError:
            k += 1
    fsafe.make_dirs(paths.leader_in_dir(k), root=root)
    return k


def _check_leader_obj(paths, step, k, obj, what):
    if obj.get("kind") != codes.AttemptKind.LEADER.value:
        raise ValueError(f"{what}: `kind` is {obj.get('kind')!r}, a leader call folder holds kind leader")
    _check_ids(paths, step, k, obj, what)


def write_leader_brief(paths, step, k, brief):
    """Validate against schemas/brief and write leader/<k>/brief.json."""
    obj = _plain(brief)
    _validate(obj, "brief", "brief.json")
    _check_leader_obj(paths, step, k, obj, "leader brief.json")
    return _write_json(paths, paths.leader_file(k, "brief.json"), obj)


def write_leader_facts(paths, step, k, facts):
    """Validate against schemas/facts and write leader/<k>/facts.json."""
    obj = _plain(facts)
    _validate(obj, "facts", "facts.json")
    _check_leader_obj(paths, step, k, obj, "leader facts.json")
    return _write_json(paths, paths.leader_file(k, "facts.json"), obj)


def read_leader_facts(paths, k):
    """Read leader/<k>/facts.json (validated; kind leader, attempt k)."""
    obj = _read_json(paths, paths.leader_file(k, "facts.json"), "facts", "facts")
    try:
        _check_leader_obj(paths, obj.get("step"), k, obj, "leader facts.json")
    except ValueError as e:
        raise CorruptFile(str(e)) from None
    return obj


def write_leader_result(paths, k, result):
    """Write the leader's structured output as received to leader/<k>/result.json."""
    return _write_received(paths, paths.leader_file(k, "result.json"), result)


def write_leader_in_file(paths, k, name, text):
    """Write an engine-made input (codes.InFile value) into leader/<k>/in/."""
    if name not in codes.InFile.values():
        raise ValueError(f"not an engine input file name: {name!r}")
    d = paths.leader_in_dir(k)
    root = _root(paths)
    fsafe.make_dirs(d, root=root)
    # the same byte round trip as write_in_file (a non-UTF-8 byte of issue.md / a diff, P5 #1797)
    return fsafe.write_bytes(os.path.join(d, str(name)), text.encode("utf-8", "surrogateescape"),
                             root=root)


# --- stage 4: sprint, base-green and mutation records ------------------------------------------
# `sp` is a paths.SprintPaths. The same rules as above: validated, atomic, no links below the engine home.

def save_sprint(sp, obj):
    """Validate against schemas/sprint-state and write sprint.json (the supervisor only)."""
    obj = _plain(obj)
    _validate(obj, "sprint-state", "sprint.json")
    if obj["repo"] != sp.repo or obj["tracker"] != sp.tracker:
        raise ValueError("sprint.json: repo / tracker differ from its folder")
    if (obj["state"] == codes.SprintState.HALTED.value) != (obj["halt"] is not None):
        raise ValueError("sprint.json: `halt` is set exactly when state = halted")
    for m in obj["members"]:
        if (m["outcome"] == codes.MemberOutcome.BLOCKED.value) != (m["block"] is not None):
            raise ValueError(f"sprint.json: member {m['issue']}: `block` is set exactly when outcome = blocked")
    return _write_json(sp, sp.state, obj)


def load_sprint(sp):
    """sprint.json, or None when this tracker has not been run on this machine."""
    try:
        return _read_json(sp, sp.state, "sprint-state", "sprint-state")
    except FileNotFoundError:
        return None


def append_sprint_log(sp, run, event, **fields):
    """Append one validated sprint log line {format, ts, tracker, run, event, …fields} (None fields left out)."""
    line = {"format": defaults.FORMAT, "ts": fields.pop("ts", None) or now_ts(), "tracker": sp.tracker, "run": run,
            "event": event}
    for k, v in fields.items():
        if k in line:
            raise ValueError(f"sprint log field {k!r} is set by the engine")
        if v is not None:
            line[k] = v
    line = _plain(line)
    _validate(line, "sprint-log-line", "sprint log line")
    root = _root(sp)
    fsafe.make_dirs(sp.dir, root=root)
    fsafe.append_line(sp.log, json.dumps(line, ensure_ascii=False, separators=(",", ":")), root=root)
    return line


def read_sprint_log(sp):
    """Every sprint log line (a list; [] when there is none)."""
    try:
        text = _read(sp, sp.log).decode("utf-8")
    except FileNotFoundError:
        return []
    except UnicodeDecodeError:
        raise CorruptFile("sprint log.jsonl: not UTF-8") from None
    if text and not text.endswith("\n"):
        raise CorruptFile("sprint log.jsonl: the last line is incomplete")
    out = []
    for n, raw in enumerate(text.split("\n")[:-1], 1):
        what = f"sprint log.jsonl line {n}"
        obj = convert("sprint-log-line", loads_strict(raw, what), what)
        _validate(obj, "sprint-log-line", what)
        out.append(obj)
    return out


def write_record(paths, path, obj, schema_name):
    """Validate `obj` against schemas/<schema_name> and write the engine record `path` (base-green,
    mutation-record, init-decisions). `paths` = EnginePaths or SprintPaths of the same engine home."""
    obj = _plain(obj)
    _validate(obj, schema_name, os.path.basename(path))
    return _write_json(paths, path, obj)


def read_record(paths, path, schema_name):
    """The validated record at `path`, or None when there is none. CorruptFile / FormatMismatch otherwise."""
    try:
        return _read_json(paths, path, schema_name, schema_name)
    except FileNotFoundError:
        return None
