# HELP

```
SDD (Spec-Driven Development) - AI Collaborative Development Process

Commands:
  /sdd init [lang]       Set up SDD for the current repository (Issue templates, labels)
                         Languages: en (default), ko/korean/한국어, ja/japanese/日本語
  /sdd analyze <issue>   Stage 1: Requirements Analysis (What/Why)
  /sdd design <issue>    Stage 2: Design (How)
  /sdd implement <issue> Stage 3: Implementation with TDD (Red → Green → Refactor)
  /sdd test <issue>      Stage 4: E2E and QA Testing
  /sdd resume <issue>    Auto-detect current stage and continue from where it left off
  /sdd rollback <issue> <stage>  Roll back to a previous stage (analyze, design, implement)
  /sdd status <issue>    Check current progress
  /sdd review <issue>    Re-run AI review on current stage output
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
  - In skip-review mode, stages auto-proceed within an orchestrator
    (AI review still runs; only the user-confirmation prompt is skipped)
  - Batch processing options:
      /sdd auto   — runs in this session; full AI review fidelity;
                    stays on Interactive billing
      /sdd batch  — generates a shell script; unattended; close Claude Code OK
                    (uses Agent SDK Credit pool from 2026-06-15)
```
