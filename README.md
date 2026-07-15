[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md)

# deku-claude-plugins

A marketplace of Claude Code plugins for development.

## Installation

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install deku-claude-plugins@<plugin-name>
```

## Plugins

| Plugin | Description | Docs |
|--------|-------------|------|
| [guild-plugin](./plugins/guild-plugin) | A self-evolving agent organization - sets up a Claude Code harness, develops via a spec-driven flow (analyze → design → execute → test), and co-evolves your codebase, your agent team, and you | [docs](./plugins/guild-plugin/README.md) |
| [sdd-plugin](./plugins/sdd-plugin) | Spec-Driven Development - AI collaborative development process with GitHub integration | [docs](./plugins/sdd-plugin/README.md) |
| [skill-quality-plugin](./plugins/skill-quality-plugin) | Evaluate Claude Code skill quality with a structured 38-item rubric | [docs](./plugins/skill-quality-plugin/README.md) |

## License

MIT
