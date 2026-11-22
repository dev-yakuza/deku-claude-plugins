# SJ-VIS-ENV — environment suspect or regression? (§3.3, J-V3, T-VISUAL-ENV, H§L.5)

The code pre-filter could not decide. A visual failure is an environment suspect when the images
fail with uniform anti-aliasing / font-hinting noise on screens this change could not reach.
A failure on an image whose screen the diff does reach is a `regression` until shown otherwise.
`unsure` sends it to a human as an environment question.
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
