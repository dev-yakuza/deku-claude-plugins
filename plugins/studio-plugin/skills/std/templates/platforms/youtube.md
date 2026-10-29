---
platform: youtube
checked: "{{CHECKED_DATE}}"
outputs:
  - name: youtube
    aspect: "16:9"
    max_duration: null
---
# YouTube

**Draft written by the agent (M1h) — a person checks it against YouTube's own help, fixes what differs, and fills
`checked` above with the date (U-M1h).** Until then `validate_copy.py` refuses every copy for this platform. Only a
person changes this file (the guard protects it; a change shows up in the harness commit question).

<!-- studio:rules -->
```json
{
  "title_max": 100,
  "description_max": 5000,
  "hashtags_max": 15,
  "required": ["This video's narration is AI-synthesized speech."]
}
```
<!-- /studio:rules -->

## Copy (`studio/copy/<video>/<lang>/youtube.md`)
- Frontmatter: `title` (at most 100 characters; YouTube's limit) and `hashtags` (a JSON list on one line; at most 15 —
  YouTube ignores all hashtags of a video that has more; the first three show above the title).
- Description (the body, at most 5000 characters): what the video covers, then the chapters exactly as the render's
  `.chapters.txt` (`0:00 <title>` lines; the first must be 0:00, at least three chapters of 10 s or more for YouTube to
  show them), the `credit_line` of every CREDITS entry, and every required notice above.
- No home paths, no in-house terms.

## Altered or synthetic content
- YouTube asks creators to disclose realistic altered or synthetic content in YouTube Studio when uploading. A narrated
  explainer with an AI voice may need the disclosure; the person decides at upload (the required notice above keeps it
  visible in the description as well).

## Upload checklist (the person)
- Upload the `.mp4`, set the thumbnail (`.thumbnail.png`) and the subtitles (`.srt`).
- Paste the title, description and hashtags from the copy.
- Answer the altered or synthetic content question in YouTube Studio.
- Check the video's visibility and audience settings ("made for kids" or not).
