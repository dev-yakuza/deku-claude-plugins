"""M0d-1b judgement (m0d1b-plan v2 §6, §10): must-deny and must-pass lists, git previews, env rules,
approvals, Write/Edit/MCP, out-of-repo files. Real git only in temporary repositories."""

import json
import os
import re
import shlex
import shutil
import subprocess

import helpers
from guard_base import DEFAULT_ALIASES, DEFAULT_FUNCS, GuardCase, snapshot_text
from stdo import SCRIPTS_VERSION, paths
from stdo.guard import judge
from stdo.guard import snapshot as snapmod

FAKE_TOOLS = ("npm", "yarn", "pnpm", "make", "npx", "node", "gh", "python3", "rg", "s2v", "ffprobe", "open",
              "tsc", "curl", "jq", "tree", "trash", "watchexec", "entr", "nodemon", "nproc", "exiftool", "firebase")
ALIASES = DEFAULT_ALIASES + [("gst", "'git status'")]


class JudgeCase(GuardCase):
    def setUp(self):
        super().setUp()
        for t in FAKE_TOOLS:
            if not os.path.exists(os.path.join(self.bin, t)):
                self.exe(t)
        self.env["PATH"] = self.bin + ":/usr/bin:/bin"
        os.remove(os.path.join(self.bin, "git"))
        git = shutil.which("git", path="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")
        os.symlink(git, os.path.join(self.bin, "git"))
        self.repo = helpers.make_repo(self.tmp, name="studio-repo", harness=True)
        for d in ("studio/videos/v/work", "studio/local/videos/w/work", "studio/cast/a/character", "studio/voices/a",
                  "studio/videos/v/audio/ko", "src", ".claude/studio/scripts/stdo", "scripts", "node_modules", "dist"):
            os.makedirs(os.path.join(self.repo, d), exist_ok=True)
        for f, text in (("studio/videos/v/work/state.json", "{}"), ("studio/videos/v/script.md", "# s\n"),
                        ("src/a.ts", "x\n"), ("src/x.ts", "x\n"), ("a.txt", "a\n"), ("studio/CREDITS.yaml", "[]\n"),

                        ("scripts/x.py", "print(1)\n"), ("scripts/release.sh", "echo release\n"),
                        ("studio/cast/a/character/character.yaml", "a: 1\n")):
            p = os.path.join(self.repo, f)
            with open(p, "w") as fh:
                fh.write(text)
        # the repository copy of Studio's scripts: the plugin's own files (the guard checks the copy's version and
        # manifest on every Studio command — D-M0-3, M0f)
        from commit_base import copy_scripts
        copy_scripts(self.repo)
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "-m", "fixture files")
        self.snap_with = self.make_snapshot()
        self.mode = "with"

    def make_snapshot(self):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"]))
        snap = snapmod.load(self.env)
        shutil.rmtree(d)
        return snap

    def loader(self, env):
        return self.snap_with if self.mode == "with" else (None, ["snapshot-none"])

    def hook(self, tool, ti, cwd=None):
        return {"tool_name": tool, "tool_input": ti, "cwd": cwd or self.repo, "session_id": "sess-1",
                "transcript_path": None, "permission_mode": "default", "tool_use_id": "t1"}

    def decide(self, tool, ti, cwd=None, probe=None):
        deny, ctx = judge.decide(self.hook(tool, ti, cwd), self.env, probe=probe, snapshot_loader=self.loader)
        return deny

    def bash(self, cmd, cwd=None, **kw):
        return self.decide("Bash", {"command": cmd}, cwd, **kw)

    def g1(self, cmd, cwd=None):
        """fix20: this guard alone (without the 0.0.26 backstop and without effects)."""
        deny, _ctx, _complete = judge.decide_g1(self.hook("Bash", {"command": cmd}, cwd), self.env,
                                                snapshot_loader=self.loader, run_finish=False)
        return deny

    def assertPassOrKept(self, cmd, kept, cwd=None):
        """assertPass, or assertHeadRefusedKept for a row in `kept` (its text with the repository as <R>)."""
        if cmd.replace(self.repo, "<R>") in kept:
            return self.assertHeadRefusedKept(cmd, cwd=cwd)
        return self.assertPass(cmd, cwd)

    def assertHeadRefusedKept(self, cmd, rule=None, cwd=None):
        """fix20: 0.0.26 refused it and this guard passes it — refused in 0.0.27 by the backstop (decide), passed by
        this guard alone (decide_g1: kept for 0.0.28, which lifts the backstop class by class)."""
        g = self.g1(cmd, cwd)
        self.assertIsNone(g, "this guard alone should pass: %s (%s): %s" % (cmd, self.mode, g and g.message()))
        d = self.bash(cmd, cwd)
        self.assertIsNotNone(d, "the 0.0.26 guard should refuse: %s (%s)" % (cmd, self.mode))
        if rule:
            self.assertEqual(d.rule, rule, "%s: %s" % (cmd, d.message()))
        return d

    def assertDeny(self, cmd, rule=None, cwd=None):
        d = self.bash(cmd, cwd)
        self.assertIsNotNone(d, "should deny: %s (%s)" % (cmd, self.mode))
        if rule:
            self.assertEqual(d.rule, rule, "%s: %s" % (cmd, d.message()))
        return d

    def assertPass(self, cmd, cwd=None):
        d = self.bash(cmd, cwd)
        self.assertIsNone(d, "should pass: %s (%s): %s" % (cmd, self.mode, d and d.message()))


MUST_DENY = [
    ("echo x > studio/videos/v/work/state.json", "G-PROT"),
    ("sed -i '' s/a/b/ .claude/studio/config.json", "G-PROT"),
    ("cp a.txt studio/voices/x.wav", "G-PROT"),
    ("rm -rf studio/local", "G-DEL"),
    ("rm -rf studio", "G-DEL"),
    ("rm -rf *", "G-DEL"),
    ("mv studio/local /tmp/x", "G-DEL"),
    ("find studio -delete", "G-DEL"),
    ("find studio -name x -exec rm {} +", "G-DEL"),
    ("find studio/voices -execdir mv {} /tmp \\;", "G-DEL"),
    ("rsync -a --delete src/ ./", "G-DEL"),
    ("git stash -a", "G-STASH"),
    ("git add -f studio/local/x", "G-PROT"),
    ("git checkout -- studio/videos/v/work/state.json", "G-PROT"),
    ("python3 -c \"import shutil; shutil.rmtree('studio/local')\"", "G-OPAQUE"),
    ("bash -c 'rm -rf studio/local'", "G-DEL"),  # M1a W2: the string's commands are judged too
    ("cat > /tmp/gx.sh <<'EOF'\nrm -rf studio/local\nEOF\nbash /tmp/gx.sh", "G-DEL"),  # M1a X1: script files too
    ('eval "rm studio/x"', "G-OPAQUE"),
    ("X=$(echo s); rm -rf $X/local", "G-DEL"),
    ("S2V_TTS_PORT=1 s2v tts v.md", "G-ENV"),
    ("env -i s2v x", "G-ENV"),
    ("HOME=/tmp/x s2v x", "G-ENV"),
    ("S2V_STATE_DIR=/elsewhere s2v x", "G-ENV"),
    ("export S2V_HEAVY_LOCK_TOKEN=a; s2v tts v.md", "G-ENV"),
    ("unset S2V_TTS; s2v x", "G-ENV"),
    ("env -u S2V_ACTOR_LOCK_TOKEN s2v x", "G-ENV"),
    ("python3 .claude/studio/scripts/state.py approve v 1 --expect abc", "G-APPROVAL"),
    ("python3 .claude/studio/scripts/state.py credit x --expect a", "G-APPROVAL"),
    ("python3 .claude/studio/scripts/state.py frobnicate", "G-APPROVAL"),
    ("python3 .claude/studio/scripts/state.py next $V", "G-DYNARG"),
    ("python3 .claude/studio/scripts/lock.py actor-op a -- s2v character approve a", "G-APPROVAL"),
    ("python3 .claude/studio/scripts/lock.py run --kind tts -- cp a.txt studio/videos/v/work/state.json", "G-PROT"),
    ("s2v character build a --reset-derived", "G-APPROVAL"),
    ("s2v voice create a --candidates 1", "G-APPROVAL"),
    ("unset CLAUDE_CODE_SESSION_ID; git commit -m x", "G-MARKER"),
    ("env -u CLAUDECODE python3 .claude/studio/scripts/check_commit.py --staged", "G-MARKER"),
    ("STUDIO_SANDBOX=1 s2v x", "G-ENV"),
    ("STUDIO_HOME=/tmp/h s2v x", "G-ENV"),
    ("python3 - <<EOF\nopen('studio/videos/v/work/state.json','w')\nEOF", "G-OPAQUE"),
    ("bash -c 'cd studio && ls'", "G-OPAQUE"),
    ("python3 scripts/x.py studio/videos/v/work/state.json", "G-PROT"),
    ("dd if=/dev/zero of=studio/videos/v/work/state.json", "G-PROT"),
    ("cp --target-directory=studio/voices a.txt", "G-PROT"),
    ("rsync --backup-dir=studio/voices/b -a src/ dist/", "G-PROT"),
    ("tar --directory=studio/cast -xf a.tar", "G-PROT"),
    ("tar -xf a.tar -C studio/voices", "G-PROT"),
    ("cp a.txt studio/cast/a/character/", "G-PROT"),
    ("cp -t studio/voices a.txt", "G-PROT"),
    ("cp dist/state.json studio/videos/v/work/", "G-PROT"),
    ("echo x > studio/CREDITS.yaml", "G-PROT"),
    ("touch .claude/studio/charter.md", "G-PROT"),
]
# fix-0025 §1 (pilot-2 P11): sed shapes outside the allowlist, the 0.0.24 holes and the forms of plan reviews 1–10.
# {root} leads from the working folder to the repository root, {v} to studio/videos/v (test_pilot2_guard runs the
# list there too); {P} is a protected file. Rule None: the first deny depends on the folder (find's own judgement).
SED_DENY = [
    # the 0.0.24 holes
    ("sed 's/a/b/e' a.txt", "G-OPAQUE"), ("sed '1e touch x' a.txt", "G-OPAQUE"),
    ("sed -n '1w {P}' a.txt", "G-OPAQUE"), ("sed 's/a/b/w {v}work/state.json' a.txt", "G-OPAQUE"),
    ("sed -n \"1w $S2V_STATE_DIR/heavy.lock.d/owner.json\" a.txt", "G-OPAQUE"),
    ("sed '1r $S2V_STATE_DIR/heavy.lock.d/owner.json' a.txt", "G-OPAQUE"),
    ("sed '1R {v}../../cast/a/character/.work/op.lock.d/owner.json' a.txt", "G-OUT"),  # the word names it
    ("sed -n '1w {P}' -e p a.txt", "G-OPAQUE"), ("sed -i x '1w {P}' a.txt", "G-OPAQUE"),
    ("sed -i.json s/a/b/ {v}work/state", "G-OPAQUE"), ("sed 's/[/]/;a\\x' a.txt", "G-OPAQUE"),
    ("echo a.txt | xargs sed -n p", "G-OPAQUE"), ("find {root}src -name a.ts -exec sed -i '' s/a/b/ {{}} \\;", None),
    ("env sed -n '1w {P}' a.txt", "G-OPAQUE"), ("command sed 's/a/b/e' a.txt", "G-OPAQUE"),
    ("/usr/bin/sed -n '1w {P}' a.txt", "G-OPAQUE"), ("nohup sed -n '1w {P}' a.txt", "G-OPAQUE"),
    # options
    ("sed -ne p a.txt", "G-OPAQUE"), ("sed '-es/a/b/w {P}' a.txt", "G-OPAQUE"), ("sed -nf x.sed a.txt", "G-OPAQUE"),
    ("sed -fevil.sed a.txt", "G-OPAQUE"), ("sed --expression=p a.txt", "G-OPAQUE"),
    ("sed --in-place=.json s/a/b/ {v}work/state", "G-OPAQUE"), ("sed -l 5 p a.txt", "G-OPAQUE"),
    ("sed s/a/b/ {P} -i", "G-OPAQUE"),
    # w forms
    ("sed -n '1!w {P}' a.txt", "G-OPAQUE"), ("sed -n '$w {P}' a.txt", "G-OPAQUE"),
    ("sed -n '0~3w {P}' a.txt", "G-OPAQUE"),
    ("sed -n '1,+2w {P}' a.txt", "G-OPAQUE"), ("sed -n '/x/I w {P}' a.txt", "G-OPAQUE"),
    ("sed 's|a|b|w {P}' a.txt", "G-OPAQUE"), ("sed 's#a#b#gw {P}' a.txt", "G-OPAQUE"),
    ("sed -n 1wfile a.txt", "G-OPAQUE"),
    # the review-3 bracket scripts
    ("sed 's/[]/]/;/w D/p' a.txt", "G-OPAQUE"), ("sed 's/[[:alpha:]/]/;/w D/q' a.txt", "G-OPAQUE"),
    ("sed 's/[^]/]/;/w D/x' a.txt", "G-OPAQUE"),
    # wrappers
    ("xargs -I p sed -n p g", "G-OPAQUE"), ("find {root}src -name a.ts -exec sed -n '{{}}' g \\;", None),
    ("printf a | xargs sed -n p", "G-OPAQUE"), ("find {root}src -name a.ts -okdir sed -i '' s/a/b/ {{}} \\;", None),
    ("parallel sed -n p ::: a.txt", "G-OPAQUE"),
    # program names (APFS is case-insensitive); package runners stay writers
    ("SED -n '1w {P}' a.txt", "G-OPAQUE"), ("Sed 's/a/b/e' a.txt", "G-OPAQUE"),
    ("/usr/bin/SED -i x '1w {P}' a.txt", "G-OPAQUE"), ("npx sed -n p {v}work/state.json", "G-PROT"),
    # redirects of a read shape
    ("sed -n p a.txt > {v}work/state.json", "G-PROT"), ("sed -n p a.txt >> {v}work/state.json", "G-PROT"),
    # words and options
    ("sed -n \"${{N}}p\" a.txt", "G-OPAQUE"), ("sed p *", "G-OPAQUE"), ("sed -Ei '' p a.txt", "G-OPAQUE"),
    ("sed -iE p a.txt", "G-OPAQUE"), ("sed -n '1!!p' a.txt", "G-OPAQUE"),
    # size and growth
    ("sed -n '%s' a.txt" % ("p;" * 101), "G-OPAQUE"), ("sed '%s' a.txt" % ";".join(["s/.*/&&/"] * 4), "G-OPAQUE"),
    ("sed '%s' a.txt" % ";".join([r"s/\(.*\)/\1\1/"] * 4), "G-OPAQUE"), ("sed 's/a/\\0/' a.txt", "G-OPAQUE"),
    ("sed 'G;h;G;h;$p' a.txt", "G-OPAQUE"), ("sed x a.txt", "G-OPAQUE"),
    # blocks and addresses BSD reads otherwise
    ("sed -n '/x/{{p}}' a.txt", "G-OPAQUE"), ("sed -n '/a/{{p;q}}' a.txt", "G-OPAQUE"),
    ("sed -n '1{{p;}}2p' a.txt", "G-OPAQUE"), ("sed -n '0,/b/p' a.txt", "G-OPAQUE"),
    ("sed -n '00,/b/p' a.txt", "G-OPAQUE"), ("sed -n -i '' p a.txt", "G-OPAQUE"),
    # review 1 B1: an unquoted empty expansion is dropped by the shell (BSD then takes `p` as the -i suffix)
    ("X=; sed -i $X p '1w {P}' a.txt", "G-OPAQUE"), ("X=''; sed -i $X p '1w {P}' a.txt", "G-OPAQUE"),
    ("export X=; sed -i $X p '1w {P}' a.txt", "G-OPAQUE"), ("X=; sed -i ${{X}} p '1w {P}' a.txt", "G-OPAQUE"),
    ("X=; Y=$X; sed -i $Y p '1w {P}' a.txt", "G-OPAQUE"), ("X=; sed $X -n p a.txt", "G-OPAQUE"),
    ("X=; sed -n p $X a.txt", "G-OPAQUE"),
    # review 2 B2: a sed that may not be the system's is other; a system bin path is shaped whatever PATH is
    ("PATH=/usr/bin sed -n '1w {P}' a.txt", "G-OPAQUE"), ("PATH=/usr/bin:/bin sed 's/a/b/e' a.txt", "G-OPAQUE"),
    ("env -i sed -n '1w {P}' a.txt", "G-OPAQUE"), ("env -i /usr/bin/sed -n '1w {P}' a.txt", "G-OPAQUE"),
    ("env -u PATH /usr/bin/sed -n '1w {P}' a.txt", "G-OPAQUE"),
    ("export PATH=/usr/bin; sed -n '1w {P}' a.txt", "G-OPAQUE"), ("/tmp/sed -n '1w {P}' a.txt", "G-OPAQUE"),
    ("/usr/bin/../../tmp/sed -n p {v}work/state.json", "G-OPAQUE"), ("/usr//bin/sed -n p a.txt", "G-OPAQUE"),
    ("find {root}src -name a.ts -exec /usr/bin/../../tmp/sed -n p {{}} \\;", "G-OPAQUE"),
    # review 1 M1: an edit of a glob (judge_glob looks at one folder)
    ("sed -i '' s/a/b/ {root}.claude/*/config.json", "G-OPAQUE"),
    ("sed -i '' s/a/b/ {root}.c*/studio/config.json", "G-OPAQUE"), ("sed -i '' s/a/b/ {v}w*/state.json", "G-OPAQUE"),
    ("sed -i '' s/a/b/ {root}s*/videos/v/work/state.json", "G-OPAQUE"),
]
SED_P = "{root}.claude/studio/config.json"


def sed_deny(root, v):
    return [(t.format(P=SED_P.format(root=root), root=root, v=v), r) for t, r in SED_DENY]


MUST_DENY += sed_deny("", "studio/videos/v/")
# G1 (guard-runners-plan §1.1–§1.7a, §1.10; §5 RUNNER_DENY): runners and their options, refused runners, file
# arguments, busybox, program names in capitals, shell payloads, folders the guard cannot tell, unmodelled programs.
# G-DEL: the runner is unwrapped and `rm` judged; G-OPAQUE: refused.
NICE17 = "nice " * 17
RUNNER_DENY = [
    # options
    ("timeout inf rm -rf studio", "G-DEL"), ("timeout 1e1 rm -rf studio", "G-DEL"), ("timeout .5 rm -rf studio", "G-DEL"),
    ("timeout 0x5 rm -rf studio", "G-DEL"), ("timeout +3 rm -rf studio", "G-DEL"),
    ("stdbuf --output L rm -rf studio", "G-DEL"), ("stdbuf --output=L rm -rf studio", "G-DEL"),
    ("ionice --class 2 rm -rf studio", "G-DEL"), ("ionice -c2 -n7 rm -rf studio", "G-DEL"),
    ("nice --adjustment 5 rm -rf studio", "G-DEL"), ("nice -5 rm -rf studio", "G-DEL"),
    ("env -iu X rm -rf studio", "G-DEL"), ("env -C . -u X rm -rf studio", "G-DEL"),
    ("env -P /usr/bin rm -rf studio", "G-DEL"),
    # refused
    ("timeout --sig KILL 5 rm -rf studio", "G-OPAQUE"), ("env --argv1 x rm -rf studio", "G-OPAQUE"),
    ("nohup -x rm -rf studio", "G-OPAQUE"), ("script -t 0 log rm -rf studio", "G-OPAQUE"),
    ("sudo -h x rm -rf studio", "G-OPAQUE"), ("sudo -R / rm -rf studio", "G-OPAQUE"),
    ("arch -foo rm -rf studio", "G-OPAQUE"), ("busybox --install /tmp/b", "G-OPAQUE"),
    ("chroot / rm -rf studio", "G-OPAQUE"), ("unshare -r rm -rf studio", "G-OPAQUE"),
    ("su -c 'rm -rf studio'", "G-OPAQUE"), ("xargs --max-lines 1 rm -rf studio", "G-OPAQUE"),
    ("npx --weird rimraf studio", "G-OPAQUE"), ("BUILTIN rm -rf studio", "G-OPAQUE"),
    (NICE17 + "rm -rf studio", "G-OPAQUE"),
    # unwrapped
    ("flock /tmp/l rm -rf studio", "G-DEL"), ("flock -w 5 /tmp/l rm -rf studio", "G-DEL"),
    ("setsid -f rm -rf studio", "G-DEL"), ("arch -arm64 rm -rf studio", "G-DEL"),
    ("arch -e K=V -arm64 rm -rf studio", "G-DEL"), ("xcrun rm -rf studio", "G-DEL"),
    ("sandbox-exec -n no-network rm -rf studio", "G-DEL"), ("taskpolicy -c utility rm -rf studio", "G-DEL"),
    ("busybox rm -rf studio", "G-DEL"), ("busybox.static rm -rf studio", "G-DEL"), ("toybox rm -rf studio", "G-DEL"),
    ("busybox busybox rm -rf studio", "G-DEL"), ("busybox env rm -rf studio", "G-DEL"),
    ("script -F log rm -rf studio", "G-DEL"), ("script -q /dev/null rm -rf studio", "G-DEL"),
    ("/usr/bin/command rm -rf studio", "G-DEL"), ("COMMAND rm -rf studio", "G-DEL"),
    ("sudo --user root rm -rf studio", "G-DEL"), ("sudo -D studio rm -rf local", "G-DEL"),
    ("doas -u root rm -rf studio", "G-DEL"), ("gnice rm -rf studio", "G-DEL"), ("gtimeout 5 rm -rf studio", "G-DEL"),
    ("gstdbuf -oL rm -rf studio", "G-DEL"), ("gtime rm -rf studio", "G-DEL"), ("caffeinate -i rm -rf studio", "G-DEL"),
    ("chronic -e rm -rf studio", "G-DEL"), ("unbuffer -p rm -rf studio", "G-DEL"), ("nohup rm -rf studio", "G-DEL"),
    # shell payloads
    ("script -c 'rm -rf studio' log", "G-DEL"), ("script --command 'rm -rf studio' log", "G-DEL"),
    ("flock /tmp/l -c 'rm -rf studio'", "G-DEL"), ("watch 'rm -rf studio'", "G-DEL"),
    ("watch -n 1 -x rm -rf studio", "G-DEL"), ("npx -c 'rm -rf studio'", "G-DEL"),
    ("npm exec -c 'rm -rf studio'", "G-DEL"), ("pnpm exec -c 'rm -rf studio'", "G-DEL"),
    ("yarn exec 'rm -rf studio'", "G-DEL"), ("busybox sh -c 'rm -rf studio'", "G-DEL"),
    ("env -iS'rm -rf studio'", "G-DEL"),
    # file arguments
    ("/usr/bin/time -o studio/videos/v/work/state.json ls", "G-PROT"),
    ("\\time -o studio/videos/v/work/state.json ls", "G-PROT"),
    ("command time -o studio/videos/v/work/state.json ls", "G-PROT"),
    ("flock studio/videos/v/work/.state.lock ls", "G-PROT"), ("script -q studio/videos/v/work/state.json ls", "G-PROT"),
    ("script -O .claude/studio/config.json -c ls", "G-PROT"), ("sudo -e studio/videos/v/work/state.json", "G-PROT"),
    ("watch -s studio/voices ls", "G-PROT"),
    # busybox: extraction, sed
    ("busybox tar -xf a.tar -C dist", "G-PROT"), ("nohup busybox unzip a.zip", "G-PROT"),
    ("busybox sed -n p a.txt", "G-OPAQUE"),
    # capitals
    ("RM -rf studio", "G-DEL"), ("/BIN/RM -rf studio", "G-DEL"), ("MV studio/local /tmp/x", "G-DEL"),
    ("FIND studio -delete", "G-DEL"), ("GIT stash -a", "G-STASH"), ("RSYNC -a --delete src/ ./", "G-DEL"),
    ("ENV rm -rf studio", "G-DEL"), ("NOHUP rm -rf studio", "G-DEL"), ("Nice rm -rf studio", "G-DEL"),
    ("NPX rimraf studio", "G-DEL"), ("XARGS --arg-file cat rm -rf studio", "G-DEL"),
    # xargs
    ("xargs --arg-file cat rm -rf studio < /dev/null", "G-DEL"),
    ("xargs --process-slot-var cat rm -rf studio < /dev/null", "G-DEL"),
    # review 1
    ("lockf /tmp/l rm -rf studio", "G-DEL"), ("lockf -t 5 /tmp/l rm -rf studio", "G-DEL"),
    ("lockf studio/videos/v/work/.state.lock ls", "G-PROT"), ("sudo -k rm -rf studio", "G-DEL"),
    ("sudo -l rm -rf studio", "G-OPAQUE"), ("flock 3 rm -rf studio", "G-DEL"), ("doas -s", "G-OPAQUE"),
    ("exec -arm rm -rf studio", "G-DEL"), ("exec -cl rm -rf studio", "G-DEL"),
    # B2: `command cd` is the external cd (no POSIX_BUILTINS)
    ("command cd /tmp && rm -rf studio", "G-DEL"), ("command cd /tmp; touch studio/videos/v/work/state.json", "G-PROT"),
    # review 2 A: POSIX_BUILTINS on
    ("setopt posixbuiltins; command cd studio && rm -rf local", "G-DEL"),
    ("emulate sh -c 'command cd studio && rm -rf local'", "G-DEL"),
    # review 3 M1, review 4: folders the guard cannot tell (§1.7a)
    ("cd $UNKNOWN; rm -rf local", "G-DEL"), ("cd $UNKNOWN; rm -rf work", "G-DEL"),
    ("f() { cd studio; }; f; rm -rf local", "G-DEL"),
    ("emulate sh -c 'f() { command cd studio; }'; f; rm -rf local", "G-DEL"),
    ("cd studio; cd n1; cd n2; cd n3; cd n4; rm -rf local", "G-DEL"),
    ("cd studio; cd $A; cd $B; cd $C; cd $D; rm -rf local", "G-DEL"),
    ("cd x1; cd x2; cd x3; cd x4; cd x5; cd x6; cd x7; cd x8; cd studio; rm -rf local", "G-DEL"),
    ("cd $UNKNOWN; touch state.json", "G-PROT"),
    # refused runners
    ("expect -c 'spawn rm -rf studio'", "G-OPAQUE"), ("echo 'exec rm -rf studio' | tclsh", "G-OPAQUE"),
    ("echo 'syscmd(rm -rf studio)' | m4", "G-OPAQUE"), ("echo '!rm -rf studio' | dc", "G-OPAQUE"),
    ("ssh-agent rm -rf studio", "G-OPAQUE"), ("screen -dm rm -rf studio", "G-OPAQUE"),
    ("uv run rm -rf studio", "G-OPAQUE"), ("bundle exec rm -rf studio", "G-OPAQUE"),
    ("direnv exec . rm -rf studio", "G-OPAQUE"), ("mise exec -- rm -rf studio", "G-OPAQUE"),
    ("leaks --atExit -- rm -rf studio", "G-OPAQUE"), ("dtrace -c 'rm -rf studio' -n BEGIN", "G-OPAQUE"),
    ("lldb -o 'platform shell rm -rf studio'", "G-OPAQUE"), ("launchctl submit -l x -- /bin/rm -rf studio", "G-OPAQUE"),
    ("echo 'rm -rf studio' | at now", "G-OPAQUE"),
    # §1.10: programs the guard does not model
    ("watchexec -- rm -rf studio", "G-OPAQUE"), ("entr -s 'rm -rf studio'", "G-OPAQUE"),
    ("nodemon --exec 'mv studio/local /tmp/x'", "G-OPAQUE"),
    ("watchexec -- echo x > studio/videos/v/work/state.json", "G-PROT"),  # the outer redirect denies first
    ("watchexec -- git stash -a", "G-STASH"),
]
MUST_DENY += RUNNER_DENY


# G1 (§1.8, §1.9, §1.11, §2, §3; §5 MUST_DENY, GLOB_DENY, EMPTY_DENY): <root> leads from the working folder to the
# repository root (test_pilot2_guard runs the list under studio/videos/v, where the rule may differ: any deny)
G1_DENY = [
    # §1.8: zsh's tables, (e), ${=X}, zargs, csh, unparsable zsh forms (G-UNPARSE without a term)
    ('hash ls=/bin/rm; ls -rf <root>studio', 'G-OPAQUE'),
    ('hash -p /bin/rm ls; ls -rf <root>studio', 'G-OPAQUE'),
    ('commands[ls]=/bin/rm; ls -rf <root>studio', 'G-OPAQUE'),
    ("functions[ls]='rm -rf <root>studio'; ls", 'G-OPAQUE'),
    ("aliases[ls]=rm; eval 'ls -rf <root>studio'", 'G-OPAQUE'),
    ("echo ${(e):-'$(rm -rf <root>studio)'}", 'G-OPAQUE'),
    ("echo *(e:'rm -rf <root>studio':)", 'G-UNPARSE'),
    ('X=rm; ${=X} -rf <root>studio', 'G-OPAQUE'),
    ('autoload -U zargs; zargs -- <root>studio -- rm -rf', 'G-OPAQUE'),
    ("csh -c 'rm -rf <root>studio'", 'G-OPAQUE'),
    ("/bin/tcsh -c 'rm -rf <root>studio'", 'G-OPAQUE'),
    ('rm -rf <root>stu(d)io', 'G-UNPARSE'),
    ('rm -rf <root>stu(d|)io', 'G-UNPARSE'),
    ("repeat 1 rm -rf <root>stu''dio", 'G-UNPARSE'),
    ("repeat 1 touch <root>stu''dio/videos/v/work/state.json", 'G-UNPARSE'),
    ('setopt extendedglob; touch <root>studio/videos/v/work/^x.json', 'G-PROT'),
    # §1.9: command-valued options and variables (p4, p11); `-c core.fsmonitor`, `alias.*`, `core.hooksPath`:
    # today's G-HOOKOFF comes first
    ("ssh -o ProxyCommand='rm -rf studio' x", 'G-OPAQUE'),
    ("rsync -e 'rm -rf studio' a x:b", 'G-OPAQUE'),
    ("tar --use-compress-program='rm -rf studio' -cf x.tar a", 'G-OPAQUE'),
    ("tar -cf x.tar --to-command='rm -rf studio' a", 'G-OPAQUE'),
    ("zip -T -TT 'rm -rf studio' x.zip a", 'G-OPAQUE'),
    ("man -P 'rm -rf studio' ls", 'G-OPAQUE'),
    ("git -c core.editor='rm -rf studio #' commit", 'G-OPAQUE'),
    ("git -c core.fsmonitor='rm -rf studio' status", 'G-HOOKOFF'),
    ("git -c diff.external='rm -rf studio' diff", 'G-OPAQUE'),
    ("git -c core.sshCommand='rm -rf studio' fetch ssh://x/y", 'G-OPAQUE'),
    ("git -c alias.st='!rm -rf studio' st", 'G-HOOKOFF'),
    ('git -c core.hooksPath=/tmp/h commit -m x', 'G-HOOKOFF'),
    ("GIT_EDITOR='rm -rf studio #' git commit", 'G-OPAQUE'),
    ("EDITOR='rm -rf studio #' git commit", 'G-OPAQUE'),
    ("GIT_EXTERNAL_DIFF='rm -rf studio' git diff", 'G-OPAQUE'),
    ("GIT_SSH_COMMAND='rm -rf studio' git fetch", 'G-OPAQUE'),
    ("LESSOPEN='|rm -rf studio' less README.md", 'G-OPAQUE'),
    ("git rebase -x 'rm -rf studio' HEAD~1", 'G-OPAQUE'),
    ('git bisect run rm -rf studio', 'G-OPAQUE'),
    ("git difftool -x 'rm -rf studio' HEAD", 'G-OPAQUE'),
    ("git submodule foreach 'rm -rf studio'", 'G-OPAQUE'),
    ("make -f /dev/stdin <<< $'all:\\n\\trm -rf studio'", 'G-OPAQUE'),
    # review 2 A (options[…] is a table write, B) and B; pin: an arithmetic subscript is walked (G-DEL today)
    ('options[posixbuiltins]=on; command cd <root>studio && rm -rf local', 'G-OPAQUE'),
    ('commands=(ls /bin/rm); ls -rf <root>studio', 'G-OPAQUE'),
    (': ${commands[ls]::=/bin/rm}; ls -rf <root>studio', 'G-OPAQUE'),
    ("typeset 'commands[ls]=/bin/rm'; ls -rf <root>studio", 'G-OPAQUE'),
    ("read -r 'commands[ls]' <<< /bin/rm; ls -rf <root>studio", 'G-OPAQUE'),
    ("print -v 'commands[ls]' /bin/rm; ls -rf <root>studio", 'G-OPAQUE'),
    ('x=ls; commands[$x]=/bin/rm; ls -rf <root>studio', 'G-OPAQUE'),
    ("functions+=( ls 'rm -rf <root>studio' ); ls", 'G-OPAQUE'),
    ('saliases[txt]=rm', 'G-OPAQUE'),
    ('set -A aliases ls rm', 'G-OPAQUE'),
    ("setopt promptsubst; print -P '$(rm -rf <root>studio)'", 'G-OPAQUE'),
    ("setopt promptsubst; echo ${(%):-'$(rm -rf <root>studio)'}", 'G-OPAQUE'),
    ("zstyle -e ':x' k 'rm -rf <root>studio'; zstyle -s ':x' k out", 'G-OPAQUE'),
    ('(( a[$(rm -rf <root>studio)] = 1 ))', 'G-DEL'),
    # review 2 C: every git config route; git's and ssh's user config files (G-HOOKOFF, like .git/config)
    ("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.fsmonitor GIT_CONFIG_VALUE_0='rm -rf studio' git status", 'G-OPAQUE'),
    ('GIT_CONFIG_GLOBAL=/tmp/g git status', 'G-OPAQUE'),
    ('HOME=/tmp/h git status', 'G-OPAQUE'),
    ('XDG_CONFIG_HOME=/tmp/x git status', 'G-OPAQUE'),
    ('GIT_DIR=/tmp/fake git status', 'G-OPAQUE'),
    ("git config core.fsmonitor 'rm -rf studio'", 'G-OPAQUE'),
    ('git config --global core.fsmonitor x', 'G-OPAQUE'),
    ('git config --file /tmp/g core.fsmonitor x', 'G-OPAQUE'),
    ('git config include.path /tmp/g', 'G-HOOKOFF'),
    ("git config core.editor 'rm -rf studio #'", 'G-OPAQUE'),
    ('git config diff.external x', 'G-OPAQUE'),
    ("git config alias.st '!rm -rf studio'", 'G-HOOKOFF'),
    ("printf '[core]\\n\\tfsmonitor = x\\n' >> <root>.git/config", 'G-HOOKOFF'),
    ("printf '[core]\\n\\tfsmonitor = x\\n' >> ~/.gitconfig", 'G-HOOKOFF'),
    ("echo 'Host *' >> ~/.ssh/config", 'G-HOOKOFF'),
    ("git ls-remote --upload-pack='rm -rf studio #' .", 'G-OPAQUE'),
    ("git fetch --upload-pack='rm -rf studio #' .", 'G-OPAQUE'),
    ("git push --receive-pack='rm -rf studio #' .", 'G-OPAQUE'),
    ("git grep -O'rm -rf studio #' x", 'G-OPAQUE'),
    ("git archive --exec='rm -rf studio #' --remote=. HEAD", 'G-OPAQUE'),
    ("git send-email --sendmail-cmd='rm -rf studio' x.patch", 'G-OPAQUE'),
    # review 3 M2 (§1.11)
    ('uniq a.txt <root>studio/videos/v/work/state.json', 'G-PROT'),
    ('sort -o <root>studio/videos/v/work/state.json a.txt', 'G-PROT'),
    ('sort a.txt -o <root>studio/videos/v/work/state.json', 'G-PROT'),
    ('xxd a.txt <root>studio/videos/v/work/state.json', 'G-PROT'),
    ('tree -o <root>studio/videos/v/work/state.json src', 'G-PROT'),
    ('exiftool -Comment=x <root>studio/voices/a/x.wav', 'G-OPAQUE'),
    ('rg --pre rm x <root>studio', 'G-OPAQUE'),
    ('open <root>studio/../x.command', 'G-OPAQUE'),
    ('open -a Terminal .', 'G-OPAQUE'),
    ('file -C -m x', 'G-OPAQUE'),
    ('ffprobe -report a.wav', 'G-OPAQUE'),
    # review 3 M3
    ("GIT_ALLOW_PROTOCOL=ext git ls-remote 'ext::sh -c rm% -rf% studio'", 'G-OPAQUE'),
    ("git -c protocol.allow=always ls-remote 'ext::sh -c rm% -rf% studio'", 'G-OPAQUE'),
    ("git ls-remote 'ext::sh -c rm% -rf% studio'", 'G-OPAQUE'),
    ('git clone --template=/tmp/t /tmp/r sub', 'G-OPAQUE'),
    ('GIT_TEMPLATE_DIR=/tmp/t git clone /tmp/r sub', 'G-OPAQUE'),
    ('GIT_EXEC_PATH=/tmp/x git mergetool', 'G-OPAQUE'),
    ('git --exec-path=/tmp/x status', 'G-HOOKOFF'),
    ('export XDG_CONFIG_HOME=/tmp/x; git status', 'G-OPAQUE'),
    ("export GIT_EDITOR='rm -rf studio #'; git commit", 'G-OPAQUE'),
    ('git config init.templateDir /tmp/t', 'G-OPAQUE'),
    ("printf '[core]\\n\\tfsmonitor = x\\n' >> <root>.git/config.worktree", 'G-HOOKOFF'),
    ('git config extensions.worktreeConfig true', 'G-OPAQUE'),
    # review 3 M4
    ('fpath=(/tmp/f $fpath); autoload -U ls; ls -rf <root>studio', 'G-OPAQUE'),
    ('autoload -Uz /tmp/f/ls; ls -rf <root>studio', 'G-OPAQUE'),
    ('FPATH=/tmp/f; autoload ls; ls -rf <root>studio', 'G-OPAQUE'),
    ('module_path=(/tmp/m); zmodload x', 'G-OPAQUE'),
    ('zmodload zsh/files; rm -rf <root>studio', 'G-OPAQUE'),
    ('zmodload zsh/mapfile', 'G-OPAQUE'),
    # review 4
    ('git clone -c core.hooksPath=/tmp/h /tmp/r sub', 'G-OPAQUE'),
    ("git clone --config core.fsmonitor='rm -rf studio' /tmp/r sub", 'G-OPAQUE'),
    ("zmodload zsh/datetime; strftime -s 'commands[ls]' /bin/rm 0; ls -rf <root>studio", 'G-OPAQUE'),
    ("n='commands[ls]'; : ${(P)n::=/bin/rm}; ls -rf <root>studio", 'G-OPAQUE'),
    ("zstyle ':x' k /bin/rm; zstyle -s ':x' k 'commands[ls]'; ls -rf <root>studio", 'G-OPAQUE'),
    ("zformat -f 'commands[ls]' /bin/rm", 'G-OPAQUE'),
    ('exiftool -o x.wav <root>studio/voices/a/x.wav', 'G-OPAQUE'),
    ('exiftool -tagsFromFile a.wav <root>studio/voices/a/x.wav', 'G-OPAQUE'),
    ('cd $UNKNOWN; touch state.json', 'G-PROT'),
    # review 3 MINOR, review 2 E (G-OPAQUE)
    ('setopt $O; rm -rf <root>studio/local', 'G-OPAQUE'),
    ('setopt $O; ls', 'G-OPAQUE'),
    ("LESSOPEN='|x %s' less a.txt", 'G-OPAQUE'),
    ("export PAGER='rm -rf studio #'", 'G-OPAQUE'),
    ("VIMINIT='!rm -rf studio' GIT_EDITOR=vi git commit", 'G-OPAQUE'),
    ('GIT_EDITOR=/tmp/vi git commit', 'G-OPAQUE'),
    ("GIT_EDITOR='vi -c x' git commit", 'G-OPAQUE'),
    ('PATH=/tmp:$PATH GIT_EDITOR=vi git commit', 'G-OPAQUE'),
    ("export EDITOR='rm -rf studio #'", 'G-OPAQUE'),
    # reviews 6 and 7
    ("autoload -U zcalc; zcalc -e '$(rm -rf <root>studio)'", 'G-OPAQUE'),
    ("autoload -U zmv; zmv -p rm -o -rf 'stud*' 'x'", 'G-OPAQUE'),
    ("autoload -U regexp-replace; regexp-replace 'commands[ls]' cat rm; ls -rf <root>studio", 'G-OPAQUE'),
    ('EXIFTOOL_HOME=/tmp/e exiftool a.wav', 'G-OPAQUE'),
    # §2 GLOB_DENY; `cp a.txt studio/videos/*/notes.md` is listed under MUST_PASS in the plan but its `*` may be
    # `voices` (P-VOICE `<sr>/**/voices/**`): the two-pattern rule denies it (fail closed)
    ('touch <root>.claude/*/config.json', 'G-PROT'),
    ('touch <root>.c*/studio/config.json', 'G-PROT'),
    ('touch <root>s*/videos/v/work/state.json', 'G-PROT'),
    ('echo x > <root>.claude/*/config.json', 'G-PROT'),
    ('touch <root>.claude/studio/*/config.internal.json', 'G-PROT'),
    ('cp a.txt <root>studio/**/state.json', 'G-PROT'),
    ('rm -rf <root>s*/local', 'G-DEL'),
    ('rm -rf <root>.claude/stu*', 'G-DEL'),
    ('touch <root>studio/videos/?/work/state.json', 'G-PROT'),
    ('touch <root>studio/videos/v/work/[^x]tate.json', 'G-PROT'),
    ('touch <root>studio/videos/v/work/st[[:alpha:]]te.json', 'G-PROT'),
    ('touch <root>studio/videos/v/work/[!x]tate.json', 'G-PROT'),
    ('touch <root>studio/videos/v/work/stat?.json', 'G-PROT'),
    ('touch <root>.CLAUDE/*/config.json', 'G-PROT'),
    ('cp a.txt <root>studio/videos/*/notes.md', 'G-PROT'),
    # §3 EMPTY_DENY (the readings: dropped words first, then the no-drop reading, then today's reading with known-
    # empty words kept)
    ('X=; timeout $X 5 rm -rf <root>studio', 'G-DEL'),
    ('X=; $X rm -rf <root>studio', 'G-DEL'),
    ('X=; nohup $X rm -rf <root>studio', 'G-DEL'),
    ('X=; git $X stash -a', 'G-STASH'),
    ('X=; git -C $X stash -a', 'G-STASH'),
    ('git $UNSET stash -a', 'G-STASH'),
    ('rm -rf $(true) <root>studio', 'G-DEL'),
    ('git -C $A $B stash -a', 'G-RESET'),
    ('git -c $A $B stash -a', 'G-STASH'),
    ('nice -n $A $B rm -rf <root>studio', 'G-DEL'),
    ('rm $A -rf <root>studio', 'G-DEL'),
    ('git $1 $2 $3 $4 stash -a', 'G-OPAQUE'),
    ('cp $@ <root>studio/voices/', 'G-OPAQUE'),
    ("X='*'; cp ${~X} <root>studio/voices/", 'G-OPAQUE'),
    ('rm -rf $1 $2 $3 $4 <root>studio', 'G-DEL'),
    ('rm -rf $@ <root>studio', 'G-DEL'),
]


# G1 implementation review 1 (scratchpad/reviewG1impl review1-bypass.md, review1-conf.md): every command of the
# reports, by finding
G1_REVIEW1_DENY = [
    # B1: a `**` glob listed: the operand roles are read on the matches (earlier matches are mv/rsync sources)
    ('mv a.txt <root>**/work/', 'G-DEL'), ('mv a.txt <root>**/videos/', 'G-DEL'),
    ('rsync -a --remove-source-files a.txt <root>**/work/', 'G-DEL'),
    ('rsync -a --remove-source-files a.txt <root>studio/videos/v/work other/', 'G-DEL'),
    # M1: the last env -C / sudo -D is the run folder
    ('env -C <root>src -C <root>studio rm -rf local', 'G-DEL'),
    ('env --chdir=<root>src --chdir=<root>studio rm -rf local', 'G-DEL'),
    ('sudo -D <root>src -D <root>studio rm -rf local', 'G-DEL'),
    # M2: words are paths in the run folder
    ('env -C <root>studio/videos/v/work truncate -s0 state.json', 'G-PROT'),
    ('sudo -D <root>studio/videos/v/work touch state.json', 'G-PROT'),
    ('env -C <root>.claude/studio touch config.json', 'G-PROT'),
    # M3: a run folder the guard cannot read is unknown (§1.7a)
    ('env -C $D rm -rf local', 'G-DEL'), ('sudo -D $D rm -rf local', 'G-DEL'), ('env -C $D touch state.json', 'G-PROT'),
    # M4: a reading refused for another cause than the dropped option value stays refused
    ('X=; timeout -s $X KILL --sig KILL 5 s2v character build a --reset-derived', 'G-OPAQUE'),
    ("X=; timeout -s $X KILL --sig KILL 5 env GIT_EDITOR='rm -rf studio #' git commit", 'G-OPAQUE'),
    # M5: npm options before the subcommand, npm_config_call
    ("npm --call='rm -rf <root>studio' exec", 'G-DEL'), ("npm_config_call='rm -rf <root>studio' npm exec", 'G-DEL'),
    ("NPM_CONFIG_CALL='rm -rf <root>studio' npm exec", 'G-DEL'), ('npm --yes exec rimraf <root>studio', 'G-DEL'),
    # M6: §1.9 variables written by other routes than an assignment
    ("export GIT_EDITOR=vi; read GIT_EDITOR <<< 'rm -rf studio #'; git commit", 'G-OPAQUE'),
    ("for GIT_EDITOR in 'rm -rf studio #'; do git commit; done", 'G-OPAQUE'),
    ("export GIT_EDITOR=vi; for GIT_EDITOR in 'rm -rf studio #'; do git commit; done", 'G-OPAQUE'),
    ("print -v GIT_EDITOR 'rm -rf studio #'; export GIT_EDITOR; git commit", 'G-OPAQUE'),
    ("export GIT_EDITOR=vi; : ${GIT_EDITOR::='rm -rf studio #'}; git commit", 'G-OPAQUE'),
    ("export GIT_EDITOR=vi; GIT_EDITOR[1,-1]='rm -rf studio #'; git commit", 'G-OPAQUE'),
    ('export GIT_EDITOR=vi; set -A GIT_EDITOR rm -rf studio; git commit', 'G-OPAQUE'),
    ("export GIT_EDITOR=vi; zformat -f GIT_EDITOR 'rm -rf studio #'; git commit", 'G-OPAQUE'),
    ("export GIT_EDITOR=vi; printf -v GIT_EDITOR '%s' 'rm -rf studio #'; git commit", 'G-OPAQUE'),
    ('export GIT_EDITOR=vi; vared GIT_EDITOR; git commit', 'G-OPAQUE'),
    ('export GIT_EDITOR=vi; getopts x GIT_EDITOR; git commit', 'G-OPAQUE'),
    ('export GIT_EDITOR=vi; select GIT_EDITOR in x; do git commit; done', 'G-OPAQUE'),
    ('read HOME <<< /tmp/h; git status', 'G-OPAQUE'),
    # M7: git's long-option abbreviations
    ("git rebase --exe 'rm -rf studio' HEAD~1", 'G-OPAQUE'), ("git ls-remote --upload-p='rm -rf studio #' .", 'G-OPAQUE'),
    ("git fetch --upload-p='rm -rf studio #' .", 'G-OPAQUE'), ("git push --receive-p='rm -rf studio #' .", 'G-OPAQUE'),
    ("git grep --open-files='rm -rf studio #' x", 'G-OPAQUE'), ("git difftool --extc='rm -rf studio #' HEAD", 'G-OPAQUE'),
    ('git clone --templ=/tmp/t /tmp/r sub', 'G-OPAQUE'),
    ("git archive --exe='rm -rf studio #' --remote=. HEAD", 'G-OPAQUE'),
    ("git send-email --sendmail-c='rm -rf studio' x.patch", 'G-OPAQUE'),
    # M8: a renamed section moves its keys
    ("git config x.fsmonitor 'rm -rf studio'; git config --rename-section x core; git status", 'G-OPAQUE'),
    ('git config rename-section x core', 'G-OPAQUE'),
    ("git config foo.st '!rm -rf studio'; git config --rename-section foo alias; git st", 'G-OPAQUE'),
    # M9, C-M2: a -c key or value the guard cannot read
    ('git -c core.hooksPath=$A commit -m x', 'G-HOOKOFF'), ('git -c $A commit -m x', 'G-OPAQUE'),
    ('git -c core.editor=$A commit', 'G-OPAQUE'), ('git -c $A status', 'G-OPAQUE'),
    ('git -c core.fsmonitor="$(echo x)" status', 'G-HOOKOFF'), ('git -c "$(echo core.fsmonitor=x)" status', 'G-OPAQUE'),
    ('git -c core.editor=$E commit', 'G-OPAQUE'),
    ('git clone -c "$(echo core.hooksPath=/tmp/h)" /tmp/r sub', 'G-OPAQUE'),
    ('git clone --config="$(echo core.hooksPath=/tmp/h)" /tmp/r sub', 'G-OPAQUE'),
    ('git clone --config "$(echo core.hooksPath=/tmp/h)" /tmp/r sub', 'G-OPAQUE'),
    # M10: tar and sort abbreviations
    ("tar -cf x.tar --use-compress-prog='rm -rf studio' a.txt", 'G-OPAQUE'),
    ('tar -cf x.tar --use-comp=/tmp/evil a.txt', 'G-OPAQUE'), ('bsdtar -cf x.tar --use-compress-prog=/tmp/evil a.txt', 'G-OPAQUE'),
    ('sort --compress-prog=/tmp/evil -S1 a.txt', 'G-OPAQUE'),
    ('sort --out=<root>studio/videos/v/work/state.json a.txt', 'G-PROT'),
    ('sort --outp <root>studio/videos/v/work/state.json a.txt', 'G-PROT'),
    # M11: §1.11 option reading
    ('tree -fo <root>studio/videos/v/work/state.json src', 'G-PROT'),
    ('uniq -cf 1 a.txt <root>studio/videos/v/work/state.json', 'G-PROT'),
    ('xxd -R never a.txt <root>studio/videos/v/work/state.json', 'G-PROT'),
    ('exiftool -lang -Comment=x <root>studio/voices/a/x.wav', 'G-OPAQUE'),
    ('exiftool -charset -Comment=x <root>studio/voices/a/x.wav', 'G-OPAQUE'),
    # M12: nested (e) flags
    ("X='$(rm -rf studio)'; echo ${${(e)X}}", 'G-OPAQUE'), ("X='$(rm -rf studio)'; echo ${Y:-${(e)X}}", 'G-OPAQUE'),
    ("X='$(rm -rf studio)'; echo ${X:+${(e)X}}", 'G-OPAQUE'), ("X='$(rm -rf studio)'; echo ${X//a/${(e)X}}", 'G-OPAQUE'),
    ("X='$(rm -rf studio)'; echo ${X/(#m)*/${(e)MATCH}}", 'G-OPAQUE'),
    # M13: vcs_info runs the command its zstyle names
    ("zstyle ':vcs_info:*' command scripts/release.sh; autoload -Uz vcs_info; vcs_info", 'G-OPAQUE'),
    # M14: find starts after a word the guard cannot read
    ('find $A <root>studio -delete', 'G-DEL'), ('find $A <root>studio -exec rm -rf {} +', 'G-DEL'),
    ('find $(true) <root>studio -delete', 'G-DEL'),
    # m5: an environment the guard cannot read is in effect for git
    ('env --env0-from=x.env git commit', 'G-OPAQUE'),
    # C-M3: arrays assigned in the call give several words
    ('a=(x <root>studio/local); mv $a /tmp/', 'G-OPAQUE'),
    ('a=(a.txt <root>studio/videos/v/work/state.json); cp $a', 'G-OPAQUE'),
]


# G1 implementation review 2 (scratchpad/reviewG1impl review2-bypass.md, review2-conf.md): every command of the
# reports, by finding (the commands from outside the repository are in NESTED_OUT_DENY; the case-insensitive files
# and the snapshot functions in G1Review2)
G1_REVIEW2_DENY = [
    # B-1: `.`, `..` and a wildcard under a folder the guard cannot tell may be the studio root or a folder above it
    ('cd $D; rm -rf .', 'G-DEL'), ('cd $D; find . -delete', 'G-DEL'),
    ('f() { cd <root>studio; }; f; rm -rf .', 'G-DEL'),
    ("sh -c 'cd $D; rm -rf .'", 'G-DEL'), ('env -C "$D" rm -rf .', 'G-DEL'), ('env -C "$D" rm -rf ./', 'G-DEL'),
    ('env -C "$D" rm -rf ..', 'G-DEL'), ('env -C "$D" rm -rf ../..', 'G-DEL'), ('env -C "$D" rm -rf */', 'G-DEL'),
    ('env -C "$D" rm -rf -- *', 'G-DEL'), ('env -C "$D" find . -delete', 'G-DEL'),
    ('env -C "$D" find . -exec rm -rf {} +', 'G-DEL'), ('env -C "$D" mv * /tmp/x', 'G-DEL'),
    ('env -C "$D" mv . /tmp/x', 'G-DEL'),
    # B-2: a wildcard in a destination folder keeps its "into this folder" reading
    ('cp /tmp/state.json <root>studio/videos/?/work/', 'G-PROT'),
    ('cp /tmp/state.json <root>s*/videos/v/work/', 'G-PROT'),
    ('cp /tmp/state.json <root>studio/vid*/v/work/', 'G-PROT'), ('mv /tmp/state.json <root>s*/videos/v/work', 'G-PROT'),
    ('ln -sf /tmp/state.json <root>s*/videos/v/work/', 'G-PROT'),
    ('install /tmp/state.json <root>s*/videos/v/work/', 'G-PROT'),
    ('rsync /tmp/state.json <root>s*/videos/v/work/', 'G-PROT'),
    ('cp -r /tmp/x/. <root>s*/videos/v/work', 'G-PROT'), ('cp -r /tmp/x/. <root>stu?io', 'G-PROT'),
    ('cp -r /tmp/x/. <root>s*', 'G-PROT'), ('cp -r /tmp/x/. <root>.c*', 'G-PROT'), ('cp -r /tmp/x/. <root>*', 'G-PROT'),
    ('cp -a /tmp/x/. <root>stu?io/local', 'G-PROT'), ('ln -sfn /tmp/x <root>s*/videos/v/work', 'G-PROT'),
    ('cp /tmp/state.json <root>**/v/../v/work/', 'G-PROT'), ('mv /tmp/state.json <root>**/v/../v/work/', 'G-PROT'),
    # M1: strings run in a run folder the guard cannot tell
    ("sudo -D $D sh -c 'rm -rf local'", 'G-OPAQUE'), ('env -C "$D" sh -c \'rm -rf local\'', 'G-OPAQUE'),
    ("env -C $D -- sh -c 'rm -rf local'", 'G-OPAQUE'), ('env -C "$D" bash -c \'rm -rf work\'', 'G-OPAQUE'),
    ('env -C "$D" nohup sh -c \'rm -rf local\'', 'G-OPAQUE'), ('env -C "$D" sh <<< \'rm -rf local\'', 'G-OPAQUE'),
    ('env -C "$D" flock /tmp/l -c \'rm -rf local\'', 'G-OPAQUE'), ('env -C "$D" npx -c \'rm -rf local\'', 'G-OPAQUE'),
    ('env -C "$D" env -S \'rm -rf local\'', 'G-OPAQUE'), ('env -C "$D" find . -exec rm -rf local \\;', 'G-DEL'),
    # M2: a value the runner may read as a number keeps the refusal
    ("X=; timeout -k $X ' 5' --sig=KILL 10 s2v character build a --reset-derived", 'G-OPAQUE'),
    ("X=; timeout -k $X 0x1p1 --sig=KILL 10 s2v character build a --reset-derived", 'G-OPAQUE'),
    ("X=; timeout -k $X ' 5' --sig=KILL 10 env GIT_EDITOR='rm -rf studio #' git commit", 'G-OPAQUE'),
    ('X=; env -C $X -Z rm -rf <root>studio', 'G-OPAQUE'), ('X=; env -C $X --bogus rm -rf <root>studio', 'G-OPAQUE'),
    # M3: a parameter name attached to its option
    ("print -v'commands[ls]' /bin/rm; ls -rf <root>studio", 'G-OPAQUE'),
    ("print -rv'functions[ls]' 'rm -rf <root>studio'; ls", 'G-OPAQUE'),
    ('set -Acommands ls /bin/rm; ls -rf <root>studio', 'G-OPAQUE'),
    ('set +Acommands ls /bin/rm; ls -rf <root>studio', 'G-OPAQUE'),
    ("strftime -s'commands[ls]' /bin/rm 0; ls -rf <root>studio", 'G-OPAQUE'),
    ("print -vGIT_EDITOR 'rm -rf studio #'; export GIT_EDITOR; git commit", 'G-OPAQUE'),
    ('strftime -sGIT_EDITOR x 0; export GIT_EDITOR; git commit', 'G-OPAQUE'),
    ('zparseopts -Acommands a; ls', 'G-OPAQUE'),
    ('zparseopts -AGIT_EDITOR a; export GIT_EDITOR; git commit', 'G-OPAQUE'),
    # M4: tied parameters
    ("typeset -T GIT_EDITOR ge ' '; ge=(rm -rf studio '#'); export GIT_EDITOR; git commit", 'G-OPAQUE'),
    ("typeset -Tx GIT_EDITOR ge ' '; ge=(rm -rf studio '#'); git commit", 'G-OPAQUE'),
    ("typeset -T PAGER pg ' '; pg=(sh -c 'rm -rf studio'); export PAGER; git log", 'G-OPAQUE'),
    ('typeset -T x commands; ls', 'G-OPAQUE'),
    # M5: -c in a short-option cluster of git clone
    ('git clone -qc core.hooksPath=/tmp/h /tmp/r sub', 'G-OPAQUE'),
    ('git clone -qccore.hooksPath=/tmp/h /tmp/r sub', 'G-OPAQUE'),
    ('git clone -nc core.hooksPath=/tmp/h /tmp/r sub', 'G-OPAQUE'),
    # M6: a section renamed into a two-part key pattern
    ('git config x.path /tmp/e.cfg; git config --rename-section x includeIf.onbranch:main; git status', 'G-OPAQUE'),
    # M7: send-email's one-dash long options (Getopt::Long)
    ("git send-email -sendmail-cmd='rm -rf studio' x.patch", 'G-OPAQUE'),
    ("git send-email -sendm='rm -rf studio' x.patch", 'G-OPAQUE'),
    ("git send-email -to-cmd='rm -rf studio' x.patch", 'G-OPAQUE'),
    ("git send-email -cc-cmd 'rm -rf studio' x.patch", 'G-OPAQUE'),
    ("git send-email -header-cmd='rm -rf studio' x.patch", 'G-OPAQUE'),
    ('git send-email -smtp-server=/tmp/evil x.patch', 'G-OPAQUE'),
    ('git send-email -smtp-s /tmp/evil x.patch', 'G-OPAQUE'),
    # M8: (e) behind a delimited flag argument, and array values
    ("X='$(rm -rf studio)'; echo ${(s(x)e)X}", 'G-OPAQUE'), ("X='$(rm -rf studio)'; arr=(\"${(e)X}\")", 'G-OPAQUE'),
    ("X='$(rm -rf studio)'; arr=(${(e)X})", 'G-OPAQUE'), ("X='$(rm -rf studio)'; arr+=(\"${(e)X}\")", 'G-OPAQUE'),
    ("X='$(rm -rf studio)'; typeset -a arr=(\"${(e)X}\")", 'G-OPAQUE'),
    ("X='$(rm -rf studio)'; arr=([k]=${(e)X})", 'G-OPAQUE'),
    ('a=($(rm -rf <root>studio))', 'G-DEL'), ('a=(`rm -rf <root>studio`)', 'G-DEL'),
    # M9: zstyle patterns that may match vcs_info's context
    ("zstyle -- ':vcs_info:*' command scripts/release.sh; autoload -Uz vcs_info; vcs_info", 'G-OPAQUE'),
    ("zstyle ':v(c)s_info:*' command scripts/release.sh; autoload -Uz vcs_info; vcs_info", 'G-OPAQUE'),
    ("zstyle ':vcs_(info|x):*' command scripts/release.sh; autoload -Uz vcs_info; vcs_info", 'G-OPAQUE'),
    ("zstyle ':vcs\\_info:*' command scripts/release.sh; autoload -Uz vcs_info; vcs_info", 'G-OPAQUE'),
    # M10: rsync's older name of --remove-source-files
    ('rsync -a --remove-sent-files <root>studio/videos/v/work/ /tmp/x/', 'G-DEL'),
    # M11: a wildcard extraction folder
    ('tar -xf /tmp/a.tar -C <root>stu?io', 'G-PROT'), ('tar -xf /tmp/a.tar -C <root>s*/videos/v/work', 'G-PROT'),
    ('tar -xf /tmp/a.tar -C <root>**/work', 'G-PROT'), ('tar -xf /tmp/a.tar --directory <root>stu?io', 'G-PROT'),
    ('tar -xf /tmp/a.tar -C<root>stu?io', 'G-PROT'), ('bsdtar -xf /tmp/a.tar -C <root>stu?io', 'G-PROT'),
    ('unzip -o /tmp/a.zip -d <root>s*/videos/v/work', 'G-PROT'), ('unzip -o /tmp/a.zip -d <root>stu?io', 'G-PROT'),
    ('ditto /tmp/x <root>s*/local', 'G-PROT'),
    # M12: a wildcard cd or run folder is a folder the guard cannot tell
    ('cd <root>stu?io; rm -rf local', 'G-DEL'), ('pushd <root>stu?io; rm -rf local', 'G-DEL'),
    ('cd <root>s*/videos/v/work; rm -f state.json', 'G-DEL'), ('cd <root>**/work && truncate -s0 state.json', 'G-PROT'),
    ('env -C <root>stu?io rm -rf local', 'G-DEL'), ('sudo -D <root>s*/videos/v/work rm -f state.json', 'G-DEL'),
    ('git -C <root>stu?io stash -a', 'G-RESET'), ('git -C <root>stu?io clean -fdx', 'G-CLEAN'),
    ('env -C $D git stash -a', 'G-RESET'), ('env -C $D git clean -fdx', 'G-CLEAN'),
    ('env -C "$D" git rm -rf .', 'G-RESET'),
    # M13: a pattern from a value with a glob qualifier that runs code
    ("X='a.txt(e:rm -rf studio:)'; echo $~X", 'G-OPAQUE'), ("X='a.txt(e:rm -rf studio:)'; echo ${~X}", 'G-OPAQUE'),
    ("X='a.txt(e:rm -rf studio:)'; echo ${(~)X}", 'G-OPAQUE'),
    ("setopt globsubst; X='a.txt(e:rm -rf studio:)'; echo $X", 'G-OPAQUE'), ('echo $~UNSET', 'G-OPAQUE'),
    # M15: make -f - in a short-option cluster
    ('make -sf - x', 'G-OPAQUE'), ('make -kf /dev/stdin x', 'G-OPAQUE'), ('make -if- x', 'G-OPAQUE'),
    ('make -C <root>src -sf - x', 'G-OPAQUE'), ("make -sf - x <<< 'x:; rm -rf studio'", 'G-OPAQUE'),
    # M16: --checkpoint-action with its value as the next word
    ("tar -cf x.tar --checkpoint=1 --checkpoint-action exec='rm -rf studio' a.txt", 'G-OPAQUE'),
]


# G1 implementation review 3 (scratchpad/reviewG1impl3 review3-bypass.md, review3-conf.md): every command of the
# reports fixed in the repository (the decoy lists from outside are in NESTED_OUT_DENY and G1Review3; the snapshot
# functions in G1Review3)
G1_REVIEW3_DENY = [
    # bypass M1: npm reads any start of --call, with any number of dashes, before and after the subcommand
    ("npm exec --c='rm -rf <root>studio'", 'G-DEL'), ("npx --c='rm -rf <root>studio'", 'G-DEL'),
    ("npm --c='rm -rf <root>studio' exec", 'G-DEL'), ("npm x --c='rm -rf <root>studio'", 'G-DEL'),
    ("npx --c 'rm -rf <root>studio'", 'G-DEL'), ("npm --c 'rm -rf <root>studio' exec", 'G-DEL'),
    ("npx ---c='rm -rf <root>studio'", 'G-DEL'), ("npm exec --cal='rm -rf <root>studio'", 'G-DEL'),
    # bypass M2: leaks' one-dash -atExit
    ('leaks -atExit -- rm -rf <root>studio', 'G-OPAQUE'), ('leaks -atexit -- rm -rf <root>studio', 'G-OPAQUE'),
    ('leaks --atExit -- rm -rf <root>studio', 'G-OPAQUE'),
    # bypass m2: §1.9 command-valued variables
    ("RSYNC_RSH='rm -rf <root>studio' rsync a x:b", 'G-OPAQUE'), ('RIPGREP_CONFIG_PATH=/tmp/rc rg x', 'G-OPAQUE'),
    # bypass R1: brace character ranges and BRACE_CCL
    ('rm -rf <root>{s..s}tudio', 'G-DEL'), ('rm -rf <root>studi{o..o}', 'G-DEL'), ('rm -rf <root>{r..t}tudio', 'G-DEL'),
    ('setopt braceccl; rm -rf <root>stu{d}io', 'G-DEL'),
    # conf M-4: GLOB_SUBST turned on through eval
    ("eval 'setopt globsubst'; X='a.txt(e:rm -rf <root>studio:)'; ls -d $X", 'G-OPAQUE'),
    ("eval setopt globsubst; X='a.txt(e:rm -rf <root>studio:)'; ls -d $X", 'G-OPAQUE'),
    ("eval \"$O\"; X='a.txt(e:rm -rf <root>studio:)'; ls -d $X", 'G-OPAQUE'),
    # conf m-3: a glob qualifier that runs code, and a glob group the guard does not read
    ('ls **/*(e:true:)', 'G-UNPARSE'), ('ls *(+f)', 'G-UNPARSE'), ('rm -rf *(D)', 'G-UNPARSE'),
    ('rm -rf <root>(stu)dio', 'G-UNPARSE'),
]
# G1 implementation review 4 (scratchpad/reviewG1impl4 review4-bypass.md, review4-conf.md): every command of the
# reports that needs no snapshot function (those are in G1Review4; the ones from outside the repository in
# NESTED_OUT_DENY)
G1_REVIEW4_DENY = [
    # bypass B2: the Bash tool runs with BARE_GLOB_QUAL off — `(…)` is a glob group (`studi(o)` matches studio)
    ('unsetopt bareglobqual; rm -rf <root>studio/video(s)', 'G-UNPARSE'),
    ('unsetopt bareglobqual; rm -f <root>studio/videos/v/work/state.jso(n)', 'G-UNPARSE'),
    ('unsetopt bareglobqual; mv <root>studio/videos/v/work/state.jso(n) /tmp/x', 'G-UNPARSE'),
    ('unsetopt bareglobqual; cp /tmp/x <root>studio/videos/v/work/state.jso(n)', 'G-UNPARSE'),
    ('unsetopt bareglobqual; rm -rf <root>studio/cast/a/characte(r)', 'G-UNPARSE'),
    ('unsetopt bareglobqual; rm -rf <root>studi(o)', 'G-UNPARSE'),
    ('setopt nobareglobqual; rm -rf <root>studi(o)', 'G-UNPARSE'),
    ('set +o bareglobqual; rm -rf <root>studi(o)', 'G-UNPARSE'),
    ('emulate -R zsh -o nobareglobqual; rm -rf <root>studi(o)', 'G-UNPARSE'), ('rm -rf <root>studi(o)', 'G-UNPARSE'),
    ('rm -rf <root>studio/video(s)', 'G-UNPARSE'), ('ls **/*(.)', 'G-UNPARSE'), ('ls -d *(/om[1])', 'G-UNPARSE'),
    ('rm -f **/*.pyc(N)', 'G-UNPARSE'), ('ls *(.) | wc -l', 'G-UNPARSE'), ('rm -rf *(Y1)', 'G-UNPARSE'),
    ('rm -rf *(/,.)', 'G-UNPARSE'), ('rm -rf *(-/)', 'G-UNPARSE'), ('rm -rf s*(/^@)', 'G-UNPARSE'),
    ('rm -rf <root>st[u]dio(/)', 'G-UNPARSE'), ('touch <root>studio/videos/v/work/*(.)', 'G-UNPARSE'),
    ('rm -f <root>studio/videos/v/work/*(.)', 'G-UNPARSE'), ('mv <root>studio/videos/v/work/*(.) /tmp', 'G-UNPARSE'),
    # bypass R1: hook functions and traps defined in the call run after later commands (the folder is then unknown)
    ('chpwd(){ builtin cd -q <root>studio; }; cd .; rm -rf local', 'G-DEL'),
    ('TRAPDEBUG(){ builtin cd -q <root>studio 2>/dev/null; }; rm -rf local', 'G-DEL'),
    ('TRAPZERR(){ cd <root>studio; }; false; rm -rf local', 'G-DEL'),
    ('command_not_found_handler(){ cd <root>studio; }; nosuchcmd; rm -rf local', 'G-DEL'),
    ("trap 'cd <root>studio' ZERR; false; rm -rf local", 'G-DEL'),
    ("trap 'cd <root>studio' DEBUG; rm -rf local", 'G-DEL'),
    ('TRAPEXIT(){ rm -rf <root>stu\'\'dio; }', 'G-DEL'),
    # bypass R2: pushd's options and the two-word form
    ('pushd -P <root>studio; rm -rf local', 'G-DEL'), ('pushd -L <root>studio; rm -rf local', 'G-DEL'),
    ('pushd -s <root>studio; rm -rf local', 'G-DEL'), ('pushd -- <root>studio; rm -rf local', 'G-DEL'),
    ('pushd -qP <root>studio; rm -rf local', 'G-DEL'),
    # bypass R3: a cd in a while/until condition
    ('until cd <root>studio; do :; done; rm -rf local', 'G-DEL'),
    ('while cd <root>studio; do break; done; rm -rf local', 'G-DEL'),
    ('while ! cd <root>studio; do :; done; rm -rf local', 'G-DEL'),
    ('while [[ -d x ]] || cd <root>studio; do break; done; rm -rf local', 'G-DEL'),
    ('while { cd <root>studio }; do break; done; rm -rf local', 'G-DEL'),
    ('while cd <root>studio && false; do :; done; rm -rf local', 'G-DEL'),
    # bypass R4: NULLCMD runs a command of redirections only
    ("NULLCMD=sh; > /dev/null <<< 'rm -rf <root>stu''dio'", 'G-DEL'),
    # the analyzer's own `return` (a function's folder stays its caller's) and functions[NAME]= text
    ('f(){ cd <root>studio; return; }; f; rm -rf local', 'G-DEL'),
    # conf M-1: values this call may have put in a parameter while GLOB_SUBST is on
    ('setopt globsubst; read l < a.txt; ls -d $l', 'G-OPAQUE'),
    ('setopt globsubst; for f in src/*.ts; do echo $f; done', 'G-OPAQUE'),
    ('eval "$O"; ls $X', 'G-OPAQUE'), ("setopt globsubst; ls -d ${X:-'a.txt(e:true:)'}", 'G-OPAQUE'),
    # conf M-2 controls: unquoted wildcards under a folder the guard cannot tell
    ('cd $D && touch s*.json', 'G-PROT'), ('cd $D && rm -rf stu?io', 'G-DEL'),
]

# G1 implementation review 5 (scratchpad/reviewG1impl5 review5-bypass.md, review5-conf.md): every command of the
# reports fixed in the repository (from outside it: NESTED_OUT_DENY; after a function the guard cannot read: G1Review5)
_Q5 = "'a.txt(#qe:rm -rf <root>stu\"\"dio:)'"
_G5 = "setopt globsubst extendedglob; "
G1_REVIEW5_DENY = [
    # M1: unbraced subscripts, modifiers and special parameters are patterns under GLOB_SUBST too
    (_G5 + "Z=%s; ls -d $Z[1,-1]" % _Q5, "G-OPAQUE"), (_G5 + "Z=%s; ls -d $Z:a" % _Q5, "G-OPAQUE"),
    (_G5 + "Z=%s; ls -d $Z[@]" % _Q5, "G-OPAQUE"), (_G5 + "Z=(%s); ls -d $Z[1]" % _Q5, "G-OPAQUE"),
    (_G5 + "set -- %s; ls -d $1" % _Q5, "G-OPAQUE"), (_G5 + "set -- %s; ls -d $@" % _Q5, "G-OPAQUE"),
    (_G5 + "set -- %s; ls -d $*" % _Q5, "G-OPAQUE"), (_G5 + "set -- %s; ls -d $argv[1]" % _Q5, "G-OPAQUE"),
    (_G5 + ": %s; ls -d $_" % _Q5, "G-OPAQUE"), (_G5 + "read -r Z <<< %s; ls -d $Z[1,-1]" % _Q5, "G-OPAQUE"),
    (_G5 + "read -r Z <<< %s; ls -d $Z:t" % _Q5, "G-OPAQUE"),
    # M2: the same parameter under another name, or written implicitly
    (_G5 + "PS1=%s; ls -d $PROMPT" % _Q5, "G-OPAQUE"), (_G5 + "PROMPT=%s; ls -d $PS1" % _Q5, "G-OPAQUE"),
    (_G5 + "prompt=%s; ls -d $PS1" % _Q5, "G-OPAQUE"), (_G5 + "PS3=%s; ls -d $PROMPT3" % _Q5, "G-OPAQUE"),
    (_G5 + "RPS1=%s; ls -d $RPROMPT" % _Q5, "G-OPAQUE"), (_G5 + "cdpath=(%s); ls -d $CDPATH" % _Q5, "G-OPAQUE"),
    (_G5 + "CDPATH=%s; ls -d $cdpath" % _Q5, "G-OPAQUE"), (_G5 + "psvar=(%s); ls -d $PSVAR" % _Q5, "G-OPAQUE"),
    (_G5 + "PSVAR=%s; ls -d $psvar" % _Q5, "G-OPAQUE"), (_G5 + "manpath=(%s); ls -d $MANPATH" % _Q5, "G-OPAQUE"),
    (_G5 + "watch=(%s); ls -d $WATCH" % _Q5, "G-OPAQUE"), (_G5 + "fpath=(%s); ls -d $FPATH" % _Q5, "G-OPAQUE"),
    (_G5 + "typeset -T ZZ zz; zz=(%s); ls -d $ZZ" % _Q5, "G-OPAQUE"),
    (_G5 + "typeset -T ZZ zz; ZZ=%s; ls -d $zz" % _Q5, "G-OPAQUE"),
    (_G5 + "alias q=%s; ls -d $aliases[q]" % _Q5, "G-OPAQUE"),
    (_G5 + "alias -g gq=%s; ls -d $galiases[gq]" % _Q5, "G-OPAQUE"),
    (_G5 + "set -- -a %s; zparseopts a:=Z; ls -d $Z" % _Q5, "G-OPAQUE"),
    (_G5 + "private Z=%s; ls -d $Z" % _Q5, "G-OPAQUE"),
    (_G5 + "setopt bashrematch; [[ %s =~ .* ]]; ls -d $BASH_REMATCH" % _Q5, "G-OPAQUE"),
    # M3: array values of a declaration are file-name generated
    (_G5 + "Z=%s; typeset -a W=($Z)" % _Q5, "G-OPAQUE"), (_G5 + "Z=%s; local -a W=($Z)" % _Q5, "G-OPAQUE"),
    (_G5 + "Z=%s; declare -a W=($Z)" % _Q5, "G-OPAQUE"),
    # M4: `function a b { … }` defines both names (a hook among them runs)
    ("function x chpwd { builtin cd -q <root>studio }; cd .; rm -rf local", "G-DEL"),
    ("function x TRAPDEBUG { builtin cd -q <root>studio 2>/dev/null }; rm -rf local", "G-DEL"),
    ("function x TRAPZERR { cd <root>studio }; false; rm -rf local", "G-DEL"),
    ("function x y { cd <root>studio }; y; rm -rf local", "G-DEL"),
    ("function x chpwd { export GIT_DIR=/tmp/x }; cd .; git commit -m x", "G-COMMIT"),
    # M5: NULLCMD/READNULLCMD read the pipe
    ("NULLCMD=sh; print 'rm -rf <root>stu''dio' | > /dev/null", "G-DEL"),
    ("NULLCMD=sh; print 'rm -rf <root>stu''dio' |& > /dev/null", "G-DEL"),
    ("NULLCMD=sh; print 'rm -rf <root>stu''dio' | ( > /dev/null )", "G-DEL"),
    ("NULLCMD=sh; { print 'rm -rf <root>stu''dio' } | > /dev/null", "G-DEL"),
    ("NULLCMD=bash; print 'rm -rf <root>stu''dio' | > /dev/null", "G-DEL"),
    ("READNULLCMD=sh; print 'rm -rf <root>stu''dio' | < /dev/stdin", "G-DEL"),
    ("READNULLCMD=sh; print 'rm -rf <root>stu''dio' | < /dev/fd/0", "G-DEL"),
    ("NULLCMD=sh; cat x.sh | > /dev/null", "G-OPAQUE"), ("print 'rm -rf <root>stu''dio' | ( sh )", "G-DEL"),
    # borderline: `^ ~ #` are wildcards under a folder the guard cannot tell while EXTENDED_GLOB may be on
    ("setopt extendedglob; cd $D; rm -rf ^x", "G-DEL"), ("setopt extendedglob; cd $D; rm -rf *~x", "G-DEL"),
    ("setopt extendedglob; cd $D; rm -rf l#ocal", "G-DEL"), ("setopt extendedglob; cd $D; touch ^x", "G-PROT"),
    # R1: an assignment-only command closed by a reserved word (`{ X=v }`, `then X=v fi`); unparsable with one
    ("{ GIT_DIR=/tmp/x }; git commit -m x", "G-HOOKOFF"), ("{ X=stu }; rm -rf <root>${X}dio", "G-DEL"),
    (_G5 + "{ Z=%s }; ls -d $Z" % _Q5, "G-OPAQUE"), (_G5 + "f(){ Z=%s }; f; ls -d $Z" % _Q5, "G-OPAQUE"),
    ("if true; then X=stu fi; rm -rf <root>${X}dio", "G-DEL"),
    ("{ :; } always { GIT_DIR=/tmp/x }; git commit -m x", "G-HOOKOFF"),
    ("{ :; } always { X=stu }; rm -rf <root>${X}dio", "G-DEL"), ("{ cd <root>studio } always { : }; rm -rf local", "G-DEL"),
    ("GIT_DIR=/tmp/x; echo 'unterminated", "G-UNPARSE"), ("X=1; echo \"$X", "G-UNPARSE"),
    # R2: what a function the call defines exports or assigns
    ("y(){ export GIT_DIR=/tmp/x; }; y; git commit -m x", "G-COMMIT"),
    ("y(){ export GIT_INDEX_FILE=/tmp/i; }; y; git commit -m x", "G-COMMIT"),
    ("y(){ export HOME=/tmp/h; }; y; git commit -m x", "G-OPAQUE"),
    ("y(){ export GIT_CONFIG_GLOBAL=/tmp/c; }; y; git commit -m x", "G-HOOKOFF"),
    ("y(){ typeset -gx GIT_DIR=/tmp/x; }; y; git commit -m x", "G-COMMIT"),
    ("y(){ GIT_DIR=/tmp/x; export GIT_DIR; }; y; git commit -m x", "G-COMMIT"),
    ("y(){ export GIT_DIR=/tmp/x; }; y; git status", "G-OPAQUE"),
    ("function f { X=<root>studio }; f; rm -rf $X", "G-DEL"), ("f(){ X=stu; }; f; rm -rf <root>${X}dio", "G-DEL"),
    # conf m-1: script with no command runs a shell on its input
    ("script -q /dev/null", "G-OPAQUE"),
]

# G1 implementation review 6 (scratchpad/reviewG1impl6 review6-bypass.md, review6-conf.md), by class (from outside the
# repository: NESTED_OUT_DENY; the hook files and after a function the guard cannot read: G1Review6)
G1_REVIEW6_DENY = [
    # regression (BLOCKER): a compound command's here-string reaches NULLCMD in it
    ("{ NULLCMD=sh; > /dev/null } <<< 'rm -rf <root>studio/local'", "G-DEL"),
    # M1-M4: the glob qualifier is judged on the whole word (parts joined, `:&`, quoted modifier text, `$0`)
    (_G5 + "X=a.txt; : \"${X:s/.txt/.txt(#qe:rm -rf <root>stu\"\"dio:)/}\"; ls -d ${X:&}", "G-OPAQUE"),
    (_G5 + "X=a.txt; : \"${X:s/.txt/.txt(#qe:rm -rf <root>stu\"\"dio:)/}\"; ls -d ${X:g&}", "G-OPAQUE"),
    (_G5 + "X='a.txt(#q'; Y='e:rm -rf <root>stu\"\"dio:)'; ls -d $X$Y", "G-OPAQUE"),
    (_G5 + "X='a.txt(#q'; Y='e:rm -rf <root>stu\"\"dio:)'; ls -d ${X}${Y}", "G-OPAQUE"),
    (_G5 + "X='a.txt(#q'; Y='e:rm -rf <root>stu\"\"dio:)'; for f in $X$Y; do :; done", "G-OPAQUE"),
    (_G5 + "X='a.txt(#q'; Y='e:rm -rf <root>stu\"\"dio:)'; ls -d $X[1,-1]$Y", "G-OPAQUE"),
    (_G5 + "X='a.txt(#q'; ls -d $X$1", "G-OPAQUE"),
    (_G5 + "0=%s; ls -d $0" % _Q5, "G-OPAQUE"), (_G5 + "0=%s; ls -d ${0}" % _Q5, "G-OPAQUE"),
    (_G5 + "1=%s; ls -d $1" % _Q5, "G-OPAQUE"), (_G5 + "0=%s; for f in $0; do :; done" % _Q5, "G-OPAQUE"),
    (_G5 + "X=a.txt; ls -d $X:s/.txt/'.txt(#qe:rm -rf <root>stu\"\"dio:)'/", "G-OPAQUE"),
    (_G5 + "X=a.txt; ls -d $X:s/.txt/\".txt(#qe:rm -rf <root>stu\"\"dio:)\"/", "G-OPAQUE"),
    (_G5 + "X=a.txt; ls -d $X:gs/.txt/'.txt(#qe:rm -rf <root>stu\"\"dio:)'/", "G-OPAQUE"),
    (_G5 + "X=a.txt; ls -d $X:s/.txt/.txt\\(#qe:rm\\ -rf\\ <root>stu\"\"dio:\\)/", "G-OPAQUE"),
    # M5-M7: one stdin for compound commands, functions the call defines, `exec` and fd duplication
    ("{ sh; } <<< 'rm -rf <root>studio/local'", "G-DEL"), ("( zsh ) <<EOF\nrm -rf <root>studio/local\nEOF", "G-DEL"),
    ("if true; then sh; fi <<< 'rm -rf <root>studio/local'", "G-DEL"),
    ("for i in 1; do sh; done <<< 'rm -rf <root>studio/local'", "G-DEL"),
    ("{ source /dev/stdin } <<< 'rm -rf <root>studio/local'", "G-DEL"), ("{ sh } < x.sh", "G-OPAQUE"),
    ("{ sh } <<< 'git config core.hooksPath /tmp'", "G-HOOKOFF"),
    ("f(){ sh }; f <<< 'rm -rf <root>studio/local'", "G-DEL"),
    ("f(){ sh }; print -r -- 'rm -rf <root>studio/local' | f", "G-DEL"),
    ("f(){ zsh -s }; f <<< 'rm -rf <root>studio/local'", "G-DEL"),
    ("f(){ source /dev/stdin }; f <<< 'rm -rf <root>studio/local'", "G-DEL"),
    ("f() sh; f <<< 'rm -rf <root>studio/local'", "G-DEL"), ("f(){ sh <&3 }; f 3<<< 'rm -rf <root>studio'", None),
    ("exec <<< 'rm -rf <root>studio/local'; sh", "G-DEL"), ("exec 0<<< 'rm -rf <root>studio/local'; zsh", "G-DEL"),
    ("exec 3<<< 'rm -rf <root>studio/local'; sh <&3", "G-DEL"),
    ("exec 3<<< 'rm -rf <root>studio/local'; sh 0<&3", "G-DEL"),
    ("exec 4<<< 'rm -rf <root>studio/local'; { sh <&4 }", "G-DEL"),
    ("{ sh <&3 } 3<<< 'rm -rf <root>studio/local'", "G-DEL"), ("sh <&3 3<<< 'rm -rf <root>studio/local'", "G-DEL"),
    ("exec 3< x.sh; sh <&3", "G-OPAQUE"), ("sh <&3", "G-OPAQUE"),
    # M8, M9: function-table writes (`functions -c`) and functions defined in a function's body
    ("f(){ cd <root>studio }; functions -c f k; k; rm -rf local", "G-DEL"),
    ("f(){ export GIT_DIR=/tmp/x }; functions -c f k; k; git commit -m x", "G-COMMIT"),
    ("functions -c cd k; k <root>studio; rm -rf local", "G-OPAQUE"), ("functions -c nvm k; k; git commit -m x", "G-OPAQUE"),
    ("functions -c rm ls 2>/dev/null; ls -rf <root>studio", "G-OPAQUE"),
    ("f(){ k(){ cd <root>studio } }; f; k; rm -rf local", "G-DEL"),
    ("f(){ k(){ export GIT_DIR=/tmp/x } }; f; k; git commit -m x", "G-COMMIT"),
    ("f(){ function k { export GIT_DIR=/tmp/x } }; f; k; git commit -m x", "G-COMMIT"),
    ("f(){ k(){ X=<root>studio } }; f; k; rm -rf $X", "G-DEL"),
    # M10: zsh's short loop and brace forms
    ("for i in x; git commit --no-verify -m x", "G-UNPARSE"), ("case x { (x) git commit -n -m x ;; }", "G-UNPARSE"),
    ("for ((i=0;i<1;i++)) git config core.hooksPath /tmp", "G-UNPARSE"),
    ("while (( 1 )) { git commit --no-verify -m x; break }", "G-UNPARSE"), ("for i in x; rm -rf .c*e/s*o", "G-UNPARSE"),
    ("for i in x; cd s*o; rm -rf l*l", "G-UNPARSE"), ("if true { rm -rf s*o }", "G-UNPARSE"),
    ("if [[ 1 ]] { rm -rf s*o }", "G-UNPARSE"), ("until false { rm -rf s*o; break }", "G-UNPARSE"),
    ("if true; then :; elif true { rm -rf s*o }; fi", "G-UNPARSE"), ("for i (x) rm -rf s*o", "G-UNPARSE"),
    # R1 (part): a literal value a function assigns through `for` or `${…::=…}`
    ("f(){ for Y in <root>studio; do :; done }; f; rm -rf $Y", "G-DEL"),
    ("Y=x; f(){ : ${Y::=<root>studio} }; f; rm -rf $Y", "G-DEL"),
]
G1_REVIEW6_DENY = [(c, r or "G-OPAQUE") for c, r in G1_REVIEW6_DENY]

# G1 implementation review 7 (scratchpad/reviewG1impl7 review7-bypass.md, review7-conf.md), by class (from outside the
# repository: NESTED_OUT_DENY; the hook files: G1Review7)
_E7 = "setopt extendedglob; "
_S7 = "'rm -rf <root>studio/local'"
G1_REVIEW7_DENY = [
    # B1, M1, M2: a bracket expression as zsh 5.9 reads it — `~ ^ #` and `/` in it are members, `]-^` is no range
    (_E7 + "rm -rf <root>[s~]tudio", "G-DEL"), (_E7 + "rm -rf <root>stu[d~]io", "G-DEL"),
    (_E7 + "rm -rf <root>studi[o~]", "G-DEL"), (_E7 + "rm -rf <root>.claude/[s~]tudio", "G-DEL"),
    (_E7 + "rm -rf <root>stud[i~]o/videos/v/work", "G-DEL"), (_E7 + "mv <root>[s~]tudio /tmp/", "G-DEL"),
    (_E7 + "find <root>[s~]tudio -delete", "G-DEL"), (_E7 + "rm -rf <root>[s~]tudio~x", "G-DEL"),
    ("rm -rf <root>[s/]tudio", "G-DEL"), ("rm -rf <root>[s/]tudio/local", "G-DEL"), ("rm -rf <root>[!/]tudio", "G-DEL"),
    ("rm -rf <root>[!]tudio", "G-DEL"), ("rm -rf <root>[[:alpha:]/]tudio", "G-DEL"),
    (_E7 + "cd $D; rm -rf [l~]ocal", "G-DEL"), (_E7 + "cd $D; rm -rf [s~]tudio", "G-DEL"),
    # M3: a positional parameter set by `N=` steers every positional ($@, $*, $argv, after `shift`)
    (_G5 + "2=%s; ls -d $@" % _Q5, "G-OPAQUE"), (_G5 + "2=%s; ls -d $argv[2]" % _Q5, "G-OPAQUE"),
    (_G5 + "1=%s; ls -d $*" % _Q5, "G-OPAQUE"), (_G5 + "1=%s; ls -d $argv" % _Q5, "G-OPAQUE"),
    (_G5 + "2=%s; shift; ls -d $1" % _Q5, "G-OPAQUE"), (_G5 + "3=%s; shift 2; ls -d $1" % _Q5, "G-OPAQUE"),
    (_G5 + "1=a.txt; 2=%s; shift; ls -d $1" % _Q5, "G-OPAQUE"),
    # M4: stdin reaches eval strings and `-c` strings (and functions an eval string defines)
    ("eval sh <<< %s" % _S7, "G-DEL"), ("eval 'zsh -s' <<< %s" % _S7, "G-DEL"),
    ("eval 'source /dev/stdin' <<< %s" % _S7, "G-DEL"), ("builtin eval sh <<< %s" % _S7, "G-DEL"),
    ("noglob eval sh <<< %s" % _S7, "G-DEL"), ("exec eval sh <<< %s" % _S7, "G-DEL"), ("zsh -c sh <<< %s" % _S7, "G-DEL"),
    ("sh -c 'source /dev/stdin' <<< %s" % _S7, "G-DEL"), ("env zsh -c sh <<< %s" % _S7, "G-DEL"),
    ("nohup sh -c sh <<< %s" % _S7, "G-DEL"), ("sh -c 'eval sh' <<< %s" % _S7, "G-DEL"),
    ("print -r -- %s | eval sh" % _S7, "G-DEL"), ("print -r -- %s | zsh -c sh" % _S7, "G-DEL"),
    ("exec <<< %s; eval sh" % _S7, "G-DEL"), ("eval sh <<EOF\nrm -rf <root>studio/local\nEOF", "G-DEL"),
    ("{ eval sh } <<< %s" % _S7, "G-DEL"), ("eval sh 3<<< %s <&3" % _S7, "G-DEL"),
    ("emulate sh -c sh <<< %s" % _S7, "G-DEL"), ("f(){ eval sh }; f <<< %s" % _S7, "G-DEL"),
    ("eval 'f(){ sh }'; f <<< %s" % _S7, "G-DEL"), ("eval 'function f { sh }'; f <<< %s" % _S7, "G-DEL"),
    ("eval 'f(){ sh }'; print -r -- %s | f" % _S7, "G-DEL"),
    ("builtin eval sh <<< 'git config core.hooksPath /tmp'", "G-HOOKOFF"),
    # conf M-1: the pattern after `==` is one word; what follows is judged; text the guard cannot read with a glob
    # group or a writing command does not pass silently
    ("[[ a == (a|b) ]]; rm -rf <root>s*", "G-DEL"), ("[[ a == (a|b) ]] && rm -rf <root>s*", "G-DEL"),
    ("[[ a == (#i)A ]]; rm -rf <root>s*", "G-DEL"), ("[[ a == (a|b) ]]; rm -rf ./<root>s*/videos", "G-DEL"),
    ("if [[ $x == (a|b) ]]; then rm -rf <root>studio; fi", "G-DEL"),
    ("[[ $(rm -rf <root>studio/local) == (a|b) ]]", "G-DEL"),
    ("[[ a == (a|b)|c ]]; rm -rf <root>s*", "G-UNPARSE"), ("[[ a == (a|b ]]; rm -rf <root>s*", "G-UNPARSE"),
    # found while checking conf M-1: zsh reads a lone `;` where a command is expected as an empty command
    ("rm -rf <root>s* &;", "G-DEL"), ("true; ; rm -rf <root>s*", "G-DEL"), ("; rm -rf <root>s*", "G-DEL"),
    ("for i in x; do; rm -rf <root>s*; done", "G-DEL"), ("print a &&; rm -rf <root>s*", "G-DEL"),
    ("{ ; rm -rf <root>s*; }", "G-DEL"), ("if true; ; then rm -rf <root>s*; fi", "G-DEL"),
    # R3: several loop names
    ("for i j in x y; do rm -rf <root>studio/local; done", "G-DEL"),
]


# G1 implementation review 8 (scratchpad/reviewG1impl8 review8-bypass.md, review8-conf.md), by class (from outside the
# repository: NESTED_OUT_DENY; real-snapshot aliases: G1Review8)
_GS8 = "setopt globstarshort; "
_NX8 = "/nonexistent/x"
G1_REVIEW8_DENY = [
    # B1: zsh's numeric glob `<N-M>` is part of a word (also inside `[…]`, after `^`, after an fd number); fail closed
    ("rm -rf <root>studi[o<->]", "G-DEL"), ("rm -rf <root>[s<->]tudio", "G-DEL"), ("rm -rf <root>studi[o<1-9>]", "G-DEL"),
    ("rm -rf <root>.claude/[s<->]tudio", "G-DEL"), ("rm -rf <root>.claude/studio/scrip[t<->]s", "G-DEL"),
    ("cp /tmp/x <root>.claude/studio/confi[g<->].json", "G-PROT"), ("print x > <root>.claude/studio/confi[g<->].json", "G-PROT"),
    ("mv <root>[s<->]tudio /tmp/", "G-DEL"), ("find <root>[s<->]tudio -delete", "G-DEL"), ("rm -rf <root>[.<->]claude", "G-DEL"),
    ("rm -rf <root>studi[o<->] x", "G-DEL"),  # (`s<->tudio`, `studio<->`: review 9 conf m-1, G1_REVIEW9_PASS)
    (_E7 + "mv <root>^<-> /tmp/", "G-DEL"), (_E7 + "find <root>^<-> -delete", "G-DEL"),
    (_E7 + "rm -rf <root>*~<-> /tmp/x", "G-DEL"),
    # B2: a redirection that may fail skips its command (builtins, cd, compound commands); PIPEFAIL
    ("pushd > %s || rm -rf <root>studio" % _NX8, "G-DEL"), ("true > %s || rm -rf <root>studio" % _NX8, "G-DEL"),
    (": > %s || rm -rf <root>studio" % _NX8, "G-DEL"), ("true <&7 || rm -rf <root>studio", "G-DEL"),
    ("true >&7 || rm -rf <root>studio", "G-DEL"), ("true > /dev/null/x || rm -rf <root>studio", "G-DEL"),
    ("true >| . || rm -rf <root>studio", "G-DEL"), ("true > %s && : || rm -rf <root>studio" % _NX8, "G-DEL"),
    ("exit 1 > %s || rm -rf <root>studio" % _NX8, "G-DEL"), ("{ : } > %s || rm -rf <root>studio" % _NX8, "G-DEL"),
    ("if true; then :; fi > %s || rm -rf <root>studio" % _NX8, "G-DEL"),
    ("cd /tmp > %s; rm -rf <root>studio" % _NX8, "G-DEL"), ("cd . > %s || rm -rf <root>studio" % _NX8, "G-DEL"),
    ("cd /tmp 2>&7 || rm -rf <root>studio", "G-DEL"), ("pushd /tmp > %s || rm -rf <root>studio" % _NX8, "G-DEL"),
    ("true > $~X || rm -rf <root>studio", "G-DEL"),
    ("setopt pipefail; false | true || rm -rf <root>studio", "G-DEL"),
    ("set -o pipefail; false | true || rm -rf <root>studio", "G-DEL"),
    ("setopt pipefail; print | false | true && : || rm -rf <root>studio", "G-DEL"),
    # M1: zsh forms the parser now reads (`time;`, `! ;`, `coproc ;`, `;|`, `>&|`, `>>&`, `&>>|`, …)
    ("time; /bin/rm -rf <root>s*", "G-DEL"), ("time; =rm -rf <root>s*", "G-DEL"), ("time; r''m -rf <root>s*", "G-DEL"),
    ("time; r\\m -rf <root>s*", "G-DEL"), ("time; ${:-rm} -rf <root>s*", "G-OPAQUE"),
    ("time; nohup /bin/rm -rf <root>s*", "G-DEL"), ("time; /bin/mv <root>s* /tmp/", "G-DEL"),
    ("time\n/bin/rm -rf <root>s*", "G-DEL"), ("time | cat; /bin/rm -rf <root>s*", "G-DEL"),
    ("case x in (x) print;| esac; /bin/rm -rf <root>s*", "G-DEL"), ("print a &>|/dev/null; /bin/rm -rf <root>s*", "G-DEL"),
    ("! ; /bin/rm -rf <root>s*", "G-DEL"), ("coproc ; /bin/rm -rf <root>s*", "G-DEL"),
    ("print '[core]' >>& <root>.git/config", "G-HOOKOFF"), ("print '[core]' >>&| <root>.git/config", "G-HOOKOFF"),
    ("print '[core]' >>&! <root>.git/config", "G-HOOKOFF"), ("print '[core]' >&| <root>.git/config", "G-HOOKOFF"),
    ("print '[core]' &>>| <root>.git/config", "G-HOOKOFF"), ("print '[core]' &>| <root>.git/config", "G-HOOKOFF"),
    ("print x >&! <root>.claude/studio/config.json", "G-PROT"),
    # M1: text the guard still cannot parse names a writing command however it is spelled, or writes a file
    ("r''m -rf <root>s* )", "G-UNPARSE"), ("echo ok; =rm -rf <root>s* ) x", "G-UNPARSE"), ("$X -rf <root>s* )", "G-UNPARSE"),
    ("echo x >| f )", "G-UNPARSE"), ("/bin/rm -rf <root>s* ;;& x", "G-UNPARSE"),
    ("alias x='r\\m -rf'; x <root>s* )", "G-UNPARSE"),
    # case: `;&` / `;|` run the next body after this one (from where it left the shell); patterns are no file names
    ("case $x in (#i)abc) rm -rf <root>studio;; esac", "G-DEL"),
    ("case $f in *.(ts|tsx)) rm -rf <root>.claude/studio;; esac", "G-DEL"),
    ("case $x in $(rm -rf <root>studio)) echo;; esac", "G-DEL"),
    # M3: GLOB_STAR_SHORT (`**x` is `**/*x`); options the guard cannot tell
    (_GS8 + "rm -rf <root>**local", "G-DEL"), (_GS8 + "rm -rf <root>***local", "G-DEL"),
    (_GS8 + "rm -f <root>**state.json", "G-DEL"), (_GS8 + "cp /tmp/x <root>**state.json", "G-PROT"),
    (_GS8 + "rm -rf <root>studio/**local", "G-DEL"), ("setopt glob_star_short; rm -f <root>**.json", "G-DEL"),
    ("eval x; rm -rf <root>**local", "G-DEL"),
    # M2 (in the repository): a function body judged from the call, with the values in effect there
    ("f(){ rm -rf $X; }; X=<root>studio; f", "G-DEL"),
]

# G1 implementation review 9 (regressions against the last release only): B1/M1 a folder change that may or may not
# happen (git, $PWD, ~+, $(pwd) judged in each folder), B2 `$'…'` in case patterns and the unparsable fallback, B3
# several inputs on one fd (MULTIOS), `$~1`, values the guard does not carry as one string (arrays, read, print -v,
# set -A/--, $(print …), a function's global) judged by each value they may hold (from outside the repository:
# NESTED_OUT_DENY; folders and the directory stack: G1Review9)
_LOG9 = "out.log"
G1_REVIEW9_DENY = [
    # B1/M1: git and the current folder after a folder change that may fail or may not run (from the repository root,
    # `rm -rf $PWD/studio` is NESTED_OUT_DENY's `cd <R> > out.log; …`)
    ("cd <root>studio > %s; git clean -fdx" % _LOG9, "G-CLEAN"),
    ("cd <root>studio > /nonexistent/x; git clean -fdx", "G-CLEAN"),
    ("true > /nonexistent/x && cd <root>studio; git clean -fdx", "G-CLEAN"),
    ("true > %s || cd <root>studio; git stash -a" % _LOG9, "G-STASH"),
    ("setopt pipefail; false | true || cd <root>studio; git clean -fdx", "G-CLEAN"),
    ("[[ -e x ]] && cd <root>studio; git clean -fdx", "G-CLEAN"),
    ("cd <root>studio > %s; git config --unset core.hooksPath" % _LOG9, "G-HOOKOFF"),
    ("cd <root>studio > %s; export GIT_INDEX_FILE=/tmp/i; git commit -m x" % _LOG9, "G-HOOKOFF"),
    ("cd <root>studio/videos > /nonexistent/x; git read-tree -u --reset HEAD", "G-PLUMB"),
    ("cd <root>studio > %s; GIT_DIR=/tmp/x git commit -m x" % _LOG9, "G-HOOKOFF"),
    ("true > %s || cd <root>studio; rm -rf $PWD/../studio" % _LOG9, "G-DEL"),
    ("true > %s || cd <root>studio; rm -rf ~+/../studio" % _LOG9, "G-DEL"),
    ("true > %s || cd <root>studio; rm -rf $(pwd)/../studio" % _LOG9, "G-DEL"),
    ("cd <root>studio > %s; rm -rf $PWD/../studio" % _LOG9, "G-DEL"),
    ("[[ -e x ]] && cd <root>studio; X=$PWD; rm -rf $X/../studio", "G-DEL"),
    ("true > %s || cd <root>studio; popd || rm -rf <root>studio" % _LOG9, "G-DEL"),
    ("f(){ cd <root>studio }; f > /nonexistent/x; ln -s /tmp/x <root>studio/videos/v/work/", "G-PROT"),
    ("f(){ cd <root>studio }; f > /nonexistent/x; watchexec -- rm -rf <root>studio", "G-OPAQUE"),
    # B2: `$'…'` (with `\'`) and `${(s:(:)…}` in a case pattern; the unparsable fallback reads `$'…'` too
    ("case x in ($'\\'') ;; esac; rm -rf <root>studio", "G-DEL"),
    ("case x in (${(s:(:)X}) ;; esac; rm -rf <root>studio", "G-DEL"),
    ("echo $'\\''; /bin/rm -rf <root>s*; case x in ($'\\'') ;; esac", "G-DEL"),
    ("case x in ($(print $'a\\'b'; /bin/rm -rf <root>s*\n)) true;; esac", "G-DEL"),
    # B3: every input redirection on fd 0 is read (MULTIOS), and a pipe with one
    ("zsh /dev/stdin <<< 'rm -rf <root>studio' <<< x", "G-DEL"), ("sh /dev/stdin <<< 'rm -rf <root>studio' < /dev/null", "G-DEL"),
    ("bash /dev/stdin <<< 'rm -rf <root>studio' 0<<< x", "G-DEL"), ("sh <<< 'rm -rf <root>studio' <<< x", "G-DEL"),
    ("zsh /dev/stdin <<EOF <<< x\nrm -rf <root>studio\nEOF", "G-DEL"), ("{ sh } <<< 'rm -rf <root>studio' <<< x", "G-DEL"),
    ("{ NULLCMD=sh; > /dev/null } <<< 'rm -rf <root>studio' <<< x", "G-DEL"),
    ("{ NULLCMD=sh; > /dev/null } <<< 'rm -rf <root>studio' < /dev/null", "G-DEL"),
    ("echo 'rm -rf <root>studio' | sh <<< x", "G-DEL"),
    # s7#11: `$~1` / `$=1` are pattern expansions of a positional parameter
    ("setopt globsubst extendedglob; Q='a.txt(#qe:touch MA:)'; 1=$Q; ls -d $~1", "G-OPAQUE"),
    ("Q='a.txt(#qe:touch MA:)'; set -- $Q; ls -d $~1", "G-OPAQUE"),
    # values the guard does not carry as one string, after forms the parser now reads
    ("X=safe; case x in x) true;| x) X=(<root>studio);| *) rm -rf -- $X;; esac", "G-DEL"),
    ("X=safe; case x in x) true;| x) X=$(print <root>studio);| *) rm -rf -- $X;; esac", "G-DEL"),
    ("X=safe; case x in x) true;| x) read X <<< <root>studio;| *) rm -rf -- $X;; esac", "G-DEL"),
    ("X=safe; case x in x) true;| x) print -v X <root>studio;| *) rm -rf -- $X;; esac", "G-DEL"),
    ("X=safe; case x in x) true;| x) set -- <root>studio; X=$1;| *) rm -rf -- $X;; esac", "G-DEL"),
    ("X=safe; time; X=(<root>studio); rm -rf -- $X", "G-DEL"), ("X=safe; time; X=$(print <root>studio); rm -rf -- $X", "G-DEL"),
    ("X=safe; time; read X <<< <root>studio; rm -rf -- $X", "G-DEL"), ("X=safe; time; set -A X <root>studio; rm -rf $X", "G-DEL"),
    ("X=safe; f(){ X=(<root>studio) }; f; rm -rf -- $X", "G-DEL"), ("X=safe; f(){ X=$(print <root>studio) }; ! f; rm -rf -- $X", "G-DEL"),
    ("X=safe; f(){ set -- <root>studio; X=$1 }; time f; rm -rf -- $X", "G-DEL"),
    ("f(){ X=(<root>studio) } > %s; X=safe; f; rm -rf -- $X" % _LOG9, "G-DEL"),
    ("X=safe; f(){ X=(<root>studio) }; { f } > %s; rm -rf -- $X" % _LOG9, "G-DEL"),
    ("X=(<root>stu); rm -rf ${X}dio", "G-DEL"), ("set -A X a <root>studio; rm -rf $X[2]", "G-DEL"),
    ("set -- a <root>studio; shift; rm -rf $1", "G-DEL"), ("for d in build <root>studio; do rm -rf $d; done", "G-DEL"),
    ("X=$(ls <root>studio); rm -rf $X", "G-DEL"), ("X=(<root>.claude/studio/config.json); echo x > $X", "G-PROT"),
]
_E9 = "setopt extendedglob; "
G1_REVIEW9_PASS = [
    # conf m-1: a numeric glob matches one or more digits in its range
    "mv frame<1-9>.png src/", "mv a<->.png out/", "mv -f log<->.txt logs/", "mv a<->.png b.png",
    "rsync --remove-source-files a<->.png out/", "rm -rf s<->tudio", "rm -rf studio<->", _E9 + "rm -rf s<1->tudio",
    "rm -f out<->.txt", "git rm --cached frame<->.png",
    # values the guard now follows, in ordinary use
    "files=(a b); rm -f $files", "for d in build dist; do rm -rf $d; done", "d=$(mktemp -d); rm -rf \"$d\"",
    "X=$(find . -name '*.tmp'); rm -f $X", "out=$(git status --short); echo \"$out\" > status.txt",
    "set -- a b; rm -f $1 $2", "read f <<< build.log; rm -f $f", "X=(dist build); rm -rf $X",
    # folders that may or may not change, in ordinary use
    "[[ -e x ]] && cd src; git status", "[[ -d build ]] && cd build; git add -A", "cd src > /dev/null; git commit -m x",
    "cd src 2>/dev/null || exit 1; rm -rf node_modules", "[[ -d src ]] && cd src; ls $PWD",
    "pushd src > /dev/null && npm test; popd > /dev/null", "if [[ -d src ]]; then pushd src; make; popd; fi; ls",
    "cat <<< a <<< b", "sh <<< 'echo hi' <<< 'echo there'", "echo x | cat <<< y",
    "case x in ($'\\'') echo q;; esac", "case $x in (${(s:(:)X}) echo y;; esac",
]

# G1 implementation review 10 (regressions against the last release only; the union rule — under uncertainty a value
# or folder is one of the old or new ones, and any unknown member makes the whole unknown and judged fail-closed):
# B1 `$PWD`, `~+`, `$(pwd)`, `git rev-parse --show-toplevel` after a folder change the guard cannot follow, or after a
# trap or hook (EXIT traps and precmd/zshexit do not run between commands); B2 `local` in a function and writes that may
# not run; B3 read / print -v / ${X:=} / plain assignments that may not run; B4 `<>` on stdin (MULTIOS); P1 `$((` in
# `${…}`; conf M-1 `set -euo pipefail` (from outside the repository: NESTED_OUT_DENY; snapshot hooks, options and
# functions: G1Review10)
G1_REVIEW10_DENY = [
    # B1
    ("cd <root>studio; trap 'cd /' EXIT; rm -rf $PWD/../studio", "G-DEL"),
    ("cd <root>studio; trap 'cd -' INT; rm -rf ~+/../studio", "G-DEL"),
    ("cd <root>studio; c(){ rm -f /tmp/l; }; trap c EXIT; rm -rf $(pwd)/../studio", "G-DEL"),
    ("cd <root>studio; TRAPEXIT(){ cd / }; rm -rf $PWD/../studio", "G-DEL"),
    ("cd <root>studio; precmd(){ cd / }; rm -rf $PWD/../studio", "G-DEL"),
    ("cd <root>studio; zshexit(){ cd / }; rm -rf $PWD/../studio", "G-DEL"),
    ("cd <root>studio; chpwd(){ cd / }; rm -rf $PWD/../studio", "G-DEL"),
    ("cd <root>studio; trap 'cd /' ZERR; rm -rf $PWD/../studio", "G-DEL"),
    ("cd <root>studio; trap 'cd /' DEBUG; rm -rf ~+/../studio", "G-DEL"),
    ("cd <root>studio; c(){ :; }; trap c INT; c(){ cd /; }; rm -rf $PWD/../studio", "G-DEL"),
    ("cd <root>studio; cd $X > out.log; rm -rf $PWD/../studio", "G-DEL"),
    ("cd <root>studio; cd $X > out.log; rm -rf \"$(pwd)/../studio\"", "G-DEL"),
    ("cd $X; cd <root>studio > out.log; rm -rf $PWD/../studio", "G-DEL"),
    ("pushd <root>studio / || cd <root>studio; rm -rf $PWD/../studio", "G-DEL"),
    ("cd $X; rm -rf $PWD/studio", "G-DEL"), ("cd $X; rm -rf $(git rev-parse --show-toplevel)/studio", "G-DEL"),
    ("cd $X; find ${PWD}/studio -delete", "G-DEL"),
    ("cd <root>.claude/studio/scripts; cd $X 2>/dev/null; rm -f $PWD/x.py", "G-DEL"),
    ("cd <root>.claude/studio/scripts; cd $X 2>/dev/null; rm -f `pwd`/x.py", "G-DEL"),
    # B2
    ("X=<root>studio; f(){ local X=a }; f; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; f(){ typeset X=a }; f; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; f(){ local -a X=(a) }; f; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; function f { private X=a }; f; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; g(){ local X=a; }; f(){ g }; f; rm -rf -- $X", "G-DEL"),
    ("dir=<root>studio; cleanup(){ local dir=$1; print $dir }; cleanup /tmp/x; rm -rf $dir", "G-DEL"),
    ("f=<root>.claude/studio/config.json; show(){ local f=$1; cat $f }; show a.txt; cp /tmp/x $f", "G-PROT"),
    ("X=<root>studio; f(){ if false; then X=a; fi }; f; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; f(){ case y in (x) X=a;; esac }; f; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; f(){ [[ -e nope ]] || return; X=a }; f; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; f(){ X=a > /nonexistent/x }; f; rm -rf -- $X", "G-DEL"),
    ("X=a; f(){ X=<root>studio; local X=b }; f; rm -rf -- $X", "G-DEL"),
    # B3
    ("X=<root>studio; read X < /nonexistent/x; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; print -v X a > /nonexistent/x; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; if false; then read X <<< a; fi; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; case y in (x) print -v X a;; esac; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; while false; do read X <<< a; done; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; [[ -e nope ]] && : ${X::=a}; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; [[ -e nope ]] && X=a; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; : ${X:=a}; rm -rf -- $X", "G-DEL"), ("X=<root>studio; read -t 0 X; rm -rf -- $X", "G-DEL"),
    ("X=<root>studio; eval true; rm -rf -- $X", "G-DEL"),
    ("X=safe; if [[ -e x ]]; then X=<root>studio; else X=b; fi; rm -rf $X", "G-DEL"),
    ("X=<root>studio; X[1]=s; rm -rf $X", "G-DEL"),
    # B4
    ("sh <<< 'rm -rf <root>studio' <> /dev/null", "G-DEL"), ("sh 0<> /dev/null <<< 'rm -rf <root>studio'", "G-DEL"),
    ("sh <<EOF <> /dev/null\nrm -rf <root>studio\nEOF", "G-DEL"),
    ("{ NULLCMD=sh; > /dev/null } <<< 'rm -rf <root>studio' <> /dev/null", "G-DEL"),
    ("python3 <<< 'import shutil; shutil.rmtree(\"<root>studio\")' <> /dev/null", "G-OPAQUE"),
    # P1
    ("echo ${X:-$(( echo a; rm -rf <root>studio ) )}", "G-DEL"),
    ("echo \"${X:-$(( echo a; rm -rf <root>studio ) )}\"", "G-DEL"),
]
G1_REVIEW10_PASS = [
    # M1, conf m-1: the trap-cleanup idiom
    "cleanup(){ rm -f /tmp/lock }; trap cleanup EXIT; git commit -m x",
    "cleanup(){ rm -f /tmp/lock }; trap cleanup EXIT INT TERM; npm test && git commit -am x",
    "cleanup() { rm -rf \"$tmpdir\" }; tmpdir=$(mktemp -d); trap cleanup EXIT; git commit -m x",
    "cleanup(){ rm -f /tmp/lock }; trap cleanup EXIT; git status",
    "cleanup(){ rm -f /tmp/lock }; trap cleanup EXIT; python3 .claude/studio/scripts/x.py",
    "cleanup(){ rm -rf \"$WORK\"; }; WORK=$(mktemp -d); trap cleanup EXIT; cp src/a.ts $WORK/",
    "trap \"rm -f $tmp\" EXIT; git commit -m x", "trap 'rm -f x.tmp' EXIT INT; git add -A && git commit -m x",
    # conf M-1: clustered `set` flags
    "set -euo pipefail; for f in src/*.ts; do wc -l $f; done", "set -euo pipefail; D=$(mktemp -d); cp src/a.ts $D/; rm -rf $D",
    "set -eu; D=/tmp/x; cp a.txt $D/", "set -ex; name=a; cp src/$name.ts /tmp/",
    "set -eo pipefail; for f in $(git diff --name-only); do echo $f; done", "set +eu; ls $X", "set -e -o pipefail; ls $X",
    # conf m-2: a pushd that may not run, then popd
    "pushd nosuch && ls && popd; git commit -m x", "pushd nosuch && ls && popd && git add -A && git commit -m x",
    "pushd nosuch >/dev/null && python3 x.py; popd >/dev/null; git add -A; git commit -m x",
    # values that may or may not change, in ordinary use
    "OUT=dist; if [ -n \"$1\" ]; then OUT=$1; fi; rm -rf $OUT", "if [ -d build ]; then D=build; else D=dist; fi; rm -rf $D",
    "f(){ local X=a; echo $X }; X=build; f; rm -rf $X", "X=build; [[ -e x ]] && X=dist; rm -rf $X",
    "cd src && npm test; cd -; git commit -m x", "[[ -d src ]] && cd src; ls; cd -; git add -A; git commit -m x",
    "echo ${X:-$(( 1 + 2 ))}", "cat < a.txt <> /dev/null", "X=studio; : ${X::=build}; rm -rf -- $X",
]

# G1 implementation review 11: B1 a function this command defined and then removed or replaced (`unfunction`,
# `unhash -f`, `disable -f`, `unset -f --`, `-m` patterns, in another function, eval, emulate -c, a sourced string, a
# definition under a name the guard cannot read, a DEBUG hook) is no longer walked as if still defined; R1 the name
# then runs the command so named (sourced files, choice values and the auditor: G1Review11, test_m1e.Auditor)
_R11_GONE = ["unfunction f", "disable -f f", "unhash -f f", "unset -f -- f", "unset -fm 'f*'", "unfunction -m 'f*'",
             "unfunction x f", "builtin unfunction f", "{ unfunction f }", "unfunction f > /dev/null",
             "[[ -e nope ]] || unfunction f", "[[ -e x ]] && unfunction f", "g(){ unfunction f; }; g",
             "g(){ unset -f f; }; g", "eval 'unfunction f'", "eval 'f(){ :; }'", "emulate zsh -c 'f(){ :; }'",
             "emulate sh -c 'unfunction f'", "n=f; $n(){ :; }", "n=f; function $n { :; }",
             "TRAPDEBUG(){ unfunction f 2>/dev/null; }", "trap 'unfunction f' DEBUG",
             "source /dev/stdin <<< 'f(){ :; }'", "u=unfunction; $u f", "functions -c f g; unfunction f",
             "disable -f f; enable -f f; disable -f f", "if [[ -e x ]]; then unfunction f; fi"]
G1_REVIEW11_DENY = [("f(){ cd /tmp; }; %s; f; rm -rf <root>studio" % g, "G-DEL") for g in _R11_GONE] + \
    [("X=<root>studio; f(){ X=a; }; %s; f; rm -rf -- $X" % g, "G-DEL") for g in _R11_GONE] + [
    ("g(){ unfunction f; }; f(){ cd /tmp; }; g; f; rm -rf <root>studio", "G-DEL"),
    ("f(){ cd /tmp; }; unfunction f; f; mv <root>studio /tmp/x", "G-DEL"),
    ("f(){ cd /tmp; }; unfunction f; f; find <root>studio -delete", "G-DEL"),
    ("f(){ cd /tmp; }; unfunction f; f; echo x > <root>.claude/studio/config.json", "G-PROT"),
    # R1: the command so named runs
    ("sh(){ cat; }; unfunction sh; sh <<< 'rm -rf <root>studio'", "G-DEL"),
    ("sh(){ cat; }; [[ -e x ]] && unfunction sh; sh <<< 'rm -rf <root>studio'", "G-DEL"),
    ("sh(){ cat; }; eval 'unfunction sh'; sh <<< 'rm -rf <root>studio'", "G-OPAQUE"),
    # sweep: a link named under Studio's folders in a folder the guard cannot tell (after eval, as at HEAD)
    ("eval true; ln -sfn /tmp/x <root>studio/videos/v/work", "G-PROT"),
    ("f(){ cd /tmp; }; eval 'f(){ :; }'; f; ln -s /tmp/x <root>studio/videos/v/work/", "G-PROT"),
    # sweep: the same definition walked in several readings stays one function
    ("cd $Q; f(){ g(){ X=<root>studio } }; f; g; rm -rf $X", "G-DEL"),
    ("f(){ cd /tmp; }; eval 'f(){ :; }'; f; Y=(<root>studio); rm -rf $PWD/$Y", "G-DEL"),
]
G1_REVIEW11_PASS = [
    # B1: a function this command removes and calls no more, or defines again
    "f(){ echo hi; }; f; unfunction f; rm -rf build", "f(){ cd src; }; f; unfunction f; git status",
    "f(){ cd /tmp; }; unfunction f; f(){ cd src; }; f; rm -rf build",
    # conf M-1: one of a few known values, judged once per value
    "if [[ -e x ]]; then B=develop; else B=main; fi; git checkout $B", "B=main; [[ -n $X ]] && B=develop; git checkout $B",
    "case $1 in hot) B=main ;; *) B=develop ;; esac; git checkout \"$B\"",
    "if [[ -n $X ]]; then D=src; else D=.; fi; cd $D && git add -A && git commit -m x",
    "if [[ -n $X ]]; then D=src; else D=.; fi; pushd $D; ls; popd; git commit -m x",
    "if [[ -n $X ]]; then N=a; else N=b; fi; python3 scripts/$N.py", "if [[ -n $X ]]; then N=a; else N=b; fi; node scripts/$N.js",
    "if [[ -n $X ]]; then F=a.txt; else F=b.txt; fi; git restore $F",
    "if [[ -n $X ]]; then R=origin; else R=upstream; fi; git log $R/main",
    # review 11 (not counted in round 11): files sourced from the repository
    "source /dev/null; git commit -m x",
]

# G1 implementation review 12: conf M-1 (readings of one command with a word of several known values are alternatives,
# not a bulk copy followed by a write), conf m-5 (`cd X || exit` where X is not there), `HOME=… pushd` with no word;
# sourced files that may move the shell, the `**` listing after them, the >16 message: G1Review12
_R12_OUT = "if [[ -n $CI ]]; then OUT=dist; else OUT=build; fi; "
G1_REVIEW12_DENY = [
    (_R12_OUT + "cp -r src $OUT; mv a.txt <root>studio/videos/v/work/a", "G-PROT"),
    (_R12_OUT + "cp -r src $OUT; touch $OUT/x", "G-PROT"),
    (_R12_OUT + "cp -r src $OUT; cp -r scripts $OUT/b", "G-PROT"),
    ("exit(){ :; }; cd nope || exit 1; rm -rf ../<root>studio", "G-DEL"),
    ("alias exit=:; cd nope || exit 1; rm -rf ../<root>studio", "G-DEL"),
    ("mkdir nope; cd nope || exit 1; rm -rf ../<root>studio", "G-DEL"),
    ("x=$(mkdir nope); cd nope || exit 1; rm -rf ../<root>studio", "G-DEL"),
    ("python3 x.py; cd nope || exit 1; rm -rf ../<root>studio", "G-DEL"),
    ("cd nope || exit 1 2>/dev/null; rm -rf ../<root>studio", "G-DEL"),
    ("cd nope || exit 1 && rm -rf ../<root>studio", "G-DEL"),
    ("( cd nope || exit 1 ); rm -rf <root>studio", "G-DEL"),
]
G1_REVIEW12_PASS = [
    _R12_OUT + "cp -r src/* $OUT/", _R12_OUT + "rm -rf $OUT && mkdir $OUT && cp -r src/* $OUT/",
    _R12_OUT + "mkdir -p $OUT && cp -r src $OUT/", _R12_OUT + 'cp -R src "$OUT"',
    "OUT=dist; [[ -n $CI ]] && OUT=build; cp -r src/* $OUT/", _R12_OUT + "cp -r src $OUT && ls $OUT",
    "if [[ -n $CI ]]; then S=src; else S=scripts; fi; cp -r $S /tmp/backup", _R12_OUT + "rsync -a src/ $OUT/",
    _R12_OUT + "ditto src $OUT", _R12_OUT + "mkdir -p $OUT && tar -xzf /tmp/pkg.tgz -C $OUT",
    _R12_OUT + "unzip -o /tmp/a.zip -d $OUT",
    "cd nope || exit 1; git commit -m x", "cd src || exit 1; npm test; cd ..; git add -A && git commit -m x",
    "source /dev/null; git status",
]

# G1 implementation review 13: review 12's `cd X || exit` early stop is removed (B13-1, B13-2, M13-1 — the folder may
# exist when zsh reaches the cd: made by git, a sourced file, a glob qualifier, or too deep for the guard to stat);
# sourced files that may move the shell are read from their commands (conf M-1): G1Review13
G1_REVIEW13_DENY = [
    ("cd nope || exit 1; rm -rf ../<root>studio", "G-DEL"),
    ("cd nope || return; rm -rf ../<root>studio", "G-DEL"),
    ("cd nope || logout; rm -rf ../<root>studio", "G-DEL"),
    ("git branch nope/x; cd nope || exit; rm -rf ../<root>studio", "G-DEL"),
    ("git stash pop; cd nope || exit; rm -rf ../<root>studio", "G-DEL"),
    ("y=(*(e:'mkdir -p nope':)); cd nope || exit; rm -rf ../<root>studio", "G-DEL"),
]
# review 14: sourced files are never followed (B14-1 … B14-6, M14-1 were all in the following); what a `source` leaves
# unknown is judged as at HEAD; `~[name]` (zsh_directory_name) operands are refused. Files: G1Review14
G1_REVIEW14_DENY = [
    ("cp -R /tmp/stage/. .venv; source /dev/null", "G-PROT"),  # a source is a later writer for W4, as at HEAD
    ("tar -xf /tmp/s.tar -C dist; . /dev/null", "G-PROT"),
    ("rm -rf ~[x]/studio", "G-OPAQUE"), ("echo x > ~[x]/studio/videos/v/work/state.json", "G-OPAQUE"),
]
G1_REVIEW14_PASS = [
    "source .venv/bin/activate && git commit -m x", "source env.sh && git status",
    "source x && git add -A && git commit -m x", "source x; rm -rf **/__pycache__", "source cd.sh; git commit -m x",
    "source env.sh; cd src; git commit -m x", "set -a; . ./env.sh; set +a; git commit -m x",
    "source .venv/bin/activate && pytest", "source .venv/bin/activate; cd src; npm test; cd ..; git add -A && git commit -m x",
    "[[ -f env.sh ]] && source env.sh; git commit -m x", "source env.sh || true; git status",
    "source /dev/null; cd $D; git commit -m x",  # review 18: as at HEAD (git is not checked after a source)
]
# review 15 (B15-1/2): `~[…]` is a tilde part only for a plain name; other text is lexed as before, so `;`, `&&`
# end the word and `$(…)` inside it is walked. C15-1/C15-2: G1Review15
G1_REVIEW15_DENY = [
    ("X=~[x;rm${=IFS}-rf${=IFS}studio;]", "G-OPAQUE"), ("noglob : ~[x&&rm${=IFS}-rf${=IFS}studio&&]", "G-OPAQUE"),
    (": ~[$(rm${=IFS}-rf${=IFS}studio)]", "G-OPAQUE"), ("X=~[$(git${=IFS}clean${=IFS}-fdx)]", "G-OPAQUE"),
    ("ls ~[`rm${=IFS}-rf${=IFS}.claude`]/", "G-OPAQUE"), (": ~[${X::=$(rm${=IFS}-rf${=IFS}studio)}]", "G-OPAQUE"),
]
# after a source, as at HEAD (files: G1Review15)
G1_REVIEW15_PASS = [
    "source .venv/bin/activate && rm -rf work", "source .venv/bin/activate && rm -rf src/work",
    "source env.sh && rm -f state.json", "source env.sh && mkdir -p audio && cp a.txt audio/",
    "source env.sh && ffmpeg -i in.mp4 audio/out.wav", "source env.sh && python3 x.py --out audio/a.wav",
    "source env.sh && python3 x.py > state.json", "source env.sh && cp a.txt CREDITS.yaml",
    "source scripts/env.sh; touch state.json", "pushd src; source ../scripts/env.sh; popd; git commit -m x",
    "cd src && source ../.venv/bin/activate && cd - && git status", "cd src; source e.sh; cd ~-; git commit -m x",
    "cd src; source e.sh; cd ~-; git reset --hard", "ls ~[x]/", "echo ~[proj:a.b]",
]
# review 16: a pushd the guard cannot follow, then popd (C16-1/2); HEAD's folder after a source kept as a known folder
# next to the unknown one (B16-1/2)
G1_REVIEW16_DENY = [
    ("source /dev/null && popd && rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("source /dev/null && pushd $X && popd && echo x > <root>studio/videos/v/work/state.json", "G-PROT"),
    ("pushd $X && popd && rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("pushd -q $X >/dev/null && popd && rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("D=$(mktemp -d); pushd $D && popd && rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("pushd $(mktemp -d) && popd && rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("pushd s* && popd && rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("pushd ~[x] && popd && rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("pushd - && popd && rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("pushd +1 && popd && rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("pushd $X; popd && rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("cd .; source /dev/null; cd -; git worktree add <root>studio/x", "G-PROT"),
    ("pushd .; source /dev/null; popd; git worktree add <root>studio/x", "G-PROT"),
    ("cd .; source /dev/null; pushd ~-; git init <root>studio/x", "G-PROT"),
]
G1_REVIEW16_PASS = [
    "source .venv/bin/activate && pushd src && npm test && popd && git status",
    "pushd src; source ../.venv/bin/activate; popd; git add -A && git commit -m x",
    "cd src && source ../.venv/bin/activate && cd - && rm -rf build && mkdir build",
    "source .venv/bin/activate && pushd src && npm test && popd && rm -rf work",
    "source .venv/bin/activate && pushd src && npm test && popd && mkdir -p audio",
    "pushd /tmp && popd && ls", "pushd $X && make && popd && git status", "pushd $X && popd && git commit -m x",
    "cd src; source e.sh; cd -; cd -; git checkout .", "cd src; source e.sh; cd -; pushd studio; popd; rm -rf work",
    "cd src; source e.sh; cd -; python3 -m pytest", "cd src; source e.sh; cd -; ls **/*.py",
    "cd src; source e.sh; cd -; f(){ :; }; f; git commit -m x", "pushd -q src && source ../.venv/bin/activate && popd -q && git push",
    "source e.sh; python3 ev.py",  # no folder change after the source: as at HEAD (guard-limits)
]
# review 17: $OLDPWD that is one of several folders (B17-1); a source inside a function (B17-2); nested code after a
# source and `cd -` / `popd` read in the folder HEAD knew (C17-1)
G1_REVIEW17_DENY = [
    ("cd <root>src; pushd $X; rm -rf $OLDPWD/<root>studio/videos/v/work", "G-DEL"),
    ("cd <root>src; [[ -n $Z ]] && cd ../scripts; cd ~-; rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("cd <root>src; pushd $X; X2=$OLDPWD; cd $X2; ln -sf /tmp/x <root>.git/config", "G-HOOKOFF"),
    ("f(){ cd <root>src; source e.sh; cd -; }; f; rm -rf <root>studio/videos/v/work", "G-DEL"),
    ("cd <root>src && source /dev/null && cd - && bash -c 'rm -rf <root>studio/videos/v/work'", "G-DEL"),
]
G1_REVIEW17_PASS = [
    "cd src && source ../.venv/bin/activate && cd - && bash scripts/release.sh",
    "cd src && source ../.venv/bin/activate && cd - && sh ./scripts/release.sh",
    "cd src && source ../.venv/bin/activate && cd - && bash -c 'npm test'",
    "cd src && source ../.venv/bin/activate && cd - && source scripts/env.sh && git status",
    "pushd scripts && . ./e.sh && popd && bash scripts/release.sh",
    "pushd src >/dev/null; source ../.venv/bin/activate; popd >/dev/null; bash scripts/release.sh",
    "cd src; . ../e.sh; cd -; sh -c 'rm -rf build'",
    "cd scripts && source env.sh && cd - && bash scripts/release.sh",
    "pushd src; pushd $X; cd ~-; ls", "cd src; pushd $X; cd ~-; git status", "pushd src; pushd $X; cd ~-; rm -rf build",
    "f(){ cd src; source ../e.sh; cd -; }; f; ls", "f(){ pushd src; source ../e.sh; popd; }; f; npm test",
]
# review 18: `source` / `.` as at HEAD — afterwards the folder is unknown (git not checked there, paths read as HEAD
# read them), and `cd -`, `popd`, `~-` and `$OLDPWD` go where HEAD's walk sent them (HEAD's $OLDPWD and stack, not the
# ones G1 follows further: functions, loops, options HEAD could not read). Files and a clean tree: G1Review18
G1_REVIEW18_DENY = [
    # HEAD's $OLDPWD after a source is the folder before it, also after a later relative cd
    ("cd <root>src; source /dev/null; cd ../scripts; cd -; git worktree add <root>studio/x", "G-PROT"),
    ("cd <root>src; source /dev/null; rm -rf ~-/<root>studio/videos/v/work", "G-DEL"),
    # HEAD did not know the folder after a loop that moves: `cd -` after a source goes to a folder it cannot tell
    ("for d in <root>src; do cd $d; cd ..; done; cd src; source /dev/null; cd -; bash -c 'rm -rf <root>studio/videos/v/work'",
     "G-OPAQUE"),
    ("sh -c 'git checkout .'; git stash pop; sh -c 'git checkout .'", "G-RESET"),  # B18-2 (also: G1Review18)
]
G1_REVIEW18_PASS = [
    "source .venv/bin/activate; cd src; cd ~-; cd src; cd ~-; git commit -am x",
    "source .venv/bin/activate && ROOT=$(pwd) && cd src && npm test && cd \"$ROOT\" && git add -A && git commit -m x",
    "source .venv/bin/activate && cd src && npm test && cd \"$OLDPWD\" && cd ../scripts && ls && cd \"$OLDPWD\" && "
    "git add -A && git commit -m x",
    "source .venv/bin/activate; X=$PWD; cd src; cd $X; git commit -am x",
    "source .venv/bin/activate; cd src; cd -; cd src; cd -; rm -rf work",
    "pushd src >/dev/null; source ../.venv/bin/activate; pushd ../scripts >/dev/null; popd >/dev/null; popd >/dev/null; "
    "mkdir -p audio",
    "cd src && source ../.venv/bin/activate && cd - && cd src && cd - && mkdir -p audio",
    "source .venv/bin/activate && cd src && pytest && cd - && rm -rf **/__pycache__",
    "pushd src; source e.sh; popd; python3 .claude/studio/scripts/state.py status",
    "set -euo pipefail; source .venv/bin/activate && git commit -am x",
]
# review 19: after a source every decision of HEAD's folder model is HEAD's own — whether a function call moved the
# shell (decided at the definition, from HEAD's folder and option table there: B19-1), a source where HEAD did not
# know the folder (G-OPAQUE, absolute files too: B19-2), AUTO_PUSHD on unless the snapshot sets it off (B19-3), a
# loop variable read as unknown, the environment HEAD read. {R} = the repository (G1Review19; script.md modified)
G1_REVIEW19_DENY = [
    ("pushd -q studio/videos/v; source {R}/.venv/bin/activate; f(){ cd {R}/src; }; f; popd -q; git checkout .",
     "G-RESET"),
    ("pushd -q studio/videos/v; source {R}/.venv/bin/activate; f(){ cd {R}/src; }; f; popd -q; git clean -fdx",
     "G-CLEAN"),
    ("f(){ cd {R}/src; popd -q; }; pushd -q studio/videos/v; source {R}/e.sh; f; popd -q; git checkout .", "G-RESET"),
    ("for d in src; do cd $d; cd ..; done; f(){ cd {R}/studio/videos/v; }; source {R}/e.sh; cd {R}/studio/videos/v; f; "
     "git checkout .", "G-RESET"),
    ("for d in src; do cd $d; cd ..; done; cd studio/videos/v; source {R}/e.sh; cd {R}; cd -; git checkout .",
     "G-OPAQUE"),
    ("for d in src; do cd $d; cd ..; done; cd studio/videos/v; source {R}/e.sh; cd {R}; cd -; rm -rf work", "G-OPAQUE"),
    ("f(){ set -e; }; source {R}/e.sh; f; cd {R}/studio/videos/v; git checkout .", "G-RESET"),
    ("source {R}/e.sh; f(){ set -x; }; f; pushd -q {R}/studio/videos/v; rm -rf work", "G-DEL"),
]
# with your shell functions (G1Review19.FUNCS: gh, mkcd, up, prompt_info; `take` in the default snapshot): a plain
# wrapper after a source keeps the environment the source's (C19-1); repeated nested pushes / commits (C19-2)
G1_REVIEW19_PASS = [
    "source .venv/bin/activate && gh pr create --fill && git push",
    "source .venv/bin/activate && gh pr view 1 && git add -A && git commit -m x",
    "source .venv/bin/activate && gh pr view 1 && git checkout -b x",
    ". .venv/bin/activate; gh pr checks; git log -1",
    "source .venv/bin/activate && take build && cd .. && git status",
    "source .venv/bin/activate && mkcd build && cd - && git status",
    "source .venv/bin/activate && up 1 && cd - && git status",
    "source .venv/bin/activate && prompt_info && git status",
    "for d in src; do cd $d; cd ..; done; cd {R}/src; source {R}/e.sh; cd {R}; git status",
    "sh -c 'git push'; sh -c 'git push'; sh -c 'git push'",
    "bash -c 'git add -A && git commit -m x'; bash -c 'git add -A && git commit -m x'",
]
G1_REVIEW13_PASS = [
    "cd src || exit 1; git status", "cd src || exit 1; cd ..; git commit -m x",
    "set -a; source /dev/null; set +a; git commit -m x",
]


def g1_deny(root):
    rows = G1_DENY + G1_REVIEW1_DENY + G1_REVIEW2_DENY + G1_REVIEW3_DENY + G1_REVIEW4_DENY + G1_REVIEW5_DENY + \
        G1_REVIEW6_DENY + G1_REVIEW7_DENY + G1_REVIEW8_DENY + G1_REVIEW9_DENY + G1_REVIEW10_DENY + G1_REVIEW11_DENY + \
        G1_REVIEW12_DENY + G1_REVIEW13_DENY + G1_REVIEW14_DENY + G1_REVIEW15_DENY + G1_REVIEW16_DENY + \
        G1_REVIEW17_DENY + G1_REVIEW18_DENY
    if root:
        # review 18: after a source the folder is unknown and a relative path is read as HEAD read it, from the
        # repository root — `../../../studio` from studio/videos/v passes there, as at HEAD
        rows = [(c, r) for c, r in rows if "; source /dev/stdin <<< 'f(){ :; }'; f; " not in c and
                not c.startswith(("source /dev/null && popd && ", "source /dev/null && pushd $X && popd && "))]
    return [(c.replace("<root>", root), r) for c, r in rows]


MUST_DENY += g1_deny("")


def runner_deny(root):
    """RUNNER_DENY and G1_DENY from another folder: `root` leads to the repository root (test_pilot2_guard runs them
    under studio/videos/v)."""
    return [(re.sub(r"(?<![\w/.$-])(studio|\.claude)(?=[/\s'\";]|$)", lambda m: root + m.group(1), c), r)
            for c, r in RUNNER_DENY] + g1_deny(root)
NO_SNAPSHOT_DENY = ["g st", "gst", "ll", "take newdir", "g clean -fdx"]

MUST_PASS = [
    "git status", "git diff", "git log --oneline -5", "git add src/x.ts", "git add -A", "git commit -m 'fix: x'",
    "git push", "git pull --rebase", "git checkout -b feat/x", "git switch main", "git stash", "git stash pop",
    "git clean -n", "git clean -fd src/", "git reset --hard", "git fetch", "gh pr create --fill", "gh pr view 12",
    "npm test", "yarn build", "pnpm lint", "make", "npx tsc --noEmit", "python3 -m pytest", "node scripts/build.js",
    "ls -la studio", "cat studio/videos/v/work/state.json", "grep -r foo studio", "rg foo", "find . -name '*.md'",
    "find studio -name '*.md'", "cp src/a.ts src/b.ts", "mkdir -p src/x", "rm -rf node_modules dist", "rm src/a.ts",
    "mv a.txt b.txt", "sed -i '' s/a/b/ src/x.ts", "cat > src/y.ts <<'EOF'\nx\nEOF", "echo x > notes.md",
    "tee README.md < /dev/null", "touch studio/videos/v/script.md", "echo x >> studio/local/videos/w/notes.md",
    "python3 -c 'print(1)'", "python3 - <<'EOF'\nimport json\nEOF", "node -e 'console.log(1)'", "bash scripts/release.sh",
    "python3 .claude/studio/scripts/state.py next v", "python3 .claude/studio/scripts/state.py status",
    "python3 .claude/studio/scripts/lock.py status --json",
    "python3 .claude/studio/scripts/lock.py run --kind tts -- s2v tts studio/videos/v/script.md",
    "s2v --version --json", "s2v inspect --json studio/videos/v/script.md", "S2V_TTS=mock node test.js",
    "find . -name '*.json' -exec grep -l x {} +", "curl -o /tmp/x.json https://example.invalid/a",
    "cp a.txt studio/videos/v/", "tar -xf a.tar -C dist", "dd if=a.txt of=dist/b.txt",
    # fix-0025 §1: the sed read and edit shapes (every form also runs on BSD /usr/bin/sed)
    "sed -n 1,80p .claude/studio/scripts/state.py", "sed -n '/def /p' narrator.py", "sed -n '/^## A/,/^## /p' notes.md",
    "sed -n '/a/I,/b/Ip' a.txt", "sed -n '/a/I!p' a.txt", "sed -n 01,3p a.txt",
    "find src -name a.md -exec sed -n p {} \\;", "sed -n '$=' a.txt", "sed '1d;3q' a.txt", "sed -n '/x/{p;q;}' a.txt",
    "sed -E -n 's/a/b/p' .claude/studio/config.json", "sed -i.bak s/a/b/ src/x.ts",
]
# G1 (§5 MUST_PASS): wrappers on ordinary work, folders the guard cannot tell, words §1.10 does not refuse
RUNNER_PASS = [
    "timeout 60 npm test", "timeout -s KILL 5 make", "gtimeout 1.5m yarn build", "nohup npm run dev &",
    "nice -n 10 make", "/usr/bin/time -p npm test", "/usr/bin/time -o /tmp/t.txt npm test", "env NODE_ENV=test npm test",
    "env -C src ls", "env -u CI npm test", "caffeinate -i npm run build", "stdbuf -oL npm test",
    "script -q /dev/null npm test", "flock /tmp/build.lock make", "arch -arm64 npm test", "xcrun --show-sdk-path",
    "sudo -l", "xargs -0 grep -l x < /dev/null", "printf 'a\\n' | xargs -I{} cat {}", "npx -y prettier --check src",
    "npx tsc --noEmit", "npm exec -- tsc --noEmit", "command -v git", "exec git status",
    "xargs -P $(nproc) grep -l x < /dev/null", "npx --no-install x", "npx --registry=https://example.invalid tsc",
    "lockf /tmp/build.lock make", "flock /tmp make", "command ls studio", "command git status", "sudo -k",
    "gnice -n 5 make", "gstdbuf -oL npm test", "gtime -p npm test", "chronic -e make", "unbuffer -p npm test",
    "ionice -c 3 make", "setsid -f make", "sandbox-exec -n no-network make", "taskpolicy -c utility make",
    "doas -u root make", "watch -n 1 ls", "busybox ls", "toybox ls", "busybox.static ls",
    # `-` is an alias of `cd -` in the test snapshot (reviewG1 p3); without one it is the precommand: `rm`
    "- rm -rf node_modules",
    # unknown folders (§1.7a): nothing protected is named
    "cd $(mktemp -d) && echo x > a.txt", "cd $(mktemp -d) && git clone https://example.invalid/r.git",
    "cd $DIR && npm install", "cd $DIR && rm -rf node_modules", "for d in src dist; do (cd $d && ls > out.log); done",
    "cd - && touch notes.md", "cd $OLDPWD && touch a.txt", "cd ~1 && touch a.txt", "cd node_modules; rm -rf .cache",
    "cd $UNKNOWN; rm -rf node_modules", "cd $DIR && echo '{}' > config.json", "cd $DIR && rm -rf source",
    # not refused by §1.10
    "echo 'rm -rf studio'", "grep -r 'rm -rf studio' src", "printf '%s\\n' 'touch studio/x'",
]
MUST_PASS += RUNNER_PASS
# G1 (§1.8, §1.9, §1.11, §2, §3; §5 MUST_PASS and reviews 2–7)
G1_PASS = [
    # §1.9: allowed editor and pager values, keys that run nothing
    "git -c color.ui=false log", "git -c user.name=x commit -m 'fix: x'", "GIT_EDITOR=true git commit -m x",
    "GIT_PAGER=cat git log", "git -c core.pager=cat log", "GIT_PAGER= git log", "GIT_EDITOR=vi git commit",
    "EDITOR=vim git commit", "git -c core.editor=vi commit", "VISUAL=nano git commit", "GIT_PAGER=less git log",
    "git config user.name x", "git config --get core.editor", "git grep -n x", "git fetch", "git fetch origin",
    "git clone -c http.sslVerify=true https://example.invalid/r.git /tmp/r", "export PAGER=less",
    # §1.8: zsh forms that change nothing the guard reads
    "autoload -Uz compinit", "autoload -U is-at-least", "zmodload zsh/datetime", "setopt extendedglob; ls",
    "(( n = 1 + 2 ))", "print -P '%F{red}x%f'", "echo ${+commands}", "echo ${commands[ls]}",
    # review 5: special parameter names in other programs' words
    "firebase deploy --only functions", "npx supabase functions deploy", "ls functions", "git add functions",
    "grep -rn options src", "echo options", "cd functions",
    # §1.11: plain reads
    "exiftool -json -G1 -Duration studio/voices/a/x.wav", "exiftool -r -ext wav studio/voices",
    "exiftool studio/voices/a/x.wav", "exiftool -j -Duration studio/voices/a/x.wav", "open studio/videos/v/out/v.mp4",
    "sort a.txt", "sort -u a.txt > /tmp/x", "uniq a.txt", "xxd a.txt", "tree src", "rg foo src", "open README.md",
    "open https://example.invalid", "open -R studio/videos/v/script.md",
    # §2: globs that match nothing protected (`**` by listing the folders)
    "rm -rf **/__pycache__", "rm -f **/*.pyc", "rm -f */*.log", "touch **/*.ts", "ls src/**/*.ts",
    "ls studio/videos/*/script.md", "cat studio/videos/*/script.md", "rm -f dist/*.js", "touch src/*.ts",
    "cp src/*.ts dist/", "rm studio/videos/v/out/*.mp4", "find . -name '*.md'",
    # §3: empty words
    "X=; ls $X src", "echo \"$HOME\"", "cd \"$(git rev-parse --show-toplevel)\" && git status",
    "for f in studio/videos/*/script.md; do wc -l $f; done",
]
MUST_PASS += G1_PASS
# G1 implementation review 1: what must keep passing
G1_REVIEW1_PASS = [
    # m6: xcrun's one-dash long options; -f looks a tool up
    "xcrun -sdk macosx --show-sdk-path", "xcrun -find clang", "xcrun -f clang",
    # C-m1: help and version run nothing
    "npx --version", "npx -v", "npx --help", "npm exec --help", "timeout --help", "env --help", "nohup --help",
    "xargs --version",
    # C-m2: ext:: only in URLs
    "git commit -m 'docs: ext:: urls'",
    # M1, M3, M5–M7, M11, M12, C-M3: the ordinary forms
    "env -C src -C . ls", "env -C $D rm -rf node_modules", "npm --prefix . exec -- tsc --noEmit",
    "git send-email --to x@example.invalid x.patch", "git config --rename-section x y", "git -c user.name=$N commit -m x",
    "exiftool -lang de -Duration studio/voices/a/x.wav", "echo ${(s:e:)X}", "a=(src dist); ls $a",
    "while read -r f; do echo $f; done < a.txt", "zstyle ':completion:*' menu select",
]
MUST_PASS += G1_REVIEW1_PASS
# G1 implementation review 2: what must keep passing
G1_REVIEW2_PASS = [
    # B-1, B-2, M11, M12: names that match nothing protected under a folder the guard cannot tell or a wildcard
    "cd $DIR && rm -f *.log", "cd $DIR && rm -rf *.bak", "cd $DIR && cp ../notes.md .", "cp src/a.ts dist*/",
    "tar -xf a.tar -C dist*", "cp -r src/. dist*", "cd $DIR && git status", "cd $DIR && git add src/a.ts",
    "cd $DIR && git stash", "cd $DIR && git checkout -b feat/x", "env -C $D git log -1", 'git -C "" status',
    # M2–M9, M13, M15, M16: the ordinary forms
    "print -u2 hello", "print -rl -- a b", "set -- a b", "typeset -T MYPATH mypath :",
    "echo ${(j: :)X}", "echo ${(l:3::0:)X}", "arr=(a b); echo $arr[1]", "X='src/*.ts'; ls $~X",
    "git clone -q https://example.invalid/r.git /tmp/r", "git config --rename-section x y",
    "git send-email -to x@example.invalid x.patch", "zstyle -- ':completion:*' menu select", "make -j4 -f Makefile",
    "make -sC src", "tar -cf x.tar --checkpoint=1 --checkpoint-action dot a.txt",
]
MUST_PASS += G1_REVIEW2_PASS
# G1 implementation review 3: what must keep passing
G1_REVIEW3_PASS = [
    # (conf m-3's glob qualifiers are refused again: the Bash tool runs with BARE_GLOB_QUAL off, review 4 B2)
    # conf M-4: an eval that sets no option leaves the options known
    "eval ls; echo $X", "eval 'ls src'; ls $dir",
    # bypass M1, R1: other npm options, brace ranges on ordinary names
    "npx --cache=/tmp/c tsc --noEmit", "npm --prefix . exec -- tsc --noEmit", "echo {a..c}", "mkdir -p src/{a..c}",
]
MUST_PASS += G1_REVIEW3_PASS
# G1 implementation review 4: what must keep passing
G1_REVIEW4_PASS = [
    # conf M-1: no file names are generated (`[[ ]]`, case, assignments, counts), or a value this call cannot steer
    "setopt globsubst; [[ -n $X ]] && echo y", "setopt globsubst; X=$Y npm test", "setopt globsubst; Z=$Y; echo hi",
    "setopt globsubst; case $X in a) echo a;; esac", "setopt globsubst; echo ${#X}", "setopt globsubst; local v=$X",
    "setopt globsubst; typeset -i n=$X", "setopt globsubst; ls $dir", "setopt globsubst; echo $X",
    "setopt globsubst; echo ${X:-y}", "setopt globsubst; for i in 1 2 3; do echo $i; done",
    "setopt globsubst; arr=(a b); echo ${arr[1]}", "eval 'ls src'; ls $X", "setopt globsubst; cat <<< $X",
    # conf M-2: quoted `(`, `[`, `*`, `?` under a folder the guard cannot tell are letters
    "cd $(mktemp -d) && python3 -c 'print(1)'", "cd $D && python3 -c 'print(1)'", "cd $D && node -e \"require('fs')\"",
    "cd $D && perl -e 'print(1)'", "cd $D && python3 x.py 'arg(1)'", "cd $D && touch 'a(1).txt'",
    "cd $D && touch a\\(1\\).txt", "cd $D && cp /tmp/x 'notes (copy).md'", "cd $D && echo hi > 'out(1).txt'",
    "cd $D && mkdir 'v(2)'", "cd $D && touch 'a[1].txt'", "cd $D && touch 's*.json'", "cd $D && rm -f 'a(1).txt'",
    "cd $D && rm -rf 'build (old)'", "cd $D && python3 -c 'print([1])'", "cd $D && python3 -c 'print(\"x\")'",
    "cd $(mktemp -d) && sed -n '1,5p' 'a(1).txt'", "cd - && touch 'a(1).txt'",
    # bypass R2, R4, m1: the ordinary forms
    "pushd src && ls", "pushd -q src; popd", "NULLCMD=cat; > /dev/null <<< x", "> out.txt <<< x", "typeset -p PATH",
    "trap 'rm -f /tmp/x.$$' EXIT; ls",
]
MUST_PASS += G1_REVIEW4_PASS
# G1 implementation review 5: what must keep passing
G1_REVIEW5_PASS = [
    # conf M-1: allowed pager and editor values (plan MUST_PASS)
    "GIT_PAGER=cat git log -1", "GIT_PAGER= git log -1", "PAGER=cat git log -1", "PAGER=less git diff",
    "EDITOR=vi git log -1",
    # M1, M2: parts of values with no `(`, counts, a prompt under its other name, a literal array
    "setopt globsubst; ls $HOME:t", "setopt globsubst; arr=(a b); ls $arr[1]", "setopt globsubst; X=src; ls $X:t",
    "setopt globsubst; ls -d $PWD:h", "setopt globsubst; echo $#", "setopt globsubst; echo $?",
    "setopt globsubst; PS1='%m'; echo $PROMPT", "setopt globsubst; typeset -a W=(a b)",
    # M4, M5: several function names; a pipe into the default NULLCMD, an assignment with a redirection
    "function a b { echo hi }; a; b", "print hi | NULLCMD=sh > /dev/null", "echo x | > /dev/null",
    "NULLCMD=cat; print x | > /dev/null", "print hi | ( cat )",
    # borderline: `^` is a letter while EXTENDED_GLOB is off; a plain name under an unknown folder
    "cd $D; rm -rf ^x", "setopt extendedglob; cd $D; rm -f notes.txt", "pushd src; pushd; ls",
    # R1, R2: the forms zsh runs, with harmless names
    "{ X=v }; echo $X", "if true; then X=v fi; echo $X", "f(){ X=1 }; f; echo $X", "{ ls; } always { echo done }",
    "y(){ export FOO=1; }; y; git commit -m x", "y(){ local x=1; echo $x; }; y; git commit -m x",
    "f(){ X=build; }; f; rm -rf $X",
]
MUST_PASS += G1_REVIEW5_PASS
# G1 implementation review 6: what must keep passing
G1_REVIEW6_PASS = [
    # conf M-1: a regular expression after `=~` (its groups are no glob groups)
    "if [[ $b =~ ^feature/(.*)$ ]]; then echo $match[1]; fi", "[[ $x =~ ^v([0-9]+)$ ]] && echo $match[1]",
    "[[ $x =~ ^(main|develop)$ ]] && echo protected", "[[ $v =~ ^v([0-9]+)\\.([0-9]+)$ ]] && echo $match[2]",
    "[[ ( $x =~ ^a(b)c$ ) && -n $y ]] && echo y", "[[ $x =~ (a|b) ]] && echo y",
    # M10: the long forms of loops and conditions
    "for f in src/*.ts\ndo\n  echo $f\ndone", "for f in a b; do\n  echo $f\ndone", "if [ -f a.txt ]\nthen\n  echo y\nfi",
    "if [[ -n $x ]]; then echo a\nelif [[ -n $y ]]; then\n echo b\nelse\n echo c\nfi", "while true\ndo\n break\ndone",
    "case $x in\n  a|b) echo ab ;;\n  *) echo other ;;\nesac", "for ((i = 0; i < 3; i++)); do echo $i; done",
    "select x in a b; do break; done", "until [ -f done.txt ]; do sleep 1; done",
    # an alias inside `$(…)` (`ls` is `ls -G` in the fixture) no longer breaks the words after it
    "for f in $(ls src); do echo $f; done", "for f in $(ls src) $(ls a); do echo $f; done", "echo \"$(ls src) x\"; echo y",
    # M5-M9: input and functions in ordinary use
    "f(){ cat }; f < a.txt", "f(){ cat }; f <<< hi", "f(){ sh }; f < /dev/null", "exec 2>/dev/null; ls",
    "exec 3>/tmp/out.txt; echo hi >&3; exec 3>&-", "{ echo a; echo b; } > out.txt", "git log | { read x; echo $x; }",
    "while read -r l; do echo $l; done < a.txt", "f(){ echo hi }; functions -c f k; k", "functions f", "functions",
    # M1-M3: values with `(` that make no qualifier
    "setopt globsubst; X='file (1)'; Y=.txt; ls -d $X$Y", "setopt globsubst; X=src; Y=a.ts; ls $X/$Y",
    # conf m-1: extended-glob words that cannot match a protected name
    "setopt extendedglob; cd $D; touch notes#1", "setopt extendedglob; cd $D; cp a.txt a.txt~",
    "setopt extendedglob; cd $D; rm -f *~", "setopt extendedglob; rm -f studio~x/a.txt",
    # M12: wildcards that match no hook file (none is installed in this fixture)
    "rm -f .git/*.lock", "cp /tmp/x .git/hooks/pre-commi?",
]
MUST_PASS += G1_REVIEW6_PASS
# G1 implementation review 7: what must keep passing
G1_REVIEW7_PASS = [
    # conf M-1, m-1: a glob group in a `[[ … == pattern ]]` operand (no file names are generated there)
    "[[ $x == (a|b) ]] && echo y", "if [[ $x == (a|b) ]]; then echo y; fi",
    "if [[ $answer == (y|Y|yes) ]]; then echo ok; fi", "if [[ $1 == (-h|--help) ]]; then echo usage; fi",
    "if [[ $(git rev-parse --abbrev-ref HEAD) == (main|master) ]]; then echo m; fi",
    "if [[ $OSTYPE == (darwin|linux)* ]]; then echo os; fi", "if [[ ! $x == (a|b) ]]; then echo n; fi",
    "if [[ $x == (#b)(*)-(*) ]]; then echo $match; fi", "while [[ $x == (q|quit) ]]; do x=; done",
    "if true; then echo; elif [[ $x == (a|b) ]]; then echo b; fi", "[[ $x != (a|b) ]] || echo y",
    "[[ $x = (a|b) ]] && echo y", "[[ $x == *.(ts|tsx) ]] && echo ts", "[[ a == a && (b == (b|c)) ]] && echo y",
    "for i in x; do; echo $i; done", "echo a &; echo b", "if true; then; echo t; fi", "echo a; ; echo b",
    # R3: several loop names
    "for i j in x y; do echo $i $j; done", "for k v in a 1 b 2; do\n  echo $k=$v\ndone",
    # M4: input into eval and `-c` strings in ordinary use
    "eval sh <<< 'echo hi'", "zsh -c 'cat' <<< hi", "eval 'echo hi'; cat <<< x", "eval 'f(){ echo hi }'; f <<< x",
    "bash -c 'wc -l' < a.txt", "print -r -- hi | sh -c 'cat'",
    # M5: `~-` and `~+` are zsh's own folders, whatever $OLDPWD and $PWD hold (checked in zsh 5.9)
    "OLDPWD=studio; ls ~-", "PWD=studio; ls ~+/src",
    # M3: positionals in ordinary use
    "set -- a b; shift; echo $1", "1=x; echo $1",
    # B1, M2: brackets that cannot match a protected name
    "setopt extendedglob; rm -f x[~]y", "rm -f [ab].log", "rm -f build/[!s]*.o", "setopt extendedglob; cd $D; rm -rf *[~]",
    "ls file[1].txt", "setopt extendedglob; rm -f dist/[a-z]*.js",
]
MUST_PASS += G1_REVIEW7_PASS
# G1 implementation review 8: what must keep passing
G1_REVIEW8_PASS = [
    # B1: real redirections next to `<`, and numeric globs that cannot match a protected name
    "cat < README.md", "cat <README.md", "cat <<< hi", "cat <> /tmp/x", "cat <&0", "ls <1-20>.txt", "ls file<->.log",
    "rm -f /tmp/x<->", "echo a <-> b", "[[ 12 == <1-20> ]] && echo y", "x=<->; echo $x", "sort < a.txt > /tmp/b.txt",
    # B2: redirections that cannot fail, and ordinary failure handling
    "true > /dev/null || echo n", "true 2>&1 || echo n", "true 0<&- || echo n", "cd src > /dev/null || exit 1",
    "pushd src > /dev/null && npm test && popd > /dev/null", "cd src 2>/dev/null || mkdir src",
    "npm test > /tmp/log 2>&1 || cat /tmp/log", "git status | grep x || echo none", "true | false || echo n",
    "setopt pipefail; git log | head -1 || echo none",
    # M1: zsh forms the parser now reads
    "time; ls", "time npm test", "time | cat", "! true; echo x", "case $x in (a) echo a;| (b) echo b;; esac",
    "echo a &>| /dev/null", "npm run build &>| /tmp/build.log", "npm test >>& /tmp/test.log", "time (npm test)",
    # conf m-1, m-2: case patterns are patterns, not file names
    "case $x in (#i)abc) echo y;; esac", "case $x in (#i)yes|(#i)y) echo yes;; esac", "case $f in *.(ts|tsx)) echo ts;; esac",
    "case $f in *.(md|txt)) cat $f;; esac", "case $x in *(#i)foo*) echo f;; esac", "case $x in (a) echo a;; (b|c) echo bc;; esac",
    "case $1 in (-h|--help) echo h;; esac", "case $x in \\(*) echo p;; esac", "case $x in <->) echo n;; esac",
    "case $f in (*.ts|*.tsx)) npx eslint $f;; esac", "for f in src/*; do case $f in *.(ts|tsx)) echo $f;; *) ;; esac; done",
    "case $x in\n  a) echo a ;;\n  b|c)\n    echo bc\n    ;;\nesac",
    # M3: GLOB_STAR_SHORT words that cannot match a protected name
    "rm -rf **local", "setopt globstarshort; ls **.md", "setopt globstarshort; rm -f src/**.tmp",
    "setopt globstarshort; git add **.ts",
    # M2: functions and HOME in ordinary use
    "f(){ ls ~/; }; HOME=/tmp/h f", "f(){ echo $1; }; f a", "HOME=/tmp/x eval 'ls ~/'", "eval 'X=1'; ls ~/",
    "f(){ npm test; }; cd src; f",
]
MUST_PASS += G1_REVIEW8_PASS
MUST_PASS += G1_REVIEW9_PASS
MUST_PASS += G1_REVIEW10_PASS
MUST_PASS += G1_REVIEW11_PASS
MUST_PASS += G1_REVIEW12_PASS
MUST_PASS += G1_REVIEW13_PASS
WITH_SNAPSHOT_PASS = ["g st", "gst", "ll", "grep foo src", "find . -name x", "take newdir"]


class MustDeny(JudgeCase):
    def test_must_deny_with_and_without_snapshot(self):
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, rule in MUST_DENY:
                self.assertDeny(cmd, rule)

    def test_no_snapshot_aliases_are_unknown(self):
        self.mode = "none"
        for cmd in NO_SNAPSHOT_DENY:
            d = self.assertDeny(cmd, "G-UNKNOWN")
            self.assertIn("shell snapshot", d.message())

    def test_owner_json(self):
        st = self.env["S2V_STATE_DIR"]
        os.makedirs(os.path.join(st, "heavy.lock.d"), exist_ok=True)
        self.assertDeny("cat %s/heavy.lock.d/owner.json" % st, "G-OUT")
        self.assertDeny("cat studio/cast/a/character/.work/op.lock.d/owner.json", "G-OUT")
        del self.env["S2V_STATE_DIR"]
        os.makedirs(os.path.join(self.env["HOME"], ".s2v", "heavy.lock.d"), exist_ok=True)
        self.assertDeny("cat ~/.s2v/heavy.lock.d/owner.json", "G-OUT")

    def test_out_of_repo_files_everywhere(self):
        other = helpers.make_repo(self.tmp, name="plain", harness=False)
        ud = paths.user_dir(self.env)
        for cwd in (self.repo, other):
            self.assertDeny("rm -rf %s/studio-backup" % ud, "G-OUT", cwd=cwd)
            self.assertDeny("echo x > %s/studio-sandbox.json" % ud, "G-OUT", cwd=cwd)
            self.assertDeny("rm -rf %s/heavy.lock.d" % self.env["S2V_STATE_DIR"], "G-OUT", cwd=cwd)
            self.assertDeny("rm -rf %s" % self.env["S2V_STATE_DIR"], "G-OUT", cwd=cwd)
        st = self.env.pop("S2V_STATE_DIR")
        self.assertDeny("rm -rf ~/.s2v", "G-OUT", cwd=other)
        self.env["S2V_STATE_DIR"] = st

    def test_alias_alternative_message(self):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        for i, al in enumerate(([("g", "git")], [])):
            with open(os.path.join(d, "snapshot-zsh-%d-a.sh" % i), "w") as f:
                f.write(snapshot_text(aliases=al, path=self.env["PATH"]))
        self.snap_with = snapmod.load(self.env)
        dn = self.assertDeny("g add -f studio/local/x", "G-PROT")
        self.assertIn('alias "g" is "git" in 1 of 2 recent shell snapshots', dn.message())
        dn = self.assertDeny("g stash -a", "G-STASH")
        self.assertIn("recent shell snapshots", dn.message())


# fix20: MUST_PASS rows the 0.0.26 guard refused — refused again in 0.0.27 by the backstop; this guard alone still
# passes them (assertHeadRefusedKept). Per snapshot mode.
HEAD_REFUSED_KEPT = {
    "with": ["rm -rf **/__pycache__", "rm -f **/*.pyc", "rm -f */*.log", "rm studio/videos/v/out/*.mp4",
             "rm -rf studio<->", "X=studio; : ${X::=build}; rm -rf -- $X"],
    "none": ["flock /tmp/build.lock make", "flock /tmp make", "gnice -n 5 make", "gstdbuf -oL npm test",
             "gtime -p npm test", "setsid -f make", "taskpolicy -c utility make", "busybox ls", "toybox ls",
             "busybox.static ls", "rm -rf **/__pycache__", "rm -f **/*.pyc", "rm -f */*.log",
             "rm studio/videos/v/out/*.mp4", "function a b { echo hi }; a; b", "f(){ echo hi }; functions -c f k; k",
             "1=x; echo $1", "rm -rf studio<->", "X=studio; : ${X::=build}; rm -rf -- $X"],
}


class MustPass(JudgeCase):
    def must_pass(self, rows):
        for cmd in rows:
            if cmd in HEAD_REFUSED_KEPT[self.mode]:
                self.assertHeadRefusedKept(cmd)
            else:
                self.assertPass(cmd)

    def test_must_pass_with_snapshot(self):
        self.mode = "with"
        self.must_pass(MUST_PASS + WITH_SNAPSHOT_PASS)

    def test_must_pass_without_snapshot(self):
        self.mode = "none"
        self.must_pass(MUST_PASS)

    def test_head_refused_kept_rows_are_must_pass(self):
        for mode, rows in HEAD_REFUSED_KEPT.items():
            for cmd in rows:
                self.assertIn(cmd, MUST_PASS, cmd)

    def test_repo_without_harness(self):
        plain = helpers.make_repo(self.tmp, name="plain", harness=False)
        os.makedirs(os.path.join(plain, "studio", "local"))
        os.rename(os.path.join(plain, "studio", "local"), os.path.join(plain, "studio", "notlocal"))
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in MUST_PASS + ["rm -rf studio", "echo x > studio/videos/v/work/state.json"]:
                if mode == "none" and cmd in NO_SNAPSHOT_DENY:
                    continue
                self.assertPass(cmd, cwd=plain)
            # s2v in a repository without a harness or marker
            self.assertPass("s2v tts x.md", cwd=plain)
            self.assertPass("S2V_TTS_PORT=1 s2v tts x.md", cwd=plain)

    def test_same_state_dir_passes(self):
        self.assertPass("S2V_STATE_DIR=%s s2v x" % self.env["S2V_STATE_DIR"])
        self.assertPass("S2V_STATE_DIR=%s S2V_TTS=mock python3 x.py" % "/elsewhere")


class Plan00(JudgeCase):
    """00-plan §3.4 M0 tests (the 1b part)."""

    def untracked(self, rel):
        p = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")

    def test_git_clean_cases(self):
        self.untracked("studio/cast/b/character/face.png")
        self.untracked("src/tmp.o")
        self.assertDeny("git clean -fd", "G-CLEAN")
        self.assertDeny("git clean -fdx", "G-CLEAN")
        self.assertDeny("git clean -f -d -x", "G-CLEAN")
        self.assertPass("git clean -fd src/")
        self.assertPass("git clean -fdX src/")
        self.assertPass("git clean -n")

    def test_git_clean_whole_studio_untracked(self):
        repo2 = helpers.make_repo(self.tmp, name="r2", harness=True)
        self.untracked_in(repo2, "studio/videos/x/script.md")
        self.assertDeny("git clean -fd", "G-CLEAN", cwd=repo2)

    def untracked_in(self, repo, rel):
        p = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")

    def test_git_clean_hardening(self):
        self.untracked("src/tmp.o")
        self.assertDeny("git -c core.fsmonitor=/bin/true clean -fd src/", "G-CLEAN")
        self.assertDeny("git -c alias.x=clean clean -fd src/", "G-CLEAN")
        self.assertDeny("git --exec-path=/tmp clean -fd src/", "G-CLEAN")
        self.assertDeny("git -c core.hooksPath=/tmp clean -fd src/", "G-CLEAN")
        self.assertPass("git -c core.excludesFile=/dev/null clean -fd src/")

        class Slow(object):
            def __init__(s, *a, **k):
                pass

            def clean_preview(s, *a, **k):
                return None

            def studio_changes(s, *a, **k):
                return None

            def is_rev(s, *a, **k):
                return None
        d = self.bash("git clean -fd src/", probe=Slow())
        self.assertEqual(d.rule, "G-CLEAN")
        d = self.bash("git reset --hard", probe=Slow())
        self.assertEqual(d.rule, "G-RESET")

    def test_git_clean_requireforce_false(self):
        self.untracked("studio/videos/z/a.md")
        self.assertDeny("git -c clean.requireForce=false clean -d", "G-CLEAN")

    def test_reset_with_studio_changes(self):
        self.assertPass("git reset --hard")
        with open(os.path.join(self.repo, "studio", "videos", "v", "script.md"), "a") as f:
            f.write("more\n")
        self.assertDeny("git reset --hard", "G-RESET")
        self.assertDeny("git checkout -f", "G-RESET")
        self.assertDeny("git switch --discard-changes main", "G-RESET")
        self.assertDeny("git checkout -- .", "G-RESET")
        self.assertDeny("git restore -- studio", "G-RESET")

    def test_cd_then_relative(self):
        cwd = os.path.join(self.repo, "studio", "videos", "v")
        self.assertDeny("echo x > work/state.json", "G-PROT", cwd=cwd)
        self.assertDeny("cd studio/videos/v && echo x > work/state.json", "G-PROT")
        self.assertPass("( cd studio/videos/v; echo x > notes.md ); echo y > work/state.json")
        self.assertDeny("{ cd studio/videos/v; echo x > work/state.json; }", "G-PROT")

    def test_yarn_cwd(self):
        self.assertPass("yarn --cwd studio/videos/v build")

    def test_other_repo_session(self):
        other = helpers.make_repo(self.tmp, name="other", harness=False)
        self.assertDeny("cp a %s/studio/videos/v/work/state.json" % self.repo, "G-PROT", cwd=other)
        self.assertDeny("touch %s/studio/voices/new/deep/x.wav" % self.repo, "G-PROT", cwd=other)
        d = self.decide("Write", {"file_path": "%s/studio/cast/a/character/new/x.yaml" % self.repo,
                                  "content": "x"}, cwd=other)
        self.assertEqual(d.rule, "G-PROT")

    def test_outside_studio_interpreters_pass(self):
        self.assertPass("python3 -c 'print(1)'")
        self.assertPass("python3 - <<'EOF'\nimport json\nprint(json.dumps({}))\nEOF")

    def test_marker_only_branch(self):
        repo3 = helpers.make_repo(self.tmp, name="r3", harness=False, marker=True)
        os.makedirs(os.path.join(repo3, "studio", "local"))
        self.assertDeny("rm -rf studio/local", "G-DEL", cwd=repo3)
        self.assertDeny("git stash -a", "G-STASH", cwd=repo3)
        self.assertDeny("git add -f studio/local/x", "G-PROT", cwd=repo3)
        self.assertPass("rm -rf src", cwd=repo3)

    def test_guard_exception_denies(self):
        from stdo.guard.where import FS

        class Boom(FS):
            def realpath(s, p):
                raise KeyError("x")
        deny, ctx = judge.decide(self.hook("Bash", {"command": "rm -rf studio"}), self.env, fs=Boom(),
                                 snapshot_loader=self.loader)
        self.assertEqual(deny.rule, "G-ERR")


class FileTools(JudgeCase):
    def test_write_edit(self):
        D = lambda tool, ti: self.decide(tool, ti)
        self.assertEqual(D("Write", {"file_path": "studio/videos/v/work/state.json", "content": "{}"}).rule, "G-PROT")
        self.assertEqual(D("Write", {"file_path": ".claude/studio/charter.md", "content": "x"}).rule, "G-PROT")
        self.assertEqual(D("Write", {"file_path": "studio/cast/a/character/character.yaml", "content": "x"}).rule,
                         "G-PROT")
        self.assertIsNone(D("Write", {"file_path": "studio/cast/a/character/character.yaml.draft", "content": "x"}))
        self.assertEqual(D("Write", {"file_path": "studio/CREDITS.yaml", "content": "x"}).rule, "G-PROT")
        self.assertIsNone(D("Write", {"file_path": "studio/CREDITS.draft.yaml", "content": "x"}))
        self.assertIsNone(D("Write", {"file_path": "src/a.ts", "content": "x"}))
        self.assertIsNone(D("Write", {"file_path": "studio/videos/v/script.md", "content": "x"}))
        self.assertIsNone(D("Write", {"file_path": "studio/local/videos/w/notes.md", "content": "x"}))
        self.assertEqual(D("NotebookEdit", {"notebook_path": "studio/voices/a/x.ipynb"}).rule, "G-PROT")
        self.assertEqual(D("Edit", {"file_path": "studio/voices/a/x", "old_string": "a", "new_string": "b"}).rule,
                         "G-PROT")

    def test_config_keys(self):
        cfgp = os.path.join(self.repo, ".claude", "studio", "config.json")
        cfg = json.load(open(cfgp))
        new = dict(cfg, language="en")
        self.assertIsNone(self.decide("Write", {"file_path": cfgp, "content": json.dumps(new)}))
        new = dict(cfg, visibility={"default": "public"})
        self.assertEqual(self.decide("Write", {"file_path": cfgp, "content": json.dumps(new)}).rule, "G-PROT")
        text = open(cfgp).read()
        old_lang = '"language": "%s"' % cfg["language"]
        self.assertIsNone(self.decide("Edit", {"file_path": cfgp, "old_string": old_lang,
                                               "new_string": '"language": "en"'}))
        self.assertEqual(self.decide("Edit", {"file_path": cfgp, "old_string": '"allow_internal_commits": false',
                                              "new_string": '"allow_internal_commits": true'}).rule, "G-PROT")
        self.assertEqual(self.decide("Write", {"file_path": cfgp, "content": "not json"}).rule, "G-PROT")
        self.assertIsNone(self.decide("Edit", {"file_path": cfgp, "old_string": "nope-not-there", "new_string": "x"}))
        self.assertEqual(self.decide("MultiEdit", {"file_path": cfgp, "edits": [
            {"old_string": old_lang, "new_string": '"language": "en"'},
            {"old_string": '"gates": [', "new_string": '"gates": ["0", '}]}).rule, "G-PROT")
        del text

    def test_out_of_repo_write(self):
        ud = paths.user_dir(self.env)
        self.assertEqual(self.decide("Write", {"file_path": os.path.join(ud, "studio-sandbox.json"),
                                               "content": "{}"}).rule, "G-OUT")

    def test_mcp_tools(self):
        D = lambda ti: self.decide("mcp__fs__write_file", ti)
        self.assertEqual(D({"path": "studio/videos/v/work/state.json", "content": "x"}).rule, "G-PROT")
        self.assertEqual(D({"paths": ["src/a.ts", "studio/voices/a/b.wav"]}).rule, "G-PROT")
        self.assertEqual(D({"destination": "studio/cast/a/character/x"}).rule, "G-PROT")
        self.assertIsNone(D({"path": "src/a.ts"}))
        self.assertIsNone(D({"query": "studio/videos/v/work/state.json"}))
        self.assertIsNone(D({"path": "studio/local/videos/w/x.md"}))
        self.assertIsNone(self.decide("TodoWrite", {"todos": []}))


class Messages(JudgeCase):
    def test_ancestor_message(self):
        for cmd in ("rm -rf studio", "rm -rf .claude", "rm -rf ."):
            self.assertIn("ancestor of Studio's folders", self.bash(cmd).message(), cmd)

    def test_message_shape(self):
        d = self.bash("rm -rf studio/local")
        m = d.message()
        self.assertTrue(m.startswith("Studio guard [G-DEL]: "))
        self.assertIn("(INV9)", m)
        self.assertLessEqual(len(m), 1000)
        self.mode = "none"
        d = self.bash("g st")
        self.assertIn("(shell snapshot:", d.message())


class Review1b(JudgeCase):
    """Implementation review round 1 (M0d-1b): every repro, in temporary harness repositories with real git."""

    def test_xargs_parallel_inputs(self):  # MJ-1
        for cmd in ("echo studio/local | xargs rm -rf", "ls -d studio/local | xargs rm -rf",
                    "find studio -maxdepth 1 -name local | xargs rm -rf",
                    "printf '%s\\n' studio/local | xargs -I{} rm -rf {}",
                    "find . -path ./studio/local -prune -o -print0 | xargs -0 rm -f",
                    "echo studio/x | parallel rm {}"):
            self.assertDeny(cmd, "G-OPAQUE")
        for cmd in ("echo studio/local | xargs grep foo", "ls studio | xargs wc -l", "ls src | xargs rm -f",
                    "find src -name '*.o' | xargs rm -f"):
            self.assertPass(cmd)
        self.assertDeny("ls | xargs rm -f", "G-OPAQUE", cwd=os.path.join(self.repo, "studio"))

    def test_checkout_restore_pathspecs(self):  # MJ-2
        with open(os.path.join(self.repo, "studio", "videos", "v", "script.md"), "a") as f:
            f.write("changed\n")
        for cmd, rule in (("git checkout .", "G-RESET"), ("git restore .", "G-RESET"), ("git checkout studio", "G-RESET"),
                          ("git checkout -- studio/videos/v/script.md", "G-RESET"),
                          ("git checkout HEAD .claude/studio/config.json", "G-PROT"),
                          ("git checkout HEAD~0 .claude/studio/charter.md", "G-PROT"),
                          ("git checkout HEAD -- studio", "G-PROT"), ("git restore -s HEAD~0 studio", "G-PROT"),
                          ("git restore --source=HEAD .claude/studio/config.json", "G-PROT"),
                          ("git checkout :/", "G-RESET"), ("git restore -- '*'", "G-RESET"),
                          ("git rm -r --cached studio", "G-DEL"), ("git mv studio studio2", "G-DEL"),
                          ("git rm .claude/studio/config.json", "G-DEL"), ("git mv a.txt .claude/studio/charter.md", "G-PROT")):
            self.assertDeny(cmd, rule)
        for cmd in ("git checkout main", "git checkout -b feat/y", "git checkout src/a.ts", "git restore src/a.ts",
                    "git restore --staged studio/videos/v/script.md", "git rm src/x.ts", "git mv src/x.ts src/z.ts",
                    "git checkout -b feat/z main"):
            self.assertPass(cmd)

    def test_checkout_clean_studio_passes(self):  # MJ-2: nothing uncommitted under Studio
        self.assertPass("git checkout .")
        self.assertPass("git restore studio")

    def test_git_dir_and_work_tree(self):  # MJ-3
        other = helpers.make_repo(self.tmp, name="plain2", harness=False)
        with open(os.path.join(self.repo, "studio", "videos", "v", "script.md"), "a") as f:
            f.write("changed\n")
        gd = os.path.join(self.repo, ".git")
        self.assertDeny("git --git-dir=%s --work-tree=%s reset --hard" % (gd, self.repo), "G-RESET", cwd=other)
        self.assertDeny("GIT_DIR=%s GIT_WORK_TREE=%s git reset --hard" % (gd, self.repo), "G-RESET", cwd=other)
        self.assertDeny("git --git-dir=$X reset --hard", "G-RESET")
        self.assertDeny("GIT_DIR=$X git reset --hard", "G-RESET")
        self.assertDeny("git -C $X reset --hard", "G-RESET")
        self.assertDeny("GIT_CONFIG_COUNT=1 git clean -fd src/", "G-CLEAN")
        # the user's own GIT_DIR (inherited) points the command at the Studio repository
        self.env["GIT_DIR"] = gd
        self.env["GIT_WORK_TREE"] = self.repo
        self.assertDeny("git reset --hard", "G-RESET", cwd=other)
        del self.env["GIT_DIR"], self.env["GIT_WORK_TREE"]
        # a plain repository targeted explicitly is not judged
        self.assertPass("git --git-dir=%s/.git --work-tree=%s reset --hard" % (other, other))
        self.untracked = None
        p = os.path.join(self.repo, "studio", "cast", "z", "character", "f.png")
        os.makedirs(os.path.dirname(p))
        open(p, "w").close()
        self.assertDeny("git -C %s clean -fd" % self.repo, "G-CLEAN", cwd=other)
        self.assertDeny("git --git-dir=%s --work-tree=%s clean -fd" % (gd, self.repo), "G-CLEAN", cwd=other)

    def test_probe_env_cleared(self):  # MJ-3
        from stdo.guard.gitprobe import Probe
        pr = Probe(dict(self.env, GIT_DIR="/x", GIT_WORK_TREE="/y", GIT_INDEX_FILE="/z", GIT_CONFIG_COUNT="1",
                        GIT_CONFIG_KEY_0="core.fsmonitor", GIT_CONFIG_VALUE_0="/bin/sh"))
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
            self.assertNotIn(k, pr.env)

    def test_find_conditions(self):  # MINOR 1
        for cmd in ("find . -name '*.pyc' -delete", "find . -name __pycache__ -type d -exec rm -rf {} +",
                    "find src -name '*.o' -delete"):
            self.assertPass(cmd)
        for cmd in ("find . -name local -delete", "find . -name '*' -delete", "find . -delete",
                    "find . ! -name x -delete", "find . -path './studio/*' -delete", "find . -iname 'STATE.json' -delete",
                    "find . -regex '.*' -delete", "find studio -name x -delete", "find studio/voices -name '*.wav' -delete"):
            self.assertDeny(cmd, "G-DEL")

    def test_more_deleters(self):  # MINOR 2
        for cmd in ("rimraf studio/local", "npx rimraf studio/local", "pnpm dlx rimraf studio", "yarn dlx rimraf studio",
                    "bunx rimraf studio/voices", "del studio/local", "trash-put studio/local", "gio trash studio/local",
                    "zip -m out.zip studio/videos/v/work/state.json", "tar --remove-files -cf a.tar studio/local"):
            self.assertDeny(cmd, "G-DEL")
        for cmd in ("npx rimraf dist", "zip -m out.zip src/a.ts", "npx prettier --write src/a.ts"):
            self.assertPass(cmd)
        wt = os.path.join(self.tmp, "wt2")
        helpers.git(self.repo, "worktree", "add", "-q", wt)
        os.makedirs(os.path.join(wt, ".claude", "studio"), exist_ok=True)
        self.assertDeny("git worktree remove %s" % wt, "G-DEL")

    def test_ln_protected_source(self):  # MINOR 3
        self.assertDeny("ln -s studio/videos/v/work/state.json /tmp/s.json", "G-PROT")
        self.assertDeny("ln .claude/studio/charter.md x.md", "G-PROT")
        self.assertPass("ln -s studio/local/videos/w/notes.md n.md")
        self.assertPass("ln -s src/a.ts b.ts")

    def test_stash_clusters(self):  # MINOR 4
        for cmd in ("git stash -au", "git stash push -ua", "git stash save -a x", "git stash --all"):
            self.assertDeny(cmd, "G-STASH")
        self.assertPass("git stash -u")
        self.assertPass("git stash push -m 'a b'")

    def test_plugin_data_pycache(self):  # MINOR 5b
        pd = os.path.join(self.tmp, "pdata")
        self.env["CLAUDE_PLUGIN_DATA"] = pd
        self.assertDeny("rm -rf %s/pycache" % pd, "G-OUT")
        self.assertDeny("rm -rf %s" % pd, "G-OUT")
        self.assertPass("ls %s" % pd)

    def test_marker_only_detection(self):  # MINOR 6 (J5)
        from stdo.guard.repos import Repos, marker_key
        from stdo.guard.where import FS, Where
        r = helpers.make_repo(self.tmp, name="mk", harness=False, marker=False)
        m = os.path.join(paths.backup_root(self.env), marker_key(os.path.join(r, ".git")), "marker")
        os.makedirs(os.path.dirname(m))
        with open(m, "w") as f:
            json.dump({"studio_root": "media"}, f)
        w = Where(FS(), self.env)
        ri = Repos(w, self.env).info(w.git_repo(r))
        self.assertTrue(ri.studio and not ri.harness)
        self.assertEqual(ri.studio_root, "media")
        os.makedirs(os.path.join(r, "media", "local"))
        self.assertDeny("rm -rf media/local", "G-DEL", cwd=r)
        self.assertEqual(marker_key(os.path.join(r, ".git")), paths.common_key(r))

    def test_opaque_literal_hits_protected_path(self):  # MINOR 6 (J21)
        cwd = os.path.join(self.repo, "studio")
        d = self.assertDeny("python3 -c \"open('voices/a/x.wav','w')\"", "G-OPAQUE", cwd=cwd)
        self.assertIn("voices/a/x.wav", d.message())

    def test_unknown_payload_in_studio_cwd(self):  # MINOR 6 (J22)
        self.assertDeny('eval "$X"', "G-OPAQUE", cwd=os.path.join(self.repo, "studio", "videos"))
        self.assertDeny('eval "$X"', "G-OPAQUE")  # M1a X1: a non-literal eval anywhere in a Studio repository

    def test_studio_script_needs_harness(self):  # NIT
        fake = helpers.make_repo(self.tmp, name="noh", harness=False)
        os.makedirs(os.path.join(fake, ".claude", "studio", "scripts"))
        with open(os.path.join(fake, ".claude", "studio", "scripts", "state.py"), "w") as f:
            f.write("#\n")
        self.assertPass("python3 .claude/studio/scripts/state.py approve v 1", cwd=fake)
        self.assertDeny("python3 .claude/studio/scripts/state.py approve v 1", "G-APPROVAL")
        self.assertDeny("python3 %s/.claude/studio/scripts/state.py next v > studio/videos/v/work/state.json" % fake,
                        "G-PROT")

    def test_mcp_nested(self):  # NIT
        D = lambda ti: self.decide("mcp__x__op", ti)
        self.assertEqual(D({"args": {"options": {"path": "studio/videos/v/work/state.json"}}}).rule, "G-PROT")
        self.assertEqual(D({"ops": [{"destination": "studio/voices/a/x"}]}).rule, "G-PROT")
        self.assertIsNone(D({"a": {"b": {"c": {"d": {"e": {"f": {"path": "studio/voices/a/x"}}}}}}}))

    def test_clean_flag_stripping(self):  # NIT
        from stdo.guard.gitprobe import Probe
        calls = []

        class R(object):
            returncode, stdout = 0, ""

        def runner(argv, **k):
            calls.append(argv)
            return R()
        pr = Probe(self.env, runner=runner)
        pr.clean_preview(self.repo, [], ["-fdx", "-efoo", "-e", "fbar", "-fe", "x"])
        tail = calls[-1][calls[-1].index("-n") + 1:]
        self.assertEqual(tail, ["-dx", "-efoo", "-e", "fbar", "-e", "x"])

    def test_dynamic_git_targets_clean_repo(self):  # MJ-3: unknown targets deny even with nothing to lose here
        for cmd in ("GIT_DIR=$X git reset --hard", "GIT_WORK_TREE=$Y git checkout .", "git --work-tree=$Y clean -fd",
                    "git -C $X reset --hard"):
            self.assertIsNotNone(self.bash(cmd), cmd)
        other = helpers.make_repo(self.tmp, name="plain3", harness=False)
        self.assertPass("GIT_DIR=$X git reset --hard", cwd=other)  # no Studio repository involved

    def test_untrusted_script_copy_is_an_ordinary_command(self):  # NIT
        fake = helpers.make_repo(self.tmp, name="noh2", harness=False)
        os.makedirs(os.path.join(fake, ".claude", "studio", "scripts"))
        with open(os.path.join(fake, ".claude", "studio", "scripts", "state.py"), "w") as f:
            f.write("#\n")
        self.assertDeny("python3 %s/.claude/studio/scripts/state.py studio/videos/v/work/state.json" % fake, "G-PROT")
        self.assertPass("python3 .claude/studio/scripts/state.py next studio/videos/v/work/state.json")


class Review2b(JudgeCase):
    """Implementation review round 2 (M0d-1b)."""

    def dirty(self):
        with open(os.path.join(self.repo, "studio", "videos", "v", "script.md"), "a") as f:
            f.write("changed\n")

    def test_subdirectory_discards(self):  # MJ-1
        self.dirty()
        R = self.repo
        for cmd in ("cd studio && git checkout .", "cd studio && git checkout -- .", "cd studio/videos && git restore .",
                    "cd studio && git restore videos", "cd studio/videos/v && git checkout script.md",
                    "cd studio && git reset --hard", "cd src && git reset --hard", "git -C src reset --hard",
                    "git -C studio checkout .", "git -C studio/videos restore .", "cd src && git checkout -- ../studio",
                    "cd %s/src && git --git-dir=../.git --work-tree=.. reset --hard" % R):
            self.assertDeny(cmd, "G-RESET")
        for cmd in ("cd src && git checkout .", "git -C src restore .", "cd studio && git restore --staged ."):
            self.assertPass(cmd)

    def test_subdirectory_clean_tree_passes(self):  # MJ-1: no uncommitted Studio changes
        self.assertPass("cd studio && git checkout .")
        self.assertPass("cd src && git reset --hard")

    def test_patch_without_pathspec(self):  # NIT
        self.dirty()
        self.assertDeny("git checkout -p", "G-RESET")
        self.assertDeny("git restore --patch", "G-RESET")
        self.assertPass("git checkout -p src/a.ts")

    def write(self, name, text):
        p = os.path.join(self.repo, name)
        with open(p, "w") as f:
            f.write(text)
        return p

    def test_arguments_from_files(self):  # MINOR 1
        self.write("bad.txt", "studio/local\n")
        self.write("rel.txt", "voices/a\n")
        self.write("ok.txt", "dist\nnode_modules\n")
        for cmd in ("xargs -a bad.txt rm -rf", "xargs --arg-file=bad.txt rm -rf", "xargs rm -rf < bad.txt",
                    "cat bad.txt | xargs rm -rf", "while read f; do rm -rf \"$f\"; done < bad.txt",
                    "for f in $(cat bad.txt); do rm -rf $f; done", "rm -rf $(cat bad.txt)",
                    ):
            self.assertDeny(cmd, None)
        d = self.bash("cd studio && xargs -a ../rel.txt rm -rf")
        self.assertIsNotNone(d)
        # a line with no Studio term that resolves to a protected folder from the command's cwd
        self.write("studio/videos/list.txt", "v/audio\n")
        cwd = os.path.join(self.repo, "studio", "videos")
        d = self.bash("while read f; do rm -rf \"$f\"; done < list.txt", cwd=cwd)
        self.assertIsNotNone(d)
        self.assertIn("protected Studio path", d.message())
        for cmd in ("xargs -a ok.txt rm -rf", "cat ok.txt | xargs rm -rf", "while read f; do rm -rf \"$f\"; done < ok.txt",
                    "rm -rf $(cat ok.txt)", "xargs -a bad.txt grep foo", "while read f; do echo \"$f\"; done < bad.txt",
                    # a missing file is not a reason: the command fails by itself (review round 3)
                    "xargs -a missing.txt rm -rf", "while read f; do mv \"$f\" /tmp; done < missing.txt"):
            self.assertPass(cmd)

    def test_parallel_arguments(self):  # MINOR 2
        self.write("bad.txt", "studio/local\n")
        self.write("ok.txt", "dist\n")
        self.assertDeny("parallel rm -rf ::: studio/local", "G-DEL")
        self.assertDeny("parallel cp a.txt ::: studio/videos/v/work/state.json", "G-PROT")
        self.assertDeny("parallel rm -rf :::: bad.txt", "G-OPAQUE")
        self.assertPass("parallel rm -rf ::: dist node_modules")
        self.assertPass("parallel rm -rf :::: ok.txt")
        self.assertPass("parallel grep foo ::: studio/videos/v/script.md")


class Review3b(JudgeCase):
    """Implementation review round 3 (M0d-1b): file-fed judgement only for real inputs of path writers."""

    def write(self, name, text, mode="w"):
        p = os.path.join(self.repo, name)
        with open(p, mode) as f:
            f.write(text)
        return p

    def test_must_pass(self):
        self.write("msg.txt", "fix: studio/local handling in studio/videos\n")
        self.write("body.md", "touches .claude/studio/config.json and studio/voices\n")
        self.write("README.md", "studio/local is ignored\n")
        self.write("build.json", '{"files": ["dist/a.js", "dist/b.js"]}\n')
        for cmd in ('git commit -m "$(cat msg.txt)"', 'gh pr create --title x --body "$(cat body.md)"',
                    'node scripts/x.js "$V" < README.md', 'python3 scripts/x.py --out "$OUT" < README.md',
                    "git branch --merged | grep -v main | xargs git branch -d",
                    "jq -r .files[] build.json | xargs rm -f", "grep -l studio src/*.ts | xargs rm -f",
                    "sed -n 's/studio/x/p' README.md | xargs rm -f"):
            self.assertPass(cmd)
        self.write("bad.txt", "studio/local\n")
        # non-writing programs are not judged by their input, even when it lists protected paths
        self.write("plist.txt", "studio/videos/v/work/state.json\nstudio/local\n")
        for cmd in ('node scripts/x.js "$V" < plist.txt', 'git commit -F plist.txt -m "$(cat plist.txt)"',
                    'python3 scripts/x.py --out "$OUT" < plist.txt'):
            self.assertPass(cmd)
        # input that feeds another command does not feed this one
        for cmd in ('echo $(cat bad.txt); rm -rf "$X"', 'wc -l < bad.txt; rm -rf "$X"',
                    'cat bad.txt | wc -l; ls | xargs rm -f'):
            self.assertPass(cmd)

    def test_round2_cases_still_deny(self):
        self.write("bad.txt", "studio/local\n")
        self.write("bad2.txt", "studio/videos/v/work/state.json\n")
        for cmd in ("xargs -a bad.txt rm -rf", "xargs --arg-file=bad.txt rm -rf", "xargs rm -rf < bad.txt",
                    "cat bad.txt | xargs rm -rf", "while read f; do rm -rf \"$f\"; done < bad.txt",
                    "for f in $(cat bad.txt); do rm -rf $f; done", "rm -rf $(cat bad.txt)",
                    "parallel rm -rf :::: bad.txt", "grep -h . bad.txt | xargs rm -rf",
                    "jq -r . bad.txt | xargs rm -rf", "cp a.txt $(cat bad2.txt)"):
            self.assertIsNotNone(self.bash(cmd), cmd)

    def test_binary_and_unreadable(self):
        self.write("bin.dat", b"studio/local\x00\x01\n\x00\n".decode("latin-1"))
        d = self.bash("xargs -a bin.dat rm -rf")
        self.assertTrue(d is None or d.rule != "G-ERR")
        p = self.write("locked.txt", "studio/local\n")
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o644)
        if os.geteuid() != 0:
            self.assertEqual(self.bash("xargs -a locked.txt rm -rf").rule, "G-OPAQUE")


# decoy paths that do not exist (review 3 B1): each costs file-system checks before the repository is reached
DECOYS = " ".join("/nx/zz%d/a/b/c/d/e/f" % i for i in range(260))
DECOYS2 = " ".join("/nx/q0/q1/q2/x%d" % i for i in range(400))
# G1 §5 NESTED_OUT_DENY: from a folder outside the repository, which is named by an absolute path (<R>); a tuple of
# rules: either deny (which one comes first depends on whether the string is read; both refuse)
NESTED_OUT_DENY = [
    # review 10 B1/M2: `$PWD` after a trap or a folder change the guard cannot follow; popd when the snapshot does not
    # turn AUTO_PUSHD on (a snapshot without it: G1Review10)
    ("cd <R>; trap 'cd /' EXIT; rm -rf $PWD/studio", ("G-DEL",)), ("cd <R>; cd $X > out.log; rm -rf ~+/studio", ("G-DEL",)),
    ("while cd <R>; do break; done; cd <R> > /nonexistent/x; rm -rf $PWD/studio", ("G-DEL",)),
    ("pushd <R> / || cd <R>; rm -rf $(pwd)/studio", ("G-DEL",)),
    ("X=<R>/studio; f(){ local X=a }; f; rm -rf -- $X", ("G-DEL",)),
    ("sh <<< 'rm -rf <R>/studio' <> /dev/null", ("G-DEL",)), ("true && HOME=<R>; rm -rf ~/studio", ("G-DEL",)),
    ("[[ -e x ]] || HOME=<R>; X=~/studio; rm -rf $X", ("G-DEL",)),
    ("f(){ rm -rf -- $X }; X=safe; f; { X=<R>/studio } > out.log; f", ("G-DEL",)),
    ("set -y; X='a <R>/studio'; rm -rf $X", ("G-DEL",)), ("f(){ cd <R> }; cd /tmp; f; rm -rf studio", ("G-DEL",)),
    # review 9 B1/B2/B3: a folder change that may fail, `$'…'` in a case pattern, several inputs, values not carried
    ("cd <R> &> /tmp/cd.log; git clean -fdx", ("G-CLEAN",)), ("cd <R> > /tmp/cd.log; git config --unset core.hooksPath",
                                                               ("G-HOOKOFF",)),
    ("pushd <R> > out.log; git rm -rf studio", ("G-DEL",)), ("cd <R> > out.log; rm -rf $PWD/studio", ("G-DEL",)),
    ("cd <R>; [[ -e x ]] && cd studio; git clean -fdx", ("G-CLEAN",)),
    ("true > out.log && cd <R>; cd /tmp; rm -rf ~-/studio", ("G-DEL",)), ("unsetopt autopushd; cd <R>; popd; rm -rf studio", ("G-DEL",)),
    ("eval cd <R>\\; rm -rf studio; case x in ($'\\'') ;; esac", ("G-DEL",)),
    ("cd <R>; sh <<< 'rm -rf studio' <<< x", ("G-DEL",)), ("X=(<R>/studio); rm -rf $X", ("G-DEL",)),
    ("X=$(print <R>/studio); rm -rf $X", ("G-DEL",)), ("f(){ X=(<R>/studio) }; f; rm -rf $X", ("G-DEL",)),
    # review 8 B1, B2, M1, M2: numeric globs, failing redirections, case fall-through, HOME for eval / `-c` / functions
    ("rm -rf <R>/studi[o<->]", ("G-DEL",)), ("cd <R>; rm -rf studi[o<->]", ("G-DEL",)),
    ("rm -rf <R>/.claude/studio/scrip[t<->]s", ("G-DEL",)), ("true > /nonexistent/x || rm -rf <R>/studio", ("G-DEL",)),
    ("pushd > /nonexistent/x || rm -rf <R>/studio", ("G-DEL",)), ("cd <R>; cd /tmp > /nonexistent/x; rm -rf studio", ("G-DEL",)),
    ("case x in (x) print;| esac; cd <R>; /bin/rm -rf s*", ("G-DEL",)),
    ("case x in (x) cd <R>;& (y) rm -rf studio;; esac", ("G-DEL",)), ("case x in (x) cd <R>;| (y) rm -rf studio;; esac", ("G-DEL",)),
    ("setopt globstarshort; rm -rf <R>/**local", ("G-DEL",)),
    ("HOME=<R> eval 'rm -rf ~/studio'", ("G-DEL",)), ("HOME=<R> zsh -fc 'rm -rf ~/studio'", ("G-DEL",)),
    ("HOME=<R> sh -c 'rm -rf ~/studio'", ("G-DEL",)), ("env HOME=<R> zsh -fc 'rm -rf ~/studio'", ("G-DEL",)),
    ("eval 'HOME=<R>'; rm -rf ~/studio", ("G-DEL",)), ("HOME=<R>; eval 'rm -rf ~/studio'", ("G-DEL",)),
    ("export HOME=<R>; sh -c 'rm -rf ~/studio'", ("G-DEL",)), ("HOME=<R> eval 'eval \"rm -rf ~/studio\"'", ("G-DEL",)),
    ("HOME=<R> eval 'cd ~; rm -rf studio'", ("G-DEL",)), ("HOME=<R> zsh -fc 'cd; rm -rf studio'", ("G-DEL",)),
    ("HOME=<R> builtin eval 'rm -rf ~/studio'", ("G-DEL",)), ("HOME=<R> nohup sh -c 'rm -rf ~/studio'", ("G-DEL",)),
    ("X=<R>; HOME=$X eval 'rm -rf ~/studio'", ("G-DEL",)), ("eval 'HOME=<R>'; cd ~; rm -rf studio", ("G-DEL",)),
    ("f(){ rm -rf ~/studio; }; HOME=<R> f", ("G-DEL",)), ("f(){ rm -rf ~/studio; }; HOME=<R>; f", ("G-DEL",)),
    ("f(){ cd ~; rm -rf studio; }; HOME=<R> f", ("G-DEL",)), ("f(){ rm -rf studio; }; cd <R>; f", ("G-DEL",)),
    ("f(){ rm -rf $X; }; X=<R>/studio; f", ("G-DEL",)),
    # review 7 M5: $HOME written by the command, then a `~` word of any command
    ("read HOME <<< <R>; rm -rf ~/studio", ("G-DEL",)), ("print -v HOME <R>; rm -rf ~/studio", ("G-DEL",)),
    ("printf -v HOME %s <R>; rm -rf ~/.claude/studio", ("G-DEL",)),
    ("X=<R>; : ${HOME::=$X}; cd; rm -rf studio", ("G-DEL",)), ("X=<R>; read HOME <<< $X; rm -rf ~/studio", ("G-DEL",)),
    ("X=<R>; print -v HOME $X; rm -rf ~/studio", ("G-DEL",)), ("read HOME <<< <R>; cp /tmp/x ~/studio/config.json", ("G-PROT",)),
    ("Y=$(print <R>); HOME=$Y; rm -rf ~/studio", ("G-DEL",)),
    # review 7 M4, B1: input into eval / `-c` strings; brackets
    ("eval sh <<< 'rm -rf <R>/studio'", ("G-DEL",)), ("zsh -c sh <<< 'rm -rf <R>/studio'", ("G-DEL",)),
    ("eval 'f(){ sh }'; f <<< 'rm -rf <R>/studio'", ("G-DEL",)),
    ("setopt extendedglob; rm -rf <R>/[s~]tudio", ("G-DEL",)), ("rm -rf <R>/[s/]tudio", ("G-DEL",)),
    ("nohup sh -c 'rm -rf <R>/studio'", ("G-DEL",)), ("env bash -c 'cd <R> && mv studio/local /tmp/x'", ("G-DEL",)),
    ("bash -c 'cd <R> && python3 .claude/studio/scripts/state.py approve v 1 --expect abc'",
     ("G-APPROVAL", "G-OPAQUE")),
    ("bash -c 'cd <R> && python3 -c \"open(\\\"studio/videos/v/work/state.json\\\",\\\"w\\\")\"'", ("G-OPAQUE",)),
    ("/usr/bin/time -o <R>/studio/videos/v/work/state.json ls", ("G-PROT",)),
    # M4: literal parts of strings and words the guard cannot read
    ("su -c 'rm -rf <R>/studio'", ("G-DEL", "G-OPAQUE")), ("su root -c 'rm -rf <R>/studio'", ("G-DEL", "G-OPAQUE")),
    ("chroot / rm -rf <R>/studio", ("G-DEL", "G-OPAQUE")), ("sh -c \"rm -rf <R>/studio$UNSET\"", ("G-DEL", "G-OPAQUE")),
    ("X=; sh -c \"rm -rf <R>/studio$X\"", ("G-DEL",)), ("eval \"rm -rf <R>/stu\"dio", ("G-DEL",)),
    ("eval \"rm -rf <R>/studio$UNSET\"", ("G-DEL", "G-OPAQUE")),
    ("sh -c \"cd <R> && rm -rf studio $UNSET\"", ("G-DEL", "G-OPAQUE")),
    ("csh -c 'rm -rf <R>/studio'", ("G-DEL", "G-OPAQUE")),
    # review 2 D: the empty reading
    ("sh -c \"cd <R>; rm -rf stu${UNSET}dio\"", ("G-OPAQUE",)),
    ("sh -c \"cd $PWD/studio-repo; rm -rf $UNSET\"", ("G-OPAQUE",)),
    # review 3 M5: dynamic folder words at the top level
    ("cd <R>/$(printf studio) && rm -rf local", ("G-DEL", "G-OPAQUE")), ("cd <R>$UNSET && rm -rf studio", ("G-DEL", "G-OPAQUE")),
    # §2: a wildcard whose folder part is (or lies above) the repository
    ("touch <R>/.claude/*/config.json", ("G-PROT",)), ("touch <R>/*/studio/config.json", ("G-PROT",)),
    ("touch <R>/../*/.claude/studio/config.json", ("G-PROT",)),
    # §1.8: an unparsable zsh form naming the repository (the term split by quoting still hits)
    ("repeat 1 rm -rf <R>/stu''dio", ("G-UNPARSE",)),
    # G1 implementation review 1: M3 (a run folder named by a word the guard cannot read), m1 (here-strings and
    # here-documents into a shell are scanned), m2 (a root shell's words are searched)
    ("env -C <R>$U rm -rf studio", ("G-DEL", "G-OPAQUE")),
    ("nohup sh <<< 'cd <R>; rm -rf studio'", ("G-DEL",)), ("sh <<< 'rm -rf <R>/studio'", ("G-DEL",)),
    ("env sh <<'EOF'\nrm -rf <R>/studio\nEOF", ("G-DEL",)), ("sh <<< \"rm -rf <R>/studio$UNSET\"", ("G-DEL", "G-OPAQUE")),
    ("sudo -s 'rm -rf <R>/studio'", ("G-OPAQUE",)), ("sudo -i 'rm -rf <R>/studio'", ("G-OPAQUE",)),
    # G1 implementation review 2: B-1, B-2, M5, M12; m-a (the command lines in §1.9 options and variables are
    # searched for Studio repositories); m-b (a shell reading its commands from stdin)
    ("cd <R>/$U && rm -rf .", ("G-DEL", "G-OPAQUE")), ("cp /tmp/state.json <R>/studio/videos/?/work/", ("G-PROT",)),
    ("nohup cp -r /tmp/x/. <R>/s*/videos/v/work", ("G-PROT",)),
    ("git -C <R> clone -qc core.hooksPath=/tmp/h /tmp/r sub", ("G-OPAQUE",)),
    ("cd <R>/stu?io && rm -rf local", ("G-DEL",)),
    ("rsync -e 'rm -rf <R>/studio' a h:b", ("G-OPAQUE",)),
    ("tar -cf /tmp/x.tar --use-compress-program='rm -rf <R>/studio' a", ("G-OPAQUE",)),
    ("sort --compress-program='rm -rf <R>/studio' a", ("G-OPAQUE",)), ("make SHELL='rm -rf <R>/studio' x", ("G-OPAQUE",)),
    ("zip -TT 'rm -rf <R>/studio' x.zip a", ("G-OPAQUE",)), ("ssh -o ProxyCommand='rm -rf <R>/studio' h", ("G-OPAQUE",)),
    ("GIT_SSH_COMMAND='rm -rf <R>/studio' git fetch", ("G-OPAQUE",)),
    ("LESSOPEN='|rm -rf <R>/studio' less a", ("G-OPAQUE",)), ("EDITOR='rm -rf <R>/studio #' crontab -e", ("G-OPAQUE",)),
    ("git -c core.pager='rm -rf <R>/studio #' log", ("G-OPAQUE",)),
    ("git rebase -x 'rm -rf <R>/studio' HEAD~1", ("G-OPAQUE",)),
    ("X='$(rm -rf <R>/studio)'; echo ${(e)X}", ("G-OPAQUE",)),
    ("sh /dev/stdin <<< 'rm -rf <R>/studio'", ("G-DEL",)), ("bash /dev/fd/0 <<< 'rm -rf <R>/studio'", ("G-DEL",)),
    ("sudo -E -s <<< 'rm -rf <R>/studio'", ("G-OPAQUE",)),
    # G1 implementation review 3: B1/B-1, M3 (decoy paths use up the guard's limits before <R>: refused whatever the
    # context), m5 (the README's tail rule)
    ("rm -rf %s <R>/studio" % DECOYS, ("G-LIMIT", "G-DEL")), ("ls %s; rm -rf <R>/studio" % DECOYS, ("G-LIMIT", "G-DEL")),
    ("ls %s; mv <R>/studio/local /tmp/x" % DECOYS, ("G-LIMIT", "G-DEL")),
    ("cat %s; cd <R> && rm -rf studio" % DECOYS, ("G-LIMIT", "G-DEL")),
    ("ls %s; cd <R>; git stash -a" % DECOYS, ("G-LIMIT", "G-RESET", "G-STASH")),
    ("ls %s; cp /tmp/x <R>/studio/videos/v/work/state.json" % DECOYS, ("G-LIMIT", "G-PROT")),
    ("ls %s; echo x > <R>/studio/videos/v/work/state.json" % DECOYS, ("G-LIMIT", "G-PROT")),
    ("ls %s; touch <R>/.claude/studio/config.json" % DECOYS, ("G-LIMIT", "G-PROT")),
    ("true %s; rm -rf <R>/studio" % DECOYS, ("G-LIMIT", "G-DEL")), ("echo %s; rm -rf <R>/studio" % DECOYS, ("G-LIMIT", "G-DEL")),
    ("sh -c 'rm -rf %s <R>/studio'" % DECOYS2, ("G-LIMIT", "G-DEL")),
    ("su -c \"ls %s; rm -rf <R>/studio\"" % DECOYS, ("G-LIMIT", "G-DEL", "G-OPAQUE")),
    ("ls %s; cd <R>$UNSET; rm -rf studio" % DECOYS, ("G-LIMIT", "G-DEL", "G-OPAQUE")),
    ("sh -c \"ls %s; rm -rf <R>/studio$UNSET\"" % DECOYS, ("G-LIMIT", "G-DEL", "G-OPAQUE")),
    ("eval \"ls %s; rm -rf <R>/studio$UNSET\"" % DECOYS, ("G-LIMIT", "G-DEL", "G-OPAQUE")),
    # G1 implementation review 4: B2 (BARE_GLOB_QUAL off), R1 (hooks), R2 (pushd), R3 (while), R4 (NULLCMD),
    # functions[NAME]= text
    ("rm -rf <R>/studio/video(s)", ("G-UNPARSE",)),
    ("unsetopt bareglobqual; rm -rf <R>/studio/video(s)", ("G-UNPARSE",)),
    ("unsetopt bareglobqual; rm -rf <R>/studi(o)", ("G-UNPARSE",)),
    ("cd <R>; unsetopt bareglobqual; rm -rf studio/video(s)", ("G-UNPARSE",)),
    ("chpwd(){ builtin cd -q <R>/studio; }; cd /tmp; rm -rf local", ("G-DEL",)),
    ("chpwd_functions=(x); x(){ builtin cd -q <R>/studio; }; cd /tmp; rm -rf local", ("G-DEL",)),
    ("TRAPDEBUG(){ builtin cd -q <R>/studio 2>/dev/null; }; rm -rf local", ("G-DEL",)),
    ("TRAPZERR(){ cd <R>/studio; }; false; rm -rf local", ("G-DEL",)), ("TRAPEXIT(){ rm -rf <R>/studio; }", ("G-DEL",)),
    ("TRAPEXIT(){ cd <R>/studio; rm -rf local; }", ("G-DEL",)),
    ("pushd -P <R>; rm -rf studio", ("G-DEL",)), ("pushd -- <R>/studio; rm -rf local", ("G-DEL",)),
    ("pushd -P <R> && git stash -a", ("G-STASH", "G-RESET")),
    ("while cd <R>; do break; done; rm -rf studio", ("G-DEL",)),
    ("until cd <R>; do :; done; rm -rf studio", ("G-DEL",)),
    ("while cd <R>; do break; done\nrm -rf studio", ("G-DEL",)),
    ("while cd <R>; do break; done; git stash -a", ("G-RESET",)),
    ("NULLCMD=sh; > /dev/null <<< 'rm -rf <R>/stu''dio'", ("G-DEL",)),
    ("NULLCMD=sh; > /dev/null <<< 'rm -rf <R>/studio'", ("G-DEL",)),
    ("functions[show]='cd <R>'; show; rm -rf studio", ("G-DEL", "G-OPAQUE")),
    # G1 implementation review 5: a known qualifier value's text (M1), M3, M4, M5, pushd to $HOME, R1
    ("setopt extendedglob; Z='<R>/a.txt(#qe:rm -rf <R>/studio:)'; ls -d ${~Z}", ("G-OPAQUE",)),
    ("setopt extendedglob; Z='<R>/a.txt(#qe:rm -rf <R>/stu\"\"dio:)'; ls -d $~Z", ("G-OPAQUE",)),
    ("setopt globsubst; Z='<R>/a.txt(#qe:rm -rf <R>/studio:)'; ls -d $Z", ("G-OPAQUE",)),
    ("setopt globsubst extendedglob; Z=('<R>/a.txt(#qe:rm -rf <R>/stu\"\"dio:)'); ls -d $Z[1]", ("G-OPAQUE",)),
    ("setopt globsubst extendedglob; Z='<R>/a.txt(#qe:rm -rf <R>/stu\"\"dio:)'; typeset -a W=($Z)", ("G-OPAQUE",)),
    ("NULLCMD=sh; print 'rm -rf <R>/stu''dio' | > /dev/null", ("G-DEL",)),
    ("function x y { cd <R> }; y; rm -rf studio", ("G-DEL",)),
    ("function x chpwd { builtin cd -q <R> }; cd .; rm -rf studio", ("G-DEL",)),
    ("HOME=<R>; pushd; rm -rf studio", ("G-DEL",)), ("HOME=<R>; pushd -q; rm -rf studio", ("G-DEL",)),
    ("{ HOME=<R> }; cd; rm -rf studio", ("G-DEL",)), ("dirs <R>; pushd; rm -rf studio", ("G-DEL",)),
    # review 6 M11: HOME written by any route before cd, pushd or `~`
    (": ${HOME::=<R>}; cd; rm -rf studio", ("G-DEL",)), (": ${HOME:=<R>}; cd; rm -rf studio", ("G-DEL",)),
    ("unset HOME; : ${HOME:=<R>}; cd; rm -rf studio", ("G-DEL",)), (": ${HOME::=<R>}; cd ~; rm -rf studio", ("G-DEL",)),
    (": ${HOME::=<R>}; rm -rf ~/studio", ("G-DEL",)), (": ${HOME::=<R>}; pushd; rm -rf studio", ("G-DEL",)),
    ("for HOME in <R>; do cd; done; rm -rf studio", ("G-DEL",)),
    ("for HOME in <R> /tmp; do :; done; cd; rm -rf studio", ("G-DEL",)),
    ("f(){ : ${HOME::=<R>} }; f; cd; rm -rf studio", ("G-DEL",)), ("print -v HOME <R>; cd; rm -rf studio", ("G-DEL",)),
    ("typeset HOME=<R>; cd; rm -rf studio", ("G-DEL",)),
]
NESTED_OUT_PASS = ["bash -c 'echo hi'", "sh -c 'cd /tmp && ls'", "nohup sh -c 'ls'", "env bash -c 'git status'",
                   "sh -c \"ls $UNSET\"", "su -c 'ls /tmp'", "touch <R>/../*/src/a.ts", "git $UNSET stash -a",
                   "hash ls=/bin/rm; ls", "git clone https://example.invalid/r.git /tmp/r", "sh <<< 'ls'",
                   "sudo -s 'ls /tmp'", "sh /dev/stdin <<< 'ls'", "sudo -E -s <<< 'ls /tmp'", "rsync -e ssh a h:b",
                   "GIT_SSH_COMMAND='ssh -i /tmp/k' git fetch"]


class G1Runners(JudgeCase):
    """guard-runners-plan §1.1–§1.7a, §1.10 (part A)."""

    def test_nested_from_outside(self):
        out = self.tmp  # the repository's parent folder: not a git repository
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, rules in NESTED_OUT_DENY:
                text = cmd.replace("<R>", self.repo)
                d = self.bash(text, cwd=out)
                self.assertIsNotNone(d, "should deny: %s (%s)" % (cmd, mode))
                self.assertIn(d.rule, rules, "%s (%s): %s" % (cmd, mode, d.message()))
            for cmd in NESTED_OUT_PASS:
                self.assertPass(cmd.replace("<R>", self.repo), cwd=out)

    def test_empty_reading_home(self):
        home = self.env["HOME"]
        self.env["HOME"] = self.tmp
        try:
            d = self.bash("sh -c \"cd ~/studio-repo && rm -rf $UNSET\"", cwd=os.path.join(home))
            self.assertIsNotNone(d)
            self.assertEqual(d.rule, "G-OPAQUE")
        finally:
            self.env["HOME"] = home

    def test_posix_builtins_maybe(self):
        # two recent snapshots disagree on POSIX_BUILTINS: each `command cd` keeps both folders, the set overflows
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        for i, opts in enumerate((("autocd", "posixbuiltins"), ("autocd",))):
            with open(os.path.join(d, "snapshot-zsh-%d-a.sh" % i), "w") as f:
                f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"], options=opts))
        self.snap_with = snapmod.load(self.env)
        shutil.rmtree(d)
        self.assertIn("posixbuiltins", self.snap_with[0].option_conflicts)
        self.assertDeny("command cd a; command cd b; command cd c; command cd studio; rm -rf local", "G-DEL")
        self.assertDeny("command cd studio && rm -rf local", "G-DEL")
        self.assertDeny("command cd /tmp && rm -rf studio", "G-DEL")
        self.assertPass("command cd src && rm -rf node_modules")

    def test_user_function_cd(self):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"],
                                  functions='mkcd () {\n\tmkdir -p "$1" && cd "$1"\n}\n'))
        self.snap_with = snapmod.load(self.env)
        shutil.rmtree(d)
        self.assertPass("mkcd build && touch a.txt")
        self.assertDeny("mkcd build && rm -rf local", "G-DEL")

    def test_unknown_folder_messages(self):
        d = self.assertDeny("cd $X; rm -rf local", "G-DEL")
        self.assertIn("a folder the guard cannot tell", d.message())
        d = self.assertDeny("cd $X; touch studio/videos/v/work/state.json", "G-PROT")
        self.assertIn("a folder the guard cannot tell", d.message())
        self.assertPass("cd $X; touch local/a.txt")  # local/ is the agent's own folder

    def test_wrapper_files_from_outside(self):
        self.assertDeny("cd %s && /usr/bin/time -o studio/videos/v/work/state.json ls" % self.repo, "G-PROT",
                        cwd=self.tmp)
        self.assertDeny("env -C %s /usr/bin/time -o studio/videos/v/work/state.json ls" % self.repo, "G-PROT",
                        cwd=self.tmp)
        self.assertPass("/usr/bin/time -o /tmp/t.txt ls", cwd=self.tmp)

    def test_refused_only_in_studio(self):
        plain = helpers.make_repo(self.tmp, name="plain", harness=False)
        for cmd in ("su -c 'rm -rf x'", "chroot / ls", "nohup -x ls", "watchexec -- rm -rf studio", "BUILTIN ls"):
            self.assertPass(cmd, cwd=plain)
            self.assertIsNotNone(self.bash(cmd), cmd)

    def test_nested_performance(self):
        """m2: nested `bash -c` 3 deep, 10/20/40 wide, and eval brace amplification decide in under 2 s of CPU (or end
        in G-LIMIT in the repository)."""
        import time
        inner = "ls"
        for _ in range(3):
            inner = "bash -c %s" % shlex.quote(inner)
        cases = ["; ".join([inner] * width) for width in (10, 20, 40)]
        cases += ["eval 'bash -c \"bash -c ls\"'{1..50}", "eval 'bash -c \"bash -c \\\"bash -c ls\\\"\"'{1..50}"]
        for cmd in cases:
            for cwd in (self.tmp, self.repo):
                t = time.process_time()
                d = self.bash(cmd, cwd=cwd)
                self.assertLess(time.process_time() - t, 2.0, cmd)
                self.assertTrue(d is None or d.rule in ("G-LIMIT", "G-OPAQUE"), d and d.message())


class G1Values(JudgeCase):
    """guard-runners-plan §1.8, §1.9, §1.11, §2, §3, §4 (part B)."""

    def test_globstar_by_listing(self):
        # zsh runs a `**` glob with its existing matches only (NOMATCH): they are judged as literal paths
        self.assertHeadRefusedKept("rm -rf **/__pycache__", "G-DEL")  # fix20: the 0.0.26 guard refuses it
        os.makedirs(os.path.join(self.repo, "studio", "voices", "__pycache__"))
        self.assertDeny("rm -rf **/__pycache__", "G-DEL")
        self.assertIsNotNone(self.g1("rm -rf **/__pycache__"))
        self.assertPass("rm -rf src/**/__pycache__")
        # the static rule: after a command that may write, with NOMATCH off, or with `***/` (follows links)
        self.assertDeny("touch a.txt; rm -f **/*.pyc", "G-DEL")
        self.assertDeny("setopt nonomatch; rm -f **/*.pyc", "G-DEL")
        self.assertDeny("setopt globdots; rm -f **/*.pyc", "G-DEL")
        self.assertDeny("rm -f ***/*.pyc", "G-DEL")

    def test_glob_outside_every_repository(self):
        out = os.path.join(self.tmp, "o")
        os.makedirs(os.path.join(out, "a", "b"))
        self.assertPass("touch %s/*/b/x.txt" % out, cwd=self.tmp)
        self.assertPass("touch %s/../*/src/a.ts" % self.repo, cwd=self.tmp)
        d = self.assertDeny("touch %s/../*/studio/videos/v/work/state.json" % self.repo, "G-PROT", cwd=self.tmp)
        self.assertIn("may match", d.message())
        # a `**` above a Studio repository naming a protected name: write the folder names
        self.assertDeny("touch %s/**/state.json" % self.tmp, "G-LIMIT", cwd=self.tmp)

    def test_user_config_files(self):
        home = self.env["HOME"]
        self.assertDeny("echo x >> ~/.gitconfig", "G-HOOKOFF")
        self.assertDeny("cp a.txt %s/.config/git/config" % home, "G-HOOKOFF")
        d = self.decide("Write", {"file_path": os.path.join(home, ".ssh", "config"), "content": "Host *\n"})
        self.assertEqual(d.rule, "G-HOOKOFF")
        self.assertIsNone(self.decide("Write", {"file_path": os.path.join(home, ".gitconfig"), "content": "x"},
                                      cwd=self.tmp))
        self.assertPass("cat ~/.gitconfig")
        # a linked worktree's own settings
        os.makedirs(os.path.join(self.repo, ".git", "worktrees", "w"))
        self.assertDeny("echo x > .git/worktrees/w/config.worktree", "G-HOOKOFF")

    def test_refused_only_in_studio(self):
        plain = helpers.make_repo(self.tmp, name="plain2", harness=False)
        for cmd in ("hash ls=/bin/rm; ls", "commands[ls]=/bin/rm", "ssh -o ProxyCommand='x' h",
                    "GIT_EDITOR='x y' git commit", "git -c core.editor=x commit", "setopt $O; ls",
                    "autoload -U zmv", "zmodload zsh/files", "exiftool -Comment=x a.wav", "open -a Terminal .",
                    "rm -rf stu(d)io", "git $1 $2 $3 $4 status", "export EDITOR='rm -rf x'"):
            self.assertPass(cmd, cwd=plain)
            self.assertIsNotNone(self.bash(cmd), cmd)

    def test_trusted_bin_dir(self):
        from unittest import mock
        from stdo.guard import recog

        class St(object):
            def __init__(s, uid, mode):
                s.st_uid, s.st_mode = uid, mode
        self.assertTrue(recog.trusted_bin_dir("/usr/bin/sed"))
        self.assertFalse(recog.trusted_bin_dir("/tmp/sed"))
        self.assertFalse(recog.trusted_bin_dir("/usr/bin/x/sed"))
        for st, want in ((St(501, 0o40775), False), (St(0, 0o40755), True), (St(0, 0o40775), False)):
            recog._TRUSTED.clear()
            with mock.patch("os.stat", return_value=st):
                self.assertEqual(recog.trusted_bin_dir("/opt/homebrew/bin/sed"), want)
        recog._TRUSTED.clear()

    def test_messages(self):
        d = self.assertDeny("git -c core.editor='rm -rf studio #' commit", "G-OPAQUE")
        self.assertIn("runs a command line the guard does not read", d.message())
        d = self.assertDeny("commands[ls]=/bin/rm", "G-OPAQUE")
        self.assertIn("zsh's command, alias, function or option tables", d.message())
        d = self.assertDeny("git $1 $2 $3 $4 status", "G-OPAQUE")
        self.assertIn("several or none", d.message())


class G1Review1(JudgeCase):
    """G1 implementation review 1: findings that need folders of their own (B1, C-M1, C-m4)."""

    def test_globstar_operand_roles(self):  # B1
        for d in ("src/p/work", "src/q/work", "zz/work"):
            os.makedirs(os.path.join(self.repo, d))
        self.assertPass("mv a.txt src/**/work/")  # src/p/work is moved into src/q/work
        d = self.assertDeny("mv src/a.ts **/work/", "G-DEL")  # zz/work is last: studio/videos/v/work is a source
        self.assertIn("mv deletes studio/", d.message())

    def test_glob_walk_budget(self):  # C-M1: the walks have their own budget; past it the static rule, never G-ERR
        for i in range(60):
            os.makedirs(os.path.join(self.repo, "pkg", "m%03d" % i, "sub"))
        self.assertPass("chmod +x **/*.sh **/*.py **/*.rb **/*.pl")
        self.assertPass("touch **/*.a **/*.b **/*.c **/*.d **/*.e **/*.f")
        # fix20: the 0.0.26 guard refuses it (its `**` rule)
        self.assertHeadRefusedKept("rm -rf **/__pycache__ **/*.pyc **/.pytest_cache **/.mypy_cache", "G-DEL")
        self.assertHeadRefusedKept("rm -rf " + " ".join("**/c%d" % i for i in range(40)), "G-DEL")
        for i in range(60, 600):
            os.makedirs(os.path.join(self.repo, "pkg", "m%03d" % i))
        self.assertDeny("rm -rf **/__pycache__ **/*.pyc **/.pytest_cache **/.mypy_cache", "G-DEL")  # past WALK_MAX
        self.assertDeny("chmod +x **/*.sh **/*.py **/*.rb **/*.pl", "G-PROT")

    def test_limits_are_not_errors(self):  # C-m4; review 2 conformance MINOR 2: G-LIMIT only in a Studio context
        paths = " ".join("%s/d%d/e/f%d.txt" % (self.tmp, i, i) for i in range(400))
        # outside every Studio repository: as before G1 (never G-ERR) — fix20: `cat` of so many files was the 0.0.26
        # guard's own internal error (LimitExceeded), which refuses it again in 0.0.27 (its verdict in 0.0.26)
        self.assertPass('sh -c "cat %s $X"' % paths, cwd=self.tmp)
        self.assertEqual(self.assertHeadRefusedKept("cat %s" % paths, cwd=self.tmp).rule, "G-ERR")
        paths = " ".join("%s/d%d/e/f%d.txt" % (self.repo, i, i) for i in range(400))
        for cmd in ('sh -c "cat %s $X"' % paths, "cat %s" % paths):
            d = self.bash(cmd)
            self.assertIsNotNone(d, cmd[:40])
            self.assertIn(d.rule, ("G-LIMIT", "G-OPAQUE"), d.message())
        self.assertEqual(self.bash("cat %s" % paths).rule, "G-LIMIT")
        from stdo.guard import limits
        from stdo.guard.where import FS

        class Spent(FS):
            def realpath(s, p):
                raise limits.LimitExceeded("fs-calls")
        deny, _ctx = judge.decide(self.hook("Bash", {"command": "rm -rf studio"}), self.env, fs=Spent(),
                                  snapshot_loader=self.loader)
        self.assertEqual(deny.rule, "G-LIMIT")


# fix20: snapshot-function rows the 0.0.26 guard refused (G-OPAQUE: it reads the function's text, which mentions studio
# or cannot be read) — refused again by the backstop in 0.0.27; this guard alone passes them (assertPassOrKept)
HEAD_REFUSED_FUNCS = {
    "diff a.txt src/a.ts; git status", "diff a.txt src/a.ts || git diff", "gh repo view --json visibility; git remote -v",
    "gh pr list && git status", "gh pr view 1; git log --oneline -3", "gh pr create --fill && git push",
    "nvm use 20 && git status", "take tmpdir && git status", "mkcd tmpdir && git init", "pyenv version; git status",
    "claude --version; git status", "d; git status", "branch_name; git status", "fetchdir x && git status",
    "gh pr view 1; git commit -m 'studio: v script'", "gh pr view 1 && git add -A && git commit -m 'fix: x'",
    "branch_name; git commit -m x", "diff a.txt src/a.ts; git commit -m x", "gh pr view 1; open studio/videos/v/script.md",
    "diff a.txt src/a.ts; git checkout -- src/a.ts", "gh pr view 1; echo $X",
    "mkcd tmpdir && python3 -c 'print(\"x\")'", "take x && touch 'a(1).txt'", "mkcd tmpdir && sed -n '1,5p' 'a(1).txt'",
    "take x && cp /tmp/x 'notes (copy).md'", "take <R> & wait; rm -rf studio",
}


# G1 implementation review 2 (R2-M1): shell functions of the snapshot. Neutral fixtures: wrappers that print and
# delegate through `command`, folder changers, a function calling a function, a `[[ =~ ]]` pattern with groups; and
# functions that export, source, eval or assign a global
SNAPSHOT_FUNCS = DEFAULT_FUNCS + '''gh () {
	local label
	label=work
	print -u2 -P "%F{cyan}account: ${label}%f"
	command gh "$@"
}
diff () {
	command diff --color "$@"
}
mkcd () {
	mkdir -p $@ && cd ${@:$#}
}
d () {
	if [[ -n $1 ]]
	then
		dirs "$@"
	else
		dirs -v | head -n 10
	fi
}
nvm () {
	local version=${2:-}
	print -r -- "using node ${version}"
}
pyenv () {
	local command=${1:-}
	[ "$#" -gt 0 ] && shift
	command pyenv "$command" "$@"
}
claude () {
	local label dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
	label=work
	print -P "%F{cyan}${label} (${dir})%f"
	command claude "$@"
}
branch_name () {
	local ref
	ref=$(git_quiet symbolic-ref --quiet HEAD 2> /dev/null)
	print -r -- ${ref#refs/heads/}
}
git_quiet () {
	GIT_OPTIONAL_LOCKS=0 command git "$@"
}
fetchdir () {
	if [[ $1 =~ ^(https?|ftp).*\\.(tar\\.gz|tgz)$ ]]
	then
		curl -LO "$1"
	else
		mkcd "$1"
	fi
}
seteditor () {
	export GIT_EDITOR='rm -rf studio #'
}
loadenv () {
	source ./env.sh
}
evalit () {
	eval "$1"
}
globalset () {
	GIT_DIR=/tmp/x
}
callsbad () {
	seteditor
}
typesetgx () {
	typeset -gx GIT_EDITOR=vi
}
allexport () {
	set -a
}
'''
FUNCTION_PASS = ["diff a.txt src/a.ts; git status", "diff a.txt src/a.ts || git diff",
                 "gh repo view --json visibility; git remote -v", "gh pr list && git status",
                 "gh pr view 1; git log --oneline -3", "gh pr create --fill && git push", "nvm use 20 && git status",
                 "take tmpdir && git status", "mkcd tmpdir && git init", "pyenv version; git status",
                 "claude --version; git status", "d; git status", "branch_name; git status", "fetchdir x && git status"]
FUNCTION_DENY = ["seteditor; git status", "loadenv; git status", "evalit x; git status", "globalset; git status",
                 "callsbad; git status", "typesetgx; git status", "allexport; git status"]


class G1Review2(JudgeCase):
    """G1 implementation review 2: user config and git files in another letter case (M14), shell functions of the
    snapshot (R2-M1), the message of the m5 refusal (MINOR 4)."""

    def use_functions(self):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"], functions=SNAPSHOT_FUNCS))
        self.snap_with = snapmod.load(self.env)
        shutil.rmtree(d)
        self.mode = "with"

    def test_snapshot_functions(self):  # R2-M1
        self.use_functions()
        for cmd in FUNCTION_PASS:
            self.assertPassOrKept(cmd, HEAD_REFUSED_FUNCS)
        for cmd in FUNCTION_DENY:
            d = self.assertDeny(cmd, "G-OPAQUE")
            self.assertIn("cannot read", d.message())
        self.assertDeny("mkcd build && rm -rf local", "G-DEL")  # the folder after a function stays unknown

    def test_m5_message(self):  # MINOR 4: the refusal does not tell the agent to run git another way
        # fix20: after a `source` or an eval the guard cannot read, the 0.0.26 rules judge the rest (the walk stops):
        # code whose environment is unknown otherwise — a function of this call that may export
        _d, ctx = judge.decide(self.hook("Bash", {"command": 'f(){ export "$1"=x; }; f "$N"; git status'}), self.env,
                               snapshot_loader=self.loader)
        texts = [x.text for x in ctx.denies if x.text.startswith("git runs with environment variables")]
        self.assertEqual(len(texts), 1, [x.text for x in ctx.denies])
        self.assertNotIn("separate call", texts[0])
        self.assertIn("shell function", texts[0])

    def test_case_insensitive_config_files(self):  # M14
        probe = os.path.join(os.path.dirname(self.repo), os.path.basename(self.repo).upper())
        if not os.path.exists(probe):
            self.skipTest("the test volume is case-sensitive")
        for cmd in ("echo x >> ~/.GitConfig", "echo x >> ~/.GITCONFIG", "echo x >> ~/.config/Git/Config",
                    "echo x >> ~/.SSH/config", "echo x >> ~/.ssh/CONFIG", "cp /tmp/x ~/.GITCONFIG",
                    "echo x >> .git/Config.Worktree", "echo x >> .GIT/config", "echo x >> .git/CONFIG"):
            self.assertDeny(cmd, "G-HOOKOFF")
        home = self.env["HOME"]
        for p in (os.path.join(home, ".GitConfig"), os.path.join(home, ".SSH", "CONFIG"),
                  os.path.join(self.repo, ".git", "CONFIG.worktree"), os.path.join(self.repo, ".GIT", "config")):
            d = self.decide("Write", {"file_path": p, "content": "[core]\n\tfsmonitor = x\n"})
            self.assertIsNotNone(d, p)
            self.assertEqual(d.rule, "G-HOOKOFF", p)
        self.assertPass("echo x >> ~/.GITCONFIG", cwd=self.tmp)  # outside a Studio repository: not refused


# G1 implementation review 3: shell functions of the snapshot that keep the folder (M-1/M4), set known options (M-2),
# assign plain globals (M-3), or run code the guard cannot read (M-4); bypass m1's forms. Neutral fixtures.
REVIEW3_FUNCS = SNAPSHOT_FUNCS + '''show_branch () {
	local ref
	ref=$(command git symbolic-ref --short HEAD 2> /dev/null)
	print -r -- "${ref:-detached}"
}
set_prompt () {
	PROMPT="%~ $(show_branch) %# "
}
counter () {
	local n=0
	for i in a b
	do
		n=$i
	done
}
extls () {
	setopt localoptions extendedglob
	ls -d ^*.o
}
dotglob () {
	setopt globdots
}
nullls () {
	setopt nullglob
	ls *.tmp
}
runit () {
	"$@"
}
commitwip () {
	git commit -m "$*"
}
byname () {
	: ${(P)1::=$2}
}
branchlocal () {
	if false
	then
		local PATH
	fi
	PATH=$1:$PATH
}
alwaysset () {
	local x
	{ HOME=$1 } always { : }
}
nolocal () {
	unsetopt localoptions
	setopt globsubst
}
lettery () {
	set -y
}
loadcomp () {
	autoload -Uz compinit
}
'''
REVIEW3_FUNCTION_PASS = [
    # M-1 / M4: the folder stays known after a function that does not change folder
    "gh pr view 1; git commit -m 'studio: v script'", "show_branch && git commit -m 'studio: harness'",
    "gh pr view 1 && git add -A && git commit -m 'fix: x'", "branch_name; git commit -m x",
    "diff a.txt src/a.ts; git commit -m x", "gh pr view 1; open studio/videos/v/script.md", "extls; git commit -m x",
    "commitwip wip; git status", "diff a.txt src/a.ts; git checkout -- src/a.ts",
    # M-2: a known option that changes no word
    "dotglob; echo $X", "dotglob; ls $dir", "nullls; cat $f", "dotglob; for f in src/*.ts; do echo $f; done",
    # M-3: plain globals git does not read
    "set_prompt; git status", "set_prompt; git diff", "set_prompt; git push", "counter; git status",
    "counter; git add .", "counter; git commit -m x",
    # M-4: functions and evals that set no option
    "gh pr view 1; echo $X", "ll; ls $dir", "loadcomp; echo $X", "loadcomp; git status",
]
REVIEW3_FUNCTION_DENY = [
    # bypass m1: assignment by name, a `local` on a branch, `always`, LOCAL_OPTIONS off, letter options
    ("byname HOME /tmp/h; git status", "G-OPAQUE"), ("byname PATH /tmp/x; git status", "G-OPAQUE"),
    ("branchlocal /tmp/x; git status", "G-OPAQUE"), ("alwaysset /tmp/h; git status", "G-OPAQUE"),
    ("nolocal; X='a.txt(e:rm -rf studio:)'; ls -d $X", "G-OPAQUE"), ("lettery; X='stash -a'; git $X", "G-OPAQUE"),
    # M-4: GLOB_SUBST through a function the guard cannot read or one that evals
    ("evalit 'setopt globsubst'; X='a.txt(e:rm -rf studio:)'; ls -d $X", "G-OPAQUE"),
    ("loadenv; X='a.txt(e:rm -rf studio:)'; ls -d $X", "G-OPAQUE"),
    ("runit setopt globsubst; X='a.txt(e:rm -rf studio:)'; ls -d $X", "G-OPAQUE"),
    # m-1 (accepted): a folder change the guard cannot follow keeps commit refused
    ("mkcd x && git commit -m x", "G-COMMIT"), ("cd -1 && git commit -m x", "G-COMMIT"),
]


class G1Review3(JudgeCase):
    """G1 implementation review 3: snapshot functions (conf M-1 to M-4, bypass M4, m1) and limits outside a Studio
    repository (B1/B-1, M3)."""

    def use_functions(self):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"], functions=REVIEW3_FUNCS))
        self.snap_with = snapmod.load(self.env)
        shutil.rmtree(d)
        self.mode = "with"

    def test_snapshot_functions(self):
        self.use_functions()
        for cmd in REVIEW3_FUNCTION_PASS + FUNCTION_PASS:
            self.assertPassOrKept(cmd, HEAD_REFUSED_FUNCS)
        for cmd, rule in REVIEW3_FUNCTION_DENY:
            self.assertDeny(cmd, rule)
        for cmd in FUNCTION_DENY:
            self.assertDeny(cmd, "G-OPAQUE")

    def test_existing_decoys_outside(self):  # conf B-1: decoy folders named studio that exist
        decoys = []
        for i in range(200):
            p = os.path.join(self.tmp, "out", "o%d" % i, "studio")
            os.makedirs(p)
            decoys.append(p)
        dec = " ".join(decoys)
        for cmd in ("sh -c 'rm -rf %s %s/studio'", "bash -c 'rm -rf %s %s/studio/local'",
                    "nohup sh -c 'rm -rf %s %s/studio'", "sh -c 'ls %s; rm -rf %s/studio'",
                    "sh -c 'mv %s %s/studio /tmp/x'"):
            d = self.bash(cmd % (dec, self.repo), cwd=self.tmp)
            self.assertIsNotNone(d, cmd)
            self.assertIn(d.rule, ("G-LIMIT", "G-DEL"), cmd)
        d = self.bash("sh -c 'cd %s && ls %s && rm -rf studio'" % (self.repo, dec), cwd=self.tmp)
        self.assertIsNotNone(d)

    def test_limit_outside_names_nothing(self):  # B1: a limit with nothing left that can name a repository
        from stdo.guard import limits
        from stdo.guard.where import FS

        class Spent(FS):
            def realpath(s, p):
                raise limits.LimitExceeded("fs-calls")
        out = os.path.join(self.tmp, "plainfolder")
        os.makedirs(out)
        deny, _ctx = judge.decide(self.hook("Bash", {"command": "ls /tmp"}, out), self.env, fs=Spent(),
                                  snapshot_loader=self.loader)
        self.assertEqual(deny.rule, "G-LIMIT")
        ctx = judge.Context(self.hook("Bash", {"command": "x"}, out), self.env)
        ctx.snap = self.snap_with[0]
        for cmd in ("echo hello world", "ls proj", "true a b c", "g st"):
            self.assertFalse(judge.may_name_repo(ctx, cmd), cmd)
        for cmd in ("ls /tmp", "cd sub; ls", "echo $X", "ls ~", "ls ..", "ls s*", "ls {a,b}", "-", "take x", "ls st\\udio"):
            self.assertTrue(judge.may_name_repo(ctx, cmd), cmd)
        os.makedirs(os.path.join(out, "proj"))
        self.assertTrue(judge.may_name_repo(ctx, "ls proj"))  # a folder in the working folder may be a repository
        self.assertTrue(judge.may_name_repo(ctx, "git -Cproj status"))
        ctx.snap = None
        self.assertTrue(judge.may_name_repo(ctx, "echo hello"))  # no snapshot: any word may be an alias


# G1 implementation review 4: autoload stubs (B1), functions that clear BARE_GLOB_QUAL (B2), functions the call
# redefines under a snapshot function (B3), `typeset -p` (m1), arithmetic by name (m2), NULLCMD (R4), functions that
# source or eval or run a dynamic command word (conf M-1, M-2, m-1), globals with a fixed prefix (conf m-2). Neutral
# fixtures.
REVIEW4_FUNCS = REVIEW3_FUNCS + '''proj () {
	# undefined
	builtin autoload -XU
}
projz () {
	# undefined
	builtin autoload -XUz
}
show () {
	git status
}
callhelper () {
	helper
}
helper () {
	print -r -- helper
}
nbq () {
	unsetopt bareglobqual
}
tp () {
	typeset -p PATH > /dev/null
	PATH=$1:$PATH
}
tp2 () {
	local -p HOME > /dev/null
	HOME=$1
}
tpx () {
	typeset -p GIT_EDITOR > /dev/null
	GIT_EDITOR=$1
}
ar () {
	(( $1 = 1 ))
}
nc () {
	NULLCMD=$1
}
nodeuse () {
	source "$NODE_HOME/env.sh"
}
envinit () {
	eval "$(envtool init -)"
}
clipit () {
	"${CLIP_CMD:-pbcopy}" < "$1"
}
cachekey () {
	typeset -g "_mycache_${1}"=1
}
cacheany () {
	typeset -g "${1}_x"=1
}
'''
REVIEW4_FUNCTION_DENY = [
    # B1: an autoload stub runs its $fpath file in this shell
    ("proj; rm -rf local", "G-DEL"), ("projz; rm -rf local", "G-DEL"), ("proj; git commit -m x", "G-COMMIT"),
    ("proj; X='a.txt(e:true:)'; ls -d $X", "G-OPAQUE"), ("proj; git stash -a", "G-RESET"),
    # B2: a function that turns BARE_GLOB_QUAL off (it is off in the Bash tool anyway)
    ("nbq; rm -rf studi(o)", "G-UNPARSE"), ("nbq; rm -rf studio/video(s)", "G-UNPARSE"),
    # B3: a function this call defines may be one a snapshot function runs
    ("function git { cd studio }; show; rm -rf local", "G-DEL"),
    ("helper(){ cd studio; }; callhelper; rm -rf local", "G-DEL"),
    ("git(){ setopt globsubst; }; show; X='a.txt(e:true:)'; ls -d $X", "G-OPAQUE"),
    ("git(){ export GIT_EDITOR=x; }; show; command git commit", "G-OPAQUE"),
    ("eval 'git(){ cd studio; }'; show; rm -rf local", "G-DEL"),
    ("mkdir(){ cd studio; }; take x; rm -rf local", "G-DEL"),
    # m1: `typeset -p` prints; m2: arithmetic assigns a name the guard cannot read
    ("tp /tmp/e; git commit -m x", "G-OPAQUE"), ("tp2 /tmp/h; git commit -m x", "G-OPAQUE"),
    ("tpx vi; git commit", "G-OPAQUE"),
    ("ar GIT_DIR; git status", "G-OPAQUE"), ("ar GIT_DIR; git commit -m x", "G-COMMIT"),
    # R4: NULLCMD set by a function
    ("nc sh; > /dev/null <<< 'rm -rf stu''dio'", "G-DEL"),
    # conf M-1: values the call may steer after a function the guard cannot read
    ("nodeuse 20; for f in src/*.ts; do echo $f; done", "G-OPAQUE"), ("nodeuse X; ls $X", "G-OPAQUE"),
    ("nodeuse 20 <<< x; ls $X", "G-OPAQUE"), ("echo x > f.txt; nodeuse 20; ls $X", "G-OPAQUE"),
    ("nodeuse 20 $Y; ls $X", "G-OPAQUE"), ("nodeuse 20; X='a.txt(e:true:)'; ls -d $X", "G-OPAQUE"),
    # conf m-1 (kept): a function zsh cannot see into may define `cd` at run time, which a later literal cd calls
    ("nodeuse 20; cd <R> && python3 .claude/studio/scripts/state.py status v", "G-PROT"),
    # conf m-2: a global whose name the guard cannot read may be a watched one
    ("cacheany GIT_DIR; git status", "G-OPAQUE"),
]
REVIEW4_FUNCTION_PASS = [
    # conf M-1: unquoted values only the environment sets, after functions the guard cannot read
    "nodeuse 20; ls $X", "nodeuse 20; echo $X", "envinit; cat $f", "clipit a.txt; ls $dir",
    "nodeuse 20; for i in 1 2 3; do echo $i; done", "nodeuse 20; echo $HOME", "nodeuse 20; basename $PWD",
    "nodeuse 20; echo ${#X}", "nodeuse 20; arr=(a b); echo ${arr[1]}", "nodeuse 20; grep -c x $f",
    "nodeuse 20; touch $f", "nodeuse 20; rm -f $f", "nodeuse 20; mkdir -p $D", "nodeuse 20; cd $D && ls",
    "nodeuse 20; cd src; basename $PWD", "envinit; [[ -n $X ]] && echo y", "envinit; X=$Y npm test",
    "envinit; case $X in a) echo a;; esac", "envinit; local v=$X", "envinit; typeset -i n=$X",
    # conf M-2: quoted pattern characters under a folder a function left unknown
    "mkcd tmpdir && python3 -c 'print(\"x\")'", "take x && touch 'a(1).txt'", "nodeuse 20 && node -e 'console.log(1)'",
    "mkcd tmpdir && sed -n '1,5p' 'a(1).txt'", "take x && cp /tmp/x 'notes (copy).md'",
    # conf m-2: a global with a fixed prefix no watched name has; B3: no definition in the call
    "cachekey a; git status", "show; git commit -m x", "alias ll2='ls -l'; show; git commit -m x",
]
# from the repository's parent folder (bypass "checked and clean": these run nothing in the repository)
REVIEW4_OUT_PASS = ["builtin take <R>; rm -rf studio", "command take <R>; rm -rf studio",
                    "exec take <R>; rm -rf studio", "take <R> & wait; rm -rf studio",
                    "alias show='cd <R>'\nshow; rm -rf studio"]
REVIEW4_OUT_DENY = [("proj studio-repo; rm -rf studio", "G-DEL"), ("git(){ cd <R>; }; show; rm -rf studio", "G-DEL"),
                    ("git(){ builtin cd <R>; }; show; rm -rf studio", "G-DEL"),
                    ("helper(){ cd <R>; }; callhelper; rm -rf studio", "G-DEL")]
# m3: hook functions of the snapshot (each its own snapshot), with the command and the folder it runs from
SNAP_HOOKS = [
    ("chpwd () {\n\texport PATH=$PWD/node_modules/.bin:$PATH\n}\n", "cd src; git commit -m x", None, "G-OPAQUE"),
    ("chpwd () {\n\tsetopt globsubst\n}\n", "cd src; X='a.txt(e:true:)'; ls -d ../$X", None, "G-OPAQUE"),
    ("chpwd () {\n\t[[ -d studio ]] && builtin cd -q studio\n}\n", "cd <R>; rm -rf local", "out", "G-DEL"),
    ("chpwd () {\n\t[[ -d studio ]] && builtin cd -q studio\n}\n", "cd .; rm -rf local", None, "G-DEL"),
    ("TRAPDEBUG () {\n\texport GIT_EDITOR=vi\n}\n", "git commit -m x", None, "G-OPAQUE"),
    ("chpwd () {\n\tprint -r -- moved\n}\n", "cd src; git commit -m x", None, None),
]


class G1Review4(JudgeCase):
    """G1 implementation review 4: snapshot functions (B1, B2, B3, m1, m2, m3, R4, conf M-1, M-2, m-1, m-2), the
    two-word pushd from a subfolder (R2) and the quoting of a word under an unknown folder (conf M-2)."""

    def use(self, functions):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"], functions=functions))
        self.snap_with = snapmod.load(self.env)
        shutil.rmtree(d)
        self.mode = "with"

    def test_snapshot_functions(self):
        self.use(REVIEW4_FUNCS)
        for cmd in REVIEW4_FUNCTION_PASS:
            self.assertPassOrKept(cmd, HEAD_REFUSED_FUNCS)
        for cmd, rule in REVIEW4_FUNCTION_DENY:
            self.assertDeny(cmd.replace("<R>", self.repo), rule)
        for cmd in REVIEW4_OUT_PASS:
            self.assertPassOrKept(cmd.replace("<R>", self.repo), HEAD_REFUSED_FUNCS, cwd=self.tmp)
        for cmd, rule in REVIEW4_OUT_DENY:
            self.assertDeny(cmd.replace("<R>", self.repo), rule, cwd=self.tmp)

    def test_snapshot_hooks(self):  # m3
        for funcs, cmd, cwd, rule in SNAP_HOOKS:
            self.use(DEFAULT_FUNCS + funcs)
            text, where = cmd.replace("<R>", self.repo), self.tmp if cwd == "out" else None
            if rule:
                self.assertDeny(text, rule, cwd=where)
            else:
                self.assertPass(text, cwd=where)

    def test_two_word_pushd(self):  # R2: zsh replaces src with studio in $PWD
        src = os.path.join(self.repo, "src")
        for cmd in ("pushd src studio; rm -rf local", "pushd -q src studio; rm -rf local"):
            self.assertDeny(cmd, "G-DEL", cwd=src)
        self.assertDeny("pushd src studio && git stash -a", "G-RESET", cwd=src)

    def test_bare_glob_qual(self):  # B2: qualifiers are read only where BARE_GLOB_QUAL is certainly on
        class Snap(object):
            options = {"bareglobqual": True}
            option_conflicts = set()
            user_functions = alternatives = global_aliases = plain = {}
        self.assertTrue(judge.bare_glob_qual_on("ls **/*(.)", Snap()))
        for cmd in ("unsetopt bareglobqual; ls *(.)", "setopt kshglob; ls *(.)", "emulate sh; ls *(.)",
                    "eval x; ls *(.)"):
            self.assertFalse(judge.bare_glob_qual_on(cmd, Snap()), cmd)
        self.assertFalse(judge.bare_glob_qual_on("ls **/*(.)", None))  # the Bash tool: off
        self.assertFalse(judge.bare_glob_qual_on("ls **/*(.)", self.snap_with[0]))


# G1 implementation review 5, after a snapshot function the guard cannot read (`nodeuse` sources a file: the options
# are unknown, GLOB_SUBST and EXTENDED_GLOB may be on). Neutral fixtures (REVIEW4_FUNCS).
_Q5F = "'a.txt(#qe:rm -rf stu\"\"dio:)'"
REVIEW5_FUNCTION_DENY = [
    ("nodeuse 20; Z=%s; ls -d $Z[1,-1]" % _Q5F, "G-OPAQUE"), ("nodeuse 20; Z=%s; ls -d $Z:a" % _Q5F, "G-OPAQUE"),
    ("nodeuse 20; set -- %s; ls -d $1" % _Q5F, "G-OPAQUE"), ("nodeuse 20; : %s; ls -d $_" % _Q5F, "G-OPAQUE"),
    ("nodeuse 20; read -r Z; ls -d $Z[1,-1]", "G-OPAQUE"), ("nodeuse 20; for Z in *; do ls -d $Z:t; done", "G-OPAQUE"),
    ("nodeuse 20; PS1=%s; ls -d $PROMPT" % _Q5F, "G-OPAQUE"),
    ("nodeuse 20; cdpath=(%s); ls -d $CDPATH" % _Q5F, "G-OPAQUE"),
    ("nodeuse 20; alias q=%s; ls -d $aliases[q]" % _Q5F, "G-OPAQUE"),
    ("nodeuse 20; private Z=%s; ls -d $Z" % _Q5F, "G-OPAQUE"),
    ("nodeuse 20; Z=%s; typeset -a W=($Z)" % _Q5F, "G-OPAQUE"),
    ("nodeuse 20; { Z=%s }; ls -d $Z" % _Q5F, "G-OPAQUE"),
    ("nodeuse 20; cd $D; rm -rf ^x", "G-DEL"),
]
REVIEW5_FUNCTION_PASS = ["nodeuse 20; ls $HOME:t", "nodeuse 20; ls -d $PWD:h", "nodeuse 20; echo $#",
                         "nodeuse 20; ls -d $X:t"]


class G1Review5(JudgeCase):
    """G1 implementation review 5: values after a snapshot function the guard cannot read (M1, M2, M3, R1, the
    extended-glob wildcards under an unknown folder)."""

    use = G1Review4.use

    def test_snapshot_functions(self):
        self.use(REVIEW4_FUNCS)
        for cmd in REVIEW5_FUNCTION_PASS:
            self.assertPass(cmd)
        for cmd, rule in REVIEW5_FUNCTION_DENY:
            self.assertDeny(cmd, rule)


# G1 implementation review 6: wildcards against the installed hook files (M12), and extended-glob words after a
# snapshot function the guard cannot read (conf m-1)
REVIEW6_HOOK_DENY = [
    ("rm -rf .git/hook?", "G-PROT"), ("rm -rf .git/h*", "G-PROT"), ("mv .git/hooks/pre-* /tmp/", "G-PROT"),
    ("cp /tmp/x .git/hooks/*", "G-PROT"), ("cp /tmp/x .git/*/pre-commit", "G-PROT"),
    ("cp /tmp/x .git/hooks/pre-commi?", "G-PROT"), ("rm -f .git/hooks/pre-commi?", "G-PROT"),
    ("cp /tmp/x .husky/pre-commi?", "G-PROT"), ("cp /tmp/x .hus*/pre-commit", "G-PROT"), ("rm -f .husky/*", "G-PROT"),
    ("print x >> .husky/pre-*", "G-PROT"), ("touch .git/hooks/pre-commi?", "G-PROT"),
    ("chmod 000 .git/hooks/pre-commi?", "G-PROT"), ("ln -sf /tmp/x .git/hooks/pre-commi?", "G-PROT"),
    ("cd .git/hooks; rm -f pre-*", "G-PROT"), ("cd .git; rm -rf hoo?s", "G-PROT"),
    ("setopt extendedglob; cp /tmp/x .git/hooks/pre-commit~x", "G-PROT"),
    ("setopt extendedglob; cp /tmp/x .git/hooks/pre-commi#t", "G-PROT"), ("setopt extendedglob; rm -f .git/hooks/^x", "G-PROT"),
    ("setopt extendedglob; rm -rf .git/hook#s", "G-PROT"), ("cp /tmp/x .git/confi?", "G-HOOKOFF"),
    ("setopt extendedglob; rm -f .git/config~x", "G-HOOKOFF"),
]
REVIEW6_HOOK_PASS = ["ls .git/hooks/*", "cat .husky/pre-*", "rm -f .git/*.lock", "cp /tmp/x .git/hooks/post-merg?"]
REVIEW6_FUNCTION_PASS = ["nodeuse 20; touch notes#1", "nodeuse 20; cp a.txt a.txt~", "nodeuse 20; rm -f notes#1",
                         "nodeuse 20; rm -f *~", "nodeuse 20; rm -f *.log"]
REVIEW6_FUNCTION_DENY = [("nodeuse 20; cd $D; rm -rf ^x", "G-DEL"), ("nodeuse 20; cd $D; rm -rf l#ocal", "G-DEL"),
                         ("nodeuse 20; cd $D; rm -f *", "G-DEL")]


REVIEW7_HOOK_DENY = [
    ("setopt extendedglob; cp /tmp/x .git/hooks/[p~]re-commit", "G-PROT"),
    ("setopt extendedglob; rm -rf .git/hooks/[p~]re-commit", "G-PROT"), ("setopt extendedglob; rm -rf .git/[h~]ooks", "G-PROT"),
    ("setopt extendedglob; rm -rf .git/hoo[k~]s", "G-PROT"), ("setopt extendedglob; cp /tmp/x .husky/[p~]re-commit", "G-PROT"),
    ("setopt extendedglob; rm -rf .[h~]usky", "G-PROT"), ("setopt extendedglob; cp /tmp/x .git/[c~]onfig", "G-HOOKOFF"),
    ("setopt extendedglob; rm -f .git/[c~]onfig", "G-HOOKOFF"), ("cp /tmp/x .git/hooks/pre[]-^]commit", "G-PROT"),
    ("rm -f .husky/pre[]-^]commit", "G-PROT"), ("cp /tmp/x .git/hooks/[p/]re-commit", "G-PROT"),
]
REVIEW7_HOOK_PASS = ["cp /tmp/x .git/hooks/post-merg[e~]x", "setopt extendedglob; cat .git/hooks/[p~]re-commit"]
REVIEW8_ALIASES = [("gpristine", "'git reset --hard && git clean --force -dfx'"), ("xrm", "'/bin/rm -rf'"),
                   ("gcn!", "'git commit --verbose --no-edit --amend'")]
REVIEW8_ALIAS_DENY = [("time; gpristine", "G-CLEAN"), ("print a &>|/dev/null; gpristine", "G-CLEAN"),
                      ("time; xrm s*", "G-DEL"), ("time; gcn! --no-verify", "G-COMMITFORM")]
REVIEW8_ALIAS_UNPARSE = ["xrm s* )", "echo ok; gpristine )"]


class G1Review11(JudgeCase):
    """G1 implementation review 11: files the command sources (review 14: never followed; git after them as at HEAD),
    function-table changes after code the guard cannot read, and values that are one of a few known ones (conf M-1)."""

    def write(self, name, text):
        p = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return p

    def test_sourced_files(self):
        self.write(".venv/pyvenv.cfg", "home = /usr/bin\n")
        self.write(".venv/bin/activate", "deactivate () {\n    if [ -n \"${_OLD_VIRTUAL_PATH:-}\" ] ; then\n"
                   "        PATH=\"${_OLD_VIRTUAL_PATH:-}\"\n        export PATH\n        unset _OLD_VIRTUAL_PATH\n"
                   "    fi\n    hash -r 2> /dev/null || true\n    unset VIRTUAL_ENV\n"
                   "    if [ ! \"${1:-}\" = \"nondestructive\" ] ; then\n        unset -f deactivate\n    fi\n}\n"
                   "deactivate nondestructive\ncase \"$(uname)\" in\n    *) export VIRTUAL_ENV=%s/.venv ;;\nesac\n"
                   "_OLD_VIRTUAL_PATH=\"$PATH\"\nPATH=\"$VIRTUAL_ENV/bin:$PATH\"\nexport PATH\n"
                   "PS1=\"(v) ${PS1:-}\"\nexport PS1\nhash -r 2> /dev/null || true\n" % self.repo)
        self.write("env.sh", "export FOO=1\nalias ll='ls -l'\nhelper(){ echo hi; }\n")
        self.write("envalias.sh", "alias ll='export GIT_DIR=/tmp/x'\nll\n")  # review 12 B1a: not followed
        self.write("envgit.sh", "export GIT_DIR=/tmp/x\n")
        self.write("envhome.sh", "export HOME=/tmp\n")
        self.write("envcd.sh", "cd src\n")
        self.write("envx.sh", "X=studio\n")
        self.write("envopt.sh", "setopt globsubst\n")
        self.write("envfn.sh", "f(){ :; }\n")
        self.write("enveval.sh", "export A=1\neval \"$B\"\n")
        for cmd in ("source .venv/bin/activate && git commit -m x", ". .venv/bin/activate; git add -A; git commit -m x",
                    "source .venv/bin/activate && deactivate && git status", "source env.sh && git status",
                    "source env.sh && git commit -m x", "cd src && source ../env.sh && git status",
                    "source envcd.sh && git status", "source env.sh; rm -rf build"):
            self.assertPass(cmd)
        # review 14: files are never followed; git after a source is judged as at HEAD (not checked: the folder and
        # the environment are the source's), whatever the file says
        outside = os.path.join(self.tmp, "outside.sh")
        with open(outside, "w") as f:
            f.write("export FOO=1\n")
        for cmd in ("source envgit.sh && git status", "source envhome.sh && git status",
                    "source envalias.sh && git status",
                    "source %s && git status" % outside, "source envcd.sh && git commit -m x"):
            self.assertPass(cmd)
        self.assertDeny("source enveval.sh && git status", "G-OPAQUE")  # the file's eval (its text is searched)
        self.assertDeny("source missing.sh && git status", "G-OPAQUE")  # a file the guard cannot read, as at HEAD
        self.assertDeny("source envx.sh; rm -rf -- $X", "G-OPAQUE")  # $X unknown after it, as at HEAD
        self.assertDeny("f(){ cd /tmp; }; source envfn.sh; f; rm -rf studio", "G-DEL")
        self.assertDeny("source envcd.sh; rm -rf studio", "G-DEL", cwd=os.path.join(self.repo, "src"))

    def test_function_table_after_unreadable_code(self):
        self.mode = "none"
        self.assertDeny("f(){ cd /tmp; }; nvm use 20; f; rm -rf studio", "G-DEL")
        self.assertDeny("X=studio; f(){ X=a; }; nvm use 20; f; rm -rf -- $X", "G-DEL")
        self.assertDeny("git(){ :; }; eval 'unfunction git'; git clean -fdx", "G-CLEAN")

    def test_choice_values(self):
        os.makedirs(os.path.join(self.repo, "sub"), exist_ok=True)
        for cmd in ("if [[ -n $X ]]; then D=src; else D=sub; fi; cd $D && git status",
                    "if [[ -n $X ]]; then D=src; else D=sub; fi; cd $D; ls; cd ..; git commit -m x",
                    "if [[ -n $X ]]; then F=a.txt; else F=b.txt; fi; sed -i '' 's/a/b/' $F",
                    "if [[ -n $X ]]; then N=a; else N=b; fi; tar -czf /tmp/$N.tgz src"):
            self.assertPass(cmd)
        self.assertDeny("if [[ -n $X ]]; then D=src; else D=studio; fi; cd $D && rm -rf local", "G-DEL")
        self.assertDeny("if [[ -n $X ]]; then F=a.txt; else F=studio; fi; git rm -r $F", "G-DEL")


_R12_FILES = {
    # B1a: an alias the file defines (or the call defined) applies to its later lines
    "up.sh": "alias up='cd ..'\nup\n", "up2.sh": "up\n", "up3.sh": "alias -g UP='..'\ncd UP\n",
    "up4.sh": "alias cd='cd ..'\ncd\n", "up5.sh": "builtin alias up='cd ..'\nup\n", "up6.sh": "al''ias up='cd ..'\nup\n",
    "g1.sh": "cd UPG\n", "g4.sh": "export FOO=1 UPC\n",
    # B1b: forms the dry walk may not follow
    "h1.sh": "HOME=.. cd\n", "h2.sh": "HOME=.. pushd\n", "n1.sh": "cd noperm 2>/dev/null || cd ..\n",
    "n2.sh": "cd noperm || cd ..\n", "q4.sh": "up(){ cd ..; }\nsetopt extendedglob\nx=(q4.sh(#q+up))\n",
    "q8.sh": "setopt extendedglob\nx=(q8.sh(#qe:'cd ..':))\n", "f1.sh": "myup\n",
    # harmless
    "ok.sh": "export FOO=1\nAPI=http://x\n",
}


class G1Review12(JudgeCase):
    """G1 implementation review 12: a sourced file that may move the shell (B1; review 14: never followed), `cd X ||
    exit` (conf m-5), the `**` listing after a source (conf m-1), more than 16 combinations of known values (conf m-3)."""

    def setUp(self):
        super().setUp()
        for name, text in _R12_FILES.items():
            with open(os.path.join(self.repo, "src", name), "w") as f:
                f.write(text)
        self.src = os.path.join(self.repo, "src")

    def use_snap(self, **kw):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"], **kw))
        self.snap_with = snapmod.load(self.env)
        shutil.rmtree(d)
        self.mode = "with"

    def test_sourced_file_moves(self):
        os.makedirs(os.path.join(self.src, "noperm"))
        os.chmod(os.path.join(self.src, "noperm"), 0)  # cd fails there: the file's `|| cd ..` runs
        self.addCleanup(os.chmod, os.path.join(self.src, "noperm"), 0o755)
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in ("source up.sh; rm -rf studio", ". ./up.sh; rm -rf studio", "source ./up.sh && rm -rf studio",
                        "source up.sh; rm -rf .claude/studio", "alias up='cd ..'; source up2.sh; rm -rf studio",
                        "source up3.sh; rm -rf studio", "source up4.sh; rm -rf studio", "source up5.sh; rm -rf studio",
                        "source up6.sh; rm -rf studio", "source h1.sh; rm -rf studio", "source h2.sh; rm -rf studio",
                        "source n1.sh; rm -rf studio", "source n2.sh; rm -rf studio", "source q4.sh; rm -rf studio",
                        "source q8.sh; rm -rf studio", "myup(){ cd ..; }; source f1.sh; rm -rf studio"):
                self.assertDeny(cmd, "G-DEL", cwd=self.src)
            self.assertDeny("source up.sh; echo x > studio/videos/v/work/state.json", "G-PROT", cwd=self.src)
            self.assertPass("source ok.sh; rm -rf build", cwd=self.src)
            # the typed form zsh runs the same way
            self.assertDeny("HOME=.. pushd; rm -rf studio", "G-DEL", cwd=self.src)
        self.use_snap(extra_alias_lines=["alias -g UPG='..'", "alias -g UPC='; cd ..'"])
        self.assertDeny("source g1.sh; rm -rf studio", "G-DEL", cwd=self.src)
        self.assertDeny("source g4.sh; rm -rf studio", "G-DEL", cwd=self.src)

    def test_virtual_environment_and_listing(self):
        os.makedirs(os.path.join(self.repo, ".venv", "bin"))
        with open(os.path.join(self.repo, ".venv", "pyvenv.cfg"), "w") as f:
            f.write("home = /usr/bin\n")
        with open(os.path.join(self.repo, ".venv", "bin", "activate"), "w") as f:
            f.write("# This file must be used with \"source bin/activate\" *from bash*\n"
                    "# use `if (set -u; : $PYTHONHOME) ;` in bash\n"
                    "deactivate () {\n    unset VIRTUAL_ENV\n    hash -r 2> /dev/null || true\n"
                    "    if [ ! \"${1:-}\" = \"nondestructive\" ] ; then\n        unset -f deactivate\n    fi\n}\n"
                    "deactivate nondestructive\ncase \"$(uname)\" in\n    CYGWIN*) VIRTUAL_ENV=$(cygpath /x) ;;\n"
                    "    *) export VIRTUAL_ENV=%s/.venv ;;\nesac\nPATH=\"$VIRTUAL_ENV/bin:$PATH\"\nexport PATH\n"
                    "if [ -n \"${PYTHONHOME:-}\" ] ; then\n    unset PYTHONHOME\nfi\n" % self.repo)
        os.makedirs(os.path.join(self.repo, "src", "__pycache__"))
        for cmd in ("source .venv/bin/activate && git commit -m x", "source .venv/bin/activate; rm -rf **/__pycache__",
                    ". .venv/bin/activate; rm -rf **/__pycache__"):
            self.assertPass(cmd)  # (with no snapshot, cygpath is a command the guard cannot resolve: as before)
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in ("source /dev/null; rm -rf **/__pycache__", "source src/ok.sh; rm -rf **/__pycache__"):
                self.assertPass(cmd)
            self.assertDeny("touch a; rm -rf **/__pycache__", "G-DEL")  # a writer before it
            # review 14: after a source the folder is unknown and `**` is judged as at HEAD
            self.assertPass("source src/ok.sh; touch a; rm -rf **/__pycache__")

    def test_cd_or_exit(self):
        os.makedirs(os.path.join(self.repo, "sub"))
        sub = os.path.join(self.repo, "sub")
        block = "cd src || exit 1\ngit status --short\ncd ..\npushd scripts >/dev/null && python3 x.py; popd >/dev/null\n"
        for mode in ("with", "none"):
            self.mode = mode
            # review 13: the early stop is gone — the rest of the list is judged (documented false refusal)
            self.assertDeny(block * 3 + "git add -A && git commit -m wip", "G-COMMIT", cwd=sub)
            self.assertPass("cd src || exit 1; cd ..; git commit -m x", cwd=sub)
            self.assertDeny("cd nope || return; rm -rf ../studio", "G-DEL")
            self.assertDeny("mkdir nope; cd nope || return; rm -rf ../studio", "G-DEL")
            self.assertDeny("f(){ mkdir nope; }; f; cd nope || exit 1; rm -rf ../studio", "G-DEL")
            self.assertDeny("TRAPDEBUG(){ mkdir -p nope; }; cd nope || exit 1; rm -rf ../studio", "G-DEL")

    def test_choice_combinations_message(self):
        cmd = "; ".join("%s=1; [[ -n $X%d ]] && %s=2" % (v, i, v) for i, v in enumerate("ABCDE")) + \
            "; node build.js $A $B $C $D $E"
        d = self.assertDeny(cmd, "G-OPAQUE")
        self.assertIn("more than 16 combinations", d.message())
        self.assertPass(cmd.replace(" $E", ""))


_R13_FILES = {
    # conf M-1: env files whose text merely mentions a move word (passed before review 12)
    "env1.sh": 'export PATH="$HOME/.local/bin:$PATH"\nexport NODE_ENV=development\n',
    "env2.sh": 'export CACHE_DIR="${HOME}/.cache/app"\n',
    "env3.sh": "# Usage: cd to the repo root, then source this file\nexport A=1\n",
    "env4.sh": "# helper functions for the build\nexport B=2\n", "env5.sh": 'echo "next: cd src && npm test"\n',
    "env6.sh": "set -a\nAPI=http://x\nset +a\n", "env7.sh": "set -euo pipefail\nexport C=1\n",
    "env8.sh": "set -o allexport\nD=1\nset +o allexport\n", "env9.sh": 'export PATH="$HOME/.local/bin:$PATH"; set -a\n',
    "env10.sh": 'alias ll="ls -l"\nexport E=1\n', "env11.sh": "export Y=$(uname)\n",
    # files that do move the shell or change what later words mean
    "m1.sh": "cd ..\n", "m2.sh": "HOME=..\n", "m3.sh": "export HOME=..\n", "m4.sh": "setopt autopushd\n",
    "m5.sh": "cdpath=(..)\n", "m6.sh": "set -o cdablevars\n", "m7.sh": "typeset -x HOME=..\n",
    "m8.sh": "for HOME in ..; do :; done\n", "m9.sh": ": ${HOME::=..}\n", "m10.sh": "set -k\n",
    "m11.sh": "g(){ cd ..; }\n", "m12.sh": "alias up='cd ..'\n", "m13.sh": "x=(*(e:'cd ..':))\n",
    "m14.sh": "set -o GLOB_SUBST\n",
    # B13-2: files that may write (not "quiet")
    "q1.sh": "export Y=$(dirname x; mkdir -p nope)\n", "q2.sh": 'export Y="$(pwd && mkdir -p nope)"\n',
    "q3.sh": "echo $(uname >/dev/null; mkdir nope) >/dev/null\n", "q4.sh": "y=(*(e:'mkdir -p nope':))\n",
    "q5.sh": "x='a[$''(mkdir nope)]'; echo $((x))\n", "q6.sh": "integer n=x\n",
}


class G1Review13(JudgeCase):
    """G1 implementation review 13: no early stop at `cd X || exit` (B13-1, B13-2, M13-1). Review 14: sourced files are
    no longer followed — env files then commit pass as at HEAD, files that move the shell leave the folder unknown."""

    def setUp(self):
        super().setUp()
        for name, text in _R13_FILES.items():
            with open(os.path.join(self.repo, "scripts", name), "w") as f:
                f.write(text)
        os.makedirs(os.path.join(self.repo, "src", "__pycache__"))

    def test_cd_or_exit_judged(self):
        hooks = "core.hooksPath /dev/null"
        for mode in ("with", "none"):
            self.mode = mode
            self.assertDeny("git branch nope/x; cd .git/refs/heads/nope || exit; rm -rf ../../../../studio", "G-DEL")
            self.assertDeny("git tag nope/x; cd .git/refs/tags/nope || exit; rm -rf ../../../../studio", "G-DEL")
            self.assertDeny("git branch nope/x; cd .git/refs/heads/nope || exit; git -C ../../../.. config " + hooks,
                            "G-HOOKOFF")
            for q in ("q1", "q2", "q3", "q4"):
                self.assertDeny("source scripts/%s.sh; cd nope || exit; rm -rf %s/studio" % (q, self.repo), "G-DEL")
                self.assertDeny("source scripts/%s.sh; cd nope || exit; git -C %s config %s" % (q, self.repo, hooks),
                                "G-HOOKOFF")
            self.assertDeny("y=(*(e:'mkdir -p nope':)); cd nope || exit; rm -rf %s/studio" % self.repo, "G-DEL")

    def test_env_files_then_commit(self):
        for mode in ("with", "none"):
            self.mode = mode
            for n in sorted(k for k in _R13_FILES if k.startswith("env")):
                self.assertPass('source scripts/%s && git add -A && git commit -m "fix: x"' % n)
                self.assertPass("set -a; source scripts/%s; set +a; git commit -m x" % n)
            for n in sorted(k for k in _R13_FILES if k.startswith("m")):
                # review 14: files are not followed; git after a source is not checked, as at HEAD
                self.assertPass("source scripts/%s; git commit -m x" % n)
                self.assertDeny("source scripts/%s; rm -rf studio" % n, "G-DEL", cwd=os.path.join(self.repo, "src"))
            src = os.path.join(self.repo, "src")
            for n in ("m2.sh", "m3.sh", "m7.sh", "m8.sh", "m9.sh"):
                self.assertDeny("source ../scripts/%s; cd; rm -rf studio" % n, "G-DEL", cwd=src)

    def test_listing_after_source(self):
        # review 14: whatever the file holds, the folder after it is unknown and `**` is judged as at HEAD; a source
        # is a writer for the bulk-writer rule (W4) as at HEAD
        for mode in ("with", "none"):
            self.mode = mode
            for n in sorted(_R13_FILES):
                self.assertPass("source scripts/%s; rm -rf **/__pycache__" % n)
            self.assertDeny("cp -R /tmp/stage/. .venv; source scripts/env1.sh", "G-PROT")


_R14_FILES = {
    "env.sh": "export A=1\n", "x": "export B=2\n", "cd.sh": "cd ..\n", "e.sh": "export A=1\n",
    # B14-3 alias in a function body, B14-4 flagged cdpath assignment, B14-5 quoted qualifier letters,
    # B14-6 zsh_directory_name, B14-2 a file that appends to itself
    "a1.sh": "f(){ alias up='c\\d ..'; }\nf\nup\n", "c1.sh": ": ${(A)cdpath::=..}\n",
    "q1.sh": "x=(*(#\"q\"e\":cd ..:\"))\n", "z1.sh": "zsh_directory_name(){ [[ $1 == n ]] && reply=(..) }\n",
    "ap.sh": "print \"cd ..\" >> ap.sh\n", "e1.sh": "export PATH=\"$PWD/dist/bin:$PATH\"\nX=$(uname)\n",
}


class G1Review14(JudgeCase):
    """G1 implementation review 14: sourced files are not followed; after `source FILE` the folder, environment, $HOME
    and the function table are unknown (review 18: judged as at HEAD — git not checked while the folder is unknown
    because of the source)."""

    def setUp(self):
        super().setUp()
        for name, text in _R14_FILES.items():
            for d in (self.repo, os.path.join(self.repo, "src")):
                with open(os.path.join(d, name), "w") as f:
                    f.write(text)
        os.makedirs(os.path.join(self.repo, ".venv", "bin"))
        with open(os.path.join(self.repo, ".venv", "pyvenv.cfg"), "w") as f:
            f.write("home = /usr/bin\n")
        with open(os.path.join(self.repo, ".venv", "bin", "activate"), "w") as f:
            f.write("export VIRTUAL_ENV=%s/.venv\nPATH=\"$VIRTUAL_ENV/bin:$PATH\"\nexport PATH\n" % self.repo)

    def test_head_equivalent_passes(self):
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in G1_REVIEW14_PASS:
                self.assertPass(cmd)

    def test_review14_attacks(self):
        src = os.path.join(self.repo, "src")
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in ("cp /tmp/evil.sh e.sh; source e.sh; rm -rf studio", "mv /tmp/evil.sh e.sh; source e.sh; rm -rf studio",
                        "source a1.sh; rm -rf studio", ". ./a1.sh && rm -rf .claude/studio",
                        "source c1.sh; cd .claude; rm -rf studio", "setopt extendedglob; source q1.sh; rm -rf studio",
                        "source ap.sh; rm -rf studio", "source e.sh; cd -; rm -rf studio", "source e.sh; popd; rm -rf studio",
                        "source e.sh; rm -rf .claude/studio"):
                self.assertDeny(cmd, "G-DEL", cwd=src)
            self.assertDeny("source e.sh; echo x > studio/videos/v/work/state.json", "G-PROT", cwd=src)
            for cmd in ("source z1.sh; rm -rf ~[x]/studio", "source z1.sh; rm -rf ~[x]/.husky",
                        "source z1.sh; echo x > ~[x]/studio/videos/v/work/state.json"):
                self.assertDeny(cmd, "G-OPAQUE", cwd=src)
            # review 18: a wildcard after a source is read as text, as at HEAD
            self.assertPass("source e.sh; rm -rf dist/*", cwd=self.repo)
            # review 18: HEAD did not know the folder after the function: the input runs from a folder the guard
            # cannot tell, as at HEAD
            self.assertDeny("f(){ cd studio/videos/v; }; f; source /dev/stdin <<< ':'; git clean -fdx", "G-OPAQUE",
                            cwd=self.repo)
            for cmd in ("cp -R /tmp/stage/. .venv; source .venv/bin/activate", "tar -xf /tmp/s.tar -C .venv; source .venv/bin/activate",
                        "cp -R /tmp/stage/. dist; source src/e1.sh", "cp -R /tmp/stage/. src; source src/e.sh"):
                self.assertDeny(cmd, "G-PROT")  # M14-1, B14-1 (W4): a source is a later writer, as at HEAD


class G1Review15(JudgeCase):
    """G1 implementation review 15: `~[…]` lexing (B15-1/2); `cd -` / `popd` after a source go where they went at
    HEAD (C15-1, review 18: HEAD's $OLDPWD and stack); a literal relative path after a source is read as HEAD read it,
    as if relative to the repository root (C15-2)."""

    def setUp(self):
        super().setUp()
        for d in (self.repo, os.path.join(self.repo, "src"), os.path.join(self.repo, "scripts"),
                  os.path.join(self.repo, "studio/videos/v")):
            for name in ("env.sh", "e.sh"):
                with open(os.path.join(d, name), "w") as f:
                    f.write("export A=1\n")
        with open(os.path.join(self.repo, "config.env"), "w") as f:
            f.write("A=1\n")
        os.makedirs(os.path.join(self.repo, ".venv", "bin"))
        with open(os.path.join(self.repo, ".venv", "bin", "activate"), "w") as f:
            f.write("export VIRTUAL_ENV=%s/.venv\n" % self.repo)

    def test_tilde_brackets(self):
        for mode in ("with", "none"):
            self.mode = mode
            src = os.path.join(self.repo, "src")
            self.assertDeny("X=~[x;cd${=IFS}..;rm${=IFS}-rf${=IFS}studio;]", "G-OPAQUE", cwd=src)
            self.assertDeny("X=~[x;git${=IFS}commit${=IFS}--no-verify${=IFS}-qm${=IFS}x;]", "G-OPAQUE")
            self.assertDeny("X=~[x&&git${=IFS}clean${=IFS}-fdx&&]", "G-OPAQUE")
            self.assertDeny("rm -rf ~[x]/studio", "G-OPAQUE")  # a plain name: still a dynamic named directory
            self.assertPass("ls ~[x]/")

    def test_popd_and_cd_dash_after_source(self):
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in ("pushd src && source ../.venv/bin/activate && popd && git clean -fdx",
                        "pushd src; source ../scripts/env.sh; popd; git clean -fdx",
                        "pushd src >/dev/null; . ../config.env; popd >/dev/null; git clean -fdx",
                        "cd src && source ../.venv/bin/activate && cd - && git clean -fdx",
                        "pushd src; source ../scripts/env.sh; cd -; git clean -fdx",
                        "pushd studio/videos/v; source ../../../scripts/env.sh; popd; git clean -fdx",
                        "pushd src; pushd ../scripts; source env.sh; popd; popd; git clean -fdx",
                        "pushd src; [ -f e.sh ] && source e.sh; popd; git clean -fdx",
                        "pushd src; source e.sh; popd; ls; git clean -fdx", "cd src; source e.sh; cd ~-; git clean -fdx"):
                self.assertDeny(cmd, "G-CLEAN")
            for cmd in ("cd src; source e.sh; rm -rf ~-/studio", "cd src; source e.sh; rm -rf $OLDPWD/studio",
                        "cd src; source e.sh; cd -; rm -rf studio", "pushd src; source e.sh; popd; rm -rf studio"):
                self.assertDeny(cmd, "G-DEL")
            src = os.path.join(self.repo, "src")
            # the file may move the shell: `cd -` / `~-` are not taken as the starting folder after it
            for cmd in ("source e.sh; cd -; rm -rf studio", "source e.sh; cd ~-; rm -rf studio",
                        "source e.sh; cd $OLDPWD; rm -rf studio"):
                self.assertDeny(cmd, "G-DEL", cwd=src)

    def test_relative_paths_after_source(self):
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in G1_REVIEW15_PASS:
                self.assertPass(cmd)
            src = os.path.join(self.repo, "src")
            v = os.path.join(self.repo, "studio/videos/v")
            self.assertDeny("source e.sh && rm -rf studio", "G-DEL", cwd=src)
            self.assertDeny("source e.sh && rm -rf studio/videos/v/work", "G-DEL", cwd=v)
            self.assertDeny("source env.sh && rm -rf studio/videos/v/work", "G-DEL")
            self.assertDeny("source env.sh && rm -rf .", "G-DEL")
            self.assertDeny("source env.sh && rm -rf .claude", "G-DEL")
            self.assertDeny("source env.sh && echo x > studio/videos/v/work/state.json", "G-PROT")

    def test_literal_cd_after_source(self):
        # review 18: a folder change after a source leaves the folder unknown, as at HEAD (git not checked there)
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in ("source env.sh; cd src; git commit -m x", "source env.sh; cd src; rm -rf work",
                        "source env.sh; cd src && npm test; cd ..; git commit -m x", "source env.sh; cd src; git clean -fdx"):
                self.assertPass(cmd)
            self.assertDeny("source env.sh; cd studio/videos/v; rm -rf studio", "G-DEL")


def source_fixture(repo):
    """review 16/17: env files and scripts that delete studio in several folders, a modified script.md, a hook."""
    for d in ("", "src", "studio", "studio/videos/v", "scripts"):
        with open(os.path.join(repo, d, "e.sh"), "w") as f:
            f.write("export A=1\n")
        with open(os.path.join(repo, d, "ev.py"), "w") as f:
            f.write("import shutil\nshutil.rmtree('studio')\n")
    os.makedirs(os.path.join(repo, ".venv", "bin"))
    with open(os.path.join(repo, ".venv", "bin", "activate"), "w") as f:
        f.write("export VIRTUAL_ENV=x\n")
    with open(os.path.join(repo, "studio/videos/v/script.md"), "a") as f:
        f.write("more\n")
    h = os.path.join(repo, ".git", "hooks")
    os.makedirs(h, exist_ok=True)
    with open(os.path.join(h, "pre-commit"), "w") as f:
        f.write("#!/bin/sh\n# studio:hook\n")


class G1Review16(JudgeCase):
    """G1 implementation review 16: after a source, a folder HEAD knew (`cd -`, `popd`, `~-`, `$OLDPWD`) is judged as a
    known folder as well as the unknown one (B16-1/2), also with a hook defined after the source (B16-3); a pushd the
    guard cannot follow leaves popd possible (C16-1/2)."""

    def setUp(self):
        super().setUp()
        source_fixture(self.repo)

    TAILS = (("rm -rf **/v", "G-DEL"), ("setopt globdots; rm -rf **/scripts", "G-DEL"), ("python3 ev.py", "G-OPAQUE"),
             ("cat ev.py | python3", "G-OPAQUE"), ("python3 < ev.py", "G-OPAQUE"),
             ("cat <<'X' > y.py\nimport shutil; shutil.rmtree('studio')\nX\npython3 y.py", "G-OPAQUE"),
             ("ln -sf /tmp/x .git/config", "G-HOOKOFF"), ("ln -sf /tmp/x .git/hooks/pre-commit", "G-PROT"),
             ("git worktree add studio/x", "G-PROT"), ("git init studio/x", "G-PROT"), ("git checkout .", "G-RESET"))

    def test_stale_moves_after_source(self):
        # B16-1: HEAD kept $OLDPWD and the stack through a source — every known-folder rule runs where it went
        for mode in ("with", "none"):
            self.mode = mode
            for pre in ("cd src; source e.sh; ", "pushd src; source e.sh; "):
                for mov in ("cd -", "popd", "cd ~-", "cd $OLDPWD", "cd -q -", "builtin cd -", "cd - >/dev/null"):
                    for tail, rule in self.TAILS:
                        self.assertDeny(pre + mov + "; " + tail, rule)
                self.assertDeny(pre + "( cd -; rm -rf **/v )", "G-DEL")
                self.assertDeny(pre + "cd - && { python3 ev.py; }", "G-OPAQUE")
                self.assertDeny(pre + "if cd -; then python3 ev.py; fi", "G-OPAQUE")
                self.assertDeny(pre + "cd -; cd studio; python3 ev.py", "G-OPAQUE")
                self.assertDeny(pre + "cd -; f(){ :; }; f; python3 ev.py", "G-OPAQUE")
            v = os.path.join(self.repo, "studio/videos/v")
            self.assertDeny("cd ../../../src; source e.sh; cd -; python3 ev.py", "G-OPAQUE", cwd=v)
            self.assertDeny("pushd ../../../src; source e.sh; popd; rm -rf work", "G-DEL", cwd=v)

    def test_oldpwd_words_after_source(self):
        # B16-2: `~-` / `$OLDPWD` in other words and through copies
        for mode in ("with", "none"):
            self.mode = mode
            for mov in ("pushd ~-", "pushd $OLDPWD", "pushd -q ~-", "cd ${OLDPWD}", "cd ~-/.", "cd -- ~-", "cd -P ~-",
                        "X=$OLDPWD; cd $X", "cd ~-/studio; cd .."):
                for tail, rule in self.TAILS:
                    # (git: the folder is also unknown for its own reason here — G-RESET may come first)
                    self.assertDeny("cd src; source e.sh; " + mov + "; " + tail, None if tail.startswith("git") else rule)
            self.assertDeny("cd src; source e.sh; env -C ~- rm -rf **/v", "G-DEL")
            self.assertDeny("cd src; source e.sh; (cd ~-; rm -rf **/v)", "G-DEL")

    def test_hook_after_source(self):
        # B16-3: a hook defined after the source does not stop git from being judged where HEAD judged it
        for mode in ("with", "none"):
            self.mode = mode
            for pre in ("pushd studio/videos/v; source e.sh; ", "cd src; source e.sh; "):
                for hook in ("chpwd(){ :; }; ", "TRAPDEBUG(){ :; }; ", "TRAPZERR(){ :; }; ", "function chpwd { :; }; ",
                             "chpwd(){ echo moved; }; "):
                    for mov in ("cd -", "popd", "cd ~-", "cd $OLDPWD"):
                        if pre.startswith("cd") and mov == "popd":
                            continue
                        self.assertDeny(pre + hook + mov + "; git checkout .", "G-RESET")
                        self.assertDeny(pre + hook + mov + "; git reset --hard", "G-RESET")

    def test_pushd_then_popd(self):
        # C16-1/2: an un-followable pushd pushes the folder it leaves; popd after a source may succeed
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, rule in G1_REVIEW16_DENY:
                self.assertDeny(cmd.replace("<root>", ""), rule)
            for cmd in ("source .venv/bin/activate && pushd src && popd && rm -rf studio/videos/v/work",
                        "source .venv/bin/activate && pushd src >/dev/null && npm test && popd >/dev/null && "
                        "rm -rf studio/videos/v/work",
                        "source .venv/bin/activate && pushd src && pushd ../scripts && popd && popd && rm -rf studio",
                        "source scripts/e.sh && pushd src && popd && rm -rf .claude/studio"):
                self.assertDeny(cmd, "G-DEL")
            self.assertDeny("source .venv/bin/activate && pushd src && popd && echo x > .claude/studio/scripts/state.py",
                            "G-PROT")
            for cmd in G1_REVIEW16_PASS:
                self.assertPass(cmd)


class G1Review17(JudgeCase):
    """G1 implementation review 17: $OLDPWD that is one of several known folders is judged once per folder, as `cd -`
    (B17-1); HEAD's reading after a source inside a function goes on after the call (B17-2); git probes are shared only
    by the readings of one command (B17-3); nested code after a source and `cd -` / `popd` is read where HEAD read it
    (C17-1)."""

    TAILS = G1Review16.TAILS

    def setUp(self):
        super().setUp()
        source_fixture(self.repo)
        for name, text in (("release.sh", "npm test\n"), ("env.sh", "export B=1\n"), ("bad.sh", "rm -rf studio\n")):
            with open(os.path.join(self.repo, "scripts", name), "w") as f:
                f.write(text)

    U_TAILS = (("rm -rf **/v", "G-DEL"), ("ln -sf /tmp/x .git/config", "G-HOOKOFF"),
               ("setopt globdots; rm -rf **/scripts", "G-DEL"))

    def test_oldpwd_union(self):
        # B17-1: a pushd the guard cannot follow (or a cd that may not run) leaves $OLDPWD one of two folders
        for mode in ("with", "none"):
            self.mode = mode
            for pre in ("pushd src; pushd $X; ", 'pushd src; pushd "$1"; ', "cd src; pushd $X; ",
                        "pushd src; pushd $(mktemp -d); ", "pushd src; cdpath=(/tmp); pushd x; ",
                        "cd src; f(){ [[ -n $Z ]] && cd ../scripts; }; f; ", "cd src; [[ -n $Z ]] && cd ../scripts; ",
                        "cd src; cd ../nosuch 2>/dev/null; "):
                self.assertDeny(pre + "rm -rf $OLDPWD/studio", "G-DEL")
                self.assertDeny(pre + "rm -rf ${OLDPWD}/studio/videos/v", "G-DEL")
                self.assertDeny(pre + 'rm -rf "$OLDPWD"/studio', "G-DEL")
                self.assertDeny(pre + "ln -sf /tmp/x $OLDPWD/.git/config", "G-HOOKOFF")
                for mov in ("cd ~-", "cd $OLDPWD", 'cd "$OLDPWD"', "cd ${OLDPWD}", "cd ~-/.", "cd -P ~-", "cd -- ~-",
                            "cd -q ~-", "pushd ~-", "pushd $OLDPWD", "X2=$OLDPWD; cd $X2"):
                    for tail, rule in self.U_TAILS:
                        self.assertDeny(pre + mov + "; " + tail, rule)
                self.assertDeny(pre + "(cd ~-; rm -rf **/v)", "G-DEL")
                self.assertDeny(pre + "env -C ~- rm -rf **/v", "G-DEL")
                self.assertDeny(pre + "cd ~- && ln -sf /tmp/x .git/config", "G-HOOKOFF")

    def test_source_in_function(self):
        # B17-2: the source runs inside a function this call defines; HEAD's reading goes on after the call
        for mode in ("with", "none"):
            self.mode = mode
            for body in ("cd src; source e.sh; cd -", "pushd src; source e.sh; popd", "cd src; . ./e.sh; cd ~-",
                         "cd src; source e.sh; cd $OLDPWD", "cd src; source e.sh; cd - >/dev/null",
                         "local X=1; cd src; source e.sh; cd -; return 0"):
                # (review 18: `{ cd src && source e.sh && cd -; }` — the source may fail, and HEAD did not know the
                # folder after the call: judged as after a source, as at HEAD)
                for call in ("f; ", "f && ", "f >/dev/null; ", "{ f; }; ", "if f; then :; fi; ", "f || true; "):
                    for tail, rule in self.TAILS[:3] + self.TAILS[6:8]:
                        self.assertDeny("f(){ %s; }; %s%s" % (body, call, tail), rule)
                self.assertDeny("function f { %s; }; f; python3 ev.py" % body, "G-OPAQUE")
            # (review 18: `cd src; f(){ source e.sh; cd -; }; f; rm -rf **/v` — HEAD did not know the folder after
            # the call; judged as after a source, as at HEAD)

    def test_nested_after_stale_move(self):
        # C17-1: a nested shell or second source after `cd X && source … && cd -` is read in the folder HEAD knew
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in G1_REVIEW17_PASS:
                self.assertPass(cmd)
            for pre in ("cd src && source ../.venv/bin/activate && cd - && ", "pushd src; source e.sh; popd; "):
                self.assertDeny(pre + "bash scripts/bad.sh", "G-DEL")
                self.assertDeny(pre + "source scripts/bad.sh", "G-DEL")
                self.assertDeny(pre + "bash -c 'rm -rf studio'", "G-DEL")
                self.assertDeny(pre + "eval 'rm -rf studio'", "G-DEL")
                self.assertDeny(pre + "bash $Y", "G-OPAQUE")
            # no folder change after the source: unknown, as at HEAD
            self.assertDeny("source .venv/bin/activate && bash scripts/release.sh", "G-OPAQUE")
            self.assertDeny("source .venv/bin/activate && cd .. && bash scripts/release.sh", "G-OPAQUE")
            for cmd, rule in G1_REVIEW17_DENY:
                self.assertDeny(cmd.replace("<root>", ""), rule)

    def test_git_probe_scope(self):
        # B17-3: a later command does not reuse an earlier command's git probes (HEAD's per-call budget)
        helpers.git(self.repo, "checkout", "--", "studio/videos/v/script.md")
        for cmd in ("git checkout .; git stash pop; git checkout .",
                    "git checkout .; git checkout .; git stash pop; git checkout .",
                    "git reset --hard; git reset --hard; git stash pop; git reset --hard",
                    "git checkout -- studio; git checkout -- studio; git stash apply; git checkout -- studio",
                    "git checkout .; cd src; source e.sh; cd -; git stash pop; git checkout ."):
            self.assertDeny(cmd, "G-RESET")
        # the two readings of one command share them (review 16)
        self.assertPass("cd src; source e.sh; cd -; git checkout .")


class G1Review10(JudgeCase):
    """G1 implementation review 10: hooks, options and functions of the snapshot under the union rule (M1, M2, B2)."""

    def use_snap(self, **kw):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"], **kw))
        self.snap_with = snapmod.load(self.env)
        shutil.rmtree(d)
        self.mode = "with"

    def test_snapshot_hooks(self):
        # M1: a signal trap of yours the guard cannot read runs only on that signal; TRAPEXIT at the end
        self.use_snap(functions=DEFAULT_FUNCS + "TRAPWINCH () {\n\tzle && zle -R\n}\nTRAPEXIT () {\n\tzle -R\n}\n")
        self.assertPass("git status")
        self.assertPass("python3 .claude/studio/scripts/x.py")
        self.assertDeny("rm -rf ~+/studio", "G-DEL")
        # one that runs between commands and cannot be read: the folder is unknown (fail closed)
        self.use_snap(functions=DEFAULT_FUNCS + "TRAPZERR () {\n\tzle -R\n}\n")
        self.assertDeny("rm -rf ~+/studio", "G-DEL")
        self.assertDeny("rm -rf $PWD/studio", "G-DEL")

    def test_snapshot_options(self):
        # M2: an option the snapshot's `setopt` list leaves out is at zsh's default (AUTO_PUSHD off)
        self.use_snap(options=("interactivecomments",))
        for cmd in ("cd <R>; popd; popd; rm -rf studio", "cd <R>; popd 2>/dev/null; rm -rf studio",
                    "cd <R>; popd; rm -rf studio"):
            self.assertDeny(cmd.replace("<R>", self.repo), "G-DEL", cwd=self.tmp)
        self.use_snap(options=("autopushd", "interactivecomments"))
        self.assertPass("cd <R>; popd; rm -rf studio".replace("<R>", self.repo), cwd=self.tmp)
        self.assertDeny("cd <R>; popd; popd; cd <R>; rm -rf studio".replace("<R>", self.repo), "G-DEL", cwd=self.tmp)

    def test_snapshot_function_writes(self):
        # B2: a write that may not run, and a local name, leave the caller's value possible
        funcs = DEFAULT_FUNCS + ("condx () {\n\t[[ -e nope ]] && X=a\n}\nifx () {\n\tif false\n\tthen\n\t\tX=a\n\tfi\n}\n"
                                 "localx () {\n\tlocal X=a\n}\n")
        self.use_snap(functions=funcs)
        for f in ("condx", "ifx", "localx"):
            self.assertDeny("X=studio; %s; rm -rf -- $X" % f, "G-DEL")
            self.assertPass("X=build; %s; rm -rf -- $X" % f)


class G1Review9(JudgeCase):
    """G1 implementation review 9: git in each folder it may run in, commits in several repositories, the directory
    stack after a `pushd` that may not run."""

    def test_folders_that_may_change(self):
        for mode in ("with", "none"):
            self.mode = mode
            self.assertDeny("[[ -e x ]] && cd studio; git clean -fdx", "G-CLEAN")
            self.assertDeny("cd studio > out.log; git stash -a", "G-STASH")
            self.assertPass("[[ -e x ]] && cd src; git status")
            self.assertPass("[[ -e x ]] && pushd src; popd; ls")
            self.assertDeny("[[ -e x ]] && pushd studio; popd; rm -rf local", "G-DEL")
            self.assertPass("cd src > out.log; X=$PWD; ls $X")


class G1Review8(JudgeCase):
    """G1 implementation review 8: M1 with aliases of the snapshot (forms the parser now reads, and text it still
    cannot read that runs an alias whose text deletes or writes)."""

    def test_aliases_after_new_forms(self):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        aliases = list(ALIASES) + REVIEW8_ALIASES
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=aliases, path=self.env["PATH"]))
        self.snap_with = snapmod.load(self.env)
        shutil.rmtree(d)
        self.mode = "with"
        for cmd, rule in REVIEW8_ALIAS_DENY:
            self.assertDeny(cmd, rule)
        for cmd in REVIEW8_ALIAS_UNPARSE:
            self.assertDeny(cmd, "G-UNPARSE")
        self.assertPass("time; gst")


class G1Review7(JudgeCase):
    """G1 implementation review 7: M1, M2 (brackets against Studio's installed hook files)."""

    def test_brackets_and_hook_files(self):
        G1Review6.install_hooks(self)
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, rule in REVIEW7_HOOK_DENY:
                self.assertDeny(cmd, rule)
            for cmd in REVIEW7_HOOK_PASS:
                self.assertPass(cmd)


class G1Review6(JudgeCase):
    """G1 implementation review 6: M12 (wildcards vs Studio's installed hook files) and conf m-1."""

    use = G1Review4.use

    def install_hooks(self):
        d = os.path.join(self.repo, ".git", "hooks")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "pre-commit"), "w") as f:
            f.write("#!/bin/sh\n# studio:hook\n")
        os.makedirs(os.path.join(self.repo, ".husky"), exist_ok=True)
        with open(os.path.join(self.repo, ".husky", "pre-commit"), "w") as f:
            f.write("#!/bin/sh\n# >>> studio:hook >>>\nx\n# <<< studio:hook <<<\n")

    def test_wildcards_and_hook_files(self):
        self.install_hooks()
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, rule in REVIEW6_HOOK_DENY:
                self.assertDeny(cmd, rule)
            for cmd in REVIEW6_HOOK_PASS:
                self.assertPass(cmd)

    def test_extended_glob_after_functions(self):
        self.use(REVIEW4_FUNCS)
        for cmd in REVIEW6_FUNCTION_PASS:
            self.assertPass(cmd)
        for cmd, rule in REVIEW6_FUNCTION_DENY:
            self.assertDeny(cmd, rule)


_R18_SRC = {"e.sh": "export A=1\n", "m.sh": "export A=1\npushd -q ../scripts; popd -q\n", "ok.sh": "export A=1\n"}


class G1Review18(JudgeCase):
    """G1 implementation review 18: `source` / `.` are handled as at HEAD. The source-only machinery of reviews 14-17
    is gone; a command with a source gets HEAD's verdict: git is not checked while the folder is unknown because of
    the source, paths there are read as HEAD read them, and `cd -` / `popd` / `~-` / `$OLDPWD` go where HEAD's walk sent
    them — not to folders only G1 follows (B18-1/B18-3, C18-1/C18-2). B18-2: a nested string run again by another
    command is judged again."""

    def setUp(self):
        super().setUp()
        source_fixture(self.repo)
        for d in ("", "src", "scripts", "studio/videos/v"):
            for name, text in _R18_SRC.items():
                with open(os.path.join(self.repo, d, name), "w") as f:
                    f.write(text)
            with open(os.path.join(self.repo, d, "x.sh"), "w") as f:
                f.write("rm -rf work\n" if d == "studio/videos/v" else "rm -rf ../studio\n" if d == "scripts" else
                        "echo ok\n")
        with open(os.path.join(self.repo, "scripts", "release.sh"), "w") as f:
            f.write("echo release\n")

    def test_head_lists(self):
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, rule in G1_REVIEW18_DENY:
                self.assertDeny(cmd.replace("<root>", ""), rule)
            for cmd in G1_REVIEW18_PASS:
                self.assertPass(cmd)

    def test_attacks_head_refused(self):
        v = "%s/studio/videos/v" % self.repo
        for mode in ("with", "none"):
            self.mode = mode
            # B18-1: a function body run again after a later source (no refusal is dropped any more)
            for body in ("bash x.sh", "bash -c 'rm -rf work'", "source x.sh", "bash < x.sh"):
                self.assertDeny("cd src; source e.sh; f(){ %s; }; cd -; f; cd %s; source e.sh; f" % (body, v), "G-OPAQUE")
            # B18-3: G1 follows the folder through a loop / a function / `set -k`; HEAD did not, and its verdict stays
            for pre in ("for d in src; do cd $d; cd ..; done; ", "for d in src; do pushd -q $d; popd -q; done; ",
                        "f(){ cd src; }; f; cd ..; ", "set -k; "):
                self.assertDeny(pre + "cd src; source m.sh; cd -; bash x.sh", "G-OPAQUE")
            self.assertDeny("set -A dirstack %s; cd src; source m.sh; popd; bash x.sh" % v, "G-OPAQUE")
            # HEAD's $OLDPWD / stack after a source
            for cmd in ("cd src; source e.sh; cd scripts; cd -; git clean -fdx", "pushd src; source e.sh; popd; git clean -fdx",
                        "cd src && source ../.venv/bin/activate && cd - && git clean -fdx"):
                self.assertDeny(cmd, "G-CLEAN")
            for cmd in ("cd src; source e.sh; rm -rf ~-/studio", "cd src; source e.sh; rm -rf $OLDPWD/studio",
                        "cd src; source e.sh; popd; rm -rf **/v", "source e.sh; rm -rf studio"):
                self.assertDeny(cmd, "G-DEL")
            self.assertDeny("source o1.sh; cd -; rm -rf studio", "G-DEL", cwd=os.path.join(self.repo, "src"))
            # a hook defined after the source: the folder HEAD knew is still judged
            self.assertDeny("TRAPDEBUG(){ cd ..; }; cd src; source e.sh; cd -; rm -rf *", "G-DEL")
            self.assertDeny("cd src; source e.sh; chpwd(){ cd ..; }; cd -; git checkout .", "G-RESET")

    def test_everyday_head_passed(self):
        src = os.path.join(self.repo, "src")
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in ("source .venv/bin/activate && git commit -m x", "source e.sh && git status",
                        "cd src && source ../.venv/bin/activate && cd - && bash scripts/release.sh",
                        "cd src && source ../.venv/bin/activate && cd ~- && cd src && source ../.venv/bin/activate && "
                        "cd ~- && bash scripts/release.sh",
                        "source .venv/bin/activate && pushd src && npm test && popd && git add -A && git commit -m x",
                        "(cd src && source ../.venv/bin/activate && npm test && cd -) && git add -A && git commit -m x",
                        "cd src; source m.sh; cd -; bash x.sh", "source e.sh; cd $D; git commit -m x",
                        "cd src; source e.sh; cd -; cd -; git checkout .", "source .venv/bin/activate && git push -u origin HEAD"):
                self.assertPass(cmd)
            for cmd in ("source ok.sh; rm -rf work", "source ../e.sh && python3 ../.claude/studio/scripts/state.py status"):
                self.assertPass(cmd, cwd=src)

    def test_nested_string_per_command(self):
        # B18-2: on a clean tree HEAD probed each `git checkout .` (and refused when its budget ran out); the same string
        # run by another command is judged again (a `git stash pop` between them may bring changes back)
        subprocess.run(["git", "checkout", "-q", "--", "."], cwd=self.repo, check=True)
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in ("sh -c 'git checkout .'; git stash pop; sh -c 'git checkout .'",
                        "sh -c 'git checkout .'; git stash pop; bash -c 'git checkout .'",
                        "sh -c 'git checkout .'; sh -c 'git checkout .'"):
                self.assertDeny(cmd, "G-RESET")
            self.assertPass("sh -c 'git checkout .'")


_R19_FUNCS = """gh () {
	command gh "$@"
}
mkcd () {
	mkdir -p "$1" && cd "$1"
}
up () {
	local n=${1:-1}
	local p=""
	for i in $(seq 1 $n)
	do
		p="../$p"
	done
	cd $p
}
prompt_info () {
	local ref
	ref=$(command git symbolic-ref --short HEAD 2> /dev/null)
	print -r -- "${ref:-detached}"
}
"""


class G1Review19(JudgeCase):
    """G1 implementation review 19: after a source, every decision of the model of HEAD's folder is HEAD's own
    (B19-1 a function call's move, B19-2 a source where HEAD did not know the folder, B19-3 AUTO_PUSHD as HEAD merged
    the snapshot); a plain snapshot wrapper after a source keeps the environment the source's (C19-1); identical nested
    push / commit checks are shared within one call (C19-2) without merging per-command discard checks (B18-2)."""

    def setUp(self):
        super().setUp()
        source_fixture(self.repo)
        for d in ("", "src", "scripts", "studio/videos/v"):
            with open(os.path.join(self.repo, d, "x.sh"), "w") as f:
                f.write("rm -rf work\n" if d == "studio/videos/v" else "echo ok\n")
        os.makedirs(os.path.join(self.repo, "studio/videos/v/work"), exist_ok=True)

    def use_snap(self, **kw):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"], **kw))
        self.snap_with = snapmod.load(self.env)
        shutil.rmtree(d)
        self.mode = "with"

    def test_head_decisions_refused(self):
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, rule in G1_REVIEW19_DENY:
                self.assertDeny(cmd.replace("{R}", self.repo), rule)

    def test_everyday_head_passed(self):
        self.use_snap(functions=DEFAULT_FUNCS + _R19_FUNCS)
        for cmd in G1_REVIEW19_PASS:
            self.assertPass(cmd.replace("{R}", self.repo))
        # a wrapper whose own body exports stays refused (the documented snapshot class; HEAD passed it); after a
        # source the 0.0.26 rules alone judge it (fix20): HEAD's verdict, pass
        self.use_snap(functions=DEFAULT_FUNCS + "runit () {\n\texport NODE_ENV=test\n\t\"$@\"\n}\n")
        self.assertDeny("runit npm test && git status", "G-OPAQUE")
        self.assertPass("source .venv/bin/activate && runit npm test && git status")

    def test_nested_checks_shared(self):
        # C19-2: identical nested pushes are checked once (the same answer); B18-2 stays: discard checks per command
        # fix20 (P20-4): the check is the frozen 0.0.26 one, shared with the 0.0.26 guard: one run for both guards
        from stdo.guard import backstop
        pushmod = backstop._frozen_checks()[0]
        calls = []
        orig = pushmod.check.__wrapped__

        def counting(*a, **kw):
            calls.append(a[2])
            return orig(*a, **kw)
        pushmod.check.__wrapped__ = counting
        try:
            self.assertPass("sh -c 'git push'; sh -c 'git push'; bash -c 'git push'")
        finally:
            pushmod.check.__wrapped__ = orig
        self.assertEqual(len(calls), 1)
        subprocess.run(["git", "checkout", "-q", "--", "."], cwd=self.repo, check=True)
        self.assertDeny("sh -c 'git checkout .'; git stash pop; sh -c 'git checkout .'", "G-RESET")
