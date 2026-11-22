# SJ-DIRECTIVE — do the human directives in scope change this stop? (§3.3, J-H1, Q-DIRECTIVE, H§M)

The engine is about to stop out of habit (PR CI, visual environment). Below are the unmarked
comments a human wrote in scope (this Issue, its open sprint trackers, a child's parent), whole.
- `applies`: directives that tell Guild what to do about THIS stop (quote the line).
- `out_of_scope`: directives that seem to apply but ask for something outside this stop's choices.
- `verdict`: `applies` | `none` | `out_of_scope` | `unsure`.
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
