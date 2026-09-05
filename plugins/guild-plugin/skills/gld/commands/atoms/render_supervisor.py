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
  - `--tracker` digits-only + the fixed basename + O_NOFOLLOW on the write
    -> containment (no traversal, no chosen name, and the destination is not a symlink).
    The symlink clause is load-bearing, not belt-and-braces: without it a link at
    `.claude/guild/.gld-sprint-99.sh` pointing at `.git/hooks/pre-commit` gets a 139KB
    executable written through it, rc=0, with the stderr contract line naming the in-repo
    path — so `run.md` step 2d approves.
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
import sys

# `commands.*` values are normalized at init time and MUST NOT contain these
# (`init.md`: "They MUST NOT contain `$(...)`, `&&`, `|`, `;`, or redirections").
# The template `eval`s each element and its own header cites that normalisation as the
# reason that is safe. We re-check here because a legacy install can still carry a
# non-normalised value: `_handoff.md` tells the human to split raw compound commands by
# hand, so nothing guarantees the config was ever migrated.
# `$` 도 거부한다. `$(...)` 만 막으면 `yarn install $HOME` 이 통과하는데, 템플릿은 각 원소를
# `eval "$IC"` 로 돌리므로 실행되는 명령이 설정에 적힌 리터럴과 달라진다(인젝션은 아니다 —
# 구분자가 전부 막혀 있다 — 그러나 설정과 실행이 어긋나는 것은 그 자체로 결함이다).
# 어절 첫머리의 `~` 도 같은 이유로 막는다.
# `*`/`?`/`{}` 도 거부한다. 템플릿은 `( cd "$WT" && eval "$IC" )` 로 돌리므로 글롭과 중괄호
# 확장이 워크트리를 상대로 일어나고, 실행되는 명령이 설정 리터럴과 달라진다 — `$`·`~` 를
# 막은 것과 같은 이유다.
_METACHAR = re.compile(r"\$|`|&&|\|\||[|;<>&\n*?{}]|(?:\A|[\s=:])~")

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
                "normalized at init time and must not contain $(...), $VAR, `..`, &&, |, ;, ~, "
                "globs (* ? {}), or redirections" % cmd
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
    # ⚠ 심링크를 따라가지 않는다. 조립 경로가 심링크면 `open(out,"w")` 도 `os.chmod` 도 링크를
    # 따라가므로, `.git/hooks/pre-commit` 을 가리키는 링크 하나로 "숫자 tracker + 고정 파일명이면
    # 산출 경로가 닫힌다" 는 봉쇄 주장이 통째로 무너진다 — 그리고 stderr 계약 줄은 레포 안의
    # 경로를 보고하므로 2d 는 아무것도 눈치채지 못한다. O_NOFOLLOW 로 커널에게 맡긴다
    # (islink 선검사는 TOCTOU 가 남는다).
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o755)
    except OSError as exc:
        if getattr(exc, "errno", None) in (errno.ELOOP, errno.EMLINK):
            die("%s is a symlink; refusing to write through it" % out)
        die("cannot write %s (%s)" % (out, exc))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(src)
        # O_CREAT 의 mode 는 파일이 이미 있으면 무시되므로 명시적으로 다시 건다.
        os.chmod(out, 0o755)
    except OSError as exc:
        die("cannot write %s (%s)" % (out, exc))

    want = len(src.encode("utf-8"))
    try:
        size = os.path.getsize(out)
    except OSError as exc:
        die("cannot stat %s after writing it (%s)" % (out, exc))
    # 0 만 보면 잘린 쓰기가 통과한다 — 515/139621 바이트가 chmod 되고 `bash -n` 도 조용했다.
    # run.md step 2d 가 받는 유일한 신호이므로 전량 일치를 요구한다.
    if size != want:
        die("wrote %d of %d bytes to %s — truncated" % (size, want, out))
    # `run.md`'s render guard reads this line. It is the only signal it gets — there is no
    # allowlisted Bash primitive (`test -s`, `wc -c`) it could use to check the file itself.
    sys.stderr.write("render_supervisor: wrote %s (%d bytes)\n" % (out, size))


if __name__ == "__main__":
    main()
