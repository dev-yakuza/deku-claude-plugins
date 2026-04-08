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
  /sdd review <issue>    AI review of current stage output
  /sdd help              Show this help message

Workflow:
  1. /sdd init [lang]       → set up repository (choose language for templates)
  2. Create an Issue using SDD templates
  3. /sdd analyze <issue>   → analyzes What/Why, posts output to Issue
  4. /sdd design <issue>    → designs How, posts output to Issue
  5. /sdd implement <issue> → TDD cycle per PR
  6. /sdd test <issue>      → E2E tests and QA

  Interrupted? Run: /sdd resume <issue> → auto-detects stage and continues
```
