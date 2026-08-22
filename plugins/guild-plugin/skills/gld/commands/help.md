# /gld help

**Resolve the installed plugin version first** (its own Read call — do NOT hardcode a version string below): Read `<<SKILL_DIR>>/../../.claude-plugin/plugin.json` and take its `version` field; substitute it for `<PLUGIN_VERSION>` below. A hardcoded literal here goes stale the moment the plugin ships a new version.

Print the following usage overview to the user (adapt formatting to the terminal).

```
Guild (/gld) — a self-evolving agent organization for your repo.
Codebase, agent team, AND you (the overseer) co-evolve.

In this version (<PLUGIN_VERSION>)
  Spine        analyze → design → execute → test → qa, run by per-repo role agents
               (leader convenes specialists by risk) + mid-execute resume
  Intake       plan: a design-doc or epic → a dependency-ordered dev-unit backlog
  Outer loop   evolve (HITL apply) · audit · contribute/update (central↔repo)
               · sprint (readiness-gated) · multi-PR child orchestration
  Memory       ⑥ knowledge · ④ working memory (evolve consolidates) · agent↔agent
               capture · ② standards lifecycle (drift sync + draft→confirmed)
  Enforcement  commit gate (below) · rule lifecycle: gate firing-log → evolve rule
               scorecard → demote/retire (core secret/verification gates exempt)
  For you      ③ human-growth engine (onboard + WHY-teaching in review/evolve/dev)
               · qa Manual Test Checklist in the PR body (automation-impossible only)
  Guards       adversarial review · data-sufficiency gate (evolve blocks on thin
               data · audit banner · review→evolve nudge)

Commit gate (deterministic enforcement layer)
  Authoritative  .git/hooks/pre-commit — blocks a commit carrying a secret or
                 weakening verification (stack-specific rules start draft = warn only)
  Early warning  PreToolUse(Bash) — the same check before the command runs
  Self-guard     PreToolUse(Edit|Write) — asks before its own off-switch/rules are edited
  Managed repo   if lefthook/husky/pre-commit owns the hook, Guild registers itself as
                 one of their commands instead of taking the file over (their config is
                 committed, so the gate then travels with a clone)
  Limits         `git commit --no-verify` skips it · on the unmanaged path `.git/hooks/`
                 is untracked, so a fresh clone needs `/gld update`
  Off-switch     /gld config --gates=off  ·  health check: /gld audit harness

Setup
  /gld init [lang]        Analyze & onboard → harness + Guild (agents) + standards + readiness audit (gaps → guild:harness issues) (one-time)
  /gld config [flags]     Show / adjust Guild settings — --language=<code> | --gates=<on|off> (commit gate) | --evolve-nudge=<on|off> (the review-stage "run evolve" reminder)
  /gld update [--check]   Adopt newer central Guild improvements, preserving local evolution (also reinstalls the git hook after a fresh clone)

Develop (spine: analyze → design → execute → test → qa)
  /gld plan <doc|issue>   Intake (upstream of the spine): decompose a design-doc FILE or an epic ISSUE into a dependency-ordered dev-unit backlog. Default dry-run; --create to make the issues (file → flat + area labels; issue → children under it for /gld dev orchestration)
  /gld dev <issue>        Run the full flow on a GitHub Issue (auto-selects execute variant; leader convenes specialists by risk)
  /gld analyze <issue>    Stage 1: requirements (What/Why)
  /gld design <issue>     Stage 2: design (How) — tech-lead skeleton, tester drafts test cases
  /gld implement <issue>  Stage 3 execute variant (feature): TDD red→green→refactor
  /gld debug <issue>      Stage 3 execute variant (bug): reproduce → root-cause → fix + regression test
  /gld refactor <issue>   Stage 3 execute variant (refactor): behavior-preserving transform (existing tests stay green)
  /gld test <issue>       Stage 4: automated correctness (verify gate)
  /gld qa <issue>         Stage 5: holistic quality (exploratory/E2E/user-flow, risk-based)
  /gld review <issue|pr>  Guided pair-programming walkthrough of the PR (pass the issue number — auto-resolves its PR — or a PR number directly) (+ adversarial pre-scan: fresh external auditor on Standards/Spec axes) — one change-unit at a time, explains why, pauses to discuss
  /gld resume <issue>     Auto-detect stage and continue
  /gld status <issue>     Show current progress
  /gld batch [issues]     Run many Issues unattended to guild:done (PR open), auto-resumes on rate limit; leader stands in at gates, human reviews PRs after
  /gld sprint [issues]    Autonomous Inner+Outer loop — LOCKED until readiness is earned by measurement (use batch until then). --readiness shows the score

Diagnose & grow (Outer Loop)
  /gld audit [dim]        Read-only health check — grades harness+team+codebase, routes to evolve (dev weakness) / refactor (codebase). Makes no changes. dim = harness | team | knowledge | standards | evolution | codebase (empty = all)
  /gld evolve [--dry-run|--apply]  Grow the Guild: scan traces → rank → adversarial panel → per-item approval → apply (backup·auto-rollback·provenance·ledger). --dry-run = propose only (no changes)
  /gld contribute         Upstream a proven flow improvement to the central plugin (sanitize · dedup · human review before send)

On-demand & observe
  /gld rollback <target>  Safely undo a Guild change (git revert / close PR / reset stage) — non-destructive, confirms first
  /gld ask <question>     Cited Q&A over standards + ⑥ knowledge (no guessing)
  /gld onboard [area]     Guided, paced tour of the codebase for a human — teaches the WHY/principles from standards + ⑥ knowledge + hotspots, one stop per turn (ramps a new maintainer)
  /gld monitoring [section] [--html]  Terminal snapshot: org · ⑥/④ status · evolution history · gates · active work. section = org|knowledge|gates|work|evolution|standards; --html also writes a self-contained dashboard file

  /gld help               This help
```

After printing, if the current repo has no `.claude/guild/` directory, add one line: "This repo is not initialized yet — run `/gld init` to set up Guild."
