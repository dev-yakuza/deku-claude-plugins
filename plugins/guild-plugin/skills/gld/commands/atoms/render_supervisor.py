#!/usr/bin/env python3
"""Render the sprint supervisor from its template — one bundled Python invocation.

Replaces the model-mediated "Read the 128KB template, Write it back with 9 substitutions"
step in `sprint/run.md`. The model never reads or writes the template body, which is the
whole point: that round trip cost ~36k input + ~36k output tokens per `/gld sprint run`.

`_bash_rules.md` sanctioned exception 1 ("A single bundled Python invocation") — same shape
as `board_write.py` / `sprint_dag.py` / `persona_migrate.py`.

Design notes and the reasoning behind each guard: design/guild/06-token-reduction.md 묶음 A.

Paths are resolved from __file__, never taken as arguments:
  template    ../../templates/sprint-supervisor.sh
  plugin.json ../../../../.claude-plugin/plugin.json
Both depths hold in the dev checkout and in the installed plugin cache — the two layouts
mirror each other (<root>/.claude-plugin/ + <root>/skills/gld/commands/atoms/).

The output path is ASSEMBLED from --human-repo + --tracker, never accepted as an argument.
A `--out <path>` form would be a hook-free write primitive whose destination the same model
call supplies, i.e. a typo guard dressed as containment. `--out` therefore accepts only the
literal `-` (stdout), which the test harness needs.
"""

import argparse
import json
import os
import re
import shlex
import sys

# `commands.*` values are normalized at init time and MUST NOT contain these
# (`init.md`: "They MUST NOT contain `$(...)`, `&&`, `|`, `;`, or redirections").
# The template `eval`s each element and its own header cites that normalisation as the
# reason that is safe. We re-check here because a legacy install can still carry a
# non-normalised value: `_handoff.md` tells the human to split raw compound commands by
# hand, so nothing guarantees the config was ever migrated.
_METACHAR = re.compile(r"\$\(|`|&&|\|\||[|;<>&\n]")

_TRACKER = re.compile(r"\A[0-9]+\Z")

_TOKENS = (
    "<PLUGIN_VERSION>",
    "<TRACKER>",
    "<ORDER>",
    "<OWNER_REPO>",
    "<DEFAULT_BRANCH>",
    "<CONTAINER>",
    "<HUMAN_REPO>",
    "<DAG_PATH>",
    "<INSTALL_CMDS>",
)

_HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.normpath(
    os.path.join(_HERE, "..", "..", "templates", "sprint-supervisor.sh")
)
PLUGIN_JSON = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", ".claude-plugin", "plugin.json")
)


def die(msg):
    sys.stderr.write("render_supervisor: %s\n" % msg)
    sys.exit(1)


def plugin_version():
    """Read the version from plugin.json. A failure is fatal, never a blank watermark.

    The value lands in a header comment that nothing asserts, so a silent empty string
    would be an unobservable defect on a script that outlives the session that made it.
    """
    try:
        with open(PLUGIN_JSON, encoding="utf-8") as fh:
            v = json.load(fh).get("version")
    except (OSError, ValueError) as exc:
        die("cannot read %s (%s)" % (PLUGIN_JSON, exc))
    if not v:
        die("no 'version' key in %s" % PLUGIN_JSON)
    return v


def array_literal(values):
    """Render a bash array body: shell-quote each element, join with spaces.

    Empty -> "" so the template's `ORDER=()` / `INSTALL_CMDS=()` parse. An empty inline
    substitution used to be a PARSE-time error the template header warns about; producing
    the empty body here is what keeps the empty-queue path (a supported, tested production
    path) working.

    Quoting moves from the model to here. `run.md`'s token table must say the caller passes
    RAW values now — if it still says "shell-quoted", the caller double-quotes and the
    template's `eval "$IC"` looks for a command literally named `yarn install`.
    """
    return " ".join(shlex.quote(v) for v in values)


def main():
    # `--print-template-path` must work on its own — it exists so the test suite can assert
    # that what this script renders is the same file its ~60 structural checks read. Making
    # it wait on the six required scalars would make that assertion unwritable, so it is
    # handled before argparse enforces them.
    if "--print-template-path" in sys.argv[1:]:
        sys.stdout.write(TEMPLATE + "\n")
        return

    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--tracker", required=True)
    ap.add_argument("--owner-repo", required=True)
    ap.add_argument("--default-branch", required=True)
    ap.add_argument("--container", required=True)
    ap.add_argument("--human-repo", required=True)
    ap.add_argument("--dag-path", required=True)
    ap.add_argument("--order", action="append", default=[])
    ap.add_argument("--install-cmd", action="append", default=[])
    ap.add_argument("--out", default=None, help="only the literal '-' (stdout) is accepted")
    ap.add_argument(
        "--print-template-path",
        action="store_true",
        help="print the resolved template path and exit",
    )
    args = ap.parse_args()

    if args.out is not None and args.out != "-":
        die("--out accepts only '-' (stdout); the file path is assembled, not passed")

    if not _TRACKER.match(args.tracker):
        die("--tracker must be digits only, got %r" % args.tracker)

    for cmd in args.install_cmd:
        if _METACHAR.search(cmd):
            die(
                "--install-cmd %r contains shell metacharacters; config.commands values are "
                "normalized at init time and must not contain $(...), &&, |, ;, or "
                "redirections" % cmd
            )

    try:
        with open(TEMPLATE, encoding="utf-8") as fh:
            src = fh.read()
    except OSError as exc:
        die("cannot read template %s (%s)" % (TEMPLATE, exc))

    subs = {
        "<PLUGIN_VERSION>": plugin_version(),
        "<TRACKER>": args.tracker,
        "<ORDER>": array_literal(args.order),
        "<OWNER_REPO>": args.owner_repo,
        "<DEFAULT_BRANCH>": args.default_branch,
        "<CONTAINER>": args.container,
        "<HUMAN_REPO>": args.human_repo,
        "<DAG_PATH>": args.dag_path,
        "<INSTALL_CMDS>": array_literal(args.install_cmd),
    }
    for token, value in subs.items():
        src = src.replace(token, value)

    # Every token must be gone. A survivor means the template gained a placeholder this
    # script does not know about — `ORDER=(<ORDER>)` left literal is a parse error the
    # supervisor would only hit at launch, in the background, with nothing to read.
    leftover = [t for t in _TOKENS if t in src]
    if leftover:
        die("unsubstituted token(s) remain: %s" % ", ".join(leftover))

    if args.out == "-":
        # stdout IS the script here — the confirmation goes to stderr, or it lands inside
        # the rendered bash and the end-to-end sections execute it.
        sys.stdout.write(src)
        # len(src) is CHARACTERS; the template is UTF-8 with multibyte prose, so the two
        # differ by ~4KB. Report what actually lands on the stream.
        sys.stderr.write(
            "render_supervisor: %d bytes to stdout\n" % len(src.encode("utf-8"))
        )
        return

    out = os.path.join(
        args.human_repo, ".claude", "guild", ".gld-sprint-%s.sh" % args.tracker
    )
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(src)
        os.chmod(out, 0o755)
    except OSError as exc:
        die("cannot write %s (%s)" % (out, exc))

    size = os.path.getsize(out)
    if size == 0:
        die("wrote 0 bytes to %s" % out)
    # `run.md`'s render guard reads this line. It is the only signal it gets — there is no
    # allowlisted Bash primitive (`test -s`, `wc -c`) it could use to check the file itself.
    sys.stderr.write("render_supervisor: wrote %s (%d bytes)\n" % (out, size))


if __name__ == "__main__":
    main()
