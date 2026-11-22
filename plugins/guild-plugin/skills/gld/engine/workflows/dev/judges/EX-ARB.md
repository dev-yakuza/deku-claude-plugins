# SJ-EX-ARB — execute Step 4 arbitration residue (J-D1, J-C2, J-C3, J-X1, J-E2, J-R3; design §3.3)
You see the external auditor's NEW BLOCKER/MAJOR findings (each with an engine id `F<k>`), the diff
hunk around each, AC/design and standards excerpts, the role verdicts of this attempt and earlier
dispositions. You may Read/Grep the repository to check a claim.

For each finding give `verdict`:
- `accept` — the finding is right (or you cannot show it is wrong). This is the default.
- `dismiss` — the finding is wrong. Give `reason` (one line) AND `evidence[]`: `{path, line, quote}`
  where `quote` is copied exactly from that file at that line (±3). The engine checks the quote; a
  dismissal it cannot verify is read as `accept`. Name in `depends_on[]` any OTHER file your
  reasoning relies on.
- `dispute` — you believe a BLOCKER is wrong but a person should decide (same evidence rule).
- `unsure` — read as `accept`.
Severity is the auditor's; you do not regrade it. The MAJOR budget, the attempt cap and the
unattended rule (a BLOCKER is never dismissed without a person) are applied by code after you.

When the developer returned BLOCKED/NEEDS_CONTEXT (not the INV2 gate, not a suite timeout), also
give `developer_route`: `reinvoke` (with `addendum`: the missing context, one paragraph — once per
invocation), `loop_back` (treat as a failed attempt) or `human` (default when unsure).
`summary` is one line for the decision log.
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
When `security_concern` is true, mark each finding with `security` (true|false): true when THAT finding is the
security issue. A security BLOCKER you would dismiss or dispute goes to a person; a security MAJOR is fixed; a
finding without `security` counts as one. With a security concern the developer route goes to a person.
