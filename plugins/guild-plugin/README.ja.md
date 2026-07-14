# Guild Plugin

Claude Code のための**自己進化するエージェント組織**。Guild はリポジトリに作動環境（*ハーネス*）を構築し、リポジトリ専用の特化ロールエージェントチームが仕様駆動フローで GitHub Issue を開発し、実際の使用トレースから**コードベースとエージェントチームを共に成長（共進化）**させます。

> `sdd-plugin`・`skill-quality-plugin` の後継。— *"レベルアップするエージェントギルド。"*

[English](./README.md) · [한국어](./README.ko.md)

## コンセプト

- **ハーネス** — Guild がインストールする作動環境：`CLAUDE.md`、settings、ロールエージェントのロスター、⑥ ナレッジベース、standards ドラフト、決定的コミットゲート。
- **組織** — リポジトリ専用の **16 ロールエージェント**（背骨：leader · tech-lead · developer · tester · qa ＋ 条件付きスペシャリスト — designer, security, dba, i18n …）が背骨をまたいで協働し、*あなたの*プロジェクトに特化します。
- **2つのループ** — **Inner ループ**はコードを開発（`analyze → design → execute → test → qa`）、**Outer ループ**（`evolve`）は実トレースを読みエージェント・知識・ゲートを成長させます。
- **共進化** — コードベース（成果物）と Guild（開発者）が使用から共に改善。`evolve` がトレースをレビュー済み・人間承認済みの改善へ蒸留します。

## インストール

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install deku-claude-plugins@guild-plugin
```

## クイックスタート

```bash
/gld init            # リポジトリ分析・オンボーディング → ハーネス + 創設 Guild エージェント + standards + ⑥ ベースライン（一度きり）
/gld dev 123         # GitHub Issue #123 をエンドツーエンド開発（feature/bug/refactor 自動選択）
/gld status 123      # 進捗確認   ·   /gld resume 123 で継続
/gld audit           # ハーネス+チーム+コードベースの読み取り専用ヘルスチェック
/gld evolve --dry-run  # Guild の成長提案（変更なし）
```

## コマンド

**セットアップ** — `init [lang]`（一度きりのオンボーディング）· `config`（ダイヤル・オフスイッチ）· `update [--check]`（中央の改善を採用、ローカル進化を保存）

**開発**（背骨：analyze → design → execute → test → qa）— `dev <issue>`（フル、execute バリアント自動選択）· `analyze` · `design` · `implement`（機能）· `debug`（バグ：再現→根本原因→修正）· `refactor`（振る舞い保存）· `test` · `qa` · `review <issue>`（ガイド付きペアレビュー + 敵対的プリスキャン）· `resume` · `status` · `batch [issues]`（無人、レート制限自動再開）

**診断・成長** — `audit`（読み取り専用、evolve/refactor へルーティング）· `evolve [--dry-run|--apply]`（スキャン → 敵対的パネル → 項目別承認 → バックアップ/ロールバック/provenance/台帳で適用）· `contribute`（フロー改善をアップストリーム）

**オンデマンド・観察** — `rollback <target>`（非破壊アンドゥ）· `ask <question>`（standards+⑥ に基づく引用付き Q&A）· `monitoring [--html]`（状態スナップショット）

**自律** — `sprint [issues]`（Inner+Outer、**準備度ゲート** — 自律は計測で獲得）

## 安全性（不変条件）

Guild は自己修正システムなので、安全性は助言ではなく決定的です：

- **INV1 — 適用は常に人間の承認が必要。** トリガーは自動、変更は無人適用されない（evolve 適用・HR・全ゲートは項目別に人間ゲート）。
- **INV2 — 検証を弱めない。** テスト/ゲートを削除・弱体化する変更はハードブロック（コミットゲート + evolve 検証）。
- **INV3 — すべて可逆**（git · `/gld rollback` · evolve 検証失敗時の自動ロールバック）。
- **INV4 — 加算的、ローカル進化を上書きしない**（エージェント・知識・standards・overlay）。
- **INV5 — サニタイズなしにマシン外へ出ない**（`contribute` はサニタイズ + 重複検査 + 人間レビュー後に送信）。
- **オフスイッチ** — `/gld config` で自動化・ゲートブロックを一時停止。

**決定的コミットゲート**（`PreToolUse` フック）がシークレットのコミットや検証の弱体化をブロックし、permission mode で回避不可。

## 状態の保存場所

| 何を | どこに |
|---|---|
| 開発状態（ステージ・出力） | GitHub Issue/PR + `guild:*` ラベル |
| ロールエージェント（習慣） | `.claude/agents/*.md` |
| コードベースの事実（⑥、関連分のみ検索） | `.claude/guild/knowledge/` |
| 生のエピソード記憶 | `.claude/guild/memory/`（gitignore） |
| 進化台帳 + ゲート + 設定 | `.claude/guild/` |
| キュレーション標準（charter・architecture…） | `docs/standards/` |

## ライセンス

MIT
