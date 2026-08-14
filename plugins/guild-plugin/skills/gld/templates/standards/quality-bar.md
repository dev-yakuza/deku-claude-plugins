---
title: Quality Bar
status: draft
updated: {{DATE}}
---
# Quality Bar — {{PROJECT_NAME}}

> "충분히 좋다"의 정의. `/gld review`의 적대적 프리스캔이 쓰는 2축(Standards/Spec) 중 Standards 축의 기준 — verify(test 스테이지)는 이 2축 프레이밍을 쓰지 않고 `docs/standards/verification.md`의 DoD/verify 규칙만 참조한다(원문 증거 vs 자기보고 대조가 전부). init이 초안, 사용자가 확정.

## 반드시 통과 (Must Pass)
{{MUST_PASS}}
<!-- 머지 전 반드시 충족. 예: 타입체크 통과, 린트 클린, 관련 테스트 green, 시크릿 미포함. -->

## 코드 품질 기대치 (Code Quality Expectations)
{{QUALITY_EXPECTATIONS}}
<!-- 가독성, 중복 회피, 함수 크기 등 이 레포의 눈높이. **주석 최소주의를 반드시 포함**: 기본 0(비자명 WHY만) · 금지 = 스펙/근거 중복(근거·수치는 docs/specs에), 이슈추적 메타데이터(TC-xx·AC#·이슈번호), 자명한 서술 · 추적성은 서술적 테스트/심볼 이름으로. -->

## 허용 트레이드오프 (Accepted Trade-offs)
{{TRADEOFFS}}
<!-- 의도적으로 낮춘 기준과 사유(수용 위험). 사람 QA로 넘기는 항목은 "진짜 자동화 불가능한 것"만 남긴다 —
     프로젝트 자체 테스트 프레임워크(유닛/위젯 레벨)로 증명 가능한 구조/행동 단언은 여기 적지 말고
     테스트로 만든다(qa.md 참고). 실 외부 의존(설치·인증·비용이 필요한 바이너리/API)이라도 QA 실행
     환경에 이미 자격증명이 있고 side effect를 안전하게 격리할 수 있으면, attended 세션에서 QA가
     1회성 스크래치 하네스로 직접 확인한다 — 이것도 사람 QA로 적지 않는다(qa.md 참고). -->
