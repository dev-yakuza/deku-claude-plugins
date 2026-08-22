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
3. Read the current stage — `_handoff.md` **Section A — canonical stage derivation**, which returns `stage` (the one current stage label, or `"none"`) plus `harness` (`guild:harness` present) and `child` (`guild:child` present); `guild:needs-human` and `guild:harness` are excluded from `stage` because neither is one, and resume leaves every non-stage label untouched:
   ```bash
   gh issue view $1 --json labels --jq '{stage: ([.labels[].name] | map(select(startswith("guild:") and . != "guild:child" and . != "guild:needs-human" and . != "guild:harness")) | .[0] // "none"), harness: ([.labels[].name] | any(. == "guild:harness")), child: ([.labels[].name] | any(. == "guild:child"))}'
   ```
4. Decide on `stage`:
   - `guild:done` → report "Issue #$1 is already done." Stop.
   - `guild:children` → this is a **split parent** mid-orchestration → **hand off to `/gld dev`**: dev's Phase 1 detects `guild:children` and re-enters child orchestration (Phase 2b), re-discovering the children and continuing from the first not-done one (`_handoff.md` Section I).
   - `guild:analyze` / `guild:design` / `guild:execute` / `guild:test` / `guild:qa` → **hand off to `/gld dev`**: read `<<SKILL_DIR>>/commands/dev.md` and execute it for `$1`. dev's Phase 1 reads the same label and starts at the matching stage — so resume and dev share one code path (no divergence). A `child == true` Issue resumes exactly like any other (its `guild:child` marker is identity, never a stage, and stays on).
   - `"none"` **and** `harness == true` → a harness-remediation issue `init.md`'s readiness audit created (labeled `guild:harness` only, not yet started) — same outcome as plain `"none"` below: **hand off to `/gld dev $1`** to start it fresh (dev's Phase 1 adds `guild:analyze` and begins normally; `guild:harness` itself is not a stage and is left alone throughout, same treatment as `guild:child`).
   - `"none"` (no `guild:*` stage label) → nothing to resume; suggest `/gld dev $1` to start fresh.

## Notes
- **Resume == dev from a mid-spine label.** There is no separate resume state — the label is the checkpoint. This is why interruption is safe (labels are the state; no local file to corrupt).
- If a stage previously returned `NEEDS_HUMAN` or `OK PAUSE`, resume re-enters that stage; the leader re-runs the gate and prompts the human again as needed. Such an Issue also carries `guild:needs-human` — additive on top of its stage label, so `stage` is unaffected and routing above is unchanged. Resume never strips it; it is removed by the stage's own next forward transition (`_handoff.md` Section A).
