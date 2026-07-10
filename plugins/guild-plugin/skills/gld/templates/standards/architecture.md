---
title: Architecture
status: draft
updated: {{DATE}}
---
# Architecture — {{PROJECT_NAME}}

> 아키텍트·개발자가 참조하는 구조 기준. init이 structure-scan으로 초안을 작성. `confirmed` 시 경계 게이트의 기준이 된다.

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
<!-- 함께 바뀌는 파일, 조심할 결합, 과거의 함정. -->
