"""Who may write Studio's protected records through this library (M1b review Y2).

The guard protects the state files (P-STATE) from the agent's tools but lets Studio's own scripts write them. An agent's
own Python that imports this library would be such a writer too, so every library writer of a protected record —
`store.write`, `stagechecks.write`, `evidence.consume`, `okfile.write`, `machine.write` — refuses unless the process
started as one of Studio's entry scripts (state.py, run_s2v.py, check_commit.py; setup.py from M1c), which call
`enable()` first. Not a security boundary against deliberate forgery (00-plan threat model): it keeps "import the
library and call write" from being an easy way around the guard."""

_ON = [False]


def enable():
    _ON[0] = True


def check(what):
    if not _ON[0]:
        raise RuntimeError("%s is written only by Studio's entry scripts (state.py, run_s2v.py, check_commit.py), not "
                           "from an import" % what)
