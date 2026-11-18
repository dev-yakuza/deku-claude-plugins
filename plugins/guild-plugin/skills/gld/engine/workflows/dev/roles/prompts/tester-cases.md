Adopt the tester persona above. Issue #{issue}: read ONLY the acceptance criteria in `ac.md` — you are not given the
design skeleton and must not look for it (bias-free test design). Write test cases (normal + edge +
failure paths) to `out/test-cases.md`; name each case's AC (`AC #n`) — every AC id in `ac.md` must
appear. Describe observable behaviour, never internal structure. An AC tagged `(safety net)` pins
behaviour the code already has: its case passes on today's code (not red-first) and keeps the tag.

`visual.txt` says `VISUAL = yes|no`. When `yes`, add after the behaviour cases a `## ` heading in the
repository's language followed by the marker line `<!-- guild:visual-cases -->` on its own line (never
translated), then one row per baseline image — screen/component · state · theme · viewport/size · AC #n
(theme "all" when the matcher writes several). A visual case never replaces a behaviour case. When `no`,
write no visual section.
You do not edit any repository file. In `result.json` give `{"covers": []}`.
