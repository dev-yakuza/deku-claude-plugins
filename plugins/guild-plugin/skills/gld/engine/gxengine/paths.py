"""Where engine files live (design §4.3, §7.2-3, §7.3, §7.12 S7, §미결 M6) — U2.

Layout (P2-0 contract — see interfaces.md "해석한 곳" for the M6 choice):

    <engine_home>/                          GLD_ENGINE_HOME, default ~/.gld
      records/<owner>/<repo>/<issue>/       engine records — denied to every role (read+write)
        state.json   log.jsonl   engine.log   engine.rc   lock
        followups-dry-run.jsonl security-findings.md     stage 3 (A4, E21) — local only
        runs/<step>/<attempt>/
          brief.json result.json facts.json
          stream.jsonl stderr.log            role session (stream-json as recorded)
          settings.json srt.json             the rendered boundary of this attempt
          run.log                            run step output
          in/                                engine-made inputs — the ONE engine folder a
                                             role may read (§7.12 S7)
        leader/<k>/                          stage 2: one needs_leader session (same files
                                             as an attempt folder, D13)
        mutations/<head sha>/                stage 4 (VB9): record.json + the run logs
      cache/<owner>/<repo>/                 the repo's Guild cache ({cache}, §7.6, S8) — role-writable
      tmp/<owner>/<repo>/<issue>/<step>-<attempt>/   per-run temp dir — role-writable
      records/<owner>/<repo>/               stage 4 (Issue folders are numbers, so no clash):
        sprints/<tracker>/                   sprint.json log.jsonl supervisor.log supervisor.rc lock
        sprint.lock                          one supervisor per repository (H4)
        base-green/<sha>-<config sha256, 16>.json   base check records (H12)
      init/<owner>/<repo>/                  stage 4 (§2.9): init draft, decisions, check results
      incidents/<slug>/                     readiness R1: incident.json + evidence/ (incidents.py)
      heavy-run.lock                        stage 4 (H22): one repository command at a time (flock)
      srt/                                  plugin-managed `npm install --prefix` of srt (§7.6)
      canary/                               canary results by key (I9)

    <main checkout parent>/.gld-<repo>-<issue>/      the Issue worktree (§7.3)
    /tmp/gx-<id>/                                     srt's own short TMPDIR (F0)

Rules: no engine record under the worktree, under any role write-allowed path, or under
/tmp/claude-<uid> (§7.3, F4). `<step>` is the step id, `<attempt>` is 1-based.

Every name that becomes a path component (owner, repo, step, attempt file) is checked
here, so no value can climb out of its folder (`..`, `/`, leading `.`-only names).
"""

import os
import re

from . import defaults

ENV_ENGINE_HOME = "GLD_ENGINE_HOME"
DEFAULT_ENGINE_HOME = "~/.gld"
LEADER_DIR = "leader"
"""Stage 2 (D13): records/<owner>/<repo>/<issue>/leader/<k>/ — one folder per needs_leader
session (brief result facts stream stderr settings in/), k 1-based and never reused."""

_REPO_PART = re.compile(r"\A[A-Za-z0-9_.-]{1,100}\Z")
_STEP = re.compile(r"\A[a-z][a-z0-9]*(-[a-z0-9]+)*\Z")
_FILE = re.compile(r"\A[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}\Z")
_RUN_ID = re.compile(r"\A[A-Za-z0-9_-]{1,24}\Z")
_SHA = re.compile(r"\A[0-9a-f]{40}([0-9a-f]{24})?\Z")
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
BASE_GREEN_CONFIG_LEN = 16
"""Characters of the config sha256 in a base-green file name."""
MUTATIONS_DIR = "mutations"
MUTATION_RECORD = "record.json"

# The sandbox temp roots an engine record must never sit under (F4). macOS resolves
# /tmp to /private/tmp, so both spellings are refused.
_FORBIDDEN_PREFIXES = (
    defaults.SANDBOX_TMP_FORBIDDEN_PREFIX,
    "/private" + defaults.SANDBOX_TMP_FORBIDDEN_PREFIX,
)


def _repo_part(value, what):
    if not isinstance(value, str) or not _REPO_PART.match(value) or set(value) <= {"."}:
        raise ValueError(f"unsafe {what}: {value!r}")
    return value


def _issue(issue):
    if isinstance(issue, bool) or not isinstance(issue, int) or issue < 1:
        raise ValueError(f"bad issue number: {issue!r}")
    return issue


def _step(step):
    if not isinstance(step, str) or len(step) > 64 or not _STEP.match(step):
        raise ValueError(f"bad step id: {step!r}")
    return step


def _attempt(attempt):
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError(f"bad attempt number: {attempt!r}")
    return attempt


def _sha(value):
    if not isinstance(value, str) or not _SHA.match(value):
        raise ValueError(f"bad commit sha: {value!r}")
    return value


def split_repo(repo):
    """"owner/name" → (owner, name); ValueError on anything else."""
    if not isinstance(repo, str) or repo.count("/") != 1:
        raise ValueError(f"repo must be owner/name: {repo!r}")
    owner, name = repo.split("/")
    return _repo_part(owner, "repo owner"), _repo_part(name, "repo name")


def is_forbidden_home(path):
    """True when `path` (absolute) is under the sandbox temp folder /tmp/claude-* (F4)."""
    cands = {os.path.normpath(path)}
    try:
        cands.add(os.path.realpath(path))
    except OSError:
        pass
    for c in cands:
        for pre in _FORBIDDEN_PREFIXES:
            if c.startswith(pre):
                return True
    return False


class EnginePaths:
    """All paths of one Issue run. Pure path arithmetic — no I/O.

    Attributes (absolute strings): engine_home, issue_dir, state, log, engine_log,
    engine_rc, lock, runs, followups_dry_run, security_findings, cache, srt_home, canary_dir. Also: repo ("owner/name"),
    owner, name, issue (int), records, tmp_root.
    """

    def __init__(self, engine_home, repo, issue):
        """`repo` is "owner/name", `issue` an int. Raises ValueError on an unsafe repo name."""
        if not isinstance(engine_home, str) or not os.path.isabs(engine_home):
            raise ValueError(f"engine home must be an absolute path: {engine_home!r}")
        home = os.path.normpath(engine_home)
        if is_forbidden_home(home):
            raise ValueError(f"engine home under the sandbox temp folder (F4): {home}")
        self.owner, self.name = split_repo(repo)
        self.repo = f"{self.owner}/{self.name}"
        self.issue = _issue(issue)
        self.engine_home = home
        self.records = os.path.join(home, "records")
        self.issue_dir = os.path.join(self.records, self.owner, self.name, str(self.issue))
        self.state = os.path.join(self.issue_dir, "state.json")
        self.log = os.path.join(self.issue_dir, "log.jsonl")
        self.engine_log = os.path.join(self.issue_dir, "engine.log")
        self.engine_rc = os.path.join(self.issue_dir, "engine.rc")
        self.lock = os.path.join(self.issue_dir, "lock")
        self.runs = os.path.join(self.issue_dir, "runs")
        # stage 3 (E20, E21): engine-local records, never committed
        self.followups_dry_run = os.path.join(self.issue_dir, defaults.FOLLOWUPS_DRY_RUN_FILE)
        self.security_findings = os.path.join(self.issue_dir, defaults.SECURITY_FINDINGS_FILE)
        self.cache = os.path.join(home, "cache", self.owner, self.name)
        self.tmp_root = os.path.join(home, "tmp", self.owner, self.name, str(self.issue))
        self.srt_home = os.path.join(home, "srt")
        self.canary_dir = os.path.join(home, "canary")

    def step_dir(self, step):
        """runs/<step>/"""
        return os.path.join(self.runs, _step(step))

    def attempt_dir(self, step, attempt):
        """runs/<step>/<attempt>/"""
        return os.path.join(self.step_dir(step), str(_attempt(attempt)))

    def in_dir(self, step, attempt):
        """runs/<step>/<attempt>/in/"""
        return os.path.join(self.attempt_dir(step, attempt), "in")

    def run_tmp(self, step, attempt):
        """tmp/<owner>/<repo>/<issue>/<step>-<attempt>/ — the per-run temp dir roles may write."""
        return os.path.join(self.tmp_root, f"{_step(step)}-{_attempt(attempt)}")

    def attempt_file(self, step, attempt, name):
        """A named file of the attempt folder (brief.json, result.json, facts.json, stream.jsonl, …)."""
        if not isinstance(name, str) or not _FILE.match(name) or name == "in":
            raise ValueError(f"bad attempt file name: {name!r}")
        return os.path.join(self.attempt_dir(step, attempt), name)

    # stage 2 (D13): needs_leader calls are not steps — <issue>/leader/<k>/ with the same files
    @property
    def leader_root(self):
        """<issue>/leader/"""
        return os.path.join(self.issue_dir, LEADER_DIR)

    def leader_dir(self, k):
        """<issue>/leader/<k>/ (k ≥ 1)."""
        return os.path.join(self.leader_root, str(_attempt(k)))

    def leader_in_dir(self, k):
        """<issue>/leader/<k>/in/"""
        return os.path.join(self.leader_dir(k), "in")

    def leader_file(self, k, name):
        """A named file of leader/<k>/ (brief.json, result.json, facts.json, stream.jsonl, …)."""
        if not isinstance(name, str) or not _FILE.match(name) or name == "in":
            raise ValueError(f"bad leader call file name: {name!r}")
        return os.path.join(self.leader_dir(k), name)

    # stage 4 (VB9): what the engine saw when it ran the declared mutations at one HEAD
    def mutations_dir(self, head):
        """<issue>/mutations/<head sha>/"""
        return os.path.join(self.issue_dir, MUTATIONS_DIR, _sha(head))

    def mutation_record(self, head):
        """<issue>/mutations/<head sha>/record.json (schemas/mutation-record)"""
        return os.path.join(self.mutations_dir(head), MUTATION_RECORD)


class SprintPaths:
    """Stage 4: all paths of one sprint (tracking Issue) of one repository. Pure path arithmetic.

    Attributes: repo, owner, name, tracker, engine_home, records, dir, state (sprint.json), log,
    supervisor_log, supervisor_rc, lock (sprints/<tracker>/lock), repo_lock (the repository's
    sprint.lock, H4). `engine_home` makes it usable with the store helpers."""

    def __init__(self, engine_home, repo, tracker):
        base = EnginePaths(engine_home, repo, tracker)      # the same checks
        self.repo, self.owner, self.name, self.tracker = base.repo, base.owner, base.name, base.issue
        self.engine_home, self.records = base.engine_home, base.records
        root = os.path.join(base.records, base.owner, base.name)
        self.dir = os.path.join(root, "sprints", str(self.tracker))
        self.state = os.path.join(self.dir, "sprint.json")
        self.log = os.path.join(self.dir, "log.jsonl")
        self.supervisor_log = os.path.join(self.dir, "supervisor.log")
        self.supervisor_rc = os.path.join(self.dir, "supervisor.rc")
        self.lock = os.path.join(self.dir, "lock")
        self.repo_lock = os.path.join(root, "sprint.lock")


INCIDENTS_DIR = "incidents"
INCIDENT_FILE = "incident.json"
EVIDENCE_DIR = "evidence"
_INCIDENT_SLUG = re.compile(r"\A[a-z0-9][a-z0-9.-]{0,90}-[0-9a-f]{8}\Z")


def is_incident_slug(name):
    """True for a folder name incidents.slug can make (<head>-<8 hex>)."""
    return isinstance(name, str) and bool(_INCIDENT_SLUG.match(name)) and ".." not in name


class IncidentPaths:
    """Readiness R1: <home>/incidents/<slug>/ {incident.json, evidence/}. Pure path arithmetic; `engine_home` makes
    it usable with the store helpers."""

    def __init__(self, engine_home):
        base = EnginePaths(engine_home, "gld/incidents", 1)          # the same home checks
        self.engine_home = base.engine_home
        self.records = base.records
        self.root = os.path.join(base.engine_home, INCIDENTS_DIR)

    def incident_dir(self, slug):
        if not is_incident_slug(slug):
            raise ValueError(f"bad incident slug: {slug!r}")
        return os.path.join(self.root, slug)

    def incident_json(self, slug):
        return os.path.join(self.incident_dir(slug), INCIDENT_FILE)

    def evidence_dir(self, slug):
        return os.path.join(self.incident_dir(slug), EVIDENCE_DIR)


def base_green_record(engine_home, repo, sha, config_sha256):
    """records/<owner>/<repo>/base-green/<base sha>-<first 16 of the config sha256>.json (H12)."""
    p = EnginePaths(engine_home, repo, 1)
    if not isinstance(config_sha256, str) or not _SHA256.match(config_sha256):
        raise ValueError(f"bad config sha256: {config_sha256!r}")
    return os.path.join(p.records, p.owner, p.name, "base-green",
                        f"{_sha(sha)}-{config_sha256[:BASE_GREEN_CONFIG_LEN]}.json")


def init_dir(engine_home, repo):
    """<home>/init/<owner>/<repo>/ — the init draft, decisions and check results (§2.9)."""
    p = EnginePaths(engine_home, repo, 1)
    return os.path.join(p.engine_home, "init", p.owner, p.name)


def heavy_run_lock(engine_home):
    """<home>/heavy-run.lock (H22, flock; the file stays)."""
    return os.path.join(EnginePaths(engine_home, "gld/lock", 1).engine_home, "heavy-run.lock")


def engine_home(environ=None):
    """Resolve the engine home from GLD_ENGINE_HOME or the default; refuse /tmp/claude-* (F4).

    `~` expands with `HOME` of `environ` (default os.environ). The result is absolute and
    resolved through links once (os.path.realpath), so later fsafe checks below it see
    plain directories; ValueError when it is relative or under /tmp/claude-*.
    """
    env = os.environ if environ is None else environ
    raw = env.get(ENV_ENGINE_HOME) or DEFAULT_ENGINE_HOME
    if raw == "~" or raw.startswith("~/"):
        home = env.get("HOME")
        if not home or not os.path.isabs(home):
            raise ValueError("HOME is not set to an absolute path; cannot place the engine home")
        raw = home + raw[1:]
    if not os.path.isabs(raw):
        raise ValueError(f"{ENV_ENGINE_HOME} must be an absolute path: {raw!r}")
    norm = os.path.normpath(raw)
    if is_forbidden_home(norm):
        raise ValueError(f"engine home under the sandbox temp folder (F4): {norm}")
    return os.path.realpath(norm)


def issue_worktree(main_checkout, repo_name, issue):
    """<parent of main checkout>/.gld-<repo>-<issue> (§7.3)."""
    if not isinstance(main_checkout, str) or not os.path.isabs(main_checkout):
        raise ValueError(f"main checkout must be an absolute path: {main_checkout!r}")
    parent = os.path.dirname(os.path.normpath(main_checkout))
    return os.path.join(parent, f".gld-{_repo_part(repo_name, 'repo name')}-{_issue(issue)}")


def specs_dir(issue):
    """docs/specs/<issue> (worktree-relative)."""
    return defaults.SPECS_DIR.replace("{issue}", str(_issue(issue)))


def procedure_path(issue):
    """docs/specs/<issue>/procedure.yaml (worktree-relative)."""
    return specs_dir(issue) + "/procedure.yaml"


def srt_tmpdir(run_id):
    """/tmp/gx-<run_id> — short, so srt's unix socket path fits (F0)."""
    if not isinstance(run_id, str) or not _RUN_ID.match(run_id):
        raise ValueError(f"bad srt run id (1-24 of [A-Za-z0-9_-]): {run_id!r}")
    return defaults.SRT_TMP_PREFIX + run_id
