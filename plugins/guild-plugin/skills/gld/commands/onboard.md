# ONBOARD (guided codebase tour — for a human)

**Ramp a human maintainer into *their own* system, one layer at a time — a paced, guided tour.** Guild's third growth engine (③ overseer growth — `_learning.md` technique **C**) has one standalone command, and this is it: a new (or returning) human runs `/gld onboard` to *intend* to learn the codebase. Everything else in the ③ engine rides inside commands the human already runs (review/evolve/dev); onboarding is the one thing a human deliberately sits down to do.

`$1` = optional focus area (a path, subsystem, or topic — e.g. `auth`, `lib/widgets`, `payments`). Omitted → whole-system orientation.

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State: `<<SKILL_DIR>>/commands/atoms/_handoff.md`. ③ contract: `<<SKILL_DIR>>/commands/atoms/_learning.md`.
> **Output language**: conduct the tour (narration, questions, recap) in `config.language` (`_handoff.md` Section K). Machine tokens / `file:line` refs stay ASCII.

> **This is a MULTI-TURN, interactive flow.** It runs in the **main session** (it must pause and wait for the human between stops — a sub-agent cannot). The command *initiates* the tour and presents the map + first stop; each subsequent turn presents the next stop after the human responds. Track the current stop index in your reasoning (like an FSM). Re-running `/gld onboard` restarts; the human can say "continue from stop N" or name an area.

> **Distinct from neighbors** — `init` builds the harness (one-time setup, machine-facing); `ask` answers a single reactive question (cited Q&A, one-shot); **`onboard` is a proactive, paced, multi-stop tour that teaches a human the system** and adapts to what they already know.

---

## Step 0 — Preflight + gather the material (read-only)
Follow `_preflight.md` **Light tier** (config + role defs, conventions + standards). If `.claude/guild/config.json` is absent → "This repo isn't initialized — run `/gld init` first (onboarding needs the Guild's ⑥ knowledge + standards)."

Gather what the tour teaches from (best-effort — degrade gracefully on any miss):
1. **⑥ knowledge** — `.claude/guild/knowledge/index.md` (the always-loaded map of accumulated codebase facts). Empty/absent → say so; the tour leans on standards + structure instead.
2. **Standards** — `docs/standards/charter.md` (why the system exists), `architecture.md` (shape), `conventions.md`, `quality-bar.md`. Honor `confirmed` as authoritative; note `draft` as provisional.
3. **Hotspots / traps** — the "주의(핫스팟·함정)" section of `.claude/agents/tech-lead.md` (the risky/subtle areas the Guild has learned).
4. **Structure** — top-level layout (`ls`), and for a focused `$1`, `ls <area>` + the entry-point file(s).
5. **③ competence signal (F)** — if the evolve **overseer scorecard** exists (`.claude/guild/evolution-log.md` / ledger), note the human's per-area competence trend so the tour can pitch its depth (Step 2). Absent (the common early case) → default to moderate depth.

## Step 1 — Build the tour map, present it, and pause
From the material, group the system into an ordered set of **stops** — pitched at the focus (`$1`) or the whole system:
- **Orient before detail** — charter/purpose (why this exists) → architecture (the shape) → the key subsystems → the hotspots/traps → where to make a first change.
- **Order by dependency** — foundational concepts before the code that assumes them.
- **Anchor every stop to real artifacts** — a `file:line`, a ⑥ fact, a standard — never generic advice. This is *their* system, taught from the ground truth of *their* repo.
- Keep each stop to one exchange; 4–8 stops for a whole-system tour, fewer for a focused one.

Present the map and **stop**:
```
<repo> 온보딩 투어를 <K>개 스톱으로 준비했습니다:
① 왜 이 시스템이 존재하는가 (charter)
② 아키텍처의 모양 — 주요 경계
③ <핵심 subsystem 1>
④ 핫스팟·함정 (Guild가 학습한 위험 지점)
⑤ 첫 변경을 시작하기 좋은 곳
①부터 시작할까요? (특정 스톱부터/이미 아는 영역 건너뛰기도 가능합니다.)
```
Wait for the human before presenting stop ①.

## Step 2 — Tour loop (ONE stop per turn — the core)
For the current stop:
1. **Header**: `[스톱 i/K] <제목>`.
2. **어디**: the anchoring artifact(s) — clickable `file:line` refs, the ⑥ fact, or the standard section. Show the key lines briefly, not whole files (the human clicks to open; Claude cannot navigate the editor for them).
3. **무엇을 / 어떻게 맞물리는가**: what this piece is and how it connects to the stops already covered (build the mental model incrementally).
4. **왜 — 원리 (A 크래프트 전수 · `_learning.md`)**: not just *what* the code does but **the underlying principle** — why it's shaped this way, what constraint or standard drives it ("이 레이어 분리는 …원칙", "이 토큰이 모드별로 분기된 건 WCAG 대비 원칙"). Ground-truth-anchored (a `confirmed` standard / evidence-anchored ⑥ fact / a real past defect), **never AI opinion** — an unanchored observation is flagged *"인사이트 후보 (미검증)"*, not taught as fact (`_learning.md` Section B).
5. **예측 먼저 (D 예측-후-공개 · optional)**: for a stop with a non-obvious answer, **first ask the human to reason** — *"이 구조라면 X는 어디서 처리될까요?"* / *"여기서 뭐가 위험해 보이세요?"* — then reveal. The predict→compare gap is where the model sticks (§8-A applied to the human). Skip for purely descriptive stops.
6. **Pause**: `질문 있으세요? 없으면 '다음'이라고 하시면 다음 스톱으로 갑니다.` → **STOP and wait.**

**Adaptive depth (F 페이딩 · `_learning.md`)**: scale each stop to the human's competence trend (the ③ competence signal gathered in **Step 0, item 5**). ⚠ **The overseer scorecard is a single authority-tier row not keyed by human identity (`_learning.md` Section D)** — so if *this* human is a **new** maintainer (onboard's whole purpose, Step 0), do **NOT** fade based on a *previous* overseer's trend; default to **full depth** regardless of scorecard. Only fade for a demonstrably **returning** overseer. Strong (returning, high-competence area) → **fade** to a one-line pointer + the predict prompt; weak/new → full worked explanation. Absent scorecard → moderate. Opt-in, non-condescending — the human can always say "더 깊게" / "건너뛰어요".

Rules for the loop:
- **One stop per turn.** Never dump the whole tour at once — that defeats the paced ramp-up.
- Answer questions from the loaded material; if the human selects a region in the editor, discuss that; if they ask about something off-map, answer it and offer to fold it into a stop.
- Advance only when the human signals ("다음") — respect their pace; they may linger, skip, or reorder.
- **Read-only.** onboard teaches; it makes no commits, branches, or edits.

## Step 3 — Recap + next steps (after the last stop)
- Recap the mental model built (the stops as a connected whole, not a list).
- **Where to go next**: point to a good first Issue / area for a first change, and the relevant commands (`/gld dev <issue>` to build, `/gld ask <q>` for a specific question later, `/gld review <pr>` to learn from an existing change).
- **③ note**: mention (once, lightly) that the WHY-teaching continues inside `review`/`dev` as they work — onboarding is the start of the ramp, not the whole of it.
- Optional: if the human asked recurring questions that map to gaps in ⑥ knowledge or a missing standard, note it as a candidate for the next `/gld evolve` (does not capture here — onboard is read-only).

## Hard rules
- **Read-only** — no branches/commits/edits; onboard only reads the repo and converses.
- **Ground-truth or abstain** (`_learning.md` Section B.1) — every stop anchored to a real artifact; AI opinion is never taught as fact. Higher bar than agent-facing.
- **Paced, one stop per turn** — the value is the incremental, adaptive walk, not a generated document.
- **Advisory, non-condescending, fades with competence** — the human is the authority (INV1); onboard assists a human who *chose* to learn.
