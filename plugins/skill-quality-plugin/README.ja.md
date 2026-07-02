# skill-quality-plugin

Claude Code スキルファイルを38項目の品質ルーブリックで評価します。マーケットプレイスやチームライブラリへの公開前に実行してください。

## なぜ必要か

descriptionが欠けていたり、トリガー条件が曖昧だったり、構造エラーがあるスキルは、Claudeがいつ・どのように呼び出すかを判断できません。このプラグインはそのような問題をユーザーに届く前に検出します。

## インストール

`.claude-plugin/marketplace.json`に追加するか、Claude Codeプラグインマーケットプレイス経由でインストールしてください。

## 使い方

```
/skill-quality check [path] [--depth=shallow|deep] [--rules-only] [--json]
/skill-quality report [path] [--depth=shallow|deep] [--json]
/skill-quality rubric
/skill-quality help
```

### check — 単一スキルの評価

```bash
# カレントディレクトリのスキルをチェック
/skill-quality check .

# 特定のスキルをチェック
/skill-quality check ./plugins/my-plugin/skills/my-skill

# 高速ルールチェックのみ（LLMモデルチェックなし）
/skill-quality check . --rules-only

# 詳細チェック（opusモデル使用）
/skill-quality check . --depth=deep

# CI/CD向けJSON出力
/skill-quality check . --json
```

**出力例:**

```
/skill-quality check: plugins/my-plugin/skills/my-skill
══════════════════════════════════════════════════════════════════════
Grade: A  (rubric v1.0)

MAJOR (2)
  [T1] WHAT not in description — "helps with tasks" is too vague
       Fix: Add what the skill does: "Generates unit tests for..."
  [C1] No org-specific knowledge — body reads as generic instructions
       Fix: Add project-specific constraints or examples

Suggestions (1)
  [R7] SKILL.md is 312 lines — consider moving content to references/

══════════════════════════════════════════════════════════════════════
BLOCKER: 0  MAJOR: 2  MINOR: 1
```

### report — ディレクトリ一括チェック

```bash
# 高速一括監査（ルールチェックのみ）
/skill-quality report ./plugins

# モデルチェックを含む詳細監査
/skill-quality report ./plugins --depth=deep
```

### rubric — 全ルーブリックを表示

```
/skill-quality rubric
```

38項目すべての基準・重大度・チェック方法を表示します。

## グレード体系

| グレード | 条件 | 意味 |
|---------|------|------|
| **S** | BLOCKER 0、MAJOR 0 | 公開可能 |
| **A** | BLOCKER 0、MAJOR 1–2 | 軽微な修正後に公開可能 |
| **B** | BLOCKER 0、MAJOR 3–5 | 公開前に作業が必要 |
| **C** | BLOCKER 0、MAJOR 6–9 | 重大な問題あり |
| **D** | BLOCKER 0、MAJOR 10+ | 大規模な修正が必要 |
| **F** | BLOCKER 1個以上 | 公開不可 |

## ルーブリック概要

7セクション38項目:

| セクション | 項目 | BLOCKER | 重点 |
|-----------|------|---------|------|
| ST — 構造 | 8 | 3 | 有効なfrontmatter、name形式、サイズ |
| F — フロントマターセマンティクス | 5 | 1 | フィールドの一貫性、effortの値 |
| T — トリガー | 6 | 0 | WHAT/WHENの明確さ、語調、具体性 |
| C — コンテンツ | 6 | 0 | 組織固有の知識、例 |
| R — リソース | 8 | 0 | パスの衛生、referencesの構造 |
| SF — 安全性 | 2 | 2 | シークレットなし、破壊的コマンドなし |
| V — 妥当性 | 2 | 0 | 目的、非冗長性 |

全項目と基準は `/skill-quality rubric` で確認できます。

## 深度モード

| モード | 速度 | モデル | 使用タイミング |
|--------|------|--------|--------------|
| `--rules-only` / `--depth=shallow` | 高速 | haiku | コミット前の素早いチェック |
| デフォルト | 中速 | sonnet | 公開前の標準チェック |
| `--depth=deep` | 徹底的 | opus | 最終品質ゲート |

## アーキテクチャ

- **check**: メインセッションがrule_checks(haiku) → model_checks(sonnet/opus)をサブエージェントとして順次生成。メインセッションは`>>> RESULT <<<`要約行のみ読み取り — コンテキスト最小化。
- **report**: メインセッションがスキルごとに自己完結型サブエージェントを並列生成（最大4並列）。追加ネストなし。

## Fixtures

`fixtures/`ディレクトリには各グレードのサンプルスキルが含まれています:

- `fixtures/example-s-grade/` — Sグレード（公開準備完了）
- `fixtures/example-b-grade/` — Bグレード（作業が必要）
- `fixtures/example-f-grade/` — Fグレード（BLOCKERあり）

## ライセンス

MIT
