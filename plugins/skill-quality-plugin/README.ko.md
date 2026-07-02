# skill-quality-plugin

Claude Code 스킬 파일을 구조화된 38개 항목 품질 루브릭으로 평가합니다. 마켓플레이스나 팀 라이브러리에 배포하기 전에 실행하세요.

## 왜 필요한가?

description이 없거나, 트리거 조건이 모호하거나, 구조적 오류가 있는 스킬은 Claude가 언제/어떻게 호출해야 할지 판단하지 못합니다. 이 플러그인이 사용자에게 도달하기 전에 그런 문제를 잡아냅니다.

## 설치

`.claude-plugin/marketplace.json`에 추가하거나 Claude Code 플러그인 마켓플레이스를 통해 설치하세요.

## 사용법

```
/skill-quality check [path] [--depth=shallow|deep] [--rules-only] [--json]
/skill-quality report [path] [--depth=shallow|deep] [--json]
/skill-quality rubric
/skill-quality help
```

### check — 단일 스킬 평가

```bash
# 현재 디렉토리의 스킬 검사
/skill-quality check .

# 특정 스킬 검사
/skill-quality check ./plugins/my-plugin/skills/my-skill

# 빠른 규칙 검사만 (LLM 모델 검사 없음)
/skill-quality check . --rules-only

# 깊이 있는 검사 (opus 모델 사용)
/skill-quality check . --depth=deep

# CI/CD용 JSON 출력
/skill-quality check . --json
```

**출력 예시:**

```
/skill-quality check: plugins/my-plugin/skills/my-skill
══════════════════════════════════════════════════════════════════════
Grade: A  (rubric v1.0)

MAJOR (2)
  [T1] WHAT not in description — "helps with tasks" is too vague
       Fix: Add what the skill does: "Generates unit tests for..."
  [C1] No org-specific knowledge — body reads as generic instructions
       Fix: Add project-specific constraints or examples

Suggestions (1)
  [R7] SKILL.md is 312 lines — consider moving content to references/

══════════════════════════════════════════════════════════════════════
BLOCKER: 0  MAJOR: 2  MINOR: 1
```

### report — 디렉토리 전체 배치 검사

```bash
# 빠른 전체 감사 (규칙 검사만)
/skill-quality report ./plugins

# 모델 검사 포함 깊이 있는 감사
/skill-quality report ./plugins --depth=deep
```

### rubric — 전체 루브릭 보기

```
/skill-quality rubric
```

38개 항목의 기준, 심각도, 검사 방식을 표시합니다.

## 등급 체계

| 등급 | 조건 | 의미 |
|------|------|------|
| **S** | BLOCKER 0, MAJOR 0 | 배포 가능 |
| **A** | BLOCKER 0, MAJOR 1–2 | 소폭 수정 후 배포 가능 |
| **B** | BLOCKER 0, MAJOR 3–5 | 배포 전 작업 필요 |
| **C** | BLOCKER 0, MAJOR 6–9 | 주요 문제 있음 |
| **D** | BLOCKER 0, MAJOR 10+ | 대규모 수정 필요 |
| **F** | BLOCKER 1개 이상 | 배포 불가 |

## 루브릭 개요

7개 섹션 38개 항목:

| 섹션 | 항목 | BLOCKER | 중점 |
|------|------|---------|------|
| ST — 구조 | 8 | 3 | 유효한 frontmatter, name 형식, 크기 |
| F — 프론트매터 의미론 | 5 | 1 | 필드 일관성, effort 값 |
| T — 트리거 | 6 | 0 | WHAT/WHEN 명확성, 화법, 구체성 |
| C — 콘텐츠 | 6 | 0 | 조직 고유 지식, 예시 |
| R — 리소스 | 8 | 0 | 경로 위생, references 구조 |
| SF — 안전성 | 2 | 2 | 시크릿 없음, destructive 명령 없음 |
| V — 타당성 | 2 | 0 | 목적, 비중복성 |

전체 항목과 기준은 `/skill-quality rubric`을 실행하세요.

## 깊이 모드

| 모드 | 속도 | 모델 | 사용 시점 |
|------|------|------|----------|
| `--rules-only` / `--depth=shallow` | 빠름 | haiku | 커밋 전 빠른 검사 |
| 기본값 | 중간 | sonnet | 배포 전 표준 검사 |
| `--depth=deep` | 철저함 | opus | 최종 품질 게이트 |

## 아키텍처

- **check**: 메인 세션이 rule_checks(haiku) → model_checks(sonnet/opus) 서브에이전트를 순서대로 생성. 메인 세션은 `>>> RESULT <<<` 요약 줄만 읽음 — context 최소화.
- **report**: 메인 세션이 스킬당 자체 완결형 서브에이전트를 병렬로 생성(최대 4개 동시). 추가 중첩 없음.

## Fixtures

`fixtures/` 디렉토리에 각 등급별 예시 스킬이 포함되어 있습니다:

- `fixtures/example-s-grade/` — S등급 (배포 준비 완료)
- `fixtures/example-b-grade/` — B등급 (작업 필요)
- `fixtures/example-f-grade/` — F등급 (BLOCKER 포함)

## 라이선스

MIT
