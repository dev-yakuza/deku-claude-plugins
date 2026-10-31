# Copy guide

How this repository's platform copy (title, description, chapters, hashtags) is written. The distributor reads it.

- The platform's rules come from `.claude/studio/platforms/<platform>.md`; required notices are never left out.
- Every claim in the copy maps to an excerpt of the source.
- Credits: every `credit_line` of the video's CREDITS.yaml appears in the description.
- The copy file is UTF-8 in NFC (composed) form — NFD breaks the checks that find credit lines, chapters and notices,
  and the title length; most compatibility ideographs (U+F900–U+FAFF) are refused too.
- The description's byte size counts each line break inside it as 2 (CRLF — the conservative count, at most 1 byte
  per break over the platform's own); trailing line breaks are not counted.
