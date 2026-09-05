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

이 절은 `SKILL.md`에서 옮겨왔습니다 — 런타임에는 로드되지 않는 참고 자료입니다.

### Guild란
Guild는 대상 레포에 **하니스**를 설치하고, 코드베이스를 개발하는 역할 에이전트 조직 — **Guild** — 을 레포마다 길러냅니다. 코드베이스(**결과물**)와 Guild(**개발자**)는 함께 진화합니다. 하니스는 **권고** 층(표준·지식·에이전트 로스터)과 **결정적 강제층**을 결합합니다. `init`은 커밋 게이트를 설치하는데, 정본은 `.git/hooks/pre-commit`이고 여기에 `PreToolUse` 조기 경고 패스가 더해집니다 — 시크릿과 검증 약화에 대해서는 첫날부터 confirmed = 차단입니다(그 밖의 스택별 규칙은 사람이 확인하기 전까지 `status: draft` = WARN 전용으로 시작합니다 — INV6 draft→confirm→enforce). 여섯 개 불변조건은 한 곳에 정의돼 있습니다: `<<SKILL_DIR>>/commands/atoms/_invariants.md` — 이 파일은 게이트의 정직한 한계도 함께 밝힙니다(`--no-verify`가 우회하며, `.git/hooks/`는 클론에 남지 않습니다). `evolve` 성장 루프는 트레이스를 읽고 Guild가 어떻게 자라야 하는지 제안하며, 사람이 항목별로 검토해 적용합니다 — 자동 적용은 없습니다(INV1). 완전 무인 자율 실행(`sprint`)은 구현돼 있고 **준비도 게이트를 걸지 않습니다**(위 주의 참조): `run`의 프리플라이트는 흐름 자체를 무의미하게 만드는 것 — 테스트를 *실행할* 방법이 없는 레포 — 에서만 차단하고 나머지는 경고합니다. PR의 검토와 머지는 여전히 전부 사람의 몫입니다(INV1).

### Guild(레포별 에이전트 조직)
- **리더**는 따로 스폰되는 서브에이전트가 아닙니다 — 메인 세션이 리더 역할을 **체현**합니다(`.claude/agents/leader.md`에서 로드). 과제에 맞춰 팀을 구성하고, 역할에 위임하고, 조정하고, 완료를 판정합니다.
- 역할들은 스테이지당 한 역할씩 배정되는 파이프라인이 아니라 스테이지를 가로질러 **협업**합니다. tech-lead가 기술 방향을 정하고 스켈레톤을 초안한 뒤 나중에 정합성을 확인하고, tester는 구현 전에 인수 기준으로부터 테스트 케이스를 쓰며, developer가 스켈레톤을 채웁니다.

### 스파인(불변)
```
analyze → design → execute → test → qa
                    └ 작업 유형에 따른 execute 변형: implement(기능) | debug(버그) | refactor(리팩터)
```
- `test` = 자동 정확성 검증(tester, verify 게이트). `qa` = 총체적 품질(qa 역할, 탐색적·E2E·사용자 흐름, 위험 기반). `guild:done`을 붙이는 것은 `qa`입니다.
- **execute** 스테이지는 PR을 열기 전에 항상 developer의 diff에 대해 페르소나 없는 **외부 감사자**를 돌립니다(`commands/atoms/_execute_spine.md` Step 3.5a). 읽기 전용에 심각도 태그가 붙은 지적이며, `BLOCKER`는 차단하고 되돌려 보내므로 수정분도 `test`/`qa`의 검증을 다시 받습니다. `/gld review`는 같은 감사자를 `dev` *바깥*에서 한 번 더 돌립니다 — 의도적인 중복이며, 스파인 안의 감사자가 실제로 작동하는지를 재는 독립 척도입니다.
- 조건부 참여자와, 리더가 위험도에 맞춰 진행 전에 끼워 넣는 **게이트 리뷰**: designer(UI → 디자인 + UI/UX 리뷰 게이트), security(→ 보안 리뷰 게이트), infra(CI/CD·배포·env·IaC → execute 리뷰 게이트, **리뷰 전용 — 자기 diff를 절대 작성하지 않습니다**). *트리거로* 스테이지를 막을 수 있는 것은 이 세 게이트 역할이며, 여기에 항상 켜져 있는 위 외부 감사자의 `BLOCKER`가 같은 방식으로 더해집니다. 나머지 전문가들은 게이트 없이 참여합니다. 전체 로스터와 트리거: `commands/atoms/_handoff.md` Section G.
- 작업 유형은 이슈의 `type:` 라벨에서 오고, `analyze`가 재분류할 수 있습니다. execute 변형은 그에 따라 고릅니다 — `implement`(기능) / `debug`(버그) / `refactor`(리팩터). 위 스파인 도식을 보십시오.
- `/gld dev <issue>`는 스파인 전체를 돌리며 execute 변형을 자동 선택합니다. 개별 스테이지도 따로 호출할 수 있습니다(`/gld analyze`, `design`, `implement`, `test`).

### Guild가 관리하는 레포 레이아웃
```
CLAUDE.md                      # 권고: 레포 지도 + 검증 명령 + 지식 라우팅
.claude/settings.json          # 퍼미션 허용목록 + PreToolUse 커밋 게이트 훅
.claude/agents/                # 역할 에이전트 (= Guild)
.claude/guild/
  config.json                  # Guild 설정 (/gld config 가 관리)
  knowledge/                   # ⑥ 코드베이스 사실: index.md(항상 로드) + facts/(관련된 것만 검색해 로드). init 이 기준선을 심고 evolve 가 키운다
  memory/                      # ④ 일화적 작업 계층 (gitignore → 클론마다 로컬, 저신뢰): ground-truth.jsonl(포착된 신호, 프리플라이트 Item 8 이 런타임에 읽음) + consolidated.jsonl(evolve 가 ③/⑥ 으로 키운 항목의 보관소) + gate-firings.jsonl(evolve 규칙 스코어카드에 들어가는 게이트 발화 로그) + review-nudge-state.json(review 의 evolve 유도 쿨다운. 마지막 유도 시점의 저장소 전역 {count, runs} 하나만 둔다 — 충분 상태가 매 review 마다 유도하지 않도록 일부러 PR 별 키를 쓰지 않는다. 이슈 하나에 PR 하나가 통상 흐름이라 PR 별 키로는 거의 모든 review 가 "처음"이 되어 결국 유도했다. 대신 가까운 시점에 검토된 두 PR 사이의 드문 경합을 받아들인다. 스스로 복구된다)
  gates/                       # 강제층: scripts/gate_precommit.py — 커밋 게이트. 세 경로로 실행된다(.git/hooks/pre-commit = 정본 · PreToolUse(Bash) = 조기 경고 · PreToolUse(Edit|Write) --guard-config = 게이트 자신의 오프 스위치·규칙 편집 전에 확인을 요구). + rules/secrets.md, rules/verification.md(게이트가 무엇을 강제하는지에 대한 사람이 읽는 선언 — 검사 자체는 하드코딩이다. 보편적이고 환각되지 않아야 하므로) + rules/boundaries.md(유일한 데이터 주도 규칙 파일: `- forbid:` 줄들. 프런트매터 status: draft → 사람이 확인하기 전까지 WARN 전용 — INV6) + dismissed.md(수용된 위험 등록부) + findings.json(미해결 위반)
  overlay/                     # 흐름 정책 오버라이드 면 (기본은 비어 있음. /gld contribute 가 여기의 diff 를 업스트림한다)
  evolution-log.md             # 진화 원장 — evolve 가 나중에 사용
docs/standards/                # charter, architecture, conventions, quality-bar, verification (init 이 초안. status: draft|confirmed)
docs/adr/ , docs/specs/
```

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
