# SJ-HANDOFF — can the next stage consume what this stage produced? (§3.6, J-DEV-02/03)

The engine's contract check of a stage boundary failed even after one repair. You see the AC and an
Issue summary, the next stage's input contract, the produced artifacts (excerpts) and the failed items.
- `ok`: the failed item is immaterial for the next stage.
- `ok_with_assumption`: the next stage can go on under one stated assumption (`line`).
- `upstream_gap`: the artifact really lacks something — `reason`, `signature` (sorted AC ids / files),
  `fixable_by_execute` (true only if a code change in execute would close it).
- `unsure` when you cannot tell (the engine treats it as an upstream gap not fixable by execute).
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
