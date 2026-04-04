# SDD Plugin (Spec-Driven Development)

AI collaborative development process for Claude Code. Manages the full development lifecycle through GitHub Issues with a structured process.

## Installation

```bash
claude /plugin marketplace add dev-yakuza/sdd-plugin
claude /plugin install sdd-plugin@sdd-plugin
```

## Quick Start

```bash
# 1. Set up SDD in your repository (choose language)
/sdd init           # English (default)
/sdd init ko        # Korean
/sdd init ja        # Japanese

# 2. Create a GitHub Issue using SDD templates

# 3. Start the development process
/sdd analyze 123     # Requirements analysis (What/Why)
/sdd design 123      # Design (How)
/sdd implement 123   # TDD implementation
/sdd test 123        # E2E and QA testing
```

## Commands

| Command | Description |
|---------|-------------|
| `/sdd init [lang]` | Set up Issue templates and labels. Languages: `en` (default), `ko`/`korean`/`한국어`, `ja`/`japanese`/`日本語` |
| `/sdd analyze <issue>` | Stage 1: Requirements Analysis (What/Why) |
| `/sdd design <issue>` | Stage 2: Design (How) |
| `/sdd implement <issue>` | Stage 3: TDD Implementation |
| `/sdd test <issue>` | Stage 4: E2E/QA Testing |
| `/sdd status <issue>` | Check current progress |
| `/sdd review <issue>` | AI review of current output |
| `/sdd help` | Show usage |

## Process

```
1. Requirements (What/Why) → 2. Design (How) → 3. Implement (TDD) → 4. Test (E2E/QA)
```

### Stage 1: Requirements Analysis (What / Why)

Focus on **What** to build and **Why** it's needed. Technical implementation (How) is NOT discussed here.

**Flow:** ① Input → ② AI Analysis → ③ Output → ④ AI Review → ⑤ User Review → Next Stage

### Stage 2: Design (How)

Define **How** to implement based on the requirements.

**Flow:** ① Input → ② AI Design → ③ Output → ④ AI Review → ⑤ User Review → Next Stage

### Stage 3: Implementation - TDD Cycle

Execute per PR with the TDD cycle:

```
3-0. PR Kickoff: Test & Implementation Plan
3-1. Red: Write Failing Tests
3-2. Green: Minimal Implementation
3-3. Refactor: Improve Code
3-4. PR Creation & Code Review
→ Repeat for next PR
```

Test scope: Unit tests / UI tests

### Stage 4: Testing

- E2E automated tests (AI writes code, runs tests)
- QA checklist (AI creates, human executes)
- Regression testing

## GitHub Integration

All outputs are stored in GitHub — no separate file management needed.

| Data | Location |
|------|----------|
| Requirements (input) | Issue body |
| Analysis output | Issue comment |
| Design output | Issue comment |
| Current stage | Issue label |
| Implementation | Pull Request |
| Test results | Issue comment |

### Labels

| Label | Stage |
|-------|-------|
| `sdd:analyze` | Requirements Analysis |
| `sdd:design` | Design |
| `sdd:implement` | Implementation |
| `sdd:test` | Testing |
| `sdd:done` | Complete |

## License

MIT
