# Guild Plugin

Claude Code를 위한 **자기진화 에이전트 조직**. Guild는 레포에 작동 환경(*하네스*)을 구축하고, 레포 전용 특화 역할 에이전트 팀이 스펙 기반 흐름으로 GitHub 이슈를 개발하며, 실제 사용 흔적에서 **코드베이스와 에이전트 팀을 함께 성장(공진화)**시킵니다.

> `sdd-plugin`·`skill-quality-plugin`의 후계자. — *"레벨업하는 에이전트 길드."*

[English](./README.md) · [日本語](./README.ja.md)

## 개념

- **하네스** — Guild가 설치하는 작동 환경: `CLAUDE.md`, settings, 역할 에이전트 로스터, ⑥ 지식 베이스, standards 초안, 결정적 커밋 게이트.
- **조직** — 레포 전용 **16 역할 에이전트**(척추: leader · tech-lead · developer · tester · qa + 조건부 스페셜리스트 — designer, security, dba, i18n …)가 척추를 넘나들며 협업하고 *당신의* 프로젝트에 특화됩니다.
- **두 루프** — **Inner 루프**는 코드를 개발(`analyze → design → execute → test → qa`), **Outer 루프**(`evolve`)는 실제 흔적을 읽어 에이전트·지식·게이트를 성장시킵니다.
- **공진화** — 코드베이스(결과물)와 Guild(개발자)가 사용에서 함께 개선됩니다. `evolve`가 흔적을 리뷰·사람 승인된 개선으로 증류합니다.

## 설치

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install deku-claude-plugins@guild-plugin
```

## 빠른 시작

```bash
/gld init            # 레포 분석·온보딩 → 하네스 + 창립 Guild 에이전트 + standards + ⑥ 베이스라인 + 준비도 감사 → guild:harness 이슈 (일회성)
/gld dev 123         # GitHub 이슈 #123 전체 개발 (feature/bug/refactor 자동 선택)
/gld status 123      # 진행 확인   ·   /gld resume 123 이어하기
/gld audit           # 하네스+팀+코드베이스 read-only 건강검진
/gld evolve --dry-run  # Guild 성장 제안 (변경 없음)
```

## 커맨드

**설정** — `init [lang]`(일회성 온보딩, 하네스 구축 + 준비도 감사) · `onboard [area]`(사람 유지보수자를 위한 가이드 코드베이스 투어) · `config`(다이얼·오프스위치) · `update [--check]`(중앙 개선 채택, 로컬 진화 보존)

**개발** (척추: analyze → design → execute → test → qa — `execute` 는 PR 이 열리기 전 개발자 diff 에 대해 읽기 전용 **외부 감사자**를 상시 실행합니다. `BLOCKER` 는 루프백되어 수정이 `test`/`qa` 로 재검증되고, `review` 는 같은 감사자를 흐름 **바깥**에서 다시 돌려 안쪽 감사자가 실제로 작동하는지를 재는 독립 계측기 역할을 합니다) — `plan <doc|epic-issue> [--create]`(에픽/설계 문서를 의존성 순서의 이슈 백로그로 분해) · `dev <issue>`(전체 흐름, execute 변종 자동 선택) · `analyze` · `design` · `implement`(기능) · `debug`(버그: 재현→근본원인→수정) · `refactor`(동작 보존) · `test` · `qa` · `review <issue|PR>`(가이드 페어리뷰 + 적대적 프리스캔, 이슈 번호뿐 아니라 PR 번호도 직접 지원) · `resume` · `status` · `batch [issues]`(무인, 리셋이 4시간 이내인 rate limit 은 기다려 재개)

**진단·성장** — `audit`(read-only, evolve/refactor로 라우팅) · `evolve [--dry-run|--apply]`(스캔 → 적대적 패널 → 항목별 승인 → 백업/롤백/provenance/ledger로 적용) · `contribute`(흐름 개선 업스트림)

**온디맨드·관찰** — `rollback <target>`(비파괴 되돌림) · `ask <question>`(standards+⑥ 기반 인용 Q&A) · `monitoring [--html]`(상태 스냅샷)

**반복 구간** — `sprint plan`(이번 스프린트에 담을 이슈 선별 + 의존성 순서 + 추적 이슈 생성) · `sprint run`(의존성 순서대로 무인 개발 → **PR 스택**, 이슈별 git 워크트리 격리, rate limit 은 리셋이 4시간 이내면 기다려 재개하고, 더 멀면 그 멤버만 차단해 재실행이 이어받는다 — 사장님은 그 사이에 리뷰·머지) · `sprint daily`(무엇을 어떤 순서로 머지할지 · 사람 대기 · 실패) · `sprint board`(스프린트를 GitHub Projects 칸반에 비춘다 — `Issues → Backlog → Ready → In progress → Blocked → In review → Done` — 처음 한 번만 설정하면 이후 `plan`·`run` 이 자동으로 갱신) · `sprint retro`(지표 → 용량 보정 → evolve → 스프린트 종료)

## 안전 (불변식)

Guild는 자기수정 시스템이므로 안전은 권고가 아니라 결정적입니다:

- **INV1 — 적용은 항상 사람 승인.** 트리거는 자동, 변경은 무인 적용 안 됨(evolve 적용·HR·모든 게이트는 항목별 사람 게이트).
- **INV2 — 검증을 약화시키지 않음.** 테스트/게이트를 삭제·약화하는 변경은 하드 차단(커밋 게이트 + evolve 검증).
- **INV3 — 모든 것은 가역**(git · `/gld rollback` · evolve 검증 실패 시 자동 롤백).
- **INV4 — additive, 로컬 진화를 덮지 않음**(에이전트·지식·standards·overlay).
- **INV5 — sanitize 없이 기기 밖으로 안 나감**(`contribute`는 sanitize + dedup + 사람 리뷰 후 전송).
- **INV6 — draft→confirm→enforce.** 자동 생성된 게이트 규칙(예: 구조/경계 규칙)은 `status: draft`(WARN만)로 시작하며 사람이 확인(`status: confirmed`)해야 비로소 차단으로 승격됩니다. 시크릿·검증 게이트 둘은 hallucination 여지가 없는 보편 규칙이라 `init`이 처음부터 confirmed 상태로 설치합니다.
- **오프스위치** — `/gld config`로 자동화·게이트 차단 일시 정지.

**결정적 커밋 게이트**가 시크릿 커밋·검증 약화를 차단합니다. `.git/hooks/pre-commit`(권위 있는 층 —
git이 인덱스가 확정된 뒤 실행하므로, 한 줄짜리 복합 `생성+커밋` 명령도 잡힙니다)과, 에이전트가 턴을
낭비하기 전에 구체적인 이유를 주는 `PreToolUse` 조기 경고 층으로 이중 배선됩니다.

**한계도 정직하게 밝힙니다** — 실제보다 크게 말하는 게이트는 진짜 빈틈을 가리기 때문입니다.
`git commit --no-verify`는 모든 git 훅과 마찬가지로 이 게이트도 건너뜁니다. `.git/hooks/`는 추적되지
않으므로 새 클론에서는 `/gld update`로 재설치해야 합니다. 저장소가 `core.hooksPath`를 설정했다면 아예
동작하지 않습니다. 이미 기록된 히스토리는 검사하지 않습니다. 게이트 자신의 오프 스위치나 규칙 파일을
수정하려 하면 차단이 아니라 사람 확인을 요구합니다 — 게이트를 끄는 것은 정당한 행위이되, 부수 효과로
일어나서는 안 되기 때문입니다. 이 게이트는 실수의 비용을 높이는 장치이지, 작정한 우회를 막는 경계가
아닙니다.

## 레퍼런스

이 절은 `SKILL.md`에서 옮겨왔습니다. 런타임에 로드되지 않는 참고 자료이며, 원문(영문)은 `README.md`의 **Reference** 절에 있습니다.

- **Guild란** — 대상 레포에 **하니스**를 설치하고, 코드베이스를 개발하는 역할 에이전트 조직(**Guild**)을 기른다. 결과물과 개발자가 함께 진화한다.
- **Guild(레포별 에이전트 조직)** — 역할 에이전트는 `.claude/agents/`에 살고 그 디렉터리가 곧 로스터다. 스파인 역할(leader·tech-lead·developer·tester·qa)은 항상 돌고, 나머지는 리더가 작업 유형·위험도에 따라 소집한다.
- **스파인(불변)** — `analyze → design → execute → test → qa`. execute는 작업 유형에 따라 `implement`(기능) / `debug`(버그) / `refactor`로 갈린다.
- **Guild가 관리하는 레포 레이아웃** — `CLAUDE.md` · `.claude/settings.json` · `.claude/agents/` · `.claude/guild/`(config·knowledge·memory·gates·overlay) · `docs/standards/` · `docs/adr/` · `docs/specs/`.

> ⚠ 상세는 영문 **Reference** 절을 보십시오 — 이 요약은 각 항목의 존재와 위치만 전달합니다.

## 상태 저장 위치

| 무엇 | 어디 |
|---|---|
| 개발 상태(스테이지·산출물) | GitHub 이슈/PR + `guild:*` 라벨 |
| 역할 에이전트(습관) | `.claude/agents/*.md` |
| 코드베이스 사실(⑥, 관련분만 검색) | `.claude/guild/knowledge/` |
| 날것 경험 기억 | `.claude/guild/memory/`(gitignore) |
| 진화 원장 + 게이트 + 설정 | `.claude/guild/` |
| 큐레이션 표준(charter·architecture…) | `docs/standards/` |

## 라이선스

MIT
