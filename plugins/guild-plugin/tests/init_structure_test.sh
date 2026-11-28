#!/usr/bin/env bash
# Structural checks over commands/init.md (stage 4, V1 — split out of prompt_structure_test.sh, content unchanged, so
# that branch B (init) and branch A (sprint, everything else) never edit the same test file; stage-4 review-q0 E-1).
# The helpers and the two scanners (`sprintkeys`, `banlist`) are copies: the same rules as prompt_structure_test.sh.
#
# Usage: bash plugins/guild-plugin/tests/init_structure_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
GLD="${1:-$HERE/../skills/gld}"
[ -d "$GLD" ] || { echo "missing: $GLD" >&2; exit 1; }
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
unset GIT_CONFIG GIT_CONFIG_COUNT
PY="${PY:-python3}"
gld_skip() { echo "SKIP: $1" >&2; [ "${GLD_ALLOW_SKIP:-0}" = 1 ] && exit 0; \
            echo "FAIL  스킵은 통과가 아닙니다 — GLD_ALLOW_SKIP=1 로 명시하십시오." >&2; exit 1; }
"$PY" -c "pass" >/dev/null 2>&1 || gld_skip "$PY is not usable — this suite is python-based"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s (expected %s, got %s)\n' "$1" "$2" "$3"; }
hasfx() {   # hasfx <case> <file> <fixed-string>   — prose OR code; comments count
  if [ -f "$2" ] && grep -qF -- "$3" "$2"; then ok "$1"; else bad "$1" "present" "not found: $3"; fi
}
lacksfx() { # lacksfx <case> <file> <fixed-string>
  if [ ! -f "$2" ]; then bad "$1" "the file to exist" "no such file: $2"; return; fi
  if [ -f "$2" ] && grep -qF -- "$3" "$2"; then bad "$1" "absent" "found: $3"; else ok "$1"; fi
}
WORK3="$(mktemp -d)"; trap 'rm -rf "$WORK3"' EXIT
INITMD="$GLD/commands/init.md"; CONFMD="$GLD/commands/config.md"
[ -f "$INITMD" ] || { echo "missing: $INITMD" >&2; exit 1; }

echo "== init.md =="
hasfx "init.md: 허용목록이 여덟 개라고 적는다" "$INITMD" 'lists only the **eight** commands'
hasfx "init.md: 넷으로 줄이지 말라고 못박는다" "$INITMD" 'Do not trim it to four'
hasfx "init.md: 기본 config 에 refactor_slot" "$INITMD" '"refactor_slot": true'
hasfx "init: config 에 commands.vrt" "$INITMD" '"vrt": "<simple cmd or null>"'
hasfx "init: 시각 매처 삭제는 경고 (차단 아님)" "$INITMD" 'dropping its screenshot matcher calls **warns**'
hasfx "init: 갭마다 판정 먼저" "$INITMD" 'Every **BLOCKER/MAJOR** gap gets **exactly one verdict, stated before any question**'
hasfx "init: MINOR 는 한 줄 카운트" "$INITMD" '`등록 불필요 <n>건 (MINOR — 리포트에만 기록)`'
lacksfx "init: 'offer MINOR too' 가 사라졌다" "$INITMD" 'offer MINOR too'
lacksfx "init: 선택지를 고르게 하지 않는다" "$INITMD" 'user picks which to file'
hasfx "init: GitHub 레포 없으면 기록만" "$INITMD" '`기록만 — GitHub 레포 없음`'
hasfx "init: 화면에는 BLOCKER/MAJOR 만" "$INITMD" '**On screen, show only BLOCKER/MAJOR gaps plus the summary count**'
hasfx "init: inline-secret 에 git rm --cached 를 제안하지 않는다" "$INITMD" 'for `inline-secret` the file is ordinary source, so **never** offer `git rm --cached`'
hasfx "init: inline-secret 로컬 조치는 안내만" "$INITMD" '**printed as guidance only, never applied**'
hasfx "init: 서브에이전트 프롬프트에 GATE_SCRIPT" "$INITMD" '`GATE_SCRIPT` = `<<SKILL_DIR>>/gates/gate_precommit.py`'
hasfx "init: absent 분기" "$INITMD" '**`absent`** → no hook yet'
hasfx "init(0.98.2 S1): dismissed.md 형식은 백틱 경로" "$INITMD" '`` - `<path/pattern>` — <reason> `` (backticks recommended, optional)'
hasfx "init(0.98.2 S1): 형식 줄은 불릿이 아닌 > 인용·문장" "$INITMD" 'as a `>` quote or a plain sentence — never as a bullet'
lacksfx "init(0.98.2 S1): 옛 백틱 없는 형식 제거" "$INITMD" '(header only; `- <path/pattern> — <reason>` downgrades'
hasfx "init(Y1): P4 요약에 PreToolUse 텍스트 가드" "$INITMD" '+ PreToolUse 가 명령 줄 텍스트의 백틱 치환·Issue 본문 묶음 저장을 막음 (`shell-text` · `bodies-save`)'
lacksfx "init(D7): harness.json 에 visual 이 없다" "$INITMD" '"visual": {'
lacksfx "init(D7): harness.json 에 gates 가 없다" "$INITMD" '"gates": {'
hasfx "init(H13): M1 설정은 harness.json 이다" "$INITMD" 'Never `config.json`** — that file is the engine'
lacksfx "init(H13): M1 설정을 config.json 에 쓰지 않는다" "$INITMD" '`.claude/guild/config.json` — the M1 config'
hasfx "init(T2 R4-3): 채널 값이 꺼진 채널은 역할 파일을 쓰지 않는다" "$INITMD" '**`writes_role_files: false`** → `init` writes **no** role file'
hasfx "init(T2 R4-3): 쓸 역할은 엔진이 정한다" "$INITMD" 'engine.py init roles --repo <owner>/<repo> --json'
hasfx "init(T2 R4-3): write 가 이름 댄 역할만 쓴다" "$INITMD" 'For **each role the answer'"'"'s `write` names — and no other**'
hasfx "init(T2 R4-3): 있는 역할 파일은 덮어쓰지 않는다" "$INITMD" '**A role file that exists is never written over, edited or merged**'
hasfx "init(T2 R4-3): 쓴 파일만 페르소나 골격 검사" "$INITMD" 'persona_migrate.py --mode check --anchor'
lacksfx "init(T2 R4-3): 안정판 명령 이름이 없다" "$INITMD" '안정판 `/'"gld"' init`'  # promote: literal
hasfx "init(T2 P4): 0.98.x 설치는 P0b 로" "$INITMD" 'present → a 0.98.x Guild may have set this folder up — do **P0b**'
hasfx "init(T2 P4): 드라이런" "$INITMD" 'engine.py init migrate --repo <owner>/<repo> --json'
hasfx "init(T2 P4): 사람 확인 뒤 실행" "$INITMD" 'engine.py init migrate --repo <owner>/<repo> --apply'
hasfx "init(T2 P4): 무인은 옮기지 않는다" "$INITMD" 'Never migrate in an unattended run.'
hasfx "init(T2 P4): 꺼진 게이트가 켜진다고 말한다" "$INITMD" 'the commit gate was off and will be on'
hasfx "init(T2 P4): 되돌리기 안내" "$INITMD" 'undo = copy them back and delete'
hasfx "init(T2 P4): 옮긴 뒤 P2.9 전체" "$INITMD" '`state: migrated` (a 0.98.x install moved here, its old config.json not yet replaced) → offer **P2.9 alone**'
hasfx "init(Y1): 텍스트 가드는 늘 켜져 있다" "$INITMD" 'The commit gate and the Bash text guard (`shell-text` · `bodies-save`) are always on in guild-plugin.'
hasfx "init(S4-init): 명령 문자열을 만들지 않는다" "$INITMD" 'You never write it, never edit it and never make up a command text'
hasfx "init(S4-init): 사람 대신 답하지 않는다" "$INITMD" '**Never answer for the human**'
hasfx "init(Q11): followups-dry-run 은 묻지 않고 기본은 실제 생성" "$INITMD" '`followups-dry-run` | **never asked** (optional; no answer = `create`'
hasfx "init(Q11): dry-run 은 사람이 원할 때만 켠다(답 또는 설정 한 줄)" "$INITMD" '`init answer … --question followups-dry-run --answer dry-run'
hasfx "init(Q11): dry-run 설정 한 줄" "$INITMD" '`"followups_dry_run": true` in `.claude/guild/config.json`'
hasfx "init(Q11): 질문 목록 예외" "$INITMD" '(all but `followups-dry-run`, which is never asked — see the table)'
lacksfx "init(Q11): 필수·기본값 없음 문구가 남지 않는다" "$INITMD" 'always (required, **no default**)'
hasfx "init(A15): 좁히지 않고 넓히면 거절" "$INITMD" 'A wider glob, or one the engine cannot prove narrower, is refused'
hasfx "init(S4-init): check 는 샌드박스 밖 백그라운드" "$INITMD" '**in the background** (`run_in_background: true`, timeout 7200000)'
for q in test-command command-conflict not-local sandbox-exception quarantine risk-rules registry-host toolchain \
         risk-add narrow-glob followups-dry-run; do   # three more by A15 (2026-11-26)
  hasfx "init(S4-init): 질문 $q" "$INITMD" "| \`$q\` |"
done
for a in doctor propose answer check write; do
  hasfx "init(S4-init): engine.py init $a" "$INITMD" "init $a --repo OWNER/REPO --checkout REPO_ROOT"
done

# init.md 의 sprint 객체와 config.md 의 스키마에서 키 집합을 뽑아 교차검증
cat > "$WORK3/sprintkeys.py" <<'SKPY'
import re, sys
init, conf = open(sys.argv[1]).read(), open(sys.argv[2]).read()
m = re.search(r'"sprint":\s*\{(.*?)\}', init, re.S)
if not m:
    print('ERR init.md has no "sprint" object'); raise SystemExit(0)
body = m.group(1)
ikeys = set(re.findall(r'"([a-z_]+)":', body))
m2 = re.search(r"sprint\{([^}]*)\}", conf)
if not m2:
    print("ERR config.md has no sprint schema"); raise SystemExit(0)
ckeys = set(k.strip().replace("[]", "") for k in m2.group(1).split(","))
problems = []
if "window" not in ikeys:
    problems.append('init.md\'s "sprint" object has no `window` key')
elif not re.search(r'"window"\s*:\s*null', body):
    problems.append("init.md's `window` default is not `null` — the window is opt-in and a "
                    "windowless run must be byte-identical to today")
for k in sorted(ikeys - ckeys):
    problems.append("init.md writes `%s` but config.md's schema does not list it" % k)
for k in sorted(ckeys - ikeys):
    problems.append("config.md's schema lists `%s` but init.md does not write it" % k)
print("OK %d keys" % len(ikeys) if not problems else "; ".join(problems))
SKPY
SK="$("$PY" "$WORK3/sprintkeys.py" "$INITMD" "$CONFMD")"
case "$SK" in
  OK*) ok "init.md 의 sprint 키 집합이 config.md 스키마와 일치하고 window 기본값이 null ($SK)" ;;
  *)   bad "sprint 키 집합 교차검증" "the same set, window=null" "$SK" ;;
esac

# 금지 목록 — init.md 의 사이트 (prompt_structure_test.sh 의 전수 검사에서 init.md 몫)
cat > "$WORK3/banlist.py" <<'PYBAN'
import os, sys
skill_dir = sys.argv[1]
# prompt_structure_test.sh 의 같은 검사에서 init.md 만 나눠 본 것이다(stage 4, V1). 규칙을 고치면 둘 다 고친다.
ONLY = {os.path.join("commands", "init.md")}
# 정본 아홉 항목. 각 항목마다 **허용되는 표기** 를 함께 적는다 — 같은 규칙을 영문/한글로,
# 낱말로/기호로 적은 판이 실제로 공존하고, 그것들은 전부 정당하다.
ITEMS = [
    ("substitution", ["$(...)", "$(…)"]),
    ("backtick",     ["backtick", "백틱", "`..`", "`…`"]),
    ("&&",           ["⺠AND⺠"]),
    ("||",           ["⺠OR⺠"]),
    ("|",            ["|"]),
    (";",            [";"]),
    ("&",            ["&"]),
    ("newline",      ["newline", "개행", "\\n"]),
    ("redirection",  ["redirection", "리다이렉션", "`<`, `>`"]),
]
# 금지 목록을 **도입하는** 어구. 토큰 개수로 찾으면 실제 셸 코드가 12건 오검출된다.
LEAD = ("MUST NOT contain", "must not contain", "never contains", "never contain",
        "forbids", "forbid ", "disallow", "rejects", "거부한다", "금지하는", "금지한다",
        "ban list", "허용하지 않는")
# `commands.*` 계약을 말하고 있다는 표지 — LEAD 는 있는데 `$(...)` 가 없을 때 후보로 남길지 정한다.
CONFIGWORD = ("commands.*", "config.commands", "commands.test", "stored command", "stored form",
              "--install-cmd", "INSTALL_CMDS", "config normalis", "config normaliz",
              "저장을 금지", "in these")
BASHRULE = ("_bash_rules.md", "simple calls only", "simple Bash tool call", "one simple call",
            "its own simple Bash", "each its own Bash call", "its own Bash call")
def norm(t):
    # `&&`/`||` 를 먼저 치환해야 낱개 `&`/`|` 검사가 그것들에 흡수되지 않는다.
    return t.replace("&&", "⺠AND⺠").replace("||", "⺠OR⺠")
problems, sites = [], 0
for root, dirs, files in os.walk(skill_dir):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in sorted(files):
        if not f.endswith((".md", ".py", ".sh")):
            continue
        path = os.path.join(root, f)
        rel = os.path.relpath(path, skill_dir)
        if rel not in ONLY:
            continue
        lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
        for n, line in enumerate(lines, 1):
            if not any(k in line for k in LEAD):
                continue
            # 열거가 두 줄에 걸치는 곳이 있다(run.md 산문, die() 문자열). **앞이 아니라 뒤로만**
            # 본다 — 예전 판은 앞 줄까지 포함해서, 사이트 자신이 틀린 말을 해도 위/아래 이웃이
            # 항목을 대신 공급하면 통과했다(실측: `render_supervisor.py:62` 는 아홉 항목 전부를
            # 이웃에게서 받고 있었다).
            win = " ".join(lines[n - 1:n + 3])
            # ⚠ 예전 판은 `$(...)` 가 없으면 **조용히 건너뛰었다.** 그래서 가장 위험한 누락 —
            #   열거에서 `$(...)` 자체를 빼는 것 — 이 사이트를 통째로 사라지게 만들었고, 검사는
            #   `OK sites=8` 을 찍었다(실측). 건너뛰기는 통과가 아니다. `commands` 문맥이면
            #   후보로 남겨 실패시키고, 무관한 `forbids`(예: "INV5 forbids leaving the machine")
            #   만 떨어뜨린다.
            if not any(v in win for v in ITEMS[0][1]):
                # ⚠ 문맥 판정은 **히트 줄 자신** 에서만 한다. 창으로 보면 이웃이 문맥을 대신
                #   공급한다 — `run.md:74`("this repo forbids merge commits")가 네 줄 아래의
                #   `config.commands` 를 빌려 후보가 됐다. 토큰 검사에서 고친 것과 같은 결함이
                #   분류기 쪽에 남아 있었다.
                if not any(k in line for k in CONFIGWORD):
                    continue
                sites += 1
                problems.append("%s:%d claims a ban list but does not name `$(...)` — the one "
                                "omission that would hide the site itself" % (rel, n))
                continue
            ctx = "\n".join(lines[max(0, n - 4):n + 2])
            if any(k in ctx for k in BASHRULE) and "commands" not in win:
                continue
            sites += 1
            w = norm(win)
            missing = [name for name, spellings in ITEMS
                       if not any(sp in w for sp in (norm(x) for x in spellings))]
            if missing:
                problems.append("%s:%d enumerates the ban list but omits %s"
                                % (rel, n, ",".join(missing)))
# ⚠ 바닥선이 아니라 **정확값** 이다. `>= 8` 이었을 때 아홉 중 하나가 통째로 사라져도 통과했다.
#   사이트가 늘거나 주는 것은 의도적 변경이므로 이 숫자를 함께 고치게 만든다.
if sites != 1:
    problems.append("found %d ban-list sites, expected exactly 1 — a site appeared or vanished; "
                    "update this number deliberately" % sites)
print("OK sites=%d" % sites if not problems else "PROBLEMS " + " | ".join(problems))
PYBAN
OUTB="$("$PY" "$WORK3/banlist.py" "$GLD")"
case "$OUTB" in
  OK*) ok "init.md: 금지 목록 사이트가 정본과 일치한다 (${OUTB#OK })" ;;
  *)   bad "init.md: 금지 목록 사이트" "OK" "$OUTB" ;;
esac
BANLIST='MUST NOT contain `$(...)` or backticks, `&&`, `||`, `|`, `;`, `&`, newlines, or redirections'
hasfx "commands/init.md: 금지 목록이 정본과 글자 그대로 같다" "$INITMD" "$BANLIST"

# 다른 문서·스크립트가 `init.md:163` 으로 인용하는 줄 (run.md · stack_sync.py · …). 줄이 움직이면 인용도 함께 고친다.
if sed -n 163p "$INITMD" | grep -qF -- 'normalized, simple-bash-safe'; then ok "init.md:163 이 인용된 계약 줄이다"
else bad "init.md:163" "normalized, simple-bash-safe" "$(sed -n 163p "$INITMD" | cut -c1-120)"; fi

echo ""
echo "결과: PASS=$PASS FAIL=$FAIL"
INIT_MIN_CHECKS=46   # 검사를 일부러 늘리거나 줄일 때 함께 고친다
if [ "$((PASS + FAIL))" -lt "$INIT_MIN_CHECKS" ]; then
  echo "FAIL  실행된 검사가 $((PASS + FAIL))건뿐입니다 (최소 ${INIT_MIN_CHECKS}건)"
  exit 1
fi
[ "$FAIL" -eq 0 ]
