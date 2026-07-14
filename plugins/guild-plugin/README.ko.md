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
/gld init            # 레포 분석·온보딩 → 하네스 + 창립 Guild 에이전트 + standards + ⑥ 베이스라인 (일회성)
/gld dev 123         # GitHub 이슈 #123 전체 개발 (feature/bug/refactor 자동 선택)
/gld status 123      # 진행 확인   ·   /gld resume 123 이어하기
/gld audit           # 하네스+팀+코드베이스 read-only 건강검진
/gld evolve --dry-run  # Guild 성장 제안 (변경 없음)
```

## 커맨드

**설정** — `init [lang]`(일회성 온보딩) · `config`(다이얼·오프스위치) · `update [--check]`(중앙 개선 채택, 로컬 진화 보존)

**개발** (척추: analyze → design → execute → test → qa) — `dev <issue>`(전체 흐름, execute 변종 자동 선택) · `analyze` · `design` · `implement`(기능) · `debug`(버그: 재현→근본원인→수정) · `refactor`(동작 보존) · `test` · `qa` · `review <issue>`(가이드 페어리뷰 + 적대적 프리스캔) · `resume` · `status` · `batch [issues]`(무인, rate-limit 자동재개)

**진단·성장** — `audit`(read-only, evolve/refactor로 라우팅) · `evolve [--dry-run|--apply]`(스캔 → 적대적 패널 → 항목별 승인 → 백업/롤백/provenance/ledger로 적용) · `contribute`(흐름 개선 업스트림)

**온디맨드·관찰** — `rollback <target>`(비파괴 되돌림) · `ask <question>`(standards+⑥ 기반 인용 Q&A) · `monitoring [--html]`(상태 스냅샷)

**자율** — `sprint [issues]`(Inner+Outer, **준비도 게이트** — 자율은 측정으로 벌어서 얻음)

## 안전 (불변식)

Guild는 자기수정 시스템이므로 안전은 권고가 아니라 결정적입니다:

- **INV1 — 적용은 항상 사람 승인.** 트리거는 자동, 변경은 무인 적용 안 됨(evolve 적용·HR·모든 게이트는 항목별 사람 게이트).
- **INV2 — 검증을 약화시키지 않음.** 테스트/게이트를 삭제·약화하는 변경은 하드 차단(커밋 게이트 + evolve 검증).
- **INV3 — 모든 것은 가역**(git · `/gld rollback` · evolve 검증 실패 시 자동 롤백).
- **INV4 — additive, 로컬 진화를 덮지 않음**(에이전트·지식·standards·overlay).
- **INV5 — sanitize 없이 기기 밖으로 안 나감**(`contribute`는 sanitize + dedup + 사람 리뷰 후 전송).
- **오프스위치** — `/gld config`로 자동화·게이트 차단 일시 정지.

**결정적 커밋 게이트**(`PreToolUse` 훅)가 시크릿 커밋·검증 약화를 차단하며, permission mode로 우회 불가.

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
