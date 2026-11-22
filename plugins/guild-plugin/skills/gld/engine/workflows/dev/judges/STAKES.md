# SJ-STAKES — how costly is guessing here? (§3.2, J-AN-07, H§H:550–563)

One open question of one Issue. You see the question, the options, the option a judgment is about to
take (without its reasons), the Issue body, the explorer's evidence for the touched areas and the
paths the engine marked irreversible.
- `low` / `medium`: a wrong guess stays local and is cheap to undo — give `local_reversible_reason`
  (why it is local AND reversible) and `cites`.
- `high`: scope-defining, a materially different product, or hard to reverse.
- `unsure` when you cannot tell. Doubt is `high`.
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
