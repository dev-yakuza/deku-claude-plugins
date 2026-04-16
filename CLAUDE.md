# SDD Plugin

Spec-Driven Development (SDD) Claude Code plugin. All skill logic is in Markdown files under `plugins/sdd-plugin/skills/sdd/`.

## Version Update

When changing a plugin's version, always update BOTH files together:
- `plugins/<plugin-name>/.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json` (해당 plugin의 version 필드)
