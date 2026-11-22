# L0-SPLIT — is this a genuine multi-PR split? (§3.2 G-SPLIT, J-DE-05, A-F22/23)

The tech-lead's `split.json` proposes splitting this Issue into child Issues. You see it, the parent
AC, the existing children (number, title, slice key) and the skeleton's split section.
- `single`: one PR is fine (most Issues).
- `split`: independently deliverable slices, each its own PR + tests. Every parent AC id must belong
  to some slice (`ac_ids`); `key` is a short stable slug (`[a-z0-9-]`), `order` the dependency order.
  Slices whose key matches an existing child are listed too (they are not created again).
- `unsure` when you cannot tell — a split is hard to undo, so the engine asks a person.
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
