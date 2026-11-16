# MJ-DWC — did the role read an input only in part? (J-X2, H§C:292)
The role ended `DONE_WITH_CONCERNS`. `partial_read` only when its concern says it could not read an
input file whole (cut off, too large, page missing). A concern about the work itself (an AC gap, a
value left out, E2E not run) is `other`. `unsure` is read as `partial_read` (one re-dispatch).
