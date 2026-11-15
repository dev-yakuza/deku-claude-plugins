---
platform: internal
audience: internal
checked: "{{CHECKED_DATE}}"
outputs:
  - name: internal
    aspect: "16:9"
    max_duration: null
sources:
---
# In-house sharing

**The organization's own rules for sharing an internal video with its members (no outside help page) — a person
checks them (`/std platform refresh internal`), which fills `checked` above.** Until then `validate_copy.py` refuses
every copy for this platform. Only a person changes this file (the guard protects it; a change shows up in the harness
commit question).

<!-- studio:rules -->
```json
{
  "title_max": 100,
  "description_max_chars": 1000,
  "hashtags_max": 0,
  "required": ["이 영상의 내레이션은 AI 합성 음성입니다."],
  "chapters": "required",
  "link": "body"
}
```
<!-- /studio:rules -->

## Copy (`internal.md` in the `copy:` folder `state.py next` prints)
- Frontmatter `title` (at most 100 characters) and `hashtags: []` (none).
- The description is the share message: a short summary (at most 1000 characters) of what the video covers, the
  chapters exactly as the render's `.chapters.txt`, every `credit_line` of CREDITS.yaml and the required notice.
- In-house terms are allowed (the video stays inside the organization); home paths are not.

## Sharing checklist (the person)
- Share the `.mp4` from the `out:` folder where the organization keeps internal material (it is never committed).
- Paste the title and the share message from the copy.
