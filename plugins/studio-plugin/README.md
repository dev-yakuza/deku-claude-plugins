# Studio Plugin

> **In development (0.0.x).** Studio is not in the marketplace yet and its commands answer
> "not implemented yet". Do not use it on a real repository.

A **per-repo video production organization** for Claude Code. Studio installs a production
harness into a repository; a team of role agents specialized to that repo turns writing that
already exists there (blog posts, docs, app pages) into narrated videos with
[script2video](https://github.com/dev-yakuza/script2video), and drafts the text that goes
with each video on the platforms you choose.

[한국어](./README.ko.md) · [日本語](./README.ja.md)

## Concepts

- **The source is the writing that already exists.** Every fact in a video (narration, on-screen
  text, title, thumbnail, chapters, platform copy) comes from the source and is checked against it.
- **Four human review gates** — ① script ② audition ③ stills ④ final (④a video · ④b copy).
  Agents never approve on a person's behalf.
- **Generate, never publish** — Studio makes the files; a person uploads them.
- **script2video does the rendering** — Studio plans, checks, asks and commits.

## Try it locally

```bash
claude --plugin-dir plugins/studio-plugin
```

Then `/std help`. Requires script2video 0.12.1 or later (set up later by `/std init`).

## License

MIT
