# PLAN — build the topic queue (`/hrd plan [--n N] [--issue] [--auto]`)

The content strategist proposes topic clusters for the queue (`.claude/herald/topics.json`).
It does not write articles. Plan §3.1, §5.

1. `HRD lock acquire --cmd plan` (keep the token; `HRD lock release --cmd plan --token <t>` on every
   exit path); base checked out and clean; `HRD sync`.
2. Delete `.claude/herald/memory/refresh-suggestions.json` (a previous run's). Spawn
   **content-strategist** (and **search-discovery** if enabled) with: `charter.md`, all
   category guides, `search-checklist.md` (if enabled), the existing queue (`HRD topics list`),
   the published list (`published.json` + content directory listing — translation directories
   excluded: a translation is the same article, `published.json` `translations`), open Herald PR titles.
   Task: propose N topics (default 10) as clusters, each `{title, category, keywords, angle}`;
   the **angle** must say what this article offers that the existing ones do not
   (scaled-content policy). Reject near-duplicates of existing or queued articles. Output file:
   `.claude/herald/memory/plan-proposal.json` (a JSON list). A rejected proposal whose existing
   article would be better refreshed goes to `.claude/herald/memory/refresh-suggestions.json`
   (`[{"slug", "reason", "proposed_topic"}]`, `[]` when none) — never into the proposal list.
3. Default: show the proposal grouped by cluster; the human keeps, edits or drops items.
   `--auto` (what `/hrd next` runs on an empty queue): no question — the editor-in-chief keeps
   the items that fit `charter.md` and a category guide, state a distinct angle and are not
   near-duplicates of a published, queued or open-PR article; it drops the rest and tells the
   user each kept or dropped title with a one-line reason. Nothing kept → release the lock and
   stop. (Unattended `plan` — `HRD_UNATTENDED=1` — is not supported.)
3.5 **Refresh suggestions** (`refresh-suggestions.json`, if any): show them as a separate list
   ("these existing articles may be worth refreshing"). `--auto`: report only. Otherwise, for
   each one the human picks, run `refresh.md` steps 3–6 right here (precheck → strategist
   recommendation → the human's decision → `--decide` → commit with `HRD commit --cmd plan --kind
   plan -m "chore(herald): refresh decision <slug>" .claude/herald/topics.json
   .claude/herald/published.json` → `--signal`) — before step 4, so the proposal's topics and
   these decisions never share a commit. Not taken from `refresh.md`: its push and lock release
   (plan keeps its lock; step 5 pushes) and its stop on a failed precheck (here: skip that
   suggestion with the reason and go on). Plan does not continue into write: the topics wait in
   the queue.
4. `HRD topics add --file .claude/herald/memory/plan-proposal.json` (accepted items only).
5. `HRD commit --cmd plan --kind plan -m "chore(herald): plan <n> topics"
   .claude/herald/topics.json`; `git push origin <base>`.
6. `--issue`: additionally open one GitHub Issue summarizing the cluster plan (`gh issue create
   --body-file`), for teams that track editorial plans as Issues. The queue stays the source.
