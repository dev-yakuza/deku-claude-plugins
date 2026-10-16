# REFRESH — update an existing article (`/hrd refresh <slug> [--attended] [--direction <id>]`)

Re-runs the spine on a published article whose metrics dropped or whose facts aged. Plan §5
(M5). The work id is `r-<slug>-<YYYYMMDD>` (a second one the same day: `-2`, `-3`, …); the branch
is `herald/<id>--<slug>`.

1. `HRD lock acquire --cmd refresh`; base clean; `HRD sync`.
2. The article must be in `published.json` (Herald or external). Gather why: Search Console
   data if connected (`.claude/herald/secrets/` present — see `monitoring.md`), else the
   human's reason.
3. Slugs outside Herald's format (lowercase ASCII, single hyphens) cannot be refreshed in 1.0 —
   say so and stop. Add the refresh topic: write `[{"id": "r-<slug>-<date>", "title": "<current title>",
   "category": "<cat>", "angle": "refresh: <reason>", "refresh_of": "<slug>", "slug": "<slug>"}]`
   (plus `"direction": ".claude/herald/memory/directions/<id>.diff"` with `--direction <id>` — a
   human's change saved when ship declined or restored it; the file must exist)
   to `.claude/herald/memory/refresh.json`, `HRD topics add --file …` (with translations it
   refuses while another topic on the slug is in progress — finish or close that one first),
   commit (`--cmd refresh`),
   push, then **release the lock** (`HRD lock release --cmd refresh --token <t>`; `write` acquires its own).
4. Run `write.md` for that id (in-session auto, or `--attended` if `refresh` got it) with these
   differences:
   - brief is a **refresh brief**: what is stale, what to keep (URL/slug fixed), new keywords;
     the cannibalization check **excludes the article itself**; `HRD branch --topic <id> --slug <slug>`.
   - draft starts from the current body (read it from the content directory) and applies the
     topic's `direction`, if any.
   - with translations: `HRD begin` gives the topic every translation language the article has
     on base; they are all made again from the refreshed source (translation stage), so the
     bundle stays one version.
5. `ship` publishes it like any article; it becomes the slug's reference topic (latest merged
   Herald PR wins).
