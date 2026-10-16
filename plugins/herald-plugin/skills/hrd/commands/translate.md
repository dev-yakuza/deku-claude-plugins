# TRANSLATE — translate a published article later (`/hrd translate <slug> [--lang l,…] [--adopt l,…] [--attended] [--ship]`, `--missing [--lang l,…]`, `--resume <id>`)

Adds languages to an article Herald already verified and published, without rewriting it:
`translation → verify → publish` on a `tr-<slug>-<YYYYMMDD>[-<n>]` topic (branch
`herald/<id>--<slug>`). Design: `design/herald/01-multilingual.md` §7. Needs `translations` in
config (`/hrd config`). The source and its images are outside a `tr-` PR's scope: it only adds
or redoes translations.

## A. One article (`/hrd translate <slug>`)

1. `HRD lock acquire --cmd translate` (keep the token; `HRD lock release --cmd translate --token
   <t>` on every exit path); base clean; `HRD sync`.
2. `HRD translate check --slug <slug> [--lang <l,…>] [--adopt]` — the preconditions, in code: a
   published Herald article (an external article has no research to verify a translation
   against → suggest `/hrd refresh <slug>` and stop), its reference topic's `research.md` and
   `claims-map.json` on base, no other topic in flight on the slug, and the bundle matching
   its verified record — or, with `--adopt`, differing only by the human translations being
   adopted. Without `--lang`: every target the article lacks (languages taken down with
   `--withdraw-lang` come back only when named). It prints `ref` and `langs`; refused → show the
   reasons and stop.
3. Add the topic: write `[{"id": "tr-<slug>-<date>", "title": "<the article's title>",
   "category": "<its category>", "keywords": […], "translate_of": "<slug>", "slug": "<slug>",
   "languages": [<langs>]}]` (`"adopt": true` with `--adopt`; a second one the same day ends in
   `-2`, `-3`, …) to `.claude/herald/memory/translate.json`, `HRD topics add --file …`, commit
   (`HRD commit --cmd translate --kind topics -m "chore(herald): translate <slug>"
   .claude/herald/topics.json`), push, then release the lock.
4. Continue with § C for that id (same flags).

## B. Every article missing a language (`/hrd translate --missing [--lang l,…]`)

`HRD translate missing [--lang …]` lists the Herald articles that lack a target language (minus
languages taken down, slugs with a topic in flight, and slugs whose last `tr-` ended in a source
defect with no refresh since). Show the list; attended → ask which to queue; then for each do
§ A steps 2–3 (one lock for the whole list), and say that `/hrd batch` (or `/hrd translate
--resume <id>` one by one) translates them.

## C. Run a tr- topic (`/hrd translate --resume <id>` — also what `batch`, `next`, `write` and `resume` route a `tr-` id to)

Preflight as `write.md` §0 (`HRD lock acquire --cmd write` — inherited from the batch runner
when unattended; `HRD lock release --cmd write --token <t>` on every exit path; base clean; `HRD sync`; `HRD ahead`; budget baseline). Unattended runs never write
base: every stop is `HRD result`.

1. `HRD begin --topic <id>` — for a new topic it re-checks § A step 2 (the queue may be old),
   copies the reference topic's `research.md` and claims maps, records brief…critique as
   inherited from it and sets the stage to translation; for an existing one it re-checks the
   source on base. Refused → hold `cannibalization` with the note `tooling: translate
   precondition: <reason>` (attended: `HRD state` + commit + push; unattended: `HRD result
   --status held:cannibalization --note …`); stop.
2. `HRD branch --topic <id> --slug <slug>` (an existing branch: switch to it and run the
   version check, `atoms/_stages.md` § Existing branches).
3. **Remap** (new topic, `translation.remapped` false): spawn the **fact-checker** with the
   source article, `<w>claims-map.json` and `<w>research.md`: re-map every factual sentence of
   the source *as it stands now* to **existing** claim ids — `text` exactly as in the article,
   never a new `C#`, never an edit to `research.md` or the article. Then `HRD remap --topic
   <id>` (code: ids exist in research.md, research.md unchanged, every text is in the article).
   A sentence no existing claim supports → hold `source-defect` (below).
4. Translation stage (`atoms/_stages.md` § translation) for the topic's languages; with
   `--adopt`, each translator gets the human's file as its starting point.
5. Verify (`atoms/_stages.md` § verify) on the whole bundle — the source and every existing
   translation, not only the new ones. Then:
   - a gap or `research_suspects` in the **source** → hold **`source-defect`** (a cleaned hold:
     the branch and files go): the verified article itself no longer holds up. Note: "the
     source needs `/hrd refresh <slug>` first". Unattended: `HRD result --status
     held:source-defect --note …`.
   - a gap in an existing translation outside the request → `HRD loopback --topic <id> --cause
     translation --lang <that lang>` adds it to the topic (and its PR scope) and redoes it.
   - a gap in a requested language → `--cause translation` as in `atoms/_stages.md`.
   `HRD loopback` refuses every other cause on a `tr-` topic.
6. Publish (`atoms/_stages.md` § publish: `git add` only `<w>` and the topic's translation files;
   `HRD scope` refuses the source) and, with `--ship` or `autonomy.publish: auto`, ship as
   `write.md` §3 (approval, `--consent` and `--session-auto` exactly as there). The PR is
   excluded from auto publish as `translated` unless `translations.auto_publish`.

After ship the `tr-` topic is the slug's reference topic; the ledger line and `published.json`
(`translations`) gain the languages.
