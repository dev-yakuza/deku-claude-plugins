# RULE

**Project-specific SDD rule capture.** Saves an implementation insight to `.claude/sdd/rules/<stage>/<topic>.md` and updates the stage index `.claude/sdd/rules/<stage>.md`.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call. See `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

## Input

| Param | Description |
|-------|-------------|
| `$1` | Stage: `implement`, `design`, `test` (optional — prompted if missing) |
| `$2` | Rule content: the insight to save (optional — prompted if missing) |

## Steps

### Step 1 — Resolve stage

If `$1` is provided and is one of `implement`, `design`, `test` → use it as `<stage>`.

Otherwise ask:
> 어떤 스테이지의 규칙인가요? (`implement` / `design` / `test`)

### Step 2 — Resolve rule content

If `$2` is provided → use it as the rule content.

Otherwise ask:
> 저장할 규칙 내용을 입력해 주세요.

### Step 3 — Derive topic slug

Derive a short `snake_case` topic slug from the most prominent technical noun(s) in the rule content (e.g., `db_migration`, `error_state`, `form_screen`, `schema_design`).

If unable to determine with confidence, ask:
> 이 규칙의 주제 슬러그를 입력해 주세요 (예: `db_migration`):

### Step 4 — Check directory structure

```bash
ls .claude/sdd/rules
```

If the directory does not exist, note that it needs to be created (the Write tool creates parent directories implicitly).

### Step 5 — Write rule file

Path: `.claude/sdd/rules/<stage>/<topic>.md`

**If the file already exists**: Read it first, then append the new rule under the existing content (add a `---` separator before the new entry).

**If the file is new**: Write with this template:

```markdown
# <Topic Title>

## 규칙

- <rule content>

## 배경

<one or two sentences explaining why this rule exists — the incident or failure that motivated it>

## 적용 예시

<brief code snippet or concrete example if applicable; omit if not helpful>
```

Fill in `<Topic Title>` as a readable title (e.g., "DB 마이그레이션 원자성"), `<rule content>` from `$2`, and `<배경>` from any context available in the current session (recent bug discussion, review findings, etc.).

### Step 6 — Update index

Path: `.claude/sdd/rules/<stage>.md`

**If the index exists**: Read it. Check whether the topic row already appears in the table.
- **Row absent** → append a new row.
- **Row present** → update the trigger keywords if the new rule adds new ones; otherwise leave unchanged.

**If the index does not exist**: Write with this template:

```markdown
# <Stage> Stage 규칙 인덱스

SDD `<stage>` 스테이지 preflight(Item 5)가 이 파일을 읽어 관련 규칙 파일을 선택 로딩합니다.
`/sdd rule <stage> "<insight>"` 명령으로 규칙을 추가할 수 있습니다.

| 파일 | 적용 범위 | 트리거 키워드 |
|------|----------|--------------|
| [<topic>.md](<stage>/<topic>.md) | <scope one-liner> | <comma-separated keywords> |
```

Fill in `<scope one-liner>` and `<comma-separated keywords>` from the rule content. Keywords should be concrete: class names, SQL keywords, framework terms — not abstract nouns.

### Step 7 — Confirm

Report:

```
규칙이 저장되었습니다.
  파일: .claude/sdd/rules/<stage>/<topic>.md
  인덱스: .claude/sdd/rules/<stage>.md

다음 /sdd <stage> 실행 시 preflight Item 5가 이 규칙을 자동으로 참조합니다.
```
