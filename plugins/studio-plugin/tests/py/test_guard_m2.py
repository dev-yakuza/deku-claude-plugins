"""The guard's capture rules (m2-plan §5.2, G1 only): `s2v capture` in every accepted s2v form only through capture.py
(G-WRAP), S2V_CAPTURE_NO_SANDBOX on an s2v, lock.py or capture.py call (G-ENV), capture.py's results protected
(P-STATE: a video's `assets/`, `work/captures/`, `work/captures.json`, `work/source-diff.txt`; their literal twins
through TAIL_NAMES), each refusal plain and after a `source` (class S); capture.py itself passes. Its allow without a
prompt is in test_guard_autoallow."""

import os

from test_guard_judge import JudgeCase

S = ".claude/studio/scripts/"
SOURCED = "source ./env.sh; "
URL = "https://example.com/a"

DENY = [
    ("s2v capture %s --out a.png" % URL, "G-WRAP"),
    ("s2v capture %s --out a.png --text a.json --timeout 30" % URL, "G-WRAP"),
    ("s2v --json capture %s --out a.png" % URL, "G-WRAP"),
    ("node {P}/packages/cli/dist/main.js capture %s --out a.png" % URL, "G-WRAP"),
    ("yarn --cwd {P} s2v capture %s --out a.png" % URL, "G-WRAP"),
    ("tsx {P}/packages/cli/src/main.ts capture %s --out a.png" % URL, "G-WRAP"),
    ("S2V_CAPTURE_NO_SANDBOX=1 python3 %scapture.py shot v hero --url %s" % (S, URL), "G-ENV"),
    ("S2V_CAPTURE_NO_SANDBOX=1 python3 %scapture.py source v" % S, "G-ENV"),
    ("env S2V_CAPTURE_NO_SANDBOX=1 python3 %scapture.py source v" % S, "G-ENV"),
    ("S2V_CAPTURE_NO_SANDBOX=1 s2v render studio/videos/v/script.md --output youtube", "G-ENV"),
    ("S2V_CAPTURE_NO_SANDBOX=1 python3 %slock.py status" % S, "G-ENV"),
    ("cp a.txt studio/videos/v/assets/a.png", "G-PROT"),
    ("cp a.txt studio/local/videos/w/assets/a.png", None),
    ("rm -rf studio/videos/v/assets", None),
    ("rm -rf studio/videos/v/work/captures", None),
    ("rm -f studio/videos/v/work/captures/hero.json", None),
    ("echo {} > studio/videos/v/work/captures.json", "G-PROT"),
    ("echo x > studio/videos/v/work/source-diff.txt", "G-PROT"),
    ("mv a.txt studio/videos/v/work/captures.json", None),
    ("rm -f studio/videos/v/work/captures.json$X", None),
    ("rm -rf studio/videos/v/assets$X", None),
    ("rm -rf studio/videos/v/work/captures$X", None),
    ("rm -f studio/videos/v/work/source-diff.txt$X", None),
    ("rm -rf studio/videos/v/$X", None),
    # review 1 M1: below a video, also through a folder the guard cannot tell
    ("rm -rf $X/videos/v/assets", "G-DEL"), ("rm -rf $X/studio/videos/v/work/captures", "G-DEL"),
    ("cp a.txt \"$D/videos/v/assets/a.png\"", None), ("rm -rf studio/local/videos/w/assets", None),
    # review 2: the video id from a command substitution
    ("rm -rf studio/videos/$(echo v)/assets", None), ("cp a.txt studio/videos/$(echo v)/assets/a.png", None),
    ("rm -rf studio/videos/`echo v`/assets", None), ("rm -rf studio/videos/$(echo v)/work/captures", None),
    ("cp a.txt studio/local/videos/$(echo w)/assets/a.png", None),
]
# review 1 M1: `assets` and `captures` are common build folders — refused only below a video (all pass at HEAD)
BUILD_PASS = [
    "rm -rf $OUT/assets", "rm -rf build/$NAME/assets", "for d in a b; do rm -rf $d/assets; done",
    "cp a.txt \"$D/assets/a.png\"", "rm -rf /tmp/*/assets", "rm -rf $OUT/captures", "rm -rf dist/assets",
    "ln -s a.txt $D/assets", "rm -rf build/$(echo x)/assets", "rm -rf `echo out`/assets",
]
PASS = [
    "python3 %scapture.py source v" % S,
    "python3 %scapture.py shot v hero --url %s" % (S, URL),
    "python3 %scapture.py shot v hero --url %s --selector main --width 1080 --height 1920" % (S, URL),
    "cat studio/videos/v/work/captures.json",
    "ls studio/videos/v/assets",
    "env -u S2V_CAPTURE_NO_SANDBOX python3 %scapture.py source v" % S,
]


class CaptureGuard(JudgeCase):
    def setUp(self):
        super().setUp()
        for d in ("studio/videos/v/assets", "studio/videos/v/work/captures", "studio/local/videos/w/assets"):
            os.makedirs(os.path.join(self.repo, d), exist_ok=True)
        with open(os.path.join(self.repo, "env.sh"), "w") as f:
            f.write("export STUDIO_TEST_A=1\n")
        from stdo import machine
        self.p = machine.s2v_path(self.repo)

    def rows(self, rows):
        return [(c.replace("{P}", self.p), r) for c, r in rows]

    def test_deny(self):
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, rule in self.rows(DENY):
                self.assertDeny(cmd, rule)
                self.assertDeny(SOURCED + cmd)  # class S: the frozen guard's verdict joins, this guard's stays

    def test_pass(self):
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in PASS:
                self.assertPass(cmd)
        self.assertDeny("s2v capture --help", "G-WRAP")  # any capture call, its help too

    def test_build_folders_named_assets(self):
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in BUILD_PASS:
                self.assertPass(cmd)

    def test_file_tools(self):
        for rel in ("studio/videos/v/assets/a.png", "studio/videos/v/work/captures.json",
                    "studio/videos/v/work/captures/hero.json", "studio/videos/v/work/source-diff.txt",
                    "studio/local/videos/w/assets/a.png"):
            p = os.path.join(self.repo, rel)
            d = self.decide("Write", {"file_path": p, "content": "x"})
            self.assertIsNotNone(d, rel)
            self.assertEqual(d.rule, "G-PROT", rel)
            d = self.decide("Edit", {"file_path": p, "old_string": "a", "new_string": "b"})
            self.assertIsNotNone(d, rel)
        # the video's other files stay the writer's
        self.assertIsNone(self.decide("Write", {"file_path": os.path.join(self.repo, "studio/videos/v/notes.md"),
                                                "content": "x"}))

    def test_messages(self):
        d = self.assertDeny("s2v capture %s --out a.png" % URL, "G-WRAP")
        self.assertIn("capture.py", d.message())
        d = self.assertDeny("S2V_CAPTURE_NO_SANDBOX=1 python3 %scapture.py source v" % S, "G-ENV")
        self.assertIn("browser sandbox", d.message())
