#!/usr/bin/env bash
# Verification for `persona_migrate.py` — the script `/gld update --migrate-personas` runs to
# draw the central/local boundary in personas that predate the marker pair
# (design: design/guild/01-persona-merge.md §7.3·§7.4·§7.4a).
#
# WHAT IS ACTUALLY AT RISK. `--mode insert` cannot lose anything: it inserts three lines and
# never moves or deletes one. The damage happens one `update` LATER, when the marker region is
# replaced — and only if a marker landed in the wrong place. So the failure this suite exists
# to catch is silent at the moment it is made and destructive after the next release.
#
# That is why the check cases are MUTATIONS. A `--mode check` that passes on a good file proves
# nothing about what it would see on a bad one; every FAIL case below breaks the file in one
# specific way and asserts the script says so. The sharpest pair is C13/C14: a mis-placed end
# marker is LOSSLESS — every original line is still present — so the lossless check passes and
# only the anchor check catches it. If those two ever collapse into one, the migration ships a
# blind spot with a green suite over it.
#
# Usage: bash plugins/guild-plugin/tests/persona_migrate_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PM="$HERE/../skills/gld/commands/atoms/persona_migrate.py"
[ -f "$PM" ] || { echo "missing: $PM" >&2; exit 1; }
PY="${PY:-python3}"
# ⚠ FUNCTIONAL probe, not `command -v`: an interpreter that exists but cannot run (broken venv,
# a shim that exits non-zero) otherwise reports as script failure with an empty diagnostic.
"$PY" -c "pass" >/dev/null 2>&1 || { echo "SKIP: $PY is not usable — this suite is python-based" >&2; exit 0; }
command -v git >/dev/null 2>&1 || { echo "SKIP: git not available" >&2; exit 0; }

WORK="$(mktemp -d)" || { echo "mktemp -d failed" >&2; exit 1; }
[ -n "$WORK" ] && [ -d "$WORK" ] || { echo "mktemp -d gave no directory" >&2; exit 1; }
trap 'cd /; rm -rf "$WORK"' EXIT

# ⚠ ALWAYS exported inside a git hook, and this plugin installs hooks. The fixture below is a
# real git repo and the script shells out to git; an inherited GIT_DIR would point every one of
# those calls at the wrong repository.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
unset GIT_CONFIG GIT_CONFIG_COUNT

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s — %s\n' "$1" "$2"; }
eq()  { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected [$2], got [$3]"; fi; }
has() { case "$2" in *"$3"*) ok "$1";; *) bad "$1" "expected to contain [$3], got [$2]";; esac; }
hasnt() { case "$2" in *"$3"*) bad "$1" "should not contain [$3], got [$2]";; *) ok "$1";; esac; }

# 모든 픽스처는 자기 중앙 템플릿을 함께 만든다. `--templates`는 이제 판별과 `insert --init`의
# **필수** 인자다 — 빠지면 유일한 거짓-T1 탐지기가 조용히 꺼지고, 그것이 라운드 3의 BLOCKER였다.
TPL="$WORK/tpl"; mkdir -p "$TPL"; export TPLDIR="$TPL"
tpl_for() {
  cat > "$TPL/$1" <<'MD'
---
name: x
description: x
---

# 제목 — {{PROJECT_NAME}}

<!-- guild:persona:start -->
## 책임
- 중앙.

## 작업 방식
- 중앙.
<!-- guild:persona:end -->

## 프로젝트 특화
- (아직 없음)

## 역할 습관
<!-- guild:persona:habits -->
- (아직 없음)
MD
}

# ── 픽스처 ───────────────────────────────────────────────────────────────
# One persona in the shape init renders: frontmatter, H1, blank, central body, anchor, local
# section. `persona()` writes a fresh copy so each case starts from the same known file.
persona() {
  tpl_for "$(basename "$1")"
  cat > "$1" <<'MD'
---
name: infra
description: 인프라 담당
model: sonnet
---

# 인프라 — 데모

## 책임
- 배포 파이프라인을 유지한다.
- 비밀값을 관리한다.

## 작업 방식
- 변경은 항상 롤백 경로와 함께 낸다.

## 프로젝트 특화
- (아직 없음)
MD
}

cd "$WORK" || exit 1
git init -q repo || exit 1
cd repo || exit 1
git config user.email t@t; git config user.name t; git config commit.gpgsign false
mkdir -p .claude/agents
persona .claude/agents/infra.md
persona .claude/agents/dba.md
persona .claude/agents/qa.md
persona .claude/agents/late.md
git add -A; git commit -qm init
INIT="$(git rev-parse HEAD)"
# `late.md` is added again in a second commit so C4 has a file whose add-commit is not INIT.
git rm -q --cached .claude/agents/late.md; rm .claude/agents/late.md
git commit -qm "drop late"
persona .claude/agents/late.md
git add -A; git commit -qm "re-add late"

echo ""
echo "== classify: 어느 역할이 기계적인가 =="

# C2 — growth BELOW the anchor is local either way, so it does not make the file T2.
printf -- '- 스테이징 배포는 수동 승인이다.\n' >> .claude/agents/dba.md
# C3 — growth INSIDE the central region: the marker pair would replace it, so a human must look.
"$PY" - <<'PYX'
import io
p='.claude/agents/qa.md'; s=io.open(p,encoding='utf-8').read()
s=s.replace("- 비밀값을 관리한다.\n", "- 비밀값을 관리한다.\n- 로컬에서 자란 줄.\n")
io.open(p,'w',encoding='utf-8').write(s)
PYX
git add -A; git commit -qm growth

C="$("$PY" "$PM" --mode classify --init "$INIT" --templates "$TPL")"
eq "C1 변경 없음 → T1"                 "T1"  "$(echo "$C" | awk '/infra.md/{print $2}')"
eq "C2 앵커 아래 성장 → T1"            "T1"  "$(echo "$C" | awk '/dba.md/{print $2}')"
eq "C3 중앙 영역 성장 → T2"            "T2"  "$(echo "$C" | awk '/qa.md/{print $2}')"
has "C4 init 커밋 소생이 아니면 HITL"   "$(echo "$C" | awk '/late.md/{print $2}')" "HITL"

# C5 — an ambiguous boundary. Two H1s means two candidate openings for the central region, so
# there is no mechanical answer; the script must say HITL rather than pick one.
printf -- '\n# 두 번째 제목\n' >> .claude/agents/infra.md
git add -A; git commit -qm "second h1"
has "C5 H1 두 개 → HITL" "$("$PY" "$PM" --mode classify --init "$INIT" --templates "$TPL" | awk '/infra.md/{print $2}')" "HITL"
git reset -q --hard HEAD~1

# C6 — a PURE DELETION inside the central region. `@@ -n +m,0 @@` touches no line in the new
# file, so a naive reader sees an empty range and calls it T1 — and the deleted line is then
# silently restored by the next update. hunk_lines() records the straddling pair for this.
"$PY" - <<'PYX'
import io
p='.claude/agents/infra.md'; s=io.open(p,encoding='utf-8').read()
io.open(p,'w',encoding='utf-8').write(s.replace("- 비밀값을 관리한다.\n",""))
PYX
git add -A; git commit -qm "delete central line"
eq "C6 중앙 영역 순수 삭제 → T2" "T2" "$("$PY" "$PM" --mode classify --init "$INIT" --templates "$TPL" | awk '/infra.md/{print $2}')"

echo ""
echo "== insert: 마커 세 줄, 그 외에는 아무것도 =="

git checkout -q -- . ; git reset -q --hard "$INIT" >/dev/null
BASE="$(git rev-parse HEAD)"
OUT="$("$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/infra.md 2>&1)"; RC=$?
eq "C7 삽입 성공 rc" "0" "$RC"
eq "C7 start는 H1 다음 빈 줄 아래" "9" "$(grep -n 'guild:persona:start' .claude/agents/infra.md | cut -d: -f1)"
eq "C7 end 바로 아래가 앵커" "## 프로젝트 특화" \
   "$(awk '/persona:end/{f=1;next} f&&/^## /{print;exit}' .claude/agents/infra.md)"
# C11 — insert is lossless BY CONSTRUCTION (it only inserts). Asserted anyway, and asserted
# WITHOUT the script: C12 below runs the script's own lossless check, so a broken check would
# only agree with itself. This one compares the two blobs directly.
git show "$BASE:.claude/agents/infra.md" > "$WORK/before.txt"
eq "C11 원본 줄 손실 0" "0" \
   "$(grep -c -v -x -F -f .claude/agents/infra.md "$WORK/before.txt"; true)"
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/infra.md >/dev/null 2>&1
eq "C8 두 번째 삽입은 가드 rc=2" "2" "$?"

# C9 — evolve may have created a habits marker already. A second one makes every later update
# skip the file as a marker anomaly, so insert must reuse it.
printf -- '\n## 역할 습관\n<!-- guild:persona:habits -->\n- 이미 자란 습관.\n' >> .claude/agents/dba.md
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/dba.md >/dev/null 2>&1
eq "C9 기존 habits 마커 재사용 (1개)" "1" "$(grep -c 'guild:persona:habits' .claude/agents/dba.md)"
has "C9 기존 습관 내용 보존" "$(cat .claude/agents/dba.md)" "이미 자란 습관"

# C10 — no anchor: the central region has no closing edge. Refuse, and leave the file alone.
"$PY" - <<'PYX'
import io
p='.claude/agents/qa.md'; s=io.open(p,encoding='utf-8').read()
io.open(p,'w',encoding='utf-8').write(s.replace("## 프로젝트 특화","## 무언가 다른 것"))
PYX
BEFORE="$(cat .claude/agents/qa.md)"
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/qa.md >/dev/null 2>&1
eq "C10 앵커 없음 → 가드 rc=2" "2" "$?"
eq "C10 …그리고 파일은 그대로" "$BEFORE" "$(cat .claude/agents/qa.md)"

echo ""
echo "== check: 변이시켜서 잡는지 본다 =="

eq "C12 정상 파일 rc" "0" "$("$PY" "$PM" --mode check --file .claude/agents/infra.md --base "$BASE" >/dev/null 2>&1; echo $?)"
has "C12 손실 검사 통과 문구" "$("$PY" "$PM" --mode check --file .claude/agents/infra.md --base "$BASE")" "ok: lossless"

# ⚠ The mutant is written INSIDE the repo, under infra.md's own name at a scratch path. `--base`
# resolves through `git show <sha>:<path>`, so a mutant living in $WORK reports "cannot read" —
# still a FAIL and still rc=3, which is why the structural cases would pass either way and C14,
# the one case that needs the lossless check to actually RUN, would not.
mut() {  # mut <label> <python-mutation> <expected FAIL substring>
  local out rc
  cp .claude/agents/infra.md "$WORK/mut.md"
  "$PY" - "$WORK/mut.md" <<PYX
import io,sys
p=sys.argv[1]; s=io.open(p,encoding='utf-8').read()
$2
io.open(p,'w',encoding='utf-8').write(s)
PYX
  cp "$WORK/mut.md" .claude/agents/infra.md
  out="$("$PY" "$PM" --mode check --file .claude/agents/infra.md --base "$BASE" 2>&1)"; rc=$?
  git checkout -q -- .claude/agents/infra.md 2>/dev/null
  "$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/infra.md >/dev/null 2>&1
  eq "$1 (rc=3)" "3" "$rc"
  has "$1 진단" "$out" "$3"
}

# C13 — the sharpest case. Moving the end marker below the anchor loses NO line, so the
# lossless check passes; only the anchor check sees it. The next update then replaces the
# project-specialization section along with the central body.
mut "C13 end 마커를 앵커 아래로" \
    's=s.replace("<!-- guild:persona:end -->\n\n","");s=s.rstrip()+"\n<!-- guild:persona:end -->\n"' \
    "FAIL: first heading below end"
# C14 — the converse: a deleted line with the markers still correct. Only lossless sees it.
mut "C14 줄 하나 삭제" 's=s.replace("- 배포 파이프라인을 유지한다.\n","")' "line(s) lost"
mut "C15 앵커가 두 번"  's=s.rstrip()+"\n\n## 프로젝트 특화\n- x\n"'  "FAIL: anchor x2"
mut "C15b H1이 두 번"   's=s.replace("## 책임","# 또 다른 제목",1)'          "h1 x2"
mut "C16 start를 frontmatter 위로" \
    's=s.replace("<!-- guild:persona:start -->\n","");s="<!-- guild:persona:start -->\n"+s' \
    "FAIL: start at"
mut "C17 habits 마커 중복"     's=s.rstrip()+"\n<!-- guild:persona:habits -->\n"'  "habits marker appears 2"
mut "C18 마커 순서 뒤바뀜"      's=s.replace("<!-- guild:persona:start -->","<!-- guild:persona:end -->",1)' \
    "marker appears"

# C19 — `--base` is optional because init and update step 4 have no "before" commit to compare
# against. Without it the structural checks still run and the lossless line is simply absent.
OUT="$("$PY" "$PM" --mode check --file .claude/agents/infra.md 2>&1)"
hasnt "C19 --base 없으면 손실 검사 생략" "$OUT" "lossless"
has   "C19 …구조 검사는 그대로"          "$OUT" "ok: markers in order"

# C20 — a batch verdict. update step 4 checks every rewritten persona in one call and wants one
# answer; a good file in the list must not mask a bad one.
cp .claude/agents/infra.md "$WORK/bad.md"
printf -- '\n## 프로젝트 특화\n' >> "$WORK/bad.md"   # 앵커 중복 → 검사 ④ FAIL
OUT="$("$PY" "$PM" --mode check --file .claude/agents/infra.md "$WORK/bad.md" 2>&1)"; RC=$?
eq  "C20 배치 중 하나라도 나쁘면 rc=3" "3" "$RC"
has "C20 …좋은 파일도 보고된다"        "$OUT" "infra.md: ok: markers in order"
eq  "C21 없는 파일은 FAIL 한 줄"       "1" \
    "$("$PY" "$PM" --mode check --file "$WORK/nope.md" 2>&1 | grep -c 'FAIL: no such file')"

# ⚠ REGRESSION GUARD. A migrated T2 persona carries a local section moved DOWN out of the
# central region, so it has THREE `## ` headings below the end marker where a freshly-rendered
# file has two. An earlier draft counted those headings and required exactly two — which would
# have hard-failed every form-D role forever, and, because update step 4 treats any FAIL as a
# break this run caused, frozen `config.version` on every subsequent run. The design rejects
# count-based checks here for a second reason too: an end marker placed one heading too low
# leaves exactly two behind and passes. Identity (C13) is what catches that.
cp .claude/agents/infra.md "$WORK/t2.md"
"$PY" - "$WORK/t2.md" <<'PYX'
import io,sys
p=sys.argv[1]; s=io.open(p,encoding='utf-8').read()
io.open(p,'w',encoding='utf-8').write(
    s.replace("## 역할 습관", "## 우리 팀 배포 규칙\n- 금요일 배포 금지.\n\n## 역할 습관", 1))
PYX
eq "C31 T2 모양(end 아래 ## 셋)은 통과한다" "0" \
   "$("$PY" "$PM" --mode check --file "$WORK/t2.md" >/dev/null 2>&1; echo $?)"
eq "C31 …그 파일의 end 아래 ## 는 실제로 셋" "3" \
   "$(awk '/persona:end/{f=1;next} f&&/^## /{n++} END{print n+0}' "$WORK/t2.md")"

echo ""
echo "== --scope below-end: update step 4가 실제로 발화할 수 있는 검사 =="
# step 4는 이번 실행이 중앙 영역을 방금 갈아끼운 뒤에 돈다. 전체 파일을 비교하면 정상적으로
# 퇴역한 중앙 줄이 전부 "손실"로 잡혀 쓸 수 없다 — 그래서 이전 판은 --base를 아예 안 넘겼고
# 결국 손실을 볼 수 있는 검사가 하나도 없었다. below-end는 update가 건드리지 않기로 한
# 부분만 본다: 오탐이 구조적으로 0이고, 진짜 손실은 전부 잡는다.
persona .claude/agents/scope.md
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/scope.md >/dev/null 2>&1
git add -A; git commit -qm scope
S_BASE="$(git rev-parse HEAD)"
"$PY" - <<'PYX'
import io
p = '.claude/agents/scope.md'
L = io.open(p, encoding='utf-8').read().split('\n')
a = [i for i, l in enumerate(L) if 'persona:start' in l][0]
b = [i for i, l in enumerate(L) if 'persona:end' in l][0]
L[a+1:b] = ['## 새 중앙 본문', '- 완전히 교체되었다.']      # 정상적인 중앙 교체
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
eq "C40 정상 중앙 교체는 below-end에서 조용하다" "0" \
   "$("$PY" "$PM" --mode check --file .claude/agents/scope.md --base "$S_BASE" --scope below-end >/dev/null 2>&1; echo $?)"
eq "C40b …전체 비교였다면 손실로 오탐한다(왜 범위가 필요한지)" "3" \
   "$("$PY" "$PM" --mode check --file .claude/agents/scope.md --base "$S_BASE" >/dev/null 2>&1; echo $?)"
"$PY" - <<'PYX'
import io
p = '.claude/agents/scope.md'
L = io.open(p, encoding='utf-8').read().split('\n')
L.remove('- (아직 없음)')                                   # end 마커 아래 로컬 줄 하나 삭제
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
has "C41 end 아래 로컬 줄 삭제는 잡는다" \
    "$("$PY" "$PM" --mode check --file .claude/agents/scope.md --base "$S_BASE" --scope below-end 2>&1)" \
    "line(s) lost"

echo ""
echo "== 앵커는 리터럴이 아니라 파라미터다 =="
# `init` renders the closing heading in config.language. If the anchor were hard-coded to the
# ko form, a non-ko repo would have NO migration path and no message saying so — every persona
# would report HITL(anchor=0) and read as corrupt. C29 is the case that keeps it honest: the
# same file that passes WITH the flag must fail WITHOUT it, or the flag is decorative.
mkdir -p .claude/agents
tpl_for_en() {
  cat > "$TPL/en.md" <<'MD'
---
name: x
description: x
---

# Title — {{PROJECT_NAME}}

<!-- guild:persona:start -->
## Responsibilities
- central.
<!-- guild:persona:end -->

## Project specifics
- (none yet)

## Role habits
<!-- guild:persona:habits -->
- (none yet)
MD
}
tpl_for_en
cat > .claude/agents/en.md <<'MD'
---
name: infra
description: infra
---

# Infra — Demo

## Responsibilities
- Keep the pipeline green.

## Project specifics
- (none yet)
MD
git add -A; git commit -qm "en persona"
EN_BASE="$(git rev-parse HEAD)"
eq "C27 비-ko 앵커로 삽입" "0" \
   "$("$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/en.md \
      --anchor '## Project specifics' --habits-heading '## Role habits' >/dev/null 2>&1; echo $?)"
has "C27 …습관 헤딩도 로컬라이즈" "$(cat .claude/agents/en.md)" "## Role habits"
eq "C28 같은 앵커로 검사 통과" "0" \
   "$("$PY" "$PM" --mode check --file .claude/agents/en.md --base "$EN_BASE" \
      --anchor '## Project specifics' >/dev/null 2>&1; echo $?)"
eq "C29 앵커 없이 같은 파일은 실패" "3" \
   "$("$PY" "$PM" --mode check --file .claude/agents/en.md --base "$EN_BASE" >/dev/null 2>&1; echo $?)"
# C27이 방금 마커를 넣었으므로 이 파일의 정답은 `done`이다. 마커가 중앙 영역 안에 들어가므로
# init 대비 diff에는 "영역 안 성장"으로 보이고, done 판정이 없으면 끝난 역할이 전부 T2로 되돌아와
# 사람 경로로 다시 밀린다 — 설계 §0.2의 "T2는 무기한 미뤄도 된다"가 그때 성립하지 않는다.
has "C30 이미 마커가 있으면 done" \
    "$("$PY" "$PM" --mode classify --init "$INIT" --anchor '## Project specifics' --templates "$TPL" | awk '/en.md/{print $2}')" \
    "done"
eq "C30b done은 워킹트리가 더러워도 done" "done(markers" \
   "$(printf -- '- 더럽힌다.\n' >> .claude/agents/en.md; "$PY" "$PM" --mode classify --init "$INIT" --templates "$TPL" \
      --anchor '## Project specifics' | awk '/en.md/{print $2}' | cut -c1-13)"
git checkout -q -- .claude/agents/en.md 2>/dev/null || true

echo ""
echo "== 오라클이 조용히 T1이라 답할 수 있는 길들 =="
# T1은 "사람이 안 봐도 되는 파일"이라는 뜻이다. 거짓 T1은 로컬 내용을 다음 update가 지우고
# 어떤 검사도 발화하지 않는다. 거짓 T2는 불필요한 HITL로 끝난다. 그래서 이 절은 전부
# "의심스러우면 T1이 아니어야 한다"를 건다.
mkdir -p .claude/agents
persona .claude/agents/oracle.md
git add -A; git commit -qm oracle
O_INIT="$(git rev-parse HEAD)"
cl(){ "$PY" "$PM" --mode classify --init "$O_INIT" --templates "$TPL" "$@" | awk '/oracle.md/{print $2}'; }

# C32 — 워킹트리가 더러우면 판정하지 않는다. diff는 커밋된 트리를 보는데 경계는 워킹트리에서
# 계산되므로, 커밋되지 않은 중앙 성장은 diff에 안 보이고 H1 위의 무관한 편집은 경계를 밀어
# 헝크 번호와 어긋난다. 둘 다 진짜 T2를 T1로 뒤집는다. §7.3은 며칠 방치를 정상으로 본다.
printf -- '- 커밋되지 않은 중앙 성장.
' >> .claude/agents/oracle.md
has "C32 더러운 워킹트리 → HITL" "$(cl)" "HITL(dirty"
git checkout -q -- .claude/agents/oracle.md

# C33 — git diff가 유니파이드 diff를 못 내면 "@@ 없음"이 되고, 그것을 "변경 없음"으로 읽으면
# 곧바로 T1이다. difftastic 사용자의 환경변수, `*.md -diff`, 깨진 textconv가 전부 이 경로다.
"$PY" - <<'PYX'
import io
p = '.claude/agents/oracle.md'
L = io.open(p, encoding='utf-8').read().split('\n')
L.insert(L.index('- 비밀값을 관리한다.') + 1, '- 중앙 영역 성장.')
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
git add -A; git commit -qm "central growth"
eq  "C33 기준선은 T2" "T2" "$(cl)"
printf '#!/bin/sh
echo "$1 changed"
' > "$WORK/xd.sh"; chmod +x "$WORK/xd.sh"
eq  "C33 GIT_EXTERNAL_DIFF에도 T2" "T2" "$(GIT_EXTERNAL_DIFF="$WORK/xd.sh" cl)"
printf -- '*.md -diff
' > .gitattributes; git add -A; git commit -qm attrs
# `--text`가 대개 이것을 이기지만, 못 이기면 헝크 없는 diff가 남는다. 그때 "변경 없음"으로
# 읽으면 곧바로 T1이므로, 읽을 수 없는 diff는 증거가 아니라 HITL이어야 한다.
CL33B="$(cl)"
case "$CL33B" in T2|HITL*) ok "C33b .gitattributes -diff → T2 또는 HITL ($CL33B)";;
                 *) bad "C33b .gitattributes -diff" "T2 또는 HITL" "$CL33B";; esac
git rm -q .gitattributes; git commit -qm unattrs

# C34 — 거짓 T1의 본체. init 커밋과 함께 들어간 로컬 절은 델타가 비어 있어 T1로 읽히고,
# 삽입이 그 아래에 end를 꽂아 영역 안에 가둔다. 그 절은 end 마커 **위**에 있으므로 이후의
# 어떤 구조 검사도 보지 않는다 — 중앙 템플릿과 헤딩을 비교하는 것이 유일한 기계적 탐지다.
persona .claude/agents/leader.md
"$PY" - <<'PYX'
import io
p = '.claude/agents/leader.md'
L = io.open(p, encoding='utf-8').read().split('\n')
i = L.index('## 프로젝트 특화')
L[i:i] = ['## 운영 계약 (로컬)', '- prod 배포는 화요일만.', '']
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
git add -A; git commit -qm "local section from day 1"
L_INIT="$(git log --format=%H --diff-filter=A -- .claude/agents/leader.md | tail -1)"
mkdir -p "$WORK/tpl"
"$PY" - <<'PYX'
import io,sys
io.open(sys.argv[1] if len(sys.argv)>1 else "/dev/stdout",'w')
PYX
cat > "$WORK/tpl/leader.md" <<'MD'
---
name: leader
description: x
---

# 리더 — {{PROJECT_NAME}}

<!-- guild:persona:start -->
## 책임
- 배포 파이프라인을 유지한다.

## 작업 방식
- 변경은 항상 롤백 경로와 함께 낸다.
<!-- guild:persona:end -->

## 프로젝트 특화
- (아직 없음)

## 역할 습관
<!-- guild:persona:habits -->
- (아직 없음)
MD
# 라운드 3의 BLOCKER: 템플릿을 못 읽으면 `foreign_headings`가 빈 목록을 돌려줬고, 그것은
# "외래 헤딩 없음"과 구별되지 않아 곧바로 T1이었다 — 조회 실패가 부재의 증거로 읽히는,
# `git()` 래퍼에서 이미 한 번 없앤 바로 그 오류다. 이제 인자가 없으면 사용법 오류이고
# 경로가 틀리면 치명적 오류다. 조용히 T1이 되는 길은 없다.
# ⚠ C34는 계약(rc=64)을 걸지 구현 줄을 걸지 않는다. main()의 명시적 필수 검사를 지워도
# `template_headings`의 die가 같은 64를 내므로 그 변이는 등가다 — 두 가드가 독립적으로 같은
# 관측값을 주는 것이고, 이 케이스가 그 위에서 초록인 것이 맞다.
eq  "C34 --templates 없는 classify는 64" "64" \
    "$("$PY" "$PM" --mode classify --init "$L_INIT" >/dev/null 2>&1; echo $?)"
eq  "C34b 틀린 --templates 경로도 64" "64" \
    "$("$PY" "$PM" --mode classify --init "$L_INIT" --templates "$WORK/nope" >/dev/null 2>&1; echo $?)"
eq  "C34c --templates 없는 insert는 64" "64" \
    "$("$PY" "$PM" --mode insert --file .claude/agents/leader.md --init "$L_INIT" >/dev/null 2>&1; echo $?)"
has "C34d 템플릿을 주면 T2로 잡는다" \
    "$("$PY" "$PM" --mode classify --init "$L_INIT" --templates "$TPL" | awk '/leader.md/{print $2}')" \
    "T2(heading-not-in-template"
eq  "C34e insert도 --init을 받으면 거부한다" "2" \
    "$("$PY" "$PM" --mode insert --file .claude/agents/leader.md --init "$L_INIT" --templates "$TPL" >/dev/null 2>&1; echo $?)"

echo ""
echo "== 무손실 검사는 집합이 아니라 다중집합이다 =="
# 설계는 정렬된 두 목록에 `comm -23`을 쓴다 — 다중집합 차집합이다. 집합 소속으로 쓰면 같은
# 줄이 두 번 있다가 하나 지워진 경우를 못 본다. 이 기능이 출하하는 템플릿 자체가
# `- (아직 없음 …)`을 반복하므로 사각지대가 자기 산출물을 덮는다.
persona .claude/agents/dup.md
printf -- '- (아직 없음)
' >> .claude/agents/dup.md
"$PY" - <<'PYX'
import io
p = '.claude/agents/dup.md'
L = io.open(p, encoding='utf-8').read().split('\n')
L.insert(L.index('- 비밀값을 관리한다.') + 1, '- (아직 없음)')
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
git add -A; git commit -qm dup
D_BASE="$(git rev-parse HEAD)"
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/dup.md >/dev/null 2>&1
"$PY" - <<'PYX'
import io
p = '.claude/agents/dup.md'
L = io.open(p, encoding='utf-8').read().split('\n')
L.remove('- (아직 없음)')          # 세 개 중 하나만
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
has "C35 중복된 줄 하나만 지워도 손실로 잡는다"     "$("$PY" "$PM" --mode check --file .claude/agents/dup.md --base "$D_BASE" 2>&1)" "line(s) lost"

echo ""
echo "== 삽입은 정말로 삽입만 한다 =="
# C36 — CRLF 파일. read()는 universal-newline이고 기본 write는 플랫폼 종결자를 쓰므로,
# 그대로 두면 모든 줄이 다시 쓰여 `6 insertions, 0 deletions`여야 할 diff가 `20/13`이 된다.
# 손실 검사는 이것을 못 본다(양쪽 다 CR을 떼므로). §7.4 step 5가 기대는 것이 그 diff다.
tpl_for crlf.md
"$PY" - <<'PYX'
import io
body = ['---', 'name: crlf', 'description: x', '---', '',
        '# 인프라 — 데모', '', '## 책임', '- a', '- b', '',
        '## 프로젝트 특화', '- L', '']
io.open('.claude/agents/crlf.md', 'w', encoding='utf-8', newline='').write('\r\n'.join(body))
PYX
git add -A; git commit -qm crlf
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/crlf.md >/dev/null 2>&1
eq "C36 CRLF 보존 (삭제된 줄 0)" "0"    "$(git diff --numstat -- .claude/agents/crlf.md | awk '{print $2+0}')"

# C37 — habits 마커가 앵커 위에 있으면 영역이 그것을 삼킨다. check는 나중에 잡지만,
# 방금 망가뜨린 파일에 insert가 성공을 보고하는 것은 마이그레이션 도중 잘못된 신호다.
persona .claude/agents/hab.md
"$PY" - <<'PYX'
import io
p = '.claude/agents/hab.md'
L = io.open(p, encoding='utf-8').read().split('\n')
i = L.index('## 프로젝트 특화')
L[i:i] = ['## 역할 습관', '<!-- guild:persona:habits -->', '- 자란 습관.', '']
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
eq "C37 앵커 위 habits → 가드 rc=2" "2"    "$("$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/hab.md >/dev/null 2>&1; echo $?)"

# C38 — 심볼릭 링크. git은 물리 경로를 내는데 abspath는 링크를 풀지 않는다. macOS의
# /tmp·/var·${TMPDIR}이 전부 링크라 이것은 예외가 아니라 일상 경로다.
eq "C38 심링크 절대경로도 손실 검사가 돈다" "0"    "$(ln -sfn "$PWD" "$WORK/link"; "$PY" "$PM" --mode check       --file "$WORK/link/.claude/agents/crlf.md" --base HEAD >/dev/null 2>&1; echo $?)"
# C39 — 짧은 SHA는 정규화한다. 안 하면 "init 커밋 소생이 아님"이라는 틀린 진단이 나온다.
eq "C39 짧은 SHA도 같은 판정" "$(cl)" "$("$PY" "$PM" --mode classify --init "${O_INIT:0:10}" --templates "$TPL" | awk '/oracle.md/{print $2}')"

echo ""
echo "== 경계 — 가운데만 시험하면 off-by-one이 전부 통과한다 =="
# 리뷰가 실측으로 보인 것: hunk_lines의 범위 끝, touched_central의 부등호, insert의 anchor-1을
# 각각 한 칸씩 밀어도 이 스위트가 통째로 초록이었다. 원인은 하나 — 픽스처가 중앙 영역의
# **가운데** 줄만 건드렸기 때문이다. 아래는 영역의 첫 줄과 마지막 줄, 그리고 앵커 바로 위가
# 빈 줄이 아닌 모양을 명시적으로 만든다.

# 앵커 바로 위가 내용인 페르소나. 기존 픽스처는 항상 빈 줄이었고, 손실 검사가 빈 줄을 무시하므로
# insert의 `anchor - 1`을 `anchor - 2`로 밀어도 공백만 뒤섞여 아무 검사도 발화하지 않았다.
tight() {
  tpl_for "$(basename "$1")"
  cat > "$1" <<'MD'
---
name: infra
description: 인프라 담당
model: sonnet
---

# 인프라 — 데모

## 책임
- 첫 중앙 줄.
- 가운데 중앙 줄.
- 마지막 중앙 줄 (앵커 바로 위, 빈 줄 없음).
## 프로젝트 특화
- (아직 없음)
MD
}
tight .claude/agents/tight.md
git add -A; git commit -qm tight
T_BASE="$(git rev-parse HEAD)"
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/tight.md >/dev/null 2>&1
has "C42 앵커 바로 위 내용 줄이 살아남는다" "$(cat .claude/agents/tight.md)" "마지막 중앙 줄"
eq  "C42b …그리고 손실 검사가 그것을 본다" "0" \
    "$("$PY" "$PM" --mode check --file .claude/agents/tight.md --base "$T_BASE" >/dev/null 2>&1; echo $?)"
eq  "C42c end 마커가 앵커 바로 위" "1" \
    "$(awk '/persona:end/{n=NR} /^## 프로젝트 특화/{a=NR} END{print (a==n+2)?1:0}' .claude/agents/tight.md)"

# 영역의 첫 줄과 마지막 줄에서의 추가·삭제. 네 방향 모두 T2여야 한다.
# 파일명을 매번 새로 쓴다 — 같은 이름을 지웠다 다시 만들면 `--diff-filter=A` 소생 커밋이
# 둘이 되어 오라클이 (정당하게) HITL로 떨어지고, 시험하려던 경계는 시험되지 않는다.
edge() {   # edge <label> <op> <name>
  tight ".claude/agents/$3.md"
  git add -A; git commit -qm "edge base $3" >/dev/null
  local E_INIT; E_INIT="$(git rev-parse HEAD)"
  "$PY" - "$2" "$3" <<'PYX'
import io, sys
op, name = sys.argv[1], sys.argv[2]
p = '.claude/agents/%s.md' % name
L = io.open(p, encoding='utf-8').read().split('\n')
if op == 'add-first':    L.insert(L.index('## 책임') + 1, '- 새 첫 줄.')
elif op == 'add-last':   L.insert(L.index('- 마지막 중앙 줄 (앵커 바로 위, 빈 줄 없음).') + 1, '- 새 마지막 줄.')
elif op == 'del-first':  L.remove('- 첫 중앙 줄.')
elif op == 'del-last':   L.remove('- 마지막 중앙 줄 (앵커 바로 위, 빈 줄 없음).')
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
  git add -A; git commit -qm "edge $2 $3" >/dev/null
  eq "C43 $1" "T2" "$("$PY" "$PM" --mode classify --init "$E_INIT" --templates "$TPL" | awk -v n="$3.md" '$1 ~ n {print $2}')"
}
edge "영역 첫 줄에 추가"   add-first  ea
edge "영역 마지막 줄에 추가" add-last   eb
edge "영역 첫 줄 삭제"     del-first  ec
edge "영역 마지막 줄 삭제"  del-last   ed

# C49 — H1 **바로 다음** 줄이 내용인 모양에서의 삭제. 기존 픽스처는 H1 뒤에 빈 줄이 있어
# 영역 첫 내용 줄이 h1+2였고, 그래서 순수 삭제의 straddle 쌍 [start, start+1] 중 start만
# 남겨도 여전히 영역 안이라 판정이 안 바뀌었다. h1+1을 지우면 start == h1이 되고, 경계가
# 열린 구간(h1 < n)이므로 start 하나만으로는 영역 밖이 된다 — 그때 비로소 두 형태가 갈린다.
nogap() {
  tpl_for "$(basename "$1")"
  cat > "$1" <<'MD'
---
name: infra
description: 인프라 담당
model: sonnet
---
# 인프라 — 데모
## 책임
- 첫 중앙 줄.
- 가운데 중앙 줄.
## 프로젝트 특화
- (아직 없음)
MD
}
nogap .claude/agents/nogap.md
git add -A; git commit -qm nogap
N_INIT="$(git rev-parse HEAD)"
"$PY" - <<'PYX'
import io
p = '.claude/agents/nogap.md'
L = io.open(p, encoding='utf-8').read().split('\n')
L.remove('## 책임')          # H1 바로 다음 줄 = 영역의 첫 줄
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
git add -A; git commit -qm "delete first region line"
eq "C49 H1 직후 줄 삭제도 T2" "T2" \
   "$("$PY" "$PM" --mode classify --init "$N_INIT" --templates "$TPL" | awk '/nogap.md/{print $2}')"

# C44 — H1이 앵커보다 아래. 이 가드가 없으면 insert가 빈 슬라이스를 만들고 앵커 아래를 통째로
# 다시 내보내 본문이 두 번 나온다. 검사 ④가 지금은 잡지만, 가드 자체에도 케이스가 필요하다.
git checkout -q -- .claude/agents/ 2>/dev/null
persona .claude/agents/rev.md
"$PY" - <<'PYX'
import io
p = '.claude/agents/rev.md'
L = io.open(p, encoding='utf-8').read().split('\n')
h = L.index('# 인프라 — 데모')
L.pop(h)
L.append('# 인프라 — 데모')
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
eq "C44 H1이 앵커 아래 → 가드 rc=2" "2" \
   "$("$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/rev.md >/dev/null 2>&1; echo $?)"

# C45 — 앵커가 두 번. landmarks의 `!= 1`을 `< 1`로 바꿔도 이전 스위트는 초록이었다.
persona .claude/agents/twoanchor.md
printf -- '\n## 프로젝트 특화\n- 두 번째.\n' >> .claude/agents/twoanchor.md
eq "C45 앵커 두 개 → 가드 rc=2" "2" \
   "$("$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/twoanchor.md >/dev/null 2>&1; echo $?)"

# C46 — 앵커 동일성. C13은 end를 파일 맨 아래로 보내 `below`를 비우므로 `(none)` 분기만 타고,
# 실제 문자열 비교는 한 번도 실행되지 않았다. 여기서는 end 아래 첫 `## `가 **다른 헤딩**이다.
persona .claude/agents/ident.md
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/ident.md >/dev/null 2>&1
"$PY" - <<'PYX'
import io
p = '.claude/agents/ident.md'
L = io.open(p, encoding='utf-8').read().split('\n')
i = [n for n, l in enumerate(L) if 'persona:end' in l][0]
L.insert(i + 2, '## 다른 헤딩')
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
has "C46 end 아래 첫 헤딩이 앵커가 아니면 잡는다" \
    "$("$PY" "$PM" --mode check --file .claude/agents/ident.md 2>&1)" "first heading below end is ## 다른 헤딩"

# C47 — "바로 아래"를 실제로 잰다. end와 앵커 사이에 중앙 산문이 남으면 그 문단은 갱신 대상에서
# 빠지고, 다음 update가 템플릿의 같은 문단을 영역 안에 다시 써서 사본이 둘로 갈린다. 헤딩을
# 넘지 않으므로 `## ` 기반 검사로는 보이지 않는다.
persona .claude/agents/stray.md
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/stray.md >/dev/null 2>&1
"$PY" - <<'PYX'
import io
p = '.claude/agents/stray.md'
L = io.open(p, encoding='utf-8').read().split('\n')
i = [n for n, l in enumerate(L) if 'persona:end' in l][0]
L.insert(i + 1, '중앙 문단이 end 아래로 밀렸다.')
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
has "C47 end와 앵커 사이의 잔여 산문을 잡는다" \
    "$("$PY" "$PM" --mode check --file .claude/agents/stray.md 2>&1)" "stranded between end marker and anchor"

# C48 — insert의 T2 가드를 **diff 경로**로. C34는 외래 헤딩 경로만 탔다.
git checkout -q -- .claude/agents/ 2>/dev/null
tight .claude/agents/t2diff.md
git add -A; git commit -qm t2diff
D_INIT="$(git rev-parse HEAD)"
"$PY" - <<'PYX'
import io
p = '.claude/agents/t2diff.md'
L = io.open(p, encoding='utf-8').read().split('\n')
L.insert(L.index('- 가운데 중앙 줄.') + 1, '- 로컬이 기른 줄.')
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
git add -A; git commit -qm "t2 growth"
eq "C48 diff가 T2면 insert가 --init에서 거부" "2" \
   "$("$PY" "$PM" --mode insert --file .claude/agents/t2diff.md --init "$D_INIT" --templates "$TPL" >/dev/null 2>&1; echo $?)"
eq "C48b --init 없이는 통과한다(T2 경로는 이것을 쓴다)" "0" \
   "$("$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/t2diff.md >/dev/null 2>&1; echo $?)"

echo ""
echo "== 삽입이 손대지 않아야 할 것들 =="
# C50 — 줄바꿈이 섞인 파일. "이 파일은 CRLF인가?"를 한 번만 답하면 어느 쪽이든 파일을 망친다.
# CRLF 한 줄 때문에 LF 열두 줄이 전부 다시 쓰이면, 마이그레이션 diff가 `6 insertions, 0 deletions`이
# 아니라 `19/12`가 되어 §7.4 step 5의 사람 검토가 불가능해진다. 손실 검사는 양쪽에서 CR을 떼므로
# 이것을 못 본다.
tpl_for mix.md
"$PY" - <<'PYX'
import io
L = ['---', 'name: mix', 'description: x', '---', '',
     '# 인프라 — 데모', '', '## 책임', '- a', '- b', '',
     '## 프로젝트 특화', '- L', '']
body = '\n'.join(L)
body = body.replace('- a\n', '- a\r\n', 1)          # 딱 한 줄만 CRLF
io.open('.claude/agents/mix.md', 'w', encoding='utf-8', newline='').write(body)
PYX
git add -A; git commit -qm mix
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/mix.md >/dev/null 2>&1
eq "C50 혼합 줄바꿈 — 삭제된 줄 0" "0" \
   "$(git diff --numstat -- .claude/agents/mix.md | awk '{print $2+0}')"
eq "C50b …CRLF 줄 수도 그대로 1" "1" \
   "$("$PY" -c "import sys;d=open('.claude/agents/mix.md','rb').read();sys.stdout.write(str(d.count(b'\r\n')))")"

# C51 — 파일 끝의 빈 줄. `rstrip`으로 지우면 손실 검사가 빈 줄을 무시하므로 아무도 못 본다.
# 내용 손실은 아니지만 "삽입만 한다"가 거짓이 되고, 그 문장이 이 마이그레이션의 안전 근거다.
persona .claude/agents/trail.md
printf -- '\n\n\n' >> .claude/agents/trail.md
git add -A; git commit -qm trail
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/trail.md >/dev/null 2>&1
eq "C51 끝 빈 줄 — 삭제된 줄 0" "0" \
   "$(git diff --numstat -- .claude/agents/trail.md | awk '{print $2+0}')"

echo ""
echo "== below-end 비교가 성립하지 않는 경우 =="
# C52 — base 쪽에 end 마커가 없으면 그 비교는 "손실 없음"이 아니라 "비교 불가"다.
# 한쪽만 빈 목록으로 만들면 Counter([]) - Counter(무엇이든)이 항상 비어 조용히 통과한다 —
# 마커 없던 파일의 로컬 불릿을 지워도 초록이었다.
persona .claude/agents/nobase.md
git add -A; git commit -qm nobase
NB="$(git rev-parse HEAD)"
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/nobase.md >/dev/null 2>&1
"$PY" - <<'PYX'
import io
p = '.claude/agents/nobase.md'
L = io.open(p, encoding='utf-8').read().split('\n')
L.remove('- (아직 없음)')
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
has "C52 base에 end 마커가 없으면 비교 불가라고 말한다" \
    "$("$PY" "$PM" --mode check --file .claude/agents/nobase.md --base "$NB" --scope below-end 2>&1)" \
    "cannot run"

echo ""
echo "== --phase가 되돌리기 가능 여부를 정한다 =="
# 되돌리기를 부르는 FAIL과 그렇지 않은 FAIL을 산문으로 가르면 선행 결함이 이번 실행 탓이 되고
# 정상 갱신이 매번 버려진다. 그래서 호출자가 phase를 고르고 도구가 검사 집합을 정한다.
#
# ⚠ 마커 **개수**는 post-write에도 들어간다. 설계는 "update가 만들 수 없는 상태"라며 빼라고
# 했지만, 잘못된 치환은 `persona:start`를 삼킬 수 있다 — 그러면 step 4가 성공을 보고하고
# 버전이 올라가고, 이후 규칙 2는 "마이그레이션 미완"이라 하고 마이그레이션은 "쌍이 깨졌으니
# 사람이 고쳐라"라고 해서 **두 복구 경로가 모두 막힌다.** 설계가 우려한 거짓 되돌리기는
# 일어날 수 없다 — 규칙 3b가 쓰기 전에 이미 1/1/1을 증명했으므로, 여기서의 개수 이상은
# 이번 실행의 소행이거나 사람이 실행 도중에 손댄 것뿐이다.
persona .claude/agents/ph.md
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/ph.md >/dev/null 2>&1
cp .claude/agents/ph.md "$WORK/ph_ok.md"
"$PY" - <<'PYX'
import io
p = '.claude/agents/ph.md'
L = io.open(p, encoding='utf-8').read().split('\n')
L = [l for l in L if 'persona:start' not in l]      # 치환이 start 마커를 삼킨 모양
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
eq "C53 post-write가 삼켜진 start 마커를 잡는다" "3" \
   "$("$PY" "$PM" --mode check --phase post-write --file .claude/agents/ph.md >/dev/null 2>&1; echo $?)"
eq "C53b pre-write도 당연히 잡는다" "3" \
   "$("$PY" "$PM" --mode check --phase pre-write --file .claude/agents/ph.md >/dev/null 2>&1; echo $?)"
eq "C53c post-write는 start 위치는 보지 않는다(쓰기 전 조건)" "0" \
   "$("$PY" - "$WORK/ph_ok.md" <<'PYX'
import io, sys
p = sys.argv[1]
L = io.open(p, encoding='utf-8').read().split('\n')
i = [n for n, l in enumerate(L) if 'persona:start' in l][0]
L.insert(0, L.pop(i))                                # 선행 결함: start를 프론트매터 위로
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
"$PY" "$PM" --mode check --phase post-write --file "$WORK/ph_ok.md" >/dev/null 2>&1; echo $?)"
eq "C53d …pre-write는 그것을 잡는다" "3" \
   "$("$PY" "$PM" --mode check --phase pre-write --file "$WORK/ph_ok.md" >/dev/null 2>&1; echo $?)"
echo ""
echo "== 마커가 '있다'의 정의는 하나여야 한다 =="
# C54 — 네 소비처가 두 정의를 썼다: classify/insert는 파일 전체 부분문자열, check/update 규칙 2는
# 줄 일치. 그래서 마커를 **산문에서 언급만** 한 페르소나(규약을 문서화하는 tech-writer가 전형)가
# 마이그레이션에는 `done`, 나머지 전부에는 "마커 없음"이 됐다. 규칙 2가 마이그레이션으로 보내고,
# 마이그레이션이 끝났다고 답하고, 그 역할은 다시는 중앙 갱신을 못 받는다.
persona .claude/agents/mention.md
"$PY" - <<'PYX'
import io
p = '.claude/agents/mention.md'
L = io.open(p, encoding='utf-8').read().split('\n')
L.append('- 규약: 중앙 영역은 `<!-- guild:persona:start -->` 로 시작한다.')
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
git add -A; git commit -qm mention
M_INIT="$(git log --format=%H --diff-filter=A -- .claude/agents/mention.md | tail -1)"
CL54="$("$PY" "$PM" --mode classify --init "$M_INIT" --templates "$TPL" | awk '/mention.md/{print $2}')"
case "$CL54" in done*) bad "C54 산문 속 마커 언급을 done으로 읽지 않는다" "T1/T2/HITL" "$CL54";;
                *) ok "C54 산문 속 마커 언급을 done으로 읽지 않는다 ($CL54)";; esac
eq "C54b …그리고 insert가 거부하지 않는다" "0" \
   "$("$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/mention.md >/dev/null 2>&1; echo $?)"
eq "C54c --templates 없는 insert는 T2 경로에서도 64" "64" \
   "$("$PY" "$PM" --mode insert --file .claude/agents/mention.md >/dev/null 2>&1; echo $?)"

echo ""
echo "== below-end는 양방향이다 =="
# C55 — step 4는 "end 마커 아래의 무엇도 바뀌지 않았다"를 약속한다. 손실만 보면 그 말을 못 한다:
# 치환이 잘못돼 절이 **추가**되면 통과하고, 그 다음 실행의 규칙 3b가 그 파일을 영원히 skip한다.
persona .claude/agents/sym.md
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/sym.md >/dev/null 2>&1
git add -A; git commit -qm sym
S_BASE2="$(git rev-parse HEAD)"
printf -- '\n## 프로젝트 특화\n- 중복.\n' >> .claude/agents/sym.md
has "C55 end 아래에 줄이 추가돼도 잡는다" \
    "$("$PY" "$PM" --mode check --phase post-write --base "$S_BASE2" --scope below-end \
       --file .claude/agents/sym.md 2>&1)" "appeared below the end marker"
eq "C55b …그리고 모순되는 ok를 함께 내지 않는다" "0" \
   "$("$PY" "$PM" --mode check --phase post-write --base "$S_BASE2" --scope below-end \
      --file .claude/agents/sym.md 2>&1 | grep -c 'ok: nothing changed below')"

echo ""
echo "== 디렉터리가 틀린 것과 역할에 템플릿이 없는 것은 다른 실패다 =="
# 라운드 3이 둘을 한데 묶어, 중앙에서 템플릿이 **은퇴한** 역할 하나가 판별 전체를 exit 64로
# 끝내고 그 뒤 정렬 순서의 파일이 전부 미판정으로 남았다. 하나는 가드가 통째로 꺼지는 치명적
# 상황이고, 다른 하나는 규칙 1이 이미 마이그레이션 범위 밖에 둔 `local-only`다.
persona .claude/agents/retired.md
rm -f "$TPL/retired.md"                       # 중앙에서 은퇴
git add -A; git commit -qm retired
R_INIT="$(git log --format=%H --diff-filter=A -- .claude/agents/retired.md | tail -1)"
OUT_R="$("$PY" "$PM" --mode classify --init "$R_INIT" --templates "$TPL" 2>&1)"; RC_R=$?
eq  "C56 은퇴한 역할이 있어도 판별은 완주한다" "0" "$RC_R"
has "C56b …그 역할은 local-only로 보고된다" "$OUT_R" "retired.md local-only"
eq  "C56c …그리고 다른 역할 판정이 사라지지 않는다" "1" \
    "$(echo "$OUT_R" | grep -c 'oracle.md')"
eq  "C57 --templates 경로 자체가 틀리면 여전히 64" "64" \
    "$("$PY" "$PM" --mode classify --init "$R_INIT" --templates "$WORK/nodir" >/dev/null 2>&1; echo $?)"
eq  "C57b 빈 디렉터리도 64" "64" \
    "$(mkdir -p "$WORK/empty"; "$PY" "$PM" --mode classify --init "$R_INIT" --templates "$WORK/empty" >/dev/null 2>&1; echo $?)"
# `*.md`가 있기만 하면 통과시키면, 형제 디렉터리(templates/standards 같은)가 조건을 만족해
# **모든 역할이 local-only**로 보고된다 — 그리고 local-only는 "조치 불필요한 정상 상태"로
# 문서화돼 있어, 잘못된 경로가 "마이그레이션할 것 없음"이라는 성공처럼 읽힌다.
eq  "C57c md는 있지만 페르소나 템플릿이 아닌 디렉터리도 64" "64" \
    "$(mkdir -p "$WORK/notpl"; printf -- '# 그냥 문서\n' > "$WORK/notpl/a.md"; \
       "$PY" "$PM" --mode classify --init "$R_INIT" --templates "$WORK/notpl" >/dev/null 2>&1; echo $?)"
eq  "C58 local-only 역할에는 insert도 가드로 막는다" "2" \
    "$("$PY" "$PM" --mode insert --file .claude/agents/retired.md --init "$R_INIT" --templates "$TPL" >/dev/null 2>&1; echo $?)"

echo ""
echo "== 마커 쌍은 세 상태다: 없음 · 둘 다 · 깨짐 =="
# 하나의 술어("마커가 하나라도 있나?")로 두 질문에 답하면 반쪽짜리 파일이 갇힌다.
# classify는 "이 역할이 끝났나"를 묻고 — `both`만 예다. insert는 "여기에 마커를 써도 되나"를
# 묻고 — `none`만 예다. OR로 합치면 start가 삼켜진 파일이 classify에는 `done`, insert에는
# 거부가 되고, 규칙 2는 계속 마이그레이션으로 보낸다: 복구 경로가 둘 다 막힌다.
persona .claude/agents/half.md
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/half.md >/dev/null 2>&1
"$PY" - <<'PYX'
import io
p = '.claude/agents/half.md'
L = io.open(p, encoding='utf-8').read().split('\n')
io.open(p, 'w', encoding='utf-8').write('\n'.join(l for l in L if 'persona:start' not in l))
PYX
git add -A; git commit -qm half
H_INIT="$(git log --format=%H --diff-filter=A -- .claude/agents/half.md | tail -1)"
CL="$("$PY" "$PM" --mode classify --init "$H_INIT" --templates "$TPL" | awk '/half.md/{print $2}')"
case "$CL" in done*) bad "C59 반쪽 쌍을 done으로 읽지 않는다" "HITL(marker anomaly…)" "$CL";;
              HITL*) ok "C59 반쪽 쌍을 done으로 읽지 않는다 ($CL)";;
              *) bad "C59 반쪽 쌍" "HITL" "$CL";; esac
eq "C59b insert도 '이미 쌍이 있다'가 아니라 '깨졌다'로 거부" "1" \
   "$("$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/half.md 2>&1 | grep -c 'broken marker pair')"

echo ""
echo "== 잘못된 템플릿 하나가 판별 전체를 죽이면 안 된다 =="
# 라운드 4까지 `templates_ok()`는 디렉터리만 봤고, 개별 템플릿의 마커가 1/1이 아니면
# `die()`가 났다. 정렬 순서상 그 뒤의 역할은 전부 미판정으로 남는다 — 편집 중인 템플릿
# 하나로 열한 역할의 판정이 사라졌다.
# ⚠ persona()가 자기 템플릿을 함께 만드므로, 페르소나를 먼저 만들고 **그 다음** 템플릿을 깬다.
persona .claude/agents/broken_tpl.md
"$PY" - <<'PYX'
import io, os
p = os.environ['TPLDIR'] + '/broken_tpl.md'
L = io.open(p, encoding='utf-8').read().split('\n')
io.open(p, 'w', encoding='utf-8').write('\n'.join(l for l in L if 'persona:end' not in l))
PYX
git add -A; git commit -qm brokentpl
B_INIT="$(git log --format=%H --diff-filter=A -- .claude/agents/broken_tpl.md | tail -1)"
OUT_B="$("$PY" "$PM" --mode classify --init "$B_INIT" --templates "$TPL" 2>&1)"
has "C60 잘못된 템플릿은 그 역할만 HITL" "$OUT_B" "broken_tpl.md HITL(central template is malformed"
eq  "C60b …다른 역할 판정은 살아남는다" "1" "$(echo "$OUT_B" | grep -c 'oracle.md')"
# ⚠ 판별의 계약은 "판정은 stdout, 종료 코드는 항상 0"이다. 잘못된 템플릿은 **판정 하나**이지
# 실행 실패가 아니다 — Bash 호출이 0이 아닌 값을 내면 읽는 쪽에서는 명령이 실패한 것으로 읽혀
# 정상 출력된 나머지 판정까지 버려진다. 역할별 처리를 도입한 이유가 바로 그것이었다.
eq  "C60c 판별은 그래도 0으로 끝난다 (판정은 stdout에 있다)" "0" \
    "$("$PY" "$PM" --mode classify --init "$B_INIT" --templates "$TPL" >/dev/null 2>&1; echo $?)"

echo ""
echo "== local-only는 T2 경로에서도 막힌다 =="
# Scope 검사가 `--init` 블록 안에 있으면 T2 경로(= --init 없음)가 중앙 템플릿 없는 페르소나를
# 그대로 감싼다 — 설계 §7.4 step 1이 그 필터를 둔 이유가 바로 그것이다.
persona .claude/agents/onlylocal.md
rm -f "$TPL/onlylocal.md"
eq "C61 T2 경로(--init 없이)도 local-only를 거부" "2" \
   "$("$PY" "$PM" --mode insert --file .claude/agents/onlylocal.md --templates "$TPL" >/dev/null 2>&1; echo $?)"

echo ""
echo "== 마커 개수는 치환이 닿을 수 있는 곳에서만 되돌리기를 부른다 =="
# 치환은 start~end **사이**만 쓴다. 그러니 그 둘의 개수 이상은 이번 실행의 소행일 수 있고,
# habits는 end 아래라 절대 아니다 — 후자에서 되돌리면 설계 §6.3이 경고한 "결함은 못 고치고
# 정상 갱신만 매번 버림"이 된다. 그래서 seam을 개수 전체가 아니라 쌍/습관으로 긋는다.
persona .claude/agents/seam.md
"$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/seam.md >/dev/null 2>&1
cp .claude/agents/seam.md "$WORK/seam_h.md"
printf -- '\n<!-- guild:persona:habits -->\n' >> "$WORK/seam_h.md"
eq "C62 habits 중복은 post-write의 개수 검사에 안 걸린다" "0" \
   "$("$PY" "$PM" --mode check --phase post-write --file "$WORK/seam_h.md" 2>&1 | grep -c 'habits marker appears')"
eq "C62b …pre-write에서는 걸린다" "1" \
   "$("$PY" "$PM" --mode check --phase pre-write --file "$WORK/seam_h.md" 2>&1 | grep -c 'habits marker appears')"
cp .claude/agents/seam.md "$WORK/seam_s.md"
"$PY" - "$WORK/seam_s.md" <<'PYX'
import io, sys
p = sys.argv[1]
L = io.open(p, encoding='utf-8').read().split('\n')
io.open(p, 'w', encoding='utf-8').write('\n'.join(l for l in L if 'persona:start' not in l))
PYX
eq "C62c start가 삼켜지면 post-write가 잡는다" "1" \
   "$("$PY" "$PM" --mode check --phase post-write --file "$WORK/seam_s.md" 2>&1 | grep -c 'start marker appears')"

echo ""
echo "== 한 FAIL 문자열이 세 가지를 뜻할 때 =="
# `start at P, fence2=F, h1=H`는 세 결함을 한 문자열로 낸다: 닫는 프론트매터 fence 소실 ·
# H1 소실 · 진짜 마커 오배치. 처방이 하나뿐이면 앞의 둘에서 **실행 불가**다 — `persona:start`는
# 제자리인데 "fence 아래로 옮기라"고 지시하게 된다. 게다가 fence 소실은 프론트매터 불릿의
# 규칙 6이 이미 `broken fence (pre-existing)`로 세므로, 같은 파일이 두 카운터에 들어간다.
mkfence() { persona "$1"; "$PY" "$PM" --mode insert --templates "$TPL" --file "$1" >/dev/null 2>&1; }
mkfence .claude/agents/f1.md
"$PY" - <<'PYX'
import io
p = '.claude/agents/f1.md'
L = io.open(p, encoding='utf-8').read().split('\n')
del L[[n for n, l in enumerate(L) if l.rstrip() == '---'][1]]
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
has "C63 fence 소실은 fence2=- 로 구별된다" \
    "$("$PY" "$PM" --mode check --phase pre-write --file .claude/agents/f1.md 2>&1)" "fence2=-"
mkfence .claude/agents/f2.md
"$PY" - <<'PYX'
import io
p = '.claude/agents/f2.md'
L = io.open(p, encoding='utf-8').read().split('\n')
del L[[n for n, l in enumerate(L) if l.startswith('# ')][0]]
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
has "C63b H1 소실은 h1=- 로 구별된다" \
    "$("$PY" "$PM" --mode check --phase pre-write --file .claude/agents/f2.md 2>&1)" "h1=-"
mkfence .claude/agents/f3.md
"$PY" - <<'PYX'
import io
p = '.claude/agents/f3.md'
L = io.open(p, encoding='utf-8').read().split('\n')
i = [n for n, l in enumerate(L) if 'persona:start' in l][0]
L.insert(0, L.pop(i))
io.open(p, 'w', encoding='utf-8').write('\n'.join(L))
PYX
OUT_F3="$("$PY" "$PM" --mode check --phase pre-write --file .claude/agents/f3.md 2>&1)"
case "$OUT_F3" in *fence2=-*|*h1=-*) bad "C63c 진짜 오배치는 두 값이 다 있다" "fence2/h1 모두 숫자" "$OUT_F3";;
                  *"start at 1"*) ok "C63c 진짜 오배치는 두 값이 다 있다";;
                  *) bad "C63c" "start at 1 …" "$OUT_F3";; esac

echo ""
echo "== 오라클이 실패했을 때 사람에게 무엇이 남는가 =="
# `git()`이 stderr를 버리면 `HITL(git-log-failed)`가 열여섯 역할에 똑같이 찍히고 단서가 0이다.
# 재판별해도 같은 값이 나오므로 진행할 방법이 없다 — 원인은 stderr에 있었다.
persona .claude/agents/gerr.md
git add -A; git commit -qm gerr
G_INIT="$(git log --format=%H --diff-filter=A -- .claude/agents/gerr.md | tail -1)"
git config log.follow bogusvalue
OUT_G="$("$PY" "$PM" --mode classify --init "$G_INIT" --templates "$TPL" 2>&1 | head -1)"
git config --unset log.follow
has "C64 git 실패에 진단이 함께 나온다" "$OUT_G" "bad boolean config value"

# C65 — 추적되지 않은 페르소나(`evolve --hire`가 만드는 흔한 모양)는 "여러 번 추가됨"이 아니다.
# 두 상태의 처방이 다르다: 전자는 커밋, 후자는 본문 출처 확인.
persona .claude/agents/untracked.md
OUT_U="$("$PY" "$PM" --mode classify --init "$G_INIT" --templates "$TPL" | awk '/untracked.md/{print $2" "$3}')"
has "C65 추적 안 된 파일은 untracked로 보고" "$OUT_U" "HITL(untracked"
git add -A; git commit -qm untracked >/dev/null

echo ""
echo "== 비-ko 레포: 헤딩 비교는 번역문과 한국어를 맞대는 짓이다 =="
# 16개 중앙 템플릿의 영역 안 헤딩은 전부 한국어이고, init은 비-ko 레포에서 그 영역을 **번역**한다.
# 그래서 헤딩 비교는 영원히 불일치 → **모든 역할이 T2**가 되고, 그 판정의 설명("로컬 절이거나
# 중앙 개명")은 둘 다 거짓이다. 사람이 첫 갈래를 따르면 중앙 절 둘을 영역 밖으로 잘라내는데
# 여섯 검사가 전부 초록이다. --localized는 그 비교만 끄고 diff로 판정한다.
mkdir -p "$WORK/ja/.claude/agents" "$WORK/ja/tpl"
tpl_ja() {
  cat > "$WORK/ja/tpl/$1" <<'MD'
---
name: x
description: x
---

# 題 — {{PROJECT_NAME}}

<!-- guild:persona:start -->
## 책임
- 중앙.
<!-- guild:persona:end -->

## 프로젝트 특화
- (아직 없음)

## 역할 습관
<!-- guild:persona:habits -->
- (아직 없음)
MD
}
tpl_ja infra.md
cat > "$WORK/ja/.claude/agents/infra.md" <<'MD'
---
name: infra
description: d
model: sonnet
---

# インフラ — デモ

## 責務
- パイプラインを維持する。

## プロジェクト特化
- (未定)
MD
( cd "$WORK/ja" && git init -q . && git config user.email t@t && git config user.name t \
  && git config commit.gpgsign false && git add -A && git commit -qm init >/dev/null )
JA_INIT="$( cd "$WORK/ja" && git rev-parse HEAD )"
eq "C66 --localized 없이는 모든 역할이 T2가 된다(현상)" "1" \
   "$( cd "$WORK/ja" && "$PY" "$PM" --mode classify --init "$JA_INIT" --anchor '## プロジェクト特化' \
      --templates tpl | grep -c 'heading-not-in-template' )"
eq "C66b --localized면 diff만으로 T1" "T1" \
   "$( cd "$WORK/ja" && "$PY" "$PM" --mode classify --init "$JA_INIT" --anchor '## プロジェクト特化' \
      --templates tpl --localized | awk '{print $2}' )"
# C67 — 습관 플레이스홀더도 현지어여야 한다. 한국어 줄을 일본어 파일에 쓰면 init.md·evolve.md가
# 둘 다 "있을 수 없다"고 말하는 상태가 되고, audit/monitoring이 그 줄로 "습관 없음"과
# "day-1 보일러플레이트"를 가른다.
( cd "$WORK/ja" && "$PY" "$PM" --mode insert --file .claude/agents/infra.md \
    --anchor '## プロジェクト特化' --habits-heading '## 役割の習慣' \
    --habits-placeholder '- (まだありません)' --templates tpl --localized >/dev/null 2>&1 )
has "C67 플레이스홀더가 현지어로 들어간다" "$(cat "$WORK/ja/.claude/agents/infra.md")" "- (まだありません)"
hasnt "C67b …그리고 한국어 줄은 들어가지 않는다" "$(cat "$WORK/ja/.claude/agents/infra.md")" "아직 없음 — \`/gld evolve\`"
eq "C67c 비-ko 파일도 검사를 통과한다" "0" \
   "$( cd "$WORK/ja" && "$PY" "$PM" --mode check --anchor '## プロジェクト特化' \
      --file .claude/agents/infra.md --base "$JA_INIT" >/dev/null 2>&1; echo $? )"

echo ""
echo "== git 실패를 '트리가 더럽다'로 보고하지 않는다 =="
# insert의 clean-tree 가드만 새 진단을 버리고 있었다 — git이 실패한 것을 "커밋하거나 스태시하라"로
# 보고하면 사람은 멀쩡한 파일에 `git status`를 돌리러 간다. classify의 쌍둥이는 메시지를 싣는다.
persona .claude/agents/gfail.md
git add -A; git commit -qm gfail
GF_INIT="$(git log --format=%H --diff-filter=A -- .claude/agents/gfail.md | tail -1)"
git config status.showUntrackedFiles bogus
OUT_GF="$("$PY" "$PM" --mode insert --templates "$TPL" --file .claude/agents/gfail.md \
          --init "$GF_INIT" 2>&1)"
git config --unset status.showUntrackedFiles
hasnt "C68 git 실패를 '트리가 더럽다'로 말하지 않는다" "$OUT_GF" "commit or stash it first"
has   "C68b …대신 무엇이 실패했는지 말한다"          "$OUT_GF" "cannot check whether the tree is clean"

echo ""
echo "== 사용법 오류는 가드 실패와 구별된다 =="
# 64 vs 2 is not decoration: without it a typo in --file reports as "this persona cannot be
# migrated" and a human goes looking for a malformed file that is fine.
eq "C22 classify에 --init 없음 → 64" "64" "$("$PY" "$PM" --mode classify >/dev/null 2>&1; echo $?)"
# C23 asserts the contract, not the line that implements it: deleting the explicit
# `no such file` guard leaves rc=64 anyway because read() dies with the same code. That
# mutant is equivalent, and this case is right to stay green on it.
eq "C23 insert에 없는 파일 → 64"     "64" "$("$PY" "$PM" --mode insert --templates "$TPL" --file "$WORK/nope.md" >/dev/null 2>&1; echo $?)"
eq "C24 insert에 파일 2개 → 64"      "64" "$("$PY" "$PM" --mode insert --templates "$TPL" --file a.md b.md >/dev/null 2>&1; echo $?)"
# argparse's own exit code is 2, which is this script's "guard failed" — so a typo in a flag
# name would read as "this persona cannot be migrated" and send a human to look at a file that
# is fine. The parser is subclassed to route its errors through the same 64.
eq "C25 알 수 없는 --mode → 64"      "64" "$("$PY" "$PM" --mode wat >/dev/null 2>&1; echo $?)"
eq "C25b 플래그 오타 → 64"           "64" "$("$PY" "$PM" --mode insert --templates "$TPL" --fil x.md >/dev/null 2>&1; echo $?)"
# C26 — the script runs from inside the user's repo; a __pycache__ next to it would show up as
# an untracked file in `git status` and trip the dirty-tree snapshot update step 2 takes.
# Scoped to THIS script's bytecode: the atoms directory legitimately holds .pyc files from
# other scripts, and in a user's repo — where __pycache__ may not be gitignored — an extra
# untracked file would trip the dirty-tree snapshot update step 2 takes before writing.
eq "C26 __pycache__ 남기지 않음" "0" \
   "$(find "$(dirname "$PM")" -name 'persona_migrate*.pyc' | grep -c .; true)"

echo ""
echo "  PASS=$PASS FAIL=$FAIL"
# ⚠ A FLOOR. Cases live in shell here, so a `cd` that fails or a fixture that does not build
# makes later cases silently not run and the suite reports FAIL=0 over a hole.
MIN_CHECKS=122
if [ "$((PASS + FAIL))" -lt "$MIN_CHECKS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${MIN_CHECKS}건) — 픽스처가 도중에 죽었을 가능성이 큽니다."
  exit 1
fi
[ "$FAIL" -eq 0 ] || exit 1
