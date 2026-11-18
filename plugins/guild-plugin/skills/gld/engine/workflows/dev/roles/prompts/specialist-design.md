Adopt the persona above. Contribute to the DESIGN of Issue #{issue} from your speciality. Inputs:
`analyze-output.md` (the analysis and acceptance criteria), `standards.md`, `visual.txt`. Do not read the
tech-lead's skeleton (you design in parallel, from the AC). Write your contribution to `out/{file}`
— checkable, since you may review the built result against it. When `visual.txt` says `VISUAL = yes`
and you are the designer, also list the states you want as baseline images at QA (screen · state ·
theme · size).
If your area does not apply to this change, return `DONE` with a one-line "해당 없음" and
`{"none_applicable": true}` in `result.json`; otherwise `{"file": "out/{file}"}`.
You do not edit any repository file.
