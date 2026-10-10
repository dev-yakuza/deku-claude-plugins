# REVIEW — independent audit outside the flow (`/hrd review <topic-id|slug|PR>`)

Runs the same external auditor (`atoms/_auditor.md`) on a pending PR or a published article.
Two purposes: help the human review a PR before `ship`, and measure whether the in-flow review
works — on a healthy flow it finds nothing. Plan §3.3. Read-only on content; it never checks
out branches.

1. Resolve the target: PR number → head ref (`gh pr view <n> --json headRefName,headRefOid`);
   topic id/slug → open PR if any, else the published file on base.
2. Materialize the article for reading without switching branches:
   `git show <ref>:<body path>` into `.claude/herald/memory/review/<id>/article.md` and the
   referenced images likewise.
3. Spawn the auditor with those paths + the charter purpose + hard policies (read-only
   tripwire: hash the materialized files before/after).
4. **Always record**: `HRD signal --kind review-finding --topic <id> --data
   '{"pr": n, "blocker": a, "major": b, "minor": c, "findings": [...]}'`. For a PR also post the
   findings as a PR comment (`gh pr comment <n> --body-file <tmp>`) with the marker
   `<!-- herald:review -->` — `ship` step 3 reads the latest one.
5. Report the findings in `config.language`; BLOCKER on a pending PR → recommend declining or
   fixing before `ship`.
