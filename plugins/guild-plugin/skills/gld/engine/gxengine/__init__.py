"""guild-plugin engine (`/gld`) — the mechanical part of orchestration (design §1).

The leader-less stage-1 engine reads a procedure and runs it step by step: role
sessions (`claude -p`), named `run` commands under `srt`, engine built-in ops. It
judges only by named kinds and fixed codes (`codes.py`) and by facts it collects
itself (git, exit codes, stream-json).

Standard library only; run with `python3 -I`. Module map and dependency direction:
`../README.md`.
"""

__all__ = []
