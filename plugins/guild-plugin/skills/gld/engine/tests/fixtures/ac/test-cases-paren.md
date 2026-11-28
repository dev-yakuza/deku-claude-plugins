# Test cases — #1797

The written form (P5): every case ends with its tag in parentheses. Prose that names an AC
inside a sentence, such as the sheet rules of AC #2 or a remark (AC #3 is the summary),
covers nothing.

## Row is visible (AC #1)

- C1: the "quiz type" row is found in the quiz screen section. (AC #1)
- C2: the row shows the localized title (same wording as the review screen). (AC #1)

## Sheet

- C3: tapping the row opens the selector sheet. (AC #2)
- C4: the sheet content equals the review screen's sheet, section by section,
  including the select-all row. (AC #2)

## Summary and persistence

| Case | Expected | AC |
|---|---|---|
| C5 | one selection shows its name | (AC #3) |
| C6 | several selections show "N selected" | (AC #3) |
| C7 | after reloading the settings the selection and the summary are unchanged | (AC #4, #3) |
