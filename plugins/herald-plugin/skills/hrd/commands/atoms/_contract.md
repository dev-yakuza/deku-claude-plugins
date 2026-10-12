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
| auditor `MAJOR` on a recheck round (`_stages.md` § critique 3) | `new` → defer to the PR (`kind: deferral`); `unfixed`/`regression` → fix (last round: any `MAJOR` → defer) | same |
| auditor `BLOCKER` | dismiss only after the human confirms | **never dismiss** — fix or hold `needs-human` (`defect:`) |
| verify gap, nothing contradicted, 1–3 unsupported (`_stages.md` § verify) | ask: trim / loop back / hold | trim once (delete or map only; code-checked), then loop back |
| stagnation / loop cap / budget | stop and report (budget: warn only) | hold `stagnation` / `budget` |

**Decision log**: every judgment between brief and critique goes into
`work/<id>/critique.json` → `decision_log: [{"kind", "note"}]` with `kind ∈ {routine,
dismissal, assumption, deferral, human}` (`human`: a human's decision on a last-round BLOCKER,
with its `id` — `atoms/_stages.md` § critique 3). verify and publish make no judgments — they
only hold — except the trim (§F), recorded in `state.json` `trim` and excluding the PR from
auto publish as `trimmed`.
`dismissal`, `assumption` and `deferral` exclude a PR from auto publish. The PR body repeats the log under
`## Unattended decisions` (`human` entries under `## Human decisions`).

**In-session auto** (the default of `/hrd write <id>` and `/hrd resume <id>`; `--attended`
asks the human at every gate instead): a normal session that asks the human nothing during the
flow. Gates follow the Unattended column above; holds
are recorded the attended way (`atoms/_stages.md` § Holds: `HRD state`, commit, push — no
`HRD result`); stagnation / loop cap / budget hold instead of stopping (budget: the article's
spend since the preflight baseline, `write.md` §0 step 7, over `per_article_usd` at a stage end
→ hold `budget`; a BLOCKER open on the last audit round →
hold `needs-human`); there is no session approval. **Pre-flow questions — exactly these three — are still asked**,
because they come before any work and the run cannot proceed safely without them: foreign
unpushed commits on base (`write.md` §0 step 4), the base merge for an existing branch with
older scripts (`atoms/_stages.md` § Existing branches) and, on `resume`, the decision on a held
topic. After them the flow asks nothing, except to confirm a human-directed BLOCKER fix; every other
gate follows the Unattended column above. Any other step that would ask (a `newer` version, an unexpected error) stops and reports instead —
it never guesses. Publishing is
the PR, then `/hrd ship` — or `ship --session-auto` right away when `autonomy.publish` is
`auto`, or when the human asked for this article to be published (`write --ship`,
`resume --ship`, `/hrd next`).

Unattended children never write the base branch: they record their outcome with
`HRD result --topic <id> --status pr-open --pr <n>` or `--status held:<reason> --note "..."`
and stop cleanly (exit 0). The runner records holds.

## D. Output language

Human-readable output (every message to the user — progress, questions, summaries, reports —
PR bodies, artifact prose, RESULT summaries) is in `config.language`, although these
instructions are English (SKILL.md "Language"). Machine tokens stay ASCII: status enums, `held:<reason>` values,
`decision_log.kind`, labels (`herald`, `herald:reverted`, ...), markers, paths, JSON keys, the
`--note` prefixes code reads (`tooling:`, `human:`, `ambiguity:`, `defect:`), any note starting
`tooling: herald version mismatch` (the whole note stays English), the CLI values (`--state`,
`--reason`, `--cause`, `--theme`) and the enum values in `critique.json`/`verify.json`
(`verdict`, `severity`, `tag`, `outcome`) — translate only the free text after a prefix. Commit
messages keep their English templates (free text in them in English too); a PR title is the
article title, in `config.language`.
Every spawn prompt ends with: "Write all human-readable output in `<language>`; keep machine
tokens, code, paths and markers in English." Unattended runs add, immediately before it:
"Unattended: write free narration (before the `>>> RESULT <<<` sentinel) in ASCII English."

## E. Model tiers (Guild `_model_tiering.md`)

- haiku: mechanical work (none of the roles by default). sonnet: every role and the auditor.
  opus: a genuine retry's rewriting role (loopback 2+), evolve's adversarial panel.
- Role default = `model:` in its file (repo-owned). The retry bump applies to that one
  re-invocation; `HRD loopback` returns `escalate_tier` and records the `escalation` signal
  itself (loopbacks 2 and 3; never for `--human`, never past the cap).
- The editor-in-chief is the main session: the user's model in interactive runs (attended or
  in-session auto),
  `config.models.batch_main` in batch children. Never proposed for change.

## F. Loops and stagnation

- critique and verify loopbacks share **3 per article** (`HRD loopback --topic <id> --cause …`
  returns `exhausted`). Human-requested revisions and `ship` delta research use `--human` / are not
  counted.
- External-auditor rounds are capped separately at **3 per article**, human-requested
  revisions included (`HRD audit-round` counts them; round 1 full, then recheck, then skip).
  A fresh auditor always finds something new, so later rounds block only on BLOCKERs, unfixed
  findings and regressions; the rest goes to the human at ship.
- **Trim** (`_stages.md` § verify): a verify gap of 1–3 unsupported sentences with nothing
  contradicted is first repaired by deleting those sentences (or mapping them to an existing
  claim, or dropping only a parenthetical aside the fact-checker named) — once per article, not counted as a
  loopback, checked in code (`HRD trim`). The
  agents settle it among themselves this way instead of holding; accepting an unsupported
  sentence as true is never theirs to decide.
- **Stagnation guard**: if a loopback's reason repeats the previous one (same weakness or the
  same unsupported sentence), do not loop again — hold `stagnation` (attended: stop and show
  both rounds).

## G. Signals

**Recorded by `HRD` itself** where the event happens — never call `HRD signal` for these:
- `gate-failure` — `stage pass` refuses on the gate.
- `revise-weakness` / `audit-finding` / `verify-gap` — `HRD loopback --cause revise|audit|verify`.
- `dismissal` — from `critique.json` `decision_log`, on `stage pass --stage critique` and on
  `loopback --cause audit`.
- `hold` — `HRD state --state held` (the batch runner records its own), except holds a human's
  change caused (`verify-after-human-edit`, `reverted`) and holds whose note starts with
  `tooling:` (environment) or `human:` (a human's choice): not writing problems.
- `ship-decline` — `HRD state --state declined`.
- `escalation` (loopbacks 2 and 3) and `incomplete` (a batch child that ended without a result;
  the runner) — context: listed for evolve, never counted by the nudge.

**Recorded with `HRD signal --kind <kind> --topic <id> --data '<json>'`** (they need a judgment
or a diff only the session has): `session-edit-request` (write approval edits), `human-edit`
(ship) and `review-finding` (review).

Signals are local (gitignored) and feed `evolve`. `HRD evolve-readiness` counts the unconsumed
ones deterministically: identical records once; malformed records and unreviewed human edits
excluded; baseline records (reviewed edits of ≤ 2 lines, clean reviews) listed for exemplars,
never counted; `tier` none | watching | sufficient — sufficient at ≥ 3 signals of one theme
(the kind, split by `theme` for REVISE and auditor findings and by reason for holds) from
≥ 2 topics, including one no completed evolve scan has seen. The same count drives evolve's
starting point, the `ship`
report nudge and the `status` line. Only a decided evolve proposal consumes signals
(`HRD evolve-mark --consume`).
