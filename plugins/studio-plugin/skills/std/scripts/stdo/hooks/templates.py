"""The files hooks.py writes (m0e-plan §3.2, §4). Kept in code (not templates/): the copy of the scripts in
a repository must rebuild them to check they are intact without the plugin. Every file carries MARK — the
guard protects a hook file only when it carries it (m0d1b-plan §5.1)."""

import re

MARK = "studio:hook"
VERSION = 1
RUNNER_VERSION = 2  # 2 (M0f): closed when HEAD has Studio's check script but the work tree does not; .husky/pre-commit
HUSKY_FILE = ".husky/pre-commit"
BLOCK_BEGIN = "# >>> studio:hook >>>"
BLOCK_END = "# <<< studio:hook <<<"
CHAINED = "pre-commit.studio-chained"
RUNNER_REL = "studio/pre-commit"  # under the git common dir


def ere(text):
    """Escape for a POSIX extended regular expression."""
    return "".join("\\" + c if c in ".[]()*+?{}|^$\\" else c for c in text)


def _sq(text):
    return "'" + text.replace("'", "'\\''") + "'"


def runner(roots):
    """The per-clone runner (git common dir): fast checks in sh, Python only for Studio paths."""
    # lines are "<status>\t<path>"; a leak is any status but D (unstaging or deleting a local file is fine)
    local_re = "^[^D]\t(" + "|".join([ere(".claude/studio/local/")] + [ere(r + "/local/") for r in roots]) + ")"
    studio_re = "^.\t(" + "|".join([ere(".claude/studio/"), ere(".claude/agents/std-"), ere(".gitignore") + "$",
                                   ere(HUSKY_FILE) + "$"] + [ere(r + "/") for r in roots]) + ")"
    return """#!/bin/sh
# %(mark)s v%(rver)d — Studio's pre-commit runner (written by hooks.py; untracked, one per clone)
# Studio roots: %(roots)s
# git runs a hook from the top of the work tree (husky and lefthook too)
for t in tr awk grep cut sed head; do
  command -v "$t" >/dev/null 2>&1 || { echo "Studio pre-commit: refused — '$t' is not on PATH; the check cannot run." >&2; exit 1; }
done
staged() {
  git -c core.quotePath=false diff --cached --name-status -z --no-renames --no-ext-diff "$1" -- 2>/dev/null |
    tr '\\000' '\\n' | awk 'NR %% 2 == 1 { s = $0; next } { print s "\\t" $0 }'
}
list=$(staged HEAD)
if [ -z "$list" ] && ! git rev-parse -q --verify 'HEAD^{commit}' >/dev/null 2>&1; then
  list=$(staged "$(git hash-object -t tree --stdin </dev/null)")  # the first commit
fi
[ -n "$list" ] || exit 0
icase=$(git config --bool core.ignorecase 2>/dev/null)
studio_match() {
  if [ "$icase" = true ]; then printf '%%s\\n' "$list" | grep -iE "$1"; else printf '%%s\\n' "$list" | grep -E "$1"; fi
}
bad=$(studio_match %(local_re)s)
if [ -n "$bad" ]; then
  echo "Studio pre-commit: refused — machine-only Studio files (local/) are staged to be added or changed; they are never committed:" >&2
  printf '%%s\\n' "$bad" | cut -f2- | head -n 10 | sed 's/^/  - /' >&2
  echo "  Unstage them: git restore --staged -- <path>" >&2
  echo "Do not bypass this check (--no-verify, HUSKY=0, LEFTHOOK=0, removing session markers): stop and ask the user (INV9)." >&2
  exit 1
fi
[ -n "$(studio_match %(studio_re)s)" ] || exit 0
cc=.claude/studio/scripts/check_commit.py
if [ ! -f "$cc" ]; then
  # a branch that never had the harness: nothing to check; HEAD has it but the work tree not: closed
  git cat-file -e "HEAD:$cc" 2>/dev/null || exit 0
  echo "Studio pre-commit: refused — Studio's check script ($cc) is in HEAD but not in the work tree." >&2
  if [ "$(git config --bool core.sparseCheckout 2>/dev/null)" = true ]; then
    echo "  This clone uses sparse-checkout: include Studio's folder (git sparse-checkout add .claude/studio)." >&2
  fi
  echo "  Taking Studio out of the repository is the person's removal procedure, committed in a terminal." >&2
  echo "Do not bypass this check (--no-verify, HUSKY=0, LEFTHOOK=0, removing session markers): stop and ask the user (INV9)." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Studio pre-commit: refused — python3 (3.9 or newer) is needed to check the staged Studio files." >&2
  exit 1
fi
exec python3 -B "$cc" --staged
""" % {"mark": MARK, "rver": RUNNER_VERSION, "roots": " ".join(roots), "local_re": _sq(local_re),
       "studio_re": _sq(studio_re)}


def shim():
    """The plain-git hook: the previous hook first (its failure stands), then the runner."""
    return """#!/bin/sh
# %(mark)s v%(ver)d — Studio's pre-commit shim (written by hooks.py; runs the previous hook first)
hooks_dir=$(cd "$(dirname "$0")" && pwd)
if [ -x "$hooks_dir/%(chained)s" ]; then
  "$hooks_dir/%(chained)s" "$@" || exit $?
fi
runner="$(git rev-parse --git-common-dir)/%(runner)s"
if [ -f "$runner" ]; then exec sh "$runner" "$@"; fi
echo "Studio pre-commit: Studio's hook runner is missing ($runner)." >&2
echo "  Reinstall it: python3 .claude/studio/scripts/hooks.py install   (or /std init --hooks)" >&2
echo "  Or take Studio's hook out of this clone: rm \\"$hooks_dir/pre-commit\\"" >&2
echo "  and, when it exists, put the previous hook back: mv \\"$hooks_dir/%(chained)s\\" \\"$hooks_dir/pre-commit\\"" >&2
exit 1
""" % {"mark": MARK, "ver": VERSION, "chained": CHAINED, "runner": RUNNER_REL}


def husky_block():
    """For the tracked .husky/pre-commit (husky runs it with `sh -e`: an `if`, not `[ … ] && …`)."""
    return """%(begin)s v%(ver)d (runs only in clones where Studio is set up)
studio_hook="$(git rev-parse --git-common-dir)/%(runner)s"
if [ -f "$studio_hook" ]; then sh "$studio_hook" || exit $?; fi
%(end)s
""" % {"begin": BLOCK_BEGIN, "end": BLOCK_END, "ver": VERSION, "runner": RUNNER_REL}


def lefthook_block():
    return """%(begin)s v%(ver)d
pre-commit:
  commands:
    studio-check:
      run: sh "$(git rev-parse --git-common-dir)/%(runner)s"
%(end)s
""" % {"begin": BLOCK_BEGIN, "end": BLOCK_END, "ver": VERSION, "runner": RUNNER_REL}


def find_block(text):
    """(start, end) character offsets of the studio:hook block (end exclusive, incl. its newline), or None;
    ValueError when the markers are unpaired or repeated."""
    lines = text.splitlines(True)
    pos, starts, ends = 0, [], []
    for l in lines:
        if l.startswith(BLOCK_BEGIN):
            starts.append(pos)
        if l.startswith(BLOCK_END):
            ends.append(pos + len(l))
        pos += len(l)
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or ends[0] <= starts[0]:
        raise ValueError("studio:hook block markers are unpaired or repeated")
    return starts[0], ends[0]


def put_block(text, block):
    sp = find_block(text)
    if sp is None:
        if text and not text.endswith("\n"):
            text += "\n"
        return text + block
    return text[:sp[0]] + block + text[sp[1]:]


STOP_RE = re.compile(r"^(exit|return|exec)\b")  # column 0 only: an indented exit sits inside an if/case/function


def stops_before_block(text):
    """Standalone exit/return/exec lines before the studio:hook block (the hook would end before it)."""
    n = 0
    for l in (text or "").splitlines():
        if l.startswith(BLOCK_BEGIN):
            break
        if STOP_RE.match(l):
            n += 1
    return n
