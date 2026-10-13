# Herald Plugin

Claude Code のための**リポジトリ専用の編集組織**。Herald はリポジトリに執筆ハーネスを導入し、
そのリポジトリに特化した役割エージェントのチームがトピックを企画し、
`brief → research → draft → critique → verify → publish` の流れで専門的なブログ記事を書き、
PR レビューを経て公開し、実際の利用の痕跡からガイドを育てます。

> 姉妹プラグイン [Guild](../guild-plugin)(ソフトウェア開発)と同じ構造 — ハーネス、役割の骨格、
> 産出する内側ループと成長する外側ループ — を執筆に適用したものです。

[English](./README.md) · [한국어](./README.ko.md)

## コンセプト

- **目的** — サービス・アプリの宣伝。最終指標は CTA クリック・流入で、検索露出は手段です。
- **正確性は床** — Herald の公開経路では `verify` を通過していない本文を公開しません(人が修正した
  本文を含む)。床の上では 検索露出 > 読者価値。
- **骨格の役割** — 編集長(メインセッション)、コンテンツ企画、リサーチャー、ライター、
  ファクトチェッカー、編集者。**条件付き** — 分野専門家・監修者、検索・発見担当(SEO・AEO・GEO)、
  イラスト、翻訳、配信・SNS。
- **外部監査者** — 組織の外にいるペルソナなしのレビュアーが、編集者の PASS の後(記事ごとに最大 3 ラウンド、2 ラウンド目からは
  BLOCKER・未修正の指摘・回帰だけを止め、残りは PR へ)、また流れの外
  (`/hrd review`)でも確認します。
- **公開 = `/hrd ship`** — PR ごとの承認、人の修正の再検証、マージ、デプロイ、URL 確認、記録。
  書くだけでは何も公開されません。

## インストール

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install deku-claude-plugins@herald-plugin
```

必要環境: `git` 2.38 以上、認証済みの `gh`、`python3` 3.9 以上。batch は `claude` CLI。
Search Console(任意): `pip install google-auth requests`。

## クイックスタート

```bash
/hrd init            # リポジトリ分析 + インタビュー → ハーネス(コミット前に確認)
/hrd plan            # トピッククラスターをキューへ
/hrd write t0001     # 記事 1 本 → PR、PR まで質問なし
/hrd write t0001 --attended  # 同じ流れで各ゲートで確認し、PR の前に承認
/hrd ship            # PR 承認 → 再検証 → マージ → デプロイ → URL 確認 → 記録
/hrd next            # 記事 1 本を公開まで一度に(キューが空なら plan から)
/hrd batch --n 5     # 無人執筆。autonomy.publish=auto なら公開まで
/hrd status          # トピック・保留・メンテナンスフラグ
```

## コマンド

**設定** `init` · `config` · `update` — **執筆** `plan` · `write` · `brief` · `research` ·
`draft` · `critique` · `verify` · `publish` · `resume` · `batch` — **公開** `next` · `ship` · `review` ·
`refresh` — **状態** `status`(`--requeue` `--drop` `--withdraw` `--unwithdraw` `--move`
`--release-slug` `--mark-published` `--unlock`) — **成長・点検** `evolve` · `rollback` · `audit` ·
`monitoring` · `ask` · `contribute`(未対応)。詳しくは `/hrd help`。

## 安全

- **INV1** 変更の適用は常に人の承認。無人実行は approve モードでマージせず、監査者の BLOCKER を
  却下しません。**INV2** 検証を弱めない(基準・ゲート・模範記事・床)。**INV3** すべて可逆
  (git、`/hrd rollback`)。**INV4** 追加的で、ローカルの進化を上書きしない。**INV5** サニタイズ
  なしにマシンの外へ出さない。**INV6** 抽出したルールは draft から始まる。
- **PreToolUse ガード**(`.claude/herald/scripts/guard.py`)が基準ファイル・批評/検証ペルソナ・
  保護設定キー・検証台帳の編集、マージ、デプロイ、範囲外コミットについて、人に確認(対話)または
  ブロック(無人)します。トリップワイヤであって境界ではなく、`/hrd audit` が事後に点検します。
- **検証台帳**(ローカル)と**デプロイ前の整合性チェック**が、デプロイ前に base のすべての Herald
  記事を検証済みの内容と照合します。

## 状態

`0.8.0` — 全フロー実装済み(実装の敵対的レビュー 10 ラウンド + 以降の変更ごとのレビューを反映)。0.3.0 で成長シグナルをコードが自動記録、0.4.0 で外部監査ラウンドの上限、0.5.0 で `write` の既定を質問なしに(`--attended` で確認モード)・設定言語で対話、0.6.0 で `/hrd next`(必要なら plan → write → ship を 1 本)と、根拠のない文が少ないときに保留せず削除で整える段階を追加、0.7.0 で読みやすさを基準に追加(人が書いたような平易な文章の規則・経験の捏造禁止、編集者の読者パス、ゲートの読みやすさヒント、ファクトチェッカーが「記事自身の例」と扱った文は一覧に残し、同意なしでは自動公開しない)、0.7.1 で `/hrd evolve` の各承認にレビューパネルの推奨(適用/却下と理由)を表示、0.8.0 でファクトチェッカーが調査資料そのものの誤りを見つけたら writer ではなく researcher に先に戻し、ループバックの上限を使い切っても事実の誤りには 1 回を残す(文章の手直しで事実の誤りを直せなくなることがない) — 既存リポジトリでは `/hrd update` が必要、その後進行中の記事の `/hrd resume` は base のマージを確認(0.4.0 より前から進行中の記事は監査ラウンドを 1 から数え直す)、決定的な層はテストで検証(`bash plugins/herald-plugin/tests/run_tests.sh`)。
`evolve` の有用性と指標に基づく提案は、実利用が蓄積してから判定できます。
