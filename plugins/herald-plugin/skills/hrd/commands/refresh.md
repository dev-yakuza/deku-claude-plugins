# REFRESH — update an existing article (`/hrd refresh <slug> [--attended] [--ship] [--direction <id>] [--force-update] [--for-translation]`)

Decides how to bring a published article up to date — same URL (`update`), a new article
(`new`, the old one stays) or nothing (`none`) — and continues with that work. The content
strategist recommends; **the human decides**, in every mode. Design:
`design/herald/02-refresh-decision.md`. Interactive only (it writes base).

1. `HRD lock acquire --cmd refresh` (keep the token; release on every exit path); base clean;
   `HRD sync`.
2. Gather why: Search Console data if connected (`.claude/herald/secrets/` present — see
   `monitoring.md`; the article's row in `gsc.py show`), else the human's reason.
3. **Precheck**: `HRD refresh-decision --slug <slug> --precheck [--for-translation]` — the
   article must be in `published.json`. It prints `choices` (the decisions possible now),
   `blocked` (why others are not), `required` (`source-defect` or `for-translation`: only
   `update` — the article has to be fixed), `source_defects`, the publish times and the last
   decision on this article. Exit 1 (no choice left) → show its reasons and the next step
   (finish the topic in progress first; a slug outside Herald's format cannot be refreshed in
   place) and stop.
4. **Decision** — skipped with `--force-update` or `--direction <id>` (the human already
   decided: go to step 5 with `--source forced` / `--source direction --direction <id>`):
   - Spawn **content-strategist** for a refresh recommendation (persona § Refresh
     recommendation) with: the article body (`config.paths.body_pattern`), the precheck output
     (its `choices` — recommend only among them), the Search Console row if any, the reason
     from step 2, the source defects if any, `docs/editorial/refresh-policy.md` (absent in a
     repo set up before 0.10.0: use the template's default rules,
     `<<SKILL_DIR>>/templates/editorial/refresh-policy.md.tmpl`).
   - `HRD refresh-decision --slug <slug> --check` → problems → send them back to the strategist
     once, else show the recommendation as information only.
   - Ask the human (`AskUserQuestion`, in every mode): options = the `choices`, the
     recommendation first and marked recommended, each with a one-line consequence (`update`:
     rewrite this URL; `new`: a new article, this one stays; `none`: nothing changes); show the
     reasons, what is stale, the rule applied and the last decision. The human may override and
     says why (`--override-reason`).
5. **Apply**: write the topic entry to `.claude/herald/memory/refresh-topic.json` — `update`:
   `{"title": "<current title>", "category": "<cat>", "keywords": [...], "angle": "refresh:
   <reason>"}`; `new`: the recommendation's `new_topic` as the human confirmed or edited it —
   then `HRD refresh-decision --slug <slug> --decide <decision> [--source …] [--direction <id>]
   [--for-translation] [--override-reason "…"] [--topic-file .claude/herald/memory/refresh-topic.json]`
   (no topic file for `none`). It adds the topic (`update`: an `r-` topic with the decision and
   what is stale; `new`: a `t` topic that `follows` this article) and records the decision in
   `published.json`, or writes nothing.
6. Commit: `HRD commit --cmd refresh --kind refresh -m "chore(herald): refresh decision <slug>"
   .claude/herald/topics.json .claude/herald/published.json` — for `none` too. A failed commit →
   `git reset -q -- .claude/herald/topics.json .claude/herald/published.json` then
   `git checkout HEAD -- .claude/herald/topics.json .claude/herald/published.json`, report and
   stop. Then `HRD refresh-decision --slug <slug> --signal` (records `refresh-override` when the
   human overturned the recommendation), `git push origin <base>`, and **release the lock**.
7. Continue:
   - `update` / `new`: run `write.md` for the new topic id (in-session auto, `--attended` and
     `--ship` as `refresh` got them). A refresh topic's differences — refresh brief, its own
     article outside the cannibalization check, the fixed slug, a draft from the current body,
     the `direction` — come from the stage spine (`atoms/_stages.md`), whichever command runs it.
   - `none`: done — say so with the reason.

With translations, an `update` topic gets every translation language the article has on base;
they are all made again from the refreshed source.
