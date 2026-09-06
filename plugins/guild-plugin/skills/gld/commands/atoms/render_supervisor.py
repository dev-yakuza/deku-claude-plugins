#!/usr/bin/env python3
"""Render the sprint supervisor from its template — one bundled Python invocation.

Replaces the model-mediated "Read the 128KB template, Write it back with 9 substitutions"
step in `sprint/run.md`. The model never reads or writes the template body, which is the
whole point: that round trip cost ~36k input + ~36k output tokens per `/gld sprint run`.

`_bash_rules.md` sanctioned exception 1 ("A single bundled Python invocation") — same shape
as `board_write.py` / `sprint_dag.py` / `persona_migrate.py`.

Design notes and the reasoning behind each guard: design/guild/06-token-reduction.md 묶음 A.

Paths are resolved from __file__, never taken as arguments:
  template    ../../templates/sprint-supervisor.sh
  plugin.json ../../../../.claude-plugin/plugin.json
Both depths hold in the dev checkout and in the installed plugin cache — the two layouts
mirror each other (<root>/.claude-plugin/ + <root>/skills/gld/commands/atoms/).

The output path is ASSEMBLED from --human-repo + --tracker, never accepted as an argument.
A `--out <path>` form would be a hook-free write primitive whose destination the same model
call supplies, i.e. a typo guard dressed as containment. `--out` therefore accepts only the
literal `-` (stdout), which the test harness needs.

Two of the three checks on that assembled path are containment, one is not, and the difference
is stated rather than blurred:
  - `--tracker` digits-only + the fixed basename gives the NAME. That is not containment on
    its own, and O_NOFOLLOW alone does not finish the job either — it constrains the final
    component, and only against a symlink. Four routes reach a different inode, and all four
    are closed at the write, from the descriptor rather than the path:
      symlink at the final component  -> O_NOFOLLOW
      hardlink at the final component -> fstat st_nlink != 1
      symlinked ancestor (.claude or .claude/guild) -> an openat chain: each component is
        opened once with O_NOFOLLOW|O_DIRECTORY and held as a descriptor, and the final
        open uses dir_fd. A realpath() pre-check is NOT enough and was measured losing the
        race 3 times in 47 attempts under load (0 in 4000 on an idle machine, which is how
        it read as closed) — the open re-resolved the path the check had just approved.
        This route is reachable from a clone alone: git stores symlinks (mode 120000), so a
        repo that commits .claude as a link would write outside the checkout on first run.
      FIFO / non-regular file -> O_NONBLOCK + S_ISREG (without O_NONBLOCK the open blocks
        forever waiting for a reader, with no rc and no message).
    chmod and the size check use fchmod/fstat on the open descriptor. The path-based pair
    was a TOCTOU window wide enough to win on the first attempt: the render went to an
    unlinked inode while the renderer chmod'ed the attacker's file 0755 for them.
  - `--human-repo` absolute + existing directory  -> a TYPO GUARD, not containment. The same
    model call supplies the value, so there is no independent standard to check it against; it
    catches a malformed or stale path, nothing more. The design initially left it out for that
    reason; it was added back because the absolute check is load-bearing for a different reason
    (the supervisor never `cd`s and runs in the background, so a relative HUMAN_REPO resolves
    the board/window conf and log dir against an inherited cwd), and the isdir check costs
    nothing once isabs is there.
"""

import argparse
import errno
import json
import os
import re
import shlex
import stat
import sys

# `commands.*` values are normalized at init time and MUST NOT contain these
# (`init.md:163`: "They MUST NOT contain `$(...)` or backticks, `&&`, `||`, `|`, `;`, `&`, newlines, or redirections").
# The template `eval`s each element and its own header cites that normalisation as the
# reason that is safe. We re-check here because a legacy install can still carry a
# non-normalised value: `_handoff.md` tells the human to split raw compound commands by
# hand, so nothing guarantees the config was ever migrated.
# ⚠ 이 집합은 `init.md:163` 의 계약과 **정확히 같아야** 한다 — 그 이상도 이하도 아니다.
#
# 라운드 1~4 에서 리뷰어 제안을 받아 `$VAR`·`~`·글롭(`* ? {} []`)을 차례로 추가했다. 근거는
# "eval 이 확장하면 실행되는 명령이 설정 리터럴과 달라진다" 였는데, **init.md 를 확인하지
# 않았다.** init 이 저장을 금지하는 것은 `$(...)`·백틱·`&&`·`||`·`|`·`;`·`&`·개행·리다이렉션뿐이고, 글롭은
# 명시적으로 허용된다. 그래서 그 추가들은 `eslint src/**/*.ts` 나 `rm -rf build/*` 처럼
# **완전히 정상인 config 를 가진 레포에서 `/gld sprint run` 을 기동 불가**로 만들었다 —
# step 2 가 non-zero 로 끝나고 2d 가 실행을 세우는데, run.md 의 처방(복합 명령 쪼개기)은
# 글롭에 적용되지 않는다. 고치려던 것보다 나쁜 회귀였다.
#
# 진짜 경계는 **어절 확장이 아니라 명령 연쇄·치환** 이다. 글롭·`$VAR`·`~` 는 인자를 바꿀 뿐
# 새 명령을 도입하지 못한다. 아래 목록이 새 명령을 도입할 수 있는 것 전부다.
# `run.md` 의 표가 이 목록을 그대로 적고, `prompt_structure_test.sh` 가 둘의 드리프트를 막는다.
_METACHAR = re.compile(r"\$\(|`|&&|\|\||[|;<>&\n]")

_TRACKER = re.compile(r"\A[0-9]+\Z")
_VERSION = re.compile(r"\A[A-Za-z0-9._+-]+\Z")

# 템플릿에 나타나는 `<UPPER>` 중 **치환 대상이 아닌** 것들. 전부 주석 안의 설명용 자리표시자다.
# 이 집합과 _TOKENS 의 합집합이 템플릿에 존재해도 되는 `<UPPER>` 의 전부이며, 그 밖의 것이
# 하나라도 있으면 렌더는 실패한다 — 템플릿이 이 스크립트가 모르는 자리표시자를 얻었다는 뜻이고,
# 치환 후 검사로는 잡을 수 없다(그 검사는 자기가 방금 치환한 아홉 개만 본다).
_PROSE_TOKENS = frozenset((
    "<TOKEN>", "<TAB>", "<N>", "<PLACEHOLDER>", "<EMPTY>", "<HHMM>",
))

_ANY_TOKEN = re.compile(r"<[A-Z_][A-Z0-9_]*>")

_TOKENS = (
    "<PLUGIN_VERSION>",
    "<TRACKER>",
    "<ORDER>",
    "<OWNER_REPO>",
    "<DEFAULT_BRANCH>",
    "<CONTAINER>",
    "<HUMAN_REPO>",
    "<DAG_PATH>",
    "<INSTALL_CMDS>",
)

_HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.normpath(
    os.path.join(_HERE, "..", "..", "templates", "sprint-supervisor.sh")
)
PLUGIN_JSON = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", ".claude-plugin", "plugin.json")
)


def die(msg):
    sys.stderr.write("render_supervisor: %s\n" % msg)
    sys.exit(1)


def plugin_version():
    """Read the version from plugin.json. A failure is fatal, never a blank watermark.

    The value lands in a header comment that nothing asserts, so a silent empty string
    would be an unobservable defect on a script that outlives the session that made it.
    """
    try:
        with open(PLUGIN_JSON, encoding="utf-8") as fh:
            v = json.load(fh).get("version")
    except (OSError, ValueError) as exc:
        die("cannot read %s (%s)" % (PLUGIN_JSON, exc))
    # `if not v` 만 보면 `"version": 72` 같은 비문자열이 통과해 나중에 str.join 에서 원시
    # 트레이스백으로 죽는다 — 이 모듈이 fatal 을 자기 문구로 내는 이유가 없어진다.
    if not isinstance(v, str) or not v:
        die("'version' in %s must be a non-empty string, got %r" % (PLUGIN_JSON, v))
    # <PLUGIN_VERSION> 은 주석 안에 들어가므로 유일하게 shlex.quote 를 거치지 않는다. 그래서
    # 개행 하나면 주석을 빠져나와 실행 가능한 줄이 된다 — `bash -n` 은 조용하다. 인용을 한 곳에
    # 모은다는 불변조건에서 새는 유일한 값이므로, 여기서 문자 집합으로 닫는다.
    if not _VERSION.match(v):
        die("'version' in %s must match %s, got %r" % (PLUGIN_JSON, _VERSION.pattern, v))
    return v


def array_literal(values):
    """Render a bash array body: shell-quote each element, join with spaces.

    Empty -> "" so the template's `ORDER=()` / `INSTALL_CMDS=()` parse. An empty inline
    substitution used to be a PARSE-time error the template header warns about; producing
    the empty body here is what keeps the empty-queue path (a supported, tested production
    path) working.

    Quoting moves from the model to here. `run.md`'s token table must say the caller passes
    RAW values now — if it still says "shell-quoted", the caller double-quotes and the
    template's `eval "$IC"` looks for a command literally named `yarn install`.
    """
    return " ".join(shlex.quote(v) for v in values)


def main():
    # `--print-template-path` must work on its own — it exists so the test suite can assert
    # that what this script renders is the same file its ~60 structural checks read. Making
    # it wait on the six required scalars would make that assertion unwritable, so it is
    # handled before argparse enforces them.
    # argv 어디에서나 매치하면 값으로 들어온 것도 잡는다 — `--install-cmd --print-template-path`
    # 가 아무것도 렌더하지 않고 exit 0 을 냈다. 유일한 인자일 때만 받는다.
    if sys.argv[1:] == ["--print-template-path"]:
        sys.stdout.write(TEMPLATE + "\n")
        return

    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--tracker", required=True)
    ap.add_argument("--owner-repo", required=True)
    ap.add_argument("--default-branch", required=True)
    ap.add_argument("--container", required=True)
    ap.add_argument("--human-repo", required=True)
    ap.add_argument("--dag-path", required=True)
    ap.add_argument("--order", action="append", default=[])
    ap.add_argument("--install-cmd", action="append", default=[])
    ap.add_argument("--out", default=None, help="only the literal '-' (stdout) is accepted")
    ap.add_argument(
        "--print-template-path",
        action="store_true",
        help="print the resolved template path and exit",
    )
    args = ap.parse_args()

    # 등록만 하고 아무도 읽지 않으면 죽은 플래그가 된다 — 필수 인자와 함께 넘기면 경로를 찍는
    # 대신 조용히 렌더했다. 단독 사용만이 의미 있는 플래그이므로 그렇게 강제한다.
    if args.print_template_path:
        die("--print-template-path must be the only argument")

    if args.out is not None and args.out != "-":
        die("--out accepts only '-' (stdout); the file path is assembled, not passed")

    # ⚠ 출력 경로는 --human-repo + --tracker 로 조립된다. --tracker 만 검증하고 --human-repo 를
    # 놓으면 "임의 디렉터리에 실행 가능한 파일을 쓰는" 원시가 그대로 남는다 — --out 을 없앤 이유가
    # 무색해진다. 상대경로도 막는다: 스크립트는 cd 하지 않고 백그라운드로 뜨므로, 상대 HUMAN_REPO 는
    # BOARD_CONF·WINDOW_CONF·로그 디렉터리를 상속된 cwd 기준으로 해석시킨다.
    if not os.path.isabs(args.human_repo):
        die("--human-repo must be an absolute path, got %r" % args.human_repo)
    if not os.path.isdir(args.human_repo):
        die("--human-repo is not an existing directory: %s" % args.human_repo)

    if not _TRACKER.match(args.tracker):
        die("--tracker must be digits only, got %r" % args.tracker)

    # --order 는 --tracker 와 같은 자료형(이슈 번호)인데 검증이 없었다. `--order ''` 는
    # `ORDER=('')` 를 만들어 템플릿의 빈 큐 가드를 무력화한다 — 길이 1 이므로 가드가 안 걸리고,
    # 슈퍼바이저는 워크트리를 만든 뒤 이슈 번호 "" 로 큐를 돈다.
    for n in args.order:
        if not _TRACKER.match(n):
            die("--order must be digits only, got %r" % n)

    for cmd in args.install_cmd:
        # 빈 값은 `INSTALL_CMDS=('')` 를 만들어 `eval ""` 을 돌린다. 무해하지만 --order '' 를
        # 거부한 것과 같은 이유로 막는다 — 설정에 없는 원소가 배열에 들어가서는 안 된다.
        if not cmd.strip():
            die("--install-cmd must not be empty")
        if _METACHAR.search(cmd):
            die(
                "--install-cmd %r contains shell metacharacters; config.commands values are "
                "normalized at init time and must not contain $(...), `..`, &&, ||, |, ;, &, "
                "newlines, or redirections (init.md:163)" % cmd
            )

    try:
        with open(TEMPLATE, encoding="utf-8") as fh:
            src = fh.read()
    except OSError as exc:
        die("cannot read template %s (%s)" % (TEMPLATE, exc))

    # ⚠ 치환 **전에** 본다. 치환 후에 _TOKENS 만 훑는 검사는 자기가 방금 지운 아홉 개를 다시
    # 확인할 뿐이어서, 템플릿이 얻은 새 자리표시자(`HEARTBEAT_EVERY=<HEARTBEAT>`)를 통과시켰다 —
    # 렌더는 rc=0 에 stderr 계약 줄까지 내고, run.md 2d 는 승인하고, step 5 가 파스 에러 스크립트를
    # 백그라운드로 띄운다. 치환 후 검사로 옮기면 값 안에 `<ORDER>` 가 든 정상 인자를 오진하므로
    # (진단문까지 틀린다) 원본에서 본다.
    unknown = sorted(set(_ANY_TOKEN.findall(src)) - set(_TOKENS) - _PROSE_TOKENS)
    if unknown:
        die(
            "template has placeholder(s) this script does not know: %s — add them to _TOKENS "
            "(substituted) or _PROSE_TOKENS (comment-only)" % ", ".join(unknown)
        )

    # Every scalar is shell-quoted, not dropped into a `X="<TOKEN>"` slot. The template's
    # assignments are bare (`X=<TOKEN>`) so the quoting lives here, in one place, for all of
    # them — the same "remove the class rather than escape it" move `run.md` step 2b made for
    # the board's ten values. Without it, `--default-branch` alone is enough: it comes from
    # `gh repo view --json defaultBranchRef`, git ref rules permit `$`, backtick and quotes,
    # and `DEFAULT_BRANCH="$(id -un)"` executes at script load — before any trap, under set -u.
    # <PLUGIN_VERSION> is the exception: it lands in a `#` comment, never in an assignment.
    subs = {
        "<PLUGIN_VERSION>": plugin_version(),
        "<TRACKER>": shlex.quote(args.tracker),
        "<ORDER>": array_literal(args.order),
        "<OWNER_REPO>": shlex.quote(args.owner_repo),
        "<DEFAULT_BRANCH>": shlex.quote(args.default_branch),
        "<CONTAINER>": shlex.quote(args.container),
        "<HUMAN_REPO>": shlex.quote(args.human_repo),
        "<DAG_PATH>": shlex.quote(args.dag_path),
        "<INSTALL_CMDS>": array_literal(args.install_cmd),
    }
    # 단일 패스. 순차 replace 는 먼저 치환한 값 안에 들어 있던 토큰을 뒤 패스가 다시 치환한다
    # (`--owner-repo '<HUMAN_REPO>'` → OWNER_REPO 가 human-repo 값으로 조용히 바뀌었다).
    src = re.sub("|".join(re.escape(t) for t in subs), lambda m: subs[m.group(0)], src)

    # ⚠ 이 가드는 **입력으로는 도달할 수 없는** 심층 방어다. 위의 사전 검사가 모르는 토큰을
    # 이미 거부하고, 아는 아홉 개는 re.sub 가 전부 바꾸므로, 어떤 인자 조합으로도 여기를
    # 발화시킬 수 없다 — 그래서 스위트에 이 가드만 겨냥한 케이스가 없다(이 가드를 지워도
    # 313/0 그린이다). `0eb3e7e` 의 커밋 메시지가 "네 가지를 전부 덮었다" 고 적은 것은 과장이며,
    # 실제로 덮인 것은 셋이다. 남겨 두는 이유는 정규식 조립이 깨지는 경우(코드 변경) 때문이고,
    # 그 경우는 스위트의 렌더 후 `<UPPER>` 검사가 잡는다.
    # 치환이 실제로 일어났는지. 위의 사전 검사가 "알 수 없는 자리표시자" 를 이미 처리하므로
    # 여기서는 아홉 개가 사라졌는지만 본다. `re.sub` 가 전부 바꿨다면 남을 수 없지만, 정규식
    # 조립이 깨지면 조용히 0건 치환이 된다 — 그 경우를 잡는다. 값 안에 토큰 문자열이 들어 있는
    # 정상 인자(`--owner-repo 'acme/<ORDER>-repo'`)는 이 검사를 오작동시킬 수 있으므로,
    # 치환된 값들이 기여한 것은 빼고 센다.
    injected = "".join(subs.values())
    leftover = [t for t in _TOKENS if src.count(t) > injected.count(t)]
    if leftover:
        die("unsubstituted token(s) remain: %s" % ", ".join(leftover))

    if args.out == "-":
        # stdout IS the script here — the confirmation goes to stderr, or it lands inside
        # the rendered bash and the end-to-end sections execute it.
        # locale 이 아니라 UTF-8 로 고정한다. LC_ALL=C 에서 sys.stdout.write 가
        # UnicodeEncodeError 로 죽으며 0바이트를 남겼다.
        try:
            sys.stdout.buffer.write(src.encode("utf-8"))
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            # ⚠ 커버리지 없음, 기록해 둔다(leftover 가드·파일 인코딩과 같은 부류). `--out -` 는
            # 하니스 전용 경로이고(`run.md` 는 `--out <path>` 형태가 없다고 못박는다) 프로덕션은
            # 조립 경로로만 쓴다. 이 die 를 pass 로 바꿔도 스위트가 그린이다 — 지키는 검사가
            # 없다는 뜻이지, 없어도 된다는 뜻이 아니다.
            die("stdout closed before the render finished")
        # len(src) is CHARACTERS; the template is UTF-8 with multibyte prose, so the two
        # differ by ~4KB. Report what actually lands on the stream.
        sys.stderr.write(
            "render_supervisor: %d bytes to stdout\n" % len(src.encode("utf-8"))
        )
        return

    out = os.path.join(
        args.human_repo, ".claude", "guild", ".gld-sprint-%s.sh" % args.tracker
    )
    # ⚠ 조립 경로로 다른 파일에 도달하는 길은 **넷** 이다. `O_NOFOLLOW` 하나로는 그중 하나만
    # 막힌다 — 마지막 성분이 심링크인 경우뿐이다. 실측으로 나머지 셋이 전부 뚫렸다:
    #   ① 마지막 성분이 심링크        -> O_NOFOLLOW
    #   ② 마지막 성분이 **하드링크**   -> O_NOFOLLOW 무관. `ln`(-s 없이) 하나로 .git/hooks/
    #      pre-commit 에 139KB 가 rc=0 으로 쓰였다. st_nlink 로 본다.
    #   ③ **상위 디렉터리**가 심링크   -> O_NOFOLLOW 는 디렉터리 성분에 적용되지 않고
    #      makedirs 가 따라간다. 이건 클론만으로 도달한다 — git 은 심링크를 저장하므로(120000)
    #      `.claude` 나 `.claude/guild` 를 심링크로 커밋한 레포는 첫 실행에서 체크아웃 **밖**에
    #      0755 파일을 얻는다. realpath 로 조상을 고정한다.
    #   ④ FIFO -> O_WRONLY 가 리더를 기다리며 **영원히 매달린다**(rc 도 메시지도 없다).
    #      O_NONBLOCK + S_ISREG 로 닫는다.
    # 그리고 경로 기반 chmod/getsize 는 TOCTOU 다 — 안전하게 연 fd 를 버리고 경로를 다시
    # 해석하므로, 그 창에서 경로를 심링크로 바꾸면 렌더러 자신이 남의 파일을 0755 로 만든다
    # (실측: 첫 시도에 성공, chmod 탈출만 따로 보면 200/200 재현). fd 로만 다룬다.
    # ⚠ 조상 검사도 **디스크립터로** 한다. `realpath` 로 미리 검사한 판은 경로 검사였고,
    # 그 뒤의 `os.open` 이 `.claude/guild` 를 **다시** 경로로 해석했다 — 그 사이에 그 성분을
    # 디렉터리 ↔ 심링크로 뒤집는 프로세스가 있으면 체크아웃 밖에 0755 실행 파일이 rc=0 으로
    # 쓰인다(실측: 부하 상태에서 47회 중 3회. 한산할 때 4000회 0건이라 "닫혔다" 고 오판했다).
    # openat 사슬은 각 성분을 한 번만 해석하고 그 결과를 fd 로 들고 있으므로 창이 없다.
    if os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd:
        die("this platform lacks openat/mkdirat; the containment guarantee cannot be met")
    dirfds = []
    try:
        try:
            dirfds.append(os.open(args.human_repo, os.O_RDONLY | os.O_DIRECTORY))
        except OSError as exc:
            die("cannot open --human-repo %s (%s)" % (args.human_repo, exc))
        for comp in (".claude", "guild"):
            # ⚠ mkdir 도 dir_fd 로 한다. 예전 판은 검사 **전에** `os.makedirs` 를 돌려, 거부하는
            # 바로 그 경로 밖에 디렉터리를 만들어 놓고 거부했다.
            try:
                os.mkdir(comp, 0o755, dir_fd=dirfds[-1])
            except FileExistsError:
                pass
            except OSError as exc:
                die("cannot create %s under %s (%s)" % (comp, args.human_repo, exc))
            try:
                dirfds.append(
                    os.open(
                        comp,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=dirfds[-1],
                    )
                )
            except OSError as exc:
                if getattr(exc, "errno", None) in (errno.ELOOP, errno.EMLINK, errno.ENOTDIR):
                    die(
                        "%s is a symlink or not a directory; refusing to write outside the "
                        "checkout" % os.path.join(args.human_repo, *(
                            (".claude",) if comp == ".claude" else (".claude", "guild")))
                    )
                die("cannot open %s under %s (%s)" % (comp, args.human_repo, exc))
        try:
            # ⚠ O_TRUNC 를 여기 두지 않는다. open 이 fstat 보다 먼저 일어나므로, 하드링크 검사가
            # 거부하기 **전에** 피해자 파일이 0바이트가 된다(실측: 6바이트 -> 0).
            # 거부는 아무것도 파괴하지 않아야 한다. 검사를 통과한 뒤 ftruncate 한다.
            fd = os.open(
                os.path.basename(out),
                os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o755,
                dir_fd=dirfds[-1],
            )
        except OSError as exc:
            _e = getattr(exc, "errno", None)
            if _e in (errno.ELOOP, errno.EMLINK):
                die("%s is a symlink; refusing to write through it" % out)
            if _e == errno.ENXIO:
                die("%s is a FIFO with no reader; refusing to write to it" % out)
            die("cannot write %s (%s)" % (out, exc))
    finally:
        for d in dirfds:
            try:
                os.close(d)
            except OSError:
                pass

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            os.close(fd)
            die("%s is not a regular file; refusing to write to it" % out)
        if st.st_nlink != 1:
            os.close(fd)
            die("%s is hard-linked (%d links); refusing to write through it" % (out, st.st_nlink))
    except OSError as exc:
        os.close(fd)
        die("cannot stat %s (%s)" % (out, exc))

    # ⚠ 커버리지 없음, 기록해 둔다. 아래 세 곳의 `encoding="utf-8"`(이 fdopen, 템플릿 읽기,
    # plugin.json 읽기)은 지워도 열 스위트가 전부 그린이다. `PYTHONIOENCODING` 은 표준 스트림만
    # 지배하므로 `open()` 의 기본 인코딩을 결정적으로 바꿀 손잡이가 없고(이 상자에서는 `LC_ALL=C`,
    # `PYTHONCOERCECLOCALE=0`, `LC_ALL=en_US.ISO8859-1` 어디서도 preferredencoding 이 utf-8 이었다),
    # 그래서 살아 있는 회귀를 만들 수 없다. stdout 쪽 회귀는 실재했으므로(라운드 2) 이 인자들도
    # 남겨 둔다 — 다만 "테스트가 지킨다" 고 믿지는 말 것.
    try:
        os.ftruncate(fd, 0)   # 검사를 통과한 뒤에야 자른다
        fh = os.fdopen(fd, "w", encoding="utf-8")
        with fh:
            fh.write(src)
            fh.flush()
            # fd 로만 만진다. `os.chmod(out, …)` 는 경로를 다시 해석하므로 그 자체가 임의 파일을
            # 0755 로 만드는 원시가 된다. O_CREAT 의 mode 는 기존 파일에 적용되지 않으므로 필요하다.
            os.fchmod(fh.fileno(), 0o755)
            size = os.fstat(fh.fileno()).st_size
    except OSError as exc:
        die("cannot write %s (%s)" % (out, exc))

    # ⚠ 이 크기 확인은 "이 프로세스가 쓴 바이트가 전부 들어갔다" 를 뜻하지, "지금 그 경로에
    # 있는 파일이 이 렌더다" 를 뜻하지 않는다. 같은 tracker 로 두 렌더가 동시에 돌면 둘 다
    # rc=0 과 계약 줄을 내고 디스크에는 하나만 남는다(실측 40/40; 내용이 섞이지는 않았다).
    # 동시 실행은 상위에서 막힌다 — `run.md` Phase 1 step 3 의 `<!-- guild:sprint:run -->`
    # 중복 실행 가드가 그 역할이고, 여기에 락을 더 두지 않는 이유다.
    want = len(src.encode("utf-8"))
    # 0 만 보면 잘린 쓰기가 통과한다 — 515/139621 바이트가 chmod 되고 `bash -n` 도 조용했다.
    # run.md step 2d 가 받는 유일한 신호이므로 전량 일치를 요구한다.
    if size != want:
        die("wrote %d of %d bytes to %s — truncated" % (size, want, out))
    # `run.md`'s render guard reads this line. It is the only signal it gets — there is no
    # allowlisted Bash primitive (`test -s`, `wc -c`) it could use to check the file itself.
    sys.stderr.write("render_supervisor: wrote %s (%d bytes)\n" % (out, size))


if __name__ == "__main__":
    main()
