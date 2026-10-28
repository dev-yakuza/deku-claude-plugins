# External auditor

Status: M1e — used before ① (`commands/verify.md`); the other gates follow with their milestones.

- A reader outside the organization: no persona, no guides, no exemplar scripts. It gets the
  in-house terms list so it can recognise internal information.
- Spawned as `std-auditor` (tools: Read, Grep, Glob). The guard denies its Write · Edit · NotebookEdit, every MCP
  tool and any Bash that is not a reading command (`G-AUDIT`). The producer still compares the state of `studio/`
  and `.claude/studio/` before and after and discards the result if anything changed.
- When: before ① (script), before ③ (stills, public videos only), before ④a (thumbnail,
  chapters, frames), after copy, and before a generated character candidate is chosen.
- It cannot hear audio; number and negation mismatches in the heard text are checked by
  `check_tts` instead.

<!-- studio:result-contract -->
> Every spawned role ends its reply with exactly one result line:
> `>>> RESULT <<< <STATUS>: <one-line summary>` where `<STATUS>` is one of
> `DONE` · `DONE_WITH_CONCERNS` · `BLOCKED` · `NEEDS_CONTEXT` · `FAIL`.
> `DONE_WITH_CONCERNS` lists each concern on its own line before the result line.
> `BLOCKED` and `NEEDS_CONTEXT` say what is missing; the producer decides, never the role.
<!-- /studio:result-contract -->
