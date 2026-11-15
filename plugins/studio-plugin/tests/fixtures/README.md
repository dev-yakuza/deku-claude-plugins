# Fixtures

Synthetic only: no content from a real repository, site or organization. Measured Claude Code
hook inputs and transcript excerpts (M0d-0) go under `claude-code/<version>/`, anonymized.

`sourced/`: the `bin/activate` files `python3 -m venv` writes (CPython 3.9 and 3.12), the venv's folder replaced by
`__VENV__` and its prompt name by `.venv` — the guard reads a sourced file in the shell that runs it (test_guard_backstop.SourceWalk).
