---
title: Architecture
status: draft
updated: {{DATE}}
---
# Architecture — {{PROJECT_NAME}}

> 테크리드·개발자가 참조하는 구조 기준. init이 structure-scan으로 초안을 작성. `confirmed` 시 경계 게이트의 기준이 된다.
>
> ⚠️ **상위 골격만 (drift 방지 — 항목 2a)**: 이 문서는 **느리게 변하는 상위 골격**(레이어·경계·확장점)만 담는다. 빠르게 변하는 **세부 결합 사실**(어떤 파일이 함께 바뀌는지, 특정 함정)은 여기 나열하지 말고 **⑥ 지식(`.claude/guild/knowledge/`)**에 둔다 — evolve가 자동 갱신하는 곳. 세부를 여기 적으면 기능마다 낡는다. execute의 tech-writer가 아키텍처 영향 변경 시 이 골격을 동기화한다(`draft`→즉시, `confirmed`→제안).

## 개요 (Overview)
{{ARCHITECTURE}}
<!-- 큰 그림: 어떤 종류의 앱인가, 주요 파트. -->

## 레이어 & 모듈 경계 (Layers & Boundaries)
{{BOUNDARIES}}
<!-- 레이어(ui/domain/data 등), 모듈 경계, 무엇이 무엇에 의존해도/안 되는가. -->

## 디렉터리 구조 (Directory Map)
{{DIRECTORY_MAP}}
<!-- 주요 디렉터리와 각각의 책임. -->

## 확장점 (Extension Seams)
{{SEAMS}}
<!-- DI 지점, 플러그인 포인트, 새 기능을 붙이는 표준 위치. -->

## 핵심 결합 & 함정 (Key Couplings & Pitfalls)
{{PITFALLS}}
<!-- 상위 수준의 구조적 결합만 (예: "결제는 반드시 도메인 레이어 경유"). 파일 단위의 세부 함정·co-change 사실은 여기 말고 ⑥ 지식으로 — evolve가 유지한다(항목 2a). -->
