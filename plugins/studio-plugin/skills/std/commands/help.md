# HELP

Show this in the repo's language (not initialized: the language the user writes in):

**Studio** — `init`, `config`, `update`, `make`, `source`, `brief`, `script`, `verify`, `board`, `render`, `copy`,
`status`, `resume` and `abandon` work; every other command answers "not implemented yet": it arrives in a later version.

**Setup** — `init` install the harness · `config [key value]` · `update`

**Making a video** — `make <source> --kind <kind>` one video end to end ·
`source|brief|script|verify|board|render|copy <video-id>` one stage; `cast` comes later (for now the voice section of
`make`)

**State** — `status [--unlock]` · `resume <video-id>` · `abandon <video-id> [--lang <l>]` ·
`move <video-id>` (later)

**Platforms & actors** — `platform list|add|remove|refresh` (later) ·
`cast list|add|build|audition` (later)

**Growth & checks** — `review <video-id>` · `evolve` · `rollback` · `audit` (later)

Flow: `init` → `make` → review gates ① script ② audition ③ stills ④ final → commit.
Studio generates files only; a person uploads them.
