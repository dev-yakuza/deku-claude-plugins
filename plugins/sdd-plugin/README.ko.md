[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md)

# SDD Plugin (Spec-Driven Development)

Claude Code를 활용한 AI 협업 개발 프로세스입니다. GitHub Issue를 통해 구조화된 프로세스로 전체 개발 라이프사이클을 관리합니다.

## 설치

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install deku-claude-plugins@sdd-plugin
```

## 빠른 시작

```bash
# 1. 저장소에 SDD 설정 (언어 선택)
/sdd init           # 영어 (기본값)
/sdd init ko        # 한국어
/sdd init ja        # 일본어

# 2. SDD 템플릿으로 GitHub Issue 생성

# 3. 개발 프로세스 시작
/sdd analyze 123     # 요구사항 분석 (What/Why)
/sdd design 123      # 설계 (How)
/sdd implement 123   # TDD 구현
/sdd test 123        # E2E 및 QA 테스트
```

## 명령어

| 명령어 | 설명 |
|--------|------|
| `/sdd init [lang]` | Issue 템플릿과 라벨 설정. 언어: `en` (기본값), `ko`/`korean`/`한국어`, `ja`/`japanese`/`日本語` |
| `/sdd analyze <issue>` | 1단계: 요구사항 분석 (What/Why) |
| `/sdd design <issue>` | 2단계: 설계 (How) |
| `/sdd implement <issue>` | 3단계: TDD 구현 |
| `/sdd test <issue>` | 4단계: E2E/QA 테스트 |
| `/sdd resume <issue>` | 단계 자동 감지 후 중단된 곳부터 재개 |
| `/sdd rollback <issue> <stage>` | 이전 단계로 롤백 (analyze, design, implement) |
| `/sdd status <issue>` | 현재 진행 상황 확인 |
| `/sdd review <issue>` | 현재 산출물 AI 리뷰 |
| `/sdd config` | SDD 설정 확인 또는 변경 |
| `/sdd help` | 사용법 표시 |

## 프로세스

```
1. 요구사항 (What/Why) → 2. 설계 (How) → 3. 구현 (TDD) → 4. 테스트 (E2E/QA)
```

### 1단계: 요구사항 분석 (What / Why)

**무엇**을 만들고 **왜** 필요한지에 집중합니다. 기술적 구현 방법(How)은 이 단계에서 다루지 않습니다.

**흐름:** ① 입력 → ② AI 분석 → ③ 산출물 → ④ AI 리뷰 → ⑤ 사용자 리뷰 → 다음 단계

### 2단계: 설계 (How)

요구사항을 바탕으로 **어떻게** 구현할지 정의합니다.

**흐름:** ① 입력 → ② AI 설계 → ③ 산출물 → ④ AI 리뷰 → ⑤ 사용자 리뷰 → 다음 단계

### 3단계: 구현 - TDD 사이클

PR 단위로 TDD 사이클을 실행합니다:

```
3-0. PR 킥오프: 테스트 & 구현 계획
3-1. Red: 실패하는 테스트 작성
3-2. Green: 최소한의 구현
3-3. Refactor: 코드 개선
3-4. PR 생성 & 코드 리뷰 (수동 테스트 체크리스트 포함)
→ 다음 PR 반복
```

테스트 범위: 유닛 테스트 / UI 테스트
PR에는 리뷰어가 UI 동작, 사용자 흐름, 엣지 케이스를 검증할 수 있는 수동 테스트 체크리스트가 포함됩니다.

### 4단계: 테스트

- E2E 자동 테스트 (AI가 코드 작성 및 테스트 실행)
- QA 체크리스트 (AI가 작성, 사람이 실행)
- 회귀 테스트

### 멀티 PR 워크플로 (부모/자식 Issue)

설계 단계에서 여러 PR이 식별되면 SDD가 자동으로 자식 Issue를 생성합니다:

```bash
/sdd analyze 100    # 부모 Issue 분석
/sdd design 100     # 설계가 3개 하위 기능으로 분리 → #101, #102, #103 생성

# 각 자식 Issue를 독립적으로 작업
/sdd analyze 101    # 자식이 부모 컨텍스트를 상속
/sdd design 101
/sdd implement 101
/sdd test 101       # 자식 #101 완료 → 부모 상태 업데이트

/sdd resume 100     # 부모 확인: #101 ✓, #102 대기 중, #103 대기 중
/sdd analyze 102    # 다음 자식 작업 계속...

# 모든 자식 완료 후
/sdd test 100       # 부모 레벨 E2E/QA 테스트
```

### 리뷰 건너뛰기 설정

기본적으로 모든 단계에서 사용자 리뷰가 필요합니다. `/sdd config`를 사용하여 특정 단계의 사용자 리뷰를 건너뛸 수 있습니다:

```bash
# skip-review 설정
/sdd config --skip-review=analyze,design,implement

# 현재 설정 확인
/sdd config

# 초기화 (모든 리뷰 활성화)
/sdd config --skip-review=
```

| 값 | 건너뛰는 리뷰 |
|----|---------------|
| `analyze` | 요구사항 분석 후 사용자 리뷰 |
| `design` | 설계 후 사용자 리뷰 |
| `implement` | TDD 하위 단계(3-0 ~ 3-3)의 사용자 리뷰 |
| `pr` | PR 코드 리뷰(3-4)의 사용자 리뷰 |
| `qa` | 수동 QA 실행 (4-2 ~ 4-3) |

설정은 `.github/.sdd-config`에 저장됩니다. AI 리뷰는 이 설정과 관계없이 항상 실행됩니다.

### 언어 설정

`/sdd init` 실행 시 언어가 `.github/.sdd-lang`에 저장됩니다. 이후 모든 명령어는 이 설정을 사용하여 템플릿과 산출물을 생성합니다.

언어를 변경하려면 새 언어로 `/sdd init`을 다시 실행하세요:

```bash
/sdd init ja        # 일본어로 전환
```

## GitHub 연동

모든 산출물은 GitHub에 저장되므로 별도의 파일 관리가 필요 없습니다.

| 데이터 | 저장 위치 |
|--------|-----------|
| 요구사항 (입력) | Issue 본문 |
| 분석 산출물 | Issue 코멘트 |
| 설계 산출물 | Issue 코멘트 |
| 현재 단계 | Issue 라벨 |
| 구현 | Pull Request |
| 테스트 결과 | Issue 코멘트 |

### 라벨

| 라벨 | 단계 |
|------|------|
| `sdd:analyze` | 요구사항 분석 |
| `sdd:design` | 설계 |
| `sdd:implement` | 구현 |
| `sdd:test` | 테스트 |
| `sdd:done` | 완료 |
| `sdd:child` | 자식 Issue (설계 단계에서 생성) |

## 라이선스

MIT
