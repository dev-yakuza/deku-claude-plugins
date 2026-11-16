"""guildcore — the command-independent platform of the Guild issue-flow engine.

Design: `design/guild/23-engine/design.md` §2.0. Rules every module here keeps:

* `guildcore` never imports `workflows.*` — workflow knowledge (stage meaning, judgment groups,
  prompts) lives in the workflow; record grammar, external reads, redaction live here.
* Every module that touches the outside world takes an adapter (gh, clock, filesystem root) so
  tests run against fakes — no network, no `claude`.

Milestone K0: parsers/renderers, state derivation, config, emit (read-only).
Milestone K1: the executor — `adapters.claude` (every `claude -p`), `roles` (settings render,
permission rules, runner, scope check), `judges`, `ask`, `pause`, `journal` (write side),
`worker`, `ratelimit`, `cost`, `capture`, `checks`, and the verified write path
`records.write` + `adapters.gh.GhWriteCli`. Still inert: no command of the plugin calls the
engine, and `gld_engine.py` exposes no `dev` workflow yet (K5 wires the drivers).
"""

ENGINE_MILESTONE = "K1"
