# Cast and actors

Status: contract only (M0). Casting arrives with M3a, actor making with M3b, acting with M3c.

- **Casting** (per video) and **actor making** (new actors in the roster) are separate.
  Actor making runs outside `make` (`/std cast add|build`) and commits on its own.
- The default narrator is an engine's built-in speaker registered by `init`; a single-narrator
  video without acting attributes needs no casting director.
- Voices kept in the repository: designed voices, their trained speakers, engine built-in
  speakers and their reference clips only — no cloned human voices.
- Character art comes from script2video (`s2v character …`) or from pictures a person
  provides with credits; Studio never generates, cuts or inspects images itself.
- Every person's confirmation in actor making is recorded with `state.py approve-actor`
  before the script2video command it allows.
