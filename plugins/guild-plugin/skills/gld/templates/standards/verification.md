---
title: Verification
status: draft
updated: {{DATE}}
---
# Verification — {{PROJECT_NAME}}

> 어떻게 "됐다"를 증명하는가. verify 게이트의 기준. init이 command-scan으로 초안을 작성.

## 검증 커맨드 (Verification Commands)
| 목적 | 커맨드 |
|---|---|
| 테스트(유닛) | `{{TEST_CMD}}` |
| E2E/통합 | `{{E2E_CMD}}` |
| 린트 | `{{LINT_CMD}}` |
| 타입체크 | `{{TYPECHECK_CMD}}` |
| 빌드 | `{{BUILD_CMD}}` |

<!-- init: E2E/통합 테스트가 없으면 그 행을 삭제한다. 있으면 커맨드를 채운다. M1은 E2E를 검출·기록만 하고 자동 실행은 하지 않는다(후속 마일스톤) — 그 취지를 verify 게이트 규칙에 한 줄로 남긴다. -->

## verify 게이트 규칙 (Verify Gate Rules)
{{VERIFY_RULES}}
<!-- 기본: 테스트 러너의 원문 출력을 캡처하고 자기보고와 대조해 일치할 때만 완료 인정. 불일치 시 원문이 이긴다. 검증을 약화(테스트 삭제·스킵)시키는 변경은 금지(INV2). -->

## 완료 정의 (Definition of Done)
{{DOD}}
<!-- 이슈가 done이 되기 위한 조건. 예: AC 전부 충족 + 관련 테스트 green + PR 사람 승인. -->
