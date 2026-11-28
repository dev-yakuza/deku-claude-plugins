## Work step rules (developer)

- **Tests.** The full suite is run by the engine's `run` steps after you. Run only the tests of the files you changed or whose behaviour you changed, never the whole suite. Capture the raw runner summary line(s) of what you ran and put them in your result `note`; the engine does not take "done" for green.
- **Never weaken verification.** Do not delete a test file, remove assertions, add skip/focus directives, loosen a tolerance or exclude a test to make something pass. If a test must change, say why in `note`.
- **Golden rule (visual tests).** An expected image or snapshot changes only when the Issue changes that screen on purpose, and only through the repository's own create/update command for the tests you touched. Never rewrite an image, loosen a comparison setting or exclude a visual test to hide a difference the Issue did not intend.
- **Dependencies.** Every import and package you use must really exist (no invented packages); add dependencies only when the step needs them.
- **Commit.** Commit your work with the repository's commit convention, in as many commits as make sense. The tree must be clean when you finish: the engine fails the step on uncommitted changes.
- **Out of scope.** Do not fix what the Issue did not ask for; record it in `discoveries`.
