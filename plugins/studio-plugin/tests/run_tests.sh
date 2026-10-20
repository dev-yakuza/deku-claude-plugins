#!/usr/bin/env bash
# Runs every Studio test suite.
#   bash plugins/studio-plugin/tests/run_tests.sh           offline, standard library only (skips listed)
#   bash plugins/studio-plugin/tests/run_tests.sh --full    everything; needs STUDIO_TEST_S2V and npx
# See tests/README.md (run --full before every commit).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python3}"
FULL=""
for a in "$@"; do
  case "$a" in
    --full) FULL="--full" ;;
    *) echo "unknown argument: $a"; exit 2 ;;
  esac
done
rc=0
# the real per-user locations must not change during the run: the s2v state folder
# ($S2V_STATE_DIR or ~/.s2v: names, sizes, mtimes), Studio's per-user files in the Claude Code
# config folder ($CLAUDE_CONFIG_DIR or ~/.claude: studio-sandbox.json, studio-backup/), and the
# sha256 of that folder's settings.json, ~/.claude.json and ~/.gitconfig
fingerprint() {
  "$PY" - <<'PYEOF'
import hashlib, os
home = os.path.expanduser("~")
cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
state = os.environ.get("S2V_STATE_DIR") or os.path.join(home, ".s2v")
for r in (state, os.path.join(cfg, "studio-sandbox.json"), os.path.join(cfg, "studio-backup")):
    if not os.path.exists(r):
        print("absent", r); continue
    if os.path.isfile(r):
        st = os.stat(r); print(r, st.st_size, st.st_mtime_ns); continue
    for d, dirs, files in os.walk(r):
        for n in sorted(dirs + files):
            p = os.path.join(d, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            print(p, st.st_size, st.st_mtime_ns)
for f in (os.path.join(cfg, "settings.json"), os.path.join(home, ".claude.json"), os.path.join(home, ".gitconfig")):
    try:
        print(f, hashlib.sha256(open(f, "rb").read()).hexdigest())
    except OSError:
        print("absent", f)
PYEOF
}
before="$(fingerprint)"
echo "== structure"; bash "$HERE/structure_test.sh" || rc=1
echo "== python"
PYTHONDONTWRITEBYTECODE=1 "$PY" -B "$HERE/py/run.py" $FULL || rc=1
after="$(fingerprint)"
if [ "$before" != "$after" ]; then
  echo "FAIL  the run changed real per-user files (s2v state folder, Studio files, settings.json, ~/.claude.json or ~/.gitconfig)."
  echo "      A script2video or Claude Code session running at the same time can also change them: rerun when idle."
  diff <(echo "$before") <(echo "$after") | head -20
  rc=1
fi
exit $rc
