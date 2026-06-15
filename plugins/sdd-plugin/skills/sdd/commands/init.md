# INIT

Set up SDD for the current GitHub repository.

**Language argument:** `$1` determines the language for Issue templates.
- `ko`, `korean`, `한국어` → Korean
- `ja`, `japanese`, `日本語` → Japanese
- `en`, `english`, or empty → English (default)

## Steps

1. **Copy Issue templates** from `<<SKILL_DIR>>/templates/{lang}/issue_*.yml` to `.github/ISSUE_TEMPLATE/`.
   - Select the template directory based on the language argument.

2. **Save the selected language** to `.github/.sdd-lang` for other commands to reference.

3. **Create GitHub labels — transactional sequence (R10)**.

   Run each `gh label create` as its own Bash call. Track every successful create in an in-memory list (kept in the main session's reasoning loop — no shell variables). If ANY create fails (non-zero exit or error in stderr), roll back every label already created, then stop.

   The 8 labels (in creation order):

   ```bash
   gh label create "sdd:analyze" --color "1d76db" --description "SDD: Requirements Analysis" --force
   gh label create "sdd:design" --color "0e8a16" --description "SDD: Design" --force
   gh label create "sdd:implement" --color "e4e669" --description "SDD: Implementation" --force
   gh label create "sdd:test" --color "f9d0c4" --description "SDD: Testing" --force
   gh label create "sdd:done" --color "0075ca" --description "SDD: Done" --force
   gh label create "sdd:child" --color "d4c5f9" --description "SDD: Child Issue" --force
   gh label create "sdd:review:deep" --color "b60205" --description "SDD: Force Opus for all reviewers on this Issue" --force
   gh label create "sdd:review:shallow" --color "c5def5" --description "SDD: Use cheaper models for reviewers on this Issue" --force
   ```

   The two `sdd:review:*` labels are optional overrides for token/quality dial per Issue (see `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section A).

   ### Transactional rollback procedure

   Pseudocode (executed by main-session reasoning between per-label Bash calls):

   ```
   created_labels = []
   for label in LABELS:
       Bash: gh label create <name> ... --force
       if exit code 0:
           append name to created_labels
       else:
           # Roll back in reverse order
           rollback_failures = []
           for name in reverse(created_labels):
               Bash: gh label delete <name> --yes
               if exit code != 0:
                   append name to rollback_failures
           if rollback_failures is empty:
               report "FAIL: '<offending label>' (<stderr>). Rolled back: <list>. Repo unchanged."
           else:
               report partial-cleanup message (see below)
           exit
   report "Labels: 8/8 OK. Templates: <N> copied. Language: <code>."
   ```

   - **One Bash call per label** (8 + N for rollback). The main session cannot use `&&` / `set -e` per `<<SKILL_DIR>>/SKILL.md` Bash Command Execution Rules — branching happens between calls.
   - Use `gh label delete <name> --yes` for rollback (non-interactive).
   - Log each rollback step's result (success/fail per label) before reporting.

   ### Outcomes

   | Outcome | Trigger | Message |
   |---|---|---|
   | `OK` | All 8 succeed (or pre-exist via `--force`) | `Labels: 8/8 OK. Templates: <N> copied. Language: <code>.` |
   | `FAIL: rolled-back` | Label N fails; prior N-1 successfully deleted | `FAIL: '<name>' (<stderr>). Rolled back: <list>. Repo unchanged.` |
   | `FAIL: partial` | Label N fails AND a rollback delete also fails | See message below. |

   ### Partial cleanup message

   If rollback itself fails for any label, produce a clear manual cleanup message and exit with error:

   ```
   ⚠ Partial label state — manual cleanup required:
     gh label delete sdd:analyze --yes
     gh label delete sdd:design --yes
     ...
   ```

   List exactly the labels that remain in the repo (creates that succeeded AND rollback deletes that failed).

   ### Edge cases preserved

   - **Idempotent re-run** on an initialized repo: `--force` succeeds silently on existing labels; rollback path never triggers.
   - **Color updates** via `--force` on an existing label are NOT treated as failures — only hard `gh` errors (auth, network, repo) trigger rollback.
   - **Template-copy failures** are NOT transactional (filesystem writes are local/idempotent — out of scope for R10).

4. **Report completion** with a summary of what was installed:
   - Number of Issue templates copied
   - Language saved
   - Labels created (count, with note about `sdd:review:deep` and `sdd:review:shallow` being optional dials)
