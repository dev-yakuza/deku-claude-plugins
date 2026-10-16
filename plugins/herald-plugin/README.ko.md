# Herald Plugin

Claude Code를 위한 **레포 맞춤 편집 조직**. Herald는 레포에 글 작성 하네스를 설치하고, 그 레포에
특화된 역할 에이전트 팀이 글감을 기획하고 `brief → research → draft → critique → verify → publish`
흐름으로 전문적인 블로그 글을 써서 PR 리뷰를 거쳐 발행하며, 실제 사용 흔적에서 가이드를 성장시킵니다.

> 형제 플러그인 [Guild](../guild-plugin)(소프트웨어 개발)와 같은 구조 — 하네스, 역할 골격, 산출하는
> 안쪽 루프와 성장하는 바깥 루프 — 를 글 작성에 적용했습니다.

[English](./README.md) · [日本語](./README.ja.md)

## 개념

- **목적** — 서비스·앱 홍보. 최종 지표는 CTA 클릭·유입이고, 검색 노출은 수단입니다.
- **정확성은 바닥선** — Herald의 발행 경로에서는 `verify`를 통과하지 않은 글을 발행하지 않습니다
  (사람이 고친 글 포함). 바닥선 위에서는 검색 노출 > 독자 가치.
- **골격 역할** — 편집장(메인 세션), 콘텐츠 기획자, 리서처, 작가, 사실 확인 담당, 편집자.
  **조건부** — 분야 전문가·감수자, 검색·발견 담당(SEO·AEO·GEO), 일러스트, 번역, 배포·SNS.
- **외부 감사자** — 조직 밖의 페르소나 없는 리뷰어가 편집자 PASS 뒤(글당 최대 3라운드, 2라운드부터는
  BLOCKER·미해결 지적·회귀만 막고 나머지는 PR로 넘김), 그리고 흐름 밖
  (`/hrd review`)에서 다시 검토합니다.
- **발행 = `/hrd ship`** — PR별 승인, 사람 수정의 재검증, 머지, 배포, URL 확인, 기록. 글을 쓰는
  것만으로는 아무것도 발행되지 않습니다.

## 설치

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install deku-claude-plugins@herald-plugin
```

필요 환경: `git` 2.38 이상, 인증된 `gh`, `python3` 3.9 이상. batch는 `claude` CLI.
Search Console(선택): `pip install google-auth requests`.

## 빠른 시작

```bash
/hrd init            # 레포 분석 + 인터뷰 → 하네스 (커밋 전에 검토)
/hrd plan            # 글감 클러스터를 큐에 추가
/hrd write t0001     # 글 1편 → PR, PR까지 질문 없이
/hrd write t0001 --attended  # 같은 흐름, 단계마다 묻고 PR 전에 승인
/hrd ship            # PR 승인 → 재검증 → 머지 → 배포 → URL 확인 → 기록
/hrd next            # 글 1편을 발행까지 한 번에 (큐가 비면 plan부터)
/hrd batch --n 5     # 무인 작성. autonomy.publish=auto면 발행까지
/hrd status          # 글감 · 보류 · 유지보수 플래그
```

## 커맨드

**설정** `init` · `config` · `update` — **작성** `plan` · `write` · `brief` · `research` ·
`draft` · `critique` · `verify` · `publish` · `resume` · `batch` — **발행** `next` · `ship` · `review` ·
`refresh` · `translate` — **상태** `status`(`--requeue` `--drop` `--withdraw` `--withdraw-lang` `--unwithdraw` `--move`
`--release-slug` `--mark-published` `--unlock`) — **성장·점검** `evolve` · `rollback` · `audit` ·
`monitoring` · `ask` · `contribute`(미지원). 자세한 내용은 `/hrd help`.

## 안전

- **INV1** 변경 적용은 항상 사람 승인. 무인 실행은 approve 모드에서 머지하지 않고, 감사자 BLOCKER를
  기각하지 않습니다. **INV2** 검증을 약화시키지 않음(기준·게이트·모범 글·바닥선). **INV3** 모든 것은
  가역(git, `/hrd rollback`). **INV4** additive, 로컬 진화를 덮지 않음. **INV5** sanitize 없이 기기
  밖으로 나가지 않음. **INV6** 추출한 규칙은 draft로 시작.
- **PreToolUse 가드**(`.claude/herald/scripts/guard.py`)가 기준 파일·비평/검증 페르소나·보호 설정
  키·검증 원장 수정, 머지, 배포, 범위 밖 커밋에 대해 사람에게 묻거나(대화형) 막습니다(무인).
  트립와이어이지 경계가 아니며, `/hrd audit`이 사후에 점검합니다.
- **검증 원장**(로컬)과 **배포 전 무결성 점검**이 배포 전에 base의 모든 Herald 글을 검증된 내용과
  대조합니다.

## 상태

`0.9.0` — 전 흐름 구현(구현 적대적 리뷰 10라운드 + 이후 변경별 리뷰 반영). 0.3.0부터 성장 신호를 코드가 자동 기록, 0.4.0에서 외부 감사 라운드 상한, 0.5.0에서 `write` 기본을 무질문으로(`--attended`로 확인 모드)·설정 언어로 대화, 0.6.0에서 `/hrd next`(필요하면 plan → write → ship 1편)와 근거 없는 문장이 적을 때 보류 대신 삭제로 정리하는 단계 추가, 0.7.0에서 읽기 쉬움을 기준에 추가(사람이 쓴 듯한 쉬운 문장 규칙·경험 지어내기 금지, 편집자의 독자 읽기, 게이트의 가독성 힌트, 팩트체커가 "이 글의 예시"로 본 문장은 목록으로 남기고 동의 없이는 자동 발행하지 않음), 0.7.1에서 `/hrd evolve`의 항목별 승인에 검토 패널의 권장안(적용/거절과 이유) 표시, 0.8.0에서 팩트체커가 조사 자료 자체의 오류를 찾으면 writer가 아니라 researcher에게 먼저 되돌리고, 루프백 상한을 다 써도 사실 오류에는 1회를 더 남겨 문장 다듬기 때문에 사실 오류를 못 고치는 일이 없게 함, 0.9.0에서 다국어 — 원문 1편을 쓰고 config `translations`의 언어로 번역(critique 뒤 `translation` 단계, 언어마다 translator, 같은 클레임에 대응시켜 코드가 누락·추가를 확인, 팩트체커가 원문 대응까지 검증), 원문과 번역을 한 묶음으로 검증·원장·발행하고 무결성은 원인(원문·번역·이미지 변경, 번역 추가·삭제)별로 처리, 이미 발행한 글은 `/hrd translate`로 나중에 번역(`--adopt`로 사람 번역 편입, `--missing`), 언어 하나 내리기 `status --withdraw-lang`, 번역이 든 PR은 기본적으로 자동 발행 제외(`translations.auto_publish`로 허용) — `translations`가 없는 레포는 0.8.0과 같게 동작 — 기존 레포는 `/hrd update` 필요, 이후 진행 중인 글의 `/hrd resume`은 base 병합을 물음(0.4.0 이전부터 진행 중이던 글은 감사 라운드를 1부터 다시 셈), 결정적 계층은 테스트로 검증(`bash plugins/herald-plugin/tests/run_tests.sh`).
`evolve`의 유용성과 지표 기반 제안은 실제 사용이 쌓여야 판정할 수 있습니다.
