# External auditor

Status: contract only (M0); prompts arrive with M1.

- A reader outside the organization: no persona, no guides, no exemplar scripts. It gets the
  in-house terms list so it can recognise internal information.
- Spawned with a read-only agent type; the producer compares the hashes of `studio/` and
  `.claude/studio/` before and after and discards the result if anything changed.
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
