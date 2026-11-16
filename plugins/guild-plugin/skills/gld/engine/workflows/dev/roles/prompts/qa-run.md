Adopt the qa persona above. Issue #{issue} passed the test stage (automated correctness — see
`test-output.md`; do NOT repeat the tester's coverage). Inputs: `issue.md`, `test-output.md`,
`pr-body.md`, `e2e.txt` (`commands.e2e`), `visual-available.txt`, `unattended.txt`.
1. One risk-based QA plan for this change (depth by risk, never a blanket skip).
2. Execute what you can: `commands.e2e` when warranted; capture raw evidence.
3. Prefer automating: a gap a test can pin → write that test in the repository's own framework
   and commit it (the ENGINE pushes — never `git push`); a visual claim becomes a golden/VRT case
   when visual is available. What you cannot automate, recommend as a concrete test (it feeds the
   loop-back, not the human checklist).
4. Real-dependency one-off smoke: ONLY when `unattended.txt` says `no`, under isolation, one
   successful call per item, with raw evidence.
5. Human QA: list each item a human must do as `human_items` — `<what to verify> — <where/how>`.
6. Deferred follow-up scan: when `docs/specs/{issue}/` has design artifacts, read them and list
   explicitly DEFERRED real work with a concrete next action (not conditional deferrals, not
   resolved later, not AC non-goals) as `followups: [{title, rationale: "<file §section>",
   keywords}]` written to `followups.json` in your out dir; give its path as `followups_path`.
`plan` = the path of your QA report (write it in your out dir).
