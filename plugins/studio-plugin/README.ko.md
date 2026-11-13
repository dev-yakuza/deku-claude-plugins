# Studio 플러그인

Claude Code용 **레포별 영상 제작 조직**입니다. Studio는 레포에 제작 하네스를 설치하고, 그 레포에
특화된 역할 에이전트 팀이 레포에 이미 있는 글(블로그 · 문서 · 앱 소개 페이지)을
[script2video](https://github.com/dev-yakuza/script2video)로 내레이션 영상으로 만들고, 고른
플랫폼에 함께 올릴 글의 초안을 씁니다.

[English](./README.md) · [日本語](./README.ja.md)

## 개념

- **원본은 이미 있는 글입니다.** 영상의 모든 사실(내레이션 · 화면 글자 · 제목 · 썸네일 · 챕터 ·
  배포용 글)은 원본에서 가져오고 원본과 대조합니다.
- **사람 검수 4단계** — ① 대본 ② 오디션 ③ 정지 화면 ④ 최종(④a 영상 · ④b 배포용 글).
  에이전트가 사람 대신 승인하지 않습니다.
- **생성만 하고 게시하지 않습니다** — 올리는 것은 사람입니다.
- **렌더링은 script2video가** — Studio는 계획 · 검사 · 질문 · 커밋을 맡습니다.

## 요구 사항

- **Claude Code**: Claude Code 2.1.304, 2.1.308, 2.1.311에서 테스트했습니다(2.1.304 미만이나 2.1.311 초과이면 `/std init`이 경고).
- **git**, 그리고 훅이 보는 `PATH`에 **python3** 3.9 이상.
- **script2video** 0.13.0 이상과 그 요구 사항(Node 22+, Yarn 4, uv, ffmpeg, `yarn build`, 모델):
  [script2video README](https://github.com/dev-yakuza/script2video#readme)를 보세요.
- **가드는 모든 호출에서 실행됩니다.** Studio가 활성화된 프로젝트의 모든 세션에서(`/std init` 전에도) Studio 가드 훅이
  Bash, Write, Edit, MultiEdit, NotebookEdit, WebFetch, WebSearch, MCP 도구 호출을 하나하나 검사합니다.
  `onFailure: block`으로 실행되므로 훅의 오류나 시간 초과는 그 호출을 막고(측정함), `python3`가 없을 때도 막을 것으로
  봅니다(측정하지 않음). `python3`가 pyenv나 asdf 방식의 shim이면 가드 호출마다 느려지고 0.0.28의 가드 자체 허용이
  꺼집니다([docs/guard-limits.ko.md](docs/guard-limits.ko.md)). Command Line Tools가 없는 macOS에서는
  `/usr/bin/python3`가 훅의 20초 시간 제한까지 기다릴 수 있습니다.
- **호출당 비용**(기기 한 대, Apple silicon Mac): 하네스가 없는 레포에서 Bash `git status`에 대한 가드는 약 80 ms(p50,
  Python 3.9.9와 3.15.2), macOS의 `/usr/bin/python3` 3.9.6으로는 약 155 ms 걸렸습니다
  (`tests/py/test_guard_entry.py`, `PerfNoHarness`). 가드는 Claude Code의 셸 스냅숏(최근 세션마다 하나, 각 ~280 KB)도
  읽습니다. 스냅숏이 13개일 때 같은 호출은 약 140 ms(3.15.2), 약 170 ms(3.9.9) 걸렸고, 파일이 하나 늘 때마다 약 5 ms가
  더 듭니다(`PerfSnapshots`).

## 설치

Claude Code에서:

```text
/plugin marketplace add dev-yakuza/deku-claude-plugins
/plugin install studio-plugin@deku-claude-plugins --scope project
```

Claude Code 문서에 따르면 project 범위는 프로젝트의 `.claude/settings.json`(커밋되는 파일)의 `enabledPlugins`에
`"studio-plugin@deku-claude-plugins": true`를 씁니다. 레포에서 일하는 모든 사람에게 Studio와 그 가드가 켜집니다. 이
레포에서 나에게만 켜려면 `--scope local`(`.claude/settings.local.json`, 커밋하지 않음)을 씁니다.

이 레포의 체크아웃에서: `claude --plugin-dir plugins/studio-plugin`.

## 처음 실행

1. 레포의 최상위 폴더에서 Claude Code를 시작합니다.
2. `/std init` — 이 기기의 script2video 체크아웃을 묻고, 레포를 읽고, 몇 가지를 물은 뒤 계획을 보여 줍니다. 확인하면
   그것이 첫 하네스 커밋입니다.
3. `/std make <source> --kind <kind>` — 글 하나에서 영상 하나(`/std help`가 커맨드를 보여 줌).
4. 검수 ① 대본 ② 오디션 ③ 정지 화면 ④ 최종(④a 영상 · ④b 배포용 글), 그다음 영상 커밋.

승인 질문: 제시된 선택지 중 하나를 고릅니다. AskUserQuestion 허용 규칙을 더하지 말고, Studio를 bypass 권한 모드로
실행하지 마세요.

## 새 clone이나 워크트리

하네스는 커밋되어 있지만, 이 기기의 s2v 경로와 pre-commit 훅은 그렇지 않습니다. 새 clone이나 워크트리에서 한 번:

```text
/std config s2v.path <이 기기의 script2video 체크아웃 절대 경로>
```

그리고 터미널에서, 그 최상위 폴더에서:

```bash
python3 .claude/studio/scripts/hooks.py install
```

둘 중 하나가 없으면 `/std status`가 알려 줍니다.

## Studio 지우기

정확한 명령과 함께 단계별로(먼저 영상과 백업 남기기, 모든 워크트리, 훅, 레포 밖의 폴더):
[docs/removing.ko.md](docs/removing.ko.md).

## 참고

- **s2v 경로는 기기마다** 둡니다. `.claude/studio/local/machine.json`(커밋하지 않음)에 clone · 워크트리마다 한 번,
  `config.json`에는 s2v 최소 버전만 남습니다.
- **승인 답은 레포 하나에서 한 번만** 쓰입니다. 같은 레포의 워크트리는 그 기록을 나누지만, 따로 받은 clone(별도
  `git clone`)은 나누지 않습니다. 영상의 답은 그 영상과 해시를 담고 있어 다른 clone에 맞는 일이 드물고, 영상이 없는
  답(설정 · 갱신)만 남는 경우입니다. 0.0.9 이하가 워크트리마다 남긴 기록은 무시됩니다.

## 버전 노트

- **초기 샌드박스(스크립트 8 이하)를 손으로 옮기기**: `.claude/studio/config.json`의 `"s2v"` 아래
  `"path"`를 지우고, `.claude/studio/local/machine.json`(링크가 아닌 실제 폴더)에
  `{"schema": 1, "s2v": {"path": "<절대 경로>"}}`를 씁니다.
- **0.0.23으로 올릴 때**: `/std update`가 Studio의 ignore 블록(`.gitignore`와 `info/exclude`)을 새로 써서 출처 초안과
  오디오 폴더가 추적되지 않은 파일로 보이지 않게 합니다. `.gitignore` 변경은 갱신 뒤의 하네스 커밋에 함께 커밋합니다.
- **Studio 문서는 열지 않고 출력합니다(0.0.24).** `/std`는 명령 문서를
  `python3 "<plugin>/skills/std/scripts/setup.py" doc <name>`으로 읽습니다. 이 명령은 Studio 자신의 문서 하나를
  출력할 뿐입니다(읽기 전용이며 설정에 아무것도 더하지 않음). 플러그인 폴더는 작업 디렉터리 밖이라 Read로 열면 파일마다
  확인을 묻게 됩니다. 스킬은 `/std`를 시작한 턴에서만 이 명령을 미리 허용하고, 그 뒤로는 Studio 가드가 정확히 그
  호출(Bash 호출에 그것 하나, 플러그인 자신의 `setup.py`, 알려진 문서 이름)만 플러그인이 켜진 모든 세션(어느 레포든,
  서브에이전트 포함)에서 허용합니다. 사용자의 deny · ask 규칙은 그대로 적용됩니다. 실행 폴더의 레포가 플러그인 자체나 그
  레포의 Python(레포 안의 가상 환경)을 담고 있으면 허용하지 않습니다. 다루지 않는 경우(남은 위험): conda 환경, 레포 밖이나
  추가 작업 디렉터리의 가상 환경, 추가 작업 디렉터리에 있는 플러그인 체크아웃. `blockReadsOutsideWorkingDirectories`는
  파일 도구만 막고 프로세스는 막지 않으므로 `doc`을 막지 않습니다. 에이전트가 그래도 Read로 플러그인 파일을 열면 평소처럼
  확인을 묻습니다(Read에는 훅이 없음).
- **`/std init`이 값을 제안합니다(0.0.24).** 사이트의 도메인(CNAME 파일, 사이트 설정), 브랜드 색 최대 세 개
  (theme-color, brand/primary/accent 속성, 그다음 사이트 자체 스타일에서 가장 많이 쓴 색 — 외부 라이브러리 빌드와 압축
  파일은 제외), 로고 파일 최대 세 개를 찾은 곳과 함께 보여 줍니다. 추적되는 파일만 읽고 `.env*`는 읽지 않습니다. 찾은 것이
  없으면 Studio 기본값(`#2563EB`, 로고 없음, 도메인 없음)을 쓰고 요약에 밝힙니다. 어느 질문이든 직접 답을 입력할 수 있습니다.
- **0.0.25(파일럿 2).** 소스 분석가는 모든 주장에 자리표시 id `C-00000000`을 쓰고, `check_claims.py <video> --source
  --fill`이 진짜 id를 씁니다(`--source`만 쓰면 목록만 보여 줌). `check_claims.py <video> --skeleton`은 판정할 항목을 모두
  담은 verify 초안을 쓰고, 팩트체커는 이를 Edit로 채웁니다. 다시 실행해도 채운 내용은 남습니다. 대본 작가와 비주얼
  디렉터는 `setup.py doc s2v-syntax`로 s2v 대본 문법을 읽습니다(이 작업 트리의 s2v 안에 있는 25,000자 이하의 일반 파일).
  승인 명령은 이제 사람의 답 바로 뒤, 같은 턴의 다음 도구 호출로 실행합니다 — 질문과 같은 어시스턴트 메시지에는 절대
  넣지 않습니다. "This is not a stop"이라고 말하는 거부는 멈추지 않고 그대로 따릅니다: Read로 읽고 Write나 Edit로 씁니다.
  역할 에이전트는 모든 파일 작업을 이렇게 합니다. 가드는 이제 `sed`를 스크립트와 옵션의 모양으로 판단합니다: 단순 출력 ·
  삭제 · 치환은 통과하고(`-i ''`나 `-i.bak`로 하는 제자리 수정도 그 파일 쓰기로 판단), 판단할 수 없는 스크립트나 옵션은 Studio 레포 안에서 거부합니다.
  `state.py shown <video> 2`는 `read:` 줄로 `audition.md`를 알려 줍니다.
- **0.0.25로 올릴 때**: `/std update`를 실행하고 바뀐 역할 에이전트 파일마다 "new"를 고릅니다 — 모든 `std-*` 에이전트
  (Read/Write 규칙과 가드 규칙의 예외), 그중 `std-writer`와 `std-visual-director`(s2v 문법 명령), `std-fact-checker`
  (스켈레톤, 연결 문장 한도, 목록 항목과 빠진 조건), `std-source-analyst`(자리표시 id).
- **0.0.26(파일럿 2, 화면과 init).** 비주얼 디렉터가 브랜드를 적용합니다: `check_assets.py <video> --look --output <o>`가
  brand.json이 요구하는 프런트매터 줄 — `theme.accent`, 브랜드 로고(`logo.src`), 레이아웃(모든 화자에게 캐릭터 그림이
  없으면 `fullscreen`; s2v의 기본값 `presenter`는 그림 없이는 아무도 그리지 않음) — 을 출력하고, 대본에 이것이 없으면
  보드 검사가 실패합니다. 보드는 이제 프런트매터의 `theme` · `logo` · `outputs.<o>.layout` · `transition`도 바꿀 수
  있습니다(블록은 그대로). 브랜드 로고는 크레딧이 필요한 그림입니다(floor `public/brand.json logo (committed in the
  harness)`). brand.json과 로고는 커밋되어 있어야 합니다: 커밋 안 된 것은 보드 검사가 거부하고, 하네스 커밋은 커밋
  안 된 로고를 경고합니다. 로고는 PNG 또는 JPEG입니다. 대본 단계에서는 장면 1이 제목 장면이고(`::title[<프런트매터
  title>]`가 유일한 시각 요소 — 썸네일에 제목이 들어감; 대본에 `::thumbnail{src=…}`가 있으면 건너뜀), 글의 쓸 수 있는
  이미지는 모두 보여 주거나 클레임 맵의 `unused_images`에 한 줄 이유를 적으며(①에서 `unused:` 줄로 출력), 작가는
  레이아웃을 쓰지 않습니다. `/std init`은 이제 내레이터를 항상 묻고(그 언어의 원어민 화자 먼저, 억양이 있을 수 있다고
  표시한 다른 화자 둘까지 — ② 발음 검사에서 실패할 수 있음), 글이 쓰는 이미지 폴더를 `visibility.public` 후보로
  보여 주며, 사이트 제목 · 웹 매니페스트 · package.json · origin 원격의 저장소 이름(URL은 출력하지 않음)에서 프로젝트
  이름 후보를 내고, 커밋 안 된 로고는 거부합니다(로고 없음을 고르거나 먼저 커밋).
- **0.0.26으로 올릴 때**: `/std update`를 실행하고 `std-visual-director`, `std-writer`, `guides/board.md`,
  `guides/script.md`에서 "new"를 고릅니다(가이드에 직접 고친 내용이 있으면 업데이트가 차이를 보여 줌). brand.json과
  로고가 커밋되어 있고 로고가 PNG 또는 JPEG인지 확인합니다(아니면 `""`). 글 이미지 폴더가 `visibility.public`에 없으면
  `/std config`로 넣습니다. 이미 보드를 지난 영상은 렌더 전에 먼저 `/std board <video>`를 실행합니다: 그러지 않으면
  영상 커밋에서 보드 검사의 화면 규칙이 실패해 보드로 돌아가고 ③, ④a 렌더, ④a를 다시 거칩니다. 진행 중인 영상은
  소스 단계를 다시 할 필요가 없습니다.
- **0.0.27 (G1: 가드가 더 많이 읽음).** 가드는 풀어서 읽는 흔한 실행기(env · nohup · nice · timeout · time · script ·
  flock · xargs · npx 등)의 옵션을 읽고 그 파일 인자를 판정합니다. Studio 레포에서는 읽을 수 없는 실행기와 옵션, 가드가
  아는 명령 값 옵션과 변수(`git -c core.editor` 등), 가드가 아는 모든 경로에서 명령을 실행하는 git 설정, 파싱할 수 없는
  zsh 형식을 거부합니다. 글롭 그룹 `(…)`이 있는 파일 이름 단어가 그 예입니다(Bash 도구는 zsh를 `BARE_GLOB_QUAL`을 끈 채 실행하므로
  `studi(o)`가 `studio`와 맞음). 사용자 셸 함수나 명령이 정의한 함수 뒤, 그리고 훅(`chpwd`, `TRAP*`) 뒤에서는 가드가
  따라갈 수 없는 것을 알 수 없는 것으로 봅니다. 그래서 git, 삭제, 따옴표 없는 `$X`가 거부될 수 있습니다. 모든 호출은
  0.0.26 가드로도 검사합니다: 0.0.26이 거부한 것은 계속 거부하며, 그 잘못된 거부도 그대로입니다(`rm -rf **/__pycache__`
  등). `source`나 `.` 뒤(그리고 가드가 읽을 수 없는 텍스트의 `eval` 뒤)의 나머지는 0.0.26 규칙만으로 판정합니다. 거기서의
  더 강한 검사는 0.0.28에서 할 예정입니다. Studio 레포에서 명령이 지우거나 쓰는 `~[name]` 경로는 거부합니다. Studio 레포
  밖에서는 가드의 한도를 넘는 긴 명령은 레포를 가리킬 수 있는 것이 하나도 없을 때만 통과합니다. 자세한 내용:
  [docs/guard-limits.ko.md](docs/guard-limits.ko.md). 가드는 플러그인의 일부라서 `/std update`는 필요 없습니다.
- **가드가 아직 보지 못하는 것(0.0.27).** 전체 목록은 [docs/guard-limits.ko.md](docs/guard-limits.ko.md)에 있습니다.
  요약하면:
  - 가드가 모델링하지 않는 방식으로 명령을 실행하는 프로그램과 설정(awk 프로그램, `NODE_OPTIONS` 등).
  - 가드가 읽을 수 없는 값(그런 값을 통한 삭제: `rm -rf $X`, `f() { rm -rf $1; }; f studio` 등).
  - Studio 레포 밖에서 쓴 형식(레포를 가리키는 인터프리터 코드 `python3 -c`, 기본값에만 적힌 폴더 `cd ${U:-<레포>}` 등).
  - 그 밖의 경우(`chmod 000 studio`, 보호 파일 위에 쓰는 아카이브 등).

  이런 경우에도 pre-commit 훅, 커밋 검사, 사람의 게이트가 뒤에 남아 있습니다.
- **0.0.28 (파일럿 3).** `state.py next <video> --enter script`가 작가가 그대로 옮길 frontmatter 줄을 출력합니다: 기본
  내레이터의 `cast:` 블록(s2v의 콘텐츠 해시에 들어가므로 처음부터 대본에 있고, 캐스트 단계는 더 이상 고치지 않음), 출력별
  `aspect`와 `maxDuration`, `targetDuration`의 범위(ceil(min ÷ 0.85)부터 floor(max ÷ 1.15)까지: youtube는 212–417이라
  s2v lint를 통과한 대본은 형식의 길이 안에 있음). `check_claims --narration`은 cast 블록을 검사하고 s2v의 실패 메시지를
  모두 출력합니다. 클레임 맵은 클레임을 말하는 대본의 모든 텍스트(화면 텍스트와 제목 포함)를 나열하고, 검증 메시지는 그
  텍스트와 위치를 밝힙니다. `check_claims --source`는 사본에 없거나 태그 안 또는 문장 중간에서 끊긴 발췌를 거부합니다.
  `record-brief --from`은 레포 루트 기준 경로도 받습니다(영상 폴더 안만). ② 질문에는 오디션이 재생하는 문장과 `read:`
  줄이 들어가고, `shown 3`과 `shown 4a`도 질문 블록을 출력합니다(④a는 소리·자막·그림이 함께 맞는지 확인을 요청). `assets.json`은
  CREDITS용 `floor_text`를 담습니다. `record-source --url <https://<공개 도메인>/…>`이 글의 주소를 기록하고, 배포용 글
  설명에는 `원문: <url>`이 있어야 합니다. 하네스 커밋의 값 블록에 brand.json의 이름·색·로고가 나옵니다.
  `begin --ask-before tts,render`(그리고 `state.py ask-before`)가 사람이 묻고 멈추라고 한 단계를 기록합니다. 모든 명령
  문서의 Rules 줄은 명령을 그대로 실행하고, 반복하지 않고, `open`만 쓰라고 합니다.
- **확인 요청 줄이기(0.0.28).** `default` 권한 모드에서 가드는 이제 Studio 자신의 스크립트 호출(레포 사본이 바뀌지 않고
  온전하며, 리터럴 인자로 단독 실행)과 각 역할이 자기 출력 파일에 쓰는 것을, 모든 조건이 맞을 때 확인 요청 없이
  허용합니다. 조건이 하나라도 맞지 않으면 평소처럼 확인을 요청합니다. `run_s2v.py`, `lock.py`, `check_commit.py`,
  `state.py ask-before`는 계속 확인을 요청합니다. Claude는 레포 폴더에서 시작하세요. 조건과 한계:
  [docs/guard-limits.ko.md](docs/guard-limits.ko.md).
- **0.0.28로 올릴 때**: `/std update`를 실행하고(스크립트 버전 25) `std-writer`, `std-source-analyst`,
  `std-visual-director`, `std-distributor`, `guides/script.md`, `formats/youtube.md`(새 `source_label`)에서 "new"를
  고릅니다. `"`나 `\`가 들어간 내레이터 스타일은 이제 `/std config` 내레이터에서 거부되니 거기서 바꿉니다. 아직 대본 단계에
  있는 영상은 대본에 cast 블록이 필요합니다(대본 검사가 알려 줌). 블록 없이 ①을 승인받은 영상은 대본 단계로 돌아갑니다
  (`/std script <video>` 후 검증과 ①을 다시). 캐스트를 지난 영상은 이미 있는 블록을 그대로 씁니다.
- **0.1.0**: 마켓플레이스 등록. 0.0.28에서 올릴 때는 `/std update`가 필요 없습니다(스크립트 버전은
  그대로 25).
- **0.1.1**: 가드가 셸 스냅숏을 약 절반의 시간에 읽습니다. 스냅숏 13개에서 호출당 전체 시간이 약 3분의 1 줄었습니다(이
  기기에서 Python 3.15.2로 210 → 140 ms, 3.9.9로 300 → 170 ms; 판정은 같음). 메시지와 템플릿에 내부 마일스톤 이름이 더는
  나오지 않습니다. pre-commit shim의 안내는 `hooks.py install`만 가리킵니다. 환경 변수 몇 개와 pyenv의 PATH도 가드
  자체 허용을 끕니다 — 셸에 전역 `PYTHONPYCACHEPREFIX`나 `GIT_CEILING_DIRECTORIES`가 있으면 Studio 스크립트 호출은
  다시 확인을 요청합니다. 이 검사는 셸 스냅숏 어디에 있는 `NAME=`에도(함수 본문 포함) 걸립니다.
- **0.1.1로 올릴 때**: `/std update`를 실행합니다(스크립트 버전 26). `platforms/youtube.md`의 `checked`를 채웠다면
  "local"을 고릅니다. 날짜가 그대로 남고, 예전 문장은 내부 마일스톤 이름만 담고 있었습니다("new"는 `checked`를 비우고,
  다시 채울 때까지 `validate_copy.py`가 모든 카피를 거부합니다). 고친 `formats/youtube.md`도 "local"을 고릅니다. 그
  밖에 바뀐 템플릿은 레포에 설치되지 않는 플러그인 파일입니다(할 일 없음). 0.1.0이 쓴 클론의 pre-commit shim은 그대로
  유효하며, `hooks.py install`이 새 내용을 씁니다.

## 라이선스

MIT
