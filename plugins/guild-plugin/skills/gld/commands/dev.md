# DEV

**Drive the full spine on one GitHub Issue: `analyze → design → execute → test → qa → done`.** Main-session FSM. The main session **embodies the leader** (plan §12, §16 C2) — it loads `.claude/agents/leader.md` and uses that persona to assemble the team, run gates, arbitrate, and judge completion. Each stage is executed by reading its wrapper command inline; the wrapper spawns the role sub-agents for that stage.

`$1` = Issue number.

> **Bash**: simple calls only (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`). State model + labels + handoff: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.

---

## Phase 0 — Setup

1. **Validate `$1`**: must be an Issue number. Confirm it exists and is not a PR:
   ```bash
   gh issue view $1 --json url --jq .url
   ```
   Empty/error → `FAIL: Issue #$1 does not exist`. URL contains `/pull/` → `FAIL: #$1 is a Pull Request, not an Issue`. Stop on either.

2. **Confirm Guild is initialized** (its own Bash call):
   ```bash
   ls .claude/guild/config.json
   ```
   Absent → report "Guild is not initialized in this repo. Run `/gld init` first." Stop.

3. **Load the leader persona**: Read `.claude/agents/leader.md`. Adopt it for the rest of this command — team assembly, delegation, gate arbitration, and completion judgment are done *as the leader*.

4. **Resolve owner/repo** once (`_handoff.md` Section F); hold the literal value.

5. **Detect run mode** (its own Bash call): `printenv GLD_UNATTENDED`. If `1` → **unattended mode** (invoked by `/gld batch`·`/gld sprint` supervisor): the leader stands in for the human at gates and never calls `AskUserQuestion` (`_handoff.md` Section H). Otherwise attended (default).

---

## Phase 1 — Determine current stage (from label)

Read the Issue's labels:
```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

Map to the current stage (`_handoff.md` Section A):
- contains `guild:done` → already complete; report and stop (or, if the user wants to re-run test, they invoke `/gld test` directly).
- contains `guild:qa` → resume at **qa**.
- contains `guild:test` → resume at **test**.
- contains `guild:execute` → resume at **execute**.
- contains `guild:design` → resume at **design**.
- contains `guild:analyze` → resume at **analyze**.
- none of the above → fresh Issue; start at **analyze**. Add the `guild:analyze` label now:
  ```bash
  gh issue edit $1 --add-label "guild:analyze"
  ```

Determine work type from the Issue's `type:` label (`type:feature|bug|refactor`) if present; default to feature. In M1, execute = **implement** only regardless of type (debug/refactor variants are a later milestone) — but analyze may still note the true type for the humans.

**Assemble the cast (as the leader).** With the work-type known, size up the change surface (Issue body + AC + hotspots) and decide which roster specialists this task needs — following the assembly rules in `leader.md` ("팀 조립 규칙") and the participation model in `_handoff.md` Section G. The **spine roles always run**; **participation roles** (designer/i18n/analytics/performance/dba/infra/security/product-owner/tech-writer/release-manager/support-triage) join only when their trigger matches; **gate reviews** (designer UI/UX, security) are inserted before advancing when risk matches. Hold this cast decision — each stage wrapper convenes the roles it owns (e.g. design convenes designer when the change is UI). When in doubt, convene minimally and let a downstream gap pull a specialist in later. Surface non-obvious/risky assembly choices to the human.

---

## Phase 2 — Run the spine

From the current stage, run each stage in order until `guild:done` or a stop condition. For each stage, **read the wrapper command inline and execute it** for Issue `$1`:

| Stage | Wrapper to read & execute |
|---|---|
| analyze | `<<SKILL_DIR>>/commands/analyze.md` |
| design | `<<SKILL_DIR>>/commands/design.md` |
| execute | `<<SKILL_DIR>>/commands/implement.md` |
| test | `<<SKILL_DIR>>/commands/test.md` |
| qa | `<<SKILL_DIR>>/commands/qa.md` |

Each wrapper **owns its own label transition** on success (single source — `_handoff.md` Section A) and returns a stage-level line (`_handoff.md` Section D). dev reads the returned line only to sequence the next stage:

- **`OK ADVANCE: <next>`** → the wrapper has already set `guild:<next>`. Continue by running `<next>`'s wrapper.
- **`OK DONE`** (from qa) → the wrapper has set `guild:done`. Report completion. Stop.
- **`NEEDS_HUMAN: <one-line>`** → a discuss/verify gate needs a human decision. **Attended**: as the leader, surface the options and ask the user (`AskUserQuestion`), then re-run the same stage wrapper with the decision. Do NOT auto-decide — plan §4: discuss refuses to proceed until the user chooses. **Unattended (`GLD_UNATTENDED=1`)**: there is no human — stages already self-resolve low/medium gates and return `OK PAUSE: needs-human` for high-stakes ones (`_handoff.md` Section H), so a `NEEDS_HUMAN` should not normally arrive here; if it does, treat it as `OK PAUSE: needs-human` (do NOT call `AskUserQuestion`).
- **`OK PAUSE: <one-line>`** → leave label as-is; report where it paused and how to resume (`/gld resume $1`). **Unattended**: a `needs-human` pause has already marked the Issue (`guild:needs-human` label + `<!-- guild:needs-human -->` comment, Section H); stop **cleanly** so the supervisor moves to the next Issue. Stop.
- **`FAIL: <reason>`** → stop; report the reason.

**Leader judgment between stages**: after each `OK ADVANCE`, briefly confirm the produced output is coherent enough to feed the next stage (completion judged by downstream consumability — plan §18 A). If a gap is obvious, loop back rather than advancing.

---

## Phase 3 — Report

On `OK DONE`: summarize what was built (stages run, PR link if any, test evidence). **Nudge the human review** — the PR now awaits the human reviewer (M1 external reviewer, INV1); suggest the guided pair review to make it lighter: "PR #<n> 리뷰 준비됨 — `/gld review $1`로 리스크 가중 가이드 리뷰를 받을 수 있습니다." On pause/fail: state the stage reached and the resume command. Never claim completion without the test stage's verify evidence (plan §18 B / `_handoff.md` Section E).

---

## Notes
- **Single Issue, in-session.** For multi-issue or unattended runs, that's a later milestone (sprint, gated). `/gld dev` is the everyday driver.
- **Leader is embodied, not spawned.** No separate leader sub-agent (avoids nesting). The main session IS the leader; only the stage roles (tech-lead/developer/tester) are spawned as sub-agents by the wrappers.
- **Labels are the state.** If interrupted, `/gld resume $1` or a fresh `/gld dev $1` re-reads the label and continues from there — no local state file to corrupt.
- **M1 review = human.** There is no agent-based independent/adversarial review in M1; the human approving the PR is the external reviewer (plan §18 A). Org collaboration (tech-lead conformance, tester-first) provides internal review.
