#!/usr/bin/env bash
# Verification for `board_write.py` — the one guard that keeps `/gld sprint plan` from
# clobbering supervisor-owned cards (design: design/guild/03-sprint-board.md §7.1a·§9.2a).
#
# Scope, honestly: these are BEHAVIOUR checks, not spelling checks. A `gh` stub records
# every call, so each case asserts what actually went out on the wire. That distinction is
# the lesson 02-sprint.md §23.7 paid for: grep-based checks pass while the control flow
# they claim to guard never runs — 249 green with three live BLOCKERs underneath.
#
# The case that matters most is TRUNCATION (H-w5). `item-list` returns the real
# `totalCount` in the same response, so a short read is detectable — and if we cannot see
# every card we cannot prove one is unowned. Writing anyway is exactly how a supervisor's
# `Blocked` card gets overwritten with `Backlog`, which is the damage the guard exists to
# prevent. A design draft had this as "proceed and report"; that reads as safe and is not.
#
# Usage: bash plugins/guild-plugin/tests/board_write_test.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BW="$HERE/../skills/gld/commands/atoms/board_write.py"
[ -f "$BW" ] || { echo "missing: $BW" >&2; exit 1; }
PY="${PY:-python3}"
WORK="$(mktemp -d)" || { echo "mktemp -d failed" >&2; exit 1; }
[ -n "$WORK" ] && [ -d "$WORK" ] || { echo "mktemp -d gave no directory" >&2; exit 1; }
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0

# ── 환경 격리 ────────────────────────────────────────────────────────────
# ⚠ `GIT_DIR`/`GIT_WORK_TREE` are ALWAYS exported inside a git hook and this plugin installs
# hooks. Nothing here runs git, but `gh` reads them to resolve the repo, and a stub that
# shadows `gh` is easier to trust when the environment is not also lying.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
unset GIT_CONFIG GIT_CONFIG_COUNT
unset GH_TOKEN                      # keyring account is what the design assumes (§1.1a)
# ⚠ A FUNCTIONAL probe, not `command -v`: an interpreter that exists but cannot run
# (a broken venv, a shim that exits non-zero) reports as a structural failure with an
# empty diagnostic — measured in the sprint_dag suite.
"$PY" -c "pass" >/dev/null 2>&1 || { echo "SKIP: $PY is not usable — this suite is python-based" >&2; exit 0; }

ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s — %s\n' "$1" "$2"; }

# ── gh 스텁 ──────────────────────────────────────────────────────────────
# Records every invocation to $WORK/calls.txt and answers `item-list` from
# $WORK/itemlist.json. `GH_FAIL_EDIT=1` makes every `item-edit` fail, which is how the
# absorb-but-count path (D9) and the item-add retry get exercised.
BIN="$WORK/bin"; mkdir -p "$BIN"

# ⚠ `project view` and `field-list` are answered by a SHARED fragment every stub sources.
# Node-ID addressing needs a project id, field ids and the column field's option ids, and a
# stub that does not answer those makes `board_write.py` refuse to write — which is correct
# behaviour and useless as a fixture. Keeping the answers in one file means a later case that
# rewrites `$BIN/gh` cannot silently lose them.
cat > "$WORK/ids.sh" <<'IDS'
gh_ids() {
  case "$2" in
    view)
      printf '{"id":"PVT_probe","number":7}\n'; exit 0 ;;
    field-list)
      printf '%s\n' '{"fields":[
        {"id":"PVTSSF_col","name":"Guild board","type":"ProjectV2SingleSelectField","options":[
          {"id":"opt_backlog","name":"Backlog"},{"id":"opt_ready","name":"Ready"},
          {"id":"opt_inprog","name":"In progress"},{"id":"opt_blocked","name":"Blocked"},
          {"id":"opt_inrev","name":"In review"},{"id":"opt_done","name":"Done"},
          {"id":"opt_todo","name":"할 일"},{"id":"opt_rev2","name":"리뷰 중"},
          {"id":"opt_r2","name":"준비"},{"id":"opt_p2","name":"진행"},
          {"id":"opt_b2","name":"막힘"},{"id":"opt_v2","name":"리뷰 대기"},
          {"id":"opt_d2","name":"완료"},{"id":"opt_doing","name":"Doing"}]},
        {"id":"PVTF_order","name":"Order","type":"ProjectV2Field"},
        {"id":"PVTF_dep","name":"Depends on","type":"ProjectV2Field"},
        {"id":"PVTF_nh","name":"Needs human","type":"ProjectV2Field"},
        {"id":"PVTF_sp","name":"Sprint","type":"ProjectV2Field"},
        {"id":"PVTF_other","name":"Other field","type":"ProjectV2Field"}],
        "totalCount":6}'
      exit 0 ;;
    item-add)
      # ⚠ Answered here too. Node-ID writes need an item id, and a card that is not on the
      # board yet gets one from `item-add --format json`. A stub that returns a bare exit 0
      # leaves the id empty and every write is counted as failed — which is correct behaviour
      # and a useless fixture. `GH_FAIL_ADD=1` still forces the failure path.
      [ "${GH_FAIL_ADD:-0}" = 1 ] && exit 1
      printf '{"id":"PVTI_added"}\n'; exit 0 ;;
  esac
}
IDS

cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$2" in
  item-list) cat "$GH_ITEMLIST" ;;
  item-edit) [ "${GH_FAIL_EDIT:-0}" = 1 ] && exit 1 ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
export PATH="$BIN:$PATH" GH_CALLS="$WORK/calls.txt" GH_ITEMLIST="$WORK/itemlist.json" \
       GH_IDS="$WORK/ids.sh"

# ── 헬퍼 ─────────────────────────────────────────────────────────────────
COLS='{"backlog":"Backlog","ready":"Ready","in_progress":"In progress","blocked":"Blocked","in_review":"In review","done":"Done"}'

# itemlist <totalCount> <json-array-of-items>
itemlist() { printf '{"items":%s,"totalCount":%s}\n' "$2" "$1" > "$GH_ITEMLIST"; }

# run_bw <input-json>  → sets OUT / RC, resets the call log
run_bw() {
  : > "$GH_CALLS"
  printf '%s\n' "$1" > "$WORK/in.json"
  OUT="$("$PY" "$BW" --input "$WORK/in.json" 2>"$WORK/err.txt")"; RC=$?
}

# expect_summary <case> <expected-summary>
expect_summary() {
  if [ "$OUT" = "$2" ]; then ok "$1"; else bad "$1" "summary=[$OUT] expected=[$2]"; fi
}

# ⚠ `-F` and `--` are both required: the patterns here start with `--`, and an earlier
# version was called as `calls_matching '--value Backlog'`, which passed `--` AS THE
# PATTERN — every argument assertion counted the `--owner` on the item-list line and was
# a tautology. Pass exactly one argument.
calls_matching() { grep -c -F -- "$1" "$GH_CALLS" 2>/dev/null || true; }

echo "board_write.py — §9.2a"

# ── H-w1 카드 값이 없음(키 부재 = 널 버킷 = Issues) → 쓴다 ─────────────────
itemlist 1 '[{"content":{"number":120,"repository":"acme/widget"}}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
expect_summary "H-w1 키 부재 → 쓴다" "wrote=1 skipped=0 unknown=0 col_failed=0 failed=0 truncated=0"
[ "$(calls_matching '--single-select-option-id opt_backlog')" -ge 1 ] \
  && ok "H-w1 컬럼 옵션 id 로 나갔다" || bad "H-w1 인자" "$(cat "$GH_CALLS")"

# ── H-w2 카드 값이 Backlog → 쓴다 (plan 소유 값) ──────────────────────────
itemlist 1 '[{"content":{"number":120,"repository":"acme/widget"},"guild board":"Backlog"}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":null}]}'
expect_summary "H-w2 Backlog → 쓴다(비우기)" "wrote=1 skipped=0 unknown=0 col_failed=0 failed=0 truncated=0"
[ "$(calls_matching '--clear')" -ge 1 ] \
  && ok "H-w2 --clear 가 나갔다" || bad "H-w2 인자" "$(cat "$GH_CALLS")"

# ── H-w3 감독자 소유 4값 → 쓰지 않는다 ────────────────────────────────────
# ⚠ `Ready` 는 여기 없다(H-w3b 로 분리). 두 주체가 쓰는 유일한 컬럼이고, 감독자 소유로 두면
# 사람이 다음 스프린트에서 **뺀** 멤버가 지난 `Order`·`Sprint` 를 달고 영영 `Ready` 에 남아
# *"큐에 있음, 하실 일 없음"* 이라고 말한다 — 어느 큐에도 없는 일에 대해.
for pair in "In review:in_review" "Blocked:blocked" "In progress:in_progress" "Done:done"; do
  disp="${pair%%:*}"
  itemlist 1 '[{"content":{"number":120,"repository":"acme/widget"},"guild board":"'"$disp"'"}]'
  run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
           "columns":'"$COLS"',"guard":true,"read":true,
           "writes":[{"issue":120,"column":"backlog"}]}'
  if [ "$OUT" = "wrote=0 skipped=1 unknown=0 col_failed=0 failed=0 truncated=0" ] && [ "$(calls_matching item-edit)" -eq 0 ]; then
    ok "H-w3 $disp → 쓰지 않는다"
  else
    bad "H-w3 $disp" "summary=[$OUT] calls=[$(tr '\n' '|' < "$GH_CALLS")]"
  fi
done

# ── H-w3b Ready 는 plan 이 다시 판정할 수 있다 (그 칸의 유일한 청소 수단) ──
itemlist 1 '[{"content":{"number":120,"repository":"acme/widget"},"guild board":"Ready"}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
expect_summary "H-w3b Ready → 쓴다 (스프린트에서 빠진 카드를 되돌릴 수 있다)" \
               "wrote=1 skipped=0 unknown=0 col_failed=0 failed=0 truncated=0"
if [ "$(calls_matching '--single-select-option-id opt_backlog')" -ge 1 ]; then
  ok "H-w3b Backlog 옵션으로 나갔다"
else
  bad "H-w3b 인자" "$(cat "$GH_CALLS")"
fi

# ── H-w4 사람이 컬럼을 개명 → 역매핑으로 판정한다 (D7) ────────────────────
# 표시 이름이 "리뷰 대기"인데 토큰은 in_review 다. 리터럴 비교라면 가드가 통과해버린다.
RENAMED='{"backlog":"할 일","ready":"준비","in_progress":"진행","blocked":"막힘","in_review":"리뷰 대기","done":"완료"}'
itemlist 1 '[{"content":{"number":120,"repository":"acme/widget"},"guild board":"리뷰 대기"}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$RENAMED"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
if [ "$OUT" = "wrote=0 skipped=1 unknown=0 col_failed=0 failed=0 truncated=0" ]; then
  ok "H-w4 개명된 컬럼도 역매핑으로 막는다"
else
  bad "H-w4 역매핑" "summary=[$OUT]"
fi
# 그리고 쓸 때는 개명된 표시 이름으로 나가야 한다
itemlist 1 '[{"content":{"number":121,"repository":"acme/widget"}}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$RENAMED"',"guard":true,"read":true,
         "writes":[{"issue":121,"column":"backlog"}]}'
[ "$(calls_matching '--single-select-option-id opt_todo')" -ge 1 ] \
  && ok "H-w4 개명된 이름으로 쓴다" || bad "H-w4 쓰기 이름" "$(cat "$GH_CALLS")"

# ── H-w5 절단 → 아무것도 쓰지 않는다 ──────────────────────────────────────
# 이 케이스가 가장 중요하다. 읽지 못한 카드를 "카드 없음"으로 보면 감독자의 Blocked 가 덮인다.
itemlist 630 '[{"content":{"number":120,"repository":"acme/widget"}}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"},{"issue":121,"column":"backlog"}]}'
if [ "$OUT" = "wrote=0 skipped=2 unknown=0 col_failed=0 failed=0 truncated=1" ] && [ "$(calls_matching item-edit)" -eq 0 ]; then
  ok "H-w5 절단 → 쓰기 0건 + truncated=1"
else
  bad "H-w5 절단" "summary=[$OUT] calls=[$(tr '\n' '|' < "$GH_CALLS")]"
fi

# ── H-w6 다른 레포 이슈는 걸러낸다 ────────────────────────────────────────
# 같은 번호가 다른 레포에 있으면, 그 카드 값으로 우리 이슈를 판정해선 안 된다.
itemlist 1 '[{"content":{"number":120,"repository":"other/repo"},"guild board":"In review"}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
expect_summary "H-w6 다른 레포는 무시 → 쓴다" "wrote=1 skipped=0 unknown=0 col_failed=0 failed=0 truncated=0"

# ── H-w7 draft 항목(번호 없음) → 예외 없이 건너뛴다 ──────────────────────
itemlist 2 '[{"content":{"title":"draft only"}},{"content":{"number":120,"repository":"acme/widget"}}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
expect_summary "H-w7 draft 항목이 있어도 동작한다" "wrote=1 skipped=0 unknown=0 col_failed=0 failed=0 truncated=0"

# ── H-w8 gh 실패 → failed 를 세고 종료코드는 0 (D9) ───────────────────────
itemlist 1 '[{"content":{"number":120,"repository":"acme/widget"}}]'
GH_FAIL_EDIT=1 run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
# ⚠ col_failed=1 도 함께 온다: 컬럼 쓰기가 실패했고, 그것이 보드가 *말하는 것*을 바꾸는 유일한
# 필드다. `Order` 쓰기 실패와 같은 칸에 세면 한 항목이 `wrote` 와 `failed` 양쪽에 들어가고,
# 호출자는 *"41건 기록"* 중 몇 장이 엉뚱한 컬럼에 있는지 알 방법이 없었다.
if [ "$OUT" = "wrote=0 skipped=0 unknown=0 col_failed=1 failed=1 truncated=0" ] && [ "$RC" -eq 0 ]; then
  ok "H-w8 실패를 흡수하되 센다 (rc=0, col_failed 분리)"
else
  bad "H-w8 흡수" "summary=[$OUT] rc=$RC"
fi
# 그리고 item-add 재시도가 한 번 끼었어야 한다
[ "$(calls_matching item-add)" -ge 1 ] \
  && ok "H-w8 item-add 재시도가 나갔다" || bad "H-w8 재시도" "$(cat "$GH_CALLS")"

# ── H-w9 멤버 시딩: guard=false + fields + clear ──────────────────────────
itemlist 1 '[{"content":{"number":101,"repository":"acme/widget"},"guild board":"Blocked"}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":101,"column":"ready","guard":false,
                    "fields":{"Order":"1","Sprint":"99"},"clear":["Needs human"]}]}'
if [ "$OUT" = "wrote=1 skipped=0 unknown=0 col_failed=0 failed=0 truncated=0" ] \
   && [ "$(calls_matching '--single-select-option-id opt_ready')" -ge 1 ] \
   && [ "$(calls_matching '--field-id PVTF_order --text 1')" -ge 1 ] \
   && [ "$(calls_matching '--field-id PVTF_nh --clear')" -ge 1 ]; then
  ok "H-w9 시딩은 가드를 통과하고 Needs human 을 비운다"
else
  bad "H-w9 시딩" "summary=[$OUT] calls=[$(tr '\n' '|' < "$GH_CALLS")]"
fi

# ── H-w10 입력 오류 → 64 ─────────────────────────────────────────────────
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"writes":[{"issue":120,"column":"없는토큰"}]}'
[ "$RC" -eq 64 ] && ok "H-w10 알 수 없는 컬럼 토큰 → 64" || bad "H-w10 토큰" "rc=$RC"
: > "$WORK/in.json"; printf 'not json\n' > "$WORK/in.json"
"$PY" "$BW" --input "$WORK/in.json" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 64 ] && ok "H-w10 깨진 JSON → 64" || bad "H-w10 JSON" "rc=$RC"
"$PY" "$BW" --input "$WORK/nope.json" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 64 ] && ok "H-w10 없는 파일 → 64" || bad "H-w10 파일" "rc=$RC"

# ── H-w11 guard 없는 호출은 item-list 를 읽지 않는다 ──────────────────────
# 감독자 시딩만 하는 호출에서 불필요한 읽기 1콜이 나가지 않아야 한다.
itemlist 1 '[]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready"}]}'
if [ "$(calls_matching item-list)" -eq 0 ]; then
  ok "H-w11 가드가 없으면 item-list 를 읽지 않는다"
else
  bad "H-w11 불필요한 읽기" "$(cat "$GH_CALLS")"
fi

# ── H-w12 item-list 자체가 실패 → 절단과 같이 취급한다 ───────────────────
# 읽지 못했으면 가드할 수 없다. 진행하면 H-w5 와 같은 손상이 난다.
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$2" in
  item-list) exit 1 ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
# ⚠ failed=1: 읽기도 gh 호출이고 그것이 실패했다. `truncated=1` 만 내면 *"보드가 너무 크다"*와
# *"project 스코프가 없다"*가 같은 화면이 되고, 그것이 D9 가 금지한 것이다.
if [ "$OUT" = "wrote=0 skipped=1 unknown=0 col_failed=0 failed=1 truncated=1" ]; then
  ok "H-w12 읽기 실패 → 쓰기 0건 · truncated=1 · failed=1"
else
  bad "H-w12 읽기 실패" "summary=[$OUT]"
fi

# ── H-w13 `guard` 키를 아예 생략하면 가드는 ON 이다 (fail closed) ─────────
# 리뷰가 잡은 실제 구멍이다: 기본값이 False 였고, 위의 모든 케이스가 `guard` 를 명시로
# 넘겨서 초록이었다. 프롬프트(plan.md)는 그 키를 적어주지 않았으므로 배포되면 비멤버
# 쓰기가 전부 무가드로 나가 감독자의 `Blocked` 를 `Backlog` 로 덮었다 — `--reset` 이
# 컬럼 필드를 일부러 건드리지 않으므로 복구도 불가능했다.
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$2" in
  item-list) cat "$GH_ITEMLIST" ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
itemlist 1 '[{"content":{"number":120,"repository":"acme/widget"},"guild board":"Blocked"}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',
         "writes":[{"issue":120,"column":"backlog"}]}'
expect_summary "H-w13 guard 생략 → 가드 ON, 감독자 카드 거부" \
               "wrote=0 skipped=1 unknown=0 col_failed=0 failed=0 truncated=0"
if [ "$(calls_matching item-list)" -ge 1 ]; then
  ok "H-w13 guard 생략 → item-list 를 읽는다"
else
  bad "H-w13 읽지 않았다" "$(cat "$GH_CALLS")"
fi
if [ "$(calls_matching '--single-select-option-id opt_backlog')" -eq 0 ]; then
  ok "H-w13 쓰기가 나가지 않았다"
else
  bad "H-w13 무가드 쓰기가 나갔다" "$(cat "$GH_CALLS")"
fi

# ── H-w14 `repo` 누락 → 64 (설계 §7.1a 가 이 키를 빠뜨리고 있었다) ────────
run_bw '{"number":7,"owner":"@me","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
[ "$RC" -eq 64 ] && ok "H-w14 repo 누락 → 64" || bad "H-w14 repo" "rc=$RC out=[$OUT]"

# ── H-w15 컬럼을 UI 에서 개명하면 가드가 열린다 (실측된 fail-open) ─────────
# `In progress` 를 `Doing` 으로 바꾸고 config 를 안 고친 상태. 역매핑이 실패하면 예전 코드는
# 그것을 *"값이 없다"* 로 읽어 감독자가 개발 중인 카드를 `Backlog` 로 옮기고 `wrote=1` 로
# 보고했다. 값이 있지만 매핑되지 않는 것은 제3의 상태이고, 거부 + 별도 집계여야 한다.
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$2" in
  item-list) cat "$GH_ITEMLIST" ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
itemlist 1 '[{"content":{"number":120,"repository":"acme/widget"},"guild board":"Doing"}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
expect_summary "H-w15 매핑 안 되는 값 → 거부하고 unknown 으로 센다" \
               "wrote=0 skipped=0 unknown=1 col_failed=0 failed=0 truncated=0"
if [ "$(calls_matching item-edit)" -eq 0 ]; then
  ok "H-w15 쓰기가 나가지 않았다"
else
  bad "H-w15 개명된 카드를 덮었다" "$(cat "$GH_CALLS")"
fi

# ── H-w16 필드 값이 객체면(반복 필드 등) 크래시하지 않는다 ────────────────
itemlist 1 '[{"content":{"number":120,"repository":"acme/widget"},"guild board":{"title":"S1"}}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
[ "$RC" -eq 0 ] && expect_summary "H-w16 객체 값 → unknown 처리, 크래시 없음" \
               "wrote=0 skipped=0 unknown=1 col_failed=0 failed=0 truncated=0" \
  || bad "H-w16 크래시" "rc=$RC out=[$OUT]"

# ── H-w17 절단이면 한계를 올려 다시 읽는다 (§7.1a 가 요구한 재읽기) ────────
# 첫 응답은 limit 500 으로 1/2 건, 두 번째는 전량. 예전 코드는 재읽기가 없어서 보드가 500장을
# 넘는 날부터 인테이크 절반이 영구히 멈췄다.
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s
' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$2" in
  item-list)
    if grep -c 'item-list' "$GH_CALLS" | grep -qx 1; then
      cat "$GH_ITEMLIST"
    else
      cat "$GH_ITEMLIST2"
    fi ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
export GH_ITEMLIST2="$WORK/itemlist2.json"
itemlist 2 '[{"content":{"number":120,"repository":"acme/widget"}}]'
printf '{"items":[{"content":{"number":120,"repository":"acme/widget"}},{"content":{"number":121,"repository":"acme/widget"}}],"totalCount":2}
' > "$GH_ITEMLIST2"
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
expect_summary "H-w17 재읽기로 절단이 풀리면 쓴다" \
               "wrote=1 skipped=0 unknown=0 col_failed=0 failed=0 truncated=0"
if [ "$(calls_matching item-list)" -eq 2 ]; then
  ok "H-w17 item-list 를 두 번 읽었다"
else
  bad "H-w17 재읽기 없음" "$(cat "$GH_CALLS")"
fi

# ── H-w18 표시 이름이 겹치면 쓰기 전에 64 ─────────────────────────────────
# 역매핑의 승자가 dict 순서로 정해지고 패자의 카드가 writable 이 된다 — 실측.
DUP='{"backlog":"Backlog","ready":"Backlog","in_progress":"In progress","blocked":"Blocked","in_review":"In review","done":"Done"}'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$DUP"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
[ "$RC" -eq 64 ] && ok "H-w18 표시 이름 중복 → 64" || bad "H-w18" "rc=$RC out=[$OUT]"

# ── H-w19 잘못된 엔트리는 쓰기 시작 전에 64 (절반 쓰고 나가지 않는다) ─────
# `die()` 가 루프 안에서 발화하면 앞 엔트리는 이미 나갔고 뒤는 조용히 버려지고 요약 줄도
# 없다 — 이 스크립트가 문서화한 계약 위반이다.
itemlist 3 '[{"content":{"number":120,"repository":"acme/widget"}},{"content":{"number":121,"repository":"acme/widget"}},{"content":{"number":122,"repository":"acme/widget"}}]'
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s
' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$2" in
  item-list) cat "$GH_ITEMLIST" ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"},
                   {"issue":121,"column":"bogus"},
                   {"issue":122,"column":"backlog"}]}'
if [ "$RC" -eq 64 ] && [ "$(calls_matching item-edit)" -eq 0 ]; then
  ok "H-w19 잘못된 토큰 → 아무 것도 쓰지 않고 64"
else
  bad "H-w19 절반 쓰고 나갔다" "rc=$RC edits=$(calls_matching item-edit)"
fi

# ── H-w20 issue 가 숫자가 아니면 64 (예전엔 ValueError → rc=1) ─────────────
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":"#101","column":"backlog"}]}'
[ "$RC" -eq 64 ] && ok "H-w20 issue 가 #101 → 64" || bad "H-w20" "rc=$RC out=[$OUT]"

# ── H-w21 totalCount 가 없으면 fail-closed ────────────────────────────────
printf '{"items":[{"content":{"number":120,"repository":"acme/widget"}}]}
' > "$GH_ITEMLIST"
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
expect_summary "H-w21 totalCount 부재 → 쓰지 않는다" \
               "wrote=0 skipped=1 unknown=0 col_failed=0 failed=0 truncated=1"

# ── H-w22 다른 레포 이슈는 repository 키가 없어도 내 것이 아니다 ──────────
itemlist 2 '[{"content":{"number":120},"guild board":"Blocked"},
             {"content":{"number":121,"repository":"acme/widget"}}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":121,"column":"backlog"}]}'
expect_summary "H-w22 repository 부재 항목은 무시된다" \
               "wrote=1 skipped=0 unknown=0 col_failed=0 failed=0 truncated=0"

# ── H-w23 owned: Guild 가 소유하지 않은 필드에는 쓰지 않는다 (D1 을 규칙으로) ──
# 설계 §4.3 은 `owned` 를 *"D1 을 의도가 아니라 규칙으로 만드는 유일한 방법"* 이라고 부르는데
# 배포 시점에는 아무도 읽지 않는 죽은 키였다. config 를 손으로 고쳐 `fields.needs_human` 을
# `Assignees` 로 돌려놓으면 Guild 가 사람의 필드에 쓰고, 그것을 거부하는 곳이 없었다.
itemlist 1 '[{"content":{"number":101,"repository":"acme/widget"}}]'
OWNED='["Guild board","Order","Depends on","Needs human","Sprint"]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"owned":'"$OWNED"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready","fields":{"Assignees":"someone"}}]}'
if [ "$RC" -eq 64 ] && [ "$(calls_matching item-edit)" -eq 0 ]; then
  ok "H-w23 owned 밖의 필드 → 아무 것도 쓰지 않고 64"
else
  bad "H-w23 소유하지 않은 필드에 썼다" "rc=$RC edits=$(calls_matching item-edit)"
fi
# owned 안의 필드는 통과한다 — 규칙이 정상 경로를 막으면 안 된다
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"owned":'"$OWNED"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready","fields":{"Order":"1"},
                    "clear":["Needs human"]}]}'
expect_summary "H-w23 owned 안의 필드는 통과한다" \
               "wrote=1 skipped=0 unknown=0 col_failed=0 failed=0 truncated=0"
# 컬럼 필드 자체가 owned 에 없으면 그것도 64
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Other field",
         "columns":'"$COLS"',"owned":'"$OWNED"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready"}]}'
[ "$RC" -eq 64 ] && ok "H-w23 컬럼 필드가 owned 밖 → 64" || bad "H-w23 컬럼 필드" "rc=$RC"
# owned 를 생략하면 예전처럼 동작한다 (선택적 키다)
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready","fields":{"Assignees":"someone"}}]}'
[ "$RC" -eq 0 ] && ok "H-w23 owned 생략은 하위 호환" || bad "H-w23 하위 호환" "rc=$RC"

# ── H-w24 col_failed 는 컬럼 실패만 센다 (Order 실패와 섞이지 않는다) ─────
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$*" in *"--field-id PVTF_order"*) exit 1 ;; esac
case "$2" in item-list) cat "$GH_ITEMLIST" ;; esac
exit 0
STUB
chmod +x "$BIN/gh"
itemlist 1 '[{"content":{"number":101,"repository":"acme/widget"}}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready","fields":{"Order":"1"}}]}'
expect_summary "H-w24 컬럼은 성공하고 Order 만 실패 → col_failed=0" \
               "wrote=1 skipped=0 unknown=0 col_failed=0 failed=1 truncated=0"
# 그리고 컬럼이 실패하면 이슈 번호가 stderr 로 나온다 — 손으로 고칠 수 있게
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$*" in *"--field-id PVTSSF_col"*) exit 1 ;; esac
case "$2" in item-list) cat "$GH_ITEMLIST" ;; esac
exit 0
STUB
chmod +x "$BIN/gh"
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready"}]}'
if grep -qF '#101' "$WORK/err.txt"; then
  ok "H-w24 컬럼 실패한 이슈 번호가 stderr 로 나온다"
else
  bad "H-w24 이슈 번호 없음" "$(cat "$WORK/err.txt")"
fi

# ── H-w25 columns 가 dict 이 아니면 64 (AttributeError → rc=1 이었다) ─────
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":[],"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready"}]}'
[ "$RC" -eq 64 ] && ok "H-w25 columns 가 배열 → 64" || bad "H-w25" "rc=$RC out=[$OUT]"

# ── H-w26 issue 를 int 로 정규화해서 URL 에 쓴다 ──────────────────────────
# 사전 검증은 int() 가 되는지만 봤고 쓰기 루프는 원값을 URL 에 넣었다: `120.9` 가
# `.../issues/120.9` 로 나가고 `wrote=1` 로 보고됐다.
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s
' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
exit 0
STUB
chmod +x "$BIN/gh"
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":false,"read":false,
         "writes":[{"issue":120.9,"column":"ready"},{"issue":" 121 ","column":"ready"}]}'
if [ "$(calls_matching 'issues/120 ')" -ge 1 ] && [ "$(calls_matching 'issues/121 ')" -ge 1 ]    && [ "$(calls_matching 'issues/120.9')" -eq 0 ]; then
  ok "H-w26 issue 가 int 로 정규화돼 URL 에 들어간다"
else
  bad "H-w26 URL 에 원값이 들어갔다" "$(cat "$GH_CALLS")"
fi

# ── H-w27 노드 ID 해석이 실패하면 아무 것도 쓰지 않는다 ───────────────────
# 이름 기반 쓰기는 104포인트, 노드 ID 기반은 1포인트다(실측, 각 4회). 해석이 실패했을 때
# 이름 형태로 되돌아가면 제거하려던 비용이 그대로 돌아오므로, 거부가 옳다.
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
case "$2" in
  view)       exit 1 ;;
  item-list)  cat "$GH_ITEMLIST" ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
itemlist 1 '[{"content":{"number":101,"repository":"acme/widget"},"id":"PVTI_x"}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready"}]}'
if [ "$RC" -eq 64 ] && [ "$(calls_matching item-edit)" -eq 0 ]; then
  ok "H-w27 project id 를 못 얻으면 쓰지 않고 64"
else
  bad "H-w27 해석 실패 후 쓰기가 나갔다" "rc=$RC edits=$(calls_matching item-edit)"
fi

# field-list 가 잘려 오면 필요한 필드가 빠졌는지 알 수 없다 → 거부
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
case "$2" in
  view)       printf '{"id":"PVT_probe","number":7}\n' ;;
  field-list) printf '%s\n' '{"fields":[{"id":"PVTSSF_col","name":"Guild board","type":"ProjectV2SingleSelectField","options":[{"id":"o1","name":"Backlog"}]}],"totalCount":9}' ;;
  item-list)  cat "$GH_ITEMLIST" ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready"}]}'
# ⚠ 이유까지 본다. 이 케이스의 픽스처는 옵션도 하나뿐이라, 짧은-목록 거부를 지워도 **옵션
# 부재**로 죽어서 통과했다 — 무엇을 검사하는지 알 수 없는 상태였다.
if [ "$RC" -eq 64 ] && [ "$(calls_matching item-edit)" -eq 0 ] \
   && grep -qF 'partial field map' "$WORK/err.txt"; then
  ok "H-w27 field-list 가 잘리면 그 이유로 64"
else
  bad "H-w27 잘린 필드 목록" "rc=$RC edits=$(calls_matching item-edit) err=[$(cat "$WORK/err.txt")]"
fi

# config 의 컬럼 이름이 보드의 옵션에 없으면 쓰기 전에 64 — 개명을 조용히 지나치지 않는다
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$2" in
  item-list) cat "$GH_ITEMLIST" ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
# (a) 이 호출이 **쓰는** 토큰이 보드에 없으면 → 쓰기 전에 64
MISSING_W='{"backlog":"Backlog","ready":"없는 이름","in_progress":"In progress","blocked":"Blocked","in_review":"In review","done":"Done"}'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$MISSING_W"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready"}]}'
if [ "$RC" -eq 64 ] && [ "$(calls_matching item-edit)" -eq 0 ]; then
  ok "H-w27 쓰려는 컬럼이 보드에 없으면 64"
else
  bad "H-w27 없는 옵션으로 썼다" "rc=$RC edits=$(calls_matching item-edit)"
fi

# (b) ⚠ 이 호출이 **쓰지 않는** 토큰이 보드에 없으면 → 죽지 않는다. 여섯 개를 다 검증하면
#     `plan` 이 건드리지도 않는 컬럼(감독자 소유 넷)의 개명이 `plan` 의 보드 단계 전체를
#     죽였고, `--reset` 은 컬럼 필드를 아예 안 쓰는데도 같이 죽었다 — 요약 줄도 없이 64.
#     문서 세 곳이 그 상황에 `unknown=<n>` 과 "config 한 줄 고치세요" 를 약속한다.
MISSING_U='{"backlog":"Backlog","ready":"Ready","in_progress":"In progress","blocked":"Blocked","in_review":"In review","done":"없는 이름"}'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$MISSING_U"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready"}]}'
expect_summary "H-w27 쓰지 않는 컬럼의 개명은 죽이지 않는다" \
               "wrote=1 skipped=0 unknown=0 col_failed=0 failed=0 truncated=0"
if grep -qF 'not on the board' "$WORK/err.txt"; then
  ok "H-w27 그래도 stderr 로 알린다"
else
  bad "H-w27 조용히 지나갔다" "$(cat "$WORK/err.txt")"
fi

# (c) --reset 형태(컬럼 키 없음)는 컬럼이 개명돼도 돌아야 한다
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$MISSING_U"',"owned":["Guild board","Order"],
         "guard":false,"read":false,
         "writes":[{"issue":101,"clear":["Order"]}]}'
expect_summary "H-w27 --reset 형태는 컬럼 개명과 무관하다" \
               "wrote=1 skipped=0 unknown=0 col_failed=0 failed=0 truncated=0"

# ── 노드 ID 배선을 실제로 고정한다 ─────────────────────────────────────────
# ⚠ 첫 버전은 *"--field 와 --value 가 없고 --field-id 가 둘 이상"* 만 봤다. 그래서 변이 셋이
# 살아남았다: (a) 읽어온 항목 id 를 안 쓰고 카드마다 item-add 를 내는 것, (b) --project-id 를
# 빼는 것, (c) 튜플 인덱스를 틀려 **표시 값**을 --id 로 넘기는 것. 이 전환의 요지가 바로 그
# 배선이므로, 세 가지를 전부 이름으로 검사한다.
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$2" in
  item-list) cat "$GH_ITEMLIST" ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
# ⚠ `read: true` — 읽어온 id 를 쓰는지 보려면 읽어야 한다. `guard: false` 라 판정은 그대로 꺼져 있다.
itemlist 1 '[{"content":{"number":101,"repository":"acme/widget"},"id":"PVTI_x"}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":false,"read":true,
         "writes":[{"issue":101,"column":"ready","fields":{"Order":"1"}}]}'
if [ "$(calls_matching '--field ')" -eq 0 ] && [ "$(calls_matching '--value ')" -eq 0 ] \
   && [ "$(calls_matching '--field-id')" -ge 2 ]; then
  ok "H-w27 이름 기반 쓰기가 남아 있지 않다 (104포인트 형태)"
else
  bad "H-w27 이름 기반 쓰기가 남아 있다" "$(cat "$GH_CALLS")"
fi
# (a) 읽어온 항목 id 를 쓴다 — item-add 를 내지 않는다
if [ "$(calls_matching 'item-add')" -eq 0 ]; then
  ok "H-w27 읽어온 항목 id 를 쓴다 (item-add 0건)"
else
  bad "H-w27 id 를 버리고 item-add 를 냈다" "$(cat "$GH_CALLS")"
fi
# (b) --project-id 가 모든 쓰기에 붙는다
if [ "$(calls_matching '--project-id PVT_probe')" -ge 2 ]; then
  ok "H-w27 --project-id 가 붙는다"
else
  bad "H-w27 --project-id 가 빠졌다" "$(cat "$GH_CALLS")"
fi
# (c) --id 가 **항목 id** 다 — 표시 값이나 이슈 번호가 아니다
if [ "$(calls_matching '--id PVTI_x')" -ge 2 ]; then
  ok "H-w27 --id 가 읽어온 항목 노드 id 다"
else
  bad "H-w27 --id 가 항목 id 가 아니다" "$(cat "$GH_CALLS")"
fi

# ── project view 가 200 을 내지만 id 가 없으면 → 쓰지 않는다 ────────────────
# 기존 검사는 `view` 를 exit 1 로만 만들어 `ok is False` 분기만 덮었다.
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
case "$2" in
  view)       printf '{"number":7}\n'; exit 0 ;;
  field-list) . "$GH_IDS"; gh_ids "$@" ;;
  item-list)  cat "$GH_ITEMLIST" ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":false,"read":false,
         "writes":[{"issue":101,"column":"ready"}]}'
# ⚠ 메시지까지 본다. 예전 코드는 실패마다 빈 map 을 돌려줬고, 그러면 **다음 줄의 필드 검사**가
# 죽였다 — 즉 이 검사는 "project id 를 검증한다"가 아니라 "어떤 이유로든 64가 난다"만 봤고,
# 검증을 지워도 통과했다. 리뷰가 *"엉뚱한 이유로 통과"*라고 부른 그 패턴이다.
if [ "$RC" -eq 64 ] && [ "$(calls_matching item-edit)" -eq 0 ] \
   && grep -qF 'returned no node id' "$WORK/err.txt"; then
  ok "H-w27 view 가 id 없이 200 을 내면 그 이유로 64"
else
  bad "H-w27 id 없는 view" "rc=$RC edits=$(calls_matching item-edit) err=[$(cat "$WORK/err.txt")]"
fi

# ── H-w28 소유 목록의 불변식 ────────────────────────────────────────────────
# `if current_tok in SUPERVISOR_OWNED` 는 두 목록이 서로 소인 동안 **도달 불가**하다 — 지워도
# 스위트가 초록이었다(변이로 확인). 목록은 입력이 아니라 모듈 상수이므로 검사가 겹침을 만들 수
# 없다. 그래서 백스톱을 검사로 덮는 대신 **불변식을 명시**했다: `_check_ownership_lists()` 가
# 시작 시 겹침을 exit 64 로 거부한다. 아래는 그 불변식이 살아 있을 때의 정상 동작을 고정한다.
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$2" in
  item-list) cat "$GH_ITEMLIST" ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
itemlist 1 '[{"content":{"number":120,"repository":"acme/widget"},"guild board":"In progress"}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
expect_summary "H-w28 in_progress 는 어느 경우에도 거부된다" \
               "wrote=0 skipped=1 unknown=0 col_failed=0 failed=0 truncated=0"
if [ "$(calls_matching item-edit)" -eq 0 ]; then
  ok "H-w28 감독자 소유 카드에 쓰기가 나가지 않았다"
else
  bad "H-w28 감독자 카드에 썼다" "$(cat "$GH_CALLS")"
fi

# ── H-w29 field-list 의 id 없는 필드는 건너뛴다 (exit 1 이 아니라) ─────────
# `None` 이 argv 까지 가면 subprocess 가 TypeError 를 내고 rc=1 이다 — 문서화된 {0,64} 밖이다.
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s
' "$*" >> "$GH_CALLS"
case "$2" in
  view)       printf '{"id":"PVT_probe","number":7}
'; exit 0 ;;
  field-list) printf '%s
' '{"fields":[{"name":"Broken","type":"ProjectV2Field"},{"id":"PVTSSF_col","name":"Guild board","type":"ProjectV2SingleSelectField","options":[{"id":"opt_ready","name":"Ready"}]},{"id":"PVTF_order","name":"Order","type":"ProjectV2Field"}],"totalCount":3}'; exit 0 ;;
  item-list)  cat "$GH_ITEMLIST" ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
itemlist 1 '[{"content":{"number":101,"repository":"acme/widget"},"id":"PVTI_x"}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":{"ready":"Ready"},"guard":false,"read":true,
         "writes":[{"issue":101,"column":"ready","fields":{"Order":"1"}}]}'
if [ "$RC" -eq 0 ] && [ "$(calls_matching '--field-id PVTF_order')" -ge 1 ]; then
  ok "H-w29 id 없는 필드를 건너뛰고 나머지는 쓴다 (rc=0)"
else
  bad "H-w29 id 없는 필드" "rc=$RC out=[$OUT] err=[$(cat "$WORK/err.txt")]"
fi
# 그 필드에 쓰라고 하면 실패로 세고, 죽지 않는다
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":{"ready":"Ready"},"guard":false,"read":true,
         "writes":[{"issue":101,"column":"ready","fields":{"Broken":"x"}}]}'
if [ "$RC" -eq 0 ]; then
  ok "H-w29 id 없는 필드에 쓰라고 해도 rc=0 (세고 넘어간다)"
else
  bad "H-w29 rc" "rc=$RC out=[$OUT]"
fi

# ── H-w30 필드 이름의 `"` 가 jq 프로그램을 깨뜨리지 않는다 ──────────────────
# 깨지면 gh 가 실패하고 그것이 read_failed/truncated 로 나타난다 — 가드는 조용히 꺼지고
# 무가드 멤버 시딩은 계속 쓴다. 즉 이스케이프 누락이 가드 무력화로 이어진다.
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s
' "$*" >> "$GH_CALLS"
. "$GH_IDS"; gh_ids "$@"
case "$2" in
  item-list) cat "$GH_ITEMLIST" ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"
itemlist 1 '[{"content":{"number":120,"repository":"acme/widget"}}]'
run_bw '{"number":7,"owner":"@me","repo":"acme/widget","field":"Guild board",
         "columns":'"$COLS"',"guard":true,"read":true,
         "writes":[{"issue":120,"column":"backlog"}]}'
if grep -qF '"guild board": .["guild board"]' "$GH_CALLS"; then
  ok "H-w30 jq 의 필드 키가 JSON 으로 인용된다"
else
  bad "H-w30 jq 인용" "$(grep -o -- '--jq.*' "$GH_CALLS" | head -1)"
fi

echo
printf '  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
