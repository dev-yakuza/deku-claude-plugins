"""`validate_copy.py <video> --platform <p> [--lang l]` (m1-plan §10) → `checks/copy--<p>.json`.

Exit: 0 pass · 1 fail (the result lists why) · 2 usage or setup (no harness, no video, platform not in the brief)."""

import os
import sys

from .. import writes
from ..claims import cli as ccli
from ..state import cli as scli, commands as C, schema, stagechecks
from . import check


def main(argv, cwd=None, env=None):
    env = dict(os.environ if env is None else env)
    try:
        if "--platform" not in argv or argv.index("--platform") + 1 >= len(argv):
            raise ccli.Usage("validate_copy.py <video> --platform <p> [--lang l]")
        i = argv.index("--platform")
        platform, rest = argv[i + 1], argv[:i] + argv[i + 2:]
        o, repo, vdir, state, lang, ctx = ccli._setup(rest, cwd or os.getcwd())
        if not schema.platform_ok(platform, state.get("kind")) or platform not in schema.current_platforms(state, lang):
            raise ccli.Usage("platform %r is not a platform of this video's brief" % (platform,))
        cfg = scli._cfg_of(repo)
        L = state["langs"][lang]
        p = L["copies"].get(platform, {}).get("path") or os.path.join(
            ctx["studio_root"], "copy", state["video"], lang, platform + ".md")
        copy_path = p if os.path.isabs(p) else os.path.join(repo, p)
        problems = check.problems(repo, vdir, state, lang, ctx, platform, cfg, env, copy_path)
    except ccli.Usage as e:
        sys.stderr.write("std validate_copy: %s\n" % e)
        return C.USAGE
    except schema.SchemaError as e:
        sys.stderr.write("std validate_copy: %s\n" % e)
        return e.code or C.USAGE
    result = "fail" if problems else "pass"
    inp = stagechecks.Inputs(ctx, state, lang, platform)
    path = stagechecks.write(vdir, lang, "copy", platform, result, {"problems": problems},
                             stagechecks.input_sha("copy", inp))
    ccli._report("copy", result, problems, os.path.relpath(path, repo))
    return C.OK if result == "pass" else C.FAIL


def entry():
    writes.enable()  # the check result (P-STATE) is written from this entry
    return main(sys.argv[1:])
