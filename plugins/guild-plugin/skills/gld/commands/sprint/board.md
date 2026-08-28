# SPRINT BOARD (set up / inspect / reset the GitHub Projects kanban)

**Optional infrastructure.** Every other `sprint` subcommand works without a board
(03-sprint-board.md D2) — this one only exists so `plan` and the `run` supervisor have
somewhere to project onto. The board is a **view**: labels and the tracking Issue stay the
source of truth, and moving a card changes nothing about what Guild does (D1).

`$1` = *(empty)* | `--setup` | `--reset` · `$2…` = that form's own flags. ⚠ **`--project` is
retired and lives in `$2`, so it is matched on the whole argument list, not on `$1`** — see
Phase 0 step 0.

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State/labels: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K).
> Machine tokens (column tokens, reason tokens, `state:` values) stay ASCII.

---

## Routing

| `$1 $2…` | Action |
|---|---|
| anything containing `--project` | ⚠ **retired.** Say so and stop — checked **first**, see Phase 0 step 0 |
| *(empty)* | **status** — Phase S. Reads the board; its one write is `column_by_verified` (step 2) |
| `--setup` | **create** — Phase 1–7. Idempotent: re-running verifies instead of duplicating |
| `--setup --project <n>` | the retired form; the first row catches it |
| `--reset` | **clear Guild's data fields** on every card that has one — the rollback step (§12) |
| anything else | report the unknown form and print this table |

---

## Phase 0 — Preflight

0. **`--project` given anywhere in `$1 $2…`?** Return
   `FAIL: --project is no longer supported — Guild always creates its own project` plus the line
   below, and **stop — before any routing**. ⚠ This is step **0** because `$1` is `--setup` in
   that form: a model matching the routing table on `$1` alone hits the `--setup` row first and
   creates a project, which is the swallow this exists to prevent.

   ```
   `--project` 는 없어졌습니다. 기존 프로젝트의 단일선택 필드는 거의 항상 내장 `Status` 하나이고,
   `Status` 에 `Done` 을 쓰면 **이슈가 닫힙니다**(실측) — 그래서 그 경로는 결국 전용 필드를 새로
   만드는 것으로 끝났습니다. `/gld sprint board --setup` 은 스프린트용 프로젝트를 새로 만듭니다.
   ```

1. **Guild initialized?** `ls .claude/guild/config.json` — absent → `FAIL: Guild not initialized (run /gld init first)`.
2. **Resolve owner/repo** once (`_handoff.md` Section F).
3. **Read `config.sprint.board`.** `null` and `$1` is not `--setup` → `OK: no board configured`
   plus one line telling the human `/gld sprint board --setup` exists. ⚠ This is **`OK`, not
   `FAIL`** — the board is opt-in, and a repo that never wants one is not in an error state.

### Phase 0a — the scope diagnosis (three branches, D11)

`gh project` needs the `project` scope, which `gh auth login` does not grant by default.
Run `gh auth status` and branch on what it says. ⚠ **All three branches are needed.** With
only "you need the scope", a user who *already has it on another account* is told to get it
again, and no number of retries fixes anything — that is a measured situation, not a
hypothetical (03-sprint-board.md §1.1a).

| What `gh auth status` shows | Say |
|---|---|
| the active token has `project` | nothing — proceed |
| the active token does not, but **another account in the keyring does** | *"활성 계정 `<A>`의 토큰에 `project` 스코프가 없습니다. keyring의 `<B>`에는 있습니다. `<A>`에 `gh auth refresh -s project`를 실행하시거나, `GH_TOKEN`이 설정돼 있다면 해제하시고 `<B>`로 전환해 주십시오."* ⚠ Do **not** assert that `GH_TOKEN` is the cause: `gh auth status` produces this same shape when the active account came from the keyring, so naming `GH_TOKEN` as the reason can be simply false (verified on a three-account keyring) |
| no account has it | *"`gh auth refresh -s project`를 실행하고 다시 오십시오."* ⚠ a browser opens, so Guild cannot do this for the human |

**In the first row's case, proceed — nothing is printed and nothing fails.** In the other two,
`FAIL: project scope missing — <the line above>` and stop.

⚠ **Record which account passed** in `config.sprint.board.verified_as` — **on the `--setup`
path only** (Phase 6 writes it). The supervisor compares against it at run start, because it
inherits the launching shell's environment and `GH_TOKEN` silently overrides the keyring
account.

⚠ **The bare status path must NOT write it.** Phase 0 runs for every route, and an unqualified
"record it" means a human who runs `sprint board` to diagnose a dead board overwrites
`verified_as` with the account that is currently active — after which the supervisor's
comparison can never fire again and `board_account_mismatch`, the one explanation for a board
where everything failed, is gone for good. On the status path: compare and report, nothing
else.

---

## Phase S — status (bare `sprint board`)

Read-only. Four things, in this order:

1. **Board line.** `board: #<n> <url>` · the column field in use · freshness.

   ⚠ **Freshness is `board_last_write` from the run marker's ledger, and nothing else.** Use the
   same four-row table `daily` uses (`daily.md` step 5), including the two rules that make it
   honest: the failure line **replaces** the freshness clause, and a missing `board_last_write`
   prints `투영 기록 없음` rather than a figure.

   ⚠ **Never print `config.sprint.board.last_projected` as "마지막 투영".** It is written by
   `plan --create` and by nothing else, so it measures when the sprint was seeded, not when a
   card last moved. Label it `마지막 시딩(plan)` if you show it at all. And never derive
   freshness from `heartbeat`: that is written regardless of what the board did, so it says the
   supervisor is alive, not that the cards are current.

   ⚠ **The tracker may be closed.** After `retro` there is no open sprint, so fall back to the
   **most recently closed** `guild:sprint` tracker's marker rather than dropping the counters —
   otherwise the one window into "did this run's projections work" shuts exactly when the human
   comes back to look.

   ⚠ **Two calls are needed to have the marker at all**, and neither existed here: find the
   open tracker, then read its comments. The marker is a **comment**, not the issue body.

   ```bash
   gh issue list --label guild:sprint --state open --limit 20 --json number,title
   ```
   ```bash
   gh api repos/<owner>/<repo>/issues/<tracker>/comments --paginate --jq '.[].body'
   ```

   Take the **last** `<!-- guild:sprint:run -->` block. No open sprint, or no marker → skip
   straight to `last_projected` and say `투영 기록 없음` when that is null too. Do not print a
   freshness figure sourced from anything that moves independently of the board.
2. **`Column by` re-check** (D14). One `gh api graphql` read.

   ⚠ **Root on the owner, never on `viewer`.** Phase 1 requires an **org** project for an org
   repo (D10), and `viewer.projectV2(number:)` resolves only the authenticated user's own
   projects — on an org board it returns `null` or, worse, a *different* project that happens
   to share the number. Read `config.sprint.board.owner_type` (recorded by `--setup`) and pick
   the root: `organization(login:$o)` for `org`, `user(login:$o)` for `user`.

   `owner_type: "org"`:

   ```bash
   gh api graphql -F o=<owner> -F n=<number> -f query='
     query($o:String!,$n:Int!){ organization(login:$o){ projectV2(number:$n){ views(first:20){ nodes{
       id name layout
       verticalGroupByFields(first:5){ nodes{ ... on ProjectV2SingleSelectField{ name } } }
     }}}}}'
   ```

   `owner_type: "user"` — **same query, `user(login:$o)` instead of `organization(login:$o)`**:

   ```bash
   gh api graphql -F o=<owner> -F n=<number> -f query='
     query($o:String!,$n:Int!){ user(login:$o){ projectV2(number:$n){ views(first:20){ nodes{
       id name layout
       verticalGroupByFields(first:5){ nodes{ ... on ProjectV2SingleSelectField{ name } } }
     }}}}}'
   ```

   ⚠ **Both forms are here because one example is what actually gets copied.** With only the
   org form on the page, a personal repo gets `organization(login:"someuser")`, which returns
   `NOT_FOUND` and a non-zero exit — Phase S step 2 dies, and since Phase 3 borrows this read
   for its view id, `--setup` on a personal repo could never run the layout mutation and the
   project stayed a table forever.

   ⚠ **`id` is selected on purpose** — Phase 3's layout mutation needs a view id and this is
   the only read that produces one.

   ⚠ **Which view?** Take the **first** node with `layout: BOARD_LAYOUT`; if none is a board,
   take the first node. A project can hold many views and Guild owns none of them — it reports
   on the one the human is most likely looking at, and says which by name.

   ⚠ **`verticalGroupByFields`, not `groupByFields`.** The former is the UI's **`Column by`**
   — the board's columns. The latter is `Swimlanes`, and it reads `none` on real boards.
   Measured on two live projects; getting this backwards is why an earlier draft told people
   to click a menu that does not exist.

   Not `<column_field>` → print the click path and nothing else changes:

   ```
   보드를 칸반으로 보시려면 컬럼 기준을 바꿔 주십시오 (1회, 이 뷰에 저장됩니다):
     화면 오른쪽 위 ⚙ View → Column by → <column_field>
   안 하셔도 투영은 정상 동작합니다 — 카드 값은 맞고 컬럼만 Status 로 갈립니다.
   ```

   ⚠ **Write the outcome to `config.sprint.board.column_by_verified`** — `true` when the check
   passed, `false` when it did not. That key is the only way any other command can tell the human
   their columns are not split by Guild's field: `daily` appends
   `· 컬럼 기준 미확인 — /gld sprint board` while it is not `true`. Without it the advice lives
   only in a command nobody is routed to, and the realistic outcome is a human looking at one
   undifferentiated pile of 40 cards while `daily` says the board is fine.

   ⚠ **The re-check belongs here, not only in `--setup`.** A view created by `--setup` is
   *always* auto-assigned `Status` (measured), so the setup-time answer is always "not set" —
   and if the human does not click right then, one-shot advice never repeats itself.
3. **Does the board still match config?** One `gh project field-list <n> --owner <owner>
   --limit 100 --format json` read (⚠ the default limit is **30**; compare against
   `totalCount` and say so rather than reporting a phantom mismatch). Compare, by name:

   - `config.sprint.board.column_field` against the fields that exist;
   - every display name in `config.sprint.board.columns` against that field's options;
   - the four `config.sprint.board.fields` names against the fields that exist.

   A mismatch is **the** diagnosis for a board that stopped working, and without this step the
   human gets `투영 실패 34건` with no cause. Renaming a column in the GitHub UI keeps the card
   values (measured B·J) but makes every supervisor write fail, and it makes `plan` refuse
   those cards as `unknown`. Say which name and which side is stale:

   ```
   ⚠ 보드와 config 가 어긋났습니다:
     컬럼 `In review` 가 보드에 없습니다 (보드에는 `리뷰 중` 이 있습니다)
     → config.sprint.board.columns.in_review 를 고치시거나 보드에서 이름을 되돌려 주십시오
   ```

   ⚠ **Guild does not fix it by itself.** Rewriting config would silently adopt whatever the
   human typed; rewriting the board is the `updateProjectV2Field` whole-list replacement that
   deletes options and wipes card values (measured C, D13). Report and stop — both remedies
   are one line, and the human knows which one they meant.

3b. **Is the running supervisor projecting somewhere else?** When a run is in flight, read
   `.claude/guild/.gld-sprint-<tracker>.board` and compare its `number`/`field` against config.
   They diverge whenever the board was set up **after** the run launched — the
   supervisor freezes its board config at launch and never re-reads it. Nothing else compares
   these two, so the counters below were produced against one project while this command reports
   the other's URL:

   ```
   ⚠ 지금 도는 run 은 프로젝트 #5 에 투영합니다 (config 는 #7). 다음 run 부터 #7 이 됩니다.
   ```

4. **Board counters from the run marker**, when a sprint is open: `board_fails` ·
   `board_bugs` · `board_account_mismatch` · `board_disabled_after` · `board_reason_disabled`
   (the reason field became unwritable and the supervisor kept projecting columns without it). ⚠ Zero and "every write failed" must not look
   the same (D9); `board_bugs` is a Guild bug, not a scope problem, and is reported apart.

---

## Phase 1–7 — `--setup`

Idempotent. Each phase verifies before it creates.

**One path: 1 → 2 → 3 → 4 → 5 → 6 → 7.** ⚠ **There is no adopt path.** An earlier version had
`--setup --project <n>` try to reuse a single-select field the human already had, with vocabulary
matching and a confirmation prompt. It is gone, and a measurement is why: the only single-select
most existing projects have is the built-in `Status`, and writing `Done` to `Status` **closes the
underlying issue** (Phase 4). So that path spent seventy lines matching vocabulary in order to
reach Phase 4's answer — "no usable field, creating `Guild board`" — while producing a second
config shape, a three-way phase reordering and a dead `auto_done` key. **Guild creates its own
project and its own field. Always.**

⚠ **On first setup, `owner_type` comes from Phase 1's own `gh repo view`, not from config.**
Phase 3 borrows Phase S's GraphQL read for a view id, and that read is written in terms of
`config.sprint.board.owner_type` — a key Phase 6 has not written yet. Use the value Phase 1
already has in hand.

### 1. Owner comes from the repo, never `@me` (D10)

`gh repo view --json owner` — an org repo gets an **org** project, a personal repo a user
project. ⚠ **Record which in `config.sprint.board.owner_type`** (`"org"` | `"user"`): Phase S's
GraphQL read has to root on the right one and cannot re-derive it without another call. ⚠ **No `--owner @me` fallback.** Measured: a user project cannot be linked to an
org repo (`has different owner from '@me'`), and `item-edit --url` then fails on issues that
`item-list` happily shows — the projection would need those node IDs resolved per **call** rather than once per run — and
that is the shape Guild now uses deliberately, because a name-addressed write costs 104 GraphQL
points against the node-ID form's 1 (measured). What makes a cross-owner project unusable is
that `item-edit --url` fails there at all, not the id resolution.
No permission to create in the org → stop:

*"`<org>`에 프로젝트를 만들 권한이 없습니다. 조직 관리자에게 요청하시거나, 이 레포에서는 보드를
쓰지 않으십시오 — `sprint`는 보드 없이 정상 동작합니다."*

### 2. Find or create the project

`config.sprint.board.number` present → verify it exists and skip to 3. Failing that, list the owner's projects and match on title `<repo> sprints`:

```bash
gh project list --owner <owner> --limit 200 --format json
```

⚠ **`--limit` is mandatory here.** The default is **30** (measured). In an org with more than
30 projects the existing sprint project is invisible, Phase 2 falls through to `create`, and
the human gets the second unremovable project this phase spends a paragraph warning about.

⚠ **Do NOT compare `len(projects)` against `totalCount` here.** Measured: `project list --limit
100` on an account with 3 projects (1 open, 2 closed) returns **1 project against
`totalCount: 3`** — closed projects are counted and then filtered out. A truncation check on
that comparison reports truncation **permanently and falsely**, so `--setup` would refuse to
run forever. (`item-list` and `field-list` are different: their `totalCount` is the real total
and the comparison is valid there.) Judge truncation by `len(projects) == limit` instead, and
only then stop with `FAIL: project list truncated — cannot prove the sprint project is absent`.

Create only when the list is complete and holds no match:

```
gh project create --owner <owner> --title "<repo> sprints" --format json
gh project link <n> --owner <owner> -R <owner>/<repo>
```

⚠ `create` makes it **private** (measured `"public": false`) — that is what §8.1's INV5
argument rests on.

### 3. Make the board a board

A new project's default view is `TABLE_LAYOUT` (measured W). Layout **is** writable.

⚠ **Get `<viewId>` first** — run Phase S's read (step 2 above) against the project you just
created and take the target view's `id`. Nothing else in this file produces one,
and the mutation cannot be written without it.

```bash
gh api graphql -F v=<viewId> -f query='
  mutation($v:ID!){ updateProjectV2View(input:{viewId:$v, layout:BOARD_LAYOUT}){
    projectV2View{ layout } } }'
```

Already `BOARD_LAYOUT` → skip the mutation and say nothing; this phase is idempotent like the
rest.

⚠ **`Column by` is not writable.** `ProjectV2ViewConfigurationInput` accepts only
`visibleFieldIds`; `groupBy` is rejected (`argumentNotAccepted`), and a new board view is
always auto-assigned `Status`, which cannot be deleted (`Only custom fields can be deleted`).
That is why the one human click exists and why Phase S re-checks it forever.

### 4. Create the column field

```
gh project field-create <n> --owner <owner> --name "Guild board" --data-type SINGLE_SELECT \
  --single-select-options "Backlog,Ready,In progress,Blocked,In review,Done"
```

⚠ **Measured**: this succeeds, the CSV order becomes the column order, and option names
with spaces (`In progress`, `In review`) survive intact.

⚠ **Six options, seven columns.** `Issues` is deliberately **not** an option — it is the
**null bucket** (D16). A card with no value for this field lands there, which is exactly
what "`plan` has not judged this, or judged it as needing refinement" should look like.
Creating an `Issues` option would give you *two* empty-ish buckets instead of one.
⚠ The human most likely sees that column labelled **`No Guild board`** — the built-in `Status`
field's null bucket was observed as `No Status` (screenshot), but **a custom field's null-bucket
label has not been verified** and the API neither reads nor writes it. Say so if asked rather
than asserting it: naming UI text nobody has seen is the `Group by` mistake (§14.1).

⚠ **Guild does not touch the built-in `Status` field.** It stays the human's. The likely
consequence: GitHub's built-in *PR merged → Done* workflow **appears to be** attached to
`Status`, so it would not fire for a custom field — the supervisor's own P5/P6 do that job
regardless, so nothing depends on this being true. ⚠ **Unmeasured**: the workflow's name and
`enabled` flag are readable, its target field is not (§1.2). Do not tell the human it will or
will not fire.

### 5. Create the four data fields

`field-list <n> --owner <owner> --limit 100 --format json` first, create only what is missing.

⚠ **`--limit 100`, and compare `len(fields)` against `totalCount`.** The default is **30**
(measured), and this read decides what to CREATE — a short read makes Phase 5 try to create a
field that already exists. It also has to match what the two writers use (`board_write.py`'s
`resolve_ids` and the supervisor's `board_resolve`, both 100): the supervisor treats a short
field read as fatal and turns the board off, so a diagnostic that reads further than the writer
reports a board healthy that the writer cannot use.

⚠ **Never `field-delete`** (INV4).

```bash
gh project field-create <n> --owner <owner> --name "Order" --data-type TEXT
```

⚠ **All four are `TEXT`.** `board_write.py` writes them with `--text` (the node-ID form has no
`--value`), so a field created as `NUMBER` or `DATE` rejects every write — counted in `failed`,
and diagnosed by step 3's mismatch check, but never written. `Order` and `Sprint` look numeric;
they are not.

| Field | Type | Why this one and not a label |
|---|---|---|
| `Order` | NUMBER | **Sorting gives the merge order.** Stacked PRs must merge bottom-up and GitHub does not enforce it. Labels filter; they do not sort. The strongest of the four |
| `Depends on` | TEXT | This PR's base is not the default branch — its diff is a delta. That fact lives only in the tracking Issue **body**, which cards do not show |
| `Needs human` | TEXT | A **classification token** — 15 of them, never prose: `needs-human` · `failed:<class>` (8) · `split-children` · `interrupted` · `pr-unknown` (the PR list could not be read, so *"there is a PR to review"* is not something we know) · `dep-unresolved` (the run ended with this member's dependency still not landed, so it will not move again by itself) · `branch-ambiguous` · `base-unresolved` (the other two end-of-run block classes — they are **not** dependency waits and their repairs differ, so they do not share `dep-unresolved`'s token). `Blocked` says *"your turn"*; this says which turn |
| `Sprint` | NUMBER | Boards are not recreated per sprint, so cards accumulate. This is how a human filters to one sprint |

### 6. Record the config

⚠ Write it with the Read/Write tools, never with `jq -i` (`config.md`'s rule): this key joins
an existing `config.json`, it does not replace it.

```json
"board": {
  "owner": "<owner>", "owner_type": "<org|user>",
  "number": 7, "url": "https://github.com/...",
  "column_field": "Guild board",
  "columns": {"backlog":"Backlog","ready":"Ready","in_progress":"In progress",
              "blocked":"Blocked","in_review":"In review","done":"Done"},
  "fields": {"order":"Order","depends_on":"Depends on",
             "needs_human":"Needs human","sprint":"Sprint"},
  "owned": ["Guild board","Order","Depends on","Needs human","Sprint"],
  "column_by_verified": false,
  "verified_as": "<account from Phase 0a>",
  "last_projected": null
}
```

⚠ **`owned` is what makes D1 a rule rather than an intention.** Projection code writes only
names on this list. Without it, *"Guild erased my edit"* can happen at any time and there is
no way to find out why.
⚠ **`columns` is token → display name** (D7). A human renaming a column in the UI is a
one-line config change, and no code compares display strings.

### 7. Tell the human what is true

Say the click path from Phase S if `Column by` is not set yet, then all five of these. ⚠ An
earlier version capped this at *"two lines, at most"* and the cap silently dropped the two
that state a **cost** — which are the two a human cannot infer:

```
새 이슈는 `sprint plan` 을 확정하실 때 보드에 올라옵니다.
⚠ 마지막으로 확정하신 뒤에 만드신 이슈는 다음 `sprint plan` 까지 보드에 보이지 않습니다.
(제안만 보시는 단계에서는 보드가 바뀌지 않습니다 — `--create` 로 확정하실 때 올라옵니다.)
(스프린트가 도는 동안 카드는 Guild 가 알아서 옮깁니다.)
GitHub 의 자동 추가 설정을 켜두시면 즉시 올라오지만, Guild 가 그것을 켜거나 확인할 수는 없습니다.
`Order` 로 정렬하실 때는 `Sprint` = #<tracker> 로 먼저 걸러 주십시오 — 지난 스프린트의 1..N 이 섞입니다.
카드를 직접 끌어 옮기셔도 Guild 의 동작은 바뀌지 않고, `Backlog`·`Ready` 로 옮기신 것은
다음 `sprint plan` 이 다시 판정합니다 (그 두 칸은 `plan` 소유입니다).
```

⚠ **The `Sprint` filter line is not optional.** `Order` is the field this design calls the most
valuable of the four, and it is written fresh as `1..N` every sprint while nothing clears the old
values and nothing archives cards. So `In review` — the one column where merge order matters —
accumulates last sprint's frozen `Order 1..7` beside this sprint's live `Order 1..7`, and sorting
it yields `1,1,2,2,3,3…`. `Sprint` is the only thing standing between `Order` and noise, and a
human who is not told to filter by it will not think to.

⚠ **Is a supervisor running right now?** Read the open tracker's `<!-- guild:sprint:run -->`
marker (Phase S step 1 already fetches it). `state: running` / `installing-deps` /
`rate-limited-*` with a live pid → **replace the fourth line** with:

```
⚠ #<tracker> 의 감독자가 이미 돌고 있습니다 — 이 run 은 이 보드에 투영하지 않습니다.
   카드를 채우려면 run 이 끝난 뒤 `/gld sprint run` 을 다시 부르시거나, 지금 중단하고 다시 시작하십시오.
```

The supervisor reads its board config **once, at launch**, from
`.claude/guild/.gld-sprint-<tracker>.board`. A run launched while `config.sprint.board` was
`null` has no such file, so every projection helper short-circuits for the whole run — and
`plan` will not run again for this sprint, so the board stays **empty**. Promising that cards
will move is the worst kind of wrong here: waiting does not help, and re-running `--setup` does
not help either.

⚠ **No sprint open → drop the fourth line entirely.** It is a claim about a future run.

⚠ **A sprint is OPEN but the run has not started** — the more likely case, and it needs its own
line. Columns will move (the supervisor adds each card on first touch), but `Order`, `Depends on`
and `Sprint` are written **only** by `plan`'s seeding, and `plan` will not run again for this
sprint. So the board runs the whole sprint with an empty `Order` — the field this design calls
the strongest of the four — and nothing else would say so:

```
⚠ 이미 열린 스프린트 #<n> 의 멤버는 컬럼만 올라갑니다 — `Order`·`Depends on`·`Sprint` 는
   `sprint plan --create` 가 쓰므로 이번 스프린트에는 비어 있습니다. 머지 순서 정렬은
   다음 스프린트부터 동작합니다.
```

⚠ **Do not name a UI menu for the auto-add setting.** Only `deleteProjectV2Workflow` exists —
Guild cannot create, configure or even read what a workflow does — and `Auto-add to project`
was **not present on either measured project**, including one with 630 cards. Naming a path
we have not seen is the mistake §14.1 records.

---

## `--reset` — the rollback step

Clears Guild's **data** fields. Order matters; this is destructive.

⚠ **Run this BEFORE removing the board from config.** `--reset` needs `owner`, `number` and the
four field names, all of which live in `config.sprint.board` — set that to `null` first and this
command returns `OK: no board configured` (Phase 0) and leaves every value on the board. The
rollback order is: `--reset`, then `config.sprint.board = null`.

1. `gh project item-list <n> --owner <owner> --format json --limit 500` and **compare
   `len(items)` against `totalCount`** (the response carries the real total, so a short read
   is detectable). Different → raise the limit and read again; still different → stop with
   `FAIL: could not read the board in full — refusing to clear part of it`.
2. **Filter to this repo's real issues first, then** target only items that have a value in at
   least one of the four.

   - Drop every item whose `.content.repository` is not `<owner>/<repo>`. A real board carries
     issues from several repos (measured on a 630-card project). `board_write.py` addresses items
     by URL built from `repo` + issue number, so `other/repo#120` in the target list clears the
     four fields on **`our/repo#120`** — an issue that was never selected, and one that may hold
     the hand-entered `Order` the ⚠ below exists to protect.
   - Drop every item with no `.content.number` — those are **drafts**. Passing one through
     produces `{"issue": null}`, which is `exit 64`: no writes, no summary line, and a rollback
     that silently did nothing.
   - Count **after** filtering. Step 3 shows this number to the human for approval, so a count
     that includes foreign and draft items describes something other than what gets touched.

   ⚠ The human may have put values in `Order` by hand on a card Guild also touches, and §7.1a
   retracted `plan`'s cleanup for exactly this reason.
3. **Show the count and ask.** Declined → `OK: reset — 취소됨` (which must be
   distinguishable from *"0 items"*).
4. **Clear the four data fields through `board_write.py` — one Bash call.**

   ```bash
   python3 <<SKILL_DIR>>/commands/atoms/board_write.py --input <path>
   ```

   Input: the same six required keys as `plan` (`number`, `owner`, `repo`, `field`, `columns`,
   `writes`) plus `"owned"` (verbatim from config — the script refuses any field not on it),
   `"guard": false` and **`"read": true`**, with one `writes` entry per target item:

   ⚠ **`read: true`, not `false`.** The guards stay off per entry, so nothing about the refusal
   logic changes — but `read: false` means the script has no item ids and pays one `item-add`
   **project mutation per target**, on a board it is about to clear. Step 1 already ran
   `item-list` and had those ids; throwing them away cost 47 extra mutations on this file's own
   47-card example.

   ```json
   {"issue": 120, "guard": false,
    "clear": ["<fields.order>","<fields.depends_on>","<fields.needs_human>","<fields.sprint>"]}
   ```

   ⚠ **Take the four names from `config.sprint.board.fields`, never from this file.** After a
   UI rename, hardcoded names make every clear fail — and this step used to print
   `OK: reset — <n>개 항목의 필드를 비웠습니다` regardless, so the human was told the rollback
   succeeded when nothing was cleared.

   ⚠ **Bind the return's `<wrote>` to `board_write.py`'s `wrote=`, never to step 3's approved
   count.** Those two differ exactly when something failed — the case this line exists to
   report. `failed > 0` → `OK: reset — <wrote>/<targets>개 항목 · 실패한 gh 호출 <failed>건 —
   다시 실행하십시오`. Naming the retry matters: the clear is idempotent, so re-running really
   does finish the job. ⚠ `failed` counts **gh calls**, up to four per item, so it is not an item
   count; and `wrote` is per-item-**any**-success, so even `wrote == targets` permits some of the
   four fields still holding values.

   ⚠ **Why the script and not `item-edit` directly**: `_bash_rules.md` forbids loops, `&&` and
   `;` in a Bash *tool* call, so "one `item-edit --clear` per field per item" is 4×N tool calls
   — **188 for a 47-card board**. That arithmetic is the entire reason `board_write.py` exists
   (`board_write.py:4-10`); `--reset` was the one caller that still ignored it. No `column` key
   in these entries, so the column field is never touched — see the next paragraph.

⚠ **`Guild board` is NOT cleared.** Clearing it would move every card into the null bucket,
i.e. `Issues` — so a rollback would actively assert *"these 47 issues all need refinement"*.
The one column the human writes ideas into must not be filled with a sprint's history.
⚠ **No `item-archive`, no `field-delete`, no `project delete`** (INV4). Removing cards is the
human's job in the UI.
⚠ **Honest boundary** (INV3): after `--reset` every card still sits in whatever column it was
in. That is not recoverable through any Guild path — the board is a second irreversible
surface, on the far side of the network rather than the gitignore line.

---

## Hard rules

- **Never write a field that is not in `config.sprint.board.owned`.** `Status`, `Assignees`,
  `Labels`, `Priority`, `Size` and anything else the human adds stay theirs.
- **Never read a card value to decide a column.** The two reads in this design (`--reset`
  here, `plan`'s overwrite guard) answer *"what must I not touch"* — never *"what state is
  this issue in"*. That is the working edge of D1.
- **`OK`, not `FAIL`, when no board is configured.** Opt-in means a repo without one is fine.
- **GraphQL appears in exactly two places** — Phase 3 (the layout mutation) and Phase S (the
`Column by` read, which Phase 3 also borrows for the view id). Nowhere else.

## Return

`OK: board #<n> ready` · `OK: no board configured` ·
`OK: reset — <wrote>/<targets>개 항목의 필드를 비웠습니다` · `OK: reset — 취소됨` ·
`FAIL: --project is no longer supported — Guild always creates its own project` (Phase 0 step 0) ·
`FAIL: project scope missing — <the Phase 0a line>` ·
`FAIL: could not read the board in full — refusing to clear part of it` ·
`FAIL: project list truncated — cannot prove the sprint project is absent`.
**The bare status route has its own tokens.** ⚠ `OK: board #<n> ready` belongs to `--setup`
**only**. With no status token the model reaches for it, and then signs off *"ready"* directly
under the mismatch block this file calls *"the diagnosis for a board that stopped working"* — in
a skimmed or scripted context the last line is the verdict.

- `OK: board #<n> — 정상` — no mismatch, `Column by` set, counters clean.
- `NEEDS_HUMAN: board #<n> — config 와 어긋난 이름 <k>건` — step 3 found a divergence.
- `NEEDS_HUMAN: board #<n> — Column by 미설정` — step 2's one click has not been done.
- `NEEDS_HUMAN: board #<n> — 투영 실패 <n>건` — step 4 found failures.
- `FAIL: board #<n> not found for <owner>` — the project in config no longer exists (the GraphQL
  read returns `null`). Say that, rather than reporting an empty board.

⚠ Not a spine token: this file never returns `OK ADVANCE` or `OK PAUSE` (`_handoff.md`
Section D).
