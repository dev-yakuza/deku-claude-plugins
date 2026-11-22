# SJ-AN-PO — what does the product-owner's concern change? (§3.3 AN-PO, J-AN-12, A-F19)

The product-owner returned DONE_WITH_CONCERNS after the readiness gate. You see the concern, the
interpretations and the chosen one, the AC and the Success rating with its anchor.
- `record`: the concern is worth keeping on the record but does not change Success.
- `rerate_success`: the concern shows Success criteria are not settled — give the new `rating`
  (`partial` needs an `anchor` as in KICKOFF; else `unclear`).
- `unsure` when you cannot tell (the engine re-rates Success `unclear`).
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
