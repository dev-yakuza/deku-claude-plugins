# /gld help

Print the following usage overview to the user (adapt formatting to the terminal).

```
Guild (/gld) — a self-evolving agent organization for your repo.
Codebase and agent team co-evolve. This version (0.1.0 / M1): bootstrap + dev flow, advisory harness.

Setup
  /gld init [lang]        Analyze & onboard → harness + Guild (agents) + standards + readiness audit (gaps → guild:harness issues) (one-time)
  /gld config             Show / adjust Guild settings

Develop (spine: analyze → design → execute → test)
  /gld dev <issue>        Run the full flow on a GitHub Issue (auto-selects execute variant)
  /gld analyze <issue>    Stage 1: requirements (What/Why)
  /gld design <issue>     Stage 2: design (How) — architect skeleton, tester drafts test cases
  /gld implement <issue>  Stage 3: TDD implementation (execute variant: feature)
  /gld test <issue>       Stage 4: verify with fresh evidence
  /gld review <issue>     Guided pair-programming walkthrough of the PR — one change-unit at a time, explains why, pauses to discuss
  /gld resume <issue>     Auto-detect stage and continue
  /gld status <issue>     Show current progress

  /gld help               This help

Planned (later milestones): debug, refactor, evolve (growth loop), audit,
rollback, ask, monitoring, update, contribute, sprint.
```

After printing, if the current repo has no `.claude/guild/` directory, add one line: "This repo is not initialized yet — run `/gld init` to set up Guild."
