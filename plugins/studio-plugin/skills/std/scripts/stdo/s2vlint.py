"""s2v lint and s2v check, run by Studio's check scripts themselves (m1-plan §4.1 v4 R3 · §7.3 v3 N6, D-M1-21).

Their pass is never the agent's word: the check script runs `lint` (script · cast) or `check` (board) with this
machine's s2v and folds the exit code and the diagnostics s2v prints on stderr (`<file>[:<line>] <severity> [<code>]
<message>`) into its result. Every error fails, and so do the warnings Studio treats as failures — over maxDuration,
targetDuration ±15 % (s2v `lint-budget.ts`: warnings there, exit 0) and subtitles that do not fit."""

import os
import re
import subprocess

DIAG = re.compile(r"^(?P<where>.+?) (?P<severity>error|warning) \[(?P<code>[\w-]+)\] (?P<message>.*)$")
# s2v's warning codes that fail a Studio check (fixed against real s2v by the --full format comparison, §12.3)
FAIL_WARNINGS = ("max-duration", "target-duration", "subtitle-budget", "subtitle-overflow")
# Latin words left in Korean or Japanese narration: the TTS reads them as English (s2v lint-budget.ts) — a failure for
# those languages (M1b review Y8)
FAIL_WARNINGS_BY_LANG = {"ko": ("unread-word",), "ja": ("unread-word",)}
LANG_RE = re.compile(r"^lang:\s*[\"']?([A-Za-z-]+)", re.M)
MODES = ("lint", "check")


class Result(object):
    def __init__(self, mode, code, diagnostics, stderr_tail, lang=None, fail_unread=True):
        self.mode, self.code, self.diagnostics, self.stderr_tail = mode, code, diagnostics, stderr_tail
        self.lang, self.fail_unread = lang, fail_unread

    @property
    def failures(self):
        fail = FAIL_WARNINGS + (FAIL_WARNINGS_BY_LANG.get((self.lang or "").split("-")[0], ())
                                if self.fail_unread else ())
        return [d for d in self.diagnostics if d["severity"] == "error" or d["code"] in fail]

    @property
    def passed(self):
        return self.code == 0 and not self.failures

    def details(self):
        return {"mode": self.mode, "exit": self.code, "lang": self.lang, "diagnostics": self.diagnostics,
                "failures": [d["code"] for d in self.failures], "stderr_tail": self.stderr_tail}


def parse(stderr):
    out = []
    for line in stderr.splitlines():
        m = DIAG.match(line.rstrip("\r"))
        if m:
            out.append({"severity": m.group("severity"), "code": m.group("code"), "message": m.group("message")})
    return out


def script_lang(script):
    """The frontmatter `lang` of a script (None when it cannot be read)."""
    try:
        with open(script, encoding="utf-8") as f:
            head = f.read(8192)
    except OSError:
        return None
    if not head.startswith("---"):
        return None
    end = head.find("\n---", 3)
    m = LANG_RE.search(head[:end if end > 0 else len(head)])
    return m.group(1) if m else None


def run(s2v_path, script, mode="lint", env=None, runner=None, lang=None, fail_unread=True):
    """Run `s2v <mode> <script>` (no lock: neither synthesizes) and judge it (`lang`: the script's, read from its
    frontmatter when not given). `fail_unread=False`: `unread-word` is information only (the script stage; it fails
    from cast on — M1b re-review Z3, pinned by M1e/M1f)."""
    if mode not in MODES:
        raise ValueError("mode is lint or check: %r" % (mode,))
    argv = ["node", os.path.join(s2v_path, "packages", "cli", "dist", "main.js"), mode, script]
    if runner is None:
        try:
            p = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=600)
            code, err = p.returncode, p.stderr
        except (OSError, subprocess.TimeoutExpired) as e:
            code, err = 127, "cannot run s2v %s: %s" % (mode, e)
    else:
        code, err = runner(argv, env)
    return Result(mode, code, parse(err), err.strip().splitlines()[-20:], lang or script_lang(script), fail_unread)
