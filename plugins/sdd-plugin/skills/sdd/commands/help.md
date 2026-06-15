# HELP

> **Source of truth**: the canonical command list is the `Valid commands` line in `<<SKILL_DIR>>/SKILL.md` (Routing). Keep the list below in sync with it. For v1.0.0 this is documented (not auto-generated); a release-time CI check is planned.

```
SDD (Spec-Driven Development) - AI Collaborative Development Process

Generated from SKILL.md command routing.

Commands:
  /sdd init [lang]       Set up SDD for the current repository (Issue templates, labels)
                         Languages: en (default), ko/korean/한국어, ja/japanese/日本語
  /sdd analyze <issue>   Stage 1: Requirements Analysis (What/Why)
  /sdd design <issue>    Stage 2: Design (How)
  /sdd implement <issue> Stage 3: Implementation with TDD (Red → Green → Refactor)
  /sdd test <issue>      Stage 4: E2E and QA Testing
  /sdd resume <issue>    Auto-detect current stage and continue from where it left off
  /sdd status <issue>    Check current progress                            (read-only)
  /sdd review <issue>    Re-run AI review on current stage output          (read-only)
  /sdd rollback <issue> <stage>  Roll back to a previous stage (analyze, design, implement)
  /sdd config            Show or update SDD settings (e.g., skip-review)
  /sdd auto [issues]     In-session sequential processing (Interactive billing pool;
                         keep this Claude Code session open during the run)
                         No args = all open; "1,2,3" = specific issues
  /sdd batch [issues]    Unattended shell processing via separate claude -p sessions
                         (uses Agent SDK Credit pool from 2026-06-15)
                         No args = all open; "1,2,3" = specific issues
  /sdd help              Show this help message

Workflow:
  1. /sdd init [lang]       → set up repository (choose language for templates)
  2. Create an Issue using SDD templates
  3. /sdd analyze <issue>   → analyzes What/Why, posts output to Issue
  4. /sdd design <issue>    → designs How, posts output to Issue
  5. /sdd implement <issue> → TDD cycle per PR
  6. /sdd test <issue>      → E2E tests and QA

  Interrupted? Run: /sdd resume <issue> → auto-detects stage and continues

Tips:
  - Each stage decomposes into work + parallel review atoms; main session
    stays small so /sdd auto can handle many Issues in one session
  - Each work atom runs Step 0 pre-flight context discovery first
    (CLAUDE.md, git log, similar PRs, target dir) — shift-left prevention
  - Design's Testability section drives implement's test plan (no
    re-derivation; mock strategies inherited from design)
  - 2 reviewer lenses per full stage: completeness, quality
    (adversarial re-spawn deferred to v1.1+; see /sdd review note)
  - TDD steps (Red/Green/Refactor/E2E) each get their own lightweight
    review atom for early bug detection
  - Reviewers can Read/Grep the codebase to verify references
  - In skip-review mode, stages auto-proceed within an orchestrator
    (AI review still runs; only the user-confirmation prompt is skipped)
  - Round 3 review failure triggers a user gate even in skip-review mode
  - Per-Issue depth dials: `sdd:review:deep` (all Opus, /code-review max)
    or `sdd:review:shallow` (cheaper models, /code-review medium)
  - /sdd implement automatically invokes /code-review + /security-review
    at PR Final stage if available; skips gracefully otherwise
  - /sdd test automatically invokes /verify (behavioral verification)
    after AI review; complements manual QA
  - Batch processing options:
      /sdd auto   — runs in this session; full AI review fidelity;
                    stays on Interactive billing
      /sdd batch  — generates a shell script; unattended; close Claude Code OK
                    (uses Agent SDK Credit pool from 2026-06-15)
```
