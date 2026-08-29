# UPDATE (adopt central Guild improvements — preserve local evolution)

**Upgrade the repo's harness to the installed plugin version, keeping local evolution intact (중앙→repo 전파).** The counterpart to `init`: **init builds** the harness once; **update** adopts newer **central-owned** structure (gate scripts · settings hooks · `CLAUDE.md` block · label set · config schema · **role persona frontmatter and the persona marker region**) while **preserving local-owned** evolution (specialized agents **except `name`, and `description` plus the `persona:start`~`end` region when `config.language == "ko"`** · ⑥ knowledge · standards · overlay). Never clobbers what the repo grew **outside those keys and that region** — inside the marker region central text wins, including over a hand edit.

`$1` (optional): `--check` (show the version gap + what's available, change nothing) · `--migrate-personas` (draw the central/local boundary in existing persona files so the normal update can refresh them — see the section at the end) · default = interactive update.

> **Bash**: `_bash_rules.md`. Handoff + owner/repo: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K).

---

## Process
**0. Preflight** — read `.claude/guild/config.json` `version` (the repo harness version, stamped at init/last-update) and the **installed plugin version** (`<<SKILL_DIR>>/../../.claude-plugin/plugin.json`, or the marketplace-installed manifest). Guild not initialized → "run `/gld init` first".

**0b. Mode dispatch** — branch on `$1` **before** step 1.
- `--migrate-personas` → go straight to the `--migrate-personas` section at the end of this file;
  do not run steps 1–5. ⚠ **Version parity is the normal state for this mode, not an exception**:
  a repo needs migration precisely because it was initialized before the markers shipped and has
  been updating ever since. Routing it through step 1 would stop it at "최신입니다" without ever
  reaching the procedure.
- `--check` or no argument → continue to step 1.
- Anything else → report the argument as unrecognized, name the two valid ones, and stop. Do not
  fall through to the default: a mistyped flag would otherwise run a full interactive update the
  human did not ask for.

**1. Version gap**
Compare the two versions **semver-numerically** (major.minor.patch, each component as a number — e.g. `0.9.0 < 0.10.0`, not a lexicographic string compare where "0.9.0" would wrongly sort above "0.10.0"):
- `config.version` ≥ plugin → **check the git hook before reporting anything** (its own Bash
  call; `git rev-parse --git-path hooks/pre-commit` resolves correctly in a worktree, where
  `.git` is a file and the literal path does not exist):
  ```bash
  ls -l "$(git rev-parse --git-path hooks/pre-commit)"
  ```
  Missing or non-executable → **this is the fresh-clone case and it is the one thing parity does
  not mean is fine.** `.git/hooks/` is not tracked, so a clone has every harness file and no
  hook: the authoritative gate layer is absent while the version says current. Reinstall it (step
  2's **Gate script**/**git hook** bullets), report that you did, and continue to the counters.
  ⚠ Do not read the Hard rule "never downgrade → `config.version` ≥ plugin is a no-op" as
  covering this: that rule is about **not rewriting repo content backwards**, and reinstalling an
  absent hook writes nothing the repo owns. `_invariants.md`, `help.md` and `audit_readiness.md`
  all promise `/gld update` restores it after a clone — this bullet is where that promise is kept.
  Then report the persona-skip counters (below), then "최신입니다 (v<config.version>)." Stop.
- **Persona skip counters — reported on the version-parity branch above AND the version-gap
  branch below, even when the versions match.** Count by reason: non-`ko` · `local-only` ·
  migration pending · marker anomaly · mis-placed anchor · pre-run dirty · broken fence
  (pre-existing) · confirm-gate declined · **hired (local body, no central region)**. A repo can sit at the current version with personas
  that never got their central keys — if only the version gap is reported, the "최신입니다.
  Stop." branch hides that until the next release. This is the same hazard the partial-update
  rule names below: an invisible gap.
  - **How to count them on the version-parity branch, which stops before step 2.** Do not
    re-derive the structural reasons in prose — rule 3b says why. Run the same script, read-only:
    ```bash
    python3 <<SKILL_DIR>>/commands/atoms/persona_migrate.py --mode check --phase pre-write --anchor '<this repo's project-specialization heading, as rendered in config.language>' --file <every .claude/agents/*.md that has a central template AND a marker pair AND is not in the pre-run dirty set — and only when config.language == "ko" or you pass this repo's own anchor>
    ```
    ⚠ **The anchor is this repo's heading, not the `ko` literal.** Rule 3b may hardcode it
    because rule 0 gates rule 3b to `ko` repos; this call has no such gate — it runs for every
    repo. Passing `## 프로젝트 특화` to a `ja` repo makes every persona report `mis-placed
    anchor` and `marker anomaly`, and the remedies below then tell a human to repair correct
    files. §7.5 sanctions a non-`ko` repo migrating by hand with its own anchor, so those
    repos do reach this call with markers in place.
    ⚠ **If the file set is empty — no persona has a marker pair yet, which is the state of
    every repo that has not migrated — do not run the command.** Report `migration pending`
    for every persona with **neither** marker (one marker is `marker anomaly`, per rule 2) and
    skip to the next counter; invoking it with no `--file` is a usage
    error surfaced to the human on a healthy repo.
    Map its `FAIL:` lines to counters exactly as rule 3b does. The **six** reasons the script
    does not decide are read directly: **non-`ko`** from `config.language`, **`local-only`** from the
    absence of a central template, **migration pending** from the absence of **both** markers — a file with exactly one is a
    broken pair and belongs in `marker anomaly`, since migration refuses it (those
    files are excluded from the call above — the script would report them as marker anomalies),
    and **pre-run dirty** from `git status --porcelain -- .claude/agents/`. **`broken fence (pre-existing)`** comes from the frontmatter bullet's rule 6, judged by reading
    the file. ⚠ The pre-write call also surfaces it, as `start at P, fence2=-, …` — **count it
    once**, under `broken fence`, and do not also add that file to `marker anomaly`.
    `confirm-gate declined` cannot arise here — no gate runs — so report it as `0` rather than
    omitting it: an omitted counter and a zero counter read the same and only one is true.
  - ⚠ **`non-ko` is a property of the repo, not of a file — report it once, not per persona.**
    It comes from `config.language`, so otherwise it applies to all sixteen *and* each file also
    carries its own structural reason: two skips per file, with two contradictory remedies
    ("needs no action, a steady state" beside "a human moves `persona:end`"). Report one line —
    *region refresh: n/a, `config.language` is `<lang>`* — and let the per-file counters describe
    the files. The frontmatter merge still runs, so this is not "nothing happened".
  - ⚠ **A hired persona is a steady state, not backlog.** `evolve --hire` writes a file whose
    body is local prose that never came from a template, and deliberately gives it the habits
    marker only. So it has no marker pair (→ would count as *migration pending*) and
    `--migrate-personas` refuses it (`HITL(not-from-init)`). Counting it as backlog puts a
    permanent unactionable number in front of the human every run. Report those under their own
    line — *hired (local body, no central region)* — with no remedy, because none applies.
    Recognize them **from the file**, not from `classify`: a habits marker present **and** no
    `persona:start`/`end` pair. Step 1 is already reading these files and that property is right
    there. ⚠ **Do not key this on `classify`'s `not-from-init`** — `classify` needs `--init <sha>`,
    the repo records that SHA nowhere, and the migration section forbids inferring it. A guessed
    SHA makes **all sixteen** personas report `not-from-init`, and this rule would then file every
    one of them as "a steady state with no action" — sixteen genuinely-pending migrations reported
    as nothing to do, which is the invisible gap these counters exist to prevent.
  - **Say what to do about each, here.** The remedies are written down in step 2, and the
    version-parity branch never reaches step 2 — so a counter reported without its remedy is a
    dead end on exactly the path these counters were added for.
    **migration pending** → run `/gld update --migrate-personas`; this is the most common reason
    by far. **marker anomaly** → a human removes duplicate markers, adds missing ones, fixes the
    order. **mis-placed anchor** → a human moves `persona:end` to just above the project-
    specialization heading. **pre-run dirty** → commit or stash those files and re-run.
    **broken fence (pre-existing)** → a human repairs the YAML frontmatter. **non-`ko`** and
    **`local-only`** need no action — they are steady states, not backlog.
- `config.version` < plugin → show the gap and what an update brings (new/changed **commands** are already available plugin-side; the **repo-side** update refreshes gate scripts, the git pre-commit hook, settings hooks, the CLAUDE.md guild block, the label set, the config schema, and **role persona frontmatter + the persona marker region**). `--check` → stop here (nudge only). **`--check` reports the missing hook the parity branch above acts on, and stops** — `--check` changes nothing by definition, so it names the gap instead of closing it.

**2. Adopt central-owned repo artifacts (each shown + confirmed — INV1)**
Before touching any persona, snapshot the pre-run dirty set once — its own Bash call:
```bash
git status --porcelain -- .claude/agents/
```
Both persona bullets below skip every file in it. ⚠ `git status --porcelain`, not
`git diff --name-only`: the latter misses **untracked** files, and a role file `evolve`
just hired is exactly that. Skipping a file the human has uncommitted work in matters
because a later verification failure rolls a file back — which would take that work with it.

Preserving local content throughout:
- **Gate script** → copy the latest `<<SKILL_DIR>>/gates/gate_precommit.py` → `.claude/guild/gates/scripts/` (central-owned; overwrite) — **but check for a local extension first.** ⚠ This overwrite destroyed real enforcement once: a repo had hand-extended the script with a `test-naming` check that read its own `gates/rules/test-naming.md` at `status: confirmed`, and it was actively blocking commits. An update replaced the script; the rule file stayed on disk, nothing read it, and it enforced nothing — silently. That is an INV4 violation, and the root cause was that the repo had nowhere else to put the check.
  1. Before overwriting, compare the two (its own Bash call):
     ```bash
     diff .claude/guild/gates/scripts/gate_precommit.py <<SKILL_DIR>>/gates/gate_precommit.py
     ```
     A large diff is normal (this file changes every release). What matters is whether the **repo's** copy contains checks the central one does not — look for `def check_*` names or `rules/<name>.md` reads that the central file lacks, and for any `rules/*.md` file with no reader in the central script:
     ```bash
     ls .claude/guild/gates/rules
     ```
     The central script reads only `boundaries.md` as data (`secrets.md`/`verification.md` are declarations, not inputs). **Any other rule file is a local extension's rule file** and is the clearest signal one exists.
     ⚠ **Check `scripts/local/` before concluding the extension is still inline.** Once a check has been migrated, its rule file legitimately has no reader in the central script — the reader is `local/<name>.py`. Grep the local modules for the rule file's name; if one reads it, the migration is already done and the central script can be overwritten with no loss. Two other things also look like inline extensions but are not: this file's own post-mortem comments naming a rule file, and the central script's comments citing the case that motivated the `local/` mechanism. Confirm a live reader (`def check_*`, an `open(...rules/<name>)`) before reporting a conflict — a false alarm here teaches the human to click through the one warning that is supposed to stop them.
  2. Local extension found → **do not overwrite silently.** Report exactly which check would be lost and that its rule file would go inert. Offer to migrate it to `.claude/guild/gates/scripts/local/<name>.py`, which update **preserves**. A module may define either or both of:
     - **`check(ctx)` → `(block, warn)`** — *add* findings. `ctx` gives `changed_names()`, `changed_diff()`, `is_dismissed(path)`, `rule_file(name)` → `(text, confirmed)`, and `record(rule, action, path)` for the evolve scorecard. Build findings with `{"rule": …, "file": …, "message": …}` (a bare string still works).
     - **`refine(ctx, findings)` → the findings to keep** — *narrow* a central rule under a repo-specific condition. This is what a policy like "deleting a non-entry-point integration test is not a weakening — our architecture has one entry point, so removing the others restores it" needs: it is neither an added finding nor a static path, so neither `check()` nor `dismissed.md` can express it, and without this hook it stays in a maintained fork forever. Guard rails: a **`secret` finding can never be suppressed** (INV5 — `dismissed.md` is the reviewable path for an accepted secret risk); every suppression is logged as a firing (`action: suppressed-by-<module>`) so it reaches evolve and `/gld audit` rather than vanishing; a refiner that raises suppresses nothing.
     ⚠ One deletion produces **two** findings when the file carried ≥3 assertions — `verification:test-deleted` *and* `verification:assertion-drop`. A refiner that exempts only the first does not actually exempt the deletion. `assertion-drop` is an aggregate over the whole commit, so it carries **`files`**: the list of test files with a net removal (and `file` names the single one when there is exactly one). Exempt it only when that list is *entirely* accounted for by the exemption — `f.get("files") == [EXEMPT]` — so an unrelated file losing assertions in the same commit still blocks. Suppressing every `verification:` finding instead is far broader than any exemption should be. Migrate, verify the check still fires, and only then overwrite the central script. If the human declines the migration, **skip the gate-script update entirely** and say the harness stays behind — a stale gate that still enforces beats a current one that silently stopped.
  3. No local extension → overwrite normally.
- **Local gate extensions** (`.claude/guild/gates/scripts/local/*.py`) → **PRESERVE** (see the preserve list below). Central never writes into that directory.
- **Commit-gate wiring** → follow `init` step 6 **including its step 2 ownership question**, which decides the whole path. Resolve with `git rev-parse --git-path hooks/pre-commit` (its own Bash call — never hardcode `.git/hooks/`, absent in a worktree), then run the detector (`gate_precommit.py --detect-hook-manager`, stdin = the existing hook's text):
  - **`guild` / `none`** → copy the latest `<<SKILL_DIR>>/gates/pre-commit.sh` to the resolved path and `chmod +x` it (its own Bash call — git silently ignores a non-executable hook). **This is the fresh-clone recovery path**: `.git/hooks/` is not tracked, so a clone has every harness file but no hook until this runs. A hand-written hook is moved aside to `<path>.local` first, exactly as `init` step 2 describes.
  - **A manager name** (`lefthook`/`husky`/…) → **do not touch the hook file.** Confirm the gate is still registered as one of that manager's commands (`init` step 2b) and re-register it if a config edit dropped it — this is the case where `update` most earns its keep, since a `lefthook install` or a config rewrite can silently remove it. Show the diff and confirm before writing (INV1).
  Then check `git config --get core.hooksPath` — on the unmanaged path a non-empty value means Guild's hook will never fire, so report it rather than claiming the gate is active; on the managed path it is expected and harmless.
- **Universal gate rules** → refresh `.claude/guild/gates/rules/secrets.md` and `rules/verification.md` (central-owned; overwrite) — **but only together with the gate script**. ⚠ These files *declare* what the gate enforces; the script *is* the enforcement. Refreshing the declaration while the script stays behind makes it claim protection the repo does not have: a 0.52.0 `secrets.md` lists `.key`/`.p8`/`id_rsa`/`.netrc`/`kubeconfig`/`.tfvars`, and against an older script none of those are actually checked. A human reading it would reasonably stop worrying about exactly the files still going through. **If the gate-script update is skipped (a local extension pending migration), skip these too** and say they stay at the old version for that reason — a declaration that overstates coverage is worse than one that is merely old. These two are the **human-readable declaration** of what the gate enforces, not inputs it parses: the secret and verification checks are hardcoded in `gate_precommit.py` precisely because they are universal and non-hallucinated. Only `rules/boundaries.md` is data-driven (the gate reads its `- forbid:` lines, and its **frontmatter** `status:` decides block vs warn).
- **settings.json** → union the latest central `PreToolUse` entries — **both** the `Bash` early-warning hook and the `Edit|Write|MultiEdit` `--guard-config` hook — and the `permissions.ask` list (INV1/INV3 made mechanical). **Preserve local `permissions.allow` and any local hooks**; dedupe by full command string, which includes the mode flag (deduping by script path alone would collapse the three modes into one).
- **Role persona frontmatter** (`.claude/agents/*.md`) → refresh the central keys
  `name` and `description` from the role's template; leave `model` and any other key
  untouched (they are LOCAL). Everything below the frontmatter is untouched here.
  1. **Scope**: only roles that are BOTH in `config.json`'s `roles` AND have a central
     template under `<<SKILL_DIR>>/templates/agents/`. Report the rest as "local-only" (rendered in
     `config.language`) and skip. That is `n/a` for this repo,
     not a partial update: it does not block the `version` bump.
  2. `name` refreshes in **every** language — `init.md` keeps it unchanged regardless
     of `language`, so the template value is always the right one.
  3. The **`description`** refresh runs **only when `config.language == "ko"`**. In any
     other language the repo's value is a translation the repo owns (init translates it)
     — report the drift and stop there.
     ⚠ That is **not** a partial update: it is `n/a` for this repo, so it does **not**
     block the `version` bump — see the `Config` bullet's partial-update rule below.
  4. **Show the drift per file and confirm (INV1)** — one line per changed key, old → new.
     A `description` is what Claude Code routes on; a wrong one misroutes silently.
  5. **Skip any persona in the pre-run dirty set** taken at the top of this step. Report
     each skip. That skip is `n/a`, not a partial update: it does not block the
     `version` bump.
  6. **Frontmatter sanity, before and after.** *Before*: if the file's fence is already
     broken (no closing `---`), skip it and report — this run cannot fix a pre-existing
     break — and that skip is `n/a`, not a partial update: it does not block the
     `version` bump. *After*: the closing `---` is still there, `model` and every other local key
     survived, and the key count did not shrink. **If the after-check fails, restore that
     file's frontmatter to its pre-write state and report** — this break *was* caused by
     this run, so restoring it is the fix, not a discard. A broken YAML fence stops
     Claude Code from registering the sub-agent at all, so this failure blocks the
     `version` bump and is reported as its own counter.
- **CLAUDE.md guild block** → update only the content between `<!-- guild:start -->`…`<!-- guild:end -->` to the latest template shape, **preserving everything outside the markers** and any local knowledge-routing lines you can carry forward.
- **Role personas** (`.claude/agents/*.md`) → update only the content between
  `<!-- guild:persona:start -->` … `<!-- guild:persona:end -->`, preserving everything
  outside this marker region — the H1, every section below `persona:end`, the habits
  block, and **every frontmatter key except `name`/`description`** (those are refreshed by the
  **Role persona frontmatter** bullet). Show the diff per file and confirm (INV1).
  0. **Only when `config.language == "ko"`.** Otherwise the central region is Korean and
     re-translating it drifts unchanged lines — report the N-line gap and stop. That is
     `n/a` for this repo, not a partial update: it does not block the `version` bump.
  1. **Scope**: only roles that are BOTH in `config.json`'s `roles` AND have a central
     template under `<<SKILL_DIR>>/templates/agents/`. Report the rest as "local-only" (rendered in
     `config.language`) and skip. That is `n/a` for this repo, not a partial update:
     it does not block the `version` bump.
  2. **A persona with NEITHER marker is NOT updated** — and "neither" is literal. A file
     carrying exactly one of the two is a **broken pair**, not an unmigrated file:
     `--migrate-personas` refuses it (`broken marker pair (start xN, end xM) — a human repairs
     it first`), so counting it as *migration pending* hands the human a command that cannot
     help. Report those as **marker anomaly** with the repair instruction instead. ⚠ **A file with a habits marker but no pair is a *hired* persona, not backlog** —
     `evolve --hire` writes local prose that never came from a template and gives it the habits
     marker only. Report it under `hired (local body, no central region)`, with no remedy.
     For a file with neither marker at all: do not guess where the central
     region ends — a wrong split silently deletes local knowledge, and the loss only
     surfaces much later. Report it as "migration pending" (rendered in
     `config.language`) and point at `/gld update --migrate-personas`.
     ⚠ Skipping here is **not** a partial update either: personas are a separate counter,
     so it does **not** block the `version` bump in the `Config` bullet of this step.
  3. A persona whose marker region was hand-edited is overwritten. That edit belongs in
     the habits block. Once the file passes rule 5, the confirm gate's diff is the only
     defence — say so.
  3b. **Structural sanity, before writing** — for every file that got past rule 2 **and is not
     in the pre-run dirty set** (rule 5 owns those; including them here would land one file in two
     counters, which rule 5 promises does not happen). Run the
     same script the migration uses, in one Bash call over all of them:
     ```bash
     python3 <<SKILL_DIR>>/commands/atoms/persona_migrate.py --mode check --phase pre-write --anchor '## 프로젝트 특화' --file <the personas that passed rule 2 and are not in the pre-run dirty set>
     ```
     ⚠ **If that set is empty, do not run the command** — `--file` with no argument is a usage
     error (exit 64) surfaced to the human on a healthy repo. Empty is the *normal* state of any
     repo that has not migrated: rule 2 sends every persona to `migration pending` and nothing
     reaches this rule. Skip to rule 5 and report the counters. (Step 1's read-only copy of this
     call carries the same guard — the two call sites must stay in step.)
     ⚠ **Run it; do not paraphrase it.** An earlier version of this rule restated a subset of
     these checks in prose and dropped two — `persona:start` above the frontmatter fence
     (which makes the write destroy the YAML, so Claude Code stops registering the sub-agent
     at all), and a heading inside the region that the template does not have (local content
     that would be replaced as if it were central). Both passed the prose rules and were
     caught only after the damage, by step 4.
     **Any file with a `FAIL:` line → skip it and report which check failed.** Do not write
     and then roll back: these are pre-existing conditions this run cannot fix, and rolling
     back would only discard the update. Every `FAIL:` the script can print, its counter, and
     who fixes it:
     ⚠ **Match on what the script PRINTS, and on the values in it — not on facts you work out
     yourself.** A check that passes prints nothing, so "the anchor is fine" can appear either
     as the *absence* of an `anchor x…` line **or** as `anchor x1` inside a line printed because
     the **H1** is wrong. One line, two independent subjects: an earlier version keyed a branch
     on the line's presence and left every H1-plus-mis-placed-`end` combination matching nothing.
     Read the counts.

     · `marker appears N time(s)` · `marker order` → **marker anomaly**. A human deletes
       duplicates, adds what is missing, reorders.
     · `anchor xN, h1 xM` (the line is printed only when something is wrong with one of them)
       → **marker anomaly**, in four shapes: `N ≥ 2` or `M ≥ 2` → a duplicate landmark; a human
       removes it. `M = 0` → no H1; a human adds the `# <Role> — <project>` line back.
       `, h1 below anchor` appended → wrong order; a human moves the H1 above the anchor.
       `N = 0` with `M = 1` and no ordering note → **not a duplicate**: the anchor heading is
       gone or renamed, and the `first heading below end` bullet below owns it.
     · `start at P, fence2=F, h1=H` → **read the three values; this one FAIL means three
       different things** and only one of them is about the marker.
       — `F` is `-` → the closing frontmatter `---` is **missing**. `persona:start` is where it
         belongs; the fence is not. That is the **`broken fence (pre-existing)`** counter, not
         `marker anomaly` — the frontmatter bullet's rule 6 owns it, so report it there and
         nowhere else. A human repairs the YAML frontmatter.
       — `H` is `-` → the file has **no H1**. The region has no upper landmark; a human adds the
         `# <Role> — <project>` line back. Counter: `marker anomaly`.
       — both are numbers → `persona:start` is above the fence, or above the H1, **or both** —
         the test is `P > F` **and** `P > H`, and it failed. Compare `P` with each: if `P < F`
         the write would replace the YAML and Claude Code would stop registering that sub-agent
         at all; if `P < H` only, the YAML is safe but the **H1 falls inside the region** and
         the write deletes it. Either way a human moves the marker below both. Counter:
         `marker anomaly`.
     · `first heading below end is X, expected Y` — **read the anchor count**, not whether an
       `anchor x…` line is present. That line is printed when the anchor **or** the H1 is wrong,
       so its mere presence says nothing about the anchor; `anchor x1, h1 x2` means the anchor
       is fine and the H1 is not.
       — `anchor x0` → the repo **renamed** its project-specialization heading.
         `persona:end` is already in the right place, so moving it is a no-op and there is no
         duplicate to remove. Two ways out, and a human picks: restore the heading to `Y`, or
         keep the new name and pass **it** as `--anchor` from now on (record it — the literal in
         this rule will be wrong on every future run). Until then the file is skipped every
         time, which is why this case needs naming: the counter says `mis-placed anchor` and the
         anchor is not mis-placed.
       — **no `anchor x…` line at all, or a line whose count is `anchor x1`** → the anchor is
         present and unique, so the defect is the marker: **mis-placed anchor**, literally —
         `persona:end` sits above the wrong heading. A human moves it to just above `Y`.
         **This is the plain case and the common one.** (If that line also carries an H1
         problem, fix the H1 too; the `anchor xN, h1 xM` bullet above owns that half.)
       — `anchor x2` or more → a duplicate anchor *and* the marker above the wrong copy.
         The `anchor xN` bullet above owns the counter; removing the duplicate usually resolves
         both, so do that first and re-run rather than moving the marker.
     · `N line(s) stranded between end marker and anchor` → **mis-placed anchor**. Central prose
       fell out of the region; a human moves `persona:end` below it.
     ⚠ **A file can carry two genuine defects and land in two counters.** Rule 5's "one file,
     one counter" governs the *skip reasons* — which file is skipped and why — not the FAIL
     lines inside one skip. When both `broken fence (pre-existing)` and `marker anomaly` apply,
     report the fence one: it is the pre-existing condition the frontmatter bullet already owns,
     and repairing it is the prerequisite for everything else.
     ⚠ **No heading-set comparison runs here** — `--templates` is deliberately not passed. As a
     pre-write gate it would fail a correctly-migrated role whose central heading was renamed
     since (measured: `product-owner` on both live repos), and the response to a failure is to
     skip the file — so that role would never receive a central update again. The replacement
     itself is what makes the heading match. That comparison belongs to `--mode classify`, which
     routes a role to a human instead of blocking it.
     **Re-running `--migrate-personas` fixes none of them** — it refuses a file that already
     has the pair. (A file *missing* the pair never reaches this rule; rule 2 sends it to
     migration, which does create what is absent.) Each skip is `n/a`, not a partial update:
     it does not block the `version` bump.
  4. **Not a check — a counter-naming note.** Both persona counters come from rule 3b's single
     call **plus rule 2's broken-pair branch** — a file with one marker never reaches 3b's call,
     and rule 2 assigns it `marker anomaly` directly. Per 3b's table: **`marker anomaly`** = marker count, marker order, anchor/H1
     uniqueness, or start-marker position; **`mis-placed anchor`** = the anchor line or stranded
     prose. The number is kept so the counters keep their names and older reports stay readable.
     (Rule 3b passes the `ko` anchor literal, so it runs under rule 0's gate.)
  5. **Skip any persona in the pre-run dirty set** taken at the top of this step. Report
     each skip. Both persona bullets — this one and the frontmatter one — read that same
     snapshot, and dirty is judged **only here and in the frontmatter bullet's matching
     rule**, never inside Scope (rule 1), so one file lands in exactly one counter. That
     skip is `n/a`, not a partial update: it does not block the `version` bump.
- **`.claude/guild/.gitignore`** → ensure it carries everything `init` writes there (currently `memory/` and `gates/scripts/local/__pycache__/`). Central-owned and additive: add missing lines, never remove a line the repo added.
- **Labels** → read what exists **before** claiming anything is missing (its own Bash call):
  ```bash
  gh label list --limit 200 --json name --jq '[.[].name] | map(select(startswith("guild:")))'
  ```
  ⚠ **`gh label list --json name` returns a FLAT array of `{"name": …}` objects** — not an object with a `.labels` field. Indexing it as `.labels[]` (the shape `gh issue view` uses, which is easy to reach for here) errors with `jq: error … Cannot index array with string` and exit 5, producing **no output at all** — which then reads as "no labels exist". Same gotcha as `atoms/audit_readiness.md` Group 4, which documents it against the real binary.
  Create only the names genuinely absent from that list, idempotently with `--force`. **The canonical set is `init.md` P2 §7's `gh label create` block** — read it rather than an enumeration held here, so a label added centrally (e.g. `guild:sprint`) reaches an existing repo through this step without a second edit. **Report the actual count** — "N개 중 M개 누락" from the read, never "전부 누락" inferred from an empty or failed query. Observed: an update run reported every `guild:*` label missing on a repo whose Issues were actively carrying `guild:done`/`guild:child`; a bad query is indistinguishable from an empty repo unless you look.
- **Config** → add any **new** config keys with defaults, **preserving existing local values** (language, roles, commands, gate/automation dials). Bump `version` to the plugin version **only if every central-owned artifact above was actually adopted**.
  ⚠ **Persona skips are a separate counter, not a partial update.** Whatever the reason — non-`ko`
  (rule 0) · `local-only` (rule 1) · migration pending (rule 2) · **hired (rule 2's carve-out)** ·
  marker anomaly (rule 3b) ·
  mis-placed anchor (rule 3b) · pre-run dirty (rule 5) · a pre-existing broken frontmatter fence ·
  a human declining a confirm gate — a skipped persona does **not** block the `version` bump.
  Report the counts and bump. Two exceptions are real failures that DO block it: a frontmatter
  break *this run caused*, and a post-write marker check that fails in step 4. Each gets its own
  counter.
  ⚠ **A partial update must NOT bump `version`.** `config.version` is a single scalar standing for the whole harness, so stamping it after skipping a component (most often the gate script, when a local extension could not be migrated) makes the gap **invisible**: the next `/gld update` compares versions, reports "최신입니다", and stops — the deferred work is never revisited, and the repo reads as current while running an old enforcement layer. Leave `version` at its old value, state plainly which component is behind and why, and say that re-running `update` will re-offer it. Re-offering the already-adopted parts is idempotent and harmless; losing track of the skipped one is not.
- **Linter scope** → re-run `init` step 0b's check. `update` **rewrites `gate_precommit.py`**, so a plugin release that adds a new secret or skip pattern adds new vocabulary to a file the repo's spell checker may lint — and the human then discovers it as a failed commit, not as an update result. If Guild-managed paths are still not excluded from a linter that would see them, propose the exclusion and confirm (INV1). This is a check every update must repeat, not a one-time `init` concern.

**3. PRESERVE — never touched** (local evolution, INV4): `.claude/agents/*` **except `name`, `description` when `config.language == "ko"`, and the `persona:start`~`end` region when `config.language == "ko"`** · `.claude/guild/knowledge/*` (⑥) · `docs/standards/*` (②) · `.claude/guild/overlay/*` (flow overrides) · `.claude/guild/evolution-log.md` (⑤) · `.claude/guild/gates/rules/boundaries.md` (locally grown by `/gld evolve` — `- forbid:` rules, `status: draft`/`confirmed`) · `.claude/guild/gates/dismissed.md` (human-curated accepted-risk registry) · `.claude/guild/gates/scripts/local/*` (**repo-local gate extensions** — the supported place for a check the central script doesn't have; central never writes there) · `.claude/guild/gates/rules/*.md` other than `secrets.md`/`verification.md` (a rule file the central script doesn't read belongs to a local extension) · `.claude/guild/gates/findings.json` and `.claude/guild/memory/*` (**runtime state, not structure** — the gate rewrites `findings.json` on its next run and the memory tier is gitignored episodic data; update neither refreshes nor deletes them).

**4. Verify it actually landed — before reporting anything** (its own Bash calls; do not skip, and do not report from what you *intended* to write):

```bash
git status --short
```
```bash
jq -r .version .claude/guild/config.json
```

- **Working tree unchanged AND `config.version` still the old value** → **nothing was applied.** Say exactly that and why (the human declined at the confirm gate · the run was cancelled · every artifact was already current). Do **not** report success. Then state what to run to actually apply it.
- **`config.version` still the old value but files did change** → a partial apply: name which artifacts landed and which did not, and that the version was deliberately not bumped. This is a state to surface, not to smooth over.
- **`config.version` == plugin version and the tree shows the expected changes** → applied; report normally.

**Persona marker check — only for files whose marker region this run replaced.** The decisive
one: the first `^## ` after `persona:end` must still be the project-specialization heading. That
is the same anchor check rule 3b ran before writing; re-running it after catches a replacement
that itself mis-placed the markers, and `--scope below-end` adds the one comparison that names
the damage directly: nothing below the end marker may have changed.

`--base HEAD` is correct here even though this run has already written. Rule 5 skipped every
persona that was dirty before the run, so every file that reached the write was clean at `HEAD`
— its pre-write state *is* `HEAD:<path>`. (An earlier version passed no `--base` on the stated
grounds that the pre-write state "is in the working tree, not in history", which is true only
of the files rule 5 excluded. The whole-file comparison would indeed be wrong here — it flags
every legitimately-retired central line — which is what `--scope below-end` fixes.)

```bash
python3 <<SKILL_DIR>>/commands/atoms/persona_migrate.py --mode check --phase post-write --base HEAD --scope below-end \
        --anchor '<the project-specialization heading, as this repo renders it>' \
        --file <the persona files this run rewrote>
```

- ⚠ **`--phase post-write` is what makes a rollback safe here.** It runs exactly the four checks
  a replacement can break: **the `start`/`end` marker count** (the write rewrites the span
  between them and can swallow one), the anchor moved, prose stranded above the anchor, and
  anything below the end marker changing when nothing there should have.
  It excludes marker **order**, the **habits** marker count, anchor/H1 uniqueness, and
  start-marker position — those are rule 3b's **pre-write** conditions, states `update` cannot
  create, already filtered before the write. Rolling back for one of them would discard a correct
  refresh without fixing the defect, so the phase excludes them rather than leaving the
  distinction to whoever reads the output. ⚠ The seam is **what the replacement can reach**, not
  "counts versus everything else": the habits marker lives below `persona:end`, outside anything
  this run writes.
- ⚠ **A human editing the persona between rule 3b and step 4 lands here too, and gets rolled
  back.** Nothing below `persona:end` is written by this run, so any difference there is either
  a replacement bug — which is what step 4 exists to catch — or a mid-run hand edit, and the
  two are indistinguishable from the file alone. The window is seconds and rule 5 already
  excluded files that were dirty at the start, so the cost is small and the alternative is a
  botched replacement going unreported. **Say so when it happens** rather than silently
  discarding: name the lines and let the human re-apply.
- ⚠ **Decide from the FAIL *set*, not from one line.** The checks are not independent: a
  mis-placed end marker fires two at once, and their individual remedies pull in opposite
  directions. Read every `FAIL:` for that file, then take the **first** rule below that matches.
  Every set the **write** can produce falls under exactly one. (`cannot read <f> at HEAD` and
  `no end marker in the base` are producible by the check but not reachable from step 4 — rule 5
  excluded every persona that was dirty or untracked at the pre-run snapshot, so each file that
  reaches here exists at `HEAD` in its pre-write form. Seeing one means step 4 was handed a file
  it should not have been; stop and say so rather than restoring anything.)
  1. **A marker is missing** — `no end marker in the current file` · `start marker appears 0
     time(s)` · `end marker appears 0 time(s)` → **restore the whole file from `HEAD`.** There is
     no region left to restore, so "restore the region" names an operation with no input. The
     frontmatter refresh from earlier in step 2 goes with it — say so, and re-run.
  2. **The boundary moved** — `first heading below end is …` · `stranded between end marker and
     anchor` · a marker appearing **more than once**, **with or without** a loss line →
     **restore the whole file from `HEAD`.** The frontmatter refresh from earlier in step 2 goes
     with it, exactly as in rule 1 — say so, and re-run. Rule 3b proved the boundary was right
     before the
     write, so a boundary failure now is this run's doing. ⚠ Do **not** apply rule 3 here even
     though a `lost` line usually accompanies it: that line *is* the moved boundary, not damage
     below it. Restoring only the below-end content duplicates the anchor and strands one copy
     inside the region; restoring only the region splices the old span over a file whose edges
     are in the wrong place and deletes the project-specialization section.
  3. **Only the content below the end marker changed** — `N line(s) lost` or `N line(s) appeared
     below the end marker`, and **no other `FAIL:` line** → **restore the file's content
     below `persona:end` from `HEAD`**, leaving the refreshed region in place.

  Whichever rule applied, the failure **blocks the `version` bump** and is reported as its own
  counter. ⚠ Restore **that one file** only — the other personas in this run were refreshed
  correctly. ⚠ Do not include files that were only frontmatter-refreshed: they may have no
  markers at all (migration pending), and this check would report a state they were never in.

Spot-check the two artifacts whose *content* matters most, rather than trusting that a copy happened — the gate script is the enforcement layer and the hook wiring is what makes it run:

```bash
grep -c "^def main_" .claude/guild/gates/scripts/gate_precommit.py
```
On the **managed** path, also confirm the gate is registered in the manager's config (grep it for `gate_precommit.py`); on the **unmanaged** path, that `.git/hooks/pre-commit` exists and is executable.

⚠ **"The plugin updated" ≠ "this repo updated."** These are two different things and conflating them produces a false success report — observed: a run that applied nothing still told the human "Guild 플러그인 업데이트가 적용됐네요", because the *plugin* had indeed reached a new version while the *repo harness* sat untouched at its old one. Step 1 already draws this distinction; the report must keep it. Always name the repo-side version explicitly (`v<old> → v<new>`), never just "updated".

**5. Report** — what updated, what was preserved, the repo-side version transition, and any newly-available commands. Reversible (git — the update is uncommitted working-tree changes the human reviews + commits). If step 4 found nothing applied, the report is that finding.

## Hard rules
- **Preserve local evolution** (INV4 additive/merge) — agents (**except `name`, and `description`/the marker region when `config.language == "ko"`**) · knowledge · standards · overlay · ledger are LOCAL-owned and never overwritten. Only central-owned *structure* is refreshed.
- **Confirm structural changes** before applying (INV1); leave them uncommitted for the human to review + commit (reversible, INV3).
- **Never downgrade** (`config.version` ≥ plugin → no-op **for repo content**). ⚠ Reinstalling an
  absent git hook is not a downgrade and is not content: `.git/hooks/` is untracked, so a fresh
  clone is current *and* ungated. Step 1's parity branch handles it.
- **Never claim an update that did not happen.** Report from step 4's verification of the working tree and `config.version`, never from intent. A declined or cancelled confirm gate is a normal outcome — say so plainly; an unchanged repo reported as "적용됐다" is worse than an obvious failure, because the human then believes the enforcement layer is current when it is still the old one.

---

## `--migrate-personas` — draw the boundary in an existing persona

A repo initialized before the persona markers shipped has no `persona:start`/`end` pair, so step 2
skips its personas and reports them as *migration pending*. This mode inserts the markers so the
normal update can refresh them from then on.

**It inserts markers. It never moves a line.** That is the whole safety property: this run cannot
lose anything, because it adds and does not delete. Loss can only happen later, when `update`
replaces the central region — and only if a marker was placed in the wrong spot, or a locally-grown
line was left inside the region. Both are what the checks below are for.

**Preconditions** (all blocking):
- `config.language == "ko"`. Other languages have translated headings, and the anchor this
  procedure defaults to is `## 프로젝트 특화`. A non-`ko` repo runs the **T2 path by hand**
  instead (§7.5): the human names this repo's own project-specialization heading, and every call
  takes `--anchor '<that heading>' --localized`, plus `--habits-placeholder '<localized>'` on
  insert. Report that and stop here rather than running the mechanical path.
- Harness committed, working tree clean for `.claude/agents/`.
- The repo's `init` commit SHA — **ask the human once per repo, do not infer it.** Commit-title
  heuristics do not work: of two measured repos only one has `init` in the title. Show the
  candidates and let them pick:
  ```bash
  git log -5 --format='%h %ad %s' --date=short --diff-filter=A -- .claude/agents/
  ```

### 1. Classify each role — T1 (mechanical) or T2 (needs a human)

**Scope first**: only roles in `config.json`'s `roles` that also have a central template under
`<<SKILL_DIR>>/templates/agents/`. Report the rest as `local-only` and skip — a file `evolve`
file with no central template has no central region to mark off, and wrapping it in one would tell
the next `update` to overwrite local prose. ⚠ The test is **template existence**, not "did `evolve`
hire it" — activating a roster role via `hire` produces a file that *does* have a template. Such a
file lands in `migration pending`, not `local-only`; one file, one counter.

The classification asks one question: **did anything grow inside what will become the central
region?** That region runs from the line after the H1 to the line before the
project-specialization heading (`ko`: `## 프로젝트 특화`).
Anything outside it — frontmatter, H1, the specialization section — is local either way.

```bash
python3 <<SKILL_DIR>>/commands/atoms/persona_migrate.py --mode classify --init <the SHA> --anchor '<the project-specialization heading, as this repo renders it>' \
        --templates <<SKILL_DIR>>/templates/agents
```

- **`done(markers already present)`** — that role is finished; skip it. This is what makes a
  **second** run usable, and the design leans on it: T2 may be deferred indefinitely, so the
  normal shape is "migrate T1 now, come back for T2 later". Without this verdict every
  already-migrated role re-reads as `T2` — the markers themselves sit inside the central region,
  so the diff against `init` shows growth there — and nine finished files get routed back to the
  human path.
- **`local-only(no central template)`** — that role has no template under
  `<<SKILL_DIR>>/templates/agents/`, so there is no central region to mark off. Rule 1 already
  puts it outside migration scope; report it and move on. ⚠ This is **not** the same as `--templates` pointing at the wrong directory, which is a
  fatal usage error — a wrong path would disable the foreign-heading guard for every role at
  once, so the script refuses to run rather than reporting every role as local-only. It checks
  that the directory actually holds **persona** templates, not merely that it holds `*.md`
  files: the sibling `templates/standards/` would otherwise pass and turn every role into a
  `local-only` verdict, which reads as "nothing to migrate".
- **`T1`** — nothing grew in the central region. Section 2.
- **`T2`** — something did. Section 3, one role at a time, with a human.
- **`HITL(…)`** — this role needs a human before anything else happens. **The reasons are not
  one family and they do not share an action** — read the parenthesis and take the matching row:

  | reason | what it means | action |
  |---|---|---|
  | `dirty — commit or stash it…` | the diff reads committed trees while the boundary comes from the working tree, so a dirty file can read as T1 when it is not | commit or stash that file, re-classify |
  | `not-from-init` | the file predates `init` or was re-added later, so **its body may never have come from a template at all** | **do not run section 3 on it.** Compare it against the central template by hand first; wrapping it would make the next `update` overwrite prose that was never central |
  | `untracked — commit it, then re-classify` | git has never seen this file; `evolve --hire` produces exactly this | commit it, then re-classify. ⚠ Until it is committed it counts as **pre-run dirty**, not as `hired` — the `hired` line needs a committed file |
  | `add-commits=N` (N ≥ 2) | git shows the file added more than once | same as above — establish where the body came from before marking a region |
  | `marker anomaly: start xN, end xM` | half a pair; neither mode can repair it | a human deletes the stray marker or adds the missing one, then re-classify |
  | `h1=N anchor=M (each must be exactly 1)` · `h1 sits below the anchor` | the region has no unambiguous edge | a human fixes the landmarks, then re-classify |
  | `central template is malformed` | a **plugin** defect, not a repo one | report it upstream; do not migrate around it. The other roles' verdicts are unaffected |
  | `git-log-failed` · `git-status-failed` · `git-diff-failed` · `diff-without-hunks` | the oracle itself could not run | fix what the message names (often `.gitattributes`), then re-classify |

- **`T2(heading-not-in-template: …)`** — the region carries a `## ` heading the current
  template does not. That is **either** a locally-grown section that must move below the
  anchor before the markers go in, **or** central text whose heading was renamed centrally
  since this repo was initialized, in which case nothing needs moving. The script cannot tell
  them apart — separating them would need the template as of the init commit, which the plugin
  deliberately does not ship. Measured on the two live repos: one of each. Look at the section
  and decide; then run section 3 without `--init`.

  ⚠ **In a non-`ko` repo this verdict is meaningless unless you pass `--localized`.** The
  templates' in-region headings are Korean and `init` translated them, so without the flag the
  comparison is between a translation and its source: **every role reports
  `T2(heading-not-in-template)`**, the two branches above are both false, and following the first
  one cuts the central sections out of the region with every check still green. With the flag the
  diff alone decides T1/T2, which is what §7.5 assumes. ⚠ **Never pass it in a `ko` repo** — it
  switches off the only mechanical detector of local content that predates the init commit
  (measured real: `word_app/leader.md`'s `## 코드상태 사실확인`). Derive it from
  `config.language`, nowhere else. On insert, pass `--habits-placeholder '<localized>'` too: the
  default is the Korean line, and `audit`/`monitoring` key on that bullet to tell "no habit yet"
  from day-1 boilerplate.

### 2. T1 — insert the markers

Per file, **guard before writing**: `^# ` exactly once, **this repo's project-specialization
heading** exactly once (`ko`: `## 프로젝트 특화`; otherwise the localized one named in §1), H1 above
the anchor. Any other count → skip and report; do not guess.

```bash
python3 <<SKILL_DIR>>/commands/atoms/persona_migrate.py --mode insert --anchor '<same heading>' --habits-heading '<the role-habits heading, same language>' \
        --init <the SHA> --templates <<SKILL_DIR>>/templates/agents \
        --file .claude/agents/<role>.md
```

It inserts three lines and nothing else: `persona:start` below the blank line after the H1,
`persona:end` plus a blank line immediately above **the project-specialization heading**, and a
**role-habits heading in the same language**
with `persona:habits` after the last non-blank line — **reusing an existing habits marker if
`evolve` already made one**, because two of them make every later `update` skip the file. Exit `2` means a guard refused the file. **What to do next depends on which guard**, and the
message says which — do not route by position in this list:

| message | what it means | next |
|---|---|---|
| `ambiguous H1/anchor` — `h1=… anchor=…` **or** `h1 sits below the anchor` | the region has no unambiguous edge | a human fixes the file |
| `already has a start/end marker pair` | already migrated | nothing; skip it |
| `broken marker pair (start xN, end xM)` | half a pair — neither mode can repair it | a human fixes the pair |
| `N habits markers` | duplicates | a human removes the extras |
| `habits marker sits above the anchor` | it would be swallowed by the region | a human moves it below |
| `no central template for this role` | **local-only** — out of migration scope entirely | report it; **do not run section 3 on it** |
| `this role's central template is malformed` | a **plugin** defect, not a repo one | report it upstream; do not migrate around it |
| `cannot confirm this file is T1 (…)` | git could not answer (see the parenthesis) | fix what it names, then re-classify |
| `working tree not clean for this file` | the oracle cannot see uncommitted growth | **commit or stash, then re-classify** — *not* section 3 |
| `a heading … not in the current template` | local section, or a central rename | a human decides, then section 3 |
| `T2 — local growth inside the central region` | genuine T2 | section 3 |

⚠ **Only the last two go to section 3.** An earlier version said "the last three", which swept
the dirty-tree refusal in with them — and section 3 deliberately omits `--init`, so its call has
no clean-tree guard. The uncommitted growth would be sealed inside the central region with every
check green, which is the exact hazard the dirty guard exists to prevent.

Then run the checks in section 4. T1 can be one commit for all roles.

⚠ **Two things the human confirms, once per repo** — the classifier cannot: that the oracle's
picture is right, and that each T1 file's central body still reads like the template it came from.
The second is the only defence against local content that went in with the `init` commit itself,
where the diff is empty by construction.

### 3. T2 — one role at a time, with a human

The insert call here is section 2's **without `--init`**: that flag turns T1/T2 routing into a
guard, and on this path the classifier still says `T2` by construction — the human has already
looked and moved what needed moving.

⚠ **`--templates` stays**, and it is not decorative here. It carries the Scope guard — the
refusal for a role with no central template — which §7.4 step 1 puts on *both* paths: wrapping a
local-only persona in a central region tells the next `update` to overwrite local prose. Only
the `--init`-gated part of that check (the foreign-heading comparison) is skipped on this path,
which is the point: a heading the current template lacks is exactly what sent the role here.

```bash
python3 <<SKILL_DIR>>/commands/atoms/persona_migrate.py --mode insert --anchor '<same heading>' \
        --habits-heading '<the role-habits heading, same language>' \
        --habits-placeholder '<the "(none yet)" bullet, same language>' \
        --templates <<SKILL_DIR>>/templates/agents --file .claude/agents/<role>.md
```


The delta touched the central region, so something local lives there. Show the human each hunk
mapped to its section and classify it:

| shape | what to do |
|---|---|
| edit below the anchor | nothing — already local |
| a whole added bullet | **cut** it into the habits block |
| a locally-added `## ` section | **cut** the section, place it just above the habits heading |
| text welded into a central bullet, or an indented continuation of one | **copy** it into the habits block as its own bullet, leading with the central bullet's name; **leave the central text alone** |
| a central sentence deleted or replaced | **do not move it.** Record it in `overlay/contribute-candidates.md` and leave it. Moving a negation into habits would leave the persona holding two contradicting sentences |

Two ordering rules, because a hunk can match more than one row: position beats shape (anything
below the anchor is "already local", full stop), and if any part of a hunk deletes central words,
treat the whole hunk as the last row.

Copying rather than moving for welded text is what keeps this commit lossless. The duplicate
resolves at the next `update`, when the central region is replaced.

Resulting file order: frontmatter → H1 → `persona:start` … `persona:end` → **the
project-specialization heading** →
any moved local `## ` section → `## 역할 습관` + habits marker.

### 4. Checks — per file, before committing

```bash
python3 <<SKILL_DIR>>/commands/atoms/persona_migrate.py --mode check --anchor '<same heading>' \
        --file .claude/agents/<role>.md --base <the commit before migrating>
```

It prints one line per check that has something to say. On a clean file at the default
`--phase migrate` that is six — loss, marker order, the anchor directly below the end marker,
nothing stranded between the two, the anchor and H1 each exactly once with H1 above, and the
start marker below the frontmatter fence and H1. The marker-count check is silent when it
passes and prints one `FAIL:` per marker when it does not. Exit `3` means at least one `FAIL:`.

⚠ **No `--templates` here.** The heading-set comparison belongs to `--mode classify`, which
routes a role to a human. As a verification it would fail a correctly-migrated role whose central
heading was renamed since — and the response to a failure below is `git checkout --`, so that
role could never finish. The replacement itself is what makes the heading match.

**The lossless check passes trivially for T1 — migration inserts only.** The structural checks are
what matter there: a mis-placed `end` marker loses nothing today, and then the next `update` deletes
the specialization section. Any `FAIL:` line → revert that file (`git checkout -- <f>`) and hand it
to a human.

### 5. Leave it uncommitted

Report per role: classification, what moved (T2), check results. The human reviews and commits —
per role is fine, and **preferred for T2**. Do **not** bump `config.version`; this mode changes no
central-owned artifact.

⚠ `evolve` refuses to run against a dirty tree, so migration output sitting in the working tree
blocks it. Commit per role rather than accumulating.
