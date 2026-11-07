# Studio 가드: 판정하는 것과 보지 못하는 것(0.0.27)

README에는 요약이 있고, 이 파일에는 자세한 내용이 있습니다. 여기 적은 모든 경우에도 pre-commit 훅, 커밋 검사, 사람의
게이트가 뒤에 남아 있습니다.

## 0.0.26 가드를 백스톱으로

- 모든 호출은 플러그인 안에 바꾸지 않고 둔 0.0.26 가드로도 판정합니다. 두 가드 중 하나라도 거부하면 거부합니다.
  0.0.26 가드만 거부하면 그 메시지는 0.0.26에서 보여 준 것과 같습니다.
- 그래서 0.0.27은 0.0.26이 거부한 것을 모두 거부하며, 그 잘못된 거부도 그대로입니다:
  - Studio 레포에서 `**`로 지우거나 쓰는 것(`rm -rf **/__pycache__`, `rm -f **/*.pyc`);
  - 아주 많은 파일을 한 번에 읽는 것. 0.0.26 가드의 내부 오류(G-ERR)가 될 수 있습니다;
  - 텍스트가 studio를 언급하거나 0.0.26이 읽지 못한 사용자 셸 함수 뒤의 git이나 `open`
    (`gh pr view 1; git commit -m 'studio: v script'`, `diff a.txt src/a.ts; git status`);
  - 셸 스냅숏이 없을 때 `PATH`에 없는 명령(`flock /tmp/build.lock make`).
- 이들은 0.0.28에서 source 뒤의 더 강한 검사와 함께, 종류별로 풀 예정입니다.
- `git push`와 Studio 커밋의 검사는 두 가드에 한 번만 실행합니다. 두 가드가 쓸 수 있는 시간보다 오래 걸리는 호출은
  훅의 20초 한도보다 훨씬 전에 거부합니다(G-LIMIT). 훅이 시간을 넘기면 메시지 없이 막히기 때문입니다.

## 함수, 훅, 옵션을 판정하는 방식

- **사용자 셸 함수**(셸 스냅숏에서 온 것):
  - export하거나, git이나 가드가 읽는 변수(`PATH`, `HOME`, `GIT_*`, 이미 export된 이름)를 설정하거나, 파일을
    source하거나 eval할 수 있는 함수 뒤에서는 git을 거부합니다. 예: `nvm`이나 `pyenv` 래퍼.
  - 폴더를 바꿀 수 있는 함수(`cd`, `pushd`) 뒤에서는 커밋, `git config`, 변경을 버리는 git 형식, `open`을 거부합니다.
    가드가 따라갈 수 없는 폴더 이동(`cd -1`, `cd $(mktemp -d)`) 뒤에서도 마찬가지입니다.
  - `gh` · `diff` · 프롬프트 도우미 같은 래퍼는 해당하지 않습니다(`gh pr create --fill && git push`는 통과). 0.0.26
    가드가 거부하는 경우는 예외입니다(위의 백스톱).
- **사용자의 훅 함수.** 폴더를 바꿀 수 있는 `chpwd`나 `TRAP*` 함수가 있으면 그 뒤의 모든 명령에서 폴더를 알 수 없는
  것으로 봅니다. export하거나 가드가 읽을 수 없는 함수를 부르는 것이면 어떤 `cd` 뒤에서든 git을 거부합니다
  (`cd src && git status`). `TRAPEXIT`와 가드가 읽을 수 없는 시그널 트랩(`TRAPWINCH(){ zle && zle -R }`)은 명령
  사이에서 실행되지 않는 것으로 봅니다. 가드가 읽을 수 없는 `TRAPDEBUG`, `TRAPZERR`, `command_not_found_handler`는
  폴더를 알 수 없게 합니다.
- **명령이 정의한 함수.**
  - 함수를 정의하면 사용자 스냅숏 함수의 효과를 알 수 없는 것으로 봅니다. `eval` · `source` · `autoload` ·
    `functions[…]`로 정의할 수 있는 경우와 사용자의 autoload 스텁(`# undefined`)도 마찬가지입니다.
  - 명령이 자기가 정의한 함수를 부르면, 본문이 export하거나 대입하는 것을 가드가 따라가지 않는 값으로 적용합니다.
    `y(){ export GIT_DIR=/tmp/x; }; y; git commit -m x`는 `export GIT_DIR=…; git commit -m x`처럼 판정합니다.
  - 함수를 호출하면 그 본문을 호출한 곳에서 다시 판정합니다: 그 폴더에서, 그때의 값과 앞붙인 대입으로
    (`f(){ rm -rf studio }; cd <레포>; f`, `f(){ rm -rf $X }; X=studio; f`).
  - `function a b { … }`는 모든 이름을 정의합니다.
  - 다른 함수 본문 안에서 정의한 함수는 그 함수를 부른 뒤부터 있습니다(`f(){ k(){ cd studio } }; f; k`).
    `functions -c`는 명령이 정의한 함수를 효과와 함께 복사합니다. 그 밖의 복사는 zsh의 함수 테이블에 쓰는 것이므로
    Studio 레포에서 거부합니다(`functions -c nvm k`).
  - 명령이 지운 함수(`unfunction f`, `unhash -f f`, `unset -f -- f`, `disable -f f`, `-m` 패턴)는 그 뒤의 호출에서
    없습니다. 그 이름은 같은 이름의 명령을 실행합니다(`git(){ :; }; unfunction git; git clean -fdx`는
    `git clean -fdx`처럼 판정). 지워졌을 수도 아닐 수도 있는 함수(`[[ -e x ]] && unfunction f`)는 두 경우를 모두
    판정합니다. 가드가 따라가지 않는 방식으로 함수를 지우거나 바꿀 수 있는 코드 — `eval`이나 `emulate … -c` 문자열,
    source한 파일, 가드가 읽을 수 없는 이름의 정의(`$n(){ … }`), 가드가 읽을 수 없는 함수나
    `DEBUG`/`ZERR` 훅, 가드가 읽을 수 없는 명령 단어 — 뒤의 호출은 이런 함수를 따라가기 전처럼 판정합니다: 폴더와
    호출이 쓸 수 있는 값은 알 수 없는 것으로 보고, 같은 이름의 명령도 판정합니다
    (`f(){ cd /tmp; }; eval 'f(){ :; }'; f; rm -rf studio`는 거부).
- **명령이 정의한 훅.** `chpwd`, `TRAPDEBUG`, `TRAPZERR`, `TRAP<signal>` 함수, `command_not_found_handler`,
  `trap … DEBUG`, `trap … ZERR`, 시그널에 건 트랩(`trap … INT TERM`), `chpwd_functions=(…)`는 뒤의 명령 사이에서
  실행될 수 있습니다. 훅이 할 수 있는 일은 그 뒤로 계속 적용됩니다: 폴더를 바꿀 수 있거나 가드가 읽을 수 없으면 폴더를
  알 수 없는 것으로 보고, 대입할 수 있는 값은 이전 값과 새 값 중 하나로 봅니다. 명령이 정의한 함수를 이름으로 부르는
  트랩 동작은 그 함수로 읽습니다(`cleanup(){ rm -f $tmp; }; trap cleanup INT TERM`은 아무것도 바꾸지 않음). 명령이
  나중에 그 함수를 다시 정의해도 마찬가지입니다. 함수 밖에서 건 `trap … EXIT`(또는 `0`)와 `TRAPEXIT`는 셸이 끝날 때,
  즉 호출의 모든 명령 뒤에 실행되므로 뒤의 명령은 폴더와 값을 그대로 유지합니다(`trap 'cd /' EXIT; rm -rf $PWD/studio`는
  거부, `cleanup(){ rm -f $tmp; }; trap cleanup EXIT; git commit -m x`는 통과). 함수 안에서 건 EXIT 트랩은 함수가
  돌아갈 때 실행되므로 훅으로 봅니다. `precmd`, `preexec`, `periodic`, `zshaddhistory`, `zshexit`(와 그
  `*_functions` 배열)는 Bash 도구의 명령 사이에서 실행되지 않습니다. 동작의 텍스트는 이전처럼 검색합니다.
- **명령이 source하는 파일.** `source`나 `.` 뒤의 나머지는 0.0.26 규칙만으로 판정합니다(위의 백스톱). 거기서의 더
  강한 검사는 0.0.28에서 할 예정입니다.
  - 명령이 정의한 별칭, `builtin` · `command` · `noglob`, 명령이 정의하고 호출한 함수, source를 실행할 수 있는
    `eval`이나 `emulate … -c` 문자열을 거쳐 source에 닿을 때도 같습니다. 가드가 텍스트를 읽을 수 없는 `eval` 뒤에도
    같습니다(`eval "$(pyenv init -)"`).
  - source 앞의 코드는 평소처럼 판정하고, 호출 자체가 source에 준 코드도 판정합니다: 그 입력
    (`source /dev/stdin <<< …`, heredoc)이나 호출이 쓴 파일. `{ source /dev/stdin } <<< 'rm -rf studio/local'`는
    거부합니다.
  - 서브셸, 분기, 반복문, 파이프라인 안의 source도 호출의 나머지에 대한 더 강한 검사를 끝냅니다:
    `if [[ -n $CI ]]; then source ci.sh; else rm -rf studio/local; fi`는 0.0.26 규칙으로 판정합니다(거부).
  - source하지만 호출하지 않는 함수는 이를 끝내지 않습니다. source하는 `chpwd` 함수나 트랩도 마찬가지입니다: 그
    본문은 정의한 곳에서 읽습니다.
  - 이 가드는 사용자의 파일을 읽지 않습니다. 0.0.26 가드가 이전처럼 그 텍스트를 검색합니다.
- **동적 이름 디렉터리.** zsh는 `~[name]`을 `zsh_directory_name` 함수나 `zsh_directory_name_functions`로 풀며, 이는
  명령이나 source한 파일, `eval`이 정의할 수 있습니다. 가드는 이를 실행하지 않습니다. Studio 레포에서 명령이 지우거나
  쓰는 `~[name]` 경로는 거부하고, `cd ~[name]`은 폴더를 알 수 없게 합니다.
- **`NULLCMD`/`READNULLCMD`**를 페이저가 아닌 값으로 설정하면 리다이렉션만 있는 명령이 입력을 셸 코드로 실행합니다:
  here-string, heredoc, `<` 파일, 또는 그 명령이 놓인 파이프(`print … | > /dev/null`, `… | < /dev/stdin`).
- **입력.** `{ … }`, `( … )`, 루프, `if`, 명령이 정의한 함수에 준 here-string · heredoc · `<` 파일 · 파이프는 그 안의
  모든 명령이 읽습니다(`{ sh } <<< …`, `f <<< …`). `exec <<< …`와 `exec 3< f`는 뒤의 명령에도 이어지고, `<&3`은
  fd 3이 가진 것을 읽습니다(`exec 3<<< …; sh <&3`). 가드가 알 수 없는 입력을 읽는 셸(모르는 fd의 `sh <&3`)은
  Studio 레포에서 거부합니다. `eval` 문자열과 `-c` 문자열은 그 명령의 입력으로 실행되고(`eval sh <<< …`,
  `zsh -c sh <<< …`), `eval` 문자열이 정의한 함수는 호출할 때 받은 입력으로 읽습니다(`eval 'f(){ sh }'; f <<< …`).
  한 명령의 입력 리다이렉션이 여럿이거나 파이프와 함께 있으면 zsh의 `MULTIOS`처럼 모두 차례로 읽습니다
  (`sh <<< … <<< x`, `sh <<< … < /dev/null`, `echo … | sh <<< x`). stdin의 `<>`도 입력으로 봅니다
  (`sh <<< … <> /dev/null`).
- **`set` 플래그와 스냅숏의 옵션.** `set` 플래그는 한 글자씩 읽습니다(`set -euo pipefail`, `set -ex`, `set +eu`).
  `-o NAME`은 옵션 이름입니다. 가드가 모르는 글자(`set -r`)는 옵션을 알 수 없게 합니다. 스냅숏의 `setopt` 목록에
  없는 옵션은 zsh 기본값입니다(`AUTO_PUSHD` 꺼짐). 스냅숏이 없으면 `AUTO_PUSHD`가 켜졌을 수도 꺼졌을 수도 있으므로
  `cd` 뒤의 `popd`를 두 경우 모두로 판정합니다.
- **따옴표 없는 `$X`**(`$X[1]`, `$X:t`, `$1`, `$@`, `$_`도):
  - `eval`이나, 단어를 바꾸는 옵션(`GLOB_SUBST`, `SH_WORD_SPLIT` 등)을 `LOCAL_OPTIONS` 없이 켤 수 있는 함수, 또는
    가드가 읽을 수 없는 함수 뒤에서는 명령이 그 값을 스스로 넣었을 수 있을 때 거부합니다. 곧 명령이 그 값을 어떤
    이름으로든(`PS1`/`PROMPT`, `cdpath`/`CDPATH`, `typeset -T` 쌍, `$aliases[…]`) 대입하거나 읽은 경우, 파일 이름을
    도는 경우, 그런 함수에 가드가 읽을 수 없는 단어 · 변수 이름 · stdin · 명령이 쓴 파일을 넘긴 경우입니다.
  - 환경에서만 오는 값은 단어를 어디에 있든 같은 뜻으로 읽는 프로그램(`ls`, `cat`, `grep`, `echo` 등)에서는 전과 같이
    판정합니다. 그 밖의 프로그램에서는 가드가 읽을 수 없는 함수 뒤의 따옴표 없는 값을 거부합니다. 단어가 나뉠 수
    있기 때문입니다(`nvm use 20; cp $X /tmp/y`).
  - `[[ ]]`, `case`, 스칼라 대입, `${#X}`는 전과 같이 판정합니다. 배열 값(`W=($X)`, `typeset -a W=($X)`)은 파일
    이름입니다.
  - `GLOB_SUBST`가 켜졌을 수 있으면 한 단어의 부분을 함께 검사합니다(`$X$Y`, `${X}'…'`). `(`가 든 값 옆에 가드가
    텍스트를 계산할 수 없는 부분이 있으면 거부합니다(`${X:&}`, `$X:s/…/'…'/`). `0=…`과 `1=…`은 대입이므로
    `$0`도 명령이 설정한 값으로 봅니다. 위치 매개변수를 하나라도 설정하면(`2=…`, `argv[2]=…`, `set --`) 모두를
    설정한 것으로 봅니다(`$@`, `$*`, `$argv`, `shift` 뒤). `$~1`, `$=1`, `$~@`는 `${~1}`과 같은 패턴 확장입니다.
  - `GLOB_SUBST`나 `SH_WORD_SPLIT`이 패턴이나 여러 단어로 바꿀 수 있는 알려진 값(`setopt globsubst`, `set -y`)은
    전체로도, 단어별로도 판정합니다.
- **가드가 하나의 문자열로 따라가지 않는 값**: 배열(`X=(studio)`), `read`, `print -v`, `set -A`, `$1`과 함께 쓴
  `set --`, `$(print …)`, `for` 변수, 명령이 정의한 함수가 대입하는 전역 변수, 명령이 실행될 수 있는 폴더마다 다른
  값. 이런 값을 지우거나 쓰는 곳에서는 값이 나온 텍스트의 단어로 가질 수 있는 값을 하나씩 판정합니다
  (`X=(studio); rm -rf -- $X`는 거부하고 `files=(a b); rm -f $files`는 통과). 명령이 계산하는 값(`X=$(ls studio)`)은
  그 명령의 단어 중 Studio가 보호하는 것을 가리키는 단어를 값으로 판정합니다.
  명령이 대입한 알려진 값 몇 개 중 하나인 단어(빈 값이나 공백 · 와일드카드 · 따옴표 · 그 밖의 셸 문자가 든 값이
  없고, `$PWD`나 `$OLDPWD`가 아니며, `GLOB_SUBST`와 `SH_WORD_SPLIT`이 꺼진 경우)가 있으면 명령을 값마다 한 번씩,
  최대 16번, 그렇게 쓴 것처럼 판정합니다(`if [[ -e x ]]; then B=develop; else B=main; fi; git checkout $B`,
  `cd $D`는 각 폴더로 갑니다). 각 경우는 차례가 아니라 그중 하나입니다: 한 경우의 재귀 복사가 다른 경우의 쓰기보다
  앞서지 않습니다(`if [[ -n $CI ]]; then OUT=dist; else OUT=build; fi; cp -r src/* $OUT/`는 통과). 조합이 16개를
  넘으면 그 단어들을 가드가 읽을 수 없는 단어로 판정하며, Studio 레포에서 그런 단어가 셋을 넘는 명령은 한도를 밝히는
  메시지와 함께 거부합니다(값을 그대로 쓰거나 명령을 나누세요). 외부 감사자(`std-auditor`)에게는 모든 경우가 읽기만 해야 합니다. 배열의 원소 하나
  (`$A[k]`)는 그 값 중 하나입니다. 문자열의 슬라이스나 첨자, 수식자(`$X[2,-1]`, `${X:1}`, `$X:t`)는 값의 일부를
  주므로 그 후보를 정확한 값으로 보지 않습니다.
- **글롭 그룹.** Studio 레포에서는 zsh가 파일 이름으로 펼치는 단어에 글롭 그룹 `(…)`이 있으면 거부합니다
  (`ls *(.)`, `ls (a|b).txt`). Bash 도구는 zsh를 `BARE_GLOB_QUAL`을 끈 채 실행하므로 `*(.)`은 글롭 한정자가 아니라
  패턴입니다(`studi(o)`가 `studio`와 맞음). `[[ ]]`의 `=~` 뒤 정규식은 글롭 그룹이 아닙니다
  (`[[ $b =~ ^feature/(.*)$ ]]`). `[[ ]]`의 `==` · `=` · `!=` 뒤 패턴도 파일 이름을 만들지 않으므로 글롭 그룹으로
  보지 않고(`[[ $x == (a|b) ]]`), 명령의 나머지는 평소처럼 판정합니다. `case` 패턴도 마찬가지이고
  (`case $f in *.(ts|tsx)) …`, `case $x in (#i)y) …`), 각 갈래의 명령은 판정합니다. `;&`나 `;|` 뒤의 갈래는 앞
  갈래가 셸을 남겨 둔 폴더에서 실행될 수 있습니다.
- **zsh의 짧은 형식**(`for i in x; cmd`, `for ((…)) cmd`, `while … { … }`, `if … { … }`, `case x { … }`)은
  Studio 레포에서 거부합니다. `do … done`, `then … fi`, `in … esac`로 쓰세요. 가드가 파싱할 수 없는 조건이나 루프
  머리도 같이 거부합니다.
- **확장 글롭.** `EXTENDED_GLOB`이 켜졌을 수 있으면 `^` · `~` · `#`를 zsh처럼 읽습니다(이름 끝의 `~`는 글자).
  보호 이름과 맞을 수 있는 단어만 거부합니다: `setopt extendedglob; cd $D; rm -rf ^x`는 거부하고,
  `touch notes#1`, `cp a.txt a.txt~`, `rm -f *~`는 통과합니다. 대괄호 식 안에서는 이들과 `/`가 글자이고, `!`/`^`,
  맨 앞의 `]`, 범위, `[:class:]`는 zsh 5.9처럼 읽습니다(`[s~]tudio`와 `[s/]tudio`는 `studio`와 맞음).
- **숫자 글롭과 `GLOB_STAR_SHORT`.** zsh는 `<N-M>`(`<->`, `<5->`)을 단어의 일부로 읽고, `[…]` 안과 `^` 뒤에서도
  그렇습니다. 숫자 글롭은 범위 안의 수를 이루는 숫자 하나 이상과 맞습니다: `mv frame<1-9>.png src/`는 통과하고,
  `rm -rf studi[o<->]`는 거부합니다(대괄호 안의 `<` · `-` · `>`는 글자). `< file`과
  다른 리다이렉션은 그대로 리다이렉션입니다. `GLOB_STAR_SHORT`가 켜졌을 수 있으면 `**x`를 `**/*x`로 읽습니다
  (`setopt globstarshort; rm -rf **local`은 거부).
- **실패할 수 있는 명령.** 열기에 실패할 수 있는 리다이렉션(파일, `$X`, 와일드카드, `>&3`)이 있으면 그 명령은
  건너뛰어지고, 빌트인 · 함수 · `{ … }`도 마찬가지입니다. 그래서 `cd /tmp > /x/y; rm -rf studio`는 시작 폴더에서
  판정하고, `true > /x/y || rm -rf studio`는 거부합니다. `/dev/null`, `2>&1`, here-string, heredoc은 해당하지
  않습니다. `PIPEFAIL`이 켜졌을 수 있으면 파이프라인의 앞 명령이 파이프라인을 실패시킬 수 있습니다
  (`false | true || …`).
- **실행될 수도 안 될 수도 있는 코드.** 실행되지 않았을 수 있는 코드 — `if`나 `case`의 갈래, `&&`나 `||` 뒤,
  루프 본문, 리다이렉션이 실패할 수 있는 명령, `${X:=…}`나 `${X=…}`, `read`, 함수 안에서 `return` 뒤나 갈래 안의 쓰기,
  정의가 실행되지 않았을 수 있는 함수, `eval`, 훅 — 이 쓴 값은 이전 값과 새 값 중 하나이며, 값을 지우거나 쓰는 곳에서
  각각 판정합니다(`X=studio; [[ -e x ]] && X=a; rm -rf -- $X`는 거부). `eval`이나 가드가 읽을 수 없는 함수 뒤에도
  명령이 설정한 값은 후보로 남습니다. 함수가 쓰기 전에 `local`(`-g` 없는 `typeset`, `declare`, `private`,
  `integer`, `readonly`도)로 선언한 이름은 그 함수의 것이므로 호출 뒤에는 호출한 쪽의 값으로 돌아갑니다
  (`X=studio; f(){ local X=a }; f; rm -rf -- $X`는 거부).
- **일어날 수도 안 일어날 수도 있는 폴더 이동**(그런 리다이렉션, `[[ … ]] && cd x`, `if`나 `case`의 갈래) 뒤에서는 git,
  `$PWD`, `~+`, `$(pwd)`, `git rev-parse --show-toplevel`을 명령이 실행될 수 있는 폴더마다
  판정합니다(`cd studio > out.log; git clean -fdx`는 거부). 둘 이상의 Studio 레포에서 실행될 수 있는 커밋은 거부합니다.
  실행되지 않았을 수 있는 `pushd`나 `cd` 뒤에서 디렉터리 스택은 가능한 스택 중 하나, `$OLDPWD`는 가능한 폴더 중 하나로
  봅니다. `cd -`, `cd ~-`, `cd $OLDPWD`, `pushd ~-`, `env -C ~-`와 `X=$OLDPWD; cd $X` 같은 복사는 그 폴더마다 가고,
  `$OLDPWD/studio`는 폴더마다의 경로를 가리킵니다(`pushd src; pushd $X; rm -rf $OLDPWD/studio`는 거부). `popd`는
  스택마다 판정합니다(빈 스택에서는 실패하고 셸이 그 자리에 머뭅니다: `pushd src && make && popd; git commit -m x`는
  `src`가 없을 때 통과). 가드가 따라갈 수 없는 `pushd`(`pushd $X`, 와일드카드, `pushd -`)는 떠나는 폴더를 push하고,
  스택을 돌리는 것(`pushd +1`)은 스택을 알 수 없게 하므로 뒤의 `popd`는 성공할 수
  있습니다(`pushd $X && popd && rm -rf studio`는 거부). 폴더를 알 수 없게 되면 뒤의 명령을 셸이 아직 있을 수 있는
  폴더들과 가드가 알 수 없는 폴더 모두에서 판정하고, 그곳의 `$PWD`, `~+`, `$(pwd)`, `$(git rev-parse --show-toplevel)`은
  그 폴더 자체로 판정합니다(`cd $X > out.log; rm -rf $PWD/studio`는 거부).
- **와일드카드와 Studio의 훅 파일.** 설치된 훅 파일(`.git/hooks/pre-commit`, `.husky/pre-commit`,
  `lefthook-local.yml`, Studio의 러너 폴더)이나 레포의 git 설정, 재귀 삭제라면 그 위 폴더와 맞을 수 있는
  와일드카드는 거부합니다(`cp /tmp/x .git/hooks/pre-commi?`, `rm -rf .git/h*`). git 설정은 훅이 설치되지 않아도
  해당하므로 `rm -rf .git/*`도 거부합니다.
- **`pushd`**를 단어 없이 쓰고 스택이 비어 있으면 `cd`처럼 `$HOME`으로 갑니다.
- **명령이 `cd` · `pushd` · 아무 명령의 `~` 단어 앞에서 어떤 방법으로든 쓴 `$HOME`**(`${HOME::=…}`, `${HOME:=…}`,
  `for HOME in …`, `read HOME`): 리터럴 값은 따라가고, 가드가 아는 변수로 된 값도 따라갑니다
  (`X=<레포>; : ${HOME::=$X}`). 그렇지 않으면 그 변수를 채운, 값이 나온 텍스트에서 `cd $D`의 대상처럼 Studio 레포를
  찾고, `~` 뒤의 경로는 가드가 알 수 없는 폴더 아래의 경로로 판정합니다. `~-`와 `~+`는 zsh 자신의 이전 폴더와 현재
  폴더이므로 `$OLDPWD`나 `$PWD`를 써도 바뀌지 않습니다. 앞붙인 `HOME=…`이나 `env HOME=…`은 명령이 실행하는 문자열과
  함수에도 적용되고(`HOME=<레포> eval 'rm -rf ~/studio'`, `HOME=<레포> sh -c '…'`), `eval`이나 `source`는 `$HOME`을
  쓸 수 있는 것으로 봅니다.
- **가드가 파싱할 수 없는 명령**은 가드가 따라가는 변수(`GIT_DIR`, `PATH` 등)나 명령이 나중에 펼치는 변수를 대입하면
  Studio 레포에서 거부합니다(`GIT_DIR=/tmp/x; echo 'unterminated`). 글롭 그룹이 있거나, 파일을 지우거나 옮기거나
  쓰거나 코드를 실행하는 명령(`rm`, `mv`, `cp`, `git`, `sh` 등)이 있어도 거부합니다
  (`[[ a == (a|b)|c ]]; rm -rf s*`). 그런 명령은 어떻게 쓰든 해당합니다: 경로(`/bin/rm`), `=rm`, 따옴표나
  백슬래시(`r''m`), 확장(`${:-rm}`, `$X`), 그런 명령을 실행하는 사용자 별칭이나 함수. 쓰기 리다이렉션(`>`, `>|`,
  `>>&!`, `&>|` 등)도 해당합니다. zsh의 형식 `time;`, `! ;`, `coproc ;`, 갈래 끝 `;|`, 리다이렉션 `>&|`, `>>&`,
  `&>>|`는 평소처럼 읽습니다.
- **Studio 레포에서는** 가드의 한도를 넘는 긴 명령을 거부하고, 함수가 서로를 너무 많이 호출하는 명령도 거부합니다
  (`f1(){ f0; f0; }; f2(){ f1; f1; }; …`).
- **Studio 레포 밖에서는** 가드의 한도를 넘는 긴 명령은 레포를 가리킬 수 있는 것이 하나도 없을 때만 통과합니다: 경로,
  확장, 와일드카드, 폴더 이동, 훅, 폴더를 바꿀 수 있는 별칭이나 함수가 없을 때입니다. 셸 스냅숏이 없으면 그런 명령은
  모두 거부합니다.

## 가드가 보지 못하는 것

### 가드가 모델링하지 않는 방식으로 명령을 실행하는 프로그램과 설정

- 가드가 모델링하지 않는 방식으로 다른 명령을 실행하는 모든 프로그램. 가드는 흔한 실행기(env · nohup · nice · timeout ·
  time · script · flock · xargs · npx 등)를 읽고, Studio 레포에서는 읽을 수 없다고 아는 실행기(su · chroot · expect ·
  tmux 등)와 명령 값 옵션(`git -c core.editor`, `ssh -o ProxyCommand` 등)을 거부합니다. 어떤 목록도 완전하지 않습니다.
- awk 프로그램과 vim · ex · ed 스크립트, `parallel`과 그것이 넘겨주는 명령.
- 패키지 실행기가 다시 실행하는 것(`npx sh -c …`, `npx git stash -a`, `npm exec -- chronic rm …`).
- 다른 도구가 레포 밖에 두었다가 나중에 읽는 설정: 환경에 이미 있는 `LESSOPEN`, `~/.npmrc`, 셸 시작 파일, vim의
  `~/.vimrc` · `~/.exrc` · `~/.vim/`, `~/.ExifTool_config`. git과 ssh의 사용자 설정 파일은 가드가 지키지만, 그 설정이
  끌어오는 파일(`[include]`, `Include`)은 보지 못합니다.
- 가드 목록에 없는 명령 값 설정: `make --eval`, `MANOPT`, git의 `man.*.cmd` · `core.alternateRefsCommand` ·
  `mergetool.*.path` · `submodule.*.update`, ssh의 `-o PKCS11Provider`와 `-I`, `ZDOTDIR`, `LD_PRELOAD`/`DYLD_*`,
  `NODE_OPTIONS`, `PERL5OPT`, `bun exec`/`bun run`.
- 목록 밖의 명령을 실행하는 git 키(`gpg.ssh.defaultKeyCommand`, `interactive.diffFilter`, `difftool.*.path`).
- 코드를 실행하는 그 밖의 프로그램과 변수: `BASH_ENV`, `RUBYOPT`, Studio 자체 스크립트에도 적용되는 `PYTHONPATH` ·
  `PYTHONSTARTUP` · `PYTHONHOME`, `MAKEFILES`, `make -f <파일>`, `TAR_OPTIONS`, `ZIPOPT`, lesskey 파일,
  `launchctl asuser`/`bsexec`.
- 다른 옵션이 가리키는 프로그램: `sftp -D`, ssh의 `-o SecurityKeyProvider`, `MAKEFLAGS='SHELL=…'`, tar의
  `--rsh-command` · `--rmt-command`, `git instaweb --httpd`/`-d`, `git web--browse -b`.
- 가드가 모델링하지 않는 프로그램의 경우:
  - 와일드카드와 Studio 폴더 위의 폴더(`watchexec -- rm -rf stu*`, `.claude`, `.`);
  - `--옵션=명령` 단어(`foo --exec='rm -rf studio'`);
  - 문자열 안에서 따옴표나 백슬래시로 나뉘었거나 중괄호 · `$PWD` · 변수로 만들어지는 보호 이름
    (`watchexec "rm -rf stu''dio"`, `watchexec 'X=studio; rm -rf $X'`).
- 옵션이나 환경으로 Studio 폴더에 둔 git 작업 트리나 파일(`git --work-tree=studio clean -fd`, `GIT_WORK_TREE`,
  `GIT_TRACE=<파일>`, `GIT_INDEX_FILE`, `GIT_COMMON_DIR`).
- 문서 종류의 기본 앱이 바뀌어 `open`이 그 앱을 실행하는 경우.
- 쓰기 가능한 PATH 폴더(예: `/opt/homebrew/bin`, 또는 명령이 `PATH`에 넣은 폴더)에 명령 이름으로 놓인 프로그램이나,
  에이전트가 직접 빌드해 실행하는 프로그램.

### 가드가 읽을 수 없는 값

- 가드가 읽을 수 없는 경로의 삭제(`rm -rf $X`). 리터럴 끝부분이 studio 루트 아래의 보호 폴더를 가리키면 거부합니다:
  `$X/studio/local`은 거부하지만 `$X/studio` · `./$X/studio` · `<레포>$X/studio`는 아닙니다.
- 보호 이름 뒤나 둘레의 확장을 통한 삭제(`rm -rf studio$X`, `$(ls)studio`, `${:-studio}`, `${X:a}`, `${~X}`,
  `$X:s/…/'…'/`).
- 함수 인자(`f() { rm -rf $1; }; f studio`, `() { … } studio`).
- 보호 대상을 가리키지 않는 텍스트로 명령이 계산하는 값(`X=$(echo c3R1ZGlv | base64 -d)`, `X=$(ls)`), 확장이 바꾸는
  값(`${X/a/b}`, `${(U)X}`), 값이 나온 텍스트가 가드가 읽을 수 없는 확장으로 쓴 값, 16단어를 넘는 값.
- 문자열 값의 슬라이스나 첨자가 보호 이름이 되는 경우(`X=studiox; rm -rf $X[1,6]`, `${X[2,-1]}`).
- rm · rmdir · unlink · touch · mkdir · chmod · trash에서 가드가 아는 값을 zsh가 보호 이름으로 바꾸는 경우
  중 `$~X`를 통한 것(`X='s*o'; rm -rf $~X`). 가드가 알 수 없는 폴더 아래에서도 같습니다
  (`cd $D; X='loca#l'; rm -rf $~X`).
- 셸 전체에서 `GLOB_SUBST`를 켜는 사용자 함수와, 코드를 실행하는 글롭 한정자를 담은 환경 값이나 이전 호출에서 만든
  파일 이름의 조합.
- 가드가 풀지 않는 값을 통한 폴더 이동(`setopt cdablevars`, `pushd`나 `popd` 앞의 `dirstack=(…)`, `cd ~1`,
  `rm -rf ~1/studio`, `cdpath`).
- Studio 레포 안에서 stdin으로 받는 xargs(`xargs rm -rf <<< studio`). here-string이 여럿일 때도 같습니다
  (`xargs rm -rf <<< studio <<< x`).
- 명령의 출력을 그대로 단어로 쓴 경우(`rm -rf $(print studio)`, `rm -rf $(echo stu)dio`)와, 확장이 다른 이름이나
  기본값에서 가져오는 값(X가 설정된 상태의 `${X:-x}`, `${(P)Y}`, `typeset -n R=X`).
- 루프 본문이 사용한 뒤에 바꾸는 값: 다음 회차는 루프 앞의 값으로 판정합니다
  (`X=a; for i in 1 2; do rm -rf $X; X=studio; done`).
- 프로세스 치환이나 here-string이 여럿인 명령의 파이프를 거쳐 셸에 닿는 입력
  (`print 'rm -rf studio' > >(sh)`, `cat <<< x <<< 'rm -rf studio' | sh`).
- 가드가 읽을 수 없는 사용자의 시그널 트랩에, 명령이 그 시그널을 셸에 보내는 경우
  (`TRAPWINCH(){ zle -R }` 뒤의 `kill -WINCH $$`).
- 일어날 수도 안 일어날 수도 있는 폴더 이동 뒤에 루프 목록, `[[ ]]`의 단어, `{ … }`의 리다이렉션에 쓴 `$PWD`
  (`[[ -e x ]] && cd studio; for f in $PWD/*; do rm -rf $f; done`). 명령 안에서 `CDABLE_VARS`를 켠 뒤 없는 폴더로의
  `cd NAME`이 `$NAME`으로 가는 경우(`setopt cdablevars; D=<레포>; cd D && rm -rf studio`).
- 매개변수 값을 통해 대입하는 사용자 함수의 산술식(`x='GIT_DIR=1'`일 때의 `(( x ))`).
- `EXTENDED_GLOB`이 켜진 상태에서 배열 대입 안의 코드를 실행하는 글롭 한정자(`(#qe:…:)`, `(#q+f)`)
  (`setopt extendedglob; x=(*(#qe:'rm -rf studio':))`).
- 명령 자신의 단어 안의 사용자 전역 별칭(`alias -g`)(`alias -g UP='..'`일 때의 `cd UP; rm -rf studio`).
- `argv[N]=`, `N=`, `argv=(…)`로 쓴 위치 매개변수와 `$*[N]`/`$@[N]`
  (`set -- build; argv[1]=studio; rm -rf $1`).
- 앞에 붙은 대입을 그 뒤의 `eval`이나 `sh -c` 문자열이 읽는 경우(`a=studio eval 'rm -rf $a'`).
- zsh가 직접 쓰는 값(`REPLY`, `reply`, `MATCH`, `match`, `OPTARG`)과, 묶인 쌍의 배열 쪽으로 쓴 스칼라 쪽 값
  (`read <<< studio; rm -rf $REPLY`, `path[1]=studio; rm -rf $PATH`).
- X가 설정된 상태의 `${X:+word}`(`rm -rf ${a:+studio}`)와, 대입 뒤에 붙인 대소문자 속성
  (`a=STUDIO; typeset -l a; git checkout $a`).
- zsh가 거부하는 옵션을 준 제거 명령을 함수를 지운 것으로 보는 경우(`unfunction -a f`, `unhash -dfm f`).
- 알려진 값의 조합이 16개를 넘을 때 값으로 만든 git 하위 명령은 이전처럼 판정합니다(`git $a -fdx $b $c $d $e`).
- `source`나 `.` 뒤의 나머지는 0.0.26 규칙만이 그 빈틈과 함께 판정합니다: source 때문에 폴더를 알 수 없는 동안
  git은 검사하지 않고, 셸을 옮기거나 `GIT_DIR`, `HOME`을 export하거나 옵션을 바꾸는 파일은 보지 못합니다
  (`source env.sh; git clean -fdx`, `source env.sh; cd studio/videos/v; git clean -fdx`,
  `source env.sh; rm -f .git/hooks/pre-commit`, `f`에 `setopt globsubst`가 있을 때 `source f; X='s*o'; rm -rf $X`).
  그곳의 와일드카드는 리터럴 부분으로 읽고(`source env.sh; rm -rf stu*`), 셸이 아닌 인터프리터가 실행하는 스크립트는
  읽지 않습니다(`source env.sh; python3 ev.py`). `cd -`, `popd`, `~-`, `$OLDPWD`는 파일이 이를 바꿨더라도 source 전에
  가리키던 폴더로 갑니다(`env.sh`에 `pushd ../scripts; popd`가 있을 때 `cd src; source env.sh; cd -; bash x.sh`).
  셸을 옮길 수 있는, 명령이 정의한 함수는 폴더를 알 수 없게 합니다
  (`f(){ cd studio/videos/v; }; source env.sh; f; git clean -fdx`).
- 가드가 텍스트를 읽을 수 없는 `eval` 뒤의 나머지는 source 뒤처럼 0.0.26 규칙만으로 판정합니다. 흔한 접두가
  그렇습니다: `eval "$(pyenv init -)"`, `eval "$(ssh-agent -s)"`, `eval "$(direnv export zsh)"`,
  `eval "$(brew shellenv)"`. 그래서 레포 밖에서 실행한
  `eval "$(pyenv init -)"; X=<repo>/studio; rm -rf $X/videos/v/work`는 0.0.26처럼 통과합니다. 0.0.28에서 다룰
  예정입니다.
- `git stash pop` 뒤에 다시 실행하는 셸 문자열 속 버리는 git 명령은 호출 전의 작업 트리로 검사합니다
  (깨끗한 트리에서 `zsh -c 'git restore .'; git stash pop; zsh -c 'git restore .'`).
- 가드가 읽을 수 없는 매개변수(환경 변수 등)로 시작해 Studio 이름으로 끝나는 피연산자(`rm -rf $Y/studio`).
- 명령이 정의한 `zsh_directory_name` 함수나 `zsh_directory_name_functions`: zsh는 `~[name]` 단어마다 이를 실행하며,
  가드는 그 동작을 따라가지 않고(`src`에서 `zsh_directory_name(){ cd ..; reply=(.); }; : ~[x]; rm -rf studio`),
  대입의 `=` 뒤에서 주는 폴더도 따라가지 않습니다(`zsh_directory_name(){ reply=(..); }; X=~[x]; rm -rf $X/studio`).

### Studio 레포 밖에서 쓴 형식

- 가드가 읽을 수 없는 단어로 한 폴더 이동과, 그런 폴더 아래에 쓴 파일 중 경로가 Studio가 지키는 것을 하나도
  가리키지 않는 것.
- 리터럴이 아니고 리터럴 부분에 Studio 경로가 없는 셸 문자열.
- 레포를 가리키는 인터프리터 코드: `python3 -c`, `node -e`, `perl -e`, `osascript`, awk, `sh -c "$(printf …)"`,
  리터럴이 아닌 값으로 `functions[…]`에 넣은 함수 본문.
- 거기서 실행한 `sed`의 경우: 스크립트 안의 단순 경로가 아닌 파일 이름, `e`와 셸을 실행하는 명령, 동적이거나
  펼쳐지지 않은 변수.
- 기본값이나 치환에만 적힌 폴더(`cd ${U:-<레포>}`, `env -C ${U:-<레포>}`, `cd`나 `~` 앞의
  `HOME=${HOME/x/<레포>}` · `HOME=${:-<레포>}`).
- xargs와 find 템플릿(`xargs sh -c '…' < /dev/null`, `find … -exec sh -c '…' \;`).
- `eval`, `emulate … -c`, 입력의 `source` 뒤에 파이프나 here-string으로 입력을 받는 셸
  (`eval true; echo 'rm -rf ~/proj/studio' | sh`).
- 다른 프로그램이나 코프로세스를 거친 입력을 읽는 셸(`{ cat | sh } <<< 'rm -rf <레포>/studio'`,
  `coproc sh; print -p …`).
- 레포를 가리키는 문자열을 zsh가 나중에 실행하는 경우: trap 동작(`trap 'rm -rf <레포>/studio' EXIT`),
  `PROMPT_SUBST`가 켜진 프롬프트 문자열(`print -P '$(…)'`, `set -x`와 함께 쓴 `PS4='$(…)'`).
- `hash -d`를 실행할 수 있는 사용자 함수 뒤의 `~이름`(`f <레포>; rm -rf ~w/studio`).
- 레포 폴더 이름 자체에 쓴 글롭 그룹(`rm -rf <rep(o)>/studio`).
- 함수나 source 파일이 돌아갈 때 실행되는 트랩이 셸을 시작 폴더 밖의 폴더로 옮기는 경우
  (다른 폴더에서 실행한 `f(){ trap 'cd ~/proj' EXIT; }; f; rm -rf studio`).
- 가드가 파싱할 수 없는 텍스트는 레포를 리터럴로 가리킬 때만 거부합니다. 다른 방법으로 레포에 닿는 텍스트는
  거부하지 않습니다(파서가 거부하는 형식과 함께 쓴 `HOME=<parent>; rm -rf ~/<name>/studio`).
- 이름에 공백이나 `;&|()<>=:,` 중 하나가 있는 레포 폴더(명령이 가드의 한도를 넘을 때).

### 그 밖의 경우

- `chmod 000 studio`.
- 시작 경로 앞의 find 옵션(`find -L studio -delete`, `find -f studio -delete`).
- 보호 파일 위에 쓰는 아카이브나 압축 해제 파일(`tar -cf <state.json> …`, `gunzip -f <state.json>.gz`).
- 대소문자를 바꿔 쓴 Studio 스크립트 이름(대소문자를 구분하지 않는 볼륨의 `STATE.py approve`).
- 대소문자를 구분하는 볼륨에서 `unsetopt caseglob` 또는 와일드카드 앞부분의 `(#i)` 뒤에 오는 리터럴 부분: 가드는
  볼륨처럼 이름을 비교합니다(`unsetopt caseglob; rm -rf s*/LOCAL`).
- 존재하는 폴더로의 `cd`는 성공한다고 봅니다. `||` 뒤의 명령은 실패할 수 있을 때만 판정합니다
  (`cd src 2>/dev/null || cd studio; rm -rf local`).
- X가 없을 때의 `cd X || exit`(`return`, `logout`도)는 셸이 계속되는 것으로 판정하므로, zsh는 `exit`에서 끝나는데도
  뒤의 `git commit -m x`를 폴더를 알 수 없는 커밋으로 거부할 수 있습니다(`src`가 없는 폴더에서
  `cd src || exit 1; …; git commit -m x`, 사이의 줄이 `pushd`와 `popd`로 셸을 옮길 때).
- EXIT가 아닌 `trap`의 동작이 변수를 담은 문자열이면 그 뒤에서 그 변수의 따옴표 없는 값을 거부합니다
  (`trap "rm -rf $TMPD" INT; echo hi > $TMPD/x`). 따옴표로 감싸세요(`"$TMPD/x"`).
- 실행되지 않았을 수 있는 `pushd` 뒤의 `popd`는 남는 폴더와 따로 스택마다 판정하므로,
  `[[ -e x ]] && pushd studio; popd; rm -rf local`은 zsh가 아무것도 지우지 않는데도 거부합니다.
- 나열한 항목이 500개를 넘는 `**` 와일드카드는 나열 없이 판단합니다. 큰 트리에서는 보호 대상과 맞지 않는 쓰기나
  삭제도 거부할 수 있습니다(`touch **/*.ts`).
- 외부 감사자(`std-auditor`)의 읽기 프로그램 목록에는 옵션이나 두 번째 피연산자로 파일을 쓸 수 있는 프로그램이
  있습니다(`less -o`, `less -O`, `LESS=…`, `tree -o`, 파일 두 개를 준 `xxd`). 값으로 만든 옵션 약어(`sort -$v`)도
  같습니다.
- `eval` 뒤에는 아무것도 바꾸지 않는 리터럴 문자열이라도 git을 거부합니다(`eval "echo hello"; git status`).
- 가드가 알 수 없는 폴더에서는 `-n`과 `list`를 포함해 모든 `git clean`과 `git worktree` 형식을 변경을 버리는 것으로
  칩니다(`take build && cd .. && git clean -n`는 거부).
- 명령이 정의한 함수가 `"$@"`를 프로그램에 넘기면 호출 인자가 리터럴이어도
  거부합니다(`mygit(){ git "$@"; }; mygit status`). 명령을 직접 쓰세요.
- 커밋되지 않은 Studio 변경은 호출이 실행되기 전에 읽습니다: 같은 호출에서 앞선 `git stash pop`이나 `git stash apply`가
  Studio 변경을 되돌려 놓아도 뒤의 `git checkout .`나 `git reset --hard`는 이를 보지
  못합니다(`git reset --hard; git stash pop; git reset --hard`).
- 실행되지 않았을 수 있는 폴더 이동이 길게 이어지고 그 사이에 `cd ~-`나 `cd $OLDPWD`가 있으면 경로 인자가 너무 많다고
  거부될 수 있습니다(G-LIMIT): 각 단어를 셸이 있을 수 있는 모든 폴더에서 판정하기 때문입니다.
- 폴더로 `cd`한 뒤 `cd -`하는 사이에 실패할 수 있는 명령이 있으면 `**` 삭제는 리터럴 부분으로
  판정합니다(`cd src && pytest && cd - && rm -rf **/__pycache__`는 거부).
