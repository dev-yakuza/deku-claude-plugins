---
platform: youtube-shorts
audience: public
checked: "{{CHECKED_DATE}}"
outputs:
  - name: shorts
    aspect: "9:16"
    max_duration: 180
    shot: full
sources:
  - https://support.google.com/youtube/answer/10059070
  - https://developers.google.com/youtube/v3/docs/videos
  - https://support.google.com/youtube/answer/14328491
---
# YouTube Shorts

**Drafted by the agent from the sources above — a person checks it against YouTube's own help (`/std platform
refresh youtube-shorts`), which fills `checked` above.** Until then `validate_copy.py` refuses every copy for this
platform. Only a person changes this file (the guard protects it; a change shows up in the harness commit question).

<!-- studio:rules -->
```json
{
  "title_max": 100,
  "description_max_bytes": 5000,
  "hashtags_max": 15,
  "required": ["이 영상의 내레이션은 AI 합성 음성입니다."],
  "chapters": "none",
  "link": "body"
}
```
<!-- /studio:rules -->

## Copy (`youtube-shorts.md` in the `copy:` folder `state.py next` prints)
- A Short is an upload like any YouTube video: frontmatter `title` (at most 100 characters) and `hashtags` (a JSON
  list on one line, each `#word`); the description at most 5000 bytes in UTF-8, as for YouTube.
- No chapters: a Short shows none, so the copy carries no chapter lines.
- Every `credit_line` of CREDITS.yaml and every required notice above, word for word; the source link line when the
  producer gives one.
- No `<` or `>`, no home paths, no in-house terms.

## Length and shape
- Vertical (9:16) or square, at most 3 minutes (`max_duration: 180`): a longer upload is a regular video.
- The platform's buttons cover the bottom and the right edge: screen text and the logo stay clear of them.

## Altered or synthetic content
- As for YouTube: the disclosure is for realistic content that could mislead viewers; a generic AI narrator most
  likely needs none, but the person decides at upload. The required notice above is Studio's own rule.

## Upload checklist (the person)
- Upload the vertical `.mp4` as a Short; choose the thumbnail frame in the upload screen.
- Paste the title, description and hashtags from the copy.
- Answer the altered or synthetic content question.
