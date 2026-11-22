# L0-INTEGRATE — do the children add up to the parent? (§3.2 G-INTEGRATE, J-DEV-07/08, A-F9/10)

Every child of this split parent is done. You see the parent AC and design output, the roster, each
child's PR / test output / closed-as-decided or human-merged flag and the tech-lead's
`coverage.json`. You may Read/Grep the repository.
- `coverage`: each parent AC → the child that satisfies it (`#n`), `결정대로 닫힘`, or `gap`.
- `gaps[]`: `kind` coverage | consistency (seams, data shapes, interfaces disagree; duplicated or
  orphaned work) | dod | slicing (the split itself caused it); `child_to_fix` when one child's PR
  would fix it; `needs_decision` when a person must choose.
- `verdict`: `clean` | `gap` | `unsure` (the engine treats unsure as a gap that needs a decision).
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
