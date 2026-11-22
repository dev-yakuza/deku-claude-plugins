# SJ-DE-ARB — a design role is blocked: what now? (§3.3 DE-ARB, J-DE-03, J-DE-04, A-F24/25)

A design-stage role (tech-lead skeleton, tester cases, a specialist) returned BLOCKED or
NEEDS_CONTEXT, or its output failed the hand-over check after one repair. You see its line, its
artifact (if any), the analyze output and what context exists.
- `reinvoke`: you can supply the missing context — `role` and a short `addendum` (the engine allows
  ONE re-invocation per role per stage).
- `decide`: a low-stakes design choice you can make — state it as `assumption` (unattended this is
  checked by a separate stakes judgment first).
- `escalate`: `reason` = `executor_conflict` (two roles' outputs contradict, e.g. existing split slices
  conflict) or `cross_stage` (the analysis itself must change); give `question` and `options`.
- `pause`: genuinely blocked — `cause` one line.
- `unsure` when you cannot tell (the engine pauses).
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
