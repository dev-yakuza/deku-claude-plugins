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
<!-- 기본: 테스트 러너의 원문 출력을 캡처하고 자기보고와 대조해 일치할 때만 완료 인정. 불일치 시 원문이 이긴다.
     검증 약화 금지(INV2) — `gate_precommit.py`가 실제로 커밋 시점에 차단하는 세 가지: (1) 테스트 파일 삭제,
     (2) skip/disable 마커 추가(`xit`/`@Skip`/`pytest.mark.skip` 등), (3) assertion 순감소(추가분 대비 3줄 이상
     삭제). 여기 규칙을 (1)(2)만 언급하고 (3)을 빠뜨리지 않는다 — 세 게이트 모두 이 verify 규칙이 실제로
     지키려는 것과 동일한 INV2다. -->

## 완료 정의 (Definition of Done)
{{DOD}}
<!-- 이슈가 guild:done이 되기 위한 조건. 예: AC 전부 충족 + 관련 테스트 green + QA 통과.
     ⚠️ "PR 사람 승인"을 조건에 넣지 않는다 — guild:done은 QA 완료 시점에 붙는 라벨로, PR 사람 리뷰·머지보다
     항상 먼저 일어난다(qa.md/dev.md). 이 조건을 문자 그대로 DoD에 넣으면 test 스테이지의 자동 verify 체크가
     영원히 충족 불가능해진다 — "완료"는 자동화된 검증 + agent-doable QA를 뜻하고, 사람 PR 승인은 그 이후
     별도로 오는 관문이다(INV1, 절대 무인 머지 없음). -->
