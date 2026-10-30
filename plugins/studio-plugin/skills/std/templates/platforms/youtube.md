---
platform: youtube
checked: "{{CHECKED_DATE}}"
outputs:
  - name: youtube
    aspect: "16:9"
    max_duration: null
---
# YouTube

**Drafted by the agent (M1h) and revised against the sources listed at the end — a person checks it against
YouTube's own help, fixes what differs, and fills `checked` above with the date (U-M1h).** Until then `validate_copy.py` refuses every copy for this platform. Only a
person changes this file (the guard protects it; a change shows up in the harness commit question).

<!-- studio:rules -->
```json
{
  "title_max": 100,
  "description_max_bytes": 5000,
  "hashtags_max": 15,
  "required": ["이 영상의 내레이션은 AI 합성 음성입니다."]
}
```
<!-- /studio:rules -->

## Copy (`studio/copy/<video>/<lang>/youtube.md`)
- Frontmatter: `title` (at most 100 characters — the Data API's `snippet.title`) and `hashtags` (a JSON list on one
  line, each `#word` with no spaces).
- Hashtags: **at most 15 is Studio's own limit**, stricter than YouTube's. YouTube itself ignores all of a video's
  hashtags only when there are more than 60, and shows up to 3 of them by the title.
- Description (the body): **at most 5000 bytes in UTF-8**, not characters — the Data API's `snippet.description`
  limit, stricter than the help page's 5,000 characters. Korean is about 3 bytes a character, so roughly 1,660 Korean
  characters. It holds what the video covers, then the chapters exactly as the render's `.chapters.txt` (`0:00 <title>`
  lines: the first starts at 0:00, at least three in ascending order, each at least 10 seconds, for YouTube to show
  them), the `credit_line` of every CREDITS entry, and every required notice above.
- No `<` or `>` in the title or the description (the Data API forbids them; `validate_copy.py` refuses them).
- No home paths, no in-house terms.

## Altered or synthetic content
- YouTube's disclosure in YouTube Studio is for realistic content that could mislead viewers — for example making a
  real person appear to say or do something they did not.
- Not needing it: cloning one's own voice for voiceovers, and production help such as writing the script.
- A generic AI narrator for an explainer most likely needs no disclosure, but the person decides at upload.
- The required notice above is Studio's own transparency rule, independent of that disclosure.

## Upload checklist (the person)
- Upload the `.mp4`, set the thumbnail (`.thumbnail.png`) and the subtitles (`.srt`).
- Paste the title, description and hashtags from the copy.
- Answer the altered or synthetic content question in YouTube Studio.
- Check the video's visibility and audience settings ("made for kids" or not).

## Sources (checked 2026-10-30)
- https://developers.google.com/youtube/v3/docs/videos (`snippet.title`, `snippet.description`)
- https://support.google.com/youtube/answer/57407
- https://support.google.com/youtube/answer/6390658
- https://support.google.com/youtube/answer/9884579
- https://support.google.com/youtube/answer/14328491
