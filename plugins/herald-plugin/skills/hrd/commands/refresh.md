# REFRESH — update an existing article (`/hrd refresh <slug>`)

Re-runs the spine on a published article whose metrics dropped or whose facts aged. Plan §5
(M5). The work id is `r-<slug>-<YYYYMMDD>`; the branch is `herald/r-<slug>-<YYYYMMDD>--<slug>`.

1. `HRD lock acquire --cmd refresh`; base clean; `HRD sync`.
2. The article must be in `published.json` (Herald or external). Gather why: Search Console
   data if connected (`.claude/herald/secrets/` present — see `monitoring.md`), else the
   human's reason.
3. Slugs outside Herald's format (lowercase ASCII, single hyphens) cannot be refreshed in 1.0 —
   say so and stop. Add the refresh topic: write `[{"id": "r-<slug>-<date>", "title": "<current title>",
   "category": "<cat>", "angle": "refresh: <reason>", "refresh_of": "<slug>", "slug": "<slug>"}]`
   to `.claude/herald/memory/refresh.json`, `HRD topics add --file …`, commit (`--cmd refresh`),
   push, then **release the lock** (`HRD lock release --cmd refresh --token <t>`; `write` acquires its own).
4. Run `write.md` for that id with these differences:
   - brief is a **refresh brief**: what is stale, what to keep (URL/slug fixed), new keywords;
     the cannibalization check **excludes the article itself**; `HRD branch --topic <id> --slug <slug>`.
   - draft starts from the current body (read it from the content directory).
5. `ship` publishes it like any article; it becomes the slug's reference topic (latest merged
   Herald PR wins).
