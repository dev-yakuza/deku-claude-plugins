# Studio プラグイン

Claude Code 向けの**リポジトリごとの動画制作組織**です。Studio はリポジトリに制作ハーネスを
インストールし、そのリポジトリに特化した役割エージェントのチームが、リポジトリにすでにある文章
(ブログ・ドキュメント・アプリ紹介ページ)を [script2video](https://github.com/dev-yakuza/script2video)
でナレーション動画にし、選んだプラットフォームに一緒に載せる文章の下書きを作ります。

[English](./README.md) · [한국어](./README.ko.md)

## コンセプト

- **原本はすでにある文章です。** 動画のすべての事実(ナレーション・画面の文字・タイトル・
  サムネイル・チャプター・配布用テキスト)は原本から取り、原本と照合します。
- **人によるレビュー 4 段階** — ① 台本 ② オーディション ③ 静止画 ④ 最終(④a 動画・④b 配布用テキスト)。
  エージェントが人の代わりに承認することはありません。
- **生成のみで公開はしません** — アップロードするのは人です。
- **レンダリングは script2video が担当** — Studio は計画・検査・質問・コミットを担当します。

## 必要なもの

- **Claude Code**: Claude Code 2.1.304、2.1.308、2.1.311 でテストしました(2.1.304 未満か 2.1.311 超では `/std init` が警告)。
- **git**、そしてフックが見る `PATH` に **python3** 3.9 以上。
- **script2video** 0.13.0 以上とその要件(Node 22+、Yarn 4、uv、ffmpeg、`yarn build`、モデル):
  [script2video の README](https://github.com/dev-yakuza/script2video#readme) を見てください。
- **ガードはすべての呼び出しで動きます。** Studio を有効にしたプロジェクトのすべてのセッションで(`/std init` の前も)、
  Studio のガードフックが Bash、Write、Edit、MultiEdit、NotebookEdit、WebFetch、WebSearch、MCP ツールの呼び出しを
  一つずつ検査します。`onFailure: block` で動くため、フックのエラーやタイムアウトはその呼び出しを止め(測定済み)、
  `python3` がないときも止めると見込んでいます(測定していません)。`python3` が pyenv や asdf 方式の shim だと、ガードの
  呼び出しごとに遅くなり、0.0.28 のガード自身の許可がオフになります([docs/guard-limits.ja.md](docs/guard-limits.ja.md))。
  Command Line Tools のない macOS では、`/usr/bin/python3` がフックの 20 秒のタイムアウトまで待つことがあります。
- **呼び出しごとのコスト**(マシン 1 台、Apple silicon の Mac): ハーネスのないリポジトリでの Bash `git status` に対するガードは
  約 80 ms(p50、Python 3.9.9 と 3.15.2)、macOS の `/usr/bin/python3` 3.9.6 では約 155 ms でした
  (`tests/py/test_guard_entry.py`、`PerfNoHarness`)。ガードは Claude Code のシェルスナップショット(最近のセッションごとに
  一つ、各 ~280 KB)も読みます。13 個あるとき同じ呼び出しは約 140 ms(3.15.2)、約 170 ms(3.9.9)で、ファイルが一つ
  増えるごとに約 5 ms 増えます(`PerfSnapshots`)。

## インストール

Claude Code で:

```text
/plugin marketplace add dev-yakuza/deku-claude-plugins
/plugin install studio-plugin@deku-claude-plugins --scope project
```

Claude Code のドキュメントによると、project スコープはプロジェクトの `.claude/settings.json`(コミットされる
ファイル)の `enabledPlugins` に `"studio-plugin@deku-claude-plugins": true` を書きます。リポジトリで作業するすべての人に Studio とそのガードが有効に
なります。このリポジトリで自分だけに有効にするには `--scope local`(`.claude/settings.local.json`、コミットしません)を
使います。

このリポジトリのチェックアウトから: `claude --plugin-dir plugins/studio-plugin`。

## 最初の実行

1. リポジトリの最上位フォルダーで Claude Code を起動します。
2. `/std init` — このマシンの script2video のチェックアウトを尋ね、リポジトリを読み、いくつか質問して計画を見せます。
   確認すると、それが最初のハーネスコミットです。
3. `/std make <source> --kind <kind>` — 一つの文章から一本の動画(`/std help` がコマンドを示します)。
4. レビュー ① 台本 ② オーディション ③ 静止画 ④ 最終(④a 動画・④b 配布用テキスト)、その後に動画のコミット。

承認の質問: 示された選択肢から一つを選びます。AskUserQuestion の許可ルールを追加せず、Studio を bypass の権限モードで
動かさないでください。

## 新しい clone やワークツリー

ハーネスはコミットされていますが、このマシンの s2v のパスと pre-commit フックはそうではありません。新しい clone や
ワークツリーで一度だけ:

```text
/std config s2v.path <このマシンの script2video のチェックアウトの絶対パス>
```

そしてターミナルで、その最上位フォルダーから:

```bash
python3 .claude/studio/scripts/hooks.py install
```

どちらかが欠けていれば `/std status` が知らせます。

## Studio を外す

正確なコマンドつきの手順(まず動画とバックアップを残す、すべてのワークツリー、フック、リポジトリの外のフォルダー):
[docs/removing.ja.md](docs/removing.ja.md)。

## 補足

- **s2v のパスはマシンごと**です。`.claude/studio/local/machine.json`(コミットしません)に clone・ワークツリーごとに
  一度だけ設定し、`config.json` には s2v の最低バージョンだけが残ります。
- **承認の回答はリポジトリ全体で一度だけ**使えます。同じリポジトリのワークツリーはその記録を共有しますが、別に取得した
  clone(別の `git clone`)は共有しません。動画の回答はその動画とハッシュを含むので別の clone に当てはまることはまれで、
  動画を持たない回答(設定・更新)だけが残るケースです。0.0.9 以前がワークツリーごとに残した記録は無視されます。

## バージョンノート

- **初期のサンドボックス(スクリプト 8 以下)を手で移行する**: `.claude/studio/config.json` の `"s2v"` の
  `"path"` を削除し、`.claude/studio/local/machine.json`(リンクではない実際のフォルダ)に
  `{"schema": 1, "s2v": {"path": "<絶対パス>"}}` を書きます。
- **0.0.23 へ上げるとき**: `/std update` が Studio の ignore ブロック(`.gitignore` と `info/exclude`)を書き直し、
  出典の下書きと音声フォルダが未追跡ファイルとして表示されなくなります。`.gitignore` の変更は更新後のハーネスコミットで
  一緒にコミットします。
- **Studio のドキュメントは開かずに出力します(0.0.24)。** `/std` はコマンドのドキュメントを
  `python3 "<plugin>/skills/std/scripts/setup.py" doc <name>` で読みます。このコマンドは Studio 自身のドキュメントを
  一つ出力するだけです(読み取り専用で、設定には何も追加しません)。プラグインのフォルダは作業ディレクトリの外にあるため、
  Read で開くとファイルごとに確認を求められます。スキルは `/std` を始めたターンだけこのコマンドを事前に許可し、その後は
  Studio のガードがまさにその呼び出し(Bash 呼び出しにそれ一つだけ、プラグイン自身の `setup.py`、既知のドキュメント名)
  だけを、プラグインが有効なすべてのセッション(どのリポジトリでも、サブエージェントも)で許可します。利用者の deny・ask
  ルールはそのまま適用されます。実行フォルダのリポジトリがプラグイン自体や、そのリポジトリの Python(リポジトリ内の仮想環境)
  を含むときは許可しません。対象外(残るリスク): conda 環境、リポジトリ外や追加の作業ディレクトリにある仮想環境、追加の
  作業ディレクトリにあるプラグインのチェックアウト。`blockReadsOutsideWorkingDirectories` はファイルツールだけを制限し
  プロセスは制限しないため、`doc` は止まりません。それでもエージェントが Read でプラグインのファイルを開くと、通常どおり
  確認を求められます(Read にはフックがありません)。
- **`/std init` が値を提案します(0.0.24)。** サイトのドメイン(CNAME ファイル、サイトの設定)、ブランドカラー最大三つ
  (theme-color、brand/primary/accent のプロパティ、次にサイト自身のスタイルで最も多く使われた色 — 外部ライブラリのビルドと
  圧縮ファイルは除外)、ロゴファイル最大三つを、見つけた場所とともに示します。追跡されているファイルだけを読み、`.env*` は
  読みません。何も見つからないときは Studio の既定値(`#2563EB`、ロゴなし、ドメインなし)を使い、要約で伝えます。どの質問
  にも自分で答えを入力できます。
- **0.0.25(パイロット 2)。** ソースアナリストはすべての主張に仮の id `C-00000000` を書き、`check_claims.py <video>
  --source --fill` が本当の id を書き込みます(`--source` だけなら一覧のみ)。`check_claims.py <video> --skeleton` は
  判定する項目をすべて含む verify の下書きを書き、ファクトチェッカーはそれを Edit で埋めます。もう一度実行しても埋めた
  内容は残ります。脚本ライターとビジュアルディレクターは `setup.py doc s2v-syntax` で s2v の脚本の文法を読みます(この
  ワークツリーの s2v の中にある 25,000 文字以下の通常ファイル)。承認コマンドは、人の回答の直後に同じターンの次のツール
  呼び出しとして実行します — 質問と同じアシスタントメッセージには決して入れません。「This is not a stop」と述べる拒否は
  止まらずにそのとおりにします: Read で読み、Write か Edit で書きます。役割エージェントはファイル作業をすべてこの方法で
  行います。ガードは `sed` をスクリプトとオプションの形で判定するようになりました: 単純な出力・削除・置換は通り(`-i ''` か `-i.bak` によるその場
  編集もそのファイルへの書き込みとして判定)、判定できないスクリプトやオプションは Studio のリポジトリ内で拒否します。
  `state.py shown <video> 2` は `read:` 行で `audition.md` を示します。
- **0.0.25 へ上げるとき**: `/std update` を実行し、変更された役割エージェントのファイルごとに「new」を選びます — すべての
  `std-*` エージェント(Read/Write の規則とガード規則の例外)、そのうち `std-writer` と `std-visual-director`(s2v 文法の
  コマンド)、`std-fact-checker`(スケルトン、つなぎ文の上限、リスト項目と抜けた条件)、`std-source-analyst`(仮の id)。
- **0.0.26(パイロット 2、見た目と init)。** ビジュアルディレクターがブランドを適用します: `check_assets.py <video> --look
  --output <o>` が brand.json の求めるフロントマターの行 — `theme.accent`、ブランドロゴ(`logo.src`)、レイアウト(すべて
  の話者にキャラクター画像がなければ `fullscreen`。s2v の既定 `presenter` は画像なしでは誰も描かない) — を出力し、
  台本にそれがなければボードのチェックが失敗します。ボードはフロントマターの `theme`・`logo`・`outputs.<o>.layout`・
  `transition` も変えられるようになりました(ブロックはそのまま)。ブランドロゴはクレジットの要る画像です(floor
  `public/brand.json logo (committed in the harness)`)。brand.json とロゴはコミット済みである必要があります:
  コミットされていないものはボードのチェックが拒否し、ハーネスコミットはコミットされていないロゴを警告します。ロゴは
  PNG か JPEG です。台本の段階では、シーン 1 がタイトルシーンで(`::title[<フロントマターの title>]` が唯一の
  ビジュアル — サムネイルにタイトルが入る。台本に `::thumbnail{src=…}` があれば省略)、記事の使える画像はすべて
  見せるか、クレームマップの `unused_images` に一行の理由を書き(① で `unused:` 行として出力)、ライターはレイアウトを
  書きません。`/std init` はナレーターを必ず尋ね(その言語のネイティブ話者を先に、なまりがあり得ると示した他の話者を
  二人まで — ② の発音チェックで失敗することがある)、記事が使う画像フォルダーを `visibility.public` の候補に出し、
  サイトのタイトル・Web マニフェスト・package.json・origin リモートのリポジトリ名(URL は出力しない)からプロジェクト
  名の候補を出し、コミットされていないロゴを拒否します(ロゴなしを選ぶか先にコミット)。
- **0.0.26 へ上げるとき**: `/std update` を実行し、`std-visual-director`、`std-writer`、`guides/board.md`、
  `guides/script.md` で「new」を選びます(ガイドに自分の変更があれば update が差分を示します)。brand.json とロゴが
  コミット済みで、ロゴが PNG か JPEG であることを確かめます(そうでなければ `""`)。記事の画像フォルダーが
  `visibility.public` になければ `/std config` で入れます。すでにボードを過ぎた動画は、レンダーの前にまず
  `/std board <video>` を実行します: そうしないと動画のコミットでボードのチェックの見た目の規則が失敗してボードに戻り、
  ③、④a のレンダー、④a をやり直すことになります。進行中の動画はソースの段階をやり直す必要はありません。
- **0.0.27(G1: ガードがより多くを読む)。** ガードは、展開して読む一般的な実行ツール(env・nohup・nice・timeout・
  time・script・flock・xargs・npx など)のオプションを読み、そのファイル引数を判定します。Studio のリポジトリでは、
  読めない実行ツールとオプション、ガードが知っているコマンド値のオプションと変数(`git -c core.editor` など)、
  ガードが知っているすべての経路でコマンドを実行する git の設定、パースできない zsh の形式を拒否します。グロブの
  グループ `(…)` を含むファイル名の単語がその例です(Bash ツールは zsh を `BARE_GLOB_QUAL` を無効にして実行するため、`studi(o)` が
  `studio` に一致する)。ユーザーのシェル関数やコマンドが定義した関数の後、そしてフック(`chpwd`、`TRAP*`)の後では、
  ガードが追えないものを不明として扱います。そのため git、削除、引用符のない `$X` が拒否されることがあります。すべての
  呼び出しは 0.0.26 のガードでも検査します: 0.0.26 が拒否したものは引き続き拒否し、その誤った拒否もそのままです
  (`rm -rf **/__pycache__` など)。`source` や `.` の後(そしてガードが読めないテキストの `eval` の後)の残りは、0.0.26
  の規則だけで判定します。そこでのより強い検査は 0.0.28 で行う予定です。Studio リポジトリでコマンドが削除または書き込む
  `~[name]` のパスは拒否します。Studio
  のリポジトリ外では、ガードの上限を超える長いコマンドは、リポジトリを指しうるものが一つもないときだけ通します。
  詳細: [docs/guard-limits.ja.md](docs/guard-limits.ja.md)。ガードはプラグインの一部なので `/std update` は不要です。
- **ガードがまだ見ないもの(0.0.27)。** 全体の一覧は [docs/guard-limits.ja.md](docs/guard-limits.ja.md) にあります。
  要約すると:
  - ガードがモデル化しない方法でコマンドを実行するプログラムと設定(awk のプログラム、`NODE_OPTIONS` など)。
  - ガードが読めない値(そうした値を通した削除: `rm -rf $X`、`f() { rm -rf $1; }; f studio` など)。
  - Studio のリポジトリ外で使う形式(リポジトリを指すインタプリタのコード `python3 -c`、既定値にだけ書いたフォルダ
    `cd ${U:-<リポジトリ>}` など)。
  - その他(`chmod 000 studio`、保護ファイルの上に書くアーカイブなど)。

  これらの場合も、pre-commit フック、コミットの検査、人のゲートが後ろに残ります。
- **0.0.28(パイロット 3)。** `state.py next <video> --enter script` が、ライターがそのまま写す frontmatter の行を出力
  します: 既定のナレーターの `cast:` ブロック(s2v のコンテンツハッシュに入るので最初から台本にあり、キャストの段階では
  もう編集しない)、出力ごとの `aspect` と `maxDuration`、`targetDuration` の範囲(ceil(min ÷ 0.85) から
  floor(max ÷ 1.15) まで: youtube は 212–417 で、s2v lint を通った台本はフォーマットの長さに収まる)。
  `check_claims --narration` は cast ブロックを検査し、s2v の失敗メッセージをすべて出力します。クレームマップは
  クレームを述べる台本のすべてのテキスト(画面のテキストとタイトルも)を挙げ、検証のメッセージはそのテキストと場所を
  示します。`check_claims --source` は、コピーにない抜粋、タグの中や文の途中で切れた抜粋を拒否します。
  `record-brief --from` はリポジトリのルートからのパスも受け付けます(動画フォルダーの中だけ)。② の質問には
  オーディションが再生する文と `read:` の行が入り、`shown 3` と `shown 4a` も質問ブロックを出力します(④a は音・字幕・
  絵が合っているかの確認を求める)。`assets.json` は CREDITS 用の `floor_text` を持ちます。
  `record-source --url <https://<公開ドメイン>/…>` が記事のアドレスを記録し、配信用テキストの説明には `원문: <url>`
  (動画の言語のラベル)が必要です。ハーネスのコミットの値ブロックに brand.json の名前・色・ロゴが出ます。
  `begin --ask-before tts,render`(と `state.py ask-before`)が、人が止まって聞くように頼んだ段階を記録します。すべての
  コマンド文書の Rules の行は、コマンドをそのまま実行し、繰り返さず、`open` だけを使うよう求めます。
- **確認の削減(0.0.28)。** `default` の権限モードで、ガードは Studio 自身のスクリプト呼び出し(リポジトリのコピーが
  変更されず完全で、リテラルの引数で単独に実行)と、各ロールが自分の出力ファイルに書くことを、すべての条件が満たされる
  とき確認なしで許可します。一つでも満たされなければ通常どおり確認します。`run_s2v.py`、`lock.py`、`check_commit.py`、
  `state.py ask-before` は引き続き確認します。Claude はリポジトリのフォルダーで起動してください。条件と限界:
  [docs/guard-limits.ja.md](docs/guard-limits.ja.md)。
- **0.0.28 へ上げるとき**: `/std update` を実行し(スクリプトのバージョン 25)、`std-writer`、`std-source-analyst`、
  `std-visual-director`、`std-distributor`、`guides/script.md`、`formats/youtube.md`(新しい `source_label`)で「new」を
  選びます。`"` や `\` を含むナレーターのスタイルは `/std config` のナレーターで拒否されるので、そこで変えます。まだ台本の
  段階にある動画は台本に cast ブロックが必要です(台本の検査が知らせる)。ブロックなしで ① を承認した動画は台本の段階へ
  戻ります(`/std script <video>` の後、検証と ① をもう一度)。キャストを過ぎた動画はすでにあるブロックを使います。
- **0.1.0**: マーケットプレイスへの登録。0.0.28 から上げるときは `/std update` は不要です(スクリプトの
  バージョンは 25 のまま)。
- **0.1.1**: ガードがシェルスナップショットを約半分の時間で読みます。スナップショット 13 個で、呼び出しごとの全体の時間が
  約 3 分の 1 減りました(このマシンで Python 3.15.2 は 210 → 140 ms、3.9.9 は 300 → 170 ms。判定は同じ)。メッセージと
  テンプレートに内部のマイルストーン名が出なくなりました。pre-commit の shim の案内は `hooks.py install` だけを示します。
  いくつかの環境変数と pyenv の PATH でもガード自身の許可がオフになります — シェルにグローバルな `PYTHONPYCACHEPREFIX`
  や `GIT_CEILING_DIRECTORIES` があると、Studio のスクリプト呼び出しはまた確認を求めます。この検査はシェルスナップショットの
  どこにある `NAME=` にも(関数の本体も含めて)かかります。
- **0.1.1 へ上げるとき**: `/std update` を実行します(スクリプトのバージョン 26)。`platforms/youtube.md` の `checked` を
  埋めてあれば「local」を選びます。日付はそのまま残り、古い文は内部のマイルストーン名を示していただけです(「new」は
  `checked` を空にし、埋め直すまで `validate_copy.py` がすべてのコピーを拒否します)。編集した `formats/youtube.md` も
  「local」を選びます。そのほかの変わったテンプレートはリポジトリにインストールされないプラグインのファイルです(作業は
  ありません)。0.1.0 が書いたクローンの pre-commit の shim はそのまま有効で、`hooks.py install` が新しい内容を書きます。

## ライセンス

MIT
