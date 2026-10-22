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

그다음 `/std help`. script2video 0.12.1 이상이 필요합니다(나중에 `/std init`이 설정).

## 참고

- **s2v 경로는 기기마다** 둡니다. `.claude/studio/local/machine.json`(커밋하지 않음)에 clone · 워크트리마다 한 번,
  `config.json`에는 s2v 최소 버전만 남습니다.
- **승인 답은 레포 하나에서 한 번만** 쓰입니다. 같은 레포의 워크트리는 그 기록을 나누지만, 따로 받은 clone(별도
  `git clone`)은 나누지 않습니다. 영상의 답은 그 영상과 해시를 담고 있어 다른 clone에 맞는 일이 드물고, 영상이 없는
  답(설정 · 갱신)만 남는 경우입니다. 0.0.9 이하가 워크트리마다 남긴 기록은 무시됩니다.
- **0.0.x 샌드박스를 손으로 옮기기**(`/std config`가 생기기 전까지): `.claude/studio/config.json`의 `"s2v"` 아래
  `"path"`를 지우고, `.claude/studio/local/machine.json`(링크가 아닌 실제 폴더)에
  `{"schema": 1, "s2v": {"path": "<절대 경로>"}}`를 씁니다.

## 라이선스

MIT
