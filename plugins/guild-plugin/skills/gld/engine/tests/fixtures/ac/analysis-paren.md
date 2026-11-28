# Analysis — #1797

type: feature
size: small
risk: low
split: none
prerequisite: none

## Interpretation

Chosen: add a "quiz type" row to the settings screen that reuses the existing selector sheet.
AC #2 keeps the sheet as it is; nothing here is a test-case tag.

## Acceptance criteria

- AC #1: The settings screen "quiz screen" section shows a "quiz type" row. (must)
- AC #2: Tapping the row opens the existing selector sheet; its sections and the select-all
  behaviour are the same as when opened from the review screen. (must)
    - detail: the sheet is not copied
- AC #3: The summary on the right reflects the current selection and updates when it changes (no extra tap). (must)
- AC #4: The selection survives an app restart. (should)

## Requirement map

| Issue requirement | AC |
|---|---|
| Show the quiz type in settings | AC #1 |
| Reuse the selector sheet | AC #2, #3 |
| Keep the choice after restart | AC #4 |

## Assumptions

- The settings screen may import the review screen's selector (the layering rule is still a draft).
- The summary label for "all" is decided in design.
