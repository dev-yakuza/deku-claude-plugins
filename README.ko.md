[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md)

# deku-claude-plugins

개발을 위한 Claude Code 플러그인 마켓플레이스입니다.

## 설치

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install <plugin-name>@deku-claude-plugins
```

## 플러그인

| 플러그인 | 설명 | 문서 |
|----------|------|------|
| [guild-plugin](./plugins/guild-plugin) | 자가진화하는 에이전트 조직 - Claude Code 하네스를 구축하고, 스펙 주도 흐름(분석 → 설계 → 실행 → 테스트)으로 개발하며, 코드베이스·에이전트 팀·사용자를 함께 성장시킴 | [문서](./plugins/guild-plugin/README.ko.md) |
| [herald-plugin](./plugins/herald-plugin) | 레포별 편집 조직 - 주제를 기획하고 글을 쓰고 검증하며, PR 리뷰로 발행하고 실제 사용에서 가이드를 키움 | [문서](./plugins/herald-plugin/README.ko.md) |
| [sdd-plugin](./plugins/sdd-plugin) | Spec-Driven Development - GitHub 연동 AI 협업 개발 프로세스 | [문서](./plugins/sdd-plugin/README.ko.md) |
| [skill-quality-plugin](./plugins/skill-quality-plugin) | 구조화된 38항목 루브릭으로 Claude Code 스킬 품질 평가 | [문서](./plugins/skill-quality-plugin/README.ko.md) |
| [studio-plugin](./plugins/studio-plugin) | 레포별 영상 제작 조직 - 레포에 이미 있는 글을 script2video로 내레이션 영상으로 만들고, 원문 대조 사실 확인·사람 검수 4단계·플랫폼 문구를 제공 | [문서](./plugins/studio-plugin/README.ko.md) |

## 라이선스

MIT
