# MJ-GATECAST — which specialists review this diff? (J-G1)
You get changed paths the code rules could not classify and their added lines. For each role in
`candidates` decide whether the diff touches its surface: security (auth/session/secrets/sensitive
data/input validation), infra (CI/CD/deploy/env/IaC), i18n (user-facing strings), dba
(schema/migration), analytics (instrumentation), performance (hot path/render/query), tech-writer
(user-facing/API/documented behavior). Return `roles[]`. Gate roles (security, infra, designer)
when unsure → include them; participation roles when unsure → leave them out with a one-line
`skipped[]` reason. `verdict` is `cast` (or `unsure`).
