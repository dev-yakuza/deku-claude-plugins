# /gld help

Print the following usage overview to the user (adapt formatting to the terminal).

```
Guild (/gld) — a self-evolving agent organization for your repo.
Codebase and agent team co-evolve. This version (0.16.0): all §3 commands — M1–M4 + evolve HITL apply + contribute/update (central↔repo) + sprint (readiness-gated) + ⑥ knowledge · agent↔agent capture · audit · commit gate · adversarial review · multi-PR child orchestration.

Setup
  /gld init [lang]        Analyze & onboard → harness + Guild (agents) + standards + readiness audit (gaps → guild:harness issues) (one-time)
  /gld config             Show / adjust Guild settings
  /gld update [--check]   Adopt newer central Guild improvements, preserving local evolution

Develop (spine: analyze → design → execute → test → qa)
  /gld dev <issue>        Run the full flow on a GitHub Issue (auto-selects execute variant; leader convenes specialists by risk)
  /gld analyze <issue>    Stage 1: requirements (What/Why)
  /gld design <issue>     Stage 2: design (How) — tech-lead skeleton, tester drafts test cases
  /gld implement <issue>  Stage 3 execute variant (feature): TDD red→green→refactor
  /gld debug <issue>      Stage 3 execute variant (bug): reproduce → root-cause → fix + regression test
  /gld refactor <issue>   Stage 3 execute variant (refactor): behavior-preserving transform (existing tests stay green)
  /gld test <issue>       Stage 4: automated correctness (verify gate)
  /gld qa <issue>         Stage 5: holistic quality (exploratory/E2E/user-flow, risk-based)
  /gld review <issue>     Guided pair-programming walkthrough of the PR (+ adversarial pre-scan: fresh external auditor on Standards/Spec axes) — one change-unit at a time, explains why, pauses to discuss
  /gld resume <issue>     Auto-detect stage and continue
  /gld status <issue>     Show current progress
  /gld batch [issues]     Run many Issues unattended to guild:done (PR open), auto-resumes on rate limit; leader stands in at gates, human reviews PRs after
  /gld sprint [issues]    Autonomous Inner+Outer loop — LOCKED until readiness is earned by measurement (use batch until then). --readiness shows the score

Diagnose & grow (Outer Loop)
  /gld audit [dim]        Read-only health check — grades harness+team+codebase, routes to evolve (dev weakness) / refactor (codebase). Makes no changes
  /gld evolve [--dry-run|--apply]  Grow the Guild: scan traces → rank → adversarial panel → per-item approval → apply (backup·auto-rollback·provenance·ledger). --dry-run = propose only (no changes)
  /gld contribute         Upstream a proven flow improvement to the central plugin (sanitize · dedup · human review before send)

On-demand & observe
  /gld rollback <target>  Safely undo a Guild change (git revert / close PR / reset stage) — non-destructive, confirms first
  /gld ask <question>     Cited Q&A over standards + ⑥ knowledge (no guessing)
  /gld monitoring         Terminal snapshot: org · ⑥/④ status · evolution history · gates · active work

  /gld help               This help
```

After printing, if the current repo has no `.claude/guild/` directory, add one line: "This repo is not initialized yet — run `/gld init` to set up Guild."
