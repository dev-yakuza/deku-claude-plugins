**인수 기준 (AC)**

- AC #1: The settings screen "quiz screen" section shows a "quiz type" row. [must]
- AC #2: Tapping the row opens the existing selector sheet; its sections and the select-all behaviour are the same as when opened from the review screen. [must] - detail: the sheet is not copied
- AC #3: The summary on the right reflects the current selection and updates when it changes. [must]
- AC #4: The selection survives an app restart. [should]

**이슈 요구 ↔ AC 대응표**

| 이슈 요구 | AC |
|---|---|
| Show the quiz type in settings | AC #1 |
| Reuse the selector sheet | AC #2, AC #3 |
| Keep the choice after restart | AC #4 |

**가정과 검토할 결정**

- 가정: The settings screen may import the review screen's selector (the layering rule is still a draft).
- 가정: The summary label for "all" is decided in design.
- major 지적 (review-design): `src/settings.ts:12` — the summary label is computed twice
- 바뀐 검증 경로: `test/settings_test.dart`
- 불안정(flaky) 표시: `test` 시도 1 — 실패 뒤 같은 트리 재실행에서 통과했습니다. 판정은 실패 그대로입니다(I8)
- 거절된 쓰기 (implement 시도 1): Write `/wt/.claude/agents/x.md`
- 머지 뒤 되돌리기 어려운 변경 (hard-to-revert, notify): `db/migrations/007_quiz.sql`

**검증 범위**

엔진이 기록한 사실(facts)로 만든 표입니다 — 역할이 쓰지 않았습니다.

| 단계 | 명령 | 결과 | 시도 | 검증한 HEAD |
|---|---|---|---|---|
| `ac-format` | `ac-format` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `ac-coverage` | `ac-coverage` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `setup` | `setup` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `lint` | `lint` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `typecheck` | `typecheck` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `test` | `test` | 통과 (종료 코드 0) | 2 | `cccccccccccc` |
| `build` | `build` | 건너뜀 (not checked locally (Xcode in srt)) | — | — |
| `e2e` | `e2e` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |
| `verify-gate` | `verify-gate` | 통과 (종료 코드 0) | 1 | `cccccccccccc` |

**로컬에서 확인하지 않은 항목**

- e2e_test/e2e_test — needs an Android emulator
- build: flutter build windows — other platform

**Manual Test Checklist**

- [ ] Open settings → quiz type row is shown
- [ ] Restart the app → the choice is kept

**범위 밖 발견**

- debt · `lib/settings.dart` — old layout helper (implement)
- bug · `lib/review_screen.dart` — select-all ignores #12 @alice (review-audit)

**범위 밖이지만 포함한 수정**

- test-gap · `test/sheet_test.dart` — the sheet had no test (review-audit)

**측정용 사실 경고**: 1건
