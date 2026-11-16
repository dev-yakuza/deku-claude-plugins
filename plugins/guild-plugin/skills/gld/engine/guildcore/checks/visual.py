"""guildcore.checks.visual — the H§L baseline ledger (`<!-- guild:visual-baselines -->`), as code.

    <!-- guild:visual-baselines -->
    run: <yes|no>
    C|M|D|P <path> — <reason>
    A <path> — replaces <old path> — <reason> | A <path> — case: <row> | A <path> — <reason>
    R <old path> -> <new path> — moved, unchanged
    none
    <!-- /guild:visual-baselines -->

The block is written by execute and copied VERBATIM into test:output (L.3) — `block_text` returns
the exact bytes (markers included) so the copy is byte-identical. Downstream readers use only
these ASCII rows, never a localized line.
"""

import fnmatch
import re

from guildcore.records import markers

NAME = "visual-baselines"
SAFETY_NET = "safety-net-evidence"
ROW_RE = re.compile(r"^(C|M|D|P|A|R) (\S.*?)(?: — (.*))?$")


class Row(object):
    def __init__(self, kind, path, rest, line):
        self.kind, self.path, self.rest, self.line = kind, path, rest or "", line
        self.replaces = self.rest.startswith("replaces ")
        self.case = self.rest.startswith("case: ")


class Ledger(object):
    def __init__(self, text):
        self.text = text
        self.run = None
        self.rows = []
        for ln in (text or "").split("\n"):
            c = markers.clean(ln)
            if c.startswith("run: "):
                self.run = c[5:].strip()
            m = ROW_RE.match(c)
            if m:
                path = m.group(2)
                if m.group(1) == "R" and " -> " in path:
                    path = path.split(" -> ", 1)[1]
                self.rows.append(Row(m.group(1), path, m.group(3), c))

    def of(self, *kinds):
        return [r for r in self.rows if r.kind in kinds]

    @property
    def pending(self):
        return [r.path for r in self.of("P")]


def block_text(body, name=NAME):
    """The verbatim marker block (markers included) inside `body`, or None. A block that is
    not whole-line delimited is not a block (markers.marker_span rule)."""
    try:
        sp = markers.marker_span(body or "", name)
    except ValueError:
        return None
    return (body or "")[sp[0]:sp[1]] if sp else None


def visual_ledger(body):
    b = block_text(body)
    return Ledger(b) if b is not None else None


def visual_available(cfg):
    """L.1 VISUAL_AVAILABLE: runnable ∧ (vrt non-null ∨ baselines non-empty)."""
    v = cfg.get("visual") or {}
    return v.get("runnable") is True and (bool((cfg.get("commands") or {}).get("vrt")) or bool(v.get("baselines")))


def ledger_expected(cfg):
    """The ledger is written (and must be copied) unless the repo has none of visual.baselines,
    visual.tests, visual.config_files and commands.vrt is null (test.md Step 2 (c))."""
    v = cfg.get("visual") or {}
    return bool(v.get("baselines") or v.get("tests") or v.get("config_files") or
                (cfg.get("commands") or {}).get("vrt"))


def visual_run(cfg, visual_cases, ledger):
    """T0.2: VISUAL_RUN = runnable ∧ vrt non-null ∧ (VISUAL_CASES ∨ ledger `run: yes`)."""
    v = cfg.get("visual") or {}
    return v.get("runnable") is True and bool((cfg.get("commands") or {}).get("vrt")) and \
        (visual_cases or (ledger is not None and ledger.run == "yes"))


GOLDEN_FAIL_RES = (
    re.compile(r'Golden "([^"]+)": Pixel test failed'),          # flutter matchesGoldenFile
    re.compile(r"Could not be compared against non-existent file: \"([^\"]+)\""),
    re.compile(r"Screenshot comparison failed[^\n]*?([\w./-]+\.png)"),  # vitest/playwright
    re.compile(r"Expected an image[^\n]*?([\w./-]+\.png)"),
)


def failing_images(raw):
    out = []
    for rx in GOLDEN_FAIL_RES:
        for m in rx.finditer(raw or ""):
            if m.group(1) not in out:
                out.append(m.group(1))
    return out


def _match(path, pending):
    for p in pending:
        if path == p or path.endswith("/" + p) or p.endswith("/" + path) or fnmatch.fnmatch(path, p):
            return True
    return False


def confined_to_pending(images, ledger):
    """T3.3: every failing image is a ledger `P` row (non-empty failures only)."""
    if not images or ledger is None or not ledger.pending:
        return False
    return all(_match(i, ledger.pending) for i in images)


def checklist_items(ledger, visual_env, visual_cases, language="ko"):
    """qa Step 2.5's code-derived items from the ledger copied into test:output."""
    if ledger is None:
        return []
    out = []
    p = ledger.of("P")
    if p:
        out.append("%s 에서 재생성 필요한 기준 이미지 %d건 (PR 시각 변경 섹션) — 재생성 후 CI golden 통과 확인"
                   % (visual_env or "visual.env", len(p)))
    changed = ledger.of("C", "M", "D") + [r for r in ledger.of("A") if r.replaces] + \
        ([r for r in ledger.of("A") if not r.case and not r.replaces] if visual_cases else [])
    if changed:
        out.append("PR 시각 변경 섹션의 비교 설정 변경·갱신·삭제·재생성 %d건이 의도한 것인지 확인" % len(changed))
    return out


def env_mismatch(host, visual_env):
    """L.5 code pre-filter: the run host (e.g. `macOS arm64`) is not named by `visual.env`
    (OS and CPU architecture both must appear). Unknown host/env → None (judgment)."""
    if not host or not visual_env:
        return None
    env = visual_env.lower()
    toks = [t.lower() for t in host.split()]
    os_names = {"macos": ("macos", "darwin", "mac"), "linux": ("linux", "ubuntu", "docker"),
                "windows": ("windows",)}
    arch = {"arm64": ("arm64", "aarch64", "apple silicon"), "amd64": ("amd64", "x86_64", "x64")}
    ok_os = any(any(a in env for a in os_names.get(t, (t,))) for t in toks if t in os_names)
    ok_arch = any(any(a in env for a in arch.get(t, (t,))) for t in toks if t in arch)
    return not (ok_os and ok_arch)
