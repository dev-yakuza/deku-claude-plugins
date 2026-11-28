# CHANNEL — the repository's active Guild channel (`/gld channel <channel>`)

**One repository uses one Guild channel at a time** (user decision R4-14): the stable channel or this experimental
one. The active one is written in `.claude/guild-channel` at the top of the repository (one line, the channel's
command name; committed, so every clone and machine agree). Every command of the channel that is not active is
refused (`SKILL.md` routing and the engine's write commands); this command switches.

`$1` = the target channel: this channel `gld`, or the stable one (the name `engine.py channel show --json` prints as
`other`). Empty `$1` → only show the verdict (step 2 alone) and stop.

> **Bash**: one command per Bash call (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`).

1. Resolve `owner/repo` (its own Bash call) and hold the literal value:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   ```
2. Show where the repository stands (read only):
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py channel show
   ```
3. **Dry run** — what the switch would change, nothing written:
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py channel set $1 --repo OWNER/REPO --dry-run
   ```
   - **exit 4** `refused: the <channel> channel still has engine runs of OWNER/REPO on this machine …` → show the
     line as it is (it lists each Issue / sprint and why it is not finished) and stop: those runs finish or stop
     with that channel first. Nothing was changed.
   - **exit 4** `refused: … is not a git checkout` / `the hook detector gave no answer …` → show it and stop.
   - **exit 0** `would switch: …` → show every line to the human: the channel file, and what happens to the commit
     gate — the pre-commit hook gets the target channel's shim (a hand-written hook moves to `pre-commit.local`
     and still runs first), or the hook manager's registered `guild-gate` command (lefthook, husky, pre-commit) is
     pointed at the target channel's gate script, or a line saying the human registers it by hand.
4. **Ask** (`AskUserQuestion`): switch this repository to `$1` — yes / no. **Unattended** (`GLD_UNATTENDED=1`): never
   switch — a channel is a human's choice; report the dry run and stop.
5. On yes, switch — outside the conversation's sandbox, as `commands/engine/dev.md` step 1.3 (it writes the git
   hook):
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py channel set $1 --repo OWNER/REPO
   ```
   Exit 0 → show its lines. It ends with `commit .claude/guild-channel (and a changed hook config) …`: offer that
   commit (`git add .claude/guild-channel` plus the hook config file the output names, then `git commit -m "chore:
   use the $1 Guild channel"` — each its own Bash call, only after the human agrees; never push). When the
   repository's `.gitignore` hid the file, the switch added `!.claude/guild-channel` to it (line `… added
   \`!.claude/guild-channel\` to .gitignore`) — add `.gitignore` to that commit too. A line `… does not bring it back`
   means the repository ignores the whole `.claude/` folder: .gitignore was left as it was — show the line, the
   human changes it. Exit 4 → show the `refused:` line; nothing was changed.
6. Tell the human what follows: from now on this repository answers only to the `$1` commands. The machine-wide
   heavy-run lock is NOT shared by the two channels — do not run unattended work of both channels on this machine
   at the same time (a human rule until a shared lock exists).
