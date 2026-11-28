"""Engine incident bundles (readiness R1 — design/guild/24-redesign/readiness/incidents.md).

A stop a human must look at that the ENGINE probably caused becomes an incident under
`<engine home>/incidents/<slug>/`: a signature (stop code + where), the engine version and commit, the
repository / Issue / step, the log lines around the stop, copies of the run's role sessions (the engine's
stream.jsonl and the CLI's own transcript, before the CLI deletes it after 30 days) — every copied text
with its secret values removed. The same signature again only counts up and adds one occurrence line.

Two kinds (§1 of the design):
  defect   needs_human stop whose reason codes.stop_cause calls `engine` (an infra-stop for the quota
           excepted — an account limit the sprint reruns itself), an uncaught supervisor exception (a refused
           start, exit 4, is no stop: the human sees it at once);
  suspect  needs_human stop the leader escalated with reason `env-problem`, or one where the leader seat
           gave no usable answer (`leader_failed`) — VW2 E1 and VW3 E2 stopped like this, not with an
           engine code (A13 `label`).
Issue-caused stops and every other `label` stop make no incident.

Signature = "<code> @ <where>":
  engine-error                        innermost gxengine frame of the traceback (`<module>.<function>`)
  another engine code                 the stopped step id (`start` when none); infra-stop as `infra-stop:<detail>`
  escalate:env-problem                the situation (stop.reason), `/<step>` when the step id differs
  leader-failed:<code>[:<detail>]     the same
  sprint-engine-error                 the supervisor's innermost gxengine frame
  silent                              (fixed-defects list only) a defect that never stopped anything

Retro (`prune`) compares each incident with the fixed-defects list shipped beside this engine
(data/fixed-defects.json): an occurrence is explained when an entry of its signature was not yet in the
list the occurring engine had (`occurrences[].engine.fixes`). All explained → `fixed` (removed);
an occurrence on an engine that already had every fix → `recurred` (kept); no entry → `unfixed` (kept).

Nothing here ever changes how the engine stops: the callers catch every exception of `record_*`.
"""

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time

from . import codes, defaults, fsafe, outbound, paths as pathsmod, schema, store

KIND_DEFECT, KIND_SUSPECT, KIND_SILENT = "defect", "suspect", "silent"
KINDS = (KIND_DEFECT, KIND_SUSPECT)
FIX_UNFIXED, FIX_FIXED, FIX_RECURRED = "unfixed", "fixed", "recurred"

SPRINT_ENGINE_ERROR = "sprint-engine-error"
ESCALATE_PREFIX = "escalate:"
LEADER_FAILED_PREFIX = "leader-failed:"
SILENT = "silent"
START = "start"

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXED_DEFECTS_FILE = os.path.join(ENGINE_DIR, "data", "fixed-defects.json")

OCCURRENCES_MAX = 50              # the first and the last 49 lines; `count` stays exact
OCC_LOG_BEFORE, OCC_LOG_AFTER = 5, 2
OCC_LINE_MAX = 2000
NOTE_MAX = 1000
EVIDENCE_LOG_BEFORE, EVIDENCE_LOG_AFTER = 400, 10
FILE_MAX_BYTES = 16 * 1024 * 1024
EVIDENCE_MAX_BYTES = 48 * 1024 * 1024
SESSION_FILES = ("stream.jsonl", "stderr.log", "result.json", "brief.json", "facts.json")
TRANSCRIPT_NAME = "transcript.jsonl"
SLUG_HEAD = 80

_SID = re.compile(r"\A[0-9A-Za-z][0-9A-Za-z_-]{7,63}\Z")
_FRAME = re.compile(r'^\s*File "([^"]+)", line [0-9]+, in (\S+)')

# --- secrets ---------------------------------------------------------------------------------------------

GATE_SECRET_PATTERNS = (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"AKIA[0-9A-Z]{16}",
    r"ASIA[0-9A-Z]{16}",
    r"AIza[0-9A-Za-z_\-]{35}",
    r"xox[baprse]-[0-9A-Za-z-]{10,}",
    r"xapp-[0-9]-[0-9A-Za-z-]{10,}",
    r"gh[pousr]_[0-9A-Za-z]{36,}",
    r"github_pat_[0-9A-Za-z_]{22,}",
    r"sk-ant-[0-9A-Za-z\-_]{20,}",
    r"sk-[A-Za-z0-9]{32,}",
    r"sk_live_[0-9A-Za-z]{16,}",
    r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.",
)
"""The gate's INLINE_SECRET_RES (gates/gate_precommit.py), the same strings — a test keeps them equal."""

_GATE_RES = tuple(re.compile(p) for p in GATE_SECRET_PATTERNS)
_EXTRA_RES = (
    ("authorization", re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic|token)?\s*)([A-Za-z0-9._~+/=\-]{8,})")),
    ("bearer", re.compile(r"(?i)(\bbearer\s+)([A-Za-z0-9._~+/=\-]{16,})")),
    ("key-value", re.compile(
        r"(?i)((?:password|passwd|secret|client[_-]?secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)"
        r"(?:\\?[\"'])?\s*[:=]\s*(?:\\?[\"'])?)(?!\[REDACTED)([^\s\"',;\\]{6,})")),   # also inside a JSON string (\")
    ("url-credential", re.compile(r"(://[^\s/:@\"']+:)([^\s/@\"']+)(@)")),
)
_ENV_NAME = re.compile(r"(?i)(TOKEN|SECRET|KEY|PASSWORD|PASSWD|CREDENTIAL|AUTH)")
ENV_VALUE_MIN = 8
REDACTED_LINE = "[REDACTED:line]"


def _env_secrets(environ):
    out = []
    for name, value in (environ or {}).items():
        if isinstance(value, str) and len(value) >= ENV_VALUE_MIN and _ENV_NAME.search(name) and "\n" not in value:
            out.append((name, value))
    return sorted(out, key=lambda nv: -len(nv[1]))


def redact_text(text, environ=None):
    """(text, count): secret values replaced by `[REDACTED:<rule>]` (no quote, no backslash — a JSON line stays
    JSON). The gate's patterns, Authorization / bearer values, `<secret-ish key> = value`, URL passwords and the
    values of this process's secret-looking environment variables."""
    n = 0
    for name, value in _env_secrets(environ):
        k = text.count(value)
        if k:
            text, n = text.replace(value, f"[REDACTED:env:{name}]"), n + k
    for i, rx in enumerate(_GATE_RES):
        text, k = rx.subn(f"[REDACTED:gate-{i + 1}]", text)
        n += k
    for rule, rx in _EXTRA_RES:
        if rule == "url-credential":
            text, k = rx.subn(lambda m: m.group(1) + f"[REDACTED:{rule}]" + m.group(3), text)
        else:
            text, k = rx.subn(lambda m, r=rule: m.group(1) + f"[REDACTED:{r}]", text)
        n += k
    return text, n


def gate_clean(texts, plugin_root):
    """The second layer (fail-closed): run the 0.98.7 scanner once over `texts` (a list of str); every line it
    still reports becomes REDACTED_LINE. Returns (cleaned texts, lines removed per text). outbound.ScanError
    when the scanner gives no verdict — the caller then keeps none of these texts."""
    if not texts:
        return [], []
    bounds, joined, line = [], [], 1
    for t in texts:
        lines = t.split("\n")
        bounds.append((line, line + len(lines) - 1))
        joined.append(t)
        line += len(lines)
    hits = set(outbound.scan_text("\n".join(joined), plugin_root))
    out, removed = [], []
    for t, (first, _last) in zip(texts, bounds):
        lines = t.split("\n")
        k = 0
        for i in range(len(lines)):
            if first + i in hits:
                lines[i] = REDACTED_LINE
                k += 1
        out.append("\n".join(lines))
        removed.append(k)
    return out, removed


# --- signature ---------------------------------------------------------------------------------------------

def frame_location(tb):
    """`<module>.<function>` of the innermost gxengine frame of a traceback text (else the innermost frame's
    `<file stem>.<function>`, else "unknown")."""
    frames = []
    for line in (tb or "").splitlines():
        m = _FRAME.match(line)
        if m:
            frames.append((m.group(1), m.group(2)))
    if not frames:
        return "unknown"
    ours = [f for f in frames if os.sep + "gxengine" + os.sep in f[0] or "/gxengine/" in f[0]]
    path, func = (ours or frames)[-1]
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"{stem}.{func}"


def _situation_where(stop):
    situation, step = stop.get("reason"), stop.get("step")
    return situation if not step or step == situation else f"{situation}/{step}"


def classify(stop, traceback_text=None):
    """(kind, signature) of a needs_human stop dict (state.json `stop`, or {"reason", "step", "detail"} of a
    refused start), or None when it is no incident."""
    if not isinstance(stop, dict) or stop.get("status", codes.StepStatus.NEEDS_HUMAN.value) != \
            codes.StepStatus.NEEDS_HUMAN.value:
        return None
    reason = stop.get("reason")
    if reason not in codes.StopReason.values():
        return None
    cause = codes.stop_cause(reason)
    if cause == codes.StopCause.ENGINE.value:
        detail = stop.get("detail")
        if reason == codes.StopReason.INFRA_STOP.value and detail == codes.InfraReason.QUOTA.value:
            return None                                  # an account limit, rerun by the sprint (H8) — design §1
        if reason == codes.StopReason.ENGINE_ERROR.value:
            return KIND_DEFECT, f"{reason} @ {frame_location(traceback_text)}"
        code = f"{reason}:{detail}" if reason == codes.StopReason.INFRA_STOP.value and detail else reason
        return KIND_DEFECT, f"{code} @ {stop.get('step') or START}"
    if cause != codes.StopCause.LABEL.value:
        return None
    rec = stop.get("recommendation") or {}
    if rec.get("reason") == codes.LeaderReason.ENV_PROBLEM.value:
        return KIND_SUSPECT, f"{ESCALATE_PREFIX}{rec['reason']} @ {_situation_where(stop)}"
    failed = stop.get("leader_failed") or {}
    if failed.get("code"):
        code = LEADER_FAILED_PREFIX + failed["code"] + (f":{failed['detail']}" if failed.get("detail") else "")
        return KIND_SUSPECT, f"{code} @ {_situation_where(stop)}"
    return None


def slug(signature):
    """The folder name of a signature: lower case, runs outside [a-z0-9.] → "-", 80 characters, "-", the first 8
    hex digits of its sha256 (two signatures never share a folder)."""
    head = re.sub(r"[^a-z0-9.]+", "-", signature.lower()).strip("-.")[:SLUG_HEAD].strip("-.") or "incident"
    return f"{head}-{hashlib.sha256(signature.encode('utf-8')).hexdigest()[:8]}"


_SIG = re.compile(r"\A(?P<code>[a-z0-9][a-z0-9:-]*) @ (?P<where>[A-Za-z0-9_.][A-Za-z0-9_./-]*)\Z")


def signature_kind(signature):
    """The kind a well-formed signature has (defect / suspect / silent), or None when it is not one (§2 grammar;
    the code must be a value the engine writes)."""
    m = _SIG.match(signature or "")
    if not m:
        return None
    code = m.group("code")
    if code == SILENT:
        return KIND_SILENT
    if code.startswith(ESCALATE_PREFIX):
        return KIND_SUSPECT if code[len(ESCALATE_PREFIX):] in codes.LeaderReason.values() else None
    if code.startswith(LEADER_FAILED_PREFIX):
        return KIND_SUSPECT if code[len(LEADER_FAILED_PREFIX):].split(":")[0] in codes.FailureCode.values() else None
    if code == SPRINT_ENGINE_ERROR:
        return KIND_DEFECT
    base, _, detail = code.partition(":")
    if base not in codes.StopReason.values() or codes.stop_cause(base) != codes.StopCause.ENGINE.value:
        return None
    if detail and (base != codes.StopReason.INFRA_STOP.value or detail not in codes.InfraReason.values()):
        return None
    return KIND_DEFECT


# --- engine identity and the fixed-defects list ---------------------------------------------------------------

def load_fixed(path=None):
    """The fixed-defects entries (schemas/fixed-defects). [] when the file is missing; ValueError when broken."""
    path = path or FIXED_DEFECTS_FILE
    try:
        with open(path, encoding="utf-8") as f:
            obj = store.loads_strict(f.read(), "fixed-defects.json")
    except FileNotFoundError:
        return []
    try:
        schema.validate(obj, "fixed-defects")
    except schema.ValidationError as e:
        raise ValueError(f"fixed-defects.json: {e}") from None
    return list(obj["defects"])


def _git(plugin_root, *args):
    try:
        p = subprocess.run(["git", "-C", plugin_root, *args], capture_output=True, text=True, timeout=10,
                           env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C",
                                "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def engine_identity(plugin_root, fixed=None):
    """{version, commit, dirty, fixes} of the engine at `plugin_root`: plugin.json's version, the git HEAD when
    the plugin folder is a work tree (else None), whether it has uncommitted changes, and the ids of the
    fixed-defects list it ships."""
    version = None
    try:
        with open(os.path.join(plugin_root, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            v = json.load(f).get("version")
        version = v if isinstance(v, str) and v else None
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    commit = _git(plugin_root, "rev-parse", "HEAD") if plugin_root else None
    if commit is not None and not re.fullmatch(r"[0-9a-f]{40}([0-9a-f]{24})?", commit):
        commit = None
    dirty = None
    if commit is not None:
        st = _git(plugin_root, "status", "--porcelain", "--", ".")
        dirty = None if st is None else bool(st)
    try:
        entries = load_fixed() if fixed is None else fixed
    except ValueError:                    # store.CorruptFile is a ValueError too
        entries = []
    return {"version": version or "unknown", "commit": commit, "dirty": dirty,
            "fixes": sorted({e["id"] for e in entries})}


# --- the incident file -----------------------------------------------------------------------------------------

def _home_root(engine_home):
    os.makedirs(engine_home, mode=0o700, exist_ok=True)
    st = os.lstat(engine_home)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise fsafe.UnsafePath(engine_home, "the engine home is not a plain directory")
    return engine_home


def _read_incident(ip, sl):
    return store.read_record(ip, ip.incident_json(sl), "incident")


def _write_incident(ip, sl, obj):
    return store.write_record(ip, ip.incident_json(sl), obj, "incident")


class _Lock:
    """incidents/.lock (flock) around one read-modify-write of an incident."""

    def __init__(self, ip):
        self.ip = ip

    def __enter__(self):
        fsafe.make_dirs(self.ip.root, root=_home_root(self.ip.engine_home))
        path = os.path.join(self.ip.root, ".lock")
        fsafe.check_parents(path, root=self.ip.engine_home)
        self.fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)


def _cut(text, n):
    return text if len(text) <= n else text[:n] + " …[cut]"


# --- reading the run that stopped ---------------------------------------------------------------------------

def _raw_log(paths):
    """[(raw line, dict or None)] of log.jsonl ([] when there is none)."""
    try:
        data = fsafe.read_bytes(paths.log, root=paths.engine_home, max_bytes=store.MAX_RECORD_BYTES)
    except FileNotFoundError:
        return []
    out = []
    for raw in data.decode("utf-8", "replace").split("\n"):
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            obj = None
        out.append((raw, obj if isinstance(obj, dict) else None))
    return out


def _stop_index(lines, stop_at):
    """Index of the stop's own `stop` line (to needs_human, at its time), else the last stop / error line."""
    best = None
    for i, (_raw, o) in enumerate(lines):
        if not o:
            continue
        if o.get("event") == codes.LogEvent.STOP.value and o.get("to") == codes.StepStatus.NEEDS_HUMAN.value:
            if stop_at and o.get("ts") == stop_at:
                return i
            best = i
        elif o.get("event") == codes.LogEvent.ERROR.value and best is None:
            best = i
    return best if best is not None else (len(lines) - 1 if lines else None)


def _run_start(lines, idx):
    for i in range(idx, -1, -1):
        o = lines[i][1]
        if o and o.get("event") == codes.LogEvent.ENGINE_START.value:
            return i
    return 0


def _last_traceback(lines, idx):
    for i in range(idx, -1, -1):
        o = lines[i][1]
        if o and o.get("event") == codes.LogEvent.ERROR.value:
            return (o.get("data") or {}).get("traceback")
        if o and o.get("event") == codes.LogEvent.ENGINE_START.value:
            return None
    return None


def _sessions(lines, start, idx, stop_step):
    """[(kind, step, n)] of the run's role / leader sessions: the stopped step's and the leader's first (latest
    first), then the others (latest first). kind "runs" = runs/<step>/<n>, "leader" = leader/<n>."""
    seen, found = set(), []
    for i in range(start, idx + 1):
        o = lines[i][1] or {}
        ev, data = o.get("event"), o.get("data") or {}
        got = []
        if ev == codes.LogEvent.ATTEMPT_START.value and isinstance(o.get("attempt"), int) and o.get("step"):
            got.append(("runs", o["step"], o["attempt"]))
        elif ev == codes.LogEvent.LEADER_CALL.value and data.get("phase") == "end":
            for n in data.get("sessions") or ():
                if isinstance(n, int) and not isinstance(n, bool):
                    got.append(("runs", o.get("step"), n) if data.get("kind") == codes.StepKind.CHECK.value
                               and o.get("step") else ("leader", None, n))
        for g in got:
            if g not in seen:
                seen.add(g)
                found.append(g)
    found.reverse()
    first = [s for s in found if s[0] == "leader" or s[1] == stop_step]
    return first + [s for s in found if s not in first]


def _mutation_record(paths, lines, start, idx):
    for i in range(idx, start - 1, -1):
        o = lines[i][1] or {}
        if o.get("event") == codes.LogEvent.MUTATION_PROOF.value:
            head = (o.get("data") or {}).get("head")
            try:
                return paths.mutation_record(head)
            except ValueError:
                return None
    return None


def _session_id(stream_text):
    for raw in stream_text.split("\n")[:50]:
        try:
            o = json.loads(raw)
        except ValueError:
            continue
        sid = o.get("session_id") if isinstance(o, dict) else None
        if isinstance(sid, str) and _SID.match(sid):
            return sid
    return None


def _config_dir(environ):
    environ = environ or {}
    cfg = environ.get("CLAUDE_CONFIG_DIR")
    if not cfg:
        home = environ.get("HOME")
        if not home or not os.path.isabs(home):
            return None
        cfg = os.path.join(home, ".claude")
    return os.path.realpath(cfg) if os.path.isabs(cfg) else None


def find_transcript(environ, sid):
    """The CLI's own transcript of session `sid`: <CLAUDE_CONFIG_DIR or ~/.claude>/projects/*/<sid>.jsonl."""
    cfg = _config_dir(environ)
    if not cfg or not sid or not _SID.match(sid):
        return None, None
    projects = os.path.join(cfg, "projects")
    try:
        names = sorted(os.listdir(projects))
    except OSError:
        return None, None
    for name in names:
        path = os.path.join(projects, name, sid + ".jsonl")
        st = fsafe._lstat(path)
        if st is not None and stat.S_ISREG(st.st_mode):
            return path, cfg
    return None, None


# --- collecting and writing the evidence ---------------------------------------------------------------------

class _Evidence:
    """The files of the first occurrence: read, redacted, scanned once, then written."""

    def __init__(self, environ):
        self.environ, self.items, self.withheld, self.total = environ, [], [], 0

    def add_text(self, rel, source, text):
        b = len(text.encode("utf-8", "surrogateescape"))
        if b > FILE_MAX_BYTES:
            self.withheld.append({"source": source, "why": "too-large"})
            return
        if self.total + b > EVIDENCE_MAX_BYTES:
            self.withheld.append({"source": source, "why": "size-cap"})
            return
        self.total += b
        red, n = redact_text(text, self.environ)
        self.items.append([rel, source, red, n])

    def add_file(self, rel, path, root):
        st = fsafe._lstat(path)
        if st is None:
            return
        if not stat.S_ISREG(st.st_mode):
            self.withheld.append({"source": path, "why": "unreadable"})
            return
        if st.st_size > FILE_MAX_BYTES:
            self.withheld.append({"source": path, "why": "too-large"})
            return
        if self.total + st.st_size > EVIDENCE_MAX_BYTES:
            self.withheld.append({"source": path, "why": "size-cap"})
            return
        try:
            data = fsafe.read_bytes(path, root=root, max_bytes=FILE_MAX_BYTES)
        except (OSError, fsafe.UnsafePath):
            self.withheld.append({"source": path, "why": "unreadable"})
            return
        self.add_text(rel, path, data.decode("utf-8", "surrogateescape"))

    def write(self, ip, sl, plugin_root):
        files = []
        try:
            cleaned, removed = gate_clean([it[2] for it in self.items], plugin_root)
        except outbound.ScanError:
            self.withheld += [{"source": it[1], "why": "scanner-unavailable"} for it in self.items]
            return {"occurrence": 1, "files": [], "withheld": self.withheld}
        root = ip.engine_home
        for (rel, source, _t, n), text, k in zip(self.items, cleaned, removed):
            dst = os.path.join(ip.evidence_dir(sl), rel)
            fsafe.make_dirs(os.path.dirname(dst), root=root)
            data = text.encode("utf-8", "surrogateescape")
            fsafe.write_bytes(dst, data, root=root, mode=0o600)
            files.append({"path": rel, "source": source, "bytes": len(data), "redacted": n + k})
        return {"occurrence": 1, "files": files, "withheld": self.withheld}


def _collect(paths, lines, start, idx, stop_step, environ, ev):
    lo = max(start, idx - EVIDENCE_LOG_BEFORE)
    ev.add_text("log.jsonl", paths.log, "\n".join(r for r, _o in lines[lo:idx + 1 + EVIDENCE_LOG_AFTER]) + "\n")
    rec = _mutation_record(paths, lines, start, idx)
    if rec:
        ev.add_file("mutation-record.json", rec, paths.engine_home)
    for kind, step, n in _sessions(lines, start, idx, stop_step):
        try:
            d = paths.attempt_dir(step, n) if kind == "runs" else paths.leader_dir(n)
        except ValueError:
            continue
        rel = os.path.join("sessions", f"{step}-{n}" if kind == "runs" else f"leader-{n}")
        for name in SESSION_FILES:
            ev.add_file(os.path.join(rel, name), os.path.join(d, name), paths.engine_home)
        in_dir = os.path.join(d, "in")
        try:
            names = sorted(os.listdir(in_dir)) if not os.path.islink(in_dir) else []
        except OSError:
            names = []
        for name in names:
            ev.add_file(os.path.join(rel, "in", name), os.path.join(in_dir, name), paths.engine_home)
        stream = next((it[2] for it in ev.items if it[0] == os.path.join(rel, "stream.jsonl")), None)
        sid = _session_id(stream) if stream else None
        tpath, troot = find_transcript(environ, sid)
        if tpath:
            ev.add_file(os.path.join(rel, TRANSCRIPT_NAME), tpath, troot)


def _occurrence_strings(lines, idx, note, environ):
    lo, hi = max(0, idx - OCC_LOG_BEFORE), idx + 1 + OCC_LOG_AFTER
    log = [redact_text(_cut(r, OCC_LINE_MAX), environ)[0] for r, _o in lines[lo:hi]]
    note = redact_text(_cut(note, NOTE_MAX), environ)[0] if note else None
    return log, note


def _scan_strings(strings, plugin_root):
    """Gate-scan short strings (one line each after JSON escaping): a hit string becomes REDACTED_LINE. None when
    the scanner gives no verdict."""
    if not strings:
        return []
    enc = [json.dumps(s, ensure_ascii=False) for s in strings]
    try:
        cleaned, removed = gate_clean(enc, plugin_root)
    except outbound.ScanError:
        return None
    return [REDACTED_LINE if k else s for s, k in zip(strings, removed)]


def _record(ip, kind, signature, occ, plugin_root, collect):
    """Add one occurrence (the first one also writes the evidence). Returns the slug, or None when this very stop
    was recorded already."""
    sl = slug(signature)
    strings = list(occ["log"]) + ([occ["note"]] if occ["note"] else [])
    scanned = _scan_strings(strings, plugin_root)
    if scanned is None:
        occ["log"], occ["note"] = [], None
    else:
        occ["log"] = scanned[:len(occ["log"])]
        occ["note"] = scanned[-1] if occ["note"] else None
    with _Lock(ip):
        try:
            inc = _read_incident(ip, sl)
        except (store.CorruptFile, store.FormatMismatch):
            inc = None
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            os.replace(ip.incident_json(sl), ip.incident_json(sl) + f".corrupt-{stamp}")
        key = (occ["repo"], occ["issue"], occ["tracker"], occ["at"])
        if inc is not None and any((o["repo"], o["issue"], o["tracker"], o["at"]) == key for o in inc["occurrences"]):
            return None
        now = store.now_ts()
        occ["recorded"] = now
        if inc is None:
            ev = _Evidence(collect[1])
            collect[0](ev)
            occ["n"] = 1
            inc = {"format": defaults.FORMAT, "signature": signature, "slug": sl, "kind": kind,
                   "first_seen": now, "last_seen": now, "count": 1, "evidence": None, "occurrences": [occ]}
            fsafe.make_dirs(ip.incident_dir(sl), root=_home_root(ip.engine_home))
            inc["evidence"] = ev.write(ip, sl, plugin_root)
        else:
            inc["count"] += 1
            inc["last_seen"] = now
            occ["n"] = inc["count"]
            occs = inc["occurrences"] + [occ]
            inc["occurrences"] = occs if len(occs) <= OCCURRENCES_MAX else occs[:1] + occs[-(OCCURRENCES_MAX - 1):]
        _write_incident(ip, sl, inc)
    return sl


def _occurrence(repo, issue, tracker, stop, records, identity):
    rec, failed = stop.get("recommendation") or {}, stop.get("leader_failed")
    return {"n": 0, "at": stop.get("at") or store.now_ts(), "recorded": None, "repo": repo, "issue": issue,
            "tracker": tracker, "step": stop.get("step"), "reason": stop.get("reason"), "detail": stop.get("detail"),
            "escalate_reason": rec.get("reason"),
            "leader_failed": None if not failed else {"code": failed.get("code"), "detail": failed.get("detail")},
            "engine": identity, "records": records, "note": None, "log": []}


def record_stop(paths, state, *, plugin_root, environ, refused=None, fixed=None):
    """Record the Issue's needs_human stop (state.json `stop`) as an incident when classify says so. `refused` =
    {"reason", "note"} stands in for a stop state.json could not take (an engine-error before or while the state
    was read). Returns the slug, or None (no incident, or this stop was recorded already). `paths` = EnginePaths."""
    stop = dict(refused, status=codes.StepStatus.NEEDS_HUMAN.value, step=None, at=store.now_ts()) if refused \
        else (state or {}).get("stop")
    if not stop or stop.get("status") != codes.StepStatus.NEEDS_HUMAN.value:
        return None
    lines = _raw_log(paths)
    idx = _stop_index(lines, None if refused else stop.get("at"))
    tb = _last_traceback(lines, idx) if idx is not None else None
    got = classify(stop, tb)
    if got is None:
        return None
    kind, signature = got
    start = _run_start(lines, idx) if idx is not None else 0
    tracker = (state or {}).get("sprint")
    occ = _occurrence(paths.repo, paths.issue, tracker if isinstance(tracker, int) else None, stop,
                      paths.issue_dir, engine_identity(plugin_root, fixed))
    if idx is not None:
        occ["log"], occ["note"] = _occurrence_strings(lines, idx, stop.get("note") or "", environ)

    def collect(ev):
        if idx is not None:
            _collect(paths, lines, start, idx, stop.get("step"), environ, ev)
    return _record(pathsmod.IncidentPaths(paths.engine_home), kind, signature, occ, plugin_root, (collect, environ))


def record_sprint_halt(sp, traceback_text, note, *, plugin_root, environ, fixed=None):
    """An uncaught exception of the supervisor (`halted: engine-error`) → a defect incident. `sp` = SprintPaths."""
    signature = f"{SPRINT_ENGINE_ERROR} @ {frame_location(traceback_text)}"
    stop = {"reason": codes.SprintHalt.ENGINE_ERROR.value, "step": None, "at": store.now_ts(), "note": note}
    occ = _occurrence(sp.repo, None, sp.tracker, stop, sp.dir, engine_identity(plugin_root, fixed))
    occ["log"] = [redact_text(_cut(traceback_text or "", OCC_LINE_MAX * 4), environ)[0]]
    occ["note"] = redact_text(_cut(note or "", NOTE_MAX), environ)[0] or None

    def collect(ev):
        try:
            data = fsafe.read_bytes(sp.log, root=sp.engine_home, max_bytes=store.MAX_RECORD_BYTES)
            tail = data.decode("utf-8", "replace").split("\n")[-(EVIDENCE_LOG_BEFORE + 1):]
            ev.add_text("log.jsonl", sp.log, "\n".join(tail))
        except (OSError, fsafe.UnsafePath):
            pass
        ev.add_text("traceback.txt", "supervisor", traceback_text or "")
    return _record(pathsmod.IncidentPaths(sp.engine_home), KIND_DEFECT, signature, occ, plugin_root,
                   (collect, environ))


# --- list and prune (daily, retro) -------------------------------------------------------------------------

def fix_status(inc, fixed):
    """(status, [fix ids of its signature], [n of the occurrences that recurred after every fix])."""
    ids = [e["id"] for e in fixed if e["signature"] == inc["signature"] and e["kind"] != KIND_SILENT]
    if not ids:
        return FIX_UNFIXED, [], []
    rec = [o["n"] for o in inc["occurrences"] if set(ids) <= set((o.get("engine") or {}).get("fixes") or ())]
    return (FIX_RECURRED if rec else FIX_FIXED), ids, rec


def _slugs(ip):
    try:
        names = sorted(os.listdir(ip.root))
    except FileNotFoundError:
        return []
    return [n for n in names if pathsmod.is_incident_slug(n) and os.path.isdir(os.path.join(ip.root, n))
            and not os.path.islink(os.path.join(ip.root, n))]


def summaries(engine_home, fixed=None):
    """Every incident, newest first: {slug, signature, kind, count, first_seen, last_seen, last, path, fix_status,
    fixes, recurred} — or {slug, path, problem} for an unreadable one. The list daily shows as it is."""
    fixed = load_fixed() if fixed is None else fixed
    ip = pathsmod.IncidentPaths(engine_home)
    out = []
    for sl in _slugs(ip):
        try:
            inc = _read_incident(ip, sl)
        except (store.CorruptFile, store.FormatMismatch, fsafe.UnsafePath) as e:
            out.append({"slug": sl, "path": ip.incident_dir(sl), "problem": str(e)[:300]})
            continue
        if inc is None:
            continue
        status, ids, rec = fix_status(inc, fixed)
        last = inc["occurrences"][-1]
        out.append({"slug": sl, "signature": inc["signature"], "kind": inc["kind"], "count": inc["count"],
                    "first_seen": inc["first_seen"], "last_seen": inc["last_seen"],
                    "last": {k: last.get(k) for k in ("repo", "issue", "tracker", "step", "at")},
                    "path": ip.incident_dir(sl), "fix_status": status, "fixes": ids, "recurred": rec})
    out.sort(key=lambda r: r.get("last_seen") or "", reverse=True)
    return out


def remove_tree(path, root):
    """Remove a directory below `root` that is a plain directory (never a link); fsafe.UnsafePath otherwise."""
    fsafe.check_parents(path, root=root)
    st = fsafe._lstat(path)
    if st is None:
        return False
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise fsafe.UnsafePath(path, "not a plain directory")
    shutil.rmtree(path)
    return True


def prune(engine_home, apply=False, fixed=None):
    """Retro: remove every `fixed` incident (only with `apply`). One row per incident: {slug, signature, kind,
    fix_status, action (removed / would-remove / kept), fixes [{id, version, commit, summary}], recurred, path}."""
    fixed = load_fixed() if fixed is None else fixed
    by_id = {e["id"]: e for e in fixed}
    ip = pathsmod.IncidentPaths(engine_home)
    rows = []
    for s in summaries(engine_home, fixed):
        if "problem" in s:
            rows.append(dict(s, action="kept"))
            continue
        action = "kept"
        if s["fix_status"] == FIX_FIXED:
            action = "would-remove"
            if apply:
                with _Lock(ip):
                    remove_tree(s["path"], ip.engine_home)
                action = "removed"
        rows.append({"slug": s["slug"], "signature": s["signature"], "kind": s["kind"], "count": s["count"],
                     "fix_status": s["fix_status"], "action": action, "recurred": s["recurred"], "path": s["path"],
                     "fixes": [{"id": i, "version": by_id[i]["fixed_in"]["version"],
                                "commit": by_id[i]["fixed_in"].get("commit"), "summary": by_id[i]["summary"]}
                               for i in s["fixes"]]})
    return rows


def referenced_records(engine_home):
    """Real paths of every records folder an incident occurrence names (records cleanup keeps them)."""
    ip = pathsmod.IncidentPaths(engine_home)
    out = set()
    for sl in _slugs(ip):
        try:
            inc = _read_incident(ip, sl)
        except (store.CorruptFile, store.FormatMismatch, fsafe.UnsafePath):
            continue
        for o in (inc or {}).get("occurrences") or ():
            if o.get("records"):
                out.add(os.path.realpath(o["records"]))
    return out
