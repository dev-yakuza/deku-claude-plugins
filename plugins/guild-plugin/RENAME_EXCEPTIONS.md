# Channel names — rename exceptions and promote tags

Guild ships in two channels made from one source. The development channel is the only source; the stable channel
is `tools/promote/promote.py build`'s copy of it with the channel names swapped (readiness T4, R4-2) and is never
edited by hand. This tree's names: plugin `guild-plugin`, skill `/gld` (`skills/gld/`), labels `guild:`, markers
`<!-- guild:… -->`, settings `.claude/guild/`, branches `gld/<N>`, worktrees `.gld-<repo>-<N>`, engine home `~/.gld`,
engine variables `GLD_ENGINE_HOME`, `GLD_SRT_BIN`, ….
The other channel's names: plugin `guild-exp`, skill `/gldx`, labels `gx:`, settings `.claude/guild-exp/`, branches `gx/<N>`, worktrees `.gldx-<repo>-<N>`, engine home `~/.gldx`, engine variables `GX_ENGINE_HOME`, `GX_SRT_BIN`, …. <!-- promote: other -->

The full table (and the few names that are internal and stay the same in both channels: the package `gxengine`, the
`gx-…` scratch names, `/tmp/gx-…` srt folders, the commands' `GLD_UNATTENDED` / `GLD_SPRINT_*` / `GLD_ALLOW_SKIP`) is
`RULES` in `tools/promote/promote.py`.

## The rule and the check

This tree names the other channel **only on purpose** — as something to refuse, to switch to, or to tell apart — and
each such line carries a tag. `tests/rename_test.sh` runs `promote.py check-names` (Python regular expressions; the
old `grep -P` check did not run on macOS's BSD grep and passed without checking anything):

- a line that names the other channel without a `promote: other` / `promote: literal` tag fails;
- a spelling of this channel's name that no promote rule renames fails (it would survive into the other channel);
- every file holding a `rename-exception` tag must be listed below.

## Tags

A tag is a comment on the line: `# promote: <kind>` in code and shell, `<!-- promote: <kind> -->` at the end of a
Markdown line. The U0 tag `rename-exception: <why>` may follow in the same comment; it is now only the reason.

| Kind | Meaning | Promotion |
|---|---|---|
| (none) = `self` | this channel's names | renamed to the other channel's |
| `other` | the other channel named on purpose (a refusal, the channel switch, a test of them) | every channel name on the line is swapped — the promoted tree names this channel there |
| `literal` | a name that means the same thing in both trees: a Guild 0.98.7 path or marker, a table keyed by channel names | the line is copied as it is |
| `literal-begin` … `literal-end` | the same for a block (the promote tool's own name table) | copied as it is |

Without a comment: the shared paths `.claude/guild/knowledge` (K2) and `.claude/guild-channel` are never renamed on any
line (`GLOBAL_LITERALS`); a file that cannot carry a comment (JSON, a code fence) is listed in `FILE_KINDS` /
`FILE_LITERALS` of the promote tool.

## Files with `rename-exception` tags

| Where | Other-channel / 0.98.7 name | Why |
|---|---|---|
| `skills/gld/commands/dev.md` Phase 0 step 1a, `skills/gld/commands/resume.md` step 1a (`promote: other`) | the other channel's stage labels | Refusal: an Issue carrying the other channel's label belongs to that channel; this one stops without touching labels or comments. (Design §9.1 "겹침 방지") |
| `skills/gld/engine/data/roles/requirements-engineer.md` (`promote: other`) | the other channel's safety-net markers | The role reads both channels' plan markers in an Issue body. |
| `skills/gld/engine/gxengine/channel.py` (`promote: other` / `literal`) | the other channel's settings folder, engine home, the channel-value table | Readiness T1 R4-14: one channel per repository; the switch reads the other channel's settings folder to see whether both channels are set up and points the commit gate at that channel's gate script. |
| `skills/gld/engine/tools/convert_config.py` (`literal`), `skills/gld/engine/tests/test_initconfig.py`, `skills/gld/engine/tests/test_globs.py` (`literal`) | the Guild 0.98.x settings file (`convert_config.STABLE_CONFIG`), its folder, its gate record | The settings converter reads the 0.98.x file where 0.98.x keeps it — the same path in both trees. In the promoted tree it is the stable channel's own folder (the first promotion's collision, R4-13). |
| `tests/persona_migrate_test.sh` (`literal`) | the pre-rename release's plugin folder and its old persona markers | Rebuilds role files from a release older than the rename (`PREV_REF`). |
| `skills/gld/engine/gxengine/defaults.py`, `skills/gld/commands/atoms/harness_size.py`, `tests/harness_size_test.sh`, `skills/gld/commands/atoms/_knowledge.md`, `skills/gld/commands/atoms/_preflight.md`, `skills/gld/commands/ask.md`, `skills/gld/commands/audit.md`, `skills/gld/commands/onboard.md`, `skills/gld/commands/update.md`, `skills/gld/commands/evolve.md`, `skills/gld/commands/init.md`, `skills/gld/templates/CLAUDE.md.tmpl`, `skills/gld/templates/standards/architecture.md` | `.claude/guild/knowledge` | Readiness T2 R4-13 K2: the ⑥ knowledge folder is ONE folder both channels read (only the stable channel writes it — channel value `writes_knowledge`). The promote tool keeps the path on every line (a global literal); lines that also name this channel are tagged `promote: self`. The role frames get it from `defaults.KNOWLEDGE_DIR`. |
| `RENAME_EXCEPTIONS.md`, `tests/rename_test.sh` | — | They define the list. |

Other `promote: other` / `literal` lines without a `rename-exception` reason are tests of the lines above (the label
refusal, the channel switch, the 0.98.x converter, the channel-value table) and the analyzer fixtures of
`tests/analyze_tool_test.sh` (Guild 0.98.7's own log format).

## Left for later units (memo — behaviour unchanged by U0)

- **U15 — role files.** `init.md` writes `.claude/agents/*.md` only when the channel value
  `writes_role_files` is on (readiness T2 R4-3: the stable channel; `engine.py init roles`).
  `update.md`, `evolve.md` and `atoms/persona_migrate.py` still write them (stable-owned). Design §9.1: the
  development channel only READS them until stage 6. Each carries a `U0 note → U15` line. A role file written by
  Guild 0.98.7 carries the old persona markers, so this channel's persona checks (monitoring/audit) do not recognise
  those habits sections until U15 decides how to read them.
- **Environment variables of the commands** (`GLD_UNATTENDED`, `GLD_SPRINT_*`, `GLD_ALLOW_SKIP`, …) keep their names in
  both channels; a stable and an experimental run in the same shell tree would share them.
- **Plugin/marketplace.** The development channel is a local install; `.claude-plugin/marketplace.json` has no entry
  for it. The README install line is the public marketplace's (kept by the promote tool, `FILE_LITERALS`).
- **Also renamed (beyond the label/marker/path list):** repo-parent worktree containers and scratch names
  (`.gld-<repo>-…`, `.gld-sprint-…`, `/tmp/gld-…`) so the two channels cannot collide or be mistaken for each other
  in `ps` / `git worktree list`.
