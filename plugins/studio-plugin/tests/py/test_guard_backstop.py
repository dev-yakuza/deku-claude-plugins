"""fix20: the 0.0.26 guard as a backstop (guard/backstop.py, guard/legacy). Every call is judged by this guard (G1)
and by the frozen 0.0.26 guard; anything either refuses is refused. After a `source` / `.` (or eval text that may run
one) G1 judges nothing more: the 0.0.26 rules alone judge the rest, and the 0.0.26 guard's finish runs. Real git only
in temporary repositories; the 0.0.26 tree for test_sourced_approval_as_0026 is rebuilt from guard/legacy (the
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
# rows with a source where the final verdict may be stricter than the 0.0.26 guard's: this guard's own refusal of the
# code before the source, or of code the call gives the source itself (the stdin / heredoc payload) — row: reason
PARITY_G1_FIRST = {
    "{ source /dev/stdin } <<< 'rm -rf studio/local'": "the code the call gives the source (here-string): this guard's",
    "f(){ source /dev/stdin }; f <<< 'rm -rf studio/local'": "the input the call gives the sourcing function: this guard's",
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
    def test_legacy_deny_is_final_for_every_tool(self):  # plan §5.2 test 1
        calls = [("Bash", {"command": "ls"}), ("Write", {"file_path": os.path.join(self.repo, "src", "n.ts"),
                                                         "content": "x"}),
                 ("WebFetch", {"url": "https://example.com", "prompt": "x"}), ("mcp__fs__read", {"path": "a.txt"})]
        saved = self.forced_legacy_deny()
        try:
            for tool, ti in calls:
                deny, ctx = self.final(tool, ti)
                self.assertIsNotNone(deny, tool)
                self.assertEqual(deny.rule, "G-DEL", tool)
                # the 0.0.26 guard's own message (its messages module), tagged and cut as in 0.0.26
                from stdo.guard.legacy import messages as lm
                self.assertIsInstance(deny, lm.Deny, tool)
                msg = deny.message(ctx.denies)
                self.assertTrue(msg.startswith("Studio guard [G-DEL]: forced by the test"), msg)
                self.assertLessEqual(len(msg), lm.LIMIT)
            hook = self.hook("Bash", {"command": "ls"})
            hook.update({"agent_id": "a1", "agent_type": "std-auditor"})
            deny, _ctx = judge.decide(hook, self.env, snapshot_loader=self.loader)
            self.assertEqual(deny and deny.rule, "G-DEL")
        finally:
            backstop._LEGACY[:] = saved
        self.assertIsNone(self.bash("ls"))

    def test_g1_deny_does_not_import_legacy(self):  # test 2 (and P20-4: the push / commit memo is lazy)
        code = ("import json, sys; sys.path.insert(0, %r); from stdo.guard import judge; "
                "hook = json.loads(sys.argv[1]); d, ctx = judge.decide(hook, dict(__import__('os').environ)); "
                "print(d and d.rule, any(m.startswith('stdo.guard.legacy') for m in sys.modules))" % helpers.SCRIPTS)
        env = dict(self.env, PYTHONDONTWRITEBYTECODE="1")
        for cmd, want in (("rm -rf studio/local", "G-DEL False"), ("ls", "None True")):
            out = subprocess.run([sys.executable, "-B", "-c", code, json.dumps(self.hook("Bash", {"command": cmd}))],
                                 capture_output=True, text=True, env=env, cwd=self.repo)
            self.assertEqual(out.stdout.strip(), want, out.stderr[-800:])

    def test_legacy_error_is_head_text(self):  # test 3, Q4
        lj, _dec = backstop._legacy()
        saved = list(backstop._LEGACY)

        def boom(ctx, hook):
            raise KeyError("x")
        backstop._LEGACY[1] = boom
        try:
            deny, ctx = self.final("Bash", {"command": "ls"})
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
                self.final("Bash", {"command": "ls"})
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
        # guard.py's record: once per repository
        deny, ctx = self.final("Bash", {"command": "ls studio"})
        self.assertIsNone(deny)
        judge.record_run(ctx)
        with open(os.path.join(self.repo, ".claude", "studio", "local", "guard-ran.json")) as f:
            self.assertIn("sess-1", json.load(f)["sessions"])

    def test_shared_checks(self):  # test 7 (P20-4)
        lp, lc = backstop._frozen_checks()
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
                self.assertEqual(lp.check("/r", {"A": "1"}, args, set()), (None, ["w"]))  # the 0.0.26 guard's call
            backstop.shared_push("/r", {"A": "2"}, args, set())
            backstop.shared_push("/s", {"A": "1"}, args, set())
            self.assertEqual([c[0] for c in calls], ["push"] * 3)
            for extra in ({}, {}, {"GIT_DIR": "/x"}):
                self.assertEqual(backstop.shared_commit("/r", {}, extra, {"amend": False}), "outcome")
            self.assertEqual(len(calls), 5)
        finally:
            lp.check.__wrapped__, lc.evaluate.__wrapped__ = orig_p, orig_c
            backstop._MEMO.clear()
        # one decision: the check runs once for both guards (a real push)
        n = []

        def counting(*a, **kw):
            n.append(1)
            return orig_p(*a, **kw)
        lp.check.__wrapped__ = counting
        try:
            self.bash("git push")
        finally:
            lp.check.__wrapped__ = orig_p
        self.assertEqual(len(n), 1)

    def test_deadline(self):  # P20-8
        old = backstop.DEADLINE
        backstop.DEADLINE = -1.0
        try:
            deny = self.bash("ls")
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

    def test_no_effects_when_legacy_denies(self):  # test 4
        n, saved = self.writes()
        saved_l = self.forced_legacy_deny()
        try:
            deny, ctx = self.final("Bash", {"command": APPROVE})
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


class SourceSkip(BackstopCase):
    def g1ctx(self, cmd, cwd=None):
        d, ctx, _c = judge.decide_g1(self.hook("Bash", {"command": cmd}, cwd), self.env, snapshot_loader=self.loader,
                                     run_finish=False)
        return d, ctx

    def test_routes_to_a_source(self):  # §3.2, P20-5
        for cmd in ("source x; ls", ". x; ls", "builtin source x; ls", "noglob source x; ls", "command . x; ls",
                    "command source x; ls", "alias act='source .venv/bin/activate'\nact; ls",
                    "alias act='. x'\nact; ls", "emulate zsh -c 'source x'; ls", "emulate sh -c \"$X\"; ls",
                    'eval "$(pyenv init -)"; ls', "eval 'source x'; ls", "eval '. x'; ls",
                    "f(){ source x; }; f; ls", "if true; then source x; fi; ls", "( source x ); ls",
                    "for i in 1; do source x; done; ls", "source x | cat; ls"):
            _d, ctx = self.g1ctx(cmd)
            self.assertTrue(ctx.sourced, cmd)
            self.assertNotIn("ls", [c.prog for c in ctx.scan.commands], cmd)
        for cmd in ("./x.sh; ls", "sh -c 'source x'; ls", "f(){ source x; }; ls", "eval 'X=1'; ls",
                    "alias a='ls -l'\na; ls", "trap 'source x' EXIT; ls", "echo source; ls"):
            _d, ctx = self.g1ctx(cmd)
            self.assertIn("ls", [c.prog for c in ctx.scan.commands], cmd)
        # a nested string's source ends only that string (its own commands after it are not this guard's)
        _d, ctx = self.g1ctx("sh -c 'source x; rm -rf studio'; ls")
        self.assertTrue(ctx.sourced)
        self.assertIn("ls", [c.prog for c in ctx.scan.commands])

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

    def test_after_the_source_is_0026s(self):
        for cmd in ("source x; rm -rf studio/videos/v/work", "source .venv/bin/activate && git commit -m x",
                    "source /dev/null; echo x > ~[x]/studio/videos/v/work/state.json",
                    "source .venv/bin/activate && runit npm test && git status",
                    "if true; then source x; else rm -rf studio/local; fi"):
            d, ctx = self.g1ctx(cmd)
            self.assertTrue(ctx.sourced, cmd)
            self.assertIsNone(d, cmd)
            f = self.bash(cmd)
            l, lctx = self.legacy_only("Bash", {"command": cmd})
            self.assertEqual(f is None, l is None, cmd)
            if l is not None:
                self.assertEqual(f.message(), l.message(), cmd)  # 0.0.26's message, byte for byte

    def test_c20_1_rows_pass(self):  # C20-1: 0.0.26 passes them; this guard no longer judges after the source
        self.use_snapshot(functions=C20_FUNCS)
        for cmd in ("source .venv/bin/activate; gh pr view 1; for f in src/*.ts; do npx prettier --write $f; done",
                    "source .venv/bin/activate; gh pr view 1; for f in src/*.ts; do git add $f; done",
                    "source .venv/bin/activate; gh pr view 1; for f in $(git diff --name-only); do echo $f; done",
                    "source .venv/bin/activate; take build; cd ..; for f in src/*.ts; do echo $f; done",
                    "source .venv/bin/activate; for p in 1 2; do gh pr view $p; done; cat $LOG",
                    "source .venv/bin/activate; for i in a b; do mkcd $i; cd ..; done; echo $X"):
            self.assertPass(cmd)

    def test_uncalled_function_and_walk_order(self):
        _d, ctx = self.g1ctx("f(){ source x; rm -rf studio/local; }; ls")
        self.assertFalse(ctx.sourced)
        self.assertIn("ls", [c.prog for c in ctx.scan.commands])
        # a hook defined before the source runs after later commands; its body is read where it is defined (the
        # one walk order != run order the guard keeps; guard-limits): chpwd's source does not stop the walk
        _d, ctx = self.g1ctx("chpwd(){ source x; }; cd src; ls")
        self.assertFalse(ctx.sourced)
        # an EXIT trap runs at the end: its text is a nested string (its source ends that string only)
        _d, ctx = self.g1ctx("trap 'source x; rm -rf studio' EXIT; ls")
        self.assertIn("ls", [c.prog for c in ctx.scan.commands])

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

    def test_parity(self):  # test 11
        from stdo.guard.legacy.messages import Deny as LDeny
        rows = [(r, "repo") for r in BACKSTOP_PARITY]
        rows += [(c, "repo") for c, _r in MUST_DENY[::10]] + [(c, "repo") for c in MUST_PASS[::12]]
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, _cwd in rows:
                text = cmd.replace("{R}", self.repo)
                f, fctx = self.final("Bash", {"command": text})
                l, lctx = self.legacy_only("Bash", {"command": text})
                if l is not None:
                    self.assertIsNotNone(f, "0.0.26 refuses, the final passes: %s (%s)" % (cmd, mode))
                if fctx.sourced and cmd not in PARITY_G1_FIRST:
                    self.assertEqual(f is None, l is None, "%s (%s): %s / %s" % (cmd, mode, f, l))
                if f is not None and isinstance(f, LDeny):  # the 0.0.26 guard's answer: its message, byte for byte
                    self.assertEqual(f.message(fctx.denies), l.message(lctx.denies), cmd)
                if f is not None:
                    msg = f.message(fctx.denies)
                    self.assertTrue(msg.startswith("Studio guard ["), msg[:80])
                    self.assertLessEqual(len(msg), 1500)
