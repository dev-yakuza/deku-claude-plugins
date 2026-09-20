#!/usr/bin/env python3
"""Guild 스프린트 로그에서 토큰/비용 실측치를 뽑는다.

사용법:
    python3 analyze_sprint_logs.py <repo>/.claude/guild/.sprint-logs [--sim]

입력은 슈퍼바이저가 남기는 `issue-<n>-<ts>-attempt<k>.log`(stream-json)다.

핵심 전제 — **청구되는 입력 토큰 = 매 턴의 prefix 크기의 합(적분)**.
    billed_input = Σ_turn (cache_read + cache_creation + input)
이 스크립트는 그 적분을 실제 로그에서 재구성하고, 다음으로 쪼갠다.
  · 모델별(메인 세션 vs 서브에이전트)
  · base(1턴차 prefix × 턴수) vs growth(누적분)
  · growth를 만들어낸 도구별 기여(= delta × 남은 턴수)
  · 컨텍스트에 주입된 콘텐츠의 출처별 분류

⚠ `usage`만 읽으면 안 된다. result 줄의 `.usage`는 **메인 세션분만**이고
  서브에이전트는 `.modelUsage`에만 들어 있다. 슈퍼바이저의 `Tokens:` 리포트가
  실제의 1/5을 찍는 이유가 이것이다(`.total_cost_usd`는 정확하다).

⚠ assistant 이벤트는 스트리밍 중 같은 message.id로 여러 번 나올 수 있다.
  message.id로 중복을 제거하지 않으면 적분이 ~1.6배 부풀어 modelUsage와 어긋난다.
"""

import collections
import glob
import json
import os
import re
import statistics
import sys

# 1M 토큰당 입력 단가(USD). 파생: cache read = 0.1x · cache write 5m = 1.25x · 1h = 2x ·
# output = 5x. ⚠ 이 표는 **실사용**된다(§7 달러 시뮬레이션). 예전에는 死코드였고, 그 때문에
# 문서가 "토큰 −38%"를 "달러 −38%"로 잘못 읽었다 — 압축은 **출력 비용을 1센트도 못 줄인다**.
RATES = {"claude-opus-5": 5.0, "claude-sonnet-5": 3.0, "claude-haiku-4-5": 1.0}
CACHE_READ, CACHE_WRITE_5M, CACHE_WRITE_1H, OUT_MULT = 0.1, 1.25, 2.0, 5.0


def price(model, *, cread=0, cwrite_5m=0, cwrite_1h=0, fresh=0, out=0):
    """토큰 구성요소를 달러로. 모르는 모델은 sonnet 요율로 본다(보수적)."""
    r = RATES.get(canon(model), 3.0) / 1_000_000
    return r * (cread * CACHE_READ + cwrite_5m * CACHE_WRITE_5M
                + cwrite_1h * CACHE_WRITE_1H + fresh + out * OUT_MULT)


def canon(model: str) -> str:
    return model.replace("[1m]", "")


def iter_events(path):
    """stream-json 로그를 읽는다. stderr가 섞여 있으므로 파싱 실패 줄은 건너뛴다."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def load(root):
    """로그를 훑어 세션/턴/도구 사용을 구조화한다."""
    logs = sorted(glob.glob(os.path.join(root, "*", "issue-*-attempt*.log")))
    if not logs:
        logs = sorted(glob.glob(os.path.join(root, "issue-*-attempt*.log")))
    out = []
    for path in logs:
        rel = os.path.relpath(path, root)
        result = None
        seen = {}   # message.id -> calls[parent] 내 인덱스(없으면 None)
        # key: parent_tool_use_id(None이면 메인 세션) -> 턴별 prefix 크기
        prefixes = collections.defaultdict(list)
        # 같은 key -> 턴별로 그 턴이 호출한 도구 이름들
        calls = collections.defaultdict(list)
        # 같은 key -> 턴별 tool_use **id** 목록. ⚠ `calls`(이름)와 따로 둔다 — 한 턴이 같은
        # 도구를 여러 번 부르는 일이 흔하고(실측: 도구 호출 턴의 17.9%, 2,244 호출),
        # 이름으로 합집합을 만들면 그 중복이 **사라진다**. 4c 의 결과 귀속은 id 로 한다.
        call_ids = collections.defaultdict(list)
        pending = {}          # tool_use_id -> (tool name, command/path, parent)
        results = []          # (tool, arg, parent, result bytes)
        results_all = []      # 모든 result 줄 — **실패 판정 전용**(비용은 마지막 줄)
        by_id = {}            # tool_use_id -> (tool, arg, result bytes)  — 4c 의 정확 귀속용
        spills = []           # 스필을 만든 Bash 커맨드 (A21 잔여 해소)
        bodies = {}           # tool_use_id -> 라벨 질의 결과 본문(4KB 상한) — 스테이지 복구용
        spawns = {}           # tool_use_id -> description
        for ev in iter_events(path):
            kind = ev.get("type")
            msg = ev.get("message") or {}
            parent = ev.get("parent_tool_use_id")
            if kind == "result":
                # ⚠ `result` 줄은 **로그당 1개가 아니다**(실측 38로그 중 15개가 다중, 최대 13개).
                # 세 필드의 의미가 다르다: `total_cost_usd` 는 **누적**, `modelUsage` 는 세션
                # **최종 스냅샷**, `.usage` 는 **세그먼트별**. 그래서 `result` 는 계속 마지막
                # 줄을 쓰고(비용·modelUsage 가 거기 있다), **실패 판정만** 전 줄을 본다.
                # 오늘 두 판정이 일치하는 이유는 실패가 항상 마지막이기 때문이고, 그 이유는
                # 세션이 거기서 끝나기 때문이다 — `--resume`(M3)이 그 순서를 뒤집는다.
                result = ev
                results_all.append(ev)
            elif kind == "assistant":
                # tool_use 등록은 중복 이벤트여도 멱등하므로 먼저 한다. dedup을 먼저 하면
                # 중복 message.id 안의 tool_use 가 통째로 등록되지 않아 4·5절이 비게 된다.
                names, ids = [], []
                for block in msg.get("content") or []:
                    if block.get("type") != "tool_use":
                        continue
                    inp = block.get("input") or {}
                    arg = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                    # ⚠⚠ **Write/Edit 의 본문에서 품질 마커를 건져낸다.** `arg` 는 경로이지
                    #    본문이 아니라서, `_bash_rules.md` 가 강제하는 「본문은 임시 파일 +
                    #    `--body-file`」 경로를 타면 §10 의 마커가 **커맨드에서 사라진다**.
                    #    실측(arm-C): qa 체크리스트가 6/6 PR 에 실제로 들어갔는데 §10 은 **3**
                    #    으로 셌고, 전이당으로는 **−58%** 로 보고했다 — **정상 런을 품질 열화로
                    #    판정**한다. M1 A/B 의 품질 축이 이것이므로 그대로 두면 실험이 무의미하다.
                    #    ⚠ 본문 전체는 보존하지 않는다(메모리). **마커 문자열만** 이어 붙인다.
                    _c = inp.get("content") or inp.get("new_string") or ""
                    if isinstance(_c, str) and _c:
                        _hit = [_m for _m, _ in _QUALITY_MARKERS if _m in _c]
                        if _hit:
                            arg = arg + " \x00markers:" + ",".join(_hit)
                    pending[block["id"]] = (block["name"], arg, parent)
                    names.append(block["name"])
                    ids.append(block["id"])
                    if block["name"] in ("Task", "Agent"):
                        # (description, 리더가 명시한 model) — model 이 None 이면 세션 모델 상속
                        spawns[block["id"]] = (inp.get("description") or "?", inp.get("model"))
                # ⚠⚠ stream-json 은 assistant 메시지 하나를 **콘텐츠 블록마다 한 이벤트**로
                # 내보낸다 — 같은 `message.id`, **바이트 단위로 같은 `usage`**. 모델은 보통
                # "text 한 줄 → tool_use" 순으로 내므로, 첫 이벤트만 남기면 **툴을 부른 턴이
                # 통째로 「도구 호출 없는 턴」으로 분류된다.** 실측: 그 오분류가 메인 세션
                # 무툴 턴을 3.3% → 62% 로, 「모델 출력」 적분 기여를 0.5% → 44.2% 로 부풀렸다.
                # 그래서 **prefix 는 한 번만 세고(usage 가 동일하므로 옳다), names 는 같은
                # message.id 의 모든 이벤트에서 합집합으로 모은다.**
                mid = msg.get("id")
                if mid in seen:
                    par0, idx = seen[mid]
                    if idx is not None:
                        slot = calls[par0][idx]
                        for n in names:
                            if n not in slot:      # 이름은 dedup 해도 된다(3절이 이름 기준)
                                slot.append(n)
                        # ⚠ id 는 **절대 dedup 하지 않는다.** 같은 턴의 같은 도구 중복 호출이
                        # 여기서 사라지면 4c 의 결과 귀속이 세션 끝까지 어긋난다.
                        call_ids[par0][idx].extend(ids)
                    continue
                usage = msg.get("usage") or {}
                size = (
                    usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                    + usage.get("input_tokens", 0)
                )
                if size:
                    prefixes[parent].append(size)
                    calls[parent].append(list(names))
                    call_ids[parent].append(list(ids))
                    # ⚠ parent 를 함께 기억한다 — 조회 시 이벤트의 parent 를 쓰면 같은 mid 가
                    # 다른 parent 로 올 때 엉뚱한 슬롯을 건드린다(현 데이터 0건이나 무료 방어).
                    seen[mid] = (parent, len(calls[parent]) - 1)
                else:
                    seen[mid] = (parent, None)
            elif kind == "user":
                for block in msg.get("content") or []:
                    if block.get("type") != "tool_result":
                        continue
                    hit = pending.get(block.get("tool_use_id"))
                    if not hit:
                        continue
                    body = block.get("content")
                    _ser = json.dumps(body, ensure_ascii=False) if body is not None else ""
                    size = len(_ser)
                    # ⚠ **스필을 만든 쪽**을 기록한다. 기존 코드는 `arg` 에 `tool-results/` 가
                    #    있는 것 — 즉 **재독** — 만 봤고, 「그 파일을 애초에 누가 만들었나」는
                    #    임시 스크립트에서만 나왔다(A21 잔여). 직렬화는 size 계산에서 이미
                    #    하므로 추가 비용이 없다.
                    if "tool-results/" in _ser:
                        # ⚠ 도구 종류를 **같이** 남긴다. 플랜은 「스필 생성 203/203 이 Bash」라고
                        #    적었는데 Bash 만 세면 그 주장을 **검증할 수 없다** — 분모가 사라진다.
                        spills.append((hit[0], hit[1]))
                    results.append((hit[0], hit[1], hit[2], size))
                    by_id[block["tool_use_id"]] = (hit[0], hit[1], size)
                    # ⚠ 본문은 **라벨 질의에 한해서만** 보존한다. 스테이지 경계를 복구하려면
                    # `gh issue view --json labels` 의 **결과 본문**이 필요한데, 크기만 남기면
                    # 200 스폰 중 52가 스테이지 미상이 되고 루프백 검출이 36 → 31 로 떨어진다.
                    # (재개 attempt 는 라벨이 이미 맞아 전이 커맨드를 안 내보낸다.)
                    # 전 결과를 보존하면 메모리가 터지므로 **질의 모양 + 4KB 상한**으로 막는다.
                    if "label" in (hit[1] or "") and body is not None:
                        bodies[block["tool_use_id"]] = json.dumps(
                            body, ensure_ascii=False)[:4000]
        out.append(dict(log=rel, result=result, prefixes=prefixes, calls=calls,
                        call_ids=call_ids, by_id=by_id, results=results, spawns=spawns,
                        bodies=bodies, results_all=results_all, spills=spills))
    return out


def failed(session):
    """⚠ 실패 판정은 **「`is_error:true` 인 result 줄이 하나라도」** 다 — 마지막 줄이 아니다.

    오늘 두 규칙이 일치하는 것은 실패가 항상 마지막이기 때문이고, 그 이유는 **세션이 거기서
    끝나기 때문**이다(실측: `is_error` 15건이 전부 자기 로그의 마지막 줄). M3(`--resume`)는
    정확히 그 순서를 뒤집는다 — 429 뒤에 성공 세그먼트가 붙으면 마지막 줄은 `completed` 이고
    **429 비중이 개선 여부와 무관하게 ~0% 로 내려간다.** 즉 M3 가 자기 성공을 자동 선언한다.

    ⚠ 판별자는 `subtype` 이 **아니다** — 429 로 죽은 줄도 `subtype:"success"` 였다(15/15).
    ⚠ 그리고 이 판정을 **비용 합산에 쓰면 안 된다** — `total_cost_usd` 는 누적값이라 전 줄을
    더하면 $832 → $2,142 로 튄다.
    """
    for ev in (session.get("results_all") or ([session["result"]] if session.get("result") else [])):
        if ev.get("is_error") or (ev.get("terminal_reason") or "completed") != "completed":
            return True
    return False


def settled(sessions):
    """아직 도는 세션을 제외한다.

    ⚠ 진행 중인 자식은 `result` 줄이 **아직 없다.** 그러면 `modelUsage`에 0을 기여하면서
    prefix 는 전부 기여하므로, 섞으면 적분이 modelUsage 를 초과하고 §1의 정합성 검증이
    깨진다(실측: 스프린트 한 건이 도는 중에 +7.6%). 429로 죽은 세션은 `result`(`is_error`)를
    남기므로 여기서 빠지지 않는다 — 빠지는 것은 **아직 안 끝난 것뿐이다.**
    """
    done = [s for s in sessions if s["result"]]
    skipped = len(sessions) - len(done)
    if skipped:
        print(f"⚠ 진행 중인 세션 {skipped}개를 제외했다(아직 result 줄이 없다):")
        for s in sessions:
            if not s["result"]:
                print(f"    {s['log']}")
        print()
    return done


def money(sessions):
    print("=" * 78)
    print("1. 비용 — modelUsage 기준(서브에이전트 포함, total_cost_usd와 정합)")
    print("=" * 78)
    agg = collections.defaultdict(collections.Counter)
    total = 0.0
    dead = 0.0
    retry = 0.0
    per_issue = collections.Counter()
    main_only_cr = 0
    for s in sessions:
        res = s["result"] or {}
        cost = res.get("total_cost_usd", 0) or 0
        total += cost
        main_only_cr += (res.get("usage") or {}).get("cache_read_input_tokens", 0)
        if failed(s):
            dead += cost
        m = re.search(r"issue-(\d+)-.*-attempt(\d+)\.log", s["log"])
        if m:
            per_issue[m.group(1)] += cost
            if int(m.group(2)) > 1:
                retry += cost
        for model, d in (res.get("modelUsage") or {}).items():
            c = agg[canon(model)]
            for k in ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens"):
                c[k] += d.get(k, 0)
            c["costUSD"] += d.get("costUSD", 0)
    head = f"{'model':18s} {'in':>8} {'out':>11} {'cacheRead':>14} {'cacheWrite':>11} {'cost$':>9} {'share':>7}"
    print(head)
    for model, c in sorted(agg.items(), key=lambda kv: -kv[1]["costUSD"]):
        share = c["costUSD"] / total * 100 if total else 0
        print(f"{model:18s} {c['inputTokens']:8,} {c['outputTokens']:11,} "
              f"{c['cacheReadInputTokens']:14,} {c['cacheCreationInputTokens']:11,} "
              f"{c['costUSD']:9.2f} {share:6.1f}%")
    cr = sum(c["cacheReadInputTokens"] for c in agg.values())
    cw = sum(c["cacheCreationInputTokens"] for c in agg.values())
    out = sum(c["outputTokens"] for c in agg.values())
    print(f"\n  합계 ${total:,.2f} · 세션 {len(sessions)}개")
    _t = cr + cw + out
    print(f"  cache read {cr:,} = 전체 토큰의 {cr / _t * 100:.1f}%" if _t else
          "  ⚠ 토큰이 0 — modelUsage 가 빈 세션만 들어왔다(429 사망 등)")
    if main_only_cr:
        print(f"  ⚠ 슈퍼바이저의 `Tokens:` 줄은 .usage만 읽어 cache read를 "
              f"{main_only_cr:,}로 보고한다 — 실제의 1/{cr / main_only_cr:.1f}")
    print(f"\n  api_error/미완료로 끝난 세션에 든 비용: ${dead:,.2f} ({dead / total * 100:.0f}%)")
    print(f"  attempt>=2 에 든 비용:                  ${retry:,.2f} ({retry / total * 100:.0f}%)")
    print("\n  이슈별 비용:")
    for issue, cost in per_issue.most_common(10):
        print(f"    #{issue:<6} ${cost:8.2f}")


def integral(sessions):
    print()
    print("=" * 78)
    print("2. prefix 적분 — 청구 입력 토큰의 정체")
    print("=" * 78)
    main, sub = {}, {}
    for s in sessions:
        for parent, seq in s["prefixes"].items():
            (sub if parent else main)[(s["log"], parent)] = seq

    def report(label, d):
        total = sum(sum(v) for v in d.values())
        base = sum(v[0] * len(v) for v in d.values())
        turns = sum(len(v) for v in d.values())
        lens = sorted(len(v) for v in d.values())
        last = sorted(v[-1] for v in d.values())
        first = [v[0] for v in d.values()]
        p90 = lambda xs: xs[int(len(xs) * 0.9)] if xs else 0
        print(f"\n  {label}: 세션 {len(d)}개 · 턴 {turns:,} · 적분 {total:,}")
        print(f"    base(1턴차 prefix × 턴수) {base:,} = {base / (total or 1) * 100:.1f}%"
              f"   growth {100 - base / total * 100:.1f}%")
        print(f"    턴/세션  중앙 {statistics.median(lens):.0f}  p90 {p90(lens)}  최대 {max(lens)}")
        print(f"    1턴차 prefix 중앙 {statistics.median(first):,.0f}"
              f"   최종 prefix 중앙 {statistics.median(last):,.0f}"
              f"  p90 {p90(last):,}  최대 {max(last):,}")
        return total

    a = report("MAIN (자식 메인 세션)", main)
    b = report("SUB  (서브에이전트)", sub)
    print(f"\n  합계 적분 {a + b:,}")
    return main, sub


def _rank(v):
    """평균 순위(동점 처리 포함)."""
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def _spearman(xs, ys):
    """순위 Pearson. scipy 없이. 표본 부족/분산 0 이면 None."""
    if len(xs) < 30:
        return None
    a, b = _rank(xs), _rank(ys)
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = sum((v - ma) ** 2 for v in a) ** 0.5
    db = sum((v - mb) ** 2 for v in b) ** 0.5
    return None if da == 0 or db == 0 else num / (da * db)


def selfcheck(sessions, integral_total, tol=0.03):
    """⚠ 도구의 유일한 자기검사. **문장이 아니라 코드여야 한다.**

    예전에는 두 수를 다른 절에 따로 찍고 "일치해야 한다"고 산문으로만 적었다 —
    사람이 눈으로 두 표를 비교하지 않으면 발화하지 않는 검사였다.
    """
    ref = 0
    for s in sessions:
        for _m, d in ((s["result"] or {}).get("modelUsage") or {}).items():
            ref += d.get("cacheReadInputTokens", 0) + d.get("cacheCreationInputTokens", 0)
    if not ref:
        print("⚠ modelUsage 가 비었다 — 정합성 검증 불가")
        return
    # ⚠ **두 번째 축이 필요하다.** 아래 적분 대조는 `prefixes` 만 본다 — 턴별 도구 목록
    # (`calls`/`call_ids`)이 오염돼도 적분은 한 토큰도 안 변해서 `[OK]` 를 찍는다. 실제로
    # 이름 dedup 버그가 그 상태로 통과했고, 4c 표가 Bash 54.7%(실제 46.7%)를 보고했다.
    # 등록된 tool_use 수 == 소비된 tool_result 수 를 단언한다.
    # ⚠ **범위를 정확히**: 이 검사가 잡는 것은 «턴에 id 가 덜 쌓이는» 회귀다 — 실측 변이
    # "연속 이벤트의 id 를 버린다"(= 옛 결함의 재현)에서 +92.2% 로 붉어진다. 잡지 **못하는**
    # 것은 turn 과 result 의 **짝이 어긋나되 개수는 맞는** 경우다.
    # ⚠⚠ 여기에 예전에는 "그건 4c 가 id 로 직접 조회하므로 구조적으로 생기지 않는다"고
    # 적혀 있었다. **단언은 검사가 아니었다.** 각 parent 의 call_ids 턴 목록을 1칸 회전시키는
    # 변이(개수·바이트·prefix 전부 보존)를 넣으면 위 두 축이 바이트 단위로 같은 출력을 내면서
    # 4c 의 1위 항목이 34.69% → 48.39% 로 14 포인트 움직인다. 그래서 세 번째 축을 건다.
    reg = con = 0
    for x in sessions:
        for par, turns in x["call_ids"].items():
            reg += sum(len(t) for t in turns)
        con += len(x["by_id"])
    if reg and abs(con / reg - 1) > 0.01:
        print(f"\n  ✗ 턴에 등록된 tool_use {reg:,} vs 결과가 있는 tool_use {con:,} "
              f"= {(con / reg - 1) * 100:+.1f}% — 턴↔결과 귀속이 깨졌다(4c 표를 믿지 마라).")
        sys.exit(1)
    print(f"  턴↔결과 귀속: tool_use {reg:,} · 결과 {con:,}  [OK]")

    # ── 축 3: 귀속이 **옳은지**. 결과 바이트가 클수록 그 턴의 prefix delta 가 커야 한다.
    # 개수 보존 치환(회전·셔플)은 이 상관만 무너뜨린다. 실측: 정상 ρ=0.74 · 1칸 회전 ρ=0.25.
    xs, ys = [], []
    for x in sessions:
        by_id = x["by_id"]
        for parent, seq in x["prefixes"].items():
            for i in range(len(seq) - 1):
                delta = seq[i + 1] - seq[i]
                if delta <= 0:
                    continue
                take = [by_id[t] for t in x["call_ids"][parent][i] if t in by_id]
                if not take:
                    continue
                xs.append(sum(t[2] for t in take))
                ys.append(delta)
    rho = _spearman(xs, ys)
    if rho is not None:
        # ⚠ 임계 0.60 은 실측으로 고른 값이다. 전역 정상 0.755 · 회전 변이 0.254, 그리고
        # 부분집합(세션 3/5/10개 × 각 20회 무작위)에서 **거짓 양성 0 · 회전 검출 100%**.
        # ⚠ 세션별로는 걸지 않는다 — (log,parent) 입도로 보면 98개 중 **16개**가 0.6 미만이라
        # 정상 데이터가 그대로 붉어진다. (예전 주석은 "1개"라고 적었으나 어떤 입도에서도
        # 재현되지 않았다 — 결론은 같고 근거만 틀렸던 경우다.)
        # ⚠ 알려진 거짓 양성 경로: 읽기 출력에 **하드 캡**을 걸면 x 에 동점이 쌓여 ρ 가
        # 내려간다. 실측 500B 캡에서 0.613 — 임계 바로 위다. 캡을 도입하면 이 값을 다시 볼 것.
        if rho < 0.60:
            print(f"\n  ✗ 결과바이트↔delta Spearman ρ={rho:.3f} < 0.60 — 턴↔결과 귀속이 "
                  f"개수는 맞지만 **짝이 어긋났다**(4c 표를 믿지 마라).")
            sys.exit(1)
        print(f"  결과바이트↔delta 상관: Spearman ρ={rho:.3f} (n={len(xs):,})  [OK]")
    else:
        # ⚠ 침묵하지 않는다. 표본이 30 미만이면 축3 은 판정을 못 하는데, 아무 줄도 안 찍으면
        # 「통과」와 구별되지 않는다 — 이 파일이 다른 곳에서 고치고 있는 바로 그 실패 모양이다.
        # ⚠ None 은 **두 경로**다 — 표본 부족과 분산 0. 둘을 한 메시지로 묶으면 거짓을
        # 보고한다(실측: `_spearman([5]*40, range(40))` 은 n=40 인데 None 이다). 그리고 이
        # 경로는 가상이 아니다 — 읽기 출력에 하드 캡을 세게 걸면 x 가 상수에 가까워진다.
        _why = ("표본 부족(n=%d < 30)" % len(xs)) if len(xs) < 30 else "분산 0(한쪽 축이 상수)"
        print(f"  ⚠ 결과바이트↔delta 상관: {_why} — 축3 **판정 없음**")
    err = integral_total / ref - 1
    ok = abs(err) <= tol
    print(f"\n  정합성: 적분 {integral_total:,} vs modelUsage(cacheRead+cacheWrite) {ref:,} "
          f"= {err * 100:+.2f}%  [{'OK' if ok else 'FAIL'}]")
    if not ok:
        print(f"  ✗ 허용치 ±{tol * 100:.0f}% 초과 — 이 상태의 분석은 읽을 가치가 없다.")
        print("    의심 순서: ① 진행 중 세션 혼입 ② message.id 중복 제거 ③ 블록 분할 합집합")
        sys.exit(1)


def scope_model(sessions):
    """scope × model 로 적분을 가른다.

    ⚠ **M1 의 기대효과가 전적으로 이 표에 달려 있다.** 예전 문서는 "Opus = 메인 세션,
    Sonnet = 서브에이전트"로 단정해 opus 비용 전액을 메인에 귀속했는데, 실측은 opus 적분의
    **23%가 서브에이전트**다(리더가 스폰에 `model: opus` 를 실은 것). M1 은 그것을
    건드리지 않으므로, 전액 귀속은 절감을 ~20% 과대평가한다.
    """
    print()
    print("=" * 78)
    print("2b. scope × model — M1 의 실제 대상")
    print("=" * 78)
    agg = collections.Counter()
    turns = collections.Counter()
    notool = collections.Counter()
    allturns = collections.Counter()
    for s in sessions:
        for parent, seq in s["prefixes"].items():
            scope = "sub" if parent else "main"
            names_by_turn = s["calls"][parent]
            for i, p in enumerate(seq):
                allturns[scope] += 1
                if not names_by_turn[i]:
                    notool[scope] += 1
            # 모델은 세션 단위로 고정이다 — 스폰의 선언 model, 없으면 세션 기본
            mdl = None
            if parent:
                mdl = (s["spawns"].get(parent) or (None, None))[1]
            key = (scope, mdl or ("session-default" if not parent else "unset(→persona sonnet)"))
            agg[key] += sum(seq)
            turns[key] += len(seq)
    total = sum(agg.values()) or 1
    print(f"{'scope / 선언 model':40s} {'적분':>15} {'share':>7} {'turns':>7}")
    for k, v in agg.most_common():
        print(f"{k[0] + ' / ' + str(k[1]):40s} {v:15,} {v / total * 100:6.1f}% {turns[k]:7,}")
    print()
    for scope in ("main", "sub"):
        if allturns[scope]:
            print(f"  {scope}: 도구 미호출 턴 {notool[scope]:,} / {allturns[scope]:,} "
                  f"= {notool[scope] / allturns[scope] * 100:.1f}%   ← §4 게이트가 읽는 값")
    print("\n  ⚠ 이 비율은 예전에 62%로 잘못 보고됐다(블록 분할 미합집합). 게이트를 이 출력으로 건다.")
    return agg


def growth_by_tool(sessions):
    print()
    print("=" * 78)
    print("3. growth 기여도 — 어떤 도구가 prefix를 키웠나 (delta × 남은 턴수)")
    print("=" * 78)
    cost = collections.Counter()
    added = collections.Counter()
    turns = collections.Counter()
    for s in sessions:
        for parent, seq in s["prefixes"].items():
            names_by_turn = s["calls"][parent]
            scope = "sub" if parent else "main"
            n = len(seq)
            for i in range(n - 1):
                delta = seq[i + 1] - seq[i]
                if delta <= 0:
                    continue
                names = names_by_turn[i] or ["(모델 자신의 출력·thinking)"]
                for name in names:
                    key = (scope, name)
                    cost[key] += delta * (n - 1 - i) / len(names)
                    added[key] += delta / len(names)
                    turns[key] += 1
    total = sum(cost.values())
    print(f"{'scope/tool':34s} {'turns':>6} {'주입 tok':>11} {'적분 기여':>14} {'share':>7}")
    for key, value in cost.most_common(14):
        print(f"{key[0] + '/' + key[1]:34s} {turns[key]:6,} {int(added[key]):11,} "
              f"{int(value):14,} {value / total * 100:6.1f}%")


def content_sources(sessions):
    print()
    print("=" * 78)
    print("4. 컨텍스트에 주입된 콘텐츠의 출처")
    print("=" * 78)
    buckets = collections.Counter()
    counts = collections.Counter()
    guild = collections.Counter()
    gcount = collections.Counter()
    for s in sessions:
        for tool, arg, _parent, size in s["results"]:
            if "tool-results/" in arg:
                key = "Claude Code 가 흘린 tool-results/*.txt 재독"
            elif "guild-plugin" in arg:
                key = "guild-plugin 지시문"
                m = re.search(r"skills/gld/(\S+?\.(?:md|py|sh|tmpl))", arg)
                name = m.group(1) if m else arg[:50]
                guild[name] += size
                gcount[name] += 1
            elif "docs/specs/" in arg:
                key = "docs/specs/<issue>/ (Guild 산출물)"
            elif "docs/standards" in arg:
                key = "docs/standards/"
            elif ".claude/" in arg:
                key = ".claude/ (페르소나·knowledge·gates)"
            elif tool == "Bash":
                key = "Bash (그 외 커맨드 출력)"
            elif tool == "Read":
                key = "Read (레포 소스·테스트)"
            else:
                key = f"{tool} (그 외)"
            buckets[key] += size
            counts[key] += 1
    total = sum(buckets.values())
    print(f"{'출처':46s} {'calls':>6} {'bytes':>12} {'share':>7}")
    for key, value in buckets.most_common():
        print(f"{key:46s} {counts[key]:6,} {value:12,} {value / total * 100:6.1f}%")
    print(f"\n  합계 {total:,}B (~{total // 4:,} tok)")
    if guild:
        gt = sum(guild.values())
        print(f"\n  guild-plugin 지시문 내역 ({gt:,}B ~{gt // 4:,} tok "
              f"= 세션당 {gt // max(len(sessions), 1) // 4:,} tok)")
        for name, value in guild.most_common(10):
            print(f"    {gcount[name]:4d}회 {value:10,}B {value / gt * 100:5.1f}%  {name}")


# 루프백/재작업 성격의 스폰. M1(모델 기본값 하향)의 **품질 대가**를 읽는 지표이므로
# 비용 지표와 반드시 같이 본다 — 싸졌는데 루프백이 늘었으면 절감이 아니다.
LOOPBACK_RE = re.compile(r"redo|retry|재스캔|정정|복원|2차|배선", re.I)


def source_integral(sessions):
    """출처별 **적분 기여**. ⚠ 바이트 점유율과 다른 축이다.

    초반에 읽힌 지시문은 남은 턴수 승수가 커서 바이트 비례가 체계적으로 왜곡한다.
    예전 문서의 §0 표(지시문 2.26% 등)는 이 계산 없이 손으로 적은 값이라 재현되지 않았다.
    """
    print()
    print("=" * 78)
    print("4c. 출처별 적분 기여 (delta 를 그 턴의 tool_result 에 바이트 가중 배분 × 남은 턴수)")
    print("=" * 78)

    def bucket(tool, arg):
        if "tool-results/" in arg:
            return "Claude Code 가 흘린 tool-results/*.txt 재독"
        if "guild-plugin" in arg:
            return ("guild 지시문: _execute_spine.md" if "_execute_spine" in arg
                    else "guild 지시문: 그 외")
        if "docs/specs/" in arg:
            return "docs/specs/<issue>/ (Guild 산출물)"
        if "docs/standards" in arg:
            return "docs/standards/"
        if ".claude/" in arg:
            return ".claude/ (페르소나·knowledge·gates)"
        if tool == "Bash":
            return "Bash 커맨드 출력"
        if tool == "Read":
            return "Read (레포 소스·테스트)"
        return f"{tool}"

    cost = collections.Counter()
    # ⚠ `docs/standards/` 를 **파일별로** 쪼갠다. `_preflight.md` 가 「verification.md 하나가
    #    가장 크다」고 지시하는데, 그 수를 도구가 찍지 않으면 규율 7(「이 절이 찍지 않는 수는
    #    인용하지 마라」) 위반이다 — 라운드 6 지적.
    std = collections.Counter()
    base = 0
    for s in sessions:
        by_id = s["by_id"]
        for parent, seq in s["prefixes"].items():
            n = len(seq)
            base += seq[0] * n
            for i in range(n - 1):
                delta = seq[i + 1] - seq[i]
                if delta <= 0:
                    continue
                # ⚠ **id 로 직접 조회한다.** 예전에는 결과를 도착 순 pool 에서
                # `pool[k:k+len(names)]` 로 잘라 썼는데, ① 이름 dedup 으로 len(names) 가
                # 줄면 k 가 덜 전진하고 ② `delta<=0` 로 건너뛴 턴의 결과가 소비되지 않아,
                # 어긋남이 **세션 끝까지 누적**됐다. 당시 실측 오차: Bash 46.7% → 54.7%,
                # docs/specs 8.7% → 6.6%. id 조회에는 그 표류가 없다.
                # ⚠ 위 네 수는 **그때의(rev2) 값**이다 — 이후 경로 앵커를 통일해(rev3)
                # 기준선 자체가 Bash 34.69% · docs/specs 16.92% 로 옮겼다. 결함의 방향을
                # 기록한 것이지 현재 값이 아니다. 지금 값과 비교하지 마라.
                take = [by_id[t] for t in s["call_ids"][parent][i] if t in by_id]
                if not take:
                    cost["모델 출력·thinking(추정)"] += delta * (n - 1 - i)
                    continue
                tot_b = sum(t[2] for t in take) or 1
                for tool, arg, size in take:
                    b = bucket(tool, arg)
                    c = delta * (n - 1 - i) * size / tot_b
                    cost[b] += c
                    if b == "docs/standards/":
                        m = _STD_FILE.search(arg)
                        std[m.group(1) if m else "(파일명 불명)"] += c
    cost["base prefix (시스템+CLAUDE.md+툴+스킬)"] = base
    total = sum(cost.values()) or 1
    print(f"{'출처':46s} {'적분 기여':>15} {'share':>7}")
    for k, v in cost.most_common():
        print(f"{k:46s} {int(v):15,} {v / total * 100:6.2f}%")
    g = sum(v for k, v in cost.items() if k.startswith("guild 지시문"))
    es = cost["guild 지시문: _execute_spine.md"]
    print(f"\n  guild 지시문 전체 {g / total * 100:.2f}%   그중 _execute_spine.md {es / total * 100:.2f}%")
    print(f"  → 묶음 E(그 파일 ⚠ 줄 31.5%) 상한 = {es * 0.315 / total * 100:.2f}%")
    if std:
        print(f"\n  `docs/standards/` {cost['docs/standards/'] / total * 100:.2f}% 의 파일별 내역")
        for k, v in std.most_common(6):
            print(f"    {k:40s} {int(v):13,} {v / total * 100:5.2f}%")
        print("    ⚠ 이 내역이 `_preflight.md` Item 2 의 「어느 표준을 끌어올 것인가」 근거다.")

    # ⚠ **스필을 만든 쪽의 분류** — `_bash_rules.md` 가 「tool-results 재독 3.88% 는 대부분
    #    M5 의 2차 효과다」라고 적는데, 그 「대부분」의 근거가 도구 밖(임시 스크립트)에 있었다.
    #    A21 의 잔여분이고 규율 7 위반이었다.
    sp_all = [t for s2 in sessions for t in (s2.get("spills") or [])]
    sp = [c for t, c in sp_all if t == "Bash"]
    other = collections.Counter(t for t, _ in sp_all if t != "Bash")
    if sp:
        cl = [_classes(c) for c in sp]
        rd = sum(1 for c in cl if "read" in c or "search" in c or "list" in c)
        pure = sum(1 for c in cl if c == {"read"})
        print(f"\n  스필을 **만든** Bash {len(sp)}건의 분류 (`_classes()`)")
        print(f"    파일 끌어오기를 품은 것  {rd:5d}  = {rd / len(sp) * 100:.0f}%  ← M5 의 2차 효과 **상한**")
        print(f"    순수 읽기만              {pure:5d}  = {pure / len(sp) * 100:.0f}%  ← 같은 것의 **하한**")
        print(f"    독립 항목(테스트·git 등) {len(sp) - rd:5d}  = {(len(sp) - rd) / len(sp) * 100:.0f}%")
        print(f"    스필 생성 **{len(sp)}/{len(sp_all)} 이 Bash**" + (f" · 나머지: {dict(other)}" if other else " (전부)"))
        print("    ⚠ 그래서 3.88% 를 통째로 M5 의 몫으로 세면 **이중 계상**이다.")


_STD_FILE = re.compile(r"docs/standards/([A-Za-z0-9_.\-]+\.md)")
_PURE_READ = ("cat", "sed", "head", "tail", "less", "more")
_SEARCH = ("grep", "rg", "awk")
_LIST = ("ls", "find", "wc")
# ⚠ 커맨드의 **첫 낱말만** 보면 안 된다 — 라운드 5 실측에서 「진짜 커맨드」 버킷의 **59.8%**가
# 읽기를 품고 있었다. `cd <dir> && sed -n '1,145p' skeleton.md`(head=`cd`),
# `echo "=== x ===" && cat x`(head=`echo`), `for f in …; do cat …; done`(head=`for`),
# 줄바꿈 이어쓰기(head=`\`), 변수 대입(head=`D="…"`) 전부 그렇게 샜다.
# **아이러니**: `_bash_rules.md` 는 복합 커맨드를 FORBIDDEN 으로 금지한다. head[0] 분류는
# 그 규칙이 지켜진다는 전제에서만 맞는데, **같은 데이터가 안 지켜짐을 증명한다**(위반율 60.1%).
_WRAP = ("time", "env", "sudo", "nohup", "timeout", "do", "then", "else", "done", "fi",
         "exec", "command", "xargs", "\\", "(", "{", "!")
# ⚠ `cd`/`export`/대입은 **감싸는 것이 아니라 바이트를 내지 않는 것**이다. `&&` 로 이미
# 쪼갠 뒤의 `cd /x` 는 감쌀 대상이 없고, 예전 판은 그 경로를 `cmd` 로 분류해 343 회
# 가짜 커맨드를 만들었다.
_SILENT = ("cd", "export", "set", "unset", "shift", "pushd", "popd", "local", "declare",
            "for", "while", "until", "if", "case", "select", "elif", "esac")
_ASSIGN = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*=")
_REDIR = re.compile(r"\A[0-9]*(?:>>?|<)&?[0-9-]*\Z")


def _strip_heredocs(arg):
    """heredoc 본문은 커맨드가 아니라 **데이터**다. 줄마다 `#`·`import`·`}` 같은 낱말이
    커맨드로 둔갑해 「혼합」을 만들었다."""
    out, lines, i = [], (arg or "").split("\n"), 0
    while i < len(lines):
        out.append(lines[i])
        m = re.search(r"<<-?\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?", lines[i])
        if m:
            delim = m.group(1)
            i += 1
            while i < len(lines) and lines[i].strip() != delim:
                i += 1
        i += 1
    return "\n".join(out)


def _split_top(text, seps):
    """따옴표 **밖**의 분리자에서만 쪼갠다. `grep -E "a|b"` 의 `|` 는 분리자가 아니다."""
    parts, buf, q, i = [], [], None, 0
    while i < len(text):
        c = text[i]
        if q:
            buf.append(c)
            if c == q:
                q = None
            elif c == "\\" and i + 1 < len(text):
                i += 1
                buf.append(text[i])
            i += 1
            continue
        if c in "'\"":
            q = c
            buf.append(c)
            i += 1
            continue
        hit = next((s for s in seps if text.startswith(s, i)), None)
        if hit:
            parts.append("".join(buf))
            buf = []
            i += len(hit)
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts


def _head_of(seg):
    """세그먼트가 실제로 실행하는 커맨드. 리다이렉션·래퍼·대입을 벗긴다."""
    w = [t for t in seg.strip().split() if not _REDIR.match(t)]
    w = [t for t in w if not re.match(r"\A[0-9]*(?:>>?|<)&?", t)]
    i = 0
    while i < len(w) and (w[i] in _WRAP or _ASSIGN.match(w[i])):
        i += 1
    if i >= len(w):
        return None
    return w[i]


def _classes(arg):
    """커맨드가 실제로 **하는 일**의 집합.

    ⚠ 라운드 6 재작성. 이전 판(`head[0]` 다음의 첫 세그먼트 분류)은 무작위 표본 40건에서
    「혼합」의 **87%를 오분류**했다. 네 가지 기계적 원인이 있었고 전부 여기서 닫는다:
      ① `2>&1` 의 `&` 가 분리자로 매칭돼 세그먼트 `1` 이 커맨드가 됐다(낱말 `1` 이 1,292회).
      ② 따옴표 안의 `|`(`grep -E "a|b"`)가 분리자로 잡혔다.
      ③ heredoc 본문이 줄마다 커맨드로 세어졌다.
      ④ `cd` 가 `_WRAP` 에 있었으나 `&&` 로 쪼갠 뒤엔 감쌀 대상이 없어, 디렉터리 경로가
         커맨드로 둔갑했다.

    ⚠⚠ **파이프의 바이트는 첫 단계에서 나온다.** `flutter test | tail -100` 의 출력은
    `tail` 이 만든 것이 아니고, `cat x | grep y` 의 내용은 `x` 에서 온다. 그래서 `|` 는
    `&&` 와 달리 **생산자(첫 단계)만** 본다. 이전 판은 `|` 를 `&&` 처럼 다뤄 순수 커맨드를
    절반으로 과소평가했다(6.7% → 실제 13.6%).
    """
    out = set()
    # ⚠ 분리자에 낱개 `&` 를 넣지 마라 — `2>&1` 이 쪼개져 세그먼트 `1` 이 커맨드가 된다.
    #   (라운드 6에서 실제로 그랬다. 백그라운드 `&` 는 이 로그에 사실상 없다.)
    for seg in _split_top(_strip_heredocs(arg or ""), ("&&", "||", ";", "\n")):
        # ⚠ 이 분할은 **실측상 중복이다** — `_head_of()` 가 어차피 첫 낱말을 고르므로,
        # 지워도 snap37 의 Bash 9,436건 중 분류가 달라지는 것이 **0건**이다. 의도(파이프의
        # 바이트는 첫 단계에서 나온다)를 코드로 남기되, **검사로 고정할 수 없음을 안다.**
        producer = _split_top(seg, ("|",))[0]      # 파이프라인의 첫 단계만
        c = _head_of(producer)
        if c is None or c in _SILENT:
            continue                                # 바이트를 내지 않는다
        if c in _PURE_READ:
            out.add("read")
        elif c in _SEARCH:
            out.add("search")
        elif c in _LIST:
            out.add("list")
        else:
            out.add("cmd")
    return out


def tool_axis(sessions):
    """4d. 적분을 «도구 × 커맨드 모양» 으로. 4c 는 **출처(경로)별**이라 이 질문에 답하지 못한다.

    ⚠ 이 절이 존재하는 이유는 실패 사례다. `_bash_rules.md` 가 인용하던 «셸 읽기 50% /
    진짜 커맨드 7%» 는 **어떤 도구도 산출하지 않는 수치**였고, 프로즈로만 존재하는 동안
    표류했다. 실측하면 셸 읽기는 28.8%, 진짜 커맨드는 19.3% 다. 수치를 규범에 적을
    거라면 그 수치를 내는 코드가 있어야 한다.

    ⚠ 4c 와 분모가 같고(같은 delta 귀속식) 축만 다르다. 그래서 두 표는 교차 검증이 된다.
    """
    print()
    print("=" * 78)
    print("4d. 적분의 도구·커맨드 모양별 내역 (4c 와 같은 귀속식, 다른 축)")
    print("=" * 78)
    cost = collections.Counter()
    base = 0
    for s in sessions:
        by_id = s["by_id"]
        for parent, seq in s["prefixes"].items():
            n = len(seq)
            base += seq[0] * n
            for i in range(n - 1):
                delta = seq[i + 1] - seq[i]
                if delta <= 0:
                    continue
                take = [by_id[t] for t in s["call_ids"][parent][i] if t in by_id]
                if not take:
                    cost["모델 출력·thinking(추정)"] += delta * (n - 1 - i)
                    continue
                tot_b = sum(t[2] for t in take) or 1
                for tool, arg, size in take:
                    w = delta * (n - 1 - i) * size / tot_b
                    if tool != "Bash":
                        cost[f"{tool} 도구"] += w
                        continue
                    cl = _classes(arg)
                    if not cl:
                        cost["Bash 분류 불가"] += w
                    elif len(cl) > 1:
                        cost["Bash 혼합 (한 호출이 읽기+커맨드)"] += w
                    elif "read" in cl:
                        cost["Bash 파일읽기 (cat/sed/head/tail)"] += w
                    elif "search" in cl:
                        cost["Bash 검색 (grep/rg/awk)"] += w
                    elif "list" in cl:
                        cost["Bash 목록 (ls/find/wc)"] += w
                    else:
                        cost["Bash 진짜 커맨드 (git/gh/test/…)"] += w
    cost["base prefix (시스템+CLAUDE.md+툴+스킬)"] = base
    total = sum(cost.values()) or 1
    print(f"{'축':46s} {'적분 기여':>15} {'share':>7}")
    for k, v in cost.most_common():
        print(f"{k:46s} {int(v):15,} {v / total * 100:6.2f}%")
    g = lambda k: cost.get(k, 0) / total * 100
    shell_read = g("Bash 파일읽기 (cat/sed/head/tail)")
    search, lst = g("Bash 검색 (grep/rg/awk)"), g("Bash 목록 (ls/find/wc)")
    mixed, cmd = g("Bash 혼합 (한 호출이 읽기+커맨드)"), g("Bash 진짜 커맨드 (git/gh/test/…)")
    read_tool = g("Read 도구")
    print()
    print("  ⚠ 규범이 인용하는 수 — `_bash_rules.md` 가 이 값을 적는다:")
    print(f"     파일을 끌어오는 것이 확실한 것 = {shell_read + search + lst + read_tool:.1f}%"
          f"   (Read 도구 {read_tool:.1f}%p · 셸 읽기 {shell_read:.1f}%p ·"
          f" 검색 {search:.1f}%p · 목록 {lst:.1f}%p)")
    print(f"     순수 커맨드 출력(테스트·git·gh) = {cmd:.1f}%")
    print(f"     혼합(한 호출에 둘 다 — 나눌 수 없음) = {mixed:.1f}%")
    print("  ⚠ 혼합을 어느 쪽에도 몰아주지 않는다. tool_result 바이트를 서브커맨드별로 쪼갤 수")
    print("     없기 때문이다. 몰아주는 것이 정확히 예전 head[0] 분류가 냈던 오차다.")
    # ⚠⚠ 혼합이 «주로 읽기»인지 **도구가 직접 답한다.** 라운드 6에서 이 수를 프로즈로만 적어
    # 출하했다가 틀렸다 — 인용한 59.8% 는 **다른 버킷**(옛 head[0] 「진짜 커맨드」)의 값이었다.
    # §12.1 이 「규범에 적을 수치는 도구가 내는 수치여야 한다」고 닫은 바로 그 문단이 저지른
    # 일이라, 교훈을 코드로 옮긴다.
    mr = mc = 0.0
    for s2 in sessions:
        by_id = s2["by_id"]
        for parent, seq in s2["prefixes"].items():
            n = len(seq)
            for i in range(n - 1):
                delta = seq[i + 1] - seq[i]
                if delta <= 0:
                    continue
                take = [by_id[t] for t in s2["call_ids"][parent][i] if t in by_id]
                tot_b = sum(t[2] for t in take) or 1
                for tool, arg, size in take:
                    if tool != "Bash":
                        continue
                    cl = _classes(arg)
                    if len(cl) <= 1:
                        continue
                    w2 = delta * (n - 1 - i) * size / tot_b
                    if cl & {"read", "search", "list"}:
                        mr += w2
                    if "cmd" in cl:
                        mc += w2
    mtot = cost.get("Bash 혼합 (한 호출이 읽기+커맨드)", 0) or 1
    print(f"     혼합 {mixed:.1f}% 의 내부: 파일 끌어오기를 포함한 것 {mr / mtot * 100:.1f}% ·"
          f" 커맨드를 포함한 것 {mc / mtot * 100:.1f}% (한 호출이 둘 다이므로 합이 100 을 넘는다)")
    print(f"  → 그래서 파일 끌어오기의 정직한 범위는 "
          f"**{shell_read + search + lst + read_tool:.1f}–"
          f"{shell_read + search + lst + read_tool + mixed:.1f}%**, "
          f"순수 커맨드는 **{cmd:.1f}–{cmd + mixed:.1f}%** 다.")
    print("  → 도구를 바꾸면 첫 줄 안에서 옮겨갈 뿐 합은 그대로다. **덜 읽어야 준다.**")


def bash_shapes(sessions):
    """Bash 출력을 커맨드 모양별로. §4의 M5 게이트(`cat`/`sed` 호출 수)가 읽는 표다."""
    print()
    print("=" * 78)
    print("4b. Bash 출력의 내역 (커맨드 모양별)")
    print("=" * 78)
    size = collections.Counter()
    calls = collections.Counter()
    for s in sessions:
        for tool, arg, _parent, n in s["results"]:
            if tool != "Bash":
                continue
            head = (arg or "").strip().split()
            if not head:
                continue
            key = " ".join(head[:3])[:40] if head[0] in (
                "gh", "git", "flutter", "dart", "python3", "bash", "sh", "yarn", "npm", "npx"
            ) else head[0][:40]
            size[key] += n
            calls[key] += 1
    total = sum(size.values()) or 1
    print(f"{'커맨드':42s} {'calls':>6} {'bytes':>12} {'share':>7} {'평균':>8}")
    for key, value in size.most_common(12):
        print(f"{key:42s} {calls[key]:6,} {value:12,} {value / total * 100:6.1f}% "
              f"{value // calls[key]:8,}")
    reads = sum(calls[k] for k in ("cat", "sed", "grep"))
    rbytes = sum(size[k] for k in ("cat", "sed", "grep"))
    print(f"\n  합계 {total:,}B · 호출 {sum(calls.values()):,}")
    print(f"  ⚠ 파일을 셸로 읽는 것(`cat`+`sed`+`grep`): 호출 {reads:,} · "
          f"{rbytes:,}B = Bash 출력의 {rbytes / total * 100:.0f}%   ← M5 게이트")


def spawn_roles(sessions):
    print()
    print("=" * 78)
    print("5. 서브에이전트 역할별 적분")
    print("=" * 78)
    agg = collections.defaultdict(lambda: [0, 0, 0])
    tiers = collections.defaultdict(collections.Counter)
    loopback = collections.Counter()
    issues_with_loopback = collections.defaultdict(set)
    for s in sessions:
        issue = re.search(r"issue-(\d+)-", s["log"])
        issue = issue.group(1) if issue else "?"
        for parent, seq in s["prefixes"].items():
            if not parent:
                continue
            desc, declared = s["spawns"].get(parent, ("(unknown)", None))
            role = re.sub(r"\s*#\d+.*", "", desc).strip() or "(unknown)"
            a = agg[role]
            a[0] += 1
            a[1] += len(seq)
            a[2] += sum(seq)
            tiers[role][declared or "(미지정)"] += len(seq)
            if LOOPBACK_RE.search(desc):
                loopback[desc] += 1
                issues_with_loopback[issue].add(desc)
    total = sum(a[2] for a in agg.values()) or 1
    print(f"{'role':30s} {'spawns':>6} {'turns':>7} {'적분':>13} {'share':>7} {'opus 비중':>9}")
    for role, a in sorted(agg.items(), key=lambda kv: -kv[1][2])[:14]:
        t = tiers[role]
        opus = t.get("opus", 0) / max(a[1], 1) * 100
        print(f"{role[:30]:30s} {a[0]:6d} {a[1]:7,} {a[2]:13,} "
              f"{a[2] / total * 100:6.1f}% {opus:8.1f}%")
    print("\n  ⚠ `opus 비중`은 리더가 스폰마다 내린 티어 판단이다 — 이미 도는 동적 선택이고,")
    print("    자식 메인 세션의 기본값(M1)과는 별개 축이다. 낮추지 말 것.")

    issues = {re.search(r"issue-(\d+)-", s["log"]).group(1)
              for s in sessions if re.search(r"issue-(\d+)-", s["log"])}
    n_lb = sum(loopback.values())
    print(f"\n  루프백/재작업 스폰: **{n_lb}회 / 이슈 {len(issues_with_loopback)} of {len(issues)}**"
          f"   ← M1 A/B 의 품질 지표(§5)")
    for desc, count in loopback.most_common(12):
        print(f"    {count}x  {desc}")


def seqs_with_model(sessions):
    """(모델, 캐시TTL, prefix 열) 목록. 달러 환산에 필요하다."""
    out = []
    for s in sessions:
        for parent, seq in s["prefixes"].items():
            if parent:
                declared = (s["spawns"].get(parent) or (None, None))[1]
                model = "claude-opus-5" if declared == "opus" else "claude-sonnet-5"
                ttl = "5m"          # 서브에이전트 실측: ephemeral_5m
            else:
                model, ttl = "claude-opus-5", "1h"   # 자식 메인 세션 실측: ephemeral_1h 100%
            out.append((model, ttl, seq))
    return out


# ⚠ 압축 요약의 **실측 크기**(유인 로그 `compactMetadata.postTokens`, n=12):
#   10,503 ~ 26,078 tok · 중앙 13,164. 도구는 이것을 `cap × keep × 0.05` 로 잡고 있었는데
#   cap=150k 에서 465~3,375 tok — **3~56배 과소**다. 게다가 그 항이 `keep` 에 비례해서,
#   낮은 keep 이 「바닥이 작다」로 한 번 「요약이 싸다」로 또 한 번 보상받는다 —
#   **압축의 비용 항이 압축의 이득 파라미터에 묶여 민감도 곡선이 편향된다.**
_SUMMARY_TOKENS = 13_164          # 실측 중앙. cap 과 무관한 상수여야 한다.


def input_cost(seqs, cap=None, keep=0.45, compaction_cost=True, summary=_SUMMARY_TOKENS):
    """입력측 달러. cap 이 있으면 압축을 재생한다.

    ⚠ 압축은 공짜가 아니다 — ① 요약기가 full prefix 를 **읽고** ② 요약을 **출력**하고
    ③ 압축된 prefix 를 통째로 **다시 쓴다**. 캐시 write 는 read 의 12.5~20배이므로
    이 항이 절감을 크게 깎는다.
    """
    total = 0.0
    events = 0
    for model, ttl, seq in seqs:
        cur = seq[0]
        total += price(model, **{"cwrite_1h" if ttl == "1h" else "cwrite_5m": cur})
        for i in range(1, len(seq)):
            delta = max(0, seq[i] - seq[i - 1])
            if cap and cur + delta > cap:
                if compaction_cost:
                    total += price(model, cread=cur)                       # 요약기 읽기
                    total += price(model, out=summary)                     # 요약 출력(실측 상수)
                cur = int(cap * keep)
                total += price(model, **{"cwrite_1h" if ttl == "1h" else "cwrite_5m": cur})
                events += 1
            total += price(model, cread=cur)
            total += price(model, **{"cwrite_1h" if ttl == "1h" else "cwrite_5m": delta})
            cur += delta
    return total, events


def output_cost(sessions):
    """압축이 **건드리지 못하는** 비용. 이 항이 토큰 절감률과 달러 절감률을 벌린다."""
    c = 0.0
    tok = 0
    for s in sessions:
        for m, d in ((s["result"] or {}).get("modelUsage") or {}).items():
            c += price(m, out=d.get("outputTokens", 0))
            tok += d.get("outputTokens", 0)
    return c, tok


def simulate(sessions, main, sub):
    print()
    print("=" * 78)
    print("7. 시뮬레이션 — 토큰과 **달러**를 분리해서 본다")
    print("=" * 78)

    def cap_tokens(d, cap, keep=0.45):
        total = 0
        for seq in d.values():
            cur = seq[0]
            total += cur
            for i in range(1, len(seq)):
                delta = max(0, seq[i] - seq[i - 1])
                if cur + delta > cap:
                    cur = int(cap * keep)
                cur += delta
                total += cur
        return total

    seqs = seqs_with_model(sessions)
    oc, otok = output_cost(sessions)
    base_tok = sum(sum(v) for v in main.values()) + sum(sum(v) for v in sub.values())
    base_in, _ = input_cost(seqs)
    base_all = base_in + oc
    print(f"  기준선: 입력 ${base_in:,.2f} + 출력 ${oc:,.2f}({otok:,} tok) = ${base_all:,.2f}")
    print(f"  ⚠ 출력 {oc / base_all * 100:.1f}% 는 **압축이 1센트도 못 줄인다.**\n")
    print(f"{'cap':>14} {'토큰적분':>15} {'토큰절감':>9} {'$(압축비용0)':>13} {'절감':>7} "
          f"{'$(비용포함)':>12} {'절감':>7} {'압축':>6}")
    for cap in (300_000, 200_000, 150_000, 120_000, 100_000):
        tk = cap_tokens(main, cap) + cap_tokens(sub, cap)
        free, _ = input_cost(seqs, cap, compaction_cost=False)
        full, ev = input_cost(seqs, cap, compaction_cost=True)
        print(f"  --autocompact {cap // 1000:3d}k {tk:15,} {(1 - tk / base_tok) * 100:8.1f}% "
              f"{free + oc:13,.2f} {(1 - (free + oc) / base_all) * 100:6.1f}% "
              f"{full + oc:12,.2f} {(1 - (full + oc) / base_all) * 100:6.1f}% {ev:6,}")
    print("\n  keep 민감도 (cap=150k, 압축비용 포함):")
    for keep in (0.20, 0.45, 0.60, 0.80):
        full, _ = input_cost(seqs, 150_000, keep=keep)
        print(f"    keep={keep:.2f} → ${full + oc:,.2f} ({(1 - (full + oc) / base_all) * 100:+.1f}%)")
    print("  ⚠ keep 은 측정값이 아니라 가정이다. 가정 (a) 검증 런에서 실측해 고정할 것.")


# ⚠ 라벨 **전이** 만 잡는다 — `--add-label "guild:<stage>"`. 마커 문자열(`:output`,
# `test-evidence`)은 전이가 아니다.
_STAGE_TRANSITION = re.compile(r"--add-label\s+[\"']?guild:(analyze|design|execute|test|qa)(?![\w:-])")
# 라벨 **조회 결과 본문**에서는 전이 문법이 없으므로 라벨 자체를 본다.
# ⚠ 본문은 `json.dumps` 로 **이중 인코딩**돼 따옴표가 `\"` 로 이스케이프된다 — 따옴표를
# 요구하면 폴백이 통째로 죽는다(실측: 미상 52/200). 라벨 이름만 본다.
_STAGE_LABEL = re.compile(r"guild:(analyze|design|execute|test|qa)(?![\w:-])")

_QUALITY_MARKERS = (
    ("guild:test-evidence",   "raw 테스트 증거 마커"),
    ("guild:auditor:execute", "감사 기록 코멘트"),
    ("manual-qa",             "qa 2.5 수동 체크리스트"),
    ("--kind correction",     "ground-truth correction"),
    ("--kind verify-gap",     "ground-truth verify-gap"),
)
_QUALITY_SPAWNS = ("external auditor", "tech-lead conformance", "tester verify",
                   "security review", "i18n review", "dba review", "designer ui/ux review")


def load_attended(root):
    """유인 경로 프런트엔드 — `~/.claude/projects/<slug>/*.jsonl`.

    ⚠ **stream-json 이 아니다. 「도구에 편입」이 아니라 두 번째 프런트엔드다.**
    레코드 타입이 다르고(`attachment`·`last-prompt`·`mode`·`ai-title`·`permission-mode` …),
    **`result` 레코드가 없어 `total_cost_usd` 가 0건**이다. 그래서:
      - §2.1 의 자기검사 3축 중 **③(적분↔modelUsage 정합성)은 유인에 원리적으로 없다.**
      - **§3 은 적분만 낼 수 있고 달러는 낼 수 없다.**
    공유되는 것은 뒷단(prefix 적분)뿐이다. 이 한계를 숨기지 않는다.

    ⚠ 서브에이전트는 `<session>/subagents/*.jsonl` 에 **따로** 산다 — 최상위 `.jsonl` 에
    안 들어오므로 `isSidechain` 필터는 no-op 이다(실측 0건).
    """
    sessions = []
    for f in sorted(glob.glob(os.path.join(root, "*.jsonl"))):
        seen, seq, sid, compacts = set(), [], None, []
        for line in open(f, encoding="utf-8", errors="replace"):
            try:
                o = json.loads(line)
            except Exception:
                continue
            sid = sid or o.get("sessionId")
            cm = o.get("compactMetadata")
            if isinstance(cm, dict) and cm.get("preTokens"):
                compacts.append((cm.get("preTokens"), cm.get("postTokens")))
            if o.get("type") != "assistant" or o.get("isSidechain"):
                continue
            m = o.get("message") or {}
            if m.get("id") in seen:
                continue
            seen.add(m.get("id"))
            u = m.get("usage") or {}
            pre = ((u.get("cache_read_input_tokens") or 0)
                   + (u.get("cache_creation_input_tokens") or 0)
                   + (u.get("input_tokens") or 0))
            if pre:
                seq.append(pre)
        subs = glob.glob(os.path.join(root, os.path.basename(f)[:-6], "subagents", "*.jsonl"))
        # ⚠ 서브에이전트 **적분까지** 낸다. 라운드 15 이전에는 파일 **개수**만 셌고, §3 의
        #    「SUB 29.7% · 리더 66.8%」는 임시 스크립트 값으로 남아 있었다(규율 7 위반).
        #    같은 코퍼스의 파일 수가 플랜 안에서 331·334·337 셋으로 갈린 것도 그 탓이다.
        subint = 0
        for sf in subs:
            sseen = set()
            for line in open(sf, encoding="utf-8", errors="replace"):
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") != "assistant":
                    continue
                m = o.get("message") or {}
                if m.get("id") in sseen:
                    continue
                sseen.add(m.get("id"))
                u = m.get("usage") or {}
                subint += ((u.get("cache_read_input_tokens") or 0)
                           + (u.get("cache_creation_input_tokens") or 0)
                           + (u.get("input_tokens") or 0))
        if len(seq) >= 10:
            sessions.append(dict(log=os.path.basename(f), sid=sid, seq=seq,
                                 compacts=compacts, nsub=len(subs), subint=subint))
    return sessions


def stage_entry(sessions, widths=(5, 10, 15)):
    """12. **스테이지 진입 창** — M9·M13 이 실제로 겨냥한 지점만 잰다.

    ⚠⚠ **왜 이 절이 필요한가.** M9(`docs/specs` 재독 축소)와 M13(`docs/standards` 재독 축소)은
    각 스테이지의 **Step 0**(preflight)에서만 작동한다. 그런데 §4c 는 **세션 전체**를 세므로,
    같은 로그를 단위만 바꿔 보면 답이 **세 개** 나온다(실측, 2026-09-16):

        share(§4c)   docs/specs 17.6% → 23.1%   「M9 역효과」
        세션당        −17.5%                     「M9 효과 있음」
        스테이지당     +177.6%                    「M9 크게 악화」

    갈린 이유는 오염원 셋이다: ①세션 크기(arm-B 가 절반) ②**정체** — 한 스테이지에서 601턴을
    갈면 의도를 반복해서 다시 읽는데 그건 읽기 규율이 아니라 루프백 문제다 ③share 는 다른
    버킷이 움직여도 흔들린다.

    → **스테이지에 «진입한 직후 K턴»** 만 센다. 정체는 그 창 밖이고, 세션 크기와 무관하며,
    분모가 «스테이지 진입 횟수» 라 조치가 겨냥한 단위와 일치한다.

    ⚠ **K 를 하나만 고르지 않는다.** Step 0 의 길이는 tier 와 스테이지에 따라 다르고, 고른 K
    가 결론을 만들면 그건 측정이 아니라 선택이다. 여러 K 를 나란히 찍어 **부호가 K 에 의존하는지**
    보이게 한다.

    ⚠ 세션의 **첫 스테이지는 전이가 없다**(라벨이 이미 맞아 재개된다). 그래서 turn 0 도
    진입으로 센다 — 빼면 재개 세션의 Step 0 이 통째로 사라진다.
    """
    print()
    print("=" * 78)
    print("12. 스테이지 진입 창 — M9·M13 이 겨냥한 지점만 (정체·세션크기 비오염)")
    print("=" * 78)
    ent = 0
    agg = {k: {w: [0, 0] for w in widths} for k in ("specs", "std")}
    for x in sessions:
        by_id = x["by_id"]
        for parent, seq in x["prefixes"].items():
            if parent:
                continue                      # 리더(MAIN)만 — Step 0 은 리더가 돈다
            ids = x["call_ids"][parent]
            marks = [0]
            for i in range(len(seq)):
                for tid in (ids[i] if i < len(ids) else []):
                    hit = by_id.get(tid)
                    if hit and _STAGE_TRANSITION.search(hit[1] or ""):
                        if i + 1 < len(seq):
                            marks.append(i + 1)
            marks = sorted(set(marks))
            for j, start in enumerate(marks):
                ent += 1
                nxt = marks[j + 1] if j + 1 < len(marks) else len(seq)
                for w in widths:
                    end = min(start + w, nxt)
                    for i in range(start, end):
                        for tid in (ids[i] if i < len(ids) else []):
                            hit = by_id.get(tid)
                            if not hit:
                                continue
                            a = hit[1] or ""
                            if "docs/specs/" in a:
                                agg["specs"][w][0] += 1; agg["specs"][w][1] += hit[2]
                            elif "docs/standards" in a:
                                agg["std"][w][0] += 1; agg["std"][w][1] += hit[2]
    if not ent:
        print("  스테이지 진입 0건 — 잴 것이 없다")
        return
    print(f"  스테이지 진입 **{ent}회** (분모). 아래는 **진입 1회당** 값이다.")
    print(f"  {'':16s}" + "".join(f"{'K=' + str(w):>22s}" for w in widths))
    for key, lbl in (("specs", "docs/specs"), ("std", "docs/standards")):
        cells = "".join(f"{agg[key][w][0] / ent:9.2f}회 {agg[key][w][1] / ent:10,.0f}B"
                        for w in widths)
        print(f"  {lbl:16s}" + cells)
    print("  ⚠ 부호가 K 에 따라 뒤집히면 그것은 **결과가 아니라 경고**다 — Step 0 의 경계가")
    print("     이 코퍼스에서 잘 정의되지 않는다는 뜻이고, 그때는 결론을 내지 않는다.")
    print("  ⚠ 분모가 «진입 횟수» 이므로 **세션 수가 아니라 진입 수**로 표본 크기를 판단하라.")


def attended(root):
    """11. 유인 경로 — §3 의 수를 **코드가 낸다**(임시 스크립트가 아니라)."""
    S = load_attended(root)
    if not S:
        print(f"\n유인 로그를 찾지 못했다: {root}/*.jsonl")
        return
    print()
    print("=" * 78)
    print("11. 유인 경로 (`~/.claude/projects/`) — ⚠ 프록시 · 달러 없음")
    print("=" * 78)
    # ⚠ 세션 중복(디스크 복제본)을 sessionId 로 제거한다 — 실측에서 한 건 있었고
    #    리더턴의 13.2% 가 재계수됐다.
    # ⚠ 어느 쪽을 남기는가가 중요하다. 첫 등장을 남기면 **파일명 알파벳 순서**가 고르는 것이고,
    #    복제본 중 하나가 잘린 사본이면 **짧은 쪽을 채택**해 턴 수와 적분을 과소평가한다.
    #    복제본은 같은 세션의 서로 다른 시점 스냅샷이므로 **긴 쪽이 상위집합**이다.
    byid, dup = {}, 0
    for x in S:
        prev = byid.get(x["sid"])
        if prev is not None:
            dup += 1
            if len(x["seq"]) <= len(prev["seq"]):
                continue
        byid[x["sid"]] = x
    U = list(byid.values())
    integ = [sum(x["seq"]) for x in U]
    turns = [len(x["seq"]) for x in U]
    print(f"  세션 {len(S)}개 (중복 {dup}건 제거 → **{len(U)}**) · 「리더턴 ≥10」 필터")
    print(f"  턴/세션 중앙 {statistics.median(turns):,.0f} · 최대 {max(turns):,}")
    ev = [(a, b) for x in U for a, b in x["compacts"]]
    print(f"  압축 이벤트 **{len(ev)}건 / {sum(1 for x in U if x['compacts'])}세션** "
          f"= 세션의 {sum(1 for x in U if x['compacts']) / len(U) * 100:.1f}%")
    if ev:
        r = sorted(b / a for a, b in ev if a)
        print(f"    `postTokens/preTokens` 중앙 {statistics.median(r):.4f} · "
              f"범위 {r[0]:.4f}–{r[-1]:.4f}")
        print("    ⚠ 이것은 「요약이 원본의 몇 배인가」이고, 시뮬레이터의 `keep`(= cap 대비)과")
        print("       **정의가 다르다.** 섞어 쓰지 마라.")
    ns = sum(x["nsub"] for x in U)
    print(f"  서브에이전트 트랜스크립트 {ns}파일 · 쓰는 세션 "
          f"{sum(1 for x in U if x['nsub'])}/{len(U)}")
    # ⚠ **§3 의 「SUB share · 리더 share」를 여기서 낸다.** 그 두 수는 M10 의 도달 범위
    #    논거(리더 P₀ 를 줄이는 레버가 유인에서 더 크다)를 떠받치는데, 라운드 15 까지
    #    임시 스크립트 값이었다. 「도구가 찍지 않는 수는 쓰지 않는다」(규율 7).
    lead = sum(integ)
    subi = sum(x.get("subint") or 0 for x in U)
    tot = lead + subi
    if tot:
        print(f"    SUB 적분 share **{subi / tot * 100:.1f}%** · 리더 **{lead / tot * 100:.1f}%** "
              f"(무인은 §2 의 MAIN/SUB 표를 봐라 — 축이 다르다)")
        top = sorted((x.get("subint") or 0) for x in U)[-4:]
        if subi:
            print(f"    ⚠ SUB 는 소수 이상치에 몰린다 — 상위 4세션이 SUB 적분의 "
                  f"{sum(top) / subi * 100:.1f}%")
    print("  ⚠ 이 절은 **달러를 낼 수 없다** — 유인 로그에 `result`/`total_cost_usd` 가 없다.")
    print("  ⚠ **동결 스냅샷에 대고 돌려라.** 라이브 `~/.claude/projects/` 는 이 세션 자신이")
    print("     쓰고 있어 실행마다 수가 는다(A20). `cp` 로 스냅샷을 떠 두면 재현된다 —")
    print("     실측: 동결본과 라이브가 59세션·9건/5세션·8.5% 로 일치했다.")


def quality_baseline(sessions):
    """10. 품질 지표 — **구조**를 센다. 판정을 세지 않는다.

    ⚠ 설계 원리. M1(리더 티어 하향)이 깎는 것은 **리더의 판정**이다 — vacuous 테스트를
    커버리지로 인정하고, stakes 를 낮게 분류하고, 심각도를 잘못 병합한다. 그 셋은 전부
    **루프백을 줄이고 BLOCKER 수를 줄여** 개선처럼 보인다. 따라서 「감사자 BLOCKER 수」나
    「테스트 커버리지」로 재면 **측정 대상이 계기를 오염시킨다.**

    반면 **마커 수는 구조적**이다 — 증거가 남았는지는 리더의 판단이 아니라 스파인이 강제한다.

    ⚠⚠ **그러나 이 절의 초안은 「스폰 수도 오염되지 않는다」고 단언했고, 그것은 틀렸다.**
      ① **스폰 축은 자유서술에 의존한다.** `role.startswith(...)` 가 리더가 지은 `description`
         을 전방일치하므로, 같은 게이트가 다른 이름을 쓰면 0 이 된다 — 실측: 서브에이전트
         200 세션 중 **95(48%)가 버킷 밖**이고 그중 `외부 감사 재스캔`·`외부 감사 최종 스캔`
         은 감사자인데 안 세어진다. §9 가 자기 한계로 적은 것과 **같은 결함**이다.
      ② **상위 3개는 방향이 정의되지 않는다.** `external auditor`·`tech-lead conformance`·
         `tester verify` 는 **루프백마다 재스폰**된다(`_execute_spine.md` chain rule). 품질이
         나빠져 루프백이 늘면 이 수는 **올라가고**, 깨끗한 런에서는 내려간다. §8 은 같은
         루프백을 «비용» 으로 세는데 이 절이 그 증가를 «개선» 으로 읽으면 모순이다.

    → 그래서 아래는 **두 묶음으로 나눠 읽는다**: 조건부 스폰(security·i18n·dba·designer)은
    루프백과 무관하게 «그 위험이 있었는가» 를 재므로 **감소 = 열화**가 성립한다. 상위 3개는
    **루프백 수와 함께** 읽어야 하고 단독으로는 품질 신호가 아니다.

    ⚠ 옛 세트에서 뺀 것: **「테스트 케이스 커버리지」는 산출 도구가 없다**(레포 스냅샷이
    로그에 없다). **「감사자 BLOCKER·MAJOR 수」는 리더의 중재 후 기록이라 오염된다** —
    스폰 수로 대체한다. **`NEEDS_HUMAN` 수는 방향이 모호**해 보조로만 읽는다.
    """
    print()
    print("=" * 78)
    print("10. 품질 지표 기준선 — **감소 = 열화** (구조를 센다, 판정을 세지 않는다)")
    print("=" * 78)
    marks = collections.Counter()
    # ⚠⚠ **두 단위를 함께 센다 — 어느 쪽도 혼자서는 깨끗하지 않다.**
    #   · 호출 기준: 같은 파일을 두 번 쓰면 2 로 센다 → **재시도가 품질로 읽힌다.**
    #     실측: arm-C 는 파일당 1.43회 쓰고 arm-A 는 1.03회 — 호출 기준은 arm-C 를 후하게 준다.
    #   · 파일 기준: 흐름이 파일을 둘로 쪼개면 2 로 센다(`gld-pr-404-manualqa.md` +
    #     `…-body-new.md`) → **흐름 모양이 품질로 읽힌다.**
    #   두 단위가 방향은 같고 크기가 다르면(실측: 증거 −15% ↔ −39%) **그 폭이 불확실성이다.**
    #   §4d 가 「파일 끌어오기 50.6–62.1%」를 범위로 적는 것과 같은 이유다.
    mark_files = collections.defaultdict(set)
    spawns = collections.Counter()
    for x in sessions:
        for _tool, arg, _p, _n in x["results"]:
            a = arg or ""
            for pat, label in _QUALITY_MARKERS:
                if pat in a:
                    mark_files[label].add((x["log"], a.split(" \x00markers:")[0]))
                    marks[label] += 1
        for parent, _seq in x["prefixes"].items():
            if not parent:
                continue
            desc = (x["spawns"].get(parent) or ("", ""))[0] or ""
            role = re.sub(r"\s*#\d+.*", "", desc).strip().lower()
            for want in _QUALITY_SPAWNS:
                if role.startswith(want):
                    spawns[want] += 1
                    break
    print("  ── 조건부 게이트가 소집됐는가 (감소 = 열화) ──")
    for k in ("security review", "i18n review", "dba review", "designer ui/ux review"):
        print(f"    {k:28s} {spawns.get(k, 0):5d}")
    print("  ── 항상 도는 역할 (⚠ 루프백마다 재스폰 — 단독으로는 품질 신호가 아니다) ──")
    for k in ("external auditor", "tech-lead conformance", "tester verify"):
        print(f"    {k:28s} {spawns.get(k, 0):5d}   ← §9 의 루프백 수와 함께 읽어라")
    print("  ── 증거·신호가 남았는가 (마커 수 — 구조적) ──")
    for _pat, label in _QUALITY_MARKERS:
        print(f"    {label:28s} {marks.get(label, 0):5d} 호출 · {len(mark_files[label]):4d} 파일")
    print("    ⚠ **두 수를 함께 읽어라.** 호출은 재시도에 부풀고, 파일은 흐름이 쪼개지면 부푼다 —")
    print("       방향이 같고 크기가 다르면 그 폭이 **불확실성**이다(§4d 의 범위와 같은 이유).")
    print()
    print("  ⚠ **어느 하나라도 내려가면 그것이 신호다.** 비용이 내려가면서 이 수들이 같이")
    print("     내려갔다면 절감이 아니라 **게이트가 덜 돈 것**이다.")
    print("  ⚠ 이 절이 M1 A/B 의 품질 축이다. 「감사자 BLOCKER 수」·「테스트 커버리지」는")
    print("     쓰지 않는다 — 전자는 리더의 중재에 오염되고 후자는 산출 도구가 없다.")
    print("  ⚠⚠ **스폰 축은 리더의 자유서술 `description` 에 의존한다** — 실측 48% 가 버킷")
    print("     밖이다(`외부 감사 재스캔` 등). §9 와 같은 한계이고, 이 절도 그것을 못 벗어난다.")
    print("  ⚠ 그리고 §10 은 「게이트가 돌았는가」를 잰다. 「옳게 판정했는가」는 재지 못한다 —")
    print("     그것은 리더 외부의 독립 판정(`/gld review`)이 필요하고 지금 그 데이터가 없다.")


def loopback_union(sessions):
    """9. 루프백 검출 — 어휘(`LOOPBACK_RE`) · 구조 · **합집합**.

    ⚠ 이 절이 존재하는 이유. M1(달러가 붙은 유일한 레버)의 유일한 미지수는 **품질**이고, 그것을
    재는 계기가 `LOOPBACK_RE` 하나였다. 그 정규식은 리더의 **자유서술 `description`** 에
    매칭하므로 `config.language` 가 바뀌면 조용히 침묵한다 — 그리고 실측 침묵률은 문서가 적던
    24% 가 아니라 **52.3%** 다(`attempt`·`rerun`·`final`·`3차`·`재호출` 을 하나도 안 가진다).

    ⚠ **구조 검출도 「프롬프트 비의존」이 아니다.** 「같은 role」이 `spawns` 의 자유서술에서
    파생되므로, 리더가 재시도 스폰의 이름을 바꾸면 짝이 깨진다. **의존을 없애는 게 아니라 줄인다.**
    그래서 정답은 둘 중 하나가 아니라 **합집합**이다 — 둘 다 놓칠 때만 놓친다.
    """
    print()
    print("=" * 78)
    print("9. 루프백 검출 — 어휘 · 구조 · 합집합 (M1 의 품질 계기)")
    print("=" * 78)
    lex, st = set(), set()
    nostage = tot = 0
    for x in sessions:
        by_id, bodies = x["by_id"], (x.get("bodies") or {})
        # ⚠ 스테이지는 **스폰 시점**에 귀속시킨다. 세션 단위로 하나만 잡으면 「같은 스테이지」가
        # 「같은 세션」으로 붕괴해 구조 검출이 과대해진다(실측 36 → 42).
        # 메인 세션의 턴을 순서대로 걸으며 ① 라벨 전이 커맨드 ② 라벨 질의 **결과 본문**으로
        # 현재 스테이지를 갱신하고, 그 턴에 일어난 Agent 스폰에 그 값을 붙인다.
        # ⚠ 메인 세션의 parent 키는 **문자 그대로 `None`** 이다. `if main_parent is not None`
        # 같은 가드를 두면 바로 그 키를 막는다(실제로 그렇게 해서 검출이 0 이 됐다).
        cur, groups = None, collections.defaultdict(list)
        turns = x["call_ids"].get(None) or []
        for turn in turns:
            for tid in turn:
                arg = (by_id.get(tid) or ("", "", 0))[1] or ""
                # ⚠⚠ **라벨 「전이」만 인정한다.** 예전에는 `guild:(stage)` 를 arg 어디서나
                # 찾았는데, 그러면 **코멘트 조회 커맨드 안의 마커 문자열**에도 걸린다 —
                # `contains("guild:design:output")`, `<!-- guild:test-evidence:step-1 -->`.
                # 실측: `cur` 갱신 143건 중 **67건(47%)이 전이가 아니었다.** 특히
                # `test-evidence` 는 execute **Step 2** 에서 돌아, 그 뒤의 모든 execute 스폰이
                # `stage=test` 로 찍혔다(구조 검출 25건 중 16건이 test, execute 는 3건뿐).
                # 오귀속은 같은 role 의 재스폰 쌍을 **다른 그룹으로 쪼개** 검출을 떨어뜨린다
                # (위양성이 아니라 **위음성**). 교정 후: 구조 25→36 · 합집합 37→44 ·
                # 어휘 침묵률 43.2%→**52.3%** · M1 손익분기 2.2→**2.0배**.
                m = _STAGE_TRANSITION.search(arg)
                if m:
                    cur = m.group(1)
                elif tid in bodies:
                    m2 = _STAGE_TRANSITION.search(bodies[tid]) or _STAGE_LABEL.search(bodies[tid])
                    if m2:
                        cur = m2.group(1)
            for tid in turn:
                if tid not in x["spawns"]:
                    continue
                tot += 1
                if cur is None:
                    nostage += 1
                desc = (x["spawns"][tid][0] or "")
                role = re.sub(r"\s*#\d+.*", "", desc).strip() or "(unknown)"
                groups[(cur, role)].append(tid)
                if LOOPBACK_RE.search(desc):
                    lex.add((x["log"], tid))
        for members in groups.values():
            for tid in members[1:]:          # 2번째 이후 = 재스폰
                st.add((x["log"], tid))
    union = lex | st
    print(f"  어휘 `LOOPBACK_RE`        {len(lex):4d}")
    print(f"  구조(스테이지+role 재스폰) {len(st):4d}")
    print(f"  교집합                    {len(lex & st):4d}")
    print(f"  **합집합**                {len(union):4d}   ← M1 이 써야 할 집합")
    if union:
        print(f"  어휘 단독 포착률 {len(lex) / len(union) * 100:.1f}% "
              f"→ **침묵률 {100 - len(lex) / len(union) * 100:.1f}%**")
    print(f"  ⚠ 스테이지 미상 스폰 {nostage}/{tot} — 미상이면 「같은 스테이지」가 「같은 세션」으로")
    print("     붕괴해 구조 검출이 과대해진다. 라벨 질의 본문 보존(T0 #3)이 그것을 줄인다.")
    print("  ⚠ 구조 검출도 자유서술 `description` 에 의존한다 — 합집합이 정답인 이유다.")
    return {t for _log, t in union}


def levers(sessions, main, sub, union_ids=None):
    """8. 레버 달러 — **이 절이 찍지 않는 수는 인용하지 않는다.**

    ⚠ 라운드 6의 실패에서 나왔다. 실행 순서를 정하는 레버 표가 전부 문서 프로즈에 있었고,
    재현을 시도하자 **다섯 개가 존재하지 않는 수**로 드러났다($7.94·$8.90·$27.35·$42.94·
    $14.10 — 어떤 자연스러운 모델로도 안 나옴). §12.1 이 4d 에만 적용한 교훈을 여기에도
    적용한다: **코드로 옮기려는 순간 없는 수는 드러난다. 그게 검사다.**

    ⚠ 그리고 이 함수를 처음 쓸 때 나 자신이 없는 헬퍼 세 개(`integral_of`/`loopback_cost`/
    `dead_cost`)를 불렀다. 같은 병이다 — 그래서 아래는 **실제로 존재하는 것만** 쓴다.
    """
    print()
    print("=" * 78)
    print("8. 레버 — 달러 (전부 이 실행에서 산출)")
    print("=" * 78)
    # ⚠ `integral()` 이 돌려주는 main/sub 는 **prefix 열의 dict** 이지 가격 튜플이 아니다.
    # 가격은 `seqs_with_model()` 이 붙인다 — parent 유무로 MAIN/SUB 를 가른다.
    seqs = seqs_with_model(sessions)
    main_seqs = [t for t in seqs if t[1] == "1h"]
    sub_seqs = [t for t in seqs if t[1] != "1h"]
    in_m, _ = input_cost(main_seqs)
    in_s, _ = input_cost(sub_seqs)
    out_c, _ = output_cost(sessions)
    base = in_m + in_s + out_c

    # MAIN 몫: 출력 비용을 적분 비율로 나눈다(M1 은 자식 메인 세션만 내린다).
    mi = sum(sum(v) for v in main.values())
    si = sum(sum(v) for v in sub.values())
    share_main = mi / (mi + si) if (mi + si) else 0.0
    # opus $5/$25 → sonnet $3/$15 = 입력·출력 모두 0.6배 → 절감 0.4배
    m1 = 0.4 * (in_m + out_c * share_main)

    # 루프백 — ⚠ **두 집합으로 찍는다.** 어휘(`LOOPBACK_RE`) 하나만 쓰면 침묵률 43% 이고,
    # 그 침묵이 손익분기를 **위로** 밀어 M1 이 실제보다 안전해 보인다(§9 참조).
    def _lb(ids):
        n = t = 0
        for x in sessions:
            for parent, seq in x["prefixes"].items():
                if not parent:
                    continue
                if ids is None:
                    desc, _d = x["spawns"].get(parent, ("(unknown)", None))
                    hit = bool(LOOPBACK_RE.search(desc or ""))
                else:
                    hit = parent in ids
                if hit:
                    n += 1
                    t += sum(seq)
        return n, t
    lb_n, lb_turns = _lb(None)
    lb_cost = (in_s + out_c * (1 - share_main)) * lb_turns / (si or 1)

    dead = sum((x["result"] or {}).get("total_cost_usd", 0) or 0 for x in sessions
               if failed(x))

    print(f"  기준선(재구성)                      ${base:9,.2f}")
    print(f"  M1  자식 메인 opus→sonnet           ${m1:9,.2f}  ({m1 / base * 100:4.1f}%)")
    if lb_cost > 0:
        r = m1 / lb_cost
        print(f"      └ 루프백 {lb_n:2d}건 ${lb_cost:8,.2f} · 손익분기 **{r:.1f}배** "
              f"(+{(r - 1) * 100:.0f}%)")
        print("      ⚠ 분자·분모를 **같은 비용 모델**(입력+출력)로 맞춘 값이다. 분모를 입력만")
        print("        으로 두면 배수가 과대해진다(라운드 6 지적).")
        print("      ⚠ LOOPBACK_RE 는 리더의 자유서술 `description` 에 매칭한다 — 레포의")
        print("        `config.language` 가 바뀌면 이 지표가 조용히 과소계상된다.")
    if union_ids:
        un, ut = _lb(union_ids)
        uc = (in_s + out_c * (1 - share_main)) * ut / (si or 1)
        if uc > 0:
            r2 = m1 / uc
            print(f"      └ **합집합** {un:2d}건 ${uc:8,.2f} · 손익분기 **{r2:.1f}배** "
                  f"(+{(r2 - 1) * 100:.0f}%)   ← 정본")
            print("      ⚠ 어휘 하나만 쓰면 침묵분이 분모에서 빠져 손익분기가 **위로** 밀린다")
            print("        — M1 이 실제보다 안전해 보인다. §9 의 합집합을 쓴다.")
    # ── M12 — 루프백 티어 상승(sonnet→opus)의 달러 ───────────────────────
    # ⚠ `_execute_spine.md` 의 chain rule: 루프백은 전 체인을 **한 티어 위**에서 재실행한다.
    #    M12 는 그 상승을 없애는 조치이므로, 달러는 **「상승분」** 이다 — 루프백 합집합에
    #    들어가면서 **`--model opus` 로 선언된 스폰**의 비용을 sonnet 으로 환산한 차액.
    # ⚠⚠ **이 수를 「절감」으로 읽지 마라.** 상승을 없애는 것은 **재시도의 품질을 낮추는
    #    것**이고, 루프백은 이미 「뭔가 틀렸다」가 확인된 자리다. 이 절은 **가격표**를 낼 뿐
    #    이고 채택 여부는 플랜 §M12 의 품질 논의가 정한다.
    esc_seqs, esc_n, esc_int = [], 0, 0
    other_opus_n = 0
    for x in sessions:
        for parent, seq in x["prefixes"].items():
            if not parent:
                continue
            declared = (x["spawns"].get(parent) or (None, None))[1]
            if declared != "opus":
                continue
            if union_ids and parent in union_ids:
                esc_seqs.append(("claude-opus-5", "5m", seq))
                esc_n += 1
                esc_int += sum(seq)
            else:
                other_opus_n += 1
    if esc_seqs:
        esc_in, _ = input_cost(esc_seqs)
        # 출력 몫은 SUB 전체 출력비를 **적분 비율**로 배분한다(M1 과 같은 방식).
        esc_out = out_c * (1 - share_main) * (esc_int / (si or 1))
        # opus $5/$25 → sonnet $3/$15 = 0.6배 → 상승분은 그 비용의 0.4배
        m12 = 0.4 * (esc_in + esc_out)
        print(f"  M12 루프백 티어 상승분(opus→sonnet) ${m12:9,.2f}  "
              f"({m12 / base * 100:4.1f}%)")
        print(f"      └ 루프백 합집합 {len(union_ids or [])}건 중 **opus 선언 {esc_n}건** "
              f"(합집합 밖 opus {other_opus_n}건은 제외)")
        print("      ⚠⚠ **절감이 아니라 가격표다.** 상승을 없애는 것은 재시도의 품질을 낮추는")
        print("         것이고, 루프백은 이미 「뭔가 틀렸다」가 확인된 자리다.")
        print("      ⚠ M1 과 **합산하지 마라** — M1 은 MAIN, M12 는 SUB 라 축이 겹치지 않지만,")
        print("         둘 다 «티어를 내린다» 는 같은 품질 대가를 두 번 치른다.")
    else:
        print("  M12 루프백 티어 상승분                **관측 0건** — opus 선언 스폰이 "
              "루프백 합집합 안에 없다")

    # ── M3 — **잔여 회수액** (노출액이 아니다) ───────────────────────────
    # ⚠⚠ `$294.80` 은 「429 세션의 **총 지출**」이지 회수 가능액이 아니다. 슈퍼바이저는 이미
    #    재시도하고(`sprint-supervisor.sh:1945-1950`) **라벨에서 재개**한다(`resume.md:34`:
    #    *"the label is the checkpoint"*). 완료된 스테이지는 **이미 보존된다.**
    #    `--resume` 이 **추가로** 사는 것은 **죽은 스테이지 «내부»의 부분 진행**뿐이다.
    # → 그래서 실패 세션의 **마지막 라벨 전이 이후 턴들**만 센다. 그 앞은 다음 시도가
    #    라벨로 건너뛰므로 재수행되지 않는다.
    # ⚠ 전이가 **0건인 세션**(재개 attempt 는 라벨이 이미 맞아 전이를 안 내보낸다)은 전체가
    #    한 스테이지 안이므로 **100% 재수행**이 맞다 — 과대계상이 아니다.
    redo_seqs, fail_seqs = [], []
    for x in sessions:
        if not failed(x):
            continue
        by_id = x["by_id"]
        for parent, seq in x["prefixes"].items():
            if parent:
                continue          # SUB 는 라벨 체크포인트가 없다 — 아래 ⚠ 참조
            ids = x["call_ids"][parent]
            last = -1
            for i in range(len(seq)):
                for tid in (ids[i] if i < len(ids) else []):
                    hit = by_id.get(tid)
                    if hit and _STAGE_TRANSITION.search(hit[1] or ""):
                        last = i
            if seq[last + 1:]:
                redo_seqs.append(("claude-opus-5", "1h", seq[last + 1:]))
            fail_seqs.append(("claude-opus-5", "1h", seq))
    m3 = 0.0
    if redo_seqs:
        m3, _ = input_cost(redo_seqs)
        fin, _ = input_cost(fail_seqs)
    print(f"  M3  429/미완료 **노출액**             ${dead:9,.2f}  ({dead / base * 100:4.1f}%)")
    if m3:
        print(f"      └ **잔여 회수액**              ${m3:9,.2f}  ({m3 / base * 100:4.1f}%)"
              f"  = 노출액의 {m3 / dead * 100:.1f}%")
        print(f"      ⚠ 실패 MAIN 입력비 ${fin:,.2f} 중 **마지막 라벨 전이 이후** 분만 셌다 —")
        print("        그 앞은 다음 시도가 라벨로 건너뛰므로 재수행되지 않는다.")
        print("      ⚠⚠ **하한도 상한도 아니다 — 두 누락이 반대 방향이다:**")
        print("         (↑ 키우는 쪽) **SUB 를 안 셌다** — 죽은 스테이지가 재실행되면 그 안의")
        print("            서브에이전트도 다시 스폰되는데 턴 단위 귀속이 없어 못 뺐다.")
        print("         (↓ 줄이는 쪽) **`--resume` 자체의 비용**(재개 시 prefix 재적재)이")
        print("            빠져 있다. 회수액 전부가 절감으로 남지 않는다.")
        print("         → **자릿수만 믿어라**: 노출액 $%.2f 의 **1/7 수준**이지 전액이 아니다."
              % dead)
    else:
        print("      └ **잔여 회수액 관측 0건** — 실패 세션이 없거나 전부 전이 직후에 죽었다")
    print()
    print("  ⚠ 여기에 없는 레버는 **아직 달러가 없는 것**이다. 문서에 숫자가 적혀 있어도")
    print("     이 절이 찍지 않으면 인용하지 마라.")


def main_():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    root = sys.argv[1]
    sessions = load(root)
    if not sessions:
        print(f"로그를 찾지 못했다: {root}/*/issue-*-attempt*.log")
        sys.exit(1)
    sessions = settled(sessions)
    if not sessions:
        print("끝난 세션이 없다 — 스프린트가 도는 중이면 끝난 뒤에 다시 돌린다.")
        sys.exit(1)
    money(sessions)
    m, s = integral(sessions)
    selfcheck(sessions, sum(sum(v) for v in m.values()) + sum(sum(v) for v in s.values()))
    scope_model(sessions)
    growth_by_tool(sessions)
    content_sources(sessions)
    source_integral(sessions)
    stage_entry(sessions)
    tool_axis(sessions)
    bash_shapes(sessions)
    spawn_roles(sessions)
    quality_baseline(sessions)
    _u = loopback_union(sessions)
    levers(sessions, m, s, _u)
    for a in sys.argv[2:]:
        if a.startswith("--attended="):
            attended(os.path.expanduser(a.split("=", 1)[1]))
    if "--sim" in sys.argv:
        simulate(sessions, m, s)


if __name__ == "__main__":
    main_()
