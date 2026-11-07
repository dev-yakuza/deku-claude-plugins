# Studio ガード: 判定するものと見ないもの(0.0.27)

README には要約があり、このファイルには詳細があります。ここに挙げたすべての場合も、pre-commit フック、コミットの検査、
人のゲートが後ろに残ります。

## 0.0.26 のガードをバックストップに

- すべての呼び出しは、プラグインの中に変えずに置いた 0.0.26 のガードでも判定します。どちらかのガードが拒否すれば
  拒否します。0.0.26 のガードだけが拒否したときは、そのメッセージは 0.0.26 で出したものと同じです。
- そのため 0.0.27 は 0.0.26 が拒否したものをすべて拒否し、その誤った拒否もそのままです:
  - Studio リポジトリで `**` で削除または書き込むもの(`rm -rf **/__pycache__`、`rm -f **/*.pyc`);
  - とても多くのファイルを一度に読むもの。0.0.26 のガードの内部エラー(G-ERR)になることがあります;
  - 内容が studio に触れているか 0.0.26 が読めなかったユーザーのシェル関数の後の git や `open`
    (`gh pr view 1; git commit -m 'studio: v script'`、`diff a.txt src/a.ts; git status`);
  - シェルのスナップショットがないときの、`PATH` にないコマンド(`flock /tmp/build.lock make`)。
- これらは 0.0.28 で、source の後のより強い検査とともに、種類ごとに外す予定です。
- `git push` と Studio のコミットの検査は、二つのガードで一度だけ実行します。二つのガードが使える時間より長くかかる
  呼び出しは、フックの 20 秒の上限よりずっと前に拒否します(G-LIMIT)。フックが時間切れになると、メッセージなしで
  止められるためです。

## 関数・フック・オプションの判定

- **ユーザーのシェル関数**(シェルのスナップショットから来るもの):
  - export する、git やガードが読む変数(`PATH`、`HOME`、`GIT_*`、すでに export された名前)を設定する、ファイルを
    source する、または eval しうる関数の後では git を拒否します。例: `nvm` や `pyenv` のラッパー。
  - フォルダを変えうる関数(`cd`、`pushd`)の後では、コミット、`git config`、変更を捨てる git の形式、`open` を
    拒否します。ガードが追えないフォルダ移動(`cd -1`、`cd $(mktemp -d)`)の後も同じです。
  - `gh`・`diff`・プロンプトの補助関数のようなラッパーは該当しません(`gh pr create --fill && git push` は通過)。
    0.0.26 のガードが拒否する場合は別です(上のバックストップ)。
- **ユーザーのフック関数。** フォルダを変えうる `chpwd` や `TRAP*` 関数があると、その後のすべてのコマンドでフォルダを
  不明として扱います。export する、またはガードが読めない関数を呼ぶものなら、どの `cd` の後でも git を拒否します
  (`cd src && git status`)。`TRAPEXIT` と、ガードが読めないシグナルトラップ(`TRAPWINCH(){ zle && zle -R }`)は、
  コマンドの間では実行されないものとみなします。ガードが読めない `TRAPDEBUG`、`TRAPZERR`、
  `command_not_found_handler` はフォルダを不明にします。
- **コマンドが定義した関数。**
  - 関数を定義すると、ユーザーのスナップショット関数の効果を不明として扱います。`eval`・`source`・`autoload`・
    `functions[…]` で定義しうる場合と、ユーザーの autoload スタブ(`# undefined`)も同じです。
  - コマンドが自分で定義した関数を呼ぶと、本体が export・代入するものを、ガードが追わない値として適用します。
    `y(){ export GIT_DIR=/tmp/x; }; y; git commit -m x` は `export GIT_DIR=…; git commit -m x` と同じように判定します。
  - 関数を呼ぶと、その本体を呼んだところで改めて判定します: そのフォルダで、そのときの値と前置きの代入で
    (`f(){ rm -rf studio }; cd <リポジトリ>; f`、`f(){ rm -rf $X }; X=studio; f`)。
  - `function a b { … }` はすべての名前を定義します。
  - 別の関数の本体の中で定義した関数は、その関数を呼んだ後から存在します(`f(){ k(){ cd studio } }; f; k`)。
    `functions -c` は、コマンドが定義した関数を効果ごとコピーします。それ以外のコピーは zsh の関数テーブルへの
    書き込みなので、Studio のリポジトリで拒否します(`functions -c nvm k`)。
  - コマンドが削除した関数(`unfunction f`、`unhash -f f`、`unset -f -- f`、`disable -f f`、`-m` のパターン)は、
    その後の呼び出しでは存在しません。その名前は同じ名前のコマンドを実行します
    (`git(){ :; }; unfunction git; git clean -fdx` は `git clean -fdx` と同じように判定)。削除されたかどうか
    分からない関数(`[[ -e x ]] && unfunction f`)は両方の場合を判定します。ガードが追わない方法で関数を削除・置換
    しうるコード — `eval` や `emulate … -c` の文字列、source したファイル、ガードが読めない名前での定義
    (`$n(){ … }`)、ガードが読めない関数や `DEBUG`/`ZERR` フック、ガードが読めないコマンドの単語 — の後の呼び出しは、
    こうした関数を追う前と同じように判定します: フォルダと呼び出しが書きうる値は不明とし、同じ名前のコマンドも
    判定します(`f(){ cd /tmp; }; eval 'f(){ :; }'; f; rm -rf studio` は拒否)。
- **コマンドが定義したフック。** `chpwd`、`TRAPDEBUG`、`TRAPZERR`、`TRAP<signal>` 関数、
  `command_not_found_handler`、`trap … DEBUG`、`trap … ZERR`、シグナルに設定したトラップ(`trap … INT TERM`)、
  `chpwd_functions=(…)` は後のコマンドの間で実行されることがあります。フックがしうることはその後ずっと適用します:
  フォルダを変えうるとき、またはガードが読めないときはフォルダを不明とし、代入しうる値は前の値か新しい値のどちらか
  とします。コマンドが定義した関数を名前で呼ぶトラップの動作は、その関数として読みます
  (`cleanup(){ rm -f $tmp; }; trap cleanup INT TERM` は何も変えません)。コマンドが後でその関数を定義し直しても同じ
  です。関数の外で設定した `trap … EXIT`(または `0`)と `TRAPEXIT` はシェルが終わるとき、つまり呼び出しのすべての
  コマンドの後に実行されるので、後のコマンドはフォルダと値をそのまま保ちます(`trap 'cd /' EXIT; rm -rf $PWD/studio`
  は拒否、`cleanup(){ rm -f $tmp; }; trap cleanup EXIT; git commit -m x` は通過)。関数の中で設定した EXIT トラップは
  関数が戻るときに実行されるので、フックとして扱います。`precmd`、`preexec`、`periodic`、`zshaddhistory`、`zshexit`
  (とその `*_functions` 配列)は Bash ツールのコマンドの間では実行されません。動作のテキストはこれまでどおり検索
  します。
- **コマンドが source するファイル。** `source` や `.` の後の残りは、0.0.26 の規則だけで判定します(上のバックストップ)。
  そこでのより強い検査は 0.0.28 で行う予定です。
  - コマンドが定義したエイリアス、`builtin`・`command`・`noglob`、コマンドが定義して呼んだ関数、source を実行しうる
    `eval` や `emulate … -c` の文字列を通って source に至るときも同じです。ガードが内容を読めない `eval` の後も
    同じです(`eval "$(pyenv init -)"`)。
  - source の前のコードはいつもどおり判定し、呼び出し自体が source に与えたコードも判定します: その入力
    (`source /dev/stdin <<< …`、heredoc)や呼び出しが書いたファイル。`{ source /dev/stdin } <<< 'rm -rf studio/local'`
    は拒否します。
  - サブシェル、分岐、ループ、パイプラインの中の source も、呼び出しの残りに対するより強い検査を終わらせます:
    `if [[ -n $CI ]]; then source ci.sh; else rm -rf studio/local; fi` は 0.0.26 の規則で判定します(拒否)。
  - source するが呼ばない関数はこれを終わらせません。source する `chpwd` 関数やトラップも同じです: その本体は
    定義したところで読みます。
  - このガードはユーザーのファイルを読みません。0.0.26 のガードが以前と同じくその内容を検索します。
- **動的な名前付きディレクトリ。** zsh は `~[name]` を `zsh_directory_name` 関数や `zsh_directory_name_functions` で
  解決し、これはコマンド、source したファイル、`eval` が定義しえます。ガードはこれを実行しません。Studio リポジトリで
  コマンドが削除または書き込む `~[name]` のパスは拒否し、`cd ~[name]` はフォルダを不明にします。
- **`NULLCMD`/`READNULLCMD`** をページャ以外の値にすると、リダイレクトだけのコマンドが入力をシェルのコードとして
  実行します: here-string、ヒアドキュメント、`<` のファイル、またはそのコマンドが置かれたパイプ
  (`print … | > /dev/null`、`… | < /dev/stdin`)。
- **入力。** `{ … }`、`( … )`、ループ、`if`、コマンドが定義した関数に与えた here-string・ヒアドキュメント・`<` の
  ファイル・パイプは、その中のすべてのコマンドが読みます(`{ sh } <<< …`、`f <<< …`)。`exec <<< …` と `exec 3< f`
  は後のコマンドにも続き、`<&3` は fd 3 が持つものを読みます(`exec 3<<< …; sh <&3`)。ガードが分からない入力を読む
  シェル(知らない fd の `sh <&3`)は、Studio のリポジトリで拒否します。`eval` の文字列と `-c` の文字列は、その
  コマンドの入力で実行し(`eval sh <<< …`、`zsh -c sh <<< …`)、`eval` の文字列が定義した関数は、呼び出したときの
  入力で読みます(`eval 'f(){ sh }'; f <<< …`)。一つのコマンドに入力のリダイレクトが複数あるとき、またはパイプと
  一緒にあるときは、zsh の `MULTIOS` と同じくすべてを順に読みます(`sh <<< … <<< x`、`sh <<< … < /dev/null`、
  `echo … | sh <<< x`)。stdin の `<>` も入力として扱います(`sh <<< … <> /dev/null`)。
- **`set` のフラグとスナップショットのオプション。** `set` のフラグは 1 文字ずつ読みます(`set -euo pipefail`、
  `set -ex`、`set +eu`)。`-o NAME` はオプション名です。ガードが知らない文字(`set -r`)はオプションを不明にします。
  スナップショットの `setopt` 一覧にないオプションは zsh の既定値です(`AUTO_PUSHD` はオフ)。スナップショットがない
  ときは `AUTO_PUSHD` がオンかオフか分からないので、`cd` の後の `popd` を両方で判定します。
- **引用符のない `$X`**(`$X[1]`、`$X:t`、`$1`、`$@`、`$_` も):
  - `eval`、単語を変えるオプション(`GLOB_SUBST`、`SH_WORD_SPLIT` など)を `LOCAL_OPTIONS` なしで有効にしうる関数、
    またはガードが読めない関数の後では、コマンドがその値を自分で入れえたときに拒否します。つまり、コマンドがその値を
    どの名前ででも(`PS1`/`PROMPT`、`cdpath`/`CDPATH`、`typeset -T` の組、`$aliases[…]`)代入するか読んだ場合、
    ファイル名を回す場合、そうした関数にガードが読めない単語・変数名・stdin・コマンドが書いたファイルを渡した場合です。
  - 環境だけから来る値は、単語をどこにあっても同じ意味に読むプログラム(`ls`、`cat`、`grep`、`echo` など)では以前と
    同じように判定します。それ以外のプログラムでは、ガードが読めない関数の後の引用符のない値を拒否します。単語が
    分かれうるためです(`nvm use 20; cp $X /tmp/y`)。
  - `[[ ]]`、`case`、スカラーの代入、`${#X}` は以前と同じように判定します。配列の値(`W=($X)`、
    `typeset -a W=($X)`)はファイル名です。
  - `GLOB_SUBST` が有効でありうるときは、一つの単語の部分をまとめて検査します(`$X$Y`、`${X}'…'`)。`(` を含む値の
    隣にガードがテキストを計算できない部分があれば拒否します(`${X:&}`、`$X:s/…/'…'/`)。`0=…` と `1=…` は代入
    なので、`$0` もコマンドが設定した値として扱います。位置パラメータを一つでも設定すると(`2=…`、`argv[2]=…`、
    `set --`)、すべてを設定したものとして扱います(`$@`、`$*`、`$argv`、`shift` の後)。`$~1`、`$=1`、`$~@` は
    `${~1}` と同じパターン展開です。
  - `GLOB_SUBST` や `SH_WORD_SPLIT` がパターンや複数の単語に変えうる既知の値(`setopt globsubst`、`set -y`)は、
    全体としても単語ごとにも判定します。
- **ガードが一つの文字列として追わない値**: 配列(`X=(studio)`)、`read`、`print -v`、`set -A`、`$1` と組み合わせた
  `set --`、`$(print …)`、`for` の変数、コマンドが定義した関数が代入するグローバル変数、コマンドが実行されうる
  フォルダごとに異なる値。こうした値を削除や書き込みに使うところでは、値の元になったテキストの単語から、取りうる値を
  一つずつ判定します(`X=(studio); rm -rf -- $X` は拒否し、`files=(a b); rm -f $files` は通す)。コマンドが計算する
  値(`X=$(ls studio)`)は、そのコマンドの単語のうち Studio が保護するものを指す単語を値として判定します。
  コマンドが代入した既知のいくつかの値のどれかである単語(空の値や、空白・ワイルドカード・引用符・その他のシェル
  文字を含む値がなく、`$PWD` や `$OLDPWD` ではなく、`GLOB_SUBST` と `SH_WORD_SPLIT` が無効な場合)があると、
  コマンドを値ごとに一度ずつ、最大 16 通り、そう書いたものとして判定します
  (`if [[ -e x ]]; then B=develop; else B=main; fi; git checkout $B`、`cd $D` はそれぞれのフォルダに移ります)。
  それぞれの場合は順番ではなく、そのうちの一つです: ある場合の再帰コピーは別の場合の書き込みより前にはなりません
  (`if [[ -n $CI ]]; then OUT=dist; else OUT=build; fi; cp -r src/* $OUT/` は通過)。組み合わせが 16 通りを
  超えると、その単語はガードが読めない単語として判定し、Studio のリポジトリでそうした単語が 3 つを超えるコマンドは
  上限を示すメッセージとともに拒否します(値をそのまま書くか、コマンドを分けてください)。
  外部監査役(`std-auditor`)では、すべての場合が読むだけでなければなりません。配列の要素一つ(`$A[k]`)はその値の
  どれかです。文字列のスライスや添字、修飾子(`$X[2,-1]`、`${X:1}`、`$X:t`)は値の一部を与えるので、その候補を
  正確な値とは見なしません。
- **グロブのグループ。** Studio のリポジトリでは、zsh がファイル名に展開する単語にグロブのグループ `(…)` があれば
  拒否します(`ls *(.)`、`ls (a|b).txt`)。Bash ツールは zsh を `BARE_GLOB_QUAL` を無効にして実行するため、`*(.)` はグロブ修飾子ではなく
  パターンです(`studi(o)` が `studio` に一致する)。`[[ ]]` の `=~` の後の正規表現はグロブのグループではありません
  (`[[ $b =~ ^feature/(.*)$ ]]`)。`[[ ]]` の `==`・`=`・`!=` の後のパターンもファイル名を作らないため、グロブの
  グループとして扱わず(`[[ $x == (a|b) ]]`)、コマンドの残りは通常どおり判定します。`case` のパターンも同じで
  (`case $f in *.(ts|tsx)) …`、`case $x in (#i)y) …`)、各分岐のコマンドは判定します。`;&` や `;|` の後の分岐は、
  前の分岐がシェルを残したフォルダで実行されることがあります。
- **zsh の短い形式**(`for i in x; cmd`、`for ((…)) cmd`、`while … { … }`、`if … { … }`、`case x { … }`)は、
  Studio のリポジトリで拒否します。`do … done`、`then … fi`、`in … esac` で書いてください。ガードがパースできない
  条件やループの先頭も同じく拒否します。
- **拡張グロブ。** `EXTENDED_GLOB` が有効でありうるときは、`^`・`~`・`#` を zsh と同じように読みます(名前の末尾の
  `~` は文字)。保護名に一致しうる単語だけを拒否します: `setopt extendedglob; cd $D; rm -rf ^x` は拒否し、
  `touch notes#1`、`cp a.txt a.txt~`、`rm -f *~` は通します。角かっこの式の中ではこれらと `/` は文字で、
  `!`/`^`、先頭の `]`、範囲、`[:class:]` は zsh 5.9 と同じように読みます(`[s~]tudio` と `[s/]tudio` は `studio` に
  一致する)。
- **数値グロブと `GLOB_STAR_SHORT`。** zsh は `<N-M>`(`<->`、`<5->`)を単語の一部として読み、`[…]` の中と `^` の
  後でも同じです。数値グロブは範囲内の数になる 1 文字以上の数字に一致します: `mv frame<1-9>.png src/` は通し、
  `rm -rf studi[o<->]` は拒否します(角括弧の中の `<`・`-`・`>` は文字)。
  `< file` などのリダイレクトはリダイレクトのままです。`GLOB_STAR_SHORT` が有効でありうるときは、`**x` を `**/*x`
  として読みます(`setopt globstarshort; rm -rf **local` は拒否)。
- **失敗しうるコマンド。** 開くのに失敗しうるリダイレクト(ファイル、`$X`、ワイルドカード、`>&3`)があると、その
  コマンドは飛ばされ、組み込みコマンド・関数・`{ … }` も同じです。そのため `cd /tmp > /x/y; rm -rf studio` は開始
  フォルダで判定し、`true > /x/y || rm -rf studio` は拒否します。`/dev/null`、`2>&1`、here-string、ヒアドキュメント
  は対象外です。`PIPEFAIL` が有効でありうるときは、パイプラインの前のコマンドがパイプラインを失敗させることがあります
  (`false | true || …`)。
- **実行されるかどうか分からないコード。** 実行されなかったかもしれないコード — `if` や `case` の分岐、`&&` や `||`
  の後、ループの本体、リダイレクトが失敗しうるコマンド、`${X:=…}` や `${X=…}`、`read`、関数の中の `return` の後や
  分岐の中の書き込み、定義が実行されなかったかもしれない関数、`eval`、フック — が書いた値は、前の値と新しい値の
  どちらかとし、値を削除する場所や書く場所でそれぞれ判定します(`X=studio; [[ -e x ]] && X=a; rm -rf -- $X` は拒否)。
  `eval` やガードが読めない関数の後でも、コマンドが設定した値は候補として残ります。関数が書き込む前に `local`
  (`-g` のない `typeset`、`declare`、`private`、`integer`、`readonly` も)で宣言した名前はその関数のものなので、
  呼び出しの後は呼び出し側の値に戻ります(`X=studio; f(){ local X=a }; f; rm -rf -- $X` は拒否)。
- **起きるかどうか分からないフォルダ移動**(そうしたリダイレクト、`[[ … ]] && cd x`、`if` や `case` の分岐)の後では、
  git、`$PWD`、`~+`、`$(pwd)`、`git rev-parse --show-toplevel` を、コマンドが実行されうるフォルダごとに判定します
  (`cd studio > out.log; git clean -fdx` は拒否)。複数の Studio のリポジトリで実行されうるコミットは拒否します。実行され
  なかったかもしれない `pushd` や `cd` の後では、ディレクトリスタックはありうるスタックのどれか、`$OLDPWD` はありうる
  フォルダのどれかとします。`cd -`、`cd ~-`、`cd $OLDPWD`、`pushd ~-`、`env -C ~-` と `X=$OLDPWD; cd $X` のようなコピー
  はそのフォルダそれぞれへ行き、`$OLDPWD/studio` はそれぞれのパスを指します(`pushd src; pushd $X; rm -rf $OLDPWD/studio`
  は拒否)。`popd` はスタックごとに判定します(空のスタックでは失敗してシェルはその場にとどまります:
  `pushd src && make && popd; git commit -m x` は `src` がないとき通過)。ガードが追えない `pushd` (`pushd $X`、ワイルド
  カード、`pushd -`)は離れるフォルダを push し、スタックを回すもの(`pushd +1`)はスタックを不明にするので、後の `popd` は
  成功しえます(`pushd $X && popd && rm -rf studio` は拒否)。フォルダが不明になると、後のコマンドを、シェルがまだいるかも
  しれないフォルダと、ガードが分からないフォルダの両方で判定し、そこでの `$PWD`、`~+`、`$(pwd)`、
  `$(git rev-parse --show-toplevel)` はそのフォルダ自体として判定します(`cd $X > out.log; rm -rf $PWD/studio` は拒否)。
- **ワイルドカードと Studio のフックファイル。** インストールされたフックファイル(`.git/hooks/pre-commit`、
  `.husky/pre-commit`、`lefthook-local.yml`、Studio のランナーフォルダ)やリポジトリの git の設定、再帰的な削除なら
  その上のフォルダに一致しうるワイルドカードは拒否します(`cp /tmp/x .git/hooks/pre-commi?`、`rm -rf .git/h*`)。
  git の設定はフックがインストールされていなくても対象なので、`rm -rf .git/*` も拒否します。
- **`pushd`** を単語なしで使い、スタックが空なら、`cd` と同じく `$HOME` に移ります。
- **`cd`・`pushd`・どのコマンドの `~` の単語の前にでもコマンドがどんな方法ででも書いた `$HOME`**(`${HOME::=…}`、
  `${HOME:=…}`、`for HOME in …`、`read HOME`): リテラルの値は追い、ガードが知っている変数でできた値も追います
  (`X=<リポジトリ>; : ${HOME::=$X}`)。そうでなければ、その変数を埋めた、値の元のテキストから、`cd $D` の行き先と
  同じように Studio のリポジトリを探し、`~` の後のパスはガードが分からないフォルダの下のパスとして判定します。
  `~-` と `~+` は zsh 自身の前のフォルダと現在のフォルダなので、`$OLDPWD` や `$PWD` を書いても変わりません。
  前置きの `HOME=…` や `env HOME=…` は、コマンドが実行する文字列と関数にも効き
  (`HOME=<リポジトリ> eval 'rm -rf ~/studio'`、`HOME=<リポジトリ> sh -c '…'`)、`eval` や `source` は `$HOME` を書き
  うるものとして扱います。
- **ガードがパースできないコマンド**は、ガードが追う変数(`GIT_DIR`、`PATH` など)か、コマンドが後で展開する変数を
  代入するとき、Studio のリポジトリで拒否します(`GIT_DIR=/tmp/x; echo 'unterminated`)。グロブのグループがあるか、
  ファイルを削除・移動・書き込みするかコードを実行するコマンド(`rm`、`mv`、`cp`、`git`、`sh` など)があるときも
  拒否します(`[[ a == (a|b)|c ]]; rm -rf s*`)。そうしたコマンドはどう書いても対象です: パス(`/bin/rm`)、
  `=rm`、引用符やバックスラッシュ(`r''m`)、展開(`${:-rm}`、`$X`)、そうしたコマンドを実行するユーザーのエイリアスや
  関数。書き込みのリダイレクト(`>`、`>|`、`>>&!`、`&>|` など)も対象です。zsh の形式 `time;`、`! ;`、`coproc ;`、
  分岐の終わり `;|`、リダイレクト `>&|`、`>>&`、`&>>|` は通常どおり読みます。
- **Studio のリポジトリでは**、ガードの上限を超える長いコマンドを拒否し、関数が互いを呼び出す回数が多すぎるコマンドも
  拒否します(`f1(){ f0; f0; }; f2(){ f1; f1; }; …`)。
- **Studio のリポジトリ外では**、ガードの上限を超える長いコマンドは、リポジトリを指しうるものが一つもないときだけ
  通します: パス、展開、ワイルドカード、フォルダ移動、フック、フォルダを変えうるエイリアスや関数がないときです。
  シェルのスナップショットがなければ、そうしたコマンドはすべて拒否します。

## ガードが見ないもの

### ガードがモデル化しない方法でコマンドを実行するプログラムと設定

- ガードがモデル化しない方法で他のコマンドを実行するあらゆるプログラム。ガードは一般的な実行ツール(env・nohup・
  nice・timeout・time・script・flock・xargs・npx など)を読み、Studio のリポジトリでは、読めないと分かっている実行ツール
  (su・chroot・expect・tmux など)とコマンド値のオプション(`git -c core.editor`、`ssh -o ProxyCommand` など)を拒否
  します。どの一覧も完全ではありません。
- awk のプログラムと vim・ex・ed のスクリプト、`parallel` とそれが渡すコマンド。
- パッケージ実行ツールがさらに実行するもの(`npx sh -c …`、`npx git stash -a`、`npm exec -- chronic rm …`)。
- 他のツールがリポジトリ外に置いて後で読む設定: 環境にすでにある `LESSOPEN`、`~/.npmrc`、シェルの起動ファイル、vim の
  `~/.vimrc`・`~/.exrc`・`~/.vim/`、`~/.ExifTool_config`。git と ssh のユーザー設定ファイルはガードが守りますが、
  その設定が取り込むファイル(`[include]`、`Include`)は見ません。
- ガードの一覧にないコマンド値の設定: `make --eval`、`MANOPT`、git の `man.*.cmd`・`core.alternateRefsCommand`・
  `mergetool.*.path`・`submodule.*.update`、ssh の `-o PKCS11Provider` と `-I`、`ZDOTDIR`、`LD_PRELOAD`/`DYLD_*`、
  `NODE_OPTIONS`、`PERL5OPT`、`bun exec`/`bun run`。
- 一覧にないコマンドを実行する git のキー(`gpg.ssh.defaultKeyCommand`、`interactive.diffFilter`、
  `difftool.*.path`)。
- コードを実行するその他のプログラムと変数: `BASH_ENV`、`RUBYOPT`、Studio 自身のスクリプトにも効く `PYTHONPATH`・
  `PYTHONSTARTUP`・`PYTHONHOME`、`MAKEFILES`、`make -f <ファイル>`、`TAR_OPTIONS`、`ZIPOPT`、lesskey ファイル、
  `launchctl asuser`/`bsexec`。
- 他のオプションが指すプログラム: `sftp -D`、ssh の `-o SecurityKeyProvider`、`MAKEFLAGS='SHELL=…'`、tar の
  `--rsh-command`・`--rmt-command`、`git instaweb --httpd`/`-d`、`git web--browse -b`。
- ガードがモデル化しないプログラムの場合:
  - ワイルドカードと Studio のフォルダより上のフォルダ(`watchexec -- rm -rf stu*`、`.claude`、`.`);
  - `--オプション=コマンド` の単語(`foo --exec='rm -rf studio'`);
  - 文字列の中で引用符やバックスラッシュで分けた、または波括弧・`$PWD`・変数で作る保護名
    (`watchexec "rm -rf stu''dio"`、`watchexec 'X=studio; rm -rf $X'`)。
- オプションや環境で Studio のフォルダに置いた git の作業ツリーやファイル(`git --work-tree=studio clean -fd`、
  `GIT_WORK_TREE`、`GIT_TRACE=<ファイル>`、`GIT_INDEX_FILE`、`GIT_COMMON_DIR`)。
- 文書の種類の既定アプリが変わり、`open` がそのアプリを起動する場合。
- 書き込み可能な PATH のフォルダ(例: `/opt/homebrew/bin`、またはコマンドが `PATH` に入れたフォルダ)にコマンド名で
  置いたプログラムや、エージェントが自分でビルドして実行するプログラム。

### ガードが読めない値

- ガードが読めないパスの削除(`rm -rf $X`)。リテラルの末尾が studio ルートの下の保護フォルダを指すときは拒否します:
  `$X/studio/local` は拒否しますが、`$X/studio`・`./$X/studio`・`<リポジトリ>$X/studio` は拒否しません。
- 保護名の後ろや周りの展開を通した削除(`rm -rf studio$X`、`$(ls)studio`、`${:-studio}`、`${X:a}`、`${~X}`、
  `$X:s/…/'…'/`)。
- 関数の引数(`f() { rm -rf $1; }; f studio`、`() { … } studio`)。
- 保護対象を指さないテキストからコマンドが計算する値(`X=$(echo c3R1ZGlv | base64 -d)`、`X=$(ls)`)、展開が変える
  値(`${X/a/b}`、`${(U)X}`)、元のテキストがガードの読めない展開で書いた値、16 単語を超える値。
- 文字列の値のスライスや添字が保護対象の名前になる場合(`X=studiox; rm -rf $X[1,6]`、`${X[2,-1]}`)。
- rm・rmdir・unlink・touch・mkdir・chmod・trash で、ガードが知っている値を zsh が保護名に変える場合
  のうち `$~X` を通したもの(`X='s*o'; rm -rf $~X`)。ガードが分からないフォルダの下でも同じです
  (`cd $D; X='loca#l'; rm -rf $~X`)。
- シェル全体で `GLOB_SUBST` を有効にするユーザー関数と、コードを実行するグロブ修飾子を含む環境の値や前の呼び出しで
  作ったファイル名の組み合わせ。
- ガードが解決しない値を通したフォルダ移動(`setopt cdablevars`、`pushd` や `popd` の前の `dirstack=(…)`、
  `cd ~1`、`rm -rf ~1/studio`、`cdpath`)。
- Studio のリポジトリ内で stdin から受け取る xargs(`xargs rm -rf <<< studio`)。here-string が複数のときも同じです
  (`xargs rm -rf <<< studio <<< x`)。
- コマンドの出力をそのまま単語に使う場合(`rm -rf $(print studio)`、`rm -rf $(echo stu)dio`)と、展開が別の名前や
  既定値から取る値(X が設定されているときの `${X:-x}`、`${(P)Y}`、`typeset -n R=X`)。
- ループの本体が使った後に変える値: 次の回はループの前の値で判定します
  (`X=a; for i in 1 2; do rm -rf $X; X=studio; done`)。
- プロセス置換や、here-string が複数あるコマンドのパイプを通ってシェルに届く入力
  (`print 'rm -rf studio' > >(sh)`、`cat <<< x <<< 'rm -rf studio' | sh`)。
- ガードが読めないユーザーのシグナルトラップがあり、コマンドがそのシグナルをシェルに送る場合
  (`TRAPWINCH(){ zle -R }` の後の `kill -WINCH $$`)。
- 起きるかどうか分からないフォルダ移動の後で、ループの一覧、`[[ ]]` の単語、`{ … }` のリダイレクトに書いた `$PWD`
  (`[[ -e x ]] && cd studio; for f in $PWD/*; do rm -rf $f; done`)。コマンドの中で `CDABLE_VARS` を有効にした後、
  存在しないフォルダへの `cd NAME` が `$NAME` に移る場合(`setopt cdablevars; D=<リポジトリ>; cd D && rm -rf studio`)。
- パラメータの値を通して代入するユーザー関数の算術式(`x='GIT_DIR=1'` のときの `(( x ))`)。
- `EXTENDED_GLOB` が有効なときの、配列の代入の中でコードを実行するグロブ修飾子(`(#qe:…:)`、`(#q+f)`)
  (`setopt extendedglob; x=(*(#qe:'rm -rf studio':))`)。
- コマンド自身の単語の中のユーザーのグローバルエイリアス(`alias -g`)(`alias -g UP='..'` のときの
  `cd UP; rm -rf studio`)。
- `argv[N]=`、`N=`、`argv=(…)` で書いた位置パラメータと `$*[N]`/`$@[N]`
  (`set -- build; argv[1]=studio; rm -rf $1`)。
- 前に付けた代入を、その後の `eval` や `sh -c` の文字列が読む場合(`a=studio eval 'rm -rf $a'`)。
- zsh が自分で書く値(`REPLY`、`reply`、`MATCH`、`match`、`OPTARG`)と、結び付けた組の配列側から書いたスカラー側の値
  (`read <<< studio; rm -rf $REPLY`、`path[1]=studio; rm -rf $PATH`)。
- X が設定されているときの `${X:+word}`(`rm -rf ${a:+studio}`)と、代入の後で付けた大文字小文字の属性
  (`a=STUDIO; typeset -l a; git checkout $a`)。
- zsh が受け付けないオプションを付けた削除コマンドを、関数を削除したものとみなす場合(`unfunction -a f`、
  `unhash -dfm f`)。
- 既知の値の組み合わせが 16 通りを超えると、値から作った git のサブコマンドは従来どおり判定します
  (`git $a -fdx $b $c $d $e`)。
- `source` や `.` の後の残りは、0.0.26 の規則だけがその抜けとともに判定します: source のせいでフォルダが不明な間は
  git を検査せず、シェルを移動させるか `GIT_DIR`、`HOME` を export するかオプションを変えるファイルは見えません
  (`source env.sh; git clean -fdx`、`source env.sh; cd studio/videos/v; git clean -fdx`、
  `source env.sh; rm -f .git/hooks/pre-commit`、`f` に `setopt globsubst` があるときの `source f; X='s*o'; rm -rf $X`)。
  そこでのワイルドカードはリテラル部分で読み(`source env.sh; rm -rf stu*`)、シェル以外のインタプリタが実行する
  スクリプトは読みません(`source env.sh; python3 ev.py`)。`cd -`、`popd`、`~-`、`$OLDPWD` は、ファイルがこれらを
  変えても source の前に指していたフォルダへ行きます(`env.sh` に `pushd ../scripts; popd` があるときの
  `cd src; source env.sh; cd -; bash x.sh`)。シェルを移動させうる、コマンドが定義した関数はフォルダを不明にします
  (`f(){ cd studio/videos/v; }; source env.sh; f; git clean -fdx`)。
- ガードが内容を読めない `eval` の後の残りは、source の後と同じく 0.0.26 の規則だけで判定します。よくある前置きが
  そうです: `eval "$(pyenv init -)"`、`eval "$(ssh-agent -s)"`、`eval "$(direnv export zsh)"`、
  `eval "$(brew shellenv)"`。そのため、リポジトリの外で実行した
  `eval "$(pyenv init -)"; X=<repo>/studio; rm -rf $X/videos/v/work` は 0.0.26 と同じく通ります。0.0.28 で扱う
  予定です。
- `git stash pop` の後でもう一度実行するシェル文字列の中の破棄する git コマンドは、呼び出し前の作業ツリーで検査します
  (クリーンなツリーで `zsh -c 'git restore .'; git stash pop; zsh -c 'git restore .'`)。
- ガードが読めないパラメータ(環境変数など)で始まり Studio の名前で終わるオペランド(`rm -rf $Y/studio`)。
- コマンドが定義した `zsh_directory_name` 関数や `zsh_directory_name_functions`: zsh は `~[name]` の語ごとにこれを
  実行し、ガードはその動作を追わず(`src` からの `zsh_directory_name(){ cd ..; reply=(.); }; : ~[x]; rm -rf studio`)、
  代入の `=` の後で返すフォルダも追いません(`zsh_directory_name(){ reply=(..); }; X=~[x]; rm -rf $X/studio`)。

### Studio のリポジトリ外で使う形式

- ガードが読めない単語でのフォルダ移動と、そうしたフォルダの下に書くファイルのうち、パスが Studio の守るものを一つも
  指さないもの。
- リテラルでなく、リテラルの部分に Studio のパスがないシェル文字列。
- リポジトリを指すインタプリタのコード: `python3 -c`、`node -e`、`perl -e`、`osascript`、awk、
  `sh -c "$(printf …)"`、リテラルでない値で `functions[…]` に入れた関数の本体。
- そこで実行した `sed` の場合: スクリプト内の単純なパスでないファイル名、`e` とシェルを実行するコマンド、動的または
  展開されない変数。
- 既定値か置換にだけ書いたフォルダ(`cd ${U:-<リポジトリ>}`、`env -C ${U:-<リポジトリ>}`、`cd` か `~` の前の
  `HOME=${HOME/x/<リポジトリ>}`・`HOME=${:-<リポジトリ>}`)。
- xargs と find のテンプレート(`xargs sh -c '…' < /dev/null`、`find … -exec sh -c '…' \;`)。
- `eval`、`emulate … -c`、入力の `source` の後で、パイプや here-string から入力を受けるシェル
  (`eval true; echo 'rm -rf ~/proj/studio' | sh`)。
- 別のプログラムかコプロセスを通った入力を読むシェル(`{ cat | sh } <<< 'rm -rf <リポジトリ>/studio'`、
  `coproc sh; print -p …`)。
- リポジトリを指す文字列を zsh が後で実行する場合: trap の動作(`trap 'rm -rf <リポジトリ>/studio' EXIT`)、
  `PROMPT_SUBST` が有効なプロンプト文字列(`print -P '$(…)'`、`set -x` と組み合わせた `PS4='$(…)'`)。
- `hash -d` を実行しうるユーザー関数の後の `~名前`(`f <リポジトリ>; rm -rf ~w/studio`)。
- リポジトリのフォルダ名そのものに書いたグロブのグループ(`rm -rf <rep(o)>/studio`)。
- 関数や source ファイルが戻るときに実行されるトラップが、シェルを開始フォルダの外へ移す場合
  (別のフォルダから実行した `f(){ trap 'cd ~/proj' EXIT; }; f; rm -rf studio`)。
- ガードが解析できないテキストは、リポジトリをリテラルで指すときだけ拒否します。別の方法でリポジトリに届くテキストは
  拒否しません(パーサが拒否する形式と組み合わせた `HOME=<parent>; rm -rf ~/<name>/studio`)。
- 名前に空白か `;&|()<>=:,` のいずれかを含むリポジトリのフォルダ(コマンドがガードの上限を超えるとき)。

### その他

- `chmod 000 studio`。
- 開始パスの前の find のオプション(`find -L studio -delete`、`find -f studio -delete`)。
- 保護ファイルの上に書くアーカイブや展開したファイル(`tar -cf <state.json> …`、`gunzip -f <state.json>.gz`)。
- 大文字小文字を変えて書いた Studio のスクリプト名(大文字小文字を区別しないボリュームでの `STATE.py approve`)。
- 大文字小文字を区別するボリュームでの `unsetopt caseglob`、またはワイルドカードの前の部分の `(#i)` の後に続く
  リテラルの部分: ガードはボリュームと同じように名前を比べます(`unsetopt caseglob; rm -rf s*/LOCAL`)。
- 存在するフォルダへの `cd` は成功するものとみなします。`||` の後のコマンドは、失敗しうるときだけ判定します
  (`cd src 2>/dev/null || cd studio; rm -rf local`)。
- X が存在しないときの `cd X || exit`(`return`、`logout` も)はシェルが続くものとして判定するので、zsh は `exit`
  で終わるのに後の `git commit -m x` をフォルダの分からないコミットとして拒否することがあります(`src` のない
  フォルダからの `cd src || exit 1; …; git commit -m x` で、間の行が `pushd` と `popd` でシェルを移動させるとき)。
- EXIT 以外の `trap` の動作が変数を含む文字列なら、その後ではその変数の引用符のない値を拒否します
  (`trap "rm -rf $TMPD" INT; echo hi > $TMPD/x`)。引用符で囲んでください(`"$TMPD/x"`)。
- 実行されなかったかもしれない `pushd` の後の `popd` は、残るフォルダとは別にスタックごとに判定するので、
  `[[ -e x ]] && pushd studio; popd; rm -rf local` は zsh が何も削除しないのに拒否します。
- 列挙した項目が 500 を超える `**` ワイルドカードは列挙せずに判断します。大きなツリーでは、保護対象に一致しない
  書き込みや削除も拒否することがあります(`touch **/*.ts`)。
- 外部監査役(`std-auditor`)の読み取りプログラムの一覧には、オプションや 2 つ目のオペランドでファイルを書ける
  プログラムがあります(`less -o`、`less -O`、`LESS=…`、`tree -o`、ファイルを 2 つ与えた `xxd`)。値から作った
  オプションの省略形(`sort -$v`)も同じです。
- `eval` の後では、何も変えないリテラルの文字列でも git を拒否します(`eval "echo hello"; git status`)。
- ガードが分からないフォルダでは、`-n` と `list` を含むすべての `git clean` と `git worktree` の形式を、変更を捨てる
  ものと数えます(`take build && cd .. && git clean -n` は拒否)。
- コマンドが定義した関数が `"$@"` をプログラムに渡すと、呼び出しの引数がリテラルでも拒否します
  (`mygit(){ git "$@"; }; mygit status`)。コマンドを直接書いてください。
- コミットされていない Studio の変更は呼び出しの実行前に読みます: 同じ呼び出しで前にある `git stash pop` や
  `git stash apply` が Studio の変更を戻しても、後の `git checkout .` や `git reset --hard` はそれを見ません
  (`git reset --hard; git stash pop; git reset --hard`)。
- 実行されなかったかもしれないフォルダ移動が長く続き、その間に `cd ~-` や `cd $OLDPWD` があると、パスの引数が多すぎると
  して拒否されることがあります(G-LIMIT): 各単語をシェルがいるかもしれないすべてのフォルダで判定するためです。
- フォルダへ `cd` してから `cd -` するまでの間に失敗しうるコマンドがあると、`**` の削除はリテラル部分で判定します
  (`cd src && pytest && cd - && rm -rf **/__pycache__` は拒否)。
