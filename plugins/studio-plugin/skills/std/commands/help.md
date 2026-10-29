# HELP

Show this in the repo's language (not initialized: the language the user writes in):

**Studio is in development (0.0.x)** — `init`, `config`, `update`, `source`, `brief`, `script`, `verify` and `make`
(up to gate ②) work; every other command answers "not implemented yet" and names the milestone that brings it.

**Setup** — `init` install the harness (M1) · `config [key value]` (M1) · `update` (M1)

**Making a video** — `make <source> --kind <kind>` one video end to end (M1) ·
`source|brief|script|verify|cast|board|render|copy <video-id>` one stage (M1; `cast` M3a)

**State** — `status [--unlock]` · `resume <video-id>` · `abandon <video-id> [--lang <l>]` ·
`move <video-id>` (M1)

**Platforms & actors** — `platform list|add|remove|refresh` (M2) ·
`cast list|add|build|audition` (M3a–M3b)

**Growth & checks** — `review <video-id>` · `evolve` · `rollback` · `audit` (M4)

Flow (when built): `init` → `make` → review gates ① script ② audition ③ stills ④ final → commit.
Studio generates files only; a person uploads them.
