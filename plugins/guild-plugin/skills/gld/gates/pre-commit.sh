#!/bin/sh
# Guild commit gate — installed by `/gld init` (refreshed by `/gld update`) to
# `.git/hooks/pre-commit`. This is the AUTHORITATIVE enforcement layer: git runs it with
# the index final, so it sees exactly what is about to be committed — including content
# created inside the same compound command, which the `PreToolUse` layer cannot see.
#
# Chaining (INV4 — additive, never clobbers): if the repo already had a `pre-commit` hook,
# init renames it to `pre-commit.local` and this shim runs it FIRST, preserving its verdict.
# Anything you want to keep running before Guild's checks goes in `pre-commit.local`.
#
# Bypass: `git commit --no-verify` skips this, as it skips every git hook. That is a
# property of the hook model — Guild's gate raises the cost of a mistake, it is not a
# boundary against a determined bypass.
#
# Off-switch: `.claude/guild/config.json` → `gates.enabled: false` (or `/gld config --gates=off`).
set -e

LOCAL_HOOK="$(git rev-parse --git-path hooks/pre-commit.local)"
if [ -x "$LOCAL_HOOK" ]; then
    "$LOCAL_HOOK" "$@" || exit $?
fi

ROOT="$(git rev-parse --show-toplevel)"
GATE="$ROOT/.claude/guild/gates/scripts/gate_precommit.py"

# A missing gate script must not wedge the repo (same fail-open spirit as the script's own
# crash handling). A missing python3, however, means the gate silently never runs — say so.
[ -f "$GATE" ] || exit 0
if ! command -v python3 >/dev/null 2>&1; then
    echo "⚠ Guild 게이트: python3 를 찾을 수 없어 커밋 검사를 건너뜁니다." >&2
    exit 0
fi

exec python3 "$GATE" --git-hook
