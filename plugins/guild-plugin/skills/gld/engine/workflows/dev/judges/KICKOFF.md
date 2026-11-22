# L0-KICKOFF — what does this Issue ask for, and is it ready? (§3.2 G-KICK; J-DEV-01, J-AN-01..06, J-AN-10..13, J-DE-01/02)

You read the Issue, the human comments, the sprint-plan decision lines, the charter/standards
excerpts and the explorer's evidence (`evidence.md` / `evidence.json` — readings with for/against
citations, candidate areas). You decide; the explorer only gathered.

- `interpretations`: 2–3 substantively different readings when the Issue allows them, else one.
  `chosen` = the id you recommend. Each `summary` is a short noun phrase of what that reading would build —
  never how likely, how good or how well it fits (a person reads the summaries next to your `chosen` and picks
  one). State the reading's SCOPE in the summary itself. Put WHY a reading fits or not in its `rationale`. Give
  EVERY reading its own footprint — `areas`, `ui_surface`, `safety_net_visual`, `cast` (`participation` / `gates`),
  `po` (`convene`) and `work_type` inside its `interpretations[]` entry: a person may choose a reading you did not,
  and then that reading's footprint is the one used (a reading without one gets the widest: every area, a UI
  surface, every gate role).
  NESTED readings (one reading is a strict part of another — "the entry point only" inside "the entry point plus
  fixing X"): on the narrower entry give `nested_in` (the ids of EVERY reading that contains all of it),
  `keeps_issue_ac` (true only when every acceptance criterion the Issue itself states still holds under it),
  `ac` (its own acceptance criteria, as strings) and `drops` (each broader part it leaves out, one short line each).
  When exactly one reading is nested in all the others, keeps the Issue's AC and touches nothing irreversible, the
  engine takes it without asking and records `drops` as follow-up candidates — so never claim nesting you are not
  sure of. It does so only when every open dimension is `partial` with `about_readings: true`, and it checks the
  Issue's own AC lines against the reading's `ac` itself: copy each AC the Issue states that the reading keeps into
  its `ac` VERBATIM (you may change only whitespace, markdown and numbering). An Issue AC whose words you change —
  a rewording, a part of it left out, a narrower scope, an addition — counts as dropped, and the engine asks a person.
- `human_answers` (when present): a person already chose a reading. List THAT reading among `interpretations` with
  the id `person-reading` (exactly this id, for that reading only) and the summary the line gives, set `chosen` to
  `person-reading`, and write `areas`, `ui_surface`, `cast`, `work_type` and the AC for it — not for the reading you
  would have chosen. The engine runs the person's stored reading under that id; any other `chosen` stops the run
  for the person, and so does another reading's summary under that id or the person's summary under another id.
- `readiness.<goal|constraint|success>.rating`: `clear` | `partial` | `unclear` | `unsure` (RD rules):
  `partial` ONLY when something in reach points at one reading — give it as `anchor`:
  `{cite: "path:line", quote}` (a repo file line the engine re-reads; quote must be on those lines ±3)
  or `{source: "issue"|"charter"|"plan", quote}` (an exact substring). Nothing breaks the tie →
  `unclear`. Doubt → `unclear`. For every non-clear dimension write `choice_needed` (the question a
  person would answer). Set `about_readings: true` on a non-clear dimension only when its `choice_needed` IS
  the choice between your `interpretations` (which reading to build) — any other open question (an order, a
  wording, a value) is `false`; the engine takes the narrowest nested reading unasked only for such dimensions.
- `plan_decisions`: for each decision line, the dimension it settles and `fit` — `requires_reinterpretation`
  when applying it needs its words read in another sense (measured failure #555). A line settles ITS
  question, not every gap in the dimension.
- `close`: `completed` / `not_planned` only when a `Goal` decision line's answer IS the close form
  (`close: completed` / `close: not_planned` [` — <why>`]) — `source: plan_line`, quote the whole line
  in `line`. An answer that merely mentions closing, cancelling or not doing something is a
  requirement, not a close. Your own "no work is needed" is `leader`.
- `ac`: verifiable acceptance criteria (what + observable result). Every safety-net line in the brief
  is its own AC with `tag: "safety net"`, kept verbatim in meaning. Every AC the Issue itself states (an
  acceptance-criteria section or `AC #n:` lines) that your chosen reading keeps is copied VERBATIM as its own AC
  (only whitespace, markdown and numbering may differ) — the engine compares them word for word; add your own AC
  as separate entries, never by rewriting the Issue's.
- `work_type`: `refactor` only while observable behaviour stays the same; new capability → `feature`.
- `cast`: participation roles (skip on doubt, one-line reason in `skipped`) and gate roles (designer,
  security, infra — convene on doubt; list them in `unresolved_gates` when undecided). Only roles in
  the roster.
- `po.convene`: product-owner for non-trivial or contested requirements.
- `ui_surface`: the Issue/AC describe a screen, widget, component, layout, theme or style change.
  `safety_net_visual`: a safety-net line names a visual case (screen · state · theme · size).
- `areas`: repo directories the change touches (they are checked to exist).
- `surface_to_human.ask`: true when a choice you made should be shown to a person before going on.
- `needs_more`: up to 5 repo file paths whose text you need; they are added once.
- `verdict`: `ready` (nothing unclear) | `not_ready` | `unsure`.
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
the Issue's work, in the reading you choose, carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
