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
/gld init            # リポジトリ分析・オンボーディング → ハーネス + 創設 Guild エージェント + standards + ⑥ ベースライン + 準備度監査 → guild:harness Issue（一度きり）
/gld dev 123         # GitHub Issue #123 をエンドツーエンド開発（feature/bug/refactor 自動選択）
/gld status 123      # 進捗確認   ·   /gld resume 123 で継続
/gld audit           # ハーネス+チーム+コードベースの読み取り専用ヘルスチェック
/gld evolve --dry-run  # Guild の成長提案（変更なし）
```

## コマンド

**セットアップ** — `init [lang]`（一度きりのオンボーディング、ハーネス構築 + 準備度監査）· `onboard [area]`（人間のメンテナーのためのガイド付きコードベースツアー）· `config`（ダイヤル・オフスイッチ）· `update [--check]`（中央の改善を採用、ローカル進化を保存）

**開発**（背骨：analyze → design → execute → test → qa — `execute` は PR を開く前に開発者の diff に対して読み取り専用の**外部監査者**を常時実行します。`BLOCKER` はループバックされ、修正は `test`/`qa` で再検証されます。`review` は同じ監査者をフローの**外**で再実行し、内側の監査者が実際に機能しているかを測る独立した計測器として働きます）— `plan <doc|epic-issue> [--create]`（エピック/設計文書を依存順の Issue バックログに分解）· `dev <issue>`（フル、execute バリアント自動選択）· `analyze` · `design` · `implement`（機能）· `debug`（バグ：再現→根本原因→修正）· `refactor`（振る舞い保存）· `test` · `qa` · `review <issue|PR>`（ガイド付きペアレビュー + 敵対的プリスキャン、Issue 番号だけでなく PR 番号も直接指定可）· `resume` · `status` · `batch [issues]`（無人、レート制限自動再開）

**診断・成長** — `audit`（読み取り専用、evolve/refactor へルーティング）· `evolve [--dry-run|--apply]`（スキャン → 敵対的パネル → 項目別承認 → バックアップ/ロールバック/provenance/台帳で適用）· `contribute`（フロー改善をアップストリーム）

**オンデマンド・観察** — `rollback <target>`（非破壊アンドゥ）· `ask <question>`（standards+⑥ に基づく引用付き Q&A）· `monitoring [--html]`（状態スナップショット）

**イテレーション** — `sprint plan`（今回のスプリントに入れる Issue の選別 + 依存順序 + 追跡 Issue 作成）· `sprint run`（依存順に無人開発 → **PR スタック**、Issue ごとの git worktree 隔離、レート制限は自動待機・再開 — その間に人間がレビュー・マージ）· `sprint daily`（何をどの順にマージするか · 人間待ち · 失敗）· `sprint board`（スプリントを GitHub Projects のカンバンに映す — `Issues → Backlog → Ready → In progress → Blocked → In review → Done` — 設定は最初の一度だけ、以降は `plan`・`run` が自動更新）· `sprint retro`（指標 → キャパシティ較正 → evolve → スプリントのクローズ）

## 安全性（不変条件）

Guild は自己修正システムなので、安全性は助言ではなく決定的です：

- **INV1 — 適用は常に人間の承認が必要。** トリガーは自動、変更は無人適用されない（evolve 適用・HR・全ゲートは項目別に人間ゲート）。
- **INV2 — 検証を弱めない。** テスト/ゲートを削除・弱体化する変更はハードブロック（コミットゲート + evolve 検証）。
- **INV3 — すべて可逆**（git · `/gld rollback` · evolve 検証失敗時の自動ロールバック）。
- **INV4 — 加算的、ローカル進化を上書きしない**（エージェント・知識・standards・overlay）。
- **INV5 — サニタイズなしにマシン外へ出ない**（`contribute` はサニタイズ + 重複検査 + 人間レビュー後に送信）。
- **INV6 — draft→confirm→enforce。** 自動生成されたゲートルール（例：構造/境界ルール）は `status: draft`（WARN のみ）で始まり、人間が確認（`status: confirmed`）して初めてブロックへ昇格します。シークレット・検証ゲートの2つは幻覚の余地がない普遍的ルールなので、`init` は最初から confirmed 状態でインストールします。
- **オフスイッチ** — `/gld config` で自動化・ゲートブロックを一時停止。

**決定的コミットゲート**がシークレットのコミットや検証の弱体化をブロックします。`.git/hooks/pre-commit`
（権威ある層 — git がインデックス確定後に実行するため、1行の複合「作成＋コミット」コマンドも捕捉）と、
エージェントがターンを浪費する前に具体的な理由を返す `PreToolUse` の早期警告層に二重配線されています。

**限界も正直に示します** — 実態より大きく語るゲートは本当の隙間を隠すからです。
`git commit --no-verify` は他のすべての git フックと同様、このゲートも飛ばします。`.git/hooks/` は
追跡されないため、新しいクローンでは `/gld update` での再インストールが必要です。リポジトリが
`core.hooksPath` を設定している場合はそもそも発火しません。既に書かれた履歴は検査しません。ゲート自身の
オフスイッチやルールファイルを編集しようとすると、ブロックではなく人間の確認を求めます — ゲートを切るのは
正当な行為ですが、副作用として起きてはならないからです。このゲートは間違いのコストを上げる仕組みであり、
本気の回避を防ぐ境界ではありません。

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
