# RESUME

Continue an in-progress Issue from where it left off. Guild's state lives in GitHub labels (`_handoff.md` Section A), so resume is stateless recovery: read the label, continue the spine from that stage.

`$1` = Issue number.

> **Bash**: `_bash_rules.md`.

---

## Process
1. Validate `$1` is an Issue (not a PR):
   ```bash
   gh issue view $1 --json url --jq .url
   ```
2. Confirm Guild is initialized:
   ```bash
   ls .claude/guild/config.json
   ```
   Absent → "Guild not initialized (run `/gld init`)." Stop.
3. Read the current stage label:
   ```bash
   gh issue view $1 --json labels --jq '[.labels[].name]'
   ```
4. Decide:
   - `guild:done` → report "Issue #$1 is already done." Stop.
   - `guild:analyze` / `guild:design` / `guild:execute` / `guild:test` / `guild:qa` → **hand off to `/gld dev`**: read `<<SKILL_DIR>>/commands/dev.md` and execute it for `$1`. dev's Phase 1 reads the same label and starts at the matching stage — so resume and dev share one code path (no divergence).
   - no `guild:*` label → nothing to resume; suggest `/gld dev $1` to start fresh.

## Notes
- **Resume == dev from a mid-spine label.** There is no separate resume state — the label is the checkpoint. This is why interruption is safe (plan §12: labels are the state; no local file to corrupt).
- If a stage previously returned `NEEDS_HUMAN` or `OK PAUSE`, resume re-enters that stage; the leader re-runs the gate and prompts the human again as needed.
