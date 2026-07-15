[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md)

# deku-claude-plugins

開発のためのClaude Codeプラグインマーケットプレイスです。

## インストール

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install deku-claude-plugins@<plugin-name>
```

## プラグイン

| プラグイン | 説明 | ドキュメント |
|------------|------|--------------|
| [guild-plugin](./plugins/guild-plugin) | 自己進化するエージェント組織 - Claude Codeハーネスを構築し、スペック駆動フロー（分析 → 設計 → 実行 → テスト）で開発し、コードベース・エージェントチーム・ユーザーを共に成長させる | [ドキュメント](./plugins/guild-plugin/README.ja.md) |
| [sdd-plugin](./plugins/sdd-plugin) | Spec-Driven Development - GitHub連携AI協業開発プロセス | [ドキュメント](./plugins/sdd-plugin/README.ja.md) |
| [skill-quality-plugin](./plugins/skill-quality-plugin) | 構造化された38項目のルーブリックでClaude Codeスキル品質を評価 | [ドキュメント](./plugins/skill-quality-plugin/README.ja.md) |

## ライセンス

MIT
