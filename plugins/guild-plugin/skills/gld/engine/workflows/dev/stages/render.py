"""workflows.dev.stages.render — the bodies of `<!-- guild:test:output -->` and `<!-- guild:qa:output -->`.

Contract (C §1.2, §4.2, §6.1): line 1 the marker; the closing marker last; inside —
* test:output: the raw runner tail (scrubbed — INV5), the pass/fail summary, the AC coverage, the
  **검증 범위** block (a)–(d) with the `<!-- guild:visual-baselines -->` and
  `<!-- guild:safety-net-evidence -->` blocks copied VERBATIM from the execute evidence (L.3 —
  qa and review read them from here), the E2E string (one of the two literals), and on the
  attended fail path `loopback-reason:` / `loopback-signature:` (ASCII keys, CR-M10);
* qa:output: QA 계획 & 결과, UI/UX 게이트, honesty of scope, `### PR CI` (one line), the optional
  `사람 지시 적용:` line, `ran-at: <ts>` (C5 — review reads it before `updated_at`), the attended
  `loopback-*` lines.
Redaction of the raw test output is PER LINE (`markers.value` on each line — a key on one line
blanks that line's match, not the whole output); a private-key header anywhere blanks the WHOLE
raw block (K0-r3: a key block spans lines, so per-line redaction would leave its body). Every other
free-text value is one `markers.value`. The fixed Korean strings are byte-stable (§6.1, Q7).
"""

import re

from guildcore.records import markers
from guildcore.records.redact import KEY_VALUE_RE, REPLACEMENT

TEST = "test:output"
QA = "qa:output"
E2E_SKIP = "E2E 불요:"
E2E_RUN = "E2E 회귀 실행 필요:"
NOT_RUN_T = "`commands.e2e`(%s), 수동 QA, 사람의 시각 판단"
VRT_NOT_RUN_T = "`commands.vrt` 미실행 — `%s` 에서만 재현, CI/사람이 실행"
RAW_TAIL = 60
NESTED = ("visual-baselines", "safety-net-evidence")
PR_NOT_FOUND = ("PR 을 찾지 못했습니다 (사이드바 Development 로만 연결된 PR 은 검색되지 않음) — "
                "아래 체크리스트를 PR 본문에 직접 옮겨 주세요.")


def e2e_line(text):
    """T-E2E: exactly one of the two literals; anything else (hedged, empty) is branch (b) —
    'if you are unsure the change touches a flow, that IS branch (b)' (test.md)."""
    t = " ".join((text or "").split())
    if t.startswith(E2E_SKIP) and len(t) > len(E2E_SKIP) + 1:
        return t, True
    if t.startswith(E2E_RUN):
        return t, True
    return "%s `<suite>` — 판정 문구가 두 형식이 아니어서 실행 필요로 봄 (사람 실행)" % E2E_RUN, False


def _fence(lines):
    n = 3
    for ln in lines:
        m = re.match(r"^\s*(`{3,}|~{3,})", ln)
        if m:
            n = max(n, len(m.group(1)) + 1)
    return "`" * n


def raw_block(raw, tail=RAW_TAIL):
    lines = (raw or "").rstrip("\n").split("\n")[-tail:]
    if KEY_VALUE_RE.search(raw or ""):
        lines = [REPLACEMENT]
    else:
        lines = [markers.value(ln, one_line=False) for ln in lines]
    f = _fence(lines)
    return [f + "text"] + lines + [f]


def _assert(out, name, nested=()):
    own = {markers.open_tag(name), markers.close_tag(name)}
    for n in nested:
        own |= {markers.open_tag(n), markers.close_tag(n)}
    for m in re.finditer(r"<!--\s*/?guild:[^>]*-->", out):
        if m.group(0) not in own:
            raise ValueError("rendered %s carries a foreign marker: %s" % (name, m.group(0)))
    from guildcore.records.redact import has_secret
    if has_secret(out):
        raise ValueError("rendered %s still carries a secret" % name)
    return out


def loopback_lines(reason, signature):
    sig = signature if isinstance(signature, str) else ",".join(sorted(signature))
    return ["loopback-reason: %s" % markers.value(reason), "loopback-signature: %s" % markers.value(sig)]


def test_output(issue, steps, raw, verify_line, claim_line, coverage, ran, not_run_extra,
                verbatim, diff_paths, e2e, loopback=None):
    """steps = [(cmd, rc, summary_line)]; coverage = [(ac, verdict, tests, why)];
    verbatim = [block text] (copied byte-for-byte); loopback = (reason, signature) | None."""
    v = markers.value
    out = [markers.open_tag(TEST), "## Test — #%d (verify 게이트)" % int(issue), "",
           "### 러너 원문 (엔진 실행)"]
    for cmd, rc, summ in steps:
        out.append("- `%s`: rc %s — %s" % (v(cmd), rc, v(summ or "요약 없음")))
    out += raw_block(raw)
    out += ["", "### verify", "- 원문 판정: %s" % v(verify_line), "- tester 주장 대조: %s" % v(claim_line),
            "", "### AC 커버리지"]
    if not coverage:
        out.append("- (판정 없음 — 원문이 green 이 아님)")
    for ac, verdict, tests, why in coverage:
        out.append("- %s: %s — %s%s" % (v(ac), verdict, v(", ".join(tests) or "인용 없음"),
                                       (" — " + v(why)) if why else ""))
    out += ["", "### 검증 범위", "- (a) 실행함(증거 있음): %s" % v(", ".join("`%s`" % c for c in ran) or "없음")]
    out.append("- (b) 실행 안 함: %s" % "; ".join([NOT_RUN_T % v(not_run_extra.get("e2e") or "없음")] +
                                               [v(x) for x in not_run_extra.get("more", [])]))
    if verbatim or diff_paths:
        out.append("- (c) 기준 이미지 ledger·safety-net 증거 (execute 증거에서 그대로):")
        for b in verbatim:
            out += b.rstrip("\n").split("\n")
        for d in diff_paths:
            out.append("- 시각 diff: %s" % v(d))
    else:
        out.append("- (c) 기준 이미지 ledger 없음 (visual 설정 없음)")
    out.append("- (d) %s" % v(e2e))
    if loopback:
        out += loopback_lines(*loopback)
    out.append(markers.close_tag(TEST))
    return _assert("\n".join(out), TEST, NESTED)


def qa_output(issue, plan_lines, ui_line, honesty, ci_line, ran_at, human_items, pr, directive=None,
              followups_line=None, loopback=None):
    v = markers.value
    out = [markers.open_tag(QA), "## QA — #%d" % int(issue), "", "### QA 계획 & 결과"]
    out += ["- %s" % v(x) for x in plan_lines] or ["- (qa 보고 없음)"]
    out += ["", "### UI/UX 게이트", v(ui_line), "", "### 범위 (honesty of scope)"]
    out += ["- %s" % v(x) for x in honesty]
    out += ["", "### PR CI", v(ci_line)]
    if directive:
        out.append("사람 지시 적용: %s" % v(directive))
    if human_items:
        out += ["", "### 사람 QA 항목 (%d건)" % len(human_items)]
        if pr is None:
            out.append(PR_NOT_FOUND)
        else:
            out.append("PR #%d 본문의 `사람 QA 체크리스트` 에 올림" % int(pr))
        out += ["- [ ] %s" % v(i) for i in human_items]
    if followups_line:
        out += ["", "### 후속 항목", v(followups_line)]
    out.append("ran-at: %s" % ran_at)
    if loopback:
        out += loopback_lines(*loopback)
    out.append(markers.close_tag(QA))
    return _assert("\n".join(out), QA)


def add_loopback_lines(body, name, reason, signature):
    """The attended fail path PATCHes the two lines into the output this run posted (before
    the closing marker; an earlier pair is replaced)."""
    lines = [l for l in body.split("\n") if not markers.clean(l).startswith(("loopback-reason: ", "loopback-signature: "))]
    close = markers.close_tag(name)
    i = max(i for i, l in enumerate(lines) if markers.clean(l) == close)
    return "\n".join(lines[:i] + loopback_lines(reason, signature) + lines[i:])
