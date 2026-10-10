# ATOM — External auditor (outside the organization)

**Not a role file.** A fresh, persona-less, read-only reviewer spawned every time. It must not
share the organization's guides — sharing them would share their blind spots. Ported from
Guild `_execute_spine.md` 3.5a. Design: `design/herald/00-plan.md` §3.3.

## When

- In `critique`, only after the editor's PASS (every round that reaches PASS).
- Outside the flow by `/hrd review` (same prompt) — a measuring instrument: on a healthy flow it
  finds nothing.

## Read-only tripwire

1. Before spawning: `HRD hash --slug <slug>` and record the hash of every file in `<w>`.
2. Spawn with an agent type that has no Edit/Write tools if available (e.g. `Explore`), else
   `general-purpose`; model `sonnet`.
3. After: hash again. Any change → discard the findings, restore nothing yourself, and stop
   (attended) / hold `needs-human` with cause `defect:` (unattended).

## Inputs (exactly these)

- the article file and the images it references (paths)
- the charter's **purpose** line (what the article promotes) and the **hard policies** from
  `docs/editorial/sources.md` and `promotion.md` (quoted, so intended policy is not reported
  as a defect)
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
> <result-contract block from `_contract.md` §B, verbatim>
> <language line from `_contract.md` §D>

## Dismissals

Per `_contract.md` §C: attended MAJOR → editor-in-chief may dismiss with a reason; attended
BLOCKER → only after the human confirms; unattended BLOCKER → never. Every dismissal goes to
`critique.md`, `critique.json` (`final_round.dismissed`, `decision_log` `kind: dismissal`) and
`HRD signal --kind dismissal`.
