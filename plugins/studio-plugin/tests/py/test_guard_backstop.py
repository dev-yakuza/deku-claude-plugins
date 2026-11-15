"""fix20: the 0.0.26 guard as a backstop (guard/backstop.py, guard/legacy). 0.1.4: this guard (G1) walks on after a
`source` / `.` (the file read in this shell, or its effects unknown); the frozen 0.0.26 guard judges only a call with a
source, after effects G1 cannot read, or that G1 stopped early (class S / L: anything either refuses is refused, and
the 0.0.26 guard's finish runs) — every other call is G1's alone (class N; the frozen guard is not imported). Real git
only in temporary repositories; the 0.0.26 tree for test_sourced_approval_as_0026 is rebuilt from guard/legacy (the
structure test proves the copy is the 0.0.26 code)."""

import json
import os
import re
import shutil
import subprocess
import sys
import types

import helpers
import transcripts as TR
from guard_base import snapshot_text
from stdo.guard import backstop, judge, limits
from stdo.guard import snapshot as snapmod
from test_guard_judge import ALIASES, MUST_DENY, MUST_PASS, JudgeCase

H = "3f2a9c0d1e4b"
APPROVE = "python3 .claude/studio/scripts/state.py approve v 1 --expect %s" % H
GUARD = os.path.join(helpers.SCRIPTS, "guard.py")

# Parity corpus: rows of the review corpora (rounds 18-20: every B20-1..4 table row, their no-source controls, and
# samples of each set, 0.0.26-refused and -passed), the C20-1 rows, the R1 / R2 examples of 0.0.26's guard-limits,
# the routes to a source, and the 0.0.26 false refusals that come back. {R}: the repository. MUST_DENY / MUST_PASS
# samples are added in test_parity.
BACKSTOP_PARITY = [
    "command cd studio/videos/v; f(){ cd {R}/studio/videos/v; }; source {R}/e.sh; cd {R}/studio/videos/v; f; rm -rf work",
    "command cd studio/videos/v; f(){ cd {R}/studio/videos/v; }; source {R}/e.sh; cd {R}/studio/videos/v; f; git checkout .",
    "f(){ cd src; cd .. 2>/x/y; }; source {R}/e.sh; cd {R}/studio/videos/v; f; rm -rf work",
    "cd studio/videos/v; cd {R} 2>/x/y; f(){ cd {R}/studio/videos/v; }; f; source {R}/e.sh; git checkout .",
    "cd studio/videos/v; f(){ command cd {R}; }; f; source {R}/e.sh; git checkout .",
    "command cd studio/videos/v; f(){ cd src; cd ..; }; f; source {R}/e.sh; git checkout .",
    "pushd -q studio/videos/v; pushd -q {R}; popd -q 2>/x/y; f(){ cd {R}; }; f; source {R}/e.sh; git checkout .",
    "command cd studio/videos/v; f(){ cd {R}/studio/videos/v; }; cd {R}/studio/videos/v; f; rm -rf work",
    "cd studio/videos/v; cd {R} 2>/x/y; f(){ cd {R}/studio/videos/v; }; f; git checkout .",
    "source {R}/e.sh; cd {R}/studio/videos/v; while cd {R}; do break; done; git checkout .",
    "cd src; source {R}/e.sh; cd -; while cd {R}/studio/videos/v; do break; done; git checkout .",
    "f(){ cd {R}/studio/videos/v; }; source {R}/e.sh; cd {R}/studio/videos/v; while f; do break; done; rm -rf work",
    "source {R}/e.sh; cd {R}/studio/videos/v; until cd {R}; do :; done; git checkout .",
    "cd {R}/studio/videos/v; while cd {R}; do break; done; git checkout .",
    "f(){ cd {R}/studio/videos/v; }; functions -c f h; source {R}/e.sh; cd {R}/studio/videos/v; h; rm -rf work",
    "cd src; f(){ g(){ cd {R}/studio/videos/v; }; }; f; source {R}/e.sh; cd {R}/studio/videos/v; g; rm -rf work",
    "cd src; f(){ cd {R}; }; functions -c f h; source {R}/e.sh; cd -; h; git checkout .",
    "cd studio/videos/v; f(){ cd {R}; }; unfunction f; f; source {R}/e.sh; git checkout .",
    "cd studio/videos/v; f(){ cd {R}; }; disable -f f; f; source {R}/e.sh; git checkout .",
    "f(){ cd -; }; unfunction f; f; source {R}/e.sh; git checkout .",
    "sh -c 'git commit -qm x'; rm -f .git/hooks/pre-commit; sh -c 'git commit -qm x'",
    "sh -c 'git push origin HEAD'; git config core.hooksPath /dev/null; sh -c 'git push origin HEAD'",
    "sh -c 'git commit -qm x'; git config core.hooksPath /dev/null; sh -c 'git commit -qm x'",
    "sh -c 'git commit -qm x'; sh -c 'git -c core.hooksPath=/dev/null commit -qm x'",
    "sh -c 'git push'; sh -c 'git push --no-verify'",
    "GIT_INDEX_FILE=/tmp/i git commit -qm x",
    "git commit --no-verify -qm x",
    "GIT_INDEX_FILE=/tmp/i sh -c 'git commit -qm x'",
    "sh -c 'git commit -qm x'; sh -c 'git commit -qm x -- studio'",
    "git commit -qm x",
    "sh -c 'git commit -qm x'; sh -c 'git commit -qm x'",
    "sh -c 'git commit -n -qm x'; sh -c 'git commit -qm x'",
    "command cd studio/videos/v; f(){ cd src; cd ..; }; f; source {R}/e.sh; git clean -fdx",
    "command cd {R}/studio/videos/v; f(){ cd {R}/studio/videos/v; }; source {R}/e.sh; cd {R}/studio/videos/v; f; rm -rf work",
    "command pushd studio/videos/v; f(){ cd {R}; }; f; source {R}/e.sh; rm -rf work",
    "command cd {R}/studio/videos/v; f(){ cd src; cd ..; }; f; source {R}/e.sh; git checkout .",
    "command cd studio/videos/v; f(){ pushd -q src; popd -q; }; f; source {R}/e.sh; git checkout .",
    "cd studio/videos/v; f(){ cd {R}/studio/videos/v; }; functions -c f h; h; source {R}/e.sh; rm -rf work",
    "cd studio/videos/v; f(){ cd {R}/studio/videos/v; }; functions -c f h; h; source {R}/e.sh; git checkout .",
    "source e.sh; cd {R}/studio/videos/v; bash x.sh",
    "pushd -q studio/videos/v; source e.sh; popd -q; git clean -fdx",
    "cd src; source e.sh; cd ~-; git reset --hard",
    "source e.sh; cd {R}; git checkout .",
    "git checkout .",
    "cd studio/videos/v; source e.sh; cd -; cd -; git checkout .",
    "cd studio/videos/v; source e.sh; cd -; cd -; rm -rf work",
    "command cd {R}/studio/videos/v; git checkout .",
    "cd -; bash x.sh",
    "popd -q; bash x.sh",
    "cd src; command cd {R}/studio/videos/v; rm -rf work",
    "cd src; command cd {R}/studio/videos/v; git checkout .",
    "source e.sh; cd {R}; f(){ cd {R}; }; cd studio/videos/v; f; git checkout .",
    "f(){ cd {R}; }; cd {R}/studio/videos/v; f; git clean -fdx",
    "f(){ cd {R} }; source e.sh; pushd -q {R}/studio/videos/v; f; git checkout .",
    "cd src; f(){ cd ..; }; cd ..; source e.sh; cd {R}/src; f; bash studio/videos/v/x.sh",
    "f(){ cd {R}; }; cd {R}/studio/videos/v; f; bash studio/videos/v/x.sh",
    "cd src; f(){ cd ..; }; cd ..; source e.sh; cd {R}/src; f; git reset --hard",
    "f(){ cd {R}; }; cd {R}/studio/videos/v; f; rm -rf studio/videos/v/work",
    "f(){ bash \"$1\"; }; cd src; source e.sh; cd -; f e.sh; cd {R}; { source e.sh; f bad.sh; }",
    "f(){ eval \"$1\"; }; cd src; source e.sh; cd -; f 'echo hi'; cd {R}; { source e.sh; f 'rm -rf studio'; }",
    "f(){ source \"$1\"; }; cd src; source e.sh; cd -; f e.sh; cd {R}; { source e.sh; f bad.sh; }",
    "f(){ python3 \"$1\"; }; cd src; source e.sh; cd -; f e.sh; cd {R}; { source e.sh; f ev.py; }",
    "f(){ bash -c 'rm -rf work'; }; cd src; source e.sh; cd -; f; cd {R}/studio/videos/v; ( source e.sh; f )",
    "f(){ bash -c 'rm -rf work'; }; cd src; source e.sh; cd -; f; cd {R}/studio/videos/v; source e.sh; f",
    "cd studio/videos/v; source e.sh; bash x.sh",
    "cd studio/videos/v; bash -c 'rm -rf work'",
    "cd studio/videos/v; source e.sh; bash -c 'rm -rf studio'",
    "cd $X; bash -c 'rm -rf work'",
    "cd studio/videos/v; source e.sh; rm -rf work",
    "f(){ bash -c 'rm -rf work'; }; cd studio/videos/v; source e.sh; f",
    "while :; do bash -c 'rm -rf work'; cd studio/videos/v; [[ -f q ]] && break; done",
    "cd src; source e.sh; cd -; repeat 2 { bash -c 'rm -rf work'; cd {R}/studio/videos/v; }",
    "for i in 1 2; do bash -c 'rm -rf work'; pushd -q studio/videos/v; done",
    "for i in 1 2; do bash -c 'rm -rf work'; cd studio/videos/v; done",
    "cd src; source e.sh; select i in 1 2; do cd -; bash x.sh; cd studio/videos/v; done",
    "cd src; source e.sh; while :; do cd -; bash -c 'rm -rf work'; cd {R}/studio/videos/v; [[ -f q ]] && break; done",
    "cd src; source e.sh; f(){ zsh x.sh; }; cd -; f; cd {R}/studio/videos/v; if source e.sh; then f; fi",
    "cd src; source e.sh; f(){ eval 'rm -rf work'; }; cd -; f; cd {R}/studio/videos/v; { . ./e.sh; f; }",
    "cd $X; f(){ eval 'rm -rf work'; }; cd {R}; cd src; source e.sh; cd -; f; cd {R}/studio/videos/v; if source e.sh; then f; fi",
    "cd $X; f(){ bash -c 'rm -rf work'; }; cd {R}; cd src; source e.sh; cd -; f; cd {R}/studio/videos/v; { source e.sh && f; }",
    "pushd -q src; source e.sh; f(){ bash x.sh; }; popd -q; f; cd {R}/studio/videos/v; source e.sh; alias h=f; h",
    "cd src; . ./e.sh; function f { bash x.sh }; cd ~-; f; cd {R}/studio/videos/v; source e.sh; alias h=f; h",
    "cd src; source e.sh; f(){ bash x.sh; }; popd 2>/dev/null; cd -; f; cd {R}/studio/videos/v; source e.sh; cd $X; f",
    "pushd -q src; source e.sh; f(){ bash x.sh; }; popd -q; f; cd {R}/studio/videos/v; source e.sh; cd ~-; cd ~-; f",
    "cd src; source e.sh; cd -; f(){ bash x.sh; }; f; cd {R}/studio/videos/v; source e.sh; f &",
    "cd src; source e.sh; cd -; f(){ bash x.sh; }; f; cd {R}/studio/videos/v; nvm use 20; f",
    "for i in 1 2; { bash x.sh; cd {R}/studio/videos/v; source e.sh; cd -; cd -; }",
    "while true; do bash x.sh; cd {R}/studio/videos/v; . ./e.sh; done",
    "cd src; source e.sh; cd -; while true; do bash x.sh; cd {R}/studio/videos/v; source e.sh; pushd -q .; popd -q; done",
    "cd src; source e.sh; cd -; for i in 1 2; { bash x.sh; cd {R}/studio/videos/v; source e.sh; }",
    "cd src; source e.sh; cd -; while true; do cd {R}; bash x.sh; cd {R}/studio/videos/v; source e.sh; done",
    "cd src; source e.sh; cd -; while true; do cd {R}; bash x.sh; cd {R}/studio/videos/v; source e.sh; cd -; cd -; done",
    "for d in . . . . . . .; do git -C $d checkout .; done",
    "eval 'git checkout .'; eval 'git checkout .'; eval 'git checkout .'; eval 'git checkout .'; eval 'git checkout .'; eval 'git checkout .'; git stash pop; eval 'git checkout .'",
    "for i in 1 2 3 4 5 6 7; do git checkout .; done; git stash pop; git checkout .",
    "cd src; source e.sh; cd -; for i in 1 2 3 4 5 6 7; do git checkout .; done; git stash pop; git checkout .",
    "f(){ git reset --hard; }; f; git stash pop; f",
    "git stash pop; for i in 1 2; do git reset --hard; done",
    "sh -c 'git checkout .' & sh -c 'git checkout .'",
    "sh -c 'git checkout .'; git stash pop; bash -c 'git checkout .'",
    "sh -c 'git checkout .; git stash pop; git checkout .'",
    "git checkout .; sh -c 'git checkout .'; git checkout .; sh -c 'git checkout .'; git checkout .; sh -c 'git checkout .'; git stash pop; sh -c 'git checkout .'",
    "sh -c 'git add -A; git commit -m x'; sh -c 'git add -A; git commit -m x'",
    "sh -c 'git reset --hard'; sh -c 'git stash pop'; sh -c 'git reset --hard'",
    "alias bx='bash x.sh'\ncd src; source e.sh; cd -; bx\ncd {R}/studio/videos/v; source e.sh; bx",
    "alias bx='bash x.sh'\ncd src; source e.sh; cd -; bx\ncd {R}/studio/videos/v && source e.sh && bx",
    "cd studio/videos/v; f(){ [[ -n $Z ]] && return; cd {R}; cd src; source e.sh; cd -; }; f || true; bash x.sh",
    "cd studio/videos/v; f(){ cd {R}; cd src; source e.sh; cd -; }; [[ -n $Z ]] && f(){ :; }; if f; then :; fi; bash -c 'rm -rf work'",
    "cd studio/videos/v; f(){ cd {R}; cd src; source e.sh; cd -; }; [[ -n $Z ]] && disable -f f; ( f ); bash -c 'rm -rf work'",
    "cd studio/videos/v; f(){ cd {R}; cd src; source e.sh; [[ -n $Z ]] && cd -; }; if f; then :; fi; bash -c 'rm -rf work'",
    "cd src; source e.sh; trap 'cd {R}/studio/videos/v' EXIT; cd -; bash x.sh",
    "cd src; source e.sh; trap 'cd {R}/studio/videos/v' DEBUG; cd $OLDPWD; bash x.sh",
    "cd src; source e.sh; setopt aliases; alias -g -- -={R}/studio/videos/v; cd $OLDPWD; bash x.sh",
    "cd src; source e.sh; trap 'cd {R}/studio/videos/v' EXIT; cd $OLDPWD; bash x.sh",
    "read OLDPWD <<< {R}/studio/videos/v; cd src; source e.sh; cd -; bash x.sh",
    "cd src; source e.sh; for OLDPWD in {R}/studio/videos/v; do :; done; cd ~-; bash x.sh",
    "pushd -q studio/videos/v; pushd -q {R}/scripts; pushd -q {R}; source e.sh; pushd -2; bash x.sh",
    "pushd -q studio/videos/v; pushd -q {R}/scripts; pushd -q {R}; cd src; source e.sh; setopt pushdminus; popd +1; bash x.sh",
    "pushd -q studio/videos/v; pushd -q {R}/scripts; pushd -q {R}; cd src; source e.sh; cd -; popd +1; bash x.sh",
    "pushd -q studio/videos/v; pushd -q {R}/scripts; pushd -q {R}; cd src; source e.sh; cd -; pushd -1; bash x.sh",
    "pushd -q studio/videos/v; pushd -q {R}/scripts; pushd -q {R}; cd src; source e.sh; popd -q; popd -q; bash x.sh",
    "pushd -q studio/videos/v; pushd -q {R}/scripts; pushd -q {R}; cd src; source e.sh; popd; popd; bash x.sh",
    "source .venv/bin/activate; gh pr view 1; for f in src/*.ts; do npx prettier --write $f; done",
    "source .venv/bin/activate; gh pr view 1; for f in src/*.ts; do git add $f; done",
    "source .venv/bin/activate; gh pr view 1; for f in $(git diff --name-only); do echo $f; done",
    "source .venv/bin/activate && prompt_info && for f in src/*.ts; do wc -l $f; done",
    "source .venv/bin/activate; take build; cd ..; for f in src/*.ts; do echo $f; done",
    "source .venv/bin/activate; for p in 1 2; do gh pr view $p; done; cat $LOG",
    "source .venv/bin/activate; for i in a b; do mkcd $i; cd ..; done; echo $X",
    "gh pr view 1; for f in src/*.ts; do echo $f; done",
    "source .venv/bin/activate; for f in src/*.ts; do echo $f; done",
    "cd studio/videos/v; source e.sh; f(){ cd -; }; f; git checkout .",
    "cd src; source e.sh; f(){ cd -; }; f; git checkout .",
    "builtin source {R}/e.sh; rm -rf studio/local",
    "noglob source {R}/e.sh; git checkout .",
    "command . .venv/bin/activate && git add -A && git commit -m x",
    "alias act='source .venv/bin/activate'\nact; rm -rf studio/local",
    "emulate zsh -c 'source .venv/bin/activate'; git add -A && git commit -m x",
    "eval \"$(pyenv init -)\"; rm -rf studio/local",
    "eval 'source e.sh'; git checkout .",
    "eval \"$(ssh-agent -s)\"; X={R}/studio; rm -rf $X/videos/v/work",
    "{ source /dev/stdin } <<< 'rm -rf studio/local'",
    "source /dev/stdin <<'EOF'\nrm -rf studio/local\nEOF",
    "cat > /tmp/gx.sh <<'EOF'\nrm -rf studio/local\nEOF\nsource /tmp/gx.sh",
    "rm -rf studio<->; source e.sh",
    "rm -rf studio/local; source e.sh",
    "source e.sh; rm -rf studio/local",
    "source e.sh; rm -rf studio/videos/v/work",
    "source /dev/null; echo x > ~[x]/studio/videos/v/work/state.json",
    "source /dev/null; rm -rf ~[x]/studio",
    "f(){ source e.sh; }; f; git checkout .",
    "f(){ source e.sh; rm -rf studio/local; }; ls",
    "for i in 1 2; do rm -rf studio/local; source e.sh; done",
    "for i in 1 2; do source e.sh; rm -rf studio/local; done",
    "if true; then source e.sh; else rm -rf studio/local; fi",
    "if true; then rm -rf studio/local; else source e.sh; fi",
    "( source e.sh ); git checkout .",
    "source e.sh | cat; rm -rf studio/local",
    "trap 'source e.sh' EXIT; git checkout .",
    "chpwd(){ source e.sh; }; cd src; cd ..; git checkout .",
    "sh -c 'source e.sh; rm -rf studio/local'",
    "sh -c 'source e.sh'; git checkout .",
    "source .venv/bin/activate && git commit -m x",
    "source .venv/bin/activate; python3 .claude/studio/scripts/state.py status",
    "source .venv/bin/activate && cd src && pytest && cd - && rm -rf **/__pycache__",
    "rm -rf **/__pycache__",
    "rm -rf **/__pycache__ **/*.pyc **/.pytest_cache **/.mypy_cache",
    "rm -f */*.log",
    "flock /tmp/build.lock make",
    "diff a.txt src/a.ts; git status",
    "gh pr view 1; git commit -m 'studio: v script'",
    "mkcd tmpdir && python3 -c 'print(1)'",
    "cd src && sh -c 'ls'",
    "X=studio; : ${X::=build}; rm -rf -- $X",
    "take build && cd .. && git clean -n",
    "take build && cd .. && git worktree list",
]
# rows routed to the 0.0.26 guard (a source, or effects this guard cannot read) where the final verdict is stricter
# than the 0.0.26 guard's: this guard's own refusal — of the code before the source, of the code the call gives the
# source, or (0.1.4) of what follows it, walked with what the file does; each refused by this guard with the source
# removed too (the 0.0.26 guard missed it after the source) — row: reason
_AFTER = "after the source, judged as without it (0.0.26 judged the rest without the folder or values before it)"
PARITY_G1_FIRST = {
    "{ source /dev/stdin } <<< 'rm -rf studio/local'": "the code the call gives the source (here-string): this guard's",
    "f(){ source /dev/stdin }; f <<< 'rm -rf studio/local'": "the input the call gives the sourcing function: this guard's",
    "cd studio/videos/v; f(){ cd {R}/studio/videos/v; }; functions -c f h; h; source {R}/e.sh; rm -rf work": _AFTER,
    "cd studio/videos/v; f(){ cd {R}/studio/videos/v; }; functions -c f h; h; source {R}/e.sh; git checkout .": _AFTER,
    "cd studio/videos/v; source e.sh; cd -; cd -; git checkout .": _AFTER,
    "cd studio/videos/v; source e.sh; cd -; cd -; rm -rf work": _AFTER,
    "cd src; f(){ cd ..; }; cd ..; source e.sh; cd {R}/src; f; git reset --hard": _AFTER,
    "f(){ bash -c 'rm -rf work'; }; cd src; source e.sh; cd -; f; cd {R}/studio/videos/v; ( source e.sh; f )": _AFTER,
    "f(){ bash -c 'rm -rf work'; }; cd src; source e.sh; cd -; f; cd {R}/studio/videos/v; source e.sh; f": _AFTER,
    "cd studio/videos/v; source e.sh; rm -rf work": _AFTER + " (guard-limits' own example)",
    "f(){ bash -c 'rm -rf work'; }; cd studio/videos/v; source e.sh; f": _AFTER,
    "cd src; source e.sh; cd -; f(){ bash x.sh; }; f; cd {R}/studio/videos/v; source e.sh; f &": _AFTER,
    "cd src; source e.sh; cd -; f(){ bash x.sh; }; f; cd {R}/studio/videos/v; nvm use 20; f": _AFTER,
    "cd studio/videos/v; source e.sh; f(){ cd -; }; f; git checkout .": _AFTER,
    "cd src; source e.sh; f(){ cd -; }; f; git checkout .": _AFTER,
    "noglob source {R}/e.sh; git checkout .": _AFTER + " (a Studio change not committed)",
    "eval 'source e.sh'; git checkout .": _AFTER + " (a Studio change not committed)",
    "source /dev/null; echo x > ~[x]/studio/videos/v/work/state.json": _AFTER + " (`~[x]`: a folder it cannot tell)",
    "source /dev/null; rm -rf ~[x]/studio": _AFTER + " (`~[x]`: a folder it cannot tell)",
    "f(){ source e.sh; }; f; git checkout .": _AFTER + " (a Studio change not committed)",
    "source .venv/bin/activate && cd src && pytest && cd - && rm -rf **/__pycache__":
        _AFTER + " (pytest may write before the `**` listing)",
    "alias bx='bash x.sh'\ncd src; source e.sh; cd -; bx\ncd {R}/studio/videos/v; source e.sh; bx":
        _AFTER + " (no snapshot: an alias of the call on its line)",
    "alias bx='bash x.sh'\ncd src; source e.sh; cd -; bx\ncd {R}/studio/videos/v && source e.sh && bx":
        _AFTER + " (no snapshot: an alias of the call on its line)",
    "pushd -q studio/videos/v; pushd -q {R}/scripts; pushd -q {R}; cd src; source e.sh; popd -q; popd -q; bash x.sh":
        _AFTER + " (no snapshot: AUTO_PUSHD may be on)",
    "pushd -q studio/videos/v; pushd -q {R}/scripts; pushd -q {R}; cd src; source e.sh; popd; popd; bash x.sh":
        _AFTER + " (no snapshot: AUTO_PUSHD may be on)",
    "source .venv/bin/activate && prompt_info && for f in src/*.ts; do wc -l $f; done":
        _AFTER + " (no snapshot: a function name it cannot find)",
    "source .venv/bin/activate; take build; cd ..; for f in src/*.ts; do echo $f; done":
        _AFTER + " (no snapshot: a function name it cannot find)",
    "source .venv/bin/activate; for i in a b; do mkcd $i; cd ..; done; echo $X":
        _AFTER + " (no snapshot: a function name it cannot find)",
    "take build && cd .. && git clean -n": "a snapshot function that changes folder (routed): git clean where it may run",
    "take build && cd .. && git worktree list": "a snapshot function that changes folder (routed): git where it may run",
}
# 0.1.4 (class N): rows the 0.0.26 guard refuses, this guard passes, and the final verdict is this guard's — each a
# 0.0.26 false refusal (with HEAD_REFUSED_KEPT / HEAD_REFUSED_FUNCS of test_guard_judge) — row or class: reason
LEGACY_FALSE_UNSOURCED = {
    "cd -; bash x.sh": "a new shell has no $OLDPWD: `cd -` fails and the shell stays (x.sh at the root is `echo ok`)",
    "popd -q; bash x.sh": "the stack is empty: popd fails and the shell stays (x.sh at the root is `echo ok`)",
    "cd src; command cd {R}/studio/videos/v; rm -rf work": "`command cd` runs the external cd (POSIX_BUILTINS off): "
                                                          "the shell stays in src",
    "cd src; command cd {R}/studio/videos/v; git checkout .": "`command cd` runs the external cd: the shell stays in src",
    "f(){ cd {R}; }; cd {R}/studio/videos/v; f; bash studio/videos/v/x.sh": "x.sh's `rm -rf work` runs in the "
                                                                          "repository root, which has no work folder",
    "rm -rf **/__pycache__ **/*.pyc **/.pytest_cache **/.mypy_cache": "the `**` listing holds no Studio data (0.0.26 "
                                                                       "refused every `**` deletion)",
    # classes, each with its rows under its own snapshot (SnapshotParity)
    "class: environment unknown after any snapshot function": "0.0.26 made the environment unknown after every shell "
                                                             "function of yours; this guard only after one that "
                                                             "exports, unexports or writes a watched name",
    "class: payload to the end of the snapshot": "0.0.26 searched a function's text to the end of the snapshot, alias "
                                                 "lines included; this guard every function body, not the alias lines",
}
# 0.1.4: rows with a source the 0.0.26 guard refuses and this guard alone passes (they stay refused in 0.1.4, as a
# call with a source is judged by both) — each a 0.0.26 false refusal: row: reason (the evidence 0.1.6 needs)
LEGACY_FALSE_AFTER_SOURCE = {
    "command pushd studio/videos/v; f(){ cd {R}; }; f; source {R}/e.sh; rm -rf work":
        "`command pushd` is the external pushd: the shell is in the repository root, whose work holds nothing Studio's",
    "cd src; f(){ cd ..; }; cd ..; source e.sh; cd {R}/src; f; bash studio/videos/v/x.sh":
        "x.sh's `rm -rf work` runs in the repository root",
    "f(){ source \"$1\"; }; cd src; source e.sh; cd -; f e.sh; cd {R}; { source e.sh; f bad.sh; }":
        "bad.sh does not exist; nothing follows",
    "pushd -q src; source e.sh; f(){ bash x.sh; }; popd -q; f; cd {R}/studio/videos/v; source e.sh; alias h=f; h":
        "an alias defined on the line it is used on is not expanded",
    "cd src; . ./e.sh; function f { bash x.sh }; cd ~-; f; cd {R}/studio/videos/v; source e.sh; alias h=f; h":
        "an alias defined on the line it is used on is not expanded",
    "cd studio/videos/v; f(){ [[ -n $Z ]] && return; cd {R}; cd src; source e.sh; cd -; }; f || true; bash x.sh":
        "$Z is unset in the hook's environment; this guard passes the row without the source too",
    "rm -rf studio<->; source e.sh": "`<->` matches digits only (HEAD_REFUSED_KEPT)",
    "source .venv/bin/activate; python3 .claude/studio/scripts/state.py status":
        "0.0.26 read it as python3 writing state.py; this guard passes it without the source too",
    "source /dev/null && popd && rm -rf studio/videos/v/work": "the stack is empty: popd fails and rm never runs",
    "cd src; source /dev/null; cd ../scripts; cd -; git worktree add studio/x": "it runs in src",
}


# the plain wrappers of the C20-1 rows (round-20 fixture)
C20_FUNCS = """take () {
\tmkdir -p $@ && cd ${@:$#}
}
gh () {
\tcommand gh "$@"
}
mkcd () {
\tmkdir -p "$1" && cd "$1"
}
prompt_info () {
\tlocal ref
\tref=$(command git symbolic-ref --short HEAD 2> /dev/null)
\tprint -r -- "${ref:-detached}"
}
"""


def setup_fixture(repo):
    """The round 19-20 review fixture: e.sh files that export, a venv, a Studio change not committed, x.sh files."""
    for d in ("src", "studio/videos/v", ".", "scripts", "studio"):
        os.makedirs(os.path.join(repo, d), exist_ok=True)
        with open(os.path.join(repo, d, "e.sh"), "w") as f:
            f.write("export A=1\n")
        with open(os.path.join(repo, d, "x.sh"), "w") as f:
            f.write("rm -rf work\n" if d == "studio/videos/v" else "echo ok\n")
    os.makedirs(os.path.join(repo, ".venv", "bin"), exist_ok=True)
    with open(os.path.join(repo, ".venv", "bin", "activate"), "w") as f:
        f.write("export VIRTUAL_ENV=x\n")
    with open(os.path.join(repo, "studio", "videos", "v", "script.md"), "a") as f:
        f.write("more\n")
    os.makedirs(os.path.join(repo, "studio", "videos", "v", "work"), exist_ok=True)


class BackstopCase(JudgeCase):
    def setUp(self):
        super().setUp()
        setup_fixture(self.repo)

    def legacy_loader(self, env):
        if self.mode != "with":
            return None, ["snapshot-none"]
        return self.snap_with[0].legacy_view

    def legacy_only(self, tool, ti, cwd=None):
        """The 0.0.26 guard alone (its own decide, finish included)."""
        from stdo.guard.legacy import judge as lj
        return lj.decide(self.hook(tool, ti, cwd), self.env, snapshot_loader=self.legacy_loader)

    def final(self, tool, ti, cwd=None, **kw):
        return judge.decide(self.hook(tool, ti, cwd), self.env, snapshot_loader=self.loader, **kw)

    def forced_legacy_deny(self, rule="G-DEL", text="forced by the test"):
        """The 0.0.26 guard's decision replaced by a refusal (backstop's own cache; restored by the caller)."""
        lj, dec = backstop._legacy()

        def fake(ctx, hook):
            ctx.denies.insert(0, lj.Deny(rule, text))
            return ctx.denies[0], ctx
        saved = list(backstop._LEGACY)
        backstop._LEGACY[1] = fake
        return saved

    def use_snapshot(self, **kw):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"], **kw))
        self.snap_with = snapmod.load(self.env)
        shutil.rmtree(d)
        self.mode = "with"


class Combination(BackstopCase):
    def test_legacy_deny_is_final_for_a_sourced_call(self):  # plan §5.2 test 1; 0.1.4: class S only
        calls = [("Bash", {"command": "source /dev/null; ls"}), ("Bash", {"command": "f(){ source e.sh; }; ls"}),
                 ("Bash", {"command": "trap '. x' DEBUG; ls"})]
        saved = self.forced_legacy_deny()
        try:
            for tool, ti in calls:
                deny, ctx = self.final(tool, ti)
                self.assertTrue(ctx.unread, ti)
                self.assertIsNotNone(deny, ti)
                self.assertEqual(deny.rule, "G-DEL", ti)
                # the 0.0.26 guard's own message (its messages module), tagged and cut as in 0.0.26
                from stdo.guard.legacy import messages as lm
                self.assertIsInstance(deny, lm.Deny, ti)
                msg = deny.message(ctx.denies)
                self.assertTrue(msg.startswith("Studio guard [G-DEL]: forced by the test"), msg)
                self.assertLessEqual(len(msg), lm.LIMIT)
            hook = self.hook("Bash", {"command": "source /dev/null; ls"})
            hook.update({"agent_id": "a1", "agent_type": "std-auditor"})
            deny, _ctx = judge.decide(hook, self.env, snapshot_loader=self.loader)
            self.assertEqual(deny and deny.rule, "G-AUDIT")  # this guard's own refusal comes first
        finally:
            backstop._LEGACY[:] = saved
        self.assertIsNone(self.bash("source /dev/null; ls"))

    def test_unsourced_call_is_g1s_alone(self):  # 0.1.4 §2.4 (class N): a frozen refusal does not change the verdict
        calls = [("Bash", {"command": "ls"}), ("Bash", {"command": "git status"}),
                 ("Write", {"file_path": os.path.join(self.repo, "src", "n.ts"), "content": "x"}),
                 ("WebFetch", {"url": "https://example.com", "prompt": "x"}), ("mcp__fs__read", {"path": "a.txt"})]
        saved = self.forced_legacy_deny()
        try:
            for tool, ti in calls:
                deny, ctx = self.final(tool, ti)
                self.assertIsNone(deny, (tool, ti, deny))
                self.assertFalse(ctx.unread, ti)
            hook = self.hook("Bash", {"command": "ls"})
            hook.update({"agent_id": "a1", "agent_type": "std-auditor"})
            deny, _ctx = judge.decide(hook, self.env, snapshot_loader=self.loader)
            self.assertIsNone(deny)
        finally:
            backstop._LEGACY[:] = saved

    def test_g1_deny_does_not_import_legacy(self):  # test 2 (and P20-4: the push / commit memo is lazy)
        code = ("import json, sys; sys.path.insert(0, %r); from stdo.guard import judge; "
                "hook = json.loads(sys.argv[1]); d, ctx = judge.decide(hook, dict(__import__('os').environ)); "
                "print(d and d.rule, any(m.startswith('stdo.guard.legacy') for m in sys.modules))" % helpers.SCRIPTS)
        env = dict(self.env, PYTHONDONTWRITEBYTECODE="1")
        # 0.1.4 (review 3 m4): a call with no source imports nothing frozen — its push and commit checks too
        cases = (("Bash", {"command": "rm -rf studio/local"}, "G-DEL False"), ("Bash", {"command": "ls"}, "None False"),
                 ("Bash", {"command": "git status"}, "None False"),
                 ("Bash", {"command": "git commit -m x"}, None), ("Bash", {"command": "git push"}, None),
                 ("Edit", {"file_path": os.path.join(self.repo, "src", "a.ts"), "old_string": "x", "new_string": "y"},
                  "None False"),
                 ("Bash", {"command": "source /dev/null; ls"}, "None True"))
        for tool, ti, want in cases:
            out = subprocess.run([sys.executable, "-B", "-c", code, json.dumps(self.hook(tool, ti))],
                                 capture_output=True, text=True, env=env, cwd=self.repo)
            if want is None:
                self.assertTrue(out.stdout.strip().endswith(" False"), (ti, out.stdout, out.stderr[-800:]))
            else:
                self.assertEqual(out.stdout.strip(), want, (ti, out.stderr[-800:]))

    def test_legacy_error_is_head_text(self):  # test 3, Q4
        lj, _dec = backstop._legacy()
        saved = list(backstop._LEGACY)

        def boom(ctx, hook):
            raise KeyError("x")
        backstop._LEGACY[1] = boom
        try:
            deny, ctx = self.final("Bash", {"command": "source /dev/null; ls"})
        finally:
            backstop._LEGACY[:] = saved
        self.assertEqual(deny.rule, "G-ERR")
        self.assertEqual(deny.text, "internal guard error (KeyError) — tell the user; this is a bug in the guard.")
        self.assertIsInstance(deny, lj.Deny)
        # an exception in the adapter itself reaches guard.py, whose own handler refuses (G-ERR)
        merge = backstop._merge

        def bad(g, lctx):
            raise RuntimeError("adapter")
        backstop._merge = bad
        try:
            with self.assertRaises(RuntimeError):
                self.final("Bash", {"command": "source /dev/null; ls"})
            self.assertIsNone(self.final("Bash", {"command": "ls"})[0])  # class N: no merge
        finally:
            backstop._merge = merge

    def test_frozen_paths(self):  # test 9 (§1.2): one more dirname gives the folders 0.0.26 computed
        from stdo.guard.legacy import judge as lj, version as lv, walk as lw
        from stdo.guard import version as gv, walk as gw
        self.assertEqual(lj.PLUGIN_SCRIPTS, judge.PLUGIN_SCRIPTS)
        self.assertEqual(lj.PLUGIN_SCRIPTS_SPELLED, judge.PLUGIN_SCRIPTS_SPELLED)
        self.assertEqual(lj.DOC_SCRIPTS, judge.DOC_SCRIPTS)
        self.assertEqual(lv.PLUGIN_SCRIPTS, gv.PLUGIN_SCRIPTS)
        self.assertEqual(lw.PLUGIN_LOCK, gw.PLUGIN_LOCK)

    def test_legacy_decision_is_head_decide_without_finish(self):  # test 10
        import inspect
        lj, dec = backstop._legacy()
        self.assertIs(dec.__code__, lj._decide.__code__)  # 0.0.26's own code, not a copy
        self.assertIs(dec.__globals__["finish"], backstop._no_finish)
        self.assertEqual({k for k in dec.__globals__ if dec.__globals__[k] is not vars(lj).get(k)}, {"finish"})
        src = inspect.getsource(lj._decide).splitlines()
        i = [n for n, line in enumerate(src) if line.strip() == "finish(ctx)"]
        self.assertEqual(len(i), 1)
        # after its finish, 0.0.26 only returns: with finish a no-op, nothing else runs
        self.assertEqual([x.strip() for x in src[i[0] + 1:]], ["if ctx.denies:", "return ctx.denies[0], ctx",
                                                               "return None, ctx"])
        # its handler is 0.0.26's decide's: the same text
        dsrc = inspect.getsource(lj.decide)
        self.assertIn('internal guard error (%s) — tell the user; this is a bug in the guard."', dsrc)
        self.assertIs(judge.decide, backstop.decide)  # P20-3: an alias, not a wrapper

    def test_merge_touched_and_warnings(self):  # test 6
        R = types.SimpleNamespace
        a, a2, b = R(worktree="/r/a"), R(worktree="/r/a"), R(worktree="/r/b")
        g, lctx = R(touched=[a], warnings=["w1"]), R(touched=[a2, b], warnings=["w1", "w2"])
        backstop._merge(g, lctx)
        self.assertEqual([x.worktree for x in g.touched], ["/r/a", "/r/b"])
        self.assertEqual(g.warnings, ["w1", "w2"])
        # guard.py's record: once per repository (a class S call: both guards' repositories)
        deny, ctx = self.final("Bash", {"command": "source /dev/null; ls studio"})
        self.assertIsNone(deny)
        judge.record_run(ctx)
        with open(os.path.join(self.repo, ".claude", "studio", "local", "guard-ran.json")) as f:
            self.assertIn("sess-1", json.load(f)["sessions"])

    def test_shared_checks(self):  # test 7 (P20-4); 0.1.4: G1's own checks, the frozen ones wrapped with the same memo
        lp, lc = backstop._own_checks()
        flp, flc = backstop._frozen_checks()
        self.assertTrue(getattr(lp.check, "_shared", False) and getattr(flp.check, "_shared", False))
        from stdo.guard import commitrule as gc, push as gp
        self.assertIs(lp, gp)
        self.assertIs(lc, gc)
        calls = []
        orig_p, orig_c = lp.check.__wrapped__, lc.evaluate.__wrapped__

        def fake_push(worktree, env, args, ids, budget=3.0):
            calls.append(("push", worktree, dict(env)))
            return None, ["w"]

        def fake_commit(worktree, env, extra, opts, budget=8.0, plugin_scripts=None):
            calls.append(("commit", worktree, dict(extra)))
            return "outcome"
        lp.check.__wrapped__, lc.evaluate.__wrapped__ = fake_push, fake_commit
        W = types.SimpleNamespace
        try:
            backstop._MEMO.clear()
            args = [W(value="push"), W(value="origin")]
            for _ in range(2):
                self.assertEqual(backstop.shared_push("/r", {"A": "1"}, args, set()), (None, ["w"]))
                self.assertEqual(flp.check("/r", {"A": "1"}, args, set()), (None, ["w"]))  # the 0.0.26 guard's call
            backstop.shared_push("/r", {"A": "2"}, args, set())
            backstop.shared_push("/s", {"A": "1"}, args, set())
            self.assertEqual([c[0] for c in calls], ["push"] * 3)
            for extra in ({}, {}, {"GIT_DIR": "/x"}):
                self.assertEqual(backstop.shared_commit("/r", {}, extra, {"amend": False}), "outcome")
            self.assertEqual(len(calls), 5)
        finally:
            lp.check.__wrapped__, lc.evaluate.__wrapped__ = orig_p, orig_c
            backstop._MEMO.clear()
        # one decision: the check runs once for both guards (a real push in a class S call), once for G1 alone
        n = []
        forig = flp.check.__wrapped__

        def counting(*a, **kw):
            n.append(1)
            return orig_p(*a, **kw)

        def fcounting(*a, **kw):
            n.append(2)
            return forig(*a, **kw)
        lp.check.__wrapped__, flp.check.__wrapped__ = counting, fcounting
        try:
            self.bash("source /dev/null; git push")
            self.assertEqual(len(n), 1, n)
            del n[:]
            self.bash("git push")
            self.assertEqual(n, [1])
        finally:
            lp.check.__wrapped__, flp.check.__wrapped__ = orig_p, forig

    def test_deadline(self):  # P20-8; 0.1.4: only a call the 0.0.26 guard also judges
        old = backstop.DEADLINE
        backstop.DEADLINE = -1.0
        try:
            deny = self.bash("source /dev/null; ls")
            self.assertIsNone(self.bash("ls"))  # class N: G1's own budget, not the sum of both
        finally:
            backstop.DEADLINE = old
        self.assertEqual(deny.rule, "G-LIMIT")
        self.assertIn("time", deny.text)
        self.assertLess(backstop.DEADLINE, 20 / 2)  # the hook's timeout is 20 s (hooks.json); both guards fit


class Effects(BackstopCase):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        d = os.path.join(self.repo, "studio", "videos", "v", "work")
        with open(os.path.join(d, "state.json"), "w") as f:
            json.dump({"video": "v", "source_lang": "ko"}, f)
        self.tpath = TR.transcript_path(self.env)
        self.t = TR.approval_turn(TR.T(), "승인 v %s" % H)
        self.t.write(self.tpath)

    def hook(self, tool, ti, cwd=None):
        h = super().hook(tool, ti, cwd)
        h.update({"transcript_path": self.tpath, "tool_use_id": "toolu_cmd1", "prompt_id": self.t.prompt})
        return h

    def pending_path(self):
        return os.path.join(self.repo, ".claude", "studio", "local", "pending-approval.json")

    def pending(self):
        try:
            with open(self.pending_path()) as f:
                return json.load(f)
        except OSError:
            return None

    def writes(self):
        """Count the evidence writes of each guard (test-only wrappers, restored by the caller)."""
        from stdo.guard import approve as ga
        from stdo.guard.legacy import approve as la
        n = {"g1": 0, "legacy": 0}
        saved = (ga.write_pending, la.write_pending)

        def wrap(fn, k):
            def w(*a, **kw):
                n[k] += 1
                return fn(*a, **kw)
            return w
        ga.write_pending, la.write_pending = wrap(ga.write_pending, "g1"), wrap(la.write_pending, "legacy")
        return n, saved

    def restore(self, saved):
        from stdo.guard import approve as ga
        from stdo.guard.legacy import approve as la
        ga.write_pending, la.write_pending = saved

    def test_g1_finish_alone(self):
        n, saved = self.writes()
        try:
            deny, ctx = self.final("Bash", {"command": APPROVE})
        finally:
            self.restore(saved)
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)
        self.assertEqual(n, {"g1": 1, "legacy": 0})

    def test_no_effects_when_legacy_denies(self):  # test 4 (0.1.4: a call the 0.0.26 guard also judges)
        n, saved = self.writes()
        saved_l = self.forced_legacy_deny()
        try:
            deny, ctx = self.final("Bash", {"command": APPROVE + "; source /dev/null"})
        finally:
            backstop._LEGACY[:] = saved_l
            self.restore(saved)
        self.assertEqual(deny.rule, "G-DEL")
        self.assertIsNone(ctx.allow)
        self.assertIsNone(self.pending())
        self.assertEqual(n, {"g1": 0, "legacy": 0})
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "studio", "local", "guard-ran.json")))

    def test_sourced_call_runs_the_0026_finish_once(self):  # test 5 (in process)
        n, saved = self.writes()
        try:
            deny, ctx = self.final("Bash", {"command": APPROVE + "; source /dev/null"})
        finally:
            self.restore(saved)
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.sourced)
        self.assertIsNone(ctx.allow)  # not alone in its call: no allow (as in 0.0.26)
        self.assertEqual(n, {"g1": 0, "legacy": 1})
        self.assertIsNotNone(self.pending())

    def test_sourced_approval_as_0026(self):  # test 5 against the 0.0.26 guard itself (P20-6)
        head = os.path.join(self.tmp, "head-scripts")
        build_0026_scripts(head)
        cmd = APPROVE + "; source /dev/null"  # the evidence of a command before a source: 0.0.26's finish writes it
        hook = self.hook("Bash", {"command": cmd})
        env = dict(self.env, PYTHONDONTWRITEBYTECODE="1")
        env.pop("CLAUDE_PLUGIN_DATA", None)
        out = {}
        for name, script in (("0.0.26", os.path.join(head, "guard.py")), ("0.0.27", GUARD)):
            if os.path.exists(self.pending_path()):
                os.remove(self.pending_path())
            r = subprocess.run([sys.executable, script], input=json.dumps(hook), capture_output=True, text=True,
                               env=env, cwd=self.repo)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            p = self.pending()
            self.assertIsNotNone(p, name)
            out[name] = (r.stdout, {k: v for k, v in p.items() if k not in ("at", "written_at")})
        self.assertEqual(out["0.0.27"], out["0.0.26"])

    def test_limit_outside_studio_runs_no_g1_finish(self):  # P20-2
        ran = []
        orig = judge.decide_bash

        def partial(ctx, command):
            ctx.collected = True
            ctx.effects.append(("G-X", lambda: ran.append(1)))
            ctx.candidates.append((None, "doc", "test"))
            raise limits.LimitExceeded("fs-calls")
        judge.decide_bash = partial
        try:
            deny, ctx = self.final("Bash", {"command": "echo hi"}, cwd=self.tmp)
        finally:
            judge.decide_bash = orig
        self.assertIsNone(deny, deny and deny.message())
        self.assertEqual(ran, [])
        self.assertIsNone(ctx.allow)

    def test_finish_errors_keep_their_handlers(self):  # P20-7
        orig = judge.finish

        def boom(ctx):
            raise ValueError("x")
        judge.finish = boom
        try:
            deny, _ctx = self.final("Bash", {"command": "ls"})
        finally:
            judge.finish = orig
        self.assertEqual((deny.rule, deny.text), ("G-ERR", "internal guard error (ValueError) — tell the user; this "
                                                            "is a bug in the guard."))
        from stdo.guard.legacy import judge as lj
        lorig = lj.finish
        lj.finish = boom
        try:
            deny, _ctx = self.final("Bash", {"command": "source .venv/bin/activate && ls"})
        finally:
            lj.finish = lorig
        self.assertEqual(deny.rule, "G-ERR")
        self.assertIsInstance(deny, lj.Deny)


def build_0026_scripts(dest):
    """The 0.0.26 plugin scripts: today's scripts with guard/ replaced by guard/legacy, the two rewrites reversed (the
    structure test proves the result is the 0.0.26 guard byte for byte)."""
    shutil.copytree(helpers.SCRIPTS, dest, ignore=shutil.ignore_patterns("__pycache__"))
    g = os.path.join(dest, "stdo", "guard")
    leg = os.path.join(g, "legacy")
    for n in os.listdir(g):
        if n.endswith(".py"):
            os.remove(os.path.join(g, n))
    for n in os.listdir(leg):
        lines = open(os.path.join(leg, n), encoding="utf-8").read().split("\n")[1:]
        out = []
        for line in lines:
            if re.match(r"^\s*from \.\.\.", line):
                line = re.sub(r"^(\s*)from \.\.\.", r"\1from ..", line, count=1)
            out.append(line.replace("os.path.abspath(os.path.dirname(__file__))", "os.path.abspath(__file__)"))
        with open(os.path.join(g, n), "w", encoding="utf-8") as f:
            f.write("\n".join(out))
    shutil.rmtree(leg)


FIXTURES = os.path.join(helpers.PLUGIN, "tests", "fixtures", "sourced")
# a file shaped like oh-my-zsh's lib/diagnostics.zsh (functions with loops, locals and candidate assignments; not its
# text): its walk takes more than its own CPU bound (limits.SOURCE_WALK_CPU) on any machine this runs on
HEAVY = "".join("f%d(){ local a=$1 b=$2; for v in a b c d; do X=$v; [[ -n $a ]] && cd $b; done; }\n" % i
                for i in range(400))


class SourceWalk(BackstopCase):
    """0.1.4 §1.4: this guard walks on after a `source` / `.` — the four classes of a source, the shares and bounds of
    a sourced file's walk, the routing to the 0.0.26 guard (`ctx.sourced`, `ctx.unread`)."""

    def g1ctx(self, cmd, cwd=None):
        d, ctx, _c = judge.decide_g1(self.hook("Bash", {"command": cmd}, cwd), self.env, snapshot_loader=self.loader,
                                     run_finish=False)
        return d, ctx

    def write(self, name, text):
        p = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return p

    def walked(self, ctx):
        """The files whose commands were walked in this shell (class 3) and those read as unknown (class 4)."""
        sc = ctx.scan
        via = {c.via_source for c in sc.commands if getattr(c, "via_source", None)}
        unread = {n.split(":")[1] for n in sc.notes if n.startswith("source-unread:")}
        return via, unread

    def venv(self, version):
        with open(os.path.join(FIXTURES, "activate-%s" % version)) as f:
            text = f.read().replace("__VENV__", os.path.join(self.repo, ".venv"))
        self.write(".venv/bin/activate", text)

    def test_routes_to_a_source(self):  # §3.2, P20-5; 0.1.4: routed (sourced) and walked on
        for cmd in ("source x; ls", ". x; ls", "builtin source x; ls", "noglob source x; ls", "command . x; ls",
                    "command source x; ls", "alias act='source .venv/bin/activate'\nact; ls",
                    "alias act='. x'\nact; ls", "emulate zsh -c 'source x'; ls", "emulate sh -c \"$X\"; ls",
                    'eval "$(pyenv init -)"; ls', "eval 'source x'; ls", "eval '. x'; ls",
                    "f(){ source x; }; f; ls", "if true; then source x; fi; ls", "( source x ); ls",
                    "for i in 1; do source x; done; ls", "source x | cat; ls",
                    # a source in a body defined here, an EXIT hook or a nested string routes the call too
                    "sh -c 'source x'; ls", "f(){ source x; }; ls", "trap 'source x' EXIT; ls",
                    "TRAPEXIT(){ source x; }; ls", "zshexit_functions+=(g); g(){ source x; }; ls",
                    "chpwd(){ source x; }; cd src; ls"):
            _d, ctx = self.g1ctx(cmd)
            self.assertTrue(ctx.sourced, cmd)
            self.assertTrue(ctx.unread, cmd)
            self.assertIn("ls", [c.prog for c in ctx.scan.commands], cmd)
        for cmd in ("./x.sh; ls", "eval 'X=1'; ls", "alias a='ls -l'\na; ls", "echo source; ls"):
            _d, ctx = self.g1ctx(cmd)
            self.assertFalse(ctx.sourced, cmd)
            self.assertFalse(ctx.unread, cmd)
            self.assertIn("ls", [c.prog for c in ctx.scan.commands], cmd)
        # a nested string's own commands after its source are judged too
        d, ctx = self.g1ctx("sh -c 'source x; rm -rf studio'; ls")
        self.assertTrue(ctx.sourced)
        self.assertEqual(d and d.rule, "G-DEL")

    def test_before_the_source_and_its_payload(self):
        for cmd, rule in (("{ source /dev/stdin } <<< 'rm -rf studio/local'", "G-DEL"),
                          ("source /dev/stdin <<'EOF'\nrm -rf studio/local\nEOF", "G-DEL"),
                          ("cat > /tmp/gx.sh <<'EOF'\nrm -rf studio/local\nEOF\nsource /tmp/gx.sh", "G-DEL"),
                          ("rm -rf studio/local; source x", "G-DEL"),
                          ("for i in 1 2; do rm -rf studio/local; source x; done", "G-DEL"),
                          ("if true; then rm -rf studio/local; else source x; fi", "G-DEL")):
            d, ctx = self.g1ctx(cmd)
            self.assertEqual(d and d.rule, rule, cmd)
            self.assertEqual(self.bash(cmd).rule, rule, cmd)

    def test_four_classes(self):
        self.write("empty.sh", "")
        self.write("big.sh", "# " + "x" * (limits.SOURCE_WALK_MAX + 1000) + "\nexport A=1\n")
        self.write("nv.sh", "nvm(){ eval \"$1\"; }\nnvm use 20\n")
        # class 2: nothing (any spelling of /dev/null, an empty regular file)
        for cmd in ("source /dev/null; git status", ". /dev/../dev/null; git status", "source empty.sh; git status"):
            d, ctx = self.g1ctx(cmd)
            self.assertIsNone(d, cmd)
            self.assertEqual(self.walked(ctx), (set(), set()), cmd)
            self.assertIn("source-read", [c for c in ctx.scan.commands if c.prog in ("source", ".")][0].flags)
        # class 3: walked in this shell
        d, ctx = self.g1ctx("source e.sh; git status")
        self.assertIsNone(d)
        self.assertEqual(self.walked(ctx), ({"e.sh"}, set()))
        self.assertIn(["export", "A=1"], [c.argv for c in ctx.scan.commands])
        for version in ("3.9", "3.12"):  # the real `python3 -m venv` activate
            self.venv(version)
            for cmd in ("source .venv/bin/activate && git commit -m x", "source .venv/bin/activate && git status",
                        "source .venv/bin/activate && git add -A",
                        "source .venv/bin/activate; gh pr view 1; for f in src/*.ts; do git add $f; done",
                        "source .venv/bin/activate && python3 -m pytest"):
                d, ctx = self.g1ctx(cmd)
                self.assertIsNone(d, (version, cmd, d))
                self.assertEqual(self.walked(ctx), ({".venv/bin/activate"}, set()), cmd)
                self.assertIsNone(self.bash(cmd), cmd)
            self.assertEqual(self.g1ctx("source .venv/bin/activate && rm -rf studio/local")[0].rule, "G-DEL")
        # class 4: a file over SOURCE_WALK_MAX, a missing file, a name the guard cannot read, a file whose own code
        # it cannot read (an nvm.sh-like function with eval): the environment unknown, git not checked
        for cmd, unread in (("source big.sh; ls", "big.sh"), ("source missing.sh; ls", None), ("source $F; ls", None)):
            d, ctx = self.g1ctx(cmd)
            self.assertIsNone(d, cmd)
            via, _u = self.walked(ctx)
            self.assertEqual(via, set(), cmd)
            files = [o.path for o in ctx.scan.opaque if o.kind == "source" and o.origin == "file"]
            self.assertEqual([os.path.basename(f) for f in files], [unread] if unread else [], cmd)
            self.assertEqual(self.g1ctx(cmd.replace("; ls", "; git status"))[0].rule, "G-OPAQUE", cmd)
        d, ctx = self.g1ctx("source nv.sh; git status")
        self.assertEqual(d and d.rule, "G-OPAQUE")
        self.assertEqual(self.walked(ctx)[0], {"nv.sh"})

    def test_guard_limits_holes_now_refused(self):
        self.write("env.sh", "export A=1\n")
        for cmd, rule in (("source e.sh; git clean -fdx", "G-CLEAN"),
                          ("source e.sh; cd studio/videos/v; git clean -fdx", "G-CLEAN"),
                          ("cd studio/videos/v; source e.sh; rm -rf work", "G-DEL"),
                          ("cd src; source /dev/null; rm -rf ~-/studio/videos/v/work", "G-DEL"),
                          ("source e.sh; rm -rf stu*", "G-DEL"),
                          ("f(){ cd studio/videos/v; }; source env.sh; f; git clean -fdx", "G-CLEAN"),
                          ("eval 'source e.sh'; git checkout .", "G-RESET"),
                          ("noglob source %s/e.sh; git checkout ." % self.repo, "G-RESET")):
            d, ctx = self.g1ctx(cmd)
            self.assertEqual(d and d.rule, rule, cmd)
            self.assertTrue(ctx.unread, cmd)
            self.assertEqual(self.bash(cmd).rule, rule, cmd)

    def test_what_the_file_does_holds_after_it(self):
        self.write("cdv.sh", "cd studio/videos/v\n")
        self.write("gd.sh", "export GIT_DIR=/tmp/x\n")
        self.write("gs.sh", "setopt globsubst\n")
        self.write("src/m.sh", "pushd -q ../scripts; popd -q\n")
        self.write("scripts/x.sh", "rm -rf ../studio\n")
        self.write("al.sh", "alias ls='rm -rf studio'\nls\n")
        self.write("ret.sh", "return\ncd studio/videos/v\n")
        self.write("noret.sh", "cd studio/videos/v\n")
        for cmd, rule in (("source cdv.sh; git checkout .", "G-RESET"), ("source gd.sh; git status", "G-OPAQUE"),
                          ("source gs.sh; X='s*o'; rm -rf $X", "G-DEL"),
                          ("cd src; source m.sh; cd -; bash x.sh", "G-DEL"),  # the folder `cd -` goes to is the file's
                          ("source al.sh; ls", None),  # review 1 M4: refused (the alias's text names studio)
                          ("source noret.sh; rm -rf work", "G-DEL")):
            d, _ctx = self.g1ctx(cmd)
            self.assertIsNotNone(d, cmd)
            if rule:
                self.assertEqual(d.rule, rule, cmd)
        d, ctx = self.g1ctx("source ret.sh; rm -rf work")  # a `return` at the top: the rest of the file is not run
        self.assertIsNone(d)
        self.assertEqual(self.walked(ctx), ({"ret.sh"}, set()))

    def test_must_pass(self):
        self.venv("3.12")
        for cmd in ("source .venv/bin/activate && git commit -m x", "source /dev/null; git status",
                    "set -a; source /dev/null; set +a; git commit -m x", "source e.sh && git status",
                    # review 1 M2: an ordinary program before the source does not make the file stale (class 3 kept)
                    "mkdir -p build && source .venv/bin/activate && git status",
                    "npm ci && source .venv/bin/activate && git status",
                    "pip install -e . && source .venv/bin/activate && git status",
                    "uv venv && source .venv/bin/activate && pytest && git status",
                    # review 1 M3: a class 2 / 3 source writes nothing before a `**` listing
                    "source /dev/null && rm -rf **/__pycache__", ". /dev/null; rm -rf **/__pycache__"):
            self.assertPass(cmd)
            if ".venv" in cmd:
                self.assertEqual(self.walked(self.g1ctx(cmd)[1]), ({".venv/bin/activate"}, set()), cmd)
        self.write(".venv/bin/activate", "export VIRTUAL_ENV=x\n")
        self.assertPass("source .venv/bin/activate && rm -rf **/__pycache__")

    def test_c20_1_rows_pass(self):  # C20-1: 0.0.26 passes them, and this guard walking after the source too
        self.use_snapshot(functions=C20_FUNCS)
        for cmd in ("source .venv/bin/activate; gh pr view 1; for f in src/*.ts; do npx prettier --write $f; done",
                    "source .venv/bin/activate; gh pr view 1; for f in src/*.ts; do git add $f; done",
                    "source .venv/bin/activate; gh pr view 1; for f in $(git diff --name-only); do echo $f; done",
                    "source .venv/bin/activate; take build; cd ..; for f in src/*.ts; do echo $f; done",
                    "source .venv/bin/activate; for p in 1 2; do gh pr view $p; done; cat $LOG",
                    "source .venv/bin/activate; for i in a b; do mkcd $i; cd ..; done; echo $X"):
            self.assertPass(cmd)
            self.assertIsNone(self.g1ctx(cmd)[0], cmd)

    def test_class_4_when_the_file_may_be_stale(self):
        self.write("gen.sh", "echo export A=1\n")
        os.symlink(os.path.join(self.repo, "e.sh"), os.path.join(self.repo, "lnk.sh"))
        for i in range(1, 6):
            self.write("s%d.sh" % i, "source s%d.sh\nexport D%d=1\n" % (i + 1, i))
        self.write("s6.sh", "export D6=1\n")
        for cmd, name in (("cp scripts/e.sh x2.sh; source x2.sh; ls", "x2.sh"),
                          ("python3 gen.py > x3.sh; source x3.sh; ls", "x3.sh"),
                          ("python3 gen.py > lnk.sh; source e.sh; ls", "e.sh"),  # the same file through a link
                          ("bash gen.sh; source e.sh; ls", "e.sh")):  # an earlier script may have written it
            self.write(name, "export B=1\n") if name != "e.sh" else None
            _d, ctx = self.g1ctx(cmd)
            via, _u = self.walked(ctx)
            self.assertNotIn(name, via, cmd)
            self.assertTrue([o for o in ctx.scan.opaque if o.kind == "source" and o.origin == "file"], cmd)
        # nested sources: read to depth 3 (SHELL_DEPTH), the fourth unknown
        _d, ctx = self.g1ctx("source s1.sh; ls")
        self.assertEqual(self.walked(ctx), ({"s1.sh", "s2.sh", "s3.sh"}, {"s4.sh"}))
        # a source in a dry run (a chpwd hook's effects) is not read, and routes the call
        _d, ctx = self.g1ctx("chpwd(){ source e.sh; }; cd src; ls")
        self.assertTrue(ctx.unread)
        # an EXIT hook's source runs after every command: not read
        _d, ctx = self.g1ctx("TRAPEXIT(){ source e.sh; }; ls")
        self.assertEqual(self.walked(ctx)[0], set())

    def test_bounds(self):  # review 1 M1, review 4 m3, review 5 m2
        import time
        self.write("heavy.sh", HEAVY)
        for k in range(8):
            self.write("h%d.sh" % k, HEAVY)
        self.write("n1.sh", "source n2.sh\n" + HEAVY)
        self.write("n2.sh", "source n3.sh\n" + HEAVY)
        self.write("n3.sh", HEAVY)
        self.write("many.sh", ":\n" * (limits.MAX_COMMANDS // 2 + 100))  # more than its share of the commands
        self.write("cds.sh", "cd src; cd ..\n" * (limits.MAX_COMMANDS // 4 + 50))
        self.write("probes.sh", "".join("bash nx%d.sh\n" % i for i in range(limits.MAX_FS_CALLS // 3)))  # file probes
        for cmd in ("source heavy.sh; ls", "; ".join("source h%d.sh" % k for k in range(8)) + "; ls",
                    "source n1.sh; ls", "source many.sh; ls", "source cds.sh; ls", "source probes.sh; ls"):
            t0 = time.monotonic()
            d, ctx = self.g1ctx(cmd)
            self.assertLess(time.monotonic() - t0, 2.0, cmd)
            self.assertIsNone(d, (cmd, d))  # class 4, not G-LIMIT
            via, unread = self.walked(ctx)
            self.assertEqual(via, set(), cmd)
            self.assertTrue(unread, cmd)
            self.assertEqual(self.g1ctx(cmd.replace("; ls", "; git status"))[0].rule, "G-OPAQUE", cmd)
        # the same text inline in the call: the call's own bounds (G-LIMIT), within its wall budget
        t0 = time.monotonic()
        d, _ctx = self.g1ctx(HEAVY + "ls")
        self.assertEqual(d and d.rule, "G-LIMIT")
        self.assertLess(time.monotonic() - t0, limits.WALL_BUDGET)

    def test_walk_on_a_copy(self):  # review 1 m2
        self.write("half.sh", "rm -rf studio/local\nexport A=1\nif then fi (((\n")
        d, ctx = self.g1ctx("source half.sh; ls")
        self.assertNotIn("rm", [c.prog for c in ctx.scan.commands])
        self.assertEqual(self.walked(ctx), (set(), {"half.sh"}))
        self.assertEqual(self.g1ctx("source half.sh; git status")[0].rule, "G-OPAQUE")  # class 4's state

    def test_message_names_the_file(self):
        self.write("rm.sh", "rm -rf studio/local\n")
        d, _ctx = self.g1ctx("source rm.sh")
        self.assertEqual(d.rule, "G-DEL")
        self.assertIn("(run by rm.sh, which this command sources.)", d.message())

    def test_source_in_a_defined_body(self):  # review 3 m6
        d, ctx = self.g1ctx("TRAPEXIT(){ source e.sh; rm -rf studio/videos; }; ls")
        self.assertEqual(d and d.rule, "G-DEL")
        self.assertTrue(ctx.unread)
        d, ctx = self.g1ctx("f(){ source e.sh; }; ls")
        self.assertIsNone(d)
        self.assertTrue(ctx.unread)
        self.assertIsNone(self.bash("f(){ source e.sh; }; ls"))
        # review 3 NIT: refused by this guard itself now, as without the source
        self.assertEqual(self.g1ctx("f(){ source e.sh; rm -rf studio/local; }; ls")[0].rule, "G-DEL")

    def test_readings_keep_the_code_before_the_source(self):  # P20-5: forks and readings
        # several folders: the reading of each starts before the source
        d, ctx = self.g1ctx('f(){ rm -rf $1/local; source x; }; if [ -n "$X" ]; then :; else cd studio; fi; f $PWD')
        self.assertTrue(ctx.sourced)
        self.assertEqual(d and d.rule, "G-DEL")
        # a may-fail fork does not drop the main reading's commands before the source
        for cmd in ("f(){ cd studio; }; f > /x/y; rm -rf local; source x", "f(){ cd $1; }; f $D > /x/y; rm -rf local; "
                    "source x"):
            d, ctx = self.g1ctx(cmd)
            self.assertEqual(d and d.rule, "G-DEL", cmd)



class Parity(BackstopCase):
    """0.1.4 §2.2, §2.5: the evidence for class N as tests — on the parity corpus, a call the 0.0.26 guard no longer
    judges loses no refusal but the listed 0.0.26 false refusals; a call it still judges keeps its verdict."""

    def g1(self, cmd):
        return judge.decide_g1(self.hook("Bash", {"command": cmd}), self.env, snapshot_loader=self.loader,
                               run_finish=False)

    def test_parity(self):  # test 11; 0.1.4 §2.5
        from stdo.guard.legacy.messages import Deny as LDeny
        from test_guard_judge import HEAD_REFUSED_FUNCS, HEAD_REFUSED_KEPT
        rows = [(r, "parity") for r in BACKSTOP_PARITY]
        rows += [(c, "deny") for c, _r in MUST_DENY[::10]] + [(c, "pass") for c in MUST_PASS[::12]]
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, kind in rows:
                text = cmd.replace("{R}", self.repo)
                f, fctx = self.final("Bash", {"command": text})
                g, gctx, complete = self.g1(text)
                l, lctx = self.legacy_only("Bash", {"command": text})
                why = "%s (%s): final %s, G1 %s, 0.0.26 %s" % (cmd, mode, f, g, l)
                if not gctx.unread and complete:
                    # class N: the final verdict is this guard's; a 0.0.26 refusal it does not give is a listed
                    # 0.0.26 false refusal; its repositories and warnings are this guard's
                    self.assertFalse(fctx.unread, why)
                    self.assertEqual(f is None, g is None, why)
                    if l is not None and g is None:
                        self.assertTrue(cmd in LEGACY_FALSE_UNSOURCED or cmd in HEAD_REFUSED_KEPT[mode] or
                                        cmd in HEAD_REFUSED_FUNCS, "a 0.0.26 refusal lost: " + why)
                    if l is None and g is None:
                        g_trees = {getattr(ri, "worktree", None) for ri in gctx.touched}
                        self.assertLessEqual({getattr(ri, "worktree", None) for ri in lctx.touched}, g_trees, why)
                        self.assertEqual([w for w in lctx.warnings if w not in gctx.warnings], [], why)
                    continue
                if l is not None:
                    self.assertIsNotNone(f, "0.0.26 refuses, the final passes: " + why)
                if kind == "parity" and l is None:
                    self.assertTrue(f is None or cmd in PARITY_G1_FIRST, "stricter than 0.0.26, not listed: " + why)
                if f is not None and isinstance(f, LDeny):  # the 0.0.26 guard's answer: its message, byte for byte
                    self.assertEqual(f.message(fctx.denies), l.message(lctx.denies), cmd)
                if f is not None:
                    msg = f.message(fctx.denies)
                    self.assertTrue(msg.startswith("Studio guard ["), msg[:80])
                    self.assertLessEqual(len(msg), 1500)
        for cmd in LEGACY_FALSE_UNSOURCED:
            self.assertTrue(cmd.startswith("class: ") or cmd in BACKSTOP_PARITY, cmd)
        for cmd in list(PARITY_G1_FIRST) + list(LEGACY_FALSE_AFTER_SOURCE):
            self.assertIn(cmd, BACKSTOP_PARITY + [c for c, _r in MUST_DENY] + list(MUST_PASS), cmd)

    def test_parity_g1_alone_after_source(self):  # 0.1.4 §1.7: the evidence 0.1.6 needs
        rows = [r for r in BACKSTOP_PARITY] + [c for c, _r in MUST_DENY] + list(MUST_PASS)
        rows = [r for r in dict.fromkeys(rows) if re.search(r"(^|[\s;&|({])(source|\.)\s", r)]
        seen = set()
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in rows:
                text = cmd.replace("{R}", self.repo)
                g, gctx, _c = self.g1(text)
                if not gctx.sourced:
                    continue
                seen.add(cmd)
                l, _lctx = self.legacy_only("Bash", {"command": text})
                if l is not None and g is None:
                    self.assertIn(cmd, LEGACY_FALSE_AFTER_SOURCE, "0.0.26 refuses after a source, this guard "
                                                                  "passes: %s (%s): %s" % (cmd, mode, l))
        self.assertGreater(len(seen), 100)
        self.assertLessEqual(set(LEGACY_FALSE_AFTER_SOURCE), seen)

    def test_parity_tools(self):  # 0.1.4 §2.2: the file, web and MCP tools — this guard's refusals ⊇ 0.0.26's
        paths = []
        for d, ds, fs in os.walk(self.repo):
            if os.sep + ".git" in d:
                continue
            paths += [os.path.join(d, n) for n in fs + ds]
        home = self.env["HOME"]
        extra = [".claude/agents/std-auditor.md", ".claude/agents/std-writer.md", ".claude/agents/std-fact-checker.md",
                 ".claude/settings.json", ".claude/settings.local.json", ".claude/studio/scripts/state.py",
                 ".claude/studio/MANIFEST", ".claude/studio/local/x.json", ".git/hooks/pre-commit", ".git/config",
                 "studio/videos/v/work/state.json", "studio/videos/v/script.md", "studio/videos/v/approvals.json",
                 "studio/local/a", "src/a.ts", "README.md", os.path.join(home, ".claude/settings.json"),
                 os.path.join(home, ".gitconfig"), "/tmp/x.txt",
                 os.path.join(self.env["CLAUDE_CONFIG_DIR"], "settings.json")]
        paths += [p if os.path.isabs(p) else os.path.join(self.repo, p) for p in extra]
        inputs = []
        for p in sorted(set(paths)):
            inputs += [("Write", {"file_path": p, "content": "x"}),
                       ("Edit", {"file_path": p, "old_string": "a", "new_string": "b"}),
                       ("MultiEdit", {"file_path": p, "edits": [{"old_string": "a", "new_string": "b"}]}),
                       ("NotebookEdit", {"notebook_path": p, "new_source": "x"}),
                       ("mcp__fs__write_file", {"path": p, "content": "x"})]
        inputs += [("WebFetch", {"url": u, "prompt": "x"}) for u in
                   ("https://example.com/", "http://localhost:8080/", "file:///etc/passwd", "https://internal.example/")]
        inputs += [("WebSearch", {"query": "studio"})]
        both = 0
        for tool, ti in inputs:
            g, gctx, complete = judge.decide_g1(self.hook(tool, ti), self.env, snapshot_loader=self.loader,
                                                run_finish=False)
            self.assertFalse(gctx.unread, (tool, ti))
            l, _lctx = self.legacy_only(tool, ti)
            if l is not None:
                self.assertIsNotNone(g, "0.0.26 refuses, this guard passes: %s %s (%s)" % (tool, ti, l.rule))
                both += 1
        self.assertGreater(both, 100)

# 0.1.4 §1.4b, §2.5: harmless and shadowing shell functions (review 3 m1/m3, review 4 m1; neutral fixtures)
REV4_FUNCS = """take () {
\tmkdir -p $@ && cd ${@:$#}
}
pv () {
\techo version
}
u1 () {
\ttypeset +x HOME
}
p3 () {
\thash sed=/tmp/sed
}
p4 () {
\tautoload -Uz sed
}
pa () {
\tpath=(/tmp $path)
}
k1 () {
\tHOME=/tmp/x exec
}
"""
# review 1 B1: pyenv-, nvm- and conda-style wrappers (an eval, a source, an export PATH) and `"$@"`
PYENV_FUNCS = """pyenv () {
\tlocal command=${1:-}
\t[ "$#" -gt 0 ] && shift
\tcase "$command" in
\t\t(rehash|shell) eval "$(pyenv "sh-$command" "$@")" ;;
\t\t(*) command pyenv "$command" "$@" ;;
\tesac
}
nvm () {
\tsource ~/.nvm/nvm.sh
\tnvm "$@"
}
conda () {
\texport PATH="/opt/conda/bin:$PATH"
\t\\command conda "$@"
}
dyn () {
\t"$@"
}
"""
ZZ = "zz () {\n\trm -rf studio/videos/$1/work\n}\n"
SED = "sed -i '' s/a/b/ studio/videos/v/script.md"
# review 4 m1: every route to a name a function's effects shadowed (`hash sed=…`)
SHADOW_ROUTES = ["p3; " + SED, "p3; sed -n 1p studio/videos/v/script.md", "p4; " + SED,
                 "p4; sed -n 1p studio/videos/v/script.md", "p3; command " + SED, "p3; exec " + SED,
                 "p3; noglob " + SED, "p3; nocorrect " + SED, "p3; time " + SED, "p3; X=1 " + SED,
                 "p3; command -p " + SED, "p3; (%s)" % SED, "p3; { %s; }" % SED, "p3; if true; then %s; fi" % SED,
                 "p3; f(){ %s; }; f" % SED, "p4; command " + SED,
                 # kept on purpose (review 5 NIT): env finds sed on PATH (0.0.26 refused it too: the rule is on the
                 # name); xargs of a list the guard cannot read is refused for its own reason
                 "p3; env " + SED, "p3; xargs sed -i '' s/a/b/ < l.txt"]
# review 4-7 (§1.4d): a function calling a later or earlier one, by any spelling — `aa; ls` must deny either way
AA_BODIES = ["zz v", "x=$(zz v)", "(zz v)", "cat <(zz v)", "z''z v", 'z""z v', 'z"z" v', "z\\z v", "x=$(z''z v)",
             "x=$(${:-z}z v)", "x=$($'\\x7az' v)", "{z,}z v", "x=$({z,}z v)", "x=$(eval z${:-z} v)",
             "x=$(command eval z$X)", "x=$(z? v)"]


class SnapshotParity(BackstopCase):
    """0.1.4 §1.4a-d, §2.5: the class N evidence under snapshots of the rev-4 reviews (each its own fixture) and the no-
    snapshot PATH rows: this guard alone refuses what the 0.0.26 guard refuses there, but the listed classes."""

    def g1(self, cmd):
        return judge.decide_g1(self.hook("Bash", {"command": cmd}), self.env, snapshot_loader=self.loader,
                               run_finish=False)

    def deny_both(self, cmd, rule=None, routed=None):
        g, ctx, _c = self.g1(cmd)
        self.assertIsNotNone(g, "this guard alone should refuse: %s (%s)" % (cmd, self.mode))
        if rule:
            self.assertEqual(g.rule, rule, "%s: %s" % (cmd, g.message()))
        if routed is not None:
            self.assertEqual(ctx.unread, routed, cmd)
        self.assertIsNotNone(self.bash(cmd), cmd)
        return ctx

    def legacy_false(self, cmd):
        """A 0.0.26 false refusal of a LEGACY_FALSE_UNSOURCED class: the 0.0.26 guard refuses, this guard passes."""
        g, ctx, _c = self.g1(cmd)
        self.assertIsNone(g, "%s: %s" % (cmd, g and g.message()))
        self.assertIsNotNone(self.legacy_only("Bash", {"command": cmd})[0], cmd)
        if not ctx.unread:
            self.assertIsNone(self.bash(cmd), cmd)  # class N: the final verdict is this guard's

    def test_functions_that_change_nothing_or_shadow(self):  # §1.4b
        self.use_snapshot(functions=REV4_FUNCS)
        with open(os.path.join(self.repo, "l.txt"), "w") as f:
            f.write("studio/videos/v/script.md\n")
        for cmd in ("u1; s2v status", "u1; python3 .claude/studio/scripts/lock.py status",
                    # review MINOR 1: assignments before a bare `exec` stay in the shell (HOME exported)
                    "k1; s2v status", "k1; python3 .claude/studio/scripts/lock.py status"):
            self.deny_both(cmd, "G-ENV")  # `typeset +x` unexports (or makes a local: kept strict)
        for cmd in SHADOW_ROUTES:
            ctx = self.deny_both(cmd, "G-OPAQUE")
            self.assertTrue(ctx.unread, cmd)  # belt and braces: routed to the 0.0.26 guard in 0.1.4
        for cmd in ("p3; ls", "p3; git status"):
            self.assertIsNone(self.g1(cmd)[0], cmd)
        # the frozen judge's three walker inputs: env.unknown, path-modified, exec-by-program
        self.deny_both("pa; " + SED, "G-OPAQUE")
        for cmd in ("env bash -c 'rm -rf studio/local'", "nohup sh -c 'rm -rf studio/local'"):
            self.deny_both(cmd, "G-DEL")
        self.assertIn("class: environment unknown after any snapshot function", LEGACY_FALSE_UNSOURCED)
        for cmd in ("pv; s2v status", "pv; python3 .claude/studio/scripts/lock.py status", "pv; " + SED,
                    "pv; bash scripts/x.sh", "take x; s2v status"):
            self.legacy_false(cmd)

    def test_history_after_unreadable_effects(self):  # §1.4a (review 1 B1, review 3 m5)
        self.use_snapshot(functions=REV4_FUNCS + PYENV_FUNCS)
        for cmd, rule in (("cd studio/videos/v; take x; rm -rf ~-/studio", "G-DEL"),
                          ("cd studio/videos/v; cd /tmp; take y; rm -rf ~-/work", "G-DEL"),
                          ("cd studio/videos/v; pyenv version; rm -rf ~-/studio", "G-DEL"),
                          ("cd studio/videos/v; pyenv version; rm -rf $OLDPWD/studio", "G-DEL"),
                          ("cd studio/videos/v; pyenv version; echo x > ~-/.claude/studio/local/a", "G-PROT"),
                          ("pushd -q studio/videos/v; nvm use 20; popd; git checkout .", "G-RESET"),
                          ("cd studio/videos/v; dyn true; rm -rf ~-/studio", "G-DEL")):
            self.deny_both(cmd, rule, routed=True)
        for cmd in ("chpwd_functions+=(g); g(){ source e.sh; }; cd src; ls", "trap '. x' ZERR; ls",
                    "trap '. x' DEBUG; ls"):
            self.assertTrue(self.g1(cmd)[1].unread, cmd)
        # an eval drops `~-` in both guards at HEAD: this guard keeps its candidates (PARITY_G1_FIRST class)
        for cmd in ("cd studio; eval 'cd videos'; rm -rf ~-", "cd studio/videos/v; eval 'echo hi'; rm -rf ~-/studio",
                    "cd studio/videos/v; eval 'echo hi'; rm -rf $OLDPWD/studio"):
            self.assertEqual(self.g1(cmd)[0].rule, "G-DEL", cmd)

    def test_function_text_is_every_function(self):  # §1.4d (reviews 3-7, option b)
        for body in AA_BODIES:
            for funcs in ("aa () {\n\t%s\n}\n%s" % (body, ZZ), "%saa () {\n\t%s\n}\n" % (ZZ, body)):
                self.use_snapshot(functions=REV4_FUNCS + funcs)
                for cmd in ("aa", "aa; ls"):
                    g, _ctx, _c = self.g1(cmd)
                    self.assertEqual(g and g.rule, "G-OPAQUE", (body, funcs.startswith("aa"), cmd))
        # review 7 m1: a `}` line inside a heredoc or a quoted string ends no body
        self.use_snapshot(functions="aa () {\n\tcat <<EOF\n}\nEOF\n\trm -rf studio/videos/v/work\n}\n"
                                    "bb () {\n\tx='\n}\n'\n\trm -rf studio/videos/v/work\n}\n" + REV4_FUNCS)
        for cmd in ("aa", "bb", "aa; ls", "pv"):
            self.deny_both(cmd, "G-OPAQUE")
        # kept new refusal (guard-limits): one body naming a Studio file puts it in every function call's text
        self.use_snapshot(functions="pv0 () {\n\techo version\n}\nh1 () {\n\tcat config.json\n}\nh2 () {\n\th1\n}\n"
                                    "pv1 () {\n\techo version\n}\n")
        for cmd in ("h1", "h2", "pv0", "pv1"):
            self.assertEqual(self.g1(cmd)[0].rule, "G-OPAQUE", cmd)
        # LEGACY_FALSE_UNSOURCED: 0.0.26's text ran to the end of the snapshot, alias lines included
        self.assertIn("class: payload to the end of the snapshot", LEGACY_FALSE_UNSOURCED)
        self.use_snapshot(functions=REV4_FUNCS, extra_alias_lines=["alias -- sclean='rm -rf studio/local'"])
        for cmd in ("pv; ls", "pv; git status"):
            self.legacy_false(cmd)

    def test_path_writes_without_a_snapshot(self):  # §1.4c (review 2 M3, reviews 3-6)
        self.mode = "none"
        deny = ["read PATH <<< /tmp", "while read PATH; do :; done <<< /tmp", "for PATH in /tmp; do :; done",
                "select PATH in /tmp; do break; done", "print -v PATH /tmp", "printf -v PATH /tmp", "getopts PATH x",
                ": ${PATH:=/tmp}", ": ${path::=/tmp}", ": ${(A)path::=/tmp}", "set -A path /tmp",
                "IFS=: read -A path <<< /tmp", "vared PATH", "zparseopts -A PATH x:", "f(){ PATH=/tmp; }; f",
                "f(){ PATH=$1; }; f /tmp", "f(){ path=(/tmp); }; f", "f(){ export PATH=/tmp; }; f",
                "f(){ PATH=$(echo /tmp); }; f", "f(){ export PATH=\"$(pwd)/bin:$PATH\"; }; f",
                "f(){ local PATH=/tmp; }; f", "f(){ unset PATH; }; f", "f(){ eval 'PATH=/tmp'; }; f", "PATH=/tmp",
                "path=(/tmp)", "export PATH=/tmp", "typeset -g PATH=/tmp", "strftime -s PATH", "sysread PATH"]
        passing = ["PATH=$(echo /tmp):$PATH", "PATH=${X:-/tmp}", "PATH+=:/tmp", "path[1]=/tmp", "eval 'PATH=/tmp'",
                   "unset PATH", "path+=(~/bin)", "path=(~/bin(N) $path)", "path=($^path/x(N))",
                   "path=($HOME/bin $path)", "PATH=${PATH%:*}", "PATH=${PATH//:\\/tmp/}",
                   "PATH=\"${PATH:+$PATH:}/opt/bin\"", "PATH=`echo /tmp`:$PATH", "PATH=$X", "PATH=$1:$PATH",
                   "PATH=$(getconf PATH)", "PATH=${PATH:-/usr/bin}", "path[1,0]=/tmp", "typeset PATH=$X",
                   "local PATH=$X"]
        for pre in deny:
            self.assertEqual(self.g1(pre + "; foo_unknown")[0].rule, "G-UNKNOWN", pre)
        for pre in passing:
            self.assertIsNone(self.g1(pre + "; foo_unknown")[0], pre)
        for cmd in ("env PATH=/tmp foo_unknown", "PATH=$(npm bin):$PATH; eslint",
                    "export PATH=\"$(pwd)/node_modules/.bin:$PATH\"; npm test"):
            self.assertIsNone(self.g1(cmd)[0], cmd)
        self.assertEqual(self.g1("PATH=$PATH:~-/bin; foo_unknown")[0].rule, "G-UNKNOWN")  # stricter, unchanged

    def test_std_auditor_rows(self):  # review 3 NIT: the auditor's own refusal, in both guards
        self.use_snapshot(functions=REV4_FUNCS)
        for cmd in ("echo x > .claude/agents/std-auditor.md", "pv; echo x > .claude/agents/std-auditor.md",
                    "source e.sh; echo x > .claude/agents/std-auditor.md", "cp x .claude/agents/std-fact-checker.md"):
            hook = self.hook("Bash", {"command": cmd})
            hook.update({"agent_id": "a1", "agent_type": "std-auditor"})
            g, _ctx, _c = judge.decide_g1(hook, self.env, snapshot_loader=self.loader, run_finish=False)
            from stdo.guard.legacy import judge as lj
            l, _lctx = lj.decide(hook, self.env, snapshot_loader=self.legacy_loader)
            self.assertEqual((g and g.rule, l and l.rule), ("G-AUDIT", "G-AUDIT"), cmd)


class SplitShared(JudgeCase):
    """fix-0029 §1.3: the frozen snapshot.split_line, wrapped once by the backstop. Real loads: snapshot files in a
    real CLAUDE_CONFIG_DIR, `judge.decide` with no loader (as in production; no injected `legacy_view`). 0.1.4: on a
    call the 0.0.26 guard judges (a source); a class N call loads no frozen snapshot."""

    def setUp(self):
        super().setUp()
        backstop._legacy()
        from stdo.guard.legacy import snapshot as ls
        self.ls = ls
        self.orig = ls.split_line.__wrapped__
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        aliases = ALIASES + [("q%d" % i, "'echo %d'" % i) for i in range(20)]
        for i in range(3):  # three files: two texts, and the same alias lines in each
            with open(os.path.join(d, "snapshot-zsh-%d-s.sh" % i), "w") as f:
                f.write(snapshot_text(aliases=aliases, path=self.env["PATH"] + ("" if i < 2 else ":/opt/s")))
        self.lines = [l for l in snapshot_text(aliases=aliases, path=self.env["PATH"]).split("\n")
                      if l.startswith("alias ")]
        self.lines += ["unalias find 2>/dev/null || true", "unalias grep 2>/dev/null || true",
                       "unalias pkill 2>/dev/null || true",
                       "PATH='%s'" % self.env["PATH"], "PATH='%s:/opt/s'" % self.env["PATH"]]

    def tearDown(self):
        self.ls.split_line.__wrapped__ = self.orig
        super().tearDown()

    def test_installed_once(self):
        w = self.ls.split_line
        self.assertTrue(getattr(w, "_shared", False))
        self.assertIs(w.__wrapped__, self.orig)
        backstop._install_split(self.ls)
        backstop._legacy()
        self.assertIs(self.ls.split_line, w)
        self.assertEqual(backstop.SPLIT_MAX, 4096)

    def test_same_answers(self):
        backstop._SPLIT_ON[:] = [True]  # as inside decide
        try:
            for line in self.lines + ["alias -- a='b' c=\"d e\" f=g\\ h", "alias -g G='| grep'", ""]:
                for _ in range(2):
                    got = self.ls.split_line(line)
                    self.assertEqual(got, self.orig(line), line)
                    got.append("changed")  # a new list each time
                self.assertEqual(self.ls.split_line(line), self.orig(line), line)
        finally:
            del backstop._SPLIT_ON[:]
            backstop._SPLIT.clear()

    def test_exception_never_kept(self):
        deep = "alias -- deep=" + "$(" * 70 + ")" * 70
        n = []

        def counting(line):
            n.append(line)
            return self.orig(line)
        self.ls.split_line.__wrapped__ = counting
        backstop._SPLIT_ON[:] = [True]
        try:
            from stdo.guard.legacy import limits as llimits
            for _ in range(3):
                with self.assertRaises(llimits.LimitExceeded):
                    self.ls.split_line(deep)
            self.assertNotIn(deep, backstop._SPLIT)
            self.assertEqual(len(n), 3)
        finally:
            del backstop._SPLIT_ON[:]
            backstop._SPLIT.clear()

    def test_outside_decide_nothing_kept(self):
        n = []

        def counting(line):
            n.append(line)
            return self.orig(line)
        self.ls.split_line.__wrapped__ = counting
        for _ in range(2):
            self.ls.load(self.env)  # the 0.0.26 load outside decide (as the tests' guard_base patch)
        self.assertEqual(backstop._SPLIT, {})
        self.assertGreater(len(n), len(set(n)))  # every file's lines went through: no memo outside decide

    def test_one_call_per_distinct_line(self):  # like test 7: one real decision
        n = []

        def counting(line):
            n.append(line)
            return self.orig(line)
        self.ls.split_line.__wrapped__ = counting
        self.assertEqual(backstop._SPLIT, {})
        import guard_base
        patch = snapmod.load
        snapmod.load = guard_base._load_both.__defaults__[-1]  # production's load (the tests' also loads 0.0.26's)
        try:
            deny, _ctx = judge.decide(self.hook("Bash", {"command": "source /dev/null; ls"}), self.env)
            self.assertIsNone(deny)
            self.assertEqual(backstop._SPLIT, {})
            self.assertEqual(sorted(n), sorted(set(n)))  # each line once
            self.assertEqual(set(n), set(self.lines))  # alias lines, stripped unalias lines, the PATH arguments
            del n[:]
            self.assertIsNone(judge.decide(self.hook("Bash", {"command": "ls"}), self.env)[0])
            self.assertEqual(n, [])  # class N: the frozen guard does not parse the snapshot
        finally:
            snapmod.load = patch

    def test_memo_empty_after_every_ending(self):
        for cmd in ("ls", "rm -rf studio/local", "source /dev/null; ls"):  # a pass, a G1 deny, a class S pass
            judge.decide(self.hook("Bash", {"command": cmd}), self.env)
            self.assertEqual((backstop._SPLIT, backstop._SPLIT_ON), ({}, []), cmd)
        lj, _dec = backstop._legacy()
        saved = list(backstop._LEGACY)

        def boom(ctx, hook):
            self.ls.load(self.env)
            self.assertTrue(backstop._SPLIT)  # filled during decide
            raise KeyError("x")
        backstop._LEGACY[1] = boom
        try:
            deny, _ctx = judge.decide(self.hook("Bash", {"command": "source /dev/null; ls"}), self.env)
        finally:
            backstop._LEGACY[:] = saved
        self.assertEqual(deny.rule, "G-ERR")
        self.assertEqual((backstop._SPLIT, backstop._SPLIT_ON), ({}, []))
        # an exception out of G1 itself (the adapter's caller sees it): still cleared
        g1 = judge.decide_g1

        def bad(*a, **kw):
            backstop._SPLIT["x"] = ["x"]
            raise RuntimeError("g1")
        judge.decide_g1 = bad
        try:
            with self.assertRaises(RuntimeError):
                judge.decide(self.hook("Bash", {"command": "ls"}), self.env)
        finally:
            judge.decide_g1 = g1
        self.assertEqual((backstop._SPLIT, backstop._SPLIT_ON), ({}, []))


class LegacyDepsClosure(JudgeCase):
    """fix-0029 §3.1: the non-guard `stdo` modules the 0.0.26 guard runs are all pinned (structure_test.sh,
    LEGACY_DEPS_HEAD). An import-only check proves nothing (kinds.registry imports harness.py and video.py lazily), so a
    subprocess runs the frozen paths: the frozen judge, push and commitrule imported, `kinds.registry({})`, one real
    frozen commit check on a staged Studio change, and a few 0.0.26 decisions with a snapshot. G1's modules
    (`stdo.guard.*` outside legacy/) are left out by name; this covers the paths it runs, not every import."""

    def test_every_module_the_frozen_paths_run_is_pinned(self):
        with open(os.path.join(helpers.PLUGIN, "tests", "structure_test.sh"), encoding="utf-8") as f:
            st = f.read()
        block = st.split("LEGACY_DEPS_HEAD = {", 1)[1].split("}", 1)[0]
        pinned = {m.replace("/", ".")[:-3].replace(".__init__", "") for m in re.findall(r'"(stdo/[^"]+\.py)"', block)}
        with open(os.path.join(self.repo, "studio", "videos", "v", "script.md"), "a") as f:
            f.write("more\n")
        helpers.git(self.repo, "add", "studio/videos/v/script.md")
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"]))
        code = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
sys.dont_write_bytecode = True
repo, hook = sys.argv[2], json.loads(sys.argv[3])
import os
from stdo.guard.legacy import commitrule as lc, judge as lj, push as lp
from stdo.commit import kinds
kinds.registry({})
o = lc.evaluate(repo, dict(os.environ), {}, lc.parse_commit([]))
out = [o.deny and o.deny[0], o.studio]
for cmd in ("git commit -qm x", "git push origin HEAD", "ls studio", "python3 .claude/studio/scripts/state.py next v"):
    hook["tool_input"] = {"command": cmd}
    d, _ctx = lj.decide(hook, dict(os.environ))
    out.append(d and d.rule)
print(json.dumps([out, sorted(m for m in sys.modules if m.startswith("stdo"))]))
"""
        hook = self.hook("Bash", {"command": "ls"})
        r = subprocess.run([sys.executable, "-B", "-c", code, helpers.SCRIPTS, self.repo, json.dumps(hook)],
                           capture_output=True, text=True, env=dict(self.env, PYTHONDONTWRITEBYTECODE="1"),
                           cwd=self.repo, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        out, mods = json.loads(r.stdout)
        self.assertEqual(out[:2], ["G-COMMIT", ["studio/videos/v/script.md"]])  # the frozen check ran to commit-ok
        self.assertEqual(len(out), 6)
        loaded = {m for m in mods if m != "stdo.guard" and not m.startswith("stdo.guard.")}  # the guards' own
        for m in ("stdo.commit.harness", "stdo.commit.video", "stdo.credits"):
            self.assertIn(m, loaded)  # the lazy imports did run
        self.assertEqual(sorted(loaded - pinned), [])
