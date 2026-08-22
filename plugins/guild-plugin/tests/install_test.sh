#!/usr/bin/env bash
# Verification for the ENFORCEMENT-LAYER INSTALL that `/gld init` P2 step 6 and `/gld update`
# prescribe, exercised against the repo shapes a real user actually has.
#
# Scope, honestly: this tests the *mechanics* those docs prescribe — that the shipped
# pre-commit.sh chains, fires, and survives a worktree; that a non-executable hook is caught;
# that the settings.json template merges into valid JSON. It cannot test that an LLM follows
# init.md correctly. What it does catch is a prescribed step that is impossible or wrong —
# which is exactly how `git mv` on an untracked hook file (always `fatal: not under version
# control`) and a hardcoded `.git/hooks/` path (a *file*, not a directory, inside a worktree)
# were both found.
#
# Usage: bash plugins/guild-plugin/tests/install_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
GATE="$HERE/../skills/gld/gates/gate_precommit.py"
HOOK="$HERE/../skills/gld/gates/pre-commit.sh"
TMPL="$HERE/../skills/gld/templates/settings.json.tmpl"
for f in "$GATE" "$HOOK" "$TMPL"; do
  [ -f "$f" ] || { echo "missing: $f" >&2; exit 1; }
done
WORK="$(mktemp -d)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s — %s\n' "$1" "$2"; }

# Everything init prescribes, done exactly as prescribed (resolved path, plain mv, chmod).
install_gate() { # cwd = a git repo
  mkdir -p .claude/guild/gates/scripts .claude/guild/memory
  printf '{"gates":{"enabled":true}}' > .claude/guild/config.json
  cp "$GATE" .claude/guild/gates/scripts/gate_precommit.py
  local hp; hp="$(git rev-parse --git-path hooks/pre-commit)"
  mkdir -p "$(dirname "$hp")"
  if [ -f "$hp" ] && ! grep -q gate_precommit.py "$hp"; then
    mv "$hp" "$hp.local"
  fi
  cp "$HOOK" "$hp"
  chmod +x "$hp"
}

new_repo() { # $1 = dir name
  rm -rf "$WORK/$1"; mkdir -p "$WORK/$1"; cd "$WORK/$1"
  git init -q .; git config user.email t@t; git config user.name t
  printf 'hello\n' > README.md
  git add -A >/dev/null 2>&1
  git -c core.hooksPath=/dev/null commit -qm base >/dev/null 2>&1
}

commits() { # returns 0 if a commit of $1 succeeds
  printf 'x\n' >> "$1"; git add "$1" >/dev/null 2>&1
  git commit -qm probe >/dev/null 2>&1
}

echo ""
echo "== A. 기본 설치 =="
new_repo a; install_gate
HP="$(git rev-parse --git-path hooks/pre-commit)"
[ -x "$HP" ] && ok "훅이 실행 가능한 상태로 설치됨" || bad "훅이 실행 가능한 상태로 설치됨" "not executable at $HP"
if commits README.md; then ok "정상 커밋 통과"; else bad "정상 커밋 통과" "blocked"; fi
printf 'SECRET=abc\n' > .env; git add .env >/dev/null 2>&1
if git commit -qm secret >/dev/null 2>&1; then bad "시크릿 커밋 차단" "commit succeeded"; else ok "시크릿 커밋 차단"; fi

echo ""
echo "== B. 실행 권한 없는 훅 (조용한 무력화) =="
new_repo b; install_gate
chmod -x "$(git rev-parse --git-path hooks/pre-commit)"
printf 'SECRET=abc\n' > .env; git add .env >/dev/null 2>&1
if git commit -qm secret >/dev/null 2>&1; then
  ok "chmod 누락 시 게이트가 무력화됨 (init step 4 가 필요한 이유)"
else
  bad "chmod 누락 시 게이트가 무력화됨" "unexpectedly blocked"
fi

echo ""
echo "== C. 기존 훅 보존 + 체이닝 =="
new_repo c
HP="$(git rev-parse --git-path hooks/pre-commit)"
printf '#!/bin/sh\necho "[repo-hook] ran" >&2\nexit 0\n' > "$HP"; chmod +x "$HP"
# git mv 는 여기서 반드시 실패한다 (훅 파일은 버전 관리 대상이 아님)
if git mv --force "$HP" "$HP.local" >/dev/null 2>&1; then
  bad "git mv 는 훅 파일에서 실패해야 함" "git mv unexpectedly succeeded — init.md의 plain mv 지시 재검토"
else
  ok "git mv 는 훅 파일에서 실패 (plain mv 를 쓰는 이유)"
fi
install_gate
[ -f "$HP.local" ] && ok "기존 훅이 pre-commit.local 로 보존됨" || bad "기존 훅이 보존됨" "no .local file"
OUT="$(printf 'y\n' >> README.md; git add README.md >/dev/null 2>&1; git commit -m chain 2>&1)"
case "$OUT" in *"[repo-hook] ran"*) ok "기존 훅이 먼저 실행됨" ;; *) bad "기존 훅이 먼저 실행됨" "no repo-hook output" ;; esac
# 기존 훅이 거부하면 Guild 검사 전에 커밋이 중단되어야 한다
printf '#!/bin/sh\nexit 1\n' > "$HP.local"; chmod +x "$HP.local"
if commits README.md; then bad "기존 훅 거부 시 커밋 중단" "commit succeeded"; else ok "기존 훅 거부 시 커밋 중단"; fi

echo ""
echo "== D. git worktree (.git 이 파일) =="
new_repo d; install_gate
git worktree add -q "$WORK/d-wt" >/dev/null 2>&1
cd "$WORK/d-wt"
[ -f .git ] && ok "worktree 의 .git 은 파일 (하드코딩 경로가 깨지는 이유)" || bad "worktree 의 .git 은 파일" "expected a file"
if [ -d .git/hooks ]; then bad ".git/hooks 리터럴 경로는 worktree 에서 없음" "unexpectedly a directory"; else ok ".git/hooks 리터럴 경로는 worktree 에서 없음"; fi
HPW="$(git rev-parse --git-path hooks/pre-commit)"
[ -x "$HPW" ] && ok "--git-path 로는 훅이 해석됨 (메인 체크아웃 공유)" || bad "--git-path 로 훅 해석" "not found at $HPW"
# worktree 에는 harness 파일이 없다 → 게이트는 fail-open 이어야 한다 (레포를 막지 않음)
if commits README.md; then ok "harness 없는 worktree 에서도 커밋 가능 (fail-open)"; else bad "harness 없는 worktree 커밋" "blocked"; fi
cd "$WORK/d" && git worktree remove --force "$WORK/d-wt" >/dev/null 2>&1

echo ""
echo "== E. core.hooksPath 리디렉션 (husky 계열) =="
new_repo e; install_gate
mkdir -p .husky; git config core.hooksPath .husky
DETECTED="$(git config --get core.hooksPath)"
[ -n "$DETECTED" ] && ok "리디렉션이 감지 가능 (init step 5)" || bad "리디렉션 감지" "empty"
printf 'SECRET=abc\n' > .env; git add .env >/dev/null 2>&1
if git commit -qm secret >/dev/null 2>&1; then
  ok "리디렉션 시 게이트가 실제로 안 뜸 (BLOCKER 로 보고해야 하는 이유)"
else
  bad "리디렉션 시 게이트가 안 뜸" "unexpectedly blocked"
fi

echo ""
echo "== F. 새 클론 = 훅 없음 (update 복구 경로) =="
new_repo f; install_gate
git add -A >/dev/null 2>&1; git commit -qm harness >/dev/null 2>&1
git clone -q "$WORK/f" "$WORK/f-clone" >/dev/null 2>&1
cd "$WORK/f-clone"
[ -f .claude/guild/gates/scripts/gate_precommit.py ] && ok "클론에 harness 파일은 존재" || bad "클론의 harness 파일" "missing"
HPC="$(git rev-parse --git-path hooks/pre-commit)"
if [ -x "$HPC" ]; then bad "클론에 훅은 없어야 함" "hook present"; else ok "클론에 훅 없음 (/gld update 필요)"; fi
git config user.email t@t; git config user.name t
printf 'SECRET=abc\n' > .env; git add .env >/dev/null 2>&1
if git commit -qm secret >/dev/null 2>&1; then
  ok "클론에서 시크릿이 통과 — audit 이 BLOCKER 로 잡아야 하는 상태"
else
  bad "클론 상태 확인" "unexpectedly blocked"
fi
# update 가 하는 일: 훅 재설치
cp "$HOOK" "$HPC"; chmod +x "$HPC"
# ⚠ 여기서 `.env2` 같은 이름을 쓰면 안 된다 — SECRET_PATH_RE 는 `$` 로 앵커돼 있어 `.env` 로
# *끝나야* 매칭된다. `.env2` 는 시크릿이 아니고, 그걸로 테스트하면 게이트가 아니라 테스트가
# 틀린 채로 "차단 실패" 를 보고한다 (실제로 이 스위트를 처음 돌렸을 때 그렇게 나왔다).
printf 'ssh-key-material\n' > id_rsa; git add id_rsa >/dev/null 2>&1
if git commit -qm secret2 >/dev/null 2>&1; then bad "update 후 시크릿 차단" "commit succeeded"; else ok "update 후 시크릿 차단"; fi

echo ""
echo "== G. settings.json 템플릿 =="
python3 - "$TMPL" <<'PY'
import json, sys
raw = open(sys.argv[1]).read()
# 1) 템플릿은 채우기 없이 그대로 유효해야 한다. 예전에는 {{ADDITIONAL_BIN_ENTRIES}} 가
#    선행 쉼표를 포함한 raw JSON 조각이라, 잘못 채우면 settings.json 전체가 파싱 불가가 되고
#    그 안에 실린 게이트 훅까지 함께 죽었다. 조각 플레이스홀더의 재도입을 여기서 막는다.
if "{{" in raw:
    print(f"  FAIL  템플릿에 플레이스홀더 잔존 — {[t for t in raw.split() if '{{' in t][:3]}")
    sys.exit(1)
try:
    d = json.loads(raw)
except Exception as e:
    print(f"  FAIL  템플릿이 그대로 유효 JSON — {e}"); sys.exit(1)
print("  PASS  템플릿이 채우기 없이 그대로 유효 JSON")

hooks = d["hooks"]["PreToolUse"]
cmds = [h["command"] for e in hooks for h in e["hooks"]]
for need, why in [("--guard-config", "guard-config 훅"),
                  ('gate_precommit.py"', "early-warning 훅")]:
    if not any(need in c for c in cmds):
        print(f"  FAIL  {why} 없음"); sys.exit(1)
if not all("timeout" in h for e in hooks for h in e["hooks"]):
    print("  FAIL  훅에 timeout 없음"); sys.exit(1)
if not any("gh pr merge" in a for a in d["permissions"]["ask"]):
    print("  FAIL  INV1(무인 머지 금지) ask 항목 없음"); sys.exit(1)
print(f"  PASS  훅 {len(hooks)}개 · timeout 지정 · ask {len(d['permissions']['ask'])}개 (INV1/INV3)")

# 2) init 이 하는 일: allow 배열에 바이너리 항목을 append. 이미 유효한 문서에 원소를
#    추가하는 것뿐이므로 실패 모드가 없다.
d["permissions"]["allow"].extend(["Bash(flutter:*)", "Bash(npx:*)"])
json.loads(json.dumps(d))
print(f"  PASS  바이너리 append 후에도 유효 (allow {len(d['permissions']['allow'])}개)")
PY
if [ $? -eq 0 ]; then PASS=$((PASS+3)); else FAIL=$((FAIL+1)); fi

echo ""
echo "결과: PASS=$PASS FAIL=$FAIL"
cd /; rm -rf "$WORK"
[ "$FAIL" -eq 0 ]
