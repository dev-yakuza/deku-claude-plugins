# Studio 플러그인

> **개발 중(0.0.x).** Studio는 아직 마켓플레이스에 없고, 커맨드는 "아직 구현되지 않음"으로
> 답합니다. 실제 레포에서 쓰지 마세요.

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

## 로컬에서 써 보기

```bash
claude --plugin-dir plugins/studio-plugin
```

그다음 `/std help`. script2video 0.13.0 이상이 필요합니다(나중에 `/std init`이 설정).

## 참고

- **s2v 경로는 기기마다** 둡니다. `.claude/studio/local/machine.json`(커밋하지 않음)에 clone · 워크트리마다 한 번,
  `config.json`에는 s2v 최소 버전만 남습니다.
- **승인 답은 레포 하나에서 한 번만** 쓰입니다. 같은 레포의 워크트리는 그 기록을 나누지만, 따로 받은 clone(별도
  `git clone`)은 나누지 않습니다. 영상의 답은 그 영상과 해시를 담고 있어 다른 clone에 맞는 일이 드물고, 영상이 없는
  답(설정 · 갱신)만 남는 경우입니다. 0.0.9 이하가 워크트리마다 남긴 기록은 무시됩니다.
- **0.0.x 샌드박스를 손으로 옮기기**(`/std config`가 생기기 전까지): `.claude/studio/config.json`의 `"s2v"` 아래
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
- **가드가 아직 보지 못하는 것(0.0.25).** awk 프로그램과 vim · ex · ed 스크립트, 일부 실행기 뒤에 숨은 명령: 가드가
  모르는 래퍼 옵션, 긴 래퍼 사슬, `flock` · `setsid` · `arch` · `xcrun` · `sandbox-exec` · `unshare` · `chroot`, 대문자로 쓴
  래퍼 이름, busybox나 toybox 애플릿, `script`, 래퍼의 파일 인자(`time -o`), `watch`, 쓰기 가능한 PATH 폴더(예: `/opt/homebrew/bin`)에 명령
  이름으로 놓인 프로그램, `sed` 외 명령에서 경로의 폴더 부분에 쓴 와일드카드(`.claude/*/…`). Studio 레포 밖에서 실행한 `sed`의
  경우: 스크립트 안의 단순 경로가 아닌 파일 이름, `e`와 셸을 실행하는 명령, 동적이거나 펼쳐지지 않은 변수. 이런 경우에도
  pre-commit 훅, 커밋 검사, 사람의 게이트가 뒤에 남아 있습니다.

## 라이선스

MIT
