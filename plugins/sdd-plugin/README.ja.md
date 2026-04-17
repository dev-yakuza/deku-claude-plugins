[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md)

# SDD Plugin (Spec-Driven Development)

Claude Codeを活用したAI協業開発プロセスです。GitHub Issueを通じて構造化されたプロセスで開発ライフサイクル全体を管理します。

## インストール

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install deku-claude-plugins@sdd-plugin
```

## クイックスタート

```bash
# 1. リポジトリにSDDをセットアップ（言語選択）
/sdd init           # 英語（デフォルト）
/sdd init ko        # 韓国語
/sdd init ja        # 日本語

# 2. SDDテンプレートでGitHub Issueを作成

# 3. 開発プロセスを開始
/sdd analyze 123     # 要件分析（What/Why）
/sdd design 123      # 設計（How）
/sdd implement 123   # TDD実装
/sdd test 123        # E2EおよびQAテスト
```

## コマンド

| コマンド | 説明 |
|----------|------|
| `/sdd init [lang]` | Issueテンプレートとラベルをセットアップ。言語: `en`（デフォルト）、`ko`/`korean`/`한국어`、`ja`/`japanese`/`日本語` |
| `/sdd analyze <issue>` | ステージ1: 要件分析（What/Why） |
| `/sdd design <issue>` | ステージ2: 設計（How） |
| `/sdd implement <issue>` | ステージ3: TDD実装 |
| `/sdd test <issue>` | ステージ4: E2E/QAテスト |
| `/sdd resume <issue>` | ステージを自動検出し、中断箇所から再開 |
| `/sdd rollback <issue> <stage>` | 前のステージにロールバック（analyze、design、implement） |
| `/sdd status <issue>` | 現在の進捗状況を確認 |
| `/sdd review <issue>` | 現在の成果物をAIレビュー |
| `/sdd config` | SDD設定の確認または変更 |
| `/sdd help` | 使い方を表示 |

## プロセス

```
1. 要件（What/Why） → 2. 設計（How） → 3. 実装（TDD） → 4. テスト（E2E/QA）
```

### ステージ1: 要件分析（What / Why）

**何**を作るか、**なぜ**必要かに集中します。技術的な実装方法（How）はこのステージでは扱いません。

**フロー:** ① 入力 → ② AI分析 → ③ 成果物 → ④ AIレビュー → ⑤ ユーザーレビュー → 次のステージ

### ステージ2: 設計（How）

要件に基づいて**どのように**実装するかを定義します。

**フロー:** ① 入力 → ② AI設計 → ③ 成果物 → ④ AIレビュー → ⑤ ユーザーレビュー → 次のステージ

### ステージ3: 実装 - TDDサイクル

PR単位でTDDサイクルを実行します:

```
3-0. PRキックオフ: テスト＆実装計画
3-1. Red: 失敗するテストを作成
3-2. Green: 最小限の実装
3-3. Refactor: コード改善
3-4. PR作成＆コードレビュー（手動テストチェックリスト含む）
→ 次のPRを繰り返し
```

テスト範囲: ユニットテスト / UIテスト
PRにはレビュアーがUI動作、ユーザーフロー、エッジケースを検証するための手動テストチェックリストが含まれます。

### ステージ4: テスト

- E2E自動テスト（AIがコード作成・テスト実行）
- QAチェックリスト（AIが作成、人が実行）
- リグレッションテスト

### マルチPRワークフロー（親子Issue）

設計ステージで複数のPRが識別されると、SDDが自動的に子Issueを作成します:

```bash
/sdd analyze 100    # 親Issueを分析
/sdd design 100     # 設計が3つのサブ機能に分割 → #101、#102、#103を作成

# 各子Issueを独立して作業
/sdd analyze 101    # 子が親のコンテキストを継承
/sdd design 101
/sdd implement 101
/sdd test 101       # 子 #101 完了 → 親のステータスを更新

/sdd resume 100     # 親を確認: #101 ✓、#102 保留中、#103 保留中
/sdd analyze 102    # 次の子の作業を続行...

# すべての子が完了後
/sdd test 100       # 親レベルのE2E/QAテスト
```

### レビュースキップ設定

デフォルトではすべてのステージでユーザーレビューが必要です。`/sdd config`を使用して特定ステージのユーザーレビューをスキップできます:

```bash
# skip-reviewを設定
/sdd config --skip-review=analyze,design,implement

# 現在の設定を確認
/sdd config

# リセット（すべてのレビューを有効化）
/sdd config --skip-review=
```

| 値 | スキップされるレビュー |
|----|----------------------|
| `analyze` | 要件分析後のユーザーレビュー |
| `design` | 設計後のユーザーレビュー |
| `implement` | TDDサブステップ（3-0〜3-3）のユーザーレビュー |
| `pr` | PRコードレビュー（3-4）のユーザーレビュー |
| `qa` | 手動QA実行（4-2〜4-3） |

設定は`.github/.sdd-config`に保存されます。AIレビューはこの設定に関係なく常に実行されます。

### 言語設定

`/sdd init`実行時に言語が`.github/.sdd-lang`に保存されます。以降のすべてのコマンドはこの設定を使用してテンプレートと成果物を生成します。

言語を変更するには、新しい言語で`/sdd init`を再実行してください:

```bash
/sdd init ja        # 日本語に切り替え
```

## GitHub連携

すべての成果物はGitHubに保存されるため、別途ファイル管理は不要です。

| データ | 保存場所 |
|--------|----------|
| 要件（入力） | Issue本文 |
| 分析成果物 | Issueコメント |
| 設計成果物 | Issueコメント |
| 現在のステージ | Issueラベル |
| 実装 | Pull Request |
| テスト結果 | Issueコメント |

### ラベル

| ラベル | ステージ |
|--------|----------|
| `sdd:analyze` | 要件分析 |
| `sdd:design` | 設計 |
| `sdd:implement` | 実装 |
| `sdd:test` | テスト |
| `sdd:done` | 完了 |
| `sdd:child` | 子Issue（設計ステージで作成） |

## ライセンス

MIT
