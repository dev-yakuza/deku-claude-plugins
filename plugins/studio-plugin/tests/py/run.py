#!/usr/bin/env python3
"""Run Studio's Python tests (m0-plan §1-§2).

Default: offline, standard library only — tests needing script2video (STUDIO_TEST_S2V) or npx
are skipped and listed with their reasons. `--full`: everything runs, and any skip is a failure.
The whole run happens under a temporary HOME / S2V_STATE_DIR / STUDIO_HOME / CLAUDE_CONFIG_DIR.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main(argv):
    full = "--full" in argv
    os.environ["STUDIO_TEST_FULL"] = "1" if full else "0"
    try:
        import helpers  # checks for leaked lock tokens on import
    except RuntimeError as e:  # helpers.LeakedToken
        print("FAIL  %s" % e)
        return 1

    # resolve the s2v checkout before HOME is swapped (it may be given relative to the real home)
    value = os.environ.get(helpers.S2V_ENV)
    if value:
        os.environ[helpers.S2V_ENV] = os.path.abspath(os.path.expanduser(value))
    if full:
        missing = []
        if not os.environ.get(helpers.S2V_ENV):
            missing.append("%s (absolute path of a built script2video checkout)" % helpers.S2V_ENV)
        if not shutil.which("npx"):
            missing.append("npx on PATH")
        if missing:
            print("FAIL  --full needs: " + "; ".join(missing))
            return 1

    # the real home, for tests that check they do not run in it
    os.environ["STUDIO_TEST_REAL_HOME"] = os.path.realpath(os.path.expanduser("~"))
    if full and not os.environ.get("STUDIO_TEST_DENY_TERMS_FILE"):
        print("warning: STUDIO_TEST_DENY_TERMS_FILE is not set: shipped files were not checked for denied terms")
    root = tempfile.mkdtemp(prefix="studio-run-")
    try:
        env = helpers.isolated_env(root)
        os.environ.clear()
        os.environ.update(env)
        suite = unittest.defaultTestLoader.discover(HERE, pattern="test_*.py", top_level_dir=HERE)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    if result.skipped:
        print("\nskipped %d:" % len(result.skipped))
        reasons = {}
        for test, reason in result.skipped:
            reasons.setdefault(reason, []).append(test.id())
        for reason, tests in sorted(reasons.items()):
            print("  %d × %s" % (len(tests), reason))
    if full and result.skipped:
        print("FAIL  --full does not allow skipped tests")
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
