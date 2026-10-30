#!/usr/bin/env python3
"""The inspect table (m1-plan §12.3, M8): which hash each kind of edit changes in real s2v `inspect --json`.

    fake_table.py <s2v repo>            print what real s2v changes for every edit (S2V_TTS=mock, an isolated HOME)
    fake_table.py <s2v repo> --write    also write tests/py/drivers/fake_s2v_cli/fake_inspect_table.json

Real s2v's inspect reads files and hashes them (it runs `ffmpeg -version` and git, no server, no model). The edits are
applied one at a time to a synthetic script; the groups compared are content · voice · presentation (of the output
`youtube`) · engine. The `--full` test (test_m1j.FakeTable) checks that real s2v still gives the checked-in table and
that the fake s2v changes the same groups for the same edits."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
TABLE = os.path.normpath(os.path.join(HERE, "..", "py", "drivers", "fake_s2v_cli", "fake_inspect_table.json"))
FAKE = os.path.normpath(os.path.join(HERE, "..", "py", "drivers", "fake_s2v_cli"))

BASE = """---
title: 공항 단어
lang: ko
cast:
  narrator: { voice: "qwen:Sohee", style: "차분하게" }
outputs:
  youtube: { aspect: "16:9" }
---

# 시작 {#intro}

narrator: 안녕하세요. 오늘은 공항 단어를 배워요.

:::quote
空港
:::

::image{src="a.png"}

::image{src=b.png}

:::split
![사진](c.png)

공항 안내
:::

:::gallery
![하나](d.png)
![둘](e.png)
:::

# 끝 {#end}

narrator: 고마워요!
"""
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000100ffff03000006000557bfabd40000000049454e44ae426082")


def _fm(text, line):
    return text.replace("outputs:\n", line + "\noutputs:\n", 1)


# (name, table place, edit of the script text, edit of the files: {name: bytes})
EDITS = [
    ("paragraph", ("body", "paragraph"), lambda t: t.replace("오늘은 공항", "오늘도 공항"), None),
    ("scene_title", ("body", "scene_title"), lambda t: t.replace("# 시작 {#intro}", "# 처음 {#intro}"), None),
    ("screen", ("body", "screen"), lambda t: t.replace("空港\n:::", "空港です\n:::"), None),
    ("image", ("body", "image"), None, {"a.png": PNG + b"\0"}),
    # M1j review A3: an unquoted src, and the markdown images of :::split and :::gallery (s2v parse.ts)
    ("image_unquoted", ("body", "image"), None, {"b.png": PNG + b"\0"}),
    ("image_split", ("body", "image"), None, {"c.png": PNG + b"\0"}),
    ("image_gallery", ("body", "image"), None, {"d.png": PNG + b"\0"}),
    ("title", ("frontmatter", "title"), lambda t: t.replace("title: 공항 단어", "title: 공항 단어들"), None),
    ("cast.voice", ("frontmatter", "cast"), lambda t: t.replace("qwen:Sohee", "qwen:Ryan"), None),
    ("cast.style", ("frontmatter", "cast"), lambda t: t.replace("차분하게", "밝게"), None),
    ("pronounce", ("frontmatter", "pronounce"), lambda t: _fm(t, "pronounce:\n  공항: 콩항"), None),
    ("pacing", ("frontmatter", "pacing"), lambda t: _fm(t, "pacing:\n  maxPause: 0.5"), None),
    ("theme", ("frontmatter", "theme"), lambda t: _fm(t, "theme: dark"), None),
    ("transition", ("frontmatter", "transition"), lambda t: _fm(t, "transition: fade"), None),
    ("logo", ("frontmatter", "logo"), lambda t: _fm(t, 'logo: { src: "a.png" }'), None),
    ("outputs", ("frontmatter", "outputs"), lambda t: t.replace('  youtube: { aspect: "16:9" }\n',
                                                               '  youtube: { aspect: "16:9" }\n'
                                                               '  shorts: { aspect: "9:16" }\n'), None),
    ("targetDuration", ("frontmatter", "targetDuration"), lambda t: _fm(t, "targetDuration: 30"), None),
    ("maxDuration", ("output_attrs_ignored", "maxDuration"),
     lambda t: t.replace('youtube: { aspect: "16:9" }', 'youtube: { aspect: "16:9", maxDuration: 300 }'), None),
    ("unknown", ("unknown", "unknownKey"), lambda t: _fm(t, "unknownKey: 1"), None),
]
GROUPS = ("content", "voice", "presentation", "engine")
IMAGES = ("a.png", "b.png", "c.png", "d.png", "e.png")


def isolated_env(home):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("S2V_", "CLAUDE", "ANTHROPIC"))}
    env.update(HOME=home, S2V_TTS="mock", S2V_NO_OPEN="1", S2V_STATE_DIR=os.path.join(home, "s2v-state"))
    return env


def inspect(s2v, script, env):
    r = subprocess.run(["node", os.path.join(s2v, "packages", "cli", "dist", "main.js"), "inspect", script, "--json"],
                       capture_output=True, text=True, env=env, timeout=300)
    if r.returncode != 0:
        raise RuntimeError("inspect failed (%d): %s" % (r.returncode, r.stderr.strip()[-800:]))
    return json.loads(r.stdout)


def groups(h):
    return {"content": h["hashes"]["content"], "voice": h["hashes"]["voice"],
            "presentation": (h["hashes"].get("presentation_by_output") or {}).get("youtube"),
            "engine": json.dumps(h["hashes"].get("engine"), sort_keys=True)}


def measure(s2v, env=None, work=None):
    """{edit name: sorted changed groups}."""
    own = work is None
    work = work or tempfile.mkdtemp(prefix="studio-fake-table-")
    env = env or isolated_env(os.path.join(work, "home"))
    os.makedirs(env["HOME"], exist_ok=True)
    try:
        repo = os.path.join(work, "repo")
        os.makedirs(os.path.join(repo, "studio", "voices"), exist_ok=True)
        subprocess.run(["git", "init", "-q", repo], check=True)
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(vdir, exist_ok=True)
        script = os.path.join(vdir, "script.ko.md")

        def put(text, files):
            with open(script, "w", encoding="utf-8") as f:
                f.write(text)
            all_files = {n: PNG for n in IMAGES}
            all_files.update(files or {})
            for n, b in all_files.items():
                with open(os.path.join(vdir, n), "wb") as f:
                    f.write(b)
        put(BASE, None)
        base = groups(inspect(s2v, script, env))
        out = {}
        for name, _place, et, ef in EDITS:
            put(et(BASE) if et else BASE, ef)
            try:
                now = groups(inspect(s2v, script, env))
            except RuntimeError:
                out[name] = ["error"]  # inspect refuses the script (an unknown frontmatter key)
                continue
            out[name] = sorted(g for g in GROUPS if now[g] != base[g])
        return out
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)


def table(results, old=None):
    """The fake's table from measured results (keys the edits do not measure are kept from `old`)."""
    t = {"schema": 1,
         "about": "Which inspect hash each kind of edit changes, measured on real s2v (S2V_TTS=mock) by "
                  "tests/tools/fake_table.py --write (m1-plan §12.3). Frontmatter keys missing here change no hash; "
                  "keys marked unmeasured come from the hand-written M1b table.",
         "frontmatter": dict((old or {}).get("frontmatter") or {}), "output_attrs_ignored": [], "body": {}}
    measured = set()
    for name, (where, key), _e, _f in EDITS:
        changed = [g for g in results[name] if g in ("content", "voice", "presentation")]
        if results[name] == ["error"]:
            if where != "unknown":
                raise RuntimeError("inspect refused the edit %r" % name)
            t["unknown_keys_refused"] = True  # real inspect exits 1 on a frontmatter key it does not know
            continue
        if where == "body":
            # one place for every form of an image (::image quoted or not, :::split, :::gallery): they must agree
            if key in t["body"] and t["body"][key] != changed:
                raise RuntimeError("the forms of body.%s change different groups: %s / %s" % (key, t["body"][key],
                                                                                            changed))
            t["body"][key] = changed
        elif where == "frontmatter":
            t["frontmatter"][key] = sorted(set(t["frontmatter"].get(key, [])) | set(changed)) if key in measured \
                else changed
            measured.add(key)
        elif where == "output_attrs_ignored" and not changed:
            t["output_attrs_ignored"].append(key)
    t["unmeasured"] = sorted(k for k in t["frontmatter"] if k not in measured)
    return t


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    res = measure(os.path.abspath(argv[0]))
    for k, v in res.items():
        print("%-16s %s" % (k, " ".join(v) or "-"))
    if "--write" in argv:
        with open(TABLE, encoding="utf-8") as f:
            old = json.load(f)
        with open(TABLE, "w", encoding="utf-8") as f:
            json.dump(table(res, old), f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("wrote %s" % TABLE)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
