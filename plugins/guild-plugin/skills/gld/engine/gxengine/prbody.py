"""PR body built from facts only (design §2.1, §7.2-2, §7.2-6, §7.4, §7.5, §7.11, I1 I8 I11) — U17.

Order:
  1. AC list and the issue-requirement ↔ AC map (people read this first, I1)
  2. 가정과 검토할 결정 — major findings, changed verification paths, flaky marks, refused
     writes (I11), hard-to-revert code notices
  3. 검증 범위 — which named runs ran and their results (from facts, never from a role)
  4. 로컬에서 확인하지 않은 항목 — repo settings `not_checked_locally`
  5. Manual Test Checklist — the qa output file, inserted as is
  6. 범위 밖 발견 / 범위 밖이지만 포함한 수정
  7. stage 2 (V11): the leader's AC verdict table (done-gate `ac_verdicts`) and the leader
     decision list (`state.leader_calls`); the discovery dispositions go inside 6
  8. warning count (§9.3)
  + the one issue-closing line, written by the engine (S10).

Stage 4 (R2 6단계, `stage4` given): the same section lines, arranged for a reviewer — after the stack block,
open: 「무엇을 바꿨나」 (the done-gate leader's `summary`, 1–3 lines, labelled as the leader's; three engine-fact
lines when there is none), 「사람이 확인할 것」 (the Manual Test Checklist as is, `<!-- guild:manual-qa -->` markers
included), 가정과 검토할 결정 · 미룬 요구 · 범위 밖 발견 · 분리한 후속 이슈 (Q11) · 범위 밖이지만 포함한 수정; then every other section in its own
`<details><summary>…</summary>` (STAGE4_FOLDS). No line of the flat body is dropped: a folded section loses only its
bold heading line, which its `<summary>` carries. The summary comes from the leader because "what changed" is a
reading of the diff — no fact the engine keeps says it (file counts do not); the done-gate leader is the one
reader of the whole diff before the human, and its text is marked as its own like the AC table.
Role text is neutralised and scanned (outbound.prepare_text) before it is sent.

P3-B decisions (fail-closed; listed as interpretations in the report):
  * engine headings are **bold** lines, never `#` headings: the outbound neutraliser turns
    every `#` of the body into a full-width one (session 3). The closing line is NOT part
    of this body — github.create_pr(..., closes=<N>) appends `Closes #N` after neutralising.
  * the body refuses to be built (PrBodyError) unless every role / run / check step is
    `done` or `skipped` and every done run's latest facts are a clean exit 0 — a PR body
    never describes a red verification as passed.
  * "가정" = the analysis.md Assumptions list (§7.4: assumptions and decisions to review).
  * changed paths = the `changed_files` of the latest facts of the LAST step (procedure
    order) that has facts — the cumulative recorded-base range (§7.12 S5).
  * flaky = any attempt of a run step whose main run was red and the same-tree rerun green
    (I8) — so `facts_by_step` values may be one facts dict or the list of every attempt.
  * refused writes (I11) = `permission_denials` of role sessions for Write / Edit /
    NotebookEdit, with the file path.
  * hard-to-revert notices = changed paths × repo-config `path_rules` kind `irreversible`
    (category + level), §7.4.
  * "범위 밖이지만 포함한 수정" = discoveries a role reported with `blocks_current_ac: true`
    (the only structured signal in stage 1 that an out-of-scope fix went into this PR);
    every other discovery goes to "범위 밖 발견" (stages 1–2 list them only, §7.5).
  * warnings = state totals.warnings when recorded, otherwise the count of facts warnings.

Stage 2 (V11) decisions — all fail closed (listed as interpretations in the session report):
  * Nothing of stage 2 appears unless there is something to show: no `state.leader_calls` and no
    done-gate step in the procedure → the body is byte-for-byte the stage-1 body.
  * The AC verdict table comes from the LATEST result of the procedure's `check: done-gate` step
    (`results_by_step` — the accepted leader answer). Its text is the leader's, never a fact, and
    the heading says so. A done-gate answer other than `approve` (a human approved after an
    `escalate`, D17) is stated as such and the table stays as the leader's own opinion; a missing
    or malformed answer renders "no leader verdicts recorded" — it neither blocks the body (the
    human's approval is a legitimate way to get here) nor invents a verdict. E5 (stage ≥ 3): a `manual`
    verdict's `why_not_automated` follows its evidence in the same cell, cut like it.
  * Decision list = `state.leader_calls` (situation · answer · reason · step), each with the first
    line of the leader's `note` when known (`leader["notes"][leader_note_key(call)]` =
    "<kind>:<situation>:<k>", VW4 E3), else the latest
    result of the plan-gate / done-gate step for the LAST call of that situation).
  * Discovery dispositions need the engine-numbered discoveries (`leader["discoveries"]` = the
    `done_gate.discoveries` of the done-gate call's in/leader-input.json — the numbering lives in
    leader.py and is not recomputed here). Without them the stage-1 listing is kept untouched.
    followup → "후속 이슈 후보 — 2단계는 만들지 않음", ignore → "무시한 발견", include (and any
    `blocks_current_ac`) → "범위 밖이지만 포함한 수정".
  * D27: unless `public_repo is False`, `kind: security` discoveries are NOT written (the count is
    for the summary comment, see `summary_leader_lines`). Unknown visibility counts as public.
  * Leader text (`evidence`, `note`) is one-lined, cut, and neutralised / scanned by the outbound
    layer like every role text (github.create_pr).
"""

from . import acparse, codes, defaults, github, globs, repoconfig
from . import procedure as procedure_mod

TITLE_MAX = 200
EVIDENCE_MAX = 400      # a leader's per-AC evidence sentence, cut for the table
NOTE_MAX = 200          # the first line of a leader's note in the decision list
SECURITY_KIND = codes.DiscoveryKind.SECURITY.value
DENIED_WRITE_TOOLS = ("Write", "Edit", "NotebookEdit", "MultiEdit")
NONE_LINE = "- (없음)"


class PrBodyError(ValueError):
    """The PR body cannot be built from the facts (an unfinished or red step, a missing input)."""


def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _latest(v):
    items = _as_list(v)
    return items[-1] if items else None


def _cfg(config):
    if isinstance(config, repoconfig.RepoConfig):
        return config
    try:
        return repoconfig.RepoConfig(config)
    except repoconfig.ConfigError as e:
        raise PrBodyError(f"repository settings refused: {e}") from e


def _analysis(analysis):
    if isinstance(analysis, dict):
        return analysis
    if not isinstance(analysis, str):
        raise PrBodyError("analysis: the analysis.md text (engine blob) or its parsed form")
    try:
        parsed = acparse.parse_analysis(analysis)
    except acparse.AcError as e:
        raise PrBodyError(f"analysis.md does not parse: {e}") from e
    problems = acparse.check_analysis(parsed)
    if problems:
        raise PrBodyError("analysis.md: " + "; ".join(problems))
    return parsed


def _one_line(text):
    return " ".join(str(text).split())


def _cell(text):
    return _one_line(text).replace("|", "\\|")


def _ac_refs(ids):
    return ", ".join(f"AC #{n}" for n in ids) if ids else "(없음)"


def _red(r):
    return r is None or r.get("exit_code") != 0 or bool(r.get("timed_out"))


def _check_finished(proc, state, facts_by_step):
    status = {s["id"]: s.get("status") for s in (state.get("steps") or [])}
    problems = []
    for st in proc.steps:
        if st.kind == codes.StepKind.OP.value:
            continue
        s = status.get(st.id)
        if s not in (codes.StepStatus.DONE.value, codes.StepStatus.SKIPPED.value):
            problems.append(f"step {st.id!r} is {s!r}, not done")
            continue
        if st.kind == codes.StepKind.RUN.value and s == codes.StepStatus.DONE.value:
            f = _latest(facts_by_step.get(st.id))
            run = (f or {}).get("run")
            if not run or _red(run) or not f.get("end_tree", {}).get("clean", False):
                problems.append(f"run step {st.id!r} is done but its latest facts are not a clean exit 0")
    if problems:
        raise PrBodyError("no PR body for an unfinished or red procedure: " + "; ".join(problems))


def _changed_paths(proc, facts_by_step):
    for st in reversed(proc.steps):
        f = _latest(facts_by_step.get(st.id))
        if f is not None:
            out = set()
            for c in f.get("changed_files") or []:
                out.add(c["path"])
                if c.get("from"):
                    out.add(c["from"])
            return sorted(out)
    return []


def _section(title, lines):
    return [f"**{title}**", ""] + (lines or [NONE_LINE]) + [""]


# --- stage 2 (V11): the leader's part ------------------------------------------------------------

def _cut(text, n):
    text = _one_line(text)
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _first_line(text):
    for ln in str(text or "").splitlines():
        if ln.strip():
            return _cut(ln, NOTE_MAX)
    return ""


def _check_step(proc, name):
    for st in proc.steps:
        if st.kind == codes.StepKind.CHECK.value and st.name == name:
            return st
    return None


def _leader_answer(res):
    """The result dict when it carries a leader `answer` of the codes, else None."""
    if isinstance(res, dict) and res.get("answer") in codes.LeaderAnswer.values():
        return res
    return None


def leader_note_key(call):
    """The `leader["notes"]` key of a state.leader_calls entry: "<kind>:<situation>:<k>".

    VW4 E3: `k` is the first session of the call — for a `check` call the ATTEMPT of that situation's own
    check step, counted per step — so plan-gate check#1 and done-gate check#1 shared "<kind>:<k>" and the
    later note was printed on both lines. A key in the old form ("check:1") is no longer looked up: it
    cannot say which call it was, so such a note is left out (the decision line stays, without a note)."""
    return f"{call.get('kind')}:{call.get('situation')}:{call.get('k')}"


def _decision_lines(state, results_by_step, proc, notes):
    calls = [c for c in (state.get("leader_calls") or []) if isinstance(c, dict)]
    last = {}
    for c in calls:
        last[c.get("situation")] = c
    lines = []
    for c in calls:
        situation = c.get("situation")
        note = (notes or {}).get(leader_note_key(c))
        if note is None and c is last[situation] and c.get("kind") == codes.AttemptKind.CHECK.value:
            st = _check_step(proc, situation)
            res = _leader_answer(_latest(results_by_step.get(st.id))) if st else None
            if res is not None and res.get("answer") == c.get("answer"):
                note = res.get("note")
        if c.get("answer") is None:
            what = f"답 없음 (리더 실패: `{c.get('failed') or '?'}`)"
        else:
            what = f"`{c['answer']}`" + (f" → `{c['step']}`" if c.get("step") else "")
            what += f" · 이유 `{c.get('reason') or '?'}`"
        first = _first_line(note)
        lines.append(f"- {c.get('kind')}#{c.get('k')} `{situation}`: {what}" + (f" — {first}" if first else ""))
    return lines


def _verdict_lines(proc, results_by_step, an):
    """The AC verdict table lines, or None when the procedure has no done-gate."""
    st = _check_step(proc, codes.CheckKind.DONE_GATE.value)
    if st is None:
        return None
    res = _leader_answer(_latest(results_by_step.get(st.id)))
    reasons = res is not None and isinstance(res.get("ac_verdicts"), list) and any(
        isinstance(v, dict) and _why_not_automated(v) for v in res["ac_verdicts"])
    lines = ["리더(LLM)가 쓴 판정입니다 — 엔진이 확인한 사실이 아닙니다. 엔진은 모든 AC의 판정 유무, `unmet` 없음, "
             "`manual` AC의 체크리스트 참조" + (", `manual` AC의 자동화하지 않은 이유 유무" if reasons else "")
             + "만 확인했습니다."]
    if res is None or not isinstance(res.get("ac_verdicts"), list):
        return lines + ["", "- 리더의 AC 판정이 기록되지 않았습니다(사람이 승인했거나 기록을 읽지 못했습니다)."]
    if res["answer"] != codes.LeaderAnswer.APPROVE.value:
        lines += ["", f"- 이 판정은 리더가 `{res['answer']}`(이유 `{res.get('reason')}`)로 답한 것이며 `approve`가 "
                      "아닙니다. 이 PR은 사람이 승인해 진행했습니다."]
    by_ac = {}
    for v in res["ac_verdicts"]:
        if isinstance(v, dict) and isinstance(v.get("ac"), int):
            by_ac[v["ac"]] = v
    rows = ["| AC | 판정 | 근거 (리더) |", "|---|---|---|"]
    for n in an["acs"]:
        v = by_ac.get(n)
        if v is None:
            rows.append(f"| AC #{n} | (판정 없음) | — |")
        else:
            status = "manual (수동 확인)" if v.get("status") == codes.AcVerdict.MANUAL.value else v.get("status")
            why = _why_not_automated(v)
            tail = f" — 자동 검사를 두지 않은 이유: {_cell(_cut(why, EVIDENCE_MAX))}" if why else ""
            rows.append(f"| AC #{n} | {_cell(status)} | {_cell(_cut(v.get('evidence', ''), EVIDENCE_MAX))}{tail} |")
    return lines + [""] + rows


def _why_not_automated(v):
    """E5: the leader's reason a `manual` criterion has no automated check ('' when none / not manual)."""
    why = v.get("why_not_automated")
    if v.get("status") != codes.AcVerdict.MANUAL.value or not isinstance(why, str):
        return ""
    return why.strip()


def _dispositions(proc, results_by_step):
    """{D id: disposition} from the latest done-gate answer ({} when none)."""
    st = _check_step(proc, codes.CheckKind.DONE_GATE.value)
    res = _leader_answer(_latest(results_by_step.get(st.id))) if st else None
    return {d["id"]: d.get("disposition") for d in (res or {}).get("discoveries") or []
            if isinstance(d, dict) and isinstance(d.get("id"), str)}


def _leader_discovery_lines(index, disp, public_repo):
    """(found, included) bullets from the engine-numbered discoveries and the leader's dispositions."""
    D = codes.DiscoveryDisposition
    found, included = [], []
    for d in index:
        if not isinstance(d, dict) or (public_repo is not False and d.get("kind") == SECURITY_KIND):
            continue                                        # D27
        what = disp.get(d.get("id"))
        line = f"{d.get('id')} · {d.get('kind')} · `{_one_line(d.get('where', ''))}` — {_one_line(d.get('note', ''))}"
        if what == D.INCLUDE.value or (what is None and d.get("blocks_current_ac")):
            included.append(f"- {line}")
        elif what == D.FOLLOWUP.value:
            found.append(f"- [후속 이슈 후보 — 2단계는 만들지 않음] {line}")
        elif what == D.IGNORE.value:
            found.append(f"- [무시한 발견] {line}")
        else:
            found.append(f"- [리더 판정 없음] {line}")
    return found, included


def _stage3_discovery_lines(index, disp, followups):
    """Stage 3 (E19–E21): (found, included, security count). A `security` discovery is never written in
    any repository — only counted. followup / duplicate name what the op did (or will do)."""
    D = codes.DiscoveryDisposition
    made = {}
    for row in followups or ():
        if isinstance(row, dict) and isinstance(row.get("key"), str):
            made[row["key"].split(":", 1)[0]] = row
    found, included, security = [], [], 0
    for d in index:
        if not isinstance(d, dict):
            continue
        if d.get("kind") == SECURITY_KIND:
            security += 1
            continue
        what = disp.get(d.get("id"))
        line = f"{d.get('id')} · {d.get('kind')} · `{_one_line(d.get('where', ''))}` — {_one_line(d.get('note', ''))}"
        row = made.get(d.get("id"))
        if what == D.INCLUDE.value or (what is None and d.get("blocks_current_ac")):
            included.append(f"- {line}")
        elif what == D.FOLLOWUP.value:
            tag = "후속 이슈"
            if row and row.get("dry_run"):
                tag += " — dry-run, 만들지 않음"
            elif row and row.get("number"):
                tag += f" #{row['number']}"
            found.append(f"- [{tag}] {line}")
        elif what == D.DUPLICATE.value:
            tag = "중복"
            if row and row.get("dry_run"):
                tag += " — dry-run, 댓글 달지 않음"
            elif row and row.get("number"):
                tag += f" — 기존 이슈 #{row['number']}에 댓글"
            found.append(f"- [{tag}] {line}")
        elif what == D.IGNORE.value:
            found.append(f"- [무시한 발견] {line}")
        else:
            found.append(f"- [리더 판정 없음] {line}")
    return found, included, security


def _followup_lines(index, disp, followups, dry_run, is_private=None, deferred=0):
    """"분리한 후속 이슈" (E20, E21, A4): what create-followups made — or, before it ran (the PR is made
    first), what it will make. Security follow-ups by number only; dry run = counts only."""
    D = codes.DiscoveryDisposition
    by_id = {d.get("id"): d for d in index if isinstance(d, dict)}
    if followups is None:
        planned = [(i, w) for i, w in disp.items() if w in (D.FOLLOWUP.value, D.DUPLICATE.value) and i in by_id]
        local = [i for i, _ in planned if is_private is not True and by_id[i].get("kind") == SECURITY_KIND]
        planned = [(i, w) for i, w in planned if i not in local]
        if not planned and not local and not deferred:
            return []
        n_new = sum(1 for _, w in planned if w == D.FOLLOWUP.value)
        n_dup = len(planned) - n_new
        tail = " (dry-run — 만들지 않음)" if dry_run else ""
        more = " · 미룬 요구 묶음 1건" if deferred else ""
        more += f" · 보안 발견 {len(local)}건은 엔진 로컬 기록만" if local else ""
        return [f"- 이 PR 뒤 `create-followups` 단계가 처리합니다{tail}: 후속 이슈 {n_new}건 · 중복 댓글 {n_dup}건{more}"]
    rows = [r for r in followups if isinstance(r, dict)]
    if not rows:
        return []
    lines = []
    dry = [r for r in rows if r.get("dry_run") and not r.get("private_path")]
    if dry:
        n_new = sum(1 for r in dry if r.get("disposition") == D.FOLLOWUP.value)
        lines.append(f"- dry-run — 만들지 않음: 후속 이슈 {n_new}건 · 중복 댓글 {len(dry) - n_new}건 "
                     "(만들었을 내용은 엔진 로컬 기록)")
    for r in rows:
        if r.get("dry_run") or r.get("private_path") or not r.get("number"):
            continue
        sid = r["key"].split(":", 1)[0]
        if r.get("kind") == SECURITY_KIND:
            lines.append(f"- 보안 후속 이슈 #{r['number']} — 내용은 이슈에서")
        elif sid == "deferred":
            lines.append(f"- 미룬 요구 → 후속 이슈 #{r['number']}")
        elif r.get("disposition") == D.DUPLICATE.value:
            lines.append(f"- {sid} · {r.get('kind')} → 기존 이슈 #{r['number']}에 댓글")
        else:
            lines.append(f"- {sid} · {r.get('kind')} → 후속 이슈 #{r['number']}")
    private = sum(1 for r in rows if r.get("private_path"))
    if private:
        lines.append(f"- 보안 발견 {private}건 — 비공개로 확인되지 않은 저장소라 GitHub에 쓰지 않았습니다(엔진 로컬 기록)")
    return lines


def _exit(r):
    if not isinstance(r, dict):
        return "실행 안 함"
    if r.get("timed_out"):
        return "시간 초과"
    return f"종료 코드 {r.get('exit_code')}"


def _repro_lines(proc, facts_by_step):
    """"재현 증거" (E6, D1, D10): the latest `repro-red` facts and the final `test` run — facts only."""
    st = next((x for x in proc.steps if x.kind == codes.StepKind.RUN.value
               and x.name == codes.PluginCommand.REPRO_RED.value), None)
    if st is None:
        return None
    f = _latest(facts_by_step.get(st.id))
    run = (f or {}).get("run") or {}
    ev = run.get("evidence") or {}
    scope = ev.get("scope") or {}
    files = [x.get("path") for x in (ev.get("overlay") or {}).get("files") or [] if isinstance(x, dict)]
    rows = ["엔진이 기록한 사실(facts)로 만든 표입니다. 판정 트리 = 기록 base의 새 worktree + `"
            + _cell(scope.get("step") or "reproduce") + "`가 바꾼 테스트 파일(HEAD blob).", "",
            "| 사실 | 값 |", "|---|---|",
            f"| 범위 (`{_cell(scope.get('step') or '?')}` 시도 {', '.join(map(str, scope.get('attempts') or [])) or '—'}"
            f"의 변경이 test-code glob 안) | {'통과' if scope.get('ok') else '실패'} |",
            "| 판정 트리에 올린 파일 | " + (", ".join(f"`{_cell(x)}`" for x in files) or "—") + " |",
            f"| 판정 트리 `test` 1회 (빨강이어야 함) | {_exit(run.get('head'))} |",
            f"| 판정 트리 `test` 2회 (빨강이어야 함) | {_exit(run.get('head_rerun'))} |",
            f"| 기록 base `test` (녹색이어야 함) | {_exit(run.get('base_run'))} |"]
    if run.get("base_rerun"):
        rows.append(f"| 기록 base `test` 2회 (1회가 녹색이 아니어서 같은 트리에서 다시) | {_exit(run['base_rerun'])} |")
    for t in proc.steps:
        if t.kind == codes.StepKind.RUN.value and t.name == "test":
            tf = _latest(facts_by_step.get(t.id))
            head = ((tf or {}).get("end_head") or "")[:12]
            rows.append(f"| 최종 `{t.id}` (수정 뒤 HEAD `{head}`) | {_exit((tf or {}).get('run'))} |")
    return rows


def _irreversible_lines(state):
    """E22–E24: one line per detected (category, code | path) at notify / human-decision, and the lowered
    levels. A human-decision entry is shown with its approval (the engine stopped for it)."""
    irr = state.get("irreversible") or {}
    approved = {(a.get("category"), a.get("code"), a.get("path")): a for a in irr.get("approved") or []
                if isinstance(a, dict)}
    lines, seen, lowered = [], set(), {}
    L = codes.IrreversibleLevel
    for d in irr.get("detected") or []:
        if not isinstance(d, dict):
            continue
        key = (d.get("category"), d.get("code"), d.get("path"))
        if d.get("lowered"):
            lowered.setdefault(d.get("category"), (d.get("default_level"), d.get("level")))
        if key in seen or d.get("level") not in (L.NOTIFY.value, L.HUMAN_DECISION.value):
            continue
        seen.add(key)
        what = f"코드 `{d['code']}`" if d.get("code") else f"`{_one_line(d.get('path') or '?')}`"
        tail = ""
        if d.get("level") == L.HUMAN_DECISION.value:
            a = approved.get(key)
            tail = f" — 사람 승인 {a.get('at')}" if a else " — 사람 승인 기록 없음"
        lines.append(f"- 되돌리기 어려운 변경 ({d.get('category')}, {d.get('level')}): {what} ({d.get('step')}){tail}")
    for cat, (default, level) in lowered.items():
        lines.append(f"- 저장소 설정이 기본보다 낮춘 수준: {cat} 기본 {default} → {level}")
    return lines


def _fix_lines(state, results_by_step, proc):
    """E18: the engine-included out-of-scope fixes (F) with the finding role, who fixed it and the
    done-gate verdict (the latest answer, else state). Security content is withheld (E21)."""
    st = _check_step(proc, codes.CheckKind.DONE_GATE.value)
    res = _leader_answer(_latest(results_by_step.get(st.id))) if st else None
    verdict = {v.get("id"): v.get("verdict") for v in (res or {}).get("included_fixes") or [] if isinstance(v, dict)}
    out = []
    for f in state.get("included_fixes") or []:
        if not isinstance(f, dict):
            continue
        v = verdict.get(f.get("id")) or f.get("verdict") or "판정 없음"
        who = f"발견 {f.get('role')}/{f.get('from_step')}, 처리 {f.get('handled_by')}, 리더 판정 {v}"
        if f.get("kind") == SECURITY_KIND:
            out.append(f"- {f.get('id')} · security — 내용은 쓰지 않습니다(E21) ({who})")
        else:
            out.append(f"- {f.get('id')} · {f.get('kind')} · `{_one_line(f.get('where', ''))}` — "
                       f"{_one_line(f.get('note', ''))} ({who})")
    return out


def _golden_rows(proc, facts_by_step):
    """[P2] V14 (E33): the baseline-image ledger of the LAST step with facts (cumulative from base,
    engine-made) — the same "last facts" rule as the changed paths."""
    for st in reversed(proc.steps):
        f = _latest(facts_by_step.get(st.id))
        if f is not None:
            return [g for g in f.get("golden") or [] if isinstance(g, dict)]
    return []


def summary_stage3_lines(state, security_count=0):
    """Engine text lines the summary comment adds in stage 3 (V16, E21, E23, A4). Pure, `[]` when nothing.

    Hard-to-revert notices (the summary is PATCHed — no new comment, E23), lowered levels, the security
    count by visibility (state.github.is_private; unknown = public) and the follow-up counts. Replaces
    summary_leader_lines' withheld-security line from stage 3 (pass it security_count=0 there)."""
    lines = []
    for ln in _irreversible_lines(state):
        lines.append(ln.replace("되돌리기 어려운 변경", "hard to revert", 1)
                     .replace("저장소 설정이 기본보다 낮춘 수준", "level lowered by the repository settings", 1)
                     .replace(" 기본 ", " default ", 1).replace("사람 승인 기록 없음", "no human approval recorded")
                     .replace("사람 승인", "approved by a human"))
    if security_count:
        if (state.get("github") or {}).get("is_private") is True:
            lines.append(f"- security discoveries: {int(security_count)} (content only in follow-up issues of this "
                         "private repository)")
        else:
            lines.append(f"- public repository — {int(security_count)} security discoveries, see "
                         f"`/gld status {state.get('issue')}`")
    rows = [r for r in state.get("followups") or [] if isinstance(r, dict) and not r.get("private_path")]
    if rows:
        dry = [r for r in rows if r.get("dry_run")]
        made = [r for r in rows if not r.get("dry_run") and r.get("disposition") == codes.DiscoveryDisposition.FOLLOWUP.value]
        if dry:
            lines.append(f"- follow-ups (dry run — not created): {len(dry)}")
        if len(rows) > len(dry):
            lines.append(f"- follow-ups: {len(made)} created, {len(rows) - len(dry) - len(made)} commented")
    return lines


def followup_body(issue, pr_number, discovery, leader_note=None):
    """The follow-up Issue body (E20): the original Issue, the PR, the finding role · kind · where, the
    role's note and the leader's note. Engine text, no `#` headings; github.create_followup neutralises,
    scans and puts the marker line first."""
    lines = ["**Guild (gld) 후속 이슈**", "",
             f"- 원래 이슈: #{issue}",
             f"- PR: #{pr_number}" if pr_number else "- PR: (없음)",
             f"- 발견한 역할: {_one_line(discovery.get('role') or '?')}",
             f"- 종류: `{discovery.get('kind')}`",
             f"- 위치: `{_one_line(discovery.get('where') or '')}`", "",
             "**역할의 설명**", "", str(discovery.get("note") or "").strip() or "(없음)", ""]
    if leader_note and str(leader_note).strip():
        lines += ["**리더의 메모 (done-gate)**", "", str(leader_note).strip(), ""]
    return "\n".join(lines)


def duplicate_comment_body(issue, pr_number, discovery):
    """The comment on a duplicate candidate (E19 `duplicate`)."""
    return "\n".join([
        "**Guild (gld) — 같은 발견이 다시 나왔습니다**", "",
        f"- 이슈: #{issue}" + (f" (PR #{pr_number})" if pr_number else ""),
        f"- 발견한 역할: {_one_line(discovery.get('role') or '?')}",
        f"- 종류: `{discovery.get('kind')}`",
        f"- 위치: `{_one_line(discovery.get('where') or '')}`", "",
        str(discovery.get("note") or "").strip() or "(없음)", ""])


def deferred_body(issue, pr_number, rows):
    """The follow-up Issue of the requirement rows a replan deferred (E30 — one Issue for all rows)."""
    lines = ["**Guild (gld) 후속 이슈 — 미룬 요구**", "",
             f"- 원래 이슈: #{issue}", f"- PR: #{pr_number}" if pr_number else "- PR: (없음)", "",
             "원래 이슈에서 리더의 `replan`(범위 축소)으로 이번 PR에서 뺀 요구입니다:", ""]
    lines += [f"- {r.get('row')}: {_one_line(r.get('text') or '')}" for r in rows]
    return "\n".join(lines + [""])


def followup_items(issue, pr_number, index, answer, *, is_private, deferred_rows=None):
    """The `create-followups` work list (E19–E21) from the engine-numbered discoveries and the
    accepted done-gate answer — pure; github.apply_followups runs it.

    index       the done-gate call's in/leader-input.json `done_gate.discoveries`
    answer      the accepted done-gate answer (its `discoveries[{id, disposition, title,
                duplicate_of}]` and `note`); None → no items
    is_private  state.github.is_private — only True opens the security follow-up (E21)
    deferred_rows  [P2] state.deferred_rows — one more item (kind deferred-requirement, E30), not counted
                against FOLLOWUPS_MAX (it is the engine's, not a leader disposition)
    Each item: {key, source, kind, disposition, title, body, labels, type_label, target, private_path}.
    PrBodyError when the answer breaks a rule the leader check guarantees (fail-closed).
    """
    D = codes.DiscoveryDisposition
    answer = answer if isinstance(answer, dict) else {}
    by_id = {d.get("id"): d for d in index or () if isinstance(d, dict)}
    items, n_followups = [], 0
    for a in answer.get("discoveries") or []:
        if not isinstance(a, dict) or a.get("disposition") not in (D.FOLLOWUP.value, D.DUPLICATE.value):
            continue
        d = by_id.get(a.get("id"))
        if d is None:
            raise PrBodyError(f"done-gate answer names unknown discovery {a.get('id')!r}")
        payload = {k: d.get(k) for k in ("kind", "role", "where", "note", "blocks_current_ac")}
        key = github.followup_key(d["id"], payload)
        security = d.get("kind") == SECURITY_KIND
        item = {"key": key, "source": d["id"], "kind": d.get("kind"), "disposition": a["disposition"],
                "title": None, "body": None, "labels": [], "type_label": None, "target": None,
                "private_path": security and is_private is not True}
        if a["disposition"] == D.FOLLOWUP.value:
            n_followups += 1
            if not isinstance(a.get("title"), str) or not a["title"].strip():
                raise PrBodyError(f"{d['id']}: followup without a title")
            item["title"] = a["title"]
            item["body"] = followup_body(issue, pr_number, d, answer.get("note"))
            item["labels"] = [github.FOLLOWUP_LABEL] + ([github.SECURITY_LABEL] if security else [])
            item["type_label"] = defaults.FOLLOWUP_TYPE_LABELS.get(d.get("kind"))
        else:
            target = a.get("duplicate_of")
            if isinstance(target, bool) or not isinstance(target, int) or target < 1:
                raise PrBodyError(f"{d['id']}: duplicate without a candidate Issue")
            item["target"] = target
            item["body"] = duplicate_comment_body(issue, pr_number, d)
        items.append(item)
    if n_followups > defaults.FOLLOWUPS_MAX:
        raise PrBodyError(f"{n_followups} follow-ups exceed FOLLOWUPS_MAX {defaults.FOLLOWUPS_MAX}")
    rows = [r for r in deferred_rows or () if isinstance(r, dict) and r.get("row")]
    if rows:
        kind = defaults.DEFERRED_REQUIREMENT_KIND
        items.append({"key": github.followup_key("deferred", [[r["row"], r.get("text")] for r in rows]),
                      "source": "deferred", "kind": kind, "disposition": D.FOLLOWUP.value,
                      "title": f"미룬 요구 — Issue {issue} ({', '.join(r['row'] for r in rows)})",
                      "body": deferred_body(issue, pr_number, rows), "labels": [github.FOLLOWUP_LABEL],
                      "type_label": defaults.FOLLOWUP_TYPE_LABELS.get(kind), "target": None, "private_path": False})
    return items


def security_findings_md(issue, index, answer=None, is_private=None):
    """`<records>/security-findings.md` (E21): every `security` discovery's content, engine-local, never
    committed or sent (`/gld status` and resume show it). None when there is none."""
    disp = {d.get("id"): d.get("disposition") for d in ((answer or {}).get("discoveries") or [])
            if isinstance(d, dict)}
    rows = [d for d in index or () if isinstance(d, dict) and d.get("kind") == SECURITY_KIND]
    if not rows:
        return None
    where = ("private repository — a follow-up Issue carries it" if is_private is True
             else "repository not known to be private — nothing was written to GitHub")
    out = [f"# Security findings — Issue {issue}", "",
           "Engine-local record (never committed, never sent). " + where + ".", ""]
    for d in rows:
        out += [f"## {d.get('id')} · {d.get('role')} · {_one_line(d.get('where') or '')}", "",
                f"- disposition: {disp.get(d.get('id')) or 'not judged'}",
                f"- blocks_current_ac: {str(bool(d.get('blocks_current_ac'))).lower()}", "",
                str(d.get("note") or "").strip() or "(no note)", ""]
    return "\n".join(out)


def security_discovery_count(index):
    """How many engine-numbered discoveries are `kind: security` (the count the summary comment shows, D27)."""
    return sum(1 for d in (index or []) if isinstance(d, dict) and d.get("kind") == SECURITY_KIND)


def summary_leader_lines(state, security_count=0, public_repo=None):
    """Engine text lines the GitHub summary comment adds in stage 2 (V11, M6 rest). Pure.

    One line per leader decision (situation · answer · rerun step · reason code), a waiting line
    while the Issue is stopped at `needs_leader`, the leader's escalate recommendation or failure
    when stopped, and — for a public repository, or unknown (fail closed) — the count of withheld
    `security` discoveries (D27). `[]` when there is nothing, so a stage-1 summary is unchanged.
    No `#` headings; the outbound layer neutralises and scans the text like the rest. The caller
    (github.summary_text is L2 and cannot import this module) appends the lines.
    """
    lines = []
    for c in (c for c in (state.get("leader_calls") or []) if isinstance(c, dict)):
        if c.get("answer") is None:
            lines.append(f"- leader `{c.get('situation')}`: no valid answer (`{c.get('failed') or '?'}`)")
        else:
            lines.append(f"- leader `{c.get('situation')}`: `{c['answer']}`"
                         + (f" → `{c['step']}`" if c.get("step") else "")
                         + f" (reason `{c.get('reason') or '?'}`)")
    stop = state.get("stop") or {}
    if stop.get("status") == codes.StepStatus.NEEDS_LEADER.value:
        lines.append(f"- waiting for the leader: `{stop.get('reason')}`"
                     + (f" at `{stop['step']}`" if stop.get("step") else ""))
    rec = stop.get("recommendation")
    if isinstance(rec, dict):
        lines.append(f"- leader recommends `{rec.get('answer')}`"
                     + (f" → `{rec['step']}`" if rec.get("step") else "") + f" (reason `{rec.get('reason')}`)")
    lf = stop.get("leader_failed")
    if isinstance(lf, dict):
        lines.append(f"- leader failed: `{lf.get('code')}`" + (f" ({lf['detail']})" if lf.get("detail") else ""))
    if security_count and public_repo is not False:
        lines.append(f"- withheld security discoveries: {int(security_count)} (public repository — tell the owner)")
    return lines



MUTATION_TEXT_MAX = 80
_MUTATION_STATUS = {
    codes.MutationStatus.KILLED.value: "killed — 테스트가 빨강",
    codes.MutationStatus.SURVIVED.value: "survived — 테스트가 녹색 그대로(증거 아님)",
    codes.MutationStatus.TIMED_OUT.value: "timed-out — 증거 아님",
    codes.MutationStatus.REFUSED.value: "refused — 실행 안 함",
    codes.MutationStatus.NOT_RUN.value: "not-run — 판정 못 함",
}


def _stack_lines(stack):
    """Stage 4 (§2.4): the stack block of a PR on another Issue's branch ([] when there is none). The markers are
    what `sprint sync` (stack_sync.py) looks for."""
    if stack is None:
        return []
    tracker = f" (스프린트 #{stack['tracker']})" if stack.get("tracker") else ""
    lines = [defaults.SPRINT_STACK_MARKER, f"**스택 PR{tracker}**", "",
             f"- 스택: 이 PR은 #{stack['issue']} 위에 있다 — 먼저 머지할 것",
             f"- 이 diff는 `gld/{stack['issue']}` 위의 변경만 담습니다"]
    if stack.get("draft"):
        lines.append("- draft — 아래 PR이 머지되면 `/gld sprint sync`가 기본 브랜치를 머지·검증하고 ready로 바꿉니다")
    return lines + [defaults.SPRINT_STACK_MARKER_END, ""]


def _snippet(text):
    """One line of role-declared code for a table cell (never ends its own code span)."""
    text = _cut(text, MUTATION_TEXT_MAX)
    return "`" + _cell(text).replace("`", "'") + "`" if text else "(없음)"


def _mutation_lines(record):
    """Stage 4 (VB9): the HEAD's mutation record as a table ([] when nothing was declared). Facts only, but for
    path / find / replace, which the developer chose; the run output stays in the engine's records."""
    if record is None:
        return []
    lines = ["엔진이 선언된 변경을 HEAD에 하나씩 적용하고 `test`를 실행한 사실입니다. 바꿀 자리와 내용은 개발자 역할이 골랐습니다. "
             "`killed`만 증거이고, 어떤 AC가 충족됐는지는 리더가 판정합니다.", ""]
    if record.get("problem"):
        return lines + [f"- `{defaults.MUTATIONS_NAME}`을 쓸 수 없어 실행하지 않았습니다 (`{record['problem']}`)"]
    control = record.get("control") or {}
    again = (f", 같은 트리에서 다시: {_exit(control['again'])}" + (" — 흔들림(빨강 뒤 녹색): 빨강은 두 번 모두 "
             "대조에 없던 실패 줄이 있을 때만 `killed`" if control.get("flaky") else "")) if control.get("again") else ""
    lines += [f"- HEAD `{str(record.get('head') or '')[:12]}` · 대조 실행(변경 없음): {_exit(record.get('control'))}{again}", "",
              "| id | AC | 파일 | 바꾼 글 | 넣은 글 | 결과 |", "|---|---|---|---|---|---|"]
    for row in record.get("rows") or ():
        what = _MUTATION_STATUS.get(row.get("status"), str(row.get("status")))
        if row.get("detail"):
            what += f" (`{row['detail']}`)"
        if row.get("run"):
            what += f", {_exit(row['run'])}"
        if row.get("again"):
            what += f", 다시 {_exit(row['again'])}"
        lines.append(f"| {row.get('id')} | {', '.join(str(n) for n in row.get('acs') or ())} | {_snippet(row.get('path') or '')} | "
                     f"{_snippet(row.get('find') or '')} | {_snippet(row.get('replace') or '')} | {what} |")
    return lines


def build(procedure, state, facts_by_step, results_by_step, config, qa_checklist, analysis,
          leader=None, public_repo=None, stage3=None, stage4=None):
    """Return the PR body text (pure).

    procedure        the parsed procedure (or its dict)
    state            state.json dict
    facts_by_step    {step id: facts dict, or the list of every attempt's facts, oldest first}
    results_by_step  {step id: result dict, or the list of every attempt's results}
    config           RepoConfig (or its dict) — from the recorded base blob
    qa_checklist     the qa output file text (committed blob), inserted as is
    analysis         analysis.md text (committed blob) or acparse.parse_analysis output
    leader           stage 2, optional dict: "discoveries" = the `done_gate.discoveries` list of the
                     done-gate call's in/leader-input.json (engine-numbered D1…Dn), "notes" =
                     {leader_note_key(entry) = "<kind>:<situation>:<k>": the leader note of that
                     state.leader_calls entry}. Both optional.
    public_repo      False only when the repository is known private (D27); None / True = security
                     discoveries stay out of the stage-2 body.
    stage3           stage 3 only (V8, V16), optional dict — None keeps the stage-2 body byte for byte:
                     "is_private" (state.github.is_private), "dry_run" (repo-config followups_dry_run),
                     "followups" (state.followups once create-followups ran; None before — the PR is
                     made first). `public_repo` is not read: E21 keeps every security discovery out.
    stage4           stage 4 only (VB8), optional dict — None keeps the stage-3 body byte for byte; a dict (even {})
                     gives the stage-4 layout (summary · checklist · assumptions open, the rest folded):
                     "stack" = None or {"issue": D, "tracker": T or None, "draft": bool} (the stack block with
                     defaults.SPRINT_STACK_MARKER … END), "allowed_test_changes" = [path] (H21: "allowed by a
                     human"), "mutations" = the HEAD's mutation-record dict or None (VB9).
    Raises PrBodyError (fail-closed). The closing line is added by github.create_pr / update_pr.
    """
    leader = leader or {}
    s3 = dict(stage3) if stage3 is not None else None
    s4 = dict(stage4) if stage4 is not None else {}
    proc = procedure if isinstance(procedure, procedure_mod.Procedure) else procedure_mod.Procedure(procedure)
    facts_by_step = dict(facts_by_step or {})
    results_by_step = dict(results_by_step or {})
    cfg = _cfg(config)
    an = _analysis(analysis)
    has_qa = any(st.kind == codes.StepKind.ROLE.value and st.name == "qa" for st in proc.steps)
    if has_qa or s3 is None:
        if not isinstance(qa_checklist, str) or not qa_checklist.strip():
            raise PrBodyError("the Manual Test Checklist (qa output) is missing or empty")
    # stage 3: a template without a qa step (safety-net) has no checklist to insert
    _check_finished(proc, state, facts_by_step)
    changed = _changed_paths(proc, facts_by_step)

    # 6. out-of-scope discoveries (computed first: stage 3 also lists security follow-ups in 2)
    found, included, seen = [], [], set()
    has_gate = _check_step(proc, codes.CheckKind.DONE_GATE.value) is not None
    index = leader.get("discoveries")
    numbered = has_gate and isinstance(index, list)
    disp = _dispositions(proc, results_by_step)
    security = 0
    if numbered and s3 is not None:
        # stage 3: E21 — no security content in any repository; followup / duplicate name the op's work
        found, included, security = _stage3_discovery_lines(index, disp, s3.get("followups"))
    elif numbered:
        # stage 2: the engine-numbered discoveries with the leader's dispositions
        found, included = _leader_discovery_lines(index, disp, public_repo)
    else:
        for st in proc.steps:
            if st.kind == codes.StepKind.CHECK.value:
                continue        # a check step's result is a leader answer; its `discoveries` have another shape
            for res in _as_list(results_by_step.get(st.id)):
                for d in (res or {}).get("discoveries") or []:
                    if s3 is None and has_gate and public_repo is not False and d.get("kind") == SECURITY_KIND:
                        continue                                    # D27 (stage 2 only)
                    key = (d.get("kind"), d.get("where"), d.get("note"), bool(d.get("blocks_current_ac")))
                    if key in seen:
                        continue
                    seen.add(key)
                    if s3 is not None and d.get("kind") == SECURITY_KIND:
                        security += 1                               # E21 (stage 3, every repository)
                        continue
                    line = (f"- {d.get('kind')} · `{_one_line(d.get('where', ''))}` — "
                            f"{_one_line(d.get('note', ''))} ({st.id})")
                    (included if d.get("blocks_current_ac") else found).append(line)

    parts = []       # (key, lines) in the stage ≤ 3 order; a stage-4 body arranges the same lines (_stage4_layout)

    def add(key, lines):
        parts.append((key, lines))

    # 1. AC list + requirement map
    add(P_AC, _section("인수 기준 (AC)", [f"- AC #{n}: {_one_line(an['ac_text'].get(n, ''))}" for n in an["acs"]]))
    deferred = [r for r in state.get("deferred_rows") or [] if isinstance(r, dict)] if s3 is not None else []
    if deferred:     # [P2] V12 (E30): right below the AC list — not met, deferred to a follow-up Issue
        add(P_DEFERRED, _section("미룬 요구", ["리더의 `replan`(범위 축소)으로 이번 PR에서 뺀 요구입니다. AC가 없고, "
                                               "`create-followups`가 후속 이슈 하나로 분리합니다.", ""]
                                 + [f"- {r.get('row')}: {_one_line(r.get('text') or '')}" for r in deferred]))
    rmap = ["| 이슈 요구 | AC |", "|---|---|"]
    rmap += [f"| {_cell(req)} | {_ac_refs(ids)} |" for req, ids in an["requirement_map"]]
    add(P_MAP, _section("이슈 요구 ↔ AC 대응표", rmap))

    # 2. assumptions and decisions to review
    review = []
    for a in an.get("assumptions") or []:
        review.append(f"- 가정: {_one_line(a)}")
    for st in proc.steps:
        res = _latest(results_by_step.get(st.id))
        for fd in (res or {}).get("findings") or []:
            if fd.get("severity") == codes.Severity.MAJOR.value:
                where = fd.get("file") or "?"
                if fd.get("line") is not None:
                    where += f":{fd['line']}"
                review.append(f"- major 지적 ({st.id}): `{where}` — {_one_line(fd.get('text', ''))}")
    verification = [p for p in changed if cfg.matches(codes.PathRuleKind.VERIFICATION.value, p)]
    for p in verification:
        review.append(f"- 바뀐 검증 경로: `{p}`")
    for p in s4.get("allowed_test_changes") or ():              # H21 (E9-2)
        review.append(f"- 사람이 허용한 기존 테스트 수정(내용만): `{_one_line(p)}` — "
                      + ("이 PR에서 바뀌었습니다" if p in changed else "이 PR에서 바뀌지 않았습니다"))
    for st in proc.steps:
        if st.kind != codes.StepKind.RUN.value:
            continue
        for f in _as_list(facts_by_step.get(st.id)):
            run = f.get("run") or {}
            rr = run.get("rerun")
            if rr and _red(run) and not _red(rr):
                review.append(f"- 불안정(flaky) 표시: `{st.id}` 시도 {f.get('attempt')} — 실패 뒤 같은 트리 재실행에서 "
                              "통과했습니다. 판정은 실패 그대로입니다(I8)")
            if run.get("head_flaky") is True:            # VW4 O1
                first = run.get("head") or {}
                review.append(f"- 불안정(flaky) 표시: `{st.id}` 시도 {f.get('attempt')} — 판정 트리 `test`가 "
                              f"{_exit(first)}로 통과하지 못한 뒤 같은 트리 재실행에서 통과해 통과로 판정했습니다"
                              f"(K8-2와 같은 규칙). 첫 실행 로그 `{_one_line(first.get('log_file') or '?')}` — 그 실패가 "
                              "안전망 테스트 자신의 것이면 그 테스트가 흔들립니다")
    for st in proc.steps:
        for f in _as_list(facts_by_step.get(st.id)):
            for d in ((f.get("session") or {}).get("permission_denials") or []):
                if d.get("tool_name") in DENIED_WRITE_TOOLS:
                    path = (d.get("tool_input") or {}).get("file_path") or (d.get("tool_input") or {}).get("path") or "?"
                    review.append(f"- 거절된 쓰기 ({st.id} 시도 {f.get('attempt')}): {d['tool_name']} `{path}`")
    golden = _golden_rows(proc, facts_by_step) if s3 is not None else []
    for g in golden:
        if g.get("row") == codes.GoldenRow.CONFIG.value:     # [P2] E33: a comparison-config change is a decision
            review.append(f"- 비교 설정 변경 (C): `{_one_line(g.get('path') or '?')}` — 완화인지는 `test-change-review`가 봅니다")
    if s3 is not None and isinstance(state.get("irreversible"), dict):
        review += _irreversible_lines(state)                    # stage 3 (E22–E24): the engine's detection
    else:
        for rule in cfg.path_rules(codes.PathRuleKind.IRREVERSIBLE.value):
            hits = [p for p in changed if globs.match_any(rule["globs"], p) is not None]
            level = rule.get("level") or codes.IrreversibleLevel.NOTIFY.value
            for p in hits:
                review.append(f"- 머지 뒤 되돌리기 어려운 변경 ({rule['category']}, {level}): `{p}`")
    if s3 is not None:
        for row in s3.get("followups") or ():
            if (isinstance(row, dict) and row.get("kind") == SECURITY_KIND and row.get("number")
                    and not row.get("dry_run") and not row.get("private_path")):
                review.append(f"- 보안 후속 이슈 #{row['number']} — 내용은 이슈에서")      # E21 (private repository)
    add(P_REVIEW, _section("가정과 검토할 결정", review))

    # 3. verification scope (facts only)
    status = {s["id"]: s for s in (state.get("steps") or [])}
    scope = ["엔진이 기록한 사실(facts)로 만든 표입니다 — 역할이 쓰지 않았습니다.", "",
             "| 단계 | 명령 | 결과 | 시도 | 검증한 HEAD |", "|---|---|---|---|---|"]
    for st in proc.steps:
        if st.kind != codes.StepKind.RUN.value:
            continue
        s = status.get(st.id, {})
        f = _latest(facts_by_step.get(st.id))
        if s.get("status") == codes.StepStatus.SKIPPED.value:
            scope.append(f"| `{st.id}` | `{st.name}` | 건너뜀 ({_cell(s.get('reason') or '이유 없음')}) | — | — |")
            continue
        head = (f.get("end_head") or "")[:12] if f else ""
        verdict = "통과 (종료 코드 0)"
        if s3 is not None and st.name in (codes.EVIDENCE_COMMANDS | codes.GIT_FACT_COMMANDS):
            verdict = "통과 (엔진 판정 — 조건 충족)"       # stage-3 interpretation 7: exit_code = the condition
        scope.append(f"| `{st.id}` | `{st.name}` | {verdict} | {s.get('latest_attempt')} | `{head}` |")
    add(P_SCOPE, _section("검증 범위", scope))

    # 4. not checked locally
    local = cfg.not_checked_locally()
    add(P_LOCAL, _section("로컬에서 확인하지 않은 항목",
                          [f"- {_one_line(e['name'])} — {_one_line(e['note'])}" for e in local]))

    # 5. Manual Test Checklist (as is)
    if isinstance(qa_checklist, str) and qa_checklist.strip():
        add(P_CHECKLIST, [CHECKLIST_HEADING, "", qa_checklist.rstrip("\n"), ""])
    else:
        add(P_CHECKLIST, [CHECKLIST_HEADING, "", "- 이 절차에는 qa 단계가 없습니다(수동 확인 항목 없음).", ""])

    if s3 is not None:
        included = _fix_lines(state, results_by_step, proc) + included      # E18: F first, then include D
    if security:
        found.append(f"- 보안 발견 {security}건 — 내용은 PR 본문에 쓰지 않습니다(E21). 비공개 저장소면 후속 이슈, "
                     "아니면 엔진 로컬 기록(`/gld status`)")
    add(P_FOUND, _section("범위 밖 발견", found))
    add(P_INCLUDED, _section("범위 밖이지만 포함한 수정", included))

    # 7. stage 2: the leader's verdicts and decisions (nothing is added when there is nothing to show)
    verdict = _verdict_lines(proc, results_by_step, an)
    if verdict is not None:
        add(P_VERDICTS, ["**인수 기준 판정 (리더)**", ""] + verdict + [""])
    decisions = _decision_lines(state, results_by_step, proc, leader.get("notes"))
    if decisions:
        add(P_DECISIONS, _section("리더 결정", decisions))

    # 9. stage 3 (V8, V16): appended after the stage-2 sections
    if s3 is not None:
        lines = _followup_lines(index if numbered else [], disp, s3.get("followups"), bool(s3.get("dry_run")),
                                is_private=s3.get("is_private"), deferred=len(state.get("deferred_rows") or []))
        if lines:
            add(P_FOLLOWUPS, _section("분리한 후속 이슈", lines))
        dismissed = [d for d in state.get("dismissed") or [] if isinstance(d, dict)]
        if dismissed:    # [P2] V13 (E32): a human dismissed a review's blockers — of that HEAD only
            add(P_DISMISSED, _section("사람이 기각한 지적", [
                f"- `{d.get('step')}` 시도 {d.get('attempt')} (HEAD `{str(d.get('head') or '')[:12]}`, {d.get('at')}) — "
                f"이유: {_one_line(d.get('reason') or '')}" + "".join(f"\n  - {_one_line(x)}" for x in d.get("findings") or [])
                for d in dismissed]))
        if golden:       # [P2] V14 (E33): rows from facts, reasons from the role (carried over)
            add(P_GOLDEN, _section("시각 변경", ["엔진이 기록한 사실(facts)로 만든 장부입니다. 이유는 역할이 낸 코드입니다.", "",
                                                 "| 행 | 경로 | 이전 경로 | 이유 |", "|---|---|---|---|"]
                                   + [f"| {g.get('row')} | `{_cell(g.get('path') or '')}` | "
                                      + (f"`{_cell(g['from'])}`" if g.get("from") else "—")
                                      + f" | {g.get('reason') or '(없음)'} |" for g in golden]))
        muts = _mutation_lines(s4.get("mutations"))
        if muts:         # stage 4 (VB9): what the engine saw, with the role's declaration
            add(P_MUTATIONS, _section("뮤테이션 실행", muts))
        repro = _repro_lines(proc, facts_by_step)
        if repro is not None:
            add(P_REPRO, _section("재현 증거 (버그)", repro))
        if proc.new_template_candidate:
            add(P_CANDIDATE, ["**새 템플릿 후보**: 예 — 리더가 표시했거나 plan이 카탈로그 단계를 2개 이상 더했습니다(evolve 입력)", ""])

    # 8. warnings
    totals = state.get("totals") or {}
    if isinstance(totals.get("warnings"), int):
        warn = totals["warnings"]
    else:
        warn = sum(len(f.get("warnings") or []) for v in facts_by_step.values() for f in _as_list(v))
    add(P_WARNINGS, [f"**측정용 사실 경고**: {warn}건"])

    out = _stack_lines(s4.get("stack"))
    if stage4 is None:           # stages 1–3: the sections one after the other, byte for byte as before
        out += [ln for _, lines in parts for ln in lines]
    else:                        # stage 4 (R2 6단계): summary · checklist · assumptions on top, the rest folded
        res = _done_gate_answer(proc, results_by_step)
        labels = {P_AC: f"{len(an['acs'])}개", P_LOCAL: f"{len(local)}개", P_DECISIONS: f"{len(decisions)}건",
                  P_VERDICTS: _verdict_counts(res), P_WARNINGS: f"측정용 사실 경고 {warn}건"}
        out += _stage4_layout(parts, _summary_lines(res, an, changed, verification, proc, state, facts_by_step), labels)
    return "\n".join(out) + "\n"


# --- stage 4: the PR body a reviewer reads top down (R2 6단계) ------------------------------------------------

P_AC, P_DEFERRED, P_MAP, P_REVIEW, P_SCOPE, P_LOCAL, P_CHECKLIST = (
    "ac", "deferred", "map", "review", "scope", "local", "checklist")
P_FOUND, P_INCLUDED, P_VERDICTS, P_DECISIONS, P_FOLLOWUPS, P_DISMISSED = (
    "found", "included", "verdicts", "decisions", "followups", "dismissed")
P_GOLDEN, P_MUTATIONS, P_REPRO, P_CANDIDATE, P_WARNINGS = ("golden", "mutations", "repro", "candidate", "warnings")
CHECKLIST_HEADING = "**Manual Test Checklist**"
STAGE4_CHECKLIST_HEADING = "**사람이 확인할 것 (Manual Test Checklist)**"
STAGE4_SUMMARY_HEADING = "**무엇을 바꿨나**"
STAGE4_FOLD_HEADING = "**근거와 기록** — 아래 항목은 접혀 있습니다. 제목을 누르면 펼쳐집니다."
STAGE4_TOP = (P_REVIEW, P_DEFERRED, P_FOUND, P_FOLLOWUPS, P_INCLUDED)
"""Open below the summary and the checklist: assumptions and decisions to review, deferred requirements, the
out-of-scope findings, the follow-up Issues split off from them (Q11, 2026-11-28: the engine files every recommended
follow-up without asking, so the numbers it made — and the existing Issues it commented on — are read, not folded)
and the out-of-scope fixes this PR carries."""
STAGE4_FOLDS = (P_AC, P_VERDICTS, P_MAP, P_SCOPE, P_REPRO, P_MUTATIONS, P_GOLDEN, P_LOCAL, P_DECISIONS,
                P_DISMISSED, P_CANDIDATE, P_WARNINGS)
"""Each one `<details>`, in this order. A part in neither list is folded at the end (never dropped)."""
FOLD_TITLES = {P_AC: "인수 기준 (AC)", P_VERDICTS: "인수 기준 판정 (리더)", P_MAP: "이슈 요구 ↔ AC 대응표",
               P_SCOPE: "검증 범위", P_REPRO: "재현 증거 (버그)", P_MUTATIONS: "뮤테이션 실행", P_GOLDEN: "시각 변경",
               P_LOCAL: "로컬에서 확인하지 않은 항목", P_DECISIONS: "리더 결정",
               P_DISMISSED: "사람이 기각한 지적", P_CANDIDATE: "새 템플릿 후보", P_WARNINGS: "엔진 기록"}
SUMMARY_LINE_MAX = 300


def _done_gate_answer(proc, results_by_step):
    st = _check_step(proc, codes.CheckKind.DONE_GATE.value)
    return _leader_answer(_latest(results_by_step.get(st.id))) if st else None


def _verdict_counts(res):
    verdicts = [v for v in (res or {}).get("ac_verdicts") or () if isinstance(v, dict)] if res else []
    counts = [(s, sum(1 for v in verdicts if v.get("status") == s)) for s in codes.AcVerdict.values()]
    return " · ".join(f"{s} {n}" for s, n in counts if n) or ""


def _summary_lines(res, an, changed, verification, proc, state, facts_by_step):
    """「무엇을 바꿨나」: the done-gate leader's `summary` (it read the whole diff — the only reader who did, before
    the human), labelled as the leader's; without one (an older answer, a human approval after an escalate with no
    lines) three engine-fact lines. Never invented: the fallback says it is facts."""
    lines = [_cut(x, SUMMARY_LINE_MAX) for x in (res or {}).get("summary") or () if isinstance(x, str) and x.strip()]
    if lines:
        return ["리더(LLM)가 diff를 읽고 쓴 요약입니다 — 엔진이 확인한 사실이 아닙니다.", ""] + [f"- {x}" for x in lines]
    status = {s["id"]: s.get("status") for s in state.get("steps") or []}
    runs = [st for st in proc.steps if st.kind == codes.StepKind.RUN.value]
    skipped = sum(1 for st in runs if status.get(st.id) == codes.StepStatus.SKIPPED.value)
    head = ""
    for st in reversed(proc.steps):
        f = _latest(facts_by_step.get(st.id))
        if f is not None:
            head = (f.get("end_head") or "")[:12]
            break
    counts = _verdict_counts(res)
    return ["리더 요약이 없어 엔진이 기록한 사실로 만든 요약입니다.", "",
            f"- 바뀐 파일 {len(changed)}개 — 검증 경로 {len(verification)}개, 그 밖 {len(changed) - len(verification)}개",
            f"- 인수 기준 {len(an['acs'])}개" + (f" — 리더 판정 {counts}" if counts else " — 리더 판정 없음"),
            f"- 실행 단계 {len(runs) - skipped}개 통과, 건너뜀 {skipped}개" + (f" (최종 HEAD `{head}`)" if head else "")]


def _fold(title, label, lines):
    """One `<details>` block of a section's lines without its own bold heading line (the summary names it); a
    one-line part ("**새 템플릿 후보**: 예 — …") keeps its line as is. Blank lines around the content so GitHub renders
    the markdown (tables) inside."""
    body = list(lines)
    if body and body[0] == f"**{title}**":
        body = body[1:]
    while body and body[0] == "":
        body = body[1:]
    while body and body[-1] == "":
        body = body[:-1]
    summary = f"{title} — {label}" if label else title
    return ["<details>", f"<summary>{summary}</summary>", ""] + body + ["", "</details>", ""]


def _stage4_layout(parts, summary, labels):
    """The stage-4 body below the stack block: the same part lines as the flat body, arranged (nothing dropped —
    tests/test_prbody.py Stage4Layout compares the two)."""
    by_key = dict(parts)
    out = [STAGE4_SUMMARY_HEADING, ""] + summary + [""]
    checklist = list(by_key.get(P_CHECKLIST) or [])
    if checklist and checklist[0] == CHECKLIST_HEADING:
        checklist[0] = STAGE4_CHECKLIST_HEADING
    out += checklist
    for key in STAGE4_TOP:
        out += by_key.get(key) or []
    out += [STAGE4_FOLD_HEADING, ""]
    order = list(STAGE4_FOLDS) + [k for k, _ in parts if k not in STAGE4_FOLDS + STAGE4_TOP + (P_CHECKLIST,)]
    for key in order:
        if key in by_key:
            out += _fold(FOLD_TITLES.get(key, key), labels.get(key, ""), by_key[key])
    return out


def title(issue_title, issue):
    """The PR title: the Issue title on one line (neutralised by github.create_pr), else `Issue <N>`."""
    t = _one_line(issue_title or "")
    if not t:
        if isinstance(issue, bool) or not isinstance(issue, int) or issue < 1:
            raise PrBodyError(f"bad issue number {issue!r}")
        return f"Issue {issue}"
    return t[:TITLE_MAX]
