# Studio guard: what it judges and what it does not see (0.0.27)

The README gives the summary. This file lists the details. The pre-commit hook, the commit checks and the
person's gates stay behind everything listed here.

## The 0.0.26 guard as a backstop

- Every call is also judged by the guard of 0.0.26, kept unchanged in the plugin. Anything either guard refuses is
  refused. When only the 0.0.26 guard refuses, its message is the one it gave in 0.0.26.
- So 0.0.27 refuses everything 0.0.26 refused, its false refusals too:
  - `**` deletions and writes in a Studio repository (`rm -rf **/__pycache__`, `rm -f **/*.pyc`);
  - reading very many files at once, which can be the 0.0.26 guard's internal error (G-ERR);
  - git or `open` after a shell function of yours whose text mentions studio or that 0.0.26 could not read
    (`gh pr view 1; git commit -m 'studio: v script'`, `diff a.txt src/a.ts; git status`);
  - commands not on `PATH` when there is no shell snapshot (`flock /tmp/build.lock make`).
- These are planned to be lifted in 0.0.28, class by class, together with stronger checks after a source.
- The checks of `git push` and of a Studio commit run once for both guards. A call that needs more time than both
  guards have is refused (G-LIMIT) well before the hook's 20-second limit, which would block it without a message.

## How it judges functions, hooks and options

- **Shell functions of yours** (from the shell snapshot):
  - git is refused after one that may export, set a variable git or the guard reads (`PATH`, `HOME`, `GIT_*`, a
    name already exported), source a file or eval. Examples: an `nvm` or `pyenv` wrapper.
  - A commit, `git config`, git's discarding forms and `open` are refused after one that may change the folder
    (`cd`, `pushd`). The same holds after a folder change the guard cannot follow (`cd -1`, `cd $(mktemp -d)`).
  - Wrappers such as `gh`, `diff` or a prompt helper do not count (`gh pr create --fill && git push` passes), unless
    the 0.0.26 guard refuses them (the backstop above).
- **Hook functions of yours.** A `chpwd` or `TRAP*` function that may change the folder makes the folder unknown for
  every later command. One that exports, or that calls a function the guard cannot read, makes git refused after any
  `cd` (`cd src && git status`). `TRAPEXIT`, and a signal trap the guard cannot read (`TRAPWINCH(){ zle && zle -R }`),
  are taken not to run between commands; a `TRAPDEBUG`, `TRAPZERR` or `command_not_found_handler` it cannot read makes
  the folder unknown.
- **Functions the command defines.**
  - Defining one makes what your snapshot functions do unknown. So does a definition the command may make through
    `eval`, `source`, `autoload` or `functions[…]`, and an autoload stub of yours (`# undefined`).
  - When the command calls a function it defined, what the body exports or assigns applies, with a value the guard
    does not follow. `y(){ export GIT_DIR=/tmp/x; }; y; git commit -m x` is judged like
    `export GIT_DIR=…; git commit -m x`.
  - A call walks the body again from where it is called: in that folder, with the values and prefix assignments in
    effect there (`f(){ rm -rf studio }; cd <repo>; f`, `f(){ rm -rf $X }; X=studio; f`).
  - `function a b { … }` defines every name.
  - A function defined inside another one's body exists once that one is called (`f(){ k(){ cd studio } }; f; k`).
    `functions -c` copies a function the command defined, with its effects; any other copy writes zsh's function
    table and is refused in a Studio repository (`functions -c nvm k`).
  - A function the command removes (`unfunction f`, `unhash -f f`, `unset -f -- f`, `disable -f f`, a `-m` pattern)
    is gone for later calls: the name then runs the command so named (`git(){ :; }; unfunction git; git clean -fdx` is
    judged as `git clean -fdx`). One that may or may not be removed (`[[ -e x ]] && unfunction f`) is judged both ways.
    After code that may remove or replace it in a way the guard does not follow — an `eval` or `emulate … -c` string,
    a sourced file, a definition under a name it cannot read (`$n(){ … }`), a function or a
    `DEBUG`/`ZERR` hook it cannot read, a command word it cannot read — a call is judged as before such functions were
    followed: the folder and the values the call may write are unknown, and the command so named is judged too
    (`f(){ cd /tmp; }; eval 'f(){ :; }'; f; rm -rf studio` is refused).
- **Hooks the command defines.** `chpwd`, `TRAPDEBUG`, `TRAPZERR`, a `TRAP<signal>` function,
  `command_not_found_handler`, `trap … DEBUG`, `trap … ZERR`, a trap on a signal (`trap … INT TERM`) and
  `chpwd_functions=(…)` may run between later commands. What the hook may do holds from there on: the folder is unknown
  when it may change it or when the guard cannot read it, and a value it may assign is one of the old or new values. A
  trap action that names a function the command defined is read as that function
  (`cleanup(){ rm -f $tmp; }; trap cleanup INT TERM` changes nothing), also when the command defines it again later.
  A `trap … EXIT` (or `0`) and `TRAPEXIT` set outside a function run when the shell ends, after every command of the
  call, so later commands keep their folder and values (`trap 'cd /' EXIT; rm -rf $PWD/studio` is refused;
  `cleanup(){ rm -f $tmp; }; trap cleanup EXIT; git commit -m x` passes). Set inside a function, an EXIT trap runs
  when the function returns and counts as a hook. `precmd`, `preexec`, `periodic`, `zshaddhistory` and `zshexit` (and
  their `*_functions` arrays) never run between the Bash tool's commands. The action's text is searched as before.
- **Files the command sources.** After a `source` or `.` the rest of the call is judged by the 0.0.26 rules only (the
  backstop above); stronger checks there are planned for 0.0.28.
  - The same holds when the source is reached through an alias the command defines, `builtin`, `command` or
    `noglob`, a function the command defines and calls, or an `eval` or `emulate … -c` string that may run one.
    It also holds after an `eval` whose text the guard cannot read (`eval "$(pyenv init -)"`).
  - Code before the source is judged as usual, and so is code the call itself gives the source: its input
    (`source /dev/stdin <<< …`, a heredoc) or a file the call wrote. `{ source /dev/stdin } <<< 'rm -rf studio/local'`
    is refused.
  - A source inside a subshell, a branch, a loop or a pipeline also ends the stricter checks for the rest of the
    call: `if [[ -n $CI ]]; then source ci.sh; else rm -rf studio/local; fi` is judged by the 0.0.26 rules (refused).
  - A function that sources and is never called does not end them. Nor does a `chpwd` function or a trap that
    sources: its body is read where it is defined.
  - This guard does not read your file; the 0.0.26 guard searches its text as it did.
- **Dynamic named directories.** zsh resolves `~[name]` through a `zsh_directory_name` function or
  `zsh_directory_name_functions`, which the command, a sourced file or an `eval` may define; the guard does not run
  them. In a Studio repository a `~[name]` path that a command deletes or writes is refused, and `cd ~[name]` makes
  the folder unknown.
- **`NULLCMD`/`READNULLCMD`** set to anything but a pager make a command of redirections only run its input as shell
  code: a here-string, a heredoc, a `<` file, or the pipe it stands in (`print … | > /dev/null`, `… | < /dev/stdin`).
- **Input.** A here-string, heredoc, `<` file or pipe given to `{ … }`, `( … )`, a loop, an `if`, or a function the
  command defines is read by every command in it (`{ sh } <<< …`, `f <<< …`). `exec <<< …` and `exec 3< f` hold for
  later commands, and `<&3` reads what fd 3 holds (`exec 3<<< …; sh <&3`). A shell reading an input the guard cannot
  tell (`sh <&3` of an fd it does not know) is refused in a Studio repository. An `eval` string or a `-c` string runs
  with its command's input (`eval sh <<< …`, `zsh -c sh <<< …`), and a function an `eval` string defines is read with
  the input it is called with (`eval 'f(){ sh }'; f <<< …`). Several input redirections on one command, and a pipe
  with one, are all read in order, as zsh's `MULTIOS` does (`sh <<< … <<< x`, `sh <<< … < /dev/null`,
  `echo … | sh <<< x`). `<>` on stdin counts as an input too (`sh <<< … <> /dev/null`).
- **`set` flags and the snapshot's options.** `set` flags are read one letter at a time (`set -euo pipefail`,
  `set -ex`, `set +eu`); `-o NAME` names an option. A letter the guard does not know (`set -r`) makes the options
  unknown. An option your snapshot's `setopt` list leaves out is at zsh's default (`AUTO_PUSHD` off); with no snapshot
  `AUTO_PUSHD` may be on or off, and `popd` after `cd` is judged both ways.
- **Unquoted `$X`** (also `$X[1]`, `$X:t`, `$1`, `$@`, `$_`):
  - After an `eval`, or a function that may turn on an option that changes words (`GLOB_SUBST`, `SH_WORD_SPLIT`, …)
    without `LOCAL_OPTIONS`, or a function the guard cannot read, it is refused when the command may have set the
    value itself. That is: the command assigns or reads it, under any of its names (`PS1`/`PROMPT`,
    `cdpath`/`CDPATH`, a `typeset -T` pair, `$aliases[…]`); it loops over file names; or it gave such a function a
    word the guard cannot read, the variable's name, stdin or a file it wrote.
  - A value only your environment sets is judged as before by programs that read their words the same wherever they
    stand (`ls`, `cat`, `grep`, `echo`, …). For other programs an unquoted value is refused after a function the
    guard cannot read, because the words may split (`nvm use 20; cp $X /tmp/y`).
  - `[[ ]]`, `case`, scalar assignments and `${#X}` are judged as before. Array values (`W=($X)`,
    `typeset -a W=($X)`) are file names.
  - While `GLOB_SUBST` may be on, the parts of one word are checked together (`$X$Y`, `${X}'…'`), and a part whose
    text the guard cannot compute next to a value holding `(` is refused (`${X:&}`, `$X:s/…/'…'/`). `0=…` and
    `1=…` are assignments, so `$0` counts as set by the command. Setting any positional parameter (`2=…`,
    `argv[2]=…`, `set --`) counts for all of them (`$@`, `$*`, `$argv`, and after `shift`). `$~1`, `$=1` and `$~@`
    are pattern expansions like `${~1}`.
  - A known value that `GLOB_SUBST` or `SH_WORD_SPLIT` may turn into a pattern or several words (`setopt globsubst`,
    `set -y`) is judged as a whole and word by word.
- **Values the guard does not carry as one string**: an array (`X=(studio)`), `read`, `print -v`, `set -A`,
  `set --` with `$1`, `$(print …)`, a `for` variable, a global that a function of the command assigns, and a value
  that differs between the folders the command may run in. Where such a value is deleted or written, each value it
  may hold is judged, from the words of the text it came from (`X=(studio); rm -rf -- $X` is refused,
  `files=(a b); rm -f $files` passes). For a value a command computes (`X=$(ls studio)`), a word of that command that
  names something Studio protects is judged as a value.
  A word that is one of a few known values the command assigned (none empty, none with a blank, a wildcard, a quote
  or another shell character; not `$PWD` or `$OLDPWD`; `GLOB_SUBST` and `SH_WORD_SPLIT` off) makes the command judged
  once per value, at most 16 readings, each as if written
  (`if [[ -e x ]]; then B=develop; else B=main; fi; git checkout $B`; `cd $D` goes to each folder). The readings are
  alternatives, not steps: a recursive copy in one does not come before a write in another
  (`if [[ -n $CI ]]; then OUT=dist; else OUT=build; fi; cp -r src/* $OUT/` passes). With more than 16 combinations
  the words are judged as words the guard cannot read; in a Studio repository a command with more than three of them
  is refused with a message that names the limit (write the values literally or split the command). For the external
  auditor (`std-auditor`) every reading must only read. One element of an array (`$A[k]`) is one of its values; a
  slice or a subscript of a string, or a modifier (`$X[2,-1]`, `${X:1}`, `$X:t`), gives part of a value: its
  candidates are never taken as exact.
- **Glob groups.** In a Studio repository a word that zsh expands to file names is refused when it has a glob group
  `(…)` (`ls *(.)`, `ls (a|b).txt`). The Bash tool runs zsh with `BARE_GLOB_QUAL` off, so `*(.)` is a pattern
  (`studi(o)` matches `studio`), not a glob qualifier. A regular expression after `=~` in `[[ ]]` is no glob group
  (`[[ $b =~ ^feature/(.*)$ ]]`). Nor is the pattern after `==`, `=` or `!=` in `[[ ]]`, which names no files
  (`[[ $x == (a|b) ]]`); the rest of the command is judged as usual. Nor are `case` patterns
  (`case $f in *.(ts|tsx)) …`, `case $x in (#i)y) …`); the commands of each branch are judged.
  After `;&` or `;|` the next branch may run where the one before left the shell.
- **zsh's short forms** (`for i in x; cmd`, `for ((…)) cmd`, `while … { … }`, `if … { … }`, `case x { … }`) are
  refused in a Studio repository: write `do … done`, `then … fi` and `in … esac`. A condition or loop head the guard
  cannot parse is refused the same way.
- **Extended glob.** While `EXTENDED_GLOB` may be on, `^`, `~` and `#` are read as zsh reads them (a `~` that ends a
  name is a letter). A word is refused when it may match a protected name: `setopt extendedglob; cd $D; rm -rf ^x`
  is refused; `touch notes#1`, `cp a.txt a.txt~` and `rm -f *~` pass. In a bracket expression they are letters, as is
  `/`, and its `!`/`^`, a leading `]`, ranges and `[:class:]` are read as zsh 5.9 reads them (`[s~]tudio` and
  `[s/]tudio` match `studio`).
- **Numeric globs and `GLOB_STAR_SHORT`.** zsh reads `<N-M>` (`<->`, `<5->`) as part of a word, also inside `[…]`
  and after `^`. It matches one or more digits whose number is in the range: `mv frame<1-9>.png src/` passes, and
  `rm -rf studi[o<->]` is refused (in a bracket, `<`, `-` and `>` are letters); `< file`
  and the other redirections stay redirections. While `GLOB_STAR_SHORT` may be on, `**x` is read as `**/*x`
  (`setopt globstarshort; rm -rf **local` is refused).
- **Commands that may fail.** A redirection that may fail to open (a file, `$X`, a wildcard, `>&3`) skips its
  command, also a builtin, a function or `{ … }`. So `cd /tmp > /x/y; rm -rf studio` is judged in the starting folder,
  and `true > /x/y || rm -rf studio` is refused. `/dev/null`, `2>&1`, here-strings and heredocs do not count. While
  `PIPEFAIL` may be on, an earlier command of a pipeline can make it fail (`false | true || …`).
- **Code that may or may not run.** A value written by code that may not run — a branch of `if` or `case`, a part
  after `&&` or `||`, a loop body, a command whose redirection may fail, `${X:=…}` or `${X=…}`, `read`, a write in a
  function after `return` or on a branch, a function whose definition may not have run, `eval`, a hook — is one of the
  old and new values, each judged where the value is deleted or written
  (`X=studio; [[ -e x ]] && X=a; rm -rf -- $X` is refused). After `eval` or a function the guard cannot read, the
  values the command set stay candidates. A name a function declares `local` (also `typeset`, `declare`, `private`,
  `integer` or `readonly` without `-g`) before writing it is the function's own: after the call the caller's value is
  back (`X=studio; f(){ local X=a }; f; rm -rf -- $X` is refused).
- **A folder change that may or may not happen** (such a redirection, `[[ … ]] && cd x`, a branch of `if` or `case`):
  git, `$PWD`, `~+`, `$(pwd)` and `git rev-parse --show-toplevel` are judged in each folder the command may run in
  (`cd studio > out.log; git clean -fdx` is refused). A commit that may run in more than one Studio repository is
  refused. After a `pushd` or `cd` that may not have run, the directory stack is one of the stacks it may be and
  `$OLDPWD` one of the folders it may hold. `cd -`, `cd ~-`, `cd $OLDPWD`, `pushd ~-`, `env -C ~-` and a copy such as
  `X=$OLDPWD; cd $X` go to each of them, and `$OLDPWD/studio` names the path in each
  (`pushd src; pushd $X; rm -rf $OLDPWD/studio` is refused). `popd` is judged on each stack (on an empty one it fails
  and the shell stays where it is: `pushd src && make && popd; git commit -m x` passes when `src` is missing). A `pushd`
  the guard cannot follow (`pushd $X`, a wildcard, `pushd -`) pushes the folder it leaves, and one that rotates the
  stack (`pushd +1`) leaves the stack unknown, so a later `popd` may succeed (`pushd $X && popd && rm -rf studio` is
  refused). When the folder becomes one the guard cannot tell, each later command is judged in the folders the shell may
  still be in as well as in a folder the guard cannot tell, and `$PWD`, `~+`, `$(pwd)` and
  `$(git rev-parse --show-toplevel)` there are judged as that folder itself (`cd $X > out.log; rm -rf $PWD/studio` is
  refused).
- **Wildcards and Studio's hook files.** A wildcard that may match an installed hook file (`.git/hooks/pre-commit`,
  `.husky/pre-commit`, `lefthook-local.yml`, Studio's runner folder) or git's settings of the repository, or for a
  recursive delete a folder above one, is refused (`cp /tmp/x .git/hooks/pre-commi?`, `rm -rf .git/h*`). Git's
  settings count even with no hook installed, so `rm -rf .git/*` is refused.
- **`pushd`** with no word and an empty stack goes to `$HOME`, as `cd` does.
- **`$HOME` written by the command** in any way before `cd`, `pushd` or a `~` word of any command (`${HOME::=…}`,
  `${HOME:=…}`, `for HOME in …`, `read HOME`): a literal value is followed, also one made of variables the guard knows
  (`X=<repo>; : ${HOME::=$X}`); otherwise the text it came from, with those variables filled in, is searched for
  Studio repositories, as a `cd $D` target is, and the path after the `~` is judged as under a folder the guard cannot
  tell. `~-` and `~+` are zsh's own previous and current folders: writing `$OLDPWD` or `$PWD` does not change them.
  A `HOME=…` prefix or `env HOME=…` holds for the strings and functions the command runs
  (`HOME=<repo> eval 'rm -rf ~/studio'`, `HOME=<repo> sh -c '…'`), and an `eval` or `source` may write `$HOME`.
- **A command the guard cannot parse** is refused in a Studio repository when it assigns a variable the guard follows
  (`GIT_DIR`, `PATH`, …) or one the command expands later (`GIT_DIR=/tmp/x; echo 'unterminated`). It is also refused
  there when it has a glob group or names a command that deletes, moves or writes files or runs code (`rm`, `mv`,
  `cp`, `git`, `sh`, …; `[[ a == (a|b)|c ]]; rm -rf s*`). Such a command counts however it is written: as a path
  (`/bin/rm`), as `=rm`, with quotes or backslashes (`r''m`), through an expansion (`${:-rm}`, `$X`), or as an alias or
  function of yours whose text runs one. A write redirection (`>`, `>|`, `>>&!`, `&>|`, …) counts too. zsh's forms
  `time;`, `! ;`, `coproc ;`, the `;|` branch end and the redirections `>&|`, `>>&`, `&>>|` are read as usual.
- **In a Studio repository**, a command too long for the guard's limits is refused, also one whose functions call each
  other too many times (`f1(){ f0; f0; }; f2(){ f1; f1; }; …`).
- **Outside a Studio repository**, a command too long for the guard's limits is refused unless nothing in it can name a
  repository: no path, expansion, wildcard, folder change, hook, or alias or function that may change folder. With no
  shell snapshot, any such command is refused.

## What the guard does not see

### Programs and settings that run commands the guard does not model

- Any program that runs other commands in a way the guard does not model. The guard reads the common runners (env,
  nohup, nice, timeout, time, script, flock, xargs, npx, …). In a Studio repository it refuses the runners it knows it
  cannot read (su, chroot, expect, tmux, …) and command-valued options (`git -c core.editor`, `ssh -o ProxyCommand`,
  …). No list is complete.
- awk programs and vim, ex or ed scripts; `parallel` and the commands it feeds.
- What a package runner runs in turn (`npx sh -c …`, `npx git stash -a`, `npm exec -- chronic rm …`).
- Settings other tools keep outside the repository and read later: a `LESSOPEN` already in your environment,
  `~/.npmrc`, shell start-up files, vim's `~/.vimrc`, `~/.exrc` and `~/.vim/`, `~/.ExifTool_config`. Git's and ssh's
  user config files are guarded, but not the files they pull in (`[include]`, `Include`).
- Command-valued settings outside the guard's lists: `make --eval`, `MANOPT`, git's `man.*.cmd`,
  `core.alternateRefsCommand`, `mergetool.*.path` and `submodule.*.update`, ssh's `-o PKCS11Provider` and `-I`,
  `ZDOTDIR`, `LD_PRELOAD`/`DYLD_*`, `NODE_OPTIONS`, `PERL5OPT`, `bun exec`/`bun run`.
- Git keys that run commands outside its list (`gpg.ssh.defaultKeyCommand`, `interactive.diffFilter`,
  `difftool.*.path`).
- More programs and variables that run code: `BASH_ENV`, `RUBYOPT`, `PYTHONPATH`, `PYTHONSTARTUP` and `PYTHONHOME`
  (also for Studio's own scripts), `MAKEFILES`, `make -f <file>`, `TAR_OPTIONS`, `ZIPOPT`, lesskey files,
  `launchctl asuser`/`bsexec`.
- Programs named by other options: `sftp -D`, ssh's `-o SecurityKeyProvider`, `MAKEFLAGS='SHELL=…'`, tar's
  `--rsh-command` and `--rmt-command`, `git instaweb --httpd`/`-d`, `git web--browse -b`.
- For a program the guard does not model:
  - wildcards and folders above Studio's (`watchexec -- rm -rf stu*`, `.claude`, `.`);
  - `--option=command` words (`foo --exec='rm -rf studio'`);
  - a protected name in its string split by quotes or backslashes, or reached through braces, `$PWD` or a variable
    (`watchexec "rm -rf stu''dio"`, `watchexec 'X=studio; rm -rf $X'`).
- Git with a work tree or files in Studio's folders set through its options or environment
  (`git --work-tree=studio clean -fd`, `GIT_WORK_TREE`, `GIT_TRACE=<file>`, `GIT_INDEX_FILE`, `GIT_COMMON_DIR`).
- A changed default app for a document type that `open` then starts.
- A program placed under a command's name in a folder on PATH that you can write to (for example
  `/opt/homebrew/bin`, or a folder the command puts on `PATH`), or any program the agent builds and runs itself.

### Values the guard cannot read

- A deletion of a path the guard cannot read (`rm -rf $X`), unless its literal end names a protected folder below the
  studio root. `$X/studio/local` is refused; `$X/studio`, `./$X/studio` and `<repo>$X/studio` are not.
- A deletion through an expansion after or around a protected name (`rm -rf studio$X`, `$(ls)studio`, `${:-studio}`,
  `${X:a}`, `${~X}`, `$X:s/…/'…'/`).
- A function's arguments (`f() { rm -rf $1; }; f studio`, `() { … } studio`).
- A value a command computes from text that does not name the protected thing (`X=$(echo c3R1ZGlv | base64 -d)`,
  `X=$(ls)`), one an expansion changes (`${X/a/b}`, `${(U)X}`), one the text it came from spells with an expansion
  the guard cannot read, and a value of more than 16 words.
- A slice or a subscript of a string value that gives a protected name (`X=studiox; rm -rf $X[1,6]`, `${X[2,-1]}`).
- For rm, rmdir, unlink, touch, mkdir, chmod and trash: a value the guard knows that zsh turns into a protected name
  through `$~X` (`X='s*o'; rm -rf $~X`), also under a folder the guard cannot tell (`cd $D; X='loca#l'; rm -rf $~X`).
- A function of yours that turns `GLOB_SUBST` on for the whole shell, together with a value in your environment, or a
  file name made in an earlier call, that holds a glob qualifier running code.
- Folder changes through values the guard does not resolve (`setopt cdablevars`, `dirstack=(…)` before `pushd` or
  `popd`, `cd ~1`, `rm -rf ~1/studio`, `cdpath`).
- xargs fed from stdin in a Studio repository (`xargs rm -rf <<< studio`), also by several here-strings
  (`xargs rm -rf <<< studio <<< x`).
- Command output used directly as a word (`rm -rf $(print studio)`, `rm -rf $(echo stu)dio`), and a value an
  expansion takes from another name or a default (`${X:-x}` while X is set, `${(P)Y}`, `typeset -n R=X`).
- A value a loop body changes after using it: the next pass is judged with the value from before the loop
  (`X=a; for i in 1 2; do rm -rf $X; X=studio; done`).
- Input reaching a shell through a process substitution or a pipe from a command with several here-strings
  (`print 'rm -rf studio' > >(sh)`, `cat <<< x <<< 'rm -rf studio' | sh`).
- A signal trap of yours the guard cannot read, when the command makes that signal reach the shell
  (`kill -WINCH $$` after `TRAPWINCH(){ zle -R }`).
- `$PWD` in a loop list, a `[[ ]]` word or a redirection of `{ … }` after a folder change that may or may not happen
  (`[[ -e x ]] && cd studio; for f in $PWD/*; do rm -rf $f; done`), and with `CDABLE_VARS` set in the command, `cd NAME`
  to a missing folder followed to `$NAME` (`setopt cdablevars; D=<repo>; cd D && rm -rf studio`).
- An arithmetic expression in a function of yours that assigns through a parameter's value (`(( x ))` with
  `x='GIT_DIR=1'`).
- A glob qualifier that runs code (`(#qe:…:)`, `(#q+f)`) in an array assignment while `EXTENDED_GLOB` is on
  (`setopt extendedglob; x=(*(#qe:'rm -rf studio':))`).
- Global aliases of yours (`alias -g`) among the command's own words (`cd UP; rm -rf studio` with `alias -g UP='..'`).
- A positional parameter written by `argv[N]=`, `N=` or `argv=(…)`, and `$*[N]`/`$@[N]`
  (`set -- build; argv[1]=studio; rm -rf $1`).
- A prefix assignment read by the `eval` or `sh -c` string it precedes (`a=studio eval 'rm -rf $a'`).
- Values zsh writes itself (`REPLY`, `reply`, `MATCH`, `match`, `OPTARG`), and the scalar side of a tied pair written
  through its array (`read <<< studio; rm -rf $REPLY`, `path[1]=studio; rm -rf $PATH`).
- `${X:+word}` while X is set (`rm -rf ${a:+studio}`), and case attributes applied after the assignment
  (`a=STUDIO; typeset -l a; git checkout $a`).
- A removal command with an option zsh rejects, taken to have removed the function (`unfunction -a f`,
  `unhash -dfm f`).
- With more than 16 combinations of known values, a git subcommand built from a value is judged as before
  (`git $a -fdx $b $c $d $e`).
- After `source` or `.` the 0.0.26 rules alone judge the rest of the call, with their gaps: git is not checked while
  the folder is unknown because of the source, and a file that moves the shell, exports `GIT_DIR` or `HOME`, or sets
  options is not seen
  (`source env.sh; git clean -fdx`, `source env.sh; cd studio/videos/v; git clean -fdx`,
  `source env.sh; rm -f .git/hooks/pre-commit`, `source f; X='s*o'; rm -rf $X` with `setopt globsubst` in `f`); a
  wildcard there is read by its literal parts (`source env.sh; rm -rf stu*`), and a script run by an interpreter other
  than a shell is not read (`source env.sh; python3 ev.py`). `cd -`, `popd`, `~-` and `$OLDPWD` go to the folder they
  named before the source, also when the file changed them (`cd src; source env.sh; cd -; bash x.sh` with
  `pushd ../scripts; popd` in `env.sh`), and a function the command defines that may move the shell leaves the folder
  unknown (`f(){ cd studio/videos/v; }; source env.sh; f; git clean -fdx`).
- After an `eval` whose text the guard cannot read, the rest of the call is judged by the 0.0.26 rules only, as after
  a source. Common prefixes do this: `eval "$(pyenv init -)"`, `eval "$(ssh-agent -s)"`,
  `eval "$(direnv export zsh)"`, `eval "$(brew shellenv)"`. So
  `eval "$(pyenv init -)"; X=<repo>/studio; rm -rf $X/videos/v/work` run from outside the repository passes, as in
  0.0.26. Planned for 0.0.28.
- A discarding git command in a shell string run again after `git stash pop` is checked against the work tree as it
  is before the call (`zsh -c 'git restore .'; git stash pop; zsh -c 'git restore .'` on a clean tree).
- An operand that starts with a parameter the guard cannot read, such as an environment variable, and ends in a Studio
  name (`rm -rf $Y/studio`).
- A `zsh_directory_name` function or `zsh_directory_name_functions` that the command defines: zsh runs it for each
  `~[name]` word, and the guard does not follow what it does
  (`zsh_directory_name(){ cd ..; reply=(.); }; : ~[x]; rm -rf studio` from `src`) or the folder it gives after `=`
  in an assignment (`zsh_directory_name(){ reply=(..); }; X=~[x]; rm -rf $X/studio`).

### Forms used from outside a Studio repository

- A folder change through a word the guard cannot read, and a file written under such a folder when its path names
  nothing Studio protects.
- A shell string that is not literal and names no Studio path in its literal parts.
- Interpreter code that names the repository: `python3 -c`, `node -e`, `perl -e`, `osascript`, awk,
  `sh -c "$(printf …)"`, and a function body set through `functions[…]` that is not literal.
- For a `sed` run there: a file name in its script that is not a plain path, its `e` and shell-run commands, and
  dynamic or unexpanded variables.
- A folder named only in a default value or a substitution (`cd ${U:-<repo>}`, `env -C ${U:-<repo>}`,
  `HOME=${HOME/x/<repo>}` or `HOME=${:-<repo>}` before `cd` or `~`).
- The templates of xargs and find (`xargs sh -c '…' < /dev/null`, `find … -exec sh -c '…' \;`).
- After an `eval`, an `emulate … -c` or a `source` of input, a shell fed from a pipe or a here-string
  (`eval true; echo 'rm -rf ~/proj/studio' | sh`).
- A shell whose input passes through another program or a coprocess (`{ cat | sh } <<< 'rm -rf <repo>/studio'`,
  `coproc sh; print -p …`).
- Code zsh runs later from a string that names the repository: a trap action (`trap 'rm -rf <repo>/studio' EXIT`),
  prompt strings with `PROMPT_SUBST` (`print -P '$(…)'`, `PS4='$(…)'` with `set -x`).
- `~name` after a function of yours that may run `hash -d` (`f <repo>; rm -rf ~w/studio`).
- A glob group in the repository folder's own name (`rm -rf <rep(o)>/studio`).
- A trap that runs when a function or a sourced file returns and moves the shell to a folder outside the starting one
  (`f(){ trap 'cd ~/proj' EXIT; }; f; rm -rf studio` run from another folder).
- Text the guard cannot parse is refused there only when it names a repository literally; text that reaches one
  another way is not (`HOME=<parent>; rm -rf ~/<name>/studio` together with a form the parser rejects).
- A repository folder whose name holds a space or one of `;&|()<>=:,`, when a command is too long for the guard's
  limits.

### Other

- `chmod 000 studio`.
- find's options before its start paths (`find -L studio -delete`, `find -f studio -delete`).
- An archive or an unpacked file written over a protected file (`tar -cf <state.json> …`,
  `gunzip -f <state.json>.gz`).
- A Studio script named in another letter case (`STATE.py approve` on a case-insensitive volume).
- `unsetopt caseglob`, or `(#i)` in an earlier part of a wildcard, before a literal part, on a volume that tells
  letter case apart: the guard compares names as the volume does (`unsetopt caseglob; rm -rf s*/LOCAL`).
- A `cd` into a folder that exists is taken to succeed: the commands after `||` are judged only when it may fail
  (`cd src 2>/dev/null || cd studio; rm -rf local`).
- `cd X || exit` (also `return` or `logout`) where X is not there is judged as if the shell went on, so a later
  `git commit -m x` may be refused as one whose folder cannot be told although zsh ends at `exit`
  (`cd src || exit 1; …; git commit -m x` from a folder without `src`, when the lines between move the shell with
  `pushd` and `popd`).
- After a `trap` other than EXIT whose action is a string holding a variable, an unquoted value of that variable is
  refused (`trap "rm -rf $TMPD" INT; echo hi > $TMPD/x`); quote it (`"$TMPD/x"`).
- A `pushd` that may not have run followed by `popd` is judged on each stack apart from the folder it leaves, so
  `[[ -e x ]] && pushd studio; popd; rm -rf local` is refused although zsh deletes nothing.
- A `**` wildcard over more than 500 listed entries is judged without listing. In a large tree it may refuse a write
  or a deletion that matches nothing protected (`touch **/*.ts`).
- The external auditor's (`std-auditor`) reader list includes programs that can write a file through an option or a
  second operand (`less -o`, `less -O`, `LESS=…`, `tree -o`, `xxd` with two files), and an option abbreviation built
  from a value (`sort -$v`).
- git is refused after any `eval`, also of a literal string that changes nothing (`eval "echo hello"; git status`).
- In a folder the guard cannot tell, every `git clean` and `git worktree` form counts as discarding, including `-n`
  and `list` (`take build && cd .. && git clean -n` is refused).
- A function the command defines that passes `"$@"` to a program is refused even when the call's arguments are literal
  (`mygit(){ git "$@"; }; mygit status`); write the command itself.
- Uncommitted Studio changes are read before the call runs: a `git stash pop` or `git stash apply` earlier in the same
  call that brings Studio changes back is not seen by a later `git checkout .` or `git reset --hard`
  (`git reset --hard; git stash pop; git reset --hard`).
- A long chain of folder changes that may not run, with `cd ~-` or `cd $OLDPWD` between them, may be refused as having
  too many path arguments (G-LIMIT): each word is judged in every folder the shell may be in.
- After `cd` into a folder and `cd -` with a command between them that may fail, a `**` deletion is judged by its
  literal parts (`cd src && pytest && cd - && rm -rf **/__pycache__` is refused).
