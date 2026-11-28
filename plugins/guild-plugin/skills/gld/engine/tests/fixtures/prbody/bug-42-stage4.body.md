<!-- guild:sprint:stack -->
**스택 PR (스프린트 #700)**

- 스택: 이 PR은 #101 위에 있다 — 먼저 머지할 것
- 이 diff는 `gld/101` 위의 변경만 담습니다
- draft — 아래 PR이 머지되면 `/gld sprint sync`가 기본 브랜치를 머지·검증하고 ready로 바꿉니다
<!-- /guild:sprint:stack -->

**무엇을 바꿨나**

리더(LLM)가 diff를 읽고 쓴 요약입니다 — 엔진이 확인한 사실이 아닙니다.

- lib/settings.dart adds the quiz-type row and keeps the choice across restarts.
- test/settings_test.dart covers the row and the restart; #12 @bob stays plain text.

**사람이 확인할 것 (Manual Test Checklist)**

- [ ] Open settings → quiz type row is shown
- [ ] Restart the app → the choice is kept

**가정과 검토할 결정**

- 가정: The settings screen may import the review screen's selector (the layering rule is still a draft).
- 가정: The summary label for "all" is decided in design.
- major 지적 (review-design): `src/settings.ts:12` — the summary label is computed twice
- 바뀐 검증 경로: `test/settings_test.dart`
- 사람이 허용한 기존 테스트 수정(내용만): `test/settings_test.dart` — 이 PR에서 바뀌었습니다
- 사람이 허용한 기존 테스트 수정(내용만): `test/x.dart` — 이 PR에서 바뀌지 않았습니다
- 불안정(flaky) 표시: `test` 시도 1 — 실패 뒤 같은 트리 재실행에서 통과했습니다. 판정은 실패 그대로입니다(I8)
- 거절된 쓰기 (implement 시도 1): Write `/wt/.claude/agents/x.md`
- 되돌리기 어려운 변경 (hard-to-revert, notify): `db/migrations/007_quiz.sql` (implement)
- 되돌리기 어려운 변경 (external-side-effect, human-decision): `deploy/app.yaml` (implement) — 사람 승인 2026-11-25T01:00:00Z
- 저장소 설정이 기본보다 낮춘 수준: human-executed 기본 notify → proceed

**범위 밖 발견**

- [후속 이슈] D1 · bug · `lib/review_screen.dart` — select-all ignores #12 @alice
- [무시한 발견] D2 · debt · `lib/settings.dart` — old layout helper
- [중복] D4 · test-gap · `test/sheet_test.dart` — the sheet had no test
- 보안 발견 1건 — 내용은 PR 본문에 쓰지 않습니다(E21). 비공개 저장소면 후속 이슈, 아니면 엔진 로컬 기록(`/gld status`)

**분리한 후속 이슈**

- 이 PR 뒤 `create-followups` 단계가 처리합니다: 후속 이슈 2건 · 중복 댓글 1건

**범위 밖이지만 포함한 수정**

- F1 · bug · `lib/sheet.dart` — blocks AC 2 @bob (발견 tech-lead/design, 처리 implement, 리더 판정 keep)
- F2 · security — 내용은 쓰지 않습니다(E21) (발견 auditor/review-audit, 처리 fix-discovery, 리더 판정 keep)

**근거와 기록** — 아래 항목은 접혀 있습니다. 제목을 누르면 펼쳐집니다.

<details>
<summary>인수 기준 (AC) — 4개</summary>

- AC #1: The settings screen "quiz screen" section shows a "quiz type" row. [must]
- AC #2: Tapping the row opens the existing selector sheet; its sections and the select-all behaviour are the same as when opened from the review screen. [must] - detail: the sheet is not copied
- AC #3: The summary on the right reflects the current selection and updates when it changes. [must]
- AC #4: The selection survives an app restart. [should]

</details>

<details>
<summary>인수 기준 판정 (리더) — met 3 · manual 1</summary>

리더(LLM)가 쓴 판정입니다 — 엔진이 확인한 사실이 아닙니다. 엔진은 모든 AC의 판정 유무, `unmet` 없음, `manual` AC의 체크리스트 참조만 확인했습니다.

| AC | 판정 | 근거 (리더) |
|---|---|---|
| AC #1 | met | settings.ts adds the row; test/settings_test.dart covers it |
| AC #2 | met | same sheet \| reused @alice |
| AC #3 | manual (수동 확인) | visual check, see the checklist |
| AC #4 | met | restart test |

</details>

<details>
<summary>이슈 요구 ↔ AC 대응표</summary>

| 이슈 요구 | AC |
|---|---|
| Show the quiz type in settings | AC #1 |
| Reuse the selector sheet | AC #2, AC #3 |
| Keep the choice after restart | AC #4 |

</details>

<details>
<summary>검증 범위</summary>

엔진이 기록한 사실(facts)로 만든 표입니다 — 역할이 쓰지 않았습니다.

| 단계 | 명령 | 결과 | 시도 | 검증한 HEAD |
|---|---|---|---|---|
| `ac-format` | `ac-format` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `ac-coverage` | `ac-coverage` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `setup` | `setup` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `repro-red` | `repro-red` | 통과 (엔진 판정 — 조건 충족) | 2 | `cccccccccccc` |
| `lint` | `lint` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `typecheck` | `typecheck` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `test` | `test` | 통과 (종료 코드 0) | 2 | `cccccccccccc` |
| `build` | `build` | 건너뜀 (not checked locally (Xcode in srt)) | — | — |
| `e2e` | `e2e` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `verify-gate` | `verify-gate` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |

</details>

<details>
<summary>재현 증거 (버그)</summary>

엔진이 기록한 사실(facts)로 만든 표입니다. 판정 트리 = 기록 base의 새 worktree + `reproduce`가 바꾼 테스트 파일(HEAD blob).

| 사실 | 값 |
|---|---|
| 범위 (`reproduce` 시도 1의 변경이 test-code glob 안) | 통과 |
| 판정 트리에 올린 파일 | `test/settings_test.dart` |
| 판정 트리 `test` 1회 (빨강이어야 함) | 종료 코드 1 |
| 판정 트리 `test` 2회 (빨강이어야 함) | 종료 코드 1 |
| 기록 base `test` (녹색이어야 함) | 종료 코드 0 |
| 최종 `test` (수정 뒤 HEAD `cccccccccccc`) | 종료 코드 0 |

</details>

<details>
<summary>뮤테이션 실행</summary>

엔진이 선언된 변경을 HEAD에 하나씩 적용하고 `test`를 실행한 사실입니다. 바꿀 자리와 내용은 개발자 역할이 골랐습니다. `killed`만 증거이고, 어떤 AC가 충족됐는지는 리더가 판정합니다.

- HEAD `cccccccccccc` · 대조 실행(변경 없음): 종료 코드 0

| id | AC | 파일 | 바꾼 글 | 넣은 글 | 결과 |
|---|---|---|---|---|---|
| M1 | 1, 2 | `lib/sheet.dart` | `hint: 'on' \| x` | (없음) | killed — 테스트가 빨강, 종료 코드 1 |
| M2 | 2 | `test/a_test.dart` | `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa…` | `b` | refused — 실행 안 함 (`verification-path`) |
| M3 | 2 | `lib/b.dart` | `b` | `c` | survived — 테스트가 녹색 그대로(증거 아님), 종료 코드 0 |

</details>

<details>
<summary>로컬에서 확인하지 않은 항목 — 2개</summary>

- e2e_test/e2e_test — needs an Android emulator
- build: flutter build windows — other platform

</details>

<details>
<summary>리더 결정 — 3건</summary>

- check#1 `plan-gate`: `plan` · 이유 `fits-template`
- leader#1 `blocked`: `rerun` → `implement` · 이유 `real-defect` — Rerun implement: the sheet is copied, not reused.
- check#1 `done-gate`: `approve` · 이유 `acceptance-met` — Ship it.

</details>

<details>
<summary>새 템플릿 후보</summary>

**새 템플릿 후보**: 예 — 리더가 표시했거나 plan이 카탈로그 단계를 2개 이상 더했습니다(evolve 입력)

</details>

<details>
<summary>엔진 기록 — 측정용 사실 경고 1건</summary>

**측정용 사실 경고**: 1건

</details>

