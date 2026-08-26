#!/usr/bin/env bash
# Structural checks over the prompt Markdown in skills/gld/.
#
# Test 2 — calibration-core identity. The external auditor is spawned from two places:
# `commands/atoms/_execute_spine.md` Step 3.5a (pre-PR) and `commands/review.md` Step 2.5
# (post-PR). The two prompts are deliberately duplicated, not shared, and the spine states
# the contract: they must stay "calibrated identically". The severity/axis definitions are
# fenced in both copies by `<!-- guild:severity-core -->` … `<!-- /guild:severity-core -->`
# so a drift in one copy is caught here instead of showing up as a systematic offset in the
# severity distribution the two stages are supposed to be comparable across.
#
# Each core line carries the enclosing blockquote's `  > ` prefix; the comparison strips
# that prefix and trailing whitespace, so re-wrapping the blockquote does not fail the test
# but changing a word does. The stage-consequence line is deliberately OUTSIDE the markers —
# it is the one intended difference between the copies.
#
# Usage: bash plugins/guild-plugin/tests/prompt_structure_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
GLD="${1:-$HERE/../skills/gld}"
[ -d "$GLD" ] || { echo "missing: $GLD" >&2; exit 1; }
SPINE="$GLD/commands/atoms/_execute_spine.md"
REVIEW="$GLD/commands/review.md"
for f in "$SPINE" "$REVIEW"; do
  [ -f "$f" ] || { echo "missing: $f" >&2; exit 1; }
done
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s (expected %s, got %s)\n' "$1" "$2" "$3"; }

echo ""
echo "== 2. 감사자 캘리브레이션 코어 동일성 =="

OUT="$(python3 - "$SPINE" "$REVIEW" <<'PY'
import re, sys

OPEN  = '<!-- guild:severity-core -->'
CLOSE = '<!-- /guild:severity-core -->'
PREFIX = re.compile(r'^  > ?')

def extract(path):
    """Return (opens, closes, core_lines_or_None) for one file."""
    lines = open(path, encoding='utf-8').read().split('\n')
    opens  = [i for i, l in enumerate(lines) if OPEN in l]
    closes = [i for i, l in enumerate(lines) if CLOSE in l]
    if len(opens) != 1 or len(closes) != 1:
        return opens, closes, None
    if closes[0] < opens[0]:
        return opens, closes, None
    body = lines[opens[0] + 1:closes[0]]
    return opens, closes, [PREFIX.sub('', l).rstrip() for l in body]

results = {}
for path in sys.argv[1:3]:
    results[path] = extract(path)

# marker pairs: 0 or 1 per file, and never a lone marker
for path, (opens, closes, core) in results.items():
    n_open, n_close = len(opens), len(closes)
    if n_open > 1 or n_close > 1:
        print('MARKERS_FAIL %s open=%d close=%d' % (path, n_open, n_close))
        raise SystemExit
    if n_open != n_close:
        print('MARKERS_FAIL %s open=%d close=%d' % (path, n_open, n_close))
        raise SystemExit
    if n_open == 1 and core is None:
        print('MARKERS_FAIL %s close-before-open' % path)
        raise SystemExit
print('MARKERS_OK')

spine, review = sys.argv[1], sys.argv[2]
sc = results[spine][2]
rc = results[review][2]

if sc is None and rc is None:
    # Neither copy carries the core yet — the pre-D3a state. Nothing to compare.
    print('CORE_ABSENT')
    raise SystemExit
if sc is None or rc is None:
    print('CORE_ONE_SIDED %s' % ('review only' if sc is None else 'spine only'))
    raise SystemExit
if not sc:
    print('CORE_EMPTY')
    raise SystemExit
if sc == rc:
    print('CORE_IDENTICAL %d' % len(sc))
    raise SystemExit

print('CORE_DIFFERS')
import difflib
for d in list(difflib.unified_diff(sc, rc, 'spine', 'review', lineterm='', n=1))[:24]:
    print('  ' + d)
PY
)"

case "$OUT" in
  *MARKERS_OK*) ok "마커 쌍이 파일당 0개 또는 1개" ;;
  *)            bad "마커 쌍이 파일당 0개 또는 1개" "0 or 1 pair" "$(printf '%s' "$OUT" | tr '\n' ' ')" ;;
esac

case "$OUT" in
  *CORE_IDENTICAL*) ok "두 사본의 코어가 바이트 동일 ($(printf '%s' "$OUT" | sed -n 's/.*CORE_IDENTICAL \([0-9]*\).*/\1/p')줄)" ;;
  *CORE_ABSENT*)    ok "두 사본 모두 코어 없음 (도입 전 상태)" ;;
  *MARKERS_FAIL*)   : ;;
  *)                bad "두 사본의 코어가 바이트 동일" "identical cores" "$(printf '%s' "$OUT" | tr '\n' ' ')" ;;
esac

echo ""
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
