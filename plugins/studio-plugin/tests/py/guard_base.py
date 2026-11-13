"""Shared setup for the guard scanner tests (M0d-1a)."""

import os
import stat
import time

from helpers import StudioTestCase
from stdo import guard
from stdo.guard import snapshot as snapmod
from stdo.guard.terms import Terms
import snapref


def _load_both(env, now=None, _load=snapmod.load):
    """fix20: a snapshot the tests load is read by both guards from the same files (they are often removed right
    after): the 0.0.26 guard's reading rides along as `legacy_view` (backstop.decide hands it to the 0.0.26 guard
    when a test injects the snapshot). fix-0029 §1.7: every load is also compared with the 0.1.0 parse (snapref.py),
    so every snapshot text the tests build checks the memos and the prefilter. `_load` (the last default) is the
    original `snapshot.load`."""
    now = time.time() if now is None else now
    out = _load(env, now=now)
    check_parity(out, snapref.load(env, now=now))
    if out[0] is not None and getattr(out[0], "legacy_view", None) is None:
        from stdo.guard.legacy import snapshot as legacy_snapshot
        out[0].legacy_view = legacy_snapshot.load(env, now=now)
    return out


def variant_fields(v):
    """The named fields of one Variant (fix-0029 §1.7), comparable across the two modules."""
    return {"aliases": dict(v.aliases), "global_aliases": sorted(v.global_aliases),
            "suffix_aliases": sorted(v.suffix_aliases), "user_functions": sorted(v.user_functions),
            "delegated": sorted(v.delegated), "options": dict(v.options), "explicit": dict(v.explicit),
            "path": v.path, "notes": list(v.notes), "func_offsets": dict(v.func_offsets), "text": v.text,
            "weight": v.weight, "extra_paths": list(v.extra_paths)}


def load_fields(out):
    """The named fields of a load's (Snapshot | None, notes): every variant's and the merged Snapshot's."""
    snap, notes = out
    if snap is None:
        return None, list(notes)
    return {"variants": [variant_fields(v) for v in snap.variants], "files": list(snap.files),
            "notes": list(snap.notes), "partial": snap.partial, "plain": dict(snap.plain),
            "alternatives": {k: list(x) for k, x in snap.alternatives.items()}, "counts": snap.counts,
            "total": snap.total, "global_aliases": sorted(snap.global_aliases),
            "suffix_aliases": sorted(snap.suffix_aliases), "user_functions": sorted(snap.user_functions),
            "delegated": sorted(snap.delegated), "options": dict(snap.options),
            "option_conflicts": sorted(snap.option_conflicts), "paths": list(snap.paths)}, list(notes)


class ParityError(AssertionError):
    pass


def check_parity(out, ref):
    a, b = load_fields(out), load_fields(ref)
    if a != b:
        raise ParityError("snapshot.load differs from the 0.1.0 parse (snapref.py): %r != %r" % (
            str(a)[:400], str(b)[:400]))


snapmod.load = _load_both

TERMS = Terms(words=["s2v", "state.py", "lock.py", "check_commit.py", "STUDIO_SANDBOX", "STUDIO_HOME"],
              paths=["studio", ".claude/studio"], names=["state.json", "verify.json", "picks.json"])

CLAUDE_SECTIONS = '''# Check for rg availability
if ! hash rg 2>/dev/null && ! typeset -f rg >/dev/null 2>&1; then
  function rg {
  local _cc_bin="${CLAUDE_CODE_EXECPATH:-}"
  [[ -x $_cc_bin ]] || _cc_bin=/opt/fake/bin/claude
  if [[ ! -x $_cc_bin ]]; then command rg ${1+"$@"}; return; fi
  if [[ -n ${ZSH_VERSION:-} ]]; then
    ARGV0=rg "$_cc_bin" ${1+"$@"}
  else
    (exec -a rg "$_cc_bin" ${1+"$@"})
  fi
}
fi
# Shadow find/grep with embedded bfs/ugrep
unalias find 2>/dev/null || true
unalias grep 2>/dev/null || true
function find {
  local _cc_bin="${CLAUDE_CODE_EXECPATH:-}"
  [[ -x $_cc_bin ]] || _cc_bin=/opt/fake/bin/claude
  if [[ ! -x $_cc_bin ]]; then command find ${1+"$@"}; return; fi
  if [[ -n ${ZSH_VERSION:-} ]]; then
    ARGV0=bfs "$_cc_bin" -S dfs -regextype findutils-default ${1+"$@"}
  else
    (exec -a bfs "$_cc_bin" -S dfs -regextype findutils-default ${1+"$@"})
  fi
}
function grep {
  local _cc_a
  for _cc_a in ${1+"$@"}; do
    case "$_cc_a" in -*-filter*|-*-pager*) echo "grep: refused" >&2; return 2 ;; esac
  done
  local _cc_bin="${CLAUDE_CODE_EXECPATH:-}"
  if [[ ! -x $_cc_bin ]]; then command grep ${1+"$@"}; return; fi
  ARGV0=ugrep "$_cc_bin" -G --ignore-files --hidden -I ${1+"$@"}
}
# Shadow pkill to refuse patterns matching the CLI process
unalias pkill 2>/dev/null || true
function pkill {
  if [ -n "${CLAUDE_PID:-}" ] && [ -r "/proc/${CLAUDE_PID}/comm" ]; then
    local _cc_a
    for _cc_a in ${1+"$@"}; do
      case "$_cc_a" in -*) ;; *) : ;; esac
    done
  fi
  command pkill ${1+"$@"}
}
'''

DEFAULT_ALIASES = [("g", "git"), ("ga", "'git add'"), ("gc", "'git commit --verbose'"), ("grhh", "'git reset --hard'"),
                   ("gclean", "'git clean --interactive -d'"), ("md", "'mkdir -p'"), ("_", "'sudo '"),
                   ("-", "'cd -'"), ("...", "../.."), ("ll", "'ls -l'"), ("ls", "'ls -G'")]
DEFAULT_FUNCS = '''take () {
	mkdir -p $@ && cd ${@:$#}
}
'''


def snapshot_text(aliases=None, functions=DEFAULT_FUNCS, options=("autocd", "autopushd", "interactivecomments"),
                  unsetopts=(), claude=True, path="/usr/bin:/bin", extra_alias_lines=()):
    aliases = DEFAULT_ALIASES if aliases is None else aliases
    out = ["# Snapshot file", "# Unset all aliases to avoid conflicts with functions", "unalias -a 2>/dev/null || true",
           "# Functions", functions.rstrip("\n"), "# Shell Options"]
    out += ["setopt %s" % o for o in options] + ["unsetopt %s" % o for o in unsetopts]
    out.append("# Aliases")
    out += ["alias -- %s=%s" % (n, v) for n, v in aliases] + list(extra_alias_lines)
    text = "\n".join(out) + "\n"
    if claude:
        text += CLAUDE_SECTIONS
    if path is not None:
        text += "export PATH='%s'\n" % path
    return text


PERF_FUNC = '''f_%(n)d () {
	local _x="${1:-.}" _n=%(n)d _i
	if [[ -z $_x ]]
	then
		print -u2 "f_%(n)d: no folder given and no default folder" && return 1
	fi
	for _i in 1 2 3
	do
		print -r -- "$_x:$_i: checking the folder and its entries for the summary" > /dev/null
	done
	case $_x in
		(-*) echo "option given where a folder was expected: $_x" >&2 ;;
		(*) : ;;
	esac
	command ls -l --color=never "$_x" 2> /dev/null | head -n $_n | sed -e "s/^/  /"
	local _y="${_x%%/*}"
	[[ -d $_y ]] && cd "$_y"
	export F_LAST="${_y:-none}" F_LAST_TIME="$(date +%%s)"
	print -r -- "${#_x}" > /dev/null
	while read -r _i
	do
		[[ $_i == q ]] && break || print -r -- "line: $_i" > /dev/null
	done < /dev/null
	return 0
}'''


def perf_snapshot_text(i, path="/usr/bin:/bin", functions=400, aliases=250):
    """fix-0029 §1.6: one of the snapshot files PerfSnapshots generates, shaped like a real one (~280 KB: ~10,500
    typeset -f lines in 400 functions, about a quarter of them with a `{`; 250 alias lines with mixed quoting; Claude
    Code's sections and PATH). File `i` differs from the others in one function-body line only: the texts differ, the
    variant key is the same (one variant)."""
    funcs = [PERF_FUNC % {"n": n} for n in range(functions)]
    funcs[0] = funcs[0].replace("\tlocal ", "\t: file %d\n\tlocal " % i, 1)
    al = []
    for k in range(aliases):
        if k % 4 == 0:
            al.append(("a%d" % k, "'git log --oneline -n %d'" % k))
        elif k % 4 == 1:
            al.append(("b%d" % k, '"ls -l %d"' % k))
        elif k % 4 == 2:
            al.append(("c%d" % k, "grep\\ -n\\ x%d" % k))
        else:
            al.append(("d%d" % k, "'echo '\\''x%d'\\'''" % k))
    return snapshot_text(aliases=al, functions="\n".join(funcs) + "\n", path=path)


class GuardCase(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp, "w")
        os.makedirs(self.root)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for name in ("git", "rm", "cp", "mv", "ls", "cat", "echo", "printf", "touch", "mkdir", "python3", "node",
                     "yarn", "npx", "tsx", "sed", "awk", "xargs", "find", "grep", "tee", "env", "sudo", "nohup",
                     "timeout", "bash", "sh", "zsh", "perl", "make", "tar", "rsync", "jq", "head", "pwd", "true",
                     "php", "ruby", "osascript", "deno", "bun", "bunx", "npm", "pnpm", "parallel", "watch", "curl",
                     "diff", "test", "nice", "stdbuf", "caffeinate", "dirname", "which", "python", "python3.12",
                     "gawk", "printenv"):
            self.exe(name)
        self.env = dict(os.environ)
        self.env["PATH"] = self.bin
        for k in ("CDPATH", "OLDPWD"):
            self.env.pop(k, None)
        self.snapshot = None
        self.snapshot_notes = ()

    def exe(self, name, target=None, content="#!/bin/sh\nexit 0\n"):
        p = os.path.join(self.bin, name)
        if target:
            os.symlink(target, p)
        else:
            with open(p, "w") as f:
                f.write(content)
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return p

    def mk(self, *rel, **kw):
        p = os.path.join(self.root, *rel)
        if kw.get("file"):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(kw.get("text", ""))
        else:
            os.makedirs(p, exist_ok=True)
        return p

    def use_snapshots(self, *texts, ages=None, names=None):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        now = time.time()
        for i, t in enumerate(texts):
            n = names[i] if names else "snapshot-zsh-%d-x%03d.sh" % (1792000000000 + i, i)
            p = os.path.join(d, n)
            with open(p, "w") as f:
                f.write(t)
            age = ages[i] if ages else 60 * (i + 1)
            os.utime(p, (now - age, now - age))
        self.snapshot, self.snapshot_notes = snapmod.load(self.env, now=now)
        return self.snapshot

    def scan(self, command, cwd=None, **kw):
        kw.setdefault("snapshot", self.snapshot)
        kw.setdefault("snapshot_notes", self.snapshot_notes)
        kw.setdefault("terms", TERMS)
        return guard.scan(command, cwd or self.root, self.env, **kw)

    def ok(self, command, cwd=None, **kw):
        r = self.scan(command, cwd, **kw)
        self.assertEqual(r.status, "ok", "%s: %s %s" % (command, r.status, r.reason))
        return r

    @staticmethod
    def by_prog(r, prog):
        # the primary reading: not the copies judged in a known folder the shell may still be in (review 10 B1)
        return [c for c in r.commands if c.prog == prog and "lost-folder" not in (c.ctx or ())]

    def one(self, r, prog):
        cs = self.by_prog(r, prog)
        self.assertEqual(len(cs), 1, "%s: %r" % (prog, [c.argv for c in r.commands]))
        return cs[0]

    @staticmethod
    def kinds(r):
        return [o.kind for o in r.opaque]
