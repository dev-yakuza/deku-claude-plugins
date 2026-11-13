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
  트립와이어이지 경계가 아니며, `/hrd audit`이 사후에 점검합니다. 가드가 예외로 죽거나 시작조차 못 해도
  머지·배포 앞에서는 묻지만, hook 제한 시간(30초)에 걸려 끊기면 아무것도 정하지 못합니다 — 0.20.0부터
  settings 자체는 `gh pr merge` 앞에서 묻지 않습니다.
- **검증 원장**(로컬)과 **배포 전 무결성 점검**이 배포 전에 base의 모든 Herald 글을 검증된 내용과
  대조합니다.

## 장면 이미지 (0.18.0)

`images.scenes`(`/hrd config images`)가 있으면 이미지 자리를 **장면**으로 둘 수 있습니다 — 실재일
필요가 없는 상황(입국 심사대 앞의 여행자)이고, 실재하는 사람·장소·상표·작품은 그리지 않습니다.
limner가 **Qwen-Image-Edit-2511(4bit) + Lightning 8step**(Apache-2.0, script2video와 모델 저장소 공유,
`lmn setup` 약 54GB)으로 이 기기에서 만듭니다. M2 Max 64GB에서 한 장에 2–3분 정도라, 편집장이 limner의
분리 작업자를 시작하고 짧은 호출로 확인하며 `wait_minutes`를 넘으면 보류(`tooling: limner …`)하고,
`/hrd resume`이 같은 실행을 이어받습니다. 장면에는 **글자가 없고**(Herald가 영어 프롬프트에 "글자 없음"
고정 문장을 붙임), 본문에는 그림 옆에 늘 **AI 생성 표시**가 붙습니다(`images.figure.scene`의
`{label}` — 같은 slug의 모든 글감에서 draft·verify·발행 때 레포 검사기와 별도로 확인, trim으로 지워지지
않음). illustrator가 먼저 그림을 검토하고, draft를 통과하려면 **모든 장면을 사람이 확인**해야 합니다.
판정은 state 필드가 아니라 생성 원장과 확인 원장이 하므로 확인 안 된 그림은 원격에 가지 않습니다.
limner·모델·RAM이 없으면 장면만 꺼지고, 번역 레포에서는 꺼져 있습니다.

## SNS 형식 (0.19.0)

`/hrd social <sns> <slug> --format image|cards|comic`(`--daily`도)으로 게시글에 그림을 붙입니다: **이미지
1장**, **카드 뉴스**(표지·요점 카드 1–8장·끝 카드의 캐러셀), **만화**(2×2 또는 3×2 한 장, run당 초안 1개).
모든 그림은 Herald 상수인 레이아웃으로 limner가 합성합니다 — 글자를 모델이 그리지 않고, 만화 칸은 글자
없이 생성한 뒤 말풍선·캡션을 합성합니다. 재료는 그 글의 도해·limner OG·사람이 확인한 장면(커밋된 그대로)과
이번 초안을 위해 생성한 그림뿐이고, 인용·외부 이미지와 같은 바이트는 절대 나가지 않습니다. 그림 속 글자는
게시글 본문과 합쳐 검사하고(통계·서비스 경험·인용, 서비스를 언급하면 광고로 판정), 생성 그림이 든 게시물은
늘 채널의 **`ai_disclosure`**(본문 문구 또는 플랫폼의 AI 라벨 설정, 광고 표시와 별개)를 답니다. `check`·
`close`는 그림마다 보호된 limner compose 기록(출력·입력 그림 전부·명세로 다시 만든 레이아웃)과 대조해,
사람이 승인하는 그림이 Herald가 검사한 그 그림이게 합니다. `--final`은 승인 프로필과 AI 표시를 이어받습니다.
`formats`가 없는 가이드는 글만입니다(`/hrd social --refresh <sns>`가 형식을 조사).

## `--ship` 끝까지 (0.20.0)

`/hrd write <id> --ship`(`resume`·`refresh`·`translate`의 `--ship`, `/hrd next`도)은 그 글 한 편을
**사람이 보지 않고** 발행해 달라는 사람의 요청이다. 사람이 외부 이미지·인용·장면·자동 스크린샷을
확인하던 자리는 **새 illustrator spawn이 검토**하고 Herald가 `--agent`로 확인한다 — 사람의 확인과
구별되어 남고(원장의 `by: agent`, PR 본문의 `agent-reviewed (no human look)`, ship 보고,
`published.json`의 `agent_confirmed`) 그 글감·그 자리·그 내용에만 유효하다. 그 뒤 PR은 묻지 않고
머지·배포된다: `HRD lock ship-pass`가 PR head를 다시 확인하고, guard는 검증된 `gh pr merge …
--match-head-commit <sha>`와 설정된 배포 명령 문자열에만 `allow`를 준다. 플래그의 유일한 근거는
체크아웃 잠금의 표시(guard 보호)이므로 사람이 쓴 경우에만 붙인다. 결함은 여전히 PR에서 멈춘다 — 열린·
미룬·에이전트가 기각한 BLOCKER, 바뀐 critique·verify 파일, 아무도 보증하지 않은 PR 안의 파일
(`images-unconfirmed`), 사람만 찍을 수 있는 스크린샷, 검토가 문제를 찾은 캡처, 하루 상한. batch와
`--ship` 없는 실행은 그대로이고, `/hrd update`가 `gh pr merge` 앞에서 묻던 0.19.0 settings 규칙을
지우자고 제안한다(guard가 직접 묻는다).

## 대체 그림과 장식 그림 (0.21.0)

실재 **장소나 일반 물건**의 외부 이미지 자리에 쓸 사진이 없으면(후보 없음, 후보가 모두 실패·거부됨, 또는 사람이
"일반형 AI 그림으로 대신"을 고름) Herald는 그 장소가 **아닌 일반형** 장면을 그립니다 — 기요미즈데라 대신 "단풍 속
산사" — 그림 옆에는 "AI 생성 이미지(실제 장소 아님)" 라벨이 붙습니다. brief가 자리마다 대상을 표시하고
(`external (place|thing|work|person|quotation)`), 작품·캐릭터·상표 제품·로고·실존 인물·글자는 대신 그리지
않으며, 사람의 "없이 감"은 대체로 뒤집히지 않습니다. 모든 판단은 brief 줄(해시)에 묶이고 brief 통과 뒤에는 바뀌지
않으며, 조사 후보는 첫 research 통과 뒤 고정됩니다. 대체 그림은 생성 전 대상 대조, 더 엄격한 검토(일본 세부, 알아볼
수 있는 랜드마크 없음), 사람 확인(또는 `--ship`의 새 검토)을 받고, SNS 재료에 들어가지 않으며, PR 본문과
`published.json`에 남습니다. 장면과 외부 이미지가 둘 다 켜진 곳에서 **기본 켜짐**(`images.scenes.stand_in:
false`로 끔, 인용 카테고리는 `stand_in_per_category`에 적어야 켜짐). 장식 그림은 opt-in(`images.scenes.decorative`,
0–3, 기본 0): 절 사이에만, 첫머리 아님, 글의 장면·외부·전체 한도 안.

## 상태

`0.22.0` — 전 흐름 구현(구현 적대적 리뷰 10라운드 + 이후 변경별 리뷰 반영). 0.3.0부터 성장 신호를 코드가 자동 기록, 0.4.0에서 외부 감사 라운드 상한, 0.5.0에서 `write` 기본을 무질문으로(`--attended`로 확인 모드)·설정 언어로 대화, 0.6.0에서 `/hrd next`(필요하면 plan → write → ship 1편)와 근거 없는 문장이 적을 때 보류 대신 삭제로 정리하는 단계 추가, 0.7.0에서 읽기 쉬움을 기준에 추가(사람이 쓴 듯한 쉬운 문장 규칙·경험 지어내기 금지, 편집자의 독자 읽기, 게이트의 가독성 힌트, 팩트체커가 "이 글의 예시"로 본 문장은 목록으로 남기고 동의 없이는 자동 발행하지 않음), 0.7.1에서 `/hrd evolve`의 항목별 승인에 검토 패널의 권장안(적용/거절과 이유) 표시, 0.8.0에서 팩트체커가 조사 자료 자체의 오류를 찾으면 writer가 아니라 researcher에게 먼저 되돌리고, 루프백 상한을 다 써도 사실 오류에는 1회를 더 남겨 문장 다듬기 때문에 사실 오류를 못 고치는 일이 없게 함, 0.9.0에서 다국어 — 원문 1편을 쓰고 config `translations`의 언어로 번역(critique 뒤 `translation` 단계, 언어마다 translator, 같은 클레임에 대응시켜 코드가 누락·추가를 확인, 팩트체커가 원문 대응까지 검증), 원문과 번역을 한 묶음으로 검증·원장·발행하고 무결성은 원인(원문·번역·이미지 변경, 번역 추가·삭제)별로 처리, 이미 발행한 글은 `/hrd translate`로 나중에 번역(`--adopt`로 사람 번역 편입, `--missing`), 언어 하나 내리기 `status --withdraw-lang`, 번역이 든 PR은 기본적으로 자동 발행 제외(`translations.auto_publish`로 허용) — `translations`가 없는 레포는 0.8.0과 같게 동작, 0.10.0에서 최신화 판단 — `/hrd refresh`가 글감을 만들기 전에 strategist가 같은 URL 최신화·새 글·불필요 중 하나를 근거와 함께 권하고 사람이 결정(`refresh-policy.md` 기준, 뒤집은 결정은 evolve 신호), 새 글로 정하면 같은 세션에서 write로 이어 가고 옛 글에는 링크 안내, plan이 겹쳐 버리는 글감을 refresh 후보로 제안, refresh 동작이 어느 입구(next·batch·resume)에서도 적용되도록 단계에 이동, 새 글은 이미 쓰이는 slug를 쓸 수 없음 — 기존 레포는 `/hrd update` 필요, 이후 진행 중인 글의 `/hrd resume`은 base 병합을 물음(0.4.0 이전부터 진행 중이던 글은 감사 라운드를 1부터 다시 셈), 0.11.0에서 SNS 초안 — `/hrd social --setup`으로 계정의 가상 페르소나 하나(글에 드러내지 않는 배경, 말투, 서비스 용어, 홍보:일상 비율)와 조사한 공감 소재를 정하고, `--add <sns>`가 채널을 조사해 가이드(형식·길이·해시태그·링크·광고와 운영 주체 표시 규정)를 만들며, `/hrd social <sns> <slug>`·`--daily`가 초안을 쓰면 코드가 검사한 뒤 사람이 하나를 고름(홍보의 사실은 검증된 글이나 `promotion.md`의 그대로 인용만, 링크는 그 글의 URL만, 채널의 표시 문구, 일상 게시물에 통계 없음, 서비스 효과를 개인 경험처럼 말하지 않음), 가이드의 바닥선 완화는 사람의 명시적 승인 필요, Herald는 게시하지 않음, 0.12.0에서 `--refresh <sns>`(재조사를 코드가 병합 — 식별 필드·하우스 규칙·확정 규칙 유지, 표시 약화는 명시적 승인 시만), `--final`(실제 게시한 문구 기록), SNS 초안의 성장 신호(수정 요청·전부 버림·검사 실패·바뀐 최종본, SNS 일자 단위)를 evolve에 연결, 가이드·페르소나의 모든 커밋에 바닥선 검사, 0.13.0에서 세션 컨텍스트에 들어가는 양을 줄임 — HRD 출력 압축, integrity는 손볼 행만, `gsc.py show --slug`, 사용자 레포에 없는 설계 문서 포인터 제거 — 그리고 비용을 잴 수 있게: `measure.py`가 `CLAUDE_CONFIG_DIR`를 따르고(설정 시 예산 측정이 전사를 못 찾던 문제), 중첩 서브에이전트를 세며, 스폰 `description`(`Herald: <역할> — <작업>`, 서브에이전트에는 보이지 않음)으로 역할을 나누고, `--detail`이 메인 세션 컨텍스트를 파일·명령·에이전트별로 귀속, 0.13.1에서 `--detail`이 변수·함수·`eval`로 HRD를 부르거나 경로 변수로 프롬프트 파일을 읽은 셸 명령을 셸 단어가 아니라 그 HRD 명령·파일로 귀속, 0.14.0에서 `/hrd batch`가 Claude 사용 한도를 기다려 넘긴다 — 하위 세션의 스트림에서 한도를 판정(종료 코드와 무관: 마지막 한도 이벤트, 깨진 이벤트 줄, 오류·결과 문구, 해제 시각이 있으면 그 시각), 자기 전에 작업을 글감 브랜치에 보존하고 보류로 기록, 해제 시각까지 대기(1회 5시간·실행당 12시간, 그동안 잠금 거부 문구에 대기 중인 pid 안내), `/hrd resume`으로 이어서 PR이 생기면 보류 해제; 더 긴 한도는 깨끗이 멈추고, 서브에이전트의 사용 한도도 같게 처리, ship child는 한도 뒤 재실행하지 않음, 0.15.0에서 사람이 찍는 스크린샷 — 글에 화면이 필요하면 기획자·리서처·작가가 촬영 안내(화면에 가는 단계와 출처, 가릴 정보)를 만들고, 사람이 로컬 inbox에 파일을 넣으면 Herald가 이미지 데이터만 남겨(남길 것만 남기는 방식이라 메타데이터가 나가지 않음) 가져오며, 다 모이기 전에는 draft가 통과하지 않음(기본·batch는 `screenshots` 보류 → `/hrd resume`), 편집자·감사자가 화면을 보고(개인정보는 BLOCKER), 스크린샷 글은 동의 발행 없이 `/hrd ship`에서 따로 확인받고, publish가 브랜치를 커밋 하나로 다시 만들어 비평 전 화면이 이력에 남지 않음, 0.16.0에서 `screenshots.capture`를 설정하면 로그인 없는 공개 페이지는 Herald가 직접 촬영하고(셸 없이 argv 템플릿으로, 문자 집합을 제한한 공개 `https://` URL만, 실패하면 그 화면은 사람 촬영으로 고정) 모든 자동 촬영본은 사람이 확인해야 인정됨(확인 안 된 촬영본은 state 필드가 아니라 보호된 촬영 로그·확인 원장으로 가려내고, publish는 push하는 모든 커밋을 검사), 0.17.0(`/hrd config images`)에서 brief가 이미지 자리마다 종류 하나를 정함 — 스크린샷, illustrator가 그리고 limner가 PNG로 렌더하는 SVG 도해(그려진 글자는 `HRD image render`만 쓰는 커밋된 렌더 기록으로 찾아 문장처럼 검증), 자유 라이선스이거나 권리자 페이지에서 인용하는 외부 이미지(Herald가 SSRF 방어와 함께 직접 받고, 메타데이터는 지우되 색 프로파일은 남기며, 본문에 출처 표기, 사람이 확인해야 하고 동의로 풀리지 않으며, 인용 이미지는 OG·SNS에 쓰지 않음) — 그리고 레포 생성기나 limner `og-title`로 만드는 대표 이미지(만들 수 없으면 보류 없이 `off`), `images` 블록이나 limner가 없으면 0.16.0과 같음, 0.18.0에서 장면 이미지(위 절) — limner가 만들고
illustrator가 검토하고 사람이 확인하며 늘 AI 생성 표시가 붙음 — `images.scenes`가 없는 레포는 0.17.0과
같음, 0.19.0에서 SNS 형식(위 절) — limner가 합성하는 이미지 1장·카드 뉴스·만화, 광고 표시와 별개인 AI 표시 —
`formats`가 없는 채널 가이드는 0.18.0과 같음, 0.20.0에서 `--ship` 끝까지(위 절) — 이미지·스크린샷 확인 대신 에이전트 검토, 검증된 머지와 배포를 묻지 않음 — 이고 `--ship` 없는 실행은 0.19.0과 같음, 0.21.0에서 대체 그림과 장식 그림(위 절) — 0.20.0 brief로 시작한 글감에는 없음, 0.22.0에서 refresh의 감사자가 코드가 인용한 refresh 범위를 받고, refresh가 건드리지 않은 문장의 범위 밖 지적은 다음 refresh로 넘김(refresh 시작 시점의 글과 코드로 대조, BLOCKER는 불가, PR·ship 보고에 표시, `published.json` `refresh_candidates`로 다음 refresh의 brief에), 감사자가 볼 수 없는 research에 근거한 기각은 claim을 명시(`grounds` — 기각으로 계속 세면서 evolve의 보조 축으로도 셈), `/hrd evolve`가 사람의 결정으로 낡은 신호를 퇴역(이유와 함께 evolution log에 기록, `--unretire`로 되돌림), 결정적 계층은 테스트로 검증(`bash plugins/herald-plugin/tests/run_tests.sh`).
`evolve`의 유용성과 지표 기반 제안은 실제 사용이 쌓여야 판정할 수 있습니다.
