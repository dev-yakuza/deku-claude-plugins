---
name: pr-size-guard
description: "Enforce pull request size limits defined in your team's CONTRIBUTING.md. Use when opening or reviewing a PR to verify it stays within the 400-line diff limit and contains no more than 5 changed files, as required by the team's review policy."
argument-hint: "[pr-number]"
user-invocable: true
---

# PR Size Guard

Checks a pull request against this team's size limits before review.

## Team Policy

Per `CONTRIBUTING.md` §3.2 (last updated in the repository, not here):
- Diff size: ≤ 400 lines changed (additions + deletions)
- File count: ≤ 5 files changed
- Exceptions require a `size-exception` label from a team lead

These limits exist because our post-incident review showed PRs over 400 lines had a 3× higher defect escape rate in Q3.

## Usage

Run with a PR number to check it:

```
/pr-size-guard 123
```

**Example — passing PR:**
- Input: PR #88 with 210 lines changed across 3 files
- Output: ✓ PR #88 passes size policy (210 lines, 3 files)

**Example — failing PR:**
- Input: PR #91 with 620 lines changed across 8 files
- Output: ✗ PR #91 exceeds size policy (620 lines > 400, 8 files > 5). Request size-exception label or split the PR.

## Steps

1. Run `gh pr view <pr-number> --json additions,deletions,changedFiles`
2. Compute total lines changed = additions + deletions
3. If total > 400 OR changedFiles > 5:
   - Report the exact numbers
   - Suggest splitting by logical concern or requesting the exception label
4. If within limits: confirm with counts

## Limitations

- Does not check binary file sizes
- `size-exception` label bypass must be verified by a human reviewer
- Only works in repositories where `gh` CLI is authenticated
