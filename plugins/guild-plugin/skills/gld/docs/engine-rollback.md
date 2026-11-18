# Guild engine — rollback (downgrade) and re-upgrade runbook

Rollback is the **whole plugin version** (0.102.x → 0.101.3), at the scope Guild is installed in — today
**user scope**, per config dir (`~/.claude`, `~/.claude-personal`, … each separately). There is no per-stage
switch; finer control is the engine's soft valves (`dev valve set …`). `E` below =
`python3 <the 0.102 plugin>/skills/gld/engine/gld_engine.py`. Do it **between sprints** when you can.

## Downgrade (0.102 → 0.101.3)

1. **Kill switch first** — `E dev valve halt --all --now` (every repository in this config dir's registry
   `${CLAUDE_CONFIG_DIR:-~/.claude}/guild-engine/repos.json`; a repository outside the registry: run
   `E dev valve halt --now` inside it). `--now` safe-kills every journaled role / judge / suite process group;
   the engine exits 6 and a running supervisor stops at its next pass with `halted:engine-kill-switch`.
   Wait until `E status running --all-repos` shows no lock.
   1b. **Human directives** — `E status directives --open --all-repos`: re-post every still-valid attended
   `dev note` directive as **your own comment** on its Issue (0.101.3 reads human comments, not the engine's
   decision log). The engine never posts them for you.
2. **Install 0.101.3 next to it and disable 0.102** (user scope of the config dir the repository uses). A
   path marketplace's name comes from its `.claude-plugin/marketplace.json`, so build a wrapper:
   ```
   mkdir -p ~/.guild-pins/0.101.3/.claude-plugin ~/.guild-pins/0.101.3/plugins
   git -C <deku-claude-plugins clone> archive guild-plugin--v0.101.3 plugins/guild-plugin | tar -x -C ~/.guild-pins/0.101.3
   # ~/.guild-pins/0.101.3/.claude-plugin/marketplace.json:
   #   {"name": "deku-guild-pin", "plugins": [{"name": "guild-plugin", "source": "./plugins/guild-plugin"}]}
   claude plugin marketplace add ~/.guild-pins/0.101.3 --scope user
   claude plugin disable guild-plugin@deku-claude-plugins --scope user
   claude plugin install guild-plugin@deku-guild-pin --scope user
   ```
   (Two behaviours are confirmed only by the release drill: installing a same-named plugin from a second
   marketplace while the first is disabled, and a path-marketplace name clash.)
3. **Check** — in EVERY path of `git worktree list`: `claude plugin list --json` shows exactly one enabled
   `guild-plugin@*`, version 0.101.3. No `index.lock` left in any worktree (a kill mid-commit: check, then
   delete by hand). `local_dev.py status` shows no running job (wait for it). Keep the worktrees and
   `<git-common-dir>/guild/engine/` (a re-upgrade reads them).
4. **Restart** — restart open Claude sessions; regenerate the supervisor with `/gld sprint run` (0.101.3
   template). Do **not** run `dev valve resume` (0.101.3 never reads `HALT`; clear it at re-upgrade).

What 0.101.3 sees: labels, output markers, loop-back, needs-human, follow-ups and manual-QA records are
byte-compatible. The engine's decision log, journal and judgment cache are ignored; an engine `pending-human`
question is judged again by the legacy flow at that point (on a re-upgrade the engine retires that block as
`superseded`).

## Upgrade / re-upgrade (0.101.x → 0.102)

1. Finish or stop the running 0.101.x sprint.
2. `claude plugin enable` / `install` 0.102 and disable the pin (the reverse of step 2 above).
3. The same check as step 3 (active = 0.102.x in every worktree).
4. **`/gld update` in each repository — it adopts the gate first** (commit it and merge to the default
   branch before any engine run; see update.md "0.102 ordering").
5. Regenerate the supervisor (`/gld sprint run`), then `E dev valve resume --all`, and confirm with
   `E status running --all-repos` that no repository still has `HALT`.

An old (0.101.x) supervisor left running after an upgrade still works through `/gld dev N` (dev.md's
engine driver attaches with `--detach`) but does not see the engine's rate limits or the kill switch —
regenerate it.
