#!/usr/bin/env -S python3 -I
"""Plugin check script `verify-gate` (design §2.1, §7.11, F5) — U15 (script) / U9 (engine side).

Runs the 0.98.7 commit gate over the recorded base range without changing the gate:
the engine (outside srt) builds the temp tree — `worktree add --detach <tmp> <base SHA>`
+ `read-tree -m -u <base SHA> <HEAD SHA>` (gitops.temp_tree_for_gate) — then runs this
script under srt with writes allowed only in the temp tree, cwd = the temp tree:
  `python3 -I <plugin root>/skills/gld/engine/scripts/verify_gate.py --issue <N>`
which runs the plugin-install-path `skills/gld/gates/gate_precommit.py --git-hook`
and returns its verdict (0 pass / 1 blocked). The engine throws the temp tree away.
Only after the step's control-file check passed (the gate imports HEAD-side local scripts).

Exit codes (the plugin check-script contract, interfaces.md §2.7):
  0  the gate allowed the range (its warnings are printed, one per line)
  1  the gate blocked it (its reasons are printed on stdout, one per line)
  2  not judged: bad arguments, cwd is not a git work tree, the gate file is missing,
     the gate timed out / died / exited with another code, or the gate says it hit an
     internal error and allowed the commit (the gate itself is fail-open on a crash; a
     verification that could not run must never read as a pass, so this wrapper is not).
The gate writes its own findings file into the temp tree; this script writes nothing.
"""

import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.realpath(__file__))
ENGINE_DIR = os.path.dirname(SCRIPTS_DIR)
GATE = os.path.join(os.path.dirname(ENGINE_DIR), "gates", "gate_precommit.py")
TIMEOUT_S = 900
# gate_precommit.py's fail-open crash line (module `__main__` handler) — treated as not judged.
CRASH_MARKER = "internal error, allowing commit"

EXIT_PASS, EXIT_FAIL, EXIT_CANNOT_JUDGE = 0, 1, 2


def parse_args(argv):
    if len(argv) == 2 and argv[0] == "--issue" and argv[1].isascii() and argv[1].isdigit() and int(argv[1]) >= 1:
        return int(argv[1])
    return None


def _lines(text):
    return [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]


def run_gate(gate, cwd):
    """(returncode, stdout, stderr) of `gate --git-hook` in `cwd`; returncode None on a timeout."""
    try:
        p = subprocess.run([sys.executable, "-I", gate, "--git-hook"], cwd=cwd, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, "", ""
    return (p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))


def inside_work_tree(cwd):
    try:
        p = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0 and p.stdout.strip() == b"true"


def judge(returncode, stdout, stderr):
    """Map the gate's result to (exit code, stdout lines)."""
    out = _lines(stdout) + _lines(stderr)
    if returncode is None:
        return EXIT_CANNOT_JUDGE, [f"verify-gate: the gate did not finish within {TIMEOUT_S} s — NOT judged"]
    if CRASH_MARKER in (stderr or ""):
        return EXIT_CANNOT_JUDGE, ["verify-gate: the gate hit an internal error and allowed the commit — NOT judged"] + out
    if returncode == 0:
        return EXIT_PASS, out or ["ok: the gate allowed the range"]
    if returncode == 1:
        return EXIT_FAIL, out or ["verify-gate: the gate blocked the range (no message)"]
    return EXIT_CANNOT_JUDGE, [f"verify-gate: the gate exited with code {returncode} — NOT judged"] + out


def main(argv):
    if parse_args(argv) is None:
        sys.stderr.write("usage: verify_gate.py --issue <N>\n")
        return EXIT_CANNOT_JUDGE
    cwd = os.getcwd()
    if not os.path.isfile(GATE):
        sys.stdout.write(f"verify-gate: the gate script is missing ({GATE}) — NOT judged\n")
        return EXIT_CANNOT_JUDGE
    if not inside_work_tree(cwd):
        sys.stdout.write("verify-gate: the working directory is not a git work tree — NOT judged\n")
        return EXIT_CANNOT_JUDGE
    try:
        code, lines = judge(*run_gate(GATE, cwd))
    except Exception as e:  # a crash is "cannot judge", never a pass
        sys.stderr.write(f"verify-gate: internal error — NOT judged ({type(e).__name__}: {e})\n")
        return EXIT_CANNOT_JUDGE
    for line in lines:
        sys.stdout.write(line + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
