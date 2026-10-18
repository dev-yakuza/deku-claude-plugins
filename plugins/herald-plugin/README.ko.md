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
`refresh` · `translate` — **SNS** `social`(`--setup` `--add` `--refresh` `--edit` `--persona` `--remove` `--list`, 초안: `social <sns> <slug>`, `social <sns> --daily`, `--final`) — **상태** `status`(`--requeue` `--drop` `--withdraw` `--withdraw-lang` `--unwithdraw` `--move`
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

`0.14.0` — 전 흐름 구현(구현 적대적 리뷰 10라운드 + 이후 변경별 리뷰 반영). 0.3.0부터 성장 신호를 코드가 자동 기록, 0.4.0에서 외부 감사 라운드 상한, 0.5.0에서 `write` 기본을 무질문으로(`--attended`로 확인 모드)·설정 언어로 대화, 0.6.0에서 `/hrd next`(필요하면 plan → write → ship 1편)와 근거 없는 문장이 적을 때 보류 대신 삭제로 정리하는 단계 추가, 0.7.0에서 읽기 쉬움을 기준에 추가(사람이 쓴 듯한 쉬운 문장 규칙·경험 지어내기 금지, 편집자의 독자 읽기, 게이트의 가독성 힌트, 팩트체커가 "이 글의 예시"로 본 문장은 목록으로 남기고 동의 없이는 자동 발행하지 않음), 0.7.1에서 `/hrd evolve`의 항목별 승인에 검토 패널의 권장안(적용/거절과 이유) 표시, 0.8.0에서 팩트체커가 조사 자료 자체의 오류를 찾으면 writer가 아니라 researcher에게 먼저 되돌리고, 루프백 상한을 다 써도 사실 오류에는 1회를 더 남겨 문장 다듬기 때문에 사실 오류를 못 고치는 일이 없게 함, 0.9.0에서 다국어 — 원문 1편을 쓰고 config `translations`의 언어로 번역(critique 뒤 `translation` 단계, 언어마다 translator, 같은 클레임에 대응시켜 코드가 누락·추가를 확인, 팩트체커가 원문 대응까지 검증), 원문과 번역을 한 묶음으로 검증·원장·발행하고 무결성은 원인(원문·번역·이미지 변경, 번역 추가·삭제)별로 처리, 이미 발행한 글은 `/hrd translate`로 나중에 번역(`--adopt`로 사람 번역 편입, `--missing`), 언어 하나 내리기 `status --withdraw-lang`, 번역이 든 PR은 기본적으로 자동 발행 제외(`translations.auto_publish`로 허용) — `translations`가 없는 레포는 0.8.0과 같게 동작, 0.10.0에서 최신화 판단 — `/hrd refresh`가 글감을 만들기 전에 strategist가 같은 URL 최신화·새 글·불필요 중 하나를 근거와 함께 권하고 사람이 결정(`refresh-policy.md` 기준, 뒤집은 결정은 evolve 신호), 새 글로 정하면 같은 세션에서 write로 이어 가고 옛 글에는 링크 안내, plan이 겹쳐 버리는 글감을 refresh 후보로 제안, refresh 동작이 어느 입구(next·batch·resume)에서도 적용되도록 단계에 이동, 새 글은 이미 쓰이는 slug를 쓸 수 없음 — 기존 레포는 `/hrd update` 필요, 이후 진행 중인 글의 `/hrd resume`은 base 병합을 물음(0.4.0 이전부터 진행 중이던 글은 감사 라운드를 1부터 다시 셈), 0.11.0에서 SNS 초안 — `/hrd social --setup`으로 계정의 가상 페르소나 하나(글에 드러내지 않는 배경, 말투, 서비스 용어, 홍보:일상 비율)와 조사한 공감 소재를 정하고, `--add <sns>`가 채널을 조사해 가이드(형식·길이·해시태그·링크·광고와 운영 주체 표시 규정)를 만들며, `/hrd social <sns> <slug>`·`--daily`가 초안을 쓰면 코드가 검사한 뒤 사람이 하나를 고름(홍보의 사실은 검증된 글이나 `promotion.md`의 그대로 인용만, 링크는 그 글의 URL만, 채널의 표시 문구, 일상 게시물에 통계 없음, 서비스 효과를 개인 경험처럼 말하지 않음), 가이드의 바닥선 완화는 사람의 명시적 승인 필요, Herald는 게시하지 않음, 0.12.0에서 `--refresh <sns>`(재조사를 코드가 병합 — 식별 필드·하우스 규칙·확정 규칙 유지, 표시 약화는 명시적 승인 시만), `--final`(실제 게시한 문구 기록), SNS 초안의 성장 신호(수정 요청·전부 버림·검사 실패·바뀐 최종본, SNS 일자 단위)를 evolve에 연결, 가이드·페르소나의 모든 커밋에 바닥선 검사, 0.13.0에서 세션 컨텍스트에 들어가는 양을 줄임 — HRD 출력 압축, integrity는 손볼 행만, `gsc.py show --slug`, 사용자 레포에 없는 설계 문서 포인터 제거 — 그리고 비용을 잴 수 있게: `measure.py`가 `CLAUDE_CONFIG_DIR`를 따르고(설정 시 예산 측정이 전사를 못 찾던 문제), 중첩 서브에이전트를 세며, 스폰 `description`(`Herald: <역할> — <작업>`, 서브에이전트에는 보이지 않음)으로 역할을 나누고, `--detail`이 메인 세션 컨텍스트를 파일·명령·에이전트별로 귀속, 0.13.1에서 `--detail`이 변수·함수·`eval`로 HRD를 부르거나 경로 변수로 프롬프트 파일을 읽은 셸 명령을 셸 단어가 아니라 그 HRD 명령·파일로 귀속, 0.14.0에서 `/hrd batch`가 Claude 사용 한도를 기다려 넘긴다 — 하위 세션의 스트림에서 한도를 판정(종료 코드와 무관: 마지막 한도 이벤트, 깨진 이벤트 줄, 오류·결과 문구, 해제 시각이 있으면 그 시각), 자기 전에 작업을 글감 브랜치에 보존하고 보류로 기록, 해제 시각까지 대기(1회 5시간·실행당 12시간, 그동안 잠금 거부 문구에 대기 중인 pid 안내), `/hrd resume`으로 이어서 PR이 생기면 보류 해제; 더 긴 한도는 깨끗이 멈추고, 서브에이전트의 사용 한도도 같게 처리, ship child는 한도 뒤 재실행하지 않음, 결정적 계층은 테스트로 검증(`bash plugins/herald-plugin/tests/run_tests.sh`).
`evolve`의 유용성과 지표 기반 제안은 실제 사용이 쌓여야 판정할 수 있습니다.
