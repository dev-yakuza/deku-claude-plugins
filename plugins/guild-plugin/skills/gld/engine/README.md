# guild-plugin engine (`/gld`)

The mechanical half of Guild's redesign: the engine reads a procedure and runs it step
by step — role sessions (`claude -p`), named `run` commands under `srt`, built-in ops —
and judges only by named kinds, fixed codes and facts it collects itself.

Status: **P4** — every module is implemented and wired; the stage-1 feature flow runs end
to end against the fakes (see "Integration (P3-Z)"), every scope §5.2 scenario has a test,
and the boundary canary ran against the real CLI (see "Fixed scenarios and the real canary"). The design references
(§…) are to the redesign design document; the Korean contract summary with the section map
and every interpretation is `stage1/interfaces.md` next to it.

**Stage 2 (leader)**: contract fixed by V1 (Q2), implemented by the Q3 sessions A–D and wired
together by Q4 (see "Integration (Q4)") — the real `leader.call` runs inside the driver loop
against the fakes, every stage-2 §5.2 scenario has a test, the leader's answer schemas are
checked against recorded real sessions (Q5 / V13). `defaults.ENGINE_STAGE` is 2 since the merge
(Q6 / D21): `dev` / `resume` run the stage-2 engine; stage-1 tests pass `stage=1`. The Korean
contract summary is `stage2/interfaces.md`.

**Stage 3 (issue types and risk handling)**: contract fixed by V1 (Q2), implemented by the Q3
sessions A · B1 · B2 · C · D · E and wired together by Q4 (see "Integration (Q4, stage 3)") —
every stage-3 unit real inside the driver loop against the fakes, every stage-3 §5.2 scenario
has a test (`tests/test_scenario_stage3.py`). `defaults.ENGINE_STAGE` is **3** since Q4 (E36):
`dev` / `resume` run the stage-3 engine; every stage-1 / stage-2 path passes its `stage`
(the `instructions.*` default is `ENGINE_STAGE`) and keeps its tables, schemas and refusals.
The Korean contract summary is `stage3/interfaces.md` (Q4 changes: its "Q4 계약 변경" section).

**Stage 4 (sprints, init, the improvement candidates)**: contract fixed by V1 (Q2) — codes, schemas, the
new modules and every call site in the driver / cli, each at its earlier behaviour below stage 4 (H23) —,
implemented by the Q3 sessions A (sprint) and B (init and improvements) on disjoint files ("Stage 4
sessions (Q3)") and wired together by VZ (see "Integration (VZ, stage 4)"): the real supervisor starts real
member engines as child processes, every stage-4 §5.2 scenario has a test (`tests/test_scenario_stage4.py`).
`defaults.ENGINE_STAGE` is **4** since VZ: `dev` / `resume` / `sprint` / `init` / `base-check` run the
stage-4 engine; every stage-1 to stage-3 path passes its `stage`. The Korean contract summary is
`stage4/interfaces.md`.

- Standard library only, `python3 -I`. Entry: `python3 -I engine.py <command>` (`gxengine/cli.py`).
- Tests: `bash plugins/guild-plugin/tests/engine_test.sh` (unittest discover, `-I -B`).
- Never a paid call in tests: `claude` and `gh` are the fakes in `tests/fakes/bin`, and
  `tests/helpers/fakes.assert_fakes_first(env)` refuses any env that would reach the real tools.

## Layout

```
engine/
  engine.py                 entry point (U18)
  gxengine/                 the package — module map below
  schemas/*.schema.json     JSON Schema draft 2020-12 (validated by gxengine/schema.py)
  scripts/                  plugin check scripts run as named commands (U15)
  tools/convert_config.py   0.98.7 settings → .claude/guild/ (U16; stage 4: the init drafts, VB2)
  data/                     start procedure, templates, catalog, role files, frames, tasks (U15)
  tests/
    test_schema.py          the validator
    test_contracts.py       schemas ↔ codes.py ↔ examples ↔ render fixtures, module boundaries
    test_fakes.py           fake claude / fake gh / git helper
    helpers/                gitrepo.py (temp repo + bare remote), fakes.py (env + logs + guard)
    fakes/bin/{claude,gh}   the fake executables
    fixtures/
      contracts/            one valid example per schema (+ <schema>.<variant>.example.json)
      render/               render input → expected settings / srt / argv / env
      claude/f1, f2         recorded stream-json (Claude Code 2.1.323), normalised
      claude/leader/real-2.1.323/  recorded real leader sessions (V13 / Q5; README there)
      claude/scenarios/     fake-claude scenarios (README there)
      gh/                   fake-gh rule files
```

## Schemas

| Schema | File | Written by | Design |
|---|---|---|---|
| `procedure` | `docs/specs/<N>/procedure.yaml` (JSON text) | engine only | §4, §4.3, §6.1 |
| `template` | `.claude/guild/procedures/<type>.yaml`, plugin start procedure | init / human | §2, §3.1 |
| `state` | `<records>/state.json` — fixed core: `format, issue, revision, steps[].{id,status,latest_attempt}, last_head` | engine | §4.3, §5 |
| `log-line` | `<records>/log.jsonl`, one object per line | engine | §4.3, §4.2 |
| `brief` | `runs/<step>/<attempt>/brief.json` | engine | §6.2, §7.2-3 |
| `result-work` / `result-review` | `--json-schema` + `runs/…/result.json` | role | §6.2, §7.5, I5 |
| `facts` | `runs/…/facts.json` | engine only | §7.2-3, §9.3 |
| `repo-config` | `.claude/guild/config.json` | conversion script / human | §7.10, §7.4, §7.12 S8 |
| `leader-answer` (+ `-plan-gate` / `-done-gate` / `-new-comment`) | `--json-schema` of a leader call + its `result.json` — **enum templates**, filled per call by `schema.fill_enums` | leader (stage 2) | §6.3, stage-2 scope §2 |
| `leader-input` | `in/leader-input.json` of a leader call | engine only | stage-2 scope D25, V3 |
| `leader-answer-s3` / `-plan-gate-s3` / `-done-gate-s3` / `-step-removal` / `-pr-review` | stage-3 leader answers — enum templates (`codes.leader_answer_schemas(stage)`) | leader (stage 3) | stage-3 scope §2 |
| `result-work-s3` / `result-review-s3` | stage-3 role results — enum templates (`codes.result_schemas(stage)`) | role (stage 3) | stage-3 scope E16, E22, E33 |
| `catalog` | `data/catalog.json` | plugin | stage-3 scope E14 |
| `sprint-state` · `sprint-log-line` | `<records>/…/sprints/<tracker>/{sprint.json,log.jsonl}` | supervisor only | stage-4 scope §2.2 |
| `base-green` | `<records>/…/base-green/<sha>-<config>.json` | engine (`basecheck`) | stage-4 scope §2.7 (H12) |
| `init-decisions` | `<home>/init/<owner>/<repo>/decisions.json` | `engine.py init answer` | stage-4 scope §2.9 |
| `mutations` | `docs/specs/<N>/mutations.json` (committed by a developer step) | role — a declaration, never a claim | VB9 |
| `mutation-record` | `<records>/…/<N>/mutations/<head>/record.json` | engine (`mutation`) | VB9 |
| `incident` | `<home>/incidents/<slug>/incident.json` (+ `evidence/`) | engine (`incidents`) | readiness R1 |
| `fixed-defects` | `data/fixed-defects.json` | plugin (one entry per fixed engine defect, each with a `@fixes_defect` test) | readiness R1 |

Every enum value lives in `gxengine/codes.py` (one module); `test_contracts.EnumSync`
keeps the schema files equal to it.

## Module map and dependency direction

`a ─► b` = a imports b. A module imports only modules of a LOWER layer, plus the
same-layer edges drawn inside a layer below. Enforced by `test_contracts.ModuleBoundaries`
(`LAYERS`, `SAME_LAYER`), which also refuses any non-stdlib import.

```
L4 orchestration     cli ─► driver ─► lifecycle        cli ─► lifecycle
                     cli ─► canaryrun ◄─ driver
                     cli ─► sprint ─► lifecycle · basecheck      cli ─► initconfig ─► basecheck · canaryrun
                     cli ─► basecheck         (stage 4; sprint never imports driver, H1)
                     cli ─► retention ─► lifecycle                     (readiness R1)
                     cli ─► channel ─► lifecycle                       (readiness T1)
                     cli ─► initharness ─► channel · initconfig        (readiness T2)
                               │
                               ▼  (any lower layer)
L3 step mechanics    results ─► facts    results ─► statemachine    rules ─► statemachine
                     prbody ─► facts     session   runner   budget
                     leader ─► session · facts · statemachine          (stage 2)
                     testchange     mutation ─► runner                 (stage 4)
                     incidents                                         (readiness R1)
                     history ─► gitops · acparse                       (readiness E4)
                               │
                               ▼
L2 boundary/outside  canary ─► render    github ─► outbound ─► gitops    instructions
                     sprinttracker ─► github                           (stage 4)
                               │
                               ▼
L1 files and data    store ─► paths      procedure ─► catalog    repoconfig    acparse    ladder
                     sprintdag    issuerefs                            (stage 4)
                               │
                               ▼
L0 foundation        globs ─► defaults ─► codes        schema    fsafe    streamjson
```

| Module | Layer | Unit | Responsibility |
|---|---|---|---|
| `codes` | L0 | P2-0 | every enum / fixed code, §6.3 allowed-answer table |
| `defaults` | L0 | P2-0 (values: U6, U14) | plugin defaults: §7.9 model/effort, tool sets, limits, budgets, env scrub, secret/control lists |
| `schema` | L0 | P2-0 | the draft 2020-12 subset validator |
| `fsafe` | L0 | U2 | link-refusing atomic writes (S6) |
| `streamjson` | L0 | U12 | stream-json reading (init, result, tool uses, denials, cost) |
| `globs` | L0 | U3 | the one path-glob dialect, control-file test |
| `paths` | L1 | U2 | engine record layout (M6), worktree path, srt TMPDIR |
| `store` | L1 | U2 | state.json / log.jsonl / attempt files, format conversion |
| `procedure` | L1 | U3 | template → procedure, grammar checks beyond the schema |
| `repoconfig` | L1 | U16 | repository settings loader and queries |
| `acparse` | L1 | U15 | AC parser shared by ac-format / ac-coverage, I1 fields |
| `catalog` | L1 | stage 3 V2 · V6 | plugin step catalog: load, developer step, positions, input propagation, request decisions (pure; shell until Q3) |
| `ladder` | L1 | stage 3 V11 | model / effort layers and the retry raise (pure; shell until Q3) |
| `render` | L2 | U5 | `--settings`, srt settings, claude/srt argv, env |
| `canary` | L2 | U12 | srt self check, boundary canary (no system/init comparison — FC decision D) |
| `gitops` | L2 | U10 | pinned git calls, ranges from the recorded base, blob reads, commit, push |
| `outbound` | L2 | U10 | secret scan, close keywords, full-width neutralising |
| `github` | L2 | U10 | gh calls, issue.md, summary comment, labels, PR |
| `instructions` | L2 | U15 | work-instruction frames, system prompt assembly |
| `statemachine` | L3 | U4 | transitions, back_to, counters, §4.4-3 reset |
| `facts` | L3 | U7 | facts.json collection (judgment vs measurement) |
| `session` | L3 | U6 | role session runner (spawn, watch, kill group) |
| `runner` | L3 | U9 | run steps under srt, I8 extras, toolchain prepare |
| `results` | L3 | U8 | result + facts → Outcome, boundary judgments, judge-output commits |
| `rules` | L3 | U11 | mandatory rules on the actual changed files |
| `budget` | L3 | U14 | issue cost, soft / absolute budget |
| `prbody` | L3 | U17 | PR body from facts |
| `leader` | L3 | stage 2 V2 · V3 | leader sessions: allowed answers (narrowing), answer-schema render, leader-input.json, answer checks, format re-calls, failure classes — returns `LeaderResult` |
| `lifecycle` | L4 | U13 | detach, lock, resume answers |
| `driver` | L4 | P3 | the main loop wiring every unit |
| `canaryrun` | L4 | P4 | the canaries as actions: paid role canary (`engine.py canary`), free srt canary (driver, before runs), records |
| `cli` | L4 | U18 | command line, exit codes |
| `sprintdag` | L1 | stage 4 VA1 (VA4: window) | member table, plan hash, order, dependency verdicts, base choice, window (pure) |
| `issuerefs` | L1 | stage 4 VB4 | `#N` references of an Issue body (stage ≥ 4: ranges, a following Korean particle) |
| `sprinttracker` | L2 | stage 4 VA2 | tracking Issue, run marker, dependency facts, merge settings, remote state |
| `testchange` | L3 | stage 4 VB5 | E9-2: base test files a human allowed |
| `mutation` | L3 | stage 4 VB9 | the engine runs declared mutations before the done-gate |
| `history` | L3 | readiness E4 | read-only git facts of an Issue: bug evidence, related files, commits since it was written (no verdict) |
| `sprint` | L4 | stage 4 VA4 | the supervisor: members as child engines, outcomes, quota, window, locks, status / report |
| `basecheck` | L4 | stage 4 VB1 | are the named commands green on a base commit — the one function A and B share |
| `initconfig` | L4 | stage 4 VB3 | init: doctor · propose · answer · check · write |
| `incidents` | L3 | readiness R1 | incident bundles of engine-caused / suspected needs_human stops: signature, evidence copy, secret removal, list, retro prune against `data/fixed-defects.json` |
| `retention` | L4 | readiness R1 | records cleanup: a sprint's merged / closed members (retro), Issue records untouched for 90 days (status) |
| `channel` | L4 | readiness T1 R4-14 | one channel per repository: the `.claude/guild-channel` verdict (routing, the write commands' entry), the switch (the other channel's unfinished runs, the commit gate of the target) |
| `initharness` | L4 | readiness T2 | init's harness part the engine decides: role files to write (`writes_role_files`), the 0.98.x install migration (harness.json with the sprint history, backup, commit gate) |

Units outside the package: U15 `scripts/*`, `data/*`; U16 `tools/convert_config.py` and the
three repositories' `.claude/guild/`; U18 the `/gld` skill docs; U19 `collect.py --log`
(design/metrics, reads `log-line`); U20 the fixed-scenario suite (`tests/test_scenario_*.py`, P4).

## Parallel sessions (P2) — file ownership

Each session writes only its own files. Files marked **frozen** change only through the
contract-change rule below.

| Session | Units | Owns (create / edit) |
|---|---|---|
| 1 | U2 · U3 · U4 | `gxengine/{fsafe,paths,store,procedure,globs,statemachine}.py`; `tests/test_{fsafe,paths,store,procedure,globs,statemachine}.py`; `tests/fixtures/procedure/**` |
| 2 | U5 · U12 | `gxengine/{render,canary,streamjson}.py`; `tests/test_{render,canary,streamjson}.py`; new files under `tests/fixtures/render/` and `tests/fixtures/claude/canary/` |
| 3 | U10 | `gxengine/{gitops,github,outbound}.py`; `tests/test_{gitops,github,outbound}.py`; new files under `tests/fixtures/gh/` |
| 4 | U15 | `gxengine/{instructions,acparse}.py`; `scripts/**`; `data/**`; `tests/test_{instructions,acparse,templates,scripts}.py`; `tests/fixtures/ac/**` |
| 5 | U16 | `gxengine/repoconfig.py`; `tools/**`; `tests/test_{repoconfig,convert_config}.py`; `tests/fixtures/config/**`; the three repos' `.claude/guild/` (human review + commit) |
| frozen | P2-0 | `gxengine/{codes,defaults,schema}.py`, `schemas/**`, `tests/test_{schema,contracts,fakes}.py`, `tests/helpers/**`, `tests/fakes/**`, `tests/fixtures/contracts/**`, existing `tests/fixtures/render/*.json`, `tests/fixtures/claude/{f1,f2}/**`, the existing scenarios, this README |

Shared rules:
- `tests/engine_test.sh` must stay green in every session's commit (the U5 snapshot test
  skips while `render` is a stub and must pass once it is not).
- A session may add a new module only with a row in the map, a layer in
  `test_contracts.LAYERS` (that edit is allowed) and no upward import.
- Session 2 owns the *rule lists* inside the render fixtures (which paths, which rules);
  the *key structure* (`settings` = permissions/sandbox/hooks, srt = network/filesystem
  with all required keys, argv order, env keys) is frozen.

## Parallel sessions (P3) — file ownership

Replaces the P2 table for P3 (P2 sessions are done). Same rules: own files only, frozen
files only through "Changing a contract" (P3-0 was that session), `engine_test.sh` green.

| Session | Units | Owns (create / edit) |
|---|---|---|
| P3-A | U6 · U7 · U8 | `gxengine/{session,facts,results}.py`; `gxengine/globs.py` (add a case-insensitive option — macOS); `gxengine/instructions.py` (add work-instruction text only); their tests; new files under `tests/fixtures/claude/scenarios/` prefixed `a-` |
| P3-B | U9 · U17 · verify-gate | `gxengine/{runner,prbody,render}.py`; `skills/gld/gates/**` (newly owned); `gxengine/repoconfig.py`; `tools/**`; `data/templates/**`; their tests; new scenarios prefixed `b-` |
| P3-C | U11 · U14 · U13 · U18 | `gxengine/{rules,budget,lifecycle,driver,cli}.py`; `engine.py`; the `/gld dev\|resume\|status` entry points in `skills/gld/SKILL.md` and `commands/**`; their tests; new scenarios prefixed `c-` |
| P3-Z | integration (later) | everything |
| P4 | U20 · real canary | everything (frozen files through "Changing a contract") |
| frozen | P2-0, P3-0 | as in the P2 table |

P3-0 contract change — what the owners still had to do (all done by P3-B / P3-A / P3-Z):
- `render` (P3-B): `sandbox_exceptions.allow_local_binding` / `weaker_network_isolation` /
  `allow_write` and the new `run_env` stay `RenderError` / unused until implemented (pinned by
  `test_render`). Implementing them: srt `network.allowLocalBinding`, top-level
  `enableWeakerNetworkIsolation`, `allow_write` entries as extra write roots with
  `{user_tmp}` = `getconf DARWIN_USER_TEMP_DIR` (a new optional `paths.user_tmp` input;
  required when an entry uses the token, otherwise refuse), `run_env` added to the run env
  after the scrub. Update the render fixtures and `test_render` together.
- `repoconfig` (P3-B): also refuse `allow_write` entries that are an ancestor of home or
  inside `defaults.HOME_SECRETS`, and a `run_env` name that is also a `cache_env` name.
- `tools/**` (P3-B): move non-path values out of `cache_env` into `run_env` in the session 5
  proposals (`tools/out/*/config*.json`, e.g. `TURBO_TELEMETRY_DISABLED`), and write the
  user temp exception as `{user_tmp}`, not a `/private/var/folders/…` path.
- `session` (P3-A): `--max-budget-usd` = `defaults.SESSION_MAX_BUDGET_USD[<role name>]`
  (role kind, no `/phase`), `FORMAT_REPAIR_BUDGET_KEY` for the haiku format repair; a role
  missing from the dict gets no session.
- `globs` (P3-A): `CONTROL_FILE_GLOBS` now has `**/.claude/**`; `names_control_file`
  skips `**`-led folder globs, so an output glob like `pkg/.claude/*.md` is not yet refused
  there (the rendered deny still covers it).

## Stage 2 sessions (Q3) — file ownership

Replaces the P3 table for stage 2 (stage-2 scope §6.2). Same rules: own files only, frozen files
only through "Changing a contract" (V1 / Q2 was that session), `engine_test.sh` green, stage-1
tests (`stage=1`) stay green. The A ↔ B contract is `leader.call(LeaderRequest) -> LeaderResult`;
B receives the leader through a new `driver.Units.leader` (default `gxengine.leader`) and tests
with a double.

| Session | Units | Owns (create / edit) |
|---|---|---|
| A leader | V2 · V3 | `gxengine/leader.py`; `tests/test_leader.py`; `tests/fixtures/leader/**`; new scenarios `tests/fixtures/claude/scenarios/l-*` (the V1 ones may be edited too); in `gxengine/paths.py` / `gxengine/store.py` only the `leader/<k>/` folder helpers (D13) |
| B flow | V4 · V5 · V6 · V7 · V8 (engine) · V9 | `gxengine/{driver,lifecycle,statemachine,procedure,rules,budget,github,cli}.py`; `engine.py`; the resume flow in `skills/gld/SKILL.md` and `commands/**`; their tests; new `tests/fixtures/gh/` files; `tests/test_scenario_stage1.py` only where a stage-1 position moves (V8) |
| C content | V10 · V8 (template) | `engine/data/**` (`roles/leader.md`, `tasks/plan-gate.md` · `done-gate.md` · `needs-leader.md`, `templates/feature.json`); `gxengine/instructions.py`; `tools/**` (the three repositories' proposals `tools/out/*`); `tests/test_{instructions,templates}.py` |
| D output · metrics | V11 · V12 | `gxengine/prbody.py`; `tests/test_prbody.py`; `tests/fixtures/prbody/**`; outside the engine `design/guild/24-redesign/metrics/{collect.py,metrics.md}` (stage-2 section) |
| Q4 integration | driver wiring A ↔ B, e2e with a fake leader, V14 L suite | everything (frozen files through "Changing a contract"); flips `defaults.ENGINE_STAGE` to 2 at the merge (D21) |
| frozen | P2-0, P3-0, V1 | `gxengine/{codes,defaults,schema}.py`, `schemas/**`, `tests/test_{schema,contracts,fakes}.py`, `tests/helpers/**`, `tests/fakes/**`, `tests/fixtures/contracts/**`, existing fixtures (incl. the existing render fixtures and `claude/{f1,f2}`), this README |

What the owners still have to do after V1 (see `stage2/interfaces.md` for the full list):
- B: switch the allowed-answer lookups (`lifecycle.allowed_answers`, `statemachine._stop`,
  `driver` stop) to `codes.allowed_answers_table(stage)`; D9 (`Allowed.escalate_only` → no
  call, needs_human without a recommendation) and the leader-call cap (`LEADER_CALL_COUNTED`,
  `LEADER_CALLS_MAX` → `absolute-limit`); `apply_answer(…, who=leader)`; procedure grammar for
  stage 2 (`STAGE2_OPS`, done-gate right before create-pr, a start-only procedure).
- A: `paths` / `store` helpers for `leader/<k>/`; brief `kind: leader` + `leader{…}`, facts
  `kind: leader`.
- C: the leader role file and task frames name `in/leader-input.json` and say that the engine
  branches only on the enum fields.

## Stage 3 sessions (Q3) — file ownership

Replaces the stage-2 table for stage 3 (stage-3 scope §6.2). Same rules: own files only, frozen
files only through "Changing a contract" (V1 / Q2 was that session), `engine_test.sh` green,
stage-1 and stage-2 tests stay green. B2 receives the other sessions' functions through
`driver.Units` doubles (the names are in `stage3/interfaces.md`). P2 units (V12–V14) are each
session's last commits (E37).

| Session | Units | Owns (create / edit) |
|---|---|---|
| A content | data of V4 · V5, `catalog.json` of V2, V19 | `engine/data/**`; `gxengine/instructions.py`; `tools/**` (the three repositories' proposals `tools/out/*`); `tests/test_{instructions,templates,convert_config}.py` |
| B1 procedure | V2 (positions, propagation) · V3 (path expansion, adjust) · V6 (request decisions) · V10 | `gxengine/{procedure,rules,catalog,repoconfig,acparse}.py`; `scripts/ac_format.py`; their tests; `tests/fixtures/procedure/**` |
| B2 flow | wiring of V2 (`roles_available`) · V3 (template reading, start-time assembly) · V4 (new `in:` files) · V6 · V7 · V8 (op) · V9 · V11 (Q8 ②) · V12 · V13; V15 | `gxengine/{driver,statemachine,lifecycle,budget,cli}.py`; `engine.py`; the resume flow in `skills/gld/SKILL.md` and `commands/**`; their tests |
| C run · facts | V4 · V5 runners, V11 ladder / session, V14 facts, result checks, Q8 ③ | `gxengine/{runner,facts,results,session,render,ladder,store,paths}.py`; their tests; `tests/fixtures/claude/scenarios/t-*` (role results) |
| D leader | leader side of V3 · V6 · V7 · V8 · V12 · V13 | `gxengine/leader.py`; `tests/test_leader*.py`; `tests/fixtures/leader/**`; `tests/fixtures/claude/scenarios/t-l-*` |
| E outside · output | V8 (GitHub, op) · V13 (fetch, fast-forward, PR reviews) · V16 · V17 | `gxengine/{github,gitops,outbound,prbody}.py`; their tests; `tests/fixtures/{gh,prbody}/**`; outside the engine `design/guild/24-redesign/metrics/{collect.py,metrics.md}` (stage-3 section) |
| Q4 integration | driver wiring, e2e, V20 T suite, `ENGINE_STAGE = 3` | everything (frozen files through "Changing a contract"); `tests/test_{e2e_stage3,scenario_stage3}.py`, `tests/z_world.py` |
| frozen | P2-0, P3-0, V1 of stages 2–3 | `gxengine/{codes,defaults,schema}.py`; `schemas/**`; `tests/test_{schema,contracts,fakes}.py`; `tests/helpers/**`; `tests/fakes/**`; `tests/fixtures/contracts/**`; existing fixtures; this README |

Modules in no row (`fsafe`, `globs`, `streamjson`, `canary`, `canaryrun`, `scripts/{ac_coverage,verify_gate}.py`)
and `data/start.json` rules other than its inputs do not change in stage 3.

## Stage 4 sessions (Q3) — file ownership

Replaces the stage-3 table for stage 4 (stage-4 scope §6.2, user decisions A13 / A14, review-q0 D1–D11).
Same rules: own files only, frozen files only through "Changing a contract" (V1 / Q2 was that session),
`engine_test.sh` green, every stage 1–3 test stays green, everything new at stage ≥ 4 only (H23). Two
sessions, never more. Paths are relative to `plugins/guild-plugin/`; `E/` = `skills/gld/engine/`,
`C/` = `skills/gld/commands/`. `tests/test_stage4_wiring.py` (`Ownership`) reads the two rows and fails
on a path in both.

| Session | Units | Owns (create / edit / delete) |
|---|---|---|
| A sprint | VA1–VA6 | `E/gxengine/{sprint,sprintdag,sprinttracker,driver,lifecycle,statemachine,gitops,github,cli}.py` `E/engine.py` `E/tests/test_sprint*.py` `E/tests/test_{driver,lifecycle,statemachine,gitops,github,cli,cli_stage2,cli_stage3,stage4_shells_a}.py` `E/tests/fixtures/sprint/**` `E/tests/fixtures/gh/sprint-*.json` `C/sprint.md` `C/sprint/{run,plan,retro,sync}.md` `C/batch.md` `C/engine/**` `C/atoms/{stack_sync,render_supervisor,spawn_supervisor}.py` `C/atoms/{_bash_rules,_handoff,_execute_spine,_sprint_dag}.md` `skills/gld/SKILL.md` `skills/gld/templates/sprint-supervisor.sh` `tests/{prompt_structure,rename,stack_sync,sprint_supervisor,batch_script}_test.sh` |
| B init · improvements | VB1–VB9 | `E/gxengine/{basecheck,initconfig,issuerefs,testchange,mutation,runner,prbody}.py` `E/tools/**` `E/data/frames/stage4-work.md` `E/data/tasks/stage4/**` `E/data/tasks/leader-stage4/**` `E/tests/test_{basecheck,initconfig,issuerefs,testchange,mutation,runner,runner_stage3,prbody,convert_config,stage4_texts,stage4_shells_b}.py` `E/tests/fixtures/init/**` `E/tests/fixtures/config/**` `E/tests/fixtures/prbody/**` `E/tests/fixtures/mutation/**` `C/init.md` `C/atoms/scan_repo.md` `skills/gld/templates/CLAUDE.md.tmpl` `tests/{init_structure,install}_test.sh` |
| VZ integration | wiring A ↔ B, e2e, the T suite, `ENGINE_STAGE = 4`, version | everything (frozen files through "Changing a contract"); `E/tests/test_{e2e_stage4,scenario_stage4}.py` |
| frozen | P2-0, P3-0, V1 of stages 2–4 | `E/gxengine/{codes,defaults,schema,paths,store,leader,instructions}.py`; `E/schemas/**`; `E/tests/test_{schema,contracts,fakes,stage4_wiring}.py`; `E/tests/helpers/**`; `E/tests/fakes/**`; `E/tests/fixtures/contracts/**`; every existing fixture; this README; the documents H13 changed that no row lists |

- Outside the engine, B also owns `design/guild/24-redesign/metrics/{collect.py,metrics.md}` and
  `validation-archive/reset.py` (VB7; A13: `codes.stop_cause`).
- Modules in no row (`render`, `canary`, `canaryrun`, `session`, `results`, `facts`, `rules`, `procedure`,
  `catalog`, `ladder`, `outbound`, `fsafe`, `globs`, `streamjson`, `acparse`, `repoconfig`, `budget`), the
  other `data/**` files and every shared test / world (`test_q8`, `test_s3_*`, `test_e2e*`,
  `test_scenario_*`, `test_leader*`, `test_results`, `c_world`, `s3_world`, `z_world` …) do not change.
- In `tests/fixtures/{gh,config,prbody}` a session only ADDS files; `gh/sprint-700.json` (V1) may be
  extended by A.
- `test_stage4_shells_{a,b}.py` held what was only true of a shell; each owner deleted its file when its units
  replaced the shells (both are gone).
- `C/init.md` line 163 is cited by line from A's files (`init.md:163`): B keeps that line there, or
  reports the new place for VZ.

## Integration (P3-Z)

`driver.Units()` defaults are the real modules (session, facts, results, runner, prbody,
github, gitops, rules, budget). One attempt, in this order (P3-A call order, human decision 1):

- role: `docs/specs/<N>/` → `facts.start_facts(ctx, step_id, …)` (+ `requested`, `reentry`)
  → `session.run_session(…, version=)` → `facts.finish_facts` →
  `results.add_boundary_facts(…, results.owner_facts(…))` (the ONLY place the boundary facts
  are filled) → `results.judge_role(…, quota_reset_at=)` → `statemachine.apply` → when done
  and a judge with outputs, `results.commit_judge_outputs(…, facts)` → `store.write_facts`.
- run: srt → `runner.toolchain_prepare` (first run of an engine start) →
  `runner.run_step(…, issue=, attempt=, paths=driver.render_paths(…, "run"), prepare_tree=,
  control_check=)` → `finish_facts` → `add_boundary_facts` → `results.judge_run(step, facts,
  StepRun.outcome)` — the verdict is the runner's (base-red first), the security boundary
  (control files) still first.
- Exceptions: `FactMissing` → infra, `UnsafePath` → `unsafe-path`, `SessionError` /
  `RenderError` / `RunnerError` → `engine-error` (I14).
- The absolute attempt cap is `defaults.total_attempts_max(len(procedure.steps))` = steps × 4.
- Role sessions run with HOME = `paths.home` (the user's home; a fake home only in the canary
  layout — otherwise the home-secret denies would follow the fake home).
- ~~The three run-only sandbox exceptions are never given to a role session~~ — replaced in
  P5 (F2, below): the developer gets the run's toolchain environment; a judge never does.
- Toolchain prepare: outside the sandbox only `sync` (a file copy from a trusted source into
  `{cache}`, re-made every engine start, links never followed); every `cmd` runs in srt.
- Control files in a run: CLAUDE.md / CLAUDE.local.md / AGENTS.md are denied per folder git
  does not ignore (`paths.worktree_dirs`), so `run: setup` may unpack them into a gitignored
  folder; `.claude/**` and procedure.yaml stay denied everywhere; role sessions keep every
  glob. The cumulative check skips such name-only control files under gitignored paths.
- End-to-end tests: `tests/test_e2e.py` (+ `tests/z_world.py`): fake claude, fake gh
  executable, bare remote, temp repository, real srt.

## Integration (Q4, stage 2)

- `driver.Units().leader` is `gxengine.leader`. One leader turn: the stop is `needs_leader` (a
  check step opens at needs_leader — `statemachine.open_check`; a needs_leader situation comes
  from `statemachine.stop_status(stage=2)`) → D9 / D14 / absolute caps / judge canary record →
  `driver.leader_request` (the driver-only facts) → `leader.call` (its sessions are the check
  step's attempts, or `leader/<k>/`) → `state.leader_calls` → `driver.apply_answer(…, who=leader)`
  = the human's path (lifecycle.apply_answer + revision 2 on plan, the close on close-as-decided).
- The leader's `-p` text is `instructions.build_leader_instruction` (frame `data/frames/leader.md`
  + the situation's task text) + the call's allowed answers.
- The PR body gets the done-gate's engine-numbered discoveries (`in/leader-input.json`
  `done_gate.discoveries`), the leader notes and — only when a `security` discovery exists —
  GitHub's `isPrivate` (D27; unknown = public). The summary comment adds prbody's waiting /
  recommendation / failure lines and the withheld security count.
- The leader `in/` files and the done-gate review diff follow the P5 fixes: bytes round-trip
  (surrogateescape), `gitops.review_diff_text` (binary files as one line).
- From stage 2 the step id `leader` is reserved (the needs_leader temp folders).
- Output pipes (Q6, measured by Q5): a process that left the group (setsid) and still holds the
  output pipe no longer keeps the engine waiting. `runner._spawn_group` returns `DRAIN_S` after
  the group is killed and ends run.log with `runner.OUTPUT_CUT_MARK`; `session.run_session`
  returns `KILL_GRACE_S` after the kill with the warning `session.STREAM_CUT_WARNING`. Both read
  the raw pipe fd through a selector (a buffered reader's lock blocked the close).
- End-to-end with the real leader: `tests/test_e2e_stage2.py`; the stage-2 fixed scenarios:
  `tests/test_scenario_stage2.py` (`SCENARIOS` L1–L26, N1', N2' → tests; L5 / L11 / L20 end to end).

## Integration (Q4, stage 3)

- `driver.Units()` defaults are the real stage-3 modules (`catalog`, `ladder`, `procedure`, `rules`,
  `github`, `gitops`, `acparse`, `repoconfig` + the stage-2 ones). Every call into `instructions`
  names the engine stage (`load_start_procedure`, `build_instruction`, `build_leader_instruction`,
  `load_default_template`); the repository settings are read with the step catalog (E25 gate check).
- Ownership (review-q0 D2, K2): `results.owned_files(paths, procedure)` → `owned=` of
  `add_boundary_facts` and `judge_role`; an evidence run gets `facts.step_files` of
  `runner.evidence_author`; ac-format gets `--stage 3 [--deferred …]`.
- create-followups (E20, E21, A4): `prbody.followup_items` → `github.apply_followups` (its rows
  recorded into `state.followups` one by one) → the PR body PATCHed with
  `build(stage3={is_private, dry_run, followups})` → the completion comment. `followups_dry_run`
  of the repository settings writes nothing to GitHub but the PR body; the would-be writes go to
  `<records>/…/<N>/followups-dry-run.jsonl`. The security record (every security discovery) is
  engine-local.
- Coordinator decisions Z1–Z7: the srt temp folder `/tmp/gx-<issue>-<attempt>-<repo hash>-<pid>`
  (`driver.srt_run_id`); a `--resume` call's cost is its own (`streamjson.call_cost`); an
  effort-only raise keeps `--resume` (`ladder.EFFORT_CHANGE_RESUMES`); a work role's output glob may
  have `*` / `**` folder segments (B1) — the render boundary keeps the control-file denies; an
  out-of-scope fix leaves `state.included_fixes`; a plan-gate on a non-stage-3 analysis goes back to
  analyze once; a lone surrogate of result.json is passed on escaped.
- End to end: `tests/test_e2e_stage3.py` (+ `tests/z_world.py` `Z3World`); the stage-3 fixed
  scenarios: `tests/test_scenario_stage3.py` (`SCENARIOS` TY1 … TX4 → tests, Z1–Z7).

## Integration (VZ, stage 4)

- The real units: `sprint.default_units` = `basecheck.check`, `sprinttracker`, `gitops`, the cli's self check
  (srt + the gate hook) and `spawn_member` (a child `engine.py dev --mode unattended --foreground …` in its own
  session, D5); the member engine uses `driver.Units()` — `prbody` draws the stack block between
  `defaults.SPRINT_STACK_MARKER` … `_END` from the state's `base_branch` / `draft` / `sprint`, `mutation.prove`
  runs before the done-gate, `testchange.allowed` reaches `frozen_violations`. Nothing was missing after the
  two merges; `tests/test_e2e_stage4.py` (TX5) runs it all as child processes against the fakes.
- The stage-4 PR body (R2 6단계, `prbody._stage4_layout`): open on top 「무엇을 바꿨나」 (the done-gate answer's
  `summary`, 1–3 lines, else three engine-fact lines), 「사람이 확인할 것」 (the qa checklist with its
  `<!-- guild:manual-qa -->` markers), assumptions · deferred rows · out-of-scope findings · the follow-up Issues the
  engine filed and the existing Issues it commented on (Q11 — filed without asking, so read, not folded) · out-of-scope
  fixes; every other section in
  its own `<details>` (`prbody.STAGE4_FOLDS`). The same lines as the flat stage-1–3 body — `tests/test_stage4_pr_body.py`.
  A `manual` done-gate verdict carries `why_not_automated` (E5, `manual-reason-mismatch`), shown after its evidence.
- `member-end` / `member-blocked` `data.cost_usd` is the member's spend in THIS run (its `totals.cost_usd`
  after the child minus before, null when no child ran) — `collect.py` adds runs up; `sprint.json` rows keep
  the Issue's total.
- `issuerefs`, stage ≥ 4: a single `#N` and the bare end of `#a~b` may be followed by a letter of another
  script (`#104이`); stages 1–3 keep the word boundary.
- The base check keeps its free srt canary as a child process (`engine.py canary --srt-only --config`); no
  `("basecheck", "canaryrun")` pair in `SAME_LAYER` (B's optional request — it would only save the child).
- End to end: `tests/test_e2e_stage4.py`; the stage-4 fixed scenarios: `tests/test_scenario_stage4.py`
  (`SCENARIOS` TD1 … TX5 → tests, VZ1–VZ3).

## After the validation (Q8, stage 3)

What the Q7 validation showed to stop Issues without need (`stage3/q7-result.md`); tests:
`tests/test_q8.py`, `test_runner_stage3.BaseTwice`.

- K8-1 **The engine runs a missing role canary itself** (stage ≥ 3 only: `driver.default_canary_ok` →
  `canaryrun.ensure_role_canary`). When: at the engine start, before the loop (`driver._canary_preflight`:
  a step runs next and its class, or a class the rest of the procedure needs, has no record) and again
  before every role / leader session. Same code as `engine.py canary` (haiku / low, the repository's
  exceptions, `CANARY_TOTAL_MAX_USD` for all canaries of one engine process). FAIL → `canary-failed`
  with the reason in the stop note. A failing record whose sessions ran is never retried by the engine
  (a boundary must not be tried until it passes): a human runs `engine.py canary [--config …]`. A
  failing record without a session (cap, leftover bait) does not hold the key.
  - Any CLI version gets the same canary (a new version is a new key). There is no list of known
    versions and no local trust record any more (FC decision D, below).
  - One role canary at a time per engine home (`canary/role-canary.lock`, flock; `engine.py canary` too):
    two at once would see and remove each other's bait in the real home.
  - Cost: a `canary` log line (`data.cost_usd`), no facts.json — never Issue cost (V17).
- K8-2 **The base run of an evidence run is judged twice** (`runner._base_runs`): red or timed out → once
  more on the same base tree, `facts.run.base_rerun`; `base-red` only when both are. Not when the first
  run left the base tree dirty. The I8 base run of an ordinary `run` step stays one run.
- K8-3 **close-as-decided at a blocked stop**, stage ≥ 3, both seats, only while `state.developer_started`
  is False (set at the start of every developer attempt; absent = an earlier engine's state = no). The
  leader gets in/issue.md; `close` is a field of `leader-answer-s3` there only (`{close_reasons}`); narrowed
  by `developer-started`, `close-risk` (the committed analysis says risk high, or none can be read) and, unattended,
  `unattended-no-decision-marker`. Applied by the plan-gate code (comment → close → every unfinished
  step skipped, the blocked one too).
- Readiness E4 (#1910) **a bug Issue keeps its red reproduction** (`gxengine/history.py`, both modes —
  `defaults.BUG_GUARD_MODES`). A bug Issue = a `defaults.BUG_LABELS` label, or an analysis.md of the branch that
  recorded `type: bug`, or a procedure that already runs a repro-red template. (1) plan-gate: `plan` is narrowed
  away (`bug-without-repro-red`) when the analysis row offers no template with a repro-red run, and a leader plan
  of such a template is refused by the driver too (needs_human at plan-gate, the leader's plan as its
  recommendation). (2) `on-fail-exceeded` at a repro-red run whose last failure is `repro-not-red`: no leader
  call — stop `not-reproduced` (needs_human; rerun / close-as-decided / escalate) with the facts in the note and
  `<records>/…/<N>/not-reproduced.md`: the reproduction test, its runs, the commits on the recorded base since
  the Issue's `createdAt` that touched a related file (the files the test imports, the paths diagnosis.md /
  analysis.md / the Issue name). (3) analyze reads `in:git-history.md` (stage ≥ 3 start procedure): commits since
  the Issue on the paths it names, `git grep` / `git log -S` of its backticked tokens — engine-run git, the
  session's tools stay Read / Write.
- FC decision D (2026-11-28, the user) **no `system/init` check of role sessions.** The final check before
  the first promotion stopped every role session of another account: CLI 2.1.326 there loads one more
  builtin plugin, and the fixed per-version lists (`defaults.CLI_BUILTINS`) could not say so. Removed whole:
  the comparison of plugins · agents · tools · permissionMode · MCP servers · skills (`canary.compare_init`),
  the `init-mismatch` stop, the local CLI version trust (`canary/cli-<version>.json`), `session.init` in facts
  (an earlier engine's facts may still carry it — allowed, not read). A new CLI version, account or builtin
  plugin no longer stops anything; a new CLI version is a new canary key, so its (probe) canary runs once.
  - Kept: the srt self check and srt canary; the role canary's probes (bait in the real home, secret reads,
    forbidden writes, network, own in/ vs another attempt's in/, structured output); the launch flags
    (`render.CLAUDE_FIXED_FLAGS`: `--setting-sources ""`, `--strict-mcp-config` + an empty MCP config,
    `--disable-slash-commands`, `--permission-mode default`, `--tools`; the scrubbed environment).
  - Lost: the flags still TRY to keep the user's settings, plugins and MCP servers out, but nothing VERIFIES
    from init that they did. A CLI update that breaks one of those flags is no longer noticed by the engine.
    The canary sessions still record what init said (`sessions[].init_plugins` / `init_agents` / `init_model`).
- FC F2 (2026-11-28) **the role canary key names the account**: `<cli>:acct-<12 hex of sha256 of the CLI config dir's
  real path>:<template hash>:<class>` (`canary.account_tag`, `canaryrun.role_key(…, environ=)`; the leader brief's
  `canary_key` too). Two accounts on one machine keep one record each: a failure of one never overwrites the
  other's pass, and a run never takes another account's record. Records of the key without an account (before
  F2) are not read — the canary runs again (fail-closed). The srt canary key has no account (synthetic home).

## Fixed scenarios and the real canary (P4)

- U20 suite: `tests/test_scenario_stage1.py`. `SCENARIOS` maps every scope §5.2 id to the
  tests asserting it (`Index` fails on a missing id or a renamed test); the table is
  `stage1/p4-scenarios.md`. New end-to-end cases there: C1 through the real units, S2 quota
  wait / stop through the driver, the srt canary gate, the recorded real canary.
- `engine.py canary` (paid, by hand, once per I9 key): role canary for `work` and `judge`
  (haiku / low, batches of 40 probes, one retry session for probes without an attempt
  record, total stop `defaults.CANARY_TOTAL_MAX_USD`), then the free srt canary. Records:
  `<engine home>/canary/<key>.json` (`ok`, outcomes, sessions, unprobed, cost); evidence:
  `<engine home>/canary/runs/<stamp>-<what>/`. `--budget-probe` records the CLI's budget end.
- The role canary runs with the REAL home and CLI config dir (measured: the CLI's login
  follows HOME). Home bait is planted only as new files and removed afterwards
  (`canary.prepare_real_home`); an existing real secret file is never shown to a session
  (Bash reads go to /dev/null, Read probes of it are listed as `unprobed`).
- The driver checks the srt canary record of the repository's run template before every run
  and runs the (free) srt canary itself when the record is missing (`canaryrun.ensure_srt_canary`);
  fail → `canary-failed`. The role canary record must exist before any role session (stage 3: the engine
  runs a missing one itself — Q8).
- Measured against the real CLI 2.1.323 and fixed (fixtures re-recorded under
  `tests/fixtures/claude/canary/real-2.1.323/`, fakes changed to match):
  `--json-schema` refuses the 2020-12 `$schema` (render drops `$schema` / `$id`); init `tools`
  gains `StructuredOutput` with `--json-schema` (was in the init lists, removed with them — FC decision D);
  the budget end is `subtype error_max_budget_usd`, `terminal_reason budget_exhausted`;
  zsh reports EPERM as lower-case `operation not permitted`; the Write tool answers
  "File has not been read yet" for an existing file before the allow rules.

## The developer's toolchain environment (P5 F2)

Measured in the P5 real runs (one-man-company 687 implement 3, word_app 1964 implement 2):
the developer could not run flutter / dart in its session (the user's SDK cache is read-only,
dart analytics writes to HOME, `mktemp` needs the user temp dir), so it could neither see
red → green nor read a failure. Coordinator decision (reverses design §7.13 "exceptions for
`run` only"):

- The developer (work role) session gets what a run gets: the cache env (`{cache}` filled,
  already in P3), `run_env`, and the approved `sandbox_exceptions` rendered into its Claude
  settings with Claude Code's own keys (settings reference, CLI 2.1.323):
  `allow_local_binding` → `sandbox.network.allowLocalBinding: true`,
  `weaker_network_isolation` → `sandbox.enableWeakerNetworkIsolation: true`,
  `allow_write` → `sandbox.filesystem.allowWrite` entries ({user_tmp} resolved) + the nested
  `.git` / `.claude` deny in the sandbox AND as `Edit/Write(…)` denies; no `Edit` allow (Bash only).
  `check_role_settings` accepts these two optional keys (exactly true, only with Bash);
  `role_sandbox_as_srt` maps them 1:1 to the srt keys.
- A judge gets none of it (`template("judge", "role", exc)` refuses; `exception_flags` = {}).
- PATH / HOME stay the user's: the gate hook and git run outside the sandbox with the session
  env, so the role-writable cache never enters PATH. Instead the work frame
  (`instructions.SANDBOX_LIMITS_RULE`, "Sandbox and toolchain") and a "Repository commands"
  section (`instructions.toolchain_section`, the named commands' text + the variable names)
  tell the developer to run a tool with the command's own `export PATH=… HOME=…` prefix.
- The work-role template (I9) contains the exceptions, so the role canary key changes:
  `canaryrun.role_key(cli, class, config)` (driver lookup) = the key `engine.py canary --config
  <repo config>` records for the work class. The judge and run template hashes are unchanged.
- Unchanged guarantee: toolchain sync re-copies the SDK at every engine start and nothing in
  the cache runs outside the sandbox.

## Engine records and reset

Engine home = `$GLD_ENGINE_HOME`, default `~/.gld` (never under `/tmp/claude-<uid>`, F4):

```
<home>/records/<owner>/<repo>/repo.lock          repository lock (one engine per repository)
<home>/records/<owner>/<repo>/<N>/               state.json log.jsonl engine.log engine.rc lock
                                                 leader-decision.md resume-note.txt (detached resume only)
                                                 runs/<step>/<attempt>/  brief result facts stream stderr
                                                 settings srt.json run*.log in/ prepare-*.log
                                                 leader/<k>/  stage-2 needs_leader calls (same files, in/
                                                 has leader-input.json; plan-gate / done-gate
                                                 sessions are runs/<check step>/<attempt>/)
<home>/tmp/<owner>/<repo>/<N>/                   per-attempt temp folders, self-check/
<home>/cache/<owner>/<repo>/                     the Guild cache ({cache}) — kept between Issues
<home>/canary/<key>.json                         canary records (I9) — role (paid; key <cli>:acct-<hash of the CLI config dir>:<template>:<class>, FC F2) and srt (free)
<home>/canary/runs/<stamp>-<what>/               canary evidence (streams, stderr, prompts, items)
<home>/canary/role-canary.lock                   one role canary at a time (Q8, flock — the file stays)
<home>/records/<owner>/<repo>/<N>/mutations/<head>/   stage 4 (VB9): record.json + run logs
<home>/incidents/<slug>/                     readiness R1: incident.json + evidence/ (first occurrence, secrets removed)
<home>/records/<owner>/<repo>/sprints/<T>/       stage 4: sprint.json log.jsonl supervisor.log supervisor.rc lock
<home>/records/<owner>/<repo>/sprint.lock        stage 4: one supervisor per repository
<home>/records/<owner>/<repo>/base-green/        stage 4: base check records
<home>/init/<owner>/<repo>/                      stage 4: init draft, decisions, check
<home>/heavy-run.lock                            stage 4: one repository command at a time (flock — stays)
<home>/srt/                                      the plugin's srt install
<main checkout parent>/.gld-<repo>-<N>/         the Issue worktree, branch gld/<N>
/tmp/gx-<id>/                                    srt's own short TMPDIR (removed after each run)
```

Reset one Issue (only while no live engine holds `lock` or `repo.lock` — `engine.py status`):

1. remove `<home>/records/<owner>/<repo>/<N>/` and `<home>/tmp/<owner>/<repo>/<N>/`;
2. `git -C <main checkout> worktree remove --force <parent>/.gld-<repo>-<N>` and
   `git -C <main checkout> branch -D gld/<N>` (the remote branch / PR separately);
3. the cache and canary records stay (they belong to the repository / the boundary, not the Issue).

The validation reset tool (`design/guild/24-redesign/validation-archive/reset.py`) knows this
layout (`{GLDX}/records/{SLUG}/{N}`, `{GLDX}/tmp/{SLUG}/{N}`, `.gld-` worktrees, `gld/<N>`)
and refuses to run while the engine's lock is live.

## Changing a contract

1. One commit, subject `contract: …`, touching the frozen files together: `codes.py`, the
   schema(s), the examples in `tests/fixtures/contracts/`, the affected fixtures, and
   `test_contracts.py` if a check moves. `engine_test.sh` green.
2. A change to a **fixed core field** of `state.json` (§4.3) also ships a converter in
   `store.CONVERTERS` in the same version, or the engine stops on the old file.
3. Record it in the §"변경 기록" of the current stage's `stage<n>/interfaces.md` (stage 4 now;
   who, why, which sessions are affected) and tell those sessions before they rebase.
4. A value for a later stage never changes an earlier stage's table, schema or refusal: add a
   stage-specific table and pick it by `stage` (see the `codes` docstring).
