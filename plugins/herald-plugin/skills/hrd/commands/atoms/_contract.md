# ATOM — Shared contract (roles, unattended mode, language, tiers, loops)

**Not a stage.** Ported from Guild `_handoff.md` (C, H, K), `_model_tiering.md`,
`_stagnation.md`, adapted to articles. Design source: `design/herald/00-plan.md` §3.2–§3.3, §3.7.

## A. Tooling

- `HRD` below means `python3 .claude/herald/scripts/hrd.py`. Run each call as its own Bash
  call; it prints JSON on success and exits non-zero with a reason on a failed precondition —
  **stop and report the reason, never work around it**.
- One shell command per Bash call. No `&&` chains around state changes. Long text for GitHub
  goes through a temp file and `--body-file`.
- Read files with the Read tool, not `cat`.
- Paths: config `.claude/herald/config.json` · editorial `docs/editorial/` · work
  `.claude/herald/work/<topic-id>/` · roles `.claude/agents/`.

## B. Role handoff (status enum + RESULT line)

A spawned role returns files plus exactly one status line after a sentinel.

<!-- herald:result-contract -->
Return EXACTLY one status line, preceded by a `>>> RESULT <<<` sentinel on its own line. Anything before the sentinel is ignored. Status is one of `DONE` / `DONE_WITH_CONCERNS: <one-line>` / `BLOCKED: <one-line>` / `NEEDS_CONTEXT: <one-line>` / `FAIL: <reason>`. Artifacts are passed as files, not pasted — write them where your task says and name the path in the RESULT line.
<!-- /herald:result-contract -->

The block above is canonical; every spawn prompt carries a byte-identical copy (checked by
`tests/structure_test.sh`). Malformed reply (no sentinel, two sentinels, or a non-enum status):
re-invoke once naming the violation; still malformed → attended: stop and tell the human;
unattended: hold `needs-human`. Never infer a verdict from prose.

| Status | Leader action |
|---|---|
| `DONE` | `HRD stage pass`, next stage |
| `DONE_WITH_CONCERNS` | record the concern in the stage artifact and the PR body; proceed |
| `BLOCKED` | brief/research: hold with that stage's reason; others: stop (attended) / `needs-human` (unattended) |
| `NEEDS_CONTEXT` | supply the missing file from the stage's read list and re-invoke once |
| `FAIL` | stop; report |

**Spawning a role**: Agent tool with `subagent_type` = the role's agent name (from
`.claude/agents/<role>.md`); if that agent type is unavailable, `general-purpose` with
"Adopt the persona in `.claude/agents/<role>.md`." The prompt contains: the task, the stage's
**read list** (paths only — nothing else; §3.2 read lists are the whole input), the output
paths, the result-contract block, and the language line (§D). Default model = the role
file's `model:`; a genuine retry raises one tier (§E).

## C. Unattended mode (`HRD_UNATTENDED=1`, set by the batch runner)

Detect once per command: `printenv HRD_UNATTENDED` → `1` = unattended. The editor-in-chief
(main session) stands in for the human at in-flow gates; the human's authority is deferred to
`ship` (PR review), never removed.

| Gate | Attended | Unattended |
|---|---|---|
| brief approval | ask the human | approve if it meets the charter and category guide; record `kind: routine` |
| ambiguity (topic intent, angle) | ask | low/medium stakes: pick the charter-aligned reading, record `kind: assumption`; high/unsure: hold `needs-human` with cause `ambiguity:` |
| cannibalization conflict | ask | hold `cannibalization` (never guess) |
| auditor `MAJOR` | may dismiss with a recorded reason | may dismiss with a recorded reason (`kind: dismissal`) |
| auditor `BLOCKER` | dismiss only after the human confirms | **never dismiss** — fix or hold `needs-human` (`defect:`) |
| stagnation / loop cap / budget | stop and report | hold `stagnation` / `budget` |

**Decision log**: every judgment between brief and critique goes into
`work/<id>/critique.json` → `decision_log: [{"kind", "note"}]` with `kind ∈ {routine,
dismissal, assumption}`. verify and publish make no judgments; they only hold. `dismissal` and
`assumption` exclude a PR from auto publish. The PR body repeats the log under
`## Unattended decisions`.

Unattended children never write the base branch: they record their outcome with
`HRD result --topic <id> --status pr-open --pr <n>` or `--status held:<reason> --note "..."`
and stop cleanly (exit 0). The runner records holds.

## D. Output language

Human-readable output (messages, PR bodies, artifact prose, RESULT summaries) is in
`config.language`. Machine tokens stay ASCII: status enums, `held:<reason>` values,
`decision_log.kind`, labels (`herald`, `herald:reverted`, ...), markers, paths, JSON keys.
Every spawn prompt ends with: "Write all human-readable output in `<language>`; keep machine
tokens, code, paths and markers in English." Unattended runs add, immediately before it:
"Unattended: write free narration (before the `>>> RESULT <<<` sentinel) in ASCII English."

## E. Model tiers (Guild `_model_tiering.md`)

- haiku: mechanical work (none of the roles by default). sonnet: every role and the auditor.
  opus: a genuine retry's rewriting role (loopback 2+), evolve's adversarial panel.
- Role default = `model:` in its file (repo-owned). The retry bump applies to that one
  re-invocation; record `HRD signal --kind escalation` with the role and reason.
- The editor-in-chief is the main session: the user's model when attended,
  `config.models.batch_main` in batch children. Never proposed for change.

## F. Loops and stagnation

- critique and verify loopbacks share **3 per article** (`HRD loopback --topic <id>` returns
  `exhausted`). Human-requested revisions and `ship` delta research use `--human` / are not
  counted.
- **Stagnation guard**: if a loopback's reason repeats the previous one (same weakness or the
  same unsupported sentence), do not loop again — hold `stagnation` (attended: stop and show
  both rounds).

## G. Signals

Record with `HRD signal --kind <kind> --topic <id> --data '<json>'` at the moments the plan
names: `revise-weakness` (each REVISE), `audit-finding`, `dismissal`, `verify-gap`,
`gate-failure`, `hold`, `stagnation`, `escalation`, `session-edit-request` (write approval
edits), `human-edit` and `ship-decline` (ship), `review-finding` (review). Signals are local
(gitignored) and feed `evolve`.
