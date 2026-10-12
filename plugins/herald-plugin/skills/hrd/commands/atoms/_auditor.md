# ATOM — External auditor (outside the organization)

**Not a role file.** A fresh, persona-less, read-only reviewer spawned every time. It must not
share the organization's guides — sharing them would share their blind spots. Ported from
Guild `_execute_spine.md` 3.5a. Design: `design/herald/00-plan.md` §3.3.

## When

- In `critique`, only after the editor's PASS, up to 3 rounds per article (`HRD audit-round`;
  past the cap it is not spawned — `atoms/_stages.md` § critique 3).
- Outside the flow by `/hrd review` (same prompt) — a measuring instrument: on a healthy flow it
  finds nothing.

## Read-only tripwire

1. Before spawning (in `critique`: after `HRD audit-round`, which writes `state.json`; `/hrd
   review` counts no round): `HRD hash --slug
   <slug>` and record the hash of every file in `<w>`.
2. Spawn with an agent type that has no Edit/Write tools if available (e.g. `Explore`), else
   `general-purpose`; model `sonnet`.
3. After: hash again. Any change → discard the findings, restore nothing yourself, and stop
   (attended) / hold `needs-human` with cause `defect:` (unattended).

## Inputs (exactly these)

- the article file and the images it references (paths)
- the charter's **purpose** line (what the article promotes) and the **hard policies** from
  `docs/editorial/sources.md` and `promotion.md` (quoted, so intended policy is not reported
  as a defect)
- in `critique`, `recheck` rounds only (`HRD audit-round` → `mode`; never `/hrd review`): the earlier findings from
  `critique.json` `audit_log` (round, id, severity, one line, outcome), quoted
- nothing else: no style guide, no category guide, no exemplars, no research

## Prompt

> You are an independent, adversarial reviewer with no prior context. You read an article as a
> skeptical first-time reader and as a search-quality rater. READ-ONLY: do not create, edit,
> or delete any file.
> Find: AI-sounding prose and empty generalities · doorway-like thin content · excessive
> promotion · confident claims without grounds · title promises the body does not keep ·
> factual statements that look wrong · broken or misleading structure.
> Hard policies (intended — do not report them as defects): <quoted policies>.
> Purpose of the article: <charter purpose>.
> Output a list: `[BLOCKER|MAJOR|MINOR] <one line> — <where> — <why>`. BLOCKER = must not be
> published as is; MAJOR = should be fixed before publishing; MINOR = polish.
> (recheck rounds add:) Earlier rounds already decided these findings: <quoted audit_log>. A
> `dismissed`, `deferred`, `noted` or `open` one (an `open` one is with a human) is settled — do
> not raise it again, reworded or not. For a
> `fixed` one, check it: still present → report it tagged `unfixed <id>`. Tag every other
> finding `regression <id>` (a fix since the last round caused or worsened it — name the
> earlier id) or `new`: `[MAJOR|regression R1-2] …`. Report a BLOCKER only for what truly must
> not be published.
> <result-contract block from `_contract.md` §B, verbatim>
> <language line from `_contract.md` §D>

## Dismissals and deferrals

Which findings block and which are deferred: `atoms/_stages.md` § critique step 3. Per
`_contract.md` §C: attended MAJOR → editor-in-chief may dismiss with a reason; attended
(`--attended`, single-stage commands) BLOCKER → only after the human confirms; in-session auto and unattended BLOCKER →
never. Every dismissal goes to
`critique.md` and `critique.json` (`final_round.dismissed`, `decision_log` `kind: dismissal` —
for every BLOCKER a human confirmed dismissing, in any round, also `kind: human` with its id,
`atoms/_stages.md` § critique 3 — without it the dismissal counts as the agents' and blocks any
unread publish);
`HRD stage pass --stage critique` records the `dismissal` signals from that log.
