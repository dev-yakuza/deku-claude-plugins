# PLAN — build the topic queue (`/hrd plan [--n N] [--issue]`)

The content strategist proposes topic clusters for the queue (`.claude/herald/topics.json`).
It does not write articles. Plan §3.1, §5.

1. `HRD lock acquire --cmd plan`; base checked out and clean; `HRD sync`.
2. Spawn **content-strategist** (and **search-discovery** if enabled) with: `charter.md`, all
   category guides, `search-checklist.md` (if enabled), the existing queue (`HRD topics list`),
   the published list (`published.json` + content directory listing), open Herald PR titles.
   Task: propose N topics (default 10) as clusters, each `{title, category, keywords, angle}`;
   the **angle** must say what this article offers that the existing ones do not
   (scaled-content policy). Reject near-duplicates of existing or queued articles. Output file:
   `.claude/herald/memory/plan-proposal.json` (a JSON list).
3. Attended: show the proposal grouped by cluster; the human keeps, edits or drops items.
   (Unattended `plan` is not supported.)
4. `HRD topics add --file .claude/herald/memory/plan-proposal.json` (accepted items only).
5. `HRD commit --cmd plan --kind plan -m "chore(herald): plan <n> topics"
   .claude/herald/topics.json`; `git push origin <base>`.
6. `--issue`: additionally open one GitHub Issue summarizing the cluster plan (`gh issue create
   --body-file`), for teams that track editorial plans as Issues. The queue stays the source.
