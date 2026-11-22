# SJ-QA — real blocking defects, fixability, the human checklist, the quality bar (§3.3, Q-DEFECT, Q-FIXABLE, Q-CHECKLIST)

From the qa report, the designer verdict, the quality bar, the AC and the test output:
- `defects`: only REAL defects the change introduced or left (a concern, a recommendation, an
  automatable test gap is not a defect). `blocking` = done must not be declared with it.
  `fixable_in_code`: `yes` = a code change in this Issue fixes it; `no` = it needs a product /
  requirement decision or an external party; `unsure` when you cannot tell (the engine sends it to
  a human).
- `checklist`: each item a human MUST do at the PR, phrased as an instruction
  `<what to verify> — <where/how>`. Never use 권장, 가능하면, 여유되면, 미검증(참고) or similar
  hedges inside an item. Leave out what the tests prove, what qa already ran with evidence, and
  test-writable gaps.
- `quality_bar_met`: `yes` | `no` | `unsure` against the quality bar excerpt.
- `verdict`: `pass` (no blocking defect, quality bar met) | `block` | `unsure`.
- `same_as`: when a defect is the SAME defect an earlier QA loop-back recorded (listed in the brief
  with its signature elements), copy that element here; otherwise leave it null.
`security_concern` (required, true|false) with `security_reason` (one short line, any language): `true` when
what you judge here carries a security ISSUE — a vulnerability (injection into SQL / a shell / HTML, XSS, CSRF,
SSRF, a known CVE), a secret or credential exposed (an API key, token, password or private key written to a log,
to analytics, committed, hard-coded, stored or sent unencrypted / in plain text), an authentication or
authorization bypass (a missing permission check, an endpoint reachable without auth), or a leak of users'
personal data. It is NOT a security issue that the Issue builds or touches an auth / security FEATURE (login,
logout, a 401 / unauthenticated redirect, a token kept in the keychain / secure storage, encryption added),
nor a non-security defect that shares a word (dependency injection, a memory leak). Read the inputs in whatever
language they are written. Doubt → `true` (a person decides it); the engine reads a missing value as `true`.
