---
name: changelog-generator
description: "Generate a changelog from git history. Use when you want to document changes."
argument-hint: "[tag]"
user-invocable: true
---

# Changelog Generator

Generates a formatted CHANGELOG.md entry from git commit history.

## Steps

1. Run `git log <tag>..HEAD --oneline` to get commits since the given tag
2. Group commits by conventional commit prefix:
   - `feat:` → Features
   - `fix:` → Bug Fixes
   - `chore:`, `refactor:`, `docs:` → Other Changes
3. Format as Markdown under `## [Unreleased]`
4. Append to the top of CHANGELOG.md

## Notes

Works best with conventional commits. Non-conventional messages are grouped under "Other Changes."
