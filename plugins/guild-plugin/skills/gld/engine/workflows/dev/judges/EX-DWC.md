# SJ-EX-DWC — do these concerns send the work back? (user decision, K3r1)
The developer, tech-lead or a gate finished with DONE_WITH_CONCERNS; nothing else blocks this attempt.
Read each concern against the Issue's test cases. `loop_back` only when a concern names a real defect
or an uncovered acceptance case that the developer can fix now (another attempt is worth its cost).
Style, naming, optional hardening, follow-up ideas and anything already recorded elsewhere →
`proceed` (the concern is printed on the PR for the human reviewer). `unsure` → proceed.
`reason` is one line for the decision log.
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
