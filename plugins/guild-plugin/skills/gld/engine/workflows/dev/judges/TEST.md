# SJ-TEST — does each acceptance criterion have an EFFECTIVE covering test? (§3.3, T-AC-COVER, T-VACUOUS)

The suite already ran green (the engine ran it; the raw output is in the brief). For every AC id:
- `effective` — a cited test exercises the AC's behaviour AND its assertion would fail if that
  behaviour broke (#894: a check skipped in one path passes regardless — that is `vacuous`).
- `vacuous` — a test is cited but asserts nothing meaningful about the AC, or cannot fail.
- `not_covering` — no cited test exercises this AC (a test of something else is not coverage).
- `unsure` — the excerpts do not let you tell.
`covered_by` lists the test references you relied on (copy them from the tester's `covers`).
The brief names the ids to judge ("Judge exactly these ids") — give one `ac[]` entry per id and no other id.
When cases are folded into an AC (`AC #3 (cases C7, C8)`), judge the AC: `effective` only when its cases' behaviour is
covered by effective tests; the tester's covers are already listed under the AC id (`[case C7]`). If you also answer
a case id, your weakest answer for the AC or any of its cases is the AC's verdict. An AC with no cover at all is never
effective (the code makes it a gap); a case no cover names is recorded for grading.
Visual rows: `covered` only when a comparing test that passed is named for that row.
Your `effective` is re-checked by code (an assertion line must exist, and for new behaviour the
test must fail with the implementation reverted) — do not call a test effective on its name alone.
`overall` = `all_effective` only when every AC is `effective`.
Use the Read/Grep tools on the repository when an excerpt is cut short.
An assertion about the SOURCE itself — a file or symbol exists (`File('lib/x.dart').existsSync()`),
a whole-module snapshot equals itself — is `vacuous`: it reacts to deleting code, not to the AC's
behaviour breaking.
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
