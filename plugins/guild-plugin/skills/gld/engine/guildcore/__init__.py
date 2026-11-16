"""guildcore — the command-independent platform of the Guild issue-flow engine.

Design: `design/guild/23-engine/design.md` §2.0. Rules every module here keeps:

* `guildcore` never imports `workflows.*` — workflow knowledge (stage meaning, judgment groups,
  prompts) lives in the workflow; record grammar, external reads, redaction live here.
* Every module that touches the outside world takes an adapter (gh, clock, filesystem root) so
  tests run against fakes — no network, no `claude`.

Milestone K0 is READ-ONLY: parsers/renderers, state derivation, config, emit. Nothing in this
package writes to GitHub or spawns a role; the renderers produce text that K1+ writers will post.
"""

ENGINE_MILESTONE = "K0"
